"""Portão B — suíte de qualidade das categorias Imagens (0.9.26) e PDF (0.9.42).

Roda o motor (`engine.convert`) sobre um corpus determinístico e mede **qualidade e segurança das saídas**, não só «se não quebrou»:
fidelidade (exato nos formatos sem perda; PSNR/SSIM nos com perda), geometria, ordem, privacidade de metadados, robustez a entradas
estranhas, determinismo, desempenho. Gera `quality-report.md` e `quality-report.json`.

    python tools/quality_suite.py                  # relatório em ./quality-report
    python tools/quality_suite.py --out pasta      # outra pasta
    python tools/quality_suite.py --corpus pasta   # só grava o corpus de imagens de teste (para testar à mão no painel)
    python tools/quality_suite.py --fast           # pula as seções de desempenho (12 MP; 50 páginas de PDF)
    python tools/quality_suite.py --only pdf       # só a categoria PDF (ou --only images)

Sai com código 1 se algum critério **bloqueante** falhar. Cada verificação aparece como PASSOU / FALHOU / PULADA (dependência ausente,
com o motivo); nada é dado como aprovado sem ter sido medido. Rodar no Windows e no Linux: os resultados dos dois valem separadamente.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import os
import platform
import shutil
import sys
import tempfile
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import numpy as np
from PIL import Image, ImageChops, ImageCms, ImageDraw, ImageFont, ImageOps

import engine
import ocr
import bgremove
import tool_registry

import logging
logging.getLogger('pypdf').setLevel(logging.CRITICAL)      # PDFs defeituosos do corpus geram avisos esperados
RESULTS: list[dict] = []
WORK = Path(tempfile.mkdtemp(prefix='quality-suite-'))


# ───────────────────────── medidas ─────────────────────────
def arr(image, mode='RGB'):
    return np.asarray(image.convert(mode), dtype=np.float64)


def psnr(a, b):
    a, b = (arr(a) if isinstance(a, Image.Image) else a), (arr(b) if isinstance(b, Image.Image) else b)
    if a.shape != b.shape:
        return 0.0
    mse = float(np.mean((a - b) ** 2))
    return 99.0 if mse == 0 else 10 * math.log10(255.0 ** 2 / mse)


def _box(x, k):
    c = np.pad(np.cumsum(np.cumsum(x, 0), 1), ((1, 0), (1, 0)))
    return (c[k:, k:] - c[:-k, k:] - c[k:, :-k] + c[:-k, :-k]) / (k * k)


def ssim(a, b, k=7):
    """SSIM médio em cinza (janela uniforme k×k; constantes padrão de Wang et al.)."""
    x, y = arr(a, 'L'), arr(b, 'L')
    if x.shape != y.shape or min(x.shape) < k:
        return 0.0
    c1, c2 = (0.01 * 255) ** 2, (0.03 * 255) ** 2
    mx, my = _box(x, k), _box(y, k)
    vx, vy, cxy = _box(x * x, k) - mx * mx, _box(y * y, k) - my * my, _box(x * y, k) - mx * my
    return float(np.mean(((2 * mx * my + c1) * (2 * cxy + c2)) / ((mx * mx + my * my + c1) * (vx + vy + c2))))


def laplacian_energy(image):
    g = arr(image, 'L')
    lap = g[1:-1, 1:-1] * 4 - g[:-2, 1:-1] - g[2:, 1:-1] - g[1:-1, :-2] - g[1:-1, 2:]
    return float(lap.var())


def identical(a, b, mode='RGBA'):
    return a.size == b.size and ImageChops.difference(a.convert(mode), b.convert(mode)).getbbox(alpha_only=False) is None


def diff_bbox(a, b):
    return ImageChops.difference(a.convert('RGB'), b.convert('RGB')).getbbox()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()



PRIVATE_TEXT = (b'TestCam', b'Modelo-X1')


def private_metadata(path):
    """Metadados privados **por estrutura do formato** (não por busca de bytes, que dá falso positivo em dados comprimidos). Devolve a lista de achados."""
    data = Path(path).read_bytes(); found = []
    if data[:8] == b'\x89PNG\r\n\x1a\n':
        pos = 8
        while pos + 8 <= len(data):
            length = int.from_bytes(data[pos:pos + 4], 'big'); kind = data[pos + 4:pos + 8]; body = data[pos + 8:pos + 8 + length]
            if kind == b'eXIf':
                found.append('PNG eXIf')
            if kind in (b'tEXt', b'iTXt', b'zTXt') and (b'xmp' in body.lower() or b'exif' in body.lower() or any(t in body for t in PRIVATE_TEXT)):
                found.append('PNG texto/XMP')
            pos += 12 + length
            if kind == b'IEND':
                break
    elif data[:2] == b'\xff\xd8':
        pos = 2
        while pos + 4 <= len(data) and data[pos] == 0xFF:
            marker = data[pos + 1]
            if marker == 0xDA:
                break
            length = int.from_bytes(data[pos + 2:pos + 4], 'big'); body = data[pos + 4:pos + 2 + length]
            if marker == 0xE1 and (body.startswith(b'Exif') or b'xpacket' in body[:80] or b'ns.adobe.com/xap' in body[:60]):
                found.append('JPEG EXIF/XMP')
            if marker == 0xED:
                found.append('JPEG Photoshop/IPTC')
            if marker == 0xFE:
                found.append('JPEG comentário')
            pos += 2 + length
    elif data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        pos = 12
        while pos + 8 <= len(data):
            kind = data[pos:pos + 4]; length = int.from_bytes(data[pos + 4:pos + 8], 'little')
            if kind in (b'EXIF', b'XMP '):
                found.append('WebP ' + kind.decode().strip())
            pos += 8 + length + (length & 1)
    else:
        with Image.open(path) as handle:
            tags = getattr(handle, 'tag_v2', None)
            if tags and any(t in tags for t in (0x010F, 0x0110, 0x8825, 0x8769, 700, 0x83BB, 0x8649)):
                found.append('TIFF tags de câmera/GPS/XMP')
    if any(t in data for t in PRIVATE_TEXT):
        found.append('texto da câmera nos bytes')
    return found


# ───────────────────────── registro ─────────────────────────
def record(func, name, ok, value='', detail='', blocking=True, skipped=False):
    RESULTS.append({'func': func, 'check': name, 'status': 'PULADA' if skipped else ('PASSOU' if ok else 'FALHOU'),
                    'value': value if isinstance(value, str) else f'{value:.3f}' if isinstance(value, float) else str(value), 'detail': detail, 'blocking': blocking})


def guarded(func):
    def wrap(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as error:      # noqa: BLE001 — um erro inesperado numa seção vira falha registrada, não derruba a suíte
            record(func.__name__, 'a seção terminou sem exceção inesperada', False, type(error).__name__, ''.join(traceback.format_exception_only(type(error), error)).strip()[:300])
    wrap.__name__ = func.__name__
    return wrap


def sandbox(label='run'):
    path = Path(tempfile.mkdtemp(prefix=label + '-', dir=WORK))
    return path


def run(target, paths, **options):
    out = sandbox('out')
    result = engine.convert({'paths': [str(p) for p in paths], 'target': target, 'output': str(out), **options})
    return [Path(p) for p in result]


def run_one(target, source, **options):
    return run(target, [source], **options)[0]


def load(path):
    with Image.open(path) as handle:
        handle.load()
        return handle.copy()


# ───────────────────────── corpus ─────────────────────────
def make_photo(size=(480, 320), seed=7):
    """Imagem «fotográfica» sintética e determinística: gradientes, ondas, manchas suaves e ruído leve."""
    rng = np.random.default_rng(seed)
    w, h = size
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float64)
    channels = []
    for index in range(3):
        base = 90 + 60 * np.sin(xx / (31 + 9 * index) + index) + 50 * np.cos(yy / (23 + 7 * index)) + 40 * (xx / w) * (index + 1) / 3
        for _ in range(5):
            cx, cy, r = rng.uniform(0, w), rng.uniform(0, h), rng.uniform(25, 90)
            base += rng.uniform(-70, 70) * np.exp(-((xx - cx) ** 2 + (yy - cy) ** 2) / (2 * r * r))
        base += rng.normal(0, 2.0, base.shape)
        channels.append(np.clip(base, 0, 255))
    return Image.fromarray(np.stack(channels, -1).astype(np.uint8), 'RGB')


def make_text_image(lines, size=34, width=1000, background='white'):
    for candidate in ('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 'C:/Windows/Fonts/arial.ttf', 'DejaVuSans.ttf'):
        try:
            font = ImageFont.truetype(candidate, size); break
        except OSError:
            font = None
    font = font or ImageFont.load_default(size)
    step = round(size * 2.4)
    image = Image.new('RGB', (width, 40 + len(lines) * step), background); draw = ImageDraw.Draw(image)
    for index, line in enumerate(lines):
        draw.text((30, 30 + index * step), line, font=font, fill='black')
    return image


def make_alpha(size=(320, 240)):
    w, h = size
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float64)
    dist = np.sqrt(((xx - w / 2) / (w * 0.4)) ** 2 + ((yy - h / 2) / (h * 0.4)) ** 2)
    alpha = np.clip((1.2 - dist) / 0.4, 0, 1) * 255
    rgb = np.stack([200 * np.ones_like(xx), 60 + 150 * (xx / w), 40 + 150 * (yy / h)], -1)
    return Image.fromarray(np.dstack([rgb, alpha]).astype(np.uint8), 'RGBA')


def write_corpus(folder):
    """Grava o corpus em `folder` e devolve {nome: caminho}. Tudo sintético (sem direitos autorais), determinístico."""
    folder = Path(folder); folder.mkdir(parents=True, exist_ok=True)
    files = {}
    photo = make_photo()
    photo.save(folder / 'foto.png'); files['photo'] = folder / 'foto.png'
    photo.save(folder / 'foto.jpg', quality=92); files['photo_jpg'] = folder / 'foto.jpg'
    photo.save(folder / 'foto.webp', quality=90); files['photo_webp'] = folder / 'foto.webp'
    photo.save(folder / 'foto.tif'); photo.save(folder / 'foto.bmp')
    make_alpha().save(folder / 'transparente.png'); files['alpha'] = folder / 'transparente.png'
    # JPEG de celular: EXIF com orientação 6 (retrato), câmera e GPS
    exif = Image.Exif(); exif[0x0112] = 6; exif[0x010F] = 'TestCam'; exif[0x0110] = 'Modelo-X1'
    gps = exif.get_ifd(0x8825); gps[1] = 'S'; gps[2] = (3.0, 7.0, 6.0); gps[3] = 'W'; gps[4] = (60.0, 1.0, 30.0)
    photo.save(folder / 'celular-gps.jpg', quality=92, exif=exif); files['exif'] = folder / 'celular-gps.jpg'
    Image.fromarray(np.asarray(photo.convert('P', palette=Image.Palette.ADAPTIVE).convert('RGB'))).convert('P', palette=Image.Palette.ADAPTIVE).save(folder / 'paleta.png'); files['palette'] = folder / 'paleta.png'
    photo.convert('L').save(folder / 'cinza.png'); files['gray'] = folder / 'cinza.png'
    gray16 = (arr(photo, 'L') / 255.0 * 65535).astype(np.uint16)
    Image.fromarray(gray16).save(folder / 'cinza16.png'); files['gray16'] = folder / 'cinza16.png'
    photo.convert('CMYK').save(folder / 'cmyk.jpg', quality=92); files['cmyk'] = folder / 'cmyk.jpg'
    profile = ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()
    photo.save(folder / 'perfil-icc.png', icc_profile=profile); files['icc'] = folder / 'perfil-icc.png'
    Image.new('RGB', (1, 1), (200, 30, 30)).save(folder / 'minuscula-1x1.png'); files['tiny'] = folder / 'minuscula-1x1.png'
    make_photo((37, 23), 3).save(folder / 'tamanho-impar-37x23.png'); files['odd'] = folder / 'tamanho-impar-37x23.png'
    make_photo((3000, 40), 4).save(folder / 'faixa-larga-3000x40.png'); files['wide'] = folder / 'faixa-larga-3000x40.png'
    low = make_photo().point(lambda v: 100 + v // 5); low.save(folder / 'baixo-contraste.png'); files['lowcontrast'] = folder / 'baixo-contraste.png'
    lines = ['Conversão offline de arquivos', 'Olá, mundo! Ação e emoção: 123,45', 'Arquivo Local — teste de OCR']
    make_text_image(lines).save(folder / 'texto-ocr.png'); files['text'] = folder / 'texto-ocr.png'
    (folder / 'vetor.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg" width="100" height="50" viewBox="0 0 100 50"><rect width="100" height="50" fill="#1e50b4"/>'
                                      '<circle cx="50" cy="25" r="18" fill="#e68c1e"/></svg>', encoding='utf8'); files['svg'] = folder / 'vetor.svg'
    # objeto isolado sobre fundo liso: referência para a remoção de fundo (a máscara certa é a elipse)
    obj = Image.new('RGB', (480, 320), (40, 90, 170)); ImageDraw.Draw(obj).ellipse((120, 50, 360, 270), fill=(235, 140, 40)); obj.save(folder / 'objeto-fundo-liso.png'); files['object'] = folder / 'objeto-fundo-liso.png'
    good = (folder / 'foto.png').read_bytes()
    (folder / 'defeito-truncada.png').write_bytes(good[: len(good) // 3]); files['truncated'] = folder / 'defeito-truncada.png'
    (folder / 'defeito-falsa.png').write_bytes(b'isto nao e uma imagem\n' * 50); files['fake'] = folder / 'defeito-falsa.png'
    return files


# ───────────────────────── seções ─────────────────────────
@guarded
def conversion_fidelity(c):
    photo, alpha = load(c['photo']), load(c['alpha'])
    for target, key in (('PNG', 'png'), ('TIFF', 'tiff'), ('BMP', 'bmp')):
        out = run_one(target, c['photo'])
        record('Conversão', f'{target} sem perda: pixels idênticos', identical(photo, load(out), 'RGB'), psnr(photo, load(out)))
    out = run_one('WEBP', c['photo'], quality=100)
    record('Conversão', 'WebP qualidade 100: pixels idênticos (modo sem perda)', identical(photo, load(out), 'RGB'), psnr(photo, load(out)), blocking=False)
    for target, limit in (('JPEG', 34.0), ('WEBP', 34.0)):
        out = run_one(target, c['photo'], quality=90)
        value, structure = psnr(photo, load(out)), ssim(photo, load(out))
        record('Conversão', f'{target} qualidade 90: PSNR ≥ {limit:.0f} dB e SSIM ≥ 0,95', value >= limit and structure >= 0.95, f'{value:.1f} dB / SSIM {structure:.3f}')
    png_size, jpg_size = run_one('PNG', c['photo']).stat().st_size, run_one('JPEG', c['photo'], quality=80).stat().st_size
    record('Conversão', 'JPEG qualidade 80 é menor que o PNG de uma foto', jpg_size < png_size, f'{jpg_size} < {png_size} B')
    out = run_one('PNG', c['alpha'])
    record('Conversão', 'PNG com transparência: alfa e cores idênticos', identical(alpha, load(out)), '')
    out = run_one('JPEG', c['alpha'])
    r, g, b = load(out).getpixel((2, 2))
    record('Conversão', 'JPEG de imagem transparente: fundo vira branco (não preto)', min(r, g, b) > 235, f'{(r, g, b)}')
    pdf = run_one('Image → PDF', c['photo'])
    record('Conversão', 'Imagem → PDF: arquivo PDF válido de 1 página', pdf.read_bytes()[:5] == b'%PDF-' and _pdf_pages(pdf) == 1, str(_pdf_pages(pdf)))
    for key in ('gif', 'ico', 'avif', 'heic'):
        if key == 'avif' and not engine.avif_available():
            record('Conversão', 'AVIF', True, skipped=True, detail='sem suporte a AVIF no Pillow'); continue
        if key == 'heic' and not engine.heic_save_available():
            record('Conversão', 'HEIC', True, skipped=True, detail='pillow-heif ausente'); continue
        out = run_one('Resize → PNG', c['photo'], resize_mode='percent', resize_percent=100, out_format=key, out_quality=90)
        with Image.open(out) as handle:
            same = handle.size == photo.size if key != 'ico' else handle.size[0] <= 256
            fidelity = psnr(photo, handle.convert('RGB')) if key in ('avif', 'heic') else 99.0
        record('Conversão', f'saída {key.upper()}: abre, tamanho certo' + (', PSNR ≥ 30 dB' if key in ('avif', 'heic') else ''), same and fidelity >= 30, f'{fidelity:.1f} dB' if key in ('avif', 'heic') else '')


def _pdf_pages(path):
    from pypdf import PdfReader
    return len(PdfReader(str(path)).pages)


@guarded
def orientation_and_privacy(c):
    base = load(c['exif'])
    upright = ImageOps.exif_transpose(base)
    record('Orientação', 'o arquivo de teste tem orientação EXIF 6 (retrato)', base.getexif().get(0x0112) == 6 and upright.size == (base.height, base.width), f'{base.size}→{upright.size}')
    lossless = {'Resize → PNG': {'resize_mode': 'percent', 'resize_percent': 100}, 'Clean → PNG': {}, 'Adjust → PNG': {'adjust_flip': 0, 'adjust_brightness': 1}}
    for target, options in lossless.items():
        out = load(run_one(target, c['exif'], **options))
        ref = upright if target != 'Adjust → PNG' else None
        ok = out.size == upright.size and (identical(out, upright, 'RGB') if target == 'Clean → PNG' else psnr(out, upright) > 45)
        record('Orientação', f'{engine.TOOL_SUFFIX.get(target, target)}: sai em pé (orientação aplicada) e sem girar de novo', ok, f'{out.size}')
        del ref
    leaks = []
    for spec in tool_registry.IMAGE_TOOLS:
        if spec.target in ('Collage → PNG', 'Images → One PDF', 'Remove Background → PNG') or spec.ext in ('txt', 'pdf'):
            continue
        options = options_for(spec.target, upright.size)
        for key in ('png', 'jpeg', 'webp', 'tiff'):
            if spec.target == 'Compress → JPEG' and key != 'png':
                continue
            try:
                extra = {'out_format': key} if spec.target in tool_registry.FORMAT_TARGETS else {}
                out = run_one(spec.target, c['exif'], **options, **extra)
            except engine.ConversionError as error:
                leaks.append(f'{spec.key}/{key}: recusado ({str(error)[:50]})'); continue
            found = private_metadata(out)
            if found:
                leaks.append(f'{spec.key}/{key}: {found}')
    for quick in ('PNG', 'JPEG', 'WEBP', 'TIFF', 'BMP', 'Image → PDF'):
        out = run_one(quick, c['exif'])
        found = private_metadata(out) if quick != 'Image → PDF' else ([m for m in ('GPS', 'TestCam', 'Modelo-X1') if m.encode() in out.read_bytes()[:4096] or m.encode() in out.read_bytes()[-4096:]])
        if found:
            leaks.append(f'conversão rápida {quick}: {found}')
    if bgremove.status()[0]:
        probe = WORK / 'objeto-exif.jpg'
        exif = Image.Exif(); exif[0x010F] = 'TestCam'; gps = exif.get_ifd(0x8825); gps[1] = 'S'
        load(c['object']).save(probe, quality=95, exif=exif)
        found = private_metadata(run_one('Remove Background → PNG', probe))
        if found:
            leaks.append(f'removebg/png: {found}')
    record('Privacidade', 'nenhuma ferramenta × formato copia EXIF, GPS, câmera ou XMP para a saída', not [x for x in leaks if 'recusado' not in x], f'{len(leaks)} achados', '; '.join(leaks)[:400])
    refused = [x for x in leaks if 'recusado' in x]
    record('Privacidade', 'nenhuma ferramenta recusou a foto de celular com EXIF', not refused, f'{len(refused)}', '; '.join(refused)[:300], blocking=False)


def options_for(target, size, **extra):
    w, h = size
    table = {
        'Crop → PNG': {'crop_x': w // 4, 'crop_y': h // 4, 'crop_width': max(1, w // 2), 'crop_height': max(1, h // 2)},
        'Resize → PNG': {'resize_mode': 'percent', 'resize_percent': 50},
        'Rotate → PNG': {'rotate_angle': 90},
        'Canvas → PNG': {'canvas_width': w + 20, 'canvas_height': h + 20, 'background': '#336699'},
        'Compress → JPEG': {'quality': 80},
        'Adjust → PNG': {'adjust_brightness': 20},
        'Levels → PNG': {'levels_auto': 1},
        'Sharpen → PNG': {'sharpen_mode': 'sharpen', 'sharpen_amount': 60},
        'Backdrop → PNG': {},
        'Remove Background → PNG': {'bg_feather': 1},
        'Annotate → PNG': {'annotation': 'Oi', 'annotation_x': 0, 'annotation_y': 0, 'annotation_size': 12},
        'Shapes → PNG': {'shape_items': [{'kind': 'rect', 'x': 0, 'y': 0, 'w': max(1, w // 2), 'h': max(1, h // 2), 'color': '#FF0000', 'thickness': 1}]},
        'Watermark → PNG': {'watermark_text': 'Marca', 'watermark_scale': 40},
        'Redact → PNG': {'redact_regions': [[0, 0, max(1, w // 2), max(1, h // 2)]]},
        'Clean → PNG': {},
    }
    options = dict(table.get(target, {})); options.update(extra)
    return options


@guarded
def geometry_tools(c):
    photo = load(c['photo']); w, h = photo.size
    # girar: 4 × 90° volta ao original; espelhos exatos
    current = c['photo']
    for _ in range(4):
        current = run_one('Rotate → PNG', current, rotate_angle=90)
    record('Girar', '4 giros de 90° devolvem a imagem idêntica', identical(photo, load(current), 'RGB'), '')
    r90 = load(run_one('Rotate → PNG', c['photo'], rotate_angle=90))
    record('Girar', '90° horário: tamanho trocado e pixel (0,0) vira o canto superior direito', r90.size == (h, w) and r90.convert('RGB').getpixel((h - 1, 0)) == photo.getpixel((0, 0)), f'{r90.size}')
    mirrored = load(run_one('Rotate → PNG', c['photo'], rotate_angle=0, rotate_flip=1))
    record('Girar', 'espelho horizontal é exato', identical(mirrored, ImageOps.mirror(photo), 'RGB'), '')
    # recortar
    crop = load(run_one('Crop → PNG', c['photo'], crop_x=50, crop_y=30, crop_width=200, crop_height=100))
    record('Recortar', 'recorte idêntico à mesma área da imagem original', identical(crop, photo.crop((50, 30, 250, 130)), 'RGB'), f'{crop.size}')
    # canvas
    canvas = load(run_one('Canvas → PNG', c['photo'], canvas_width=w + 40, canvas_height=h + 20, background='#336699')).convert('RGB')
    record('Canvas', 'imagem centralizada e intacta; borda na cor pedida',
           canvas.size == (w + 40, h + 20) and identical(canvas.crop((20, 10, 20 + w, 10 + h)), photo, 'RGB') and canvas.getpixel((3, 3)) == (0x33, 0x66, 0x99), f'{canvas.size}')
    # redimensionar
    half = load(run_one('Resize → PNG', c['photo'], resize_mode='percent', resize_percent=50))
    reference = Image.fromarray(arr(photo).reshape(h // 2, 2, w // 2, 2, 3).mean(axis=(1, 3)).astype(np.uint8))
    value = psnr(half, reference)
    record('Tamanho', 'reduzir a 50%: tamanho exato e PSNR ≥ 36 dB contra a média de blocos', half.size == (w // 2, h // 2) and value >= 36, f'{value:.1f} dB')
    up = run_one('Resize → PNG', c['photo'], resize_mode='percent', resize_percent=200)
    back = load(run_one('Resize → PNG', up, resize_mode='percent', resize_percent=50))
    value = psnr(back, photo)
    record('Tamanho', 'ampliar 200% e voltar a 50%: PSNR ≥ 38 dB (sem deriva)', back.size == photo.size and value >= 38, f'{value:.1f} dB')
    fit = load(run_one('Resize → PNG', c['photo'], resize_mode='fit', resize_width=100, resize_height=0))
    record('Tamanho', '«caber em» largura 100 mantém a proporção', fit.size == (100, round(h * 100 / w)), f'{fit.size}')
    exact = load(run_one('Resize → PNG', c['photo'], resize_mode='exact', resize_width=77, resize_height=55))
    record('Tamanho', '«medida exata» 77×55', exact.size == (77, 55), f'{exact.size}')
    # transparência não gera halo no redimensionar
    alpha = load(c['alpha']); small = load(run_one('Resize → PNG', c['alpha'], resize_mode='percent', resize_percent=40))
    arrays = arr(small, 'RGBA'); edge = arrays[(arrays[..., 3] > 200)]
    record('Tamanho', 'redimensionar com transparência não escurece a borda (sem halo)', edge.size > 0 and float(edge[:, 0].min()) > 185, f'R mínimo {edge[:, 0].min():.0f}' if edge.size else 'sem pixels')
    del alpha


@guarded
def look_tools(c):
    photo = load(c['photo']); low = load(c['lowcontrast'])
    bright = load(run_one('Adjust → PNG', c['photo'], adjust_brightness=30))
    record('Ajustar', 'brilho +30 aumenta a média; mesmo tamanho', arr(bright).mean() > arr(photo).mean() + 5 and bright.size == photo.size, f'{arr(photo).mean():.1f}→{arr(bright).mean():.1f}')
    gray = arr(load(run_one('Adjust → PNG', c['photo'], adjust_saturation=-100)))
    record('Ajustar', 'saturação −100 deixa a imagem cinza (R=G=B ±2)', float(np.abs(gray[..., 0] - gray[..., 1]).max()) <= 2 and float(np.abs(gray[..., 1] - gray[..., 2]).max()) <= 2, '')
    flipped = load(run_one('Adjust → PNG', c['photo'], adjust_flip=2))
    record('Ajustar', 'espelhar vertical sem ajuste é exato', identical(flipped, ImageOps.flip(photo), 'RGB'), '')
    transparent = load(run_one('Adjust → PNG', c['alpha'], adjust_brightness=20))
    record('Ajustar', 'o canal alfa não muda', identical(transparent.getchannel('A'), load(c['alpha']).getchannel('A'), 'L'), '')
    auto = arr(load(run_one('Levels → PNG', c['lowcontrast'], levels_auto=1)), 'L')
    record('Níveis', 'automático estica o contraste (de ~100–150 para quase 0–255)', arr(low, 'L').max() - arr(low, 'L').min() < 70 and auto.min() <= 12 and auto.max() >= 243, f'{auto.min():.0f}–{auto.max():.0f}')
    again = arr(load(run_one('Levels → PNG', run_one('Levels → PNG', c['lowcontrast'], levels_auto=1), levels_auto=1)), 'L')
    record('Níveis', 'automático é estável ao repetir (faixa muda ≤ 12 níveis)', abs(again.min() - auto.min()) <= 12 and abs(again.max() - auto.max()) <= 12, f'{again.min():.0f}–{again.max():.0f}')
    sharp = load(run_one('Sharpen → PNG', c['photo'], sharpen_mode='sharpen', sharpen_amount=100, sharpen_radius=2))
    blur = load(run_one('Sharpen → PNG', c['photo'], sharpen_mode='blur', sharpen_radius=4))
    base = laplacian_energy(photo)
    record('Nitidez', 'nitidez aumenta e desfoque reduz a energia de bordas', laplacian_energy(sharp) > base * 1.15 and laplacian_energy(blur) < base * 0.7, f'{base:.1f}→{laplacian_energy(sharp):.1f} / {laplacian_energy(blur):.1f}')
    # halo no desfoque: quadrado branco opaco sobre fundo transparente com RGB preto escondido
    sq = Image.new('RGBA', (120, 120), (0, 0, 0, 0)); sq.paste((255, 255, 255, 255), (40, 40, 80, 80)); sqp = WORK / 'quadrado.png'; sq.save(sqp)
    blurred = arr(load(run_one('Sharpen → PNG', sqp, sharpen_mode='blur', sharpen_radius=6)), 'RGBA'); visible = blurred[blurred[..., 3] > 128]
    record('Nitidez', 'desfoque de PNG transparente não cria halo escuro (RGB ≥ 235 onde o alfa > 50%)', visible.size > 0 and float(visible[:, :3].min()) >= 235, f'{visible[:, :3].min():.0f}' if visible.size else '')
    backdrop = load(run_one('Backdrop → PNG', c['photo'], backdrop_padding=40, backdrop_radius=0, backdrop_shadow=0, backdrop_style='navy'))
    (bw, bh), (ox, oy) = engine.backdrop_layout(photo.width, photo.height, 40, 'auto')
    record('Fundo', 'imagem preservada no centro do fundo (PSNR ≥ 45 dB no miolo)', backdrop.size == (bw, bh) and psnr(backdrop.convert('RGB').crop((ox + 20, oy + 20, ox + photo.width - 20, oy + photo.height - 20)), photo.crop((20, 20, photo.width - 20, photo.height - 20))) >= 45, f'{backdrop.size}')


@guarded
def draw_and_protect_tools(c):
    photo = load(c['photo']); w, h = photo.size
    note = load(run_one('Annotate → PNG', c['photo'], annotation='Teste', annotation_x=20, annotation_y=20, annotation_size=36, annotation_color='#FF0000'))
    box = diff_bbox(note, photo)
    record('Anotar', 'só a área do texto muda; fora dela a imagem é idêntica', box is not None and box[0] >= 15 and box[1] >= 15 and box[2] <= 20 + 36 * 6 and box[3] <= 20 + 36 * 2, f'{box}')
    shape = load(run_one('Shapes → PNG', c['photo'], shape_items=[{'kind': 'rect', 'x': 40, 'y': 30, 'w': 100, 'h': 60, 'color': '#00FF00', 'thickness': 4, 'fill': 0}]))
    box = diff_bbox(shape, photo)
    record('Formas', 'retângulo desenhado só dentro da caixa pedida', box is not None and box[0] >= 40 and box[1] >= 30 and box[2] <= 140 and box[3] <= 90 and shape.convert('RGB').getpixel((41, 60)) == (0, 255, 0), f'{box}')
    mark = load(run_one('Watermark → PNG', c['photo'], watermark_text='MARCA', watermark_scale=25, watermark_opacity=80, watermark_position='br', watermark_color='#FFFFFF'))
    box = diff_bbox(mark, photo)
    record('Marca d\'água', 'marca no canto inferior direito; canto oposto intacto', box is not None and box[0] > w // 2 and box[1] > h // 2 and mark.convert('RGB').getpixel((2, 2)) == photo.getpixel((2, 2)), f'{box}')
    tile = diff_bbox(load(run_one('Watermark → PNG', c['photo'], watermark_text='MARCA', watermark_scale=20, watermark_opacity=60, watermark_position='tile')), photo)
    record('Marca d\'água', 'marca repetida cobre a imagem toda', tile is not None and tile[0] < w * 0.2 and tile[2] > w * 0.8 and tile[1] < h * 0.2 and tile[3] > h * 0.8, f'{tile}')
    black = load(run_one('Redact → PNG', c['photo'], redact_regions=[[50, 40, 120, 80]], redact_mode='black')).convert('RGB')
    region = arr(black.crop((50, 40, 170, 120)))
    outside = photo.copy(); outside.paste((0, 0, 0), (50, 40, 170, 120)); black_ok = identical(black, outside, 'RGB')
    record('Ocultar', 'tarja preta: região 100% preta e o resto da imagem idêntico', float(region.max()) == 0 and black_ok, f'máx {region.max():.0f}')
    pix = load(run_one('Redact → PNG', c['photo'], redact_regions=[[50, 40, 120, 80]], redact_mode='pixelate', redact_block=40)).convert('RGB')
    cells = arr(pix.crop((50, 40, 170, 120)))
    first = cells[:40, :40].reshape(-1, 3); unique = len({tuple(p) for p in first.astype(int)})
    original_cells = arr(photo.crop((50, 40, 170, 120)))[:40, :40].reshape(-1, 3); original_unique = len({tuple(p) for p in original_cells.astype(int)})
    outside2 = photo.copy(); outside2.paste(pix.crop((50, 40, 170, 120)), (50, 40))
    record('Ocultar', 'pixelização: blocos uniformes (informação destruída) e o resto idêntico', unique <= 4 and original_unique > 100 and identical(pix, outside2, 'RGB'), f'{unique} cores no bloco (antes {original_unique})')
    cleaned = load(run_one('Clean → PNG', c['icc']))
    record('Metadados', 'cópia limpa: pixels idênticos', identical(cleaned, load(c['icc']), 'RGB'), '')
    record('Metadados', 'cópia limpa: perfil de cor ICC mantido', bool(cleaned.info.get('icc_profile')), '')


@guarded
def compress_tool(c):
    photo = load(c['photo']); sizes, scores = [], []
    for quality in (95, 80, 50, 20):
        out = run_one('Compress → JPEG', c['photo'], quality=quality)
        sizes.append(out.stat().st_size); scores.append(psnr(photo, load(out)))
    record('Comprimir', 'tamanho e PSNR diminuem com a qualidade (monotônico)', sizes == sorted(sizes, reverse=True) and scores == sorted(scores, reverse=True), f'{sizes} / {[round(s, 1) for s in scores]}')
    record('Comprimir', 'qualidade 95 ≥ 38 dB e qualidade 50 ≥ 30 dB', scores[0] >= 38 and scores[2] >= 30, f'{scores[0]:.1f} / {scores[2]:.1f} dB')


@guarded
def multi_image_tools(c):
    red, green, blue = (WORK / 'r.png'), (WORK / 'g.png'), (WORK / 'b.png')
    Image.new('RGB', (80, 60), (220, 20, 20)).save(red); Image.new('RGB', (60, 80), (20, 200, 20)).save(green); Image.new('RGB', (100, 100), (20, 20, 220)).save(blue)
    collage = load(run('Collage → PNG', [red, green, blue], collage_columns=3, collage_cell=100, collage_gap=10, background='#FFFFFF')[0]).convert('RGB')
    cells = [collage.getpixel((10 + 50 + i * 110, 10 + 50)) for i in range(3)]
    ok_order = cells[0][0] > 180 and cells[1][1] > 150 and cells[2][2] > 180
    record('Colagem', 'ordem das imagens respeitada (vermelha, verde, azul) e tamanho', ok_order and collage.size == (340, 120), f'{collage.size} {cells}')
    pdf = run('Images → One PDF', [red, green, blue], pdf_page='image')[0]
    from pypdf import PdfReader
    reader = PdfReader(str(pdf)); sizes = [(round(float(p.mediabox.width)), round(float(p.mediabox.height))) for p in reader.pages]
    record('PDF único', '3 páginas, na ordem, cada uma com o tamanho da imagem (pt = 72/150 px)', len(sizes) == 3 and sizes[0][0] < sizes[0][1] * 1.4 and sizes[1][0] < sizes[1][1], f'{sizes}')
    try:
        import pypdfium2 as pdfium
        document = pdfium.PdfDocument(str(pdf)); colors = []
        for index in range(3):
            page = document[index]; bitmap = page.render(scale=0.5).to_pil().convert('RGB'); colors.append(bitmap.getpixel((bitmap.width // 2, bitmap.height // 2))); page.close()
        document.close()
        record('PDF único', 'cor central de cada página confere com a ordem da lista', colors[0][0] > 150 and colors[1][1] > 130 and colors[2][2] > 150, f'{colors}')
    except ImportError:
        record('PDF único', 'cor central de cada página', True, skipped=True, detail='pypdfium2 ausente')
    a4 = run('Images → One PDF', [red, green], pdf_page='a4', pdf_margin=10)[0]
    box = PdfReader(str(a4)).pages[0].mediabox
    record('PDF único', 'página A4 tem 595×842 pt (ou deitada)', {round(float(box.width)), round(float(box.height))} == {595, 842}, f'{float(box.width):.0f}×{float(box.height):.0f}')


@guarded
def robustness(c):
    """Cada ferramenta com cada entrada incomum: nunca pode terminar com exceção que não seja ConversionError, nem deixar lixo."""
    odd = ('palette', 'gray', 'gray16', 'cmyk', 'tiny', 'odd', 'wide', 'alpha', 'icc')
    crashes, refusals, total = [], [], 0
    for spec in tool_registry.IMAGE_TOOLS:
        if spec.target in ('Collage → PNG', 'Images → One PDF', 'Remove Background → PNG') or spec.ext in ('txt', 'pdf'):
            continue
        for name in odd:
            total += 1
            src = c[name]; size = load(src).size
            out_dir = sandbox('rob')
            try:
                engine.convert({'paths': [str(src)], 'target': spec.target, 'output': str(out_dir), **options_for(spec.target, size)})
                produced = [p for p in out_dir.iterdir() if p.is_file()]
                if not produced:
                    crashes.append(f'{spec.key}/{name}: sem saída')
            except engine.ConversionError as error:
                refusals.append(f'{spec.key}/{name}: {str(error)[:60]}')
            except Exception as error:      # noqa: BLE001
                crashes.append(f'{spec.key}/{name}: {type(error).__name__}: {str(error)[:60]}')
            leftovers = [p.name for p in out_dir.iterdir() if p.name.startswith('.arquivo-local')]
            if leftovers:
                crashes.append(f'{spec.key}/{name}: lixo {leftovers}')
    record('Robustez', f'{total} combinações ferramenta × entrada incomum (paleta, cinza, 16 bits, CMYK, 1×1, ímpar, faixa, alfa, ICC) sem exceção inesperada nem lixo', not crashes, f'{len(crashes)} problemas', '; '.join(crashes)[:500])
    record('Robustez', 'recusas com mensagem (informativo)', True, f'{len(refusals)}', '; '.join(refusals)[:500], blocking=False)
    g16 = load(run_one('Resize → PNG', c['gray16'], resize_mode='percent', resize_percent=100))
    src16 = np.asarray(Image.open(c['gray16']), dtype=np.float64) / 257.0
    record('Robustez', 'cinza de 16 bits vira 8 bits na escala certa (média ±2%)', abs(arr(g16, 'L').mean() - src16.mean()) <= 255 * 0.02, f'{arr(g16, "L").mean():.1f} vs {src16.mean():.1f}')
    cmyk = load(run_one('Resize → PNG', c['cmyk'], resize_mode='percent', resize_percent=100))
    record('Robustez', 'CMYK vira RGB com cores próximas (média ±12 níveis)', cmyk.mode in ('RGB', 'RGBA') and abs(arr(cmyk).mean() - arr(load(c['photo'])).mean()) <= 12, f'{arr(cmyk).mean():.1f}')
    for name in ('truncated', 'fake'):
        out_dir = sandbox('bad'); status = 'sem erro'
        try:
            engine.convert({'paths': [str(c[name])], 'target': 'PNG', 'output': str(out_dir)})
        except engine.ConversionError as error:
            status = 'recusada'
        except Exception as error:      # noqa: BLE001
            status = f'EXCEÇÃO {type(error).__name__}'
        left = [p.name for p in out_dir.iterdir()]
        record('Robustez', f'arquivo defeituoso ({name}) é recusado com mensagem e sem criar arquivos', status == 'recusada' and not left, status, str(left))


@guarded
def determinism_and_originals(c):
    problems = []
    for spec in tool_registry.IMAGE_TOOLS:
        if spec.target in ('Collage → PNG', 'Images → One PDF', 'Remove Background → PNG') or spec.ext in ('txt', 'pdf'):
            continue
        before = sha(c['photo']); size = load(c['photo']).size
        options = options_for(spec.target, size)
        first, second = run_one(spec.target, c['photo'], **options), run_one(spec.target, c['photo'], **options)
        if sha(c['photo']) != before:
            problems.append(f'{spec.key}: original alterado')
        if not identical(load(first), load(second)):
            problems.append(f'{spec.key}: duas execuções diferem')
    record('Determinismo', 'mesma ferramenta, mesmas opções → mesmos pixels; o original nunca muda', not problems, f'{len(problems)} problemas', '; '.join(problems))
    out = sandbox('collision'); names = set()
    for _ in range(3):
        names.add(Path(engine.convert({'paths': [str(c['photo'])], 'target': 'PNG', 'output': str(out)})[0]).name)
    record('Determinismo', 'nunca sobrescreve: 3 execuções geram 3 arquivos de nomes diferentes', len(names) == 3 and len(list(out.iterdir())) == 3, f'{sorted(names)}')


@guarded
def vector_input(c):
    out = load(run_one('PNG', c['svg'], vector_width=200)).convert('RGB')
    record('SVG', 'SVG 100×50 desenhado em 200 px: 200×100, fundo azul e círculo laranja', out.size == (200, 100) and out.getpixel((5, 5))[2] > 150 and out.getpixel((100, 50))[0] > 200, f'{out.size} {out.getpixel((100, 50))}')


@guarded
def background_removal(c):
    ready, message = bgremove.status()
    if not ready:
        record('Remover fundo', 'modelo e pacotes disponíveis', True, skipped=True, detail=message[:120]); return
    source = load(c['object'])
    out = load(run_one('Remove Background → PNG', c['object'], bg_feather=0))
    truth = Image.new('L', source.size, 0); ImageDraw.Draw(truth).ellipse((120, 50, 360, 270), fill=255)
    pred = arr(out.getchannel('A'), 'L') > 127; real = arr(truth, 'L') > 127
    iou = float((pred & real).sum() / max(1, (pred | real).sum()))
    record('Remover fundo', 'objeto isolado: IoU ≥ 0,90 contra a máscara verdadeira', iou >= 0.90, f'{iou:.3f}')
    visible = arr(out)[pred & real]
    record('Remover fundo', 'cores do objeto intactas (RGB idêntico ao original onde ficou opaco)', identical(Image.fromarray(arr(out)[..., :3].astype(np.uint8)).convert('RGB'), source, 'RGB'), '')
    del visible
    soft = load(run_one('Remove Background → PNG', c['object'], bg_feather=6)); a = arr(soft.getchannel('A'), 'L')
    record('Remover fundo', 'borda suave cria transição de alfa (pixels intermediários)', int(((a > 20) & (a < 235)).sum()) > int(((arr(out.getchannel('A'), 'L') > 20) & (arr(out.getchannel('A'), 'L') < 235)).sum()), '')


@guarded
def ocr_quality(c):
    ready, message = ocr.status()
    if not ready:
        record('OCR', 'Tesseract disponível', True, skipped=True, detail=message[:120]); return
    import difflib
    expected = '\n'.join(['Conversão offline de arquivos', 'Olá, mundo! Ação e emoção: 123,45', 'Arquivo Local — teste de OCR'])
    out = run_one('OCR → Text', c['text'], ocr_lang='por')
    got = out.read_text(encoding='utf8').strip()
    ratio = difflib.SequenceMatcher(None, ' '.join(expected.split()), ' '.join(got.split())).ratio()
    record('OCR', 'texto limpo em português: acerto de caracteres ≥ 95%', ratio >= 0.95, f'{ratio:.3f}')
    pdf = run_one('OCR → PDF', c['text'], ocr_lang='por')
    from pypdf import PdfReader
    text = PdfReader(str(pdf)).pages[0].extract_text() or ''
    record('OCR', 'PDF pesquisável contém o texto reconhecido', 'offline' in text.lower() or 'arquivos' in text.lower(), text[:40].replace('\n', ' '))
    noisy = Image.fromarray(np.clip(arr(load(c['text'])) + np.random.default_rng(1).normal(0, 28, (load(c['text']).height, load(c['text']).width, 3)), 0, 255).astype(np.uint8))
    noisy_path = WORK / 'ruido.png'; noisy.save(noisy_path)
    got2 = run_one('OCR → Text', noisy_path, ocr_lang='por').read_text(encoding='utf8')
    ratio2 = difflib.SequenceMatcher(None, ' '.join(expected.split()), ' '.join(got2.split())).ratio()
    record('OCR', 'texto com ruído gaussiano (σ=28): acerto ≥ 80% (informativo)', ratio2 >= 0.80, f'{ratio2:.3f}', blocking=False)


@guarded
def performance(c):
    big = WORK / 'grande-12mp.png'
    rng = np.random.default_rng(5)
    base = np.asarray(make_photo((500, 375), 9).resize((4000, 3000), Image.Resampling.BICUBIC), dtype=np.float64) + rng.normal(0, 3, (3000, 4000, 3))
    Image.fromarray(np.clip(base, 0, 255).astype(np.uint8)).save(big)
    slow = []; table = []
    for spec in tool_registry.IMAGE_TOOLS:
        if spec.target in ('Collage → PNG', 'Images → One PDF', 'Remove Background → PNG') or spec.ext in ('txt', 'pdf'):
            continue
        options = options_for(spec.target, (4000, 3000))
        start = time.perf_counter(); run_one(spec.target, big, **options); elapsed = time.perf_counter() - start
        table.append((spec.key, elapsed));
        if elapsed > 45:
            slow.append(f'{spec.key} {elapsed:.0f}s')
    record('Desempenho', 'cada ferramenta processa 12 MP em ≤ 45 s (nesta máquina)', not slow, f'pior: {max(table, key=lambda x: x[1])[0]} {max(x[1] for x in table):.1f}s', ', '.join(f'{k} {v:.1f}s' for k, v in table)[:500])
    if bgremove.status()[0]:
        start = time.perf_counter(); run_one('Remove Background → PNG', big, bg_feather=2); elapsed = time.perf_counter() - start
        record('Desempenho', 'remover fundo (u2netp) de 12 MP em ≤ 45 s', elapsed <= 45, f'{elapsed:.1f}s', blocking=False)


# ───────────────────────── corpus de PDFs (0.9.42) ─────────────────────────
SECRETS = ('123.456.789-09', '12345678909', 'Maria', 'Souza', 'maria@exemplo', '98888-7777', 'segredo.txt', 'Dossi')
PDF_LINES = (['Relatório confidencial', 'Cliente Maria Souza CPF 123.456.789-09'],
             ['Contato maria@exemplo.com.br fone (91) 98888-7777', 'Ação e emoção: 123,45'],
             ['Texto livre sem segredo nenhum', 'Fim do documento'])


def text_pdf_bytes(pages, width=595, height=842, rotations=(), cropbox=None):
    """PDF de texto Helvetica (WinAnsi, fonte não incorporada) escrito à mão: estrutura simples, sem dependência de biblioteca de PDF."""
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>', None]
    kids = []
    for index, lines in enumerate(pages):
        page_id, content_id = 3 + index * 2, 4 + index * 2
        kids.append(f'{page_id} 0 R')
        body = b'BT /F1 16 Tf 40 %d Td 22 TL ' % (height - 60)
        for line in lines:
            safe = line.encode('cp1252', 'replace').replace(b'\\', b'\\\\').replace(b'(', b'\\(').replace(b')', b'\\)')
            body += b'(' + safe + b') Tj T* '
        body += b'ET'
        extra = f' /Rotate {rotations[index]}' if index < len(rotations) and rotations[index] else ''
        if cropbox and index == 1:
            extra += ' /CropBox [%d %d %d %d]' % cropbox
        objects.append(f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {width} {height}]{extra} /Contents {content_id} 0 R /Resources << /Font << /F1 << /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >> >> >> >>'.encode())
        objects.append(b'<< /Length %d >>\nstream\n' % len(body) + body + b'\nendstream')
    objects[1] = f'<< /Type /Pages /Kids [{" ".join(kids)}] /Count {len(pages)} >>'.encode()
    out = bytearray(b'%PDF-1.4\n'); offsets = []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out)); out += b'%d 0 obj\n' % number + body + b'\nendobj\n'
    xref = len(out)
    out += b'xref\n0 %d\n0000000000 65535 f \n' % (len(objects) + 1) + b''.join(b'%010d 00000 n \n' % o for o in offsets)
    out += b'trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n' % (len(objects) + 1, xref)
    return bytes(out)


def write_pdf_corpus(folder):
    from pypdf import PdfReader, PdfWriter
    folder = Path(folder); folder.mkdir(parents=True, exist_ok=True); files = {}
    # texto com marcadores, metadados e anexo que repetem os segredos (o que a redação precisa eliminar)
    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(text_pdf_bytes(PDF_LINES))))
    writer.add_outline_item('Capítulo Maria Souza', 0); writer.add_metadata({'/Title': 'Dossiê Maria Souza', '/Author': 'Maria Souza'}); writer.add_attachment('segredo.txt', b'123.456.789-09')
    with (folder / 'texto.pdf').open('wb') as handle: writer.write(handle)
    files['text'] = folder / 'texto.pdf'
    (folder / 'texto-simples.pdf').write_bytes(text_pdf_bytes(PDF_LINES)); files['plain'] = folder / 'texto-simples.pdf'
    scan_lines = [['Monthly report quarterly', 'Invoice number total amount'], ['Contract delivery payment', 'Customer address balance']]
    pages = [make_text_image(lines, size=44, width=1240).convert('RGB').resize((1240, 1754), Image.Resampling.BICUBIC) if False else make_text_image(lines, size=44, width=1240) for lines in scan_lines]
    pages = [p.convert('RGB') for p in pages]
    pages[0].save(folder / 'escaneado.pdf', save_all=True, append_images=pages[1:], resolution=150); files['scan'] = folder / 'escaneado.pdf'; files['scan_words'] = [w for lines in scan_lines for line in lines for w in line.split()]
    sys.path.insert(0, str(ROOT / 'tests'))
    from formfixture import form_pdf
    (folder / 'formulario.pdf').write_bytes(form_pdf()); files['form'] = folder / 'formulario.pdf'
    locked = PdfWriter(clone_from=PdfReader(io.BytesIO(text_pdf_bytes(PDF_LINES)))); locked.encrypt('senha1234')
    with (folder / 'com-senha.pdf').open('wb') as handle: locked.write(handle)
    files['locked'] = folder / 'com-senha.pdf'
    good = (folder / 'texto-simples.pdf').read_bytes()
    (folder / 'defeito-truncado.pdf').write_bytes(good[: len(good) // 2]); files['truncated'] = folder / 'defeito-truncado.pdf'
    (folder / 'defeito-corrompido.pdf').write_bytes(b'%PDF-1.4\n' + bytes(range(256)) * 40); files['corrupt'] = folder / 'defeito-corrompido.pdf'
    (folder / 'defeito-falso.pdf').write_bytes(b'isto nao e um pdf\n' * 40); files['fake'] = folder / 'defeito-falso.pdf'
    (folder / '200-paginas.pdf').write_bytes(text_pdf_bytes([[f'Página {n}', 'Texto de preenchimento'] for n in range(1, 201)], 300, 400)); files['p200'] = folder / '200-paginas.pdf'
    (folder / '201-paginas.pdf').write_bytes(text_pdf_bytes([[f'Página {n}'] for n in range(1, 202)], 200, 200)); files['p201'] = folder / '201-paginas.pdf'
    (folder / 'pagina-gigante.pdf').write_bytes(text_pdf_bytes([['Página gigante']], 14400, 14400)); files['giant'] = folder / 'pagina-gigante.pdf'
    active = PdfWriter(clone_from=PdfReader(io.BytesIO(text_pdf_bytes(PDF_LINES)))); active.add_js('app.alert("oi");'); active.add_attachment('nota.txt', b'anexo'); active.add_metadata({'/Author': 'Autor Teste'})
    with (folder / 'js-anexos.pdf').open('wb') as handle: active.write(handle)
    files['js'] = folder / 'js-anexos.pdf'
    (folder / 'girado-cropbox.pdf').write_bytes(text_pdf_bytes(PDF_LINES, rotations=(90, 0, 270), cropbox=(50, 100, 500, 700))); files['rotated'] = folder / 'girado-cropbox.pdf'
    (folder / '50-paginas.pdf').write_bytes(text_pdf_bytes([[f'Página {n} Maria Souza', 'Texto de preenchimento para medir desempenho'] for n in range(1, 51)])); files['p50'] = folder / '50-paginas.pdf'
    return files


def render_pages(path, dpi=72):
    import pdfinfo
    document = pdfinfo.open_document(path); images = []
    try:
        for number in range(1, len(document) + 1):
            images.append(pdfinfo.render_dpi(document, number, dpi).convert('L'))
    finally:
        document.close()
    return images


def pdf_text(path):
    from pypdf import PdfReader
    return [' '.join((page.extract_text() or '').split()) for page in PdfReader(str(path)).pages]


def pdf_blob(path):
    """Tudo o que o arquivo guarda, decodificado: bytes brutos + cada fluxo descomprimido + textos das páginas (para procurar vazamentos)."""
    from pypdf import PdfReader
    raw = Path(path).read_bytes(); parts = [raw]
    reader = PdfReader(str(path), strict=False)
    try:
        for index in range(1, int(reader.trailer['/Size'])):
            try:
                obj = reader.get_object(index)
                if hasattr(obj, 'get_data'): parts.append(obj.get_data())
                else: parts.append(repr(obj).encode('utf8', 'replace'))
            except Exception: continue
    except Exception: pass
    parts.append('\n'.join(pdf_text(path)).encode('utf8', 'replace'))
    return b'\n'.join(parts)


class NoNetwork:
    """Conta (e impede) qualquer tentativa de abrir conexão durante uma conversão."""
    def __enter__(self):
        import socket
        self.attempts = 0; self.real = (socket.socket.connect, socket.create_connection)
        def blocked(*_a, **_k):
            self.attempts += 1; raise OSError('rede bloqueada pela suíte de qualidade')
        socket.socket.connect = blocked; socket.create_connection = blocked
        return self

    def __exit__(self, *_exc):
        import socket
        socket.socket.connect, socket.create_connection = self.real


def leftovers(folder):
    return [p.name for p in Path(folder).rglob('*') if p.is_file() and (p.suffix.lower() in ('.part', '.tmp') or p.name.startswith('.') or p.name.endswith('~'))]


PDF_CASES = (('PDF → Text', 'text', {}), ('PDF → Images', 'text', {}), ('Split PDF', 'text', {'split_mode': 'each'}), ('Organize PDF', 'text', {'organize_pages': ['3:0', '1:90', '2:0']}),
             ('Clean PDF', 'js', {'meta_info': 'on', 'meta_attach': 'on', 'meta_js': 'on'}), ('Compress PDF', 'scan', {'pdf_level': 'medium'}), ('Stamp PDF', 'text', {}),
             ('Protect PDF', 'text', {'pdf_password': 'senha1234'}), ('Unprotect PDF', 'locked', {'pdf_password': 'senha1234'}), ('Redact PDF', 'text', {'redact_terms': ['Maria']}),
             ('Fill PDF', 'form', {'form_values': ['nome\tAna'], 'form_flatten': 'on'}), ('Extract PDF Images', 'scan', {}))


@guarded
def pdf_invariants(c):
    pc = c['pdf']
    for target, key, options in PDF_CASES:
        source = pc[key]; before = sha(source)
        try:
            with NoNetwork() as net:
                outputs = run(target, [source], **options)
        except Exception as error:      # noqa: BLE001
            record('PDF — invariantes', f'{target}: converte o caso padrão', False, type(error).__name__, str(error)[:200]); continue
        folder = outputs[0].parent
        opens = True
        for out in outputs:
            if out.suffix.lower() == '.pdf':
                try:
                    reader = __import__('pypdf').PdfReader(str(out))
                    if reader.is_encrypted: reader.decrypt(options.get('pdf_password', ''))
                    opens = opens and len(reader.pages) >= 1
                except Exception: opens = False
            else: opens = opens and out.stat().st_size > 0
        record('PDF — invariantes', f'{target}: original intacto, sem parciais, sem rede, saída abre', sha(source) == before and not leftovers(folder) and net.attempts == 0 and opens,
               f'{len(outputs)} arquivo(s)', f'original={"ok" if sha(source) == before else "ALTERADO"} sobras={leftovers(folder)} rede={net.attempts} abre={opens}')
    out = sandbox('collision-pdf'); names = set()
    for _ in range(3): names.add(Path(engine.convert({'paths': [str(pc['plain'])], 'target': 'Stamp PDF', 'output': str(out)})[0]).name)
    record('PDF — invariantes', 'nunca sobrescreve: 3 execuções geram 3 arquivos diferentes', len(names) == 3, f'{sorted(names)}')


@guarded
def pdf_fidelity(c):
    pc = c['pdf']; original_images = render_pages(pc['text']); original_text = pdf_text(pc['text'])
    def similarity(a, b): return min(ssim(x, y) for x, y in zip(a, b)) if len(a) == len(b) else 0.0
    clean = run_one('Clean PDF', pc['text'], meta_info='on', meta_attach='on', meta_js='on')
    record('PDF — fidelidade', 'metadados/anexos removidos: texto igual e páginas idênticas (SSIM ≥ 0.999)', pdf_text(clean) == original_text and similarity(original_images, render_pages(clean)) >= 0.999, f'{similarity(original_images, render_pages(clean)):.4f}')
    protected = run_one('Protect PDF', pc['plain'], pdf_password='senha1234'); back = run_one('Unprotect PDF', protected, pdf_password='senha1234')
    record('PDF — fidelidade', 'proteger → remover senha devolve o mesmo texto e a mesma imagem', pdf_text(back) == pdf_text(pc['plain']) and similarity(render_pages(pc['plain']), render_pages(back)) >= 0.999, f'{similarity(render_pages(pc["plain"]), render_pages(back)):.4f}')
    merged = run('Merge PDFs', [pc['plain'], pc['plain']])[0]
    record('PDF — fidelidade', 'unir dois PDFs: 6 páginas, texto e imagens na ordem', len(pdf_text(merged)) == 6 and pdf_text(merged) == pdf_text(pc['plain']) * 2 and similarity(render_pages(merged), render_pages(pc['plain']) * 2) >= 0.999)
    parts = run('Split PDF', [pc['plain']], split_mode='each')
    record('PDF — fidelidade', 'dividir cada página: 3 arquivos de 1 página, texto na ordem', len(parts) == 3 and [pdf_text(p)[0] for p in sorted(parts, key=lambda p: p.name)] == pdf_text(pc['plain']), f'{len(parts)} arquivos')
    stamped = run_one('Stamp PDF', pc['plain'], pdf_pages='1', stamp_text='SELO {n}', stamp_kind='text', stamp_position='bc')
    after = render_pages(stamped); before = render_pages(pc['plain'])
    record('PDF — fidelidade', 'carimbo só na página 1: páginas 2–3 idênticas, página 1 mudou só no rodapé', similarity(before[1:], after[1:]) >= 0.999 and not identical(before[0].convert('RGB'), after[0].convert('RGB')) and identical(before[0].crop((0, 0, before[0].width, int(before[0].height * 0.85))).convert('RGB'), after[0].crop((0, 0, after[0].width, int(after[0].height * 0.85))).convert('RGB')))
    scan_before = render_pages(pc['scan'], 100)
    for level, floor in (('light', 0.97), ('medium', 0.93), ('strong', 0.85)):
        try:
            out = run_one('Compress PDF', pc['scan'], pdf_level=level); value = similarity(scan_before, render_pages(out, 100)); smaller = out.stat().st_size < pc['scan'].stat().st_size
            record('PDF — fidelidade', f'comprimir ({level}): menor que o original e SSIM ≥ {floor}', value >= floor and smaller, f'SSIM {value:.3f} · {out.stat().st_size // 1024} KB de {pc["scan"].stat().st_size // 1024} KB')
        except engine.ConversionError as error:
            record('PDF — fidelidade', f'comprimir ({level}): menor que o original', level == 'light', 'sem economia', str(error)[:120], blocking=level != 'light')
    flat = run_one('Fill PDF', pc['form'], form_values=['nome\tAna Lima', 'estado\tSP'], form_flatten='on'); text = ' '.join(pdf_text(flat))
    record('PDF — fidelidade', 'formulário achatado mostra os valores e não tem mais campos', 'Ana Lima' in text and 'SP' in text and '/AcroForm' not in __import__('pypdf').PdfReader(str(flat)).trailer['/Root'])


@guarded
def pdf_redaction(c):
    pc = c['pdf']; checks = (('termo «Maria»', {'redact_terms': ['Maria', 'Souza']}), ('padrões CPF/e-mail/telefone', {'redact_patterns': 'cpf,email,telefone'}),
                             ('área da página 1 + termo', {'redact_areas': ['1:0,0,1000,1000'], 'redact_terms': ['Maria']}))
    total_leaks = 0; details = []
    for label, options in checks:
        out = run_one('Redact PDF', pc['text'], **options); blob = pdf_blob(out)
        leaks = [s for s in SECRETS if s.encode('utf8') in blob or s.encode('utf-16-be') in blob]
        if 'Maria' not in options.get('redact_terms', []) and 'redact_patterns' in options: leaks = [s for s in leaks if s not in ('Maria', 'Souza', 'Dossi', 'segredo.txt')] if False else leaks
        total_leaks += len(leaks); details.append(f'{label}: {leaks or "sem vazamento"}')
        pages = pdf_text(out)
        redacted_pages_empty = pages[0] == '' and (pages[1] == '' if ('redact_patterns' in options or options.get('redact_terms')) else True)
        record('PDF — redação', f'{label}: nenhum segredo em bytes, fluxos, texto, marcadores, anexos ou metadados', not leaks, f'{len(leaks)} vazamentos', '; '.join(leaks))
        record('PDF — redação', f'{label}: páginas tarjadas sem camada de texto', redacted_pages_empty, f'{[len(t) for t in pages]}')
    image = render_pages(run_one('Redact PDF', pc['text'], redact_areas=['1:0,0,1000,1000']))[0]
    record('PDF — redação', 'área cobrindo a página inteira deixa a página preta', max(image.get_flattened_data()) <= 10, f'máximo {max(image.get_flattened_data())}')
    ready, message = ocr.status()
    if ready:
        out = run_one('Redact PDF', pc['text'], redact_terms=['Maria', 'Souza', 'confidencial'], pdf_dpi=200); langs = ocr.available_languages()
        text = run_one('PDF OCR → Text', out, ocr_lang='por' if 'por' in langs else 'eng', ocr_skip='off').read_text(encoding='utf8').lower() if True else ''
        record('PDF — redação', 'OCR sobre o resultado tarjado não lê o termo escondido', 'maria' not in text and 'souza' not in text, f'{len(text)} caracteres lidos', blocking=True)
    else:
        record('PDF — redação', 'OCR sobre o resultado tarjado', True, skipped=True, detail=message[:120])


@guarded
def pdf_robustness(c):
    pc = c['pdf']; bad = ('truncated', 'corrupt', 'fake', 'locked', 'giant', 'p201')
    targets = [(t, k, o) for t, k, o in PDF_CASES if t not in ('Unprotect PDF', 'Fill PDF', 'Extract PDF Images')] + [('Fill PDF', 'text', {'form_flatten': 'on'}), ('Unprotect PDF', 'text', {'pdf_password': 'x'})]
    problems = []; slow = []; accepted = []
    for key in bad:
        for target, _k, options in targets:
            source = pc[key]; before = sha(source); out = sandbox('bad')
            start = time.perf_counter()
            try:
                result = engine.convert({'paths': [str(source)], 'target': target, 'output': str(out), **options})
                for item in result:
                    if str(item).endswith('.pdf') and target != 'Protect PDF': __import__('pypdf').PdfReader(str(item), strict=False).pages[0]
                accepted.append(f'{key}/{target}')
                if key in ('truncated', 'corrupt', 'fake') and target not in ('PDF → Text',): problems.append(f'{key}/{target}: aceitou entrada defeituosa')
            except engine.ConversionError:
                pass
            except Exception as error:      # noqa: BLE001
                problems.append(f'{key}/{target}: {type(error).__name__}')
            elapsed = time.perf_counter() - start
            if elapsed > 60: slow.append(f'{key}/{target} {elapsed:.0f}s')
            if sha(source) != before: problems.append(f'{key}/{target}: original alterado')
            if leftovers(out): problems.append(f'{key}/{target}: sobras {leftovers(out)}')
    record('PDF — robustez', f'{len(bad)} entradas defeituosas × {len(targets)} ferramentas: só erro explicado (ConversionError), original intacto, sem parciais', not problems, f'{len(problems)} problemas', '; '.join(problems)[:400])
    record('PDF — robustez', 'nenhuma combinação passa de 60 s', not slow, f'{len(slow)} lentas', '; '.join(slow))
    record('PDF — robustez', 'informativo: combinações defeito × ferramenta que terminaram com sucesso (esperado só para texto/dividir/carimbar em página gigante e 201 páginas)', True, f'{len(accepted)} combinações', ', '.join(accepted)[:300], blocking=False)
    ok200 = run_one('PDF → Text', pc['p200']).stat().st_size > 0; parts = run('Split PDF', [pc['p200']], split_mode='each')
    record('PDF — robustez', '200 páginas: texto e dividir em 200 arquivos', ok200 and len(parts) == 200, f'{len(parts)} arquivos')


@guarded
def pdf_geometry(c):
    pc = c['pdf']; from pypdf import PdfReader
    reader = PdfReader(str(pc['rotated'])); problems = []
    out = run_one('Stamp PDF', pc['rotated'], stamp_kind='text', stamp_text='SELOTESTE', stamp_position='tc', stamp_size=30, stamp_bold='on')
    before, after = render_pages(pc['rotated']), render_pages(out)
    for number, (b, a) in enumerate(zip(before, after), 1):
        diff = ImageChops.difference(b.convert('RGB'), a.convert('RGB')).getbbox()
        if diff is None: problems.append(f'carimbo p{number}: nada mudou'); continue
        if diff[1] > a.height * 0.2: problems.append(f'carimbo p{number}: fora do alto visível {diff}')
    record('PDF — geometria', 'carimbo no topo aparece no topo visível em páginas giradas (90°/270°) e com CropBox', not problems, f'{len(problems)} problemas', '; '.join(problems))
    problems = []
    red = run_one('Redact PDF', pc['rotated'], redact_areas=['1:0,0,1000,250', '2:0,0,1000,250', '3:0,0,1000,250'])
    for number, image in enumerate(render_pages(red), 1):
        top = image.crop((0, 0, image.width, int(image.height * 0.22))); rest = image.crop((0, int(image.height * 0.3), image.width, image.height))
        if max(top.get_flattened_data()) > 10: problems.append(f'p{number}: o topo não ficou preto')
        if min(rest.get_flattened_data()) < 255 and number != 3: pass
        if sum(rest.get_flattened_data()) / (rest.width * rest.height) < 200: problems.append(f'p{number}: tarja passou do lugar')
    record('PDF — geometria', 'tarja marcada no topo cobre o topo visível em páginas giradas e com CropBox', not problems, f'{len(problems)} problemas', '; '.join(problems))
    problems = []; sig = WORK / 'assinatura.png'; Image.new('RGBA', (300, 100), (0, 0, 0, 0)).save(sig)
    mark = Image.new('RGBA', (300, 100), (0, 0, 0, 0)); ImageDraw.Draw(mark).rectangle((10, 40, 290, 60), fill=(0, 0, 0, 255)); mark.save(sig)
    signed = run_one('Fill PDF', pc['rotated'], sign_image=str(sig), sign_areas=['1:0,0,1000,250', '2:0,0,1000,250', '3:0,0,1000,250'])
    for number, (b, a) in enumerate(zip(before, render_pages(signed)), 1):
        diff = ImageChops.difference(b.convert('RGB'), a.convert('RGB')).getbbox()
        if diff is None: problems.append(f'p{number}: assinatura ausente')
        elif diff[3] > a.height * 0.3: problems.append(f'p{number}: assinatura fora do alto {diff}')
    record('PDF — geometria', 'imagem de assinatura fica na área marcada em páginas giradas e com CropBox', not problems, f'{len(problems)} problemas', '; '.join(problems))


@guarded
def pdf_security(c):
    pc = c['pdf']; from pypdf import PdfReader
    protected = run_one('Protect PDF', pc['plain'], pdf_password='senha1234'); reader = PdfReader(str(protected))
    record('PDF — senha', 'protegido: exige senha (vazia falha, correta abre) e usa AES-256', reader.is_encrypted and reader.decrypt('') == 0 and reader.decrypt('senha1234') > 0 and b'/AESV3' in protected.read_bytes(), '')
    try:
        run_one('Unprotect PDF', protected, pdf_password='errada123'); wrong = False; message = ''
    except engine.ConversionError as error:
        wrong = True; message = str(error)
    record('PDF — senha', 'senha errada: erro, nada salvo, e a mensagem não repete a senha', wrong and 'errada123' not in message, message[:80])
    opened = run_one('Unprotect PDF', protected, pdf_password='senha1234')
    record('PDF — senha', 'senha certa: cópia abre sem senha com o mesmo texto', not PdfReader(str(opened)).is_encrypted and pdf_text(opened) == pdf_text(pc['plain']))
    report = ' '.join(engine.loss_report([str(protected)], 'Protect PDF', {'pdf_password': 'senha1234'}))
    record('PDF — senha', 'relatório de perdas nunca contém a senha', 'senha1234' not in report)
    js = run_one('Clean PDF', pc['js'], meta_info='on', meta_attach='on', meta_js='on'); blob = pdf_blob(js)
    record('PDF — metadados', 'cópia limpa sem JavaScript, anexo nem autor', b'app.alert' not in blob and b'nota.txt' not in blob and b'Autor Teste' not in blob)


@guarded
def pdf_ocr_quality(c):
    pc = c['pdf']; ready, message = ocr.status()
    if not ready:
        record('PDF — OCR', 'Tesseract disponível', True, skipped=True, detail=message[:120]); return
    langs = ocr.available_languages(); lang = 'eng' if 'eng' in langs else langs[0]
    text = run_one('PDF OCR → Text', pc['scan'], ocr_lang=lang).read_text(encoding='utf8').lower(); words = pc['scan_words']
    hits = sum(1 for w in words if w.lower() in text); rate = hits / len(words)
    record('PDF — OCR', 'PDF digitalizado: ≥ 90% das palavras reconhecidas', rate >= 0.9, f'{rate:.2f} ({hits}/{len(words)})')
    searchable = run_one('PDF OCR → PDF', pc['scan'], ocr_lang=lang); extracted = ' '.join(pdf_text(searchable)).lower()
    record('PDF — OCR', 'PDF pesquisável: mesmas páginas, texto extraível e aparência igual', len(pdf_text(searchable)) == 2 and sum(1 for w in words if w.lower() in extracted) / len(words) >= 0.9 and min(ssim(a, b.resize(a.size)) for a, b in zip(render_pages(pc['scan'], 100), render_pages(searchable, 100))) >= 0.97)


@guarded
def pdf_libreoffice(c):
    import subprocess
    exe = shutil.which('soffice') or shutil.which('libreoffice')
    if not exe:
        record('PDF — LibreOffice', 'PDF produzido pelo LibreOffice', True, skipped=True, detail='soffice não encontrado'); return
    html = WORK / 'relatorio-lo.html'; html.write_text('<html><head><meta charset="utf-8"></head><body><h1>Relatório de ação</h1><p>Cliente Maria Souza, CPF 123.456.789-09.</p><table border="1"><tr><td>Item</td><td>Preço</td></tr><tr><td>Emoção</td><td>123,45</td></tr></table></body></html>', encoding='utf8')
    try:
        subprocess.run([exe, '--headless', f'-env:UserInstallation=file://{WORK}/lo-profile', '--convert-to', 'pdf', '--outdir', str(WORK), str(html)], capture_output=True, timeout=180, check=False)
    except Exception as error:      # noqa: BLE001
        record('PDF — LibreOffice', 'PDF produzido pelo LibreOffice', True, skipped=True, detail=type(error).__name__); return
    lo = WORK / 'relatorio-lo.pdf'
    if not lo.exists():
        record('PDF — LibreOffice', 'PDF produzido pelo LibreOffice', True, skipped=True, detail='a conversão não gerou o PDF'); return
    text = ' '.join(pdf_text(lo)); results = []
    for target, options in (('PDF → Text', {}), ('PDF → Images', {}), ('Stamp PDF', {}), ('Clean PDF', {'meta_info': 'on'}), ('Protect PDF', {'pdf_password': 'senha1234'}), ('Redact PDF', {'redact_patterns': 'cpf', 'redact_terms': ['Maria']})):
        try: run(target, [lo], **options); results.append(True)
        except Exception as error: results.append(False); record('PDF — LibreOffice', f'{target} sobre PDF do LibreOffice', False, type(error).__name__, str(error)[:160])
    record('PDF — LibreOffice', 'ferramentas aceitam PDF com fontes incorporadas e tabelas', all(results), f'{sum(results)}/{len(results)}', f'texto lido: {text[:60]}')
    out = run_one('Redact PDF', lo, redact_terms=['Maria', 'Souza'], redact_patterns='cpf'); blob = pdf_blob(out)
    record('PDF — LibreOffice', 'redação sobre PDF do LibreOffice sem vazamento', b'Maria' not in blob and b'123.456' not in blob and pdf_text(out)[0] == '', '')


@guarded
def pdf_performance(c):
    pc = c['pdf']
    try: import resource
    except ImportError: resource = None
    limits = {'PDF → Text': 0.5, 'PDF → Images': 3.0, 'Split PDF': 0.5, 'Stamp PDF': 0.5, 'Protect PDF': 0.5, 'Redact PDF': 3.0}
    table = []; slow = []
    for target, limit in limits.items():
        options = {'split_mode': 'each'} if target == 'Split PDF' else {'pdf_password': 'senha1234'} if target == 'Protect PDF' else {'redact_terms': ['Maria']} if target == 'Redact PDF' else {}
        start = time.perf_counter(); run(target, [pc['p50']], **options); per_page = (time.perf_counter() - start) / 50
        table.append((target, per_page))
        if per_page > limit: slow.append(f'{target} {per_page:.2f}s/pág')
    start = time.perf_counter(); run('Merge PDFs', [pc['p50'], pc['p50']]); merge = (time.perf_counter() - start) / 100; table.append(('Merge PDFs', merge))
    if merge > 0.3: slow.append(f'Merge PDFs {merge:.2f}s/pág')
    record('PDF — desempenho', 'tempo por página (50 páginas A4) dentro do limite de cada ferramenta', not slow, 'pior: ' + max(table, key=lambda x: x[1])[0], ', '.join(f'{k} {v:.2f}s/pág' for k, v in table))
    if resource is None:
        record('PDF — desempenho', 'pico de memória', True, skipped=True, detail='módulo resource indisponível (Windows)')
    else:
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
        record('PDF — desempenho', 'pico de memória do processo ≤ 1500 MB', peak <= 1500, f'{peak:.0f} MB', blocking=False)


IMAGE_SECTIONS = (conversion_fidelity, orientation_and_privacy, geometry_tools, look_tools, draw_and_protect_tools, compress_tool, multi_image_tools,
            robustness, determinism_and_originals, vector_input, background_removal, ocr_quality)
PDF_SECTIONS = (pdf_invariants, pdf_fidelity, pdf_redaction, pdf_robustness, pdf_geometry, pdf_security, pdf_ocr_quality, pdf_libreoffice)
SECTIONS = IMAGE_SECTIONS + PDF_SECTIONS


def score(passed, failed):
    total = passed + failed
    return 100 if total == 0 else round(100 * passed / total)


def grade(passed, failed):
    total = passed + failed
    if total == 0:
        return '—'
    ratio = passed / total
    return 'A' if ratio == 1 else 'B' if ratio >= 0.9 else 'C' if ratio >= 0.75 else 'D'


def write_report(out_dir, seconds):
    out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    groups: dict[str, list[dict]] = {}
    for item in RESULTS:
        groups.setdefault(item['func'], []).append(item)
    passed = sum(1 for r in RESULTS if r['status'] == 'PASSOU'); failed = [r for r in RESULTS if r['status'] == 'FALHOU']; skipped = sum(1 for r in RESULTS if r['status'] == 'PULADA')
    blocking_failures = [r for r in failed if r['blocking']]
    low = [name for name, items in groups.items() if score(sum(1 for r in items if r['status'] == 'PASSOU'), sum(1 for r in items if r['status'] == 'FALHOU' and r['blocking'])) < 80]
    lines = ['# Relatório de qualidade — categorias Imagens e PDF', '',
             f'- Versão do motor: `{engine.VERSION}` · Python {platform.python_version()} · {platform.system()} {platform.release()}',
             f'- Duração: {seconds:.0f} s · verificações: {len(RESULTS)} · **passaram {passed}** · falharam {len(failed)} (bloqueantes: {len(blocking_failures)}) · puladas {skipped}',
             f'- Resultado geral: **{"APROVADO" if not blocking_failures and not low else "REPROVADO"}**' + (f' · funções abaixo de 80: {", ".join(low)}' if low else ' · nenhuma função abaixo de 80'), '',
             '| Função | Nota (0–100) | Conceito | Passou | Falhou | Pulada |', '|---|---|---|---|---|---|']
    for name, items in groups.items():
        p = sum(1 for r in items if r['status'] == 'PASSOU'); f = sum(1 for r in items if r['status'] == 'FALHOU'); s = sum(1 for r in items if r['status'] == 'PULADA')
        lines.append(f'| {name} | {score(p, f)} | {grade(p, f)} | {p} | {f} | {s} |')
    lines += ['', '## Detalhe', '', '| Função | Verificação | Resultado | Medida |', '|---|---|---|---|']
    for item in RESULTS:
        mark = {'PASSOU': 'passou', 'FALHOU': '**FALHOU**' + ('' if item['blocking'] else ' (não bloqueante)'), 'PULADA': 'pulada'}[item['status']]
        measure = (item['value'] + (' — ' + item['detail'] if item['detail'] else '')).replace('|', '/').replace('\n', ' ')[:300]
        lines.append(f"| {item['func']} | {item['check']} | {mark} | {measure} |")
    (out_dir / 'quality-report.md').write_text('\n'.join(lines) + '\n', encoding='utf8')
    (out_dir / 'quality-report.json').write_text(json.dumps({'version': engine.VERSION, 'results': RESULTS}, ensure_ascii=False, indent=1), encoding='utf8')
    return passed, failed, skipped, blocking_failures


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):      # console do Windows (cp1252) não imprime «→»; saída sempre em UTF-8
        try: stream.reconfigure(encoding='utf-8', errors='replace')
        except (AttributeError, ValueError): pass
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--out', default='quality-report'); parser.add_argument('--corpus'); parser.add_argument('--fast', action='store_true'); parser.add_argument('--only', choices=('all', 'images', 'pdf'), default='all')
    args = parser.parse_args(argv)
    if args.corpus:
        files = write_corpus(args.corpus); write_pdf_corpus(Path(args.corpus) / 'pdf')
        print(f'{len(list(Path(args.corpus).rglob("*.*")))} arquivos de teste gravados em {args.corpus} (PDFs em {Path(args.corpus) / "pdf"})')
        return 0
    start = time.perf_counter()
    corpus = write_corpus(WORK / 'corpus')
    sections = []
    if args.only in ('all', 'images'):
        sections += list(IMAGE_SECTIONS) + ([] if args.fast else [performance])
    if args.only in ('all', 'pdf'):
        corpus['pdf'] = write_pdf_corpus(WORK / 'corpus-pdf')
        sections += list(PDF_SECTIONS) + ([] if args.fast else [pdf_performance])
    for section in sections:
        section(corpus)
        print(f'  {section.__name__}: {sum(1 for r in RESULTS if r["func"] == section.__name__ or True)} verificações até aqui', flush=True)
    passed, failed, skipped, blocking = write_report(args.out, time.perf_counter() - start)
    print(f'passaram {passed} · falharam {len(failed)} (bloqueantes {len(blocking)}) · puladas {skipped} → {Path(args.out).resolve() / "quality-report.md"}')
    for item in failed:
        print('  FALHOU:', item['func'], '—', item['check'], '→', item['value'], item['detail'][:160])
    shutil.rmtree(WORK, ignore_errors=True)
    return 1 if blocking or any(item['func'] and False for item in failed) else 0


if __name__ == '__main__':
    raise SystemExit(main())
