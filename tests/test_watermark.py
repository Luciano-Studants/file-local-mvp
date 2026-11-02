"""Ferramenta Marca d'água (Watermark → PNG): texto e imagem, posições, repetição, opacidade, validação, painel e relatório."""
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
from engine import ConversionError, TOOL_SUFFIX, WATERMARK_POSITIONS, convert, load_font, loss_report, watermark_image, watermark_options_from
from radial_menu import actions_for_selection, flatten_actions
from tray_app import FeaturePanel, JobController


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def options(**kw):
    return watermark_options_from({'watermark_text': 'Teste', 'watermark_scale': 30, 'watermark_opacity': 100, 'watermark_color': '#FFFFFF', **kw})


def bright_box(im):
    """Caixa dos pixels claros (a marca é branca sobre fundo escuro)."""
    return im.convert('RGB').point(lambda v: 255 if v > 200 else 0).getbbox()


class WatermarkOptionTests(unittest.TestCase):
    def test_defaults_and_roundtrip(self):
        got = watermark_options_from({'watermark_text': '  Oi  '})
        self.assertEqual((got['kind'], got['text'], got['scale'], got['opacity'], got['margin'], got['position'], got['color']), ('text', 'Oi', 25, 60, 3, 'br', '#FFFFFF'))

    def test_validation(self):
        bad = ({}, {'watermark_text': '   '}, {'watermark_text': 'x' * 101}, {'watermark_text': 'a\nb'}, {'watermark_text': 'ok', 'watermark_kind': 'video'},
               {'watermark_text': 'ok', 'watermark_position': 'xx'}, {'watermark_text': 'ok', 'watermark_scale': 0}, {'watermark_text': 'ok', 'watermark_scale': 101},
               {'watermark_text': 'ok', 'watermark_opacity': 0}, {'watermark_text': 'ok', 'watermark_margin': 26}, {'watermark_text': 'ok', 'watermark_margin': -1},
               {'watermark_text': 'ok', 'watermark_color': 'branco'}, {'watermark_text': 'ok', 'watermark_scale': 'x'},
               {'watermark_text': 'ok', 'watermark_position': 'tile', 'watermark_scale': 4}, {'watermark_kind': 'image'}, {'watermark_kind': 'image', 'watermark_image': '  '})
        for job in bad:
            with self.assertRaises(ConversionError, msg=str(job)):
                watermark_options_from(job)
        self.assertEqual(watermark_options_from({}, strict=False)['text'], '')               # modo não estrito: usado na prévia e no relatório


class WatermarkRenderTests(unittest.TestCase):
    def setUp(self):
        self.base = Image.new('RGB', (400, 300), (30, 60, 90))

    def test_text_width_follows_scale_and_positions(self):
        out = watermark_image(self.base, options(watermark_position='br', watermark_scale=30))
        box = bright_box(out); self.assertAlmostEqual((box[2] - box[0]) / 400, 0.30, delta=0.03)
        expected = {'tl': (0, 0), 'tr': (1, 0), 'bl': (0, 1), 'br': (1, 1), 'c': (.5, .5), 'tc': (.5, 0), 'bc': (.5, 1), 'ml': (0, .5), 'mr': (1, .5)}
        for position, (fx, fy) in expected.items():
            box = bright_box(watermark_image(self.base, options(watermark_position=position)))
            cx, cy = (box[0] + box[2]) / 2 / 400, (box[1] + box[3]) / 2 / 300
            self.assertLess(abs(cx - (0.5 if fx == .5 else (0.19 if fx == 0 else 0.81))), 0.06, position)
            self.assertLess(abs(cy - (0.5 if fy == .5 else (0.07 if fy == 0 else 0.93))), 0.06, position)

    def test_margin_moves_the_mark_away_from_the_edge(self):
        near = bright_box(watermark_image(self.base, options(watermark_position='tl', watermark_margin=0)))
        far = bright_box(watermark_image(self.base, options(watermark_position='tl', watermark_margin=20)))
        self.assertLess(near[0], far[0]); self.assertLess(near[1], far[1])
        self.assertLessEqual(near[0], 1)

    def test_opacity_blends_and_alpha_is_kept(self):
        full = watermark_image(self.base, options(watermark_opacity=100, watermark_position='c'))
        half = watermark_image(self.base, options(watermark_opacity=50, watermark_position='c'))
        px = lambda im: max(im.convert('RGB').getdata(), key=sum)
        self.assertGreater(sum(px(full)), sum(px(half))); self.assertGreater(sum(px(half)), sum((30, 60, 90)))
        transparent = Image.new('RGBA', (200, 100), (0, 0, 0, 0))
        out = watermark_image(transparent, options(watermark_position='c'))
        self.assertEqual(out.getpixel((0, 0))[3], 0); self.assertGreater(max(out.getchannel('A').getdata()), 200)   # fora da marca segue transparente

    def test_tile_covers_the_image_and_stays_inside(self):
        out = watermark_image(self.base, options(watermark_position='tile', watermark_scale=20, watermark_opacity=100))
        self.assertEqual(out.size, (400, 300))
        quadrants = [out.crop(box).convert('RGB').point(lambda v: 255 if v > 200 else 0).getbbox() for box in ((0, 0, 200, 150), (200, 0, 400, 150), (0, 150, 200, 300), (200, 150, 400, 300))]
        self.assertTrue(all(quadrants))                                                 # a marca aparece nos quatro quadrantes

    def test_image_mark_scales_and_keeps_its_alpha(self):
        logo = Image.new('RGBA', (100, 50), (255, 0, 0, 255))
        out = watermark_image(self.base, watermark_options_from({'watermark_kind': 'image', 'watermark_image': 'x.png', 'watermark_scale': 50, 'watermark_opacity': 100, 'watermark_position': 'c'}), logo)
        red = out.convert('RGB').point(lambda v: v).getdata()
        xs = [i % 400 for i, p in enumerate(red) if p[0] > 200 and p[1] < 80]
        self.assertAlmostEqual((max(xs) - min(xs) + 1) / 400, 0.50, delta=0.02)
        round_logo = Image.new('RGBA', (100, 100), (0, 0, 0, 0)); round_logo.paste((255, 0, 0, 255), (25, 25, 75, 75))
        out = watermark_image(self.base, watermark_options_from({'watermark_kind': 'image', 'watermark_image': 'x.png', 'watermark_scale': 50, 'watermark_opacity': 100, 'watermark_position': 'tl', 'watermark_margin': 0}), round_logo)
        self.assertEqual(out.getpixel((2, 2))[:3], (30, 60, 90))                       # canto transparente do logotipo não pinta

    def test_mark_never_exceeds_the_image(self):
        tall = Image.new('RGBA', (10, 1000), (255, 255, 255, 255))
        out = watermark_image(Image.new('RGB', (200, 100), 'black'), watermark_options_from({'watermark_kind': 'image', 'watermark_image': 'x', 'watermark_scale': 100, 'watermark_opacity': 100}), tall)
        self.assertEqual(out.size, (200, 100))

    def test_font_loader_always_returns_a_font(self):
        self.assertIsNotNone(load_font(20)); self.assertIsNotNone(load_font(20, bold=True))

    def test_preview_size_independence(self):
        """O mesmo ajuste em tamanhos diferentes dá a mesma proporção: a prévia reduzida confere com o arquivo final."""
        small = bright_box(watermark_image(Image.new('RGB', (200, 150), (30, 60, 90)), options(watermark_position='bl')))
        large = bright_box(watermark_image(Image.new('RGB', (800, 600), (30, 60, 90)), options(watermark_position='bl')))
        for a, b, size in zip(small, large, (200, 150, 200, 150)):
            self.assertAlmostEqual(a / size, b / (size * 4), delta=0.03)


class WatermarkEngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.source = self.root / 'a.png'; Image.new('RGB', (200, 100), (30, 60, 90)).save(self.source)
        self.logo = self.root / 'logo.png'; Image.new('RGBA', (40, 20), (255, 0, 0, 255)).save(self.logo)

    def tearDown(self):
        self.temp.cleanup()

    def run_job(self, **kw):
        before = digest(self.source); logo_before = digest(self.logo)
        out = Path(convert({'paths': [str(self.source)], 'target': 'Watermark → PNG', **kw})[0])
        self.assertEqual(digest(self.source), before); self.assertEqual(digest(self.logo), logo_before)
        return out

    def test_text_job(self):
        out = self.run_job(watermark_text='Oi', watermark_scale=40, watermark_opacity=100)
        self.assertTrue(out.name.endswith('-com-marca.png')); self.assertEqual(TOOL_SUFFIX['Watermark → PNG'], 'com-marca')
        with Image.open(out) as im: self.assertEqual(im.size, (200, 100)); self.assertTrue(bright_box(im))

    def test_image_job_and_formats(self):
        for key in ('png', 'jpeg', 'webp'):
            out = self.run_job(watermark_kind='image', watermark_image=str(self.logo), watermark_scale=30, watermark_opacity=100, out_format=key)
            with Image.open(out) as im:
                data = list(im.convert('RGB').getdata()); self.assertTrue(any(p[0] > 180 and p[1] < 90 for p in data), key)

    def test_invalid_jobs_leave_nothing(self):
        before = sorted(p.name for p in self.root.iterdir())
        cases = ({}, {'watermark_text': ' '}, {'watermark_kind': 'image'}, {'watermark_kind': 'image', 'watermark_image': str(self.root / 'nao-existe.png')},
                 {'watermark_kind': 'image', 'watermark_image': str(self.root)}, {'watermark_kind': 'image', 'watermark_image': 'relativo.png'},
                 {'watermark_text': 'x', 'watermark_opacity': 0})
        for job in cases:
            with self.assertRaises((ConversionError, OSError), msg=str(job)):
                convert({'paths': [str(self.source)], 'target': 'Watermark → PNG', **job})
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), before)

    def test_mark_image_must_be_a_supported_image_and_not_a_link(self):
        txt = self.root / 'logo.txt'; txt.write_text('x')
        with self.assertRaises(ConversionError):
            convert({'paths': [str(self.source)], 'target': 'Watermark → PNG', 'watermark_kind': 'image', 'watermark_image': str(txt)})
        link = self.root / 'link.png'
        try: os.symlink(self.logo, link)
        except (OSError, NotImplementedError): self.skipTest('sem privilégio para links simbólicos')
        with self.assertRaises(ConversionError):
            convert({'paths': [str(self.source)], 'target': 'Watermark → PNG', 'watermark_kind': 'image', 'watermark_image': str(link)})

    def test_never_overwrites(self):
        first = self.run_job(watermark_text='Oi'); second = self.run_job(watermark_text='Oi')
        self.assertNotEqual(first, second); self.assertTrue(first.exists() and second.exists())

    def test_loss_report(self):
        text = ' '.join(loss_report([str(self.source)], 'Watermark → PNG', {'watermark_text': 'Oi', 'watermark_position': 'tile', 'watermark_opacity': 40, 'watermark_scale': 20}))
        self.assertIn('repetida na diagonal', text); self.assertIn('40 % de opacidade', text); self.assertIn('não dá para removê-la', text)
        text = ' '.join(loss_report([str(self.source)], 'Watermark → PNG', {'watermark_kind': 'image', 'watermark_image': str(self.logo)}))
        self.assertIn('no canto inferior direito', text); self.assertIn('não foi alterado', text)

    def test_position_list_matches_ui_order(self):
        self.assertEqual(WATERMARK_POSITIONS, ('tl', 'tc', 'tr', 'ml', 'c', 'mr', 'bl', 'bc', 'br', 'tile'))


class WatermarkUITests(unittest.TestCase):
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
            path = Path(self.tmp.name) / f'f{index}.png'; Image.new('RGB', (300, 200), (30, 60, 90)).save(path); paths.append(str(path))
        self.logo = Path(self.tmp.name) / 'logo.png'; Image.new('RGBA', (50, 25), (255, 0, 0, 255)).save(self.logo)
        panel.set_files(paths, 'Watermark → PNG')
        return controller, panel

    def visible(self, panel):
        return {k for k, w in panel.form_fields.items() if panel.settings_form.isRowVisible(w)}

    def test_registry_wheel_and_icon(self):
        import icons
        self.assertIn('__tool_watermark__', [a.target for a in flatten_actions(actions_for_selection([r'C:\x\p.png']))])
        self.assertIn('watermark', icons.ICON_SHAPES); self.assertEqual(tool_registry.BY_TARGET['Watermark → PNG'].group, 'draw')
        self.assertEqual(tool_registry.BY_TARGET['Watermark → PNG'].label, 'Marca')

    def test_controls_follow_kind_and_position(self):
        _c, panel = self.make_panel()
        base = {'wkind', 'wscale', 'wopacity', 'wpos', 'ofmt'}
        self.assertEqual(self.visible(panel) & (base | {'wtext', 'wcolor', 'wimage', 'wmargin'}), base | {'wtext', 'wcolor', 'wmargin'})
        panel.wm_kind.setCurrentIndex(1)
        self.assertEqual(self.visible(panel) & (base | {'wtext', 'wcolor', 'wimage', 'wmargin'}), base | {'wimage', 'wmargin'})
        panel.wm_position.setCurrentIndex(9)
        self.assertNotIn('wmargin', self.visible(panel))

    def test_run_requires_text_or_image(self):
        controller, panel = self.make_panel()
        with patch.object(controller, 'start_job') as start:
            panel.run_selected(); start.assert_not_called(); self.assertIn('texto', panel.status.text())
            panel.wm_kind.setCurrentIndex(1); panel.run_selected(); start.assert_not_called(); self.assertIn('imagem', panel.status.text())

    def test_options_are_sent(self):
        controller, panel = self.make_panel(count=2)
        with patch.object(controller, 'start_job') as start:
            panel.wm_text.setText('Confidencial'); panel.wm_scale.setValue(40); panel.wm_opacity.setValue(35); panel.wm_position.setCurrentIndex(4); panel.wm_color.setText('#FF0000')
            panel.run_selected()
            paths, target, sent = start.call_args.args
            self.assertEqual((len(paths), target), (2, 'Watermark → PNG'))
            self.assertEqual((sent['watermark_kind'], sent['watermark_text'], sent['watermark_scale'], sent['watermark_opacity'], sent['watermark_position'], sent['watermark_color']),
                             ('text', 'Confidencial', 40, 35, 'c', '#FF0000'))

    def test_choose_image_sets_path_and_sends_it(self):
        controller, panel = self.make_panel()
        with patch('workspace_panel.QFileDialog.getOpenFileName', return_value=(str(self.logo), '')), patch.object(controller, 'start_job') as start:
            panel.wm_kind.setCurrentIndex(1); panel.choose_watermark_image()
            self.assertTrue(panel.wm_image_path.text().endswith('logo.png'))
            panel.run_selected(); sent = start.call_args.args[2]
            self.assertEqual((sent['watermark_kind'], os.path.normcase(sent['watermark_image'])), ('image', os.path.normcase(panel.wm_image_path.text())))

    def test_non_image_file_is_refused_before_queueing(self):
        controller, panel = self.make_panel()
        with patch.object(controller, 'start_job') as start:
            panel.wm_kind.setCurrentIndex(1); panel.wm_image_path.setText(str(Path(self.tmp.name) / 'nota.txt')); panel.run_selected()
            start.assert_not_called(); self.assertIn('imagem suportada', panel.status.text())

    def test_live_preview_changes_with_the_text(self):
        _c, panel = self.make_panel()
        panel.wm_text.setText('Marca'); self.app.processEvents()
        self.assertIn('prévia', panel.tool_hint.text().lower())
        panel.wm_text.setText(''); self.assertIn('Digite o texto', panel.tool_hint.text())

    def test_multiple_files_use_the_same_mark(self):
        _c, panel = self.make_panel(count=3)
        self.assertIn('várias', panel.tool_hint.text())

    def test_whitelist_accepts_long_image_path_but_not_other_long_strings(self):
        controller = JobController(capabilities={'images': (True, 'ok'), 'pdf': (True, 'ok')}); controller.notify = lambda *a, **k: None; controller._start_next = lambda: None
        path = Path(tempfile.mkdtemp()) / 'a.png'; Image.new('RGB', (4, 4)).save(path)
        self.assertTrue(controller.start_job([str(path)], 'Watermark → PNG', {'watermark_kind': 'image', 'watermark_image': 'C:\\' + 'a' * 300 + '.png', 'watermark_text': 'x'}))
        self.assertFalse(controller.start_job([str(path)], 'Watermark → PNG', {'watermark_text': 'x' * 201}))
        self.assertFalse(controller.start_job([str(path)], 'Watermark → PNG', {'watermark_image': 'a' * 1025}))
        self.assertFalse(controller.start_job([str(path)], 'Watermark → PNG', {'watermark_scale': '30'}))


if __name__ == '__main__':
    unittest.main()
