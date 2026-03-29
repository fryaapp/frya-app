"""API endpoints for alpha feedback."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth.dependencies import require_authenticated, require_operator, require_admin
from app.auth.models import AuthUser
from app.config import get_settings
from app.feedback.repository import FeedbackRepository

logger = logging.getLogger(__name__)
router = APIRouter(prefix='/api/v1/feedback', tags=['feedback'])


def _get_repo() -> FeedbackRepository:
    return FeedbackRepository(get_settings().database_url)


async def _get_user_ids(user: AuthUser) -> tuple[str, str]:
    from app.dependencies import get_user_repository
    from app.case_engine.tenant_resolver import resolve_tenant_id
    user_repo = get_user_repository()
    db_user = await user_repo.find_by_username(user.username)
    if db_user is None:
        raise HTTPException(status_code=404, detail='User not found in DB')
    tenant_id = await resolve_tenant_id()
    if tenant_id is None:
        raise HTTPException(status_code=404, detail='No tenant configured')
    return tenant_id, db_user.username


class FeedbackCreate(BaseModel):
    """JSON body for POST /api/v1/feedback.

    Accepts both naming conventions:
    - ``text`` / ``current_page``  (used by the frontend smoke tests)
    - ``description`` / ``page``   (legacy form field names)
    """
    text: str | None = None
    description: str | None = None
    current_page: str | None = None
    page: str | None = None
    screenshot: str | None = None  # Base64 data URI
    system_info: dict | None = None

    @property
    def resolved_description(self) -> str:
        value = self.text or self.description
        if not value:
            raise ValueError('Either "text" or "description" must be provided')
        return value

    @property
    def resolved_page(self) -> str | None:
        return self.current_page or self.page


@router.post('', status_code=201)
async def create_feedback(
    body: FeedbackCreate,
    user: AuthUser = Depends(require_authenticated),
):
    tenant_id, user_id = await _get_user_ids(user)
    repo = _get_repo()

    screenshot_path: str | None = None

    description = body.resolved_description
    page = body.resolved_page

    feedback_id = await repo.create(
        tenant_id=tenant_id,
        user_id=user_id,
        description=description,
        page=page,
        screenshot_path=screenshot_path,
        screenshot_data=body.screenshot,
        system_info=body.system_info,
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


@router.get('/{feedback_id}')
async def get_feedback_detail(
    feedback_id: str,
    user: AuthUser = Depends(require_admin),
):
    repo = _get_repo()
    item = await repo.get_by_id(feedback_id)
    if not item:
        raise HTTPException(status_code=404, detail='Feedback not found')
    # Convert datetime for JSON
    if item.get('created_at'):
        item['created_at'] = item['created_at'].isoformat()
    return item


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


class ExportRequest(BaseModel):
    feedback_ids: list[str]


@router.post('/export')
async def export_feedback(
    body: ExportRequest,
    user: AuthUser = Depends(require_admin),
):
    """Export selected feedback items as Claude-ready markdown."""
    repo = _get_repo()
    items = []
    for fid in body.feedback_ids:
        item = await repo.get_by_id(fid)
        if item:
            items.append(item)

    if not items:
        raise HTTPException(status_code=404, detail='No feedback items found')

    # Build markdown report
    md_lines = [
        '# FRYA Bug-Report Export',
        f'Exportiert: {__import__("datetime").datetime.now().strftime("%d.%m.%Y %H:%M")}',
        f'Anzahl: {len(items)}',
        '',
        '---',
        '',
    ]

    screenshots = {}
    for i, item in enumerate(items, 1):
        created = item.get('created_at')
        if hasattr(created, 'strftime'):
            created = created.strftime('%d.%m.%Y %H:%M')
        else:
            created = str(created)[:16] if created else 'unbekannt'

        md_lines.append(f'## Bug #{i}: {item.get("description", "")[:80]}')
        md_lines.append('')
        md_lines.append(f'- **ID:** `{item["id"]}`')
        md_lines.append(f'- **User:** {item.get("user_id", "?")}')
        md_lines.append(f'- **Seite:** {item.get("page", "?")}')
        md_lines.append(f'- **Status:** {item.get("status", "?")}')
        md_lines.append(f'- **Datum:** {created}')
        md_lines.append('')
        md_lines.append('### Beschreibung')
        md_lines.append(item.get('description', '(leer)'))
        md_lines.append('')

        # System info
        si = item.get('system_info')
        if si and isinstance(si, dict):
            md_lines.append('### Systeminfos')
            for k, v in si.items():
                md_lines.append(f'- **{k}:** {v}')
            md_lines.append('')

        # Screenshot — embedded as Base64 data URI directly in Markdown
        if item.get('screenshot_data'):
            screenshots[f'screenshot_{i}'] = item['screenshot_data']
            md_lines.append(f'### Screenshot')
            md_lines.append(f'![Bug {i} Screenshot]({item["screenshot_data"]})')
            md_lines.append('')

        md_lines.append('---')
        md_lines.append('')

    # Mark as exported
    await repo.mark_exported(body.feedback_ids)

    return {
        'markdown': '\n'.join(md_lines),
        'screenshots': screenshots,
        'count': len(items),
        'exported_ids': body.feedback_ids,
    }
