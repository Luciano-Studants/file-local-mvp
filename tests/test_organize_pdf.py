"""Organizar páginas (0.9.33): motor (giro, exclusão, duplicação, ordem), miniaturas em lotes, widget PageOrganizer, painel e controlador."""
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
from page_organizer import PageOrganizer
from tray_app import JobController
from workspace_panel import FeaturePanel, STAGE_ORGANIZE

APP = QApplication.instance() or QApplication([])
NEEDS_PDFIUM = unittest.skipUnless(pdfinfo.preview_available(), 'pypdfium2 não instalado')
T = 'Organize PDF'


class Base(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name); self.addCleanup(self.temp.cleanup)

    def pdf(self, name='doc.pdf', pages=4):
        writer = PdfWriter()
        for i in range(pages): writer.add_blank_page(100 + i, 50)      # largura = 100 + índice
        writer.add_outline_item('Capítulo', 0)
        path = self.root / name
        with path.open('wb') as handle: writer.write(handle)
        return path

    @staticmethod
    def summary(path):
        return [(int(float(p.mediabox.width)), int(p.get('/Rotate') or 0)) for p in PdfReader(str(path)).pages]


class EngineTests(Base):
    def test_order_rotation_deletion_and_duplication(self):
        out = convert({'paths': [str(self.pdf())], 'target': T, 'organize_pages': ['3:90', '1:0', '1:180', '4:270']})
        self.assertEqual(Path(out[0]).name, 'doc-organizado.pdf')
        self.assertEqual(self.summary(out[0]), [(102, 90), (100, 0), (100, 180), (103, 270)])      # página 2 foi excluída, a 1 aparece duas vezes

    def test_rotation_adds_to_the_existing_rotation(self):
        writer = PdfWriter(); page = writer.add_blank_page(100, 50); page.rotate(90)
        source = self.root / 'r.pdf'
        with source.open('wb') as handle: writer.write(handle)
        out = convert({'paths': [str(source)], 'target': T, 'organize_pages': ['1:90']})
        self.assertEqual(self.summary(out[0]), [(100, 180)])

    def test_invalid_plans_leave_nothing(self):
        source = self.pdf()
        for plan in ([], None, 'x', ['9:0'], ['0:0'], ['1:45'], ['1'], [1], ['1:0'] * 201):
            with self.assertRaises(ConversionError, msg=str(plan)): convert({'paths': [str(source)], 'target': T, 'organize_pages': plan})
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ['doc.pdf'])

    def test_non_pdf_and_several_files_are_refused_and_name_never_overwrites(self):
        source = self.pdf(); other = self.pdf('b.pdf')
        with self.assertRaises(ConversionError): convert({'paths': [str(source), str(other)], 'target': T, 'organize_pages': ['1:0']})
        a = convert({'paths': [str(source)], 'target': T, 'organize_pages': ['1:0']}); b = convert({'paths': [str(source)], 'target': T, 'organize_pages': ['1:0']})
        self.assertNotEqual(a, b)

    def test_through_the_real_worker(self):
        out = runner.run_job({'paths': [str(self.pdf())], 'target': T, 'organize_pages': ['2:0', '1:90']})
        self.assertEqual(self.summary(out[0]), [(101, 0), (100, 90)])

    def test_report(self):
        text = ' '.join(engine.loss_report(['/x.pdf'], T, {'organize_pages': ['1:0', '1:0']}))
        self.assertIn('Marcadores', text); self.assertIn('duplicadas', text)


class BatchPreviewTests(Base):
    @NEEDS_PDFIUM
    def test_thumbs_start_at_first_and_validate(self):
        source = self.pdf(pages=30)
        result = runner.run_pdf_op({'op': 'pdf_preview', 'path': str(source), 'thumbs': 24, 'first': 25, 'page': 0})
        self.assertEqual([p['page'] for p in result['pages']], [25, 26, 27, 28, 29, 30])
        for bad in (0, 201, '1', True):
            with self.assertRaises(ValueError): runner.run_pdf_op({'op': 'pdf_preview', 'path': str(source), 'thumbs': 24, 'first': bad, 'page': 0})


@NEEDS_PDFIUM
class OrganizerWidgetTests(Base):
    def widget(self, pages=5):
        widget = PageOrganizer(); widget.loader = lambda job: runner.run_pdf_op(job); self.addCleanup(widget.shutdown)
        widget.load(str(self.pdf(pages=pages))); APP.processEvents(); return widget

    def test_loads_every_page_in_batches(self):
        widget = self.widget(30)
        self.assertEqual(widget.page_count, 30); self.assertEqual(widget.list.count(), 30); self.assertEqual(len(widget._pixmaps), 30)
        self.assertEqual(widget.option_value()[:2], ['1:0', '2:0']); self.assertFalse(widget.is_modified())

    def test_rotate_delete_duplicate_move_and_reset(self):
        widget = self.widget(5)
        widget.list.item(1).setSelected(True); widget.rotate_selected(90); widget.rotate_selected(90)
        self.assertEqual(widget.option_value()[1], '2:180'); widget.rotate_selected(-270); self.assertEqual(widget.option_value()[1], '2:270')
        widget.duplicate_selected(); self.assertEqual(widget.option_value(), ['1:0', '2:270', '2:270', '3:0', '4:0', '5:0'])
        self.assertIn('cópia', widget.list.item(2).text())
        widget.list.clearSelection(); widget.list.item(0).setSelected(True); widget.move_selected(1)
        self.assertEqual(widget.option_value()[:3], ['2:270', '1:0', '2:270']); self.assertEqual(widget.selected_rows(), [1])
        widget.move_selected(-1); widget.move_selected(-1); self.assertEqual(widget.selected_rows(), [0])       # parar no início
        widget.list.clearSelection(); widget.list.item(0).setSelected(True); widget.delete_selected()
        self.assertEqual(widget.option_value(), ['2:270', '2:270', '3:0', '4:0', '5:0']); self.assertIn('1 excluída', widget.summary.text())      # a página 1 saiu; a 2 continua duas vezes
        widget.reset(); self.assertFalse(widget.is_modified()); self.assertEqual(widget.list.count(), 5)

    def test_cannot_delete_everything_or_exceed_200(self):
        widget = self.widget(3)
        widget.select_all(); widget.delete_selected(); self.assertEqual(widget.list.count(), 3)
        big = self.widget(120); big.select_all(); big.duplicate_selected(); self.assertEqual(big.list.count(), 120)      # 240 passaria do limite: nada acontece

    def test_errors_are_shown_and_stale_answers_ignored(self):
        widget = PageOrganizer(); widget.loader = lambda job: runner.run_pdf_op(job); self.addCleanup(widget.shutdown)
        widget.load(str(self.root / 'nao-existe.pdf')); APP.processEvents()
        self.assertTrue(widget.error); self.assertEqual(widget.list.count(), 0)
        widget.load(str(self.pdf())); APP.processEvents(); self.assertEqual(widget.error, ''); self.assertEqual(widget.list.count(), 4)
        widget._apply(widget._token - 1, 1, {'info': {'error': 'velho'}}, '')          # resposta de um pedido antigo
        self.assertEqual(widget.error, '')


@NEEDS_PDFIUM
class PanelTests(Base):
    def controller(self):
        patcher = mock.patch.object(JobController, '_start_next'); patcher.start(); self.addCleanup(patcher.stop)
        return JobController(capabilities={'images': (True, 'ok'), 'pdf': (True, 'ok')})

    def panel(self):
        panel = FeaturePanel(self.controller()); panel.resize(1100, 760)
        panel.organizer.loader = lambda job: runner.run_pdf_op(job); self.addCleanup(panel.organizer.shutdown)
        panel.pdf_stage.loader = lambda job: runner.run_pdf_op(job); self.addCleanup(panel.pdf_stage.shutdown)
        return panel

    def test_stage_buttons_and_gate(self):
        panel = self.panel(); panel.set_files([str(self.pdf(pages=4))], T); APP.processEvents()
        self.assertEqual(panel.stage.currentIndex(), STAGE_ORGANIZE); self.assertEqual(panel.organizer.list.count(), 4)
        self.assertFalse(panel.run_button.isEnabled()); self.assertIn('Nada mudou', panel.org_info.text()); self.assertFalse(panel.org_left.isEnabled())
        panel.organizer.list.item(2).setSelected(True); APP.processEvents()
        self.assertTrue(panel.org_left.isEnabled()); panel.org_right.click(); APP.processEvents()
        self.assertTrue(panel.run_button.isEnabled()); self.assertEqual(panel.organizer.option_value()[2], '3:90')
        self.assertIn('4 páginas no PDF novo', panel.org_info.text()); self.assertEqual(panel.run_button.text(), 'Salvar PDF organizado')
        panel.org_reset.click(); APP.processEvents(); self.assertFalse(panel.run_button.isEnabled())

    def test_several_files_show_the_one_at_a_time_message(self):
        panel = self.panel(); panel.set_files([str(self.pdf()), str(self.pdf('b.pdf'))], T); APP.processEvents()
        self.assertIn('um PDF por vez', panel.preview_image.text()); self.assertFalse(panel.run_button.isEnabled()); self.assertEqual(panel.organizer.list.count(), 0)

    def test_switching_tools_does_not_reload_or_leak_edits(self):
        panel = self.panel(); source = str(self.pdf()); panel.set_files([source], T); APP.processEvents()
        panel.organizer.list.item(0).setSelected(True); panel.org_delete.click(); APP.processEvents()
        self.assertEqual(panel.organizer.list.count(), 3)
        panel.select_tool('Split PDF'); APP.processEvents(); self.assertEqual(panel.organizer.path, '')
        panel.select_tool(T); APP.processEvents(); self.assertEqual(panel.organizer.list.count(), 4)      # volta limpo, sem edição antiga


class ControllerTests(Base):
    def controller(self):
        patcher = mock.patch.object(JobController, '_start_next'); patcher.start(); self.addCleanup(patcher.stop)
        return JobController(capabilities={'images': (True, 'ok'), 'pdf': (True, 'ok')})

    def test_option_validation(self):
        a, b = str(self.pdf()), str(self.pdf('b.pdf'))
        c = self.controller(); self.assertTrue(c.start_job([a], T, {'organize_pages': ['1:90', '2:0']}))
        self.assertEqual(c.pending_jobs[0]['options']['organize_pages'], ['1:90', '2:0'])
        self.assertFalse(self.controller().start_job([a, b], T, {'organize_pages': ['1:0']}))
        for bad in ('1:0', ['1:0', 5], ['1:0'] * 201, ['1234567:0'], []):
            self.assertFalse(self.controller().start_job([a], T, {'organize_pages': bad}), msg=str(bad))
        self.assertFalse(self.controller().start_job([a], 'Split PDF', {'organize_pages': ['1:0']}))


if __name__ == '__main__':
    unittest.main()
