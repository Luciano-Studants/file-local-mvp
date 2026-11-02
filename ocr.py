"""OCR (reconhecimento de texto em imagens) com o Tesseract, rodando como programa externo e offline.

Núcleo puro (sem Qt): não importa o motor; os erros são `OcrError` e o motor os converte em `ConversionError`.
O Tesseract (Apache-2.0) NÃO é carregado dentro do processo: é chamado como processo separado, sem shell, sem rede,
com a imagem num arquivo temporário e tempo máximo. Procura-se, nesta ordem: a pasta `tesseract/` ao lado do aplicativo
(pacote do Windows) e o PATH do sistema (Linux: `apt install tesseract-ocr`); no Windows também a pasta padrão do instalador.
Os dados de idioma (`tessdata/`: português, inglês e `pdf.ttf`, necessário para o PDF pesquisável) acompanham o aplicativo.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

LANGS = {'por+eng': 'Português + Inglês', 'por': 'Português', 'eng': 'Inglês'}      # id → rótulo (ordem dos botões)
PSM = {'auto': (3, 'Automático'), 'block': (6, 'Bloco único'), 'line': (7, 'Uma linha'), 'sparse': (11, 'Texto esparso')}
OUTPUTS = ('txt', 'pdf')
TIMEOUT = 120                          # segundos de relógio por imagem
MAX_TEXT = 16 * 1024 * 1024            # bytes lidos da saída de texto
MAX_SIDE = 12000                       # lado máximo (px) entregue ao Tesseract; acima disso a imagem é reduzida
MIN_SIDE = 1000                        # abaixo disso (nos dois lados) o texto é ampliado 2× antes de reconhecer
DPI = 300

_EXE_NAME = 'tesseract.exe' if os.name == 'nt' else 'tesseract'
_cache: dict = {}


class OcrError(ValueError):
    pass


def app_dirs():
    """Pastas onde procurar `tesseract/` e `tessdata/`: ao lado deste módulo e, em pacote do PyInstaller, no diretório de dados/executável."""
    dirs = [Path(__file__).resolve().parent]
    for raw in (getattr(sys, '_MEIPASS', None), Path(sys.executable).parent if getattr(sys, 'frozen', False) else None):
        if raw and Path(raw).resolve() not in dirs:
            dirs.append(Path(raw).resolve())
    return dirs


def find_tesseract():
    """Caminho absoluto do executável ou None."""
    if 'exe' in _cache:
        return _cache['exe']
    candidates = [base / 'tesseract' / _EXE_NAME for base in app_dirs()]
    found = shutil.which('tesseract')
    if found:
        candidates.append(Path(found))
    if os.name == 'nt':
        for variable in ('ProgramFiles', 'ProgramFiles(x86)'):
            if os.environ.get(variable):
                candidates.append(Path(os.environ[variable]) / 'Tesseract-OCR' / _EXE_NAME)
    result = next((str(path.resolve()) for path in candidates if path.is_file()), None)
    _cache['exe'] = result
    return result


def tessdata_dir():
    """Pasta `tessdata/` do aplicativo, se tiver dados de idioma; senão None (o Tesseract usa a dele)."""
    for base in app_dirs():
        folder = base / 'tessdata'
        if folder.is_dir() and any(folder.glob('*.traineddata')):
            return folder
    return None


def reset_cache():
    _cache.clear()


def _environment():
    environment = dict(os.environ)
    environment['OMP_THREAD_LIMIT'] = '1'              # uma thread: tempo previsível e menos memória virtual
    environment.pop('TESSDATA_PREFIX', None)           # só a pasta escolhida aqui vale
    return environment


def _run(arguments, work, timeout=TIMEOUT):
    flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0) if os.name == 'nt' else 0
    try:
        return subprocess.run(arguments, cwd=str(work), env=_environment(), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              timeout=timeout, creationflags=flags, shell=False)
    except subprocess.TimeoutExpired as error:
        raise OcrError(f'O reconhecimento passou de {timeout} segundos e foi interrompido. Tente uma imagem menor ou recorte a área com texto.') from error
    except OSError as error:
        raise OcrError('Não foi possível executar o Tesseract.') from error


def _data_args():
    folder = tessdata_dir()
    return ['--tessdata-dir', str(folder)] if folder else []


def available_languages():
    """Conjunto de idiomas instalados (ex.: {'por', 'eng'}); vazio se não houver Tesseract."""
    if 'langs' in _cache:
        return _cache['langs']
    exe = find_tesseract()
    langs = set()
    if exe:
        try:
            result = _run([exe, '--list-langs', *_data_args()], Path(tempfile.gettempdir()), timeout=30)
            lines = result.stdout.decode('utf8', 'replace').splitlines()
            langs = {line.strip() for line in lines[1:] if line.strip() and line.strip() != 'osd' and ' ' not in line.strip()}
        except OcrError:
            langs = set()
    _cache['langs'] = langs
    return langs


def status():
    """(pronto, mensagem em português): usado pelo painel e pelo motor."""
    exe = find_tesseract()
    if not exe:
        return False, ('O Tesseract não foi encontrado. No Windows, coloque o programa na pasta «tesseract» ao lado do aplicativo; '
                       'no Linux, instale o pacote «tesseract-ocr». O OCR funciona offline, mas precisa desse programa.')
    if not available_languages():
        return False, 'O Tesseract foi encontrado, mas sem dados de idioma. Copie os arquivos .traineddata (por, eng) para a pasta «tessdata» do aplicativo.'
    return True, ''


def languages_for(lang):
    """Lista de códigos de idioma de uma opção (ex.: 'por+eng' → ['por', 'eng'])."""
    if lang not in LANGS:
        raise OcrError('Idioma de OCR inválido.')
    return lang.split('+')


def check_ready(lang):
    ready, message = status()
    if not ready:
        raise OcrError(message)
    missing = [code for code in languages_for(lang) if code not in available_languages()]
    if missing:
        raise OcrError('Faltam os dados de idioma do Tesseract: ' + ', '.join(missing) + '. Copie os arquivos .traineddata para a pasta «tessdata» do aplicativo.')


def recognize(image_path, lang, psm_id, output, work, base='ocr'):
    """Roda o Tesseract sobre `image_path` (PNG já preparado) e devolve o caminho do resultado dentro de `work`.

    output='txt' → arquivo de texto UTF-8; output='pdf' → PDF com a imagem e a camada de texto invisível.
    """
    if output not in OUTPUTS:
        raise OcrError('Saída de OCR inválida.')
    if psm_id not in PSM:
        raise OcrError('Modo de página de OCR inválido.')
    check_ready(lang)
    exe = find_tesseract()
    work = Path(work)
    out_base = work / base
    arguments = [exe, str(image_path), str(out_base), '-l', lang, '--psm', str(PSM[psm_id][0]), '--oem', '1', '--dpi', str(DPI), *_data_args()]
    if output == 'pdf':
        arguments += ['-c', 'tessedit_create_pdf=1']       # o mesmo que o arquivo de configuração «pdf», que não precisa existir em tessdata
    result = _run(arguments, work)
    produced = out_base.with_suffix('.pdf' if output == 'pdf' else '.txt')
    if result.returncode != 0 or not produced.is_file():
        detail = result.stderr.decode('utf8', 'replace').strip().splitlines()
        if any('pdf.ttf' in line or 'Could not initialize' in line for line in detail) and output == 'pdf':
            raise OcrError('O Tesseract não encontrou o arquivo «pdf.ttf» em «tessdata»; ele é necessário para o PDF pesquisável.')
        raise OcrError('O Tesseract não conseguiu reconhecer esta imagem.' + (' (' + detail[-1][:160] + ')' if detail else ''))
    return produced


def clean_text(raw):
    """Normaliza a saída: quebras de linha \\n, sem avanço de página, sem espaços no fim das linhas e sem linhas vazias repetidas."""
    text = raw.replace('\r\n', '\n').replace('\r', '\n').replace('\f', '\n')
    lines = [line.rstrip() for line in text.split('\n')]
    result, blank = [], 0
    for line in lines:
        blank = blank + 1 if not line else 0
        if blank <= 1:
            result.append(line)
    return '\n'.join(result).strip('\n') + ('\n' if any(result) else '')


def read_text(path):
    data = Path(path).read_bytes()[:MAX_TEXT + 1]
    if len(data) > MAX_TEXT:
        raise OcrError('O texto reconhecido é grande demais.')
    return clean_text(data.decode('utf8', 'replace'))
