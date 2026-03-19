"""Tenant management API: soft-delete, hard-delete, status."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth.dependencies import require_admin
from app.auth.models import AuthUser
from app.auth.tenant_repository import TenantRecord, TenantRepository
from app.dependencies import get_audit_service, get_mail_service, get_user_repository
from app.email.mail_service import MailService

router = APIRouter(prefix='/api/admin/tenants', tags=['tenants'])

_HARD_DELETE_DAYS = 30


def _get_tenant_repo() -> TenantRepository:
    from app.dependencies import get_tenant_repository
    return get_tenant_repository()


class TenantDeleteRequest(BaseModel):
    confirm: bool = False  # Must be True to proceed


class TenantDeleteResponse(BaseModel):
    tenant_id: str
    status: str
    hard_delete_after: datetime
    message: str


@router.delete('/{tenant_id}', response_model=TenantDeleteResponse)
async def delete_tenant(
    tenant_id: str,
    body: TenantDeleteRequest,
    current_user: AuthUser = Depends(require_admin),
    tenant_repo: TenantRepository = Depends(_get_tenant_repo),
    mail_service: MailService = Depends(get_mail_service),
):
    if not body.confirm:
        raise HTTPException(
            status_code=400,
            detail='Bitte confirm=true setzen um die Loeschung zu bestaetigen.',
        )

    tenant = await tenant_repo.find_by_id(tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail='Tenant nicht gefunden.')
    if tenant.status != 'active':
        raise HTTPException(
            status_code=409,
            detail=f'Tenant hat Status {tenant.status!r} – Loeschung nur aus active moeglich.',
        )

    hard_delete_after = datetime.now(timezone.utc) + timedelta(days=_HARD_DELETE_DAYS)
    updated = await tenant_repo.soft_delete(
        tenant_id,
        requested_by=current_user.username,
        hard_delete_after=hard_delete_after,
    )
    if updated is None:
        raise HTTPException(status_code=409, detail='Tenant konnte nicht geloescht werden.')

    # Deactivate all users of this tenant
    try:
        user_repo = get_user_repository()
        await user_repo.deactivate_by_tenant(tenant_id)
    except Exception:
        pass

    # Audit event
    try:
        await get_audit_service().log_event({
            'event_id': str(uuid.uuid4()),
            'case_id': f'tenant:{tenant_id}',
            'source': 'admin',
            'agent_name': 'admin',
            'approval_status': 'NOT_REQUIRED',
            'action': 'TENANT_DELETION_REQUESTED',
            'result': tenant_id,
            'llm_output': {
                'tenant_id': tenant_id,
                'requested_by': current_user.username,
                'hard_delete_after': hard_delete_after.isoformat(),
            },
        })
    except Exception:
        pass

    # Notify tenant admin by mail
    if tenant.admin_email:
        try:
            await mail_service.send_mail(
                to=tenant.admin_email,
                subject='Ihr FRYA-Mandant wird geloescht',
                body_html=_deletion_mail_html(tenant, hard_delete_after),
                body_text=_deletion_mail_text(tenant, hard_delete_after),
                tenant_id=tenant_id,
            )
        except Exception:
            pass

    return TenantDeleteResponse(
        tenant_id=tenant_id,
        status='pending_deletion',
        hard_delete_after=hard_delete_after,
        message=(
            f'Tenant {tenant_id!r} auf pending_deletion gesetzt. '
            f'Hard-Delete nach 30 Tagen am {hard_delete_after.date().isoformat()}.'
        ),
    )


@router.post('/{tenant_id}/hard-delete')
async def hard_delete_tenant(
    tenant_id: str,
    current_user: AuthUser = Depends(require_admin),
    tenant_repo: TenantRepository = Depends(_get_tenant_repo),
):
    """Internal endpoint called by n8n after 30-day window. Also usable manually by admin."""
    tenant = await tenant_repo.find_by_id(tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail='Tenant nicht gefunden.')
    if tenant.status != 'pending_deletion':
        raise HTTPException(
            status_code=409,
            detail=f'Hard-Delete nur aus pending_deletion moeglich, aktuell: {tenant.status!r}.',
        )
    if tenant.hard_delete_after and tenant.hard_delete_after > datetime.now(timezone.utc):
        raise HTTPException(
            status_code=409,
            detail=f'Hard-Delete erst ab {tenant.hard_delete_after.date().isoformat()} moeglich.',
        )

    # GoBD-Check: block hard-delete if tenant has accounting data within retention period
    from app.gobd.retention import RETENTION_RULES, RetentionViolation, may_delete
    tenant_created = getattr(tenant, 'created_at', None)
    if tenant_created is not None:
        for table in RETENTION_RULES:
            if not may_delete(tenant_created, table):
                from app.gobd.retention import earliest_deletion_date
                earliest = earliest_deletion_date(tenant_created, table)
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f'GoBD-Sperre: Buchhaltungsdaten ({table}) unterliegen '
                        f'10-jähriger Aufbewahrungspflicht (§147 AO). '
                        f'Frühestmöglich: {earliest.date().isoformat() if earliest else "unbekannt"}. '
                        f'Nur User-Daten werden gelöscht; Buchungsdaten bleiben erhalten.'
                    ),
                )

    await tenant_repo.mark_hard_deleted(tenant_id)

    try:
        await get_audit_service().log_event({
            'event_id': str(uuid.uuid4()),
            'case_id': f'tenant:{tenant_id}',
            'source': 'admin',
            'agent_name': 'admin',
            'approval_status': 'NOT_REQUIRED',
            'action': 'TENANT_HARD_DELETED',
            'result': tenant_id,
            'llm_output': {
                'tenant_id': tenant_id,
                'deleted_by': current_user.username,
            },
        })
    except Exception:
        pass

    return {'tenant_id': tenant_id, 'status': 'deleted'}


@router.get('/{tenant_id}')
async def get_tenant(
    tenant_id: str,
    current_user: AuthUser = Depends(require_admin),
    tenant_repo: TenantRepository = Depends(_get_tenant_repo),
):
    tenant = await tenant_repo.find_by_id(tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail='Tenant nicht gefunden.')
    return tenant.model_dump(mode='json', exclude={'mail_config'})


@router.get('/')
async def list_tenants(
    current_user: AuthUser = Depends(require_admin),
    tenant_repo: TenantRepository = Depends(_get_tenant_repo),
):
    tenants = await tenant_repo.list_active()
    return [t.model_dump(mode='json', exclude={'mail_config'}) for t in tenants]


def _deletion_mail_html(tenant: TenantRecord, hard_delete_after: datetime) -> str:
    return (
        f'<html><body>'
        f'<h2>Ihr FRYA-Mandant wird geloescht</h2>'
        f'<p>Der Mandant <strong>{tenant.name or tenant.tenant_id}</strong> wurde zur Loeschung vorgemerkt.</p>'
        f'<p>Alle Daten werden am <strong>{hard_delete_after.date().isoformat()}</strong> '
        f'unwiderruflich geloescht.</p>'
        f'<p>Falls dies ein Irrtum ist, wenden Sie sich umgehend an support@myfrya.de.</p>'
        f'</body></html>'
    )


def _deletion_mail_text(tenant: TenantRecord, hard_delete_after: datetime) -> str:
    return (
        f'Ihr FRYA-Mandant wird geloescht\n\n'
        f'Mandant: {tenant.name or tenant.tenant_id}\n'
        f'Hard-Delete-Datum: {hard_delete_after.date().isoformat()}\n\n'
        f'Alle Daten werden an diesem Datum unwiderruflich geloescht.\n'
        f'Bei Irrtum: support@myfrya.de\n'
    )
