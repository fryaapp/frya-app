from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from app.approvals.presentation import approval_next_step
from app.approvals.service import ApprovalService
from app.auth.csrf import require_csrf
from app.cases.urls import inspect_case_href
from app.auth.dependencies import require_admin, require_operator
from app.auth.models import AuthUser
from app.dependencies import get_approval_service

router = APIRouter(prefix='/inspect/approvals', tags=['inspect'], dependencies=[Depends(require_operator)])


class ApprovalDecisionRequest(BaseModel):
    decision: str
    decided_by: str | None = None
    reason: str | None = None


@router.get('', response_class=HTMLResponse)
async def approvals_view(
    case_id: str | None = Query(default=None),
    approval_service: ApprovalService = Depends(get_approval_service),
) -> str:
    approvals = await (approval_service.list_by_case(case_id) if case_id else approval_service.recent(limit=200))
    rows = ''.join(
        '<tr>'
        f'<td>{a.requested_at}</td>'
        f'<td>{a.approval_id}</td>'
        f"<td><a href='{inspect_case_href(a.case_id)}'>{a.case_id}</a></td>"
        f'<td>{a.action_type}</td>'
        f'<td>{a.required_mode}</td>'
        f'<td>{a.status}</td>'
        f'<td>{a.reason or ""}</td>'
        f'<td>{approval_next_step(a.status)}</td>'
        f'<td>{a.scope_ref or ""}</td>'
        f'<td>{a.open_item_id or ""}</td>'
        f'<td>{a.expires_at or ""}</td>'
        f'<td>{a.requested_by}</td>'
        f'<td>{a.decided_by or ""}</td>'
        '</tr>'
        for a in approvals
    )
    return (
        '<h1>Approvals</h1>'
        '<table border="1" cellpadding="6"><tr>'
        '<th>Zeit</th><th>Approval ID</th><th>Case</th><th>Action</th><th>Mode</th><th>Status</th>'
        '<th>Grund</th><th>Naechster Schritt</th><th>Scope</th><th>Open Item</th><th>Expires</th><th>Requested By</th><th>Decided By</th>'
        '</tr>'
        f'{rows}</table>'
    )


@router.get('/json')
async def approvals_json(
    case_id: str | None = Query(default=None),
    approval_service: ApprovalService = Depends(get_approval_service),
) -> list[dict]:
    approvals = await (approval_service.list_by_case(case_id) if case_id else approval_service.recent(limit=200))
    return [a.model_dump() for a in approvals]


@router.post('/{approval_id}/decision', dependencies=[Depends(require_csrf)])
async def decide_approval(
    approval_id: str,
    request: ApprovalDecisionRequest,
    approval_service: ApprovalService = Depends(get_approval_service),
    current_user: AuthUser = Depends(require_admin),
) -> dict:
    try:
        updated = await approval_service.decide_approval(
            approval_id=approval_id,
            decision=request.decision,
            decided_by=current_user.username,
            reason=request.reason,
            source='approval_ui',
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if updated is None:
        raise HTTPException(status_code=404, detail='Approval nicht gefunden')

    return {
        'status': 'ok',
        'approval_id': approval_id,
        'new_status': updated.status,
        'open_item_id': updated.open_item_id,
        'required_mode': updated.required_mode,
        'next_step': approval_next_step(updated.status),
    }


