"""Formulários PDF e assinatura visual (0.9.41): listar, preencher, achatar, imagem de assinatura em páginas giradas, validações, controlador e painel."""
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

from PIL import Image
from pypdf import PdfReader, PdfWriter
from pypdf.generic import NameObject
from PySide6.QtWidgets import QApplication

import engine
import pdfform
import pdfinfo
import runner
from engine import ConversionError, convert
from formfixture import form_pdf
from tray_app import JobController
from workspace_panel import FeaturePanel

APP = QApplication.instance() or QApplication([])
NEEDS_PDFIUM = unittest.skipUnless(pdfinfo.preview_available(), 'pypdfium2 não instalado')
FM = 'Fill PDF'
FULL = ['nome\tMaria Souza', 'endereco.cidade\tBelém', 'aceito\ton', 'turno\ttarde', 'estado\tSP']


class Base(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name); self.addCleanup(self.temp.cleanup)

    def form(self, name='form.pdf', **kwargs):
        path = self.root / name; path.write_bytes(form_pdf(**kwargs)); return path

    def plain(self, name='plain.pdf', rotate=0):
        writer = PdfWriter(); page = writer.add_blank_page(400, 300)
        if rotate: page.rotate(rotate)
        path = self.root / name; writer.write(str(path)); return path

    def signature(self, name='assinatura.png', size=(200, 80), alpha=True):
        image = Image.new('RGBA' if alpha else 'RGB', size, (0, 0, 0, 0) if alpha else (255, 255, 255)); path = self.root / name
        for x in range(10, size[0] - 10):
            for y in range(size[1] // 2 - 4, size[1] // 2 + 4): image.putpixel((x, y), (0, 0, 160, 255) if alpha else (0, 0, 160))
        image.save(path); return path

    def run_fill(self, source, **options):
        return Path(convert({'paths': [str(source)], 'target': FM, **options})[0])

    def fields(self, path):
        return {f['name']: f for f in pdfform.list_fields(PdfReader(str(path)))}

    def darkest(self, path, number=1, scale=1):
        import pypdfium2
        document = pypdfium2.PdfDocument(str(path))
        try:
            image = document[number - 1].render(scale=scale).to_pil().convert('L'); return image
        finally: document.close()


class CoreTests(Base):
    def test_list_fields_kinds_and_options(self):
        found = self.fields(self.form())
        self.assertEqual({n: f['kind'] for n, f in found.items()}, {'nome': 'text', 'endereco.cidade': 'text', 'aceito': 'check', 'turno': 'radio', 'estado': 'choice'})
        self.assertEqual(found['turno']['options'], ['manha', 'tarde']); self.assertEqual(found['estado']['options'], ['PA', 'SP', 'AM'])
        self.assertEqual(found['aceito']['value'], 'off')

    def test_signature_field_is_listed_but_not_fillable(self):
        found = self.fields(self.form(signature_field=True)); self.assertEqual(found['assinatura_digital']['kind'], 'signature')
        with self.assertRaises(pdfform.FormError): pdfform.parse_values(['assinatura_digital\tx'], list(found.values()))

    def test_parse_values_validation(self):
        fields = list(self.fields(self.form()).values())
        for bad in ('x', ['semtab'], ['nada\tx'], ['aceito\tsim'], ['turno\tnoite'], ['estado\tRJ'], ['nome\t' + 'a' * 1001], ['nome\ta\x01b']):
            with self.assertRaises(pdfform.FormError, msg=str(bad)): pdfform.parse_values(bad, fields)
        self.assertEqual(pdfform.parse_values(['turno\t', 'estado\t'], fields), {'turno': '', 'estado': ''})

    def test_readonly_field_refused(self):
        fields = list(self.fields(self.form(readonly_name=True)).values())
        with self.assertRaises(pdfform.FormError): pdfform.parse_values(['nome\tx'], fields)

    def test_sign_area_parse(self):
        self.assertEqual(pdfform.parse_sign_area('1:10,20,300,400', 2), (1, (10, 20, 300, 400)))
        for bad in ('3:0,0,10,10', '1:10,0,10,10', 'x', 7): 
            with self.assertRaises(pdfform.FormError): pdfform.parse_sign_area(bad, 2)

    def test_inspect_pdf_reports_fields(self):
        info = pdfinfo.inspect_pdf(self.form()); self.assertTrue(info['forms']); self.assertEqual(len(info['form_fields']), 5)
        self.assertEqual(pdfinfo.inspect_pdf(self.plain())['form_fields'], [])


@NEEDS_PDFIUM
class EngineTests(Base):
    def test_fill_keeps_form_editable(self):
        source = self.form(); before = source.read_bytes()
        out = self.run_fill(source, form_values=FULL)
        self.assertEqual(out.name, 'form-preenchido.pdf'); self.assertEqual(source.read_bytes(), before)
        found = self.fields(out)
        self.assertEqual({n: f['value'] for n, f in found.items()}, {'nome': 'Maria Souza', 'endereco.cidade': 'Belém', 'aceito': 'on', 'turno': 'tarde', 'estado': 'SP'})
        self.assertIn('/AcroForm', PdfReader(str(out)).trailer['/Root'])

    def test_partial_fill_leaves_other_fields(self):
        found = self.fields(self.run_fill(self.form(), form_values=['nome\tAna']))
        self.assertEqual((found['nome']['value'], found['aceito']['value'], found['turno']['value']), ('Ana', 'off', ''))

    def test_flatten_draws_values_and_removes_fields(self):
        out = self.run_fill(self.form(), form_values=FULL, form_flatten='on')
        reader = PdfReader(str(out)); text = reader.pages[0].extract_text()
        self.assertNotIn('/AcroForm', reader.trailer['/Root']); self.assertIsNone(reader.pages[0].get('/Annots'))
        for word in ('Maria Souza', 'Belém', 'SP'): self.assertIn(word, text)
        self.assertNotIn('PA', text.replace('PARA', ''))                                  # lista suspensa mostra só o valor escolhido
        gray = self.darkest(out); self.assertLess(min(gray.getdata()), 80)

    def test_flatten_without_changes_and_without_fields(self):
        self.assertTrue(self.run_fill(self.form(), form_flatten='on').exists())
        with self.assertRaisesRegex(ConversionError, 'não tem campos'): self.run_fill(self.plain(), form_flatten='on')

    def test_checkbox_off_value_and_radio_clear(self):
        first = self.run_fill(self.form(), form_values=['aceito\ton', 'turno\tmanha'])
        second = self.run_fill(first, form_values=['aceito\toff', 'turno\t'])
        found = self.fields(second); self.assertEqual((found['aceito']['value'], found['turno']['value']), ('off', ''))

    def test_xfa_is_dropped(self):
        writer = PdfWriter(clone_from=str(self.form())); writer._root_object['/AcroForm'][NameObject('/XFA')] = writer._add_object(__import__('pypdf').generic.ArrayObject())
        path = self.root / 'xfa.pdf'; writer.write(str(path))
        out = self.run_fill(path, form_values=['nome\tX1'])
        self.assertNotIn('/XFA', PdfReader(str(out)).trailer['/Root']['/AcroForm'])

    def test_signature_image_placed_in_area(self):
        out = self.run_fill(self.plain(), sign_image=str(self.signature()), sign_areas=['1:100,600,700,900'])
        gray = self.darkest(out, scale=2); self.assertEqual(gray.size, (800, 600))
        region = gray.crop((int(800 * .1), int(600 * .6), int(800 * .7), int(600 * .9)))
        self.assertLess(min(region.getdata()), 120)                                          # traço azul escuro dentro da área
        outside = gray.crop((0, 0, 800, int(600 * .55))); self.assertEqual(min(outside.getdata()), 255)

    def test_signature_respects_rotation(self):
        for rotate in (90, 180, 270):
            out = self.run_fill(self.plain(f'r{rotate}.pdf', rotate), sign_image=str(self.signature()), sign_areas=['1:0,0,1000,300'])
            gray = self.darkest(out, scale=1); w, h = gray.size
            top = gray.crop((0, 0, w, int(h * .3))); rest = gray.crop((0, int(h * .35), w, h))
            self.assertLess(min(top.getdata()), 120, rotate); self.assertEqual(min(rest.getdata()), 255, rotate)       # a assinatura fica no alto, como aparece

    def test_signature_jpeg_without_alpha_and_multiple_areas(self):
        out = self.run_fill(self.plain(), sign_image=str(self.signature('a.jpg', alpha=False)), sign_areas=['1:0,0,400,300', '1:500,700,1000,1000'])
        self.assertLess(min(self.darkest(out).getdata()), 120)

    def test_fill_and_sign_together_and_two_pages(self):
        writer = PdfWriter(clone_from=str(self.form())); writer.add_blank_page(400, 300); path = self.root / 'duas.pdf'; writer.write(str(path))
        out = self.run_fill(path, form_values=['nome\tAna'], form_flatten='on', sign_image=str(self.signature()), sign_areas=['2:100,100,900,500'])
        self.assertEqual(len(PdfReader(str(out)).pages), 2); self.assertLess(min(self.darkest(out, 2).getdata()), 120)

    def test_validation_errors(self):
        form = self.form(); sig = str(self.signature())
        with self.assertRaisesRegex(ConversionError, 'ao menos um campo'): self.run_fill(form)
        with self.assertRaisesRegex(ConversionError, 'não existe'): self.run_fill(form, form_values=['xx\t1'])
        with self.assertRaisesRegex(ConversionError, 'fora da página'): self.run_fill(form, sign_image=sig, sign_areas=['5:0,0,10,10'])
        with self.assertRaisesRegex(ConversionError, 'Marque a área'): self.run_fill(form, form_values=['nome\tA'], sign_image=sig)
        with self.assertRaisesRegex(ConversionError, 'Escolha a imagem'): self.run_fill(form, sign_areas=['1:0,0,10,10'])
        with self.assertRaisesRegex(ConversionError, 'PNG, JPEG'): self.run_fill(form, sign_image=str(self.root / 'x.txt'), sign_areas=['1:0,0,10,10'])
        with self.assertRaisesRegex(ConversionError, 'não foi encontrada'): self.run_fill(form, sign_image=str(self.root / 'nada.png'), sign_areas=['1:0,0,10,10'])
        bad = self.root / 'ruim.png'; bad.write_bytes(b'nao e imagem')
        with self.assertRaisesRegex(ConversionError, 'Não foi possível abrir'): self.run_fill(form, sign_image=str(bad), sign_areas=['1:0,0,10,10'])
        with self.assertRaisesRegex(ConversionError, 'no máximo'): self.run_fill(form, sign_image=sig, sign_areas=['1:0,0,10,10'] * 11)

    def test_encrypted_pdf_refused(self):
        writer = PdfWriter(clone_from=str(self.form())); writer.encrypt('senha1234'); locked = self.root / 'l.pdf'; writer.write(str(locked))
        with self.assertRaisesRegex(ConversionError, 'senha'): self.run_fill(locked, form_values=['nome\tx'])

    def test_loss_report_says_not_a_certified_signature(self):
        text = ' '.join(engine.loss_report(['/x.pdf'], FM)); self.assertIn('NÃO é assinatura digital certificada', text); self.assertIn(FM, engine.OPERATIONS)


@NEEDS_PDFIUM
class ControllerTests(Base):
    def test_options_validated(self):
        controller = JobController(capabilities={'images': (True, 'ok'), 'pdf': (True, 'ok')}); source = str(self.form()); controller.notify = mock.Mock()
        with mock.patch.object(JobController, '_start_next'):
            self.assertTrue(controller.start_job([source], FM, {'form_values': FULL, 'form_flatten': 'on', 'sign_image': '/tmp/a.png', 'sign_areas': ['1:0,0,10,10']}))
            for bad in ({'form_values': 'x'}, {'form_values': [5]}, {'form_values': ['a'] * 201}, {'sign_areas': ['1:0,0,1,1'] * 11}, {'sign_image': 5}, {'sign_image': 'x' * 1100}):
                self.assertFalse(controller.start_job([source], FM, bad), bad)
            self.assertFalse(controller.start_job([source], 'Compress PDF', {'form_values': ['a\tb']}))


@NEEDS_PDFIUM
class PanelTests(Base):
    def panel(self, source):
        panel = FeaturePanel(JobController(capabilities={'images': (True, 'ok'), 'pdf': (True, 'ok')})); panel.resize(1200, 800)
        panel.form_stage.loader = lambda job: runner.run_pdf_op(job); self.addCleanup(panel.form_stage.shutdown)
        panel.set_files([str(source)], FM); APP.processEvents(); return panel

    def select(self, panel, left=.1, top=.2, width=.5, height=.3):
        from PySide6.QtCore import QRectF
        from PySide6.QtWidgets import QGraphicsRectItem
        view = panel.form_stage.page_view; bounds = view.image_bounds()
        view.crop_rect = QGraphicsRectItem(QRectF(bounds.left() + bounds.width() * left, bounds.top() + bounds.height() * top, bounds.width() * width, bounds.height() * height))
        view.graphics_scene.addItem(view.crop_rect); view.selection_changed.emit(); APP.processEvents()

    def test_fields_listed_and_unchanged_form_disabled(self):
        with mock.patch.object(JobController, '_start_next'):
            panel = self.panel(self.form()); self.assertEqual(set(panel.fm_editors), {'nome', 'endereco.cidade', 'aceito', 'turno', 'estado'})
            self.assertEqual(panel.run_button.text(), 'Gerar PDF preenchido'); self.assertFalse(panel.run_button.isEnabled()); self.assertIn('Altere algum campo', panel.fm_info.text())

    def test_editing_fields_builds_values(self):
        with mock.patch.object(JobController, '_start_next'):
            panel = self.panel(self.form())
            panel.fm_editors['nome'][1].setText('Ana Lima'); panel.fm_editors['aceito'][1].setChecked(True); panel.fm_editors['turno'][1].setCurrentText('manha'); panel.fm_editors['estado'][1].setCurrentText('AM'); APP.processEvents()
            self.assertTrue(panel.run_button.isEnabled()); values = panel._form_values()
            self.assertEqual(sorted(values['form_values']), sorted(['nome\tAna Lima', 'aceito\ton', 'turno\tmanha', 'estado\tAM'])); self.assertNotIn('form_flatten', values)
            panel.fm_flatten.setCurrentIndex(1); APP.processEvents(); self.assertEqual(panel._form_values()['form_flatten'], 'on')

    def test_signature_flow_requires_image_and_area(self):
        with mock.patch.object(JobController, '_start_next'):
            panel = self.panel(self.plain()); self.assertIn('não tem campos', panel.fm_info.text()); self.assertFalse(panel.run_button.isEnabled())
            self.select(panel); self.assertFalse(panel.fm_add_button.isEnabled())            # sem imagem ainda
            panel.set_sign_image(str(self.signature())); APP.processEvents(); self.assertTrue(panel.fm_add_button.isEnabled()); self.assertFalse(panel.run_button.isEnabled()); self.assertIn('ainda não marcada', panel.fm_info.text())
            panel.add_form_area(); APP.processEvents(); self.assertTrue(panel.run_button.isEnabled()); self.assertEqual(len(panel.form_stage.page_view.committed), 1)
            values = panel._form_values(); self.assertEqual(values['sign_image'], panel.fm_image); self.assertEqual(len(values['sign_areas']), 1); self.assertIn('não é assinatura digital certificada', panel.fm_info.text())
            panel.undo_form_area(); APP.processEvents(); self.assertFalse(panel.run_button.isEnabled()); self.assertIn('Marque na página', panel.fm_info.text())

    def test_run_sends_options_and_resets(self):
        with mock.patch.object(JobController, '_start_next'), mock.patch.object(JobController, 'start_job') as start:
            panel = self.panel(self.form()); panel.fm_editors['nome'][1].setText('Ana'); APP.processEvents(); panel.run_selected()
            args = start.call_args[0]; self.assertEqual(args[1], FM); self.assertEqual(args[2]['form_values'], ['nome\tAna'])
            APP.processEvents(); self.assertEqual(panel.fm_areas, []); self.assertFalse(panel.run_button.isEnabled())

    def test_end_to_end_job_options_work_in_engine(self):
        with mock.patch.object(JobController, '_start_next'), mock.patch.object(JobController, 'start_job') as start:
            source = self.form(); panel = self.panel(source); panel.fm_editors['nome'][1].setText('Rita'); panel.fm_flatten.setCurrentIndex(1); APP.processEvents(); panel.run_selected()
            options = dict(start.call_args[0][2]); out = Path(convert({'paths': [str(source)], 'target': FM, **options})[0])
            self.assertIn('Rita', PdfReader(str(out)).pages[0].extract_text())

    def test_multiple_files_and_encrypted(self):
        with mock.patch.object(JobController, '_start_next'):
            panel = self.panel(self.form()); panel.set_files([str(self.form('a.pdf')), str(self.form('b.pdf'))], FM); APP.processEvents()
            self.assertIn('um PDF por vez', panel._form_state()[0])
        writer = PdfWriter(clone_from=str(self.form())); writer.encrypt('senha1234'); locked = self.root / 'l.pdf'; writer.write(str(locked))
        with mock.patch.object(JobController, '_start_next'):
            panel = self.panel(locked); self.assertFalse(panel.run_button.isEnabled())


if __name__ == '__main__':
    unittest.main()
