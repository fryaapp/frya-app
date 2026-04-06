from __future__ import annotations

import logging
import os
import uuid
from typing import Any

import litellm

_LLM_TIMEOUT = float(os.environ.get('FRYA_LLM_TIMEOUT', '120'))

from app.telegram.communicator.context_resolver import extract_case_ref_from_text, resolve_context, search_case_by_vendor
from app.telegram.communicator.guardrail import check_guardrail
from app.telegram.communicator.intent_classifier import classify_intent
from app.telegram.communicator.memory.conversation_store import (
    ConversationMemoryStore,
    build_updated_conversation_memory,
)
from app.telegram.communicator.memory.models import ConversationMemory, TruthAnnotation
from app.telegram.communicator.memory.truth_arbitration import TruthArbitrator
from app.telegram.communicator.memory.user_store import (
    UserMemoryStore,
    build_or_update_user_memory,
)
from app.telegram.communicator.models import (
    CommunicatorContextResolution,
    CommunicatorResult,
    CommunicatorTurn,
)
from app.telegram.communicator.prompts import COMMUNICATOR_SYSTEM_PROMPT, UNCERTAINTY_SUFFIX
from app.telegram.communicator.response_builder import build_response
from app.telegram.models import TelegramNormalizedIngressMessage

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Aufgabe 1: Trust Boundary — provider-based context filter
# ---------------------------------------------------------------------------

import re as _re_filter
import json as _json_mod

_IBAN_RE = _re_filter.compile(r'\b[A-Z]{2}\d{2}[\s]?[\dA-Z]{4}[\s]?[\dA-Z]{4}[\s]?[\dA-Z]{4}[\s]?[\dA-Z]{4}[\s]?[\dA-Z]{0,4}\b')
_STEUER_RE = _re_filter.compile(r'(?:Steuer(?:nummer|nr|id)|USt-?ID(?:Nr)?|Tax[ -]?ID)[:\s]*[\w/\-\.]+', _re_filter.IGNORECASE)


def _filter_sensitive_context(context: str) -> str:
    """Remove IBANs and Steuernummern from context for non-EU providers.

    Applied when provider != 'bedrock' (data goes outside EU).
    """
    filtered = _IBAN_RE.sub('[IBAN entfernt — Bedrock EU nötig]', context)
    filtered = _STEUER_RE.sub('[Steuernummer entfernt — Bedrock EU nötig]', filtered)
    return filtered


# ---------------------------------------------------------------------------
# Aufgabe 3: Parse LLM-generated suggestions from response
# ---------------------------------------------------------------------------

_SUGGESTIONS_RE = _re_filter.compile(
    r'SUGGESTIONS_JSON:\s*(\[.*?\])\s*$',
    _re_filter.MULTILINE | _re_filter.DOTALL,
)

# P-08 A4: Additional patterns for leaked JSON in text
_JSON_LEAK_PATTERNS = [
    # Catches SUGGESTIONS_JSON: [{...}] anywhere in text (not just end)
    _re_filter.compile(r'SUGGESTIONS_JSON:\s*\[.*?\]', _re_filter.DOTALL),
    # Catches bare {"suggestions": [...]} or {"label": ...} arrays
    _re_filter.compile(r'\{["\']?(?:suggestions|label)["\']?\s*:\s*[\[\{].*?\}[\]\}]*', _re_filter.DOTALL),
    # Catches bare JSON arrays that look like suggestions [{"label": ...}]
    _re_filter.compile(r'\[\s*\{\s*["\']label["\']\s*:.*?\}\s*\]', _re_filter.DOTALL),
]

# ---------------------------------------------------------------------------
# Aufgabe: Parse INVOICE_DATA from communicator response
# ---------------------------------------------------------------------------

def _parse_invoice_data(raw_text: str) -> tuple[str, dict | None]:
    """Extract INVOICE_DATA JSON from LLM response text.

    Uses brace-counting to find the complete JSON object even with nested arrays.
    Returns (cleaned_text, invoice_data_dict_or_None).
    """
    marker = 'INVOICE_DATA:'
    idx = raw_text.find(marker)
    if idx == -1:
        return raw_text, None
    # Find the opening brace
    brace_start = raw_text.find('{', idx + len(marker))
    if brace_start == -1:
        return raw_text, None
    # Count braces to find matching close
    depth = 0
    brace_end = -1
    for i in range(brace_start, len(raw_text)):
        if raw_text[i] == '{':
            depth += 1
        elif raw_text[i] == '}':
            depth -= 1
            if depth == 0:
                brace_end = i
                break
    if brace_end == -1:
        return raw_text, None
    json_str = raw_text[brace_start:brace_end + 1]
    # Remove the INVOICE_DATA block from the text
    cleaned = (raw_text[:idx].rstrip() + '\n' + raw_text[brace_end + 1:].lstrip()).strip()
    try:
        data = _json_mod.loads(json_str)
        if not isinstance(data, dict):
            return raw_text, None
        # Validate required fields
        if not data.get('contact_name') or not data.get('items'):
            return raw_text, None
        # Validate items structure
        items = data['items']
        if not isinstance(items, list) or not items:
            return raw_text, None
        valid_items = []
        for item in items:
            if isinstance(item, dict) and item.get('description') and item.get('unit_price'):
                valid_items.append({
                    'description': str(item['description'])[:200],
                    'quantity': float(item.get('quantity', 1)),
                    'unit_price': float(item['unit_price']),
                    'tax_rate': float(item.get('tax_rate', 19)),
                })
        if not valid_items:
            return raw_text, None
        data['items'] = valid_items
        return cleaned, data
    except (_json_mod.JSONDecodeError, TypeError, ValueError):
        return raw_text, None


def _parse_llm_suggestions(raw_text: str) -> tuple[str, list[dict]]:
    """Extract SUGGESTIONS_JSON from LLM response text.

    Returns (cleaned_text, suggestions_list).
    """
    match = _SUGGESTIONS_RE.search(raw_text)
    if not match:
        # P-08 A4: Fallback — clean any leaked JSON from text
        cleaned = _clean_json_leaks(raw_text)
        return cleaned, []
    try:
        suggestions = _json_mod.loads(match.group(1))
        if not isinstance(suggestions, list):
            cleaned = _clean_json_leaks(raw_text[:match.start()].rstrip())
            return cleaned, []
        # Validate each suggestion has required fields
        valid = []
        for s in suggestions:
            if isinstance(s, dict) and s.get('label') and s.get('chat_text'):
                valid.append({
                    'label': str(s['label'])[:30],
                    'chat_text': str(s['chat_text'])[:80],
                    'style': str(s.get('style', 'secondary')),
                })
        cleaned = raw_text[:match.start()].rstrip()
        # P-08 A4: Also clean any remaining JSON fragments
        cleaned = _clean_json_leaks(cleaned)
        return cleaned, valid
    except (_json_mod.JSONDecodeError, TypeError):
        cleaned = _clean_json_leaks(raw_text)
        return cleaned, []


def _clean_json_leaks(text: str) -> str:
    """P-08 A4: Remove any JSON fragments that leaked into chat text."""
    for pattern in _JSON_LEAK_PATTERNS:
        text = pattern.sub('', text)
    # Clean up resulting whitespace
    import re
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()

_CONTEXT_INTENTS = frozenset({
    'STATUS_OVERVIEW',
    'NEEDS_FROM_USER',
    'DOCUMENT_ARRIVAL_CHECK',
    'LAST_CASE_EXPLANATION',
})

_INTENT_RESPONSE_TYPES: dict[str, str] = {
    'GREETING': 'COMMUNICATOR_REPLY_GREETING',
    'STATUS_OVERVIEW': 'COMMUNICATOR_REPLY_STATUS',
    'NEEDS_FROM_USER': 'COMMUNICATOR_REPLY_NEEDS',
    'DOCUMENT_ARRIVAL_CHECK': 'COMMUNICATOR_REPLY_EXPLANATION',
    'LAST_CASE_EXPLANATION': 'COMMUNICATOR_REPLY_EXPLANATION',
    'GENERAL_SAFE_HELP': 'COMMUNICATOR_REPLY_SAFE_HELP',
    'GENERAL_CONVERSATION': 'COMMUNICATOR_REPLY_GENERAL',
    'REMINDER_PERSONAL': 'COMMUNICATOR_REPLY_GENERAL',
}

_GENERAL_CONVERSATION_PERSONALITY = (
    '\n[KOMMUNIKATIONSSTIL]\n'
    'Antworte freundlich, kompetent und direkt auf Deutsch. Sprich den User mit "du" an.\n'
    'Bei Buchhaltungsthemen: beziehe dich auf verfuegbare Daten — wenn keine vorhanden, sage es ehrlich.\n'
    'Bei Small Talk: kurz und natuerlich antworten (1-2 Saetze). Du bist eine Kollegin, kein Chatbot.\n'
    'Wenn unklar ist was der User will: kurz nachfragen.\n'
    '[/KOMMUNIKATIONSSTIL]'
)


def build_llm_context_payload(
    intent: str,
    context_resolution: CommunicatorContextResolution | None,
    truth_annotation: TruthAnnotation,
    conversation_memory: ConversationMemory | None,
    user_message: str,
    *,
    system_context: str | None = None,
    provider: str | None = None,
    chat_history: list[dict] | None = None,
) -> dict:
    """Build the messages payload for litellm.acompletion."""
    lines = ['[FALLKONTEXT]']
    res_status = context_resolution.resolution_status if context_resolution else 'NOT_FOUND'
    # If conversation memory has a case ref, override NOT_FOUND so LLM uses system context
    if res_status == 'NOT_FOUND' and conversation_memory and conversation_memory.last_case_ref:
        res_status = 'FOUND'
    lines.append(f'resolution_status: {res_status}')
    lines.append(f'truth_basis: {truth_annotation.truth_basis}')

    if context_resolution:
        if context_resolution.open_item_state:
            lines.append(f'open_item_state: {context_resolution.open_item_state}')
        if context_resolution.open_item_title:
            lines.append(f'open_item_title: {context_resolution.open_item_title}')
        if context_resolution.clarification_question:
            lines.append(f'clarification_question: {context_resolution.clarification_question}')
        if context_resolution.resolved_document_ref:
            lines.append(f'document_ref: {context_resolution.resolved_document_ref}')

    if conversation_memory:
        parts: list[str] = []
        if conversation_memory.last_intent:
            parts.append(f'intent={conversation_memory.last_intent}')
        if conversation_memory.last_case_ref:
            parts.append(f'case_ref={conversation_memory.last_case_ref}')
        if conversation_memory.last_search_ref and not conversation_memory.last_case_ref:
            parts.append(f'search_ref={conversation_memory.last_search_ref}')
        if conversation_memory.last_context_resolution_status:
            parts.append(f'resolution={conversation_memory.last_context_resolution_status}')
        if parts:
            lines.append(f'letzte_turns: [{", ".join(parts)}]')
            # RC-3 Fix: wenn context_resolution None, trotzdem last_case_ref
            # explizit als resolved_case_ref nennen fuer Folgefragen.
            if context_resolution is None and conversation_memory.last_case_ref:
                lines.append(f'resolved_case_ref: {conversation_memory.last_case_ref}')
                lines.append('context_from: conversation_memory')
        else:
            lines.append('letzte_turns: keine')
    else:
        lines.append('letzte_turns: keine')

    lines.append('[/FALLKONTEXT]')

    system_content = COMMUNICATOR_SYSTEM_PROMPT
    _aktueller_vorgang_block = ''
    if system_context:
        # Extract [AKTUELLER VORGANG] block and put it in the user message
        # so the LLM sees it directly adjacent to the question (not buried in system prompt)
        import re as _re_payload
        _av_match = _re_payload.search(
            r'(\[AKTUELLER VORGANG\].*?\[/AKTUELLER VORGANG\])',
            system_context, _re_payload.DOTALL,
        )
        if _av_match:
            _aktueller_vorgang_block = _av_match.group(1)
            # Keep the rest in system context (without the block)
            _sys_ctx_without_av = system_context[:_av_match.start()] + system_context[_av_match.end():]
            system_content = f'{COMMUNICATOR_SYSTEM_PROMPT}\n{_sys_ctx_without_av.strip()}'
        else:
            system_content = f'{COMMUNICATOR_SYSTEM_PROMPT}\n{system_context}'

    if _aktueller_vorgang_block:
        lines.append(_aktueller_vorgang_block)
    lines.append(f'Nutzernachricht: {user_message}')

    # Anthropic Prompt Caching: system prompt as content array with cache_control
    if provider == 'anthropic':
        system_msg = {
            'role': 'system',
            'content': [
                {
                    'type': 'text',
                    'text': system_content,
                    'cache_control': {'type': 'ephemeral'},
                }
            ],
        }
    else:
        system_msg = {'role': 'system', 'content': system_content}

    messages = [system_msg]
    if chat_history:
        # Filter out empty content blocks — Anthropic rejects them
        for msg in chat_history:
            if msg.get('content', '').strip():
                messages.append(msg)
    messages.append({'role': 'user', 'content': '\n'.join(lines)})

    return {
        'messages': messages,
    }


async def _build_system_context(
    tenant_id: Any,
    case_repository: Any,
    audit_service: Any,
    user_memory: Any,
    conv_memory: Any = None,
    effective_case_ref: str | None = None,
) -> str | None:
    """Fetch live system data and format as a [SYSTEMKONTEXT] block for the LLM."""
    parts: list[str] = []

    # ── Detailed case context from effective context or conversation memory ──
    _effective_case_ref = effective_case_ref or (
        getattr(conv_memory, 'last_case_ref', None) if conv_memory else None
    )
    if _effective_case_ref and case_repository is not None:
        try:
            import uuid as _uuid_mod
            import re as _re_mod

            _case_ref = _effective_case_ref
            _case_uuid = None

            # Try direct UUID parse first
            try:
                _case_uuid = _uuid_mod.UUID(_case_ref)
            except (ValueError, AttributeError) as exc:
                logger.debug('Case ref %s is not a UUID: %s', _case_ref, exc)

            # If not a UUID (e.g. "doc-19", "tg-chat-msg"), resolve via audit trail
            if _case_uuid is None and audit_service is not None:
                try:
                    _events = await audit_service.by_case(_case_ref, limit=50)
                    for _ev in _events:
                        if getattr(_ev, 'action', '') == 'document_assigned_to_case':
                            _result_str = getattr(_ev, 'result', '') or ''
                            _m = _re_mod.search(r'case_id=([0-9a-f-]{36})', _result_str)
                            if _m:
                                _case_uuid = _uuid_mod.UUID(_m.group(1))
                                break
                except Exception as exc:
                    logger.warning('Audit trail lookup failed for case ref %s: %s', _case_ref, exc)

            case_detail = await case_repository.get_case(_case_uuid) if _case_uuid else None
            if case_detail:
                detail_parts = []
                detail_parts.append(f'Aktueller Vorgang: {case_detail.case_number or case_detail.id}')
                detail_parts.append(f'Vendor: {case_detail.vendor_name}')
                detail_parts.append(f'Betrag: {case_detail.total_amount} {case_detail.currency}')
                detail_parts.append(f'Status: {case_detail.status}')

                meta = case_detail.metadata or {}
                if meta.get('document_analysis'):
                    analysis = meta['document_analysis']
                    if analysis.get('document_number'):
                        detail_parts.append(f'Rechnungsnummer: {analysis["document_number"]}')
                    if analysis.get('document_date'):
                        detail_parts.append(f'Datum: {analysis["document_date"]}')
                    if analysis.get('line_items'):
                        items_lines = []
                        for item in analysis['line_items'][:10]:
                            desc = item.get('description', '?') if isinstance(item, dict) else str(item)
                            qty = item.get('quantity', '') if isinstance(item, dict) else ''
                            price = item.get('total_price', '') if isinstance(item, dict) else ''
                            if qty:
                                items_lines.append(f'    {qty}x {desc} — {price}')
                            else:
                                items_lines.append(f'    {desc} — {price}')
                        detail_parts.append('Positionen:\n' + '\n'.join(items_lines))
                    if analysis.get('sender'):
                        detail_parts.append(f'Absender: {analysis["sender"]}')
                    if analysis.get('iban'):
                        detail_parts.append(f'IBAN: {analysis["iban"]}')

                if meta.get('booking_proposal'):
                    bp = meta['booking_proposal']
                    detail_parts.append(f'Buchung: {bp.get("skr03_soll_name")} -> {bp.get("skr03_haben_name")}')

                _vorgang_text = 'Vorgang-Details:\n' + '\n'.join(f'  - {p}' for p in detail_parts)
                parts.insert(0, _vorgang_text)
            else:
                logger.debug('No case detail found for case ref %s', _effective_case_ref)
        except Exception as exc:
            logger.warning('Failed to build detailed case context for %s: %s', _effective_case_ref, exc)

    # Open cases
    if case_repository is not None and tenant_id is not None:
        try:
            all_cases = await case_repository.list_active_cases_for_tenant(tenant_id)
            open_count = len(all_cases)
            overdue = [c for c in all_cases if getattr(c, 'status', '') == 'OVERDUE']
            overdue_count = len(overdue)
            parts.append(f'Offene Vorgaenge: {open_count} (davon ueberfaellig: {overdue_count})')

            # Top 5 by urgency: OVERDUE first, then by created_at desc
            sorted_cases = sorted(
                all_cases,
                key=lambda c: (0 if getattr(c, 'status', '') == 'OVERDUE' else 1, getattr(c, 'created_at', None) or ''),
            )
            if sorted_cases:
                top_lines: list[str] = []
                for c in sorted_cases[:5]:
                    amount = getattr(c, 'total_amount', None)
                    amount_str = f'{amount} {getattr(c, "currency", "EUR")}' if amount else '-'
                    vendor = getattr(c, 'vendor_name', None) or '-'
                    status = getattr(c, 'status', '-')
                    case_num = getattr(c, 'case_number', str(getattr(c, 'id', '-')))
                    top_lines.append(f'  - {case_num}: {vendor}, {amount_str}, Status={status}')
                parts.append('Dringendste Vorgaenge:\n' + '\n'.join(top_lines))
        except Exception as _exc:
            logger.debug('system_context: case fetch failed: %s', _exc)

    # Recent audit events
    if audit_service is not None:
        try:
            recent = await audit_service.recent(limit=5)
            if recent:
                audit_lines: list[str] = []
                for ev in recent:
                    action = getattr(ev, 'action', '?')
                    result = str(getattr(ev, 'result', '-'))[:80]
                    agent = getattr(ev, 'agent_name', '-')
                    created = str(getattr(ev, 'created_at', ''))[:16]
                    audit_lines.append(f'  - [{created}] {action} / {result} ({agent})')
                parts.append('Letzte Aktivitaeten:\n' + '\n'.join(audit_lines))
        except Exception as _exc:
            logger.debug('system_context: audit fetch failed: %s', _exc)

    # User memory
    if user_memory is not None:
        try:
            interests = getattr(user_memory, 'known_interests', None)
            if interests:
                parts.append(f'Nutzer-Kontext: {", ".join(interests[:5])}')
        except Exception as exc:
            logger.debug('Failed to load user memory for system context: %s', exc)

    if not parts:
        return None
    return '[SYSTEMKONTEXT]\n' + '\n'.join(parts) + '\n[/SYSTEMKONTEXT]'


class TelegramCommunicatorService:
    """12-step communicator pipeline.

    Stateless: all state is in stores passed per-call.
    """

    async def try_handle_turn(
        self,
        normalized: TelegramNormalizedIngressMessage,
        case_id: str,
        *,
        audit_service: Any,
        open_items_service: Any,
        clarification_service: Any,
        conversation_store: ConversationMemoryStore | None = None,
        user_store: UserMemoryStore | None = None,
        llm_config_repository: Any = None,
        email_intake_repository: Any = None,
        case_repository: Any = None,
        chat_history_store: Any = None,
    ) -> CommunicatorResult | None:
        # ── Step 1: classify ────────────────────────────────────────────────
        intent = classify_intent(normalized.text)

        # ── Step 2: fall-through (no audit, no memory update) ───────────────
        if intent is None:
            return None

        # ── Step 3: guardrail ───────────────────────────────────────────────
        guardrail_passed, _guardrail_reason = check_guardrail(intent)

        # ── Step 4: load ConversationMemory ─────────────────────────────────
        chat_id = normalized.actor.chat_id
        conv_memory = None
        if conversation_store is not None:
            conv_memory = await conversation_store.load(chat_id)

        # ── Step 4b: load ChatHistory ────────────────────────────────────────
        chat_history: list[dict] = []
        if chat_history_store is not None:
            chat_history = await chat_history_store.load(chat_id)

        # ── Step 5: load UserMemory ──────────────────────────────────────────
        sender_id = normalized.actor.sender_id or chat_id
        prev_user_memory = None
        if user_store is not None:
            prev_user_memory = await user_store.load(sender_id)

        # ── Step 6: resolve context (only for context-needing intents) ───────
        core_ctx = None
        ctx_ref = None
        if intent in _CONTEXT_INTENTS:
            core_ctx, ctx_ref = await resolve_context(
                case_id,
                audit_service=audit_service,
                clarification_service=clarification_service,
                open_items_service=open_items_service,
            )

        # ── Step 6a: explicit doc-ref in user text ─────────────────────────
        _vendor_search_used = False
        if core_ctx is None or core_ctx.resolution_status == 'NOT_FOUND':
            _explicit_ref = extract_case_ref_from_text(normalized.text or '')
            if _explicit_ref:
                core_ctx = CommunicatorContextResolution(
                    resolution_status='FOUND',
                    resolved_case_ref=_explicit_ref,
                    context_reason='Explizite doc-Referenz im Text.',
                )

        # ── Step 6b: vendor-name fallback when context not found ───────────
        if (
            (core_ctx is None or core_ctx.resolution_status == 'NOT_FOUND')
            and case_repository is not None
        ):
            _tenant_for_vendor = None
            # Try tenant from current case_id
            if case_id and case_id != 'unknown':
                try:
                    import uuid as _uuid_mod
                    _co = await case_repository.get_case(_uuid_mod.UUID(case_id))
                    if _co:
                        _tenant_for_vendor = _co.tenant_id
                except Exception as exc:
                    logger.debug('Tenant lookup from case_id failed: %s', exc)
            # Fallback: try tenant from conversation memory
            if _tenant_for_vendor is None and conv_memory and conv_memory.last_case_ref:
                try:
                    import uuid as _uuid_mod
                    _co2 = await case_repository.get_case(_uuid_mod.UUID(conv_memory.last_case_ref))
                    if _co2:
                        _tenant_for_vendor = _co2.tenant_id
                except Exception as exc:
                    logger.debug('Tenant lookup from conv memory case ref failed: %s', exc)
            # Fallback: tenant resolver
            if _tenant_for_vendor is None:
                try:
                    from app.case_engine.tenant_resolver import resolve_tenant_id as _resolve_tid_v
                    _tid_v = await _resolve_tid_v()
                    if _tid_v:
                        import uuid as _uuid_mod
                        _tenant_for_vendor = _uuid_mod.UUID(_tid_v)
                except Exception as exc:
                    logger.debug('Tenant resolver fallback failed: %s', exc)

            if _tenant_for_vendor is not None:
                vendor_case_id = await search_case_by_vendor(
                    normalized.text or '', case_repository, _tenant_for_vendor,
                )
                if vendor_case_id:
                    core_ctx = CommunicatorContextResolution(
                        resolution_status='FOUND',
                        resolved_case_ref=vendor_case_id,
                        context_reason='Vendor-Name im Text erkannt.',
                    )
                    _vendor_search_used = True

        # ── Step 7: truth arbitration ────────────────────────────────────────
        arbitrator = TruthArbitrator()
        effective_ctx, truth_annotation = arbitrator.arbitrate(
            core_context=core_ctx,
            conv_memory=conv_memory,
            intent=intent,
        )

        memory_used = truth_annotation.truth_basis == 'CONVERSATION_MEMORY'
        conv_memory_ref = conv_memory.conversation_memory_ref if (memory_used and conv_memory) else None

        # ── Step 7b: email arrival enrichment for DOCUMENT_ARRIVAL_CHECK ──────
        email_arrival_info: str | None = None
        if intent == 'DOCUMENT_ARRIVAL_CHECK' and email_intake_repository is not None:
            try:
                sender_id = normalized.actor.sender_id or normalized.actor.chat_id
                recent_emails = await email_intake_repository.find_by_user_ref(sender_id, limit=1)
                if recent_emails:
                    latest = recent_emails[0]
                    received_str = (
                        latest.received_at.strftime('%d.%m.%Y %H:%M')
                        if hasattr(latest.received_at, 'strftime')
                        else str(latest.received_at)[:16]
                    )
                    email_arrival_info = (
                        f'[EMAIL_ANKUNFT] Letzte E-Mail empfangen: {received_str} '
                        f'| Betreff: {latest.subject or "-"} '
                        f'| Anhaenge: {latest.attachment_count} '
                        f'| Status: {latest.intake_status} [/EMAIL_ANKUNFT]'
                    )
            except Exception as _email_exc:
                logger.debug('Email arrival check failed: %s', _email_exc)

        # ── Step 8: response (guardrail / LLM / template / fallback) ─────────
        llm_called = False
        model_used: str | None = None
        _llm_suggestions: list[dict] = []
        _invoice_data: dict | None = None

        if not guardrail_passed:
            # Hard guardrail: template response, no LLM call ever
            reply_text, response_type = build_response(
                intent,
                effective_ctx,
                guardrail_passed=False,
                truth_annotation=truth_annotation,
            )
            response_source = 'GUARDRAIL'

        else:
            # Guardrail passed: resolve LLM config
            _repo = llm_config_repository
            model_str = ''
            llm_config: dict = {}

            if _repo is None:
                try:
                    from app.dependencies import get_llm_config_repository as _get_repo
                    _repo = _get_repo()
                except Exception as exc:
                    logger.debug('Failed to get LLM config repository: %s', exc)
                    _repo = None

            if _repo is not None:
                try:
                    llm_config = await _repo.get_config_or_fallback('communicator')
                    model_str = (llm_config.get('model') or '').strip()
                except Exception as exc:
                    logger.warning('Failed to load communicator LLM config: %s', exc)
                    model_str = ''

            if not model_str:
                # No model configured → template response, no error logged
                reply_text, response_type = build_response(
                    intent,
                    effective_ctx,
                    guardrail_passed=True,
                    truth_annotation=truth_annotation,
                )
                response_source = 'TEMPLATE'

            else:
                # Model configured → attempt LLM call
                provider = (llm_config.get('provider') or '').strip()
                # IONOS uses OpenAI-compatible endpoint: prefix with 'openai/'
                if provider == 'ionos':
                    full_model = f'openai/{model_str}'
                elif provider and '/' not in model_str:
                    full_model = f'{provider}/{model_str}'
                else:
                    full_model = model_str

                try:
                    api_key = _repo.decrypt_key_for_call(llm_config) if _repo else None
                    base_url = llm_config.get('base_url') or None

                    # Resolve case_repository from dependencies if not passed
                    _case_repo = case_repository
                    if _case_repo is None:
                        try:
                            from app.dependencies import get_case_repository as _get_case_repo
                            _case_repo = _get_case_repo()
                        except Exception as exc:
                            logger.debug('Failed to get case repository: %s', exc)
                            _case_repo = None

                    # Determine tenant_id for open-cases lookup
                    _tenant_id = None
                    if _case_repo is not None and case_id and case_id != 'unknown':
                        try:
                            import uuid as _uuid_mod
                            _case_obj = await _case_repo.get_case(_uuid_mod.UUID(case_id))
                            if _case_obj is not None:
                                _tenant_id = _case_obj.tenant_id
                        except (ValueError, AttributeError) as exc:
                            logger.debug('case_id is not a UUID (e.g. tg-chat-msg, doc-N): %s', exc)
                        except Exception as exc:
                            logger.warning('Failed to resolve tenant from case_id: %s', exc)

                    # Fallback: resolve tenant from default tenant resolver
                    if _tenant_id is None:
                        try:
                            from app.case_engine.tenant_resolver import resolve_tenant_id as _resolve_tid
                            _tid_str = await _resolve_tid()
                            if _tid_str:
                                import uuid as _uuid_mod
                                _tenant_id = _uuid_mod.UUID(_tid_str)
                        except Exception as exc:
                            logger.debug('Tenant resolver fallback failed: %s', exc)

                    # Prefer core_ctx (vendor search / context resolver) over effective_ctx
                    # because truth arbitrator returns None for non-context intents
                    _resolved_ref = (
                        (core_ctx.resolved_case_ref if core_ctx and core_ctx.resolution_status == 'FOUND' else None)
                        or (effective_ctx.resolved_case_ref if effective_ctx else None)
                    )
                    # Try Memory Curator for rich context (primary path)
                    sys_ctx = None
                    try:
                        from app.memory_curator.service import build_memory_curator_service
                        from app.config import get_settings as _get_mem_settings
                        from app.dependencies import get_accounting_repository
                        _mem_settings = _get_mem_settings()
                        _mem_curator = build_memory_curator_service(
                            data_dir=_mem_settings.data_dir,
                            llm_config_repository=_repo,
                            case_repository=_case_repo,
                            audit_service=audit_service,
                            accounting_repository=get_accounting_repository(),
                        )
                        sys_ctx = await _mem_curator.get_context_assembly(
                            _tenant_id,
                            conversation_memory=conv_memory,
                            effective_case_ref=_resolved_ref,
                        )
                    except Exception as _mem_exc:
                        logger.warning('Memory Curator failed, falling back: %s', _mem_exc)

                    # Fallback to _build_system_context if Memory Curator fails
                    if not sys_ctx:
                        sys_ctx = await _build_system_context(
                            tenant_id=_tenant_id,
                            case_repository=_case_repo,
                            audit_service=audit_service,
                            user_memory=prev_user_memory,
                            conv_memory=conv_memory,
                            effective_case_ref=_resolved_ref,
                        )
                    if intent == 'GENERAL_CONVERSATION':
                        sys_ctx = (sys_ctx or '') + _GENERAL_CONVERSATION_PERSONALITY

                    # Prefer core_ctx over effective_ctx for FALLKONTEXT —
                    # truth arbitrator returns None for non-context intents,
                    # but core_ctx has the doc-ref / vendor search result.
                    _ctx_for_payload = effective_ctx
                    if _ctx_for_payload is None and core_ctx and core_ctx.resolution_status == 'FOUND':
                        _ctx_for_payload = core_ctx
                    # Aufgabe 1: Provider-based context filtering
                    _ctx_for_llm = sys_ctx
                    if _ctx_for_llm and provider not in ('bedrock',):
                        _ctx_for_llm = _filter_sensitive_context(_ctx_for_llm)
                        logger.info(
                            'Trust-Boundary: provider=%s — sensible Felder gefiltert '
                            '(IBAN, Steuernummern). Für vollen Kontext: Bedrock EU nutzen.',
                            provider,
                        )
                    elif _ctx_for_llm and provider == 'bedrock':
                        logger.info('Trust-Boundary: provider=bedrock — voller Kontext, keine Filterung.')

                    payload = build_llm_context_payload(
                        intent=intent,
                        context_resolution=_ctx_for_payload,
                        truth_annotation=truth_annotation,
                        conversation_memory=conv_memory,
                        user_message=normalized.text or '',
                        system_context=_ctx_for_llm,
                        provider=provider,
                        chat_history=chat_history,
                    )
                    # Prepend email arrival info for DOCUMENT_ARRIVAL_CHECK
                    if email_arrival_info and intent == 'DOCUMENT_ARRIVAL_CHECK':
                        msgs = payload['messages']
                        for msg in msgs:
                            if msg.get('role') == 'user':
                                msg['content'] = f'{email_arrival_info}\n{msg["content"]}'
                                break

                    # ── Prompt-injection guard ────────────────────────────────
                    from app.security.input_sanitizer import sanitize_user_message as _sanitize_msg
                    _inj = _sanitize_msg(normalized.text or '')
                    if _inj.is_blocked:
                        await audit_service.log_event({
                            'event_id': 'sec-' + uuid.uuid4().hex[:12],
                            'action': 'PROMPT_INJECTION_BLOCKED',
                            'agent_name': 'frya-communicator',
                            'result': f'risk_score={_inj.risk_score:.2f}',
                            'case_id': case_id,
                            'approval_status': 'NOT_REQUIRED',
                            'llm_output': {'patterns': _inj.detected_patterns},
                        })
                        reply_text = (
                            'FRYA: Ich konnte deine Nachricht nicht verarbeiten. '
                            'Bitte formuliere sie um.'
                        )
                        response_type = 'COMMUNICATOR_REPLY_SAFE_HELP'
                        response_source = 'INJECTION_GUARD'
                    else:
                        call_kwargs: dict = {
                            'model': full_model,
                            'messages': payload['messages'],
                            'max_tokens': 450,
                            'timeout': _LLM_TIMEOUT,
                        }
                        # Bedrock uses AWS env vars (AWS_ACCESS_KEY_ID etc.)
                        # — don't pass api_key/api_base which would override
                        if provider != 'bedrock':
                            if api_key:
                                call_kwargs['api_key'] = api_key
                            if base_url:
                                call_kwargs['api_base'] = base_url

                        try:
                            resp = await litellm.acompletion(**call_kwargs)
                        except (litellm.exceptions.APIError, litellm.exceptions.Timeout,
                                litellm.exceptions.InternalServerError) as fallback_exc:
                            # Anthropic overloaded / timeout → fallback to IONOS Mistral
                            logger.warning(
                                'Primary LLM (%s) failed: %s. Falling back to IONOS Mistral.',
                                full_model, fallback_exc,
                            )
                            import os as _fb_os
                            _fb_base = _fb_os.environ.get(
                                'IONOS_API_BASE',
                                'https://openai.inference.de-txl.ionos.com/v1',
                            )
                            _fb_key = _fb_os.environ.get('IONOS_API_KEY', '')
                            if _fb_key:
                                resp = await litellm.acompletion(
                                    model='openai/Mistral-Small-24B-Instruct-2501',
                                    messages=call_kwargs['messages'],
                                    max_tokens=300,
                                    timeout=_LLM_TIMEOUT,
                                    api_key=_fb_key,
                                    api_base=_fb_base,
                                )
                                logger.info('Fallback to IONOS Mistral succeeded.')
                            else:
                                raise  # No fallback key → re-raise original error

                        # Token tracking
                        try:
                            from app.token_tracking import log_token_usage as _log_usage
                            from app.config import get_settings as _ts
                            await _log_usage(
                                database_url=_ts().database_url,
                                tenant_id='default',
                                agent_id='communicator',
                                model=full_model,
                                provider=provider,
                                response=resp,
                                case_id=case_id,
                            )
                        except Exception as exc:
                            logger.debug('Token usage logging failed: %s', exc)

                        raw_text = (resp.choices[0].message.content or '').strip()

                        # Parse INVOICE_DATA from communicator response
                        raw_text, _invoice_data = _parse_invoice_data(raw_text)

                        # Aufgabe 3: Parse LLM-generated suggestions
                        raw_text, _llm_suggestions = _parse_llm_suggestions(raw_text)

                        # Ensure FRYA: prefix
                        if not raw_text.startswith('FRYA:'):
                            raw_text = f'FRYA: {raw_text}'

                        # Append uncertainty suffix for CONVERSATION_MEMORY truth basis
                        if (
                            truth_annotation.requires_uncertainty_phrase
                            and UNCERTAINTY_SUFFIX not in raw_text
                        ):
                            raw_text = f'{raw_text} {UNCERTAINTY_SUFFIX}'

                        reply_text = raw_text
                        response_type = _INTENT_RESPONSE_TYPES.get(intent, 'COMMUNICATOR_REPLY_STATUS')
                        llm_called = True
                        model_used = getattr(resp, 'model', None) or full_model
                        response_source = 'LLM'

                        if chat_history_store is not None and reply_text:
                            await chat_history_store.append(chat_id, normalized.text or '', reply_text)

                        # Save reminder for REMINDER_PERSONAL intent
                        if intent == 'REMINDER_PERSONAL':
                            try:
                                from app.config import get_settings as _rs
                                from datetime import datetime, timedelta, timezone
                                import asyncpg as _apg
                                _db = _rs().database_url
                                if not _db.startswith('memory://'):
                                    _remind_at = datetime.now(timezone.utc) + timedelta(days=1)
                                    _remind_at = _remind_at.replace(hour=9, minute=0, second=0)
                                    _conn = await _apg.connect(_db)
                                    try:
                                        await _conn.execute(
                                            "INSERT INTO frya_reminders (tenant_id, user_id, chat_id, reminder_text, remind_at) "
                                            "VALUES ($1, $2, $3, $4, $5)",
                                            'default', sender_id, chat_id,
                                            (normalized.text or '')[:500], _remind_at,
                                        )
                                    finally:
                                        await _conn.close()
                            except Exception as _re:
                                logger.debug('reminder save failed: %s', _re)

                except Exception as exc:
                    if intent == 'CREATE_INVOICE':
                        reply_text = (
                            'FRYA: Die Rechnung konnte gerade nicht erstellt werden. '
                            'Bitte versuche es nochmal.'
                        )
                    elif intent == 'GENERAL_CONVERSATION':
                        reply_text = (
                            'FRYA: Ich konnte deine Nachricht gerade nicht verarbeiten. '
                            'Versuch es in ein paar Sekunden nochmal.'
                        )
                    else:
                        reply_text = (
                            'FRYA: Da ist etwas schiefgelaufen. '
                            'Bitte versuche es nochmal.'
                        )
                    response_type = 'COMMUNICATOR_REPLY_FALLBACK'
                    response_source = 'FALLBACK'
                    logger.warning('LLM call failed for communicator turn: %s', exc)

                    await audit_service.log_event({
                        'event_id': 'comm-err-' + uuid.uuid4().hex[:12],
                        'action': 'COMMUNICATOR_LLM_ERROR',
                        'agent_name': 'frya-communicator',
                        'result': 'LLM_CALL_FAILED',
                        'case_id': case_id,
                        'llm_output': {
                            'error_message': f'{type(exc).__name__}: {str(exc)[:200]}',
                            'intent': intent,
                        },
                    })

        # ── Step 9: build CommunicatorTurn ──────────────────────────────────
        turn_ref = 'comm-' + uuid.uuid4().hex[:12]

        memory_types_used: list[str] = []
        if memory_used:
            memory_types_used.append('conversation_memory')
        if user_store is not None:
            memory_types_used.append('user_memory')

        routing_status = (
            'COMMUNICATOR_GUARDRAIL_TRIGGERED' if not guardrail_passed
            else 'COMMUNICATOR_HANDLED'
        )

        turn = CommunicatorTurn(
            communicator_turn_ref=turn_ref,
            intent=intent,
            guardrail_passed=guardrail_passed,
            truth_basis=truth_annotation.truth_basis,
            memory_used=memory_used,
            conversation_memory_ref=conv_memory_ref,
            response_type=response_type,
            context_resolution=effective_ctx,
            memory_types_used=memory_types_used,
            llm_called=llm_called,
            model_used=model_used,
            response_source=response_source,
        )

        # ── Step 10: audit ───────────────────────────────────────────────────
        llm_output: dict = {
            'communicator_turn_ref': turn_ref,
            'intent': intent,
            'guardrail_passed': guardrail_passed,
            'truth_basis': truth_annotation.truth_basis,
            'memory_used': memory_used,
            'response_type': response_type,
            'memory_types_used': memory_types_used,
            'context_resolution': (
                effective_ctx.model_dump(mode='json') if effective_ctx else None
            ),
            'llm_called': llm_called,
            'model_used': model_used,
            'response_source': response_source,
        }
        await audit_service.log_event({
            'event_id': 'comm-evt-' + uuid.uuid4().hex[:12],
            'action': 'COMMUNICATOR_TURN_PROCESSED',
            'agent_name': 'frya-communicator',
            'result': intent,
            'case_id': case_id,
            'llm_output': llm_output,
        })

        # ── Step 11: update conversation memory ──────────────────────────────
        if conversation_store is not None:
            updated_conv = build_updated_conversation_memory(
                chat_id=chat_id,
                prev_memory=conv_memory,
                intent=intent,
                resolved_case_ref=effective_ctx.resolved_case_ref if effective_ctx else None,
                resolved_document_ref=effective_ctx.resolved_document_ref if effective_ctx else None,
                resolved_clarification_ref=effective_ctx.resolved_clarification_ref if effective_ctx else None,
                resolved_open_item_id=effective_ctx.resolved_open_item_id if effective_ctx else None,
                context_resolution_status=effective_ctx.resolution_status if effective_ctx else None,
                is_search_result=_vendor_search_used,
            )
            await conversation_store.save(updated_conv)

        # ── Step 12: update user memory ───────────────────────────────────────
        if user_store is not None:
            new_user_mem = build_or_update_user_memory(
                sender_id=sender_id,
                prev_memory=prev_user_memory,
                intent=intent,
            )
            await user_store.save(new_user_mem)

        return CommunicatorResult(
            handled=True,
            routing_status=routing_status,
            turn=turn,
            reply_text=reply_text,
            llm_suggestions=_llm_suggestions,
            invoice_data=_invoice_data,
        )
