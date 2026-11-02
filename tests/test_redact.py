"""Ferramenta Ocultar (Redact → PNG): motor, validação, painel e roda."""
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

from engine import ConversionError, TOOL_SUFFIX, convert, loss_report
from radial_menu import RadialAction, actions_for_selection, flatten_actions
import tool_registry
from tray_app import FeaturePanel, JobController


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def noisy(size=(120, 80)):
    im = Image.new('RGB', size)
    im.putdata([((x * 7) % 256, (y * 13) % 256, ((x + y) * 5) % 256) for y in range(size[1]) for x in range(size[0])])
    return im


class RedactEngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def run_job(self, path, **options):
        before = digest(path)
        out = convert({'paths': [str(path)], 'target': 'Redact → PNG', **options})[0]
        self.assertEqual(digest(path), before)
        return Path(out)

    def test_black_burns_opaque_pixels_only_inside_regions(self):
        path = self.root / 'a.png'; noisy().save(path)
        out = self.run_job(path, redact_regions=[[10, 10, 30, 20], [60, 40, 20, 20]], redact_mode='black')
        self.assertIn('ocultada', out.name)
        with Image.open(out) as im, Image.open(path) as src:
            self.assertEqual(im.size, src.size)
            rgba = im.convert('RGBA'); source = src.convert('RGBA')
            for x, y in ((10, 10), (39, 29), (60, 40), (79, 59)):
                self.assertEqual(rgba.getpixel((x, y)), (0, 0, 0, 255))
            for x, y in ((9, 10), (40, 29), (0, 0), (100, 70), (59, 40)):
                self.assertEqual(rgba.getpixel((x, y)), source.getpixel((x, y)))

    def test_pixelate_replaces_detail_with_block_average(self):
        path = self.root / 'a.png'; noisy().save(path)
        out = self.run_job(path, redact_regions=[[0, 0, 64, 64]], redact_mode='pixelate', redact_block=16)
        with Image.open(out) as im, Image.open(path) as src:
            rgba = im.convert('RGB'); source = src.convert('RGB')
            # dentro de um bloco 16×16 todos os pixels são iguais
            colors = {rgba.getpixel((x, y)) for x in range(16) for y in range(16)}
            self.assertEqual(len(colors), 1)
            self.assertNotEqual(rgba.getpixel((1, 1)), source.getpixel((1, 1)))
            self.assertEqual(rgba.getpixel((100, 70)), source.getpixel((100, 70)))
            # a cor do bloco é a média da origem (tolerância de arredondamento)
            block = [source.getpixel((x, y)) for x in range(16) for y in range(16)]
            mean = tuple(sum(c[i] for c in block) / len(block) for i in range(3))
            for got, want in zip(colors.pop(), mean):
                self.assertAlmostEqual(got, want, delta=2)

    def test_transparent_pixels_do_not_leak_through_the_region(self):
        path = self.root / 't.png'; Image.new('RGBA', (40, 40), (255, 0, 0, 0)).save(path)
        for mode in ('black', 'pixelate'):
            out = self.run_job(path, redact_regions=[[5, 5, 20, 20]], redact_mode=mode, redact_block=8)
            with Image.open(out) as im:
                self.assertEqual(im.convert('RGBA').getpixel((10, 10))[3], 255, mode)
                self.assertEqual(im.convert('RGBA').getpixel((30, 30))[3], 0, mode)

    def test_metadata_is_not_copied(self):
        path = self.root / 'm.jpg'
        im = noisy(); exif = Image.Exif(); exif[0x010F] = 'CameraMaker'; im.save(path, exif=exif)
        out = self.run_job(path, redact_regions=[[0, 0, 10, 10]])
        with Image.open(out) as result:
            self.assertEqual(len(result.getexif()), 0)

    def test_invalid_options_are_rejected_without_output(self):
        path = self.root / 'a.png'; noisy().save(path)
        bad = [dict(), dict(redact_regions=[]), dict(redact_regions=[[0, 0, 0, 5]]), dict(redact_regions=[[-1, 0, 5, 5]]),
               dict(redact_regions=[[100, 0, 30, 5]]), dict(redact_regions=[[0, 0, 5]]), dict(redact_regions=[['a', 0, 5, 5]]),
               dict(redact_regions=[[0, 0, 5, 5]] * 51), dict(redact_regions=[[0, 0, 5, 5]], redact_mode='blur'),
               dict(redact_regions=[[0, 0, 5, 5]], redact_mode='pixelate', redact_block=2),
               dict(redact_regions=[[0, 0, 5, 5]], redact_mode='pixelate', redact_block=500)]
        for options in bad:
            with self.assertRaises(ConversionError, msg=str(options)):
                convert({'paths': [str(path)], 'target': 'Redact → PNG', **options})
        self.assertEqual([p.name for p in self.root.iterdir()], ['a.png'])

    def test_regions_use_the_oriented_image(self):
        path = self.root / 'o.jpg'
        im = Image.new('RGB', (80, 40), (10, 200, 10)); exif = Image.Exif(); exif[0x0112] = 6; im.save(path, exif=exif)
        # após o EXIF a imagem fica 40×80: a área (0, 50, 40, 30) só cabe na versão orientada
        out = self.run_job(path, redact_regions=[[0, 50, 40, 30]])
        with Image.open(out) as result:
            self.assertEqual(result.size, (40, 80))
            self.assertEqual(result.convert('RGB').getpixel((5, 60)), (0, 0, 0))

    def test_report_mentions_burned_pixels(self):
        path = self.root / 'a.png'; noisy().save(path)
        text = ' '.join(loss_report([str(path)], 'Redact → PNG', {'redact_regions': [[0, 0, 5, 5], [9, 9, 5, 5]], 'redact_mode': 'pixelate'}))
        self.assertIn('2 área(s)', text); self.assertIn('pixelização', text); self.assertIn('Não é anonimização certificada', text)

    def test_suffix_is_registered(self):
        self.assertEqual(TOOL_SUFFIX['Redact → PNG'], 'ocultada')


class RedactUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make_panel(self, size=(300, 200), count=1):
        controller = JobController(capabilities={'images': (True, 'ok'), 'pdf': (True, 'ok')})
        panel = FeaturePanel(controller)
        self.tmp = tempfile.TemporaryDirectory()
        paths = []
        for index in range(count):
            path = Path(self.tmp.name) / f'a{index}.png'; Image.new('RGB', size, (200, 30, 30)).save(path); paths.append(str(path))
        panel.set_files(paths, 'Redact → PNG')
        return controller, panel

    def tearDown(self):
        if hasattr(self, 'tmp'):
            self.tmp.cleanup()

    def test_radial_and_wheel_entries(self):
        targets = [a.target for a in flatten_actions(actions_for_selection([r'C:\x\p.png']))]
        self.assertIn('__tool_redact__', targets)
        self.assertEqual(RadialAction('Ocultar', '__tool_redact__').icon, 'redact')
        import icons, workspace_panel
        self.assertIn('redact', icons.ICON_SHAPES)
        self.assertIn('Redact → PNG', tool_registry.flat_targets(workspace_panel.WHEEL_COLUMNS['images'][1][2]))

    def test_flow_adds_regions_and_sends_them(self):
        controller, panel = self.make_panel()
        visible = sorted(k for k, w in panel.form_fields.items() if panel.settings_form.isRowVisible(w) and k not in ('nname', 'nexample', 'nstart', 'ndigits'))
        self.assertEqual(visible, ['ofmt', 'rbuttons', 'rhelp', 'rmode'])
        self.assertEqual(panel.stage.currentIndex(), 1)
        self.assertEqual(panel.run_button.text(), 'Ocultar e salvar PNG')
        panel.crop_preview.set_selection(panel.crop_preview.image_bounds().adjusted(30, 20, -150, -100))
        panel._crop_selection_changed()
        panel.add_redact_region()
        self.assertEqual(len(panel.redact_regions), 1)
        self.assertEqual(len(panel.crop_preview.committed), 1)
        self.assertIsNotNone(panel.crop_preview.overlay_item)
        self.assertIn('1 área', panel.redact_help.text())
        panel.crop_preview.set_selection(panel.crop_preview.image_bounds().adjusted(200, 100, -10, -10))
        panel._crop_selection_changed()
        panel.redact_mode.setCurrentIndex(1)
        self.assertTrue(panel.settings_form.isRowVisible(panel.redact_block))
        panel.redact_block.setValue(24)
        captured = {}
        with patch.object(controller, 'start_job', side_effect=lambda files, target, options: captured.update(target=target, options=options) or True):
            panel.run_selected()                     # a área ainda não confirmada entra também
        o = captured['options']
        self.assertEqual(captured['target'], 'Redact → PNG')
        self.assertEqual(len(o['redact_regions']), 2)
        self.assertEqual((o['redact_mode'], o['redact_block']), ('pixelate', 24))
        self.assertTrue(all(len(r) == 4 and all(type(v) is int for v in r) for r in o['redact_regions']))
        x, y, w, h = o['redact_regions'][0]
        self.assertEqual((x, y), (30, 20)); self.assertGreater(w, 100)
        panel.undo_redact_region()
        self.assertEqual(len(panel.redact_regions), 0)
        panel.allow_close = True; panel.close()

    def test_without_area_or_with_many_files_nothing_runs(self):
        controller, panel = self.make_panel()
        with patch.object(controller, 'start_job') as start:
            panel.run_selected()
            start.assert_not_called()
        self.assertIn('pelo menos uma área', panel.status.text())
        panel.allow_close = True; panel.close()
        controller, panel = self.make_panel(count=2)
        self.assertIn('uma imagem por vez', panel.preview_image.text())
        with patch.object(controller, 'start_job') as start:
            panel.run_selected()
            start.assert_not_called()
        panel.allow_close = True; panel.close()

    def test_controller_validates_regions(self):
        controller = JobController(capabilities={'images': (True, 'ok'), 'pdf': (True, 'ok')})
        notices = []
        controller.notify = lambda title, text: notices.append(text)
        good = {'redact_regions': [[0, 0, 5, 5]], 'redact_mode': 'black', 'redact_block': 16}
        with patch.object(controller, 'start_next', create=True), patch('tray_app.validate_selection', side_effect=lambda p: p):
            for bad in ({'redact_regions': 'x'}, {'redact_regions': [[0, 0, 5]]}, {'redact_regions': [[0, 0, 5, 5.5]]}, {'redact_regions': [[0, 0, 5, 5]] * 51}):
                self.assertFalse(controller.start_job([r'C:\a.png'], 'Redact → PNG', bad), bad)
            self.assertFalse(controller.start_job([r'C:\a.png', r'C:\b.png'], 'Redact → PNG', good))


class RedactPreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'n.png'; noisy((300, 200)).save(self.path)
        self.controller = JobController(capabilities={'images': (True, 'ok'), 'pdf': (True, 'ok')})
        self.panel = FeaturePanel(self.controller)
        self.panel.set_files([str(self.path)], 'Redact → PNG')

    def tearDown(self):
        self.panel.allow_close = True; self.panel.close(); self.tmp.cleanup()

    def select(self, box):
        bounds = self.panel.crop_preview.image_bounds()
        sx, sy = bounds.width() / 300, bounds.height() / 200
        from PySide6.QtCore import QRectF
        self.panel.crop_preview.set_selection(QRectF(box[0] * sx, box[1] * sy, box[2] * sx, box[3] * sy))
        self.panel._crop_selection_changed()

    def overlay_image(self):
        item = self.panel.crop_preview.overlay_item
        self.assertIsNotNone(item)
        return item.pixmap().toImage()

    def test_pending_selection_is_previewed_in_black_and_scene_is_not_dimmed(self):
        self.assertFalse(self.panel.crop_preview.dim_outside)
        self.assertIsNone(self.panel.crop_preview.overlay_item)
        self.select((50, 40, 100, 80))
        image = self.overlay_image()
        scale = image.width() / 300
        inside = image.pixelColor(round(100 * scale), round(80 * scale))
        self.assertEqual((inside.red(), inside.green(), inside.blue()), (0, 0, 0))
        outside = image.pixelColor(round(10 * scale), round(10 * scale))
        self.assertGreater(outside.red() + outside.green() + outside.blue(), 0)

    def test_pixelate_preview_shows_blocks_and_follows_mode_and_block_size(self):
        self.panel.redact_mode.setCurrentIndex(1); self.panel.redact_block.setValue(40)
        self.select((0, 0, 200, 120)); self.panel.add_redact_region()
        image = self.overlay_image()
        scale = image.width() / 300
        block = max(1, round(40 * scale))
        first = image.pixelColor(1, 1)
        for dx in (0, block - 1):
            for dy in (0, block - 1):
                self.assertEqual(image.pixelColor(dx, dy).rgb(), first.rgb())   # um bloco = uma cor
        self.assertNotEqual(image.pixelColor(block + 1, 1).rgb(), first.rgb())
        self.panel.redact_block.setValue(4)
        smaller = self.overlay_image()
        self.assertNotEqual(smaller.pixelColor(1, 1).rgb(), smaller.pixelColor(max(1, round(8 * scale)), 1).rgb())
        self.panel.redact_mode.setCurrentIndex(0)
        black = self.overlay_image()
        self.assertEqual(black.pixelColor(5, 5).rgb(), 0xff000000)

    def test_undo_and_leaving_the_tool_remove_the_preview(self):
        self.select((10, 10, 50, 50)); self.panel.add_redact_region()
        self.assertIsNotNone(self.panel.crop_preview.overlay_item)
        self.panel.undo_redact_region()
        self.assertIsNone(self.panel.crop_preview.overlay_item)
        self.select((10, 10, 50, 50)); self.panel.add_redact_region()
        self.panel.select_tool('Crop → PNG')
        self.assertIsNone(self.panel.crop_preview.overlay_item)
        self.assertTrue(self.panel.crop_preview.dim_outside)

    def test_preview_matches_the_engine_output_on_a_downscaled_copy(self):
        from engine import redact_apply, redact_image
        im = noisy((300, 200))
        regions = [(20, 30, 90, 60)]
        a = redact_image(im, regions, 'pixelate', 16); b = redact_apply(im, regions, 'pixelate', 16)
        from PIL import ImageChops
        self.assertIsNone(ImageChops.difference(a, b).getbbox())
        with self.assertRaises(ConversionError):
            redact_image(im, regions, 'pixelate', 2)                # o motor continua validando o bloco
        self.assertEqual(redact_apply(im, regions, 'pixelate', 1).size, im.size)   # a prévia pode usar blocos menores


if __name__ == '__main__':
    unittest.main()
