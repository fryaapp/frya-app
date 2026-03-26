"""Phase 8: Auth endpoints — forgot-password, reset-password, change-password, activate."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from pydantic import BaseModel, Field

from app.auth.dependencies import require_authenticated
from app.auth.jwt_auth import create_access_token, create_refresh_token
from app.auth.models import AuthUser
from app.auth.service import hash_password_pbkdf2, verify_password
from app.config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix='/api/v1/auth', tags=['auth'])

RESET_MAX_AGE = 900        # 15 minutes
ACTIVATION_MAX_AGE = 172800  # 48 hours
MIN_PASSWORD_LENGTH = 8


def _get_serializer() -> URLSafeTimedSerializer:
    settings = get_settings()
    return URLSafeTimedSerializer(settings.jwt_secret)


def _get_user_repo():
    from app.dependencies import get_user_repository
    return get_user_repository()


# ---------------------------------------------------------------------------
# Pydantic request/response models
# ---------------------------------------------------------------------------

class ForgotPasswordRequest(BaseModel):
    email: str = Field(min_length=5, max_length=254)

class ForgotPasswordResponse(BaseModel):
    message: str

class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(min_length=MIN_PASSWORD_LENGTH)

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=MIN_PASSWORD_LENGTH)

class ActivateRequest(BaseModel):
    token: str


# ---------------------------------------------------------------------------
# POST /api/v1/auth/forgot-password
# ---------------------------------------------------------------------------

@router.post('/forgot-password', response_model=ForgotPasswordResponse)
async def forgot_password(body: ForgotPasswordRequest, request: Request):
    """
    Request a password-reset link.  Always returns the same message regardless
    of whether the email exists (no information leakage).
    """
    safe_response = ForgotPasswordResponse(
        message='Falls ein Konto existiert, wurde eine E-Mail gesendet.',
    )

    repo = _get_user_repo()
    user = await repo.find_by_email(body.email)
    if user is None:
        return safe_response

    serializer = _get_serializer()
    token = serializer.dumps({'user_id': user.username, 'action': 'reset'})

    settings = get_settings()
    reset_link = f'{settings.app_base_url}/reset-password?token={token}'

    # Log the link — actual email sending can be wired later
    logger.info(
        'Password reset requested for user=%s link=%s',
        user.username,
        reset_link,
    )

    return safe_response


# ---------------------------------------------------------------------------
# POST /api/v1/auth/reset-password
# ---------------------------------------------------------------------------

@router.post('/reset-password')
async def reset_password(body: ResetPasswordRequest):
    """Validate a reset token and set a new password."""
    serializer = _get_serializer()

    try:
        data = serializer.loads(body.token, max_age=RESET_MAX_AGE)
    except (SignatureExpired, BadSignature):
        raise HTTPException(status_code=400, detail='Link ungueltig oder abgelaufen.')

    if not isinstance(data, dict) or data.get('action') != 'reset':
        raise HTTPException(status_code=400, detail='Link ungueltig oder abgelaufen.')

    username: str | None = data.get('user_id')
    if not username:
        raise HTTPException(status_code=400, detail='Link ungueltig oder abgelaufen.')

    repo = _get_user_repo()
    user = await repo.find_by_username(username)
    if user is None:
        raise HTTPException(status_code=400, detail='Link ungueltig oder abgelaufen.')

    new_hash = hash_password_pbkdf2(body.new_password)
    await repo.update_password(username, new_hash)

    logger.info('Password reset completed for user=%s', username)
    return {'message': 'Passwort wurde erfolgreich zurueckgesetzt.'}


# ---------------------------------------------------------------------------
# POST /api/v1/auth/change-password  (requires Bearer JWT)
# ---------------------------------------------------------------------------

@router.post('/change-password')
async def change_password(
    body: ChangePasswordRequest,
    user: AuthUser = Depends(require_authenticated),
):
    """Change the current user's password (requires valid JWT / session)."""
    repo = _get_user_repo()
    db_user = await repo.find_by_username(user.username)
    if db_user is None or not db_user.password_hash:
        raise HTTPException(status_code=400, detail='Benutzer nicht gefunden.')

    if not verify_password(body.current_password, db_user.password_hash):
        raise HTTPException(status_code=400, detail='Aktuelles Passwort ist falsch.')

    new_hash = hash_password_pbkdf2(body.new_password)
    await repo.update_password(user.username, new_hash)

    # Issue fresh JWT pair so the caller stays authenticated
    access_token = create_access_token(
        user_id=user.username,
        tenant_id=getattr(user, 'tenant_id', None) or '',
        role=user.role,
    )
    refresh_token = create_refresh_token(user_id=user.username)

    logger.info('Password changed for user=%s', user.username)
    return {
        'message': 'Passwort wurde erfolgreich geaendert.',
        'access_token': access_token,
        'refresh_token': refresh_token,
    }


# ---------------------------------------------------------------------------
# POST /api/v1/auth/activate
# ---------------------------------------------------------------------------

@router.post('/activate')
async def activate_account(body: ActivateRequest):
    """Activate a user account via an activation token (48 h validity)."""
    serializer = _get_serializer()

    try:
        data = serializer.loads(body.token, max_age=ACTIVATION_MAX_AGE)
    except (SignatureExpired, BadSignature):
        raise HTTPException(status_code=400, detail='Link ungueltig oder abgelaufen.')

    if not isinstance(data, dict) or data.get('action') != 'activate':
        raise HTTPException(status_code=400, detail='Link ungueltig oder abgelaufen.')

    username: str | None = data.get('user_id')
    if not username:
        raise HTTPException(status_code=400, detail='Link ungueltig oder abgelaufen.')

    repo = _get_user_repo()
    user = await repo.find_by_username(username)
    if user is None:
        raise HTTPException(status_code=400, detail='Link ungueltig oder abgelaufen.')

    await repo.activate_user(username)

    logger.info('Account activated for user=%s', username)
    return {'message': 'Konto wurde erfolgreich aktiviert.'}
