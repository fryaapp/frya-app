"""API endpoint for personalized start-page greeting."""
from __future__ import annotations

import logging
import random
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException

from app.auth.dependencies import require_authenticated
from app.auth.models import AuthUser

logger = logging.getLogger(__name__)
router = APIRouter(prefix='/api/v1', tags=['greeting'])

# ---------------------------------------------------------------------------
# Greeting variation pools
# ---------------------------------------------------------------------------

_GREETINGS_MORNING: list[str] = [
    'Moin {name}!',
    'Guten Morgen {name}!',
    'Früh dran heute!',
    'Morgen {name}! Kaffee schon fertig?',
]

_GREETINGS_DAY: list[str] = [
    'Hey {name}!',
    'Da bist du ja!',
    'Was gibt\'s {name}?',
    'Schön dass du reinschaust!',
    'Na {name}, was steht an?',
]

_GREETINGS_EVENING: list[str] = [
    'Noch fleißig {name}?',
    'Feierabend-Check?',
    'Na, kurz reinschauen?',
    'Abend {name}!',
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _resolve_tenant(user=None) -> uuid.UUID:
    if user and getattr(user, 'tenant_id', None):
        return uuid.UUID(str(user.tenant_id))
    from app.case_engine.tenant_resolver import resolve_tenant_id
    tid = await resolve_tenant_id()
    if not tid:
        raise HTTPException(status_code=503, detail='tenant_unavailable')
    return uuid.UUID(tid)


def _time_greeting(username: str) -> str:
    """Return a varied German greeting based on the current hour (UTC)."""
    hour = datetime.now(timezone.utc).hour
    if hour < 10:
        pool = _GREETINGS_MORNING
    elif hour < 17:
        pool = _GREETINGS_DAY
    else:
        pool = _GREETINGS_EVENING
    return random.choice(pool).format(name=username)


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


async def _get_user_preferences(username: str, tenant_id: uuid.UUID) -> dict[str, str]:
    """Read all user preferences from frya_user_preferences."""
    try:
        from app.dependencies import get_settings
        settings = get_settings()
        db_url = settings.database_url
        if db_url.startswith('memory://'):
            return {}
        import asyncpg
        conn = await asyncpg.connect(db_url)
        try:
            rows = await conn.fetch(
                "SELECT key, value FROM frya_user_preferences WHERE user_id = $1 AND tenant_id = $2",
                username, str(tenant_id),
            )
            return {r['key']: r['value'] for r in rows}
        finally:
            await conn.close()
    except Exception as exc:
        logger.warning('Failed to read user preferences: %s', exc)
    return {}


async def _get_display_name(username: str, tenant_id: uuid.UUID) -> str:
    """Read display_name from frya_user_preferences, fallback to username."""
    prefs = await _get_user_preferences(username, tenant_id)
    return prefs.get('display_name') or username


@router.get('/greeting')
async def get_greeting(user: AuthUser = Depends(require_authenticated)) -> dict:
    """Personalised greeting with quick status summary for the start page."""
    tenant_id = await _resolve_tenant(user)
    today = date.today()
    deadline_horizon = today + timedelta(days=7)

    # --- inbox count (DRAFT / OPEN cases) ---
    inbox_count = 0
    try:
        from app.dependencies import get_case_repository
        repo = get_case_repository()
        cases = await repo.list_active_cases_for_tenant(tenant_id)
        inbox_count = len([c for c in cases if c.status in ('DRAFT', 'OPEN')])
    except Exception as exc:
        logger.warning('Greeting: failed to fetch inbox count: %s', exc)

    # --- overdue open items + upcoming deadlines ---
    overdue_items: list = []
    upcoming_deadline_count = 0
    contacts_by_id: dict[str, str] = {}
    try:
        from app.dependencies import get_accounting_repository
        acc_repo = get_accounting_repository()
        open_items = await acc_repo.list_open_items(tenant_id)

        for item in open_items:
            if item.status not in ('OPEN', 'PARTIALLY_PAID'):
                continue
            if item.due_date is not None:
                if item.due_date < today:
                    overdue_items.append(item)
                elif item.due_date <= deadline_horizon:
                    upcoming_deadline_count += 1

        # Resolve contact names for overdue items
        if overdue_items:
            try:
                all_contacts = await acc_repo.list_contacts(tenant_id)
                contacts_by_id = {
                    c.id: (c.display_name or c.name) for c in all_contacts
                }
            except Exception as exc:
                logger.warning('Greeting: failed to fetch contacts: %s', exc)
    except Exception as exc:
        logger.warning('Greeting: failed to fetch open items: %s', exc)

    overdue_count = len(overdue_items)

    # --- build status_summary ---
    parts: list[str] = []
    if inbox_count:
        label = 'Beleg wartet' if inbox_count == 1 else 'Belege warten'
        parts.append(f'{inbox_count} {label} auf Freigabe')
    if overdue_count:
        label = 'überfälliger Posten' if overdue_count == 1 else 'überfällige Posten'
        parts.append(f'{overdue_count} {label}')
    if upcoming_deadline_count:
        label = 'Frist' if upcoming_deadline_count == 1 else 'Fristen'
        parts.append(f'{upcoming_deadline_count} {label} in den nächsten 7 Tagen')
    status_summary = ', '.join(parts) if parts else 'Alles im grünen Bereich.'

    # --- build urgent ---
    urgent: dict | None = None
    if overdue_items:
        first = overdue_items[0]
        contact_name = contacts_by_id.get(first.contact_id, first.contact_id)
        remaining = first.original_amount - first.paid_amount
        days_overdue = (today - first.due_date).days
        day_label = 'Tag' if days_overdue == 1 else 'Tagen'
        urgent = {
            'text': (
                f'{contact_name} schuldet dir {remaining}\u20AC '
                f'\u2014 seit {days_overdue} {day_label} überfällig.'
            ),
            'case_ref': first.case_id,
            'priority': 'HIGH',
        }
    elif inbox_count > 5:
        urgent = {
            'text': f'{inbox_count} Belege stapeln sich \u2014 soll ich die mal durchgehen?',
            'case_ref': None,
            'priority': 'MEDIUM',
        }

    # --- build suggestions ---
    if not inbox_count and not overdue_count:
        suggestions = ['EÜR anschauen', 'Wäschekorb leeren', 'Alles klar \u2014 Feierabend!']
    elif overdue_items:
        first = overdue_items[0]
        contact_name = contacts_by_id.get(first.contact_id, first.contact_id)
        suggestions = [f'{contact_name} mahnen', 'Inbox öffnen']
    else:
        suggestions = ['Inbox öffnen']

    # Resolve user preferences for display_name + onboarding detection
    prefs = await _get_user_preferences(user.username, tenant_id)
    display_name = prefs.get('display_name') or user.username

    # Onboarding detection: if display_name not set, user is new
    if not prefs.get('display_name'):
        return {
            'greeting': 'Willkommen bei Frya!',
            'status_summary': 'Ich bin deine KI-Buchhaltungsassistentin.',
            'onboarding': True,
            'onboarding_step': 'name',
            'urgent': None,
            'suggestions': [],
        }

    return {
        'greeting': _time_greeting(display_name),
        'status_summary': status_summary,
        'urgent': urgent,
        'suggestions': suggestions,
        'onboarding': False,
    }
