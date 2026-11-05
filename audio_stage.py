"""Área de informações do áudio no painel (0.9.43): resumo do arquivo, lista quando há vários e detalhes.

Nenhum áudio é aberto neste processo: as informações vêm do worker descartável (`runner.run_media_op` → `mediatools.run_op`),
numa thread de segundo plano. Cada pedido recebe um número; respostas de pedidos antigos são descartadas.
Os textos vêm do arquivo (etiquetas) e por isso são sempre escapados antes de entrar no HTML do rótulo.
"""
from __future__ import annotations

from html import escape
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import QLabel, QListWidget, QListWidgetItem, QScrollArea, QVBoxLayout, QWidget

import mediatools
import runner
from audio_wave import WavePanel

ROLE_PATH = Qt.ItemDataRole.UserRole


class AudioLoadTask(QThread):
    """Pede ao worker as informações; `loader` é injetável para os testes (nunca iniciam uma thread real)."""
    finished_with = Signal(int, object, str)

    def __init__(self, token: int, job: dict, loader=None):
        super().__init__()
        self.token, self.job, self.loader = token, job, loader or runner.run_media_op

    def run(self):
        try:
            self.finished_with.emit(self.token, self.loader(self.job), '')
        except Exception as error:
            self.finished_with.emit(self.token, None, str(error)[:300] or 'Não foi possível ler o áudio.')


def details_html(info: dict) -> str:
    """Tabela HTML das informações; todo valor é escapado (as etiquetas vêm do arquivo e não são confiáveis)."""
    rows = ''.join(f'<tr><td style="padding:2px 14px 2px 0;color:#7a6a5a">{escape(label)}</td><td style="padding:2px 0"><b>{escape(str(value))}</b></td></tr>'
                   for label, value in mediatools.describe(info))
    return f'<table>{rows}</table>'


class AudioStage(QWidget):
    infos_ready = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('AudioStage')
        self.setStyleSheet('QWidget#AudioStage, QScrollArea, QLabel{background:transparent}')          # herda o branco do cartão da prévia
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.summary = QLabel('Abra um áudio para ver as informações.')
        self.summary.setObjectName('Muted'); self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.files = QListWidget()
        self.files.setMaximumHeight(150)
        self.files.setToolTip('Clique num arquivo para ver os detalhes dele.')
        self.files.currentRowChanged.connect(self._file_chosen)
        layout.addWidget(self.files)
        self.details = QLabel('')
        self.details.setTextFormat(Qt.TextFormat.RichText); self.details.setWordWrap(True)
        self.details.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.details.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QScrollArea.Shape.NoFrame); scroll.setWidget(self.details)
        scroll.setStyleSheet('QScrollArea{background:transparent}'); scroll.viewport().setStyleSheet('background:transparent'); self.details.setStyleSheet('background:transparent')
        layout.addWidget(scroll, 1)
        self.note = QLabel(''); self.note.setObjectName('Caption'); self.note.setWordWrap(True)
        layout.addWidget(self.note)
        self.wave = WavePanel()               # só aparece em «Cortar»
        self.wave.hide()
        layout.addWidget(self.wave)
        self.files.hide()
        self.paths: list[str] = []
        self.infos: dict[str, dict] = {}
        self.loader = None                    # testes: chamada síncrona no lugar da thread
        self.capability = mediatools.capability
        self._token = 0
        self._tasks: list[AudioLoadTask] = []

    def show_files(self, paths: list[str]):
        self.paths = [str(p) for p in paths][:mediatools.MAX_PATHS]
        self.infos = {}
        self.details.setText(''); self.note.setText('')
        self.files.blockSignals(True); self.files.clear(); self.files.blockSignals(False)
        self._token += 1                      # qualquer resposta pendente ficou velha
        if not self.paths:
            self.files.hide()
            self.summary.setText('Abra um áudio para ver as informações.')
            return
        ok, reason = self.capability()
        if not ok:
            self.files.hide()
            self.summary.setText(reason)
            return
        for path in self.paths:
            QListWidgetItem(f'{Path(path).name}   ·   lendo…', self.files).setData(ROLE_PATH, path)
        self.files.setVisible(len(self.paths) > 1)
        self.summary.setText('Lendo o áudio…' if len(self.paths) == 1 else f'Lendo {len(self.paths)} arquivos…')
        self._request({'op': 'audio_info', 'paths': self.paths})

    def _request(self, job: dict):
        token = self._token
        if self.loader is not None:
            try:
                self._apply(token, self.loader(job), '')
            except Exception as error:
                self._apply(token, None, str(error)[:300])
            return
        self._tasks = [t for t in self._tasks if t.isRunning()]          # destruir um QThread ativo derruba o programa
        task = AudioLoadTask(token, job)
        task.finished_with.connect(self._apply)
        self._tasks.append(task)
        task.start()

    def _apply(self, token: int, result, error: str):
        if token != self._token:
            return
        if error or not result or 'infos' not in result:
            self.summary.setText(error or 'Não foi possível ler o áudio.')
            return
        infos = result['infos']
        self.files.blockSignals(True)
        for index, info in enumerate(infos):
            path = self.paths[index] if index < len(self.paths) else ''
            self.infos[path] = info
            item = self.files.item(index)
            if item is not None:
                item.setText(f'{info.get("name") or Path(path).name}   ·   {self._short(info)}')
        self.files.blockSignals(False)
        good = [i for i in infos if not i.get('error')]
        total = sum(i.get('duration', 0) for i in good)
        if len(infos) == 1:
            self.summary.setText(infos[0].get('name', ''))
        else:
            self.summary.setText(f'{len(infos)} arquivos · duração total {mediatools.format_duration(total)}' + ('' if len(good) == len(infos) else f' · {len(infos) - len(good)} com problema (veja a lista)'))
        for index, info in enumerate(infos):
            if not info.get('error') and index < len(self.paths):
                self.files.setCurrentRow(index) if len(infos) > 1 else self._show_info(self.paths[index])
                break
        else:
            self.details.setText(escape(infos[0].get('error', '')) if infos else '')
        self.infos_ready.emit()

    @staticmethod
    def _short(info: dict) -> str:
        if info.get('error'):
            return info['error']
        return f"{mediatools.format_duration(info.get('duration', 0))} · {info.get('codec', '?')}"

    def _show_info(self, path: str):
        info = self.infos.get(path)
        if not info:
            return
        if info.get('error'):
            self.details.setText(f'<p>{escape(info["error"])}</p>')
        else:
            self.details.setText(details_html(info))
            self.note.setText('Somente leitura: nada é gravado nem alterado.')

    def _file_chosen(self, row: int):
        if 0 <= row < len(self.paths):
            self._show_info(self.paths[row])

    def shutdown(self):
        """Espera as threads de leitura terminarem (o worker tem tempo máximo); usado ao fechar o painel e nos testes."""
        self.wave.shutdown()
        for task in self._tasks:
            if task.isRunning():
                task.wait(5000)
        self._tasks = [t for t in self._tasks if t.isRunning()]
