from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)
from urllib.parse import unquote

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.status import HTTP_303_SEE_OTHER

from app.auth.csrf import ensure_csrf_token, require_csrf
from app.auth.dependencies import get_optional_user
from app.auth.reset_service import PasswordResetService
from app.auth.service import (
    AuthService,
    authenticate_db_then_env,
    build_session_payload,
    get_auth_service,
    hash_password_pbkdf2,
    issue_now_ts,
)
from app.auth.user_repository import UserRepository
from app.config import get_settings
from app.dependencies import (
    get_mail_service,
    get_password_reset_service,
    get_user_repository,
)
from app.email.mail_service import MailService

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / 'ui' / 'templates'))
router = APIRouter(prefix='/auth', tags=['auth'])

_MIN_PASSWORD_LEN = 12


def _safe_next(next_target: str | None) -> str:
    """Return a safe redirect target — always a relative path within this app.

    Decodes percent-encoded input first to block bypasses like /%2F%2Fexample.com.
    """
    if not next_target:
        return '/ui/dashboard'
    # Decode once to catch encoded-slash bypasses (e.g. /%2F%2F)
    decoded = unquote(next_target)
    if not decoded.startswith('/'):
        return '/ui/dashboard'
    if decoded.startswith('//'):
        return '/ui/dashboard'
    # Reject anything that looks like a scheme (e.g. after double-decode or unicode tricks)
    if ':' in decoded.split('/')[1] if len(decoded.split('/')) > 1 else '':
        return '/ui/dashboard'
    return next_target


# ── Login / Logout ────────────────────────────────────────────────────────────

@router.get('/login', response_class=HTMLResponse)
async def login_page(
    request: Request,
    next: str | None = None,
    current_user=Depends(get_optional_user),
):
    if current_user is not None:
        return RedirectResponse(url='/ui/dashboard', status_code=HTTP_303_SEE_OTHER)

    return TEMPLATES.TemplateResponse(
        request,
        'login.html',
        {
            'request': request,
            'title': 'Login',
            'error': None,
            'next': _safe_next(next),
        },
    )


@router.post('/login', response_class=HTMLResponse)
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    next: str | None = Form(default=None),
    auth_service: AuthService = Depends(get_auth_service),
):
    user = await authenticate_db_then_env(username, password, auth_service)
    if user is None:
        return TEMPLATES.TemplateResponse(
            request,
            'login.html',
            {
                'request': request,
                'title': 'Login',
                'error': 'Login fehlgeschlagen.',
                'next': _safe_next(next),
            },
            status_code=401,
        )

    # Fetch session_version for this user (to include in cookie for future invalidation)
    try:
        repo = get_user_repository()
        session_ver = await repo.get_session_version(user.username)
    except Exception as exc:
        logger.warning('Failed to get session version for %s: %s', user.username, exc)
        session_ver = 1

    # Check if 2FA is enabled for this user
    try:
        db_user = await repo.find_by_username(user.username)
        if db_user and db_user.totp_enabled and db_user.totp_secret:
            # Store pending auth state and redirect to TOTP verification
            request.session.clear()
            request.session['totp_pending_username'] = user.username
            request.session['totp_pending_session'] = build_session_payload(user)
            request.session['totp_pending_session_ver'] = session_ver
            request.session['totp_pending_next'] = _safe_next(next)
            return RedirectResponse(url='/auth/verify-totp', status_code=HTTP_303_SEE_OTHER)
    except Exception as exc:
        logger.warning('2FA check failed for %s: %s', user.username, exc)

    request.session.clear()
    request.session['auth_user'] = build_session_payload(user)
    request.session['auth_issued_at'] = issue_now_ts()
    request.session['auth_last_seen'] = issue_now_ts()
    request.session['session_ver'] = session_ver
    await ensure_csrf_token(request)

    return RedirectResponse(url=_safe_next(next), status_code=HTTP_303_SEE_OTHER)


@router.post('/logout')
async def logout(request: Request):
    if request.session.get('auth_user'):
        await require_csrf(request)
    request.session.clear()
    return RedirectResponse(url='/auth/login', status_code=HTTP_303_SEE_OTHER)


# ── Forgot password ───────────────────────────────────────────────────────────

@router.get('/forgot-password', response_class=HTMLResponse)
async def forgot_password_page(request: Request):
    return TEMPLATES.TemplateResponse(
        request,
        'forgot_password.html',
        {'request': request, 'title': 'Passwort vergessen', 'done': False, 'error': None},
    )


@router.post('/forgot-password', response_class=HTMLResponse)
async def forgot_password_submit(
    request: Request,
    email: str = Form(...),
    user_repo: UserRepository = Depends(get_user_repository),
    reset_service: PasswordResetService = Depends(get_password_reset_service),
    mail_service: MailService = Depends(get_mail_service),
):
    ip = request.client.host if request.client else '0.0.0.0'
    allowed = await reset_service.check_rate_limit(ip)
    if not allowed:
        # Still return 200 to avoid information leakage
        return TEMPLATES.TemplateResponse(
            request,
            'forgot_password.html',
            {'request': request, 'title': 'Passwort vergessen', 'done': True, 'error': None},
        )

    user = await user_repo.find_by_email(email.strip())
    if user is not None:
        token = await reset_service.issue_reset_token(user.username)
        settings = get_settings()
        reset_link = f'{settings.app_base_url}/auth/reset-password?token={token}'
        try:
            await mail_service.send_mail(
                to=email.strip(),
                subject='Ihr FRYA Passwort-Reset',
                body_html=_reset_mail_html(reset_link, first=False),
                body_text=_reset_mail_text(reset_link, first=False),
                tenant_id=user.tenant_id,
            )
        except Exception as exc:
            logger.warning('Failed to send password reset mail: %s', exc)  # Never expose mail errors to the user
        try:
            from app.dependencies import get_audit_service
            import uuid
            await get_audit_service().log_event({
                'event_id': str(uuid.uuid4()),
                'case_id': f'auth:{user.username}',
                'source': 'auth',
                'agent_name': 'auth',
                'approval_status': 'NOT_REQUIRED',
                'action': 'PASSWORD_RESET_REQUESTED',
                'result': user.username,
                'llm_output': {'username': user.username, 'ip': ip},
            })
        except Exception as exc:
            logger.warning('Audit logging failed for password reset request: %s', exc)

    # Always return 200 — never reveal whether e-mail exists
    return TEMPLATES.TemplateResponse(
        request,
        'forgot_password.html',
        {'request': request, 'title': 'Passwort vergessen', 'done': True, 'error': None},
    )


# ── Reset password ────────────────────────────────────────────────────────────

@router.get('/reset-password', response_class=HTMLResponse)
async def reset_password_page(
    request: Request,
    token: str,
    first: str | None = None,
    reset_service: PasswordResetService = Depends(get_password_reset_service),
):
    username = await reset_service.validate_token(token)
    if username is None:
        return TEMPLATES.TemplateResponse(
            request,
            'reset_password.html',
            {
                'request': request,
                'title': 'Passwort zuruecksetzen',
                'token': token,
                'username': None,
                'is_first': False,
                'error': 'Dieser Link ist ungueltig oder abgelaufen.',
                'success': False,
            },
            status_code=400,
        )
    return TEMPLATES.TemplateResponse(
        request,
        'reset_password.html',
        {
            'request': request,
            'title': 'Passwort zuruecksetzen',
            'token': token,
            'username': username,
            'is_first': first == 'true',
            'error': None,
            'success': False,
        },
    )


@router.post('/reset-password', response_class=HTMLResponse)
async def reset_password_submit(
    request: Request,
    token: str = Form(...),
    password: str = Form(...),
    password_confirm: str = Form(...),
    reset_service: PasswordResetService = Depends(get_password_reset_service),
    user_repo: UserRepository = Depends(get_user_repository),
):
    def _error(msg: str, is_first: bool = False):
        return TEMPLATES.TemplateResponse(
            request,
            'reset_password.html',
            {
                'request': request,
                'title': 'Passwort zuruecksetzen',
                'token': token,
                'username': None,
                'is_first': is_first,
                'error': msg,
                'success': False,
            },
            status_code=400,
        )

    # Validate token first (before consuming)
    username = await reset_service.validate_token(token)
    if username is None:
        attempts = await reset_service.record_failed_attempt(token)
        return _error('Dieser Link ist ungueltig oder abgelaufen.')

    if len(password) < _MIN_PASSWORD_LEN:
        return _error(f'Das Passwort muss mindestens {_MIN_PASSWORD_LEN} Zeichen lang sein.')

    if password != password_confirm:
        return _error('Die Passwoerter stimmen nicht ueberein.')

    # Consume token (single-use)
    confirmed_username = await reset_service.consume_token(token)
    if confirmed_username is None:
        return _error('Dieser Link ist ungueltig oder abgelaufen.')

    new_hash = hash_password_pbkdf2(password)
    await user_repo.update_password(confirmed_username, new_hash)

    try:
        from app.dependencies import get_audit_service
        import uuid
        await get_audit_service().log_event({
            'event_id': str(uuid.uuid4()),
            'case_id': f'auth:{confirmed_username}',
            'source': 'auth',
            'agent_name': 'auth',
            'approval_status': 'NOT_REQUIRED',
            'action': 'PASSWORD_RESET_COMPLETED',
            'result': confirmed_username,
            'llm_output': {'username': confirmed_username},
        })
    except Exception as exc:
        logger.warning('Audit logging failed for password reset completion: %s', exc)

    return RedirectResponse(
        url='/auth/login?reset=1',
        status_code=HTTP_303_SEE_OTHER,
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _reset_mail_html(link: str, *, first: bool) -> str:
    if first:
        subject_line = 'Willkommen bei FRYA'
        body_text = (
            'du bist eingeladen, FRYA als Alpha-Tester auszuprobieren!<br><br>'
            'FRYA ist deine KI-gestuetzte Buchhaltung:<br>'
            'Dokument hochladen → KI versteht → bucht → archiviert → meldet.'
        )
        button_text = 'Account einrichten'
        validity = 'Dieser Link ist 7 Tage gueltig.'
    else:
        subject_line = 'Passwort zuruecksetzen'
        body_text = 'Du hast einen Passwort-Reset angefordert. Klicke auf den Button um ein neues Passwort zu setzen.'
        button_text = 'Neues Passwort setzen'
        validity = 'Dieser Link ist 30 Minuten gueltig.'

    return f'''<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width"></head>
<body style="margin:0;padding:0;background:#F5F0ED;font-family:'Plus Jakarta Sans',Helvetica,Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#F5F0ED;padding:40px 20px;">
<tr><td align="center">
<table width="560" cellpadding="0" cellspacing="0" style="max-width:560px;width:100%;">
  <!-- Orange Header -->
  <tr><td style="background:#E87830;padding:20px;text-align:center;border-radius:16px 16px 0 0;">
    <span style="color:#FFFFFF;font-size:28px;font-weight:700;letter-spacing:2px;">FRYA</span>
  </td></tr>
  <!-- Content -->
  <tr><td style="background:#FFFFFF;padding:40px 32px;">
    <h1 style="text-align:center;font-size:24px;font-weight:700;color:#201A17;margin:0 0 8px;">{subject_line}</h1>
    <p style="text-align:center;font-size:14px;color:#52443D;margin:0 0 28px;">FRYA — Deine KI-Buchhaltung</p>
    <p style="font-size:16px;color:#201A17;line-height:1.6;margin:0 0 32px;">{body_text}</p>
    <!-- CTA Button -->
    <div style="text-align:center;margin-bottom:24px;">
      <a href="{link}" style="display:inline-block;padding:16px 48px;background:#E87830;color:#FFFFFF;text-decoration:none;border-radius:24px;font-size:16px;font-weight:600;">{button_text}</a>
    </div>
    <p style="text-align:center;font-size:12px;color:#84746B;margin:0 0 16px;">{validity}</p>
    <p style="text-align:center;font-size:12px;color:#84746B;margin:0;">Falls der Button nicht funktioniert:<br><a href="{link}" style="color:#E87830;word-break:break-all;">{link}</a></p>
  </td></tr>
  <!-- Footer -->
  <tr><td style="background:#EEDFD8;padding:24px 32px;text-align:center;border-radius:0 0 16px 16px;">
    <p style="color:#52443D;font-size:14px;margin:0 0 4px;">Viele Gruesse</p>
    <p style="color:#52443D;font-size:14px;font-weight:600;margin:0 0 16px;">Maze — Mycelium Enterprises UG</p>
    <p style="color:#84746B;font-size:11px;margin:0;">Du erhaeltst diese Mail weil du als Alpha-Tester eingeladen wurdest.<br>Fragen? <a href="mailto:kontakt@myfrya.de" style="color:#E87830;">kontakt@myfrya.de</a></p>
  </td></tr>
</table>
</td></tr></table>
</body></html>'''


def _reset_mail_text(link: str, *, first: bool) -> str:
    if first:
        return (
            'Willkommen bei FRYA\n\n'
            'Du bist eingeladen, FRYA als Alpha-Tester auszuprobieren!\n\n'
            'FRYA ist deine KI-gestuetzte Buchhaltung:\n'
            'Dokument hochladen → KI versteht → bucht → archiviert → meldet.\n\n'
            f'Account einrichten: {link}\n\n'
            'Dieser Link ist 7 Tage gueltig.\n\n'
            'Viele Gruesse\n'
            'Maze — Mycelium Enterprises UG\n'
        )
    return (
        'Passwort zuruecksetzen\n\n'
        'Du hast einen Passwort-Reset angefordert.\n\n'
        f'Neues Passwort setzen: {link}\n\n'
        'Dieser Link ist 30 Minuten gueltig.\n\n'
        'Falls du keinen Reset angefordert hast, ignoriere diese Mail.\n'
    )
