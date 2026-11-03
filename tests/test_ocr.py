"""OCR com o Tesseract externo (0.9.22): núcleo `ocr.py`, opções, relatório, texto, PDF pesquisável, segurança, worker e painel.

Os testes que rodam o Tesseract de verdade são pulados quando ele (ou os dados de idioma) não está instalado.
"""
import hashlib
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PIL import Image, ImageDraw, ImageFont
from PySide6.QtWidgets import QApplication

import engine
import ocr
import tool_registry
from engine import ConversionError, convert, loss_report, ocr_options_from, ocr_prepare
from tray_app import FeaturePanel, JobController

READY = ocr.status()[0] and {'por', 'eng'} <= ocr.available_languages()
def _find_font():
    """Fonte com acentos em qualquer sistema (o Pillow também procura nas pastas de fontes do sistema pelo nome)."""
    for candidate in ('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 'DejaVuSans.ttf', 'segoeui.ttf', 'arial.ttf', 'Arial.ttf'):
        try:
            ImageFont.truetype(candidate, 20)
            return candidate
        except OSError:
            continue
    return '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'


FONT = _find_font()
LINES = ['Conversão offline de arquivos', 'Olá, mundo! Ação e emoção: 123,45', 'Arquivo Local — versão 0.9.22']


def text_image(size=34, width=1000, background='white', mode='RGB', lines=LINES):
    try: font = ImageFont.truetype(FONT, size)
    except OSError: font = ImageFont.load_default(size)
    im = Image.new('RGB', (width, 40 + len(lines) * round(size * 2.4)), background); draw = ImageDraw.Draw(im)
    for index, line in enumerate(lines): draw.text((30, 30 + index * round(size * 2.4)), line, font=font, fill='black')
    return im.convert(mode)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class OcrCoreTests(unittest.TestCase):
    def test_lists(self):
        self.assertEqual(tuple(ocr.LANGS), ('por+eng', 'por', 'eng')); self.assertEqual(tuple(ocr.PSM), ('auto', 'block', 'line', 'sparse'))
        self.assertEqual(ocr.languages_for('por+eng'), ['por', 'eng'])
        with self.assertRaises(ocr.OcrError): ocr.languages_for('por;rm')

    def test_clean_text(self):
        self.assertEqual(ocr.clean_text('a  \r\nb\f\n\n\n\nc\n\n'), 'a\nb\n\nc\n')
        self.assertEqual(ocr.clean_text('  \n\f'), '')

    def test_missing_tesseract_is_reported(self):
        with patch.dict(ocr._cache, {'exe': None, 'langs': set()}, clear=True):
            ocr._cache['exe'] = None
            ready, message = ocr.status()
            self.assertFalse(ready); self.assertIn('Tesseract não foi encontrado', message)
            with self.assertRaises(ocr.OcrError): ocr.check_ready('por')

    def test_missing_language_data_is_reported(self):
        with patch.dict(ocr._cache, {'exe': '/usr/bin/true', 'langs': set()}, clear=True):
            self.assertIn('sem dados de idioma', ocr.status()[1])
        with patch.dict(ocr._cache, {'exe': '/usr/bin/true', 'langs': {'eng'}}, clear=True):
            with self.assertRaises(ocr.OcrError) as caught: ocr.check_ready('por')
            self.assertIn('por', str(caught.exception))

    def test_invalid_arguments_are_refused_before_running(self):
        with patch.dict(ocr._cache, {'exe': '/usr/bin/true', 'langs': {'por', 'eng'}}, clear=True), patch.object(ocr, '_run') as run:
            for args in (('x.png', 'xx', 'auto', 'txt'), ('x.png', 'por', 'auto', 'html'), ('x.png', 'por', '99', 'txt'), ('x.png', 'por', 'auto', 'docx')):
                with self.assertRaises(ocr.OcrError): ocr.recognize(*args, '/tmp')
            run.assert_not_called()

    def test_timeout_message(self):
        with patch('subprocess.run', side_effect=subprocess.TimeoutExpired('tesseract', 1)):
            with self.assertRaises(ocr.OcrError) as caught: ocr._run(['x'], '/tmp', timeout=1)
            self.assertIn('foi interrompido', str(caught.exception))

    def test_command_has_no_shell_and_no_network_env(self):
        seen = {}

        def fake(arguments, **kwargs):
            seen.update(arguments=arguments, **kwargs)
            raise subprocess.TimeoutExpired('x', 1)
        with patch('subprocess.run', side_effect=fake), patch.dict(os.environ, {'TESSDATA_PREFIX': '/evil'}):
            with self.assertRaises(ocr.OcrError): ocr._run(['/usr/bin/tesseract', 'a.png', 'out'], '/tmp')
        self.assertIs(seen['shell'], False); self.assertEqual(seen['stdin'], subprocess.DEVNULL)
        self.assertNotIn('TESSDATA_PREFIX', seen['env']); self.assertEqual(seen['env']['OMP_THREAD_LIMIT'], '1')

    def test_bundled_data_has_licensed_files(self):
        folder = Path(__file__).resolve().parents[1] / 'tessdata'
        for name in ('por.traineddata', 'eng.traineddata', 'pdf.ttf', 'LICENSE-tessdata_fast.txt'): self.assertTrue((folder / name).is_file(), name)


class OcrOptionTests(unittest.TestCase):
    def test_defaults_and_validation(self):
        self.assertEqual(ocr_options_from({}), ('por+eng', 'auto')); self.assertEqual(ocr_options_from({'ocr_lang': 'eng', 'ocr_psm': 'line'}), ('eng', 'line'))
        for bad in ({'ocr_lang': 'fra'}, {'ocr_lang': 3}, {'ocr_psm': 'x'}, {'ocr_lang': 'por+eng+deu'}):
            with self.assertRaises(ConversionError): ocr_options_from(bad)
        self.assertEqual(ocr_options_from({'ocr_lang': 'zzz', 'ocr_psm': None}, strict=False), ('por+eng', 'auto'))

    def test_registry(self):
        for key, target, ext in (('ocr_text', 'OCR → Text', 'txt'), ('ocr_pdf', 'OCR → PDF', 'pdf')):
            spec = tool_registry.BY_TARGET[target]
            self.assertEqual((spec.key, spec.ext, spec.group, spec.str_options), (key, ext, 'read', ('ocr_lang', 'ocr_psm')))
            self.assertNotIn(target, tool_registry.FORMAT_TARGETS); self.assertIn(target, engine.RENAMEABLE_TARGETS)
        self.assertEqual(tool_registry.GROUPS['read'][0], 'Ler texto'); self.assertIn('ocr_lang', tool_registry.all_str_options())
        self.assertEqual(tool_registry.BY_TARGET['Compress → JPEG'].group, 'transform')

    def test_prepare_flattens_scales_and_limits(self):
        rgba = Image.new('RGBA', (1200, 300), (0, 0, 0, 0)); out = ocr_prepare(rgba, 'txt')
        self.assertEqual((out.mode, out.size, out.getpixel((5, 5))), ('RGB', (1200, 300), (255, 255, 255)))
        small = ocr_prepare(Image.new('RGB', (300, 100), 'white'), 'txt'); self.assertEqual(small.size, (600, 200))
        keep = ocr_prepare(Image.new('RGB', (300, 100), 'white'), 'pdf'); self.assertEqual(keep.size, (300, 100))
        huge = ocr_prepare(Image.new('L', (ocr.MAX_SIDE + 1000, 40), 255), 'txt'); self.assertEqual(max(huge.size), ocr.MAX_SIDE)
        palette = ocr_prepare(Image.new('P', (1200, 100)), 'pdf'); self.assertEqual(palette.mode, 'RGB')

    def test_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'a.png'; text_image().save(path)
            for target in ('OCR → Text', 'OCR → PDF'):
                text = ' '.join(loss_report([str(path)], target, {'ocr_lang': 'por'}))
                self.assertIn('aproximado', text); self.assertIn('Português', text); self.assertIn('internet', text)
            self.assertIn('texto invisível', ' '.join(loss_report([str(path)], 'OCR → PDF', {})))
            self.assertIn('UTF-8', ' '.join(loss_report([str(path)], 'OCR → Text', {})))
            with patch.dict(ocr._cache, {'exe': None, 'langs': set()}, clear=True):
                ocr._cache['exe'] = None
                self.assertIn('Tesseract não foi encontrado', ' '.join(loss_report([str(path)], 'OCR → Text', {})))


class OcrFailureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name); self.out = self.root / 'out'; self.out.mkdir()
        self.source = self.root / 'a.png'; text_image().save(self.source)

    def tearDown(self):
        self.temp.cleanup()

    def test_without_tesseract_nothing_is_created(self):
        before = digest(self.source)
        with patch.dict(ocr._cache, {'exe': None, 'langs': set()}, clear=True):
            ocr._cache['exe'] = None
            for target in ('OCR → Text', 'OCR → PDF'):
                with self.assertRaises(ConversionError) as caught: convert({'paths': [str(self.source)], 'target': target, 'output': str(self.out)})
                self.assertIn('Tesseract', str(caught.exception))
        self.assertEqual(list(self.out.iterdir()), []); self.assertEqual(digest(self.source), before)
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ['a.png', 'out'])

    def test_invalid_options_and_inputs(self):
        for extra in ({'ocr_lang': 'fra'}, {'ocr_psm': 'zzz'}):
            with self.assertRaises(ConversionError): convert({'paths': [str(self.source)], 'target': 'OCR → Text', 'output': str(self.out), **extra})
        pdf = self.root / 'x.pdf'; pdf.write_bytes(b'%PDF-1.4\n')
        with self.assertRaises(ConversionError) as caught: convert({'paths': [str(pdf)], 'target': 'OCR → Text', 'output': str(self.out)})
        self.assertIn('imagem suportada', str(caught.exception))
        with self.assertRaises(ConversionError): convert({'paths': [str(self.source), str(self.source)], 'target': 'OCR → PDF', 'output': str(self.out)})
        self.assertEqual(list(self.out.iterdir()), [])

    def test_tesseract_failure_is_reported_in_portuguese(self):
        with patch.dict(ocr._cache, {'exe': sys.executable, 'langs': {'por', 'eng'}}, clear=True):      # um programa que sempre falha com estes argumentos (vale no Windows e no Linux)
            with self.assertRaises(ConversionError) as caught: convert({'paths': [str(self.source)], 'target': 'OCR → Text', 'output': str(self.out)})
            self.assertIn('não conseguiu reconhecer', str(caught.exception))
        self.assertEqual(list(self.out.iterdir()), [])


@unittest.skipUnless(READY, 'Tesseract com dados por e eng não está instalado')
class OcrRealTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name); self.out = self.root / 'out'; self.out.mkdir()
        self.source = self.root / 'a.png'; text_image().save(self.source)

    def tearDown(self):
        self.temp.cleanup()

    def run_ocr(self, target='OCR → Text', source=None, **extra):
        return Path(convert({'paths': [str(source or self.source)], 'target': target, 'output': str(self.out), **extra})[0])

    def test_text_output(self):
        before = digest(self.source)
        result = self.run_ocr(ocr_lang='por')
        self.assertEqual(result.name, 'a-texto.txt'); text = result.read_text(encoding='utf8')
        for line in LINES: self.assertIn(line, text)
        self.assertNotIn('\f', text); self.assertNotIn('\r', text); self.assertTrue(text.endswith('\n'))
        self.assertEqual(digest(self.source), before); self.assertEqual([p.name for p in self.out.iterdir()], ['a-texto.txt'])
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ['a.png', 'out'])

    def test_both_languages_and_english_only(self):
        self.assertIn('Olá, mundo', self.run_ocr(ocr_lang='por+eng').read_text(encoding='utf8'))
        english = text_image(lines=['Hello world, this is a test', 'Offline file converter 2026'])
        path = self.root / 'en.png'; english.save(path)
        self.assertIn('Hello world', self.run_ocr(source=path, ocr_lang='eng').read_text(encoding='utf8'))

    def test_searchable_pdf(self):
        from pypdf import PdfReader
        before = digest(self.source)
        result = self.run_ocr('OCR → PDF', ocr_lang='por')
        self.assertEqual(result.name, 'a-pesquisavel.pdf'); pdf = PdfReader(str(result)); self.assertEqual(len(pdf.pages), 1)
        text = pdf.pages[0].extract_text(); self.assertIn('Conversão offline', text); self.assertIn('Ação e emoção', text)
        self.assertEqual(digest(self.source), before); self.assertEqual([p.name for p in self.out.iterdir()], ['a-pesquisavel.pdf'])

    def test_transparent_and_palette_and_small_images(self):
        rgba = Image.new('RGBA', (1000, 200), (0, 0, 0, 0)); ImageDraw.Draw(rgba).text((20, 40), 'Texto transparente', font=ImageFont.truetype(FONT, 60), fill=(0, 0, 0, 255))
        path = self.root / 't.png'; rgba.save(path); self.assertIn('Texto transparente', self.run_ocr(source=path, ocr_lang='por').read_text(encoding='utf8'))
        palette = self.root / 'p.png'; text_image().convert('P').save(palette); self.assertIn('Conversão offline', self.run_ocr(source=palette, ocr_lang='por').read_text(encoding='utf8'))
        small = self.root / 's.png'; text_image(size=20, width=420, lines=['Pequeno texto aqui']).save(small)
        self.assertIn('Pequeno texto', self.run_ocr(source=small, ocr_lang='por').read_text(encoding='utf8'))

    def test_page_modes(self):
        line = self.root / 'l.png'; text_image(lines=['Uma linha só']).save(line)
        self.assertIn('Uma linha', self.run_ocr(source=line, ocr_lang='por', ocr_psm='line').read_text(encoding='utf8'))
        self.assertIn('Conversão offline', self.run_ocr(ocr_lang='por', ocr_psm='block').read_text(encoding='utf8'))
        self.assertIn('Conversão', self.run_ocr(ocr_lang='por', ocr_psm='sparse').read_text(encoding='utf8'))

    def test_blank_image_saves_nothing(self):
        blank = self.root / 'b.png'; Image.new('RGB', (900, 300), 'white').save(blank)
        for target in ('OCR → Text', 'OCR → PDF'):
            with self.assertRaises(ConversionError) as caught: self.run_ocr(target, source=blank)
            self.assertIn('Nenhum texto foi reconhecido', str(caught.exception))
        self.assertEqual(list(self.out.iterdir()), []); self.assertEqual(sorted(p.name for p in self.root.iterdir()), ['a.png', 'b.png', 'out'])

    def test_never_overwrites_and_rename(self):
        first = self.run_ocr(); second = self.run_ocr()
        self.assertEqual((first.name, second.name), ('a-texto.txt', 'a-texto-2.txt'))
        named = self.run_ocr(rename_pattern='ocr-{nome}', rename_n=1)
        self.assertEqual(named.suffix, '.txt'); self.assertTrue(named.name.startswith('ocr-a'))

    def test_heic_svg_and_jpeg_inputs(self):
        jpeg = self.root / 'j.jpg'; text_image().save(jpeg, quality=92); self.assertIn('Conversão offline', self.run_ocr(source=jpeg, ocr_lang='por').read_text(encoding='utf8'))
        svg = self.root / 'v.svg'
        svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="900" height="200"><rect width="900" height="200" fill="white"/>'
                       '<text x="20" y="120" font-size="80" font-family="DejaVu Sans">Vetor legivel</text></svg>', encoding='utf8')
        try: text = self.run_ocr(source=svg, ocr_lang='por').read_text(encoding='utf8')
        except ConversionError: self.skipTest('desenhista de SVG sem fonte de texto neste ambiente')
        self.assertIn('Vetor', text)

    def test_worker_process_with_limits(self):
        import runner
        result = runner.run_job({'paths': [str(self.source)], 'target': 'OCR → PDF', 'output': str(self.out), 'ocr_lang': 'por'}, timeout=120)
        self.assertTrue(Path(result[0]).name.endswith('-pesquisavel.pdf'))
        result = runner.run_job({'paths': [str(self.source)], 'target': 'OCR → Text', 'output': str(self.out), 'ocr_lang': 'por+eng'}, timeout=120)
        self.assertIn('Olá, mundo', Path(result[0]).read_text(encoding='utf8'))

    def test_rotated_image_is_not_silently_fixed(self):
        """Documenta o limite: de cabeça para baixo o OCR não é corrigido (o relatório avisa)."""
        flipped = self.root / 'f.png'; text_image().rotate(180).save(flipped)
        try: text = self.run_ocr(source=flipped, ocr_lang='por').read_text(encoding='utf8')
        except ConversionError: text = ''
        self.assertNotIn('Conversão offline de arquivos', text)


class OcrPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make_panel(self, target='OCR → Text'):
        controller = JobController(capabilities={'images': (True, 'ok'), 'pdf': (True, 'ok')}); panel = FeaturePanel(controller)
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup); path = Path(self.tmp.name) / 'f.png'; text_image().save(path)
        panel.set_files([str(path)], target); return controller, panel

    def visible(self, panel):
        return {k for k, w in panel.form_fields.items() if panel.settings_form.isRowVisible(w)}

    def test_controls_and_button(self):
        for target, label in (('OCR → Text', 'Reconhecer e salvar texto'), ('OCR → PDF', 'Reconhecer e salvar PDF')):
            _c, panel = self.make_panel(target)
            self.assertTrue({'olang', 'opsm'} <= self.visible(panel)); self.assertNotIn('ofmt', self.visible(panel))
            self.assertEqual(panel.run_button.text(), label)
            self.assertEqual((panel.ocr_lang.count(), panel.ocr_psm.count()), (3, 4))
            self.assertEqual(panel.run_button.isEnabled(), ocr.status()[0])

    def test_options_are_sent(self):
        controller, panel = self.make_panel('OCR → PDF')
        with patch.object(controller, 'start_job') as start, patch.object(ocr, 'status', return_value=(True, '')):
            panel.ocr_lang.setCurrentIndex(2); panel.ocr_psm.setCurrentIndex(3); panel.run_selected()
            _paths, target, options = start.call_args.args[:3]
            self.assertEqual((target, options['ocr_lang'], options['ocr_psm']), ('OCR → PDF', 'eng', 'sparse'))

    def test_run_is_blocked_with_message_when_tesseract_is_missing(self):
        controller, panel = self.make_panel()
        with patch.object(controller, 'start_job') as start, patch.object(ocr, 'status', return_value=(False, 'O Tesseract não foi encontrado.')):
            panel.select_tool('OCR → Text'); panel.run_selected()
            start.assert_not_called(); self.assertIn('Tesseract', panel.status.text()); self.assertFalse(panel.run_button.isEnabled())

    def test_controller_accepts_ocr_options(self):
        controller = JobController(capabilities={'images': (True, 'ok'), 'pdf': (True, 'ok')}); controller._start_next = lambda: None
        controller.notify = lambda *a, **k: None
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'a.png'; text_image().save(path)
            self.assertTrue(controller.start_job([str(path)], 'OCR → Text', {'ocr_lang': 'por', 'ocr_psm': 'auto'}))
            self.assertFalse(controller.start_job([str(path)], 'OCR → Text', {'ocr_lang': 5}))


if __name__ == '__main__':
    unittest.main()
