"""Item «Arquivo Local» no menu de contexto do Explorer para imagens e PDFs (por usuário, sem administrador).

Grava só em HKEY_CURRENT_USER\\Software\\Classes e só as chaves do próprio aplicativo; remover apaga somente elas.
No Windows 11 o item aparece em «Mostrar mais opções». O módulo `winreg` é injetável para os testes.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

VERB_KEY = 'ArquivoLocal'
VERB_LABEL = 'Arquivo Local'
BASES = (r'Software\Classes\SystemFileAssociations\image\shell', r'Software\Classes\SystemFileAssociations\.pdf\shell')


def launch_command(executable: str | None = None, script: str | None = None) -> str:
    """Linha de comando do verbo; cada caminho entre aspas (o Explorer substitui %1 com segurança, sem passar por cmd)."""
    if getattr(sys, 'frozen', False) and executable is None:
        return f'"{sys.executable}" --send-to "%1"'
    executable = executable or sys.executable
    if os.name == 'nt' and Path(executable).name.lower() == 'python.exe':
        pythonw = Path(executable).with_name('pythonw.exe')
        executable = str(pythonw) if pythonw.exists() else executable
    script = script or str(Path(__file__).with_name('app.py'))
    return f'"{executable}" "{script}" --send-to "%1"'


def _registry(registry=None):
    if registry is not None:
        return registry
    import winreg
    return winreg


def install(command: str | None = None, registry=None) -> bool:
    reg = _registry(registry)
    command = command or launch_command()
    try:
        for base in BASES:
            with reg.CreateKey(reg.HKEY_CURRENT_USER, f'{base}\\{VERB_KEY}') as key:
                reg.SetValueEx(key, '', 0, reg.REG_SZ, VERB_LABEL)
            with reg.CreateKey(reg.HKEY_CURRENT_USER, f'{base}\\{VERB_KEY}\\command') as key:
                reg.SetValueEx(key, '', 0, reg.REG_SZ, command)
        return True
    except OSError:
        return False


def is_installed(registry=None) -> bool:
    reg = _registry(registry)
    try:
        for base in BASES:
            with reg.OpenKey(reg.HKEY_CURRENT_USER, f'{base}\\{VERB_KEY}\\command') as key:
                if not reg.QueryValueEx(key, '')[0]:
                    return False
        return True
    except OSError:
        return False


def uninstall(registry=None) -> bool:
    reg = _registry(registry)
    ok = True
    for base in BASES:
        for sub in (f'{base}\\{VERB_KEY}\\command', f'{base}\\{VERB_KEY}'):
            try:
                reg.DeleteKey(reg.HKEY_CURRENT_USER, sub)
            except FileNotFoundError:
                pass
            except OSError:
                ok = False
    return ok
