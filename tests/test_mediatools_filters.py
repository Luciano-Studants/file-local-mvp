"""Dependência do FFmpeg: filtros exigidos pelas ferramentas de Áudio (builds enxutos devem ser recusados com explicação)."""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import audiobleep
import audiochannels
import audionorm
import audiotrim
import audioviz
import mediatools
from mediatools import MediaError

LISTING = """Filters:
  T.. = Timeline support
 ... aformat           A->A       Convert the input audio to one of the specified formats.
 T.. volume            A->A       Change input volume.
 .S. showwaves         A->V       Convert input audio to a video output.
 ..C loudnorm          A->A       EBU R128 loudness normalization
 TSC aeval             A->A       Filter audio signal according to a specified expression.
 ... anullsrc          |->A       Null audio source, return empty audio frames.
"""


class ParseTests(unittest.TestCase):
    def test_parse_filters_accepts_other_flag_letters(self):
        text = ' TSC aeval A->A x\n XYZ novo A->V y\n'
        self.assertEqual(mediatools.parse_filters(text), {'aeval', 'novo'})

    def test_parse_filters_reads_names_only(self):
        self.assertEqual(mediatools.parse_filters(LISTING), {'aformat', 'volume', 'showwaves', 'loudnorm', 'aeval', 'anullsrc'})

    def test_parse_filters_ignores_garbage(self):
        self.assertEqual(mediatools.parse_filters('\nFilters:\n  T.. = Timeline support\nlixo\n'), set())

    def test_every_tool_lists_needed_filters(self):
        self.assertEqual(set(mediatools.FILTERS_NEEDED), {'channels', 'trim', 'normalize', 'bleep', 'viz'})
        for names in mediatools.FILTERS_NEEDED.values():
            self.assertTrue(names)


class RequireTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(mediatools, '_filter_exists', return_value=False)     # o build de mentira não tem nenhum filtro fora da lista
        patcher.start(); self.addCleanup(patcher.stop)

    def build(self, filters, video=('mpeg4',)):
        return {'version': '7', 'license': 'lgpl', 'encoders': ['aac'], 'video_encoders': list(video), 'filters': filters, 'outputs': ['mp3'], 'exe': '/x/ffmpeg'}

    def test_full_build_passes(self):
        everything = sorted({n for names in mediatools.FILTERS_NEEDED.values() for n in names})
        with mock.patch.object(mediatools, 'build_info', return_value=self.build(everything)):
            for tool in mediatools.FILTERS_NEEDED:
                mediatools.require_filters(tool)
            self.assertEqual(mediatools.unavailable_tools(self.build(everything)), [])

    def test_lean_build_is_refused_in_portuguese(self):
        with mock.patch.object(mediatools, 'build_info', return_value=self.build(['volume'])):
            with self.assertRaises(MediaError) as caught:
                mediatools.require_filters('bleep')
        self.assertIn('aeval', str(caught.exception)); self.assertIn('DEPENDENCIAS', str(caught.exception))

    def test_unknown_filter_list_does_not_block(self):
        with mock.patch.object(mediatools, 'build_info', return_value=None):
            mediatools.require_filters('viz')
        with mock.patch.object(mediatools, 'build_info', return_value={'filters': None}):
            mediatools.require_filters('viz')

    def test_unavailable_tools_report(self):
        gaps = mediatools.unavailable_tools(self.build(['aformat', 'volume'], video=()))
        text = ' '.join(gaps)
        for word in ('Canais', 'Normalizar', 'Bleep', 'Visualizador', 'Cortar por silêncio'):
            self.assertIn(word, text)

    def test_missing_mpeg4_alone_is_reported(self):
        everything = sorted({n for names in mediatools.FILTERS_NEEDED.values() for n in names})
        self.assertEqual(mediatools.unavailable_tools(self.build(everything, video=('libx264',))), ['Visualizador (sem codificador mpeg4)'])

    def test_real_build_lists_filters(self):
        if not mediatools.find_tool('ffmpeg'):
            self.skipTest('sem FFmpeg')
        info = mediatools.build_info(refresh=True)
        self.assertIn('aeval', info['filters']); self.assertIn('loudnorm', info['filters'])
        self.assertEqual(mediatools.unavailable_tools(info), [])


class ApplyRefusesTests(unittest.TestCase):
    """As 5 ferramentas recusam um build sem os filtros antes de rodar qualquer coisa."""
    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup); self.dir = Path(self.tmp.name)

    def test_each_tool_refuses_a_lean_build(self):
        if not mediatools.find_tool('ffmpeg'):
            self.skipTest('sem FFmpeg')
        import subprocess
        src = self.dir / 'a.wav'
        subprocess.run([mediatools.find_tool('ffmpeg'), '-v', 'error', '-y', '-f', 'lavfi', '-i', 'sine=d=2', str(src)], check=True, capture_output=True)
        real = mediatools.build_info(refresh=True)
        lean = {**real, 'filters': ['volume']}
        cases = ((audiochannels, {'chan_mode': 'stereo'}), (audionorm, {'norm_target': 'podcast'}), (audiobleep, {'bleep_ranges': ['0-1']}), (audioviz, {}), (audiotrim, {'trim_mode': 'silence'}))
        with mock.patch.object(mediatools, 'build_info', return_value=lean), mock.patch.object(mediatools, '_filter_exists', return_value=False):
            for module, job in cases:
                with self.subTest(module=module.__name__):
                    stage = self.dir / f'{module.__name__}.out'
                    with self.assertRaises(MediaError) as caught:
                        module.apply(src, stage, job)
                    self.assertIn('compilado sem o filtro', str(caught.exception)); self.assertFalse(stage.exists())


if __name__ == '__main__':
    unittest.main()


class ConfirmationTests(unittest.TestCase):
    """Se a lista de `-filters` não mostrar um filtro, o app pergunta ao FFmpeg antes de recusar (formato muda entre versões)."""
    def info(self):
        return {'filters': ['volume'], 'exe': '/x/ffmpeg'}

    def test_filter_found_by_direct_check_is_not_missing(self):
        with mock.patch.object(mediatools, '_filter_exists', return_value=True):
            self.assertEqual(mediatools._missing(self.info(), ('aeval', 'volume')), [])

    def test_filter_really_missing(self):
        with mock.patch.object(mediatools, '_filter_exists', return_value=False):
            self.assertEqual(mediatools._missing(self.info(), ('aeval', 'volume')), ['aeval'])

    def test_unreadable_list_never_blocks(self):
        self.assertEqual(mediatools._missing({'filters': None}, ('aeval',)), [])

    def test_filter_exists_parses_the_help_output(self):
        mediatools._cache.clear()
        with mock.patch.object(mediatools, 'run_tool', return_value='Filter aeval\n  Filter audio signal\n'):
            self.assertTrue(mediatools._filter_exists('/x/ffmpeg', 'aeval'))
        mediatools._cache.clear()
        with mock.patch.object(mediatools, 'run_tool', return_value="Unknown filter 'aeval'.\n"):
            self.assertFalse(mediatools._filter_exists('/x/ffmpeg', 'aeval'))
        mediatools._cache.clear()
        with mock.patch.object(mediatools, 'run_tool', side_effect=MediaError('x')):
            self.assertTrue(mediatools._filter_exists('/x/ffmpeg', 'aeval'))
        mediatools._cache.clear()

    @unittest.skipUnless(mediatools.find_tool('ffmpeg'), 'sem FFmpeg')
    def test_real_ffmpeg_confirms_real_filters(self):
        exe = mediatools.find_tool('ffmpeg'); mediatools._cache.clear()
        self.assertTrue(mediatools._filter_exists(exe, 'aeval')); self.assertFalse(mediatools._filter_exists(exe, 'filtro_que_nao_existe'))
