"""Várias imagens de formatos diferentes → uma pasta nova com nomes numerados na ordem da seleção (0.9.27)."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image
from PySide6.QtWidgets import QApplication

import engine
from engine import ConversionError, batch_rename_options, create_batch_folder
from runner import run_job
from tray_app import JobController
from workspace_panel import FeaturePanel

APP = QApplication.instance() or QApplication([])
FORMATS = (('a.png', 'PNG'), ('b.jpg', 'JPEG'), ('c.webp', 'WEBP'), ('d.bmp', 'BMP'), ('e.tif', 'TIFF'))


def make_files(folder, count=5):
    paths = []
    for index in range(count):
        name, fmt = FORMATS[index % len(FORMATS)]
        path = Path(folder) / f'orig{index}-{name}'
        Image.new('RGB', (40 + index, 30), (index * 40, 90, 160)).save(path, format=fmt)
        paths.append(str(path))
    return paths


class BatchHelpersTests(unittest.TestCase):
    def test_default_names_are_numbers_with_at_least_three_digits(self):
        options = batch_rename_options({}, 5)
        self.assertEqual((options['rename_pattern'], options['rename_start'], options['rename_digits']), ('{n}', 1, 3))
        self.assertEqual(batch_rename_options({'rename_start': 998}, 5)['rename_digits'], 4)

    def test_user_pattern_without_counter_gets_one(self):
        self.assertEqual(batch_rename_options({'rename_pattern': 'viagem'}, 3)['rename_pattern'], 'viagem-{n}')
        self.assertEqual(batch_rename_options({'rename_pattern': 'viagem {n}'}, 3)['rename_pattern'], 'viagem {n}')

    def test_folder_is_new_never_reused_and_stays_inside_parent(self):
        with tempfile.TemporaryDirectory() as tmp:
            import datetime
            moment = datetime.datetime(2026, 10, 29, 9, 0, 0)
            first = create_batch_folder(tmp, moment); second = create_batch_folder(tmp, moment)
            self.assertNotEqual(first, second)
            self.assertEqual(first.parent, Path(tmp).resolve()); self.assertTrue(first.is_dir() and second.is_dir())
            self.assertIn('Convertidas 2026-10-29 09-00-00', first.name)

    def test_folder_creation_failure_is_portuguese(self):
        with self.assertRaises(ConversionError):
            create_batch_folder('relativa/pasta')


class BatchFolderEndToEndTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.controller = JobController(capabilities={'images': (True, 'ok'), 'pdf': (True, 'ok')})
        self.controller.notify = lambda *a, **k: None
        self.controller._start_next = lambda: None          # só enfileira; o trabalho é executado abaixo, de forma síncrona

    def run_queue(self):
        outputs = []
        while self.controller.pending_jobs:
            job = self.controller.pending_jobs.popleft()
            outputs += run_job({'paths': job['paths'], 'target': job['target'], **job['options']})
        return outputs

    def test_mixed_formats_go_to_one_numbered_folder_in_selection_order(self):
        paths = make_files(self.tmp.name)
        before = {p: Path(p).read_bytes() for p in paths}
        self.assertTrue(self.controller.start_job(paths, 'PNG', {'to_folder': 'on'}))
        outputs = self.run_queue()
        self.assertEqual([Path(o).name for o in outputs], ['001.png', '002.png', '003.png', '004.png', '005.png'])
        folders = {Path(o).parent for o in outputs}
        self.assertEqual(len(folders), 1)
        folder = folders.pop()
        self.assertTrue(folder.name.startswith('Convertidas ')); self.assertEqual(folder.parent, Path(self.tmp.name).resolve())
        self.assertEqual(sorted(p.name for p in folder.iterdir()), ['001.png', '002.png', '003.png', '004.png', '005.png'])      # nada de arquivos de preparo
        for index, output in enumerate(outputs):                      # a ordem da seleção é a ordem dos números
            with Image.open(output) as im: self.assertEqual(im.size, (40 + index, 30))
        self.assertEqual({p: Path(p).read_bytes() for p in paths}, before)       # originais intactos
        self.assertEqual(sorted(p.name for p in Path(self.tmp.name).iterdir() if p.is_file()), sorted(Path(p).name for p in paths))

    def test_other_output_formats_and_tools(self):
        paths = make_files(self.tmp.name, 3)
        self.controller.start_job(paths, 'JPEG', {'to_folder': 'on'})
        outputs = self.run_queue()
        self.assertEqual([Path(o).name for o in outputs], ['001.jpg', '002.jpg', '003.jpg'])

    def test_without_the_option_nothing_changes(self):
        paths = make_files(self.tmp.name, 3)
        self.controller.start_job(paths, 'PNG', {})
        outputs = self.run_queue()
        self.assertTrue(all(Path(o).parent == Path(self.tmp.name).resolve() for o in outputs))
        self.assertFalse(any(p.name.startswith('Convertidas') for p in Path(self.tmp.name).iterdir()))

    def test_single_file_and_pdf_operations_ignore_the_option(self):
        paths = make_files(self.tmp.name, 1)
        self.controller.start_job(paths, 'PNG', {'to_folder': 'on'})
        self.assertFalse(any(p.name.startswith('Convertidas') for p in Path(self.tmp.name).iterdir()))
        self.controller.pending_jobs.clear()
        self.controller.start_job(make_files(self.tmp.name, 3), 'Images → One PDF', {'to_folder': 'on'})
        self.assertFalse(any(p.name.startswith('Convertidas') for p in Path(self.tmp.name).iterdir()))

    def test_user_pattern_and_start_number(self):
        paths = make_files(self.tmp.name, 3)
        self.controller.start_job(paths, 'PNG', {'to_folder': 'on', 'rename_pattern': 'viagem', 'rename_start': 10})
        self.assertEqual([Path(o).name for o in self.run_queue()], ['viagem-010.png', 'viagem-011.png', 'viagem-012.png'])

    def test_empty_folder_is_removed_when_everything_fails(self):
        bad = []
        for index in range(2):
            path = Path(self.tmp.name) / f'ruim{index}.png'; path.write_bytes(b'nao sou imagem'); bad.append(str(path))
        self.controller.start_job(bad, 'PNG', {'to_folder': 'on'})
        for job in list(self.controller.pending_jobs):
            with self.assertRaises(Exception): run_job({'paths': job['paths'], 'target': job['target'], **job['options']})
        self.controller.pending_jobs.clear(); self.controller._cleanup_batch_dirs()
        self.assertFalse(any(p.name.startswith('Convertidas') for p in Path(self.tmp.name).iterdir()))

    def test_folder_with_results_is_never_removed(self):
        paths = make_files(self.tmp.name, 2)
        self.controller.start_job(paths, 'PNG', {'to_folder': 'on'}); self.run_queue(); self.controller._cleanup_batch_dirs()
        self.assertEqual(len([p for p in Path(self.tmp.name).iterdir() if p.name.startswith('Convertidas')]), 1)

    def test_queue_full_removes_the_new_folder(self):
        paths = make_files(self.tmp.name, 2)
        self.controller.MAX_QUEUED_JOBS = 1
        self.assertFalse(self.controller.start_job(paths, 'PNG', {'to_folder': 'on'}))
        self.assertFalse(any(p.name.startswith('Convertidas') for p in Path(self.tmp.name).iterdir()))


class BatchFolderPanelTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.controller = JobController(capabilities={'images': (True, 'ok'), 'pdf': (True, 'ok')})
        self.panel = FeaturePanel(self.controller)
        self.sent = []
        self.controller.start_job = lambda files, target, options: self.sent.append((list(files), target, dict(options))) or True

    def test_checkbox_is_on_for_many_files_and_hidden_for_one_or_ordered_tools(self):
        paths = make_files(self.tmp.name, 3)
        self.panel.set_files(paths, 'PNG')
        self.assertTrue(self.panel.to_folder.isChecked()); self.assertTrue(self.panel.settings_form.isRowVisible(self.panel.to_folder))
        self.assertIn('001.png', self.panel.rename_example.text())
        self.panel.set_files(paths[:1], 'PNG')
        self.assertFalse(self.panel.to_folder.isChecked()); self.assertFalse(self.panel.settings_form.isRowVisible(self.panel.to_folder))
        self.panel.set_files(paths, 'Collage → PNG')
        self.assertFalse(self.panel.settings_form.isRowVisible(self.panel.to_folder))

    def test_run_sends_to_folder_only_when_checked(self):
        paths = make_files(self.tmp.name, 3)
        self.panel.set_files(paths, 'PNG'); self.panel.run_selected()
        self.assertEqual(self.sent[-1][2].get('to_folder'), 'on')
        self.panel.to_folder.setChecked(False); self.panel.run_selected()
        self.assertNotIn('to_folder', self.sent[-1][2])

    def test_wheel_conversions_of_many_files_use_the_folder(self):
        import tray_app
        source = Path(tray_app.__file__).read_text(encoding='utf8')
        import re
        self.assertEqual(len(re.findall(r"\{'to_folder':\s*'on'\}\s*if len\(", source)), 2)


if __name__ == '__main__':
    unittest.main()
