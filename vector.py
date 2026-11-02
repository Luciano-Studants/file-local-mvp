"""Entrada vetorial (SVG e SVGZ): leitura segura, limpeza e tamanho. Núcleo puro: não importa Qt.

A rasterização é uma *porta*: este módulo prepara um SVG limpo e o tamanho final em pixels e entrega a um adaptador
(`vector_qt.py`, carregado só na hora de desenhar). Assim o núcleo continua sem interface e o adaptador pode ser trocado
(por exemplo, por resvg) sem mexer no resto.

Regras de segurança (SVG é XML com referências externas, entidades e dimensões enormes):
- nada de rede nem de arquivos vizinhos: `href`/`url()` que não apontem para `#id` do próprio arquivo são removidos
  (exceção: imagens `data:` PNG/JPEG/GIF/WebP embutidas); `@import` e `@font-face` saem;
- scripts, `foreignObject`, `iframe` e atributos `on*` são descartados (nada é executado; é só defesa em profundidade);
- DOCTYPE com declaração de entidade é recusado (XXE, «billion laughs»); a DTD externa nunca é buscada;
- o desenho roda sem rede e sem acesso a arquivos vizinhos (o SVG limpo vai como texto para o desenhista);
- limites: 16 MiB de SVG, 50 MiB depois de descompactar SVGZ, 200 mil elementos, profundidade 128, 2 milhões de elementos
  depois de expandir `<use>`, referências circulares recusadas, 40 megapixels e 16384 px por lado na saída.
"""
import gzip
import importlib
import io
import math
import re
import zlib
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

VECTOR_SUFFIXES = frozenset({'.svg', '.svgz'})
SVG_MAX_BYTES = 16 * 1024 * 1024
SVGZ_MAX_BYTES = 50 * 1024 * 1024
SVG_MAX_ELEMENTS = 200_000
SVG_MAX_DEPTH = 128
SVG_MAX_EXPANSION = 2_000_000
VECTOR_MAX_SIDE = 16384
VECTOR_DEFAULT_MAX_SIDE = 8192
VECTOR_MAX_PIXELS = 40_000_000
DATA_IMAGE_MAX_BYTES = 12 * 1024 * 1024
ADAPTER_MODULES = ('vector_resvg', 'vector_qt')      # em ordem de preferência; o primeiro que carregar desenha

SVG_NS = 'http://www.w3.org/2000/svg'
XLINK_NS = 'http://www.w3.org/1999/xlink'
XML_NS = 'http://www.w3.org/XML/1998/namespace'
DROP_ELEMENTS = frozenset({'script', 'foreignobject', 'iframe', 'audio', 'video', 'embed', 'object'})
DATA_IMAGE_RE = re.compile(r'^data:image/(?:png|jpe?g|gif|webp)(?:;[a-z0-9=._+-]+)*,', re.I)
URL_REF_RE = re.compile(r'url\(\s*([\'"]?)(#[^)\'"]*)\1\s*\)', re.I)
URL_ANY_RE = re.compile(r'url\(\s*([\'"]?)(?!#)[^)]*\)', re.I)
CSS_IMPORT_RE = re.compile(r'@import\b[^;{]*;?', re.I)
CSS_FONTFACE_RE = re.compile(r'@font-face\s*\{[^}]*\}', re.I)
LENGTH_RE = re.compile(r'^\s*([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)\s*(px|pt|pc|mm|cm|in|em|ex|%)?\s*$')
UNIT_PX = {None: 1.0, 'px': 1.0, 'pt': 96 / 72, 'pc': 16.0, 'mm': 96 / 25.4, 'cm': 96 / 2.54, 'in': 96.0, 'em': 16.0, 'ex': 8.0}

ET.register_namespace('', SVG_NS)
ET.register_namespace('xlink', XLINK_NS)


class VectorError(Exception):
    """Erro de leitura ou de desenho do vetor; a mensagem já vem em português."""


@dataclass
class PreparedSvg:
    data: bytes                       # SVG limpo, pronto para o adaptador
    declared: tuple                   # (largura, altura) em px a 96 dpi, como o arquivo declara
    dropped: dict = field(default_factory=dict)      # o que foi ignorado: {'externas': n, 'scripts': n, ...}
    compressed: bool = False


def _local(name):
    return name.rsplit('}', 1)[-1].lower() if isinstance(name, str) else ''


def _namespace(name):
    return name[1:].split('}', 1)[0] if isinstance(name, str) and name.startswith('{') else ''


def read_svg_bytes(path):
    """Lê o arquivo (SVG ou SVGZ) com limite de tamanho, inclusive depois de descompactar."""
    path = Path(path)
    try:
        with path.open('rb') as handle: raw = handle.read(SVG_MAX_BYTES + 1)
    except OSError as error:
        raise VectorError(f'Não foi possível ler o SVG: {error.strerror or type(error).__name__}.')
    compressed = raw[:2] == b'\x1f\x8b'
    if path.suffix.lower() == '.svgz' and not compressed:
        compressed = False                                           # SVGZ que na verdade é texto: aceito como SVG
    if compressed:
        try:
            with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream: data = stream.read(SVGZ_MAX_BYTES + 1)
        except (OSError, EOFError, zlib.error):
            raise VectorError('O SVGZ está corrompido ou não é um arquivo compactado válido.')
        if len(data) > SVGZ_MAX_BYTES:
            raise VectorError('O SVGZ passa de 50 MiB depois de descompactado.')
        return data, True
    if len(raw) > SVG_MAX_BYTES:
        raise VectorError('O SVG passa de 16 MiB.')
    return raw, False


def _refuse_entity(*_args):
    raise VectorError('SVG com declaração de entidade XML (DOCTYPE com ENTITY) não é aceito por segurança.')


def parse_svg(data):
    """Interpreta o XML sem entidades e com limites de elementos e profundidade; devolve a raiz (árvore do ElementTree).

    Usa o expat direto: dá para recusar a declaração de entidade na hora em que ela aparece e abortar assim que um limite
    estoura, sem montar uma árvore gigante antes. A DTD externa nunca é buscada (o expat não carrega por padrão)."""
    from xml.parsers import expat
    parser = expat.ParserCreate(namespace_separator='}')
    parser.buffer_text = True
    stack, state = [], {'root': None, 'count': 0}

    def qualified(name):
        return '{' + name if '}' in name else name

    def start(name, attrs):
        state['count'] += 1
        if state['count'] > SVG_MAX_ELEMENTS: raise VectorError('O SVG tem elementos demais (limite de 200 mil).')
        if len(stack) >= SVG_MAX_DEPTH: raise VectorError('O SVG tem aninhamento profundo demais (limite de 128 níveis).')
        element = ET.Element(qualified(name), {qualified(k): v for k, v in attrs.items()})
        if stack: stack[-1].append(element)
        elif state['root'] is None: state['root'] = element
        else: raise VectorError('O SVG tem mais de um elemento raiz.')
        stack.append(element)

    def end(_name):
        stack.pop()

    def text(chunk):
        if not stack: return
        parent = stack[-1]
        if len(parent): parent[-1].tail = (parent[-1].tail or '') + chunk
        else: parent.text = (parent.text or '') + chunk

    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.CharacterDataHandler = text
    parser.EntityDeclHandler = _refuse_entity
    parser.UnparsedEntityDeclHandler = _refuse_entity
    parser.ExternalEntityRefHandler = lambda *_a: _refuse_entity()
    try:
        parser.Parse(data, True)
    except VectorError:
        raise
    except expat.ExpatError as error:
        raise VectorError('O arquivo não é um SVG/XML válido: ' + str(error)[:120])
    except (ValueError, LookupError, UnicodeError) as error:
        raise VectorError('O SVG tem codificação ou conteúdo inválido: ' + str(error)[:120])
    root = state['root']
    if root is None or _local(root.tag) != 'svg':
        raise VectorError('O arquivo não é um SVG: o elemento raiz deveria ser <svg>.')
    if _namespace(root.tag) not in ('', SVG_NS):
        raise VectorError('O arquivo não é um SVG: o espaço de nomes da raiz não é o do SVG.')
    return root


def _clean_css(text, dropped):
    original = text
    text = CSS_IMPORT_RE.sub('', text)
    text = CSS_FONTFACE_RE.sub('', text)
    text = URL_ANY_RE.sub('none', text)
    if text != original: dropped['externas'] = dropped.get('externas', 0) + 1
    return text


def sanitize(root):
    """Remove o que sai do arquivo ou executa algo. Altera a árvore e devolve o resumo do que foi ignorado."""
    dropped = {}

    def bump(key): dropped[key] = dropped.get(key, 0) + 1

    def walk(element):
        for child in list(element):
            name = _local(child.tag)
            ns = _namespace(child.tag)
            if ns not in ('', SVG_NS):                                # sodipodi, inkscape, rdf…: metadados do editor
                element.remove(child); continue
            if name in DROP_ELEMENTS:
                element.remove(child); bump('scripts' if name == 'script' else 'incorporados'); continue
            clean_attributes(child, name)
            if name == 'image' and not any(_local(k) == 'href' for k in child.attrib):
                element.remove(child); continue
            if name == 'style' and child.text: child.text = _clean_css(child.text, dropped)
            walk(child)

    def clean_attributes(element, name):
        for key in list(element.attrib):
            value = element.attrib[key]
            ns = _namespace(key)
            local = _local(key)
            if ns not in ('', XLINK_NS, XML_NS):
                del element.attrib[key]; continue
            if local.startswith('on'):
                del element.attrib[key]; bump('scripts'); continue
            if local == 'href':
                stripped = value.strip()
                if stripped.startswith('#'): element.attrib[key] = stripped; continue
                if name == 'image' and DATA_IMAGE_RE.match(stripped) and len(stripped) <= DATA_IMAGE_MAX_BYTES * 4 // 3 + 128:
                    element.attrib[key] = stripped; continue
                del element.attrib[key]; bump('externas'); continue
            if 'url(' in value.lower() or '@import' in value.lower():
                element.attrib[key] = _clean_css(value, dropped)

    # a própria raiz também passa pela limpeza de atributos
    clean_attributes(root, 'svg')
    walk(root)
    return dropped


def check_references(root):
    """Recusa referências circulares e expansões de `<use>` explosivas (nós: elementos; arestas: filhos e referências #id)."""
    elements = list(root.iter())
    ids = {}
    for element in elements:
        ident = element.attrib.get('id')
        if ident and ident not in ids: ids[ident] = element
    children = {id(e): list(e) for e in elements}
    refs, uses = {}, {}
    for element in elements:
        targets, use_targets = [], []
        for key, value in element.attrib.items():
            if _local(key) == 'href' and value.startswith('#') and value[1:] in ids:
                targets.append(ids[value[1:]])
                if _local(element.tag) == 'use': use_targets.append(ids[value[1:]])
            elif 'url(' in value.lower():
                for match in URL_REF_RE.finditer(value):
                    target = ids.get(match.group(2)[1:])
                    if target is not None: targets.append(target)
        if element.text and _local(element.tag) == 'style':
            for match in URL_REF_RE.finditer(element.text):
                target = ids.get(match.group(2)[1:])
                if target is not None: targets.append(target)
        refs[id(element)] = targets; uses[id(element)] = use_targets
    state, size = {}, {}                                   # 1 = no caminho, 2 = pronto
    for start in elements:
        if id(start) in state: continue
        stack = [(start, iter(children[id(start)] + refs[id(start)]))]
        state[id(start)] = 1
        while stack:
            node, iterator = stack[-1]
            advanced = False
            for nxt in iterator:
                mark = state.get(id(nxt))
                if mark == 1: raise VectorError('O SVG tem referências circulares (um elemento usa a si mesmo); não é possível desenhar com segurança.')
                if mark is None:
                    state[id(nxt)] = 1; stack.append((nxt, iter(children[id(nxt)] + refs[id(nxt)]))); advanced = True; break
            if advanced: continue
            total = 1 + sum(size[id(c)] for c in children[id(node)]) + sum(size[id(t)] for t in uses[id(node)])
            if total > SVG_MAX_EXPANSION: raise VectorError('O SVG expande para elementos demais ao repetir <use> (possível bomba de repetição).')
            size[id(node)] = total; state[id(node)] = 2; stack.pop()


def _length(value):
    match = LENGTH_RE.match(value or '')
    if not match: return None
    unit = match.group(2)
    if unit == '%': return None
    return float(match.group(1)) * UNIT_PX[unit]


def declared_size(root):
    """Tamanho do desenho em px (96 dpi): `width`/`height` do arquivo ou, na falta deles, o `viewBox`."""
    width, height = _length(root.attrib.get('width')), _length(root.attrib.get('height'))
    view = None
    parts = re.split(r'[\s,]+', (root.attrib.get('viewBox') or root.attrib.get('viewbox') or '').strip())
    if len(parts) == 4:
        try: view = tuple(float(x) for x in parts)
        except ValueError: view = None
    if view and (view[2] <= 0 or view[3] <= 0): view = None
    if width is not None and width <= 0 or height is not None and height <= 0:
        raise VectorError('O SVG declara largura ou altura zero ou negativa.')
    if width and height: return width, height
    if view:
        ratio = view[2] / view[3]
        if width: return width, width / ratio
        if height: return height * ratio, height
        return view[2], view[3]
    raise VectorError('O SVG não informa o tamanho (faltam width/height e viewBox); não dá para saber em que tamanho desenhar.')


def target_size(declared, width=None):
    """Tamanho final em pixels. `width` (px) pedido pelo usuário mantém a proporção; sem ele vale o tamanho do arquivo,
    reduzido se passar de 8192 px por lado ou de 40 megapixels. Devolve (largura, altura, reduzido)."""
    dw, dh = declared
    reduced = False
    if width:
        w, h = float(width), dh * width / dw
    else:
        w, h = dw, dh
        scale = min(1.0, VECTOR_DEFAULT_MAX_SIDE / max(w, h), (VECTOR_MAX_PIXELS / (w * h)) ** 0.5)
        if scale < 1.0: w, h, reduced = math.floor(w * scale), math.floor(h * scale), True        # arredonda para baixo: nunca passa do limite
    w, h = max(1, round(w)), max(1, round(h))
    if max(w, h) > VECTOR_MAX_SIDE or w * h > VECTOR_MAX_PIXELS:
        raise VectorError(f'O resultado ({w} × {h} px) passa do limite de {VECTOR_MAX_SIDE} px por lado ou de 40 megapixels.')
    return w, h, reduced


def prepare_svg(path):
    data, compressed = read_svg_bytes(path)
    root = parse_svg(data)
    dropped = sanitize(root)
    declared = declared_size(root)
    check_references(root)
    clean = ET.tostring(root, encoding='utf-8', xml_declaration=True)
    return PreparedSvg(clean, declared, dropped, compressed)


def _adapter():
    for name in ADAPTER_MODULES:
        try: return importlib.import_module(name)
        except ImportError: continue
    raise VectorError('Não há desenhista de SVG disponível neste computador (nem o resvg-py nem o QtSvg do PySide6 puderam ser carregados).')


def engine_info():
    """(rótulo, suporte completo?) do desenhista que será usado; None se não houver nenhum."""
    try: module = _adapter()
    except VectorError: return None
    return module.LABEL, bool(getattr(module, 'FULL_SUPPORT', False))


def rasterize_svg(path, width=None):
    """SVG/SVGZ → imagem RGBA do Pillow, com fundo transparente. `width` em px (opcional) escolhe o tamanho; sem ele vale o do arquivo."""
    prepared = prepare_svg(path)
    w, h, _reduced = target_size(prepared.declared, width)
    return _adapter().render(prepared.data, (w, h))


def describe_svg(path, width=None):
    """Resumo para o relatório de perdas e para a interface, sem desenhar."""
    prepared = prepare_svg(path)
    w, h, reduced = target_size(prepared.declared, width)
    return {'declared': prepared.declared, 'size': (w, h), 'reduced': reduced, 'dropped': prepared.dropped, 'compressed': prepared.compressed, 'engine': engine_info()}
