"""Áudio, item 8: comprimir (bitrate-alvo e tamanho-alvo como melhor esforço).

Planejamento, argumentos e textos são testados sem FFmpeg; a ponta a ponta usa o FFmpeg real.
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

import audiocompress
import audioconvert
import engine
import mediatools
import runner
from audiocompress import MediaError

FFMPEG = mediatools.find_tool('ffmpeg')
NEEDS_FFMPEG = unittest.skipUnless(FFMPEG and mediatools.find_tool('ffprobe'), 'FFmpeg/ffprobe não instalados')


def opts(**extra):
    return audiocompress.options_from(extra)


def info(**extra):
    return {'container': 'wav', 'codec': 'pcm_s16le', 'channels': 2, 'audio_streams': 1, 'has_video': False, 'has_cover': False, 'chapters': 0,
            'duration': 10.0, 'sample_rate': 44100, 'bit_rate': 1411200, 'stream_bit_rate': 1411200, **extra}


def run(*args):
    subprocess.run([FFMPEG, '-hide_banner', '-nostdin', '-v', 'error', '-y', *args], check=True, stdin=subprocess.DEVNULL, capture_output=True, timeout=90)


def music(path, *extra, seconds=10):
    """Ruído rosa estéreo: não comprime à toa."""
    run('-f', 'lavfi', '-i', f'anoisesrc=d={seconds}:c=pink:r=44100:a=0.3,aformat=channel_layouts=stereo', *extra, str(path))
    return Path(path)


class OptionTests(unittest.TestCase):
    def test_defaults_and_values(self):
        self.assertEqual(opts(), {'mode': 'bitrate', 'format': 'mp3', 'kbps': 128, 'size_kb': 0, 'mono': False, 'tags': 'keep'})
        self.assertEqual(opts(comp_mode='size', comp_size_kb=500, audio_format='opus', comp_mono='yes', audio_tags='drop'),
                         {'mode': 'size', 'format': 'opus', 'kbps': 128, 'size_kb': 500, 'mono': True, 'tags': 'drop'})

    def test_refusals(self):
        for job in ({'comp_mode': 'x'}, {'audio_format': 'flac'}, {'audio_format': 'wav'}, {'comp_mono': 'talvez'}, {'audio_tags': 'x'}, {'comp_kbps': 8}, {'comp_kbps': 999},
                    {'comp_kbps': True}, {'comp_kbps': 64.5}, {'audio_format': 'opus', 'comp_kbps': 300}, {'comp_mode': 'size', 'comp_size_kb': 1}, {'comp_mode': 'size', 'comp_size_kb': 10 ** 9},
                    {'comp_mode': 'size'}, {'comp_mode': 'size', 'comp_size_kb': '5'}):
            with self.subTest(job=job), self.assertRaises(MediaError):
                opts(**job)

    def test_opus_accepts_very_low_bitrates(self):
        self.assertEqual(opts(audio_format='opus', comp_kbps=16)['kbps'], 16)
        with self.assertRaises(MediaError):
            opts(audio_format='mp3', comp_kbps=16)


class PlanTests(unittest.TestCase):
    def test_size_to_bitrate(self):
        self.assertAlmostEqual(audiocompress.kbps_for_size(100, 10.0), (102400 - 16384) * 8 / 10 / 1000 * 0.98, places=3)
        with self.assertRaises(MediaError):
            audiocompress.kbps_for_size(100, 0)

    def test_bitrate_mode_plan_and_already_small_source(self):
        self.assertEqual(audiocompress.plan_bitrate(opts(comp_kbps=64), info(), 1_764_000), (64, None))
        mp3 = info(container='mp3', codec='mp3', stream_bit_rate=128000)
        with self.assertRaises(MediaError) as caught:
            audiocompress.plan_bitrate(opts(comp_kbps=128), mp3, 160_000)
        self.assertIn('não reduziria', str(caught.exception))
        self.assertEqual(audiocompress.plan_bitrate(opts(comp_kbps=96), mp3, 160_000)[0], 96)

    def test_size_mode_plan(self):
        kbps, note = audiocompress.plan_bitrate(opts(comp_mode='size', comp_size_kb=100), info(), 1_764_000)
        self.assertEqual((kbps, note), (67, None))

    def test_size_mode_refusals_and_clamping(self):
        with self.assertRaises(MediaError) as caught:                              # 20 KB em 10 s: ~3 kbps, abaixo do mínimo do MP3
            audiocompress.plan_bitrate(opts(comp_mode='size', comp_size_kb=20), info(), 1_764_000)
        self.assertIn('Opus', str(caught.exception)); self.assertIn('mínimo de 32 kbps', str(caught.exception))
        with self.assertRaises(MediaError) as caught:                              # alvo maior que o próprio arquivo
            audiocompress.plan_bitrate(opts(comp_mode='size', comp_size_kb=5000), info(), 1_764_000)
        self.assertIn('já tem', str(caught.exception))
        kbps, note = audiocompress.plan_bitrate(opts(comp_mode='size', comp_size_kb=1700, audio_format='opus'), info(), 20_000_000)
        self.assertEqual(kbps, 256); self.assertIn('menor que o alvo', note)
        with self.assertRaises(MediaError):
            audiocompress.plan_bitrate(opts(comp_mode='size', comp_size_kb=100), info(duration=0), 1_764_000)

    def test_channels(self):
        self.assertEqual(audiocompress.out_channels(opts(), info(channels=6)), 2)
        self.assertEqual(audiocompress.out_channels(opts(audio_format='opus'), info(channels=6)), 6)
        self.assertEqual(audiocompress.out_channels(opts(comp_mono='yes'), info(channels=6)), 1)


class ArgsAndNotesTests(unittest.TestCase):
    def test_args(self):
        args = audiocompress.build_args('/in/a.wav', '/w/o', opts(comp_kbps=64, audio_format='opus'), 64, info())
        for expected in ('-nostdin', '-protocol_whitelist', 'file:/in/a.wav', '-vn', 'libopus', '64k', '-n', 'file:/w/o'):
            self.assertIn(expected, args)
        self.assertNotIn('-ac', args); self.assertEqual(args[args.index('-f') + 1], 'opus')
        self.assertEqual(args[args.index('-map_chapters') + 1], '-1')

    def test_mono_drop_tags_and_surround_downmix(self):
        mono = audiocompress.build_args('/in/a.wav', '/w/o', opts(comp_mono='yes', audio_tags='drop'), 96, info())
        self.assertEqual(mono[mono.index('-ac') + 1], '1'); self.assertEqual(mono[mono.index('-map_metadata') + 1], '-1')
        surround = audiocompress.build_args('/in/a.wav', '/w/o', opts(), 96, info(channels=6))
        self.assertEqual(surround[surround.index('-ac') + 1], '2')
        self.assertIn('-id3v2_version', surround)

    def test_notes(self):
        text = ' '.join(audiocompress.notes(info(has_cover=True, chapters=1), opts(comp_mono='yes')))
        for word in ('128 kbps', 'mono', 'capa', 'capítulos', '-comprimido', 'menor que o original'):
            self.assertIn(word, text)
        self.assertIn('melhor esforço', ' '.join(audiocompress.notes(None, opts(comp_mode='size', comp_size_kb=500))))
        self.assertIn('já está neste formato', ' '.join(audiocompress.notes(info(codec='mp3'), opts())))


@NEEDS_FFMPEG
class EndToEndTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        mediatools.reset_cache()
        self.outputs = (mediatools.build_info() or {}).get('outputs', [])

    def job(self, source, **options):
        return {'target': engine.AUDIO_COMPRESS, 'paths': [str(source)], 'output': str(self.dir), **options}

    def test_each_format_shrinks_and_keeps_tags(self):
        source = music(self.dir / 'm.wav')
        for fmt in audiocompress.FORMATS:
            with self.subTest(fmt=fmt):
                if fmt not in self.outputs:
                    self.skipTest(f'sem codificador de {fmt}')
                tagged = self.dir / f't-{fmt}.flac'
                run('-i', str(source), '-metadata', 'title=Canção', str(tagged))
                [out] = engine.convert(self.job(tagged, audio_format=fmt, comp_kbps=64))
                self.assertEqual(Path(out).name, f't-{fmt}-comprimido.{audioconvert.FORMATS[fmt]["suffix"]}')
                self.assertLess(Path(out).stat().st_size, tagged.stat().st_size / 3)
                result = mediatools.probe(out)
                self.assertEqual(result['tags'].get('title'), 'Canção'); self.assertEqual(result['channels'], 2)
                self.assertAlmostEqual(result['duration'], 10.0, delta=0.3)
                self.assertTrue(any('Tamanho: de' in n for n in engine.RUN_NOTES))

    def test_bitrate_is_close_to_the_target(self):
        if 'mp3' not in self.outputs:
            self.skipTest('sem mp3')
        source = music(self.dir / 'm.wav')
        [out] = engine.convert(self.job(source, comp_kbps=64))
        self.assertAlmostEqual(Path(out).stat().st_size * 8 / 10 / 1000, 64, delta=6)

    def test_mono_halves_the_channels_and_cover_is_dropped(self):
        if 'mp3' not in self.outputs:
            self.skipTest('sem mp3')
        run('-f', 'lavfi', '-i', 'color=c=red:s=64x64:d=1', '-frames:v', '1', str(self.dir / 'c.png'))
        source = self.dir / 'capa.flac'
        run('-i', str(music(self.dir / 'raw.wav')), '-i', str(self.dir / 'c.png'), '-map', '0:a', '-map', '1:v', '-c:a', 'flac', '-c:v', 'mjpeg', '-disposition:v', 'attached_pic', str(source))
        self.assertTrue(mediatools.probe(source)['has_cover'])
        [out] = engine.convert(self.job(source, comp_mono='yes', comp_kbps=48))
        result = mediatools.probe(out)
        self.assertEqual(result['channels'], 1); self.assertFalse(result['has_cover'])

    def test_drop_tags(self):
        if 'mp3' not in self.outputs:
            self.skipTest('sem mp3')
        tagged = self.dir / 't.flac'
        run('-i', str(music(self.dir / 'raw.wav')), '-metadata', 'title=Segredo', str(tagged))
        [out] = engine.convert(self.job(tagged, audio_tags='drop', comp_kbps=64))
        self.assertNotIn('title', mediatools.probe(out)['tags'])

    def test_size_mode_fits_the_target(self):
        source = music(self.dir / 'm.wav')
        for fmt in audiocompress.FORMATS:
            with self.subTest(fmt=fmt):
                if fmt not in self.outputs:
                    self.skipTest(f'sem codificador de {fmt}')
                [out] = engine.convert(self.job(source, comp_mode='size', comp_size_kb=120, audio_format=fmt))
                self.assertLessEqual(Path(out).stat().st_size, 120 * 1024 * 1.05)
                self.assertGreater(Path(out).stat().st_size, 60 * 1024)                 # usou boa parte do orçamento
                for path in list(self.dir.glob('m-comprimido*')):
                    path.unlink()

    def test_size_mode_retry_and_best_effort_warning(self):
        """Simula uma gravação que passa do alvo: tenta uma vez com menos kbps e, passando de novo, avisa em vez de falhar."""
        if 'mp3' not in self.outputs:
            self.skipTest('sem mp3')
        source = music(self.dir / 'm.wav')
        calls = []
        real = audiocompress._encode

        def fake(exe, source_path, stage, options, kbps, info_):
            calls.append(kbps)
            real(exe, source_path, stage, options, kbps, info_)
            return 120 * 1024 * (2.0 if len(calls) == 1 else 1.4)                      # tamanho «medido» (inflado)

        with mock.patch.object(audiocompress, '_encode', fake):
            [out] = engine.convert(self.job(source, comp_mode='size', comp_size_kb=120, audio_format='mp3'))
        self.assertEqual(len(calls), 2); self.assertLess(calls[1], calls[0])
        self.assertTrue(any('Melhor esforço' in n for n in engine.RUN_NOTES))
        self.assertTrue(Path(out).exists())

    def test_would_not_get_smaller_is_refused_and_leaves_nothing(self):
        if 'mp3' not in self.outputs:
            self.skipTest('sem mp3')
        source = music(self.dir / 's.wav')
        before = sorted(p.name for p in self.dir.iterdir())
        real = audiocompress._encode

        def fake(exe, source_path, stage, options, kbps, info_):
            real(exe, source_path, stage, options, kbps, info_)
            return source.stat().st_size                                                  # «ficou do mesmo tamanho»

        with mock.patch.object(audiocompress, '_encode', fake), self.assertRaises(engine.ConversionError) as caught:
            engine.convert(self.job(source, comp_kbps=64))
        self.assertIn('s.wav', str(caught.exception)); self.assertIn('nada foi salvo', str(caught.exception))
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), before)

    def test_already_low_bitrate_source_is_refused_up_front(self):
        if 'mp3' not in self.outputs:
            self.skipTest('sem mp3')
        mp3 = music(self.dir / 'a.mp3', '-c:a', 'libmp3lame', '-b:a', '96k')
        with self.assertRaises(engine.ConversionError) as caught:
            engine.convert(self.job(mp3, comp_kbps=128))
        self.assertIn('não reduziria', str(caught.exception))

    def test_video_source_extracts_audio(self):
        if 'mp3' not in self.outputs:
            self.skipTest('sem mp3')
        video = self.dir / 'v.mp4'
        try:
            run('-f', 'lavfi', '-i', 'color=c=blue:s=64x64:d=5:r=10', '-f', 'lavfi', '-i', 'anoisesrc=d=5:c=pink:r=44100:a=0.3', '-c:v', 'mpeg4', '-c:a', 'aac', '-shortest', str(video))
        except subprocess.CalledProcessError:
            self.skipTest('sem mpeg4/aac para criar o vídeo')
        [out] = engine.convert(self.job(video, comp_kbps=64))
        self.assertFalse(mediatools.probe(out)['has_video'])

    def test_original_untouched_and_collisions_never_overwrite(self):
        source = music(self.dir / 'p.wav'); before = source.read_bytes()
        a = engine.convert(self.job(source, comp_kbps=64))[0]; b = engine.convert(self.job(source, comp_kbps=64))[0]
        self.assertEqual(sorted([Path(a).name, Path(b).name]), ['p-comprimido-2.mp3', 'p-comprimido.mp3']); self.assertEqual(source.read_bytes(), before)

    def test_not_audio_is_refused(self):
        (self.dir / 'x.mp3').write_bytes(b'not audio')
        with self.assertRaises(engine.ConversionError):
            engine.convert(self.job(self.dir / 'x.mp3'))

    def test_worker_returns_the_notes(self):
        source = music(self.dir / 'w.wav')
        done = runner.run_job(self.job(source, comp_kbps=64))
        self.assertEqual(Path(done[0]).name, 'w-comprimido.mp3')
        self.assertTrue(any('Tamanho: de' in n for n in runner.take_notes()))

    def test_loss_report(self):
        source = music(self.dir / 'p.wav')
        self.assertIn('64 kbps', ' '.join(engine.loss_report([str(source)], engine.AUDIO_COMPRESS, {'comp_kbps': 64})))
        self.assertIn('Comprimir usa formatos com perda', ' '.join(engine.loss_report([str(source)], engine.AUDIO_COMPRESS, {'audio_format': 'flac'})))


class RegistrationTests(unittest.TestCase):
    def test_target_options_and_wheel(self):
        import tool_registry
        self.assertIn(engine.AUDIO_COMPRESS, engine.OPERATIONS); self.assertIn(engine.AUDIO_COMPRESS, engine.PDF_LONG_TARGETS)
        self.assertTrue({'comp_mode', 'comp_mono'} <= tool_registry.BASE_STR_OPTIONS); self.assertTrue({'comp_kbps', 'comp_size_kb'} <= tool_registry.BASE_INT_OPTIONS)
        self.assertEqual([m[0] for m in tool_registry.AUDIO_GROUPS['convert'][3]], [engine.AUDIO_CONVERT, engine.AUDIO_COMPRESS])


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
        patcher = mock.patch.object(mediatools, 'build_info', return_value={'outputs': ['mp3', 'm4a', 'ogg', 'opus', 'flac', 'wav', 'aiff'], 'encoders': []})
        patcher.start(); self.addCleanup(patcher.stop)

    def open_tool(self, files=('/x/a.wav',), size=1_764_000, **extra):
        self.panel.select_category('audio')
        self.panel.files = list(files)
        with mock.patch.object(self.panel.audio_stage, 'show_files'):
            self.panel.select_tool(self.wp.AUDIO_COMPRESS)
        self.panel.audio_stage.infos = {path: info(name=Path(path).name, size=size, **extra) for path in files}
        self.panel._audiocompress_changed()

    def test_widgets_do_not_collide_with_the_pdf_compress_panel(self):
        for name in ('mode', 'format', 'kbps', 'size', 'mono', 'tags', 'info'):
            self.assertIsNot(getattr(self.panel, 'ca_' + name), getattr(self.panel, 'cp_' + name, None))
        self.assertEqual({k for k, w in self.panel.form_fields.items() if w is self.panel.cp_info}, {'pinfo'})

    def test_values_follow_the_chips(self):
        self.open_tool()
        self.assertEqual(self.panel._audiocompress_values(), {'comp_mode': 'bitrate', 'audio_format': 'mp3', 'comp_mono': 'no', 'audio_tags': 'keep', 'comp_kbps': 128})
        self.panel.ca_mode.setCurrentIndex(1); self.panel.ca_format.setCurrentIndex(3); self.panel.ca_mono.setCurrentIndex(1); self.panel.ca_tags.setCurrentIndex(1); self.panel.ca_size.setValue(0.5)
        self.assertEqual(self.panel._audiocompress_values(), {'comp_mode': 'size', 'audio_format': 'opus', 'comp_mono': 'yes', 'audio_tags': 'drop', 'comp_size_kb': 500})

    def test_bitrate_state_shows_the_estimate(self):
        self.open_tool()
        text, ready = self.panel._audiocompress_state()
        self.assertTrue(ready); self.assertIn('≈ 128 kbps', text); self.assertIn('(de ', text)
        self.assertTrue(self.panel.run_button.isEnabled()); self.assertTrue(self.panel.ca_kbps.isEnabled()); self.assertFalse(self.panel.ca_size.isEnabled())

    def test_format_limits_block_the_run(self):
        self.open_tool()
        self.panel.ca_format.setCurrentIndex(2); self.panel.ca_kbps.setCurrentIndex(audiocompress.KBPS_CHOICES.index(320))     # OGG vai até 256
        text, ready = self.panel._audiocompress_state()
        self.assertFalse(ready); self.assertIn('256', text)

    def test_size_mode_state(self):
        self.open_tool()
        self.panel.ca_mode.setCurrentIndex(1)
        self.assertTrue(self.panel.ca_size.isEnabled()); self.assertFalse(self.panel.ca_kbps.isEnabled())
        self.panel.ca_size.setValue(0.1)                                    # 100 KB para 10 s: ≈ 67 kbps
        text, ready = self.panel._audiocompress_state()
        self.assertTrue(ready); self.assertIn('≈ 67 kbps', text); self.assertIn('Melhor esforço', text)
        self.panel.ca_size.setValue(3.0)                                    # maior que o arquivo (1,7 MB)
        self.assertFalse(self.panel._audiocompress_state()[1]); self.assertIn('já tem', self.panel._audiocompress_state()[0])

    def test_many_files_only_in_bitrate_mode(self):
        self.open_tool(files=('/x/a.wav', '/x/b.wav'))
        self.assertTrue(self.panel._audiocompress_state()[1]); self.assertIn('2 arquivos', self.panel._audiocompress_state()[0])
        self.panel.ca_mode.setCurrentIndex(1)
        self.assertFalse(self.panel._audiocompress_state()[1]); self.assertIn('um arquivo só', self.panel._audiocompress_state()[0])

    def test_already_small_source_blocks(self):
        self.open_tool(container='mp3', codec='mp3', stream_bit_rate=96000, size=120_000)
        self.assertFalse(self.panel._audiocompress_state()[1]); self.assertIn('não reduziria', self.panel._audiocompress_state()[0])

    def test_blocked_without_ffmpeg_error_or_while_reading(self):
        self.open_tool(); self.panel.audio_stage.infos = {}
        self.assertEqual(self.panel._audiocompress_state(), ('Lendo o arquivo…', False))
        self.open_tool(error='Arquivo corrompido.'); self.assertEqual(self.panel._audiocompress_state(), ('Arquivo corrompido.', False))
        self.panel.controller.capabilities['audio'] = (False, 'FFmpeg não encontrado.')
        self.assertEqual(self.panel._audiocompress_state(), ('FFmpeg não encontrado.', False))

    def test_missing_encoder_blocks(self):
        self.open_tool()
        with mock.patch.object(mediatools, 'build_info', return_value={'outputs': ['flac'], 'encoders': []}):
            self.assertIn('codificador', self.panel._audiocompress_state()[0])

    def test_run_sends_the_options(self):
        self.open_tool()
        started = []
        self.panel.controller.start_job = lambda *args, **kwargs: started.append((args, kwargs))
        self.panel.ca_format.setCurrentIndex(3); self.panel.ca_kbps.setCurrentIndex(audiocompress.KBPS_CHOICES.index(64))
        self.panel.run_selected()
        self.assertTrue(started, self.panel.status.text())
        text = repr(started[0])
        for expected in ("'comp_kbps': 64", "'audio_format': 'opus'", self.wp.AUDIO_COMPRESS):
            self.assertIn(expected, text)


if __name__ == '__main__':
    unittest.main()
