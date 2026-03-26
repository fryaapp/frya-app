"""n8n Webhook-Endpoints — /api/n8n/*.

All endpoints require the n8n API token (X-N8N-API-KEY or Authorization: Bearer).
These endpoints are called by n8n Cron/Webhook nodes on staging.

Endpoints:
  POST /api/n8n/fristen-check          — run full deadline check
  POST /api/n8n/skonto-warnung         — only skonto_expiring items
  POST /api/n8n/mahnwesen              — list OVERDUE outgoing_invoice cases
  POST /api/n8n/frist-eskalation       — overdue >14 days → create ProblemCase
  POST /api/n8n/paperless-post-consumption — forward to /api/cases/assign
  POST /api/n8n/tages-summary          — daily summary of memory state + cases
"""
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.config import get_settings
from app.deadline_analyst.service import build_deadline_analyst_service
from app.dependencies import (
    get_case_repository,
    get_llm_config_repository,
    get_problem_case_service,
)

router = APIRouter(prefix='/api/n8n', tags=['n8n'])


# ---------------------------------------------------------------------------
# Shared auth dependency
# ---------------------------------------------------------------------------

async def require_n8n_token(request: Request) -> None:
    """Accept X-N8N-API-KEY header or Authorization: Bearer token."""
    settings = get_settings()
    token = (
        request.headers.get('x-n8n-api-key')
        or request.headers.get('authorization', '').removeprefix('Bearer ').strip()
    )
    if not settings.n8n_token or token != settings.n8n_token:
        raise HTTPException(status_code=401, detail='Valid n8n API token required.')


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class N8NTenantRequest(BaseModel):
    tenant_id: str


class PaperlessPostConsumptionRequest(BaseModel):
    tenant_id: str
    document_source: str = 'paperless'
    document_source_id: str
    reference_values: list[list[str]] = Field(default_factory=list)
    vendor_name: str | None = None
    total_amount: float | None = None
    currency: str = 'EUR'
    document_date: date | None = None
    filename: str | None = None


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _parse_tenant_uuid(tenant_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(tenant_id)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail=f'Invalid tenant_id UUID: {tenant_id!r}')


async def _build_deadline_svc(tenant_id: uuid.UUID):
    repo = get_case_repository()
    llm_repo = get_llm_config_repository()
    config = await llm_repo.get_config('deadline_analyst')
    svc = build_deadline_analyst_service(repo, llm_repo, config)
    return svc, repo


# ---------------------------------------------------------------------------
# POST /api/n8n/fristen-check
# Workflow 1 (Cron 08:00): full deadline report
# ---------------------------------------------------------------------------

@router.post('/fristen-check', dependencies=[Depends(require_n8n_token)])
async def fristen_check(body: N8NTenantRequest) -> dict[str, Any]:
    """Run full deadline check for a tenant and return the DeadlineReport."""
    tid = _parse_tenant_uuid(body.tenant_id)
    svc, _ = await _build_deadline_svc(tid)
    report = await svc.check_all_deadlines(tid)
    return report.model_dump(mode='json')


# ---------------------------------------------------------------------------
# POST /api/n8n/skonto-warnung
# Workflow 2 (Cron 08:00): only skonto_expiring items
# ---------------------------------------------------------------------------

@router.post('/skonto-warnung', dependencies=[Depends(require_n8n_token)])
async def skonto_warnung(body: N8NTenantRequest) -> dict[str, Any]:
    """Return only the skonto_expiring subset of the deadline report."""
    tid = _parse_tenant_uuid(body.tenant_id)
    svc, _ = await _build_deadline_svc(tid)
    report = await svc.check_all_deadlines(tid)
    skonto = report.skonto_expiring
    return {
        'tenant_id': body.tenant_id,
        'count': len(skonto),
        'skonto_expiring': [c.model_dump(mode='json') for c in skonto],
        'checked_at': datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# POST /api/n8n/mahnwesen
# Workflow 3 (Cron 09:00): OVERDUE outgoing_invoice cases
# ---------------------------------------------------------------------------

@router.post('/mahnwesen', dependencies=[Depends(require_n8n_token)])
async def mahnwesen(body: N8NTenantRequest) -> dict[str, Any]:
    """Return all OVERDUE outgoing_invoice cases for a tenant."""
    tid = _parse_tenant_uuid(body.tenant_id)
    repo = get_case_repository()
    cases = await repo.list_cases(tid, status='OVERDUE', limit=200)
    outgoing = [c for c in cases if c.case_type == 'outgoing_invoice']
    return {
        'tenant_id': body.tenant_id,
        'count': len(outgoing),
        'cases': [
            {
                'case_id': str(c.id),
                'case_number': c.case_number,
                'title': c.title,
                'vendor_name': c.vendor_name,
                'total_amount': str(c.total_amount) if c.total_amount else None,
                'currency': c.currency,
                'due_date': c.due_date.isoformat() if c.due_date else None,
                'created_at': c.created_at.isoformat() if c.created_at else None,
            }
            for c in outgoing
        ],
        'checked_at': datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# POST /api/n8n/frist-eskalation
# Workflow 4 (Cron 08:00): overdue >14 days → ProblemCase
# ---------------------------------------------------------------------------

@router.post('/frist-eskalation', dependencies=[Depends(require_n8n_token)])
async def frist_eskalation(body: N8NTenantRequest) -> dict[str, Any]:
    """Create ProblemCase entries for cases overdue more than 14 days."""
    tid = _parse_tenant_uuid(body.tenant_id)
    repo = get_case_repository()
    problem_svc = get_problem_case_service()
    today = date.today()

    cases = await repo.list_cases(tid, status='OVERDUE', limit=200)

    escalated = []
    for c in cases:
        if c.due_date is None:
            continue
        days_overdue = (today - c.due_date).days
        if days_overdue > 14:
            problem = await problem_svc.add_case(
                case_id=str(c.id),
                title=f'Frist-Eskalation: {c.title or c.case_number} ({days_overdue} Tage ueberfaellig)',
                details=(
                    f'Fall {c.case_number} ist seit {days_overdue} Tagen ueberfaellig. '
                    f'Faelligkeitsdatum: {c.due_date}. '
                    f'Betrag: {c.total_amount} {c.currency}.'
                ),
                severity='HIGH',
                exception_type='deadline_escalation',
                created_by='n8n-frist-eskalation',
            )
            escalated.append({
                'case_id': str(c.id),
                'case_number': c.case_number,
                'days_overdue': days_overdue,
                'problem_id': problem.problem_id,
            })

    return {
        'tenant_id': body.tenant_id,
        'escalated_count': len(escalated),
        'escalated': escalated,
        'checked_at': datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# POST /api/n8n/paperless-post-consumption
# Workflow 5 (Webhook): forward Paperless document to case assignment
# ---------------------------------------------------------------------------

@router.post('/paperless-post-consumption', dependencies=[Depends(require_n8n_token)])
async def paperless_post_consumption(body: PaperlessPostConsumptionRequest) -> dict[str, Any]:
    """Forward a Paperless-ngx post-consumption event to the case assignment engine."""
    import logging as _logging
    from app.case_engine.assignment import CaseAssignmentEngine, DocumentData
    from app.dependencies import get_bulk_upload_repository

    _log = _logging.getLogger(__name__)
    tid = _parse_tenant_uuid(body.tenant_id)
    repo = get_case_repository()
    engine = CaseAssignmentEngine(repo)

    doc = DocumentData(
        document_source=body.document_source,
        document_source_id=body.document_source_id,
        reference_values=body.reference_values,
        vendor_name=body.vendor_name,
        total_amount=float(body.total_amount) if body.total_amount is not None else None,
        currency=body.currency,
        document_date=body.document_date,
        filename=body.filename,
    )

    result = await engine.assign_document(tenant_id=tid, doc=doc)
    assigned_case_id: str | None = None
    assignment_confidence: str | None = None

    if result is None:
        response_body: dict[str, Any] = {
            'assigned': False, 'case_id': None, 'confidence': None, 'method': None,
        }
    else:
        # Persist document-case link
        await repo.add_document_to_case(
            case_id=result.case_id,
            document_source=doc.document_source,
            document_source_id=doc.document_source_id,
            assignment_confidence=result.confidence,
            assignment_method=result.method,
            filename=doc.filename,
        )
        assigned_case_id = str(result.case_id)
        assignment_confidence = result.confidence
        response_body = {'assigned': True, **result.model_dump(mode='json')}

    # ── Bulk-Upload Bridge 2: document_id → case_id ────────────────────────────
    # If this document came from a bulk-upload, update the upload item status.
    # ALWAYS use tenant_id in the lookup (never without).
    try:
        paperless_doc_id_str = body.document_source_id
        paperless_doc_id_int: int | None = None
        try:
            paperless_doc_id_int = int(paperless_doc_id_str)
        except (ValueError, TypeError) as exc:
            logger.debug('paperless_post_consumption: doc_id not an int: %s', exc)

        if paperless_doc_id_int is not None:
            bulk_repo = get_bulk_upload_repository()
            upload_item = await bulk_repo.find_item_by_paperless_doc(
                body.tenant_id, paperless_doc_id_int
            )
            if upload_item is not None:
                # Store doc_data in metadata for potential re-evaluate
                doc_data = {
                    'document_source': body.document_source,
                    'document_source_id': body.document_source_id,
                    'reference_values': body.reference_values,
                    'vendor_name': body.vendor_name,
                    'total_amount': body.total_amount,
                    'currency': body.currency,
                    'filename': body.filename,
                }
                await bulk_repo.update_item_case(
                    upload_item['id'],
                    case_id=assigned_case_id,
                    confidence=assignment_confidence,
                    doc_data=doc_data,
                )
                await bulk_repo.update_item_status(upload_item['id'], 'completed')
                _log.info(
                    'Bulk-Upload Bridge 2: item %s → case %s (tenant %s)',
                    upload_item['id'], assigned_case_id, body.tenant_id,
                )
    except Exception as exc:
        # Bridge 2 failure must NOT break the existing case assignment flow
        _log.warning('Bulk-Upload Bridge 2 failed: %s', exc)

    return response_body


# ---------------------------------------------------------------------------
# POST /api/n8n/tages-summary
# Workflow 6 (Cron 18:00): daily summary → memory state + open cases
# ---------------------------------------------------------------------------

@router.post('/tages-summary', dependencies=[Depends(require_n8n_token)])
async def tages_summary(body: N8NTenantRequest) -> dict[str, Any]:
    """Return a daily summary: open case counts by status + memory DMS state."""
    tid = _parse_tenant_uuid(body.tenant_id)
    repo = get_case_repository()

    # Collect counts per status
    status_list = ['DRAFT', 'OPEN', 'OVERDUE', 'PAID', 'CLOSED']
    counts: dict[str, int] = {}
    for st in status_list:
        cases = await repo.list_cases(tid, status=st, limit=1000)
        counts[st.lower()] = len(cases)

    # Try memory curator DMS state (optional — graceful fallback)
    dms_state: dict | None = None
    try:
        from app.memory_curator.service import MemoryCuratorService
        settings = get_settings()
        curator = MemoryCuratorService(
            data_dir=settings.data_dir,
            case_repository=repo,
        )
        dms_state = (await curator.get_dms_state(tid)).model_dump(mode='json')
    except Exception as exc:
        logger.warning('tages_summary: DMS state fetch failed: %s', exc)
        dms_state = None

    return {
        'tenant_id': body.tenant_id,
        'date': date.today().isoformat(),
        'case_counts': counts,
        'total_open': counts.get('open', 0) + counts.get('overdue', 0) + counts.get('draft', 0),
        'dms_state': dms_state,
        'generated_at': datetime.now(timezone.utc).isoformat(),
    }
