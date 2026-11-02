"""Ferramenta Níveis (Levels → PNG): opções, curva medida, auto-níveis, alfa, histograma, job, painel e relatório."""
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
from engine import ConversionError, TOOL_SUFFIX, convert, levels_auto_points, levels_image, levels_options_from, levels_resolve, loss_report, luminance_histogram
from radial_menu import actions_for_selection, flatten_actions
from tray_app import FeaturePanel, JobController
from widgets import HistogramView


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def opts(black=0, white=255, gamma=100, auto=0):
    return levels_options_from({'levels_black': black, 'levels_white': white, 'levels_gamma': gamma, 'levels_auto': auto}, strict=False)


def gray_ramp(low=0, high=255, size=(256, 20)):
    """Rampa horizontal de cinza entre low e high."""
    im = Image.new('RGB', size)
    for x in range(size[0]):
        v = round(low + (high - low) * x / (size[0] - 1)); ImageDraw.Draw(im).line((x, 0, x, size[1]), fill=(v, v, v))
    return im


def lum(im, x, y=5):
    return im.convert('L').getpixel((x, y))


class LevelsOptionTests(unittest.TestCase):
    def test_defaults(self):
        self.assertEqual(levels_options_from({}, strict=False), {'auto': 0, 'black': 0, 'white': 255, 'gamma': 100})

    def test_validation(self):
        for bad in ({'levels_black': 255}, {'levels_black': -1}, {'levels_white': 0}, {'levels_white': 256}, {'levels_gamma': 9}, {'levels_gamma': 501},
                    {'levels_auto': 2}, {'levels_black': 'x'}, {'levels_black': 100, 'levels_white': 100}, {'levels_black': 200, 'levels_white': 100}):
            with self.assertRaises(ConversionError): levels_options_from(bad, strict=False)

    def test_identity_needs_a_change_unless_auto(self):
        with self.assertRaises(ConversionError): levels_options_from({})
        self.assertTrue(levels_options_from({'levels_auto': 1})['auto']); self.assertEqual(levels_options_from({'levels_gamma': 120})['gamma'], 120)
        self.assertEqual(levels_options_from({'levels_black': 5})['black'], 5)

    def test_auto_ignores_inverted_manual_points(self):
        self.assertEqual(levels_options_from({'levels_auto': 1, 'levels_black': 200, 'levels_white': 100})['auto'], 1)


class LevelsRenderTests(unittest.TestCase):
    def test_identity_is_exact(self):
        src = gray_ramp(); self.assertEqual(ImageChops.difference(levels_image(src, opts()).convert('RGB'), src).getbbox(), None)

    def test_black_and_white_points_clip_and_stretch(self):
        out = levels_image(gray_ramp(), opts(black=50, white=200))
        self.assertEqual((lum(out, 10), lum(out, 50), lum(out, 200), lum(out, 250)), (0, 0, 255, 255))
        self.assertAlmostEqual(lum(out, 125), 128, delta=2)                                  # meio do intervalo → cinza médio

    def test_gamma_moves_midtones_but_not_extremes(self):
        bright = levels_image(gray_ramp(), opts(gamma=200)); dark = levels_image(gray_ramp(), opts(gamma=50))
        self.assertEqual((lum(bright, 0), lum(bright, 255)), (0, 255)); self.assertEqual((lum(dark, 0), lum(dark, 255)), (0, 255))
        self.assertGreater(lum(bright, 128), 128 + 30); self.assertLess(lum(dark, 128), 128 - 30)
        self.assertAlmostEqual(lum(bright, 128), round(255 * (128 / 255) ** 0.5), delta=2)   # gama 2,0: v^(1/2)

    def test_monotonic_and_same_curve_on_all_channels(self):
        out = levels_image(Image.merge('RGB', [gray_ramp().getchannel(0)] * 3), opts(black=20, white=230, gamma=150))
        values = [lum(out, x) for x in range(256)]; self.assertEqual(values, sorted(values))
        color = Image.new('RGB', (4, 4), (200, 100, 50)); got = levels_image(color, opts(black=30, white=220)).getpixel((0, 0))[:3]
        self.assertEqual(got, tuple(round(255 * ((c - 30) / 190)) for c in (200, 100, 50)))   # mesma curva: a cor não desvia

    def test_alpha_is_untouched(self):
        src = Image.new('RGBA', (40, 40), (120, 120, 120, 255)); ImageDraw.Draw(src).ellipse((5, 5, 35, 35), fill=(200, 50, 50, 90))
        out = levels_image(src, opts(black=40, white=180, gamma=140)); self.assertEqual(ImageChops.difference(out.getchannel('A'), src.getchannel('A')).getbbox(), None)

    def test_source_not_mutated_and_size_kept(self):
        src = gray_ramp(); copy = src.copy(); out = levels_image(src, opts(black=10, white=240)); self.assertEqual((out.size, out.mode), (src.size, 'RGBA'))
        self.assertEqual(ImageChops.difference(src, copy).getbbox(), None)


class LevelsAutoTests(unittest.TestCase):
    def test_histogram_counts_and_ignores_transparent(self):
        im = Image.new('RGBA', (10, 10), (0, 0, 0, 0)); ImageDraw.Draw(im).rectangle((0, 0, 4, 9), fill=(100, 100, 100, 255))
        hist = luminance_histogram(im); self.assertEqual((len(hist), sum(hist), hist[100], hist[0]), (256, 50, 50, 0))

    def test_auto_points_find_the_used_range(self):
        black, white = levels_auto_points(gray_ramp(60, 190)); self.assertLessEqual(abs(black - 61), 3); self.assertLessEqual(abs(white - 189), 3)

    def test_auto_stretches_a_flat_low_contrast_image(self):
        src = gray_ramp(60, 190); out = levels_image(src, opts(auto=1)); lo, hi = out.convert('L').getextrema()
        self.assertLessEqual(lo, 3); self.assertGreaterEqual(hi, 252)
        self.assertGreater(ImageStat.Stat(out.convert('L')).stddev[0], ImageStat.Stat(src.convert('L')).stddev[0] * 1.5)

    def test_auto_is_computed_per_image(self):
        a = levels_resolve(gray_ramp(60, 190), opts(auto=1)); b = levels_resolve(gray_ramp(0, 120), opts(auto=1)); self.assertNotEqual(a[:2], b[:2])

    def test_auto_leaves_full_range_and_flat_images_alone(self):
        self.assertEqual(levels_auto_points(gray_ramp()), (levels_auto_points(gray_ramp())[0], levels_auto_points(gray_ramp())[1]))
        self.assertEqual(levels_auto_points(Image.new('RGB', (30, 30), (90, 90, 90))), (0, 255))
        flat = Image.new('RGB', (30, 30), (90, 90, 90)); self.assertEqual(ImageChops.difference(levels_image(flat, opts(auto=1)).convert('RGB'), flat).getbbox(), None)
        self.assertEqual(levels_auto_points(Image.new('RGBA', (8, 8), (0, 0, 0, 0))), (0, 255))      # tudo transparente

    def test_auto_keeps_gamma(self):
        src = gray_ramp(60, 190); plain = levels_image(src, opts(auto=1)); bright = levels_image(src, opts(auto=1, gamma=200))
        self.assertGreater(lum(bright, 128), lum(plain, 128))


class LevelsEngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.source = self.root / 'a.png'; gray_ramp(60, 190).save(self.source)

    def tearDown(self):
        self.temp.cleanup()

    def run_job(self, **kw):
        before = digest(self.source)
        out = Path(convert({'paths': [str(self.source)], 'target': 'Levels → PNG', **kw})[0])
        self.assertEqual(digest(self.source), before)
        return out

    def test_job_writes_new_file(self):
        out = self.run_job(levels_auto=1)
        self.assertTrue(out.name.endswith('-com-niveis.png')); self.assertEqual(TOOL_SUFFIX['Levels → PNG'], 'com-niveis')
        with Image.open(out) as im: lo, hi = im.convert('L').getextrema(); self.assertLessEqual(lo, 3); self.assertGreaterEqual(hi, 252)

    def test_manual_job_and_formats(self):
        for key in ('png', 'jpeg', 'webp', 'tiff', 'bmp'): self.assertTrue(self.run_job(levels_black=40, levels_white=200, out_format=key).exists())

    def test_invalid_or_identity_options_stop_the_job(self):
        for bad in ({}, {'levels_black': 300}, {'levels_black': 150, 'levels_white': 100}):
            with self.assertRaises(ConversionError): convert({'paths': [str(self.source)], 'target': 'Levels → PNG', **bad})

    def test_batch_auto_uses_each_images_own_points(self):
        other = self.root / 'b.png'; gray_ramp(0, 120).save(other)
        outs = [convert({'paths': [str(path)], 'target': 'Levels → PNG', 'levels_auto': 1})[0] for path in (self.source, other)]
        self.assertEqual(len(set(outs)), 2)
        for out in outs:
            with Image.open(out) as im: lo, hi = im.convert('L').getextrema(); self.assertLessEqual(lo, 3); self.assertGreaterEqual(hi, 252)

    def test_loss_report_notes(self):
        manual = ' '.join(loss_report([str(self.source)], 'Levels → PNG', {'levels_black': 30, 'levels_white': 220, 'levels_gamma': 120}))
        self.assertIn('preto em 30, branco em 220', manual); self.assertIn('gama 1.20', manual); self.assertIn('perdem detalhe', manual)
        auto = ' '.join(loss_report([str(self.source)], 'Levels → PNG', {'levels_auto': 1})); self.assertIn('cada imagem', auto)


class LevelsUITests(unittest.TestCase):
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
            path = Path(self.tmp.name) / f'f{index}.png'; gray_ramp(60, 190, (300, 200)).save(path); paths.append(str(path))
        panel.set_files(paths, 'Levels → PNG')
        return controller, panel

    def visible(self, panel):
        return {k for k, w in panel.form_fields.items() if panel.settings_form.isRowVisible(w)}

    def test_registry_wheel_and_icon(self):
        import icons
        self.assertIn('__tool_levels__', [a.target for a in flatten_actions(actions_for_selection([r'C:\x\p.png']))])
        spec = tool_registry.BY_TARGET['Levels → PNG']; self.assertEqual((spec.group, spec.label), ('look', 'Níveis')); self.assertIn('levels', icons.ICON_SHAPES)
        self.assertLessEqual(len(tool_registry.group_members('look')) + 1, 8)

    def test_controls_follow_mode(self):
        _c, panel = self.make_panel(); keys = {'lmode', 'lhist', 'lblack', 'lwhite', 'lgamma', 'lreset'}
        self.assertEqual(self.visible(panel) & keys, keys)
        panel.lv_mode.setCurrentIndex(1); self.assertEqual(self.visible(panel) & keys, keys - {'lblack', 'lwhite'})

    def test_run_is_gated_until_something_changes(self):
        controller, panel = self.make_panel()
        self.assertFalse(panel.run_button.isEnabled())
        with patch.object(controller, 'start_job') as start:
            panel.run_selected(); start.assert_not_called(); self.assertIn('Mova', panel.status.text())
        panel.lv_gamma.slider.setValue(130); self.assertTrue(panel.run_button.isEnabled())
        panel.lv_gamma.slider.setValue(100); self.assertFalse(panel.run_button.isEnabled())
        panel.lv_mode.setCurrentIndex(1); self.assertTrue(panel.run_button.isEnabled())

    def test_black_and_white_cannot_cross(self):
        _c, panel = self.make_panel(); panel.lv_white.slider.setValue(100); panel.lv_black.slider.setValue(150)
        self.assertGreater(panel.lv_white.value(), panel.lv_black.value())
        panel.lv_white.slider.setValue(10); self.assertLess(panel.lv_black.value(), panel.lv_white.value())

    def test_options_are_sent_and_batch_allowed(self):
        controller, panel = self.make_panel(count=3)
        with patch.object(controller, 'start_job') as start:
            panel.lv_mode.setCurrentIndex(1); panel.lv_gamma.slider.setValue(120); panel.run_selected()
            paths, target, sent = start.call_args.args
            self.assertEqual((len(paths), target, sent['levels_auto'], sent['levels_gamma']), (3, 'Levels → PNG', 1, 120))

    def test_histogram_and_preview_with_one_image(self):
        _c, panel = self.make_panel(); panel.lv_black.slider.setValue(60); self.app.processEvents()
        hist = panel.lv_hist.histogram(); self.assertIsNotNone(hist); self.assertEqual(len(hist), 256); self.assertEqual(sum(hist[:55]), 0)
        self.assertIn('prévia', panel.tool_hint.text().lower())
        panel.lv_mode.setCurrentIndex(1); self.assertIn('Automático: preto em', panel.tool_hint.text())

    def test_reset_on_reopen(self):
        _c, panel = self.make_panel(); panel.lv_mode.setCurrentIndex(1); panel.lv_black.slider.setValue(40); panel.lv_gamma.slider.setValue(180)
        panel.set_files([panel.files[0]], 'Levels → PNG')
        self.assertEqual((panel.lv_mode.currentIndex(), panel.lv_black.value(), panel.lv_white.value(), panel.lv_gamma.value()), (0, 0, 255, 100))

    def test_gamma_label_shows_two_decimals(self):
        _c, panel = self.make_panel(); panel.lv_gamma.slider.setValue(150); self.assertEqual(panel.lv_gamma.label.text(), '1.50')

    def test_histogram_widget_paints_with_and_without_data(self):
        view = HistogramView(); view.resize(300, 90)
        view.grab(); view.set_histogram([0] * 100 + [50] * 56 + [0] * 100); view.set_marks(40, 200, 150); self.assertTrue(view.grab().toImage().width() > 0)
        view.set_histogram(None); view.grab()

    def test_whitelist_accepts_the_options(self):
        controller = JobController(capabilities={'images': (True, 'ok'), 'pdf': (True, 'ok')}); controller.notify = lambda *a, **k: None; controller._start_next = lambda: None
        path = Path(tempfile.mkdtemp()) / 'a.png'; Image.new('RGB', (4, 4)).save(path)
        self.assertTrue(controller.start_job([str(path)], 'Levels → PNG', {'levels_auto': 1, 'levels_black': 5, 'levels_white': 250, 'levels_gamma': 110}))
        self.assertFalse(controller.start_job([str(path)], 'Levels → PNG', {'levels_gamma': '110'}))


if __name__ == '__main__':
    unittest.main()
