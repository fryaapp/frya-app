"""Memory Curator REST API.

Endpoints:
  POST /api/memory/curate-daily   — run daily curation for a tenant (n8n cron)
  GET  /api/memory/state          — current DMS state (from DB)
  GET  /api/memory/context        — full context assembly (for debug)

Auth:
  POST /api/memory/curate-daily   — requires operator + CSRF
  GET  /api/memory/state          — requires operator
  GET  /api/memory/context        — requires operator
"""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from app.auth.csrf import require_csrf
from app.auth.dependencies import require_operator
from app.config import get_settings
from app.dependencies import get_accounting_repository, get_audit_service, get_case_repository, get_llm_config_repository
from app.memory_curator.schemas import CurationResult, DmsState
from app.memory_curator.service import build_memory_curator_service

router = APIRouter(prefix='/api/memory', tags=['memory-curator'])


def _parse_uuid(val: str) -> uuid.UUID:
    try:
        return uuid.UUID(val)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail=f'Invalid UUID: {val!r}')


def _get_service():
    settings = get_settings()
    return build_memory_curator_service(
        data_dir=settings.data_dir,
        llm_config_repository=get_llm_config_repository(),
        case_repository=get_case_repository(),
        audit_service=get_audit_service(),
        accounting_repository=get_accounting_repository(),
    )


# ---------------------------------------------------------------------------
# POST /api/memory/curate-daily
# ---------------------------------------------------------------------------

@router.post('/curate-daily', dependencies=[Depends(require_operator), Depends(require_csrf)])
async def curate_daily(tenant_id: str) -> dict[str, Any]:
    """Run daily memory curation for a tenant. Called by n8n cron at 23:00."""
    tid = _parse_uuid(tenant_id)
    svc = _get_service()
    result = await svc.curate_daily(tid)
    return result.model_dump(mode='json')


# ---------------------------------------------------------------------------
# GET /api/memory/state
# ---------------------------------------------------------------------------

@router.get('/state', dependencies=[Depends(require_operator)])
async def get_memory_state(tenant_id: str) -> dict[str, Any]:
    """Return current DMS state calculated from DB (no LLM needed)."""
    tid = _parse_uuid(tenant_id)
    svc = _get_service()
    state = await svc.get_dms_state(tid)
    return state.model_dump(mode='json')


# ---------------------------------------------------------------------------
# GET /api/memory/context
# ---------------------------------------------------------------------------

@router.get('/context', dependencies=[Depends(require_operator)])
async def get_memory_context(tenant_id: str) -> dict[str, Any]:
    """Return full context assembly string (for debugging and verification)."""
    tid = _parse_uuid(tenant_id)
    svc = _get_service()
    context = await svc.get_context_assembly(tid)
    return {'tenant_id': str(tid), 'context': context, 'tokens_estimate': len(context) // 4}
