"""Proteger e remover senha do PDF (0.9.39): AES-256, permissões, tentativa única, restrições só com a senha de proprietário, senha fora de mensagens/relatório e painel."""
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
from pypdf.constants import UserAccessPermissions as Perm
from PySide6.QtWidgets import QApplication

import engine
import pdfinfo
import runner
from engine import ConversionError, convert
from tray_app import JobController
from workspace_panel import FeaturePanel

APP = QApplication.instance() or QApplication([])
NEEDS_PDFIUM = unittest.skipUnless(pdfinfo.preview_available(), 'pypdfium2 não instalado')
PR, UN = 'Protect PDF', 'Unprotect PDF'
SECRET = 'S3nha-Muito-Secreta'
OWNER = 'Dono-Permissoes-9'


class Base(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name); self.addCleanup(self.temp.cleanup)

    def pdf(self, name='doc.pdf'):
        writer = PdfWriter(); writer.add_blank_page(200, 200); writer.add_blank_page(200, 200); writer.add_outline_item('Capítulo', 1)
        writer.add_metadata({'/Title': 'Contrato'}); path = self.root / name; writer.write(str(path)); return path

    def protected(self, **extra):
        return Path(convert({'paths': [str(self.pdf())], 'target': PR, 'pdf_password': SECRET, **extra})[0])


class ProtectTests(Base):
    def test_aes256_and_needs_password(self):
        out = self.protected(); self.assertEqual(out.name, 'doc-protegido.pdf'); data = out.read_bytes()
        self.assertIn(b'/AESV3', data); self.assertNotIn(b'Contrato', data); self.assertNotIn(SECRET.encode(), data)
        reader = PdfReader(str(out)); self.assertTrue(reader.is_encrypted); self.assertEqual(reader.decrypt(''), 0); self.assertEqual(reader.decrypt('outra'), 0)
        reader = PdfReader(str(out)); self.assertNotEqual(reader.decrypt(SECRET), 0); self.assertEqual(len(reader.pages), 2); self.assertEqual(reader.metadata['/Title'], 'Contrato')
        self.assertEqual([item.title for item in reader.outline], ['Capítulo'])

    def test_permissions_need_owner_password(self):
        source = str(self.pdf())
        for extra in ({'perm_print': 'off'}, {'perm_copy': 'off', 'pdf_owner_password': SECRET}, {'perm_edit': 'off', 'pdf_owner_password': 'ab'}):
            with self.assertRaises(ConversionError, msg=str(extra)) as ctx: convert({'paths': [source], 'target': PR, 'pdf_password': SECRET, **extra})
            self.assertNotIn(SECRET, str(ctx.exception))
        out = self.protected(pdf_owner_password=OWNER, perm_print='off', perm_copy='off')
        reader = PdfReader(str(out)); self.assertEqual(reader.decrypt(SECRET), 1); flags = reader.user_access_permissions
        self.assertFalse(flags & Perm.PRINT); self.assertFalse(flags & Perm.EXTRACT); self.assertTrue(flags & Perm.MODIFY)
        self.assertEqual(PdfReader(str(out)).decrypt(OWNER), 2)

    def test_validation(self):
        source = str(self.pdf())
        for bad in ({'pdf_password': 'abc'}, {'pdf_password': ''}, {'pdf_password': 'x' * 128}, {'pdf_password': 'abcd\n'}, {'pdf_owner_password': 'ab'}, {'perm_print': 'x'}):
            with self.assertRaises(ConversionError, msg=str(bad)): convert({'paths': [source], 'target': PR, **{'pdf_password': SECRET, **bad}})
        locked = self.protected()
        with self.assertRaises(ConversionError) as ctx: convert({'paths': [str(locked)], 'target': PR, 'pdf_password': SECRET})
        self.assertIn('tem senha', str(ctx.exception))
        (self.root / 'a.txt').write_text('x')
        with self.assertRaises(ConversionError): convert({'paths': [str(self.root / 'a.txt')], 'target': PR, 'pdf_password': SECRET})


class UnprotectTests(Base):
    def test_remove_with_right_password_only(self):
        locked = self.protected(); before = sorted(p.name for p in self.root.iterdir())
        for wrong in ('errada', ''):
            with self.assertRaises(ConversionError, msg=wrong) as ctx: convert({'paths': [str(locked)], 'target': UN, 'pdf_password': wrong})
            self.assertIn('não abriu', str(ctx.exception)); self.assertNotIn('errada', str(ctx.exception))
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), before)
        out = Path(convert({'paths': [str(locked)], 'target': UN, 'pdf_password': SECRET})[0])
        reader = PdfReader(str(out)); self.assertFalse(reader.is_encrypted); self.assertEqual(len(reader.pages), 2); self.assertEqual(reader.metadata['/Title'], 'Contrato')
        self.assertEqual([item.title for item in reader.outline], ['Capítulo']); self.assertTrue(locked.exists())

    def test_restrictions_need_owner_password(self):
        locked = self.protected(pdf_owner_password=OWNER, perm_print='off', perm_copy='off', perm_edit='off')
        with self.assertRaises(ConversionError) as ctx: convert({'paths': [str(locked)], 'target': UN, 'pdf_password': SECRET})
        self.assertIn('senha de permissões', str(ctx.exception)); self.assertNotIn(SECRET, str(ctx.exception))
        out = Path(convert({'paths': [str(locked)], 'target': UN, 'pdf_password': OWNER})[0]); self.assertFalse(PdfReader(str(out)).is_encrypted)

    def test_owner_only_pdf_needs_owner_password(self):
        writer = PdfWriter(); writer.add_blank_page(100, 100); writer.encrypt('', OWNER, algorithm='AES-256', permissions_flag=Perm.PRINT)
        path = self.root / 'so-dono.pdf'; writer.write(str(path))
        with self.assertRaises(ConversionError): convert({'paths': [str(path)], 'target': UN, 'pdf_password': ''})
        self.assertFalse(PdfReader(str(convert({'paths': [str(path)], 'target': UN, 'pdf_password': OWNER})[0])).is_encrypted)

    def test_not_encrypted_and_other_tools_point_here(self):
        with self.assertRaises(ConversionError) as ctx: convert({'paths': [str(self.pdf())], 'target': UN, 'pdf_password': SECRET})
        self.assertIn('não tem senha', str(ctx.exception))
        with self.assertRaises(ConversionError) as ctx: convert({'paths': [str(self.protected())], 'target': 'PDF → Text'})
        self.assertIn('Remover senha', str(ctx.exception))


class PrivacyTests(Base):
    def controller(self):
        patcher = mock.patch.object(JobController, '_start_next'); patcher.start(); self.addCleanup(patcher.stop)
        return JobController(capabilities={'images': (True, 'ok'), 'pdf': (True, 'ok')})

    def test_runner_roundtrip_and_no_password_in_reports(self):
        out = runner.run_job({'paths': [str(self.pdf())], 'target': PR, 'pdf_password': SECRET}); self.assertEqual([Path(p).name for p in out], ['doc-protegido.pdf'])
        for target in (PR, UN):
            text = ' '.join(engine.loss_report(['/x.pdf'], target, {'pdf_password': SECRET, 'pdf_owner_password': OWNER}))
            self.assertNotIn(SECRET, text); self.assertNotIn(OWNER, text)
        self.assertIn('AES-256', ' '.join(engine.loss_report(['/x.pdf'], PR))); self.assertIn('não adivinha nem quebra', ' '.join(engine.loss_report(['/x.pdf'], UN)))
        self.assertIn(PR, engine.OPERATIONS); self.assertIn(UN, engine.OPERATIONS)

    def test_controller_option_types_and_report(self):
        source = str(self.pdf()); controller = self.controller()
        self.assertTrue(controller.start_job([source], PR, {'pdf_password': SECRET, 'pdf_owner_password': OWNER, 'perm_print': 'off', 'perm_copy': 'on', 'perm_edit': 'on'}))
        self.assertNotIn(SECRET, ' '.join(getattr(controller, 'last_report', []) or []))
        for bad in ({'pdf_password': 1234}, {'perm_print': 0}, {'pdf_owner_password': 'x' * 201}):
            self.assertFalse(self.controller().start_job([source], PR, bad), msg=str(bad))

    def test_worker_error_never_echoes_password(self):
        with self.assertRaises(Exception) as ctx: runner.run_job({'paths': [str(self.protected())], 'target': UN, 'pdf_password': 'Chute-Errado-77'})
        self.assertNotIn('Chute-Errado-77', str(ctx.exception))


@NEEDS_PDFIUM
class PanelTests(Base):
    def panel(self, source, tool):
        panel = FeaturePanel(JobController(capabilities={'images': (True, 'ok'), 'pdf': (True, 'ok')})); panel.resize(1100, 760)
        panel.pdf_stage.loader = lambda job: runner.run_pdf_op(job); self.addCleanup(panel.pdf_stage.shutdown)
        panel.set_files([str(source)], tool); APP.processEvents(); return panel

    def test_protect_controls(self):
        with mock.patch.object(JobController, '_start_next') as start:
            panel = self.panel(self.pdf(), PR); self.assertFalse(panel.run_button.isEnabled()); self.assertIn('pelo menos 4', panel.pw_info.text())
            self.assertEqual(panel.pw_pass.echoMode().name, 'Password')
            panel.pw_pass.setText(SECRET); panel.pw_repeat.setText('diferente'); APP.processEvents(); self.assertIn('não são iguais', panel.pw_info.text()); self.assertFalse(panel.run_button.isEnabled())
            panel.pw_repeat.setText(SECRET); APP.processEvents(); self.assertTrue(panel.run_button.isEnabled()); self.assertEqual(panel.run_button.text(), 'Proteger com senha')
            panel.pw_print.setCurrentIndex(1); APP.processEvents(); self.assertFalse(panel.run_button.isEnabled()); self.assertIn('senha de permissões', panel.pw_info.text())
            panel.pw_owner.setText(OWNER); APP.processEvents(); self.assertTrue(panel.run_button.isEnabled())
            self.assertNotIn(SECRET, panel.pw_info.text()); panel.run_selected(); self.assertTrue(start.called)
            self.assertEqual((panel.pw_pass.text(), panel.pw_repeat.text(), panel.pw_owner.text()), ('', '', ''))        # senha some da tela ao iniciar

    def test_unprotect_controls_and_clearing(self):
        locked = self.protected()
        with mock.patch.object(JobController, '_start_next'):
            panel = self.panel(locked, UN); self.assertTrue(panel.run_button.isEnabled()); self.assertEqual(panel.run_button.text(), 'Remover senha')
            panel.pw_current.setText(SECRET); self.assertEqual(panel._password_values(), {'pdf_password': SECRET})
            panel.set_files([str(locked)], UN); self.assertEqual(panel.pw_current.text(), '')
            plain = self.panel(self.pdf('plano.pdf'), UN); self.assertFalse(plain.run_button.isEnabled()); self.assertIn('não tem senha', plain.pw_info.text())
            already = self.panel(locked, PR); self.assertFalse(already.run_button.isEnabled()); self.assertIn('já tem senha', already.pw_info.text())


if __name__ == '__main__':
    unittest.main()
