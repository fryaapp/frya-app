"""API endpoint for dunning (Mahnwesen) escalation check."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.auth.dependencies import require_admin
from app.auth.models import AuthUser
from app.config import get_settings
from app.dunning.service import DunningService

router = APIRouter(prefix='/api/v1/dunning', tags=['dunning'])


@router.post('/check')
async def check_dunning(user: AuthUser = Depends(require_admin)):
    settings = get_settings()
    # Use default tenant for single-tenant staging
    tenant_id = settings.default_tenant_id or 'default'
    service = DunningService(settings.database_url)
    escalated = await service.check_and_escalate(tenant_id)
    return {'escalated': len(escalated), 'items': escalated}
