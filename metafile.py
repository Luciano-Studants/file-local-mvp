"""Leitura de metarquivos do Windows (EMF e WMF), desenhados em pixels pelo GDI do próprio Windows, por meio do Pillow.

Núcleo puro (sem Qt, sem importar o motor): erros `MetafileError`; o motor os converte em `ConversionError`.

**Só funciona no Windows.** O Pillow para Windows traz o desenhista (`Image.core.drawwmf`, que chama o GDI); em Linux e macOS ele só lê o
cabeçalho e não há como desenhar — nesses sistemas o arquivo é recusado com uma mensagem clara, sem simulação. Limites conhecidos do caminho
pelo Pillow: o GDI desenha **sobre fundo branco opaco** (não há transparência: o resultado sai com alfa 255), sem suavização das bordas das
formas vetoriais, e o texto usa as fontes instaladas no computador. EMF+ (GDI+) é desenhado pelos registros de reserva do EMF, quando existem.
Só são aceitos WMF «placeable» (com o cabeçalho de 22 bytes que traz a caixa e a escala) e EMF; WMF antigo sem esse cabeçalho não tem tamanho e é recusado.

O tamanho padrão é o do cabeçalho: EMF em pixels do dispositivo de referência do arquivo; WMF placeable a 72 pontos por polegada. A largura pedida pelo
usuário (a mesma «Largura do vetor» do SVG) muda o dpi usado ao desenhar — o desenho é refeito no tamanho novo, não ampliado — e valem os mesmos
limites do SVG (`vector.target_size`: 8192 px por lado ou 40 megapixels por padrão; 16384 px no máximo).

Segurança: o GDI interpreta um arquivo não confiável; isso roda no worker (processo separado, com a pasta de trabalho privada). No Windows o worker
ainda não tem objeto de job com limites de memória/CPU (pendência registrada). Nada é buscado na rede.
"""
from __future__ import annotations

import struct
from pathlib import Path

import vector

SUFFIXES = frozenset({'.emf', '.wmf'})
LABEL = 'GDI do Windows'
MAX_BYTES = 100 * 1024 * 1024
MAX_UNITS = 1_000_000              # coordenadas do cabeçalho: acima disso o arquivo é tratado como inválido
WMF_MAGIC = b'\xd7\xcd\xc6\x9a'
EMF_MARK = b'\x01\x00\x00\x00'
UNAVAILABLE = ('EMF e WMF só podem ser desenhados no Windows (o desenho é feito pelo GDI); neste sistema o arquivo não é aberto. '
               'Converta-o no Windows ou exporte-o como SVG ou PNG; nada foi simulado.')


class MetafileError(ValueError):
    pass


def current_handler():
    """O desenhista de metarquivos registrado no Pillow (None fora do Windows). O Pillow 12 o guarda no módulo `WmfImagePlugin`; o 13, na classe `WmfStubImageFile`."""
    from PIL import WmfImagePlugin
    return getattr(WmfImagePlugin.WmfStubImageFile, '_handler', None) or getattr(WmfImagePlugin, '_handler', None)


def available():
    """True se há um desenhista de metarquivos neste computador (o do Pillow no Windows, ou outro registrado)."""
    return current_handler() is not None


def read_header(path):
    """Confere o cabeçalho do arquivo e devolve {'kind': 'emf'|'wmf', 'declared': (largura, altura)} em pixels. Não precisa do GDI."""
    path = Path(path)
    size = path.stat().st_size
    if size == 0 or size > MAX_BYTES:
        raise MetafileError('O arquivo EMF/WMF não pode estar vazio nem passar de 100 MiB.')
    with path.open('rb') as handle:
        head = handle.read(44)
    if head.startswith(WMF_MAGIC + b'\x00\x00'):
        if size < 40 or len(head) < 26 or head[22:26] != b'\x01\x00\t\x00':
            raise MetafileError('Este WMF está fora do padrão (cabeçalho inválido).')
        inch = struct.unpack_from('<H', head, 14)[0]
        if inch == 0:
            raise MetafileError('Este WMF está inválido (escala por polegada igual a zero).')
        x0, y0, x1, y1 = struct.unpack_from('<4h', head, 6)
        width, height = (x1 - x0) * 72 / inch, (y1 - y0) * 72 / inch
        kind = 'wmf'
    elif head.startswith(EMF_MARK) and head[40:44] == b' EMF' and len(head) >= 44:
        if size < 88:
            raise MetafileError('Este EMF está truncado (menor que o registro de cabeçalho).')
        x0, y0, x1, y1 = struct.unpack_from('<4i', head, 8)
        fx0, fy0, fx1, fy1 = struct.unpack_from('<4i', head, 24)
        if fx1 - fx0 <= 0 or fy1 - fy0 <= 0:
            raise MetafileError('Este EMF está inválido (a moldura do cabeçalho não tem tamanho).')
        width, height = x1 - x0, y1 - y0
        kind = 'emf'
    elif head.startswith((b'\x01\x00\x09\x00', b'\x02\x00\x09\x00')):
        raise MetafileError('Este WMF é do tipo antigo, sem o cabeçalho «placeable» que informa o tamanho; o Arquivo Local não sabe em que tamanho desenhá-lo. Abra-o em um editor e salve como EMF, SVG ou PNG.')
    else:
        raise MetafileError('Este arquivo não parece um EMF nem um WMF.')
    if not (0 < width <= MAX_UNITS and 0 < height <= MAX_UNITS):
        raise MetafileError('O tamanho informado no cabeçalho deste arquivo é inválido ou grande demais.')
    return {'kind': kind, 'declared': (float(width), float(height))}


def describe_metafile(path, width=None):
    """Resumo para o relatório de perdas e a interface, sem desenhar a imagem. Exige o desenhista do Windows."""
    header = read_header(path)
    if not available():
        raise MetafileError(UNAVAILABLE)
    try:
        w, h, reduced = vector.target_size(header['declared'], width)
    except vector.VectorError as error:
        raise MetafileError(str(error)) from error
    return {'kind': 'metafile', 'format': header['kind'], 'declared': header['declared'], 'size': (w, h), 'reduced': reduced, 'dropped': {}, 'engine': (LABEL, True)}


def rasterize_metafile(path, width=None):
    """EMF/WMF → imagem RGBA do Pillow, **opaca** (fundo branco do GDI). `width` em px (opcional) escolhe o tamanho; sem ele vale o do cabeçalho."""
    from PIL import Image
    info = describe_metafile(path, width)
    w, h = info['size']
    try:
        with Path(path).open('rb') as handle:        # o Pillow não fecha o arquivo do metarquivo depois de desenhar: o `with` garante (no Windows, um arquivo aberto fica travado)
            image = Image.open(handle)
            base = image.info.get('dpi', 72)
            dx, dy = base if isinstance(base, tuple) else (base, base)
            scale = w / info['declared'][0]
            image.load(dpi=(dx * scale, dy * scale))
            rendered = image.convert('RGBA')
            image.close()
    except (SyntaxError, ValueError, OSError, ZeroDivisionError, struct.error, MemoryError, OverflowError, Image.DecompressionBombError) as error:
        raise MetafileError('O Windows não conseguiu desenhar este arquivo EMF/WMF (arquivo danificado, fora do padrão ou grande demais).') from error
    if min(rendered.size) < 1:
        rendered.close()
        raise MetafileError('O desenho deste arquivo EMF/WMF ficou com tamanho zero (a caixa do cabeçalho é pequena demais para o tamanho pedido).')
    if rendered.size != (w, h):
        resized = rendered.resize((w, h), Image.Resampling.LANCZOS); rendered.close(); rendered = resized
    return rendered
