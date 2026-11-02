"""Ferramenta Formas (Shapes → PNG): validação, desenho medido, setas e retas, suavização, ordem, alfa, job, painel e relatório."""
import hashlib
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PIL import Image, ImageChops
from PySide6.QtCore import QRectF
from PySide6.QtWidgets import QApplication

import tool_registry
from engine import ConversionError, SHAPE_MAX_ITEMS, TOOL_SUFFIX, convert, draw_shape, loss_report, shape_endpoints, shape_items_from, shapes_image
from radial_menu import actions_for_selection, flatten_actions
from tray_app import FeaturePanel, JobController

RED = (255, 0, 0, 255)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def item(kind='rect', x=10, y=10, w=60, h=40, color='#FF0000', thickness=4, fill=0, dir=0):
    return {'kind': kind, 'x': x, 'y': y, 'w': w, 'h': h, 'color': color, 'thickness': thickness, 'fill': fill, 'dir': dir}


def canvas(size=(120, 100), color=(255, 255, 255, 255)):
    return Image.new('RGBA', size, color)


def paint(*items, size=(120, 100), base=None):
    return shapes_image(base or canvas(size), shape_items_from({'shape_items': list(items)}, size))


def is_red(px, tol=40):
    return px[0] > 255 - tol and px[1] < tol and px[2] < tol


class ShapeValidationTests(unittest.TestCase):
    def test_valid_item_is_normalised(self):
        got = shape_items_from({'shape_items': [item('line', color='#ff00aa', fill=1, dir=2), item('rect', fill=1, dir=3)]}, (120, 100))
        self.assertEqual((got[0]['color'], got[0]['fill'], got[0]['dir']), ('#FF00AA', 0, 2)); self.assertEqual((got[1]['fill'], got[1]['dir']), (1, 0))

    def test_rejections(self):
        size = (120, 100)
        bad_items = (item(kind='star'), item(color='red'), item(color='#12345'), item(thickness=0), item(thickness=201), item(fill=2), item(dir=4),
                     item(w=0), item(h=0), item(x=-1), item(y=-1), item(x=70, w=60), item(y=70, h=40), 'x', {'kind': 'rect', 'x': 'a', 'y': 0, 'w': 5, 'h': 5})
        for bad in bad_items:
            with self.assertRaises(ConversionError, msg=str(bad)): shape_items_from({'shape_items': [bad]}, size)
        for raw in (None, [], 'x', [item()] * (SHAPE_MAX_ITEMS + 1)):
            with self.assertRaises(ConversionError): shape_items_from({'shape_items': raw}, size)

    def test_box_exactly_filling_the_image_is_allowed(self):
        shape_items_from({'shape_items': [item(x=0, y=0, w=120, h=100)]}, (120, 100))


class ShapeEndpointTests(unittest.TestCase):
    def test_four_directions(self):
        base = item('line', x=10, y=20, w=40, h=30)
        got = [shape_endpoints({**base, 'dir': d}) for d in range(4)]
        self.assertEqual(got[0], ((10, 20), (50, 50))); self.assertEqual(got[1], ((50, 20), (10, 50)))
        self.assertEqual(got[2], ((10, 50), (50, 20))); self.assertEqual(got[3], ((50, 50), (10, 20)))

    def test_flat_boxes_snap_to_a_straight_line(self):
        (x0, y0), (x1, y1) = shape_endpoints(item('arrow', x=10, y=20, w=100, h=6, dir=0)); self.assertEqual((y0, y1, x0, x1), (23, 23, 10, 110))
        (x0, y0), (x1, y1) = shape_endpoints(item('arrow', x=10, y=20, w=100, h=6, dir=3)); self.assertEqual((y0, y1, x0, x1), (23, 23, 110, 10))
        (x0, y0), (x1, y1) = shape_endpoints(item('line', x=10, y=20, w=6, h=100, dir=1)); self.assertEqual((x0, x1, y0, y1), (13, 13, 20, 120))
        (x0, y0), (x1, y1) = shape_endpoints(item('line', x=10, y=20, w=40, h=30)); self.assertNotEqual(y0, y1)               # caixa normal não achata


class ShapeRenderTests(unittest.TestCase):
    def test_rect_outline_is_inside_the_box_and_hollow(self):
        out = paint(item('rect', x=10, y=10, w=60, h=40, thickness=4))
        for point in ((10, 30), (69, 30), (40, 10), (40, 49), (11, 11)): self.assertTrue(is_red(out.getpixel(point)), point)
        self.assertEqual(out.getpixel((40, 30)), (255, 255, 255, 255)); self.assertEqual(out.getpixel((9, 30)), (255, 255, 255, 255)); self.assertEqual(out.getpixel((40, 14)), (255, 255, 255, 255))
        box = ImageChops.difference(out.convert('RGB'), canvas().convert('RGB')).getbbox()
        self.assertTrue(box[0] >= 9 and box[1] >= 9 and box[2] <= 71 and box[3] <= 51, box)

    def test_thickness_is_measured(self):
        for t in (2, 6, 12):
            out = paint(item('rect', x=10, y=10, w=80, h=60, thickness=t)); run = sum(1 for y in range(10, 40) if is_red(out.getpixel((50, y)), 80))
            self.assertAlmostEqual(run, t, delta=1)

    def test_filled_rect_covers_inside(self):
        out = paint(item('rect', fill=1)); self.assertTrue(is_red(out.getpixel((40, 30)))); self.assertEqual(out.getpixel((5, 5)), (255, 255, 255, 255))

    def test_ellipse_leaves_box_corners_and_touches_edge_midpoints(self):
        out = paint(item('ellipse', x=10, y=10, w=80, h=60, thickness=4))
        self.assertEqual(out.getpixel((11, 11)), (255, 255, 255, 255)); self.assertTrue(is_red(out.getpixel((11, 40)), 60)); self.assertTrue(is_red(out.getpixel((50, 11)), 60))
        self.assertEqual(out.getpixel((50, 40)), (255, 255, 255, 255)); self.assertTrue(is_red(paint(item('ellipse', x=10, y=10, w=80, h=60, fill=1)).getpixel((50, 40))))

    def test_edges_are_antialiased(self):
        out = paint(item('ellipse', x=10, y=10, w=80, h=80, thickness=3)); tones = {out.getpixel((x, y))[1] for x in range(120) for y in range(100)}
        self.assertGreater(len(tones), 6)                                                                    # há tons intermediários, não só vermelho e branco

    def test_line_runs_corner_to_corner_and_is_straight_when_flat(self):
        out = paint(item('line', x=10, y=10, w=80, h=60, thickness=3)); self.assertTrue(is_red(out.getpixel((10, 10)), 90)); self.assertTrue(is_red(out.getpixel((89, 69)), 90))
        self.assertTrue(is_red(out.getpixel((50, 40)), 90)); self.assertEqual(out.getpixel((10, 69)), (255, 255, 255, 255))
        flat = paint(item('line', x=10, y=40, w=90, h=4, thickness=4)); self.assertTrue(is_red(flat.getpixel((50, 42)))); self.assertEqual(flat.getpixel((50, 30)), (255, 255, 255, 255))

    def test_arrow_head_is_wider_than_the_shaft_and_sits_at_the_end(self):
        item_ = item('arrow', x=10, y=40, w=100, h=4, thickness=3, dir=0); out = paint(item_)
        column = lambda x: sum(1 for y in range(100) if not out.getpixel((x, y))[1] > 200)
        self.assertLessEqual(column(30), 5); self.assertGreater(column(99), column(30) + 6)                  # perto da ponta (direita) é bem mais largo
        self.assertGreater(column(99), column(12) + 6)
        back = paint({**item_, 'dir': 3}); backcol = lambda x: sum(1 for y in range(100) if not back.getpixel((x, y))[1] > 200)
        self.assertGreater(backcol(21), backcol(100) + 6)                                                    # sentido invertido: a ponta vai para a esquerda

    def test_arrow_tip_reaches_the_corner_without_overshoot(self):
        out = paint(item('arrow', x=10, y=40, w=100, h=4, thickness=3, dir=0)); xs = [x for x in range(120) for y in range(100) if not out.getpixel((x, y))[1] > 200]
        self.assertLessEqual(max(xs), 110); self.assertGreaterEqual(max(xs), 108)

    def test_later_shapes_cover_earlier_ones(self):
        out = paint(item('rect', fill=1, color='#FF0000'), item('rect', x=20, y=20, w=20, h=20, fill=1, color='#0000FF'))
        self.assertEqual(out.getpixel((30, 30))[:3], (0, 0, 255)); self.assertTrue(is_red(out.getpixel((60, 40))))

    def test_alpha_of_transparent_png_is_preserved_outside_shapes(self):
        base = Image.new('RGBA', (120, 100), (0, 0, 0, 0)); out = paint(item('rect', fill=1), base=base)
        self.assertEqual(out.getpixel((0, 0))[3], 0); self.assertEqual(out.getpixel((40, 30)), RED); self.assertEqual(base.getpixel((40, 30))[3], 0)   # origem intacta

    def test_stroke_at_the_image_edge_is_clipped_not_an_error(self):
        out = paint(item('rect', x=0, y=0, w=120, h=100, thickness=30)); self.assertTrue(is_red(out.getpixel((0, 0)))); self.assertEqual(out.size, (120, 100))
        out = paint(item('arrow', x=0, y=0, w=120, h=100, thickness=60)); self.assertEqual(out.size, (120, 100))

    def test_non_rgba_input_is_converted(self):
        out = shapes_image(Image.new('L', (50, 50), 255), [shape_items_from({'shape_items': [item(x=5, y=5, w=30, h=30, fill=1)]}, (50, 50))[0]]); self.assertEqual(out.mode, 'RGBA')

    def test_big_shape_stays_fast_and_correct(self):
        size = (3000, 3000); big = Image.new('RGBA', size, (255, 255, 255, 255)); start = time.time()
        shapes_image(big, shape_items_from({'shape_items': [item('ellipse', x=0, y=0, w=3000, h=3000, thickness=40)]}, size))
        self.assertLess(time.time() - start, 20)
        self.assertTrue(is_red(big.getpixel((10, 1500)), 255) is False)                                      # entrada não é alterada; a cópia é

    def test_draw_shape_mutates_only_its_target(self):
        a = canvas(); b = a.copy(); draw_shape(a, shape_items_from({'shape_items': [item(fill=1)]}, (120, 100))[0]); self.assertIsNotNone(ImageChops.difference(a.convert('RGB'), b.convert('RGB')).getbbox())


class ShapeEngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.source = self.root / 'a.png'; Image.new('RGB', (120, 100), (255, 255, 255)).save(self.source)

    def tearDown(self):
        self.temp.cleanup()

    def run_job(self, items, **kw):
        before = digest(self.source)
        out = Path(convert({'paths': [str(self.source)], 'target': 'Shapes → PNG', 'shape_items': items, **kw})[0])
        self.assertEqual(digest(self.source), before)
        return out

    def test_job_writes_new_file(self):
        out = self.run_job([item(fill=1), item('arrow', x=20, y=70, w=80, h=5)])
        self.assertTrue(out.name.endswith('-com-formas.png')); self.assertEqual(TOOL_SUFFIX['Shapes → PNG'], 'com-formas')
        with Image.open(out) as im: self.assertEqual(im.size, (120, 100)); self.assertTrue(is_red(im.convert('RGBA').getpixel((40, 30))))

    def test_formats_and_invalid_input(self):
        for key in ('png', 'jpeg', 'webp', 'tiff', 'bmp'): self.assertTrue(self.run_job([item()], out_format=key).exists())
        with self.assertRaises(ConversionError): convert({'paths': [str(self.source)], 'target': 'Shapes → PNG'})
        with self.assertRaises(ConversionError): convert({'paths': [str(self.source)], 'target': 'Shapes → PNG', 'shape_items': [item(x=100, w=60)]})

    def test_exif_orientation_uses_the_oriented_size(self):
        rotated = self.root / 'r.jpg'; im = Image.new('RGB', (120, 100), (255, 255, 255)); exif = Image.Exif(); exif[274] = 6; im.save(rotated, exif=exif)   # vira 100 × 120
        out = Path(convert({'paths': [str(rotated)], 'target': 'Shapes → PNG', 'shape_items': [item(x=0, y=0, w=100, h=120, fill=1)]})[0])
        with Image.open(out) as result: self.assertEqual(result.size, (100, 120)); self.assertTrue(is_red(result.convert('RGBA').getpixel((50, 110))))
        with self.assertRaises(ConversionError): convert({'paths': [str(rotated)], 'target': 'Shapes → PNG', 'shape_items': [item(x=0, y=0, w=120, h=100)]})

    def test_loss_report(self):
        text = ' '.join(loss_report([str(self.source)], 'Shapes → PNG', {'shape_items': [item(), item('arrow'), item('arrow')]}))
        self.assertIn('3 forma(s)', text); self.assertIn('1 retângulo', text); self.assertIn('2 seta', text); self.assertIn('nos pixels', text)


class ShapeUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def tearDown(self):
        if hasattr(self, 'panel'):
            self.panel.allow_close = True; self.panel.close()
        if hasattr(self, 'tmp'):
            self.tmp.cleanup()

    def make_panel(self, count=1):
        self.controller = JobController(capabilities={'images': (True, 'ok'), 'pdf': (True, 'ok')}); self.panel = FeaturePanel(self.controller)
        self.tmp = tempfile.TemporaryDirectory(); paths = []
        for index in range(count):
            path = Path(self.tmp.name) / f'f{index}.png'; Image.new('RGB', (300, 200), (255, 255, 255)).save(path); paths.append(str(path))
        self.panel.set_files(paths, 'Shapes → PNG')
        return self.controller, self.panel

    def visible(self, panel):
        return {k for k, w in panel.form_fields.items() if panel.settings_form.isRowVisible(w)}

    def select(self, box):
        panel = self.panel; bounds = panel.crop_preview.image_bounds(); sx, sy = bounds.width() / 300, bounds.height() / 200
        panel.crop_preview.set_selection(QRectF(box[0] * sx, box[1] * sy, box[2] * sx, box[3] * sy)); panel._crop_selection_changed()

    def test_registry_wheel_group_and_icon(self):
        import icons
        spec = tool_registry.BY_TARGET['Shapes → PNG']; self.assertEqual((spec.group, spec.label, spec.single_file, spec.risk), ('draw', 'Formas', True, 'médio'))
        self.assertIn('shapes', icons.ICON_SHAPES); self.assertIn('__tool_shapes__', [a.target for a in flatten_actions(actions_for_selection([r'C:\x\p.png']))])
        self.assertEqual([s.label for s in tool_registry.group_members('draw')], ['Anotar', 'Formas', 'Marca'])
        self.assertEqual([s.label for s in tool_registry.group_members('look')], ['Ajustar', 'Níveis', 'Nitidez', 'Fundo', 'Sem fundo'])

    def test_controls_follow_the_kind(self):
        _c, panel = self.make_panel(); common = {'hkind', 'hcolor', 'hthick', 'hhelp', 'hbuttons', 'ofmt'}
        self.assertEqual(self.visible(panel) & (common | {'hfill', 'hdir'}), common | {'hfill'}); self.assertEqual(panel.stage.currentIndex(), 1)
        panel.sh_kind.setCurrentIndex(3); self.assertEqual(self.visible(panel) & (common | {'hfill', 'hdir'}), common | {'hdir'})
        panel.sh_kind.setCurrentIndex(2); self.assertIn('hdir', self.visible(panel))

    def test_add_undo_and_help(self):
        _c, panel = self.make_panel(); self.assertFalse(panel.sh_undo_button.isEnabled())
        self.select((20, 20, 100, 60)); panel.add_shape(); self.assertEqual(len(panel.shape_items), 1); self.assertIn('1 forma', panel.sh_help.text())
        self.assertTrue(panel.sh_undo_button.isEnabled()); self.assertIsNotNone(panel.crop_preview.overlay_item); self.assertEqual(panel.crop_preview.committed, [])
        panel.undo_shape(); self.assertEqual(panel.shape_items, []); self.assertIsNone(panel.crop_preview.overlay_item)

    def test_add_without_selection_or_with_bad_color(self):
        _c, panel = self.make_panel(); panel.add_shape(); self.assertIn('Arraste', panel.status.text()); self.assertEqual(panel.shape_items, [])
        self.select((20, 20, 100, 60)); panel.sh_color.setText('#12'); panel.add_shape(); self.assertIn('#RRGGBB', panel.status.text()); self.assertEqual(panel.shape_items, [])

    def test_preview_overlay_shows_the_pending_shape_live(self):
        _c, panel = self.make_panel(); self.assertIsNone(panel.crop_preview.overlay_item)
        self.select((20, 20, 100, 60)); self.assertIsNotNone(panel.crop_preview.overlay_item)
        panel.sh_color.setText('#0000FF'); self.assertIsNotNone(panel.crop_preview.overlay_item)

    def test_style_is_stored_per_shape(self):
        _c, panel = self.make_panel()
        self.select((20, 20, 100, 60)); panel.sh_color.setText('#00FF00'); panel.sh_fill.setCurrentIndex(1); panel.add_shape()
        panel.sh_kind.setCurrentIndex(3); panel.sh_dir.setCurrentIndex(2); panel.sh_color.setText('#0000FF'); panel.sh_thickness.slider.setValue(9); self.select((150, 20, 120, 80)); panel.add_shape()
        a, b = panel.shape_items; self.assertEqual((a['kind'], a['color'], a['fill']), ('rect', '#00FF00', 1)); self.assertEqual((b['kind'], b['color'], b['dir'], b['thickness'], b['fill']), ('arrow', '#0000FF', 2, 9, 0))

    def test_run_sends_confirmed_and_pending_shapes(self):
        controller, panel = self.make_panel(); self.select((20, 20, 100, 60)); panel.add_shape(); self.select((150, 100, 100, 60)); sent = {}
        with patch.object(controller, 'start_job', side_effect=lambda files, target, options: sent.update(target=target, options=options) or True):
            panel.run_selected()
        self.assertEqual(sent['target'], 'Shapes → PNG'); items = sent['options']['shape_items']; self.assertEqual(len(items), 2)
        self.assertTrue(all(type(v) is int for it in items for k, v in it.items() if k not in ('kind', 'color')))
        shape_items_from({'shape_items': items}, (300, 200))

    def test_run_without_shapes_is_refused(self):
        controller, panel = self.make_panel()
        with patch.object(controller, 'start_job') as start: panel.run_selected(); start.assert_not_called(); self.assertIn('Desenhe', panel.status.text())

    def test_several_files_are_refused_with_explanation(self):
        _c, panel = self.make_panel(count=2); self.assertIn('uma imagem por vez', panel.preview_image.text())

    def test_reopening_resets_the_shapes(self):
        _c, panel = self.make_panel(); self.select((20, 20, 100, 60)); panel.add_shape(); panel.sh_kind.setCurrentIndex(1); panel.sh_color.setText('#00FF00')
        panel.set_files([panel.files[0]], 'Shapes → PNG'); self.assertEqual(panel.shape_items, []); self.assertEqual((panel.sh_kind.currentIndex(), panel.sh_color.text()), (0, '#FF0000'))

    def test_default_thickness_follows_image_size(self):
        _c, panel = self.make_panel(); self.assertEqual(panel.sh_thickness.value(), 2)

    def test_whitelist(self):
        controller = JobController(capabilities={'images': (True, 'ok'), 'pdf': (True, 'ok')}); controller.notify = lambda *a, **k: None; controller._start_next = lambda: None
        path = Path(tempfile.mkdtemp()) / 'a.png'; Image.new('RGB', (40, 40)).save(path); ok = item()
        self.assertTrue(controller.start_job([str(path)], 'Shapes → PNG', {'shape_items': [ok]}))
        for bad in ([ok] * 51, [{**ok, 'x': '1'}], [{**ok, 'extra': 1}], [{**ok, 'kind': 'x' * 17}], [{**ok, 'color': '#FFFFFFF0'}], ['x'], [{**ok, 'thickness': True}], 'x'):
            self.assertFalse(controller.start_job([str(path)], 'Shapes → PNG', {'shape_items': bad}), msg=str(bad)[:60])
        self.assertFalse(controller.start_job([str(path), str(path)], 'Shapes → PNG', {'shape_items': [ok]}))             # só uma imagem por vez


if __name__ == '__main__':
    unittest.main()
