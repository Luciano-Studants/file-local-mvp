"""Carimbo em páginas de PDF: numeração, texto de cabeçalho/rodapé e marca d'água, como texto vetorial (Helvetica, WinAnsi).

Núcleo puro (sem Qt, sem importar o motor). A fonte é uma das 14 fontes padrão do PDF: nada é embutido, o texto continua selecionável e o arquivo quase não cresce.
Os caracteres precisam existir no alfabeto latino do Windows (cp1252: acentos do português incluídos). As larguras vêm das métricas Adobe que o pypdf já traz.
As posições valem para a página como ela aparece (com /Rotate e CropBox); a marca diagonal só fica no centro.
"""
from __future__ import annotations

import math
import re

POSITIONS = ('tl', 'tc', 'tr', 'ml', 'c', 'mr', 'bl', 'bc', 'br')
MM = 72 / 25.4
CAP = 0.72                      # altura das maiúsculas da Helvetica em relação ao corpo
DEFAULT_WIDTH = 556


class StampError(ValueError):
    pass


def _widths(bold: bool):
    try:
        from pypdf._codecs.core_font_metrics import CORE_FONT_METRICS
        return CORE_FONT_METRICS['Helvetica-Bold' if bold else 'Helvetica'].character_widths
    except Exception:
        return None


def text_width(text: str, size: float, bold: bool = False) -> float:
    """Largura em pontos de `text` em Helvetica (ou Helvetica-Bold) no corpo `size`."""
    widths = _widths(bold)
    total = sum((widths.get(char, widths.get('default', DEFAULT_WIDTH)) if widths else DEFAULT_WIDTH) for char in text)
    return total * size / 1000


def encode(text: str) -> bytes:
    try:
        return text.encode('cp1252')
    except UnicodeEncodeError as error:
        raise StampError('O texto tem caracteres que a fonte do carimbo não tem; use letras latinas (com acentos), números e pontuação comum.') from error


def _literal(data: bytes) -> bytes:
    return b'(' + re.sub(rb'([()\\])', rb'\\\1', data).replace(b'\r', b'\\r').replace(b'\n', b'\\n') + b')'


def expand(text: str, number: int, total: int) -> str:
    """Troca {n} e {total}; qualquer outra chave entre chaves fica como foi escrita."""
    return text.replace('{n}', str(number)).replace('{total}', str(total))


def visible_geometry(page):
    """(x0, y0, largura_usuario, altura_usuario, rotação) da área visível; a largura/altura que a pessoa vê trocam quando a rotação é 90 ou 270."""
    box = page.cropbox if '/CropBox' in page else page.mediabox
    x0, y0 = float(box.left), float(box.bottom)
    width, height = abs(float(box.width)), abs(float(box.height))
    try:
        rotation = int(page.get('/Rotate', 0) or 0) % 360
    except Exception:
        rotation = 0
    if rotation not in (0, 90, 180, 270):
        rotation = 0
    return x0, y0, width, height, rotation


def _to_user(point, geometry):
    """Ponto (X, Y) da página como aparece → coordenadas do espaço do usuário."""
    X, Y = point
    x0, y0, w, h, rotation = geometry
    if rotation == 90:
        return x0 + (w - Y), y0 + X
    if rotation == 180:
        return x0 + w - X, y0 + h - Y
    if rotation == 270:
        return x0 + Y, y0 + h - X
    return x0 + X, y0 + Y


def visible_size(geometry):
    _x0, _y0, w, h, rotation = geometry
    return (h, w) if rotation in (90, 270) else (w, h)


def stamp_content(geometry, text: str, *, position: str, size: float, bold: bool, color: str, opacity: int, margin_mm: float, angle: int = 0, fit_percent: float = 0) -> bytes:
    """Fluxo de conteúdo (bytes) que desenha o texto. `fit_percent` > 0 ajusta o corpo para o texto ocupar essa porcentagem da largura (ou da diagonal, se `angle`) visível."""
    if position not in POSITIONS:
        raise StampError('Posição inválida.')
    if angle and position != 'c':
        raise StampError('O texto na diagonal só pode ficar no centro da página.')
    data = encode(text)
    view_w, view_h = visible_size(geometry)
    if fit_percent:
        reference = math.hypot(view_w, view_h) if angle else view_w
        unit = text_width(text, 1, bold)
        size = max(4.0, min(400.0, reference * fit_percent / 100 / unit)) if unit > 0 else size
    text_w = text_width(text, size, bold)
    margin = margin_mm * MM
    column, row = position[1] if position[0] in 'tmb' and len(position) == 2 else 'c', position[0]
    if position == 'c':
        row, column = 'm', 'c'
    # linha de base e início horizontal, com o texto sem giro
    if column == 'l':
        start_x = margin
    elif column == 'r':
        start_x = view_w - margin - text_w
    else:
        start_x = (view_w - text_w) / 2
    if row == 't':
        base_y = view_h - margin - size * CAP
    elif row == 'b':
        base_y = margin
    else:
        base_y = (view_h - size * CAP) / 2
    visual_angle = math.radians(angle)
    if angle:
        # gira em torno do centro do texto, que fica no centro da página
        cx, cy = view_w / 2, view_h / 2
        dx, dy = -text_w / 2, -size * CAP / 2
        start_x = cx + dx * math.cos(visual_angle) - dy * math.sin(visual_angle)
        base_y = cy + dx * math.sin(visual_angle) + dy * math.cos(visual_angle)
    rotation = geometry[4]
    user_x, user_y = _to_user((start_x, base_y), geometry)
    total_angle = visual_angle + math.radians(rotation)
    cos, sin = math.cos(total_angle), math.sin(total_angle)
    red, green, blue = (int(color[i:i + 2], 16) / 255 for i in (1, 3, 5))
    parts = [b'q']
    if opacity < 100:
        parts.append(b'/GS1 gs')
    parts.append(f'{red:.4f} {green:.4f} {blue:.4f} rg'.encode())
    parts.append(f'BT /{"F2" if bold else "F1"} {size:.2f} Tf {cos:.5f} {sin:.5f} {-sin:.5f} {cos:.5f} {user_x:.2f} {user_y:.2f} Tm '.encode() + _literal(data) + b' Tj ET')
    parts.append(b'Q')
    return b'\n'.join(parts)


def overlay_page(page, content: bytes, bold: bool, opacity: int):
    """Página em branco do mesmo tamanho (MediaBox), só com o conteúdo do carimbo e os recursos de fonte e transparência."""
    from pypdf import PageObject
    from pypdf.generic import DecodedStreamObject, DictionaryObject, FloatObject, NameObject
    box = page.mediabox
    overlay = PageObject.create_blank_page(None, abs(float(box.width)), abs(float(box.height)))
    overlay.mediabox = box.__class__(list(box))
    font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'),
                             NameObject('/BaseFont'): NameObject('/Helvetica-Bold' if bold else '/Helvetica'), NameObject('/Encoding'): NameObject('/WinAnsiEncoding')})
    resources = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F2' if bold else '/F1'): font})})
    if opacity < 100:
        alpha = FloatObject(opacity / 100)
        resources[NameObject('/ExtGState')] = DictionaryObject({NameObject('/GS1'): DictionaryObject({NameObject('/Type'): NameObject('/ExtGState'), NameObject('/ca'): alpha, NameObject('/CA'): alpha})})
    overlay[NameObject('/Resources')] = resources
    stream = DecodedStreamObject()
    stream.set_data(content)
    overlay[NameObject('/Contents')] = stream
    return overlay
