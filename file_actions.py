"""Non-destructive Windows file actions for the secondary radial menu."""
from __future__ import annotations
import ctypes
import ntpath
import os
import stat
from pathlib import Path

FILE_ATTRIBUTE_REPARSE_POINT = 0x0400
DRIVE_REMOTE = 4


def normalize_local_paths(values) -> list[str]:
    """Normalize and deduplicate absolute drive paths, rejecting UNC/virtual paths."""
    paths: list[str] = []
    seen: set[str] = set()
    for value in values:
        raw = str(value or '').strip()
        if not raw or raw.startswith('\\\\') or raw.startswith('//'):
            continue
        drive, tail = ntpath.splitdrive(raw)
        if not drive or not ntpath.isabs(raw) or ':' in tail:
            continue
        normalized = ntpath.normpath(raw)
        key = normalized.casefold()
        if key not in seen:
            seen.add(key)
            paths.append(normalized)
    return paths


def validate_local_item(raw: str, *, drive_type_fn=None, lstat_fn=None) -> str:
    """Revalidate an existing ordinary local file/folder immediately before use."""
    normalized = normalize_local_paths([raw])
    if len(normalized) != 1:
        raise ValueError('Selecione um caminho absoluto de disco local; caminhos de rede não são aceitos.')
    path = normalized[0]
    if os.name != 'nt':
        raise OSError('Ações globais de arquivos estão disponíveis somente no Windows.')

    drive, _ = ntpath.splitdrive(path)
    if drive_type_fn is None:
        drive_type_fn = ctypes.WinDLL('kernel32', use_last_error=True).GetDriveTypeW
        drive_type_fn.argtypes = (ctypes.c_wchar_p,)
        drive_type_fn.restype = ctypes.c_uint
    if drive_type_fn(drive + '\\') == DRIVE_REMOTE:
        raise ValueError('Unidades de rede não são aceitas.')

    native_path = Path(path)
    components = list(reversed(native_path.parents)) + [native_path]
    metadata = None
    for index, component in enumerate(components):
        try:
            current = (lstat_fn or os.lstat)(component)
        except OSError as error:
            raise ValueError('O item ou um diretório pai não existe ou não está acessível.') from error
        attributes = getattr(current, 'st_file_attributes', 0)
        if stat.S_ISLNK(current.st_mode) or attributes & FILE_ATTRIBUTE_REPARSE_POINT:
            raise ValueError('Links, junctions e reparse points não são aceitos nesta ação.')
        if index < len(components) - 1 and not stat.S_ISDIR(current.st_mode):
            raise ValueError('O caminho atravessa um componente que não é uma pasta comum.')
        metadata = current
    if metadata is None or not (stat.S_ISREG(metadata.st_mode) or stat.S_ISDIR(metadata.st_mode)):
        raise ValueError('Somente arquivos e pastas comuns são aceitos.')
    return path


def validate_selection(paths: list[str]) -> list[str]:
    """Validate each path and return a case-insensitively unique selection."""
    result = []
    seen = set()
    for raw in paths:
        path = validate_local_item(raw)
        key = path.casefold()
        if key not in seen:
            seen.add(key)
            result.append(path)
    if not result:
        raise ValueError('Nenhum arquivo local válido foi selecionado.')
    return result


def copy_paths_text(paths: list[str]) -> str:
    """Format validated paths as one Unicode path per line."""
    return '\r\n'.join(validate_selection(paths))


def format_path_lines(paths: list[str]) -> str:
    """Format already-normalized paths without touching the filesystem."""
    return '\r\n'.join(normalize_local_paths(paths))


def terminal_directory(paths: list[str]) -> str:
    """Return the selected folder or the containing directory of one selected file."""
    validated = validate_selection(paths)
    if len(validated) != 1:
        raise ValueError('Abra o terminal com apenas um arquivo ou pasta selecionado.')
    path = Path(validated[0])
    return str(path if path.is_dir() else path.parent)
