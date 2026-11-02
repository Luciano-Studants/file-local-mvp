"""Leitura segura de PDF: informações do arquivo, abertura com limites e páginas desenhadas em pixels (miniaturas e prévia).

Núcleo puro (sem Qt, sem importar o motor): erros `PdfError`; o motor os converte em `ConversionError`.
Um PDF é entrada hostil. Este módulo só lê: não executa JavaScript, não abre anexos nem links, não desenha formulários nem anotações,
não usa a rede e não pede senha (PDF protegido é apenas reconhecido e recusado). A interface nunca abre o PDF no próprio processo:
as informações e as miniaturas vêm do worker descartável (`run_op`, chamado por `engine.worker_main`), que tem limites de memória e de CPU.

Duas bibliotecas, cada uma no que faz melhor: `pypdf` (estrutura: páginas, metadados, indícios de formulário/script/anexos) e
`pypdfium2` (PDFium: desenhar páginas). Sem o `pypdfium2` as informações continuam funcionando e a prévia avisa que está indisponível.
"""
from __future__ import annotations

import re
from pathlib import Path

PDF_MAX_BYTES = 100 * 1024 * 1024
PDF_MAX_PAGES = 200                    # mesmo limite das ferramentas de PDF do motor
MAX_PAGE_POINTS = 14_400               # lado máximo de uma página para ser desenhada (200 polegadas; o Acrobat vai até 200 pol.)
MAX_RENDER_SIDE = 2400                 # maior lado, em px, de uma página desenhada
MAX_RENDER_PIXELS = 12_000_000         # teto de pixels por página desenhada (a prévia nunca precisa de mais)
MAX_PREVIEW_PAGES = 24                 # miniaturas por pedido
THUMB_SIDE = 150
PAGE_SIDE = 900
TEXT_SAMPLE_PAGES = 3                  # páginas olhadas para saber se há camada de texto
DPI_MIN, DPI_MAX, DPI_DEFAULT = 72, 600, 150
MAX_IMAGE_PIXELS = 40_000_000           # mesmo teto de pixels das imagens do motor; vale por página
PREVIEW_DIR_PREFIX = '.arquivo-local-preview-'
HEADER_WINDOW = 1024                   # o cabeçalho «%PDF-» pode ter lixo antes, como aceitam os leitores comuns

PAPER_SIZES_MM = (('A5', 148, 210), ('A4', 210, 297), ('A3', 297, 420), ('Carta', 215.9, 279.4), ('Ofício', 215.9, 355.6))
PAPER_TOLERANCE_MM = 2.5


class PdfError(ValueError):
    pass


# ----------------------------------------------------------------------------
# bibliotecas
# ----------------------------------------------------------------------------
def _pypdf():
    try:
        import pypdf
    except ImportError as error:
        raise PdfError('Para ler PDFs instale o pacote pypdf («pip install -r requirements.txt»).') from error
    return pypdf


def _pdfium():
    try:
        import pypdfium2
    except ImportError as error:
        raise PdfError('A prévia das páginas precisa do pacote pypdfium2 («pip install -r requirements.txt»).') from error
    return pypdfium2


def preview_available() -> bool:
    try:
        _pdfium()
    except PdfError:
        return False
    return True


# ----------------------------------------------------------------------------
# arquivo
# ----------------------------------------------------------------------------
def read_pdf_bytes(path) -> bytes:
    """Lê o arquivo e confere tamanho e cabeçalho. Devolve os bytes a partir do `%PDF-`."""
    path = Path(path)
    size = path.stat().st_size
    if size == 0 or size > PDF_MAX_BYTES:
        raise PdfError('O PDF não pode estar vazio nem passar de 100 MiB.')
    data = path.read_bytes()
    start = data[:HEADER_WINDOW].find(b'%PDF-')
    if start < 0:
        raise PdfError('Este arquivo não parece um PDF (falta o cabeçalho «%PDF-»); ele pode estar danificado ou ter outra extensão.')
    return data[start:]


def _reader(data: bytes):
    import io
    pypdf = _pypdf()
    try:
        return pypdf.PdfReader(io.BytesIO(data), strict=False)
    except Exception as error:                      # o pypdf levanta tipos variados em arquivo quebrado
        raise PdfError('Não foi possível ler este PDF: o arquivo está danificado, truncado ou fora do padrão.') from error


def _is_locked(reader) -> bool:
    """True se o PDF exige senha. PDF com senha de abertura vazia (só restrições) também é tratado como protegido: o app não os abre."""
    try:
        return bool(reader.is_encrypted)
    except Exception:
        return True


RESTRICTION_BITS = 4 | 8 | 16 | 32 | 256 | 512 | 1024 | 2048     # imprimir, alterar, copiar, anotar, preencher, extrair, montar, imprimir em alta qualidade


def open_protected(path, password: str):
    """Abre um PDF com senha usando a senha informada (UMA tentativa, sem adivinhar nada). Devolve (leitor, tipo) com tipo 0 = sem senha no arquivo, 1 = senha de abertura, 2 = senha do proprietário."""
    reader = _reader(read_pdf_bytes(path))
    kind = 0
    try:
        if reader.is_encrypted:
            kind = int(reader.decrypt(password))
            if kind == 0:
                raise PdfError('A senha não abriu o PDF. Confira a senha (maiúsculas e minúsculas contam).')
    except PdfError:
        raise
    except Exception as error:
        raise PdfError('Não foi possível abrir este PDF com a senha informada: a criptografia dele não é suportada ou o arquivo está danificado.') from error
    try:
        pages = len(reader.pages)
    except Exception as error:
        raise PdfError('Não foi possível ler as páginas deste PDF: o arquivo está danificado ou truncado.') from error
    if not 0 < pages <= PDF_MAX_PAGES:
        raise PdfError(f'Os PDFs devem ter de 1 a {PDF_MAX_PAGES} páginas.')
    return reader, kind


def has_restrictions(reader) -> bool:
    """True se o PDF (já aberto) limita impressão, cópia, edição… para quem só tem a senha de abertura."""
    try:
        flags = reader.user_access_permissions
        return flags is not None and (int(flags) & RESTRICTION_BITS) != RESTRICTION_BITS
    except Exception:
        return False


def open_reader(path):
    """Abre um PDF para as ferramentas do motor (unir, separar, texto): confere tamanho, cabeçalho, senha e número de páginas."""
    reader = _reader(read_pdf_bytes(path))
    if _is_locked(reader):
        raise PdfError('Este PDF tem senha. Para usá-lo aqui, gere antes uma cópia sem senha em PDF › Remover senha.')
    try:
        pages = len(reader.pages)
    except Exception as error:
        raise PdfError('Não foi possível ler as páginas deste PDF: o arquivo está danificado ou truncado.') from error
    if not 0 < pages <= PDF_MAX_PAGES:
        raise PdfError(f'Os PDFs devem ter de 1 a {PDF_MAX_PAGES} páginas.')
    return reader


# ----------------------------------------------------------------------------
# informações
# ----------------------------------------------------------------------------
def _clean(value, limit=200) -> str:
    text = re.sub(r'[\x00-\x1f\x7f]+', ' ', str(value or '')).strip()
    text = re.sub(r'\s+', ' ', text)
    return text[:limit]


def pdf_date(raw) -> str:
    """«D:20240131154500-03'00'» → «2024-01-31». Texto que não segue o padrão volta limpo e curto."""
    text = _clean(raw, 40)
    match = re.match(r'^D?:?(\d{4})(\d\d)?(\d\d)?', text)
    if not match:
        return text
    year, month, day = match.group(1), match.group(2), match.group(3)
    if month and day and 1 <= int(month) <= 12 and 1 <= int(day) <= 31:
        return f'{year}-{month}-{day}'
    return year


def paper_name(width_pt: float, height_pt: float) -> str:
    """Nome do papel (A4, Carta…) ou medida em mm; a orientação não importa."""
    w, h = sorted((width_pt / 72 * 25.4, height_pt / 72 * 25.4))
    for name, pw, ph in PAPER_SIZES_MM:
        if abs(w - pw) <= PAPER_TOLERANCE_MM and abs(h - ph) <= PAPER_TOLERANCE_MM:
            return name
    return f'{w:.0f} × {h:.0f} mm'


def _page_points(page):
    """(largura, altura) da página em pontos, já com a rotação aplicada."""
    box = page.mediabox
    width, height = abs(float(box.width)), abs(float(box.height))
    try:
        rotation = int(page.rotation or 0) % 360
    except Exception:
        rotation = 0
    return (height, width) if rotation in (90, 270) else (width, height)


def _text_layer(reader, pages: int) -> str:
    """'sim' / 'não' / 'desconhecido': olha só as primeiras páginas, então é um indício e não uma garantia."""
    found, tried = False, 0
    for index in range(min(pages, TEXT_SAMPLE_PAGES)):
        try:
            text = reader.pages[index].extract_text() or ''
        except Exception:
            continue
        tried += 1
        if len(text.strip()) >= 20:
            found = True
            break
    if found:
        return 'sim'
    return 'não' if tried else 'desconhecido'


def _structure_flags(reader) -> dict:
    """Formulário, script e anexos pela estrutura do documento (não por busca de texto, que falha em arquivos comprimidos)."""
    flags = {'forms': False, 'javascript': False, 'attachments': False}
    try:
        root = reader.trailer['/Root']
        flags['forms'] = '/AcroForm' in root
        names = root.get('/Names')
        if names is not None:
            names = names.get_object()
            flags['javascript'] = '/JavaScript' in names
            flags['attachments'] = '/EmbeddedFiles' in names
        action = root.get('/OpenAction')
        if action is not None:
            action = action.get_object()
            if hasattr(action, 'get') and str(action.get('/S')) == '/JavaScript':
                flags['javascript'] = True
        if '/AA' in root:
            flags['javascript'] = True
    except Exception:
        pass
    return flags


INFO_LABELS = {'/Title': 'Título', '/Author': 'Autor', '/Subject': 'Assunto', '/Keywords': 'Palavras-chave', '/Creator': 'Programa que criou',
               '/Producer': 'Programa que gerou o PDF', '/CreationDate': 'Criado em', '/ModDate': 'Alterado em', '/Trapped': 'Trapped'}
XMP_MAX = 1024 * 1024
MAX_FIELDS = 40


def _xmp_text(root) -> str:
    """Texto do pacote XMP do documento ('' se não houver ou se passar de 1 MiB)."""
    try:
        stream = root.get('/Metadata')
        if stream is None:
            return ''
        data = stream.get_object().get_data()
    except Exception:
        return ''
    return data[:XMP_MAX].decode('utf8', 'replace') if data else ''


def _xmp_fields(text: str) -> list:
    found = []
    for label, pattern in (('Autor (XMP)', r'<dc:creator>.*?<rdf:li[^>]*>(.*?)</rdf:li>'), ('Programa (XMP)', r'<xmp:CreatorTool>(.*?)</xmp:CreatorTool>'),
                           ('Gerador (XMP)', r'<pdf:Producer>(.*?)</pdf:Producer>'), ('Criado (XMP)', r'<xmp:CreateDate>(.*?)</xmp:CreateDate>')):
        match = re.search(pattern, text, re.S)
        if match and _clean(match.group(1)):
            found.append([label, _clean(match.group(1), 120)])
    return found


def _attachment_names(root, reader=None) -> list:
    """Nomes dos anexos da árvore de nomes (até 20); lê só as folhas imediatas e os filhos de primeiro nível."""
    names = []
    try:
        node = root['/Names'].get_object()['/EmbeddedFiles'].get_object()
        stack = [node]
        while stack and len(names) < 20:
            current = stack.pop().get_object()
            pairs = current.get('/Names')
            if pairs:
                pairs = pairs.get_object()
                for index in range(0, len(pairs) - 1, 2):
                    names.append(_clean(pairs[index].get_object() if hasattr(pairs[index], 'get_object') else pairs[index], 120))
                    if len(names) >= 20:
                        break
            for kid in (current.get('/Kids') or []):
                if len(stack) < 50:
                    stack.append(kid)
    except Exception:
        pass
    return names


def metadata_details(reader) -> dict:
    """Tudo o que a ferramenta de metadados mostra: campos do dicionário Info, XMP, nomes dos anexos."""
    details = {'meta_fields': [], 'xmp': False, 'xmp_fields': [], 'attachment_names': []}
    try:
        meta = reader.metadata
        if meta:
            for key, value in list(meta.items())[:MAX_FIELDS]:
                text = pdf_date(value) if key in ('/CreationDate', '/ModDate') else _clean(value, 120)
                if text:
                    details['meta_fields'].append([INFO_LABELS.get(str(key), str(key).lstrip('/')[:40]), text])
    except Exception:
        pass
    try:
        root = reader.trailer['/Root']
        text = _xmp_text(root)
        details['xmp'] = '/Metadata' in root
        details['xmp_fields'] = _xmp_fields(text) if text else []
        details['attachment_names'] = _attachment_names(root)
    except Exception:
        pass
    return details


# ----------------------------------------------------------------------------
# cópia limpa: o que existe e remoção

PAGE_EXTRAS = ('/Metadata', '/PieceInfo', '/Thumb')
MAX_FIELD_NODES = 20000


def _js_action(action, depth=0) -> bool:
    """True se a ação (ou alguma da cadeia /Next) executa JavaScript."""
    try:
        action = action.get_object() if hasattr(action, 'get_object') else action
        if depth > 20 or not hasattr(action, 'get'):
            return False
        if str(action.get('/S')) == '/JavaScript' or '/JS' in action:
            return True
        following = action.get('/Next')
        if following is None:
            return False
        following = following.get_object() if hasattr(following, 'get_object') else following
        if isinstance(following, list):
            return any(_js_action(item, depth + 1) for item in following)
        return _js_action(following, depth + 1)
    except Exception:
        return False


def _holder_has_js(holder) -> bool:
    try:
        if '/A' in holder and _js_action(holder['/A']):
            return True
        extra = holder.get('/AA')
        if extra is not None:
            extra = extra.get_object()
            return any(_js_action(value) for value in extra.values())
    except Exception:
        pass
    return False


def _strip_js(holder) -> None:
    try:
        if '/A' in holder and _js_action(holder['/A']):
            del holder['/A']
        extra = holder.get('/AA')
        if extra is not None:
            extra = extra.get_object()
            for key in [key for key, value in extra.items() if _js_action(value)]:
                del extra[key]
            if not extra:
                del holder['/AA']
    except Exception:
        pass


def _field_nodes(root):
    """Campos do formulário (árvore /Fields e /Kids), sem repetir e com teto."""
    try:
        stack = list(root['/AcroForm'].get_object().get('/Fields') or [])
    except Exception:
        return
    seen = set()
    while stack and len(seen) < MAX_FIELD_NODES:
        node = stack.pop()
        try:
            marker = getattr(node, 'idnum', None) or id(node)
            if marker in seen:
                continue
            seen.add(marker)
            node = node.get_object()
            yield node
            stack.extend(node.get('/Kids') or [])
        except Exception:
            continue


def _annotations(page):
    try:
        return [item.get_object() for item in (page.get('/Annots') or [])]
    except Exception:
        return []


def _is_attachment_annot(annot) -> bool:
    return str(annot.get('/Subtype')) == '/FileAttachment'


def _action_holders(root, pages):
    yield root
    for page in pages:
        yield page
        for annot in _annotations(page):
            yield annot
    yield from _field_nodes(root)


def clean_scan(reader) -> dict:
    """{'info', 'attach', 'js'}: o que a cópia limpa teria para remover neste PDF (olha até 200 páginas)."""
    found = {'info': False, 'attach': False, 'js': False}
    try:
        root = reader.trailer['/Root']
        pages = list(reader.pages)[:PDF_MAX_PAGES]
        try:
            found['info'] = bool(reader.metadata)
        except Exception:
            pass
        found['info'] = found['info'] or '/Metadata' in root or '/PieceInfo' in root or any(key in page for page in pages for key in PAGE_EXTRAS)
        names = root.get('/Names')
        names = names.get_object() if names is not None else {}
        found['attach'] = '/EmbeddedFiles' in names or any(_is_attachment_annot(annot) for page in pages for annot in _annotations(page))
        action = root.get('/OpenAction')
        found['js'] = '/JavaScript' in names or (action is not None and _js_action(action)) or any(_holder_has_js(holder) for holder in _action_holders(root, pages))
        try:
            found['js'] = found['js'] or '/XFA' in root['/AcroForm'].get_object()
        except Exception:
            pass
    except Exception:
        pass
    return found


def clean_apply(writer, info=False, attach=False, js=False) -> None:
    """Remove do PDF aberto no `writer` o que foi pedido. O dicionário Info (`writer._info`) é tratado por quem chama."""
    from pypdf.generic import ArrayObject, NameObject
    root = writer._root_object
    pages = list(writer.pages)
    names = root.get('/Names')
    names = names.get_object() if names is not None else None
    if info:
        for key in ('/Metadata', '/PieceInfo'):
            root.pop(key, None)
        for page in pages:
            for key in PAGE_EXTRAS:
                page.pop(key, None)
    if attach:
        if names is not None:
            names.pop('/EmbeddedFiles', None)
        for page in pages:
            raw = page.get('/Annots')
            if raw is not None:
                kept = [item for item in raw.get_object() if not _is_attachment_annot(item.get_object())]
                if len(kept) != len(raw.get_object()):
                    page[NameObject('/Annots')] = ArrayObject(kept)
    if js:
        if names is not None:
            names.pop('/JavaScript', None)
        action = root.get('/OpenAction')
        if action is not None and _js_action(action):
            del root['/OpenAction']
        for holder in _action_holders(root, pages):
            _strip_js(holder)
        try:
            root['/AcroForm'].get_object().pop('/XFA', None)
        except Exception:
            pass


def inspect_pdf(path) -> dict:
    """Resumo do PDF para a interface e os relatórios; não desenha nada. Erros de arquivo viram `PdfError`; PDF com senha é descrito, não recusado."""
    path = Path(path)
    data = read_pdf_bytes(path)
    info = {'name': path.name, 'size_bytes': len(data), 'version': '', 'encrypted': False, 'pages': None, 'page_size': '', 'page_points': None,
            'mixed_sizes': False, 'metadata': {}, 'meta_fields': [], 'xmp': False, 'xmp_fields': [], 'attachment_names': [], 'text_layer': 'desconhecido', 'forms': False, 'javascript': False, 'attachments': False, 'too_many_pages': False}
    version = re.match(rb'%PDF-(\d\.\d)', data[:16])
    if version:
        info['version'] = version.group(1).decode('ascii')
    reader = _reader(data)
    if _is_locked(reader):
        info['encrypted'] = True
        return info
    try:
        pages = len(reader.pages)
    except Exception as error:
        raise PdfError('Não foi possível ler as páginas deste PDF: o arquivo está danificado ou truncado.') from error
    if pages < 1:
        raise PdfError('Este PDF não tem nenhuma página.')
    info['pages'] = pages
    info['too_many_pages'] = pages > PDF_MAX_PAGES
    try:
        first = _page_points(reader.pages[0])
        info['page_points'] = [round(first[0], 1), round(first[1], 1)]
        info['page_size'] = paper_name(*first)
        for index in range(1, min(pages, PDF_MAX_PAGES)):
            other = _page_points(reader.pages[index])
            if abs(other[0] - first[0]) > 2 or abs(other[1] - first[1]) > 2:
                info['mixed_sizes'] = True
                break
    except Exception:
        pass
    try:
        meta = reader.metadata
        if meta:
            info['metadata'] = {key: value for key, value in {
                'title': _clean(meta.get('/Title')), 'author': _clean(meta.get('/Author')), 'subject': _clean(meta.get('/Subject')),
                'creator': _clean(meta.get('/Creator')), 'producer': _clean(meta.get('/Producer')), 'created': pdf_date(meta.get('/CreationDate')),
                'modified': pdf_date(meta.get('/ModDate'))}.items() if value}
    except Exception:
        pass
    info['text_layer'] = _text_layer(reader, pages)
    info.update(_structure_flags(reader))
    info['form_fields'] = []
    if info.get('forms'):
        try:
            import pdfform
            info['form_fields'] = pdfform.list_fields(reader)
        except Exception:
            info['form_fields'] = []
    info.update(metadata_details(reader))
    return info


def summary_text(info: dict) -> str:
    """Uma linha curta em português para a interface: «12 páginas · A4 · 1,2 MB · PDF 1.7 · com texto»."""
    if info.get('error'):
        return info['error']
    if info.get('encrypted'):
        return f'Protegido por senha · {human_bytes(info.get("size_bytes", 0))}. O Arquivo Local não abre PDFs protegidos.'
    pages = info.get('pages') or 0
    parts = [f'{pages} {"página" if pages == 1 else "páginas"}']
    if info.get('page_size'):
        parts.append(info['page_size'] + (' (tamanhos variados)' if info.get('mixed_sizes') else ''))
    parts.append(human_bytes(info.get('size_bytes', 0)))
    if info.get('version'):
        parts.append('PDF ' + info['version'])
    layer = info.get('text_layer')
    parts.append({'sim': 'com texto', 'não': 'sem camada de texto (talvez digitalizado)'}.get(layer, 'texto não verificado'))
    extras = [label for key, label in (('forms', 'formulário'), ('javascript', 'JavaScript'), ('attachments', 'anexos')) if info.get(key)]
    if extras:
        parts.append('contém ' + ', '.join(extras))
    text = ' · '.join(parts)
    if info.get('too_many_pages'):
        text += f' · passa do limite de {PDF_MAX_PAGES} páginas das ferramentas'
    return text


def human_bytes(size: int) -> str:
    if size < 1024 * 1024:
        return f'{max(1, round(size / 1024)):,} KB'.replace(',', '.')
    return f'{size / 1024 / 1024:,.1f} MB'.replace('.', ',')


# ----------------------------------------------------------------------------
# páginas em pixels
# ----------------------------------------------------------------------------
def open_document(path):
    """Abre o PDF no pypdfium2 (a partir dos bytes já limitados). O chamador fecha o documento."""
    pdfium = _pdfium()
    data = read_pdf_bytes(path)
    try:
        return pdfium.PdfDocument(data)
    except pdfium.PdfiumError as error:
        if 'password' in str(error).lower():
            raise PdfError('Este PDF está protegido por senha; o Arquivo Local não abre PDFs protegidos.') from error
        raise PdfError('Não foi possível desenhar este PDF: o arquivo está danificado ou fora do padrão.') from error


def parse_page_range(text, count: int) -> list:
    """Converte «1-3,7», «5-» (até o fim), «-3» (as três primeiras) ou vazio (todas) em números de página a partir de 1, sem repetição e na ordem pedida."""
    if type(count) is not int or count < 1:
        raise PdfError('Este PDF não tem nenhuma página.')
    raw = str(text or '').strip().replace(';', ',')
    if not raw:
        return list(range(1, count + 1))
    pages, seen = [], set()
    for token in raw.split(','):
        token = token.strip().replace(' ', '')
        if not token:
            raise PdfError('Intervalo de páginas inválido: há uma vírgula sobrando. Exemplo: 1-3,7.')
        if re.fullmatch(r'\d{1,6}', token):
            start = end = int(token)
        elif re.fullmatch(r'\d{1,6}-\d{0,6}', token) or re.fullmatch(r'-\d{1,6}', token):
            left, right = token.split('-')
            start = int(left) if left else 1
            end = int(right) if right else count
        else:
            raise PdfError(f'Intervalo de páginas inválido: «{token[:20]}». Use números, vírgulas e hífens, como 1-3,7.')
        if start < 1 or end < start:
            raise PdfError(f'Intervalo de páginas inválido: «{token}». As páginas começam em 1 e o intervalo vai do menor ao maior.')
        if end > count:
            raise PdfError(f'O PDF tem {count} {"página" if count == 1 else "páginas"}; «{token}» passa do fim.')
        for number in range(start, end + 1):
            if number not in seen:
                seen.add(number); pages.append(number)
    if len(pages) > PDF_MAX_PAGES:
        raise PdfError(f'Escolha no máximo {PDF_MAX_PAGES} páginas por vez.')
    return pages


def parse_page_groups(text, count: int) -> list:
    """«1-3; 4,6; 9-» → uma lista de páginas por grupo (grupos separados por «;» ou quebra de linha; páginas de cada grupo como em `parse_page_range`)."""
    raw = str(text or '').strip()
    if not raw:
        raise PdfError('Escreva os intervalos, por exemplo 1-3; 4-6; 7-.')
    parts = [part.strip() for part in re.split(r'[;\n]', raw)]
    if parts and parts[-1] == '':
        parts.pop()                    # «1-3;» (ponto e vírgula no fim) não gera grupo vazio
    if not parts or len(parts) > PDF_MAX_PAGES:
        raise PdfError(f'Use de 1 a {PDF_MAX_PAGES} grupos de páginas.')
    groups = []
    for part in parts:
        if not part:
            raise PdfError('Há um grupo de páginas vazio entre dois «;».')
        groups.append(parse_page_range(part.replace(';', ','), count))
    return groups


def dpi_size(width_pt: float, height_pt: float, dpi: int):
    """Tamanho em pixels de uma página a `dpi` (arredondado para cima, mínimo 1)."""
    import math
    return max(1, math.ceil(width_pt * dpi / 72)), max(1, math.ceil(height_pt * dpi / 72))


def check_dpi(dpi) -> int:
    if type(dpi) is not int or not DPI_MIN <= dpi <= DPI_MAX:
        raise PdfError(f'A resolução deve ficar entre {DPI_MIN} e {DPI_MAX} dpi.')
    return dpi


def page_pixels_ok(number: int, width_pt: float, height_pt: float, dpi: int):
    """Confere o tamanho da página e o teto de 40 MP a `dpi`; devolve (largura, altura) em px ou levanta PdfError em português."""
    if not (0 < width_pt <= MAX_PAGE_POINTS and 0 < height_pt <= MAX_PAGE_POINTS):
        raise PdfError(f'O tamanho da página {number} é inválido ou grande demais para desenhar.')
    w, h = dpi_size(width_pt, height_pt, dpi)
    if w * h > MAX_IMAGE_PIXELS:
        limit = int(72 * (MAX_IMAGE_PIXELS / (width_pt * height_pt)) ** 0.5)
        raise PdfError(f'A página {number} ficaria com {w} × {h} px ({w * h / 1e6:.0f} megapixels), acima do limite de 40 megapixels. '
                       f'Use no máximo {max(1, limit)} dpi para esta página ou escolha outras páginas.')
    return w, h


def render_dpi(document, number: int, dpi: int):
    """Desenha a página `number` (a partir de 1) de um documento aberto a `dpi`, em RGB sobre fundo branco. O chamador fecha a imagem."""
    pdfium = _pdfium()
    check_dpi(dpi)
    page = document[number - 1]
    try:
        width, height = page.get_size()
        page_pixels_ok(number, width, height, dpi)
        try:
            bitmap = page.render(scale=dpi / 72, may_draw_forms=False, draw_annots=False, fill_color=(255, 255, 255, 255), rev_byteorder=False)
            image = bitmap.to_pil()
        except (pdfium.PdfiumError, MemoryError, ValueError) as error:
            raise PdfError(f'Não foi possível desenhar a página {number}: memória insuficiente ou página fora do padrão.') from error
        if image.mode != 'RGB':
            converted = image.convert('RGB'); image.close(); image = converted
        return image
    finally:
        page.close()


def render_pages(path, pages, side: int):
    """Desenha as páginas pedidas (números a partir de 1) com o maior lado em `side` px. Devolve uma lista de (número, imagem RGB do Pillow).

    Formulários e anotações não são desenhados; o fundo é branco opaco. O chamador fecha as imagens.
    """
    pdfium = _pdfium()
    if not isinstance(side, int) or not 16 <= side <= MAX_RENDER_SIDE:
        raise PdfError(f'O tamanho da prévia deve ficar entre 16 e {MAX_RENDER_SIDE} px.')
    wanted = list(pages)
    if not wanted or len(wanted) > MAX_PREVIEW_PAGES or any(type(n) is not int or n < 1 for n in wanted):
        raise PdfError('Pedido de páginas inválido.')
    document = open_document(path)
    result = []
    try:
        count = len(document)
        if count < 1:
            raise PdfError('Este PDF não tem nenhuma página.')
        if any(n > count for n in wanted):
            raise PdfError(f'O PDF tem {count} {"página" if count == 1 else "páginas"}; a página pedida não existe.')
        for number in wanted:
            page = document[number - 1]
            try:
                width, height = page.get_size()
                if not (0 < width <= MAX_PAGE_POINTS and 0 < height <= MAX_PAGE_POINTS):
                    raise PdfError('O tamanho da página é inválido ou grande demais para desenhar.')
                scale = side / max(width, height)
                if width * scale * height * scale > MAX_RENDER_PIXELS:
                    scale = (MAX_RENDER_PIXELS / (width * height)) ** 0.5
                try:
                    bitmap = page.render(scale=scale, may_draw_forms=False, draw_annots=False, fill_color=(255, 255, 255, 255), rev_byteorder=False)
                    image = bitmap.to_pil()
                except (pdfium.PdfiumError, MemoryError, ValueError) as error:
                    raise PdfError(f'Não foi possível desenhar a página {number}: memória insuficiente ou página fora do padrão.') from error
                if image.mode != 'RGB':
                    converted = image.convert('RGB'); image.close(); image = converted
                result.append((number, image))
            finally:
                page.close()
    except BaseException:
        for _number, image in result:
            image.close()
        raise
    finally:
        document.close()
    return result


# ----------------------------------------------------------------------------
# operações do worker
# ----------------------------------------------------------------------------
def _safe_preview_dir(raw) -> Path:
    folder = Path(str(raw))
    if not folder.is_absolute() or folder.is_symlink() or not folder.is_dir() or not folder.name.startswith(PREVIEW_DIR_PREFIX):
        raise PdfError('Pasta de prévia inválida.')
    return folder


def _error_text(error: Exception) -> str:
    return str(error)[:300] or type(error).__name__


def run_op(job: dict, source_file=None) -> dict:
    """Operações de leitura pedidas à interface, executadas no worker.

    `pdf_info`: `paths` (até 100) → `{'infos': [info | {'name', 'error'}]}` (um erro de arquivo não derruba a lista).
    `pdf_preview`: `path`, `out` (pasta de prévia), `thumbs` (0–24, miniaturas a partir da página `first`, padrão 1), `thumb_side`, `page` (0 = nenhuma), `page_side`
    → `{'info': …, 'files': [{'page': n, 'kind': 'thumb'|'page', 'file': nome, 'size': [w, h]}]}`.
    `source_file` valida o caminho (o motor passa a sua função; sem ela só se exige caminho absoluto e arquivo comum).
    """
    check = source_file or _plain_source
    op = job.get('op')
    if op == 'pdf_info':
        raws = job.get('paths')
        if not isinstance(raws, list) or not 1 <= len(raws) <= 100:
            raise PdfError('Escolha de 1 a 100 PDFs.')
        infos = []
        for raw in raws:
            name = Path(str(raw)).name
            try:
                infos.append(inspect_pdf(check(raw)))
            except OSError:
                infos.append({'name': name, 'error': 'O arquivo não pôde ser aberto (foi movido, apagado ou está em uso).'})
            except (PdfError, ValueError) as error:
                infos.append({'name': name, 'error': _error_text(error)})
        return {'infos': infos}
    if op == 'pdf_preview':
        path = check(job.get('path'))
        out = _safe_preview_dir(job.get('out'))
        thumbs, page, first = job.get('thumbs', 0), job.get('page', 0), job.get('first', 1)
        thumb_side, page_side = job.get('thumb_side', THUMB_SIDE), job.get('page_side', PAGE_SIDE)
        if any(type(v) is not int for v in (thumbs, page, first, thumb_side, page_side)) or not 0 <= thumbs <= MAX_PREVIEW_PAGES or not 0 <= page <= PDF_MAX_PAGES or not 1 <= first <= PDF_MAX_PAGES \
                or not 16 <= thumb_side <= MAX_RENDER_SIDE or not 16 <= page_side <= MAX_RENDER_SIDE:
            raise PdfError('Pedido de prévia inválido.')
        info = inspect_pdf(path)
        files = []
        if info.get('encrypted') or not info.get('pages'):
            return {'info': info, 'files': files}
        if info['pages'] > PDF_MAX_PAGES:
            info['preview_note'] = f'O PDF tem mais de {PDF_MAX_PAGES} páginas; só as primeiras aparecem.'
        requests = []
        if page:
            requests.append(('page', [page], page_side))
        if thumbs:
            numbers = list(range(first, min(first + thumbs - 1, info['pages'], PDF_MAX_PAGES) + 1))
            if numbers:
                requests.append(('thumb', numbers, thumb_side))
        if requests and not preview_available():
            info['preview_note'] = 'A prévia das páginas precisa do pacote pypdfium2; as informações do arquivo continuam disponíveis.'
            return {'info': info, 'files': files}
        for kind, numbers, side in requests:
            try:
                rendered = render_pages(path, numbers, side)
            except PdfError as error:
                info['preview_note'] = _error_text(error)
                break
            for number, image in rendered:
                try:
                    name = f'{kind}-{number:03d}.png'
                    image.save(out / name, format='PNG')
                    files.append({'page': number, 'kind': kind, 'file': name, 'size': list(image.size)})
                finally:
                    image.close()
        return {'info': info, 'files': files}
    raise PdfError('Operação de PDF desconhecida.')


def _plain_source(raw) -> Path:
    path = Path(str(raw or ''))
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise PdfError('Escolha um arquivo PDF local.')
    return path
