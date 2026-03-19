"""Tests for CaseEngine: conflict creation and resolution."""
from __future__ import annotations

import asyncio
import uuid

import pytest


def _run(coro):
    return asyncio.run(coro)


def _repo():
    from app.case_engine.repository import CaseRepository
    return CaseRepository('memory://test')


TENANT = uuid.uuid4()


# ── Create conflict ───────────────────────────────────────────────────────────

def test_create_conflict():
    async def run():
        repo = _repo()
        case = await repo.create_case(tenant_id=TENANT, case_type='incoming_invoice')
        conflict = await repo.create_conflict(
            case_id=case.id,
            conflict_type='amount_mismatch',
            description='Invoice says 100 EUR, booking says 110 EUR',
        )
        assert conflict.case_id == case.id
        assert conflict.conflict_type == 'amount_mismatch'
        assert conflict.description is not None
        assert conflict.resolution is None
    _run(run())


# ── get_conflicts returns all conflicts for case ──────────────────────────────

def test_get_conflicts_for_case():
    async def run():
        repo = _repo()
        case = await repo.create_case(tenant_id=TENANT, case_type='other')
        await repo.create_conflict(case_id=case.id, conflict_type='duplicate_case')
        await repo.create_conflict(case_id=case.id, conflict_type='vendor_mismatch')
        conflicts = await repo.get_conflicts(case.id)
        assert len(conflicts) == 2
        types = {c.conflict_type for c in conflicts}
        assert 'duplicate_case' in types
        assert 'vendor_mismatch' in types
    _run(run())


# ── get_conflicts: other case's conflicts not returned ────────────────────────

def test_get_conflicts_isolation():
    async def run():
        repo = _repo()
        c1 = await repo.create_case(tenant_id=TENANT, case_type='other')
        c2 = await repo.create_case(tenant_id=TENANT, case_type='other')
        await repo.create_conflict(case_id=c1.id, conflict_type='multi_match')
        conflicts_c2 = await repo.get_conflicts(c2.id)
        assert len(conflicts_c2) == 0
    _run(run())


# ── Resolve conflict ──────────────────────────────────────────────────────────

def test_resolve_conflict_manual():
    async def run():
        repo = _repo()
        case = await repo.create_case(tenant_id=TENANT, case_type='incoming_invoice')
        conflict = await repo.create_conflict(
            case_id=case.id,
            conflict_type='date_mismatch',
        )
        resolved = await repo.resolve_conflict(
            conflict.id,
            'resolved_manual',
            resolved_by='operator@frya.de',
        )
        assert resolved.resolution == 'resolved_manual'
        assert resolved.resolved_by == 'operator@frya.de'
        assert resolved.resolved_at is not None
    _run(run())


# ── Resolve conflict: auto resolution ────────────────────────────────────────

def test_resolve_conflict_auto():
    async def run():
        repo = _repo()
        case = await repo.create_case(tenant_id=TENANT, case_type='other')
        conflict = await repo.create_conflict(
            case_id=case.id,
            conflict_type='duplicate_case',
        )
        resolved = await repo.resolve_conflict(conflict.id, 'resolved_auto')
        assert resolved.resolution == 'resolved_auto'
        assert resolved.resolved_by is None
    _run(run())


# ── Resolve conflict: ignored ─────────────────────────────────────────────────

def test_resolve_conflict_ignored():
    async def run():
        repo = _repo()
        case = await repo.create_case(tenant_id=TENANT, case_type='other')
        conflict = await repo.create_conflict(
            case_id=case.id,
            conflict_type='multi_match',
            description='Multiple cases matched',
        )
        resolved = await repo.resolve_conflict(conflict.id, 'ignored')
        assert resolved.resolution == 'ignored'
    _run(run())


# ── Resolve unknown conflict → ValueError ────────────────────────────────────

def test_resolve_unknown_conflict_raises():
    async def run():
        repo = _repo()
        with pytest.raises(ValueError, match='not found'):
            await repo.resolve_conflict(uuid.uuid4(), 'resolved_manual')
    _run(run())


# ── Conflict with metadata ────────────────────────────────────────────────────

def test_conflict_metadata():
    async def run():
        repo = _repo()
        case = await repo.create_case(tenant_id=TENANT, case_type='incoming_invoice')
        conflict = await repo.create_conflict(
            case_id=case.id,
            conflict_type='amount_mismatch',
            metadata={'expected': '100.00', 'actual': '110.00'},
        )
        assert conflict.metadata['expected'] == '100.00'
        conflicts = await repo.get_conflicts(case.id)
        assert conflicts[0].metadata['actual'] == '110.00'
    _run(run())
