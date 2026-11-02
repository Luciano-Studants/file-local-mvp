"""PDF pesquisável de várias imagens (0.9.26): opção «Texto pesquisável (OCR)» do PDF único."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PIL import Image
from PySide6.QtWidgets import QApplication
from pypdf import PdfReader

import engine
import ocr
import quality_suite as qs
import tool_registry
from engine import ConversionError, convert, loss_report, onepdf_options_from
from tray_app import FeaturePanel, JobController

READY = ocr.status()[0] and {'por', 'eng'} <= ocr.available_languages()
needs_ocr = unittest.skipUnless(READY, 'Tesseract ou dados de idioma ausentes')
PAGES = (['Primeira página de teste', 'Conversão offline de arquivos'], ['Segunda página muito diferente', 'Olá, mundo 12345'])


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup); self.root = Path(self.tmp.name)
        self.paths = []
        for index, lines in enumerate(PAGES):
            path = self.root / f'p{index}.png'; qs.make_text_image(lines, width=900).save(path); self.paths.append(path)
        self.blank = self.root / 'branca.png'; Image.new('RGB', (900, 300), 'white').save(self.blank)
        self.out = self.root / 'saida'; self.out.mkdir()

    def run_pdf(self, paths, **extra):
        return Path(convert({'paths': [str(p) for p in paths], 'target': 'Images → One PDF', 'output': str(self.out), **extra})[0])


class OptionTests(Base):
    def test_defaults_and_validation(self):
        self.assertEqual(onepdf_options_from({})['ocr'], 'off'); self.assertEqual(onepdf_options_from({'pdf_ocr': 'por'})['ocr'], 'por')
        for bad in ({'pdf_ocr': 'fra'}, {'pdf_ocr': 3}, {'pdf_ocr': 'por', 'pdf_page': 'a4'}, {'pdf_ocr': 'por', 'pdf_page': 'letter'}):
            with self.assertRaises(ConversionError, msg=str(bad)): onepdf_options_from(bad)
        self.assertIn('pdf_ocr', tool_registry.BY_TARGET['Images → One PDF'].str_options)

    def test_without_tesseract_nothing_is_created(self):
        with patch.object(ocr, 'status', return_value=(False, 'O Tesseract não foi encontrado XYZ.')):
            with self.assertRaisesRegex(ConversionError, 'XYZ'): self.run_pdf(self.paths, pdf_ocr='por')
        self.assertEqual(list(self.out.iterdir()), [])

    def test_page_limit_with_ocr(self):
        many = [self.paths[0]] * (engine.PDF_OCR_MAX_PAGES + 1)
        with patch.object(ocr, 'status', return_value=(True, '')), patch.object(ocr, 'available_languages', return_value={'por', 'eng'}):
            with self.assertRaisesRegex(ConversionError, 'de 2 a 20'): self.run_pdf(many, pdf_ocr='por')
        self.assertEqual(list(self.out.iterdir()), [])

    def test_report_mentions_ocr_only_when_on(self):
        on = ' '.join(loss_report([str(p) for p in self.paths], 'Images → One PDF', {'pdf_ocr': 'por'})); off = ' '.join(loss_report([str(p) for p in self.paths], 'Images → One PDF', {}))
        self.assertIn('Texto pesquisável (OCR, Português)', on); self.assertIn('300 dpi', on); self.assertNotIn('Tesseract', off)


@needs_ocr
class RealOcrTests(Base):
    def test_three_pages_in_order_with_text_layer_and_blank_page(self):
        original = [p.read_bytes() for p in self.paths]
        pdf = self.run_pdf([self.paths[0], self.blank, self.paths[1]], pdf_ocr='por')
        pages = PdfReader(str(pdf)).pages; texts = [(page.extract_text() or '').strip() for page in pages]
        self.assertEqual(len(pages), 3)
        self.assertIn('Primeira', texts[0]); self.assertEqual(texts[1], ''); self.assertIn('Segunda', texts[2])
        self.assertEqual([p.read_bytes() for p in self.paths], original)
        self.assertEqual(sorted(p.name for p in self.out.iterdir()), [pdf.name])

    def test_page_size_follows_the_image_at_300_dpi(self):
        pdf = self.run_pdf(self.paths, pdf_ocr='por'); box = PdfReader(str(pdf)).pages[0].mediabox
        with Image.open(self.paths[0]) as handle: size = handle.size
        self.assertAlmostEqual(float(box.width), size[0] * 72 / 300, delta=1.5); self.assertAlmostEqual(float(box.height), size[1] * 72 / 300, delta=1.5)

    def test_worker_process(self):
        import runner
        result = runner.run_job({'paths': [str(p) for p in self.paths], 'target': 'Images → One PDF', 'output': str(self.out), 'pdf_ocr': 'por+eng'}, timeout=170)
        self.assertEqual(len(PdfReader(result[0]).pages), 2)


class PanelTests(Base):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make_panel(self):
        panel = FeaturePanel(JobController(capabilities={'images': (True, 'ok'), 'pdf': (True, 'ok')})); panel.set_files([str(p) for p in self.paths], 'Images → One PDF'); return panel

    def visible(self, panel):
        return {k for k, w in panel.form_fields.items() if panel.settings_form.isRowVisible(w)}

    def test_control_and_values(self):
        panel = self.make_panel(); self.assertIn('pocr', self.visible(panel)); self.assertEqual(panel._onepdf_values()['pdf_ocr'], 'off'); self.assertIn('quality', self.visible(panel))
        panel.pdf_ocr.setCurrentIndex(2); self.assertEqual(panel._onepdf_values()['pdf_ocr'], 'por'); self.assertNotIn('quality', self.visible(panel))

    def test_run_is_blocked_with_a_message_when_ocr_cannot_run(self):
        panel = self.make_panel(); panel.pdf_ocr.setCurrentIndex(1)
        with patch.object(ocr, 'status', return_value=(False, 'Sem Tesseract XYZ.')), patch.object(panel.controller, 'start_job') as start:
            panel._onepdf_changed(); self.assertFalse(panel.run_button.isEnabled()); self.assertIn('XYZ', panel.tool_hint.text())
            panel.run_selected(); start.assert_not_called(); self.assertIn('XYZ', panel.status.text())
        with patch.object(ocr, 'status', return_value=(True, '')):
            panel.pdf_page.setCurrentIndex(1); self.app.processEvents(); self.assertFalse(panel.run_button.isEnabled()); self.assertIn('Do tamanho da imagem', panel.tool_hint.text())

    def test_options_are_sent(self):
        panel = self.make_panel(); panel.pdf_ocr.setCurrentIndex(3)
        with patch.object(ocr, 'status', return_value=(True, '')), patch.object(panel.controller, 'start_job') as start:
            panel.run_selected(); options = start.call_args.args[2]; self.assertEqual(options['pdf_ocr'], 'eng')


if __name__ == '__main__':
    unittest.main()
