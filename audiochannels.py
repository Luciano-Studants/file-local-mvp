"""Canais de áudio com FFmpeg (núcleo puro, sem Qt). Áudio, item 5.

Mono, estéreo (downmix de surround ou duplicação de mono), só o canal esquerdo ou só o direito. Esta operação **recodifica** o áudio no
mesmo formato do arquivo (qualidade pelos mesmos níveis da conversão); etiquetas e capa (MP3, M4A, FLAC) são mantidas.

Avisos medidos de verdade (FFmpeg `astats`, em passadas separadas que só decodificam):
- **fase:** no estéreo → mono o app compara o volume do mono com o do estéreo; se partes do som se anulam (canais em oposição de fase)
  avisa, e se o mono ficaria quase mudo **recusa** e sugere «só esquerdo» ou «só direito»;
- **clipping:** no surround → mono/estéreo mede o pico da mistura e, se passar de 0 dBFS, reduz o volume o mínimo necessário (e avisa).
Os avisos voltam do worker em `RUN_NOTES` (ver `engine`), sem mexer no formato da resposta dos jobs.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import audioconvert
import audiotags
import mediatools
from mediatools import MediaError

MODES = ('mono', 'stereo', 'left', 'right')
SUFFIXES = {'mono': 'mono', 'stereo': 'estereo', 'left': 'esquerdo', 'right': 'direito'}
OUT_CHANNELS = {'mono': 1, 'stereo': 2, 'left': 1, 'right': 1}
MODE_LABELS = {'mono': 'Mono', 'stereo': 'Estéreo', 'left': 'Só o canal esquerdo', 'right': 'Só o canal direito'}
PHASE_WARN_DB = -6.0           # mono mais de 6 dB abaixo do estéreo: avisa
PHASE_REFUSE_DB = -15.0        # mono quase mudo (mais de 15 dB abaixo): recusa
HEADROOM_DB = 0.3              # folga abaixo de 0 dBFS ao reduzir o volume
MAX_GAIN_DB = 24.0
MAX_STDERR = 256 * 1024
_LEVEL = re.compile(r'\b(Peak|RMS) level dB:[ \t]*(-?inf|-?\d+(?:\.\d+)?)[ \t\r]*$', re.M)


def options_from(job: dict) -> tuple:
    """`(modo, qualidade)`; a qualidade (baixa/média/alta) só vale para formatos com perda."""
    mode = str(job.get('chan_mode') or '')
    quality = str(job.get('audio_quality') or audioconvert.DEFAULT_QUALITY)
    if mode not in MODES:
        raise MediaError('Escolha mono, estéreo, só o canal esquerdo ou só o canal direito.')
    if quality not in audioconvert.QUALITIES:
        raise MediaError('Qualidade inválida. Escolha baixa, média ou alta.')
    return mode, quality


def plan(info: dict, mode: str) -> dict:
    """Valida o modo contra os canais do arquivo e devolve `{'filter', 'measure', 'phase', 'out'}`. Levanta `MediaError` se não fizer sentido."""
    channels = int(info.get('channels') or 0)
    if channels < 1:
        raise MediaError('Não foi possível saber quantos canais o áudio tem.')
    audiotags.kind_of(info)                       # mesmos formatos aceitos (e recusa vídeo / várias faixas)
    if mode in ('left', 'right'):
        if channels != 2:
            raise MediaError('Só o canal esquerdo ou direito só existe em áudio estéreo; este arquivo tem ' + (f'{channels} canais.' if channels != 1 else 'um canal (já é mono).'))
        return {'filter': f'pan=mono|c0=c{0 if mode == "left" else 1}', 'measure': False, 'phase': False, 'out': 1}
    if mode == 'mono':
        if channels == 1:
            raise MediaError('O áudio já é mono; não há o que converter.')
        if channels == 2:
            return {'filter': 'pan=mono|c0=0.5*c0+0.5*c1', 'measure': False, 'phase': True, 'out': 1}
        return {'filter': 'aresample=ochl=mono', 'measure': True, 'phase': False, 'out': 1}
    if channels == 2:
        raise MediaError('O áudio já é estéreo; não há o que converter.')
    if channels == 1:
        return {'filter': 'pan=stereo|c0=c0|c1=c0', 'measure': False, 'phase': False, 'out': 2}
    return {'filter': 'aresample=ochl=stereo', 'measure': True, 'phase': False, 'out': 2}


def parse_levels(text: str) -> dict:
    """Último par «Peak level / RMS level» do `astats` (dB; None se o áudio é silêncio, «-inf»)."""
    levels = {}
    for kind, value in _LEVEL.findall(text or ''):
        levels[kind.lower()] = None if value.endswith('inf') else float(value)
    return levels


def measure_args(source: str, audio_filter: str) -> list:
    return ['-nostdin', '-v', 'info', '-nostats', '-protocol_whitelist', 'file', '-format_whitelist', ','.join(mediatools.INPUT_FORMATS), '-i', 'file:' + source,
            '-map', '0:a:0', '-vn', '-af', (audio_filter + ',' if audio_filter else '') + 'astats=measure_perchannel=none:measure_overall=Peak_level+RMS_level', '-f', 'null', '-']


def measure(exe: str, source: str, audio_filter: str) -> dict:
    flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    try:
        done = subprocess.run([exe, '-hide_banner', *measure_args(source, audio_filter)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                              timeout=audioconvert.CONVERT_TIMEOUT, env=mediatools._clean_env(), creationflags=flags, shell=False)
    except subprocess.TimeoutExpired:
        raise MediaError('A análise do áudio demorou demais e foi interrompida; tente um arquivo menor.') from None
    except OSError:
        raise MediaError('Não foi possível executar o FFmpeg.') from None
    if done.returncode != 0:
        raise MediaError('O FFmpeg não conseguiu analisar este arquivo. Ele pode estar corrompido ou usar um formato sem suporte.')
    return parse_levels(done.stderr[-MAX_STDERR:].decode('utf-8', errors='replace'))


def build_args(source: str, target: str, kind: str, quality: str, audio_filter: str, info: dict) -> list:
    muxer, _suffix, _stream_tags, cover_stream, _label = audiotags.KINDS[kind]
    spec = audioconvert.FORMATS[kind]
    args = ['-nostdin', '-v', 'error', '-protocol_whitelist', 'file', '-format_whitelist', ','.join(mediatools.INPUT_FORMATS), '-i', 'file:' + source, '-map', '0:a:0']
    if cover_stream and info.get('has_cover'):
        args += ['-map', '0:v:0?']
    args += ['-map_chapters', '-1', '-map_metadata', '0', '-map_metadata:s:a:0', '0:s:a:0', '-af', audio_filter, '-c:a', spec['encoder'], *audioconvert.QUALITY_ARGS.get(kind, {}).get(quality, [])]
    if cover_stream and info.get('has_cover'):
        args += ['-c:v', 'copy']
    if kind == 'mp3':
        args += ['-id3v2_version', '3']
    args += ['-fflags', '+bitexact', '-fs', str(audioconvert.MAX_OUTPUT_BYTES - 1024 * 1024), '-f', muxer, '-n', 'file:' + target]
    return args


def notes(info: dict | None, mode: str, quality: str) -> list:
    """Frases (português) sobre o que a operação muda; vale antes e depois (os avisos medidos vêm em `RUN_NOTES`)."""
    out = [f'Resultado: {MODE_LABELS[mode]}. O áudio é recodificado no mesmo formato do arquivo.']
    kind = None
    if info:
        try:
            kind = audiotags.kind_of(info)
        except MediaError as error:
            out.append(str(error))
    if kind:
        spec = audioconvert.FORMATS[kind]
        if spec['lossy']:
            out.append(f'{spec["label"]} é um formato com perda: recodificar perde um pouco de qualidade (≈ {audioconvert.BITRATES[kind][quality]} kbps).')
        elif kind in ('wav', 'aiff'):
            out.append(f'{spec["label"]} é regravado com 16 bits (arquivos de 24 bits ou decimais perdem profundidade).')
        else:
            out.append('FLAC: sem perda de qualidade na recodificação.')
        if info.get('has_cover') and kind in ('ogg', 'opus'):
            out.append(f'A capa embutida de arquivos {spec["label"]} não é copiada (limite do FFmpeg).')
        if info.get('chapters'):
            out.append('Os capítulos não são copiados.')
    if mode == 'mono':
        out.append('Mistura dos canais em um só. Se os canais estiverem em oposição de fase, parte do som some: o app mede isso e avisa.')
    elif mode == 'stereo':
        out.append('Surround vira estéreo pela mistura padrão do FFmpeg (o app mede o pico e reduz o volume só se passar de 0 dBFS); mono vira estéreo duplicando o canal, sem ganho real.')
    else:
        out.append('Só o canal escolhido é mantido; o outro é descartado.')
    out.append('As etiquetas são mantidas quando o formato aceita.')
    out.append(f'O arquivo original não é alterado; a cópia ganha o sufixo «-{SUFFIXES[mode]}».')
    return out


def _db(value) -> str:
    return 'silêncio' if value is None else f'{value:.1f} dB'.replace('.', ',')


def apply(source: Path, stage: Path, job: dict) -> dict:
    """Grava em `stage` o áudio com os canais pedidos. Devolve `{'suffix', 'name', 'notes'}` (avisos medidos, em português)."""
    mode, quality = options_from(job)
    exe = mediatools.find_tool('ffmpeg')
    if not exe or not mediatools.find_tool('ffprobe'):
        raise MediaError('O FFmpeg não foi encontrado neste computador. Instale-o (veja docs/DEPENDENCIAS.md) e tente de novo.')
    info = mediatools.probe(source)
    kind = audiotags.kind_of(info)
    chosen = plan(info, mode)
    spec = audioconvert.FORMATS[kind]
    build = mediatools.build_info()
    mediatools.require_filters('channels')
    if build and build.get('encoders') is not None and not set(mediatools.OUTPUT_ENCODERS[kind]) & set(build['encoders']):
        raise MediaError(f'Este FFmpeg não tem o codificador de {spec["label"]}.')
    estimate = audioconvert.estimate_bytes(kind, quality, {**info, 'channels': chosen['out']})
    if info['duration'] <= 0 and not spec['lossy']:
        raise MediaError('Não foi possível saber a duração do áudio; para evitar um arquivo gigante, a operação foi recusada.')
    if estimate > audioconvert.MAX_OUTPUT_BYTES * audioconvert.SAFETY_MARGIN:
        raise MediaError('A saída passaria do limite de 512 MiB; escolha um arquivo menor.')
    if stage.exists():
        raise MediaError('A pasta de preparo já tem um arquivo de saída.')
    source_path = str(source.resolve())
    warnings = []
    audio_filter = chosen['filter']
    if chosen['phase']:
        original = measure(exe, source_path, '')
        mixed = measure(exe, source_path, audio_filter)
        if original.get('rms') is not None:
            delta = float('-inf') if mixed.get('rms') is None else mixed['rms'] - original['rms']
            if delta < PHASE_REFUSE_DB:
                raise MediaError(f'Os dois canais estão em oposição de fase: o mono ficaria ' + ('completamente mudo' if delta == float('-inf') else f'{_db(abs(delta))} mais baixo, quase mudo') + '. Escolha «Só o canal esquerdo» ou «Só o canal direito».')
            if delta < PHASE_WARN_DB:
                warnings.append(f'Atenção (fase): o mono ficou {_db(abs(delta))} mais baixo que o estéreo, porque parte do som se anula entre os canais. Se soar fraco, use «Só o canal esquerdo» ou «Só o canal direito».')
    if chosen['measure']:
        levels = measure(exe, source_path, audio_filter)
        peak = levels.get('peak')
        if peak is not None and peak > -HEADROOM_DB:
            gain = -(peak + HEADROOM_DB)
            if gain < -MAX_GAIN_DB:
                raise MediaError('A mistura estoura o limite do áudio por muito; a operação foi recusada para não distorcer.')
            audio_filter += f',volume={gain:.2f}dB'
            warnings.append(f'Atenção (clipping): a mistura passaria de 0 dBFS (pico de {_db(peak)}); o volume foi reduzido em {_db(abs(gain))} para não distorcer.')
    audioconvert._run(exe, build_args(source_path, str(stage.resolve()), kind, quality, audio_filter, info))
    if not stage.is_file() or stage.is_symlink() or stage.stat().st_size == 0:
        raise MediaError('A operação não gerou nenhum arquivo.')
    try:
        _verify(info, mediatools.probe(stage), kind, chosen['out'])
    except MediaError:
        stage.unlink(missing_ok=True)
        raise
    return {'suffix': audiotags.KINDS[kind][1], 'name': SUFFIXES[mode], 'notes': warnings}


def _verify(before: dict, after: dict, kind: str, channels: int) -> None:
    spec = audioconvert.FORMATS[kind]
    if after['codec'] not in spec['codecs'] or after['audio_streams'] != 1 or after['has_video']:
        raise MediaError('A conferência do arquivo novo falhou (formato inesperado); nada foi salvo.')
    if after['channels'] != channels:
        raise MediaError(f'A conferência do arquivo novo falhou (esperava {channels} canal(is), saiu {after["channels"]}); nada foi salvo.')
    if before['duration'] > 0 and abs(after['duration'] - before['duration']) > max(1.0, before['duration'] * audioconvert.DURATION_TOLERANCE):
        raise MediaError('A conferência do arquivo novo falhou (a duração difere da original); nada foi salvo.')
    for key, value in (before.get('tags') or {}).items():
        if (after.get('tags') or {}).get(key) != value:
            raise MediaError(f'O formato {spec["label"]} perderia o campo «{mediatools.TAG_LABELS.get(key, key)}» ao ser regravado; nada foi salvo.')
