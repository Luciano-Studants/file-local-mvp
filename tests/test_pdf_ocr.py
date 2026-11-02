"""OCR de PDF digitalizado (0.9.35): PDF pesquisável e texto, páginas, páginas que já têm texto, limite, erros, runner, relatório, controlador e painel."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from PIL import Image, ImageDraw, ImageFont
from pypdf import PdfReader
from PySide6.QtWidgets import QApplication

import engine
import ocr
import pdfinfo
import runner
from engine import ConversionError, convert
from test_illustrator import make_pdf
from tray_app import JobController
from workspace_panel import FeaturePanel

APP = QApplication.instance() or QApplication([])
READY = ocr.status()[0] and 'eng' in ocr.available_languages() and pdfinfo.preview_available()
NEEDS_OCR = unittest.skipUnless(READY, 'Tesseract (eng) ou pypdfium2 indisponível')
PDF, TXT = 'PDF OCR → PDF', 'PDF OCR → Text'
FONT = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'


def scan_page(word):
    image = Image.new('RGB', (1240, 1754), 'white'); draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(FONT, 44) if os.path.exists(FONT) else ImageFont.load_default(44)
    for row in range(6):
        draw.text((100, 150 + row * 90), f'{word} report line {row + 1}', fill='black', font=font)
    return image


class Base(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name); self.addCleanup(self.temp.cleanup)

    def scan(self, name='scan.pdf', words=('Monthly', 'Quarterly')):
        path = self.root / name; pages = [scan_page(w) for w in words]
        pages[0].save(path, save_all=True, append_images=pages[1:], resolution=150); return path

    def blank_scan(self):
        path = self.root / 'blank.pdf'; Image.new('RGB', (800, 1000), 'white').save(path, resolution=150); return path

    def text_pdf(self):
        path = self.root / 'texto.pdf'
        path.write_bytes(make_pdf(b'BT /F1 24 Tf 10 40 Td (Ola mundo texto existente aqui) Tj ET', font=True, pages=1, width=400, height=100)); return path


@NEEDS_OCR
class EngineTests(Base):
    def test_searchable_pdf_keeps_page_count_and_gets_text(self):
        out = convert({'paths': [str(self.scan())], 'target': PDF, 'ocr_lang': 'eng'})
        self.assertEqual([Path(p).name for p in out], ['scan-pesquisavel.pdf'])
        reader = PdfReader(out[0]); self.assertEqual(len(reader.pages), 2)
        self.assertIn('Quarterly', reader.pages[1].extract_text()); self.assertIn('Monthly', reader.pages[0].extract_text())

    def test_page_range_only_keeps_selected_pages(self):
        out = convert({'paths': [str(self.scan())], 'target': PDF, 'ocr_lang': 'eng', 'pdf_pages': '2'})
        reader = PdfReader(out[0]); self.assertEqual(len(reader.pages), 1); self.assertIn('Quarterly', reader.pages[0].extract_text())

    def test_text_modes(self):
        source = str(self.scan())
        single = Path(convert({'paths': [source], 'target': TXT, 'ocr_lang': 'eng'})[0])
        self.assertEqual(single.name, 'scan-ocr.txt'); self.assertIn('Monthly', single.read_text(encoding='utf8'))
        marks = Path(convert({'paths': [source], 'target': TXT, 'ocr_lang': 'eng', 'text_mode': 'marks'})[0]).read_text(encoding='utf8')
        self.assertIn('--- Página 2 ---', marks)
        out = runner.run_job({'paths': [source], 'target': TXT, 'ocr_lang': 'eng', 'text_mode': 'pages', 'pdf_pages': '1-2'})
        self.assertEqual(sorted(Path(p).relative_to(self.root).as_posix() for p in out), ['scan - texto/pagina-001.txt', 'scan - texto/pagina-002.txt'])

    def test_pages_with_text_are_skipped_or_forced(self):
        source = str(self.text_pdf())
        with self.assertRaises(ConversionError) as ctx: convert({'paths': [source], 'target': PDF, 'ocr_lang': 'eng'})
        self.assertIn('já têm texto', str(ctx.exception))
        out = convert({'paths': [source], 'target': TXT, 'ocr_lang': 'eng', 'ocr_skip': 'off'})
        self.assertTrue(Path(out[0]).read_text(encoding='utf8').strip())

    def test_mixed_pdf_reuses_existing_text_page(self):
        scan = self.scan(words=('Monthly',)); text = self.text_pdf()
        from pypdf import PdfWriter
        writer = PdfWriter(); writer.append(str(text)); writer.append(str(scan))
        mixed = self.root / 'misto.pdf'; mixed.write_bytes(b''); writer.write(str(mixed))
        out = Path(convert({'paths': [str(mixed)], 'target': TXT, 'ocr_lang': 'eng', 'text_mode': 'marks'})[0]).read_text(encoding='utf8')
        self.assertIn('--- Página 1 ---', out); self.assertIn('Ola mundo', out); self.assertIn('Monthly', out)
        pdf = convert({'paths': [str(mixed)], 'target': PDF, 'ocr_lang': 'eng'})[0]
        self.assertEqual(len(PdfReader(pdf).pages), 2)

    def test_blank_pages_save_nothing(self):
        source = self.blank_scan(); before = sorted(p.name for p in self.root.iterdir())
        with self.assertRaises(ConversionError) as ctx: convert({'paths': [str(source)], 'target': TXT, 'ocr_lang': 'eng'})
        self.assertIn('Nenhum texto', str(ctx.exception)); self.assertEqual(sorted(p.name for p in self.root.iterdir()), before)

    def test_page_limit_and_invalid_options(self):
        many = self.root / 'many.pdf'; many.write_bytes(make_pdf(b'', pages=engine.PDF_OCR_MAX_PAGES + 1, width=100, height=100))
        with self.assertRaises(ConversionError) as ctx: convert({'paths': [str(many)], 'target': PDF, 'ocr_lang': 'eng', 'ocr_skip': 'off'})
        self.assertIn(f'limite é {engine.PDF_OCR_MAX_PAGES}', str(ctx.exception))
        source = str(self.scan())
        for bad in ({'ocr_skip': 'x'}, {'ocr_lang': 'xx'}, {'pdf_pages': '9'}, {'text_mode': 'zzz'}):
            with self.assertRaises(ConversionError, msg=str(bad)): convert({'paths': [source], 'target': TXT, **{'ocr_lang': 'eng', **bad}})

    def test_rejects_non_pdf(self):
        png = self.root / 'a.png'; Image.new('RGB', (10, 10)).save(png)
        with self.assertRaises(ConversionError): convert({'paths': [str(png)], 'target': PDF, 'ocr_lang': 'eng'})

    def test_runner_publishes_and_scales_timeout(self):
        out = runner.run_job({'paths': [str(self.scan())], 'target': PDF, 'ocr_lang': 'eng'})
        self.assertEqual([Path(p).name for p in out], ['scan-pesquisavel.pdf'])
        with mock.patch.object(runner, '_run_job', return_value=[]) as fake:
            try: runner.run_job({'paths': [str(self.scan())], 'target': PDF, 'ocr_lang': 'eng'})
            except Exception: pass
        self.assertGreaterEqual(fake.call_args.args[2], engine.PDF_OCR_TIMEOUT)


class StaticTests(Base):
    def test_operations_and_reports(self):
        self.assertIn(PDF, engine.OPERATIONS); self.assertIn(TXT, engine.OPERATIONS)
        text = ' '.join(engine.loss_report(['/x.pdf'], PDF)); self.assertIn('invisível', text); self.assertIn('Nada é enviado para a internet', text)
        self.assertIn('texto que já existe', ' '.join(engine.loss_report(['/x.pdf'], TXT)))
        self.assertEqual(engine.output_group_suffix({'target': TXT, 'text_mode': 'pages'}), engine.TEXT_FOLDER_SUFFIX)
        self.assertIsNone(engine.output_group_suffix({'target': TXT, 'text_mode': 'single'}))

    def test_without_tesseract_error_is_friendly(self):
        source = self.root / 's.pdf'; source.write_bytes(make_pdf(b'', pages=1, width=100, height=100))
        with mock.patch.object(ocr, 'check_ready', side_effect=ocr.OcrError('O Tesseract não foi encontrado.')):
            with self.assertRaises(ConversionError) as ctx: convert({'paths': [str(source)], 'target': PDF, 'ocr_skip': 'off'})
        self.assertIn('Tesseract', str(ctx.exception))

    def controller(self):
        patcher = mock.patch.object(JobController, '_start_next'); patcher.start(); self.addCleanup(patcher.stop)
        return JobController(capabilities={'images': (True, 'ok'), 'pdf': (True, 'ok')})

    def test_controller_option_types(self):
        source = str(self.text_pdf())
        self.assertTrue(self.controller().start_job([source], PDF, {'ocr_lang': 'eng', 'ocr_psm': 'auto', 'ocr_skip': 'off', 'pdf_pages': '1'}))
        self.assertTrue(self.controller().start_job([source], TXT, {'text_mode': 'pages', 'ocr_skip': 'on'}))
        for bad in ({'ocr_skip': 1}, {'ocr_lang': 5}, {'pdf_pages': 3}):
            self.assertFalse(self.controller().start_job([source], PDF, bad), msg=str(bad))


@unittest.skipUnless(pdfinfo.preview_available(), 'pypdfium2 não instalado')
class PanelTests(Base):
    def panel(self, source, tool):
        panel = FeaturePanel(JobController(capabilities={'images': (True, 'ok'), 'pdf': (True, 'ok')})); panel.resize(1100, 760)
        panel.pdf_stage.loader = lambda job: runner.run_pdf_op(job); self.addCleanup(panel.pdf_stage.shutdown)
        panel.set_files([str(source)], tool); APP.processEvents(); return panel

    def test_controls_and_values(self):
        with mock.patch.object(JobController, '_start_next'), mock.patch.object(ocr, 'status', return_value=(True, '')):
            panel = self.panel(self.text_pdf(), PDF)
            self.assertIn('1 página escolhida', panel.rocr_info.text()); self.assertEqual(panel.run_button.text(), 'Gerar PDF pesquisável')
            self.assertTrue(panel.run_button.isEnabled())
            panel.rocr_skip.setCurrentIndex(1); panel.rocr_pages.setText('1'); APP.processEvents()
            values = panel._pdfocr_values()
            self.assertEqual(values['ocr_skip'], 'off'); self.assertEqual(values['pdf_pages'], '1'); self.assertNotIn('text_mode', values)
            panel.rocr_pages.setText('9'); APP.processEvents(); self.assertFalse(panel.run_button.isEnabled())
            panel.set_files([str(self.text_pdf())], TXT); APP.processEvents()
            panel.rocr_text.setCurrentIndex(2); self.assertEqual(panel._pdfocr_values()['text_mode'], 'pages'); self.assertEqual(panel.run_button.text(), 'Reconhecer texto')

    def test_run_disabled_without_tesseract(self):
        with mock.patch.object(JobController, '_start_next'), mock.patch.object(ocr, 'status', return_value=(False, 'O Tesseract não foi encontrado.')):
            panel = self.panel(self.text_pdf(), PDF)
            self.assertFalse(panel.run_button.isEnabled()); self.assertIn('Tesseract', panel.rocr_info.text())


if __name__ == '__main__':
    unittest.main()
