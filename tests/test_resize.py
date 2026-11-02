"""Ferramenta Redimensionar (Resize → PNG): cálculo de tamanho, motor, validação, painel, roda e relatório."""
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

from engine import ConversionError, MAX_PIXELS, TOOL_SUFFIX, convert, loss_report, resize_image, resize_target_size
from radial_menu import actions_for_selection, flatten_actions
import tool_registry
from tray_app import FeaturePanel, JobController


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class ResizeSizeTests(unittest.TestCase):
    def test_percent(self):
        self.assertEqual(resize_target_size((400, 300), 'percent', 50), (200, 150))
        self.assertEqual(resize_target_size((400, 300), 'percent', 200), (800, 600))
        self.assertEqual(resize_target_size((3, 3), 'percent', 1), (1, 1))               # nunca zero

    def test_fit_keeps_ratio_and_allows_one_free_axis(self):
        self.assertEqual(resize_target_size((400, 200), 'fit', 0, 100, 100), (100, 50))
        self.assertEqual(resize_target_size((400, 200), 'fit', 0, 0, 50), (100, 50))
        self.assertEqual(resize_target_size((400, 200), 'fit', 0, 200, 0), (200, 100))
        self.assertEqual(resize_target_size((100, 100), 'fit', 0, 300, 300), (300, 300))   # pode ampliar, e o relatório avisa

    def test_exact(self):
        self.assertEqual(resize_target_size((400, 200), 'exact', 0, 123, 77), (123, 77))

    def test_invalid_inputs(self):
        for args in (('percent', 0), ('percent', 1001), ('fit', 0, 0, 0), ('fit', 0, -5, 10), ('exact', 0, 100, 0), ('exact', 0, 0, 100), ('weird', 10)):
            with self.assertRaises(ConversionError, msg=str(args)):
                resize_target_size((400, 200), *args)

    def test_limits(self):
        with self.assertRaises(ConversionError):
            resize_target_size((4000, 3000), 'percent', 300)                       # 12000 > 10000 px
        with self.assertRaises(ConversionError):
            resize_target_size((100, 100), 'exact', 0, 9000, 9000)                 # 81 MP > 40 MP
        self.assertEqual(resize_target_size((100, 100), 'exact', 0, 6000, 6000), (6000, 6000))


class ResizeEngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def sample(self, name='a.png', size=(40, 20), mode='RGB', color=(10, 120, 220)):
        path = self.root / name
        Image.new(mode, size, color if mode in ('RGB',) else color + (255,)).save(path)
        return path

    def run_job(self, path, **options):
        before = digest(path)
        out = Path(convert({'paths': [str(path)], 'target': 'Resize → PNG', **options})[0])
        self.assertEqual(digest(path), before)                                       # o original nunca muda
        self.assertNotEqual(out, path)
        return out

    def test_percent_and_name(self):
        out = self.run_job(self.sample(), resize_mode='percent', resize_percent=50)
        self.assertIn('redimensionada', out.name); self.assertEqual(TOOL_SUFFIX['Resize → PNG'], 'redimensionada')
        with Image.open(out) as im:
            self.assertEqual(im.size, (20, 10)); self.assertEqual(im.format, 'PNG')

    def test_fit_and_exact(self):
        with Image.open(self.run_job(self.sample(), resize_mode='fit', resize_width=10)) as im: self.assertEqual(im.size, (10, 5))
        with Image.open(self.run_job(self.sample('b.png'), resize_mode='exact', resize_width=7, resize_height=9)) as im: self.assertEqual(im.size, (7, 9))

    def test_enlarge(self):
        with Image.open(self.run_job(self.sample(), resize_mode='percent', resize_percent=300)) as im: self.assertEqual(im.size, (120, 60))

    def test_alpha_is_preserved_without_halo(self):
        path = self.root / 'alpha.png'
        im = Image.new('RGBA', (20, 20), (255, 0, 0, 0)); im.paste((255, 0, 0, 255), (0, 0, 10, 20)); im.save(path)
        with Image.open(self.run_job(path, resize_mode='percent', resize_percent=50)) as out:
            self.assertEqual(out.mode, 'RGBA')
            px = out.getpixel((0, 5)); self.assertEqual(px[3], 255)
            edge = out.getpixel((9, 5)); self.assertEqual(edge[:3], (255, 0, 0) if edge[3] else edge[:3])   # cor da borda não "escurece" com o alfa 0
            self.assertEqual(out.getpixel((9, 5))[0] >= 250 or out.getpixel((9, 5))[3] == 0, True)

    def test_exif_orientation_is_applied_before_sizing(self):
        path = self.root / 'rot.jpg'
        im = Image.new('RGB', (40, 20), 'red'); exif = Image.Exif(); exif[0x0112] = 6; im.save(path, exif=exif)   # gira 90°: 20 × 40
        with Image.open(self.run_job(path, resize_mode='percent', resize_percent=50)) as out: self.assertEqual(out.size, (10, 20))

    def test_gray_16bit_and_palette_inputs(self):
        gray = self.root / 'g.png'; Image.new('L', (30, 10), 128).save(gray)
        pal = self.root / 'p.png'; Image.new('P', (30, 10)).save(pal)
        for path in (gray, pal):
            with Image.open(self.run_job(path, resize_mode='percent', resize_percent=50)) as out: self.assertEqual(out.size, (15, 5))
        sixteen = self.root / 's.png'; Image.new('I;16', (30, 10), 40000).save(sixteen)
        with Image.open(self.run_job(sixteen, resize_mode='percent', resize_percent=50)) as out: self.assertEqual(out.size, (15, 5))

    def test_invalid_job_is_rejected_and_leaves_no_output(self):
        path = self.sample()
        for options in ({'resize_mode': 'percent', 'resize_percent': 5000}, {'resize_mode': 'fit'}, {'resize_mode': 'exact', 'resize_width': 5}):
            with self.assertRaises(ConversionError):
                convert({'paths': [str(path)], 'target': 'Resize → PNG', **options})
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ['a.png'])

    def test_never_overwrites_existing_result(self):
        path = self.sample()
        first = self.run_job(path, resize_mode='percent', resize_percent=50); second = self.run_job(path, resize_mode='percent', resize_percent=50)
        self.assertNotEqual(first, second); self.assertTrue(first.exists() and second.exists())

    def test_loss_report_mentions_sizes_and_warnings(self):
        path = self.sample()
        notes = ' '.join(loss_report([str(path)], 'Resize → PNG', {'resize_mode': 'percent', 'resize_percent': 200}))
        self.assertIn('40 × 20 px → 80 × 40 px', notes); self.assertIn('ampliada', notes); self.assertIn('borrada', notes)
        notes = ' '.join(loss_report([str(path)], 'Resize → PNG', {'resize_mode': 'exact', 'resize_width': 40, 'resize_height': 40}))
        self.assertIn('proporção', notes)
        notes = ' '.join(loss_report([str(path)], 'Resize → PNG', {'resize_mode': 'percent', 'resize_percent': 25}))
        self.assertIn('reduzida', notes)

    def test_resize_image_same_size_is_a_copy(self):
        im = Image.new('RGB', (5, 5), 'blue'); out = resize_image(im, (5, 5)); self.assertIsNot(out, im); self.assertEqual(out.size, (5, 5))


class ResizeUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def tearDown(self):
        if hasattr(self, 'tmp'):
            self.tmp.cleanup()

    def make_panel(self, count=1, size=(200, 100)):
        controller = JobController(capabilities={'images': (True, 'ok'), 'pdf': (True, 'ok')})
        panel = FeaturePanel(controller)
        self.tmp = tempfile.TemporaryDirectory()
        paths = []
        for index in range(count):
            path = Path(self.tmp.name) / f'f{index}.png'; Image.new('RGB', size, (100, 120, 140)).save(path); paths.append(str(path))
        panel.set_files(paths, 'Resize → PNG')
        return controller, panel

    def visible(self, panel):
        return sorted(k for k, w in panel.form_fields.items() if panel.settings_form.isRowVisible(w) and k not in ('nname', 'nexample', 'nstart', 'ndigits'))

    def test_wheel_registry_and_icon(self):
        import icons, workspace_panel
        targets = [a.target for a in flatten_actions(actions_for_selection([r'C:\x\p.png']))]
        self.assertIn('__tool_resize__', targets)
        self.assertIn('resize', icons.ICON_SHAPES); self.assertIn('Resize → PNG', tool_registry.flat_targets(workspace_panel.WHEEL_COLUMNS['images'][1][2]))
        self.assertNotIn('__tool_resize__', [a.target for a in actions_for_selection([r'C:\x\a.png', r'C:\x\b.png'])])

    def test_controls_follow_the_mode(self):
        _controller, panel = self.make_panel()
        self.assertEqual(self.visible(panel), ['ofmt', 'zinfo', 'zmode', 'zpercent'])
        panel.resize_mode.setCurrentIndex(1)
        self.assertEqual(self.visible(panel), ['ofmt', 'zheight', 'zinfo', 'zmode', 'zwidth'])
        panel.resize_mode.setCurrentIndex(2)
        self.assertEqual(self.visible(panel), ['ofmt', 'zheight', 'zinfo', 'zmode', 'zwidth'])

    def test_info_shows_result_and_warnings(self):
        _controller, panel = self.make_panel()
        panel.resize_percent.setValue(50); self.assertIn('200 × 100 px → 100 × 50 px', panel.resize_info.text())
        panel.resize_percent.setValue(200); self.assertIn('ampliação', panel.resize_info.text())
        panel.resize_mode.setCurrentIndex(2); panel.resize_width.setValue(100); panel.resize_height.setValue(100)
        self.assertIn('proporção muda', panel.resize_info.text())
        panel.resize_mode.setCurrentIndex(1); panel.resize_width.setValue(0); panel.resize_height.setValue(0)
        self.assertIn('Informe', panel.resize_info.text())

    def test_multiple_files_note(self):
        _controller, panel = self.make_panel(count=3)
        self.assertIn('3 arquivos', panel.resize_info.text())

    def test_run_sends_options_and_blocks_invalid(self):
        controller, panel = self.make_panel()
        with patch.object(controller, 'start_job') as start:
            panel.resize_mode.setCurrentIndex(1); panel.resize_width.setValue(0); panel.resize_height.setValue(0)
            panel.run_selected(); start.assert_not_called(); self.assertIn('Informe', panel.status.text())
            panel.resize_width.setValue(80); panel.run_selected()
            _paths, target, options = start.call_args.args
            self.assertEqual(target, 'Resize → PNG')
            self.assertEqual((options['resize_mode'], options['resize_width'], options['resize_height']), ('fit', 80, 0))

    def test_whitelist_accepts_resize_options_and_rejects_others(self):
        controller = JobController(capabilities={'images': (True, 'ok'), 'pdf': (True, 'ok')})
        controller.notify = lambda *a, **k: None
        controller._start_next = lambda: None                       # só valida e enfileira; não inicia thread de trabalho
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'a.png'; Image.new('RGB', (10, 10)).save(path)
            self.assertTrue(controller.start_job([str(path)], 'Resize → PNG', {'resize_mode': 'percent', 'resize_percent': 50, 'resize_width': 0, 'resize_height': 0}))
            controller.pending_jobs.clear()
            self.assertFalse(controller.start_job([str(path)], 'Resize → PNG', {'resize_percent': '50'}))
            self.assertFalse(controller.start_job([str(path)], 'Resize → PNG', {'resize_evil': 1}))


if __name__ == '__main__':
    unittest.main()
