"""Entrada vetorial SVG/SVGZ (0.9.19): leitura segura, limites, tamanho, desenho com transparência, integração com o motor, relatório e painel."""
import gzip
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
import vector
from engine import ConversionError, convert, loss_report, open_image, set_vector_width
from tray_app import FeaturePanel, JobController

NS = 'xmlns="http://www.w3.org/2000/svg"'
RED_BOX = f'<svg {NS} width="100" height="50"><rect width="100" height="50" fill="#ff0000"/></svg>'
STRIPES = f'<svg {NS} width="120" height="60"><defs><linearGradient id="g" x1="0" x2="1"><stop offset="0" stop-color="#000"/><stop offset="1" stop-color="#fff"/></linearGradient></defs><rect width="60" height="60" fill="url(#g)"/></svg>'


class Base(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        set_vector_width(0)

    def tearDown(self):
        set_vector_width(0); self.temp.cleanup()

    def svg(self, text, name='a.svg', data=None):
        path = self.root / name
        if data is not None: path.write_bytes(data)
        else: path.write_text(text, encoding='utf-8')
        return path


class SizeTests(Base):
    def size(self, attrs, inner=''):
        return vector.declared_size(vector.parse_svg(f'<svg {NS} {attrs}>{inner}</svg>'.encode()))

    def test_units(self):
        self.assertEqual(self.size('width="100" height="50"'), (100, 50))
        w, h = self.size('width="1in" height="2in"'); self.assertEqual((round(w), round(h)), (96, 192))
        w, h = self.size('width="25.4mm" height="10mm"'); self.assertEqual((round(w), round(h)), (96, 38))
        w, h = self.size('width="72pt" height="36pt"'); self.assertEqual((round(w), round(h)), (96, 48))
        self.assertEqual(self.size('width="10px" height="5px"'), (10, 5))

    def test_viewbox_fallbacks(self):
        self.assertEqual(self.size('viewBox="0 0 40 20"'), (40, 20))
        self.assertEqual(self.size('width="100%" height="100%" viewBox="0 0 40 20"'), (40, 20))
        self.assertEqual(self.size('width="80" viewBox="0 0 40 20"'), (80, 40))
        self.assertEqual(self.size('height="10" viewBox="0 0 40 20"'), (20, 10))
        self.assertEqual(self.size('viewBox="0,0,30,30"'), (30, 30))

    def test_no_size_is_an_error(self):
        for attrs in ('', 'width="100"', 'width="50%" height="50%"', 'viewBox="0 0 0 10"'):
            with self.assertRaises(vector.VectorError, msg=attrs): self.size(attrs)
        with self.assertRaises(vector.VectorError): self.size('width="0" height="10"')
        with self.assertRaises(vector.VectorError): self.size('width="-5" height="10"')

    def test_target_size(self):
        self.assertEqual(vector.target_size((100, 50)), (100, 50, False))
        self.assertEqual(vector.target_size((100, 50), 400), (400, 200, False))
        self.assertEqual(vector.target_size((3, 7), 1), (1, 2, False))
        w, h, reduced = vector.target_size((20000, 10000)); self.assertTrue(reduced); self.assertLessEqual(max(w, h), 8192); self.assertEqual(round(w / h, 2), 2.0)
        w, h, reduced = vector.target_size((8000, 8000)); self.assertTrue(reduced); self.assertLessEqual(w * h, 40_000_000)
        for bad in (16385, 100000):
            with self.assertRaises(vector.VectorError): vector.target_size((100, 50), bad)
        with self.assertRaises(vector.VectorError): vector.target_size((100, 100), 7000 * 1 + 9000)        # 16000 × 16000 passa de 40 MP


class SafetyTests(Base):
    def prepared(self, text):
        return vector.prepare_svg(self.svg(text))

    def test_external_references_are_removed(self):
        text = f'<svg {NS} xmlns:xlink="http://www.w3.org/1999/xlink" width="10" height="10"><image xlink:href="secret.png"/><image href="http://example.com/x.png"/><use href="other.svg#a"/><a href="https://example.com"><rect width="5" height="5" style="fill:url(http://example.com/p)"/></a></svg>'
        done = self.prepared(text); body = done.data.decode()
        for banned in ('secret.png', 'example.com', 'other.svg'): self.assertNotIn(banned, body)
        self.assertGreaterEqual(done.dropped.get('externas', 0), 3)

    def test_internal_references_and_embedded_images_are_kept(self):
        uri = 'data:image/png;base64,iVBORw0KGgo='
        done = self.prepared(f'<svg {NS} width="10" height="10"><defs><rect id="r" width="2" height="2"/></defs><use href="#r"/><image href="{uri}" width="2" height="2"/></svg>')
        body = done.data.decode(); self.assertIn('#r', body); self.assertIn(uri, body); self.assertEqual(done.dropped, {})

    def test_non_image_data_uri_is_removed(self):
        done = self.prepared(f'<svg {NS} width="10" height="10"><image href="data:text/html;base64,PHNjcmlwdD4="/></svg>')
        self.assertNotIn('data:text', done.data.decode()); self.assertGreaterEqual(done.dropped['externas'], 1)

    def test_scripts_events_and_embedded_content_are_dropped(self):
        done = self.prepared(f'<svg {NS} width="10" height="10" onload="alert(1)"><script>alert(1)</script><foreignObject><div>x</div></foreignObject><iframe src="x"/><rect width="5" height="5" onclick="evil()"/></svg>')
        body = done.data.decode().lower()
        for banned in ('script', 'foreignobject', 'iframe', 'onload', 'onclick', 'alert'): self.assertNotIn(banned, body)
        self.assertGreaterEqual(done.dropped['scripts'], 1); self.assertGreaterEqual(done.dropped['incorporados'], 1)

    def test_css_imports_fonts_and_urls_are_removed(self):
        done = self.prepared(f'<svg {NS} width="10" height="10"><style>@import url(http://example.com/a.css); @font-face {{ font-family:x; src:url(http://example.com/f.woff) }} .a {{ fill:red }}</style><rect class="a" width="5" height="5"/></svg>')
        body = done.data.decode(); self.assertNotIn('example.com', body); self.assertNotIn('@import', body); self.assertIn('.a', body)

    def test_editor_metadata_is_removed_but_drawing_stays(self):
        done = self.prepared(f'<svg {NS} xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape" xmlns:sodipodi="http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd" width="10" height="10" inkscape:version="1.0"><sodipodi:namedview/><metadata>m</metadata><rect width="5" height="5"/></svg>')
        body = done.data.decode(); self.assertNotIn('inkscape', body); self.assertNotIn('sodipodi', body); self.assertIn('rect', body)

    def test_entities_are_refused(self):
        bomb = '<?xml version="1.0"?><!DOCTYPE svg [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;"><!ENTITY c "&b;&b;&b;&b;&b;&b;&b;&b;&b;&b;">]>' + f'<svg {NS} width="10" height="10"><text>&c;</text></svg>'
        with self.assertRaises(vector.VectorError) as caught: vector.prepare_svg(self.svg(bomb))
        self.assertIn('entidade', str(caught.exception))
        xxe = '<?xml version="1.0"?><!DOCTYPE svg [<!ENTITY x SYSTEM "file:///etc/passwd">]>' + f'<svg {NS} width="10" height="10"><text>&x;</text></svg>'
        with self.assertRaises(vector.VectorError): vector.prepare_svg(self.svg(xxe))

    def test_plain_doctype_is_accepted(self):
        text = '<?xml version="1.0"?><!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" "http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd">' + RED_BOX
        self.assertEqual(vector.prepare_svg(self.svg(text)).declared, (100, 50))

    def test_not_svg_or_broken(self):
        for text in ('<html><body/></html>', '<svg xmlns="http://example.com/other" width="1" height="1"/>', '<svg', 'texto qualquer', ''):
            with self.assertRaises(vector.VectorError, msg=text): vector.prepare_svg(self.svg(text, data=text.encode()))

    def test_depth_and_element_limits(self):
        deep = f'<svg {NS} width="10" height="10">' + '<g>' * 140 + '</g>' * 140 + '</svg>'
        with self.assertRaises(vector.VectorError) as caught: vector.prepare_svg(self.svg(deep))
        self.assertIn('aninhamento', str(caught.exception))
        many = f'<svg {NS} width="10" height="10">' + '<g/>' * 200_001 + '</svg>'
        with self.assertRaises(vector.VectorError) as caught: vector.prepare_svg(self.svg(many))
        self.assertIn('elementos demais', str(caught.exception))

    def test_circular_references_are_refused(self):
        for body in ('<g id="a"><use href="#a"/></g>', '<pattern id="p" width="2" height="2"><rect width="2" height="2" fill="url(#p)"/></pattern>',
                     '<g id="a"><use href="#b"/></g><g id="b"><use href="#a"/></g>', '<linearGradient id="x" href="#y"/><linearGradient id="y" href="#x"/>'):
            with self.assertRaises(vector.VectorError, msg=body) as caught: vector.prepare_svg(self.svg(f'<svg {NS} width="10" height="10">{body}</svg>'))
            self.assertIn('circulares', str(caught.exception))

    def test_use_bomb_is_refused(self):
        levels = ['<g id="l0"><rect width="1" height="1"/></g>']
        for i in range(1, 12): levels.append(f'<g id="l{i}">' + f'<use href="#l{i - 1}"/>' * 10 + '</g>')
        with self.assertRaises(vector.VectorError) as caught: vector.prepare_svg(self.svg(f'<svg {NS} width="10" height="10"><defs>{"".join(levels)}</defs><use href="#l11"/></svg>'))
        self.assertIn('expande', str(caught.exception))

    def test_reasonable_use_is_accepted(self):
        items = ''.join(f'<use href="#d" x="{i}"/>' for i in range(500))
        self.assertEqual(vector.prepare_svg(self.svg(f'<svg {NS} width="10" height="10"><defs><rect id="d" width="1" height="1"/></defs>{items}</svg>')).declared, (10, 10))

    def test_file_size_limits(self):
        with self.assertRaises(vector.VectorError) as caught: vector.prepare_svg(self.svg('', data=b'<svg ' + b' ' * (vector.SVG_MAX_BYTES + 1)))
        self.assertIn('16 MiB', str(caught.exception))

    def test_svgz(self):
        path = self.svg('', 'a.svgz', gzip.compress(RED_BOX.encode()))
        done = vector.prepare_svg(path); self.assertTrue(done.compressed); self.assertEqual(done.declared, (100, 50))
        bomb = self.svg('', 'b.svgz', gzip.compress(b'<svg ' + b' ' * (vector.SVGZ_MAX_BYTES + 10)))
        with self.assertRaises(vector.VectorError) as caught: vector.prepare_svg(bomb)
        self.assertIn('50 MiB', str(caught.exception))
        broken = self.svg('', 'c.svgz', b'\x1f\x8b\x08\x00garbage')
        with self.assertRaises(vector.VectorError): vector.prepare_svg(broken)

    def test_neighbour_files_and_local_urls_are_never_drawn(self):
        Image.new('RGB', (10, 10), (255, 0, 0)).save(self.root / 'secret.png')
        path = self.svg(f'<svg {NS} xmlns:xlink="http://www.w3.org/1999/xlink" width="20" height="20"><image xlink:href="secret.png" width="20" height="20"/><image href="file://{self.root}/secret.png" width="20" height="20"/></svg>')
        image = vector.rasterize_svg(path)
        self.assertEqual(image.getchannel('A').getextrema(), (0, 0))              # nada foi desenhado


class RasterCases:
    """Casos que valem para qualquer desenhista; as subclasses escolhem o adaptador."""
    ADAPTERS = ()

    def setUp(self):
        super().setUp()
        patcher = patch.object(vector, 'ADAPTER_MODULES', self.ADAPTERS); patcher.start(); self.addCleanup(patcher.stop)

    def test_size_transparency_and_colour(self):
        path = self.svg(f'<svg {NS} width="100" height="50"><rect x="50" width="50" height="50" fill="#ff0000"/></svg>')
        image = vector.rasterize_svg(path)
        self.assertEqual((image.size, image.mode), ((100, 50), 'RGBA'))
        self.assertEqual(image.getpixel((10, 10))[3], 0); self.assertEqual(image.getpixel((75, 25)), (255, 0, 0, 255))

    def test_requested_width_redraws_sharp(self):
        path = self.svg(f'<svg {NS} width="10" height="10"><circle cx="5" cy="5" r="4" fill="#0000ff"/></svg>')
        image = vector.rasterize_svg(path, 400)
        self.assertEqual(image.size, (400, 400)); self.assertEqual(image.getpixel((200, 200)), (0, 0, 255, 255))
        edge = [image.getpixel((x, 200))[3] for x in range(0, 400)]
        self.assertEqual(max(edge), 255); self.assertEqual(edge[5], 0)               # borda nítida em 400 px, não um borrão de 10 px ampliado

    def test_partial_alpha_is_kept_not_premultiplied(self):
        path = self.svg(f'<svg {NS} width="10" height="10"><rect width="10" height="10" fill="#ff0000" fill-opacity="0.5"/></svg>')
        r, g, b, a = vector.rasterize_svg(path).getpixel((5, 5))
        self.assertTrue(250 <= r and g <= 3 and b <= 3 and 120 <= a <= 135, (r, g, b, a))

    def test_gradient_and_text_are_drawn(self):
        image = vector.rasterize_svg(self.svg(STRIPES))
        self.assertLess(image.getpixel((2, 30))[0], 20); self.assertGreater(image.getpixel((57, 30))[0], 230); self.assertEqual(image.getpixel((100, 30))[3], 0)
        text = vector.rasterize_svg(self.svg(f'<svg {NS} width="200" height="60"><text x="5" y="45" font-size="40" fill="#000">Abc</text></svg>', 't.svg'))
        self.assertGreater(sum(1 for a in text.getchannel('A').tobytes() if a > 128), 100)

    def test_preserve_aspect_ratio_centres_the_drawing(self):
        path = self.svg(f'<svg {NS} width="200" height="100" viewBox="0 0 10 10"><rect width="10" height="10" fill="#00aa00"/></svg>')
        image = vector.rasterize_svg(path)
        self.assertEqual(image.size, (200, 100)); self.assertEqual(image.getpixel((100, 50)), (0, 170, 0, 255)); self.assertEqual(image.getpixel((5, 50))[3], 0); self.assertEqual(image.getpixel((195, 50))[3], 0)

    def test_filter_blur_is_applied(self):
        path = self.svg(f'<svg {NS} width="60" height="60"><defs><filter id="f"><feGaussianBlur stdDeviation="6"/></filter></defs><rect x="20" y="20" width="20" height="20" fill="#000" filter="url(#f)"/></svg>')
        image = vector.rasterize_svg(path)
        self.assertTrue(0 < image.getpixel((19, 30))[3] < 255)                      # a borda borrou para fora do retângulo (dentro da região do filtro)

    def test_svgz_is_drawn(self):
        image = vector.rasterize_svg(self.svg('', 'z.svgz', gzip.compress(RED_BOX.encode())))
        self.assertEqual(image.getpixel((50, 25)), (255, 0, 0, 255))

    def test_unreadable_is_a_clear_error(self):
        with self.assertRaises(vector.VectorError): vector.rasterize_svg(self.root / 'missing.svg')

    def test_neighbour_files_are_never_drawn(self):
        Image.new('RGB', (10, 10), (255, 0, 0)).save(self.root / 'secret.png')
        path = self.svg(f'<svg {NS} xmlns:xlink="http://www.w3.org/1999/xlink" width="20" height="20"><image xlink:href="secret.png" width="20" height="20"/><image href="file://{self.root}/secret.png" width="20" height="20"/></svg>', 'n.svg')
        self.assertEqual(vector.rasterize_svg(path).getchannel('A').getextrema(), (0, 0))

    def test_big_drawing(self):
        path = self.svg(f'<svg {NS} width="6000" height="3000"><rect width="6000" height="3000" fill="#3366cc"/></svg>', 'big.svg')
        image = vector.rasterize_svg(path)
        self.assertEqual(image.size, (6000, 3000)); self.assertEqual(image.getpixel((3000, 1500)), (51, 102, 204, 255))


class RasterQtTests(RasterCases, Base):
    ADAPTERS = ('vector_qt',)

    def test_engine_label(self):
        self.assertEqual(vector.engine_info(), ('Qt SVG', False))

    def test_known_limits_of_the_fallback_are_documented_by_measurement(self):
        # medido na 0.9.19: o Qt SVG não desenha clipPath; se isto passar a falhar, o adaptador melhorou e a nota do relatório deve ser revista
        path = self.svg(f'<svg {NS} width="100" height="100"><defs><clipPath id="c"><circle cx="50" cy="50" r="30"/></clipPath></defs><rect width="100" height="100" fill="#093" clip-path="url(#c)"/></svg>', 'clip.svg')
        self.assertEqual(vector.rasterize_svg(path).getpixel((2, 2))[3], 255)


@unittest.skipUnless(__import__('importlib').util.find_spec('resvg_py'), 'resvg-py não instalado')
class RasterResvgTests(RasterCases, Base):
    ADAPTERS = ('vector_resvg',)

    def test_engine_label(self):
        self.assertEqual(vector.engine_info(), ('resvg', True))

    def test_clip_path(self):
        path = self.svg(f'<svg {NS} width="100" height="100"><defs><clipPath id="c"><circle cx="50" cy="50" r="30"/></clipPath></defs><rect width="100" height="100" fill="#093" clip-path="url(#c)"/></svg>', 'clip.svg')
        image = vector.rasterize_svg(path)
        self.assertEqual(image.getpixel((2, 2))[3], 0); self.assertEqual(image.getpixel((50, 50)), (0, 153, 51, 255))

    def test_text_on_a_path_and_nested_svg_and_symbol_scaling(self):
        ns = f'{NS} xmlns:xlink="http://www.w3.org/1999/xlink"'
        text = vector.rasterize_svg(self.svg(f'<svg {ns} width="200" height="100"><defs><path id="p" d="M10 80 Q100 0 190 80"/></defs><text font-size="24" fill="#000"><textPath xlink:href="#p">Caminho de texto</textPath></text></svg>', 'tp.svg'))
        self.assertGreater(sum(1 for a in text.getchannel('A').tobytes() if a > 128), 200)
        nested = vector.rasterize_svg(self.svg(f'<svg {ns} width="100" height="100"><svg x="10" y="10" width="50" height="50" viewBox="0 0 10 10"><circle cx="5" cy="5" r="5" fill="#390"/></svg></svg>', 'ns.svg'))
        self.assertEqual(nested.getpixel((35, 35)), (51, 153, 0, 255)); self.assertEqual(nested.getpixel((90, 90))[3], 0)
        symbol = vector.rasterize_svg(self.svg(f'<svg {ns} width="100" height="100"><defs><symbol id="s" viewBox="0 0 10 10"><rect width="10" height="10" fill="#f60"/></symbol></defs><use href="#s" x="10" y="10" width="60" height="60"/></svg>', 'sy.svg'))
        self.assertEqual(symbol.getpixel((60, 60)), (255, 102, 0, 255))              # o símbolo foi esticado para 60 × 60

    def test_odd_sizes(self):
        for size in ((1, 1), (3, 7), (7, 3), (1, 5000)):
            path = self.svg(f'<svg {NS} width="{size[0]}" height="{size[1]}"><rect width="100%" height="100%" fill="#000"/></svg>', f'o{size[0]}x{size[1]}.svg')
            self.assertEqual(vector.rasterize_svg(path).size, size)


class AdapterChoiceTests(Base):
    def test_falls_back_when_the_preferred_adapter_is_missing(self):
        path = self.svg(RED_BOX)
        with patch.object(vector, 'ADAPTER_MODULES', ('modulo_que_nao_existe', 'vector_qt')):
            self.assertEqual(vector.engine_info()[0], 'Qt SVG'); self.assertEqual(vector.rasterize_svg(path).size, (100, 50))

    def test_no_adapter_is_a_clear_error(self):
        with patch.object(vector, 'ADAPTER_MODULES', ('modulo_que_nao_existe',)):
            self.assertIsNone(vector.engine_info())
            with self.assertRaises(vector.VectorError) as caught: vector.rasterize_svg(self.svg(RED_BOX))
        self.assertIn('desenhista', str(caught.exception))

    def test_report_names_the_fallback_and_its_limits(self):
        path = self.svg(RED_BOX)
        with patch.object(vector, 'ADAPTER_MODULES', ('vector_qt',)):
            notes = ' '.join(loss_report([str(path)], 'PNG', {}))
        self.assertIn('Qt SVG', notes); self.assertIn('alternativa embutida', notes); self.assertIn('resvg-py', notes)


class EngineTests(Base):
    def setUp(self):
        super().setUp()
        self.half = self.svg(f'<svg {NS} width="100" height="50"><rect x="50" width="50" height="50" fill="#ff0000"/></svg>', 'half.svg')

    def test_open_image_and_input_set(self):
        self.assertIn('.svg', engine.IMAGE_INPUTS); self.assertIn('.svgz', engine.IMAGE_INPUTS)
        with open_image(self.half) as image: self.assertEqual((image.size, image.mode), ((100, 50), 'RGBA'))
        set_vector_width(300)
        with open_image(self.half) as image: self.assertEqual(image.size, (300, 150))

    def test_bad_svg_is_a_conversion_error(self):
        bad = self.svg('<html/>', 'bad.svg')
        with self.assertRaises(ConversionError): open_image(bad)

    def test_every_output_format(self):
        for fmt, ext in (('png', 'png'), ('webp', 'webp'), ('tiff', 'tiff'), ('jpeg', 'jpg'), ('bmp', 'bmp'), ('gif', 'gif'), ('ico', 'ico')):
            with self.subTest(format=fmt):
                out = Path(convert({'paths': [str(self.half)], 'target': 'Resize → PNG', 'resize_mode': 'percent', 'resize_percent': 100, 'out_format': fmt, 'out_quality': 100, 'out_flatten': '#00FF00'})[0])
                self.assertEqual(out.suffix, '.' + ext)
                with Image.open(out) as image:
                    rgba = image.convert('RGBA'); w, h = rgba.size
                    left = rgba.getpixel((max(0, w // 8), h // 2))
                    if fmt in ('jpeg', 'bmp'): self.assertTrue(left[1] > 200 and left[0] < 60, left)      # transparente vira o «Fundo opaco»
                    elif fmt == 'ico': pass
                    else: self.assertEqual(left[3], 0, fmt)                                             # transparência preservada

    def test_conversions_with_width_and_png_keeps_alpha(self):
        out = Path(convert({'paths': [str(self.half)], 'target': 'PNG', 'vector_width': 500})[0])
        with Image.open(out) as image: self.assertEqual(image.size, (500, 250)); self.assertEqual(image.mode, 'RGBA'); self.assertEqual(image.getpixel((10, 10))[3], 0)
        out = Path(convert({'paths': [str(self.half)], 'target': 'JPEG', 'vector_width': 100})[0])
        with Image.open(out) as image: self.assertEqual(image.mode, 'RGB'); self.assertEqual(image.getpixel((5, 5)), (255, 255, 255))
        out = Path(convert({'paths': [str(self.half)], 'target': 'Image → PDF'})[0]); self.assertTrue(out.read_bytes().startswith(b'%PDF'))

    def test_tools_work_on_vectors(self):
        for target, extra in (('Rotate → PNG', {'rotate_angle': 90}), ('Sharpen → PNG', {'sharpen_mode': 'sharpen'}), ('Clean → PNG', {}), ('Backdrop → PNG', {}),
                              ('Crop → PNG', {'crop_x': 0, 'crop_y': 0, 'crop_width': 20, 'crop_height': 10}), ('Watermark → PNG', {'watermark_text': 'X', 'watermark_scale': 30})):
            with self.subTest(target=target):
                out = Path(convert({'paths': [str(self.half)], 'target': target, **extra})[0]); self.assertTrue(out.exists())

    def test_collage_and_one_pdf_with_vectors(self):
        raster = self.root / 'r.png'; Image.new('RGB', (30, 30), 'green').save(raster)
        self.assertTrue(Path(convert({'paths': [str(self.half), str(raster)], 'target': 'Collage → PNG'})[0]).exists())
        pdf = Path(convert({'paths': [str(self.half), str(raster)], 'target': 'Images → One PDF'})[0]); self.assertTrue(pdf.read_bytes().startswith(b'%PDF'))

    def test_width_option_is_validated_and_restored(self):
        for bad in (-1, 16385, 'x'):
            with self.assertRaises(ConversionError, msg=str(bad)): convert({'paths': [str(self.half)], 'target': 'PNG', 'vector_width': bad})
        set_vector_width(123); convert({'paths': [str(self.half)], 'target': 'PNG', 'vector_width': 40}); self.assertEqual(engine.VECTOR_WIDTH, 123)      # convert devolve o valor anterior

    def test_original_untouched_and_never_overwritten(self):
        before = self.half.read_bytes()
        first = convert({'paths': [str(self.half)], 'target': 'PNG'})[0]; second = convert({'paths': [str(self.half)], 'target': 'PNG'})[0]
        self.assertNotEqual(first, second); self.assertEqual(self.half.read_bytes(), before)

    def test_report_notes(self):
        notes = ' '.join(loss_report([str(self.half)], 'Resize → PNG', {'resize_mode': 'percent', 'resize_percent': 100, 'out_format': 'jpeg', 'vector_width': 400}))
        self.assertIn('400 × 200 px', notes); self.assertIn('declara 100 × 50', notes); self.assertIn('não volta a ser vetor', notes); self.assertIn('Desenho feito pelo', notes); self.assertIn('transparência', notes)
        plain = ' '.join(loss_report([str(self.half)], 'PNG', {}))
        self.assertIn('tamanho declarado no arquivo', plain)
        risky = self.svg(f'<svg {NS} width="10" height="10"><script>x()</script><image href="http://e.com/a.png"/></svg>', 'risky.svg')
        notes = ' '.join(loss_report([str(risky)], 'PNG', {})); self.assertIn('Referências externas', notes); self.assertIn('Scripts', notes)
        self.assertIn('Não foi possível ler um SVG', ' '.join(loss_report([str(self.svg("<html/>", "bad.svg"))], 'PNG', {})))

    def test_worker_process_draws_vectors(self):
        import runner
        result = runner.run_job({'paths': [str(self.half)], 'target': 'PNG', 'vector_width': 200}, timeout=60)
        with Image.open(result[0]) as image: self.assertEqual((image.size, image.mode), ((200, 100), 'RGBA'))


class PanelTests(Base):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make_panel(self, name='half.svg', tool='Resize → PNG'):
        controller = JobController(capabilities={'images': (True, 'ok'), 'pdf': (True, 'ok')})
        panel = FeaturePanel(controller)
        path = self.svg(RED_BOX, name) if name.endswith(('.svg', '.svgz')) else self.root / name
        if not name.endswith(('.svg', '.svgz')): Image.new('RGB', (200, 100), 'blue').save(path)
        panel.set_files([str(path)], tool)
        return controller, panel

    def visible(self, panel):
        return {k for k, w in panel.form_fields.items() if panel.settings_form.isRowVisible(w)}

    def test_row_only_with_vectors(self):
        _c, panel = self.make_panel(); self.assertIn('vwidth', self.visible(panel))
        _c, panel = self.make_panel('p.png'); self.assertNotIn('vwidth', self.visible(panel))
        for tool in ('PNG', 'JPEG', 'Image → PDF', 'Crop → PNG', 'Sharpen → PNG'):
            _c, panel = self.make_panel(tool=tool); self.assertIn('vwidth', self.visible(panel), tool)

    def test_preview_follows_the_chosen_width(self):
        _c, panel = self.make_panel(tool='Crop → PNG')
        self.assertEqual(panel.crop_image_size, (100, 50))
        panel.vector_width.setValue(400); panel._vector_timer.stop(); panel._vector_width_changed()
        self.assertEqual(panel.crop_image_size, (400, 200)); self.assertEqual(engine.VECTOR_WIDTH, 400)

    def test_option_is_sent_only_for_vectors(self):
        controller, panel = self.make_panel()
        with patch.object(controller, 'start_job') as start:
            panel.vector_width.setValue(640); panel.run_selected(); self.assertEqual(start.call_args.args[2]['vector_width'], 640)
        controller, panel = self.make_panel('p.png')
        with patch.object(controller, 'start_job') as start:
            panel.run_selected(); self.assertNotIn('vector_width', start.call_args.args[2])
        self.assertIsNone(engine.VECTOR_WIDTH)                                             # sem SVG na sessão, volta ao padrão

    def test_whitelist(self):
        controller = JobController(capabilities={'images': (True, 'ok'), 'pdf': (True, 'ok')}); controller.notify = lambda *a, **k: None; controller._start_next = lambda: None
        path = self.svg(RED_BOX)
        self.assertTrue(controller.start_job([str(path)], 'PNG', {'vector_width': 300}))
        self.assertFalse(controller.start_job([str(path)], 'PNG', {'vector_width': '300'}))


if __name__ == '__main__':
    unittest.main()
