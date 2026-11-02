"""Preferências do usuário em JSON (pasta local de dados do app): atalho global e gatilho com o botão do meio.

Gravação atômica; valores inválidos voltam ao padrão sem derrubar o aplicativo.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, asdict
from pathlib import Path

from global_hotkey import DEFAULT_HOTKEY, parse_hotkey


@dataclass
class Settings:
    hotkey: str = DEFAULT_HOTKEY            # atalho global das ferramentas do arquivo
    middle_click: bool = False              # Shift + botão do meio abre a roda de ferramentas

    def validated(self) -> 'Settings':
        try:
            hotkey = parse_hotkey(self.hotkey)[2]
        except ValueError:
            hotkey = DEFAULT_HOTKEY
        return Settings(hotkey=hotkey, middle_click=bool(self.middle_click))


def default_settings_path() -> Path:
    from PySide6.QtCore import QStandardPaths
    folder = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation)
    if not folder:
        raise RuntimeError('Não foi possível localizar a pasta local de dados do usuário.')
    return Path(folder) / 'settings.json'


def load_settings(path: Path | None = None) -> Settings:
    """Lê as preferências; arquivo ausente, ilegível ou com tipos errados resulta nos padrões."""
    try:
        target = path or default_settings_path()
        raw = json.loads(Path(target).read_text(encoding='utf-8'))
        if not isinstance(raw, dict) or Path(target).stat().st_size > 16384:
            return Settings()
        return Settings(hotkey=raw.get('hotkey', DEFAULT_HOTKEY) if isinstance(raw.get('hotkey'), str) else DEFAULT_HOTKEY,
                        middle_click=raw.get('middle_click') is True).validated()
    except (OSError, ValueError, RuntimeError):
        return Settings()


def save_settings(settings: Settings, path: Path | None = None) -> bool:
    """Grava via arquivo temporário + os.replace; devolve False (sem exceção) se não conseguir."""
    try:
        target = Path(path or default_settings_path())
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temp = tempfile.mkstemp(prefix='.settings-', suffix='.tmp', dir=target.parent)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as handle:
                json.dump(asdict(settings.validated()), handle, ensure_ascii=False, indent=2)
            os.replace(temp, target)
        except BaseException:
            try:
                os.unlink(temp)
            except OSError:
                pass
            raise
        return True
    except (OSError, RuntimeError):
        return False
