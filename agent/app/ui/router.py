from __future__ import annotations

import json
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.status import HTTP_303_SEE_OTHER

from app.accounting_analysis.akaunting_reconciliation_service import AkauntingReconciliationService
from app.accounting_analysis.models import (
    AccountingClarificationCompletionInput,
    AccountingOperatorReviewDecisionInput,
    ExternalAccountingProcessResolutionInput,
    ExternalReturnClarificationCompletionInput,
)
from app.accounting_analysis.review_service import AccountingOperatorReviewService
from app.approvals.presentation import approval_next_step, latest_gate_summary
from app.approvals.service import ApprovalService
from app.audit.service import AuditService
from app.auth.csrf import get_csrf_token, require_csrf
from app.auth.dependencies import require_admin, require_operator
from app.auth.models import AuthUser
from app.cases.urls import ui_case_href
from app.config import get_settings
from app.dependencies import (
    get_accounting_operator_review_service,
    get_akaunting_reconciliation_service,
    get_approval_service,
    get_audit_service,
    get_file_store,
    get_open_items_service,
    get_policy_access_layer,
    get_problem_case_service,
    get_rule_change_audit_service,
    get_rule_loader,
)
from app.memory.file_store import FileStore
from app.open_items.models import OpenItem
from app.open_items.service import OpenItemsService
from app.problems.service import ProblemCaseService
from app.rules.audit_service import RuleChangeAuditService
from app.rules.loader import RuleLoader
from app.rules.policy_access import REQUIRED_POLICY_ROLES, PolicyAccessLayer

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).resolve().parent / 'templates'))
router = APIRouter(prefix='/ui', tags=['ui'], dependencies=[Depends(require_operator)])


def _ctx(request: Request, **kwargs: Any) -> dict[str, Any]:
    auth_user = getattr(request.state, 'auth_user', None)
    base = {
        'request': request,
        'internal_notice': 'Interne Operator-UI mit Session-Auth/ACL.',
        'auth_user': auth_user,
        'csrf_token': get_csrf_token(request),
        'case_href': ui_case_href,
    }
    base.update(kwargs)
    return base


def _priority_of(item: OpenItem) -> str:
    if item.due_at is None:
        return 'UNSET'

    due = item.due_at
    if due.tzinfo is None:
        due = due.replace(tzinfo=timezone.utc)

    now = datetime.now(timezone.utc)
    if due <= now:
        return 'HIGH'
    if due <= now + timedelta(hours=24):
        return 'HIGH'
    if due <= now + timedelta(hours=72):
        return 'MEDIUM'
    return 'LOW'


def _case_kind(case_id: str) -> str:
    if case_id.startswith('doc-'):
        return 'Dokument'
    if case_id.startswith('tg-'):
        return 'Telegram'
    if case_id.startswith('rule:'):
        return 'Rule-Aenderung'
    if case_id.startswith('system-'):
        return 'System'
    return 'Allgemein'


def _collect_refs(events: list[Any], problems: list[Any], open_items: list[Any]) -> tuple[list[str], list[str]]:
    doc_refs = {e.document_ref for e in events if getattr(e, 'document_ref', None)}
    doc_refs.update({p.document_ref for p in problems if p.document_ref})
    doc_refs.update({o.document_ref for o in open_items if o.document_ref})

    acc_refs = {e.accounting_ref for e in events if getattr(e, 'accounting_ref', None)}
    acc_refs.update({p.accounting_ref for p in problems if p.accounting_ref})
    acc_refs.update({o.accounting_ref for o in open_items if o.accounting_ref})

    return sorted(doc_refs), sorted(acc_refs)


def _collect_policy_refs(events: list[Any]) -> list[dict[str, str]]:
    refs: list[dict[str, str]] = []
    seen: set[tuple[str | None, str | None, str | None]] = set()
    for event in events:
        for ref in getattr(event, 'policy_refs', []):
            key = (ref.get('policy_name'), ref.get('policy_version'), ref.get('policy_path'))
            if key in seen:
                continue
            seen.add(key)
            refs.append(ref)
    return refs


def _normalize_payload(payload: Any) -> Any:
    if isinstance(payload, str):
        try:
            return json.loads(payload)
        except Exception:
            return payload
    return payload


def _latest_accounting_review(events: list[Any]) -> dict[str, Any] | None:
    for event in reversed(events):
        if getattr(event, 'action', None) == 'ACCOUNTING_REVIEW_DRAFT_READY' and getattr(event, 'llm_output', None):
            payload = _normalize_payload(event.llm_output)
            if isinstance(payload, dict):
                return payload
    return None


def _latest_accounting_analysis(events: list[Any]) -> dict[str, Any] | None:
    for event in reversed(events):
        if getattr(event, 'action', None) == 'ACCOUNTING_ANALYSIS_COMPLETED' and getattr(event, 'llm_output', None):
            payload = _normalize_payload(event.llm_output)
            if isinstance(payload, dict):
                return payload
    return None


def _latest_accounting_operator_review(events: list[Any]) -> dict[str, Any] | None:
    for event in reversed(events):
        if getattr(event, 'action', None) not in {'ACCOUNTING_OPERATOR_REVIEW_CONFIRMED', 'ACCOUNTING_OPERATOR_REVIEW_REJECTED'}:
            continue
        if not getattr(event, 'llm_output', None):
            continue
        payload = _normalize_payload(event.llm_output)
        if isinstance(payload, dict):
            return payload
    return None


def _latest_accounting_manual_handoff(events: list[Any]) -> dict[str, Any] | None:
    for event in reversed(events):
        if getattr(event, 'action', None) != 'ACCOUNTING_MANUAL_HANDOFF_READY':
            continue
        if not getattr(event, 'llm_output', None):
            continue
        payload = _normalize_payload(event.llm_output)
        if isinstance(payload, dict):
            return payload
    return None


def _latest_accounting_manual_handoff_resolution(events: list[Any]) -> dict[str, Any] | None:
    for event in reversed(events):
        if getattr(event, 'action', None) not in {'ACCOUNTING_MANUAL_HANDOFF_COMPLETED', 'ACCOUNTING_MANUAL_HANDOFF_RETURNED'}:
            continue
        if not getattr(event, 'llm_output', None):
            continue
        payload = _normalize_payload(event.llm_output)
        if isinstance(payload, dict):
            return payload
    return None


def _latest_accounting_clarification_completion(events: list[Any]) -> dict[str, Any] | None:
    for event in reversed(events):
        if getattr(event, 'action', None) != 'ACCOUNTING_CLARIFICATION_COMPLETED':
            continue
        if not getattr(event, 'llm_output', None):
            continue
        payload = _normalize_payload(event.llm_output)
        if isinstance(payload, dict):
            return payload
    return None



def _latest_external_accounting_process_resolution(events: list[Any]) -> dict[str, Any] | None:
    for event in reversed(events):
        if getattr(event, 'action', None) not in {'EXTERNAL_ACCOUNTING_COMPLETED', 'EXTERNAL_ACCOUNTING_RETURNED'}:
            continue
        if not getattr(event, 'llm_output', None):
            continue
        payload = _normalize_payload(event.llm_output)
        if isinstance(payload, dict):
            return payload
    return None


def _latest_external_return_clarification_completion(events: list[Any]) -> dict[str, Any] | None:
    for event in reversed(events):
        if getattr(event, 'action', None) != 'EXTERNAL_RETURN_CLARIFICATION_COMPLETED':
            continue
        if not getattr(event, 'llm_output', None):
            continue
        payload = _normalize_payload(event.llm_output)
        if isinstance(payload, dict):
            return payload
    return None


def _latest_akaunting_probe(events: list[Any]) -> dict[str, Any] | None:
    for event in reversed(events):
        if getattr(event, 'action', None) != 'AKAUNTING_PROBE_EXECUTED':
            continue
        if not getattr(event, 'llm_output', None):
            continue
        payload = _normalize_payload(event.llm_output)
        if isinstance(payload, dict):
            return payload
    return None


def _outside_agent_accounting_process(
    manual_handoff_resolution: dict[str, Any] | None,
    clarification_completion: dict[str, Any] | None,
    external_resolution: dict[str, Any] | None,
    external_return_clarification_completion: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if external_return_clarification_completion:
        return {
            'status': external_return_clarification_completion.get('status'),
            'suggested_next_step': external_return_clarification_completion.get('suggested_next_step'),
            'outside_process_open_item_id': external_return_clarification_completion.get('external_return_open_item_id'),
            'outside_process_open_item_title': external_return_clarification_completion.get('external_return_open_item_title'),
            'source_status': external_return_clarification_completion.get('status'),
            'resolution_recorded': True,
            'reclarification_recorded': True,
        }
    if external_resolution:
        return {
            'status': external_resolution.get('status'),
            'suggested_next_step': external_resolution.get('suggested_next_step'),
            'outside_process_open_item_id': external_resolution.get('outside_process_open_item_id'),
            'outside_process_open_item_title': external_resolution.get('outside_process_open_item_title'),
            'source_status': external_resolution.get('status'),
            'resolution_recorded': True,
            'reclarification_recorded': False,
        }
    if clarification_completion and clarification_completion.get('suggested_next_step') == 'OUTSIDE_AGENT_ACCOUNTING_PROCESS':
        return {
            'status': 'OUTSIDE_AGENT_ACCOUNTING_PROCESS',
            'suggested_next_step': 'EXTERNAL_ACCOUNTING_RESOLUTION',
            'outside_process_open_item_id': clarification_completion.get('outside_process_open_item_id'),
            'outside_process_open_item_title': clarification_completion.get('outside_process_open_item_title'),
            'source_status': clarification_completion.get('status'),
            'resolution_recorded': False,
            'reclarification_recorded': False,
        }
    if manual_handoff_resolution and manual_handoff_resolution.get('decision') == 'COMPLETED':
        return {
            'status': 'OUTSIDE_AGENT_ACCOUNTING_PROCESS',
            'suggested_next_step': 'EXTERNAL_ACCOUNTING_RESOLUTION',
            'outside_process_open_item_id': manual_handoff_resolution.get('outside_process_open_item_id'),
            'outside_process_open_item_title': manual_handoff_resolution.get('outside_process_open_item_title'),
            'source_status': manual_handoff_resolution.get('status'),
            'resolution_recorded': False,
            'reclarification_recorded': False,
        }
    return None
def _can_submit_accounting_review(accounting_analysis: dict[str, Any] | None, operator_review: dict[str, Any] | None) -> bool:
    if operator_review is not None:
        return False
    if not accounting_analysis:
        return False
    return accounting_analysis.get('global_decision') == 'PROPOSED'


def _can_complete_accounting_clarification(
    manual_handoff_resolution: dict[str, Any] | None,
    clarification_completion: dict[str, Any] | None,
) -> bool:
    if clarification_completion is not None:
        return False
    if not manual_handoff_resolution:
        return False
    return manual_handoff_resolution.get('decision') == 'RETURNED'



def _can_resolve_external_accounting_process(
    outside_agent_accounting_process: dict[str, Any] | None,
    external_resolution: dict[str, Any] | None,
) -> bool:
    if external_resolution is not None:
        return False
    if not outside_agent_accounting_process:
        return False
    return outside_agent_accounting_process.get('resolution_recorded') is False


def _can_complete_external_return_clarification(
    external_resolution: dict[str, Any] | None,
    external_return_clarification_completion: dict[str, Any] | None,
) -> bool:
    if external_return_clarification_completion is not None:
        return False
    if not external_resolution:
        return False
    return external_resolution.get('decision') == 'RETURNED'

@router.get('', include_in_schema=False)
async def ui_root() -> RedirectResponse:
    return RedirectResponse(url='/ui/dashboard', status_code=HTTP_303_SEE_OTHER)


@router.get('/dashboard', response_class=HTMLResponse)
async def dashboard(
    request: Request,
    audit_service: AuditService = Depends(get_audit_service),
    open_items_service: OpenItemsService = Depends(get_open_items_service),
    problem_service: ProblemCaseService = Depends(get_problem_case_service),
    rule_change_service: RuleChangeAuditService = Depends(get_rule_change_audit_service),
    policy_access: PolicyAccessLayer = Depends(get_policy_access_layer),
    approval_service: ApprovalService = Depends(get_approval_service),
) -> HTMLResponse:
    settings = get_settings()

    recent_cases = await audit_service.case_ids(limit=15)
    open_items = await open_items_service.list_items()
    problem_cases = await problem_service.recent(limit=10)
    rule_changes = await rule_change_service.recent(limit=10)
    approvals = await approval_service.recent(limit=200)
    pending_approvals = [item for item in approvals if item.status == 'PENDING']

    counter = Counter(item.status for item in open_items)
    health = {'status': 'ok', 'service': 'frya-agent', 'llm_model': settings.llm_model}
    policies_ok, policies_missing = policy_access.required_policies_loaded()
    summary = {
        'recent_cases': len(recent_cases),
        'open_items': len(open_items),
        'problem_cases': len(problem_cases),
        'policy_missing': len(policies_missing),
        'pending_approvals': len(pending_approvals),
    }

    return TEMPLATES.TemplateResponse(
        request,
        'dashboard.html',
        _ctx(
            request,
            title='Dashboard',
            health=health,
            architecture={
                'agent_is_backend': True,
                'separate_backend_service_target': False,
            },
            recent_cases=recent_cases,
            open_item_counts=dict(counter),
            problem_cases=problem_cases,
            rule_changes=rule_changes,
            pending_approvals=pending_approvals[:10],
            policies_ok=policies_ok,
            policies_missing=policies_missing,
            summary=summary,
        ),
    )


@router.get('/cases', response_class=HTMLResponse)
async def ui_cases(
    request: Request,
    audit_service: AuditService = Depends(get_audit_service),
) -> HTMLResponse:
    case_ids = await audit_service.case_ids(limit=300)

    latest_by_case: dict[str, Any] = {}
    try:
        recent_events = await audit_service.recent(limit=2000)
        for event in recent_events:
            if event.case_id and event.case_id not in latest_by_case:
                latest_by_case[event.case_id] = event
    except Exception:
        latest_by_case = {}

    case_rows: list[dict[str, Any]] = []
    for cid in case_ids:
        latest = latest_by_case.get(cid)
        case_rows.append(
            {
                'case_id': cid,
                'kind': _case_kind(cid),
                'last_action': latest.action if latest else '-',
                'last_result': latest.result if latest else '-',
                'last_activity': latest.created_at if latest else None,
            }
        )

    return TEMPLATES.TemplateResponse(
        request,
        'cases_list.html',
        _ctx(request, title='Cases', case_rows=case_rows),
    )


@router.post('/cases/{case_id:path}/accounting-review-decision', dependencies=[Depends(require_csrf)])
async def ui_case_accounting_review_decision(
    request: Request,
    case_id: str,
    decision: str = Form(...),
    note: str = Form(default=''),
    review_service: AccountingOperatorReviewService = Depends(get_accounting_operator_review_service),
    current_user: AuthUser = Depends(require_admin),
) -> RedirectResponse:
    try:
        result = await review_service.decide(
            AccountingOperatorReviewDecisionInput(
                case_id=case_id,
                decision=decision,
                decided_by=current_user.username,
                decision_note=note or None,
                source='ui_case_detail',
            )
        )
        msg = f'Accounting Review {result.decision} gespeichert.'
    except ValueError as exc:
        msg = str(exc)
    return RedirectResponse(url=f'{ui_case_href(case_id)}?msg={quote(msg)}', status_code=HTTP_303_SEE_OTHER)


@router.post('/cases/{case_id:path}/accounting-clarification-complete', dependencies=[Depends(require_csrf)])
async def ui_case_accounting_clarification_complete(
    request: Request,
    case_id: str,
    note: str = Form(default=''),
    review_service: AccountingOperatorReviewService = Depends(get_accounting_operator_review_service),
    current_user: AuthUser = Depends(require_admin),
) -> RedirectResponse:
    try:
        result = await review_service.complete_clarification(
            AccountingClarificationCompletionInput(
                case_id=case_id,
                decided_by=current_user.username,
                note=note or None,
                source='ui_case_detail',
            )
        )
        msg = f'Accounting Klaerabschluss {result.status} gespeichert.'
    except ValueError as exc:
        msg = str(exc)
    return RedirectResponse(url=f'{ui_case_href(case_id)}?msg={quote(msg)}', status_code=HTTP_303_SEE_OTHER)


@router.post('/cases/{case_id:path}/external-accounting-resolution', dependencies=[Depends(require_csrf)])
async def ui_case_external_accounting_resolution(
    request: Request,
    case_id: str,
    decision: str = Form(...),
    note: str = Form(default=''),
    review_service: AccountingOperatorReviewService = Depends(get_accounting_operator_review_service),
    current_user: AuthUser = Depends(require_admin),
) -> RedirectResponse:
    try:
        result = await review_service.resolve_external_accounting_process(
            ExternalAccountingProcessResolutionInput(
                case_id=case_id,
                decision=decision,
                decided_by=current_user.username,
                note=note or None,
                source='ui_case_detail',
            )
        )
        msg = f'Externer Accounting-Abschluss {result.status} gespeichert.'
    except ValueError as exc:
        msg = str(exc)
    return RedirectResponse(url=f'{ui_case_href(case_id)}?msg={quote(msg)}', status_code=HTTP_303_SEE_OTHER)



@router.post('/cases/{case_id:path}/external-return-clarification-complete', dependencies=[Depends(require_csrf)])
async def ui_case_external_return_clarification_complete(
    request: Request,
    case_id: str,
    note: str = Form(default=''),
    review_service: AccountingOperatorReviewService = Depends(get_accounting_operator_review_service),
    current_user: AuthUser = Depends(require_admin),
) -> RedirectResponse:
    try:
        result = await review_service.complete_external_return_clarification(
            ExternalReturnClarificationCompletionInput(
                case_id=case_id,
                decided_by=current_user.username,
                note=note or None,
                source='ui_case_detail',
            )
        )
        msg = f'Externer Ruecklauf {result.status} gespeichert.'
    except ValueError as exc:
        msg = str(exc)
    return RedirectResponse(url=f'{ui_case_href(case_id)}?msg={quote(msg)}', status_code=HTTP_303_SEE_OTHER)

@router.post('/cases/{case_id:path}/akaunting-probe', dependencies=[Depends(require_csrf)])
async def ui_case_akaunting_probe(
    request: Request,
    case_id: str,
    reconciliation_service: AkauntingReconciliationService = Depends(get_akaunting_reconciliation_service),
) -> RedirectResponse:
    try:
        await reconciliation_service.probe_case(case_id=case_id, accounting_data={})
        msg = 'Akaunting-Abgleich ausgefuehrt.'
    except Exception as exc:
        msg = f'Probe-Fehler: {exc}'
    return RedirectResponse(url=f'{ui_case_href(case_id)}?msg={quote(msg)}', status_code=HTTP_303_SEE_OTHER)


@router.get('/cases/{case_id:path}', response_class=HTMLResponse)
async def ui_case_detail(
    request: Request,
    case_id: str,
    audit_service: AuditService = Depends(get_audit_service),
    open_items_service: OpenItemsService = Depends(get_open_items_service),
    problem_service: ProblemCaseService = Depends(get_problem_case_service),
    approval_service: ApprovalService = Depends(get_approval_service),
) -> HTMLResponse:
    chronology = await audit_service.by_case(case_id, limit=1000)
    open_items = await open_items_service.list_by_case(case_id)
    problems = await problem_service.by_case(case_id)
    approvals = await approval_service.list_by_case(case_id)

    if not chronology and not open_items and not problems and not approvals:
        raise HTTPException(status_code=404, detail='Case nicht gefunden')

    document_refs, accounting_refs = _collect_refs(chronology, problems, open_items)
    approvals_from_audit = [e for e in chronology if e.approval_status in {'APPROVED', 'REJECTED', 'PENDING', 'CANCELLED', 'EXPIRED', 'REVOKED'}]
    decisions = [e for e in chronology if e.action not in {'SYSTEM_STARTUP'}]
    exceptions = [p for p in problems]
    policy_refs = _collect_policy_refs(chronology)
    latest_gate = latest_gate_summary(chronology)
    accounting_review = _latest_accounting_review(chronology)
    accounting_analysis = _latest_accounting_analysis(chronology)
    accounting_operator_review = _latest_accounting_operator_review(chronology)
    accounting_manual_handoff = _latest_accounting_manual_handoff(chronology)
    accounting_manual_handoff_resolution = _latest_accounting_manual_handoff_resolution(chronology)
    accounting_clarification_completion = _latest_accounting_clarification_completion(chronology)
    external_accounting_process_resolution = _latest_external_accounting_process_resolution(chronology)
    external_return_clarification_completion = _latest_external_return_clarification_completion(chronology)
    outside_agent_accounting_process = _outside_agent_accounting_process(
        accounting_manual_handoff_resolution,
        accounting_clarification_completion,
        external_accounting_process_resolution,
        external_return_clarification_completion,
    )
    akaunting_probe = _latest_akaunting_probe(chronology)

    return TEMPLATES.TemplateResponse(
        request,
        'case_detail.html',
        _ctx(
            request,
            title=f'Case {case_id}',
            case_id=case_id,
            chronology=chronology,
            document_refs=document_refs,
            accounting_refs=accounting_refs,
            approvals=approvals,
            approvals_from_audit=approvals_from_audit,
            decisions=decisions,
            exceptions=exceptions,
            open_items=open_items,
            policy_refs=policy_refs,
            latest_gate=latest_gate,
            accounting_review=accounting_review,
            accounting_analysis=accounting_analysis,
            accounting_operator_review=accounting_operator_review,
            accounting_manual_handoff=accounting_manual_handoff,
            accounting_manual_handoff_resolution=accounting_manual_handoff_resolution,
            accounting_clarification_completion=accounting_clarification_completion,
            outside_agent_accounting_process=outside_agent_accounting_process,
            external_accounting_process_resolution=external_accounting_process_resolution,
            external_return_clarification_completion=external_return_clarification_completion,
            akaunting_probe=akaunting_probe,
            can_submit_accounting_review=_can_submit_accounting_review(accounting_analysis, accounting_operator_review),
            can_complete_accounting_clarification=_can_complete_accounting_clarification(accounting_manual_handoff_resolution, accounting_clarification_completion),
            can_resolve_external_accounting_process=_can_resolve_external_accounting_process(outside_agent_accounting_process, external_accounting_process_resolution),
            can_complete_external_return_clarification=_can_complete_external_return_clarification(external_accounting_process_resolution, external_return_clarification_completion),
            approval_next_step=approval_next_step,
            message=request.query_params.get('msg'),
        ),
    )


@router.get('/open-items', response_class=HTMLResponse)
async def ui_open_items(
    request: Request,
    status: str = Query(default='ALL'),
    priority: str = Query(default='ALL'),
    open_items_service: OpenItemsService = Depends(get_open_items_service),
) -> HTMLResponse:
    all_items = await open_items_service.list_items()

    rows: list[dict[str, Any]] = []
    for item in all_items:
        p = _priority_of(item)
        rows.append({'item': item, 'priority': p})

    status_counts = Counter(r['item'].status for r in rows)
    priority_counts = Counter(r['priority'] for r in rows)

    status_norm = status.upper()
    priority_norm = priority.upper()

    filtered = rows
    if status_norm != 'ALL':
        filtered = [r for r in filtered if r['item'].status == status_norm]
    if priority_norm != 'ALL':
        filtered = [r for r in filtered if r['priority'] == priority_norm]

    return TEMPLATES.TemplateResponse(
        request,
        'open_items.html',
        _ctx(
            request,
            title='Open Items',
            rows=filtered,
            selected_status=status_norm,
            selected_priority=priority_norm,
            statuses=['ALL', 'OPEN', 'WAITING_USER', 'WAITING_DATA', 'SCHEDULED', 'COMPLETED', 'CANCELLED'],
            priorities=['ALL', 'HIGH', 'MEDIUM', 'LOW', 'UNSET'],
            priority_note='Priority wird in V1 transparent aus due_at abgeleitet (HIGH/MEDIUM/LOW/UNSET).',
            status_counts=dict(status_counts),
            priority_counts=dict(priority_counts),
            total_count=len(rows),
            filtered_count=len(filtered),
        ),
    )


@router.get('/problem-cases', response_class=HTMLResponse)
async def ui_problem_cases(
    request: Request,
    type: str = Query(default='ALL'),
    risk: str = Query(default='ALL'),
    status: str = Query(default='ALL'),
    service: ProblemCaseService = Depends(get_problem_case_service),
) -> HTMLResponse:
    problems = await service.recent(limit=500)

    type_norm = type
    risk_norm = risk.upper()
    status_norm = status.upper()

    rows: list[dict[str, Any]] = []
    for p in problems:
        row_status = 'OPEN'
        row_type = p.exception_type or 'UNSET'
        row_risk = (p.severity or 'UNKNOWN').upper()
        rows.append({'problem': p, 'type': row_type, 'risk': row_risk, 'status': row_status})

    filtered = rows
    if type_norm != 'ALL':
        filtered = [r for r in filtered if r['type'] == type_norm]
    if risk_norm != 'ALL':
        filtered = [r for r in filtered if r['risk'] == risk_norm]
    if status_norm != 'ALL':
        filtered = [r for r in filtered if r['status'] == status_norm]

    type_options = sorted({'ALL', *[r['type'] for r in rows]})
    risk_options = sorted({'ALL', *[r['risk'] for r in rows]})

    return TEMPLATES.TemplateResponse(
        request,
        'problem_cases.html',
        _ctx(
            request,
            title='Problem Cases',
            rows=filtered,
            selected_type=type_norm,
            selected_risk=risk_norm,
            selected_status=status_norm,
            type_options=type_options,
            risk_options=risk_options,
            status_options=['ALL', 'OPEN'],
            status_note='Problem-Case-Status-Lifecycle ist aktuell noch nicht als separates Backend-Modell implementiert; V1 zeigt transparent OPEN.',
        ),
    )


@router.get('/rules', response_class=HTMLResponse)
async def ui_rules(
    request: Request,
    loader: RuleLoader = Depends(get_rule_loader),
) -> HTMLResponse:
    status_items = loader.load_status()
    return TEMPLATES.TemplateResponse(
        request,
        'rules_list.html',
        _ctx(request, title='Rules', status_items=status_items),
    )


@router.get('/rules/audit', response_class=HTMLResponse)
async def ui_rules_audit(
    request: Request,
    rule_change_service: RuleChangeAuditService = Depends(get_rule_change_audit_service),
) -> HTMLResponse:
    changes = await rule_change_service.recent(limit=300)
    return TEMPLATES.TemplateResponse(
        request,
        'rules_audit.html',
        _ctx(request, title='Rules Audit', changes=changes),
    )


@router.get('/rules/{file_name:path}', response_class=HTMLResponse)
async def ui_rule_detail(
    request: Request,
    file_name: str,
    loader: RuleLoader = Depends(get_rule_loader),
    approval_service: ApprovalService = Depends(get_approval_service),
) -> HTMLResponse:
    document = loader.load_rule_document(file_name)
    if not document['loaded']:
        raise HTTPException(status_code=404, detail='Regeldatei nicht gefunden oder nicht ladbar')

    msg = request.query_params.get('msg')
    approval_id = request.query_params.get('approval_id')
    approval_record = await approval_service.get(approval_id) if approval_id else None
    return TEMPLATES.TemplateResponse(
        request,
        'rule_detail.html',
        _ctx(
            request,
            title=f'Rule {file_name}',
            doc=document,
            message=msg,
            approval_id=approval_id,
            approval_record=approval_record,
            approval_next_step=approval_next_step,
        ),
    )


@router.post('/rules/{file_name:path}', dependencies=[Depends(require_csrf)])
async def ui_rule_update(
    request: Request,
    file_name: str,
    content: str = Form(...),
    reason: str = Form(...),
    approval_id: str | None = Form(default=None),
    loader: RuleLoader = Depends(get_rule_loader),
    policy_access: PolicyAccessLayer = Depends(get_policy_access_layer),
    approval_service: ApprovalService = Depends(get_approval_service),
    audit_service: AuditService = Depends(get_audit_service),
    rule_change_service: RuleChangeAuditService = Depends(get_rule_change_audit_service),
    current_user: AuthUser = Depends(require_admin),
) -> RedirectResponse:
    gate = policy_access.evaluate_gate(
        intent='WORKFLOW_TRIGGER',
        action_name='rule_policy_edit',
        context={'side_effect': True, 'confidence': 1.0},
    )
    case_id = f'rule:{file_name}'
    approved_record = await approval_service.get(approval_id) if approval_id else None
    approved_for_write = bool(
        approved_record
        and approved_record.status == 'APPROVED'
        and approved_record.case_id == case_id
        and approved_record.action_type == gate.action_key
        and approved_record.scope_ref == file_name
    )
    if not approved_for_write:
        approval = await approval_service.request_approval(
            case_id=case_id,
            action_type=gate.action_key,
            requested_by=current_user.username,
            scope_ref=file_name,
            reason=reason,
            policy_refs=gate.consulted_policy_refs,
            required_mode=gate.decision_mode,
            approval_context={'file_name': file_name, 'reason': reason},
            source='ui_rules',
        )
        return RedirectResponse(
            url=(
                f'/ui/rules/{file_name}?msg={quote("Freigabe erforderlich vor Rule-Update.")}'
                f'&approval_id={approval.approval_id}'
            ),
            status_code=HTTP_303_SEE_OTHER,
        )

    old_doc = loader.load_rule_document(file_name)
    old_content = old_doc['content'] if old_doc['loaded'] and old_doc['content'] is not None else ''
    old_version = old_doc.get('version') if old_doc['loaded'] else None

    loader.save_rule_file(file_name, content)
    new_doc = loader.load_rule_document(file_name)
    if not new_doc['loaded']:
        raise HTTPException(status_code=400, detail=f"Datei konnte nicht geladen werden: {new_doc.get('error')}")

    change_record = await rule_change_service.record_change(
        file_name=file_name,
        old_content=old_content,
        new_content=new_doc['content'] or '',
        changed_by=current_user.username,
        reason=reason,
        old_version=old_version,
        new_version=new_doc.get('version'),
    )

    await audit_service.log_event(
        {
            'event_id': str(uuid.uuid4()),
            'case_id': f'rule:{file_name}',
            'source': 'ui_rules',
            'agent_name': 'frya-policy-layer',
            'approval_status': 'APPROVED',
            'action': 'RULE_FILE_UPDATED_UI',
            'result': f'{file_name} updated by {current_user.username};approval_id={approved_record.approval_id}',
            'llm_input': {'old_version': old_version, 'new_version': new_doc.get('version'), 'approval_id': approved_record.approval_id},
            'llm_output': {'reason': reason, 'change_id': change_record.change_id, 'required_mode': gate.decision_mode},
            'policy_refs': gate.consulted_policy_refs,
        }
    )

    return RedirectResponse(
        url=f'/ui/rules/{file_name}?msg=Gespeichert&approval_id={approved_record.approval_id}',
        status_code=HTTP_303_SEE_OTHER,
    )


@router.get('/verfahrensdoku', response_class=HTMLResponse)
async def ui_verfahrensdoku(
    request: Request,
    file_store: FileStore = Depends(get_file_store),
) -> HTMLResponse:
    files = file_store.list_files('verfahrensdoku')
    return TEMPLATES.TemplateResponse(
        request,
        'verfahrensdoku.html',
        _ctx(request, title='Verfahrensdokumentation', files=files),
    )


@router.get('/system', response_class=HTMLResponse)
async def ui_system(
    request: Request,
    loader: RuleLoader = Depends(get_rule_loader),
    policy_access: PolicyAccessLayer = Depends(get_policy_access_layer),
) -> HTMLResponse:
    settings = get_settings()
    status = loader.load_status()
    entries = loader.list_rule_entries()
    required_ok, required_missing = policy_access.required_policies_loaded()

    connectors = [
        {'name': 'paperless', 'base_url': settings.paperless_base_url, 'configured': bool(settings.paperless_base_url)},
        {'name': 'akaunting', 'base_url': settings.akaunting_base_url, 'configured': bool(settings.akaunting_base_url)},
        {'name': 'n8n', 'base_url': settings.n8n_base_url, 'configured': bool(settings.n8n_base_url)},
    ]

    models = {
        'litellm_model': settings.llm_model,
        'openai_key_configured': bool(settings.openai_api_key),
        'anthropic_key_configured': bool(settings.anthropic_api_key),
    }

    feature_state = {
        'required_policy_roles': list(REQUIRED_POLICY_ROLES),
        'required_policies_loaded': required_ok,
        'missing_required_roles': required_missing,
        'explicit_feature_toggles_model': 'not_implemented_yet',
    }

    return TEMPLATES.TemplateResponse(
        request,
        'system.html',
        _ctx(
            request,
            title='System',
            connectors=connectors,
            rule_registry_entries=entries,
            rule_load_status=status,
            models=models,
            feature_state=feature_state,
        ),
    )








