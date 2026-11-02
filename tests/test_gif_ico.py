"""Saída em GIF estático e ICO (0.9.18): paleta, transparência de 1 bit, tamanhos do ícone, relatório, painel e arquivos de origem intactos."""
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

import tool_registry
from engine import ConversionError, ICO_SIZES, OUTPUT_FORMATS, convert, finalize_for_format, gif_prepare, ico_sizes, ico_square, loss_report, output_options_from
from tray_app import FeaturePanel, JobController


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def gradient(size=(64, 48)):
    im = Image.new('RGBA', size)
    for x in range(size[0]):
        for y in range(size[1]):
            im.putpixel((x, y), (x * 255 // size[0], y * 255 // size[1], 128, 255))
    return im


class OptionTests(unittest.TestCase):
    def test_formats_are_accepted(self):
        for key in ('gif', 'ico'):
            self.assertEqual(output_options_from({'out_format': key}, 'Crop → PNG')[0], key)
        self.assertEqual(output_options_from({'out_format': 'gif'}, 'Compress → JPEG')[0], 'png')       # não vale fora das ferramentas
        with self.assertRaises(ConversionError): output_options_from({'out_format': 'svg'}, 'Crop → PNG')


class GifPrepareTests(unittest.TestCase):
    def test_opaque_uses_up_to_256_colours_and_no_transparency(self):
        p = gif_prepare(gradient())
        self.assertEqual(p.mode, 'P'); self.assertNotIn('transparency', p.info)
        self.assertLessEqual(len(p.getcolors(maxcolors=256) or []), 256)

    def test_transparency_is_one_bit_with_a_reserved_index(self):
        im = Image.new('RGBA', (4, 1), (255, 0, 0, 255))
        im.putpixel((1, 0), (0, 255, 0, 0)); im.putpixel((2, 0), (0, 0, 255, 127)); im.putpixel((3, 0), (0, 0, 255, 128))
        p = gif_prepare(im)
        self.assertEqual(p.info['transparency'], 255)
        indexes = [p.getpixel((x, 0)) for x in range(4)]
        self.assertEqual(indexes[1], 255); self.assertEqual(indexes[2], 255)        # alfa < 128 → transparente
        self.assertNotEqual(indexes[0], 255); self.assertNotEqual(indexes[3], 255)  # alfa ≥ 128 → opaco

    def test_palette_never_collides_with_the_reserved_index(self):
        im = gradient((40, 40)); im.putpixel((0, 0), (0, 0, 0, 0))
        p = gif_prepare(im)
        self.assertEqual(p.histogram()[255], 1)               # só o pixel transparente usa o 255


class IcoSquareTests(unittest.TestCase):
    def test_sizes_that_fit(self):
        self.assertEqual(ICO_SIZES, (16, 32, 48, 64, 128, 256))
        self.assertEqual(ico_sizes(256), [(n, n) for n in ICO_SIZES]); self.assertEqual(ico_sizes(100), [(16, 16), (32, 32), (48, 48), (64, 64)]); self.assertEqual(ico_sizes(16), [(16, 16)])

    def test_non_square_is_centered_not_cropped_or_stretched(self):
        im = Image.new('RGBA', (40, 20), (255, 0, 0, 255))
        sq = ico_square(im)
        self.assertEqual(sq.size, (40, 40)); self.assertEqual(sq.getpixel((20, 5))[3], 0); self.assertEqual(sq.getpixel((20, 20)), (255, 0, 0, 255)); self.assertEqual(sq.getpixel((20, 34))[3], 0)

    def test_large_is_reduced_and_tiny_is_enlarged(self):
        self.assertEqual(ico_square(Image.new('RGB', (1000, 500), 'blue')).size, (256, 256))
        self.assertEqual(ico_square(Image.new('RGB', (4, 4), 'blue')).size, (16, 16))
        self.assertEqual(ico_square(Image.new('RGB', (8, 2), 'blue')).size, (16, 16))

    def test_finalize_routes(self):
        self.assertEqual(finalize_for_format(Image.new('RGB', (20, 10)), 'ico').size, (20, 20))
        self.assertEqual(finalize_for_format(Image.new('RGBA', (5, 5)), 'gif').mode, 'P')


class ConvertTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.source = self.root / 'a.png'
        im = gradient((300, 150))
        for x in range(150, 300):
            for y in range(150): im.putpixel((x, y), (0, 0, 0, 0))
        im.save(self.source)

    def tearDown(self):
        self.temp.cleanup()

    def run_tool(self, target='Resize → PNG', fmt='gif', **extra):
        options = {'resize_mode': 'percent', 'resize_percent': 100} if target == 'Resize → PNG' else {}
        return Path(convert({'paths': [str(self.source)], 'target': target, 'out_format': fmt, **options, **extra})[0])

    def test_gif_file(self):
        before = digest(self.source); out = self.run_tool(fmt='gif')
        self.assertEqual(out.suffix, '.gif'); self.assertEqual(digest(self.source), before)
        with Image.open(out) as im:
            self.assertEqual((im.format, im.size, getattr(im, 'n_frames', 1)), ('GIF', (300, 150), 1))
            rgba = im.convert('RGBA')
            self.assertEqual(rgba.getpixel((250, 75))[3], 0)       # lado vazio continua transparente
            self.assertEqual(rgba.getpixel((10, 10))[3], 255)

    def test_gif_without_transparency(self):
        photo = self.root / 'p.png'; gradient((50, 50)).convert('RGB').save(photo)
        out = Path(convert({'paths': [str(photo)], 'target': 'Clean → PNG', 'out_format': 'gif'})[0])
        with Image.open(out) as im: self.assertNotIn('transparency', im.info); self.assertEqual(im.convert('RGBA').getpixel((3, 3))[3], 255)

    def test_gif_keeps_the_look_within_a_palette_error(self):
        out = self.run_tool(fmt='gif')
        with Image.open(out) as im, Image.open(self.source) as ref:
            a = im.convert('RGB').getpixel((75, 40)); b = ref.convert('RGB').getpixel((75, 40))
            self.assertLess(sum(abs(i - j) for i, j in zip(a, b)), 90)

    def test_ico_file_has_every_size_that_fits(self):
        out = self.run_tool(fmt='ico')
        self.assertEqual(out.suffix, '.ico')
        with Image.open(out) as im:
            self.assertEqual(im.format, 'ICO'); self.assertEqual(sorted(im.info['sizes']), [(n, n) for n in ICO_SIZES])      # 300 px de lado → reduzido a 256 → todos os tamanhos
        small = self.root / 's.png'; Image.new('RGBA', (70, 70), (9, 9, 9, 255)).save(small)
        out = Path(convert({'paths': [str(small)], 'target': 'Clean → PNG', 'out_format': 'ico'})[0])
        with Image.open(out) as im: self.assertEqual(sorted(im.info['sizes']), [(16, 16), (32, 32), (48, 48), (64, 64)])

    def test_ico_transparency_and_padding(self):
        out = self.run_tool(fmt='ico')
        with Image.open(out) as im:
            im.size = max(im.info['sizes'])
            big = im.convert('RGBA')
        self.assertEqual(big.getpixel((big.width // 4, 2))[3], 0)                              # faixa de centralização (300×150 → 256×128 no meio)
        self.assertEqual(big.getpixel((big.width // 4, big.height // 2))[3], 255)               # lado esquerdo da imagem é opaco
        self.assertEqual(big.getpixel((big.width * 3 // 4, big.height // 2))[3], 0)             # lado direito era transparente

    def test_other_tools_and_collage(self):
        for target in ('Rotate → PNG', 'Clean → PNG', 'Backdrop → PNG', 'Sharpen → PNG'):
            extra = {'rotate_angle': 90} if target == 'Rotate → PNG' else ({'sharpen_mode': 'sharpen'} if target == 'Sharpen → PNG' else {})
            for fmt, pil in (('gif', 'GIF'), ('ico', 'ICO')):
                with self.subTest(target=target, fmt=fmt):
                    out = Path(convert({'paths': [str(self.source)], 'target': target, 'out_format': fmt, **extra})[0])
                    with Image.open(out) as im: self.assertEqual(im.format, pil)
        second = self.root / 'b.png'; Image.new('RGB', (30, 30), 'green').save(second)
        for fmt, pil in (('gif', 'GIF'), ('ico', 'ICO')):
            out = Path(convert({'paths': [str(self.source), str(second)], 'target': 'Collage → PNG', 'out_format': fmt})[0])
            self.assertTrue(out.name.startswith('collage') and out.suffix == '.' + fmt)
            with Image.open(out) as im: self.assertEqual(im.format, pil)

    def test_never_overwrites(self):
        first = self.run_tool(fmt='gif'); second = self.run_tool(fmt='gif')
        self.assertNotEqual(first, second); self.assertTrue(first.exists() and second.exists())

    def test_small_and_odd_sources(self):
        for size in ((1, 1), (3, 7), (300, 1), (2000, 10)):
            tiny = self.root / f't{size[0]}x{size[1]}.png'; Image.new('RGBA', size, (5, 6, 7, 200)).save(tiny)
            for fmt in ('gif', 'ico'):
                with self.subTest(size=size, fmt=fmt):
                    out = Path(convert({'paths': [str(tiny)], 'target': 'Clean → PNG', 'out_format': fmt})[0])
                    with Image.open(out) as im: self.assertGreater(im.width, 0)

    def test_mode_sources(self):
        for mode in ('L', 'LA', 'P', 'RGB', 'I;16'):
            src = self.root / f'm{mode.replace(";", "")}.png'
            try: Image.new(mode, (20, 10)).save(src)
            except Exception: continue
            for fmt in ('gif', 'ico'):
                with self.subTest(mode=mode, fmt=fmt):
                    out = Path(convert({'paths': [str(src)], 'target': 'Clean → PNG', 'out_format': fmt})[0]); self.assertTrue(out.exists())


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.path = Path(self.temp.name) / 'a.png'; Image.new('RGBA', (40, 20), (1, 2, 3, 0)).save(self.path)

    def tearDown(self):
        self.temp.cleanup()

    def notes(self, fmt, target='Rotate → PNG'):
        return ' '.join(loss_report([str(self.path)], target, {'rotate_angle': 90, 'out_format': fmt}))

    def test_gif_report(self):
        text = self.notes('gif'); self.assertIn('GIF estático', text); self.assertIn('256 cores', text); self.assertIn('1 bit', text)

    def test_ico_report(self):
        text = self.notes('ico'); self.assertIn('ícone', text); self.assertIn('256 px', text); self.assertIn('centralizadas', text)

    def test_clean_report_says_pixels_changed(self):
        for fmt in ('gif', 'ico'): self.assertIn('recompactados com perda', self.notes(fmt, 'Clean → PNG'))


class PanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def tearDown(self):
        if hasattr(self, 'tmp'): self.tmp.cleanup()

    def make_panel(self):
        controller = JobController(capabilities={'images': (True, 'ok'), 'pdf': (True, 'ok')})
        panel = FeaturePanel(controller)
        self.tmp = tempfile.TemporaryDirectory(); path = Path(self.tmp.name) / 'f.png'; Image.new('RGB', (200, 100), (100, 120, 140)).save(path)
        panel.set_files([str(path)], 'Resize → PNG')
        return controller, panel

    def test_chips_and_button(self):
        _c, panel = self.make_panel()
        self.assertEqual(panel.out_format.count(), len(OUTPUT_FORMATS))
        panel.out_format.setCurrentIndex(5); self.assertEqual(panel.run_button.text(), 'Redimensionar e salvar GIF')
        panel.out_format.setCurrentIndex(6); self.assertEqual(panel.run_button.text(), 'Redimensionar e salvar ICO')

    def test_options_are_sent(self):
        controller, panel = self.make_panel()
        with patch.object(controller, 'start_job') as start:
            for index, key in ((5, 'gif'), (6, 'ico')):
                panel.out_format.setCurrentIndex(index); panel.run_selected()
                self.assertEqual(start.call_args.args[2]['out_format'], key)

    def test_rename_example_uses_the_extension(self):
        _c, panel = self.make_panel()
        panel.out_format.setCurrentIndex(6); self.assertEqual(panel._rename_extension('Resize → PNG'), 'ico')
        panel.out_format.setCurrentIndex(5); self.assertEqual(panel._rename_extension('Resize → PNG'), 'gif')

    def test_registry_still_flags_every_png_tool(self):
        self.assertTrue(tool_registry.FORMAT_TARGETS)


if __name__ == '__main__':
    unittest.main()
