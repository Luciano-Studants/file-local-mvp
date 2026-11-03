"""Diagnóstico do ambiente de desenvolvimento: diz o que está instalado e o que falta. Uso: python tools/doctor.py [--strict]

Itens obrigatórios (Python, pacotes de requirements.txt) fazem o código de saída ser 1; os opcionais (Tesseract,
FFmpeg, LibreOffice, Inno Setup) só avisam, a menos que `--strict` seja usado.
"""
import importlib.metadata as md
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def required_packages(path=None):
    """Lê `requirements.txt` e devolve [(nome, especificação)] aplicáveis a esta plataforma."""
    pins = []
    for raw in (path or ROOT / 'requirements.txt').read_text(encoding='utf-8').splitlines():
        line = raw.split('#', 1)[0].strip()
        if not line:
            continue
        spec, _, marker = line.partition(';')
        if marker.strip() == 'sys_platform == "win32"' and sys.platform != 'win32':
            continue
        match = re.match(r'^([A-Za-z0-9_.\-]+)\s*(.*)$', spec.strip())
        if match:
            pins.append((match.group(1), match.group(2).strip()))
    return pins


def check_package(name, spec):
    try:
        version = md.version(name)
    except md.PackageNotFoundError:
        return False, 'não instalado'
    if spec.startswith('==') and version != spec[2:]:
        return False, f'instalado {version}, esperado {spec[2:]}'
    return True, version


def tool_version(command, args=('--version',)):
    exe = shutil.which(command)
    if not exe:
        return None
    try:
        out = subprocess.run([exe, *args], capture_output=True, text=True, timeout=20)
        return (out.stdout or out.stderr).strip().splitlines()[0] if (out.stdout or out.stderr).strip() else exe
    except (OSError, subprocess.SubprocessError):
        return exe


def find_tesseract():
    sys.path.insert(0, str(ROOT))
    try:
        import ocr
        return ocr.find_tesseract()
    except Exception:   # noqa: BLE001 - diagnóstico não pode quebrar
        return shutil.which('tesseract')
    finally:
        sys.path.pop(0)


def run():
    required, optional = [], []
    ok = sys.version_info[:2] in ((3, 12), (3, 13))
    required.append(('Python 3.12/3.13', ok, sys.version.split()[0]))
    for name, spec in required_packages():
        good, detail = check_package(name, spec)
        required.append((name, good, detail))
    tess = find_tesseract()
    optional.append(('Tesseract (OCR)', bool(tess), str(tess) if tess else 'instale: winget install UB-Mannheim.TesseractOCR (Windows) / apt install tesseract-ocr'))
    tessdata = ROOT / 'tessdata'
    langs = sorted(p.stem for p in tessdata.glob('*.traineddata')) if tessdata.is_dir() else []
    optional.append(('Dados de idioma do OCR (tessdata/)', {'eng', 'por'} <= set(langs), ', '.join(langs) or 'ausentes'))
    for label, command, hint in (
        ('FFmpeg (categorias de áudio/vídeo, futuro)', 'ffmpeg', 'winget install Gyan.FFmpeg'),
        ('LibreOffice (documentos, opcional)', 'soffice', 'winget install TheDocumentFoundation.LibreOffice'),
    ):
        version = tool_version(command, ('-version',) if command == 'ffmpeg' else ('--version',))
        optional.append((label, bool(version), version or hint))
    if os.name == 'nt':
        inno = shutil.which('iscc') or next((p for p in (r'C:\Program Files (x86)\Inno Setup 6\ISCC.exe', r'C:\Program Files\Inno Setup 6\ISCC.exe') if Path(p).is_file()), None)
        optional.append(('Inno Setup 6 (instalador)', bool(inno), inno or 'winget install JRSoftware.InnoSetup'))
    for name in ('pyinstaller', 'pip-audit', 'pip-licenses'):
        try:
            optional.append((name + ' (requirements-dev.txt)', True, md.version(name)))
        except md.PackageNotFoundError:
            optional.append((name + ' (requirements-dev.txt)', False, 'python -m pip install -r requirements-dev.txt'))
    return required, optional


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    strict = '--strict' in argv
    required, optional = run()
    print('== Obrigatórios ==')
    for name, good, detail in required:
        print(f"  [{'OK' if good else 'FALTA'}] {name}: {detail}")
    print('== Opcionais ==')
    for name, good, detail in optional:
        print(f"  [{'OK' if good else 'aviso'}] {name}: {detail}")
    failed = [n for n, good, _ in required if not good]
    warned = [n for n, good, _ in optional if not good]
    if failed:
        print('\nFaltam itens obrigatórios: ' + ', '.join(failed) + '\nCorrija com: python -m pip install -r requirements.txt')
    elif warned:
        print('\nTudo o que é obrigatório está instalado. Itens opcionais ausentes: ' + ', '.join(warned))
    else:
        print('\nAmbiente completo.')
    return 1 if failed or (strict and warned) else 0


if __name__ == '__main__':
    raise SystemExit(main())
