"""Dividir e extrair páginas (0.9.32): modos, nomes, pasta «- partes», marcadores, erros, controlador e painel."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from pypdf import PdfReader, PdfWriter
from PySide6.QtWidgets import QApplication

import engine
import pdfinfo
import runner
from engine import ConversionError, convert
from tray_app import JobController
from workspace_panel import FeaturePanel

APP = QApplication.instance() or QApplication([])
NEEDS_PDFIUM = unittest.skipUnless(pdfinfo.preview_available(), 'pypdfium2 não instalado')
T = 'Split PDF'


class Base(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name); self.addCleanup(self.temp.cleanup)

    def pdf(self, name='doc.pdf', pages=7, bookmark_page=None):
        writer = PdfWriter()
        for i in range(pages): writer.add_blank_page(100 + i, 100)      # largura = 100 + índice: identifica a página
        if bookmark_page is not None: writer.add_outline_item('Capítulo', bookmark_page)
        path = self.root / name
        with path.open('wb') as handle: writer.write(handle)
        return path

    @staticmethod
    def widths(path):
        return [int(float(p.mediabox.width)) for p in PdfReader(str(path)).pages]

    def names(self, outputs):
        return [Path(x).relative_to(self.root).as_posix() for x in outputs]


class GroupTests(unittest.TestCase):
    def test_parse_groups(self):
        g = pdfinfo.parse_page_groups
        self.assertEqual(g('1-2; 5-;4', 7), [[1, 2], [5, 6, 7], [4]]); self.assertEqual(g('1-3;', 5), [[1, 2, 3]]); self.assertEqual(g('1\n2,3', 5), [[1], [2, 3]])
        for bad in ('', ' ', '1;;2', ';1', '9', 'x'):
            with self.assertRaises(pdfinfo.PdfError, msg=bad): g(bad, 5)

    def test_groups_per_mode(self):
        self.assertEqual(engine.split_groups('every', 3, '', 7), [[1, 2, 3], [4, 5, 6], [7]]); self.assertEqual(engine.split_groups('each', 1, '', 2), [[1], [2]])
        self.assertEqual(engine.split_groups('extract', 1, '2,7', 7), [[2, 7]])
        with self.assertRaisesRegex(ConversionError, 'extraídas'): engine.split_groups('extract', 1, '', 7)

    def test_option_validation(self):
        for bad in ({'split_mode': 'x'}, {'split_every': 0}, {'split_every': 201}, {'split_every': '2'}, {'split_every': True}, {'split_ranges': 'a' * 201}):
            with self.assertRaises(ConversionError, msg=str(bad)): engine.split_options_from(bad)
        self.assertEqual(engine.split_options_from({}), ('each', 1, ''))


class ConvertTests(Base):
    def test_default_is_one_file_per_page_in_a_parts_folder(self):
        out = convert({'paths': [str(self.pdf(pages=3))], 'target': T})
        self.assertEqual(self.names(out), ['doc - partes/pagina-001.pdf', 'doc - partes/pagina-002.pdf', 'doc - partes/pagina-003.pdf'])
        self.assertEqual([self.widths(x) for x in out], [[100], [101], [102]])

    def test_every_n(self):
        out = convert({'paths': [str(self.pdf())], 'target': T, 'split_mode': 'every', 'split_every': 3})
        self.assertEqual(self.names(out)[0], 'doc - partes/parte-001.pdf'); self.assertEqual([self.widths(x) for x in out], [[100, 101, 102], [103, 104, 105], [106]])

    def test_ranges_allow_overlap_and_order(self):
        out = convert({'paths': [str(self.pdf())], 'target': T, 'split_mode': 'ranges', 'split_ranges': '5-; 1-2; 2'})
        self.assertEqual([self.widths(x) for x in out], [[104, 105, 106], [100, 101], [101]])

    def test_extract_makes_one_loose_file(self):
        out = convert({'paths': [str(self.pdf())], 'target': T, 'split_mode': 'extract', 'split_ranges': '7,2-3'})
        self.assertEqual(self.names(out), ['doc-extraido.pdf']); self.assertEqual(self.widths(out[0]), [106, 101, 102])      # as páginas saem na ordem em que foram escritas

    def test_bookmarks_follow_the_copied_pages(self):
        source = self.pdf(bookmark_page=3)
        kept = PdfReader(convert({'paths': [str(source)], 'target': T, 'split_mode': 'extract', 'split_ranges': '3-5'})[0])
        self.assertEqual([o.title for o in kept.outline], ['Capítulo'])
        gone = PdfReader(convert({'paths': [str(source)], 'target': T, 'split_mode': 'extract', 'split_ranges': '1-2'})[0])
        self.assertEqual(list(gone.outline), [])

    def test_errors_leave_nothing_behind(self):
        source = self.pdf()
        for options, pattern in (({'split_mode': 'extract'}, 'extraídas'), ({'split_mode': 'ranges', 'split_ranges': '1;;2'}, 'vazio'), ({'split_mode': 'ranges', 'split_ranges': '9'}, 'passa do fim'),
                                 ({'split_mode': 'every', 'split_every': 0}, 'entre 1 e 200'), ({'split_mode': 'nada'}, 'desconhecido')):
            with self.assertRaisesRegex(ConversionError, pattern): convert({'paths': [str(source)], 'target': T, **options})
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ['doc.pdf'])

    def test_second_run_gets_a_new_folder_and_extract_never_overwrites(self):
        source = self.pdf(pages=2)
        convert({'paths': [str(source)], 'target': T}); second = convert({'paths': [str(source)], 'target': T})
        self.assertEqual(self.names(second)[0], 'doc - partes (2)/pagina-001.pdf')
        a = convert({'paths': [str(source)], 'target': T, 'split_mode': 'extract', 'split_ranges': '1'}); b = convert({'paths': [str(source)], 'target': T, 'split_mode': 'extract', 'split_ranges': '1'})
        self.assertNotEqual(a, b)

    def test_page_limit_still_applies(self):
        with self.assertRaisesRegex(ConversionError, '200'): convert({'paths': [str(self.pdf('big.pdf', 201))], 'target': T})

    def test_real_worker_publishes_into_the_folder_only_at_the_end(self):
        source = self.pdf()
        out = runner.run_job({'paths': [str(source)], 'target': T, 'split_mode': 'every', 'split_every': 4})
        self.assertEqual(self.names(out), ['doc - partes/parte-001.pdf', 'doc - partes/parte-002.pdf'])
        out = runner.run_job({'paths': [str(source)], 'target': T, 'split_mode': 'extract', 'split_ranges': '1'})
        self.assertEqual(self.names(out), ['doc-extraido.pdf'])
        with self.assertRaises(ValueError): runner.run_job({'paths': [str(source)], 'target': T, 'split_mode': 'ranges', 'split_ranges': '99'})
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ['doc - partes', 'doc-extraido.pdf', 'doc.pdf'])


class ReportTests(unittest.TestCase):
    def test_reports_by_mode(self):
        self.assertIn('Só as páginas escolhidas', ' '.join(engine.loss_report(['/x.pdf'], T, {'split_mode': 'extract'})))
        self.assertIn('partes de N', ' '.join(engine.loss_report(['/x.pdf'], T, {'split_mode': 'every'})))
        self.assertIn('marcadores', ' '.join(engine.loss_report(['/x.pdf'], T)))


class ControllerAndPanelTests(Base):
    def controller(self):
        patcher = mock.patch.object(JobController, '_start_next'); patcher.start(); self.addCleanup(patcher.stop)
        return JobController(capabilities={'images': (True, 'ok'), 'pdf': (True, 'ok')})

    def test_controller_option_types(self):
        source = str(self.pdf())
        c = self.controller(); self.assertTrue(c.start_job([source], T, {'split_mode': 'every', 'split_every': 3, 'split_ranges': ''}))
        for bad in ({'split_every': '3'}, {'split_mode': 4}, {'split_ranges': 5}):
            self.assertFalse(self.controller().start_job([source], T, bad))

    @NEEDS_PDFIUM
    def test_panel_modes_result_text_and_gate(self):
        panel = FeaturePanel(self.controller()); panel.resize(1100, 760); panel.pdf_stage.loader = lambda job: runner.run_pdf_op(job); self.addCleanup(panel.pdf_stage.shutdown)
        panel.set_files([str(self.pdf())], T); APP.processEvents()
        self.assertEqual(panel._split_values(), {'split_mode': 'each'}); self.assertIn('7 PDFs de 1 página', panel.split_info.text()); self.assertTrue(panel.run_button.isEnabled())
        panel.split_mode.setCurrentIndex(1); panel.split_every.setValue(3); APP.processEvents()
        self.assertEqual(panel._split_values(), {'split_mode': 'every', 'split_every': 3}); self.assertIn('3 PDFs (de 1 a 3 páginas)', panel.split_info.text())
        panel.split_mode.setCurrentIndex(2); APP.processEvents()
        self.assertFalse(panel.run_button.isEnabled()); panel.split_ranges.setText('1-2; 5-'); APP.processEvents()
        self.assertTrue(panel.run_button.isEnabled()); self.assertIn('2 PDFs', panel.split_info.text())
        panel.split_ranges.setText('1-2; 99'); APP.processEvents()
        self.assertFalse(panel.run_button.isEnabled()); self.assertIn('passa do fim', panel.split_info.text())
        panel.split_mode.setCurrentIndex(3); panel.split_ranges.setText('2,4'); APP.processEvents()
        self.assertTrue(panel.run_button.isEnabled()); self.assertIn('Um PDF novo com 2 páginas (de 7)', panel.split_info.text())
        self.assertEqual(panel._split_values(), {'split_mode': 'extract', 'split_ranges': '2,4'})


if __name__ == '__main__':
    unittest.main()
