"""Ferramenta Metadados (inspeção + cópia PNG sem metadados)."""
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

from engine import TOOL_SUFFIX, convert, inspect_metadata, loss_report
from radial_menu import RadialAction, actions_for_selection, flatten_actions
import tool_registry
from tray_app import FeaturePanel, JobController


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def tagged_jpeg(path, gps=True, orientation=1):
    im = Image.new('RGB', (64, 48))
    im.putdata([((x * 9) % 256, (y * 5) % 256, 90) for y in range(48) for x in range(64)])
    exif = Image.Exif()
    exif[0x010F] = 'MarcaX'; exif[0x0110] = 'Modelo 9'; exif[0x0131] = 'EditorY'; exif[0x013B] = 'Maria'
    exif[0x0112] = orientation
    sub = exif.get_ifd(0x8769); sub[0x9003] = '2026:01:02 03:04:05'
    if gps:
        g = exif.get_ifd(0x8825)
        g[1] = 'S'; g[2] = (23.0, 30.0, 0.0); g[3] = 'W'; g[4] = (46.0, 38.0, 0.0)
    im.save(path, exif=exif)
    return im


class MetadataEngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_inspection_lists_identifying_fields_in_portuguese(self):
        path = self.root / 'a.jpg'; tagged_jpeg(path)
        info = inspect_metadata(str(path))
        rows = dict(info['rows'])
        self.assertIsNone(info['error'])
        self.assertEqual(rows['Fabricante da câmera'], 'MarcaX'); self.assertEqual(rows['Modelo da câmera'], 'Modelo 9')
        self.assertEqual(rows['Software'], 'EditorY'); self.assertEqual(rows['Autor'], 'Maria')
        self.assertEqual(rows['Data e hora'], '2026:01:02 03:04:05')
        self.assertEqual(rows['Localização (GPS)'], '-23.50000, -46.63333')
        self.assertIn('JPEG', rows['Formato']); self.assertIn('64 × 48', rows['Formato'])
        for label in ('Localização (GPS)', 'Data e hora', 'Modelo da câmera', 'Autor'):
            self.assertIn(label, info['sensitive'])
        self.assertNotIn('Software', info['sensitive'])

    def test_clean_file_and_broken_file_never_raise(self):
        clean = self.root / 'c.png'; Image.new('RGB', (10, 10)).save(clean)
        info = inspect_metadata(str(clean))
        self.assertEqual(info['sensitive'], []); self.assertIn(('Metadados', 'nenhum conhecido além dos pixels'), info['rows'])
        broken = self.root / 'b.png'; broken.write_bytes(b'not an image')
        self.assertIsNotNone(inspect_metadata(str(broken))['error'])
        self.assertIsNotNone(inspect_metadata(str(self.root / 'missing.png'))['error'])
        self.assertIsNotNone(inspect_metadata('relativo.png')['error'])

    def test_text_values_are_sanitized(self):
        path = self.root / 's.jpg'
        im = Image.new('RGB', (8, 8)); exif = Image.Exif(); exif[0x013B] = 'Ana\x00\x1b[31m' + 'z' * 200; im.save(path, exif=exif)
        value = dict(inspect_metadata(str(path))['rows'])['Autor']
        self.assertTrue(value.isprintable()); self.assertLessEqual(len(value), 80); self.assertTrue(value.endswith('…'))

    def test_clean_copy_keeps_pixels_and_drops_metadata(self):
        path = self.root / 'a.jpg'; tagged_jpeg(path)
        before = digest(path)
        out = Path(convert({'paths': [str(path)], 'target': 'Clean → PNG'})[0])
        self.assertEqual(digest(path), before)
        self.assertTrue(out.name.endswith('-sem-metadados.png'), out.name)
        with Image.open(out) as result, Image.open(path) as src:
            self.assertEqual(len(result.getexif()), 0)
            self.assertFalse(set(result.info) & {'exif', 'xmp', 'comment'})
            from PIL import ImageChops
            self.assertIsNone(ImageChops.difference(result.convert('RGB'), src.convert('RGB')).getbbox())
        info = inspect_metadata(str(out))
        self.assertEqual(info['sensitive'], [])

    def test_clean_copy_applies_orientation(self):
        path = self.root / 'o.jpg'; tagged_jpeg(path, orientation=6)
        out = Path(convert({'paths': [str(path)], 'target': 'Clean → PNG'})[0])
        with Image.open(out) as result:
            self.assertEqual(result.size, (48, 64))

    def test_report_and_suffix(self):
        path = self.root / 'a.jpg'; tagged_jpeg(path)
        text = ' '.join(loss_report([str(path)], 'Clean → PNG', {}))
        self.assertIn('Os pixels não mudaram', text); self.assertIn('Metadados da origem', text)
        plain = self.root / 'p.png'; Image.new('RGB', (4, 4)).save(plain)
        self.assertIn('não tinha metadados conhecidos', ' '.join(loss_report([str(plain)], 'Clean → PNG', {})))
        self.assertEqual(TOOL_SUFFIX['Clean → PNG'], 'sem-metadados')


class MetadataUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def tearDown(self):
        if hasattr(self, 'tmp'):
            self.tmp.cleanup()

    def make_panel(self, count=1):
        controller = JobController(capabilities={'images': (True, 'ok'), 'pdf': (True, 'ok')})
        panel = FeaturePanel(controller)
        self.tmp = tempfile.TemporaryDirectory()
        paths = []
        for index in range(count):
            path = Path(self.tmp.name) / f'f{index}.jpg'; tagged_jpeg(path, gps=index == 0); paths.append(str(path))
        panel.set_files(paths, 'Clean → PNG')
        return controller, panel

    def test_radial_and_wheel_entries(self):
        self.assertIn('__tool_clean__', [a.target for a in flatten_actions(actions_for_selection([r'C:\x\p.png']))])
        self.assertEqual(RadialAction('Metadados', '__tool_clean__').icon, 'metadata')
        import icons, workspace_panel
        self.assertIn('metadata', icons.ICON_SHAPES)
        self.assertIn('Clean → PNG', tool_registry.flat_targets(workspace_panel.WHEEL_COLUMNS['images'][1][2]))

    def test_panel_shows_info_and_runs_without_options(self):
        controller, panel = self.make_panel()
        visible = sorted(k for k, w in panel.form_fields.items() if panel.settings_form.isRowVisible(w) and k not in ('nname', 'nexample', 'nstart', 'ndigits'))
        self.assertEqual(visible, ['minfo', 'ofmt'])
        text = panel.metadata_info.text()
        self.assertIn('Localização (GPS): -23.50000', text); self.assertIn('Modelo da câmera: Modelo 9', text)
        self.assertIn('Pode identificar pessoa, lugar ou aparelho', text)
        self.assertEqual(panel.run_button.text(), 'Salvar cópia sem metadados')
        captured = {}
        with patch.object(controller, 'start_job', side_effect=lambda files, target, options: captured.update(target=target, files=files) or True):
            panel.run_selected()
        self.assertEqual(captured['target'], 'Clean → PNG'); self.assertEqual(len(captured['files']), 1)
        panel.allow_close = True; panel.close()

    def test_multiple_files_show_one_line_each(self):
        _controller, panel = self.make_panel(count=2)
        lines = panel.metadata_info.text().splitlines()
        self.assertEqual(len(lines), 2)
        self.assertIn('Localização (GPS)', lines[0]); self.assertIn('Localização (GPS)', lines[0])
        panel.allow_close = True; panel.close()


if __name__ == '__main__':
    unittest.main()
