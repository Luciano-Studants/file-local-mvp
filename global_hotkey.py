"""Registro de atalho global (padrão Shift+F9) sem ganchos de teclado e sem registrar teclas."""
from __future__ import annotations
import ctypes
import os
from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter

HOTKEY_ID = 0xA710
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_NOREPEAT = 0x4000
VK_F9 = 0x78
WM_HOTKEY = 0x0312
DEFAULT_HOTKEY = 'Shift+F9'
# Alternativas oferecidas na tela de configurações. Todas exigem modificador; Alt+Espaço fica de fora (menu do sistema).
HOTKEY_PRESETS = ['Shift+F9', 'Ctrl+Shift+F9', 'Ctrl+Alt+F9', 'Ctrl+Alt+Espaço', 'Ctrl+Shift+Espaço']
_MODIFIERS = {'SHIFT': MOD_SHIFT, 'CTRL': MOD_CONTROL, 'CONTROL': MOD_CONTROL, 'ALT': MOD_ALT}


def parse_hotkey(text: str) -> tuple[int, int, str]:
    """Valida e converte «Ctrl+Shift+F9» em (modificadores, código virtual, texto normalizado).

    Regras: ao menos um modificador (Shift, Ctrl ou Alt); Shift sozinho só com teclas F1–F12 (senão engoliria a digitação);
    teclas permitidas: F1–F12, A–Z e Espaço; Alt+Espaço é recusado por conflitar com o menu da janela.
    """
    parts = [part.strip() for part in str(text).replace(' ', '').split('+') if part.strip()]
    if len(parts) < 2:
        raise ValueError('O atalho precisa de ao menos um modificador (Shift, Ctrl ou Alt) e uma tecla.')
    *mods, key = parts
    modifiers = 0
    names = []
    for name in mods:
        flag = _MODIFIERS.get(name.upper())
        if flag is None:
            raise ValueError(f'Modificador desconhecido: {name}.')
        if not modifiers & flag:
            modifiers |= flag
            names.append({MOD_SHIFT: 'Shift', MOD_CONTROL: 'Ctrl', MOD_ALT: 'Alt'}[flag])
    upper = key.upper()
    if upper in ('ESPAÇO', 'ESPACO', 'SPACE'):
        vk, key_name = 0x20, 'Espaço'
    elif len(upper) in (2, 3) and upper[0] == 'F' and upper[1:].isdigit() and 1 <= int(upper[1:]) <= 12:
        vk, key_name = 0x70 + int(upper[1:]) - 1, upper
    elif len(upper) == 1 and 'A' <= upper <= 'Z':
        vk, key_name = ord(upper), upper
    else:
        raise ValueError('Tecla não permitida: use F1–F12, uma letra de A a Z ou Espaço.')
    if modifiers == MOD_SHIFT and not key_name.startswith('F'):
        raise ValueError('Shift sozinho só pode acompanhar teclas F1–F12; com letras ou Espaço atrapalharia a digitação.')
    if modifiers == MOD_ALT and key_name == 'Espaço':
        raise ValueError('Alt+Espaço abre o menu da janela do Windows; escolha outro atalho.')
    order = [name for name in ('Ctrl', 'Alt', 'Shift') if name in names]
    return modifiers, vk, '+'.join([*order, key_name])


class _NativeMessage(ctypes.Structure):
    _fields_ = [
        ('hwnd', wintypes.HWND),
        ('message', wintypes.UINT),
        ('wParam', wintypes.WPARAM),
        ('lParam', wintypes.LPARAM),
        ('time', wintypes.DWORD),
        ('pt_x', wintypes.LONG),
        ('pt_y', wintypes.LONG),
        ('lPrivate', wintypes.DWORD),
    ]


def is_hotkey_message(message_id: int, wparam: int) -> bool:
    return int(message_id) == WM_HOTKEY and int(wparam) == HOTKEY_ID


class GlobalHotkey(QAbstractNativeEventFilter):
    """Registra um atalho para uma janela Qt oculta; nenhum gancho e nenhuma outra tecla é lida."""
    def __init__(self, app, callback, hotkey: str = DEFAULT_HOTKEY):
        super().__init__()
        self.app = app
        self.callback = callback
        self.modifiers, self.vk, self.hotkey = parse_hotkey(hotkey)
        self.window = None
        self.registered = False
        self.last_error = 0

    def nativeEventFilter(self, event_type, message):
        if os.name != 'nt':
            return False, 0
        try:
            pointer = int(message)
            native = ctypes.cast(pointer, ctypes.POINTER(_NativeMessage)).contents
        except (TypeError, ValueError, OSError):
            return False, 0
        if is_hotkey_message(native.message, native.wParam):
            self.callback()
            return True, 0
        return False, 0

    def start(self) -> bool:
        if os.name != 'nt':
            return False
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QWidget
        self.window = QWidget()
        self.window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        self.window.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        hwnd = int(self.window.winId())
        self.app.installNativeEventFilter(self)
        user32 = ctypes.WinDLL('user32', use_last_error=True)
        register = user32.RegisterHotKey
        register.argtypes = (wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT)
        register.restype = wintypes.BOOL
        if not register(wintypes.HWND(hwnd), HOTKEY_ID, self.modifiers | MOD_NOREPEAT, self.vk):
            self.last_error = ctypes.get_last_error()
            self.app.removeNativeEventFilter(self)
            self.window.destroy()
            self.window = None
            return False
        self.registered = True
        return True

    def stop(self) -> None:
        if self.registered and self.window is not None and os.name == 'nt':
            user32 = ctypes.WinDLL('user32', use_last_error=True)
            unregister = user32.UnregisterHotKey
            unregister.argtypes = (wintypes.HWND, ctypes.c_int)
            unregister.restype = wintypes.BOOL
            unregister(wintypes.HWND(int(self.window.winId())), HOTKEY_ID)
            self.registered = False
        if os.name == 'nt':
            try:
                self.app.removeNativeEventFilter(self)
            except RuntimeError:
                pass
        if self.window is not None:
            self.window.destroy()
            self.window = None


    def restart(self, hotkey: str) -> bool:
        """Troca o atalho: valida, libera o atual e registra o novo; se o novo falhar, volta ao anterior."""
        modifiers, vk, normalized = parse_hotkey(hotkey)
        previous = (self.modifiers, self.vk, self.hotkey)
        self.stop()
        self.modifiers, self.vk, self.hotkey = modifiers, vk, normalized
        if self.start():
            return True
        self.modifiers, self.vk, self.hotkey = previous
        self.start()
        return False


class ShiftF9Hotkey(GlobalHotkey):
    """Compatibilidade: o atalho padrão Shift+F9."""
    def __init__(self, app, callback):
        super().__init__(app, callback, DEFAULT_HOTKEY)
