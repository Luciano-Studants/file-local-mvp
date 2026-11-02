"""Identidade visual do Arquivo Local: claro, discreto e com um único acento laranja.

Todas as cores ficam aqui para que painel, editor visual e radial usem a mesma paleta.
"""
from __future__ import annotations

BG = '#f3f4f4'
CARD = '#ffffff'
LINE = '#e1e4e4'
LINE_STRONG = '#cfd4d4'
TEXT = '#1d2224'
MUTED = '#6a7376'
DISABLED = '#a3abad'
ACCENT = '#ff5a00'
ACCENT_HOVER = '#e65000'
ACCENT_SOFT = '#fff0e8'
WHEEL_BASE = '#e8ebeb'
WHEEL_SEGMENT = '#f7f8f8'
STAGE = '#e9ecec'
# vidro quente da roda (referência: roda de pétalas cor de pêssego com fatia ativa laranja-avermelhada)
RIM = '#d8a56a'
RIM_EDGE = '#f6dcb8'
PETAL_TOP = '#fde6cb'
PETAL_BOTTOM = '#f8c898'
PETAL_HOT_TOP = '#ff6f22'
PETAL_HOT_BOTTOM = '#e04600'
HUB = '#e8924a'
HUB_EDGE = '#f2b87c'
PILL = '#fff3e4'
PETAL_TEXT = '#2a1a0e'
FONT_STACK = '"Segoe UI Variable Text","Segoe UI","Noto Sans","DejaVu Sans",sans-serif'


def panel_stylesheet() -> str:
    return f'''
    QWidget{{background:{BG};color:{TEXT};font-family:{FONT_STACK};font-size:13px}}
    QLabel{{background:transparent}}
    QLabel#Brand{{font-size:22px;font-weight:700;letter-spacing:0.3px}}
    QLabel#Muted{{color:{MUTED}}}
    QLabel#PageTitle{{font-size:26px;font-weight:600}}
    QLabel#Caption{{color:{MUTED};font-size:12px}}
    QLabel#KeyCap{{background:{CARD};border:1px solid {LINE_STRONG};border-bottom:3px solid {LINE_STRONG};border-radius:9px;padding:6px 16px;font-weight:600}}
    QLabel#FilePill{{background:{CARD};border:1px solid {LINE};border-radius:10px;padding:9px 12px}}
    QFrame#Card{{background:{CARD};border:1px solid {LINE};border-radius:16px}}
    QFrame#Card QLabel{{background:transparent}}
    QFrame#Footer{{background:{CARD};border:1px solid {LINE};border-radius:10px}}
    QFrame#Divider{{background:{LINE};border:0;max-width:1px;min-width:1px}}
    QPushButton{{background:{CARD};color:{TEXT};border:1px solid {LINE_STRONG};border-radius:9px;padding:8px 14px}}
    QPushButton:hover{{border-color:{ACCENT};color:{ACCENT_HOVER}}}
    QPushButton:focus{{border-color:{ACCENT}}}
    QPushButton:disabled{{color:{DISABLED};background:{BG};border-color:{LINE}}}
    QPushButton#Tab{{background:transparent;border:1px solid transparent;border-radius:12px;padding:8px 9px;color:{MUTED}}}
    QPushButton#Tab:hover{{background:{CARD};color:{TEXT}}}
    QPushButton#Tab:checked{{background:{CARD};border-color:{LINE_STRONG};color:{TEXT}}}
    QPushButton#Chip{{background:{BG};color:{MUTED};border:1px solid {LINE};border-radius:13px;padding:5px 12px;font-weight:600}}
    QPushButton#Chip:hover{{border-color:{ACCENT};color:{TEXT}}}
    QPushButton#Chip:checked{{background:{ACCENT};border-color:{ACCENT};color:#fff}}
    QPushButton#Chip:disabled{{color:{DISABLED}}}
    QSlider::groove:horizontal{{height:4px;background:{LINE_STRONG};border-radius:2px}}
    QSlider::sub-page:horizontal{{background:{ACCENT};border-radius:2px}}
    QSlider::handle:horizontal{{background:#fff;border:2px solid {ACCENT};width:12px;height:12px;margin:-6px 0;border-radius:8px}}
    QSlider::handle:horizontal:hover{{background:{ACCENT_SOFT}}}
    QLabel#SliderValue{{color:{MUTED};min-width:54px}}
    QPushButton#Swatch{{border:2px solid transparent;border-radius:9px;min-width:26px;max-width:26px;min-height:26px;max-height:26px;padding:0}}
    QPushButton#Swatch:hover{{border-color:{LINE_STRONG}}}
    QPushButton#Swatch:checked{{border-color:{ACCENT}}}
    QPushButton#Primary{{background:{ACCENT};color:#fff;border:0;font-weight:700;padding:11px 18px}}
    QPushButton#Primary:hover{{background:{ACCENT_HOVER};color:#fff}}
    QPushButton#Primary:disabled{{background:{LINE_STRONG};color:#fff}}
    QPushButton#CategoryCard,QPushButton#ToolCardButton{{background:{CARD};border:1px solid {LINE};border-radius:14px;text-align:left;padding:14px;color:{TEXT}}}
    QPushButton#CategoryCard:hover,QPushButton#ToolCardButton:hover{{border-color:{ACCENT};color:{TEXT}}}
    QPushButton#CategoryCard{{font-size:14px;min-height:94px}}
    QPushButton#CategoryCard:disabled,QPushButton#ToolCardButton:disabled{{color:{DISABLED};background:{BG};border-color:{LINE}}}
    QLineEdit,QSpinBox,QComboBox{{background:{CARD};border:1px solid {LINE_STRONG};border-radius:8px;padding:7px 8px;selection-background-color:{ACCENT}}}
    QSpinBox::up-button,QSpinBox::down-button{{width:0;border:0}}
    QLineEdit:focus,QSpinBox:focus,QComboBox:focus{{border-color:{ACCENT}}}
    QLineEdit:disabled,QSpinBox:disabled,QComboBox:disabled{{color:{DISABLED};background:{BG}}}
    QScrollArea{{border:0;background:transparent}}
    QScrollArea>QWidget>QWidget{{background:transparent}}
    QProgressBar{{border:0;background:{LINE};border-radius:3px;max-height:6px}}
    QProgressBar::chunk{{background:{ACCENT};border-radius:3px}}
    QScrollBar:vertical{{background:transparent;width:8px;margin:2px 1px}}
    QScrollBar::handle:vertical{{background:{LINE_STRONG};min-height:26px;border-radius:3px}}
    QScrollBar::handle:vertical:hover{{background:{ACCENT}}}
    QScrollBar:horizontal{{background:transparent;height:8px;margin:1px 2px}}
    QScrollBar::handle:horizontal{{background:{LINE_STRONG};min-width:26px;border-radius:3px}}
    QScrollBar::handle:horizontal:hover{{background:{ACCENT}}}
    QScrollBar::add-line,QScrollBar::sub-line{{height:0;width:0}}
    QScrollBar::add-page,QScrollBar::sub-page{{background:transparent}}
    QListWidget{{background:{CARD};border:1px solid {LINE};border-radius:10px;padding:6px;outline:0}}
    QListWidget::item{{padding:7px 10px;border-radius:7px;color:{TEXT}}}
    QListWidget::item:hover{{background:{BG}}}
    QListWidget::item:selected{{background:{ACCENT_SOFT};color:{TEXT};border:1px solid {ACCENT}}}
    QToolTip{{background:{TEXT};color:#fff;border:0;padding:5px 8px}}
    '''


def dialog_stylesheet() -> str:
    return f'''
    QDialog{{background:{BG};color:{TEXT};font-family:{FONT_STACK}}}
    QLabel{{font-size:13px;color:{TEXT};background:transparent}}
    QLabel#CropTitle{{font-size:16px;font-weight:600}}
    QLabel#CropHint{{color:{MUTED}}}
    QPushButton{{background:{CARD};color:{TEXT};border:1px solid {LINE_STRONG};border-radius:8px;padding:9px 16px}}
    QPushButton:hover{{border-color:{ACCENT}}}
    QPushButton:disabled{{color:{DISABLED};background:{BG};border-color:{LINE}}}
    QPushButton#Primary{{background:{ACCENT};color:#fff;border:0;font-weight:700;padding:10px 20px}}
    QPushButton#Primary:hover{{background:{ACCENT_HOVER};color:#fff}}
    QPushButton#Primary:disabled{{background:{LINE_STRONG};color:#fff}}
    QPushButton#Chip{{background:{BG};color:{MUTED};border:1px solid {LINE};border-radius:13px;padding:5px 12px;font-weight:600}}
    QPushButton#Chip:hover{{border-color:{ACCENT};color:{TEXT}}}
    QPushButton#Chip:checked{{background:{ACCENT};border-color:{ACCENT};color:#fff}}
    '''
