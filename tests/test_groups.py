"""Sub-rodas: grupos de ferramentas na roda (navegação, voltar, Esc, arrastar, legenda, ligação com painel e menu flutuante)."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
from PySide6.QtGui import QDropEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

import tool_registry
from radial_menu import BACK_TARGET, RadialAction, RadialMenu, RadialWheel, actions_for_selection, image_tool_actions
from tray_app import FeaturePanel, JobController


def sample_actions():
    return [RadialAction('Um', 'um'), RadialAction('Grupo', '__group_x__', 'Descrição', children=(RadialAction('A', 'a'), RadialAction('B', 'b'))), RadialAction('Três', 'tres')]


class WheelGroupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make(self):
        wheel = RadialWheel(sample_actions(), 'Escolha', 340)
        wheel.show(); self.app.processEvents()
        self.events = {'activated': [], 'hovered': [], 'navigated': 0}
        wheel.activated.connect(lambda i: self.events['activated'].append(wheel.actions[i].target))
        wheel.hovered.connect(lambda i: self.events['hovered'].append(i))
        wheel.navigated.connect(lambda: self.events.__setitem__('navigated', self.events['navigated'] + 1))
        return wheel

    def click(self, wheel, index):
        QTest.mouseClick(wheel, Qt.MouseButton.LeftButton, pos=wheel.slice_center(index).toPoint())

    def test_group_opens_with_children_and_back(self):
        wheel = self.make(); self.click(wheel, 1)
        self.assertTrue(wheel.in_group)
        self.assertEqual([a.target for a in wheel.actions], ['a', 'b', BACK_TARGET])
        self.assertEqual(wheel.center_text(), 'Grupo'); self.assertEqual(self.events['activated'], [])   # abrir um grupo não executa nada
        self.assertEqual(self.events['navigated'], 1); self.assertEqual(self.events['hovered'][-1], -1)

    def test_child_click_activates_and_back_restores_root(self):
        wheel = self.make(); self.click(wheel, 1); self.click(wheel, 0)
        self.assertEqual(self.events['activated'], ['a'])
        self.click(wheel, 2)                                                    # Voltar
        self.assertFalse(wheel.in_group); self.assertEqual([a.target for a in wheel.actions], ['um', '__group_x__', 'tres'])
        self.assertEqual(wheel.center_text(), 'Escolha'); self.assertEqual(self.events['activated'], ['a'])

    def test_escape_and_backspace_go_back_only_inside_a_group(self):
        wheel = self.make(); self.click(wheel, 1)
        QTest.keyClick(wheel, Qt.Key.Key_Escape); self.assertFalse(wheel.in_group)
        self.click(wheel, 1); QTest.keyClick(wheel, Qt.Key.Key_Backspace); self.assertFalse(wheel.in_group)

    def test_keyboard_opens_group(self):
        wheel = self.make(); wheel.set_hover(1); QTest.keyClick(wheel, Qt.Key.Key_Return)
        self.assertTrue(wheel.in_group)
        wheel.set_hover(0); QTest.keyClick(wheel, Qt.Key.Key_Space); self.assertEqual(self.events['activated'], ['a'])

    def test_disabled_state_is_restored_after_back(self):
        wheel = RadialWheel(sample_actions(), 'x', 340, disabled=[0]); wheel.show()
        wheel.activate(0); self.assertFalse(wheel.in_group)
        wheel.open_group(1); self.assertEqual(wheel.disabled, set())
        wheel.close_group(); self.assertEqual(wheel.disabled, {0})

    def test_open_group_ignores_plain_slices_and_double_open(self):
        wheel = self.make()
        self.assertFalse(wheel.open_group(0)); self.assertFalse(wheel.open_group(99))
        self.assertTrue(wheel.open_group(1)); self.assertFalse(wheel.open_group(0))
        self.assertTrue(wheel.close_group()); self.assertFalse(wheel.close_group())

    def test_files_cannot_be_dropped_on_groups_or_back(self):
        wheel = self.make()
        self.assertFalse(wheel._accepts_drop(1)); self.assertTrue(wheel._accepts_drop(0))
        wheel.open_group(1); self.assertTrue(wheel._accepts_drop(0)); self.assertFalse(wheel._accepts_drop(2))
        dropped = []; wheel.dropped.connect(lambda i, p: dropped.append((i, p)))
        mime = QMimeData(); mime.setUrls([QUrl.fromLocalFile('/tmp/x.png')])
        event = QDropEvent(wheel.slice_center(2), Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        wheel.dropEvent(event); self.assertEqual(dropped, [])
        event = QDropEvent(wheel.slice_center(0), Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        wheel.dropEvent(event); self.assertEqual([i for i, _p in dropped], [0])


class ImageGroupIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_every_tool_is_reachable_from_the_single_image_menu(self):
        reached = set()
        for action in actions_for_selection([r'C:\x\p.png']):
            reached.update(c.target for c in action.children) if action.children else reached.add(action.target)
        self.assertEqual(reached & {s.action for s in tool_registry.IMAGE_TOOLS}, {s.action for s in tool_registry.IMAGE_TOOLS if s.in_selection_wheel})

    def test_floating_menu_runs_the_child_action_and_never_the_group(self):
        chosen = []
        menu = RadialMenu('p.png', actions_for_selection([r'C:\x\p.png']), lambda action: chosen.append(action.target)); menu.show(); self.app.processEvents()
        wheel = menu.wheel
        QTest.mouseClick(wheel, Qt.MouseButton.LeftButton, pos=wheel.slice_center(0).toPoint())     # Transformar ›
        self.assertTrue(menu.isVisible()); self.assertEqual(chosen, [])                              # continua aberto
        QTest.mouseClick(wheel, Qt.MouseButton.LeftButton, pos=wheel.slice_center(1).toPoint())     # Tamanho
        self.assertEqual(chosen, ['__tool_resize__']); self.assertFalse(menu.isVisible())

    def test_floating_menu_drop_on_child_uses_the_child_action(self):
        got = []
        menu = RadialMenu('p.png', actions_for_selection([r'C:\x\p.png']), lambda action: None, on_drop=lambda paths, action: got.append((paths, action.target)))
        menu.show(); menu.wheel.open_group(0); menu.wheel.dropped.emit(2, ['/tmp/a.png'])
        self.assertEqual(got, [(['/tmp/a.png'], '__tool_rotate__')])

    def test_panel_group_click_then_child_opens_tool_and_back_returns(self):
        panel = FeaturePanel(JobController(capabilities={'images': (True, 'ok'), 'pdf': (True, 'ok')}))
        panel.resize(1040, 740); panel.show(); panel.select_category('images'); self.app.processEvents()
        wheel = panel.wheel_widgets[1]
        names = [a.label for a in wheel.actions]; self.assertEqual(names, ['Transformar', 'Ajustes', 'Desenhar', 'Proteger', 'Ler texto', 'PDF único', 'Colagem'])
        QTest.mouseClick(wheel, Qt.MouseButton.LeftButton, pos=wheel.slice_center(1).toPoint())     # Ajustes
        self.assertEqual([a.label for a in wheel.actions], ['Ajustar', 'Níveis', 'Nitidez', 'Fundo', 'Sem fundo', 'Voltar'])
        QTest.mouseClick(wheel, Qt.MouseButton.LeftButton, pos=wheel.slice_center(5).toPoint())     # Voltar
        self.assertFalse(wheel.in_group); self.assertIsNone(panel.selected_tool)
        panel.allow_close = True; panel.close()

    def test_panel_wheel_is_disabled_for_groups_without_backend(self):
        panel = FeaturePanel(JobController(capabilities={'images': (False, 'Pillow ausente.'), 'pdf': (True, 'ok')}))
        panel.select_category('images'); wheel = panel.wheel_widgets[1]
        QTest.mouseClick(wheel, Qt.MouseButton.LeftButton, pos=wheel.slice_center(0).toPoint())
        self.assertFalse(wheel.in_group); self.assertIsNone(panel.selected_tool)
        panel.allow_close = True; panel.close()


if __name__ == '__main__':
    unittest.main()
