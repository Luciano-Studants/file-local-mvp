"""Base de mídia (0.9.43): localizar o FFmpeg, conferir licença/capacidades e ler informações de áudio.

A análise (licença, codificadores, JSON do ffprobe) é testada com textos prontos; a leitura de ponta a ponta usa o FFmpeg real
quando ele existe (os arquivos de teste são gerados por ele com fontes sintéticas) e é pulada quando não existe.
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import capabilities
import mediatools
from mediatools import MediaError

FFMPEG = mediatools.find_tool('ffmpeg')
NEEDS_FFMPEG = unittest.skipUnless(FFMPEG and mediatools.find_tool('ffprobe'), 'FFmpeg/ffprobe não instalados')

GPL_CONFIG = 'configuration: --prefix=/usr --enable-gpl --enable-libx264 --enable-libmp3lame'
LGPL_CONFIG = 'configuration: --disable-gpl --enable-version3 --enable-libmp3lame --enable-libopus'
ENCODERS = """Encoders:
 V..... = Video
 A..... = Audio
 ------
 A....D aac                  AAC (Advanced Audio Coding)
 A....D flac                 FLAC (Free Lossless Audio Codec)
 A....D libmp3lame           libmp3lame MP3 (MPEG audio layer 3) (codec mp3)
 A....D pcm_s16le            PCM signed 16-bit little-endian
 V....D libx264              libx264 H.264
"""


def make_audio(path, args, duration=1):
    command = [FFMPEG, '-hide_banner', '-nostdin', '-v', 'error', '-y', *args, str(path)]
    subprocess.run(command, check=True, stdin=subprocess.DEVNULL, capture_output=True, timeout=60)
    return Path(path)


class PureTests(unittest.TestCase):
    def test_license_classification(self):
        self.assertEqual(mediatools.parse_version('ffmpeg version 6.1 Copyright\n' + GPL_CONFIG)['license'], 'gpl')
        lgpl = mediatools.parse_version('ffmpeg version 7.0-lgpl Copyright\n' + LGPL_CONFIG)
        self.assertEqual((lgpl['license'], lgpl['version3'], lgpl['version']), ('lgpl', True, '7.0-lgpl'))
        self.assertEqual(mediatools.classify_license('--enable-gpl --enable-nonfree'), 'nonfree')
        self.assertEqual(mediatools.classify_license(''), 'lgpl')

    def test_encoder_parser_keeps_only_audio(self):
        names = mediatools.parse_encoders(ENCODERS)
        self.assertEqual(names, {'aac', 'flac', 'libmp3lame', 'pcm_s16le'})

    def test_probe_summary_and_tag_cleaning(self):
        data = {'format': {'format_name': 'mp3', 'format_long_name': 'MP2/3', 'duration': '12.5', 'size': '2000', 'bit_rate': '128000',
                           'tags': {'TITLE': 'Canção\x00 teste', 'artist': 'A' * 500, 'encoder': 'segredo'}},
                'streams': [{'codec_type': 'audio', 'codec_name': 'mp3', 'sample_rate': '44100', 'channels': 2, 'channel_layout': 'stereo'},
                            {'codec_type': 'video', 'codec_name': 'mjpeg', 'disposition': {'attached_pic': 1}}], 'chapters': [{}, {}]}
        info = mediatools.parse_probe(data)
        self.assertEqual((info['duration'], info['sample_rate'], info['channels'], info['chapters']), (12.5, 44100, 2, 2))
        self.assertTrue(info['has_cover']); self.assertFalse(info['has_video'])
        self.assertEqual(info['tags']['title'], 'Canção  teste')
        self.assertEqual(len(info['tags']['artist']), mediatools.MAX_TAG)
        self.assertNotIn('encoder', info['tags'])             # só etiquetas conhecidas aparecem

    def test_probe_rejects_files_without_audio_or_over_limits(self):
        with self.assertRaisesRegex(MediaError, 'não contém áudio'):
            mediatools.parse_probe({'streams': [{'codec_type': 'video'}], 'format': {}})
        with self.assertRaises(MediaError):
            mediatools.parse_probe({'streams': [], 'format': {}})
        with self.assertRaisesRegex(MediaError, 'fluxos demais'):
            mediatools.parse_probe({'streams': [{'codec_type': 'audio'}] * (mediatools.MAX_STREAMS + 1), 'format': {}})
        with self.assertRaisesRegex(MediaError, 'longo demais'):
            mediatools.parse_probe({'streams': [{'codec_type': 'audio'}], 'format': {'duration': str(mediatools.MAX_DURATION + 1)}})

    def test_bad_numbers_do_not_crash(self):
        info = mediatools.parse_probe({'streams': [{'codec_type': 'audio', 'sample_rate': 'x', 'channels': None}], 'format': {'duration': 'N/A', 'bit_rate': 'N/A'}})
        self.assertEqual((info['sample_rate'], info['channels'], info['duration']), (0, 0, 0))

    def test_probe_command_is_locked_down(self):
        args = mediatools.probe_args('/a/b.mp3')
        self.assertEqual(args[args.index('-protocol_whitelist') + 1], 'file')      # nada de rede, nem por lista de reprodução
        self.assertEqual(args[-2:], ['-i', 'file:/a/b.mp3'])                         # nome nunca é lido como opção

    def test_run_tool_has_no_shell_no_keyboard_and_a_timeout(self):
        with mock.patch('subprocess.run') as run:
            run.return_value = mock.Mock(stdout=b'ok', returncode=0)
            self.assertEqual(mediatools.run_tool('/x/ffprobe', ['-version']), 'ok')
        kwargs = run.call_args.kwargs
        self.assertIs(kwargs['shell'], False); self.assertEqual(kwargs['stdin'], subprocess.DEVNULL); self.assertGreater(kwargs['timeout'], 0)
        self.assertEqual(run.call_args.args[0][:2], ['/x/ffprobe', '-hide_banner'])

    def test_run_tool_errors_are_portuguese_and_bounded(self):
        with mock.patch('subprocess.run', side_effect=subprocess.TimeoutExpired('x', 1)):
            with self.assertRaisesRegex(MediaError, 'demorou demais'): mediatools.run_tool('/x', [])
        with mock.patch('subprocess.run', side_effect=OSError('boom')):
            with self.assertRaisesRegex(MediaError, 'Não foi possível executar'): mediatools.run_tool('/x', [])
        with mock.patch('subprocess.run', return_value=mock.Mock(stdout=b'x' * (mediatools.MAX_OUTPUT + 1), returncode=0)):
            with self.assertRaisesRegex(MediaError, 'grande demais'): mediatools.run_tool('/x', [])
        with mock.patch('subprocess.run', return_value=mock.Mock(stdout=b'', returncode=1)):
            with self.assertRaisesRegex(MediaError, 'não pôde ser lido'): mediatools.run_tool('/x', [])

    def test_format_duration(self):
        self.assertEqual((mediatools.format_duration(5), mediatools.format_duration(65.4), mediatools.format_duration(3725)), ('0:05', '1:05', '1:02:05'))

    def test_capability_without_ffmpeg_says_how_to_fix(self):
        with mock.patch.object(mediatools, 'find_tool', return_value=None):
            ok, reason = mediatools.capability()
        self.assertFalse(ok); self.assertIn('ffmpeg', reason); self.assertIn('ffprobe', reason)
        with mock.patch.object(mediatools, 'find_tool', return_value=None), mock.patch.object(mediatools, 'build_info', return_value=None):
            self.assertEqual(mediatools.capability_report()['found'], False)

    def test_unknown_tool_name_is_refused(self):
        with self.assertRaises(ValueError): mediatools.find_tool('ffplay')

    def test_capabilities_module_lists_audio(self):
        with mock.patch.object(mediatools, 'capability', return_value=(True, 'ok')):
            self.assertEqual(capabilities.probe_capabilities()['audio'], (True, 'ok'))
        self.assertIn('Áudio', capabilities.describe_capabilities(capabilities.probe_capabilities()))

    def test_build_must_be_lgpl_to_ship(self):
        info = {'found': True, 'license': 'gpl'}
        fake = {'version': '1', 'configuration': '', 'license': 'gpl', 'version3': False, 'encoders': [], 'outputs': ['mp3'], 'exe': '/x'}
        with mock.patch.object(mediatools, 'build_info', return_value=fake):
            self.assertFalse(mediatools.capability_report()['distributable'])
            self.assertIn('NÃO pode', mediatools.capability_report()['note'])
        fake['license'] = 'lgpl'
        with mock.patch.object(mediatools, 'build_info', return_value=fake):
            self.assertTrue(mediatools.capability_report()['distributable'])


@NEEDS_FFMPEG
class RealFfmpegTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name); self.addCleanup(self.temp.cleanup)

    def test_build_info_reports_version_license_and_outputs(self):
        info = mediatools.build_info(refresh=True)
        self.assertTrue(info['version']); self.assertIn(info['license'], ('lgpl', 'gpl', 'nonfree'))
        self.assertIn('wav', info['outputs']); self.assertIn('flac', info['outputs'])
        self.assertTrue(mediatools.capability()[0])

    def test_probe_wav(self):
        wav = make_audio(self.root / 'tom.wav', ['-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=22050:duration=1.5', '-ac', '1'])
        info = mediatools.probe(wav)
        self.assertEqual((info['codec'], info['sample_rate'], info['channels']), ('pcm_s16le', 22050, 1))
        self.assertAlmostEqual(info['duration'], 1.5, delta=0.05)
        self.assertEqual(info['audio_streams'], 1); self.assertFalse(info['has_video'])

    def test_probe_flac_with_tags_stereo(self):
        flac = make_audio(self.root / 'a.flac', ['-f', 'lavfi', '-i', 'sine=frequency=300:duration=1', '-ac', '2', '-metadata', 'title=Teste', '-metadata', 'artist=Eu'])
        info = mediatools.probe(flac)
        self.assertEqual((info['codec'], info['channels'], info['tags'].get('title'), info['tags'].get('artist')), ('flac', 2, 'Teste', 'Eu'))

    def test_extension_does_not_decide_the_format(self):
        wav = make_audio(self.root / 'tom.wav', ['-f', 'lavfi', '-i', 'sine=duration=1'])
        disguised = self.root / 'musica.mp3'; disguised.write_bytes(wav.read_bytes())
        self.assertEqual(mediatools.probe(disguised)['codec'], 'pcm_s16le')

    def test_non_audio_and_empty_and_missing_files(self):
        text = self.root / 'a.mp3'; text.write_text('isto não é áudio', encoding='utf-8')
        with self.assertRaises(MediaError): mediatools.probe(text)
        empty = self.root / 'v.wav'; empty.write_bytes(b'')
        with self.assertRaisesRegex(MediaError, 'vazio'): mediatools.probe(empty)
        with self.assertRaisesRegex(MediaError, 'não foi encontrado'): mediatools.probe(self.root / 'nao-existe.wav')
        with self.assertRaises(MediaError): mediatools.probe(self.root)

    def test_video_without_audio_is_refused(self):
        video = make_audio(self.root / 'mudo.mkv', ['-f', 'lavfi', '-i', 'color=c=black:s=64x64:d=1', '-c:v', 'mpeg4'])
        with self.assertRaisesRegex(MediaError, 'não contém áudio'): mediatools.probe(video)

    def test_video_with_audio_is_accepted_and_flagged(self):
        video = make_audio(self.root / 'com-som.mkv', ['-f', 'lavfi', '-i', 'color=c=black:s=64x64:d=1', '-f', 'lavfi', '-i', 'sine=duration=1', '-c:v', 'mpeg4', '-c:a', 'flac', '-shortest'])
        info = mediatools.probe(video)
        self.assertTrue(info['has_video']); self.assertEqual(info['codec'], 'flac')

    def test_playlist_cannot_reach_the_network(self):
        playlist = self.root / 'lista.m3u8'
        playlist.write_text('#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-TARGETDURATION:1\n#EXTINF:1,\nhttp://127.0.0.1:9/x.ts\n#EXT-X-ENDLIST\n', encoding='utf-8')
        with self.assertRaises(MediaError): mediatools.probe(playlist)

    def test_name_starting_with_dash_is_not_an_option(self):
        odd = make_audio(self.root / '-v.wav', ['-f', 'lavfi', '-i', 'sine=duration=1'])
        self.assertEqual(mediatools.probe(odd)['codec'], 'pcm_s16le')

    @unittest.skipIf(sys.platform == 'win32', 'link simbólico exige privilégio no Windows')
    def test_symlink_is_refused(self):
        wav = make_audio(self.root / 'tom.wav', ['-f', 'lavfi', '-i', 'sine=duration=1'])
        link = self.root / 'link.wav'; link.symlink_to(wav)
        with self.assertRaisesRegex(MediaError, 'não foi encontrado'): mediatools.probe(link)

    def test_original_is_untouched(self):
        wav = make_audio(self.root / 'tom.wav', ['-f', 'lavfi', '-i', 'sine=duration=1'])
        before = wav.read_bytes(); mediatools.probe(wav)
        self.assertEqual(wav.read_bytes(), before); self.assertEqual(sorted(p.name for p in self.root.iterdir()), ['tom.wav'])


if __name__ == '__main__':
    unittest.main()
