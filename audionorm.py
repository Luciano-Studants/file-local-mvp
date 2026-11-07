"""Normalizar o volume do áudio (EBU R128) com FFmpeg (núcleo puro, sem Qt). Áudio, item 7.

Duas passadas, as duas só com o FFmpeg:
1. **medição** com `loudnorm` (ITU-R BS.1770 / EBU R128): volume integrado em LUFS e pico real (true peak) em dBTP;
2. **correção linear**: um único ganho (`volume=… dB`) calculado a partir da medição. É o mesmo resultado do modo `linear` do `loudnorm`, sem
   o limitador dinâmico dele: a dinâmica da música/fala não é mexida.

Como não há limitador, **alvos que causariam clipping são recusados** (o app diz qual é o volume máximo alcançável sem distorcer). Também
são recusados: áudio mudo ou curto demais para medir, e arquivo que já está no alvo. Depois de gravar, o app mede o arquivo novo e confere
se chegou ao alvo. O áudio é recodificado no mesmo formato (como em «Canais»); etiquetas e capa seguem as mesmas regras.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import audiochannels
import audioconvert
import audiotags
import mediatools
from mediatools import MediaError

# chave → (LUFS, rótulo)
TARGETS = {'ebu': (-23.0, 'EBU R128 (TV e rádio)'), 'podcast': (-16.0, 'Podcast e vídeo'), 'music': (-14.0, 'Música em streaming')}
DEFAULT_TARGET = 'podcast'
TP_LOSSY = -1.5                # dBTP máximo (a recodificação com perda pode passar um pouco do pico medido)
TP_LOSSLESS = -1.0
MIN_LOUDNESS = -69.0           # abaixo disso o app considera «quase mudo»
ALREADY_DB = 0.3               # a menos de 0,3 LU do alvo: nada a fazer
WARN_GAIN_DB = 12.0            # ganho grande amplifica também o ruído de fundo
MAX_GAIN_DB = 30.0
VERIFY_REFUSE_LU = 1.5
VERIFY_WARN_LU = 0.5
MAX_STDERR = 256 * 1024
_BLOCK = re.compile(r'\{[^{}]*\}')


def options_from(job: dict) -> tuple:
    """`(alvo, qualidade)`; a qualidade (baixa/média/alta) só vale para formatos com perda."""
    target = str(job.get('norm_target') or DEFAULT_TARGET)
    quality = str(job.get('audio_quality') or audioconvert.DEFAULT_QUALITY)
    if target not in TARGETS:
        raise MediaError('Escolha o alvo de volume: EBU R128 (−23), podcast (−16) ou música (−14).')
    if quality not in audioconvert.QUALITIES:
        raise MediaError('Qualidade inválida. Escolha baixa, média ou alta.')
    return target, quality


def tp_limit(kind: str) -> float:
    return TP_LOSSY if audioconvert.FORMATS[kind]['lossy'] else TP_LOSSLESS


def parse_loudness(text: str) -> dict:
    """Último bloco JSON do `loudnorm` → `{'i', 'tp', 'lra'}` (LUFS, dBTP, LU; None quando o FFmpeg diz «-inf»). `{}` se não houver bloco."""
    blocks = _BLOCK.findall((text or '').replace('\r', ''))
    for block in reversed(blocks):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        if 'input_i' not in data:
            continue
        out = {}
        for key, name in (('input_i', 'i'), ('input_tp', 'tp'), ('input_lra', 'lra')):
            try:
                value = float(str(data.get(key)))
            except ValueError:
                value = None
            out[name] = value if value is not None and value == value and abs(value) != float('inf') else None
        return out
    return {}


def measure_args(source: str) -> list:
    return ['-nostdin', '-v', 'info', '-nostats', '-protocol_whitelist', 'file', '-format_whitelist', ','.join(mediatools.INPUT_FORMATS), '-i', 'file:' + source,
            '-map', '0:a:0', '-vn', '-af', 'loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json', '-f', 'null', '-']


def measure(exe: str, source: str, timeout: int = audioconvert.CONVERT_TIMEOUT) -> dict:
    flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    try:
        done = subprocess.run([exe, '-hide_banner', *measure_args(source)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                              timeout=timeout, env=mediatools._clean_env(), creationflags=flags, shell=False)
    except subprocess.TimeoutExpired:
        raise MediaError('A medição do volume demorou demais e foi interrompida; tente um arquivo menor.') from None
    except OSError:
        raise MediaError('Não foi possível executar o FFmpeg.') from None
    if done.returncode != 0:
        raise MediaError('O FFmpeg não conseguiu medir este arquivo. Ele pode estar corrompido ou usar um formato sem suporte.')
    levels = parse_loudness(done.stderr[-MAX_STDERR:].decode('utf-8', errors='replace'))
    if not levels:
        raise MediaError('Não foi possível ler a medição de volume do FFmpeg.')
    return levels


def fmt(value, unit: str) -> str:
    return 'mudo' if value is None else f'{value:.1f} {unit}'.replace('.', ',').replace('-', '−')


def plan_gain(levels: dict, target: float, limit: float) -> float:
    """Ganho (dB) que leva o volume integrado ao alvo. Levanta `MediaError` se o áudio não pode ser normalizado (mudo, no alvo, clipping)."""
    loudness, peak = levels.get('i'), levels.get('tp')
    if loudness is None or loudness < MIN_LOUDNESS:
        raise MediaError('O áudio está mudo, quase mudo ou é curto demais (menos de ~0,4 s) para medir o volume; nada foi alterado.')
    gain = round(target - loudness, 2)
    if abs(gain) < ALREADY_DB:
        raise MediaError(f'O áudio já está no alvo ({fmt(loudness, "LUFS")}); não há o que normalizar.')
    if gain > MAX_GAIN_DB:
        raise MediaError(f'Seria preciso aumentar o volume em {fmt(gain, "dB")}, o que amplificaria só ruído; o limite é {fmt(MAX_GAIN_DB, "dB")}.')
    if peak is not None and peak + gain > limit + 0.005:
        reachable = round(limit - peak + loudness, 1)
        raise MediaError(f'Para chegar a {fmt(target, "LUFS")} o pico passaria de {fmt(limit, "dBTP")} e o som distorceria (clipping). '
                         f'Sem distorcer, o máximo para este áudio é {fmt(reachable, "LUFS")}; escolha um alvo mais baixo.')
    return gain


def audio_filter(gain: float) -> str:
    return f'volume={gain:.2f}dB'


def notes(info: dict | None, target: str, quality: str) -> list:
    """Frases (português) sobre o que a operação muda; os valores medidos vêm em `RUN_NOTES`."""
    lufs, label = TARGETS[target]
    out = [f'Alvo: {fmt(lufs, "LUFS")} ({label}). O app mede o volume (EBU R128) e aplica um ganho único: a dinâmica não é alterada e não há limitador, por isso alvos que causariam clipping são recusados.']
    kind = None
    if info:
        try:
            kind = audiotags.kind_of(info)
        except MediaError as error:
            out.append(str(error))
    if kind:
        spec = audioconvert.FORMATS[kind]
        if spec['lossy']:
            out.append(f'{spec["label"]} é um formato com perda: o áudio é recodificado (≈ {audioconvert.BITRATES[kind][quality]} kbps) e perde um pouco de qualidade.')
        elif kind in ('wav', 'aiff'):
            out.append(f'{spec["label"]} é regravado com 16 bits (arquivos de 24 bits ou decimais perdem profundidade).')
        else:
            out.append('FLAC: sem perda de qualidade na recodificação.')
        if info.get('has_cover') and kind in ('ogg', 'opus'):
            out.append(f'A capa embutida de arquivos {spec["label"]} não é copiada (limite do FFmpeg).')
        if info.get('chapters'):
            out.append('Os capítulos não são copiados.')
    out.append('Depois de gravar, o app mede o arquivo novo e confere se chegou ao alvo.')
    out.append('As etiquetas são mantidas quando o formato aceita.')
    out.append('O arquivo original não é alterado; a cópia ganha o sufixo «-normalizado».')
    return out


def apply(source: Path, stage: Path, job: dict) -> dict:
    """Grava em `stage` o áudio normalizado. Devolve `{'suffix', 'name', 'notes'}`."""
    target_key, quality = options_from(job)
    target = TARGETS[target_key][0]
    exe = mediatools.find_tool('ffmpeg')
    if not exe or not mediatools.find_tool('ffprobe'):
        raise MediaError('O FFmpeg não foi encontrado neste computador. Instale-o (veja docs/DEPENDENCIAS.md) e tente de novo.')
    info = mediatools.probe(source)
    kind = audiotags.kind_of(info)
    spec = audioconvert.FORMATS[kind]
    build = mediatools.build_info()
    mediatools.require_filters('normalize')
    if build and build.get('encoders') is not None and not set(mediatools.OUTPUT_ENCODERS[kind]) & set(build['encoders']):
        raise MediaError(f'Este FFmpeg não tem o codificador de {spec["label"]}.')
    if info['duration'] <= 0 and not spec['lossy']:
        raise MediaError('Não foi possível saber a duração do áudio; para evitar um arquivo gigante, a operação foi recusada.')
    if audioconvert.estimate_bytes(kind, quality, info) > audioconvert.MAX_OUTPUT_BYTES * audioconvert.SAFETY_MARGIN:
        raise MediaError('A saída passaria do limite de 512 MiB; escolha um arquivo menor.')
    if stage.exists():
        raise MediaError('A pasta de preparo já tem um arquivo de saída.')
    source_path = str(source.resolve())
    limit = tp_limit(kind)
    before = measure(exe, source_path)
    gain = plan_gain(before, target, limit)
    audioconvert._run(exe, audiochannels.build_args(source_path, str(stage.resolve()), kind, quality, audio_filter(gain), info))
    if not stage.is_file() or stage.is_symlink() or stage.stat().st_size == 0:
        raise MediaError('A operação não gerou nenhum arquivo.')
    warnings = []
    try:
        after_info = mediatools.probe(stage)
        audiochannels._verify(info, after_info, kind, info['channels'])
        after = measure(exe, str(stage.resolve()))
        if after.get('i') is None or abs(after['i'] - target) > VERIFY_REFUSE_LU:
            raise MediaError(f'A conferência falhou: o arquivo novo mede {fmt(after.get("i"), "LUFS")}, longe do alvo de {fmt(target, "LUFS")}; nada foi salvo.')
    except MediaError:
        stage.unlink(missing_ok=True)
        raise
    summary = f'Volume: de {fmt(before["i"], "LUFS")} para {fmt(after["i"], "LUFS")} (alvo {fmt(target, "LUFS")}; ganho {"+" if gain > 0 else ""}{fmt(gain, "dB")}); pico real {fmt(before["tp"], "dBTP")} → {fmt(after.get("tp"), "dBTP")}.'
    warnings.append(summary)
    if abs(after['i'] - target) > VERIFY_WARN_LU:
        warnings.append(f'Atenção: a recodificação com perda deixou o volume {fmt(abs(after["i"] - target), "LU")} longe do alvo.')
    if after.get('tp') is not None and after['tp'] > limit + 0.5:
        warnings.append(f'Atenção: a recodificação com perda fez o pico real passar de {fmt(limit, "dBTP")}; em reprodutores muito sensíveis pode haver distorção leve.')
    if gain > WARN_GAIN_DB:
        warnings.append(f'Atenção: o volume subiu {fmt(gain, "dB")}; o ruído de fundo sobe junto.')
    return {'suffix': audiotags.KINDS[kind][1], 'name': 'normalizado', 'notes': warnings}


def run_op(job: dict, source_file=None) -> dict:
    """`audio_loudness`: um caminho → `{'name', 'i', 'tp', 'lra'}` ou `{'name', 'error'}` (a interface mostra o texto)."""
    if job.get('op') != 'audio_loudness':
        raise MediaError('Operação de áudio desconhecida.')
    raws = job.get('paths')
    if not isinstance(raws, list) or len(raws) != 1:
        raise MediaError('Escolha um arquivo de áudio.')
    name = Path(str(raws[0])).name
    path = (source_file or mediatools._plain_source)(raws[0])
    exe = mediatools.find_tool('ffmpeg')
    if not exe:
        return {'name': name, 'error': 'O FFmpeg não foi encontrado.'}
    try:
        info = mediatools.probe(path)
        audiotags.kind_of(info)
        if info['duration'] > 4 * 3600:
            return {'name': name, 'error': 'Áudio longo demais para medir aqui; a medição acontece ao normalizar.'}
        return {'name': name, **measure(exe, str(Path(path).resolve()), 200)}
    except MediaError as error:
        return {'name': name, 'error': str(error)}
