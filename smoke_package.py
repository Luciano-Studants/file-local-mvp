"""Smoke-test the generated Windows GUI and one packaged image conversion."""
import json
import os
import subprocess
import tempfile
from pathlib import Path

from PIL import Image

if os.name != 'nt':
    raise SystemExit('Execute este teste em Windows; o pacote Windows não pode ser validado no Sandbox Linux.')

root = Path(__file__).resolve().parent
executable = root / 'dist' / 'ArquivoLocal' / 'ArquivoLocal.exe'
subprocess.run([str(executable), '--smoke-test'], check=True, timeout=30)

with tempfile.TemporaryDirectory() as folder:
    source = Path(folder) / 'entrada.png'
    Image.new('RGB', (20, 20), 'orange').save(source)
    result = subprocess.run(
        [str(executable), '--worker'],
        input=json.dumps({'paths': [str(source)], 'target': 'JPEG', 'output': folder}),
        text=True,
        capture_output=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr or result.stdout)
    data = json.loads(result.stdout)
    assert data['ok'], data
    output = Path(data['outputs'][0])
    with Image.open(output) as image:
        assert image.size == (20, 20)

print('PASS: janela empacotada e conversão PNG para JPEG no worker')
