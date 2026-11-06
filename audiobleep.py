"""Bleep: cobrir trechos do áudio com um tom sintético (ou silêncio) com FFmpeg (núcleo puro, sem Qt). Áudio, item 9.

Os trechos vêm como texto («0:12,5-0:14; 1:02-1:03,5») e são **validados**: formato, ordem, limites do arquivo, tamanho mínimo, quantidade
máxima; trechos que se sobrepõem são unidos (e o app avisa). Só números calculados pelo app entram no filtro do FFmpeg, nunca texto do usuário.
O filtro é um `aeval` que, dentro dos trechos, troca as amostras originais por um seno de 0,25 de amplitude (−12 dBFS) ou por zero (silêncio);
fora deles o sinal não é tocado (na recodificação, com perda ou sem).

**Isto não é anonimização criptográfica nem garantia de privacidade:** o arquivo original continua existindo; o resto do áudio pode revelar a
pessoa (voz, contexto); etiquetas, capa e capítulos podem trazer dados (por isso há a opção de removê-los). O app confere, medindo o arquivo
novo (decodificando alguns trechos), que eles foram mesmo substituídos.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import audiochannels
import audioconvert
import audiotags
import audiotrim
import mediatools
from mediatools import MediaError

MODES = ('tone', 'mute')
TONES = {'low': 500, 'mid': 1000, 'high': 2000}
TONE_LABELS = {'low': 'grave (500 Hz)', 'mid': 'médio (1000 Hz)', 'high': 'agudo (2000 Hz)'}
TONE_AMPLITUDE = 0.25
MAX_RANGES = 200
MAX_TEXT = 8000
MIN_LENGTH = 0.05                 # s
MAX_LENGTH = 3600.0               # s por trecho
END_TOLERANCE = 0.05              # s: fim até 50 ms depois da duração é ajustado
TONE_MIN_RATIO = 0.9              # energia mínima na faixa do tom, no arquivo novo
_TIME = re.compile(r'^[0-9]+(?:[.,][0-9]{1,3})?$')
_SPLIT = re.compile(r'[;\n]+')
_DASH = re.compile(r'\s*[-–—]\s*')


def parse_time(text: str) -> float:
    """«12,5», «1:02», «1:02.5» ou «0:01:02,5» → segundos. Levanta `MediaError` com a parte problemática."""
    raw = text.strip()
    parts = raw.split(':')
    if not raw or len(parts) > 3 or not all(parts):
        raise MediaError(f'Tempo inválido: «{raw[:20]}». Use segundos (12,5) ou min:seg (1:02,5).')
    *whole, last = parts
    if not _TIME.match(last) or any(not (p.isascii() and p.isdigit()) or len(p) > 2 for p in whole):
        raise MediaError(f'Tempo inválido: «{raw[:20]}». Use segundos (12,5) ou min:seg (1:02,5).')
    seconds = float(last.replace(',', '.'))
    multiplier = 60
    for part in reversed(whole):
        seconds += int(part) * multiplier
        multiplier *= 60
    if len(whole) >= 1 and float(last.replace(',', '.')) >= 60:
        raise MediaError(f'Tempo inválido: «{raw[:20]}» (os segundos vão de 0 a 59 quando há minutos).')
    return round(seconds, 3)


def parse_ranges(text: str) -> list:
    """Texto → lista de `(início, fim)` em segundos, na ordem escrita (sem juntar). Levanta `MediaError` citando o trecho com problema."""
    if isinstance(text, list):                       # a interface manda uma lista de textos «início-fim»
        if not all(isinstance(item, str) and len(item) <= 64 for item in text):
            raise MediaError('Trechos inválidos.')
        text = '\n'.join(text)
    if not isinstance(text, str):
        raise MediaError('Informe os trechos do bleep.')
    if len(text) > MAX_TEXT:
        raise MediaError(f'O texto dos trechos é grande demais (máximo de {MAX_TEXT} caracteres).')
    if any(ord(ch) < 32 and ch != '\n' for ch in text):
        raise MediaError('Os trechos têm caracteres inválidos.')
    out = []
    for item in _SPLIT.split(text):
        item = item.strip()
        if not item:
            continue
        halves = _DASH.split(item)
        if len(halves) != 2:
            raise MediaError(f'Trecho inválido: «{item[:30]}». Escreva «início-fim», por exemplo 0:12,5-0:14.')
        try:
            start, end = parse_time(halves[0]), parse_time(halves[1])
        except MediaError as error:
            raise MediaError(f'Trecho «{item[:30]}»: {error}') from None
        if end <= start:
            raise MediaError(f'Trecho «{item[:30]}»: o fim precisa ser depois do início.')
        out.append((start, end))
    if not out:
        raise MediaError('Informe pelo menos um trecho (por exemplo 0:12,5-0:14).')
    if len(out) > MAX_RANGES:
        raise MediaError(f'Há {len(out)} trechos; o máximo é {MAX_RANGES}.')
    return out


def options_from(job: dict) -> dict:
    """`{'ranges','mode','tone','quality','tags'}` (trechos ainda sem checar contra a duração do arquivo)."""
    mode = str(job.get('bleep_mode') or 'tone')
    tone = str(job.get('bleep_tone') or 'mid')
    quality = str(job.get('audio_quality') or audioconvert.DEFAULT_QUALITY)
    tags = str(job.get('audio_tags') or audioconvert.DEFAULT_TAGS)
    if mode not in MODES:
        raise MediaError('Modo inválido. Escolha tom (bleep) ou silêncio.')
    if tone not in TONES:
        raise MediaError('Tom inválido. Escolha grave, médio ou agudo.')
    if quality not in audioconvert.QUALITIES:
        raise MediaError('Qualidade inválida. Escolha baixa, média ou alta.')
    if tags not in audioconvert.TAG_MODES:
        raise MediaError('Opção de etiquetas inválida. Escolha manter ou remover.')
    return {'ranges': parse_ranges(job.get('bleep_ranges', '')), 'mode': mode, 'tone': tone, 'quality': quality, 'tags': tags}


def plan_ranges(ranges: list, duration: float) -> tuple:
    """`(trechos_finais, avisos)`: confere contra a duração, ajusta fins quase no fim, une sobreposições. Levanta `MediaError` se não der."""
    if duration <= 0:
        raise MediaError('Não foi possível saber a duração do áudio; os trechos não podem ser conferidos.')
    clean = []
    for start, end in ranges:
        label = f'{audiotrim.fmt_time(start)}–{audiotrim.fmt_time(end)}'
        if start >= duration:
            raise MediaError(f'O trecho {label} começa depois do fim do áudio ({audiotrim.fmt_time(duration)}).')
        if end > duration + END_TOLERANCE:
            raise MediaError(f'O trecho {label} termina depois do fim do áudio ({audiotrim.fmt_time(duration)}).')
        end = min(end, duration)
        if end - start < MIN_LENGTH:
            raise MediaError(f'O trecho {label} é curto demais (menos de {MIN_LENGTH * 1000:.0f} ms).')
        if end - start > MAX_LENGTH:
            raise MediaError(f'O trecho {label} passa de 1 hora.')
        clean.append((start, end))
    clean.sort()
    merged = [clean[0]]
    for start, end in clean[1:]:
        if start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    warnings = []
    if len(merged) < len(clean):
        warnings.append(f'{len(clean) - len(merged)} trecho(s) se sobrepunham ou se tocavam e foram unidos.')
    if sum(end - start for start, end in merged) >= duration - MIN_LENGTH:
        raise MediaError('Os trechos cobrem o áudio inteiro; nada do original sobraria.')
    return merged, warnings


def format_ranges(ranges: list) -> str:
    """Trechos → texto aceito por `parse_ranges` (um por linha, tempos em milissegundos)."""
    return '\n'.join(f'{audiotrim.fmt_time(start)}-{audiotrim.fmt_time(end)}' for start, end in ranges)


def _num(value: float) -> str:
    return f'{value:.3f}'


def audio_filter(ranges: list, channels: int, mode: str, tone: str) -> str:
    """`aeval` que troca as amostras dos trechos por seno (ou zero). Só números calculados aqui entram na expressão."""
    inside = '+'.join(f'between(t,{_num(start)},{_num(end)})' for start, end in ranges)
    amplitude = TONE_AMPLITUDE if mode == 'tone' else 0.0
    replacement = f'{amplitude:g}*sin(2*PI*{TONES[tone]}*t)'
    exprs = '|'.join(f'if(gt({inside},0),{replacement},val({index}))' for index in range(channels))
    return f"aeval='{exprs}':c=same"


def build_args(source: str, target: str, kind: str, info: dict, options: dict, ranges: list) -> list:
    muxer, _suffix, _stream_tags, cover_stream, _label = audiotags.KINDS[kind]
    spec = audioconvert.FORMATS[kind]
    keep = options['tags'] == 'keep'
    args = ['-nostdin', '-v', 'error', '-protocol_whitelist', 'file', '-format_whitelist', ','.join(mediatools.INPUT_FORMATS), '-i', 'file:' + source, '-map', '0:a:0']
    if cover_stream and info.get('has_cover') and keep:
        args += ['-map', '0:v:0?']
    args += ['-map_chapters', '-1']
    args += ['-map_metadata', '0', '-map_metadata:s:a:0', '0:s:a:0'] if keep else ['-map_metadata', '-1', '-map_metadata:s:a:0', '-1']
    args += ['-af', audio_filter(ranges, int(info['channels']), options['mode'], options['tone']), '-c:a', spec['encoder'], *audioconvert.QUALITY_ARGS.get(kind, {}).get(options['quality'], [])]
    if cover_stream and info.get('has_cover') and keep:
        args += ['-c:v', 'copy']
    if kind == 'mp3':
        args += ['-id3v2_version', '3']
    args += ['-fflags', '+bitexact', '-fs', str(audioconvert.MAX_OUTPUT_BYTES - 1024 * 1024), '-f', muxer, '-n', 'file:' + target]
    return args


def notes(info: dict | None, options: dict) -> list:
    """Frases (português) sobre o que a operação faz e **não** faz (antes de rodar)."""
    ranges = options['ranges']
    total = sum(end - start for start, end in ranges)
    what = f'um tom {TONE_LABELS[options["tone"]]}' if options['mode'] == 'tone' else 'silêncio'
    out = [f'{len(ranges)} trecho(s), {audiotrim.fmt_time(total)} no total, são substituídos por {what}; o resto do áudio não é tocado.']
    kind = None
    if info:
        try:
            kind = audiotags.kind_of(info)
        except MediaError as error:
            out.append(str(error))
    if kind:
        spec = audioconvert.FORMATS[kind]
        if spec['lossy']:
            out.append(f'{spec["label"]} é um formato com perda: o áudio é recodificado (≈ {audioconvert.BITRATES[kind][options["quality"]]} kbps) e perde um pouco de qualidade.')
        elif kind in ('wav', 'aiff'):
            out.append(f'{spec["label"]} é regravado com 16 bits (arquivos de 24 bits ou decimais perdem profundidade).')
        else:
            out.append('FLAC: sem perda de qualidade na recodificação.')
        if info.get('has_cover') and options['tags'] == 'keep' and kind in ('ogg', 'opus'):
            out.append(f'A capa embutida de arquivos {spec["label"]} não é copiada (limite do FFmpeg).')
        if info.get('chapters'):
            out.append('Os capítulos não são copiados.')
    out.append('As etiquetas e a capa são mantidas; podem conter nomes ou dados (use «Remover» se isso importa).' if options['tags'] == 'keep' else 'As etiquetas e a capa são removidas.')
    out.append('Atenção: isto NÃO é anonimização garantida. O arquivo original continua existindo, e o resto do áudio (voz, contexto) pode identificar a pessoa.')
    out.append('O arquivo original não é alterado; a cópia ganha o sufixo «-bleep».')
    return out


def _window_samples(exe: str, path: str, start: float, end: float):
    """Amostras (mono, 16 kHz, s16) do trecho, decodificadas pelo FFmpeg; no máximo 10 s."""
    import numpy as np
    flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    length = min(end - start, 10.0)
    args = [exe, '-hide_banner', '-nostdin', '-v', 'error', '-protocol_whitelist', 'file', '-format_whitelist', ','.join(mediatools.INPUT_FORMATS), '-ss', _num(start), '-t', _num(length),
            '-i', 'file:' + path, '-map', '0:a:0', '-vn', '-ac', '1', '-ar', '16000', '-f', 's16le', '-']
    try:
        done = subprocess.run(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=120, env=mediatools._clean_env(), creationflags=flags, shell=False)
    except (subprocess.TimeoutExpired, OSError):
        raise MediaError('Não foi possível conferir o arquivo novo; nada foi salvo.') from None
    if done.returncode != 0 or len(done.stdout) < 64:
        raise MediaError('Não foi possível conferir o arquivo novo; nada foi salvo.')
    return np.frombuffer(done.stdout[:len(done.stdout) // 2 * 2], dtype='<i2').astype(np.float64)


def tone_ratio(samples, hz: int) -> float:
    """Fração da energia (sem o nível contínuo) que está numa faixa de ±10 % em torno de `hz`."""
    import numpy as np
    window = samples - samples.mean()
    spectrum = np.abs(np.fft.rfft(window * np.hanning(len(window)))) ** 2
    total = spectrum.sum()
    if total <= 0:
        return 0.0
    freqs = np.fft.rfftfreq(len(window), 1 / 16000)
    return float(spectrum[(freqs >= hz * 0.9) & (freqs <= hz * 1.1)].sum() / total)


def _check_replaced(exe: str, path: str, ranges: list, options: dict) -> None:
    """Decodifica alguns trechos do arquivo novo: tom → quase toda a energia está na frequência do tom; silêncio → nível abaixo de −50 dB."""
    import math
    longest = max(ranges, key=lambda r: r[1] - r[0])
    for start, end in dict.fromkeys([ranges[0], longest, ranges[-1]]):
        if end - start < 0.12:
            continue
        samples = _window_samples(exe, path, start + 0.04, end - 0.04)
        if options['mode'] == 'mute':
            rms = math.sqrt(float((samples ** 2).mean())) / 32768
            if rms > 10 ** (-50 / 20):
                raise MediaError('A conferência falhou: um trecho que devia ficar mudo ainda tem som; nada foi salvo.')
        elif tone_ratio(samples, TONES[options['tone']]) < TONE_MIN_RATIO:
            raise MediaError('A conferência falhou: um trecho que devia ter o tom ainda tem o som original; nada foi salvo.')


def _verify(before: dict, after: dict, kind: str, channels: int, keep: bool) -> None:
    if keep:
        audiochannels._verify(before, after, kind, channels)
        return
    audiochannels._verify({**before, 'tags': {}}, after, kind, channels)
    if after.get('tags') or after.get('extra_tags') or after.get('has_cover'):
        raise MediaError('A conferência falhou: ainda restaram etiquetas ou capa no arquivo novo; nada foi salvo.')


def apply(source: Path, stage: Path, job: dict) -> dict:
    """Grava em `stage` o áudio com os trechos substituídos. Devolve `{'suffix', 'name', 'notes'}`."""
    options = options_from(job)
    exe = mediatools.find_tool('ffmpeg')
    if not exe or not mediatools.find_tool('ffprobe'):
        raise MediaError('O FFmpeg não foi encontrado neste computador. Instale-o (veja docs/DEPENDENCIAS.md) e tente de novo.')
    info = mediatools.probe(source)
    kind = audiotags.kind_of(info)
    spec = audioconvert.FORMATS[kind]
    channels = int(info.get('channels') or 0)
    if not 1 <= channels <= 8:
        raise MediaError('Não foi possível saber quantos canais o áudio tem (ou passam de 8).')
    ranges, warnings = plan_ranges(options['ranges'], info['duration'])
    build = mediatools.build_info()
    if build and build.get('encoders') is not None and not set(mediatools.OUTPUT_ENCODERS[kind]) & set(build['encoders']):
        raise MediaError(f'Este FFmpeg não tem o codificador de {spec["label"]}.')
    if audioconvert.estimate_bytes(kind, options['quality'], info) > audioconvert.MAX_OUTPUT_BYTES * audioconvert.SAFETY_MARGIN:
        raise MediaError('A saída passaria do limite de 512 MiB; escolha um arquivo menor.')
    if stage.exists():
        raise MediaError('A pasta de preparo já tem um arquivo de saída.')
    audioconvert._run(exe, build_args(str(source.resolve()), str(stage.resolve()), kind, info, options, ranges))
    if not stage.is_file() or stage.is_symlink() or stage.stat().st_size == 0:
        raise MediaError('A operação não gerou nenhum arquivo.')
    try:
        _verify(info, mediatools.probe(stage), kind, channels, options['tags'] == 'keep')
        _check_replaced(exe, str(stage.resolve()), ranges, options)
    except MediaError:
        stage.unlink(missing_ok=True)
        raise
    total = sum(end - start for start, end in ranges)
    what = 'tom' if options['mode'] == 'tone' else 'silêncio'
    summary = f'Bleep: {len(ranges)} trecho(s), {audiotrim.fmt_time(total)} no total, substituído(s) por {what}. Lembrete: isto não é anonimização garantida; o original continua existindo.'
    return {'suffix': audiotags.KINDS[kind][1], 'name': 'bleep', 'notes': [summary, *warnings]}
