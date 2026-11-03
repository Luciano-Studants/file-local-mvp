"""Menu radial de fatias, exibido junto ao arquivo selecionado ou embutido no painel."""
from __future__ import annotations
import ctypes
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from PySide6.QtCore import QDir, QPointF, QRectF, QTimer, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QCursor, QFont, QFontMetrics, QGuiApplication, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from engine import COLLAGE_MAX

import theme
import tool_registry
from icons import draw_icon

IMAGE_SUFFIXES = {'.png', '.jpg', '.jpeg', '.webp', '.tif', '.tiff', '.bmp', '.avif', '.svg', '.svgz', '.ai', '.emf', '.wmf', '.heic', '.heif', '.hif'}


# ícone (de icons.py) por alvo: só as ferramentas têm ícone; as conversões de formato ficam só com texto
ACTION_ICONS = {
    **{spec.action: spec.icon for spec in tool_registry.IMAGE_TOOLS}, **{spec.target: spec.icon for spec in tool_registry.IMAGE_TOOLS},
    **{tool_registry.group_action(group): icon for group, (_label, _tip, icon) in tool_registry.GROUPS.items()}, '__group_back__': 'back',
    **{tool_registry.pdf_group_action(group): icon for group, (_label, _tip, icon, _members) in tool_registry.PDF_GROUPS.items()},
    **{target: icon for _l, _t, _i, members in tool_registry.PDF_GROUPS.values() for target, _label, _tip, icon in members},
    '__panel__': 'tools', 'PDF → Text': 'text', 'PDF → Images': 'image', 'Split PDF': 'split', '__panel_merge__': 'merge', 'Merge PDFs': 'merge',
    '__copy_paths__': 'copy', '__copy_files__': 'copy', '__copy_group__': 'copy', '__shelf_add__': 'shelf', '__open_terminal__': 'terminal',
}


BACK_TARGET = '__group_back__'
COPY_GROUP_TARGET = '__copy_group__'      # «Copiar» agrupa «Caminhos» e «Arquivos» para a roda não passar de 8 fatias


@dataclass(frozen=True)
class RadialAction:
    label: str
    target: str
    description: str = ''
    icon: str = ''
    children: tuple = ()             # fatia de grupo: abre uma sub-roda com estas ações

    def __post_init__(self):
        if not self.icon:
            object.__setattr__(self, 'icon', ACTION_ICONS.get(self.target, ''))


def _conversion(label: str, target: str, name: str | None = None) -> RadialAction:
    return RadialAction(label, target, f'Converter para {name or label}')


def actions_for_file(path: str, capabilities: dict | None = None) -> list[RadialAction]:
    suffix = Path(path).suffix.lower()
    if suffix in IMAGE_SUFFIXES:
        if capabilities is not None and not capabilities.get('images', (False, 'Pillow indisponível.'))[0]:
            return [RadialAction('Imagem indisponível', '__capability_images__'), RadialAction('Mais', '__panel__')]
        return [
            _conversion('JPEG', 'JPEG'),
            _conversion('PNG', 'PNG'),
            _conversion('WebP', 'WEBP'),
            _conversion('TIFF', 'TIFF'),
            _conversion('BMP', 'BMP'),
            _conversion('PDF', 'Image → PDF'),
            RadialAction('Ferramentas', '__panel__', 'Abrir o painel de ferramentas'),
        ]
    if suffix == '.pdf':
        if capabilities is not None and not capabilities.get('pdf', (False, 'pypdf indisponível.'))[0]:
            return [RadialAction('PDF indisponível', '__capability_pdf__'), RadialAction('Mais', '__panel__')]
        return [
            RadialAction('Texto', 'PDF → Text', 'Extrair o texto das páginas'),
            RadialAction('Imagens', 'PDF → Images', 'Salvar cada página como imagem'),
            RadialAction('Separar', 'Split PDF', 'Criar um PDF por página'),
            RadialAction('Unir…', '__panel_merge__', 'Combinar PDFs no painel'),
            RadialAction('Ferramentas', '__panel__', 'Abrir o painel de ferramentas'),
        ]
    return [RadialAction('Painel', '__panel__', 'Abrir o painel de ferramentas')]


def flatten_actions(actions) -> list[RadialAction]:
    """Ações de primeiro nível com as filhas dos grupos expandidas no lugar do grupo (útil para testes e buscas)."""
    flat = []
    for action in actions:
        flat.extend(action.children if action.children else [action])
    return flat


def group_back_action() -> RadialAction:
    return RadialAction('Voltar', BACK_TARGET, 'Voltar ao menu anterior')


def image_tool_actions(selection_only: bool = False, engine_targets: bool = False) -> list[RadialAction]:
    """Fatias de primeiro nível das ferramentas de imagem; os grupos trazem as ferramentas como filhas."""
    actions = []
    for entry in tool_registry.wheel_layout(selection_only):
        if entry.startswith(tool_registry.GROUP_PREFIX):
            group = entry[len(tool_registry.GROUP_PREFIX):-2]
            label, tip, _icon = tool_registry.GROUPS[group]
            children = tuple(RadialAction(spec.label, spec.target if engine_targets else spec.action, spec.tip) for spec in tool_registry.group_members(group, selection_only))
            actions.append(RadialAction(label, entry, tip, children=children))
        else:
            spec = tool_registry.BY_TARGET[entry]
            actions.append(RadialAction(spec.label, spec.target if engine_targets else spec.action, spec.tip))
    return actions


def pdf_tool_actions() -> list[RadialAction]:
    """Fatias de primeiro nível das operações de PDF; cada grupo abre uma sub-roda com as operações como filhas."""
    actions = []
    for group, (label, tip, _icon, members) in tool_registry.PDF_GROUPS.items():
        children = tuple(RadialAction(member_label, target, member_tip) for target, member_label, member_tip, _member_icon in members)
        actions.append(RadialAction(label, tool_registry.pdf_group_action(group), tip, children=children))
    return actions


def actions_for_selection(paths: list[str], capabilities: dict | None = None) -> list[RadialAction]:
    """Ferramentas do tipo de arquivo mais ações comuns; aberto por Shift+F9."""
    suffixes = {Path(path).suffix.lower() for path in paths}
    if len(paths) == 1 and suffixes & IMAGE_SUFFIXES:
        image_ok = capabilities is None or capabilities.get('images', (False, 'Pillow indisponível.'))[0]
        if image_ok:
            actions = image_tool_actions(selection_only=True)
        else:
            actions = [RadialAction('Imagem indisponível', '__capability_images__')]
    elif 2 <= len(paths) <= COLLAGE_MAX and suffixes <= IMAGE_SUFFIXES:
        image_ok = capabilities is None or capabilities.get('images', (False, 'Pillow indisponível.'))[0]
        collage = tool_registry.BY_TARGET['Collage → PNG']
        onepdf = tool_registry.BY_TARGET['Images → One PDF']
        actions = [RadialAction(collage.label, collage.action, collage.tip), RadialAction(onepdf.label, onepdf.action, onepdf.tip)] if image_ok else [RadialAction('Imagem indisponível', '__capability_images__')]
    elif len(paths) == 1 and suffixes == {'.pdf'}:
        pdf_ok = capabilities is None or capabilities.get('pdf', (False, 'pypdf indisponível.'))[0]
        actions = [
            RadialAction('Texto', 'PDF → Text', 'Extrair o texto das páginas'),
            RadialAction('Imagens', 'PDF → Images', 'Salvar cada página como imagem'),
            RadialAction('Separar', 'Split PDF', 'Criar um PDF por página'),
            RadialAction('Unir…', '__panel_merge__', 'Combinar PDFs no painel'),
        ] if pdf_ok else [RadialAction('PDF indisponível', '__capability_pdf__')]
    else:
        actions = []
    actions = [
        *actions,
        RadialAction('Copiar', COPY_GROUP_TARGET, 'Copiar os caminhos como texto ou os arquivos para colar no Explorer', children=(
            RadialAction('Caminhos', '__copy_paths__', 'Copiar caminhos como texto'),
            RadialAction('Arquivos', '__copy_files__', 'Copiar referências para colar no Explorer'),
        )),
        RadialAction('Prateleira', '__shelf_add__', 'Guardar na prateleira da sessão'),
    ]
    if len(paths) == 1:
        if capabilities is None or capabilities.get('terminal', (False, 'Terminal indisponível.'))[0]:
            actions.append(RadialAction('Terminal', '__open_terminal__', 'Abrir terminal na pasta'))
        else:
            actions.append(RadialAction('Terminal indisponível', '__capability_terminal__'))
    return actions


def should_dismiss_radial(cursor_inside: bool, left_button_down: bool, escape_down: bool) -> bool:
    """Predicado puro para o fechamento global por Esc/clique fora."""
    return bool(escape_down or (left_button_down and not cursor_inside))


def slice_index_at(dx: float, dy: float, count: int, inner: float, outer: float) -> int:
    """Índice da fatia sob o ponto (dx, dy) relativo ao centro; -1 fora do anel.

    A fatia 0 fica centrada no topo e as demais seguem no sentido horário.
    """
    if count < 1:
        return -1
    distance = math.hypot(dx, dy)
    if distance < inner or distance > outer:
        return -1
    clockwise_from_top = math.degrees(math.atan2(dx, -dy)) % 360
    size = 360 / count
    return int(((clockwise_from_top + size / 2) % 360) // size)


class RadialWheel(QWidget):
    """Roda de fatias desenhada à mão: hover laranja, rótulo central e navegação por teclado."""
    hovered = Signal(int)
    activated = Signal(int)
    dismissed = Signal()
    dropped = Signal(int, list)          # (índice da fatia, caminhos locais soltos nela)
    navigated = Signal()                 # abriu ou fechou uma sub-roda

    def __init__(self, actions: Iterable[RadialAction], center_text: str = '', diameter: int = 340,
                 disabled: Iterable[int] = (), parent: QWidget | None = None):
        super().__init__(parent)
        self.actions = list(actions)
        self.default_center = center_text
        self.disabled = set(disabled)
        self.hover_index = -1
        self.diameter = diameter
        self.setFixedSize(diameter, diameter)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setAcceptDrops(True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAccessibleName('Menu radial')
        self._keyboard_focus = False
        self._root_actions: list[RadialAction] | None = None   # raiz guardada enquanto uma sub-roda está aberta
        self._root_disabled: set[int] = set()
        self._root_center = ''

    @property
    def in_group(self) -> bool:
        return self._root_actions is not None

    def open_group(self, index: int) -> bool:
        """Troca a roda pelas ações do grupo (mais a fatia Voltar). Devolve False se a fatia não for um grupo."""
        if self.in_group or not 0 <= index < len(self.actions) or not self.actions[index].children:
            return False
        group = self.actions[index]
        self._root_actions, self._root_disabled, self._root_center = self.actions, self.disabled, self.default_center
        self.actions = list(group.children) + [group_back_action()]
        self.disabled = set()
        self.default_center = group.label
        self._after_navigation()
        return True

    def close_group(self) -> bool:
        if not self.in_group:
            return False
        self.actions, self.disabled, self.default_center = self._root_actions, self._root_disabled, self._root_center
        self._root_actions = None
        self._after_navigation()
        return True

    def _after_navigation(self) -> None:
        self.hover_index = -1
        self.hovered.emit(-1)                        # quem mostra legenda volta ao texto padrão
        self.navigated.emit()
        self.update()

    def set_diameter(self, diameter: int) -> None:
        self.diameter = diameter
        self.setFixedSize(diameter, diameter)
        self.update()

    # --- geometria -------------------------------------------------
    @property
    def outer_radius(self) -> float:
        return self.diameter / 2 - 22

    @property
    def inner_radius(self) -> float:
        return self.outer_radius * 0.45

    def slice_at(self, point: QPointF) -> int:
        center = self.rect().center()
        return slice_index_at(point.x() - center.x() - 0.5, point.y() - center.y() - 0.5,
                              len(self.actions), self.inner_radius, self.outer_radius)

    def slice_center(self, index: int) -> QPointF:
        """Centro da fatia em coordenadas do widget (útil para testes e dicas)."""
        angle = math.radians(index * 360 / max(1, len(self.actions)))
        radius = (self.inner_radius + self.outer_radius) / 2
        center = QPointF(self.width() / 2, self.height() / 2)
        return QPointF(center.x() + math.sin(angle) * radius, center.y() - math.cos(angle) * radius)

    def _slice_path(self, index: int) -> QPainterPath:
        count = max(1, len(self.actions))
        size = 360 / count
        pad = 5.0                                    # raio de arredondamento (via traço)
        outer, inner = self.outer_radius - pad - 1, self.inner_radius + pad + 1
        gap = 2.2 + (pad * 2 / max(outer, 1)) * 57.3  # compensa o traço para manter o vão constante
        start = index * size - size / 2 + gap / 2
        sweep = size - gap
        center = QPointF(self.width() / 2, self.height() / 2)
        outer_rect = QRectF(center.x() - outer, center.y() - outer, outer * 2, outer * 2)
        inner_rect = QRectF(center.x() - inner, center.y() - inner, inner * 2, inner * 2)
        path = QPainterPath()
        path.arcMoveTo(outer_rect, 90 - start)
        path.arcTo(outer_rect, 90 - start, -sweep)
        path.arcTo(inner_rect, 90 - (start + sweep), sweep)
        path.closeSubpath()
        return path

    # --- estado ----------------------------------------------------
    def set_hover(self, index: int) -> None:
        if index != self.hover_index:
            self.hover_index = index
            self.hovered.emit(index)
            self.update()

    def center_text(self) -> str:
        if 0 <= self.hover_index < len(self.actions):
            return self.actions[self.hover_index].label
        return self.default_center

    def set_default_center(self, text: str) -> None:
        self.default_center = text
        self.update()

    def activate(self, index: int) -> None:
        if 0 <= index < len(self.actions) and index not in self.disabled:
            action = self.actions[index]
            if action.children:
                self.open_group(index)
            elif action.target == BACK_TARGET:
                self.close_group()
            else:
                self.activated.emit(index)

    def focusInEvent(self, event):
        self._keyboard_focus = event.reason() in (Qt.FocusReason.TabFocusReason, Qt.FocusReason.BacktabFocusReason, Qt.FocusReason.PopupFocusReason)
        super().focusInEvent(event)

    # --- arrastar e soltar arquivos sobre uma fatia -------------------------
    @staticmethod
    def _local_paths(mime) -> list[str]:
        if mime is None or not mime.hasUrls():
            return []
        # Qt devolve barras normais (C:/pasta/a.png); o resto do app compara e deduplica caminhos no formato nativo do Windows
        return [QDir.toNativeSeparators(url.toLocalFile()) for url in mime.urls() if url.isLocalFile() and url.toLocalFile()]

    def _accepts_drop(self, index: int) -> bool:
        action = self.actions[index]
        return not action.children and action.target != BACK_TARGET     # grupos e «Voltar» não recebem arquivos

    def dragEnterEvent(self, event):
        if self._local_paths(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        index = self.slice_at(event.position())
        self.set_hover(index)
        if index >= 0 and index not in self.disabled and self._accepts_drop(index):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        self.set_hover(-1)
        event.accept()

    def dropEvent(self, event):
        index = self.slice_at(event.position())
        paths = self._local_paths(event.mimeData())
        self.set_hover(-1)
        if index >= 0 and index not in self.disabled and paths and self._accepts_drop(index):
            event.acceptProposedAction()
            self.dropped.emit(index, paths)
        else:
            event.ignore()

    # --- eventos ---------------------------------------------------
    def mouseMoveEvent(self, event):
        self.set_hover(self.slice_at(event.position()))
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        self.set_hover(-1)
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            center = self.rect().center()
            distance = math.hypot(event.position().x() - center.x(), event.position().y() - center.y())
            if distance > self.outer_radius + 6:
                self.dismissed.emit()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            index = self.slice_at(event.position())
            if index >= 0:
                self.activate(index)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        count = len(self.actions)
        key = event.key()
        if count and key in (Qt.Key.Key_Right, Qt.Key.Key_Down, Qt.Key.Key_Tab):
            self.set_hover((self.hover_index + 1) % count)
        elif count and key in (Qt.Key.Key_Left, Qt.Key.Key_Up, Qt.Key.Key_Backtab):
            self.set_hover((self.hover_index - 1) % count if self.hover_index >= 0 else count - 1)
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.activate(self.hover_index)
        elif key in (Qt.Key.Key_Escape, Qt.Key.Key_Backspace) and self.in_group:
            self.close_group()
        else:
            super().keyPressEvent(event)
            return
        event.accept()

    # --- desenho ---------------------------------------------------
    @staticmethod
    def _vertical_gradient(rect: QRectF, top: str, bottom: str, alpha: int = 255) -> QLinearGradient:
        gradient = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        first, second = QColor(top), QColor(bottom)
        first.setAlpha(alpha); second.setAlpha(alpha)
        gradient.setColorAt(0, first); gradient.setColorAt(1, second)
        return gradient

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        center = QPointF(self.width() / 2, self.height() / 2)
        radius = self.outer_radius
        # sombra suave
        painter.setPen(Qt.PenStyle.NoPen)
        for step in range(9, 0, -1):
            painter.setBrush(QColor(60, 30, 10, 2 + (9 - step)))
            grow = step * 1.4 + 6
            painter.drawEllipse(QPointF(center.x(), center.y() + 4), radius + grow, radius + grow)
        # aro de vidro: faixa âmbar com borda clara
        rim_rect = QRectF(center.x() - radius - 8, center.y() - radius - 8, (radius + 8) * 2, (radius + 8) * 2)
        painter.setBrush(self._vertical_gradient(rim_rect, theme.RIM_EDGE, theme.RIM, 235))
        painter.setPen(QPen(QColor(255, 255, 255, 120), 1.2))
        painter.drawEllipse(center, radius + 9, radius + 9)
        painter.setBrush(QColor(theme.RIM)); painter.setPen(QPen(QColor(255, 255, 255, 90), 1))
        painter.drawEllipse(center, radius + 1, radius + 1)

        count = len(self.actions)
        label_font = QFont(self.font()); label_font.setPixelSize(max(9, round(self.diameter * 0.03))); label_font.setWeight(QFont.Weight.Bold)
        label_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.5)
        icon_size = max(14, round(self.diameter * 0.058))
        for index, action in enumerate(self.actions):
            hot = index == self.hover_index and index not in self.disabled
            muted = index in self.disabled
            path = self._slice_path(index)
            bounds = path.boundingRect()
            if hot:
                brush = self._vertical_gradient(bounds, theme.PETAL_HOT_TOP, theme.PETAL_HOT_BOTTOM)
            else:
                brush = self._vertical_gradient(bounds, theme.PETAL_TOP, theme.PETAL_BOTTOM, 150 if muted else 238)
            painter.setPen(QPen(QBrush(brush), 8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            painter.setBrush(brush)
            painter.drawPath(path)
            if index == self.hover_index and index in self.disabled:
                painter.setPen(QPen(QColor(theme.LINE_STRONG), 1.4)); painter.setBrush(Qt.BrushStyle.NoBrush); painter.drawPath(path)
            anchor = self.slice_center(index)
            chord = 2 * math.pi * ((self.inner_radius + radius) / 2) / max(count, 1)
            width = max(68.0 if count >= 9 else 54.0, min(chord - 14, radius - self.inner_radius - 6))
            text = action.label.upper() + ('\u00a0›' if action.children else '')
            fitted = QFont(label_font)
            longest = max(text.split() or [''], key=len)
            while fitted.pixelSize() > 8 and QFontMetrics(fitted).horizontalAdvance(longest) > width:
                fitted.setPixelSize(fitted.pixelSize() - 1)
            color = '#ffffff' if hot else (theme.DISABLED if muted else theme.PETAL_TEXT)
            painter.setFont(fitted)
            painter.setPen(QColor(color))
            if action.icon:
                painter.drawPixmap(QPointF(anchor.x() - icon_size / 2, anchor.y() - icon_size - 2), draw_icon(action.icon, color, icon_size))
                box = QRectF(anchor.x() - width / 2, anchor.y() + 2, width, 34)
                painter.drawText(box, int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop) | int(Qt.TextFlag.TextWordWrap), text)
            else:
                box = QRectF(anchor.x() - width / 2, anchor.y() - 24, width, 48)
                painter.drawText(box, int(Qt.AlignmentFlag.AlignCenter) | int(Qt.TextFlag.TextWordWrap), text)

        # miolo âmbar com pílula (tamanho do arquivo ou nome da ação sob o mouse)
        hub = self.inner_radius - 3
        hub_rect = QRectF(center.x() - hub, center.y() - hub, hub * 2, hub * 2)
        painter.setPen(QPen(QColor(theme.HUB_EDGE), 3))
        painter.setBrush(self._vertical_gradient(hub_rect, theme.HUB_EDGE, theme.HUB, 240))
        painter.drawEllipse(center, hub, hub)
        pill_width = self.inner_radius * 1.62
        pill = QRectF(center.x() - pill_width / 2, center.y() - 17, pill_width, 34)
        painter.setPen(QPen(QColor(255, 255, 255, 140), 1))
        painter.setBrush(QColor(theme.PILL))
        painter.drawRoundedRect(pill, 17, 17)
        center_font = QFont(self.font()); center_font.setPixelSize(max(10, round(self.diameter * 0.034))); center_font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(center_font)
        painter.setPen(QColor(theme.PETAL_TEXT))
        shown = QFontMetrics(center_font).elidedText(self.center_text(), Qt.TextElideMode.ElideMiddle, int(pill_width - 18))
        painter.drawText(pill, int(Qt.AlignmentFlag.AlignCenter), shown)
        if self.hasFocus() and self._keyboard_focus and self.hover_index < 0:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(theme.ACCENT), 2, Qt.PenStyle.DotLine))
            painter.drawEllipse(center, radius + 13, radius + 13)


class RadialMenu(QWidget):
    """Janela flutuante com a roda; fecha com Esc, clique fora ou ao escolher uma ação."""
    PAD = 18

    def __init__(self, filename: str, actions: list[RadialAction], callback: Callable[[RadialAction], None],
                 context: str = '', on_drop: Callable[[list[str], RadialAction], None] | None = None):
        super().__init__(None, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setObjectName('RadialMenu')
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.callback = callback
        self.actions = list(actions)
        self.filename = Path(filename).name if filename else ''
        diameter = 380 if len(self.actions) > 6 else 340
        self.on_drop = on_drop
        self.wheel = RadialWheel(self.actions, context or self.filename, diameter, parent=self)
        self.wheel.move(self.PAD, self.PAD)
        self.setFixedSize(diameter + self.PAD * 2, diameter + self.PAD * 2)
        self.wheel.activated.connect(lambda index: self.choose(self.wheel.actions[index]))
        self.wheel.dismissed.connect(self.close)
        self.wheel.dropped.connect(self._dropped)
        self.dismiss_timer = QTimer(self)
        self.dismiss_timer.setInterval(12)
        self.dismiss_timer.timeout.connect(self._poll_global_dismiss)

    @property
    def center_text(self) -> str:
        return self.wheel.center_text()

    def _dropped(self, index: int, paths: list) -> None:
        """Arquivos soltos numa fatia: executa a ação com o que foi solto (ou, sem tratamento de soltar, com a ação normal)."""
        action = self.wheel.actions[index]
        self.close()
        if self.on_drop is not None:
            self.on_drop(list(paths), action)
        else:
            self.callback(action)

    def choose(self, action: RadialAction) -> None:
        self.close()
        self.callback(action)

    def show_at_cursor(self) -> None:
        cursor = QCursor.pos()
        screen = QGuiApplication.screenAt(cursor) or QGuiApplication.primaryScreen()
        if screen:
            area = screen.availableGeometry()
            x = max(area.left(), min(cursor.x() - self.width() // 2, area.right() - self.width() + 1))
            y = max(area.top(), min(cursor.y() - self.height() // 2, area.bottom() - self.height() + 1))
            self.move(x, y)
        else:
            self.move(cursor.x() - self.width() // 2, cursor.y() - self.height() // 2)
        self.show()
        self.activateWindow()
        self.wheel.setFocus(Qt.FocusReason.PopupFocusReason)
        if os.name == 'nt':
            self.dismiss_timer.start()

    def _poll_global_dismiss(self) -> None:
        if os.name != 'nt' or not self.isVisible():
            return
        try:
            user32 = ctypes.windll.user32
            mouse_down = any(user32.GetAsyncKeyState(code) & 0x8000 for code in (0x01, 0x02, 0x04, 0x05, 0x06))
            escape_down = bool(user32.GetAsyncKeyState(0x1B) & 0x8000)
        except Exception:
            return
        inside = self.frameGeometry().contains(QCursor.pos())
        if should_dismiss_radial(inside, mouse_down, escape_down):
            self.close()

    def closeEvent(self, event):
        self.dismiss_timer.stop()
        super().closeEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)
