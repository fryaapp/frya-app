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
# Global WebSocket connection registry for push notifications
# ---------------------------------------------------------------------------

class _ChatConnectionRegistry:
    """Track active chat WebSocket connections for server-push notifications.

    Used by the Paperless webhook to notify clients when new documents
    have been processed and appear in the inbox.
    """

    def __init__(self) -> None:
        self._connections: dict[str, WebSocket] = {}

    def register(self, user_id: str, ws: WebSocket) -> None:
        self._connections[user_id] = ws

    def unregister(self, user_id: str) -> None:
        self._connections.pop(user_id, None)

    async def broadcast(self, message: dict) -> None:
        """Send a JSON message to all connected clients."""
        dead: list[str] = []
        for uid, ws in self._connections.items():
            try:
                if ws.client_state == WebSocketState.CONNECTED:
                    await ws.send_json(message)
                else:
                    dead.append(uid)
            except Exception:
                dead.append(uid)
        for uid in dead:
            self._connections.pop(uid, None)

    async def send_to_user(self, user_id: str, message: dict) -> None:
        ws = self._connections.get(user_id)
        if ws:
            try:
                if ws.client_state == WebSocketState.CONNECTED:
                    await ws.send_json(message)
            except Exception:
                self._connections.pop(user_id, None)


chat_registry = _ChatConnectionRegistry()

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
    'SHOW_CONTACTS': 'contact_card',
    'SHOW_EXPORT': 'finance',
    'CREATE_INVOICE': 'invoice_draft',
    'SHOW_INVOICE': 'invoice_draft',
    'SEND_INVOICE': 'none',
    'VOID_INVOICE': 'none',
    'EDIT_INVOICE': 'invoice_draft',
    'CHOOSE_TEMPLATE': 'none',
    'SET_TEMPLATE': 'none',
    'UPLOAD_LOGO': 'none',
    'CREATE_CONTACT': 'contact_card',
    'CREATE_REMINDER': 'deadlines',
    'SETTINGS': 'settings',
    'UPLOAD': 'upload_status',
    'STATUS_OVERVIEW': 'none',
    'SMALL_TALK': 'none',
    'APPROVE': 'inbox',
}


# ---------------------------------------------------------------------------
# Business info extraction — detects hourly rates, company data, etc.
# ---------------------------------------------------------------------------

import re

# Patterns for extractable business preferences
_RATE_PATTERNS = [
    re.compile(r'(?:mein\s+)?stundensatz\s+(?:ist|betr[aä]gt|liegt\s+bei)\s+(\d+(?:[.,]\d+)?)\s*(?:€|euro|eur)', re.IGNORECASE),
    re.compile(r'(\d+(?:[.,]\d+)?)\s*(?:€|euro|eur)\s+(?:pro\s+stunde|die\s+stunde|\/\s*h|\/stunde)', re.IGNORECASE),
    re.compile(r'(?:ich\s+(?:berechne|nehme|verlange))\s+(\d+(?:[.,]\d+)?)\s*(?:€|euro|eur)', re.IGNORECASE),
]

_COMPANY_NAME_PATTERNS = [
    re.compile(r'(?:mein(?:e)?\s+(?:firma|unternehmen|company)\s+(?:hei(?:ß|ss)t|ist|lautet)\s+)(.+?)(?:\.|,|$)', re.IGNORECASE),
    re.compile(r'(?:firma|unternehmen):\s*(.+?)(?:\.|,|$)', re.IGNORECASE),
]

_TAX_NUMBER_PATTERNS = [
    re.compile(r'(?:steuer(?:nummer|nr)[.:]?\s*)(\d{2,3}[/\s]\d{3,4}[/\s]\d{4,5})', re.IGNORECASE),
    re.compile(r'(?:ust[.-]?id(?:nr)?[.:]?\s*)(DE\d{9})', re.IGNORECASE),
]

_ADDRESS_PATTERNS = [
    re.compile(r'(?:adresse|anschrift)[.:]?\s*(.+?\d{5}\s+\w+)', re.IGNORECASE),
]

_KLEINUNTERNEHMER_PATTERNS = [
    re.compile(r'(?:ich\s+bin\s+)?kleinunternehmer', re.IGNORECASE),
    re.compile(r'§\s*19\s*ustg', re.IGNORECASE),
    re.compile(r'umsatzsteuerbefreit', re.IGNORECASE),
]

_IBAN_PATTERNS = [
    re.compile(r'(?:iban[.:]?\s*)?([A-Z]{2}\d{2}\s?\d{4}\s?\d{4}\s?\d{4}\s?\d{4}\s?\d{2,4})', re.IGNORECASE),
]

_BIC_PATTERNS = [
    re.compile(r'(?:bic|swift)[.:]?\s*([A-Z]{6}[A-Z0-9]{2,5})', re.IGNORECASE),
]

_COMPANY_EMAIL_PATTERNS = [
    re.compile(r'(?:geschäftlich|business|firma|unternehmens?)?[\s-]*e-?mail[.:]?\s*([\w.+-]+@[\w.-]+\.\w+)', re.IGNORECASE),
    re.compile(r'(?:mail|e-?mail)\s+(?:ist|lautet)\s+([\w.+-]+@[\w.-]+\.\w+)', re.IGNORECASE),
]

_STREET_PATTERNS = [
    re.compile(r'(?:straße|strasse|str\.?)[.:]?\s*(.+?\d+\s*[a-zA-Z]?)\s*(?:,|$)', re.IGNORECASE),
]

_ZIP_CITY_PATTERNS = [
    re.compile(r'(\d{5})\s+([A-ZÄÖÜ][a-zäöüß]+(?:\s+[a-zäöüß]+)*)', re.IGNORECASE),
]

_NEIN_KLEINUNTERNEHMER_PATTERNS = [
    re.compile(r'(?:nein|nicht|kein).*kleinunternehmer', re.IGNORECASE),
    re.compile(r'(?:nein|nicht).*§\s*19', re.IGNORECASE),
    re.compile(r'ganz\s+normal\s+mit\s+mwst', re.IGNORECASE),
]


async def _extract_and_persist_business_info(
    user_text: str, user_id: str, tenant_id: str,
) -> None:
    """Extract business info from user message and persist to preferences + user.md."""
    facts_to_learn: list[str] = []
    prefs_to_save: list[tuple[str, str]] = []

    # Hourly rate
    for pat in _RATE_PATTERNS:
        m = pat.search(user_text)
        if m:
            rate = m.group(1).replace(',', '.')
            prefs_to_save.append(('default_hourly_rate', rate))
            facts_to_learn.append(f'- Standard-Stundensatz: {rate} EUR')
            break

    # Company name
    for pat in _COMPANY_NAME_PATTERNS:
        m = pat.search(user_text)
        if m:
            name = m.group(1).strip().rstrip('.!?,;')
            if len(name) >= 3:
                prefs_to_save.append(('company_name', name))
                facts_to_learn.append(f'- Firmenname: {name}')
            break

    # Tax number
    for pat in _TAX_NUMBER_PATTERNS:
        m = pat.search(user_text)
        if m:
            tax_nr = m.group(1).strip()
            prefs_to_save.append(('tax_number', tax_nr))
            facts_to_learn.append(f'- Steuernummer/USt-IdNr: {tax_nr}')
            break

    # Address
    for pat in _ADDRESS_PATTERNS:
        m = pat.search(user_text)
        if m:
            addr = m.group(1).strip()
            prefs_to_save.append(('company_address', addr))
            facts_to_learn.append(f'- Geschaeftsadresse: {addr}')
            break

    # Kleinunternehmer (check "nein" first)
    _is_nein_klein = any(p.search(user_text) for p in _NEIN_KLEINUNTERNEHMER_PATTERNS)
    if _is_nein_klein:
        prefs_to_save.append(('kleinunternehmer', 'false'))
        facts_to_learn.append('- Kein Kleinunternehmer (normale MwSt)')
    else:
        for pat in _KLEINUNTERNEHMER_PATTERNS:
            if pat.search(user_text):
                prefs_to_save.append(('kleinunternehmer', 'true'))
                facts_to_learn.append('- Kleinunternehmer nach §19 UStG')
                break

    # IBAN
    for pat in _IBAN_PATTERNS:
        m = pat.search(user_text)
        if m:
            iban = m.group(1).strip().replace(' ', '')
            prefs_to_save.append(('company_iban', iban))
            # Mask IBAN in facts (privacy)
            masked = iban[:4] + '****' + iban[-4:]
            facts_to_learn.append(f'- IBAN: {masked}')
            break

    # BIC
    for pat in _BIC_PATTERNS:
        m = pat.search(user_text)
        if m:
            bic = m.group(1).strip()
            prefs_to_save.append(('company_bic', bic))
            facts_to_learn.append(f'- BIC: {bic}')
            break

    # Company email
    for pat in _COMPANY_EMAIL_PATTERNS:
        m = pat.search(user_text)
        if m:
            email = m.group(1).strip()
            prefs_to_save.append(('company_email', email))
            facts_to_learn.append(f'- Geschaeftliche E-Mail: {email}')
            break

    # Street (split address)
    for pat in _STREET_PATTERNS:
        m = pat.search(user_text)
        if m:
            street = m.group(1).strip().rstrip(',.')
            if len(street) >= 5:
                prefs_to_save.append(('company_street', street))
                facts_to_learn.append(f'- Strasse: {street}')
            break

    # PLZ + Ort (split address)
    for pat in _ZIP_CITY_PATTERNS:
        m = pat.search(user_text)
        if m:
            zip_city = f'{m.group(1)} {m.group(2)}'.strip()
            prefs_to_save.append(('company_zip_city', zip_city))
            facts_to_learn.append(f'- PLZ/Ort: {zip_city}')
            break

    if not prefs_to_save:
        return

    # Save to frya_user_preferences (legacy)
    for key, value in prefs_to_save:
        await _persist_preference(user_id, tenant_id, key, value)

    # ALSO save to frya_business_profile (new compliance source)
    try:
        from app.services.business_profile_service import BusinessProfileService
        _bp_svc = BusinessProfileService()
        _bp_map: dict[str, str] = {
            'company_name': 'company_name',
            'company_street': 'company_street',
            'company_zip_city': 'company_zip',  # split below
            'tax_number': 'tax_number',
            'kleinunternehmer': 'is_kleinunternehmer',
            'company_iban': 'company_iban',
            'company_bic': 'company_bic',
            'company_email': 'company_email',
            'company_phone': 'company_phone',
            'default_hourly_rate': 'default_hourly_rate',
        }
        for key, value in prefs_to_save:
            bp_field = _bp_map.get(key)
            if bp_field:
                if key == 'company_zip_city' and ' ' in str(value):
                    # Split "12345 Berlin" into zip + city
                    parts = str(value).split(' ', 1)
                    await _bp_svc.upsert_field(user_id, tenant_id, 'company_zip', parts[0])
                    await _bp_svc.upsert_field(user_id, tenant_id, 'company_city', parts[1])
                elif key == 'tax_number' and str(value).startswith('DE'):
                    # DE prefix means USt-IdNr, not Steuernummer
                    await _bp_svc.upsert_field(user_id, tenant_id, 'ust_id', value)
                else:
                    await _bp_svc.upsert_field(user_id, tenant_id, bp_field, value)
    except Exception as exc:
        logger.warning('BusinessProfile sync failed: %s', exc)

    # Save to user.md via Memory Curator
    if facts_to_learn:
        try:
            from app.memory_curator.service import build_memory_curator_service
            from app.config import get_settings as _get_settings
            from app.dependencies import get_accounting_repository
            import uuid as _uuid
            _settings = _get_settings()
            _curator = build_memory_curator_service(
                data_dir=_settings.data_dir,
                llm_config_repository=None,
                case_repository=None,
                audit_service=None,
                accounting_repository=get_accounting_repository(),
            )
            _tid = _uuid.UUID(tenant_id) if tenant_id else None
            if not _tid:
                from app.case_engine.tenant_resolver import resolve_tenant_id
                _tid_str = await resolve_tenant_id()
                _tid = _uuid.UUID(_tid_str) if _tid_str else None
            if _tid:
                for fact in facts_to_learn:
                    await _curator.learn_user_fact(_tid, fact)
        except Exception as exc:
            logger.warning('Failed to write to user.md: %s', exc)


# ---------------------------------------------------------------------------
# Name-update detection — detects "Ich heiße X" etc. and persists it
# ---------------------------------------------------------------------------

_NAME_PATTERNS = [
    re.compile(r'(?:ich\s+hei(?:ß|ss)e|mein\s+name\s+ist|nenn\s+mich|ich\s+bin(?:\s+die|\s+der)?)\s+(\w[\w\s-]{0,30})', re.IGNORECASE),
]


def _extract_name_intent(user_text: str) -> str | None:
    """Extract a display-name from the user message, or return None.

    P-06: Also validates via is_plausible_name() before returning.
    """
    text = user_text.strip()
    for pat in _NAME_PATTERNS:
        m = pat.search(text)
        if m:
            name = m.group(1).strip().rstrip('.!?,;')
            # Sanity: at least 2 chars, not a common filler
            if len(name) >= 2 and name.lower() not in ('da', 'ja', 'so', 'es', 'ok'):
                # P-06: Validate name plausibility before accepting
                is_name, _conf = is_plausible_name(name)
                if is_name:
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


# ---------------------------------------------------------------------------
# P-06: Name plausibility check — pure Python, no LLM
# ---------------------------------------------------------------------------

_NON_NAME_WORDS = frozenset({
    'kleinunternehmer', 'rechnung', 'firma', 'unternehmen', 'gmbh', 'ug',
    'steuer', 'ust', 'mwst', 'prozent', 'euro', 'konto', 'iban', 'bic',
    'adresse', 'strasse', 'plz', 'stadt', 'mail', 'telefon', 'fax',
    'ja', 'nein', 'hallo', 'danke', 'bitte', 'okay', 'test',
    'invoice', 'tax', 'company', 'business', 'address', 'email',
    'stundensatz', 'coaching', 'beratung', 'freelancer', 'selbstaendig',
    'selbststaendig', 'inhaber', 'geschaeftsfuehrer', 'buchhaltung',
    'operator', 'admin', 'user', 'login', 'password',
})

_NAME_CHAR_RE = re.compile(r'^[a-zA-ZäöüÄÖÜßéèêàáâîïôùûçñ\s.\-]+$')


def is_plausible_name(value: str) -> tuple[bool, float]:
    """Check if a string is a plausible person name.

    Returns (is_name, confidence) — confidence between 0.0 and 1.0.
    Pure Python, no LLM calls.
    """
    if not value or not value.strip():
        return False, 0.0

    name = value.strip()

    # Hard-Fail: contains digits
    if any(c.isdigit() for c in name):
        return False, 0.0

    # Hard-Fail: only allowed characters (letters, spaces, hyphens, dots)
    if not _NAME_CHAR_RE.match(name):
        return False, 0.0

    # Hard-Fail: too long
    if len(name) > 40:
        return False, 0.0

    # Hard-Fail: too short (single char)
    if len(name) < 2:
        return False, 0.0

    # Hard-Fail: contains non-name words
    lower = name.lower()
    for word in _NON_NAME_WORDS:
        if word in lower:
            return False, 0.0

    # Confidence calculation
    confidence = 0.5

    word_count = len(name.split())
    if word_count == 1:
        confidence += 0.2
    elif word_count == 2:
        confidence += 0.3
    elif word_count == 3:
        confidence += 0.1  # e.g. "Dr. Max Mueller"
    else:
        confidence -= 0.3  # 4+ words unlikely a name

    # First letter uppercase
    if name[0].isupper():
        confidence += 0.2

    return True, min(confidence, 1.0)


DISPLAY_NAME_CONFIDENCE_THRESHOLD = 0.6


async def _persist_display_name(user_id: str, tenant_id: str, new_name: str) -> None:
    """Write display_name to frya_user_preferences (upsert).

    P-06: Only stores if is_plausible_name() passes with sufficient confidence.
    """
    new_name = _sanitize_display_name(new_name)
    if not new_name:
        return

    # P-06: Plausibility gate — reject non-names
    is_name, confidence = is_plausible_name(new_name)
    if not is_name:
        logger.info('Rejected display_name=%r (not a name)', new_name)
        return
    if confidence < DISPLAY_NAME_CONFIDENCE_THRESHOLD:
        logger.info('Rejected display_name=%r (confidence=%.2f < %.2f)',
                     new_name, confidence, DISPLAY_NAME_CONFIDENCE_THRESHOLD)
        return

    # Title-case the name for consistency
    new_name = new_name.strip().title()
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


async def _persist_preference(user_id: str, tenant_id: str, key: str, value: str) -> None:
    """Write an arbitrary preference to frya_user_preferences (upsert)."""
    try:
        from app.dependencies import get_settings
        settings = get_settings()
        db_url = settings.database_url
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
            logger.info('Persisted preference %s=%s for user=%s', key, value, user_id)
        finally:
            await conn.close()
    except Exception as exc:
        logger.warning('Failed to persist preference %s: %s', key, exc)


# ---------------------------------------------------------------------------
# Theme keyword map for SETTINGS intent
# ---------------------------------------------------------------------------

_THEME_MAP: dict[str, str] = {
    'dunkelmodus': 'dark', 'dark mode': 'dark', 'dunkel': 'dark',
    'nachtmodus': 'dark', 'dunkler modus': 'dark',
    'heller modus': 'light', 'light mode': 'light', 'hell': 'light',
    'hellmodus': 'light', 'tagmodus': 'light', 'helles design': 'light',
}

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


async def _dispatch_invoice_send(
    reply_text: str,
    user_text: str,
    user_id: str,
    tenant_id: str,
    chat_history: list | None = None,
) -> dict | None:
    """Parse communicator reply for invoice-send intent and execute.

    Extracts: contact name, email, items (description, qty, price), payment terms
    from the reply text and recent chat history.
    Returns result dict or None if data insufficient.
    """
    import re as _re

    # 1. Extract email from reply
    _emails = _re.findall(r'[\w.+-]+@[\w.-]+\.\w+', reply_text)
    if not _emails:
        return None
    email = _emails[0]

    # 2. Gather all text context (reply + recent user messages + conversation store)
    _all_text = reply_text + '\n' + user_text
    try:
        _conv_store = get_communicator_conversation_store()
        _recent = await _conv_store.get_recent(user_id, limit=10)
        for msg in (_recent or []):
            _content = msg.get('content', '') if isinstance(msg, dict) else str(msg)
            _all_text += '\n' + _content
    except Exception:
        pass  # Best-effort
    if chat_history:
        for msg in chat_history[-10:]:
            _content = msg.get('content', '') if isinstance(msg, dict) else str(msg)
            _all_text += '\n' + _content

    # 3. Extract contact name — look for "Empfänger: X" or "Kunde ist X"
    _name_match = (
        _re.search(r'Empf[aä]nger:\s*([^\n,]+)', _all_text)
        or _re.search(r'Kunde\s+(?:ist\s+)?([A-ZÄÖÜ][a-zäöüß]+(?:\s+[A-ZÄÖÜ][a-zäöüß]+)+)', _all_text)
    )
    contact_name = _name_match.group(1).strip() if _name_match else 'Unbekannt'

    # 4. Extract items — look for patterns like "2 Stunden Coaching à 90"
    items = []
    # Pattern: quantity + description + price (various formats)
    _item_patterns = [
        # "2 Stunden Coaching à 90,00 EUR"
        _re.compile(r'(\d+)\s+(Stunden?|Std\.?|Stk\.?|x)\s+(.+?)\s*[àa@]\s*(\d+[.,]?\d*)', _re.IGNORECASE),
        # "Position: 2 Stunden Coaching à 90,00 EUR"
        _re.compile(r'Position:\s*(\d+)\s+(Stunden?|Std\.?|Stk\.?)\s+(.+?)\s*[àa@]\s*(\d+[.,]?\d*)', _re.IGNORECASE),
    ]
    for _pat in _item_patterns:
        for _m in _pat.finditer(_all_text):
            _qty = int(_m.group(1))
            _desc = _m.group(3).strip().rstrip(' =—–-')
            _price = float(_m.group(4).replace(',', '.'))
            items.append({
                'description': _desc,
                'quantity': _qty,
                'unit_price': _price,
                'tax_rate': 19,
            })
    if not items:
        # Fallback: try to extract from "X EUR" total
        _total_match = _re.search(r'(\d+[.,]?\d*)\s*EUR', _all_text)
        if _total_match:
            _total = float(_total_match.group(1).replace(',', '.'))
            # Assume gross, calculate net (19% MwSt)
            _net = round(_total / 1.19, 2)
            items = [{'description': 'Leistung', 'quantity': 1, 'unit_price': _net, 'tax_rate': 19}]

    if not items:
        logger.warning('Invoice dispatch: no items found in text')
        return None

    # 5. Extract payment terms
    _terms_match = _re.search(r'(\d+)\s*Tage', _all_text)
    payment_terms_days = int(_terms_match.group(1)) if _terms_match else 14

    # 6. Execute
    from app.services.form_handlers import handle_invoice_send
    result = await handle_invoice_send({
        'contact_name': contact_name,
        'email': email,
        'items': items,
        'payment_terms_days': payment_terms_days,
    }, user_id)

    return result


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
    chat_registry.register(user_id, websocket)
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
                    # --- Phase 0: Pending-Flow Resume (P-10 A3) ---
                    # If a previous turn set a pending flow (e.g. waiting for email),
                    # resume that flow instead of starting a new intent.
                    _pending_flow = getattr(websocket, '_frya_pending_flow', None)
                    if _pending_flow and isinstance(_pending_flow, dict):
                        _pf_type = _pending_flow.get('waiting_for')
                        _pf_invoice_id = _pending_flow.get('invoice_id')
                        _pf_data = _pending_flow.get('pending_data', {})

                        # Clear pending before processing
                        websocket._frya_pending_flow = None

                        if _pf_type == 'recipient_email' and _pf_invoice_id:
                            # User responded with email — resume send flow
                            from app.services.invoice_pipeline import handle_send_invoice
                            _send_params = {
                                'invoice_id': _pf_invoice_id,
                                'recipient_email': text.strip(),
                            }
                            _send_result = await handle_send_invoice(_send_params, user_id)
                            await websocket.send_json({
                                'type': 'typing', 'active': False,
                            })
                            await websocket.send_json({
                                'type': 'message_complete',
                                'text': _send_result.get('text', ''),
                                'case_ref': None,
                                'context_type': 'none',
                                'suggestions': [a['chat_text'] for a in _send_result.get('actions', [])[:3]] or _DEFAULT_SUGGESTIONS,
                                'content_blocks': _send_result.get('content_blocks', []),
                                'actions': _send_result.get('actions', []),
                                'routing': 'pending_flow',
                            })
                            continue

                        elif _pf_type == 'recipient_address' and _pf_data:
                            # User responded with address — merge into pending data and retry
                            _pf_data['contact_address'] = text.strip()
                            from app.services.invoice_pipeline import handle_create_invoice
                            _resume_result = await handle_create_invoice(_pf_data, user_id)
                            _resume_text = _resume_result.get('text', '')
                            _resume_blocks = _resume_result.get('content_blocks', [])
                            _resume_actions = _resume_result.get('actions', [])
                            # Check if still pending
                            if _resume_result.get('_pending_intent'):
                                websocket._frya_pending_flow = {
                                    'waiting_for': 'recipient_address',
                                    'pending_data': _resume_result.get('_pending_data', _pf_data),
                                }
                            await websocket.send_json({
                                'type': 'typing', 'active': False,
                            })
                            await websocket.send_json({
                                'type': 'message_complete',
                                'text': _resume_text,
                                'case_ref': None,
                                'context_type': _resume_result.get('context_type', 'invoice_draft'),
                                'suggestions': [a['chat_text'] for a in _resume_actions[:3]] or _DEFAULT_SUGGESTIONS,
                                'content_blocks': _resume_blocks,
                                'actions': _resume_actions,
                                'routing': 'pending_flow',
                            })
                            continue

                    # --- Phase 1: TieredOrchestrator intent routing ---
                    quick_action = data.get('quick_action')
                    # Inject user_id + tenant_id so ActionRouter can use them
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
                            routing_result = await orchestrator.route(
                                message=text, quick_action=quick_action,
                            )
                            tier_intent = routing_result.get('intent')
                            tier_routing = routing_result.get('routing')
                            logger.info('TieredOrchestrator: intent=%s routing=%s', tier_intent, tier_routing)
                        except Exception as exc:
                            logger.warning('TieredOrchestrator failed, falling back: %s', exc)

                    # --- Phase 1a: ActionRouter short-circuit ---
                    # When ActionRouter handled a quick_action (send_invoice, void_invoice etc.),
                    # the result is already complete — skip communicator entirely.
                    if tier_routing == 'action_router' and isinstance(routing_result.get('result'), dict):
                        _ar_result = routing_result['result']
                        _ar_text = _ar_result.get('text', '')
                        _ar_blocks = _ar_result.get('content_blocks', [])
                        _ar_actions = _ar_result.get('actions', [])
                        _ar_ctx = _ar_result.get('context_type', 'none')
                        _ar_suggestions = (
                            [a['chat_text'] for a in _ar_actions[:3]]
                            if _ar_actions
                            else _DEFAULT_SUGGESTIONS
                        )
                        await websocket.send_json({
                            'type': 'message_complete',
                            'text': _ar_text,
                            'case_ref': None,
                            'context_type': _ar_ctx,
                            'suggestions': _ar_suggestions,
                            'content_blocks': _ar_blocks,
                            'actions': _ar_actions,
                            'routing': 'action_router',
                        })
                        continue

                    # --- Phase 1b: Short-circuit intents that must NOT hit communicator ---
                    _shortcircuit_reply: str | None = None
                    _shortcircuit_data: dict = {}
                    _theme_changed: str | None = None

                    if tier_intent == 'UPLOAD':
                        # BUG-002: User typed "upload" but has no attachment —
                        # skip communicator to avoid hallucinated "received" reply.
                        _shortcircuit_reply = (
                            'Zum Hochladen nutze das Bueroklammer-Symbol unten '
                            'oder ziehe Dateien direkt in den Chat.'
                        )

                    elif tier_intent == 'CHOOSE_TEMPLATE':
                        # Template selection — show 3 template cards
                        _shortcircuit_reply = (
                            'Wie sollen deine Rechnungen aussehen? '
                            'Hier sind drei Vorlagen:'
                        )

                    elif tier_intent == 'SET_TEMPLATE':
                        # Parse which template from text
                        _tpl_text = text.lower()
                        _chosen_tpl = 'clean'
                        if 'professional' in _tpl_text:
                            _chosen_tpl = 'professional'
                        elif 'minimal' in _tpl_text:
                            _chosen_tpl = 'minimal'
                        await _persist_preference(user_id, tenant_id, 'invoice_template', _chosen_tpl)
                        _tpl_titles = {'clean': 'Clean', 'professional': 'Professional', 'minimal': 'Minimal'}
                        _shortcircuit_reply = f'Rechnungs-Template auf "{_tpl_titles[_chosen_tpl]}" geaendert.'

                    elif tier_intent == 'UPLOAD_LOGO':
                        _shortcircuit_reply = (
                            'Schick mir einfach dein Logo als Bild (PNG, JPG oder SVG). '
                            'Nutze das Bueroklammer-Symbol unten links.'
                        )

                    elif tier_intent == 'SHOW_CONTACTS':
                        # P-08 A2: Load all contacts for card_list
                        try:
                            from app.dependencies import get_accounting_repository
                            _contacts_repo = get_accounting_repository()
                            _all_contacts = await _contacts_repo.list_contacts(uuid.UUID(tenant_id))
                            _contact_dicts = [
                                {
                                    'name': c.display_name or c.name,
                                    'contact_type': c.contact_type,
                                    'email': c.email or '',
                                    'category': c.category,
                                }
                                for c in _all_contacts if c.is_active
                            ]
                            _shortcircuit_reply = f'{len(_contact_dicts)} Kontakte gefunden.'
                            # Store for ResponseBuilder
                            _shortcircuit_data = {'contacts': _contact_dicts}
                        except Exception as _ce:
                            logger.warning('SHOW_CONTACTS failed: %s', _ce)
                            _shortcircuit_reply = 'Kontakte konnten nicht geladen werden.'
                            _shortcircuit_data = {}

                    elif tier_intent == 'SETTINGS':
                        # BUG-006: Handle theme change requests directly
                        text_lower = text.lower()
                        for trigger, theme in _THEME_MAP.items():
                            if trigger in text_lower:
                                await _persist_preference(user_id, tenant_id, 'theme', theme)
                                _theme_changed = theme
                                _label = 'Dunkel' if theme == 'dark' else 'Hell'
                                _shortcircuit_reply = f'Design auf "{_label}" umgestellt.'
                                break

                    # --- SHOW_INVOICE: Load and display specific invoice ---
                    if tier_intent == 'SHOW_INVOICE':
                        import re as _re_inv
                        _inv_match = _re_inv.search(r'RE-\d+-\d+', text)
                        if _inv_match:
                            _inv_nr = _inv_match.group(0)
                            try:
                                import asyncpg as _apg_inv
                                from app.dependencies import get_settings as _gs_inv
                                _inv_conn = await _apg_inv.connect(_gs_inv().database_url)
                                try:
                                    _inv_row = await _inv_conn.fetchrow(
                                        "SELECT i.*, c.name as contact_name FROM frya_invoices i "
                                        "LEFT JOIN frya_contacts c ON c.id = i.contact_id "
                                        "WHERE i.invoice_number = $1", _inv_nr,
                                    )
                                finally:
                                    await _inv_conn.close()

                                if _inv_row:
                                    from app.services.invoice_pipeline import _eur
                                    _inv_status_map = {'DRAFT': 'Entwurf', 'SENT': 'Versendet', 'PAID': 'Bezahlt', 'VOID': 'Storniert'}
                                    _inv_blocks = [{
                                        'block_type': 'key_value',
                                        'data': {'items': [
                                            {'label': 'Rechnungsnr.', 'value': _inv_row['invoice_number']},
                                            {'label': 'Empfaenger', 'value': _inv_row['contact_name'] or ''},
                                            {'label': 'Status', 'value': _inv_status_map.get(_inv_row['status'], _inv_row['status'])},
                                            {'label': 'Netto', 'value': _eur(float(_inv_row['net_total'] or 0))},
                                            {'label': 'Brutto', 'value': _eur(float(_inv_row['gross_total'] or 0))},
                                            {'label': 'Datum', 'value': _inv_row['invoice_date'].strftime('%d.%m.%Y') if _inv_row['invoice_date'] else ''},
                                            {'label': 'Faellig', 'value': _inv_row['due_date'].strftime('%d.%m.%Y') if _inv_row['due_date'] else ''},
                                        ]},
                                    }]
                                    _inv_pdf_url = f"/api/v1/invoices/{_inv_row['id']}/pdf"
                                    _inv_blocks.append({
                                        'block_type': 'document',
                                        'data': {'title': f'Rechnung {_inv_nr}', 'url': _inv_pdf_url, 'format': 'PDF'},
                                    })
                                    _inv_actions = []
                                    if _inv_row['status'] == 'DRAFT':
                                        _inv_actions = [
                                            {'label': 'Freigeben & Senden', 'chat_text': f'Rechnung {_inv_nr} senden', 'style': 'primary',
                                             'quick_action': {'type': 'send_invoice', 'params': {'invoice_id': str(_inv_row['id'])}}},
                                            {'label': 'Verwerfen', 'chat_text': f'Rechnung {_inv_nr} verwerfen', 'style': 'text',
                                             'quick_action': {'type': 'void_invoice', 'params': {'invoice_id': str(_inv_row['id'])}}},
                                        ]
                                    await websocket.send_json({
                                        'type': 'message_complete',
                                        'text': f'Rechnung {_inv_nr} — {_inv_status_map.get(_inv_row["status"], _inv_row["status"])}',
                                        'case_ref': None,
                                        'context_type': 'invoice_draft',
                                        'suggestions': [a['chat_text'] for a in _inv_actions[:3]] if _inv_actions else _DEFAULT_SUGGESTIONS,
                                        'content_blocks': _inv_blocks,
                                        'actions': _inv_actions,
                                        'routing': 'regex',
                                    })
                                    continue
                                else:
                                    _shortcircuit_reply = f'Rechnung {_inv_nr} nicht gefunden.'
                            except Exception as _inv_exc:
                                logger.warning('SHOW_INVOICE failed: %s', _inv_exc)

                    if _shortcircuit_reply is not None:
                        # Determine context_type from orchestrator
                        context_type = _TIER_INTENT_TO_CONTEXT.get(tier_intent, 'none')
                        if context_type != 'none':
                            await websocket.send_json({
                                'type': 'ui_hint',
                                'action': 'open_context',
                                'context_type': context_type,
                            })

                        # Build content_blocks via ResponseBuilder if data available
                        _sc_blocks: list = []
                        _sc_actions: list = []
                        if _shortcircuit_data and tier_intent:
                            try:
                                from app.agents.response_builder import ResponseBuilder
                                _sc_rb = ResponseBuilder()
                                _sc_result = _sc_rb.build(tier_intent, _shortcircuit_data, _shortcircuit_reply or '')
                                _sc_blocks = _sc_result.get('content_blocks', [])
                                _sc_actions = _sc_result.get('actions', [])
                            except Exception:
                                pass

                        response_payload: dict[str, Any] = {
                            'type': 'message_complete',
                            'text': _shortcircuit_reply,
                            'case_ref': None,
                            'context_type': context_type,
                            'suggestions': [a['chat_text'] for a in _sc_actions[:3]] if _sc_actions else _DEFAULT_SUGGESTIONS,
                            'content_blocks': _sc_blocks,
                            'actions': _sc_actions if _sc_actions else [],
                            'routing': tier_routing,
                        }
                        if _theme_changed:
                            response_payload['settings_changed'] = {'theme': _theme_changed}

                        await websocket.send_json(response_payload)
                        continue

                    # --- Phase 2: Communicator (always, for natural-language reply) ---
                    result = await _get_communicator_reply(text, user_id, tenant_id)

                    # Aufgabe 3: Extract LLM-generated suggestions from communicator
                    _llm_suggestions: list[dict] = []
                    if result and result.handled:
                        reply_text = result.reply_text
                        _llm_suggestions = getattr(result, 'llm_suggestions', []) or []
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

                    # --- Business info extraction (hourly rate, company, tax) ---
                    await _extract_and_persist_business_info(text, user_id, tenant_id)

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

                    # Detect "show all" request for inbox
                    if tier_intent == 'SHOW_INBOX':
                        _text_lower = text.lower()
                        if 'alle' in _text_lower and ('zeig' in _text_lower or 'beleg' in _text_lower):
                            agent_results['show_all'] = True

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
                                llm_suggestions=_llm_suggestions,
                            )
                            content_blocks = enhanced.get('content_blocks', [])
                            actions = enhanced.get('actions', [])
                        except Exception as exc:
                            logger.warning('ResponseBuilder failed: %s', exc)

                    # --- Strip "FRYA:" prefix from reply text ---
                    if reply_text:
                        reply_text = re.sub(r'^FRYA:\s*', '', reply_text)

                    # --- Phase 2b: Invoice Pipeline (Ausgangsrechnungs-Pipeline) ---
                    # If communicator returned INVOICE_DATA, create draft + show preview.
                    # NO auto_send — every invoice MUST show preview + require user approval.
                    _invoice_data = getattr(result, 'invoice_data', None) if result else None
                    if _invoice_data and isinstance(_invoice_data, dict):
                        try:
                            from app.services.invoice_pipeline import handle_create_invoice
                            pipeline_result = await handle_create_invoice(_invoice_data, user_id)
                            # Override response with pipeline result
                            reply_text = pipeline_result.get('text', reply_text)
                            content_blocks = pipeline_result.get('content_blocks', [])
                            actions = pipeline_result.get('actions', [])
                            context_type = pipeline_result.get('context_type', 'invoice_draft')
                            logger.info('Invoice pipeline: draft created from INVOICE_DATA')

                            # P-10 A3: Set pending flow if pipeline needs more info
                            if pipeline_result.get('_pending_intent'):
                                _pending_data = pipeline_result.get('_pending_data', _invoice_data)
                                if pipeline_result.get('awaiting_email_for_invoice'):
                                    websocket._frya_pending_flow = {
                                        'waiting_for': 'recipient_email',
                                        'invoice_id': pipeline_result['awaiting_email_for_invoice'],
                                        'pending_data': _pending_data,
                                    }
                                else:
                                    websocket._frya_pending_flow = {
                                        'waiting_for': 'recipient_address',
                                        'pending_data': _pending_data,
                                    }
                        except Exception as exc:
                            logger.error('Invoice pipeline failed: %s', exc)
                            reply_text = f'Rechnung konnte nicht erstellt werden: {exc}'

                    # --- Phase 2c: ActionRouter pipeline results with content_blocks ---
                    # When ActionRouter handles send_invoice/void_invoice, result contains
                    # content_blocks + actions directly from invoice_pipeline.
                    if tier_routing == 'action_router' and isinstance(agent_results, dict):
                        _pipeline_result = agent_results.get('result', {})
                        if isinstance(_pipeline_result, dict) and _pipeline_result.get('content_blocks'):
                            content_blocks = _pipeline_result['content_blocks']
                            actions = _pipeline_result.get('actions', [])
                            reply_text = _pipeline_result.get('text', reply_text)
                            context_type = _pipeline_result.get('context_type', context_type)
                        # P-10 A3: Pending flow for send_invoice email question
                        if isinstance(_pipeline_result, dict) and _pipeline_result.get('awaiting_email_for_invoice'):
                            websocket._frya_pending_flow = {
                                'waiting_for': 'recipient_email',
                                'invoice_id': _pipeline_result['awaiting_email_for_invoice'],
                                'pending_data': {},
                            }

                    # --- Synchronize text with content_blocks for SHOW_INBOX ---
                    # The communicator generates text BEFORE blocks exist,
                    # causing "Inbox ist leer" even when blocks show items.
                    if tier_intent == 'SHOW_INBOX' and content_blocks:
                        _inbox_item_count = 0
                        for _b in content_blocks:
                            if _b.get('block_type') == 'card_list':
                                _inbox_item_count = len(_b.get('data', {}).get('items', []))
                        if _inbox_item_count > 0:
                            _total = agent_results.get('count', _inbox_item_count)
                            reply_text = f'{_total} Belege warten auf deine Freigabe.'
                        elif not any(_b.get('block_type') == 'alert' for _b in content_blocks):
                            reply_text = 'Deine Inbox ist leer — aktuell keine neuen Dokumente.'

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
                        'type': 'message_complete',
                        'text': 'Da ist etwas schiefgelaufen. Bitte versuche es nochmal.',
                        'case_ref': None,
                        'context_type': 'none',
                        'suggestions': [text] if text else _DEFAULT_SUGGESTIONS,
                        'content_blocks': [],
                        'actions': [
                            {'label': 'Nochmal versuchen', 'chat_text': text, 'style': 'primary'},
                        ] if text else [],
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
                        handle_invoice_form, handle_invoice_send,
                        handle_contact_form, handle_settings_form,
                    )
                    rb = _get_response_builder()
                    if form_type == 'invoice':
                        result = await handle_invoice_form(form_data, user_id)
                        text = f'FRYA: Rechnung {result.get("invoice_number","?")} erstellt ({result.get("gross_total","?")}€, Entwurf).'
                    elif form_type == 'invoice_send':
                        result = await handle_invoice_send(form_data, user_id)
                        if result.get('status') == 'sent':
                            text = f'Rechnung {result.get("invoice_number","?")} wurde erstellt und an {result.get("email","?")} gesendet ({result.get("gross_total","?")}€).'
                        else:
                            text = f'Rechnung {result.get("invoice_number","?")} erstellt ({result.get("gross_total","?")}€). {result.get("message","")}'
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
    finally:
        chat_registry.unregister(user_id)


# ---------------------------------------------------------------------------
# Synchronous POST fallback
# ---------------------------------------------------------------------------


# NOTE: Synchronous POST /api/v1/chat is provided by customer_api.py
# (expects {"message": "..."} with Bearer auth). Removed from here to
# avoid duplicate route conflict.
