"""Controles do sistema de design: chips segmentados e linhas com controle deslizante.

`ChipGroup` imita o subconjunto de `QComboBox` que o painel usa (addItem, currentIndex, setCurrentIndex,
currentText, itemText, count, currentIndexChanged), então pode substituí-lo sem mudar a lógica.
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QButtonGroup, QGridLayout, QHBoxLayout, QLabel, QPushButton, QSlider, QWidget


class ChipGroup(QWidget):
    currentIndexChanged = Signal(int)

    def __init__(self, items=(), per_row: int = 4, parent=None):
        super().__init__(parent)
        self._per_row = max(1, per_row)
        self._buttons: list[QPushButton] = []
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._layout = QGridLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setHorizontalSpacing(6)
        self._layout.setVerticalSpacing(6)
        self._index = -1
        self.addItems(items)

    def addItem(self, text: str) -> None:
        index = len(self._buttons)
        button = QPushButton(text)
        button.setObjectName('Chip')
        button.setMinimumHeight(28)
        button.setCheckable(True)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(lambda _checked=False, i=index: self.setCurrentIndex(i))
        self._group.addButton(button)
        self._layout.addWidget(button, index // self._per_row, index % self._per_row)
        self._buttons.append(button)
        if self._index < 0:
            self._index = 0
            button.setChecked(True)

    def addItems(self, items) -> None:
        for text in items:
            self.addItem(text)

    def count(self) -> int:
        return len(self._buttons)

    def itemText(self, index: int) -> str:
        return self._buttons[index].text() if 0 <= index < len(self._buttons) else ''

    def currentIndex(self) -> int:
        return self._index

    def currentText(self) -> str:
        return self.itemText(self._index)

    def setCurrentIndex(self, index: int) -> None:
        if not 0 <= index < len(self._buttons):
            return
        self._buttons[index].setChecked(True)
        if index != self._index:
            self._index = index
            self.currentIndexChanged.emit(index)
        else:
            self._index = index

    def setEnabled(self, enabled: bool) -> None:
        super().setEnabled(enabled)
        for button in self._buttons:
            button.setEnabled(enabled)


class SliderRow(QWidget):
    """Controle deslizante com o valor à direita (ex.: «Margem · 120 px»)."""
    valueChanged = Signal(int)

    def __init__(self, minimum: int = 0, maximum: int = 100, value: int = 0, suffix: str = ' px', parent=None, formatter=None):
        super().__init__(parent)
        self._suffix = suffix
        self._formatter = formatter
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(minimum, maximum)
        self.slider.setValue(value)
        self.label = QLabel(); self.label.setObjectName('SliderValue'); self.label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.slider, 1)
        layout.addWidget(self.label)
        self.slider.valueChanged.connect(self._changed)
        self._refresh()

    def _refresh(self) -> None:
        self.label.setText(self._formatter(self.slider.value()) if self._formatter else f'{self.slider.value()}{self._suffix}')

    def _changed(self, value: int) -> None:
        self._refresh()
        self.valueChanged.emit(value)

    def value(self) -> int:
        return self.slider.value()

    def setValue(self, value: int) -> None:
        self.slider.setValue(value)

    def setRange(self, minimum: int, maximum: int) -> None:
        self.slider.setRange(minimum, maximum)

    def maximum(self) -> int:
        return self.slider.maximum()

    def setEnabled(self, enabled: bool) -> None:
        super().setEnabled(enabled)
        self.slider.setEnabled(enabled)


class HistogramView(QWidget):
    """Histograma de luminosidade (256 faixas) com marcas nos pontos preto e branco e no tom médio do gama."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(86); self.setMaximumHeight(110)
        self._hist: list[int] | None = None; self._black = 0; self._white = 255; self._gamma = 100

    def set_histogram(self, hist) -> None:
        self._hist = list(hist) if hist else None
        self.update()

    def set_marks(self, black: int, white: int, gamma: int = 100) -> None:
        self._black, self._white, self._gamma = black, white, gamma
        self.update()

    def histogram(self):
        return self._hist

    def paintEvent(self, _event) -> None:
        painter = QPainter(self); painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setPen(QPen(QColor('#e1e4e4'))); painter.setBrush(QColor('#ffffff')); painter.drawRoundedRect(rect, 6, 6)
        inner = rect.adjusted(6, 6, -6, -6)
        if not self._hist or not max(self._hist):
            painter.setPen(QColor('#a3abad')); painter.drawText(inner, Qt.AlignmentFlag.AlignCenter, 'Histograma disponível com uma imagem'); return
        peak = max(sorted(self._hist)[-3:]) or 1                       # ignora o pico isolado de preto/branco puro para o resto continuar legível
        width = inner.width() / 256
        painter.setPen(Qt.PenStyle.NoPen); painter.setBrush(QColor('#c9ced0'))
        for value, count in enumerate(self._hist):
            height = inner.height() * min(1.0, count / peak)
            painter.drawRect(QRectF(inner.left() + value * width, inner.bottom() - height, max(width, 1.0), height))
        dim = QColor(29, 34, 36, 70); painter.setBrush(dim)
        painter.drawRect(QRectF(inner.left(), inner.top(), self._black * width, inner.height()))
        painter.drawRect(QRectF(inner.left() + (self._white + 1) * width, inner.top(), max(0.0, (255 - self._white) * width), inner.height()))
        painter.setBrush(Qt.BrushStyle.NoBrush); accent = QPen(QColor('#ff5a00')); accent.setWidthF(1.6); painter.setPen(accent)
        for mark in (self._black, self._white):
            x = inner.left() + (mark + 0.5) * width; painter.drawLine(x, inner.top(), x, inner.bottom())
        mid = self._black + (self._white - self._black) * 0.5 ** (self._gamma / 100)      # tom que vira cinza médio depois do gama
        x = inner.left() + (mid + 0.5) * width; painter.setPen(QPen(QColor('#6a7376'), 1.2, Qt.PenStyle.DashLine)); painter.drawLine(x, inner.top(), x, inner.bottom())


def swatch_pixmap(kind: str, colors: tuple[str, ...], size: int = 26, plus: bool = False) -> QPixmap:
    """Miniatura de amostra de fundo: cor lisa ou degradê diagonal; `plus` marca a amostra personalizada com um «+»."""
    pixmap = QPixmap(size, size)
    painter = QPainter(pixmap)
    if kind == 'solid' or len(colors) < 2:
        painter.fillRect(pixmap.rect(), QColor(colors[0]))
    else:
        gradient = QLinearGradient(0, 0, size, size)
        for position, color in enumerate(colors):
            gradient.setColorAt(position / (len(colors) - 1), QColor(color))
        painter.fillRect(pixmap.rect(), gradient)
    if plus:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QColor('#1d2224' if QColor(colors[0]).lightness() > 140 else '#ffffff'))
        painter.drawLine(size // 2, size // 2 - 5, size // 2, size // 2 + 5)
        painter.drawLine(size // 2 - 5, size // 2, size // 2 + 5, size // 2)
    painter.end()
    return pixmap
