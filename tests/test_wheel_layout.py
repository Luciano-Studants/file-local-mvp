"""Guarda de design das rodas (0.9.43): nenhuma roda pode ter fatias demais nem rótulos longos, em nenhuma categoria.

Regra permanente: sempre que uma ferramenta nova entrar numa roda, estes testes precisam continuar passando. Se estourar,
a ferramenta vai para um grupo (sub-roda) em tool_registry.PDF_GROUPS / GROUPS, não para o primeiro nível.
"""
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication

import icons
import radial_menu
import tool_registry
import workspace_panel
from radial_menu import RadialWheel

app = QApplication.instance() or QApplication([])


def every_wheel():
    """(nome, ações) de todas as rodas do app, inclusive cada sub-roda já com a fatia «Voltar»."""
    roots = {
        'imagens: conversões': [radial_menu.RadialAction(label, target, description) for target, label, description in workspace_panel.TOOLS['images'] if target in workspace_panel.WHEEL_COLUMNS['images'][0][2]],
        'imagens: ferramentas (painel)': radial_menu.image_tool_actions(engine_targets=True),
        'imagens: ferramentas (Shift+F9)': radial_menu.image_tool_actions(selection_only=True),
        'pdf: painel': radial_menu.pdf_tool_actions(),
        'áudio: painel': radial_menu.audio_tool_actions(),
        'rápida: imagem': radial_menu.actions_for_file('a.png'),
        'rápida: pdf': radial_menu.actions_for_file('a.pdf'),
        'rápida: outro': radial_menu.actions_for_file('a.xyz'),
        'seleção: pdf': radial_menu.actions_for_selection(['a.pdf']),
        'seleção: imagem': radial_menu.actions_for_selection(['a.png']),
        'seleção: várias imagens': radial_menu.actions_for_selection(['a.png', 'b.png']),
    }
    for name, actions in roots.items():
        yield name, actions
        for action in actions:
            if action.children:
                yield f'{name} › {action.label}', list(action.children) + [radial_menu.group_back_action()]


class WheelLayoutTests(unittest.TestCase):
    def test_no_wheel_has_too_many_slices(self):
        for name, actions in every_wheel():
            with self.subTest(name):
                self.assertLessEqual(len(actions), tool_registry.MAX_SLICES, f'{name}: {len(actions)} fatias; mova ferramentas para um grupo')

    def test_labels_are_short_and_unique_per_wheel(self):
        for name, actions in every_wheel():
            with self.subTest(name):
                labels = [a.label for a in actions]
                self.assertEqual(len(labels), len(set(labels)), f'{name}: rótulos repetidos')
                for label in labels:
                    self.assertLessEqual(len(label), tool_registry.MAX_LABEL, f'{name}: «{label}» é longo demais para a fatia')

    def test_every_slice_has_a_description_and_a_known_icon(self):
        for name, actions in every_wheel():
            for action in actions:
                with self.subTest(name, action=action.label):
                    if action.target != radial_menu.BACK_TARGET:
                        self.assertTrue(action.description, 'fatia sem descrição (legenda ao passar o mouse)')
                    if action.icon:
                        self.assertIn(action.icon, icons.ICON_SHAPES)

    def test_audio_wheel_reaches_every_audio_operation_exactly_once(self):
        reachable = tool_registry.audio_flat_targets()
        self.assertEqual(len(reachable), len(set(reachable)))
        children = [c.target for a in radial_menu.audio_tool_actions() for c in a.children]
        self.assertEqual(sorted(children), sorted(reachable))
        self.assertEqual(sorted(reachable), sorted(target for target, _l, _d in workspace_panel.TOOLS['audio']))
        self.assertEqual(workspace_panel.WHEEL_COLUMNS['audio'][0][2], tool_registry.audio_wheel_layout())

    def test_pdf_wheel_reaches_every_pdf_operation_exactly_once(self):
        panel_pdf = [target for target, _label, _description in workspace_panel.TOOLS['pdf']]
        reachable = tool_registry.pdf_flat_targets()
        self.assertEqual(sorted(reachable), sorted(panel_pdf), 'toda operação de PDF do painel precisa estar em exatamente um grupo da roda')
        children = [c.target for a in radial_menu.pdf_tool_actions() for c in a.children]
        self.assertEqual(children, reachable)

    def test_pdf_group_ids_do_not_collide_with_image_groups(self):
        self.assertFalse(tool_registry.pdf_group_action('read').startswith(tool_registry.GROUP_PREFIX))
        panel = workspace_panel.WHEEL_COLUMNS['pdf'][0][2]
        self.assertEqual(panel, tool_registry.pdf_wheel_layout())

    def test_group_navigation_and_render(self):
        wheel = RadialWheel(radial_menu.pdf_tool_actions(), 'Escolha', 330)
        wheel.show()
        self.assertEqual(len(wheel.actions), len(tool_registry.PDF_GROUPS))
        for index in range(len(wheel.actions)):
            self.assertTrue(wheel.open_group(index))
            self.assertTrue(wheel.actions[-1].target == radial_menu.BACK_TARGET)
            self.assertFalse(wheel.grab().isNull())
            self.assertTrue(wheel.close_group())
        wheel.close()

    def test_panel_builds_the_grouped_pdf_wheel(self):
        import tray_app
        panel = tray_app.FeaturePanel(tray_app.JobController()) if hasattr(tray_app, 'FeaturePanel') else None
        if panel is None:
            self.skipTest('painel indisponível')
        panel.select_category('pdf')
        wheels = getattr(panel, 'wheel_widgets', [])
        self.assertEqual(len(wheels), 1)
        self.assertLessEqual(len(wheels[0].actions), tool_registry.MAX_SLICES)
        self.assertTrue(all(a.children for a in wheels[0].actions))
        panel.close()


if __name__ == '__main__':
    unittest.main()
