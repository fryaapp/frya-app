"""CaseEngine REST API — /api/cases.

All endpoints require operator auth. PAID/CLOSED transitions are allowed for
operator-role and above (enforced by the require_operator dependency).
"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.accounting_analyst.schemas import BookingProposal, CaseAnalysisInput
from app.accounting_analyst.service import build_accounting_analyst_service
from app.auth.csrf import require_csrf
from app.auth.dependencies import require_operator
from app.auth.models import AuthUser
from app.case_engine.assignment import CaseAssignmentEngine, DocumentData
from app.case_engine.status import StatusTransitionError
from app.dependencies import get_case_repository, get_llm_config_repository

router = APIRouter(prefix='/api/cases', tags=['case-engine'])


# ── Request models ────────────────────────────────────────────────────────────

class CreateCaseRequest(BaseModel):
    tenant_id: uuid.UUID
    case_type: str
    title: str | None = None
    vendor_name: str | None = None
    total_amount: float | None = None
    currency: str = 'EUR'
    due_date: date | None = None
    created_by: str | None = None
    metadata: dict = Field(default_factory=dict)


class UpdateStatusRequest(BaseModel):
    status: str


class AddDocumentRequest(BaseModel):
    document_source: str
    document_source_id: str
    assignment_confidence: str
    assignment_method: str
    document_type: str | None = None
    assigned_by: str | None = None
    filename: str | None = None
    metadata: dict = Field(default_factory=dict)


class AddReferenceRequest(BaseModel):
    reference_type: str
    reference_value: str
    extracted_from_document_id: uuid.UUID | None = None


class AssignRequest(BaseModel):
    tenant_id: uuid.UUID
    document_source: str
    document_source_id: str
    reference_values: list[list[str]] = Field(default_factory=list)
    vendor_name: str | None = None
    total_amount: float | None = None
    currency: str = 'EUR'
    document_date: date | None = None
    filename: str | None = None


class MergeRequest(BaseModel):
    target_case_id: uuid.UUID


class ResolveConflictRequest(BaseModel):
    resolution: str
    resolved_by: str | None = None


# ── helpers ───────────────────────────────────────────────────────────────────

def _parse_uuid(val: str) -> uuid.UUID:
    try:
        return uuid.UUID(val)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail=f'Invalid UUID: {val!r}')


# ── endpoints — specific paths BEFORE parameterized ──────────────────────────

@router.get('', dependencies=[Depends(require_operator)])
async def list_cases(
    tenant_id: str,
    status: str | None = None,
    case_type: str | None = None,
    offset: int = 0,
    limit: int = 50,
) -> list[dict[str, Any]]:
    tid = _parse_uuid(tenant_id)
    repo = get_case_repository()
    cases = await repo.list_cases(tid, status=status, offset=offset, limit=limit)
    if case_type:
        cases = [c for c in cases if c.case_type == case_type]
    return [c.model_dump(mode='json') for c in cases]


@router.post('', dependencies=[Depends(require_operator), Depends(require_csrf)], status_code=201)
async def create_case(
    body: CreateCaseRequest,
    auth_user: AuthUser = Depends(require_operator),
) -> dict[str, Any]:
    repo = get_case_repository()
    amount = Decimal(str(body.total_amount)) if body.total_amount is not None else None
    case = await repo.create_case(
        tenant_id=body.tenant_id,
        case_type=body.case_type,
        title=body.title,
        vendor_name=body.vendor_name,
        total_amount=amount,
        currency=body.currency,
        due_date=body.due_date,
        created_by=body.created_by or auth_user.username,
        metadata=body.metadata,
    )
    return case.model_dump(mode='json')


@router.post('/assign', dependencies=[Depends(require_operator), Depends(require_csrf)])
async def assign_document(body: AssignRequest) -> dict[str, Any]:
    """Run the two-layer assignment engine against existing cases."""
    repo = get_case_repository()
    engine = CaseAssignmentEngine(repo)
    doc = DocumentData(
        document_source=body.document_source,
        document_source_id=body.document_source_id,
        reference_values=[(r[0], r[1]) for r in body.reference_values if len(r) == 2],
        vendor_name=body.vendor_name,
        total_amount=body.total_amount,
        currency=body.currency,
        document_date=body.document_date,
        filename=body.filename,
    )
    result = await engine.assign_document(body.tenant_id, doc)
    if result is None:
        return {'assigned': False, 'case_id': None, 'confidence': None, 'method': None}
    return {
        'assigned': True,
        'case_id': str(result.case_id),
        'confidence': result.confidence,
        'method': result.method,
    }


@router.patch('/conflicts/{conflict_id}', dependencies=[Depends(require_operator), Depends(require_csrf)])
async def resolve_conflict(conflict_id: str, body: ResolveConflictRequest) -> dict[str, Any]:
    cid = _parse_uuid(conflict_id)
    repo = get_case_repository()
    try:
        conflict = await repo.resolve_conflict(cid, body.resolution, resolved_by=body.resolved_by)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return conflict.model_dump(mode='json')


# ── parameterized endpoints ───────────────────────────────────────────────────

@router.get('/{case_id}', dependencies=[Depends(require_operator)])
async def get_case(case_id: str) -> dict[str, Any]:
    cid = _parse_uuid(case_id)
    repo = get_case_repository()
    case = await repo.get_case(cid)
    if case is None:
        raise HTTPException(status_code=404, detail='Case nicht gefunden.')
    docs = await repo.get_case_documents(cid)
    conflicts = await repo.get_conflicts(cid)
    # References: collect via case_id lookup
    refs = [
        r for r in repo._references.values() if r.case_id == cid
    ] if repo.is_memory else await _fetch_refs_pg(repo, cid)
    return {
        **case.model_dump(mode='json'),
        'documents': [d.model_dump(mode='json') for d in docs],
        'references': [r.model_dump(mode='json') for r in refs],
        'conflicts': [c.model_dump(mode='json') for c in conflicts],
    }


async def _fetch_refs_pg(repo: Any, case_id: uuid.UUID) -> list:
    """Fetch references for a case from PostgreSQL."""
    import asyncpg
    from app.case_engine.models import CaseReferenceRecord
    conn = await asyncpg.connect(repo.database_url)
    try:
        rows = await conn.fetch(
            "SELECT * FROM case_references WHERE case_id=$1 ORDER BY created_at",
            case_id,
        )
    finally:
        await conn.close()
    return [CaseReferenceRecord(**dict(r)) for r in rows]


@router.patch('/{case_id}/status', dependencies=[Depends(require_operator), Depends(require_csrf)])
async def update_status(
    case_id: str,
    body: UpdateStatusRequest,
    auth_user: AuthUser = Depends(require_operator),
) -> dict[str, Any]:
    cid = _parse_uuid(case_id)
    repo = get_case_repository()
    # All authenticated users (operator+) are treated as operators for status transitions
    try:
        case = await repo.update_case_status(cid, body.status, operator=True)
    except StatusTransitionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return case.model_dump(mode='json')


@router.post('/{case_id}/documents', dependencies=[Depends(require_operator), Depends(require_csrf)])
async def add_document(
    case_id: str,
    body: AddDocumentRequest,
    auth_user: AuthUser = Depends(require_operator),
) -> dict[str, Any]:
    cid = _parse_uuid(case_id)
    repo = get_case_repository()
    case = await repo.get_case(cid)
    if case is None:
        raise HTTPException(status_code=404, detail='Case nicht gefunden.')
    doc = await repo.add_document_to_case(
        case_id=cid,
        document_source=body.document_source,
        document_source_id=body.document_source_id,
        assignment_confidence=body.assignment_confidence,
        assignment_method=body.assignment_method,
        document_type=body.document_type,
        assigned_by=body.assigned_by or auth_user.username,
        filename=body.filename,
        metadata=body.metadata,
    )
    return doc.model_dump(mode='json')


@router.post('/{case_id}/references', dependencies=[Depends(require_operator), Depends(require_csrf)])
async def add_reference(case_id: str, body: AddReferenceRequest) -> dict[str, Any]:
    cid = _parse_uuid(case_id)
    repo = get_case_repository()
    case = await repo.get_case(cid)
    if case is None:
        raise HTTPException(status_code=404, detail='Case nicht gefunden.')
    ref = await repo.add_reference(
        case_id=cid,
        reference_type=body.reference_type,
        reference_value=body.reference_value,
        extracted_from_document_id=body.extracted_from_document_id,
    )
    return ref.model_dump(mode='json')


@router.post('/{case_id}/merge', dependencies=[Depends(require_operator), Depends(require_csrf)])
async def merge_cases(case_id: str, body: MergeRequest) -> dict[str, Any]:
    source_id = _parse_uuid(case_id)
    repo = get_case_repository()
    try:
        result = await repo.merge_cases(source_id, body.target_case_id, operator=True)
    except StatusTransitionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return result.model_dump(mode='json')


@router.post('/{case_id}/analyze-booking', dependencies=[Depends(require_operator), Depends(require_csrf)])
async def analyze_booking(case_id: str) -> dict[str, Any]:
    """Run the Accounting Analyst and store the SKR03 booking proposal in case metadata."""
    cid = _parse_uuid(case_id)
    repo = get_case_repository()
    case = await repo.get_case(cid)
    if case is None:
        raise HTTPException(status_code=404, detail='Case nicht gefunden.')

    llm_repo = get_llm_config_repository()
    config = await llm_repo.get_config('accounting_analyst')
    svc = build_accounting_analyst_service(llm_repo, config)

    doc_type: str | None = None
    if isinstance(case.metadata.get('document_analysis'), dict):
        doc_type = case.metadata['document_analysis'].get('document_type')

    case_input = CaseAnalysisInput(
        case_id=str(case.id),
        case_type=case.case_type,
        vendor_name=case.vendor_name,
        total_amount=case.total_amount,
        currency=case.currency,
        due_date=case.due_date,
        title=case.title,
        document_type=doc_type,
        metadata=case.metadata,
    )
    proposal = await svc.analyze(case_input)
    await repo.update_metadata(cid, {'booking_proposal': proposal.model_dump(mode='json')})
    return proposal.model_dump(mode='json')


@router.get('/{case_id}/booking-proposal', dependencies=[Depends(require_operator)])
async def get_booking_proposal(case_id: str) -> dict[str, Any]:
    """Return the stored booking proposal for a case, or 404 if none exists."""
    cid = _parse_uuid(case_id)
    repo = get_case_repository()
    case = await repo.get_case(cid)
    if case is None:
        raise HTTPException(status_code=404, detail='Case nicht gefunden.')
    proposal = case.metadata.get('booking_proposal')
    if not proposal:
        raise HTTPException(status_code=404, detail='Kein Buchungsvorschlag vorhanden.')
    return proposal


@router.post('/{case_id}/booking-proposal/confirm', dependencies=[Depends(require_operator), Depends(require_csrf)])
async def confirm_booking_proposal(case_id: str) -> dict[str, Any]:
    """Mark the booking proposal as CONFIRMED."""
    return await _update_proposal_status(case_id, 'CONFIRMED')


@router.post('/{case_id}/booking-proposal/reject', dependencies=[Depends(require_operator), Depends(require_csrf)])
async def reject_booking_proposal(case_id: str) -> dict[str, Any]:
    """Mark the booking proposal as REJECTED."""
    return await _update_proposal_status(case_id, 'REJECTED')


async def _update_proposal_status(case_id: str, status: str) -> dict[str, Any]:
    cid = _parse_uuid(case_id)
    repo = get_case_repository()
    case = await repo.get_case(cid)
    if case is None:
        raise HTTPException(status_code=404, detail='Case nicht gefunden.')
    proposal = case.metadata.get('booking_proposal')
    if not proposal:
        raise HTTPException(status_code=404, detail='Kein Buchungsvorschlag vorhanden.')
    proposal['status'] = status
    await repo.update_metadata(cid, {'booking_proposal': proposal})
    return proposal


@router.get('/{case_id}/conflicts', dependencies=[Depends(require_operator)])
async def list_conflicts(case_id: str) -> list[dict[str, Any]]:
    cid = _parse_uuid(case_id)
    repo = get_case_repository()
    case = await repo.get_case(cid)
    if case is None:
        raise HTTPException(status_code=404, detail='Case nicht gefunden.')
    conflicts = await repo.get_conflicts(cid)
    return [c.model_dump(mode='json') for c in conflicts]
