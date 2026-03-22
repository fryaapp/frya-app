"""2FA / TOTP endpoints: setup, confirm, disable, and login verification."""
from __future__ import annotations

import io
import json
import base64
import secrets
from pathlib import Path

import pyotp
import qrcode  # type: ignore[import-untyped]
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.status import HTTP_303_SEE_OTHER

from app.auth.csrf import ensure_csrf_token, require_csrf
from app.auth.dependencies import require_authenticated
from app.auth.models import AuthUser
from app.auth.user_repository import UserRepository
from app.dependencies import get_user_repository

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / 'ui' / 'templates'))
router = APIRouter(prefix='/auth', tags=['auth-2fa'])


# ── 2FA Setup Page ────────────────────────────────────────────────────────────

@router.get('/2fa', response_class=HTMLResponse)
async def totp_settings_page(
    request: Request,
    auth_user: AuthUser = Depends(require_authenticated),
    user_repo: UserRepository = Depends(get_user_repository),
):
    csrf_token = await ensure_csrf_token(request)
    db_user = await user_repo.find_by_username(auth_user.username)
    totp_enabled = db_user.totp_enabled if db_user else False

    return TEMPLATES.TemplateResponse(
        request,
        'totp_settings.html',
        {
            'request': request,
            'csrf_token': csrf_token,
            'auth_user': auth_user,
            'title': '2FA-Einstellungen',
            'totp_enabled': totp_enabled,
            'qr_code': None,
            'secret': None,
            'backup_codes': None,
            'error': None,
            'success': None,
        },
    )


# ── 2FA Setup: Generate secret + QR code ─────────────────────────────────────

@router.post('/2fa/setup', response_class=HTMLResponse)
async def totp_setup(
    request: Request,
    auth_user: AuthUser = Depends(require_authenticated),
    _csrf: None = Depends(require_csrf),
):
    csrf_token = await ensure_csrf_token(request)
    secret = pyotp.random_base32()
    totp = pyotp.TOTP(secret)

    provisioning_uri = totp.provisioning_uri(
        name=auth_user.username,
        issuer_name='FRYA',
    )

    img = qrcode.make(provisioning_uri)
    buffer = io.BytesIO()
    img.save(buffer, format='PNG')
    qr_b64 = base64.b64encode(buffer.getvalue()).decode()

    backup_codes = [secrets.token_hex(4) for _ in range(10)]

    # Store pending setup in session (expires with session)
    request.session['totp_setup_secret'] = secret
    request.session['totp_setup_backup_codes'] = json.dumps(backup_codes)

    return TEMPLATES.TemplateResponse(
        request,
        'totp_settings.html',
        {
            'request': request,
            'csrf_token': csrf_token,
            'auth_user': auth_user,
            'title': '2FA-Einstellungen',
            'totp_enabled': False,
            'qr_code': f'data:image/png;base64,{qr_b64}',
            'secret': secret,
            'backup_codes': backup_codes,
            'error': None,
            'success': None,
        },
    )


# ── 2FA Confirm: Verify code and activate ────────────────────────────────────

@router.post('/2fa/confirm', response_class=HTMLResponse)
async def totp_confirm(
    request: Request,
    code: str = Form(...),
    auth_user: AuthUser = Depends(require_authenticated),
    user_repo: UserRepository = Depends(get_user_repository),
    _csrf: None = Depends(require_csrf),
):
    csrf_token = await ensure_csrf_token(request)
    secret = request.session.get('totp_setup_secret')
    backup_codes_raw = request.session.get('totp_setup_backup_codes')

    if not secret or not backup_codes_raw:
        return TEMPLATES.TemplateResponse(
            request,
            'totp_settings.html',
            {
                'request': request,
                'csrf_token': csrf_token,
                'auth_user': auth_user,
                'title': '2FA-Einstellungen',
                'totp_enabled': False,
                'qr_code': None,
                'secret': None,
                'backup_codes': None,
                'error': 'Kein aktives 2FA-Setup. Bitte erneut starten.',
                'success': None,
            },
        )

    totp = pyotp.TOTP(secret)
    if not totp.verify(code.strip(), valid_window=1):
        return TEMPLATES.TemplateResponse(
            request,
            'totp_settings.html',
            {
                'request': request,
                'csrf_token': csrf_token,
                'auth_user': auth_user,
                'title': '2FA-Einstellungen',
                'totp_enabled': False,
                'qr_code': None,
                'secret': secret,
                'backup_codes': json.loads(backup_codes_raw),
                'error': 'Ungueltiger Code. Bitte erneut versuchen.',
                'success': None,
            },
        )

    await user_repo.enable_totp(auth_user.username, secret, backup_codes_raw)

    # Clean up session
    request.session.pop('totp_setup_secret', None)
    request.session.pop('totp_setup_backup_codes', None)

    return TEMPLATES.TemplateResponse(
        request,
        'totp_settings.html',
        {
            'request': request,
            'csrf_token': csrf_token,
            'auth_user': auth_user,
            'title': '2FA-Einstellungen',
            'totp_enabled': True,
            'qr_code': None,
            'secret': None,
            'backup_codes': json.loads(backup_codes_raw),
            'error': None,
            'success': '2FA wurde erfolgreich aktiviert. Bewahre die Backup-Codes sicher auf!',
        },
    )


# ── 2FA Disable ───────────────────────────────────────────────────────────────

@router.post('/2fa/disable', response_class=HTMLResponse)
async def totp_disable(
    request: Request,
    code: str = Form(...),
    auth_user: AuthUser = Depends(require_authenticated),
    user_repo: UserRepository = Depends(get_user_repository),
    _csrf: None = Depends(require_csrf),
):
    csrf_token = await ensure_csrf_token(request)
    db_user = await user_repo.find_by_username(auth_user.username)

    if not db_user or not db_user.totp_enabled or not db_user.totp_secret:
        return RedirectResponse(url='/auth/2fa', status_code=HTTP_303_SEE_OTHER)

    totp = pyotp.TOTP(db_user.totp_secret)
    if not totp.verify(code.strip(), valid_window=1):
        return TEMPLATES.TemplateResponse(
            request,
            'totp_settings.html',
            {
                'request': request,
                'csrf_token': csrf_token,
                'auth_user': auth_user,
                'title': '2FA-Einstellungen',
                'totp_enabled': True,
                'qr_code': None,
                'secret': None,
                'backup_codes': None,
                'error': 'Ungueltiger Code. 2FA wurde NICHT deaktiviert.',
                'success': None,
            },
        )

    await user_repo.disable_totp(auth_user.username)

    return TEMPLATES.TemplateResponse(
        request,
        'totp_settings.html',
        {
            'request': request,
            'csrf_token': csrf_token,
            'auth_user': auth_user,
            'title': '2FA-Einstellungen',
            'totp_enabled': False,
            'qr_code': None,
            'secret': None,
            'backup_codes': None,
            'error': None,
            'success': '2FA wurde deaktiviert.',
        },
    )


# ── 2FA Verify (during login) ────────────────────────────────────────────────

@router.get('/verify-totp', response_class=HTMLResponse)
async def verify_totp_page(request: Request):
    if not request.session.get('totp_pending_username'):
        return RedirectResponse(url='/auth/login', status_code=HTTP_303_SEE_OTHER)

    return TEMPLATES.TemplateResponse(
        request,
        'verify_totp.html',
        {
            'request': request,
            'title': '2FA-Verifizierung',
            'error': None,
        },
    )


@router.post('/verify-totp', response_class=HTMLResponse)
async def verify_totp_submit(
    request: Request,
    code: str = Form(...),
    user_repo: UserRepository = Depends(get_user_repository),
):
    username = request.session.get('totp_pending_username')
    next_target = request.session.get('totp_pending_next', '/ui/dashboard')

    if not username:
        return RedirectResponse(url='/auth/login', status_code=HTTP_303_SEE_OTHER)

    db_user = await user_repo.find_by_username(username)
    if not db_user or not db_user.totp_secret:
        request.session.clear()
        return RedirectResponse(url='/auth/login', status_code=HTTP_303_SEE_OTHER)

    code_str = code.strip()
    totp = pyotp.TOTP(db_user.totp_secret)
    verified = totp.verify(code_str, valid_window=1)

    # Try backup code if TOTP failed
    if not verified:
        backup_codes = json.loads(db_user.totp_backup_codes or '[]')
        if code_str in backup_codes:
            backup_codes.remove(code_str)
            await user_repo.update_backup_codes(username, json.dumps(backup_codes))
            verified = True

    if not verified:
        return TEMPLATES.TemplateResponse(
            request,
            'verify_totp.html',
            {
                'request': request,
                'title': '2FA-Verifizierung',
                'error': 'Ungueltiger Code. Bitte erneut versuchen.',
            },
            status_code=401,
        )

    # TOTP verified — complete login
    pending_session = request.session.get('totp_pending_session', {})
    session_ver = request.session.get('totp_pending_session_ver', 1)

    request.session.clear()
    request.session['auth_user'] = pending_session
    from app.auth.service import issue_now_ts
    request.session['auth_issued_at'] = issue_now_ts()
    request.session['auth_last_seen'] = issue_now_ts()
    request.session['session_ver'] = session_ver
    from app.auth.csrf import ensure_csrf_token
    await ensure_csrf_token(request)

    return RedirectResponse(url=next_target, status_code=HTTP_303_SEE_OTHER)
