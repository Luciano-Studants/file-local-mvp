"""Cortar áudio com FFmpeg (núcleo puro, sem Qt). Áudio, item 6.

Dois modos: **início e fim** (em milissegundos, escolhidos na onda ou digitados) e **silêncio das pontas** (só o começo e o fim; silêncio no meio
nunca é tocado). Formatos com perda (MP3, M4A, OGG, Opus) são cortados **sem recodificar** (precisão de quadro, ± ~40 ms) ou, a pedido, de forma
exata recodificando; FLAC, WAV e AIFF são sempre cortados de forma exata (o FFmpeg não corta FLAC por cópia e a recodificação não perde nada).
Etiquetas são mantidas; a capa (MP3, M4A, FLAC) volta num segundo passo de cópia, porque o corte descartaria a imagem.

Também gera a **onda** (picos por trecho) que a interface desenha: o FFmpeg decodifica para mono de 4 kHz e só os picos ficam na memória.
"""
from __future__ import annotations

import re
import subprocess
import threading
from pathlib import Path

import audioconvert
import audiotags
import mediatools
from mediatools import MediaError

MODES = ('range', 'silence')
MAX_MS = mediatools.MAX_DURATION * 1000
MIN_LENGTH = 0.1                     # segundos: menor trecho aceito
SILENCE_DB = -50                     # abaixo disso é silêncio
SILENCE_MIN = 0.3                    # segundos de silêncio para contar
SILENCE_PAD = 0.05                   # folga mantida junto ao som ao cortar o silêncio
EDGE_TOLERANCE = 0.05
WAVE_RATE = 4000                     # Hz da decodificação para a onda
WAVE_BUCKETS = 1200
MAX_WAVE_SECONDS = 2 * 3600          # acima disso não há onda (o corte por números continua valendo)
WAVE_TIMEOUT = 120
SILENCE_OP_TIMEOUT = 90
MAX_STDERR = 256 * 1024
LOSSLESS = ('flac', 'wav', 'aiff')   # sempre cortados de forma exata
_SIL_START = re.compile(r'silence_start:\s*(-?\d+(?:\.\d+)?)')
_SIL_END = re.compile(r'silence_end:\s*(-?\d+(?:\.\d+)?)')


def options_from(job: dict) -> tuple:
    """`(modo, início_ms, fim_ms, exato, qualidade)`; fim 0 = até o fim do arquivo."""
    mode = str(job.get('trim_mode') or 'range')
    exact = str(job.get('trim_exact') or 'no')
    quality = str(job.get('audio_quality') or audioconvert.DEFAULT_QUALITY)
    if mode not in MODES:
        raise MediaError('Modo de corte inválido. Escolha início e fim ou silêncio das pontas.')
    if exact not in ('yes', 'no'):
        raise MediaError('Opção de precisão inválida.')
    if quality not in audioconvert.QUALITIES:
        raise MediaError('Qualidade inválida. Escolha baixa, média ou alta.')
    values = []
    for key in ('trim_start_ms', 'trim_end_ms'):
        value = job.get(key, 0)
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= MAX_MS:
            raise MediaError('Início e fim devem ser tempos válidos (em milissegundos, de 0 a 24 horas).')
        values.append(value)
    start, end = values
    if mode == 'range':
        if end and end <= start:
            raise MediaError('O fim precisa ser depois do início.')
        if start == 0 and end == 0:
            raise MediaError('Nada para cortar: escolha um início e/ou um fim.')
    return mode, start, end, exact == 'yes', quality


def parse_silence(text: str) -> list:
    """Intervalos `(início, fim|None)` do `silencedetect` (fim None = continua até o fim do arquivo)."""
    spans, current = [], None
    for line in (text or '').replace('\r', '\n').split('\n'):
        match = _SIL_START.search(line)
        if match:
            current = float(match.group(1))
            continue
        match = _SIL_END.search(line)
        if match and current is not None:
            spans.append((current, float(match.group(1))))
            current = None
    if current is not None:
        spans.append((current, None))
    return spans


def edges_from(spans: list, duration: float) -> tuple:
    """`(silêncio_no_início, silêncio_no_fim)` em segundos; levanta `MediaError` se o arquivo todo é silêncio."""
    lead = tail = 0.0
    for start, end in spans:
        end_at = duration if end is None else end
        if start <= EDGE_TOLERANCE:
            lead = max(lead, end_at)
        if end_at >= duration - EDGE_TOLERANCE:
            tail = max(tail, duration - max(start, 0.0))
    if lead >= duration - EDGE_TOLERANCE:
        raise MediaError('O arquivo inteiro é silêncio; não há o que manter.')
    return round(min(lead, duration), 3), round(min(tail, duration), 3)


def silence_args(source: str) -> list:
    return ['-nostdin', '-v', 'info', '-nostats', '-protocol_whitelist', 'file', '-format_whitelist', ','.join(mediatools.INPUT_FORMATS), '-i', 'file:' + source,
            '-map', '0:a:0', '-vn', '-af', f'silencedetect=noise={SILENCE_DB}dB:d={SILENCE_MIN}', '-f', 'null', '-']


def detect_edges(exe: str, source: str, duration: float, timeout: int = audioconvert.CONVERT_TIMEOUT) -> tuple:
    flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    try:
        done = subprocess.run([exe, '-hide_banner', *silence_args(source)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                              timeout=timeout, env=mediatools._clean_env(), creationflags=flags, shell=False)
    except subprocess.TimeoutExpired:
        raise MediaError('A análise do silêncio demorou demais e foi interrompida; tente um arquivo menor.') from None
    except OSError:
        raise MediaError('Não foi possível executar o FFmpeg.') from None
    if done.returncode != 0:
        raise MediaError('O FFmpeg não conseguiu analisar este arquivo. Ele pode estar corrompido ou usar um formato sem suporte.')
    return edges_from(parse_silence(done.stderr[-MAX_STDERR:].decode('utf-8', errors='replace')), duration)


def plan_cut(mode: str, start_ms: int, end_ms: int, duration: float, edges: tuple | None) -> tuple:
    """`(início_s, comprimento_s)` do trecho que fica; levanta `MediaError` se não sobrar nada ou não houver o que cortar."""
    if mode == 'silence':
        lead, tail = edges or (0.0, 0.0)
        if lead < SILENCE_MIN and tail < SILENCE_MIN:
            raise MediaError(f'Não há silêncio de pelo menos {SILENCE_MIN:g} s (abaixo de {SILENCE_DB} dB) no começo nem no fim.'.replace('.', ','))
        start = max(0.0, lead - SILENCE_PAD) if lead >= SILENCE_MIN else 0.0
        end = duration - max(0.0, tail - SILENCE_PAD) if tail >= SILENCE_MIN else duration
    else:
        start = start_ms / 1000
        end = min(end_ms / 1000, duration) if end_ms else duration
    if start >= duration - MIN_LENGTH:
        raise MediaError('O início passa do fim do áudio.')
    if end - start < MIN_LENGTH:
        raise MediaError('O trecho que sobraria é curto demais (menos de 0,1 s).')
    if start <= 0.0005 and end >= duration - 0.0005:
        raise MediaError('O corte pedido não remove nada do áudio.')
    return round(start, 3), round(end - start, 3)


def build_args(source: str, target: str, kind: str, start: float, length: float, exact: bool, quality: str, keep_cover: bool) -> list:
    """Passo 1: só o áudio (e as etiquetas) do trecho. A capa, se houver, volta no passo 2 (`cover_args`)."""
    muxer = audiotags.KINDS[kind][0]
    args = ['-nostdin', '-v', 'error', '-protocol_whitelist', 'file', '-format_whitelist', ','.join(mediatools.INPUT_FORMATS), '-i', 'file:' + source,
            '-map', '0:a:0', '-map_chapters', '-1', '-map_metadata', '0', '-map_metadata:s:a:0', '0:s:a:0', '-ss', f'{start:.3f}', '-t', f'{length:.3f}']
    if exact or kind in LOSSLESS:
        args += ['-c:a', audioconvert.FORMATS[kind]['encoder'], *audioconvert.QUALITY_ARGS.get(kind, {}).get(quality, [])]
    else:
        args += ['-c', 'copy']
    if kind == 'mp3':
        args += ['-id3v2_version', '3']
    args += ['-fflags', '+bitexact', '-fs', str(audioconvert.MAX_OUTPUT_BYTES - 1024 * 1024), '-f', muxer, '-n', 'file:' + target]
    return args


def cover_args(cut: str, original: str, kind: str, target: str) -> list:
    muxer = audiotags.KINDS[kind][0]
    args = ['-nostdin', '-v', 'error', '-protocol_whitelist', 'file', '-format_whitelist', ','.join(mediatools.INPUT_FORMATS), '-i', 'file:' + cut, '-i', 'file:' + original,
            '-map', '0:a:0', '-map', '1:v:0', '-map_chapters', '-1', '-map_metadata', '0', '-map_metadata:s:a:0', '0:s:a:0', '-c', 'copy', '-disposition:v:0', 'attached_pic']
    if kind == 'mp3':
        args += ['-id3v2_version', '3']
    args += ['-fflags', '+bitexact', '-fs', str(audioconvert.MAX_OUTPUT_BYTES - 1024 * 1024), '-f', muxer, '-n', 'file:' + target]
    return args


def fmt_time(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    minutes, rest = divmod(seconds, 60)
    return f'{int(minutes)}:{rest:06.3f}'.replace('.', ',')


def notes(info: dict | None, mode: str, exact: bool) -> list:
    """Frases (português) sobre o que a operação muda."""
    out = []
    kind = None
    if info:
        try:
            kind = audiotags.kind_of(info)
        except MediaError as error:
            out.append(str(error))
    if mode == 'silence':
        out.append(f'Só o silêncio do começo e do fim é removido (abaixo de {SILENCE_DB} dB por pelo menos {SILENCE_MIN:g} s, com folga de {int(SILENCE_PAD * 1000)} ms); silêncio no meio nunca é tocado.'.replace('.', ','))
    else:
        out.append('Fica só o trecho entre o início e o fim escolhidos.')
    if kind in LOSSLESS:
        out.append(f'{audioconvert.FORMATS[kind]["label"]} é cortado de forma exata, sem perda de qualidade' + (' (arquivos de 24 bits ou decimais saem com 16 bits).' if kind in ('wav', 'aiff') else '.'))
    elif kind:
        if exact:
            out.append(f'Corte exato: o áudio é recodificado em {audioconvert.FORMATS[kind]["label"]} (perde um pouco de qualidade).')
        else:
            out.append('Corte sem recodificar: nenhuma perda de qualidade; o ponto de corte cai no quadro de áudio mais próximo (erro de até ~40 ms).')
    if info and kind:
        if info.get('has_cover') and kind in ('ogg', 'opus'):
            out.append(f'A capa embutida de arquivos {audioconvert.FORMATS[kind]["label"]} não é copiada (limite do FFmpeg).')
        if info.get('chapters'):
            out.append('Os capítulos não são copiados (os tempos mudam com o corte).')
    out.append('As etiquetas são mantidas.')
    out.append('O arquivo original não é alterado; a cópia ganha o sufixo «-cortado».')
    return out


def apply(source: Path, stage: Path, job: dict) -> dict:
    """Grava em `stage` o trecho pedido. Devolve `{'suffix', 'name', 'notes'}`."""
    mode, start_ms, end_ms, exact, quality = options_from(job)
    exe = mediatools.find_tool('ffmpeg')
    if not exe or not mediatools.find_tool('ffprobe'):
        raise MediaError('O FFmpeg não foi encontrado neste computador. Instale-o (veja docs/DEPENDENCIAS.md) e tente de novo.')
    info = mediatools.probe(source)
    kind = audiotags.kind_of(info)
    if info['duration'] <= 0:
        raise MediaError('Não foi possível saber a duração do áudio; o corte foi recusado.')
    spec = audioconvert.FORMATS[kind]
    build = mediatools.build_info()
    if (exact or kind in LOSSLESS) and build and build.get('encoders') is not None and not set(mediatools.OUTPUT_ENCODERS[kind]) & set(build['encoders']):
        raise MediaError(f'Este FFmpeg não tem o codificador de {spec["label"]}.')
    source_path = str(source.resolve())
    edges = detect_edges(exe, source_path, info['duration']) if mode == 'silence' else None
    start, length = plan_cut(mode, start_ms, end_ms, info['duration'], edges)
    if stage.exists():
        raise MediaError('A pasta de preparo já tem um arquivo de saída.')
    keep_cover = bool(info.get('has_cover')) and audiotags.KINDS[kind][3]
    warnings = []
    cut = stage.with_name(stage.name + '.corte') if keep_cover else stage
    try:
        audioconvert._run(exe, build_args(source_path, str(cut.resolve()), kind, start, length, exact, quality, keep_cover))
        if not cut.is_file() or cut.is_symlink() or cut.stat().st_size == 0:
            raise MediaError('A operação não gerou nenhum arquivo.')
        if keep_cover:
            audioconvert._run(exe, cover_args(str(cut.resolve()), source_path, kind, str(stage.resolve())))
    finally:
        if cut != stage:
            cut.unlink(missing_ok=True)
    if info.get('has_cover') and not keep_cover:
        warnings.append(f'A capa embutida não foi copiada ({spec["label"]} não permite regravá-la com o FFmpeg).')
    try:
        _verify(info, mediatools.probe(stage), kind, length, exact or kind in LOSSLESS)
    except MediaError:
        stage.unlink(missing_ok=True)
        raise
    out_duration = mediatools.probe(stage)['duration']
    if mode == 'silence':
        warnings.insert(0, f'Silêncio removido: {fmt_time(start)} no começo e {fmt_time(max(0.0, info["duration"] - start - length))} no fim (duração final {fmt_time(out_duration)}).')
    elif abs(out_duration - length) > 0.03:
        warnings.insert(0, f'Duração final {fmt_time(out_duration)} (pedido: {fmt_time(length)}): o corte sem recodificar cai no quadro de áudio mais próximo.')
    return {'suffix': audiotags.KINDS[kind][1], 'name': 'cortado', 'notes': warnings}


def _verify(before: dict, after: dict, kind: str, length: float, exact: bool) -> None:
    spec = audioconvert.FORMATS[kind]
    if after['codec'] not in spec['codecs'] or after['audio_streams'] != 1 or after['has_video'] or after['channels'] != before['channels']:
        raise MediaError('A conferência do arquivo novo falhou (formato inesperado); nada foi salvo.')
    tolerance = max(0.1, length * 0.02) if exact else max(0.15, length * 0.03)
    if abs(after['duration'] - length) > tolerance:
        raise MediaError('A conferência do arquivo novo falhou (a duração não é a pedida); nada foi salvo.')
    for key, value in (before.get('tags') or {}).items():
        if (after.get('tags') or {}).get(key) != value:
            raise MediaError(f'O formato {spec["label"]} perderia o campo «{mediatools.TAG_LABELS.get(key, key)}» ao ser regravado; nada foi salvo.')
    if before.get('has_cover') and audiotags.KINDS[kind][3] and not after.get('has_cover'):
        raise MediaError('A capa se perdeu no corte; nada foi salvo.')


# ---------------------------------------------------------------------------
# onda (picos) para a interface
# ---------------------------------------------------------------------------
def wave_args(source: str) -> list:
    return ['-nostdin', '-v', 'error', '-protocol_whitelist', 'file', '-format_whitelist', ','.join(mediatools.INPUT_FORMATS), '-i', 'file:' + source,
            '-map', '0:a:0', '-vn', '-ac', '1', '-ar', str(WAVE_RATE), '-f', 's16le', '-']


def reduce_peaks(chunks, total_samples: int, buckets: int = WAVE_BUCKETS) -> list:
    """`[[mín, máx], …]` em −100..100 (um par por trecho) a partir de blocos de bytes s16le; só os picos ficam na memória."""
    import numpy as np
    size = max(1, -(-total_samples // buckets))
    peaks, pending, carry = [], np.zeros(0, dtype=np.int16), b''
    for chunk in chunks:
        chunk = carry + chunk
        usable = len(chunk) - len(chunk) % 2
        carry = chunk[usable:]                          # meia amostra no fim do bloco vai junto com o próximo
        if not usable:
            continue
        pending = np.concatenate([pending, np.frombuffer(chunk[:usable], dtype='<i2')])
        full = len(pending) // size
        if full:
            block = pending[:full * size].reshape(full, size)
            peaks.extend(zip(block.min(axis=1).tolist(), block.max(axis=1).tolist()))
            pending = pending[full * size:]
    if len(pending):
        peaks.append((int(pending.min()), int(pending.max())))
    return [[round(lo / 327.68), round(hi / 327.68)] for lo, hi in peaks[:buckets + 1]]


def waveform(source: str, duration: float) -> list:
    exe = mediatools.find_tool('ffmpeg')
    if not exe:
        raise MediaError('O programa de mídia (ffmpeg) não foi encontrado.')
    if duration <= 0 or duration > MAX_WAVE_SECONDS:
        raise MediaError('A onda só é mostrada para áudios de até 2 horas; use os campos de tempo para cortar.')
    flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    proc = subprocess.Popen([exe, '-hide_banner', *wave_args(source)], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            env=mediatools._clean_env(), creationflags=flags, shell=False)
    timer = threading.Timer(WAVE_TIMEOUT, proc.kill)
    timer.start()
    limit = int((duration + 60) * WAVE_RATE * 2)
    state = {'read': 0}

    def chunks():
        while True:
            data = proc.stdout.read(1 << 20)
            if not data:
                return
            state['read'] += len(data)
            if state['read'] > limit:
                proc.kill()
                raise MediaError('O áudio decodificado passou do esperado; a onda foi cancelada.')
            yield data

    try:
        peaks = reduce_peaks(chunks(), int(duration * WAVE_RATE))
    finally:
        timer.cancel()
        proc.kill() if proc.poll() is None else None
        proc.stdout.close()
        proc.wait()
    if not peaks:
        raise MediaError('Não foi possível ler o áudio para desenhar a onda.')
    return peaks


def run_op(job: dict, source_file=None) -> dict:
    """`audio_wave`: um caminho → `{'duration', 'peaks', 'silence': {'lead','tail'} | None, 'info': …}`; erros viram `{'error'}` para a interface mostrar."""
    if job.get('op') != 'audio_wave':
        raise MediaError('Operação de áudio desconhecida.')
    raws = job.get('paths')
    if not isinstance(raws, list) or len(raws) != 1:
        raise MediaError('Escolha um arquivo de áudio.')
    check = source_file or mediatools._plain_source
    path = check(raws[0])
    info = mediatools.probe(path)
    result = {'name': Path(str(raws[0])).name, 'duration': info['duration'], 'channels': info['channels'], 'silence': None, 'peaks': [], 'wave_error': ''}
    try:
        result['peaks'] = waveform(str(Path(path).resolve()), info['duration'])
    except MediaError as error:
        result['wave_error'] = str(error)
    exe = mediatools.find_tool('ffmpeg')
    if exe and 0 < info['duration'] <= MAX_WAVE_SECONDS:
        try:
            lead, tail = detect_edges(exe, str(Path(path).resolve()), info['duration'], SILENCE_OP_TIMEOUT)
            result['silence'] = {'lead': lead, 'tail': tail}
        except MediaError as error:
            result['silence_error'] = str(error)
    return result
