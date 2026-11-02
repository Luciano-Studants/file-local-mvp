"""Colagem: miniaturas na prévia e reordenação da lista."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PIL import Image
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

from tray_app import FeaturePanel, JobController
from visual_tools import collage_layout_pixmap


class CollageOrderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.paths = []
        for index, color in enumerate(((220, 0, 0), (0, 200, 0), (0, 0, 220))):
            path = Path(self.tmp.name) / f'img{index}.png'
            Image.new('RGB', (80, 40), color).save(path); self.paths.append(str(path))
        self.controller = JobController(capabilities={'images': (True, 'ok'), 'pdf': (True, 'ok')})
        self.panel = FeaturePanel(self.controller)
        self.panel.set_files(self.paths, 'Collage → PNG')

    def tearDown(self):
        self.panel.allow_close = True; self.panel.close(); self.tmp.cleanup()

    def sent(self):
        captured = {}
        with patch.object(self.controller, 'start_job', side_effect=lambda files, target, options: captured.update(files=files) or True):
            self.panel.run_selected()
        return captured.get('files')

    def test_list_shows_numbered_names_and_buttons_follow_selection(self):
        panel = self.panel
        self.assertEqual([panel.collage_list.item(i).text() for i in range(3)], ['1  ·  img0.png', '2  ·  img1.png', '3  ·  img2.png'])
        self.assertEqual(panel.collage_list.currentRow(), 0)
        self.assertFalse(panel.collage_up_button.isEnabled()); self.assertTrue(panel.collage_down_button.isEnabled())
        panel.collage_list.setCurrentRow(2)
        self.assertTrue(panel.collage_up_button.isEnabled()); self.assertFalse(panel.collage_down_button.isEnabled())

    def test_move_changes_the_order_sent_to_the_job_and_the_preview(self):
        panel = self.panel
        panel.collage_cell.setValue(100); panel.collage_gap.setValue(0); panel.collage_columns.setValue(3)
        before = panel.static_preview.pixmap_item.pixmap().toImage()
        self.assertGreater(before.pixelColor(50, 50).red(), 150)               # primeira célula: img0 (vermelha)
        panel.collage_down_button.click()                                        # img0 desce
        self.assertEqual([Path(p).name for p in panel.files], ['img1.png', 'img0.png', 'img2.png'])
        self.assertEqual(panel.collage_list.currentRow(), 1)
        self.assertEqual(panel.collage_list.item(1).text(), '2  ·  img0.png')
        after = panel.static_preview.pixmap_item.pixmap().toImage()
        self.assertGreater(after.pixelColor(50, 50).green(), 150)               # agora img1 (verde) vem primeiro
        self.assertEqual([Path(p).name for p in self.sent()], ['img1.png', 'img0.png', 'img2.png'])
        panel.collage_list.setCurrentRow(2); panel.collage_up_button.click()
        self.assertEqual([Path(p).name for p in panel.files], ['img1.png', 'img2.png', 'img0.png'])
        self.assertIn('img1.png', panel.files_label.text())

    def test_move_beyond_the_edges_does_nothing(self):
        panel = self.panel
        panel.collage_list.setCurrentRow(0); panel.move_collage_item(-1)
        panel.collage_list.setCurrentRow(2); panel.move_collage_item(1)
        self.assertEqual([Path(p).name for p in panel.files], ['img0.png', 'img1.png', 'img2.png'])

    def test_remove_and_minimum_count(self):
        panel = self.panel
        panel.collage_list.setCurrentRow(1); panel.collage_remove_button.click()
        self.assertEqual([Path(p).name for p in panel.files], ['img0.png', 'img2.png'])
        self.assertEqual(panel.collage_list.count(), 2)
        panel.collage_remove_button.click()
        self.assertEqual(len(panel.files), 1)
        self.assertIn('duas ou mais', panel.preview_image.text())
        self.assertEqual(panel.collage_list.count(), 1)
        with patch.object(self.controller, 'start_job') as start:
            panel.run_selected(); start.assert_not_called()
        for path in self.paths:                                                  # os originais continuam no disco
            self.assertTrue(Path(path).exists())

    def test_too_many_images_can_be_trimmed_from_the_list(self):
        extra = []
        for index in range(13):
            path = Path(self.tmp.name) / f'x{index}.png'; Image.new('RGB', (10, 10)).save(path); extra.append(str(path))
        self.panel.set_files(extra, 'Collage → PNG')
        self.assertEqual(self.panel.collage_list.count(), 13)
        self.assertIn('até 12', self.panel.preview_image.text())
        self.panel.collage_remove_button.click()
        self.assertEqual(len(self.panel.files), 12)
        self.assertEqual(self.panel.stage.currentIndex(), 4)

    def test_preview_draws_thumbnails_without_enlarging_small_images(self):
        small = Image.new('RGB', (20, 10), (255, 0, 0)); small.save(Path(self.tmp.name) / 'small.png')
        thumbs = [self.panel._collage_thumb(str(Path(self.tmp.name) / 'small.png')), None]
        self.assertEqual(thumbs[0][1], (20, 10))
        pixmap = collage_layout_pixmap(['small.png', 'sem.png'], 2, 100, 0, '#ffffff', thumbs=thumbs)
        image = pixmap.toImage()
        self.assertEqual(image.pixelColor(50, 50).red(), 255); self.assertLess(image.pixelColor(50, 50).green(), 60)   # miniatura no centro
        corner = image.pixelColor(30, 20)                                                                              # fora dos 20×10 centrais
        self.assertFalse(corner.red() > 200 and corner.green() < 60)
        placeholder = collage_layout_pixmap(['a', 'b'], 2, 100, 0, '#ffffff', thumbs=None)
        self.assertEqual((placeholder.width(), placeholder.height()), (200, 100))

    def test_unreadable_image_falls_back_to_placeholder(self):
        bad = Path(self.tmp.name) / 'bad.png'; bad.write_bytes(b'nope')
        self.assertIsNone(self.panel._collage_thumb(str(bad)))
        self.panel.set_files([*self.paths, str(bad)], 'Collage → PNG')
        self.assertEqual(self.panel.stage.currentIndex(), 4)


if __name__ == '__main__':
    unittest.main()
