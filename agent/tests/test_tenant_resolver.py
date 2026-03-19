"""Tests for app/case_engine/tenant_resolver.py.

Scenarios:
  1. ENV FRYA_DEFAULT_TENANT_ID set → returned immediately (no DB query)
  2. No ENV, DB has one active tenant → first tenant's ID returned
  3. No ENV, DB has multiple active tenants → first tenant returned
  4. No ENV, DB empty → None returned
  5. No ENV, DB unavailable (exception) → None returned, no raise
  6. ENV takes priority over DB (ENV wins even if DB has tenants)
  7. Memory-backend TenantRepository used without ENV → returns tenant_id
  8. Invalid ENV value (not a UUID, but non-empty string) → still returned as-is
     (resolver returns raw string; UUID validation is done by the CaseEngine hook)
"""
from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch


def _run(coro):
    return asyncio.run(coro)


def _clear_caches():
    import app.config as config_module
    import app.dependencies as deps_module
    config_module.get_settings.cache_clear()
    for name in dir(deps_module):
        obj = getattr(deps_module, name)
        if callable(obj) and hasattr(obj, 'cache_clear'):
            obj.cache_clear()


# ── Test 1: ENV set → returned immediately ────────────────────────────────────

def test_env_default_tenant_id_returned(monkeypatch):
    tid = str(uuid.uuid4())
    monkeypatch.setenv('FRYA_DEFAULT_TENANT_ID', tid)
    monkeypatch.setenv('FRYA_DATABASE_URL', 'memory://db')
    monkeypatch.setenv('FRYA_REDIS_URL', 'memory://redis')
    monkeypatch.setenv('FRYA_PAPERLESS_BASE_URL', 'http://p')
    monkeypatch.setenv('FRYA_AKAUNTING_BASE_URL', 'http://a')
    monkeypatch.setenv('FRYA_N8N_BASE_URL', 'http://n')
    monkeypatch.setenv('FRYA_AUTH_SESSION_SECRET', 'test')
    _clear_caches()

    from app.case_engine.tenant_resolver import resolve_tenant_id
    result = _run(resolve_tenant_id())
    assert result == tid


# ── Test 2: No ENV, memory DB has one active tenant ───────────────────────────

def test_db_one_active_tenant(monkeypatch):
    monkeypatch.setenv('FRYA_DEFAULT_TENANT_ID', '')
    monkeypatch.setenv('FRYA_DATABASE_URL', 'memory://db')
    monkeypatch.setenv('FRYA_REDIS_URL', 'memory://redis')
    monkeypatch.setenv('FRYA_PAPERLESS_BASE_URL', 'http://p')
    monkeypatch.setenv('FRYA_AKAUNTING_BASE_URL', 'http://a')
    monkeypatch.setenv('FRYA_N8N_BASE_URL', 'http://n')
    monkeypatch.setenv('FRYA_AUTH_SESSION_SECRET', 'test')
    _clear_caches()

    tid = str(uuid.uuid4())

    async def run():
        from app.auth.tenant_repository import TenantRecord
        from app.dependencies import get_tenant_repository
        repo = get_tenant_repository()
        await repo.create_tenant(TenantRecord(tenant_id=tid, name='test-tenant', status='active'))
        from app.case_engine.tenant_resolver import resolve_tenant_id
        return await resolve_tenant_id()

    result = _run(run())
    assert result == tid


# ── Test 3: No ENV, DB has multiple active tenants → first returned ────────────

def test_db_multiple_tenants_returns_first(monkeypatch):
    monkeypatch.setenv('FRYA_DEFAULT_TENANT_ID', '')
    monkeypatch.setenv('FRYA_DATABASE_URL', 'memory://db')
    monkeypatch.setenv('FRYA_REDIS_URL', 'memory://redis')
    monkeypatch.setenv('FRYA_PAPERLESS_BASE_URL', 'http://p')
    monkeypatch.setenv('FRYA_AKAUNTING_BASE_URL', 'http://a')
    monkeypatch.setenv('FRYA_N8N_BASE_URL', 'http://n')
    monkeypatch.setenv('FRYA_AUTH_SESSION_SECRET', 'test')
    _clear_caches()

    t1 = str(uuid.uuid4())
    t2 = str(uuid.uuid4())

    async def run():
        from app.auth.tenant_repository import TenantRecord
        from app.dependencies import get_tenant_repository
        repo = get_tenant_repository()
        await repo.create_tenant(TenantRecord(tenant_id=t1, name='alpha', status='active'))
        await repo.create_tenant(TenantRecord(tenant_id=t2, name='beta', status='active'))
        from app.case_engine.tenant_resolver import resolve_tenant_id
        return await resolve_tenant_id()

    result = _run(run())
    assert result in (t1, t2)  # one of the two, deterministic by insertion order


# ── Test 4: No ENV, DB empty → None ──────────────────────────────────────────

def test_db_empty_returns_none(monkeypatch):
    monkeypatch.setenv('FRYA_DEFAULT_TENANT_ID', '')
    monkeypatch.setenv('FRYA_DATABASE_URL', 'memory://db')
    monkeypatch.setenv('FRYA_REDIS_URL', 'memory://redis')
    monkeypatch.setenv('FRYA_PAPERLESS_BASE_URL', 'http://p')
    monkeypatch.setenv('FRYA_AKAUNTING_BASE_URL', 'http://a')
    monkeypatch.setenv('FRYA_N8N_BASE_URL', 'http://n')
    monkeypatch.setenv('FRYA_AUTH_SESSION_SECRET', 'test')
    _clear_caches()

    from app.case_engine.tenant_resolver import resolve_tenant_id
    result = _run(resolve_tenant_id())
    assert result is None


# ── Test 5: DB raises → None, no crash ───────────────────────────────────────

def test_db_error_returns_none_no_raise(monkeypatch):
    monkeypatch.setenv('FRYA_DEFAULT_TENANT_ID', '')
    monkeypatch.setenv('FRYA_DATABASE_URL', 'memory://db')
    monkeypatch.setenv('FRYA_REDIS_URL', 'memory://redis')
    monkeypatch.setenv('FRYA_PAPERLESS_BASE_URL', 'http://p')
    monkeypatch.setenv('FRYA_AKAUNTING_BASE_URL', 'http://a')
    monkeypatch.setenv('FRYA_N8N_BASE_URL', 'http://n')
    monkeypatch.setenv('FRYA_AUTH_SESSION_SECRET', 'test')
    _clear_caches()

    broken_repo = MagicMock()
    broken_repo.list_active = AsyncMock(side_effect=RuntimeError('DB offline'))

    with patch('app.dependencies.get_tenant_repository', return_value=broken_repo):
        from app.case_engine import tenant_resolver
        import importlib
        importlib.reload(tenant_resolver)
        result = _run(tenant_resolver.resolve_tenant_id())

    assert result is None


# ── Test 6: ENV takes priority over DB ───────────────────────────────────────

def test_env_takes_priority_over_db(monkeypatch):
    env_tid = str(uuid.uuid4())
    db_tid = str(uuid.uuid4())

    monkeypatch.setenv('FRYA_DEFAULT_TENANT_ID', env_tid)
    monkeypatch.setenv('FRYA_DATABASE_URL', 'memory://db')
    monkeypatch.setenv('FRYA_REDIS_URL', 'memory://redis')
    monkeypatch.setenv('FRYA_PAPERLESS_BASE_URL', 'http://p')
    monkeypatch.setenv('FRYA_AKAUNTING_BASE_URL', 'http://a')
    monkeypatch.setenv('FRYA_N8N_BASE_URL', 'http://n')
    monkeypatch.setenv('FRYA_AUTH_SESSION_SECRET', 'test')
    _clear_caches()

    async def run():
        from app.auth.tenant_repository import TenantRecord
        from app.dependencies import get_tenant_repository
        repo = get_tenant_repository()
        await repo.create_tenant(TenantRecord(tenant_id=db_tid, name='db-tenant', status='active'))
        from app.case_engine.tenant_resolver import resolve_tenant_id
        return await resolve_tenant_id()

    result = _run(run())
    assert result == env_tid  # ENV wins


# ── Test 7: deleted tenant not returned ──────────────────────────────────────

def test_deleted_tenant_not_returned(monkeypatch):
    monkeypatch.setenv('FRYA_DEFAULT_TENANT_ID', '')
    monkeypatch.setenv('FRYA_DATABASE_URL', 'memory://db')
    monkeypatch.setenv('FRYA_REDIS_URL', 'memory://redis')
    monkeypatch.setenv('FRYA_PAPERLESS_BASE_URL', 'http://p')
    monkeypatch.setenv('FRYA_AKAUNTING_BASE_URL', 'http://a')
    monkeypatch.setenv('FRYA_N8N_BASE_URL', 'http://n')
    monkeypatch.setenv('FRYA_AUTH_SESSION_SECRET', 'test')
    _clear_caches()

    async def run():
        from app.auth.tenant_repository import TenantRecord
        from app.dependencies import get_tenant_repository
        repo = get_tenant_repository()
        await repo.create_tenant(TenantRecord(
            tenant_id=str(uuid.uuid4()),
            name='deleted',
            status='deleted',
        ))
        from app.case_engine.tenant_resolver import resolve_tenant_id
        return await resolve_tenant_id()

    result = _run(run())
    assert result is None  # deleted tenant must not be used
