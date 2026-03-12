from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.status import HTTP_303_SEE_OTHER

from app.auth.csrf import ensure_csrf_token, require_csrf
from app.auth.dependencies import get_optional_user
from app.auth.service import AuthService, build_session_payload, get_auth_service, issue_now_ts

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / 'ui' / 'templates'))
router = APIRouter(prefix='/auth', tags=['auth'])


def _safe_next(next_target: str | None) -> str:
    if not next_target:
        return '/ui/dashboard'
    if not next_target.startswith('/'):
        return '/ui/dashboard'
    if next_target.startswith('//'):
        return '/ui/dashboard'
    return next_target


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
    user = auth_service.authenticate(username=username, password=password)
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

    request.session.clear()
    request.session['auth_user'] = build_session_payload(user)
    request.session['auth_issued_at'] = issue_now_ts()
    request.session['auth_last_seen'] = issue_now_ts()
    await ensure_csrf_token(request)

    return RedirectResponse(url=_safe_next(next), status_code=HTTP_303_SEE_OTHER)


@router.post('/logout')
async def logout(request: Request):
    if request.session.get('auth_user'):
        await require_csrf(request)
    request.session.clear()
    return RedirectResponse(url='/auth/login', status_code=HTTP_303_SEE_OTHER)

