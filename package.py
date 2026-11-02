"""Build a portable Windows folder with corresponding source and notices."""
import hashlib
import importlib.metadata
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from engine import VERSION

root = Path(__file__).resolve().parent
os.chdir(root)
if os.name != 'nt':
    raise SystemExit('Execute este script no Windows para gerar o pacote Windows.')
# OCR (0.9.22): os dados de idioma sempre entram; o programa Tesseract do Windows entra se a pasta «tesseract» (tesseract.exe + DLLs) estiver ao lado deste script.
data_args = ['--add-data', f'tessdata{os.pathsep}tessdata', '--add-data', f'models{os.pathsep}models']       # models/: u2netp.onnx da remoção de fundo (0.9.25)
if (root / 'tesseract' / 'tesseract.exe').is_file():
    data_args += ['--add-data', f'tesseract{os.pathsep}tesseract']
else:
    print('AVISO: pasta «tesseract» ausente; o pacote sairá sem o programa de OCR (o OCR fica indisponível até instalá-lo).')
subprocess.run([
    sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir',
    '--name', 'ArquivoLocal', '--collect-all', 'pypdf', '--collect-all', 'resvg_py', '--collect-all', 'pillow_heif', '--collect-all', 'pypdfium2', '--collect-all', 'pypdfium2_raw', '--collect-all', 'onnxruntime', '--collect-all', 'numpy',
    '--hidden-import', 'win32com.client', '--hidden-import', 'pythoncom',
    '--hidden-import', 'pywintypes', '--hidden-import', 'win32gui',
    '--hidden-import', 'vector_qt', '--hidden-import', 'vector_resvg', '--hidden-import', 'pillow_heif', '--hidden-import', 'PySide6.QtSvg', '--hidden-import', 'ocr', '--hidden-import', 'illustrator', '--hidden-import', 'metafile', '--hidden-import', 'bgremove', '--hidden-import', 'winjob', '--hidden-import', 'pdfinfo', '--hidden-import', 'pdfcompress', '--hidden-import', 'pdfstamp', '--hidden-import', 'pdfredact', '--hidden-import', 'pdfform', '--hidden-import', 'cryptography', '--hidden-import', 'pdf_stage', '--hidden-import', 'page_organizer', '--hidden-import', 'onnxruntime', '--hidden-import', 'pypdfium2', *data_args, 'app.py',
], check=True)

dest = root / 'dist' / 'ArquivoLocal'
licenses = dest / 'licenses'
licenses.mkdir(exist_ok=True)
shutil.copyfile(root.parent / 'LICENSE', dest / 'LICENSE')
shutil.copyfile(root.parent / 'LICENSE', licenses / 'GPL-3.0.txt')
shutil.copyfile(root / 'README.md', dest / 'LEIA-ME.md')
shutil.copyfile(root / 'NOTICE', dest / 'NOTICE')
shutil.copyfile(root / 'THIRD_PARTY_NOTICES.md', dest / 'THIRD_PARTY_NOTICES.md')
shutil.copytree(root / 'licenses', licenses / 'explicit', dirs_exist_ok=True)

source = dest / 'source' / 'Desktop'
source.mkdir(parents=True, exist_ok=True)
shutil.copyfile(root.parent / 'LICENSE', dest / 'source' / 'LICENSE')
shutil.copyfile(root / 'NOTICE', dest / 'source' / 'NOTICE')
shutil.copyfile(root / 'THIRD_PARTY_NOTICES.md', dest / 'source' / 'THIRD_PARTY_NOTICES.md')
shutil.copyfile(root.parent / 'PROJECT_GOALS.md', dest / 'source' / 'PROJECT_GOALS.md')
shutil.copyfile(root.parent / 'IMPLEMENTATION_ROADMAP.md', dest / 'source' / 'IMPLEMENTATION_ROADMAP.md')
shutil.copyfile(root / 'README.md', source / 'README.md')
shutil.copyfile(root / 'RELEASE.md', source / 'RELEASE.md')
shutil.copyfile(root / 'NOTICE', source / 'NOTICE')
shutil.copyfile(root / 'THIRD_PARTY_NOTICES.md', source / 'THIRD_PARTY_NOTICES.md')
shutil.copytree(root / 'licenses', source / 'licenses', dirs_exist_ok=True)
shutil.copytree(root / 'models', source / 'models', dirs_exist_ok=True)           # modelo da remoção de fundo (0.9.25)
shutil.copytree(root / 'tessdata', source / 'tessdata', dirs_exist_ok=True)      # dados de idioma do OCR (0.9.22)
shutil.copytree(root / 'tests', source / 'tests', ignore=shutil.ignore_patterns('__pycache__'))
shutil.copytree(root / 'tools', source / 'tools', ignore=shutil.ignore_patterns('__pycache__'), dirs_exist_ok=True)           # suíte de qualidade de imagem (0.9.26)
shutil.copytree(root / 'instalador', source / 'instalador', dirs_exist_ok=True)          # kit de instalação do Windows (0.9.26)
for path in root.glob('*.py'):
    shutil.copyfile(path, source / path.name)
shutil.copyfile(root / 'requirements.txt', source / 'requirements.txt')

versions = {}
for name in ['Pillow', 'pypdf', 'cryptography', 'cffi', 'pycparser', 'resvg-py', 'pillow-heif', 'pypdfium2', 'numpy', 'onnxruntime', 'PySide6-Essentials', 'shiboken6', 'pywin32', 'pyinstaller']:
    distribution = importlib.metadata.distribution(name)
    versions[name] = distribution.version
    for item in distribution.files or []:
        if 'license' in str(item).lower() or 'copying' in str(item).lower():
            license_file = Path(distribution.locate_file(item))
            if license_file.is_file():
                target = licenses / name / str(item).replace('..', '_')
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(license_file, target)
(dest / 'dependencies.json').write_text(json.dumps(versions, indent=2), encoding='utf-8')

archive_base = root / 'dist' / f'Arquivo-Local-{VERSION}-Windows-x64'
archive = shutil.make_archive(str(archive_base), 'zip', root_dir=root / 'dist', base_dir='ArquivoLocal')
archive_path = Path(archive)
archive_path.with_name(archive_path.name + '.sha256').write_text(
    hashlib.sha256(archive_path.read_bytes()).hexdigest() + '  ' + archive_path.name + '\n',
    encoding='ascii',
)
print(archive)
