"""Etiquetas (metadados) de áudio com FFmpeg (núcleo puro, sem Qt). Áudio, item 4.

O áudio é **copiado sem recodificar** (`-c copy`): só o texto das etiquetas e a capa mudam. Só os campos de `mediatools.TAG_KEYS`
podem ser editados (valores curtos e validados); os demais campos do arquivo são mantidos, ou todos são removidos em «Limpar tudo».
Os mesmos cuidados da conversão valem aqui: sem shell, `-protocol_whitelist file`, `-format_whitelist`, `-n`, tempo máximo e conferência
do resultado com o ffprobe antes de publicar.
"""
from __future__ import annotations

import re
from pathlib import Path

import audioconvert
import mediatools
from mediatools import MediaError

TAG_KEYS = mediatools.TAG_KEYS
MAX_VALUE = mediatools.MAX_TAG                 # caracteres por campo
MODES = ('edit', 'clear')
COVER_MODES = ('keep', 'drop')
MAX_FILE_BYTES = audioconvert.MAX_OUTPUT_BYTES - 2 * 1024 * 1024       # a cópia precisa caber no limite de saída
DURATION_TOLERANCE = 0.02
PREFIX = 'tag_'
FIELD_PATTERNS = {
    'track': (re.compile(r'^\d{1,4}(/\d{1,4})?$'), 'A faixa deve ser um número ou «n/total» (ex.: 3 ou 3/12).'),
    'disc': (re.compile(r'^\d{1,3}(/\d{1,3})?$'), 'O disco deve ser um número ou «n/total» (ex.: 1 ou 1/2).'),
    'date': (re.compile(r'^\d{4}(-\d{2}(-\d{2})?)?$'), 'A data deve ser AAAA, AAAA-MM ou AAAA-MM-DD.'),
}
# tipo → (muxer, sufixo, etiquetas no fluxo?, capa como fluxo de imagem?, rótulo)
KINDS = {
    'mp3': ('mp3', 'mp3', False, True, 'MP3'), 'm4a': ('ipod', 'm4a', False, True, 'M4A'), 'flac': ('flac', 'flac', False, True, 'FLAC'),
    'ogg': ('ogg', 'ogg', True, False, 'OGG'), 'opus': ('opus', 'opus', True, False, 'Opus'),
    'wav': ('wav', 'wav', False, False, 'WAV'), 'aiff': ('aiff', 'aiff', False, False, 'AIFF'),
}


def kind_of(info: dict) -> str:
    """Tipo de arquivo editável a partir do que o ffprobe disse (nunca da extensão). Levanta `MediaError` se não houver suporte."""
    container, codec = str(info.get('container', '')), str(info.get('codec', ''))
    if info.get('has_video'):
        raise MediaError('Este arquivo é um vídeo; a edição de etiquetas vale só para arquivos de áudio.')
    if int(info.get('audio_streams') or 1) > 1:
        raise MediaError('O arquivo tem mais de uma faixa de áudio; para não perder nenhuma, ele não é reescrito.')
    if container == 'mp3':
        return 'mp3'
    if container.startswith('mov,mp4') and codec in ('aac', 'alac'):
        return 'm4a'
    if container == 'flac':
        return 'flac'
    if container == 'ogg' and codec == 'vorbis':
        return 'ogg'
    if container == 'ogg' and codec == 'opus':
        return 'opus'
    if container == 'wav' and codec.startswith('pcm_'):
        return 'wav'
    if container == 'aiff':
        return 'aiff'
    raise MediaError('Só é possível editar etiquetas de MP3, M4A, FLAC, OGG, Opus, WAV e AIFF.')


def clean_value(key: str, raw) -> str:
    if not isinstance(raw, str):
        raise MediaError('Valor de etiqueta inválido.')
    value = raw.strip()
    if len(value) > MAX_VALUE:
        raise MediaError(f'O campo «{mediatools.TAG_LABELS.get(key, key)}» passa de {MAX_VALUE} caracteres.')
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise MediaError(f'O campo «{mediatools.TAG_LABELS.get(key, key)}» tem caracteres de controle.')
    if value and key in FIELD_PATTERNS and not FIELD_PATTERNS[key][0].match(value):
        raise MediaError(FIELD_PATTERNS[key][1])
    return value


def options_from(job: dict) -> tuple:
    """`(modo, capa, edições)`; edições = só os campos presentes no job (valor vazio = remover o campo)."""
    mode = str(job.get('tag_mode') or 'edit')
    cover = str(job.get('tag_cover') or 'keep')
    if mode not in MODES:
        raise MediaError('Modo de etiquetas inválido. Escolha editar ou limpar tudo.')
    if cover not in COVER_MODES:
        raise MediaError('Opção de capa inválida. Escolha manter ou remover.')
    edits = {key: clean_value(key, job[PREFIX + key]) for key in TAG_KEYS if PREFIX + key in job}
    if mode == 'clear' and edits:
        raise MediaError('«Limpar tudo» não combina com edição de campos; escolha uma das duas coisas.')
    if mode == 'edit' and not edits and cover == 'keep':
        raise MediaError('Nada para mudar: edite algum campo, remova a capa ou escolha «Limpar tudo».')
    return mode, cover, edits


def build_args(source: str, target: str, kind: str, mode: str, cover: str, edits: dict) -> list:
    muxer, _suffix, stream_tags, cover_stream, _label = KINDS[kind]
    args = ['-nostdin', '-v', 'error', '-protocol_whitelist', 'file', '-format_whitelist', ','.join(mediatools.INPUT_FORMATS), '-i', 'file:' + source,
            '-map', '0:a:0']
    if cover_stream and cover == 'keep' and mode == 'edit':
        args += ['-map', '0:v:0?']
    args += ['-c', 'copy']
    if mode == 'clear':
        args += ['-map_metadata', '-1', '-map_metadata:s:a:0', '-1', '-map_chapters', '-1']
    else:
        args += ['-map_metadata', '0', '-map_metadata:s:a:0', '0:s:a:0']
        scope = '-metadata:s:a:0' if stream_tags else '-metadata'
        for key in TAG_KEYS:
            if key in edits:
                args += [scope, f'{key}={edits[key]}']
        if cover == 'drop' and stream_tags:
            args += [scope, f'{mediatools.COVER_TAG}=']
    if kind == 'mp3':
        args += ['-id3v2_version', '3']
    args += ['-fflags', '+bitexact', '-fs', str(audioconvert.MAX_OUTPUT_BYTES - 1024 * 1024), '-f', muxer, '-n', 'file:' + target]
    return args


def notes(info: dict | None, mode: str, cover: str, edits: dict) -> list:
    """Frases (português) sobre o que a operação muda; `info` pode ser None."""
    out = ['O áudio é copiado sem recodificar: nenhuma perda de qualidade, só o texto das etiquetas muda.']
    if mode == 'clear':
        out.append('Todas as etiquetas, a capa e os capítulos são removidos.')
    else:
        if edits:
            out.append('Campos editados: ' + ', '.join(mediatools.TAG_LABELS.get(key, key) for key in TAG_KEYS if key in edits) + '. Campo deixado em branco = removido.')
            out.append('Os outros campos do arquivo são mantidos, inclusive os que o app não edita.')
        if cover == 'drop':
            out.append('A capa embutida é removida.')
    if info:
        try:
            kind = kind_of(info)
        except MediaError as error:
            out.append(str(error))
        else:
            if kind in ('wav', 'aiff') and edits:
                out.append(f'{KINDS[kind][4]} guarda poucos campos; se o formato não aceitar algum, nada é salvo e o app avisa qual.')
            if cover == 'drop' and not KINDS[kind][2] and not KINDS[kind][3]:
                out.append(f'{KINDS[kind][4]} não tem capa embutida.')
            if kind in ('ogg', 'opus') and cover == 'keep':
                out.append(f'{KINDS[kind][4]} com capa embutida só pode ser reescrito removendo a capa (limite do FFmpeg).')
    out.append('O arquivo original não é alterado; a cópia ganha o sufixo «-etiquetas».')
    return out


def _verify(before: dict, after: dict, kind: str, mode: str, cover: str, edits: dict) -> None:
    label = KINDS[kind][4]
    if after['codec'] != before['codec'] or after['audio_streams'] != 1 or after['has_video']:
        raise MediaError('A conferência do arquivo novo falhou (formato inesperado); nada foi salvo.')
    if before['duration'] > 0 and abs(after['duration'] - before['duration']) > max(1.0, before['duration'] * DURATION_TOLERANCE):
        raise MediaError('A conferência do arquivo novo falhou (a duração difere da original); nada foi salvo.')
    tags = after.get('tags') or {}
    if mode == 'clear':
        if tags or after.get('extra_tags') or after.get('has_cover'):
            raise MediaError('A conferência falhou: ainda restaram etiquetas ou capa no arquivo novo; nada foi salvo.')
        return
    for key, value in edits.items():
        if value and tags.get(key) != value:
            raise MediaError(f'O formato {label} não guarda o campo «{mediatools.TAG_LABELS.get(key, key)}»; nada foi salvo. Deixe esse campo em branco ou converta para outro formato.')
        if not value and key in tags:
            raise MediaError(f'Não foi possível remover o campo «{mediatools.TAG_LABELS.get(key, key)}» neste formato; nada foi salvo.')
    for key, value in (before.get('tags') or {}).items():
        if key not in edits and tags.get(key) != value:
            raise MediaError(f'O formato {label} perderia o campo «{mediatools.TAG_LABELS.get(key, key)}» ao ser reescrito; nada foi salvo.')
    if cover == 'drop' and after.get('has_cover'):
        raise MediaError('A capa não pôde ser removida neste arquivo; nada foi salvo.')
    if cover == 'keep' and before.get('has_cover') and not after.get('has_cover'):
        if kind in ('ogg', 'opus'):
            raise MediaError(f'O FFmpeg não consegue regravar a capa de arquivos {label}; para editar as etiquetas escolha «Remover capa». Nada foi salvo.')
        raise MediaError('A capa se perderia ao reescrever este arquivo; nada foi salvo.')


def apply(source: Path, stage: Path, job: dict) -> dict:
    """Grava em `stage` uma cópia de `source` com as etiquetas pedidas. Devolve `{'suffix', 'input', 'output'}`."""
    mode, cover, edits = options_from(job)
    exe = mediatools.find_tool('ffmpeg')
    if not exe or not mediatools.find_tool('ffprobe'):
        raise MediaError('O FFmpeg não foi encontrado neste computador. Instale-o (veja docs/DEPENDENCIAS.md) e tente de novo.')
    if source.stat().st_size > MAX_FILE_BYTES:
        raise MediaError('O arquivo é grande demais para ser reescrito (limite de cerca de 510 MiB).')
    info = mediatools.probe(source)
    kind = kind_of(info)
    if stage.exists():
        raise MediaError('A pasta de preparo já tem um arquivo de saída.')
    audioconvert._run(exe, build_args(str(source.resolve()), str(stage.resolve()), kind, mode, cover, edits))
    if not stage.is_file() or stage.is_symlink() or stage.stat().st_size == 0:
        raise MediaError('A operação não gerou nenhum arquivo.')
    try:
        _verify(info, mediatools.probe(stage), kind, mode, cover, edits)
    except MediaError:
        stage.unlink(missing_ok=True)
        raise
    return {'suffix': KINDS[kind][1], 'input': info, 'kind': kind}
