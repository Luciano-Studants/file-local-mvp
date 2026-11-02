"""Adaptador de rasterização de SVG com o QtSvg do PySide6 (sem dependência nova): alternativa quando o resvg não está instalado.

Implementa a porta de `vector.py`: `render(svg_limpo, (largura, altura)) -> PIL.Image RGBA` com fundo transparente.
O Qt desenha SVG 1.1 estático e SVG Tiny 1.2: scripts, animações e recursos externos não rodam, e alguns recursos
(medido na 0.9.19: recortes `clipPath`, texto em caminho, `<svg>` aninhado e a escala de `<symbol>` em `<use>` não são desenhados) podem sair diferentes do navegador.
"""
import os

from PIL import Image

from vector import VectorError

LABEL = 'Qt SVG'
FULL_SUPPORT = False       # não desenha clipPath, textPath, <svg> aninhado nem escala <symbol> em <use>

_app = None


def _ensure_app():
    """Desenhar texto exige uma aplicação Qt (fontes). No worker não há janela: cria uma sem tela, na plataforma offscreen.
    Cria `QApplication` (e não só `QGuiApplication`) para que uma interface criada depois no mesmo processo, como nos testes, ainda funcione."""
    global _app
    from PySide6.QtCore import QCoreApplication
    from PySide6.QtWidgets import QApplication
    if QCoreApplication.instance() is not None: return
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    _app = QApplication(['arquivo-local-vetor'])


def render(data, size):
    from PySide6.QtCore import QByteArray, QRectF, Qt
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer
    width, height = size
    _ensure_app()
    renderer = QSvgRenderer(QByteArray(data))
    if not renderer.isValid():
        raise VectorError('O SVG não pôde ser interpretado pelo desenhista (arquivo inválido ou com recursos não suportados).')
    renderer.setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatio)         # como preserveAspectRatio="xMidYMid meet"
    image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    if image.isNull(): raise VectorError('Memória insuficiente para desenhar o SVG nesse tamanho.')
    image.fill(0)                                                           # fundo transparente
    painter = QPainter(image)
    painter.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform | QPainter.RenderHint.TextAntialiasing)
    renderer.render(painter, QRectF(0, 0, width, height))
    painter.end()
    straight = image.convertToFormat(QImage.Format.Format_RGBA8888)         # desfaz a pré-multiplicação do alfa
    result = Image.frombuffer('RGBA', (width, height), bytes(straight.constBits()), 'raw', 'RGBA', straight.bytesPerLine(), 1).copy()
    return result
