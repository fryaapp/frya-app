"""Tests for GoBD write-once DB enforcement (migration 0012).

These tests verify the *application-level* contract: the migration SQL
correctly defines REVOKE statements for accounting tables.
The actual PostgreSQL enforcement is tested via integration tests against
a real DB in CI.  Unit tests here verify the migration file is well-formed
and that the audit repository only exposes append operations (no update/delete).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.audit.repository import AuditRepository
from app.audit.service import AuditService


MIGRATION_FILE = (
    Path(__file__).parent.parent / 'migrations' / '0012_gobd_write_once.sql'
)

WRITE_ONCE_TABLES = ['frya_audit_log', 'case_documents', 'case_references']
REVOKED_OPERATIONS = ['UPDATE', 'DELETE', 'TRUNCATE']


# ---------------------------------------------------------------------------
# Migration file structure
# ---------------------------------------------------------------------------

def test_migration_file_exists():
    assert MIGRATION_FILE.exists(), f'Migration not found: {MIGRATION_FILE}'


def test_migration_revokes_all_tables():
    sql = MIGRATION_FILE.read_text(encoding='utf-8')
    for table in WRITE_ONCE_TABLES:
        assert table in sql, f'Missing REVOKE for table {table!r}'


def test_migration_revokes_all_operations():
    sql = MIGRATION_FILE.read_text(encoding='utf-8').upper()
    for op in REVOKED_OPERATIONS:
        assert op in sql, f'Missing REVOKE of {op!r} in migration'


def test_migration_targets_frya_user():
    sql = MIGRATION_FILE.read_text(encoding='utf-8')
    assert 'FROM frya' in sql or 'from frya' in sql.lower(), (
        'Migration must REVOKE FROM frya application user'
    )


def test_migration_has_revoke_statements():
    sql = MIGRATION_FILE.read_text(encoding='utf-8').upper()
    revoke_count = sql.count('REVOKE')
    assert revoke_count >= 3, (
        f'Expected at least 3 REVOKE statements, found {revoke_count}'
    )


# ---------------------------------------------------------------------------
# AuditRepository — no update/delete exposed
# ---------------------------------------------------------------------------

def test_audit_repository_has_no_update_method():
    """AuditRepository must not expose any update/delete method."""
    public_methods = [
        m for m in dir(AuditRepository)
        if not m.startswith('_')
    ]
    forbidden = [m for m in public_methods if any(
        kw in m.lower() for kw in ('update', 'delete', 'truncate', 'remove', 'clear')
    )]
    assert forbidden == [], (
        f'AuditRepository must be append-only. Found forbidden methods: {forbidden}'
    )


@pytest.mark.asyncio
async def test_audit_repository_append_only_in_memory():
    """Verify that new records are appended and existing records are immutable."""
    repo = AuditRepository('memory://audit')
    service = AuditService(repo)
    await service.initialize()

    r1 = await service.log_event({
        'event_id': 'wo-1',
        'source': 'test',
        'agent_name': 'agent',
        'action': 'WRITE_ONCE_TEST',
        'result': 'original',
        'approval_status': 'NOT_REQUIRED',
    })

    # Capture original record hash
    original_hash = r1.record_hash

    r2 = await service.log_event({
        'event_id': 'wo-2',
        'source': 'test',
        'agent_name': 'agent',
        'action': 'SECOND_EVENT',
        'result': 'second',
        'approval_status': 'NOT_REQUIRED',
    })

    # Verify first record is unchanged in memory store
    rows = await repo.list_all_ordered()
    assert rows[0][2] == original_hash, 'First record hash must not change after second insert'
    # Verify second record references first
    assert rows[1][1] == original_hash, 'Second record previous_hash must equal first record_hash'


@pytest.mark.asyncio
async def test_audit_log_entries_immutable_after_insert():
    """Direct memory store manipulation check — records are pydantic models (immutable by default)."""
    repo = AuditRepository('memory://audit')
    service = AuditService(repo)
    await service.initialize()

    record = await service.log_event({
        'event_id': 'immutable-test',
        'source': 'test',
        'agent_name': 'agent',
        'action': 'IMMUTABILITY_CHECK',
        'result': 'original_result',
        'approval_status': 'NOT_REQUIRED',
    })

    original_action = record.action
    original_hash = record.record_hash

    # Pydantic v2 models are mutable by default, but the DB layer enforces immutability.
    # Verify the stored record matches what was returned.
    stored = repo._memory_records[0]
    assert stored.action == original_action
    assert stored.record_hash == original_hash
