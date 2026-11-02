"""Arrastar para reordenar a lista da colagem e do PDF único (0.9.26)."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PIL import Image
from PySide6.QtCore import QModelIndex
from PySide6.QtWidgets import QApplication, QListWidget

from tray_app import FeaturePanel, JobController


class DragReorderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make(self, target):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        paths = []
        for index, color in enumerate(('red', 'green', 'blue', 'yellow')):
            path = Path(tmp.name) / f'{index}-{color}.png'; Image.new('RGB', (30, 20), color).save(path); paths.append(str(path))
        panel = FeaturePanel(JobController(capabilities={'images': (True, 'ok'), 'pdf': (True, 'ok')})); panel.set_files(paths, target)
        return panel, paths

    def names(self, panel):
        return [Path(p).name for p in panel.files]

    def test_list_accepts_internal_moves(self):
        panel, _ = self.make('Collage → PNG')
        self.assertEqual(panel.collage_list.dragDropMode(), QListWidget.DragDropMode.InternalMove)

    def test_moving_a_row_down_and_up_reorders_files_and_refreshes_numbers(self):
        for target in ('Collage → PNG', 'Images → One PDF'):
            panel, paths = self.make(target); original = [Path(p).name for p in paths]
            panel.collage_list.model().moveRow(QModelIndex(), 0, QModelIndex(), 3)          # 1º item solto antes do 4º → fica na 3ª posição
            self.app.processEvents(); self.app.processEvents()
            self.assertEqual(self.names(panel), [original[1], original[2], original[0], original[3]], target)
            self.assertTrue(panel.collage_list.item(0).text().startswith('1  ·  ' + original[1]))
            panel.collage_list.model().moveRow(QModelIndex(), 3, QModelIndex(), 0)
            self.app.processEvents(); self.app.processEvents()
            self.assertEqual(self.names(panel), [original[3], original[1], original[2], original[0]], target)

    def test_buttons_still_work_after_a_drag(self):
        panel, paths = self.make('Collage → PNG'); original = [Path(p).name for p in paths]
        panel.collage_list.model().moveRow(QModelIndex(), 0, QModelIndex(), 2); self.app.processEvents(); self.app.processEvents()
        panel.collage_list.setCurrentRow(0); panel.move_collage_item(1)
        self.assertEqual(self.names(panel), [original[0], original[1], original[2], original[3]])


if __name__ == '__main__':
    unittest.main()
