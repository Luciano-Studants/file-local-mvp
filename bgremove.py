"""Remoção de fundo (segmentação do objeto principal) com redes U²-Net executadas offline pelo ONNX Runtime.

Núcleo puro (sem Qt, sem importar o motor): erros `BgError`; o motor os converte em `ConversionError`.
Funcionamento: a imagem é reduzida a 320×320, a rede U²-Net devolve um mapa de «quanto cada ponto pertence ao objeto principal», o mapa é
ampliado ao tamanho original e vira o canal alfa (transparência) do PNG. Nada é enviado à internet e nenhum modelo é baixado: os arquivos
`.onnx` acompanham o aplicativo (`models/`) ou são colocados ali pelo usuário.

Segurança: um arquivo `.onnx` é interpretado por código nativo; por isso só são aceitos os modelos da lista `MODELS`, conferidos pelo SHA-256 do
conteúdo **antes** de carregar (arquivo trocado ou adulterado é recusado). O trabalho roda no worker (processo separado, com limites de memória e CPU).

Limites conhecidos: é segmentação de objeto de destaque, não recorte profissional — cabelos finos, vidro, sombras, objetos muito parecidos com o fundo
e imagens com vários objetos podem sair errados; o resultado deve ser conferido. Só `u2netp` (leve, ~4,6 MB) acompanha o pacote; `u2net` (~176 MB,
mais preciso) é opcional. O modelo `isnet-general-use` NÃO é usado: foi treinado com o conjunto DIS5K, cujos termos permitem só uso não comercial.
"""
from __future__ import annotations

import hashlib
import importlib.util
import sys
from pathlib import Path

# id → (arquivo, SHA-256 do conteúdo, tamanho em bytes, rótulo curto, incluído no pacote). Origem: release v0.0.0 do rembg (pesos oficiais do U²-Net, Apache-2.0).
MODELS = {
    'u2netp': ('u2netp.onnx', '309c8469258dda742793dce0ebea8e6dd393174f89934733ecc8b14c76f4ddd8', 4574861, 'Leve (u2netp)', True),
    'u2net': ('u2net.onnx', '8d10d2f3bb75ae3b6d527c77944fc5e7dcd94b29809d47a739a7a728a912b491', 175997641, 'Preciso (u2net)', False),
}
DEFAULT_MODEL = 'u2netp'
INPUT_SIDE = 320                               # lado de entrada das redes U²-Net
MEAN = (0.485, 0.456, 0.406)
STD = (0.229, 0.224, 0.225)
MAX_FEATHER = 10                               # raio máximo (px) da suavização da borda
DEFAULT_FEATHER = 2
MAX_MODEL_BYTES = 300 * 1024 * 1024
_sessions: dict = {}


class BgError(ValueError):
    pass


def app_dirs():
    """Pastas onde procurar `models/`: ao lado deste módulo e, em pacote do PyInstaller, no diretório de dados/executável."""
    dirs = [Path(__file__).resolve().parent]
    for raw in (getattr(sys, '_MEIPASS', None), Path(sys.executable).parent if getattr(sys, 'frozen', False) else None):
        if raw and Path(raw).resolve() not in dirs:
            dirs.append(Path(raw).resolve())
    return dirs


def model_path(model):
    """Caminho do arquivo do modelo, ou None se não estiver instalado. Não confere o conteúdo (isso é feito ao carregar)."""
    if model not in MODELS:
        return None
    for base in app_dirs():
        path = base / 'models' / MODELS[model][0]
        if path.is_file():
            return path
    return None


def installed_models():
    """Ids dos modelos encontrados, na ordem de `MODELS`."""
    return [key for key in MODELS if model_path(key)]


def libraries_ready():
    return all(importlib.util.find_spec(name) is not None for name in ('numpy', 'onnxruntime'))


def status(model=DEFAULT_MODEL):
    """(pronto, mensagem em português): usado pelo painel e pelo motor."""
    if not libraries_ready():
        return False, 'A remoção de fundo precisa dos pacotes numpy e onnxruntime («pip install -r requirements.txt»).'
    if model not in MODELS:
        return False, 'Modelo de remoção de fundo desconhecido.'
    if not model_path(model):
        name = MODELS[model][0]
        return False, (f'O modelo «{MODELS[model][3]}» não foi encontrado. Coloque o arquivo {name} (conferido por SHA-256, SHA-256 em SOURCES.md) '
                       'na pasta «models» ao lado do aplicativo; nada é baixado pela internet.')
    return True, ''


def _read_verified(model):
    path = model_path(model)
    if path is None:
        raise BgError(status(model)[1])
    _name, digest, size, _label, _bundled = MODELS[model]
    try:
        actual_size = path.stat().st_size
        if actual_size != size or actual_size > MAX_MODEL_BYTES:
            raise BgError(f'O arquivo {path.name} não é o modelo esperado (tamanho diferente); ele não foi carregado.')
        data = path.read_bytes()
    except OSError as error:
        raise BgError(f'Não foi possível ler o modelo {path.name}.') from error
    if hashlib.sha256(data).hexdigest() != digest:
        raise BgError(f'O arquivo {path.name} não confere com o modelo esperado (SHA-256 diferente); ele não foi carregado.')
    return data


def _session(model):
    """Sessão do ONNX Runtime já criada para o modelo (uma por processo)."""
    if not libraries_ready():
        raise BgError(status(model)[1])
    if model in _sessions:
        return _sessions[model]
    data = _read_verified(model)
    import onnxruntime
    options = onnxruntime.SessionOptions()
    options.intra_op_num_threads = 1                # tempo previsível e menos memória
    options.inter_op_num_threads = 1
    options.enable_cpu_mem_arena = False
    options.enable_mem_pattern = False
    options.log_severity_level = 3
    try:
        session = onnxruntime.InferenceSession(data, options, providers=['CPUExecutionProvider'])
    except Exception as error:
        raise BgError('Não foi possível carregar o modelo de remoção de fundo (memória insuficiente ou arquivo incompatível).') from error
    finally:
        del data
    shape = session.get_inputs()[0].shape
    if len(shape) != 4 or shape[1] != 3:
        raise BgError('O modelo carregado não tem o formato de entrada esperado.')
    _sessions[model] = session
    return session


def reset_sessions():
    _sessions.clear()


def predict_mask(image, model=DEFAULT_MODEL):
    """Mapa de objeto principal (imagem 'L' no tamanho de `image`, 0 = fundo, 255 = objeto)."""
    import numpy
    from PIL import Image
    session = _session(model)
    rgb = image.convert('RGB')
    try:
        small = rgb.resize((INPUT_SIDE, INPUT_SIDE), Image.Resampling.LANCZOS)
    finally:
        rgb.close()
    try:
        array = numpy.asarray(small, dtype=numpy.float32)
    finally:
        small.close()
    array = array / max(float(array.max()), 1e-6)
    array = (array - numpy.array(MEAN, dtype=numpy.float32)) / numpy.array(STD, dtype=numpy.float32)
    tensor = numpy.ascontiguousarray(array.transpose(2, 0, 1)[None], dtype=numpy.float32)
    try:
        outputs = session.run(None, {session.get_inputs()[0].name: tensor})
    except Exception as error:
        raise BgError('O modelo de remoção de fundo falhou ao processar esta imagem (memória insuficiente?).') from error
    result = numpy.asarray(outputs[0], dtype=numpy.float32)
    if result.ndim != 4 or result.shape[0] != 1 or result.shape[1] != 1 or not numpy.isfinite(result).all():
        raise BgError('O modelo de remoção de fundo devolveu um resultado inesperado.')
    result = result[0, 0]
    low, high = float(result.min()), float(result.max())
    result = (result - low) / (high - low + 1e-8)
    mask = Image.fromarray((result * 255.0 + 0.5).astype('uint8'), 'L')
    try:
        return mask.resize(image.size, Image.Resampling.LANCZOS)
    finally:
        mask.close()


def remove_background(image, model=DEFAULT_MODEL, feather=DEFAULT_FEATHER):
    """Devolve uma imagem RGBA igual a `image`, com o fundo transparente. Transparência que já existia é mantida. Não fecha `image`."""
    from PIL import Image, ImageChops, ImageFilter
    if model not in MODELS:
        raise BgError('Modelo de remoção de fundo desconhecido.')
    if isinstance(feather, bool) or not isinstance(feather, int) or not 0 <= feather <= MAX_FEATHER:
        raise BgError(f'A suavização da borda deve ficar entre 0 e {MAX_FEATHER} px.')
    mask = predict_mask(image, model)
    try:
        if feather:
            softened = mask.filter(ImageFilter.GaussianBlur(feather)); mask.close(); mask = softened
        rgba = image.convert('RGBA')
        try:
            original = rgba.getchannel('A')
            combined = ImageChops.multiply(original, mask)
            original.close()
            rgba.putalpha(combined)
            combined.close()
        except Exception:
            rgba.close()
            raise
        return rgba
    finally:
        mask.close()


def coverage(rgba):
    """Fração (0–1) da imagem que ficou opaca (alfa ≥ 128): serve para avisar quando o resultado ficou vazio ou sem mudança."""
    alpha = rgba.getchannel('A')
    try:
        histogram = alpha.histogram()
    finally:
        alpha.close()
    total = sum(histogram)
    return sum(histogram[128:]) / total if total else 0.0
