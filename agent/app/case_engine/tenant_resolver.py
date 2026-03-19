"""Tenant resolution for the CaseEngine integration.

Single-tenant strategy (Staging / MVP):
  1. ENV:  FRYA_DEFAULT_TENANT_ID  → use directly
  2. DB:   frya_tenants WHERE status='active' LIMIT 1  → first tenant
  3. None  → CaseEngine integration is skipped silently

Multi-tenant routing (coming later) will replace this with session/JWT lookup.
"""
from __future__ import annotations

import logging

_logger = logging.getLogger(__name__)


async def resolve_tenant_id() -> str | None:
    """Return a tenant_id string, or None if none can be resolved.

    Logs at INFO level when resolved, at DEBUG level when skipped.
    Never raises — callers treat None as "skip CaseEngine".
    """
    from app.config import get_settings
    from app.dependencies import get_tenant_repository

    # ── 1. Explicit ENV override ───────────────────────────────────────────────
    try:
        settings = get_settings()
        if settings.default_tenant_id:
            _logger.info('CaseEngine: tenant_id resolved from config: %s', settings.default_tenant_id)
            return settings.default_tenant_id
    except Exception as exc:
        _logger.warning('CaseEngine: could not read settings: %s', exc)

    # ── 2. First active tenant from DB ────────────────────────────────────────
    try:
        repo = get_tenant_repository()
        tenants = await repo.list_active()
        if tenants:
            tid = tenants[0].tenant_id
            _logger.info('CaseEngine: tenant_id resolved from DB: %s', tid)
            return tid
    except Exception as exc:
        _logger.warning('CaseEngine: tenant DB lookup failed: %s', exc)

    # ── 3. No tenant available ────────────────────────────────────────────────
    _logger.debug('CaseEngine: skipped, no tenant_id available')
    return None
