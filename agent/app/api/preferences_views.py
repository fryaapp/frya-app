"""API endpoints for user preferences."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth.dependencies import require_operator
from app.auth.models import AuthUser
from app.config import get_settings
from app.preferences.repository import UserPreferencesRepository

router = APIRouter(prefix='/api/v1/preferences', tags=['preferences'])

_VALID_KEYS = {
    'formal_address', 'formality_level', 'emoji_enabled',
    'notification_channel', 'theme',
}


def _get_repo() -> UserPreferencesRepository:
    return UserPreferencesRepository(get_settings().database_url)


async def _get_user_ids(user: AuthUser) -> tuple[str, str]:
    """Resolve tenant_id and user_id from the authenticated user.

    P-17: Prefer JWT tenant_id over resolve_tenant_id() to prevent
    cross-tenant data leakage.
    """
    from app.dependencies import get_user_repository
    user_repo = get_user_repository()
    db_user = await user_repo.find_by_username(user.username)
    if db_user is None:
        raise HTTPException(status_code=404, detail='User not found in DB')
    # P-17: Use JWT tenant first, fallback only for non-authenticated contexts
    if user and getattr(user, 'tenant_id', None):
        tenant_id = str(user.tenant_id)
    else:
        import logging as _logging
        _logging.getLogger(__name__).warning('P-17: preferences_views using resolve_tenant_id() fallback — no tenant_id in JWT')
        from app.case_engine.tenant_resolver import resolve_tenant_id
        tenant_id = await resolve_tenant_id()
    if tenant_id is None:
        raise HTTPException(status_code=404, detail='No tenant configured')
    return tenant_id, db_user.username


class PrefValue(BaseModel):
    value: str


@router.get('')
async def get_preferences(user: AuthUser = Depends(require_operator)):
    tenant_id, user_id = await _get_user_ids(user)
    repo = _get_repo()
    prefs = await repo.get_all_preferences(tenant_id, user_id)
    return prefs


@router.put('/{key}')
async def set_preference(
    key: str,
    body: PrefValue,
    user: AuthUser = Depends(require_operator),
):
    if key not in _VALID_KEYS:
        raise HTTPException(status_code=400, detail=f'Unknown preference key: {key}')
    tenant_id, user_id = await _get_user_ids(user)
    repo = _get_repo()
    await repo.set_preference(tenant_id, user_id, key, body.value)
    return {'key': key, 'value': body.value}
