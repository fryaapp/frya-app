"""Communicator send-message endpoint — POST /api/communicator/send-message.

Sends a direct Telegram message without LLM involvement.
Auth: n8n API token (X-N8N-API-KEY or Authorization: Bearer).
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from app.api.n8n_endpoints import require_n8n_token
from app.connectors.contracts import NotificationMessage
from app.dependencies import get_telegram_connector

router = APIRouter(prefix='/api/communicator', tags=['communicator'])


class SendMessageRequest(BaseModel):
    chat_id: str
    text: str


@router.post('/send-message', dependencies=[Depends(require_n8n_token)])
async def send_message(body: SendMessageRequest) -> dict[str, Any]:
    """Send a plain Telegram message directly (no LLM, no session)."""
    connector = get_telegram_connector()
    result = await connector.send(
        NotificationMessage(target=body.chat_id, text=body.text)
    )
    return {'ok': result.get('ok', False), 'detail': result}
