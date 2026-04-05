"""Tenant resolution for the CaseEngine integration.

P-24 SECURITY: This resolver must NEVER return another user's tenant_id.
In multi-tenant mode the tenant MUST come from the JWT (via _resolve_tenant
in each API module). This resolver is ONLY a fallback for non-authenticated
contexts (webhooks, cron jobs, migrations).

WARNING: Do NOT use this function for user-facing API endpoints.
Use the _resolve_tenant(user) pattern instead which reads from JWT first.
"""
from __future__ import annotations

import logging

_logger = logging.getLogger(__name__)


async def resolve_tenant_id() -> str | None:
    """Return a tenant_id string, or None if none can be resolved.

    P-24: In multi-tenant mode this function logs a WARNING because
    it should NOT be used for user-facing requests. The tenant must
    come from the JWT token via _resolve_tenant(user).

    Never raises — callers treat None as "skip CaseEngine".
    """
    _logger.warning(
        'P-24 SECURITY: resolve_tenant_id() called without JWT context. '
        'This is only safe for webhooks/cron. If this appears during a '
        'user request, there is a tenant isolation bug!'
    )

    from app.config import get_settings

    # ── 1. Explicit ENV override (only for non-user contexts) ─────────────────
    try:
        settings = get_settings()
        if settings.default_tenant_id:
            _logger.info('CaseEngine: tenant_id resolved from config: %s', settings.default_tenant_id)
            return settings.default_tenant_id
    except Exception as exc:
        _logger.warning('CaseEngine: could not read settings: %s', exc)

    # ── 2. P-24: Do NOT fall back to "first active tenant" ────────────────────
    # This was the root cause of cross-tenant data leaks.
    # In multi-tenant mode, returning the wrong tenant is a security breach.
    _logger.warning('CaseEngine: no tenant_id available — returning None (multi-tenant safe)')
    return None
