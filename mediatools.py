"""Base de mídia (0.9.43): localizar o FFmpeg/ffprobe, conferir a licença e as capacidades do build e ler as informações de um áudio.

Núcleo puro (sem Qt, sem importar o motor): erros são `MediaError` e o motor os converte em `ConversionError`.
O FFmpeg NÃO é carregado dentro do processo: é chamado como programa separado, sem shell, sem rede (`-protocol_whitelist file`),
sem ler o teclado, com tempo máximo e saída limitada. Procura-se, nesta ordem: a pasta `ffmpeg/` (ou `ffmpeg/bin/`) ao lado do
aplicativo (pacote do Windows) e o PATH do sistema (Linux: `apt install ffmpeg`).

Licença: o pacote distribuído usa um build **LGPL** (sem `--enable-gpl`/`--enable-nonfree`). Um build GPL funciona para desenvolver
e testar, mas `capability_report()` avisa que ele não pode ser distribuído com o aplicativo.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

PROBE_TIMEOUT = 30                       # segundos de relógio para ler um arquivo
INFO_TIMEOUT = 20                        # segundos para `-version`/`-encoders`
MAX_OUTPUT = 4 * 1024 * 1024             # bytes aceitos da saída de um programa de mídia
MAX_STREAMS = 32                         # fluxos por arquivo (acima disso o arquivo é recusado)
MAX_DURATION = 24 * 3600                 # segundos; acima disso o arquivo é recusado
MAX_TAG = 200                            # caracteres por etiqueta mostrada
TAG_KEYS = ('title', 'artist', 'album', 'album_artist', 'date', 'genre', 'track', 'disc', 'composer', 'comment')

# codificadores de áudio necessários para as saídas planejadas (formato → codificadores aceitos, em ordem de preferência)
OUTPUT_ENCODERS = {
    'mp3': ('libmp3lame',), 'm4a': ('aac',), 'flac': ('flac',), 'ogg': ('libvorbis',), 'opus': ('libopus',),
    'wav': ('pcm_s16le',), 'aiff': ('pcm_s16be',),
}

_EXE = {'ffmpeg': 'ffmpeg.exe' if os.name == 'nt' else 'ffmpeg', 'ffprobe': 'ffprobe.exe' if os.name == 'nt' else 'ffprobe'}
_cache: dict = {}


class MediaError(ValueError):
    pass


def app_dirs():
    """Pastas onde procurar `ffmpeg/`: ao lado deste módulo e, em pacote do PyInstaller, no diretório de dados/executável."""
    dirs = [Path(__file__).resolve().parent]
    for raw in (getattr(sys, '_MEIPASS', None), Path(sys.executable).parent if getattr(sys, 'frozen', False) else None):
        if raw and Path(raw).resolve() not in dirs:
            dirs.append(Path(raw).resolve())
    return dirs


def find_tool(name: str):
    """Caminho absoluto de `ffmpeg` ou `ffprobe`, ou None."""
    if name not in _EXE:
        raise ValueError('programa de mídia desconhecido')
    if name in _cache:
        return _cache[name]
    candidates = []
    for base in app_dirs():
        candidates += [base / 'ffmpeg' / _EXE[name], base / 'ffmpeg' / 'bin' / _EXE[name]]
    found = shutil.which(name)
    if found:
        candidates.append(Path(found))
    result = next((str(path.resolve()) for path in candidates if path.is_file()), None)
    _cache[name] = result
    return result


def reset_cache() -> None:
    _cache.clear()


def _clean_env() -> dict:
    env = {key: value for key, value in os.environ.items() if key.upper() not in ('FFREPORT', 'FFMPEG_DATADIR')}
    env['LC_ALL'] = 'C'
    return env


def run_tool(exe: str, args: list, timeout: float = INFO_TIMEOUT) -> str:
    """Executa o programa sem shell, sem teclado e com tempo máximo; devolve a saída padrão (texto)."""
    command = [exe, '-hide_banner', *args]      # stdin já é o DEVNULL (o ffprobe não aceita -nostdin; as conversões usarão -nostdin no ffmpeg)
    flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0) if os.name == 'nt' else 0
    try:
        done = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout, env=_clean_env(), creationflags=flags, shell=False)
    except subprocess.TimeoutExpired:
        raise MediaError('O programa de áudio demorou demais e foi interrompido.') from None
    except OSError:
        raise MediaError('Não foi possível executar o programa de áudio (FFmpeg).') from None
    if len(done.stdout) > MAX_OUTPUT:
        raise MediaError('O programa de áudio devolveu uma resposta grande demais.')
    if done.returncode != 0:
        raise MediaError('O arquivo não pôde ser lido como áudio ou vídeo.')
    return done.stdout.decode('utf-8', errors='replace')


# ---------------------------------------------------------------------------
# build: versão, licença e codificadores
# ---------------------------------------------------------------------------
def classify_license(configuration: str) -> str:
    """'nonfree' | 'gpl' | 'lgpl' a partir da linha `configuration:` do `-version`."""
    flags = set(configuration.split())
    if '--enable-nonfree' in flags:
        return 'nonfree'
    if '--enable-gpl' in flags:
        return 'gpl'
    return 'lgpl'


def parse_version(text: str) -> dict:
    version = re.search(r'^ff(?:mpeg|probe) version (\S+)', text, re.M)
    configuration = re.search(r'^configuration:(.*)$', text, re.M)
    config = configuration.group(1).strip() if configuration else ''
    return {'version': version.group(1) if version else '', 'configuration': config, 'license': classify_license(config),
            'version3': '--enable-version3' in config.split()}


def parse_encoders(text: str) -> set:
    """Nomes dos codificadores de áudio da saída de `ffmpeg -encoders` (linhas «A..... nome descrição»)."""
    names = set()
    for line in text.splitlines():
        match = re.match(r'^\s*A[\.A-Z]{5}\s+(\S+)\s', line)
        if match and match.group(1) != '=':          # a linha de legenda «A..... = Audio» não é um codificador
            names.add(match.group(1))
    return names


def build_info(refresh: bool = False) -> dict | None:
    """Versão, licença e codificadores de áudio do FFmpeg encontrado (None se não houver)."""
    if 'build' in _cache and not refresh:
        return _cache['build']
    exe = find_tool('ffmpeg')
    info = None
    if exe:
        info = parse_version(run_tool(exe, ['-version']))
        encoders = parse_encoders(run_tool(exe, ['-encoders']))
        info['encoders'] = sorted(encoders)
        info['outputs'] = sorted(fmt for fmt, names in OUTPUT_ENCODERS.items() if any(name in encoders for name in names))
        info['exe'] = exe
    _cache['build'] = info
    return info


def capability() -> tuple:
    """(disponível, motivo) para a trava da interface; não executa conversão."""
    ffmpeg, ffprobe = find_tool('ffmpeg'), find_tool('ffprobe')
    if not ffmpeg or not ffprobe:
        faltam = ' e '.join(name for name, path in (('ffmpeg', ffmpeg), ('ffprobe', ffprobe)) if not path)
        return False, f'Falta o programa de mídia ({faltam}). No Windows ele acompanha o pacote; no Linux instale o pacote «ffmpeg».'
    try:
        info = build_info()
    except MediaError as error:
        return False, str(error)
    if not info or not info['outputs']:
        return False, 'O FFmpeg encontrado não tem codificadores de áudio suficientes.'
    return True, f"FFmpeg {info['version']} ({info['license'].upper()}) com {len(info['outputs'])} formatos de saída."


def capability_report() -> dict:
    """Dados para o diagnóstico: o que foi encontrado e se o build pode ser distribuído."""
    info = build_info()
    if not info:
        return {'found': False, 'distributable': False, 'note': 'FFmpeg não encontrado.'}
    distributable = info['license'] == 'lgpl'
    note = 'Build LGPL: pode acompanhar o aplicativo.' if distributable else f"Build {info['license'].upper()}: serve para desenvolver e testar, mas NÃO pode acompanhar o aplicativo (use um build LGPL)."
    return {'found': True, 'distributable': distributable, 'note': note, **{key: info[key] for key in ('version', 'license', 'outputs', 'exe')}}


# ---------------------------------------------------------------------------
# leitura de um arquivo (ffprobe)
# ---------------------------------------------------------------------------
def _text(value, limit=MAX_TAG) -> str:
    text = ''.join(ch if ch.isprintable() else ' ' for ch in str(value)).strip()
    return text[:limit]


def _number(value, cast=float, default=0):
    try:
        return cast(value)
    except (TypeError, ValueError):
        return default


def parse_probe(data: dict) -> dict:
    """Resumo seguro de um JSON do ffprobe. Levanta `MediaError` se não houver áudio ou se passar dos limites."""
    streams = data.get('streams') or []
    if not isinstance(streams, list) or not streams:
        raise MediaError('Este arquivo não contém nenhum fluxo de áudio ou vídeo.')
    if len(streams) > MAX_STREAMS:
        raise MediaError(f'O arquivo tem fluxos demais ({len(streams)}); o limite é {MAX_STREAMS}.')
    audio = [s for s in streams if s.get('codec_type') == 'audio']
    if not audio:
        raise MediaError('Este arquivo não contém áudio.')
    fmt = data.get('format') or {}
    first = audio[0]
    duration = _number(fmt.get('duration'), float, 0) or _number(first.get('duration'), float, 0)
    if duration > MAX_DURATION:
        raise MediaError('O áudio é longo demais para esta versão (limite de 24 horas).')
    tags = {str(k).lower(): v for k, v in {**(first.get('tags') or {}), **(fmt.get('tags') or {})}.items()}
    # capa embutida aparece como fluxo de vídeo com disposição attached_pic
    has_cover = any(s.get('codec_type') == 'video' and (s.get('disposition') or {}).get('attached_pic') for s in streams)
    video = [s for s in streams if s.get('codec_type') == 'video' and not (s.get('disposition') or {}).get('attached_pic')]
    return {
        'container': _text(fmt.get('format_name', ''), 60), 'container_label': _text(fmt.get('format_long_name', ''), 80),
        'duration': round(duration, 3), 'size': _number(fmt.get('size'), int, 0), 'bit_rate': _number(fmt.get('bit_rate'), int, 0),
        'audio_streams': len(audio), 'has_video': bool(video), 'has_cover': has_cover, 'chapters': len(data.get('chapters') or []),
        'codec': _text(first.get('codec_name', ''), 40), 'codec_label': _text(first.get('codec_long_name', ''), 80), 'profile': _text(first.get('profile', ''), 40),
        'sample_rate': _number(first.get('sample_rate'), int, 0), 'channels': _number(first.get('channels'), int, 0),
        'channel_layout': _text(first.get('channel_layout', ''), 40), 'bits_per_sample': _number(first.get('bits_per_sample') or first.get('bits_per_raw_sample'), int, 0),
        'stream_bit_rate': _number(first.get('bit_rate'), int, 0),
        'tags': {key: _text(tags[key]) for key in TAG_KEYS if key in tags and _text(tags[key])},
    }


def probe_args(path: str) -> list:
    return ['-v', 'error', '-protocol_whitelist', 'file', '-print_format', 'json', '-show_format', '-show_streams', '-show_chapters', '-i', 'file:' + path]


def probe(path) -> dict:
    """Informações de um arquivo de áudio (ou vídeo com áudio). Somente leitura."""
    exe = find_tool('ffprobe')
    if not exe:
        raise MediaError('O programa de mídia (ffprobe) não foi encontrado.')
    source = Path(path)
    if source.is_symlink() or not source.is_file():
        raise MediaError('O arquivo de áudio não foi encontrado.')
    if source.stat().st_size == 0:
        raise MediaError('O arquivo está vazio.')
    output = run_tool(exe, probe_args(str(source.resolve())), PROBE_TIMEOUT)
    try:
        data = json.loads(output)
    except ValueError:
        raise MediaError('O arquivo não é um áudio reconhecido.') from None
    if not isinstance(data, dict):
        raise MediaError('O arquivo não é um áudio reconhecido.')
    return parse_probe(data)


def format_duration(seconds: float) -> str:
    total = int(round(seconds))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    return f'{hours}:{minutes:02d}:{secs:02d}' if hours else f'{minutes}:{secs:02d}'
