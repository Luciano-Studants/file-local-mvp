"""Portão B da categoria PDF (0.9.42): o corpus, os detectores da suíte de qualidade e uma execução completa (--only pdf --fast) sem falhas bloqueantes."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / 'tools'))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PIL import Image
from pypdf import PdfReader

import pdfinfo
import quality_suite as qs

NEEDS_PDFIUM = unittest.skipUnless(pdfinfo.preview_available(), 'pypdfium2 não instalado')


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup); self.root = Path(self.tmp.name)


class CorpusTests(Base):
    def test_corpus_has_every_kind_and_files_behave(self):
        files = qs.write_pdf_corpus(self.root)
        for key in ('text', 'plain', 'scan', 'form', 'locked', 'truncated', 'corrupt', 'fake', 'p200', 'p201', 'giant', 'js', 'rotated', 'p50'):
            self.assertTrue(files[key].is_file(), key)
        self.assertEqual(len(PdfReader(str(files['p200'])).pages), 200); self.assertEqual(len(PdfReader(str(files['p201'])).pages), 201)
        self.assertEqual(len(PdfReader(str(files['rotated'])).pages), 3); self.assertTrue(PdfReader(str(files['locked'])).is_encrypted)
        self.assertEqual(float(PdfReader(str(files['giant'])).pages[0].mediabox.width), 14400.0)
        with self.assertRaises(Exception): PdfReader(str(files['fake']), strict=True).pages

    def test_corpus_is_deterministic(self):
        a = qs.write_pdf_corpus(self.root / 'a'); b = qs.write_pdf_corpus(self.root / 'b')
        for key in ('plain', 'p200', 'rotated', 'giant'):
            self.assertEqual(a[key].read_bytes(), b[key].read_bytes(), key)


class DetectorTests(Base):
    def test_leak_detector_sees_secrets_in_metadata_attachments_and_text(self):
        files = qs.write_pdf_corpus(self.root); blob = qs.pdf_blob(files['text'])
        for secret in (b'Maria', b'123.456.789-09', b'segredo.txt', b'Dossi'):
            self.assertIn(secret, blob, secret)
        self.assertNotIn(b'Maria', qs.pdf_blob(files['p200']))

    def test_identical_detects_differences_in_opaque_images(self):
        a = Image.new('RGB', (10, 10), 'white'); b = a.copy(); b.putpixel((3, 3), (250, 250, 250))
        self.assertFalse(qs.identical(a, b)); self.assertTrue(qs.identical(a, a.copy()))

    def test_no_network_context_counts_attempts(self):
        import socket
        with qs.NoNetwork() as net:
            with self.assertRaises(OSError): socket.create_connection(('127.0.0.1', 9))
        self.assertEqual(net.attempts, 1)
        with self.assertRaises(OSError): socket.create_connection(('127.0.0.1', 9), timeout=0.2)       # restaurado: erro de conexão real, não o bloqueio

    def test_score_and_leftovers(self):
        self.assertEqual((qs.score(0, 0), qs.score(9, 1), qs.score(3, 1)), (100, 90, 75))
        (self.root / 'a.part').write_text('x'); (self.root / 'ok.pdf').write_text('x')
        self.assertEqual(qs.leftovers(self.root), ['a.part'])


@NEEDS_PDFIUM
class FullRunTests(Base):
    def test_pdf_quality_run_passes_with_no_blocking_failures(self):
        out = self.root / 'rel'
        result = subprocess.run([sys.executable, str(ROOT / 'tools' / 'quality_suite.py'), '--only', 'pdf', '--fast', '--out', str(out)], cwd=str(ROOT), capture_output=True, text=True, timeout=600)
        self.assertEqual(result.returncode, 0, result.stdout[-1500:] + result.stderr[-800:])
        data = json.loads((out / 'quality-report.json').read_text(encoding='utf8'))
        pdf = [r for r in data['results'] if r['func'].startswith('PDF')]
        self.assertGreaterEqual(len(pdf), 40); self.assertFalse([r for r in pdf if r['status'] == 'FALHOU'])
        self.assertIn('nenhuma função abaixo de 80', (out / 'quality-report.md').read_text(encoding='utf8'))


if __name__ == '__main__':
    unittest.main()
