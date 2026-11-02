"""Adaptador de rasterização de SVG com o resvg (pacote `resvg-py`, wheel com o motor em Rust; MIT/Apache-2.0).

Implementa a porta de `vector.py`: `render(svg_limpo, (largura, altura)) -> PIL.Image RGBA` com fundo transparente.
É o adaptador preferido: o resvg desenha o SVG estático completo (recortes `clipPath`, texto em caminho, `<svg>` aninhado,
`<symbol>`, máscaras, filtros) e, como não há um navegador por trás, não executa scripts nem busca nada na rede.
Se o pacote não estiver instalado, o `import` falha e `vector.py` cai no adaptador do Qt (`vector_qt.py`).
"""
import io

import resvg_py                                    # ImportError aqui = adaptador indisponível
from PIL import Image

from vector import VectorError

LABEL = 'resvg'
FULL_SUPPORT = True


def render(data, size):
    width, height = size
    try:
        png = resvg_py.svg_to_bytes(svg_string=data.decode('utf-8'), width=width, height=height)
    except Exception as error:                      # o resvg levanta erros próprios (SVG inválido, tamanho, falta de memória)
        raise VectorError('O SVG não pôde ser desenhado: ' + (str(error).strip()[:160] or type(error).__name__))
    try:
        with Image.open(io.BytesIO(bytes(png))) as decoded:
            decoded.load()
            result = decoded.convert('RGBA')
    except Exception:
        raise VectorError('O desenhista devolveu uma imagem inválida para este SVG.')
    if result.size != (width, height):               # arredondamento de 1 px na proporção: ajusta ao tamanho calculado
        result = result.resize((width, height), Image.Resampling.LANCZOS)
    return result
