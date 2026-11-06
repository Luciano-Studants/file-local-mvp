"""Verify archive checksum plus notices and rebuildable source for the radial app."""
import hashlib
import os
import zipfile
from pathlib import Path

from engine import VERSION

if os.name != 'nt':
    raise SystemExit('Execute este verificador no Windows após gerar o ZIP Windows.')

root = Path(__file__).resolve().parent
archive_path = root / 'dist' / f'Arquivo-Local-{VERSION}-Windows-x64.zip'
checksum_path = archive_path.with_name(archive_path.name + '.sha256')
expected = checksum_path.read_text(encoding='ascii').split()[0]
actual = hashlib.sha256(archive_path.read_bytes()).hexdigest()
assert expected == actual, 'SHA-256 do ZIP não corresponde ao arquivo.'

with zipfile.ZipFile(archive_path) as archive:
    names = set(archive.namelist())
required = [
    'ArquivoLocal/ArquivoLocal.exe',
    'ArquivoLocal/LICENSE',
    'ArquivoLocal/NOTICE',
    'ArquivoLocal/THIRD_PARTY_NOTICES.md',
    'ArquivoLocal/licenses/explicit/LGPL-3.0-only.txt',
    'ArquivoLocal/licenses/explicit/Python-3.12-LICENSE.txt',
    'ArquivoLocal/source/LICENSE',
    'ArquivoLocal/source/NOTICE',
    'ArquivoLocal/source/THIRD_PARTY_NOTICES.md',
    'ArquivoLocal/source/Desktop/README.md',
    'ArquivoLocal/source/Desktop/NOTICE',
    'ArquivoLocal/source/Desktop/THIRD_PARTY_NOTICES.md',
    'ArquivoLocal/source/Desktop/app.py',
    'ArquivoLocal/source/Desktop/tray_app.py',
    'ArquivoLocal/source/Desktop/radial_menu.py',
    'ArquivoLocal/source/Desktop/windows_bridge.py',
    'ArquivoLocal/source/Desktop/engine.py',
    'ArquivoLocal/source/Desktop/ocr.py',
    'ArquivoLocal/source/Desktop/mediatools.py',
    'ArquivoLocal/source/Desktop/audioconvert.py',
    'ArquivoLocal/source/Desktop/audiotags.py',
    'ArquivoLocal/source/Desktop/audiochannels.py',
    'ArquivoLocal/source/Desktop/audiotrim.py',
    'ArquivoLocal/source/Desktop/audionorm.py',
    'ArquivoLocal/source/Desktop/audio_wave.py',
    'ArquivoLocal/source/Desktop/audio_stage.py',
    'ArquivoLocal/source/Desktop/bgremove.py',
    'ArquivoLocal/source/Desktop/winjob.py',
    'ArquivoLocal/source/Desktop/pdfinfo.py',
    'ArquivoLocal/source/Desktop/pdfcompress.py',
    'ArquivoLocal/source/Desktop/pdfstamp.py',
    'ArquivoLocal/source/Desktop/pdfredact.py',
    'ArquivoLocal/source/Desktop/pdfform.py',
    'ArquivoLocal/source/Desktop/pdf_stage.py',
    'ArquivoLocal/source/Desktop/page_organizer.py',
    'ArquivoLocal/source/Desktop/tools/quality_suite.py',
    'ArquivoLocal/source/Desktop/instalador/ArquivoLocal.iss',
    'ArquivoLocal/source/Desktop/instalador/build_windows.ps1',
    'ArquivoLocal/source/Desktop/models/u2netp.onnx',
    'ArquivoLocal/source/Desktop/tessdata/por.traineddata',
    'ArquivoLocal/source/Desktop/tessdata/eng.traineddata',
    'ArquivoLocal/source/Desktop/tessdata/pdf.ttf',
    'ArquivoLocal/source/Desktop/package.py',
    'ArquivoLocal/source/Desktop/requirements.txt',
]
missing = [name for name in required if name not in names]
assert not missing, 'Arquivos ausentes no pacote: ' + ', '.join(missing)
print('PASS: checksum, licenças, avisos e fonte do app radial presentes no ZIP')
