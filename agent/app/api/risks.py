"""Risk Analyst REST API — /api/risk.

Endpoints:
  POST /api/risk/{case_id}/check   — run all checks, store result
  GET  /api/risk/{case_id}/report  — return stored result
  POST /api/risk/scan-all          — check all open/overdue cases for a tenant

All endpoints require operator auth.
"""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from app.auth.csrf import require_csrf
from app.auth.dependencies import require_operator
from app.dependencies import get_case_repository, get_llm_config_repository
from app.risk_analyst.service import build_risk_analyst_service

router = APIRouter(prefix='/api/risk', tags=['risk-analyst'])


def _parse_uuid(val: str) -> uuid.UUID:
    try:
        return uuid.UUID(val)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail=f'Invalid UUID: {val!r}')


# ---------------------------------------------------------------------------
# POST /api/risk/{case_id}/check
# ---------------------------------------------------------------------------

@router.post('/{case_id}/check', dependencies=[Depends(require_operator), Depends(require_csrf)])
async def risk_check(case_id: str) -> dict[str, Any]:
    """Run all risk checks for a case and store the report in case metadata."""
    cid = _parse_uuid(case_id)
    repo = get_case_repository()
    llm_repo = get_llm_config_repository()
    config = await llm_repo.get_config('risk_consistency')
    svc = build_risk_analyst_service(repo, llm_repo, config)

    report = await svc.analyze_case(cid)
    if report is None:
        raise HTTPException(status_code=404, detail='Case nicht gefunden.')
    return report.model_dump(mode='json')


# ---------------------------------------------------------------------------
# GET /api/risk/{case_id}/report
# ---------------------------------------------------------------------------

@router.get('/{case_id}/report', dependencies=[Depends(require_operator)])
async def get_risk_report(case_id: str) -> dict[str, Any]:
    """Return the stored risk report for a case (404 if not yet analysed)."""
    cid = _parse_uuid(case_id)
    repo = get_case_repository()
    case = await repo.get_case(cid)
    if case is None:
        raise HTTPException(status_code=404, detail='Case nicht gefunden.')
    report = case.metadata.get('risk_report')
    if not report:
        raise HTTPException(status_code=404, detail='Kein Risikobericht vorhanden.')
    return report


# ---------------------------------------------------------------------------
# POST /api/risk/scan-all
# ---------------------------------------------------------------------------

@router.post('/scan-all', dependencies=[Depends(require_operator), Depends(require_csrf)])
async def scan_all(tenant_id: str) -> list[dict[str, Any]]:
    """Run risk checks for all open/overdue cases of a tenant."""
    tid = _parse_uuid(tenant_id)
    repo = get_case_repository()
    llm_repo = get_llm_config_repository()
    config = await llm_repo.get_config('risk_consistency')
    svc = build_risk_analyst_service(repo, llm_repo, config)

    reports = await svc.scan_all_open_cases(tid)
    return [r.model_dump(mode='json') for r in reports]
