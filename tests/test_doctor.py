import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location('doctor', ROOT / 'tools' / 'doctor.py')
doctor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(doctor)


class DoctorTests(unittest.TestCase):
    def test_reads_requirements(self):
        names = [n for n, _ in doctor.required_packages()]
        self.assertIn('Pillow', names)
        self.assertIn('pypdf', names)

    def test_windows_only_requirement_filtered(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'r.txt'
            path.write_text('pypdf==1\npywin32>=306,<400; sys_platform == "win32"\n# x\n', encoding='utf-8')
            names = [n for n, _ in doctor.required_packages(path)]
        self.assertIn('pypdf', names)
        self.assertEqual('pywin32' in names, doctor.sys.platform == 'win32')

    def test_check_package_states(self):
        self.assertFalse(doctor.check_package('pacote-que-nao-existe-xyz', '==1')[0])
        ok, version = doctor.check_package('pypdf', '')
        self.assertTrue(ok)
        self.assertFalse(doctor.check_package('pypdf', '==0.0.1')[0])

    def test_all_requirements_satisfied_in_this_environment(self):
        required, _ = doctor.run()
        self.assertEqual([n for n, good, _ in required if not good], [])

    def test_main_exit_code(self):
        self.assertEqual(doctor.main([]), 0)
