"""Painel do Arquivo Local: categorias no topo, rodas de ferramentas e prévia visual por ferramenta."""
from __future__ import annotations

from collections import OrderedDict
from pathlib import Path

from PySide6.QtCore import QDir, QRectF, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QIcon, QImage, QPixmap, QTransform
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QCheckBox, QColorDialog, QComboBox, QFileDialog, QFormLayout, QFrame, QGridLayout, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMessageBox,
    QPushButton, QProgressBar, QScrollArea, QSpinBox, QStackedWidget,
    QVBoxLayout, QWidget,
)

import re
import theme
from capabilities import describe_capabilities, probe_capabilities
import bgremove
import ocr
import tool_registry
from engine import OCR_TARGETS, ONEPDF, PDF_MAX_MARGIN_MM, PDF_MAX_PAGES, PDF_CLEAN, PDF_COMPRESS, PDF_PROTECT, PDF_UNPROTECT, PASSWORD_MIN, PDF_STAMP, PDF_REDACT, PDF_FORM, PDF_OCR_MAX_PAGES, PDF_OCR_PDF, PDF_OCR_TARGETS, PDF_OCR_TEXT, PDF_PAGES, onepdf_options_from, pdf_page_pixels
import engine as engine_module
from engine import BG_DEFAULT_MODEL, BG_TARGET, bg_options_from, VECTOR_INPUTS, VECTOR_MAX_WIDTH, set_vector_width, ConversionError, IMAGE_INPUTS, IMAGE_OUTPUTS, OUTPUT_FORMATS, RENAMEABLE_TARGETS, TOOL_SUFFIX, batch_rename_options, rename_options_from, rename_stem, RESIZE_MAX_SIDE, WATERMARK_POSITIONS, resize_target_size, SHAPE_KINDS, SHAPE_MAX_ITEMS, levels_image, levels_options_from, levels_resolve, luminance_histogram, shape_items_from, shapes_image, sharpen_image, sharpen_options_from, watermark_image, watermark_options_from
from engine import BACKDROPS, BACKDROP_RATIOS, COLLAGE_MAX, COLLAGE_MIN, OPERATIONS, VERSION, backdrop_layout, collage_layout, adjust_image, inspect_metadata, jpeg_bytes, open_image, source_file
from icons import category_icon
from radial_menu import RadialAction, RadialWheel, audio_tool_actions, image_tool_actions, pdf_tool_actions
from widgets import ChipGroup, HistogramView, SliderRow, swatch_pixmap
import pdfinfo
import pdfform
import pdfredact
import pdfstamp
from pdf_stage import PdfStage
import audioconvert
from audio_stage import AudioStage
import mediatools
from page_organizer import PageOrganizer
from visual_tools import (
    ASPECTS, AnnotateView, CanvasView, CropEditor, CropView, ImageStageView, backdrop_preview_pixmap, collage_layout_pixmap, pdf_pages_pixmap,
    pixmap_from_image_path, selection_to_image_box,
)

# chave -> (rótulo, descrição, ferramentas disponíveis)
CATEGORIES = OrderedDict([
    ('images', ('Imagens', 'Edição visual e formatos', True)),
    ('video', ('Vídeo', 'Corte, conversão e ajustes', False)),
    ('audio', ('Áudio', 'Informações e conversão de formato', True)),
    ('pdf', ('PDF', 'Ver páginas, extrair texto, separar e unir', True)),
    ('documents', ('Documentos', 'Formatos de texto', False)),
    ('slides', ('Slides', 'Apresentações', False)),
    ('spreadsheets', ('Planilhas', 'Tabelas e dados', False)),
    ('epub', ('EPUB', 'Livros digitais', False)),
    ('subtitles', ('Legendas', 'SRT, VTT e texto', False)),
    ('archives', ('ZIP', 'Compactação e extração', False)),
])

AUDIO_INFO = tool_registry.AUDIO_INFO      # ferramenta de leitura: não gera arquivo (0.9.43)
AUDIO_CONVERT = tool_registry.AUDIO_CONVERT
READONLY_TOOLS = frozenset({AUDIO_INFO})
AUDIO_SUFFIXES = {'.mp3', '.m4a', '.aac', '.wav', '.flac', '.ogg', '.oga', '.opus', '.aiff', '.aif', '.wma'}

PLANNED_TOOLS = {
    'video': [('Cortar trecho', 'Trim com preview'), ('Converter vídeo', 'Formatos e codecs locais'), ('Extrair quadro', 'Snapshot visual'), ('Comprimir vídeo', 'Qualidade e tamanho')],
    'audio': [('Metadados', 'Ver e limpar etiquetas e capa'), ('Canais', 'Mono, estéreo e downmix'), ('Cortar áudio', 'Seleção visual de trecho'), ('Normalizar volume', 'Métricas antes/depois'), ('Comprimir áudio', 'Bitrate e tamanho')],
    'documents': [('Texto para PDF', 'TXT/Markdown'), ('DOCX', 'Importação/exportação controlada'), ('Visualizar documento', 'Prévia local')],
    'slides': [('PPTX ↔ PDF', 'Avisos de fidelidade'), ('Exportar slides', 'Imagens ou PDF')],
    'spreadsheets': [('CSV / TSV', 'Separador e codificação'), ('XLSX / ODS', 'Conversão local'), ('Planilha para PDF', 'Prévia antes de exportar')],
    'epub': [('EPUB ↔ texto', 'Conteúdo sem DRM'), ('EPUB para PDF', 'Reflow e limites de layout')],
    'subtitles': [('SRT ↔ VTT', 'Conversão de legendas'), ('Ajustar tempos', 'Revisão de sincronização')],
    'archives': [('Criar ZIP', 'Compactação segura'), ('Extrair arquivos', 'Bloqueado até o reforço contra traversal e links')],
}

# alvo do motor, rótulo curto (usado na roda e nos cartões), descrição
TOOLS = {
    'images': [
        ('JPEG', 'JPEG', 'Converter para JPEG'), ('PNG', 'PNG', 'Converter para PNG'),
        ('WEBP', 'WebP', 'Converter para WebP'), ('TIFF', 'TIFF', 'Converter para TIFF'),
        ('BMP', 'BMP', 'Converter para BMP'), ('Image → PDF', 'PDF', 'Salvar a imagem em PDF'),
        *[(spec.target, spec.label, spec.tip) for spec in tool_registry.IMAGE_TOOLS],
    ],
    'audio': [
        (AUDIO_INFO, 'Informações', 'Duração, codec, taxa, canais, etiquetas e capa do áudio'),
        (AUDIO_CONVERT, 'Converter', 'Converter para MP3, M4A, FLAC, OGG, Opus, WAV ou AIFF'),
    ],
    'pdf': [
        ('PDF → Text', 'Extrair texto', 'Exportar o texto das páginas'),
        ('Extract PDF Images', 'Imagens do PDF', 'Extrair as imagens embutidas'),
        ('PDF OCR → PDF', 'OCR → PDF pesquisável', 'Reconhecer um PDF digitalizado'),
        ('PDF OCR → Text', 'OCR → texto', 'Reconhecer o texto de um PDF digitalizado'),
        ('PDF → Images', 'Páginas em imagens', 'Salvar cada página como imagem'),
        ('Split PDF', 'Dividir / extrair', 'Separar em partes ou extrair páginas'),
        ('Organize PDF', 'Organizar páginas', 'Girar, excluir, duplicar e reordenar'),
        ('Merge PDFs', 'Unir PDFs', 'Combinar dois ou mais arquivos'),
        ('Protect PDF', 'Proteger com senha', 'Criptografar com senha (AES-256)'),
        ('Unprotect PDF', 'Remover senha', 'Gerar uma cópia sem senha'),
        ('Fill PDF', 'Preencher e assinar', 'Campos do formulário e imagem de assinatura'),
        ('Redact PDF', 'Tarjar conteúdo', 'Cobrir áreas, termos e dados pessoais'),
        ('Stamp PDF', 'Numerar / carimbar', 'Números de página, texto e marca d\'água'),
        ('Compress PDF', 'Comprimir', 'Reduzir o tamanho do arquivo'),
        ('Clean PDF', 'Metadados', 'Ver metadados e gerar uma cópia limpa'),
    ],
}

# colunas de rodas por categoria: (tecla, subtítulo, alvos)
WHEEL_COLUMNS = {
    'images': [
        ('Shift', 'Converter formatos', ['JPEG', 'PNG', 'WEBP', 'TIFF', 'BMP', 'Image → PDF']),
        ('Shift + F9', 'Ferramentas do arquivo', tool_registry.wheel_layout()),
    ],
    'pdf': [
        ('Shift', 'Operações de PDF', tool_registry.pdf_wheel_layout()),
    ],
    'audio': [
        ('Shift', 'Operações de áudio', tool_registry.audio_wheel_layout()),
    ],
}

BASIC_CONVERSIONS = {'JPEG', 'PNG', 'WEBP', 'TIFF', 'BMP', 'Image → PDF'}
QUALITY_PRESETS = [('Leve · 95', 95), ('Equilibrado · 88', 88), ('Pequeno · 70', 70), ('Mínimo · 50', 50), ('Personalizado', None)]
ESTIMATE_MAX_PIXELS = 12_000_000
IMAGE_TARGETS = {'JPEG', 'PNG', 'WEBP', 'TIFF', 'BMP', 'Image → PDF', *tool_registry.TARGETS}
IMAGE_SUFFIXES = {'.png', '.jpg', '.jpeg', '.webp', '.tif', '.tiff', '.bmp', '.avif', '.svg', '.svgz', '.ai', '.emf', '.wmf', '.heic', '.heif', '.hif'}
LABELS = {
    'JPEG': 'Imagem → JPEG', 'PNG': 'Imagem → PNG', 'WEBP': 'Imagem → WebP', 'TIFF': 'Imagem → TIFF', 'BMP': 'Imagem → BMP',
    'Image → PDF': 'Imagem → PDF', **{spec.target: spec.panel_title for spec in tool_registry.IMAGE_TOOLS},
    'PDF → Text': 'Extrair texto do PDF', 'Extract PDF Images': 'Imagens embutidas no PDF', 'PDF → Images': 'Páginas do PDF em imagens',
    'Protect PDF': 'Proteger o PDF com senha', 'Unprotect PDF': 'Remover a senha do PDF', 'Stamp PDF': 'Numerar e carimbar o PDF', 'Redact PDF': 'Tarjar conteúdo do PDF', 'Fill PDF': 'Preencher e assinar o PDF', 'Compress PDF': 'Comprimir PDF', 'Clean PDF': 'Metadados e cópia limpa do PDF', 'PDF OCR → PDF': 'PDF digitalizado → PDF pesquisável (OCR)', 'PDF OCR → Text': 'PDF digitalizado → texto (OCR)',
    AUDIO_INFO: 'Informações do áudio', AUDIO_CONVERT: 'Converter áudio',
    'Split PDF': 'Dividir e extrair páginas do PDF', 'Organize PDF': 'Organizar páginas do PDF', 'Merge PDFs': 'Unir PDFs',
}
FUTURE_SUFFIXES = {
    '.mp4': 'video', '.mkv': 'video', '.mov': 'video', '.mp3': 'audio', '.wav': 'audio', '.flac': 'audio',
    '.docx': 'documents', '.odt': 'documents', '.txt': 'documents', '.pptx': 'slides', '.xlsx': 'spreadsheets',
    '.ods': 'spreadsheets', '.epub': 'epub', '.srt': 'subtitles', '.vtt': 'subtitles', '.zip': 'archives',
}
# stage: índices da pilha de prévia
STAGE_MESSAGE, STAGE_CROP, STAGE_ANNOTATE, STAGE_CANVAS, STAGE_STATIC, STAGE_FILES, STAGE_PDF, STAGE_ORGANIZE, STAGE_REDACT, STAGE_FORM, STAGE_AUDIO = range(11)
ORDERED_TARGETS = ('Collage → PNG', 'Images → One PDF')      # ferramentas que juntam várias imagens na ordem da lista


class ColorField(QLineEdit):
    """Campo #RRGGBB com amostra de cor que abre o seletor do sistema."""

    def __init__(self, value: str, parent=None):
        super().__init__(value, parent)
        self.setMaxLength(7)
        self.swatch_action = self.addAction(QIcon(), QLineEdit.ActionPosition.TrailingPosition)
        self.swatch_action.setToolTip('Escolher cor')
        self.swatch_action.triggered.connect(self.pick_color)
        self.textChanged.connect(self._refresh_swatch)
        self._refresh_swatch(value)

    def _refresh_swatch(self, text: str):
        color = QColor(text)
        pixmap = QPixmap(16, 16)
        pixmap.fill(color if color.isValid() and len(text) == 7 else QColor(theme.LINE))
        self.swatch_action.setIcon(QIcon(pixmap))

    def pick_color(self):
        chosen = QColorDialog.getColor(QColor(self.text()) if QColor(self.text()).isValid() else QColor('#ffffff'), self, 'Escolher cor')
        if chosen.isValid():
            self.setText(chosen.name().upper())


class FeaturePanel(QMainWindow):
    """Interface por categorias; os controles aparecem somente para a ferramenta escolhida."""

    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.files: list[str] = []
        self.last_output_dir = ''
        self.allow_close = False
        self.active_category = 'images'
        self.selected_tool = None
        self.crop_image_size = (0, 0)
        self.estimate = None
        self._pixmap_cache: tuple[str, QPixmap, tuple[int, int]] | None = None
        self._syncing = False
        self.setWindowTitle('Arquivo Local')
        self.resize(1040, 740)
        self.setMinimumSize(780, 580)
        self.setAcceptDrops(True)

        shell = QWidget(self)
        self.setCentralWidget(shell)
        outer = QVBoxLayout(shell)
        outer.setContentsMargins(24, 18, 24, 16)
        outer.setSpacing(12)

        header = QHBoxLayout()
        header.setSpacing(14)
        brand = QVBoxLayout()
        brand.setSpacing(0)
        title = QLabel(f'arquivo<span style="color:{theme.ACCENT}">.</span>local')
        title.setTextFormat(Qt.TextFormat.RichText)
        title.setObjectName('Brand')
        subtitle = QLabel('Ferramentas locais para seus arquivos')
        subtitle.setObjectName('Muted')
        brand.addWidget(title)
        brand.addWidget(subtitle)
        header.addLayout(brand, 1)
        self.files_label = QLabel('Nenhum arquivo selecionado')
        self.files_label.setObjectName('FilePill')
        self.files_label.setWordWrap(True)
        header.addWidget(self.files_label, 2)
        self.choose_button = QPushButton('Abrir arquivo')
        self.choose_button.clicked.connect(self.choose_files)
        header.addWidget(self.choose_button)
        self.settings_button = QPushButton('Atalhos')
        self.settings_button.setToolTip('Atalho global, botão do meio e menu de contexto do Explorer')
        header.addWidget(self.settings_button)
        outer.addLayout(header)

        self.category_scroll = QScrollArea()
        self.category_scroll.setWidgetResizable(True)
        self.category_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.category_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.category_scroll.setFixedHeight(58)
        category_row = QWidget()
        self.category_layout = QHBoxLayout(category_row)
        self.category_layout.setContentsMargins(0, 0, 0, 4)
        self.category_layout.setSpacing(2)
        self.category_buttons = {}
        for key, (label, _desc, available) in CATEGORIES.items():
            button = QPushButton(label)
            button.setObjectName('Tab')
            button.setCheckable(True)
            button.setIcon(category_icon(key, theme.MUTED, theme.ACCENT))
            button.setIconSize(QSize(18, 18))
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setToolTip('Ferramentas disponíveis' if available else 'Em desenvolvimento: veja o que está planejado; ainda não executa operações')
            button.clicked.connect(lambda checked=False, category=key: self.select_category(category))
            self.category_layout.addWidget(button)
            self.category_buttons[key] = button
        self.category_layout.addStretch(1)
        self.category_scroll.setWidget(category_row)
        outer.addWidget(self.category_scroll)

        self.pages = QStackedWidget()
        outer.addWidget(self.pages, 1)
        self.home_page = QWidget()
        self.category_page = QWidget()
        self.tool_page = QWidget()
        self.pages.addWidget(self.home_page)
        self.pages.addWidget(self.category_page)
        self.pages.addWidget(self.tool_page)
        self._build_home()
        self._build_category_page()
        self._build_tool_page()

        self.footer = QFrame()
        self.footer.setObjectName('Footer')
        footer_layout = QHBoxLayout(self.footer)
        footer_layout.setContentsMargins(12, 8, 12, 8)
        self.status = QLabel('Processamento local • originais preservados • sem sobrescrita silenciosa')
        self.status.setWordWrap(True)
        self.status.setObjectName('Muted')
        footer_layout.addWidget(self.status, 1)
        self.progress = QProgressBar()
        self.progress.setFixedWidth(90)
        self.progress.setTextVisible(False)
        footer_layout.addWidget(self.progress)
        self.cancel_button = QPushButton('Cancelar')
        self.cancel_button.clicked.connect(self.controller.cancel_current)
        footer_layout.addWidget(self.cancel_button)
        outer.addWidget(self.footer)

        # Modelos de compatibilidade ocultos: mantidos para testes e tecnologias assistivas.
        self.image_list = QListWidget(self)
        self.pdf_list = QListWidget(self)
        for target, label, _description in TOOLS['images']:
            item = QListWidgetItem(label); item.setData(Qt.ItemDataRole.UserRole, target); self.image_list.addItem(item)
        for target, label, _description in TOOLS['pdf']:
            item = QListWidgetItem(label); item.setData(Qt.ItemDataRole.UserRole, target); self.pdf_list.addItem(item)
        self.image_list.hide(); self.pdf_list.hide()
        self.operation = QComboBox(self)
        for target in OPERATIONS:
            self.operation.addItem(LABELS.get(target, target), target)
        self.operation.currentIndexChanged.connect(self._compat_operation_changed)
        self.operation.hide()
        self._build_compatibility_controls()

        self.setStyleSheet(theme.panel_stylesheet())
        self.controller.job_finished.connect(self.on_job_finished)
        self.controller.queue_changed.connect(self.refresh_queue)
        self.refresh_capabilities_view()
        self.refresh_queue()
        self.pages.setCurrentWidget(self.home_page)

    # ------------------------------------------------------------------
    # construção das páginas
    # ------------------------------------------------------------------
    def _build_home(self):
        layout = QVBoxLayout(self.home_page)
        layout.setContentsMargins(4, 26, 4, 4)
        layout.setSpacing(14)
        layout.addStretch(1)
        intro = QLabel('O que você quer fazer hoje?')
        intro.setObjectName('PageTitle')
        intro.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(intro)
        desc = QLabel('Escolha uma categoria na barra acima. Imagens e PDF já funcionam; as demais aparecem para mostrar o que vem a seguir e ficam desativadas até serem implementadas e validadas.')
        desc.setObjectName('Muted'); desc.setWordWrap(True); desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(desc)
        cards = QHBoxLayout(); cards.setSpacing(14)
        for key, label, summary in (('images', 'Imagens', 'Converter, recortar, anotar, adicionar fundo e comprimir'),
                                    ('pdf', 'PDF', 'Ver as páginas, extrair texto, separar e unir arquivos')):
            card = QPushButton(f'{label}\n{summary}')
            card.setObjectName('CategoryCard'); card.setMinimumHeight(104); card.setCursor(Qt.CursorShape.PointingHandCursor)
            card.clicked.connect(lambda checked=False, category=key: self.select_category(category))
            cards.addWidget(card)
        layout.addLayout(cards)
        tip = QLabel('Dica: selecione um arquivo no Explorer e segure Shift para converter, ou use Shift + F9 para as ferramentas do arquivo.')
        tip.setObjectName('Caption'); tip.setWordWrap(True); tip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(tip)
        layout.addStretch(1)

    def _build_category_page(self):
        layout = QVBoxLayout(self.category_page)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(10)
        top = QHBoxLayout()
        self.category_title = QLabel('Imagens'); self.category_title.setObjectName('PageTitle')
        top.addWidget(self.category_title, 1)
        self.category_help = QLabel('Escolha uma ferramenta para continuar.'); self.category_help.setObjectName('Muted')
        top.addWidget(self.category_help)
        self.category_back = QPushButton('Todas as categorias')
        self.category_back.clicked.connect(lambda: self.pages.setCurrentWidget(self.home_page))
        top.addWidget(self.category_back)
        layout.addLayout(top)
        self.category_body = QStackedWidget()
        self.wheels_scroll = QScrollArea(); self.wheels_scroll.setWidgetResizable(True)
        self.wheels_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.wheels_host = QWidget(); self.wheels_layout = QHBoxLayout(self.wheels_host)
        self.wheels_layout.setContentsMargins(0, 0, 0, 0); self.wheels_layout.setSpacing(0)
        self.wheels_scroll.setWidget(self.wheels_host)
        self.category_body.addWidget(self.wheels_scroll)
        self.tool_grid_widget = QWidget()
        self.tool_grid = QGridLayout(self.tool_grid_widget)
        self.tool_grid.setContentsMargins(0, 0, 0, 0); self.tool_grid.setSpacing(10)
        self.tools_scroll = QScrollArea(); self.tools_scroll.setWidgetResizable(True)
        self.tools_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.tools_scroll.setWidget(self.tool_grid_widget)
        self.category_body.addWidget(self.tools_scroll)
        layout.addWidget(self.category_body, 1)
        self.queue_title = QLabel('Na fila'); self.queue_title.setObjectName('Caption')
        layout.addWidget(self.queue_title)
        self.queue_view = QListWidget(); self.queue_view.setMaximumHeight(70)
        layout.addWidget(self.queue_view)

    def _build_tool_page(self):
        outer = QVBoxLayout(self.tool_page)
        outer.setContentsMargins(4, 4, 4, 4)
        outer.setSpacing(10)
        top = QHBoxLayout()
        self.back_button = QPushButton('‹ Voltar')
        self.back_button.clicked.connect(lambda: self.select_category(self.active_category))
        top.addWidget(self.back_button)
        self.tool_title = QLabel('Ferramenta'); self.tool_title.setObjectName('PageTitle')
        top.addWidget(self.tool_title, 1)
        self.preview_button = QPushButton('Ampliar editor…')
        self.preview_button.clicked.connect(self.open_visual_crop)
        top.addWidget(self.preview_button)
        outer.addLayout(top)
        self.tool_description = QLabel(''); self.tool_description.setObjectName('Muted'); self.tool_description.setWordWrap(True)
        outer.addWidget(self.tool_description)
        body = QHBoxLayout(); body.setSpacing(16); outer.addLayout(body, 1)

        self.preview_frame = QFrame(); self.preview_frame.setObjectName('Card'); self.preview_frame.setMinimumWidth(320)
        preview_layout = QVBoxLayout(self.preview_frame); preview_layout.setContentsMargins(10, 10, 10, 10)
        self.stage = QStackedWidget()
        self.preview_image = QLabel('Abra um arquivo para ver a prévia.')
        self.preview_image.setAlignment(Qt.AlignmentFlag.AlignCenter); self.preview_image.setWordWrap(True); self.preview_image.setObjectName('Muted')
        blank = QPixmap(1, 1); blank.fill(Qt.GlobalColor.transparent)
        self.crop_preview = CropView(blank)
        self.annotate_preview = AnnotateView(blank)
        self.canvas_preview = CanvasView(blank)
        self.static_preview = ImageStageView(blank)
        self.file_preview = QListWidget()
        self.pdf_stage = PdfStage()                  # PDFs: resumo, página grande e miniaturas (0.9.29); a leitura roda no worker
        self.redact_stage = PdfStage(selectable=True)      # Tarjar (0.9.40): a página aceita seleção de áreas
        self.form_stage = PdfStage(selectable=True)        # Preencher e assinar (0.9.41): a página aceita a área da assinatura
        self.form_stage.page_view.committed_fill = False
        self.audio_stage = AudioStage()              # Áudio (0.9.43): informações do arquivo; a leitura roda no worker
        self.organizer = PageOrganizer()             # Organizar páginas (0.9.33): miniaturas que se arrastam, giram, somem e se duplicam
        for widget in (self.preview_image, self.crop_preview, self.annotate_preview, self.canvas_preview, self.static_preview, self.file_preview, self.pdf_stage, self.organizer, self.redact_stage, self.form_stage, self.audio_stage):
            self.stage.addWidget(widget)
        preview_layout.addWidget(self.stage, 1)
        body.addWidget(self.preview_frame, 3)

        settings = QWidget(); settings.setMinimumWidth(300); settings.setMaximumWidth(380)
        settings_layout = QVBoxLayout(settings); settings_layout.setContentsMargins(0, 0, 8, 0); settings_layout.setSpacing(12)
        self.settings_heading = QLabel('Ajustes'); self.settings_heading.setStyleSheet('font-weight:600;font-size:15px')
        settings_layout.addWidget(self.settings_heading)
        self.tool_hint = QLabel(''); self.tool_hint.setObjectName('Muted'); self.tool_hint.setWordWrap(True)
        self.settings_form = QFormLayout()
        self.settings_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.settings_form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        self.settings_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)      # campo largo vai para baixo do rótulo em vez de ser cortado (0.9.26)
        self.settings_form.setVerticalSpacing(10)
        self.width = QSpinBox(); self.width.setRange(0, 10000); self.width.setSpecialValueText('Original'); self.width.setSuffix(' px')
        self.rotation = ChipGroup(['Sem rotação', '90° horário', '180°', '270° horário'], per_row=2)
        self.quality = QSpinBox(); self.quality.setRange(1, 100); self.quality.setValue(88); self.quality.setSuffix(' / 100')
        self.compress_preset = ChipGroup([label for label, _quality in QUALITY_PRESETS], per_row=3)
        self.compress_preset.setCurrentIndex(1)
        self._pil_image = None
        self._estimate_timer = QTimer(self); self._estimate_timer.setSingleShot(True); self._estimate_timer.setInterval(220)
        self._estimate_timer.timeout.connect(self._run_estimate)
        self.crop_x = QSpinBox(); self.crop_y = QSpinBox(); self.crop_width = QSpinBox(); self.crop_height = QSpinBox()
        for spin in (self.crop_x, self.crop_y, self.crop_width, self.crop_height):
            spin.setRange(0, 10000); spin.setParent(settings); spin.hide()
        self.canvas_width = QSpinBox(); self.canvas_width.setRange(0, 10000); self.canvas_width.setSuffix(' px')
        self.canvas_height = QSpinBox(); self.canvas_height.setRange(0, 10000); self.canvas_height.setSuffix(' px')
        self.background = ColorField('#FFFFFF')
        self.backdrop_style = 'sunset'
        self.backdrop_swatches = QWidget(); swatch_layout = QGridLayout(self.backdrop_swatches)
        swatch_layout.setContentsMargins(0, 0, 0, 0); swatch_layout.setSpacing(6)
        self.backdrop_group = QButtonGroup(self.backdrop_swatches); self.backdrop_group.setExclusive(True)
        self.backdrop_buttons = {}
        self.backdrop_color = ColorField('#FFFFFF')
        for position, (style_id, (label, kind, colors)) in enumerate([*BACKDROPS.items(), ('custom', ('Cor personalizada', 'solid', ('#FFFFFF',)))]):
            button = QPushButton(); button.setObjectName('Swatch'); button.setCheckable(True); button.setToolTip(label)
            button.setIcon(QIcon(swatch_pixmap(kind, colors, 22, plus=style_id == 'custom'))); button.setIconSize(QSize(22, 22))
            button.clicked.connect(lambda _checked=False, s=style_id: self._backdrop_style_picked(s))
            self.backdrop_group.addButton(button); swatch_layout.addWidget(button, position // 6, position % 6)
            self.backdrop_buttons[style_id] = button
        self.backdrop_buttons['sunset'].setChecked(True)
        self.backdrop_padding = SliderRow(0, 600, 80); self.backdrop_radius = SliderRow(0, 300, 24); self.backdrop_shadow = SliderRow(0, 100, 30, suffix='')
        self.backdrop_ratio = ChipGroup(['Auto', '1:1', '16:9', '4:5'], per_row=4)
        self.collage_list = QListWidget(); self.collage_list.setMaximumHeight(190); self.collage_list.setSpacing(2); self.collage_list.setAlternatingRowColors(False)
        self.merge_ranges: dict[str, str] = {}          # «Unir PDFs»: intervalo de páginas de cada arquivo (por caminho)
        self.merge_pages = QLineEdit(); self.merge_pages.setMaxLength(200); self.merge_pages.setPlaceholderText('Todas as páginas (ou, por exemplo, 1-3,7)')
        self.merge_pages.setToolTip('Páginas do arquivo selecionado na lista que entram no PDF unido. Vazio = todas; «5-» vai até o fim.')
        self.merge_info = QLabel(''); self.merge_info.setWordWrap(True); self.merge_info.setTextFormat(Qt.TextFormat.PlainText)
        self.collage_buttons = QWidget(); collage_row = QGridLayout(self.collage_buttons); collage_row.setContentsMargins(0, 0, 0, 0); collage_row.setSpacing(6)
        self.collage_up_button = QPushButton('Subir'); self.collage_down_button = QPushButton('Descer'); self.collage_remove_button = QPushButton('Tirar')
        collage_row.addWidget(self.collage_up_button, 0, 0); collage_row.addWidget(self.collage_down_button, 0, 1); collage_row.addWidget(self.collage_remove_button, 1, 0, 1, 2)
        self.collage_up_button.clicked.connect(lambda: self.move_collage_item(-1))
        self.collage_down_button.clicked.connect(lambda: self.move_collage_item(1))
        self.collage_remove_button.clicked.connect(self.remove_collage_item)
        self.collage_list.currentRowChanged.connect(lambda _row: self._update_collage_buttons())
        self.collage_list.currentRowChanged.connect(self._merge_row_changed)
        self.merge_pages.textChanged.connect(self._merge_range_edited)
        self.collage_list.setDragDropMode(QListWidget.DragDropMode.InternalMove); self.collage_list.setDefaultDropAction(Qt.DropAction.MoveAction)      # arrastar para reordenar (0.9.26)
        self.collage_list.setToolTip('Arraste os itens para mudar a ordem, ou use Subir e Descer.')
        self.collage_list.model().rowsMoved.connect(self._collage_rows_moved)
        self._collage_thumbs = {}
        self.pdf_ocr = ChipGroup(['Não'] + list(ocr.LANGS.values()), per_row=1)
        self.pdf_page = ChipGroup([label for label, _mm in PDF_PAGES.values()], per_row=1); self.pdf_margin = SliderRow(0, PDF_MAX_MARGIN_MM, 10, suffix=' mm')
        self.collage_columns = QSpinBox(); self.collage_columns.setRange(0, 6); self.collage_columns.setSpecialValueText('Automático')
        self.collage_cell = QSpinBox(); self.collage_cell.setRange(64, 2000); self.collage_cell.setValue(600); self.collage_cell.setSuffix(' px')
        self.collage_gap = QSpinBox(); self.collage_gap.setRange(0, 200); self.collage_gap.setValue(20); self.collage_gap.setSuffix(' px')
        self.annotation = QLineEdit(); self.annotation.setMaxLength(200); self.annotation.setPlaceholderText('Digite o texto')
        self.annotation_x = QSpinBox(); self.annotation_x.setRange(0, 10000); self.annotation_x.setSuffix(' px')
        self.annotation_y = QSpinBox(); self.annotation_y.setRange(0, 10000); self.annotation_y.setSuffix(' px')
        self.annotation_color = ColorField('#FF5A00')
        self.annotation_size = QSpinBox(); self.annotation_size.setRange(8, 400); self.annotation_size.setValue(18); self.annotation_size.setSuffix(' px')
        self.adjust_brightness = SliderRow(-100, 100, 0, suffix=''); self.adjust_contrast = SliderRow(-100, 100, 0, suffix=''); self.adjust_saturation = SliderRow(-100, 100, 0, suffix='')
        self.adjust_flip = ChipGroup(['Nenhum', 'Horizontal', 'Vertical', 'Ambos'], per_row=2)
        self.adjust_reset_button = QPushButton('Redefinir ajustes'); self.adjust_reset_button.clicked.connect(self.reset_adjustments)
        self._adjust_source = None
        self.pdfimg_dpi = SliderRow(pdfinfo.DPI_MIN, pdfinfo.DPI_MAX, pdfinfo.DPI_DEFAULT, suffix=' dpi')
        self.pdfimg_pages = QLineEdit(); self.pdfimg_pages.setMaxLength(200); self.pdfimg_pages.setPlaceholderText('Todas as páginas (ou, por exemplo, 1-3,7)')
        self.pdfimg_pages.setToolTip('Páginas a salvar: números separados por vírgula e intervalos com hífen. «5-» vai até o fim e vazio significa todas.')
        self.txt_mode = ChipGroup(['Um arquivo', 'Com marcas de página', 'Um por página'], per_row=1)
        self.txt_layout = ChipGroup(['Simples', 'Manter o layout'], per_row=2)
        self.txt_pages = QLineEdit(); self.txt_pages.setMaxLength(200); self.txt_pages.setPlaceholderText('Todas as páginas (ou, por exemplo, 1-3,7)')
        self.txt_info = QLabel(''); self.txt_info.setWordWrap(True); self.txt_info.setTextFormat(Qt.TextFormat.PlainText)
        self.emb_pages = QLineEdit(); self.emb_pages.setMaxLength(200); self.emb_pages.setPlaceholderText('Todas as páginas (ou, por exemplo, 1-3,7)')
        self.emb_min = SliderRow(0, 500, 32, suffix=' px')
        self.emb_min.setToolTip('Ignora imagens cujo maior lado é menor que isto (ícones, filetes, pontos). 0 extrai tudo.')
        self.emb_info = QLabel(''); self.emb_info.setWordWrap(True); self.emb_info.setTextFormat(Qt.TextFormat.PlainText)
        self.rocr_pages = QLineEdit(); self.rocr_pages.setMaxLength(200); self.rocr_pages.setPlaceholderText('Todas (ou, por exemplo, 1-5,9)')
        self.rocr_pages.setToolTip(f'Páginas a reconhecer; até {PDF_OCR_MAX_PAGES} com OCR por vez.')
        self.rocr_skip = ChipGroup(['Pular', 'Reconhecer todas'], per_row=2)
        self.rocr_skip.setToolTip('«Pular» deixa como estão as páginas que já têm texto; elas não contam no limite.')
        self.rocr_text = ChipGroup(['Um arquivo', 'Com marcas de página', 'Um por página'], per_row=1)
        self.rocr_info = QLabel(''); self.rocr_info.setWordWrap(True); self.rocr_info.setTextFormat(Qt.TextFormat.PlainText)
        self.pw_pass = QLineEdit(); self.pw_repeat = QLineEdit(); self.pw_owner = QLineEdit(); self.pw_current = QLineEdit()
        for field in (self.pw_pass, self.pw_repeat, self.pw_owner, self.pw_current):
            field.setEchoMode(QLineEdit.EchoMode.Password); field.setMaxLength(100); field.setPlaceholderText('Senha')
            field.setToolTip('A senha não é guardada em lugar nenhum e some da tela quando você inicia a tarefa.')
        self.pw_repeat.setPlaceholderText('Repita a senha'); self.pw_owner.setPlaceholderText('Opcional, para bloquear impressão/cópia/edição')
        self.pw_print = ChipGroup(['Permitir', 'Bloquear'], per_row=2); self.pw_copy = ChipGroup(['Permitir', 'Bloquear'], per_row=2); self.pw_edit = ChipGroup(['Permitir', 'Bloquear'], per_row=2)
        self.pw_info = QLabel(''); self.pw_info.setWordWrap(True); self.pw_info.setTextFormat(Qt.TextFormat.PlainText)
        self.st_kind = ChipGroup(['Numeração', 'Texto', 'Marca d\'água'], per_row=3)
        self.st_text = QLineEdit(); self.st_text.setMaxLength(100); self.st_text.setText('Página {n} de {total}')
        self.st_text.setToolTip('{n} vira o número da página e {total} o total de páginas. Só letras latinas (com acentos), números e pontuação comum.')
        self.st_position = ChipGroup(['↖', '↑', '↗', '←', '●', '→', '↙', '↓', '↘'], per_row=3); self.st_position.setCurrentIndex(7)
        self.st_angle = ChipGroup(['Horizontal', 'Diagonal'], per_row=2); self.st_angle.setCurrentIndex(1)
        self.st_size = SliderRow(6, 72, 10, suffix=' pt'); self.st_wsize = SliderRow(10, 100, 70, suffix=' %')
        self.st_wsize.setToolTip('Quanto da largura da página (ou da diagonal) o texto ocupa.')
        self.st_opacity = SliderRow(5, 100, 100, suffix=' %'); self.st_margin = SliderRow(0, 50, 10, suffix=' mm')
        self.st_color = ColorField('#000000'); self.st_bold = ChipGroup(['Normal', 'Negrito'], per_row=2)
        self.st_start = QSpinBox(); self.st_start.setRange(1, 9999); self.st_start.setValue(1); self.st_start.setToolTip('Número da primeira página (útil para continuar a numeração de outro arquivo).')
        self.st_pages = QLineEdit(); self.st_pages.setMaxLength(200); self.st_pages.setPlaceholderText('Todas as páginas (ou, por exemplo, 2- para pular a capa)')
        self.st_info = QLabel(''); self.st_info.setWordWrap(True); self.st_info.setTextFormat(Qt.TextFormat.PlainText)
        self.rd_areas: list[str] = []                 # «página:x0,y0,x1,y1» em milésimos da página
        self.rd_page = 1
        self.rd_help = QLabel('Arraste sobre a página, clique em “Marcar área” e repita. Mude de página pelas miniaturas.'); self.rd_help.setWordWrap(True)
        self.rd_buttons = QWidget(); rd_row = QHBoxLayout(self.rd_buttons); rd_row.setContentsMargins(0, 0, 0, 0); rd_row.setSpacing(6)
        self.rd_add_button = QPushButton('Marcar área'); self.rd_undo_button = QPushButton('Desfazer'); self.rd_clear_button = QPushButton('Limpar')
        for button in (self.rd_add_button, self.rd_undo_button, self.rd_clear_button):
            rd_row.addWidget(button)
        self.rd_terms = QLineEdit(); self.rd_terms.setMaxLength(600); self.rd_terms.setPlaceholderText('Palavras ou números, separados por ponto e vírgula')
        self.rd_terms.setToolTip('Todo trecho igual (sem diferenciar maiúsculas) no texto do PDF é tarjado. Só funciona em PDF com texto de verdade; em página digitalizada, marque a área.')
        self.rd_presets = QWidget(); rd_preset_row = QHBoxLayout(self.rd_presets); rd_preset_row.setContentsMargins(0, 0, 0, 0); rd_preset_row.setSpacing(8)
        self.rd_preset_boxes = {}
        for key in ('cpf', 'cnpj', 'email', 'telefone'):
            box = QCheckBox(pdfredact.PRESETS[key][0]); self.rd_preset_boxes[key] = box; rd_preset_row.addWidget(box)
        self.rd_dpi = ChipGroup(['150 dpi', '200 dpi', '300 dpi'], per_row=3); self.rd_dpi.setCurrentIndex(1)
        self.rd_info = QLabel(''); self.rd_info.setWordWrap(True); self.rd_info.setTextFormat(Qt.TextFormat.PlainText)
        self.fm_areas: list[str] = []
        self.fm_page = 1
        self.fm_image = ''
        self.fm_editors: dict = {}
        self.fm_signature_key = None
        self.fm_fields_box = QWidget(); self.fm_fields_layout = QFormLayout(self.fm_fields_box); self.fm_fields_layout.setContentsMargins(0, 0, 0, 0); self.fm_fields_layout.setVerticalSpacing(6)
        self.fm_fields_scroll = QScrollArea(); self.fm_fields_scroll.setWidgetResizable(True); self.fm_fields_scroll.setWidget(self.fm_fields_box); self.fm_fields_scroll.setMinimumHeight(120); self.fm_fields_scroll.setMaximumHeight(260)
        self.fm_flatten = ChipGroup(['Manter editável', 'Achatar'], per_row=2)
        self.fm_flatten.setToolTip('Achatar fixa os valores na página e remove os campos: o formulário deixa de ser editável.')
        self.fm_image_box = QWidget(); fm_image_row = QHBoxLayout(self.fm_image_box); fm_image_row.setContentsMargins(0, 0, 0, 0); fm_image_row.setSpacing(6)
        self.fm_image_button = QPushButton('Escolher imagem…'); self.fm_image_label = QLabel('Nenhuma'); self.fm_image_label.setObjectName('Muted'); self.fm_image_label.setWordWrap(True)
        fm_image_row.addWidget(self.fm_image_button); fm_image_row.addWidget(self.fm_image_label, 1)
        self.fm_help = QLabel('Escolha a imagem, arraste sobre a página onde ela deve ficar e clique em “Marcar área”.'); self.fm_help.setWordWrap(True)
        self.fm_buttons = QWidget(); fm_row = QHBoxLayout(self.fm_buttons); fm_row.setContentsMargins(0, 0, 0, 0); fm_row.setSpacing(6)
        self.fm_add_button = QPushButton('Marcar área'); self.fm_undo_button = QPushButton('Desfazer'); self.fm_clear_button = QPushButton('Limpar')
        for button in (self.fm_add_button, self.fm_undo_button, self.fm_clear_button):
            fm_row.addWidget(button)
        self.fm_info = QLabel(''); self.fm_info.setWordWrap(True); self.fm_info.setTextFormat(Qt.TextFormat.PlainText)
        self.cp_level = ChipGroup(['Leve', 'Médio', 'Forte'], per_row=3); self.cp_level.setCurrentIndex(1)
        self.ac_format = ChipGroup(['MP3', 'M4A', 'FLAC', 'OGG', 'Opus', 'WAV', 'AIFF'], per_row=4)
        self.ac_quality = ChipGroup(['Baixa', 'Média', 'Alta'], per_row=3); self.ac_quality.setCurrentIndex(1)
        self.ac_tags = ChipGroup(['Manter', 'Remover'], per_row=2)
        self.ac_info = QLabel(''); self.ac_info.setWordWrap(True); self.ac_info.setTextFormat(Qt.TextFormat.PlainText)
        self.cp_info = QLabel(''); self.cp_info.setWordWrap(True); self.cp_info.setTextFormat(Qt.TextFormat.PlainText)
        self.kl_meta = ChipGroup(['Remover', 'Manter'], per_row=2); self.kl_attach = ChipGroup(['Remover', 'Manter'], per_row=2); self.kl_js = ChipGroup(['Remover', 'Manter'], per_row=2)
        self.kl_details = QLabel(''); self.kl_details.setWordWrap(True); self.kl_details.setTextFormat(Qt.TextFormat.PlainText)
        self.kl_details.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.kl_info = QLabel(''); self.kl_info.setWordWrap(True); self.kl_info.setTextFormat(Qt.TextFormat.PlainText)
        self.org_buttons = QWidget(); org_grid = QGridLayout(self.org_buttons); org_grid.setContentsMargins(0, 0, 0, 0); org_grid.setSpacing(6)
        self.org_left = QPushButton('↺ Girar'); self.org_right = QPushButton('↻ Girar'); self.org_delete = QPushButton('Excluir'); self.org_copy = QPushButton('Duplicar')
        self.org_back = QPushButton('◀ Mover'); self.org_forward = QPushButton('Mover ▶'); self.org_all = QPushButton('Selecionar tudo'); self.org_reset = QPushButton('Restaurar tudo')
        for position, button in enumerate((self.org_left, self.org_right, self.org_back, self.org_forward, self.org_copy, self.org_delete, self.org_all, self.org_reset)):
            org_grid.addWidget(button, position // 2, position % 2)
        self.org_left.setToolTip('Gira as páginas selecionadas 90° para a esquerda.'); self.org_right.setToolTip('Gira as páginas selecionadas 90° para a direita.')
        self.org_info = QLabel(''); self.org_info.setWordWrap(True); self.org_info.setTextFormat(Qt.TextFormat.PlainText)
        self.split_mode = ChipGroup(['Uma por página', 'A cada N', 'Por intervalos', 'Extrair páginas'], per_row=2)
        self.split_every = QSpinBox(); self.split_every.setRange(1, 200); self.split_every.setValue(2); self.split_every.setSuffix(' páginas')
        self.split_ranges = QLineEdit(); self.split_ranges.setMaxLength(200)
        self.split_info = QLabel(''); self.split_info.setWordWrap(True); self.split_info.setTextFormat(Qt.TextFormat.PlainText)
        self.pdfimg_info = QLabel(''); self.pdfimg_info.setWordWrap(True); self.pdfimg_info.setTextFormat(Qt.TextFormat.PlainText)
        self.out_format = ChipGroup([label for _fmt, _ext, label in OUTPUT_FORMATS.values()], per_row=3)
        self.out_quality = SliderRow(1, 100, 90, suffix=' %')
        self.out_flatten = ColorField('#FFFFFF')
        self.vector_width = QSpinBox(); self.vector_width.setRange(0, VECTOR_MAX_WIDTH); self.vector_width.setSpecialValueText('Do arquivo'); self.vector_width.setSuffix(' px')
        self.vector_width.setToolTip('Largura em que o vetor (SVG, .ai, EMF ou WMF) é desenhado; a altura segue a proporção. «Do arquivo» usa o tamanho declarado no arquivo (no .ai, 1 pt = 1 px).')
        self._vector_timer = QTimer(self); self._vector_timer.setSingleShot(True); self._vector_timer.setInterval(450)
        self.wm_kind = ChipGroup(['Texto', 'Imagem'], per_row=2)
        self.wm_text = QLineEdit(); self.wm_text.setMaxLength(100); self.wm_text.setPlaceholderText('Digite o texto da marca')
        self.wm_image_path = QLineEdit(); self.wm_image_path.setReadOnly(True); self.wm_image_path.setPlaceholderText('Nenhuma imagem escolhida')
        self.wm_image_button = QPushButton('Escolher…'); self.wm_image_button.clicked.connect(self.choose_watermark_image)
        self.wm_image_row = QWidget(); wm_row = QHBoxLayout(self.wm_image_row); wm_row.setContentsMargins(0, 0, 0, 0); wm_row.setSpacing(6)
        wm_row.addWidget(self.wm_image_path, 1); wm_row.addWidget(self.wm_image_button)
        self.wm_color = ColorField('#FFFFFF')
        self.wm_scale = SliderRow(1, 100, 25, suffix=' %'); self.wm_opacity = SliderRow(1, 100, 60, suffix=' %'); self.wm_margin = SliderRow(0, 25, 3, suffix=' %')
        self.wm_position = ChipGroup(['↖', '↑', '↗', '←', '●', '→', '↙', '↓', '↘', 'Repetir'], per_row=3)
        self.wm_position.setCurrentIndex(8)
        self._wm_source = None; self._wm_logo = None; self._wm_logo_path = ''
        self.sharp_mode = ChipGroup(['Nitidez', 'Desfoque'], per_row=2)
        self.bg_model = ChipGroup([values[3] for values in bgremove.MODELS.values()], per_row=1); self.bg_feather = SliderRow(0, bgremove.MAX_FEATHER, bgremove.DEFAULT_FEATHER, suffix=' px')
        self.bg_status = QLabel(''); self.bg_status.setWordWrap(True)
        self.bg_preview_button = QPushButton('Ver prévia do resultado'); self.bg_preview_button.clicked.connect(self._bg_preview)
        self.ocr_lang = ChipGroup(list(ocr.LANGS.values()), per_row=1); self.ocr_psm = ChipGroup([label for _id, label in ocr.PSM.values()], per_row=2)
        self.ocr_status = QLabel(''); self.ocr_status.setWordWrap(True)
        self.sharp_amount = SliderRow(1, 100, 50, suffix=' %'); self.sharp_radius = SliderRow(1, 100, 2, suffix='')
        self._sharp_source = None
        self.lv_mode = ChipGroup(['Manual', 'Automático'], per_row=2); self.lv_hist = HistogramView()
        self.lv_black = SliderRow(0, 254, 0, suffix=''); self.lv_white = SliderRow(1, 255, 255, suffix='')
        self.lv_gamma = SliderRow(10, 500, 100, formatter=lambda value: f'{value / 100:.2f}')
        self.lv_reset_button = QPushButton('Redefinir níveis'); self.lv_reset_button.clicked.connect(self.reset_levels)
        self.rename_pattern = QLineEdit(); self.rename_pattern.setMaxLength(120); self.rename_pattern.setPlaceholderText('{nome}-{sufixo}')
        self.rename_pattern.setToolTip('Marcadores: {nome} nome original · {n} número · {sufixo} sufixo da ferramenta · {data} AAAA-MM-DD.\nA extensão é escolhida pela ferramenta. Vazio = nome padrão.')
        self.rename_example = QLabel(''); self.rename_example.setWordWrap(True)
        self.to_folder = QCheckBox('Salvar tudo numa pasta nova, com nomes 001, 002… na ordem da seleção')
        self.to_folder.setToolTip('Cria a pasta «Convertidas AAAA-MM-DD HH-MM-SS» ao lado do primeiro arquivo e grava ali todas as imagens convertidas, numeradas pela ordem em que foram escolhidas.\nOs originais não são alterados. Formatos de entrada diferentes podem ser misturados.')
        self.to_folder.toggled.connect(lambda _checked: self._rename_changed(force=True))
        self.rename_start = QSpinBox(); self.rename_start.setRange(0, 999999); self.rename_start.setValue(1)
        self.rename_digits = SliderRow(1, 6, 1, suffix='')
        self._lv_source = None
        self.shape_items: list[dict] = []; self._shape_source = None
        self.sh_kind = ChipGroup(['Retângulo', 'Elipse', 'Linha', 'Seta'], per_row=2); self.sh_color = ColorField('#FF0000')
        self.sh_thickness = SliderRow(1, 200, 6, suffix=' px'); self.sh_fill = ChipGroup(['Contorno', 'Cheio'], per_row=2)
        self.sh_dir = ChipGroup(['↘', '↙', '↗', '↖'], per_row=4)
        self.sh_help = QLabel('Arraste sobre a imagem para desenhar a forma e clique em “Adicionar forma”.'); self.sh_help.setWordWrap(True)
        self.sh_buttons = QWidget(); sh_row = QHBoxLayout(self.sh_buttons); sh_row.setContentsMargins(0, 0, 0, 0); sh_row.setSpacing(6)
        self.sh_add_button = QPushButton('Adicionar forma'); self.sh_undo_button = QPushButton('Desfazer última')
        sh_row.addWidget(self.sh_add_button); sh_row.addWidget(self.sh_undo_button)
        self.sh_add_button.clicked.connect(self.add_shape); self.sh_undo_button.clicked.connect(self.undo_shape)
        self.rotate_angle = ChipGroup(['Nenhum', '90° à direita', '180°', '90° à esquerda'], per_row=2)
        self.rotate_flip = ChipGroup(['Nenhum', 'Horizontal', 'Vertical', 'Ambos'], per_row=2)
        self.rotate_info = QLabel(''); self.rotate_info.setWordWrap(True)
        self.resize_mode = ChipGroup(['Porcentagem', 'Caber em', 'Medida exata'], per_row=2)
        self.resize_percent = SliderRow(1, 400, 50, suffix=' %')
        self.resize_width = QSpinBox(); self.resize_width.setRange(0, RESIZE_MAX_SIDE); self.resize_width.setSpecialValueText('Sem limite'); self.resize_width.setSuffix(' px')
        self.resize_height = QSpinBox(); self.resize_height.setRange(0, RESIZE_MAX_SIDE); self.resize_height.setSpecialValueText('Sem limite'); self.resize_height.setSuffix(' px')
        self.resize_info = QLabel(''); self.resize_info.setWordWrap(True); self.resize_info.setTextFormat(Qt.TextFormat.PlainText)
        self.metadata_info = QLabel(''); self.metadata_info.setWordWrap(True); self.metadata_info.setTextFormat(Qt.TextFormat.PlainText)
        self.metadata_info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.redact_regions: list[tuple[int, int, int, int]] = []
        self.redact_mode = ChipGroup(['Tarja preta', 'Pixelar'], per_row=2)
        self.redact_block = SliderRow(4, 200, 16)
        self.redact_help = QLabel('Marque uma área e clique em “Adicionar área”.'); self.redact_help.setWordWrap(True)
        self._redact_source = None
        self.redact_buttons = QWidget(); redact_row = QHBoxLayout(self.redact_buttons); redact_row.setContentsMargins(0, 0, 0, 0); redact_row.setSpacing(6)
        self.redact_add_button = QPushButton('Adicionar área'); self.redact_undo_button = QPushButton('Desfazer última')
        redact_row.addWidget(self.redact_add_button); redact_row.addWidget(self.redact_undo_button)
        self.redact_add_button.clicked.connect(self.add_redact_region); self.redact_undo_button.clicked.connect(self.undo_redact_region)
        self.crop_help = QLabel('Arraste na imagem para definir a área.')
        self.crop_help.setWordWrap(True)
        self.crop_aspect = ChipGroup([label for label, _ratio in ASPECTS], per_row=4)
        self.clear_crop_button = QPushButton('Limpar seleção')
        self.clear_crop_button.clicked.connect(self._clear_crop_selection)
        rows = (('width', 'Largura máxima', self.width), ('rotation', 'Rotação', self.rotation), ('preset', 'Predefinição', self.compress_preset), ('quality', 'Qualidade JPEG', self.quality),
                ('crop_aspect', 'Proporção', self.crop_aspect), ('crop', 'Área', self.crop_help), ('crop_clear', '', self.clear_crop_button),
                ('abright', 'Brilho', self.adjust_brightness), ('acontrast', 'Contraste', self.adjust_contrast), ('asat', 'Saturação', self.adjust_saturation),
                ('aflip', 'Espelhar', self.adjust_flip), ('areset', '', self.adjust_reset_button),
                ('ofmt', 'Salvar como', self.out_format), ('oqual', 'Qualidade', self.out_quality), ('oflat', 'Fundo opaco', self.out_flatten),
                ('tmode', 'Salvar como', self.txt_mode), ('tlayout', 'Leitura', self.txt_layout), ('tpages', 'Páginas', self.txt_pages), ('tinfo', 'Resultado', self.txt_info),
                ('pwpass', 'Senha para abrir', self.pw_pass), ('pwrepeat', 'Repetir senha', self.pw_repeat), ('pwprint', 'Imprimir', self.pw_print), ('pwcopy', 'Copiar texto', self.pw_copy),
                ('pwedit', 'Editar', self.pw_edit), ('pwowner', 'Senha de permissões', self.pw_owner), ('pwcurrent', 'Senha do PDF', self.pw_current), ('pwinfo', 'Resultado', self.pw_info),
                ('skind', 'Tipo', self.st_kind), ('stext', 'Texto', self.st_text), ('spos', 'Posição', self.st_position), ('sangle', 'Direção', self.st_angle), ('ssize', 'Tamanho', self.st_size),
                ('swsize', 'Largura', self.st_wsize), ('sopac', 'Opacidade', self.st_opacity), ('smargin', 'Margem', self.st_margin), ('scolor', 'Cor', self.st_color), ('sbold', 'Peso', self.st_bold),
                ('fmfields', 'Campos', self.fm_fields_scroll), ('fmflat', 'Formulário', self.fm_flatten), ('fmimage', 'Assinatura', self.fm_image_box), ('fmhelp', 'Área', self.fm_help), ('fmbuttons', '', self.fm_buttons), ('fminfo', 'Resumo', self.fm_info),
                ('rdhelp', 'Áreas', self.rd_help), ('rdbuttons', '', self.rd_buttons), ('rdterms', 'Termos', self.rd_terms), ('rdpresets', 'Dados pessoais', self.rd_presets), ('rddpi', 'Resolução', self.rd_dpi), ('rdinfo', 'Resumo', self.rd_info),
                ('sstart', 'Primeiro nº', self.st_start), ('spages', 'Páginas', self.st_pages), ('sinfo', 'Exemplo', self.st_info),
                ('plevel', 'Nível', self.cp_level), ('pinfo', 'Resultado', self.cp_info),
                ('aformat', 'Formato', self.ac_format), ('aquality', 'Qualidade', self.ac_quality), ('atags', 'Etiquetas', self.ac_tags), ('ainfo', 'Resultado', self.ac_info),
                ('kdetails', 'No arquivo', self.kl_details), ('kmeta', 'Metadados', self.kl_meta), ('kattach', 'Anexos', self.kl_attach), ('kjs', 'JavaScript', self.kl_js), ('kinfo', 'Resultado', self.kl_info),
                ('rpages', 'Páginas', self.rocr_pages), ('rskip', 'Páginas com texto', self.rocr_skip), ('rtext', 'Salvar como', self.rocr_text), ('rinfo', 'Resultado', self.rocr_info),
                ('epages', 'Páginas', self.emb_pages), ('emin', 'Tamanho mínimo', self.emb_min), ('einfo', 'Resultado', self.emb_info),
                ('qbuttons', '', self.org_buttons), ('qinfo', 'Resultado', self.org_info),
                ('xmode', 'Modo', self.split_mode), ('xevery', 'Por parte', self.split_every), ('xranges', 'Páginas', self.split_ranges), ('xinfo', 'Resultado', self.split_info),
                ('pimgdpi', 'Resolução', self.pdfimg_dpi), ('pimgpages', 'Páginas', self.pdfimg_pages), ('pimginfo', 'Tamanho', self.pdfimg_info),
                ('nfolder', '', self.to_folder), ('nname', 'Nome', self.rename_pattern), ('nexample', 'Exemplo', self.rename_example), ('nstart', 'Primeiro nº', self.rename_start), ('ndigits', 'Dígitos', self.rename_digits), ('vwidth', 'Largura do vetor', self.vector_width),
                ('hkind', 'Forma', self.sh_kind), ('hcolor', 'Cor', self.sh_color), ('hthick', 'Espessura', self.sh_thickness), ('hfill', 'Estilo', self.sh_fill),
                ('hdir', 'Direção', self.sh_dir), ('hhelp', 'Formas', self.sh_help), ('hbuttons', '', self.sh_buttons),
                ('lmode', 'Modo', self.lv_mode), ('lhist', 'Histograma', self.lv_hist), ('lblack', 'Preto', self.lv_black), ('lwhite', 'Branco', self.lv_white),
                ('lgamma', 'Tons médios', self.lv_gamma), ('lreset', '', self.lv_reset_button),
                ('bmodel', 'Modelo', self.bg_model), ('bfeather', 'Borda suave', self.bg_feather), ('bstatus', '', self.bg_status), ('bpreview', '', self.bg_preview_button),
                ('smode', 'Efeito', self.sharp_mode), ('samount', 'Força', self.sharp_amount), ('sradius', 'Raio', self.sharp_radius),
                ('wkind', 'Tipo', self.wm_kind), ('wtext', 'Texto', self.wm_text), ('wimage', 'Imagem', self.wm_image_row), ('wcolor', 'Cor', self.wm_color),
                ('wscale', 'Tamanho', self.wm_scale), ('wopacity', 'Opacidade', self.wm_opacity), ('wpos', 'Posição', self.wm_position), ('wmargin', 'Margem', self.wm_margin),
                ('gangle', 'Girar', self.rotate_angle), ('gflip', 'Espelhar', self.rotate_flip), ('ginfo', 'Resultado', self.rotate_info),
                ('zmode', 'Modo', self.resize_mode), ('zpercent', 'Escala', self.resize_percent), ('zwidth', 'Largura', self.resize_width), ('zheight', 'Altura', self.resize_height), ('zinfo', 'Resultado', self.resize_info),
                ('minfo', '', self.metadata_info),
                ('olang', 'Idioma', self.ocr_lang), ('opsm', 'Página', self.ocr_psm), ('ostatus', '', self.ocr_status),
                ('rmode', 'Modo', self.redact_mode), ('rblock', 'Bloco', self.redact_block), ('rhelp', 'Áreas', self.redact_help), ('rbuttons', '', self.redact_buttons),
                ('canvas_w', 'Largura do canvas', self.canvas_width), ('canvas_h', 'Altura do canvas', self.canvas_height),
                ('ppage', 'Página', self.pdf_page), ('pocr', 'Texto pesquisável (OCR)', self.pdf_ocr), ('pmargin', 'Margem', self.pdf_margin),
                ('clist', 'Ordem (arraste)', self.collage_list), ('cbuttons', '', self.collage_buttons), ('mpages', 'Páginas do arquivo', self.merge_pages), ('mtotal', 'Resultado', self.merge_info),
                ('ccols', 'Colunas', self.collage_columns), ('ccell', 'Tamanho da célula', self.collage_cell), ('cgap', 'Espaço entre imagens', self.collage_gap),
                ('bswatch', 'Fundo', self.backdrop_swatches), ('bcustom', 'Cor', self.backdrop_color), ('bpad', 'Margem', self.backdrop_padding),
                ('bradius', 'Cantos', self.backdrop_radius), ('bshadow', 'Sombra', self.backdrop_shadow), ('bratio', 'Proporção', self.backdrop_ratio),
                ('background', 'Cor de fundo', self.background), ('text', 'Texto', self.annotation),
                ('asize', 'Tamanho do texto', self.annotation_size), ('ax', 'Posição X', self.annotation_x), ('ay', 'Posição Y', self.annotation_y), ('acolor', 'Cor do texto', self.annotation_color))
        common = ('ofmt', 'oqual', 'oflat', 'nfolder', 'nname', 'nexample', 'nstart', 'ndigits', 'vwidth')      # comuns a todas as ferramentas: vêm depois dos controles da própria ferramenta (0.9.26)
        rows = tuple(r for r in rows if r[0] not in common) + tuple(r for r in rows if r[0] in common)
        self.form_fields = {}
        spanning = ('nfolder', 'bpreview', 'clist', 'cbuttons', 'rbuttons', 'hbuttons', 'rdbuttons', 'fmbuttons', 'fmfields', 'rhelp', 'hhelp', 'ostatus', 'bstatus', 'minfo', 'lhist', 'crop', 'qbuttons')      # sem rótulo ao lado: usam a largura toda
        for key, label, widget in rows:
            if key in spanning and key not in ('lhist', 'crop', 'rhelp', 'hhelp'):
                self.settings_form.addRow(widget)
            else:
                self.settings_form.addRow(label, widget)
            self.form_fields[key] = widget
        settings_layout.addLayout(self.settings_form)
        settings_layout.addWidget(self.tool_hint)
        self.run_button = QPushButton('Aplicar'); self.run_button.setObjectName('Primary'); self.run_button.clicked.connect(self.run_selected)
        self.report_card = QFrame(); self.report_card.setObjectName('Footer'); self.report_card.hide()
        report_layout = QVBoxLayout(self.report_card); report_layout.setContentsMargins(12, 10, 12, 10); report_layout.setSpacing(4)
        self.report_title = QLabel('O que mudou neste resultado'); self.report_title.setStyleSheet('font-weight:600')
        self.report_label = QLabel(''); self.report_label.setWordWrap(True); self.report_label.setTextFormat(Qt.TextFormat.PlainText)
        report_layout.addWidget(self.report_title); report_layout.addWidget(self.report_label)
        settings_layout.addWidget(self.report_card)
        self.open_button = QPushButton('Abrir pasta do resultado'); self.open_button.setEnabled(False); self.open_button.clicked.connect(self.open_output)
        settings_layout.addStretch(1)
        self.settings_scroll = QScrollArea(); self.settings_scroll.setWidgetResizable(True)
        self.settings_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.settings_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.settings_scroll.setWidget(settings)
        # cartão de ajustes: a lista de controles rola, mas o botão principal fica sempre visível no rodapé do cartão (0.9.26)
        self.settings_card = QFrame(); self.settings_card.setObjectName('Card')
        self.settings_card.setMinimumWidth(settings.minimumWidth() + 40); self.settings_card.setMaximumWidth(settings.maximumWidth() + 40)
        card_layout = QVBoxLayout(self.settings_card); card_layout.setContentsMargins(18, 16, 10, 14); card_layout.setSpacing(10)
        self.settings_scroll.setMinimumWidth(0); self.settings_scroll.setMaximumWidth(16777215)
        card_layout.addWidget(self.settings_scroll, 1)
        footer_layout = QVBoxLayout(); footer_layout.setContentsMargins(0, 0, 8, 0); footer_layout.setSpacing(8)
        footer_layout.addWidget(self.run_button); footer_layout.addWidget(self.open_button)
        card_layout.addLayout(footer_layout)
        body.addWidget(self.settings_card, 2)

        self.crop_preview.selection_changed.connect(self._crop_selection_changed)
        self.redact_block.valueChanged.connect(lambda _v: self._refresh_redact_overlay())
        self.crop_aspect.currentIndexChanged.connect(self._aspect_changed)
        self.redact_mode.currentIndexChanged.connect(self._redact_mode_changed)
        for control in (self.adjust_brightness, self.adjust_contrast, self.adjust_saturation):
            control.valueChanged.connect(self._adjust_changed)
        self.adjust_flip.currentIndexChanged.connect(self._adjust_changed)
        self.out_format.currentIndexChanged.connect(self._output_format_changed)
        self.vector_width.valueChanged.connect(lambda _value: self._vector_timer.start())
        self._vector_timer.timeout.connect(self._vector_width_changed)
        self.sh_kind.currentIndexChanged.connect(self._shape_kind_changed)
        self.sh_fill.currentIndexChanged.connect(lambda _i: self._refresh_shapes_overlay()); self.sh_dir.currentIndexChanged.connect(lambda _i: self._refresh_shapes_overlay())
        self.sh_color.textChanged.connect(lambda _t: self._refresh_shapes_overlay()); self.sh_thickness.valueChanged.connect(lambda _v: self._refresh_shapes_overlay())
        self.rename_pattern.textChanged.connect(self._rename_changed); self.rename_start.valueChanged.connect(self._rename_changed); self.rename_digits.valueChanged.connect(self._rename_changed)
        self.lv_mode.currentIndexChanged.connect(self._levels_mode_changed)
        self.lv_black.valueChanged.connect(self._levels_black_changed); self.lv_white.valueChanged.connect(self._levels_white_changed)
        self.lv_gamma.valueChanged.connect(self._levels_changed)
        self.sharp_mode.currentIndexChanged.connect(self._sharpen_mode_changed)
        self.bg_model.currentIndexChanged.connect(self._bg_model_changed)
        for control in (self.sharp_amount, self.sharp_radius):
            control.valueChanged.connect(self._sharpen_changed)
        self.wm_kind.currentIndexChanged.connect(self._watermark_kind_changed)
        self.wm_position.currentIndexChanged.connect(self._watermark_position_changed)
        self.wm_text.textChanged.connect(self._watermark_changed); self.wm_color.textChanged.connect(self._watermark_changed)
        for control in (self.wm_scale, self.wm_opacity, self.wm_margin):
            control.valueChanged.connect(self._watermark_changed)
        self.rotate_angle.currentIndexChanged.connect(self._rotate_changed); self.rotate_flip.currentIndexChanged.connect(self._rotate_changed)
        self.resize_mode.currentIndexChanged.connect(self._resize_mode_changed)
        self.resize_percent.valueChanged.connect(self._resize_changed)
        self.organizer.changed.connect(self._organize_changed)
        self.org_left.clicked.connect(lambda: self.organizer.rotate_selected(-90)); self.org_right.clicked.connect(lambda: self.organizer.rotate_selected(90))
        self.org_delete.clicked.connect(self.organizer.delete_selected); self.org_copy.clicked.connect(self.organizer.duplicate_selected)
        self.org_back.clicked.connect(lambda: self.organizer.move_selected(-1)); self.org_forward.clicked.connect(lambda: self.organizer.move_selected(1))
        for edit_field in (self.txt_pages, self.emb_pages):
            edit_field.textChanged.connect(self._pdftext_changed)
        self.txt_mode.currentIndexChanged.connect(self._pdftext_changed); self.txt_layout.currentIndexChanged.connect(self._pdftext_changed)
        self.emb_min.valueChanged.connect(self._pdftext_changed)
        self.rocr_pages.textChanged.connect(self._pdfocr_changed); self.rocr_skip.currentIndexChanged.connect(self._pdfocr_changed)
        self.pdf_stage.infos_ready.connect(self._pdfocr_changed)
        self.form_stage.page_shown.connect(self._form_page_shown); self.form_stage.infos_ready.connect(self._form_infos)
        self.fm_add_button.clicked.connect(self.add_form_area); self.fm_undo_button.clicked.connect(self.undo_form_area); self.fm_clear_button.clicked.connect(self.clear_form_areas)
        self.fm_image_button.clicked.connect(self.choose_sign_image); self.fm_flatten.currentIndexChanged.connect(self._form_changed)
        self.form_stage.page_view.selection_changed.connect(self._form_changed)
        self.redact_stage.page_shown.connect(self._redact_page_shown); self.redact_stage.infos_ready.connect(self._redact_changed)
        self.rd_add_button.clicked.connect(self.add_redact_area); self.rd_undo_button.clicked.connect(self.undo_redact_area); self.rd_clear_button.clicked.connect(self.clear_redact_areas)
        self.redact_stage.page_view.selection_changed.connect(self._redact_changed)
        self.rd_terms.textChanged.connect(self._redact_changed); self.rd_dpi.currentIndexChanged.connect(self._redact_changed)
        for box in self.rd_preset_boxes.values():
            box.toggled.connect(self._redact_changed)
        self.pdf_stage.infos_ready.connect(self._pdfclean_changed)
        for field in (self.pw_pass, self.pw_repeat, self.pw_owner, self.pw_current):
            field.textChanged.connect(self._password_changed)
        for chips in (self.pw_print, self.pw_copy, self.pw_edit):
            chips.currentIndexChanged.connect(self._password_changed)
        self.pdf_stage.infos_ready.connect(self._password_changed)
        self.st_kind.currentIndexChanged.connect(self._stamp_kind_changed)
        self.st_position.currentIndexChanged.connect(self._stamp_layout_changed); self.st_angle.currentIndexChanged.connect(self._stamp_changed); self.st_bold.currentIndexChanged.connect(self._stamp_changed)
        self.st_text.textChanged.connect(self._stamp_layout_changed); self.st_pages.textChanged.connect(self._stamp_changed); self.st_color.textChanged.connect(self._stamp_changed)
        self.st_start.valueChanged.connect(self._stamp_changed); self.pdf_stage.infos_ready.connect(self._stamp_changed)
        for control in (self.st_size, self.st_wsize, self.st_opacity, self.st_margin):
            control.valueChanged.connect(self._stamp_changed)
        for chips in (self.ac_format, self.ac_quality, self.ac_tags):
            chips.currentIndexChanged.connect(self._audioconvert_changed)
        self.audio_stage.infos_ready.connect(self._audioconvert_changed)
        self.cp_level.currentIndexChanged.connect(self._pdfcompress_changed); self.pdf_stage.infos_ready.connect(self._pdfcompress_changed)
        for chips in (self.kl_meta, self.kl_attach, self.kl_js):
            chips.currentIndexChanged.connect(self._pdfclean_changed)
        self.pdf_stage.infos_ready.connect(self._pdftext_changed)
        self.org_all.clicked.connect(self.organizer.select_all); self.org_reset.clicked.connect(self.organizer.reset)
        self.pdf_stage.infos_ready.connect(self._pdfimg_changed)
        self.pdf_stage.infos_ready.connect(self._merge_changed)
        self.pdf_stage.infos_ready.connect(self._split_changed)
        self.split_mode.currentIndexChanged.connect(self._split_mode_changed)
        self.split_every.valueChanged.connect(self._split_changed)
        self.split_ranges.textChanged.connect(self._split_changed)
        self.pdfimg_dpi.valueChanged.connect(self._pdfimg_changed)
        self.pdfimg_pages.textChanged.connect(self._pdfimg_changed)
        self.resize_width.valueChanged.connect(self._resize_changed); self.resize_height.valueChanged.connect(self._resize_changed)
        self.compress_preset.currentIndexChanged.connect(self._preset_changed)
        self.quality.valueChanged.connect(self._quality_changed)
        self.width.valueChanged.connect(self._conversion_changed)
        self.rotation.currentIndexChanged.connect(self._conversion_changed)
        self.annotate_preview.position_changed.connect(self._annotation_position_picked)
        self.annotation_x.valueChanged.connect(self._annotation_spin_changed)
        self.annotation_y.valueChanged.connect(self._annotation_spin_changed)
        self.annotation.textChanged.connect(self._annotation_style_changed)
        self.annotation_size.valueChanged.connect(self._annotation_style_changed)
        self.annotation_color.textChanged.connect(self._annotation_style_changed)
        for control in (self.canvas_width, self.canvas_height):
            control.valueChanged.connect(self._canvas_changed)
        self.background.textChanged.connect(self._canvas_changed)
        for control in (self.backdrop_padding, self.backdrop_radius, self.backdrop_shadow):
            control.valueChanged.connect(self._backdrop_changed)
        self.backdrop_ratio.currentIndexChanged.connect(self._backdrop_changed)
        self.backdrop_color.textChanged.connect(self._backdrop_changed)
        for control in (self.collage_columns, self.collage_cell, self.collage_gap):
            control.valueChanged.connect(self._collage_changed)
        self.pdf_ocr.currentIndexChanged.connect(self._onepdf_ocr_changed); self.pdf_page.currentIndexChanged.connect(self._onepdf_page_changed); self.pdf_margin.valueChanged.connect(self._onepdf_changed)
        self.background.textChanged.connect(self._collage_changed)

    def _build_compatibility_controls(self):
        self.capability_label = QLabel(self); self.capability_button = QPushButton('Verificar', self)
        self.capability_button.clicked.connect(self.recheck_capabilities)
        self.clear_queue_button = QPushButton('Limpar fila', self)
        self.clear_queue_button.clicked.connect(self.clear_queue)
        self.history = QListWidget(self); self.version = QLabel(f'Experimental • {VERSION}', self)
        self.active_job_label = QLabel('Nenhuma tarefa em execução', self)
        for widget in (self.capability_label, self.capability_button, self.clear_queue_button, self.history, self.version, self.active_job_label):
            widget.hide()

    # ------------------------------------------------------------------
    # categorias e rodas
    # ------------------------------------------------------------------
    def _capability_for(self, target: str):
        if target.startswith(tool_registry.AUDIO_GROUP_PREFIX) or target in (AUDIO_INFO, AUDIO_CONVERT):
            return self.controller.capabilities.get('audio', (False, 'FFmpeg indisponível.'))
        key = 'images' if target in IMAGE_TARGETS or target.startswith(tool_registry.GROUP_PREFIX) else 'pdf'
        return self.controller.capabilities.get(key, (False, 'Dependência indisponível.'))

    def select_category(self, category: str):
        if category not in CATEGORIES:
            return
        self.active_category = category
        self.category_title.setText(CATEGORIES[category][0])
        category_available = CATEGORIES[category][2]
        self.category_help.setText('Passe o mouse sobre uma fatia e clique para abrir a ferramenta' if category in WHEEL_COLUMNS
                                   else ('Ferramentas disponíveis' if category_available else 'Em desenvolvimento · ainda não executa operações'))
        for key, button in self.category_buttons.items():
            button.setChecked(key == category)
        self._clear_layout(self.tool_grid)
        self._clear_layout(self.wheels_layout)
        if category in WHEEL_COLUMNS:
            self._build_wheels(category)
            self.category_body.setCurrentWidget(self.wheels_scroll)
        else:
            ready = [(target, label, description) for target, label, description in TOOLS.get(category, [])]
            planned = PLANNED_TOOLS.get(category, [])
            columns = 3 if self.size().width() >= 960 else 2
            for index, (target, label, description) in enumerate(ready):          # ferramentas já disponíveis (Áudio: Informações)
                card = QPushButton(f'{label}\n{description}')
                card.setObjectName('ToolCardButton'); card.setMinimumHeight(78)
                card.clicked.connect(lambda checked=False, t=target: self.select_tool(t))
                self.tool_grid.addWidget(card, index // columns, index % columns)
            offset = len(ready)
            for index, (label, description) in enumerate(planned, start=offset):
                card = QPushButton(f'{label}\n{description} · Planejado')
                card.setObjectName('ToolCardButton'); card.setMinimumHeight(78); card.setEnabled(False)
                card.setToolTip('Este recurso ainda não está disponível e não executa operações nesta versão.')
                self.tool_grid.addWidget(card, index // columns, index % columns)
            if not planned and not ready:
                empty = QLabel('Ainda não há ferramentas nesta categoria. Ela será ativada quando o respectivo motor local estiver pronto.')
                empty.setObjectName('Muted'); empty.setWordWrap(True); self.tool_grid.addWidget(empty, 0, 0)
            self.tool_grid.setRowStretch(max(1, (len(planned) + offset + columns - 1) // columns), 1)
            self.category_body.setCurrentWidget(self.tools_scroll)
        self.pages.setCurrentWidget(self.category_page)

    @staticmethod
    def _clear_layout(layout):
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()

    def _build_wheels(self, category: str):
        descriptions = {target: (label, description) for target, label, description in TOOLS[category]}
        columns = WHEEL_COLUMNS[category]
        self.wheel_widgets = []
        self.wheels_layout.addStretch(1)
        for column_index, (key_label, subtitle, targets) in enumerate(columns):
            if column_index:
                divider = QFrame(); divider.setObjectName('Divider'); self.wheels_layout.addWidget(divider)
                self.wheels_layout.addSpacing(0)
            column = QWidget(); column_layout = QVBoxLayout(column)
            column_layout.setContentsMargins(28, 6, 28, 6); column_layout.setSpacing(8)
            key = QLabel(key_label); key.setObjectName('KeyCap'); key.setAlignment(Qt.AlignmentFlag.AlignCenter)
            column_layout.addWidget(key, 0, Qt.AlignmentFlag.AlignHCenter)
            sub = QLabel(subtitle); sub.setObjectName('Muted'); sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
            column_layout.addWidget(sub)
            if targets and targets[0].startswith(tool_registry.GROUP_PREFIX):
                actions = image_tool_actions(engine_targets=True)
            elif targets and targets[0].startswith(tool_registry.PDF_GROUP_PREFIX):
                actions = pdf_tool_actions()
            elif targets and targets[0].startswith(tool_registry.AUDIO_GROUP_PREFIX):
                actions = audio_tool_actions()
            else:
                actions = [RadialAction(descriptions[target][0], target, descriptions[target][1]) for target in targets]
            enabled, reason = self._capability_for(targets[0])
            wheel = RadialWheel(actions, 'Escolha', 330, disabled=() if enabled else range(len(actions)))
            wheel.setToolTip('' if enabled else reason)
            caption = QLabel('Passe o mouse sobre uma fatia' if enabled else reason); caption.setObjectName('Caption'); caption.setAlignment(Qt.AlignmentFlag.AlignCenter); caption.setWordWrap(True)
            default_caption = caption.text()
            wheel.hovered.connect(lambda index, w=wheel, c=caption, d=default_caption: c.setText(w.actions[index].description or w.actions[index].label) if index >= 0 else c.setText(d))
            wheel.activated.connect(lambda index, w=wheel: self.select_tool(w.actions[index].target))
            wheel.dropped.connect(lambda index, paths, w=wheel: self.set_files(paths, w.actions[index].target))
            column_layout.addWidget(wheel, 0, Qt.AlignmentFlag.AlignHCenter)
            column_layout.addWidget(caption)
            column_layout.addStretch(1)
            self.wheels_layout.addWidget(column)
            self.wheel_widgets.append(wheel)
        self.wheels_layout.addStretch(1)
        QTimer.singleShot(0, self._fit_wheels)

    def _fit_wheels(self):
        """Ajusta o diâmetro das rodas ao espaço disponível, sem exigir rolagem em janelas pequenas."""
        wheels = getattr(self, 'wheel_widgets', [])
        if not wheels or self.category_body.currentWidget() is not self.wheels_scroll:
            return
        viewport = self.wheels_scroll.viewport()
        by_height = viewport.height() - 128
        by_width = viewport.width() // max(1, len(wheels)) - 70
        diameter = int(max(220, min(360, by_height, by_width)))
        for wheel in wheels:
            if wheel.diameter != diameter:
                wheel.set_diameter(diameter)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_wheels()

    # ------------------------------------------------------------------
    # ferramenta escolhida
    # ------------------------------------------------------------------
    def select_tool(self, target: str):
        self._clear_passwords()
        self._redact_reset(); self._form_reset()
        if target not in OPERATIONS and target not in READONLY_TOOLS:
            return
        self.selected_tool = target
        self.operation.blockSignals(True)
        self.operation.setCurrentIndex(self.operation.findData(target))
        self.operation.blockSignals(False)
        self.tool_title.setText(LABELS.get(target, target))
        description = next((d for tools in TOOLS.values() for t, _label, d in tools if t == target), 'Ferramenta local.')
        self.tool_description.setText(description)
        self.open_button.setEnabled(bool(self.last_output_dir))
        if self.controller.active_job is None:
            self.status.setText('Processamento local • originais preservados • sem sobrescrita silenciosa')
        self.report_card.hide()
        self._show_tool_controls(target)
        self._prepare_stage(target)
        self.pages.setCurrentWidget(self.tool_page)

    def _stage_message(self, text: str):
        self.preview_image.setText(text)
        self.stage.setCurrentIndex(STAGE_MESSAGE)

    def _load_pixmap(self, path: str):
        if self._pixmap_cache and self._pixmap_cache[0] == path:
            return self._pixmap_cache[1], self._pixmap_cache[2]
        pixmap, size = pixmap_from_image_path(path)
        self._pixmap_cache = (path, pixmap, size)
        return pixmap, size

    def _has_vector(self) -> bool:
        return any(Path(path).suffix.lower() in VECTOR_INPUTS for path in self.files)

    def _sync_vector_width(self):
        """A prévia e o job desenham o SVG na mesma largura (o worker recebe `vector_width`); sem SVG na sessão, volta ao padrão."""
        width = self.vector_width.value() if self._has_vector() else 0
        if (width or None) != engine_module.VECTOR_WIDTH:
            self._pixmap_cache = None                    # a prévia em cache foi desenhada em outra largura
        set_vector_width(width)

    def _vector_width_changed(self):
        # as posições marcadas na prévia (recorte, formas, áreas) dependem do tamanho do desenho; por isso a ferramenta recomeça
        if self.pages.currentWidget() is self.tool_page and self.selected_tool:
            self._prepare_stage(self.selected_tool)
            self._show_tool_controls(self.selected_tool)

    def _prepare_stage(self, target: str):
        self._sync_vector_width()
        self.preview_button.setVisible(target == 'Crop → PNG')
        self.redact_regions = []
        self._update_redact_help()
        self._adjust_source = None
        self._redact_source = None
        self._wm_source = None
        self._sharp_source = None
        self._lv_source = None
        self._shape_source = None
        self.shape_items = []
        self.rename_pattern.blockSignals(True); self.rename_pattern.clear(); self.rename_pattern.blockSignals(False)
        self.rename_start.blockSignals(True); self.rename_start.setValue(1); self.rename_start.blockSignals(False)
        self.rename_digits.slider.blockSignals(True); self.rename_digits.slider.setValue(1); self.rename_digits.slider.blockSignals(False); self.rename_digits._refresh()
        self._update_shape_help()
        self._rotate_pixmap = None
        if target == 'Rotate → PNG':
            self.reset_rotation()
        self.crop_preview.dim_outside = target not in ('Redact → PNG', 'Shapes → PNG')
        self.crop_preview.set_overlay(None)
        if target == 'Adjust → PNG':
            self.reset_adjustments(refresh=False)
        if target == 'Levels → PNG':
            self.reset_levels(refresh=False)
        if target == 'Shapes → PNG':
            self._syncing = True
            self.sh_kind.setCurrentIndex(0); self.sh_fill.setCurrentIndex(0); self.sh_dir.setCurrentIndex(0); self.sh_color.setText('#FF0000'); self.sh_thickness.setValue(6)
            self._syncing = False
        if target == 'Sharpen → PNG':
            self._syncing = True
            self.sharp_mode.setCurrentIndex(0); self.sharp_amount.setValue(50); self.sharp_radius.setValue(2)
            self._syncing = False
        if target == 'Clean → PNG':
            self._refresh_metadata_info()
        for control in (self.crop_x, self.crop_y, self.crop_width, self.crop_height):
            control.setValue(0)
        self.crop_help.setText('Arraste na imagem para definir a área.')
        if target in (AUDIO_INFO, AUDIO_CONVERT):
            self.file_preview.clear()
            self.pdf_stage.show_files([])
            audios = [path for path in self.files if Path(path).suffix.lower() in AUDIO_SUFFIXES or Path(path).suffix.lower() in ('.mp4', '.mkv', '.mov', '.webm')]
            if audios:
                if self.audio_stage.paths != audios:
                    self.audio_stage.show_files(audios)
                self.stage.setCurrentIndex(STAGE_AUDIO)
            else:
                self.audio_stage.show_files([])
                self._stage_message('Abra um arquivo de áudio para ver as informações.' if target == AUDIO_INFO else 'Abra um arquivo de áudio ou vídeo para converter.')
            return
        if target not in IMAGE_TARGETS:
            self.file_preview.clear()
            pdfs = [path for path in self.files if Path(path).suffix.lower() == '.pdf']
            if target == PDF_FORM:
                self.pdf_stage.show_files([])
                if len(pdfs) == 1 and len(self.files) == 1:
                    if self.form_stage.paths != [pdfs[0]]:
                        self.form_stage.show_files(pdfs)
                    self.stage.setCurrentIndex(STAGE_FORM)
                else:
                    self.form_stage.show_files([])
                    self._stage_message('Preencher e assinar trabalha com um PDF por vez. Escolha apenas um.' if self.files else 'Abra um PDF para continuar.')
                self._form_infos()
                return
            if target == PDF_REDACT:
                self.pdf_stage.show_files([])
                if len(pdfs) == 1 and len(self.files) == 1:
                    if self.redact_stage.paths != [pdfs[0]]:
                        self.redact_stage.show_files(pdfs)
                    self.stage.setCurrentIndex(STAGE_REDACT)
                else:
                    self.redact_stage.show_files([])
                    self._stage_message('Tarjar trabalha com um PDF por vez. Escolha apenas um.' if self.files else 'Abra um PDF para continuar.')
                self._redact_changed()
                return
            if target == 'Organize PDF':
                self.pdf_stage.show_files([])
                if len(pdfs) == 1 and len(self.files) == 1:
                    if self.organizer.path != pdfs[0]:
                        self.organizer.load(pdfs[0])
                    self.stage.setCurrentIndex(STAGE_ORGANIZE)
                else:
                    self.organizer.clear()
                    self._stage_message('Organizar páginas trabalha com um PDF por vez. Escolha apenas um.' if self.files else 'Abra um PDF para continuar.')
                self._organize_changed()
                return
            if self.organizer.path:
                self.organizer.clear()
            self.pdf_stage.hide_list = target == 'Merge PDFs'
            if pdfs:
                self.pdf_stage.show_files(pdfs)
                self.stage.setCurrentIndex(STAGE_PDF)
                if target == 'Merge PDFs':
                    self._merge_changed()
            else:
                self.pdf_stage.show_files([])
                self._stage_message('Abra um ou mais PDFs para continuar.')
            return
        self._pil_image = None
        if not self.files:
            self.crop_image_size = (0, 0)
            self._stage_message('Abra uma imagem para ver a prévia.')
            return
        if target in ORDERED_TARGETS:
            self.crop_image_size = (0, 0)
            self._ordered_changed()
            return
        if target == 'Shapes → PNG' and len(self.files) != 1:
            self.crop_image_size = (0, 0)
            self._stage_message('Formas trabalha com uma imagem por vez, porque cada forma depende da posição na imagem. Escolha apenas uma.')
            return
        if target == 'Redact → PNG' and len(self.files) != 1:
            self.crop_image_size = (0, 0)
            self._stage_message('Ocultar trabalha com uma imagem por vez, porque as áreas dependem da posição na imagem. Escolha apenas uma.')
            return
        if len(self.files) != 1:
            self.crop_image_size = (0, 0)
            self._stage_message(f'{len(self.files)} imagens selecionadas. A prévia visual aparece quando há apenas uma; a operação será aplicada a cada arquivo.')
            self._resize_changed()
            return
        try:
            pixmap, size = self._load_pixmap(self.files[0])
        except Exception as error:
            self.crop_image_size = (0, 0)
            self._stage_message('Prévia indisponível: ' + str(error)[:180])
            return
        self.crop_image_size = size
        if target in ('Crop → PNG', 'Redact → PNG', 'Shapes → PNG'):
            self.crop_aspect.blockSignals(True); self.crop_aspect.setCurrentIndex(0); self.crop_aspect.blockSignals(False)
            self.crop_preview.set_aspect(None)
            self.crop_preview.set_preview_pixmap(pixmap)
            self.stage.setCurrentIndex(STAGE_CROP)
            if target == 'Shapes → PNG':
                self._syncing = True; self.sh_thickness.setValue(max(2, min(200, round(min(size) / 150)))); self._syncing = False
                self.tool_hint.setText('Escolha a forma, arraste sobre a imagem e clique em “Adicionar forma”. Repita para desenhar outras.')
        elif target == 'Annotate → PNG':
            self.annotate_preview.set_preview_pixmap(pixmap)
            for spin in (self.annotation_x, self.annotation_y):
                spin.setMaximum(max(0, (size[0] if spin is self.annotation_x else size[1]) - 1))
            self._syncing = True
            self.annotation_x.setValue(0); self.annotation_y.setValue(0)
            self.annotation_size.setValue(max(18, min(400, round(size[1] / 18))))
            self._syncing = False
            self._annotation_style_changed()
            self.tool_hint.setText('Clique ou arraste sobre a imagem para posicionar o texto. A anotação fica incorporada aos pixels do arquivo novo.')
            self.stage.setCurrentIndex(STAGE_ANNOTATE)
        elif target == 'Adjust → PNG':
            self._adjust_changed()
        elif target == 'Levels → PNG':
            self.static_preview.set_preview_pixmap(pixmap)
            self.static_preview.set_rotation(0)
            self.stage.setCurrentIndex(STAGE_STATIC)
            self._levels_changed()
        elif target == 'Sharpen → PNG':
            self.static_preview.set_preview_pixmap(pixmap)
            self.static_preview.set_rotation(0)
            self.stage.setCurrentIndex(STAGE_STATIC)
            self._sharpen_changed()
        elif target == 'Watermark → PNG':
            self.static_preview.set_preview_pixmap(pixmap)
            self.static_preview.set_rotation(0)
            self.stage.setCurrentIndex(STAGE_STATIC)
            self._watermark_changed()
        elif target == 'Rotate → PNG':
            self._rotate_pixmap = pixmap
            self.static_preview.set_preview_pixmap(pixmap)
            self.static_preview.set_rotation(0)
            self.stage.setCurrentIndex(STAGE_STATIC)
            self._rotate_changed()
        elif target == 'Resize → PNG':
            self.static_preview.set_preview_pixmap(pixmap)
            self.static_preview.set_rotation(0)
            self.stage.setCurrentIndex(STAGE_STATIC)
            self._syncing = True
            self.resize_width.setValue(max(1, size[0] // 2)); self.resize_height.setValue(max(1, size[1] // 2))
            self._syncing = False
            self._resize_changed()
        elif target == 'Backdrop → PNG':
            self._syncing = True
            self.backdrop_padding.setValue(min(600, round(max(size) * 0.08)))
            self.backdrop_radius.setValue(min(300, round(min(size) * 0.03)))
            self._syncing = False
            self._backdrop_changed()
        elif target == 'Canvas → PNG':
            self.canvas_preview.set_preview_pixmap(pixmap)
            self._syncing = True
            self.canvas_width.setValue(min(10000, round(size[0] * 1.2))); self.canvas_height.setValue(min(10000, round(size[1] * 1.2)))
            self._syncing = False
            self._canvas_changed()
            self.stage.setCurrentIndex(STAGE_CANVAS)
        else:
            self.static_preview.set_preview_pixmap(pixmap)
            self.stage.setCurrentIndex(STAGE_STATIC)
            self._conversion_changed()
            if target == 'Compress → JPEG':
                self._load_estimate_source()

    # --- nome do arquivo novo --------------------------------------------
    @staticmethod
    def _renameable(target: str) -> bool:
        return target in RENAMEABLE_TARGETS or target in ORDERED_TARGETS

    def _rename_extension(self, target: str) -> str:
        if target in ('Image → PDF', ONEPDF):
            return 'pdf'
        if target in tool_registry.FORMAT_TARGETS:
            return OUTPUT_FORMATS[self._output_format_values()[0]][1]
        return IMAGE_OUTPUTS.get(target, 'png')

    def _rename_values(self) -> dict:
        return {'rename_pattern': self.rename_pattern.text().strip(), 'rename_start': self.rename_start.value(), 'rename_digits': self.rename_digits.value()}

    def _folder_mode(self, target=None) -> bool:
        """True quando a conversão vai para a pasta numerada: ferramenta de um arquivo por imagem, 2 ou mais arquivos e a caixa marcada."""
        target = target or self.selected_tool
        return bool(target) and target in RENAMEABLE_TARGETS and target not in ORDERED_TARGETS and len(self.files) > 1 and self.to_folder.isChecked()

    def _rename_changed(self, _value=None, force=False):
        target = self.selected_tool
        if not target or not self._renameable(target):
            return
        if force or self.settings_form.isRowVisible(self.rename_start) != ('{n}' in self.rename_pattern.text() or self._folder_mode(target)):
            self._show_tool_controls(target)               # já atualiza o exemplo
            return
        self._update_rename_example()

    def _update_rename_example(self):
        target = self.selected_tool
        if not target or not self._renameable(target):
            return
        values = self._rename_values()
        if self._folder_mode(target):
            try:
                batch = batch_rename_options({**values, 'rename_pattern': values['rename_pattern']}, len(self.files))
                options = rename_options_from(batch)
                ext = self._rename_extension(target)
                names = [rename_stem({**options, 'n': options['start'] + index}, Path(path).stem, TOOL_SUFFIX.get(target, 'converted')) + '.' + ext for index, path in enumerate(self.files[:2])]
                self.rename_example.setText('Pasta «Convertidas …»: ' + ' · '.join(names) + ' …')
            except ConversionError as error:
                self.rename_example.setText('Padrão inválido: ' + str(error))
            return
        if not values['rename_pattern']:
            self.rename_example.setText('Nome padrão: o original + o sufixo da ferramenta.')
            return
        try:
            options = rename_options_from(values)
            suffix = TOOL_SUFFIX.get(target, 'converted'); ext = self._rename_extension(target)
            if target in ORDERED_TARGETS:
                base = 'imagens' if target == ONEPDF else 'colagem'
                names = [rename_stem({**options, 'n': options['start']}, base, base) + '.' + ext]
            else:
                names = [rename_stem({**options, 'n': options['start'] + index}, Path(path).stem, suffix) + '.' + ext for index, path in enumerate(self.files[:2])]
                if not names:
                    names = [rename_stem({**options, 'n': options['start']}, 'imagem', suffix) + '.' + ext]
            text = ' · '.join(names) + (' …' if len(self.files) > 2 and target not in ORDERED_TARGETS else '')
            if len(self.files) > 1 and target not in ORDERED_TARGETS and '{n}' not in values['rename_pattern'] and '{nome}' not in values['rename_pattern']:
                text += '\nSem {n} nem {nome}, nomes repetidos ganham -2, -3…'
            self.rename_example.setText(text)
        except ConversionError as error:
            self.rename_example.setText('Padrão inválido: ' + str(error))

    def _run_text(self, target: str) -> str:
        """Texto do botão com o formato escolhido (ex.: «Recortar e salvar WebP»)."""
        if target == tool_registry.PDF_IMAGES:
            return 'Salvar páginas como ' + OUTPUT_FORMATS[self._output_format_values()[0]][2]
        text = tool_registry.BY_TARGET[target].run_label
        if text.endswith(' PNG'):
            text = text[:-4] + ' ' + OUTPUT_FORMATS[self._output_format_values()[0]][2]
        return text

    def _show_tool_controls(self, target: str):
        visible = {
            'JPEG': ('width', 'rotation', 'quality'), 'Compress → JPEG': ('preset', 'quality'),
            'PNG': ('width', 'rotation'), 'WEBP': ('width', 'rotation'), 'TIFF': ('width', 'rotation'), 'BMP': ('width', 'rotation'),
            'Image → PDF': ('width', 'rotation'), 'Crop → PNG': ('crop_aspect', 'crop', 'crop_clear'),
            'Canvas → PNG': ('canvas_w', 'canvas_h', 'background'),
            'Collage → PNG': ('clist', 'cbuttons', 'ccols', 'ccell', 'cgap', 'background'),
            'Images → One PDF': ('clist', 'cbuttons', 'ppage', *(('pmargin',) if self.pdf_page.currentIndex() > 0 else ()), 'pocr', *(() if self.pdf_ocr.currentIndex() > 0 else ('quality',))),
            'Backdrop → PNG': ('bswatch', *(('bcustom',) if self.backdrop_style == 'custom' else ()), 'bpad', 'bradius', 'bshadow', 'bratio'),
            'Annotate → PNG': ('text', 'asize', 'ax', 'ay', 'acolor'),
            'Adjust → PNG': ('abright', 'acontrast', 'asat', 'aflip', 'areset'),
            'Rotate → PNG': ('gangle', 'gflip', 'ginfo'),
            'Levels → PNG': ('lmode', 'lhist', *(('lblack', 'lwhite') if self.lv_mode.currentIndex() == 0 else ()), 'lgamma', 'lreset'),
            'Remove Background → PNG': ('bmodel', 'bfeather', 'bpreview', 'bstatus'),
            'Sharpen → PNG': ('smode', *(('samount',) if self.sharp_mode.currentIndex() == 0 else ()), 'sradius'),
            'Watermark → PNG': ('wkind', *(('wtext', 'wcolor') if self.wm_kind.currentIndex() == 0 else ('wimage',)), 'wscale', 'wopacity', 'wpos', *(('wmargin',) if self.wm_position.currentIndex() < 9 else ())),
            'Resize → PNG': ('zmode', *(('zpercent',) if self.resize_mode.currentIndex() == 0 else ('zwidth', 'zheight')), 'zinfo'),
            'Clean → PNG': ('minfo',),
            'OCR → Text': ('olang', 'opsm', 'ostatus'), 'OCR → PDF': ('olang', 'opsm', 'ostatus'),
            'Shapes → PNG': ('hkind', 'hcolor', 'hthick', *(('hfill',) if self.sh_kind.currentIndex() < 2 else ('hdir',)), 'hhelp', 'hbuttons'),
            'PDF → Text': ('tmode', 'tlayout', 'tpages', 'tinfo'),
            'Extract PDF Images': ('epages', 'emin', 'einfo'),
            PDF_PROTECT: ('pwpass', 'pwrepeat', 'pwprint', 'pwcopy', 'pwedit', 'pwowner', 'pwinfo'),
            PDF_UNPROTECT: ('pwcurrent', 'pwinfo'),
            PDF_STAMP: self._stamp_fields(),
            PDF_FORM: ('fmfields', 'fmflat', 'fmimage', 'fmhelp', 'fmbuttons', 'fminfo'),
            PDF_REDACT: ('rdhelp', 'rdbuttons', 'rdterms', 'rdpresets', 'rddpi', 'rdinfo'),
            PDF_COMPRESS: ('plevel', 'pinfo'),
            AUDIO_CONVERT: ('aformat', 'aquality', 'atags', 'ainfo'),
            PDF_CLEAN: ('kdetails', 'kmeta', 'kattach', 'kjs', 'kinfo'),
            PDF_OCR_PDF: ('olang', 'opsm', 'rpages', 'rskip', 'rinfo', 'ostatus'),
            PDF_OCR_TEXT: ('olang', 'opsm', 'rpages', 'rskip', 'rtext', 'rinfo', 'ostatus'),
            'Organize PDF': ('qbuttons', 'qinfo'),
            'Split PDF': ('xmode', *(('xevery',) if self.split_mode.currentIndex() == 1 else ('xranges',) if self.split_mode.currentIndex() >= 2 else ()), 'xinfo'),
            'Merge PDFs': ('clist', 'cbuttons', 'mpages', 'mtotal'),
            'PDF → Images': ('pimgdpi', 'pimgpages', 'pimginfo'),
            'Redact → PNG': ('rmode', *(('rblock',) if self.redact_mode.currentIndex() == 1 else ()), 'rhelp', 'rbuttons'),
        }.get(target, ())
        if target in tool_registry.FORMAT_TARGETS:
            index = max(0, self.out_format.currentIndex())          # 0 PNG, 1 JPEG, 2 WebP, 3 TIFF, 4 BMP, 5 GIF, 6 ICO, 7 AVIF, 8 HEIC
            visible = (*visible, 'ofmt', *(('oqual',) if index in (1, 2, 7, 8) else ()), *(('oflat',) if index in (1, 4) else ()))
        if self._has_vector():
            visible = (*visible, 'vwidth')
        if self._renameable(target):
            folder_mode = self._folder_mode(target)
            visible = (*visible, *(('nfolder',) if target in RENAMEABLE_TARGETS and target not in ORDERED_TARGETS and len(self.files) > 1 else ()), 'nname', 'nexample', *(('nstart',) if folder_mode else ()), *(('nstart', 'ndigits') if '{n}' in self.rename_pattern.text() and not folder_mode else ()), *(('ndigits',) if folder_mode and '{n}' in self.rename_pattern.text() else ()))
        self.run_button.setEnabled(True)
        self.run_button.setVisible(target not in READONLY_TOOLS)          # ferramentas de leitura não têm o que aplicar nem pasta de resultado
        self.open_button.setVisible(target not in READONLY_TOOLS)
        for key, widget in self.form_fields.items():
            shown = key in visible
            self.settings_form.setRowVisible(widget, shown)
            widget.setEnabled(shown)
        for control in (self.crop_x, self.crop_y, self.crop_width, self.crop_height):
            control.setEnabled(target == 'Crop → PNG')
        hints = {
            'Crop → PNG': 'Arraste sobre a imagem para marcar a área. Use as alças para ajustar e o interior para mover.',
            'Watermark → PNG': 'Escreva um texto ou escolha um logotipo e ajuste tamanho, opacidade e posição; a prévia mostra o resultado. A marca é gravada nos pixels do arquivo novo e não pode ser removida depois. Com várias imagens, a mesma marca vai em todas (a prévia aparece quando há uma).',
            'Levels → PNG': 'Arraste «Preto» e «Branco» até a borda do histograma para dar mais contraste; «Tons médios» clareia ou escurece sem mexer nos extremos. «Automático» calcula os pontos de cada imagem (descarta 0,5 % de cada ponta) e vale também para vários arquivos. Tons fora dos pontos viram preto ou branco puro. Gera um arquivo novo; o original não muda.',
            'Sharpen → PNG': 'Nitidez realça as bordas; Desfoque suaviza. O raio é proporcional ao tamanho da imagem, então a prévia mostra o mesmo efeito do resultado. É gravado nos pixels de um arquivo novo e não dá para desfazer; o original não muda. Nitidez em excesso cria halos e realça ruído.',
            'Rotate → PNG': 'Escolha o giro e, se quiser, o espelhamento (aplicado depois do giro). Os pixels só mudam de lugar: não há perda de qualidade. Gera um arquivo novo no formato escolhido; o original não muda. Com várias imagens, a mesma regra vale para todas.',
            'Resize → PNG': 'Porcentagem muda tudo na mesma escala; “Caber em” mantém a proporção dentro da largura e da altura (deixe um deles em “Sem limite”); “Medida exata” pode esticar a imagem. Gera um arquivo novo no formato escolhido; o original não muda. Ampliar não cria detalhe.',
            'Adjust → PNG': 'Mova os controles para ver o resultado na prévia. Os ajustes são gravados nos pixels de um arquivo novo; o original não muda. Com várias imagens, os mesmos ajustes valem para todas.',
            'Remove Background → PNG': 'Apaga o fundo e deixa só o objeto principal, com transparência, em um PNG novo; tudo é feito no seu computador, sem internet. Confira o resultado: cabelos finos, vidro, sombras e imagens com vários objetos podem sair errados. «Leve» é rápido; «Preciso» exige colocar o arquivo u2net.onnx na pasta «models». «Borda suave» esconde o serrilhado. O original não muda.',
            'OCR → Text': 'Reconhece o texto da imagem no seu computador, sem internet, e salva um arquivo .txt novo. Escolha o idioma e, se for só um trecho, o modo de página. Confira o resultado: o OCR erra em letras manuscritas, imagens borradas e tabelas. O original não muda.',
            'OCR → PDF': 'Reconhece o texto no seu computador, sem internet, e salva um PDF novo com a imagem e o texto invisível por baixo, para buscar e copiar. Confira o resultado. Cada imagem gera um PDF de uma página; o original não muda.',
            'Clean → PNG': 'A cópia mantém o perfil de cor e deixa de fora EXIF, GPS, XMP e comentários; em PNG, TIFF, BMP e WebP 100 % os pixels ficam idênticos, em JPEG não. O original não é alterado.',
            'Shapes → PNG': 'Escolha a forma, a cor e a espessura, arraste sobre a imagem e clique em “Adicionar forma”; repita para desenhar outras (até 50). Linha e seta vão de um canto da área ao canto oposto, no sentido da «Direção»; área muito achatada vira reta. As formas são gravadas nos pixels do arquivo novo, na ordem em que foram adicionadas; o original não muda.',
            'Redact → PNG': 'Arraste sobre a imagem, clique em “Adicionar área” e repita. A tarja ou pixelização é gravada nos pixels do arquivo novo; o original não muda. A prévia mostra o efeito (aproximado) já aplicado.',
            'Canvas → PNG': 'O canvas precisa ser maior ou igual à imagem. A imagem fica centralizada sobre a cor escolhida.',
            'Backdrop → PNG': 'Escolha o fundo e ajuste margem, cantos e sombra. O resultado é uma imagem nova; a prévia aproxima a sombra.',
            'Images → One PDF': 'Cada imagem vira uma página, na ordem da lista (use Subir, Descer e Tirar). «Imagem» deixa cada página do tamanho da imagem; A4 e Carta usam a orientação da imagem, margem e ajuste à área útil (pode ampliar). As páginas são imagens a 150 dpi em JPEG: há perda de qualidade e o texto não fica selecionável.',
            'Collage → PNG': 'As imagens entram na ordem da lista (use Subir, Descer e Tirar), cada uma inteira dentro da sua célula quadrada. A prévia mostra miniaturas.',
            'Compress → JPEG': 'JPEG perde detalhes: quanto menor a qualidade, menor tende a ser o arquivo e maior a perda visual.',
            'PDF → Text': 'O texto é extraído sem OCR, no seu computador. Escolha um arquivo só, com marcas «--- Página N ---» ou um arquivo por página (numerados numa pasta nova). PDFs digitalizados não têm texto: nesse caso nada é salvo. Colunas e tabelas podem sair misturadas; confira o resultado. O original não muda.',
            PDF_PROTECT: 'Cria «<nome>-protegido.pdf», que só abre com a senha (criptografia AES-256). A senha não é guardada em lugar nenhum: se você a perder, o conteúdo não pode ser recuperado. Para impedir impressão, cópia ou edição defina também uma senha de permissões diferente; essas restrições só valem em programas que as respeitam. O original não muda.',
            PDF_UNPROTECT: 'Cria «<nome>-desprotegido.pdf», uma cópia que abre sem senha. Você precisa informar a senha: o Arquivo Local não adivinha nem quebra senhas. Se o PDF tiver restrições de impressão, cópia ou edição, só a senha de permissões (proprietário) permite remover a proteção. Use só em documentos seus ou que você pode usar. O original não muda.',
            PDF_FORM: 'Preencha os campos do formulário (texto, caixas, opções e listas), se o PDF tiver, e/ou coloque uma imagem de assinatura na página. «Achatar» fixa os valores e remove os campos. A imagem NÃO é assinatura digital certificada: não tem certificado nem prova de autoria. Gera «<nome>-preenchido.pdf»; o original não muda.',
            PDF_REDACT: 'Cobre de verdade o que precisa sumir: as páginas afetadas viram imagem com tarjas pretas, então o texto sob a tarja deixa de existir no arquivo (e a página perde o texto selecionável). Marque áreas na página e/ou informe termos e padrões (CPF, CNPJ, e-mail, telefone), que só são achados em PDF com texto real. Marcadores, anexos, formulários e metadados são removidos, e o resultado é conferido automaticamente. Gera «<nome>-tarjado.pdf»; o original não muda. Confira o resultado antes de compartilhar.',
            PDF_STAMP: 'Escreve o número da página, um texto de cabeçalho/rodapé ou uma marca d\'água nas páginas escolhidas, como texto vetorial por cima do conteúdo (selecionável, quase sem aumentar o arquivo). {n} e {total} viram o número e o total. Gera «<nome>-numerado.pdf» (ou «-carimbado», «-marcadagua»); o original não muda. A marca d\'água não protege o conteúdo: dá para removê-la editando o PDF. Assinaturas digitais ficam inválidas.',
            PDF_COMPRESS: 'Reduz imagens grandes demais para a página (Leve: até 300 dpi · Médio: 150 dpi · Forte: 96 dpi) e recodifica em JPEG; o resto do arquivo não muda. Gera «<nome>-comprimido.pdf» só se ficar pelo menos 1 % menor; o original não muda. Fotos perdem qualidade e texto pequeno em páginas digitalizadas perde nitidez; assinaturas digitais ficam inválidas.',
            PDF_CLEAN: 'Mostra o que o PDF guarda além das páginas: autor, programa, datas, XMP, anexos e scripts. A cópia limpa, «<nome>-limpo.pdf», remove o que você marcar; texto, imagens e páginas ficam iguais e o original não muda. Não remove metadados dentro de imagens (EXIF) e invalida assinaturas digitais. Confira o resultado antes de enviar.',
            PDF_OCR_PDF: f'Para PDFs digitalizados (páginas que são fotos). Cada página escolhida é reconhecida no seu computador, sem internet, e vira imagem com o texto invisível por baixo: o PDF novo, «<nome>-pesquisavel.pdf», fica pesquisável e copiável. Páginas que já têm texto são puladas. Até {PDF_OCR_MAX_PAGES} páginas por vez. O OCR erra: confira. Marcadores, anexos, formulários e assinaturas não são preservados. O original não muda.',
            PDF_OCR_TEXT: f'Reconhece o texto de um PDF digitalizado no seu computador, sem internet, e salva em .txt («<nome>-ocr.txt», ou um arquivo por página numa pasta nova). Páginas que já têm texto usam o texto existente. Até {PDF_OCR_MAX_PAGES} páginas por vez. Colunas e tabelas podem sair misturadas; confira. O original não muda.',
            'Extract PDF Images': 'Copia as imagens embutidas no PDF: JPEG e JPEG 2000 saem como estão, sem perda; as outras viram PNG. Vão numeradas para uma pasta nova «<nome> - imagens». A mesma imagem repetida em várias páginas sai uma vez; ícones e filetes menores que o tamanho mínimo são ignorados. Para uma página digitalizada inteira, use «Páginas em imagens».',
            'PDF → Images': 'Cada página vira uma imagem numerada («pagina-001») numa pasta nova ao lado do PDF. Resolução maior dá mais nitidez e arquivos bem maiores (limite de 40 megapixels por página). Texto e desenhos viram pixels; formulários e anotações não são desenhados. O PDF original não muda.',
            'Split PDF': 'Escolha como dividir: uma página por PDF, partes de N páginas, grupos de páginas (1-3; 4-6; 7-) ou extrair só algumas páginas para um PDF novo. Várias partes vão numeradas para uma pasta nova ao lado do original, que não muda. Anexos, formulários e assinaturas não são preservados.',
            'Organize PDF': 'Arraste as miniaturas para mudar a ordem; selecione uma ou várias (Ctrl ou Shift) para girar, duplicar, mover ou excluir. O resultado é um PDF novo, «<nome>-organizado.pdf»; o original não muda. Marcadores, anexos, formulários e assinaturas não são preservados.',
            AUDIO_CONVERT: 'Converte a primeira faixa de áudio (ou o áudio de um vídeo) para MP3, M4A, FLAC, OGG, Opus, WAV ou AIFF, sem internet. A qualidade vale só para os formatos com perda (MP3, M4A, OGG, Opus). Gera «<nome>-convertido» ao lado do original, que fica intacto.',
            AUDIO_INFO: 'Mostra o que o arquivo de áudio contém: duração, codec, taxa de amostragem, canais, taxa de bits, etiquetas e capa. É só leitura: nada é gravado nem alterado. A leitura é feita no seu computador, sem internet; a extensão do arquivo não decide o formato. Por enquanto o limite é de 100 MiB por arquivo.',
            'Merge PDFs': 'Os PDFs são unidos na ordem da lista (arraste ou use Subir e Descer). Para usar só parte de um arquivo, selecione-o e escreva as páginas, como 1-3,7. Cada arquivo ganha um marcador com o nome dele; formulários, anexos e assinaturas não são preservados. Os originais não mudam.',
        }
        self.tool_hint.setText(hints.get(target, 'A operação cria um novo arquivo; o original fica intacto.'))
        self.run_button.setText(self._run_text(target) if target in tool_registry.FORMAT_TARGETS else {**{spec.target: spec.run_label for spec in tool_registry.IMAGE_TOOLS},
                                 'PDF → Text': 'Extrair texto', 'Extract PDF Images': 'Extrair imagens', PDF_PROTECT: 'Proteger com senha', PDF_UNPROTECT: 'Remover senha', PDF_STAMP: 'Aplicar carimbo', PDF_REDACT: 'Tarjar PDF', PDF_FORM: 'Gerar PDF preenchido', PDF_COMPRESS: 'Comprimir PDF', AUDIO_CONVERT: 'Converter áudio', PDF_CLEAN: 'Gerar cópia limpa', PDF_OCR_PDF: 'Gerar PDF pesquisável', PDF_OCR_TEXT: 'Reconhecer texto', 'Split PDF': 'Dividir PDF', 'Organize PDF': 'Salvar PDF organizado', 'Merge PDFs': 'Unir PDFs'}.get(target, 'Converter'))
        if target == 'Split PDF':
            self._split_changed()
        if target == 'Organize PDF':
            self._organize_changed()
        if target in ('PDF → Text', 'Extract PDF Images'):
            self._pdftext_changed()
        if target == 'PDF → Images':
            self.pdfimg_info.setText(self._pdfimg_summary())
            self.run_button.setEnabled(not self._pdfimg_problem())
        if target in OCR_TARGETS:
            ready, message = ocr.status()
            self.ocr_status.setText(message if not ready else '')
            self.run_button.setEnabled(ready)
        if target in PDF_OCR_TARGETS:
            self._pdfocr_changed()
        if target == PDF_CLEAN:
            self._pdfclean_changed()
        if target == PDF_COMPRESS:
            self._pdfcompress_changed()
        if target == AUDIO_CONVERT:
            self._audioconvert_changed()
        if target == PDF_STAMP:
            self._stamp_changed()
        if target == PDF_REDACT:
            self._redact_changed()
        if target == PDF_FORM:
            self._form_changed()
        if target in (PDF_PROTECT, PDF_UNPROTECT):
            self._password_changed()
        if target == BG_TARGET:
            ready, message = bgremove.status(self._bg_values()['bg_model'])
            self.bg_status.setText(message if not ready else '')
            self.run_button.setEnabled(ready)
        self._update_rename_example()

    # --- sincronização entre prévias e campos ---------------------------
    def _crop_selection_changed(self):
        box = selection_to_image_box(self.crop_preview, self.crop_image_size)
        if box is None:
            for control in (self.crop_x, self.crop_y, self.crop_width, self.crop_height):
                control.setValue(0)
            self.crop_help.setText('Arraste na imagem para definir a área.')
            self._redact_preview(None)
            self._shapes_preview(None)
            return
        x, y, width, height = box
        self.crop_x.setValue(x); self.crop_y.setValue(y); self.crop_width.setValue(width); self.crop_height.setValue(height)
        self.crop_help.setText(f'{width} × {height} px, a partir de ({x}, {y}). Ajuste pelas alças.')
        if self.selected_tool == 'Shapes → PNG':
            self._shapes_preview(box)
            self.status.setText('Forma desenhada. Clique em “Adicionar forma” para confirmá-la.')
        elif self.selected_tool == 'Redact → PNG':
            self._redact_preview(box)
            self.status.setText('Área marcada. Clique em “Adicionar área” para confirmá-la.')
        else:
            self.status.setText('Área selecionada. Clique em “Recortar e salvar” para criar um novo arquivo.')

    # --- ajustes de imagem ---------------------------------------------
    # --- marca d'água ----------------------------------------------------
    def _watermark_values(self) -> dict:
        return {'watermark_kind': 'text' if self.wm_kind.currentIndex() == 0 else 'image', 'watermark_text': self.wm_text.text(), 'watermark_image': self.wm_image_path.text(),
                'watermark_color': self.wm_color.text(), 'watermark_scale': self.wm_scale.value(), 'watermark_opacity': self.wm_opacity.value(),
                'watermark_margin': self.wm_margin.value(), 'watermark_position': WATERMARK_POSITIONS[max(0, min(9, self.wm_position.currentIndex()))]}

    def _watermark_kind_changed(self, _index=None):
        if self.selected_tool == 'Watermark → PNG':
            self._show_tool_controls('Watermark → PNG')
            self._watermark_changed()

    def _watermark_position_changed(self, _index=None):
        if self.selected_tool == 'Watermark → PNG':
            self._show_tool_controls('Watermark → PNG')
            self._watermark_changed()

    def choose_watermark_image(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Escolher a imagem da marca', '', 'Imagens (*.png *.jpg *.jpeg *.webp *.tif *.tiff *.bmp *.avif *.svg *.svgz *.ai *.emf *.wmf *.heic *.heif *.hif)')
        if path:
            self.wm_image_path.setText(QDir.toNativeSeparators(path))
            self._wm_logo = None
            self._watermark_changed()

    def _watermark_logo(self):
        path = self.wm_image_path.text()
        if not path:
            return None
        if self._wm_logo is None or self._wm_logo_path != path:
            self._wm_logo = open_image(source_file(path)); self._wm_logo_path = path
        return self._wm_logo

    def _watermark_changed(self, _value=None):
        if self.selected_tool != 'Watermark → PNG' or getattr(self, '_syncing', False) or not self.files:
            return
        if len(self.files) != 1 or not self.crop_image_size[0]:
            return
        values = self._watermark_values()
        try:
            if self._wm_source is None:
                from PIL import Image
                source = open_image(source_file(self.files[0]))
                source.thumbnail((900, 900), Image.Resampling.LANCZOS)
                self._wm_source = source
            from PIL.ImageQt import ImageQt
            options = watermark_options_from(values, strict=False)
            ready = bool(options['text']) if options['kind'] == 'text' else bool(options['image'])
            preview = watermark_image(self._wm_source, options, self._watermark_logo()) if ready else self._wm_source.convert('RGBA')
            self.static_preview.set_preview_pixmap(QPixmap.fromImage(QImage(ImageQt(preview))))
            preview.close()
            self.tool_hint.setText('Ajuste a marca; a prévia mostra o resultado.' if ready else ('Digite o texto da marca.' if options['kind'] == 'text' else 'Escolha a imagem da marca.'))
        except (ConversionError, OSError, ValueError) as error:
            self.tool_hint.setText('Prévia indisponível: ' + str(error)[:160])
            return
        self.stage.setCurrentIndex(STAGE_STATIC)

    def _levels_values(self) -> dict:
        return {'levels_auto': self.lv_mode.currentIndex(), 'levels_black': self.lv_black.value(), 'levels_white': self.lv_white.value(), 'levels_gamma': self.lv_gamma.value()}

    def reset_levels(self, refresh=True):
        self._syncing = True
        self.lv_mode.setCurrentIndex(0); self.lv_black.setValue(0); self.lv_white.setValue(255); self.lv_gamma.setValue(100)
        self._syncing = False
        if self.selected_tool == 'Levels → PNG':
            self._show_tool_controls('Levels → PNG')
        if refresh:
            self._levels_changed()

    def _levels_mode_changed(self, _index=None):
        if self.selected_tool == 'Levels → PNG':
            self._show_tool_controls('Levels → PNG')
            self._levels_changed()

    def _levels_black_changed(self, value):
        if not getattr(self, '_syncing', False) and value >= self.lv_white.value():
            self._syncing = True; self.lv_white.setValue(min(255, value + 1)); self._syncing = False
        self._levels_changed()

    def _levels_white_changed(self, value):
        if not getattr(self, '_syncing', False) and value <= self.lv_black.value():
            self._syncing = True; self.lv_black.setValue(max(0, value - 1)); self._syncing = False
        self._levels_changed()

    def _levels_changed(self, _value=None):
        if self.selected_tool != 'Levels → PNG' or getattr(self, '_syncing', False) or not self.files:
            return
        values = self._levels_values()
        identity = (values['levels_black'], values['levels_white'], values['levels_gamma']) == (0, 255, 100)
        self.run_button.setEnabled(bool(values['levels_auto']) or not identity)
        if len(self.files) != 1 or not self.crop_image_size[0]:
            self.lv_hist.set_histogram(None)
            return
        try:
            if self._lv_source is None:
                from PIL import Image
                source = open_image(source_file(self.files[0]))
                source.thumbnail((900, 900), Image.Resampling.LANCZOS)
                self._lv_source = source
                self.lv_hist.set_histogram(luminance_histogram(source))
            from PIL.ImageQt import ImageQt
            opts = levels_options_from(values, strict=False)
            black, white, gamma = levels_resolve(self._lv_source, opts)
            self.lv_hist.set_marks(black, white, gamma)
            preview = levels_image(self._lv_source, opts)
            self.static_preview.set_preview_pixmap(QPixmap.fromImage(QImage(ImageQt(preview))))
            preview.close()
        except (ConversionError, OSError, ValueError) as error:
            self.tool_hint.setText('Prévia indisponível: ' + str(error)[:160])
            return
        self.stage.setCurrentIndex(STAGE_STATIC)
        if opts['auto']:
            self.tool_hint.setText(f'Automático: preto em {black} e branco em {white} nesta imagem.')
        else:
            self.tool_hint.setText('Mova os controles; a prévia mostra o resultado.' if not identity else 'Nenhum ajuste ainda: mova um controle ou escolha Automático.')

    def _bg_preview(self):
        """Mostra o resultado da remoção de fundo (imagem reduzida a 1000 px, sobre um xadrez) para escolher modelo e borda antes de salvar."""
        if self.selected_tool != BG_TARGET or not self.files:
            return
        from PIL import Image
        from PIL.ImageQt import ImageQt
        ready, message = bgremove.status(self._bg_values()['bg_model'])
        if not ready:
            self.tool_hint.setText(message); return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            source = open_image(source_file(self.files[0])); source.thumbnail((1000, 1000), Image.Resampling.LANCZOS)
            values = self._bg_values(); result = bgremove.remove_background(source, values['bg_model'], values['bg_feather']); source.close()
            board = Image.new('RGBA', result.size, (238, 238, 238, 255)); tile = max(8, min(result.size) // 40)
            squares = Image.new('RGBA', (tile, tile), (205, 205, 205, 255))
            for y in range(0, result.height, tile):
                for x in range(0, result.width, tile):
                    if (x // tile + y // tile) % 2: board.paste(squares, (x, y))
            board.alpha_composite(result); result.close()
            self.static_preview.set_preview_pixmap(QPixmap.fromImage(QImage(ImageQt(board)))); board.close()
            self.stage.setCurrentIndex(STAGE_STATIC)
            self.tool_hint.setText('Prévia do resultado sobre xadrez (a transparência aparece como quadrados). Confira bordas, cabelo e sombras antes de salvar.')
        except (ConversionError, bgremove.BgError, OSError, ValueError) as error:
            self.tool_hint.setText('Prévia indisponível: ' + str(error)[:200])
        finally:
            QApplication.restoreOverrideCursor()

    def _bg_model_changed(self, _index=None):
        if self.selected_tool == BG_TARGET and not getattr(self, '_syncing', False):
            self._show_tool_controls(BG_TARGET)

    def _bg_values(self) -> dict:
        return {'bg_model': tuple(bgremove.MODELS)[max(0, self.bg_model.currentIndex())], 'bg_feather': self.bg_feather.value()}

    def _ocr_values(self) -> dict:
        return {'ocr_lang': tuple(ocr.LANGS)[max(0, self.ocr_lang.currentIndex())], 'ocr_psm': tuple(ocr.PSM)[max(0, self.ocr_psm.currentIndex())]}

    def _sharpen_values(self) -> dict:
        return {'sharpen_mode': 'blur' if self.sharp_mode.currentIndex() == 1 else 'sharpen', 'sharpen_amount': self.sharp_amount.value(), 'sharpen_radius': self.sharp_radius.value()}

    def _sharpen_mode_changed(self, _index=None):
        if self.selected_tool == 'Sharpen → PNG':
            self._show_tool_controls('Sharpen → PNG')
            self._sharpen_changed()

    def _sharpen_changed(self, _value=None):
        if self.selected_tool != 'Sharpen → PNG' or getattr(self, '_syncing', False) or not self.files:
            return
        if len(self.files) != 1 or not self.crop_image_size[0]:
            return
        try:
            if self._sharp_source is None:
                from PIL import Image
                source = open_image(source_file(self.files[0]))
                source.thumbnail((900, 900), Image.Resampling.LANCZOS)
                self._sharp_source = source
            from PIL.ImageQt import ImageQt
            preview = sharpen_image(self._sharp_source, sharpen_options_from(self._sharpen_values()))
            self.static_preview.set_preview_pixmap(QPixmap.fromImage(QImage(ImageQt(preview))))
            preview.close()
        except (ConversionError, OSError, ValueError) as error:
            self.tool_hint.setText('Prévia indisponível: ' + str(error)[:160])
            return
        self.stage.setCurrentIndex(STAGE_STATIC)
        self.tool_hint.setText('Ajuste o efeito; a prévia mostra o resultado.')

    def _output_format_values(self):
        key = tuple(OUTPUT_FORMATS)[max(0, self.out_format.currentIndex())]
        return key, self.out_quality.value(), self.out_flatten.text()

    def _output_format_changed(self, _index=None):
        target = self.selected_tool
        if target in tool_registry.FORMAT_TARGETS:
            keep_enabled = self.run_button.isEnabled()
            self._show_tool_controls(target)
            self.run_button.setEnabled(keep_enabled)
            self._refresh_tool_gate(target)

    def _refresh_tool_gate(self, target):
        """Reaplica o bloqueio do botão de ferramentas que exigem uma escolha antes de salvar."""
        if target == 'Adjust → PNG':
            self._adjust_changed()
        elif target == 'Rotate → PNG':
            self._rotate_changed()

    def _rotate_values(self):
        return (0, 90, 180, 270)[max(0, self.rotate_angle.currentIndex())], max(0, self.rotate_flip.currentIndex())

    def reset_rotation(self):
        self._syncing = True
        self.rotate_angle.setCurrentIndex(0); self.rotate_flip.setCurrentIndex(0)
        self._syncing = False

    def _rotate_changed(self, _value=None):
        if self.selected_tool != 'Rotate → PNG' or getattr(self, '_syncing', False) or not self.files:
            return
        angle, flip = self._rotate_values()
        self.run_button.setEnabled(bool(angle or flip))
        if len(self.files) != 1 or not self.crop_image_size[0] or getattr(self, '_rotate_pixmap', None) is None:
            self.rotate_info.setText(f'{len(self.files)} arquivos: a mesma regra vale para cada imagem.' if len(self.files) > 1 else '')
            return
        image = self._rotate_pixmap.toImage()
        if angle:
            image = image.transformed(QTransform().rotate(angle))
        if flip:
            image = image.mirrored(flip in (1, 3), flip in (2, 3))
        self.static_preview.set_preview_pixmap(QPixmap.fromImage(image))
        width, height = self.crop_image_size
        out = (height, width) if angle in (90, 270) else (width, height)
        self.rotate_info.setText(f'{width} × {height} px → {out[0]} × {out[1]} px (sem perda)' if (angle or flip) else 'Nenhuma mudança escolhida ainda.')

    def _resize_mode_changed(self, _index=None):
        if self.selected_tool == 'Resize → PNG':
            self._show_tool_controls('Resize → PNG')
            self._resize_changed()

    # --- Extrair texto e imagens embutidas -------------------------------------
    def _pdftext_values(self) -> dict:
        values = {'text_mode': ('single', 'marks', 'pages')[max(0, self.txt_mode.currentIndex())],
                  'text_layout': 'layout' if self.txt_layout.currentIndex() == 1 else 'simple'}
        if self.txt_pages.text().strip():
            values['pdf_pages'] = self.txt_pages.text().strip()
        return values

    def _embedded_values(self) -> dict:
        values = {'img_min': self.emb_min.value()}
        if self.emb_pages.text().strip():
            values['pdf_pages'] = self.emb_pages.text().strip()
        return values

    def _pdf_range_state(self, text: str):
        """(páginas escolhidas ou None, mensagem de problema, informações do PDF) para o PDF aberto e o intervalo digitado."""
        if not self.files:
            return None, 'Abra um PDF.', {}
        if not self.pdf_stage.infos:
            return None, 'Lendo o PDF…', {}
        info = next(iter(self.pdf_stage.infos.values()))
        if info.get('error'):
            return None, str(info['error']), info
        if info.get('encrypted'):
            return None, 'Este PDF está protegido por senha; o Arquivo Local não abre PDFs protegidos.', info
        try:
            return pdfinfo.parse_page_range(text, info.get('pages') or 0), '', info
        except pdfinfo.PdfError as error:
            return None, str(error), info

    def _pdftext_state(self):
        """(texto, pode salvar) da ferramenta de texto ou de imagens embutidas, conforme a ferramenta aberta."""
        if self.selected_tool == 'PDF → Text':
            pages, problem, info = self._pdf_range_state(self.txt_pages.text())
            if problem:
                return problem, False
            text = f'{len(pages)} {"página será lida" if len(pages) == 1 else "páginas serão lidas"}.'
            if info.get('text_layer') == 'não':
                text += ' O PDF parece não ter camada de texto (talvez digitalizado): se as páginas escolhidas não tiverem texto, nada será salvo.'
            return text, True
        pages, problem, _info = self._pdf_range_state(self.emb_pages.text())
        if problem:
            return problem, False
        minimum = self.emb_min.value()
        return f'Imagens de {len(pages)} {"página" if len(pages) == 1 else "páginas"}' + (f', ignorando as menores que {minimum} px.' if minimum else ', sem ignorar nenhuma.'), True

    def _pdftext_changed(self, *_args):
        if self.selected_tool not in ('PDF → Text', 'Extract PDF Images'):
            return
        text, ready = self._pdftext_state()
        (self.txt_info if self.selected_tool == 'PDF → Text' else self.emb_info).setText(text)
        self.run_button.setEnabled(ready)

    # --- Proteger e remover senha ------------------------------------------------
    def _clear_passwords(self):
        for field in (self.pw_pass, self.pw_repeat, self.pw_owner, self.pw_current):
            field.blockSignals(True); field.clear(); field.blockSignals(False)

    def _password_values(self) -> dict:
        if self.selected_tool == PDF_UNPROTECT:
            return {'pdf_password': self.pw_current.text()}
        values = {'pdf_password': self.pw_pass.text(), 'perm_print': 'off' if self.pw_print.currentIndex() == 1 else 'on',
                  'perm_copy': 'off' if self.pw_copy.currentIndex() == 1 else 'on', 'perm_edit': 'off' if self.pw_edit.currentIndex() == 1 else 'on'}
        if self.pw_owner.text():
            values['pdf_owner_password'] = self.pw_owner.text()
        return values

    def _password_state(self):
        """(mensagem, pode executar). A mensagem nunca mostra a senha."""
        if not self.files:
            return 'Abra um PDF.', False
        if not self.pdf_stage.infos:
            return 'Lendo o PDF…', False
        infos = list(self.pdf_stage.infos.values())
        if any(info.get('error') for info in infos):
            return str(next(info['error'] for info in infos if info.get('error'))), False
        if self.selected_tool == PDF_UNPROTECT:
            if not any(info.get('encrypted') for info in infos):
                return 'Este PDF não tem senha; não há o que remover.', False
            return 'Informe a senha do PDF. Ela só é usada nesta tarefa e não é guardada.', True
        if any(info.get('encrypted') for info in infos):
            return 'Este PDF já tem senha. Remova-a antes (Remover senha) se quiser trocar.', False
        values = self._password_values()
        if len(values['pdf_password']) < PASSWORD_MIN:
            return f'A senha deve ter pelo menos {PASSWORD_MIN} caracteres.', False
        if values['pdf_password'] != self.pw_repeat.text():
            return 'As senhas não são iguais.', False
        blocked = 'off' in (values['perm_print'], values['perm_copy'], values['perm_edit'])
        owner = values.get('pdf_owner_password', '')
        if blocked and (len(owner) < PASSWORD_MIN or owner == values['pdf_password']):
            return f'Para bloquear impressão, cópia ou edição, defina uma senha de permissões diferente (mínimo {PASSWORD_MIN} caracteres).', False
        if owner and not blocked and len(owner) < PASSWORD_MIN:
            return f'A senha de permissões deve ter pelo menos {PASSWORD_MIN} caracteres.', False
        return 'Pronto para proteger. Guarde a senha: sem ela o conteúdo não pode ser recuperado.', True

    def _password_changed(self, *_args):
        if self.selected_tool not in (PDF_PROTECT, PDF_UNPROTECT):
            return
        text, ready = self._password_state()
        self.pw_info.setText(text)
        self.run_button.setEnabled(ready)

    # --- Numerar e carimbar PDF ------------------------------------------------
    STAMP_PRESETS = (('Página {n} de {total}', 7, 10, 100), ('', 1, 10, 100), ('CONFIDENCIAL', 4, 70, 25))       # texto, posição, tamanho, opacidade por tipo

    def _stamp_fields(self):
        water = self.st_kind.currentIndex() == 2
        centered = self.st_position.currentIndex() == 4
        fields = ['skind', 'stext', 'spos']
        if water and centered:
            fields.append('sangle')
        fields += ['swsize' if water else 'ssize', 'sopac']
        if not (water and centered):
            fields.append('smargin')
        fields += ['scolor', 'sbold']
        if '{n}' in self.st_text.text():
            fields.append('sstart')
        return (*fields, 'spages', 'sinfo')

    def _stamp_kind_changed(self, _index=None):
        kind = max(0, self.st_kind.currentIndex())
        presets = [item[0] for item in self.STAMP_PRESETS]
        if self.st_text.text().strip() in presets or not self.st_text.text().strip():
            self.st_text.setText(self.STAMP_PRESETS[kind][0])
        self.st_text.setPlaceholderText('Texto do cabeçalho ou rodapé' if kind == 1 else 'Texto da marca')
        self.st_position.setCurrentIndex(self.STAMP_PRESETS[kind][1])
        if kind == 2:
            self.st_wsize.setValue(70); self.st_opacity.setValue(25); self.st_color.setText('#808080'); self.st_angle.setCurrentIndex(1)
        else:
            self.st_size.setValue(10); self.st_opacity.setValue(100); self.st_color.setText('#000000')
        self._stamp_layout_changed()

    def _stamp_layout_changed(self, _index=None):
        if self.selected_tool == PDF_STAMP:
            self._show_tool_controls(PDF_STAMP)
            self._stamp_changed()

    def _stamp_values(self) -> dict:
        water = self.st_kind.currentIndex() == 2
        centered = self.st_position.currentIndex() == 4
        values = {'stamp_kind': 'watermark' if water else 'text', 'stamp_text': self.st_text.text().strip(),
                  'stamp_position': ('tl', 'tc', 'tr', 'ml', 'c', 'mr', 'bl', 'bc', 'br')[max(0, self.st_position.currentIndex())],
                  'stamp_size': self.st_wsize.value() if water else self.st_size.value(), 'stamp_opacity': self.st_opacity.value(), 'stamp_margin': self.st_margin.value(),
                  'stamp_angle': 45 if (water and centered and self.st_angle.currentIndex() == 1) else 0, 'stamp_start': self.st_start.value(),
                  'stamp_color': self.st_color.text().strip(), 'stamp_bold': 'on' if self.st_bold.currentIndex() == 1 else 'off'}
        if self.st_pages.text().strip():
            values['pdf_pages'] = self.st_pages.text().strip()
        return values

    def _stamp_state(self):
        """(exemplo/mensagem, pode executar) para o PDF aberto."""
        pages, problem, info = self._pdf_range_state(self.st_pages.text())
        if problem:
            return problem, False
        if len(self.files) != 1:
            return 'O carimbo trabalha com um PDF por vez; escolha apenas um arquivo.', False
        values = self._stamp_values()
        if not values['stamp_text']:
            return 'Escreva o texto do carimbo.', False
        if not re.fullmatch(r'#[0-9A-Fa-f]{6}', values['stamp_color']):
            return 'A cor deve estar no formato #RRGGBB.', False
        try:
            pdfstamp.encode(values['stamp_text'])
        except pdfstamp.StampError as error:
            return str(error), False
        start, total = values['stamp_start'], (info.get('pages') or 0) + values['stamp_start'] - 1
        sample = pdfstamp.expand(values['stamp_text'], pages[0] + start - 1, total)
        return f'«{sample}» em {len(pages)} {"página" if len(pages) == 1 else "páginas"} (a primeira é a {pages[0]}).', True

    def _stamp_changed(self, *_args):
        if self.selected_tool != PDF_STAMP:
            return
        text, ready = self._stamp_state()
        self.st_info.setText(text)
        self.run_button.setEnabled(ready)

    # --- Tarjar conteúdo do PDF (0.9.40) ------------------------------------------
    def _redact_reset(self):
        self.rd_areas = []

    def _redact_page_shown(self, page: int):
        self.rd_page = max(1, int(page))
        self._redact_refresh_overlay()
        self._redact_changed()

    def _redact_refresh_overlay(self):
        view = self.redact_stage.page_view
        bounds = view.image_bounds()
        rects = []
        for item in self.rd_areas:
            page, (x0, y0, x1, y1) = pdfredact.parse_area(item, 999)
            if page == self.rd_page and bounds.width() > 0:
                rects.append(QRectF(bounds.left() + bounds.width() * x0 / 1000, bounds.top() + bounds.height() * y0 / 1000,
                                    bounds.width() * (x1 - x0) / 1000, bounds.height() * (y1 - y0) / 1000))
        view.set_committed(rects)

    def add_redact_area(self):
        view = self.redact_stage.page_view
        selected, bounds = view.selected_bounds(), view.image_bounds()
        if selected is None or bounds.width() <= 0 or bounds.height() <= 0:
            return
        def milli(value, origin, size):
            return max(0, min(1000, round((value - origin) / size * 1000)))
        x0, x1 = milli(selected.left(), bounds.left(), bounds.width()), milli(selected.right(), bounds.left(), bounds.width())
        y0, y1 = milli(selected.top(), bounds.top(), bounds.height()), milli(selected.bottom(), bounds.top(), bounds.height())
        if x1 <= x0 or y1 <= y0 or len(self.rd_areas) >= pdfredact.MAX_AREAS:
            return
        self.rd_areas.append(f'{self.rd_page}:{x0},{y0},{x1},{y1}')
        view.clear_selection(emit=False)
        self._redact_refresh_overlay()
        self._redact_changed()

    def undo_redact_area(self):
        if self.rd_areas:
            self.rd_areas.pop()
            self._redact_refresh_overlay()
            self._redact_changed()

    def clear_redact_areas(self):
        self.rd_areas = []
        self._redact_refresh_overlay()
        self._redact_changed()

    def _redact_terms(self) -> list:
        return [term.strip() for term in re.split(r'[;\n]', self.rd_terms.text()) if term.strip()]

    def _redact_values(self) -> dict:
        values = {'pdf_dpi': (150, 200, 300)[max(0, self.rd_dpi.currentIndex())]}
        if self.rd_areas:
            values['redact_areas'] = list(self.rd_areas)
        if self._redact_terms():
            values['redact_terms'] = self._redact_terms()
        presets = [key for key, box in self.rd_preset_boxes.items() if box.isChecked()]
        if presets:
            values['redact_patterns'] = ','.join(presets)
        return values

    def _redact_state(self):
        if not self.files:
            return 'Abra um PDF.', False
        if len(self.files) != 1:
            return 'Tarjar trabalha com um PDF por vez; escolha apenas um arquivo.', False
        info = next(iter(self.redact_stage.infos.values()), None)
        if not info:
            return 'Lendo o PDF…', False
        if info.get('error'):
            return str(info['error']), False
        if info.get('encrypted'):
            return 'Este PDF está protegido por senha. Gere antes uma cópia sem senha em PDF › Remover senha.', False
        try:
            pdfredact.check_terms(self._redact_terms())
        except pdfredact.RedactError as error:
            return str(error), False
        values = self._redact_values()
        pending = self.redact_stage.page_view.selected_bounds() is not None
        if not (values.get('redact_areas') or values.get('redact_terms') or values.get('redact_patterns')):
            return ('Há uma seleção ainda não marcada: clique em “Marcar área”.' if pending else 'Marque uma área na página ou informe um termo ou padrão.'), False
        parts = []
        if self.rd_areas:
            pages = sorted({int(item.split(':')[0]) for item in self.rd_areas})
            parts.append(f'{len(self.rd_areas)} área(s) em {len(pages)} página(s)')
        if values.get('redact_terms') or values.get('redact_patterns'):
            parts.append('termos/padrões em todas as páginas')
        text = ' · '.join(parts) + '. As páginas afetadas viram imagem (sem texto selecionável).'
        if pending:
            text += ' A seleção atual ainda não foi marcada.'
        return text, True

    def _redact_changed(self, *_args):
        self.rd_undo_button.setEnabled(bool(self.rd_areas)); self.rd_clear_button.setEnabled(bool(self.rd_areas))
        self.rd_add_button.setEnabled(self.redact_stage.page_view.selected_bounds() is not None)
        if self.selected_tool != PDF_REDACT:
            return
        text, ready = self._redact_state()
        self.rd_info.setText(text)
        self.run_button.setEnabled(ready)

    # --- Preencher formulário e assinatura visual (0.9.41) -----------------------------
    def _form_reset(self):
        self.fm_areas = []
        self.fm_image = ''
        self.fm_signature_key = None
        self.fm_editors = {}
        if hasattr(self, 'fm_image_label'):
            self.fm_image_label.setText('Nenhuma')
            self.fm_flatten.blockSignals(True); self.fm_flatten.setCurrentIndex(0); self.fm_flatten.blockSignals(False)
            while self.fm_fields_layout.rowCount():
                self.fm_fields_layout.removeRow(0)

    def _form_info(self) -> dict:
        return next(iter(self.form_stage.infos.values()), None) or {}

    def _form_infos(self, *_args):
        """Chegaram as informações do PDF: monta os editores dos campos (uma vez por conjunto de campos) e atualiza o resumo."""
        info = self._form_info()
        fields = info.get('form_fields') or []
        key = tuple((f['name'], f['kind']) for f in fields)
        if key != self.fm_signature_key:
            self.fm_signature_key = key
            self.fm_editors = {}
            while self.fm_fields_layout.rowCount():
                self.fm_fields_layout.removeRow(0)
            for field in fields:
                editor = self._form_editor(field)
                self.fm_fields_layout.addRow(QLabel(field['name'] + (f'  (p. {field["page"]})' if (info.get('pages') or 1) > 1 else '')), editor)
                self.fm_editors[field['name']] = (field['kind'], editor, field['value'], field)
            if not fields:
                note = QLabel('Este PDF não tem campos de formulário.' if info else 'Lendo o PDF…'); note.setObjectName('Muted'); note.setWordWrap(True)
                self.fm_fields_layout.addRow(note)
        self._form_changed()

    def _form_editor(self, field: dict):
        kind, value = field['kind'], field['value']
        if kind == 'check':
            editor = QCheckBox(); editor.setChecked(value == 'on'); editor.toggled.connect(self._form_changed)
        elif kind in ('radio', 'choice'):
            editor = QComboBox(); editor.addItem(''); editor.addItems(field['options'])
            index = editor.findText(value) if value else 0
            editor.setCurrentIndex(max(0, index)); editor.currentIndexChanged.connect(self._form_changed)
        else:
            editor = QLineEdit(); editor.setText(value); editor.setMaxLength(min(pdfform.MAX_VALUE, field['maxlen'] or pdfform.MAX_VALUE)); editor.textChanged.connect(self._form_changed)
        if kind not in pdfform.FILLABLE or field['readonly']:
            editor.setEnabled(False)
            editor.setToolTip('Campo somente leitura, botão ou assinatura digital: não pode ser preenchido aqui.')
        return editor

    def _form_page_shown(self, page: int):
        self.fm_page = max(1, int(page))
        self._form_refresh_overlay()
        self._form_changed()

    def _form_refresh_overlay(self):
        view = self.form_stage.page_view
        bounds = view.image_bounds()
        rects = []
        for item in self.fm_areas:
            page, (x0, y0, x1, y1) = pdfform.parse_sign_area(item, 999)
            if page == self.fm_page and bounds.width() > 0:
                rects.append(QRectF(bounds.left() + bounds.width() * x0 / 1000, bounds.top() + bounds.height() * y0 / 1000, bounds.width() * (x1 - x0) / 1000, bounds.height() * (y1 - y0) / 1000))
        view.set_committed(rects)

    def add_form_area(self):
        view = self.form_stage.page_view
        selected, bounds = view.selected_bounds(), view.image_bounds()
        if selected is None or bounds.width() <= 0 or bounds.height() <= 0 or len(self.fm_areas) >= pdfform.MAX_SIGN_AREAS:
            return
        def milli(value, origin, size):
            return max(0, min(1000, round((value - origin) / size * 1000)))
        x0, x1 = milli(selected.left(), bounds.left(), bounds.width()), milli(selected.right(), bounds.left(), bounds.width())
        y0, y1 = milli(selected.top(), bounds.top(), bounds.height()), milli(selected.bottom(), bounds.top(), bounds.height())
        if x1 <= x0 or y1 <= y0:
            return
        self.fm_areas.append(f'{self.fm_page}:{x0},{y0},{x1},{y1}')
        view.clear_selection(emit=False)
        self._form_refresh_overlay(); self._form_changed()

    def undo_form_area(self):
        if self.fm_areas:
            self.fm_areas.pop(); self._form_refresh_overlay(); self._form_changed()

    def clear_form_areas(self):
        self.fm_areas = []; self._form_refresh_overlay(); self._form_changed()

    def choose_sign_image(self):
        path, _filter = QFileDialog.getOpenFileName(self, 'Imagem da assinatura', '', 'Imagens (*.png *.jpg *.jpeg *.webp *.bmp)')
        if path:
            self.set_sign_image(path)

    def set_sign_image(self, path: str):
        self.fm_image = str(path)
        self.fm_image_label.setText(Path(path).name if path else 'Nenhuma')
        self._form_changed()

    def _form_values(self) -> dict:
        values = []
        for name, (kind, editor, original, field) in self.fm_editors.items():
            if not editor.isEnabled():
                continue
            if kind == 'check':
                current = 'on' if editor.isChecked() else 'off'
            elif kind in ('radio', 'choice'):
                current = editor.currentText()
            else:
                current = editor.text()
            if current != original:
                values.append(f'{name}\t{current}')
        result = {}
        if values:
            result['form_values'] = values
        if self.fm_flatten.currentIndex() == 1:
            result['form_flatten'] = 'on'
        if self.fm_areas:
            result['sign_areas'] = list(self.fm_areas)
        if self.fm_image and self.fm_areas:
            result['sign_image'] = self.fm_image
        return result

    def _form_state(self):
        if not self.files:
            return 'Abra um PDF.', False
        if len(self.files) != 1:
            return 'Preencher e assinar trabalha com um PDF por vez; escolha apenas um arquivo.', False
        info = self._form_info()
        if not info:
            return 'Lendo o PDF…', False
        if info.get('error'):
            return str(info['error']), False
        if info.get('encrypted'):
            return 'Este PDF está protegido por senha. Gere antes uma cópia sem senha em PDF › Remover senha.', False
        values = self._form_values()
        flat = self.fm_flatten.currentIndex() == 1
        if self.fm_areas and not self.fm_image:
            return 'Escolha a imagem da assinatura.', False
        if self.fm_image and not self.fm_areas:
            return ('Há uma seleção ainda não marcada: clique em “Marcar área”.' if self.form_stage.page_view.selected_bounds() is not None else 'Marque na página onde a assinatura deve ficar.'), False
        if flat and not self.fm_editors:
            return 'Este PDF não tem campos de formulário para achatar.', False
        if not (values.get('form_values') or flat or self.fm_areas):
            return ('Este PDF não tem campos: escolha uma imagem e marque onde assiná-lo.' if not self.fm_editors else 'Altere algum campo, escolha achatar ou marque a assinatura.'), False
        parts = []
        if values.get('form_values'):
            parts.append(f'{len(values["form_values"])} campo(s) alterado(s)')
        if flat:
            parts.append('formulário achatado')
        if self.fm_areas:
            parts.append(f'assinatura em {len(self.fm_areas)} área(s)')
        text = ' · '.join(parts) + '.'
        if self.fm_areas:
            text += ' A imagem não é assinatura digital certificada.'
        return text, True

    def _form_changed(self, *_args):
        self.fm_undo_button.setEnabled(bool(self.fm_areas)); self.fm_clear_button.setEnabled(bool(self.fm_areas))
        self.fm_add_button.setEnabled(bool(self.fm_image) and self.form_stage.page_view.selected_bounds() is not None)
        if self.selected_tool != PDF_FORM:
            return
        text, ready = self._form_state()
        self.fm_info.setText(text)
        self.run_button.setEnabled(ready)

    # --- Comprimir PDF -------------------------------------------------------
    def _pdfcompress_values(self) -> dict:
        return {'pdf_level': ('light', 'medium', 'strong')[max(0, self.cp_level.currentIndex())]}

    def _pdfcompress_state(self):
        if not self.files:
            return 'Abra um PDF.', False
        if not self.pdf_stage.infos:
            return 'Lendo o PDF…', False
        info = next(iter(self.pdf_stage.infos.values()))
        if info.get('error'):
            return str(info['error']), False
        if info.get('encrypted'):
            return 'Este PDF está protegido por senha; o Arquivo Local não abre PDFs protegidos.', False
        text = f'Tamanho atual: {pdfinfo.human_bytes(info.get("size_bytes", 0))}.'
        if len(self.files) > 1:
            text = f'{len(self.files)} PDFs: cada um é comprimido à parte. ' + text.replace('Tamanho atual', 'Primeiro')
        if info.get('text_layer') == 'não':
            text += ' Parece digitalizado: o nível Forte pode deixar o texto difícil de ler.'
        return text + ' O tamanho final aparece ao terminar; se não reduzir, nada é salvo.', True

    def _pdfcompress_changed(self, *_args):
        if self.selected_tool != PDF_COMPRESS:
            return
        text, ready = self._pdfcompress_state()
        self.cp_info.setText(text)
        self.run_button.setEnabled(ready)

    # --- Converter áudio ------------------------------------------------------
    AUDIO_FORMAT_KEYS = ('mp3', 'm4a', 'flac', 'ogg', 'opus', 'wav', 'aiff')

    def _audioconvert_values(self) -> dict:
        return {'audio_format': self.AUDIO_FORMAT_KEYS[max(0, self.ac_format.currentIndex())],
                'audio_quality': ('low', 'medium', 'high')[max(0, self.ac_quality.currentIndex())],
                'audio_tags': 'drop' if self.ac_tags.currentIndex() == 1 else 'keep'}

    def _audioconvert_state(self):
        if not self.files:
            return 'Abra um arquivo de áudio ou vídeo.', False
        capability = self.controller.capabilities.get('audio', (False, 'FFmpeg indisponível.'))
        if not capability[0]:
            return capability[1], False
        if not self.audio_stage.infos:
            return 'Lendo o arquivo…', False
        values = self._audioconvert_values()
        info = next(iter(self.audio_stage.infos.values()))
        if info.get('error'):
            return str(info['error']), False
        spec = audioconvert.FORMATS[values['audio_format']]
        outputs = (mediatools.build_info() or {}).get('outputs', [])
        if values['audio_format'] not in outputs:
            return f'Este FFmpeg não tem o codificador de {spec["label"]}; escolha outro formato.', False
        lines = [f'Saída: {spec["label"]}.']
        if len(self.files) > 1:
            lines = [f'{len(self.files)} arquivos: cada um é convertido à parte. '] + lines
        if spec['lossy']:
            lines.append(f'Com perda de qualidade (≈ {audioconvert.BITRATES[values["audio_format"]][values["audio_quality"]]} kbps).')
        estimate = audioconvert.estimate_bytes(values['audio_format'], values['audio_quality'], info)
        if estimate > audioconvert.MAX_OUTPUT_BYTES * audioconvert.SAFETY_MARGIN:
            return f'A saída em {spec["label"]} passaria de 512 MiB; escolha um formato comprimido.', False
        if estimate and not spec['lossy']:
            lines.append(f'Tamanho aproximado: até {mediatools.human_size(estimate)}.')
        if info.get('has_video'):
            lines.append('Só o áudio do vídeo é extraído.')
        return ' '.join(lines), True

    def _audioconvert_changed(self, *_args):
        if self.selected_tool != AUDIO_CONVERT:
            return
        text, ready = self._audioconvert_state()
        self.ac_info.setText(text)
        self.run_button.setEnabled(ready)

    # --- Metadados e cópia limpa ---------------------------------------------
    def _pdfclean_values(self) -> dict:
        return {'meta_info': 'off' if self.kl_meta.currentIndex() == 1 else 'on', 'meta_attach': 'off' if self.kl_attach.currentIndex() == 1 else 'on',
                'meta_js': 'off' if self.kl_js.currentIndex() == 1 else 'on'}

    def _pdfclean_details(self, info: dict) -> str:
        lines = [f'{label}: {value}' for label, value in info.get('meta_fields', [])]
        lines += [f'{label}: {value}' for label, value in info.get('xmp_fields', [])]
        if info.get('xmp') and not info.get('xmp_fields'):
            lines.append('XMP: presente')
        if info.get('attachment_names'):
            lines.append('Anexos: ' + ', '.join(info['attachment_names']))
        elif info.get('attachments'):
            lines.append('Anexos: presentes')
        if info.get('javascript'):
            lines.append('JavaScript: presente')
        if info.get('forms'):
            lines.append('Formulário: presente')
        return '\n'.join(lines) if lines else 'Nenhum metadado, anexo ou script encontrado.'

    def _pdfclean_state(self):
        """(detalhes, resultado, pode executar) para o primeiro PDF aberto."""
        if not self.files:
            return '', 'Abra um PDF.', False
        if not self.pdf_stage.infos:
            return '', 'Lendo o PDF…', False
        info = next(iter(self.pdf_stage.infos.values()))
        if info.get('error'):
            return '', str(info['error']), False
        if info.get('encrypted'):
            return '', 'Este PDF está protegido por senha; o Arquivo Local não abre PDFs protegidos.', False
        values = self._pdfclean_values()
        if all(value == 'off' for value in values.values()):
            return self._pdfclean_details(info), 'Marque ao menos uma coisa para remover.', False
        text = 'A cópia limpa será salva ao lado do original.'
        if len(self.files) > 1:
            text = f'{len(self.files)} PDFs: cada um ganha a sua cópia limpa. Os detalhes acima são do primeiro.'
        return self._pdfclean_details(info), text, True

    def _pdfclean_changed(self, *_args):
        if self.selected_tool != PDF_CLEAN:
            return
        details, text, ready = self._pdfclean_state()
        self.kl_details.setText(details); self.kl_info.setText(text)
        self.run_button.setEnabled(ready)

    # --- OCR de PDF digitalizado ---------------------------------------------
    def _pdfocr_values(self) -> dict:
        values = {**self._ocr_values(), 'ocr_skip': 'off' if self.rocr_skip.currentIndex() == 1 else 'on'}
        if self.selected_tool == PDF_OCR_TEXT:
            values['text_mode'] = ('single', 'marks', 'pages')[max(0, self.rocr_text.currentIndex())]
        if self.rocr_pages.text().strip():
            values['pdf_pages'] = self.rocr_pages.text().strip()
        return values

    def _pdfocr_state(self):
        """(texto, pode executar) para o PDF aberto: conta as páginas que realmente precisam de OCR."""
        pages, problem, info = self._pdf_range_state(self.rocr_pages.text())
        if problem:
            return problem, False
        if len(self.files) != 1:
            return 'O OCR de PDF trabalha com um arquivo por vez; escolha apenas um PDF.', False
        ready, message = ocr.status()
        if not ready:
            return message, False
        text = f'{len(pages)} {"página escolhida" if len(pages) == 1 else "páginas escolhidas"}.'
        if self.rocr_skip.currentIndex() == 0 and info.get('text_layer') == 'sim':
            text += ' Este PDF já tem texto: as páginas que o têm serão puladas.'
        elif len(pages) > PDF_OCR_MAX_PAGES and self.rocr_skip.currentIndex() == 1:
            return text + f' O limite é {PDF_OCR_MAX_PAGES} por vez; escolha um intervalo menor, como 1-{PDF_OCR_MAX_PAGES}.', False
        elif len(pages) > PDF_OCR_MAX_PAGES:
            text += f' Só {PDF_OCR_MAX_PAGES} páginas sem texto cabem por vez; se houver mais, o trabalho avisa e nada é salvo.'
        return text + ' Cada página leva alguns segundos.', True

    def _pdfocr_changed(self, *_args):
        if self.selected_tool not in PDF_OCR_TARGETS:
            return
        text, ready = self._pdfocr_state()
        self.rocr_info.setText(text)
        self.run_button.setEnabled(ready)

    # --- Organizar páginas ---------------------------------------------------
    def _organize_changed(self, *_args):
        if self.selected_tool != 'Organize PDF':
            return
        has = self.organizer.list.count() > 0
        selected = bool(self.organizer.selected_rows())
        for button in (self.org_left, self.org_right, self.org_back, self.org_forward, self.org_copy):
            button.setEnabled(selected)
        self.org_delete.setEnabled(selected and len(self.organizer.selected_rows()) < self.organizer.list.count())
        self.org_all.setEnabled(has); self.org_reset.setEnabled(has and self.organizer.is_modified())
        if self.organizer.error:
            text, ready = self.organizer.error, False
        elif not has:
            text, ready = 'Abra um PDF para organizar as páginas.', False
        elif not self.organizer.is_modified():
            text, ready = 'Nada mudou ainda: gire, mova, exclua ou duplique páginas.', False
        else:
            text, ready = self.organizer.summary.text().replace(' Carregando miniaturas…', ''), True
        self.org_info.setText(text)
        self.run_button.setEnabled(ready)

    # --- Dividir e extrair páginas ----------------------------------------
    def _split_values(self) -> dict:
        index = max(0, self.split_mode.currentIndex())
        values = {'split_mode': ('each', 'every', 'ranges', 'extract')[index]}
        if index == 1:
            values['split_every'] = self.split_every.value()
        if index >= 2:
            values['split_ranges'] = self.split_ranges.text().strip()
        return values

    def _split_mode_changed(self, _index=None):
        if self.selected_tool != 'Split PDF':
            return
        self._show_tool_controls('Split PDF')          # mostra/oculta os campos do modo e já recalcula o resultado

    def _split_state(self):
        """(texto do resultado, pode salvar) para o PDF aberto e a escolha atual."""
        infos = [(path, info) for path, info in self.pdf_stage.infos.items()]
        if not self.files:
            return 'Abra um PDF.', False
        if not infos:
            return 'Lendo o PDF…', False
        _path, info = infos[0]
        if info.get('error'):
            return str(info['error']), False
        if info.get('encrypted'):
            return 'Este PDF está protegido por senha; o Arquivo Local não abre PDFs protegidos.', False
        count = info.get('pages') or 0
        values = self._split_values()
        try:
            mode, every, text = engine_module.split_options_from(values)
            groups = engine_module.split_groups(mode, every, text, count)
        except ConversionError as error:
            return str(error), False
        if mode == 'extract':
            return f'Um PDF novo com {len(groups[0])} {"página" if len(groups[0]) == 1 else "páginas"} (de {count}).', True
        sizes = sorted({len(group) for group in groups})
        detail = f' de {sizes[0]} {"página" if sizes[0] == 1 else "páginas"}' if len(sizes) == 1 else f' (de {sizes[0]} a {sizes[-1]} páginas)'
        return f'{len(groups)} {"PDF" if len(groups) == 1 else "PDFs"}{detail}, numerados numa pasta nova ao lado do original.', True

    def _split_changed(self, _value=None):
        if self.selected_tool != 'Split PDF':
            return
        self.split_ranges.setPlaceholderText('Ex.: 1-3; 4-6; 7-  (cada grupo vira um PDF)' if self.split_mode.currentIndex() == 2 else 'Ex.: 1-3,7  (as páginas que ficam no PDF novo)')
        text, ready = self._split_state()
        self.split_info.setText(text)
        self.run_button.setEnabled(ready)

    def _pdfimg_changed(self, _value=None):
        if self.selected_tool != 'PDF → Images':
            return
        self.pdfimg_info.setText(self._pdfimg_summary())
        self._refresh_pdfimg_gate()

    def _pdfimg_values(self) -> dict:
        return {'pdf_dpi': self.pdfimg_dpi.value(), 'pdf_pages': self.pdfimg_pages.text().strip()}

    def _pdfimg_problem(self) -> str:
        """Motivo pelo qual as páginas não podem ser salvas com a escolha atual (vazio se estiver tudo certo)."""
        dpi = self.pdfimg_dpi.value()
        for path, info in self.pdf_stage.infos.items():
            count, points = info.get('pages'), info.get('page_points')
            if info.get('error') or info.get('encrypted') or not count:
                continue
            try:
                pages = pdfinfo.parse_page_range(self.pdfimg_pages.text(), count)
                if points and 1 in pages:
                    pdfinfo.page_pixels_ok(1, points[0], points[1], dpi)
            except pdfinfo.PdfError as error:
                return f'{Path(path).name}: {error}' if len(self.pdf_stage.infos) > 1 else str(error)
        return ''

    def _pdfimg_summary(self) -> str:
        dpi = self.pdfimg_dpi.value()
        problem = self._pdfimg_problem()
        if problem:
            return problem
        for info in self.pdf_stage.infos.values():
            points = info.get('page_points')
            if points and not info.get('error') and not info.get('encrypted'):
                w, h = pdfinfo.dpi_size(points[0], points[1], dpi)
                return f'A primeira página fica com {w} × {h} px ({w * h / 1e6:.1f} megapixels) a {dpi} dpi.'
        return f'{dpi} dpi: uma página A4 fica com cerca de {round(8.27 * dpi)} × {round(11.69 * dpi)} px.'

    def _refresh_pdfimg_gate(self):
        if self.selected_tool == 'PDF → Images':
            self.run_button.setEnabled(not self._pdfimg_problem())

    def _resize_values(self):
        return ('percent', 'fit', 'exact')[max(0, self.resize_mode.currentIndex())], self.resize_percent.value(), self.resize_width.value(), self.resize_height.value()

    def _resize_changed(self, _value=None):
        if self.selected_tool != 'Resize → PNG' or getattr(self, '_syncing', False):
            return
        if not self.files:
            self.resize_info.setText(''); return
        mode, percent, width, height = self._resize_values()
        if not all(self.crop_image_size):
            try:
                resize_target_size((1, 1), mode, percent, width, height)
            except ValueError as error:
                self.resize_info.setText(str(error)); return
            limit = f'{width or "sem limite"} × {height or "sem limite"} px'
            rule = {'percent': f'{percent} % do tamanho de cada imagem', 'fit': f'caber em {limit}, mantendo a proporção', 'exact': f'{width} × {height} px exatos'}[mode]
            self.resize_info.setText(f'{len(self.files)} arquivos: cada imagem fica com {rule}. O tamanho final é calculado imagem por imagem.')
            return
        original = self.crop_image_size
        try:
            new = resize_target_size(original, mode, percent, width, height)
        except ValueError as error:
            self.resize_info.setText(str(error)); return
        text = f'{original[0]} × {original[1]} px → {new[0]} × {new[1]} px'
        if new[0] * new[1] > original[0] * original[1]:
            text += ' (ampliação: pode ficar borrada)'
        elif mode == 'exact' and abs(new[0] / new[1] - original[0] / original[1]) > 0.01:
            text += ' (a proporção muda)'
        self.resize_info.setText(text)

    def reset_adjustments(self, refresh=True):
        self._syncing = True
        for control in (self.adjust_brightness, self.adjust_contrast, self.adjust_saturation):
            control.setValue(0)
        self.adjust_flip.setCurrentIndex(0)
        self._syncing = False
        if refresh:
            self._adjust_changed()

    def _adjust_changed(self, _value=None):
        if self.selected_tool != 'Adjust → PNG' or getattr(self, '_syncing', False) or not self.files:
            return
        values = (self.adjust_brightness.value(), self.adjust_contrast.value(), self.adjust_saturation.value(), self.adjust_flip.currentIndex())
        self.run_button.setEnabled(any(values))
        if len(self.files) != 1 or not self.crop_image_size[0]:
            return
        try:
            if self._adjust_source is None:
                source = open_image(source_file(self.files[0]))
                from PIL import Image
                source.thumbnail((900, 900), Image.Resampling.LANCZOS)
                self._adjust_source = source
            from PIL.ImageQt import ImageQt
            preview = adjust_image(self._adjust_source, *values)
            self.static_preview.set_preview_pixmap(QPixmap.fromImage(QImage(ImageQt(preview))))
            preview.close()
        except Exception as error:
            self.status.setText('Prévia indisponível: ' + str(error)[:160])
            return
        self.stage.setCurrentIndex(STAGE_STATIC)
        self.tool_hint.setText('Mova os controles para ajustar.' if any(values) else 'Nenhum ajuste escolhido ainda: mova um controle ou escolha espelhar.')

    # --- metadados -----------------------------------------------------
    def _refresh_metadata_info(self):
        if not self.files:
            self.metadata_info.setText('Abra uma imagem para ver os metadados.')
            return
        if len(self.files) == 1:
            info = inspect_metadata(self.files[0])
            lines = [f'{label}: {value}' for label, value in info['rows']]
            if info['error']:
                lines.append(info['error'])
            elif info['sensitive']:
                lines.append('')
                lines.append('Pode identificar pessoa, lugar ou aparelho: ' + ', '.join(dict.fromkeys(info['sensitive'])) + '.')
            self.metadata_info.setText('\n'.join(lines))
            return
        lines = []
        for path in self.files[:12]:
            info = inspect_metadata(path)
            marks = list(dict.fromkeys(info['sensitive']))
            lines.append(f'{Path(path).name}: ' + (', '.join(marks) if marks else ('erro de leitura' if info['error'] else 'sem metadados sensíveis conhecidos')))
        if len(self.files) > 12:
            lines.append(f'… e mais {len(self.files) - 12} arquivos.')
        self.metadata_info.setText('\n'.join(lines))

    # --- ocultar áreas -----------------------------------------------
    def _update_redact_help(self):
        count = len(self.redact_regions)
        self.redact_help.setText('Marque uma área e clique em “Adicionar área”.' if not count else f'{count} área(s) confirmada(s). Marque outra ou salve.')
        self.redact_undo_button.setEnabled(count > 0)

    def _redact_preview(self, extra=None):
        """Prévia do resultado: aplica as áreas confirmadas (e a seleção atual) a uma cópia reduzida, com o mesmo código do motor."""
        if self.selected_tool != 'Redact → PNG' or not all(self.crop_image_size) or len(self.files) != 1:
            self.crop_preview.set_overlay(None)
            return
        regions = list(self.redact_regions) + ([tuple(extra)] if extra else [])
        if not regions:
            self.crop_preview.set_overlay(None)
            return
        try:
            if self._redact_source is None:
                from PIL import Image
                source = open_image(source_file(self.files[0]))
                source.thumbnail((1000, 1000), Image.Resampling.LANCZOS)
                self._redact_source = source
            source = self._redact_source
            scale = source.width / self.crop_image_size[0]
            scaled = []
            for x, y, w, h in regions:
                left, top = round(x * scale), round(y * scale)
                right = min(source.width, max(left + 1, round((x + w) * scale)))
                bottom = min(source.height, max(top + 1, round((y + h) * scale)))
                scaled.append((left, top, right - left, bottom - top))
            mode = 'pixelate' if self.redact_mode.currentIndex() == 1 else 'black'
            from PIL.ImageQt import ImageQt
            from engine import redact_apply
            preview = redact_apply(source, scaled, mode, max(1, round(self.redact_block.value() * scale)))
            self.crop_preview.set_overlay(QPixmap.fromImage(QImage(ImageQt(preview))))
            preview.close()
        except Exception as error:
            self.crop_preview.set_overlay(None)
            self.status.setText('Prévia do efeito indisponível: ' + str(error)[:140])

    def _refresh_redact_overlay(self):
        scene = self.crop_preview.image_bounds()
        if not all(self.crop_image_size) or scene.isNull():
            self.crop_preview.set_committed([])
            self.crop_preview.set_overlay(None)
            return
        self._redact_preview(selection_to_image_box(self.crop_preview, self.crop_image_size))
        sx = scene.width() / self.crop_image_size[0]; sy = scene.height() / self.crop_image_size[1]
        self.crop_preview.set_committed([QRectF(x * sx, y * sy, w * sx, h * sy) for x, y, w, h in self.redact_regions])

    def add_redact_region(self):
        box = selection_to_image_box(self.crop_preview, self.crop_image_size)
        if box is None:
            self.status.setText('Arraste sobre a imagem para marcar a área antes de adicioná-la.')
            return
        if len(self.redact_regions) >= 50:
            self.status.setText('Limite de 50 áreas por imagem.')
            return
        self.redact_regions.append(tuple(box))
        self.crop_preview.clear_selection()
        self._refresh_redact_overlay(); self._update_redact_help()

    def undo_redact_region(self):
        if self.redact_regions:
            self.redact_regions.pop()
            self._refresh_redact_overlay(); self._update_redact_help()

    # --- formas ----------------------------------------------------------
    def _update_shape_help(self):
        count = len(self.shape_items)
        self.sh_help.setText('Arraste sobre a imagem para desenhar a forma e clique em “Adicionar forma”.' if not count else f'{count} forma(s) confirmada(s). Desenhe outra ou salve.')
        self.sh_undo_button.setEnabled(count > 0)

    def _shape_from_box(self, box):
        kind = SHAPE_KINDS[max(0, min(3, self.sh_kind.currentIndex()))]
        x, y, w, h = box
        return {'kind': kind, 'x': x, 'y': y, 'w': w, 'h': h, 'color': self.sh_color.text().upper(), 'thickness': self.sh_thickness.value(),
                'fill': self.sh_fill.currentIndex() if kind in ('rect', 'ellipse') else 0, 'dir': self.sh_dir.currentIndex() if kind in ('line', 'arrow') else 0}

    def _shapes_preview(self, extra=None):
        """Prévia: desenha as formas confirmadas (e a área atual, com o estilo atual) numa cópia reduzida, com o mesmo código do motor."""
        if self.selected_tool != 'Shapes → PNG' or not all(self.crop_image_size) or len(self.files) != 1:
            self.crop_preview.set_overlay(None)
            return
        items = list(self.shape_items) + ([self._shape_from_box(extra)] if extra else [])
        if extra and not re.fullmatch(r'#[0-9A-Fa-f]{6}', self.sh_color.text()):
            items = list(self.shape_items)
        if not items:
            self.crop_preview.set_overlay(None)
            return
        try:
            if self._shape_source is None:
                from PIL import Image
                source = open_image(source_file(self.files[0]))
                source.thumbnail((1000, 1000), Image.Resampling.LANCZOS)
                self._shape_source = source
            source = self._shape_source
            scale = source.width / self.crop_image_size[0]
            scaled = []
            for item in items:
                left, top = round(item['x'] * scale), round(item['y'] * scale)
                right = min(source.width, max(left + 1, round((item['x'] + item['w']) * scale)))
                bottom = min(source.height, max(top + 1, round((item['y'] + item['h']) * scale)))
                scaled.append({**item, 'x': left, 'y': top, 'w': right - left, 'h': bottom - top, 'thickness': max(1, round(item['thickness'] * scale))})
            from PIL.ImageQt import ImageQt
            preview = shapes_image(source, scaled)
            self.crop_preview.set_overlay(QPixmap.fromImage(QImage(ImageQt(preview))))
            preview.close()
        except Exception as error:
            self.crop_preview.set_overlay(None)
            self.status.setText('Prévia das formas indisponível: ' + str(error)[:140])

    def _refresh_shapes_overlay(self):
        if self.selected_tool != 'Shapes → PNG' or getattr(self, '_syncing', False):
            return
        self.crop_preview.set_committed([])
        self._shapes_preview(selection_to_image_box(self.crop_preview, self.crop_image_size))

    def _shape_kind_changed(self, _index=None):
        if self.selected_tool == 'Shapes → PNG':
            self._show_tool_controls('Shapes → PNG')
            self._refresh_shapes_overlay()

    def add_shape(self):
        box = selection_to_image_box(self.crop_preview, self.crop_image_size)
        if box is None:
            self.status.setText('Arraste sobre a imagem para desenhar a forma antes de adicioná-la.')
            return
        if not re.fullmatch(r'#[0-9A-Fa-f]{6}', self.sh_color.text()):
            self.status.setText('A cor deve estar no formato #RRGGBB.')
            return
        if len(self.shape_items) >= SHAPE_MAX_ITEMS:
            self.status.setText(f'Limite de {SHAPE_MAX_ITEMS} formas por imagem.')
            return
        self.shape_items.append(self._shape_from_box(box))
        self.crop_preview.clear_selection()
        self._refresh_shapes_overlay(); self._update_shape_help()

    def undo_shape(self):
        if self.shape_items:
            self.shape_items.pop()
            self._refresh_shapes_overlay(); self._update_shape_help()

    def _redact_mode_changed(self, _index=0):
        if self.selected_tool == 'Redact → PNG':
            self._show_tool_controls('Redact → PNG')
            self._refresh_redact_overlay()

    # --- compressão: predefinições e estimativa ------------------------
    def _preset_changed(self, index: int):
        quality = QUALITY_PRESETS[index][1]
        if quality is not None and self.quality.value() != quality:
            self.quality.setValue(quality)

    def _quality_changed(self, value: int):
        match = next((i for i, (_label, q) in enumerate(QUALITY_PRESETS) if q == value), len(QUALITY_PRESETS) - 1)
        if self.compress_preset.currentIndex() != match:
            self.compress_preset.blockSignals(True); self.compress_preset.setCurrentIndex(match); self.compress_preset.blockSignals(False)
        if self.selected_tool == 'Compress → JPEG' and self._pil_image is not None:
            self._estimate_timer.start()

    def _load_estimate_source(self):
        self._pil_image = None
        width, height = self.crop_image_size
        if not (self.files and len(self.files) == 1 and width and height):
            return
        if width * height > ESTIMATE_MAX_PIXELS:
            self.tool_hint.setText('Imagem grande: a estimativa de tamanho não é feita na prévia; o resultado real aparece depois de comprimir.')
            return
        try:
            self._pil_image = open_image(source_file(self.files[0]))
        except Exception as error:
            self.tool_hint.setText('Estimativa indisponível: ' + str(error)[:120])
            return
        self._run_estimate()

    @staticmethod
    def format_size(size: int) -> str:
        return f'{size / 1024:,.0f} KB' if size < 1024 * 1024 else f'{size / 1024 / 1024:,.1f} MB'

    def _run_estimate(self):
        if self.selected_tool != 'Compress → JPEG' or self._pil_image is None or len(self.files) != 1:
            return
        try:
            data = jpeg_bytes(self._pil_image, self.quality.value(), self._pil_image.info.get('icc_profile'))
            original = Path(self.files[0]).stat().st_size
        except Exception as error:
            self.tool_hint.setText('Estimativa indisponível: ' + str(error)[:120])
            return
        pixmap = QPixmap()
        if pixmap.loadFromData(data, 'JPEG'):
            self.static_preview.set_preview_pixmap(pixmap)
        change = 100 * (len(data) - original) / original if original else 0
        verdict = ' O JPEG ficará maior que o original: prefira uma qualidade menor ou mantenha o arquivo.' if len(data) >= original else ''
        self.tool_hint.setText(f'Original: {self.format_size(original)} · estimado: {self.format_size(len(data))} ({change:+.0f}%). A prévia mostra a imagem com esta qualidade.{verdict}')
        self.estimate = (original, len(data))

    def _clear_crop_selection(self, _checked=False):
        self.crop_preview.clear_selection()          # o bool de clicked viraria emit=False e os campos não seriam atualizados (0.9.28)

    def _aspect_changed(self, index: int):
        ratio = ASPECTS[index][1]
        if ratio == 'original':
            width, height = self.crop_image_size
            ratio = width / height if width and height else None
        self.crop_preview.set_aspect(ratio)

    @staticmethod
    def output_size(image_size: tuple[int, int], max_side: int, rotation: int) -> tuple[int, int]:
        """Tamanho aproximado após 'largura máxima' (lado maior, sem ampliar) e rotação, como no motor."""
        width, height = image_size
        if max_side and max(width, height) > max_side:
            scale = max_side / max(width, height)
            width, height = max(1, round(width * scale)), max(1, round(height * scale))
        return (height, width) if rotation % 180 else (width, height)

    def _conversion_changed(self, _value=None):
        target = self.selected_tool
        if self.stage.currentIndex() != STAGE_STATIC or not all(self.crop_image_size):
            return
        if target in BASIC_CONVERSIONS:
            rotation = self.rotation.currentIndex() * 90
            self.static_preview.set_rotation(rotation)
            out_w, out_h = self.output_size(self.crop_image_size, self.width.value(), rotation)
            self.tool_hint.setText(f'Original: {self.crop_image_size[0]} × {self.crop_image_size[1]} px · resultado aproximado: {out_w} × {out_h} px. A imagem nunca é ampliada.')
        else:
            self.static_preview.set_rotation(0)

    def _annotation_position_picked(self, x: int, y: int):
        self._syncing = True
        self.annotation_x.setValue(x); self.annotation_y.setValue(y)
        self._syncing = False

    def _annotation_spin_changed(self, _value: int):
        if not self._syncing:
            self.annotate_preview.set_position(self.annotation_x.value(), self.annotation_y.value())

    def _annotation_style_changed(self, _value=None):
        self.annotate_preview.set_text(self.annotation.text(), self.annotation_color.text(), self.annotation_size.value())

    def _backdrop_style_picked(self, style_id: str):
        self.backdrop_style = style_id
        if self.selected_tool == 'Backdrop → PNG':
            self._show_tool_controls('Backdrop → PNG')
        self._backdrop_changed()

    def _refresh_custom_swatch(self):
        color = self.backdrop_color.text()
        if QColor(color).isValid():
            self.backdrop_buttons['custom'].setIcon(QIcon(swatch_pixmap('solid', (color,), 22, plus=True)))

    def _backdrop_changed(self, _value=None):
        self._refresh_custom_swatch()
        if self.selected_tool != 'Backdrop → PNG' or getattr(self, '_syncing', False) or len(self.files) != 1 or not self.crop_image_size[0]:
            return
        try:
            pixmap, size = self._load_pixmap(self.files[0])
        except Exception:
            return
        ratio = self.backdrop_ratio.currentText().lower()
        (width, height), _origin = backdrop_layout(size[0], size[1], self.backdrop_padding.value(), ratio)
        too_big = width > 10000 or height > 10000 or width * height > 40_000_000
        self.run_button.setEnabled(not too_big)
        if too_big:
            self.tool_hint.setText('O resultado ficaria grande demais (máx. 10000 px por lado e 40 megapixels); reduza a margem.')
            return
        self.static_preview.set_preview_pixmap(backdrop_preview_pixmap(pixmap, self.backdrop_style, self.backdrop_color.text(), self.backdrop_padding.value(),
                                                                       self.backdrop_radius.value(), self.backdrop_shadow.value(), ratio))
        self.stage.setCurrentIndex(STAGE_STATIC)
        self.tool_hint.setText(f'Resultado: {width} × {height} px, imagem opaca. A prévia aproxima a sombra.')

    # --- colagem: ordem e miniaturas -----------------------------------
    def _collage_thumb(self, path: str):
        if path in self._collage_thumbs:
            return self._collage_thumbs[path]
        thumb = None
        try:
            from PIL.ImageQt import ImageQt
            from PIL import Image
            with open_image(source_file(path)) as opened:
                size = opened.size
                small = opened.copy()
            small.thumbnail((320, 320), Image.Resampling.LANCZOS)
            thumb = (QPixmap.fromImage(QImage(ImageQt(small.convert('RGBA')))), size)
            small.close()
        except Exception:
            thumb = None
        if len(self._collage_thumbs) >= 48:
            self._collage_thumbs.pop(next(iter(self._collage_thumbs)))
        self._collage_thumbs[path] = thumb
        return thumb

    def _refresh_collage_list(self, select: int | None = None):
        current = self.collage_list.currentRow() if select is None else select
        self.collage_list.blockSignals(True)
        self.collage_list.clear()
        merging = self.selected_tool == 'Merge PDFs'
        for number, path in enumerate(self.files, 1):
            label = f'{number}  ·  {Path(path).name}'
            if merging:
                pages = (self.pdf_stage.infos.get(path) or {}).get('pages')
                chosen = self.merge_ranges.get(path, '')
                label += (f'  ·  {pages} pág.' if pages else '') + (f'  ·  páginas {chosen}' if chosen else '')
            self.collage_list.addItem(label)
        if self.files:
            self.collage_list.setCurrentRow(max(0, min(current, len(self.files) - 1)))
        self.collage_list.blockSignals(False)
        self._update_collage_buttons()

    def _update_collage_buttons(self):
        row, count = self.collage_list.currentRow(), len(self.files)
        self.collage_up_button.setEnabled(row > 0)
        self.collage_down_button.setEnabled(0 <= row < count - 1)
        self.collage_remove_button.setEnabled(0 <= row < count and count > 0)

    def _after_collage_order_changed(self, select: int):
        shown = [Path(path).name for path in self.files[:2]]
        suffix = f' +{len(self.files) - 2}' if len(self.files) > 2 else ''
        self.files_label.setText('  ·  '.join(shown) + suffix if self.files else 'Nenhum arquivo selecionado')
        self.status.setText(f'{len(self.files)} {"arquivo" if len(self.files) == 1 else "arquivos"} na sessão.' if self.files else 'Processamento local • originais preservados')
        self._refresh_collage_list(select)
        self._ordered_changed()

    def _collage_rows_moved(self, _parent, start, end, _destination, row):
        """A lista foi reordenada com o mouse: a ordem de `self.files` acompanha (a lista é refeita logo depois, com a numeração certa)."""
        if not self._is_ordered(self.selected_tool) or start != end or not 0 <= start < len(self.files):
            return
        target = row if row <= start else row - 1
        target = max(0, min(target, len(self.files) - 1))
        item = self.files.pop(start); self.files.insert(target, item)
        QTimer.singleShot(0, lambda: self._after_collage_order_changed(target))

    def move_collage_item(self, delta: int):
        row = self.collage_list.currentRow(); target = row + delta
        if not self._is_ordered(self.selected_tool) or not 0 <= row < len(self.files) or not 0 <= target < len(self.files):
            return
        self.files[row], self.files[target] = self.files[target], self.files[row]
        self._after_collage_order_changed(target)

    def remove_collage_item(self):
        row = self.collage_list.currentRow()
        if not self._is_ordered(self.selected_tool) or not 0 <= row < len(self.files):
            return
        del self.files[row]
        self._after_collage_order_changed(min(row, len(self.files) - 1))

    @staticmethod
    def _is_ordered(target) -> bool:
        return target in ORDERED_TARGETS or target == 'Merge PDFs'

    # --- Unir PDFs: ordem, intervalo por arquivo e total -----------------
    def _merge_state(self):
        """(total de páginas, problemas, ainda lendo) da lista atual de «Unir PDFs»."""
        total, problems, pending = 0, [], False
        for path in self.files:
            info = self.pdf_stage.infos.get(path)
            name = Path(path).name
            if info is None:
                pending = True; continue
            if info.get('error'):
                problems.append(f'{name}: {info["error"]}'); continue
            if info.get('encrypted'):
                problems.append(f'{name}: protegido por senha.'); continue
            try:
                total += len(pdfinfo.parse_page_range(self.merge_ranges.get(path, ''), info.get('pages') or 0))
            except pdfinfo.PdfError as error:
                problems.append(f'{name}: {error}')
        return total, problems, pending

    def _merge_changed(self, _value=None):
        if self.selected_tool != 'Merge PDFs' or getattr(self, '_syncing', False):
            return
        if list(self.files) != self.pdf_stage.paths:
            self.pdf_stage.set_paths(self.files)
        self._refresh_collage_list()
        row = self.collage_list.currentRow()
        self.merge_pages.setEnabled(0 <= row < len(self.files))
        total, problems, pending = self._merge_state()
        count = len(self.files)
        if count < 2:
            text, ready = 'Escolha pelo menos dois PDFs (use «Abrir arquivo» para adicionar).', False
        elif problems:
            text, ready = problems[0] + (f' (+{len(problems) - 1} outros)' if len(problems) > 1 else ''), False
        elif pending:
            text, ready = 'Lendo os PDFs…', False
        elif total > pdfinfo.PDF_MAX_PAGES:
            text, ready = f'O PDF unido teria {total} páginas; o limite é {pdfinfo.PDF_MAX_PAGES}. Tire arquivos ou escolha menos páginas.', False
        elif total < 1:
            text, ready = 'Nenhuma página escolhida.', False
        else:
            text, ready = f'{total} {"página" if total == 1 else "páginas"} no PDF unido, vindas de {count} arquivos.', True
        self.merge_info.setText(text)
        self.run_button.setEnabled(ready)

    def _merge_row_changed(self, row):
        if self.selected_tool != 'Merge PDFs' or not 0 <= row < len(self.files):
            return
        path = self.files[row]
        self.merge_pages.blockSignals(True); self.merge_pages.setText(self.merge_ranges.get(path, '')); self.merge_pages.blockSignals(False)
        self.pdf_stage.select_path(path)

    def _merge_range_edited(self, text):
        row = self.collage_list.currentRow()
        if self.selected_tool != 'Merge PDFs' or not 0 <= row < len(self.files):
            return
        self.merge_ranges[self.files[row]] = text.strip()
        self._merge_changed()

    def _merge_options(self) -> dict:
        ranges = [self.merge_ranges.get(path, '').strip() for path in self.files]
        return {'merge_ranges': ranges} if any(ranges) else {}

    def _ordered_changed(self, _value=None):
        if self.selected_tool == 'Merge PDFs':
            self._merge_changed()
        elif self.selected_tool == ONEPDF:
            self._onepdf_changed()
        else:
            self._collage_changed()

    def _onepdf_page_changed(self, _index=None):
        if self.selected_tool == ONEPDF:
            self._show_tool_controls(ONEPDF)
            self._onepdf_changed()

    def _onepdf_ocr_changed(self, _index=None):
        if self.selected_tool == ONEPDF:
            self._show_tool_controls(ONEPDF)
            self._onepdf_changed()

    def _onepdf_values(self) -> dict:
        ocr_index = max(0, self.pdf_ocr.currentIndex())
        return {'pdf_page': tuple(PDF_PAGES)[max(0, self.pdf_page.currentIndex())], 'pdf_margin': self.pdf_margin.value(), 'pdf_ocr': 'off' if ocr_index == 0 else tuple(ocr.LANGS)[ocr_index - 1]}

    def _onepdf_changed(self, _value=None):
        if self.selected_tool != ONEPDF or getattr(self, '_syncing', False):
            return
        self._refresh_collage_list()
        count = len(self.files)
        if count < 2:
            self._stage_message('Escolha duas ou mais imagens para montar o PDF.')
            self.tool_hint.setText('Use "Abrir arquivos" para adicionar mais imagens; a ordem da lista é a ordem das páginas.')
            self.run_button.setEnabled(False)
            return
        if count > PDF_MAX_PAGES:
            self._stage_message(f'O PDF aceita até {PDF_MAX_PAGES} imagens; há {count} na sessão.')
            self.run_button.setEnabled(False)
            return
        values = self._onepdf_values()
        if values['pdf_ocr'] != 'off':
            problem = ''
            ready, message = ocr.status()
            if values['pdf_page'] != 'image': problem = 'O texto pesquisável (OCR) só vale com as páginas «Do tamanho da imagem».'
            elif count > PDF_OCR_MAX_PAGES: problem = f'Com OCR, o PDF aceita até {PDF_OCR_MAX_PAGES} imagens (cada página leva alguns segundos); há {count}.'
            elif not ready: problem = message
            if problem:
                self.tool_hint.setText(problem); self.run_button.setEnabled(False)
                return
        self.static_preview.set_preview_pixmap(pdf_pages_pixmap([Path(path).name for path in self.files], values['pdf_page'], values['pdf_margin'],
                                                                thumbs=[self._collage_thumb(path) for path in self.files]))
        self.static_preview.set_rotation(0)
        self.stage.setCurrentIndex(STAGE_STATIC)
        label = PDF_PAGES[values['pdf_page']][0]
        self.tool_hint.setText(f'{count} páginas na ordem da lista, {"cada uma do tamanho da imagem" if values["pdf_page"] == "image" else label + ", orientação conforme a imagem"}.' + (' Cada página passa pelo OCR (alguns segundos cada).' if values['pdf_ocr'] != 'off' else ''))
        self.run_button.setEnabled(True)

    def _collage_changed(self, _value=None):
        if self.selected_tool != 'Collage → PNG' or getattr(self, '_syncing', False):
            return
        self._refresh_collage_list()
        count = len(self.files)
        if count < COLLAGE_MIN:
            self._stage_message('Escolha duas ou mais imagens para montar a colagem.')
            self.tool_hint.setText('Use "Abrir arquivos" para adicionar mais imagens; a ordem da lista é a ordem na colagem.')
            return
        if count > COLLAGE_MAX:
            self._stage_message(f'A colagem aceita até {COLLAGE_MAX} imagens; há {count} na sessão.')
            return
        columns, cell, gap = self.collage_columns.value(), self.collage_cell.value(), self.collage_gap.value()
        (width, height), _origins = collage_layout(count, columns, cell, gap)
        self.static_preview.set_preview_pixmap(collage_layout_pixmap([Path(path).name for path in self.files], columns, cell, gap, self.background.text(),
                                                                     thumbs=[self._collage_thumb(path) for path in self.files]))
        self.stage.setCurrentIndex(STAGE_STATIC)
        too_big = width > 10000 or height > 10000 or width * height > 40_000_000
        self.tool_hint.setText(('A colagem ficaria grande demais (máx. 10000 px por lado e 40 megapixels); reduza a célula ou o espaço.' if too_big
                                else f'Resultado: {width} × {height} px, {count} imagens. Cada imagem cabe inteira na célula e não é ampliada.'))
        self.run_button.setEnabled(not too_big)

    def _canvas_changed(self, _value=None):
        if self._syncing:
            return
        self.canvas_preview.set_canvas(self.canvas_width.value(), self.canvas_height.value(), self.background.text())
        if self.crop_image_size[0] and self.selected_tool == 'Canvas → PNG':
            too_small = self.canvas_preview.invalid
            self.tool_hint.setText(f'O canvas precisa ter pelo menos {self.crop_image_size[0]} × {self.crop_image_size[1]} px (tamanho da imagem).' if too_small
                                   else f'Resultado: {self.canvas_width.value()} × {self.canvas_height.value()} px, com a imagem centralizada.')

    def _compat_operation_changed(self, _index: int):
        target = self.operation.currentData()
        if target in OPERATIONS and target != self.selected_tool:
            self.select_tool(target)

    def select_feature(self, item):
        self.select_tool(item.data(Qt.ItemDataRole.UserRole))

    def update_options(self):
        target = self.operation.currentData()
        if target:
            self._show_tool_controls(target)

    # ------------------------------------------------------------------
    # arquivos
    # ------------------------------------------------------------------
    def set_files(self, paths: list[str], target: str | None = None):
        self._clear_passwords()
        self._redact_reset(); self._form_reset()
        self.files = list(dict.fromkeys(str(path) for path in paths))
        self.to_folder.blockSignals(True); self.to_folder.setChecked(len(self.files) > 1); self.to_folder.blockSignals(False)       # várias imagens → pasta numerada por padrão
        if self.files:
            shown = [Path(path).name for path in self.files[:2]]
            suffix = f' +{len(self.files) - 2}' if len(self.files) > 2 else ''
            self.files_label.setText('  ·  '.join(shown) + suffix)
            ext = Path(self.files[0]).suffix.lower()
            category = 'images' if ext in IMAGE_SUFFIXES else ('pdf' if ext == '.pdf' else ('audio' if ext in AUDIO_SUFFIXES else None))
            category = category or FUTURE_SUFFIXES.get(ext)
            if category:
                self.select_category(category)
                if category == 'audio' and not target and ext in AUDIO_SUFFIXES:
                    target = AUDIO_INFO          # arquivo de áudio solto: abre «Informações» (a roda continua a um clique)
            for control in (self.crop_x, self.crop_y, self.crop_width, self.crop_height):
                control.setValue(0)
        else:
            self.files_label.setText('Nenhum arquivo selecionado')
        if target:
            self.select_tool(target)
        elif self.pages.currentWidget() is self.tool_page and self.selected_tool:
            self._prepare_stage(self.selected_tool)
        self.status.setText(f'{len(self.files)} {"arquivo" if len(self.files) == 1 else "arquivos"} na sessão.' if self.files else 'Processamento local • originais preservados')

    # --- soltar arquivos em qualquer parte da janela ---------------------
    def dragEnterEvent(self, event):
        mime = event.mimeData()
        if mime.hasUrls() and any(url.isLocalFile() for url in mime.urls()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        dropped = [QDir.toNativeSeparators(url.toLocalFile()) for url in event.mimeData().urls() if url.isLocalFile() and url.toLocalFile()]
        if not dropped:
            event.ignore()
            return
        event.acceptProposedAction()
        self.set_files([*self.files, *dropped], self.selected_tool if self.pages.currentWidget() is self.tool_page else None)

    def show_home(self):
        self.selected_tool = None
        for button in self.category_buttons.values():
            button.setChecked(False)
        self.pages.setCurrentWidget(self.home_page)

    def choose_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, 'Abrir arquivos locais', '', 'Todos os arquivos (*.*);;Imagens e PDFs (*.png *.jpg *.jpeg *.webp *.tif *.tiff *.bmp *.avif *.svg *.svgz *.ai *.emf *.wmf *.heic *.heif *.hif *.pdf)')
        if paths:
            self.set_files([*self.files, *paths], self.selected_tool if self.pages.currentWidget() is self.tool_page else None)

    def open_visual_crop(self):
        if len(self.files) != 1:
            QMessageBox.information(self, 'Recortar imagem', 'Escolha apenas uma imagem para abrir o editor visual.')
            return
        try:
            dialog = CropEditor(self.files[0], self)
            if dialog.exec() and dialog.coordinates:
                x, y, width, height = dialog.coordinates
                self.crop_preview.set_selection(QRectF(x, y, width, height))
                self._crop_selection_changed()
        except Exception as error:
            self.status.setText('Não foi possível abrir o editor: ' + str(error)[:180])

    # ------------------------------------------------------------------
    # execução e fila
    # ------------------------------------------------------------------
    def run_selected(self):
        target = self.selected_tool or self.operation.currentData()
        if not self.files:
            QMessageBox.information(self, 'Arquivo Local', 'Abra um arquivo antes de usar a ferramenta.')
            return
        if target == 'Crop → PNG' and (self.crop_width.value() < 1 or self.crop_height.value() < 1):
            self.status.setText('Marque a área de recorte sobre a imagem antes de continuar.')
            return
        redact_regions = []
        if target == 'Redact → PNG':
            if len(self.files) != 1:
                self.status.setText('Ocultar trabalha com uma imagem por vez.')
                return
            redact_regions = [list(region) for region in self.redact_regions]
            pending = selection_to_image_box(self.crop_preview, self.crop_image_size)
            if pending is not None:
                redact_regions.append(list(pending))
            if not redact_regions:
                self.status.setText('Marque pelo menos uma área para ocultar.')
                return
        shape_items = []
        if target == 'Shapes → PNG':
            if len(self.files) != 1:
                self.status.setText('Formas trabalha com uma imagem por vez.')
                return
            shape_items = [dict(item) for item in self.shape_items]
            pending = selection_to_image_box(self.crop_preview, self.crop_image_size)
            if pending is not None:
                shape_items.append(self._shape_from_box(pending))
            try:
                shape_items_from({'shape_items': shape_items}, self.crop_image_size)
            except ConversionError as error:
                self.status.setText(str(error)); return
        if target == 'Resize → PNG':
            mode, percent, width, height = self._resize_values()
            try:
                resize_target_size(self.crop_image_size if all(self.crop_image_size) else (1, 1), mode, percent, width, height)
            except ValueError as error:
                self.status.setText(str(error)); return
        if target == 'Rotate → PNG' and not any(self._rotate_values()):
            self.status.setText('Escolha um giro ou um espelhamento antes de salvar.')
            return
        if target == 'Adjust → PNG' and not (self.adjust_brightness.value() or self.adjust_contrast.value() or self.adjust_saturation.value() or self.adjust_flip.currentIndex()):
            self.status.setText('Escolha pelo menos um ajuste antes de salvar.')
            return
        if target == 'Annotate → PNG' and not self.annotation.text().strip():
            self.status.setText('Digite o texto da anotação.')
            self.annotation.setFocus()
            return
        if target == 'Collage → PNG' and not COLLAGE_MIN <= len(self.files) <= COLLAGE_MAX:
            self.status.setText(f'Escolha de {COLLAGE_MIN} a {COLLAGE_MAX} imagens para a colagem.')
            return
        if target == ONEPDF and not 2 <= len(self.files) <= PDF_MAX_PAGES:
            self.status.setText(f'Escolha de 2 a {PDF_MAX_PAGES} imagens para o PDF.')
            return
        if target == ONEPDF and self._onepdf_values()['pdf_ocr'] != 'off':
            ready, message = ocr.status()
            if not ready or self._onepdf_values()['pdf_page'] != 'image' or len(self.files) > PDF_OCR_MAX_PAGES:
                self.status.setText(message if not ready else f'Com OCR: páginas «Do tamanho da imagem» e até {PDF_OCR_MAX_PAGES} imagens.')
                return
        if target == 'Merge PDFs' and len(self.files) < 2:
            QMessageBox.information(self, 'Unir PDFs', 'Escolha pelo menos dois PDFs.')
            return
        options = {'width': self.width.value(), 'rotation': self.rotation.currentIndex() * 90, 'quality': self.quality.value(),
                   'crop_x': self.crop_x.value(), 'crop_y': self.crop_y.value(), 'crop_width': self.crop_width.value(), 'crop_height': self.crop_height.value(),
                   'canvas_width': self.canvas_width.value(), 'canvas_height': self.canvas_height.value(), 'background': self.background.text(),
                   'annotation': self.annotation.text(), 'annotation_size': self.annotation_size.value(), 'annotation_x': self.annotation_x.value(), 'annotation_y': self.annotation_y.value(),
                   'annotation_color': self.annotation_color.text(),
                   'collage_columns': self.collage_columns.value(), 'collage_cell': self.collage_cell.value(), 'collage_gap': self.collage_gap.value(),
                   'backdrop_style': self.backdrop_style, 'backdrop_padding': self.backdrop_padding.value(), 'backdrop_radius': self.backdrop_radius.value(),
                   'backdrop_shadow': self.backdrop_shadow.value(), 'backdrop_ratio': self.backdrop_ratio.currentText().lower()}
        if target == 'Shapes → PNG':
            options['shape_items'] = shape_items
        if target == ONEPDF:
            options.update(self._onepdf_values())
        if target == 'Levels → PNG':
            try:
                levels_options_from(self._levels_values())
            except ConversionError as error:
                self.status.setText(str(error)); return
            options.update(self._levels_values())
        if target in OCR_TARGETS:
            ready, message = ocr.status()
            if not ready:
                self.status.setText(message); return
            options.update(self._ocr_values())
        if target == BG_TARGET:
            ready, message = bgremove.status(self._bg_values()['bg_model'])
            if not ready:
                self.status.setText(message); return
            options.update(self._bg_values())
        if target == 'Sharpen → PNG':
            options.update(self._sharpen_values())
        if target == 'Watermark → PNG':
            values = self._watermark_values()
            try:
                watermark_options_from(values)
                if values['watermark_kind'] == 'image' and Path(values['watermark_image']).suffix.lower() not in IMAGE_INPUTS:
                    raise ConversionError('A marca d\'água precisa ser uma imagem suportada.')
            except ConversionError as error:
                self.status.setText(str(error)); return
            options.update(values)
        if target in tool_registry.FORMAT_TARGETS:
            key, quality, flatten = self._output_format_values()
            if not re.fullmatch(r'#[0-9A-Fa-f]{6}', flatten):
                self.status.setText('A cor que substitui a transparência deve estar no formato #RRGGBB.'); return
            options.update({'out_format': key, 'out_quality': quality, 'out_flatten': flatten})
        if target in ('PDF → Text', 'Extract PDF Images'):
            text, ready = self._pdftext_state()
            if not ready:
                self.status.setText(text); return
            options.update(self._pdftext_values() if target == 'PDF → Text' else self._embedded_values())
        if target in (PDF_PROTECT, PDF_UNPROTECT):
            text, ready = self._password_state()
            if not ready:
                self.status.setText(text); return
            options.update(self._password_values())
        if target == PDF_STAMP:
            text, ready = self._stamp_state()
            if not ready:
                self.status.setText(text); return
            options.update(self._stamp_values())
        if target == PDF_FORM:
            text, ready = self._form_state()
            if not ready:
                self.status.setText(text); return
            options.update(self._form_values())
        if target == PDF_REDACT:
            text, ready = self._redact_state()
            if not ready:
                self.status.setText(text); return
            options.update(self._redact_values())
        if target == AUDIO_CONVERT:
            text, ready = self._audioconvert_state()
            if not ready:
                self.status.setText(text); return
            options.update(self._audioconvert_values())
        if target == PDF_COMPRESS:
            text, ready = self._pdfcompress_state()
            if not ready:
                self.status.setText(text); return
            options.update(self._pdfcompress_values())
        if target == PDF_CLEAN:
            _details, text, ready = self._pdfclean_state()
            if not ready:
                self.status.setText(text); return
            options.update(self._pdfclean_values())
        if target in PDF_OCR_TARGETS:
            text, ready = self._pdfocr_state()
            if not ready:
                self.status.setText(text); return
            options.update(self._pdfocr_values())
        if target == 'Organize PDF':
            if not self.organizer.list.count() or self.organizer.error or not self.organizer.is_modified():
                self.status.setText('Mude alguma coisa nas páginas antes de salvar.'); return
            options['organize_pages'] = self.organizer.option_value()
        if target == 'Split PDF':
            text, ready = self._split_state()
            if not ready:
                self.status.setText(text); return
            options.update(self._split_values())
        if target == 'PDF → Images':
            problem = self._pdfimg_problem()
            if problem:
                self.status.setText(problem); return
            options.update(self._pdfimg_values())
        if target == 'Merge PDFs':
            _total, problems, pending = self._merge_state()
            if problems or pending:
                self.status.setText(problems[0] if problems else 'Aguarde a leitura dos PDFs.'); return
            options.update(self._merge_options())
        if target == 'Rotate → PNG':
            angle, flip = self._rotate_values()
            options.update({'rotate_angle': angle, 'rotate_flip': flip})
        if target == 'Resize → PNG':
            mode, percent, width, height = self._resize_values()
            options.update({'resize_mode': mode, 'resize_percent': percent, 'resize_width': width, 'resize_height': height})
        if target == 'Backdrop → PNG':
            options['background'] = self.backdrop_color.text()
        if target == 'Adjust → PNG':
            options.update({'adjust_brightness': self.adjust_brightness.value(), 'adjust_contrast': self.adjust_contrast.value(), 'adjust_saturation': self.adjust_saturation.value(), 'adjust_flip': self.adjust_flip.currentIndex()})
        if target == 'Redact → PNG':
            options.update({'redact_regions': redact_regions, 'redact_mode': 'pixelate' if self.redact_mode.currentIndex() == 1 else 'black', 'redact_block': self.redact_block.value()})
        if self._has_vector():
            options['vector_width'] = self.vector_width.value()
        if self._folder_mode(target):
            options['to_folder'] = 'on'
            options['rename_start'] = self.rename_start.value()
        if self._renameable(target) and self.rename_pattern.text().strip():
            values = self._rename_values()
            try:
                rename_options_from(values)
            except ConversionError as error:
                self.status.setText(str(error)); return
            options.update(values)
        self.controller.start_job(self.files, target, options)
        if target in (PDF_PROTECT, PDF_UNPROTECT):
            self._clear_passwords(); self._password_changed()
        if target == PDF_REDACT:
            self._redact_reset(); self._redact_changed()
        if target == PDF_FORM:
            self._form_reset(); self._form_infos()

    def refresh_queue(self):
        active = self.controller.active_job
        if active:
            filename = Path(active['paths'][0]).name
            self.status.setText(f'Processando {LABELS.get(active["target"], active["target"])} · {filename}')
            self.progress.setRange(0, 0)
            self.progress.setVisible(True)
        else:
            self.progress.setRange(0, 1); self.progress.setValue(0)
            self.progress.setVisible(False)
        self.cancel_button.setEnabled(active is not None and self.controller.worker is not None)
        self.cancel_button.setVisible(active is not None)
        self.queue_view.clear()
        for index, job in enumerate(self.controller.pending_jobs, 1):
            name = Path(job['paths'][0]).name
            self.queue_view.addItem(f'{index}  ·  {LABELS.get(job["target"], job["target"])}  ·  {name}')
        has_queue = bool(self.controller.pending_jobs)
        self.queue_title.setVisible(has_queue)
        self.queue_view.setVisible(has_queue)

    def refresh_capabilities_view(self, recheck=False):
        if recheck:
            hotkey = self.controller.capabilities.get('shift_f9', (False, 'Atalho não registrado.'))
            self.controller.capabilities = probe_capabilities(); self.controller.capabilities['shift_f9'] = hotkey
        self.capability_label.setToolTip(describe_capabilities(self.controller.capabilities))
        for widget, key in ((self.image_list, 'images'), (self.pdf_list, 'pdf')):
            available, reason = self.controller.capabilities.get(key, (False, 'Não verificado.'))
            for index in range(widget.count()):
                item = widget.item(index)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEnabled if available else item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
                item.setToolTip('Disponível.' if available else reason)
        if self.pages.currentWidget() is self.category_page:
            self.select_category(self.active_category)

    def recheck_capabilities(self):
        self.refresh_capabilities_view(recheck=True)

    def clear_queue(self):
        removed = self.controller.clear_pending()
        self.status.setText(f'{removed} tarefa(s) pendente(s) removida(s).')

    def on_job_finished(self, success, message, outputs, paths, target):
        if success:
            self.last_output_dir = str(Path(outputs[0]).parent) if outputs else ''
            self.open_button.setEnabled(bool(self.last_output_dir))
            detail = f'Concluído · {len(outputs)} resultado(s). Originais preservados.'
            if target in ('Compress → JPEG', 'Compress PDF') and outputs and paths:
                try:
                    before = sum(Path(path).stat().st_size for path in paths); after = sum(Path(path).stat().st_size for path in outputs)
                    delta = 100 * (before - after) / before if before else 0
                    detail += f' {before:,} → {after:,} bytes ({delta:+.1f}%).'
                except OSError:
                    pass
            self.status.setText(detail)
            report = list(getattr(self.controller, 'last_report', []) or [])
            self.show_report(Path(paths[0]).name if len(paths) == 1 else f'{len(paths)} arquivos', report)
            for output in outputs:
                self.history.insertItem(0, f'{Path(paths[0]).name} → {Path(output).name}')
                if report:
                    self.history.item(0).setToolTip('\n'.join('• ' + line for line in report))
            while self.history.count() > 12:
                self.history.takeItem(self.history.count() - 1)
        elif message.startswith('Cancelado'):
            self.status.setText(message)
        else:
            self.status.setText('Falha: ' + message[:240])

    def show_report(self, origin: str, lines: list[str]):
        """Mostra o relatório de perdas do último resultado; fica oculto quando não há nada a dizer."""
        self.last_report_lines = list(lines)
        if not lines:
            self.report_card.hide()
            return
        self.report_title.setText(f'O que mudou · {origin}')
        self.report_label.setText('\n'.join('• ' + line for line in lines))
        self.report_card.show()
        QTimer.singleShot(0, lambda: self.settings_scroll.ensureWidgetVisible(self.report_card, 0, 20))

    def open_output(self):
        if self.last_output_dir:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.last_output_dir))

    def closeEvent(self, event):
        if self.allow_close:
            self.pdf_stage.shutdown(); self.organizer.shutdown(); self.audio_stage.shutdown()
            event.accept()
        else:
            self.hide()
            event.ignore()
