from __future__ import annotations

import logging
import re
import uuid
from typing import Any

from app.telegram.communicator.models import CommunicatorContextResolution

logger = logging.getLogger(__name__)

# Open item statuses that count as "still open" (user/data pending)
_ACTIVE_STATUSES = frozenset({'OPEN', 'WAITING_USER', 'WAITING_DATA', 'SCHEDULED'})
_DONE_STATUSES = frozenset({'COMPLETED', 'CANCELLED', 'DONE'})


async def resolve_context(
    case_id: str,
    *,
    audit_service: Any,
    clarification_service: Any,
    open_items_service: Any,
) -> tuple[CommunicatorContextResolution, str]:
    """Resolve conservative context for a communicator turn.

    Pulls from:
    - Audit trail: latest document_ref for this case
    - Clarification DB: latest open clarification + question text
    - Open Items DB: active open item(s), their state and human title

    Status logic:
    - FOUND: any of doc/clarification/open-item resolved
    - AMBIGUOUS: multiple distinct active open items (returned conservatively as first)
    - NOT_FOUND: nothing found for this case

    Conservative rule: prefers NOT_FOUND over hallucination. No cross-case lookups.
    """
    ctx_ref = 'ctx-' + str(uuid.uuid4())[:8]

    # ── 1. Latest document from audit trail ──────────────────────────────────
    latest_doc: str | None = None
    try:
        events = await audit_service.by_case(case_id, limit=200)
        for ev in reversed(events):
            doc_ref = getattr(ev, 'document_ref', None)
            if doc_ref:
                latest_doc = doc_ref
                break
    except Exception:
        events = []

    # ── 2. Latest open clarification ─────────────────────────────────────────
    clar_ref: str | None = None
    clar_question: str | None = None
    try:
        clar = await clarification_service.latest_by_case(case_id)
        if clar and getattr(clar, 'clarification_state', None) == 'OPEN':
            clar_ref = clar.clarification_ref
            # Pull actual question text for natural response
            raw_q = getattr(clar, 'question_text', None)
            if raw_q:
                # Truncate to 200 chars — avoid leaking full operator prompt
                clar_question = raw_q[:200].strip()
    except Exception as exc:
        logger.warning('resolve_context: clarification lookup failed: %s', exc)

    # ── 3. Active open items ─────────────────────────────────────────────────
    active_item_id: str | None = None
    open_item_state: str | None = None
    open_item_title: str | None = None
    has_multiple = False
    try:
        items = await open_items_service.list_by_case(case_id)
        active_items = [
            it for it in items
            if getattr(it, 'status', None) not in _DONE_STATUSES
        ]
        if len(active_items) >= 2:
            has_multiple = True
        if active_items:
            first = active_items[0]
            active_item_id = first.item_id
            open_item_state = getattr(first, 'status', None)
            # Use title; fall back to first 80 chars of description
            title = getattr(first, 'title', None)
            if not title:
                desc = getattr(first, 'description', None)
                title = desc[:80] if desc else None
            open_item_title = title
    except Exception as exc:
        logger.warning('resolve_context: open items lookup failed: %s', exc)

    has_context = bool(latest_doc or clar_ref or active_item_id)

    # Determine resolution status
    if has_context and has_multiple:
        resolution_status = 'AMBIGUOUS'
        reason = 'Mehrere offene Punkte gefunden — zeige den aktuellsten.'
    elif has_context:
        resolution_status = 'FOUND'
        reason = 'Fallkontext aufgeloest.'
    else:
        resolution_status = 'NOT_FOUND'
        reason = 'Kein Kontext fuer diesen Fall gefunden.'

    return CommunicatorContextResolution(
        resolution_status=resolution_status,
        resolved_case_ref=case_id if has_context else None,
        resolved_document_ref=latest_doc,
        resolved_clarification_ref=clar_ref,
        resolved_open_item_id=active_item_id,
        context_reason=reason,
        open_item_state=open_item_state,
        open_item_title=open_item_title,
        clarification_question=clar_question,
        has_multiple_open_items=has_multiple,
    ), ctx_ref


def extract_case_ref_from_text(text: str) -> str | None:
    """Extract doc-reference from user text. Returns 'doc-N' or None."""
    if not text:
        return None
    # Patterns: "doc 26", "doc-26", "Doc26", "doc26"
    m = re.search(r'\bdoc[- ]?(\d+)\b', text, re.IGNORECASE)
    if m:
        return f'doc-{m.group(1)}'
    # "Vorgang 26", "Fall 26", "ref 26"
    m = re.search(r'\b(?:vorgang|fall|ref)\s*(\d+)\b', text, re.IGNORECASE)
    if m:
        return f'doc-{m.group(1)}'
    return None


async def search_case_by_vendor(
    text: str,
    case_repository: Any,
    tenant_id: Any,
) -> str | None:
    """Search for a case whose vendor_name matches text from the user message.

    Returns case_id (str) or None.
    """
    if not text or case_repository is None or tenant_id is None:
        return None

    # Include DRAFT cases — users often ask about recently uploaded documents
    all_cases = await case_repository.list_active_cases_for_tenant(tenant_id)
    try:
        draft_cases = await case_repository.list_cases_by_status(tenant_id, 'DRAFT')
        # Merge without duplicates
        seen_ids = {c.id for c in all_cases}
        for dc in draft_cases:
            if dc.id not in seen_ids:
                all_cases.append(dc)
    except Exception as exc:
        logger.debug('search_case_by_vendor: list_cases_by_status unavailable: %s', exc)
    text_lower = text.lower()

    # Pass 1: vendor name appears in user text (or vice versa)
    for case in all_cases:
        vendor = (getattr(case, 'vendor_name', None) or '').lower()
        if not vendor:
            continue
        if vendor in text_lower or text_lower in vendor:
            return str(case.id)

    # Pass 2: any word >3 chars from user text matches inside a vendor name
    words = [w.strip('?!.,;:()[]{}"\'/') for w in text_lower.split()]
    words = [w for w in words if len(w) > 3]
    for case in all_cases:
        vendor = (getattr(case, 'vendor_name', None) or '').lower()
        if not vendor:
            continue
        if any(word in vendor for word in words):
            return str(case.id)

    return None
