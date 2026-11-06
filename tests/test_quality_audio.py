"""Portão B da categoria Áudio (0.9.51): detectores da suíte de qualidade e uma execução de seções reais sem falhas bloqueantes."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / 'tools'))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import quality_suite as qs

NEEDS_FFMPEG = unittest.skipUnless(qs.have_audio(), 'FFmpeg/ffprobe não instalados')


def tone(hz, rate=16000, seconds=1.0, amp=0.5):
    t = np.arange(int(rate * seconds)) / rate
    return amp * np.sin(2 * np.pi * hz * t)


class DetectorTests(unittest.TestCase):
    def test_peak_hz(self):
        for hz in (200, 440, 1000, 3000):
            self.assertAlmostEqual(qs.peak_hz(tone(hz)), hz, delta=3)
        self.assertEqual(qs.peak_hz(np.zeros(100)), 0.0)

    def test_band_ratio_separates_a_tone_from_noise(self):
        self.assertGreater(qs.band_ratio(tone(1000), 1000), 0.99)
        self.assertLess(qs.band_ratio(tone(300), 1000), 0.01)
        self.assertLess(qs.band_ratio(np.random.default_rng(1).normal(0, 0.2, 16000), 1000), 0.2)

    def test_level_db(self):
        self.assertAlmostEqual(qs.level_db(tone(440, amp=1.0)), -3.01, delta=0.05)
        self.assertAlmostEqual(qs.level_db(tone(440, amp=0.1)), -23.0, delta=0.1)
        self.assertLess(qs.level_db(np.zeros(1000)), -100)

    def test_sections_are_registered(self):
        names = [s.__name__ for s in qs.AUDIO_SECTIONS]
        for expected in ('audio_convert', 'audio_tags', 'audio_channels', 'audio_trim', 'audio_normalize', 'audio_compress', 'audio_bleep', 'audio_visualizer', 'audio_robustness', 'audio_determinism'):
            self.assertIn(expected, names)
        self.assertTrue(set(qs.AUDIO_SECTIONS) <= set(qs.SECTIONS))
        self.assertTrue({target for target, _ in qs.AUDIO_TOOLS} == set(qs.engine.AUDIO_TARGETS))


@NEEDS_FFMPEG
class CorpusAndSectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(); cls.root = Path(cls.tmp.name)
        cls.corpus = {'audio': qs.write_audio_corpus(cls.root / 'c')}

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        qs.RESULTS.clear()

    def failures(self):
        return [(r['func'], r['check'], r['value'], r['detail']) for r in qs.RESULTS if r['status'] == 'FALHOU']

    def test_corpus_has_every_kind(self):
        a = self.corpus['audio']
        for key in ('stereo', 'flac', 'two', 'mono', 'silence', 'padded', 'surround', 'quiet', 'noise', 'peaky', 'tagged', 'garbage', 'empty', 'text', 'truncated', 'fake_ext', 'spaces', 'vbr', 'rate11025', 'rate96000'):
            self.assertTrue(a[key].is_file(), key)
        info = qs.mediatools.probe(a['tagged'])
        self.assertEqual(info['tags']['title'], 'Canção de Teste'); self.assertTrue(info['has_cover'])
        self.assertEqual(qs.mediatools.probe(a['surround'])['channels'], 6)
        self.assertEqual(a['empty'].stat().st_size, 0)

    def test_the_suite_detects_a_wrong_tone(self):
        import audiobleep
        original = dict(audiobleep.TONES)
        audiobleep.TONES.update({'mid': 1500})
        try:
            qs.audio_bleep(self.corpus)
        finally:
            audiobleep.TONES.clear(); audiobleep.TONES.update(original)
        self.assertTrue(any('1 kHz' in check for _f, check, _v, _d in self.failures()), 'a suíte deveria reprovar um tom fora de 1 kHz')

    def test_fast_sections_pass(self):
        for section in (qs.audio_tags, qs.audio_channels, qs.audio_bleep, qs.audio_determinism):
            section(self.corpus)
        self.assertEqual(self.failures(), [])
        self.assertGreater(len(qs.RESULTS), 30)


if __name__ == '__main__':
    unittest.main()
