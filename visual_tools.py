"""Ferramentas visuais de imagem: recorte com alças, posição de anotação e prévia de canvas."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QImage, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QGraphicsPixmapItem, QGraphicsRectItem, QGraphicsScene,
    QGraphicsSimpleTextItem, QGraphicsView, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
)

import theme
from widgets import ChipGroup

ASPECTS = [('Livre', None), ('Original', 'original'), ('1:1', 1.0), ('4:3', 4 / 3), ('3:2', 3 / 2), ('16:9', 16 / 9), ('9:16', 9 / 16)]      # proporções do recorte (painel e editor)

HANDLE_PX = 9          # tamanho visual das alças, em pixels da tela
HIT_PX = 12            # tolerância de clique nas alças, em pixels da tela
MIN_SELECTION = 2.0    # menor lado aceito para o recorte, em pixels da imagem


def pixmap_from_image_path(path: str) -> tuple[QPixmap, tuple[int, int]]:
    """Abre a imagem com as mesmas regras do motor (EXIF aplicado, limites, caminho local)."""
    from engine import open_image, source_file
    from PIL.ImageQt import ImageQt
    validated = source_file(path)
    with open_image(validated) as opened:
        qimage = QImage(ImageQt(opened.copy()))
        size = opened.size
    if qimage.isNull():
        raise ValueError('Não foi possível criar o preview desta imagem.')
    return QPixmap.fromImage(qimage), size


def collage_layout_pixmap(names: list[str], columns: int, cell: int, gap: int, background: str, max_side: int = 900, thumbs: list | None = None) -> QPixmap:
    """Prévia da colagem: o mesmo layout do motor (`engine.collage_layout`), com células numeradas na ordem da lista.

    `thumbs` (opcional) traz, por imagem, `(miniatura QPixmap, (largura, altura) original)` ou None; a miniatura é desenhada inteira,
    centralizada e sem ampliar além do tamanho original, como faz o motor. Sem miniatura a célula mostra só o número e o nome."""
    from engine import collage_layout
    (width, height), origins = collage_layout(len(names), columns, cell, gap)
    scale = min(1.0, max_side / max(width, height))
    pixmap = QPixmap(max(1, round(width * scale)), max(1, round(height * scale)))
    color = QColor(background)
    pixmap.fill(color if color.isValid() else QColor('#ffffff'))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    font = QFont(); font.setPixelSize(max(9, round(cell * scale * 0.14))); painter.setFont(font)
    for number, ((x, y), name) in enumerate(zip(origins, names), start=1):
        rect = QRectF(x * scale, y * scale, cell * scale, cell * scale)
        painter.setPen(QPen(QColor(theme.ACCENT), 1.5)); painter.setBrush(QColor(theme.ACCENT_SOFT))
        painter.drawRoundedRect(rect, 4, 4)
        thumb = thumbs[number - 1] if thumbs and number - 1 < len(thumbs) else None
        if thumb is not None:
            small, (orig_w, orig_h) = thumb
            fit = min(1.0, cell / max(orig_w, orig_h, 1))
            draw_w, draw_h = max(1.0, orig_w * fit * scale), max(1.0, orig_h * fit * scale)
            target = QRectF(rect.center().x() - draw_w / 2, rect.center().y() - draw_h / 2, draw_w, draw_h)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            painter.drawPixmap(target, small, QRectF(small.rect()))
            badge_size = max(16.0, min(26.0, font.pixelSize() * 1.5))
            badge = QRectF(rect.left() + 3, rect.top() + 3, badge_size, badge_size)
            painter.setPen(Qt.PenStyle.NoPen); painter.setBrush(QColor(theme.ACCENT))
            painter.drawRoundedRect(badge, 5, 5)
            badge_font = QFont(font); badge_font.setPixelSize(max(8, round(badge_size * 0.6))); badge_font.setBold(True)
            painter.setFont(badge_font); painter.setPen(QColor('#ffffff')); painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, str(number)); painter.setFont(font)
            continue
        painter.setPen(QColor(theme.TEXT))
        label = painter.fontMetrics().elidedText(f'{number}  {name}', Qt.TextElideMode.ElideMiddle, max(10, int(rect.width() - 8)))
        painter.drawText(rect.adjusted(4, 4, -4, -4), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, label)
    painter.end()
    return pixmap


def pdf_pages_pixmap(names: list[str], page: str, margin_mm: int, thumbs: list | None = None, max_side: int = 900) -> QPixmap:
    """Prévia do PDF: uma folha por imagem, na ordem da lista, com a mesma geometria do motor (`engine.pdf_page_pixels`): tamanho da página,
    orientação conforme a imagem, margem e imagem ajustada à área útil. `thumbs` como em `collage_layout_pixmap`; sem miniatura a folha mostra o nome."""
    import math
    from engine import pdf_page_pixels
    count = max(1, len(names))
    sizes = []
    for index in range(count):
        thumb = thumbs[index] if thumbs and index < len(thumbs) else None
        sizes.append(thumb[1] if thumb is not None else (3, 4))
    layouts = [pdf_page_pixels(page, size, margin_mm) for size in sizes]
    columns = max(1, min(4, math.ceil(math.sqrt(count)))); rows = math.ceil(count / columns)
    box_w = max(layout[0][0] for layout in layouts); box_h = max(layout[0][1] for layout in layouts)
    gap = 0.12
    unit = min(max_side / (columns * box_w * (1 + gap)), max_side / (rows * box_h * (1 + gap)))
    cell_w, cell_h = box_w * unit * (1 + gap), box_h * unit * (1 + gap)
    pixmap = QPixmap(max(1, round(columns * cell_w)), max(1, round(rows * cell_h)))
    pixmap.fill(QColor(theme.STAGE))
    painter = QPainter(pixmap); painter.setRenderHint(QPainter.RenderHint.Antialiasing); painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    font = QFont(); font.setPixelSize(max(9, round(min(cell_w, cell_h) * 0.07))); painter.setFont(font)
    for index, ((page_w, page_h), (ax, ay, aw, ah)) in enumerate(layouts):
        column, row = index % columns, index // columns
        left = column * cell_w + (cell_w - page_w * unit) / 2; top = row * cell_h + (cell_h - page_h * unit) / 2
        sheet = QRectF(left, top, page_w * unit, page_h * unit)
        painter.setPen(Qt.PenStyle.NoPen); painter.setBrush(QColor(0, 0, 0, 40)); painter.drawRect(sheet.translated(3, 3))
        painter.setPen(QPen(QColor(theme.LINE_STRONG), 1)); painter.setBrush(QColor('#ffffff')); painter.drawRect(sheet)
        thumb = thumbs[index] if thumbs and index < len(thumbs) else None
        if thumb is not None:
            small, (orig_w, orig_h) = thumb
            if page == 'image':
                target = sheet
            else:
                fit = min(aw / orig_w, ah / orig_h); draw_w, draw_h = orig_w * fit * unit, orig_h * fit * unit
                target = QRectF(sheet.left() + (ax + aw / 2) * unit - draw_w / 2, sheet.top() + (ay + ah / 2) * unit - draw_h / 2, draw_w, draw_h)
            painter.drawPixmap(target, small, QRectF(small.rect()))
        else:
            painter.setPen(QColor(theme.TEXT))
            painter.drawText(sheet.adjusted(4, 4, -4, -4), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, names[index] if index < len(names) else '')
        badge_size = max(16.0, font.pixelSize() * 1.6); badge = QRectF(sheet.left() + 3, sheet.top() + 3, badge_size, badge_size)
        painter.setPen(Qt.PenStyle.NoPen); painter.setBrush(QColor(theme.ACCENT)); painter.drawRoundedRect(badge, 5, 5)
        badge_font = QFont(font); badge_font.setPixelSize(max(8, round(badge_size * 0.6))); badge_font.setBold(True)
        painter.setFont(badge_font); painter.setPen(QColor('#ffffff')); painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, str(index + 1)); painter.setFont(font)
    painter.end()
    return pixmap


def backdrop_preview_pixmap(source: QPixmap, style: str, custom: str, padding: int, radius: int, shadow: int, ratio: str, max_side: int = 900) -> QPixmap:
    """Prévia da ferramenta Fundo, com a mesma geometria e as mesmas cores do motor; a sombra é aproximada por camadas translúcidas."""
    from engine import backdrop_colors, backdrop_layout
    from PySide6.QtGui import QLinearGradient
    (total_w, total_h), (x, y) = backdrop_layout(source.width(), source.height(), padding, ratio)
    scale = min(1.0, max_side / max(total_w, total_h))
    out_w, out_h = max(1, round(total_w * scale)), max(1, round(total_h * scale))
    pixmap = QPixmap(out_w, out_h)
    kind, colors = backdrop_colors(style, custom if QColor(custom).isValid() else '#ffffff')
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    if kind == 'solid' or len(colors) < 2:
        painter.fillRect(pixmap.rect(), QColor(colors[0]))
    else:
        gradient = QLinearGradient(0, 0, out_w, out_h)
        for position, color in enumerate(colors):
            gradient.setColorAt(position / (len(colors) - 1), QColor(color))
        painter.fillRect(pixmap.rect(), gradient)
    rect = QRectF(x * scale, y * scale, source.width() * scale, source.height() * scale)
    corner = min(radius, min(source.width(), source.height()) // 2) * scale
    if shadow:
        blur = shadow * 0.8 * scale
        offset = shadow * 0.25 * scale
        steps = 12
        painter.setPen(Qt.PenStyle.NoPen)
        for step in range(steps, 0, -1):
            grow = blur * step / steps
            painter.setBrush(QColor(0, 0, 0, max(1, round(255 * 0.38 / steps))))
            painter.drawRoundedRect(rect.adjusted(-grow, -grow + offset, grow, grow + offset), corner + grow, corner + grow)
    clip = QPainterPath()
    clip.addRoundedRect(rect, corner, corner)
    painter.setClipPath(clip)
    painter.drawPixmap(rect.toRect(), source)
    painter.end()
    return pixmap


class ImageStageView(QGraphicsView):
    """Visualizador que ajusta a imagem à janela; a cena usa pixels da imagem original."""

    def __init__(self, pixmap: QPixmap, parent=None):
        super().__init__(parent)
        self.graphics_scene = QGraphicsScene(self)
        self.setScene(self.graphics_scene)
        self.pixmap_item = QGraphicsPixmapItem(pixmap)
        self.pixmap_item.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
        self.graphics_scene.addItem(self.pixmap_item)
        self.graphics_scene.setSceneRect(QRectF(pixmap.rect()))
        self.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setBackgroundBrush(QColor(theme.STAGE))
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setMinimumSize(180, 160)
        self.setMouseTracking(True)
        self._fit()

    def _fit(self):
        rect = self.graphics_scene.sceneRect()
        if rect.isValid() and not rect.isEmpty():
            margin = 6
            self.fitInView(rect.adjusted(-margin, -margin, margin, margin), Qt.AspectRatioMode.KeepAspectRatio)

    def view_scale(self) -> float:
        return max(self.transform().m11(), 1e-6)

    def set_preview_pixmap(self, pixmap: QPixmap):
        self.pixmap_item.setPixmap(pixmap)
        self.pixmap_item.setRotation(0)
        self.pixmap_item.setPos(0, 0)
        self.graphics_scene.setSceneRect(QRectF(pixmap.rect()))
        self._fit()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit()

    def image_bounds(self) -> QRectF:
        return self.pixmap_item.boundingRect()

    def set_rotation(self, degrees: int):
        """Gira a prévia no sentido horário (0/90/180/270), como o motor fará na conversão."""
        pixmap = self.pixmap_item.pixmap()
        width, height = pixmap.width(), pixmap.height()
        swapped = degrees % 180 != 0
        new_w, new_h = (height, width) if swapped else (width, height)
        self.pixmap_item.setTransformOriginPoint(width / 2, height / 2)
        self.pixmap_item.setRotation(degrees)
        self.pixmap_item.setPos((new_w - width) / 2, (new_h - height) / 2)
        self.graphics_scene.setSceneRect(QRectF(0, 0, new_w, new_h))
        self._fit()

    def clamp_to_image(self, point: QPointF) -> QPointF:
        bounds = self.image_bounds()
        return QPointF(min(max(point.x(), bounds.left()), bounds.right()),
                       min(max(point.y(), bounds.top()), bounds.bottom()))


class CropView(ImageStageView):
    """Recorte direto na imagem: arraste para marcar, use as alças para ajustar e o interior para mover."""
    selection_changed = Signal()
    HANDLES = ('nw', 'n', 'ne', 'e', 'se', 's', 'sw', 'w')
    CURSORS = {'nw': Qt.CursorShape.SizeFDiagCursor, 'se': Qt.CursorShape.SizeFDiagCursor,
               'ne': Qt.CursorShape.SizeBDiagCursor, 'sw': Qt.CursorShape.SizeBDiagCursor,
               'n': Qt.CursorShape.SizeVerCursor, 's': Qt.CursorShape.SizeVerCursor,
               'e': Qt.CursorShape.SizeHorCursor, 'w': Qt.CursorShape.SizeHorCursor}

    def __init__(self, pixmap: QPixmap, parent=None):
        super().__init__(pixmap, parent)
        self.crop_rect: QGraphicsRectItem | None = None
        self.drag_start: QPointF | None = None
        self.drag_mode = ''            # 'new', 'move' ou nome de uma alça
        self.drag_origin = QRectF()
        self.drag_anchor = QPointF()
        self.aspect: float | None = None   # largura/altura; None = livre
        self.committed: list[QRectF] = []  # áreas já confirmadas (ferramenta Ocultar), em coordenadas da cena
        self.overlay_item: QGraphicsPixmapItem | None = None  # prévia do resultado da ocultação, sobre a imagem inteira
        self.committed_fill = True         # áreas confirmadas em preto (ocultação); False = só realce (área da assinatura)
        self.dim_outside = True            # escurece fora da seleção (recorte); a ocultação desliga para mostrar o efeito
        self.setCursor(Qt.CursorShape.CrossCursor)

    # --- API pública -----------------------------------------------
    def set_preview_pixmap(self, pixmap: QPixmap):
        self.clear_selection(emit=False)
        self.committed = []
        self.set_overlay(None)
        super().set_preview_pixmap(pixmap)

    def set_overlay(self, pixmap: QPixmap | None):
        """Mostra `pixmap` (qualquer resolução) esticado sobre a imagem inteira; None remove."""
        if pixmap is None or pixmap.isNull():
            if self.overlay_item is not None:
                self.graphics_scene.removeItem(self.overlay_item)
                self.overlay_item = None
            self.viewport().update()
            return
        if self.overlay_item is None:
            self.overlay_item = QGraphicsPixmapItem()
            self.overlay_item.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
            self.overlay_item.setZValue(5)
            self.graphics_scene.addItem(self.overlay_item)
        bounds = self.image_bounds()
        self.overlay_item.setPixmap(pixmap)
        self.overlay_item.setPos(bounds.topLeft())
        self.overlay_item.setScale(bounds.width() / max(1, pixmap.width()))
        self.viewport().update()

    def set_committed(self, rects: list[QRectF]):
        self.committed = [QRectF(r) for r in rects]
        self.viewport().update()

    def clear_selection(self, emit: bool = True):
        if self.crop_rect is not None:
            self.graphics_scene.removeItem(self.crop_rect)
            self.crop_rect = None
        self.drag_start = None
        self.drag_mode = ''
        self.viewport().update()
        if emit:
            self.selection_changed.emit()

    def set_aspect(self, ratio: float | None):
        """Define a proporção do recorte (largura/altura) ou None para livre; reajusta a seleção atual."""
        self.aspect = ratio if ratio and ratio > 0 else None
        if self.aspect and self.crop_rect is not None:
            current = self.crop_rect.rect().normalized()
            if current.width() >= MIN_SELECTION and current.height() >= MIN_SELECTION:
                center = current.center()
                width = min(current.width(), current.height() * self.aspect)
                rect = QRectF(0, 0, width, width / self.aspect)
                rect.moveCenter(center)
                bounds = self.image_bounds()
                rect.moveLeft(min(max(rect.left(), bounds.left()), bounds.right() - rect.width()))
                rect.moveTop(min(max(rect.top(), bounds.top()), bounds.bottom() - rect.height()))
                self.set_selection(rect)
                self.selection_changed.emit()

    def _ratio_rect(self, anchor: QPointF, point: QPointF) -> QRectF:
        """Retângulo a partir de um canto fixo até o ponteiro, respeitando a proporção e a imagem."""
        bounds = self.image_bounds()
        sign_x = 1 if point.x() >= anchor.x() else -1
        sign_y = 1 if point.y() >= anchor.y() else -1
        width, height = abs(point.x() - anchor.x()), abs(point.y() - anchor.y())
        if self.aspect is None:
            return QRectF(anchor, point).normalized()
        if width / self.aspect > height:
            height = width / self.aspect
        else:
            width = height * self.aspect
        room_x = (bounds.right() - anchor.x()) if sign_x > 0 else (anchor.x() - bounds.left())
        room_y = (bounds.bottom() - anchor.y()) if sign_y > 0 else (anchor.y() - bounds.top())
        scale = min(1.0, room_x / width if width else 1.0, room_y / height if height else 1.0)
        width, height = width * scale, height * scale
        return QRectF(anchor, QPointF(anchor.x() + sign_x * width, anchor.y() + sign_y * height)).normalized()

    def set_selection(self, rect: QRectF):
        rect = rect.normalized().intersected(self.image_bounds())
        if self.crop_rect is None:
            self.crop_rect = QGraphicsRectItem()
            self.crop_rect.setPen(QPen(QColor(theme.ACCENT), 0))
            self.crop_rect.setBrush(Qt.BrushStyle.NoBrush)
            self.crop_rect.setZValue(10)
            self.graphics_scene.addItem(self.crop_rect)
        pen = QPen(QColor(theme.ACCENT), 2); pen.setCosmetic(True)
        self.crop_rect.setPen(pen)
        self.crop_rect.setRect(rect)
        self.viewport().update()

    def selected_bounds(self) -> QRectF | None:
        if self.crop_rect is None:
            return None
        rect = self.crop_rect.rect().normalized().intersected(self.image_bounds())
        return rect if rect.width() >= MIN_SELECTION and rect.height() >= MIN_SELECTION else None

    # --- geometria das alças ---------------------------------------
    def handle_points(self, rect: QRectF) -> dict[str, QPointF]:
        cx, cy = rect.center().x(), rect.center().y()
        return {'nw': rect.topLeft(), 'n': QPointF(cx, rect.top()), 'ne': rect.topRight(),
                'e': QPointF(rect.right(), cy), 'se': rect.bottomRight(), 's': QPointF(cx, rect.bottom()),
                'sw': rect.bottomLeft(), 'w': QPointF(rect.left(), cy)}

    def handle_at(self, scene_point: QPointF) -> str:
        if self.crop_rect is None:
            return ''
        rect = self.crop_rect.rect()
        tolerance = HIT_PX / self.view_scale()
        best, best_distance = '', tolerance
        for name, point in self.handle_points(rect).items():
            distance = max(abs(point.x() - scene_point.x()), abs(point.y() - scene_point.y()))
            if distance <= best_distance:
                best, best_distance = name, distance
        return best

    def _hover_cursor(self, scene_point: QPointF):
        name = self.handle_at(scene_point)
        if name:
            self.setCursor(self.CURSORS[name])
        elif self.crop_rect is not None and self.crop_rect.rect().contains(scene_point):
            self.setCursor(Qt.CursorShape.SizeAllCursor)
        else:
            self.setCursor(Qt.CursorShape.CrossCursor)

    # --- mouse -----------------------------------------------------
    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        point = self.mapToScene(event.position().toPoint())
        handle = self.handle_at(point)
        if handle:
            self.drag_mode = handle
            self.drag_origin = QRectF(self.crop_rect.rect())
        elif self.crop_rect is not None and self.crop_rect.rect().contains(point):
            self.drag_mode = 'move'
            self.drag_origin = QRectF(self.crop_rect.rect())
            self.drag_anchor = point
        elif self.image_bounds().contains(point):
            self.drag_mode = 'new'
            self.drag_start = self.clamp_to_image(point)
            self.set_selection(QRectF(self.drag_start, self.drag_start))
        else:
            super().mousePressEvent(event)
            return
        event.accept()

    def mouseMoveEvent(self, event):
        point = self.mapToScene(event.position().toPoint())
        if not self.drag_mode:
            self._hover_cursor(point)
            super().mouseMoveEvent(event)
            return
        bounds = self.image_bounds()
        if self.drag_mode == 'new' and self.drag_start is not None:
            self.set_selection(self._ratio_rect(self.drag_start, self.clamp_to_image(point)))
        elif self.drag_mode == 'move':
            delta = point - self.drag_anchor
            moved = QRectF(self.drag_origin).translated(delta)
            dx = min(max(moved.left(), bounds.left()), bounds.right() - moved.width()) - moved.left()
            dy = min(max(moved.top(), bounds.top()), bounds.bottom() - moved.height()) - moved.top()
            self.set_selection(moved.translated(dx, dy))
        else:
            self.set_selection(self._resized(self.drag_mode, self.clamp_to_image(point)))
        event.accept()

    def _resized(self, handle: str, point: QPointF) -> QRectF:
        origin = self.drag_origin
        if self.aspect is not None:
            corner = {'nw': origin.bottomRight(), 'ne': origin.bottomLeft(), 'se': origin.topLeft(), 'sw': origin.topRight()}
            if handle in corner:
                rect = self._ratio_rect(corner[handle], point)
                return rect if rect.width() >= MIN_SELECTION and rect.height() >= MIN_SELECTION else origin
            # alças laterais: a outra dimensão acompanha pelo centro
            bounds = self.image_bounds()
            center = origin.center()
            if handle in ('e', 'w'):
                width = max(MIN_SELECTION, abs(point.x() - (origin.left() if handle == 'e' else origin.right())))
                width = min(width, bounds.width(), bounds.height() * self.aspect)
                height = width / self.aspect
                rect = QRectF(origin.left() if handle == 'e' else origin.right() - width, center.y() - height / 2, width, height)
            else:
                height = max(MIN_SELECTION, abs(point.y() - (origin.top() if handle == 's' else origin.bottom())))
                height = min(height, bounds.height(), bounds.width() / self.aspect)
                width = height * self.aspect
                rect = QRectF(center.x() - width / 2, origin.top() if handle == 's' else origin.bottom() - height, width, height)
            rect.moveLeft(min(max(rect.left(), bounds.left()), bounds.right() - rect.width()))
            rect.moveTop(min(max(rect.top(), bounds.top()), bounds.bottom() - rect.height()))
            return rect
        left, top, right, bottom = origin.left(), origin.top(), origin.right(), origin.bottom()
        if 'w' in handle:
            left = min(point.x(), right - MIN_SELECTION)
        if 'e' in handle:
            right = max(point.x(), left + MIN_SELECTION)
        if 'n' in handle:
            top = min(point.y(), bottom - MIN_SELECTION)
        if 's' in handle:
            bottom = max(point.y(), top + MIN_SELECTION)
        return QRectF(QPointF(left, top), QPointF(right, bottom))

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.drag_mode:
            self.mouseMoveEvent(event)
            self.drag_start = None
            self.drag_mode = ''
            self.selection_changed.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    # --- desenho sobre a imagem ------------------------------------
    def drawForeground(self, painter: QPainter, _rect: QRectF):
        if self.committed:
            painter.save()
            for number, area in enumerate(self.committed, 1):
                if self.overlay_item is None:
                    painter.fillRect(area, QColor(12, 12, 12, 245) if self.committed_fill else QColor(255, 106, 0, 40))
                edge = QPen(QColor(theme.ACCENT), 1.5); edge.setCosmetic(True); painter.setPen(edge); painter.drawRect(area)
            painter.restore()
        if self.crop_rect is None:
            return
        selection = self.crop_rect.rect().normalized()
        if selection.width() < 1 or selection.height() < 1:
            return
        painter.save()
        outside = QPainterPath()
        outside.addRect(self.image_bounds())
        inside = QPainterPath()
        inside.addRect(selection)
        if self.dim_outside:
            painter.fillPath(outside.subtracted(inside), QColor(15, 20, 22, 120))
        guide = QPen(QColor(255, 255, 255, 150), 1); guide.setCosmetic(True)
        painter.setPen(guide)
        for fraction in (1 / 3, 2 / 3):
            painter.drawLine(QPointF(selection.left() + selection.width() * fraction, selection.top()),
                             QPointF(selection.left() + selection.width() * fraction, selection.bottom()))
            painter.drawLine(QPointF(selection.left(), selection.top() + selection.height() * fraction),
                             QPointF(selection.right(), selection.top() + selection.height() * fraction))
        size = HANDLE_PX / self.view_scale()
        painter.setBrush(QColor('#ffffff'))
        border = QPen(QColor(theme.ACCENT), 2); border.setCosmetic(True)
        painter.setPen(border)
        for point in self.handle_points(selection).values():
            painter.drawRect(QRectF(point.x() - size / 2, point.y() - size / 2, size, size))
        painter.restore()


class AnnotateView(ImageStageView):
    """Escolha da posição do texto clicando ou arrastando na imagem, com o texto em prévia."""
    position_changed = Signal(int, int)

    def __init__(self, pixmap: QPixmap, parent=None):
        super().__init__(pixmap, parent)
        self.text_item = QGraphicsSimpleTextItem('')
        font = QFont(); font.setPixelSize(18)       # mesmo tamanho aproximado usado pelo motor
        self.text_item.setFont(font)
        self.text_item.setZValue(10)
        self.graphics_scene.addItem(self.text_item)
        self.marker = QGraphicsRectItem()
        pen = QPen(QColor(theme.ACCENT), 1.5, Qt.PenStyle.DashLine); pen.setCosmetic(True)
        self.marker.setPen(pen)
        self.marker.setZValue(9)
        self.graphics_scene.addItem(self.marker)
        self.position = QPointF(0, 0)
        self.dragging = False
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.set_text('', '#FF0000')

    def set_preview_pixmap(self, pixmap: QPixmap):
        super().set_preview_pixmap(pixmap)
        self.set_position(0, 0)

    def set_text(self, text: str, color: str, size: int = 18):
        font = QFont(self.text_item.font()); font.setPixelSize(max(8, min(400, size)))
        self.text_item.setFont(font)
        valid = QColor(color).isValid() and len(color) == 7
        self.text_item.setBrush(QBrush(QColor(color) if valid else QColor('#ff0000')))
        self.text_item.setText(text)
        self._update_marker()

    def set_position(self, x: int, y: int):
        bounds = self.image_bounds()
        self.position = QPointF(min(max(x, 0), max(0, bounds.width() - 1)), min(max(y, 0), max(0, bounds.height() - 1)))
        self.text_item.setPos(self.position)
        self._update_marker()

    def _update_marker(self):
        rect = self.text_item.boundingRect()
        if rect.width() < 1:
            rect = QRectF(0, 0, 12, 18)
        self.marker.setRect(QRectF(self.position, rect.size()))
        self.viewport().update()

    def _place(self, event):
        point = self.clamp_to_image(self.mapToScene(event.position().toPoint()))
        self.set_position(round(point.x()), round(point.y()))
        self.position_changed.emit(int(self.position.x()), int(self.position.y()))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.image_bounds().contains(self.mapToScene(event.position().toPoint())):
            self.dragging = True
            self._place(event)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.dragging:
            self._place(event)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.dragging:
            self.dragging = False
            event.accept()
            return
        super().mouseReleaseEvent(event)


class CanvasView(ImageStageView):
    """Prévia do canvas: cor de fundo com a imagem centralizada, como o motor irá gerar."""

    def __init__(self, pixmap: QPixmap, parent=None):
        super().__init__(pixmap, parent)
        self.background_item = QGraphicsRectItem()
        self.background_item.setZValue(-1)
        self.background_item.setPen(QPen(QColor(theme.LINE_STRONG), 0))
        self.graphics_scene.addItem(self.background_item)
        self.invalid = False
        self.image_size = (pixmap.width(), pixmap.height())
        self.set_canvas(pixmap.width(), pixmap.height(), '#FFFFFF')

    def set_preview_pixmap(self, pixmap: QPixmap):
        self.image_size = (pixmap.width(), pixmap.height())
        self.pixmap_item.setPixmap(pixmap)
        self.set_canvas(pixmap.width(), pixmap.height(), '#FFFFFF')

    def set_canvas(self, width: int, height: int, color: str):
        image_w, image_h = self.image_size
        self.invalid = width < image_w or height < image_h
        shown_w, shown_h = max(width, image_w), max(height, image_h)
        valid_color = len(color) == 7 and QColor(color).isValid()
        self.background_item.setBrush(QColor(color if valid_color else '#ffffff'))
        self.background_item.setRect(QRectF(0, 0, shown_w, shown_h))
        self.pixmap_item.setPos((shown_w - image_w) / 2, (shown_h - image_h) / 2)
        self.graphics_scene.setSceneRect(QRectF(0, 0, shown_w, shown_h))
        pen = QPen(QColor('#d92d20') if self.invalid else QColor(theme.LINE_STRONG), 2 if self.invalid else 0)
        pen.setCosmetic(True)
        self.background_item.setPen(pen)
        self._fit()


class CropEditor(QDialog):
    """Janela ampla de recorte: mesma ferramenta do painel, com mais espaço para ajustar."""

    def __init__(self, image_path: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Recortar imagem')
        self.resize(820, 640)
        self.setMinimumSize(600, 480)
        self.coordinates: tuple[int, int, int, int] | None = None
        pixmap, self.image_size = pixmap_from_image_path(image_path)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 14)
        layout.setSpacing(12)
        title = QLabel('Arraste sobre a imagem para marcar a área. Use as alças para ajustar e o interior para mover.')
        title.setObjectName('CropTitle')
        title.setWordWrap(True)
        layout.addWidget(title)
        tools = QHBoxLayout(); tools.setSpacing(10)
        proportion = QLabel('Proporção'); proportion.setObjectName('CropHint')
        self.aspect = ChipGroup([label for label, _ratio in ASPECTS], per_row=7)
        self.aspect.setCurrentIndex(0)
        self.clear_button = QPushButton('Limpar seleção'); self.clear_button.setEnabled(False)
        tools.addWidget(proportion); tools.addWidget(self.aspect, 1); tools.addWidget(self.clear_button)
        layout.addLayout(tools)
        self.view = CropView(pixmap, self)
        layout.addWidget(self.view, 1)
        self.hint = QLabel(self.DEFAULT_HINT)
        self.hint.setObjectName('CropHint')
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel, parent=self)
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('Cancelar')
        self.apply_button = self.buttons.addButton('Aplicar recorte', QDialogButtonBox.ButtonRole.AcceptRole)
        self.apply_button.setObjectName('Primary'); self.apply_button.setDefault(True); self.apply_button.setAutoDefault(True)
        self.apply_button.setEnabled(False)
        self.buttons.accepted.connect(self.accept_crop)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.view.selection_changed.connect(self._selection_changed)
        self.aspect.currentIndexChanged.connect(self._aspect_changed)
        self.clear_button.clicked.connect(self._clear_selection)
        self.setStyleSheet(theme.dialog_stylesheet())

    DEFAULT_HINT = 'A imagem original permanece intacta. O recorte será salvo como um novo arquivo.'

    def _clear_selection(self, _checked=False):
        self.view.clear_selection()          # o bool de clicked não pode virar o argumento emit

    def _aspect_changed(self, index: int):
        ratio = ASPECTS[index][1]
        if ratio == 'original':
            width, height = self.image_size
            ratio = width / height if width and height else None
        self.view.set_aspect(ratio)

    def _selection_changed(self):
        coordinates = selection_to_image_box(self.view, self.image_size)
        self.apply_button.setEnabled(coordinates is not None)
        self.clear_button.setEnabled(coordinates is not None)
        if coordinates:
            x, y, width, height = coordinates
            self.hint.setText(f'Recorte: {width} × {height} px, a partir de ({x}, {y}) numa imagem de {self.image_size[0]} × {self.image_size[1]} px. Ajuste pelas alças ou arraste o interior.')
        else:
            self.hint.setText(self.DEFAULT_HINT)

    def accept_crop(self):
        coordinates = selection_to_image_box(self.view, self.image_size)
        if coordinates is None:
            return
        self.coordinates = coordinates
        self.accept()


def selection_to_image_box(view: CropView, image_size: tuple[int, int]) -> tuple[int, int, int, int] | None:
    """Converte a seleção da cena em (x, y, largura, altura) na imagem já orientada."""
    bounds = view.selected_bounds()
    if bounds is None or not all(image_size):
        return None
    scene = view.image_bounds()
    scale_x = image_size[0] / scene.width()
    scale_y = image_size[1] / scene.height()
    left = max(0, min(image_size[0] - 1, round(bounds.left() * scale_x)))
    top = max(0, min(image_size[1] - 1, round(bounds.top() * scale_y)))
    right = min(image_size[0], round(bounds.right() * scale_x))
    bottom = min(image_size[1], round(bounds.bottom() * scale_y))
    if right <= left or bottom <= top:
        return None
    return left, top, right - left, bottom - top
