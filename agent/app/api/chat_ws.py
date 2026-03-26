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
  {"type": "ui_hint", "action": "open_context", "context_type": "..."}
  {"type": "message_complete", "text": "...", "case_ref": null, "context_type": "...", "suggestions": [...]}
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
# Typing hints (intent -> user-facing status text)
# ---------------------------------------------------------------------------

TYPING_HINTS: dict[str, str] = {
    'document_analyze': 'Schaue mir den Beleg an...',
    'booking_journal_show': 'Lade das Buchungsjournal...',
    'euer_generate': 'Rechne die EÜR zusammen...',
    'ust_generate': 'Berechne die USt...',
    'open_items_show': 'Prüfe die offenen Posten...',
    'contact_search': 'Suche den Kontakt...',
    'vendor_search': 'Durchsuche die Vorgänge...',
}

_GENERIC_TYPING_HINT = 'Einen Moment...'

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DEFAULT_SUGGESTIONS: list[str] = [
    'Was gibt es Neues?',
    'Zeig mir offene Posten',
    'Hilfe',
]

# Intent-to-context mapping for communicator results that expose an intent.
INTENT_TO_CONTEXT: dict[str, str] = {
    'booking_journal_show': 'bookings',
    'euer_generate': 'finance',
    'ust_generate': 'finance',
    'open_items_show': 'open_items',
    'deadline_show': 'deadlines',
    'case_detail': 'case_detail',
    'document_search': 'document_preview',
    'invoice_create': 'invoice_draft',
    'contact_search': 'contact_card',
}


def _detect_context_type(user_text: str) -> str:
    """Keyword-based fallback for context_type detection."""
    text = user_text.lower()
    if any(w in text for w in ('frist', 'deadline', 'fällig', 'termin')):
        return 'deadlines'
    if any(w in text for w in ('eür', 'einnahmen', 'ausgaben', 'finanzen', 'bilanz')):
        return 'finance'
    if any(w in text for w in ('inbox', 'beleg', 'rechnung', 'offene')):
        return 'inbox'
    if any(w in text for w in ('buchung', 'journal', 'konto')):
        return 'bookings'
    if any(w in text for w in ('upload', 'hochladen', 'wäschekorb')):
        return 'upload_status'
    if any(w in text for w in ('kontakt', 'lieferant', 'kunde')):
        return 'contact_card'
    return 'none'


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

                # Typing indicator ON with hint
                await websocket.send_json({
                    'type': 'typing',
                    'active': True,
                    'hint': _GENERIC_TYPING_HINT,
                })

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

                    # --- Determine context_type ---
                    # Try intent from communicator first, fall back to keywords.
                    intent = getattr(result, 'intent', None) if result else None
                    context_type = (
                        INTENT_TO_CONTEXT.get(intent, 'none')
                        if intent
                        else _detect_context_type(text)
                    )

                    # Send ui_hint before message_complete when relevant.
                    if context_type != 'none':
                        await websocket.send_json({
                            'type': 'ui_hint',
                            'action': 'open_context',
                            'context_type': context_type,
                        })

                    await websocket.send_json({
                        'type': 'message_complete',
                        'text': reply_text,
                        'case_ref': case_ref,
                        'context_type': context_type,
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


# NOTE: Synchronous POST /api/v1/chat is provided by customer_api.py
# (expects {"message": "..."} with Bearer auth). Removed from here to
# avoid duplicate route conflict.
