"""Regressões achadas pela suíte de qualidade (0.9.26): WebP rápido respeita a qualidade; arquivo corrompido/falso vira ConversionError em português."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PIL import Image

import engine
import quality_suite as qs
from engine import ConversionError, convert


class QuickConversionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup); self.root = Path(self.tmp.name)
        self.photo = qs.make_photo((320, 240)); self.src = self.root / 'f.png'; self.photo.save(self.src)

    def run_quick(self, target, **options):
        out = self.root / 'out'; out.mkdir(exist_ok=True)
        return Path(convert({'paths': [str(self.src)], 'target': target, 'output': str(out), **options})[0])

    def test_webp_quality_is_respected_and_100_is_lossless(self):
        sizes = {q: self.run_quick('WEBP', quality=q).stat().st_size for q in (20, 60, 90)}
        self.assertLess(sizes[20], sizes[60]); self.assertLess(sizes[60], sizes[90])
        lossless = self.run_quick('WEBP', quality=100)
        with Image.open(lossless) as im: self.assertTrue(qs.identical(im, self.photo, 'RGB'))

    def test_webp_default_quality_is_good(self):
        out = self.run_quick('WEBP')
        with Image.open(out) as im: self.assertGreaterEqual(qs.psnr(im, self.photo), 34)


class DefectiveFileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup); self.root = Path(self.tmp.name)
        good = self.root / 'good.png'; qs.make_photo((200, 150)).save(good); data = good.read_bytes()
        self.truncated = self.root / 'cortada.png'; self.truncated.write_bytes(data[: len(data) // 3])
        self.fake = self.root / 'falsa.png'; self.fake.write_bytes(b'isto nao e uma imagem\n' * 30)
        self.empty = self.root / 'vazia.jpg'; self.empty.write_bytes(b'')
        self.jpeg = self.root / 'cortada.jpg'; qs.make_photo((200, 150)).save(self.jpeg, quality=90); self.jpeg.write_bytes(self.jpeg.read_bytes()[:900])

    def test_every_defective_file_is_refused_in_portuguese_without_leftovers(self):
        for path in (self.truncated, self.fake, self.empty, self.jpeg):
            for target in ('PNG', 'Rotate → PNG', 'Clean → PNG', 'OCR → Text'):
                out = Path(tempfile.mkdtemp(dir=self.root))
                with self.subTest(file=path.name, target=target):
                    with self.assertRaises(ConversionError) as caught:
                        convert({'paths': [str(path)], 'target': target, 'output': str(out), 'rotate_angle': 90})
                    self.assertTrue(any(word in str(caught.exception) for word in ('imagem', 'arquivo', 'truncada', 'danificada')), str(caught.exception))
                    self.assertEqual([p.name for p in out.iterdir() if not p.name.startswith('.arquivo-local-work')], [])

    def test_message_names_the_file(self):
        with self.assertRaisesRegex(ConversionError, 'falsa.png'):
            convert({'paths': [str(self.fake)], 'target': 'PNG', 'output': str(self.root)})


class SuiteHelpersTests(unittest.TestCase):
    def test_metrics(self):
        a = qs.make_photo((64, 48)); b = a.copy()
        self.assertEqual(qs.psnr(a, b), 99.0); self.assertAlmostEqual(qs.ssim(a, b), 1.0, places=6)
        noisy = Image.eval(a, lambda v: min(255, v + 25)); self.assertLess(qs.psnr(a, noisy), 30); self.assertLess(qs.ssim(a, noisy), 1.0)
        self.assertEqual(qs.psnr(a, a.resize((10, 10))), 0.0)

    def test_private_metadata_detects_by_structure_not_by_bytes(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup); root = Path(tmp.name)
        files = qs.write_corpus(root / 'c')
        self.assertTrue(qs.private_metadata(files['exif']))
        clean = root / 'limpo.png'; Image.open(files['photo']).save(clean); self.assertEqual(qs.private_metadata(clean), [])
        with_gps = root / 'x.png'; im = Image.open(files['photo']); info = Image.Exif(); info[0x010F] = 'TestCam'; im.save(with_gps, exif=info)
        self.assertTrue(qs.private_metadata(with_gps))

    def test_corpus_is_deterministic(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        one, two = qs.write_corpus(Path(tmp.name) / 'a'), qs.write_corpus(Path(tmp.name) / 'b')
        for key in ('photo', 'alpha', 'text', 'object', 'exif', 'cmyk'):
            self.assertEqual(qs.sha(one[key]), qs.sha(two[key]), key)


if __name__ == '__main__':
    unittest.main()
