"""Remoção de fundo (0.9.25): núcleo `bgremove.py`, allowlist por SHA-256, opções, relatório, motor, worker e painel.

Os testes que rodam a rede de verdade são pulados quando o ONNX Runtime ou o modelo `u2netp` não está instalado.
"""
import hashlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PIL import Image, ImageDraw
from PySide6.QtWidgets import QApplication

import bgremove
import engine
import tool_registry
from engine import ConversionError, bg_options_from, convert, loss_report
from tray_app import FeaturePanel, JobController

import workspace_panel


def tray_stage_static():
    return workspace_panel.STAGE_STATIC


TARGET = 'Remove Background → PNG'
READY = bgremove.status('u2netp')[0]
needs_model = unittest.skipUnless(READY, 'onnxruntime ou o modelo u2netp não está instalado')


def sample_image(size=(480, 320)):
    """Foto sintética: fundo azul liso e uma elipse laranja, grande e central, com textura (o objeto de destaque)."""
    im = Image.new('RGB', size, (40, 90, 170)); draw = ImageDraw.Draw(im)
    w, h = size
    draw.ellipse((w * 0.25, h * 0.15, w * 0.75, h * 0.85), fill=(235, 140, 40))
    for step in range(0, 10):
        draw.ellipse((w * (0.33 + step * 0.01), h * (0.3 + step * 0.04), w * (0.6 - step * 0.01), h * (0.6 + step * 0.02)), outline=(250, 200 - step * 10, 90), width=3)
    return im


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class CoreTests(unittest.TestCase):
    def test_model_table_is_pinned(self):
        self.assertEqual(bgremove.DEFAULT_MODEL, 'u2netp'); self.assertEqual(set(bgremove.MODELS), {'u2netp', 'u2net'})
        self.assertNotIn('isnet-general-use', bgremove.MODELS)           # DIS5K: só uso não comercial
        for name, digest, size, label, bundled in bgremove.MODELS.values():
            self.assertTrue(name.endswith('.onnx')); self.assertEqual(len(digest), 64); self.assertGreater(size, 1000); self.assertTrue(label)
        self.assertTrue(bgremove.MODELS['u2netp'][4]); self.assertFalse(bgremove.MODELS['u2net'][4])

    @needs_model
    def test_bundled_model_matches_the_pinned_hash(self):
        path = bgremove.model_path('u2netp')
        self.assertEqual((sha(path), path.stat().st_size), (bgremove.MODELS['u2netp'][1], bgremove.MODELS['u2netp'][2]))

    def test_missing_model_is_reported_in_portuguese(self):
        with patch.object(bgremove, 'app_dirs', return_value=[Path(tempfile.gettempdir()) / 'sem-modelos-aqui']):
            ready, message = bgremove.status('u2net')
            self.assertFalse(ready); self.assertIn('u2net.onnx', message); self.assertIn('models', message); self.assertIn('nada é baixado', message)
            self.assertEqual(bgremove.installed_models(), [])
            with self.assertRaises(bgremove.BgError): bgremove.remove_background(Image.new('RGB', (20, 20)), 'u2net')

    def test_unknown_model_is_refused(self):
        self.assertFalse(bgremove.status('isnet-general-use')[0])
        with self.assertRaises(bgremove.BgError): bgremove.remove_background(Image.new('RGB', (20, 20)), '../u2net')
        self.assertIsNone(bgremove.model_path('../../etc/passwd'))

    def test_wrong_size_or_content_is_not_loaded(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / 'models').mkdir(); fake = Path(tmp) / 'models' / 'u2netp.onnx'
            with patch.object(bgremove, 'app_dirs', return_value=[Path(tmp)]):
                bgremove.reset_sessions()
                fake.write_bytes(b'x' * 100)
                with self.assertRaisesRegex(bgremove.BgError, 'tamanho diferente'): bgremove.predict_mask(Image.new('RGB', (20, 20)), 'u2netp')
                fake.write_bytes(b'x' * bgremove.MODELS['u2netp'][2])             # tamanho certo, conteúdo errado
                with self.assertRaisesRegex(bgremove.BgError, 'SHA-256'): bgremove.predict_mask(Image.new('RGB', (20, 20)), 'u2netp')
            bgremove.reset_sessions()

    def test_feather_validation(self):
        for bad in (-1, bgremove.MAX_FEATHER + 1, 1.5, '2', True, None):
            with self.assertRaises(bgremove.BgError): bgremove.remove_background(Image.new('RGB', (20, 20)), 'u2netp', bad)

    def test_libraries_missing_message(self):
        with patch.object(bgremove, 'libraries_ready', return_value=False):
            ready, message = bgremove.status(); self.assertFalse(ready); self.assertIn('onnxruntime', message)
            with self.assertRaises(bgremove.BgError): bgremove.remove_background(Image.new('RGB', (20, 20)))

    def test_coverage(self):
        rgba = Image.new('RGBA', (10, 10), (0, 0, 0, 0)); self.assertEqual(bgremove.coverage(rgba), 0.0)
        rgba.paste((0, 0, 0, 255), (0, 0, 10, 5)); self.assertEqual(bgremove.coverage(rgba), 0.5)

    @needs_model
    def test_real_inference_cuts_the_background(self):
        source = sample_image(); out = bgremove.remove_background(source, 'u2netp', 0)
        self.assertEqual((out.mode, out.size), ('RGBA', source.size)); self.assertEqual(source.mode, 'RGB')
        w, h = out.size
        self.assertGreater(out.getpixel((w // 2, h // 2))[3], 200); self.assertLess(out.getpixel((4, 4))[3], 40); self.assertLess(out.getpixel((w - 5, h - 5))[3], 40)
        self.assertEqual(out.getpixel((w // 2, h // 2))[:3], source.getpixel((w // 2, h // 2)))        # as cores não mudam, só o alfa
        self.assertGreater(bgremove.coverage(out), 0.1)

    @needs_model
    def test_existing_transparency_is_kept_and_feather_softens(self):
        source = sample_image().convert('RGBA'); source.paste((0, 0, 0, 0), (0, 0, 100, source.height))        # faixa já transparente
        sharp = bgremove.remove_background(source, 'u2netp', 0); soft = bgremove.remove_background(source, 'u2netp', 8)
        self.assertEqual(sharp.getpixel((50, source.height // 2))[3], 0); self.assertEqual(soft.getpixel((50, source.height // 2))[3], 0)
        mid = lambda image: len([v for v in image.getchannel('A').getdata() if 20 < v < 235])
        self.assertGreaterEqual(mid(soft), mid(sharp))

    @needs_model
    def test_palette_gray_and_tiny_images(self):
        for image in (sample_image().convert('L'), sample_image().convert('P'), sample_image((3, 2)), Image.new('RGB', (1, 1), 'white')):
            out = bgremove.remove_background(image, 'u2netp', 1); self.assertEqual((out.mode, out.size), ('RGBA', image.size))


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.source = Path(self.tmp.name) / 'foto.png'; sample_image().save(self.source); self.out = Path(self.tmp.name) / 'saida'; self.out.mkdir()

    def run_job(self, source, options):
        return [str(path) for path in convert({'paths': [str(source)], 'target': TARGET, 'output': str(self.out), **options})]

    def test_registry(self):
        spec = tool_registry.BY_TARGET[TARGET]
        self.assertEqual((spec.key, spec.ext, spec.group, spec.int_options, spec.str_options, spec.suffix), ('removebg', 'png', 'look', ('bg_feather',), ('bg_model',), 'sem-fundo'))
        self.assertIn(TARGET, tool_registry.FORMAT_TARGETS); self.assertIn('bg_model', tool_registry.all_str_options()); self.assertIn('bg_feather', tool_registry.all_int_options())
        self.assertEqual(spec.label, 'Sem fundo'); self.assertLessEqual(len(spec.label), 10)

    def test_option_defaults_and_validation(self):
        self.assertEqual(bg_options_from({}), {'model': 'u2netp', 'feather': 2})
        self.assertEqual(bg_options_from({'bg_model': 'u2net', 'bg_feather': 0}), {'model': 'u2net', 'feather': 0})
        for bad in ({'bg_model': 'isnet-general-use'}, {'bg_model': 4}, {'bg_feather': 11}, {'bg_feather': -1}, {'bg_feather': True}, {'bg_feather': '3'}):
            with self.assertRaises(ConversionError): bg_options_from(bad)
        self.assertEqual(bg_options_from({'bg_model': 'x', 'bg_feather': 99}, strict=False), {'model': 'u2netp', 'feather': 2})

    def test_report(self):
        text = ' '.join(loss_report([str(self.source)], TARGET, {'bg_feather': 4}))
        for word in ('rede neural', 'U²-Net', 'confira', 'sem internet', '4 px', 'transparente', 'original não muda'): self.assertIn(word, text)
        with patch.object(bgremove, 'status', return_value=(False, 'Modelo ausente XYZ.')): self.assertIn('Modelo ausente XYZ.', ' '.join(loss_report([str(self.source)], TARGET, {})))
        self.assertIn('branco', ' '.join(loss_report([str(self.source)], TARGET, {'out_format': 'jpeg'})))

    def test_invalid_options_create_nothing(self):
        for bad in ({'bg_model': 'nope'}, {'bg_feather': 50}):
            with self.assertRaises(ConversionError): self.run_job(self.source, bad)
        self.assertEqual(list(self.out.iterdir()), [])

    def test_missing_model_creates_nothing(self):
        with patch.object(bgremove, 'status', return_value=(False, 'Modelo ausente XYZ.')):
            with self.assertRaisesRegex(ConversionError, 'XYZ'): self.run_job(self.source, {})
        self.assertEqual(list(self.out.iterdir()), [])

    def test_empty_result_is_refused(self):
        with patch.object(bgremove, 'status', return_value=(True, '')), patch.object(bgremove, 'predict_mask', side_effect=lambda image, model: Image.new('L', image.size, 0)):
            with self.assertRaisesRegex(ConversionError, 'nenhum objeto'): self.run_job(self.source, {})
        self.assertEqual(list(self.out.iterdir()), [])

    def test_engine_error_is_translated(self):
        with patch.object(bgremove, 'status', return_value=(True, '')), patch.object(bgremove, 'remove_background', side_effect=bgremove.BgError('Falhou XYZ.')):
            with self.assertRaisesRegex(ConversionError, 'Falhou XYZ'): self.run_job(self.source, {})

    def test_non_image_is_refused(self):
        pdf = Path(self.tmp.name) / 'a.pdf'; pdf.write_bytes(b'%PDF-1.4')
        with self.assertRaises(ConversionError): self.run_job(pdf, {})

    @needs_model
    def test_end_to_end_png_keeps_original_and_never_overwrites(self):
        before = sha(self.source)
        first = self.run_job(self.source, {'bg_feather': 2}); second = self.run_job(self.source, {})
        self.assertEqual(sha(self.source), before); self.assertNotEqual(first[0], second[0])
        self.assertTrue(Path(first[0]).name.startswith('foto-sem-fundo')); self.assertEqual(Path(first[0]).suffix, '.png')
        with Image.open(first[0]) as result:
            self.assertEqual((result.mode, result.size), ('RGBA', (480, 320))); self.assertLess(result.getpixel((3, 3))[3], 40); self.assertGreater(result.getpixel((240, 160))[3], 200)
            self.assertNotIn('exif', result.info)

    @needs_model
    def test_jpeg_output_flattens_on_white(self):
        paths = self.run_job(self.source, {'out_format': 'jpeg', 'out_flatten': '#FFFFFF'})
        with Image.open(paths[0]) as result:
            self.assertEqual(result.format, 'JPEG'); r, g, b = result.getpixel((3, 3)); self.assertGreater(min(r, g, b), 200)

    @needs_model
    def test_worker_process_with_limits(self):
        import runner
        result = runner.run_job({'paths': [str(self.source)], 'target': TARGET, 'output': str(self.out), 'bg_feather': 1}, timeout=120)
        with Image.open(result[0]) as image: self.assertEqual(image.mode, 'RGBA'); self.assertLess(image.getpixel((2, 2))[3], 40)

    @needs_model
    def test_large_image_fits_in_the_worker(self):
        import runner
        big = Path(self.tmp.name) / 'grande.png'; Image.new('RGB', (7000, 5700), (40, 90, 170)).save(big)       # ≈ 39,9 MP
        with Image.open(big) as im:
            canvas = im.copy(); ImageDraw.Draw(canvas).ellipse((1750, 1425, 5250, 4275), fill=(235, 140, 40)); canvas.save(big); canvas.close()
        result = runner.run_job({'paths': [str(big)], 'target': TARGET, 'output': str(self.out)}, timeout=160)
        with Image.open(result[0]) as image: self.assertEqual(image.size, (7000, 5700))


class PanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make_panel(self, target=TARGET):
        controller = JobController(capabilities={'images': (True, 'ok'), 'pdf': (True, 'ok')}); panel = FeaturePanel(controller)
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup); path = Path(tmp.name) / 'f.png'; sample_image().save(path)
        panel.set_files([str(path)], target); return controller, panel

    def visible(self, panel):
        return {k for k, w in panel.form_fields.items() if panel.settings_form.isRowVisible(w)}

    def test_controls_and_button(self):
        _c, panel = self.make_panel()
        self.assertTrue({'bmodel', 'bfeather', 'ofmt'} <= self.visible(panel)); self.assertEqual(panel.run_button.text(), 'Remover fundo e salvar PNG')
        self.assertEqual((panel.bg_model.count(), panel.bg_feather.value()), (2, 2)); self.assertEqual(panel.run_button.isEnabled(), READY)

    def test_options_are_sent(self):
        controller, panel = self.make_panel()
        with patch.object(controller, 'start_job') as start, patch.object(bgremove, 'status', return_value=(True, '')):
            panel.bg_model.setCurrentIndex(1); panel.bg_feather.setValue(7); panel.run_selected()
            _paths, target, options = start.call_args.args[:3]
            self.assertEqual((target, options['bg_model'], options['bg_feather']), (TARGET, 'u2net', 7))

    def test_run_is_blocked_with_message_when_model_is_missing(self):
        controller, panel = self.make_panel()
        with patch.object(controller, 'start_job') as start, patch.object(bgremove, 'status', return_value=(False, 'Modelo ausente XYZ.')):
            panel.select_tool(TARGET); panel.run_selected()
            start.assert_not_called(); self.assertIn('XYZ', panel.status.text()); self.assertFalse(panel.run_button.isEnabled())

    @needs_model
    def test_preview_button_shows_the_result_over_a_checkerboard(self):
        controller, panel = self.make_panel()
        self.assertIn('bpreview', self.visible(panel)); before = panel.tool_hint.text()
        panel._bg_preview()
        self.assertIn('xadrez', panel.tool_hint.text()); self.assertNotEqual(before, panel.tool_hint.text())
        self.assertEqual(panel.stage.currentIndex(), tray_stage_static())

    def test_preview_button_explains_when_the_model_is_missing(self):
        _c, panel = self.make_panel()
        with patch.object(bgremove, 'status', return_value=(False, 'Modelo ausente XYZ.')):
            panel._bg_preview()
        self.assertIn('XYZ', panel.tool_hint.text())

    def test_controller_accepts_options(self):
        controller = JobController(capabilities={'images': (True, 'ok'), 'pdf': (True, 'ok')}); controller._start_next = lambda: None; controller.notify = lambda *a, **k: None
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'a.png'; sample_image().save(path)
            self.assertTrue(controller.start_job([str(path)], TARGET, {'bg_model': 'u2netp', 'bg_feather': 3}))
            self.assertFalse(controller.start_job([str(path)], TARGET, {'bg_feather': 'x'}))


if __name__ == '__main__':
    unittest.main()
