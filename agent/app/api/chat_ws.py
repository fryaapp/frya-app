"""WebSocket chat endpoint for the React UI.

WS /api/v1/chat/stream?token=JWT
POST /api/v1/chat  (synchronous fallback)

Protocol (inbound):
  {"type": "message", "text": "..."}
  {"type": "ping"}

Protocol (outbound):
  {"type": "pong"}
  {"type": "typing", "active": true/false}
  {"type": "chunk", "text": "..."}
  {"type": "message_complete", "text": "...", "case_ref": null, "suggestions": [...]}
  {"type": "error", "message": "..."}
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Query, WebSocket
from pydantic import BaseModel
from starlette.websockets import WebSocketDisconnect, WebSocketState

from app.auth.jwt_auth import decode_token
from app.dependencies import (
    get_audit_service,
    get_chat_history_store,
    get_communicator_conversation_store,
    get_communicator_user_store,
    get_llm_config_repository,
    get_open_items_service,
    get_telegram_clarification_service,
    get_telegram_communicator_service,
)
from app.telegram.communicator.models import CommunicatorResult
from app.telegram.models import TelegramActor, TelegramNormalizedIngressMessage

logger = logging.getLogger(__name__)

router = APIRouter(prefix='/api/v1/chat', tags=['chat'])

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DEFAULT_SUGGESTIONS: list[str] = [
    'Was gibt es Neues?',
    'Zeig mir offene Posten',
    'Hilfe',
]


def _validate_jwt(token: str) -> dict:
    """Decode and validate a JWT token.  Returns the payload dict.

    Raises ``ValueError`` with a human-readable message on failure.
    """
    if not token:
        raise ValueError('Token fehlt')
    try:
        payload = decode_token(token)
    except Exception as exc:
        raise ValueError(f'Ungültiges Token: {exc}') from exc
    if payload.get('type') != 'access':
        raise ValueError('Kein Access-Token')
    return payload


def _build_normalized_message(
    text: str,
    user_id: str,
    tenant_id: str,
) -> TelegramNormalizedIngressMessage:
    """Build a ``TelegramNormalizedIngressMessage`` suitable for the
    communicator service from a plain web-chat message."""
    event_id = str(uuid.uuid4())
    return TelegramNormalizedIngressMessage(
        event_id=event_id,
        source='telegram',  # reuse existing literal
        raw_type='message',
        text=text,
        telegram_update_ref=f'web-{event_id}',
        telegram_message_ref=f'web-msg-{event_id}',
        telegram_chat_ref=f'web-chat-{user_id}',
        actor=TelegramActor(
            chat_id=f'web-{user_id}',
            chat_type='web',
            sender_id=user_id,
            sender_username=user_id,
        ),
    )


async def _get_communicator_reply(
    text: str,
    user_id: str,
    tenant_id: str,
) -> CommunicatorResult | None:
    """Run the communicator pipeline and return the result."""
    normalized = _build_normalized_message(text, user_id, tenant_id)
    case_id = f'web-{user_id}-{uuid.uuid4().hex[:8]}'
    service = get_telegram_communicator_service()
    return await service.try_handle_turn(
        normalized,
        case_id,
        audit_service=get_audit_service(),
        open_items_service=get_open_items_service(),
        clarification_service=get_telegram_clarification_service(),
        conversation_store=get_communicator_conversation_store(),
        user_store=get_communicator_user_store(),
        llm_config_repository=get_llm_config_repository(),
        chat_history_store=get_chat_history_store(),
    )


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------


@router.websocket('/stream')
async def chat_stream(websocket: WebSocket, token: str = Query(...)) -> None:
    """Real-time chat over WebSocket.

    The client connects with ``?token=<JWT>`` and exchanges JSON frames.
    """
    # ── Auth ──────────────────────────────────────────────────────────────
    try:
        jwt_payload = _validate_jwt(token)
    except ValueError as exc:
        await websocket.close(code=1008, reason=str(exc))
        return

    user_id: str = jwt_payload.get('sub', 'unknown')
    tenant_id: str = jwt_payload.get('tid', '')

    await websocket.accept()
    logger.info('WS chat connected: user=%s tenant=%s', user_id, tenant_id)

    try:
        while True:
            data: dict = await websocket.receive_json()
            msg_type = data.get('type')

            # ── Ping / Pong ───────────────────────────────────────────────
            if msg_type == 'ping':
                await websocket.send_json({'type': 'pong'})
                continue

            # ── Chat message ──────────────────────────────────────────────
            if msg_type == 'message':
                text = (data.get('text') or '').strip()
                if not text:
                    await websocket.send_json({
                        'type': 'error',
                        'message': 'Leere Nachricht',
                    })
                    continue

                # Typing indicator ON
                await websocket.send_json({'type': 'typing', 'active': True})

                try:
                    result = await _get_communicator_reply(text, user_id, tenant_id)

                    if result and result.handled:
                        reply_text = result.reply_text
                        case_ref = (
                            result.turn.context_resolution.resolved_case_ref
                            if result.turn.context_resolution
                            else None
                        )
                    else:
                        reply_text = (
                            'Entschuldigung, ich konnte deine Nachricht '
                            'gerade nicht verarbeiten. Bitte versuche es erneut.'
                        )
                        case_ref = None

                    await websocket.send_json({
                        'type': 'message_complete',
                        'text': reply_text,
                        'case_ref': case_ref,
                        'suggestions': _DEFAULT_SUGGESTIONS,
                    })

                except Exception:
                    logger.exception('Communicator error for user=%s', user_id)
                    await websocket.send_json({
                        'type': 'error',
                        'message': 'Interner Fehler — bitte versuche es erneut.',
                    })

                finally:
                    # Typing indicator OFF — guard against already-closed socket
                    if websocket.client_state == WebSocketState.CONNECTED:
                        await websocket.send_json({'type': 'typing', 'active': False})

                continue

            # ── Unknown frame type ────────────────────────────────────────
            await websocket.send_json({
                'type': 'error',
                'message': f'Unbekannter Nachrichtentyp: {msg_type}',
            })

    except WebSocketDisconnect:
        logger.info('WS chat disconnected: user=%s', user_id)
    except Exception:
        logger.exception('WS chat error: user=%s', user_id)
        if websocket.client_state == WebSocketState.CONNECTED:
            await websocket.close(code=1011, reason='internal_error')


# ---------------------------------------------------------------------------
# Synchronous POST fallback
# ---------------------------------------------------------------------------


class ChatRequest(BaseModel):
    text: str
    token: str


class ChatResponse(BaseModel):
    text: str
    case_ref: str | None = None
    suggestions: list[str] = []


@router.post('', response_model=ChatResponse)
async def chat_sync(body: ChatRequest) -> ChatResponse:
    """Synchronous chat endpoint — POST /api/v1/chat.

    Accepts ``{"text": "...", "token": "JWT"}`` and returns the full
    assistant reply in one response.
    """
    try:
        jwt_payload = _validate_jwt(body.token)
    except ValueError as exc:
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    user_id: str = jwt_payload.get('sub', 'unknown')
    tenant_id: str = jwt_payload.get('tid', '')

    try:
        result = await _get_communicator_reply(body.text.strip(), user_id, tenant_id)
    except Exception:
        logger.exception('POST /api/v1/chat error for user=%s', user_id)
        from fastapi import HTTPException
        raise HTTPException(
            status_code=500,
            detail='Interner Fehler — bitte versuche es erneut.',
        )

    if result and result.handled:
        reply_text = result.reply_text
        case_ref = (
            result.turn.context_resolution.resolved_case_ref
            if result.turn.context_resolution
            else None
        )
    else:
        reply_text = (
            'Entschuldigung, ich konnte deine Nachricht '
            'gerade nicht verarbeiten. Bitte versuche es erneut.'
        )
        case_ref = None

    return ChatResponse(
        text=reply_text,
        case_ref=case_ref,
        suggestions=_DEFAULT_SUGGESTIONS,
    )
