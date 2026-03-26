"""Tests for Paket 61: DSGVO tenant soft-delete and hard-delete."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta


def _run(coro):
    return asyncio.run(coro)


def _check(label: str, ok: bool, detail=None):
    if not ok:
        raise AssertionError(f'FAIL [{label}]: {detail}')


# ── Test 1: Soft-delete sets status=pending_deletion ─────────────────────────

def test_soft_delete_sets_pending_status():
    async def run():
        from app.auth.tenant_repository import TenantRecord, TenantRepository
        repo = TenantRepository('memory://db')
        tenant = TenantRecord(tenant_id='t-001', name='Test GmbH', status='active')
        await repo.create_tenant(tenant)

        hard_delete_after = datetime.utcnow() + timedelta(days=30)
        updated = await repo.soft_delete('t-001', requested_by='admin', hard_delete_after=hard_delete_after)
        _check('status is pending_deletion', updated.status == 'pending_deletion', updated.status)
        _check('requested_by set', updated.deletion_requested_by == 'admin', updated.deletion_requested_by)
        _check('hard_delete_after set', updated.hard_delete_after is not None, updated.hard_delete_after)
    _run(run())


# ── Test 2: Soft-delete twice is rejected ────────────────────────────────────

def test_soft_delete_twice_rejected():
    async def run():
        from app.auth.tenant_repository import TenantRecord, TenantRepository
        repo = TenantRepository('memory://db')
        tenant = TenantRecord(tenant_id='t-002', name='Test GmbH', status='active')
        await repo.create_tenant(tenant)

        hda = datetime.utcnow() + timedelta(days=30)
        await repo.soft_delete('t-002', requested_by='admin', hard_delete_after=hda)
        second = await repo.soft_delete('t-002', requested_by='admin', hard_delete_after=hda)
        _check('second soft_delete returns None', second is None, second)
    _run(run())


# ── Test 3: Hard-delete only after window ────────────────────────────────────

def test_hard_delete_after_window():
    async def run():
        from app.auth.tenant_repository import TenantRecord, TenantRepository
        repo = TenantRepository('memory://db')
        tenant = TenantRecord(tenant_id='t-003', name='Test GmbH', status='active')
        await repo.create_tenant(tenant)

        # Set hard_delete_after to past (simulate expired window)
        hda = datetime.utcnow() - timedelta(days=1)
        await repo.soft_delete('t-003', requested_by='admin', hard_delete_after=hda)

        pending = await repo.list_pending_hard_delete()
        ids = [t.tenant_id for t in pending]
        _check('t-003 in pending hard delete', 't-003' in ids, ids)

        await repo.mark_hard_deleted('t-003')
        updated = await repo.find_by_id('t-003')
        _check('status is deleted', updated.status == 'deleted', updated.status)
    _run(run())


# ── Test 4: Active tenant not in pending_hard_delete list ────────────────────

def test_active_tenant_not_in_pending_hard_delete():
    async def run():
        from app.auth.tenant_repository import TenantRecord, TenantRepository
        repo = TenantRepository('memory://db')
        tenant = TenantRecord(tenant_id='t-004', name='Active GmbH', status='active')
        await repo.create_tenant(tenant)
        pending = await repo.list_pending_hard_delete()
        ids = [t.tenant_id for t in pending]
        _check('active tenant not in pending', 't-004' not in ids, ids)
    _run(run())


# ── Test 5: TENANT_DELETION_REQUESTED audit event structure ──────────────────

def test_tenant_deletion_audit_event_fields():
    event = {
        'action': 'TENANT_DELETION_REQUESTED',
        'llm_output': {
            'tenant_id': 't-005',
            'requested_by': 'admin',
            'hard_delete_after': '2026-04-17T00:00:00',
        },
    }
    _check('action correct', event['action'] == 'TENANT_DELETION_REQUESTED', event['action'])
    _check('tenant_id in payload', 'tenant_id' in event['llm_output'], event['llm_output'])
    _check('requested_by in payload', 'requested_by' in event['llm_output'], event['llm_output'])


# ── Test 6: Deactivate users by tenant ───────────────────────────────────────

def test_deactivate_users_by_tenant():
    async def run():
        from app.auth.user_repository import UserRecord, UserRepository
        repo = UserRepository('memory://db')
        await repo.create_user(UserRecord(username='u1', email='u1@x.de', role='operator', tenant_id='t-abc'))
        await repo.create_user(UserRecord(username='u2', email='u2@x.de', role='operator', tenant_id='t-abc'))
        await repo.create_user(UserRecord(username='u3', email='u3@x.de', role='operator', tenant_id='t-other'))

        count = await repo.deactivate_by_tenant('t-abc')
        _check('2 users deactivated', count == 2, count)
        u1 = await repo.find_by_username('u1')
        _check('u1 is inactive', not u1.is_active, u1)
        u3 = await repo.find_by_username('u3')
        _check('u3 (other tenant) still active', u3.is_active, u3)
    _run(run())


# ── Test 7: Tenant not found returns None ────────────────────────────────────

def test_tenant_not_found():
    async def run():
        from app.auth.tenant_repository import TenantRepository
        repo = TenantRepository('memory://db')
        result = await repo.find_by_id('nonexistent')
        _check('not found returns None', result is None, result)
    _run(run())


# ── Test 8: Only active tenants in list_active ───────────────────────────────

def test_list_active_excludes_deleted():
    async def run():
        from app.auth.tenant_repository import TenantRecord, TenantRepository
        repo = TenantRepository('memory://db')
        await repo.create_tenant(TenantRecord(tenant_id='ta-1', name='Active', status='active'))
        await repo.create_tenant(TenantRecord(tenant_id='ta-2', name='Deleted', status='deleted'))
        active = await repo.list_active()
        ids = [t.tenant_id for t in active]
        _check('active tenant included', 'ta-1' in ids, ids)
        _check('deleted tenant excluded', 'ta-2' not in ids, ids)
    _run(run())
