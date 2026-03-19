from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.auth.csrf import ensure_csrf_token, require_csrf
from app.auth.dependencies import require_operator
from app.auth.models import AuthUser
from app.dependencies import (
    get_audit_service,
    get_email_intake_repository,
    get_email_intake_service,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=['email-intake'])

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / 'ui' / 'templates'))


# ── Mailgun webhook (no auth — signature-validated) ─────────────────────────

@router.post('/webhooks/mailgun')
async def mailgun_webhook(request: Request):
    from app.dependencies import get_email_intake_service as _get_svc
    svc = _get_svc()

    form = await request.form()

    timestamp = form.get('timestamp', '')
    token = form.get('token', '')
    signature = form.get('signature', '')

    if not timestamp or not token or not signature:
        raise HTTPException(status_code=400, detail='Mailgun-Pflichtfelder fehlen.')

    sender = form.get('sender') or form.get('from') or ''
    recipient = form.get('recipient') or form.get('To') or None
    subject = form.get('subject') or None
    body_plain = form.get('body-plain') or None
    message_id = form.get('Message-Id') or form.get('message-id') or None

    attachments: list[dict] = []
    for i in range(1, 11):
        att_field = form.get(f'attachment-{i}')
        if att_field is None:
            break
        if hasattr(att_field, 'read'):
            content = await att_field.read()
            attachments.append({
                'file_name': getattr(att_field, 'filename', None),
                'mime_type': getattr(att_field, 'content_type', None),
                'content': content,
            })

    try:
        record = await svc.handle_webhook(
            timestamp=str(timestamp),
            token=str(token),
            signature=str(signature),
            sender=str(sender),
            recipient=str(recipient) if recipient else None,
            subject=str(subject) if subject else None,
            body_plain=str(body_plain) if body_plain else None,
            message_id=str(message_id) if message_id else None,
            attachments=attachments,
        )
    except ValueError as exc:
        msg = str(exc)
        if 'Signatur' in msg or 'signature' in msg.lower():
            raise HTTPException(status_code=403, detail=msg) from exc
        if 'Duplikat' in msg:
            return {'status': 'duplicate_ignored'}
        raise HTTPException(status_code=422, detail=msg) from exc

    return {
        'status': 'ok',
        'email_intake_id': record.email_intake_id,
        'intake_status': record.intake_status,
    }


# ── API endpoints ────────────────────────────────────────────────────────────

@router.get('/api/email-intake', dependencies=[Depends(require_operator)])
async def list_email_intake(
    limit: int = 50,
    offset: int = 0,
):
    repo = get_email_intake_repository()
    records = await repo.list_recent(limit=limit, offset=offset)
    return [r.model_dump(mode='json') for r in records]


@router.get('/api/email-intake/{email_intake_id}', dependencies=[Depends(require_operator)])
async def get_email_intake(email_intake_id: str):
    repo = get_email_intake_repository()
    record = await repo.get_by_id(email_intake_id)
    if record is None:
        raise HTTPException(status_code=404, detail='E-Mail-Eingang nicht gefunden.')
    attachments = await repo.get_attachments(email_intake_id)
    return {
        **record.model_dump(mode='json'),
        'attachments': [a.model_dump(mode='json') for a in attachments],
    }


@router.post(
    '/api/email-intake/{email_intake_id}/forward-to-analyst',
    dependencies=[Depends(require_operator), Depends(require_csrf)],
)
async def forward_to_analyst(
    email_intake_id: str,
    request: Request,
    auth_user: AuthUser = Depends(require_operator),
):
    svc = get_email_intake_service()
    try:
        contexts = await svc.forward_to_analyst_manually(
            email_intake_id, actor=auth_user.username
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return {
        'status': 'ok',
        'contexts_created': len(contexts),
        'case_ids': [c.source_case_id for c in contexts],
    }
