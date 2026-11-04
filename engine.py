"""Local conversion engine. No shell, network clients, deletion of inputs or archive extraction."""
from __future__ import annotations
import struct
import errno, json, os, re, shutil, stat, tempfile, warnings
from pathlib import Path

import audioconvert
import audiotags
import bgremove
import ocr
import pdfcompress
import pdfform
import pdfinfo
import pdfredact
import pdfstamp
import tool_registry

VERSION = '0.9.42-phase2-dev'
MAX_BYTES = 100 * 1024 * 1024
AUDIO_MAX_BYTES = 512 * 1024 * 1024      # áudio e vídeo de entrada (o arquivo é lido em fluxo pelo FFmpeg, não carregado na memória)
AUDIO_CONVERT='Convert Audio'
AUDIO_TAGS='Audio Tags'
AUDIO_TARGETS=(AUDIO_CONVERT,AUDIO_TAGS)
MAX_PIXELS = 40_000_000
MAX_OUTPUT = 512 * 1024 * 1024
COLLAGE_MIN, COLLAGE_MAX = 2, 12
AI_INPUTS = {'.ai'}                   # Adobe Illustrator com parte de PDF: desenhado pelo PDFium (ver illustrator.py)
METAFILE_INPUTS = {'.emf', '.wmf'}    # metarquivos do Windows: desenhados pelo GDI, só no Windows (ver metafile.py)
VECTOR_INPUTS = {'.svg', '.svgz'} | AI_INPUTS | METAFILE_INPUTS      # vetores: desenhados em pixels ao abrir (ver vector.py e illustrator.py)
HEIF_INPUTS = {'.heic', '.heif', '.hif'}   # HEIC/HEIF: leitura e gravação pelo pacote pillow-heif (opcional em tempo de execução)
IMAGE_INPUTS = {'.png', '.jpg', '.jpeg', '.webp', '.bmp', '.tif', '.tiff', '.avif'} | VECTOR_INPUTS | HEIF_INPUTS
VECTOR_WIDTH = None                    # largura (px) pedida para desenhar vetores; None = tamanho declarado no arquivo
VECTOR_MAX_WIDTH = 16384
IMAGE_OUTPUTS = {
    'PNG': 'png', 'JPEG': 'jpg', 'WEBP': 'webp', 'TIFF': 'tiff', 'BMP': 'bmp',
    **{spec.target: spec.ext for spec in tool_registry.IMAGE_TOOLS},     # ferramentas: definidas em tool_registry.py
}
# Fundos prontos da ferramenta «Fundo»: id → (rótulo, tipo, cores). 'custom' usa a cor escolhida pelo usuário.
BACKDROPS = {
    'sunset': ('Pôr do sol', 'gradient', ('#ff5f6d', '#ffc371', '#8e6bd1')),
    'peach': ('Pêssego', 'gradient', ('#ffd9b8', '#ffffff')),
    'aurora': ('Aurora', 'gradient', ('#43e7b5', '#3d7bf0', '#9b5de5')),
    'ocean': ('Oceano', 'gradient', ('#2193b0', '#6dd5ed')),
    'lavender': ('Lavanda', 'gradient', ('#c8b6ff', '#ffd6e8')),
    'graphite': ('Grafite', 'gradient', ('#434343', '#000000')),
    'white': ('Branco', 'solid', ('#ffffff',)), 'sun': ('Amarelo', 'solid', ('#f5c542',)),
    'lime': ('Lima', 'solid', ('#8bc34a',)), 'green': ('Verde', 'solid', ('#1e9e5a',)),
    'cyan': ('Ciano', 'solid', ('#3cc4d8',)), 'blue': ('Azul', 'solid', ('#3e5ce0',)),
    'navy': ('Marinho', 'solid', ('#1f2a44',)), 'violet': ('Violeta', 'solid', ('#7a4fd1',)),
}
BACKDROP_RATIOS = {'auto': None, '1:1': (1, 1), '16:9': (16, 9), '4:5': (4, 5)}
TOOL_SUFFIX = {spec.target: spec.suffix for spec in tool_registry.IMAGE_TOOLS if spec.suffix}
TOOL_SUFFIX[AUDIO_CONVERT]='convertido'
TOOL_SUFFIX[AUDIO_TAGS]='etiquetas'
RESIZE_MODES = ('percent', 'fit', 'exact')
RESIZE_MAX_SIDE = 10000
WATERMARK_POSITIONS = ('tl','tc','tr','ml','c','mr','bl','bc','br','tile')   # cantos, bordas, centro e repetida na diagonal
WATERMARK_KINDS = ('text','image')
WATERMARK_MAX_TEXT = 100
# formato de saída das ferramentas: id → (formato do Pillow, extensão, rótulo)
OUTPUT_FORMATS = {'png': ('PNG', 'png', 'PNG'), 'jpeg': ('JPEG', 'jpg', 'JPEG'), 'webp': ('WEBP', 'webp', 'WebP'), 'tiff': ('TIFF', 'tiff', 'TIFF'), 'bmp': ('BMP', 'bmp', 'BMP'), 'gif': ('GIF', 'gif', 'GIF'), 'ico': ('ICO', 'ico', 'ICO'), 'avif': ('AVIF', 'avif', 'AVIF'), 'heic': ('HEIF', 'heic', 'HEIC')}
ICO_SIZES = (16, 32, 48, 64, 128, 256)      # tamanhos padrão de um ícone; só entram os que cabem na imagem
ICO_MAX = 256
GIF_ALPHA_CUT = 128                          # GIF só tem transparência de 1 bit: alfa abaixo disso vira transparente
ROTATE_ANGLES = (0, 90, 180, 270)      # graus no sentido horário
ADJUST_RANGE = 100
REDACT_MAX_REGIONS = 50
REDACT_MODES = ('black', 'pixelate')
OPERATIONS = list(IMAGE_OUTPUTS) + ['Image → PDF', 'PDF → Text', 'PDF → Images', 'Merge PDFs', 'Split PDF', 'Organize PDF', 'Extract PDF Images', 'PDF OCR → PDF', 'PDF OCR → Text', 'Clean PDF', 'Compress PDF', 'Stamp PDF', 'Protect PDF', 'Unprotect PDF', 'Redact PDF', 'Fill PDF', AUDIO_CONVERT, AUDIO_TAGS]
RENAMEABLE_TARGETS = frozenset(IMAGE_OUTPUTS) | {'Image → PDF'}      # a colagem usa o mesmo padrão, com {nome} = «colagem»
class ConversionError(ValueError): pass

RENAME_TOKENS=('nome','n','sufixo','data')
RENAME_DEFAULT='{nome}-{sufixo}'
RENAME_MAX_PATTERN=120
RENAME_MAX_STEM=100                   # mesmo limite que `publish` aplica ao nome

def rename_options_from(job):
    """Lê o padrão de nome (`rename_pattern`; vazio = comportamento padrão), o primeiro número (`rename_start`, 0–999999), os dígitos (`rename_digits`, 1–6)
    e o número desta tarefa (`rename_n`, que a fila define para cada arquivo). Devolve None quando não há padrão."""
    pattern=job.get('rename_pattern','')
    if pattern is None: pattern=''
    if not isinstance(pattern,str): raise ConversionError('Padrão de nome inválido.')
    pattern=pattern.strip()
    if not pattern: return None
    if len(pattern)>RENAME_MAX_PATTERN: raise ConversionError(f'O padrão de nome aceita até {RENAME_MAX_PATTERN} caracteres.')
    if any(ord(char)<32 for char in pattern) or any(char in pattern for char in '/\\:*?"<>|'): raise ConversionError('O padrão de nome não pode ter / \\ : * ? " < > | nem caracteres de controle; a extensão é escolhida pela ferramenta.')
    leftover=re.sub(r'\{[^{}]*\}','',pattern)
    if '{' in leftover or '}' in leftover: raise ConversionError('Chaves do padrão desbalanceadas: use {nome}, {n}, {sufixo} ou {data}.')
    for token in re.findall(r'\{([^{}]*)\}',pattern):
        if token not in RENAME_TOKENS: raise ConversionError('Marcador {'+token+'} desconhecido: use {nome}, {n}, {sufixo} ou {data}.')
    try: start=int(job.get('rename_start',1));digits=int(job.get('rename_digits',1));number=job.get('rename_n');number=start if number is None else int(number)
    except (TypeError,ValueError): raise ConversionError('Numeração do nome inválida.')
    if not 0<=start<=999999 or not 1<=digits<=6 or not 0<=number<=9999999: raise ConversionError('O primeiro número fica entre 0 e 999999 e os dígitos entre 1 e 6.')
    return {'pattern':pattern,'start':start,'digits':digits,'n':number}

def rename_stem(options,name,suffix,today=None):
    """Aplica o padrão: {nome} nome original sem extensão, {n} número com zeros à esquerda, {sufixo} o da ferramenta, {data} AAAA-MM-DD.
    O {nome} é encurtado se o resultado passar do limite; o nome final nunca fica vazio nem termina em ponto ou espaço."""
    import datetime
    date=(today or datetime.date.today()).isoformat();number=str(options['n']).zfill(options['digits'])
    def fill(nome): return re.sub(r'\{(nome|n|sufixo|data)\}',lambda m:{'nome':nome,'n':number,'sufixo':suffix,'data':date}[m.group(1)],options['pattern'])
    stem=fill(name)
    if len(stem)>RENAME_MAX_STEM:
        excess=len(stem)-RENAME_MAX_STEM;count=options['pattern'].count('{nome}')
        if not count or len(name)<=excess//max(count,1)+1: raise ConversionError('O nome ficou longo demais; encurte o padrão.')
        keep=len(name)-(excess+count-1)//count;stem=fill(name[:keep])
    stem=re.sub(r'[<>:"/\\|?*\x00-\x1f]','_',stem).strip().rstrip('. ')
    if not stem: raise ConversionError('O padrão gerou um nome vazio.')
    return stem

BATCH_PREFIX='Convertidas'
BATCH_MIN_DIGITS=3

def batch_target_ok(target):
    """Conversões que geram um arquivo por imagem (as únicas que podem ir juntas para uma pasta numerada)."""
    return target in RENAMEABLE_TARGETS

def create_batch_folder(parent,now=None):
    """Cria (sem nunca reaproveitar) a subpasta «Convertidas AAAA-MM-DD HH-MM-SS[ -2]» dentro de `parent` e devolve o caminho. Falha com mensagem em português."""
    import datetime
    base=output_folder(parent);stamp=(now or datetime.datetime.now()).strftime('%Y-%m-%d %H-%M-%S')
    for n in range(1,1000):
        folder=base/(f'{BATCH_PREFIX} {stamp}'+('' if n==1 else f' ({n})'))
        try: folder.mkdir()
        except FileExistsError: continue
        except OSError as error: raise ConversionError('Não foi possível criar a pasta de saída. Verifique as permissões e o espaço livre.') from error
        return folder
    raise ConversionError('Não foi possível escolher um nome livre para a pasta de saída.')

def batch_rename_options(options,count):
    """Opções de nome para a pasta numerada: sem padrão do usuário vale «{n}» (001, 002…); com padrão sem {n}, acrescenta «-{n}» para manter a ordem. Dígitos nunca ficam menores que o necessário."""
    options=dict(options);pattern=str(options.get('rename_pattern') or '').strip() or '{n}'
    if '{n}' not in pattern: pattern+='-{n}'
    start=options.get('rename_start',1) if type(options.get('rename_start',1)) is int else 1
    need=max(BATCH_MIN_DIGITS,len(str(min(9999999,start+count-1))))
    digits=options.get('rename_digits',1) if type(options.get('rename_digits',1)) is int else 1
    options.update({'rename_pattern':pattern,'rename_start':start,'rename_digits':max(digits,need)})
    return options

def redact_regions_from(job, size):
    """Valida as áreas de ocultação [x, y, largura, altura] contra a imagem já orientada."""
    raw=job.get('redact_regions')
    if not isinstance(raw,(list,tuple)) or not 1<=len(raw)<=REDACT_MAX_REGIONS:
        raise ConversionError(f'Marque de 1 a {REDACT_MAX_REGIONS} áreas para ocultar.')
    regions=[]
    for item in raw:
        try: x,y,w,h=[int(v) for v in item]
        except (TypeError,ValueError): raise ConversionError('Área de ocultação inválida.')
        if x<0 or y<0 or w<1 or h<1 or x+w>size[0] or y+h>size[1]:
            raise ConversionError('Cada área a ocultar precisa caber dentro da imagem já orientada; as coordenadas começam no canto superior esquerdo.')
        regions.append((x,y,w,h))
    return regions

def redact_image(im, regions, mode='black', block=16):
    """Grava a ocultação nos pixels (RGBA opaco dentro das áreas). Pixelar usa a média de cada bloco; não é reversível por desfoque."""
    from PIL import Image
    if mode not in REDACT_MODES: raise ConversionError('Modo de ocultação inválido.')
    block=int(block)
    if not 4<=block<=200: raise ConversionError('O tamanho do bloco da pixelização deve ficar entre 4 e 200 px.')
    return redact_apply(im,regions,mode,block)

def redact_apply(im,regions,mode,block):
    """Aplica as áreas sem revalidar o bloco; o motor valida antes (`redact_image`) e a prévia da tela reduz o bloco junto com a imagem."""
    from PIL import Image
    out=im.convert('RGBA')
    for x,y,w,h in regions:
        box=(x,y,x+w,y+h)
        if mode=='black':
            patch=Image.new('RGBA',(w,h),(0,0,0,255))
        else:
            piece=out.crop(box);flat=Image.new('RGB',(w,h),'white');flat.paste(piece,mask=piece.getchannel('A'));piece.close()
            small=flat.resize((max(1,-(-w//block)),max(1,-(-h//block))),Image.Resampling.BOX);flat.close()
            patch=small.resize((w,h),Image.Resampling.NEAREST).convert('RGBA');small.close()
        out.paste(patch,box);patch.close()
    return out

def source_file(raw, max_bytes=MAX_BYTES):
    p=Path(raw).expanduser()
    # Reject devices, symlinks, Windows reparse points and remote UNC paths.
    if not p.is_absolute(): raise ConversionError('Escolha um caminho de arquivo local absoluto.')
    if os.name=='nt' and (str(p).startswith('\\\\') or str(p).startswith('//')): raise ConversionError('Caminhos de rede não são suportados.')
    s=p.lstat()
    if not stat.S_ISREG(s.st_mode) or p.is_symlink() or getattr(s,'st_file_attributes',0)&0x400:
        raise ConversionError('Escolha um arquivo comum, não uma pasta, atalho ou dispositivo.')
    if s.st_size==0 or s.st_size>max_bytes: raise ConversionError(f'Os arquivos não podem estar vazios nem passar de {max_bytes//(1024*1024)} MiB.')
    return checked_resolve(p, s)

def checked_resolve(path, before):
    """Detect replacement during canonicalization; not a filesystem sandbox."""
    resolved=path.resolve(strict=True)
    after=path.lstat();actual=resolved.stat()
    if (before.st_dev,before.st_ino)!=(after.st_dev,after.st_ino) or (before.st_dev,before.st_ino)!=(actual.st_dev,actual.st_ino) or stat.S_ISLNK(after.st_mode) or getattr(after,'st_file_attributes',0)&0x400:
        raise ConversionError('O caminho mudou durante a verificação; selecione-o novamente.')
    return resolved

def output_folder(raw):
    raw=str(raw)
    if os.name=='nt' and (raw.startswith('\\\\') or raw.startswith('//')): raise ConversionError('Pastas de saída em rede não são suportadas.')
    folder=Path(raw)
    if not folder.is_absolute():raise ConversionError('Escolha uma pasta de saída local com caminho absoluto.')
    info=folder.lstat()
    if not stat.S_ISDIR(info.st_mode) or getattr(info,'st_file_attributes',0)&0x400:
        raise ConversionError('Escolha uma pasta de saída local real; links simbólicos e atalhos não são suportados.')
    return checked_resolve(folder,info)

def publish(stage, folder, stem, suffix):
    """Never overwrite. Prefer atomic hardlink; exclusive copy supports removable disks."""
    if not stage.is_file() or not 0<stage.stat().st_size<=MAX_OUTPUT: raise ConversionError('Saída vazia ou grande demais.')
    stem=re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', stem).rstrip('. ')[:100] or 'converted'
    if stem.upper() in {'CON','PRN','AUX','NUL',*[f'COM{i}' for i in range(1,10)],*[f'LPT{i}' for i in range(1,10)]}: stem='file-'+stem
    for n in range(1,10001):
        target=folder/(stem+('-'+str(n) if n>1 else '')+'.'+suffix)
        try:
            os.link(stage,target)
            return str(target)
        except FileExistsError: continue
        except OSError as e:
            if e.errno not in (errno.EPERM,errno.EOPNOTSUPP,errno.EXDEV,errno.ENOSYS):
                raise ConversionError('Não foi possível gravar na pasta de saída. Verifique as permissões e o espaço livre.') from e
            try:
                fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_BINARY',0),0o600)
            except FileExistsError:continue
            identity=os.fstat(fd)
            try:
                with os.fdopen(fd,'wb') as out, stage.open('rb') as source:
                    shutil.copyfileobj(source,out,1024*1024)
                    out.flush();os.fsync(out.fileno())
                return str(target)
            except BaseException:
                # Remove only the incomplete file this call created, never a replacement.
                try:
                    current=target.lstat()
                    if (current.st_dev,current.st_ino)==(identity.st_dev,identity.st_ino):target.unlink()
                except OSError:pass
                raise
    raise ConversionError('Já existem nomes de saída demais; escolha outra pasta.')

def set_vector_width(width):
    """Largura em px usada ao desenhar SVG/SVGZ (0 ou None = tamanho do arquivo). O painel e o worker usam o mesmo valor, então a prévia coincide com o resultado."""
    global VECTOR_WIDTH
    VECTOR_WIDTH=int(width) if width else None

def vector_width_from(job):
    try: width=int(job.get('vector_width',0) or 0)
    except (TypeError,ValueError): raise ConversionError('A largura do vetor deve ser um número inteiro.')
    if not 0<=width<=VECTOR_MAX_WIDTH: raise ConversionError(f'A largura do vetor fica entre 1 e {VECTOR_MAX_WIDTH} px (0 = tamanho do arquivo).')
    return width

def open_vector(p):
    if Path(p).suffix.lower() in METAFILE_INPUTS:
        import metafile
        try: return metafile.rasterize_metafile(p,VECTOR_WIDTH)
        except metafile.MetafileError as error: raise ConversionError(str(error))
    if Path(p).suffix.lower() in AI_INPUTS:
        import illustrator
        try: return illustrator.rasterize_ai(p,VECTOR_WIDTH)
        except illustrator.AiError as error: raise ConversionError(str(error))
    import vector
    try: image=vector.rasterize_svg(p,VECTOR_WIDTH)
    except vector.VectorError as error: raise ConversionError(str(error))
    return image

_HEIF_STATE = {}

def heif_register():
    """Registra o HEIC/HEIF no Pillow (uma vez). Devolve True se o pacote `pillow-heif` está instalado e carregou."""
    if 'ok' not in _HEIF_STATE:
        try:
            import pillow_heif
            pillow_heif.register_heif_opener()
            _HEIF_STATE['ok']=True
        except Exception: _HEIF_STATE['ok']=False
    return _HEIF_STATE['ok']

def heic_save_available():
    """True se dá para GRAVAR HEIC (pacote instalado com codificador HEVC)."""
    if not heif_register(): return False
    try:
        from PIL import Image
        return 'HEIF' in Image.SAVE
    except Exception: return False

def heif_needed(path):
    """Antes de abrir um .heic/.heif/.hif: registra o formato ou explica o que falta."""
    if Path(str(path)).suffix.lower() in HEIF_INPUTS and not heif_register():
        raise ConversionError('Para abrir HEIC/HEIF instale o pacote pillow-heif (pip install -r requirements.txt).')

def open_image(p):
    if Path(p).suffix.lower() in VECTOR_INPUTS: return open_vector(p)
    heif_needed(p)
    from PIL import Image, ImageOps
    Image.MAX_IMAGE_PIXELS=MAX_PIXELS
    warnings.simplefilter('error', Image.DecompressionBombWarning)
    try: opened=Image.open(p)
    except (Image.DecompressionBombWarning,Image.DecompressionBombError): raise ConversionError('A imagem excede 40 megapixels.')
    except (Image.UnidentifiedImageError,SyntaxError,ValueError,OSError,EOFError,struct.error) as error:
        raise ConversionError(f'«{Path(p).name}» não é uma imagem que o Arquivo Local consiga abrir (arquivo corrompido, de outro tipo ou com a extensão trocada).') from error
    try:
        with opened as im:
            if im.width*im.height>MAX_PIXELS: raise ConversionError('A imagem excede 40 megapixels.')
            if getattr(im,'n_frames',1)!=1: raise ConversionError('Imagens animadas ou com várias páginas não são suportadas; use uma imagem de quadro único.')
            im.load()
            result=ImageOps.exif_transpose(im).copy()
    except ConversionError: raise
    except (Image.DecompressionBombWarning,Image.DecompressionBombError): raise ConversionError('A imagem excede 40 megapixels.')
    except (SyntaxError,ValueError,OSError,EOFError,struct.error,OverflowError) as error:
        raise ConversionError(f'«{Path(p).name}» está truncada ou danificada e não pôde ser lida por inteiro; nada foi salvo.') from error
    return normalize_mode(result)

def normalize_mode(im):
    """Leva modos que o restante do motor não trata bem para 8 bits: cinza de 16 bits (I;16, I) é reduzido sem estourar para branco e CMYK vai para sRGB (pelo perfil, se válido)."""
    from PIL import Image
    if im.mode.startswith('I'):
        scaled=im.point(lambda value:value*(1/256));converted=scaled.convert('L');scaled.close();im.close();return converted
    if im.mode=='CMYK':
        icc=im.info.get('icc_profile');converted=None
        if icc:
            try:
                import io
                from PIL import ImageCms
                source=ImageCms.ImageCmsProfile(io.BytesIO(icc))
                if source.profile.xcolor_space.strip()=='CMYK':
                    converted=ImageCms.profileToProfile(im,source,ImageCms.createProfile('sRGB'),outputMode='RGB')
            except Exception: converted=None
        if converted is None: converted=im.convert('RGB')
        converted.info.pop('icc_profile',None);im.close();return converted
    return im

def icc_for_output(icc, mode):
    """Devolve o perfil ICC somente se ele for válido e compatível com o modo de saída (RGB para cores, GRAY para cinza)."""
    if not icc or mode not in ('RGB','RGBA','L','LA'): return None
    try:
        import io
        from PIL import ImageCms
        space=ImageCms.ImageCmsProfile(io.BytesIO(icc)).profile.xcolor_space.strip()
    except Exception: return None
    return icc if space==('GRAY' if mode in ('L','LA') else 'RGB') else None

def to_srgb(im, icc):
    """Converte os pixels do perfil embutido para sRGB (usado em BMP e PDF, que não guardam perfil). Perfil inválido: mantém os pixels."""
    if not icc: return im
    try:
        import io
        from PIL import Image, ImageCms
        source=ImageCms.ImageCmsProfile(io.BytesIO(icc))
        if source.profile.xcolor_space.strip()!='RGB': return im
        srgb=ImageCms.createProfile('sRGB')
        rgba=im.convert('RGBA')
        converted=ImageCms.profileToProfile(rgba.convert('RGB'),source,srgb,outputMode='RGB')
        converted.putalpha(rgba.getchannel('A'));rgba.close()
        return converted
    except Exception: return im

def collage_columns_for(count, columns=0):
    """0 = automático (raiz quadrada arredondada para cima); nunca mais colunas do que imagens."""
    import math
    return max(1,min(count,columns if columns else math.ceil(math.sqrt(count))))

def collage_layout(count, columns, cell, gap):
    """Geometria da colagem: devolve ((largura, altura), [(x, y)...]) com a posição da célula de cada imagem, em ordem de leitura; a última linha incompleta fica centralizada. Compartilhada pelo motor e pela prévia."""
    columns=collage_columns_for(count,columns)
    rows=-(-count//columns)
    size=(columns*cell+(columns+1)*gap,rows*cell+(rows+1)*gap)
    origins=[]
    for index in range(count):
        row,column=divmod(index,columns)
        in_row=min(columns,count-row*columns)
        offset=((columns-in_row)*(cell+gap))//2
        origins.append((gap+column*(cell+gap)+offset,gap+row*(cell+gap)))
    return size,origins

def build_collage(paths, columns, cell, gap, background):
    """Monta a colagem: cada imagem (já orientada, em sRGB) cabe inteira na sua célula quadrada, centralizada, sem ampliar além da célula; transparência vai sobre a cor de fundo."""
    from PIL import Image, ImageColor
    if not COLLAGE_MIN<=len(paths)<=COLLAGE_MAX: raise ConversionError(f'A colagem aceita de {COLLAGE_MIN} a {COLLAGE_MAX} imagens.')
    if not 0<=columns<=6 or not 64<=cell<=2000 or not 0<=gap<=200: raise ConversionError('Opções de colagem inválidas: colunas 0–6, célula 64–2000 px, espaço 0–200 px.')
    if not re.fullmatch(r'#[0-9A-Fa-f]{6}',background): raise ConversionError('A cor de fundo deve estar no formato hexadecimal #RRGGBB.')
    (width,height),origins=collage_layout(len(paths),columns,cell,gap)
    if width>10000 or height>10000 or width*height>MAX_PIXELS: raise ConversionError('A colagem ficaria grande demais (máximo 10000 px por lado e 40 megapixels); reduza o tamanho da célula.')
    canvas=Image.new('RGB',(width,height),ImageColor.getrgb(background))
    try:
        for path,(x,y) in zip(paths,origins):
            im=open_image(path)
            try:
                icc=im.info.get('icc_profile')
                if icc:
                    converted=to_srgb(im,icc)
                    if converted is not im: im.close();im=converted
                rgba=im.convert('RGBA');im.close();im=rgba
                if im.width>cell or im.height>cell: im.thumbnail((cell,cell),Image.Resampling.LANCZOS)
                canvas.paste(im,(x+(cell-im.width)//2,y+(cell-im.height)//2),im.getchannel('A'))
            finally: im.close()
        return canvas
    except BaseException:
        canvas.close();raise

ONEPDF='Images → One PDF'
OCR_TEXT='OCR → Text'
OCR_PDF='OCR → PDF'
OCR_TARGETS=(OCR_TEXT,OCR_PDF)
OCR_DEFAULT_LANG='por+eng'
OCR_DEFAULT_PSM='auto'

BG_TARGET='Remove Background → PNG'
BG_DEFAULT_MODEL=bgremove.DEFAULT_MODEL

def bg_options_from(job,strict=True):
    """Modelo e suavização da remoção de fundo: só modelos da lista (bgremove.MODELS) e suavização de 0 a bgremove.MAX_FEATHER px."""
    model=job.get('bg_model',BG_DEFAULT_MODEL);feather=job.get('bg_feather',bgremove.DEFAULT_FEATHER)
    if not isinstance(model,str) or model not in bgremove.MODELS:
        if strict: raise ConversionError('Modelo de remoção de fundo inválido.')
        model=BG_DEFAULT_MODEL
    if isinstance(feather,bool) or not isinstance(feather,int) or not 0<=feather<=bgremove.MAX_FEATHER:
        if strict: raise ConversionError(f'A suavização da borda deve ficar entre 0 e {bgremove.MAX_FEATHER} px.')
        feather=bgremove.DEFAULT_FEATHER
    return {'model':model,'feather':feather}

def run_bg_remove(im,job):
    """Remove o fundo de `im` (já aberta) e devolve a imagem RGBA nova; não fecha `im`. Recusa resultado totalmente vazio."""
    opt=bg_options_from(job)
    ready,message=bgremove.status(opt['model'])
    if not ready: raise ConversionError(message)
    try: result=bgremove.remove_background(im,opt['model'],opt['feather'])
    except bgremove.BgError as error: raise ConversionError(str(error)) from error
    if bgremove.coverage(result)<0.001:
        result.close();raise ConversionError('O modelo não encontrou nenhum objeto principal nesta imagem; nada foi salvo. Tente o modelo «Preciso» ou outra imagem.')
    return result

def ocr_options_from(job,strict=True):
    """Idioma e modo de página do OCR: só valores da lista (ocr.LANGS, ocr.PSM). Fora do modo estrito, valores inválidos voltam ao padrão."""
    lang=job.get('ocr_lang',OCR_DEFAULT_LANG);psm=job.get('ocr_psm',OCR_DEFAULT_PSM)
    if not isinstance(lang,str) or lang not in ocr.LANGS:
        if strict: raise ConversionError('Idioma de OCR inválido.')
        lang=OCR_DEFAULT_LANG
    if not isinstance(psm,str) or psm not in ocr.PSM:
        if strict: raise ConversionError('Modo de página de OCR inválido.')
        psm=OCR_DEFAULT_PSM
    return lang,psm

def ocr_prepare(im,output):
    """Imagem pronta para o Tesseract: sem transparência (fundo branco), em RGB ou cinza, com no máximo ocr.MAX_SIDE px e, no texto, ampliada 2× se for pequena."""
    from PIL import Image
    if im.mode in ('RGBA','LA','PA') or 'transparency' in im.info:
        rgba=im.convert('RGBA');base=Image.new('RGB',rgba.size,'white');base.paste(rgba,mask=rgba.getchannel('A'));rgba.close();im.close();im=base
    elif im.mode not in ('RGB','L'):
        converted=im.convert('RGB');im.close();im=converted
    if max(im.size)>ocr.MAX_SIDE:
        im.thumbnail((ocr.MAX_SIDE,ocr.MAX_SIDE),Image.Resampling.LANCZOS)
    elif output=='txt' and max(im.size)<ocr.MIN_SIDE:
        bigger=im.resize((im.width*2,im.height*2),Image.Resampling.LANCZOS);im.close();im=bigger
    return im

def run_ocr(im,job,output,work,stage):
    """Roda o OCR sobre `im` (já aberta) e deixa o resultado em `stage`; devolve a extensão. Fecha `im`."""
    lang,psm=ocr_options_from(job)
    try: ocr.check_ready(lang)
    except ocr.OcrError as error:
        im.close();raise ConversionError(str(error)) from error
    prepared=ocr_prepare(im,output)
    try:
        source=Path(work)/'ocr-input.png'
        prepared.save(source,format='PNG',dpi=(ocr.DPI,ocr.DPI))
    finally: prepared.close()
    try: produced=ocr.recognize(source,lang,psm,output,work)
    except ocr.OcrError as error: raise ConversionError(str(error)) from error
    empty='Nenhum texto foi reconhecido nesta imagem. Tente outro idioma, outro modo de página ou uma imagem maior e mais nítida; nada foi salvo.'
    if output=='txt':
        try: text=ocr.read_text(produced)
        except ocr.OcrError as error: raise ConversionError(str(error)) from error
        if not text.strip(): raise ConversionError(empty)
        stage.write_text(text,encoding='utf8',newline='\n')
        return 'txt'
    from pypdf import PdfReader
    try: found=''.join((page.extract_text() or '') for page in PdfReader(str(produced),strict=False).pages).strip()
    except Exception as error: raise ConversionError('O PDF gerado pelo OCR não pôde ser verificado.') from error
    if not found: raise ConversionError(empty)
    shutil.move(str(produced),str(stage))
    return 'pdf'
PDF_PAGES={'image':('Do tamanho da imagem',None),'a4':('A4',(210,297)),'letter':('Carta',(215.9,279.4))}      # id → (rótulo, (largura, altura) em mm)
PDF_DPI=150
PDF_MAX_PAGES=200
PDF_MAX_MARGIN_MM=50
PDF_CLEAN='Clean PDF'
PDF_COMPRESS='Compress PDF'
PDF_STAMP='Stamp PDF'
PDF_PROTECT='Protect PDF'
PDF_REDACT='Redact PDF'
PDF_FORM='Fill PDF'
REDACT_DEFAULT_DPI=200
PDF_UNPROTECT='Unprotect PDF'
PASSWORD_MIN=4
STAMP_KINDS=('text','watermark')
PDF_LONG_TARGETS=('PDF OCR → PDF','PDF OCR → Text','Compress PDF','Redact PDF','Convert Audio')      # jobs que podem passar do tempo padrão do runner
PDF_OCR_PDF='PDF OCR → PDF'
PDF_OCR_TEXT='PDF OCR → Text'
PDF_OCR_TARGETS=(PDF_OCR_PDF,PDF_OCR_TEXT)
PDF_OCR_TIMEOUT=900      # segundos: até 20 páginas, alguns segundos cada (o padrão do runner é 180)
PDF_OCR_MAX_PAGES=20          # OCR leva alguns segundos por página; o job tem tempo máximo

def onepdf_options_from(job):
    """Lê o tamanho de página (`pdf_page`: image/a4/letter), a margem em mm (`pdf_margin`, só A4/Carta) e a qualidade JPEG das páginas (`quality`, 1–100)."""
    page=str(job.get('pdf_page','image') or 'image')
    try: margin=int(job.get('pdf_margin',10));quality=int(job.get('quality',90))
    except (TypeError,ValueError): raise ConversionError('Opções do PDF inválidas.')
    if page not in PDF_PAGES: raise ConversionError('O tamanho de página deve ser: do tamanho da imagem, A4 ou Carta.')
    if not 0<=margin<=PDF_MAX_MARGIN_MM or not 1<=quality<=100: raise ConversionError(f'Margem de 0 a {PDF_MAX_MARGIN_MM} mm e qualidade de 1 a 100.')
    if page!='image' and margin*2>=min(PDF_PAGES[page][1]): raise ConversionError('A margem não deixa área para a imagem.')
    ocr_lang=job.get('pdf_ocr','off') or 'off'
    if not isinstance(ocr_lang,str) or (ocr_lang!='off' and ocr_lang not in ocr.LANGS): raise ConversionError('Idioma do texto pesquisável inválido.')
    if ocr_lang!='off' and page!='image': raise ConversionError('O texto pesquisável (OCR) só vale com as páginas «Do tamanho da imagem»; escolha esse tamanho ou desligue o OCR.')
    return {'page':page,'margin':margin if page!='image' else 0,'quality':quality,'ocr':ocr_lang}

def pdf_page_pixels(page,size,margin_mm):
    """Página em pixels a PDF_DPI e área útil (x, y, largura, altura). A orientação acompanha a imagem (paisagem se for mais larga que alta);
    no modo «image» a página é a própria imagem."""
    if page=='image': return (size[0],size[1]),(0,0,size[0],size[1])
    w_mm,h_mm=PDF_PAGES[page][1]
    if size[0]>size[1]: w_mm,h_mm=h_mm,w_mm
    px=lambda mm:max(1,round(mm/25.4*PDF_DPI));page_w,page_h=px(w_mm),px(h_mm);m=round(margin_mm/25.4*PDF_DPI)
    return (page_w,page_h),(m,m,max(1,page_w-2*m),max(1,page_h-2*m))

def pdf_page_image(im,opts):
    """Monta a página (RGB, transparência sobre branco). Na página fixa a imagem é ajustada à área útil mantendo a proporção, centralizada; pode ampliar."""
    from PIL import Image
    rgba=im.convert('RGBA')
    try:
        (pw,ph),(ax,ay,aw,ah)=pdf_page_pixels(opts['page'],rgba.size,opts['margin'])
        page=Image.new('RGB',(pw,ph),(255,255,255))
        if opts['page']=='image': placed=rgba;pos=(0,0)
        else:
            scale=min(aw/rgba.width,ah/rgba.height);new=(max(1,round(rgba.width*scale)),max(1,round(rgba.height*scale)))
            placed=rgba.resize(new,Image.Resampling.LANCZOS);pos=(ax+(aw-new[0])//2,ay+(ah-new[1])//2)
        page.paste(placed,pos,placed.getchannel('A'))
        if placed is not rgba: placed.close()
        return page
    finally: rgba.close()

def ocr_page_pdf(im,lang,work,stage):
    """OCR de uma página para um PDF de uma página em `stage` (imagem + texto invisível). Devolve True se algum texto foi reconhecido; página em branco vira só a imagem. Fecha `im`."""
    prepared=ocr_prepare(im,'pdf')
    try:
        source=Path(work)/'ocr-page.png'
        prepared.save(source,format='PNG',dpi=(ocr.DPI,ocr.DPI))
    finally: prepared.close()
    try: produced=ocr.recognize(source,lang,OCR_DEFAULT_PSM,'pdf',work)
    except ocr.OcrError as error: raise ConversionError(str(error)) from error
    from pypdf import PdfReader
    try: found=''.join((page.extract_text() or '') for page in PdfReader(str(produced),strict=False).pages).strip()
    except Exception as error: raise ConversionError('O PDF gerado pelo OCR não pôde ser verificado.') from error
    shutil.move(str(produced),str(stage))
    return bool(found)

def build_onepdf_ocr(paths,opts,work,out):
    """PDF pesquisável de várias imagens: cada uma passa pelo OCR (300 dpi assumidos) e as páginas são unidas na ordem da lista. Devolve quantas páginas ficaram sem texto."""
    from pypdf import PdfReader, PdfWriter
    if not 2<=len(paths)<=PDF_OCR_MAX_PAGES: raise ConversionError(f'Com OCR, escolha de 2 a {PDF_OCR_MAX_PAGES} imagens (cada página leva alguns segundos).')
    lang=opts['ocr']
    try: ocr.check_ready(lang)
    except ocr.OcrError as error: raise ConversionError(str(error)) from error
    writer=PdfWriter();keep=[];blank=0;total=0
    for index,path in enumerate(paths):
        im=open_image(path)
        icc=im.info.get('icc_profile')
        if icc:
            converted=to_srgb(im,icc)
            if converted is not im: im.close();im=converted
        part=Path(work)/f'page-{index}.pdf'
        if not ocr_page_pdf(im,lang,work,part): blank+=1
        total+=part.stat().st_size
        if total>MAX_OUTPUT: raise ConversionError('O PDF ficaria maior que 512 MiB; use menos imagens.')
        reader=PdfReader(str(part),strict=False);keep.append(reader);writer.add_page(reader.pages[0])
    with out.open('wb') as f: writer.write(f)
    for reader in keep: reader.stream.close() if hasattr(reader.stream,'close') else None
    return blank

def build_onepdf(paths,opts,out):
    """Grava um PDF com uma página por imagem, na ordem recebida. Uma imagem por vez na memória: cada página vira um PDF de uma página e depois são unidos."""
    import io
    from pypdf import PdfReader, PdfWriter
    if not 2<=len(paths)<=PDF_MAX_PAGES: raise ConversionError(f'Escolha de 2 a {PDF_MAX_PAGES} imagens para o PDF.')
    writer=PdfWriter();keep=[];total=0
    for path in paths:
        im=open_image(path)
        try:
            icc=im.info.get('icc_profile')
            if icc:
                converted=to_srgb(im,icc)
                if converted is not im: im.close();im=converted
            page=pdf_page_image(im,opts)
        finally: im.close()
        try:
            buffer=io.BytesIO();page.save(buffer,format='PDF',resolution=float(PDF_DPI),quality=opts['quality'])
        finally: page.close()
        total+=buffer.tell()
        if total>MAX_OUTPUT: raise ConversionError('O PDF ficaria maior que 512 MiB; reduza a qualidade ou o número de imagens.')
        buffer.seek(0);reader=PdfReader(buffer);keep.append(reader)
        writer.add_page(reader.pages[0])
    with out.open('wb') as f: writer.write(f)

def backdrop_layout(width, height, padding, ratio='auto'):
    """Geometria da ferramenta Fundo: ((largura, altura) do resultado, (x, y) da imagem). A proporção só aumenta o fundo."""
    import math
    total_w,total_h=width+2*padding,height+2*padding
    spec=BACKDROP_RATIOS.get(ratio)
    if spec:
        wanted=spec[0]/spec[1]
        if total_w/total_h<wanted: total_w=math.ceil(total_h*wanted)
        elif total_w/total_h>wanted: total_h=math.ceil(total_w/wanted)
    return (total_w,total_h),((total_w-width)//2,(total_h-height)//2)

def backdrop_colors(style, custom='#FFFFFF'):
    if style=='custom': return 'solid',(custom,)
    _label,kind,colors=BACKDROPS[style]
    return kind,colors

def build_backdrop(im, style, custom, padding, radius, shadow, ratio):
    """Compõe a imagem (RGBA) sobre um fundo liso ou em degradê diagonal, com cantos arredondados e sombra. Devolve RGB."""
    from PIL import Image, ImageChops, ImageColor, ImageDraw, ImageFilter, ImageOps
    if style!='custom' and style not in BACKDROPS: raise ConversionError('Fundo desconhecido.')
    if style=='custom' and not re.fullmatch(r'#[0-9A-Fa-f]{6}',custom): raise ConversionError('A cor do fundo deve estar no formato hexadecimal #RRGGBB.')
    if ratio not in BACKDROP_RATIOS: raise ConversionError('Proporção do fundo inválida.')
    if not 0<=padding<=600 or not 0<=radius<=300 or not 0<=shadow<=100: raise ConversionError('Opções de fundo inválidas: margem 0–600 px, cantos 0–300 px, sombra 0–100.')
    (total_w,total_h),(x,y)=backdrop_layout(im.width,im.height,padding,ratio)
    if total_w>10000 or total_h>10000 or total_w*total_h>MAX_PIXELS: raise ConversionError('O resultado ficaria grande demais (máximo 10000 px por lado e 40 megapixels); reduza a margem.')
    kind,colors=backdrop_colors(style,custom)
    if kind=='solid' or len(colors)<2: canvas=Image.new('RGB',(total_w,total_h),ImageColor.getrgb(colors[0]))
    else:
        ramp=Image.linear_gradient('L')
        horizontal=ramp.rotate(90,expand=True).resize((total_w,total_h),Image.Resampling.BILINEAR)
        vertical=ramp.resize((total_w,total_h),Image.Resampling.BILINEAR)
        weight=total_w*total_w/(total_w*total_w+total_h*total_h)   # mesma projeção diagonal do QLinearGradient(0,0,w,h) usado na prévia
        weighted_h=horizontal.point(lambda value:round(value*weight));weighted_v=vertical.point(lambda value:round(value*(1-weight)))
        t=ImageChops.add(weighted_h,weighted_v)
        ramp.close();horizontal.close();vertical.close();weighted_h.close();weighted_v.close()
        canvas=ImageOps.colorize(t,black=colors[0],white=colors[-1],mid=colors[1] if len(colors)==3 else None);t.close()
    radius=min(radius,min(im.width,im.height)//2)
    mask=Image.new('L',im.size,255)
    if radius:
        scale=4
        big=Image.new('L',(im.width*scale,im.height*scale),0)
        ImageDraw.Draw(big).rounded_rectangle((0,0,im.width*scale-1,im.height*scale-1),radius*scale,fill=255)
        mask=big.resize(im.size,Image.Resampling.LANCZOS);big.close()
    if shadow:
        layer=Image.new('L',canvas.size,0)
        layer.paste(mask,(x,y+round(shadow*0.25)))
        blurred=layer.filter(ImageFilter.GaussianBlur(shadow*0.8+1));layer.close()
        blurred=blurred.point(lambda value:round(value*0.38))
        canvas.paste(Image.new('RGB',canvas.size,(0,0,0)),(0,0),blurred);blurred.close()
    alpha=ImageChops.multiply(im.getchannel('A'),mask);mask.close()
    canvas.paste(im.convert('RGB'),(x,y),alpha);alpha.close()
    return canvas

def jpeg_bytes(im, quality, icc=None):
    """Codifica como o 'Compress → JPEG' do motor (transparência sobre branco, optimize=True); usado na estimativa da interface."""
    import io
    from PIL import Image
    rgba=im.convert('RGBA');base=Image.new('RGB',rgba.size,'white');base.paste(rgba,mask=rgba.getchannel('A'));rgba.close()
    buffer=io.BytesIO()
    options={'quality':quality,'optimize':True}
    profile=icc_for_output(icc,'RGB')
    if profile: options['icc_profile']=profile
    try: base.save(buffer,format='JPEG',**options)
    finally: base.close()
    return buffer.getvalue()

_GPS_REFS={'N','S','E','W'}
def _clean_text(value,limit=80):
    if isinstance(value,bytes): value=value.decode('utf-8','replace')
    text=''.join(ch if ch.isprintable() else ' ' for ch in str(value)).strip()
    return text if len(text)<=limit else text[:limit-1]+'…'

def _gps_text(gps):
    try:
        def deg(values,ref):
            d,m,sec=[float(v) for v in values];result=d+m/60+sec/3600
            return -result if ref in ('S','W') else result
        lat=deg(gps[2],gps[1]);lon=deg(gps[4],gps[3])
        if abs(lat)<=90 and abs(lon)<=180: return f'{lat:.5f}, {lon:.5f}'
    except Exception: pass
    return 'presente (coordenadas ilegíveis)'

def load_font(size,bold=False):
    """Fonte local (Arial no Windows; DejaVu/Liberation no Linux); sem nenhuma delas, a fonte embutida do Pillow."""
    from PIL import ImageFont
    names=('arialbd.ttf','arial.ttf') if bold else ('arial.ttf',)
    candidates=[]
    if os.name=='nt': candidates.extend(Path(os.environ.get('WINDIR',r'C:\Windows'))/'Fonts'/name for name in names)
    candidates.extend((Path('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf' if bold else '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'),
                       Path('/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf' if bold else '/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf')))
    for path in candidates:
        if path.is_file():
            try: return ImageFont.truetype(str(path),size)
            except OSError: pass
    return ImageFont.load_default(size)

def watermark_options_from(job,strict=True):
    """Valida a marca d'água: tipo, texto ou arquivo de imagem, cor, tamanho (% da largura), opacidade (%), posição e margem (% do menor lado)."""
    kind=str(job.get('watermark_kind','text'))
    position=str(job.get('watermark_position','br'))
    color=str(job.get('watermark_color','#FFFFFF'))
    try: scale,opacity,margin=[int(job.get(key,default)) for key,default in (('watermark_scale',25),('watermark_opacity',60),('watermark_margin',3))]
    except (TypeError,ValueError): raise ConversionError('Tamanho, opacidade e margem da marca d\'água devem ser números.')
    if kind not in WATERMARK_KINDS: raise ConversionError('Tipo de marca d\'água desconhecido; use texto ou imagem.')
    if position not in WATERMARK_POSITIONS: raise ConversionError('Posição da marca d\'água inválida.')
    if not 1<=scale<=100 or not 1<=opacity<=100 or not 0<=margin<=25: raise ConversionError('Tamanho e opacidade ficam de 1 a 100 %, e a margem de 0 a 25 %.')
    if position=='tile' and scale<5: raise ConversionError('Para repetir a marca, use tamanho de pelo menos 5 %.')
    if not re.fullmatch(r'#[0-9A-Fa-f]{6}',color): raise ConversionError('A cor da marca d\'água deve estar no formato #RRGGBB.')
    text=job.get('watermark_text','');image=job.get('watermark_image','')
    if kind=='text':
        if not isinstance(text,str) or (strict and not text.strip()) or len(text)>WATERMARK_MAX_TEXT or any(ord(char)<32 for char in text):
            raise ConversionError(f'O texto da marca d\'água deve ter de 1 a {WATERMARK_MAX_TEXT} caracteres imprimíveis.')
    elif strict and (not isinstance(image,str) or not image.strip()): raise ConversionError('Escolha a imagem da marca d\'água.')
    return {'kind':kind,'text':text.strip() if isinstance(text,str) else '','image':image if isinstance(image,str) else '','color':color,'scale':scale,'opacity':opacity,'margin':margin,'position':position}

def watermark_mark(options,width,logo=None):
    """Monta a marca (RGBA) pronta: texto desenhado com a cor escolhida ou logotipo, ocupando `scale` % da largura `width`, já com a opacidade aplicada."""
    from PIL import Image, ImageColor, ImageDraw
    target=max(4,round(width*options['scale']/100))
    if options['kind']=='text':
        text=options['text']
        if not text: raise ConversionError('Digite o texto da marca d\'água.')
        low,high=6,max(8,target*2)
        probe=ImageDraw.Draw(Image.new('L',(1,1)))
        def measure(size):
            box=probe.textbbox((0,0),text,font=load_font(size,bold=True)); return box[2]-box[0]
        while low<high:                                    # maior corpo cujo texto cabe em `target` px
            mid=(low+high+1)//2
            if measure(mid)<=target: low=mid
            else: high=mid-1
        font=load_font(low,bold=True);box=probe.textbbox((0,0),text,font=font)
        mark=Image.new('RGBA',(max(1,box[2]-box[0]),max(1,box[3]-box[1])),(0,0,0,0))
        ImageDraw.Draw(mark).text((-box[0],-box[1]),text,fill=ImageColor.getrgb(options['color'])+(255,),font=font)
    else:
        if logo is None: raise ConversionError('Escolha a imagem da marca d\'água.')
        ratio=target/logo.width
        mark=logo.convert('RGBA').resize((target,max(1,round(logo.height*ratio))),Image.Resampling.LANCZOS)
    if options['opacity']<100:
        alpha=mark.getchannel('A').point(lambda v:round(v*options['opacity']/100));mark.putalpha(alpha)
    return mark

def _place_rgba(canvas,mark,x,y):
    """alpha_composite com recorte: a marca pode passar da borda (útil na repetição) sem erro."""
    x0,y0=max(0,x),max(0,y);x1,y1=min(canvas.width,x+mark.width),min(canvas.height,y+mark.height)
    if x1>x0 and y1>y0: canvas.alpha_composite(mark.crop((x0-x,y0-y,x1-x,y1-y)),(x0,y0))

def watermark_image(im,options,logo=None):
    """Aplica a marca d'água sobre uma cópia RGBA da imagem. Tamanho, margem e opacidade são relativos à imagem: a prévia reduzida e o resultado final coincidem."""
    from PIL import Image
    base=im.convert('RGBA');W,H=base.size
    mark=watermark_mark(options,W,logo)
    position=options['position']
    if position=='tile':
        turned=mark.rotate(30,expand=True,resample=Image.Resampling.BICUBIC);mark.close();mark=turned
        step_x,step_y=max(1,round(mark.width*1.6)),max(1,round(mark.height*1.6))
        for row,y in enumerate(range(-mark.height//2,H,step_y)):
            for x in range(-mark.width//2-(step_x//2 if row%2 else 0),W,step_x): _place_rgba(base,mark,x,y)
    else:
        if mark.width>W or mark.height>H:                      # nunca maior que a imagem
            fit=min(W/mark.width,H/mark.height);resized=mark.resize((max(1,int(mark.width*fit)),max(1,int(mark.height*fit))),Image.Resampling.LANCZOS);mark.close();mark=resized
        gap=round(min(W,H)*options['margin']/100)
        row_key,col_key=('m','c') if position=='c' else (position[0],position[1])
        x={'l':gap,'c':(W-mark.width)//2,'r':W-mark.width-gap}[col_key]
        y={'t':gap,'m':(H-mark.height)//2,'b':H-mark.height-gap}[row_key]
        _place_rgba(base,mark,max(0,x),max(0,y))
    mark.close();return base

def output_options_from(job,target,strict=True):
    """Formato de saída das ferramentas: (id do formato, qualidade 1–100, cor que substitui a transparência).
    Só vale para ferramentas que geram imagem (`tool_registry.FORMAT_TARGETS`); nas demais o resultado é sempre o padrão do alvo."""
    if target not in tool_registry.FORMAT_TARGETS: return 'png',90,'#FFFFFF'
    key=str(job.get('out_format','png') or 'png')
    try: quality=int(job.get('out_quality',90) if job.get('out_quality',90) is not None else 90)
    except (TypeError,ValueError): raise ConversionError('A qualidade de saída deve ser um número de 1 a 100.')
    flatten=str(job.get('out_flatten','#FFFFFF') or '#FFFFFF')
    if key not in OUTPUT_FORMATS: raise ConversionError('Formato de saída desconhecido; use PNG, JPEG, WebP, TIFF, BMP, GIF, ICO, AVIF ou HEIC.')
    if not 1<=quality<=100: raise ConversionError('A qualidade de saída deve ficar entre 1 e 100.')
    if key=='heic' and strict and not heic_save_available(): raise ConversionError('Este computador não tem o pacote pillow-heif com codificador HEIC; escolha outro formato.')
    if key=='avif' and strict and not avif_available(): raise ConversionError('Este computador não tem suporte a AVIF no Pillow instalado; escolha outro formato.')
    if not re.fullmatch(r'#[0-9A-Fa-f]{6}',flatten): raise ConversionError('A cor que substitui a transparência deve estar no formato #RRGGBB.')
    return key,quality,flatten

def avif_available():
    try:
        from PIL import features
        return bool(features.check('avif'))
    except Exception: return False

def finalize_for_format(im,key,flatten='#FFFFFF'):
    """Deixa a imagem no modo que o formato aceita: JPEG/BMP não têm transparência (entra a cor `flatten`); WebP/TIFF/PNG mantêm o alfa."""
    from PIL import Image, ImageColor
    if key in ('jpeg','bmp'):
        rgba=im.convert('RGBA');base=Image.new('RGB',rgba.size,ImageColor.getrgb(flatten));base.paste(rgba,mask=rgba.getchannel('A'));rgba.close();im.close();return base
    if key=='gif': return gif_prepare(im)
    if key=='ico': return ico_square(im)
    if key in ('webp','avif','heic') and im.mode not in ('RGB','RGBA'):
        converted=im.convert('RGBA' if im.mode in ('LA','PA') or 'transparency' in im.info else 'RGB');im.close();return converted
    if im.mode not in ('RGB','RGBA','L','LA'):
        converted=im.convert('RGBA');im.close();return converted
    return im

def ico_square(im):
    """Ícone: quadrado RGBA de 16 a 256 px. A imagem é centralizada em fundo transparente (nada é cortado ou esticado); acima de 256 px ela é reduzida, abaixo de 16 px é ampliada."""
    from PIL import Image
    rgba=im.convert('RGBA');im.close()
    w,h=rgba.size;side=max(w,h)
    if side>ICO_MAX or side<16:
        scale=(ICO_MAX if side>ICO_MAX else 16)/side
        resized=rgba.resize((max(1,round(w*scale)),max(1,round(h*scale))),Image.Resampling.LANCZOS);rgba.close();rgba=resized;w,h=rgba.size
    side=max(w,h,16)
    canvas=Image.new('RGBA',(side,side),(0,0,0,0));canvas.paste(rgba,((side-w)//2,(side-h)//2));rgba.close();return canvas

def ico_sizes(side):
    return [(n,n) for n in ICO_SIZES if n<=side]

def gif_prepare(im):
    """GIF estático: paleta de até 256 cores (255 + 1 índice reservado quando há transparência) com pontilhado Floyd–Steinberg; transparência de 1 bit."""
    from PIL import Image
    rgba=im.convert('RGBA');im.close()
    alpha=rgba.getchannel('A');transparent=alpha.getextrema()[0]<GIF_ALPHA_CUT
    rgb=rgba.convert('RGB');rgba.close()
    p=rgb.quantize(colors=255 if transparent else 256,method=Image.Quantize.MEDIANCUT,dither=Image.Dither.FLOYDSTEINBERG);rgb.close()
    if transparent:
        palette=list(p.getpalette() or [])[:768];palette+=[0]*(768-len(palette));p.putpalette(palette)
        p.paste(255,mask=alpha.point(lambda v:255 if v<GIF_ALPHA_CUT else 0))
        p.info['transparency']=255
    alpha.close();return p

def format_save_options(key,quality,transparency=None,side=None):
    if key=='gif': return {'transparency':transparency} if transparency is not None else {}
    if key=='ico': return {'sizes':ico_sizes(side or ICO_MAX)}
    if key=='heic': return {'quality':-1 if quality>=100 else quality,'chroma':444 if quality>=95 else 420}
    if key=='avif': return {'quality':quality,'subsampling':'4:4:4' if quality>=95 else '4:2:0','speed':6}
    if key=='jpeg': return {'quality':quality}
    if key=='webp': return {'lossless':True,'quality':100,'method':4} if quality>=100 else {'quality':quality,'method':4}
    return {}

def resize_target_size(size,mode,percent=100,width=0,height=0):
    """Calcula o tamanho final: 'percent' (1–1000 %), 'fit' (cabe em largura×altura mantendo a proporção; 0 = sem limite nesse eixo) ou 'exact' (medida exata)."""
    w0,h0=size
    if mode=='percent':
        if not 1<=percent<=1000: raise ConversionError('A porcentagem fica entre 1 e 1000.')
        new=(max(1,round(w0*percent/100)),max(1,round(h0*percent/100)))
    elif mode=='fit':
        if width<0 or height<0 or not (width or height): raise ConversionError('Informe a largura, a altura ou as duas.')
        scale=min(width/w0 if width else float('inf'),height/h0 if height else float('inf'))
        new=(max(1,round(w0*scale)),max(1,round(h0*scale)))
    elif mode=='exact':
        if width<1 or height<1: raise ConversionError('Informe a largura e a altura exatas.')
        new=(width,height)
    else: raise ConversionError('Modo de redimensionamento desconhecido.')
    if max(new)>RESIZE_MAX_SIDE or new[0]*new[1]>MAX_PIXELS:
        raise ConversionError(f'O resultado ({new[0]} × {new[1]} px) passa do limite de {RESIZE_MAX_SIDE} px por lado ou de 40 megapixels.')
    return new

def resize_options_from(job,size=None):
    """Lê as opções do job; com `size`, devolve (tamanho_final,) para `resize_image`."""
    try: percent,width,height=[int(job.get(key,0) or 0) for key in ('resize_percent','resize_width','resize_height')]
    except (TypeError,ValueError): raise ConversionError('Opções de redimensionamento inválidas.')
    mode=str(job.get('resize_mode','percent'))
    if size is None: return mode,percent,width,height
    return (resize_target_size(size,mode,percent or 100,width,height),)

def resize_image(im,new_size):
    """Redimensiona com Lanczos; o alfa é tratado com pré-multiplicação (sem halos). Mesmo tamanho = cópia."""
    from PIL import Image
    if tuple(new_size)==im.size: return im.copy()
    work=im if im.mode in ('RGB','RGBA','L','LA') else im.convert('RGBA')
    out=work.resize(tuple(new_size),Image.Resampling.LANCZOS)
    if work is not im: work.close()
    return out

def rotate_options_from(job,strict=True):
    """Lê o giro (0, 90, 180 ou 270 graus no sentido horário) e o espelhamento depois do giro (0 nenhum, 1 horizontal, 2 vertical, 3 ambos)."""
    try: angle,flip=[int(job.get(key,0) or 0) for key in ('rotate_angle','rotate_flip')]
    except (TypeError,ValueError): raise ConversionError('Opções de giro inválidas.')
    if angle not in ROTATE_ANGLES or flip not in (0,1,2,3): raise ConversionError('O giro aceita 0, 90, 180 ou 270 graus; o espelhamento vai de 0 a 3.')
    if strict and not angle and not flip: raise ConversionError('Escolha um giro ou um espelhamento.')
    return angle,flip

def rotate_image(im,angle=0,flip=0):
    """Gira e depois espelha trocando pixels de lugar, sem reamostragem: o resultado não perde nada."""
    from PIL import Image
    T=Image.Transpose
    out=im.copy()
    for step in ({0:[],90:[T.ROTATE_270],180:[T.ROTATE_180],270:[T.ROTATE_90]}[angle]+{0:[],1:[T.FLIP_LEFT_RIGHT],2:[T.FLIP_TOP_BOTTOM],3:[T.ROTATE_180]}[flip]):
        nxt=out.transpose(step);out.close();out=nxt
    return out

def adjust_options_from(job,strict=True):
    """Lê brilho, contraste e saturação (−100 a 100) e o espelhamento (0 nenhum, 1 horizontal, 2 vertical, 3 ambos)."""
    try: values=[int(job.get(key,0) or 0) for key in ('adjust_brightness','adjust_contrast','adjust_saturation','adjust_flip')]
    except (TypeError,ValueError): raise ConversionError('Ajustes de imagem inválidos.')
    brightness,contrast,saturation,flip=values
    if not all(-ADJUST_RANGE<=v<=ADJUST_RANGE for v in values[:3]) or flip not in (0,1,2,3): raise ConversionError('Brilho, contraste e saturação ficam entre −100 e 100; o espelhamento é 0 a 3.')
    if strict and not any(values): raise ConversionError('Escolha pelo menos um ajuste: brilho, contraste, saturação ou espelhamento.')
    return brightness,contrast,saturation,flip

def adjust_image(im,brightness=0,contrast=0,saturation=0,flip=0):
    """Espelha e ajusta brilho, contraste e saturação (cada valor −100…100 vira um fator 0…2); o canal alfa não muda."""
    from PIL import Image, ImageEnhance, ImageOps
    work=im.convert('RGBA');alpha=work.getchannel('A');rgb=work.convert('RGB');work.close()
    if flip in (1,3): rgb=ImageOps.mirror(rgb)
    if flip in (2,3): rgb=ImageOps.flip(rgb)
    if flip in (1,3): alpha=ImageOps.mirror(alpha)
    if flip in (2,3): alpha=ImageOps.flip(alpha)
    for enhancer,value in ((ImageEnhance.Brightness,brightness),(ImageEnhance.Contrast,contrast),(ImageEnhance.Color,saturation)):
        if value: rgb=enhancer(rgb).enhance(1+value/100)
    out=rgb.convert('RGBA');out.putalpha(alpha);return out

SHARPEN_MODES=('sharpen','blur')

def sharpen_options_from(job,strict=True):
    """Lê o efeito (`sharpen`/`blur`), a força (1–100 %) e o raio (1–100, em milésimos do menor lado da imagem)."""
    mode=str(job.get('sharpen_mode','sharpen') or 'sharpen')
    try: amount=int(job.get('sharpen_amount',50)); radius=int(job.get('sharpen_radius',2))
    except (TypeError,ValueError): raise ConversionError('Nitidez e desfoque: força e raio inválidos.')
    if mode not in SHARPEN_MODES: raise ConversionError('O efeito deve ser nitidez ou desfoque.')
    if not 1<=amount<=100 or not 1<=radius<=100: raise ConversionError('A força e o raio ficam entre 1 e 100.')
    return {'mode':mode,'amount':amount,'radius':radius}

def sharpen_radius_px(size,radius):
    """Raio em pixels: proporcional ao menor lado, para a prévia reduzida ficar igual ao resultado."""
    return max(0.3,min(size)*radius/1000)

def sharpen_image(im,options):
    """Aplica nitidez (máscara de nitidez no RGB) ou desfoque gaussiano. O desfoque usa alfa pré-multiplicado, sem halo escuro nas bordas transparentes."""
    from PIL import Image, ImageFilter
    px=sharpen_radius_px(im.size,options['radius'])
    work=im.convert('RGBA')
    if options['mode']=='blur':
        soft=work.convert('RGBa').filter(ImageFilter.GaussianBlur(px));out=soft.convert('RGBA');soft.close();work.close();return out
    alpha=work.getchannel('A');rgb=work.convert('RGB');work.close()
    sharp=rgb.filter(ImageFilter.UnsharpMask(radius=px,percent=options['amount']*3,threshold=0));rgb.close()
    out=sharp.convert('RGBA');sharp.close();out.putalpha(alpha);alpha.close();return out

LEVELS_CLIP_PERCENT=0.5

def levels_options_from(job,strict=True):
    """Lê o modo (`levels_auto` 0 manual/1 automático), o ponto preto (0–254), o ponto branco (1–255) e o gama (10–500 = 0,10 a 5,00)."""
    try: auto=int(job.get('levels_auto',0) or 0);black=int(job.get('levels_black',0));white=int(job.get('levels_white',255));gamma=int(job.get('levels_gamma',100))
    except (TypeError,ValueError): raise ConversionError('Níveis inválidos.')
    if auto not in (0,1): raise ConversionError('O modo dos níveis deve ser manual ou automático.')
    if not 0<=black<=254 or not 1<=white<=255 or not 10<=gamma<=500: raise ConversionError('Ponto preto de 0 a 254, ponto branco de 1 a 255 e gama de 0,10 a 5,00.')
    if not auto and black>=white: raise ConversionError('O ponto preto precisa ser menor que o ponto branco.')
    if strict and not auto and (black,white,gamma)==(0,255,100): raise ConversionError('Mova um controle (ou use o modo automático) antes de aplicar os níveis.')
    return {'auto':auto,'black':black,'white':white,'gamma':gamma}

def luminance_histogram(im):
    """Histograma (256 contagens) da luminosidade dos pixels que não são totalmente transparentes."""
    work=im.convert('RGBA');alpha=work.getchannel('A');gray=work.convert('RGB').convert('L');work.close()
    hist=gray.histogram(mask=alpha.point(lambda a:255 if a else 0));gray.close();alpha.close();return hist

def levels_auto_points(im,clip=LEVELS_CLIP_PERCENT):
    """Pontos preto e branco que descartam `clip` % dos pixels mais escuros e mais claros; (0, 255) se a imagem é lisa."""
    hist=luminance_histogram(im);total=sum(hist)
    if not total: return 0,255
    cut=total*clip/100;acc=0;black=0
    for value,count in enumerate(hist):
        acc+=count
        if acc>cut: black=value;break
    acc=0;white=255
    for value in range(255,-1,-1):
        acc+=hist[value]
        if acc>cut: white=value;break
    return (0,255) if white-black<2 else (black,white)

def levels_resolve(im,opts):
    """Devolve (preto, branco, gama) a aplicar: os do usuário ou, no modo automático, os calculados para esta imagem."""
    if opts['auto']:
        black,white=levels_auto_points(im);return black,white,opts['gamma']
    return opts['black'],opts['white'],opts['gamma']

def levels_image(im,opts):
    """Aplica níveis ao RGB (mesma curva nos três canais, então a cor não desvia); o canal alfa não muda."""
    black,white,gamma=levels_resolve(im,opts);inv=100/gamma
    lut=[round(255*min(1.0,max(0.0,(v-black)/(white-black)))**inv) for v in range(256)]
    work=im.convert('RGBA');alpha=work.getchannel('A');rgb=work.convert('RGB');work.close()
    out=rgb.point(lut*3).convert('RGBA');rgb.close();out.putalpha(alpha);alpha.close();return out

SHAPE_KINDS=('rect','ellipse','line','arrow')
SHAPE_MAX_ITEMS=50
SHAPE_MAX_SUPERSAMPLE_PIXELS=16_000_000
SHAPE_DIRECTIONS=((1,1),(-1,1),(1,-1),(-1,-1))      # 0 ↘, 1 ↙, 2 ↗, 3 ↖: sentido do ponto de partida para a ponta

def shape_items_from(job,size):
    """Valida a lista de formas. Cada item: kind, x, y, w, h (caixa dentro da imagem já orientada), color (#RRGGBB), thickness (1–200 px),
    fill (0 contorno, 1 cheio; só retângulo e elipse) e dir (0–3; só linha e seta)."""
    raw=job.get('shape_items')
    if not isinstance(raw,(list,tuple)) or not 1<=len(raw)<=SHAPE_MAX_ITEMS: raise ConversionError(f'Desenhe de 1 a {SHAPE_MAX_ITEMS} formas.')
    items=[]
    for item in raw:
        if not isinstance(item,dict): raise ConversionError('Forma inválida.')
        try: x,y,w,h,thickness,fill,direction=[int(item.get(key,default)) for key,default in (('x',0),('y',0),('w',0),('h',0),('thickness',4),('fill',0),('dir',0))]
        except (TypeError,ValueError): raise ConversionError('Forma inválida.')
        kind=item.get('kind');color=str(item.get('color','#FF0000'))
        if kind not in SHAPE_KINDS or not re.fullmatch(r'#[0-9A-Fa-f]{6}',color): raise ConversionError('Tipo ou cor de forma inválidos.')
        if not 1<=thickness<=200 or fill not in (0,1) or direction not in (0,1,2,3): raise ConversionError('A espessura fica entre 1 e 200 px; preenchimento 0 ou 1; direção 0 a 3.')
        if x<0 or y<0 or w<1 or h<1 or x+w>size[0] or y+h>size[1]: raise ConversionError('Cada forma precisa caber dentro da imagem já orientada; as coordenadas começam no canto superior esquerdo.')
        items.append({'kind':kind,'x':x,'y':y,'w':w,'h':h,'color':color.upper(),'thickness':thickness,'fill':fill if kind in ('rect','ellipse') else 0,'dir':direction if kind in ('line','arrow') else 0})
    return items

def shape_endpoints(item):
    """Início e fim (coordenadas da imagem) de uma linha ou seta: cantos opostos da caixa; caixa muito achatada vira reta horizontal ou vertical."""
    x,y,w,h=item['x'],item['y'],item['w'],item['h'];sx,sy=SHAPE_DIRECTIONS[item['dir']]
    left,right,top,bottom=x,x+w,y,y+h
    if min(w,h)<=0.08*max(w,h):
        if w>=h: top=bottom=y+h/2;sy=0
        else: left=right=x+w/2;sx=0
    start=(left if sx>=0 else right,top if sy>=0 else bottom);end=(right if sx>=0 else left,bottom if sy>=0 else top)
    if sx==0: end=(start[0],end[1])
    if sy==0: end=(end[0],start[1])
    return start,end

def draw_shape(im,item):
    """Desenha uma forma em `im` (RGBA) com suavização: pinta numa região ampliada e reduz. Retorna a mesma imagem."""
    import math
    from PIL import Image, ImageColor, ImageDraw
    t=item['thickness'];pad=t*2+4
    left=max(0,item['x']-pad);top=max(0,item['y']-pad);right=min(im.width,item['x']+item['w']+pad);bottom=min(im.height,item['y']+item['h']+pad)
    rw,rh=right-left,bottom-top
    ss=max(1,min(4,int(math.sqrt(SHAPE_MAX_SUPERSAMPLE_PIXELS/max(1,rw*rh)))))
    layer=Image.new('RGBA',(rw*ss,rh*ss),(0,0,0,0));draw=ImageDraw.Draw(layer);color=ImageColor.getrgb(item['color'])+(255,)
    box=[(item['x']-left)*ss,(item['y']-top)*ss,(item['x']+item['w']-left)*ss-1,(item['y']+item['h']-top)*ss-1];width=max(1,t*ss)
    kind=item['kind']
    if kind=='rect': draw.rectangle(box,outline=color,fill=color if item['fill'] else None,width=width)
    elif kind=='ellipse': draw.ellipse(box,outline=color,fill=color if item['fill'] else None,width=width)
    else:
        (x0,y0),(x1,y1)=shape_endpoints(item);p0=((x0-left)*ss,(y0-top)*ss);p1=((x1-left)*ss,(y1-top)*ss)
        length=math.hypot(p1[0]-p0[0],p1[1]-p0[1]) or 1.0;ux,uy=(p1[0]-p0[0])/length,(p1[1]-p0[1])/length
        if kind=='arrow':
            head=min(length*0.6,max(t*ss*4,12*ss));half=head*0.5;bx,by=p1[0]-ux*head,p1[1]-uy*head
            draw.line([p0,(bx+ux*1,by+uy*1)],fill=color,width=width)
            draw.ellipse((p0[0]-width/2,p0[1]-width/2,p0[0]+width/2,p0[1]+width/2),fill=color)
            draw.polygon([p1,(bx-uy*half,by+ux*half),(bx+uy*half,by-ux*half)],fill=color)
        else:
            draw.line([p0,p1],fill=color,width=width)
            for px,py in (p0,p1): draw.ellipse((px-width/2,py-width/2,px+width/2,py+width/2),fill=color)
    if ss>1: layer=layer.resize((rw,rh),Image.Resampling.BOX)
    im.alpha_composite(layer,(left,top));layer.close();return im

def shapes_image(im,items):
    """Grava as formas, na ordem da lista, numa cópia RGBA da imagem."""
    out=im.convert('RGBA')
    for item in items: draw_shape(out,item)
    return out

def inspect_metadata(path):
    """Lê só o cabeçalho e lista, em português, o que o arquivo guarda além dos pixels. Nunca levanta erro.

    Devolve {'rows': [(rótulo, valor)], 'sensitive': [rótulos que costumam identificar pessoa/lugar/aparelho], 'error': str|None}.
    """
    rows=[];sensitive=[]
    try:
        from PIL import Image
        Image.MAX_IMAGE_PIXELS=MAX_PIXELS
        heif_needed(path)
        with Image.open(source_file(path)) as im:
            rows.append(('Formato',f'{im.format or "?"} · {im.width} × {im.height} px · modo {im.mode}'))
            exif=im.getexif()
            orientation=exif.get(0x0112)
            if orientation and orientation!=1: rows.append(('Orientação EXIF',f'{orientation} (será aplicada aos pixels)'))
            for tag,label in ((0x010F,'Fabricante da câmera'),(0x0110,'Modelo da câmera'),(0x0131,'Software'),(0x013B,'Autor'),(0x8298,'Direitos autorais'),(0x010E,'Descrição')):
                if exif.get(tag):
                    rows.append((label,_clean_text(exif[tag])))
                    if tag in (0x010F,0x0110,0x013B,0x8298,0x010E): sensitive.append(label)
            try: sub=exif.get_ifd(0x8769)
            except Exception: sub={}
            taken=sub.get(0x9003) or exif.get(0x0132)
            if taken: rows.append(('Data e hora',_clean_text(taken))); sensitive.append('Data e hora')
            if sub.get(0xA431): rows.append(('Número de série do corpo',_clean_text(sub[0xA431]))); sensitive.append('Número de série do corpo')
            try: gps=exif.get_ifd(0x8825)
            except Exception: gps={}
            if gps and 2 in gps and 4 in gps:
                rows.append(('Localização (GPS)',_gps_text(gps)));sensitive.append('Localização (GPS)')
            elif gps: rows.append(('Localização (GPS)','campos presentes sem coordenadas completas')); sensitive.append('Localização (GPS)')
            if any(key in im.info for key in ('xmp','XML:com.adobe.xmp')): rows.append(('XMP','presente (pode incluir autor, programa e histórico de edição)'));sensitive.append('XMP')
            comment=im.info.get('comment')
            if comment: rows.append(('Comentário',_clean_text(comment)))
            for key in ('Author','Description','Software','Title','Copyright'):
                if im.info.get(key): rows.append((f'Texto PNG: {key}',_clean_text(im.info[key])))
            if 'photoshop' in im.info: rows.append(('Photoshop/IPTC','presente'))
            icc=im.info.get('icc_profile')
            if icc: rows.append(('Perfil de cor ICC',f'presente ({len(icc)} bytes); é mantido na cópia limpa'))
    except Exception as error:
        return {'rows':rows,'sensitive':sensitive,'error':'Não foi possível ler os metadados: '+_clean_text(error,120)}
    if len(rows)<=1: rows.append(('Metadados','nenhum conhecido além dos pixels'))
    return {'rows':rows,'sensitive':sensitive,'error':None}

def ai_notes(items):
    """Frases do relatório de perdas para entradas .ai (`illustrator.describe_ai`)."""
    notes=[];ok=[v for v in items if 'error' not in v]
    for v in items:
        if 'error' in v: notes.append('Não foi possível ler um .ai: '+v['error'])
    if not ok: return notes
    first=ok[0];(w,h)=first['size'];(dw,dh)=first['declared']
    where=f'{w} × {h} px'+(f' (a página tem {dw:.0f} × {dh:.0f} pt)' if (round(dw),round(dh))!=(w,h) else ' (1 pt = 1 px, o tamanho da página)')
    notes.append(f'O .ai foi desenhado em pixels pelo {first["engine"][0]}, só a primeira página (prancheta): {where}. O resultado é uma imagem e não volta a ser vetor; para outro tamanho, desenhe de novo com outra largura.')
    if first['reduced']: notes.append('O tamanho da página passava de 8192 px por lado ou de 40 megapixels e foi reduzido na mesma proporção.')
    if any(v['pages']>1 for v in ok): notes.append('Este .ai tem mais de uma página; as outras não foram desenhadas.')
    notes.append('O fundo fica transparente. As cores vêm da parte de PDF do arquivo e podem diferir um pouco do Illustrator (conversão CMYK→RGB simples, sem simulação de impressão, sobreposição e tintas especiais); fontes não incorporadas são trocadas por outras; confira o resultado.')
    return notes

def metafile_notes(items):
    """Frases do relatório de perdas para entradas EMF/WMF (`metafile.describe_metafile`)."""
    notes=[];ok=[v for v in items if 'error' not in v]
    for v in items:
        if 'error' in v: notes.append('Não foi possível ler um EMF/WMF: '+v['error'])
    if not ok: return notes
    first=ok[0];(w,h)=first['size'];(dw,dh)=first['declared']
    where=f'{w} × {h} px'+(f' (o cabeçalho informa {dw:.0f} × {dh:.0f} px)' if (round(dw),round(dh))!=(w,h) else ' (tamanho do cabeçalho do arquivo)')
    notes.append(f'O metarquivo foi desenhado em pixels pelo {first["engine"][0]}: {where}. O resultado é uma imagem e não volta a ser vetor; para outro tamanho, desenhe de novo com outra largura (o desenho é refeito, não ampliado).')
    notes.append('O Windows desenha EMF/WMF sobre fundo branco opaco: o resultado não tem transparência (alfa 255), as bordas das formas não são suavizadas e o texto usa as fontes instaladas neste computador; confira o resultado.')
    if first['reduced']: notes.append('O tamanho do cabeçalho passava de 8192 px por lado ou de 40 megapixels e foi reduzido na mesma proporção.')
    return notes

def vector_notes(vectors):
    """Frases do relatório de perdas para entradas SVG/SVGZ (`vector.describe_svg`; itens com 'error' vieram de arquivos ilegíveis) e .ai."""
    meta_items=[v for v in vectors if v.get('kind')=='metafile']
    if meta_items:
        return vector_notes([v for v in vectors if v.get('kind')!='metafile'])+metafile_notes(meta_items) if len(meta_items)<len(vectors) else metafile_notes(meta_items)
    ai_items=[v for v in vectors if v.get('kind')=='ai']
    if ai_items:
        others=[v for v in vectors if v.get('kind')!='ai']
        return vector_notes(others)+ai_notes(ai_items) if others else ai_notes(ai_items)
    notes=[];ok=[v for v in vectors if 'error' not in v]
    for v in vectors:
        if 'error' in v: notes.append('Não foi possível ler um SVG: '+v['error'])
    if not ok: return notes
    first=ok[0];(w,h)=first['size'];(dw,dh)=first['declared']
    where=f'{w} × {h} px'+(f' (o arquivo declara {dw:.0f} × {dh:.0f} px)' if (round(dw),round(dh))!=(w,h) else ' (tamanho declarado no arquivo)')
    notes.append(f'O vetor foi desenhado em pixels: {where}. O resultado é uma imagem e não volta a ser vetor; para outro tamanho, desenhe de novo com outra largura (não amplie os pixels).')
    if first['reduced']: notes.append('O tamanho declarado passava de 8192 px por lado ou de 40 megapixels e foi reduzido na mesma proporção.')
    engine_label,full=first.get('engine') or ('desconhecido',False)
    if full: notes.append(f'Desenho feito pelo {engine_label} (SVG estático): o fundo fica transparente; o texto usa as fontes instaladas neste computador (fonte ausente é trocada por outra) e animações e scripts não rodam; confira o resultado.')
    else: notes.append(f'Desenho feito pelo {engine_label}, a alternativa embutida: ela não desenha recortes (clipPath), texto em caminho, <svg> aninhado nem a escala de <symbol>, e filtros e CSS avançado podem sair diferentes do navegador. Instale o pacote resvg-py para um desenho mais fiel.')
    dropped={}
    for v in ok:
        for key,count in v['dropped'].items(): dropped[key]=dropped.get(key,0)+count
    if dropped.get('externas'): notes.append('Referências externas (arquivos vizinhos, links, fontes da web) foram ignoradas por segurança; só o conteúdo do próprio SVG e imagens embutidas entram.')
    if dropped.get('scripts') or dropped.get('incorporados'): notes.append('Scripts, eventos e conteúdo incorporado (foreignObject, iframe…) foram descartados; nada foi executado.')
    return notes

def loss_report(paths, target, options=None):
    """Relatório do que a conversão muda ou perde, em português; só lê o cabeçalho das imagens de origem (nada é decodificado nem gravado).

    Devolve uma lista de frases. Reproduz as regras de `convert`; os testes comparam com as saídas reais para evitar divergência.
    """
    options=options or {}
    if target==tool_registry.PDF_IMAGES:
        out_key,out_quality,_flat=output_options_from(options,target,strict=False)
        dpi=options.get('pdf_dpi',pdfinfo.DPI_DEFAULT)
        notes=[f'Cada página virou uma imagem {OUTPUT_FORMATS[out_key][2]} desenhada a {dpi if type(dpi) is int else pdfinfo.DPI_DEFAULT} dpi sobre fundo branco; o que é vetorial (texto, desenhos) vira pixels e não pode mais ser selecionado nem ampliado sem perda.',
               'Campos de formulário e anotações (comentários, carimbos, realces) não são desenhados; a aparência pode diferir um pouco da de outros leitores de PDF.']
        if out_key in ('jpeg','avif','heic') or (out_key=='webp' and out_quality<100): notes.append(f'O formato {OUTPUT_FORMATS[out_key][2]} perde detalhes (qualidade {out_quality}).')
        if out_key=='gif': notes.append('GIF reduz cada página a 256 cores; fotos e degradês perdem qualidade.')
        return notes
    if target==PDF_FORM:
        return ['Os campos escolhidos são preenchidos no PDF novo, «<nome>-preenchido.pdf»; o original não muda. Se você escolher «achatar», os valores viram parte da página e o formulário deixa de ser editável.',
                'A imagem de assinatura é só uma imagem colocada na página: NÃO é assinatura digital certificada, não tem certificado, data confiável nem prova de quem assinou, e qualquer pessoa pode copiá-la ou removê-la.',
                'Assinaturas digitais que o PDF já tinha ficam inválidas; formulários XFA (formato antigo da Adobe) são tratados como formulário comum, sem a parte XFA.']
    if target==PDF_REDACT:
        return ['As páginas com tarja são desenhadas como imagem e as tarjas pintadas de preto NOS PIXELS: o texto, as imagens e os vetores originais dessas páginas deixam de existir no arquivo novo. Essas páginas perdem a camada de texto (não dá mais para selecionar nem pesquisar) e ficam maiores; comentários e campos de formulário delas não são desenhados.',
                'As outras páginas são copiadas como estão. O arquivo novo sai sem marcadores, anexos, formulários e metadados do original, que podiam guardar o texto tarjado. Assinaturas digitais ficam inválidas.',
                'Termos e padrões (CPF, CNPJ, e-mail, telefone) só acham texto que o PDF tem: texto dentro de imagens digitalizadas precisa ser tarjado por área. Padrões podem pegar números parecidos; confira. O app confere sozinho que as tarjas estão pretas e que não sobrou texto nas páginas tarjadas, mas a conferência final é sua: abra o resultado antes de enviar.']
    if target==PDF_PROTECT:
        notes=['O PDF novo, «<nome>-protegido.pdf», só abre com a senha, com criptografia AES-256. O Arquivo Local não guarda a senha em lugar nenhum: se você a perder, ninguém consegue recuperar o conteúdo.',
               'Restrições (imprimir, copiar, editar) valem só para programas que as respeitam e exigem a senha de permissões; quem tem a senha de abertura vê tudo o que o arquivo mostra.',
               'Texto, imagens, marcadores, anexos e formulários são mantidos; assinaturas digitais ficam inválidas. Nem todos os leitores antigos abrem AES-256.']
        return notes
    if target==PDF_UNPROTECT:
        return ['A cópia «<nome>-desprotegido.pdf» abre sem senha e traz o mesmo conteúdo. É preciso informar a senha: o Arquivo Local não adivinha nem quebra senhas, e a senha informada não é guardada.',
                'Se o PDF tiver restrições de uso (imprimir, copiar, editar), só a senha de permissões (proprietário) permite remover a cópia sem elas; a senha de abertura sozinha não basta.',
                'Quem pode abrir o arquivo só deve remover a senha de documentos que são seus ou que você tem permissão para usar.']
    if target==PDF_STAMP:
        notes=['O carimbo é texto vetorial (Helvetica) desenhado sobre a página: continua selecionável e o arquivo quase não cresce. O conteúdo da página fica por baixo e não é alterado; só as páginas escolhidas recebem o carimbo.',
               'Só letras latinas (com acentos), números e pontuação comum; {n} vira o número da página e {total} o total.']
        notes.append('A marca d\'água é desenhada por cima do conteúdo (não por baixo) e pode ser removida por quem editar o PDF: não serve como proteção.' if str(options.get('stamp_kind') or 'text')=='watermark' else 'O carimbo pode cobrir parte do conteúdo se a margem for pequena; confira a posição.')
        notes.append('Assinaturas digitais ficam inválidas (o arquivo foi reescrito); marcadores e anexos são mantidos.')
        return notes
    if target==AUDIO_TAGS:
        try: mode,cover,edits=audiotags.options_from(options)
        except audioconvert.MediaError as error: return [str(error)]
        info=None
        try:
            if paths: info=audioconvert.mediatools.probe(source_file(paths[0],AUDIO_MAX_BYTES))
        except (audioconvert.MediaError,ConversionError,OSError): info=None
        return audiotags.notes(info,mode,cover,edits)
    if target==AUDIO_CONVERT:
        try: fmt,quality,tags=audioconvert.options_from(options)
        except audioconvert.MediaError as error: return [str(error)]
        info=None
        try:
            if paths: info=audioconvert.mediatools.probe(source_file(paths[0],AUDIO_MAX_BYTES))
        except (audioconvert.MediaError,ConversionError,OSError): info=None
        return audioconvert.loss_notes(info,fmt,quality,tags)
    if target==PDF_COMPRESS:
        level=str(options.get('pdf_level') or pdfcompress.DEFAULT_LEVEL)
        dpi,quality,photos=pdfcompress.LEVELS.get(level,pdfcompress.LEVELS[pdfcompress.DEFAULT_LEVEL])
        notes=[f'Imagens simples (RGB ou cinza) maiores que {dpi} dpi na página são reduzidas a {dpi} dpi e recodificadas em JPEG (qualidade {quality}): há perda de qualidade nas fotos.'+(' Fotos guardadas sem perda também viram JPEG.' if photos else ' Fotos sem perda ficam como estão.')+' Texto, desenhos vetoriais, formulários, marcadores e anexos não são alterados.',
               'Imagens com transparência, máscara, paleta ou CMYK e imagens dentro de blocos internos da página não são tocadas. O arquivo só é salvo se ficar pelo menos 1 % menor; senão nada é salvo.',
               'Assinaturas digitais ficam inválidas (o arquivo foi reescrito). Confira o resultado: texto pequeno em imagens e digitalizações perdem nitidez nos níveis médio e forte.']
        return notes
    if target==PDF_CLEAN:
        notes=['A cópia limpa é um PDF novo, «<nome>-limpo.pdf»: o texto, as imagens e as páginas continuam iguais; só sai o que você marcou.']
        if str(options.get('meta_info') or 'on')!='off': notes.append('Metadados: o dicionário Info (autor, programa, datas), o XMP e os dados privados de aplicativos nas páginas são removidos. Metadados que ficam DENTRO das imagens (EXIF de fotos) e o histórico de edição que o programa tenha guardado no texto das páginas não são removidos.')
        if str(options.get('meta_attach') or 'on')!='off': notes.append('Anexos: arquivos embutidos e anotações de anexo são removidos; os originais não mudam.')
        if str(options.get('meta_js') or 'on')!='off': notes.append('JavaScript: scripts do documento, da abertura, de páginas, links e campos são removidos; campos de formulário continuam, mas cálculos e validações feitos por script deixam de funcionar. Dados XFA de formulários também saem.')
        notes.append('Assinaturas digitais ficam inválidas (o arquivo foi reescrito). Marque tudo que quiser remover antes de enviar o arquivo a outras pessoas e confira o resultado.')
        return notes
    if target in PDF_OCR_TARGETS:
        notes=['O OCR é aproximado: confira o resultado, principalmente números, acentos, tabelas e letras manuscritas. Nada é enviado para a internet; o reconhecimento roda no seu computador.',
               f'Cada página é desenhada a {ocr.DPI} dpi (fundo branco, sem anotações) e reconhecida; até {PDF_OCR_MAX_PAGES} páginas por vez.']
        if str(options.get('ocr_skip') or 'on')!='off': notes.append('Páginas que já têm texto não passam pelo OCR: ficam como estão (no PDF) ou usam o texto que já existe.')
        if target==PDF_OCR_PDF: notes.append('As páginas reconhecidas viram a imagem da página com o texto invisível por baixo (JPEG, qualidade 85): o PDF fica pesquisável, mas as páginas perdem o vetor original, marcadores, anexos, formulários e assinaturas. Só as páginas escolhidas entram no resultado.')
        else: notes.append('O texto não guarda posição nem formatação; a ordem de colunas e tabelas pode sair misturada.')
        return notes
    if target=='PDF → Text':
        notes=['O texto é extraído sem OCR: imagens e formatação não entram. Páginas digitalizadas (só imagem) não têm texto; se nenhuma página escolhida tiver texto, nada é salvo.',
               'A ordem de leitura depende de como o PDF foi montado; colunas e tabelas podem sair misturadas ou com espaços estranhos. Confira o resultado.']
        if str(options.get('text_layout') or '')=='layout': notes.append('O modo «Manter o layout» usa espaços para imitar as posições da página; o resultado fica mais largo.')
        return notes
    if target=='Extract PDF Images':
        return ['Imagens JPEG e JPEG 2000 são copiadas como estão no PDF, sem recomprimir; as demais são decodificadas e salvas em PNG (sem perda).',
                'Transparências guardadas à parte (máscaras), recortes e filtros de cor do PDF podem não aparecer na imagem extraída; a mesma imagem usada em várias páginas sai uma vez só.',
                'Imagens muito pequenas (ícones, filetes) são ignoradas conforme o tamanho mínimo escolhido.']
    if target=='Organize PDF':
        notes=['O PDF novo tem as páginas na ordem e com os giros escolhidos; páginas excluídas ficaram de fora e páginas duplicadas aparecem mais de uma vez.',
               'Marcadores, anexos, campos de formulário e assinaturas digitais não são preservados.']
        plan=options.get('organize_pages')
        if isinstance(plan,list) and len(plan)!=len(set(plan)): notes.append('Há páginas duplicadas: o arquivo fica maior.')
        return notes
    if target=='Split PDF':
        mode=str(options.get('split_mode') or 'each')
        first={'extract':'Só as páginas escolhidas foram copiadas para um PDF novo; as outras ficaram de fora.','every':'O PDF foi dividido em partes de N páginas (a última pode ter menos), cada uma um PDF novo.','ranges':'Cada grupo de páginas virou um PDF novo; uma página pode aparecer em mais de um grupo.'}.get(mode,'Cada página virou um PDF novo.')
        return [first,'Os marcadores das páginas copiadas são mantidos quando o arquivo permite; anexos, campos de formulário e assinaturas digitais não são preservados.']
    if target=='Merge PDFs':
        notes=['As páginas foram unidas na ordem da lista. Cada arquivo ganhou um marcador com o nome dele e os marcadores que ele já tinha foram mantidos (quando o arquivo permite).',
               'Campos de formulário, anexos e assinaturas digitais não são preservados; links e anotações entre arquivos diferentes podem deixar de funcionar.']
        chosen=[x for x in (options.get('merge_ranges') or []) if isinstance(x,str) and x.strip()] if isinstance(options.get('merge_ranges'),list) else []
        if chosen: notes.insert(1,f'Em {len(chosen)} {"arquivo" if len(chosen)==1 else "arquivos"} só entraram as páginas escolhidas; as outras ficaram de fora.')
        return notes
    if target not in OPERATIONS: return []
    if target in OCR_TARGETS:
        lang,_psm=ocr_options_from(options,strict=False)
        notes=['O OCR é aproximado: confira o resultado, principalmente números, acentos, tabelas e letras manuscritas. Nada é enviado para a internet; o reconhecimento roda no seu computador.',
               'Idioma usado: '+ocr.LANGS[lang]+'. Imagens de cabeça para baixo ou inclinadas não são corrigidas (use «Girar» antes); a ordem de colunas e tabelas pode sair misturada.',
               'Transparência vira fundo branco antes de reconhecer; imagens com mais de %d px de lado são reduzidas e as muito pequenas são ampliadas (no texto).'%ocr.MAX_SIDE]
        if target==OCR_PDF: notes.append('O PDF guarda a imagem como está (sem perfil de cor nem metadados da origem) e o texto invisível por baixo, para buscar e copiar; é uma página, com 300 dpi assumidos.')
        else: notes.append('O arquivo de texto não guarda posição nem formatação, só as linhas reconhecidas, em UTF-8.')
        ready,message=ocr.status()
        if not ready: notes.append(message)
        return notes
    from PIL import Image
    notes=[];heif_deep=False;lossy_source=False;alpha=False;metadata=False;oriented=False;profile=None;sixteen=False;cmyk=None;first_size=None
    vectors=[]
    for raw in paths:
        if Path(str(raw)).suffix.lower() in VECTOR_INPUTS:
            alpha=True
            try:
                width=VECTOR_WIDTH if not options.get('vector_width') else int(options['vector_width'])
                if Path(str(raw)).suffix.lower() in AI_INPUTS:
                    import illustrator
                    info=illustrator.describe_ai(source_file(raw),width)
                elif Path(str(raw)).suffix.lower() in METAFILE_INPUTS:
                    import metafile
                    info=metafile.describe_metafile(source_file(raw),width)
                else:
                    import vector
                    info=vector.describe_svg(source_file(raw),width)
                vectors.append(info);first_size=first_size or info['size']
            except Exception as error: vectors.append({'error':str(error),'kind':'ai' if Path(str(raw)).suffix.lower() in AI_INPUTS else ('metafile' if Path(str(raw)).suffix.lower() in METAFILE_INPUTS else 'svg')})
            continue
        try:
            if Path(str(raw)).suffix.lower() in HEIF_INPUTS: heif_register()
            with Image.open(source_file(raw)) as im:
                alpha=alpha or im.mode in ('RGBA','LA','PA') or 'transparency' in im.info
                lossy_source=lossy_source or im.format in ('JPEG','WEBP','HEIF','AVIF')
                if im.format=='HEIF' and int(im.info.get('bit_depth',8) or 8)>8: heif_deep=True
                exif=im.getexif()
                metadata=metadata or bool(exif) or any(key in im.info for key in ('exif','xmp','XML:com.adobe.xmp','comment','photoshop'))
                orientation=exif.get(0x0112,1)
                oriented=oriented or orientation in (2,3,4,5,6,7,8)
                first_size=first_size or (im.size[::-1] if orientation in (5,6,7,8) else im.size)
                sixteen=sixteen or im.mode.startswith('I')
                icc=im.info.get('icc_profile')
                if im.mode=='CMYK':
                    cmyk_profile=False
                    if icc:
                        try:
                            import io
                            from PIL import ImageCms
                            cmyk_profile=ImageCms.ImageCmsProfile(io.BytesIO(icc)).profile.xcolor_space.strip()=='CMYK'
                        except Exception: pass
                    cmyk=cmyk or ('perfil' if cmyk_profile else 'sem perfil')
                elif icc:
                    effective='L' if im.mode in ('L','LA','I','F') or im.mode.startswith('I;16') else 'RGB'
                    found='ok' if icc_for_output(icc,effective) else 'descartado'
                    profile='descartado' if 'descartado' in (profile,found) else found
        except Exception: continue
    if vectors:
        notes.extend(vector_notes(vectors))
    if heif_deep: notes.append('O HEIC tem mais de 8 bits por canal (HDR); foi reduzido para 8 bits, então cor e faixa dinâmica podem mudar.')
    to_flat=target in ('JPEG','BMP','Image → PDF','Compress → JPEG')
    out_key,out_quality,out_flatten=output_options_from(options,target,strict=False) if target in tool_registry.FORMAT_TARGETS else ('png',90,'#FFFFFF')
    out_recompress=out_key in ('jpeg','avif','heic') or (out_key=='webp' and out_quality<100)
    out_lossy=out_recompress or out_key in ('gif','ico')      # GIF reduz as cores; ICO redimensiona
    if target in tool_registry.FORMAT_TARGETS and out_key!='png':
        label=OUTPUT_FORMATS[out_key][2]
        if out_key=='jpeg': notes.append(f'Salvo em {label} (qualidade {out_quality}): formato com perda; detalhes finos não voltam.')
        elif out_key=='webp': notes.append('Salvo em WebP sem perda.' if out_quality>=100 else f'Salvo em WebP com perda (qualidade {out_quality}); use 100 para não perder nada.')
        elif out_key=='heic': notes.append(f'Salvo em HEIC (qualidade {out_quality}): formato com perda'+(' (na qualidade máxima o codificador usa o modo sem perda, mas a conversão de cor ainda pode mudar um nível por canal)' if out_quality>=100 else '')+'; detalhes finos não voltam. A transparência é mantida. O HEIC usa HEVC (há patentes de terceiros) e o Windows pode exigir as extensões HEIF e HEVC da Microsoft Store para abri-lo.'+(' Em qualidade 95 ou mais as cores não são reduzidas (4:4:4).' if out_quality>=95 else ''))
        elif out_key=='avif': notes.append(f'Salvo em AVIF (qualidade {out_quality}): formato sempre com perda, mesmo na qualidade máxima; detalhes finos não voltam. A transparência é mantida. O arquivo só abre em programas e navegadores recentes.'+(' Em qualidade 95 ou mais as cores não são reduzidas (4:4:4).' if out_quality>=95 else ''))
        elif out_key=='gif': notes.append('Salvo em GIF estático (sem animação): no máximo 256 cores, com pontilhado; degradês e fotos perdem qualidade. A transparência é de 1 bit: pixels meio transparentes ficam totalmente transparentes ou totalmente opacos.')
        elif out_key=='ico': notes.append('Salvo como ícone (.ico) quadrado com os tamanhos padrão de 16 a 256 px que cabem na imagem. Imagens maiores que 256 px são reduzidas; as não quadradas ficam centralizadas em fundo transparente (nada é cortado). A transparência é mantida.')
        else: notes.append(f'Salvo em {label}.')
        if lossy_source and out_recompress: notes.append('A origem já tinha perda; recomprimir acumula perdas.')
        if alpha and out_key in ('jpeg','bmp') and target not in ('Canvas → PNG','Backdrop → PNG','Collage → PNG'):
            notes.append(f'{label} não tem transparência: ela foi substituída pela cor {out_flatten.upper()}.')
        if out_lossy and target=='Redact → PNG': notes.append('As áreas ocultadas foram gravadas antes da compactação; o conteúdo coberto não está no arquivo.')
    if target in ('JPEG','Compress → JPEG'):
        notes.append(f'JPEG é um formato com perda (qualidade {int(options.get("quality",90))}); detalhes finos não voltam.')
    if target=='WEBP': notes.append('WebP foi salvo com perda (qualidade padrão do Pillow).')
    if lossy_source and target in ('JPEG','Compress → JPEG','WEBP'): notes.append('A origem já tinha perda; recomprimir acumula perdas.')
    if alpha and (to_flat or target=='Collage → PNG'):
        notes.append('A transparência foi substituída pela cor de fundo.' if target=='Collage → PNG' else 'A transparência foi substituída por fundo branco.')
    if target=='Canvas → PNG': notes.append('A imagem foi colocada sobre um fundo opaco do canvas.')
    if target=='Backdrop → PNG': notes.append('A imagem foi composta sobre o fundo escolhido; margem, cantos arredondados e sombra ficaram gravados nos pixels; o resultado é opaco.')
    if target=='Resize → PNG':
        mode,percent,width,height=resize_options_from(options)
        try: new=resize_target_size(first_size,mode,percent or 100,width,height) if first_size else None
        except ConversionError: new=None
        if new and first_size:
            word='ampliada' if new[0]*new[1]>first_size[0]*first_size[1] else ('reduzida' if new!=tuple(first_size) else 'mantida no mesmo tamanho')
            notes.append(f'Imagem {word}: {first_size[0]} × {first_size[1]} px → {new[0]} × {new[1]} px (Lanczos).'+(' Ampliar não cria detalhe novo; a imagem pode ficar borrada.' if word=='ampliada' else ''))
            if mode=='exact' and abs(new[0]/new[1]-first_size[0]/first_size[1])>0.01: notes.append('A proporção original não foi mantida; a imagem pode parecer esticada.')
        else: notes.append('Imagem redimensionada com Lanczos.')
    if target=='Watermark → PNG':
        wm=watermark_options_from(options,strict=False)
        where={'tl':'no canto superior esquerdo','tc':'no topo','tr':'no canto superior direito','ml':'à esquerda','c':'no centro','mr':'à direita','bl':'no canto inferior esquerdo','bc':'embaixo','br':'no canto inferior direito','tile':'repetida na diagonal'}[wm['position']]
        notes.append(f'Marca d\'água ({"texto" if wm["kind"]=="text" else "imagem"}) gravada nos pixels {where}, com {wm["opacity"]} % de opacidade e {wm["scale"]} % da largura; não dá para removê-la do arquivo novo.')
        if wm['kind']=='image': notes.append('A imagem da marca foi lida só para compor o resultado; o arquivo dela não foi alterado.')
    if target=='Rotate → PNG':
        angle,flip=rotate_options_from(options,strict=False)
        parts=[{90:'girada 90° para a direita',180:'girada 180°',270:'girada 90° para a esquerda'}[angle]] if angle else []
        if flip: parts.append({1:'espelhada na horizontal',2:'espelhada na vertical',3:'espelhada nos dois eixos'}[flip])
        notes.append('Imagem '+' e '.join(parts)+': os pixels só trocaram de lugar, sem reamostragem e sem perda.'+(f' Tamanho {first_size[0]} × {first_size[1]} px → {first_size[1]} × {first_size[0]} px.' if angle in (90,270) and first_size else ''))
    if target=='Adjust → PNG':
        brightness,contrast,saturation,flip=adjust_options_from(options,strict=False)
        parts=[f'{name} {value:+d}' for name,value in (('brilho',brightness),('contraste',contrast),('saturação',saturation)) if value]
        if flip: parts.append({1:'espelhada na horizontal',2:'espelhada na vertical',3:'espelhada nos dois eixos'}[flip])
        notes.append('Ajustes gravados nos pixels ('+', '.join(parts)+'); não dá para desfazê-los no arquivo novo. Realces e sombras fortes podem perder detalhe.')
    if target=='Shapes → PNG':
        items=options.get('shape_items') or []
        names={'rect':'retângulo','ellipse':'elipse','line':'linha','arrow':'seta'};kinds=', '.join(f'{sum(1 for i in items if isinstance(i,dict) and i.get("kind")==k)} {names[k]}' for k in SHAPE_KINDS if any(isinstance(i,dict) and i.get('kind')==k for i in items))
        notes.append(f'{len(items)} forma(s) gravada(s) nos pixels ({kinds}), na ordem em que foram desenhadas; não dá para editá-las nem removê-las no arquivo novo. As posições valem para esta imagem; formas cheias cobrem o que está embaixo.')
    if target=='Levels → PNG':
        opt=levels_options_from(options,strict=False)
        how='pontos preto e branco calculados para cada imagem (descartando 0,5 % dos pixels de cada ponta)' if opt['auto'] else f'preto em {opt["black"]}, branco em {opt["white"]}'
        notes.append(f'Níveis gravados nos pixels ({how}; gama {opt["gamma"]/100:.2f}), com a mesma curva nos três canais. Tons abaixo do ponto preto ou acima do branco viram preto ou branco puro e perdem detalhe; não dá para desfazer no arquivo novo.')
    if target==BG_TARGET:
        opt=bg_options_from(options,strict=False)
        notes.append('O fundo foi removido por uma rede neural (U²-Net, '+bgremove.MODELS[opt['model']][3]+') que escolhe o objeto de destaque: confira o resultado, pois cabelos finos, vidro, sombras, objetos parecidos com o fundo e imagens com vários objetos podem sair errados. Tudo roda no seu computador, sem internet.')
        notes.append(f'A borda foi suavizada em {opt["feather"]} px. O que foi apagado ficou transparente no PNG novo (transparência que a imagem já tinha é mantida); não dá para recuperar o fundo nesse arquivo, mas o original não muda. Em JPEG o fundo transparente vira branco.')
        ready,message=bgremove.status(opt['model'])
        if not ready: notes.append(message)
    if target=='Sharpen → PNG':
        opt=sharpen_options_from(options,strict=False);px=sharpen_radius_px(first_size,opt['radius']) if first_size else None
        where=f' (raio ≈ {px:.1f} px na primeira imagem)' if px else ''
        if opt['mode']=='blur': notes.append(f'Desfoque gaussiano gravado nos pixels{where}; o detalhe perdido não volta, nem com nitidez depois.')
        else: notes.append(f'Nitidez ({opt["amount"]} %) gravada nos pixels{where}; ela realça bordas e ruído e pode criar halos claros ao redor de contornos fortes. Não recupera detalhe que a foto não tem.')
    if target=='Clean → PNG':
        notes.append(('Os pixels foram recompactados com perda, então não são idênticos aos do original; a cópia ' if out_lossy else 'Os pixels não mudaram (só a orientação do EXIF foi aplicada); a cópia ')+'não leva EXIF, GPS, XMP nem comentários. O perfil de cor foi mantido quando o formato permite. O original continua com os metadados.')
        if not metadata: notes.append('A origem não tinha metadados conhecidos.')
    if target=='Redact → PNG':
        count=len(options.get('redact_regions') or [])
        notes.append(f'{count} área(s) ocultada(s) com {"pixelização" if options.get("redact_mode")=="pixelate" else "tarja preta"}, gravadas nos pixels; o conteúdo original dessas áreas não está no resultado. Metadados não foram copiados. Não é anonimização certificada: confira o resultado.')
    if target=='Annotate → PNG': notes.append('O texto da anotação ficou gravado nos pixels; não dá para editá-lo depois.')
    if target=='Crop → PNG': notes.append(f'Foi mantida só a área recortada ({int(options.get("crop_width",0))} × {int(options.get("crop_height",0))} px); o resto não está no resultado.')
    if target==ONEPDF:
        try: opt=onepdf_options_from(options)
        except ConversionError: opt=onepdf_options_from({})
        where='cada página tem o tamanho da própria imagem' if opt['page']=='image' else f'páginas {PDF_PAGES[opt["page"]][0]} (orientação conforme a imagem), margem de {opt["margin"]} mm, imagem ajustada à área útil e centralizada, podendo ser ampliada'
        notes.append(f'{len(paths)} página(s) na ordem da lista; {where}. As páginas são imagens gravadas a {PDF_DPI} dpi e compactadas em JPEG (qualidade {opt["quality"]}), então há perda de qualidade e o texto das imagens não é selecionável (sem OCR). A transparência vira fundo branco, as cores foram convertidas para sRGB e EXIF/GPS não entram no PDF.')
        if opt['ocr']!='off': notes.append('Texto pesquisável (OCR, '+ocr.LANGS[opt['ocr']]+'): cada página passou pelo Tesseract no seu computador e guarda a imagem como está (sem recompactar em JPEG) com o texto invisível por baixo, para buscar e copiar; o OCR é aproximado, então confira números, acentos e tabelas. As páginas têm o tamanho da imagem a 300 dpi. Páginas sem texto reconhecível entram só como imagem.')
    if target=='Collage → PNG': notes.append('Cada imagem foi reduzida para caber na célula, se maior; imagens menores não são ampliadas.')
    width=int(options.get('width',0) or 0)
    if width and first_size and max(first_size)>width and target in {'JPEG','PNG','WEBP','TIFF','BMP','Image → PDF'}:
        notes.append(f'A imagem foi reduzida para no máximo {width} px no lado maior (original {first_size[0]} × {first_size[1]} px).')
    if metadata: notes.append('Metadados da origem (EXIF, como câmera, data e localização, além de XMP e comentários) não foram copiados.')
    if oriented: notes.append('A orientação do EXIF foi aplicada aos pixels da imagem.')
    if sixteen: notes.append('Tons de cinza de 16 bits foram reduzidos para 8 bits.')
    if cmyk=='sem perfil': notes.append('CMYK foi convertido para RGB sem perfil de cor; as cores são aproximadas.')
    elif cmyk: notes.append('CMYK foi convertido para RGB; as cores podem diferir um pouco.')
    if profile=='ok':
        if target in ('BMP','Image → PDF','Collage → PNG') or out_key=='bmp': notes.append('As cores foram convertidas do perfil embutido para sRGB, pois este resultado não guarda perfil.')
        else: notes.append('O perfil de cor embutido foi preservado quando compatível com o resultado.')
    elif profile=='descartado': notes.append('O perfil de cor embutido era inválido ou incompatível e foi descartado.')
    try: custom=rename_options_from(options) if target in RENAMEABLE_TARGETS or target in ('Collage → PNG',ONEPDF) else None
    except ConversionError: custom=None
    if custom: notes.append(f'Nome do arquivo novo montado pelo padrão «{custom["pattern"]}»; se já existir um arquivo com esse nome, o novo recebe -2, -3… e nada é sobrescrito. O original não é renomeado nem movido.')
    return notes or ['Nenhuma perda adicional conhecida nesta conversão.']

def read_pdf(p):
    """Abre um PDF para unir, separar ou extrair texto, com as verificações de `pdfinfo` (tamanho, cabeçalho, senha, 1–200 páginas)."""
    try: return pdfinfo.open_reader(p)
    except pdfinfo.PdfError as error: raise ConversionError(f'{Path(p).name}: {error}') from error

def convert(job):
    previous=VECTOR_WIDTH
    set_vector_width(vector_width_from(job))
    try: return _convert(job)
    finally: set_vector_width(previous)

def _convert(job):
    target=job.get('target')
    if target not in OPERATIONS: raise ConversionError('Operação não suportada.')
    raws=job.get('paths',[])
    if not isinstance(raws,list) or not 1<=len(raws)<=100: raise ConversionError('Selecione de 1 a 100 arquivos.')
    limit=AUDIO_MAX_BYTES if target in AUDIO_TARGETS else MAX_BYTES
    paths=[source_file(p,limit) for p in raws]
    if target not in ('Merge PDFs','Collage → PNG',ONEPDF) and len(paths)!=1: raise ConversionError('Cada conversão aceita um arquivo; use a fila em lote.')
    folder=output_folder(job.get('output') or paths[0].parent)
    work_root=folder
    if job.get('_work_root'):
        work_root=output_folder(job['_work_root'])
        if work_root.parent!=folder or not work_root.name.startswith('.arquivo-local-work-'):
            raise ConversionError('Pasta de preparo do job inválida.')
    p=paths[0]; stem=p.stem+'-'+TOOL_SUFFIX.get(target,'converted');results=[]
    rename=rename_options_from(job)
    if rename and (target in RENAMEABLE_TARGETS or target in ('Collage → PNG',ONEPDF)): stem=rename_stem(rename,p.stem,TOOL_SUFFIX.get(target,'converted'))
    else: rename=None
    with tempfile.TemporaryDirectory(prefix='.arquivo-local-tmp-',dir=work_root) as work:
        stage=Path(work)/'output'
        if target=='Collage → PNG':
            if any(x.suffix.lower() not in IMAGE_INPUTS for x in paths): raise ConversionError('A colagem exige somente imagens suportadas.')
            collage=build_collage(paths,int(job.get('collage_columns',0)),int(job.get('collage_cell',600)),int(job.get('collage_gap',20)),str(job.get('background','#FFFFFF')))
            try:
                out_key,out_quality,out_flatten=output_options_from(job,target)
                final=finalize_for_format(collage,out_key,out_flatten)
                collage=final
                final.save(stage,format=OUTPUT_FORMATS[out_key][0],**format_save_options(out_key,out_quality,final.info.get('transparency'),final.width))
                results.append(publish(stage,folder,rename_stem(rename,'colagem','colagem') if rename else 'collage',OUTPUT_FORMATS[out_key][1]))
            finally: collage.close()
        elif target==ONEPDF:
            if any(x.suffix.lower() not in IMAGE_INPUTS for x in paths): raise ConversionError('Esta operação exige somente imagens suportadas.')
            onepdf_opt=onepdf_options_from(job)
            if onepdf_opt['ocr']!='off': build_onepdf_ocr(paths,onepdf_opt,work,stage)
            else: build_onepdf(paths,onepdf_opt,stage)
            results.append(publish(stage,folder,rename_stem(rename,'imagens','imagens') if rename else 'images','pdf'))
        elif target in OCR_TARGETS:
            if p.suffix.lower() not in IMAGE_INPUTS: raise ConversionError('Esta operação exige uma imagem suportada.')
            ocr_options_from(job)
            im=open_image(p)
            results.append(publish(stage,folder,stem,run_ocr(im,job,'txt' if target==OCR_TEXT else 'pdf',work,stage)))
        elif target in IMAGE_OUTPUTS or target=='Image → PDF':
            if p.suffix.lower() not in IMAGE_INPUTS: raise ConversionError('Esta operação exige uma imagem suportada.')
            from PIL import Image
            im=open_image(p)
            out_key,out_quality,out_flatten=output_options_from(job,target)
            icc=im.info.get('icc_profile')
            if (target in ('BMP','Image → PDF','Backdrop → PNG') or out_key=='bmp') and icc:
                converted=to_srgb(im,icc)
                if converted is not im: im.close();im=converted
                icc=None
            try:
                basic_conversion=target in {'PNG','JPEG','WEBP','TIFF','BMP','Image → PDF'}
                width=int(job.get('width',0)) if basic_conversion else 0
                rotation=int(job.get('rotation',0)) if basic_conversion else 0
                quality=int(job.get('quality',90))
                if not 0<=width<=10000 or rotation not in (0,90,180,270) or not 1<=quality<=100: raise ConversionError('Opções de imagem inválidas.')
                if target=='Crop → PNG':
                    x=int(job.get('crop_x',-1));y=int(job.get('crop_y',-1));crop_width=int(job.get('crop_width',0));crop_height=int(job.get('crop_height',0))
                    if x<0 or y<0 or crop_width<1 or crop_height<1 or x+crop_width>im.width or y+crop_height>im.height:
                        raise ConversionError('A área de recorte precisa caber dentro da imagem já orientada; as coordenadas começam no canto superior esquerdo.')
                    cropped=im.crop((x,y,x+crop_width,y+crop_height));im.close();im=cropped
                elif target=='Canvas → PNG':
                    from PIL import ImageColor
                    canvas_width=int(job.get('canvas_width',0));canvas_height=int(job.get('canvas_height',0));background=str(job.get('background','#FFFFFF'))
                    if not 1<=canvas_width<=10000 or not 1<=canvas_height<=10000 or canvas_width<im.width or canvas_height<im.height or canvas_width*canvas_height>MAX_PIXELS:
                        raise ConversionError('O canvas precisa comportar a imagem e ficar dentro de 40 megapixels.')
                    if not re.fullmatch(r'#[0-9A-Fa-f]{6}',background): raise ConversionError('A cor do canvas deve estar no formato hexadecimal #RRGGBB.')
                    canvas=Image.new('RGBA',(canvas_width,canvas_height),ImageColor.getrgb(background)+(255,))
                    rgba=im.convert('RGBA');canvas.alpha_composite(rgba,((canvas_width-im.width)//2,(canvas_height-im.height)//2));rgba.close();im.close();im=canvas
                elif target=='Backdrop → PNG':
                    rgba=im.convert('RGBA');im.close()
                    try: im=build_backdrop(rgba,str(job.get('backdrop_style','sunset')),str(job.get('background','#FFFFFF')),int(job.get('backdrop_padding',80)),int(job.get('backdrop_radius',24)),int(job.get('backdrop_shadow',30)),str(job.get('backdrop_ratio','auto')))
                    finally: rgba.close()
                elif target=='Redact → PNG':
                    regions=redact_regions_from(job,im.size)
                    redacted=redact_image(im,regions,str(job.get('redact_mode','black')),job.get('redact_block',16));im.close();im=redacted
                elif target=='Clean → PNG':
                    pass
                elif target=='Resize → PNG':
                    resized=resize_image(im,*resize_options_from(job,im.size));im.close();im=resized
                elif target=='Watermark → PNG':
                    options_wm=watermark_options_from(job);logo=None
                    if options_wm['kind']=='image':
                        logo_path=source_file(options_wm['image'])
                        if logo_path.suffix.lower() not in IMAGE_INPUTS: raise ConversionError('A marca d\'água precisa ser uma imagem suportada.')
                        logo=open_image(logo_path)
                    try: marked=watermark_image(im,options_wm,logo)
                    finally:
                        if logo is not None: logo.close()
                    im.close();im=marked
                elif target=='Rotate → PNG':
                    turned=rotate_image(im,*rotate_options_from(job));im.close();im=turned
                elif target=='Adjust → PNG':
                    adjusted=adjust_image(im,*adjust_options_from(job));im.close();im=adjusted
                elif target=='Shapes → PNG':
                    shaped=shapes_image(im,shape_items_from(job,im.size));im.close();im=shaped
                elif target=='Levels → PNG':
                    leveled=levels_image(im,levels_options_from(job));im.close();im=leveled
                elif target==BG_TARGET:
                    removed=run_bg_remove(im,job);im.close();im=removed
                elif target=='Sharpen → PNG':
                    sharpened=sharpen_image(im,sharpen_options_from(job));im.close();im=sharpened
                elif target=='Annotate → PNG':
                    from PIL import ImageColor, ImageDraw, ImageFont
                    text=job.get('annotation','');x=int(job.get('annotation_x',0));y=int(job.get('annotation_y',0));color=str(job.get('annotation_color','#FF0000'));font_size=int(job.get('annotation_size',18))
                    if not isinstance(text,str) or not text.strip() or len(text)>200 or any(ord(char)<32 for char in text):
                        raise ConversionError('A anotação deve ter de 1 a 200 caracteres imprimíveis.')
                    if not 8<=font_size<=400 or not 0<=x<im.width or not 0<=y<im.height or not re.fullmatch(r'#[0-9A-Fa-f]{6}',color):
                        raise ConversionError('A posição, o tamanho (8–400 px) ou a cor #RRGGBB da anotação é inválido.')
                    rgba=im.convert('RGBA');im.close();im=rgba
                    font=load_font(font_size)
                    ImageDraw.Draw(im).text((x,y),text,fill=ImageColor.getrgb(color)+(255,),font=font)
                if width: im.thumbnail((width,width),Image.Resampling.LANCZOS)
                if rotation:
                    rotated=im.rotate(-rotation,expand=True);im.close();im=rotated
                if target in tool_registry.FORMAT_TARGETS:
                    im=finalize_for_format(im,out_key,out_flatten)
                elif target in ('JPEG','BMP','Image → PDF','Compress → JPEG'):
                    rgba=im.convert('RGBA');base=Image.new('RGB',rgba.size,'white');base.paste(rgba,mask=rgba.getchannel('A'));rgba.close();im.close();im=base
                elif im.mode not in ('RGB','RGBA','L','LA'):
                    converted=im.convert('RGBA');im.close();im=converted
                # Drop ancillary metadata; this is not a certified anonymizer.
                keep_transparency=im.info.get('transparency') if out_key=='gif' and target in tool_registry.FORMAT_TARGETS else None
                im.info.clear()
                fmt='PDF' if target=='Image → PDF' else ('JPEG' if target=='Compress → JPEG' else (OUTPUT_FORMATS[out_key][0] if target in tool_registry.FORMAT_TARGETS else target))
                save_options=format_save_options(out_key,out_quality,keep_transparency,im.width) if target in tool_registry.FORMAT_TARGETS else ({'quality':quality} if fmt=='JPEG' else (format_save_options('webp',quality) if fmt=='WEBP' else {}))      # WebP rápido respeita a qualidade (antes usava o padrão 80 do Pillow; 100 = sem perda)
                final_icc=icc_for_output(icc,im.mode) if fmt in ('PNG','JPEG','WEBP','TIFF','AVIF','HEIF') else None
                if final_icc: save_options['icc_profile']=final_icc
                if target=='Compress → JPEG': save_options['optimize']=True
                im.save(stage,format=fmt,**save_options)
                ext='pdf' if fmt=='PDF' else (OUTPUT_FORMATS[out_key][1] if target in tool_registry.FORMAT_TARGETS else IMAGE_OUTPUTS[target])
                results.append(publish(stage,folder,stem,ext))
            finally: im.close()
        elif target==tool_registry.PDF_IMAGES:
            if p.suffix.lower()!='.pdf': raise ConversionError('Selecione somente arquivos PDF.')
            results.extend(pdf_to_images(p,job,folder,work))
        elif target==PDF_FORM:
            if p.suffix.lower()!='.pdf': raise ConversionError('Selecione somente arquivos PDF.')
            results.extend(pdf_form(p,read_pdf(p),job,folder,stage))
        elif target==PDF_REDACT:
            if p.suffix.lower()!='.pdf': raise ConversionError('Selecione somente arquivos PDF.')
            results.extend(pdf_redact(p,read_pdf(p),job,folder,work,stage))
        elif target==PDF_PROTECT:
            if p.suffix.lower()!='.pdf': raise ConversionError('Selecione somente arquivos PDF.')
            results.extend(pdf_protect(p,read_pdf(p),job,folder,stage))
        elif target==PDF_UNPROTECT:
            if p.suffix.lower()!='.pdf': raise ConversionError('Selecione somente arquivos PDF.')
            results.extend(pdf_unprotect(p,job,folder,stage))
        elif target==PDF_STAMP:
            if p.suffix.lower()!='.pdf': raise ConversionError('Selecione somente arquivos PDF.')
            results.extend(pdf_stamp(p,read_pdf(p),job,folder,stage))
        elif target==AUDIO_TAGS:
            try: done=audiotags.apply(p,stage,job)
            except audioconvert.MediaError as error: raise ConversionError(f'{p.name}: {error}') from error
            results.append(publish(stage,folder,stem,done['suffix']))
        elif target==AUDIO_CONVERT:
            try: done=audioconvert.convert(p,stage,job)
            except audioconvert.MediaError as error: raise ConversionError(f'{p.name}: {error}') from error
            results.append(publish(stage,folder,stem,done['suffix']))
        elif target==PDF_COMPRESS:
            if p.suffix.lower()!='.pdf': raise ConversionError('Selecione somente arquivos PDF.')
            results.extend(pdf_compress(p,read_pdf(p),job,folder,work,stage))
        elif target==PDF_CLEAN:
            if p.suffix.lower()!='.pdf': raise ConversionError('Selecione somente arquivos PDF.')
            results.extend(pdf_clean(p,read_pdf(p),job,folder,work,stage))
        elif target in PDF_OCR_TARGETS:
            if p.suffix.lower()!='.pdf': raise ConversionError('Selecione somente arquivos PDF.')
            results.extend(pdf_ocr(p,read_pdf(p),job,folder,work,stage))
        elif target=='Extract PDF Images':
            if p.suffix.lower()!='.pdf': raise ConversionError('Selecione somente arquivos PDF.')
            results.extend(pdf_extract_images(p,job,folder,work))
        elif target in ('PDF → Text','Merge PDFs','Split PDF','Organize PDF'):
            if any(x.suffix.lower()!='.pdf' for x in paths): raise ConversionError('Selecione somente arquivos PDF.')
            from pypdf import PdfWriter
            if target=='Merge PDFs':
                ranges=merge_ranges_from(job,len(paths));writer=PdfWriter();total=0
                for path,text in zip(paths,ranges):
                    pdf=read_pdf(path)
                    try: chosen=pdfinfo.parse_page_range(text,len(pdf.pages))
                    except pdfinfo.PdfError as error: raise ConversionError(f'{path.name}: {error}')
                    total+=len(chosen)
                    if total>200: raise ConversionError('O PDF unido não pode passar de 200 páginas.')
                    try: pdf.outline;outline=True      # marcadores ilegíveis não impedem a união: o arquivo entra só com o marcador do nome
                    except Exception: outline=False
                    writer.append(pdf,outline_item=path.stem[:100] or 'PDF',pages=[n-1 for n in chosen],import_outline=outline)
                with stage.open('wb') as f: writer.write(f)
                results.append(publish(stage,folder,'unido','pdf'))
            else:
                pdf=read_pdf(p)
                if target=='PDF → Text': results.extend(pdf_to_text(p,pdf,job,folder,work,stage,stem))
                elif target=='Organize PDF': results.append(organize_pdf(p,pdf,job,folder,stage))
                else: results.extend(split_pdf(p,pdf,job,folder,work))
    return results

TEXT_MODES=('single','marks','pages')

def text_options_from(job):
    """(modo, layout, páginas) de «PDF → texto»: `text_mode` single/marks/pages, `text_layout` simple/layout, `pdf_pages` (intervalo; vazio = todas)."""
    mode=job.get('text_mode') or 'single'
    if mode not in TEXT_MODES: raise ConversionError('Modo de texto desconhecido.')
    layout=job.get('text_layout') or 'simple'
    if layout not in ('simple','layout'): raise ConversionError('Modo de layout desconhecido.')
    pages=job.get('pdf_pages') or ''
    if not isinstance(pages,str) or len(pages)>200: raise ConversionError('O intervalo de páginas é inválido ou longo demais.')
    return mode,layout,pages

def pdf_to_text(path,pdf,job,folder,work,stage,stem):
    """Extrai o texto (sem OCR). Se nenhuma página escolhida tiver texto, não salva nada e explica o motivo."""
    mode,layout,pages_text=text_options_from(job)
    try: numbers=pdfinfo.parse_page_range(pages_text,len(pdf.pages))
    except pdfinfo.PdfError as error: raise ConversionError(f'{path.name}: {error}')
    chunks=[];total=0
    for number in numbers:
        try: text=pdf.pages[number-1].extract_text(extraction_mode='layout' if layout=='layout' else 'plain') or ''
        except Exception: text=''
        total+=len(text.encode('utf8'))
        if total>MAX_OUTPUT: raise ConversionError('O texto extraído é grande demais.')
        chunks.append((number,text))
    if not any(text.strip() for _n,text in chunks):
        raise ConversionError(f'{path.name}: não há texto nas páginas escolhidas. O PDF parece digitalizado (só imagens) e precisaria de OCR, que o Arquivo Local ainda não faz em PDFs.')
    return write_text_chunks(chunks,mode,path,job,folder,work,stage,'-texto')

def write_text_chunks(chunks,mode,path,job,folder,work,stage,name_suffix):
    """Grava [(página, texto)] como um arquivo (com ou sem marcas de página) ou um arquivo por página na pasta «- texto»."""
    if mode=='pages':
        digits=max(3,len(str(max(number for number,_t in chunks))));items=[]
        for index,(number,text) in enumerate(chunks):
            item=Path(work)/f'text-{index}'
            item.write_text(text.rstrip('\n')+'\n',encoding='utf8')
            items.append((f'pagina-{number:0{digits}d}',item))
        return publish_group(items,'txt',job,folder,path.stem,TEXT_FOLDER_SUFFIX)
    with stage.open('w',encoding='utf8') as handle:
        for number,text in chunks:
            if mode=='marks': handle.write(f'--- Página {number} ---\n')
            handle.write(text);handle.write('\n')
    return [publish(stage,folder,path.stem+name_suffix,'txt')]

def redact_options_from(job,count):
    """({página: [áreas em milésimos]}, termos, padrões, dpi) do job de «Tarjar»; erros em português."""
    areas={}
    raw=job.get('redact_areas') or []
    if not isinstance(raw,list) or len(raw)>pdfredact.MAX_AREAS: raise ConversionError(f'Use no máximo {pdfredact.MAX_AREAS} áreas de tarja.')
    try:
        for item in raw:
            page,box=pdfredact.parse_area(item,count)
            areas.setdefault(page,[]).append(box)
        terms=pdfredact.check_terms(job.get('redact_terms'))
        presets=pdfredact.check_presets(job.get('redact_patterns'))
    except pdfredact.RedactError as error: raise ConversionError(str(error)) from error
    dpi=job.get('pdf_dpi',REDACT_DEFAULT_DPI)
    if dpi is None: dpi=REDACT_DEFAULT_DPI
    try: dpi=pdfinfo.check_dpi(dpi)
    except pdfinfo.PdfError as error: raise ConversionError(str(error)) from error
    if not areas and not terms and not presets: raise ConversionError('Marque ao menos uma área na página ou informe um termo ou padrão para tarjar.')
    return areas,terms,presets,dpi

def pdf_redact(path,pdf,job,folder,work,stage):
    """Tarja segura: páginas com área, termo ou padrão são desenhadas como imagem, as tarjas são pintadas nos pixels e o resultado é conferido (tarjas pretas, sem camada de texto, sem marcadores/anexos/metadados)."""
    import io
    from pypdf import PdfReader,PdfWriter
    from PIL import Image
    count=len(pdf.pages)
    areas,terms,presets,dpi=redact_options_from(job,count)
    compiled=pdfredact.patterns(terms,presets)
    scale=dpi/72
    boxes={}           # página → [(x0,y0,x1,y1) em pixels a `dpi`]
    pieces={}          # página → PDF de uma página já rasterizado
    total=0
    try:
        document=pdfinfo.open_document(path)
        try:
            for number in range(1,count+1):
                page=document[number-1]
                found=[pdfredact.area_to_pixels(area,*pdfinfo.dpi_size(*page.get_size(),dpi)) for area in areas.get(number,[])]
                if compiled:
                    textpage=page.get_textpage()
                    try:
                        text=textpage.get_text_range()
                        if compiled and len(text)!=textpage.count_chars(): raise ConversionError(f'{path.name}: não foi possível localizar o texto da página {number} com segurança; tarje essa página por área.')
                        crop=tuple(float(v) for v in page.get_cropbox()); rotation=page.get_rotation()%360
                        for start,end in pdfredact.find_spans(text,compiled):
                            found.extend(pdfredact.to_pixels(rect,crop,rotation,scale) for rect in pdfredact.char_rects(textpage,start,end))
                    finally: textpage.close()
                if not found: continue
                image=pdfinfo.render_dpi(document,number,dpi)
                try:
                    pdfredact.paint(image,found)
                    width_pt,height_pt=page.get_size()
                    buffer=io.BytesIO()
                    image.save(buffer,'PDF',resolution=image.width*72/width_pt,quality=88)
                finally: image.close()
                pieces[number]=buffer.getvalue(); boxes[number]=found
                total+=len(pieces[number])
                if total>MAX_OUTPUT: raise ConversionError('O PDF tarjado ficaria maior que 512 MiB; use uma resolução menor.')
        finally: document.close()
    except pdfinfo.PdfError as error: raise ConversionError(f'{path.name}: {error}') from error
    if not boxes: raise ConversionError(f'{path.name}: nada foi encontrado para tarjar com os termos e padrões informados e nenhuma área foi marcada nas páginas; nada foi salvo.')
    try:
        writer=PdfWriter()
        keep=[]
        for number in range(1,count+1):
            if number in pieces:
                reader=PdfReader(io.BytesIO(pieces[number]),strict=False); keep.append(reader); writer.add_page(reader.pages[0])
            else: writer.append(pdf,pages=[number-1],import_outline=False)
        writer._info=None
        with stage.open('wb') as handle: writer.write(handle)
    except Exception as error: raise ConversionError(f'{path.name}: não foi possível montar o PDF tarjado ({type(error).__name__}).') from error
    redact_verify(path,stage,count,boxes,dpi,compiled)
    return [publish(stage,folder,path.stem+'-tarjado','pdf')]

def redact_verify(path,stage,count,boxes,dpi,compiled):
    """Confere o PDF tarjado: sem restos do documento original, páginas tarjadas sem texto e com as tarjas realmente pretas, páginas livres sem os termos."""
    from pypdf import PdfReader
    fail=lambda why: ConversionError(f'{path.name}: a conferência da tarja falhou ({why}); nada foi salvo.')
    check=PdfReader(str(stage),strict=False)
    if len(check.pages)!=count: raise fail('número de páginas')
    root=check.trailer['/Root']
    outline=root.get('/Outlines')
    if (outline is not None and '/First' in outline.get_object()) or any(key in root for key in ('/Names','/AcroForm','/Metadata','/OpenAction','/AA')) or '/Info' in check.trailer: raise fail('sobraram marcadores, anexos, formulários ou metadados')
    for number in range(1,count+1):
        text=check.pages[number-1].extract_text() or ''
        if number in boxes:
            if text.strip(): raise fail(f'a página {number} ainda tem texto')
        elif compiled and pdfredact.find_spans(text,compiled): raise fail(f'o texto ainda aparece na página {number}; tarje essa página por área')
    document=pdfinfo.open_document(stage)
    try:
        for number,found in boxes.items():
            image=pdfinfo.render_dpi(document,number,72)
            try:
                gray=image.convert('L'); factor=72/dpi
                for x0,y0,x1,y1 in found:
                    left,top,right,bottom=int(x0*factor)+2,int(y0*factor)+2,int(x1*factor)-2,int(y1*factor)-2
                    if right<=left or bottom<=top: continue
                    region=gray.crop((max(0,left),max(0,top),min(gray.width,right),min(gray.height,bottom)))
                    if region.width>0 and region.height>0 and sum(region.getdata())/(region.width*region.height)>24: raise fail(f'uma tarja da página {number} não ficou preta')
            finally: image.close()
    except pdfinfo.PdfError as error: raise fail(str(error)) from error
    finally: document.close()

def form_sign_image(value):
    """Abre a imagem da assinatura (PNG, JPEG, WebP ou BMP; até 20 MB) já na orientação certa; erros em português."""
    from PIL import Image, ImageOps
    if not isinstance(value,str) or not value.strip(): raise ConversionError('Escolha a imagem da assinatura.')
    image_path=Path(value)
    if image_path.suffix.lower() not in ('.png','.jpg','.jpeg','.webp','.bmp'): raise ConversionError('A assinatura deve ser uma imagem PNG, JPEG, WebP ou BMP.')
    try:
        if not image_path.is_file() or image_path.is_symlink(): raise ConversionError('A imagem da assinatura não foi encontrada.')
        if image_path.stat().st_size>pdfform.MAX_SIGN_BYTES: raise ConversionError('A imagem da assinatura passa de 20 MB.')
        with Image.open(image_path) as source:
            if source.width*source.height>40_000_000: raise ConversionError('A imagem da assinatura é grande demais.')
            return ImageOps.exif_transpose(source).copy()
    except ConversionError: raise
    except Exception as error: raise ConversionError('Não foi possível abrir a imagem da assinatura.') from error

def pdf_form(path,pdf,job,folder,stage):
    """Preenche campos do formulário (AcroForm), opcionalmente achata o resultado e/ou coloca a imagem de assinatura em áreas da página; confere o resultado antes de publicar."""
    from pypdf import PdfReader,PdfWriter
    count=len(pdf.pages)
    fields=pdfform.list_fields(pdf)
    try:
        values=pdfform.parse_values(job.get('form_values'),fields)
        flat=job.get('form_flatten')=='on'
        raw=job.get('sign_areas') or []
        if not isinstance(raw,list) or len(raw)>pdfform.MAX_SIGN_AREAS: raise pdfform.FormError(f'Use no máximo {pdfform.MAX_SIGN_AREAS} áreas de assinatura.')
        areas=[pdfform.parse_sign_area(item,count) for item in raw]
    except pdfform.FormError as error: raise ConversionError(f'{path.name}: {error}') from error
    if flat and not fields: raise ConversionError(f'{path.name}: este PDF não tem campos de formulário para achatar.')
    if not values and not areas and not flat: raise ConversionError('Preencha ao menos um campo, escolha achatar o formulário ou marque onde colocar a assinatura.')
    image=form_sign_image(job.get('sign_image')) if areas else None
    if image is None and job.get('sign_image'): raise ConversionError('Marque a área da página onde a assinatura vai ficar.')
    try:
        writer=PdfWriter(clone_from=pdf)
        acro=writer._root_object.get('/AcroForm')
        if acro is not None: acro.get_object().pop('/XFA',None)
        if values: pdfform.fill(writer,values,fields)
        fixed=pdfform.flatten(writer) if flat else 0
        if areas:
            ref,width,height=pdfform.signature_xobject(writer,image)
            for page,box in areas: pdfform.place_signature(writer,page,box,ref,(width,height))
        with stage.open('wb') as handle: writer.write(handle)
        check=PdfReader(str(stage),strict=False)
        if len(check.pages)!=count: raise ConversionError(f'{path.name}: a conferência do preenchimento falhou (número de páginas); nada foi salvo.')
        root=check.trailer['/Root']
        if flat:
            if '/AcroForm' in root or any(True for _n,_r,_w in pdfform._widgets(check)): raise ConversionError(f'{path.name}: a conferência falhou (sobraram campos); nada foi salvo.')
        else:
            now={f['name']:f for f in pdfform.list_fields(check)}
            for name,value in values.items():
                got=now.get(name,{}).get('value')
                if got!=value and not (value=='' and got in ('',None)): raise ConversionError(f'{path.name}: a conferência falhou (o campo «{name[:40]}» não guardou o valor); nada foi salvo.')
        for page,_box in areas:
            xobjects=check.pages[page-1].get('/Resources',{}).get('/XObject')
            if not xobjects or not any(item.get_object().get('/Subtype')=='/Image' for item in xobjects.get_object().values()): raise ConversionError(f'{path.name}: a conferência falhou (a assinatura não aparece na página {page}); nada foi salvo.')
    except ConversionError: raise
    except (pdfform.FormError,pdfstamp.StampError) as error: raise ConversionError(f'{path.name}: {error}') from error
    except Exception as error: raise ConversionError(f'{path.name}: não foi possível preencher o PDF ({type(error).__name__}).') from error
    finally:
        if image is not None: image.close()
    return [publish(stage,folder,path.stem+'-preenchido','pdf')]

def password_from(value,label):
    """Valida uma senha (≤127 bytes em UTF-8, sem caracteres de controle). A mensagem nunca repete a senha."""
    if value is None: value=''
    if not isinstance(value,str) or len(value.encode('utf8'))>127 or any(ord(char)<32 for char in value): raise ConversionError(f'{label} deve ter no máximo 127 bytes e nenhum caractere de controle.')
    return value

def pdf_protect(path,pdf,job,folder,stage):
    """Protege o PDF com senha de abertura (AES-256) e, se pedido, restrições de uso com senha de permissões diferente. Confere o resultado antes de publicar."""
    from pypdf import PdfReader,PdfWriter
    from pypdf.constants import UserAccessPermissions as Perm
    user=password_from(job.get('pdf_password'),'A senha')
    if len(user)<PASSWORD_MIN: raise ConversionError(f'A senha deve ter pelo menos {PASSWORD_MIN} caracteres.')
    owner=password_from(job.get('pdf_owner_password'),'A senha de permissões')
    flags=Perm.all()
    blocked=False
    for key,bits in (('perm_print',Perm.PRINT|Perm.PRINT_TO_REPRESENTATION),('perm_copy',Perm.EXTRACT|Perm.EXTRACT_TEXT_AND_GRAPHICS),('perm_edit',Perm.MODIFY|Perm.ADD_OR_MODIFY|Perm.FILL_FORM_FIELDS|Perm.ASSEMBLE_DOC)):
        raw=job.get(key) or 'on'
        if raw not in ('on','off'): raise ConversionError('Opção de permissão inválida.')
        if raw=='off': flags&=~bits; blocked=True
    if blocked and (len(owner)<PASSWORD_MIN or owner==user): raise ConversionError(f'Para bloquear impressão, cópia ou edição defina uma senha de permissões (mínimo {PASSWORD_MIN} caracteres) diferente da senha de abertura; sem isso qualquer pessoa desfaz a restrição.')
    if owner and not blocked and len(owner)<PASSWORD_MIN: raise ConversionError(f'A senha de permissões deve ter pelo menos {PASSWORD_MIN} caracteres.')
    try:
        writer=PdfWriter(clone_from=pdf)
        writer.encrypt(user,owner or None,algorithm='AES-256',permissions_flag=flags)
        with stage.open('wb') as handle: writer.write(handle)
        raw=stage.read_bytes()
        check=PdfReader(str(stage),strict=False)
        if b'/AESV3' not in raw or not check.is_encrypted or check.decrypt(user)==0 or len(check.pages)!=len(pdf.pages): raise ConversionError(f'{path.name}: a conferência da proteção falhou; nada foi salvo.')
        if PdfReader(str(stage),strict=False).decrypt('')!=0: raise ConversionError(f'{path.name}: a conferência da proteção falhou (abre sem senha); nada foi salvo.')
    except ConversionError: raise
    except Exception as error: raise ConversionError(f'{path.name}: não foi possível proteger o PDF ({type(error).__name__}). Para AES-256 é preciso o pacote «cryptography».') from error
    return [publish(stage,folder,path.stem+'-protegido','pdf')]

def pdf_unprotect(path,job,folder,stage):
    """Grava uma cópia sem senha de um PDF protegido, usando a senha informada (uma tentativa). Restrições de uso só saem com a senha de proprietário."""
    from pypdf import PdfReader,PdfWriter
    password=password_from(job.get('pdf_password'),'A senha')
    try: reader,kind=pdfinfo.open_protected(path,password)
    except pdfinfo.PdfError as error: raise ConversionError(f'{path.name}: {error}') from error
    if kind==0: raise ConversionError(f'{path.name}: este PDF não tem senha; não há o que remover.')
    if pdfinfo.has_restrictions(reader) and kind!=2: raise ConversionError(f'{path.name}: este PDF tem restrições de uso (imprimir, copiar ou editar). Para remover a proteção é preciso informar a senha de permissões (proprietário); a senha de abertura não basta. Nada foi salvo.')
    try:
        writer=PdfWriter(clone_from=reader)
        with stage.open('wb') as handle: writer.write(handle)
        check=PdfReader(str(stage),strict=False)
        if check.is_encrypted or len(check.pages)!=len(reader.pages): raise ConversionError(f'{path.name}: a conferência da cópia sem senha falhou; nada foi salvo.')
    except ConversionError: raise
    except Exception as error: raise ConversionError(f'{path.name}: não foi possível gravar a cópia sem senha ({type(error).__name__}).') from error
    return [publish(stage,folder,path.stem+'-desprotegido','pdf')]

def stamp_options_from(job):
    """Opções do carimbo com padrões por tipo (texto: rodapé central, preto; marca d'água: diagonal no centro, cinza e transparente)."""
    kind=job.get('stamp_kind') or 'text'
    if kind not in STAMP_KINDS: raise ConversionError('Tipo de carimbo inválido.')
    water=kind=='watermark'
    text=job.get('stamp_text')
    if text is None: text='' if water else 'Página {n} de {total}'
    if not isinstance(text,str) or not text.strip() or len(text)>100 or any(ord(char)<32 for char in text): raise ConversionError('O texto do carimbo deve ter de 1 a 100 caracteres imprimíveis.')
    try: pdfstamp.encode(text)
    except pdfstamp.StampError as error: raise ConversionError(str(error)) from error
    position=job.get('stamp_position') or ('c' if water else 'bc')
    if position not in pdfstamp.POSITIONS: raise ConversionError('Posição do carimbo inválida.')
    def number(key,default,low,high,label):
        value=job.get(key,default)
        if type(value) is not int or not low<=value<=high: raise ConversionError(f'{label} deve ficar entre {low} e {high}.')
        return value
    size=number('stamp_size',70 if water else 10,10 if water else 6,100 if water else 72,'O tamanho do carimbo')
    opacity=number('stamp_opacity',25 if water else 100,5,100,'A opacidade do carimbo')
    margin=number('stamp_margin',10,0,50,'A margem do carimbo')
    angle=number('stamp_angle',45 if water else 0,0,45,'O ângulo do carimbo')
    if angle not in (0,45): raise ConversionError('O ângulo do carimbo deve ser 0 ou 45.')
    if angle and (not water or position!='c'): raise ConversionError('O texto na diagonal só existe na marca d\'água, no centro da página.')
    start=number('stamp_start',1,1,9999,'O primeiro número')
    color=job.get('stamp_color') or ('#808080' if water else '#000000')
    if not isinstance(color,str) or not re.fullmatch(r'#[0-9A-Fa-f]{6}',color): raise ConversionError('A cor do carimbo deve estar no formato #RRGGBB.')
    bold_raw=job.get('stamp_bold') or 'off'
    if bold_raw not in ('on','off'): raise ConversionError('Opção de negrito inválida.')
    return {'kind':kind,'text':text,'position':position,'size':size,'opacity':opacity,'margin':margin,'angle':angle,'start':start,'color':color,'bold':bold_raw=='on'}

def pdf_stamp(path,pdf,job,folder,stage):
    """Escreve numeração, texto de cabeçalho/rodapé ou marca d'água nas páginas escolhidas (`pdf_pages`); o resto do PDF fica como estava."""
    from pypdf import PdfReader,PdfWriter
    opts=stamp_options_from(job)
    count=len(pdf.pages)
    try: numbers=pdfinfo.parse_page_range(job.get('pdf_pages') or '',count)
    except pdfinfo.PdfError as error: raise ConversionError(f'{path.name}: {error}')
    water=opts['kind']=='watermark'
    total=count+opts['start']-1
    try:
        writer=PdfWriter(clone_from=pdf)
        expected={}
        for n in numbers:
            page=writer.pages[n-1]
            label=pdfstamp.expand(opts['text'],n+opts['start']-1,total)
            content=pdfstamp.stamp_content(pdfstamp.visible_geometry(page),label,position=opts['position'],size=opts['size'],bold=opts['bold'],color=opts['color'],opacity=opts['opacity'],
                                           margin_mm=opts['margin'],angle=opts['angle'],fit_percent=opts['size'] if water else 0)
            page.merge_page(pdfstamp.overlay_page(page,content,opts['bold'],opts['opacity']))
            expected[n]=label
        with stage.open('wb') as handle: writer.write(handle)
        check=PdfReader(str(stage),strict=False)
        if len(check.pages)!=count: raise ConversionError(f'{path.name}: a conferência do carimbo falhou (número de páginas); nada foi salvo.')
        first=numbers[0]
        try: found=check.pages[first-1].extract_text() or ''
        except Exception: found=None
        if found is not None and re.sub(r'\s+','',expected[first]) not in re.sub(r'\s+','',found): raise ConversionError(f'{path.name}: a conferência do carimbo falhou (texto não encontrado na página {first}); nada foi salvo.')
    except ConversionError: raise
    except pdfstamp.StampError as error: raise ConversionError(str(error)) from error
    except Exception as error: raise ConversionError(f'{path.name}: não foi possível aplicar o carimbo ({type(error).__name__}).') from error
    suffix='-marcadagua' if water else ('-numerado' if '{n}' in opts['text'] else '-carimbado')
    return [publish(stage,folder,path.stem+suffix,'pdf')]

def pdf_compress(path,pdf,job,folder,work,stage):
    """Comprime o PDF pelo nível `pdf_level` (light/medium/strong). Nunca aumenta: se não economizar ao menos 1 %, nada é salvo. Duas passadas (clonar de novo descarta objetos órfãos)."""
    import io
    from pypdf import PdfReader,PdfWriter
    level=job.get('pdf_level') or pdfcompress.DEFAULT_LEVEL
    if level not in pdfcompress.LEVELS: raise ConversionError('Nível de compressão inválido.')
    original=path.stat().st_size
    try:
        first=PdfWriter(clone_from=pdf)
        stats=pdfcompress.compress(first,level)
        buffer=io.BytesIO(); first.write(buffer)
        second=PdfWriter(clone_from=PdfReader(io.BytesIO(buffer.getvalue()),strict=False))
        buffer.close()
        with stage.open('wb') as handle: second.write(handle)
        check=PdfReader(str(stage),strict=False)
        if len(check.pages)!=len(pdf.pages): raise ConversionError(f'{path.name}: a conferência da compressão falhou (número de páginas); nada foi salvo.')
    except ConversionError: raise
    except Exception as error: raise ConversionError(f'{path.name}: não foi possível comprimir o PDF ({type(error).__name__}).') from error
    final=stage.stat().st_size
    if final>original*0.99:
        raise ConversionError(f'{path.name}: a compressão neste nível não reduziu o arquivo (pelo menos 1 %); nada foi salvo.'+(' Tente um nível mais forte.' if level!='strong' else ' O PDF já está compacto ou só tem imagens que não podem ser recomprimidas.'))
    return [publish(stage,folder,path.stem+'-comprimido','pdf')]

def clean_options_from(job):
    """{'info','attach','js'} → bool a partir de `meta_info/meta_attach/meta_js` ('on' é o padrão)."""
    values={}
    for name,key in (('info','meta_info'),('attach','meta_attach'),('js','meta_js')):
        raw=job.get(key) or 'on'
        if raw not in ('on','off'): raise ConversionError('Opção de limpeza do PDF inválida.')
        values[name]=raw=='on'
    if not any(values.values()): raise ConversionError('Marque ao menos uma coisa para remover.')
    return values

def pdf_clean(path,pdf,job,folder,work,stage):
    """Cópia limpa: remove metadados, anexos e/ou JavaScript e confere o resultado. Precisa de duas passadas: a primeira apaga as referências, a segunda reescreve só o que ainda é alcançável (sem restos dos dados removidos no arquivo)."""
    import io
    from pypdf import PdfReader,PdfWriter
    want=clean_options_from(job)
    found=pdfinfo.clean_scan(pdf)
    todo={name:want[name] and found[name] for name in want}
    if not any(todo.values()):
        raise ConversionError(f'{path.name}: não há nada do que você marcou para remover; o PDF já está limpo nesses pontos. Nada foi salvo.')
    try:
        first=PdfWriter(clone_from=pdf)
        pdfinfo.clean_apply(first,info=todo['info'],attach=todo['attach'],js=todo['js'])
        if todo['info']: first._info=None
        buffer=io.BytesIO(); first.write(buffer)
        second=PdfWriter(clone_from=PdfReader(io.BytesIO(buffer.getvalue()),strict=False))
        if todo['info']: second._info=None
        with stage.open('wb') as handle: second.write(handle)
        buffer.close()
        check=PdfReader(str(stage),strict=False)
        again=pdfinfo.clean_scan(check)
        problems=[name for name in want if want[name] and again[name]]
        if problems or len(check.pages)!=len(pdf.pages): raise ConversionError(f'{path.name}: a conferência da cópia limpa falhou ({", ".join(problems) or "páginas"}); nada foi salvo.')
    except ConversionError: raise
    except Exception as error: raise ConversionError(f'{path.name}: não foi possível gerar a cópia limpa ({type(error).__name__}).') from error
    return [publish(stage,folder,path.stem+'-limpo','pdf')]

def page_has_text(page):
    try: return len((page.extract_text() or '').strip())>=20
    except Exception: return False

def pdf_ocr(path,pdf,job,folder,work,stage):
    """OCR de PDF digitalizado: desenha cada página escolhida a 300 dpi e reconhece com o Tesseract. Saída: PDF pesquisável (imagem + texto invisível) ou texto.
    Páginas que já têm texto são puladas (opção `ocr_skip`, padrão ligada). O limite de páginas vale para as que realmente passam pelo OCR."""
    from PIL import Image
    from pypdf import PdfReader,PdfWriter
    want_pdf=job.get('target')==PDF_OCR_PDF
    lang,psm=ocr_options_from(job)
    skip_option=job.get('ocr_skip') or 'on'
    if skip_option not in ('on','off'): raise ConversionError('Opção de páginas com texto inválida.')
    skip=skip_option=='on'
    mode,_layout,pages_text=text_options_from({**job,'text_mode':job.get('text_mode') or 'single'})
    try: ocr.check_ready(lang)
    except ocr.OcrError as error: raise ConversionError(str(error)) from error
    try: numbers=pdfinfo.parse_page_range(pages_text,len(pdf.pages))
    except pdfinfo.PdfError as error: raise ConversionError(f'{path.name}: {error}')
    has={n:(skip and page_has_text(pdf.pages[n-1])) for n in numbers}
    need=[n for n in numbers if not has[n]]
    if not need: raise ConversionError(f'{path.name}: todas as páginas escolhidas já têm texto, então não há o que reconhecer. Desligue «Pular páginas que já têm texto» para reconhecer mesmo assim.')
    if len(need)>PDF_OCR_MAX_PAGES: raise ConversionError(f'{len(need)} páginas precisam de OCR; o limite é {PDF_OCR_MAX_PAGES} por vez (cada página leva alguns segundos). Escolha um intervalo menor, por exemplo 1-{PDF_OCR_MAX_PAGES}.')
    parts={};texts={};blank=0;total=0
    try:
        document=pdfinfo.open_document(path)
        try:
            for n in need:
                image=pdfinfo.render_dpi(document,n,ocr.DPI)
                prepared=ocr_prepare(image,'pdf' if want_pdf else 'txt')
                source=Path(work)/(f'ocr-source-{n}.'+('jpg' if want_pdf else 'png'))
                try:
                    if want_pdf: prepared.convert('RGB').save(source,format='JPEG',quality=85,dpi=(ocr.DPI,ocr.DPI))
                    else: prepared.save(source,format='PNG',dpi=(ocr.DPI,ocr.DPI))
                finally: prepared.close()
                try: produced=ocr.recognize(source,lang,psm,'pdf' if want_pdf else 'txt',work,base=f'ocr-out-{n}')
                except ocr.OcrError as error: raise ConversionError(f'Página {n}: {error}') from error
                finally: source.unlink(missing_ok=True)
                if want_pdf:
                    total+=produced.stat().st_size
                    if total>MAX_OUTPUT: raise ConversionError('O PDF ficaria maior que 512 MiB; escolha menos páginas.')
                    parts[n]=produced
                    try:
                        found=''.join((pg.extract_text() or '') for pg in PdfReader(str(produced),strict=False).pages).strip()
                    except Exception as error: raise ConversionError(f'Página {n}: o PDF gerado pelo OCR não pôde ser verificado.') from error
                    if not found: blank+=1
                else:
                    try: text=ocr.read_text(produced)
                    except ocr.OcrError as error: raise ConversionError(str(error)) from error
                    texts[n]=text
                    if not text.strip(): blank+=1
        finally: document.close()
    except pdfinfo.PdfError as error: raise ConversionError(str(error))
    if blank==len(need): raise ConversionError('Nenhum texto foi reconhecido nas páginas. Tente outro idioma, outro modo de página ou um PDF mais nítido; nada foi salvo.')
    if want_pdf:
        writer=PdfWriter();keep=[]
        for n in numbers:
            if n in parts:
                reader=PdfReader(str(parts[n]),strict=False);keep.append(reader);writer.add_page(reader.pages[0])
            else: writer.append(pdf,pages=[n-1],import_outline=False)
        with stage.open('wb') as handle: writer.write(handle)
        return [publish(stage,folder,path.stem+'-pesquisavel','pdf')]
    chunks=[(n,texts[n] if n in texts else (pdf.pages[n-1].extract_text() or '')) for n in numbers]
    return write_text_chunks(chunks,mode,path,job,folder,work,stage,'-ocr')

IMAGE_EXTRACT_MAX=500

def pdf_extract_images(path,job,folder,work):
    """Copia as imagens embutidas nas páginas escolhidas (JPEG e JPEG 2000 sem recomprimir; o resto vira PNG). A mesma imagem em várias páginas sai uma vez."""
    import hashlib
    import pypdfium2.raw as pdfium_raw
    minimum=job.get('img_min',32)
    if minimum is None: minimum=32
    if type(minimum) is not int or not 0<=minimum<=2000: raise ConversionError('O tamanho mínimo das imagens deve ficar entre 0 e 2000 px.')
    pages_text=job.get('pdf_pages') or ''
    if not isinstance(pages_text,str) or len(pages_text)>200: raise ConversionError('O intervalo de páginas é inválido ou longo demais.')
    ready=[];seen=set();total=0
    try:
        document=pdfinfo.open_document(path)
        try:
            numbers=pdfinfo.parse_page_range(pages_text,len(document))
            for number in numbers:
                page=document[number-1]
                try:
                    objects=list(page.get_objects(filter=[pdfium_raw.FPDF_PAGEOBJ_IMAGE]))
                    for index,obj in enumerate(objects,1):
                        try:
                            width,height=obj.get_px_size()
                            if max(width,height)<minimum: continue
                            if width*height>MAX_PIXELS: raise ConversionError(f'A imagem {index} da página {number} tem {width} × {height} px ({width*height/1e6:.0f} megapixels), acima do limite de 40 megapixels.')
                            prefix=Path(work)/f'img-{len(ready)}'
                            try: obj.extract(str(prefix),fb_format='png')
                            except ConversionError: raise
                            except Exception: continue          # imagem que o PDFium não consegue decodificar: pula
                            produced=sorted(Path(work).glob(prefix.name+'.*'))
                            if not produced: continue
                            item=produced[0];digest=hashlib.sha256(item.read_bytes()).hexdigest()
                            if digest in seen: item.unlink();continue
                            seen.add(digest)
                            total+=item.stat().st_size
                            if total>MAX_OUTPUT: raise ConversionError('As imagens extraídas passam de 512 MiB.')
                            ready.append((f'pagina-{number:03d}-imagem-{index}',item))
                            if len(ready)>IMAGE_EXTRACT_MAX: raise ConversionError(f'O PDF tem mais de {IMAGE_EXTRACT_MAX} imagens nas páginas escolhidas; escolha menos páginas ou aumente o tamanho mínimo.')
                        finally: obj.close()
                finally: page.close()
        finally: document.close()
    except pdfinfo.PdfError as error: raise ConversionError(str(error))
    if not ready: raise ConversionError(f'{path.name}: nenhuma imagem encontrada nas páginas escolhidas'+(f' com pelo menos {minimum} px' if minimum else '')+'. Páginas digitalizadas guardam a página inteira como uma imagem; use «PDF → imagens» para desenhar as páginas.')
    ext_of=lambda item:item.suffix.lstrip('.').lower()
    if job.get('_work_root'): return [publish(item,folder,name,ext_of(item)) for name,item in ready]      # dentro do runner: soltas na pasta privada; o runner as leva para «- imagens»
    target_folder=create_pages_folder(folder,path.stem,IMAGES_FOLDER_SUFFIX);results=[]
    try:
        for name,item in ready: results.append(publish(item,target_folder,name,ext_of(item)))
    except BaseException:
        for done in results:
            try: Path(done).unlink()
            except OSError: pass
        try: target_folder.rmdir()
        except OSError: pass
        raise
    return results

ORGANIZE_ENTRY=re.compile(r'(\d{1,3}):(0|90|180|270)')

def organize_plan_from(job,count):
    """Lista de (página a partir de 1, giro em graus) do PDF novo, na ordem final; as páginas excluídas simplesmente não aparecem."""
    raw=job.get('organize_pages')
    if not isinstance(raw,list) or not 1<=len(raw)<=200: raise ConversionError('Deixe de 1 a 200 páginas no PDF organizado.')
    plan=[]
    for item in raw:
        match=ORGANIZE_ENTRY.fullmatch(item) if isinstance(item,str) else None
        if not match: raise ConversionError('A lista de páginas é inválida.')
        page,rotation=int(match.group(1)),int(match.group(2))
        if not 1<=page<=count: raise ConversionError(f'O PDF tem {count} {"página" if count==1 else "páginas"}; a página {page} não existe.')
        plan.append((page,rotation))
    return plan

def organize_pdf(path,pdf,job,folder,stage):
    from pypdf import PdfWriter
    plan=organize_plan_from(job,len(pdf.pages))
    writer=PdfWriter()
    for page,rotation in plan:
        writer.append(pdf,pages=[page-1],import_outline=False)      # `append` copia a página (a mesma página pode entrar mais de uma vez)
        if rotation: writer.pages[-1].rotate(rotation)
    with stage.open('wb') as handle: writer.write(handle)
    return publish(stage,folder,path.stem+'-organizado','pdf')

SPLIT_MODES=('each','every','ranges','extract')

def split_options_from(job):
    """(modo, N, texto dos intervalos) de «Separar/Extrair páginas»; erros em português."""
    mode=job.get('split_mode') or 'each'
    if mode not in SPLIT_MODES: raise ConversionError('Modo de divisão desconhecido.')
    every=job.get('split_every',1)
    if every is None: every=1
    if type(every) is not int or not 1<=every<=200: raise ConversionError('O número de páginas por parte deve ficar entre 1 e 200.')
    text=job.get('split_ranges') or ''
    if not isinstance(text,str) or len(text)>200: raise ConversionError('O intervalo de páginas é inválido ou longo demais.')
    return mode,every,text

def split_groups(mode,every,text,count):
    """Páginas (a partir de 1) de cada PDF de saída."""
    try:
        if mode=='each': return [[n] for n in range(1,count+1)]
        if mode=='every': return [list(range(a,min(a+every,count+1))) for a in range(1,count+1,every)]
        if mode=='ranges': return pdfinfo.parse_page_groups(text,count)
        pages=pdfinfo.parse_page_range(text,count)
        if not text.strip(): raise pdfinfo.PdfError('Escreva as páginas que devem ser extraídas, por exemplo 1-3,7.')
        return [pages]
    except pdfinfo.PdfError as error: raise ConversionError(str(error))

def output_group_suffix(job):
    """Sufixo da pasta dedicada quando o job gera vários arquivos de uma vez (None = arquivos soltos ao lado do original)."""
    if job.get('target')==tool_registry.PDF_IMAGES: return PDF_IMAGES_FOLDER_SUFFIX
    if job.get('target')=='Extract PDF Images': return IMAGES_FOLDER_SUFFIX
    if job.get('target') in ('PDF → Text',PDF_OCR_TEXT) and job.get('text_mode')=='pages': return TEXT_FOLDER_SUFFIX
    if job.get('target')=='Split PDF' and (job.get('split_mode') or 'each')!='extract': return SPLIT_FOLDER_SUFFIX
    return None

def split_pdf(path,pdf,job,folder,work):
    """Divide ou extrai páginas. Todas as partes são escritas antes de qualquer publicação; várias partes vão para a pasta «<nome> - partes»."""
    from pypdf import PdfWriter
    mode,every,text=split_options_from(job)
    count=len(pdf.pages)
    groups=split_groups(mode,every,text,count)
    try: pdf.outline;outline=True
    except Exception: outline=False
    digits=max(3,len(str(count if mode!='ranges' else len(groups))))
    pieces=[];total=0
    for index,group in enumerate(groups):
        writer=PdfWriter();writer.append(pdf,pages=[n-1 for n in group],import_outline=outline)
        item=Path(work)/f'part-{index}'
        with item.open('wb') as handle: writer.write(handle)
        total+=item.stat().st_size
        if total>MAX_OUTPUT: raise ConversionError('As saídas da divisão passam de 512 MiB.')
        name=f'pagina-{group[0]:0{digits}d}' if mode=='each' else f'parte-{index+1:0{digits}d}'
        pieces.append((name,item))
    if mode=='extract': return [publish(pieces[0][1],folder,path.stem+'-extraido','pdf')]
    return publish_group(pieces,'pdf',job,folder,path.stem,SPLIT_FOLDER_SUFFIX)

def publish_group(items,ext,job,folder,stem,suffix):
    """Publica (nome, arquivo de preparo) numa pasta dedicada. Dentro do runner os arquivos ficam soltos na pasta privada do job e o runner os leva para a pasta; fora dele a pasta é criada aqui e desfeita se algo falhar."""
    if job.get('_work_root'): return [publish(item,folder,name,ext) for name,item in items]
    target_folder=create_pages_folder(folder,stem,suffix);results=[]
    try:
        for name,item in items: results.append(publish(item,target_folder,name,ext))
    except BaseException:
        for done in results:
            try: Path(done).unlink()
            except OSError: pass
        try: target_folder.rmdir()
        except OSError: pass
        raise
    return results

def merge_ranges_from(job,count):
    """Um texto de intervalo por arquivo de «Unir PDFs» (vazio = todas as páginas); sem a opção, todas."""
    raw=job.get('merge_ranges')
    if raw is None: return ['']*count
    if not isinstance(raw,list) or len(raw)!=count or any(not isinstance(x,str) or len(x)>200 for x in raw):
        raise ConversionError('Os intervalos de páginas não combinam com a lista de arquivos.')
    return raw

PDF_IMAGES_FOLDER_SUFFIX=' - páginas'
SPLIT_FOLDER_SUFFIX=' - partes'
TEXT_FOLDER_SUFFIX=' - texto'
IMAGES_FOLDER_SUFFIX=' - imagens'

def pdf_images_options_from(job):
    """(dpi, texto das páginas) do job de «PDF → imagens»; erros em português."""
    dpi=job.get('pdf_dpi',pdfinfo.DPI_DEFAULT)
    if dpi is None: dpi=pdfinfo.DPI_DEFAULT
    pages=job.get('pdf_pages','')
    if pages is None: pages=''
    if not isinstance(pages,str) or len(pages)>200: raise ConversionError('O intervalo de páginas é inválido ou longo demais.')
    try: return pdfinfo.check_dpi(dpi),pages
    except pdfinfo.PdfError as error: raise ConversionError(str(error))

def create_pages_folder(parent,stem,suffix=None):
    """Cria (sem reaproveitar) a pasta «<nome> - páginas[ (2)]» (ou com o sufixo dado) dentro de `parent`."""
    suffix=suffix or PDF_IMAGES_FOLDER_SUFFIX
    base=re.sub(r'[<>:"/\\|?*\x00-\x1f]','_',stem).rstrip('. ')[:80] or 'pdf'
    for n in range(1,1000):
        folder=Path(parent)/(base+suffix+('' if n==1 else f' ({n})'))
        try: folder.mkdir()
        except FileExistsError: continue
        except OSError as error: raise ConversionError('Não foi possível criar a pasta das páginas. Verifique as permissões e o espaço livre.') from error
        return folder
    raise ConversionError('Não foi possível escolher um nome livre para a pasta das páginas.')

def pdf_to_images(path,job,folder,work):
    """Desenha as páginas escolhidas do PDF, uma de cada vez, e as publica numeradas («pagina-001») numa pasta nova ao lado do PDF.
    Nada é publicado antes de todas as páginas estarem prontas; se falhar na publicação, a pasta criada é desfeita."""
    out_key,out_quality,out_flatten=output_options_from(job,tool_registry.PDF_IMAGES)
    if out_key=='ico': raise ConversionError('ICO não serve para páginas de PDF; escolha PNG, JPEG, WebP, TIFF ou outro formato.')
    dpi,pages_text=pdf_images_options_from(job)
    try:
        document=pdfinfo.open_document(path)
        try:
            count=len(document)
            pages=pdfinfo.parse_page_range(pages_text,count)
            for number in pages:      # confere todos os tamanhos antes de desenhar qualquer página
                page=document[number-1]
                try: width,height=page.get_size()
                finally: page.close()
                pdfinfo.page_pixels_ok(number,width,height,dpi)
            ready=[];total=0;digits=max(3,len(str(max(pages))))
            for index,number in enumerate(pages):
                image=pdfinfo.render_dpi(document,number,dpi)
                try:
                    image=finalize_for_format(image,out_key,out_flatten)
                    item=Path(work)/f'page-{index}'
                    image.save(item,format=OUTPUT_FORMATS[out_key][0],**format_save_options(out_key,out_quality,image.info.get('transparency') if out_key=='gif' else None,image.width))
                finally: image.close()
                total+=item.stat().st_size
                if total>MAX_OUTPUT: raise ConversionError('As imagens das páginas passam de 512 MiB; use uma resolução menor ou menos páginas.')
                ready.append((number,item))
        finally: document.close()
    except pdfinfo.PdfError as error: raise ConversionError(str(error))
    return publish_group([(f'pagina-{number:0{digits}d}',item) for number,item in ready],OUTPUT_FORMATS[out_key][1],job,folder,path.stem,PDF_IMAGES_FOLDER_SUFFIX)      # dentro do runner as páginas ficam soltas e o runner as leva para a pasta «- páginas»

def worker_main():
    import sys
    try:
        if sys.platform.startswith('linux'):
            import resource
            resource.setrlimit(resource.RLIMIT_AS,(1536*1024*1024,1536*1024*1024))
            resource.setrlimit(resource.RLIMIT_FSIZE,(MAX_OUTPUT,MAX_OUTPUT))
            resource.setrlimit(resource.RLIMIT_CPU,(160,160))
        raw=sys.stdin.buffer.read(65537)
        if len(raw)>65536: raise ConversionError('Pedido do job grande demais.')
        job=json.loads(raw)
        if isinstance(job,dict) and str(job.get('op','')).startswith('audio_'):
            import mediatools
            result={'ok':True,'outputs':mediatools.run_op(job,lambda raw: source_file(raw,AUDIO_MAX_BYTES))}       # leitura de áudio para a interface (informações), sem gerar arquivo
        elif isinstance(job,dict) and job.get('op'): result={'ok':True,'outputs':pdfinfo.run_op(job,source_file)}       # leitura de PDF para a interface (informações e prévia), sem gerar arquivo do usuário
        else: result={'ok':True,'outputs':convert(job)}
    except Exception as e: result={'ok':False,'error':str(e)[:1000] or type(e).__name__}
    print(json.dumps(result,ensure_ascii=True),flush=True)
    return 0 if result['ok'] else 1
