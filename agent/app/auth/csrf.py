from __future__ import annotations

import hmac

from fastapi import HTTPException, Request

from app.auth.service import issue_csrf_token
from app.config import get_settings


async def ensure_csrf_token(request: Request) -> str:
    token = request.session.get('csrf_token')
    if isinstance(token, str) and token:
        return token

    token = issue_csrf_token()
    request.session['csrf_token'] = token
    return token


def get_csrf_token(request: Request) -> str | None:
    token = request.session.get('csrf_token')
    if isinstance(token, str) and token:
        return token
    return None


async def require_csrf(request: Request) -> None:
    expected = get_csrf_token(request)
    if not expected:
        raise HTTPException(status_code=403, detail='forbidden')

    settings = get_settings()
    token = request.headers.get(settings.auth_csrf_header)

    if not token:
        content_type = request.headers.get('content-type', '')
        if 'application/x-www-form-urlencoded' in content_type or 'multipart/form-data' in content_type:
            form = await request.form()
            raw = form.get('csrf_token')
            token = str(raw) if raw is not None else None

    if not token:
        raise HTTPException(status_code=403, detail='forbidden')

    if not hmac.compare_digest(token, expected):
        raise HTTPException(status_code=403, detail='forbidden')
