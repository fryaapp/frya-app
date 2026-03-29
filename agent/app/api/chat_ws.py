"""WebSocket chat endpoint for the React UI.

WS /api/v1/chat/stream?token=JWT
POST /api/v1/chat  (synchronous fallback)

Protocol (inbound):
  {"type": "message", "text": "...", "quick_action": {...}}  # quick_action optional
  {"type": "form_submit", "form_type": "...", "data": {...}}
  {"type": "ping"}

Protocol (outbound):
  {"type": "pong"}
  {"type": "typing", "active": true/false}
  {"type": "chunk", "text": "..."}
  {"type": "ui_hint", "action": "open_context", "context_type": "..."}
  {"type": "message_complete", "text": "...", "case_ref": null, "context_type": "...",
   "suggestions": [...], "content_blocks": [...], "actions": [...]}
  {"type": "error", "message": "..."}

FLOW (after integration):
  1. User sends message (+ optional quick_action)
  2. TieredOrchestrator.route() → intent + routing tier (regex/fast/deep)
  3. For regex/fast: intent is known, skip to step 5
  4. For deep/fallback: Communicator pipeline (existing code)
  5. ResponseBuilder adds content_blocks + actions to response
  6. Backward-compat: text, suggestions, context_type always present
"""
from __future__ import annotations

import html as _html
import logging
import time
import uuid
from typing import Any

from fastapi import APIRouter, Query, WebSocket
from pydantic import BaseModel
from starlette.websockets import WebSocketDisconnect, WebSocketState

from app.auth.jwt_auth import decode_token
from app.security.input_sanitizer import sanitize_user_message
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
# New modules (Phase G/H/I integration)
# ---------------------------------------------------------------------------

_tiered_orchestrator = None
_response_builder = None


def _get_tiered_orchestrator():
    global _tiered_orchestrator
    if _tiered_orchestrator is None:
        try:
            from app.agents.tiered_orchestrator import TieredOrchestrator
            from app.agents.action_router import ActionRouter
            from app.agents.service_registry import build_service_registry
            services = build_service_registry()
            action_router = ActionRouter(services=services)
            _tiered_orchestrator = TieredOrchestrator(action_router=action_router)
            logger.info('TieredOrchestrator initialized with ActionRouter (%d services)', len(services))
        except Exception as exc:
            logger.warning('TieredOrchestrator unavailable: %s', exc)
    return _tiered_orchestrator


def _get_response_builder():
    global _response_builder
    if _response_builder is None:
        try:
            from app.agents.response_builder import ResponseBuilder
            _response_builder = ResponseBuilder()
        except Exception as exc:
            logger.warning('ResponseBuilder unavailable: %s', exc)
    return _response_builder


# Map TieredOrchestrator intents to context_type for the frontend
_TIER_INTENT_TO_CONTEXT: dict[str, str] = {
    'SHOW_INBOX': 'inbox',
    'SHOW_FINANCE': 'finance',
    'SHOW_DEADLINES': 'deadlines',
    'SHOW_BOOKINGS': 'bookings',
    'SHOW_OPEN_ITEMS': 'open_items',
    'SHOW_CONTACT': 'contact_card',
    'SHOW_EXPORT': 'finance',
    'CREATE_INVOICE': 'invoice_draft',
    'CREATE_CONTACT': 'contact_card',
    'CREATE_REMINDER': 'deadlines',
    'SETTINGS': 'settings',
    'UPLOAD': 'upload_status',
    'STATUS_OVERVIEW': 'none',
    'SMALL_TALK': 'none',
    'APPROVE': 'inbox',
}


# ---------------------------------------------------------------------------
# Name-update detection — detects "Ich heiße X" etc. and persists it
# ---------------------------------------------------------------------------

import re

_NAME_PATTERNS = [
    re.compile(r'(?:ich\s+hei(?:ß|ss)e|mein\s+name\s+ist|nenn\s+mich|ich\s+bin(?:\s+die|\s+der)?)\s+(\w[\w\s-]{0,30})', re.IGNORECASE),
]


def _extract_name_intent(user_text: str) -> str | None:
    """Extract a display-name from the user message, or return None."""
    text = user_text.strip()
    for pat in _NAME_PATTERNS:
        m = pat.search(text)
        if m:
            name = m.group(1).strip().rstrip('.!?,;')
            # Sanity: at least 2 chars, not a common filler
            if len(name) >= 2 and name.lower() not in ('da', 'ja', 'so', 'es', 'ok'):
                return name
    return None


def _sanitize_display_name(name: str) -> str:
    """Sanitize display_name to prevent XSS."""
    # HTML-escape first
    name = _html.escape(name, quote=True)
    # Only allow letters, numbers, spaces, hyphens, German umlauts
    name = re.sub(r'[^\w\s\-äöüÄÖÜß]', '', name)
    # Max 50 chars
    return name[:50].strip()


async def _persist_display_name(user_id: str, tenant_id: str, new_name: str) -> None:
    """Write display_name to frya_user_preferences (upsert)."""
    new_name = _sanitize_display_name(new_name)
    if not new_name:
        return
    try:
        from app.dependencies import get_settings
        settings = get_settings()
        db_url = settings.database_url
        if db_url.startswith('memory://'):
            return
        import asyncpg
        # TODO(P-53): Replace with connection pool from app lifespan
        conn = await asyncpg.connect(db_url)
        try:
            await conn.execute('''
                INSERT INTO frya_user_preferences (tenant_id, user_id, key, value, updated_at)
                VALUES ($1, $2, 'display_name', $3, NOW())
                ON CONFLICT (tenant_id, user_id, key) DO UPDATE
                  SET value = EXCLUDED.value, updated_at = NOW()
            ''', tenant_id, user_id, new_name)
            logger.info('Persisted display_name=%s for user=%s', new_name, user_id)
        finally:
            await conn.close()
    except Exception as exc:
        logger.warning('Failed to persist display_name: %s', exc)

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

MAX_WS_MESSAGE_LENGTH = 4000

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

    # Rate limiting state (per connection)
    _msg_count = 0
    _rate_window_start = time.monotonic()
    _MAX_MESSAGES_PER_MINUTE = 30

    try:
        while True:
            data: dict = await websocket.receive_json()
            msg_type = data.get('type')

            # ── Fallback: no type but has text → treat as message ────────
            if not msg_type and data.get('text'):
                msg_type = 'message'
                data['type'] = 'message'

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

                # H-2: Max message length guard
                if len(text) > MAX_WS_MESSAGE_LENGTH:
                    await websocket.send_json({
                        'type': 'error',
                        'message': f'Nachricht zu lang (max {MAX_WS_MESSAGE_LENGTH} Zeichen).',
                    })
                    continue

                # G-1: Per-connection rate limiting
                now = time.monotonic()
                if now - _rate_window_start > 60:
                    _msg_count = 0
                    _rate_window_start = now
                _msg_count += 1
                if _msg_count > _MAX_MESSAGES_PER_MINUTE:
                    await websocket.send_json({
                        'type': 'error',
                        'message': 'Zu viele Nachrichten. Bitte warte einen Moment.',
                    })
                    continue

                # H-1: Prompt-injection protection before any LLM processing
                sanitized = sanitize_user_message(text)
                if sanitized.is_blocked:
                    logger.warning(
                        'BLOCKED prompt injection from user=%s score=%.2f patterns=%s',
                        user_id, sanitized.risk_score, sanitized.detected_patterns,
                    )
                    await websocket.send_json({
                        'type': 'message_complete',
                        'text': 'Ich kann diese Nachricht leider nicht verarbeiten.',
                        'case_ref': None,
                        'context_type': 'none',
                        'suggestions': _DEFAULT_SUGGESTIONS,
                        'content_blocks': [],
                        'actions': [],
                    })
                    continue
                if sanitized.is_suspected:
                    logger.warning(
                        'SUSPECTED prompt injection from user=%s score=%.2f patterns=%s',
                        user_id, sanitized.risk_score, sanitized.detected_patterns,
                    )
                text = sanitized.cleaned_text

                # Typing indicator ON with hint
                await websocket.send_json({
                    'type': 'typing',
                    'active': True,
                    'hint': _GENERIC_TYPING_HINT,
                })

                try:
                    # --- Phase 1: TieredOrchestrator intent routing ---
                    quick_action = data.get('quick_action')
                    tier_intent = None
                    tier_routing = None
                    orchestrator = _get_tiered_orchestrator()
                    if orchestrator:
                        try:
                            routing_result = await orchestrator.route(
                                message=text, quick_action=quick_action,
                            )
                            tier_intent = routing_result.get('intent')
                            tier_routing = routing_result.get('routing')
                            logger.info('TieredOrchestrator: intent=%s routing=%s', tier_intent, tier_routing)
                        except Exception as exc:
                            logger.warning('TieredOrchestrator failed, falling back: %s', exc)

                    # --- Phase 2: Communicator (always, for natural-language reply) ---
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

                    # --- Name-update side-effect ---
                    extracted_name = _extract_name_intent(text)
                    if extracted_name:
                        await _persist_display_name(user_id, tenant_id, extracted_name)

                    # --- Determine context_type ---
                    # Prefer TieredOrchestrator intent, then communicator, then keywords
                    if tier_intent and tier_intent in _TIER_INTENT_TO_CONTEXT:
                        context_type = _TIER_INTENT_TO_CONTEXT[tier_intent]
                    else:
                        comm_intent = getattr(result, 'intent', None) if result else None
                        context_type = (
                            INTENT_TO_CONTEXT.get(comm_intent, 'none')
                            if comm_intent
                            else _detect_context_type(text)
                        )

                    # Send ui_hint before message_complete when relevant.
                    if context_type != 'none':
                        await websocket.send_json({
                            'type': 'ui_hint',
                            'action': 'open_context',
                            'context_type': context_type,
                        })

                    # --- Phase 3: Fetch data for content_blocks via ServiceRegistry ---
                    agent_results: dict = {}
                    if tier_intent and tier_routing in ('regex', 'fast', 'action_router'):
                        try:
                            from app.agents.service_registry import build_service_registry
                            _intent_to_service = {
                                'SHOW_INBOX': ('inbox_service', 'list_pending'),
                                'SHOW_FINANCE': ('euer_service', 'get_finance_summary'),
                                'SHOW_DEADLINES': ('deadline_service', 'list'),
                                'SHOW_BOOKINGS': ('booking_service', 'list'),
                                'SHOW_OPEN_ITEMS': ('open_item_service', 'list'),
                                'SHOW_CONTACT': ('contact_service', 'get_dossier'),
                                'SETTINGS': ('settings_service', 'get'),
                            }
                            svc_info = _intent_to_service.get(tier_intent)
                            if svc_info:
                                registry = build_service_registry()
                                svc = registry.get(svc_info[0])
                                if svc:
                                    method = getattr(svc, svc_info[1], None)
                                    if method:
                                        agent_results = await method() or {}
                        except Exception as exc:
                            logger.warning('Service data fetch failed: %s', exc)

                    # --- Phase 4: ResponseBuilder (content_blocks + actions) ---
                    content_blocks: list = []
                    actions: list = []
                    rb = _get_response_builder()
                    if rb and tier_intent:
                        try:
                            enhanced = rb.build(
                                intent=tier_intent,
                                agent_results=agent_results,
                                communicator_text=reply_text,
                            )
                            content_blocks = enhanced.get('content_blocks', [])
                            actions = enhanced.get('actions', [])
                        except Exception as exc:
                            logger.warning('ResponseBuilder failed: %s', exc)

                    # --- Strip "FRYA:" prefix from reply text ---
                    if reply_text:
                        reply_text = re.sub(r'^FRYA:\s*', '', reply_text)

                    # Build final response (backward-compatible + new fields)
                    suggestions = (
                        [a['chat_text'] for a in actions[:3]]
                        if actions
                        else _DEFAULT_SUGGESTIONS
                    )

                    await websocket.send_json({
                        'type': 'message_complete',
                        'text': reply_text,
                        'case_ref': case_ref,
                        'context_type': context_type,
                        'suggestions': suggestions,
                        'content_blocks': content_blocks,
                        'actions': actions,
                        'routing': tier_routing,
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

            # ── Form submit ─────────────────────────────────────────────
            if msg_type == 'form_submit':
                form_type = data.get('form_type', '')
                form_data = data.get('data', {})
                logger.info('Form submit: type=%s user=%s', form_type, user_id)
                try:
                    from app.services.form_handlers import (
                        handle_invoice_form, handle_contact_form, handle_settings_form,
                    )
                    rb = _get_response_builder()
                    if form_type == 'invoice':
                        result = await handle_invoice_form(form_data, user_id)
                        text = f'FRYA: Rechnung {result.get("invoice_number","?")} erstellt ({result.get("gross_total","?")}€, Entwurf).'
                    elif form_type == 'contact':
                        result = await handle_contact_form(form_data, user_id)
                        text = f'FRYA: Kontakt {form_data.get("name","?")} gespeichert.'
                    elif form_type == 'settings':
                        result = await handle_settings_form(form_data, user_id)
                        text = 'FRYA: Einstellungen gespeichert.'
                    else:
                        result = {}
                        text = f'FRYA: Formular "{form_type}" wird noch nicht unterstützt.'

                    response: dict = {
                        'type': 'message_complete',
                        'text': text,
                        'content_blocks': [],
                        'actions': [],
                        'suggestions': _DEFAULT_SUGGESTIONS,
                        'context_type': 'none',
                    }
                    if rb:
                        enhanced = rb.build(f'SUBMIT_{form_type.upper()}', result, text)
                        response['content_blocks'] = enhanced.get('content_blocks', [])
                        response['actions'] = enhanced.get('actions', [])
                    await websocket.send_json(response)
                except Exception as exc:
                    logger.exception('form_submit error: %s', exc)
                    await websocket.send_json({
                        'type': 'error',
                        'message': 'Formular konnte nicht verarbeitet werden. Bitte versuche es erneut.',
                    })
                continue

            # ── Unknown frame type — silently ignore, never show to user ──
            logger.warning('Ignoring unknown WS frame: type=%s keys=%s', msg_type, list(data.keys()))

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
