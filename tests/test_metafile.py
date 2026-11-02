"""Leitura de metarquivos EMF/WMF (0.9.24): cabeçalhos, limites, mensagens fora do Windows, motor, relatório e painel.

**Importante:** o desenho real é feito pelo GDI e só existe no Windows. No Linux estes testes conferem a leitura do cabeçalho, as contas de tamanho e dpi
(pelo código do próprio Pillow), os limites, as mensagens de erro e a ligação com o motor usando um desenhista falso (que devolve uma cor lisa). Eles
**não provam** que o GDI desenha o arquivo certo. O teste de desenho real (`WindowsRenderTests`) só roda no Windows e cria um EMF de verdade pelo gdi32.
"""
import ctypes
import os
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PIL import Image, ImageFile, WmfImagePlugin
from PySide6.QtWidgets import QApplication

import engine
import metafile
import vector
from engine import ConversionError, IMAGE_INPUTS, METAFILE_INPUTS, VECTOR_INPUTS, convert, loss_report, set_vector_width
from tray_app import FeaturePanel, JobController


def make_emf(width=400, height=300, frame_mm100=(10583, 7937), extra=b''):
    """EMF mínimo: registro de cabeçalho (88 bytes) e registro de fim. Bounds em px do dispositivo; moldura em 0,01 mm."""
    eof = struct.pack('<4I', 14, 20, 0, 16) + struct.pack('<I', 20)
    header = struct.pack('<2I4i4i', 1, 88, 0, 0, width - 1 + 1, height - 1 + 1, 0, 0, frame_mm100[0], frame_mm100[1])
    header = struct.pack('<2I', 1, 88) + struct.pack('<4i', 0, 0, width, height) + struct.pack('<4i', 0, 0, frame_mm100[0], frame_mm100[1])
    header += b' EMF' + struct.pack('<I', 0x10000) + struct.pack('<I', 88 + len(eof) + len(extra)) + struct.pack('<I', 2) + struct.pack('<H', 1) + struct.pack('<H', 0)
    header += struct.pack('<III', 0, 0, 0) + struct.pack('<2i', 1280, 1024) + struct.pack('<2i', 320, 240)
    assert len(header) == 88, len(header)
    return header + extra + eof


def make_wmf(width_units=1440, height_units=720, inch=1440, placeable=True):
    standard = struct.pack('<HHHIHIH', 1, 9, 0x0300, 0, 0, 0, 0)
    eof = struct.pack('<IH', 3, 0)
    if not placeable:
        return standard + eof
    header = struct.pack('<IHhhhhHI', 0x9AC6CDD7, 0, 0, 0, width_units, height_units, inch, 0)
    checksum = 0
    for i in range(0, 20, 2): checksum ^= struct.unpack_from('<H', header, i)[0]
    return header + struct.pack('<H', checksum) + standard + eof


class FakeHandler(ImageFile.StubHandler):
    """Desenhista falso: devolve uma cor lisa no tamanho pedido (só para testar a ligação com o motor)."""
    calls = []

    def open(self, im):
        self.bbox = im.info['wmf_bbox']

    def load(self, im):
        FakeHandler.calls.append((im.size, im.info.get('dpi')))
        return Image.new('RGB', im.size, (200, 50, 50))


class MetaBase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name); self.out = self.root / 'out'; self.out.mkdir()
        self.previous = metafile.current_handler(); set_vector_width(0); FakeHandler.calls = []

    def tearDown(self):
        WmfImagePlugin.register_handler(self.previous); set_vector_width(0); self.temp.cleanup()

    def use_fake(self):
        WmfImagePlugin.register_handler(FakeHandler())

    def use_none(self):
        WmfImagePlugin.register_handler(None)

    def file(self, data, name='arte.emf'):
        path = self.root / name; path.write_bytes(data); return path

    def run_tool(self, path, target='Resize → PNG', **extra):
        options = {'resize_mode': 'percent', 'resize_percent': 100} if target == 'Resize → PNG' else {}
        return Path(convert({'paths': [str(path)], 'target': target, 'output': str(self.out), **options, **extra})[0])


class MetafileRegistryTests(unittest.TestCase):
    def test_suffixes(self):
        for ext in ('.emf', '.wmf'):
            self.assertIn(ext, IMAGE_INPUTS); self.assertIn(ext, VECTOR_INPUTS); self.assertIn(ext, METAFILE_INPUTS); self.assertNotIn(ext, engine.AI_INPUTS)
        import radial_menu, workspace_panel
        for ext in ('.emf', '.wmf'): self.assertIn(ext, workspace_panel.IMAGE_SUFFIXES); self.assertIn(ext, radial_menu.IMAGE_SUFFIXES)

    def test_pillow_win_handler_is_looked_up_in_both_layouts(self):
        """Pillow 12 guarda o desenhista no módulo, o 13 na classe; `current_handler` precisa achar os dois."""
        sentinel = object()
        with patch.object(WmfImagePlugin, '_handler', sentinel, create=True), patch.object(WmfImagePlugin.WmfStubImageFile, '_handler', None, create=True):
            self.assertIs(metafile.current_handler(), sentinel)
        with patch.object(WmfImagePlugin.WmfStubImageFile, '_handler', sentinel, create=True), patch.object(WmfImagePlugin, '_handler', None, create=True):
            self.assertIs(metafile.current_handler(), sentinel)


class MetafileHeaderTests(MetaBase):
    def test_emf_header(self):
        info = metafile.read_header(self.file(make_emf(400, 300)))
        self.assertEqual((info['kind'], info['declared']), ('emf', (400.0, 300.0)))

    def test_wmf_placeable_header_is_normalized_to_72_dpi(self):
        info = metafile.read_header(self.file(make_wmf(1440, 720), 'a.wmf'))
        self.assertEqual((info['kind'], info['declared']), ('wmf', (72.0, 36.0)))
        self.assertEqual(metafile.read_header(self.file(make_wmf(2880, 1440, inch=720), 'b.wmf'))['declared'], (288.0, 144.0))

    def test_invalid_files_are_refused_with_clear_messages(self):
        cases = {
            'vazio.emf': (b'', 'vazio'),
            'texto.emf': (b'isto nao e um metarquivo ' * 4, 'não parece'),
            'antigo.wmf': (make_wmf(placeable=False), 'tipo antigo'),
            'moldura.emf': (make_emf(frame_mm100=(0, 0)), 'moldura'),
            'inch.wmf': (make_wmf(inch=0), 'zero'),
            'enorme.emf': (make_emf(width=5_000_000, height=10), 'inválido ou grande demais'),
            'negativo.emf': (make_emf(width=-5, height=10), 'inválido ou grande demais'),
        }
        for name, (data, expected) in cases.items():
            with self.assertRaises(metafile.MetafileError, msg=name) as caught: metafile.read_header(self.file(data, name))
            self.assertIn(expected, str(caught.exception), name)
        with self.assertRaises(metafile.MetafileError): metafile.read_header(self.file(make_wmf()[:30], 'cortado.wmf'))

    def test_header_is_read_without_a_renderer(self):
        self.use_none(); self.assertFalse(metafile.available())
        self.assertEqual(metafile.read_header(self.file(make_emf()))['declared'], (400.0, 300.0))


class MetafileUnavailableTests(MetaBase):
    def test_describe_and_rasterize_say_windows_only(self):
        self.use_none(); path = self.file(make_emf())
        for function in (metafile.describe_metafile, metafile.rasterize_metafile):
            with self.assertRaises(metafile.MetafileError) as caught: function(path)
            self.assertIn('só podem ser desenhados no Windows', str(caught.exception)); self.assertIn('nada foi simulado', str(caught.exception))

    def test_engine_refuses_without_creating_files(self):
        self.use_none(); before = sorted(p.name for p in self.root.iterdir())
        for name, data in (('a.emf', make_emf()), ('b.wmf', make_wmf())):
            path = self.file(data, name)
            with self.assertRaises(ConversionError) as caught: self.run_tool(path)
            self.assertIn('Windows', str(caught.exception))
        self.assertEqual(list(self.out.iterdir()), []); self.assertEqual(sorted(p.name for p in self.root.iterdir()), sorted(before + ['a.emf', 'b.wmf']))

    def test_report_explains_why(self):
        self.use_none()
        text = ' '.join(loss_report([str(self.file(make_emf()))], 'Resize → PNG', {}))
        self.assertIn('Não foi possível ler um EMF/WMF', text); self.assertIn('só podem ser desenhados no Windows', text)

    def test_worker_process_reports_the_same(self):
        import runner
        if metafile.available(): self.skipTest('há desenhista de metarquivos neste sistema (Windows)')
        path = self.file(make_emf())
        with self.assertRaises(Exception) as caught: runner.run_job({'paths': [str(path)], 'target': 'Resize → PNG', 'resize_mode': 'percent', 'resize_percent': 100, 'output': str(self.out)}, timeout=60)
        self.assertIn('Windows', str(caught.exception)); self.assertEqual(list(self.out.iterdir()), [])


class MetafileWiringTests(MetaBase):
    """Ligação com o motor usando o desenhista FALSO; o desenho real só existe no Windows."""

    def setUp(self):
        super().setUp(); self.use_fake()

    def test_available_and_default_size(self):
        self.assertTrue(metafile.available())
        info = metafile.describe_metafile(self.file(make_emf(400, 300)))
        self.assertEqual((info['kind'], info['format'], info['size'], info['reduced'], info['engine']), ('metafile', 'emf', (400, 300), False, ('GDI do Windows', True)))
        image = metafile.rasterize_metafile(self.file(make_emf(400, 300)))
        self.assertEqual((image.mode, image.size, image.getpixel((5, 5))), ('RGBA', (400, 300), (200, 50, 50, 255)))        # opaco

    def test_width_changes_the_dpi_not_the_pixels_after_the_fact(self):
        path = self.file(make_emf(400, 300))
        image = metafile.rasterize_metafile(path, 800)
        self.assertEqual(image.size, (800, 600))
        (size, dpi) = FakeHandler.calls[-1]; self.assertEqual(size, (800, 600))
        base_dpi = 2540.0 * 400 / 10583; self.assertAlmostEqual(dpi[0] if isinstance(dpi, tuple) else dpi, base_dpi * 2, places=3)
        wmf = metafile.rasterize_metafile(self.file(make_wmf(1440, 720), 'a.wmf'), 144)
        self.assertEqual(wmf.size, (144, 72)); self.assertAlmostEqual(FakeHandler.calls[-1][1][0] if isinstance(FakeHandler.calls[-1][1], tuple) else FakeHandler.calls[-1][1], 144.0)

    def test_limits(self):
        big = self.file(make_emf(8000, 6000, frame_mm100=(100000, 75000)), 'grande.emf')
        info = metafile.describe_metafile(big); self.assertTrue(info['reduced']); self.assertLessEqual(info['size'][0] * info['size'][1], 40_000_000)
        with self.assertRaises(metafile.MetafileError) as caught: metafile.describe_metafile(big, 20000)
        self.assertIn('limite', str(caught.exception))

    def test_renderer_failures_are_mapped(self):
        class Broken(FakeHandler):
            def load(self, im): raise OSError('GDI falhou')
        WmfImagePlugin.register_handler(Broken())
        with self.assertRaises(metafile.MetafileError) as caught: metafile.rasterize_metafile(self.file(make_emf()))
        self.assertIn('não conseguiu desenhar', str(caught.exception))

    def test_tiny_box_with_zero_size_is_refused(self):
        class Zero(FakeHandler):
            def load(self, im): return Image.new('RGB', (0, 0))
        WmfImagePlugin.register_handler(Zero())
        with self.assertRaises(metafile.MetafileError): metafile.rasterize_metafile(self.file(make_emf(1, 1)))

    def test_tools_and_formats(self):
        path = self.file(make_emf(400, 300))
        png = self.run_tool(path)
        with Image.open(png) as im: self.assertEqual((im.size, im.convert('RGBA').getpixel((5, 5))), ((400, 300), (200, 50, 50, 255)))
        self.assertEqual(png.name, 'arte-redimensionada.png')
        for fmt in ('webp', 'jpeg', 'tiff', 'bmp', 'gif', 'ico'):
            self.assertTrue(self.run_tool(path, out_format=fmt).is_file(), fmt)
        with Image.open(self.run_tool(path, vector_width=200)) as im: self.assertEqual(im.size, (200, 150))
        for target, extra in (('Rotate → PNG', {'rotate_angle': 90}), ('Compress → JPEG', {}), ('Clean → PNG', {})):
            self.assertTrue(self.run_tool(path, target, **extra).is_file(), target)
        wmf = self.run_tool(self.file(make_wmf(1440, 720), 'b.wmf'), vector_width=288)
        with Image.open(wmf) as im: self.assertEqual(im.size, (288, 144))

    def test_original_untouched_and_no_leftovers(self):
        path = self.file(make_emf()); before = path.read_bytes(); self.run_tool(path)
        self.assertEqual(path.read_bytes(), before); self.assertEqual(sorted(p.name for p in self.root.iterdir()), ['arte.emf', 'out'])

    def test_corrupt_file_creates_nothing(self):
        with self.assertRaises(ConversionError): self.run_tool(self.file(b'\x01\x00\x00\x00' + b'\x00' * 100, 'ruim.emf'))
        self.assertEqual(list(self.out.iterdir()), [])

    def test_report(self):
        text = ' '.join(loss_report([str(self.file(make_emf(400, 300)))], 'Resize → PNG', {'vector_width': 800}))
        for part in ('GDI do Windows', '800 × 600 px', 'fundo branco opaco', 'não tem transparência', 'fontes instaladas'): self.assertIn(part, text)
        mixed = ' '.join(loss_report([str(self.file(make_emf())), str(self.root / 'x.png')], 'Resize → PNG', {})) if False else ''
        svg = self.root / 'v.svg'; svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="40" height="20"><rect width="40" height="20" fill="red"/></svg>', encoding='utf8')
        both = ' '.join(loss_report([str(svg), str(self.file(make_emf()))], 'Resize → PNG', {}))
        self.assertIn('GDI do Windows', both); self.assertIn('SVG', both)

    def test_report_for_big_header_mentions_reduction(self):
        text = ' '.join(loss_report([str(self.file(make_emf(8000, 6000, frame_mm100=(100000, 75000)), 'g.emf'))], 'Resize → PNG', {}))
        self.assertIn('reduzido', text)


@unittest.skipUnless(os.name == 'nt' and metafile.available(), 'só no Windows, com o desenhista do Pillow')
class WindowsRenderTests(MetaBase):
    """Cria um EMF de verdade pelo gdi32 e confere o desenho real do GDI. É a primeira prova no Windows; no Linux fica pulado."""

    def make_real_emf(self):
        gdi32 = ctypes.WinDLL('gdi32')
        gdi32.CreateEnhMetaFileW.restype = ctypes.c_void_p; gdi32.CreateEnhMetaFileW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_void_p, ctypes.c_wchar_p]
        gdi32.CreateSolidBrush.restype = ctypes.c_void_p; gdi32.CreateSolidBrush.argtypes = [ctypes.c_uint]
        gdi32.SelectObject.restype = ctypes.c_void_p; gdi32.SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        gdi32.Rectangle.restype = ctypes.c_int; gdi32.Rectangle.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int]
        gdi32.CloseEnhMetaFile.restype = ctypes.c_void_p; gdi32.CloseEnhMetaFile.argtypes = [ctypes.c_void_p]
        gdi32.DeleteEnhMetaFile.argtypes = [ctypes.c_void_p]; gdi32.DeleteObject.argtypes = [ctypes.c_void_p]
        path = self.root / 'real.emf'
        frame = (ctypes.c_long * 4)(0, 0, 5300, 2650)                 # 53 × 26,5 mm ≈ 200 × 100 px a 96 dpi
        hdc = gdi32.CreateEnhMetaFileW(None, str(path), ctypes.byref(frame), None)
        if not hdc: self.skipTest('o gdi32 não criou o EMF de teste')
        brush = gdi32.CreateSolidBrush(0x0000FF)                       # COLORREF = 0x00BBGGRR → vermelho
        gdi32.SelectObject(hdc, brush); gdi32.Rectangle(hdc, 0, 0, 200, 100)
        gdi32.DeleteEnhMetaFile(gdi32.CloseEnhMetaFile(hdc)); gdi32.DeleteObject(brush)
        return path

    def test_real_emf_is_drawn_by_gdi(self):
        path = self.make_real_emf()
        info = metafile.describe_metafile(path)
        image = metafile.rasterize_metafile(path)
        self.assertEqual(image.size, info['size']); self.assertEqual(image.mode, 'RGBA')
        r, g, b, a = image.getpixel((image.width // 2, image.height // 2))
        self.assertEqual(a, 255); self.assertGreater(r, 200); self.assertLess(g, 60); self.assertLess(b, 60)
        bigger = metafile.rasterize_metafile(path, image.width * 2)
        self.assertEqual(bigger.size[0], image.width * 2)
        png = self.run_tool(path); self.assertTrue(png.is_file())

    def test_worker_draws_it_too(self):
        import runner
        path = self.make_real_emf()
        result = runner.run_job({'paths': [str(path)], 'target': 'Resize → PNG', 'resize_mode': 'percent', 'resize_percent': 100, 'output': str(self.out), 'vector_width': 300}, timeout=90)
        with Image.open(result[0]) as im: self.assertEqual(im.size[0], 300)


class MetafilePanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_width_row_for_emf_and_message_instead_of_preview_without_renderer(self):
        previous = metafile.current_handler(); WmfImagePlugin.register_handler(None)
        self.addCleanup(WmfImagePlugin.register_handler, previous)
        controller = JobController(capabilities={'images': (True, 'ok'), 'pdf': (True, 'ok')}); panel = FeaturePanel(controller)
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup); path = Path(tmp.name) / 'a.emf'; path.write_bytes(make_emf())
        panel.set_files([str(path)], 'Resize → PNG')
        visible = {k for k, w in panel.form_fields.items() if panel.settings_form.isRowVisible(w)}
        self.assertIn('vwidth', visible); self.assertTrue(panel._has_vector()); self.assertEqual(tuple(panel.crop_image_size), (0, 0))
        self.assertIn('EMF', panel.vector_width.toolTip())


if __name__ == '__main__':
    unittest.main()
