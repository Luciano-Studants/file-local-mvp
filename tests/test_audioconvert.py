"""Áudio, item 3: converter áudio (MP3, M4A, FLAC, OGG, Opus, WAV, AIFF) com o FFmpeg.

Os testes de argumentos, limites e textos não precisam de FFmpeg; os de ponta a ponta (motor e worker de verdade) usam o FFmpeg real,
geram a entrada com fontes sintéticas e são pulados quando ele não existe.
"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import audioconvert
import engine
import mediatools
import runner
from audioconvert import FORMATS, MediaError

FFMPEG = mediatools.find_tool('ffmpeg')
NEEDS_FFMPEG = unittest.skipUnless(FFMPEG and mediatools.find_tool('ffprobe'), 'FFmpeg/ffprobe não instalados')
INFO = {'duration': 10.0, 'sample_rate': 44100, 'channels': 2, 'has_video': False, 'audio_streams': 1, 'has_cover': False, 'chapters': 0, 'codec': 'flac'}


def make(path, *args):
    subprocess.run([FFMPEG, '-hide_banner', '-nostdin', '-v', 'error', '-y', *args, str(path)], check=True, stdin=subprocess.DEVNULL, capture_output=True, timeout=90)
    return Path(path)


def tone(path, seconds=2, rate=44100, extra=()):
    return make(path, '-f', 'lavfi', '-i', f'sine=frequency=440:duration={seconds}:sample_rate={rate}', *extra)


class OptionTests(unittest.TestCase):
    def test_defaults_and_valid_values(self):
        self.assertEqual(audioconvert.options_from({}), ('mp3', 'medium', 'keep'))
        self.assertEqual(audioconvert.options_from({'audio_format': 'opus', 'audio_quality': 'high', 'audio_tags': 'drop'}), ('opus', 'high', 'drop'))

    def test_invalid_values_are_refused(self):
        for key, value in (('audio_format', 'wma'), ('audio_format', '../x'), ('audio_quality', 'ultra'), ('audio_tags', 'tanto faz')):
            with self.subTest(key=key), self.assertRaises(MediaError):
                audioconvert.options_from({key: value})

    def test_every_format_has_an_encoder_known_to_the_media_base(self):
        self.assertEqual(set(FORMATS), set(mediatools.OUTPUT_ENCODERS))
        for fmt, spec in FORMATS.items():
            self.assertIn(spec['encoder'], mediatools.OUTPUT_ENCODERS[fmt])
            if spec['lossy']:
                self.assertEqual(set(audioconvert.QUALITY_ARGS[fmt]), set(audioconvert.QUALITIES))
                self.assertEqual(set(audioconvert.BITRATES[fmt]), set(audioconvert.QUALITIES))


class ArgumentTests(unittest.TestCase):
    def args(self, fmt='mp3', quality='medium', tags='keep', info=None):
        return audioconvert.build_args('/in/a.flac', '/work/out', fmt, quality, tags, info or INFO)

    def test_input_is_sandboxed(self):
        args = self.args()
        self.assertIn('-nostdin', args)
        self.assertEqual(args[args.index('-protocol_whitelist') + 1], 'file')
        self.assertIn('-format_whitelist', args)
        self.assertEqual(args[args.index('-i') + 1], 'file:/in/a.flac')
        self.assertEqual(args[-1], 'file:/work/out')
        self.assertLess(args.index('-protocol_whitelist'), args.index('-i'))
        self.assertLess(args.index('-format_whitelist'), args.index('-i'))
        self.assertIn('-n', args)                       # nunca sobrescreve

    def test_only_the_first_audio_stream_without_video_or_chapters(self):
        args = self.args()
        self.assertEqual(args[args.index('-map') + 1], '0:a:0')
        for flag in ('-vn', '-sn', '-dn'):
            self.assertIn(flag, args)
        self.assertEqual(args[args.index('-map_chapters') + 1], '-1')

    def test_tags_keep_or_drop(self):
        keep, drop = self.args(tags='keep'), self.args(tags='drop')
        self.assertEqual(keep[keep.index('-map_metadata') + 1], '0')
        self.assertEqual(drop[drop.index('-map_metadata') + 1], '-1')

    def test_quality_changes_lossy_arguments_only(self):
        self.assertNotEqual(self.args('mp3', 'low'), self.args('mp3', 'high'))
        self.assertEqual(self.args('flac', 'low'), self.args('flac', 'high'))
        self.assertIn('320k', self.args('mp3', 'high'))
        self.assertIn('-q:a', self.args('ogg', 'medium'))

    def test_mp3_downmixes_more_than_two_channels(self):
        self.assertIn('-ac', self.args('mp3', info={**INFO, 'channels': 6}))
        self.assertNotIn('-ac', self.args('mp3'))
        self.assertNotIn('-ac', self.args('flac', info={**INFO, 'channels': 6}))

    def test_output_has_a_size_cap(self):
        args = self.args()
        self.assertLess(int(args[args.index('-fs') + 1]), engine.MAX_OUTPUT)


class EstimateTests(unittest.TestCase):
    def test_lossless_estimate_is_pcm_size(self):
        self.assertAlmostEqual(audioconvert.estimate_bytes('wav', 'low', INFO), 10 * 44100 * 2 * 2, delta=70000)
        self.assertEqual(audioconvert.estimate_bytes('flac', 'low', INFO), audioconvert.estimate_bytes('aiff', 'low', INFO))

    def test_lossy_estimate_follows_the_bitrate(self):
        self.assertAlmostEqual(audioconvert.estimate_bytes('mp3', 'high', INFO), 10 * 320000 / 8, delta=70000)

    def test_unknown_duration_gives_zero(self):
        self.assertEqual(audioconvert.estimate_bytes('wav', 'low', {**INFO, 'duration': 0}), 0)

    def test_huge_lossless_output_is_refused_before_running(self):
        long = {**INFO, 'duration': 4 * 3600.0, 'sample_rate': 96000, 'channels': 2}
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'a.flac'; source.write_bytes(b'x')
            with mock.patch.object(mediatools, 'find_tool', return_value='/usr/bin/ffmpeg'), mock.patch.object(mediatools, 'build_info', return_value=None), \
                 mock.patch.object(mediatools, 'probe', return_value=long), mock.patch.object(audioconvert, '_run') as run:
                with self.assertRaises(MediaError) as caught:
                    audioconvert.convert(source, Path(folder) / 'out', {'audio_format': 'wav'})
            self.assertIn('512 MiB', str(caught.exception)); run.assert_not_called()

    def test_unknown_duration_is_refused_for_pcm_but_not_for_lossy(self):
        zero = {**INFO, 'duration': 0.0}
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'a.flac'; source.write_bytes(b'x')
            with mock.patch.object(mediatools, 'find_tool', return_value='/usr/bin/ffmpeg'), mock.patch.object(mediatools, 'build_info', return_value=None), \
                 mock.patch.object(mediatools, 'probe', return_value=zero), mock.patch.object(audioconvert, '_run', side_effect=MediaError('parou')):
                with self.assertRaises(MediaError) as caught:
                    audioconvert.convert(source, Path(folder) / 'out', {'audio_format': 'wav'})
                self.assertIn('duração', str(caught.exception))
                with self.assertRaises(MediaError) as caught:
                    audioconvert.convert(source, Path(folder) / 'out', {'audio_format': 'mp3'})
                self.assertEqual(str(caught.exception), 'parou')


class LossNoteTests(unittest.TestCase):
    def test_lossy_target_says_so(self):
        text = ' '.join(audioconvert.loss_notes(INFO, 'mp3', 'medium', 'keep'))
        self.assertIn('com perda', text); self.assertIn('192', text); self.assertIn('original não é alterado', text)

    def test_lossless_notes_differ(self):
        self.assertIn('16 bits', ' '.join(audioconvert.loss_notes(INFO, 'wav', 'low', 'keep')))
        self.assertIn('não perde qualidade', ' '.join(audioconvert.loss_notes(INFO, 'flac', 'low', 'keep')))

    def test_video_cover_chapters_streams_and_channels_are_mentioned(self):
        rich = {**INFO, 'has_video': True, 'has_cover': True, 'chapters': 3, 'audio_streams': 2, 'channels': 6}
        text = ' '.join(audioconvert.loss_notes(rich, 'mp3', 'low', 'drop'))
        for word in ('vídeo', 'capa', 'capítulos', 'primeira', 'estéreo', 'removidas'):
            self.assertIn(word, text)

    def test_same_format_warning_and_missing_info(self):
        self.assertIn('já está neste formato', ' '.join(audioconvert.loss_notes({**INFO, 'codec': 'mp3'}, 'mp3', 'low', 'keep')))
        self.assertTrue(audioconvert.loss_notes(None, 'ogg', 'low', 'keep'))


@NEEDS_FFMPEG
class EndToEndTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        mediatools.reset_cache()

    def job(self, source, **options):
        return {'target': engine.AUDIO_CONVERT, 'paths': [str(source)], 'output': str(self.dir), **options}

    def names(self):
        return sorted(p.name for p in self.dir.iterdir())

    def test_every_format_round_trips_and_the_original_is_untouched(self):
        source = tone(self.dir / 'tom.flac', extra=('-metadata', 'title=Canção', '-metadata', 'artist=Ela'))
        before = source.read_bytes()
        for fmt, spec in FORMATS.items():
            with self.subTest(fmt=fmt):
                if fmt not in (mediatools.build_info() or {}).get('outputs', []):
                    self.skipTest(f'sem codificador de {fmt}')
                [out] = engine.convert(self.job(source, audio_format=fmt, audio_quality='low'))
                self.assertEqual(Path(out).name, f'tom-convertido.{spec["suffix"]}')
                info = mediatools.probe(out)
                self.assertIn(info['codec'], spec['codecs']); self.assertEqual(info['audio_streams'], 1)
                self.assertAlmostEqual(info['duration'], 2.0, delta=0.3)
                Path(out).unlink()
        self.assertEqual(source.read_bytes(), before)
        self.assertEqual(self.names(), ['tom.flac'])                       # nada de arquivo de preparo sobrando

    def test_tags_are_kept_by_default_and_removed_on_request(self):
        source = tone(self.dir / 'tom.flac', extra=('-metadata', 'title=Canção', '-metadata', 'artist=Ela'))
        [kept] = engine.convert(self.job(source, audio_format='ogg'))
        self.assertEqual(mediatools.probe(kept)['tags'].get('title'), 'Canção')
        [dropped] = engine.convert(self.job(source, audio_format='m4a', audio_tags='drop'))
        self.assertEqual(mediatools.probe(dropped)['tags'], {})

    def test_name_collisions_never_overwrite(self):
        source = tone(self.dir / 'tom.wav')
        first = engine.convert(self.job(source, audio_format='mp3'))[0]
        second = engine.convert(self.job(source, audio_format='mp3'))[0]
        self.assertEqual([Path(first).name, Path(second).name], ['tom-convertido.mp3', 'tom-convertido-2.mp3'])

    def test_surround_becomes_stereo_for_mp3_and_stays_for_flac(self):
        source = tone(self.dir / 'six.wav', extra=('-ac', '6'))
        self.assertEqual(mediatools.probe(engine.convert(self.job(source, audio_format='mp3'))[0])['channels'], 2)
        self.assertEqual(mediatools.probe(engine.convert(self.job(source, audio_format='flac'))[0])['channels'], 6)

    def test_audio_is_extracted_from_a_video(self):
        video = make(self.dir / 'clip.mp4', '-f', 'lavfi', '-i', 'testsrc=duration=2:size=64x64:rate=10', '-f', 'lavfi', '-i', 'sine=duration=2', '-shortest', '-c:v', 'mpeg4')
        [out] = engine.convert(self.job(video, audio_format='flac'))
        info = mediatools.probe(out)
        self.assertEqual(info['codec'], 'flac'); self.assertFalse(info['has_video'])

    def test_extension_does_not_decide_the_format(self):
        wav = tone(self.dir / 'real.wav'); fake = self.dir / 'verdade.mp3'; fake.write_bytes(wav.read_bytes())
        [out] = engine.convert(self.job(fake, audio_format='flac'))
        self.assertEqual(mediatools.probe(out)['codec'], 'flac')

    def test_non_audio_input_fails_cleanly_without_leftovers(self):
        bogus = self.dir / 'texto.mp3'; bogus.write_text('isto não é áudio')
        with self.assertRaises(engine.ConversionError) as caught:
            engine.convert(self.job(bogus))
        self.assertIn('texto.mp3', str(caught.exception))
        self.assertEqual(self.names(), ['texto.mp3'])

    def test_playlist_files_cannot_pull_other_files_in(self):
        secret = tone(self.dir / 'segredo.wav')
        playlist = self.dir / 'lista.m3u8'
        playlist.write_text(f'#EXTM3U\n#EXT-X-TARGETDURATION:2\n#EXTINF:2,\nfile:{secret}\n#EXT-X-ENDLIST\n')
        with self.assertRaises(engine.ConversionError):
            engine.convert(self.job(playlist))
        self.assertNotIn('lista-convertido.mp3', self.names())

    def test_invalid_options_are_refused_before_any_output(self):
        source = tone(self.dir / 'tom.wav')
        for options in ({'audio_format': 'wma'}, {'audio_quality': 'x'}, {'audio_tags': 'x'}):
            with self.subTest(options=options), self.assertRaises(engine.ConversionError):
                engine.convert(self.job(source, **options))
        self.assertEqual(self.names(), ['tom.wav'])

    def test_one_file_per_job_and_audio_size_limit(self):
        a, b = tone(self.dir / 'a.wav'), tone(self.dir / 'b.wav')
        with self.assertRaises(engine.ConversionError):
            engine.convert({**self.job(a), 'paths': [str(a), str(b)]})
        self.assertEqual(engine.source_file(str(a), 10 ** 9), a.resolve())
        with self.assertRaises(engine.ConversionError) as caught:
            engine.source_file(str(a), 1000)
        self.assertIn('MiB', str(caught.exception))
        self.assertGreater(engine.AUDIO_MAX_BYTES, engine.MAX_BYTES)

    def test_loss_report_reads_the_real_file(self):
        source = tone(self.dir / 'tom.flac')
        text = ' '.join(engine.loss_report([str(source)], engine.AUDIO_CONVERT, {'audio_format': 'wav'}))
        self.assertIn('16 bits', text)
        self.assertIn('inválido', ' '.join(engine.loss_report([str(source)], engine.AUDIO_CONVERT, {'audio_format': 'zzz'})).lower())

    def test_runs_in_the_real_worker_and_publishes_atomically(self):
        source = tone(self.dir / 'tom.wav')
        [out] = runner.run_job({'target': engine.AUDIO_CONVERT, 'paths': [str(source)], 'audio_format': 'opus', 'audio_quality': 'low'})
        self.assertEqual(Path(out).name, 'tom-convertido.opus')
        self.assertEqual(mediatools.probe(out)['codec'], 'opus')
        self.assertEqual(self.names(), ['tom-convertido.opus', 'tom.wav'])

    def test_cancel_leaves_no_output(self):
        import threading
        source = tone(self.dir / 'tom.wav'); cancel = threading.Event(); cancel.set()
        with self.assertRaises(runner.Cancelled):
            runner.run_job({'target': engine.AUDIO_CONVERT, 'paths': [str(source)]}, cancel)
        self.assertEqual(self.names(), ['tom.wav'])

    def test_verification_rejects_a_wrong_duration(self):
        source = tone(self.dir / 'tom.wav')
        real = mediatools.probe
        def fake(path):
            info = real(path)
            if Path(path).name == 'out': info = {**info, 'duration': info['duration'] + 30}
            return info
        with mock.patch.object(mediatools, 'probe', side_effect=fake), self.assertRaises(MediaError):
            audioconvert.convert(source, self.dir / 'out', {'audio_format': 'flac'})
        self.assertFalse((self.dir / 'out').exists())


class LongTargetTests(unittest.TestCase):
    def test_audio_conversion_gets_the_long_timeout(self):
        self.assertIn(engine.AUDIO_CONVERT, engine.PDF_LONG_TARGETS)
        self.assertLess(audioconvert.CONVERT_TIMEOUT, engine.PDF_OCR_TIMEOUT)

    def test_target_and_options_are_registered(self):
        import tool_registry
        self.assertIn(engine.AUDIO_CONVERT, engine.OPERATIONS)
        for key in ('audio_format', 'audio_quality', 'audio_tags'):
            self.assertIn(key, tool_registry.BASE_STR_OPTIONS)


class PanelTests(unittest.TestCase):
    def setUp(self):
        from PySide6.QtWidgets import QApplication
        self.app = QApplication.instance() or QApplication([])
        import workspace_panel as wp
        from tray_app import FeaturePanel, JobController
        self.wp = wp
        self.panel = FeaturePanel(JobController(capabilities={'images': (True, 'ok'), 'pdf': (True, 'ok'), 'audio': (True, 'ok')}))
        self.panel.audio_stage.capability = lambda: (True, 'ok')
        self.addCleanup(self.panel.close)

    def open_tool(self, infos=None, files=('/x/a.flac',)):
        self.panel.select_category('audio')
        self.panel.files = list(files)
        with mock.patch.object(self.panel.audio_stage, 'show_files'):          # sem QThread: as informações são injetadas
            self.panel.select_tool(self.wp.AUDIO_CONVERT)
        self.panel.audio_stage.infos = infos if infos is not None else {files[0]: {**INFO, 'name': 'a.flac'}}
        self.panel._audioconvert_changed()

    def test_values_follow_the_chips(self):
        self.open_tool()
        self.assertEqual(self.panel._audioconvert_values(), {'audio_format': 'mp3', 'audio_quality': 'medium', 'audio_tags': 'keep'})
        self.panel.ac_format.setCurrentIndex(3); self.panel.ac_quality.setCurrentIndex(2); self.panel.ac_tags.setCurrentIndex(1)
        self.assertEqual(self.panel._audioconvert_values(), {'audio_format': 'ogg', 'audio_quality': 'high', 'audio_tags': 'drop'})

    def test_every_chip_is_a_valid_engine_value(self):
        self.open_tool()
        for index in range(7):
            self.panel.ac_format.setCurrentIndex(index)
            audioconvert.options_from(self.panel._audioconvert_values())

    def test_tool_shows_its_controls_and_a_run_button(self):
        self.open_tool()
        self.assertFalse(self.panel.run_button.isHidden())
        self.assertEqual(self.panel.tool_title.text(), 'Converter áudio')
        self.assertEqual(self.panel.run_button.text(), 'Converter áudio')
        self.assertEqual(self.panel.stage.currentIndex(), self.wp.STAGE_AUDIO)

    def test_state_waits_for_the_reading_and_reports_errors(self):
        self.open_tool(infos={})
        self.assertFalse(self.panel._audioconvert_state()[1])
        self.panel.audio_stage.infos = {'/x/a.flac': {'name': 'a.flac', 'error': 'Este arquivo não contém áudio.'}}
        text, ready = self.panel._audioconvert_state()
        self.assertFalse(ready); self.assertIn('não contém áudio', text)

    def test_state_blocks_without_ffmpeg_and_huge_lossless_output(self):
        self.open_tool()
        self.panel.controller.capabilities['audio'] = (False, 'FFmpeg não encontrado.')
        self.assertEqual(self.panel._audioconvert_state(), ('FFmpeg não encontrado.', False))
        self.panel.controller.capabilities['audio'] = (True, 'ok')
        self.panel.audio_stage.infos = {'/x/a.flac': {**INFO, 'duration': 4 * 3600.0, 'sample_rate': 96000}}
        self.panel.ac_format.setCurrentIndex(5)           # WAV
        with mock.patch.object(mediatools, 'build_info', return_value={'outputs': list(FORMATS)}):
            text, ready = self.panel._audioconvert_state()
        self.assertFalse(ready); self.assertIn('512 MiB', text)

    def test_state_is_ready_and_describes_the_output(self):
        self.open_tool()
        with mock.patch.object(mediatools, 'build_info', return_value={'outputs': list(FORMATS)}):
            text, ready = self.panel._audioconvert_state()
            self.panel.ac_format.setCurrentIndex(2)       # FLAC
            lossless, _ready = self.panel._audioconvert_state()
        self.assertTrue(ready); self.assertIn('MP3', text); self.assertIn('Com perda', text)
        self.assertNotIn('Com perda', lossless); self.assertIn('Tamanho aproximado', lossless)

    def test_run_selected_sends_the_options(self):
        self.open_tool()
        started = []
        self.panel.controller.start_job = lambda *args, **kwargs: started.append((args, kwargs))
        with mock.patch.object(mediatools, 'build_info', return_value={'outputs': list(FORMATS)}):
            self.panel.ac_format.setCurrentIndex(4)
            self.panel.run_selected()
        self.assertTrue(started, self.panel.status.text())
        text = repr(started[0])
        self.assertIn("'audio_format': 'opus'", text); self.assertIn(self.wp.AUDIO_CONVERT, text)


if __name__ == '__main__':
    unittest.main()
