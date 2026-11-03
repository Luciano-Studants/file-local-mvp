"""Numerar, cabeçalho/rodapé e marca d'água em PDF (0.9.38): texto, posições, páginas giradas, intervalo, opacidade, validações, runner, controlador e painel."""
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
import pdfstamp
import runner
from engine import ConversionError, convert
from tray_app import JobController
from workspace_panel import FeaturePanel

APP = QApplication.instance() or QApplication([])
NEEDS_PDFIUM = unittest.skipUnless(pdfinfo.preview_available(), 'pypdfium2 não instalado')
ST = 'Stamp PDF'


class Base(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name); self.addCleanup(self.temp.cleanup)

    def pdf(self, name='doc.pdf', pages=5, rotations=()):
        writer = PdfWriter()
        for index in range(pages):
            page = writer.add_blank_page(595, 842)
            if index < len(rotations) and rotations[index]: page.rotate(rotations[index])
        path = self.root / name; writer.write(str(path)); return path

    def texts(self, path):
        return [' '.join(page.extract_text().split()) for page in PdfReader(str(path)).pages]


class CoreTests(unittest.TestCase):
    def test_width_and_expand(self):
        self.assertAlmostEqual(pdfstamp.text_width('iii', 10), 10 * 3 * 222 / 1000, places=1)
        self.assertGreater(pdfstamp.text_width('WWW', 10, bold=True), pdfstamp.text_width('iii', 10))
        self.assertEqual(pdfstamp.expand('{n}/{total} {x}', 3, 9), '3/9 {x}')

    def test_encoding_limits(self):
        self.assertEqual(pdfstamp.encode('ação é ñ'), 'ação é ñ'.encode('cp1252'))
        with self.assertRaises(pdfstamp.StampError): pdfstamp.encode('漢字')

    def test_diagonal_only_in_center(self):
        page = PdfWriter().add_blank_page(100, 100); geometry = pdfstamp.visible_geometry(page)
        with self.assertRaises(pdfstamp.StampError): pdfstamp.stamp_content(geometry, 'x', position='bc', size=10, bold=False, color='#000000', opacity=100, margin_mm=5, angle=45)

    def test_geometry_with_rotation(self):
        writer = PdfWriter(); page = writer.add_blank_page(300, 200); page.rotate(90)
        geometry = pdfstamp.visible_geometry(page); self.assertEqual(geometry[4], 90); self.assertEqual(pdfstamp.visible_size(geometry), (200, 300))


class EngineTests(Base):
    def test_default_numbers_all_pages_and_keeps_original(self):
        source = self.pdf(); out = Path(convert({'paths': [str(source)], 'target': ST})[0])
        self.assertEqual(out.name, 'doc-numerado.pdf')
        self.assertEqual(self.texts(out), [f'Página {n} de 5' for n in range(1, 6)]); self.assertEqual(self.texts(source), [''] * 5)

    def test_range_start_and_total(self):
        out = Path(convert({'paths': [str(self.pdf())], 'target': ST, 'pdf_pages': '2-3', 'stamp_start': 11, 'stamp_text': '{n}/{total}'})[0])
        self.assertEqual(self.texts(out), ['', '12/15', '13/15', '', ''])

    def test_header_text_and_bold(self):
        out = Path(convert({'paths': [str(self.pdf())], 'target': ST, 'stamp_text': 'Relatório interno ação', 'stamp_position': 'tc', 'stamp_bold': 'on', 'pdf_pages': '1'})[0])
        self.assertEqual(out.name, 'doc-carimbado.pdf'); self.assertEqual(self.texts(out)[0], 'Relatório interno ação'); self.assertIn(b'/Helvetica-Bold', out.read_bytes())

    def test_watermark_defaults_and_opacity(self):
        out = Path(convert({'paths': [str(self.pdf())], 'target': ST, 'stamp_kind': 'watermark', 'stamp_text': 'RASCUNHO'})[0])
        self.assertEqual(out.name, 'doc-marcadagua.pdf'); self.assertEqual(self.texts(out)[0], 'RASCUNHO'); data = out.read_bytes()
        self.assertIn(b'/ca 0.25', data); self.assertLess(out.stat().st_size, 20000)

    @NEEDS_PDFIUM
    def test_rotated_pages_draw_where_they_should(self):
        out = Path(convert({'paths': [str(self.pdf(pages=4, rotations=(0, 90, 180, 270)))], 'target': ST, 'stamp_text': 'MARCA', 'stamp_position': 'bc', 'stamp_size': 30})[0])
        import pypdfium2 as pdfium
        document = pdfium.PdfDocument(str(out)); self.addCleanup(document.close)      # no Windows um arquivo aberto não pode ser apagado
        for index in range(4):
            image = document[index].render(scale=0.5).to_pil().convert('L'); width, height = image.size
            dark = [(x, y) for y in range(height) for x in range(width) if image.getpixel((x, y)) < 128]
            self.assertTrue(dark, msg=f'página {index + 1} sem carimbo')
            mean_x = sum(x for x, _y in dark) / len(dark); mean_y = sum(y for _x, y in dark) / len(dark)
            self.assertAlmostEqual(mean_x / width, 0.5, delta=0.06); self.assertGreater(mean_y / height, 0.85)       # centro embaixo, como a pessoa vê

    def test_keeps_bookmarks_and_attachments(self):
        writer = PdfWriter(clone_from=PdfReader(str(self.pdf()))); writer.add_outline_item('Capítulo', 0); writer.add_attachment('nota.txt', b'x')
        source = self.root / 'rico.pdf'; writer.write(str(source))
        out = Path(convert({'paths': [str(source)], 'target': ST})[0]); reader = PdfReader(str(out))
        self.assertEqual([item.title for item in reader.outline], ['Capítulo']); self.assertIn('/EmbeddedFiles', reader.trailer['/Root']['/Names'])

    def test_validation_errors(self):
        source = str(self.pdf()); before = sorted(p.name for p in self.root.iterdir())
        for bad in ({'stamp_kind': 'x'}, {'stamp_text': ''}, {'stamp_text': '漢字'}, {'stamp_text': 'a' * 101}, {'stamp_position': 'zz'}, {'stamp_size': 1}, {'stamp_opacity': 0},
                    {'stamp_margin': 99}, {'stamp_start': 0}, {'stamp_color': 'red'}, {'stamp_bold': 'x'}, {'stamp_angle': 45}, {'pdf_pages': '9'},
                    {'stamp_kind': 'watermark', 'stamp_position': 'bc', 'stamp_angle': 45}, {'stamp_angle': 30}):
            with self.assertRaises(ConversionError, msg=str(bad)): convert({'paths': [source], 'target': ST, **bad})
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), before)
        (self.root / 'a.txt').write_text('x')
        with self.assertRaises(ConversionError): convert({'paths': [str(self.root / 'a.txt')], 'target': ST})

    def test_runner_and_reports(self):
        out = runner.run_job({'paths': [str(self.pdf())], 'target': ST}); self.assertEqual([Path(p).name for p in out], ['doc-numerado.pdf'])
        self.assertIn('não serve como proteção', ' '.join(engine.loss_report(['/x.pdf'], ST, {'stamp_kind': 'watermark'})))
        self.assertIn('Assinaturas digitais', ' '.join(engine.loss_report(['/x.pdf'], ST))); self.assertIn(ST, engine.OPERATIONS)

    def controller(self):
        patcher = mock.patch.object(JobController, '_start_next'); patcher.start(); self.addCleanup(patcher.stop)
        return JobController(capabilities={'images': (True, 'ok'), 'pdf': (True, 'ok')})

    def test_controller_option_types(self):
        source = str(self.pdf())
        self.assertTrue(self.controller().start_job([source], ST, {'stamp_kind': 'text', 'stamp_text': 'x', 'stamp_size': 12, 'stamp_opacity': 50, 'stamp_margin': 5, 'stamp_angle': 0, 'stamp_start': 1, 'stamp_color': '#112233', 'stamp_bold': 'on', 'stamp_position': 'tc'}))
        for bad in ({'stamp_size': '12'}, {'stamp_text': 3}, {'stamp_angle': 'x'}):
            self.assertFalse(self.controller().start_job([source], ST, bad), msg=str(bad))


@NEEDS_PDFIUM
class PanelTests(Base):
    def panel(self, source):
        panel = FeaturePanel(JobController(capabilities={'images': (True, 'ok'), 'pdf': (True, 'ok')})); panel.resize(1100, 760)
        panel.pdf_stage.loader = lambda job: runner.run_pdf_op(job); self.addCleanup(panel.pdf_stage.shutdown)
        panel.set_files([str(source)], ST); APP.processEvents(); return panel

    def test_numbering_defaults_and_example(self):
        with mock.patch.object(JobController, '_start_next'):
            panel = self.panel(self.pdf()); self.assertIn('«Página 1 de 5» em 5 páginas', panel.st_info.text()); self.assertTrue(panel.run_button.isEnabled())
            self.assertEqual(panel.run_button.text(), 'Aplicar carimbo'); values = panel._stamp_values()
            self.assertEqual((values['stamp_kind'], values['stamp_position'], values['stamp_size'], values['stamp_angle']), ('text', 'bc', 10, 0))
            panel.st_pages.setText('2-'); panel.st_start.setValue(10); APP.processEvents(); self.assertIn('«Página 11 de 14» em 4 páginas (a primeira é a 2)', panel.st_info.text())

    def test_kinds_change_defaults_and_fields(self):
        with mock.patch.object(JobController, '_start_next'):
            panel = self.panel(self.pdf()); panel.st_kind.setCurrentIndex(2); APP.processEvents()
            values = panel._stamp_values(); self.assertEqual((values['stamp_kind'], values['stamp_text'], values['stamp_position'], values['stamp_angle'], values['stamp_opacity']), ('watermark', 'CONFIDENCIAL', 'c', 45, 25))
            self.assertIn('sangle', panel._stamp_fields()); self.assertNotIn('smargin', panel._stamp_fields())
            panel.st_position.setCurrentIndex(7); APP.processEvents(); self.assertEqual(panel._stamp_values()['stamp_angle'], 0); self.assertNotIn('sangle', panel._stamp_fields())
            panel.st_kind.setCurrentIndex(1); APP.processEvents(); self.assertEqual(panel.st_text.text(), ''); self.assertFalse(panel.run_button.isEnabled())
            panel.st_text.setText('漢字'); APP.processEvents(); self.assertFalse(panel.run_button.isEnabled()); self.assertIn('letras latinas', panel.st_info.text())
            panel.st_text.setText('Interno'); panel.st_pages.setText('99'); APP.processEvents(); self.assertFalse(panel.run_button.isEnabled())


if __name__ == '__main__':
    unittest.main()
