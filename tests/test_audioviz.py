"""Áudio, item 10: visualizador em MP4 (onda ou espectro, MPEG-4 + AAC).

Opções, filtro e textos são testados sem FFmpeg; a ponta a ponta usa o FFmpeg real.
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

import audioviz
import engine
import mediatools
import runner
import tool_registry
from audioviz import MediaError

FFMPEG = mediatools.find_tool('ffmpeg')
NEEDS_FFMPEG = unittest.skipUnless(FFMPEG and mediatools.find_tool('ffprobe'), 'FFmpeg/ffprobe não instalados')
HAS_VIDEO_ENCODER = bool(FFMPEG) and audioviz.VIDEO_ENCODER in ((mediatools.build_info() or {}).get('video_encoders') or [])
NEEDS_ENCODER = unittest.skipUnless(HAS_VIDEO_ENCODER, 'FFmpeg sem o codificador mpeg4')


def info(**extra):
    return {'container': 'flac', 'codec': 'flac', 'channels': 2, 'audio_streams': 1, 'has_video': False, 'has_cover': False, 'chapters': 0,
            'duration': 20.0, 'sample_rate': 44100, 'tags': {}, 'extra_tags': {}, **extra}


def run(*args):
    subprocess.run([FFMPEG, '-hide_banner', '-nostdin', '-v', 'error', '-y', *args], check=True, stdin=subprocess.DEVNULL, capture_output=True, timeout=90)


class OptionTests(unittest.TestCase):
    def test_defaults(self):
        self.assertEqual(audioviz.options_from({}), {'style': 'waves', 'size': '720p', 'tags': 'keep'})

    def test_values(self):
        self.assertEqual(audioviz.options_from({'viz_style': 'spectrum', 'viz_size': '360p', 'audio_tags': 'drop'}), {'style': 'spectrum', 'size': '360p', 'tags': 'drop'})

    def test_refusals(self):
        for key, value in (('viz_style', 'bars'), ('viz_size', '4k'), ('viz_size', '1280x720'), ('audio_tags', 'x'), ('viz_style', "waves';rm")):
            with self.subTest(key=key, value=value), self.assertRaises(MediaError):
                audioviz.options_from({key: value})


class PlanTests(unittest.TestCase):
    def test_duration_limits(self):
        audioviz.plan(info(duration=1800.0))
        for duration in (0, -1, 1800.5, 7200):
            with self.subTest(duration=duration), self.assertRaises(MediaError):
                audioviz.plan(info(duration=duration))

    def test_long_audio_message_suggests_trim(self):
        with self.assertRaises(MediaError) as caught:
            audioviz.plan(info(duration=3600.0))
        self.assertIn('Cortar', str(caught.exception)); self.assertIn('30 minutos', str(caught.exception))


class ArgsTests(unittest.TestCase):
    def args(self, **over):
        return audioviz.build_args('/x/a.flac', '/x/out.mp4', audioviz.options_from(over), info())

    def test_safety_flags(self):
        args = self.args()
        for flag in ('-nostdin', '-protocol_whitelist', '-format_whitelist', '-n', '-fs'):
            self.assertIn(flag, args)
        self.assertEqual(args.count('-protocol_whitelist'), 2); self.assertEqual(args.count('file:/x/a.flac'), 2)
        self.assertEqual(args[args.index('-protocol_whitelist') + 1], 'file')
        self.assertEqual(args[-1], 'file:/x/out.mp4')

    def test_codecs_and_container(self):
        args = self.args()
        self.assertEqual(args[args.index('-c:v') + 1], 'mpeg4'); self.assertEqual(args[args.index('-c:a') + 1], 'aac')
        self.assertEqual(args[args.index('-f') + 1], 'mp4')
        self.assertNotIn('libx264', args)

    def test_filters_use_only_app_numbers(self):
        waves = self.args()[self.args().index('-filter_complex') + 1]
        self.assertIn('showwaves=s=1280x720', waves); self.assertIn('format=yuv420p', waves)
        spectrum = self.args(viz_style='spectrum', viz_size='360p')[self.args(viz_style='spectrum', viz_size='360p').index('-filter_complex') + 1]
        self.assertIn('showspectrum=s=640x360', spectrum); self.assertIn(',fps=25,', spectrum); self.assertNotIn('asplit', spectrum)

    def test_bitrate_follows_size(self):
        self.assertEqual(self.args()[self.args().index('-b:v') + 1], '1500k')
        self.assertEqual(self.args(viz_size='360p')[self.args(viz_size='360p').index('-b:v') + 1], '600k')

    def test_tags_and_surround(self):
        keep, drop = self.args(), self.args(audio_tags='drop')
        self.assertEqual(keep[keep.index('-map_metadata') + 1], '0'); self.assertEqual(drop[drop.index('-map_metadata') + 1], '-1')
        self.assertNotIn('-ac', keep)
        args = audioviz.build_args('/x/a', '/x/o', audioviz.options_from({}), info(channels=6))
        self.assertEqual(args[args.index('-ac') + 1], '2')

    def test_chapters_and_extra_streams_not_copied(self):
        args = self.args()
        self.assertEqual(args[args.index('-map_chapters') + 1], '-1')
        self.assertIn('-sn', args)


class NotesTests(unittest.TestCase):
    def test_notes_are_honest_about_the_codec(self):
        text = ' '.join(audioviz.notes(info(), audioviz.options_from({})))
        self.assertIn('MPEG-4 Parte 2', text); self.assertIn('H.264', text); self.assertIn('-visualizador', text)

    def test_notes_mention_what_is_dropped(self):
        text = ' '.join(audioviz.notes(info(has_video=True, chapters=2, has_cover=True, channels=6, audio_streams=2), audioviz.options_from({'audio_tags': 'drop'})))
        for word in ('vídeo original', 'capítulos', 'capa', 'estéreo', 'primeira', 'removidas'):
            self.assertIn(word, text)

    def test_engine_loss_report_runs_without_a_file(self):
        notes = engine.loss_report([], engine.AUDIO_VIZ, {'viz_style': 'spectrum'})
        self.assertTrue(any('espectro' in n for n in notes))
        self.assertEqual(engine.loss_report([], engine.AUDIO_VIZ, {'viz_style': 'bad'}), ['Estilo inválido. Escolha onda ou espectro.'])


class RegistrationTests(unittest.TestCase):
    def test_registered(self):
        self.assertIn(engine.AUDIO_VIZ, engine.OPERATIONS); self.assertIn(engine.AUDIO_VIZ, engine.PDF_LONG_TARGETS); self.assertIn(engine.AUDIO_VIZ, engine.AUDIO_TARGETS)
        self.assertEqual(engine.TOOL_SUFFIX[engine.AUDIO_VIZ], 'visualizador')
        self.assertTrue({'viz_style', 'viz_size'} <= tool_registry.BASE_STR_OPTIONS)
        self.assertEqual([m[0] for m in tool_registry.AUDIO_GROUPS['convert'][3]], [engine.AUDIO_CONVERT, engine.AUDIO_COMPRESS, engine.AUDIO_VIZ])

    def test_encoder_listing_parser(self):
        text = ' V....D libx264              libx264 H.264\n V.S... mpeg4                MPEG-4 part 2\n A....D aac                  AAC\n ------\n V..... = Video\n'
        self.assertEqual(mediatools.parse_video_encoders(text), {'libx264', 'mpeg4'})
        self.assertNotIn('mpeg4', mediatools.parse_encoders(text))

    def test_probe_reports_the_video_stream(self):
        data = {'streams': [{'codec_type': 'audio', 'codec_name': 'aac', 'channels': 2}, {'codec_type': 'video', 'codec_name': 'mpeg4', 'width': 1280, 'height': 720}],
                'format': {'duration': '3'}}
        out = mediatools.parse_probe(data)
        self.assertEqual((out['video_codec'], out['video_width'], out['video_height']), ('mpeg4', 1280, 720))
        audio_only = mediatools.parse_probe({'streams': [{'codec_type': 'audio', 'codec_name': 'flac'}], 'format': {'duration': '3'}})
        self.assertEqual((audio_only['video_codec'], audio_only['video_width']), ('', 0))

    def test_job_controller_accepts_the_options(self):
        from PySide6.QtWidgets import QApplication
        QApplication.instance() or QApplication([])
        from tray_app import JobController
        controller = JobController(capabilities={'images': (True, 'ok'), 'pdf': (True, 'ok'), 'audio': (True, 'ok')})
        with mock.patch.object(JobController, '_start_next'):
            self.assertTrue(controller.start_job(['/x/a.wav'], engine.AUDIO_VIZ, {'viz_style': 'spectrum', 'viz_size': '360p'}))


@NEEDS_FFMPEG
@NEEDS_ENCODER
class EndToEndTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(); cls.dir = Path(cls.tmp.name)
        cls.src = cls.dir / 'musica.flac'
        run('-f', 'lavfi', '-i', 'sine=f=440:d=6:sample_rate=44100', '-metadata', 'title=Canção', '-metadata', 'artist=Banda', str(cls.src))
        cls.sil = cls.dir / 'silencio.wav'
        run('-f', 'lavfi', '-i', 'anullsrc=r=44100:cl=stereo', '-t', '3', str(cls.sil))
        cls.long = cls.dir / 'longo.wav'
        run('-f', 'lavfi', '-i', 'anullsrc=r=8000:cl=mono', '-t', '1801', str(cls.long))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def make(self, source, **job):
        stage = self.dir / f'stage-{len(list(self.dir.iterdir()))}.mp4'
        done = audioviz.apply(source, stage, job)
        return stage, done

    def test_waves_720p(self):
        stage, done = self.make(self.src)
        out = mediatools.probe(stage)
        self.assertEqual((out['video_codec'], out['video_width'], out['video_height'], out['codec']), ('mpeg4', 1280, 720, 'aac'))
        self.assertAlmostEqual(out['duration'], 6.0, delta=0.3)
        self.assertEqual(done['suffix'], 'mp4'); self.assertEqual(done['name'], 'visualizador')
        self.assertEqual(out['tags'].get('title'), 'Canção')

    def test_spectrum_360p_and_tags_removed(self):
        stage, _ = self.make(self.src, viz_style='spectrum', viz_size='360p', audio_tags='drop')
        out = mediatools.probe(stage)
        self.assertEqual((out['video_width'], out['video_height']), (640, 360)); self.assertEqual(out['tags'], {})

    def test_video_has_content_for_sound_and_decodes(self):
        stage, _ = self.make(self.src)
        frame = self.dir / 'frame.pgm'
        run('-ss', '3', '-i', str(stage), '-frames:v', '1', '-vf', 'format=gray', str(frame))
        data = frame.read_bytes()
        self.assertGreater(sum(1 for b in data[20:] if b > 40), 500)          # há traço desenhado, não é um quadro preto

    def test_silent_audio_works(self):
        stage, _ = self.make(self.sil, viz_style='spectrum', viz_size='360p')
        self.assertTrue(stage.is_file())

    def test_too_long_is_refused_without_a_file(self):
        stage = self.dir / 'never.mp4'
        with self.assertRaises(MediaError) as caught:
            audioviz.apply(self.long, stage, {})
        self.assertIn('30 minutos', str(caught.exception)); self.assertFalse(stage.exists())

    def test_existing_stage_is_refused(self):
        stage = self.dir / 'exists.mp4'; stage.write_bytes(b'x')
        with self.assertRaises(MediaError):
            audioviz.apply(self.src, stage, {})
        self.assertEqual(stage.read_bytes(), b'x')

    def test_failed_verification_leaves_nothing(self):
        stage = self.dir / 'bad.mp4'
        with mock.patch.object(audioviz, '_decode_check', side_effect=MediaError('A conferência falhou: x')):
            with self.assertRaises(MediaError):
                audioviz.apply(self.src, stage, {})
        self.assertFalse(stage.exists())

    def test_decode_check_rejects_a_truncated_file(self):
        stage, _ = self.make(self.src)
        broken = self.dir / 'broken.mp4'
        broken.write_bytes(stage.read_bytes()[: stage.stat().st_size // 2])
        with self.assertRaises(MediaError):
            audioviz._decode_check(FFMPEG, str(broken))

    def test_engine_publishes_next_to_the_original_and_keeps_it(self):
        work = self.dir / 'pub'; work.mkdir()
        original = work / 'faixa.flac'; original.write_bytes(self.src.read_bytes())
        before = original.read_bytes()
        outputs = runner.run_job({'paths': [str(original)], 'target': engine.AUDIO_VIZ, 'viz_size': '360p'})
        names = sorted(p.name for p in work.iterdir())
        self.assertIn('faixa-visualizador.mp4', names); self.assertEqual(original.read_bytes(), before)
        self.assertTrue(outputs)

    def test_second_run_gets_a_new_name(self):
        work = self.dir / 'pub2'; work.mkdir()
        original = work / 'faixa.flac'; original.write_bytes(self.src.read_bytes())
        for _ in range(2):
            runner.run_job({'paths': [str(original)], 'target': engine.AUDIO_VIZ, 'viz_size': '360p'})
        self.assertEqual(sorted(p.name for p in work.iterdir() if p.suffix == '.mp4'), ['faixa-visualizador-2.mp4', 'faixa-visualizador.mp4'])


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
        with mock.patch.object(self.panel.audio_stage, 'show_files'):
            self.panel.select_tool(self.wp.AUDIO_VIZ)
        self.panel.audio_stage.infos = {path: info(**extra) for path in files}
        self.panel._audioviz_changed()

    def test_ready_with_estimate(self):
        self.open_tool()
        text, ready = self.panel._audioviz_state()
        self.assertTrue(ready); self.assertIn('1280×720', text); self.assertIn('MPEG-4', text)

    def test_too_long_blocks(self):
        self.open_tool(duration=4000.0)
        text, ready = self.panel._audioviz_state()
        self.assertFalse(ready); self.assertIn('30 minutos', text)

    def test_values(self):
        self.open_tool()
        self.panel.vz_style.setCurrentIndex(1); self.panel.vz_size.setCurrentIndex(1); self.panel.vz_tags.setCurrentIndex(1)
        self.assertEqual(self.panel._audioviz_values(), {'viz_style': 'spectrum', 'viz_size': '360p', 'audio_tags': 'drop'})

    def test_no_file_blocks(self):
        self.open_tool(files=())
        self.assertFalse(self.panel._audioviz_state()[1])


if __name__ == '__main__':
    unittest.main()
