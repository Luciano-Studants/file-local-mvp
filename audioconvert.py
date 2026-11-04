"""Conversão de áudio com FFmpeg (núcleo puro, sem Qt). Áudio, item 3.

O FFmpeg roda como programa externo: sem shell, sem teclado, `-protocol_whitelist file`, só demuxers de áudio/vídeo conhecidos
(`-format_whitelist`), entrada sempre como `file:<caminho absoluto>`, tempo máximo e tamanho máximo de saída. A extensão nunca decide o
formato. O resultado é gravado na pasta de preparo do job e conferido com o ffprobe (codec, quantidade de fluxos, duração) antes de ser publicado.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import mediatools
from mediatools import MediaError

CONVERT_TIMEOUT = 800                  # segundos de relógio (o runner dá 900 aos alvos longos)
MAX_STDERR = 64 * 1024                 # bytes de diagnóstico aceitos
MAX_OUTPUT_BYTES = 512 * 1024 * 1024   # mesmo limite do motor (`engine.MAX_OUTPUT`)
SAFETY_MARGIN = 0.95                   # a estimativa de WAV/AIFF/FLAC precisa caber com folga
DURATION_TOLERANCE = 0.02              # 2 % (ou 1 s) de diferença entre entrada e saída
DEFAULT_FORMAT = 'mp3'
DEFAULT_QUALITY = 'medium'
DEFAULT_TAGS = 'keep'
QUALITIES = ('low', 'medium', 'high')
TAG_MODES = ('keep', 'drop')

INPUT_FORMATS = mediatools.INPUT_FORMATS      # demuxers aceitos na entrada (ver mediatools)

# formato → sufixo, codificador, muxer, codecs esperados na saída, rótulo, com perda?, máximo de canais
FORMATS = {
    'mp3': {'suffix': 'mp3', 'encoder': 'libmp3lame', 'muxer': 'mp3', 'codecs': ('mp3',), 'label': 'MP3', 'lossy': True, 'max_channels': 2},
    'm4a': {'suffix': 'm4a', 'encoder': 'aac', 'muxer': 'ipod', 'codecs': ('aac',), 'label': 'M4A (AAC)', 'lossy': True, 'max_channels': 8},
    'flac': {'suffix': 'flac', 'encoder': 'flac', 'muxer': 'flac', 'codecs': ('flac',), 'label': 'FLAC', 'lossy': False, 'max_channels': 8},
    'ogg': {'suffix': 'ogg', 'encoder': 'libvorbis', 'muxer': 'ogg', 'codecs': ('vorbis',), 'label': 'OGG (Vorbis)', 'lossy': True, 'max_channels': 8},
    'opus': {'suffix': 'opus', 'encoder': 'libopus', 'muxer': 'opus', 'codecs': ('opus',), 'label': 'Opus', 'lossy': True, 'max_channels': 8},
    'wav': {'suffix': 'wav', 'encoder': 'pcm_s16le', 'muxer': 'wav', 'codecs': ('pcm_s16le',), 'label': 'WAV (16 bits)', 'lossy': False, 'max_channels': 8},
    'aiff': {'suffix': 'aiff', 'encoder': 'pcm_s16be', 'muxer': 'aiff', 'codecs': ('pcm_s16be',), 'label': 'AIFF (16 bits)', 'lossy': False, 'max_channels': 8},
}
# qualidade → argumentos do codificador (só os formatos com perda; FLAC/WAV/AIFF ignoram a qualidade)
QUALITY_ARGS = {
    'mp3': {'low': ['-b:a', '128k'], 'medium': ['-b:a', '192k'], 'high': ['-b:a', '320k']},
    'm4a': {'low': ['-b:a', '96k'], 'medium': ['-b:a', '160k'], 'high': ['-b:a', '256k']},
    'ogg': {'low': ['-q:a', '3'], 'medium': ['-q:a', '5'], 'high': ['-q:a', '8']},
    'opus': {'low': ['-b:a', '64k'], 'medium': ['-b:a', '96k'], 'high': ['-b:a', '160k']},
}
BITRATES = {'mp3': {'low': 128, 'medium': 192, 'high': 320}, 'm4a': {'low': 96, 'medium': 160, 'high': 256},
            'ogg': {'low': 112, 'medium': 160, 'high': 256}, 'opus': {'low': 64, 'medium': 96, 'high': 160}}


def options_from(job: dict) -> tuple:
    """Lê `audio_format`, `audio_quality` e `audio_tags` do job, com valores padrão; recusa o que não existe."""
    fmt = str(job.get('audio_format') or DEFAULT_FORMAT)
    quality = str(job.get('audio_quality') or DEFAULT_QUALITY)
    tags = str(job.get('audio_tags') or DEFAULT_TAGS)
    if fmt not in FORMATS:
        raise MediaError('Formato de saída inválido. Escolha MP3, M4A, FLAC, OGG, Opus, WAV ou AIFF.')
    if quality not in QUALITIES:
        raise MediaError('Qualidade inválida. Escolha baixa, média ou alta.')
    if tags not in TAG_MODES:
        raise MediaError('Opção de etiquetas inválida. Escolha manter ou remover.')
    return fmt, quality, tags


def estimate_bytes(fmt: str, quality: str, info: dict) -> int:
    """Tamanho máximo provável da saída (0 se a duração for desconhecida). FLAC usa o tamanho do WAV como teto."""
    duration = float(info.get('duration') or 0)
    if duration <= 0:
        return 0
    if fmt in BITRATES:
        return int(duration * BITRATES[fmt][quality] * 1000 / 8) + 65536
    channels = max(1, min(int(info.get('channels') or 2), FORMATS[fmt]['max_channels']))
    rate = int(info.get('sample_rate') or 48000)
    return int(duration * rate * channels * 2) + 65536


def build_args(source: str, target: str, fmt: str, quality: str, tags: str, info: dict) -> list:
    """Argumentos do ffmpeg (sem o executável). `source` e `target` são caminhos absolutos."""
    spec = FORMATS[fmt]
    args = ['-nostdin', '-v', 'error', '-protocol_whitelist', 'file', '-format_whitelist', ','.join(INPUT_FORMATS), '-i', 'file:' + source,
            '-map', '0:a:0', '-vn', '-sn', '-dn', '-map_chapters', '-1']
    if tags == 'keep':
        args += ['-map_metadata', '0', '-map_metadata:s:a:0', '0:s:a:0']
    else:
        args += ['-map_metadata', '-1', '-map_metadata:s:a:0', '-1']
    args += ['-c:a', spec['encoder'], *QUALITY_ARGS.get(fmt, {}).get(quality, [])]
    if int(info.get('channels') or 0) > spec['max_channels']:
        args += ['-ac', str(spec['max_channels'])]
    if fmt == 'mp3':
        args += ['-id3v2_version', '3']
    args += ['-fflags', '+bitexact', '-fs', str(MAX_OUTPUT_BYTES - 1024 * 1024), '-f', spec['muxer'], '-n', 'file:' + target]
    return args


def loss_notes(info: dict | None, fmt: str, quality: str, tags: str) -> list:
    """Frases (português) sobre o que a conversão muda ou perde. `info` pode ser None (arquivo ilegível)."""
    spec = FORMATS[fmt]
    notes = []
    if spec['lossy']:
        rate = f' ({BITRATES[fmt][quality]} kbps aproximados)'
        notes.append(f'{spec["label"]} é um formato com perda: o áudio é recodificado e não volta ao original{rate}.')
    elif fmt in ('wav', 'aiff'):
        notes.append(f'{spec["label"]} grava o áudio sem compressão e sem perda a partir do que foi decodificado; arquivos de 24 bits ou decimais são gravados com 16 bits, e o arquivo fica muito maior.')
    else:
        notes.append('FLAC não perde qualidade em relação ao áudio decodificado; se a origem tinha perda (MP3, AAC, Opus), ela continua lá.')
    if info:
        if info.get('has_video'):
            notes.append('Somente a faixa de áudio é extraída; o vídeo não vai para o arquivo novo.')
        if int(info.get('audio_streams') or 1) > 1:
            notes.append('O arquivo tem mais de uma faixa de áudio: só a primeira é convertida.')
        if int(info.get('channels') or 0) > spec['max_channels']:
            notes.append(f'{spec["label"]} aceita até {spec["max_channels"]} canais: o áudio será mixado para estéreo.')
        if info.get('has_cover'):
            notes.append('A capa embutida não é copiada.')
        if info.get('chapters'):
            notes.append('Os capítulos não são copiados.')
        if info.get('codec') and info['codec'] in spec['codecs'] and spec['lossy']:
            notes.append('A origem já está neste formato: converter de novo perde qualidade sem ganho de tamanho garantido.')
    notes.append('As etiquetas (título, artista, álbum…) são copiadas quando o formato novo as aceita.' if tags == 'keep' else 'As etiquetas (título, artista, álbum…) são removidas.')
    notes.append('O arquivo original não é alterado; a cópia convertida ganha o sufixo «-convertido».')
    return notes


def _run(exe: str, args: list) -> None:
    flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    try:
        done = subprocess.run([exe, '-hide_banner', *args], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                              timeout=CONVERT_TIMEOUT, env=mediatools._clean_env(), creationflags=flags, shell=False)
    except subprocess.TimeoutExpired:
        raise MediaError('A conversão demorou demais e foi interrompida; tente um arquivo menor.') from None
    except OSError:
        raise MediaError('Não foi possível executar o FFmpeg.') from None
    if done.returncode != 0 or len(done.stderr or b'') > MAX_STDERR:
        raise MediaError('O FFmpeg não conseguiu converter este arquivo. Ele pode estar corrompido ou usar um formato sem suporte.')


def convert(source: Path, stage: Path, job: dict) -> dict:
    """Converte `source` em `stage` (caminho que ainda não existe, na pasta de preparo). Devolve `{'format', 'suffix', 'input', 'output'}`."""
    fmt, quality, tags = options_from(job)
    spec = FORMATS[fmt]
    exe = mediatools.find_tool('ffmpeg')
    if not exe or not mediatools.find_tool('ffprobe'):
        raise MediaError('O FFmpeg não foi encontrado neste computador. Instale-o (veja docs/DEPENDENCIAS.md) e tente de novo.')
    build = mediatools.build_info()
    if build and build.get('encoders') is not None and not set(mediatools.OUTPUT_ENCODERS[fmt]) & set(build['encoders']):
        raise MediaError(f'Este FFmpeg não tem o codificador de {spec["label"]}. Escolha outro formato.')
    info = mediatools.probe(source)
    if info['duration'] <= 0 and fmt in ('wav', 'aiff', 'flac'):
        raise MediaError('Não foi possível saber a duração do áudio; para evitar um arquivo gigante, escolha MP3, M4A, OGG ou Opus.')
    estimate = estimate_bytes(fmt, quality, info)
    if estimate > MAX_OUTPUT_BYTES * SAFETY_MARGIN:
        raise MediaError(f'A saída em {spec["label"]} passaria do limite de 512 MiB; escolha um formato comprimido (MP3, M4A, OGG ou Opus).')
    if stage.exists():
        raise MediaError('A pasta de preparo já tem um arquivo de saída.')
    _run(exe, build_args(str(source.resolve()), str(stage.resolve()), fmt, quality, tags, info))
    if not stage.is_file() or stage.is_symlink() or stage.stat().st_size == 0:
        raise MediaError('A conversão não gerou nenhum arquivo.')
    if stage.stat().st_size >= MAX_OUTPUT_BYTES - 1024 * 1024:
        stage.unlink(missing_ok=True)
        raise MediaError('A saída passou do limite de 512 MiB e foi descartada.')
    out = mediatools.probe(stage)
    if out['codec'] not in spec['codecs'] or out['audio_streams'] != 1 or out['has_video']:
        stage.unlink(missing_ok=True)
        raise MediaError('A conferência do arquivo convertido falhou (formato inesperado); nada foi salvo.')
    if info['duration'] > 0 and abs(out['duration'] - info['duration']) > max(1.0, info['duration'] * DURATION_TOLERANCE):
        stage.unlink(missing_ok=True)
        raise MediaError('A conferência do arquivo convertido falhou (a duração difere da original); nada foi salvo.')
    return {'format': fmt, 'suffix': spec['suffix'], 'input': info, 'output': out}
