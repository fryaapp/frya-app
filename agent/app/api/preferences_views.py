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
    """Resolve tenant_id and user_id from the authenticated user."""
    from app.dependencies import get_user_repository, get_tenant_repository
    user_repo = get_user_repository()
    tenant_repo = get_tenant_repository()
    db_user = await user_repo.find_by_username(user.username)
    if db_user is None:
        raise HTTPException(status_code=404, detail='User not found in DB')
    tenant = await tenant_repo.get_default_tenant()
    if tenant is None:
        raise HTTPException(status_code=404, detail='No tenant configured')
    return str(tenant['id']), str(db_user.id)


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
