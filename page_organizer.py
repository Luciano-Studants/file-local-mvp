"""Organizar páginas de um PDF: miniaturas que se arrastam, giram, somem e se duplicam; o resultado é uma lista (página, giro) para o motor.

Nada de PDF é aberto neste processo: as miniaturas vêm do worker descartável (`runner.run_pdf_op`), em lotes de 24 páginas numa thread de segundo plano,
e vão aparecendo conforme chegam. A lista de itens É o estado: a ordem dos itens é a ordem final, cada item guarda (página original, giro).
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap, QTransform
from PySide6.QtWidgets import QAbstractItemView, QLabel, QListView, QListWidget, QListWidgetItem, QVBoxLayout, QWidget

import pdfinfo
from pdf_stage import PdfLoadTask

ITEM_SIZE = QSize(104, 148)
ICON_SIZE = QSize(84, 92)
ROLE_ENTRY = Qt.ItemDataRole.UserRole           # (página original a partir de 1, giro em graus, é cópia)
BATCH = pdfinfo.MAX_PREVIEW_PAGES


def _blank_pixmap() -> QPixmap:
    pixmap = QPixmap(ICON_SIZE); pixmap.fill(QColor('#f3f4f6'))
    painter = QPainter(pixmap); painter.setPen(QColor('#d0d3d9')); painter.drawRect(0, 0, pixmap.width() - 1, pixmap.height() - 1); painter.end()
    return pixmap


class PageOrganizer(QWidget):
    changed = Signal()           # a lista mudou (ordem, giro, exclusão, cópia ou carga)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0); layout.setSpacing(8)
        self.summary = QLabel('Abra um PDF para organizar as páginas.')
        self.summary.setObjectName('Muted'); self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.list = QListWidget()
        self.list.setViewMode(QListView.ViewMode.IconMode)
        self.list.setResizeMode(QListView.ResizeMode.Adjust)
        self.list.setMovement(QListView.Movement.Snap)
        self.list.setFlow(QListView.Flow.LeftToRight)
        self.list.setWrapping(True)
        self.list.setSpacing(6)
        self.list.setUniformItemSizes(True)
        self.list.setIconSize(ICON_SIZE)
        self.list.setGridSize(ITEM_SIZE)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.list.setToolTip('Arraste as páginas para mudar a ordem. Selecione várias com Ctrl ou Shift.')
        self.list.model().rowsMoved.connect(lambda *_args: self._refresh_later())
        self.list.itemSelectionChanged.connect(self.changed.emit)
        layout.addWidget(self.list, 1)
        self.path = ''
        self.page_count = 0
        self.loader = None           # testes: chamada síncrona no lugar da thread
        self._pixmaps: dict[int, QPixmap] = {}
        self._token = 0
        self._tasks: list[PdfLoadTask] = []
        self._error = ''
        self._loading = False

    # --- carga ---------------------------------------------------------------
    def load(self, path: str):
        self._token += 1
        self.path = str(path); self.page_count = 0; self._pixmaps = {}; self._error = ''; self._loading = True
        self.list.clear()
        self.summary.setText('Lendo o PDF…')
        self._request(1)
        self.changed.emit()

    def clear(self):
        self._token += 1
        self.path = ''; self.page_count = 0; self._pixmaps = {}; self._error = ''; self._loading = False
        self.list.clear()
        self.summary.setText('Abra um PDF para organizar as páginas.')
        self.changed.emit()

    def _request(self, first: int):
        job = {'op': 'pdf_preview', 'path': self.path, 'thumbs': BATCH, 'first': first, 'page': 0}
        token = self._token
        if self.loader is not None:
            try:
                self._apply(token, first, self.loader(job), '')
            except Exception as error:
                self._apply(token, first, None, str(error)[:300])
            return
        self._tasks = [t for t in self._tasks if t.isRunning()]          # destruir um QThread ativo derruba o programa: guarda as threads
        task = PdfLoadTask(token, job)
        task.finished_with.connect(lambda tok, result, error, f=first: self._apply(tok, f, result, error))
        self._tasks.append(task)
        task.start()

    def _apply(self, token: int, first: int, result, error: str):
        if token != self._token:
            return                                         # resposta de um arquivo já trocado
        if error or result is None:
            self._fail(error or 'Não foi possível ler o PDF.'); return
        info = result.get('info', {})
        if first == 1:
            if info.get('error'):
                self._fail(str(info['error'])); return
            if info.get('encrypted'):
                self._fail('Este PDF está protegido por senha; o Arquivo Local não abre PDFs protegidos.'); return
            pages = info.get('pages') or 0
            if not pages:
                self._fail('Este PDF não tem nenhuma página.'); return
            if pages > pdfinfo.PDF_MAX_PAGES:
                self._fail(f'O PDF tem {pages} páginas; o limite é {pdfinfo.PDF_MAX_PAGES}.'); return
            self.page_count = pages
            for number in range(1, pages + 1):
                self.list.addItem(self._make_item(number, 0, False))
        for entry in result.get('pages', []):
            pixmap = QPixmap()
            if entry.get('kind') == 'thumb' and pixmap.loadFromData(entry['data'], 'PNG'):
                self._pixmaps[int(entry['page'])] = pixmap
        self._refresh_icons()
        if first + BATCH <= self.page_count:
            self._request(first + BATCH)
        else:
            self._loading = False
        self._refresh_summary()
        self.changed.emit()

    def _fail(self, text: str):
        self._error = text; self._loading = False
        self.list.clear(); self.page_count = 0
        self.summary.setText(text)
        self.changed.emit()

    # --- itens ---------------------------------------------------------------------
    def _make_item(self, page: int, rotation: int, copy: bool) -> QListWidgetItem:
        item = QListWidgetItem()
        item.setData(ROLE_ENTRY, (page, rotation, copy))
        item.setSizeHint(ITEM_SIZE)
        item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter)
        self._style(item)
        return item

    def _style(self, item: QListWidgetItem):
        page, rotation, copy = item.data(ROLE_ENTRY)
        base = self._pixmaps.get(page) or _blank_pixmap()
        pixmap = base.transformed(QTransform().rotate(rotation), Qt.TransformationMode.SmoothTransformation) if rotation else base
        pixmap = pixmap.scaled(ICON_SIZE, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        pixmap = QPixmap(pixmap)           # cópia: o contorno é desenhado só na miniatura mostrada, nunca na guardada
        painter = QPainter(pixmap); painter.setPen(QColor('#b9bdc4')); painter.drawRect(0, 0, pixmap.width() - 1, pixmap.height() - 1); painter.end()      # páginas brancas somem no fundo branco
        icon = QIcon()
        for mode in (QIcon.Mode.Normal, QIcon.Mode.Active, QIcon.Mode.Selected):
            icon.addPixmap(pixmap, mode)             # sem isto o Qt tinge de azul a miniatura selecionada
        item.setIcon(icon)
        label = str(page) + (' · cópia' if copy else '') + '\n' + (f'↻{rotation}°' if rotation else ' ')
        item.setText(label)

    def _refresh_icons(self):
        for row in range(self.list.count()):
            self._style(self.list.item(row))

    def _refresh_later(self):
        QTimer.singleShot(0, self._after_move)

    def _after_move(self):
        self._refresh_summary(); self.changed.emit()

    def _refresh_summary(self):
        if self._error:
            return
        kept = self.list.count()
        present = {page for page, _rotation in self.entries()}
        excluded = self.page_count - len(present)
        text = f'{kept} {"página" if kept == 1 else "páginas"} no PDF novo (o original tem {self.page_count}).'
        if excluded:
            text += f' {excluded} {"excluída" if excluded == 1 else "excluídas"}.'
        if self._loading:
            text += ' Carregando miniaturas…'
        self.summary.setText(text)

    # --- leitura do estado ---------------------------------------------------------
    def entries_full(self) -> list[tuple[int, int, bool]]:
        return [tuple(self.list.item(row).data(ROLE_ENTRY)) for row in range(self.list.count())]

    def entries(self) -> list[tuple[int, int]]:
        """(página original, giro em graus) na ordem final."""
        return [(page, rotation) for page, rotation, _copy in self.entries_full()]

    def option_value(self) -> list[str]:
        return [f'{page}:{rotation}' for page, rotation in self.entries()]

    def is_modified(self) -> bool:
        return self.entries() != [(n, 0) for n in range(1, self.page_count + 1)]

    @property
    def error(self) -> str:
        return self._error

    def selected_rows(self) -> list[int]:
        return sorted(self.list.row(item) for item in self.list.selectedItems())

    # --- ações -----------------------------------------------------------------------
    def rotate_selected(self, delta: int):
        rows = self.selected_rows()
        for row in rows:
            item = self.list.item(row); page, rotation, copy = item.data(ROLE_ENTRY)
            item.setData(ROLE_ENTRY, (page, (rotation + delta) % 360, copy)); self._style(item)
        if rows:
            self._after_move()

    def delete_selected(self):
        rows = self.selected_rows()
        if not rows:
            return
        if len(rows) >= self.list.count():
            return                       # o PDF precisa ficar com ao menos uma página
        for row in reversed(rows):
            self.list.takeItem(row)
        self._after_move()

    def duplicate_selected(self):
        rows = self.selected_rows()
        if not rows or self.list.count() + len(rows) > pdfinfo.PDF_MAX_PAGES:
            return
        for offset, row in enumerate(rows):
            page, rotation, _copy = self.list.item(row + offset).data(ROLE_ENTRY)
            self.list.insertItem(row + offset + 1, self._make_item(page, rotation, True))
        self._after_move()

    def move_selected(self, delta: int):
        rows = self.selected_rows()
        if not rows:
            return
        count = self.list.count()
        if (delta < 0 and rows[0] == 0) or (delta > 0 and rows[-1] == count - 1):
            return
        order = list(range(count))
        for row in (rows if delta < 0 else reversed(rows)):
            order[row], order[row + delta] = order[row + delta], order[row]
        items = [self.list.takeItem(0) for _ in range(count)]
        new_rows = []
        for new_row, old_row in enumerate(order):
            self.list.addItem(items[old_row])
            if old_row in rows:
                new_rows.append(new_row)
        for row in new_rows:
            self.list.item(row).setSelected(True)
        self._after_move()

    def select_all(self):
        self.list.selectAll()

    def reset(self):
        """Volta à ordem original, sem giros, com todas as páginas."""
        if not self.page_count:
            return
        self.list.clear()
        for number in range(1, self.page_count + 1):
            self.list.addItem(self._make_item(number, 0, False))
        self._after_move()

    def shutdown(self):
        for task in self._tasks:
            if task.isRunning():
                task.wait(8000)
        self._tasks = [t for t in self._tasks if t.isRunning()]
