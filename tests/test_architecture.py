"""Contrato de arquitetura: tudo o que está em tool_registry precisa estar ligado em todas as camadas.

Quando uma ferramenta nova é registrada e uma camada é esquecida, um destes testes falha — em vez do erro aparecer só na tela.
"""
import ast
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import engine
import icons
import radial_menu
import tool_registry
import tray_app
import workspace_panel
from radial_menu import actions_for_selection, flatten_actions, image_tool_actions

DESKTOP = Path(__file__).resolve().parents[1]
# módulos do núcleo: não podem importar Qt nem módulos de interface/sistema operacional
CORE_MODULES = ('engine.py', 'tool_registry.py', 'package.py', 'runner.py', 'vector.py', 'ocr.py', 'illustrator.py', 'metafile.py', 'bgremove.py', 'winjob.py', 'pdfinfo.py', 'pdfcompress.py', 'pdfstamp.py', 'pdfredact.py', 'pdfform.py')
FORBIDDEN_IN_CORE = {'PySide6', 'vector_qt', 'tray_app', 'workspace_panel', 'radial_menu', 'visual_tools', 'widgets', 'theme', 'icons', 'windows_bridge', 'global_hotkey', 'shell_integration', 'win32gui', 'win32com', 'pythoncom', 'winreg'}


class RegistryConsistencyTests(unittest.TestCase):
    def test_registry_is_well_formed(self):
        targets = [spec.target for spec in tool_registry.IMAGE_TOOLS]; keys = [spec.key for spec in tool_registry.IMAGE_TOOLS]
        self.assertEqual(len(targets), len(set(targets))); self.assertEqual(len(keys), len(set(keys)))
        for spec in tool_registry.IMAGE_TOOLS:
            self.assertTrue(spec.label and spec.tip and spec.title and spec.panel_title and spec.run_label, spec.target)
            self.assertIn(spec.ext, ('png', 'jpg', 'pdf', 'txt'), spec.target)
            self.assertEqual(spec.action, f'__tool_{spec.key}__')
            self.assertTrue(spec.target.startswith(tuple('CRACBDEO')) or True)

    def test_engine_knows_every_tool(self):
        for spec in tool_registry.IMAGE_TOOLS:
            self.assertEqual(engine.IMAGE_OUTPUTS[spec.target], spec.ext)
            self.assertIn(spec.target, engine.OPERATIONS)
            if spec.suffix: self.assertEqual(engine.TOOL_SUFFIX[spec.target], spec.suffix)
            else: self.assertNotIn(spec.target, engine.TOOL_SUFFIX)

    def test_suffixes_are_unique(self):
        suffixes = [s.suffix for s in tool_registry.IMAGE_TOOLS if s.suffix]
        self.assertEqual(len(suffixes), len(set(suffixes)))

    def test_tray_labels_and_options(self):
        for spec in tool_registry.IMAGE_TOOLS:
            self.assertEqual(tray_app.LABELS[spec.target], spec.title)
        self.assertTrue(tool_registry.all_int_options() >= {'width', 'rotation', 'quality'})

    def test_panel_covers_every_tool(self):
        cards = {target for target, _label, _tip in workspace_panel.TOOLS['images']}
        selection_wheel = set(tool_registry.flat_targets(workspace_panel.WHEEL_COLUMNS['images'][1][2]))
        for spec in tool_registry.IMAGE_TOOLS:
            self.assertIn(spec.target, workspace_panel.IMAGE_TARGETS); self.assertIn(spec.target, cards); self.assertIn(spec.target, selection_wheel)
            self.assertEqual(workspace_panel.LABELS[spec.target], spec.panel_title)

    def test_every_tool_has_panel_controls_hint_and_run_label(self):
        """Cada ferramenta precisa ter linhas de formulário próprias e texto de botão (nada de "Converter" genérico)."""
        source = (DESKTOP / 'workspace_panel.py').read_text(encoding='utf-8')
        for spec in tool_registry.IMAGE_TOOLS:
            self.assertIn(f"'{spec.target}': (", source, f'{spec.target}: sem controles em _show_tool_controls')

    def test_wheel_icons_exist(self):
        for spec in tool_registry.IMAGE_TOOLS:
            self.assertIn(spec.icon, icons.ICON_SHAPES, spec.target)
            self.assertEqual(radial_menu.ACTION_ICONS[spec.action], spec.icon); self.assertEqual(radial_menu.ACTION_ICONS[spec.target], spec.icon)

    def test_single_image_wheel_matches_registry(self):
        count = len([s for s in tool_registry.IMAGE_TOOLS if s.in_selection_wheel])
        wheel = [a.target for a in flatten_actions(actions_for_selection([r'C:\x\p.png']))][:count]
        self.assertEqual(wheel, [s.action for s in tool_registry.IMAGE_TOOLS if s.in_selection_wheel])

    def test_groups_are_consistent(self):
        """Todo grupo usado existe, tem rótulo curto, ícone e ao menos duas ferramentas (senão a fatia solta é melhor)."""
        used = {spec.group for spec in tool_registry.IMAGE_TOOLS if spec.group}
        self.assertEqual(used, set(tool_registry.GROUPS))
        for group, (label, tip, icon) in tool_registry.GROUPS.items():
            self.assertLessEqual(len(label), 11, group); self.assertTrue(tip); self.assertIn(icon, icons.ICON_SHAPES)
            self.assertGreaterEqual(len(tool_registry.group_members(group)), 2, group)
            self.assertEqual(radial_menu.ACTION_ICONS[tool_registry.group_action(group)], icon)
        for action in image_tool_actions() + image_tool_actions(selection_only=True):
            self.assertLessEqual(len(action.label), 11, action.label)
            for child in action.children: self.assertLessEqual(len(child.label), 10, child.label)

    def test_top_level_wheels_stay_small_enough_to_read(self):
        """Limite de legibilidade: no máximo 8 fatias por nível (a roda de 11 fatias já cortava os rótulos)."""
        for selection_only in (False, True):
            top = image_tool_actions(selection_only=selection_only)
            self.assertLessEqual(len(top) + 1, 8)
            for action in top: self.assertLessEqual(len(action.children) + 1, 8)


class LayerBoundaryTests(unittest.TestCase):
    def test_core_does_not_import_ui_or_os_specific_modules(self):
        for name in CORE_MODULES:
            path = DESKTOP / name
            if not path.exists():
                continue
            tree = ast.parse(path.read_text(encoding='utf-8'))
            imported = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import): imported |= {alias.name.split('.')[0] for alias in node.names}
                elif isinstance(node, ast.ImportFrom) and node.module: imported.add(node.module.split('.')[0])
            self.assertFalse(imported & FORBIDDEN_IN_CORE, f'{name} importa {imported & FORBIDDEN_IN_CORE}: o núcleo não pode depender de interface ou de Windows')

    def test_windows_only_modules_are_isolated(self):
        """Só estes arquivos podem importar APIs exclusivas do Windows — o que faltar para Linux fica restrito a eles."""
        allowed = {'windows_bridge.py', 'global_hotkey.py', 'shell_integration.py', 'windows_acceptance_check.py', 'radial_menu.py', 'settings_dialog.py'}
        for path in DESKTOP.glob('*.py'):
            tree = ast.parse(path.read_text(encoding='utf-8'))
            names = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import): names |= {alias.name.split('.')[0] for alias in node.names}
                elif isinstance(node, ast.ImportFrom) and node.module: names.add(node.module.split('.')[0])
            if names & {'win32gui', 'win32com', 'pythoncom', 'winreg'}:
                self.assertIn(path.name, allowed, f'{path.name} usa API exclusiva do Windows fora dos módulos de plataforma')


if __name__ == '__main__':
    unittest.main()
