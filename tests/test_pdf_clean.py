"""Metadados do PDF e cópia limpa (0.9.36): leitura, remoção de Info/XMP/anexos/JavaScript, conferência, erros, relatório, controlador e painel."""
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
from pypdf.generic import DictionaryObject, NameObject, TextStringObject
from PySide6.QtWidgets import QApplication

import engine
import pdfinfo
import runner
from engine import ConversionError, convert
from tray_app import JobController
from workspace_panel import FeaturePanel

APP = QApplication.instance() or QApplication([])
NEEDS_PDFIUM = unittest.skipUnless(pdfinfo.preview_available(), 'pypdfium2 não instalado')
CLEAN = 'Clean PDF'


class Base(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name); self.addCleanup(self.temp.cleanup)

    def dirty(self, name='sujo.pdf', info=True, attach=True, js=True, xmp=True):
        writer = PdfWriter(); writer.add_blank_page(200, 200); writer.add_blank_page(200, 200)
        if info: writer.add_metadata({'/Title': 'Contrato', '/Author': 'Fulano Segredo', '/Creator': 'Word', '/Custom': 'valor'})
        if attach: writer.add_attachment('anexo-secreto.txt', b'conteudo')
        if js: writer.add_js('app.alert("ola-script")')
        if xmp:
            from pypdf.generic import DecodedStreamObject
            stream = DecodedStreamObject(); stream.set_data(b'<x:xmpmeta><rdf:li>Fulano XMP</rdf:li><dc:creator><rdf:Seq><rdf:li>Autora XMP</rdf:li></rdf:Seq></dc:creator></x:xmpmeta>')
            writer._root_object[NameObject('/Metadata')] = writer._add_object(stream)
        path = self.root / name; writer.write(str(path)); return path

    def clean(self, **extra):
        return Path(convert({'paths': [str(self.dirty())], 'target': CLEAN, **extra})[0])


class CoreTests(Base):
    def test_inspect_lists_everything(self):
        info = pdfinfo.inspect_pdf(self.dirty())
        labels = dict(info['meta_fields']); self.assertEqual(labels['Autor'], 'Fulano Segredo'); self.assertEqual(labels['Custom'], 'valor')
        self.assertTrue(info['xmp']); self.assertEqual(dict(info['xmp_fields'])['Autor (XMP)'], 'Autora XMP')
        self.assertEqual(info['attachment_names'], ['anexo-secreto.txt']); self.assertTrue(info['javascript'])

    def test_scan_clean_pdf(self):
        path = self.root / 'ok.pdf'; writer = PdfWriter(); writer.add_blank_page(100, 100); writer._info = None; writer.write(str(path))
        self.assertEqual(pdfinfo.clean_scan(PdfReader(str(path))), {'info': False, 'attach': False, 'js': False})
        self.assertEqual(pdfinfo.inspect_pdf(path)['meta_fields'], [])

    def test_annotation_javascript_and_file_attachment(self):
        writer = PdfWriter(); page = writer.add_blank_page(200, 200); writer._info = None
        annot = DictionaryObject({NameObject('/Type'): NameObject('/Annot'), NameObject('/Subtype'): NameObject('/Link')})
        action = DictionaryObject({NameObject('/S'): NameObject('/JavaScript'), NameObject('/JS'): TextStringObject('app.alert(1)')})
        annot[NameObject('/A')] = action
        from pypdf.generic import ArrayObject
        page[NameObject('/Annots')] = ArrayObject([writer._add_object(annot)])
        path = self.root / 'a.pdf'; writer.write(str(path))
        self.assertTrue(pdfinfo.clean_scan(PdfReader(str(path)))['js'])
        out = Path(convert({'paths': [str(path)], 'target': CLEAN})[0])
        self.assertFalse(pdfinfo.clean_scan(PdfReader(str(out)))['js']); self.assertNotIn(b'ola', out.read_bytes())


class EngineTests(Base):
    def test_clean_copy_removes_everything_and_keeps_pages(self):
        out = self.clean(); self.assertEqual(out.name, 'sujo-limpo.pdf')
        data = out.read_bytes()
        for secret in (b'Fulano', b'Segredo', b'anexo-secreto', b'ola-script', b'Autora XMP', b'pypdf', b'Contrato'): self.assertNotIn(secret, data, msg=str(secret))
        reader = PdfReader(str(out)); self.assertEqual(len(reader.pages), 2); self.assertIsNone(reader.metadata)
        self.assertEqual(pdfinfo.clean_scan(reader), {'info': False, 'attach': False, 'js': False})
        self.assertTrue((self.root / 'sujo.pdf').read_bytes().count(b'Fulano') >= 1)       # original intacto

    def test_partial_options(self):
        out = self.clean(meta_info='off', meta_js='off'); found = pdfinfo.clean_scan(PdfReader(str(out)))
        self.assertEqual(found, {'info': True, 'attach': False, 'js': True}); self.assertEqual(PdfReader(str(out)).metadata['/Author'], 'Fulano Segredo')
        out = self.clean(meta_attach='off', meta_js='off'); self.assertEqual(pdfinfo.clean_scan(PdfReader(str(out))), {'info': False, 'attach': True, 'js': True})

    def test_nothing_to_remove_and_invalid(self):
        clean = self.clean(); before = sorted(p.name for p in self.root.iterdir())
        with self.assertRaises(ConversionError) as ctx: convert({'paths': [str(clean)], 'target': CLEAN})
        self.assertIn('já está limpo', str(ctx.exception)); self.assertEqual(sorted(p.name for p in self.root.iterdir()), before)
        source = str(self.dirty('b.pdf'))
        for bad in ({'meta_info': 'x'}, {'meta_info': 'off', 'meta_attach': 'off', 'meta_js': 'off'}):
            with self.assertRaises(ConversionError, msg=str(bad)): convert({'paths': [source], 'target': CLEAN, **bad})
        (self.root / 'x.txt').write_text('x')
        with self.assertRaises(ConversionError): convert({'paths': [str(self.root / 'x.txt')], 'target': CLEAN})

    def test_only_info_present_but_not_selected(self):
        path = self.dirty('so-info.pdf', attach=False, js=False, xmp=False)
        with self.assertRaises(ConversionError): convert({'paths': [str(path)], 'target': CLEAN, 'meta_info': 'off'})

    def test_runner_and_reports(self):
        out = runner.run_job({'paths': [str(self.dirty())], 'target': CLEAN})
        self.assertEqual([Path(p).name for p in out], ['sujo-limpo.pdf'])
        text = ' '.join(engine.loss_report(['/x.pdf'], CLEAN)); self.assertIn('EXIF', text); self.assertIn('Assinaturas digitais', text)
        self.assertNotIn('JavaScript', ' '.join(engine.loss_report(['/x.pdf'], CLEAN, {'meta_js': 'off'})))
        self.assertIn(CLEAN, engine.OPERATIONS)

    def controller(self):
        patcher = mock.patch.object(JobController, '_start_next'); patcher.start(); self.addCleanup(patcher.stop)
        return JobController(capabilities={'images': (True, 'ok'), 'pdf': (True, 'ok')})

    def test_controller_option_types(self):
        source = str(self.dirty())
        self.assertTrue(self.controller().start_job([source], CLEAN, {'meta_info': 'off', 'meta_attach': 'on', 'meta_js': 'on'}))
        self.assertFalse(self.controller().start_job([source], CLEAN, {'meta_js': 1}))


@NEEDS_PDFIUM
class PanelTests(Base):
    def panel(self, source):
        panel = FeaturePanel(JobController(capabilities={'images': (True, 'ok'), 'pdf': (True, 'ok')})); panel.resize(1100, 760)
        panel.pdf_stage.loader = lambda job: runner.run_pdf_op(job); self.addCleanup(panel.pdf_stage.shutdown)
        panel.set_files([str(source)], CLEAN); APP.processEvents(); return panel

    def test_details_and_controls(self):
        with mock.patch.object(JobController, '_start_next'):
            panel = self.panel(self.dirty()); text = panel.kl_details.text()
            for expected in ('Autor: Fulano Segredo', 'Autor (XMP): Autora XMP', 'anexo-secreto.txt', 'JavaScript: presente'): self.assertIn(expected, text)
            self.assertTrue(panel.run_button.isEnabled()); self.assertEqual(panel.run_button.text(), 'Gerar cópia limpa')
            self.assertEqual(panel._pdfclean_values(), {'meta_info': 'on', 'meta_attach': 'on', 'meta_js': 'on'})
            panel.kl_meta.setCurrentIndex(1); panel.kl_attach.setCurrentIndex(1); panel.kl_js.setCurrentIndex(1); APP.processEvents()
            self.assertFalse(panel.run_button.isEnabled()); self.assertIn('ao menos uma', panel.kl_info.text())

    def test_clean_pdf_message(self):
        path = self.root / 'ok.pdf'; writer = PdfWriter(); writer.add_blank_page(100, 100); writer._info = None; writer.write(str(path))
        with mock.patch.object(JobController, '_start_next'):
            self.assertIn('Nenhum metadado', self.panel(path).kl_details.text())


if __name__ == '__main__':
    unittest.main()
