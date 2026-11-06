"""Áudio, item 9: bleep (tom ou silêncio em trechos validados).

Validação, filtro e textos são testados sem FFmpeg; a ponta a ponta usa o FFmpeg real.
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

import audiobleep
import audiochannels
import engine
import mediatools
import runner
from audiobleep import MediaError

FFMPEG = mediatools.find_tool('ffmpeg')
NEEDS_FFMPEG = unittest.skipUnless(FFMPEG and mediatools.find_tool('ffprobe'), 'FFmpeg/ffprobe não instalados')


def info(container='flac', codec='flac', **extra):
    return {'container': container, 'codec': codec, 'channels': 2, 'audio_streams': 1, 'has_video': False, 'has_cover': False, 'chapters': 0,
            'duration': 20.0, 'sample_rate': 44100, 'tags': {}, 'extra_tags': {}, **extra}


def run(*args):
    subprocess.run([FFMPEG, '-hide_banner', '-nostdin', '-v', 'error', '-y', *args], check=True, stdin=subprocess.DEVNULL, capture_output=True, timeout=90)


def loud(path, *extra, seconds=20, channels='stereo'):
    """Seno de 300 Hz alto (RMS ≈ −9 dB): trechos trocados por tom (−12 dBFS, 1 kHz) ou silêncio se distinguem."""
    run('-f', 'lavfi', '-i', f'sine=f=300:d={seconds}:sample_rate=44100,volume=15dB,aformat=channel_layouts={channels}', *extra, str(path))
    return Path(path)


class TimeTests(unittest.TestCase):
    def test_parse_time(self):
        for text, expected in (('12', 12.0), ('12,5', 12.5), ('12.25', 12.25), ('1:02', 62.0), ('1:02,5', 62.5), ('0:01:02.5', 62.5), ('01:00:00', 3600.0), (' 7 ', 7.0), ('0', 0.0)):
            with self.subTest(text=text):
                self.assertEqual(audiobleep.parse_time(text), expected)

    def test_parse_time_refusals(self):
        for text in ('', 'abc', '1:2:3:4', '1::2', '-5', '1:75', '12,5555', '1e3', '٣', '1:02:', ':30', '100:00'):
            with self.subTest(text=text), self.assertRaises(MediaError):
                audiobleep.parse_time(text)


class RangeTests(unittest.TestCase):
    def test_parse_ranges_formats(self):
        self.assertEqual(audiobleep.parse_ranges('0:12,5-0:14; 1:02 – 1:03,5\n 20-21 '), [(12.5, 14.0), (62.0, 63.5), (20.0, 21.0)])
        self.assertEqual(audiobleep.parse_ranges(['1-2', '3 - 4']), [(1.0, 2.0), (3.0, 4.0)])

    def test_parse_ranges_refusals(self):
        for text in ('', '   ', ';;', '5', '5-', '-5', '1-2-3', '2-1', '2-2', 'a-b', '1:75-1:80', "1-2'; rm -rf", 'x' * 9000):
            with self.subTest(text=text[:20]), self.assertRaises(MediaError):
                audiobleep.parse_ranges(text)
        with self.assertRaises(MediaError):
            audiobleep.parse_ranges(['1-2', 3])
        with self.assertRaises(MediaError):
            audiobleep.parse_ranges('\n'.join(f'{i}-{i}.5' for i in range(audiobleep.MAX_RANGES + 1)))
        with self.assertRaises(MediaError):
            audiobleep.parse_ranges('1-2\x00')
        with self.assertRaises(MediaError):
            audiobleep.parse_ranges(None)

    def test_error_names_the_bad_range(self):
        with self.assertRaises(MediaError) as caught:
            audiobleep.parse_ranges('1-2\n3:99-4')
        self.assertIn('3:99-4', str(caught.exception))

    def test_plan_merges_overlaps_and_sorts(self):
        merged, warnings = audiobleep.plan_ranges([(10.0, 12.0), (1.0, 2.0), (11.5, 13.0), (2.0, 3.0)], 20.0)
        self.assertEqual(merged, [(1.0, 3.0), (10.0, 13.0)])
        self.assertIn('2 trecho(s)', warnings[0])
        self.assertEqual(audiobleep.plan_ranges([(1.0, 2.0)], 20.0), ([(1.0, 2.0)], []))

    def test_plan_checks_the_duration(self):
        self.assertEqual(audiobleep.plan_ranges([(19.0, 20.03)], 20.0)[0], [(19.0, 20.0)])          # fim quase no fim é ajustado
        for ranges in ([(20.0, 21.0)], [(25.0, 26.0)], [(19.0, 20.5)], [(1.0, 1.02)], [(0.0, 19.98)], [(0.0, 10.0), (10.0, 20.0)]):
            with self.subTest(ranges=ranges), self.assertRaises(MediaError):
                audiobleep.plan_ranges(ranges, 20.0)
        with self.assertRaises(MediaError):
            audiobleep.plan_ranges([(1.0, 2.0)], 0)

    def test_format_round_trips(self):
        ranges = [(12.5, 14.0), (62.0, 63.5)]
        self.assertEqual(audiobleep.parse_ranges(audiobleep.format_ranges(ranges)), ranges)
        self.assertLessEqual(max(len(line) for line in audiobleep.format_ranges([(3599.999, 3600.0 + 3599)]).split('\n')), 64)


class OptionTests(unittest.TestCase):
    def test_options(self):
        opts = audiobleep.options_from({'bleep_ranges': ['1-2']})
        self.assertEqual((opts['mode'], opts['tone'], opts['quality'], opts['tags'], opts['ranges']), ('tone', 'mid', 'medium', 'keep', [(1.0, 2.0)]))
        self.assertEqual(audiobleep.options_from({'bleep_ranges': '1-2', 'bleep_mode': 'mute', 'bleep_tone': 'high', 'audio_quality': 'high', 'audio_tags': 'drop'})['mode'], 'mute')
        for job in ({}, {'bleep_ranges': '1-2', 'bleep_mode': 'x'}, {'bleep_ranges': '1-2', 'bleep_tone': 'x'}, {'bleep_ranges': '1-2', 'audio_quality': 'x'}, {'bleep_ranges': '1-2', 'audio_tags': 'x'}):
            with self.subTest(job=job), self.assertRaises(MediaError):
                audiobleep.options_from(job)


class FilterAndNotesTests(unittest.TestCase):
    def test_filter_uses_only_numbers_we_computed(self):
        text = audiobleep.audio_filter([(1.5, 2.5), (10.0, 11.25)], 2, 'tone', 'mid')
        self.assertEqual(text, "aeval='if(gt(between(t,1.500,2.500)+between(t,10.000,11.250),0),0.25*sin(2*PI*1000*t),val(0))|if(gt(between(t,1.500,2.500)+between(t,10.000,11.250),0),0.25*sin(2*PI*1000*t),val(1))':c=same")
        self.assertIn('0*sin', audiobleep.audio_filter([(1.0, 2.0)], 1, 'mute', 'low'))
        self.assertIn('500*t', audiobleep.audio_filter([(1.0, 2.0)], 1, 'tone', 'low')); self.assertEqual(audiobleep.audio_filter([(1.0, 2.0)], 6, 'tone', 'high').count('val('), 6)

    def test_args(self):
        opts = audiobleep.options_from({'bleep_ranges': '1-2'})
        args = audiobleep.build_args('/in/a.mp3', '/w/o', 'mp3', info('mp3', 'mp3', has_cover=True), opts, [(1.0, 2.0)])
        for expected in ('-nostdin', '-protocol_whitelist', 'file:/in/a.mp3', '-n', '-af', 'libmp3lame', '0:v:0?'):
            self.assertIn(expected, args)
        drop = audiobleep.build_args('/in/a.mp3', '/w/o', 'mp3', info('mp3', 'mp3', has_cover=True), audiobleep.options_from({'bleep_ranges': '1-2', 'audio_tags': 'drop'}), [(1.0, 2.0)])
        self.assertNotIn('0:v:0?', drop); self.assertEqual(drop[drop.index('-map_metadata') + 1], '-1')

    def test_notes_warn_it_is_not_anonymization(self):
        text = ' '.join(audiobleep.notes(info('mp3', 'mp3', has_cover=True, chapters=1), audiobleep.options_from({'bleep_ranges': '1-2'})))
        for word in ('NÃO é anonimização', 'original continua existindo', 'com perda', 'capítulos', '-bleep', 'tom médio'):
            self.assertIn(word, text)
        self.assertIn('silêncio', ' '.join(audiobleep.notes(None, audiobleep.options_from({'bleep_ranges': '1-2', 'bleep_mode': 'mute'}))))
        self.assertIn('removidas', ' '.join(audiobleep.notes(None, audiobleep.options_from({'bleep_ranges': '1-2', 'audio_tags': 'drop'}))))


@NEEDS_FFMPEG
class EndToEndTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        mediatools.reset_cache()
        self.outputs = (mediatools.build_info() or {}).get('outputs', [])

    def job(self, source, ranges=('5-7',), **options):
        return {'target': engine.AUDIO_BLEEP, 'paths': [str(source)], 'output': str(self.dir), 'bleep_ranges': list(ranges), **options}

    def rms(self, path, start, end):
        return audiochannels.measure(FFMPEG, str(path), f'atrim=start={start}:end={end}')['rms']

    def test_tone_replaces_only_the_ranges_in_every_format(self):
        import audioconvert
        for kind in audioconvert.FORMATS:
            with self.subTest(kind=kind):
                if kind not in self.outputs:
                    self.skipTest(f'sem codificador de {kind}')
                codec = {'ogg': ['-c:a', 'libvorbis'], 'opus': ['-c:a', 'libopus'], 'm4a': ['-c:a', 'aac'], 'mp3': ['-c:a', 'libmp3lame']}.get(kind, [])
                source = loud(self.dir / f'm.{kind}', *codec, '-metadata', 'title=Canção')
                [out] = engine.convert(self.job(source, ('5-7',)))
                self.assertEqual(Path(out).name, f'm-bleep.{kind}')
                self.assertAlmostEqual(mediatools.probe(out)['duration'], 20.0, delta=0.3)
                inside, outside = self.rms(out, 5.2, 6.8), self.rms(out, 10, 12)
                self.assertTrue(-18 < inside < -12, inside)                       # seno de 0,25 de amplitude: ≈ −15 dB
                self.assertTrue(-11 < outside < -7, outside)                      # o resto continua o original (≈ −9 dB RMS)
                if kind != 'aiff':
                    self.assertEqual(mediatools.probe(out)['tags'].get('title'), 'Canção')
                for path in list(self.dir.iterdir()):
                    path.unlink()

    def test_the_tone_is_not_the_original_voice(self):
        """Dentro do trecho não sobra o sinal original: a frequência dominante é a do tom (1 kHz), não a de 300 Hz."""
        import numpy as np
        source = loud(self.dir / 'v.wav')
        [out] = engine.convert(self.job(source, ('5-7',)))
        raw = subprocess.run([FFMPEG, '-nostdin', '-v', 'error', '-ss', '5.2', '-t', '1.5', '-i', out, '-ac', '1', '-f', 's16le', '-'], capture_output=True, check=True).stdout
        samples = np.frombuffer(raw, dtype='<i2').astype(float)
        spectrum = np.abs(np.fft.rfft(samples))
        peak_hz = np.argmax(spectrum) * 44100 / len(samples)
        self.assertAlmostEqual(peak_hz, 1000, delta=20)
        self.assertLess(spectrum[int(300 * len(samples) / 44100)] / spectrum.max(), 0.01)

    def test_mute_mode_and_multiple_ranges(self):
        source = loud(self.dir / 'm.flac')
        [out] = engine.convert(self.job(source, ('2-3', '8-9.5', '15-16'), bleep_mode='mute'))
        for a, b in ((2.1, 2.9), (8.1, 9.4), (15.1, 15.9)):
            self.assertLess(self.rms(out, a, b) if self.rms(out, a, b) is not None else -120, -60)
        self.assertGreater(self.rms(out, 4, 7), -11)

    def test_every_tone_frequency(self):
        import numpy as np
        source = loud(self.dir / 't.wav')
        for key, hz in audiobleep.TONES.items():
            with self.subTest(key=key):
                [out] = engine.convert(self.job(source, ('5-7',), bleep_tone=key))
                raw = subprocess.run([FFMPEG, '-nostdin', '-v', 'error', '-ss', '5.2', '-t', '1.5', '-i', out, '-ac', '1', '-f', 's16le', '-'], capture_output=True, check=True).stdout
                samples = np.frombuffer(raw, dtype='<i2').astype(float)
                self.assertAlmostEqual(np.argmax(np.abs(np.fft.rfft(samples))) * 44100 / len(samples), hz, delta=25)
                Path(out).unlink()

    def test_mono_and_surround_keep_their_channels(self):
        mono = loud(self.dir / 'mono.flac', channels='mono')
        [out] = engine.convert(self.job(mono)); self.assertEqual(mediatools.probe(out)['channels'], 1)
        run('-f', 'lavfi', '-i', 'sine=f=300:d=20:sample_rate=44100,volume=15dB,pan=5.1|c0=c0|c1=c0|c2=c0|c3=c0|c4=c0|c5=c0', str(self.dir / 's.flac'))
        [out] = engine.convert(self.job(self.dir / 's.flac')); self.assertEqual(mediatools.probe(out)['channels'], 6)

    def test_cover_kept_or_removed_and_tags_removed(self):
        if 'mp3' not in self.outputs:
            self.skipTest('sem mp3')
        run('-f', 'lavfi', '-i', 'color=c=red:s=32x32:d=1', '-frames:v', '1', str(self.dir / 'c.png'))
        source = self.dir / 'capa.mp3'
        run('-i', str(loud(self.dir / 'raw.wav')), '-i', str(self.dir / 'c.png'), '-map', '0:a', '-map', '1:v', '-c:a', 'libmp3lame', '-c:v', 'mjpeg', '-disposition:v', 'attached_pic',
            '-metadata', 'title=Segredo', str(source))
        [kept] = engine.convert(self.job(source))
        self.assertTrue(mediatools.probe(kept)['has_cover']); self.assertEqual(mediatools.probe(kept)['tags'].get('title'), 'Segredo')
        [clean] = engine.convert(self.job(source, audio_tags='drop'))
        result = mediatools.probe(clean)
        self.assertFalse(result['has_cover']); self.assertNotIn('title', result['tags'])

    def test_invalid_ranges_are_refused_and_leave_no_file(self):
        source = loud(self.dir / 'r.wav'); before = sorted(p.name for p in self.dir.iterdir())
        for ranges in (('25-26',), ('19-21',), ('0-19.99',), ('5',), ('7-5',), ()):
            with self.subTest(ranges=ranges), self.assertRaises(engine.ConversionError):
                engine.convert(self.job(source, ranges))
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), before)

    def test_check_fails_if_a_range_was_not_replaced(self):
        """A conferência mede o arquivo novo: se o trecho não mudou, nada é salvo."""
        source = loud(self.dir / 'f.wav'); before = sorted(p.name for p in self.dir.iterdir())
        with mock.patch.object(audiobleep, 'audio_filter', return_value='anull'), self.assertRaises(engine.ConversionError) as caught:
            engine.convert(self.job(source, ('5-7',)))
        self.assertIn('conferência falhou', str(caught.exception))
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), before)

    def test_tone_ratio_tells_a_tone_from_other_sounds(self):
        import numpy as np
        t = np.arange(16000) / 16000
        self.assertGreater(audiobleep.tone_ratio(np.sin(2 * np.pi * 1000 * t) * 8000, 1000), 0.99)
        noise = np.random.default_rng(1).normal(0, 3000, 16000)
        self.assertLess(audiobleep.tone_ratio(noise, 1000), 0.2)
        self.assertLess(audiobleep.tone_ratio(np.sin(2 * np.pi * 300 * t) * 8000, 1000), 0.05)
        self.assertEqual(audiobleep.tone_ratio(np.zeros(1600), 1000), 0.0)

    def test_overlaps_warn_and_notes_reach_the_worker(self):
        source = loud(self.dir / 'o.wav')
        done = runner.run_job(self.job(source, ('5-7', '6-8')))
        self.assertEqual(Path(done[0]).name, 'o-bleep.wav')
        notes = ' '.join(runner.take_notes())
        self.assertIn('foram unidos', notes); self.assertIn('não é anonimização garantida', notes)

    def test_original_untouched_and_collisions_never_overwrite(self):
        source = loud(self.dir / 'p.flac'); before = source.read_bytes()
        a = engine.convert(self.job(source))[0]; b = engine.convert(self.job(source))[0]
        self.assertEqual(sorted([Path(a).name, Path(b).name]), ['p-bleep-2.flac', 'p-bleep.flac']); self.assertEqual(source.read_bytes(), before)

    def test_not_audio_is_refused(self):
        (self.dir / 'x.mp3').write_bytes(b'not audio')
        with self.assertRaises(engine.ConversionError):
            engine.convert(self.job(self.dir / 'x.mp3'))

    def test_loss_report(self):
        source = loud(self.dir / 'p.flac')
        self.assertIn('NÃO é anonimização', ' '.join(engine.loss_report([str(source)], engine.AUDIO_BLEEP, {'bleep_ranges': ['1-2']})))
        self.assertIn('Informe', ' '.join(engine.loss_report([str(source)], engine.AUDIO_BLEEP, {})))


class RegistrationTests(unittest.TestCase):
    def test_target_options_and_wheel(self):
        import tool_registry
        self.assertIn(engine.AUDIO_BLEEP, engine.OPERATIONS); self.assertIn(engine.AUDIO_BLEEP, engine.PDF_LONG_TARGETS)
        self.assertTrue({'bleep_mode', 'bleep_tone'} <= tool_registry.BASE_STR_OPTIONS); self.assertIn('bleep_ranges', tool_registry.BASE_LIST_OPTIONS)
        self.assertEqual([m[0] for m in tool_registry.AUDIO_GROUPS['edit'][3]], [engine.AUDIO_TRIM, engine.AUDIO_BLEEP])

    def test_job_controller_accepts_the_list_only_for_this_tool(self):
        from PySide6.QtWidgets import QApplication
        QApplication.instance() or QApplication([])
        from tray_app import JobController
        controller = JobController(capabilities={'images': (True, 'ok'), 'pdf': (True, 'ok'), 'audio': (True, 'ok')})
        notices = []
        controller.notify = lambda *args: notices.append(args)
        with mock.patch.object(JobController, '_start_next'):
            self.assertTrue(controller.start_job(['/x/a.wav'], engine.AUDIO_BLEEP, {'bleep_ranges': ['1-2', '3-4'], 'bleep_mode': 'tone'}), notices)
            self.assertFalse(controller.start_job(['/x/a.wav'], engine.AUDIO_TRIM, {'bleep_ranges': ['1-2']}))
            self.assertFalse(controller.start_job(['/x/a.wav'], engine.AUDIO_BLEEP, {'bleep_ranges': ['1-2'] * 201}))
            self.assertFalse(controller.start_job(['/x/a.wav'], engine.AUDIO_BLEEP, {'bleep_ranges': ['x' * 65]}))


class WaveSelectTests(unittest.TestCase):
    def setUp(self):
        from PySide6.QtWidgets import QApplication
        self.app = QApplication.instance() or QApplication([])
        from audio_wave import WavePanel
        self.panel = WavePanel(); self.addCleanup(self.panel.shutdown)
        self.view = self.panel.view; self.view.resize(500, 130)
        self.view.set_data([[-50, 50]] * 100, 10.0)
        self.panel.set_mode('select', 'Marque trechos.')

    def press(self, kind, fraction):
        from PySide6.QtCore import QEvent, QPointF, Qt
        from PySide6.QtGui import QMouseEvent
        x = 1 + (self.view.width() - 2) * fraction
        event = QMouseEvent(kind, QPointF(x, 20), QPointF(x, 20), Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        {QEvent.Type.MouseButtonPress: self.view.mousePressEvent, QEvent.Type.MouseMove: self.view.mouseMoveEvent, QEvent.Type.MouseButtonRelease: self.view.mouseReleaseEvent}[kind](event)

    def test_dragging_selects_a_range_in_either_direction(self):
        from PySide6.QtCore import QEvent
        seen = []
        self.view.range_changed.connect(lambda a, b: seen.append((a, b)))
        self.press(QEvent.Type.MouseButtonPress, 0.6); self.press(QEvent.Type.MouseMove, 0.3); self.press(QEvent.Type.MouseButtonRelease, 0.3)
        self.assertAlmostEqual(self.view.start, 3.0, delta=0.05); self.assertAlmostEqual(self.view.end, 6.0, delta=0.05)
        self.assertTrue(seen); self.assertLess(seen[-1][0], seen[-1][1])

    def test_marks_are_drawn_and_hover_updates_the_caption(self):
        self.view.marks = [(1.0, 2.0), (5.0, 6.0)]
        self.assertFalse(self.view.grab().isNull())
        self.view.hovered.emit(65.5)
        self.assertIn('1:05,500', self.panel.caption.text())
        self.view.hovered.emit(-1.0)
        self.assertEqual(self.panel.caption.text(), 'Marque trechos.')
        self.panel.set_mode('handles', 'Arraste as alças.')
        self.assertEqual(self.view.mode, 'handles')


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
            self.panel.select_tool(self.wp.AUDIO_BLEEP)
        self.panel.audio_stage.infos = {path: info(name=Path(path).name, **extra) for path in files}
        self.panel.audio_stage.wave.view.set_data([[-10, 10]] * 50, 20.0)
        self.panel._audiobleep_changed()

    def test_empty_list_blocks_with_a_hint(self):
        self.open_tool()
        text, ready = self.panel._audiobleep_state()
        self.assertFalse(ready); self.assertIn('Marque trechos', text); self.assertFalse(self.panel.run_button.isEnabled())

    def test_typing_ranges_enables_and_shows_the_total(self):
        self.open_tool()
        self.panel.bl_list.setPlainText('5-7\n10-11,5')
        text, ready = self.panel._audiobleep_state()
        self.assertTrue(ready); self.assertIn('2 trecho(s)', text); self.assertIn('0:03,500', text); self.assertIn('Não é anonimização', text)
        self.assertEqual(self.panel.audio_stage.wave.view.marks, [(5.0, 7.0), (10.0, 11.5)])

    def test_errors_are_shown_and_block(self):
        self.open_tool()
        for text, word in (('5', 'Trecho inválido'), ('7-5', 'depois do início'), ('25-26', 'depois do fim'), ('1:99-3', 'inválido')):
            self.panel.bl_list.setPlainText(text)
            state = self.panel._audiobleep_state()
            self.assertFalse(state[1], text); self.assertIn(word, state[0])

    def test_selection_button_adds_a_line(self):
        self.open_tool()
        self.assertFalse(self.panel.bl_add.isEnabled())
        self.panel.audio_stage.wave.range_changed.emit(3.0, 4.5)
        self.assertTrue(self.panel.bl_add.isEnabled()); self.assertIn('0:03,000–0:04,500', self.panel.bl_add.text())
        self.panel.bl_add.click()
        self.assertEqual(self.panel.bl_list.toPlainText(), '0:03,000-0:04,500')
        self.assertFalse(self.panel.bl_add.isEnabled())
        self.panel.audio_stage.wave.range_changed.emit(6.0, 7.0); self.panel.bl_add.click()
        self.assertEqual(self.panel._audiobleep_lines(), ['0:03,000-0:04,500', '0:06,000-0:07,000'])
        self.panel.bl_clear.click(); self.assertEqual(self.panel._audiobleep_lines(), [])

    def test_tiny_selection_cannot_be_added(self):
        self.open_tool()
        self.panel.audio_stage.wave.range_changed.emit(3.0, 3.01)
        self.assertFalse(self.panel.bl_add.isEnabled())

    def test_values(self):
        self.open_tool(); self.panel.bl_list.setPlainText('5-7; 9-10')
        self.assertEqual(self.panel._audiobleep_values(), {'bleep_ranges': ['5-7', '9-10'], 'bleep_mode': 'tone', 'bleep_tone': 'mid', 'audio_quality': 'medium', 'audio_tags': 'keep'})
        self.panel.bl_mode.setCurrentIndex(1); self.panel.bl_tone.setCurrentIndex(2); self.panel.bl_tags.setCurrentIndex(1)
        values = self.panel._audiobleep_values()
        self.assertEqual((values['bleep_mode'], values['bleep_tone'], values['audio_tags']), ('mute', 'high', 'drop'))

    def test_one_file_only_ffmpeg_video_and_reading(self):
        self.open_tool(files=('/x/a.flac', '/x/b.flac')); self.assertIn('um arquivo só', self.panel._audiobleep_state()[0])
        self.open_tool(); self.panel.audio_stage.infos = {}; self.panel.bl_list.setPlainText('1-2')
        self.assertEqual(self.panel._audiobleep_state(), ('Lendo o arquivo…', False))
        self.open_tool(has_video=True); self.panel.bl_list.setPlainText('1-2'); self.assertIn('vídeo', self.panel._audiobleep_state()[0])
        self.panel.controller.capabilities['audio'] = (False, 'FFmpeg não encontrado.')
        self.assertEqual(self.panel._audiobleep_state(), ('FFmpeg não encontrado.', False))

    def test_wave_is_in_select_mode_only_for_this_tool(self):
        self.open_tool()
        self.assertFalse(self.panel.audio_stage.wave.isHidden()); self.assertEqual(self.panel.audio_stage.wave.view.mode, 'select')
        with mock.patch.object(self.panel.audio_stage, 'show_files'), mock.patch.object(self.panel.audio_stage.wave, 'show_file'):
            self.panel.select_tool(self.wp.AUDIO_TRIM)
        self.assertEqual(self.panel.audio_stage.wave.view.mode, 'handles')

    def test_run_sends_the_options(self):
        self.open_tool(); self.panel.bl_list.setPlainText('5-7')
        started = []
        self.panel.controller.start_job = lambda *args, **kwargs: started.append((args, kwargs))
        self.panel.run_selected()
        self.assertTrue(started, self.panel.status.text())
        text = repr(started[0])
        for expected in ("'bleep_ranges': ['5-7']", self.wp.AUDIO_BLEEP):
            self.assertIn(expected, text)


if __name__ == '__main__':
    unittest.main()
