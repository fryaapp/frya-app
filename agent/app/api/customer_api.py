"""P-41: Customer-facing REST API endpoints."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
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
