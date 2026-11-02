"""Kit de instalação do Windows (0.9.26): confere que os arquivos existem e que as regras de segurança do instalador estão escritas (não executa nada)."""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class InstallerKitTests(unittest.TestCase):
    def setUp(self):
        self.iss = (ROOT / 'instalador' / 'ArquivoLocal.iss').read_text(encoding='utf8')
        self.ps1 = (ROOT / 'instalador' / 'build_windows.ps1').read_text(encoding='utf8')
        self.readme = (ROOT / 'instalador' / 'LEIA-ME-INSTALACAO.md').read_text(encoding='utf8')

    def test_files_exist(self):
        for name in ('ArquivoLocal.iss', 'build_windows.ps1', 'LEIA-ME-INSTALACAO.md'):
            self.assertTrue((ROOT / 'instalador' / name).is_file(), name)

    def test_installer_never_needs_administrator_and_touches_only_hkcu(self):
        self.assertIn('PrivilegesRequired=lowest', self.iss)
        self.assertNotIn('PrivilegesRequired=admin', self.iss)
        roots = set(re.findall(r'^Root:\s*(\w+)', self.iss, re.M))
        self.assertEqual(roots, {'HKCU'})
        self.assertIn('x64compatible', self.iss); self.assertIn('LicenseFile=..\\..\\LICENSE', self.iss)

    def test_optional_tasks_are_off_by_default_and_registry_is_removed_on_uninstall(self):
        for task in ('startup', 'contextmenu'):
            line = next(l for l in self.iss.splitlines() if l.startswith(f'Name: "{task}"'))
            self.assertIn('unchecked', line)
        for line in (l for l in self.iss.splitlines() if l.startswith('Root: HKCU') and 'ValueName: ""' in l and 'command' not in l.split('Subkey')[1].split(';')[0]):
            self.assertIn('uninsdeletekey', line)
        self.assertIn('uninsdeletevalue', self.iss)

    def test_context_menu_command_matches_the_app(self):
        import shell_integration
        self.assertEqual(shell_integration.VERB_KEY, 'ArquivoLocal')
        self.assertIn('--send-to', self.iss)
        for base in shell_integration.BASES:
            self.assertIn(base.replace('Software\\Classes\\', 'Software\\Classes\\'), self.iss)

    def test_script_runs_tests_and_quality_before_packaging_and_stops_on_failure(self):
        self.assertIn("$ErrorActionPreference = 'Stop'", self.ps1)
        order = [self.ps1.index(token) for token in ('-m unittest discover', '& $py tools\\quality_suite.py', '& $py package.py', '& $py verify_package.py', '& $iscc')]
        self.assertEqual(order, sorted(order))
        self.assertGreaterEqual(self.ps1.count('throw'), 6)

    def test_readme_states_the_unverified_status_and_next_steps(self):
        for word in ('não foram executados no Windows', 'SmartScreen', 'SHA-256', 'offline', 'Tesseract', 'u2net.onnx'):
            self.assertIn(word, self.readme.replace('ainda não foram executados', 'não foram executados') if word.startswith('não foram') else self.readme)


if __name__ == '__main__':
    unittest.main()
