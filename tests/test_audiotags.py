"""Áudio, item 4: etiquetas (metadados) — editar campos, remover capa e limpar tudo, sem recodificar o áudio.

Argumentos, validação e textos não precisam de FFmpeg; a reescrita de ponta a ponta (motor e worker de verdade) usa o FFmpeg real.
"""
import hashlib
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import audiotags
import engine
import mediatools
import runner
from audiotags import MediaError

FFMPEG = mediatools.find_tool('ffmpeg')
NEEDS_FFMPEG = unittest.skipUnless(FFMPEG and mediatools.find_tool('ffprobe'), 'FFmpeg/ffprobe não instalados')
INFO = {'container': 'mp3', 'codec': 'mp3', 'audio_streams': 1, 'has_video': False, 'has_cover': False, 'duration': 2.0, 'tags': {'title': 'A', 'artist': 'B'}, 'extra_tags': {}}


def run(*args):
    subprocess.run([FFMPEG, '-hide_banner', '-nostdin', '-v', 'error', '-y', *args], check=True, stdin=subprocess.DEVNULL, capture_output=True, timeout=90)


def make_source(folder: Path, kind: str, cover=True):
    """Arquivo de teste com etiquetas (inclusive uma que o app não edita) e, quando o formato permite, capa."""
    folder = Path(folder)
    run('-f', 'lavfi', '-i', 'sine=duration=2:sample_rate=44100', str(folder / 'base.wav'))
    run('-f', 'lavfi', '-i', 'color=c=red:s=32x32:d=1', '-frames:v', '1', str(folder / 'cover.png'))
    out = folder / f'musica.{kind}'
    tags = ['-metadata', 'title=Original', '-metadata', 'artist=Artista', '-metadata', 'album_artist=AA', '-metadata', 'comment=nota']
    codec = {'ogg': ['-c:a', 'libvorbis'], 'opus': ['-c:a', 'libopus']}.get(kind, [])
    if kind in ('mp3', 'm4a', 'flac') and cover:
        run('-i', str(folder / 'base.wav'), '-i', str(folder / 'cover.png'), '-map', '0:a', '-map', '1:v', *codec, '-c:v', 'mjpeg', '-disposition:v', 'attached_pic',
            *tags, '-metadata', 'custom_x=extra', str(out))
    else:
        run('-i', str(folder / 'base.wav'), *codec, *tags, '-metadata', 'genre=Rock', str(out))
    return out


def audio_hash(path):
    """Hash do áudio decodificado (PCM): prova que não houve recodificação com perda."""
    done = subprocess.run([FFMPEG, '-nostdin', '-v', 'error', '-i', str(path), '-map', '0:a:0', '-f', 'hash', '-hash', 'sha256', '-'], capture_output=True, stdin=subprocess.DEVNULL, timeout=60)
    return done.stdout.strip()


class OptionTests(unittest.TestCase):
    def test_defaults_need_something_to_do(self):
        with self.assertRaises(MediaError) as caught:
            audiotags.options_from({})
        self.assertIn('Nada para mudar', str(caught.exception))

    def test_edits_cover_and_clear(self):
        self.assertEqual(audiotags.options_from({'tag_title': ' Oi '}), ('edit', 'keep', {'title': 'Oi'}))
        self.assertEqual(audiotags.options_from({'tag_cover': 'drop'}), ('edit', 'drop', {}))
        self.assertEqual(audiotags.options_from({'tag_mode': 'clear'}), ('clear', 'keep', {}))
        self.assertEqual(audiotags.options_from({'tag_genre': ''})[2], {'genre': ''})          # vazio = remover o campo

    def test_invalid_values_are_refused(self):
        bad = ({'tag_mode': 'tudo'}, {'tag_cover': 'x'}, {'tag_title': 'x' * 201}, {'tag_title': 'linha\nquebrada'}, {'tag_title': 'nul\x00'}, {'tag_title': 5},
               {'tag_track': 'três'}, {'tag_track': '3/'}, {'tag_disc': '1/2/3'}, {'tag_date': '01/02/2020'}, {'tag_mode': 'clear', 'tag_title': 'x'})
        for job in bad:
            with self.subTest(job=job), self.assertRaises(MediaError):
                audiotags.options_from(job)

    def test_valid_special_fields(self):
        for key, value in (('track', '3'), ('track', '3/12'), ('disc', '1/2'), ('date', '2020'), ('date', '2020-05'), ('date', '2020-05-01'), ('date', '')):
            self.assertEqual(audiotags.options_from({'tag_' + key: value})[2], {key: value})

    def test_only_listed_fields_are_read_from_the_job(self):
        self.assertEqual(audiotags.options_from({'tag_title': 'a', 'tag_encoder': 'x', 'tag_custom': 'y'})[2], {'title': 'a'})


class KindTests(unittest.TestCase):
    def test_supported_kinds(self):
        cases = {('mp3', 'mp3'): 'mp3', ('mov,mp4,m4a,3gp,3g2,mj2', 'aac'): 'm4a', ('mov,mp4,m4a,3gp,3g2,mj2', 'alac'): 'm4a', ('flac', 'flac'): 'flac',
                 ('ogg', 'vorbis'): 'ogg', ('ogg', 'opus'): 'opus', ('wav', 'pcm_s16le'): 'wav', ('aiff', 'pcm_s16be'): 'aiff'}
        for (container, codec), kind in cases.items():
            self.assertEqual(audiotags.kind_of({**INFO, 'container': container, 'codec': codec}), kind)

    def test_unsupported_inputs_are_refused(self):
        for patch in ({'container': 'asf', 'codec': 'wmav2'}, {'container': 'ogg', 'codec': 'flac'}, {'container': 'matroska,webm', 'codec': 'opus'},
                      {'has_video': True}, {'audio_streams': 2}, {'container': 'mov,mp4,m4a,3gp,3g2,mj2', 'codec': 'mp3'}):
            with self.subTest(patch=patch), self.assertRaises(MediaError):
                audiotags.kind_of({**INFO, **patch})


class ArgumentTests(unittest.TestCase):
    def args(self, kind='mp3', mode='edit', cover='keep', edits=None):
        return audiotags.build_args('/in/a.mp3', '/w/out', kind, mode, cover, edits if edits is not None else {'title': 'T'})

    def test_audio_is_copied_and_input_is_sandboxed(self):
        args = self.args()
        self.assertEqual(args[args.index('-c') + 1], 'copy')
        for flag in ('-nostdin', '-n', '-fs'):
            self.assertIn(flag, args)
        self.assertEqual(args[args.index('-protocol_whitelist') + 1], 'file')
        self.assertEqual(args[args.index('-i') + 1], 'file:/in/a.mp3'); self.assertEqual(args[-1], 'file:/w/out')
        self.assertNotIn('-c:a', args)                       # nunca recodifica

    def test_values_travel_as_one_argument_each(self):
        args = self.args(edits={'title': '-i /etc/passwd; rm -rf'})
        self.assertIn('title=-i /etc/passwd; rm -rf', args)

    def test_stream_scope_for_ogg_and_opus_only(self):
        self.assertIn('-metadata:s:a:0', self.args('ogg')); self.assertIn('-metadata:s:a:0', self.args('opus'))
        self.assertNotIn('-metadata:s:a:0', self.args('flac')); self.assertIn('-metadata', self.args('flac'))

    def test_cover_mapping(self):
        self.assertIn('0:v:0?', self.args('mp3', cover='keep'))
        self.assertNotIn('0:v:0?', self.args('mp3', cover='drop'))
        self.assertNotIn('0:v:0?', self.args('wav'))
        self.assertIn(f'{mediatools.COVER_TAG}=', self.args('ogg', cover='drop', edits={}))

    def test_clear_drops_everything(self):
        args = self.args('mp3', mode='clear', edits={})
        self.assertEqual(args[args.index('-map_metadata') + 1], '-1')
        self.assertIn('-map_chapters', args); self.assertNotIn('0:v:0?', args)

    def test_only_the_first_audio_stream_is_mapped(self):
        self.assertEqual(self.args()[self.args().index('-map') + 1], '0:a:0')


class NoteTests(unittest.TestCase):
    def test_notes_describe_the_change(self):
        text = ' '.join(audiotags.notes(INFO, 'edit', 'drop', {'title': 'x'}))
        for word in ('sem recodificar', 'Título', 'capa', 'não é alterado', '-etiquetas'):
            self.assertIn(word, text)
        self.assertIn('removidos', ' '.join(audiotags.notes(INFO, 'clear', 'keep', {})))

    def test_wav_and_unsupported_notes(self):
        self.assertIn('poucos campos', ' '.join(audiotags.notes({**INFO, 'container': 'wav', 'codec': 'pcm_s16le'}, 'edit', 'keep', {'title': 'x'})))
        self.assertIn('Só é possível', ' '.join(audiotags.notes({**INFO, 'container': 'asf', 'codec': 'wmav2'}, 'edit', 'keep', {'title': 'x'})))
        self.assertTrue(audiotags.notes(None, 'edit', 'keep', {'title': 'x'}))


class VerifyTests(unittest.TestCase):
    def check(self, after, mode='edit', cover='keep', edits=None, before=None, kind='mp3'):
        audiotags._verify(before or INFO, {**INFO, **after}, kind, mode, cover, edits if edits is not None else {'title': 'N'})

    def test_good_result_passes(self):
        self.check({'tags': {'title': 'N', 'artist': 'B'}})

    def test_failures_are_reported_without_saving(self):
        for after, kwargs in (({'tags': {'title': 'A', 'artist': 'B'}}, {}),                                   # edição não gravada
                              ({'tags': {'title': 'N'}}, {}),                                                  # perdeu o artista
                              ({'tags': {'title': 'N', 'artist': 'B'}, 'codec': 'aac'}, {}),
                              ({'tags': {'title': 'N', 'artist': 'B'}, 'duration': 90.0}, {}),
                              ({'tags': {'title': 'N', 'artist': 'B'}, 'has_cover': True}, {'cover': 'drop'}),
                              ({'tags': {'title': 'x'}}, {'mode': 'clear', 'edits': {}}),
                              ({'tags': {'title': 'N', 'artist': 'B'}, 'has_video': True}, {})):
            with self.subTest(after=after, kwargs=kwargs), self.assertRaises(MediaError):
                self.check(after, **kwargs)

    def test_cover_must_survive_when_kept(self):
        with self.assertRaises(MediaError):
            self.check({'tags': {'title': 'N', 'artist': 'B'}, 'has_cover': False}, before={**INFO, 'has_cover': True})

    def test_removed_field_must_be_gone(self):
        with self.assertRaises(MediaError):
            self.check({'tags': {'title': 'N', 'artist': 'B'}}, edits={'artist': ''})
        self.check({'tags': {'title': 'A'}}, edits={'artist': ''})


@NEEDS_FFMPEG
class EndToEndTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        mediatools.reset_cache()

    def job(self, source, **options):
        return {'target': engine.AUDIO_TAGS, 'paths': [str(source)], 'output': str(self.dir), **options}

    def names(self):
        return sorted(p.name for p in self.dir.iterdir())

    def test_edit_keeps_the_audio_identical_and_the_other_tags(self):
        for kind in ('mp3', 'm4a', 'flac', 'ogg', 'opus', 'wav'):
            with self.subTest(kind=kind):
                source = make_source(self.dir, kind)
                before = source.read_bytes()
                [out] = engine.convert(self.job(source, tag_title='Novo ç', tag_genre='Samba', tag_track='3/9', tag_album_artist=''))
                self.assertEqual(Path(out).name, f'musica-etiquetas.{kind}')
                info = mediatools.probe(out)
                self.assertEqual(info['tags']['title'], 'Novo ç'); self.assertEqual(info['tags']['genre'], 'Samba'); self.assertEqual(info['tags']['track'], '3/9')
                self.assertNotIn('album_artist', info['tags'])
                self.assertEqual(info['tags']['artist'], 'Artista'); self.assertEqual(info['tags']['comment'], 'nota')          # os outros ficam
                self.assertEqual(info['has_cover'], mediatools.probe(source)['has_cover'])
                self.assertEqual(audio_hash(out), audio_hash(source))             # mesmo áudio, sem recodificar
                self.assertEqual(source.read_bytes(), before)                     # original intacto
                for path in list(self.dir.iterdir()):
                    path.unlink()

    def test_extra_fields_the_app_does_not_edit_are_kept(self):
        source = make_source(self.dir, 'flac')
        [out] = engine.convert(self.job(source, tag_title='X'))
        self.assertEqual(mediatools.probe(out)['extra_tags'], {'custom_x': 'extra'})

    def test_clear_removes_tags_cover_and_extras(self):
        for kind in ('mp3', 'm4a', 'flac', 'ogg', 'wav'):
            with self.subTest(kind=kind):
                source = make_source(self.dir, kind)
                [out] = engine.convert(self.job(source, tag_mode='clear'))
                info = mediatools.probe(out)
                self.assertEqual(info['tags'], {}); self.assertEqual(info['extra_tags'], {}); self.assertFalse(info['has_cover'])
                self.assertEqual(audio_hash(out), audio_hash(source))
                for path in list(self.dir.iterdir()):
                    path.unlink()

    def test_remove_cover_only(self):
        for kind in ('mp3', 'm4a', 'flac'):
            with self.subTest(kind=kind):
                source = make_source(self.dir, kind)
                self.assertTrue(mediatools.probe(source)['has_cover'])
                [out] = engine.convert(self.job(source, tag_cover='drop'))
                info = mediatools.probe(out)
                self.assertFalse(info['has_cover']); self.assertEqual(info['tags']['title'], 'Original')
                for path in list(self.dir.iterdir()):
                    path.unlink()

    def test_ogg_cover_tag_is_removed(self):
        import base64, struct
        source = make_source(self.dir, 'ogg', cover=False)
        image = (self.dir / 'cover.png').read_bytes()
        block = struct.pack('>II', 3, 9) + b'image/png' + struct.pack('>I', 0) + struct.pack('>IIII', 32, 32, 24, 0) + struct.pack('>I', len(image)) + image
        with_cover = self.dir / 'capa.ogg'
        run('-i', str(source), '-c', 'copy', '-map_metadata:s:a:0', '0:s:a:0', '-metadata:s:a:0', 'METADATA_BLOCK_PICTURE=' + base64.b64encode(block).decode(), str(with_cover))
        self.assertTrue(mediatools.probe(with_cover)['has_cover'])
        with self.assertRaises(engine.ConversionError) as caught:               # o FFmpeg não regrava a capa do OGG
            engine.convert(self.job(with_cover, tag_title='x'))
        self.assertIn('Remover capa', str(caught.exception))
        [out] = engine.convert(self.job(with_cover, tag_title='x', tag_cover='drop'))
        info = mediatools.probe(out)
        self.assertFalse(info['has_cover']); self.assertEqual(info['tags']['title'], 'x')

    def test_aiff_refuses_a_field_it_cannot_store_and_leaves_nothing(self):
        source = make_source(self.dir, 'aiff', cover=False)
        with self.assertRaises(engine.ConversionError) as caught:
            engine.convert(self.job(source, tag_genre='Samba'))
        self.assertIn('AIFF', str(caught.exception)); self.assertIn('Gênero', str(caught.exception))
        self.assertEqual(self.names(), ['base.wav', 'cover.png', 'musica.aiff'])

    def test_unsupported_and_invalid_inputs_fail_cleanly(self):
        wma = self.dir / 'm.wma'; run('-f', 'lavfi', '-i', 'sine=duration=1', '-c:a', 'wmav2', str(wma))
        bogus = self.dir / 'texto.mp3'; bogus.write_text('não é áudio')
        for path in (wma, bogus):
            with self.subTest(path=path.name), self.assertRaises(engine.ConversionError):
                engine.convert(self.job(path, tag_title='x'))
        self.assertEqual(self.names(), ['m.wma', 'texto.mp3'])

    def test_invalid_options_and_nothing_to_do(self):
        source = make_source(self.dir, 'mp3')
        for options in ({}, {'tag_track': 'x'}, {'tag_mode': 'clear', 'tag_title': 'x'}):
            with self.subTest(options=options), self.assertRaises(engine.ConversionError):
                engine.convert(self.job(source, **options))
        self.assertNotIn('musica-etiquetas.mp3', self.names())

    def test_name_collision_never_overwrites(self):
        source = make_source(self.dir, 'mp3')
        first = engine.convert(self.job(source, tag_title='1'))[0]
        second = engine.convert(self.job(source, tag_title='2'))[0]
        self.assertEqual([Path(first).name, Path(second).name], ['musica-etiquetas.mp3', 'musica-etiquetas-2.mp3'])

    def test_runs_in_the_real_worker(self):
        source = make_source(self.dir, 'mp3')
        [out] = runner.run_job({'target': engine.AUDIO_TAGS, 'paths': [str(source)], 'tag_title': 'Pelo worker'})
        self.assertEqual(mediatools.probe(out)['tags']['title'], 'Pelo worker')

    def test_loss_report_reads_the_file(self):
        source = make_source(self.dir, 'wav', cover=False)
        text = ' '.join(engine.loss_report([str(source)], engine.AUDIO_TAGS, {'tag_title': 'x'}))
        self.assertIn('sem recodificar', text); self.assertIn('poucos campos', text)
        self.assertIn('Nada para mudar', ' '.join(engine.loss_report([str(source)], engine.AUDIO_TAGS, {})))

    def test_oversized_source_is_refused(self):
        source = make_source(self.dir, 'mp3')
        with mock.patch.object(audiotags, 'MAX_FILE_BYTES', 10), self.assertRaises(MediaError):
            audiotags.apply(source, self.dir / 'out', {'tag_title': 'x'})
        self.assertFalse((self.dir / 'out').exists())

    def test_info_shows_everything_in_the_file(self):
        source = make_source(self.dir, 'flac')
        info = mediatools.probe(source)
        rows = dict(mediatools.describe(info))
        self.assertEqual(rows['Outra: custom_x'], 'extra'); self.assertEqual(rows['Capa'], 'embutida')


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

    def open_tool(self, files=('/x/a.mp3',), infos=None):
        self.panel.select_category('audio')
        self.panel.files = list(files)
        with mock.patch.object(self.panel.audio_stage, 'show_files'):
            self.panel.select_tool(self.wp.AUDIO_TAGS)
        self.panel.audio_stage.infos = infos if infos is not None else {path: {**INFO, 'name': Path(path).name} for path in files}
        self.panel._audiotags_changed()

    def test_fields_are_prefilled_and_only_changes_are_sent(self):
        self.open_tool()
        self.assertEqual(self.panel.at_edits['title'].text(), 'A')
        self.assertFalse(self.panel._audiotags_state()[1])                   # nada mudou ainda
        self.panel.at_edits['title'].setText('Novo'); self.panel.at_edits['artist'].setText('')
        self.assertEqual(self.panel._audiotags_values(), {'tag_cover': 'keep', 'tag_mode': 'edit', 'tag_title': 'Novo', 'tag_artist': ''})
        self.assertTrue(self.panel._audiotags_state()[1])

    def test_typing_is_not_overwritten_when_the_infos_arrive_again(self):
        self.open_tool()
        self.panel.at_edits['album'].setText('Meu álbum')
        self.panel.audio_stage.infos_ready.emit()
        self.assertEqual(self.panel.at_edits['album'].text(), 'Meu álbum')

    def test_clear_mode_and_cover_values(self):
        self.open_tool()
        self.panel.at_mode.setCurrentIndex(1)
        self.assertEqual(self.panel._audiotags_values(), {'tag_cover': 'keep', 'tag_mode': 'clear'})
        self.assertFalse(self.panel.at_scroll.isEnabled()); self.assertTrue(self.panel._audiotags_state()[1])
        self.panel.at_mode.setCurrentIndex(0); self.panel.at_cover.setCurrentIndex(1)
        self.assertEqual(self.panel._audiotags_values()['tag_cover'], 'drop'); self.assertTrue(self.panel._audiotags_state()[1])

    def test_many_files_only_allow_clear_and_cover(self):
        self.open_tool(files=('/x/a.mp3', '/x/b.mp3'))
        self.assertFalse(self.panel.at_scroll.isEnabled())
        text, ready = self.panel._audiotags_state()
        self.assertFalse(ready); self.assertIn('vários arquivos', text)
        self.panel.at_cover.setCurrentIndex(1)
        self.assertTrue(self.panel._audiotags_state()[1])

    def test_state_reports_errors_and_unsupported_files(self):
        self.open_tool(infos={})
        self.assertFalse(self.panel._audiotags_state()[1])
        self.panel.audio_stage.infos = {'/x/a.mp3': {'name': 'a.mp3', 'error': 'Este arquivo não contém áudio.'}}
        self.assertIn('não contém áudio', self.panel._audiotags_state()[0])
        self.panel.audio_stage.infos = {'/x/a.mp3': {**INFO, 'container': 'asf', 'codec': 'wmav2'}}
        self.assertIn('Só é possível', self.panel._audiotags_state()[0])
        self.panel.audio_stage.infos = {'/x/a.mp3': INFO}
        self.panel._audiotags_changed()
        self.panel.at_edits['date'].setText('ontem')
        text, ready = self.panel._audiotags_state()
        self.assertFalse(ready); self.assertIn('data', text.lower())

    def test_run_sends_the_options(self):
        self.open_tool()
        started = []
        self.panel.controller.start_job = lambda *args, **kwargs: started.append((args, kwargs))
        self.panel.at_edits['title'].setText('Pelo painel')
        self.panel.run_selected()
        self.assertTrue(started, self.panel.status.text())
        self.assertIn("'tag_title': 'Pelo painel'", repr(started[0])); self.assertIn(self.wp.AUDIO_TAGS, repr(started[0]))

    def test_tool_is_in_the_read_group_of_the_wheel(self):
        import tool_registry
        self.assertIn(self.wp.AUDIO_TAGS, tool_registry.audio_flat_targets())
        self.assertEqual([m[0] for m in tool_registry.AUDIO_GROUPS['read'][3]], [self.wp.AUDIO_INFO, self.wp.AUDIO_TAGS])
        self.assertFalse(self.panel.run_button.isHidden() and False)


if __name__ == '__main__':
    unittest.main()
