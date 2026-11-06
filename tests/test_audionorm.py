"""Áudio, item 7: normalizar o volume (EBU R128, duas passadas, ganho linear, recusa de clipping).

Planejamento, análise e textos são testados sem FFmpeg; a ponta a ponta usa o FFmpeg real.
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

import audionorm
import engine
import mediatools
import runner
from audionorm import MediaError

FFMPEG = mediatools.find_tool('ffmpeg')
NEEDS_FFMPEG = unittest.skipUnless(FFMPEG and mediatools.find_tool('ffprobe'), 'FFmpeg/ffprobe não instalados')

JSON = '''[Parsed_loudnorm_0 @ 0x1]
{
\t"input_i" : "-33.75",
\t"input_tp" : "-30.06",
\t"input_lra" : "0.00",
\t"input_thresh" : "-43.75",
\t"output_i" : "-16.03",
\t"target_offset" : "0.03"
}
'''


def info(container='flac', codec='flac', **extra):
    return {'container': container, 'codec': codec, 'channels': 2, 'audio_streams': 1, 'has_video': False, 'has_cover': False, 'chapters': 0,
            'duration': 6.0, 'sample_rate': 44100, 'tags': {}, 'extra_tags': {}, **extra}


def run(*args):
    subprocess.run([FFMPEG, '-hide_banner', '-nostdin', '-v', 'error', '-y', *args], check=True, stdin=subprocess.DEVNULL, capture_output=True, timeout=90)


def tone(path, db, *extra, seconds=6, af=''):
    run('-f', 'lavfi', '-i', f'sine=f=440:d={seconds}:sample_rate=44100,volume={db}dB{af}', *extra, str(path))
    return Path(path)


class OptionAndParseTests(unittest.TestCase):
    def test_options(self):
        self.assertEqual(audionorm.options_from({}), ('podcast', 'medium'))
        self.assertEqual(audionorm.options_from({'norm_target': 'ebu', 'audio_quality': 'high'}), ('ebu', 'high'))
        for job in ({'norm_target': '-16'}, {'audio_quality': 'x'}):
            with self.subTest(job=job), self.assertRaises(MediaError):
                audionorm.options_from(job)

    def test_parse_tolerates_prefix_crlf_and_inf(self):
        expected = {'i': -33.75, 'tp': -30.06, 'lra': 0.0}
        self.assertEqual(audionorm.parse_loudness(JSON), expected)
        self.assertEqual(audionorm.parse_loudness(JSON.replace('\n', '\r\n')), expected)
        self.assertEqual(audionorm.parse_loudness(JSON.replace('-33.75', '-inf'))['i'], None)
        self.assertEqual(audionorm.parse_loudness('lixo { não é json } fim'), {})
        self.assertEqual(audionorm.parse_loudness(None), {})
        self.assertEqual(audionorm.parse_loudness(JSON + 'ruído depois\n'), expected)

    def test_measure_args_are_safe(self):
        args = audionorm.measure_args('/in/a.wav')
        for expected in ('-nostdin', '-protocol_whitelist', 'file:/in/a.wav', '-vn'):
            self.assertIn(expected, args)
        self.assertEqual(args[-3:], ['-f', 'null', '-'])


class PlanTests(unittest.TestCase):
    def test_gain_reaches_the_target(self):
        self.assertEqual(audionorm.plan_gain({'i': -20.0, 'tp': -9.0}, -16.0, -1.5), 4.0)
        self.assertEqual(audionorm.plan_gain({'i': -10.0, 'tp': -1.0}, -16.0, -1.5), -6.0)           # baixar nunca causa clipping

    def test_clipping_is_refused_with_the_reachable_level(self):
        with self.assertRaises(MediaError) as caught:
            audionorm.plan_gain({'i': -20.0, 'tp': -2.0}, -14.0, -1.5)
        text = str(caught.exception)
        self.assertIn('clipping', text); self.assertIn('−19,5 LUFS', text)                       # -1,5 − (−2) + (−20)
        self.assertEqual(audionorm.plan_gain({'i': -20.0, 'tp': -2.0}, -19.5, -1.5), 0.5)         # exatamente no limite passa

    def test_refusals(self):
        for levels, word in (({'i': None, 'tp': None}, 'mudo'), ({'i': -75.0, 'tp': -60.0}, 'mudo'), ({'i': -16.1, 'tp': -5.0}, 'já está no alvo'),
                             ({'i': -60.0, 'tp': -80.0}, 'ruído'), ({}, 'mudo')):
            with self.subTest(levels=levels), self.assertRaises(MediaError) as caught:
                audionorm.plan_gain(levels, -16.0, -1.5)
            self.assertIn(word, str(caught.exception))

    def test_lossy_formats_keep_more_headroom(self):
        self.assertLess(audionorm.tp_limit('mp3'), audionorm.tp_limit('flac'))

    def test_filter_and_notes(self):
        self.assertEqual(audionorm.audio_filter(-3.456), 'volume=-3.46dB')
        text = ' '.join(audionorm.notes(info('mp3', 'mp3', has_cover=True, chapters=1), 'music', 'low'))
        self.assertIn('−14,0 LUFS', text); self.assertIn('com perda', text); self.assertIn('capítulos', text); self.assertIn('-normalizado', text)
        self.assertIn('sem perda', ' '.join(audionorm.notes(info(), 'ebu', 'medium')))
        self.assertIn('16 bits', ' '.join(audionorm.notes(info('wav', 'pcm_s16le'), 'ebu', 'medium')))
        self.assertTrue(audionorm.notes(None, 'podcast', 'medium'))
        self.assertEqual(audionorm.fmt(-16.04, 'LUFS'), '−16,0 LUFS'); self.assertEqual(audionorm.fmt(None, 'dB'), 'mudo')


@NEEDS_FFMPEG
class EndToEndTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        mediatools.reset_cache()

    def job(self, source, target='podcast', **options):
        return {'target': engine.AUDIO_NORM, 'paths': [str(source)], 'output': str(self.dir), 'norm_target': target, **options}

    def lufs(self, path):
        return audionorm.measure(FFMPEG, str(path))['i']

    def test_quiet_and_loud_files_land_on_the_target_in_every_format(self):
        outputs = (mediatools.build_info() or {}).get('outputs', [])
        import audioconvert
        for kind in audioconvert.FORMATS:
            with self.subTest(kind=kind):
                if kind not in outputs:
                    self.skipTest(f'sem codificador de {kind}')
                codec = {'ogg': ['-c:a', 'libvorbis'], 'opus': ['-c:a', 'libopus'], 'm4a': ['-c:a', 'aac'], 'mp3': ['-c:a', 'libmp3lame']}.get(kind, [])
                source = tone(self.dir / f'm.{kind}', -20, *codec, '-metadata', 'title=Canção')
                [out] = engine.convert(self.job(source, 'podcast'))
                self.assertEqual(Path(out).name, f'm-normalizado.{kind}')
                self.assertAlmostEqual(self.lufs(out), -16.0, delta=0.8)
                if kind != 'aiff':
                    self.assertEqual(mediatools.probe(out)['tags'].get('title'), 'Canção')
                self.assertTrue(any('Volume: de' in n for n in engine.RUN_NOTES))
                for path in list(self.dir.iterdir()):
                    path.unlink()

    def test_loud_file_is_turned_down(self):
        source = tone(self.dir / 'loud.flac', -3)
        [out] = engine.convert(self.job(source, 'ebu'))
        self.assertAlmostEqual(self.lufs(out), -23.0, delta=0.5)

    def test_every_preset_reaches_its_target_when_possible(self):
        source = tone(self.dir / 'p.flac', -20)
        for key, lufs in (('ebu', -23.0), ('podcast', -16.0), ('music', -14.0)):
            with self.subTest(key=key):
                try:
                    [out] = engine.convert(self.job(source, key))
                except engine.ConversionError as error:
                    self.assertIn('clipping', str(error)); continue
                self.assertAlmostEqual(self.lufs(out), lufs, delta=0.5)

    def test_target_that_would_clip_is_refused_and_leaves_no_file(self):
        run('-f', 'lavfi', '-i', 'sine=f=440:d=6:sample_rate=44100', '-af', "volume=-14dB,volume=14dB:enable='between(t,3,3.02)'", str(self.dir / 'peak.flac'))        # som baixo com um estalo de pico alto
        before = sorted(p.name for p in self.dir.iterdir())
        with self.assertRaises(engine.ConversionError) as caught:
            engine.convert(self.job(self.dir / 'peak.flac', 'music'))
        self.assertIn('peak.flac', str(caught.exception)); self.assertIn('clipping', str(caught.exception))
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), before)

    def test_silence_short_and_already_on_target_are_refused(self):
        run('-f', 'lavfi', '-i', 'anullsrc=r=44100:cl=mono:d=3', str(self.dir / 'sil.wav'))
        run('-f', 'lavfi', '-i', 'sine=f=440:d=0.3:sample_rate=44100', str(self.dir / 'short.wav'))
        for name in ('sil.wav', 'short.wav'):
            with self.subTest(name=name), self.assertRaises(engine.ConversionError) as caught:
                engine.convert(self.job(self.dir / name))
            self.assertIn('mudo', str(caught.exception))
        source = tone(self.dir / 'ok.flac', -20)
        [out] = engine.convert(self.job(source, 'podcast'))
        with self.assertRaises(engine.ConversionError) as caught:                                    # a cópia já está no alvo
            engine.convert(self.job(out, 'podcast'))
        self.assertIn('já está no alvo', str(caught.exception))

    def test_surround_keeps_channels(self):
        source = self.dir / 's.flac'
        run('-f', 'lavfi', '-i', 'sine=f=440:d=6:sample_rate=44100,volume=-20dB,pan=5.1|c0=c0|c1=c0|c2=c0|c3=c0|c4=c0|c5=c0', str(source))
        [out] = engine.convert(self.job(source, 'ebu'))
        self.assertEqual(mediatools.probe(out)['channels'], 6)

    def test_cover_survives_for_mp3(self):
        if 'mp3' not in (mediatools.build_info() or {}).get('outputs', []):
            self.skipTest('sem codificador de mp3')
        run('-f', 'lavfi', '-i', 'color=c=red:s=32x32:d=1', '-frames:v', '1', str(self.dir / 'c.png'))
        run('-f', 'lavfi', '-i', 'sine=f=440:d=6:sample_rate=44100,volume=-20dB', '-i', str(self.dir / 'c.png'), '-map', '0:a', '-map', '1:v', '-c:a', 'libmp3lame', '-c:v', 'mjpeg',
            '-disposition:v', 'attached_pic', str(self.dir / 'capa.mp3'))
        [out] = engine.convert(self.job(self.dir / 'capa.mp3'))
        self.assertTrue(mediatools.probe(out)['has_cover'])

    def test_original_untouched_and_collisions_never_overwrite(self):
        source = tone(self.dir / 'p.flac', -20); before = source.read_bytes()
        a = engine.convert(self.job(source))[0]; b = engine.convert(self.job(source))[0]
        self.assertEqual([Path(a).name, Path(b).name], ['p-normalizado.flac', 'p-normalizado-2.flac']); self.assertEqual(source.read_bytes(), before)

    def test_not_audio_is_refused(self):
        (self.dir / 'x.mp3').write_bytes(b'not audio')
        with self.assertRaises(engine.ConversionError):
            engine.convert(self.job(self.dir / 'x.mp3'))

    def test_loudness_operation_and_worker(self):
        source = tone(self.dir / 'l.wav', -20)
        result = audionorm.run_op({'op': 'audio_loudness', 'paths': [str(source)]})
        self.assertAlmostEqual(result['i'], self.lufs(source), delta=0.01)
        self.assertEqual(runner.run_media_op({'op': 'audio_loudness', 'paths': [str(source)]}, timeout=120)['name'], 'l.wav')
        (self.dir / 'x.mp3').write_bytes(b'not audio')
        self.assertIn('error', audionorm.run_op({'op': 'audio_loudness', 'paths': [str(self.dir / 'x.mp3')]}))
        with self.assertRaises(MediaError):
            audionorm.run_op({'op': 'audio_loudness', 'paths': ['a', 'b']})
        done = runner.run_job(self.job(source))
        self.assertEqual(Path(done[0]).name, 'l-normalizado.wav')
        self.assertTrue(any('Volume: de' in n for n in runner.take_notes()))

    def test_loss_report_reads_the_file(self):
        source = tone(self.dir / 'p.flac', -20)
        self.assertIn('−16,0 LUFS', ' '.join(engine.loss_report([str(source)], engine.AUDIO_NORM, {'norm_target': 'podcast'})))
        self.assertIn('Escolha', ' '.join(engine.loss_report([str(source)], engine.AUDIO_NORM, {'norm_target': 'x'})))


class RegistrationTests(unittest.TestCase):
    def test_target_options_and_wheel(self):
        import tool_registry
        self.assertIn(engine.AUDIO_NORM, engine.OPERATIONS); self.assertIn(engine.AUDIO_NORM, engine.PDF_LONG_TARGETS)
        self.assertIn('norm_target', tool_registry.BASE_STR_OPTIONS)
        self.assertEqual([m[0] for m in tool_registry.AUDIO_GROUPS['adjust'][3]], [engine.AUDIO_CHANNELS, engine.AUDIO_NORM])


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

    def open_tool(self, files=('/x/a.flac',), loudness=None, **extra):
        self.panel.select_category('audio')
        self.panel.files = list(files)
        with mock.patch.object(self.panel.audio_stage, 'show_files'), mock.patch.object(self.panel.audio_stage.loudness, 'show_file'):
            self.panel.select_tool(self.wp.AUDIO_NORM)
        self.panel.audio_stage.infos = {path: info(name=Path(path).name, **extra) for path in files}
        self.panel.audio_stage.loudness.data = {'i': -20.0, 'tp': -9.0, 'lra': 1.0} if loudness is None else loudness
        self.panel._audionorm_changed()

    def test_values_follow_the_chips(self):
        self.open_tool()
        self.assertEqual(self.panel._audionorm_values(), {'norm_target': 'podcast', 'audio_quality': 'medium'})
        self.panel.nm_target.setCurrentIndex(2); self.panel.nm_quality.setCurrentIndex(2)
        self.assertEqual(self.panel._audionorm_values(), {'norm_target': 'music', 'audio_quality': 'high'})

    def test_state_shows_the_measurement_and_gain(self):
        self.open_tool()
        text, ready = self.panel._audionorm_state()
        self.assertTrue(ready); self.assertIn('−20,0 LUFS', text); self.assertIn('+4,0 dB', text); self.assertTrue(self.panel.run_button.isEnabled())

    def test_clipping_target_blocks_the_button_with_the_reason(self):
        self.open_tool(loudness={'i': -20.0, 'tp': -2.0, 'lra': 1.0})
        self.panel.nm_target.setCurrentIndex(2)                           # −14 passaria do limite
        text, ready = self.panel._audionorm_state()
        self.assertFalse(ready); self.assertIn('clipping', text); self.assertFalse(self.panel.run_button.isEnabled())
        self.panel.nm_target.setCurrentIndex(0); self.assertTrue(self.panel._audionorm_state()[1])

    def test_lossy_limit_is_stricter_than_lossless(self):
        loud = {'i': -20.0, 'tp': -5.2, 'lra': 1.0}                       # +4 dB dá −1,2 dBTP: passa no FLAC (limite −1,0) mas não no MP3 (−1,5)
        self.open_tool(loudness=loud); self.assertTrue(self.panel._audionorm_state()[1])
        self.open_tool(loudness=loud, container='mp3', codec='mp3')
        self.assertFalse(self.panel._audionorm_state()[1])

    def test_waiting_error_and_many_files(self):
        self.open_tool(loudness={}); self.panel.audio_stage.loudness.data = {}
        self.assertEqual(self.panel._audionorm_state(), ('Medindo o volume…', False))
        self.panel.audio_stage.loudness.data = {'error': 'O áudio está mudo.'}
        self.assertEqual(self.panel._audionorm_state(), ('O áudio está mudo.', False))
        self.open_tool(files=('/x/a.flac', '/x/b.flac'))
        text, ready = self.panel._audionorm_state()
        self.assertTrue(ready); self.assertIn('2 arquivos', text)

    def test_blocked_without_ffmpeg_video_or_while_reading(self):
        self.open_tool(); self.panel.audio_stage.infos = {}
        self.assertFalse(self.panel._audionorm_state()[1])
        self.open_tool(has_video=True); self.assertIn('vídeo', self.panel._audionorm_state()[0])
        self.panel.controller.capabilities['audio'] = (False, 'FFmpeg não encontrado.')
        self.assertEqual(self.panel._audionorm_state(), ('FFmpeg não encontrado.', False))

    def test_probe_ignores_stale_answers(self):
        probe = self.panel.audio_stage.loudness
        probe.loader = lambda job: {'name': 'a', 'i': -20.0, 'tp': -9.0}
        probe.show_file('/x/a.wav'); self.assertEqual(probe.data['i'], -20.0)
        probe._apply(probe._token - 1, {'i': 0.0}, ''); self.assertEqual(probe.data['i'], -20.0)
        probe.loader = lambda job: (_ for _ in ()).throw(RuntimeError('quebrou'))
        probe.path = ''; probe.show_file('/x/b.wav'); self.assertEqual(probe.data, {'error': 'quebrou'})
        probe.reset(); self.assertEqual(probe.path, '')

    def test_run_sends_the_options(self):
        self.open_tool()
        started = []
        self.panel.controller.start_job = lambda *args, **kwargs: started.append((args, kwargs))
        self.panel.nm_target.setCurrentIndex(0)
        self.panel.run_selected()
        self.assertTrue(started, self.panel.status.text())
        text = repr(started[0]); self.assertIn("'norm_target': 'ebu'", text); self.assertIn(self.wp.AUDIO_NORM, text)


if __name__ == '__main__':
    unittest.main()
