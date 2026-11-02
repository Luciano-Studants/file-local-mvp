"""Fixtures sintéticas de fidelidade do Image Core: orientação EXIF, alpha, ICC, limites e saída reaberta.

Os arquivos são gerados em tempo de teste; nada binário é versionado.
"""
import hashlib
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PIL import Image

from engine import ConversionError, collage_columns_for, collage_layout, convert, jpeg_bytes, loss_report, source_file
from fixtures_icc import srgb_profile_bytes, swapped_primaries_profile_bytes

COLORS = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0), (0, 0, 0), (255, 255, 255), (128, 128, 128), (10, 200, 100)]
# Orientação EXIF -> transposição que leva a imagem ARMAZENADA à imagem EXIBIDA (norma EXIF 2.32).
DISPLAY_TRANSFORM = {
    2: Image.Transpose.FLIP_LEFT_RIGHT, 3: Image.Transpose.ROTATE_180, 4: Image.Transpose.FLIP_TOP_BOTTOM,
    5: Image.Transpose.TRANSPOSE, 6: Image.Transpose.ROTATE_270, 7: Image.Transpose.TRANSVERSE, 8: Image.Transpose.ROTATE_90,
}
INVERSE = {Image.Transpose.ROTATE_270: Image.Transpose.ROTATE_90, Image.Transpose.ROTATE_90: Image.Transpose.ROTATE_270}


def pixels(image):
    rgb = image.convert('RGBA')
    data = rgb.tobytes()
    return [tuple(data[i:i + 4]) for i in range(0, len(data), 4)]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class FixtureCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def run_job(self, source, target, **options):
        before = digest(source)
        outputs = convert({'paths': [str(source)], 'target': target, **options})
        self.assertEqual(digest(source), before, 'o original foi alterado')
        for output in outputs:                              # saída reaberta e válida
            if not str(output).endswith('.pdf'):
                with Image.open(output) as reopened:
                    reopened.verify()
        return outputs[0]

    def base_image(self):
        image = Image.new('RGB', (4, 2))
        image.putdata(COLORS)
        return image


class ExifOrientationTests(FixtureCase):
    def stored_for(self, orientation):
        base = self.base_image()
        if orientation == 1:
            return base
        transform = DISPLAY_TRANSFORM[orientation]
        return base.transpose(INVERSE.get(transform, transform))

    def write(self, orientation, name='o.png'):
        path = self.root / name
        exif = Image.Exif(); exif[0x0112] = orientation; exif[0x010F] = 'CameraMarca'
        self.stored_for(orientation).save(path, exif=exif)
        return path

    def test_all_eight_orientations_are_displayed_upright_in_output(self):
        expected = pixels(self.base_image())
        for orientation in range(1, 9):
            with self.subTest(orientation=orientation):
                output = self.run_job(self.write(orientation), 'PNG')
                with Image.open(output) as result:
                    self.assertEqual(result.size, (4, 2))
                    self.assertEqual(pixels(result), expected)

    def test_exif_metadata_is_not_copied_to_output(self):
        output = self.run_job(self.write(6), 'PNG')
        with Image.open(output) as result:
            self.assertEqual(dict(result.getexif()), {})
            self.assertNotIn('exif', result.info)

    def test_crop_coordinates_use_the_oriented_image(self):
        path = self.write(6)                                  # armazenada 2×4 → exibida 4×2
        output = self.run_job(path, 'Crop → PNG', crop_x=1, crop_y=0, crop_width=2, crop_height=1)
        with Image.open(output) as result:
            self.assertEqual(pixels(result), pixels(self.base_image())[1:3])
        with self.assertRaises(ConversionError):               # 3 de altura só existiria sem orientar
            convert({'paths': [str(path)], 'target': 'Crop → PNG', 'crop_x': 0, 'crop_y': 0, 'crop_width': 1, 'crop_height': 3})

    def test_jpeg_with_orientation_is_upright(self):
        base = Image.new('RGB', (64, 32))
        for x in range(64):
            for y in range(32):
                base.putpixel((x, y), [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0)][(x >= 32) + 2 * (y >= 16)])
        stored = base.transpose(Image.Transpose.ROTATE_90)    # para orientação 6
        path = self.root / 'o.jpg'
        exif = Image.Exif(); exif[0x0112] = 6
        stored.save(path, exif=exif, quality=95)
        output = self.run_job(path, 'PNG')
        with Image.open(output) as result:
            self.assertEqual(result.size, (64, 32))
            for point, color in (((4, 4), (255, 0, 0)), ((60, 4), (0, 255, 0)), ((4, 28), (0, 0, 255)), ((60, 28), (255, 255, 0))):
                actual = result.convert('RGB').getpixel(point)
                self.assertTrue(all(abs(a - b) < 30 for a, b in zip(actual, color)), (point, actual, color))

    def test_preview_pixmap_matches_exported_orientation(self):
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication([])
        from visual_tools import pixmap_from_image_path
        expected = pixels(self.base_image())
        for orientation in (3, 6, 8):
            with self.subTest(orientation=orientation):
                pixmap, size = pixmap_from_image_path(str(self.write(orientation, f'p{orientation}.png')))
                self.assertEqual(size, (4, 2))
                image = pixmap.toImage()
                actual = [tuple(image.pixelColor(x, y).getRgb()[:3]) + (255,) for y in range(2) for x in range(4)]
                self.assertEqual(actual, expected)


class AlphaTests(FixtureCase):
    def rgba_file(self):
        image = Image.new('RGBA', (32, 8))
        for x in range(32):
            alpha = (0, 128, 255, 255)[x // 8]
            for y in range(8):
                image.putpixel((x, y), (255, 0, 0, alpha) if x < 24 else (0, 0, 255, 255))
        path = self.root / 'alpha.png'
        image.save(path)
        return path

    def test_png_and_tiff_keep_alpha_exactly(self):
        for target in ('PNG', 'TIFF'):
            with self.subTest(target=target):
                with Image.open(self.run_job(self.rgba_file(), target)) as result:
                    self.assertEqual(result.convert('RGBA').getpixel((4, 4)), (255, 0, 0, 0))
                    self.assertEqual(result.convert('RGBA').getpixel((12, 4)), (255, 0, 0, 128))
                    self.assertEqual(result.convert('RGBA').getpixel((28, 4)), (0, 0, 255, 255))

    def test_webp_keeps_the_alpha_channel(self):
        with Image.open(self.run_job(self.rgba_file(), 'WEBP')) as result:
            self.assertIn('A', result.mode)
            alpha = [result.convert('RGBA').getpixel((x, 4))[3] for x in (4, 12, 20, 28)]
            self.assertEqual(alpha, [0, 128, 255, 255])

    def test_bmp_jpeg_and_compress_flatten_on_white(self):
        for target, tolerance in (('BMP', 1), ('JPEG', 14), ('Compress → JPEG', 14)):
            with self.subTest(target=target):
                with Image.open(self.run_job(self.rgba_file(), target)) as result:
                    self.assertEqual(result.mode, 'RGB')
                    transparent = result.getpixel((4, 4))
                    half = result.getpixel((12, 4))
                    self.assertTrue(all(c >= 255 - tolerance for c in transparent), transparent)
                    self.assertTrue(abs(half[0] - 255) <= tolerance and abs(half[1] - 127) <= tolerance + 1, half)

    def test_image_to_pdf_flattens_on_white(self):
        from pypdf import PdfReader
        output = self.run_job(self.rgba_file(), 'Image → PDF')
        embedded = PdfReader(output).pages[0].images[0].image.convert('RGB')
        self.assertTrue(all(c >= 240 for c in embedded.getpixel((4, 4))))

    def test_palette_and_gray_alpha_transparency_survive_png(self):
        palette = Image.new('P', (2, 1)); palette.putpalette([255, 0, 0, 0, 255, 0] + [0] * 762)
        palette.putdata([0, 1]); palette.info['transparency'] = 1
        path = self.root / 'palette.png'; palette.save(path, transparency=1)
        with Image.open(self.run_job(path, 'PNG')) as result:
            self.assertEqual([p[3] for p in pixels(result)], [255, 0])
        gray = Image.new('LA', (2, 1)); gray.putdata([(100, 255), (100, 0)])
        path = self.root / 'gray.png'; gray.save(path)
        with Image.open(self.run_job(path, 'PNG')) as result:
            self.assertEqual([p[3] for p in pixels(result)], [255, 0])

    def test_canvas_is_opaque_and_annotation_keeps_transparent_areas(self):
        with Image.open(self.run_job(self.rgba_file(), 'Canvas → PNG', canvas_width=40, canvas_height=16, background='#00FF00')) as result:
            self.assertEqual(result.convert('RGBA').getpixel((0, 0)), (0, 255, 0, 255))
        with Image.open(self.run_job(self.rgba_file(), 'Annotate → PNG', annotation='x', annotation_x=26, annotation_y=0, annotation_size=8)) as result:
            self.assertEqual(result.convert('RGBA').getpixel((4, 4))[3], 0)


class IccProfileTests(FixtureCase):
    def write(self, color=(255, 0, 0), profile=None, name='icc.png', mode='RGB'):
        path = self.root / name
        image = Image.new(mode, (16, 16), color)
        image.save(path, **({'icc_profile': profile} if profile else {}))
        return path

    def test_profile_is_preserved_in_formats_that_can_carry_it(self):
        profile = swapped_primaries_profile_bytes()
        path = self.write(profile=profile)
        for target in ('PNG', 'JPEG', 'WEBP', 'TIFF', 'Compress → JPEG'):
            with self.subTest(target=target):
                with Image.open(self.run_job(path, target)) as result:
                    self.assertEqual(result.info.get('icc_profile'), profile)
        with Image.open(self.run_job(path, 'PNG')) as result:     # os pixels não mudam; o perfil é que os descreve
            self.assertEqual(result.convert('RGB').getpixel((2, 2)), (255, 0, 0))

    def test_bmp_and_pdf_are_converted_to_srgb(self):
        from pypdf import PdfReader
        path = self.write(profile=swapped_primaries_profile_bytes())
        with Image.open(self.run_job(path, 'BMP')) as result:
            red, green, blue = result.convert('RGB').getpixel((2, 2))
            self.assertGreater(green, 200); self.assertLess(red, 60)
        output = self.run_job(path, 'Image → PDF')
        red, green, blue = PdfReader(output).pages[0].images[0].image.convert('RGB').getpixel((2, 2))
        self.assertGreater(green, 200); self.assertLess(red, 60)

    def test_srgb_profile_conversion_is_identity_for_bmp(self):
        path = self.write(color=(200, 50, 30), profile=srgb_profile_bytes())
        with Image.open(self.run_job(path, 'BMP')) as result:
            actual = result.convert('RGB').getpixel((2, 2))
            self.assertTrue(all(abs(a - b) <= 2 for a, b in zip(actual, (200, 50, 30))), actual)

    def test_invalid_or_mismatched_profiles_are_dropped_without_failing(self):
        path = self.write(profile=b'isto nao e um perfil icc' * 20, name='bad.png')
        for target in ('PNG', 'JPEG', 'BMP', 'Image → PDF'):
            with self.subTest(target=target):
                output = self.run_job(path, target)
                if not output.endswith('.pdf'):
                    with Image.open(output) as result:
                        self.assertIsNone(result.info.get('icc_profile'))
        gray = self.root / 'gray.png'
        Image.new('L', (8, 8), 90).save(gray, icc_profile=srgb_profile_bytes())   # perfil RGB em imagem cinza
        with Image.open(self.run_job(gray, 'PNG')) as result:
            self.assertIsNone(result.info.get('icc_profile'))

    def test_compress_estimate_includes_the_profile_and_matches_output(self):
        profile = swapped_primaries_profile_bytes()
        path = self.write(profile=profile, name='est.png')
        with Image.open(path) as source:
            estimate = len(jpeg_bytes(source.copy(), 70, profile))
        output = self.run_job(path, 'Compress → JPEG', quality=70)
        self.assertEqual(estimate, Path(output).stat().st_size)
        self.assertGreater(estimate, len(jpeg_bytes(Image.new('RGB', (16, 16), (255, 0, 0)), 70)))


class ColorModeTests(FixtureCase):
    def test_sixteen_bit_gray_is_scaled_not_blown_out(self):
        for value, expected in ((0, 0), (32768, 128), (65535, 255)):
            with self.subTest(value=value):
                path = self.root / f'g{value}.png'
                Image.new('I;16', (8, 8), value).save(path)
                with Image.open(self.run_job(path, 'PNG')) as result:
                    self.assertTrue(abs(result.convert('RGB').getpixel((2, 2))[0] - expected) <= 1)

    def test_sixteen_bit_gray_in_jpeg_and_pdf(self):
        from pypdf import PdfReader
        path = self.root / 'g.png'
        Image.new('I;16', (8, 8), 32768).save(path)
        with Image.open(self.run_job(path, 'JPEG')) as result:
            self.assertTrue(abs(result.getpixel((2, 2))[0] - 128) <= 2)
        pdf = self.run_job(path, 'Image → PDF')
        self.assertTrue(abs(PdfReader(pdf).pages[0].images[0].image.convert('L').getpixel((2, 2)) - 128) <= 2)

    def test_cmyk_becomes_rgb_without_a_usable_profile(self):
        path = self.root / 'c.tif'
        Image.new('CMYK', (8, 8), (255, 0, 0, 0)).save(path)
        with Image.open(self.run_job(path, 'PNG')) as result:
            self.assertEqual(result.convert('RGB').getpixel((2, 2)), (0, 255, 255))
        mismatched = self.root / 'm.jpg'
        Image.new('CMYK', (8, 8), (0, 0, 0, 128)).save(mismatched, icc_profile=srgb_profile_bytes())   # perfil RGB num CMYK
        with Image.open(self.run_job(mismatched, 'PNG')) as result:
            self.assertEqual(result.convert('RGB').getpixel((2, 2)), (127, 127, 127))
            self.assertIsNone(result.info.get('icc_profile'))


class CollageTests(FixtureCase):
    def solid(self, name, color, size=(40, 20), mode='RGB'):
        path = self.root / name
        Image.new(mode, size, color).save(path)
        return path

    def collage(self, paths, **options):
        before = {str(p): digest(p) for p in paths}
        outputs = convert({'paths': [str(p) for p in paths], 'target': 'Collage → PNG', **options})
        for p in paths:
            self.assertEqual(digest(p), before[str(p)], 'um original foi alterado')
        self.assertEqual(len(outputs), 1)
        return outputs[0]

    def test_layout_geometry_and_automatic_columns(self):
        self.assertEqual([collage_columns_for(n) for n in (2, 3, 4, 5, 9, 12)], [2, 2, 2, 3, 3, 4])
        self.assertEqual(collage_columns_for(3, 6), 3)
        size, origins = collage_layout(4, 2, 100, 10)
        self.assertEqual(size, (230, 230))
        self.assertEqual(origins, [(10, 10), (120, 10), (10, 120), (120, 120)])
        size, origins = collage_layout(3, 2, 100, 10)          # última linha incompleta centralizada
        self.assertEqual(size, (230, 230))
        self.assertEqual(origins[2], (65, 120))
        self.assertEqual(collage_layout(5, 1, 64, 0)[0], (64, 320))

    def test_images_land_in_their_cells_in_list_order_on_background(self):
        paths = [self.solid('a.png', (255, 0, 0)), self.solid('b.png', (0, 255, 0)), self.solid('c.png', (0, 0, 255))]
        output = self.collage(paths, collage_columns=2, collage_cell=100, collage_gap=10, background='#202020')
        with Image.open(output) as result:
            self.assertEqual(result.size, (230, 230)); self.assertEqual(result.mode, 'RGB')
            pixel = result.getpixel
            self.assertEqual(pixel((60, 60)), (255, 0, 0))     # centro da célula 1 (a imagem 40×20 não é ampliada)
            self.assertEqual(pixel((170, 60)), (0, 255, 0))
            self.assertEqual(pixel((115, 170)), (0, 0, 255))   # 3ª imagem centralizada na última linha
            self.assertEqual(pixel((2, 2)), (32, 32, 32))      # espaço = fundo
            self.assertEqual(pixel((20, 20)), (32, 32, 32))    # dentro da célula, fora da imagem pequena

    def test_large_images_shrink_to_fit_and_small_ones_are_not_enlarged(self):
        big = self.solid('big.png', (255, 0, 0), size=(400, 200))
        small = self.solid('small.png', (0, 255, 0), size=(10, 10))
        with Image.open(self.collage([big, small], collage_columns=2, collage_cell=100, collage_gap=0, background='#FFFFFF')) as result:
            self.assertEqual(result.size, (200, 100))
            self.assertEqual(result.getpixel((50, 50)), (255, 0, 0))
            self.assertEqual(result.getpixel((50, 26)), (255, 0, 0))     # 400×200 → 100×50, centralizada: y de 25 a 75
            self.assertEqual(result.getpixel((50, 10)), (255, 255, 255))
            self.assertEqual(result.getpixel((150, 50)), (0, 255, 0))
            self.assertEqual(result.getpixel((150, 30)), (255, 255, 255))

    def test_exif_orientation_transparency_and_icc_are_respected(self):
        stored = Image.new('RGB', (2, 4), (255, 0, 0)); stored.putpixel((0, 0), (0, 0, 255))
        oriented = self.root / 'o.png'
        exif = Image.Exif(); exif[0x0112] = 6
        stored.save(oriented, exif=exif)                                  # exibida 4×2
        transparent = self.solid('t.png', (255, 0, 0, 0), size=(8, 8), mode='RGBA')
        profiled = self.solid('p.png', (255, 0, 0), size=(8, 8))
        Image.new('RGB', (8, 8), (255, 0, 0)).save(profiled, icc_profile=swapped_primaries_profile_bytes())
        with Image.open(self.collage([oriented, transparent, profiled], collage_columns=3, collage_cell=64, collage_gap=0, background='#00FF00')) as result:
            self.assertEqual(result.size, (192, 64))
            self.assertEqual(result.getpixel((32, 32)), (255, 0, 0))     # a imagem 4×2 não é ampliada: o centro é do conteúdo
            self.assertEqual(result.getpixel((64 + 32, 32)), (0, 255, 0))  # transparente → fundo
            red, green, blue = result.getpixel((128 + 32, 32))
            self.assertGreater(green, 200); self.assertLess(red, 60)      # perfil convertido para sRGB
            self.assertNotIn('icc_profile', result.info)

    def test_validation_errors_leave_no_output(self):
        a, b = self.solid('a.png', 'red'), self.solid('b.png', 'blue')
        txt = self.root / 'x.txt'; txt.write_text('x')
        cases = [([a], {}, 'de 2 a 12'), ([a, b], {'collage_cell': 10}, 'inválidas'), ([a, b], {'collage_gap': 500}, 'inválidas'),
                 ([a, b], {'collage_columns': 9}, 'inválidas'), ([a, b], {'background': 'red'}, 'hexadecimal'),
                 ([a] * 12, {'collage_cell': 2000, 'collage_columns': 6, 'collage_gap': 200}, 'grande demais'),
                 ([a, txt], {}, 'somente imagens'), ([a] * 13, {}, 'de 2 a 12')]
        for paths, options, message in cases:
            with self.subTest(message=message, options=options), self.assertRaisesRegex(ConversionError, message):
                convert({'paths': [str(p) for p in paths], 'target': 'Collage → PNG', **options})
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ['a.png', 'b.png', 'x.txt'])

    def test_output_never_overwrites_an_existing_collage(self):
        a, b = self.solid('a.png', 'red'), self.solid('b.png', 'blue')
        first = self.collage([a, b]); second = self.collage([a, b])
        self.assertNotEqual(first, second)
        self.assertEqual(Path(first).name, 'collage.png'); self.assertEqual(Path(second).name, 'collage-2.png')


class LossReportTests(FixtureCase):
    def report(self, path, target, **options):
        return ' | '.join(loss_report([str(path)], target, options))

    def test_lossless_conversion_without_issues_says_so(self):
        path = self.root / 'plain.png'; Image.new('RGB', (8, 8), 'red').save(path)
        for target in ('PNG', 'TIFF', 'BMP'):
            self.assertEqual(loss_report([str(path)], target), ['Nenhuma perda adicional conhecida nesta conversão.'])

    def test_jpeg_webp_and_recompression_are_reported(self):
        png = self.root / 'a.png'; Image.new('RGB', (8, 8), 'red').save(png)
        jpg = self.root / 'a.jpg'; Image.new('RGB', (8, 8), 'red').save(jpg)
        self.assertIn('qualidade 70', self.report(png, 'JPEG', quality=70))
        self.assertIn('qualidade 88', self.report(png, 'Compress → JPEG', quality=88))
        self.assertNotIn('acumula', self.report(png, 'JPEG'))
        self.assertIn('acumula', self.report(jpg, 'Compress → JPEG'))
        self.assertIn('WebP foi salvo com perda', self.report(png, 'WEBP'))
        self.assertNotIn('com perda', self.report(png, 'PNG'))

    def test_transparency_note_matches_what_the_engine_really_does(self):
        rgba = self.root / 'alpha.png'; Image.new('RGBA', (8, 8), (255, 0, 0, 0)).save(rgba)
        for target in ('JPEG', 'BMP', 'Image → PDF', 'Compress → JPEG'):
            self.assertIn('transparência foi substituída por fundo branco', self.report(rgba, target))
        for target in ('PNG', 'TIFF', 'WEBP'):
            self.assertNotIn('transparência', self.report(rgba, target))
            with Image.open(self.run_job(rgba, target)) as result:
                self.assertIn('A', result.mode)
        self.assertIn('cor de fundo', ' '.join(loss_report([str(rgba), str(rgba)], 'Collage → PNG')))
        opaque = self.root / 'opaque.png'; Image.new('RGB', (8, 8)).save(opaque)
        self.assertNotIn('transparência', self.report(opaque, 'JPEG'))

    def test_metadata_orientation_and_resize_notes(self):
        path = self.root / 'photo.png'
        exif = Image.Exif(); exif[0x0112] = 6; exif[0x010F] = 'Marca'
        Image.new('RGB', (200, 100), 'red').save(path, exif=exif)
        text = self.report(path, 'PNG', width=50)
        self.assertIn('Metadados da origem', text); self.assertIn('orientação do EXIF', text)
        self.assertIn('no máximo 50 px', text)
        with Image.open(self.run_job(path, 'PNG', width=50)) as result:
            self.assertEqual(dict(result.getexif()), {}); self.assertLessEqual(max(result.size), 50)
        self.assertIn('original 100 × 200 px', self.report(path, 'PNG', width=50))   # orientação 6 troca largura e altura
        self.assertNotIn('no máximo', self.report(path, 'PNG', width=500))     # não reduz → não afirma
        upright = self.root / 'upright.png'; Image.new('RGB', (8, 8)).save(upright)
        text = self.report(upright, 'PNG')
        self.assertNotIn('orientação', text); self.assertNotIn('Metadados', text)

    def test_color_profile_and_bit_depth_notes(self):
        profile = swapped_primaries_profile_bytes()
        tagged = self.root / 'tag.png'; Image.new('RGB', (8, 8), 'red').save(tagged, icc_profile=profile)
        self.assertIn('convertidas do perfil embutido para sRGB', self.report(tagged, 'BMP'))
        self.assertIn('convertidas do perfil embutido para sRGB', self.report(tagged, 'Image → PDF'))
        self.assertIn('foi preservado', self.report(tagged, 'PNG'))
        bad = self.root / 'bad.png'; Image.new('RGB', (8, 8)).save(bad, icc_profile=b'lixo' * 50)
        self.assertIn('descartado', self.report(bad, 'PNG'))
        gray = self.root / 'gray.png'; Image.new('L', (8, 8)).save(gray, icc_profile=srgb_profile_bytes())
        self.assertIn('descartado', self.report(gray, 'PNG'))          # perfil RGB em imagem cinza
        deep = self.root / 'deep.png'; Image.new('I;16', (8, 8), 40000).save(deep)
        self.assertIn('16 bits foram reduzidos', self.report(deep, 'PNG'))
        cmyk = self.root / 'c.tif'; Image.new('CMYK', (8, 8)).save(cmyk)
        self.assertIn('sem perfil de cor', self.report(cmyk, 'PNG'))

    def test_tool_specific_notes_and_pdf_operations(self):
        path = self.root / 'a.png'; Image.new('RGB', (40, 40), 'red').save(path)
        self.assertIn('10 × 12 px', self.report(path, 'Crop → PNG', crop_width=10, crop_height=12))
        self.assertIn('gravado nos pixels', self.report(path, 'Annotate → PNG'))
        self.assertIn('fundo opaco', self.report(path, 'Canvas → PNG'))
        self.assertIn('não são ampliadas', self.report(path, 'Collage → PNG'))
        self.assertIn('sem OCR', ' '.join(loss_report(['/x.pdf'], 'PDF → Text')))
        self.assertIn('marcadores', ' '.join(loss_report(['/x.pdf'], 'Split PDF')))
        self.assertIn('na ordem da lista', ' '.join(loss_report(['/x.pdf', '/y.pdf'], 'Merge PDFs')))
        self.assertEqual(loss_report([str(path)], 'Operação inventada'), [])

    def test_unreadable_sources_never_raise(self):
        self.assertEqual(loss_report(['/não/existe.png'], 'PNG'), ['Nenhuma perda adicional conhecida nesta conversão.'])


class LimitsAndSafetyTests(FixtureCase):
    def test_images_over_40_megapixels_are_rejected_without_output(self):
        path = self.root / 'huge.png'
        Image.new('L', (6001, 6700), 0).save(path, optimize=False, compress_level=1)
        with self.assertRaisesRegex(ConversionError, '40 megapixels'):
            convert({'paths': [str(path)], 'target': 'PNG'})
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ['huge.png'])

    def test_files_over_100_mib_are_rejected_before_decoding(self):
        path = self.root / 'big.png'
        with open(path, 'wb') as handle:
            handle.truncate(101 * 1024 * 1024)
        with self.assertRaisesRegex(ConversionError, '100 MiB'):
            source_file(str(path))

    def test_truncated_and_non_image_files_fail_cleanly(self):
        good = self.root / 'good.png'
        Image.new('RGB', (64, 64), 'red').save(good)
        truncated = self.root / 'truncated.png'
        truncated.write_bytes(good.read_bytes()[:60])
        fake = self.root / 'fake.png'
        fake.write_bytes(b'MZ' + os.urandom(200))
        for path in (truncated, fake):
            with self.subTest(path=path.name), self.assertRaises(Exception):
                convert({'paths': [str(path)], 'target': 'PNG'})
        leftovers = [p.name for p in self.root.iterdir() if p.name not in {'good.png', 'truncated.png', 'fake.png'}]
        self.assertEqual(leftovers, [])

    def test_animated_images_are_rejected(self):
        path = self.root / 'anim.png'
        frames = [Image.new('RGB', (8, 8), color).convert('P') for color in ('red', 'blue')]  # APNG: formato aceito como entrada
        frames[0].save(path, format='PNG', save_all=True, append_images=frames[1:])
        with self.assertRaisesRegex(ConversionError, 'animadas'):
            convert({'paths': [str(path)], 'target': 'PNG'})


if __name__ == '__main__':
    unittest.main()
