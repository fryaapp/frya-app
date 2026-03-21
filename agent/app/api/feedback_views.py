"""API endpoints for alpha feedback."""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile, File
from pydantic import BaseModel

from app.auth.dependencies import require_operator, require_admin
from app.auth.models import AuthUser
from app.config import get_settings
from app.feedback.repository import FeedbackRepository

logger = logging.getLogger(__name__)
router = APIRouter(prefix='/api/v1/feedback', tags=['feedback'])

_SCREENSHOT_DIR = Path('/app/data/feedback/screenshots')


def _get_repo() -> FeedbackRepository:
    return FeedbackRepository(get_settings().database_url)


async def _get_user_ids(user: AuthUser) -> tuple[str, str]:
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


@router.post('', status_code=201)
async def create_feedback(
    description: str = Form(...),
    page: str | None = Form(default=None),
    screenshot: UploadFile | None = File(default=None),
    user: AuthUser = Depends(require_operator),
):
    tenant_id, user_id = await _get_user_ids(user)
    repo = _get_repo()

    screenshot_path: str | None = None
    if screenshot and screenshot.filename:
        _SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
        import uuid
        fname = f'{uuid.uuid4().hex}_{screenshot.filename}'
        dest = _SCREENSHOT_DIR / fname
        content = await screenshot.read()
        dest.write_bytes(content)
        screenshot_path = str(dest)

    feedback_id = await repo.create(
        tenant_id=tenant_id,
        user_id=user_id,
        description=description,
        page=page,
        screenshot_path=screenshot_path,
    )

    # Telegram notification to Maze
    try:
        from app.dependencies import get_telegram_connector
        from app.connectors.contracts import NotificationMessage
        settings = get_settings()
        chat_id = settings.telegram_default_chat_id
        if chat_id:
            text = (
                f'Neues Alpha-Feedback:\n'
                f'Seite: {page or "(unbekannt)"}\n'
                f'User: {user.username}\n'
                f'---\n'
                f'"{description[:200]}"'
            )
            connector = get_telegram_connector()
            await connector.send(NotificationMessage(target=chat_id, text=text))
    except Exception as exc:
        logger.warning('Feedback Telegram notification failed: %s', exc)

    return {'feedback_id': feedback_id}


@router.get('')
async def list_feedback(user: AuthUser = Depends(require_admin)):
    repo = _get_repo()
    items = await repo.list_all()
    return items


class StatusUpdate(BaseModel):
    status: str


@router.patch('/{feedback_id}')
async def update_feedback_status(
    feedback_id: str,
    body: StatusUpdate,
    user: AuthUser = Depends(require_admin),
):
    if body.status not in ('NEW', 'IN_PROGRESS', 'RESOLVED'):
        raise HTTPException(status_code=400, detail='Invalid status')
    repo = _get_repo()
    await repo.update_status(feedback_id, body.status)
    return {'feedback_id': feedback_id, 'status': body.status}
