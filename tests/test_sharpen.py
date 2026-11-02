"""Ferramenta Nitidez e desfoque (Sharpen → PNG): opções, efeito medido, alfa, raio proporcional, job, painel e relatório."""
import hashlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PIL import Image, ImageChops, ImageDraw, ImageStat
from PySide6.QtWidgets import QApplication

import tool_registry
from engine import ConversionError, TOOL_SUFFIX, convert, loss_report, sharpen_image, sharpen_options_from, sharpen_radius_px
from radial_menu import actions_for_selection, flatten_actions
from tray_app import FeaturePanel, JobController


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def opts(mode='sharpen', amount=50, radius=5):
    return sharpen_options_from({'sharpen_mode': mode, 'sharpen_amount': amount, 'sharpen_radius': radius})


def edge_image(size=(200, 100), soft=True):
    """Metade escura, metade clara, com a transição levemente borrada (típica de foto sem nitidez)."""
    im = Image.new('RGB', size, (60, 60, 60)); ImageDraw.Draw(im).rectangle((size[0] // 2, 0, size[0], size[1]), fill=(190, 190, 190))
    if soft:
        from PIL import ImageFilter
        im = im.filter(ImageFilter.GaussianBlur(2))
    return im


def row_range(im, y=50):
    values = [im.convert('L').getpixel((x, y)) for x in range(im.width)]
    return min(values), max(values)


def step_width(im, y=50):
    """Quantos pixels leva a transição entre 20 % e 80 % do degrau."""
    values = [im.convert('L').getpixel((x, y)) for x in range(im.width)]
    low, high = min(values), max(values); a, b = low + (high - low) * .2, low + (high - low) * .8
    return sum(1 for v in values if a < v < b)


class SharpenOptionTests(unittest.TestCase):
    def test_defaults(self):
        self.assertEqual(sharpen_options_from({}), {'mode': 'sharpen', 'amount': 50, 'radius': 2})

    def test_validation(self):
        for bad in ({'sharpen_mode': 'x'}, {'sharpen_amount': 0}, {'sharpen_amount': 101}, {'sharpen_radius': 0}, {'sharpen_radius': 101}, {'sharpen_radius': 'a'}, {'sharpen_amount': 'x'}):
            with self.assertRaises(ConversionError): sharpen_options_from(bad)

    def test_radius_is_proportional_to_the_short_side(self):
        self.assertAlmostEqual(sharpen_radius_px((3000, 2000), 10), 20); self.assertAlmostEqual(sharpen_radius_px((300, 200), 10), 2)
        self.assertEqual(sharpen_radius_px((10, 10), 1), 0.3)                                    # piso para imagens minúsculas


class SharpenRenderTests(unittest.TestCase):
    def test_sharpen_steepens_edges_and_overshoots(self):
        src = edge_image(); out = sharpen_image(src, opts(amount=100, radius=10))
        self.assertLess(step_width(out), step_width(src))
        lo, hi = row_range(out); slo, shi = row_range(src); self.assertLess(lo, slo); self.assertGreater(hi, shi)   # realce e halo

    def test_sharpen_leaves_flat_areas_unchanged(self):
        flat = Image.new('RGB', (80, 80), (120, 40, 200)); out = sharpen_image(flat, opts(amount=100, radius=20))
        self.assertEqual(ImageChops.difference(out.convert('RGB'), flat).getbbox(), None)

    def test_amount_scales_the_effect(self):
        src = edge_image(); diff = lambda a: ImageStat.Stat(ImageChops.difference(sharpen_image(src, opts(amount=a, radius=20)).convert('RGB'), src)).mean[0]
        self.assertLess(diff(10), diff(50)); self.assertLess(diff(50), diff(100))

    def test_blur_softens_edges_and_keeps_mean(self):
        src = edge_image(soft=False); out = sharpen_image(src, opts(mode='blur', radius=20))
        self.assertGreater(step_width(out), step_width(src) + 3); lo, hi = row_range(out); self.assertGreaterEqual(lo, 60); self.assertLessEqual(hi, 190)
        self.assertAlmostEqual(ImageStat.Stat(out.convert('L')).mean[0], ImageStat.Stat(src.convert('L')).mean[0], delta=2)

    def test_blur_amount_is_ignored_and_radius_matters(self):
        src = edge_image(soft=False)
        a = sharpen_image(src, opts(mode='blur', amount=1, radius=10)); b = sharpen_image(src, opts(mode='blur', amount=100, radius=10))
        self.assertEqual(ImageChops.difference(a, b).getbbox(), None)
        self.assertGreater(step_width(sharpen_image(src, opts(mode='blur', radius=40))), step_width(a))

    def test_sharpen_keeps_alpha_exactly(self):
        src = Image.new('RGBA', (60, 60), (200, 10, 10, 255)); ImageDraw.Draw(src).ellipse((10, 10, 50, 50), fill=(10, 10, 200, 90))
        out = sharpen_image(src, opts(amount=100, radius=10)); self.assertEqual(ImageChops.difference(out.getchannel('A'), src.getchannel('A')).getbbox(), None)

    def test_blur_has_no_dark_halo_on_transparent_edges(self):
        src = Image.new('RGBA', (80, 80), (0, 0, 0, 0)); ImageDraw.Draw(src).rectangle((20, 20, 60, 60), fill=(255, 0, 0, 255))   # fundo transparente com RGB preto
        out = sharpen_image(src, opts(mode='blur', radius=30)); seen = 0
        for x in range(10, 70):
            r, g, b, a = out.getpixel((x, 40))
            if a > 40: seen += 1; self.assertGreater(r, 230); self.assertLess(g, 20)           # cor continua vermelha onde há alfa
        self.assertGreater(seen, 20); self.assertTrue(any(0 < out.getpixel((x, 40))[3] < 255 for x in range(10, 70)))   # a borda ficou macia

    def test_preview_matches_the_result_at_another_scale(self):
        big = edge_image((800, 400)); small = big.resize((400, 200), Image.Resampling.LANCZOS)
        a = sharpen_image(big, opts(mode='blur', radius=15)).resize((400, 200), Image.Resampling.LANCZOS); b = sharpen_image(small, opts(mode='blur', radius=15))
        self.assertLess(ImageStat.Stat(ImageChops.difference(a.convert('L'), b.convert('L'))).mean[0], 2.0)

    def test_modes_and_sizes_preserved_and_source_not_mutated(self):
        src = edge_image((90, 60)); copy = src.copy()
        for mode in ('sharpen', 'blur'):
            out = sharpen_image(src, opts(mode=mode)); self.assertEqual((out.size, out.mode), ((90, 60), 'RGBA'))
        self.assertEqual(ImageChops.difference(src, copy).getbbox(), None)


class SharpenEngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.source = self.root / 'a.png'; edge_image().save(self.source)

    def tearDown(self):
        self.temp.cleanup()

    def run_job(self, **kw):
        before = digest(self.source)
        out = Path(convert({'paths': [str(self.source)], 'target': 'Sharpen → PNG', **kw})[0])
        self.assertEqual(digest(self.source), before)
        return out

    def test_job_writes_new_file(self):
        out = self.run_job(sharpen_mode='sharpen', sharpen_amount=80, sharpen_radius=8)
        self.assertTrue(out.name.endswith('-com-efeito.png')); self.assertEqual(TOOL_SUFFIX['Sharpen → PNG'], 'com-efeito')
        with Image.open(out) as im, Image.open(self.source) as src: self.assertEqual(im.size, src.size); self.assertLess(step_width(im), step_width(src))

    def test_job_with_defaults_and_formats(self):
        for key in ('png', 'jpeg', 'webp', 'tiff', 'bmp'):
            out = self.run_job(sharpen_mode='blur', out_format=key); self.assertTrue(out.exists())
        self.assertTrue(self.run_job().exists())

    def test_invalid_options_stop_the_job(self):
        with self.assertRaises(ConversionError): convert({'paths': [str(self.source)], 'target': 'Sharpen → PNG', 'sharpen_radius': 500})

    def test_existing_output_is_never_overwritten(self):
        first = self.run_job(); second = self.run_job(); self.assertNotEqual(first, second)

    def test_loss_report_notes(self):
        blur = ' '.join(self._report('blur'))
        self.assertIn('Desfoque', blur); self.assertIn('não volta', blur)
        sharp = ' '.join(self._report('sharpen')); self.assertIn('Nitidez', sharp); self.assertIn('halos', sharp); self.assertIn('raio ≈ 2.0 px', sharp)

    def _report(self, mode):
        return loss_report([str(self.source)], 'Sharpen → PNG', {'sharpen_mode': mode, 'sharpen_radius': 20, 'sharpen_amount': 50})


class SharpenUITests(unittest.TestCase):
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
            path = Path(self.tmp.name) / f'f{index}.png'; edge_image((300, 200)).save(path); paths.append(str(path))
        panel.set_files(paths, 'Sharpen → PNG')
        return controller, panel

    def visible(self, panel):
        return {k for k, w in panel.form_fields.items() if panel.settings_form.isRowVisible(w)}

    def test_registry_wheel_and_icon(self):
        import icons
        self.assertIn('__tool_sharpen__', [a.target for a in flatten_actions(actions_for_selection([r'C:\x\p.png']))])
        spec = tool_registry.BY_TARGET['Sharpen → PNG']; self.assertEqual((spec.group, spec.label, spec.risk), ('look', 'Nitidez', 'baixo'))
        self.assertIn('sharpen', icons.ICON_SHAPES); self.assertLessEqual(len(spec.label), 10)

    def test_controls_follow_mode(self):
        _c, panel = self.make_panel(); keys = {'smode', 'samount', 'sradius'}
        self.assertEqual(self.visible(panel) & keys, keys)
        panel.sharp_mode.setCurrentIndex(1); self.assertEqual(self.visible(panel) & keys, {'smode', 'sradius'})
        self.assertIn('ofmt', self.visible(panel))

    def test_options_are_sent(self):
        controller, panel = self.make_panel(count=2)
        with patch.object(controller, 'start_job') as start:
            panel.sharp_mode.setCurrentIndex(1); panel.sharp_radius.setValue(30); panel.sharp_amount.setValue(70)
            panel.run_selected(); paths, target, sent = start.call_args.args
            self.assertEqual((len(paths), target, sent['sharpen_mode'], sent['sharpen_radius'], sent['sharpen_amount']), (2, 'Sharpen → PNG', 'blur', 30, 70))

    def test_default_run_is_allowed(self):
        controller, panel = self.make_panel()
        with patch.object(controller, 'start_job') as start:
            panel.run_selected(); sent = start.call_args.args[2]; self.assertEqual((sent['sharpen_mode'], sent['sharpen_amount'], sent['sharpen_radius']), ('sharpen', 50, 2))

    def test_live_preview_and_reset_on_reopen(self):
        _c, panel = self.make_panel(); panel.sharp_radius.setValue(40); self.app.processEvents()
        self.assertIn('prévia', panel.tool_hint.text().lower())
        panel.sharp_mode.setCurrentIndex(1); panel.sharp_amount.setValue(90)
        panel.set_files([panel.files[0]], 'Sharpen → PNG')
        self.assertEqual((panel.sharp_mode.currentIndex(), panel.sharp_amount.value(), panel.sharp_radius.value()), (0, 50, 2))

    def test_multiple_files_work_without_preview(self):
        _c, panel = self.make_panel(count=3); self.assertTrue(panel.run_button.isEnabled())

    def test_whitelist_accepts_the_options_and_rejects_bad_types(self):
        controller = JobController(capabilities={'images': (True, 'ok'), 'pdf': (True, 'ok')}); controller.notify = lambda *a, **k: None; controller._start_next = lambda: None
        path = Path(tempfile.mkdtemp()) / 'a.png'; Image.new('RGB', (4, 4)).save(path)
        self.assertTrue(controller.start_job([str(path)], 'Sharpen → PNG', {'sharpen_mode': 'blur', 'sharpen_amount': 10, 'sharpen_radius': 5}))
        self.assertFalse(controller.start_job([str(path)], 'Sharpen → PNG', {'sharpen_radius': '5'}))
        self.assertFalse(controller.start_job([str(path)], 'Sharpen → PNG', {'sharpen_mode': 'x' * 201}))


if __name__ == '__main__':
    unittest.main()
