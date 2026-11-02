"""Unir PDFs melhorado (0.9.31): intervalo por arquivo, marcadores, nome «unido», limites, lista reordenável no painel e controlador."""
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
T = 'Merge PDFs'


class Base(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name); self.addCleanup(self.temp.cleanup)

    def pdf(self, name, pages, base_width=100, bookmark=None):
        """Páginas com larguras distintas (base_width + índice) para reconhecer cada uma no resultado."""
        writer = PdfWriter()
        for i in range(pages): writer.add_blank_page(base_width + i, 100)
        if bookmark: writer.add_outline_item(bookmark, min(1, pages - 1))
        path = self.root / name
        with path.open('wb') as handle: writer.write(handle)
        return path

    @staticmethod
    def widths(path):
        return [int(float(p.mediabox.width)) for p in PdfReader(str(path)).pages]


class EngineTests(Base):
    def test_all_pages_in_list_order_and_portuguese_name(self):
        a, b = self.pdf('a.pdf', 2, 100), self.pdf('b.pdf', 3, 200)
        out = convert({'paths': [str(b), str(a)], 'target': T})
        self.assertEqual(Path(out[0]).name, 'unido.pdf'); self.assertEqual(self.widths(out[0]), [200, 201, 202, 100, 101])

    def test_range_per_file(self):
        a, b = self.pdf('a.pdf', 4, 100), self.pdf('b.pdf', 3, 200)
        out = convert({'paths': [str(a), str(b)], 'target': T, 'merge_ranges': ['1,4', '2-']})
        self.assertEqual(self.widths(out[0]), [100, 103, 201, 202])
        out = convert({'paths': [str(a), str(b)], 'target': T, 'merge_ranges': ['', '-1']})
        self.assertEqual(self.widths(out[0]), [100, 101, 102, 103, 200])

    def test_one_bookmark_per_file_and_original_bookmarks_kept(self):
        a, b = self.pdf('a.pdf', 3, 100, 'Capítulo A'), self.pdf('b.pdf', 2, 200)
        reader = PdfReader(convert({'paths': [str(a), str(b)], 'target': T})[0])
        titles = [o.title if not isinstance(o, list) else [x.title for x in o] for o in reader.outline]
        self.assertEqual(titles, ['a', ['Capítulo A'], 'b'])
        dropped = PdfReader(convert({'paths': [str(a), str(b)], 'target': T, 'merge_ranges': ['1', '']})[0])      # o marcador apontava para a página 2, que ficou de fora
        self.assertEqual([o.title for o in dropped.outline if not isinstance(o, list)], ['a', 'b'])

    def test_invalid_ranges_name_the_file_and_leave_nothing(self):
        a, b = self.pdf('a.pdf', 2), self.pdf('b.pdf', 2)
        for ranges, pattern in ((['9', ''], r'a\.pdf.*passa do fim'), (['', 'x'], r'b\.pdf.*inválido'), (['1'], 'não combinam'), ('1', 'não combinam'), (['1', 5], 'não combinam')):
            with self.assertRaisesRegex(ConversionError, pattern): convert({'paths': [str(a), str(b)], 'target': T, 'merge_ranges': ranges})
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ['a.pdf', 'b.pdf'])

    def test_page_cap_counts_only_chosen_pages(self):
        big = self.pdf('big.pdf', 150); other = self.pdf('o.pdf', 100)
        with self.assertRaisesRegex(ConversionError, '200'): convert({'paths': [str(big), str(other)], 'target': T})
        out = convert({'paths': [str(big), str(other)], 'target': T, 'merge_ranges': ['1-100', '']})
        self.assertEqual(len(PdfReader(out[0]).pages), 200)

    def test_never_overwrites_existing_unido(self):
        a, b = self.pdf('a.pdf', 1), self.pdf('b.pdf', 1)
        first = convert({'paths': [str(a), str(b)], 'target': T})[0]; second = convert({'paths': [str(a), str(b)], 'target': T})[0]
        self.assertNotEqual(first, second); self.assertTrue(Path(first).is_file())

    def test_through_the_real_worker(self):
        a, b = self.pdf('a.pdf', 3), self.pdf('b.pdf', 3, 200)
        out = runner.run_job({'paths': [str(a), str(b)], 'target': T, 'merge_ranges': ['2', '3']})
        self.assertEqual(self.widths(out[0]), [101, 202])


class ReportTests(Base):
    def test_report_mentions_bookmarks_and_chosen_ranges(self):
        notes = ' '.join(engine.loss_report([], T, {'merge_ranges': ['1-2', '', ' ']}))
        self.assertIn('marcador', notes); self.assertIn('Em 1 arquivo só entraram', notes); self.assertIn('formulário', notes)
        self.assertNotIn('só entraram', ' '.join(engine.loss_report([], T, {})))


class ControllerTests(Base):
    def controller(self):
        patcher = mock.patch.object(JobController, '_start_next'); patcher.start(); self.addCleanup(patcher.stop)
        return JobController(capabilities={'images': (True, 'ok'), 'pdf': (True, 'ok')})

    def test_ranges_accepted_only_for_merge_with_matching_length(self):
        a, b = str(self.pdf('a.pdf', 1)), str(self.pdf('b.pdf', 1))
        controller = self.controller()
        self.assertTrue(controller.start_job([a, b], T, {'merge_ranges': ['1', '']}))
        self.assertEqual(controller.pending_jobs[0]['options']['merge_ranges'], ['1', ''])
        for bad in (['1'], '1', ['1', 2], ['1', 'x' * 201]):
            self.assertFalse(self.controller().start_job([a, b], T, {'merge_ranges': bad}))
        self.assertFalse(self.controller().start_job([a], 'Split PDF', {'merge_ranges': ['1']}))


@NEEDS_PDFIUM
class PanelTests(Base):
    def panel(self, *specs):
        controller = JobController(capabilities={'images': (True, 'ok'), 'pdf': (True, 'ok')})
        panel = FeaturePanel(controller); panel.resize(1100, 760); panel.pdf_stage.loader = lambda job: runner.run_pdf_op(job)
        self.addCleanup(panel.pdf_stage.shutdown)
        paths = [str(self.pdf(name, pages)) for name, pages in specs]
        panel.set_files(paths, T); APP.processEvents(); return panel, paths

    def test_list_total_and_range_gate(self):
        panel, paths = self.panel(('a.pdf', 4), ('b.pdf', 3))
        self.assertEqual(panel.collage_list.count(), 2); self.assertIn('4 pág.', panel.collage_list.item(0).text())
        self.assertIn('7 páginas', panel.merge_info.text()); self.assertTrue(panel.run_button.isEnabled())
        panel.collage_list.setCurrentRow(1); panel.merge_pages.setText('2-9'); APP.processEvents()
        self.assertFalse(panel.run_button.isEnabled()); self.assertIn('b.pdf', panel.merge_info.text())
        panel.merge_pages.setText('2-3'); APP.processEvents()
        self.assertTrue(panel.run_button.isEnabled()); self.assertIn('6 páginas', panel.merge_info.text()); self.assertIn('páginas 2-3', panel.collage_list.item(1).text())
        self.assertEqual(panel._merge_options(), {'merge_ranges': ['', '2-3']})

    def test_reorder_and_remove_keep_ranges_with_their_files(self):
        panel, paths = self.panel(('a.pdf', 4), ('b.pdf', 3), ('c.pdf', 2))
        panel.collage_list.setCurrentRow(0); panel.merge_pages.setText('1'); APP.processEvents()
        panel.move_collage_item(1); APP.processEvents()
        self.assertEqual(panel.files, [paths[1], paths[0], paths[2]]); self.assertEqual(panel._merge_options(), {'merge_ranges': ['', '1', '']})
        self.assertEqual(panel.pdf_stage.paths, panel.files)
        panel.collage_list.setCurrentRow(1); panel.remove_collage_item(); APP.processEvents()
        self.assertEqual(panel.files, [paths[1], paths[2]]); self.assertNotIn('merge_ranges', panel._merge_options())
        panel.collage_list.setCurrentRow(0); panel.remove_collage_item(); APP.processEvents()
        self.assertFalse(panel.run_button.isEnabled()); self.assertIn('pelo menos dois', panel.merge_info.text())

    def test_selecting_a_row_previews_that_file(self):
        panel, paths = self.panel(('a.pdf', 4), ('b.pdf', 3))
        panel.collage_list.setCurrentRow(1); APP.processEvents()
        self.assertEqual(panel.pdf_stage.current_path, paths[1]); self.assertEqual(panel.pdf_stage.thumbs.count(), 3)

    def test_page_limit_blocks_the_button(self):
        panel, _paths = self.panel(('a.pdf', 150), ('b.pdf', 100))
        self.assertFalse(panel.run_button.isEnabled()); self.assertIn('250', panel.merge_info.text())


if __name__ == '__main__':
    unittest.main()
