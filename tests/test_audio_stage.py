"""Áudio, item 2 (0.9.43): leitura pelo worker, texto das informações e a ferramenta «Informações» no painel.

A leitura de ponta a ponta usa o worker de verdade (subprocesso) e o FFmpeg real quando existe; a parte de interface injeta o leitor.
"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from PySide6.QtWidgets import QApplication, QPushButton

import audio_stage
import mediatools
import runner
import workspace_panel as wp
from audio_stage import AudioStage, details_html
from tray_app import FeaturePanel, JobController

app = QApplication.instance() or QApplication([])
FFMPEG = mediatools.find_tool('ffmpeg')
NEEDS_FFMPEG = unittest.skipUnless(FFMPEG and mediatools.find_tool('ffprobe'), 'FFmpeg/ffprobe não instalados')

INFO = {'name': 'a.flac', 'container': 'flac', 'container_label': 'raw FLAC', 'duration': 65.4, 'size': 2048, 'bit_rate': 128000, 'audio_streams': 1,
        'has_video': False, 'has_cover': True, 'chapters': 0, 'codec': 'flac', 'codec_label': 'FLAC (Free Lossless Audio Codec)', 'profile': '',
        'sample_rate': 44100, 'channels': 2, 'channel_layout': 'stereo', 'bits_per_sample': 16, 'stream_bit_rate': 0, 'tags': {'title': 'Canção', 'artist': 'Eu'}}


def make_wav(path, seconds=1):
    subprocess.run([FFMPEG, '-hide_banner', '-nostdin', '-v', 'error', '-y', '-f', 'lavfi', '-i', f'sine=frequency=440:duration={seconds}', str(path)],
                   check=True, stdin=subprocess.DEVNULL, capture_output=True, timeout=60)
    return Path(path)


class TextTests(unittest.TestCase):
    def test_describe_rows_are_in_portuguese(self):
        rows = dict(mediatools.describe(INFO))
        self.assertEqual((rows['Duração'], rows['Taxa de amostragem'], rows['Canais'], rows['Profundidade']), ('1:05', '44,1 kHz', 'Estéreo (2)', '16 bits'))
        self.assertEqual((rows['Capa'], rows['Título'], rows['Artista'], rows['Tamanho']), ('embutida', 'Canção', 'Eu', '2,0 KB'))
        self.assertEqual(rows['Taxa de bits'], '128 kb/s')

    def test_describe_handles_missing_values(self):
        rows = dict(mediatools.describe({'duration': 0}))
        self.assertEqual(rows['Codec'], '—'); self.assertNotIn('Canais', rows); self.assertNotIn('Taxa de amostragem', rows)

    def test_tags_from_the_file_are_escaped_in_html(self):
        info = {**INFO, 'tags': {'title': '<script>alert(1)</script><b>x</b>', 'artist': '&amp;'}}
        html = details_html(info)
        self.assertNotIn('<script>', html); self.assertNotIn('<b>x</b>', html)
        self.assertIn('&lt;script&gt;', html); self.assertIn('&amp;amp;', html)

    def test_human_size(self):
        self.assertEqual((mediatools.human_size(10), mediatools.human_size(1536), mediatools.human_size(5 * 1024 ** 2)), ('10 B', '1,5 KB', '5,0 MB'))


class RunOpTests(unittest.TestCase):
    def test_validates_the_request(self):
        for bad in ({'op': 'x', 'paths': ['/a']}, {'op': 'audio_info'}, {'op': 'audio_info', 'paths': []}, {'op': 'audio_info', 'paths': ['/a'] * 101}, {'op': 'audio_info', 'paths': 'a'}):
            with self.subTest(bad), self.assertRaises(mediatools.MediaError):
                mediatools.run_op(bad)

    def test_a_bad_file_does_not_break_the_list(self):
        result = mediatools.run_op({'op': 'audio_info', 'paths': ['relativo.mp3', '/nao/existe.wav']})
        self.assertEqual([i['name'] for i in result['infos']], ['relativo.mp3', 'existe.wav'])
        self.assertTrue(all(i.get('error') for i in result['infos']))

    def test_engine_validator_errors_become_list_errors(self):
        def refuse(_raw): raise ValueError('Os arquivos não podem estar vazios nem passar de 100 MiB.')
        info = mediatools.run_op({'op': 'audio_info', 'paths': ['/a/b.wav']}, refuse)['infos'][0]
        self.assertIn('100 MiB', info['error'])


@NEEDS_FFMPEG
class RealWorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name); self.addCleanup(self.temp.cleanup)

    def test_worker_reads_audio_and_reports_bad_files(self):
        wav = make_wav(self.root / 'tom.wav', 2)
        bad = self.root / 'texto.mp3'; bad.write_text('nada de áudio', encoding='utf-8')
        result = runner.run_media_op({'op': 'audio_info', 'paths': [str(wav), str(bad)]})
        good, broken = result['infos']
        self.assertEqual((good['name'], good['codec']), ('tom.wav', 'pcm_s16le')); self.assertAlmostEqual(good['duration'], 2, delta=0.1)
        self.assertEqual(broken['name'], 'texto.mp3'); self.assertTrue(broken['error'])
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ['texto.mp3', 'tom.wav'])          # nada gravado ao lado dos arquivos

    def test_worker_refuses_relative_paths_and_empty_files(self):
        empty = self.root / 'v.wav'; empty.write_bytes(b'')
        result = runner.run_media_op({'op': 'audio_info', 'paths': [str(empty), 'rel.wav']})
        self.assertTrue(all(i.get('error') for i in result['infos']))


class StageTests(unittest.TestCase):
    def make(self, infos):
        stage = AudioStage(); stage.capability = lambda: (True, 'ok')
        stage.loader = lambda job: {'infos': infos}
        self.addCleanup(stage.deleteLater)
        return stage

    def test_one_file_shows_details_without_a_list(self):
        stage = self.make([INFO]); stage.show_files(['/x/a.flac'])
        self.assertTrue(stage.files.isHidden()); self.assertEqual(stage.summary.text(), 'a.flac')
        self.assertIn('Duração', stage.details.text()); self.assertIn('Somente leitura', stage.note.text())

    def test_many_files_show_a_list_totals_and_problems(self):
        stage = self.make([INFO, {'name': 'b.mp3', 'error': 'O arquivo não é um áudio reconhecido.'}])
        stage.show_files(['/x/a.flac', '/x/b.mp3'])
        self.assertFalse(stage.files.isHidden()); self.assertEqual(stage.files.count(), 2)
        self.assertIn('1 com problema', stage.summary.text()); self.assertIn('duração total 1:05', stage.summary.text())
        self.assertIn('1:05 · flac', stage.files.item(0).text()); self.assertIn('não é um áudio', stage.files.item(1).text())
        stage.files.setCurrentRow(1); self.assertIn('não é um áudio', stage.details.text())
        stage.files.setCurrentRow(0); self.assertIn('Duração', stage.details.text())

    def test_only_bad_files(self):
        stage = self.make([{'name': 'b.mp3', 'error': 'Este arquivo não contém áudio.'}]); stage.show_files(['/x/b.mp3'])
        self.assertIn('não contém áudio', stage.details.text())

    def test_missing_ffmpeg_explains_and_does_not_read(self):
        stage = AudioStage(); stage.capability = lambda: (False, 'Falta o programa de mídia (ffmpeg).')
        calls = []; stage.loader = lambda job: calls.append(job)
        stage.show_files(['/x/a.flac'])
        self.assertIn('Falta o programa', stage.summary.text()); self.assertEqual(calls, [])

    def test_stale_answers_are_dropped(self):
        stage = self.make([INFO]); stage.show_files(['/x/a.flac'])
        stage._apply(stage._token - 1, {'infos': [{**INFO, 'name': 'velho.flac'}]}, '')
        self.assertEqual(stage.summary.text(), 'a.flac')

    def test_loader_failure_is_shown(self):
        stage = AudioStage(); stage.capability = lambda: (True, 'ok')
        def boom(job): raise RuntimeError('worker caiu')
        stage.loader = boom; stage.show_files(['/x/a.flac'])
        self.assertIn('worker caiu', stage.summary.text())

    def test_empty_selection_resets(self):
        stage = self.make([INFO]); stage.show_files(['/x/a.flac']); stage.show_files([])
        self.assertEqual(stage.details.text(), ''); self.assertTrue(stage.files.isHidden())

    def test_task_thread_reports_result_and_error(self):
        results = []
        ok = audio_stage.AudioLoadTask(1, {'op': 'audio_info'}, loader=lambda job: {'infos': []}); ok.finished_with.connect(lambda t, r, e: results.append((t, r, e))); ok.run()
        bad = audio_stage.AudioLoadTask(2, {}, loader=lambda job: (_ for _ in ()).throw(ValueError('x'))); bad.finished_with.connect(lambda t, r, e: results.append((t, r, e))); bad.run()
        self.assertEqual(results, [(1, {'infos': []}, ''), (2, None, 'x')])


class PanelTests(unittest.TestCase):
    def setUp(self):
        controller = JobController(capabilities={'images': (True, 'ok'), 'pdf': (True, 'ok'), 'audio': (True, 'ok')})
        self.panel = FeaturePanel(controller)
        self.panel.audio_stage.capability = lambda: (True, 'ok')
        self.panel.audio_stage.loader = lambda job: mediatools.run_op(job)
        self.addCleanup(self.panel.close)

    def test_audio_category_uses_the_wheel_with_groups(self):
        self.panel.select_category('audio')
        self.assertIs(self.panel.category_body.currentWidget(), self.panel.wheels_scroll)
        wheel = self.panel.wheel_widgets[0]
        self.assertEqual([a.label for a in wheel.actions], ['Ler', 'Converter', 'Editar', 'Ajustar'])
        self.assertEqual([c.target for a in wheel.actions for c in a.children], [wp.AUDIO_INFO, wp.AUDIO_TAGS, wp.AUDIO_CONVERT, wp.AUDIO_COMPRESS, wp.AUDIO_TRIM, wp.AUDIO_CHANNELS, wp.AUDIO_NORM])
        self.assertTrue(wp.CATEGORIES['audio'][2])

    def test_choosing_the_wheel_slice_opens_the_read_only_tool(self):
        self.panel.select_category('audio')
        self.panel.select_tool(wp.AUDIO_INFO)
        self.assertEqual(self.panel.selected_tool, wp.AUDIO_INFO)
        self.assertEqual(self.panel.tool_title.text(), 'Informações do áudio')
        self.assertTrue(self.panel.run_button.isHidden())
        self.assertIn('Abra um arquivo de áudio', self.panel.preview_image.text())

    @NEEDS_FFMPEG
    def test_dropping_an_audio_file_opens_the_information(self):
        with tempfile.TemporaryDirectory() as folder:
            wav = make_wav(Path(folder) / 'tom.wav', 3)
            self.panel.set_files([str(wav)])
            self.assertEqual(self.panel.selected_tool, wp.AUDIO_INFO)
            self.assertEqual(self.panel.stage.currentIndex(), wp.STAGE_AUDIO)
            self.assertIn('0:03', self.panel.audio_stage.details.text())
            self.assertEqual(sorted(p.name for p in Path(folder).iterdir()), ['tom.wav'])

    def test_run_button_comes_back_in_other_tools(self):
        self.panel.select_category('audio'); self.panel.select_tool(wp.AUDIO_INFO)
        self.assertTrue(self.panel.run_button.isHidden())
        self.panel.select_category('pdf'); self.panel.select_tool('PDF → Text')
        self.assertFalse(self.panel.run_button.isHidden())

    def test_audio_suffixes_do_not_open_the_image_tools(self):
        self.assertFalse(wp.AUDIO_SUFFIXES & wp.IMAGE_SUFFIXES)


if __name__ == '__main__':
    unittest.main()
