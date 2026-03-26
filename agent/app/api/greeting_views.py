"""API endpoint for personalized start-page greeting."""
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from app.auth.dependencies import require_authenticated
from app.auth.models import AuthUser

logger = logging.getLogger(__name__)
router = APIRouter(prefix='/api/v1', tags=['greeting'])


async def _resolve_tenant() -> uuid.UUID:
    from app.case_engine.tenant_resolver import resolve_tenant_id
    tid = await resolve_tenant_id()
    if not tid:
        raise HTTPException(status_code=503, detail='tenant_unavailable')
    return uuid.UUID(tid)


def _time_greeting(username: str) -> str:
    """Return a German greeting based on the current hour (UTC)."""
    hour = datetime.now(timezone.utc).hour
    if hour < 11:
        prefix = 'Guten Morgen'
    elif hour < 17:
        prefix = 'Hallo'
    else:
        prefix = 'Guten Abend'
    return f'{prefix}, {username}!'


@router.get('/greeting')
async def get_greeting(user: AuthUser = Depends(require_authenticated)) -> dict:
    """Personalised greeting with quick status summary for the start page."""
    tenant_id = await _resolve_tenant()

    # --- inbox count ---
    inbox_count = 0
    try:
        from app.dependencies import get_case_repository
        repo = get_case_repository()
        cases = await repo.list_active_cases_for_tenant(tenant_id)
        inbox_count = len([c for c in cases if c.status in ('DRAFT', 'OPEN')])
    except Exception as exc:
        logger.warning('Greeting: failed to fetch inbox count: %s', exc)

    # --- overdue open-items ---
    overdue_count = 0
    try:
        from app.dependencies import get_accounting_repository
        acc_repo = get_accounting_repository()
        open_items = await acc_repo.list_open_items(tenant_id)
        today = date.today()
        overdue_count = len([
            i for i in open_items
            if i.status in ('OPEN', 'PARTIALLY_PAID')
            and i.due_date is not None
            and i.due_date < today
        ])
    except Exception as exc:
        logger.warning('Greeting: failed to fetch overdue items: %s', exc)

    # --- build status summary ---
    parts: list[str] = []
    if inbox_count:
        parts.append(f'{inbox_count} offene Belege')
    if overdue_count:
        parts.append(f'{overdue_count} überfällige Posten')
    status_summary = ', '.join(parts) if parts else 'Alles im grünen Bereich.'

    urgent: str | None = None
    if overdue_count:
        urgent = f'{overdue_count} überfällige Posten erfordern Aufmerksamkeit.'

    suggestions = ['Status-Übersicht', 'Offene Belege', 'Frist-Check']

    return {
        'greeting': _time_greeting(user.username),
        'status_summary': status_summary,
        'urgent': urgent,
        'suggestions': suggestions,
    }
