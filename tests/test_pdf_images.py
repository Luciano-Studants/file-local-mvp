"""PDF → imagens (0.9.30): intervalo de páginas, resolução, limite de 40 MP, pasta numerada, formatos e integração com o painel/controlador."""
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
from pypdf import PdfWriter
from PySide6.QtWidgets import QApplication

import engine
import pdfinfo
import runner
import tool_registry
from engine import ConversionError, convert
from test_illustrator import make_pdf
from tray_app import JobController
from workspace_panel import FeaturePanel

APP = QApplication.instance() or QApplication([])
NEEDS_PDFIUM = unittest.skipUnless(pdfinfo.preview_available(), 'pypdfium2 não instalado')
T = tool_registry.PDF_IMAGES


class Base(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name); self.addCleanup(self.temp.cleanup)

    def pdf(self, name='doc.pdf', pages=4, width=200, height=100):
        path = self.root / name; path.write_bytes(make_pdf(pages=pages, width=width, height=height)); return path

    def blank(self, name, pages, width, height):
        writer = PdfWriter()
        for _ in range(pages): writer.add_blank_page(width, height)
        path = self.root / name
        with path.open('wb') as handle: writer.write(handle)
        return path


class RangeTests(unittest.TestCase):
    def test_valid_ranges(self):
        p = pdfinfo.parse_page_range
        self.assertEqual(p('', 4), [1, 2, 3, 4]); self.assertEqual(p('1-3,7', 9), [1, 2, 3, 7]); self.assertEqual(p('3-', 5), [3, 4, 5])
        self.assertEqual(p('-2', 5), [1, 2]); self.assertEqual(p(' 2 ; 2 , 1 ', 5), [2, 1]); self.assertEqual(p(None, 2), [1, 2])

    def test_invalid_ranges_have_portuguese_messages(self):
        for bad in ('0', '3-1', '9', 'a', '1,,2', '1-2-3', '1.5', '--2'):
            with self.assertRaisesRegex(pdfinfo.PdfError, 'páginas|página|intervalo|Intervalo'): pdfinfo.parse_page_range(bad, 5)

    def test_page_cap(self):
        with self.assertRaisesRegex(pdfinfo.PdfError, 'no máximo'): pdfinfo.parse_page_range('1-201', 300)


class PixelTests(unittest.TestCase):
    def test_dpi_bounds_and_size(self):
        self.assertEqual(pdfinfo.dpi_size(595, 842, 72), (595, 842)); self.assertEqual(pdfinfo.dpi_size(72, 72, 300), (300, 300))
        for bad in (71, 601, 150.0, '150', True, None):
            with self.assertRaises(pdfinfo.PdfError): pdfinfo.check_dpi(bad)

    def test_forty_megapixel_cap_explains_and_suggests_dpi(self):
        with self.assertRaisesRegex(pdfinfo.PdfError, r'40 megapixels.*no máximo \d+ dpi'): pdfinfo.page_pixels_ok(3, 2000, 2000, 600)
        self.assertEqual(pdfinfo.page_pixels_ok(1, 595, 842, 600), (4959, 7017))      # A4 a 600 dpi ≈ 34,8 MP: dentro do limite


@NEEDS_PDFIUM
class ConvertTests(Base):
    def test_default_png_numbered_in_a_new_folder(self):
        source = self.pdf(); out = convert({'paths': [str(source)], 'target': T})
        folder = self.root / 'doc - páginas'
        self.assertEqual([Path(x).name for x in out], ['pagina-001.png', 'pagina-002.png', 'pagina-003.png', 'pagina-004.png'])
        self.assertTrue(all(Path(x).parent == folder for x in out))
        with Image.open(out[0]) as im: self.assertEqual((im.size, im.mode), ((417, 209), 'RGB'))       # 200×100 pt a 150 dpi
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ['doc - páginas', 'doc.pdf'])     # nenhum rascunho sobrou

    def test_dpi_scales_the_pixels(self):
        out = convert({'paths': [str(self.pdf(pages=1))], 'target': T, 'pdf_dpi': 72})
        with Image.open(out[0]) as im: self.assertEqual(im.size, (200, 100))
        out = convert({'paths': [str(self.pdf('b.pdf', pages=1))], 'target': T, 'pdf_dpi': 300})
        with Image.open(out[0]) as im: self.assertEqual(im.size, (834, 417))

    def test_page_range_keeps_original_numbers(self):
        out = convert({'paths': [str(self.pdf(pages=6))], 'target': T, 'pdf_pages': '2-3,6', 'pdf_dpi': 72})
        self.assertEqual([Path(x).name for x in out], ['pagina-002.png', 'pagina-003.png', 'pagina-006.png'])

    def test_content_is_drawn_on_white(self):
        out = convert({'paths': [str(self.pdf(pages=1))], 'target': T, 'pdf_dpi': 72})
        with Image.open(out[0]) as im:
            self.assertEqual(im.getpixel((10, 90)), (255, 0, 0)); self.assertEqual(im.getpixel((190, 5)), (255, 255, 255))

    def test_output_formats(self):
        for key, ext in (('jpeg', 'jpg'), ('webp', 'webp'), ('tiff', 'tif'), ('bmp', 'bmp'), ('gif', 'gif')):
            source = self.pdf(f'{key}.pdf', pages=1)
            out = convert({'paths': [str(source)], 'target': T, 'out_format': key, 'pdf_dpi': 72})
            self.assertEqual(Path(out[0]).suffix, '.' + engine.OUTPUT_FORMATS[key][1], key)
            with Image.open(out[0]) as im: im.load(); self.assertEqual(im.size, (200, 100))

    def test_ico_is_refused_and_leaves_nothing(self):
        source = self.pdf()
        with self.assertRaisesRegex(ConversionError, 'ICO'): convert({'paths': [str(source)], 'target': T, 'out_format': 'ico'})
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ['doc.pdf'])

    def test_invalid_options_leave_nothing(self):
        source = self.pdf()
        for options, pattern in (({'pdf_dpi': 50}, 'dpi'), ({'pdf_dpi': 700}, 'dpi'), ({'pdf_pages': '9'}, 'passa do fim'), ({'pdf_pages': 'x'}, 'inválido'), ({'pdf_pages': 'a' * 300}, 'longo')):
            with self.assertRaisesRegex(ConversionError, pattern): convert({'paths': [str(source)], 'target': T, **options})
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ['doc.pdf'])

    def test_forty_megapixel_page_is_refused_before_any_output(self):
        source = self.blank('big.pdf', 2, 595, 842)
        big = self.blank('mix.pdf', 1, 2000, 2000)
        with self.assertRaisesRegex(ConversionError, '40 megapixels'): convert({'paths': [str(big)], 'target': T, 'pdf_dpi': 600})
        out = convert({'paths': [str(source)], 'target': T, 'pdf_dpi': 600, 'pdf_pages': '1'})      # A4 a 600 dpi cabe
        self.assertEqual(len(out), 1)
        self.assertFalse((self.root / 'mix - páginas').exists())

    def test_second_run_never_overwrites(self):
        source = self.pdf(pages=1)
        first = convert({'paths': [str(source)], 'target': T, 'pdf_dpi': 72}); second = convert({'paths': [str(source)], 'target': T, 'pdf_dpi': 72})
        self.assertEqual(Path(second[0]).parent.name, 'doc - páginas (2)'); self.assertTrue(Path(first[0]).is_file())

    def test_rejects_non_pdf_encrypted_and_damaged(self):
        text = self.root / 'a.txt'; text.write_text('x')
        with self.assertRaisesRegex(ConversionError, 'PDF'): convert({'paths': [str(text)], 'target': T})
        broken = self.root / 'broken.pdf'; broken.write_bytes(b'%PDF-1.4\nnada')
        with self.assertRaises(ConversionError): convert({'paths': [str(broken)], 'target': T})
        self.assertFalse((self.root / 'broken - páginas').exists())

    def test_one_file_per_job(self):
        with self.assertRaises(ConversionError): convert({'paths': [str(self.pdf()), str(self.pdf('b.pdf'))], 'target': T})

    def test_real_worker_end_to_end(self):
        source = self.pdf(pages=2)
        runner.run_job({'paths': [str(source)], 'target': T, 'pdf_dpi': 72, 'out_format': 'jpeg'})
        self.assertTrue((self.root / 'doc - páginas' / 'pagina-002.jpg').is_file())
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ['doc - páginas', 'doc.pdf'])      # sem pasta de preparo sobrando
        with self.assertRaisesRegex(ValueError, 'passa do fim'): runner.run_job({'paths': [str(source)], 'target': T, 'pdf_pages': '9'})
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ['doc - páginas', 'doc.pdf'])


class LossReportTests(Base):
    def test_report_mentions_dpi_format_and_vector_loss(self):
        notes = ' '.join(engine.loss_report([str(self.pdf())], T, {'pdf_dpi': 200, 'out_format': 'jpeg', 'out_quality': 80}))
        self.assertIn('200 dpi', notes); self.assertIn('JPEG', notes); self.assertIn('pixels', notes); self.assertIn('formulário', notes)


class ControllerAndPanelTests(Base):
    def controller(self):
        patcher = mock.patch.object(JobController, '_start_next'); patcher.start(); self.addCleanup(patcher.stop)      # nenhum job de verdade (thread) nos testes
        return JobController(capabilities={'images': (True, 'ok'), 'pdf': (True, 'ok')})

    def test_controller_accepts_the_new_options_and_rejects_bad_types(self):
        controller = self.controller(); source = str(self.pdf())
        self.assertTrue(controller.start_job([source], T, {'pdf_dpi': 200, 'pdf_pages': '1-2', 'out_format': 'png'}))
        self.assertEqual(controller.pending_jobs[0]['options']['pdf_dpi'], 200)
        bad = self.controller()
        self.assertFalse(bad.start_job([source], T, {'pdf_dpi': '200'})); self.assertFalse(bad.start_job([source], T, {'pdf_pages': 5}))

    @NEEDS_PDFIUM
    def test_panel_options_and_gate(self):
        controller = self.controller(); panel = FeaturePanel(controller); panel.resize(1000, 700)
        panel.pdf_stage.loader = lambda job: runner.run_pdf_op(job); self.addCleanup(panel.pdf_stage.shutdown)
        panel.set_files([str(self.pdf())], T); APP.processEvents()
        self.assertEqual(panel.selected_tool, T)
        panel.pdfimg_dpi.setValue(300); panel.pdfimg_pages.setText('9'); APP.processEvents()
        self.assertFalse(panel.run_button.isEnabled()); self.assertIn('passa do fim', panel.pdfimg_info.text())
        panel.pdfimg_pages.setText('1-2'); APP.processEvents()
        self.assertTrue(panel.run_button.isEnabled()); self.assertIn('megapixels', panel.pdfimg_info.text())
        self.assertEqual(panel._pdfimg_values(), {'pdf_dpi': 300, 'pdf_pages': '1-2'})
        self.assertIn('Salvar páginas como', panel.run_button.text())


if __name__ == '__main__':
    unittest.main()
