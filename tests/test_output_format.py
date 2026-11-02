"""Formato de saída das ferramentas (PNG, JPEG, WebP, TIFF, BMP, GIF, ICO, AVIF, HEIC): matriz ferramenta × formato, transparência, qualidade, relatório e painel."""
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
from engine import ConversionError, OUTPUT_FORMATS, convert, finalize_for_format, heic_save_available, loss_report, output_options_from
from tray_app import FeaturePanel, JobController

MINIMAL = {
    'Crop → PNG': {'crop_x': 0, 'crop_y': 0, 'crop_width': 20, 'crop_height': 10},
    'Resize → PNG': {'resize_mode': 'percent', 'resize_percent': 50},
    'Rotate → PNG': {'rotate_angle': 90},
    'Canvas → PNG': {'canvas_width': 60, 'canvas_height': 60},
    'Adjust → PNG': {'adjust_brightness': 20},
    'Annotate → PNG': {'annotation': 'Oi', 'annotation_x': 1, 'annotation_y': 1},
    'Redact → PNG': {'redact_regions': [[0, 0, 5, 5]]},
    'Sharpen → PNG': {'sharpen_mode': 'sharpen'},
    'Levels → PNG': {'levels_auto': 1},
    'Shapes → PNG': {'shape_items': [{'kind': 'rect', 'x': 1, 'y': 1, 'w': 4, 'h': 4, 'color': '#FF0000', 'thickness': 1}]},
    'Watermark → PNG': {'watermark_text': 'Marca', 'watermark_scale': 40},
    'Backdrop → PNG': {},
    'Remove Background → PNG': {'bg_feather': 1},
    'Clean → PNG': {},
    'Collage → PNG': {},
}
PIL_NAME = {'png': 'PNG', 'jpeg': 'JPEG', 'webp': 'WEBP', 'tiff': 'TIFF', 'bmp': 'BMP', 'gif': 'GIF', 'ico': 'ICO', 'avif': 'AVIF', 'heic': 'HEIF'}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class OutputOptionTests(unittest.TestCase):
    def test_defaults_and_validation(self):
        self.assertEqual(output_options_from({}, 'Crop → PNG'), ('png', 90, '#FFFFFF'))
        self.assertEqual(output_options_from({'out_format': 'webp', 'out_quality': 100, 'out_flatten': '#00ff00'}, 'Crop → PNG'), ('webp', 100, '#00ff00'))
        self.assertEqual(output_options_from({'out_format': 'ico'}, 'Compress → JPEG'), ('png', 90, '#FFFFFF'))      # não vale fora das ferramentas
        for bad in ({'out_format': 'svg'}, {'out_format': 'PNG '}, {'out_quality': 0}, {'out_quality': 101}, {'out_quality': 'x'}, {'out_flatten': 'red'}, {'out_flatten': '#12345'}):
            with self.assertRaises(ConversionError, msg=str(bad)):
                output_options_from(bad, 'Crop → PNG')
        self.assertEqual(output_options_from({'out_quality': None}, 'Crop → PNG')[1], 90)

    def test_finalize_modes(self):
        rgba = Image.new('RGBA', (2, 1), (255, 0, 0, 0)); rgba.putpixel((1, 0), (0, 0, 255, 255))
        flat = finalize_for_format(rgba.copy(), 'jpeg', '#00FF00')
        self.assertEqual((flat.mode, flat.getpixel((0, 0)), flat.getpixel((1, 0))), ('RGB', (0, 255, 0), (0, 0, 255)))     # transparente vira a cor escolhida
        self.assertEqual(finalize_for_format(rgba.copy(), 'bmp', '#112233').getpixel((0, 0)), (17, 34, 51))
        self.assertEqual(finalize_for_format(rgba.copy(), 'webp').mode, 'RGBA'); self.assertEqual(finalize_for_format(rgba.copy(), 'png').mode, 'RGBA')
        self.assertEqual(finalize_for_format(Image.new('L', (2, 2)), 'webp').mode, 'RGB')
        self.assertEqual(finalize_for_format(Image.new('LA', (2, 2)), 'webp').mode, 'RGBA')
        self.assertEqual(finalize_for_format(Image.new('P', (2, 2)), 'tiff').mode, 'RGBA')


class OutputMatrixTests(unittest.TestCase):
    """Cada ferramenta com cada formato: arquivo certo, extensão certa, original intacto, nada além do resultado na pasta."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        im = Image.new('RGBA', (40, 20), (255, 0, 0, 0)); im.paste((10, 120, 220, 255), (0, 0, 20, 20))
        self.source = self.root / 'a.png'; im.save(self.source)
        self.second = self.root / 'b.png'; Image.new('RGB', (30, 30), 'green').save(self.second)

    def tearDown(self):
        self.temp.cleanup()

    def paths(self, target):
        return [str(self.source), str(self.second)] if target == 'Collage → PNG' else [str(self.source)]

    def test_matrix(self):
        self.assertEqual(set(MINIMAL), set(tool_registry.FORMAT_TARGETS) - {tool_registry.PDF_IMAGES})
        for target in sorted(set(tool_registry.FORMAT_TARGETS) - {tool_registry.PDF_IMAGES}):
            for key, (pil, ext, _label) in OUTPUT_FORMATS.items():
                if key == 'heic' and not heic_save_available(): continue            # pacote pillow-heif opcional
                with self.subTest(target=target, format=key):
                    before = digest(self.source)
                    out = Path(convert({'paths': self.paths(target), 'target': target, 'out_format': key, 'out_quality': 80, **MINIMAL[target]})[0])
                    self.assertEqual(out.suffix, '.' + ext); self.assertEqual(digest(self.source), before)
                    with Image.open(out) as result:
                        self.assertEqual(result.format, pil); self.assertGreater(result.width, 0)
                    out.unlink()

    def test_default_is_still_png_with_the_old_names(self):
        out = Path(convert({'paths': [str(self.source)], 'target': 'Rotate → PNG', 'rotate_angle': 90})[0])
        self.assertTrue(out.name.endswith('-girada.png'))
        out2 = Path(convert({'paths': [str(self.source)], 'target': 'Rotate → PNG', 'rotate_angle': 90, 'out_format': 'jpeg'})[0])
        self.assertTrue(out2.name.endswith('-girada.jpg'))

    def test_transparency_is_carried_or_replaced(self):
        for key in ('png', 'webp', 'tiff'):
            out = Path(convert({'paths': [str(self.source)], 'target': 'Resize → PNG', 'resize_mode': 'percent', 'resize_percent': 100, 'out_format': key, 'out_quality': 100})[0])
            with Image.open(out) as im:
                self.assertIn(im.mode, ('RGBA', 'LA'), key); self.assertEqual(im.convert('RGBA').getpixel((39, 10))[3], 0, key)      # lado vazio continua transparente
        for key in ('jpeg', 'bmp'):
            out = Path(convert({'paths': [str(self.source)], 'target': 'Resize → PNG', 'resize_mode': 'percent', 'resize_percent': 100, 'out_format': key, 'out_flatten': '#00FF00'})[0])
            with Image.open(out) as im:
                self.assertEqual(im.mode, 'RGB'); r, g, b = im.getpixel((39, 10)); self.assertTrue(g > 240 and r < 20 and b < 20, (key, (r, g, b)))

    def test_webp_100_is_lossless_and_lower_quality_is_smaller(self):
        photo = self.root / 'photo.png'
        noise = Image.effect_noise((200, 200), 60).convert('RGB'); noise.save(photo)
        def run(**kw):
            out = Path(convert({'paths': [str(photo)], 'target': 'Resize → PNG', 'resize_mode': 'percent', 'resize_percent': 100, **kw})[0]); size = out.stat().st_size; return out, size
        lossless, big = run(out_format='webp', out_quality=100)
        with Image.open(lossless) as im: self.assertEqual(list(im.convert('RGB').getdata()), list(noise.getdata()))
        _lossy, small = run(out_format='webp', out_quality=30); self.assertLess(small, big)
        _hi, jpeg_hi = run(out_format='jpeg', out_quality=95); _lo, jpeg_lo = run(out_format='jpeg', out_quality=20); self.assertLess(jpeg_lo, jpeg_hi)

    def test_lossless_formats_keep_pixels(self):
        for key in ('png', 'tiff', 'bmp'):
            out = Path(convert({'paths': [str(self.second)], 'target': 'Clean → PNG', 'out_format': key})[0])
            with Image.open(out) as im: self.assertEqual(list(im.convert('RGB').getdata()), list(Image.open(self.second).convert('RGB').getdata()), key)

    def test_invalid_format_creates_nothing(self):
        before = sorted(p.name for p in self.root.iterdir())
        for bad in ({'out_format': 'svg'}, {'out_quality': 500}, {'out_flatten': 'azul'}):
            with self.assertRaises(ConversionError):
                convert({'paths': [str(self.source)], 'target': 'Rotate → PNG', 'rotate_angle': 90, **bad})
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), before)

    def test_exif_gps_is_not_copied_to_jpeg(self):
        photo = self.root / 'gps.jpg'; exif = Image.Exif(); exif[0x010F] = 'Marca'; exif[0x8825] = {1: 'N', 2: (1.0, 2.0, 3.0)}
        Image.new('RGB', (16, 16), 'red').save(photo, exif=exif)
        out = Path(convert({'paths': [str(photo)], 'target': 'Clean → PNG', 'out_format': 'jpeg'})[0])
        with Image.open(out) as im:
            self.assertEqual(len(im.getexif()), 0); self.assertNotIn('exif', im.info)

    def test_icc_profile_survives_in_jpeg_and_webp_but_not_bmp(self):
        from PIL import ImageCms
        profile = ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()
        tagged = self.root / 'icc.png'; Image.new('RGB', (8, 8), 'blue').save(tagged, icc_profile=profile)
        for key, expected in (('jpeg', True), ('webp', True), ('tiff', True), ('bmp', False)):
            out = Path(convert({'paths': [str(tagged)], 'target': 'Clean → PNG', 'out_format': key})[0])
            with Image.open(out) as im: self.assertEqual(bool(im.info.get('icc_profile')), expected, key)


class OutputReportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.path = self.root / 'a.png'; Image.new('RGBA', (40, 20), (1, 2, 3, 0)).save(self.path)

    def tearDown(self):
        self.temp.cleanup()

    def notes(self, target, **options):
        return ' '.join(loss_report([str(self.path)], target, {**MINIMAL[target], **options}))

    def test_png_adds_nothing_new(self):
        text = self.notes('Rotate → PNG'); self.assertNotIn('Salvo em', text); self.assertNotIn('transparência', text)

    def test_jpeg_report(self):
        text = self.notes('Rotate → PNG', out_format='jpeg', out_quality=70, out_flatten='#00ff00')
        self.assertIn('Salvo em JPEG (qualidade 70)', text); self.assertIn('com perda', text); self.assertIn('substituída pela cor #00FF00', text)

    def test_webp_report(self):
        self.assertIn('sem perda', self.notes('Rotate → PNG', out_format='webp', out_quality=100))
        self.assertIn('com perda (qualidade 60)', self.notes('Rotate → PNG', out_format='webp', out_quality=60))
        self.assertNotIn('substituída pela cor', self.notes('Rotate → PNG', out_format='webp', out_quality=60))

    def test_bmp_and_tiff_report(self):
        self.assertIn('BMP não tem transparência', self.notes('Rotate → PNG', out_format='bmp')); self.assertIn('Salvo em TIFF.', self.notes('Rotate → PNG', out_format='tiff'))

    def test_clean_and_redact_lossy_notes(self):
        self.assertIn('recompactados com perda', self.notes('Clean → PNG', out_format='jpeg'))
        self.assertIn('Os pixels não mudaram', self.notes('Clean → PNG', out_format='webp', out_quality=100))
        self.assertIn('antes da compactação', self.notes('Redact → PNG', out_format='jpeg'))
        self.assertNotIn('antes da compactação', self.notes('Redact → PNG', out_format='png'))

    def test_opaque_results_do_not_claim_transparency_loss(self):
        self.assertNotIn('transparência', self.notes('Canvas → PNG', out_format='jpeg').replace('A transparência foi substituída pela cor de fundo', ''))


class OutputPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def tearDown(self):
        if hasattr(self, 'tmp'):
            self.tmp.cleanup()

    def make_panel(self, tool='Resize → PNG'):
        controller = JobController(capabilities={'images': (True, 'ok'), 'pdf': (True, 'ok')})
        panel = FeaturePanel(controller)
        self.tmp = tempfile.TemporaryDirectory(); path = Path(self.tmp.name) / 'f.png'; Image.new('RGB', (200, 100), (100, 120, 140)).save(path)
        panel.set_files([str(path)], tool)
        return controller, panel

    def visible(self, panel):
        return {k for k, w in panel.form_fields.items() if panel.settings_form.isRowVisible(w)}

    def test_controls_follow_the_format(self):
        _c, panel = self.make_panel()
        self.assertEqual(self.visible(panel) & {'ofmt', 'oqual', 'oflat'}, {'ofmt'})                  # PNG: sem qualidade nem cor
        panel.out_format.setCurrentIndex(1); self.assertEqual(self.visible(panel) & {'ofmt', 'oqual', 'oflat'}, {'ofmt', 'oqual', 'oflat'})   # JPEG
        panel.out_format.setCurrentIndex(2); self.assertEqual(self.visible(panel) & {'ofmt', 'oqual', 'oflat'}, {'ofmt', 'oqual'})            # WebP
        panel.out_format.setCurrentIndex(3); self.assertEqual(self.visible(panel) & {'ofmt', 'oqual', 'oflat'}, {'ofmt'})                     # TIFF
        panel.out_format.setCurrentIndex(4); self.assertEqual(self.visible(panel) & {'ofmt', 'oqual', 'oflat'}, {'ofmt', 'oflat'})            # BMP
        for index in (5, 6): panel.out_format.setCurrentIndex(index); self.assertEqual(self.visible(panel) & {'ofmt', 'oqual', 'oflat'}, {'ofmt'})   # GIF e ICO

    def test_run_button_text_names_the_format(self):
        _c, panel = self.make_panel()
        self.assertEqual(panel.run_button.text(), 'Redimensionar e salvar PNG')
        panel.out_format.setCurrentIndex(2); self.assertEqual(panel.run_button.text(), 'Redimensionar e salvar WebP')
        panel.out_format.setCurrentIndex(1); self.assertEqual(panel.run_button.text(), 'Redimensionar e salvar JPEG')

    def test_format_is_not_offered_for_compress_or_conversions(self):
        _c, panel = self.make_panel('Compress → JPEG'); self.assertNotIn('ofmt', self.visible(panel))
        _c, panel = self.make_panel('PNG'); self.assertNotIn('ofmt', self.visible(panel))

    def test_options_are_sent(self):
        controller, panel = self.make_panel()
        with patch.object(controller, 'start_job') as start:
            panel.out_format.setCurrentIndex(1); panel.out_quality.setValue(77); panel.out_flatten.setText('#102030'); panel.run_selected()
            options = start.call_args.args[2]
            self.assertEqual((options['out_format'], options['out_quality'], options['out_flatten']), ('jpeg', 77, '#102030'))
            start.reset_mock(); panel.out_flatten.setText('azul'); panel.run_selected()
            start.assert_not_called(); self.assertIn('#RRGGBB', panel.status.text())

    def test_gate_of_tools_that_need_a_choice_survives_format_change(self):
        _c, panel = self.make_panel('Rotate → PNG')
        self.assertFalse(panel.run_button.isEnabled())
        panel.out_format.setCurrentIndex(1); self.assertFalse(panel.run_button.isEnabled())
        panel.rotate_angle.setCurrentIndex(1); self.assertTrue(panel.run_button.isEnabled())
        panel.out_format.setCurrentIndex(0); self.assertTrue(panel.run_button.isEnabled())

    def test_whitelist_accepts_output_options(self):
        controller = JobController(capabilities={'images': (True, 'ok'), 'pdf': (True, 'ok')}); controller.notify = lambda *a, **k: None
        controller._start_next = lambda: None
        path = Path(tempfile.mkdtemp()) / 'a.png'; Image.new('RGB', (4, 4)).save(path)
        self.assertTrue(controller.start_job([str(path)], 'Rotate → PNG', {'rotate_angle': 90, 'out_format': 'webp', 'out_quality': 100, 'out_flatten': '#FFFFFF'}))
        self.assertFalse(controller.start_job([str(path)], 'Rotate → PNG', {'out_quality': '90'}))
        self.assertFalse(controller.start_job([str(path)], 'Rotate → PNG', {'out_format': 5}))


if __name__ == '__main__':
    unittest.main()
