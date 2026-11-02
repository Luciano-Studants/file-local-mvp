"""Session-only file reference shelf. It never copies or moves file contents."""
from __future__ import annotations
import ntpath
from typing import Callable

from PySide6.QtCore import QMimeData, Qt, QUrl
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import QLabel, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout, QWidget

from file_actions import validate_selection

MAX_SHELF_ITEMS = 100
PATH_ROLE = Qt.ItemDataRole.UserRole


def reference_mime_data(paths: list[str], validator: Callable = validate_selection) -> QMimeData:
    """Build file-reference URLs for a copy drag; never reads file bytes."""
    checked = validator(paths)
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(path) for path in checked])
    return mime


class _ShelfList(QListWidget):
    def __init__(self, owner: 'FileShelf'):
        super().__init__(owner)
        self.owner = owner
        self.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.setDragEnabled(True)
        self.setDragDropMode(QListWidget.DragDropMode.DragOnly)

    def startDrag(self, supported_actions):
        paths = [str(item.data(PATH_ROLE)) for item in self.selectedItems()]
        if not paths:
            return
        try:
            mime = reference_mime_data(paths, self.owner.path_validator)
        except Exception as error:
            self.owner.status.setText('Arraste cancelado: ' + str(error)[:180])
            return
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.CopyAction, Qt.DropAction.CopyAction)


class FileShelf(QWidget):
    """Floating, per-session shelf with local file references and Copy-only drag."""
    def __init__(self, path_validator: Callable = validate_selection):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint)
        self.path_validator = path_validator
        self.setWindowTitle('Arquivo Local — prateleira')
        self.resize(360, 430)
        self.setMinimumSize(300, 260)
        layout = QVBoxLayout(self)
        title = QLabel('Prateleira desta sessão')
        title.setStyleSheet('font-size:18px;font-weight:700;color:#44c7b2')
        layout.addWidget(title)
        help_text = QLabel('Guarda referências locais temporárias. Arraste itens para o Explorer para copiar; nenhum arquivo é movido ou duplicado pelo app.')
        help_text.setWordWrap(True)
        layout.addWidget(help_text)
        self.items = _ShelfList(self)
        self.items.setToolTip('Arraste itens selecionados para outro aplicativo como referências de arquivo (Copy).')
        layout.addWidget(self.items, 1)
        self.status = QLabel('Vazia. Adicione itens pelo radial Shift+F9.')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.remove_button = QPushButton('Remover selecionados')
        self.remove_button.clicked.connect(self.remove_selected)
        layout.addWidget(self.remove_button)
        self.clear_button = QPushButton('Limpar prateleira')
        self.clear_button.clicked.connect(self.clear_items)
        layout.addWidget(self.clear_button)
        self.setStyleSheet('QWidget{background:#171b1b;color:#f3f6f5;font-size:12px} QPushButton{padding:7px;border:1px solid #63716f;border-radius:6px} QListWidget{background:#202727;border:1px solid #45524f;border-radius:6px;padding:6px} QListWidget::item{padding:7px}')

    def paths(self) -> list[str]:
        return [str(self.items.item(index).data(PATH_ROLE)) for index in range(self.items.count())]

    def add_paths(self, paths: list[str]) -> int:
        checked = self.path_validator(paths)
        known = {ntpath.normcase(path) for path in self.paths()}
        added = 0
        limit_reached = False
        for path in checked:
            key = ntpath.normcase(path)
            if key in known:
                continue
            if self.items.count() >= MAX_SHELF_ITEMS:
                limit_reached = True
                break
            item = QListWidgetItem(ntpath.basename(path) or path)
            item.setData(PATH_ROLE, path)
            item.setToolTip(path)
            self.items.addItem(item)
            known.add(key)
            added += 1
        if limit_reached:
            self.status.setText(f'Limite de {MAX_SHELF_ITEMS} referências atingido; os itens existentes não foram alterados.')
        else:
            self.status.setText(f'{self.items.count()} referência(s) na prateleira. Permanecem apenas nesta sessão.')
        return added

    def remove_selected(self):
        for item in self.items.selectedItems():
            self.items.takeItem(self.items.row(item))
        self.status.setText(f'{self.items.count()} referência(s) na prateleira.')

    def clear_items(self):
        self.items.clear()
        self.status.setText('Prateleira limpa. Nenhum arquivo foi alterado.')
