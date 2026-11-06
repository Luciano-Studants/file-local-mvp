"""Comprimir áudio com FFmpeg (núcleo puro, sem Qt). Áudio, item 8.

Recodifica em MP3, M4A (AAC), OGG (Vorbis) ou Opus com um **bitrate-alvo** (kbps) ou, como *melhor esforço*, um **tamanho-alvo**: o app
calcula o bitrate que caberia (duração × bitrate), grava, mede o arquivo e, se passou do alvo, tenta uma única vez com um bitrate menor;
se ainda assim passar (ou o bitrate necessário for baixo demais para o formato) o app **avisa** o tamanho real em vez de prometer.
A capa embutida e os capítulos não são copiados (a capa pode ser a maior parte do arquivo); as etiquetas são mantidas a pedido.
Se o arquivo novo não ficasse menor que o original, ele é descartado e o app explica (comprimir de novo algo já pequeno só perde qualidade).
Mesmos cuidados das outras ferramentas de áudio: sem shell, `-protocol_whitelist file`, `-format_whitelist`, `-n`, tempo máximo, conferência.
"""
from __future__ import annotations

from pathlib import Path

import audioconvert
import mediatools
from mediatools import MediaError

MODES = ('bitrate', 'size')
FORMATS = ('mp3', 'm4a', 'ogg', 'opus')
DEFAULT_FORMAT = 'mp3'
DEFAULT_KBPS = 128
KBPS_CHOICES = (32, 48, 64, 96, 128, 160, 192, 256, 320)
LIMITS = {'mp3': (32, 320), 'm4a': (32, 320), 'ogg': (32, 256), 'opus': (16, 256)}        # kbps aceitos por formato (estéreo ou mono)
MIN_SIZE_KB = 16
MAX_SIZE_KB = 512 * 1024
OVERHEAD_BYTES = 16 * 1024          # contêiner e etiquetas
SIZE_SLACK = 0.98                   # o bitrate calculado deixa 2 % de folga
RETRY_SLACK = 0.99


def options_from(job: dict) -> dict:
    """`{'mode','format','kbps','size_kb','mono','tags'}`; recusa o que não existe."""
    mode = str(job.get('comp_mode') or 'bitrate')
    fmt = str(job.get('audio_format') or DEFAULT_FORMAT)
    mono = str(job.get('comp_mono') or 'no')
    tags = str(job.get('audio_tags') or audioconvert.DEFAULT_TAGS)
    if mode not in MODES:
        raise MediaError('Modo inválido. Escolha bitrate ou tamanho-alvo.')
    if fmt not in FORMATS:
        raise MediaError('Comprimir usa formatos com perda: MP3, M4A, OGG ou Opus (para FLAC, WAV ou AIFF use «Converter»).')
    if mono not in ('yes', 'no'):
        raise MediaError('Opção de canais inválida. Escolha manter ou mono.')
    if tags not in audioconvert.TAG_MODES:
        raise MediaError('Opção de etiquetas inválida. Escolha manter ou remover.')
    kbps = job.get('comp_kbps', DEFAULT_KBPS)
    size_kb = job.get('comp_size_kb', 0)
    for value in (kbps, size_kb):
        if isinstance(value, bool) or not isinstance(value, int):
            raise MediaError('Bitrate e tamanho devem ser números inteiros.')
    low, high = LIMITS[fmt]
    label = audioconvert.FORMATS[fmt]['label']
    if mode == 'bitrate' and not low <= kbps <= high:
        raise MediaError(f'{label} aceita de {low} a {high} kbps; escolha um valor nessa faixa.')
    if mode == 'size' and not MIN_SIZE_KB <= size_kb <= MAX_SIZE_KB:
        raise MediaError(f'O tamanho-alvo deve ficar entre {MIN_SIZE_KB} KB e 512 MB.')
    return {'mode': mode, 'format': fmt, 'kbps': kbps, 'size_kb': size_kb, 'mono': mono == 'yes', 'tags': tags}


def kbps_for_size(size_kb: int, duration: float) -> float:
    """Bitrate (kbps, fracionário) que, em `duration` s, cabe em `size_kb` KB deixando folga."""
    if duration <= 0:
        raise MediaError('Não foi possível saber a duração do áudio; o tamanho-alvo não pode ser calculado. Use o modo bitrate.')
    payload = size_kb * 1024 - OVERHEAD_BYTES
    return max(0.0, payload * 8 / duration / 1000 * SIZE_SLACK)


def plan_bitrate(options: dict, info: dict, source_size: int) -> tuple:
    """`(kbps, nota|None)`. Levanta `MediaError` se não houver o que comprimir."""
    fmt, label = options['format'], audioconvert.FORMATS[options['format']]['label']
    low, high = LIMITS[fmt]
    duration = float(info.get('duration') or 0)
    note = None
    if options['mode'] == 'size':
        target = options['size_kb'] * 1024
        if source_size and target >= source_size:
            raise MediaError(f'O arquivo já tem {mediatools.human_size(source_size)}, que cabe no alvo de {mediatools.human_size(target)}; não há o que comprimir.')
        wanted = kbps_for_size(options['size_kb'], duration)
        if wanted < low:
            raise MediaError(f'Para caber em {mediatools.human_size(target)} o áudio teria ≈ {wanted:.0f} kbps, abaixo do mínimo de {low} kbps do {label}. '
                             f'Escolha um tamanho maior' + (', o formato Opus (aceita 16 kbps) ou o modo mono.' if fmt != 'opus' else ' ou o modo mono.'))
        kbps = int(wanted)
        if kbps > high:
            kbps = high
            note = f'O alvo de {mediatools.human_size(target)} permitiria mais que {high} kbps (máximo do {label}); o arquivo ficará menor que o alvo.'
        kbps = max(low, kbps)
    else:
        kbps = options['kbps']
        current = int(info.get('stream_bit_rate') or info.get('bit_rate') or 0) // 1000
        if info.get('codec') in ('mp3', 'aac', 'vorbis', 'opus') and current and kbps >= current:
            raise MediaError(f'O áudio já tem cerca de {current} kbps; recodificar a {kbps} kbps não reduziria o tamanho. Escolha um bitrate menor.')
    return kbps, note


def out_channels(options: dict, info: dict) -> int:
    channels = int(info.get('channels') or 2)
    return 1 if options['mono'] else min(channels, audioconvert.FORMATS[options['format']]['max_channels'])


def build_args(source: str, target: str, options: dict, kbps: int, info: dict) -> list:
    spec = audioconvert.FORMATS[options['format']]
    args = ['-nostdin', '-v', 'error', '-protocol_whitelist', 'file', '-format_whitelist', ','.join(audioconvert.INPUT_FORMATS), '-i', 'file:' + source,
            '-map', '0:a:0', '-vn', '-sn', '-dn', '-map_chapters', '-1']
    if options['tags'] == 'keep':
        args += ['-map_metadata', '0', '-map_metadata:s:a:0', '0:s:a:0']
    else:
        args += ['-map_metadata', '-1', '-map_metadata:s:a:0', '-1']
    args += ['-c:a', spec['encoder'], '-b:a', f'{kbps}k']
    channels = out_channels(options, info)
    if channels != int(info.get('channels') or channels):
        args += ['-ac', str(channels)]
    if options['format'] == 'mp3':
        args += ['-id3v2_version', '3']
    args += ['-fflags', '+bitexact', '-fs', str(audioconvert.MAX_OUTPUT_BYTES - 1024 * 1024), '-f', spec['muxer'], '-n', 'file:' + target]
    return args


def notes(info: dict | None, options: dict) -> list:
    """Frases (português) sobre o que a operação muda (antes de rodar)."""
    spec = audioconvert.FORMATS[options['format']]
    if options['mode'] == 'size':
        out = [f'Alvo de {mediatools.human_size(options["size_kb"] * 1024)}: o app calcula o bitrate que caberia, grava e mede; se passar, tenta uma vez com bitrate menor e, se ainda passar, avisa o tamanho real (é melhor esforço, não garantia).']
    else:
        out = [f'Bitrate de {options["kbps"]} kbps em {spec["label"]}: o áudio é recodificado e perde qualidade em troca de tamanho.']
    if options['mono']:
        out.append('Os canais são misturados em um só (mono): o arquivo fica menor; se houver oposição de fase, parte do som some.')
    if info:
        if info.get('has_video'):
            out.append('Somente a faixa de áudio é mantida; o vídeo não vai para o arquivo novo.')
        if int(info.get('audio_streams') or 1) > 1:
            out.append('O arquivo tem mais de uma faixa de áudio: só a primeira é comprimida.')
        if int(info.get('channels') or 0) > spec['max_channels'] and not options['mono']:
            out.append(f'{spec["label"]} aceita até {spec["max_channels"]} canais: o áudio será mixado para estéreo.')
        if info.get('has_cover'):
            out.append('A capa embutida não é copiada (ela pode ocupar boa parte do arquivo).')
        if info.get('chapters'):
            out.append('Os capítulos não são copiados.')
        if info.get('codec') in spec['codecs']:
            out.append('A origem já está neste formato: recodificar de novo perde qualidade; só vale se o tamanho cair bastante.')
    out.append('As etiquetas são mantidas quando o formato aceita.' if options['tags'] == 'keep' else 'As etiquetas são removidas.')
    out.append('Se o arquivo novo não ficar menor que o original, ele é descartado e o app explica.')
    out.append('O arquivo original não é alterado; a cópia ganha o sufixo «-comprimido».')
    return out


def _encode(exe: str, source_path: str, stage: Path, options: dict, kbps: int, info: dict) -> int:
    if stage.exists():
        stage.unlink()
    audioconvert._run(exe, build_args(source_path, str(stage.resolve()), options, kbps, info))
    if not stage.is_file() or stage.is_symlink() or stage.stat().st_size == 0:
        raise MediaError('A operação não gerou nenhum arquivo.')
    size = stage.stat().st_size
    if size >= audioconvert.MAX_OUTPUT_BYTES - 1024 * 1024:
        stage.unlink(missing_ok=True)
        raise MediaError('A saída passou do limite de 512 MiB e foi descartada.')
    return size


def apply(source: Path, stage: Path, job: dict) -> dict:
    """Grava em `stage` o áudio comprimido. Devolve `{'suffix', 'name', 'notes'}`."""
    options = options_from(job)
    fmt = options['format']
    spec = audioconvert.FORMATS[fmt]
    exe = mediatools.find_tool('ffmpeg')
    if not exe or not mediatools.find_tool('ffprobe'):
        raise MediaError('O FFmpeg não foi encontrado neste computador. Instale-o (veja docs/DEPENDENCIAS.md) e tente de novo.')
    build = mediatools.build_info()
    if build and build.get('encoders') is not None and not set(mediatools.OUTPUT_ENCODERS[fmt]) & set(build['encoders']):
        raise MediaError(f'Este FFmpeg não tem o codificador de {spec["label"]}. Escolha outro formato.')
    info = mediatools.probe(source)
    source_size = source.stat().st_size
    kbps, note = plan_bitrate(options, info, source_size)
    if stage.exists():
        raise MediaError('A pasta de preparo já tem um arquivo de saída.')
    source_path = str(source.resolve())
    messages = [note] if note else []
    size = _encode(exe, source_path, stage, options, kbps, info)
    if options['mode'] == 'size':
        target = options['size_kb'] * 1024
        if size > target:
            retry = int(kbps * (target - OVERHEAD_BYTES) / max(1, size - OVERHEAD_BYTES) * RETRY_SLACK)
            low = LIMITS[fmt][0]
            if low <= retry < kbps:
                kbps = retry
                size = _encode(exe, source_path, stage, options, kbps, info)
            if size > target:
                messages.append(f'Melhor esforço: o arquivo ficou com {mediatools.human_size(size)}, acima do alvo de {mediatools.human_size(target)}'
                                + (' (o bitrate necessário já estaria abaixo do mínimo do formato).' if retry < low else '.'))
    try:
        out = mediatools.probe(stage)
        channels = out_channels(options, info)
        if out['codec'] not in spec['codecs'] or out['audio_streams'] != 1 or out['has_video'] or out['channels'] != channels:
            raise MediaError('A conferência do arquivo novo falhou (formato inesperado); nada foi salvo.')
        if info['duration'] > 0 and abs(out['duration'] - info['duration']) > max(1.0, info['duration'] * audioconvert.DURATION_TOLERANCE):
            raise MediaError('A conferência do arquivo novo falhou (a duração difere da original); nada foi salvo.')
        if source_size and size >= source_size:
            raise MediaError(f'O arquivo novo ficaria com {mediatools.human_size(size)}, não menor que o original ({mediatools.human_size(source_size)}); nada foi salvo. Escolha um bitrate menor ou o modo mono.')
    except MediaError:
        stage.unlink(missing_ok=True)
        raise
    saved = 100 - round(size * 100 / source_size) if source_size else 0
    messages.insert(0, f'Tamanho: de {mediatools.human_size(source_size)} para {mediatools.human_size(size)} (−{saved} %), ≈ {kbps} kbps em {spec["label"]}.')
    return {'suffix': spec['suffix'], 'name': 'comprimido', 'notes': messages}
