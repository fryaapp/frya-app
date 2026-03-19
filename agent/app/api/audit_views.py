from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse

from app.auth.dependencies import require_operator
from app.audit.service import AuditService
from app.dependencies import get_audit_service

router = APIRouter(prefix='/inspect/audit', tags=['inspect'], dependencies=[Depends(require_operator)])


@router.get('', response_class=HTMLResponse)
async def audit_view(
    case_id: str | None = Query(default=None),
    audit_service: AuditService = Depends(get_audit_service),
) -> str:
    records = await (audit_service.by_case(case_id, limit=500) if case_id else audit_service.recent(limit=200))
    rows = ''.join(
        f"<tr><td>{r.created_at}</td><td>{r.case_id}</td><td>{r.event_id}</td><td>{r.source}</td><td>{r.action}</td><td>{r.approval_status}</td><td>{r.result}</td><td>{len(r.policy_refs)}</td></tr>"
        for r in records
    )
    return (
        '<h1>FRYA Audit View</h1>'
        '<p>Append-only Ereignisse mit Hash-Chain.</p>'
        '<table border="1" cellpadding="6"><tr><th>Zeit</th><th>Case</th><th>Event</th><th>Quelle</th><th>Aktion</th><th>Freigabe</th><th>Ergebnis</th><th>Policy Refs</th></tr>'
        f'{rows}</table>'
    )


@router.get('/json')
async def audit_json(
    case_id: str | None = Query(default=None),
    audit_service: AuditService = Depends(get_audit_service),
) -> list[dict]:
    records = await (audit_service.by_case(case_id, limit=500) if case_id else audit_service.recent(limit=200))
    return [r.model_dump() for r in records]


@router.get('/verify-chain')
async def verify_chain(
    audit_service: AuditService = Depends(get_audit_service),
) -> dict:
    """GoBD-Compliance: verify hash-chain integrity across all audit records.

    Returns valid=true if every record's previous_hash matches
    the record_hash of its predecessor (append-only guarantee).
    """
    return await audit_service.verify_chain()
