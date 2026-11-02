"""Per-user single-instance lock for the tray application."""
from __future__ import annotations
from pathlib import Path

from PySide6.QtCore import QLockFile, QStandardPaths


def acquire_app_lock(lock_path: str | None = None) -> QLockFile | None:
    """Return an acquired QLockFile, or None if another process owns it."""
    if lock_path is None:
        data_dir = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation)
        if not data_dir:
            raise RuntimeError('Não foi possível localizar a pasta local de dados do usuário.')
        Path(data_dir).mkdir(parents=True, exist_ok=True)
        lock_path = str(Path(data_dir) / 'arquivo-local-instance.lock')
    lock = QLockFile(lock_path)
    if not lock.tryLock(0):
        return None
    return lock
