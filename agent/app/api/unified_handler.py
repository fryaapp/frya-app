"""Unified Message Handler — pure function, kein WebSocket, kein I/O-Transport.

Extrahiert aus chat_ws.py (af9bffe) — alle Intent-Shortcircuits, Pending-Flows,
Communicator, ResponseBuilder und Redis-Pending-Action-Logik in einer einzigen
async-Funktion ohne Seiteneffekte auf den Transport-Layer.

Rueckgabe ist immer ein dict, das der Caller (WS oder REST) in sein eigenes
Protokoll verpackt.

P-Regeln (Pflicht):
  P1: _resolve_pending_conflict() — pending_invoice gewinnt ueber pending_action
  P2: _is_confirmation_with_modification() — "Ja, aber aendere..." != Confirmation
  P3: JEDE Redis-Operation in try/except, NIE re-raisen
  P4: get_session_id() deterministisch
  P5: _atomic_get_and_delete() fuer Pending-Cleanup

Sub-Handler in _handler_intents.py ausgelagert (500-Zeilen-Regel).
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any

from app.core.intents import Intent, parse_intent

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants (mirrored from chat_ws.py for decoupling)
# ---------------------------------------------------------------------------

_DEFAULT_SUGGESTIONS: list[str] = [
    'Was gibt es Neues?',
    'Zeig mir offene Posten',
    'Hilfe',
]

_TIER_INTENT_TO_CONTEXT: dict[str, str] = {
    Intent.SHOW_INBOX: 'inbox',
    Intent.SHOW_FINANCE: 'finance',
    Intent.SHOW_FINANCIAL_OVERVIEW: 'finance',
    Intent.SHOW_DEADLINES: 'deadlines',
    Intent.SHOW_BOOKINGS: 'bookings',
    Intent.SHOW_OPEN_ITEMS: 'open_items',
    Intent.SHOW_CONTACT: 'contact_card',
    Intent.SHOW_CONTACTS: 'contact_card',
    Intent.SHOW_EXPORT: 'finance',
    Intent.CREATE_INVOICE: 'invoice_draft',
    Intent.SHOW_INVOICE: 'invoice_draft',
    Intent.SEND_INVOICE: 'none',
    Intent.VOID_INVOICE: 'none',
    Intent.EDIT_INVOICE: 'invoice_draft',
    Intent.CHOOSE_TEMPLATE: 'none',
    Intent.SET_TEMPLATE: 'none',
    Intent.UPLOAD_LOGO: 'none',
    Intent.CREATE_CONTACT: 'contact_card',
    Intent.CREATE_REMINDER: 'deadlines',
    Intent.SETTINGS: 'settings',
    Intent.UPLOAD: 'upload_status',
    Intent.STATUS_OVERVIEW: 'none',
    Intent.SMALL_TALK: 'none',
    Intent.APPROVE: 'inbox',
    Intent.SHOW_EXPENSE_CATEGORIES: 'finance',
    Intent.SHOW_PROFIT_LOSS: 'finance',
    Intent.SHOW_REVENUE_TREND: 'finance',
    Intent.SHOW_FORECAST: 'finance',
}

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

_THEME_MAP: dict[str, str] = {
    'dunkelmodus': 'dark', 'dark mode': 'dark', 'dunkel': 'dark',
    'nachtmodus': 'dark', 'dunkler modus': 'dark',
    'heller modus': 'light', 'light mode': 'light', 'hell': 'light',
    'hellmodus': 'light', 'tagmodus': 'light', 'helles design': 'light',
}

_CANCEL_KEYWORDS = (
    'abbrech', 'vergiss', 'nein', 'stop', 'cancel',
    'aufhoeren', 'nicht mehr', 'lass es', 'skip', 'ignorier',
)

_CONFIRMATION_WORDS = frozenset({
    'ja', 'jo', 'jep', 'jap', 'jup', 'yes', 'ok', 'okay', 'oke',
    'genau', 'stimmt', 'richtig', 'korrekt', 'passt', 'perfekt',
    'mach', 'mach das', 'tu das', 'los', 'go', 'weiter',
    'ja bitte', 'ja genau', 'ja danke', 'ja mach', 'ja klar',
    'in ordnung', 'alles klar', 'einverstanden', 'gerne',
    'ja gerne', 'bitte', 'ja bitte mach das',
})

_REJECTION_WORDS = frozenset({
    'nein', 'nee', 'ne', 'noe', 'nicht', 'stop', 'stopp',
    'abbrechen', 'cancel', 'lass', 'lass das', 'vergiss es',
    'doch nicht', 'lieber nicht', 'nein danke',
})

_CHART_SHORTCIRCUIT_INTENTS = frozenset({
    Intent.SHOW_FINANCIAL_OVERVIEW, Intent.SHOW_FINANCE, Intent.SHOW_INBOX,
    Intent.SHOW_BOOKINGS, Intent.SHOW_OPEN_ITEMS, Intent.SHOW_DEADLINES,
    Intent.SHOW_EXPENSE_CATEGORIES, Intent.SHOW_PROFIT_LOSS,
    Intent.SHOW_REVENUE_TREND, Intent.SHOW_FORECAST, Intent.PROCESS_INBOX,
})


# ---------------------------------------------------------------------------
# P4: Deterministic session ID
# ---------------------------------------------------------------------------

def get_session_id(user_id: str, tenant_id: str) -> str:
    """P4: Deterministisch — gleicher User+Tenant = gleiche Session."""
    return f'web-{user_id}-{tenant_id}'


# ---------------------------------------------------------------------------
# P5: Atomic get-and-delete for Redis pending data
# ---------------------------------------------------------------------------

async def _atomic_get_and_delete(redis_conn: Any, key: str) -> str | None:
    """P5: Atomares Lesen+Loeschen einer Redis-Key."""
    # P3: Jede Redis-Op in try/except
    try:
        pipe = redis_conn.pipeline(transaction=True)
        pipe.get(key)
        pipe.delete(key)
        results = await pipe.execute()
        return results[0]
    except Exception as exc:
        logger.debug('_atomic_get_and_delete failed for %s: %s', key, exc)
        return None


# ---------------------------------------------------------------------------
# P1: Pending-Conflict Resolution
# ---------------------------------------------------------------------------

def _resolve_pending_conflict(
    pending_flow: dict | None,
    pending_action_raw: str | None,
) -> tuple[dict | None, dict | None]:
    """P1: pending_invoice (Flow) gewinnt ueber pending_action."""
    pa_data = None
    if pending_action_raw:
        try:
            pa_data = json.loads(pending_action_raw)
        except (json.JSONDecodeError, TypeError):
            pa_data = None
    if pending_flow and pa_data:
        logger.debug('P1: pending_flow wins over pending_action')
        return pending_flow, None
    return pending_flow, pa_data


# ---------------------------------------------------------------------------
# P2: Confirmation-with-modification detection
# ---------------------------------------------------------------------------

def _is_confirmation_with_modification(text: str) -> bool:
    """P2: 'Ja, aber aendere den Betrag' ist KEINE Confirmation."""
    _mod_markers = (
        'aber', 'allerdings', 'jedoch', 'ausser', 'nur',
        'aender', 'änder', 'statt', 'anstatt', 'change',
        'mit anderem', 'mit anderer', 'anderen betrag',
    )
    lower = text.lower().strip()
    starts_confirm = any(lower.startswith(w) for w in ('ja', 'ok', 'gut', 'passt'))
    has_mod = any(m in lower for m in _mod_markers)
    return starts_confirm and has_mod


# ---------------------------------------------------------------------------
# Redis helper (lazy init, P3: never raises)
# ---------------------------------------------------------------------------

_redis_conn = None


async def _get_redis():
    """Lazy Redis connection — P3: never raises."""
    global _redis_conn
    if _redis_conn is None:
        try:
            import redis.asyncio as aioredis
            from app.config import get_settings
            _redis_conn = aioredis.Redis.from_url(
                get_settings().redis_url, decode_responses=True,
            )
        except Exception as exc:
            logger.debug('Redis init failed: %s', exc)
            return None
    return _redis_conn


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _detect_context_type(user_text: str) -> str:
    """Keyword-based fallback for context_type detection."""
    text = user_text.lower()
    if any(w in text for w in ('frist', 'deadline', 'faellig', 'termin')):
        return 'deadlines'
    if any(w in text for w in ('euer', 'einnahmen', 'ausgaben', 'finanzen', 'bilanz')):
        return 'finance'
    if any(w in text for w in ('inbox', 'beleg', 'rechnung', 'offene')):
        return 'inbox'
    if any(w in text for w in ('buchung', 'journal', 'konto')):
        return 'bookings'
    if any(w in text for w in ('upload', 'hochladen')):
        return 'upload_status'
    if any(w in text for w in ('kontakt', 'lieferant', 'kunde')):
        return 'contact_card'
    return 'none'


def _make_suggestions(actions: list[dict]) -> list[str]:
    """Extract chat_text from first 3 actions, fallback to defaults."""
    if actions:
        texts = [a['chat_text'] for a in actions[:3] if a.get('chat_text')]
        if texts:
            return texts
    return list(_DEFAULT_SUGGESTIONS)


def _build_response(
    text: str = '',
    content_blocks: list | None = None,
    actions: list | None = None,
    case_ref: str | None = None,
    context_type: str = 'none',
    routing: str | None = None,
    suggestions: list[str] | None = None,
    next_pending_flow: dict | None = None,
    settings_changed: dict | None = None,
) -> dict:
    """Construct the canonical response dict."""
    _actions = actions or []
    return {
        'text': text,
        'content_blocks': content_blocks or [],
        'actions': _actions,
        'case_ref': case_ref,
        'context_type': context_type,
        'routing': routing,
        'suggestions': suggestions or _make_suggestions(_actions),
        'next_pending_flow': next_pending_flow,
        'settings_changed': settings_changed,
    }


def _save_history(user_id: str, user_text: str, reply_text: str) -> None:
    """Fire-and-forget chat history append. P3: never raises."""
    try:
        import asyncio
        from app.dependencies import get_chat_history_store
        store = get_chat_history_store()
        if store and reply_text:
            asyncio.ensure_future(store.append(f'web-{user_id}', user_text, reply_text))
    except Exception as exc:
        logger.debug('History append failed: %s', exc)


# Singleton caches
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


async def _get_communicator_reply(text: str, user_id: str, tenant_id: str):
    """Run communicator pipeline and return CommunicatorResult."""
    from app.dependencies import (
        get_audit_service, get_chat_history_store,
        get_communicator_conversation_store, get_communicator_user_store,
        get_llm_config_repository, get_open_items_service,
        get_telegram_clarification_service, get_telegram_communicator_service,
    )
    from app.telegram.models import TelegramActor, TelegramNormalizedIngressMessage

    _evt_id = f'web-evt-{uuid.uuid4().hex[:12]}'
    normalized = TelegramNormalizedIngressMessage(
        event_id=_evt_id,
        text=text,
        telegram_update_ref=f'web-update-{_evt_id}',
        telegram_message_ref=f'web-msg-{_evt_id}',
        telegram_chat_ref=f'web:{user_id}',
        actor=TelegramActor(
            chat_id=f'web-{user_id}',
            sender_id=user_id,
            sender_username=user_id,
        ),
        media_attachments=[],
    )
    case_id = f'web-{user_id}-{uuid.uuid4().hex[:8]}'
    service = get_telegram_communicator_service()
    return await service.try_handle_turn(
        normalized, case_id,
        audit_service=get_audit_service(),
        open_items_service=get_open_items_service(),
        clarification_service=get_telegram_clarification_service(),
        conversation_store=get_communicator_conversation_store(),
        user_store=get_communicator_user_store(),
        llm_config_repository=get_llm_config_repository(),
        chat_history_store=get_chat_history_store(),
    )


async def _persist_preference(user_id: str, tenant_id: str, key: str, value: str) -> None:
    """Write preference to frya_user_preferences. P3: never raises."""
    try:
        from app.dependencies import get_settings
        db_url = get_settings().database_url
        if db_url.startswith('memory://'):
            return
        import asyncpg
        conn = await asyncpg.connect(db_url)
        try:
            await conn.execute('''
                INSERT INTO frya_user_preferences (tenant_id, user_id, key, value, updated_at)
                VALUES ($1, $2, $3, $4, NOW())
                ON CONFLICT (tenant_id, user_id, key) DO UPDATE
                  SET value = EXCLUDED.value, updated_at = NOW()
            ''', tenant_id, user_id, key, value)
        finally:
            await conn.close()
    except Exception as exc:
        logger.warning('Failed to persist preference %s: %s', key, exc)


async def _run_business_info_extraction(text: str, user_id: str, tenant_id: str) -> None:
    """Extract business info. Delegates to chat_ws. P3: never raises."""
    try:
        from app.api.chat_ws import _extract_and_persist_business_info
        await _extract_and_persist_business_info(text, user_id, tenant_id)
    except Exception as exc:
        logger.warning('Business info extraction failed: %s', exc)


# ---------------------------------------------------------------------------
# MAIN ENTRY POINT
# ---------------------------------------------------------------------------

async def handle_user_message(
    message: str,
    tenant_id: str,
    user_id: str,
    session_id: str,
    quick_action: dict | None = None,
    pending_flow: dict | None = None,
) -> dict:
    """Verarbeitet eine User-Nachricht und gibt ein Response-Dict zurueck.

    REINE Funktion — kein websocket.send_json, kein typing indicator,
    kein Connection-State. Der Caller ist verantwortlich fuer Transport.
    """
    # Import sub-handlers (ausgelagert fuer 500-Zeilen-Regel)
    from app.api._handler_intents import (
        handle_approve, handle_cancel_invoice, handle_change_ku_status,
        handle_chart_shortcircuit, handle_invoice_draft_review,
        handle_pending_action, handle_show_case, handle_show_contacts,
        handle_show_invoice,
    )

    text = message

    # === Phase 0: Pending-Flow Resume (P-10 A3) ===
    if pending_flow and isinstance(pending_flow, dict):
        pf_type = pending_flow.get('waiting_for')
        pf_invoice_id = pending_flow.get('invoice_id')
        pf_data = pending_flow.get('pending_data', {})

        if any(kw in text.lower() for kw in _CANCEL_KEYWORDS):
            _save_history(user_id, text, 'Vorgang abgebrochen.')
            return _build_response(
                text='Alles klar, ich habe den Vorgang abgebrochen. Was kann ich sonst fuer dich tun?',
                routing='cancel',
            )

        if pf_type == 'recipient_email' and pf_invoice_id:
            from app.services.invoice_pipeline import handle_send_invoice
            r = await handle_send_invoice(
                {'invoice_id': pf_invoice_id, 'recipient_email': text.strip()},
                user_id, tenant_id=tenant_id,
            )
            _save_history(user_id, text, r.get('text', ''))
            return _build_response(
                text=r.get('text', ''), content_blocks=r.get('content_blocks', []),
                actions=r.get('actions', []), routing='pending_flow',
            )

        if pf_type == 'company_profile_wizard' and pf_data:
            await _run_business_info_extraction(text, user_id, tenant_id)
            from app.services.invoice_pipeline import handle_create_invoice
            r = await handle_create_invoice(pf_data, user_id, tenant_id=tenant_id)
            npf = None
            if r.get('_waiting_for') == 'company_profile_wizard':
                npf = {'waiting_for': 'company_profile_wizard', 'pending_data': r.get('_pending_data', pf_data)}
            elif r.get('awaiting_email_for_invoice'):
                npf = {'waiting_for': 'recipient_email', 'invoice_id': r['awaiting_email_for_invoice'], 'pending_data': pf_data}
            _save_history(user_id, text, r.get('text', ''))
            return _build_response(
                text=r.get('text', ''), content_blocks=r.get('content_blocks', []),
                actions=r.get('actions', []), context_type=r.get('context_type', 'none'),
                routing='pending_flow', next_pending_flow=npf,
            )

        if pf_type == 'recipient_address' and pf_data:
            pf_data['contact_address'] = text.strip()
            from app.services.invoice_pipeline import handle_create_invoice
            r = await handle_create_invoice(pf_data, user_id, tenant_id=tenant_id)
            npf = None
            if r.get('_pending_intent'):
                npf = {'waiting_for': 'recipient_address', 'pending_data': r.get('_pending_data', pf_data)}
            _save_history(user_id, text, r.get('text', ''))
            return _build_response(
                text=r.get('text', ''), content_blocks=r.get('content_blocks', []),
                actions=r.get('actions', []), context_type=r.get('context_type', 'invoice_draft'),
                routing='pending_flow', next_pending_flow=npf,
            )

        if pf_type == 'invoice_draft_review' and pf_invoice_id:
            return await handle_invoice_draft_review(text, pf_invoice_id, pf_data, user_id, tenant_id)

    # === Phase 0b: Pending Action Confirmation (P-43 Fix D) ===
    cleaned_msg = text.lower().strip().rstrip('.!?')
    # P2: "Ja, aber aendere..." ist KEINE Confirmation
    is_confirm = cleaned_msg in _CONFIRMATION_WORDS and not _is_confirmation_with_modification(text)
    is_reject = cleaned_msg in _REJECTION_WORDS

    if is_confirm or is_reject:
        pa_result = await handle_pending_action(text, tenant_id, user_id, is_confirm)
        if pa_result is not None:
            return pa_result

    # === Phase 1: TieredOrchestrator intent routing ===
    if quick_action and isinstance(quick_action, dict):
        qa_params = quick_action.get('params', {})
        qa_params['user_id'] = user_id
        qa_params['tenant_id'] = tenant_id
        quick_action['params'] = qa_params

    tier_intent = None
    tier_routing = None
    routing_result: dict = {}
    orchestrator = _get_tiered_orchestrator()
    if orchestrator:
        try:
            routing_result = await orchestrator.route(message=text, quick_action=quick_action)
            tier_intent = routing_result.get('intent')
            tier_routing = routing_result.get('routing')
        except Exception as exc:
            logger.warning('TieredOrchestrator failed: %s', exc)

    # Phase 1a: ActionRouter short-circuit
    if tier_routing == 'action_router' and isinstance(routing_result.get('result'), dict):
        ar = routing_result['result']
        _save_history(user_id, text, ar.get('text', ''))
        return _build_response(
            text=ar.get('text', ''), content_blocks=ar.get('content_blocks', []),
            actions=ar.get('actions', []), context_type=ar.get('context_type', 'none'),
            routing='action_router',
        )

    # === Phase 1b: Intent shortcircuits ===
    sc_reply: str | None = None
    sc_data: dict = {}
    theme_changed: str | None = None

    if tier_intent == Intent.APPROVE:
        sc_reply, sc_data = await handle_approve(text, quick_action, tenant_id)
    elif tier_intent == Intent.UPLOAD:
        sc_reply = 'Zum Hochladen nutze das Bueroklammer-Symbol unten oder ziehe Dateien direkt in den Chat.'
    elif tier_intent == Intent.CHOOSE_TEMPLATE:
        sc_reply = 'Wie sollen deine Rechnungen aussehen? Hier sind drei Vorlagen:'
    elif tier_intent == Intent.SET_TEMPLATE:
        chosen = 'professional' if 'professional' in text.lower() else ('minimal' if 'minimal' in text.lower() else 'clean')
        await _persist_preference(user_id, tenant_id, 'invoice_template', chosen)
        _tpl_titles = {'clean': 'Clean', 'professional': 'Professional', 'minimal': 'Minimal'}
        sc_reply = f'Rechnungs-Template auf "{_tpl_titles[chosen]}" geaendert.'
    elif tier_intent == Intent.UPLOAD_LOGO:
        sc_reply = 'Schick mir einfach dein Logo als Bild (PNG, JPG oder SVG). Nutze das Bueroklammer-Symbol unten links.'
    elif tier_intent == Intent.SHOW_CONTACTS:
        sc_reply, sc_data = await handle_show_contacts(tenant_id)
    elif tier_intent == Intent.SETTINGS:
        for trigger, theme in _THEME_MAP.items():
            if trigger in text.lower():
                await _persist_preference(user_id, tenant_id, 'theme', theme)
                theme_changed = theme
                sc_reply = f'Design auf "{"Dunkel" if theme == "dark" else "Hell"}" umgestellt.'
                break

    if tier_intent == Intent.CHANGE_KU_STATUS:
        sc_reply = await handle_change_ku_status(text, user_id, tenant_id)
    if tier_intent == Intent.CANCEL_INVOICE:
        sc_reply, sc_data = await handle_cancel_invoice(text, tenant_id, user_id)
    if tier_intent == Intent.SHOW_CASE:
        sc_reply, sc_data = await handle_show_case(routing_result, quick_action)
    if tier_intent == Intent.SHOW_INVOICE:
        inv_resp = await handle_show_invoice(text, tenant_id)
        if inv_resp is not None:
            _save_history(user_id, text, inv_resp.get('text', ''))
            return inv_resp

    if sc_reply is None and tier_intent in _CHART_SHORTCIRCUIT_INTENTS:
        sc_reply, sc_data = await handle_chart_shortcircuit(tier_intent, tenant_id)

    if sc_reply is not None:
        ctx = _TIER_INTENT_TO_CONTEXT.get(tier_intent, 'none')
        sc_blocks: list = []
        sc_actions: list = []
        if sc_data and tier_intent:
            try:
                from app.agents.response_builder import ResponseBuilder
                rb = ResponseBuilder()
                built = rb.build(tier_intent, sc_data, sc_reply)
                sc_blocks = built.get('content_blocks', [])
                sc_actions = built.get('actions', [])
            except Exception:
                pass
            raw_a = sc_data.get('actions', [])
            if raw_a and any(a.get('quick_action') for a in raw_a):
                sc_actions = raw_a
        _save_history(user_id, text, sc_reply)
        return _build_response(
            text=sc_reply, content_blocks=sc_blocks, actions=sc_actions,
            context_type=ctx, routing=tier_routing,
            settings_changed={'theme': theme_changed} if theme_changed else None,
        )

    # === Phase 2: Communicator ===
    result = await _get_communicator_reply(text, user_id, tenant_id)
    llm_suggestions: list = []
    case_ref: str | None = None
    if result and result.handled:
        reply_text = result.reply_text
        llm_suggestions = getattr(result, 'llm_suggestions', []) or []
        case_ref = result.turn.context_resolution.resolved_case_ref if result.turn.context_resolution else None
    else:
        reply_text = 'Entschuldigung, ich konnte deine Nachricht gerade nicht verarbeiten. Bitte versuche es erneut.'

    # Side-effects
    try:
        from app.api.chat_ws import _extract_name_intent
        name = _extract_name_intent(text)
        if name:
            from app.api.chat_ws import _persist_display_name
            await _persist_display_name(user_id, tenant_id, name)
    except Exception:
        pass
    await _run_business_info_extraction(text, user_id, tenant_id)

    # Context type
    if tier_intent and tier_intent in _TIER_INTENT_TO_CONTEXT:
        context_type = _TIER_INTENT_TO_CONTEXT[tier_intent]
    else:
        ci = getattr(result, 'intent', None) if result else None
        context_type = INTENT_TO_CONTEXT.get(ci, 'none') if ci else _detect_context_type(text)

    # === Phase 3: ServiceRegistry data fetch ===
    agent_results: dict = {}
    if tier_intent and tier_routing in ('regex', 'fast', 'action_router'):
        try:
            from app.agents.service_registry import build_service_registry
            svc_map = {
                Intent.SHOW_INBOX: ('inbox_service', 'list_pending'),
                Intent.PROCESS_INBOX: ('inbox_service', 'process_first'),
                Intent.SHOW_FINANCE: ('euer_service', 'get_finance_summary'),
                Intent.SHOW_DEADLINES: ('deadline_service', 'list'),
                Intent.SHOW_BOOKINGS: ('booking_service', 'list'),
                Intent.SHOW_OPEN_ITEMS: ('open_item_service', 'list'),
                Intent.SHOW_CONTACT: ('contact_service', 'get_dossier'),
                Intent.SETTINGS: ('settings_service', 'get'),
            }
            si = svc_map.get(tier_intent)
            if si:
                reg = build_service_registry()
                svc = reg.get(si[0])
                if svc:
                    m = getattr(svc, si[1], None)
                    if m:
                        agent_results = await m(tenant_id=tenant_id) or {}
        except Exception as exc:
            logger.warning('Service data fetch failed: %s', exc)

    if tier_intent == Intent.SHOW_INBOX and 'alle' in text.lower() and ('zeig' in text.lower() or 'beleg' in text.lower()):
        agent_results['show_all'] = True

    # === Phase 4: ResponseBuilder ===
    content_blocks: list = []
    actions: list = []
    rb = _get_response_builder()
    if rb and tier_intent:
        try:
            enhanced = rb.build(intent=tier_intent, agent_results=agent_results, communicator_text=reply_text, llm_suggestions=llm_suggestions)
            content_blocks = enhanced.get('content_blocks', [])
            actions = enhanced.get('actions', [])
        except Exception as exc:
            logger.warning('ResponseBuilder failed: %s', exc)

    if reply_text:
        reply_text = re.sub(r'^FRYA:\s*', '', reply_text)

    # === Phase 2b: Invoice Pipeline ===
    next_pf: dict | None = None
    inv_data = getattr(result, 'invoice_data', None) if result else None
    if inv_data and isinstance(inv_data, dict):
        try:
            from app.services.invoice_pipeline import handle_create_invoice
            pr = await handle_create_invoice(inv_data, user_id, tenant_id=tenant_id)
            reply_text = pr.get('text', reply_text)
            content_blocks = pr.get('content_blocks', [])
            actions = pr.get('actions', [])
            context_type = pr.get('context_type', 'invoice_draft')
            if pr.get('_pending_intent'):
                pd = pr.get('_pending_data', inv_data)
                if pr.get('awaiting_email_for_invoice'):
                    next_pf = {'waiting_for': 'recipient_email', 'invoice_id': pr['awaiting_email_for_invoice'], 'pending_data': pd}
                elif pr.get('_waiting_for') == 'company_profile_wizard':
                    next_pf = {'waiting_for': 'company_profile_wizard', 'pending_data': pd}
                else:
                    next_pf = {'waiting_for': 'recipient_address', 'pending_data': pd}
            else:
                did = pr.get('invoice_id')
                if did:
                    next_pf = {'waiting_for': 'invoice_draft_review', 'invoice_id': did, 'pending_data': inv_data}
        except Exception as exc:
            logger.error('Invoice pipeline failed: %s', exc)
            reply_text = f'Rechnung konnte nicht erstellt werden: {exc}'

    # Phase 2c: ActionRouter pipeline
    if tier_routing == 'action_router' and isinstance(agent_results, dict):
        pr2 = agent_results.get('result', {})
        if isinstance(pr2, dict) and pr2.get('content_blocks'):
            content_blocks = pr2['content_blocks']
            actions = pr2.get('actions', [])
            reply_text = pr2.get('text', reply_text)
            context_type = pr2.get('context_type', context_type)
        if isinstance(pr2, dict) and pr2.get('awaiting_email_for_invoice'):
            next_pf = {'waiting_for': 'recipient_email', 'invoice_id': pr2['awaiting_email_for_invoice'], 'pending_data': {}}

    # Text-Sync: SHOW_INBOX
    if tier_intent == Intent.SHOW_INBOX and content_blocks:
        ic = sum(len(b.get('data', {}).get('items', [])) for b in content_blocks if b.get('block_type') == 'card_list')
        if ic > 0:
            reply_text = f'{agent_results.get("count", ic)} Belege warten auf deine Freigabe.'
        elif not any(b.get('block_type') == 'alert' for b in content_blocks):
            reply_text = 'Deine Inbox ist leer — aktuell keine neuen Dokumente.'

    # P-43 Fix D: pending_action storage
    _pa_pats = [
        r'soll ich.+(?:buchen|umbuchen|freigeben|stornieren|loeschen|löschen|ändern|aendern)',
        r'moechtest du.+(?:buchen|umbuchen|freigeben|stornieren)',
        r'darf ich.+(?:buchen|umbuchen|freigeben)',
    ]
    if case_ref and any(re.search(p, reply_text.lower()) for p in _pa_pats):
        try:
            rc = await _get_redis()
            if rc:
                pk = f'frya:pending_action:{tenant_id or user_id}'
                await rc.set(pk, json.dumps({
                    'action': 'confirm_proposed', 'case_ref': case_ref,
                    'original_text': reply_text[:200], 'confirm_text': reply_text[:200], 'params': {},
                }), ex=300)
        except Exception:
            pass  # P3

    _save_history(user_id, text, reply_text)
    return _build_response(
        text=reply_text, content_blocks=content_blocks, actions=actions,
        case_ref=case_ref, context_type=context_type, routing=tier_routing,
        next_pending_flow=next_pf,
    )
