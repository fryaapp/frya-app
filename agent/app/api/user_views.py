"""User management API: create users, send invitations."""
from __future__ import annotations

import logging
import uuid
from typing import Literal

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth.csrf import require_csrf
from app.auth.dependencies import require_admin
from app.auth.models import AuthUser
from app.auth.reset_service import PasswordResetService, INVITE_TTL
from app.auth.user_repository import UserRecord, UserRepository
from app.config import get_settings
from app.dependencies import (
    get_audit_service,
    get_mail_service,
    get_password_reset_service,
    get_user_repository,
)
from app.email.mail_service import MailService

router = APIRouter(prefix='/api/auth', tags=['users'])


class CreateUserRequest(BaseModel):
    username: str
    email: str
    role: Literal['operator', 'admin'] = 'operator'
    tenant_id: str | None = None


class CreateUserResponse(BaseModel):
    username: str
    email: str
    role: str
    invite_sent: bool


@router.post('/users', response_model=CreateUserResponse)
async def create_user(
    body: CreateUserRequest,
    current_user: AuthUser = Depends(require_admin),
    user_repo: UserRepository = Depends(get_user_repository),
    reset_service: PasswordResetService = Depends(get_password_reset_service),
    mail_service: MailService = Depends(get_mail_service),
):
    await require_csrf  # type hint only — enforced via CSRF middleware on POST
    existing = await user_repo.find_by_username(body.username)
    if existing:
        raise HTTPException(status_code=409, detail='Username bereits vergeben.')

    record = UserRecord(
        username=body.username,
        email=body.email,
        role=body.role,
        tenant_id=body.tenant_id,
        is_active=True,
        session_version=1,
    )
    await user_repo.create_user(record)

    token = await reset_service.issue_invite_token(body.username)
    settings = get_settings()
    invite_link = f'{settings.app_base_url}/auth/reset-password?token={token}&first=true'
    invite_sent = False

    try:
        from app.auth.router import _reset_mail_html, _reset_mail_text
        await mail_service.send_mail(
            to=body.email,
            subject=f'Ihr Zugang zu FRYA',
            body_html=_reset_mail_html(invite_link, first=True),
            body_text=_reset_mail_text(invite_link, first=True),
            tenant_id=body.tenant_id,
        )
        invite_sent = True
    except Exception as exc:
        logger.warning('create_user: invite mail failed for %s: %s', body.username, exc)

    try:
        await get_audit_service().log_event({
            'event_id': str(uuid.uuid4()),
            'case_id': f'auth:{body.username}',
            'source': 'auth',
            'agent_name': 'auth',
            'approval_status': 'NOT_REQUIRED',
            'action': 'USER_INVITED',
            'result': body.username,
            'llm_output': {
                'username': body.username,
                'email': body.email,
                'role': body.role,
                'created_by': current_user.username,
                'invite_sent': invite_sent,
            },
        })
    except Exception as exc:
        logger.warning('create_user: audit log failed: %s', exc)

    return CreateUserResponse(
        username=record.username,
        email=record.email,
        role=record.role,
        invite_sent=invite_sent,
    )


@router.get('/users')
async def list_users(
    current_user: AuthUser = Depends(require_admin),
    user_repo: UserRepository = Depends(get_user_repository),
):
    users = await user_repo.list_users()
    return [
        {'username': u.username, 'email': u.email, 'role': u.role,
         'is_active': u.is_active, 'tenant_id': u.tenant_id}
        for u in users
    ]
