"""Ícones de linha desenhados em código (grade 24×24), sem depender de fontes de símbolos."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap, QPolygonF

# Primitivas: ('rect', x, y, w, h, raio) · ('line', x1, y1, x2, y2) · ('poly', [(x, y), ...], fechado)
# · ('circle', cx, cy, r)
ICON_SHAPES: dict[str, list[tuple]] = {
    'images': [('rect', 3, 4, 18, 16, 3), ('circle', 8.5, 9.5, 1.8), ('poly', [(4, 18), (10, 12), (14, 16), (17, 13), (20, 17)], False)],
    'video': [('rect', 3, 5, 18, 14, 3), ('poly', [(10, 9), (10, 15), (15, 12)], True)],
    'audio': [('line', 9, 17, 9, 6), ('line', 9, 6, 19, 4), ('line', 19, 4, 19, 15), ('circle', 6.5, 17.5, 2.5), ('circle', 16.5, 15.5, 2.5)],
    'pdf': [('poly', [(6, 3), (14, 3), (19, 8), (19, 21), (6, 21)], True), ('poly', [(14, 3), (14, 8), (19, 8)], False), ('line', 9, 13, 16, 13), ('line', 9, 17, 14, 17)],
    'documents': [('rect', 5, 3, 14, 18, 2), ('line', 8.5, 8, 15.5, 8), ('line', 8.5, 12, 15.5, 12), ('line', 8.5, 16, 12.5, 16)],
    'slides': [('rect', 3, 4, 18, 12, 2), ('line', 12, 16, 12, 20), ('line', 8, 20, 16, 20)],
    'spreadsheets': [('rect', 3, 4, 18, 16, 2), ('line', 3, 10, 21, 10), ('line', 3, 15, 21, 15), ('line', 10, 4, 10, 20)],
    'epub': [('poly', [(4, 5), (11, 7), (11, 20), (4, 18)], True), ('poly', [(20, 5), (13, 7), (13, 20), (20, 18)], True)],
    'subtitles': [('rect', 3, 5, 18, 14, 3), ('line', 7, 11, 11, 11), ('line', 13, 11, 17, 11), ('line', 7, 15, 14, 15)],
    'archives': [('rect', 3, 4, 18, 5, 1.5), ('poly', [(5, 9), (5, 20), (19, 20), (19, 9)], False), ('line', 10, 13, 14, 13)],
    # ícones das ferramentas (fatias da roda)
    'onepdf': [('poly', [(7, 3), (14, 3), (18, 7), (18, 21), (7, 21)], True), ('line', 14, 3, 14, 7), ('line', 14, 7, 18, 7), ('line', 10, 12, 15, 12), ('line', 10, 16, 15, 16)],
    'shapes': [('rect', 4, 4, 10, 8, 1), ('circle', 16, 15, 4.5), ('line', 5, 20, 12, 17), ('line', 10.5, 16.2, 12, 17), ('line', 11.2, 19.2, 12, 17)],
    'levels': [('line', 4, 20, 20, 20), ('line', 5, 20, 5, 14), ('line', 9, 20, 9, 8), ('line', 13, 20, 13, 11), ('line', 17, 20, 17, 5), ('line', 4, 4, 4, 4)],
    'removebg': [('circle', 12, 9, 3.2), ('poly', [(6, 20), (6, 17), (9, 14.5), (15, 14.5), (18, 17), (18, 20)], False), ('line', 3, 3, 3, 6), ('line', 3, 3, 6, 3), ('line', 21, 3, 21, 6), ('line', 21, 3, 18, 3), ('line', 3, 21, 3, 18), ('line', 3, 21, 6, 21), ('line', 21, 21, 21, 18), ('line', 21, 21, 18, 21)],
    'ocr': [('rect', 3, 3, 18, 18, 2.5), ('line', 7, 8, 17, 8), ('line', 7, 12, 17, 12), ('line', 7, 16, 13, 16)],
    'sharpen': [('circle', 12, 12, 7), ('circle', 12, 12, 3), ('line', 12, 2, 12, 5), ('line', 12, 19, 12, 22), ('line', 2, 12, 5, 12), ('line', 19, 12, 22, 12)],
    'adjust': [('line', 5, 6, 19, 6), ('line', 5, 12, 19, 12), ('line', 5, 18, 19, 18), ('circle', 9, 6, 2.2), ('circle', 15, 12, 2.2), ('circle', 10, 18, 2.2)],
    'metadata': [('rect', 5, 3, 14, 18, 2.5), ('line', 8.5, 8, 15.5, 8), ('line', 8.5, 12, 15.5, 12), ('line', 8.5, 16, 12.5, 16)],
    'resize': [('rect', 3, 11, 10, 10, 1.5), ('rect', 3, 3, 18, 18, 2.5), ('line', 14, 10, 20, 4), ('line', 15, 4, 20, 4), ('line', 20, 4, 20, 9)],
    'watermark': [('rect', 3, 4, 18, 16, 3), ('line', 7, 16, 11, 8), ('line', 11, 8, 15, 16), ('line', 8.5, 13, 13.5, 13)],
    'lock': [('rect', 5, 11, 14, 10, 2), ('poly', [(8, 11), (8, 7.5), (9.5, 5), (14.5, 5), (16, 7.5), (16, 11)], False), ('line', 12, 15, 12, 17.5)],
    'back': [('line', 19, 12, 6, 12), ('poly', [(11, 6), (5, 12), (11, 18)], False)],
    'rotate': [('poly', [(15.8, 5.5), (10.7, 4.6), (6.3, 7.2), (4.5, 12.0), (6.3, 16.8), (10.7, 19.4), (15.8, 18.5)], False), ('poly', [(15.5, 3.5), (19.5, 8.5), (13.5, 9)], True)],
    'redact': [('rect', 3, 5, 18, 14, 2.5), ('line', 7, 12, 17, 12)],
    'crop': [('line', 7, 3, 7, 17), ('line', 7, 17, 21, 17), ('line', 3, 7, 17, 7), ('line', 17, 7, 17, 21)],
    'annotate': [('circle', 12, 12, 8.5), ('line', 8.5, 15.5, 15.5, 8.5), ('line', 14, 8, 16, 10)],
    'canvas': [('rect', 3, 4, 18, 16, 3), ('rect', 8, 9, 8, 6, 1.2)],
    'backdrop': [('rect', 3, 4, 18, 16, 3), ('rect', 7.5, 8.5, 9, 7, 1.5), ('line', 5, 20, 19, 20)],
    'compress': [('line', 4, 4, 10, 10), ('poly', [(4, 9), (4, 4), (9, 4)], False), ('line', 20, 20, 14, 14), ('poly', [(20, 15), (20, 20), (15, 20)], False)],
    'collage': [('rect', 3, 3, 8, 8, 1.5), ('rect', 13, 3, 8, 8, 1.5), ('rect', 3, 13, 8, 8, 1.5), ('rect', 13, 13, 8, 8, 1.5)],
    'tools': [('line', 4, 8, 20, 8), ('line', 4, 16, 20, 16), ('circle', 9, 8, 2.2), ('circle', 15, 16, 2.2)],
    'text': [('line', 5, 6, 19, 6), ('line', 12, 6, 12, 19), ('line', 9, 19, 15, 19)],
    'image': [('rect', 3, 4, 18, 16, 2.5), ('circle', 9, 10, 1.8), ('poly', [(4, 19), (10, 13), (14, 17), (17, 14), (20, 18)], False)],
    'split': [('rect', 3, 5, 7, 14, 1.5), ('rect', 14, 5, 7, 14, 1.5)],
    'merge': [('rect', 3, 8, 11, 12, 1.5), ('rect', 10, 4, 11, 12, 1.5)],
    'copy': [('rect', 8, 8, 12, 12, 2), ('poly', [(16, 8), (16, 5), (5, 5), (5, 16), (8, 16)], False)],
    'shelf': [('line', 3, 18, 21, 18), ('rect', 5, 8, 5, 10, 1), ('rect', 12, 5, 4, 13, 1), ('line', 18, 18, 18, 9)],
    'terminal': [('rect', 3, 5, 18, 14, 3), ('poly', [(7, 10), (10, 12.5), (7, 15)], False), ('line', 12, 15, 16, 15)],
    'eye': [('poly', [(3, 12), (7, 7), (12, 5.5), (17, 7), (21, 12), (17, 17), (12, 18.5), (7, 17)], True), ('circle', 12, 12, 2.6)],
    'tag': [('poly', [(4, 4), (12, 4), (21, 13), (13, 21), (4, 12)], True), ('circle', 8.5, 8.5, 1.5)],
}


def draw_icon(kind: str, color: str, size: int = 20) -> QPixmap:
    ratio = 2
    pixmap = QPixmap(size * ratio, size * ratio)
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.scale(size / 24, size / 24)
    pen = QPen(QColor(color), 1.7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    for shape in ICON_SHAPES.get(kind, []):
        name = shape[0]
        if name == 'rect':
            _, x, y, w, h, radius = shape
            painter.drawRoundedRect(QRectF(x, y, w, h), radius, radius)
        elif name == 'line':
            painter.drawLine(QPointF(shape[1], shape[2]), QPointF(shape[3], shape[4]))
        elif name == 'circle':
            painter.drawEllipse(QPointF(shape[1], shape[2]), shape[3], shape[3])
        elif name == 'poly':
            points = QPolygonF([QPointF(x, y) for x, y in shape[1]])
            painter.drawPolygon(points) if shape[2] else painter.drawPolyline(points)
    painter.end()
    return pixmap


def category_icon(kind: str, normal: str, active: str, size: int = 20) -> QIcon:
    icon = QIcon()
    icon.addPixmap(draw_icon(kind, normal, size), QIcon.Mode.Normal, QIcon.State.Off)
    icon.addPixmap(draw_icon(kind, active, size), QIcon.Mode.Normal, QIcon.State.On)
    icon.addPixmap(draw_icon(kind, normal, size), QIcon.Mode.Disabled, QIcon.State.Off)
    return icon
