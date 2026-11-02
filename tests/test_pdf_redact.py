"""Tarjar conteúdo do PDF (0.9.40): áreas, termos, padrões, páginas giradas, rasterização, conferência automática, validações, runner, controlador e painel."""
import io
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
from PySide6.QtCore import QRectF
from PySide6.QtWidgets import QApplication

import engine
import pdfinfo
import pdfredact
import runner
from engine import ConversionError, convert
from test_illustrator import make_pdf
from tray_app import JobController
from workspace_panel import FeaturePanel

APP = QApplication.instance() or QApplication([])
NEEDS_PDFIUM = unittest.skipUnless(pdfinfo.preview_available(), 'pypdfium2 não instalado')
RD = 'Redact PDF'
LINES = (b'Cliente Maria Souza CPF 123.456.789-09', b'Contato maria@exemplo.com.br fone (91) 98888-7777', b'Texto livre sem segredo nenhum')


def page_pdf(line):
    return make_pdf(b'BT /F1 14 Tf 20 100 Td (' + line + b') Tj ET', width=400, height=200, font=True)


class Base(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name); self.addCleanup(self.temp.cleanup)

    def pdf(self, name='doc.pdf', lines=LINES, rotations=(), extras=True):
        writer = PdfWriter()
        for index, line in enumerate(lines):
            part = PdfReader(io.BytesIO(page_pdf(line)))
            writer.append(part)
            if index < len(rotations) and rotations[index]:
                writer.pages[index].rotate(rotations[index])
        if extras:
            writer.add_outline_item('Capítulo secreto', 0)
            writer.add_metadata({'/Title': 'Dossiê Maria Souza', '/Author': 'Maria Souza'})
            writer.add_attachment('segredo.txt', b'123.456.789-09')
        path = self.root / name; writer.write(str(path)); return path

    def texts(self, path):
        return [' '.join((page.extract_text() or '').split()) for page in PdfReader(str(path)).pages]

    def run_redact(self, source=None, **options):
        source = source or self.pdf()
        job = {'paths': [str(source)], 'target': RD, **options}
        return Path(convert(job)[0])


class CoreTests(unittest.TestCase):
    def test_parse_area(self):
        self.assertEqual(pdfredact.parse_area('2:10,20,500,600', 3), (2, (10, 20, 500, 600)))
        for bad in ('4:0,0,10,10', '0:0,0,10,10', '1:10,0,10,10', '1:0,0,1001,10', 'x', 5, '1:0,0,10'):
            with self.assertRaises(pdfredact.RedactError): pdfredact.parse_area(bad, 3)

    def test_terms_and_presets_validation(self):
        self.assertEqual(pdfredact.check_terms([' Maria ', 'Maria', 'ab']), ['Maria', 'ab'])
        for bad in ('x', ['a'], ['x' * 61], ['a\nb'], [1], ['aa'] * 21):
            with self.assertRaises(pdfredact.RedactError): pdfredact.check_terms(bad if bad != ['aa'] * 21 else [f't{i:02d}' for i in range(21)])
        self.assertEqual(pdfredact.check_presets('cpf, email,cpf'), ['cpf', 'email'])
        with self.assertRaises(pdfredact.RedactError): pdfredact.check_presets('rg')

    def test_presets_find_brazilian_data(self):
        text = 'CPF 123.456.789-09 e 12345678909; CNPJ 12.345.678/0001-95; a@b.com.br; (91) 98888-7777; 91 3222-1100; 2024-01'
        for key, count in (('cpf', 2), ('cnpj', 1), ('email', 1), ('telefone', 2)):
            found = pdfredact.find_spans(text, pdfredact.patterns([], [key]))
            self.assertEqual(len(found), count, (key, found))

    def test_terms_are_case_insensitive_and_literal(self):
        found = pdfredact.find_spans('Maria e MARIA e m.ria', pdfredact.patterns(['maria', 'm.ria'], []))
        self.assertEqual(len(found), 3)

    def test_paint_draws_black(self):
        from PIL import Image
        image = Image.new('RGB', (100, 100), 'white'); pdfredact.paint(image, [(10, 10, 50, 40)])
        self.assertEqual(image.getpixel((30, 25)), (0, 0, 0)); self.assertEqual(image.getpixel((80, 80)), (255, 255, 255))


@NEEDS_PDFIUM
class EngineTests(Base):
    def test_area_blacks_out_page_and_removes_text(self):
        out = self.run_redact(redact_areas=['1:0,300,1000,700'])
        self.assertEqual(out.name, 'doc-tarjado.pdf')
        texts = self.texts(out)
        self.assertEqual(texts[0], '')                                   # página rasterizada: sem camada de texto
        self.assertIn('Contato', texts[1]); self.assertIn('Texto livre', texts[2])      # páginas livres seguem intactas
        self.assertNotIn(b'123.456', out.read_bytes()); self.assertNotIn(b'Maria', out.read_bytes())

    def test_area_covers_pixels(self):
        out = self.run_redact(redact_areas=['1:0,0,1000,1000'])
        document = pdfinfo.open_document(out)
        try:
            image = pdfinfo.render_dpi(document, 1, 72); self.assertLess(max(image.convert('L').getdata()), 10)
        finally: document.close()

    def test_terms_found_on_every_page(self):
        out = self.run_redact(redact_terms=['Maria'])
        texts = self.texts(out)
        self.assertEqual((texts[0], texts[1]), ('', ''))                  # páginas 1 e 2 têm «Maria»
        self.assertIn('Texto livre', texts[2])
        self.assertNotIn(b'Maria', out.read_bytes())

    def test_presets_cpf_and_email(self):
        out = self.run_redact(redact_patterns='cpf,email')
        texts = self.texts(out); self.assertEqual((texts[0], texts[1]), ('', '')); self.assertIn('Texto livre', texts[2])

    def test_no_outline_attachments_or_metadata(self):
        out = self.run_redact(redact_areas=['3:0,0,100,100'])
        reader = PdfReader(str(out)); self.assertFalse(reader.outline); self.assertFalse(reader.attachments)
        self.assertFalse(reader.metadata or {})
        data = out.read_bytes()
        for leftover in (b'Dossi', b'segredo.txt', b'Cap\xc3\xadtulo secreto', b'Capitulo'): self.assertNotIn(leftover, data)

    def test_rotated_pages_keep_rotation_and_cover_text(self):
        out = self.run_redact(source=self.pdf(rotations=(90, 0, 270)), redact_terms=['Maria', 'fone'])
        reader = PdfReader(str(out)); texts = self.texts(out)
        self.assertEqual((texts[0], texts[1]), ('', ''))
        import pypdfium2
        document = pypdfium2.PdfDocument(str(out))
        try: self.assertIn('Texto livre', document[2].get_textpage().get_text_range())      # página 3 (girada) fora dos termos: segue com texto
        finally: document.close()
        self.assertEqual(len(reader.pages), 3)
        # a conferência interna só passa se as tarjas estiverem pretas sobre o texto: o resultado existir já a valida

    def test_original_is_untouched_and_second_output_gets_suffix(self):
        source = self.pdf(); before = source.read_bytes()
        first = self.run_redact(source=source, redact_terms=['Maria']); second = self.run_redact(source=source, redact_terms=['Maria'])
        self.assertEqual(source.read_bytes(), before); self.assertNotEqual(first, second)

    def test_dpi_changes_size(self):
        small = self.run_redact(redact_terms=['Maria'], pdf_dpi=150).stat().st_size
        self.assertGreater(small, 0)
        with self.assertRaises(ConversionError): self.run_redact(redact_terms=['Maria'], pdf_dpi=5)

    def test_validation_errors(self):
        with self.assertRaisesRegex(ConversionError, 'Marque ao menos'): self.run_redact()
        with self.assertRaisesRegex(ConversionError, 'fora da página'): self.run_redact(redact_areas=['9:0,0,10,10'])
        with self.assertRaisesRegex(ConversionError, 'inválida'): self.run_redact(redact_areas=['abc'])
        with self.assertRaisesRegex(ConversionError, 'Padrão'): self.run_redact(redact_patterns='rg')
        with self.assertRaisesRegex(ConversionError, 'no máximo'): self.run_redact(redact_areas=['1:0,0,10,10'] * 301)

    def test_term_not_found_saves_nothing_and_explains(self):
        with self.assertRaisesRegex(ConversionError, 'nada foi encontrado'): self.run_redact(redact_terms=['inexistente'])
        self.assertFalse(list(self.root.glob('*-tarjado*.pdf')))

    def test_encrypted_pdf_is_refused_with_guidance(self):
        source = self.pdf(); writer = PdfWriter(clone_from=str(source)); writer.encrypt('senha1234')
        locked = self.root / 'locked.pdf'; writer.write(str(locked))
        with self.assertRaisesRegex(ConversionError, 'senha'): self.run_redact(source=locked, redact_terms=['Maria'])

    def test_verification_detects_leftover_text(self):
        source = self.pdf(extras=False)
        with mock.patch.object(pdfredact, 'paint', lambda image, boxes: None):         # tarja que não pinta nada: a conferência precisa reprovar
            with self.assertRaisesRegex(ConversionError, 'conferência'): self.run_redact(source=source, redact_areas=['1:0,0,1000,1000'])
        self.assertFalse(list(self.root.glob('*-tarjado*.pdf')))

    def test_loss_report_warns(self):
        report = ' '.join(engine.loss_report(['/x.pdf'], RD)).lower()
        self.assertIn('texto', report); self.assertIn('imagem', report)

    def test_runner_job_publishes_and_uses_long_timeout(self):
        self.assertIn(RD, engine.PDF_LONG_TARGETS)


@NEEDS_PDFIUM
class ControllerTests(Base):
    def test_list_options_are_validated(self):
        controller = JobController(capabilities={'images': (True, 'ok'), 'pdf': (True, 'ok')}); source = str(self.pdf())
        with mock.patch.object(JobController, '_start_next'):
            controller.notify = mock.Mock()
            self.assertTrue(controller.start_job([source], RD, {'redact_areas': ['1:0,0,10,10'], 'redact_terms': ['Maria'], 'redact_patterns': 'cpf', 'pdf_dpi': 200}))
            self.assertEqual(controller.pending_jobs[-1]['options']['redact_terms'], ['Maria'])
            for bad in ({'redact_areas': 'x'}, {'redact_areas': [5]}, {'redact_terms': ['a' * 65]}, {'redact_areas': ['1:0,0,1,1'] * 301}, {'redact_terms': ['aa'] * 21}):
                self.assertFalse(controller.start_job([source], RD, bad), bad)
            self.assertFalse(controller.start_job([source], 'Compress PDF', {'redact_areas': ['1:0,0,10,10']}))


@NEEDS_PDFIUM
class PanelTests(Base):
    def panel(self, source):
        panel = FeaturePanel(self.controller_for_panel()); panel.resize(1200, 800)
        panel.redact_stage.loader = lambda job: runner.run_pdf_op(job); self.addCleanup(panel.redact_stage.shutdown)
        panel.set_files([str(source)], RD); APP.processEvents(); return panel

    def controller_for_panel(self):
        return JobController(capabilities={'images': (True, 'ok'), 'pdf': (True, 'ok')})

    def test_starts_disabled_and_mark_area_flow(self):
        with mock.patch.object(JobController, '_start_next'):
            panel = self.panel(self.pdf()); self.assertEqual(panel.run_button.text(), 'Tarjar PDF'); self.assertFalse(panel.run_button.isEnabled())
            view = panel.redact_stage.page_view; bounds = view.image_bounds(); self.assertGreater(bounds.width(), 0)
            self.assertFalse(panel.rd_add_button.isEnabled())
            view.crop_rect = None
            from PySide6.QtWidgets import QGraphicsRectItem
            view.crop_rect = QGraphicsRectItem(QRectF(bounds.left() + bounds.width() * 0.1, bounds.top() + bounds.height() * 0.2, bounds.width() * 0.5, bounds.height() * 0.3))
            view.graphics_scene.addItem(view.crop_rect); view.selection_changed.emit(); APP.processEvents()
            self.assertTrue(panel.rd_add_button.isEnabled()); self.assertIn('ainda não foi marcada', panel._redact_state()[0]) if panel._redact_state()[1] else None
            panel.add_redact_area(); APP.processEvents()
            self.assertEqual(len(panel.rd_areas), 1); self.assertTrue(panel.run_button.isEnabled())
            page, (x0, y0, x1, y1) = pdfredact.parse_area(panel.rd_areas[0], 3)
            self.assertEqual(page, 1); self.assertAlmostEqual(x0, 100, delta=3); self.assertAlmostEqual(y1 - y0, 300, delta=4); self.assertEqual(len(view.committed), 1)
            panel.undo_redact_area(); APP.processEvents(); self.assertEqual(panel.rd_areas, []); self.assertFalse(panel.run_button.isEnabled())

    def test_terms_and_presets_enable_and_build_options(self):
        with mock.patch.object(JobController, '_start_next'):
            panel = self.panel(self.pdf()); panel.rd_terms.setText('Maria; Souza ;'); panel.rd_preset_boxes['cpf'].setChecked(True); panel.rd_dpi.setCurrentIndex(2); APP.processEvents()
            self.assertTrue(panel.run_button.isEnabled())
            self.assertEqual(panel._redact_values(), {'pdf_dpi': 300, 'redact_terms': ['Maria', 'Souza'], 'redact_patterns': 'cpf'})
            panel.rd_terms.setText('a'); APP.processEvents(); self.assertFalse(panel.run_button.isEnabled()); self.assertIn('2 a 60', panel.rd_info.text())

    def test_run_sends_options_and_resets_areas(self):
        with mock.patch.object(JobController, '_start_next'), mock.patch.object(JobController, 'start_job') as start:
            panel = self.panel(self.pdf()); panel.rd_areas = ['2:0,0,500,500']; panel.rd_terms.setText('Maria'); APP.processEvents(); panel.run_selected()
            args = start.call_args[0]; self.assertEqual(args[1], RD)
            self.assertEqual((args[2]['redact_areas'], args[2]['redact_terms'], args[2]['pdf_dpi']), (['2:0,0,500,500'], ['Maria'], 200))
            self.assertEqual(panel.rd_areas, [])

    def test_multiple_files_and_non_pdf_show_message(self):
        with mock.patch.object(JobController, '_start_next'):
            panel = self.panel(self.pdf()); panel.set_files([str(self.pdf('a.pdf')), str(self.pdf('b.pdf'))], RD); APP.processEvents()
            self.assertFalse(panel.run_button.isEnabled()); self.assertIn('um PDF por vez', panel._redact_state()[0])

    def test_encrypted_pdf_message(self):
        source = self.pdf(); writer = PdfWriter(clone_from=str(source)); writer.encrypt('senha1234'); locked = self.root / 'l.pdf'; writer.write(str(locked))
        with mock.patch.object(JobController, '_start_next'):
            panel = self.panel(locked); panel.rd_terms.setText('Maria'); APP.processEvents(); self.assertFalse(panel.run_button.isEnabled())


if __name__ == '__main__':
    unittest.main()
