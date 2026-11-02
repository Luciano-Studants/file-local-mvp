"""Leitura de Adobe Illustrator (.ai com parte de PDF) pelo PDFium (0.9.23): núcleo `illustrator.py`, motor, relatório, worker e painel.

Os arquivos de teste são PDFs mínimos montados à mão com extensão .ai (o formato moderno do Illustrator é um PDF por dentro).
Os testes que desenham precisam do pacote pypdfium2 e são pulados sem ele.
"""
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PIL import Image
from PySide6.QtWidgets import QApplication

import engine
import illustrator
import vector
from engine import ConversionError, IMAGE_INPUTS, VECTOR_INPUTS, convert, loss_report, set_vector_width
from tray_app import FeaturePanel, JobController

HAS = illustrator.available()
STUB = b'BT /F1 12 Tf 10 50 Td (This Adobe Illustrator file was saved without PDF Content.) Tj ET'
RED_BLUE = b'1 0 0 rg 0 0 100 100 re f 0 0 1 rg 100 0 50 50 re f'        # vermelho à esquerda, azul embaixo à direita, resto vazio


def make_pdf(content=RED_BLUE, width=200, height=100, pages=1, extra_catalog='', font=False, header=b''):
    kids = ' '.join(f'{3 + i} 0 R' for i in range(pages))
    objects = [f'<< /Type /Catalog /Pages 2 0 R {extra_catalog} >>'.encode(), f'<< /Type /Pages /Kids [{kids}] /Count {pages} >>'.encode()]
    resources = '/Font << /F1 << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> >>' if font else ''
    first_content = 3 + pages
    for i in range(pages):
        objects.append(f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {width} {height}] /Contents {first_content + i} 0 R /Resources << {resources} >> >>'.encode())
    for i in range(pages):
        body = content if i == 0 else b'0 1 0 rg 0 0 200 100 re f'
        objects.append(b'<< /Length %d >>\nstream\n' % len(body) + body + b'\nendstream')
    out = bytearray(header + b'%PDF-1.5\n'); offsets = []
    base = len(header)
    for number, body in enumerate(objects, 1):
        offsets.append(len(out) - base); out += b'%d 0 obj\n' % number + body + b'\nendobj\n'
    xref = len(out) - base
    out += b'xref\n0 %d\n0000000000 65535 f \n' % (len(objects) + 1)
    for offset in offsets: out += b'%010d 00000 n \n' % offset
    out += b'trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n' % (len(objects) + 1, xref)
    return bytes(out)


class AiBase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name); self.out = self.root / 'out'; self.out.mkdir()
        set_vector_width(0)

    def tearDown(self):
        set_vector_width(0); self.temp.cleanup()

    def ai(self, data=None, name='arte.ai', **kwargs):
        path = self.root / name; path.write_bytes(data if data is not None else make_pdf(**kwargs)); return path

    def run_tool(self, path, target='Resize → PNG', **extra):
        options = {'resize_mode': 'percent', 'resize_percent': 100} if target == 'Resize → PNG' else {}
        return Path(convert({'paths': [str(path)], 'target': target, 'output': str(self.out), **options, **extra})[0])


class AiRegistryTests(unittest.TestCase):
    def test_suffix_is_an_image_and_vector_input(self):
        self.assertIn('.ai', IMAGE_INPUTS); self.assertIn('.ai', VECTOR_INPUTS); self.assertIn('.ai', engine.AI_INPUTS); self.assertNotIn('.ai', vector.VECTOR_SUFFIXES)
        self.assertIn('.svg', VECTOR_INPUTS)

    def test_requirements_pin_pypdfium2(self):
        text = (Path(__file__).resolve().parents[1] / 'requirements.txt').read_text(encoding='utf8')
        self.assertIn('pypdfium2==', text)

    def test_licenses_are_bundled(self):
        folder = Path(__file__).resolve().parents[1] / 'licenses'
        for name in ('pypdfium2-5.13.0-LICENSE.txt', 'pypdfium2_5.13.0-LICENSES_bundled.txt'): self.assertTrue((folder / name).is_file(), name)
        self.assertIn('pdfium', (folder / 'pypdfium2_5.13.0-LICENSES_bundled.txt').read_text(encoding='utf8').lower())

    def test_ui_lists_include_ai(self):
        import radial_menu, workspace_panel
        self.assertIn('.ai', workspace_panel.IMAGE_SUFFIXES); self.assertIn('.ai', radial_menu.IMAGE_SUFFIXES)


@unittest.skipUnless(HAS, 'pypdfium2 não está instalado')
class AiCoreTests(AiBase):
    def test_default_size_is_the_page_in_points(self):
        info = illustrator.describe_ai(self.ai())
        self.assertEqual((info['size'], info['declared'], info['reduced'], info['pages'], info['kind']), ((200, 100), (200.0, 100.0), False, 1, 'ai'))
        self.assertEqual(info['engine'], ('PDFium', True))

    def test_render_colors_position_and_transparency(self):
        im = illustrator.rasterize_ai(self.ai())
        self.assertEqual((im.mode, im.size), ('RGBA', (200, 100)))
        self.assertEqual(im.getpixel((10, 10)), (255, 0, 0, 255)); self.assertEqual(im.getpixel((120, 80)), (0, 0, 255, 255))
        self.assertEqual(im.getpixel((120, 20))[3], 0); self.assertEqual(im.getpixel((190, 90))[3], 0)

    def test_width_option_keeps_proportion(self):
        im = illustrator.rasterize_ai(self.ai(), 500); self.assertEqual(im.size, (500, 250))
        self.assertEqual(im.getpixel((25, 25)), (255, 0, 0, 255))
        small = illustrator.rasterize_ai(self.ai(), 40); self.assertEqual(small.size, (40, 20))

    def test_big_page_is_reduced_and_explicit_overflow_is_refused(self):
        big = self.ai(width=20000, height=1000, name='grande.ai')
        info = illustrator.describe_ai(big); self.assertTrue(info['reduced']); self.assertEqual(max(info['size']), 8192)
        with self.assertRaises(illustrator.AiError) as caught: illustrator.describe_ai(big, 20000)
        self.assertIn('limite', str(caught.exception))
        huge = self.ai(width=300000, height=100, name='enorme.ai')
        with self.assertRaises(illustrator.AiError): illustrator.describe_ai(huge)

    def test_only_the_first_page_is_drawn(self):
        path = self.ai(pages=2)
        self.assertEqual(illustrator.describe_ai(path)['pages'], 2)
        im = illustrator.rasterize_ai(path); self.assertEqual(im.getpixel((10, 10)), (255, 0, 0, 255))

    def test_header_offset_is_accepted(self):
        path = self.ai(make_pdf(header=b'JUNK' * 20, ))
        self.assertEqual(illustrator.describe_ai(path)['size'], (200, 100))

    def test_legacy_postscript_and_other_files_are_refused(self):
        legacy = self.ai(b'%!PS-Adobe-3.0 EPSF-3.0\n%%Creator: Adobe Illustrator(R) 8.0\n' + b'x' * 100, name='velho.ai')
        with self.assertRaises(illustrator.AiError) as caught: illustrator.describe_ai(legacy)
        self.assertIn('formato antigo', str(caught.exception)); self.assertIn('compatível com PDF', str(caught.exception))
        other = self.ai(b'hello world, not an illustrator file', name='outro.ai')
        with self.assertRaises(illustrator.AiError) as caught: illustrator.describe_ai(other)
        self.assertIn('não parece', str(caught.exception))
        empty = self.ai(b'', name='vazio.ai')
        with self.assertRaises(illustrator.AiError): illustrator.describe_ai(empty)

    def test_corrupt_pdf_part_is_refused(self):
        with self.assertRaises(illustrator.AiError) as caught: illustrator.rasterize_ai(self.ai(b'%PDF-1.4\nthis is nonsense\n', name='ruim.ai'))
        self.assertIn('não pôde ser lida', str(caught.exception))
        truncated = make_pdf()[:120]
        with self.assertRaises(illustrator.AiError): illustrator.rasterize_ai(self.ai(truncated, name='cortado.ai'))

    def test_password_protected_is_refused(self):
        from pypdf import PdfWriter
        writer = PdfWriter(); writer.add_blank_page(100, 100); writer.encrypt('segredo'); buffer = io.BytesIO(); writer.write(buffer)
        with self.assertRaises(illustrator.AiError) as caught: illustrator.describe_ai(self.ai(buffer.getvalue(), name='senha.ai'))
        self.assertIn('senha', str(caught.exception))

    def test_file_saved_without_pdf_content_is_refused(self):
        stub = self.ai(make_pdf(STUB, font=True), name='sem-pdf.ai')
        for function in (illustrator.describe_ai, illustrator.rasterize_ai):
            with self.assertRaises(illustrator.AiError) as caught: function(stub)
            self.assertIn('sem a parte de PDF', str(caught.exception))

    def test_javascript_and_actions_do_not_run_or_break_drawing(self):
        path = self.ai(make_pdf(extra_catalog='/OpenAction << /S /JavaScript /JS (app.alert\\(1\\);) >>'), name='js.ai')
        self.assertEqual(illustrator.rasterize_ai(path).getpixel((10, 10)), (255, 0, 0, 255))

    def test_missing_package_message(self):
        with patch.object(illustrator, '_pdfium', side_effect=illustrator.AiError('Para abrir arquivos .ai instale o pacote pypdfium2')):
            with self.assertRaises(illustrator.AiError) as caught: illustrator.describe_ai(self.ai())
            self.assertIn('pypdfium2', str(caught.exception))


@unittest.skipUnless(HAS, 'pypdfium2 não está instalado')
class AiEngineTests(AiBase):
    def test_tools_and_formats_keep_transparency_where_possible(self):
        path = self.ai()
        png = self.run_tool(path)
        with Image.open(png) as im: self.assertEqual((im.size, im.convert('RGBA').getpixel((190, 90))[3], im.convert('RGBA').getpixel((10, 10))), ((200, 100), 0, (255, 0, 0, 255)))
        webp = self.run_tool(path, out_format='webp', out_quality=100)
        with Image.open(webp) as im: self.assertEqual(im.convert('RGBA').getpixel((190, 90))[3], 0)
        jpeg = self.run_tool(path, out_format='jpeg', out_flatten='#00FF00')
        with Image.open(jpeg) as im: self.assertEqual(im.mode, 'RGB'); self.assertGreater(im.getpixel((190, 90))[1], 200)
        tiff = self.run_tool(path, out_format='tiff')
        with Image.open(tiff) as im: self.assertEqual(im.convert('RGBA').getpixel((190, 90))[3], 0)

    def test_other_tools_work_on_ai(self):
        path = self.ai()
        for target, extra in (('Rotate → PNG', {'rotate_angle': 90}), ('Sharpen → PNG', {'sharpen_mode': 'blur', 'sharpen_radius': 1}), ('Compress → JPEG', {}), ('Clean → PNG', {})):
            self.assertTrue(self.run_tool(path, target, **extra).is_file(), target)
        self.assertTrue(sorted(f.name for f in self.out.iterdir() if 'girada' in f.name)[0].startswith('arte-girada'))

    def test_vector_width_option_and_default(self):
        path = self.ai()
        with Image.open(self.run_tool(path, vector_width=600)) as im: self.assertEqual(im.size, (600, 300))
        with Image.open(self.run_tool(path)) as im: self.assertEqual(im.size, (200, 100))
        set_vector_width(0)

    def test_ai_mixed_with_collage_and_pdf(self):
        other = self.root / 'b.png'; Image.new('RGB', (50, 50), 'blue').save(other)
        collage = Path(convert({'paths': [str(self.ai()), str(other)], 'target': 'Collage → PNG', 'output': str(self.out)})[0])
        self.assertTrue(collage.is_file())
        pdf = Path(convert({'paths': [str(self.ai()), str(other)], 'target': 'Images → One PDF', 'output': str(self.out)})[0])
        self.assertTrue(pdf.is_file())

    def test_ocr_reads_text_from_ai_when_available(self):
        import ocr
        if not (ocr.status()[0] and 'eng' in ocr.available_languages()): self.skipTest('Tesseract indisponível')
        content = b'BT /F1 40 Tf 20 40 Td (Hello Illustrator) Tj ET'
        path = self.ai(make_pdf(content, width=500, height=120, font=True), name='texto.ai')
        text = self.run_tool(path, 'OCR → Text', ocr_lang='eng').read_text(encoding='utf8')
        self.assertIn('Hello', text)

    def test_original_untouched_and_no_leftovers(self):
        path = self.ai(); before = path.read_bytes(); self.run_tool(path)
        self.assertEqual(path.read_bytes(), before); self.assertEqual(sorted(p.name for p in self.root.iterdir()), ['arte.ai', 'out'])

    def test_failures_create_nothing(self):
        legacy = self.ai(b'%!PS-Adobe-3.0 EPSF-3.0\n%%Creator: Adobe Illustrator(R) 8.0\n', name='velho.ai')
        for path in (legacy, self.ai(b'%PDF-1.4\nlixo', name='ruim.ai')):
            with self.assertRaises(ConversionError): self.run_tool(path)
        with patch.object(illustrator, '_pdfium', side_effect=illustrator.AiError('Para abrir arquivos .ai instale o pacote pypdfium2')):
            with self.assertRaises(ConversionError) as caught: self.run_tool(self.ai(name='c.ai'))
            self.assertIn('pypdfium2', str(caught.exception))
        self.assertEqual(list(self.out.iterdir()), [])

    def test_worker_process(self):
        import runner
        result = runner.run_job({'paths': [str(self.ai())], 'target': 'Resize → PNG', 'resize_mode': 'percent', 'resize_percent': 100, 'output': str(self.out), 'vector_width': 400}, timeout=90)
        with Image.open(result[0]) as im: self.assertEqual(im.size, (400, 200))

    def test_forty_megapixel_page_fits_the_worker(self):
        import runner
        path = self.ai(width=8000, height=5000, name='grande.ai')
        result = runner.run_job({'paths': [str(path)], 'target': 'Resize → PNG', 'resize_mode': 'percent', 'resize_percent': 50, 'output': str(self.out)}, timeout=150)
        with Image.open(result[0]) as im: self.assertEqual(im.size, (4000, 2500))


@unittest.skipUnless(HAS, 'pypdfium2 não está instalado')
class AiReportTests(AiBase):
    def test_report_for_ai(self):
        text = ' '.join(loss_report([str(self.ai(pages=2))], 'Resize → PNG', {}))
        for part in ('PDFium', 'primeira página', '200 × 100 px', 'mais de uma página', 'transparente', 'CMYK'): self.assertIn(part, text)

    def test_report_for_big_page_and_width(self):
        self.assertIn('reduzido', ' '.join(loss_report([str(self.ai(width=20000, height=1000, name='g.ai'))], 'Resize → PNG', {})))
        self.assertIn('1000 × 500 px', ' '.join(loss_report([str(self.ai())], 'Resize → PNG', {'vector_width': 1000})))

    def test_report_for_unreadable_ai(self):
        text = ' '.join(loss_report([str(self.ai(b'%!PS-Adobe-3.0\n', name='velho.ai'))], 'Resize → PNG', {}))
        self.assertIn('Não foi possível ler um .ai', text); self.assertIn('formato antigo', text)

    def test_report_with_svg_and_ai_together(self):
        svg = self.root / 'v.svg'; svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="40" height="20"><rect width="40" height="20" fill="red"/></svg>', encoding='utf8')
        text = ' '.join(loss_report([str(svg), str(self.ai())], 'Resize → PNG', {}))
        self.assertIn('PDFium', text); self.assertIn('SVG', text)


class AiPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make_panel(self, data):
        controller = JobController(capabilities={'images': (True, 'ok'), 'pdf': (True, 'ok')}); panel = FeaturePanel(controller)
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup); path = Path(tmp.name) / 'a.ai'; path.write_bytes(data)
        panel.set_files([str(path)], 'Resize → PNG'); return controller, panel

    def visible(self, panel):
        return {k for k, w in panel.form_fields.items() if panel.settings_form.isRowVisible(w)}

    def test_width_row_is_shown_and_labeled_for_vectors(self):
        _c, panel = self.make_panel(make_pdf())
        self.assertIn('vwidth', self.visible(panel)); self.assertTrue(panel._has_vector())
        self.assertIn('.ai', panel.vector_width.toolTip())

    @unittest.skipUnless(HAS, 'pypdfium2 não está instalado')
    def test_preview_loads_and_width_is_sent(self):
        controller, panel = self.make_panel(make_pdf())
        self.assertTrue(all(panel.crop_image_size)); self.assertEqual(tuple(panel.crop_image_size), (200, 100))
        with patch.object(controller, 'start_job') as start:
            panel.vector_width.setValue(800); panel.run_selected()
            self.assertEqual(start.call_args.args[2]['vector_width'], 800)

    def test_legacy_ai_shows_message_instead_of_preview(self):
        _c, panel = self.make_panel(b'%!PS-Adobe-3.0 EPSF-3.0\n%%Creator: Adobe Illustrator(R) 8.0\n')
        self.assertEqual(tuple(panel.crop_image_size), (0, 0))


if __name__ == '__main__':
    unittest.main()
