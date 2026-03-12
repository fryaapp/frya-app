from __future__ import annotations

import time
from typing import Any

from fastapi import Depends, HTTPException, Request

from app.auth.models import AuthUser
from app.auth.service import AuthService, get_auth_service
from app.config import get_settings

ROLE_LEVEL = {
    'operator': 10,
    'admin': 20,
}


def _is_ui_request(request: Request) -> bool:
    return request.url.path.startswith('/ui')


def _raise_unauthorized() -> None:
    raise HTTPException(status_code=401, detail='not_authenticated')


def _raise_forbidden() -> None:
    raise HTTPException(status_code=403, detail='forbidden')


def _get_session_user_payload(request: Request) -> dict[str, Any] | None:
    if 'auth_user' not in request.session:
        return None
    payload = request.session.get('auth_user')
    return payload if isinstance(payload, dict) else None


def _enforce_idle_timeout(request: Request) -> None:
    settings = get_settings()
    idle_timeout = settings.auth_session_idle_timeout_seconds
    if idle_timeout <= 0:
        return

    now = int(time.time())
    last_seen = request.session.get('auth_last_seen')
    if isinstance(last_seen, int) and now - last_seen > idle_timeout:
        request.session.clear()
        _raise_unauthorized()

    request.session['auth_last_seen'] = now


async def get_optional_user(
    request: Request,
    auth_service: AuthService = Depends(get_auth_service),
) -> AuthUser | None:
    payload = _get_session_user_payload(request)
    if payload is None:
        return None

    user = auth_service.resolve_session_user(payload)
    if user is None:
        request.session.clear()
        return None

    _enforce_idle_timeout(request)
    request.state.auth_user = user
    return user


async def require_authenticated(
    request: Request,
    auth_service: AuthService = Depends(get_auth_service),
) -> AuthUser:
    payload = _get_session_user_payload(request)
    if payload is None:
        _raise_unauthorized()

    user = auth_service.resolve_session_user(payload)
    if user is None:
        request.session.clear()
        _raise_unauthorized()

    _enforce_idle_timeout(request)
    request.state.auth_user = user
    return user


def _has_required_role(user: AuthUser, required: str) -> bool:
    return ROLE_LEVEL.get(user.role, 0) >= ROLE_LEVEL.get(required, 999)


async def require_operator(user: AuthUser = Depends(require_authenticated)) -> AuthUser:
    if not _has_required_role(user, 'operator'):
        _raise_forbidden()
    return user


async def require_admin(user: AuthUser = Depends(require_authenticated)) -> AuthUser:
    if not _has_required_role(user, 'admin'):
        _raise_forbidden()
    return user
