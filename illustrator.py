"""Leitura de arquivos do Adobe Illustrator (.ai) «compatíveis com PDF», desenhados em pixels com o PDFium (pacote `pypdfium2`).

Núcleo puro (sem Qt, sem importar o motor): erros `AiError`; o motor os converte em `ConversionError`.
Um `.ai` moderno guarda, junto dos dados próprios do Illustrator, um PDF completo — é ele que é desenhado (a primeira página, que é a
primeira prancheta). Um `.ai` antigo, em PostScript, ou um salvo sem «Criar arquivo compatível com PDF» não tem esse conteúdo e é recusado
com uma mensagem clara; nada é simulado. O tamanho padrão é o da página em pontos, com 1 pt = 1 px (como o Illustrator exporta), e vale
a mesma regra de largura, de limites e de 40 megapixels dos SVG (`vector.target_size`).

Segurança: o PDFium é uma biblioteca nativa e roda no processo do worker (com limites de memória e de CPU); o pypdfium2 não traz JavaScript,
formulários nem anotações são desenhados, nada é buscado na rede e anexos são ignorados. Senha não é pedida: PDF protegido é recusado.
"""
from __future__ import annotations

from pathlib import Path

import vector

SUFFIXES = frozenset({'.ai'})
AI_MAX_BYTES = 100 * 1024 * 1024
LABEL = 'PDFium'
STUB_TEXT = 'without pdf content'          # texto da página que o Illustrator grava quando o arquivo é salvo sem a parte de PDF
MAX_POINTS = 200_000                       # lado máximo da página, em pontos (o Illustrator vai até ~16 383 pt)


class AiError(ValueError):
    pass


def _pdfium():
    try:
        import pypdfium2
    except ImportError as error:
        raise AiError('Para abrir arquivos .ai instale o pacote pypdfium2 («pip install -r requirements.txt»).') from error
    return pypdfium2


def available():
    try:
        _pdfium()
    except AiError:
        return False
    return True


def read_ai_bytes(path):
    """Lê o arquivo e confere que ele tem a parte de PDF. Devolve os bytes (a partir do cabeçalho `%PDF-`)."""
    path = Path(path)
    size = path.stat().st_size
    if size == 0 or size > AI_MAX_BYTES:
        raise AiError('O arquivo .ai não pode estar vazio nem passar de 100 MiB.')
    data = path.read_bytes()
    start = data[:1024].find(b'%PDF-')
    if start < 0:
        if data[:16].startswith(b'%!PS-Adobe') or b'%%Creator: Adobe Illustrator' in data[:4096]:
            raise AiError('Este .ai está no formato antigo (PostScript) ou foi salvo sem a parte de PDF. No Illustrator, salve de novo com «Criar arquivo compatível com PDF» '
                          'ou exporte como SVG ou PDF; o Arquivo Local não consegue desenhá-lo e nada foi simulado.')
        raise AiError('Este arquivo não parece um arquivo do Illustrator com parte de PDF.')
    return data[start:]


def _open(path):
    pdfium = _pdfium()
    data = read_ai_bytes(path)
    try:
        document = pdfium.PdfDocument(data)
    except pdfium.PdfiumError as error:
        text = str(error).lower()
        if 'password' in text:
            raise AiError('Este .ai está protegido por senha; o Arquivo Local não abre arquivos protegidos.') from error
        raise AiError('A parte de PDF deste .ai não pôde ser lida (arquivo danificado ou fora do padrão).') from error
    return document


def _page_info(document):
    try:
        pages = len(document)
    except Exception as error:
        raise AiError('A parte de PDF deste .ai não pôde ser lida.') from error
    if pages < 1:
        raise AiError('Este .ai não tem nenhuma página para desenhar.')
    page = document[0]
    width, height = page.get_size()
    if not (0 < width <= MAX_POINTS and 0 < height <= MAX_POINTS):
        page.close()
        raise AiError('O tamanho da página deste .ai é inválido ou grande demais.')
    return page, pages, (float(width), float(height))


def _is_stub(page):
    try:
        textpage = page.get_textpage()
        try:
            return STUB_TEXT in textpage.get_text_range().lower()
        finally:
            textpage.close()
    except Exception:
        return False


def describe_ai(path, width=None):
    """Resumo para o relatório de perdas e a interface, sem desenhar a imagem: tamanho, páginas e desenhista."""
    document = _open(path)
    try:
        page, pages, declared = _page_info(document)
        try:
            if _is_stub(page):
                raise AiError('Este .ai foi salvo sem a parte de PDF (só há uma página de aviso). No Illustrator, salve de novo com «Criar arquivo compatível com PDF».')
        finally:
            page.close()
        try:
            w, h, reduced = vector.target_size(declared, width)
        except vector.VectorError as error:
            raise AiError(str(error)) from error
        return {'kind': 'ai', 'declared': declared, 'size': (w, h), 'reduced': reduced, 'pages': pages, 'dropped': {}, 'engine': (LABEL, True)}
    finally:
        document.close()


def rasterize_ai(path, width=None):
    """.ai → imagem RGBA do Pillow, com fundo transparente. `width` em px (opcional) escolhe o tamanho; sem ele vale o tamanho da página."""
    from PIL import Image
    pdfium = _pdfium()
    document = _open(path)
    try:
        page, _pages, declared = _page_info(document)
        try:
            if _is_stub(page):
                raise AiError('Este .ai foi salvo sem a parte de PDF (só há uma página de aviso). No Illustrator, salve de novo com «Criar arquivo compatível com PDF».')
            try:
                w, h, _reduced = vector.target_size(declared, width)
            except vector.VectorError as error:
                raise AiError(str(error)) from error
            try:
                bitmap = page.render(scale=w / declared[0], fill_color=(255, 255, 255, 0), may_draw_forms=False, draw_annots=False, rev_byteorder=False)
                image = bitmap.to_pil()
            except (pdfium.PdfiumError, MemoryError, ValueError) as error:
                raise AiError('Não foi possível desenhar este .ai nesse tamanho (memória insuficiente ou arquivo fora do padrão).') from error
            if image.mode != 'RGBA':
                converted = image.convert('RGBA'); image.close(); image = converted
            if image.size != (w, h):
                resized = image.resize((w, h), Image.Resampling.LANCZOS); image.close(); image = resized
            return image
        finally:
            page.close()
    finally:
        document.close()
