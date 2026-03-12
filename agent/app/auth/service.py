from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from functools import lru_cache

from app.auth.models import AuthUser, AuthUserRecord, SessionUser
from app.config import get_settings

PBKDF2_PREFIX = 'pbkdf2_sha256'
DEFAULT_PBKDF2_ITERATIONS = 390000


class AuthService:
    def __init__(self, users: list[AuthUserRecord]) -> None:
        self._users = {u.username: u for u in users}

    @classmethod
    def from_env(cls) -> 'AuthService':
        settings = get_settings()
        users = parse_auth_users_json(settings.auth_users_json)
        return cls(users)

    def authenticate(self, username: str, password: str) -> AuthUser | None:
        record = self._users.get(username)
        if record is None:
            return None
        if not verify_password(password, record.password_hash):
            return None
        return AuthUser(username=record.username, role=record.role)

    def resolve_session_user(self, payload: dict | None) -> AuthUser | None:
        if not payload:
            return None
        try:
            session_user = SessionUser.model_validate(payload)
        except Exception:
            return None

        record = self._users.get(session_user.username)
        if record is None:
            return None

        if record.role != session_user.role:
            return None

        return AuthUser(username=record.username, role=record.role)


@lru_cache
def get_auth_service() -> AuthService:
    return AuthService.from_env()


def parse_auth_users_json(raw: str) -> list[AuthUserRecord]:
    if not raw.strip():
        return []

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError('FRYA_AUTH_USERS_JSON ist kein valides JSON') from exc

    if not isinstance(payload, list):
        raise ValueError('FRYA_AUTH_USERS_JSON muss ein JSON-Array sein')

    users: list[AuthUserRecord] = []
    seen: set[str] = set()

    for item in payload:
        user = AuthUserRecord.model_validate(item)
        if user.username in seen:
            raise ValueError(f'Doppelter Username in FRYA_AUTH_USERS_JSON: {user.username}')
        seen.add(user.username)
        users.append(user)

    return users


def build_session_payload(user: AuthUser) -> dict:
    return {
        'username': user.username,
        'role': user.role,
    }


def issue_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def issue_now_ts() -> int:
    return int(time.time())


def hash_password_pbkdf2(password: str, *, iterations: int = DEFAULT_PBKDF2_ITERATIONS, salt_bytes: int = 16) -> str:
    if not password:
        raise ValueError('Passwort darf nicht leer sein')

    salt = secrets.token_bytes(salt_bytes)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, iterations)
    salt_b64 = base64.b64encode(salt).decode('ascii')
    digest_b64 = base64.b64encode(digest).decode('ascii')
    return f'{PBKDF2_PREFIX}${iterations}${salt_b64}${digest_b64}'


def verify_password(password: str, stored_hash: str) -> bool:
    if not stored_hash:
        return False

    parts = stored_hash.split('$')
    if len(parts) != 4:
        return False

    prefix, raw_iterations, raw_salt, raw_digest = parts
    if prefix != PBKDF2_PREFIX:
        return False

    try:
        iterations = int(raw_iterations)
        salt = base64.b64decode(raw_salt.encode('ascii'))
        expected_digest = base64.b64decode(raw_digest.encode('ascii'))
    except Exception:
        return False

    candidate = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, iterations)
    return hmac.compare_digest(candidate, expected_digest)
