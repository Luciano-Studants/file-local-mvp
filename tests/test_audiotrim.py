"""Áudio, item 6: cortar (início e fim, silêncio das pontas) e a onda da interface.

Planejamento, argumentos, análise do silêncio e textos são testados sem FFmpeg; a ponta a ponta usa o FFmpeg real.
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
import audiotrim
import engine
import mediatools
import runner
from audiotrim import MediaError

FFMPEG = mediatools.find_tool('ffmpeg')
NEEDS_FFMPEG = unittest.skipUnless(FFMPEG and mediatools.find_tool('ffprobe'), 'FFmpeg/ffprobe não instalados')


def info(container='flac', codec='flac', **extra):
    return {'container': container, 'codec': codec, 'channels': 2, 'audio_streams': 1, 'has_video': False, 'has_cover': False, 'chapters': 0,
            'duration': 4.5, 'sample_rate': 44100, 'tags': {}, 'extra_tags': {}, **extra}


def run(*args):
    subprocess.run([FFMPEG, '-hide_banner', '-nostdin', '-v', 'error', '-y', *args], check=True, stdin=subprocess.DEVNULL, capture_output=True, timeout=90)


def edge_source(path, *extra):
    """1 s de silêncio + 2 s de tom + 1,5 s de silêncio (4,5 s)."""
    run('-f', 'lavfi', '-i', 'anullsrc=r=44100:cl=mono:d=1', '-f', 'lavfi', '-i', 'sine=f=440:d=2:sample_rate=44100', '-f', 'lavfi', '-i', 'anullsrc=r=44100:cl=mono:d=1.5',
        '-filter_complex', '[0][1][2]concat=n=3:v=0:a=1', *extra, str(path))
    return Path(path)


class OptionTests(unittest.TestCase):
    def test_options(self):
        self.assertEqual(audiotrim.options_from({'trim_start_ms': 500}), ('range', 500, 0, False, 'medium'))
        self.assertEqual(audiotrim.options_from({'trim_mode': 'silence', 'trim_exact': 'yes', 'audio_quality': 'high'}), ('silence', 0, 0, True, 'high'))
        for job in ({'trim_mode': 'x', 'trim_start_ms': 1}, {'trim_exact': 'x', 'trim_start_ms': 1}, {'audio_quality': 'x', 'trim_start_ms': 1}, {'trim_start_ms': -1},
                    {'trim_start_ms': True}, {'trim_start_ms': 1.5}, {'trim_end_ms': 10 ** 12}, {'trim_start_ms': 900, 'trim_end_ms': 900}, {'trim_start_ms': 900, 'trim_end_ms': 100}, {}):
            with self.subTest(job=job), self.assertRaises(MediaError):
                audiotrim.options_from(job)


class SilenceTests(unittest.TestCase):
    TEXT = ('[silencedetect @ 0x55] silence_start: 0\n[silencedetect @ 0x55] silence_end: 1.0005 | silence_duration: 1.0005\n'
            '[silencedetect @ 0x55] silence_start: 3.0\n')

    def test_parse_tolerates_prefix_and_crlf(self):
        expected = [(0.0, 1.0005), (3.0, None)]
        self.assertEqual(audiotrim.parse_silence(self.TEXT), expected)
        self.assertEqual(audiotrim.parse_silence(self.TEXT.replace('\n', '\r\n')), expected)
        self.assertEqual(audiotrim.parse_silence(None), [])
        self.assertEqual(audiotrim.parse_silence('silence_end: 2\n'), [])           # fim sem começo é ignorado

    def test_edges_ignore_the_middle(self):
        self.assertEqual(audiotrim.edges_from([(0.0, 1.0), (2.0, 2.5), (3.0, None)], 4.5), (1.0, 1.5))
        self.assertEqual(audiotrim.edges_from([(2.0, 2.5)], 4.5), (0.0, 0.0))
        self.assertEqual(audiotrim.edges_from([(0.0, 1.0), (3.0, 4.5)], 4.5), (1.0, 1.5))

    def test_all_silence_is_refused(self):
        with self.assertRaises(MediaError):
            audiotrim.edges_from([(0.0, None)], 4.5)


class PlanTests(unittest.TestCase):
    def test_range(self):
        self.assertEqual(audiotrim.plan_cut('range', 1000, 3000, 4.5, None), (1.0, 2.0))
        self.assertEqual(audiotrim.plan_cut('range', 1000, 0, 4.5, None), (1.0, 3.5))
        self.assertEqual(audiotrim.plan_cut('range', 500, 99000, 4.5, None), (0.5, 4.0))

    def test_range_refusals(self):
        for args in ((4450, 0), (4500, 0), (1000, 1050), (0, 4500)):
            with self.subTest(args=args), self.assertRaises(MediaError):
                audiotrim.plan_cut('range', args[0], args[1], 4.5, None)

    def test_silence_keeps_a_margin(self):
        self.assertEqual(audiotrim.plan_cut('silence', 0, 0, 4.5, (1.0, 1.5)), (0.95, 2.1))
        self.assertEqual(audiotrim.plan_cut('silence', 0, 0, 4.5, (1.0, 0.0)), (0.95, 3.55))
        self.assertEqual(audiotrim.plan_cut('silence', 0, 0, 4.5, (0.0, 1.5)), (0.0, 3.05))
        for edges in ((0.1, 0.2), (0.0, 0.0), None):
            with self.subTest(edges=edges), self.assertRaises(MediaError):
                audiotrim.plan_cut('silence', 0, 0, 4.5, edges)


class ArgsAndNotesTests(unittest.TestCase):
    def test_copy_for_lossy_and_encode_for_lossless_or_exact(self):
        mp3 = audiotrim.build_args('/in/a.mp3', '/w/o', 'mp3', 1.0, 2.0, False, 'medium', False)
        self.assertIn('copy', mp3); self.assertIn('-ss', mp3); self.assertIn('file:/in/a.mp3', mp3); self.assertIn('-n', mp3); self.assertEqual(mp3[mp3.index('-f') + 1], 'mp3')
        self.assertEqual(mp3[mp3.index('-t') + 1], '2.000'); self.assertIn('-nostdin', mp3); self.assertIn('-protocol_whitelist', mp3)
        exact = audiotrim.build_args('/in/a.mp3', '/w/o', 'mp3', 1.0, 2.0, True, 'high', False)
        self.assertNotIn('copy', exact); self.assertIn('libmp3lame', exact)
        flac = audiotrim.build_args('/in/a.flac', '/w/o', 'flac', 1.0, 2.0, False, 'low', False)
        self.assertNotIn('copy', flac); self.assertIn('flac', flac)

    def test_ss_comes_after_input_so_the_cut_is_frame_accurate(self):
        args = audiotrim.build_args('/in/a.mp3', '/w/o', 'mp3', 1.0, 2.0, False, 'low', False)
        self.assertGreater(args.index('-ss'), args.index('file:/in/a.mp3'))

    def test_cover_step_copies_cover_only_from_the_original(self):
        args = audiotrim.cover_args('/w/cut', '/in/a.mp3', 'm4a', '/w/o')
        self.assertEqual([a for a in args if a.startswith('file:')], ['file:/w/cut', 'file:/in/a.mp3', 'file:/w/o'])
        self.assertIn('1:v:0', args); self.assertIn('attached_pic', args); self.assertEqual(args[args.index('-f') + 1], 'ipod')

    def test_notes(self):
        text = ' '.join(audiotrim.notes(info('mp3', 'mp3', has_cover=True, chapters=2), 'range', False))
        self.assertIn('sem recodificar', text); self.assertIn('40 ms', text); self.assertIn('capítulos', text); self.assertIn('-cortado', text)
        self.assertIn('recodificado', ' '.join(audiotrim.notes(info('mp3', 'mp3'), 'range', True)))
        self.assertIn('sem perda', ' '.join(audiotrim.notes(info(), 'range', False)))
        self.assertIn('16 bits', ' '.join(audiotrim.notes(info('wav', 'pcm_s16le'), 'range', False)))
        self.assertIn('silêncio do começo e do fim', ' '.join(audiotrim.notes(info(), 'silence', False)))
        self.assertIn('limite do FFmpeg', ' '.join(audiotrim.notes(info('ogg', 'vorbis', has_cover=True), 'range', False)))
        self.assertTrue(audiotrim.notes(None, 'range', False))

    def test_fmt_time(self):
        for text in (' '.join(audiotrim.notes(info(), 'silence', False)),):
            self.assertIn('0,3 s', text); self.assertTrue(text.count('.') >= 3)          # frases terminam em ponto
        with self.assertRaises(MediaError) as caught:
            audiotrim.plan_cut('silence', 0, 0, 4.5, (0.0, 0.0))
        self.assertTrue(str(caught.exception).endswith('fim.'))
        self.assertEqual(audiotrim.fmt_time(65.5), '1:05,500'); self.assertEqual(audiotrim.fmt_time(-3), '0:00,000')


class PeaksTests(unittest.TestCase):
    def test_reduce_peaks_streams_in_odd_chunks(self):
        import numpy as np
        samples = np.concatenate([np.full(2000, 16384, dtype='<i2'), np.zeros(2000, dtype='<i2')]).tobytes()
        chunks = [samples[i:i + 999] for i in range(0, len(samples), 999)]               # blocos ímpares: um amostra pode ser partida ao meio
        peaks = audiotrim.reduce_peaks(iter(chunks), 4000, buckets=4)
        self.assertEqual(len(peaks), 4)
        self.assertEqual(peaks[0], [50, 50]); self.assertEqual(peaks[1], [50, 50]); self.assertEqual(peaks[3], [0, 0])
        self.assertEqual(audiotrim.reduce_peaks(iter([b'']), 10), [])

    def test_wave_refuses_very_long_audio(self):
        with mock.patch.object(mediatools, 'find_tool', return_value='/x/ffmpeg'), self.assertRaises(MediaError):
            audiotrim.waveform('/x/a.wav', audiotrim.MAX_WAVE_SECONDS + 1)


@NEEDS_FFMPEG
class EndToEndTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        mediatools.reset_cache()

    def job(self, source, **options):
        return {'target': engine.AUDIO_TRIM, 'paths': [str(source)], 'output': str(self.dir), **options}

    def duration(self, path):
        return mediatools.probe(path)['duration']

    def test_range_cut_in_every_format(self):
        outputs = (mediatools.build_info() or {}).get('outputs', [])
        for kind in audioconvert.FORMATS:
            with self.subTest(kind=kind):
                if kind not in outputs:
                    self.skipTest(f'sem codificador de {kind}')
                codec = {'ogg': ['-c:a', 'libvorbis'], 'opus': ['-c:a', 'libopus'], 'm4a': ['-c:a', 'aac'], 'mp3': ['-c:a', 'libmp3lame']}.get(kind, [])
                source = edge_source(self.dir / f'm.{kind}', *codec, '-metadata', 'title=Canção')
                [out] = engine.convert(self.job(source, trim_start_ms=1000, trim_end_ms=3000))
                self.assertEqual(Path(out).name, f'm-cortado.{kind}')
                self.assertAlmostEqual(self.duration(out), 2.0, delta=0.12)
                if kind != 'aiff':
                    self.assertEqual(mediatools.probe(out)['tags'].get('title'), 'Canção')
                for path in list(self.dir.iterdir()):
                    path.unlink()

    def test_exact_mode_is_exact_for_lossy(self):
        source = edge_source(self.dir / 'm.mp3', '-c:a', 'libmp3lame')
        [out] = engine.convert(self.job(source, trim_start_ms=1000, trim_end_ms=3000, trim_exact='yes'))
        self.assertAlmostEqual(self.duration(out), 2.0, delta=0.06)

    def test_silence_mode_cuts_only_the_ends(self):
        source = edge_source(self.dir / 'e.wav')
        [out] = engine.convert(self.job(source, trim_mode='silence'))
        self.assertAlmostEqual(self.duration(out), 2.0 + 2 * audiotrim.SILENCE_PAD, delta=0.08)
        self.assertTrue(any('Silêncio removido' in n for n in engine.RUN_NOTES))

    def test_silence_in_the_middle_is_never_touched(self):
        run('-f', 'lavfi', '-i', 'sine=f=440:d=1:sample_rate=44100', '-f', 'lavfi', '-i', 'anullsrc=r=44100:cl=mono:d=1.5', '-f', 'lavfi', '-i', 'sine=f=440:d=1:sample_rate=44100',
            '-filter_complex', '[0][1][2]concat=n=3:v=0:a=1', str(self.dir / 'mid.wav'))
        with self.assertRaises(engine.ConversionError) as caught:
            engine.convert(self.job(self.dir / 'mid.wav', trim_mode='silence'))
        self.assertIn('silêncio', str(caught.exception))

    def test_cover_and_tags_survive_for_mp3_m4a_and_flac(self):
        run('-f', 'lavfi', '-i', 'color=c=red:s=32x32:d=1', '-frames:v', '1', str(self.dir / 'c.png'))
        outputs = (mediatools.build_info() or {}).get('outputs', [])
        for kind, codec in (('mp3', 'libmp3lame'), ('m4a', 'aac'), ('flac', 'flac')):
            with self.subTest(kind=kind):
                if kind not in outputs:
                    self.skipTest(f'sem codificador de {kind}')
                audio = edge_source(self.dir / f'raw.{kind}', '-c:a', codec)
                src = self.dir / f'capa.{kind}'
                run('-i', str(audio), '-i', str(self.dir / 'c.png'), '-map', '0:a', '-map', '1:v', '-c:a', 'copy', '-c:v', 'mjpeg', '-disposition:v', 'attached_pic', '-metadata', 'title=Com capa', str(src))
                self.assertTrue(mediatools.probe(src)['has_cover'])
                [out] = engine.convert(self.job(src, trim_start_ms=1000, trim_end_ms=3000))
                result = mediatools.probe(out)
                self.assertTrue(result['has_cover']); self.assertEqual(result['tags'].get('title'), 'Com capa')
                self.assertAlmostEqual(result['duration'], 2.0, delta=0.12)
                self.assertEqual(sorted(p.name for p in self.dir.iterdir() if '.corte' in p.name), [])          # sem resto do passo intermediário
                for path in list(self.dir.iterdir()):
                    if path.name != 'c.png':
                        path.unlink()

    def test_refusals_leave_no_file(self):
        source = edge_source(self.dir / 'r.wav'); before = sorted(p.name for p in self.dir.iterdir())
        for options in ({'trim_start_ms': 4400}, {'trim_start_ms': 100, 'trim_end_ms': 150}, {'trim_start_ms': 0, 'trim_end_ms': 4500}):
            with self.subTest(options=options), self.assertRaises(engine.ConversionError):
                engine.convert(self.job(source, **options))
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), before)

    def test_not_audio_and_video_are_refused(self):
        (self.dir / 'x.mp3').write_bytes(b'not audio')
        with self.assertRaises(engine.ConversionError):
            engine.convert(self.job(self.dir / 'x.mp3', trim_start_ms=500))

    def test_original_untouched_and_collisions_never_overwrite(self):
        source = edge_source(self.dir / 'p.flac'); before = source.read_bytes()
        a = engine.convert(self.job(source, trim_start_ms=500))[0]; b = engine.convert(self.job(source, trim_start_ms=500))[0]
        self.assertEqual([Path(a).name, Path(b).name], ['p-cortado.flac', 'p-cortado-2.flac']); self.assertEqual(source.read_bytes(), before)

    def test_waveform_and_edges_operation(self):
        source = edge_source(self.dir / 'w.wav')
        result = audiotrim.run_op({'op': 'audio_wave', 'paths': [str(source)]})
        self.assertAlmostEqual(result['duration'], 4.5, delta=0.05)
        self.assertGreater(len(result['peaks']), 100)
        peaks = result['peaks']; quiet = peaks[: len(peaks) // 6]; loud = peaks[len(peaks) * 4 // 10: len(peaks) * 6 // 10]
        self.assertLess(max(p[1] for p in quiet), 5); self.assertGreater(max(p[1] for p in loud), 8)
        self.assertAlmostEqual(result['silence']['lead'], 1.0, delta=0.1); self.assertAlmostEqual(result['silence']['tail'], 1.5, delta=0.1)
        with self.assertRaises(MediaError):
            audiotrim.run_op({'op': 'audio_wave', 'paths': ['a', 'b']})

    def test_worker_runs_the_wave_op_and_returns_notes(self):
        source = edge_source(self.dir / 'w.wav')
        result = runner.run_media_op({'op': 'audio_wave', 'paths': [str(source)]}, timeout=120)
        self.assertTrue(result['peaks'])
        done = runner.run_job({'target': engine.AUDIO_TRIM, 'paths': [str(source)], 'output': str(self.dir), 'trim_mode': 'silence'})
        self.assertEqual(Path(done[0]).name, 'w-cortado.wav')
        self.assertTrue(any('Silêncio removido' in n for n in runner.take_notes()))

    def test_loss_report_reads_the_file(self):
        source = edge_source(self.dir / 'p.flac')
        self.assertIn('FLAC', ' '.join(engine.loss_report([str(source)], engine.AUDIO_TRIM, {'trim_start_ms': 500})))
        self.assertIn('Nada para cortar', ' '.join(engine.loss_report([str(source)], engine.AUDIO_TRIM, {})))


class RegistrationTests(unittest.TestCase):
    def test_target_options_and_wheel(self):
        import tool_registry
        self.assertIn(engine.AUDIO_TRIM, engine.OPERATIONS); self.assertIn(engine.AUDIO_TRIM, engine.PDF_LONG_TARGETS)
        self.assertTrue({'trim_mode', 'trim_exact'} <= tool_registry.BASE_STR_OPTIONS); self.assertTrue({'trim_start_ms', 'trim_end_ms'} <= tool_registry.BASE_INT_OPTIONS)
        self.assertEqual(list(tool_registry.AUDIO_GROUPS), ['read', 'convert', 'edit', 'adjust'])
        self.assertEqual([m[0] for m in tool_registry.AUDIO_GROUPS['edit'][3]], [engine.AUDIO_TRIM, engine.AUDIO_BLEEP])


class WaveWidgetTests(unittest.TestCase):
    def setUp(self):
        from PySide6.QtWidgets import QApplication
        self.app = QApplication.instance() or QApplication([])
        from audio_wave import WavePanel, WaveformView
        self.view = WaveformView(); self.view.resize(500, 130); self.addCleanup(self.view.close)
        self.panel = WavePanel(); self.addCleanup(self.panel.shutdown)
        self.view.set_data([[-50, 50]] * 100, 10.0, (1.0, 2.0))

    def test_set_data_puts_handles_at_the_ends(self):
        self.assertEqual((self.view.start, self.view.end), (0.0, 10.0))
        self.view.set_range(2, 99); self.assertEqual((self.view.start, self.view.end), (2.0, 10.0))
        self.view.set_range(5, 3); self.assertEqual(self.view.end, 5.0)           # fim nunca antes do início

    def test_dragging_moves_the_nearest_handle_and_emits(self):
        from PySide6.QtCore import QPointF, Qt, QEvent
        from PySide6.QtGui import QMouseEvent
        seen = []
        self.view.range_changed.connect(lambda a, b: seen.append((a, b)))
        def send(kind, x):
            event = QMouseEvent(kind, QPointF(x, 20), QPointF(x, 20), Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
            {QEvent.Type.MouseButtonPress: self.view.mousePressEvent, QEvent.Type.MouseMove: self.view.mouseMoveEvent, QEvent.Type.MouseButtonRelease: self.view.mouseReleaseEvent}[kind](event)
        width = self.view.width() - 2
        send(QEvent.Type.MouseButtonPress, 1 + width * 0.3); send(QEvent.Type.MouseMove, 1 + width * 0.4); send(QEvent.Type.MouseButtonRelease, 1 + width * 0.4)
        self.assertAlmostEqual(self.view.start, 4.0, delta=0.05); self.assertEqual(self.view.end, 10.0)
        send(QEvent.Type.MouseButtonPress, 1 + width * 0.95); send(QEvent.Type.MouseMove, 1 + width * 0.1)
        self.assertGreaterEqual(self.view.end, self.view.start + 0.1 - 1e-9)                  # alças não se cruzam
        self.assertTrue(seen)

    def test_view_paints_without_data_and_with_data(self):
        self.assertFalse(self.view.grab().isNull())
        self.view.clear('Sem onda.'); self.assertFalse(self.view.grab().isNull())

    def test_panel_ignores_stale_answers_and_shows_errors(self):
        self.panel.loader = lambda job: {'duration': 3.0, 'peaks': [[-10, 10]] * 5, 'silence': {'lead': 0.5, 'tail': 0.0}}
        self.panel.show_file('/x/a.wav')
        self.assertEqual(self.panel.view.duration, 3.0); self.assertEqual(self.panel.view.silence, (0.5, 0.0))
        self.panel._apply(self.panel._token - 1, {'duration': 99, 'peaks': []}, '')
        self.assertEqual(self.panel.view.duration, 3.0)
        self.panel.loader = lambda job: (_ for _ in ()).throw(RuntimeError('quebrou'))
        self.panel.path = ''; self.panel.show_file('/x/b.wav')
        self.assertEqual(self.panel.view.message, 'quebrou'); self.assertEqual(self.panel.view.peaks, [])


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

    def open_tool(self, files=('/x/a.flac',), **extra):
        self.panel.select_category('audio')
        self.panel.files = list(files)
        with mock.patch.object(self.panel.audio_stage, 'show_files'), mock.patch.object(self.panel.audio_stage.wave, 'show_file'):
            self.panel.select_tool(self.wp.AUDIO_TRIM)
        self.panel.audio_stage.infos = {path: info(name=Path(path).name, **extra) for path in files}
        self.panel.audio_stage.wave.data = {'duration': 4.5, 'silence': {'lead': 1.0, 'tail': 1.5}}
        self.panel.audio_stage.wave.view.set_data([[-10, 10]] * 50, 4.5, (1.0, 1.5))
        self.panel._audiotrim_loaded()

    def test_wave_is_visible_only_in_this_tool(self):
        self.open_tool()
        self.assertFalse(self.panel.audio_stage.wave.isHidden())
        with mock.patch.object(self.panel.audio_stage, 'show_files'):
            self.panel.select_tool(self.wp.AUDIO_INFO)
        self.assertTrue(self.panel.audio_stage.wave.isHidden())

    def test_loaded_wave_sets_the_fields(self):
        self.open_tool()
        self.assertEqual((self.panel.tr_start.value(), self.panel.tr_end.value()), (0.0, 4.5))
        self.assertFalse(self.panel.run_button.isEnabled())                       # nada escolhido ainda
        self.assertIn('não remove nada', self.panel._audiotrim_state()[0])

    def test_fields_and_wave_stay_in_sync(self):
        self.open_tool()
        self.panel.tr_start.setValue(1.0); self.panel.tr_end.setValue(3.0)
        self.assertEqual((self.panel.audio_stage.wave.view.start, self.panel.audio_stage.wave.view.end), (1.0, 3.0))
        self.panel.audio_stage.wave.view.start = 0.5; self.panel.audio_stage.wave.range_changed.emit(0.5, 2.5)
        self.assertEqual((self.panel.tr_start.value(), self.panel.tr_end.value()), (0.5, 2.5))
        self.assertEqual(self.panel._audiotrim_values()['trim_start_ms'], 500); self.assertEqual(self.panel._audiotrim_values()['trim_end_ms'], 2500)
        self.assertTrue(self.panel.run_button.isEnabled()); self.assertIn('Fica 0:02,000 de 0:04,500', self.panel.tr_info.text())

    def test_end_at_duration_means_until_the_end(self):
        self.open_tool()
        self.panel.tr_start.setValue(1.0)
        values = self.panel._audiotrim_values()
        self.assertEqual((values['trim_start_ms'], values['trim_end_ms']), (1000, 0))

    def test_silence_mode_disables_the_range_and_reports_the_edges(self):
        self.open_tool()
        self.panel.tr_mode.setCurrentIndex(1)
        self.assertFalse(self.panel.tr_start.isEnabled()); self.assertTrue(self.panel.run_button.isEnabled())
        self.assertIn('Silêncio medido: 0:01,000 no começo e 0:01,500 no fim', self.panel.tr_info.text())
        self.assertEqual(self.panel._audiotrim_values()['trim_mode'], 'silence'); self.assertNotIn('trim_start_ms', self.panel._audiotrim_values())
        self.panel.audio_stage.wave.data = {'duration': 4.5, 'silence': {'lead': 0.0, 'tail': 0.1}}
        self.panel._audiotrim_changed()
        self.assertFalse(self.panel.run_button.isEnabled()); self.assertIn('Não há silêncio', self.panel.tr_info.text())

    def test_precision_text_follows_the_format(self):
        self.open_tool(container='mp3', codec='mp3'); self.panel.tr_start.setValue(1.0)
        self.assertIn('Sem recodificar', self.panel._audiotrim_state()[0])
        self.panel.tr_exact.setCurrentIndex(1)
        self.assertIn('recodifica em MP3', self.panel._audiotrim_state()[0])
        self.open_tool(); self.panel.tr_start.setValue(1.0)
        self.assertIn('exato e sem perda', self.panel._audiotrim_state()[0])

    def test_many_files_only_in_silence_mode(self):
        self.open_tool(files=('/x/a.flac', '/x/b.flac'))
        self.assertFalse(self.panel._audiotrim_state()[1]); self.assertIn('um arquivo só', self.panel._audiotrim_state()[0])
        self.panel.tr_mode.setCurrentIndex(1)
        self.assertTrue(self.panel._audiotrim_state()[1])

    def test_blocked_without_ffmpeg_video_or_while_reading(self):
        self.open_tool(); self.panel.audio_stage.infos = {}
        self.assertFalse(self.panel._audiotrim_state()[1])
        self.open_tool(has_video=True); self.panel.tr_start.setValue(1.0)
        self.assertFalse(self.panel._audiotrim_state()[1]); self.assertIn('vídeo', self.panel._audiotrim_state()[0])
        self.panel.controller.capabilities['audio'] = (False, 'FFmpeg não encontrado.')
        self.assertEqual(self.panel._audiotrim_state(), ('FFmpeg não encontrado.', False))

    def test_run_sends_the_options(self):
        self.open_tool()
        started = []
        self.panel.controller.start_job = lambda *args, **kwargs: started.append((args, kwargs))
        self.panel.tr_start.setValue(1.0); self.panel.tr_end.setValue(3.0); self.panel.tr_exact.setCurrentIndex(1)
        self.panel.run_selected()
        self.assertTrue(started, self.panel.status.text())
        text = repr(started[0])
        for expected in ("'trim_start_ms': 1000", "'trim_end_ms': 3000", "'trim_exact': 'yes'", self.wp.AUDIO_TRIM):
            self.assertIn(expected, text)


if __name__ == '__main__':
    unittest.main()
