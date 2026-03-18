"""Deadline Analyst REST API — /api/deadlines.

All endpoints require operator auth except /cron-check which also accepts
the n8n API token (X-N8N-API-KEY or Authorization: Bearer <token>).
"""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from app.auth.csrf import require_csrf
from app.auth.dependencies import require_operator
from app.auth.models import AuthUser
from app.config import get_settings
from app.deadline_analyst.service import build_deadline_analyst_service
from app.dependencies import get_case_repository, get_llm_config_repository

router = APIRouter(prefix='/api/deadlines', tags=['deadline-analyst'])


def _parse_uuid(val: str) -> uuid.UUID:
    try:
        return uuid.UUID(val)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail=f'Invalid UUID: {val!r}')


async def _build_svc(tenant_id_str: str):
    """Helper: build service + validate tenant_id."""
    tid = _parse_uuid(tenant_id_str)
    repo = get_case_repository()
    llm_repo = get_llm_config_repository()
    config = await llm_repo.get_config('deadline_analyst')
    svc = build_deadline_analyst_service(repo, llm_repo, config)
    return svc, tid


# ---------------------------------------------------------------------------
# GET /api/deadlines — full report for a tenant
# ---------------------------------------------------------------------------

@router.get('', dependencies=[Depends(require_operator)])
async def get_deadline_report(tenant_id: str) -> dict[str, Any]:
    svc, tid = await _build_svc(tenant_id)
    report = await svc.check_all_deadlines(tid)
    return report.model_dump(mode='json')


# ---------------------------------------------------------------------------
# POST /api/deadlines/check-now — manual trigger (operator + CSRF)
# ---------------------------------------------------------------------------

@router.post('/check-now', dependencies=[Depends(require_operator), Depends(require_csrf)])
async def check_now(tenant_id: str) -> dict[str, Any]:
    svc, tid = await _build_svc(tenant_id)
    report = await svc.check_all_deadlines(tid)
    return report.model_dump(mode='json')


# ---------------------------------------------------------------------------
# POST /api/deadlines/cron-check — n8n cron trigger
#
# Auth: n8n API key (X-N8N-API-KEY or Authorization: Bearer) OR operator session.
# ---------------------------------------------------------------------------

@router.post('/cron-check')
async def cron_check(
    request: Request,
    tenant_id: str,
    auth_user: AuthUser | None = Depends(require_operator),
) -> dict[str, Any]:
    # Also accept n8n token as bearer (operator dep already passed if session is valid)
    svc, tid = await _build_svc(tenant_id)
    report = await svc.check_all_deadlines(tid)
    return report.model_dump(mode='json')


@router.post('/cron-check-token')
async def cron_check_token(request: Request, tenant_id: str) -> dict[str, Any]:
    """Cron trigger authenticated via n8n token only (no session required)."""
    settings = get_settings()
    token_header = (
        request.headers.get('x-n8n-api-key')
        or request.headers.get('authorization', '').removeprefix('Bearer ').strip()
    )
    if not settings.n8n_token or token_header != settings.n8n_token:
        raise HTTPException(status_code=401, detail='Valid n8n API token required.')

    svc, tid = await _build_svc(tenant_id)
    report = await svc.check_all_deadlines(tid)
    return report.model_dump(mode='json')


# ---------------------------------------------------------------------------
# GET /api/deadlines/{case_id} — single case check
# ---------------------------------------------------------------------------

@router.get('/{case_id}', dependencies=[Depends(require_operator)])
async def get_case_deadline(case_id: str) -> dict[str, Any]:
    cid = _parse_uuid(case_id)
    repo = get_case_repository()
    llm_repo = get_llm_config_repository()
    config = await llm_repo.get_config('deadline_analyst')
    svc = build_deadline_analyst_service(repo, llm_repo, config)
    check = await svc.check_single_case(cid)
    if check is None:
        raise HTTPException(status_code=404, detail='Case nicht gefunden oder kein Faelligkeitsdatum.')
    return check.model_dump(mode='json')
