"""Ferramenta Ajustar (Adjust → PNG): motor, validação, painel e roda."""
import hashlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PIL import Image
from PySide6.QtWidgets import QApplication

from engine import ConversionError, TOOL_SUFFIX, adjust_image, adjust_options_from, convert, loss_report
from radial_menu import RadialAction, actions_for_selection, flatten_actions
import tool_registry
from tray_app import FeaturePanel, JobController


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class AdjustEngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def sample(self, name='a.png', mode='RGB'):
        path = self.root / name
        im = Image.new('RGB', (4, 2), (100, 150, 50)); im.putpixel((0, 0), (200, 10, 10)); im.putpixel((3, 1), (10, 10, 220))
        im.convert(mode).save(path)
        return path

    def run_job(self, path, **options):
        before = digest(path)
        out = Path(convert({'paths': [str(path)], 'target': 'Adjust → PNG', **options})[0])
        self.assertEqual(digest(path), before)
        return out

    def test_brightness_and_contrast_move_values_in_the_right_direction(self):
        im = Image.new('RGB', (2, 1), (100, 100, 100)); im.putpixel((1, 0), (200, 200, 200))
        lighter = adjust_image(im, brightness=50); darker = adjust_image(im, brightness=-50)
        self.assertEqual(lighter.getpixel((0, 0))[:3], (150, 150, 150)); self.assertEqual(darker.getpixel((0, 0))[:3], (50, 50, 50))
        flat = adjust_image(im, contrast=-100)
        self.assertEqual(flat.getpixel((0, 0))[:3], flat.getpixel((1, 0))[:3])
        more = adjust_image(im, contrast=50)
        self.assertLess(more.getpixel((0, 0))[0], 100); self.assertGreater(more.getpixel((1, 0))[0], 200)

    def test_saturation_zero_is_gray_and_neutral_is_identity(self):
        im = Image.new('RGB', (1, 1), (200, 50, 50))
        gray = adjust_image(im, saturation=-100).getpixel((0, 0))
        self.assertEqual(gray[0], gray[1]); self.assertEqual(gray[1], gray[2])
        self.assertEqual(adjust_image(im).getpixel((0, 0))[:3], (200, 50, 50))
        self.assertGreater(adjust_image(im, saturation=100).getpixel((0, 0))[0] - adjust_image(im, saturation=100).getpixel((0, 0))[1], 150)

    def test_flip_modes_mirror_pixels_and_alpha(self):
        im = Image.new('RGBA', (3, 2), (0, 0, 0, 255)); im.putpixel((0, 0), (255, 0, 0, 255)); im.putpixel((1, 0), (0, 0, 0, 0))
        h = adjust_image(im, flip=1); v = adjust_image(im, flip=2); both = adjust_image(im, flip=3)
        self.assertEqual(h.getpixel((2, 0)), (255, 0, 0, 255)); self.assertEqual(h.getpixel((1, 0))[3], 0)
        self.assertEqual(v.getpixel((0, 1)), (255, 0, 0, 255)); self.assertEqual(both.getpixel((2, 1)), (255, 0, 0, 255))

    def test_alpha_channel_is_not_touched_by_color_adjustments(self):
        im = Image.new('RGBA', (2, 1), (100, 100, 100, 77))
        out = adjust_image(im, brightness=40, contrast=20, saturation=-30)
        self.assertEqual(out.getpixel((0, 0))[3], 77)

    def test_convert_writes_new_png_and_keeps_original(self):
        path = self.sample()
        out = self.run_job(path, adjust_brightness=30, adjust_flip=1)
        self.assertTrue(out.name.endswith('-ajustada.png'), out.name)
        with Image.open(out) as result, Image.open(path) as src:
            self.assertEqual(result.size, src.size)
            self.assertEqual(result.convert('RGB').getpixel((3, 0))[0], min(255, round(200 * 1.3)))

    def test_validation_rejects_empty_or_out_of_range_adjustments(self):
        path = self.sample()
        for options in (dict(), dict(adjust_brightness=101), dict(adjust_contrast=-101), dict(adjust_saturation=500), dict(adjust_flip=4), dict(adjust_flip=-1), dict(adjust_brightness='x')):
            with self.assertRaises(ConversionError, msg=str(options)):
                convert({'paths': [str(path)], 'target': 'Adjust → PNG', **options})
        self.assertEqual([p.name for p in self.root.iterdir()], ['a.png'])
        self.assertEqual(adjust_options_from({'adjust_flip': 2}), (0, 0, 0, 2))

    def test_report_names_the_adjustments(self):
        path = self.sample()
        text = ' '.join(loss_report([str(path)], 'Adjust → PNG', {'adjust_brightness': 20, 'adjust_saturation': -10, 'adjust_flip': 3}))
        self.assertIn('brilho +20', text); self.assertIn('saturação -10', text); self.assertIn('dois eixos', text)
        self.assertEqual(TOOL_SUFFIX['Adjust → PNG'], 'ajustada')


class AdjustUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def tearDown(self):
        if hasattr(self, 'tmp'):
            self.tmp.cleanup()

    def make_panel(self, count=1):
        controller = JobController(capabilities={'images': (True, 'ok'), 'pdf': (True, 'ok')})
        panel = FeaturePanel(controller)
        self.tmp = tempfile.TemporaryDirectory()
        paths = []
        for index in range(count):
            path = Path(self.tmp.name) / f'f{index}.png'; Image.new('RGB', (120, 80), (100, 120, 140)).save(path); paths.append(str(path))
        panel.set_files(paths, 'Adjust → PNG')
        return controller, panel

    def test_wheel_entries(self):
        self.assertIn('__tool_adjust__', [a.target for a in flatten_actions(actions_for_selection([r'C:\x\p.png']))])
        self.assertEqual(RadialAction('Ajustar', '__tool_adjust__').icon, 'adjust')
        import icons, workspace_panel
        self.assertIn('adjust', icons.ICON_SHAPES)
        self.assertIn('Adjust → PNG', tool_registry.flat_targets(workspace_panel.WHEEL_COLUMNS['images'][1][2]))

    def test_controls_preview_and_options(self):
        controller, panel = self.make_panel()
        visible = sorted(k for k, w in panel.form_fields.items() if panel.settings_form.isRowVisible(w) and k not in ('nname', 'nexample', 'nstart', 'ndigits'))
        self.assertEqual(visible, ['abright', 'acontrast', 'aflip', 'areset', 'asat', 'ofmt'])
        self.assertFalse(panel.run_button.isEnabled())
        with patch.object(controller, 'start_job') as start:
            panel.run_button.setEnabled(True); panel.run_selected()
            start.assert_not_called()
        self.assertIn('pelo menos um ajuste', panel.status.text())
        panel.adjust_brightness.setValue(60)
        self.assertTrue(panel.run_button.isEnabled())
        self.assertEqual(panel.stage.currentIndex(), 4)
        image = panel.static_preview.pixmap_item.pixmap().toImage()
        self.assertGreater(image.pixelColor(10, 10).red(), 120)               # mais claro que o original (100)
        panel.adjust_flip.setCurrentIndex(2); panel.adjust_saturation.setValue(-20)
        captured = {}
        with patch.object(controller, 'start_job', side_effect=lambda files, target, options: captured.update(target=target, options=options) or True):
            panel.run_selected()
        o = captured['options']
        self.assertEqual(captured['target'], 'Adjust → PNG')
        self.assertEqual((o['adjust_brightness'], o['adjust_contrast'], o['adjust_saturation'], o['adjust_flip']), (60, 0, -20, 2))
        panel.reset_adjustments()
        self.assertEqual(panel.adjust_brightness.value(), 0); self.assertEqual(panel.adjust_flip.currentIndex(), 0)
        self.assertFalse(panel.run_button.isEnabled())
        panel.allow_close = True; panel.close()

    def test_controller_whitelists_and_applies_to_each_file(self):
        controller = JobController(capabilities={'images': (True, 'ok'), 'pdf': (True, 'ok')})
        controller.notify = lambda *_: None
        with patch('tray_app.validate_selection', side_effect=lambda p: p):
            self.assertFalse(controller.start_job([r'C:\a.png'], 'Adjust → PNG', {'adjust_brightness': 1.5}))
            self.assertFalse(controller.start_job([r'C:\a.png'], 'Adjust → PNG', {'adjust_unknown': 1}))


if __name__ == '__main__':
    unittest.main()
