"""Akaunting API compatibility check endpoint."""
from __future__ import annotations

import logging

from fastapi import APIRouter

from app.config import get_settings
from app.connectors.accounting_akaunting import AkauntingConnector

logger = logging.getLogger(__name__)
router = APIRouter(tags=['akaunting'])


def _get_connector() -> AkauntingConnector:
    settings = get_settings()
    return AkauntingConnector(
        base_url=settings.akaunting_base_url,
        email=settings.akaunting_email,
        password=settings.akaunting_password,
        token=settings.akaunting_token,
    )


@router.get('/api/v1/akaunting/health')
async def akaunting_health():
    """Check if Akaunting API is reachable and expected endpoints work."""
    connector = _get_connector()
    checks: dict[str, bool] = {}

    for endpoint in ('companies', 'contacts', 'categories'):
        try:
            await connector.get_object(endpoint, '1')
            checks[endpoint] = True
        except Exception:
            # Try list endpoint (no ID)
            try:
                if endpoint == 'companies':
                    feed = await connector.get_feed_status()
                    checks[endpoint] = feed.get('reachable', False)
                elif endpoint == 'contacts':
                    result = await connector.search_contacts()
                    checks[endpoint] = isinstance(result, list)
                elif endpoint == 'categories':
                    result = await connector.get_categories()
                    checks[endpoint] = isinstance(result, list)
            except Exception:
                checks[endpoint] = False

    all_ok = all(checks.values())
    if not all_ok:
        logger.warning('Akaunting API compatibility check failed: %s', checks)

    return {'compatible': all_ok, 'checks': checks}
