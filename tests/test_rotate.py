"""Ferramenta Girar (Rotate → PNG): sem perda, validação, painel, roda e relatório."""
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

from engine import ConversionError, TOOL_SUFFIX, convert, loss_report, rotate_image, rotate_options_from
from radial_menu import actions_for_selection, flatten_actions
import tool_registry
from tray_app import FeaturePanel, JobController


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def marked(mode='RGB'):
    """4 × 2 com cantos distintos, para detectar qualquer troca de lugar."""
    im = Image.new('RGB', (4, 2), (50, 50, 50))
    im.putpixel((0, 0), (255, 0, 0)); im.putpixel((3, 0), (0, 255, 0)); im.putpixel((0, 1), (0, 0, 255)); im.putpixel((3, 1), (255, 255, 0))
    return im.convert(mode)


class RotateImageTests(unittest.TestCase):
    def test_clockwise_quarter_turn_moves_corners(self):
        out = rotate_image(marked(), 90)
        self.assertEqual(out.size, (2, 4))
        self.assertEqual(out.getpixel((1, 0)), (255, 0, 0))     # canto superior esquerdo vai para o superior direito
        self.assertEqual(out.getpixel((1, 3)), (0, 255, 0))     # superior direito → inferior direito
        self.assertEqual(out.getpixel((0, 0)), (0, 0, 255))     # inferior esquerdo → superior esquerdo

    def test_other_angles_and_four_turns_are_identity(self):
        base = marked()
        self.assertEqual(rotate_image(base, 180).getpixel((3, 1)), (255, 0, 0))
        self.assertEqual(rotate_image(base, 270).size, (2, 4)); self.assertEqual(rotate_image(base, 270).getpixel((0, 3)), (255, 0, 0))
        out = base
        for _ in range(4): out = rotate_image(out, 90)
        self.assertEqual(list(out.getdata()), list(base.getdata()))
        self.assertEqual(list(rotate_image(rotate_image(base, 90), 270).getdata()), list(base.getdata()))

    def test_flips_are_applied_after_the_turn(self):
        base = marked()
        self.assertEqual(rotate_image(base, 0, 1).getpixel((3, 0)), (255, 0, 0))
        self.assertEqual(rotate_image(base, 0, 2).getpixel((0, 0)), (0, 0, 255))
        self.assertEqual(list(rotate_image(base, 0, 3).getdata()), list(rotate_image(base, 180).getdata()))
        # girar 90° e espelhar na horizontal: o canto vermelho (que ficou em cima à direita) vai para cima à esquerda
        self.assertEqual(rotate_image(base, 90, 1).getpixel((0, 0)), (255, 0, 0))

    def test_alpha_and_modes_survive_unchanged(self):
        rgba = Image.new('RGBA', (3, 2), (10, 20, 30, 0)); rgba.putpixel((0, 0), (1, 2, 3, 255))
        out = rotate_image(rgba, 90); self.assertEqual(out.mode, 'RGBA'); self.assertEqual(out.getpixel((1, 0)), (1, 2, 3, 255)); self.assertEqual(out.getpixel((0, 0))[3], 0)
        for mode in ('L', 'P', 'I;16'):
            self.assertEqual(rotate_image(Image.new(mode, (6, 2)), 90).size, (2, 6), mode)

    def test_options_validation(self):
        self.assertEqual(rotate_options_from({'rotate_angle': 90, 'rotate_flip': 3}), (90, 3))
        for bad in ({}, {'rotate_angle': 45}, {'rotate_angle': 360}, {'rotate_flip': 4}, {'rotate_angle': 'x'}, {'rotate_angle': -90}):
            with self.assertRaises(ConversionError, msg=str(bad)):
                rotate_options_from(bad)
        self.assertEqual(rotate_options_from({}, strict=False), (0, 0))


class RotateEngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def run_job(self, path, **options):
        before = digest(path)
        out = Path(convert({'paths': [str(path)], 'target': 'Rotate → PNG', **options})[0])
        self.assertEqual(digest(path), before); self.assertNotEqual(out, path)
        return out

    def test_png_is_pixel_exact_and_named(self):
        path = self.root / 'a.png'; marked().save(path)
        out = self.run_job(path, rotate_angle=90)
        self.assertIn('girada', out.name); self.assertEqual(TOOL_SUFFIX['Rotate → PNG'], 'girada')
        with Image.open(out) as im:
            self.assertEqual(im.format, 'PNG'); self.assertEqual(im.size, (2, 4))
            self.assertEqual(list(im.convert('RGB').getdata()), list(rotate_image(marked(), 90).getdata()))

    def test_exif_orientation_is_applied_first_then_turn(self):
        path = self.root / 'e.jpg'; exif = Image.Exif(); exif[0x0112] = 6
        Image.new('RGB', (40, 20), 'red').save(path, exif=exif)                 # com o EXIF: 20 × 40
        with Image.open(self.run_job(path, rotate_angle=90)) as im: self.assertEqual(im.size, (40, 20))

    def test_invalid_job_leaves_no_output(self):
        path = self.root / 'a.png'; marked().save(path)
        for options in ({}, {'rotate_angle': 45}, {'rotate_flip': 9}):
            with self.assertRaises(ConversionError):
                convert({'paths': [str(path)], 'target': 'Rotate → PNG', **options})
        self.assertEqual([p.name for p in self.root.iterdir()], ['a.png'])

    def test_never_overwrites(self):
        path = self.root / 'a.png'; marked().save(path)
        first = self.run_job(path, rotate_angle=180); second = self.run_job(path, rotate_angle=180)
        self.assertNotEqual(first, second); self.assertTrue(first.exists() and second.exists())

    def test_loss_report(self):
        path = self.root / 'a.png'; Image.new('RGB', (40, 20)).save(path)
        notes = ' '.join(loss_report([str(path)], 'Rotate → PNG', {'rotate_angle': 90, 'rotate_flip': 1}))
        self.assertIn('girada 90° para a direita', notes); self.assertIn('espelhada na horizontal', notes); self.assertIn('sem perda', notes); self.assertIn('20 × 40', notes)


class RotateUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def tearDown(self):
        if hasattr(self, 'tmp'):
            self.tmp.cleanup()

    def make_panel(self, count=1):
        controller = JobController(capabilities={'images': (True, 'ok'), 'pdf': (True, 'ok')})
        panel = FeaturePanel(controller)
        self.tmp = tempfile.TemporaryDirectory(); paths = []
        for index in range(count):
            path = Path(self.tmp.name) / f'f{index}.png'; Image.new('RGB', (120, 80), (100, 120, 140)).save(path); paths.append(str(path))
        panel.set_files(paths, 'Rotate → PNG')
        return controller, panel

    def test_wheel_icon_and_registry(self):
        import icons, workspace_panel
        self.assertIn('__tool_rotate__', [a.target for a in flatten_actions(actions_for_selection([r'C:\x\p.png']))])
        self.assertIn('rotate', icons.ICON_SHAPES); self.assertIn('Rotate → PNG', tool_registry.flat_targets(workspace_panel.WHEEL_COLUMNS['images'][1][2]))

    def test_controls_preview_and_run_gate(self):
        controller, panel = self.make_panel()
        visible = sorted(k for k, w in panel.form_fields.items() if panel.settings_form.isRowVisible(w) and k not in ('nname', 'nexample', 'nstart', 'ndigits'))
        self.assertEqual(visible, ['gangle', 'gflip', 'ginfo', 'ofmt'])
        self.assertFalse(panel.run_button.isEnabled())
        with patch.object(controller, 'start_job') as start:
            panel.run_selected(); start.assert_not_called(); self.assertIn('Escolha', panel.status.text())
            panel.rotate_angle.setCurrentIndex(1)
            self.assertTrue(panel.run_button.isEnabled()); self.assertIn('120 × 80 px → 80 × 120 px', panel.rotate_info.text())
            panel.rotate_flip.setCurrentIndex(1); panel.run_selected()
            _paths, target, options = start.call_args.args
            self.assertEqual(target, 'Rotate → PNG'); self.assertEqual((options['rotate_angle'], options['rotate_flip']), (90, 1))

    def test_angles_map_to_clockwise_degrees(self):
        controller, panel = self.make_panel()
        with patch.object(controller, 'start_job') as start:
            for index, degrees in ((1, 90), (2, 180), (3, 270)):
                panel.rotate_angle.setCurrentIndex(index); panel.run_selected()
                self.assertEqual(start.call_args.args[2]['rotate_angle'], degrees)

    def test_state_resets_when_reopened(self):
        _controller, panel = self.make_panel()
        panel.rotate_angle.setCurrentIndex(2); panel.rotate_flip.setCurrentIndex(3)
        panel.set_files([panel.files[0]], 'Rotate → PNG')
        self.assertEqual((panel.rotate_angle.currentIndex(), panel.rotate_flip.currentIndex()), (0, 0))

    def test_multiple_files_use_one_rule(self):
        _controller, panel = self.make_panel(count=3)
        panel.rotate_angle.setCurrentIndex(1)
        self.assertIn('3 arquivos', panel.rotate_info.text()); self.assertTrue(panel.run_button.isEnabled())


if __name__ == '__main__':
    unittest.main()
