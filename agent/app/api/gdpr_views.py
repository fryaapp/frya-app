"""DSGVO-Endpoints: Datenexport (Art. 20) und Löschantrag (Art. 17)."""
from __future__ import annotations

import io
import json
import logging
import uuid
import zipfile

logger = logging.getLogger(__name__)
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app.auth.dependencies import require_admin
from app.auth.models import AuthUser
from app.auth.tenant_repository import TenantRepository
from app.auth.user_repository import UserRepository
from app.audit.service import AuditService
from app.case_engine.repository import CaseRepository

router = APIRouter(prefix='/api/tenant', tags=['gdpr'])

_HARD_DELETE_DAYS = 30


def _get_tenant_repo() -> TenantRepository:
    from app.dependencies import get_tenant_repository
    return get_tenant_repository()


def _get_case_repo() -> CaseRepository:
    from app.dependencies import get_case_repository
    return get_case_repository()


def _get_audit_svc() -> AuditService:
    from app.dependencies import get_audit_service
    return get_audit_service()


def _get_user_repo() -> UserRepository:
    from app.dependencies import get_user_repository
    return get_user_repository()


# ---------------------------------------------------------------------------
# GET /api/tenant/{tenant_id}/export  — Art. 20 DSGVO Datenportabilität
# ---------------------------------------------------------------------------

@router.get('/{tenant_id}/export')
async def export_tenant_data(
    tenant_id: str,
    current_user: AuthUser = Depends(require_admin),
    tenant_repo: TenantRepository = Depends(_get_tenant_repo),
    case_repo: CaseRepository = Depends(_get_case_repo),
    audit_svc: AuditService = Depends(_get_audit_svc),
    user_repo: UserRepository = Depends(_get_user_repo),
):
    """Erstellt einen ZIP-Export aller Mandantendaten für Betroffenenrecht Portabilität (Art. 20 DSGVO)."""
    tenant = await tenant_repo.find_by_id(tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail='Tenant nicht gefunden.')

    try:
        tid_uuid = uuid.UUID(tenant_id)
    except ValueError:
        raise HTTPException(status_code=422, detail='tenant_id ist keine gültige UUID.')

    # Collect cases
    cases_data: list[dict] = []
    docs_data: list[dict] = []
    tenant_case_ids: list[str] = []
    offset = 0
    while True:
        batch = await case_repo.list_cases(tid_uuid, offset=offset, limit=200)
        if not batch:
            break
        for case in batch:
            cases_data.append(case.model_dump(mode='json'))
            tenant_case_ids.append(str(case.id))
            case_docs = await case_repo.get_case_documents(str(case.id))
            for doc in case_docs:
                docs_data.append(doc.model_dump(mode='json'))
        offset += len(batch)
        if len(batch) < 200:
            break

    # Collect audit log — tenant-scoped (only events belonging to this tenant)
    audit_records = await audit_svc.recent_for_tenant(
        tenant_id=tenant_id, case_ids=tenant_case_ids, limit=500
    )
    audit_data = [r.model_dump(mode='json') for r in audit_records]

    # Collect users
    users_raw = await user_repo.list_users(limit=500)
    users_data = [
        {k: v for k, v in u.model_dump(mode='json').items() if k != 'password_hash'}
        for u in users_raw
    ]

    # Tenant metadata
    tenant_data = tenant.model_dump(mode='json', exclude={'mail_config'})

    # Build ZIP in memory
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode='w', compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('tenant.json', json.dumps(tenant_data, indent=2, ensure_ascii=False, default=str))
        zf.writestr('cases.json', json.dumps(cases_data, indent=2, ensure_ascii=False, default=str))
        zf.writestr('documents_metadata.json', json.dumps(docs_data, indent=2, ensure_ascii=False, default=str))
        zf.writestr('audit_log.json', json.dumps(audit_data, indent=2, ensure_ascii=False, default=str))
        zf.writestr('users.json', json.dumps(users_data, indent=2, ensure_ascii=False, default=str))
        zf.writestr(
            'README.txt',
            (
                f'FRYA Datenexport\n'
                f'Tenant: {tenant_id}\n'
                f'Exportiert am: {datetime.now(timezone.utc).isoformat()}\n'
                f'Exportiert durch: {current_user.username}\n\n'
                f'Enthaltene Dateien:\n'
                f'  tenant.json            - Mandant-Stammdaten\n'
                f'  cases.json             - Alle Vorgaenge des Mandanten\n'
                f'  documents_metadata.json - Dokument-Metadaten (kein Dateiinhalt)\n'
                f'  audit_log.json         - Audit-Log (letzte 500 Eintraege, mandantenbezogen)\n'
                f'  users.json             - Nutzerdaten (ohne Passwort-Hash)\n'
            ),
        )

    buf.seek(0)
    filename = f'frya_export_{tenant_id}_{datetime.now(timezone.utc).strftime("%Y%m%d")}.zip'
    return StreamingResponse(
        buf,
        media_type='application/zip',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# POST /api/tenant/{tenant_id}/request-deletion  — Art. 17 DSGVO Löschantrag
# ---------------------------------------------------------------------------

@router.post('/{tenant_id}/request-deletion')
async def request_tenant_deletion(
    tenant_id: str,
    current_user: AuthUser = Depends(require_admin),
    tenant_repo: TenantRepository = Depends(_get_tenant_repo),
    user_repo: UserRepository = Depends(_get_user_repo),
    audit_svc: AuditService = Depends(_get_audit_svc),
):
    """Startet den Soft-Delete-Prozess für einen Mandanten (Art. 17 DSGVO).

    Setzt Status auf pending_deletion + hard_delete_after in 30 Tagen.
    Bestehende Löschlogik in tenant_views.py bleibt unverändert.
    """
    tenant = await tenant_repo.find_by_id(tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail='Tenant nicht gefunden.')
    if tenant.status != 'active':
        raise HTTPException(
            status_code=409,
            detail=f'Tenant hat Status {tenant.status!r} – Löschantrag nur aus active möglich.',
        )

    hard_delete_after = datetime.now(timezone.utc) + timedelta(days=_HARD_DELETE_DAYS)
    updated = await tenant_repo.soft_delete(
        tenant_id,
        requested_by=current_user.username,
        hard_delete_after=hard_delete_after,
    )
    if updated is None:
        raise HTTPException(status_code=409, detail='Löschantrag konnte nicht gesetzt werden.')

    # Deactivate users of this tenant
    try:
        await user_repo.deactivate_by_tenant(tenant_id)
    except Exception as exc:
        logger.warning('request_tenant_deletion: deactivate_by_tenant failed: %s', exc)

    # Audit event
    try:
        import uuid as _uuid
        await audit_svc.log_event({
            'event_id': str(_uuid.uuid4()),
            'case_id': f'tenant:{tenant_id}',
            'source': 'admin',
            'agent_name': 'admin',
            'approval_status': 'NOT_REQUIRED',
            'action': 'GDPR_DELETION_REQUESTED',
            'result': tenant_id,
            'llm_output': {
                'tenant_id': tenant_id,
                'requested_by': current_user.username,
                'hard_delete_after': hard_delete_after.isoformat(),
            },
        })
    except Exception as exc:
        logger.warning('request_tenant_deletion: audit log failed: %s', exc)

    return {
        'tenant_id': tenant_id,
        'status': 'pending_deletion',
        'hard_delete_after': hard_delete_after.isoformat(),
        'message': (
            f'Löschantrag für Tenant {tenant_id!r} gestellt. '
            f'Hard-Delete in 30 Tagen am {hard_delete_after.date().isoformat()}.'
        ),
    }
