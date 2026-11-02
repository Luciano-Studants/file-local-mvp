"""Extrair texto (melhorado) e imagens embutidas (0.9.34): páginas, modos, PDF digitalizado, JPEG sem recomprimir, deduplicação, painel e controlador."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from PIL import Image
from PySide6.QtWidgets import QApplication

import engine
import pdfinfo
import runner
from engine import ConversionError, convert
from test_illustrator import make_pdf
from tray_app import JobController
from workspace_panel import FeaturePanel

APP = QApplication.instance() or QApplication([])
NEEDS_PDFIUM = unittest.skipUnless(pdfinfo.preview_available(), 'pypdfium2 não instalado')
TEXT = b'BT /F1 24 Tf 10 40 Td (Ola mundo teste) Tj ET'
TXT = 'PDF → Text'
IMG = 'Extract PDF Images'


class Base(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name); self.addCleanup(self.temp.cleanup)

    def text_pdf(self, name='texto.pdf', pages=2):
        path = self.root / name; path.write_bytes(make_pdf(TEXT, font=True, pages=pages, width=300, height=100)); return path      # só a página 1 tem texto

    def image_pdf(self, name='imagens.pdf'):
        """Páginas: 1 = foto JPEG 200×120, 2 = JPEG 90×90 azul, 3 = ícone 10×10, 4 = a mesma foto da página 1 de novo."""
        photo = Image.effect_noise((200, 120), 80).convert('RGB'); blue = Image.new('RGB', (90, 90), 'blue'); icon = Image.new('RGB', (10, 10), 'green')
        path = self.root / name; photo.save(path, save_all=True, append_images=[blue, icon, photo]); return path

    def names(self, outputs):
        return [Path(x).relative_to(self.root).as_posix() for x in outputs]


class TextTests(Base):
    def test_single_file_default_name(self):
        out = convert({'paths': [str(self.text_pdf())], 'target': TXT})
        self.assertEqual(self.names(out), ['texto-texto.txt']); self.assertIn('Ola mundo teste', Path(out[0]).read_text(encoding='utf8'))

    def test_page_marks(self):
        out = convert({'paths': [str(self.text_pdf())], 'target': TXT, 'text_mode': 'marks'})
        text = Path(out[0]).read_text(encoding='utf8'); self.assertIn('--- Página 1 ---', text); self.assertIn('--- Página 2 ---', text)

    def test_one_file_per_page_in_a_text_folder(self):
        out = convert({'paths': [str(self.text_pdf())], 'target': TXT, 'text_mode': 'pages'})
        self.assertEqual(self.names(out), ['texto - texto/pagina-001.txt', 'texto - texto/pagina-002.txt'])
        self.assertIn('Ola mundo', Path(out[0]).read_text(encoding='utf8')); self.assertEqual(Path(out[1]).read_text(encoding='utf8').strip(), '')

    def test_layout_mode_and_page_range(self):
        out = convert({'paths': [str(self.text_pdf())], 'target': TXT, 'text_layout': 'layout', 'pdf_pages': '1'})
        self.assertIn('Ola mundo teste', Path(out[0]).read_text(encoding='utf8'))

    def test_pdf_without_text_saves_nothing_and_explains(self):
        for source, options in ((self.root / 'blank.pdf', {}), (self.text_pdf(), {'pdf_pages': '2'})):
            if not source.exists():
                from pypdf import PdfWriter
                writer = PdfWriter(); writer.add_blank_page(100, 100)
                with source.open('wb') as handle: writer.write(handle)
            with self.assertRaisesRegex(ConversionError, 'não há texto.*OCR'): convert({'paths': [str(source)], 'target': TXT, **options})
        self.assertFalse(any('.txt' in p.name for p in self.root.rglob('*')))

    def test_invalid_options(self):
        source = str(self.text_pdf())
        for options, pattern in (({'text_mode': 'x'}, 'Modo'), ({'text_layout': 'x'}, 'layout'), ({'pdf_pages': '9'}, 'passa do fim'), ({'pdf_pages': 5}, 'inválido')):
            with self.assertRaisesRegex(ConversionError, pattern): convert({'paths': [source], 'target': TXT, **options})

    def test_real_worker_publishes_text_folder(self):
        out = runner.run_job({'paths': [str(self.text_pdf())], 'target': TXT, 'text_mode': 'pages'})
        self.assertEqual(self.names(out), ['texto - texto/pagina-001.txt', 'texto - texto/pagina-002.txt'])
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ['texto - texto', 'texto.pdf'])


@NEEDS_PDFIUM
class ImageTests(Base):
    def test_jpeg_is_copied_without_recompression_and_duplicates_and_icons_are_skipped(self):
        source = self.image_pdf(); out = convert({'paths': [str(source)], 'target': IMG})
        self.assertEqual(self.names(out), ['imagens - imagens/pagina-001-imagem-1.jpg', 'imagens - imagens/pagina-002-imagem-1.jpg'])      # ícone 10 px e a foto repetida ficaram de fora
        with Image.open(out[0]) as im: self.assertEqual(im.size, (200, 120)); self.assertEqual(im.format, 'JPEG')

    def test_minimum_size_zero_keeps_the_icon(self):
        out = convert({'paths': [str(self.image_pdf())], 'target': IMG, 'img_min': 0})
        self.assertEqual(len(out), 3); self.assertTrue(any('pagina-003' in x for x in out))

    def test_page_range(self):
        out = convert({'paths': [str(self.image_pdf())], 'target': IMG, 'pdf_pages': '2'})
        self.assertEqual(self.names(out), ['imagens - imagens/pagina-002-imagem-1.jpg'])

    def test_non_jpeg_becomes_png(self):
        path = self.root / 'paleta.pdf'
        image = Image.new('P', (80, 60)); image.putpalette([255, 0, 0, 0, 255, 0] + [0] * 762); image.save(path)
        out = convert({'paths': [str(path)], 'target': IMG})
        self.assertEqual(Path(out[0]).suffix, '.png')
        with Image.open(out[0]) as im: self.assertEqual(im.size, (80, 60))

    def test_no_images_is_an_explained_error_without_leftovers(self):
        source = self.text_pdf()
        with self.assertRaisesRegex(ConversionError, 'nenhuma imagem.*Páginas em imagens|nenhuma imagem.*PDF → imagens'): convert({'paths': [str(source)], 'target': IMG})
        with self.assertRaisesRegex(ConversionError, 'pelo menos 50 px'): convert({'paths': [str(self.image_pdf())], 'target': IMG, 'pdf_pages': '3', 'img_min': 50})
        self.assertFalse((self.root / 'texto - imagens').exists())

    def test_invalid_options_and_non_pdf(self):
        source = str(self.image_pdf())
        for options, pattern in (({'img_min': 3000}, 'entre 0 e 2000'), ({'img_min': '5'}, 'entre 0 e 2000'), ({'pdf_pages': '99'}, 'passa do fim')):
            with self.assertRaisesRegex(ConversionError, pattern): convert({'paths': [source], 'target': IMG, **options})
        text = self.root / 'a.txt'; text.write_text('x')
        with self.assertRaisesRegex(ConversionError, 'PDF'): convert({'paths': [str(text)], 'target': IMG})

    def test_real_worker_publishes_into_the_images_folder(self):
        out = runner.run_job({'paths': [str(self.image_pdf())], 'target': IMG})
        self.assertEqual(self.names(out), ['imagens - imagens/pagina-001-imagem-1.jpg', 'imagens - imagens/pagina-002-imagem-1.jpg'])
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ['imagens - imagens', 'imagens.pdf'])


class ReportAndControllerTests(Base):
    def controller(self):
        patcher = mock.patch.object(JobController, '_start_next'); patcher.start(); self.addCleanup(patcher.stop)
        return JobController(capabilities={'images': (True, 'ok'), 'pdf': (True, 'ok')})

    def test_reports(self):
        self.assertIn('digitalizadas', ' '.join(engine.loss_report(['/x.pdf'], TXT)))
        self.assertIn('layout', ' '.join(engine.loss_report(['/x.pdf'], TXT, {'text_layout': 'layout'})))
        text = ' '.join(engine.loss_report(['/x.pdf'], IMG)); self.assertIn('sem recomprimir', text); self.assertIn('máscaras', text)

    def test_controller_option_types(self):
        source = str(self.text_pdf())
        c = self.controller(); self.assertTrue(c.start_job([source], TXT, {'text_mode': 'pages', 'text_layout': 'layout', 'pdf_pages': '1'}))
        self.assertTrue(c.start_job([source], IMG, {'img_min': 10, 'pdf_pages': '1'}))
        for target, bad in ((TXT, {'text_mode': 3}), (IMG, {'img_min': '10'}), (IMG, {'pdf_pages': 5})):
            self.assertFalse(self.controller().start_job([source], target, bad), msg=str(bad))


@NEEDS_PDFIUM
class PanelTests(Base):
    def panel(self, source, tool):
        panel = FeaturePanel(JobController(capabilities={'images': (True, 'ok'), 'pdf': (True, 'ok')})); panel.resize(1100, 760)
        panel.pdf_stage.loader = lambda job: runner.run_pdf_op(job); self.addCleanup(panel.pdf_stage.shutdown)
        panel.set_files([str(source)], tool); APP.processEvents(); return panel

    def test_text_controls(self):
        with mock.patch.object(JobController, '_start_next'):
            panel = self.panel(self.text_pdf(), TXT)
            self.assertIn('2 páginas serão lidas', panel.txt_info.text()); self.assertTrue(panel.run_button.isEnabled())
            panel.txt_mode.setCurrentIndex(2); panel.txt_layout.setCurrentIndex(1); panel.txt_pages.setText('1'); APP.processEvents()
            self.assertEqual(panel._pdftext_values(), {'text_mode': 'pages', 'text_layout': 'layout', 'pdf_pages': '1'}); self.assertIn('1 página será lida', panel.txt_info.text())
            panel.txt_pages.setText('9'); APP.processEvents()
            self.assertFalse(panel.run_button.isEnabled()); self.assertIn('passa do fim', panel.txt_info.text())

    def test_embedded_image_controls(self):
        with mock.patch.object(JobController, '_start_next'):
            panel = self.panel(self.image_pdf(), IMG)
            self.assertIn('4 páginas', panel.emb_info.text()); self.assertIn('menores que 32 px', panel.emb_info.text()); self.assertEqual(panel.run_button.text(), 'Extrair imagens')
            panel.emb_min.setValue(0); panel.emb_pages.setText('2-3'); APP.processEvents()
            self.assertEqual(panel._embedded_values(), {'img_min': 0, 'pdf_pages': '2-3'}); self.assertIn('sem ignorar nenhuma', panel.emb_info.text())
            panel.emb_pages.setText('x'); APP.processEvents(); self.assertFalse(panel.run_button.isEnabled())

    def test_scanned_pdf_warning(self):
        with mock.patch.object(JobController, '_start_next'):
            panel = self.panel(self.image_pdf(), TXT)
            self.assertIn('não ter camada de texto', panel.txt_info.text())


if __name__ == '__main__':
    unittest.main()
