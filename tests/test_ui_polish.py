"""Retoques de interface (0.9.28): editor de recorte com proporções e botão principal; lista da colagem; plural do status."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image
from PySide6.QtCore import QRectF
from PySide6.QtWidgets import QApplication

import theme
from tray_app import JobController
from visual_tools import ASPECTS, CropEditor
from workspace_panel import FeaturePanel

APP = QApplication.instance() or QApplication([])


class PolishTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.paths = []
        for index in range(3):
            path = Path(self.tmp.name) / f'f{index}.png'; Image.new('RGB', (400, 300), (index * 60, 80, 120)).save(path); self.paths.append(str(path))

    def test_crop_editor_has_ratios_clear_and_a_primary_default_button(self):
        editor = CropEditor(self.paths[0]); editor.show(); APP.processEvents()
        self.assertEqual(editor.aspect.currentIndex(), 0)
        self.assertEqual(editor.apply_button.objectName(), 'Primary')
        self.assertFalse(editor.apply_button.isEnabled()); self.assertFalse(editor.clear_button.isEnabled())
        editor.view.set_selection(QRectF(40, 30, 200, 120)); editor._selection_changed()
        self.assertTrue(editor.apply_button.isEnabled() and editor.clear_button.isEnabled())
        self.assertIn('a partir de', editor.hint.text())
        editor.aspect.setCurrentIndex(2)                                   # 1:1
        x, y, width, height = editor.view and __import__('visual_tools').selection_to_image_box(editor.view, editor.image_size)
        self.assertLessEqual(abs(width - height), 2)
        editor.clear_button.click(); APP.processEvents()
        self.assertFalse(editor.apply_button.isEnabled()); self.assertEqual(editor.hint.text(), CropEditor.DEFAULT_HINT)

    def test_panel_clear_selection_button_updates_the_fields(self):
        controller = JobController(capabilities={'images': (True, 'ok'), 'pdf': (True, 'ok')}); panel = FeaturePanel(controller)
        panel.resize(1000, 700); panel.show(); panel.set_files(self.paths[:1], 'Crop → PNG'); APP.processEvents()
        panel.crop_preview.set_selection(QRectF(20, 20, 100, 80)); panel._crop_selection_changed()
        self.assertGreater(panel.crop_width.value(), 0)
        panel.clear_crop_button.click(); APP.processEvents()
        self.assertEqual((panel.crop_width.value(), panel.crop_height.value()), (0, 0))

    def test_crop_editor_original_ratio_follows_the_image(self):
        editor = CropEditor(self.paths[0]); editor.view.set_selection(QRectF(20, 20, 100, 100)); editor._selection_changed()
        editor.aspect.setCurrentIndex(1)
        self.assertAlmostEqual(editor.view.aspect, 400 / 300, places=3)

    def test_aspects_are_shared_between_panel_and_editor(self):
        import workspace_panel
        self.assertIs(workspace_panel.ASPECTS, ASPECTS)

    def test_dialog_and_panel_styles_cover_primary_chip_and_list_selection(self):
        for sheet in (theme.dialog_stylesheet(), theme.panel_stylesheet()):
            self.assertIn('QPushButton#Primary', sheet); self.assertIn('QPushButton#Chip:checked', sheet)
        self.assertIn('QListWidget::item:selected', theme.panel_stylesheet())

    def test_collage_list_label_mentions_dragging_and_status_plural(self):
        controller = JobController(capabilities={'images': (True, 'ok'), 'pdf': (True, 'ok')}); panel = FeaturePanel(controller)
        panel.set_files(self.paths[:1], 'PNG'); self.assertEqual(panel.status.text(), '1 arquivo na sessão.')
        panel.set_files(self.paths, 'Collage → PNG'); self.assertEqual(panel.status.text(), '3 arquivos na sessão.')
        self.assertIn('Arraste', panel.collage_list.toolTip())
        self.assertEqual(panel.collage_list.dragDropMode(), panel.collage_list.DragDropMode.InternalMove)


if __name__ == '__main__':
    unittest.main()
