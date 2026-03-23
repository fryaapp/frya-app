"""JWT token creation and validation for mobile clients."""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

JWT_ALGORITHM = 'HS256'
JWT_ACCESS_EXPIRY = timedelta(hours=1)
JWT_REFRESH_EXPIRY = timedelta(days=30)


def _get_secret() -> str:
    from app.config import get_settings
    secret = get_settings().jwt_secret
    if not secret:
        secret = os.environ.get('FRYA_JWT_SECRET', '')
    if not secret:
        logger.warning('FRYA_JWT_SECRET is not set — JWT auth will not work')
    return secret


def create_access_token(user_id: str, tenant_id: str, role: str) -> str:
    import jwt
    payload = {
        'sub': user_id,
        'tid': tenant_id,
        'role': role,
        'exp': datetime.now(timezone.utc) + JWT_ACCESS_EXPIRY,
        'type': 'access',
    }
    return jwt.encode(payload, _get_secret(), algorithm=JWT_ALGORITHM)


def create_refresh_token(user_id: str) -> str:
    import jwt
    payload = {
        'sub': user_id,
        'exp': datetime.now(timezone.utc) + JWT_REFRESH_EXPIRY,
        'type': 'refresh',
    }
    return jwt.encode(payload, _get_secret(), algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    import jwt
    return jwt.decode(token, _get_secret(), algorithms=[JWT_ALGORITHM])
