"""Prévia de PDF no painel (0.9.29): resumo, página grande, miniaturas e lista de vários arquivos.

A leitura usa o worker real, chamado de forma síncrona (`stage.loader`): os testes não iniciam threads de segundo plano.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from pypdf import PdfWriter
from PySide6.QtWidgets import QApplication

import pdfinfo
import runner
import workspace_panel
from pdf_stage import PdfLoadTask, PdfStage
from test_illustrator import make_pdf
from tray_app import JobController
from workspace_panel import FeaturePanel, STAGE_MESSAGE, STAGE_PDF

APP = QApplication.instance() or QApplication([])
NEEDS_PDFIUM = unittest.skipUnless(pdfinfo.preview_available(), 'pypdfium2 não instalado')


class StageBase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name); self.addCleanup(self.temp.cleanup)
        self.jobs = []

    def sync_loader(self, job):
        self.jobs.append(dict(job)); return runner.run_pdf_op(job)

    def pdf(self, name, pages=3):
        path = self.root / name; path.write_bytes(make_pdf(pages=pages)); return str(path)

    def stage(self):
        stage = PdfStage(); stage.loader = self.sync_loader; stage.resize(600, 500); stage.show(); APP.processEvents()
        self.addCleanup(stage.shutdown); return stage


@NEEDS_PDFIUM
class StageTests(StageBase):
    def test_single_pdf_shows_summary_page_and_thumbnails(self):
        stage = self.stage(); stage.show_files([self.pdf('a.pdf')]); APP.processEvents()
        self.assertIn('3 páginas', stage.summary.text())
        self.assertEqual(stage.thumbs.count(), 3); self.assertFalse(stage.thumbs.isHidden()); self.assertTrue(stage.files.isHidden())
        self.assertGreater(stage.page_view.pixmap_item.pixmap().width(), 100)
        self.assertEqual(self.jobs[0]['op'], 'pdf_preview'); self.assertEqual((self.jobs[0]['page'], self.jobs[0]['thumbs']), (1, pdfinfo.MAX_PREVIEW_PAGES))
        self.assertEqual(stage.thumbs.currentRow(), 0)

    def test_choosing_a_thumbnail_loads_that_page_without_reloading_thumbnails(self):
        stage = self.stage(); stage.show_files([self.pdf('a.pdf')]); self.jobs.clear()
        shown = []; stage.page_shown.connect(shown.append)
        stage.thumbs.setCurrentRow(2); APP.processEvents()
        self.assertEqual(len(self.jobs), 1); self.assertEqual((self.jobs[0]['page'], self.jobs[0]['thumbs']), (3, 0))
        self.assertEqual(shown, [3]); self.assertEqual(stage.thumbs.count(), 3); self.assertEqual(stage.thumbs.currentRow(), 2)

    def test_many_pdfs_show_a_list_with_pages_and_errors_and_open_the_first_readable(self):
        good, other = self.pdf('a.pdf', 2), self.pdf('b.pdf', 5)
        broken = self.root / 'ruim.pdf'; broken.write_bytes(b'nao sou pdf')
        writer = PdfWriter(); writer.add_blank_page(100, 100); writer.encrypt('x')
        locked = self.root / 'locked.pdf'
        with locked.open('wb') as handle: writer.write(handle)
        stage = self.stage(); stage.show_files([str(broken), str(locked), good, other]); APP.processEvents()
        self.assertFalse(stage.files.isHidden()); self.assertEqual(stage.files.count(), 4)
        texts = [stage.files.item(i).text() for i in range(4)]
        self.assertIn('cabeçalho', texts[0]); self.assertIn('protegido por senha', texts[1]); self.assertIn('2 páginas', texts[2]); self.assertIn('5 páginas', texts[3])
        self.assertIn('2 com problema', stage.totals.text()); self.assertIn('7 páginas no total', stage.totals.text()); self.assertFalse(stage.totals.isHidden())
        self.assertEqual(stage.files.currentRow(), 2); self.assertEqual(stage.current_path, good); self.assertEqual(stage.thumbs.count(), 2)
        stage.files.setCurrentRow(3); APP.processEvents()
        self.assertEqual(stage.current_path, other); self.assertEqual(stage.thumbs.count(), 5)
        stage.files.setCurrentRow(1); APP.processEvents()                  # protegido: não pede prévia, só avisa
        self.assertEqual(stage.current_path, other); self.assertIn('senha', stage.summary.text())

    def test_old_responses_are_ignored(self):
        stage = self.stage(); stage.show_files([self.pdf('a.pdf')])
        summary = stage.summary.text(); old = stage._token - 1
        stage._apply(old, {'info': {'pages': 99, 'size_bytes': 1}, 'pages': []}, ''); stage._apply(old, None, 'erro velho')
        self.assertEqual(stage.summary.text(), summary)

    def test_a_failed_read_shows_the_message_and_keeps_the_stage_usable(self):
        stage = self.stage()
        stage.loader = lambda job: (_ for _ in ()).throw(ValueError('O worker de conversão parou: limite de tempo de CPU.'))
        stage.show_files([self.pdf('a.pdf')]); APP.processEvents()
        self.assertIn('limite de tempo de CPU', stage.summary.text()); self.assertEqual(stage.thumbs.count(), 0)
        stage.loader = self.sync_loader; stage.show_files([self.pdf('b.pdf', 1)]); APP.processEvents()
        self.assertIn('1 página', stage.summary.text()); self.assertEqual(stage.thumbs.count(), 1)

    def test_without_files_the_stage_is_empty_and_clear(self):
        stage = self.stage(); stage.show_files([self.pdf('a.pdf')]); stage.show_files([])
        self.assertEqual(stage.thumbs.count(), 0); self.assertTrue(stage.thumbs.isHidden() and stage.files.isHidden()); self.assertIn('Abra um PDF', stage.summary.text())

    def test_more_than_the_thumbnail_limit_says_so(self):
        big = self.root / 'big.pdf'; writer = PdfWriter()
        for _ in range(30): writer.add_blank_page(60, 60)
        with big.open('wb') as handle: writer.write(handle)
        stage = self.stage(); stage.show_files([str(big)]); APP.processEvents()
        self.assertEqual(stage.thumbs.count(), pdfinfo.MAX_PREVIEW_PAGES); self.assertFalse(stage.note.isHidden()); self.assertIn('24 primeiras páginas de 30', stage.note.text())
        stage.open_page(30); APP.processEvents()                            # páginas além das miniaturas continuam acessíveis pelo pedido direto
        self.assertEqual(self.jobs[-1]['page'], 30)


@NEEDS_PDFIUM
class PanelIntegrationTests(StageBase):
    def panel(self):
        controller = JobController(capabilities={'images': (True, 'ok'), 'pdf': (True, 'ok')}); panel = FeaturePanel(controller)
        panel.pdf_stage.loader = self.sync_loader; panel.resize(1000, 700); panel.show(); APP.processEvents()
        self.addCleanup(panel.pdf_stage.shutdown); return panel

    def test_pdf_tools_open_on_the_page_preview(self):
        panel = self.panel(); panel.set_files([self.pdf('a.pdf')], 'PDF → Text'); APP.processEvents()
        self.assertEqual(panel.stage.currentIndex(), STAGE_PDF); self.assertEqual(panel.pdf_stage.thumbs.count(), 3)
        self.assertIn('3 páginas', panel.pdf_stage.summary.text())
        panel.set_files([self.pdf('a.pdf'), self.pdf('b.pdf', 1)], 'Merge PDFs'); APP.processEvents()
        self.assertTrue(panel.pdf_stage.files.isHidden()); self.assertEqual(panel.pdf_stage.files.count(), 2)      # em «Unir» a ordem fica na lista do painel (0.9.31)
        self.assertEqual(panel.collage_list.count(), 2)

    def test_pdf_tool_without_files_shows_the_message(self):
        panel = self.panel(); panel.select_tool('Split PDF'); APP.processEvents()
        self.assertEqual(panel.stage.currentIndex(), STAGE_MESSAGE); self.assertIn('PDF', panel.preview_image.text())

    def test_image_tools_do_not_touch_the_pdf_stage(self):
        from PIL import Image
        panel = self.panel(); image = self.root / 'f.png'; Image.new('RGB', (40, 30), 'red').save(image)
        panel.set_files([str(image)], 'Resize → PNG'); APP.processEvents()
        self.assertNotEqual(panel.stage.currentIndex(), STAGE_PDF); self.assertEqual(self.jobs, [])

    def test_pdf_category_texts_mention_the_preview(self):
        self.assertIn('Ver páginas', workspace_panel.CATEGORIES['pdf'][1])


class ThreadTaskTests(unittest.TestCase):
    def test_load_task_reports_result_and_error_through_the_signal(self):
        got = []
        ok = PdfLoadTask(7, {'op': 'x'}, loader=lambda job: {'echo': job['op']}); ok.finished_with.connect(lambda t, r, e: got.append((t, r, e)))
        ok.start(); ok.wait(5000); APP.processEvents()
        failing = PdfLoadTask(8, {'op': 'x'}, loader=lambda job: (_ for _ in ()).throw(RuntimeError('quebrou')))
        failing.finished_with.connect(lambda t, r, e: got.append((t, r, e))); failing.start(); failing.wait(5000); APP.processEvents()
        self.assertEqual(got, [(7, {'echo': 'x'}, ''), (8, None, 'quebrou')])


if __name__ == '__main__':
    unittest.main()
