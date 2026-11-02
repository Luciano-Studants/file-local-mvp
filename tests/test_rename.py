"""Lote com renomeação: padrão {nome}/{n}/{sufixo}/{data}, validação, nomes seguros, fila numerada, painel e relatório."""
import datetime
import hashlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PIL import Image
from PySide6.QtWidgets import QApplication

from engine import ConversionError, RENAME_MAX_STEM, convert, loss_report, rename_options_from, rename_stem
from tray_app import FeaturePanel, JobController


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def opts(pattern, start=1, digits=1, n=None):
    return rename_options_from({'rename_pattern': pattern, 'rename_start': start, 'rename_digits': digits, **({'rename_n': n} if n is not None else {})})


class RenameOptionTests(unittest.TestCase):
    def test_empty_means_default_behaviour(self):
        for job in ({}, {'rename_pattern': ''}, {'rename_pattern': '   '}, {'rename_pattern': None}): self.assertIsNone(rename_options_from(job))

    def test_parsing_and_defaults(self):
        self.assertEqual(rename_options_from({'rename_pattern': ' {nome}-{n} '}), {'pattern': '{nome}-{n}', 'start': 1, 'digits': 1, 'n': 1})
        self.assertEqual(opts('{n}', start=10, digits=3, n=12), {'pattern': '{n}', 'start': 10, 'digits': 3, 'n': 12})

    def test_rejections(self):
        for bad in ('a/b', 'a\\b', 'a:b', 'a*b', 'a?b', 'a"b', 'a<b', 'a>b', 'a|b', 'a\x01b', '{x}', '{nome', 'nome}', '{{nome}}', '{}', 'x' * 121, 5):
            with self.assertRaises(ConversionError, msg=repr(bad)): rename_options_from({'rename_pattern': bad})
        for kw in ({'rename_start': -1}, {'rename_start': 1000000}, {'rename_digits': 0}, {'rename_digits': 7}, {'rename_n': -1}, {'rename_n': 10_000_000}, {'rename_start': 'a'}):
            with self.assertRaises(ConversionError, msg=str(kw)): rename_options_from({'rename_pattern': '{n}', **kw})

    def test_dotted_patterns_are_allowed(self):
        self.assertEqual(rename_stem(opts('{nome}.v2'), 'a', 's'), 'a.v2')


class RenameStemTests(unittest.TestCase):
    def test_tokens(self):
        day = datetime.date(2026, 10, 25)
        self.assertEqual(rename_stem(opts('{nome}-{n}', digits=3, n=7), 'foto', 'x'), 'foto-007')
        self.assertEqual(rename_stem(opts('{sufixo}_{nome}'), 'foto', 'redimensionada'), 'redimensionada_foto')
        self.assertEqual(rename_stem(opts('{data}-{nome}'), 'foto', 'x', today=day), '2026-10-25-foto')
        self.assertEqual(rename_stem(opts('{nome}{nome}-{n}', n=0), 'ab', 'x'), 'abab-0'); self.assertEqual(rename_stem(opts('Viagem {n}', n=12, digits=2), 'x', 'x'), 'Viagem 12')

    def test_number_wider_than_digits_is_kept(self):
        self.assertEqual(rename_stem(opts('{n}', digits=2, n=1234), 'a', 's'), '1234')

    def test_long_names_are_shortened_but_keep_the_counter(self):
        stem = rename_stem(opts('{nome}-{n}', digits=3, n=5), 'a' * 300, 's'); self.assertLessEqual(len(stem), RENAME_MAX_STEM); self.assertTrue(stem.endswith('-005'))
        stem = rename_stem(opts('{nome}-{nome}-{n}', n=9), 'b' * 300, 's'); self.assertLessEqual(len(stem), RENAME_MAX_STEM); self.assertTrue(stem.endswith('-9'))
        with self.assertRaises(ConversionError): rename_stem(opts('x' * 110 + '{n}'), 'a', 's')

    def test_empty_or_dot_only_result_is_refused_and_trailing_dots_trimmed(self):
        with self.assertRaises(ConversionError): rename_stem(opts('.'), 'a', 's')
        with self.assertRaises(ConversionError): rename_stem(opts('..'), 'a', 's')
        self.assertEqual(rename_stem(opts('{nome}.'), 'a', 's'), 'a'); self.assertEqual(rename_stem(opts('{nome} '), 'a', 's'), 'a')

    def test_hostile_original_names_are_sanitised(self):
        self.assertEqual(rename_stem(opts('{nome}-{n}'), 'a<b>c', 's'), 'a_b_c-1')


class RenameEngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.source = self.root / 'foto.png'; Image.new('RGB', (40, 30), (10, 20, 30)).save(self.source)

    def tearDown(self):
        self.temp.cleanup()

    def job(self, target='PNG', **kw):
        before = digest(self.source)
        out = [Path(p) for p in convert({'paths': [str(self.source)], 'target': target, **kw})]
        self.assertEqual(digest(self.source), before)
        return out

    def test_default_name_is_unchanged_without_pattern(self):
        self.assertEqual(self.job()[0].name, 'foto-converted.png'); self.assertEqual(self.job('Resize → PNG', resize_mode='percent', resize_percent=50)[0].name, 'foto-redimensionada.png')

    def test_pattern_with_counter(self):
        out = self.job(rename_pattern='{nome}-{n}', rename_digits=3, rename_n=7)[0]; self.assertEqual((out.name, out.parent), ('foto-007.png', self.root))

    def test_collision_never_overwrites(self):
        first = self.job(rename_pattern='{nome}-{n}', rename_n=1)[0]; before = digest(first)
        second = self.job(rename_pattern='{nome}-{n}', rename_n=1)[0]
        self.assertEqual((first.name, second.name), ('foto-1.png', 'foto-1-2.png')); self.assertEqual(digest(first), before)

    def test_pattern_equal_to_original_name_keeps_the_original(self):
        out = self.job(rename_pattern='{nome}')[0]; self.assertNotEqual(out, self.source); self.assertEqual(out.name, 'foto-2.png')       # foto.png já existe

    def test_suffix_token_follows_the_tool(self):
        self.assertEqual(self.job('Resize → PNG', resize_mode='percent', resize_percent=50, rename_pattern='{sufixo}-{nome}')[0].name, 'redimensionada-foto.png')

    def test_extension_is_always_the_tools(self):
        self.assertEqual(self.job('JPEG', rename_pattern='{nome}.png')[0].name, 'foto.png.jpg'); self.assertEqual(self.job('Compress → JPEG', rename_pattern='c-{nome}')[0].name, 'c-foto.jpg')
        self.assertEqual(self.job('Image → PDF', rename_pattern='doc-{n}')[0].name, 'doc-1.pdf')
        self.assertEqual(self.job('Resize → PNG', resize_mode='percent', resize_percent=50, out_format='webp', rename_pattern='w')[0].name, 'w.webp')

    def test_reserved_windows_names_are_handled(self):
        self.assertEqual(self.job(rename_pattern='CON')[0].name, 'file-CON.png')

    def test_collage_uses_the_pattern(self):
        other = self.root / 'b.png'; Image.new('RGB', (40, 30), (200, 0, 0)).save(other)
        out = Path(convert({'paths': [str(self.source), str(other)], 'target': 'Collage → PNG', 'rename_pattern': '{nome}-{n}', 'rename_n': 3})[0])
        self.assertEqual(out.name, 'colagem-3.png'); self.assertEqual(Path(convert({'paths': [str(self.source), str(other)], 'target': 'Collage → PNG'})[0]).name, 'collage.png')

    def test_invalid_pattern_stops_the_job_and_writes_nothing(self):
        before = sorted(p.name for p in self.root.iterdir())
        with self.assertRaises(ConversionError): self.job(rename_pattern='a/b')
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), before)

    def test_loss_report_mentions_the_pattern_only_when_used(self):
        used = ' '.join(loss_report([str(self.source)], 'PNG', {'rename_pattern': '{nome}-{n}'})); self.assertIn('«{nome}-{n}»', used); self.assertIn('-2, -3', used); self.assertIn('não é renomeado', used)
        self.assertNotIn('padrão', ' '.join(loss_report([str(self.source)], 'PNG', {})).lower().replace('nenhuma perda adicional conhecida', ''))
        self.assertNotIn('«', ' '.join(loss_report([str(self.source)], 'PNG', {'rename_pattern': 'a/b'})))                      # padrão inválido não vira nota


class RenameQueueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.paths = []
        for name in ('a', 'b', 'c'):
            path = self.root / f'{name}.png'; Image.new('RGB', (20, 20), (1, 2, 3)).save(path); self.paths.append(str(path))
        self.controller = JobController(capabilities={'images': (True, 'ok'), 'pdf': (True, 'ok')}); self.controller.notify = lambda *a, **k: None; self.controller._start_next = lambda: None

    def tearDown(self):
        self.temp.cleanup()

    def test_each_file_gets_the_next_number(self):
        self.assertTrue(self.controller.start_job(self.paths, 'PNG', {'rename_pattern': '{nome}-{n}', 'rename_start': 5, 'rename_digits': 2}))
        self.assertEqual([job['options']['rename_n'] for job in self.controller.pending_jobs], [5, 6, 7])
        names = [Path(convert({'paths': job['paths'], 'target': job['target'], **job['options']})[0]).name for job in self.controller.pending_jobs]
        self.assertEqual(names, ['a-05.png', 'b-06.png', 'c-07.png'])

    def test_default_start_is_one_and_no_pattern_adds_nothing(self):
        self.controller.start_job(self.paths, 'PNG', {'rename_pattern': '{n}'}); self.assertEqual([j['options']['rename_n'] for j in self.controller.pending_jobs], [1, 2, 3])
        self.controller.pending_jobs.clear(); self.controller.start_job(self.paths, 'PNG', {}); self.assertTrue(all('rename_n' not in j['options'] for j in self.controller.pending_jobs))
        self.controller.pending_jobs.clear(); self.controller.start_job(self.paths, 'PNG', {'rename_pattern': '  '}); self.assertTrue(all('rename_n' not in j['options'] for j in self.controller.pending_jobs))

    def test_collage_is_one_job_with_the_first_number(self):
        self.controller.start_job(self.paths, 'Collage → PNG', {'rename_pattern': 'c{n}', 'rename_start': 9}); self.assertEqual(len(self.controller.pending_jobs), 1); self.assertEqual(self.controller.pending_jobs[0]['options']['rename_n'], 9)

    def test_whitelist_types_and_limits(self):
        for bad in ({'rename_pattern': 5}, {'rename_pattern': 'x' * 201}, {'rename_pattern': '{n}', 'rename_start': '1'}, {'rename_pattern': '{n}', 'rename_digits': True}, {'rename_n': 1.5}):
            self.assertFalse(self.controller.start_job(self.paths[:1], 'PNG', bad), msg=str(bad))

    def test_invalid_pattern_fails_in_the_engine_not_silently(self):
        self.controller.start_job(self.paths[:1], 'PNG', {'rename_pattern': 'a/b'})
        job = self.controller.pending_jobs[0]
        with self.assertRaises(ConversionError): convert({'paths': job['paths'], 'target': job['target'], **job['options']})


class RenameUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def tearDown(self):
        if hasattr(self, 'panel'):
            self.panel.allow_close = True; self.panel.close()
        if hasattr(self, 'tmp'):
            self.tmp.cleanup()

    def make_panel(self, target='PNG', count=2):
        self.controller = JobController(capabilities={'images': (True, 'ok'), 'pdf': (True, 'ok')}); self.panel = FeaturePanel(self.controller)
        self.tmp = tempfile.TemporaryDirectory(); paths = []
        for index in range(count):
            path = Path(self.tmp.name) / f'f{index}.png'; Image.new('RGB', (60, 40), (255, 255, 255)).save(path); paths.append(str(path))
        self.panel.set_files(paths, target)
        self.panel.to_folder.setChecked(False)          # estes testes cobrem o modo sem pasta numerada (ver test_batch_folder)
        return self.controller, self.panel

    def visible(self, panel):
        return {k for k, w in panel.form_fields.items() if panel.settings_form.isRowVisible(w)}

    def test_rows_follow_the_counter_marker(self):
        _c, panel = self.make_panel(); keys = {'nname', 'nexample', 'nstart', 'ndigits'}
        self.assertEqual(self.visible(panel) & keys, {'nname', 'nexample'})
        panel.rename_pattern.setText('{nome}-{n}'); self.assertEqual(self.visible(panel) & keys, keys)
        panel.rename_pattern.setText('{nome}'); self.assertEqual(self.visible(panel) & keys, {'nname', 'nexample'})

    def test_example_shows_real_names_and_extension(self):
        _c, panel = self.make_panel('Resize → PNG'); self.assertIn('Nome padrão', panel.rename_example.text())
        panel.rename_pattern.setText('{nome}-{n}'); panel.rename_digits.slider.setValue(3); panel.rename_start.setValue(8)
        self.assertEqual(panel.rename_example.text(), 'f0-008.png · f1-009.png')
        panel.out_format.setCurrentIndex(2); self.assertTrue(panel.rename_example.text().startswith('f0-008.webp'))

    def test_example_for_pdf_collage_and_many_files(self):
        _c, panel = self.make_panel('Image → PDF'); panel.rename_pattern.setText('doc-{n}'); self.assertEqual(panel.rename_example.text(), 'doc-1.pdf · doc-2.pdf')
        _c, panel = self.make_panel('Collage → PNG'); panel.rename_pattern.setText('{nome}-{n}'); self.assertEqual(panel.rename_example.text(), 'colagem-1.png')
        _c, panel = self.make_panel(count=4); panel.rename_pattern.setText('{n}'); self.assertTrue(panel.rename_example.text().endswith('…'))

    def test_warning_when_names_would_repeat(self):
        _c, panel = self.make_panel(); panel.rename_pattern.setText('foto'); self.assertIn('-2, -3', panel.rename_example.text())
        panel.rename_pattern.setText('{n}'); self.assertNotIn('-2, -3', panel.rename_example.text())
        _c, panel = self.make_panel(count=1); panel.rename_pattern.setText('foto'); self.assertNotIn('-2, -3', panel.rename_example.text())

    def test_invalid_pattern_is_explained_and_blocks_the_run(self):
        controller, panel = self.make_panel(); panel.rename_pattern.setText('a/b'); self.assertIn('Padrão inválido', panel.rename_example.text())
        with patch.object(controller, 'start_job') as start: panel.run_selected(); start.assert_not_called(); self.assertIn('não pode ter', panel.status.text())
        panel.rename_pattern.setText('{xyz}'); self.assertIn('desconhecido', panel.rename_example.text())

    def test_options_are_sent_only_with_a_pattern(self):
        controller, panel = self.make_panel()
        with patch.object(controller, 'start_job') as start:
            panel.run_selected(); self.assertNotIn('rename_pattern', start.call_args.args[2])
            panel.rename_pattern.setText('{nome}-{n}'); panel.rename_start.setValue(4); panel.rename_digits.slider.setValue(2); panel.run_selected(); sent = start.call_args.args[2]
            self.assertEqual((sent['rename_pattern'], sent['rename_start'], sent['rename_digits']), ('{nome}-{n}', 4, 2))

    def test_other_tools_and_non_image_operations(self):
        _c, panel = self.make_panel('Sharpen → PNG'); self.assertIn('nname', self.visible(panel))
        _c, panel = self.make_panel('Compress → JPEG'); self.assertIn('nname', self.visible(panel)); panel.rename_pattern.setText('c-{nome}'); self.assertEqual(panel.rename_example.text(), 'c-f0.jpg · c-f1.jpg')
        _c, panel = self.make_panel('Merge PDFs'); self.assertNotIn('nname', self.visible(panel))

    def test_reopening_resets_the_name(self):
        _c, panel = self.make_panel(); panel.rename_pattern.setText('{n}'); panel.rename_start.setValue(5)
        panel.set_files(panel.files, 'PNG'); self.assertEqual((panel.rename_pattern.text(), panel.rename_start.value(), panel.rename_digits.value()), ('', 1, 1))


if __name__ == '__main__':
    unittest.main()
