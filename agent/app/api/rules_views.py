from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from app.approvals.service import ApprovalService
from app.audit.service import AuditService
from app.auth.csrf import require_csrf
from app.auth.dependencies import require_admin, require_operator
from app.auth.models import AuthUser
from app.dependencies import get_approval_service, get_audit_service, get_policy_access_layer, get_rule_change_audit_service, get_rule_loader
from app.rules.audit_service import RuleChangeAuditService
from app.rules.loader import RuleLoader
from app.rules.policy_access import PolicyAccessLayer

router = APIRouter(prefix='/inspect/rules', tags=['inspect'], dependencies=[Depends(require_operator)])


class RuleUpdateRequest(BaseModel):
    content: str
    changed_by: str | None = None
    reason: str
    approval_id: str | None = None


@router.get('', response_class=HTMLResponse)
async def list_rules(loader: RuleLoader = Depends(get_rule_loader)) -> str:
    status_items = loader.load_status()
    rows = ''.join(
        f"<tr><td>{x['file']}</td><td>{x.get('role','')}</td><td>{x.get('format','')}</td><td>{x.get('version') or ''}</td><td>{'OK' if x['loaded'] else 'ERROR'}</td><td>{x.get('error') or ''}</td></tr>"
        for x in status_items
    )
    return (
        '<h1>Regeldateien</h1>'
        '<p><a href="/inspect/rules/load-status">Load Status (HTML)</a> | '
        '<a href="/inspect/rules/load-status/json">Load Status (JSON)</a> | '
        '<a href="/inspect/rules/audit">Rule-Change-Audit</a></p>'
        '<table border="1" cellpadding="6"><tr><th>Datei</th><th>Rolle</th><th>Format</th><th>Version</th><th>Status</th><th>Fehler</th></tr>'
        f'{rows}</table>'
    )


@router.get('/load-status', response_class=HTMLResponse)
async def load_status_html(loader: RuleLoader = Depends(get_rule_loader)) -> str:
    status_items = loader.load_status()
    rows = ''.join(
        f"<tr><td>{x['file']}</td><td>{x.get('role','')}</td><td>{'geladen' if x['loaded'] else 'nicht geladen'}</td><td>{x.get('error') or ''}</td></tr>"
        for x in status_items
    )
    return '<h1>Rule Load Status</h1><table border="1" cellpadding="6"><tr><th>Datei</th><th>Rolle</th><th>Status</th><th>Fehler</th></tr>' + rows + '</table>'


@router.get('/load-status/json')
async def load_status_json(loader: RuleLoader = Depends(get_rule_loader)) -> dict:
    status_items = loader.load_status()
    loaded = [x for x in status_items if x['loaded']]
    failed = [x for x in status_items if not x['loaded']]
    return {'loaded': loaded, 'failed': failed}


@router.get('/audit', response_class=HTMLResponse)
async def rule_audit_view(audit_service: RuleChangeAuditService = Depends(get_rule_change_audit_service)) -> str:
    changes = await audit_service.recent(limit=200)
    rows = ''.join(
        f'<tr><td>{x.changed_at}</td><td>{x.file_name}</td><td>{x.old_version or ""}</td><td>{x.new_version or ""}</td><td>{x.changed_by}</td><td>{x.reason}</td></tr>'
        for x in changes
    )
    return (
        '<h1>Rule Change Audit</h1>'
        '<table border="1" cellpadding="6"><tr><th>Zeit</th><th>Datei</th><th>Alt</th><th>Neu</th><th>User</th><th>Begruendung</th></tr>'
        f'{rows}</table>'
    )


@router.get('/audit/json')
async def rule_audit_json(audit_service: RuleChangeAuditService = Depends(get_rule_change_audit_service)) -> list[dict]:
    changes = await audit_service.recent(limit=200)
    return [x.model_dump() for x in changes]


@router.get('/json/{file_name:path}')
async def get_rule_json(file_name: str, loader: RuleLoader = Depends(get_rule_loader)) -> dict:
    document = loader.load_rule_document(file_name)
    if not document['loaded']:
        raise HTTPException(status_code=404, detail='Regeldatei nicht gefunden oder nicht ladbar')
    return document


@router.get('/{file_name:path}', response_class=HTMLResponse)
async def get_rule(file_name: str, loader: RuleLoader = Depends(get_rule_loader)) -> str:
    document = loader.load_rule_document(file_name)
    if not document['loaded']:
        raise HTTPException(status_code=404, detail='Regeldatei nicht gefunden oder nicht ladbar')
    return (
        f"<h1>{document['file']}</h1>"
        f"<p>Format: {document['format']} | Version: {document['version'] or '-'} </p>"
        f"<pre>{document['content']}</pre>"
    )


@router.put('/{file_name:path}', dependencies=[Depends(require_csrf)])
async def update_rule(
    file_name: str,
    request: RuleUpdateRequest,
    loader: RuleLoader = Depends(get_rule_loader),
    policy_access: PolicyAccessLayer = Depends(get_policy_access_layer),
    approval_service: ApprovalService = Depends(get_approval_service),
    audit_service: AuditService = Depends(get_audit_service),
    rule_change_service: RuleChangeAuditService = Depends(get_rule_change_audit_service),
    current_user: AuthUser = Depends(require_admin),
) -> dict:
    gate = policy_access.evaluate_gate(
        intent='WORKFLOW_TRIGGER',
        action_name='rule_policy_edit',
        context={'side_effect': True, 'confidence': 1.0},
    )
    case_id = f'rule:{file_name}'
    approved_record = await approval_service.get(request.approval_id) if request.approval_id else None
    approved_for_write = bool(
        approved_record
        and approved_record.status == 'APPROVED'
        and approved_record.case_id == case_id
        and approved_record.action_type == gate.action_key
        and approved_record.scope_ref == file_name
    )
    if not approved_for_write:
        approval = await approval_service.request_approval(
            case_id=case_id,
            action_type=gate.action_key,
            requested_by=current_user.username,
            scope_ref=file_name,
            reason=request.reason,
            policy_refs=gate.consulted_policy_refs,
            required_mode=gate.decision_mode,
            approval_context={'file_name': file_name, 'reason': request.reason},
            source='rules_ui',
        )
        raise HTTPException(
            status_code=409,
            detail={
                'status': 'WAITING_APPROVAL',
                'approval_id': approval.approval_id,
                'approval_mode': gate.decision_mode,
                'action_key': gate.action_key,
                'reason': approval.reason,
                'open_item_id': approval.open_item_id,
                'next_step': 'Approval freigeben und den Rule-Write danach mit approval_id erneut ausfuehren.',
            },
        )

    old_doc = loader.load_rule_document(file_name)
    old_content = old_doc['content'] if old_doc['loaded'] and old_doc['content'] is not None else ''
    old_version = old_doc.get('version') if old_doc['loaded'] else None

    loader.save_rule_file(file_name, request.content)
    new_doc = loader.load_rule_document(file_name)
    if not new_doc['loaded']:
        raise HTTPException(status_code=400, detail=f"Datei konnte nicht geladen werden: {new_doc.get('error')}")

    change_record = await rule_change_service.record_change(
        file_name=file_name,
        old_content=old_content,
        new_content=new_doc['content'] or '',
        changed_by=current_user.username,
        reason=request.reason,
        old_version=old_version,
        new_version=new_doc.get('version'),
    )

    await audit_service.log_event(
        {
            'event_id': str(uuid.uuid4()),
            'case_id': f'rule:{file_name}',
            'source': 'rules_ui',
            'agent_name': 'frya-policy-layer',
            'approval_status': 'APPROVED',
            'action': 'RULE_FILE_UPDATED',
            'result': f'{file_name} updated by {current_user.username};approval_id={approved_record.approval_id}',
            'llm_input': {'old_version': old_version, 'new_version': new_doc.get('version'), 'approval_id': approved_record.approval_id},
            'llm_output': {'reason': request.reason, 'change_id': change_record.change_id, 'required_mode': gate.decision_mode},
            'policy_refs': gate.consulted_policy_refs,
        }
    )

    return {
        'status': 'ok',
        'file_name': file_name,
        'change_id': change_record.change_id,
        'old_version': change_record.old_version,
        'new_version': change_record.new_version,
        'loaded': True,
        'approval_id': approved_record.approval_id,
    }
