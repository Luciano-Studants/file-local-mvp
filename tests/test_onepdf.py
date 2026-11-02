"""Ferramenta Várias imagens → um PDF (Images → One PDF): opções, geometria das páginas, ordem, transparência, EXIF, nomes, fila, painel e relatório."""
import hashlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PIL import Image
from pypdf import PdfReader
from PySide6.QtWidgets import QApplication

import tool_registry
from engine import ConversionError, ONEPDF, PDF_DPI, TOOL_SUFFIX, convert, loss_report, onepdf_options_from, pdf_page_image, pdf_page_pixels
from radial_menu import actions_for_selection
from tray_app import FeaturePanel, JobController
from visual_tools import pdf_pages_pixmap

A4_PX = (round(210 / 25.4 * PDF_DPI), round(297 / 25.4 * PDF_DPI))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def opts(page='image', margin=10, quality=90):
    return onepdf_options_from({'pdf_page': page, 'pdf_margin': margin, 'quality': quality})


def page_points(reader, index):
    box = reader.pages[index].mediabox
    return float(box.width), float(box.height)


class OnePdfOptionTests(unittest.TestCase):
    def test_defaults_and_margin_only_for_fixed_pages(self):
        self.assertEqual(onepdf_options_from({}), {'page': 'image', 'margin': 0, 'quality': 90, 'ocr': 'off'})
        self.assertEqual(opts('a4', 15), {'page': 'a4', 'margin': 15, 'quality': 90, 'ocr': 'off'}); self.assertEqual(opts('image', 30)['margin'], 0)

    def test_rejections(self):
        for bad in ({'pdf_page': 'a3'}, {'pdf_margin': -1}, {'pdf_margin': 51}, {'quality': 0}, {'quality': 101}, {'pdf_margin': 'x'}):
            with self.assertRaises(ConversionError, msg=str(bad)): onepdf_options_from({'pdf_page': 'a4', **bad} if 'pdf_page' not in bad else bad)


class OnePdfGeometryTests(unittest.TestCase):
    def test_image_mode_is_the_image(self):
        self.assertEqual(pdf_page_pixels('image', (300, 200), 0), ((300, 200), (0, 0, 300, 200)))

    def test_a4_orientation_follows_the_image(self):
        self.assertEqual(pdf_page_pixels('a4', (100, 200), 0)[0], A4_PX); self.assertEqual(pdf_page_pixels('a4', (200, 100), 0)[0], A4_PX[::-1])
        self.assertEqual(pdf_page_pixels('a4', (100, 100), 0)[0], A4_PX)                                        # quadrada: retrato
        letter = pdf_page_pixels('letter', (100, 200), 0)[0]; self.assertAlmostEqual(letter[0] / letter[1], 215.9 / 279.4, places=2)

    def test_margin_area(self):
        (pw, ph), (x, y, w, h) = pdf_page_pixels('a4', (100, 200), 10); m = round(10 / 25.4 * PDF_DPI)
        self.assertEqual((x, y, w, h), (m, m, pw - 2 * m, ph - 2 * m))

    def test_page_image_image_mode_and_alpha_on_white(self):
        src = Image.new('RGBA', (60, 40), (0, 0, 0, 0)); page = pdf_page_image(src, opts('image'))
        self.assertEqual((page.size, page.mode, page.getpixel((5, 5))), ((60, 40), 'RGB', (255, 255, 255)))

    def test_page_image_fixed_page_centres_scales_and_keeps_margins(self):
        src = Image.new('RGB', (100, 100), (200, 0, 0)); page = pdf_page_image(src, opts('a4', 10)); (pw, ph), (ax, ay, aw, ah) = pdf_page_pixels('a4', (100, 100), 10)
        self.assertEqual(page.size, (pw, ph)); self.assertEqual(page.getpixel((2, 2)), (255, 255, 255)); self.assertEqual(page.getpixel((pw // 2, ay - 3)), (255, 255, 255))
        self.assertEqual(page.getpixel((pw // 2, ph // 2))[:1], (200,)); self.assertEqual(page.getpixel((ax + 2, ph // 2))[:1], (200,))        # ampliou até a largura útil
        self.assertEqual(page.getpixel((ax - 3, ph // 2)), (255, 255, 255))

    def test_wide_image_in_portrait_never_happens_but_tall_one_is_fitted_by_height(self):
        src = Image.new('RGB', (50, 400), (0, 0, 200)); page = pdf_page_image(src, opts('a4', 0)); (pw, ph), _area = pdf_page_pixels('a4', (50, 400), 0)
        self.assertEqual(page.getpixel((pw // 2, 2))[2], 200); self.assertEqual(page.getpixel((pw // 2, ph - 3))[2], 200); self.assertEqual(page.getpixel((3, ph // 2)), (255, 255, 255))


class OnePdfEngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.paths = []
        for name, size, color in (('a', (300, 200), (200, 30, 30)), ('b', (200, 300), (30, 200, 30)), ('c', (120, 120), (30, 30, 200))):
            path = self.root / f'{name}.png'; Image.new('RGB', size, color).save(path); self.paths.append(path)

    def tearDown(self):
        self.temp.cleanup()

    def run_job(self, paths=None, **kw):
        paths = paths or self.paths; before = [digest(p) for p in paths]
        out = [Path(p) for p in convert({'paths': [str(p) for p in paths], 'target': ONEPDF, **kw})]
        self.assertEqual([digest(p) for p in paths], before)
        return out[0]

    def colors(self, pdf):
        reader = PdfReader(str(pdf)); result = []
        for page in reader.pages:
            image = page.images[0].image.convert('RGB'); result.append(image.getpixel((image.width // 2, image.height // 2)))
        return result

    def test_image_mode_pages_follow_image_sizes_in_order(self):
        out = self.run_job(); reader = PdfReader(str(out)); self.assertEqual((out.name, len(reader.pages)), ('images.pdf', 3))
        for index, (w, h) in enumerate(((300, 200), (200, 300), (120, 120))):
            pw, ph = page_points(reader, index); self.assertAlmostEqual(pw, w * 72 / PDF_DPI, delta=0.6); self.assertAlmostEqual(ph, h * 72 / PDF_DPI, delta=0.6)
        c = self.colors(out); self.assertTrue(c[0][0] > 150 and c[1][1] > 150 and c[2][2] > 150)

    def test_order_follows_the_list(self):
        out = self.run_job(paths=list(reversed(self.paths))); c = self.colors(out); self.assertTrue(c[0][2] > 150 and c[2][0] > 150)

    def test_a4_pages_have_standard_size_and_orientation(self):
        reader = PdfReader(str(self.run_job(pdf_page='a4', pdf_margin=10)))
        sizes = [page_points(reader, i) for i in range(3)]
        self.assertAlmostEqual(sizes[0][0], 297 / 25.4 * 72, delta=1); self.assertAlmostEqual(sizes[0][1], 210 / 25.4 * 72, delta=1)       # imagem paisagem → página paisagem
        self.assertAlmostEqual(sizes[1][0], 210 / 25.4 * 72, delta=1); self.assertAlmostEqual(sizes[1][1], 297 / 25.4 * 72, delta=1)
        self.assertEqual(sizes[2], sizes[1])

    def test_letter_pages(self):
        reader = PdfReader(str(self.run_job(pdf_page='letter', pdf_margin=0))); w, h = page_points(reader, 1); self.assertAlmostEqual(w, 215.9 / 25.4 * 72, delta=1); self.assertAlmostEqual(h, 279.4 / 25.4 * 72, delta=1)

    def test_transparent_png_becomes_white(self):
        a = self.root / 't.png'; Image.new('RGBA', (80, 60), (0, 0, 0, 0)).save(a)
        out = self.run_job(paths=[a, self.paths[0]]); image = PdfReader(str(out)).pages[0].images[0].image.convert('RGB'); self.assertEqual(image.getpixel((10, 10)), (255, 255, 255))

    def test_exif_orientation_is_applied(self):
        rotated = self.root / 'r.jpg'; im = Image.new('RGB', (120, 100), (255, 255, 255)); exif = Image.Exif(); exif[274] = 6; im.save(rotated, exif=exif)
        out = self.run_job(paths=[rotated, self.paths[0]]); w, h = page_points(PdfReader(str(out)), 0); self.assertLess(w, h)

    def test_quality_changes_the_size(self):
        import random
        noisy = []
        for i in range(2):
            path = self.root / f'n{i}.png'; rnd = random.Random(i); im = Image.new('RGB', (200, 200)); im.putdata([(rnd.randrange(256), rnd.randrange(256), rnd.randrange(256)) for _ in range(40000)]); im.save(path); noisy.append(path)
        low = self.run_job(paths=noisy, quality=10).stat().st_size; high = self.run_job(paths=noisy, quality=95).stat().st_size; self.assertLess(low, high)

    def test_names_never_overwrite_and_pattern_applies(self):
        first = self.run_job(); second = self.run_job(); self.assertEqual((first.name, second.name), ('images.pdf', 'images-2.pdf'))
        self.assertEqual(self.run_job(rename_pattern='album-{n}', rename_n=3).name, 'album-3.pdf'); self.assertEqual(self.run_job(rename_pattern='{nome}').name, 'imagens.pdf')

    def test_invalid_input(self):
        with self.assertRaises(ConversionError): convert({'paths': [str(self.paths[0])], 'target': ONEPDF})
        text = self.root / 'x.txt'; text.write_text('x')
        with self.assertRaises(ConversionError): convert({'paths': [str(self.paths[0]), str(text)], 'target': ONEPDF})
        with self.assertRaises(ConversionError): convert({'paths': [str(p) for p in self.paths], 'target': ONEPDF, 'pdf_page': 'a3'})
        self.assertEqual([p.name for p in self.root.iterdir() if p.suffix == '.pdf'], [])

    def test_loss_report(self):
        text = ' '.join(loss_report([str(p) for p in self.paths], ONEPDF, {'pdf_page': 'a4', 'pdf_margin': 12, 'quality': 80}))
        for expected in ('3 página(s)', 'A4', '12 mm', 'JPEG', 'sem OCR', 'EXIF'): self.assertIn(expected, text)
        self.assertIn('tamanho da própria imagem', ' '.join(loss_report([str(p) for p in self.paths], ONEPDF, {})))

    def test_registry(self):
        spec = tool_registry.BY_TARGET[ONEPDF]; self.assertEqual((spec.label, spec.ext, spec.suffix, spec.in_selection_wheel, spec.group), ('PDF único', 'pdf', None, False, ''))
        self.assertNotIn(ONEPDF, tool_registry.FORMAT_TARGETS); self.assertNotIn(ONEPDF, TOOL_SUFFIX)


class OnePdfQueueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.paths = []
        for name in 'abc':
            path = Path(self.temp.name) / f'{name}.png'; Image.new('RGB', (20, 20)).save(path); self.paths.append(str(path))
        self.controller = JobController(capabilities={'images': (True, 'ok'), 'pdf': (True, 'ok')}); self.controller.notify = lambda *a, **k: None; self.controller._start_next = lambda: None

    def tearDown(self):
        self.temp.cleanup()

    def test_single_job_for_all_files_and_minimum_two(self):
        self.assertTrue(self.controller.start_job(self.paths, ONEPDF, {'pdf_page': 'a4', 'pdf_margin': 5, 'quality': 80, 'rename_pattern': 'x{n}', 'rename_start': 4}))
        self.assertEqual(len(self.controller.pending_jobs), 1); job = self.controller.pending_jobs[0]; self.assertEqual((job['paths'], job['options']['rename_n']), (self.paths, 4))
        self.assertFalse(self.controller.start_job(self.paths[:1], ONEPDF, {}))

    def test_whitelist(self):
        for bad in ({'pdf_page': 'x' * 201}, {'pdf_page': 3}, {'pdf_margin': '5'}, {'pdf_margin': True}):
            self.assertFalse(self.controller.start_job(self.paths, ONEPDF, bad), msg=str(bad))


class OnePdfUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def tearDown(self):
        if hasattr(self, 'panel'):
            self.panel.allow_close = True; self.panel.close()
        if hasattr(self, 'tmp'):
            self.tmp.cleanup()

    def make_panel(self, count=3):
        self.controller = JobController(capabilities={'images': (True, 'ok'), 'pdf': (True, 'ok')}); self.panel = FeaturePanel(self.controller)
        self.tmp = tempfile.TemporaryDirectory(); paths = []
        for index in range(count):
            path = Path(self.tmp.name) / f'f{index}.png'; Image.new('RGB', (300 if index % 2 == 0 else 200, 200 if index % 2 == 0 else 300), (200, 30 * index, 30)).save(path); paths.append(str(path))
        self.panel.set_files(paths, ONEPDF)
        return self.controller, self.panel

    def visible(self, panel):
        return {k for k, w in panel.form_fields.items() if panel.settings_form.isRowVisible(w)}

    def test_controls_follow_the_page_choice(self):
        _c, panel = self.make_panel(); base = {'clist', 'cbuttons', 'ppage', 'quality', 'nname', 'nexample'}
        self.assertEqual(self.visible(panel) & (base | {'pmargin', 'ofmt'}), base)
        panel.pdf_page.setCurrentIndex(1); self.assertEqual(self.visible(panel) & (base | {'pmargin', 'ofmt'}), base | {'pmargin'})
        panel.pdf_page.setCurrentIndex(2); self.assertIn('pmargin', self.visible(panel)); self.assertEqual(panel.run_button.text(), 'Criar PDF')

    def test_preview_and_message(self):
        _c, panel = self.make_panel(); self.assertEqual(panel.stage.currentIndex(), 4); self.assertIn('3 páginas', panel.tool_hint.text()); self.assertTrue(panel.run_button.isEnabled())
        panel.pdf_page.setCurrentIndex(1); self.assertIn('A4', panel.tool_hint.text())
        _c, panel = self.make_panel(count=1); self.assertEqual(panel.stage.currentIndex(), 0); self.assertFalse(panel.run_button.isEnabled())

    def test_order_buttons_reorder_the_pages(self):
        _c, panel = self.make_panel(); names = [Path(p).name for p in panel.files]
        panel.collage_list.setCurrentRow(0); panel.move_collage_item(1); self.assertEqual([Path(p).name for p in panel.files], [names[1], names[0], names[2]])
        panel.collage_list.setCurrentRow(2); panel.remove_collage_item(); self.assertEqual(len(panel.files), 2)
        self.assertIn('2 páginas', panel.tool_hint.text())
        panel.collage_list.setCurrentRow(0); panel.remove_collage_item(); self.assertFalse(panel.run_button.isEnabled())

    def test_options_are_sent(self):
        controller, panel = self.make_panel()
        with patch.object(controller, 'start_job') as start:
            panel.pdf_page.setCurrentIndex(1); panel.pdf_margin.slider.setValue(15); panel.quality.setValue(77); panel.run_selected()
            paths, target, sent = start.call_args.args
            self.assertEqual((len(paths), target, sent['pdf_page'], sent['pdf_margin'], sent['quality']), (3, ONEPDF, 'a4', 15, 77))

    def test_run_refused_with_one_image(self):
        controller, panel = self.make_panel(count=1)
        with patch.object(controller, 'start_job') as start: panel.run_selected(); start.assert_not_called(); self.assertIn('2 a 200', panel.status.text())

    def test_rename_example_uses_the_group_name(self):
        _c, panel = self.make_panel(); panel.rename_pattern.setText('{nome}-{n}'); self.assertEqual(panel.rename_example.text(), 'imagens-1.pdf')

    def test_global_radial_offers_the_tool_for_several_images(self):
        targets = [a.target for a in actions_for_selection([r'C:\x\1.png', r'C:\x\2.png'])]; self.assertIn('__tool_onepdf__', targets); self.assertIn('__tool_collage__', targets)
        self.assertNotIn('__tool_onepdf__', [a.target for a in actions_for_selection([r'C:\x\1.png'])])

    def test_pages_pixmap_renders_all_modes(self):
        from PySide6.QtGui import QPixmap
        small = QPixmap(30, 20); small.fill()
        for page in ('image', 'a4', 'letter'):
            for thumbs in (None, [(small, (300, 200)), (small, (200, 300)), None]):
                pixmap = pdf_pages_pixmap(['a', 'b', 'c'], page, 10, thumbs); self.assertFalse(pixmap.isNull()); self.assertLessEqual(max(pixmap.width(), pixmap.height()), 905)
        self.assertFalse(pdf_pages_pixmap([], 'a4', 10).isNull())


if __name__ == '__main__':
    unittest.main()
