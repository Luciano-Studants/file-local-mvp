"""Áudio, item 5: canais (mono, estéreo, só esquerdo, só direito) com avisos medidos de fase e clipping.

Planejamento, argumentos, análise e textos são testados sem FFmpeg (a medição é simulada); a ponta a ponta usa o FFmpeg real.
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

import audiochannels
import audioconvert
import engine
import mediatools
import runner
from audiochannels import MediaError

FFMPEG = mediatools.find_tool('ffmpeg')
NEEDS_FFMPEG = unittest.skipUnless(FFMPEG and mediatools.find_tool('ffprobe'), 'FFmpeg/ffprobe não instalados')


def info(channels=2, container='flac', codec='flac', **extra):
    return {'container': container, 'codec': codec, 'channels': channels, 'audio_streams': 1, 'has_video': False, 'has_cover': False, 'chapters': 0,
            'duration': 2.0, 'sample_rate': 44100, 'tags': {}, 'extra_tags': {}, **extra}


def run(*args):
    subprocess.run([FFMPEG, '-hide_banner', '-nostdin', '-v', 'error', '-y', *args], check=True, stdin=subprocess.DEVNULL, capture_output=True, timeout=90)


def sine(path, af, *extra, seconds=2):
    run('-f', 'lavfi', '-i', f'sine=f=440:d={seconds}:sample_rate=44100', '-af', af, *extra, str(path))
    return Path(path)


class OptionAndPlanTests(unittest.TestCase):
    def test_options(self):
        self.assertEqual(audiochannels.options_from({'chan_mode': 'mono'}), ('mono', 'medium'))
        self.assertEqual(audiochannels.options_from({'chan_mode': 'left', 'audio_quality': 'high'}), ('left', 'high'))
        for job in ({}, {'chan_mode': 'surround'}, {'chan_mode': 'mono', 'audio_quality': 'x'}):
            with self.subTest(job=job), self.assertRaises(MediaError):
                audiochannels.options_from(job)

    def test_plan_matrix(self):
        cases = [(2, 'mono', 'pan=mono|c0=0.5*c0+0.5*c1', True, False, 1), (2, 'left', 'pan=mono|c0=c0', False, False, 1), (2, 'right', 'pan=mono|c0=c1', False, False, 1),
                 (1, 'stereo', 'pan=stereo|c0=c0|c1=c0', False, False, 2), (6, 'stereo', 'aresample=ochl=stereo', False, True, 2), (6, 'mono', 'aresample=ochl=mono', False, True, 1)]
        for channels, mode, expected, phase, measure, out in cases:
            with self.subTest(channels=channels, mode=mode):
                plan = audiochannels.plan(info(channels), mode)
                self.assertEqual((plan['filter'], plan['phase'], plan['measure'], plan['out']), (expected, phase, measure, out))

    def test_plan_refuses_pointless_or_impossible_requests(self):
        for channels, mode in ((1, 'mono'), (2, 'stereo'), (1, 'left'), (6, 'left'), (6, 'right'), (0, 'mono')):
            with self.subTest(channels=channels, mode=mode), self.assertRaises(MediaError):
                audiochannels.plan(info(channels), mode)

    def test_plan_refuses_unsupported_files(self):
        for patch in ({'has_video': True}, {'audio_streams': 2}, {'container': 'asf', 'codec': 'wmav2'}):
            with self.subTest(patch=patch), self.assertRaises(MediaError):
                audiochannels.plan(info(2, **patch), 'mono')


class ParsingAndArgumentTests(unittest.TestCase):
    def test_parse_levels(self):
        text = '[Parsed_astats_0 @ 0x1] Overall\n[Parsed_astats_0 @ 0x1] Peak level dB: -21.07\n[Parsed_astats_0 @ 0x1] RMS level dB: -24.08\n'
        self.assertEqual(audiochannels.parse_levels(text), {'peak': -21.07, 'rms': -24.08})
        self.assertEqual(audiochannels.parse_levels('[x] RMS level dB: -inf\n[x] Peak level dB: 0.5\n'), {'rms': None, 'peak': 0.5})
        self.assertEqual(audiochannels.parse_levels(text.replace('\n', '\r\n')), {'peak': -21.07, 'rms': -24.08})          # FFmpeg no Windows termina as linhas com CRLF
        self.assertEqual(audiochannels.parse_levels('nada\n'), {})
        self.assertEqual(audiochannels.parse_levels(None), {})

    def test_measure_args_only_decode(self):
        args = audiochannels.measure_args('/in/a.wav', 'pan=mono|c0=c0')
        self.assertEqual(args[args.index('-protocol_whitelist') + 1], 'file'); self.assertIn('-format_whitelist', args)
        self.assertEqual(args[args.index('-i') + 1], 'file:/in/a.wav'); self.assertEqual(args[-3:], ['-f', 'null', '-'])
        self.assertIn('pan=mono|c0=c0,astats=', args[args.index('-af') + 1])

    def test_build_args(self):
        args = audiochannels.build_args('/in/a.mp3', '/w/out', 'mp3', 'high', 'pan=mono|c0=c0', info(2, has_cover=True))
        self.assertIn('-nostdin', args); self.assertIn('-n', args); self.assertEqual(args[-1], 'file:/w/out')
        self.assertEqual(args[args.index('-protocol_whitelist') + 1], 'file')
        self.assertEqual(args[args.index('-af') + 1], 'pan=mono|c0=c0')
        self.assertEqual(args[args.index('-c:a') + 1], 'libmp3lame'); self.assertIn('320k', args)
        self.assertIn('0:v:0?', args); self.assertEqual(args[args.index('-c:v') + 1], 'copy')
        self.assertEqual(args[args.index('-map_metadata') + 1], '0')
        self.assertLess(int(args[args.index('-fs') + 1]), engine.MAX_OUTPUT)

    def test_cover_only_mapped_when_present_and_supported(self):
        self.assertNotIn('0:v:0?', audiochannels.build_args('/a', '/b', 'mp3', 'low', 'x', info(2)))
        self.assertNotIn('0:v:0?', audiochannels.build_args('/a', '/b', 'ogg', 'low', 'x', info(2, has_cover=True)))

    def test_notes(self):
        text = ' '.join(audiochannels.notes(info(2), 'mono', 'medium'))
        for word in ('Mono', 'recodificado', 'oposição de fase', 'não é alterado', '-mono'):
            self.assertIn(word, text)
        lossy = ' '.join(audiochannels.notes(info(2, container='mp3', codec='mp3', has_cover=True, chapters=2), 'left', 'low'))
        self.assertIn('com perda', lossy); self.assertIn('Só o canal escolhido', lossy)
        ogg = ' '.join(audiochannels.notes(info(2, container='ogg', codec='vorbis', has_cover=True), 'mono', 'low'))
        self.assertIn('capa', ogg)
        self.assertIn('16 bits', ' '.join(audiochannels.notes(info(2, container='wav', codec='pcm_s16le'), 'mono', 'low')))
        self.assertIn('duplicando', ' '.join(audiochannels.notes(info(1), 'stereo', 'low')))
        self.assertTrue(audiochannels.notes(None, 'stereo', 'low'))


class MeasuredWarningTests(unittest.TestCase):
    """A medição é simulada: o que importa aqui é a decisão (avisar, recusar, reduzir volume)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.source = Path(self.tmp.name) / 'a.flac'; self.source.write_bytes(b'x')
        self.stage = Path(self.tmp.name) / 'out'
        self.ran = []
        patches = [mock.patch.object(mediatools, 'find_tool', return_value='/usr/bin/ffmpeg'), mock.patch.object(mediatools, 'build_info', return_value=None),
                   mock.patch.object(audioconvert, '_run', side_effect=self.fake_run), mock.patch.object(mediatools, 'probe', side_effect=self.fake_probe)]
        for patch in patches:
            patch.start(); self.addCleanup(patch.stop)
        self.channels = 2

    def fake_run(self, exe, args):
        self.ran.append(args)
        self.stage.write_bytes(b'saida')

    def fake_probe(self, path):
        if Path(path) == self.stage:
            return {**info(self.out_channels), 'tags': {}}
        return info(self.channels)

    out_channels = 1

    def measure(self, *results):
        return mock.patch.object(audiochannels, 'measure', side_effect=list(results))

    def test_no_warning_when_levels_agree(self):
        with self.measure({'rms': -20.0, 'peak': -3.0}, {'rms': -23.0, 'peak': -9.0}):       # −3 dB: estéreo não correlacionado
            result = audiochannels.apply(self.source, self.stage, {'chan_mode': 'mono'})
        self.assertEqual(result['notes'], []); self.assertEqual(result['name'], 'mono'); self.assertEqual(result['suffix'], 'flac')

    def test_phase_warning_names_the_loss(self):
        with self.measure({'rms': -20.0, 'peak': -3.0}, {'rms': -27.5, 'peak': -9.0}):
            result = audiochannels.apply(self.source, self.stage, {'chan_mode': 'mono'})
        self.assertEqual(len(result['notes']), 1); self.assertIn('fase', result['notes'][0]); self.assertIn('7,5 dB', result['notes'][0])

    def test_severe_cancellation_is_refused_and_leaves_nothing(self):
        with self.measure({'rms': -20.0, 'peak': -3.0}, {'rms': -40.0, 'peak': -30.0}), self.assertRaises(MediaError) as caught:
            audiochannels.apply(self.source, self.stage, {'chan_mode': 'mono'})
        self.assertIn('Só o canal esquerdo', str(caught.exception)); self.assertFalse(self.stage.exists()); self.assertEqual(self.ran, [])

    def test_total_cancellation_is_refused(self):
        with self.measure({'rms': -20.0, 'peak': -3.0}, {'rms': None, 'peak': None}), self.assertRaises(MediaError) as caught:
            audiochannels.apply(self.source, self.stage, {'chan_mode': 'mono'})
        self.assertIn('mudo', str(caught.exception))

    def test_silent_source_is_not_a_phase_problem(self):
        with self.measure({'rms': None, 'peak': None}, {'rms': None, 'peak': None}):
            self.assertEqual(audiochannels.apply(self.source, self.stage, {'chan_mode': 'mono'})['notes'], [])

    def test_left_and_right_do_not_measure(self):
        with mock.patch.object(audiochannels, 'measure') as measure:
            audiochannels.apply(self.source, self.stage, {'chan_mode': 'right'})
        measure.assert_not_called()

    def test_surround_clipping_reduces_the_volume_and_says_so(self):
        self.channels = 6
        with self.measure({'rms': -10.0, 'peak': 2.0}):
            result = audiochannels.apply(self.source, self.stage, {'chan_mode': 'mono'})
        graph = self.ran[0][self.ran[0].index('-af') + 1]
        self.assertIn('aresample=ochl=mono,volume=-2.30dB', graph)
        self.assertIn('clipping', result['notes'][0]); self.assertIn('2,3 dB', result['notes'][0])

    def test_surround_without_clipping_keeps_the_volume(self):
        self.channels = 6; self.out_channels = 2
        with self.measure({'rms': -10.0, 'peak': -1.0}):
            result = audiochannels.apply(self.source, self.stage, {'chan_mode': 'stereo'})
        self.assertNotIn('volume', self.ran[0][self.ran[0].index('-af') + 1]); self.assertEqual(result['notes'], [])

    def test_absurd_overshoot_is_refused(self):
        self.channels = 6
        with self.measure({'rms': -10.0, 'peak': 40.0}), self.assertRaises(MediaError):
            audiochannels.apply(self.source, self.stage, {'chan_mode': 'mono'})

    def test_wrong_output_channels_are_caught_by_the_verification(self):
        self.out_channels = 2
        with self.measure({'rms': -20.0}, {'rms': -23.0}), self.assertRaises(MediaError) as caught:
            audiochannels.apply(self.source, self.stage, {'chan_mode': 'mono'})
        self.assertIn('esperava 1', str(caught.exception)); self.assertFalse(self.stage.exists())

    def test_huge_pcm_output_is_refused_before_running(self):
        self.out_channels = 2; self.channels = 1
        big = {**info(1), 'duration': 6 * 3600.0, 'sample_rate': 96000}
        with mock.patch.object(mediatools, 'probe', return_value=big), self.assertRaises(MediaError) as caught:
            audiochannels.apply(self.source, self.stage, {'chan_mode': 'stereo'})
        self.assertIn('512 MiB', str(caught.exception)); self.assertEqual(self.ran, [])


@NEEDS_FFMPEG
class EndToEndTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        mediatools.reset_cache()

    def job(self, source, mode, **options):
        return {'target': engine.AUDIO_CHANNELS, 'paths': [str(source)], 'output': str(self.dir), 'chan_mode': mode, **options}

    def names(self):
        return sorted(p.name for p in self.dir.iterdir())

    def rms(self, path):
        return audiochannels.measure(FFMPEG, str(path), '').get('rms')

    def test_stereo_to_mono_in_every_format_keeps_tags(self):
        for kind in audioconvert.FORMATS:
            with self.subTest(kind=kind):
                if kind not in (mediatools.build_info() or {}).get('outputs', []):
                    self.skipTest(f'sem codificador de {kind}')
                codec = {'ogg': ['-c:a', 'libvorbis'], 'opus': ['-c:a', 'libopus'], 'm4a': ['-c:a', 'aac'], 'mp3': ['-c:a', 'libmp3lame']}.get(kind, [])
                source = sine(self.dir / f'musica.{kind}', 'pan=stereo|c0=c0|c1=0.5*c0', *codec, '-metadata', 'title=Canção', '-metadata', 'artist=Ela')
                [out] = engine.convert(self.job(source, 'mono', audio_quality='low'))
                self.assertEqual(Path(out).name, f'musica-mono.{kind}')
                result = mediatools.probe(out)
                self.assertEqual(result['channels'], 1)
                if kind not in ('aiff',):
                    self.assertEqual(result['tags'].get('title'), 'Canção')
                for path in list(self.dir.iterdir()):
                    path.unlink()

    def test_left_and_right_keep_only_their_channel(self):
        source = sine(self.dir / 'lr.flac', 'pan=stereo|c0=c0|c1=0*c0')              # tom só à esquerda
        [left] = engine.convert(self.job(source, 'left')); [right] = engine.convert(self.job(source, 'right'))
        self.assertEqual((Path(left).name, Path(right).name), ('lr-esquerdo.flac', 'lr-direito.flac'))
        self.assertIsNotNone(self.rms(left)); self.assertIsNone(self.rms(right))        # direito é silêncio
        self.assertEqual(mediatools.probe(left)['channels'], 1)

    def test_mono_to_stereo_duplicates(self):
        source = sine(self.dir / 'm.wav', 'anull')
        [out] = engine.convert(self.job(source, 'stereo'))
        info_out = mediatools.probe(out)
        self.assertEqual((Path(out).name, info_out['channels']), ('m-estereo.wav', 2))
        self.assertAlmostEqual(self.rms(out), self.rms(source), delta=0.3)

    def test_surround_to_stereo_and_mono(self):
        source = sine(self.dir / 'sur.flac', 'pan=5.1|c0=c0|c1=c0|c2=c0|c3=c0|c4=c0|c5=c0')
        self.assertEqual(mediatools.probe(source)['channels'], 6)
        self.assertEqual(mediatools.probe(engine.convert(self.job(source, 'stereo'))[0])['channels'], 2)
        self.assertEqual(mediatools.probe(engine.convert(self.job(source, 'mono'))[0])['channels'], 1)

    def test_loud_surround_never_clips(self):
        source = sine(self.dir / 'loud.flac', 'volume=17dB,pan=5.1|c0=c0|c1=c0|c2=c0|c3=c0|c4=c0|c5=c0')
        [out] = engine.convert(self.job(source, 'stereo'))
        peak = audiochannels.measure(FFMPEG, str(out), '').get('peak')
        self.assertLess(peak, 0.0)

    def test_cover_is_kept_for_mp3(self):
        run('-f', 'lavfi', '-i', 'color=c=red:s=32x32:d=1', '-frames:v', '1', str(self.dir / 'c.png'))
        run('-f', 'lavfi', '-i', 'sine=d=1', '-i', str(self.dir / 'c.png'), '-map', '0:a', '-map', '1:v', '-ac', '2', '-c:v', 'mjpeg', '-disposition:v', 'attached_pic', str(self.dir / 'capa.mp3'))
        self.assertTrue(mediatools.probe(self.dir / 'capa.mp3')['has_cover'])
        [out] = engine.convert(self.job(self.dir / 'capa.mp3', 'mono'))
        self.assertTrue(mediatools.probe(out)['has_cover'])

    def test_phase_warning_travels_from_the_worker(self):
        source = sine(self.dir / 'parcial.wav', 'pan=stereo|c0=c0|c1=-0.6*c0')
        [out] = runner.run_job(self.job(source, 'mono'))
        notes = runner.take_notes()
        self.assertTrue(Path(out).is_file()); self.assertEqual(len(notes), 1); self.assertIn('fase', notes[0])
        self.assertEqual(runner.take_notes(), [])                                      # lido uma vez só

    def test_opposite_phase_is_refused_with_no_leftovers(self):
        source = sine(self.dir / 'oposta.wav', 'pan=stereo|c0=c0|c1=-1.0*c0')
        with self.assertRaises(engine.ConversionError) as caught:
            engine.convert(self.job(source, 'mono'))
        self.assertIn('oposição de fase', str(caught.exception)); self.assertEqual(self.names(), ['oposta.wav'])
        [out] = engine.convert(self.job(source, 'left'))                             # a saída sugerida funciona
        self.assertTrue(Path(out).is_file())

    def test_notes_do_not_leak_between_jobs(self):
        warn = sine(self.dir / 'parcial.wav', 'pan=stereo|c0=c0|c1=-0.6*c0'); ok = sine(self.dir / 'ok.wav', 'pan=stereo|c0=c0|c1=c0')
        runner.run_job(self.job(warn, 'mono')); runner.run_job(self.job(ok, 'mono'))
        self.assertEqual(runner.take_notes(), [])

    def test_invalid_requests_fail_cleanly(self):
        mono = sine(self.dir / 'm.wav', 'anull'); bogus = self.dir / 'x.mp3'; bogus.write_text('não é áudio')
        for source, mode in ((mono, 'mono'), (mono, 'left'), (bogus, 'mono'), (mono, 'tudo')):
            with self.subTest(source=source.name, mode=mode), self.assertRaises(engine.ConversionError):
                engine.convert(self.job(source, mode))
        self.assertEqual(self.names(), ['m.wav', 'x.mp3'])

    def test_original_untouched_and_collisions_never_overwrite(self):
        source = sine(self.dir / 'p.flac', 'pan=stereo|c0=c0|c1=0.5*c0'); before = source.read_bytes()
        first = engine.convert(self.job(source, 'mono'))[0]; second = engine.convert(self.job(source, 'mono'))[0]
        self.assertEqual([Path(first).name, Path(second).name], ['p-mono.flac', 'p-mono-2.flac']); self.assertEqual(source.read_bytes(), before)

    def test_loss_report_reads_the_file(self):
        source = sine(self.dir / 'p.flac', 'pan=stereo|c0=c0|c1=0.5*c0')
        text = ' '.join(engine.loss_report([str(source)], engine.AUDIO_CHANNELS, {'chan_mode': 'mono'}))
        self.assertIn('Mono', text); self.assertIn('FLAC', text)
        self.assertIn('Escolha', ' '.join(engine.loss_report([str(source)], engine.AUDIO_CHANNELS, {})))


class RegistrationTests(unittest.TestCase):
    def test_target_options_and_wheel(self):
        import tool_registry
        self.assertIn(engine.AUDIO_CHANNELS, engine.OPERATIONS); self.assertIn(engine.AUDIO_CHANNELS, engine.PDF_LONG_TARGETS)
        self.assertIn('chan_mode', tool_registry.BASE_STR_OPTIONS)
        self.assertEqual(list(tool_registry.AUDIO_GROUPS), ['read', 'convert', 'edit', 'adjust'])
        self.assertEqual([m[0] for m in tool_registry.AUDIO_GROUPS['adjust'][3]], [engine.AUDIO_CHANNELS])

    def test_report_gets_the_worker_warnings_first(self):
        from tray_app import JobController
        from PySide6.QtWidgets import QApplication
        QApplication.instance() or QApplication([])
        controller = JobController(capabilities={'images': (True, 'ok'), 'pdf': (True, 'ok'), 'audio': (True, 'ok')})
        controller.active_job = {'paths': ['/x/a.wav'], 'target': engine.AUDIO_CHANNELS, 'options': {'chan_mode': 'left'}}
        runner.LAST_NOTES[:] = ['Atenção (fase): teste']
        with mock.patch('tray_app.loss_report', return_value=['linha do relatório']), mock.patch.object(controller, 'notify'):
            controller._on_worker_result(True, 'Concluído', ['/x/a-esquerdo.wav'])
        self.assertEqual(controller.last_report, ['Atenção (fase): teste', 'linha do relatório'])
        self.assertEqual(runner.take_notes(), [])


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

    def open_tool(self, channels=2, files=('/x/a.flac',)):
        self.panel.select_category('audio')
        self.panel.files = list(files)
        with mock.patch.object(self.panel.audio_stage, 'show_files'):
            self.panel.select_tool(self.wp.AUDIO_CHANNELS)
        self.panel.audio_stage.infos = {path: info(channels, name=Path(path).name) for path in files}
        self.panel._audiochannels_changed()

    def test_values_follow_the_chips(self):
        self.open_tool()
        self.assertEqual(self.panel._audiochannels_values(), {'chan_mode': 'mono', 'audio_quality': 'medium'})
        self.panel.ch_mode.setCurrentIndex(3); self.panel.ch_quality.setCurrentIndex(2)
        self.assertEqual(self.panel._audiochannels_values(), {'chan_mode': 'right', 'audio_quality': 'high'})

    def test_state_follows_the_file_channels(self):
        self.open_tool(channels=2)
        text, ready = self.panel._audiochannels_state()
        self.assertTrue(ready); self.assertIn('Entrada: Estéreo', text); self.assertIn('fase', text)
        self.panel.ch_mode.setCurrentIndex(1)                                      # estéreo → já é estéreo
        self.assertFalse(self.panel._audiochannels_state()[1]); self.assertFalse(self.panel.run_button.isEnabled())
        self.open_tool(channels=1)
        self.panel.ch_mode.setCurrentIndex(1); self.assertTrue(self.panel._audiochannels_state()[1])
        self.panel.ch_mode.setCurrentIndex(0); self.assertIn('já é mono', self.panel._audiochannels_state()[0])

    def test_many_files_name_the_first_problem(self):
        self.open_tool(files=('/x/a.flac', '/x/b.flac'))
        self.panel.audio_stage.infos['/x/b.flac'] = info(1, name='b.flac')
        text, ready = self.panel._audiochannels_state()
        self.assertFalse(ready); self.assertIn('b.flac', text)

    def test_blocked_without_ffmpeg_or_while_reading(self):
        self.open_tool()
        self.panel.audio_stage.infos = {}
        self.assertFalse(self.panel._audiochannels_state()[1])
        self.panel.controller.capabilities['audio'] = (False, 'FFmpeg não encontrado.')
        self.assertEqual(self.panel._audiochannels_state(), ('FFmpeg não encontrado.', False))

    def test_run_sends_the_options(self):
        self.open_tool()
        started = []
        self.panel.controller.start_job = lambda *args, **kwargs: started.append((args, kwargs))
        self.panel.ch_mode.setCurrentIndex(2)
        self.panel.run_selected()
        self.assertTrue(started, self.panel.status.text())
        self.assertIn("'chan_mode': 'left'", repr(started[0])); self.assertIn(self.wp.AUDIO_CHANNELS, repr(started[0]))


if __name__ == '__main__':
    unittest.main()
