"""P-41: Customer-facing REST API endpoints."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app.auth.dependencies import require_authenticated
from app.auth.models import AuthUser

logger = logging.getLogger(__name__)

router = APIRouter(prefix='/api/v1', tags=['customer'])


async def _resolve_tenant_uuid() -> uuid.UUID:
    """Resolve the single-tenant UUID. Raises 503 if unavailable."""
    from app.case_engine.tenant_resolver import resolve_tenant_id
    tid = await resolve_tenant_id()
    if not tid:
        raise HTTPException(status_code=503, detail='tenant_unavailable')
    return uuid.UUID(tid)


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

@router.post('/chat')
async def send_chat_message(
    body: ChatRequest,
    user: AuthUser = Depends(require_authenticated),
) -> ChatResponse:
    """Send a message to Frya and get a synchronous reply."""
    from app.dependencies import (
        get_audit_service, get_case_repository, get_chat_history_store,
        get_communicator_conversation_store, get_communicator_user_store,
        get_open_items_service, get_telegram_clarification_service,
        get_telegram_communicator_service,
    )
    from app.telegram.communicator.intent_classifier import classify_intent
    from app.telegram.models import TelegramActorInfo, TelegramNormalizedIngressMessage

    chat_id = f'web-{user.username}'
    case_id = f'web-chat-{user.username}-{uuid.uuid4().hex[:8]}'

    normalized = TelegramNormalizedIngressMessage(
        update_id=0, message_id=0,
        telegram_chat_ref=f'web:{user.username}',
        actor=TelegramActorInfo(chat_id=chat_id, sender_id=user.username, sender_username=user.username),
        text=body.message, media_attachments=[],
    )

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
        return ChatResponse(reply='FRYA: Ich konnte deine Nachricht nicht verarbeiten.', suggestions=[])

    conv_store = get_communicator_conversation_store()
    conv_mem = await conv_store.load(chat_id)
    case_ref = conv_mem.last_case_ref if conv_mem else None

    intent = classify_intent(body.message)
    suggestions = _build_suggestions(intent, case_ref)
    return ChatResponse(reply=result.reply_text, case_ref=case_ref, suggestions=suggestions)

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
    tenant_id = await _resolve_tenant_uuid()
    repo = get_case_repository()

    all_cases = await repo.list_active_cases_for_tenant(tenant_id)
    try:
        drafts = await repo.list_cases_by_status(tenant_id, 'DRAFT')
        seen = {c.id for c in all_cases}
        for d in drafts:
            if d.id not in seen:
                all_cases.append(d)
    except Exception:
        pass

    if status == 'pending':
        all_cases = [c for c in all_cases if c.status in ('DRAFT', 'OPEN')]

    all_cases.sort(key=lambda c: c.created_at or datetime.min, reverse=True)
    page = all_cases[offset:offset + limit]

    tr = _get_translations()
    items = []
    for c in page:
        meta = c.metadata or {}
        bp = meta.get('booking_proposal')
        conf = meta.get('overall_confidence')
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
    from app.booking.approval_service import BookingApprovalService
    from app.dependencies import (
        get_akaunting_connector, get_approval_service,
        get_audit_service, get_open_items_service,
    )

    approval_svc = get_approval_service()
    pending = [r for r in await approval_svc.list_by_case(case_id)
               if r.status == 'PENDING' and r.action_type == 'booking_finalize']
    if not pending:
        raise HTTPException(status_code=404, detail='no_pending_approval')

    booking_svc = BookingApprovalService(
        approval_service=approval_svc, open_items_service=get_open_items_service(),
        audit_service=get_audit_service(), akaunting_connector=get_akaunting_connector(),
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
    return {'ref': ref, 'status': 'processing', 'message': 'Dokument angenommen. Analyse läuft.',
            'task_id': result.get('task_id')}


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
    tenant_id = await _resolve_tenant_uuid()
    repo = get_case_repository()

    if status:
        cases = await repo.list_cases_by_status(tenant_id, status.upper())
    else:
        cases = []
        for s in ['DRAFT', 'OPEN', 'OVERDUE', 'PAID', 'CLOSED']:
            try:
                cases.extend(await repo.list_cases_by_status(tenant_id, s))
            except Exception:
                pass

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
    tenant_id = await _resolve_tenant_uuid()
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
    from app.deadline_analyst.service import DeadlineAnalystService
    from app.dependencies import get_case_repository
    tenant_id = await _resolve_tenant_uuid()
    svc = DeadlineAnalystService(get_case_repository())
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
    from app.dependencies import get_akaunting_connector
    ak = get_akaunting_connector()
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
    for m in months:
        try:
            s = await ak.get_monthly_summary(now.year, m)
            total_income += s.get('total_income', 0.0)
            total_expenses += s.get('total_expense', 0.0)
        except Exception as exc:
            logger.warning('Finance summary failed for %d-%02d: %s', now.year, m, exc)

    open_recv = 0.0
    open_pay = 0.0
    try:
        oi = await ak.get_open_items_summary()
        open_recv = oi.get('total_receivable', 0.0)
        open_pay = oi.get('total_payable', 0.0)
    except Exception as exc:
        logger.warning('Open items fetch failed: %s', exc)

    overdue_count = 0
    overdue_amount = 0.0
    try:
        from app.dependencies import get_case_repository
        tid = await _resolve_tenant_uuid()
        overdue = await get_case_repository().list_cases_by_status(tid, 'OVERDUE')
        overdue_count = len(overdue)
        overdue_amount = sum(float(c.total_amount or 0) for c in overdue)
    except Exception:
        pass

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

    tenant_id = record.tenant_id or 'default'
    access = create_access_token(record.username, tenant_id, record.role)
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

    tenant_id = record.tenant_id or 'default'
    access = create_access_token(record.username, tenant_id, record.role)
    return RefreshResponse(access_token=access)


@router.post('/auth/logout')
async def logout(user: AuthUser = Depends(require_authenticated)) -> dict:
    """Logout — invalidates session (JWT stateless, client discards token)."""
    return {'status': 'logged_out'}
