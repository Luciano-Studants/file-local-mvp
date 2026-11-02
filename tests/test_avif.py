"""Saída e entrada em AVIF (0.9.20), com o suporte nativo do Pillow: qualidade, transparência, ICC, relatório, disponibilidade e painel."""
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
from engine import ConversionError, OUTPUT_FORMATS, avif_available, convert, finalize_for_format, format_save_options, loss_report, output_options_from
from tray_app import FeaturePanel, JobController

HAS_AVIF = avif_available()


@unittest.skipUnless(HAS_AVIF, 'Pillow sem suporte a AVIF')
class AvifTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        im = Image.new('RGBA', (80, 40), (255, 0, 0, 0)); im.paste((10, 120, 220, 255), (0, 0, 40, 40))
        self.source = self.root / 'a.png'; im.save(self.source)

    def tearDown(self):
        self.temp.cleanup()

    def run_tool(self, source=None, target='Resize → PNG', **extra):
        options = {'resize_mode': 'percent', 'resize_percent': 100} if target == 'Resize → PNG' else {}
        return Path(convert({'paths': [str(source or self.source)], 'target': target, 'out_format': 'avif', **options, **extra})[0])

    def test_option_and_registry(self):
        self.assertEqual(OUTPUT_FORMATS['avif'], ('AVIF', 'avif', 'AVIF'))
        self.assertEqual(output_options_from({'out_format': 'avif', 'out_quality': 60}, 'Crop → PNG')[:2], ('avif', 60))
        self.assertEqual(output_options_from({'out_format': 'avif'}, 'Compress → JPEG')[0], 'png')

    def test_unavailable_is_a_clear_error_and_report_still_works(self):
        with patch.object(engine, 'avif_available', return_value=False):
            with self.assertRaises(ConversionError) as caught: output_options_from({'out_format': 'avif'}, 'Crop → PNG')
            self.assertIn('AVIF', str(caught.exception))
            with self.assertRaises(ConversionError): self.run_tool()
            self.assertEqual(output_options_from({'out_format': 'avif'}, 'Crop → PNG', strict=False)[0], 'avif')       # o relatório não depende do suporte

    def test_save_options(self):
        self.assertEqual(format_save_options('avif', 80), {'quality': 80, 'subsampling': '4:2:0', 'speed': 6})
        self.assertEqual(format_save_options('avif', 95)['subsampling'], '4:4:4'); self.assertEqual(format_save_options('avif', 100)['subsampling'], '4:4:4')

    def test_finalize_keeps_alpha_and_normalizes_modes(self):
        self.assertEqual(finalize_for_format(Image.new('RGBA', (2, 2)), 'avif').mode, 'RGBA'); self.assertEqual(finalize_for_format(Image.new('RGB', (2, 2)), 'avif').mode, 'RGB')
        self.assertEqual(finalize_for_format(Image.new('L', (2, 2)), 'avif').mode, 'RGB'); self.assertEqual(finalize_for_format(Image.new('LA', (2, 2)), 'avif').mode, 'RGBA')

    def test_file_alpha_and_look(self):
        before = self.source.read_bytes(); out = self.run_tool(out_quality=90)
        self.assertEqual(out.suffix, '.avif'); self.assertEqual(self.source.read_bytes(), before)
        with Image.open(out) as im:
            self.assertEqual((im.format, im.size), ('AVIF', (80, 40))); rgba = im.convert('RGBA')
            self.assertEqual(rgba.getpixel((70, 20))[3], 0)                                     # lado vazio continua transparente
            r, g, b, a = rgba.getpixel((20, 20)); self.assertEqual(a, 255); self.assertLess(abs(r - 10) + abs(g - 120) + abs(b - 220), 30)

    def test_lower_quality_is_smaller(self):
        noise = self.root / 'n.png'; Image.effect_noise((200, 200), 60).convert('RGB').save(noise)
        high = self.run_tool(noise, out_quality=90).stat().st_size; low = self.run_tool(noise, out_quality=15).stat().st_size
        self.assertLess(low, high)

    def test_every_tool_and_collage(self):
        second = self.root / 'b.png'; Image.new('RGB', (30, 30), 'green').save(second)
        for target, extra in (('Rotate → PNG', {'rotate_angle': 90}), ('Clean → PNG', {}), ('Backdrop → PNG', {}), ('Sharpen → PNG', {'sharpen_mode': 'sharpen'}),
                              ('Crop → PNG', {'crop_x': 0, 'crop_y': 0, 'crop_width': 20, 'crop_height': 10})):
            with self.subTest(target=target):
                with Image.open(self.run_tool(target=target, **extra)) as im: self.assertEqual(im.format, 'AVIF')
        out = Path(convert({'paths': [str(self.source), str(second)], 'target': 'Collage → PNG', 'out_format': 'avif'})[0])
        with Image.open(out) as im: self.assertEqual(im.format, 'AVIF')

    def test_small_odd_and_mode_sources(self):
        for size in ((1, 1), (3, 7), (300, 1)):
            tiny = self.root / f't{size[0]}x{size[1]}.png'; Image.new('RGBA', size, (5, 6, 7, 200)).save(tiny)
            with self.subTest(size=size), Image.open(self.run_tool(tiny, target='Clean → PNG')) as im: self.assertEqual(im.size, size)
        for mode in ('L', 'LA', 'P', 'RGB'):
            src = self.root / f'm{mode}.png'; Image.new(mode, (20, 10)).save(src)
            with self.subTest(mode=mode): self.assertTrue(self.run_tool(src, target='Clean → PNG').exists())

    def test_icc_survives_but_exif_does_not(self):
        from PIL import ImageCms
        profile = ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()
        tagged = self.root / 'icc.jpg'; exif = Image.Exif(); exif[0x010F] = 'Marca'; exif[0x8825] = {1: 'N', 2: (1.0, 2.0, 3.0)}
        Image.new('RGB', (16, 16), 'blue').save(tagged, icc_profile=profile, exif=exif)
        with Image.open(self.run_tool(tagged, target='Clean → PNG')) as im:
            self.assertTrue(im.info.get('icc_profile')); self.assertEqual(len(im.getexif()), 0)

    def test_avif_as_input(self):
        source = self.root / 'in.avif'; gradient = Image.new('RGB', (64, 32))
        for x in range(64): gradient.paste((x * 4, 100, 200 - x * 3), (x, 0, x + 1, 32))
        gradient.save(source, 'AVIF', quality=95)
        out = Path(convert({'paths': [str(source)], 'target': 'PNG'})[0])
        with Image.open(out) as im: self.assertEqual((im.format, im.size), ('PNG', (64, 32)))
        out = Path(convert({'paths': [str(source)], 'target': 'Rotate → PNG', 'rotate_angle': 90, 'out_format': 'webp'})[0])
        with Image.open(out) as im: self.assertEqual(im.size, (32, 64))

    def test_report(self):
        notes = ' '.join(loss_report([str(self.source)], 'Rotate → PNG', {'rotate_angle': 90, 'out_format': 'avif', 'out_quality': 70}))
        self.assertIn('AVIF (qualidade 70)', notes); self.assertIn('sempre com perda', notes); self.assertIn('transparência é mantida', notes); self.assertNotIn('4:4:4', notes)
        self.assertIn('4:4:4', ' '.join(loss_report([str(self.source)], 'Rotate → PNG', {'rotate_angle': 90, 'out_format': 'avif', 'out_quality': 98})))
        jpg = self.root / 'j.jpg'; Image.new('RGB', (8, 8)).save(jpg)
        self.assertIn('A origem já tinha perda', ' '.join(loss_report([str(jpg)], 'Rotate → PNG', {'rotate_angle': 90, 'out_format': 'avif'})))
        self.assertIn('recompactados com perda', ' '.join(loss_report([str(self.source)], 'Clean → PNG', {'out_format': 'avif'})))


class AvifPanelTests(unittest.TestCase):
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

    def test_chip_quality_and_button(self):
        _c, panel = self.make_panel()
        self.assertEqual(panel.out_format.count(), len(OUTPUT_FORMATS)); self.assertEqual(tuple(OUTPUT_FORMATS)[7], 'avif')
        panel.out_format.setCurrentIndex(7)
        self.assertEqual(self.visible(panel) & {'ofmt', 'oqual', 'oflat'}, {'ofmt', 'oqual'})                 # qualidade sim, fundo opaco não (AVIF tem alfa)
        self.assertEqual(panel.run_button.text(), 'Redimensionar e salvar AVIF'); self.assertEqual(panel._rename_extension('Resize → PNG'), 'avif')

    def test_options_are_sent(self):
        controller, panel = self.make_panel()
        with patch.object(controller, 'start_job') as start:
            panel.out_format.setCurrentIndex(7); panel.out_quality.setValue(55); panel.run_selected()
            options = start.call_args.args[2]; self.assertEqual((options['out_format'], options['out_quality']), ('avif', 55))


if __name__ == '__main__':
    unittest.main()
