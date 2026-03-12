from __future__ import annotations

from typing import Any

from app.connectors.contracts import NotificationConnector, NotificationMessage


class WebSocketNotificationConnector(NotificationConnector):
    def __init__(self) -> None:
        self._clients: dict[str, Any] = {}

    def register(self, client_id: str, websocket: Any) -> None:
        self._clients[client_id] = websocket

    def unregister(self, client_id: str) -> None:
        self._clients.pop(client_id, None)

    async def send(self, message: NotificationMessage) -> dict:
        ws = self._clients.get(message.target)
        if ws is None:
            return {'ok': False, 'reason': 'client_not_connected'}
        await ws.send_json({'text': message.text, 'metadata': message.metadata or {}})
        return {'ok': True}
