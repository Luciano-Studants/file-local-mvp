"""Entrega de caminhos ao Arquivo Local já aberto (menu de contexto do Explorer): soquete local por usuário.

Só aceita uma lista JSON de caminhos de texto (até 100, 64 KiB); a validação real dos caminhos continua em
`file_actions.validate_selection`, como em qualquer outra entrada.
"""
from __future__ import annotations

import getpass
import json

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

MAX_MESSAGE = 65536
MAX_PATHS = 100
BATCH_MS = 350          # o Explorer abre um processo por arquivo; juntamos os que chegam em sequência


def server_name() -> str:
    user = ''.join(ch for ch in getpass.getuser() if ch.isalnum() or ch in '-_') or 'user'
    return f'ArquivoLocal-{user}-v1'


def send_paths(paths: list[str], name: str | None = None, timeout_ms: int = 600) -> bool:
    """Envia os caminhos (ou uma lista vazia, que só pede para mostrar o painel). True se a instância aberta recebeu."""
    payload = json.dumps({'paths': [str(path) for path in paths][:MAX_PATHS]}).encode('utf-8')
    if len(payload) > MAX_MESSAGE:
        return False
    socket = QLocalSocket()
    socket.connectToServer(name or server_name())
    if not socket.waitForConnected(timeout_ms):
        return False
    socket.write(payload)
    socket.flush()
    ok = socket.bytesToWrite() == 0 or socket.waitForBytesWritten(timeout_ms)
    socket.disconnectFromServer()
    return bool(ok)


class PathServer(QObject):
    """Escuta o soquete local e emite `paths_received(list)` já agrupado e sem duplicatas."""
    paths_received = Signal(list)

    def __init__(self, name: str | None = None, parent=None):
        super().__init__(parent)
        self.name = name or server_name()
        self.server = QLocalServer(self)
        self.server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self.server.newConnection.connect(self._accept)
        self._buffers: dict[QLocalSocket, bytearray] = {}
        self._batch: list[str] = []
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(BATCH_MS)
        self._timer.timeout.connect(self._flush)

    def start(self) -> bool:
        QLocalServer.removeServer(self.name)      # sobra de uma execução anterior que caiu
        return self.server.listen(self.name)

    def stop(self) -> None:
        self.server.close()

    def _accept(self) -> None:
        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            self._buffers[socket] = bytearray()
            socket.readyRead.connect(lambda s=socket: self._read(s))
            socket.disconnected.connect(lambda s=socket: self._finish(s))

    def _read(self, socket: QLocalSocket) -> None:
        buffer = self._buffers.get(socket)
        if buffer is None:
            return
        buffer.extend(bytes(socket.readAll()))
        if len(buffer) > MAX_MESSAGE:
            self._buffers.pop(socket, None)
            socket.abort()

    def _finish(self, socket: QLocalSocket) -> None:
        buffer = self._buffers.pop(socket, None)
        socket.deleteLater()
        if not buffer:
            return
        try:
            data = json.loads(bytes(buffer).decode('utf-8'))
            paths = data['paths']
        except (ValueError, KeyError, TypeError, UnicodeDecodeError):
            return
        if not isinstance(paths, list) or not all(isinstance(path, str) and 0 < len(path) <= 1024 for path in paths):
            return
        for path in paths[:MAX_PATHS]:
            if path not in self._batch:
                self._batch.append(path)
        if not paths:                              # pedido só de «mostrar painel»
            self._batch.append('')
        self._timer.start()

    def feed(self, paths: list[str]) -> None:
        """Entrada local (primeira instância): passa pelo mesmo agrupamento dos caminhos vindos de outros processos."""
        for path in paths[:MAX_PATHS]:
            if path not in self._batch:
                self._batch.append(path)
        self._timer.start()

    def _flush(self) -> None:
        batch, self._batch = [p for p in self._batch if p][:MAX_PATHS], []
        self.paths_received.emit(batch)
