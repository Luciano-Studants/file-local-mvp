"""Tray-resident Windows UI with a Shift-triggered Explorer radial menu."""
from __future__ import annotations
import os
import subprocess
import sys
import time
from collections import deque
from threading import Event
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

from engine import VERSION, OPERATIONS, COLLAGE_MAX, ConversionError, batch_rename_options, batch_target_ok, create_batch_folder, loss_report
from capabilities import describe_capabilities, probe_capabilities
from radial_menu import RadialAction, RadialMenu, actions_for_file, actions_for_selection
from runner import Cancelled, run_job, take_notes
from windows_bridge import key_is_down, selected_paths_from_explorer, shift_is_down
from global_hotkey import GlobalHotkey, parse_hotkey
from settings import Settings, load_settings, save_settings
from ipc import PathServer
from file_actions import format_path_lines, terminal_directory, validate_selection
from shelf import FileShelf
import tool_registry
from workspace_panel import FeaturePanel

LABELS = {
    'PNG': 'Imagem → PNG',
    'JPEG': 'Imagem → JPEG',
    'WEBP': 'Imagem → WebP',
    'TIFF': 'Imagem → TIFF',
    'BMP': 'Imagem → BMP',
    **{spec.target: spec.title for spec in tool_registry.IMAGE_TOOLS},
    'Image → PDF': 'Imagem → PDF',
    'PDF → Text': 'Extrair texto do PDF', 'Extract PDF Images': 'Extrair imagens embutidas do PDF',
    'PDF → Images': 'Salvar páginas do PDF como imagens',
    'Redact PDF': 'Tarjar conteúdo do PDF', 'Fill PDF': 'Preencher e assinar o PDF', 'Protect PDF': 'Proteger o PDF com senha', 'Unprotect PDF': 'Remover a senha do PDF',
    'Stamp PDF': 'Numerar e carimbar o PDF', 'Compress PDF': 'Comprimir PDF', 'Convert Audio': 'Converter áudio', 'Audio Tags': 'Editar etiquetas do áudio', 'Audio Channels': 'Mudar os canais do áudio', 'Audio Trim': 'Cortar o áudio',
    'Clean PDF': 'Cópia limpa do PDF (sem metadados)',
    'PDF OCR → PDF': 'Reconhecer texto do PDF digitalizado (PDF pesquisável)', 'PDF OCR → Text': 'Reconhecer texto do PDF digitalizado (texto)',
    'Merge PDFs': 'Unir PDFs',
    'Split PDF': 'Dividir e extrair páginas do PDF', 'Organize PDF': 'Organizar páginas do PDF',
}


VK_MIDDLE_BUTTON, VK_CONTROL, VK_ALT = 0x04, 0x11, 0x12


def middle_click_trigger(enabled: bool, shift_down: bool, middle_down: bool, was_down: bool) -> bool:
    """Shift + botão do meio (só na borda de descida) abre a roda de ferramentas, se a opção estiver ligada."""
    return bool(enabled and shift_down and middle_down and not was_down)


def chord_in_progress(ctrl_down: bool, alt_down: bool, hotkey_key_down: bool) -> bool:
    """Ctrl/Alt junto com Shift, ou a tecla do atalho global pressionada, indicam um atalho em andamento: não abrir a roda por Shift."""
    return bool(ctrl_down or alt_down or hotkey_key_down)


def human_size(size: int) -> str:
    """Tamanho em português («1,2 MB») para o centro da roda."""
    if size < 1024 * 1024:
        return f'{max(1, round(size / 1024)):,} KB'.replace(',', '.')
    return f'{size / 1024 / 1024:,.1f} MB'.replace('.', ',')


class ConversionTask(QThread):
    completed = Signal(bool, str, list)

    def __init__(self, paths: list[str], target: str, options: dict):
        super().__init__()
        self.paths = paths
        self.target = target
        self.options = options
        self.cancel_event = Event()

    def request_cancel(self):
        self.cancel_event.set()

    def run(self):
        try:
            outputs = run_job({'paths': self.paths, 'target': self.target, **self.options}, cancel=self.cancel_event)
            self.completed.emit(True, 'Concluído', outputs)
        except Cancelled:
            self.completed.emit(False, 'Cancelado pelo usuário; nenhuma saída parcial foi publicada.', [])
        except Exception as error:
            self.completed.emit(False, str(error), [])


class JobController(QObject):
    job_finished = Signal(bool, str, list, list, str)
    queue_changed = Signal()
    MAX_QUEUED_JOBS = 100

    def __init__(self, tray=None, capabilities=None):
        super().__init__()
        self.tray = tray
        self.panel = None
        self.capabilities = capabilities if capabilities is not None else probe_capabilities()
        self.worker: ConversionTask | None = None
        self.active_job: dict | None = None
        self.pending_jobs = deque()
        self._batch_dirs = set()                # pastas numeradas criadas por «salvar numa pasta»; as que ficarem vazias são removidas
        self.last_report: list[str] = []

    def notify(self, title: str, message: str):
        if self.tray and self.tray.isVisible():
            self.tray.showMessage(title, message, QSystemTrayIcon.MessageIcon.Information, 5000)
        elif self.panel:
            self.panel.status.setText(message)

    def start_job(self, paths: list[str], target: str, options: dict | None = None):
        options = dict(options or {})
        if target not in OPERATIONS:
            self.notify('Arquivo Local', 'Operação desconhecida; job não enfileirado.')
            return False
        capability_key = 'images' if target in {'JPEG', 'PNG', 'WEBP', 'TIFF', 'BMP', 'Image → PDF', *tool_registry.TARGETS} else 'pdf'
        available, reason = self.capabilities.get(capability_key, (False, 'Capacidade não verificada.'))
        if not available:
            self.notify('Arquivo Local', f'Operação indisponível: {reason}')
            return False
        if not paths:
            self.notify('Arquivo Local', 'Escolha pelo menos um arquivo.')
            return False
        if len(paths) > 100 or (target == 'Merge PDFs' and len(paths) < 2) or (target == 'Organize PDF' and len(paths) != 1) or (target == 'Collage → PNG' and not 2 <= len(paths) <= COLLAGE_MAX) or (target == 'Images → One PDF' and len(paths) < 2) or (target in tool_registry.BY_TARGET and tool_registry.BY_TARGET[target].single_file and len(paths) != 1):
            self.notify('Arquivo Local', 'Quantidade de arquivos incompatível com esta operação.')
            return False
        integer_options = tool_registry.all_int_options()
        string_options = tool_registry.all_str_options()
        path_options = tool_registry.all_path_options()
        regions = options.get('redact_regions')
        regions_ok = regions is None or (isinstance(regions, list) and len(regions) <= 50 and all(isinstance(r, list) and len(r) == 4 and all(type(v) is int for v in r) for r in regions))
        shapes = options.get('shape_items')
        shape_ints = ('x', 'y', 'w', 'h', 'thickness', 'fill', 'dir')
        shapes_ok = shapes is None or (isinstance(shapes, list) and len(shapes) <= 50 and all(
            isinstance(item, dict) and set(item) <= {'kind', 'color', *shape_ints} and isinstance(item.get('kind'), str) and len(item['kind']) <= 16
            and isinstance(item.get('color', ''), str) and len(item.get('color', '')) <= 7 and all(type(item[key]) is int for key in shape_ints if key in item) for item in shapes))
        if not regions_ok or not shapes_ok:
            self.notify('Arquivo Local', 'Opções do job inválidas.')
            return False
        if any((key in integer_options and type(value) is not int) or
               (key in string_options and (not isinstance(value, str) or len(value) > 200)) or
               (key in path_options and (not isinstance(value, str) or len(value) > 1024)) or
               key not in integer_options | string_options | path_options | tool_registry.all_list_options() for key, value in options.items()):
            self.notify('Arquivo Local', 'Opções do job inválidas.')
            return False
        ranges = options.get('merge_ranges')
        if ranges is not None and not (target == 'Merge PDFs' and isinstance(ranges, list) and len(ranges) == len(paths) and all(isinstance(r, str) and len(r) <= 200 for r in ranges)):
            self.notify('Arquivo Local', 'Opções do job inválidas.')
            return False
        plan = options.get('organize_pages')
        if plan is not None and not (target == 'Organize PDF' and isinstance(plan, list) and 1 <= len(plan) <= 200 and all(isinstance(x, str) and len(x) <= 7 for x in plan)):
            self.notify('Arquivo Local', 'Opções do job inválidas.')
            return False
        for key, limit, owner, size in (('redact_areas', 300, 'Redact PDF', 64), ('redact_terms', 20, 'Redact PDF', 64), ('form_values', 200, 'Fill PDF', 1300), ('sign_areas', 10, 'Fill PDF', 64)):
            value = options.get(key)
            if value is not None and not (target == owner and isinstance(value, list) and len(value) <= limit and all(isinstance(x, str) and len(x) <= size for x in value)):
                self.notify('Arquivo Local', 'Opções do job inválidas.')
                return False
        to_folder = options.pop('to_folder', '') == 'on'
        if target in ('Merge PDFs', 'Collage → PNG', 'Images → One PDF'):
            jobs = [{'paths': list(paths), 'target': target, 'options': dict(options)}]
        else:
            jobs = [{'paths': [path], 'target': target, 'options': dict(options)} for path in paths]
        batch_dir = None
        if to_folder and len(jobs) > 1 and batch_target_ok(target):
            try:
                batch_dir = create_batch_folder(Path(paths[0]).parent)
            except (ConversionError, OSError) as error:
                self.notify('Arquivo Local', str(error))
                return False
            options = batch_rename_options(options, len(jobs))
            for job in jobs:
                job['options'] = {**options, 'output': str(batch_dir)}
            self._batch_dirs.add(batch_dir)
            self.notify('Arquivo Local', f'{len(jobs)} imagens serão salvas numeradas na pasta «{batch_dir.name}».')
        if str(options.get('rename_pattern') or '').strip():
            start = options.get('rename_start', 1)
            for position, job in enumerate(jobs):
                job['options']['rename_n'] = min(9999999, start + position)       # cada arquivo da fila recebe o próximo número
        if len(self.pending_jobs) + (1 if self.active_job else 0) + len(jobs) > self.MAX_QUEUED_JOBS:
            self.notify('Arquivo Local', 'Fila cheia (100 jobs); aguarde antes de adicionar mais.')
            self._cleanup_batch_dirs()
            return False
        self.pending_jobs.extend(jobs)
        self.queue_changed.emit()
        if self.worker is None:
            self._start_next()
        else:
            self.notify('Arquivo Local', f'{len(jobs)} job(s) adicionado(s) à fila ({len(self.pending_jobs)} aguardando).')
        return True

    def _start_next(self):
        if self.worker is not None or not self.pending_jobs:
            return
        self.active_job = self.pending_jobs.popleft()
        self.worker = ConversionTask(self.active_job['paths'], self.active_job['target'], self.active_job['options'])
        self.worker.completed.connect(self._on_worker_result)
        self.worker.finished.connect(self._on_worker_stopped)
        self.queue_changed.emit()
        self.worker.start()

    def _on_worker_result(self, success: bool, message: str, outputs: list):
        job = self.active_job
        if job is None:
            return
        paths, target = job['paths'], job['target']
        try:
            self.last_report = loss_report(paths, target, job.get('options')) if success else []
        except Exception:
            self.last_report = []
        notes = take_notes()
        if success and notes:
            self.last_report = [*notes, *self.last_report]          # avisos medidos durante o job (fase, clipping) vêm primeiro
        self.job_finished.emit(success, message, outputs, paths, target)
        if success:
            detail = Path(outputs[0]).name if outputs else 'concluído'
            self.notify('Arquivo Local', f'Concluído: {detail}')
        elif message.startswith('Cancelado'):
            self.notify('Arquivo Local', message)
        else:
            self.notify('Arquivo Local', 'Não foi possível concluir. Abra o painel para ver o detalhe.')

    def _cleanup_batch_dirs(self):
        """Remove pastas numeradas que ficaram vazias (tudo falhou ou foi cancelado); pasta com arquivos ou ainda em uso nunca é tocada."""
        in_use = {str(job['options'].get('output')) for job in [*self.pending_jobs, *([self.active_job] if self.active_job else [])]}
        for folder in list(self._batch_dirs):
            if str(folder) in in_use:
                continue
            try:
                folder.rmdir()
            except OSError:
                pass
            if not folder.exists() or any(folder.iterdir()):
                self._batch_dirs.discard(folder)

    def _on_worker_stopped(self):
        worker = self.worker
        self.worker = None
        self.active_job = None
        if worker:
            worker.deleteLater()
        self._cleanup_batch_dirs()
        self.queue_changed.emit()
        self._start_next()

    def cancel_current(self) -> bool:
        if not self.worker or not self.worker.isRunning():
            return False
        self.worker.request_cancel()
        self.notify('Arquivo Local', 'Cancelamento solicitado; a tarefa atual está sendo interrompida.')
        return True

    def clear_pending(self) -> int:
        count = len(self.pending_jobs)
        self.pending_jobs.clear()
        self._cleanup_batch_dirs()
        self.queue_changed.emit()
        return count


class TrayApplication:
    HOLD_SECONDS = 0.38

    def __init__(self, app: QApplication):
        self.app = app
        self.controller = JobController()
        self.panel = FeaturePanel(self.controller)
        self.controller.panel = self.panel
        self.shelf = FileShelf()
        self.radial: RadialMenu | None = None
        self.radial_mode = ''
        self.radial_paths: list[str] = []
        self.shift_started: float | None = None
        self.activated_for_hold = False
        self.suppress_shift_until_release = False
        self.tray_menu = None
        self.status_action = None
        self.settings = load_settings()
        self._middle_was_down = False
        self.tray = self._create_tray()
        self.controller.tray = self.tray

        self.poller = QTimer()
        self.poller.setInterval(35)
        self.poller.timeout.connect(self.poll_shift)
        self.poller.start()
        self.global_hotkey = GlobalHotkey(self.app, self.open_global_radial, self.settings.hotkey)
        self.hotkey_registered = self.global_hotkey.start()
        self._publish_hotkey_state()
        self.ipc = PathServer()
        self.ipc.paths_received.connect(self.on_paths_received)
        self.ipc_listening = self.ipc.start()
        self.panel.settings_button.clicked.connect(self.open_settings)
        self.panel.refresh_capabilities_view()
        if not self.hotkey_registered and os.name == 'nt' and self.tray:
            self.tray.showMessage(
                'Arquivo Local',
                f'{self.global_hotkey.hotkey} não foi registrado (pode haver conflito). As conversões por Shift continuam disponíveis; escolha outro atalho em Atalhos.',
                QSystemTrayIcon.MessageIcon.Warning,
                7000,
            )
        if not self.tray:
            self.panel.show()

    def _publish_hotkey_state(self):
        name = self.global_hotkey.hotkey
        self.controller.capabilities['shift_f9'] = (
            self.hotkey_registered,
            f'Atalho global {name} registrado.' if self.hotkey_registered else 'Não registrado; pode haver conflito com outro aplicativo.',
        )
        text = f'Shift: conversões • {name}: ferramentas dos arquivos'
        if self.status_action is not None:
            self.status_action.setText(text)
        if getattr(self, 'tray', None):
            self.tray.setToolTip(f'Arquivo Local — selecione um arquivo e segure Shift ({name} abre as ferramentas)')
        self.panel.refresh_capabilities_view()

    def _switch_hotkey(self, normalized: str) -> bool:
        """Troca o atalho global. No Windows registra de verdade (pode falhar se outro programa já usa a combinação)."""
        if os.name == 'nt':
            return self.global_hotkey.restart(normalized)
        self.global_hotkey.modifiers, self.global_hotkey.vk, self.global_hotkey.hotkey = parse_hotkey(normalized)
        return True

    def apply_settings(self, hotkey: str, middle_click: bool) -> tuple[bool, str]:
        """Valida e aplica as preferências; devolve (ok, mensagem em português). Em falha o atalho anterior continua valendo."""
        try:
            normalized = parse_hotkey(hotkey)[2]
        except ValueError as error:
            return False, str(error)
        message = 'Preferências salvas.'
        ok = True
        if normalized != self.global_hotkey.hotkey:
            if self._switch_hotkey(normalized):
                self.hotkey_registered = True
            else:
                ok = False
                message = f'Não foi possível registrar {normalized} (outro aplicativo pode estar usando); o atalho {self.global_hotkey.hotkey} continua valendo.'
                normalized = self.global_hotkey.hotkey
        self.settings = Settings(hotkey=normalized, middle_click=bool(middle_click)).validated()
        if not save_settings(self.settings):
            ok = False
            message = 'As preferências valem nesta sessão, mas não foi possível gravá-las no disco.'
        self._publish_hotkey_state()
        return ok, message

    def open_settings(self):
        from settings_dialog import SettingsDialog
        dialog = SettingsDialog(self, self.panel)
        dialog.exec()

    def on_paths_received(self, paths: list):
        """Caminhos vindos do menu de contexto do Explorer (outro processo); lista vazia só mostra o painel."""
        if not paths:
            self.show_panel()
            return
        self.open_global_radial(paths)

    @staticmethod
    def _icon() -> QIcon:
        pixmap = QPixmap(32, 32)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor('#ff5a00'))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(2, 2, 28, 28)
        painter.setPen(QColor('#ffffff'))
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, 'A')
        painter.end()
        return QIcon(pixmap)

    def _create_tray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return None
        tray = QSystemTrayIcon(self._icon(), self.app)
        tray.setToolTip(f'Arquivo Local — selecione um arquivo e segure Shift ({self.settings.hotkey} abre as ferramentas)')
        menu = QMenu()
        self.tray_menu = menu
        open_action = QAction('Abrir painel de funcionalidades', menu)
        open_action.triggered.connect(lambda: self.show_panel())
        menu.addAction(open_action)
        shelf_action = QAction('Abrir prateleira de arquivos', menu)
        shelf_action.triggered.connect(self.show_shelf)
        menu.addAction(shelf_action)
        menu.addSeparator()
        status = QAction(f'Shift: conversões • {self.settings.hotkey}: ferramentas dos arquivos', menu)
        status.setEnabled(False)
        menu.addAction(status)
        self.status_action = status
        settings_action = QAction('Atalhos e integração…', menu)
        settings_action.triggered.connect(self.open_settings)
        menu.addAction(settings_action)
        menu.addSeparator()
        quit_action = QAction('Sair', menu)
        quit_action.triggered.connect(self.quit)
        menu.addAction(quit_action)
        tray.setContextMenu(menu)
        tray.activated.connect(self.on_tray_activated)
        tray.show()
        return tray

    def on_tray_activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.show_panel()

    def show_panel(self, paths: list[str] | None = None, target: str | None = None):
        if paths is not None:
            self.panel.set_files(paths, target)
        elif target is None:
            self.panel.show_home()
        self.panel.showNormal()
        self.panel.raise_()
        self.panel.activateWindow()

    def show_shelf(self):
        self.shelf.showNormal()
        self.shelf.raise_()
        self.shelf.activateWindow()

    def open_global_radial(self, paths: list[str] | None = None):
        self.suppress_shift_until_release = True
        self.shift_started = None
        self.activated_for_hold = False
        paths_from_open_menu = None
        if self.radial and self.radial.isVisible():
            if self.radial_mode == 'global':
                return
            paths_from_open_menu = list(self.radial_paths)
            self.radial.close()
        try:
            paths = validate_selection(paths_from_open_menu or paths or selected_paths_from_explorer())
        except Exception as error:
            self.controller.notify('Arquivo Local', 'Não foi possível usar a seleção: ' + str(error)[:180])
            return
        title = Path(paths[0]).name if len(paths) == 1 else f'{len(paths)} itens selecionados'
        self.panel.set_files(paths)
        self.radial_paths = list(paths)
        self.radial = RadialMenu(
            title,
            actions_for_selection(paths, self.controller.capabilities),
            lambda action: self.handle_global_action(paths, action),
            context=self._context_text(paths),
            on_drop=lambda dropped, action: self.handle_global_action(self._valid_drop(dropped) or paths, action),
        )
        self.radial_mode = 'global'
        self.radial.show_at_cursor()

    def handle_global_action(self, paths: list[str], action: RadialAction):
        try:
            checked = validate_selection(paths)
            tool_targets = {action_id: spec.target for action_id, spec in tool_registry.BY_ACTION.items()}
            if action.target in tool_targets:
                target=tool_targets[action.target]
                self.show_panel(checked,target)
                return
            if action.target in OPERATIONS:
                self.controller.start_job(checked,action.target,{'to_folder':'on'} if len(checked) > 1 else {})
                return
            if action.target=='__panel_merge__':
                self.show_panel(checked,'Merge PDFs')
                return
            if action.target=='__panel__':
                self.show_panel(checked)
                return
            if action.target.startswith('__capability_'):
                key = action.target.removeprefix('__capability_')
                _available, reason = self.controller.capabilities.get(key, (False, 'Capacidade não verificada.'))
                self.controller.notify('Arquivo Local', f'Ação indisponível: {reason}')
                return
            if action.target == '__copy_paths__':
                QApplication.clipboard().setText(format_path_lines(checked))
                self.controller.notify('Arquivo Local', f'{len(checked)} caminho(s) copiado(s) como texto.')
                return
            if action.target == '__copy_files__':
                from PySide6.QtCore import QMimeData
                mime = QMimeData()
                mime.setUrls([QUrl.fromLocalFile(path) for path in checked])
                QApplication.clipboard().setMimeData(mime)
                self.controller.notify('Arquivo Local', f'{len(checked)} referência(s) de arquivo(s) copiadas.')
                return
            if action.target == '__shelf_add__':
                added = self.shelf.add_paths(checked)
                self.show_shelf()
                self.controller.notify('Arquivo Local', f'{added} referência(s) adicionada(s) à prateleira.')
                return
            if action.target == '__open_terminal__':
                directory = terminal_directory(checked)
                local_app_data = os.environ.get('LOCALAPPDATA', '')
                terminal = os.path.join(local_app_data, 'Microsoft', 'WindowsApps', 'wt.exe') if local_app_data else ''
                if terminal and os.path.isfile(terminal):
                    subprocess.Popen([terminal, '-d', directory], cwd=directory, shell=False, close_fds=True)
                else:
                    system_root = os.environ.get('SystemRoot', r'C:\\Windows')
                    powershell = os.path.join(system_root, 'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe')
                    if not os.path.isfile(powershell):
                        raise FileNotFoundError('Windows Terminal e Windows PowerShell não foram encontrados.')
                    subprocess.Popen([powershell, '-NoExit'], cwd=directory, shell=False, close_fds=True)
                return
            raise ValueError('Ação global desconhecida.')
        except Exception as error:
            self.controller.notify('Arquivo Local', 'Ação não executada: ' + str(error)[:180])

    def poll_shift(self):
        down = shift_is_down()
        middle = key_is_down(VK_MIDDLE_BUTTON)
        if middle_click_trigger(self.settings.middle_click, down, middle, self._middle_was_down) and not (self.radial and self.radial.isVisible()):
            self._middle_was_down = middle
            self.open_global_radial()
            return
        self._middle_was_down = middle
        if self.suppress_shift_until_release:
            if not down:
                self.suppress_shift_until_release = False
                self.shift_started = None
                self.activated_for_hold = False
            return
        if chord_in_progress(key_is_down(VK_CONTROL), key_is_down(VK_ALT), key_is_down(self.global_hotkey.vk)) or (self.radial and self.radial.isVisible()):
            self.shift_started = None
            self.activated_for_hold = False
            return
        if not down:
            self.shift_started = None
            self.activated_for_hold = False
            return
        now = time.monotonic()
        if self.shift_started is None:
            self.shift_started = now
            self.activated_for_hold = False
            return
        if self.activated_for_hold or now - self.shift_started < self.HOLD_SECONDS:
            return
        self.activated_for_hold = True
        try:
            paths = selected_paths_from_explorer()
        except Exception as error:
            self.controller.notify('Arquivo Local', 'Integração com o Windows Shell indisponível: ' + str(error)[:120])
            return
        if not paths:
            return
        if len(paths) > 1:
            self.controller.notify('Arquivo Local', 'Há vários arquivos selecionados; abra o painel para escolher a operação.')
            self.show_panel(paths)
            return
        self.open_radial(paths[0])

    def open_radial(self, path: str):
        if self.radial and self.radial.isVisible():
            return
        actions = actions_for_file(path, self.controller.capabilities)
        self.panel.set_files([path])
        self.radial_paths = [path]
        self.radial = RadialMenu(path, actions, lambda action: self.handle_radial_action(path, action),
                                 context=self._context_text([path]), on_drop=lambda dropped, action: self.handle_dropped_on_quick_wheel(dropped, path, action))
        self.radial_mode = 'quick'
        self.radial.show_at_cursor()

    @staticmethod
    def _context_text(paths: list[str]) -> str:
        """Texto do miolo da roda: tamanho do arquivo ou quantidade de itens."""
        if len(paths) != 1:
            return f'{len(paths)} arquivos'
        try:
            return human_size(Path(paths[0]).stat().st_size)
        except OSError:
            return Path(paths[0]).name

    @staticmethod
    def _valid_drop(dropped: list[str]) -> list[str]:
        try:
            return validate_selection(dropped)
        except Exception:
            return []

    def handle_dropped_on_quick_wheel(self, dropped: list[str], fallback: str, action: RadialAction):
        """Arquivos soltos numa fatia da roda rápida: a conversão vale para o que foi solto (ou, sem nada válido, para o arquivo da roda)."""
        paths = self._valid_drop(dropped) or [fallback]
        if action.target in OPERATIONS:
            self.controller.start_job(paths, action.target, {'to_folder': 'on'} if len(paths) > 1 else {})
        else:
            self.handle_radial_action(paths[0], action)

    def handle_radial_action(self, path: str, action: RadialAction):
        if action.target.startswith('__capability_'):
            key = action.target.removeprefix('__capability_')
            _available, reason = self.controller.capabilities.get(key, (False, 'Capacidade não verificada.'))
            self.controller.notify('Arquivo Local', f'Operação indisponível: {reason}')
        elif action.target == '__panel_merge__':
            self.show_panel([path], 'Merge PDFs')
        elif action.target == '__panel__':
            self.show_panel([path])
        elif action.target in OPERATIONS:
            self.controller.start_job([path],action.target,{})
        else:
            self.controller.start_job([path], action.target, {})

    def quit(self):
        if self.controller.worker and self.controller.worker.isRunning():
            self.controller.notify('Arquivo Local', 'Aguarde a operação atual terminar antes de sair.')
            return
        self.poller.stop()
        self.global_hotkey.stop()
        self.ipc.stop()
        if self.radial:
            self.radial.close()
        self.shelf.close()
        self.panel.allow_close = True
        self.panel.close()
        if self.tray:
            self.tray.hide()
        self.app.quit()


def _hide_frozen_console():
    if os.name == 'nt' and getattr(sys, 'frozen', False):
        try:
            import ctypes
            hwnd = ctypes.windll.kernel32.GetConsoleWindow()
            if hwnd:
                ctypes.windll.user32.ShowWindow(hwnd, 0)
        except Exception:
            pass


def send_to_paths(argv: list[str]) -> list[str]:
    """Caminhos que vêm depois de `--send-to` (um por argumento; o menu de contexto passa um por processo)."""
    if '--send-to' not in argv:
        return []
    return [arg for arg in argv[argv.index('--send-to') + 1:] if arg and not arg.startswith('--')]


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName('Arquivo Local')
    app.setQuitOnLastWindowClosed(False)
    if '--smoke-test' in sys.argv:
        controller = TrayApplication(app)
        QTimer.singleShot(700, controller.quit)
        return app.exec()
    from instance_guard import acquire_app_lock
    from ipc import send_paths
    forwarded = send_to_paths(sys.argv)
    wants_send_to = '--send-to' in sys.argv
    try:
        instance_lock = acquire_app_lock()
    except Exception as error:
        QMessageBox.critical(None, 'Arquivo Local', 'Não foi possível garantir uma única instância: ' + str(error))
        return 2
    if instance_lock is None:
        # Já existe uma instância: entregue os caminhos (ou só peça para mostrar o painel). Nas chamadas do Explorer a
        # instância pode estar ainda subindo, então tentamos algumas vezes antes de desistir em silêncio.
        for _attempt in range(8 if wants_send_to else 1):
            if send_paths(forwarded):
                return 0
            time.sleep(0.4)
        if not wants_send_to:
            QMessageBox.information(None, 'Arquivo Local', 'O Arquivo Local já está aberto. Procure o ícone na bandeja do sistema.')
        return 0
    _hide_frozen_console()
    try:
        controller = TrayApplication(app)
        if forwarded:
            QTimer.singleShot(0, lambda: controller.ipc.feed(forwarded))
        return app.exec()
    finally:
        instance_lock.unlock()
