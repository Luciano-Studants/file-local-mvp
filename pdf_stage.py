"""Área de prévia dos PDFs no painel: resumo do arquivo, página grande e faixa de miniaturas.

Nada de PDF é aberto neste processo: as informações e as imagens vêm do worker descartável (`runner.run_pdf_op`), numa thread de segundo plano.
Cada pedido recebe um número; respostas de pedidos antigos (o usuário trocou de arquivo ou de página) são descartadas.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, QThread, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QLabel, QListWidget, QListWidgetItem, QVBoxLayout, QWidget

import pdfinfo
import runner
from visual_tools import CropView, ImageStageView

THUMB_ITEM = QSize(100, 120)
ROLE_PAGE = Qt.ItemDataRole.UserRole
ROLE_PATH = Qt.ItemDataRole.UserRole + 1


class PdfLoadTask(QThread):
    """Pede ao worker as informações/imagens; `loader` é injetável para os testes (nunca iniciam uma thread real)."""
    finished_with = Signal(int, object, str)

    def __init__(self, token: int, job: dict, loader=None):
        super().__init__()
        self.token, self.job, self.loader = token, job, loader or runner.run_pdf_op

    def run(self):
        try:
            self.finished_with.emit(self.token, self.loader(self.job), '')
        except Exception as error:
            self.finished_with.emit(self.token, None, str(error)[:300] or 'Não foi possível ler o PDF.')


class PdfStage(QWidget):
    page_shown = Signal(int)
    infos_ready = Signal()          # as informações dos PDFs chegaram (o painel recalcula o tamanho em pixels)

    def __init__(self, parent=None, selectable: bool = False):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.summary = QLabel('Abra um PDF para ver as páginas.')
        self.summary.setObjectName('Muted'); self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.note = QLabel(''); self.note.setObjectName('Caption'); self.note.setWordWrap(True); self.note.hide()
        layout.addWidget(self.note)
        blank = QPixmap(1, 1); blank.fill(Qt.GlobalColor.transparent)
        self.page_view = CropView(blank) if selectable else ImageStageView(blank)      # «Tarjar»: a página aceita seleção de áreas
        if selectable:
            self.page_view.dim_outside = False
        self.page_view.setMinimumSize(120, 90)          # a janela pequena encolhe a página em vez de sobrepor as miniaturas
        layout.addWidget(self.page_view, 1)
        self.thumbs = QListWidget()
        self.thumbs.setViewMode(QListWidget.ViewMode.IconMode)
        self.thumbs.setFlow(QListWidget.Flow.LeftToRight)
        self.thumbs.setWrapping(False)
        self.thumbs.setMovement(QListWidget.Movement.Static)
        self.thumbs.setIconSize(QSize(THUMB_ITEM.width() - 20, THUMB_ITEM.height() - 38))
        self.thumbs.setSpacing(4)
        self.thumbs.setFixedHeight(THUMB_ITEM.height() + 26)
        self.thumbs.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.thumbs.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.thumbs.setToolTip('Clique numa miniatura para ver a página maior.')
        self.thumbs.currentRowChanged.connect(self._thumb_chosen)
        layout.addWidget(self.thumbs)
        self.totals = QLabel(''); self.totals.setObjectName('Caption'); self.totals.setWordWrap(True); self.totals.hide()
        layout.addWidget(self.totals)
        self.files = QListWidget()
        self.files.setMaximumHeight(130)
        self.files.setToolTip('Clique num arquivo para ver as páginas dele.')
        self.files.currentRowChanged.connect(self._file_chosen)
        layout.addWidget(self.files)
        self.thumbs.hide(); self.files.hide()
        self.paths: list[str] = []
        self.current_path = ''
        self.infos: dict[str, dict] = {}
        self.loader = None            # testes: chamada síncrona no lugar da thread (recebe o job, devolve o resultado)
        self._token = 0
        self._tasks: list[PdfLoadTask] = []
        self._syncing = False
        self.hide_list = False        # «Unir PDFs»: a lista de ordem fica no painel de ajustes; aqui só a prévia do arquivo escolhido

    # --- entrada --------------------------------------------------------
    def show_files(self, paths: list[str]):
        """Mostra os PDFs escolhidos: um arquivo abre direto na prévia; vários mostram a lista com páginas e tamanho."""
        self.paths = [str(p) for p in paths]
        self.infos = {}
        self.current_path = ''
        self._clear_pages()
        self.note.hide()
        self.files.blockSignals(True); self.files.clear(); self.files.blockSignals(False)
        if not self.paths:
            self.files.hide(); self.thumbs.hide(); self.totals.hide()
            self.summary.setText('Abra um PDF para ver as páginas.')
            return
        for path in self.paths:
            QListWidgetItem(f'{Path(path).name}   ·   lendo…', self.files).setData(ROLE_PATH, path)
        self.files.setVisible(len(self.paths) > 1 and not self.hide_list)
        self.totals.setVisible(len(self.paths) > 1); self.totals.setText('')
        self.summary.setText('Lendo o PDF…' if len(self.paths) == 1 else f'Lendo {len(self.paths)} PDFs…')
        if len(self.paths) == 1:
            self._request({'op': 'pdf_preview', 'path': self.paths[0], 'thumbs': pdfinfo.MAX_PREVIEW_PAGES, 'page': 1}, self.paths[0])
        else:
            self._request({'op': 'pdf_info', 'paths': self.paths[:100]}, '')

    def set_paths(self, paths: list[str]):
        """Nova ordem/seleção dos mesmos PDFs sem reler nada (a lista de «Unir» foi reordenada ou teve um arquivo tirado); só vale para arquivos já lidos."""
        keep = [str(p) for p in paths if str(p) in self.infos or str(p) in self.paths]
        self.paths = keep
        self.files.blockSignals(True); self.files.clear()
        for path in keep:
            info = self.infos.get(path)
            text = f'{info.get("name") or Path(path).name}   ·   {self._short(info)}' if info else f'{Path(path).name}   ·   lendo…'
            QListWidgetItem(text, self.files).setData(ROLE_PATH, path)
        self.files.blockSignals(False)
        self.files.setVisible(len(keep) > 1 and not self.hide_list)

    def select_path(self, path: str):
        """Mostra a prévia do PDF `path` (um dos arquivos da lista)."""
        for row in range(self.files.count()):
            if str(self.files.item(row).data(ROLE_PATH)) == str(path):
                if self.files.currentRow() == row:
                    self._file_chosen(row)
                else:
                    self.files.setCurrentRow(row)
                return

    def open_page(self, number: int):
        """Pede a página `number` (a partir de 1) do arquivo atual em tamanho maior, sem refazer as miniaturas."""
        if self.current_path and number >= 1:
            self._request({'op': 'pdf_preview', 'path': self.current_path, 'thumbs': 0, 'page': number}, self.current_path, keep_thumbs=True)

    # --- pedidos ----------------------------------------------------------
    def _request(self, job: dict, path: str, keep_thumbs: bool = False):
        self._token += 1
        token = self._token
        self._keep_thumbs = keep_thumbs
        self._pending_path = path
        if self.loader is not None:
            try:
                self._apply(token, self.loader(job), '')
            except Exception as error:
                self._apply(token, None, str(error)[:300])
            return
        self._tasks = [t for t in self._tasks if t.isRunning()]          # guarda as threads em andamento: destruir um QThread ativo derruba o programa
        task = PdfLoadTask(token, job)
        task.finished_with.connect(self._apply)
        self._tasks.append(task)
        task.start()

    def _apply(self, token: int, result, error: str):
        if token != self._token:
            return                                       # resposta de um pedido já superado
        if error or result is None:
            self.summary.setText(error or 'Não foi possível ler o PDF.')
            return
        if 'infos' in result:
            self._apply_infos(result['infos'])
        else:
            self._apply_preview(result)

    def _apply_infos(self, infos: list):
        self.infos = {}
        self.files.blockSignals(True)
        for index, info in enumerate(infos):
            path = self.paths[index] if index < len(self.paths) else ''
            self.infos[path] = info
            item = self.files.item(index)
            if item is not None:
                item.setText(f'{info.get("name") or Path(path).name}   ·   {self._short(info)}')
        self.files.blockSignals(False)
        total = sum(i.get('pages') or 0 for i in infos)
        ok = sum(1 for i in infos if not i.get('error') and not i.get('encrypted'))
        self.totals.setText(f'{len(infos)} PDFs · {total} páginas no total' + ('' if ok == len(infos) else f' · {len(infos) - ok} com problema (veja a lista)'))
        for index, info in enumerate(infos):
            if not info.get('error') and not info.get('encrypted') and index < len(self.paths):
                self.files.setCurrentRow(index)          # abre a prévia do primeiro PDF legível
                break
        self.infos_ready.emit()

    @staticmethod
    def _short(info: dict) -> str:
        if info.get('error'):
            return info['error']
        if info.get('encrypted'):
            return 'protegido por senha'
        pages = info.get('pages') or 0
        return f'{pages} {"página" if pages == 1 else "páginas"} · {pdfinfo.human_bytes(info.get("size_bytes", 0))}'

    def _apply_preview(self, result: dict):
        info = result.get('info', {})
        path = self._pending_path or self.current_path
        self.current_path = path
        if path:
            self.infos[path] = info
        self.summary.setText(pdfinfo.summary_text(info))
        note = info.get('preview_note', '')
        self.note.setText(note); self.note.setVisible(bool(note))
        pages = result.get('pages', [])
        big = next((p for p in pages if p['kind'] == 'page'), None)
        if big is not None:
            pixmap = QPixmap()
            if pixmap.loadFromData(big['data'], 'PNG'):
                self.page_view.set_preview_pixmap(pixmap)
                self.page_shown.emit(int(big['page']))
        if not self._keep_thumbs:
            self._fill_thumbs([p for p in pages if p['kind'] == 'thumb'], info)
        self.infos_ready.emit()          # um PDF só: as informações chegam junto com a prévia

    def _fill_thumbs(self, thumbs: list, info: dict):
        self._syncing = True
        self.thumbs.clear()
        for entry in thumbs:
            pixmap = QPixmap()
            if not pixmap.loadFromData(entry['data'], 'PNG'):
                continue
            painter = QPainter(pixmap); painter.setPen(QColor('#b9bdc4')); painter.drawRect(0, 0, pixmap.width() - 1, pixmap.height() - 1); painter.end()      # contorno: páginas brancas somem no fundo branco da lista
            icon = QIcon()
            for mode in (QIcon.Mode.Normal, QIcon.Mode.Active, QIcon.Mode.Selected):
                icon.addPixmap(pixmap, mode)             # sem isto o Qt tinge de azul a miniatura selecionada
            item = QListWidgetItem(icon, str(entry['page']))
            item.setData(ROLE_PAGE, int(entry['page']))
            item.setSizeHint(THUMB_ITEM)
            item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter)
            self.thumbs.addItem(item)
        self._syncing = False
        self.thumbs.setVisible(self.thumbs.count() > 0)
        if self.thumbs.count():
            self._syncing = True; self.thumbs.setCurrentRow(0); self._syncing = False
        pages = info.get('pages') or 0
        if pages > self.thumbs.count() > 0:
            self.note.setText(f'Miniaturas das {self.thumbs.count()} primeiras páginas de {pages}.'); self.note.show()

    def _clear_pages(self):
        blank = QPixmap(1, 1); blank.fill(Qt.GlobalColor.transparent)
        self.page_view.set_preview_pixmap(blank)
        self._syncing = True; self.thumbs.clear(); self._syncing = False

    # --- escolhas do usuário ---------------------------------------------
    def _thumb_chosen(self, row: int):
        if self._syncing or row < 0:
            return
        item = self.thumbs.item(row)
        if item is not None:
            self.open_page(int(item.data(ROLE_PAGE)))

    def _file_chosen(self, row: int):
        if self._syncing or row < 0:
            return
        item = self.files.item(row)
        if item is None:
            return
        path = str(item.data(ROLE_PATH) or '')
        info = self.infos.get(path, {})
        if not path or info.get('error') or info.get('encrypted'):
            self.summary.setText(pdfinfo.summary_text(info) if info else 'Lendo…')
            return
        self._clear_pages()
        self._request({'op': 'pdf_preview', 'path': path, 'thumbs': pdfinfo.MAX_PREVIEW_PAGES, 'page': 1}, path)

    def shutdown(self):
        """Espera as threads de leitura terminarem (o worker tem tempo máximo); usado ao fechar o painel e nos testes."""
        for task in self._tasks:
            if task.isRunning():
                task.wait(5000)
        self._tasks = [t for t in self._tasks if t.isRunning()]
