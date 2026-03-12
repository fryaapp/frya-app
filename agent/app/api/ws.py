from __future__ import annotations

from fastapi import APIRouter, WebSocket
from starlette.websockets import WebSocketDisconnect

router = APIRouter(tags=['ws'])


@router.websocket('/ws/{client_id}')
async def ws_endpoint(websocket: WebSocket, client_id: str) -> None:
    # WS bleibt in Paket 1 bewusst geschlossen, bis eine eigene WS-Auth vorhanden ist.
    await websocket.close(code=1008, reason='ws_auth_not_enabled')
    try:
        await websocket.receive_text()
    except WebSocketDisconnect:
        return
