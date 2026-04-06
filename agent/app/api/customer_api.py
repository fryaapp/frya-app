"""P-41: Customer-facing REST API endpoints."""
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, UploadFile, WebSocket, WebSocketDisconnect, Query
from pydantic import BaseModel, Field

from app.auth.dependencies import require_authenticated
from app.auth.models import AuthUser

logger = logging.getLogger(__name__)

router = APIRouter(prefix='/api/v1', tags=['customer'])


async def _ensure_tenant_uuid(username: str, raw_tid: str | None) -> uuid.UUID:
    """P-33/P-35: Ensure every user has a valid, persistent UUID tenant.

    1. If raw_tid is already a valid UUID → return it.
    2. Otherwise compute deterministic uuid5 from the raw string.
    3. If raw_tid is None/empty, use 'default' as seed (single-tenant legacy mode).
       This matches bulk_upload._get_tenant_id() which also falls through to 'default'.
    4. Auto-provision: create row in frya_tenants + update frya_users if missing.

    This is idempotent — safe to call on every login/refresh.
    P-35 FIX: Use 'default' (not username) as seed when raw_tid is None, to stay
    consistent with the uuid5(NAMESPACE_DNS, 'default') = 916180a7... used by uploads.
    """
    # Determine the UUID we want to use
    if raw_tid:
        try:
            return uuid.UUID(str(raw_tid))
        except ValueError:
            pass
    # P-35: Use 'default' as fallback seed (not username) — matches bulk_upload logic
    seed = raw_tid if raw_tid else 'default'
    tenant_uuid = uuid.uuid5(uuid.NAMESPACE_DNS, seed)

    # Auto-provision: create tenant row if it doesn't exist
    try:
        from app.dependencies import get_db_pool as _get_pool
        pool = _get_pool()
        if pool:
            async with pool.acquire() as conn:
                tid_str = str(tenant_uuid)
                # Insert tenant row (idempotent)
                await conn.execute(
                    """INSERT INTO frya_tenants (tenant_id, name, status)
                       VALUES ($1, $2, 'active')
                       ON CONFLICT (tenant_id) DO NOTHING""",
                    tid_str,
                    f'Tenant {username}',
                )
                # Update user record so next login skips this path
                await conn.execute(
                    """UPDATE frya_users SET tenant_id = $1
                       WHERE username = $2 AND (tenant_id IS NULL OR tenant_id = $3)""",
                    tid_str,
                    username,
                    raw_tid or '',
                )
    except Exception as _e:
        logger.warning('P-33: auto-provision tenant failed for %s: %s', username, _e)

    return tenant_uuid


async def _resolve_tenant_uuid(user=None) -> uuid.UUID:
    """Resolve tenant UUID from authenticated user.

    Delegates to _ensure_tenant_uuid so every account always gets
    a consistent, valid UUID — even if tenant_id is missing or non-UUID.
    """
    username = getattr(user, 'username', None) or 'unknown' if user else 'unknown'
    raw_tid = getattr(user, 'tenant_id', None) if user else None
    return await _ensure_tenant_uuid(username, str(raw_tid) if raw_tid else None)


_TRANSLATIONS: dict | None = None

def _get_translations() -> dict:
    global _TRANSLATIONS
    if _TRANSLATIONS is None:
        import yaml
        from pathlib import Path
        _path = Path(__file__).resolve().parent.parent.parent / 'data' / 'config' / 'ui_translations.yaml'
        with open(_path, encoding='utf-8') as f:
            _TRANSLATIONS = yaml.safe_load(f)
    return _TRANSLATIONS


# ---------------------------------------------------------------------------
# TASK 2: POST /chat
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)

class ChatResponse(BaseModel):
    reply: str
    case_ref: str | None = None
    suggestions: list[str] = Field(default_factory=list)
    content_blocks: list[dict] = Field(default_factory=list)
    actions: list[dict] = Field(default_factory=list)
    routing: str | None = None

@router.post('/chat')
async def send_chat_message(
    body: ChatRequest,
    user: AuthUser = Depends(require_authenticated),
) -> ChatResponse:
    """Send a message to Frya and get a synchronous reply."""
    # P-22: Token-Tracking Kontext setzen
    from app.token_tracking import set_tracking_context
    _tid = str(user.tenant_id) if user and getattr(user, 'tenant_id', None) else 'default'
    set_tracking_context(tenant_id=_tid, agent_id='communicator')

    from app.dependencies import (
        get_audit_service, get_case_repository, get_chat_history_store,
        get_communicator_conversation_store, get_communicator_user_store,
        get_open_items_service, get_telegram_clarification_service,
        get_telegram_communicator_service,
    )
    from app.telegram.communicator.intent_classifier import classify_intent
    from app.telegram.models import TelegramActor, TelegramNormalizedIngressMessage

    chat_id = f'web-{user.username}'
    case_id = f'web-chat-{user.username}-{uuid.uuid4().hex[:8]}'
    _evt_id = f'web-evt-{uuid.uuid4().hex[:12]}'

    normalized = TelegramNormalizedIngressMessage(
        event_id=_evt_id,
        text=body.message,
        telegram_update_ref=f'web-update-{_evt_id}',
        telegram_message_ref=f'web-msg-{_evt_id}',
        telegram_chat_ref=f'web:{user.username}',
        actor=TelegramActor(chat_id=chat_id, sender_id=user.username, sender_username=user.username),
        media_attachments=[],
    )

    # P-12: APPROVE shortcircuit — execute booking approval BEFORE communicator
    try:
        from app.api.chat_ws import _get_tiered_orchestrator
        _pre_orch = _get_tiered_orchestrator()
        if _pre_orch:
            _pre_route = await _pre_orch.route(message=body.message)
            _pre_intent = _pre_route.get('intent')
            if _pre_intent == 'APPROVE':
                from app.agents.service_registry import _InboxService
                _inbox_svc = _InboxService()
                _approve_cid = None
                # Find case by vendor name in text
                import re as _re_ap
                _case_match = _re_ap.search(r'CASE-\d{4}-\d{5}', body.message)
                if _case_match:
                    import asyncpg as _apg_ap
                    from app.dependencies import get_settings as _gs_ap
                    _ap_tenant = await _resolve_tenant_uuid(user)
                    _conn_ap = await _apg_ap.connect(_gs_ap().database_url)
                    try:
                        _cr = await _conn_ap.fetchrow("SELECT id FROM case_cases WHERE case_number = $1 AND tenant_id = $2", _case_match.group(0), str(_ap_tenant))
                        if _cr:
                            _approve_cid = str(_cr['id'])
                    finally:
                        await _conn_ap.close()
                else:
                    # P-12b: Match vendor name against PENDING approvals via DB join
                    _text_low = body.message.lower()
                    _stop = {'gmbh', 'ag', 'ug', 'kg', 'ohg', 'se', 'co', 'mbh',
                             'freigeben', 'buchen', 'genehmigen', 'beleg', 'rechnung',
                             'bitte', 'den', 'die', 'das', 'der', 'und', 'oder', 'von'}
                    _tw = set(_text_low.split()) - _stop
                    try:
                        import asyncpg as _apg_rest
                        from app.dependencies import get_settings as _gs_rest
                        _conn_rest = await _apg_rest.connect(_gs_rest().database_url)
                        try:
                            _pr_rows = await _conn_rest.fetch("""
                                SELECT a.case_id AS approval_case_id, cc.id AS case_uuid, cc.vendor_name
                                FROM frya_approvals a
                                JOIN case_documents cd ON cd.document_source_id::text = REPLACE(a.case_id, 'doc-', '')
                                JOIN case_cases cc ON cc.id = cd.case_id
                                WHERE a.status = 'PENDING' AND a.action_type = 'booking_finalize'
                                  AND cc.vendor_name IS NOT NULL
                            """)
                            _best = (None, 0)
                            for _pr in _pr_rows:
                                _vn = _pr['vendor_name'].lower()
                                if any(w in _vn for w in _tw if len(w) >= 4):
                                    _vw = set(_vn.split()) - _stop
                                    _ov = len(_tw & _vw)
                                    if _ov > _best[1]:
                                        _best = (str(_pr['case_uuid']), _ov)
                            if _best[0] and _best[1] >= 1:
                                _approve_cid = _best[0]
                        finally:
                            await _conn_rest.close()
                    except Exception:
                        pass

                if _approve_cid:
                    _ap_result = await _inbox_svc.approve(case_id=_approve_cid)
                    if _ap_result.get('status') == 'approved':
                        _next = _ap_result.get('next_item')
                        _next_text = ''
                        if _next:
                            _next_text = f"\n\nNaechster Beleg: {_next.get('vendor', '?')} ({_next.get('amount', '?')} EUR)"
                        return ChatResponse(
                            reply=f'Freigabe erledigt. Buchung erstellt.{_next_text}',
                            suggestions=['Naechster Beleg', 'Inbox', 'Finanzen'],
                            content_blocks=[{'block_type': 'alert', 'data': {'severity': 'success', 'text': 'Buchung freigegeben und erstellt.'}}],
                            actions=[],
                        )
                    elif _ap_result.get('status') == 'no_pending':
                        pass  # Fall through to communicator
    except Exception as _ae:
        logger.warning('REST APPROVE shortcircuit failed: %s', _ae)

    communicator = get_telegram_communicator_service()
    result = await communicator.try_handle_turn(
        normalized, case_id,
        audit_service=get_audit_service(),
        open_items_service=get_open_items_service(),
        clarification_service=get_telegram_clarification_service(),
        conversation_store=get_communicator_conversation_store(),
        user_store=get_communicator_user_store(),
        case_repository=get_case_repository(),
        chat_history_store=get_chat_history_store(),
    )

    if result is None or not result.reply_text:
        return ChatResponse(reply='Ich konnte deine Nachricht nicht verarbeiten.', suggestions=[])

    # Strip "FRYA:" prefix
    reply_raw = result.reply_text
    if reply_raw.startswith('FRYA:'):
        reply_raw = reply_raw[5:].strip()
    result.reply_text = reply_raw

    # --- Name-update side-effect (same as WS handler) ---
    from app.api.chat_ws import _extract_name_intent, _persist_display_name, _extract_and_persist_business_info
    extracted_name = _extract_name_intent(body.message)
    tenant_id = getattr(user, 'tenant_id', '') or ''
    if extracted_name:
        await _persist_display_name(user.username, tenant_id, extracted_name)

    # --- Business info extraction (hourly rate, company, tax) ---
    await _extract_and_persist_business_info(body.message, user.username, tenant_id)

    conv_store = get_communicator_conversation_store()
    conv_mem = await conv_store.load(chat_id)
    case_ref = conv_mem.last_case_ref if conv_mem else None

    intent = classify_intent(body.message)
    suggestions = _build_suggestions(intent, case_ref)

    # --- TieredOrchestrator + ResponseBuilder integration ---
    content_blocks: list[dict] = []
    actions: list[dict] = []
    routing: str | None = None
    try:
        from app.api.chat_ws import _get_tiered_orchestrator, _get_response_builder
        orchestrator = _get_tiered_orchestrator()
        if orchestrator:
            routing_result = await orchestrator.route(message=body.message)
            tier_intent = routing_result.get('intent')
            routing = routing_result.get('routing')

            # Fetch real data for content_blocks
            agent_results: dict = {}
            if tier_intent and routing in ('regex', 'fast'):
                try:
                    from app.agents.service_registry import build_service_registry
                    _i2s = {
                        'SHOW_INBOX': ('inbox_service', 'list_pending'),
                        'SHOW_FINANCE': ('euer_service', 'get_finance_summary'),
                        'SHOW_DEADLINES': ('deadline_service', 'list'),
                        'SHOW_BOOKINGS': ('booking_service', 'list'),
                        'SHOW_OPEN_ITEMS': ('open_item_service', 'list'),
                    }
                    si = _i2s.get(tier_intent)
                    if si:
                        # P-34 FIX: Always pass tenant_id so service_registry
                        # doesn't fall back to resolve_tenant_id() → None → empty inbox
                        _svc_tenant_id: str | None = None
                        try:
                            _svc_tenant_id = str(await _resolve_tenant_uuid(user))
                        except Exception:
                            pass
                        reg = build_service_registry()
                        svc = reg.get(si[0])
                        if svc:
                            m = getattr(svc, si[1], None)
                            if m:
                                agent_results = await m(tenant_id=_svc_tenant_id) or {}
                except Exception:
                    pass

            rb = _get_response_builder()
            if rb and tier_intent:
                _rest_llm_sugg = getattr(result, 'llm_suggestions', []) or []
                enhanced = rb.build(
                    intent=tier_intent, agent_results=agent_results,
                    communicator_text=result.reply_text,
                    llm_suggestions=_rest_llm_sugg,
                )
                content_blocks = enhanced.get('content_blocks', [])
                actions = enhanced.get('actions', [])
                if actions:
                    suggestions = [a['chat_text'] for a in actions[:3]]
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning('REST chat integration failed: %s', exc)

    # --- Invoice Pipeline: INVOICE_DATA from communicator ---
    # If communicator returned structured INVOICE_DATA, create draft + preview.
    # NO auto_send — every invoice MUST show preview + require user approval.
    _invoice_data = getattr(result, 'invoice_data', None)
    if _invoice_data and isinstance(_invoice_data, dict):
        try:
            from app.services.invoice_pipeline import handle_create_invoice
            pipeline_result = await handle_create_invoice(_invoice_data, user.username, tenant_id=str(user.tenant_id) if getattr(user, 'tenant_id', None) else None)
            result.reply_text = pipeline_result.get('text', result.reply_text)
            content_blocks = pipeline_result.get('content_blocks', [])
            actions = pipeline_result.get('actions', [])
            if actions:
                suggestions = [a['chat_text'] for a in actions[:3]]
            logger.info('Invoice pipeline: draft created from INVOICE_DATA (REST)')
        except Exception as exc:
            logger.error('Invoice pipeline failed (REST): %s', exc)
            result.reply_text = f'Rechnung konnte nicht erstellt werden: {exc}'

    return ChatResponse(
        reply=result.reply_text, case_ref=case_ref, suggestions=suggestions,
        content_blocks=content_blocks, actions=actions, routing=routing,
    )

def _build_suggestions(intent: str | None, case_ref: str | None) -> list[str]:
    if case_ref:
        return ['Details anzeigen', 'Buchen', 'Rechnung suchen']
    if intent == 'GREETING':
        return ['Status-Übersicht', 'Offene Belege', 'Frist-Check']
    return ['Offene Belege', 'Rechnung suchen']


# ---------------------------------------------------------------------------
# TASK 3: GET /inbox + POST /inbox/{id}/approve
# ---------------------------------------------------------------------------

class InboxItem(BaseModel):
    case_id: str
    case_number: str | None = None
    vendor_name: str | None = None
    amount: float | None = None
    currency: str = 'EUR'
    document_type: str | None = None
    status: str | None = None
    approval_mode: str | None = None
    confidence: float | None = None
    confidence_label: str | None = None
    created_at: str | None = None
    due_date: str | None = None
    risk_flags: list[str] = Field(default_factory=list)
    booking_proposal: dict | None = None

class InboxResponse(BaseModel):
    count: int
    items: list[InboxItem]

class ApprovalRequest(BaseModel):
    action: str = Field(pattern=r'^(approve|correct|reject|defer)$')
    corrections: dict | None = None

@router.get('/inbox')
async def get_inbox(
    user: AuthUser = Depends(require_authenticated),
    status: str = 'pending',
    limit: int = 50,
    offset: int = 0,
) -> InboxResponse:
    from app.dependencies import get_case_repository
    tenant_id = await _resolve_tenant_uuid(user)
    repo = get_case_repository()

    all_cases = await repo.list_active_cases_for_tenant(tenant_id)
    try:
        drafts = await repo.list_cases_by_status(tenant_id, 'DRAFT')
        seen = {c.id for c in all_cases}
        for d in drafts:
            if d.id not in seen:
                all_cases.append(d)
    except Exception as exc:
        logger.warning('Failed to fetch DRAFT cases for inbox: %s', exc)

    if status == 'pending':
        all_cases = [c for c in all_cases if c.status in ('DRAFT', 'OPEN')]

    all_cases.sort(key=lambda c: c.created_at or datetime.min, reverse=True)
    page = all_cases[offset:offset + limit]

    tr = _get_translations()
    items = []
    for c in page:
        meta = c.metadata or {}
        bp = meta.get('booking_proposal')
        doc_analysis = meta.get('document_analysis', {})
        # overall_confidence lives inside document_analysis sub-dict
        conf = doc_analysis.get('overall_confidence') or meta.get('overall_confidence')
        items.append(InboxItem(
            case_id=str(c.id), case_number=c.case_number, vendor_name=c.vendor_name,
            amount=float(c.total_amount) if c.total_amount else None,
            currency=c.currency or 'EUR',
            document_type=tr.get('document_type', {}).get(
                meta.get('document_analysis', {}).get('document_type', ''), 'Sonstiges'),
            status=c.status, confidence=conf,
            confidence_label=_confidence_label(conf, tr),
            created_at=c.created_at.isoformat() if c.created_at else None,
            due_date=str(c.due_date) if c.due_date else None,
            booking_proposal=bp,
        ))
    return InboxResponse(count=len(all_cases), items=items)

def _confidence_label(conf: float | None, tr: dict) -> str | None:
    if conf is None:
        return None
    labels = tr.get('confidence', {})
    if conf >= 0.85: return labels.get('CERTAIN', 'Sicher')
    if conf >= 0.65: return labels.get('HIGH', 'Hoch')
    if conf >= 0.40: return labels.get('MEDIUM', 'Mittel')
    return labels.get('LOW', 'Niedrig')

@router.post('/inbox/{case_id}/approve')
async def approve_inbox_item(
    case_id: str,
    body: ApprovalRequest,
    user: AuthUser = Depends(require_authenticated),
) -> dict:
    from app.accounting.booking_service import BookingService
    from app.booking.approval_service import BookingApprovalService
    from app.dependencies import (
        get_accounting_repository, get_approval_service,
        get_audit_service, get_open_items_service,
    )

    approval_svc = get_approval_service()
    pending = [r for r in await approval_svc.list_by_case(case_id)
               if r.status == 'PENDING' and r.action_type == 'booking_finalize']
    if not pending:
        raise HTTPException(status_code=404, detail='no_pending_approval')

    booking_svc = BookingApprovalService(
        approval_service=approval_svc, open_items_service=get_open_items_service(),
        audit_service=get_audit_service(), booking_service=BookingService(get_accounting_repository()),
    )
    result = await booking_svc.process_response(
        case_id=case_id, approval_id=pending[0].approval_id,
        decision_raw=body.action.upper(), decided_by=user.username,
        correction_payload=body.corrections, source='customer_api',
    )
    return {'status': 'processed', 'result': result}


# ---------------------------------------------------------------------------
# TASK 4: POST /inbox/{id}/learn
# ---------------------------------------------------------------------------

class LearnRequest(BaseModel):
    scope: str = Field(pattern=r'^(this_only|vendor_always|category_always|ask_every_time)$')
    rule: str | None = None

@router.post('/inbox/{case_id}/learn')
async def learn_from_correction(
    case_id: str,
    body: LearnRequest,
    user: AuthUser = Depends(require_authenticated),
) -> dict:
    from app.dependencies import get_audit_service, get_case_repository
    audit = get_audit_service()
    await audit.log_event({
        'event_id': str(uuid.uuid4()), 'case_id': case_id,
        'source': 'customer_api', 'agent_name': 'memory-curator',
        'approval_status': 'NOT_REQUIRED',
        'action': 'LEARN_RULE_SUBMITTED',
        'result': f'scope={body.scope}, rule={body.rule or "-"}',
    })
    if body.scope == 'vendor_always' and body.rule:
        try:
            repo = get_case_repository()
            case = await repo.get_case(uuid.UUID(case_id))
            if case:
                await repo.update_metadata(case.id, {
                    'learn_rule': {'scope': body.scope, 'rule': body.rule, 'by': user.username}
                })
        except Exception as exc:
            logger.warning('Learn rule save failed for %s: %s', case_id, exc)
    return {'status': 'accepted', 'scope': body.scope}


# ---------------------------------------------------------------------------
# TASK 5: Documents (3 endpoints)
# ---------------------------------------------------------------------------

# ── Document Models ──────────────────────────────────────────────────────────

class DocumentItem(BaseModel):
    id: int
    title: str | None = None
    correspondent: str | None = None
    document_type: str | None = None
    tags: list[str] = Field(default_factory=list)
    created_at: str | None = None
    thumbnail_url: str | None = None


class DocumentsResponse(BaseModel):
    count: int
    items: list[DocumentItem]


@router.get('/documents')
async def search_documents(
    user: AuthUser = Depends(require_authenticated),
    query: str = '',
    document_type: str = '',
    limit: int = 25,
    offset: int = 0,
) -> DocumentsResponse:
    """Search documents in Paperless."""
    from app.dependencies import get_paperless_connector
    pc = get_paperless_connector()

    search_query = query
    if document_type:
        search_query = f'{search_query} type:{document_type}'.strip()

    docs = await pc.search_documents(search_query) if search_query else await pc.list_all_documents()
    if not isinstance(docs, list):
        docs = []

    total = len(docs)
    page = docs[offset:offset + limit]
    items = [
        DocumentItem(
            id=d.get('id', 0),
            title=d.get('title'),
            correspondent=d.get('correspondent_name') or str(d.get('correspondent') or ''),
            document_type=d.get('document_type_name') or str(d.get('document_type') or ''),
            tags=[str(t) for t in (d.get('tags') or [])],
            created_at=d.get('created') or d.get('added'),
            thumbnail_url=f'/api/v1/documents/{d.get("id", 0)}/thumbnail',
        )
        for d in page
    ]
    return DocumentsResponse(count=total, items=items)


@router.post('/documents/upload')
async def upload_document(
    file: UploadFile,
    user: AuthUser = Depends(require_authenticated),
) -> dict:
    """Upload a document and start the analysis pipeline."""
    from app.dependencies import get_paperless_connector
    content = await file.read()
    if len(content) > 20_000_000:
        raise HTTPException(status_code=400, detail='file_too_large')

    pc = get_paperless_connector()
    ref = f'web-upload-{uuid.uuid4().hex[:8]}'
    result = await pc.upload_document(
        content, filename=file.filename or 'upload.pdf',
        title=f'frya:{ref}:{file.filename or "upload"}',
    )
    # Paperless NGX returns a plain task-id string; older versions return {'task_id': '...'}
    if isinstance(result, dict):
        task_id = result.get('task_id')
    else:
        task_id = str(result) if result else None
    return {'ref': ref, 'status': 'processing', 'message': 'Dokument angenommen. Analyse läuft.',
            'task_id': task_id}


@router.get('/documents/{doc_id}/thumbnail')
async def get_document_thumbnail(
    doc_id: int,
    user: AuthUser = Depends(require_authenticated),
):
    """Proxy to Paperless document thumbnail."""
    from fastapi.responses import Response
    from app.dependencies import get_paperless_connector
    pc = get_paperless_connector()
    try:
        thumb_bytes = await pc.get_thumbnail_bytes(str(doc_id))
    except Exception:
        raise HTTPException(status_code=404, detail='thumbnail_not_found')
    return Response(content=thumb_bytes, media_type='image/png')


# ---------------------------------------------------------------------------
# P-35: GET /cases/{case_id}/document — PDF proxy from Paperless (tenant-isolated)
# ---------------------------------------------------------------------------

@router.get('/cases/{case_id}/document')
async def get_case_document(
    case_id: str,
    user: AuthUser = Depends(require_authenticated),
):
    """Return the original PDF for a case, fetched from Paperless.

    Tenant-isolated: the case must belong to the requesting user's tenant.
    The document is found by searching Paperless with vendor name + amount.
    """
    from fastapi.responses import Response as FastResponse
    from app.dependencies import get_case_repository, get_paperless_connector

    # 1. Tenant isolation: load case and verify ownership
    tenant_id = await _resolve_tenant_uuid(user)
    repo = get_case_repository()
    try:
        case = await repo.get_case(uuid.UUID(case_id))
    except Exception:
        raise HTTPException(status_code=404, detail='case_not_found')

    if not case or case.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail='case_not_found')

    pc = get_paperless_connector()

    # 2. Check case metadata for a stored Paperless document ID (fast path)
    meta = case.metadata or {}
    paperless_id: str | int | None = (
        meta.get('paperless_id')
        or meta.get('paperless_document_id')
        or meta.get('document_analysis', {}).get('paperless_id')
    )

    # 3. If no stored ID, search Paperless by vendor name + amount (slow path)
    if not paperless_id:
        vendor = (case.vendor_name or '').strip()
        amount = float(case.total_amount) if case.total_amount else None
        search_term = vendor.split()[0] if vendor else ''

        if not search_term:
            raise HTTPException(status_code=404, detail='document_not_found')

        try:
            docs = await pc.search_documents(search_term) or []
        except Exception as exc:
            logger.warning('Paperless search failed for case %s: %s', case_id, exc)
            raise HTTPException(status_code=503, detail='paperless_unavailable')

        # Match by amount in Paperless title (format: "Vendor — X.XXEUR — Mon YYYY")
        for doc in docs:
            title = doc.get('title', '')
            if amount and (
                f'{amount:.2f}' in title
                or f'{amount:.0f}' in title
                or str(int(amount)) in title
            ):
                paperless_id = doc['id']
                break
        # Fallback: first result with matching vendor name fragment
        if not paperless_id:
            vendor_lower = vendor.lower()
            for doc in docs:
                if vendor_lower[:6] in (doc.get('title') or '').lower():
                    paperless_id = doc['id']
                    break
        if not paperless_id and docs:
            paperless_id = docs[0]['id']

    if not paperless_id:
        raise HTTPException(status_code=404, detail='document_not_found_in_paperless')

    # 4. Download PDF bytes from Paperless
    try:
        pdf_bytes = await pc.download_document_bytes(str(paperless_id))
    except Exception as exc:
        logger.warning('Paperless PDF download failed for doc %s: %s', paperless_id, exc)
        raise HTTPException(status_code=503, detail='pdf_download_failed')

    # Safe filename from vendor name
    safe_vendor = ''.join(c for c in (case.vendor_name or 'dokument') if c.isalnum() or c in ' -')[:40].strip()
    filename = f'{safe_vendor}.pdf' if safe_vendor else 'dokument.pdf'

    return FastResponse(
        content=pdf_bytes,
        media_type='application/pdf',
        headers={
            'Content-Disposition': f'inline; filename="{filename}"',
            'Cache-Control': 'private, max-age=300',
        },
    )


# ---------------------------------------------------------------------------
# TASK 6: Cases (2 endpoints)
# ---------------------------------------------------------------------------

# ── Case Models ──────────────────────────────────────────────────────────────

class CaseDetail(BaseModel):
    case_id: str
    case_number: str | None = None
    vendor_name: str | None = None
    amount: float | None = None
    currency: str = 'EUR'
    status: str | None = None
    case_type: str | None = None
    created_at: str | None = None
    due_date: str | None = None
    document_analysis: dict | None = None
    booking_proposal: dict | None = None
    line_items: list[dict] = Field(default_factory=list)
    timeline: list[dict] = Field(default_factory=list)


class CasesResponse(BaseModel):
    count: int
    items: list[CaseDetail]


def _case_to_detail(case: Any) -> CaseDetail:
    meta = case.metadata or {}
    da = meta.get('document_analysis', {})
    return CaseDetail(
        case_id=str(case.id), case_number=case.case_number,
        vendor_name=case.vendor_name,
        amount=float(case.total_amount) if case.total_amount else None,
        currency=case.currency or 'EUR', status=case.status,
        case_type=getattr(case, 'case_type', None),
        created_at=case.created_at.isoformat() if case.created_at else None,
        due_date=str(case.due_date) if case.due_date else None,
        document_analysis=da or None, booking_proposal=meta.get('booking_proposal'),
        line_items=da.get('line_items', []),
    )


@router.get('/cases')
async def list_cases(
    user: AuthUser = Depends(require_authenticated),
    status: str = '',
    limit: int = 50,
    offset: int = 0,
) -> CasesResponse:
    """List all cases for the tenant."""
    from app.dependencies import get_case_repository
    tenant_id = await _resolve_tenant_uuid(user)
    repo = get_case_repository()

    if status:
        cases = await repo.list_cases_by_status(tenant_id, status.upper())
    else:
        cases = []
        for s in ['DRAFT', 'OPEN', 'OVERDUE', 'PAID', 'CLOSED']:
            try:
                cases.extend(await repo.list_cases_by_status(tenant_id, s))
            except Exception as exc:
                logger.warning('Failed to fetch cases with status %s: %s', s, exc)

    cases.sort(key=lambda c: c.created_at or datetime.min, reverse=True)
    total = len(cases)
    page = cases[offset:offset + limit]
    return CasesResponse(count=total, items=[_case_to_detail(c) for c in page])


@router.get('/cases/{case_id}')
async def get_case_detail_endpoint(
    case_id: str,
    user: AuthUser = Depends(require_authenticated),
) -> CaseDetail:
    """Get full case details including line items and timeline."""
    from app.dependencies import get_audit_service, get_case_repository
    tenant_id = await _resolve_tenant_uuid(user)
    repo = get_case_repository()

    case = await repo.get_case(uuid.UUID(case_id))
    if case is None or case.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail='case_not_found')

    detail = _case_to_detail(case)

    try:
        audit = get_audit_service()
        events = await audit.by_case(str(case.id), limit=50)
        detail.timeline = [
            {'action': getattr(ev, 'action', ''),
             'result': str(getattr(ev, 'result', ''))[:100],
             'agent': getattr(ev, 'agent_name', ''),
             'created_at': str(getattr(ev, 'created_at', ''))[:19]}
            for ev in (events or [])
        ]
    except Exception as exc:
        logger.warning('Timeline fetch failed for case %s: %s', case_id, exc)

    return detail


# ---------------------------------------------------------------------------
# TASK 7: GET /deadlines
# ---------------------------------------------------------------------------

class DeadlinesResponse(BaseModel):
    overdue: list[dict] = Field(default_factory=list)
    due_today: list[dict] = Field(default_factory=list)
    due_soon: list[dict] = Field(default_factory=list)
    skonto_expiring: list[dict] = Field(default_factory=list)
    summary: str = ''


@router.get('/deadlines')
async def get_deadlines(
    user: AuthUser = Depends(require_authenticated),
) -> DeadlinesResponse:
    """Return deadline overview."""
    from app.deadline_analyst.service import build_deadline_analyst_service
    from app.dependencies import get_case_repository, get_llm_config_repository
    tenant_id = await _resolve_tenant_uuid(user)
    _llm_repo = get_llm_config_repository()
    _llm_config = None
    if _llm_repo:
        try:
            _llm_config = await _llm_repo.get_config_or_fallback('deadline_analyst')
        except Exception as exc:
            logger.warning('Failed to load deadline_analyst LLM config: %s', exc)
    svc = build_deadline_analyst_service(get_case_repository(), _llm_repo, _llm_config)
    report = await svc.check_all_deadlines(tenant_id)

    def _item(it: Any) -> dict:
        return {
            'case_id': str(getattr(it, 'case_id', '')),
            'case_number': getattr(it, 'case_number', None),
            'vendor_name': getattr(it, 'vendor_name', None),
            'amount': float(getattr(it, 'amount', 0)) if getattr(it, 'amount', None) else None,
            'due_date': str(getattr(it, 'due_date', '')),
            'days_remaining': getattr(it, 'days_remaining', None),
            'severity': getattr(it, 'severity', None),
        }

    return DeadlinesResponse(
        overdue=[_item(c) for c in (getattr(report, 'overdue', None) or [])],
        due_today=[_item(c) for c in (getattr(report, 'due_today', None) or [])],
        due_soon=[_item(c) for c in (getattr(report, 'due_soon', None) or [])],
        skonto_expiring=[_item(c) for c in (getattr(report, 'skonto_expiring', None) or [])],
        summary=getattr(report, 'summary', '') or '',
    )


# ---------------------------------------------------------------------------
# TASK 8: GET /finance/summary
# ---------------------------------------------------------------------------

class FinanceSummaryResponse(BaseModel):
    period: str = ''
    income: float = 0.0
    expenses: float = 0.0
    open_receivables: float = 0.0
    open_payables: float = 0.0
    overdue_count: int = 0
    overdue_amount: float = 0.0


@router.get('/finance/summary')
async def get_finance_summary(
    user: AuthUser = Depends(require_authenticated),
    period: str = 'month',
) -> FinanceSummaryResponse:
    """Return financial summary."""
    from app.accounting.booking_service import BookingService
    from app.dependencies import get_accounting_repository
    now = datetime.now(timezone.utc)

    if period == 'quarter':
        q_start = ((now.month - 1) // 3) * 3 + 1
        months = list(range(q_start, now.month + 1))
        label = f'Q{(now.month - 1) // 3 + 1} {now.year}'
    elif period == 'year':
        months = list(range(1, now.month + 1))
        label = str(now.year)
    else:
        months = [now.month]
        label = now.strftime('%B %Y')

    total_income = 0.0
    total_expenses = 0.0
    try:
        tid = await _resolve_tenant_uuid(user)
        svc = BookingService(get_accounting_repository())
        from calendar import monthrange
        date_from = date(now.year, months[0], 1)
        last_day = monthrange(now.year, months[-1])[1]
        date_to = date(now.year, months[-1], last_day)
        summary = await svc.get_finance_summary(tid, date_from, date_to)
        total_income = summary.get('total_income', 0.0)
        total_expenses = summary.get('total_expense', 0.0)
    except Exception as exc:
        logger.warning('Finance summary failed: %s', exc)

    open_recv = 0.0
    open_pay = 0.0

    overdue_count = 0
    overdue_amount = 0.0
    try:
        from app.dependencies import get_case_repository
        tid = await _resolve_tenant_uuid(user)
        overdue = await get_case_repository().list_cases_by_status(tid, 'OVERDUE')
        overdue_count = len(overdue)
        overdue_amount = sum(float(c.total_amount or 0) for c in overdue)
    except Exception as exc:
        logger.warning('Failed to fetch overdue cases for finance summary: %s', exc)

    return FinanceSummaryResponse(
        period=label, income=total_income, expenses=total_expenses,
        open_receivables=open_recv, open_payables=open_pay,
        overdue_count=overdue_count, overdue_amount=overdue_amount,
    )


# ---------------------------------------------------------------------------
# AUTH ENDPOINTS (P-42)
# ---------------------------------------------------------------------------

class LoginRequest(BaseModel):
    email: str
    password: str

class LoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    expires_in: int = 3600

class RefreshRequest(BaseModel):
    refresh_token: str

class RefreshResponse(BaseModel):
    access_token: str
    expires_in: int = 3600


@router.post('/auth/login')
async def login(body: LoginRequest) -> LoginResponse:
    """Login with email + password, returns JWT tokens."""
    from app.auth.jwt_auth import create_access_token, create_refresh_token
    from app.auth.service import verify_password
    from app.dependencies import get_user_repository

    repo = get_user_repository()
    record = await repo.find_by_email(body.email)
    if record is None:
        record = await repo.find_by_username(body.email)
    if record is None or not record.is_active:
        raise HTTPException(status_code=401, detail='invalid_credentials')

    if not verify_password(body.password, record.password_hash or ''):
        raise HTTPException(status_code=401, detail='invalid_credentials')

    # P-33: Ensure every user has a valid UUID tenant (auto-provisions if needed)
    tenant_uuid = await _ensure_tenant_uuid(record.username, record.tenant_id or None)
    access = create_access_token(record.username, str(tenant_uuid), record.role)
    refresh = create_refresh_token(record.username)

    return LoginResponse(access_token=access, refresh_token=refresh)


@router.post('/auth/refresh')
async def refresh_token(body: RefreshRequest) -> RefreshResponse:
    """Exchange refresh token for new access token."""
    from app.auth.jwt_auth import create_access_token, decode_token
    from app.dependencies import get_user_repository

    try:
        payload = decode_token(body.refresh_token)
    except Exception:
        raise HTTPException(status_code=401, detail='invalid_refresh_token')

    if payload.get('type') != 'refresh':
        raise HTTPException(status_code=401, detail='invalid_token_type')

    user_id = payload.get('sub')
    if not user_id:
        raise HTTPException(status_code=401, detail='invalid_refresh_token')

    repo = get_user_repository()
    record = await repo.find_by_username(user_id)
    if record is None or not record.is_active:
        raise HTTPException(status_code=401, detail='user_not_found')

    # P-33: Same auto-provision logic as login
    tenant_uuid = await _ensure_tenant_uuid(record.username, record.tenant_id or None)
    access = create_access_token(record.username, str(tenant_uuid), record.role)
    return RefreshResponse(access_token=access)


@router.post('/auth/logout')
async def logout(user: AuthUser = Depends(require_authenticated)) -> dict:
    """Logout — invalidates session (JWT stateless, client discards token)."""
    return {'status': 'logged_out'}


# ---------------------------------------------------------------------------
# AUTH: Forgot / Reset / Change Password + Activate (P-22 Security)
# ---------------------------------------------------------------------------

class ForgotPasswordRequest(BaseModel):
    email: str

class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(min_length=8)

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8)

class ActivateRequest(BaseModel):
    token: str


@router.post('/auth/forgot-password')
async def forgot_password(body: ForgotPasswordRequest) -> dict:
    """Request a password-reset link via e-mail."""
    from app.dependencies import get_mail_service, get_password_reset_service, get_user_repository

    repo = get_user_repository()
    reset_service = get_password_reset_service()

    user = await repo.find_by_email(body.email.strip())
    if user is not None:
        token = await reset_service.issue_reset_token(user.username)
        from app.config import get_settings
        settings = get_settings()
        reset_link = f'{settings.app_base_url}/reset-password?token={token}'
        try:
            mail_service = get_mail_service()
            await mail_service.send_mail(
                to=body.email.strip(),
                subject='Ihr FRYA Passwort-Reset',
                body_html=_forgot_password_html(reset_link),
                body_text=_forgot_password_text(reset_link),
                tenant_id=user.tenant_id,
            )
        except Exception as exc:
            logger.warning('Failed to send password reset mail: %s', exc)

    # Always return same response — no info leak
    return {'message': 'Falls ein Konto existiert, wurde eine E-Mail gesendet.'}


@router.post('/auth/reset-password')
async def reset_password(body: ResetPasswordRequest) -> dict:
    """Set a new password using a reset token."""
    from app.auth.service import hash_password_pbkdf2
    from app.dependencies import get_password_reset_service, get_user_repository

    reset_service = get_password_reset_service()

    username = await reset_service.validate_token(body.token)
    if username is None:
        raise HTTPException(status_code=400, detail='Link ungültig oder abgelaufen.')

    confirmed = await reset_service.consume_token(body.token)
    if confirmed is None:
        raise HTTPException(status_code=400, detail='Link ungültig oder abgelaufen.')

    repo = get_user_repository()
    new_hash = hash_password_pbkdf2(body.new_password)
    await repo.update_password(confirmed, new_hash)

    return {'message': 'Passwort wurde geändert.'}


@router.post('/auth/change-password')
async def change_password(
    body: ChangePasswordRequest,
    user: AuthUser = Depends(require_authenticated),
) -> dict:
    """Change the current user's password (requires valid session)."""
    from app.auth.jwt_auth import create_access_token, create_refresh_token
    from app.auth.service import hash_password_pbkdf2, verify_password
    from app.dependencies import get_user_repository

    repo = get_user_repository()
    record = await repo.find_by_username(user.username)
    if record is None:
        raise HTTPException(status_code=404, detail='Benutzer nicht gefunden.')

    if not verify_password(body.current_password, record.password_hash or ''):
        raise HTTPException(status_code=400, detail='Aktuelles Passwort ist falsch.')

    new_hash = hash_password_pbkdf2(body.new_password)
    await repo.update_password(user.username, new_hash)

    # Issue fresh JWT pair so the client stays authenticated
    tenant_id = record.tenant_id or 'default'
    new_access = create_access_token(record.username, tenant_id, record.role)
    new_refresh = create_refresh_token(record.username)

    return {
        'message': 'Passwort wurde geändert.',
        'access_token': new_access,
        'refresh_token': new_refresh,
    }


@router.post('/auth/activate')
async def activate_account(body: ActivateRequest) -> dict:
    """Activate a user account using an invitation/activation token."""
    from app.dependencies import get_password_reset_service, get_user_repository

    reset_service = get_password_reset_service()

    username = await reset_service.validate_token(body.token)
    if username is None:
        raise HTTPException(status_code=400, detail='Aktivierungslink ungültig oder abgelaufen.')

    confirmed = await reset_service.consume_token(body.token)
    if confirmed is None:
        raise HTTPException(status_code=400, detail='Aktivierungslink ungültig oder abgelaufen.')

    repo = get_user_repository()
    await repo.activate_user(confirmed)

    return {'message': 'Konto wurde aktiviert.'}


# ---------------------------------------------------------------------------
# User Settings
# ---------------------------------------------------------------------------


@router.get('/settings')
async def get_user_settings(user: AuthUser = Depends(require_authenticated)) -> dict:
    """User-Einstellungen lesen (frya_user_preferences)."""
    from app.dependencies import get_settings
    import asyncpg
    settings = get_settings()
    if settings.database_url.startswith('memory://'):
        return {'display_name': '', 'theme': 'system'}
    try:
        conn = await asyncpg.connect(settings.database_url)
        try:
            rows = await conn.fetch(
                "SELECT key, value FROM frya_user_preferences WHERE user_id = $1",
                user.username,
            )
            prefs = {r['key']: r['value'] for r in rows}
            return {
                'display_name': prefs.get('display_name', ''),
                'theme': prefs.get('theme', 'system'),
                'formal_address': prefs.get('formal_address', 'false') == 'true',
                'notification_channel': prefs.get('notification_channel', 'in_app'),
            }
        finally:
            await conn.close()
    except Exception as exc:
        logger.warning('get_user_settings failed: %s', exc)
        return {'display_name': '', 'theme': 'system'}


@router.put('/settings')
async def update_user_settings(
    data: dict,
    user: AuthUser = Depends(require_authenticated),
) -> dict:
    """User-Einstellungen aktualisieren."""
    from app.dependencies import get_settings
    import asyncpg
    settings = get_settings()
    allowed = {'display_name', 'theme', 'formal_address', 'notification_channel', 'emoji_enabled'}
    if settings.database_url.startswith('memory://'):
        return {'status': 'ok'}
    try:
        conn = await asyncpg.connect(settings.database_url)
        try:
            for key, value in data.items():
                if key in allowed:
                    # P-06: Validate display_name before saving
                    if key == 'display_name':
                        from app.api.chat_ws import is_plausible_name
                        is_name, conf = is_plausible_name(str(value))
                        if not is_name or conf < 0.6:
                            continue  # Skip invalid name
                        value = str(value).strip().title()
                    await conn.execute(
                        """INSERT INTO frya_user_preferences (tenant_id, user_id, key, value, updated_at)
                        VALUES ('default', $1, $2, $3, NOW())
                        ON CONFLICT (tenant_id, user_id, key) DO UPDATE
                          SET value = EXCLUDED.value, updated_at = NOW()""",
                        user.username, key, str(value),
                    )
        finally:
            await conn.close()
    except Exception as exc:
        logger.warning('update_user_settings failed: %s', exc)
        return {'status': 'error', 'message': str(exc)}
    return {'status': 'ok'}


# ---------------------------------------------------------------------------
# GDPR Proxy Endpoints (customer-facing, resolves tenant automatically)
# ---------------------------------------------------------------------------

@router.get('/gdpr/export')
async def gdpr_export_proxy(user: AuthUser = Depends(require_authenticated)):
    """GDPR data export proxy — resolves tenant automatically."""
    from app.api.gdpr_views import export_tenant_data
    from app.dependencies import (
        get_audit_service, get_case_repository,
        get_tenant_repository, get_user_repository,
    )

    tenant_id = await _resolve_tenant_uuid(user)
    return await export_tenant_data(
        tenant_id=str(tenant_id),
        current_user=user,
        tenant_repo=get_tenant_repository(),
        case_repo=get_case_repository(),
        audit_svc=get_audit_service(),
        user_repo=get_user_repository(),
    )


@router.post('/gdpr/delete')
async def gdpr_delete_proxy(user: AuthUser = Depends(require_authenticated)):
    """GDPR deletion request proxy — resolves tenant automatically."""
    from app.api.gdpr_views import request_tenant_deletion
    from app.dependencies import (
        get_audit_service, get_tenant_repository, get_user_repository,
    )

    tenant_id = await _resolve_tenant_uuid(user)
    return await request_tenant_deletion(
        tenant_id=str(tenant_id),
        current_user=user,
        tenant_repo=get_tenant_repository(),
        user_repo=get_user_repository(),
        audit_svc=get_audit_service(),
    )


def _forgot_password_html(link: str) -> str:
    return (
        '<html><body>'
        '<h2>Passwort zurücksetzen</h2>'
        '<p>Sie haben einen Passwort-Reset angefordert. Klicken Sie auf den folgenden Link:</p>'
        f'<p><a href="{link}">{link}</a></p>'
        '<p>Dieser Link ist 30 Minuten gültig.</p>'
        '<p>Falls Sie keinen Reset angefordert haben, ignorieren Sie diese Mail.</p>'
        '</body></html>'
    )


def _forgot_password_text(link: str) -> str:
    return (
        'Passwort zurücksetzen\n\n'
        'Sie haben einen Passwort-Reset angefordert.\n\n'
        f'{link}\n\n'
        'Dieser Link ist 30 Minuten gültig.\n'
    )


# ── WebSocket Connection Manager ─────────────────────────────────────────────


class ConnectionManager:
    """Manages active WebSocket connections per user."""

    def __init__(self) -> None:
        self._connections: dict[str, WebSocket] = {}

    async def connect(self, user_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        old = self._connections.get(user_id)
        if old:
            try:
                await old.close(code=4000, reason='new_connection')
            except Exception as exc:
                logger.debug('Failed to close old WebSocket connection: %s', exc)
        self._connections[user_id] = websocket

    def disconnect(self, user_id: str) -> None:
        self._connections.pop(user_id, None)

    async def send_to_user(self, user_id: str, data: dict) -> None:
        ws = self._connections.get(user_id)
        if ws:
            try:
                await ws.send_json(data)
            except Exception as exc:
                logger.debug('WebSocket send failed for user %s, disconnecting: %s', user_id, exc)
                self.disconnect(user_id)

    @property
    def active_count(self) -> int:
        return len(self._connections)


ws_manager = ConnectionManager()


async def _validate_ws_token(token: str) -> AuthUser | None:
    """Validate JWT token for WebSocket connection."""
    if not token:
        return None
    try:
        from app.auth.jwt_auth import decode_token
        payload = decode_token(token)
        if payload.get('type') != 'access':
            return None
        return AuthUser(
            username=payload['sub'],
            role=payload.get('role', 'customer'),
            tenant_id=payload.get('tid'),
        )
    except Exception as exc:
        logger.debug('WS token validation failed: %s', exc)
        return None


async def _handle_ws_message(websocket: WebSocket, user: AuthUser, data: dict) -> None:
    """Handle an incoming WebSocket message — stream LLM response."""
    text = data.get('text', '').strip()
    if not text:
        await websocket.send_json({'type': 'error', 'message': 'Leere Nachricht'})
        return

    # Typing indicator
    await websocket.send_json({'type': 'typing', 'active': True})

    try:
        from app.dependencies import (
            get_audit_service, get_case_repository, get_chat_history_store,
            get_communicator_conversation_store, get_communicator_user_store,
            get_open_items_service, get_telegram_clarification_service,
            get_llm_config_repository,
        )
        from app.telegram.communicator.intent_classifier import classify_intent
        from app.telegram.communicator.memory.conversation_store import (
            ConversationMemoryStore, build_updated_conversation_memory,
        )
        from app.telegram.communicator.context_resolver import resolve_context, search_case_by_vendor
        from app.telegram.communicator.models import CommunicatorContextResolution
        from app.telegram.communicator.prompts import COMMUNICATOR_SYSTEM_PROMPT
        from app.telegram.communicator.service import (
            build_llm_context_payload, _build_system_context, _CONTEXT_INTENTS,
            _GENERAL_CONVERSATION_PERSONALITY,
        )
        import litellm

        chat_id = f'web-{user.username}'
        case_id = f'ws-{user.username}-{uuid.uuid4().hex[:8]}'

        # Load conversation memory
        conv_store = get_communicator_conversation_store()
        conv_memory = await conv_store.load(chat_id) if conv_store else None

        # Load chat history
        chat_history_store = get_chat_history_store()
        chat_history = await chat_history_store.load(chat_id) if chat_history_store else []

        # Classify intent
        intent = classify_intent(text)
        if intent is None:
            await websocket.send_json({'type': 'message_complete', 'text': 'FRYA: Ich bin nicht sicher was du meinst.', 'suggestions': []})
            await websocket.send_json({'type': 'typing', 'active': False})
            return

        # Resolve LLM config
        _repo = get_llm_config_repository()
        llm_config = {}
        model_str = ''
        if _repo:
            try:
                llm_config = await _repo.get_config_or_fallback('communicator')
                model_str = (llm_config.get('model') or '').strip()
            except Exception as exc:
                logger.warning('Failed to load LLM config for communicator WS: %s', exc)

        if not model_str:
            # No model configured — simple template response
            await websocket.send_json({
                'type': 'message_complete',
                'text': 'FRYA: Ich bin gerade nicht konfiguriert. Bitte wende dich an den Administrator.',
                'suggestions': [],
            })
            await websocket.send_json({'type': 'typing', 'active': False})
            return

        # Build model name
        provider = (llm_config.get('provider') or '').strip()
        if provider == 'ionos':
            full_model = f'openai/{model_str}'
        elif provider and '/' not in model_str:
            full_model = f'{provider}/{model_str}'
        else:
            full_model = model_str

        api_key = _repo.decrypt_key_for_call(llm_config) if _repo else None
        base_url = llm_config.get('base_url') or None

        # Resolve tenant + system context
        _tenant_id = None
        try:
            _tenant_id = await _resolve_tenant_uuid(user)
        except Exception as exc:
            logger.warning('Failed to resolve tenant UUID for WS: %s', exc)

        case_repo = get_case_repository()

        # Context resolution for context intents
        core_ctx = None
        if intent in _CONTEXT_INTENTS:
            try:
                core_ctx, _ = await resolve_context(
                    case_id,
                    audit_service=get_audit_service(),
                    clarification_service=get_telegram_clarification_service(),
                    open_items_service=get_open_items_service(),
                )
            except Exception as exc:
                logger.warning('Context resolution failed in WS: %s', exc)

        # Vendor search fallback
        if (core_ctx is None or core_ctx.resolution_status == 'NOT_FOUND') and case_repo and _tenant_id:
            try:
                vendor_case_id = await search_case_by_vendor(text, case_repo, _tenant_id)
                if vendor_case_id:
                    core_ctx = CommunicatorContextResolution(
                        resolution_status='FOUND',
                        resolved_case_ref=vendor_case_id,
                        context_reason='Vendor-Name im Text erkannt.',
                    )
            except Exception as exc:
                logger.warning('Vendor search fallback failed in WS: %s', exc)

        _resolved_ref = core_ctx.resolved_case_ref if core_ctx and core_ctx.resolution_status == 'FOUND' else None

        # Try Memory Curator for rich context (primary path)
        sys_ctx = None
        try:
            from app.memory_curator.service import build_memory_curator_service
            from app.config import get_settings as _get_mem_settings
            from app.dependencies import get_accounting_repository
            _mem_settings = _get_mem_settings()
            _mem_curator = build_memory_curator_service(
                data_dir=_mem_settings.data_dir,
                llm_config_repository=None,
                case_repository=case_repo,
                audit_service=get_audit_service(),
                accounting_repository=get_accounting_repository(),
            )
            sys_ctx = await _mem_curator.get_context_assembly(
                _tenant_id,
                conversation_memory=conv_memory,
                effective_case_ref=_resolved_ref,
            )
        except Exception as _mem_exc:
            logger.warning('Memory Curator failed in WS, falling back: %s', _mem_exc)

        # Fallback to _build_system_context if Memory Curator fails
        if not sys_ctx:
            sys_ctx = await _build_system_context(
                tenant_id=_tenant_id, case_repository=case_repo,
                audit_service=get_audit_service(), user_memory=None,
                conv_memory=conv_memory, effective_case_ref=_resolved_ref,
            )
        if intent == 'GENERAL_CONVERSATION':
            sys_ctx = (sys_ctx or '') + _GENERAL_CONVERSATION_PERSONALITY

        # Build LLM payload
        from app.telegram.communicator.memory.models import TruthAnnotation
        truth = TruthAnnotation.unknown()
        payload = build_llm_context_payload(
            intent=intent, context_resolution=core_ctx,
            truth_annotation=truth, conversation_memory=conv_memory,
            user_message=text, system_context=sys_ctx, provider=provider,
            chat_history=chat_history,
        )

        call_kwargs = {
            'model': full_model,
            'messages': payload['messages'],
            'max_tokens': 300,
            'timeout': 120,
        }
        if api_key:
            call_kwargs['api_key'] = api_key
        if base_url:
            call_kwargs['api_base'] = base_url

        # Try streaming first
        full_text = ''
        try:
            call_kwargs['stream'] = True
            response = await litellm.acompletion(**call_kwargs)
            async for chunk in response:
                delta = (chunk.choices[0].delta.content or '') if chunk.choices else ''
                if delta:
                    full_text += delta
                    await websocket.send_json({'type': 'chunk', 'text': delta})
        except Exception as exc:
            # Fallback: non-streaming
            logger.warning('Streaming LLM call failed, falling back to non-streaming: %s', exc)
            call_kwargs.pop('stream', None)
            response = await litellm.acompletion(**call_kwargs)
            full_text = (response.choices[0].message.content or '').strip()

        if not full_text.startswith('FRYA:'):
            full_text = f'FRYA: {full_text}'

        # Get case ref from memory
        case_ref = conv_memory.last_case_ref if conv_memory else None
        suggestions = _build_suggestions(intent, case_ref or _resolved_ref)

        await websocket.send_json({
            'type': 'message_complete',
            'text': full_text,
            'case_ref': case_ref or _resolved_ref,
            'suggestions': suggestions,
        })

        # Update chat history
        if chat_history_store:
            await chat_history_store.append(chat_id, text, full_text)

        # Update conversation memory
        if conv_store:
            updated = build_updated_conversation_memory(
                chat_id=chat_id, prev_memory=conv_memory,
                intent=intent, resolved_case_ref=_resolved_ref,
                resolved_document_ref=None, resolved_clarification_ref=None,
                resolved_open_item_id=None,
                context_resolution_status=core_ctx.resolution_status if core_ctx else None,
            )
            await conv_store.save(updated)

    except Exception as exc:
        logger.warning('WebSocket message handling error: %s', exc)
        await websocket.send_json({'type': 'error', 'message': 'Fehler bei der Verarbeitung'})

    await websocket.send_json({'type': 'typing', 'active': False})


# ---------------------------------------------------------------------------
# P-45 Problem 5: POST /admin/backfill-case-metadata
# ---------------------------------------------------------------------------

@router.post('/admin/backfill-case-metadata')
async def backfill_case_metadata(
    user: AuthUser = Depends(require_authenticated),
) -> dict:
    """Backfill document_analysis metadata for cases that don't have it."""
    from app.dependencies import get_case_repository, get_paperless_connector

    # P-17: Use JWT tenant_id instead of resolve_tenant_id()
    if user and getattr(user, 'tenant_id', None):
        tid_str = str(user.tenant_id)
    else:
        from app.case_engine.tenant_resolver import resolve_tenant_id
        logger.warning('P-17: backfill_case_metadata using resolve_tenant_id() fallback — no tenant_id in JWT')
        tid_str = await resolve_tenant_id()
    if not tid_str:
        return {'error': 'no_tenant', 'updated': 0, 'skipped': 0}

    repo = get_case_repository()
    pc = get_paperless_connector()
    tid = uuid.UUID(tid_str)

    updated = 0
    skipped = 0
    errors = []

    # Get all cases across all statuses
    all_cases = []
    for status in ['DRAFT', 'OPEN', 'OVERDUE', 'PAID', 'CLOSED']:
        try:
            all_cases.extend(await repo.list_cases_by_status(tid, status))
        except Exception as exc:
            logger.warning('Backfill: failed to fetch cases with status %s: %s', status, exc)

    for case in all_cases:
        meta = case.metadata or {}
        if meta.get('document_analysis') and meta['document_analysis'].get('line_items'):
            skipped += 1
            continue

        # Find linked documents to get Paperless doc ID
        try:
            docs = await repo.get_case_documents(case.id)
            paperless_doc_id = None
            for d in docs:
                if d.document_source == 'paperless' and d.document_source_id:
                    paperless_doc_id = d.document_source_id
                    break
                # Also try numeric IDs from source_id
                src_id = d.document_source_id or ''
                if src_id.isdigit():
                    paperless_doc_id = src_id
                    break

            if not paperless_doc_id:
                skipped += 1
                continue

            # Get document content from Paperless
            paperless_doc = await pc.get_document(str(paperless_doc_id))
            if not paperless_doc:
                skipped += 1
                continue

            # Build analysis dict from existing Paperless metadata + case data
            existing_analysis = meta.get('document_analysis', {})
            analysis_update = {
                'sender': existing_analysis.get('sender') or case.vendor_name,
                'document_number': existing_analysis.get('document_number'),
                'document_date': existing_analysis.get('document_date'),
                'gross_amount': existing_analysis.get('gross_amount') or (float(case.total_amount) if case.total_amount else None),
                'document_type': existing_analysis.get('document_type') or 'INVOICE',
            }

            # Merge with existing metadata (don't overwrite existing fields)
            if meta.get('document_analysis'):
                for k, v in analysis_update.items():
                    if not meta['document_analysis'].get(k) and v:
                        meta['document_analysis'][k] = v
                await repo.update_metadata(case.id, {'document_analysis': meta['document_analysis']})
            else:
                await repo.update_metadata(case.id, {'document_analysis': analysis_update})

            updated += 1
            logger.info('Backfill: updated case %s (%s)', case.id, case.vendor_name)

        except Exception as exc:
            errors.append(f'{case.id}: {str(exc)[:100]}')
            logger.warning('Backfill failed for case %s: %s', case.id, exc)

    return {
        'updated': updated,
        'skipped': skipped,
        'total': len(all_cases),
        'errors': errors[:10],
    }


@router.websocket('/chat/stream')
async def chat_websocket(websocket: WebSocket, token: str = Query(default='')):
    """WebSocket for real-time chat with Frya."""
    user = await _validate_ws_token(token)

    # Also try session auth from cookies
    if user is None:
        try:
            session_payload = websocket.session.get('auth_user') if hasattr(websocket, 'session') else None
            if isinstance(session_payload, dict) and session_payload.get('username'):
                user = AuthUser(
                    username=session_payload['username'],
                    role=session_payload.get('role', 'operator'),
                )
        except Exception as exc:
            logger.debug('WS session auth fallback failed: %s', exc)

    if user is None:
        await websocket.close(code=4001, reason='Unauthorized')
        return

    user_id = user.username
    await ws_manager.connect(user_id, websocket)

    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get('type', '')

            if msg_type == 'ping':
                await websocket.send_json({'type': 'pong'})
            elif msg_type == 'message':
                await _handle_ws_message(websocket, user, data)
            else:
                await websocket.send_json({'type': 'error', 'message': f'Unbekannter Nachrichtentyp: {msg_type}'})
    except WebSocketDisconnect:
        ws_manager.disconnect(user_id)
    except Exception as exc:
        logger.warning('WebSocket error for user %s: %s', user_id, exc)
        ws_manager.disconnect(user_id)


# ---------------------------------------------------------------------------
# P-31: POST /settings/push-token — FCM-Token speichern
# ---------------------------------------------------------------------------

class PushTokenRequest(BaseModel):
    token: str
    platform: str = 'android'


@router.post('/settings/push-token', status_code=200)
async def save_push_token_endpoint(
    body: PushTokenRequest,
    user: AuthUser = Depends(require_authenticated),
):
    """Speichert oder aktualisiert den FCM-Push-Token fuer den angemeldeten User.

    Wird von der nativen App aufgerufen, nachdem der User Push-Benachrichtigungen
    erlaubt hat und die App einen FCM-Token von Firebase empfangen hat.
    """
    tenant_id = await _resolve_tenant_uuid(user)
    try:
        from app.services.push_service import save_push_token
        await save_push_token(str(tenant_id), body.token, body.platform)
        logger.info('[Push] Token gespeichert fuer Tenant %s (platform=%s)', tenant_id, body.platform)
    except Exception as exc:
        logger.error('[Push] Token-Speicherung fehlgeschlagen fuer Tenant %s: %s', tenant_id, exc)
        raise HTTPException(status_code=500, detail='Push-Token konnte nicht gespeichert werden.')
    return {'status': 'ok', 'platform': body.platform}
