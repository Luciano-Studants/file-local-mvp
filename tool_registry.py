"""Registro central das ferramentas de imagem — fonte única de verdade.

Antes, cada ferramenta nova exigia editar de 8 a 10 lugares (motor, bandeja, painel, roda, ícones) e esquecer um deles
só aparecia em tempo de execução. Agora a identidade da ferramenta (nome, sufixo, formato de saída, opções permitidas,
rótulos, ícone) vive aqui, sem depender de Qt, e as demais camadas derivam suas tabelas deste módulo.
`tests/test_architecture.py` confere que a interface (roda, controles do painel) cobre tudo o que está registrado.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ToolSpec:
    target: str                    # nome da operação no motor, ex.: 'Resize → PNG'
    key: str                       # id curto; a ação da roda é '__tool_<key>__'
    label: str                     # rótulo da fatia
    tip: str                       # descrição curta (dica da roda e do cartão)
    title: str                     # nome na fila/bandeja
    panel_title: str               # título no painel
    run_label: str                 # texto do botão de executar
    suffix: str | None             # sufixo do arquivo de saída (None = nome padrão da operação)
    ext: str = 'png'
    icon: str = ''
    int_options: tuple[str, ...] = ()
    str_options: tuple[str, ...] = ()
    list_options: tuple[str, ...] = ()
    path_options: tuple[str, ...] = ()   # caminhos de arquivo (até 1024 caracteres; o motor valida de novo)
    single_file: bool = False      # True: o job aceita um arquivo por vez
    in_selection_wheel: bool = True  # aparece na roda de um arquivo (Shift+F9)
    risk: str = 'baixo'            # risco de implementação, usado só na documentação/ordem do plano
    group: str = ''                # grupo da roda ('' = fatia solta); ver GROUPS

    @property
    def action(self) -> str:
        return f'__tool_{self.key}__'


IMAGE_TOOLS: tuple[ToolSpec, ...] = (

    ToolSpec('Crop → PNG', 'crop', 'Recortar', 'Recortar a imagem marcando a área sobre ela', 'Recortar imagem → PNG', 'Recortar imagem',
             'Recortar e salvar PNG', 'recortada', icon='crop', int_options=('crop_x', 'crop_y', 'crop_width', 'crop_height'), group='transform'),

    ToolSpec('Resize → PNG', 'resize', 'Tamanho', 'Mudar o tamanho da imagem por porcentagem, por limite de largura e altura ou por medida exata',
             'Redimensionar imagem → PNG', 'Redimensionar imagem', 'Redimensionar e salvar PNG', 'redimensionada', icon='resize',
             int_options=('resize_percent', 'resize_width', 'resize_height'), str_options=('resize_mode',), group='transform'),

    ToolSpec('Rotate → PNG', 'rotate', 'Girar', 'Girar 90° ou 180° e espelhar a imagem, sem perda de qualidade', 'Girar ou espelhar imagem → PNG',
             'Girar imagem', 'Girar e salvar PNG', 'girada', icon='rotate', int_options=('rotate_angle', 'rotate_flip'), group='transform'),

    ToolSpec('Canvas → PNG', 'canvas', 'Canvas', 'Aumentar a área ao redor da imagem, com uma cor de fundo', 'Adicionar canvas → PNG',
             'Canvas para imagem', 'Aplicar canvas e salvar PNG', 'canvas', icon='canvas',
             int_options=('canvas_width', 'canvas_height'), str_options=('background',), group='transform'),

    ToolSpec('Compress → JPEG', 'compress', 'Comprimir', 'Salvar em JPEG com a qualidade escolhida', 'Comprimir → JPEG (com perda)',
             'Comprimir JPEG', 'Comprimir e salvar JPEG', 'comprimida', ext='jpg', icon='compress', group='transform'),

    ToolSpec('Adjust → PNG', 'adjust', 'Ajustar', 'Mudar brilho, contraste e saturação, ou espelhar a imagem', 'Ajustar brilho, contraste e cor → PNG',
             'Ajustar imagem', 'Ajustar e salvar PNG', 'ajustada', icon='adjust',
             int_options=('adjust_brightness', 'adjust_contrast', 'adjust_saturation', 'adjust_flip'), group='look'),

    ToolSpec('Levels → PNG', 'levels', 'Níveis', 'Corrigir sombras, realces e tons médios olhando o histograma, ou deixar o ajuste automático', 'Níveis e auto-níveis → PNG',
             'Níveis da imagem', 'Aplicar níveis e salvar PNG', 'com-niveis', icon='levels',
             int_options=('levels_auto', 'levels_black', 'levels_white', 'levels_gamma'), group='look'),

    ToolSpec('Sharpen → PNG', 'sharpen', 'Nitidez', 'Realçar bordas (nitidez) ou suavizar a imagem (desfoque)', 'Nitidez e desfoque → PNG',
             'Nitidez e desfoque', 'Aplicar e salvar PNG', 'com-efeito', icon='sharpen',
             int_options=('sharpen_amount', 'sharpen_radius'), str_options=('sharpen_mode',), group='look'),

    ToolSpec('Backdrop → PNG', 'backdrop', 'Fundo', 'Colocar a imagem sobre um fundo, com margem, cantos arredondados e sombra', 'Imagem com fundo → PNG',
             'Imagem com fundo', 'Salvar com fundo', 'com-fundo', icon='backdrop',
             int_options=('backdrop_padding', 'backdrop_radius', 'backdrop_shadow'), str_options=('backdrop_style', 'backdrop_ratio', 'background'), group='look'),

    ToolSpec('Remove Background → PNG', 'removebg', 'Sem fundo', 'Remover o fundo da imagem (offline, por rede neural) e salvar com transparência', 'Remover fundo → PNG (transparente)',
             'Remover fundo', 'Remover fundo e salvar PNG', 'sem-fundo', icon='removebg',
             int_options=('bg_feather',), str_options=('bg_model',), group='look', risk='alto'),

    ToolSpec('Annotate → PNG', 'annotate', 'Anotar', 'Escrever um texto sobre a imagem', 'Anotar imagem → PNG (achatado)',
             'Anotar imagem', 'Anotar e salvar PNG', 'anotada', icon='annotate',
             int_options=('annotation_x', 'annotation_y', 'annotation_size'), str_options=('annotation', 'annotation_color'), group='draw'),

    ToolSpec('Shapes → PNG', 'shapes', 'Formas', 'Desenhar retângulos, elipses, linhas e setas sobre a imagem, quantas precisar', 'Formas sobre a imagem → PNG',
             'Formas sobre a imagem', 'Desenhar e salvar PNG', 'com-formas', icon='shapes',
             list_options=('shape_items',), single_file=True, group='draw', risk='médio'),

    ToolSpec('Watermark → PNG', 'watermark', 'Marca', 'Colocar um texto ou logotipo semitransparente na imagem: num canto, no centro ou repetido na diagonal',
             "Marca d'água → PNG", "Marca d'água", 'Aplicar marca e salvar PNG', 'com-marca', icon='watermark',
             int_options=('watermark_scale', 'watermark_opacity', 'watermark_margin'),
             str_options=('watermark_kind', 'watermark_text', 'watermark_color', 'watermark_position'), path_options=('watermark_image',), group='draw', risk='médio'),
    ToolSpec('Redact → PNG', 'redact', 'Ocultar', 'Cobrir áreas da imagem com tarja preta ou pixelização', 'Ocultar áreas → PNG (gravado nos pixels)',
             'Ocultar áreas da imagem', 'Ocultar e salvar PNG', 'ocultada', icon='redact', int_options=('redact_block',),
             str_options=('redact_mode',), list_options=('redact_regions',), single_file=True, risk='médio', group='protect'),

    ToolSpec('Clean → PNG', 'clean', 'Metadados', 'Ver o que a imagem guarda além dos pixels e salvar uma cópia limpa', 'Cópia PNG sem metadados',
             'Cópia sem metadados', 'Salvar cópia sem metadados', 'sem-metadados', icon='metadata', group='protect'),

    ToolSpec('OCR → Text', 'ocr_text', 'Texto', 'Reconhecer o texto da imagem (OCR, offline) e salvar em um arquivo .txt', 'OCR da imagem → texto (.txt)',
             'Texto da imagem (OCR)', 'Reconhecer e salvar texto', 'texto', ext='txt', icon='ocr', str_options=('ocr_lang', 'ocr_psm'), group='read', risk='médio'),

    ToolSpec('OCR → PDF', 'ocr_pdf', 'PDF texto', 'Reconhecer o texto (OCR, offline) e salvar um PDF com a imagem e o texto pesquisável por baixo', 'OCR da imagem → PDF pesquisável',
             'PDF pesquisável (OCR)', 'Reconhecer e salvar PDF', 'pesquisavel', ext='pdf', icon='ocr', str_options=('ocr_lang', 'ocr_psm'), group='read', risk='médio'),

    ToolSpec('Images → One PDF', 'onepdf', 'PDF único', 'Juntar várias imagens em um único PDF, uma por página, na ordem da lista', 'Várias imagens → um PDF',
             'Várias imagens em um PDF', 'Criar PDF', None, ext='pdf', icon='onepdf',
             int_options=('pdf_margin',), str_options=('pdf_page', 'pdf_ocr'), in_selection_wheel=False),

    ToolSpec('Collage → PNG', 'collage', 'Colagem', 'Juntar de duas a doze imagens em um único PNG', 'Colagem de imagens → PNG',
             'Colagem de imagens', 'Criar colagem PNG', None, icon='collage',
             int_options=('collage_columns', 'collage_cell', 'collage_gap'), str_options=('background',), in_selection_wheel=False),
)

# grupos da roda: id → (rótulo ≤ 10 caracteres, descrição, ícone)
GROUPS = {
    'transform': ('Transformar', 'Recortar, redimensionar, girar, ampliar a área ou comprimir a imagem', 'resize'),
    'look': ('Ajustes', 'Ajustar cores e níveis, nitidez, fundo e remoção de fundo', 'adjust'),
    'draw': ('Desenhar', 'Escrever texto, desenhar formas e colocar marca d\'água', 'annotate'),
    'protect': ('Proteger', 'Ocultar áreas e remover metadados', 'redact'),
    'read': ('Ler texto', 'Reconhecer o texto da imagem (OCR): arquivo de texto ou PDF pesquisável', 'ocr'),
}
GROUP_PREFIX = '__group_'


def group_action(group: str) -> str:
    return f'{GROUP_PREFIX}{group}__'


def group_members(group: str, selection_only: bool = False) -> list['ToolSpec']:
    return [spec for spec in IMAGE_TOOLS if spec.group == group and (spec.in_selection_wheel or not selection_only)]


def wheel_layout(selection_only: bool = False) -> list[str]:
    """Fatias de primeiro nível na ordem do registro: o alvo da ferramenta solta ou o id do grupo (na primeira aparição)."""
    seen, layout = set(), []
    for spec in IMAGE_TOOLS:
        if selection_only and not spec.in_selection_wheel:
            continue
        if spec.group:
            if spec.group not in seen:
                seen.add(spec.group); layout.append(group_action(spec.group))
        else:
            layout.append(spec.target)
    return layout


def flat_targets(entries) -> list[str]:
    """Expande ids de grupo nos alvos das ferramentas (para testes e para a lista de operações)."""
    result = []
    for entry in entries:
        if isinstance(entry, str) and entry.startswith(GROUP_PREFIX):
            result.extend(spec.target for spec in group_members(entry[len(GROUP_PREFIX):-2]))
        else:
            result.append(entry)
    return result


# ---------------------------------------------------------------------------
# Roda do PDF (0.9.43): as 15 operações ficam em grupos com sub-roda, como nas imagens.
# REGRA DE DESIGN: uma roda nunca passa de MAX_SLICES fatias (a sub-roda já conta o «Voltar») e cada rótulo cabe em
# MAX_LABEL caracteres. Operação nova de PDF entra num grupo daqui (ou num grupo novo, se o primeiro nível ainda couber);
# tests/test_wheel_layout.py barra qualquer roda que estoure o limite.
# ---------------------------------------------------------------------------
MAX_SLICES = 8
MAX_LABEL = 13
PDF_GROUP_PREFIX = '__pdfgroup_'

# id → (rótulo, descrição, ícone, [(alvo, rótulo curto, descrição, ícone)])
PDF_GROUPS = {
    'read': ('Ler', 'Extrair texto e imagens, ou reconhecer um PDF digitalizado (OCR)', 'text', [
        ('PDF → Text', 'Texto', 'Exportar o texto das páginas', 'text'),
        ('Extract PDF Images', 'Imagens', 'Extrair as imagens embutidas', 'image'),
        ('PDF OCR → PDF', 'OCR → PDF', 'Reconhecer um PDF digitalizado e gerar um PDF pesquisável', 'ocr'),
        ('PDF OCR → Text', 'OCR → texto', 'Reconhecer o texto de um PDF digitalizado', 'ocr'),
    ]),
    'pages': ('Páginas', 'Dividir, unir, reordenar ou salvar as páginas como imagens', 'onepdf', [
        ('PDF → Images', 'Em imagens', 'Salvar cada página como imagem', 'image'),
        ('Split PDF', 'Dividir', 'Separar em partes ou extrair páginas', 'split'),
        ('Organize PDF', 'Organizar', 'Girar, excluir, duplicar e reordenar', 'onepdf'),
        ('Merge PDFs', 'Unir', 'Combinar dois ou mais arquivos', 'merge'),
    ]),
    'edit': ('Editar', 'Numerar e carimbar, preencher e assinar, tarjar conteúdo', 'annotate', [
        ('Stamp PDF', 'Carimbar', 'Números de página, texto e marca d\'água', 'watermark'),
        ('Fill PDF', 'Preencher', 'Campos do formulário e imagem de assinatura', 'annotate'),
        ('Redact PDF', 'Tarjar', 'Cobrir áreas, termos e dados pessoais', 'redact'),
    ]),
    'optimize': ('Otimizar', 'Reduzir o tamanho e limpar metadados', 'compress', [
        ('Compress PDF', 'Comprimir', 'Reduzir o tamanho do arquivo', 'compress'),
        ('Clean PDF', 'Metadados', 'Ver metadados e gerar uma cópia limpa', 'metadata'),
    ]),
    'secure': ('Senha', 'Proteger com senha ou remover a senha', 'lock', [
        ('Protect PDF', 'Proteger', 'Criptografar com senha (AES-256)', 'lock'),
        ('Unprotect PDF', 'Remover senha', 'Gerar uma cópia sem senha', 'lock'),
    ]),
}


def pdf_group_action(group: str) -> str:
    return f'{PDF_GROUP_PREFIX}{group}__'


def pdf_wheel_layout() -> list[str]:
    """Fatias de primeiro nível da roda do PDF (ids de grupo)."""
    return [pdf_group_action(group) for group in PDF_GROUPS]


def pdf_flat_targets() -> list[str]:
    """Todas as operações de PDF alcançáveis pela roda, na ordem dos grupos."""
    return [target for _l, _t, _i, members in PDF_GROUPS.values() for target, *_rest in members]


BY_TARGET = {spec.target: spec for spec in IMAGE_TOOLS}
BY_ACTION = {spec.action: spec for spec in IMAGE_TOOLS}
TARGETS = tuple(spec.target for spec in IMAGE_TOOLS)
PNG_TARGETS = frozenset(spec.target for spec in IMAGE_TOOLS if spec.ext == 'png')
# ferramentas que deixam escolher o formato de saída (as que geram PNG por padrão); «Comprimir» continua só JPEG
PDF_IMAGES = 'PDF → Images'
FORMAT_TARGETS = PNG_TARGETS | {PDF_IMAGES}      # «PDF → imagens» também usa o formato de saída (mas não é uma ferramenta de imagem)
# opções comuns às conversões de formato (não pertencem a uma ferramenta)
BASE_INT_OPTIONS = frozenset({'width', 'rotation', 'quality', 'out_quality', 'rename_start', 'rename_digits', 'rename_n', 'vector_width', 'pdf_dpi', 'split_every', 'img_min', 'stamp_size', 'stamp_opacity', 'stamp_margin', 'stamp_angle', 'stamp_start'})
BASE_PATH_OPTIONS = frozenset({'sign_image'})      # caminhos que não pertencem a uma ferramenta de imagem (assinatura visual do PDF)
BASE_LIST_OPTIONS = frozenset({'merge_ranges', 'organize_pages', 'redact_areas', 'redact_terms', 'form_values', 'sign_areas'})      # «Unir PDFs»: um intervalo de páginas (texto) por arquivo, na ordem da lista
BASE_STR_OPTIONS = frozenset({'background', 'out_format', 'out_flatten', 'rename_pattern', 'to_folder', 'pdf_pages', 'split_mode', 'split_ranges', 'text_mode', 'text_layout', 'ocr_skip', 'meta_info', 'meta_attach', 'meta_js', 'pdf_level', 'stamp_kind', 'stamp_text', 'stamp_position', 'stamp_color', 'stamp_bold', 'pdf_password', 'pdf_owner_password', 'perm_print', 'perm_copy', 'perm_edit', 'redact_patterns', 'form_flatten'})


def all_int_options() -> frozenset[str]:
    return BASE_INT_OPTIONS | {key for spec in IMAGE_TOOLS for key in spec.int_options}


def all_str_options() -> frozenset[str]:
    return BASE_STR_OPTIONS | {key for spec in IMAGE_TOOLS for key in spec.str_options}


def all_path_options() -> frozenset[str]:
    return BASE_PATH_OPTIONS | {key for spec in IMAGE_TOOLS for key in spec.path_options}


def all_list_options() -> frozenset[str]:
    return BASE_LIST_OPTIONS | {key for spec in IMAGE_TOOLS for key in spec.list_options}
