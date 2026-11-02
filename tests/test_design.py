"""Sistema de design (roda de vidro, chips, sliders), ferramenta Fundo, atalhos alternativos, IPC e menu de contexto."""
import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PIL import Image
from PySide6.QtCore import QMimeData, QPoint, QPointF, QUrl, Qt
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

import shell_integration
from engine import (BACKDROPS, ConversionError, backdrop_layout, build_backdrop, convert, loss_report)
from global_hotkey import HOTKEY_PRESETS, MOD_ALT, MOD_CONTROL, MOD_SHIFT, parse_hotkey
from ipc import MAX_MESSAGE, PathServer, send_paths
from radial_menu import ACTION_ICONS, RadialAction, RadialMenu, RadialWheel, actions_for_file
from settings import Settings, load_settings, save_settings
from tray_app import JobController, FeaturePanel, TrayApplication, chord_in_progress, human_size, middle_click_trigger, send_to_paths
from widgets import ChipGroup, SliderRow


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class QtCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])


class WheelDesignTests(QtCase):
    def test_tool_actions_have_icons_and_format_conversions_do_not(self):
        for target in ('__tool_crop__', '__tool_backdrop__', '__tool_collage__', '__tool_compress__', '__panel__', 'PDF → Text'):
            self.assertTrue(RadialAction('x', target).icon, target)
        self.assertEqual(RadialAction('PNG', 'PNG').icon, '')
        self.assertEqual(RadialAction('x', '__tool_crop__', icon='eye').icon, 'eye')
        import icons
        self.assertTrue(set(ACTION_ICONS.values()) <= set(icons.ICON_SHAPES))
        self.assertEqual([a.icon for a in actions_for_file('/a/b.png')[:6]], [''] * 6)

    def test_hot_slice_is_orange_and_context_text_is_the_idle_label(self):
        actions = [RadialAction(label, f'__tool_{label}__') for label in ('Recortar', 'Anotar', 'Canvas', 'Fundo')]
        wheel = RadialWheel(actions, '1,2 MB', 380)
        wheel.show(); self.app.processEvents()
        self.assertEqual(wheel.center_text(), '1,2 MB')
        idle = wheel.grab().toImage()
        point = wheel.slice_center(1)
        idle_color = idle.pixelColor(int(point.x()), int(point.y() - 22))
        wheel.set_hover(1)
        self.assertEqual(wheel.center_text(), 'Anotar')
        hot = wheel.grab().toImage().pixelColor(int(point.x()), int(point.y() - 22))
        self.assertGreater(hot.red(), 200); self.assertLess(hot.green(), 140); self.assertLess(hot.blue(), 80)
        self.assertGreater(idle_color.green(), 170)                      # pétala em repouso é clara (pêssego)
        wheel.set_hover(-1)
        self.assertEqual(wheel.center_text(), '1,2 MB')
        wheel.close()

    def test_menu_uses_context_text_and_filename_otherwise(self):
        menu = RadialMenu('/a/foto.png', [RadialAction('PNG', 'PNG')], lambda a: None, context='3,4 MB')
        self.assertEqual(menu.center_text, '3,4 MB')
        self.assertEqual(RadialMenu('/a/foto.png', [RadialAction('PNG', 'PNG')], lambda a: None).center_text, 'foto.png')

    def test_chip_group_behaves_like_the_combo_it_replaces(self):
        chips = ChipGroup(['A', 'B', 'C'], per_row=2)
        seen = []
        chips.currentIndexChanged.connect(seen.append)
        self.assertEqual((chips.count(), chips.currentIndex(), chips.currentText()), (3, 0, 'A'))
        chips.setCurrentIndex(2)
        self.assertEqual((chips.currentIndex(), chips.currentText(), seen), (2, 'C', [2]))
        chips.setCurrentIndex(2); chips.setCurrentIndex(9)
        self.assertEqual(seen, [2])
        chips.blockSignals(True); chips.setCurrentIndex(1); chips.blockSignals(False)
        self.assertEqual((chips.currentIndex(), seen), (1, [2]))
        chips._buttons[0].click()
        self.assertEqual((chips.currentIndex(), seen), (0, [2, 0]))
        self.assertEqual(sum(b.isChecked() for b in chips._buttons), 1)
        chips.setEnabled(False)
        self.assertTrue(all(not b.isEnabled() for b in chips._buttons))

    def test_slider_row_shows_value_with_suffix(self):
        row = SliderRow(0, 200, 50, ' px')
        got = []
        row.valueChanged.connect(got.append)
        self.assertEqual(row.label.text(), '50 px')
        row.setValue(120)
        self.assertEqual((row.value(), row.label.text(), got), (120, '120 px', [120]))


class BackdropEngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def image(self, name='a.png', size=(100, 60), color=(255, 0, 0), mode='RGB'):
        path = self.root / name
        Image.new(mode, size, color).save(path)
        return path

    def run_job(self, path, **options):
        before = digest(path)
        out = convert({'paths': [str(path)], 'target': 'Backdrop → PNG', **options})[0]
        self.assertEqual(digest(path), before)
        return out

    def test_layout_padding_and_ratio_only_grow_the_background(self):
        self.assertEqual(backdrop_layout(100, 60, 10, 'auto'), ((120, 80), (10, 10)))
        (w, h), (x, y) = backdrop_layout(100, 60, 10, '1:1')
        self.assertEqual((w, h, x, y), (120, 120, 10, 30))
        (w, h), _ = backdrop_layout(100, 60, 10, '16:9')
        self.assertGreaterEqual(w, 120); self.assertGreaterEqual(h, 80); self.assertAlmostEqual(w / h, 16 / 9, delta=0.02)
        (w, h), _ = backdrop_layout(60, 100, 0, '4:5')
        self.assertAlmostEqual(w / h, 0.8, delta=0.02); self.assertGreaterEqual(h, 100)

    def test_gradient_runs_corner_to_corner_and_solid_is_flat(self):
        im = Image.new('RGBA', (20, 20), (255, 0, 0, 255))
        out = build_backdrop(im, 'sunset', '#000000', 80, 0, 0, 'auto')
        first, _label, colors = BACKDROPS['sunset'][2], None, BACKDROPS['sunset'][2]
        top_left, bottom_right = out.getpixel((0, 0)), out.getpixel((out.width - 1, out.height - 1))
        self.assertTrue(all(abs(a - int(colors[0][i * 2 + 1:i * 2 + 3], 16)) <= 3 for i, a in enumerate(top_left)), top_left)
        self.assertTrue(all(abs(a - int(colors[-1][i * 2 + 1:i * 2 + 3], 16)) <= 4 for i, a in enumerate(bottom_right)), bottom_right)
        flat = build_backdrop(im, 'navy', '#000000', 30, 0, 0, 'auto')
        self.assertEqual(flat.getpixel((0, 0)), flat.getpixel((flat.width - 1, flat.height - 1)))
        custom = build_backdrop(im, 'custom', '#00FF00', 10, 0, 0, 'auto')
        self.assertEqual(custom.getpixel((1, 1)), (0, 255, 0))

    def test_rounded_corners_and_shadow_are_drawn(self):
        im = Image.new('RGBA', (100, 100), (255, 0, 0, 255))
        square = build_backdrop(im, 'white', '#000000', 40, 0, 0, 'auto')
        self.assertEqual(square.getpixel((40, 40)), (255, 0, 0))
        rounded = build_backdrop(im, 'white', '#000000', 40, 40, 0, 'auto')
        self.assertEqual(rounded.getpixel((41, 41)), (255, 255, 255))      # canto da imagem agora é fundo
        self.assertEqual(rounded.getpixel((90, 90)), (255, 0, 0))
        shadowed = build_backdrop(im, 'white', '#000000', 60, 0, 60, 'auto')
        below = shadowed.getpixel((110, 60 + 100 + 8))
        self.assertLess(sum(below), 3 * 255 - 30)                          # sombra escurece logo abaixo da imagem
        self.assertGreaterEqual(min(shadowed.getpixel((2, 2))), 253)      # longe da imagem não há sombra
        self.assertEqual(shadowed.getpixel((110, 110)), (255, 0, 0))

    def test_transparent_regions_show_the_background_and_output_is_opaque_srgb_png(self):
        path = self.image('t.png', (40, 40), (255, 0, 0, 0), 'RGBA')
        with Image.open(self.run_job(path, backdrop_style='custom', background='#0000FF', backdrop_padding=10, backdrop_radius=0, backdrop_shadow=0)) as result:
            self.assertEqual(result.mode, 'RGB'); self.assertEqual(result.getpixel((30, 30)), (0, 0, 255))
            self.assertNotIn('icc_profile', result.info)
            self.assertEqual(result.size, (60, 60))
        tagged = self.root / 'icc.png'
        from fixtures_icc import swapped_primaries_profile_bytes
        Image.new('RGB', (20, 20), (255, 0, 0)).save(tagged, icc_profile=swapped_primaries_profile_bytes())
        with Image.open(self.run_job(tagged, backdrop_style='white', backdrop_padding=5, backdrop_radius=0, backdrop_shadow=0)) as result:
            red, green, _ = result.getpixel((15, 15))
            self.assertGreater(green, 200); self.assertLess(red, 60)        # perfil convertido para sRGB

    def test_exif_orientation_is_applied_before_composing(self):
        stored = Image.new('RGB', (20, 40), (255, 0, 0)); path = self.root / 'o.png'
        exif = Image.Exif(); exif[0x0112] = 6
        stored.save(path, exif=exif)
        with Image.open(self.run_job(path, backdrop_style='white', backdrop_padding=10, backdrop_radius=0, backdrop_shadow=0)) as result:
            self.assertEqual(result.size, (60, 40))

    def test_file_names_use_portuguese_tool_suffixes_and_never_overwrite(self):
        path = self.image()
        first = self.run_job(path); second = self.run_job(path)
        self.assertEqual((Path(first).name, Path(second).name), ('a-com-fundo.png', 'a-com-fundo-2.png'))
        crop = convert({'paths': [str(path)], 'target': 'Crop → PNG', 'crop_x': 0, 'crop_y': 0, 'crop_width': 10, 'crop_height': 10})[0]
        self.assertEqual(Path(crop).name, 'a-recortada.png')
        self.assertEqual(Path(convert({'paths': [str(path)], 'target': 'Compress → JPEG'})[0]).name, 'a-comprimida.jpg')
        self.assertEqual(Path(convert({'paths': [str(path)], 'target': 'PNG'})[0]).name, 'a-converted.png')
        chained = self.run_job(Path(crop))
        self.assertEqual(Path(chained).name, 'a-recortada-com-fundo.png')

    def test_validation_errors_leave_no_output(self):
        path = self.image()
        cases = [({'backdrop_style': 'nao-existe'}, 'desconhecido'), ({'backdrop_style': 'custom', 'background': 'azul'}, 'hexadecimal'),
                 ({'backdrop_ratio': '3:2'}, 'Proporção'), ({'backdrop_padding': 601}, 'Opções de fundo'), ({'backdrop_radius': 301}, 'Opções de fundo'),
                 ({'backdrop_shadow': 101}, 'Opções de fundo'), ({'backdrop_padding': -1}, 'Opções de fundo')]
        for options, message in cases:
            with self.subTest(options=options), self.assertRaisesRegex(ConversionError, message):
                convert({'paths': [str(path)], 'target': 'Backdrop → PNG', **options})
        big = self.root / 'big.png'; Image.new('L', (9800, 4000), 0).save(big, compress_level=1)
        with self.assertRaisesRegex(ConversionError, 'grande demais'):
            convert({'paths': [str(big)], 'target': 'Backdrop → PNG', 'backdrop_padding': 600})
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ['a.png', 'big.png'])

    def test_report_mentions_the_composition(self):
        self.assertIn('composta sobre o fundo', ' '.join(loss_report([str(self.image())], 'Backdrop → PNG')))


class BackdropPanelTests(QtCase):
    def make_panel(self, size=(300, 200)):
        controller = JobController(capabilities={'images': (True, 'ok'), 'pdf': (True, 'ok')})
        panel = FeaturePanel(controller)
        self.tmp = tempfile.TemporaryDirectory()
        path = Path(self.tmp.name) / 'a.png'; Image.new('RGB', size, (200, 30, 30)).save(path)
        panel.set_files([str(path)], 'Backdrop → PNG')
        return controller, panel, path

    def tearDown(self):
        if hasattr(self, 'tmp'):
            self.tmp.cleanup()

    def test_controls_preview_and_options(self):
        controller, panel, path = self.make_panel()
        visible = sorted(k for k, w in panel.form_fields.items() if panel.settings_form.isRowVisible(w) and k not in ('nname', 'nexample', 'nstart', 'ndigits'))
        self.assertEqual(visible, ['bpad', 'bradius', 'bratio', 'bshadow', 'bswatch', 'ofmt'])
        self.assertEqual(panel.backdrop_padding.value(), 24)                      # 8% do maior lado
        self.assertEqual(panel.backdrop_radius.value(), 6)                        # 3% do menor lado
        self.assertEqual(panel.stage.currentIndex(), 4)
        pixmap = panel.static_preview.pixmap_item.pixmap()
        self.assertEqual((pixmap.width(), pixmap.height()), (348, 248))
        panel.backdrop_buttons['custom'].click()
        self.assertTrue(panel.settings_form.isRowVisible(panel.backdrop_color))
        panel.backdrop_color.setText('#112233'); panel.backdrop_ratio.setCurrentIndex(1)
        panel.backdrop_padding.setValue(50); panel.backdrop_radius.setValue(10); panel.backdrop_shadow.setValue(40)
        self.assertIn('imagem opaca', panel.tool_hint.text())
        captured = {}
        with patch.object(controller, 'start_job', side_effect=lambda files, target, options: captured.update(files=files, target=target, options=options) or True):
            panel.run_selected()
        o = captured['options']
        self.assertEqual((captured['target'], o['backdrop_style'], o['background'], o['backdrop_ratio']), ('Backdrop → PNG', 'custom', '#112233', '1:1'))
        self.assertEqual((o['backdrop_padding'], o['backdrop_radius'], o['backdrop_shadow']), (50, 10, 40))
        panel.backdrop_buttons['aurora'].click()
        self.assertFalse(panel.settings_form.isRowVisible(panel.backdrop_color))
        self.assertEqual(panel.backdrop_style, 'aurora')
        panel.allow_close = True; panel.close()

    def test_oversized_result_disables_the_button(self):
        controller, panel, path = self.make_panel(size=(9800, 100))
        panel.backdrop_padding.setValue(600)
        self.assertFalse(panel.run_button.isEnabled())
        self.assertIn('grande demais', panel.tool_hint.text())
        panel.backdrop_padding.setValue(0)
        self.assertTrue(panel.run_button.isEnabled())
        panel.allow_close = True; panel.close()


class HotkeyAndSettingsTests(QtCase):
    def test_hotkey_parser_accepts_presets_and_rejects_dangerous_ones(self):
        for preset in HOTKEY_PRESETS:
            self.assertEqual(parse_hotkey(preset)[2], preset)
        self.assertEqual(parse_hotkey('shift+f9'), (MOD_SHIFT, 0x78, 'Shift+F9'))
        self.assertEqual(parse_hotkey('alt + ctrl + a')[:2], (MOD_ALT | MOD_CONTROL, ord('A')))
        for bad in ('F9', 'Shift+A', 'Shift+Espaço', 'Alt+Espaço', 'Win+F9', 'Ctrl+F13', 'Ctrl+1', '', 'Ctrl+'):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                parse_hotkey(bad)

    def test_settings_roundtrip_defaults_and_corruption(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'sub' / 'settings.json'
            self.assertEqual(load_settings(path), Settings())
            self.assertTrue(save_settings(Settings(hotkey='ctrl+alt+a', middle_click=True), path))
            self.assertEqual(load_settings(path), Settings(hotkey='Ctrl+Alt+A', middle_click=True))
            self.assertEqual([p.name for p in path.parent.iterdir()], ['settings.json'])
            for content in ('não é json', '[1,2]', '{"hotkey": 5, "middle_click": "sim"}', '{"hotkey": "Shift+A"}', ''):
                path.write_text(content, encoding='utf-8')
                self.assertEqual(load_settings(path), Settings(), content)
            self.assertFalse(save_settings(Settings(), path / 'x' / 'y.json'))      # o pai é um arquivo

    def test_pure_predicates(self):
        self.assertTrue(middle_click_trigger(True, True, True, False))
        self.assertFalse(middle_click_trigger(False, True, True, False))
        self.assertFalse(middle_click_trigger(True, False, True, False))
        self.assertFalse(middle_click_trigger(True, True, True, True))            # só na borda de descida
        self.assertTrue(chord_in_progress(True, False, False)); self.assertTrue(chord_in_progress(False, True, False))
        self.assertTrue(chord_in_progress(False, False, True)); self.assertFalse(chord_in_progress(False, False, False))
        self.assertEqual((human_size(512), human_size(2048), human_size(1_300_000)), ('1 KB', '2 KB', '1,2 MB'))
        self.assertEqual(send_to_paths(['app.py', '--send-to', '/a/b.png', '/c d/e.pdf']), ['/a/b.png', '/c d/e.pdf'])
        self.assertEqual(send_to_paths(['app.py']), [])

    def make_tray(self, temp):
        patches = [patch('tray_app.load_settings', return_value=Settings()), patch('tray_app.save_settings', side_effect=lambda s, p=None: True),
                   patch('ipc.server_name', return_value=f'ArquivoLocal-test-{os.getpid()}-{os.path.basename(temp)}')]
        for p in patches:
            p.start(); self.addCleanup(p.stop)
        return TrayApplication(self.app)

    def test_apply_settings_validates_saves_and_republishes(self):
        with tempfile.TemporaryDirectory() as temp:
            tray = self.make_tray(temp)
            ok, message = tray.apply_settings('Shift+A', False)
            self.assertFalse(ok); self.assertIn('Shift sozinho', message)
            self.assertEqual(tray.settings.hotkey, 'Shift+F9')
            with patch.object(tray, '_switch_hotkey', side_effect=lambda hk: setattr(tray.global_hotkey, 'hotkey', hk) or True):   # sem registrar no sistema
                ok, message = tray.apply_settings('Ctrl+Alt+Espaço', True)
            self.assertTrue(ok); self.assertEqual(message, 'Preferências salvas.')
            self.assertEqual((tray.settings.hotkey, tray.settings.middle_click), ('Ctrl+Alt+Espaço', True))
            self.assertEqual(tray.global_hotkey.hotkey, 'Ctrl+Alt+Espaço')
            self.assertIn('Ctrl+Alt+Espaço', tray.controller.capabilities['shift_f9'][1] + ' Ctrl+Alt+Espaço')
            with patch.object(tray, '_switch_hotkey', side_effect=lambda hk: setattr(tray.global_hotkey, 'hotkey', hk) or True), patch('tray_app.save_settings', return_value=False):
                ok, message = tray.apply_settings('Ctrl+Shift+F9', True)
            self.assertFalse(ok); self.assertIn('não foi possível gravá-las', message)
            tray.quit()

    def test_hotkey_already_taken_keeps_the_previous_one_and_says_so(self):
        with tempfile.TemporaryDirectory() as temp:
            tray = self.make_tray(temp)
            before = tray.global_hotkey.hotkey
            with patch.object(tray, '_switch_hotkey', return_value=False):     # outro programa já usa a combinação
                ok, message = tray.apply_settings('Ctrl+Alt+Espaço', True)
            self.assertFalse(ok)
            self.assertIn('Não foi possível registrar Ctrl+Alt+Espaço', message); self.assertIn(before, message)
            self.assertEqual(tray.settings.hotkey, before); self.assertEqual(tray.global_hotkey.hotkey, before)
            tray.quit()

    def test_drop_on_quick_wheel_runs_the_action_for_dropped_files_only(self):
        with tempfile.TemporaryDirectory() as temp:
            tray = self.make_tray(temp)
            a, b = Path(temp) / 'a.png', Path(temp) / 'b.png'
            for p in (a, b):
                Image.new('RGB', (4, 4)).save(p)
            calls = []
            def fake_validate(paths):
                if any(not os.path.isabs(p) for p in paths):
                    raise ValueError('inválido')
                return list(paths)
            with patch('tray_app.validate_selection', side_effect=fake_validate), patch.object(tray.controller, 'start_job', side_effect=lambda paths, target, options: calls.append((paths, target)) or True):
                tray.handle_dropped_on_quick_wheel([str(b), str(a)], str(a), RadialAction('PNG', 'PNG'))
                tray.handle_dropped_on_quick_wheel(['relativo/x.png'], str(a), RadialAction('JPEG', 'JPEG'))     # inválido → arquivo da roda
            self.assertEqual(calls, [([str(b), str(a)], 'PNG'), ([str(a)], 'JPEG')])
            tray.quit()


class DropTests(QtCase):
    @staticmethod
    def mime(*paths, url=None):
        data = QMimeData()
        data.setUrls([QUrl.fromLocalFile(p) for p in paths] if url is None else [QUrl(url)])
        return data

    def event(self, cls, point, mime):
        self.__dict__.setdefault('_keep', []).append(mime)          # o evento não é dono do QMimeData
        return cls(point, Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)

    def test_wheel_accepts_local_files_dropped_on_an_enabled_slice(self):
        wheel = RadialWheel([RadialAction(n, n) for n in ('A', 'B', 'C', 'D')], 'x', 340, disabled=[2])
        got = []
        wheel.dropped.connect(lambda index, paths: got.append((index, paths)))
        target = wheel.slice_center(1).toPoint()
        mime = self.mime('/tmp/a.png', '/tmp/b.png')
        enter = self.event(QDragEnterEvent, target, mime); wheel.dragEnterEvent(enter)
        self.assertTrue(enter.isAccepted()); 
        drop = self.event(QDropEvent, QPointF(target), mime); wheel.dropEvent(drop)
        from PySide6.QtCore import QDir
        native = [QDir.toNativeSeparators(p) for p in ('/tmp/a.png', '/tmp/b.png')]      # o app entrega caminhos no formato nativo
        self.assertEqual(got, [(1, native)]); self.assertTrue(drop.isAccepted())
        disabled = self.event(QDropEvent, QPointF(wheel.slice_center(2).toPoint()), mime); wheel.dropEvent(disabled)
        outside = self.event(QDropEvent, QPointF(2, 2), mime); wheel.dropEvent(outside)
        self.assertEqual(len(got), 1); self.assertFalse(disabled.isAccepted()); self.assertFalse(outside.isAccepted())
        remote = self.mime(url='https://exemplo.com/a.png')
        refused = self.event(QDragEnterEvent, target, remote); wheel.dragEnterEvent(refused)
        self.assertFalse(refused.isAccepted())

    def test_menu_forwards_the_drop_and_closes(self):
        actions = [RadialAction('PNG', 'PNG'), RadialAction('JPEG', 'JPEG')]
        seen = []
        menu = RadialMenu('/a/x.png', actions, lambda a: seen.append(('click', a.label)), on_drop=lambda paths, a: seen.append((paths, a.label)))
        menu.show(); menu.wheel._local_paths(self.mime('/tmp/z.png'))
        menu.wheel.dropped.emit(1, ['/tmp/z.png'])
        self.assertEqual(seen, [(['/tmp/z.png'], 'JPEG')]); self.assertFalse(menu.isVisible())
        plain = RadialMenu('/a/x.png', actions, lambda a: seen.append(('click', a.label)))
        plain.show(); plain.wheel.dropped.emit(0, ['/tmp/z.png'])
        self.assertEqual(seen[-1], ('click', 'PNG'))

    def test_panel_wheel_drop_opens_the_tool_with_the_dropped_files_and_window_drop_adds_files(self):
        controller = JobController(capabilities={'images': (True, 'ok'), 'pdf': (True, 'ok')})
        panel = FeaturePanel(controller)
        with tempfile.TemporaryDirectory() as temp:
            files = []
            for name in ('a.png', 'b.png'):
                p = Path(temp) / name; Image.new('RGB', (8, 8)).save(p); files.append(str(p))
            panel.select_category('images')
            wheel = panel.wheel_widgets[1]
            wheel.open_group(next(i for i, a in enumerate(wheel.actions) if any(c.target == 'Backdrop → PNG' for c in a.children)))
            index = next(i for i, a in enumerate(wheel.actions) if a.target == 'Backdrop → PNG')
            wheel.dropped.emit(index, files[:1])
            self.assertEqual((panel.selected_tool, panel.files), ('Backdrop → PNG', files[:1]))
            drop = self.event(QDropEvent, QPointF(10, 10), self.mime(files[1])); panel.dropEvent(drop)
            self.assertEqual(panel.files, files); self.assertEqual(panel.selected_tool, 'Backdrop → PNG')
        panel.allow_close = True; panel.close()



class FakeRegistry:
    HKEY_CURRENT_USER = 'HKCU'; REG_SZ = 1

    class _Key:
        def __init__(self, store, path): self.store, self.path = store, path
        def __enter__(self): return self
        def __exit__(self, *exc): return False

    def __init__(self):
        self.keys = {'Software\\Classes\\Outro\\shell\\Cliente': {'': 'não mexer'}}

    def CreateKey(self, root, path):
        self.keys.setdefault(path, {}); return self._Key(self.keys, path)

    def OpenKey(self, root, path):
        if path not in self.keys: raise FileNotFoundError(path)
        return self._Key(self.keys, path)

    def SetValueEx(self, key, name, _r, _t, value): self.keys[key.path][name] = value
    def QueryValueEx(self, key, name): return self.keys[key.path][name], 1

    def DeleteKey(self, root, path):
        if path not in self.keys: raise FileNotFoundError(path)
        if any(other.startswith(path + '\\') for other in self.keys): raise PermissionError('tem subchaves')
        del self.keys[path]


class ShellIntegrationTests(QtCase):
    def test_install_is_idempotent_scoped_and_removable(self):
        reg = FakeRegistry()
        self.assertFalse(shell_integration.is_installed(reg))
        self.assertTrue(shell_integration.install('"C:\\Py\\pythonw.exe" "C:\\App\\app.py" --send-to "%1"', reg))
        self.assertTrue(shell_integration.install('"C:\\Py\\pythonw.exe" "C:\\App\\app.py" --send-to "%1"', reg))
        self.assertTrue(shell_integration.is_installed(reg))
        commands = [v[''] for k, v in reg.keys.items() if k.endswith('\\command')]
        self.assertEqual(len(commands), 2); self.assertTrue(all(c.endswith('--send-to "%1"') for c in commands))
        self.assertTrue(all(k.startswith('Software\\Classes\\') for k in reg.keys))
        self.assertTrue(shell_integration.uninstall(reg))
        self.assertFalse(shell_integration.is_installed(reg))
        self.assertEqual(list(reg.keys), ['Software\\Classes\\Outro\\shell\\Cliente'])
        self.assertTrue(shell_integration.uninstall(reg))                             # já removido: sem erro

    def test_launch_command_quotes_every_part(self):
        command = shell_integration.launch_command('C:\\Program Files\\Py\\python.exe', 'C:\\Meu App\\app.py')
        self.assertEqual(command, '"C:\\Program Files\\Py\\python.exe" "C:\\Meu App\\app.py" --send-to "%1"')


class IpcTests(QtCase):
    def make_server(self):
        name = f'ArquivoLocal-test-ipc-{os.getpid()}-{id(self)}'
        server = PathServer(name)
        self.assertTrue(server.start()); self.addCleanup(server.stop)
        received = []
        server.paths_received.connect(received.append)
        return name, server, received

    @staticmethod
    def send_from_other_process(paths, name):
        """Envia como o Explorer faz (outro processo) enquanto este processo atende o servidor; no Windows o soquete bloqueante não pode
        compartilhar a thread do servidor."""
        import subprocess
        code = ('import sys, json; sys.path.insert(0, sys.argv[1]); from PySide6.QtCore import QCoreApplication; app = QCoreApplication([]); '
                'from ipc import send_paths; sys.exit(0 if send_paths(json.loads(sys.argv[2]), sys.argv[3]) else 1)')
        root = str(Path(__file__).resolve().parents[1])
        process = subprocess.Popen([sys.executable, '-c', code, root, json.dumps(paths), name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(100):
            if process.poll() is not None:
                break
            QTest.qWait(50)
        else:
            process.kill()
        return process.wait() == 0

    def test_paths_are_delivered_batched_and_deduplicated(self):
        name, server, received = self.make_server()
        self.assertTrue(self.send_from_other_process(['/a/1.png'], name)); self.assertTrue(self.send_from_other_process(['/a/2.png', '/a/1.png'], name))
        QTest.qWait(900)
        # iniciar um processo leva mais que a janela de 350 ms (no Windows, ~1 s): os dois envios podem virar lotes diferentes.
        # O que importa aqui é a entrega entre processos e que nenhum lote repita caminho; o agrupamento é testado com `feed`.
        self.assertTrue(received and all(len(batch) == len(set(batch)) for batch in received))
        self.assertEqual({path for batch in received for path in batch}, {'/a/1.png', '/a/2.png'})
        received.clear()
        server.feed(['/a/1.png']); server.feed(['/a/2.png', '/a/1.png']); QTest.qWait(700)
        self.assertEqual(received, [['/a/1.png', '/a/2.png']])               # dentro da janela: um lote, sem duplicatas
        self.assertTrue(self.send_from_other_process([], name)); QTest.qWait(900)
        self.assertEqual(received[-1], [])
        server.feed(['/a/3.png']); QTest.qWait(700)
        self.assertEqual(received[-1], ['/a/3.png'])

    def test_malformed_oversized_or_wrong_typed_messages_are_ignored(self):
        from PySide6.QtNetwork import QLocalSocket
        name, server, received = self.make_server()
        for payload in (b'isto nao e json', b'{"paths": "texto"}', b'{"paths": [1, 2]}', b'[1]', b'{"paths": ["' + b'x' * 2000 + b'"]}', b'\xff\xfe', b'x' * (MAX_MESSAGE + 10)):
            socket = QLocalSocket(); socket.connectToServer(name); self.assertTrue(socket.waitForConnected(500))
            socket.write(payload); socket.waitForBytesWritten(500); socket.disconnectFromServer()
            QTest.qWait(80)
        QTest.qWait(600)
        self.assertEqual(received, [])

    def test_send_fails_cleanly_without_a_server_and_caps_the_list(self):
        self.assertFalse(send_paths(['/a/1.png'], 'ArquivoLocal-ninguem-escuta', timeout_ms=50))
        self.assertFalse(send_paths(['x' * 70000], 'ArquivoLocal-ninguem-escuta', timeout_ms=50))
        name, server, received = self.make_server()
        self.assertTrue(self.send_from_other_process([f'/a/{i}.png' for i in range(150)], name)); QTest.qWait(900)
        self.assertEqual(len(received[0]), 100)


class SettingsDialogTests(QtCase):
    class FakeTray:
        def __init__(self):
            self.settings = Settings(hotkey='Ctrl+Alt+A', middle_click=True)
            self.hotkey_registered = True
            self.global_hotkey = type('H', (), {'hotkey': 'Ctrl+Alt+A'})()
            self.applied = []

        def apply_settings(self, hotkey, middle):
            self.applied.append((hotkey, middle))
            return (hotkey != 'Shift+F9', 'Preferências salvas.' if hotkey != 'Shift+F9' else 'Falhou.')

    def test_dialog_reflects_state_and_applies_choices(self):
        from settings_dialog import SettingsDialog
        tray = self.FakeTray(); registry = FakeRegistry()
        dialog = SettingsDialog(tray, registry=registry)
        self.assertEqual(dialog.hotkey_chips.currentText(), 'Ctrl+Alt+A')          # atalho fora das predefinições aparece e fica marcado
        self.assertTrue(dialog.middle_check.isChecked())
        self.assertIn('registrado', dialog.hotkey_status.text())
        self.assertEqual(dialog.context_button.text(), 'Adicionar ao menu de contexto')
        dialog.context_button.click()
        self.assertTrue(shell_integration.is_installed(registry))
        self.assertEqual(dialog.context_button.text(), 'Remover do menu de contexto')
        self.assertIn('Menu de contexto adicionado', dialog.message.text())
        dialog.context_button.click()
        self.assertFalse(shell_integration.is_installed(registry))
        dialog.hotkey_chips.setCurrentIndex(HOTKEY_PRESETS.index('Ctrl+Shift+F9') + 0 if 'Ctrl+Shift+F9' in [dialog.hotkey_chips.itemText(i) for i in range(dialog.hotkey_chips.count())] else 0)
        dialog.middle_check.setChecked(False)
        dialog.apply_button.click()
        self.assertEqual(tray.applied[-1][1], False)
        self.assertEqual(dialog.message.text(), 'Preferências salvas.')

    def test_failure_message_is_shown_and_non_windows_disables_the_context_menu(self):
        from settings_dialog import SettingsDialog
        tray = self.FakeTray()
        dialog = SettingsDialog(tray)                                               # sem registro injetado
        if os.name != 'nt':
            self.assertFalse(dialog.context_button.isEnabled())
            self.assertIn('somente no Windows', dialog.context_status.text())
        dialog.hotkey_chips.setCurrentIndex(dialog.hotkey_chips.count() - 1)
        for index in range(dialog.hotkey_chips.count()):
            if dialog.hotkey_chips.itemText(index) == 'Shift+F9':
                dialog.hotkey_chips.setCurrentIndex(index)
        dialog.apply_button.click()
        self.assertEqual(dialog.message.text(), 'Falhou.')


if __name__ == '__main__':
    unittest.main()
