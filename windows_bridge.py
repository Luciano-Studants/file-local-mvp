"""Windows Shell bridge for Explorer/desktop selections and the Shift key state."""
from __future__ import annotations
import ctypes
import ntpath
import os

EXPLORER_CLASSES = {'CabinetWClass', 'ExploreWClass'}
DESKTOP_ROOT_CLASSES = {'Progman', 'WorkerW'}
VK_SHIFT = 0x10
VK_F9 = 0x78
CSIDL_DESKTOP = 0
SWC_DESKTOP = 8
SWFO_NEEDDISPATCH = 1


def shift_is_down() -> bool:
    """Read only the current Shift state; no keystrokes are recorded."""
    if os.name != 'nt':
        return False
    return bool(ctypes.windll.user32.GetAsyncKeyState(VK_SHIFT) & 0x8000)


def f9_is_down() -> bool:
    """Read only whether F9 is currently down; no key events are recorded."""
    if os.name != 'nt':
        return False
    return bool(ctypes.windll.user32.GetAsyncKeyState(VK_F9) & 0x8000)


def key_is_down(virtual_key: int) -> bool:
    """Lê só se uma tecla está pressionada agora (modificadores, F-teclas, botão do meio = 0x04); nada é registrado."""
    if os.name != 'nt':
        return False
    return bool(ctypes.windll.user32.GetAsyncKeyState(virtual_key) & 0x8000)


def normalize_shell_paths(values) -> list[str]:
    """Keep unique absolute local Windows paths; reject UNC and virtual items."""
    result = []
    seen = set()
    for value in values:
        path = str(value or '').strip()
        if not path or path.startswith('\\\\') or path.startswith('//') or not ntpath.isabs(path):
            continue
        normalized = ntpath.normpath(path)
        key = normalized.casefold()
        if key not in seen:
            seen.add(key)
            result.append(normalized)
    return result


def is_desktop_root_class(class_name: str) -> bool:
    """Identify top-level Windows shell containers that can host the desktop view."""
    return class_name in DESKTOP_ROOT_CLASSES


def _foreground_handles(win32gui):
    foreground = win32gui.GetForegroundWindow()
    if not foreground:
        return 0, 0, ''
    root = win32gui.GetAncestor(foreground, 2) or foreground  # GA_ROOT
    try:
        root_class = win32gui.GetClassName(root)
    except Exception:
        root_class = win32gui.GetClassName(foreground)
    return int(foreground), int(root), root_class


def _selection_paths(shell_window) -> list[str]:
    selected_items = shell_window.Document.SelectedItems()
    return normalize_shell_paths(str(getattr(item, 'Path', '') or '') for item in selected_items)


def _desktop_dispatch(shell_windows, pythoncom, win32_client):
    """Resolve the registered Desktop Shell view through documented ShellWindows automation."""
    result = shell_windows.FindWindowSW(
        win32_client.VARIANT(pythoncom.VT_I4, CSIDL_DESKTOP),
        win32_client.VARIANT(pythoncom.VT_EMPTY, None),
        SWC_DESKTOP,
        0,
        SWFO_NEEDDISPATCH,
    )
    candidates = result if isinstance(result, tuple) else (result,)
    for candidate in candidates:
        try:
            if candidate is not None and candidate.Document is not None:
                return candidate
        except Exception:
            continue
    return None


def selected_paths_from_explorer() -> list[str]:
    """Return file-system paths selected in the foreground Explorer or desktop view."""
    if os.name != 'nt':
        return []

    import pythoncom
    import win32com.client as win32_client
    import win32gui

    foreground, root, root_class = _foreground_handles(win32gui)
    if not foreground:
        return []
    if root_class not in EXPLORER_CLASSES and not is_desktop_root_class(root_class):
        return []

    pythoncom.CoInitialize()
    try:
        shell = win32_client.Dispatch('Shell.Application')
        shell_windows = shell.Windows()

        if root_class in EXPLORER_CLASSES:
            for window in shell_windows:
                try:
                    if int(window.HWND) in {foreground, root}:
                        return _selection_paths(window)
                except Exception:
                    continue
            return []

        # The Desktop is a Shell view, not an ordinary Explorer frame. FindWindowSW
        # retrieves that registered view, and its Document exposes SelectedItems().
        desktop = _desktop_dispatch(shell_windows, pythoncom, win32_client)
        if desktop is None:
            return []
        return _selection_paths(desktop)
    finally:
        pythoncom.CoUninitialize()
