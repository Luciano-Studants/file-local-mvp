"""Onda do áudio com duas alças (início e fim) para «Cortar» (Áudio, item 6).

A onda vem do worker (`audio_wave` → picos já reduzidos); este widget só desenha e mexe nas alças. Nada de áudio é aberto neste processo.
Cada pedido recebe um número; respostas de pedidos antigos são descartadas. `loader` é injetável para os testes (nunca iniciam thread real).
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, QThread, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QLabel, QSizePolicy, QVBoxLayout, QWidget

import runner

HANDLE_GRAB = 9          # px em volta da alça em que o clique a pega
MIN_GAP = 0.1            # s entre as alças


class WaveTask(QThread):
    finished_with = Signal(int, object, str)

    def __init__(self, token: int, job: dict, loader=None):
        super().__init__()
        self.token, self.job, self.loader = token, job, loader or (lambda job: runner.run_media_op(job, timeout=260))

    def run(self):
        try:
            self.finished_with.emit(self.token, self.loader(self.job), '')
        except Exception as error:
            self.finished_with.emit(self.token, None, str(error)[:300] or 'Não foi possível desenhar a onda.')


class WaveformView(QWidget):
    """Onda + alças. Tempos em segundos. `range_changed(início, fim)` sai quando o usuário arrasta."""
    range_changed = Signal(float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(110)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(130)
        self.setMouseTracking(True)
        self.peaks: list = []
        self.duration = 0.0
        self.start = 0.0
        self.end = 0.0
        self.silence: tuple | None = None          # (silêncio no início, no fim) em segundos
        self.message = 'Sem onda.'
        self._drag = None

    # --- dados ---
    def set_data(self, peaks: list, duration: float, silence=None, message: str = ''):
        self.peaks, self.duration = list(peaks or []), max(0.0, float(duration or 0))
        self.silence = (float(silence[0]), float(silence[1])) if silence else None
        self.start, self.end = 0.0, self.duration
        self.message = message or ('' if self.peaks else 'Sem onda para este arquivo; use os campos de tempo.')
        self.update()

    def clear(self, message: str = 'Sem onda.'):
        self.set_data([], 0.0, None, message)

    def set_range(self, start: float, end: float):
        if self.duration <= 0:
            return
        start = min(max(0.0, float(start)), self.duration)
        end = min(max(0.0, float(end)), self.duration)
        self.start, self.end = start, max(end, start)
        self.update()

    # --- geometria ---
    def _x(self, seconds: float) -> float:
        width = max(1, self.width() - 2)
        return 1 + (seconds / self.duration) * width if self.duration > 0 else 1.0

    def _seconds(self, x: float) -> float:
        width = max(1, self.width() - 2)
        return min(max(0.0, (x - 1) / width), 1.0) * self.duration

    # --- desenho ---
    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        rect = self.rect()
        painter.fillRect(rect, QColor('#fbf7f1'))
        painter.setPen(QPen(QColor('#e3d9cc'), 1))
        painter.drawRect(rect.adjusted(0, 0, -1, -1))
        if not self.peaks or self.duration <= 0:
            painter.setPen(QColor('#7a6a5a'))
            painter.drawText(rect.adjusted(8, 0, -8, 0), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, self.message)
            return
        middle = rect.height() / 2
        loudest = max((max(abs(low), abs(high)) for low, high in self.peaks), default=1)
        scale = (rect.height() / 2 - 6) / max(25, loudest)          # a onda é ampliada para ocupar a altura (sons baixos também aparecem)
        if self.silence:                                              # silêncio das pontas em cinza-azulado
            lead, tail = self.silence
            for a, b in ((0.0, lead), (self.duration - tail, self.duration)):
                if b - a >= 0.01:
                    painter.fillRect(QRectF(self._x(a), 1, max(1.0, self._x(b) - self._x(a)), rect.height() - 2), QColor(120, 150, 190, 40))
        count = len(self.peaks)
        painter.setPen(QPen(QColor('#b8733a'), 1))
        for index, (low, high) in enumerate(self.peaks):
            x = 1 + index * (rect.width() - 2) / count
            painter.drawLine(QPointF(x, middle - high * scale), QPointF(x, middle - low * scale - 1))
        painter.setPen(QPen(QColor('#d9cdbd'), 1))
        painter.drawLine(1, int(middle), rect.width() - 2, int(middle))
        shade = QColor(60, 40, 20, 90)                                # a parte que será descartada
        painter.fillRect(QRectF(1, 1, max(0.0, self._x(self.start) - 1), rect.height() - 2), shade)
        painter.fillRect(QRectF(self._x(self.end), 1, max(0.0, rect.width() - 1 - self._x(self.end)), rect.height() - 2), shade)
        painter.setPen(QPen(QColor('#7a3d12'), 2))
        for seconds in (self.start, self.end):
            x = self._x(seconds)
            painter.drawLine(QPointF(x, 1), QPointF(x, rect.height() - 2))
            painter.fillRect(QRectF(x - 4, 1, 8, 10), QColor('#7a3d12'))

    # --- mouse ---
    def _nearest(self, x: float):
        dist_start, dist_end = abs(x - self._x(self.start)), abs(x - self._x(self.end))
        if min(dist_start, dist_end) <= HANDLE_GRAB:
            return 'start' if dist_start <= dist_end else 'end'
        return 'start' if abs(x - self._x(self.start)) <= abs(x - self._x(self.end)) else 'end'

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton or not self.peaks or self.duration <= 0:
            return
        self._drag = self._nearest(event.position().x())
        self._move(event.position().x())

    def mouseMoveEvent(self, event):
        if self._drag:
            self._move(event.position().x())
        elif self.peaks:
            near = min(abs(event.position().x() - self._x(self.start)), abs(event.position().x() - self._x(self.end))) <= HANDLE_GRAB
            self.setCursor(Qt.CursorShape.SizeHorCursor if near else Qt.CursorShape.ArrowCursor)

    def mouseReleaseEvent(self, _event):
        self._drag = None

    def _move(self, x: float):
        seconds = round(self._seconds(x), 3)
        if self._drag == 'start':
            self.start = min(seconds, max(0.0, self.end - MIN_GAP))
        else:
            self.end = max(seconds, min(self.duration, self.start + MIN_GAP))
        self.update()
        self.range_changed.emit(self.start, self.end)


class WavePanel(QWidget):
    """Onda + rótulo de estado, com leitura pelo worker."""
    loaded = Signal()
    range_changed = Signal(float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self); layout.setContentsMargins(0, 0, 0, 0); layout.setSpacing(4)
        self.view = WaveformView()
        self.view.range_changed.connect(self.range_changed)
        self.caption = QLabel('Arraste as alças para escolher o trecho que fica; a parte escura será descartada.')
        self.caption.setObjectName('Caption'); self.caption.setWordWrap(True)
        layout.addWidget(self.view); layout.addWidget(self.caption)
        self.path = ''
        self.data: dict = {}
        self.loader = None
        self._token = 0
        self._tasks: list[WaveTask] = []

    def show_file(self, path: str):
        if path == self.path and self.data:
            return
        self.path, self.data = path, {}
        self._token += 1
        self.view.clear('Lendo a onda…' if path else 'Sem onda.')
        if path:
            self._request({'op': 'audio_wave', 'paths': [path]})

    def reset(self):
        self.show_file('')

    def _request(self, job: dict):
        token = self._token
        if self.loader is not None:
            try:
                self._apply(token, self.loader(job), '')
            except Exception as error:
                self._apply(token, None, str(error)[:300])
            return
        self._tasks = [t for t in self._tasks if t.isRunning()]
        task = WaveTask(token, job)
        task.finished_with.connect(self._apply)
        self._tasks.append(task)
        task.start()

    def _apply(self, token: int, result, error: str):
        if token != self._token:
            return
        if error or not isinstance(result, dict):
            self.data = {}
            self.view.clear(error or 'Não foi possível desenhar a onda.')
            self.loaded.emit()
            return
        self.data = result
        silence = result.get('silence')
        self.view.set_data(result.get('peaks') or [], result.get('duration') or 0, (silence['lead'], silence['tail']) if silence else None, result.get('wave_error') or '')
        self.loaded.emit()

    def shutdown(self):
        for task in self._tasks:
            if task.isRunning():
                task.wait(8000)
        self._tasks = [t for t in self._tasks if t.isRunning()]
