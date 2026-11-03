import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from radial_menu import RadialAction, RadialMenu, actions_for_file, actions_for_selection, flatten_actions, should_dismiss_radial
from capabilities import describe_capabilities, probe_capabilities
from tray_app import FeaturePanel, JobController, TrayApplication
from windows_bridge import _desktop_dispatch, _selection_paths, is_desktop_root_class, normalize_shell_paths
from global_hotkey import HOTKEY_ID, WM_HOTKEY, is_hotkey_message
from file_actions import format_path_lines, normalize_local_paths
from unittest.mock import patch
from instance_guard import acquire_app_lock
from shelf import FileShelf, MAX_SHELF_ITEMS, reference_mime_data
from visual_tools import CropEditor
from PIL import Image


class RadialUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_image_menu_contains_quick_conversions_and_panel(self):
        actions = actions_for_file(r'C:\Users\Test\photo.png')
        targets = [action.target for action in actions]
        self.assertIn('JPEG', targets)
        self.assertIn('Image → PDF', targets)
        self.assertIn('__panel__', targets)

    def test_pdf_menu_exposes_text_split_and_merge_panel(self):
        actions = actions_for_file(r'C:\Users\Test\report.pdf')
        targets = [action.target for action in actions]
        self.assertEqual(targets, ['PDF → Text', 'PDF → Images', 'Split PDF', '__panel_merge__', '__panel__'])

    def test_global_radial_exposes_only_nondestructive_windows_actions(self):
        actions = actions_for_selection([r'C:\Users\Test\photo.png'])
        targets=[a.target for a in actions]
        self.assertEqual(targets[:5], ['__group_transform__','__group_look__','__group_draw__','__group_protect__','__group_read__'])
        self.assertEqual(targets[5:], ['__copy_group__','__shelf_add__','__open_terminal__'])
        self.assertEqual([a.target for a in actions[5].children], ['__copy_paths__','__copy_files__'])
        self.assertEqual([a.target for a in flatten_actions(actions)][:12], ['__tool_crop__','__tool_resize__','__tool_rotate__','__tool_canvas__','__tool_compress__','__tool_adjust__','__tool_levels__','__tool_sharpen__','__tool_backdrop__','__tool_removebg__','__tool_annotate__','__tool_shapes__'])
        multiple = actions_for_selection([r'C:\Users\Test\one.png', r'C:\Users\Test\two.png'])
        self.assertEqual([a.target for a in flatten_actions(multiple)], ['__tool_collage__', '__tool_onepdf__', '__copy_paths__', '__copy_files__', '__shelf_add__'])
        mixed = actions_for_selection([r'C:\Users\Test\one.png', r'C:\Users\Test\doc.pdf'])
        self.assertEqual([a.target for a in flatten_actions(mixed)], ['__copy_paths__', '__copy_files__', '__shelf_add__'])

    def test_secondary_radial_is_contextual_for_pdf(self):
        targets=[a.target for a in flatten_actions(actions_for_selection([r'C:\Users\Test\report.pdf']))]
        self.assertEqual(targets[:4],['PDF → Text','PDF → Images','Split PDF','__panel_merge__'])
        self.assertIn('__copy_paths__',targets)

    def test_radial_gates_operations_when_local_backend_is_missing(self):
        unavailable = {'images': (False, 'Pillow ausente.'), 'pdf': (False, 'pypdf ausente.'), 'terminal': (False, 'PowerShell não localizado.')}
        self.assertEqual([a.target for a in actions_for_file(r'C:\Users\Test\photo.png', unavailable)], ['__capability_images__', '__panel__'])
        self.assertEqual([a.target for a in actions_for_file(r'C:\Users\Test\report.pdf', unavailable)], ['__capability_pdf__', '__panel__'])
        targets = [a.target for a in actions_for_selection([r'C:\Users\Test\photo.png'], unavailable)]
        self.assertIn('__capability_terminal__', targets)
        self.assertNotIn('__open_terminal__', targets)

    def test_capability_probe_is_local_and_returns_explainable_states(self):
        capabilities = probe_capabilities()
        self.assertTrue({'images', 'pdf', 'desktop_selection', 'terminal', 'clipboard', 'shelf', 'shift_f9'} <= set(capabilities))
        self.assertTrue(all(isinstance(value, tuple) and len(value) == 2 and isinstance(value[0], bool) for value in capabilities.values()))
        self.assertIn('Imagens:', describe_capabilities(capabilities))

    def test_controller_refuses_jobs_when_backend_is_unavailable(self):
        controller = JobController(capabilities={'images': (False, 'Pillow ausente.'), 'pdf': (True, 'pypdf carregado.')})
        self.assertFalse(controller.start_job([r'C:\Test\photo.png'], 'JPEG'))
        self.assertFalse(controller.start_job([r'C:\Test\photo.png'], 'Crop → PNG'))
        self.assertEqual(len(controller.pending_jobs), 0)

    def test_image_core_panel_enables_matching_controls(self):
        controller = JobController(capabilities={'images': (True, 'Pillow carregado.'), 'pdf': (True, 'pypdf carregado.')})
        panel = FeaturePanel(controller)
        panel.operation.setCurrentIndex(panel.operation.findData('Crop → PNG'))
        self.assertTrue(panel.crop_x.isEnabled())
        self.assertFalse(panel.canvas_width.isEnabled())
        panel.operation.setCurrentIndex(panel.operation.findData('Canvas → PNG'))
        self.assertTrue(panel.canvas_width.isEnabled())
        self.assertFalse(panel.annotation.isEnabled())
        panel.operation.setCurrentIndex(panel.operation.findData('Annotate → PNG'))
        self.assertTrue(panel.annotation.isEnabled())
        panel.operation.setCurrentIndex(panel.operation.findData('Compress → JPEG'))
        self.assertTrue(panel.quality.isEnabled())
        panel.allow_close = True
        panel.close()

    def test_panel_disables_features_with_missing_backend(self):
        controller = JobController(capabilities={'images': (False, 'Pillow ausente.'), 'pdf': (False, 'pypdf ausente.')})
        panel = FeaturePanel(controller)
        enabled = Qt.ItemFlag.ItemIsEnabled
        self.assertFalse(panel.image_list.item(0).flags() & enabled)
        self.assertFalse(panel.pdf_list.item(0).flags() & enabled)
        self.assertIn('Pillow ausente', panel.image_list.item(0).toolTip())
        panel.allow_close = True
        panel.close()

    def test_panel_starts_with_category_chooser_and_future_categories_are_informational(self):
        controller=JobController(capabilities={'images':(True,'Pillow carregado.'),'pdf':(True,'pypdf carregado.')})
        panel=FeaturePanel(controller)
        self.assertIs(panel.pages.currentWidget(),panel.home_page)
        self.assertEqual(len(panel.category_buttons),10)
        panel.select_category('video')
        self.assertIs(panel.pages.currentWidget(),panel.category_page)
        self.assertIn('ainda não executa',panel.category_help.text())
        self.assertTrue(all(not panel.tool_grid.itemAt(i).widget().isEnabled() for i in range(panel.tool_grid.count())))
        panel.set_files(['/tmp/sample.mp4'])
        self.assertEqual(panel.active_category,'video')
        self.assertIsNone(panel.selected_tool)
        panel.allow_close=True; panel.close()

    def test_crop_editor_drag_returns_source_image_coordinates(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path=Path(temp_dir)/'source.png'
            source=Image.new('RGB',(240,160))
            for y in range(160):
                for x in range(240): source.putpixel((x,y),(x%256,y%256,(x+y)%256))
            source.save(path); source.close()
            original_bytes=path.read_bytes()
            editor=CropEditor(str(path))
            editor.show(); self.app.processEvents()
            start=editor.view.mapFromScene(20,20)
            end=editor.view.mapFromScene(180,120)
            QTest.mousePress(editor.view.viewport(),Qt.MouseButton.LeftButton,pos=start)
            QTest.mouseMove(editor.view.viewport(),end,delay=20)
            QTest.mouseRelease(editor.view.viewport(),Qt.MouseButton.LeftButton,pos=end)
            self.app.processEvents()
            self.assertTrue(editor.apply_button.isEnabled())
            editor.accept_crop()
            self.assertIsNotNone(editor.coordinates)
            x,y,width,height=editor.coordinates
            self.assertAlmostEqual(x,20,delta=2); self.assertAlmostEqual(y,20,delta=2)
            self.assertAlmostEqual(width,160,delta=3); self.assertAlmostEqual(height,100,delta=3)
            from engine import convert
            outputs=convert({'paths':[str(path)],'target':'Crop → PNG','crop_x':x,'crop_y':y,'crop_width':width,'crop_height':height})
            with Image.open(outputs[0]) as cropped:
                self.assertEqual(cropped.size,(width,height))
                self.assertEqual(cropped.getpixel((0,0)),(x%256,y%256,(x+y)%256))
            self.assertEqual(path.read_bytes(),original_bytes)
            editor.close()

    def test_crop_workspace_embeds_preview_and_drag_populates_controls(self):
        panel=FeaturePanel(JobController(capabilities={'images':(True,'ok'),'pdf':(True,'ok')}))
        with tempfile.TemporaryDirectory() as temp_dir:
            path=Path(temp_dir)/'workspace.png'
            Image.new('RGB',(240,160),'#6284a1').save(path)
            panel.set_files([str(path)],'Crop → PNG')
            panel.resize(760,560); panel.show(); self.app.processEvents()
            self.assertTrue(panel.crop_preview.isVisible())
            self.assertFalse(panel.preview_image.isVisible())
            start=panel.crop_preview.mapFromScene(20,20)
            end=panel.crop_preview.mapFromScene(180,120)
            QTest.mousePress(panel.crop_preview.viewport(),Qt.MouseButton.LeftButton,pos=start)
            QTest.mouseMove(panel.crop_preview.viewport(),end,delay=20)
            QTest.mouseRelease(panel.crop_preview.viewport(),Qt.MouseButton.LeftButton,pos=end)
            self.app.processEvents()
            self.assertEqual((panel.crop_x.value(),panel.crop_y.value()),(20,20))
            self.assertAlmostEqual(panel.crop_width.value(),160,delta=3)
            self.assertAlmostEqual(panel.crop_height.value(),100,delta=3)
            self.assertIn('×',panel.crop_help.text())
        panel.allow_close=True; panel.close()

    def test_shift_f9_message_filter_identifies_only_its_hotkey_id(self):
        self.assertTrue(is_hotkey_message(WM_HOTKEY, HOTKEY_ID))
        self.assertFalse(is_hotkey_message(WM_HOTKEY, HOTKEY_ID + 1))
        self.assertFalse(is_hotkey_message(WM_HOTKEY + 1, HOTKEY_ID))

    def test_local_path_normalization_and_copy_path_format(self):
        paths = normalize_local_paths([
            r'C:\Users\Test\image one.png',
            r'c:\users\test\IMAGE ONE.PNG',
            r'\\server\share\remote.png',
            r'folder\relative.png',
            r'C:\Users\Test\image.png:alternate',
            '::{virtual}',
        ])
        self.assertEqual(paths, [r'C:\Users\Test\image one.png'])
        self.assertEqual(format_path_lines(paths), r'C:\Users\Test\image one.png')

    def test_radial_click_on_slice_dispatches_selected_action(self):
        actions = actions_for_file(r'C:\Users\Test\photo.png')
        selected = []
        menu = RadialMenu(r'C:\Users\Test\photo.png', actions, selected.append)
        menu.show(); self.app.processEvents()
        QTest.mouseClick(menu.wheel, Qt.MouseButton.LeftButton, pos=menu.wheel.slice_center(0).toPoint())
        self.app.processEvents()
        self.assertEqual(selected[0].target, 'JPEG')
        self.assertFalse(menu.isVisible())

    def test_secondary_radial_hover_displays_tool_name_in_center(self):
        menu=RadialMenu('photo.png',actions_for_selection([r'C:\Users\Test\photo.png']),lambda action:None)
        menu.show(); self.app.processEvents()
        QTest.mouseMove(menu.wheel,menu.wheel.slice_center(0).toPoint(),delay=10)
        self.app.processEvents()
        self.assertEqual(menu.wheel.hover_index,0)
        self.assertEqual(menu.center_text,'Transformar')
        QTest.mouseMove(menu.wheel,menu.wheel.rect().center(),delay=10)
        self.app.processEvents()
        self.assertEqual(menu.wheel.hover_index,-1)
        self.assertEqual(menu.center_text,'photo.png')
        menu.close()

    def test_radial_escape_key_closes_menu(self):
        menu = RadialMenu('photo.png', actions_for_file(r'C:\Users\Test\photo.png'), lambda action: None)
        menu.show()
        self.app.processEvents()
        event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(menu, event)
        self.app.processEvents()
        self.assertFalse(menu.isVisible())

    def test_outside_dismiss_predicate(self):
        self.assertTrue(should_dismiss_radial(False, True, False))
        self.assertTrue(should_dismiss_radial(True, False, True))
        self.assertFalse(should_dismiss_radial(False, False, False))
        self.assertFalse(should_dismiss_radial(True, True, False))

    def test_global_radial_replaces_quick_menu_and_ignores_duplicate_open(self):
        controller = TrayApplication(self.app)
        controller.poller.stop()
        path = r'C:\Users\Test\photo.png'
        controller.open_radial(path)
        quick = controller.radial
        with patch('tray_app.selected_paths_from_explorer', side_effect=AssertionError('não deve perder foco e reler a seleção')), \
             patch('tray_app.validate_selection', side_effect=lambda items: items):
            controller.open_global_radial()
            global_menu = controller.radial
            self.assertIsNot(global_menu, quick)
            self.assertFalse(quick.isVisible())
            self.assertEqual(controller.radial_mode, 'global')
            controller.open_global_radial()
            self.assertIs(controller.radial, global_menu)
        global_menu.close()
        controller.global_hotkey.stop()
        controller.panel.allow_close = True
        controller.panel.close()

    def test_single_instance_lock_rejects_second_copy_and_releases(self):
        with tempfile.TemporaryDirectory() as temp:
            path = str(Path(temp) / 'instance.lock')
            first = acquire_app_lock(path)
            self.assertIsNotNone(first)
            self.assertIsNone(acquire_app_lock(path))
            first.unlock()
            second = acquire_app_lock(path)
            self.assertIsNotNone(second)
            second.unlock()

    def test_shelf_add_deduplicates_remove_and_clear_without_touching_files(self):
        shelf = FileShelf(path_validator=lambda paths: paths)
        paths = [r'C:\Users\Test\one.png', r'C:\Users\Test\two file.pdf']
        self.assertEqual(shelf.add_paths(paths), 2)
        self.assertEqual(shelf.add_paths([r'c:\users\test\ONE.PNG']), 0)
        self.assertEqual(shelf.paths(), paths)
        self.assertEqual(shelf.items.item(1).text(), 'two file.pdf')
        shelf.items.item(0).setSelected(True)
        shelf.remove_selected()
        self.assertEqual(shelf.paths(), [paths[1]])
        shelf.clear_items()
        self.assertEqual(shelf.paths(), [])
        self.assertIn('Nenhum arquivo', shelf.status.text())
        shelf.close()

    def test_shelf_drag_mime_contains_file_urls_not_file_contents(self):
        with tempfile.TemporaryDirectory() as temp:
            path = str(Path(temp) / 'arquivo com espaço.txt')
            Path(path).write_text('conteúdo local', encoding='utf-8')
            mime = reference_mime_data([path], validator=lambda paths: paths)
            from PySide6.QtCore import QDir
            self.assertEqual([QDir.toNativeSeparators(url.toLocalFile()) for url in mime.urls()], [QDir.toNativeSeparators(path)])      # Qt usa '/' em toLocalFile
            self.assertFalse(mime.hasFormat('application/octet-stream'))

    def test_shelf_has_bounded_item_count(self):
        shelf = FileShelf(path_validator=lambda paths: paths)
        candidates = [fr'C:\Users\Test\{index}.png' for index in range(MAX_SHELF_ITEMS + 5)]
        self.assertEqual(shelf.add_paths(candidates), MAX_SHELF_ITEMS)
        self.assertEqual(shelf.items.count(), MAX_SHELF_ITEMS)
        self.assertIn(str(MAX_SHELF_ITEMS), shelf.status.text())
        shelf.close()

    def test_job_controller_queues_sequentially_and_cancels_only_active(self):
        class FakeTask(QObject):
            completed = Signal(bool, str, list)
            finished = Signal()

            def __init__(self, paths, target, options):
                super().__init__()
                self.paths, self.target, self.options = paths, target, options
                self.cancelled = False
                self.running = False

            def start(self):
                self.running = True

            def isRunning(self):
                return self.running

            def request_cancel(self):
                self.cancelled = True

            def complete(self, outputs):
                self.completed.emit(True, 'Concluído', outputs)
                self.running = False
                self.finished.emit()

        controller = JobController()
        created = []
        def factory(paths, target, options):
            task = FakeTask(paths, target, options)
            created.append(task)
            return task
        with patch('tray_app.ConversionTask', side_effect=factory):
            self.assertTrue(controller.start_job([r'C:\Test\one.png'], 'JPEG'))
            self.assertTrue(controller.start_job([r'C:\Test\two.png', r'C:\Test\three.png'], 'PNG'))
            self.assertEqual(len(created), 1)
            self.assertEqual(len(controller.pending_jobs), 2)
            self.assertTrue(controller.cancel_current())
            self.assertTrue(created[0].cancelled)
            created[0].complete([])
            self.app.processEvents()
            self.assertEqual(controller.active_job['paths'], [r'C:\Test\two.png'])
            self.assertEqual(len(created), 2)
            self.assertEqual(controller.clear_pending(), 1)
            created[1].complete([])
            self.app.processEvents()
            self.assertIsNone(controller.active_job)

    def test_queue_panel_shows_busy_state_and_keeps_enqueue_enabled(self):
        controller = JobController()
        panel = FeaturePanel(controller)
        controller.active_job = {'paths': [r'C:\Test\active.png'], 'target': 'JPEG', 'options': {}}
        controller.worker = object()
        controller.pending_jobs.append({'paths': [r'C:\Test\waiting.pdf'], 'target': 'PDF → Text', 'options': {}})
        panel.refresh_queue()
        self.assertEqual(panel.progress.maximum(), 0)
        self.assertEqual(panel.queue_view.count(), 1)
        self.assertTrue(panel.cancel_button.isEnabled())
        self.assertTrue(panel.run_button.isEnabled())
        panel.allow_close = True
        panel.close()

    def test_panel_routes_selected_file_to_category_without_forcing_operation(self):
        panel = FeaturePanel(JobController())
        panel.set_files([r'C:\Users\Test\report.pdf'])
        self.assertEqual(panel.active_category,'pdf')
        self.assertIs(panel.pages.currentWidget(),panel.category_page)
        self.assertIsNone(panel.selected_tool)
        panel.set_files([r'C:\Users\Test\photo.jpg'])
        self.assertEqual(panel.active_category,'images')
        self.assertIs(panel.pages.currentWidget(),panel.category_page)
        self.assertIsNone(panel.selected_tool)
        panel.allow_close = True
        panel.close()

    def test_shell_paths_reject_unc_and_deduplicate(self):
        paths = normalize_shell_paths([
            r'C:\Users\Test\Photo.png',
            r'c:\users\test\photo.PNG',
            r'\\server\share\secret.pdf',
            '',
            'virtual:Recent',
        ])
        self.assertEqual(paths, [r'C:\Users\Test\Photo.png'])

    def test_desktop_shell_root_classification(self):
        self.assertTrue(is_desktop_root_class('Progman'))
        self.assertTrue(is_desktop_root_class('WorkerW'))
        self.assertFalse(is_desktop_root_class('CabinetWClass'))

    def test_desktop_dispatch_uses_shellwindows_find_window(self):
        class PythonCom:
            VT_I4 = 3
            VT_EMPTY = 0

        class Win32Client:
            @staticmethod
            def VARIANT(kind, value):
                return ('variant', kind, value)

        class DesktopView:
            Document = object()

        class ShellWindows:
            def __init__(self):
                self.args = None
                self.dispatch = DesktopView()

            def FindWindowSW(self, *args):
                self.args = args
                return self.dispatch

        windows = ShellWindows()
        self.assertIs(_desktop_dispatch(windows, PythonCom, Win32Client), windows.dispatch)
        self.assertEqual(windows.args, (('variant', 3, 0), ('variant', 0, None), 8, 0, 1))

    def test_desktop_selection_keeps_filesystem_paths_only(self):
        class Item:
            def __init__(self, path):
                self.Path = path

        class Document:
            def SelectedItems(self):
                return [Item(r'C:\Users\Test\Desktop\image.png'), Item(r'\\server\share\file.pdf'), Item('::{recycle-bin}')]

        window = type('Window', (), {'Document': Document()})()
        self.assertEqual(_selection_paths(window), [r'C:\Users\Test\Desktop\image.png'])



class WheelGeometryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_slice_index_follows_clockwise_order_from_top(self):
        from radial_menu import slice_index_at
        self.assertEqual(slice_index_at(0, -100, 4, 40, 150), 0)    # topo
        self.assertEqual(slice_index_at(100, 0, 4, 40, 150), 1)     # direita
        self.assertEqual(slice_index_at(0, 100, 4, 40, 150), 2)     # base
        self.assertEqual(slice_index_at(-100, 0, 4, 40, 150), 3)    # esquerda
        self.assertEqual(slice_index_at(0, -10, 4, 40, 150), -1)    # pílula central
        self.assertEqual(slice_index_at(0, -200, 4, 40, 150), -1)   # fora do anel

    def test_every_slice_center_hits_its_own_slice(self):
        from radial_menu import RadialWheel
        for count in range(1, 9):
            actions = [RadialAction(f'A{i}', f't{i}') for i in range(count)]
            wheel = RadialWheel(actions, 'x', 340)
            for index in range(count):
                self.assertEqual(wheel.slice_at(wheel.slice_center(index)), index, (count, index))

    def test_keyboard_navigation_activates_and_disabled_slices_do_not(self):
        from radial_menu import RadialWheel
        actions = [RadialAction('Um', 'a'), RadialAction('Dois', 'b'), RadialAction('Três', 'c')]
        wheel = RadialWheel(actions, 'x', 300, disabled={1})
        got = []
        wheel.activated.connect(got.append)
        wheel.show(); self.app.processEvents()
        QTest.keyClick(wheel, Qt.Key.Key_Right); QTest.keyClick(wheel, Qt.Key.Key_Return)
        self.assertEqual(wheel.hover_index, 0); self.assertEqual(got, [0])
        QTest.keyClick(wheel, Qt.Key.Key_Right); QTest.keyClick(wheel, Qt.Key.Key_Return)
        self.assertEqual(got, [0])                                   # fatia 1 está desabilitada
        QTest.keyClick(wheel, Qt.Key.Key_Right); QTest.keyClick(wheel, Qt.Key.Key_Return)
        self.assertEqual(got, [0, 2])
        wheel.close()


class CollageUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make_panel(self):
        controller = JobController(capabilities={'images': (True, 'Pillow carregado.'), 'pdf': (True, 'pypdf carregado.')})
        return controller, FeaturePanel(controller)

    def test_radial_offers_collage_only_for_two_to_twelve_images(self):
        def targets(paths):
            return [action.target for action in actions_for_selection(paths)]
        self.assertIn('__tool_collage__', targets(['/a/1.png', '/a/2.jpg']))
        self.assertIn('__tool_collage__', targets([f'/a/{i}.png' for i in range(12)]))
        self.assertNotIn('__tool_collage__', targets(['/a/1.png']))
        self.assertNotIn('__tool_collage__', targets([f'/a/{i}.png' for i in range(13)]))
        self.assertNotIn('__tool_collage__', targets(['/a/1.png', '/a/2.pdf']))
        self.assertNotIn('__tool_crop__', targets(['/a/1.png', '/a/2.jpg']))
        unavailable = [a.target for a in actions_for_selection(['/a/1.png', '/a/2.png'], {'images': (False, 'sem Pillow')})]
        self.assertNotIn('__tool_collage__', unavailable)

    def test_controller_validates_collage_selection_and_keeps_it_as_one_job(self):
        controller, panel = self.make_panel()
        class FakeTask(QObject):
            completed = Signal(bool, str, list)
            finished = Signal()

            def __init__(self, paths, target, options):
                super().__init__()
                self.paths, self.target, self.options = paths, target, options

            def start(self): pass
            def isRunning(self): return True
        with patch('tray_app.ConversionTask', side_effect=FakeTask), patch.object(controller, 'notify'):
            self.assertFalse(controller.start_job([r'C:\T\a.png'], 'Collage → PNG'))
            self.assertFalse(controller.start_job([rf'C:\T\{i}.png' for i in range(13)], 'Collage → PNG'))
            self.assertFalse(controller.start_job([r'C:\T\a.png', r'C:\T\b.png'], 'Collage → PNG', {'collage_cell': '600'}))
            self.assertTrue(controller.start_job([r'C:\T\a.png', r'C:\T\b.png', r'C:\T\c.png'], 'Collage → PNG', {'collage_cell': 400}))
            self.assertEqual(controller.active_job['paths'], [r'C:\T\a.png', r'C:\T\b.png', r'C:\T\c.png'])
            self.assertEqual(len(controller.pending_jobs), 0)
        panel.allow_close = True; panel.close()

    def test_panel_previews_layout_and_sends_options(self):
        from engine import collage_layout
        controller, panel = self.make_panel()
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = []
            for index in range(3):
                path = Path(temp_dir) / f'img{index}.png'
                Image.new('RGB', (30, 20), (index * 80, 0, 0)).save(path); paths.append(str(path))
            panel.set_files(paths[:1], 'Collage → PNG')
            self.assertEqual(panel.stage.currentIndex(), 0)                       # mensagem: falta imagem
            self.assertIn('duas ou mais', panel.preview_image.text())
            panel.set_files(paths, 'Collage → PNG')
            self.assertEqual(panel.selected_tool, 'Collage → PNG')
            visible = [k for k, w in panel.form_fields.items() if panel.settings_form.isRowVisible(w) and k not in ('nname', 'nexample', 'nstart', 'ndigits')]
            self.assertEqual(sorted(visible), ['background', 'cbuttons', 'ccell', 'ccols', 'cgap', 'clist', 'ofmt'])
            panel.collage_cell.setValue(100); panel.collage_gap.setValue(10); panel.collage_columns.setValue(2)
            self.assertEqual(collage_layout(3, 2, 100, 10)[0], (230, 230))
            self.assertIn('230 × 230', panel.tool_hint.text())
            pixmap = panel.static_preview.pixmap_item.pixmap()
            self.assertEqual((pixmap.width(), pixmap.height()), (230, 230))
            self.assertTrue(panel.run_button.isEnabled())
            panel.collage_cell.setValue(2000); panel.collage_gap.setValue(200); panel.collage_columns.setValue(6)
            panel.set_files(paths * 4, 'Collage → PNG')                              # duplicadas são unificadas: 3 imagens
            self.assertEqual(len(panel.files), 3)
            captured = {}
            with patch.object(controller, 'start_job', side_effect=lambda files, target, options: captured.update(files=files, target=target, options=options) or True):
                panel.collage_columns.setValue(2); panel.collage_cell.setValue(300); panel.collage_gap.setValue(5)
                panel.run_selected()
            self.assertEqual(captured['target'], 'Collage → PNG')
            self.assertEqual(captured['files'], paths)
            self.assertEqual((captured['options']['collage_columns'], captured['options']['collage_cell'], captured['options']['collage_gap']), (2, 300, 5))
        panel.allow_close = True; panel.close()

    def test_oversized_collage_disables_the_button_and_wheel_lists_the_tool(self):
        controller, panel = self.make_panel()
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = []
            for index in range(12):
                path = Path(temp_dir) / f'i{index}.png'; Image.new('RGB', (4, 4)).save(path); paths.append(str(path))
            panel.set_files(paths, 'Collage → PNG')
            panel.collage_cell.setValue(2000); panel.collage_gap.setValue(200); panel.collage_columns.setValue(6)
            self.assertFalse(panel.run_button.isEnabled())
            self.assertIn('grande demais', panel.tool_hint.text())
            panel.select_tool('PNG')
            self.assertTrue(panel.run_button.isEnabled())
        from workspace_panel import WHEEL_COLUMNS
        import tool_registry
        self.assertIn('Collage → PNG', tool_registry.flat_targets(WHEEL_COLUMNS['images'][1][2]))
        panel.allow_close = True; panel.close()

    def test_layout_pixmap_matches_engine_geometry(self):
        from visual_tools import collage_layout_pixmap
        pixmap = collage_layout_pixmap(['a.png', 'b.png', 'c.png', 'd.png', 'e.png'], 3, 100, 10, '#102030')
        self.assertEqual((pixmap.width(), pixmap.height()), (340, 230))
        image = pixmap.toImage()
        self.assertEqual(image.pixelColor(1, 1).name(), '#102030')
        big = collage_layout_pixmap(['a', 'b'], 2, 2000, 200, '#ffffff')
        self.assertEqual(max(big.width(), big.height()), 900)


class LossReportUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_panel_shows_report_after_job_and_hides_it_when_changing_tool(self):
        controller = JobController(capabilities={'images': (True, 'ok'), 'pdf': (True, 'ok')})
        panel = FeaturePanel(controller)
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / 'a.png'; Image.new('RGBA', (8, 8), (255, 0, 0, 0)).save(path)
            out = Path(temp_dir) / 'a-converted.jpg'; Image.new('RGB', (8, 8)).save(out)
            panel.set_files([str(path)], 'JPEG')
            controller.active_job = {'paths': [str(path)], 'target': 'JPEG', 'options': {'quality': 70}}
            controller._on_worker_result(True, 'Concluído', [str(out)])
            self.assertFalse(panel.report_card.isHidden())
            self.assertIn('qualidade 70', panel.report_label.text())
            self.assertIn('transparência', panel.report_label.text())
            self.assertIn('a.png', panel.report_title.text())
            self.assertIn('qualidade 70', panel.history.item(0).toolTip())
            panel.select_tool('PNG')
            self.assertTrue(panel.report_card.isHidden())
            controller._on_worker_result(False, 'erro', [])
            self.assertEqual(controller.last_report, [])
            panel.show_report('x', [])
            self.assertTrue(panel.report_card.isHidden())
        panel.allow_close = True; panel.close()


class VisualToolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    @staticmethod
    def drag(view, start, end):
        QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=view.mapFromScene(*start))
        QTest.mouseMove(view.viewport(), view.mapFromScene(*end), delay=10)
        QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=view.mapFromScene(*end))

    def make_view(self, size=(300, 200)):
        from PySide6.QtGui import QPixmap
        from visual_tools import CropView
        pixmap = QPixmap(*size); pixmap.fill(Qt.GlobalColor.gray)
        view = CropView(pixmap); view.resize(640, 440); view.show(); self.app.processEvents()
        return view

    def test_crop_selection_can_be_resized_by_handle_and_moved(self):
        from visual_tools import selection_to_image_box
        view = self.make_view()
        self.drag(view, (50, 40), (150, 120))
        self.assertEqual(selection_to_image_box(view, (300, 200)), (50, 40, 100, 80))
        self.drag(view, (150, 120), (210, 160))            # alça sudeste
        self.assertEqual(selection_to_image_box(view, (300, 200)), (50, 40, 160, 120))
        self.drag(view, (100, 80), (130, 90))               # mover pelo interior
        x, y, w, h = selection_to_image_box(view, (300, 200))
        self.assertEqual((w, h), (160, 120))
        self.assertAlmostEqual(x, 80, delta=2); self.assertAlmostEqual(y, 50, delta=2)
        view.close()

    def test_crop_selection_stays_inside_image_when_dragged_past_edges(self):
        from visual_tools import selection_to_image_box
        view = self.make_view()
        self.drag(view, (100, 100), (900, 900))
        box = selection_to_image_box(view, (300, 200))
        self.assertEqual(box, (100, 100, 200, 100))
        self.drag(view, (200, 150), (-500, -500))           # mover para fora: deve ficar presa na borda
        x, y, w, h = selection_to_image_box(view, (300, 200))
        self.assertEqual((x, y, w, h), (0, 0, 200, 100))
        view.close()

    def test_aspect_ratio_constrains_new_selection_and_corner_resize(self):
        from visual_tools import selection_to_image_box
        view = self.make_view((320, 240))
        view.set_aspect(1.0)
        self.drag(view, (40, 40), (200, 90))
        x, y, w, h = selection_to_image_box(view, (320, 240))
        self.assertEqual(w, h); self.assertGreaterEqual(w, 150)
        view.set_aspect(16 / 9)
        x, y, w, h = selection_to_image_box(view, (320, 240))
        self.assertAlmostEqual(w / h, 16 / 9, delta=0.05)
        corner = (x + w, y + h)
        self.drag(view, corner, (corner[0] - 30, corner[1] - 20))
        _x, _y, w2, h2 = selection_to_image_box(view, (320, 240))
        self.assertAlmostEqual(w2 / h2, 16 / 9, delta=0.05)
        self.assertLess(w2, w)
        view.close()

    def test_aspect_selection_never_leaves_image(self):
        from visual_tools import selection_to_image_box
        view = self.make_view((320, 240))
        view.set_aspect(9 / 16)
        self.drag(view, (200, 200), (900, 900))
        x, y, w, h = selection_to_image_box(view, (320, 240))
        self.assertLessEqual(x + w, 320); self.assertLessEqual(y + h, 240)
        self.assertAlmostEqual(w / h, 9 / 16, delta=0.05)
        view.close()

    def test_panel_aspect_combo_updates_crop_fields(self):
        panel = FeaturePanel(JobController(capabilities={'images': (True, 'ok'), 'pdf': (True, 'ok')}))
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / 'aspect.png'
            Image.new('RGB', (400, 300), '#6284a1').save(path)
            panel.set_files([str(path)], 'Crop → PNG')
            panel.resize(900, 640); panel.show(); self.app.processEvents()
            panel.crop_aspect.setCurrentIndex(2)   # 1:1
            self.drag(panel.crop_preview, (20, 20), (250, 150))
            self.assertEqual(panel.crop_width.value(), panel.crop_height.value())
            panel.crop_aspect.setCurrentIndex(5)   # 16:9
            self.assertAlmostEqual(panel.crop_width.value() / panel.crop_height.value(), 16 / 9, delta=0.05)
            panel.select_tool('Crop → PNG')
            self.assertEqual(panel.crop_aspect.currentIndex(), 0)
        panel.allow_close = True; panel.close()

    def test_conversion_preview_shows_rotated_result_size(self):
        panel = FeaturePanel(JobController(capabilities={'images': (True, 'ok'), 'pdf': (True, 'ok')}))
        self.assertEqual(FeaturePanel.output_size((4000, 3000), 1000, 90), (750, 1000))
        self.assertEqual(FeaturePanel.output_size((800, 600), 2000, 0), (800, 600))
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / 'resize.png'
            Image.new('RGB', (400, 200), '#6284a1').save(path)
            panel.set_files([str(path)], 'PNG')
            panel.resize(900, 640); panel.show(); self.app.processEvents()
            panel.rotation.setCurrentIndex(1)
            self.assertEqual(panel.static_preview.sceneRect().size().toTuple(), (200.0, 400.0))
            panel.width.setValue(100)
            self.assertIn('50 × 100', panel.tool_hint.text())
            panel.select_tool('Compress → JPEG')
            self.assertEqual(panel.static_preview.sceneRect().size().toTuple(), (400.0, 200.0))
        panel.allow_close = True; panel.close()

    def test_engine_rotation_matches_preview_direction(self):
        from engine import convert
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / 'dir.png'
            image = Image.new('RGB', (40, 20), 'white'); image.putpixel((0, 0), (255, 0, 0)); image.save(path)
            out = convert({'paths': [str(path)], 'target': 'PNG', 'rotation': 90})[0]
            with Image.open(out) as rotated:
                self.assertEqual(rotated.size, (20, 40))
                self.assertEqual(rotated.convert('RGB').getpixel((19, 0)), (255, 0, 0))   # horário: canto sup. esq. vai para sup. dir.

    def test_compress_presets_set_quality_and_custom_value_reverts_to_custom(self):
        panel = FeaturePanel(JobController(capabilities={'images': (True, 'ok'), 'pdf': (True, 'ok')}))
        panel.compress_preset.setCurrentIndex(2)          # Pequeno · 70
        self.assertEqual(panel.quality.value(), 70)
        panel.quality.setValue(50)
        self.assertEqual(panel.compress_preset.currentText(), 'Mínimo · 50')
        panel.quality.setValue(63)
        self.assertEqual(panel.compress_preset.currentText(), 'Personalizado')
        panel.allow_close = True; panel.close()

    def test_compress_estimate_matches_real_output_size_and_updates_preview(self):
        import random
        from engine import convert
        panel = FeaturePanel(JobController(capabilities={'images': (True, 'ok'), 'pdf': (True, 'ok')}))
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / 'estimate.png'
            rng = random.Random(3)
            image = Image.new('RGB', (200, 150))
            image.putdata([(rng.randrange(256), rng.randrange(256), rng.randrange(256)) for _ in range(200 * 150)])
            image.save(path)
            panel.set_files([str(path)], 'Compress → JPEG')
            panel.resize(900, 640); panel.show(); self.app.processEvents()
            panel.quality.setValue(40)
            panel._run_estimate()
            original, estimated = panel.estimate
            self.assertEqual(original, path.stat().st_size)
            real = Path(convert({'paths': [str(path)], 'target': 'Compress → JPEG', 'quality': 40})[0]).stat().st_size
            self.assertEqual(estimated, real)
            self.assertIn('estimado', panel.tool_hint.text()); self.assertIn('%', panel.tool_hint.text())
            self.assertEqual(panel.stage.currentIndex(), 4)
            panel.select_tool('PNG')
            self.assertIsNone(panel._pil_image)
        panel.allow_close = True; panel.close()

    def test_compress_estimate_warns_when_jpeg_would_be_larger(self):
        panel = FeaturePanel(JobController(capabilities={'images': (True, 'ok'), 'pdf': (True, 'ok')}))
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / 'flat.png'
            Image.new('RGB', (200, 150), '#6284a1').save(path, optimize=True)   # cor chapada: PNG minúsculo
            panel.set_files([str(path)], 'Compress → JPEG')
            panel.quality.setValue(100); panel._run_estimate()
            self.assertIn('maior que o original', panel.tool_hint.text())
        panel.allow_close = True; panel.close()

    def test_clear_selection_resets_to_none(self):
        view = self.make_view()
        self.drag(view, (10, 10), (100, 100))
        view.clear_selection()
        self.assertIsNone(view.selected_bounds())
        view.close()

    def test_tiny_selection_is_rejected(self):
        view = self.make_view()
        self.drag(view, (10, 10), (10, 10))
        self.assertIsNone(view.selected_bounds())
        view.close()

    def test_annotation_click_updates_position_fields_and_spins_move_marker(self):
        panel = FeaturePanel(JobController(capabilities={'images': (True, 'ok'), 'pdf': (True, 'ok')}))
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / 'annotate.png'
            Image.new('RGB', (300, 200), '#6284a1').save(path)
            panel.set_files([str(path)], 'Annotate → PNG')
            panel.resize(900, 640); panel.show(); self.app.processEvents()
            view = panel.annotate_preview
            self.assertTrue(view.isVisible())
            panel.annotation.setText('Olá')
            QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=view.mapFromScene(120, 80))
            self.assertAlmostEqual(panel.annotation_x.value(), 120, delta=2)
            self.assertAlmostEqual(panel.annotation_y.value(), 80, delta=2)
            panel.annotation_x.setValue(10)
            self.assertEqual(int(view.position.x()), 10)
            self.assertEqual(view.text_item.text(), 'Olá')
        panel.allow_close = True; panel.close()

    def test_canvas_preview_defaults_larger_than_image_and_flags_invalid_sizes(self):
        panel = FeaturePanel(JobController(capabilities={'images': (True, 'ok'), 'pdf': (True, 'ok')}))
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / 'canvas.png'
            Image.new('RGB', (300, 200), '#6284a1').save(path)
            panel.set_files([str(path)], 'Canvas → PNG')
            panel.resize(900, 640); panel.show(); self.app.processEvents()
            self.assertEqual((panel.canvas_width.value(), panel.canvas_height.value()), (360, 240))
            self.assertFalse(panel.canvas_preview.invalid)
            panel.canvas_width.setValue(100)
            self.assertTrue(panel.canvas_preview.invalid)
            self.assertIn('pelo menos', panel.tool_hint.text())
        panel.allow_close = True; panel.close()

    def test_images_category_shows_two_wheels_and_slice_click_opens_tool(self):
        panel = FeaturePanel(JobController(capabilities={'images': (True, 'ok'), 'pdf': (True, 'ok')}))
        panel.resize(1040, 740); panel.show()
        panel.select_category('images'); self.app.processEvents()
        self.assertEqual(len(panel.wheel_widgets), 2)
        tools_wheel = panel.wheel_widgets[1]
        QTest.mouseClick(tools_wheel, Qt.MouseButton.LeftButton, pos=tools_wheel.slice_center(0).toPoint())
        self.assertTrue(tools_wheel.in_group); self.assertIsNone(panel.selected_tool)       # o primeiro clique abre «Transformar»
        QTest.mouseClick(tools_wheel, Qt.MouseButton.LeftButton, pos=tools_wheel.slice_center(0).toPoint())
        self.assertEqual(panel.selected_tool, 'Crop → PNG')
        self.assertIs(panel.pages.currentWidget(), panel.tool_page)
        panel.select_category('pdf'); self.app.processEvents()
        self.assertEqual(len(panel.wheel_widgets), 1)
        panel.allow_close = True; panel.close()

    def test_wheels_are_disabled_when_backend_is_missing(self):
        panel = FeaturePanel(JobController(capabilities={'images': (False, 'Pillow ausente.'), 'pdf': (True, 'ok')}))
        panel.select_category('images')
        wheel = panel.wheel_widgets[0]
        QTest.mouseClick(wheel, Qt.MouseButton.LeftButton, pos=wheel.slice_center(1).toPoint())
        self.assertIsNone(panel.selected_tool)
        panel.allow_close = True; panel.close()

    def test_run_requires_crop_area_and_annotation_text(self):
        controller = JobController(capabilities={'images': (True, 'ok'), 'pdf': (True, 'ok')})
        panel = FeaturePanel(controller)
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / 'run.png'
            Image.new('RGB', (120, 80), '#6284a1').save(path)
            panel.set_files([str(path)], 'Crop → PNG')
            panel.run_selected()
            self.assertFalse(controller.pending_jobs); self.assertIsNone(controller.active_job)
            self.assertIn('área de recorte', panel.status.text())
            panel.select_tool('Annotate → PNG')
            panel.run_selected()
            self.assertIsNone(controller.active_job)
            self.assertIn('texto da anotação', panel.status.text())
        panel.allow_close = True; panel.close()

if __name__ == '__main__':
    unittest.main()
