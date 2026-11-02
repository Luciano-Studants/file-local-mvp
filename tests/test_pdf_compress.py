"""Comprimir PDF (0.9.37): níveis, resolução efetiva, JPEG e Flate, imagens ignoradas, nunca aumentar, runner, relatório, controlador e painel."""
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
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, DecodedStreamObject, DictionaryObject, NameObject, NumberObject
from PySide6.QtWidgets import QApplication

import engine
import pdfcompress
import pdfinfo
import runner
from engine import ConversionError, convert
from tray_app import JobController
from workspace_panel import FeaturePanel

APP = QApplication.instance() or QApplication([])
NEEDS_PDFIUM = unittest.skipUnless(pdfinfo.preview_available(), 'pypdfium2 não instalado')
CP = 'Compress PDF'


def flate_pdf(path, image, width_pt=576, height_pt=432, smask=False):
    """PDF de uma página com a imagem RGB em Flate (sem perda) desenhada em width_pt × height_pt."""
    writer = PdfWriter(); page = writer.add_blank_page(width_pt, height_pt)
    xobject = DecodedStreamObject(); xobject.set_data(image.tobytes())
    xobject.update({NameObject('/Type'): NameObject('/XObject'), NameObject('/Subtype'): NameObject('/Image'), NameObject('/Width'): NumberObject(image.width),
                    NameObject('/Height'): NumberObject(image.height), NameObject('/ColorSpace'): NameObject('/DeviceRGB'), NameObject('/BitsPerComponent'): NumberObject(8)})
    if smask:
        mask = DecodedStreamObject(); mask.set_data(bytes([255]) * (image.width * image.height))
        mask.update({NameObject('/Type'): NameObject('/XObject'), NameObject('/Subtype'): NameObject('/Image'), NameObject('/Width'): NumberObject(image.width),
                     NameObject('/Height'): NumberObject(image.height), NameObject('/ColorSpace'): NameObject('/DeviceGray'), NameObject('/BitsPerComponent'): NumberObject(8)})
        xobject[NameObject('/SMask')] = writer._add_object(mask)
    page[NameObject('/Resources')] = DictionaryObject({NameObject('/XObject'): DictionaryObject({NameObject('/Im0'): writer._add_object(xobject.flate_encode())})})
    content = DecodedStreamObject(); content.set_data(f'q {width_pt} 0 0 {height_pt} 0 0 cm /Im0 Do Q'.encode())
    page[NameObject('/Contents')] = writer._add_object(content)
    writer.write(str(path)); return path


def first_image(path):
    return list(PdfReader(str(path)).pages[0].images)[0]


class Base(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name); self.addCleanup(self.temp.cleanup)

    def jpeg_pdf(self, name='foto.pdf'):
        path = self.root / name; Image.effect_noise((2400, 1800), 60).convert('RGB').save(path, resolution=300); return path     # JPEG de 8 × 6 pol a 300 dpi

    def photo_flate(self, name='flate.pdf', **kw):
        noise = Image.merge('RGB', [Image.effect_noise((900, 675), 70) for _ in range(3)])
        return flate_pdf(self.root / name, noise, **kw)

    def flat_flate(self, name='plano.pdf'):
        import random
        random.seed(1); palette = [tuple(random.randrange(256) for _ in range(3)) for _ in range(30)]
        tile = Image.new('RGB', (48, 36)); tile.putdata([random.choice(palette) for _ in range(48 * 36)])
        return flate_pdf(self.root / name, tile.resize((1152, 864), Image.NEAREST), 288, 216)       # 288 dpi efetivos, 30 cores, blocos de 24 px


class EngineTests(Base):
    def test_levels_downscale_by_effective_dpi_and_shrink(self):
        source = self.jpeg_pdf(); sizes = {}
        for level, width in (('medium', 1200), ('strong', 768)):
            out = Path(convert({'paths': [str(source)], 'target': CP, 'pdf_level': level})[0])
            self.assertTrue(out.name.startswith('foto-comprimido')); self.assertEqual(first_image(out).image.size[0], width); sizes[level] = out.stat().st_size
            self.assertLess(out.stat().st_size, source.stat().st_size * 0.5)
        self.assertLess(sizes['strong'], sizes['medium'])
        self.assertEqual(len(PdfReader(str(out)).pages), 1); self.assertTrue(source.exists())

    def test_default_is_medium_and_light_keeps_resolution_or_refuses(self):
        out = Path(convert({'paths': [str(self.jpeg_pdf())], 'target': CP})[0]); self.assertEqual(first_image(out).image.size[0], 1200)
        with self.assertRaises(ConversionError) as ctx: convert({'paths': [str(self.jpeg_pdf('b.pdf'))], 'target': CP, 'pdf_level': 'light'})
        self.assertIn('não reduziu', str(ctx.exception))

    def test_flate_photo_becomes_jpeg_only_in_medium(self):
        source = self.photo_flate()
        out = Path(convert({'paths': [str(source)], 'target': CP, 'pdf_level': 'medium'})[0])
        stream = PdfReader(str(out)).pages[0]['/Resources']['/XObject']['/Im0'].get_object()
        self.assertEqual(str(stream['/Filter']), '/DCTDecode'); self.assertLess(out.stat().st_size, source.stat().st_size * 0.5)
        with self.assertRaises(ConversionError): convert({'paths': [str(source)], 'target': CP, 'pdf_level': 'light'})       # leve não toca em fotos sem perda

    def test_flat_flate_stays_lossless_and_scaled(self):
        out = Path(convert({'paths': [str(self.flat_flate())], 'target': CP, 'pdf_level': 'strong'})[0])
        stream = PdfReader(str(out)).pages[0]['/Resources']['/XObject']['/Im0'].get_object()
        self.assertEqual(str(stream['/Filter']), '/FlateDecode'); self.assertEqual(int(stream['/Width']), 384)

    def test_image_with_mask_is_untouched(self):
        with self.assertRaises(ConversionError): convert({'paths': [str(self.photo_flate('mask.pdf', smask=True))], 'target': CP, 'pdf_level': 'strong'})

    def test_never_larger_and_validation(self):
        small = self.root / 'pequeno.pdf'; writer = PdfWriter(); writer.add_blank_page(100, 100); writer.write(str(small))
        before = sorted(p.name for p in self.root.iterdir())
        with self.assertRaises(ConversionError) as ctx: convert({'paths': [str(small)], 'target': CP, 'pdf_level': 'strong'})
        self.assertIn('nada foi salvo', str(ctx.exception)); self.assertEqual(sorted(p.name for p in self.root.iterdir()), before)
        with self.assertRaises(ConversionError): convert({'paths': [str(self.jpeg_pdf())], 'target': CP, 'pdf_level': 'x'})
        (self.root / 'a.txt').write_text('x')
        with self.assertRaises(ConversionError): convert({'paths': [str(self.root / 'a.txt')], 'target': CP})

    def test_keeps_text_bookmarks_and_attachments(self):
        source = self.root / 'rico.pdf'; writer = PdfWriter(clone_from=PdfReader(str(self.jpeg_pdf())))
        writer.add_outline_item('Capítulo', 0); writer.add_attachment('nota.txt', b'dados'); writer.write(str(source))
        out = Path(convert({'paths': [str(source)], 'target': CP})[0]); reader = PdfReader(str(out))
        self.assertEqual([item.title for item in reader.outline], ['Capítulo']); self.assertIn('/EmbeddedFiles', reader.trailer['/Root']['/Names'])

    def test_drawn_sizes_follow_the_matrix(self):
        reader = PdfReader(str(self.jpeg_pdf())); writer = PdfWriter(clone_from=reader)
        sizes = pdfcompress.drawn_sizes(writer.pages[0], writer); self.assertEqual(len(sizes), 1)
        width, height = next(iter(sizes.values())); self.assertAlmostEqual(width, 576, delta=1); self.assertAlmostEqual(height, 432, delta=1)

    def test_runner_scales_timeout_and_reports(self):
        out = runner.run_job({'paths': [str(self.jpeg_pdf())], 'target': CP, 'pdf_level': 'strong'}); self.assertEqual([Path(p).name for p in out], ['foto-comprimido.pdf'])
        with mock.patch.object(runner, '_run_job', return_value=[]) as fake:
            try: runner.run_job({'paths': [str(self.jpeg_pdf('c.pdf'))], 'target': CP})
            except Exception: pass
        self.assertGreaterEqual(fake.call_args.args[2], engine.PDF_OCR_TIMEOUT)
        text = ' '.join(engine.loss_report(['/x.pdf'], CP, {'pdf_level': 'strong'})); self.assertIn('96 dpi', text); self.assertIn('Assinaturas digitais', text)
        self.assertIn('Fotos sem perda ficam como estão', ' '.join(engine.loss_report(['/x.pdf'], CP, {'pdf_level': 'light'})))
        self.assertIn(CP, engine.OPERATIONS)

    def controller(self):
        patcher = mock.patch.object(JobController, '_start_next'); patcher.start(); self.addCleanup(patcher.stop)
        return JobController(capabilities={'images': (True, 'ok'), 'pdf': (True, 'ok')})

    def test_controller_option_types(self):
        source = str(self.jpeg_pdf())
        self.assertTrue(self.controller().start_job([source], CP, {'pdf_level': 'strong'}))
        self.assertFalse(self.controller().start_job([source], CP, {'pdf_level': 2}))


@NEEDS_PDFIUM
class PanelTests(Base):
    def panel(self, source):
        panel = FeaturePanel(JobController(capabilities={'images': (True, 'ok'), 'pdf': (True, 'ok')})); panel.resize(1100, 760)
        panel.pdf_stage.loader = lambda job: runner.run_pdf_op(job); self.addCleanup(panel.pdf_stage.shutdown)
        panel.set_files([str(source)], CP); APP.processEvents(); return panel

    def test_controls(self):
        with mock.patch.object(JobController, '_start_next'):
            panel = self.panel(self.jpeg_pdf()); self.assertIn('Tamanho atual', panel.cp_info.text()); self.assertTrue(panel.run_button.isEnabled())
            self.assertEqual(panel.run_button.text(), 'Comprimir PDF'); self.assertEqual(panel._pdfcompress_values(), {'pdf_level': 'medium'})
            panel.cp_level.setCurrentIndex(2); self.assertEqual(panel._pdfcompress_values(), {'pdf_level': 'strong'})
            panel.cp_level.setCurrentIndex(0); self.assertEqual(panel._pdfcompress_values(), {'pdf_level': 'light'})

    def test_finished_message_shows_sizes(self):
        with mock.patch.object(JobController, '_start_next'):
            source = self.jpeg_pdf(); panel = self.panel(source)
            out = Path(convert({'paths': [str(source)], 'target': CP})[0])
            panel.on_job_finished(True, 'Concluído', [str(out)], [str(source)], CP)
            self.assertIn('→', panel.status.text()); self.assertIn('%', panel.status.text())


if __name__ == '__main__':
    unittest.main()
