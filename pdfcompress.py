"""Compressão de PDF sem Ghostscript: reduz imagens pela resolução efetiva e reaproveita o resto do arquivo.

Núcleo puro (sem Qt, sem importar o motor). Trabalha sobre um `PdfWriter` do pypdf já clonado do original.
Só mexe em imagens simples (RGB ou cinza de 8 bits, sem máscara): JPEG é recodificado e fotos em Flate viram JPEG nos níveis médio e forte;
imagens com transparência, máscaras, paleta, CMYK ou dentro de formulários internos ficam como estão.
A resolução efetiva vem do tamanho em que cada imagem é desenhada na página (matriz `cm` do fluxo de conteúdo).
"""
from __future__ import annotations

import io
import math
import zlib

# nível → (dpi alvo, qualidade JPEG, fotos em Flate viram JPEG)
LEVELS = {'light': (300, 88, False), 'medium': (150, 72, True), 'strong': (96, 55, True)}
DEFAULT_LEVEL = 'medium'
MAX_PIXELS = 40_000_000
MAX_OPERATIONS = 200_000
PHOTO_COLORS = 2000          # cores distintas numa miniatura 96×96 a partir das quais a imagem é tratada como foto


def _multiply(m, n):
    """m aplicado depois de n (como `cm`: nova matriz = m × atual)."""
    a, b, c, d, e, f = m
    a2, b2, c2, d2, e2, f2 = n
    return (a * a2 + b * c2, a * b2 + b * d2, c * a2 + d * c2, c * b2 + d * d2, e * a2 + f * c2 + e2, e * b2 + f * d2 + f2)


def drawn_sizes(page, writer) -> dict:
    """{nome do XObject: (largura, altura) em pontos} do MAIOR tamanho em que cada imagem é desenhada diretamente na página."""
    from pypdf.generic import ContentStream
    sizes = {}
    try:
        contents = page.get_contents()
        if contents is None:
            return sizes
        operations = ContentStream(contents, writer).operations
    except Exception:
        return sizes
    matrix, stack = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0), []
    for operands, operator in operations[:MAX_OPERATIONS]:
        try:
            if operator == b'q':
                if len(stack) < 64:
                    stack.append(matrix)
            elif operator == b'Q':
                if stack:
                    matrix = stack.pop()
            elif operator == b'cm' and len(operands) == 6:
                matrix = _multiply(tuple(float(x) for x in operands), matrix)
            elif operator == b'Do' and operands:
                width, height = math.hypot(matrix[0], matrix[1]), math.hypot(matrix[2], matrix[3])
                name = str(operands[0])
                old = sizes.get(name, (0.0, 0.0))
                sizes[name] = (max(old[0], width), max(old[1], height))
        except Exception:
            continue
    return sizes


def _components(xobject):
    """1 ou 3 para espaços de cor simples; None para o resto (paleta, CMYK, Lab, separação…)."""
    space = xobject.get('/ColorSpace')
    try:
        space = space.get_object() if hasattr(space, 'get_object') else space
        if str(space) in ('/DeviceRGB', '/CalRGB'):
            return 3
        if str(space) in ('/DeviceGray', '/CalGray'):
            return 1
        if isinstance(space, list) and space and str(space[0]) == '/ICCBased':
            count = int(space[1].get_object().get('/N'))
            return count if count in (1, 3) else None
    except Exception:
        return None
    return None


def _filter_name(xobject):
    value = xobject.get('/Filter')
    if isinstance(value, list):
        if len(value) != 1:
            return None
        value = value[0]
    return str(value) if value is not None else ''


def _is_photo(image) -> bool:
    from PIL import Image
    sample = image.convert('RGB').resize((96, 96), Image.NEAREST)
    return sample.getcolors(maxcolors=PHOTO_COLORS) is None


def recompress_image(xobject, scale: float, quality: float, photos_to_jpeg: bool) -> int:
    """Recodifica uma imagem no próprio objeto e devolve quantos bytes economizou (0 = ficou como estava)."""
    from PIL import Image
    from pypdf.generic import NameObject, NumberObject
    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    if xobject.get('/ImageMask') or '/SMask' in xobject or '/Mask' in xobject or '/Decode' in xobject:
        return 0
    comps = _components(xobject)
    filt = _filter_name(xobject)
    try:
        width, height = int(xobject['/Width']), int(xobject['/Height'])
        bpc = int(xobject.get('/BitsPerComponent', 8))
    except Exception:
        return 0
    if comps is None or bpc != 8 or width < 1 or height < 1 or width * height > MAX_PIXELS or filt not in ('/DCTDecode', '/FlateDecode', ''):
        return 0
    try:
        data = xobject.get_data()
        old = len(xobject._data)
        if filt == '/DCTDecode':
            image = Image.open(io.BytesIO(data)); image.load()
            if image.mode != ('RGB' if comps == 3 else 'L') or image.size != (width, height):
                return 0
        else:
            if len(data) != width * height * comps:
                return 0
            image = Image.frombytes('RGB' if comps == 3 else 'L', (width, height), data)
        as_jpeg = filt == '/DCTDecode' or (photos_to_jpeg and _is_photo(image))
        if scale < 0.98:
            new_size = (max(1, round(width * scale)), max(1, round(height * scale)))
            image = image.resize(new_size, Image.LANCZOS if as_jpeg else Image.BOX)       # arte chapada: BOX não cria cores novas fora das bordas (LANCZOS incha o Flate)
        elif filt != '/DCTDecode' and not as_jpeg:
            return 0
        if as_jpeg:
            buffer = io.BytesIO(); image.save(buffer, 'JPEG', quality=int(quality), optimize=True); new, new_filter = buffer.getvalue(), '/DCTDecode'
        else:
            new, new_filter = zlib.compress(image.tobytes(), 9), '/FlateDecode'
        if len(new) >= old:
            return 0
        xobject._data = new
        xobject[NameObject('/Filter')] = NameObject(new_filter)
        xobject.pop('/DecodeParms', None)
        xobject[NameObject('/Width')] = NumberObject(image.size[0])
        xobject[NameObject('/Height')] = NumberObject(image.size[1])
        xobject[NameObject('/BitsPerComponent')] = NumberObject(8)
        return old - len(new)
    except Exception:
        return 0


def compress(writer, level: str) -> dict:
    """Aplica o nível ao `writer`. Devolve {'images': n, 'changed': n, 'saved': bytes}."""
    dpi_target, quality, photos = LEVELS[level]
    uses = {}                    # idnum → (objeto, menor dpi efetivo entre os usos ou None)
    stats = {'images': 0, 'changed': 0, 'saved': 0}
    for page in writer.pages:
        try:
            page.compress_content_streams(level=9)
        except Exception:
            pass
        try:
            resources = page.get('/Resources')
            xobjects = resources.get_object().get('/XObject') if resources is not None else None
            xobjects = xobjects.get_object() if xobjects is not None else {}
        except Exception:
            continue
        sizes = drawn_sizes(page, writer)
        for name, reference in xobjects.items():
            try:
                xobject = reference.get_object()
                if str(xobject.get('/Subtype')) != '/Image':
                    continue
                key = getattr(reference, 'idnum', None) or id(xobject)
                dpi = None
                if str(name) in sizes:
                    drawn_w, drawn_h = sizes[str(name)]
                    if drawn_w > 0.5 and drawn_h > 0.5:
                        dpi = min(int(xobject['/Width']) / (drawn_w / 72), int(xobject['/Height']) / (drawn_h / 72))
                previous = uses.get(key)
                if previous is None:
                    uses[key] = (xobject, dpi)
                elif dpi is not None and (previous[1] is None or dpi < previous[1]):
                    uses[key] = (xobject, dpi)
            except Exception:
                continue
    for xobject, dpi in uses.values():
        stats['images'] += 1
        scale = min(1.0, dpi_target / dpi) if dpi else 1.0
        saved = recompress_image(xobject, scale, quality, photos)
        if saved > 0:
            stats['changed'] += 1
            stats['saved'] += saved
    try:
        writer.compress_identical_objects(remove_identicals=True, remove_orphans=True)
    except Exception:
        pass
    return stats
