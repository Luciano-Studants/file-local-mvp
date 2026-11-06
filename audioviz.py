"""Visualizador em MP4: áudio → vídeo com onda ou espectro (núcleo puro, sem Qt). Áudio, item 10.

O vídeo é desenhado pelo próprio FFmpeg (`showwaves` / `showspectrum`) a partir do áudio; nenhuma imagem externa é aberta. O codificador de vídeo
é o **`mpeg4` nativo do FFmpeg** (MPEG-4 Parte 2, presente em qualquer build LGPL): H.264 exige `libx264` (GPL), que não pode acompanhar o aplicativo
(pendência jurídica no plano do Vídeo). O áudio vai em AAC. O MP4 resultante toca em VLC, Windows e na maioria dos players, mas alguns sites e
celulares só aceitam H.264; o app avisa isso.
Limites: até 30 minutos de áudio, 360p ou 720p, 25 quadros/s, bitrate de vídeo fixo (tamanho previsível). Mesmos cuidados das outras ferramentas:
sem shell, `-protocol_whitelist file`, `-format_whitelist`, `-n`, tempo máximo, conferência do arquivo novo (codec, tamanho, duração, decodificação).
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import audioconvert
import mediatools
from mediatools import MediaError

STYLES = {'waves': 'Onda', 'spectrum': 'Espectro'}
SIZES = {'360p': (640, 360, 600), '720p': (1280, 720, 1500)}        # largura, altura, kbps de vídeo
DEFAULT_STYLE, DEFAULT_SIZE = 'waves', '720p'
FPS = 25
AUDIO_KBPS = 192
MAX_SECONDS = 30 * 60
VIDEO_ENCODER = 'mpeg4'
COLOR = '0xE8873A'
VERIFY_TIMEOUT = 600


def options_from(job: dict) -> dict:
    style = str(job.get('viz_style') or DEFAULT_STYLE)
    size = str(job.get('viz_size') or DEFAULT_SIZE)
    tags = str(job.get('audio_tags') or audioconvert.DEFAULT_TAGS)
    if style not in STYLES:
        raise MediaError('Estilo inválido. Escolha onda ou espectro.')
    if size not in SIZES:
        raise MediaError('Tamanho inválido. Escolha 360p ou 720p.')
    if tags not in audioconvert.TAG_MODES:
        raise MediaError('Opção de etiquetas inválida. Escolha manter ou remover.')
    return {'style': style, 'size': size, 'tags': tags}


def video_filter(options: dict) -> str:
    """Cadeia do ramo de vídeo (só valores fixos do app entram nela)."""
    width, height, _kbps = SIZES[options['size']]
    if options['style'] == 'waves':
        draw = f'showwaves=s={width}x{height}:mode=cline:rate={FPS}:scale=sqrt:colors={COLOR}'
    else:
        draw = f'showspectrum=s={width}x{height}:slide=scroll:color=intensity:scale=log,fps={FPS}'
    return f'aformat=channel_layouts=mono,{draw},format=yuv420p'


def plan(info: dict) -> None:
    duration = float(info.get('duration') or 0)
    if duration <= 0:
        raise MediaError('Não foi possível saber a duração do áudio; o vídeo não pode ser planejado.')
    if duration > MAX_SECONDS:
        raise MediaError(f'O áudio tem {mediatools.format_duration(duration)}; o visualizador aceita até {MAX_SECONDS // 60} minutos. Use «Cortar» antes.')


def build_args(source: str, target: str, options: dict, info: dict) -> list:
    _w, _h, kbps = SIZES[options['size']]
    # o arquivo é aberto duas vezes (som e desenho): com `asplit` o FFmpeg pode travar esperando um dos ramos
    graph = f'[1:a:0]{video_filter(options)}[vo]'
    gate = ['-protocol_whitelist', 'file', '-format_whitelist', ','.join(audioconvert.INPUT_FORMATS)]
    args = ['-nostdin', '-v', 'error', *gate, '-i', 'file:' + source, *gate, '-i', 'file:' + source,
            '-filter_complex', graph, '-map', '[vo]', '-map', '0:a:0', '-sn', '-dn', '-map_chapters', '-1']
    if options['tags'] == 'keep':
        args += ['-map_metadata', '0']
    else:
        args += ['-map_metadata', '-1']
    args += ['-c:v', VIDEO_ENCODER, '-b:v', f'{kbps}k', '-g', str(FPS * 2), '-c:a', 'aac', '-b:a', f'{AUDIO_KBPS}k']
    if int(info.get('channels') or 2) > 2:
        args += ['-ac', '2']
    args += ['-fflags', '+bitexact', '-movflags', '+faststart', '-fs', str(audioconvert.MAX_OUTPUT_BYTES - 1024 * 1024), '-f', 'mp4', '-n', 'file:' + target]
    return args


def notes(info: dict | None, options: dict) -> list:
    width, height, kbps = SIZES[options['size']]
    out = [f'Gera um vídeo MP4 de {width}×{height} ({FPS} quadros/s) com {STYLES[options["style"]].lower()} do áudio; o som vai em AAC a {AUDIO_KBPS} kbps.',
           'O vídeo usa MPEG-4 Parte 2 (codificador livre do FFmpeg), não H.264: toca em VLC e no Windows, mas alguns sites e celulares só aceitam H.264.',
           f'Limite de {MAX_SECONDS // 60} minutos de áudio; o vídeo usa cerca de {kbps} kbps (≈ {(kbps + AUDIO_KBPS) * 60 / 8 / 1024:.1f} MB por minuto).']
    if info:
        if info.get('has_video'):
            out.append('Só a faixa de áudio é usada; o vídeo original não vai para o arquivo novo.')
        if int(info.get('audio_streams') or 1) > 1:
            out.append('O arquivo tem mais de uma faixa de áudio: só a primeira é usada.')
        if int(info.get('channels') or 0) > 2:
            out.append('O som será mixado para estéreo.')
        if info.get('chapters'):
            out.append('Os capítulos não são copiados.')
        if info.get('has_cover'):
            out.append('A capa embutida não é copiada.')
    out.append('As etiquetas são mantidas quando o MP4 aceita.' if options['tags'] == 'keep' else 'As etiquetas são removidas.')
    out.append('O arquivo original não é alterado; a cópia ganha o sufixo «-visualizador».')
    return out


def _decode_check(exe: str, path: str) -> None:
    """Decodifica o arquivo novo inteiro (vídeo e áudio) sem gravar nada; qualquer erro do decodificador reprova."""
    flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    args = [exe, '-hide_banner', '-nostdin', '-v', 'error', '-protocol_whitelist', 'file', '-format_whitelist', 'mov,mp4,m4a,3gp,3g2,mj2', '-i', 'file:' + path, '-f', 'null', '-']
    try:
        done = subprocess.run(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=VERIFY_TIMEOUT, env=mediatools._clean_env(), creationflags=flags, shell=False)
    except (subprocess.TimeoutExpired, OSError):
        raise MediaError('Não foi possível conferir o vídeo novo; nada foi salvo.') from None
    if done.returncode != 0 or done.stderr.strip():
        raise MediaError('A conferência falhou: o vídeo novo não decodifica sem erros; nada foi salvo.')


def _verify(exe: str, before: dict, after: dict, stage: Path, options: dict) -> None:
    width, height, _kbps = SIZES[options['size']]
    if after['video_codec'] != VIDEO_ENCODER or (after['video_width'], after['video_height']) != (width, height):
        raise MediaError('A conferência falhou: o vídeo novo não tem o formato esperado; nada foi salvo.')
    if after['codec'] != 'aac' or after['audio_streams'] != 1:
        raise MediaError('A conferência falhou: o áudio do vídeo novo não tem o formato esperado; nada foi salvo.')
    if before['duration'] > 0 and abs(after['duration'] - before['duration']) > max(1.0, before['duration'] * audioconvert.DURATION_TOLERANCE):
        raise MediaError('A conferência falhou: a duração do vídeo novo difere da original; nada foi salvo.')
    if options['tags'] == 'drop' and after.get('tags'):
        raise MediaError('A conferência falhou: ainda restaram etiquetas no arquivo novo; nada foi salvo.')
    _decode_check(exe, str(stage.resolve()))


def apply(source: Path, stage: Path, job: dict) -> dict:
    """Grava em `stage` o MP4 com a visualização. Devolve `{'suffix', 'name', 'notes'}`."""
    options = options_from(job)
    exe = mediatools.find_tool('ffmpeg')
    if not exe or not mediatools.find_tool('ffprobe'):
        raise MediaError('O FFmpeg não foi encontrado neste computador. Instale-o (veja docs/DEPENDENCIAS.md) e tente de novo.')
    build = mediatools.build_info()
    if build and build.get('encoders') is not None:
        if 'aac' not in build['encoders']:
            raise MediaError('Este FFmpeg não tem o codificador de áudio AAC.')
        if VIDEO_ENCODER not in (build.get('video_encoders') or []):
            raise MediaError('Este FFmpeg não tem o codificador de vídeo MPEG-4 necessário para o visualizador.')
    info = mediatools.probe(source)
    plan(info)
    if stage.exists():
        raise MediaError('A pasta de preparo já tem um arquivo de saída.')
    try:
        audioconvert._run(exe, build_args(str(source.resolve()), str(stage.resolve()), options, info))
        if not stage.is_file() or stage.is_symlink() or stage.stat().st_size == 0:
            raise MediaError('A operação não gerou nenhum arquivo.')
        if stage.stat().st_size >= audioconvert.MAX_OUTPUT_BYTES - 1024 * 1024:
            raise MediaError('A saída passou do limite de 512 MiB e foi descartada.')
        _verify(exe, info, mediatools.probe(stage), stage, options)
    except MediaError:
        stage.unlink(missing_ok=True)
        raise
    return {'suffix': 'mp4', 'name': 'visualizador', 'notes': [f'Vídeo de {mediatools.human_size(stage.stat().st_size)} gerado (MPEG-4 + AAC, {SIZES[options["size"]][0]}×{SIZES[options["size"]][1]}).']}
