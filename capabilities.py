"""Offline capability probes used to gate File Local UI actions."""
from __future__ import annotations
import importlib
import os
from pathlib import Path

Capability = tuple[bool, str]


def _modules_available(modules: tuple[str, ...]) -> Capability:
    missing = []
    for module in modules:
        try:
            importlib.import_module(module)
        except Exception:
            missing.append(module)
    if missing:
        return False, 'Dependência ausente ou não carregável: ' + ', '.join(missing)
    return True, 'Dependências locais carregadas.'


def probe_capabilities() -> dict[str, Capability]:
    """Probe installed modules and fixed Windows tools; performs no network or file conversion."""
    image_ok, image_reason = _modules_available(('PIL.Image',))
    pdf_ok, pdf_reason = _modules_available(('pypdf',))
    if os.name == 'nt':
        shell_ok, shell_reason = _modules_available(('pythoncom', 'win32com.client', 'win32gui'))
        local_app_data = os.environ.get('LOCALAPPDATA', '')
        terminal = Path(local_app_data) / 'Microsoft' / 'WindowsApps' / 'wt.exe' if local_app_data else None
        system_root = os.environ.get('SystemRoot', r'C:\Windows')
        powershell = Path(system_root) / 'System32' / 'WindowsPowerShell' / 'v1.0' / 'powershell.exe'
        terminal_ok = bool((terminal and terminal.is_file()) or powershell.is_file())
        terminal_reason = 'Windows Terminal ou Windows PowerShell disponível.' if terminal_ok else 'Windows Terminal e Windows PowerShell não foram localizados.'
    else:
        shell_ok, shell_reason = False, 'A seleção do Explorer/Área de Trabalho é exclusiva do Windows.'
        terminal_ok, terminal_reason = False, 'Terminal local por seleção está disponível somente no Windows.'
    return {
        'images': (image_ok, image_reason),
        'pdf': (pdf_ok, pdf_reason),
        'desktop_selection': (shell_ok, shell_reason),
        'terminal': (terminal_ok, terminal_reason),
        'clipboard': (True, 'Clipboard Qt local disponível.'),
        'shelf': (True, 'Prateleira Qt disponível; arraste Copy-only.'),
        'shift_f9': (False, 'Atalho ainda não registrado.'),
    }


def describe_capabilities(capabilities: dict[str, Capability]) -> str:
    labels = {
        'images': 'Imagens', 'pdf': 'PDF', 'desktop_selection': 'Seleção do Explorer/Desktop',
        'terminal': 'Terminal', 'clipboard': 'Clipboard', 'shelf': 'Prateleira', 'shift_f9': 'Shift+F9',
    }
    rows = []
    for key, label in labels.items():
        available, reason = capabilities.get(key, (False, 'Não verificado.'))
        rows.append(f'{label}: {"disponível" if available else "indisponível"} — {reason}')
    return '\n'.join(rows)
