from __future__ import annotations

import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from app.accounting_analysis.akaunting_reconciliation_service import AkauntingReconciliationService
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
from app.dependencies import (
    get_accounting_operator_review_service,
    get_akaunting_reconciliation_service,
    get_approval_service,
    get_audit_service,
    get_open_items_service,
    get_problem_case_service,
)
from app.open_items.service import OpenItemsService
from app.problems.service import ProblemCaseService

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


def _latest_accounting_review(events):
    for event in reversed(events):
        if event.action == 'ACCOUNTING_REVIEW_DRAFT_READY' and getattr(event, 'llm_output', None):
            return _normalize_payload(event.llm_output)
    return None


def _latest_accounting_analysis(events):
    for event in reversed(events):
        if event.action == 'ACCOUNTING_ANALYSIS_COMPLETED' and getattr(event, 'llm_output', None):
            return _normalize_payload(event.llm_output)
    return None


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


@router.get('/{case_id:path}/json')
async def case_view_json(
    case_id: str,
    audit_service: AuditService = Depends(get_audit_service),
    open_items_service: OpenItemsService = Depends(get_open_items_service),
    problem_service: ProblemCaseService = Depends(get_problem_case_service),
    approval_service: ApprovalService = Depends(get_approval_service),
) -> dict:
    chronology = await audit_service.by_case(case_id, limit=1000)
    open_items = await open_items_service.list_by_case(case_id)
    problems = await problem_service.by_case(case_id)
    approvals = await approval_service.list_by_case(case_id)

    if not chronology and not open_items and not problems and not approvals:
        raise HTTPException(status_code=404, detail='Case nicht gefunden')

    doc_refs, acc_refs = _collect_refs(chronology, problems, open_items)
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
        'accounting_operator_review': _latest_accounting_operator_review(chronology),
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
) -> str:
    chronology = await audit_service.by_case(case_id, limit=1000)
    open_items = await open_items_service.list_by_case(case_id)
    problems = await problem_service.by_case(case_id)
    approvals = await approval_service.list_by_case(case_id)

    if not chronology and not open_items and not problems and not approvals:
        raise HTTPException(status_code=404, detail='Case nicht gefunden')

    doc_refs, acc_refs = _collect_refs(chronology, problems, open_items)
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

    return (
        f'<h1>Case View: {case_id}</h1>'
        f"<h2>Document Refs</h2><pre>{doc_refs}</pre>"
        f"<h2>Accounting Refs</h2><pre>{acc_refs}</pre>"
        f'{latest_gate_html}'
        f'{operator_review_html}'
        f'{manual_handoff_html}'
        f'{manual_handoff_resolution_html}'
        f'{clarification_completion_html}'
        f'{outside_agent_process_html}'
        f'{external_resolution_html}'
        f'{external_return_clarification_html}'
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
