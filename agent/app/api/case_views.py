from __future__ import annotations

import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from app.accounting_analysis.akaunting_reconciliation_service import AkauntingProbeResult, AkauntingReconciliationService
from app.accounting_analysis.models import (
    AkauntingReconciliationInput,
    AccountingClarificationCompletionInput,
    AccountingManualHandoffInput,
    AccountingManualHandoffResolutionInput,
    AccountingOperatorReviewDecisionInput,
    ExternalAccountingProcessResolutionInput,
    ExternalReturnClarificationCompletionInput,
)
from app.accounting_analysis.review_service import AccountingOperatorReviewService
from app.approvals.presentation import approval_next_step, latest_gate_summary
from app.approvals.service import ApprovalService
from app.audit.service import AuditService
from app.auth.csrf import require_csrf
from app.auth.dependencies import require_admin, require_operator
from app.auth.models import AuthUser
from app.cases.urls import inspect_case_href
from app.banking.models import (
    BankClarificationInput,
    BankingClarificationCompletionInput,
    ExternalBankingProcessCompletionInput,
    BankingHandoffReadyInput,
    BankingHandoffResolutionDecision,
    BankingHandoffResolutionInput,
    BankReconciliationDecision,
    BankReconciliationReviewInput,
    BankReconciliationReviewResult,
    BankTransactionProbeResult,
    FeedStatus,
    ReconciliationSignal,
)
from app.banking.reconciliation_context import ReconciliationContextService
from app.banking.review_service import BankReconciliationReviewService
from app.banking.service import BankTransactionService
from app.dependencies import (
    get_accounting_operator_review_service,
    get_akaunting_reconciliation_service,
    get_approval_service,
    get_audit_service,
    get_bank_reconciliation_review_service,
    get_reconciliation_context_service,
    get_bank_transaction_service,
    get_open_items_service,
    get_problem_case_service,
    get_telegram_case_link_service,
    get_telegram_clarification_service,
    get_telegram_document_analyst_followup_service,
    get_telegram_document_analyst_review_service,
    get_telegram_document_analyst_start_service,
)
from app.open_items.service import OpenItemsService
from app.problems.service import ProblemCaseService
from app.telegram.document_analyst_followup_service import TelegramDocumentAnalystFollowupService
from app.telegram.document_analyst_review_service import TelegramDocumentAnalystReviewService
from app.telegram.document_analyst_start_service import TelegramDocumentAnalystStartService
from app.telegram.models import (
    TelegramCaseLinkRecord,
    TelegramClarificationRecord,
    TelegramUserVisibleStatus,
)
from app.telegram.clarification_service import TelegramClarificationService
from app.telegram.service import TelegramCaseLinkService

router = APIRouter(prefix='/inspect/cases', tags=['inspect'], dependencies=[Depends(require_operator)])


class AccountingReviewDecisionBody(BaseModel):
    decision: Literal['CONFIRMED', 'REJECTED']
    note: str | None = None


class AccountingManualHandoffBody(BaseModel):
    note: str | None = None


class AccountingManualHandoffResolutionBody(BaseModel):
    decision: Literal['COMPLETED', 'RETURNED']
    note: str | None = None


class AccountingClarificationCompletionBody(BaseModel):
    note: str | None = None


class ExternalAccountingProcessResolutionBody(BaseModel):
    decision: Literal['COMPLETED', 'RETURNED']
    note: str | None = None


class ExternalReturnClarificationCompletionBody(BaseModel):
    note: str | None = None


class AkauntingReconciliationLookupBody(BaseModel):
    object_type: str
    object_id: str
    note: str | None = None


class TelegramClarificationRequestBody(BaseModel):
    question: str


class TelegramClarificationReviewBody(BaseModel):
    note: str | None = None


class TelegramClarificationResolutionBody(BaseModel):
    decision: Literal['COMPLETED', 'STILL_OPEN']
    note: str | None = None


class TelegramInternalFollowupReviewBody(BaseModel):
    note: str | None = None


class TelegramInternalFollowupResolutionBody(BaseModel):
    decision: Literal['COMPLETED']
    note: str | None = None


class TelegramDocumentAnalystStartBody(BaseModel):
    note: str | None = None


class TelegramDocumentAnalystReviewBody(BaseModel):
    decision: Literal['COMPLETED', 'STILL_OPEN']
    note: str | None = None


class TelegramDocumentAnalystFollowupBody(BaseModel):
    mode: Literal['REQUEST_DATA', 'INTERNAL_ONLY', 'CLOSE_CONSERVATIVELY']
    note: str | None = None
    question: str | None = None


class TelegramDocumentAnalystFollowupWithdrawBody(BaseModel):
    note: str | None = None


class TelegramDocumentAnalystFollowupInternalTakeoverBody(BaseModel):
    note: str | None = None


class TelegramDocumentAnalystFollowupInternalCompleteBody(BaseModel):
    note: str | None = None


@router.post('/{case_id:path}/telegram-clarification-request', dependencies=[Depends(require_csrf)])
async def case_telegram_clarification_request(
    case_id: str,
    body: TelegramClarificationRequestBody,
    telegram_case_link_service: TelegramCaseLinkService = Depends(get_telegram_case_link_service),
    telegram_clarification_service: TelegramClarificationService = Depends(get_telegram_clarification_service),
    current_user: AuthUser = Depends(require_operator),
) -> dict:
    link = await telegram_case_link_service.get_by_case(case_id)
    if link is None or not link.track_for_status:
        raise HTTPException(status_code=409, detail='Kein verknuepfter Telegram-Fall fuer Rueckfrage verfuegbar')
    try:
        result = await telegram_clarification_service.request_clarification(
            linked_case_id=link.linked_case_id or case_id,
            telegram_case_link=link,
            question_text=body.question,
            asked_by=current_user.username,
            source='inspect_case_view',
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return result.model_dump(mode='json')


@router.post('/{case_id:path}/telegram-clarification-under-review', dependencies=[Depends(require_csrf)])
async def case_telegram_clarification_under_review(
    case_id: str,
    body: TelegramClarificationReviewBody,
    telegram_clarification_service: TelegramClarificationService = Depends(get_telegram_clarification_service),
    current_user: AuthUser = Depends(require_operator),
) -> dict:
    try:
        result = await telegram_clarification_service.mark_under_review(
            linked_case_id=case_id,
            reviewed_by=current_user.username,
            note=body.note,
            source='inspect_case_view',
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return result.model_dump(mode='json')


@router.post('/{case_id:path}/telegram-clarification-resolution', dependencies=[Depends(require_csrf)])
async def case_telegram_clarification_resolution(
    case_id: str,
    body: TelegramClarificationResolutionBody,
    telegram_clarification_service: TelegramClarificationService = Depends(get_telegram_clarification_service),
    current_user: AuthUser = Depends(require_operator),
) -> dict:
    try:
        result = await telegram_clarification_service.resolve_clarification(
            linked_case_id=case_id,
            decision=body.decision,
            resolved_by=current_user.username,
            note=body.note,
            source='inspect_case_view',
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return result.model_dump(mode='json')


@router.post('/{case_id:path}/telegram-internal-followup-under-review', dependencies=[Depends(require_csrf)])
async def case_telegram_internal_followup_under_review(
    case_id: str,
    body: TelegramInternalFollowupReviewBody,
    telegram_clarification_service: TelegramClarificationService = Depends(get_telegram_clarification_service),
    current_user: AuthUser = Depends(require_operator),
) -> dict:
    try:
        result = await telegram_clarification_service.mark_internal_followup_under_review(
            linked_case_id=case_id,
            reviewed_by=current_user.username,
            note=body.note,
            source='inspect_case_view',
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return result.model_dump(mode='json')


@router.post('/{case_id:path}/telegram-internal-followup-resolution', dependencies=[Depends(require_csrf)])
async def case_telegram_internal_followup_resolution(
    case_id: str,
    body: TelegramInternalFollowupResolutionBody,
    telegram_clarification_service: TelegramClarificationService = Depends(get_telegram_clarification_service),
    current_user: AuthUser = Depends(require_operator),
) -> dict:
    try:
        result = await telegram_clarification_service.complete_internal_followup(
            linked_case_id=case_id,
            resolved_by=current_user.username,
            note=body.note,
            source='inspect_case_view',
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return result.model_dump(mode='json')


@router.post('/{case_id:path}/document-analyst-start', dependencies=[Depends(require_csrf)])
async def case_document_analyst_start(
    case_id: str,
    body: TelegramDocumentAnalystStartBody,
    request: Request,
    document_analyst_start_service: TelegramDocumentAnalystStartService = Depends(get_telegram_document_analyst_start_service),
    current_user: AuthUser = Depends(require_operator),
) -> dict:
    try:
        result = await document_analyst_start_service.start_runtime(
            case_id,
            actor=current_user.username,
            note=body.note,
            trigger='inspect_case_view',
            graph=request.app.state.graph,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return result.model_dump(mode='json')


@router.post('/{case_id:path}/document-analyst-review', dependencies=[Depends(require_csrf)])
async def case_document_analyst_review(
    case_id: str,
    body: TelegramDocumentAnalystReviewBody,
    document_analyst_review_service: TelegramDocumentAnalystReviewService = Depends(get_telegram_document_analyst_review_service),
    current_user: AuthUser = Depends(require_operator),
) -> dict:
    try:
        result = await document_analyst_review_service.resolve_review(
            case_id,
            decision=body.decision,
            reviewed_by=current_user.username,
            note=body.note,
            source='inspect_case_view',
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return result.model_dump(mode='json')


@router.post('/{case_id:path}/document-analyst-followup', dependencies=[Depends(require_csrf)])
async def case_document_analyst_followup(
    case_id: str,
    body: TelegramDocumentAnalystFollowupBody,
    document_analyst_followup_service: TelegramDocumentAnalystFollowupService = Depends(get_telegram_document_analyst_followup_service),
    current_user: AuthUser = Depends(require_operator),
) -> dict:
    try:
        result = await document_analyst_followup_service.execute_followup(
            case_id,
            mode=body.mode,
            actor=current_user.username,
            note=body.note,
            source='inspect_case_view',
            question_text=body.question,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return result.model_dump(mode='json')


@router.post('/{case_id:path}/document-analyst-followup-withdraw', dependencies=[Depends(require_csrf)])
async def case_document_analyst_followup_withdraw(
    case_id: str,
    body: TelegramDocumentAnalystFollowupWithdrawBody,
    document_analyst_followup_service: TelegramDocumentAnalystFollowupService = Depends(get_telegram_document_analyst_followup_service),
    current_user: AuthUser = Depends(require_operator),
) -> dict:
    """Withdraw an open Telegram data request (DATA_REQUESTED -> WITHDRAWN).

    Operator action: pull back the Telegram clarification without waiting for user reply.
    The case continues internally. User status switches to UNDER_INTERNAL_REVIEW.
    Late user replies will be rejected as CLARIFICATION_NOT_OPEN.
    """
    try:
        result = await document_analyst_followup_service.withdraw_data_request(
            case_id,
            actor=current_user.username,
            note=body.note,
            source='inspect_case_view',
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return result.model_dump(mode='json')


@router.post('/{case_id:path}/document-analyst-followup-internal-takeover', dependencies=[Depends(require_csrf)])
async def case_document_analyst_followup_internal_takeover(
    case_id: str,
    body: TelegramDocumentAnalystFollowupInternalTakeoverBody,
    document_analyst_followup_service: TelegramDocumentAnalystFollowupService = Depends(get_telegram_document_analyst_followup_service),
    current_user: AuthUser = Depends(require_operator),
) -> dict:
    """Activate internal takeover after withdraw (WITHDRAWN -> INTERNAL_ONLY).

    Operator signals that the internal team is actively handling the case.
    No Telegram message sent. User status remains UNDER_INTERNAL_REVIEW.
    """
    try:
        result = await document_analyst_followup_service.activate_internal_takeover(
            case_id,
            actor=current_user.username,
            note=body.note,
            source='inspect_case_view',
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return result.model_dump(mode='json')


@router.post('/{case_id:path}/document-analyst-followup-internal-complete', dependencies=[Depends(require_csrf)])
async def case_document_analyst_followup_internal_complete(
    case_id: str,
    body: TelegramDocumentAnalystFollowupInternalCompleteBody,
    document_analyst_followup_service: TelegramDocumentAnalystFollowupService = Depends(get_telegram_document_analyst_followup_service),
    current_user: AuthUser = Depends(require_operator),
) -> dict:
    """Conservative internal completion after INTERNAL_ONLY takeover (INTERNAL_ONLY -> COMPLETED).

    Operator signals that the internal follow-up path is done.
    Open item: -> COMPLETED.
    Clarification internal_followup_state: -> COMPLETED.
    User-visible status: UNDER_INTERNAL_REVIEW -> COMPLETED (Intern abgeschlossen).
    No Telegram messages sent.
    """
    try:
        result = await document_analyst_followup_service.complete_internal(
            case_id,
            actor=current_user.username,
            note=body.note,
            source='inspect_case_view',
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return result.model_dump(mode='json')


def _collect_refs(events, problems, open_items):
    doc_refs = {e.document_ref for e in events if e.document_ref}
    doc_refs.update({p.document_ref for p in problems if p.document_ref})
    doc_refs.update({o.document_ref for o in open_items if o.document_ref})

    acc_refs = {e.accounting_ref for e in events if e.accounting_ref}
    acc_refs.update({p.accounting_ref for p in problems if p.accounting_ref})
    acc_refs.update({o.accounting_ref for o in open_items if o.accounting_ref})

    return sorted(doc_refs), sorted(acc_refs)


def _collect_policy_refs(events):
    refs = []
    seen = set()
    for event in events:
        for ref in event.policy_refs:
            key = (ref.get('policy_name'), ref.get('policy_version'), ref.get('policy_path'))
            if key in seen:
                continue
            seen.add(key)
            refs.append(ref)
    return refs


def _normalize_payload(payload):
    if isinstance(payload, str):
        try:
            return json.loads(payload)
        except Exception:
            return payload
    return payload


def _latest_telegram_received(events):
    for event in reversed(events):
        if getattr(event, 'action', None) != 'TELEGRAM_WEBHOOK_RECEIVED':
            continue
        payload = _normalize_payload(getattr(event, 'llm_input', None))
        if isinstance(payload, dict):
            return {'action': event.action, 'created_at': str(getattr(event, 'created_at', '')), **payload}
    return None


def _latest_telegram_route(events):
    for event in reversed(events):
        if getattr(event, 'action', None) not in {
            'TELEGRAM_ROUTED',
            'TELEGRAM_AUTH_DENIED',
            'TELEGRAM_SECRET_DENIED',
        }:
            continue
        payload = _normalize_payload(getattr(event, 'llm_output', None))
        if isinstance(payload, dict):
            return {'action': event.action, 'created_at': str(getattr(event, 'created_at', '')), **payload}
    return None


def _latest_telegram_reply(events):
    for event in reversed(events):
        if getattr(event, 'action', None) != 'TELEGRAM_REPLY_ATTEMPTED':
            continue
        payload = _normalize_payload(getattr(event, 'llm_output', None))
        if isinstance(payload, dict):
            return {'action': event.action, 'created_at': str(getattr(event, 'created_at', '')), **payload}
    return None


def _latest_telegram_duplicate(events):
    for event in reversed(events):
        if getattr(event, 'action', None) != 'TELEGRAM_DUPLICATE_IGNORED':
            continue
        payload = _normalize_payload(getattr(event, 'llm_output', None))
        if isinstance(payload, dict):
            return {'action': event.action, 'created_at': str(getattr(event, 'created_at', '')), **payload}
    return None


def _telegram_ingress(
    events,
    case_link: TelegramCaseLinkRecord | None = None,
    user_visible_status: TelegramUserVisibleStatus | None = None,
):
    received = _latest_telegram_received(events)
    route = _latest_telegram_route(events)
    reply = _latest_telegram_reply(events)
    duplicate = _latest_telegram_duplicate(events)
    if not received and not route and not reply and not duplicate:
        return None

    reply_ok = reply.get('reply_ok') if isinstance(reply, dict) else None
    reply_reason = reply.get('reply_reason') if isinstance(reply, dict) else None
    if reply_ok is True:
        reply_status = 'SENT'
    elif reply_reason == 'telegram_bot_token_missing':
        reply_status = 'SKIPPED_NO_TOKEN'
    elif reply is not None:
        reply_status = 'FAILED'
    else:
        reply_status = 'NOT_ATTEMPTED'

    return {
        'telegram_update_ref': (received or {}).get('telegram_update_ref'),
        'telegram_message_ref': (received or {}).get('telegram_message_ref'),
        'telegram_chat_ref': (received or {}).get('telegram_chat_ref'),
        'telegram_thread_ref': case_link.telegram_thread_ref if case_link else None,
        'chat_type': (received or {}).get('chat_type'),
        'sender_id': (received or {}).get('sender_id'),
        'sender_username': (received or {}).get('sender_username'),
        'text_preview': (received or {}).get('text'),
        'routing_status': (route or {}).get('routing_status') or (route or {}).get('result'),
        'intent_name': (route or {}).get('intent_name'),
        'authorization_status': (route or {}).get('authorization_status'),
        'auth_reason': (route or {}).get('auth_reason'),
        'open_item_id': (route or {}).get('open_item_id'),
        'open_item_title': (route or {}).get('open_item_title'),
        'next_manual_step': (route or {}).get('next_manual_step'),
        'ack_template': (route or {}).get('ack_template'),
        'duplicate_ignored': duplicate is not None,
        'duplicate_at': (duplicate or {}).get('created_at'),
        'reply_status': reply_status,
        'reply_ok': reply_ok,
        'reply_reason': reply_reason,
        'received_at': (received or {}).get('created_at'),
        'routed_at': (route or {}).get('created_at'),
        'replied_at': (reply or {}).get('created_at'),
        'linked_case_id': case_link.linked_case_id if case_link else None,
        'track_for_status': case_link.track_for_status if case_link else False,
        'user_visible_status': user_visible_status.model_dump(mode='json') if user_visible_status else None,
    }


def _telegram_clarification_payload(record: TelegramClarificationRecord | None):
    if record is None:
        return None
    return record.model_dump(mode='json')


def _telegram_clarification_rounds_payload(records: list[TelegramClarificationRecord]) -> list[dict]:
    return [record.model_dump(mode='json') for record in records]


def _latest_telegram_media(events):
    for event in reversed(events):
        if getattr(event, 'action', None) not in {
            'TELEGRAM_MEDIA_STORED',
            'TELEGRAM_MEDIA_QUEUED',
            'TELEGRAM_MEDIA_REJECTED',
            'TELEGRAM_MEDIA_DOWNLOAD_FAILED',
            'TELEGRAM_DOCUMENT_STORED',
            'TELEGRAM_DOCUMENT_QUEUED',
            'TELEGRAM_DOCUMENT_REJECTED',
            'TELEGRAM_DOCUMENT_DOWNLOAD_FAILED',
            'DOCUMENT_INBOX_ACCEPTED',
            'DOCUMENT_INTAKE_LINKED',
        }:
            continue
        payload = _normalize_payload(getattr(event, 'llm_output', None))
        if isinstance(payload, dict):
            return {'action': event.action, 'created_at': str(getattr(event, 'created_at', '')), **payload}
    return None


def _latest_telegram_notification(events):
    for event in reversed(events):
        if getattr(event, 'action', None) not in {
            'TELEGRAM_NOTIFICATION_SENT',
            'TELEGRAM_NOTIFICATION_SKIPPED',
            'TELEGRAM_NOTIFICATION_FAILED',
        }:
            continue
        payload = _normalize_payload(getattr(event, 'llm_output', None))
        if isinstance(payload, dict):
            return {'action': event.action, 'created_at': str(getattr(event, 'created_at', '')), **payload}
    return None


def _latest_document_analyst_context(events):
    for event in reversed(events):
        if getattr(event, 'action', None) not in {
            'DOCUMENT_ANALYST_CONTEXT_READY',
            'DOCUMENT_ANALYST_CONTEXT_ATTACHED',
            'DOCUMENT_ANALYST_PENDING',
        }:
            continue
        payload = _normalize_payload(getattr(event, 'llm_output', None))
        if isinstance(payload, dict):
            return {'action': event.action, 'created_at': str(getattr(event, 'created_at', '')), **payload}
    return None


def _latest_document_analyst_start(events):
    for event in reversed(events):
        if getattr(event, 'action', None) not in {
            'DOCUMENT_ANALYST_START_READY',
            'DOCUMENT_ANALYST_START_REQUESTED',
            'DOCUMENT_ANALYST_RUNTIME_STARTED',
            'DOCUMENT_ANALYST_RUNTIME_FAILED',
        }:
            continue
        payload = _normalize_payload(getattr(event, 'llm_output', None))
        if isinstance(payload, dict):
            return {'action': event.action, 'created_at': str(getattr(event, 'created_at', '')), **payload}
    return None


def _latest_document_analysis(events):
    for event in reversed(events):
        if getattr(event, 'action', None) != 'DOCUMENT_ANALYSIS_COMPLETED':
            continue
        payload = _normalize_payload(getattr(event, 'llm_output', None))
        if isinstance(payload, dict):
            return {'action': event.action, 'created_at': str(getattr(event, 'created_at', '')), **payload}
    return None


def _latest_document_analyst_review(events):
    for event in reversed(events):
        if getattr(event, 'action', None) not in {
            'DOCUMENT_ANALYST_REVIEW_READY',
            'DOCUMENT_ANALYST_REVIEW_COMPLETED',
            'DOCUMENT_ANALYST_REVIEW_STILL_OPEN',
        }:
            continue
        payload = _normalize_payload(getattr(event, 'llm_output', None))
        if isinstance(payload, dict):
            return {'action': event.action, 'created_at': str(getattr(event, 'created_at', '')), **payload}
    return None


def _latest_document_analyst_followup(events):
    for event in reversed(events):
        if getattr(event, 'action', None) not in {
            'DOCUMENT_ANALYST_FOLLOWUP_REQUIRED',
            'DOCUMENT_ANALYST_FOLLOWUP_DATA_REQUESTED',
            'DOCUMENT_ANALYST_FOLLOWUP_WITHDRAWN',
            'DOCUMENT_ANALYST_FOLLOWUP_INTERNAL_ONLY',
            'DOCUMENT_ANALYST_FOLLOWUP_COMPLETED',
        }:
            continue
        payload = _normalize_payload(getattr(event, 'llm_output', None))
        if isinstance(payload, dict):
            return {'action': event.action, 'created_at': str(getattr(event, 'created_at', '')), **payload}
    return None


def _latest_communicator_turn(events):
    """Latest COMMUNICATOR_TURN_PROCESSED event — exposes truth_basis, memory_used, intent."""
    for event in reversed(events):
        if getattr(event, 'action', None) == 'COMMUNICATOR_TURN_PROCESSED':
            payload = _normalize_payload(getattr(event, 'llm_output', None))
            if isinstance(payload, dict):
                return payload
    return None


def _latest_accounting_review(events):
    for event in reversed(events):
        if event.action == 'ACCOUNTING_REVIEW_DRAFT_READY' and getattr(event, 'llm_output', None):
            return _normalize_payload(event.llm_output)
    return None


def _latest_bank_reconciliation_review(events):
    """V1.3: latest BANK_RECONCILIATION_CONFIRMED or _REJECTED audit event."""
    for event in reversed(events):
        action = getattr(event, 'action', '') or ''
        if action in {'BANK_RECONCILIATION_CONFIRMED', 'BANK_RECONCILIATION_REJECTED'}:
            payload = _normalize_payload(getattr(event, 'llm_output', None))
            if isinstance(payload, dict):
                return {'action': action, 'created_at': str(getattr(event, 'created_at', '')), **payload}
    return None


def _latest_bank_handoff_ready(events):
    """Latest BANKING_HANDOFF_READY audit event."""
    for event in reversed(events):
        action = getattr(event, 'action', '') or ''
        if action == 'BANKING_HANDOFF_READY':
            payload = _normalize_payload(getattr(event, 'llm_output', None))
            if isinstance(payload, dict):
                return {'action': action, 'created_at': str(getattr(event, 'created_at', '')), **payload}
    return None


def _latest_bank_handoff_resolution(events):
    """Latest BANKING_HANDOFF_COMPLETED or BANKING_HANDOFF_RETURNED audit event."""
    for event in reversed(events):
        action = getattr(event, 'action', '') or ''
        if action in {'BANKING_HANDOFF_COMPLETED', 'BANKING_HANDOFF_RETURNED'}:
            payload = _normalize_payload(getattr(event, 'llm_output', None))
            if isinstance(payload, dict):
                return {'action': action, 'created_at': str(getattr(event, 'created_at', '')), **payload}
    return None


def _latest_bank_clarification(events):
    latest_completion = None
    latest_return = None
    for event in reversed(events):
        action = getattr(event, 'action', '') or ''
        if latest_completion is None and action == 'BANKING_CLARIFICATION_COMPLETED':
            payload = _normalize_payload(getattr(event, 'llm_output', None))
            if isinstance(payload, dict):
                latest_completion = {'action': action, 'created_at': str(getattr(event, 'created_at', '')), **payload}
        if latest_return is None and action == 'BANKING_HANDOFF_RETURNED':
            payload = _normalize_payload(getattr(event, 'llm_output', None))
            if isinstance(payload, dict):
                latest_return = {'action': action, 'created_at': str(getattr(event, 'created_at', '')), **payload}
        if latest_completion is not None and latest_return is not None:
            break
    if latest_completion:
        return latest_completion
    if latest_return:
        return {
            'action': 'BANKING_CLARIFICATION_OPEN',
            'created_at': latest_return.get('created_at'),
            'status': 'BANKING_CLARIFICATION_OPEN',
            'clarification_state': latest_return.get('clarification_state') or 'OPEN',
            'clarification_ref': latest_return.get('clarification_ref') or latest_return.get('resolution_id'),
            'handoff_ref': latest_return.get('handoff_ref'),
            'review_ref': latest_return.get('review_ref'),
            'workbench_ref': latest_return.get('workbench_ref'),
            'transaction_id': latest_return.get('transaction_id'),
            'candidate_reference': latest_return.get('candidate_reference'),
            'clarification_guidance': 'Rueckgabegrund manuell klaeren und den Abschluss dokumentieren.',
            'required_manual_evidence': 'Kurznotiz, welche Rueckfrage oder Pruefung den Banking-Ruecklauf klaert.',
            'next_manual_step': 'Klaerung dokumentieren oder den Fall bewusst offen halten.',
            'clarification_open_item_id': latest_return.get('follow_up_open_item_id'),
            'clarification_open_item_title': latest_return.get('follow_up_open_item_title'),
            'bank_write_executed': False,
            'no_financial_write': True,
        }
    return None


def _latest_external_banking_process_resolution(events):
    for event in reversed(events):
        action = getattr(event, 'action', '') or ''
        if action == 'EXTERNAL_BANKING_PROCESS_COMPLETED':
            payload = _normalize_payload(getattr(event, 'llm_output', None))
            if isinstance(payload, dict):
                return {'action': action, 'created_at': str(getattr(event, 'created_at', '')), **payload}
    return None


def _outside_agent_banking_process(events):
    resolution = _latest_external_banking_process_resolution(events)
    if resolution:
        return {
            'status': resolution.get('status'),
            'suggested_next_step': resolution.get('suggested_next_step'),
            'outside_process_open_item_id': resolution.get('outside_process_open_item_id'),
            'outside_process_open_item_title': resolution.get('outside_process_open_item_title'),
            'source_status': resolution.get('source_internal_status') or resolution.get('status'),
            'resolution_recorded': True,
        }
    clarification = _latest_bank_clarification(events)
    if clarification and clarification.get('status') == 'BANKING_CLARIFICATION_COMPLETED':
        return {
            'status': 'OUTSIDE_AGENT_BANKING_PROCESS',
            'suggested_next_step': 'EXTERNAL_BANKING_PROCESS_COMPLETION',
            'outside_process_open_item_id': clarification.get('outside_process_open_item_id'),
            'outside_process_open_item_title': clarification.get('outside_process_open_item_title') or '[Banking] Externen Banking-Abschluss dokumentieren',
            'source_status': clarification.get('status'),
            'resolution_recorded': False,
        }
    handoff_resolution = _latest_bank_handoff_resolution(events)
    if handoff_resolution and handoff_resolution.get('decision') == 'COMPLETED':
        return {
            'status': 'OUTSIDE_AGENT_BANKING_PROCESS',
            'suggested_next_step': 'EXTERNAL_BANKING_PROCESS_COMPLETION',
            'outside_process_open_item_id': handoff_resolution.get('outside_process_open_item_id'),
            'outside_process_open_item_title': handoff_resolution.get('outside_process_open_item_title') or '[Banking] Externen Banking-Abschluss dokumentieren',
            'source_status': handoff_resolution.get('status'),
            'resolution_recorded': False,
        }
    return None


def _latest_akaunting_probe(events):
    for event in reversed(events):
        action = getattr(event, 'action', '') or ''
        if action == 'AKAUNTING_PROBE_EXECUTED':
            payload = _normalize_payload(getattr(event, 'llm_output', None))
            if isinstance(payload, dict):
                return {'action': action, 'created_at': str(getattr(event, 'created_at', '')), **payload}
    return None


def _latest_bank_transaction_probe(events):
    for event in reversed(events):
        action = getattr(event, 'action', '') or ''
        if action in {'BANK_TRANSACTION_PROBE_EXECUTED', 'BANK_TEST_PROBE_EXECUTED'}:
            payload = _normalize_payload(getattr(event, 'llm_output', None))
            if isinstance(payload, dict):
                return {'action': action, 'created_at': str(getattr(event, 'created_at', '')), **payload}
    return None


def _latest_accounting_analysis(events):
    for event in reversed(events):
        if event.action == 'ACCOUNTING_ANALYSIS_COMPLETED' and getattr(event, 'llm_output', None):
            return _normalize_payload(event.llm_output)
    return None


def _should_build_reconciliation_context(events, doc_refs, acc_refs):
    actions = {getattr(event, 'action', '') or '' for event in events}
    if any(action.startswith('BANK_') or action.startswith('AKAUNTING_') for action in actions):
        return True
    refs = [*doc_refs, *acc_refs]
    return any(str(ref).upper().startswith(('INV-', 'OUT-', 'EXP-', 'REC-', 'BILL-')) for ref in refs)


def _latest_accounting_operator_review(events):
    for event in reversed(events):
        if event.action in {'ACCOUNTING_OPERATOR_REVIEW_CONFIRMED', 'ACCOUNTING_OPERATOR_REVIEW_REJECTED'} and getattr(event, 'llm_output', None):
            payload = _normalize_payload(event.llm_output)
            if isinstance(payload, dict):
                return payload
    return None


def _latest_accounting_manual_handoff(events):
    for event in reversed(events):
        if event.action == 'ACCOUNTING_MANUAL_HANDOFF_READY' and getattr(event, 'llm_output', None):
            payload = _normalize_payload(event.llm_output)
            if isinstance(payload, dict):
                return payload
    return None


def _latest_accounting_manual_handoff_resolution(events):
    for event in reversed(events):
        if event.action in {'ACCOUNTING_MANUAL_HANDOFF_COMPLETED', 'ACCOUNTING_MANUAL_HANDOFF_RETURNED'} and getattr(event, 'llm_output', None):
            payload = _normalize_payload(event.llm_output)
            if isinstance(payload, dict):
                return payload
    return None


def _latest_accounting_clarification_completion(events):
    for event in reversed(events):
        if event.action == 'ACCOUNTING_CLARIFICATION_COMPLETED' and getattr(event, 'llm_output', None):
            payload = _normalize_payload(event.llm_output)
            if isinstance(payload, dict):
                return payload
    return None


def _latest_external_accounting_process_resolution(events):
    for event in reversed(events):
        if event.action in {'EXTERNAL_ACCOUNTING_COMPLETED', 'EXTERNAL_ACCOUNTING_RETURNED'} and getattr(event, 'llm_output', None):
            payload = _normalize_payload(event.llm_output)
            if isinstance(payload, dict):
                return payload
    return None


def _latest_external_return_clarification_completion(events):
    for event in reversed(events):
        if event.action == 'EXTERNAL_RETURN_CLARIFICATION_COMPLETED' and getattr(event, 'llm_output', None):
            payload = _normalize_payload(event.llm_output)
            if isinstance(payload, dict):
                return payload
    return None


def _outside_agent_accounting_process(events):
    reclarification = _latest_external_return_clarification_completion(events)
    if reclarification:
        return {
            'status': reclarification.get('status'),
            'suggested_next_step': reclarification.get('suggested_next_step'),
            'outside_process_open_item_id': reclarification.get('external_return_open_item_id'),
            'outside_process_open_item_title': reclarification.get('external_return_open_item_title'),
            'source_status': reclarification.get('status'),
            'resolution_recorded': True,
            'reclarification_recorded': True,
        }

    resolution = _latest_external_accounting_process_resolution(events)
    if resolution:
        return {
            'status': resolution.get('status'),
            'suggested_next_step': resolution.get('suggested_next_step'),
            'outside_process_open_item_id': resolution.get('outside_process_open_item_id'),
            'outside_process_open_item_title': resolution.get('outside_process_open_item_title'),
            'source_status': resolution.get('status'),
            'resolution_recorded': True,
            'reclarification_recorded': False,
        }

    clarification = _latest_accounting_clarification_completion(events)
    if clarification and clarification.get('suggested_next_step') == 'OUTSIDE_AGENT_ACCOUNTING_PROCESS':
        return {
            'status': 'OUTSIDE_AGENT_ACCOUNTING_PROCESS',
            'suggested_next_step': 'EXTERNAL_ACCOUNTING_RESOLUTION',
            'outside_process_open_item_id': clarification.get('outside_process_open_item_id'),
            'outside_process_open_item_title': clarification.get('outside_process_open_item_title'),
            'source_status': clarification.get('status'),
            'resolution_recorded': False,
            'reclarification_recorded': False,
        }

    manual_resolution = _latest_accounting_manual_handoff_resolution(events)
    if manual_resolution and manual_resolution.get('decision') == 'COMPLETED':
        return {
            'status': 'OUTSIDE_AGENT_ACCOUNTING_PROCESS',
            'suggested_next_step': 'EXTERNAL_ACCOUNTING_RESOLUTION',
            'outside_process_open_item_id': manual_resolution.get('outside_process_open_item_id'),
            'outside_process_open_item_title': manual_resolution.get('outside_process_open_item_title'),
            'source_status': manual_resolution.get('status'),
            'resolution_recorded': False,
            'reclarification_recorded': False,
        }

    return None


@router.get('', response_class=HTMLResponse)
async def case_index(audit_service: AuditService = Depends(get_audit_service)) -> str:
    case_ids = await audit_service.case_ids(limit=500)
    items = ''.join(f"<li><a href='{inspect_case_href(cid)}'>{cid}</a></li>" for cid in case_ids)
    return '<h1>Cases</h1><ul>' + items + '</ul>'


@router.post('/{case_id:path}/accounting-review-decision', dependencies=[Depends(require_csrf)])
async def case_accounting_review_decision(
    case_id: str,
    body: AccountingReviewDecisionBody,
    review_service: AccountingOperatorReviewService = Depends(get_accounting_operator_review_service),
    current_user: AuthUser = Depends(require_admin),
) -> dict:
    try:
        result = await review_service.decide(
            AccountingOperatorReviewDecisionInput(
                case_id=case_id,
                decision=body.decision,
                decided_by=current_user.username,
                decision_note=body.note,
                source='inspect_case_view',
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return result.model_dump(mode='json')


@router.post('/{case_id:path}/accounting-manual-handoff', dependencies=[Depends(require_csrf)])
async def case_accounting_manual_handoff(
    case_id: str,
    body: AccountingManualHandoffBody,
    review_service: AccountingOperatorReviewService = Depends(get_accounting_operator_review_service),
    current_user: AuthUser = Depends(require_admin),
) -> dict:
    try:
        result = await review_service.mark_manual_handoff(
            AccountingManualHandoffInput(
                case_id=case_id,
                decided_by=current_user.username,
                note=body.note,
                source='inspect_case_view',
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return result.model_dump(mode='json')


@router.post('/{case_id:path}/accounting-manual-handoff-resolution', dependencies=[Depends(require_csrf)])
async def case_accounting_manual_handoff_resolution(
    case_id: str,
    body: AccountingManualHandoffResolutionBody,
    review_service: AccountingOperatorReviewService = Depends(get_accounting_operator_review_service),
    current_user: AuthUser = Depends(require_admin),
) -> dict:
    try:
        result = await review_service.resolve_manual_handoff(
            AccountingManualHandoffResolutionInput(
                case_id=case_id,
                decision=body.decision,
                decided_by=current_user.username,
                note=body.note,
                source='inspect_case_view',
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return result.model_dump(mode='json')


@router.post('/{case_id:path}/accounting-clarification-complete', dependencies=[Depends(require_csrf)])
async def case_accounting_clarification_complete(
    case_id: str,
    body: AccountingClarificationCompletionBody,
    review_service: AccountingOperatorReviewService = Depends(get_accounting_operator_review_service),
    current_user: AuthUser = Depends(require_admin),
) -> dict:
    try:
        result = await review_service.complete_clarification(
            AccountingClarificationCompletionInput(
                case_id=case_id,
                decided_by=current_user.username,
                note=body.note,
                source='inspect_case_view',
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return result.model_dump(mode='json')


@router.post('/{case_id:path}/external-accounting-resolution', dependencies=[Depends(require_csrf)])
async def case_external_accounting_resolution(
    case_id: str,
    body: ExternalAccountingProcessResolutionBody,
    review_service: AccountingOperatorReviewService = Depends(get_accounting_operator_review_service),
    current_user: AuthUser = Depends(require_admin),
) -> dict:
    try:
        result = await review_service.resolve_external_accounting_process(
            ExternalAccountingProcessResolutionInput(
                case_id=case_id,
                decision=body.decision,
                decided_by=current_user.username,
                note=body.note,
                source='inspect_case_view',
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return result.model_dump(mode='json')


@router.post('/{case_id:path}/external-return-clarification-complete', dependencies=[Depends(require_csrf)])
async def case_external_return_clarification_complete(
    case_id: str,
    body: ExternalReturnClarificationCompletionBody,
    review_service: AccountingOperatorReviewService = Depends(get_accounting_operator_review_service),
    current_user: AuthUser = Depends(require_admin),
) -> dict:
    try:
        result = await review_service.complete_external_return_clarification(
            ExternalReturnClarificationCompletionInput(
                case_id=case_id,
                decided_by=current_user.username,
                note=body.note,
                source='inspect_case_view',
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return result.model_dump(mode='json')


@router.post('/{case_id:path}/akaunting-reconciliation-lookup', dependencies=[Depends(require_csrf)])
async def case_akaunting_reconciliation_lookup(
    case_id: str,
    body: AkauntingReconciliationLookupBody,
    reconciliation_service: AkauntingReconciliationService = Depends(get_akaunting_reconciliation_service),
    current_user: AuthUser = Depends(require_admin),
) -> dict:
    try:
        result = await reconciliation_service.lookup(
            AkauntingReconciliationInput(
                case_id=case_id,
                object_type=body.object_type,
                object_id=body.object_id,
                triggered_by=current_user.username,
                note=body.note,
                source='inspect_case_view',
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return result.model_dump(mode='json')


@router.post('/{case_id:path}/akaunting-probe')
async def case_akaunting_probe(
    case_id: str,
    accounting_data: dict | None = None,
    reconciliation_service: AkauntingReconciliationService = Depends(get_akaunting_reconciliation_service),
    audit_service: AuditService = Depends(get_audit_service),
) -> dict:
    """Read-only Akaunting probe. No write, no payment, no finalisation."""
    if accounting_data is None:
        accounting_data = {}
    result: AkauntingProbeResult = await reconciliation_service.probe_case(
        case_id=case_id,
        accounting_data=accounting_data,
    )
    assert result.akaunting_write_executed is False, 'Safety invariant violated'
    return result.model_dump(mode='json')


class BankTransactionProbeBody(BaseModel):
    reference: str | None = None
    amount: float | None = None
    contact_name: str | None = None
    date_from: str | None = None
    date_to: str | None = None


class BankTestProbeBody(BaseModel):
    """V1.2: test-mode probe body. Caller supplies transactions; system scores them.

    All results are flagged is_test_data=True and logged as BANK_TEST_PROBE_EXECUTED.
    """
    test_transactions: list[dict]
    reference: str | None = None
    amount: float | None = None
    contact_name: str | None = None
    date_from: str | None = None
    date_to: str | None = None


@router.post('/{case_id:path}/bank-transaction-probe')
async def case_bank_transaction_probe(
    case_id: str,
    body: BankTransactionProbeBody | None = None,
    bank_service: BankTransactionService = Depends(get_bank_transaction_service),
) -> dict:
    """Read-only bank transaction probe via Akaunting. No write, no payment initiation."""
    if body is None:
        body = BankTransactionProbeBody()
    result: BankTransactionProbeResult = await bank_service.probe_transactions(
        case_id=case_id,
        reference=body.reference,
        amount=body.amount,
        contact_name=body.contact_name,
        date_from=body.date_from,
        date_to=body.date_to,
    )
    assert result.bank_write_executed is False, 'Bank safety invariant violated'
    return result.model_dump(mode='json')


@router.post('/{case_id:path}/bank-test-probe')
async def case_bank_test_probe(
    case_id: str,
    body: BankTestProbeBody,
    bank_service: BankTransactionService = Depends(get_bank_transaction_service),
) -> dict:
    """V1.2 read-only test probe: score caller-supplied transactions with V1.2 pipeline.

    Result is flagged is_test_data=True. No write, no payment, no Akaunting write.
    Useful for demonstrating candidate scoring when live feed has no transactions.
    """
    result: BankTransactionProbeResult = await bank_service.probe_test_transactions(
        case_id=case_id,
        test_transactions=body.test_transactions,
        reference=body.reference,
        amount=body.amount,
        contact_name=body.contact_name,
        date_from=body.date_from,
        date_to=body.date_to,
    )
    assert result.bank_write_executed is False, 'Bank safety invariant violated'
    assert result.is_test_data is True, 'Test-probe must be flagged is_test_data'
    return result.model_dump(mode='json')


@router.get('/{case_id:path}/banking/feed-status')
async def case_banking_feed_status(
    case_id: str,
    bank_service: BankTransactionService = Depends(get_bank_transaction_service),
) -> dict:
    """V1.2 read-only: return live banking feed health (accounts, transaction count, reachability)."""
    feed: FeedStatus = await bank_service.get_feed_status()
    return feed.model_dump(mode='json')


# ---------------------------------------------------------------------------
# V1.3 — Operator Banking Reconciliation Review
# ---------------------------------------------------------------------------

class BankReconciliationReviewBody(BaseModel):
    """Request body for POST /bank-reconciliation-review.

    The caller passes a snapshot of the probe candidate plus the operator decision.
    No financial system write occurs.
    """
    transaction_id: str | int | None = None
    candidate_amount: float | None = None
    candidate_currency: str | None = None
    candidate_date: str | None = None
    candidate_reference: str | None = None
    candidate_contact: str | None = None
    candidate_description: str | None = None
    confidence_score: int = 0
    match_quality: str = 'LOW'
    reason_codes: list[str] = []
    tx_type: str | None = None
    probe_result: str = ''
    probe_note: str = ''
    workbench_ref: str
    workbench_signal: str = ''
    workbench_guidance: str = ''
    review_guidance: str = ''
    candidate_rank: int | None = None
    decision: BankReconciliationDecision
    decision_note: str = ''


@router.post('/{case_id:path}/bank-reconciliation-review', dependencies=[Depends(require_csrf)])
async def case_bank_reconciliation_review(
    case_id: str,
    body: BankReconciliationReviewBody,
    review_service: BankReconciliationReviewService = Depends(get_bank_reconciliation_review_service),
    current_user: AuthUser = Depends(require_operator),
) -> dict:
    """V1.3 operator banking review step.

    Records the operator's CONFIRM or REJECT decision on a probe candidate.
    Creates audit event + follow-up open item. No Akaunting write. No payment.
    bank_write_executed is always False.
    """
    payload = BankReconciliationReviewInput(
        case_id=case_id,
        transaction_id=body.transaction_id,
        candidate_amount=body.candidate_amount,
        candidate_currency=body.candidate_currency,
        candidate_date=body.candidate_date,
        candidate_reference=body.candidate_reference,
        candidate_contact=body.candidate_contact,
        candidate_description=body.candidate_description,
        confidence_score=body.confidence_score,
        match_quality=body.match_quality,
        reason_codes=body.reason_codes,
        tx_type=body.tx_type,
        probe_result=body.probe_result,
        probe_note=body.probe_note,
        workbench_ref=body.workbench_ref,
        workbench_signal=body.workbench_signal,
        workbench_guidance=body.workbench_guidance,
        review_guidance=body.review_guidance,
        candidate_rank=body.candidate_rank,
        decision=body.decision,
        decision_note=body.decision_note,
        decided_by=current_user.username,
    )
    result: BankReconciliationReviewResult = await review_service.submit_review(payload)
    assert result.bank_write_executed is False, 'Bank review safety invariant violated'
    assert result.no_financial_write is True, 'Bank review financial safety violated'
    return result.model_dump(mode='json')


@router.get('/{case_id:path}/banking/review-status')
async def case_banking_review_status(
    case_id: str,
    review_service: BankReconciliationReviewService = Depends(get_bank_reconciliation_review_service),
) -> dict:
    """V1.3 read-only: return latest banking reconciliation review event for this case."""
    latest = await review_service.get_latest_review(case_id)
    return latest or {'status': 'NO_REVIEW_YET', 'case_id': case_id}


# ---------------------------------------------------------------------------
# V1.4 — Banking Manual Handoff
# ---------------------------------------------------------------------------

class BankingHandoffReadyBody(BaseModel):
    review_ref: str
    workbench_ref: str
    transaction_id: str | int | None = None
    note: str = ''


class BankingHandoffResolutionBody(BaseModel):
    handoff_ref: str
    decision: BankingHandoffResolutionDecision
    note: str = ''


@router.post('/{case_id:path}/banking/handoff-ready', dependencies=[Depends(require_csrf)])
async def case_bank_handoff_ready(
    case_id: str,
    body: BankingHandoffReadyBody,
    review_service: BankReconciliationReviewService = Depends(get_bank_reconciliation_review_service),
    current_user: AuthUser = Depends(require_operator),
) -> dict:
    result = await review_service.mark_handoff_ready(
        BankingHandoffReadyInput(
            case_id=case_id,
            review_ref=body.review_ref,
            workbench_ref=body.workbench_ref,
            transaction_id=body.transaction_id,
            handoff_note=body.note,
            handed_off_by=current_user.username,
            source='inspect_case_view',
        )
    )
    assert result.bank_write_executed is False, 'Bank handoff safety invariant violated'
    assert result.no_financial_write is True, 'Bank handoff financial safety violated'
    return result.model_dump(mode='json')


@router.post('/{case_id:path}/banking/handoff-resolution', dependencies=[Depends(require_csrf)])
async def case_bank_handoff_resolution(
    case_id: str,
    body: BankingHandoffResolutionBody,
    review_service: BankReconciliationReviewService = Depends(get_bank_reconciliation_review_service),
    current_user: AuthUser = Depends(require_operator),
) -> dict:
    result = await review_service.resolve_handoff(
        BankingHandoffResolutionInput(
            case_id=case_id,
            handoff_ref=body.handoff_ref,
            decision=body.decision,
            resolution_note=body.note,
            resolved_by=current_user.username,
            source='inspect_case_view',
        )
    )
    assert result.bank_write_executed is False, 'Bank handoff safety invariant violated'
    assert result.no_financial_write is True, 'Bank handoff financial safety violated'
    return result.model_dump(mode='json')


@router.get('/{case_id:path}/banking/handoff-status')
async def case_banking_handoff_status(
    case_id: str,
    audit_service: AuditService = Depends(get_audit_service),
) -> dict:
    """Read-only: return current banking handoff state for this case."""
    chronology = await audit_service.by_case(case_id, limit=500)
    ready = _latest_bank_handoff_ready(list(chronology))
    resolution = _latest_bank_handoff_resolution(list(chronology))
    return {
        'ready': ready,
        'resolution': resolution,
        'status': (
            resolution.get('status')
            if resolution else
            ready.get('outcome_status')
            if ready else
            'NO_HANDOFF_YET'
        ),
        'case_id': case_id,
    }


# ---------------------------------------------------------------------------
# V1.4 — Banking Clarification
# ---------------------------------------------------------------------------

class BankClarificationBody(BaseModel):
    clarification_ref: str
    note: str = ''


class ExternalBankingProcessCompletionBody(BaseModel):
    note: str = ''


@router.post('/{case_id:path}/bank-clarification-complete', dependencies=[Depends(require_csrf)])
async def case_bank_clarification_complete(
    case_id: str,
    body: BankClarificationBody,
    review_service: BankReconciliationReviewService = Depends(get_bank_reconciliation_review_service),
    current_user: AuthUser = Depends(require_operator),
) -> dict:
    payload = BankingClarificationCompletionInput(
        case_id=case_id,
        clarification_ref=body.clarification_ref,
        clarification_note=body.note,
        clarified_by=current_user.username,
        source='inspect_case_view',
    )
    result = await review_service.complete_banking_clarification(payload)
    assert result.bank_write_executed is False, 'Bank clarification safety invariant violated'
    assert result.no_financial_write is True, 'Bank clarification financial safety violated'
    return result.model_dump(mode='json')


@router.post('/{case_id:path}/external-banking-process-complete', dependencies=[Depends(require_csrf)])
async def case_external_banking_process_complete(
    case_id: str,
    body: ExternalBankingProcessCompletionBody,
    review_service: BankReconciliationReviewService = Depends(get_bank_reconciliation_review_service),
    current_user: AuthUser = Depends(require_operator),
) -> dict:
    result = await review_service.complete_external_banking_process(
        ExternalBankingProcessCompletionInput(
            case_id=case_id,
            resolution_note=body.note,
            resolved_by=current_user.username,
            source='inspect_case_view',
        )
    )
    assert result.bank_write_executed is False, 'External banking completion safety invariant violated'
    assert result.no_financial_write is True, 'External banking completion financial safety violated'
    return result.model_dump(mode='json')


@router.get('/{case_id:path}/banking/reconciliation-context')
async def case_banking_reconciliation_context(
    case_id: str,
    reconciliation_context_service: ReconciliationContextService = Depends(get_reconciliation_context_service),
) -> dict:
    context = await reconciliation_context_service.build(case_id=case_id)
    assert context.bank_write_executed is False, 'Bank reconciliation context safety invariant violated'
    assert context.no_financial_write is True, 'Bank reconciliation context financial safety violated'
    return context.model_dump(mode='json')


@router.get('/{case_id:path}/json')
async def case_view_json(
    case_id: str,
    audit_service: AuditService = Depends(get_audit_service),
    open_items_service: OpenItemsService = Depends(get_open_items_service),
    problem_service: ProblemCaseService = Depends(get_problem_case_service),
    approval_service: ApprovalService = Depends(get_approval_service),
    reconciliation_context_service: ReconciliationContextService = Depends(get_reconciliation_context_service),
    telegram_case_link_service: TelegramCaseLinkService = Depends(get_telegram_case_link_service),
    telegram_clarification_service: TelegramClarificationService = Depends(get_telegram_clarification_service),
) -> dict:
    chronology = await audit_service.by_case(case_id, limit=1000)
    open_items = await open_items_service.list_by_case(case_id)
    problems = await problem_service.by_case(case_id)
    approvals = await approval_service.list_by_case(case_id)

    if not chronology and not open_items and not problems and not approvals:
        raise HTTPException(status_code=404, detail='Case nicht gefunden')

    doc_refs, acc_refs = _collect_refs(chronology, problems, open_items)
    reconciliation_context = None
    if _should_build_reconciliation_context(chronology, doc_refs, acc_refs):
        reconciliation_context = await reconciliation_context_service.build(case_id=case_id)
    telegram_case_link = await telegram_case_link_service.get_by_case(case_id)
    telegram_user_status = None
    telegram_clarification = None
    telegram_clarification_rounds: list[TelegramClarificationRecord] = []
    if telegram_case_link is not None:
        linked_case_id = telegram_case_link.linked_case_id or case_id
        telegram_clarification = await telegram_clarification_service.latest_by_case(linked_case_id)
        telegram_clarification_rounds = await telegram_clarification_service.list_by_case(linked_case_id)
        linked_open_items = open_items if linked_case_id == case_id else await open_items_service.list_by_case(linked_case_id)
        linked_problems = problems if linked_case_id == case_id else await problem_service.by_case(linked_case_id)
        linked_chronology = chronology if linked_case_id == case_id else await audit_service.by_case(linked_case_id, limit=200)
        telegram_user_status = await telegram_case_link_service.build_user_visible_status(
            telegram_case_link,
            linked_open_items,
            linked_problems,
            linked_chronology,
            telegram_clarification,
        )
    approvals_from_audit = [e for e in chronology if e.approval_status in {'APPROVED', 'REJECTED', 'PENDING', 'CANCELLED', 'EXPIRED', 'REVOKED'}]
    decisions = [e for e in chronology if e.action not in {'SYSTEM_STARTUP'}]

    return {
        'case_id': case_id,
        'document_refs': doc_refs,
        'accounting_refs': acc_refs,
        'chronology': [e.model_dump() for e in chronology],
        'approvals': [a.model_dump() for a in approvals],
        'approvals_from_audit': [e.model_dump() for e in approvals_from_audit],
        'agent_decisions': [e.model_dump() for e in decisions],
        'exceptions': [p.model_dump() for p in problems],
        'open_items': [o.model_dump() for o in open_items],
        'policy_refs_consulted': _collect_policy_refs(chronology),
        'latest_gate_summary': latest_gate_summary(chronology),
        'accounting_review': _latest_accounting_review(chronology),
        'accounting_analysis': _latest_accounting_analysis(chronology),
        'akaunting_probe': _latest_akaunting_probe(chronology),
        'bank_transaction_probe': _latest_bank_transaction_probe(chronology),
        'banking_reconciliation_context': (
            reconciliation_context.model_dump(mode='json') if reconciliation_context else None
        ),
        'accounting_operator_review': _latest_accounting_operator_review(chronology),
        'bank_reconciliation_review': _latest_bank_reconciliation_review(chronology),
        'banking_handoff_ready': _latest_bank_handoff_ready(chronology),
        'banking_handoff_resolution': _latest_bank_handoff_resolution(chronology),
        'bank_clarification': _latest_bank_clarification(chronology),
        'outside_agent_banking_process': _outside_agent_banking_process(chronology),
        'external_banking_process_resolution': _latest_external_banking_process_resolution(chronology),
        'communicator_turn': _latest_communicator_turn(chronology),
        'telegram_ingress': _telegram_ingress(chronology, telegram_case_link, telegram_user_status),
        'telegram_case_link': telegram_case_link.model_dump(mode='json') if telegram_case_link else None,
        'telegram_clarification': _telegram_clarification_payload(telegram_clarification),
        'telegram_clarification_rounds': _telegram_clarification_rounds_payload(telegram_clarification_rounds),
        'telegram_media': _latest_telegram_media(chronology),
        'document_analyst_context': _latest_document_analyst_context(chronology),
        'document_analyst_start': _latest_document_analyst_start(chronology),
        'document_analysis': _latest_document_analysis(chronology),
        'document_analyst_review': _latest_document_analyst_review(chronology),
        'document_analyst_followup': _latest_document_analyst_followup(chronology),
        'telegram_notification': _latest_telegram_notification(chronology),
        'accounting_manual_handoff': _latest_accounting_manual_handoff(chronology),
        'accounting_manual_handoff_resolution': _latest_accounting_manual_handoff_resolution(chronology),
        'accounting_clarification_completion': _latest_accounting_clarification_completion(chronology),
        'outside_agent_accounting_process': _outside_agent_accounting_process(chronology),
        'external_accounting_process_resolution': _latest_external_accounting_process_resolution(chronology),
        'external_return_clarification_completion': _latest_external_return_clarification_completion(chronology),
    }


@router.get('/{case_id:path}', response_class=HTMLResponse)
async def case_view(
    case_id: str,
    audit_service: AuditService = Depends(get_audit_service),
    open_items_service: OpenItemsService = Depends(get_open_items_service),
    problem_service: ProblemCaseService = Depends(get_problem_case_service),
    approval_service: ApprovalService = Depends(get_approval_service),
    reconciliation_context_service: ReconciliationContextService = Depends(get_reconciliation_context_service),
) -> str:
    chronology = await audit_service.by_case(case_id, limit=1000)
    open_items = await open_items_service.list_by_case(case_id)
    problems = await problem_service.by_case(case_id)
    approvals = await approval_service.list_by_case(case_id)

    if not chronology and not open_items and not problems and not approvals:
        raise HTTPException(status_code=404, detail='Case nicht gefunden')

    doc_refs, acc_refs = _collect_refs(chronology, problems, open_items)
    reconciliation_context = None
    if _should_build_reconciliation_context(chronology, doc_refs, acc_refs):
        reconciliation_context = await reconciliation_context_service.build(case_id=case_id)
    approvals_from_audit = [e for e in chronology if e.approval_status in {'APPROVED', 'REJECTED', 'PENDING', 'CANCELLED', 'EXPIRED', 'REVOKED'}]
    decisions = [e for e in chronology if e.action not in {'SYSTEM_STARTUP'}]
    policy_refs = _collect_policy_refs(chronology)
    latest_gate = latest_gate_summary(chronology)

    chronology_rows = ''.join(
        f"<tr><td>{e.created_at}</td><td>{e.source}</td><td>{e.action}</td><td>{e.result}</td></tr>" for e in chronology
    )
    approval_rows = ''.join(
        '<tr>'
        f'<td>{a.requested_at}</td><td>{a.approval_id}</td><td>{a.action_type}</td><td>{a.required_mode}</td><td>{a.status}</td>'
        f'<td>{a.reason or ""}</td><td>{approval_next_step(a.status)}</td>'
        f'<td>{a.scope_ref or ""}</td><td>{a.open_item_id or ""}</td><td>{a.expires_at or ""}</td><td>{a.requested_by}</td><td>{a.decided_by or ""}</td>'
        '</tr>'
        for a in approvals
    )
    audit_approval_rows = ''.join(
        f"<tr><td>{e.created_at}</td><td>{e.action}</td><td>{e.approval_status}</td><td>{e.result}</td></tr>" for e in approvals_from_audit
    )
    decision_rows = ''.join(
        f"<tr><td>{e.created_at}</td><td>{e.agent_name}</td><td>{e.action}</td><td>{e.result}</td></tr>" for e in decisions
    )
    exception_rows = ''.join(
        f"<tr><td>{p.created_at}</td><td>{p.severity}</td><td>{p.title}</td><td>{p.details}</td></tr>" for p in problems
    )
    open_item_rows = ''.join(
        f"<tr><td>{o.item_id}</td><td>{o.status}</td><td>{o.title}</td><td>{o.description}</td></tr>" for o in open_items
    )
    policy_rows = ''.join(
        f"<tr><td>{p.get('policy_name','')}</td><td>{p.get('policy_version','')}</td><td>{p.get('policy_path','')}</td></tr>" for p in policy_refs
    )

    latest_gate_html = ''
    if latest_gate:
        latest_gate_html = (
            '<h2>Latest Gate Decision</h2>'
            f"<p>mode={latest_gate['mode']} | action={latest_gate['action_key']} | reason={latest_gate['reason']} | next_step={latest_gate['next_step']}</p>"
        )

    operator_review = _latest_accounting_operator_review(chronology)
    operator_review_html = ''
    if operator_review:
        operator_review_html = ('<h2>Accounting Operator Review</h2>' f"<pre>{operator_review}</pre>")

    # V1.3 Banking Reconciliation Review
    bank_review = _latest_bank_reconciliation_review(chronology)
    bank_review_html = ''
    if bank_review:
        decision_val = bank_review.get('decision', '')
        decision_color = '#2d862d' if decision_val == 'CONFIRMED' else '#cc0000'
        tx_id = bank_review.get('transaction_id', '?')
        score = bank_review.get('confidence_score', 0)
        quality = bank_review.get('match_quality', '-')
        reasons = ', '.join(bank_review.get('reason_codes', []))
        note = bank_review.get('decision_note', '-')
        decided_by = bank_review.get('decided_by', '-')
        outcome = bank_review.get('outcome_status', '-')
        follow_up = bank_review.get('follow_up_open_item_id', '-')
        ts = bank_review.get('created_at', '-')
        bank_review_html = (
            '<h2>Banking Reconciliation Review (V1.3)</h2>'
            '<table border="1" cellpadding="6">'
            '<tr><th>Zeit</th><th>Entscheidung</th><th>TX-ID</th><th>Score</th><th>Qualitaet</th>'
            '<th>Gruende</th><th>Notiz</th><th>Entscheider</th><th>Outcome</th><th>Follow-Up Open Item</th></tr>'
            f'<tr>'
            f'<td>{ts}</td>'
            f'<td style="color:{decision_color};font-weight:bold">{decision_val}</td>'
            f'<td>{tx_id}</td>'
            f'<td>{score}/100</td>'
            f'<td>{quality}</td>'
            f'<td>{reasons}</td>'
            f'<td>{note}</td>'
            f'<td>{decided_by}</td>'
            f'<td>{outcome}</td>'
            f'<td>{follow_up}</td>'
            f'</tr>'
            '</table>'
            '<p style="color:#666;font-size:0.9em">'
            '[bank_write_executed=False | no_financial_write=True | read-only probe basis]'
            '</p>'
        )

    # V1.4 Banking Manual Handoff
    bank_handoff_ready = _latest_bank_handoff_ready(chronology)
    bank_handoff_ready_html = ''
    if bank_handoff_ready:
        bank_handoff_ready_html = (
            '<h2>Banking Handoff Ready (V1.0)</h2>'
            '<table border="1" cellpadding="6">'
            '<tr><th>Zeit</th><th>Review</th><th>Workbench</th><th>TX-ID</th><th>Referenz</th><th>Next Manual Step</th><th>Open Item</th></tr>'
            f'<tr>'
            f'<td>{bank_handoff_ready.get("created_at", "-")}</td>'
            f'<td>{bank_handoff_ready.get("review_ref", "-")}</td>'
            f'<td>{bank_handoff_ready.get("workbench_ref", "-")}</td>'
            f'<td>{bank_handoff_ready.get("transaction_id", "-")}</td>'
            f'<td>{bank_handoff_ready.get("candidate_reference", "-")}</td>'
            f'<td>{bank_handoff_ready.get("next_manual_step", "-")}</td>'
            f'<td>{bank_handoff_ready.get("handoff_open_item_title", "-")}</td>'
            f'</tr></table>'
            '<p style="color:#666;font-size:0.9em">'
            '[bank_write_executed=False | no_financial_write=True]'
            '</p>'
        )

    bank_handoff_resolution = _latest_bank_handoff_resolution(chronology)
    bank_handoff_resolution_html = ''
    if bank_handoff_resolution:
        h_action = bank_handoff_resolution.get('action', '')
        h_color = '#2d862d' if h_action == 'BANKING_HANDOFF_COMPLETED' else '#cc7700'
        bank_handoff_resolution_html = (
            '<h2>Banking Handoff Resolution (V1.0)</h2>'
            '<table border="1" cellpadding="6">'
            '<tr><th>Zeit</th><th>Entscheidung</th><th>Review</th><th>TX-ID</th><th>Notiz</th><th>By</th><th>Status</th><th>Follow-up</th></tr>'
            f'<tr>'
            f'<td>{bank_handoff_resolution.get("created_at", "-")}</td>'
            f'<td style="color:{h_color};font-weight:bold">{bank_handoff_resolution.get("decision", "-")}</td>'
            f'<td>{bank_handoff_resolution.get("review_ref", "-")}</td>'
            f'<td>{bank_handoff_resolution.get("transaction_id", "-")}</td>'
            f'<td>{bank_handoff_resolution.get("resolution_note", "-")}</td>'
            f'<td>{bank_handoff_resolution.get("resolved_by", "-")}</td>'
            f'<td>{bank_handoff_resolution.get("status", "-")}</td>'
            f'<td>{bank_handoff_resolution.get("follow_up_open_item_title", "-")}</td>'
            f'</tr></table>'
            '<p style="color:#666;font-size:0.9em">'
            '[bank_write_executed=False | no_financial_write=True]'
            '</p>'
        )

    # V1.4 Banking Clarification
    bank_clarif = _latest_bank_clarification(chronology)
    bank_clarif_html = ''
    if bank_clarif:
        bank_clarif_html = (
            '<h2>Banking Clarification (V1.4)</h2>'
            '<table border="1" cellpadding="6">'
            '<tr><th>Zeit</th><th>TX-ID</th><th>Notiz</th><th>By</th><th>Status</th><th>Open Item</th></tr>'
            f'<tr>'
            f'<td>{bank_clarif.get("created_at", "-")}</td>'
            f'<td>{bank_clarif.get("transaction_id", "-")}</td>'
            f'<td>{bank_clarif.get("clarification_note", "-")}</td>'
            f'<td>{bank_clarif.get("clarified_by", "-")}</td>'
            f'<td style="color:#2d862d;font-weight:bold">{bank_clarif.get("status", "-")}</td>'
            f'<td>{bank_clarif.get("clarification_open_item_title", "-")}</td>'
            f'</tr></table>'
            '<p style="color:#666;font-size:0.9em">'
            '[bank_write_executed=False | no_financial_write=True]'
            '</p>'
        )

    outside_bank = _outside_agent_banking_process(chronology)
    outside_bank_html = ''
    if outside_bank:
        outside_bank_html = ('<h2>Outside-Agent Banking Process</h2>' f"<pre>{outside_bank}</pre>")

    external_bank = _latest_external_banking_process_resolution(chronology)
    external_bank_html = ''
    if external_bank:
        external_bank_html = ('<h2>External Banking Process Resolution</h2>' f"<pre>{external_bank}</pre>")

    manual_handoff = _latest_accounting_manual_handoff(chronology)
    manual_handoff_html = ''
    if manual_handoff:
        manual_handoff_html = ('<h2>Accounting Manual Handoff</h2>' f"<pre>{manual_handoff}</pre>")

    manual_handoff_resolution = _latest_accounting_manual_handoff_resolution(chronology)
    manual_handoff_resolution_html = ''
    if manual_handoff_resolution:
        manual_handoff_resolution_html = ('<h2>Accounting Manual Handoff Resolution</h2>' f"<pre>{manual_handoff_resolution}</pre>")

    clarification_completion = _latest_accounting_clarification_completion(chronology)
    clarification_completion_html = ''
    if clarification_completion:
        clarification_completion_html = ('<h2>Accounting Clarification Completion</h2>' f"<pre>{clarification_completion}</pre>")

    outside_agent_process = _outside_agent_accounting_process(chronology)
    outside_agent_process_html = ''
    if outside_agent_process:
        outside_agent_process_html = ('<h2>Outside-Agent Accounting Process</h2>' f"<pre>{outside_agent_process}</pre>")

    external_resolution = _latest_external_accounting_process_resolution(chronology)
    external_resolution_html = ''
    if external_resolution:
        external_resolution_html = ('<h2>External Accounting Resolution</h2>' f"<pre>{external_resolution}</pre>")

    external_return_clarification = _latest_external_return_clarification_completion(chronology)
    external_return_clarification_html = ''
    if external_return_clarification:
        external_return_clarification_html = ('<h2>External Return Clarification Completion</h2>' f"<pre>{external_return_clarification}</pre>")

    reconciliation_context_html = ''
    if reconciliation_context:
        reconciliation_context_html = (
            '<h2>Banking Reconciliation Context</h2>'
            f"<pre>{reconciliation_context.model_dump(mode='json')}</pre>"
        )

    return (
        f'<h1>Case View: {case_id}</h1>'
        f"<h2>Document Refs</h2><pre>{doc_refs}</pre>"
        f"<h2>Accounting Refs</h2><pre>{acc_refs}</pre>"
        f'{latest_gate_html}'
        f'{operator_review_html}'
        f'{bank_review_html}'
        f'{bank_handoff_ready_html}'
        f'{bank_handoff_resolution_html}'
        f'{bank_clarif_html}'
        f'{outside_bank_html}'
        f'{external_bank_html}'
        f'{manual_handoff_html}'
        f'{manual_handoff_resolution_html}'
        f'{clarification_completion_html}'
        f'{outside_agent_process_html}'
        f'{external_resolution_html}'
        f'{external_return_clarification_html}'
        f'{reconciliation_context_html}'
        '<h2>Chronology</h2>'
        '<table border="1" cellpadding="6"><tr><th>Zeit</th><th>Source</th><th>Action</th><th>Result</th></tr>'
        f'{chronology_rows}</table>'
        '<h2>Approvals (Dedicated Model)</h2>'
        '<table border="1" cellpadding="6"><tr><th>Zeit</th><th>Approval ID</th><th>Action</th><th>Mode</th><th>Status</th><th>Grund</th><th>Naechster Schritt</th><th>Scope</th><th>Open Item</th><th>Expires</th><th>Requested By</th><th>Decided By</th></tr>'
        f'{approval_rows}</table>'
        '<h2>Approvals (Audit Derived)</h2>'
        '<table border="1" cellpadding="6"><tr><th>Zeit</th><th>Action</th><th>Status</th><th>Result</th></tr>'
        f'{audit_approval_rows}</table>'
        '<h2>Agent Decisions</h2>'
        '<table border="1" cellpadding="6"><tr><th>Zeit</th><th>Agent</th><th>Action</th><th>Result</th></tr>'
        f'{decision_rows}</table>'
        '<h2>Exceptions</h2>'
        '<table border="1" cellpadding="6"><tr><th>Zeit</th><th>Severity</th><th>Titel</th><th>Details</th></tr>'
        f'{exception_rows}</table>'
        '<h2>Open Items</h2>'
        '<table border="1" cellpadding="6"><tr><th>ID</th><th>Status</th><th>Titel</th><th>Beschreibung</th></tr>'
        f'{open_item_rows}</table>'
        '<h2>Consulted Policies</h2>'
        '<table border="1" cellpadding="6"><tr><th>Policy</th><th>Version</th><th>Registry Path</th></tr>'
        f'{policy_rows}</table>'
    )
