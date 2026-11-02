"""HEIC/HEIF (0.9.21): leitura e gravação pelo pacote pillow-heif (opcional em tempo de execução): qualidade, transparência, ICC, EXIF, relatório, ausência do pacote e painel."""
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

import engine
from engine import ConversionError, HEIF_INPUTS, IMAGE_INPUTS, OUTPUT_FORMATS, convert, finalize_for_format, format_save_options, heic_save_available, loss_report, output_options_from, open_image
from tray_app import FeaturePanel, JobController

HAS_HEIF = heic_save_available()


class PlainTests(unittest.TestCase):
    def test_registry(self):
        self.assertEqual(OUTPUT_FORMATS['heic'], ('HEIF', 'heic', 'HEIC')); self.assertEqual(tuple(OUTPUT_FORMATS)[8], 'heic')
        for ext in ('.heic', '.heif', '.hif'): self.assertIn(ext, IMAGE_INPUTS); self.assertIn(ext, HEIF_INPUTS)

    def test_save_options(self):
        self.assertEqual(format_save_options('heic', 80), {'quality': 80, 'chroma': 420})
        self.assertEqual(format_save_options('heic', 95), {'quality': 95, 'chroma': 444}); self.assertEqual(format_save_options('heic', 100), {'quality': -1, 'chroma': 444})

    def test_finalize_modes(self):
        self.assertEqual(finalize_for_format(Image.new('L', (2, 2)), 'heic').mode, 'RGB'); self.assertEqual(finalize_for_format(Image.new('LA', (2, 2)), 'heic').mode, 'RGBA')
        self.assertEqual(finalize_for_format(Image.new('RGBA', (2, 2)), 'heic').mode, 'RGBA')

    def test_missing_package_gives_clear_errors(self):
        with patch.object(engine, 'heic_save_available', return_value=False):
            with self.assertRaises(ConversionError) as caught: output_options_from({'out_format': 'heic'}, 'Crop → PNG')
            self.assertIn('pillow-heif', str(caught.exception)); self.assertEqual(output_options_from({'out_format': 'heic'}, 'Crop → PNG', strict=False)[0], 'heic')
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'x.heic'; path.write_bytes(b'\x00\x00\x00\x18ftypheic' + b'\x00' * 32)
            with patch.object(engine, 'heif_register', return_value=False):
                with self.assertRaises(ConversionError) as caught: open_image(path)
                self.assertIn('pillow-heif', str(caught.exception))

    def test_report_notes_do_not_need_the_package(self):
        with tempfile.TemporaryDirectory() as folder:
            src = Path(folder) / 'a.png'; Image.new('RGBA', (8, 8), (1, 2, 3, 0)).save(src)
            text = ' '.join(loss_report([str(src)], 'Rotate → PNG', {'rotate_angle': 90, 'out_format': 'heic', 'out_quality': 70}))
            self.assertIn('HEIC (qualidade 70)', text); self.assertIn('HEVC', text); self.assertIn('patentes', text)
            self.assertNotIn('4:4:4', text); self.assertNotIn('usa o modo sem perda', text)
            top = ' '.join(loss_report([str(src)], 'Rotate → PNG', {'rotate_angle': 90, 'out_format': 'heic', 'out_quality': 100}))
            self.assertIn('4:4:4', top); self.assertIn('usa o modo sem perda', top)


@unittest.skipUnless(HAS_HEIF, 'pillow-heif não instalado')
class HeicTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        im = Image.new('RGBA', (80, 40), (255, 0, 0, 0)); im.paste((10, 120, 220, 255), (0, 0, 40, 40))
        self.source = self.root / 'a.png'; im.save(self.source)

    def tearDown(self):
        self.temp.cleanup()

    def run_tool(self, source=None, target='Resize → PNG', **extra):
        options = {'resize_mode': 'percent', 'resize_percent': 100} if target == 'Resize → PNG' else {}
        return Path(convert({'paths': [str(source or self.source)], 'target': target, 'out_format': 'heic', **options, **extra})[0])

    def make_heic(self, name='in.heic', size=(64, 32), mode='RGB', **save):
        path = self.root / name; image = Image.new(mode, size)
        for x in range(size[0]): image.paste((x * 255 // size[0], 100, 200 - x * 2) + ((255,) if mode == 'RGBA' else ()), (x, 0, x + 1, size[1]))
        import pillow_heif; pillow_heif.register_heif_opener(); image.save(path, 'HEIF', **save); return path

    def test_option(self):
        self.assertEqual(output_options_from({'out_format': 'heic', 'out_quality': 60}, 'Crop → PNG')[:2], ('heic', 60))
        self.assertEqual(output_options_from({'out_format': 'heic'}, 'Compress → JPEG')[0], 'png')

    def test_file_alpha_and_look(self):
        before = self.source.read_bytes(); out = self.run_tool(out_quality=90)
        self.assertEqual(out.suffix, '.heic'); self.assertEqual(self.source.read_bytes(), before)
        with Image.open(out) as im:
            self.assertEqual((im.format, im.size), ('HEIF', (80, 40))); rgba = im.convert('RGBA')
            self.assertEqual(rgba.getpixel((70, 20))[3], 0)
            r, g, b, a = rgba.getpixel((20, 20)); self.assertEqual(a, 255); self.assertLess(abs(r - 10) + abs(g - 120) + abs(b - 220), 30)

    def test_quality_and_lossless_mode(self):
        noise = self.root / 'n.png'; Image.effect_noise((160, 160), 60).convert('RGB').save(noise)
        high = self.run_tool(noise, out_quality=90).stat().st_size; low = self.run_tool(noise, out_quality=15).stat().st_size
        self.assertLess(low, high)
        out = self.run_tool(noise, out_quality=100)
        from PIL import ImageChops
        with Image.open(out) as im, Image.open(noise) as ref:
            worst = max(high_ for _low, high_ in ImageChops.difference(im.convert('RGB'), ref.convert('RGB')).getextrema()); self.assertLessEqual(worst, 2)   # quase sem perda

    def test_every_tool_and_collage(self):
        second = self.root / 'b.png'; Image.new('RGB', (30, 30), 'green').save(second)
        for target, extra in (('Rotate → PNG', {'rotate_angle': 90}), ('Clean → PNG', {}), ('Backdrop → PNG', {}), ('Sharpen → PNG', {'sharpen_mode': 'sharpen'}),
                              ('Crop → PNG', {'crop_x': 0, 'crop_y': 0, 'crop_width': 20, 'crop_height': 10})):
            with self.subTest(target=target), Image.open(self.run_tool(target=target, **extra)) as im: self.assertEqual(im.format, 'HEIF')
        out = Path(convert({'paths': [str(self.source), str(second)], 'target': 'Collage → PNG', 'out_format': 'heic'})[0])
        with Image.open(out) as im: self.assertEqual(im.format, 'HEIF')

    def test_odd_and_mode_sources(self):
        for size in ((1, 1), (3, 7), (300, 1)):
            tiny = self.root / f't{size[0]}x{size[1]}.png'; Image.new('RGBA', size, (5, 6, 7, 200)).save(tiny)
            with self.subTest(size=size), Image.open(self.run_tool(tiny, target='Clean → PNG')) as im: self.assertEqual(im.size, size)
        for mode in ('L', 'LA', 'P', 'RGB'):
            src = self.root / f'm{mode}.png'; Image.new(mode, (20, 10)).save(src)
            with self.subTest(mode=mode): self.assertTrue(self.run_tool(src, target='Clean → PNG').exists())

    def test_icc_survives_exif_does_not(self):
        from PIL import ImageCms
        profile = ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()
        tagged = self.root / 'icc.jpg'; exif = Image.Exif(); exif[0x010F] = 'Marca'; exif[0x8825] = {1: 'N', 2: (1.0, 2.0, 3.0)}
        Image.new('RGB', (16, 16), 'blue').save(tagged, icc_profile=profile, exif=exif)
        with Image.open(self.run_tool(tagged, target='Clean → PNG')) as im:
            self.assertTrue(im.info.get('icc_profile')); self.assertEqual(len(im.getexif()), 0)

    def test_heic_as_input_every_extension(self):
        source = self.make_heic(quality=95)
        for name in ('in.heic', 'in.heif', 'in.hif'):
            copy = self.root / name
            if copy != source: copy.write_bytes(source.read_bytes())
            out = Path(convert({'paths': [str(copy)], 'target': 'PNG'})[0])
            with Image.open(out) as im: self.assertEqual((im.format, im.size), ('PNG', (64, 32)))
            out.unlink()

    def test_heic_input_goes_through_tools_and_formats(self):
        source = self.make_heic()
        out = Path(convert({'paths': [str(source)], 'target': 'Rotate → PNG', 'rotate_angle': 90, 'out_format': 'webp'})[0])
        with Image.open(out) as im: self.assertEqual(im.size, (32, 64))
        out = Path(convert({'paths': [str(source)], 'target': 'JPEG'})[0]); self.assertEqual(out.suffix, '.jpg')
        out = Path(convert({'paths': [str(source)], 'target': 'Image → PDF'})[0]); self.assertTrue(out.read_bytes().startswith(b'%PDF'))
        out = Path(convert({'paths': [str(source)], 'target': 'Resize → PNG', 'resize_mode': 'percent', 'resize_percent': 100, 'out_format': 'heic'})[0])
        with Image.open(out) as im: self.assertEqual(im.format, 'HEIF')

    def test_heic_rgba_input_keeps_alpha(self):
        source = self.make_heic('alpha.heic', mode='RGBA', quality=95)
        out = Path(convert({'paths': [str(source)], 'target': 'PNG'})[0])
        with Image.open(out) as im: self.assertEqual(im.mode, 'RGBA')

    def test_heic_orientation_is_applied_and_metadata_is_not_copied(self):
        path = self.root / 'rot.heic'; exif = Image.Exif(); exif[0x0112] = 6; exif[0x010F] = 'Marca'
        import pillow_heif; pillow_heif.register_heif_opener()
        Image.new('RGB', (40, 20), 'red').save(path, 'HEIF', exif=exif.tobytes())
        with open_image(path) as image: self.assertEqual(image.size[0] * image.size[1], 800)
        out = Path(convert({'paths': [str(path)], 'target': 'Clean → PNG'})[0])
        with Image.open(out) as im: self.assertEqual(len(im.getexif()), 0)

    def test_oversized_heic_is_refused_before_decoding(self):
        source = self.make_heic()
        with patch.object(engine, 'MAX_PIXELS', 100):
            with self.assertRaises(ConversionError): open_image(source)

    def test_corrupt_file_is_a_clear_error(self):
        bad = self.root / 'bad.heic'; bad.write_bytes(b'\x00\x00\x00\x18ftypheic' + b'\x01' * 200)
        before = sorted(p.name for p in self.root.iterdir())
        with self.assertRaises(Exception) as caught: convert({'paths': [str(bad)], 'target': 'PNG'})
        self.assertTrue(str(caught.exception))
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), before)

    def test_report_for_heic_source(self):
        source = self.make_heic()
        text = ' '.join(loss_report([str(source)], 'Rotate → PNG', {'rotate_angle': 90, 'out_format': 'jpeg'}))
        self.assertIn('A origem já tinha perda', text)

    def test_worker_process(self):
        import runner
        source = self.make_heic()
        result = runner.run_job({'paths': [str(source)], 'target': 'Resize → PNG', 'resize_mode': 'percent', 'resize_percent': 200, 'out_format': 'heic'}, timeout=90)
        with Image.open(result[0]) as im: self.assertEqual((im.format, im.size), ('HEIF', (128, 64)))


class HeicPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def tearDown(self):
        if hasattr(self, 'tmp'): self.tmp.cleanup()

    def make_panel(self):
        controller = JobController(capabilities={'images': (True, 'ok'), 'pdf': (True, 'ok')}); panel = FeaturePanel(controller)
        self.tmp = tempfile.TemporaryDirectory(); path = Path(self.tmp.name) / 'f.png'; Image.new('RGB', (200, 100), (100, 120, 140)).save(path)
        panel.set_files([str(path)], 'Resize → PNG'); return controller, panel

    def visible(self, panel):
        return {k for k, w in panel.form_fields.items() if panel.settings_form.isRowVisible(w)}

    def test_chip_quality_button_and_extension(self):
        _c, panel = self.make_panel()
        self.assertEqual(panel.out_format.count(), len(OUTPUT_FORMATS)); panel.out_format.setCurrentIndex(8)
        self.assertEqual(self.visible(panel) & {'ofmt', 'oqual', 'oflat'}, {'ofmt', 'oqual'})
        self.assertEqual(panel.run_button.text(), 'Redimensionar e salvar HEIC'); self.assertEqual(panel._rename_extension('Resize → PNG'), 'heic')

    def test_options_are_sent(self):
        controller, panel = self.make_panel()
        with patch.object(controller, 'start_job') as start:
            panel.out_format.setCurrentIndex(8); panel.out_quality.setValue(60); panel.run_selected()
            options = start.call_args.args[2]; self.assertEqual((options['out_format'], options['out_quality']), ('heic', 60))

    def test_heic_files_are_images_in_the_panel(self):
        from workspace_panel import IMAGE_SUFFIXES
        for ext in ('.heic', '.heif', '.hif'): self.assertIn(ext, IMAGE_SUFFIXES)


if __name__ == '__main__':
    unittest.main()
