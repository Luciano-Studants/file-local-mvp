"""Tarja segura em PDF: onde procurar (áreas marcadas, termos e padrões) e como converter posições do texto em pixels da página como ela aparece.

Núcleo puro (sem Qt, sem importar o motor). O motor rasteriza as páginas afetadas, pinta as tarjas nos pixels e conferem o resultado;
aqui ficam só as contas: validar áreas, achar ocorrências no texto, agrupar caracteres por linha e mapear coordenadas do PDF para pixels (CropBox e /Rotate).
"""
from __future__ import annotations

import re

MAX_AREAS = 300
MAX_TERMS = 20
MIN_TERM = 2
MAX_TERM = 60
PAD = 1.5                         # pontos de folga em volta do texto achado
PRESETS = {
    'cpf': ('CPF', re.compile(r'(?<!\d)(?:\d{3}\.\d{3}\.\d{3}-\d{2}|\d{11})(?!\d)')),
    'cnpj': ('CNPJ', re.compile(r'(?<!\d)(?:\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}|\d{14})(?!\d)')),
    'email': ('E-mail', re.compile(r'[\w.+-]+@[\w-]+(?:\.[\w-]+)+')),
    'telefone': ('Telefone', re.compile(r'(?<!\d)(?:\+?55\s?)?(?:\(?\d{2}\)?\s?)?9?\d{4}[-\s]?\d{4}(?!\d)')),
}


class RedactError(ValueError):
    pass


def parse_area(item, page_count: int):
    """«página:x0,y0,x1,y1» (milésimos da página como aparece, origem no canto superior esquerdo) → (página, (x0, y0, x1, y1))."""
    match = re.fullmatch(r'(\d{1,3}):(\d{1,4}),(\d{1,4}),(\d{1,4}),(\d{1,4})', item) if isinstance(item, str) else None
    if not match:
        raise RedactError('Área de tarja inválida.')
    page, x0, y0, x1, y1 = (int(value) for value in match.groups())
    if not 1 <= page <= page_count or not (0 <= x0 < x1 <= 1000 and 0 <= y0 < y1 <= 1000):
        raise RedactError('Uma área de tarja está fora da página.')
    return page, (x0, y0, x1, y1)


def check_terms(terms) -> list:
    if terms is None:
        return []
    if not isinstance(terms, list) or len(terms) > MAX_TERMS:
        raise RedactError(f'Use no máximo {MAX_TERMS} termos.')
    cleaned = []
    for term in terms:
        if not isinstance(term, str) or not MIN_TERM <= len(term.strip()) <= MAX_TERM or any(ord(char) < 32 for char in term):
            raise RedactError(f'Cada termo deve ter de {MIN_TERM} a {MAX_TERM} caracteres.')
        if term.strip() not in cleaned:
            cleaned.append(term.strip())
    return cleaned


def check_presets(value) -> list:
    if not value:
        return []
    names = [name.strip() for name in str(value).split(',') if name.strip()]
    if any(name not in PRESETS for name in names):
        raise RedactError('Padrão de dados desconhecido.')
    return list(dict.fromkeys(names))


def patterns(terms, presets):
    """Lista de expressões: termos literais (sem diferenciar maiúsculas) e os padrões escolhidos."""
    found = [re.compile(re.escape(term), re.I) for term in terms]
    found.extend(PRESETS[name][1] for name in presets)
    return found


def find_spans(text: str, compiled) -> list:
    """Intervalos (início, fim) das ocorrências, já unidos quando se tocam."""
    spans = sorted((m.start(), m.end()) for regex in compiled for m in regex.finditer(text) if m.end() > m.start())
    merged = []
    for start, end in spans:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def char_rects(textpage, start: int, end: int) -> list:
    """Retângulos (l, b, r, t), no espaço do PDF, que cobrem os caracteres [start, end), um por linha."""
    boxes = []
    for index in range(start, end):
        try:
            left, bottom, right, top = textpage.get_charbox(index)
        except Exception:
            continue
        if right - left > 0.01 and top - bottom > 0.01:
            boxes.append((left, bottom, right, top))
    rects = []
    for left, bottom, right, top in boxes:
        if rects:
            l0, b0, r0, t0 = rects[-1]
            height = t0 - b0
            middle, middle0 = (bottom + top) / 2, (b0 + t0) / 2
            if abs(middle - middle0) <= 0.6 * max(height, top - bottom) and left <= r0 + 2 * max(height, 1):
                rects[-1] = (min(l0, left), min(b0, bottom), max(r0, right), max(t0, top))
                continue
        rects.append((left, bottom, right, top))
    return [(l - PAD, b - PAD, r + PAD, t + PAD) for l, b, r, t in rects]


def to_pixels(rect, cropbox, rotation: int, scale: float):
    """Retângulo do espaço do PDF (l, b, r, t) → (x0, y0, x1, y1) em pixels da página como aparece (origem no canto superior esquerdo)."""
    cx0, cy0, cx1, cy1 = cropbox
    w, h = cx1 - cx0, cy1 - cy0
    l, b, r, t = rect[0] - cx0, rect[1] - cy0, rect[2] - cx0, rect[3] - cy0
    if rotation == 90:
        box = (b, l, t, r)
    elif rotation == 180:
        box = (w - r, b, w - l, t)
    elif rotation == 270:
        box = (h - t, w - r, h - b, w - l)
    else:
        box = (l, h - t, r, h - b)
    return tuple(value * scale for value in box)


def area_to_pixels(area, width: int, height: int):
    x0, y0, x1, y1 = area
    return (x0 * width / 1000, y0 * height / 1000, x1 * width / 1000, y1 * height / 1000)


def paint(image, boxes) -> None:
    """Pinta as caixas (pixels) de preto sólido sobre a imagem, sem transparência."""
    from PIL import ImageDraw
    draw = ImageDraw.Draw(image)
    for x0, y0, x1, y1 in boxes:
        draw.rectangle((int(x0) - 1, int(y0) - 1, int(x1) + 1, int(y1) + 1), fill=(0, 0, 0))
