"""Formulários PDF (AcroForm) e assinatura visual — núcleo sem Qt (0.9.41).

Lista os campos (texto, caixa de seleção, opção única, lista), preenche valores, «acha» o formulário (desenha as aparências na página e remove os campos)
e posiciona uma imagem de assinatura numa área da página. A imagem NÃO é assinatura digital certificada: não há certificado nem prova de autoria.
"""
from __future__ import annotations

import re

MAX_FIELDS = 200
MAX_VALUE = 1000
MAX_NAME = 200
MAX_SIGN_AREAS = 10
MAX_SIGN_BYTES = 20 * 1024 * 1024
FILLABLE = ('text', 'check', 'radio', 'choice')
HIDDEN_FLAGS = 0b100010  # Invisible (1) e Hidden (2) → bits 0 e 1; NoView (6) → bit 5


class FormError(ValueError):
    pass


def _resolve(obj):
    return obj.get_object() if hasattr(obj, 'get_object') else obj


def _inherited(obj, key):
    seen = 0
    while obj is not None and seen < 40:
        obj = _resolve(obj)
        if key in obj:
            return _resolve(obj[key])
        obj = obj.get('/Parent')
        seen += 1
    return None


def qualified_name(widget) -> str:
    parts, obj, seen = [], widget, 0
    while obj is not None and seen < 40:
        obj = _resolve(obj)
        title = obj.get('/T')
        if title is not None:
            parts.append(str(_resolve(title)))
        obj = obj.get('/Parent')
        seen += 1
    return '.'.join(reversed(parts))


def field_root(widget):
    """Dicionário que guarda o valor do campo (o ancestral mais alto com /T ou /FT; o próprio widget se for um campo só)."""
    obj, best, seen = _resolve(widget), _resolve(widget), 0
    while seen < 40:
        parent = obj.get('/Parent')
        if parent is None:
            break
        obj = _resolve(parent); seen += 1
        if '/T' in obj or '/FT' in obj:
            best = obj
    return best


def kind_of(widget) -> str:
    ft = _inherited(widget, '/FT')
    flags = int(_inherited(widget, '/Ff') or 0)
    if ft == '/Tx':
        return 'text'
    if ft == '/Ch':
        return 'choice'
    if ft == '/Sig':
        return 'signature'
    if ft == '/Btn':
        if flags & (1 << 16):
            return 'button'
        return 'radio' if flags & (1 << 15) else 'check'
    return 'other'


def on_state(widget) -> str:
    """Nome do estado «ligado» (sem a barra) de uma caixa/opção, lido das aparências."""
    ap = _resolve(widget).get('/AP')
    if ap is not None:
        normal = _resolve(_resolve(ap).get('/N')) if '/N' in _resolve(ap) else None
        if normal is not None and hasattr(normal, 'keys'):
            for key in normal.keys():
                if key != '/Off':
                    return str(key)[1:]
    return 'Yes'


def _widgets(pdf):
    for number, page in enumerate(pdf.pages, 1):
        for annot in page.get('/Annots') or []:
            obj = _resolve(annot)
            if obj.get('/Subtype') == '/Widget':
                yield number, annot, obj


def list_fields(pdf) -> list:
    """Campos do formulário: {name, kind, value, options, page, multiline, readonly, maxlen}. No máximo MAX_FIELDS; nomes repetidos viram um só campo."""
    fields = {}
    for number, _ref, widget in _widgets(pdf):
        name = qualified_name(widget)
        if not name or len(name) > MAX_NAME:
            continue
        kind = kind_of(widget)
        entry = fields.get(name)
        if entry is None:
            if len(fields) >= MAX_FIELDS:
                continue
            flags = int(_inherited(widget, '/Ff') or 0)
            value = _inherited(widget, '/V')
            entry = {'name': name, 'kind': kind, 'page': number, 'options': [], 'multiline': kind == 'text' and bool(flags & (1 << 12)),
                     'readonly': bool(flags & 1), 'maxlen': int(_inherited(widget, '/MaxLen') or 0), 'value': ''}
            if kind == 'text' or kind == 'choice':
                entry['value'] = '' if value is None else (str(value) if not isinstance(value, list) else '; '.join(str(v) for v in value))
            elif kind == 'check':
                entry['value'] = 'off' if value in (None, '/Off') or str(value) == '/Off' else 'on'
            elif kind == 'radio':
                entry['value'] = '' if value in (None, '/Off') or str(value) == '/Off' else str(value).lstrip('/')
            if kind == 'choice':
                for option in _inherited(widget, '/Opt') or []:
                    option = _resolve(option)
                    entry['options'].append(str(_resolve(option[0])) if isinstance(option, list) else str(option))
                entry['multiselect'] = bool(flags & (1 << 21))
            fields[name] = entry
        if kind == 'radio':
            state = on_state(widget)
            if state not in entry['options']:
                entry['options'].append(state)
    return list(fields.values())


def has_signature_fields(pdf) -> bool:
    return any(kind_of(widget) == 'signature' for _n, _r, widget in _widgets(pdf))


def parse_values(raw, fields) -> dict:
    """Lista «nome<TAB>valor» → {nome: valor} validado contra os campos do PDF."""
    if raw is None:
        return {}
    if not isinstance(raw, list) or len(raw) > MAX_FIELDS:
        raise FormError(f'Use no máximo {MAX_FIELDS} campos.')
    by_name = {f['name']: f for f in fields}
    values = {}
    for item in raw:
        if not isinstance(item, str) or '\t' not in item:
            raise FormError('Valor de campo inválido.')
        name, value = item.split('\t', 1)
        field = by_name.get(name)
        if field is None:
            raise FormError(f'O campo «{name[:60]}» não existe neste PDF.')
        if field['kind'] not in FILLABLE or field['readonly']:
            raise FormError(f'O campo «{name[:60]}» não pode ser preenchido (somente leitura, botão ou assinatura digital).')
        if len(value) > MAX_VALUE or any(ord(c) < 32 and not (c in '\n\r' and field['multiline']) for c in value):
            raise FormError(f'O valor do campo «{name[:60]}» é longo demais ou tem caracteres inválidos.')
        if field['kind'] == 'check' and value not in ('on', 'off'):
            raise FormError(f'A caixa «{name[:60]}» aceita só marcada ou desmarcada.')
        if field['kind'] == 'radio' and value and value not in field['options']:
            raise FormError(f'A opção escolhida para «{name[:60]}» não existe.')
        if field['kind'] == 'choice' and value and field['options'] and value not in field['options']:
            raise FormError(f'O valor de «{name[:60]}» não está entre as opções da lista.')
        if field['kind'] == 'text' and field['maxlen'] and len(value) > field['maxlen']:
            raise FormError(f'O campo «{name[:60]}» aceita no máximo {field["maxlen"]} caracteres.')
        values[name] = value
    return values


def parse_sign_area(item, page_count: int):
    match = re.fullmatch(r'(\d{1,3}):(\d{1,4}),(\d{1,4}),(\d{1,4}),(\d{1,4})', item) if isinstance(item, str) else None
    if not match:
        raise FormError('Área de assinatura inválida.')
    page, x0, y0, x1, y1 = (int(v) for v in match.groups())
    if not 1 <= page <= page_count or not (0 <= x0 < x1 <= 1000 and 0 <= y0 < y1 <= 1000):
        raise FormError('Uma área de assinatura está fora da página.')
    return page, (x0, y0, x1, y1)


def fill(writer, values: dict, fields: list) -> None:
    """Grava `values` nos campos do `writer` (um PdfWriter já clonado). Texto e listas ganham aparência pelo pypdf; caixas e opções trocam o estado."""
    from pypdf.generic import NameObject, TextStringObject
    by_name = {f['name']: f for f in fields}
    pages = {}
    for number, _ref, widget in _widgets(writer):
        pages.setdefault(qualified_name(widget), []).append((number, widget))
    for name, value in values.items():
        field, found = by_name[name], pages.get(name, [])
        if not found:
            raise FormError(f'O campo «{name[:60]}» não foi encontrado nas páginas.')
        root = field_root(found[0][1])
        if field['kind'] == 'check':
            for _n, widget in found:
                state = '/' + on_state(widget) if value == 'on' else '/Off'
                widget[NameObject('/AS')] = NameObject(state)
                if widget is root or '/T' in widget:
                    widget[NameObject('/V')] = NameObject(state)
            root[NameObject('/V')] = NameObject('/' + on_state(found[0][1]) if value == 'on' else '/Off')
        elif field['kind'] == 'radio':
            for _n, widget in found:
                widget[NameObject('/AS')] = NameObject('/' + on_state(widget) if value and on_state(widget) == value else '/Off')
            root[NameObject('/V')] = NameObject('/' + value if value else '/Off')
        elif field['kind'] == 'choice':
            root[NameObject('/V')] = TextStringObject(value)
            for _n, widget in found:
                _choice_appearance(writer, widget, value)
        else:
            number = found[0][0]
            page = writer.pages[number - 1]
            writer.update_page_form_field_values(page, {name: value}, auto_regenerate=False)
            if _inherited(found[0][1], '/V') is None or str(_inherited(found[0][1], '/V')) != value:
                root[NameObject('/V')] = TextStringObject(value)


def _choice_appearance(writer, widget, value: str) -> None:
    """Aparência de uma lista suspensa: só o valor escolhido (o pypdf desenharia todas as opções)."""
    from pypdf.generic import ArrayObject, DecodedStreamObject, DictionaryObject, FloatObject, NameObject
    rect = [float(_resolve(v)) for v in widget['/Rect']]
    width, height = abs(rect[2] - rect[0]), abs(rect[3] - rect[1])
    da = str(_inherited(widget, '/DA') or '/Helv 12 Tf 0 g')
    match = re.search(r'/(\S+)\s+([\d.]+)\s+Tf', da)
    font_name = match.group(1) if match else 'Helv'
    size = float(match.group(2)) if match and float(match.group(2)) > 0 else 11.0
    size = min(size, max(6.0, height - 4))
    text = value.encode('latin-1', 'replace').decode('latin-1').replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')
    content = f'/Tx BMC q 1 1 {width - 2:.2f} {height - 2:.2f} re W n BT /{font_name} {size:.1f} Tf 0 g 2 {max(2.0, (height - size) / 2 + size * 0.2):.2f} Td ({text}) Tj ET Q EMC' if value else ''
    form = _resolve(writer._root_object.get('/AcroForm')) if '/AcroForm' in writer._root_object else None
    fonts = _resolve(_resolve(form.get('/DR')).get('/Font')) if form is not None and '/DR' in form and '/Font' in _resolve(form['/DR']) else None
    font = fonts.get('/' + font_name) if fonts is not None else None
    if font is None:
        font = writer._add_object(DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')}))
    stream = DecodedStreamObject(); stream.set_data(content.encode('latin-1', 'replace'))
    stream[NameObject('/Type')] = NameObject('/XObject'); stream[NameObject('/Subtype')] = NameObject('/Form')
    stream[NameObject('/BBox')] = ArrayObject([FloatObject(0), FloatObject(0), FloatObject(width), FloatObject(height)])
    stream[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/' + font_name): font})})
    widget[NameObject('/AP')] = DictionaryObject({NameObject('/N'): writer._add_object(stream)})


def _matrix_apply(matrix, x, y):
    a, b, c, d, e, f = matrix
    return a * x + c * y + e, b * x + d * y + f


def flatten(writer) -> int:
    """Desenha a aparência de cada campo visível no conteúdo da página e remove campos e AcroForm. Devolve quantos campos foram fixados."""
    from pypdf import PageObject
    from pypdf.generic import ArrayObject, DecodedStreamObject, DictionaryObject, NameObject
    fixed = 0
    for page in writer.pages:
        annots = page.get('/Annots')
        if not annots:
            continue
        keep, xobjects, content = ArrayObject(), DictionaryObject(), []
        for ref in annots:
            annot = _resolve(ref)
            if annot.get('/Subtype') != '/Widget':
                keep.append(ref); continue
            flags = int(annot.get('/F', 0) or 0)
            ap = _resolve(annot.get('/AP')) if annot.get('/AP') is not None else None
            normal = _resolve(ap.get('/N')) if ap is not None and '/N' in ap else None
            if normal is not None and not hasattr(normal, 'get_data'):
                state = annot.get('/AS')
                normal = _resolve(normal.get(state)) if state is not None and state in normal else None
            if normal is None or flags & 0b10 or flags & 0b100000 or '/Rect' not in annot or str(annot.get('/AS', '')) == '/Off':
                continue
            rect = [float(_resolve(v)) for v in annot['/Rect']]
            left, right, bottom, top = min(rect[0], rect[2]), max(rect[0], rect[2]), min(rect[1], rect[3]), max(rect[1], rect[3])
            bbox = [float(_resolve(v)) for v in normal.get('/BBox', [0, 0, right - left, top - bottom])]
            matrix = [float(_resolve(v)) for v in normal.get('/Matrix', [1, 0, 0, 1, 0, 0])]
            corners = [_matrix_apply(matrix, x, y) for x in (bbox[0], bbox[2]) for y in (bbox[1], bbox[3])]
            min_x, max_x = min(c[0] for c in corners), max(c[0] for c in corners)
            min_y, max_y = min(c[1] for c in corners), max(c[1] for c in corners)
            if max_x - min_x <= 0 or max_y - min_y <= 0:
                continue
            sx, sy = (right - left) / (max_x - min_x), (top - bottom) / (max_y - min_y)
            name = f'/FlatF{fixed}'
            xobjects[NameObject(name)] = writer._add_object(normal) if getattr(normal, 'indirect_reference', None) is None else normal.indirect_reference
            content.append(f'q {sx:.6f} 0 0 {sy:.6f} {left - min_x * sx:.4f} {bottom - min_y * sy:.4f} cm {name} Do Q')
            fixed += 1
        if '/Annots' in page:
            if len(keep):
                page[NameObject('/Annots')] = keep
            else:
                del page['/Annots']
        if content:
            overlay = PageObject.create_blank_page(None, abs(float(page.mediabox.width)), abs(float(page.mediabox.height)))
            overlay.mediabox = page.mediabox.__class__(list(page.mediabox))
            overlay[NameObject('/Resources')] = DictionaryObject({NameObject('/XObject'): xobjects})
            stream = DecodedStreamObject(); stream.set_data('\n'.join(content).encode('latin-1'))
            overlay[NameObject('/Contents')] = stream
            page.merge_page(overlay)
    root = writer._root_object
    if '/AcroForm' in root:
        del root['/AcroForm']
    return fixed


def signature_xobject(writer, image):
    """Imagem (RGB/RGBA/L) → XObject com máscara de transparência. Devolve (referência, largura, altura)."""
    import zlib
    from PIL import Image
    from pypdf.generic import DecodedStreamObject, NameObject, NumberObject
    image = image.convert('RGBA') if image.mode in ('RGBA', 'LA', 'P') else image.convert('RGB')
    image.thumbnail((2000, 2000))
    rgb = image.convert('RGB')
    base = _flate(writer, rgb.tobytes(), rgb.width, rgb.height, '/DeviceRGB')
    if image.mode == 'RGBA':
        alpha = image.getchannel('A')
        if alpha.getextrema()[0] < 255:
            mask = _flate(writer, alpha.tobytes(), rgb.width, rgb.height, '/DeviceGray')
            base[NameObject('/SMask')] = writer._add_object(mask)
    return writer._add_object(base), rgb.width, rgb.height


def _flate(writer, data: bytes, width: int, height: int, space: str):
    import zlib
    from pypdf.generic import DecodedStreamObject, NameObject, NumberObject
    stream = DecodedStreamObject()
    stream._data = zlib.compress(data, 6)
    stream[NameObject('/Filter')] = NameObject('/FlateDecode')
    for key, value in (('/Type', NameObject('/XObject')), ('/Subtype', NameObject('/Image')), ('/Width', NumberObject(width)), ('/Height', NumberObject(height)),
                       ('/ColorSpace', NameObject(space)), ('/BitsPerComponent', NumberObject(8))):
        stream[NameObject(key)] = value
    return stream


def place_signature(writer, page_number: int, area, image_ref, image_size) -> None:
    """Desenha a imagem dentro da `area` (milésimos da página como aparece), sem deformar e centralizada, respeitando rotação e CropBox."""
    from pypdf import PageObject
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
    import pdfstamp
    page = writer.pages[page_number - 1]
    geometry = pdfstamp.visible_geometry(page)
    vw, vh = pdfstamp.visible_size(geometry)
    x0, y0, x1, y1 = area
    left, right = vw * x0 / 1000, vw * x1 / 1000
    top, bottom = vh * (1 - y0 / 1000), vh * (1 - y1 / 1000)       # origem embaixo, Y para cima
    box_w, box_h = right - left, top - bottom
    ratio = image_size[0] / image_size[1]
    width, height = (box_w, box_w / ratio) if box_w / box_h <= ratio else (box_h * ratio, box_h)
    cx, cy = left + box_w / 2, bottom + box_h / 2
    origin = pdfstamp._to_user((cx - width / 2, cy - height / 2), geometry)
    right_pt = pdfstamp._to_user((cx + width / 2, cy - height / 2), geometry)
    up_pt = pdfstamp._to_user((cx - width / 2, cy + height / 2), geometry)
    a, b, c, d = right_pt[0] - origin[0], right_pt[1] - origin[1], up_pt[0] - origin[0], up_pt[1] - origin[1]
    overlay = PageObject.create_blank_page(None, abs(float(page.mediabox.width)), abs(float(page.mediabox.height)))
    overlay.mediabox = page.mediabox.__class__(list(page.mediabox))
    overlay[NameObject('/Resources')] = DictionaryObject({NameObject('/XObject'): DictionaryObject({NameObject('/SignImg'): image_ref})})
    stream = DecodedStreamObject(); stream.set_data(f'q {a:.5f} {b:.5f} {c:.5f} {d:.5f} {origin[0]:.4f} {origin[1]:.4f} cm /SignImg Do Q'.encode())
    overlay[NameObject('/Contents')] = stream
    page.merge_page(overlay)
