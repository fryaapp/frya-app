"""Tests for GoBD hash-chain integrity (verify-chain endpoint + service)."""
from __future__ import annotations

import pytest

from app.audit.repository import AuditRepository
from app.audit.service import AuditService


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

async def _make_service(n_events: int = 3) -> AuditService:
    repo = AuditRepository('memory://audit')
    service = AuditService(repo)
    await service.initialize()
    for i in range(n_events):
        await service.log_event(
            {
                'event_id': f'e{i}',
                'source': 'test',
                'agent_name': 'agent',
                'action': f'ACTION_{i}',
                'result': f'ok{i}',
                'approval_status': 'NOT_REQUIRED',
            }
        )
    return service


# ---------------------------------------------------------------------------
# verify_chain — valid chains
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_verify_chain_empty_log():
    repo = AuditRepository('memory://audit')
    service = AuditService(repo)
    await service.initialize()
    result = await service.verify_chain()
    assert result['valid'] is True
    assert result['entries_checked'] == 0
    assert result['first_broken_at'] is None


@pytest.mark.asyncio
async def test_verify_chain_single_entry():
    service = await _make_service(1)
    result = await service.verify_chain()
    assert result['valid'] is True
    assert result['entries_checked'] == 1
    assert result['first_broken_at'] is None


@pytest.mark.asyncio
async def test_verify_chain_multiple_entries_intact():
    service = await _make_service(5)
    result = await service.verify_chain()
    assert result['valid'] is True
    assert result['entries_checked'] == 5
    assert result['first_broken_at'] is None


# ---------------------------------------------------------------------------
# verify_chain — tampered chain
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_verify_chain_detects_tampered_previous_hash():
    service = await _make_service(4)

    # Manually corrupt the previous_hash of record #3
    records = service.repository._memory_records
    assert len(records) == 4
    records[2] = records[2].model_copy(update={'previous_hash': 'TAMPERED_HASH'})

    result = await service.verify_chain()
    assert result['valid'] is False
    assert result['first_broken_at'] is not None


@pytest.mark.asyncio
async def test_verify_chain_returns_entries_checked_on_failure():
    service = await _make_service(6)

    # Corrupt record at index 1 (second record)
    records = service.repository._memory_records
    records[1] = records[1].model_copy(update={'previous_hash': 'BAD'})

    result = await service.verify_chain()
    assert result['valid'] is False
    # first_broken_at should be 2 (1-based index of the second record)
    assert result['first_broken_at'] == 2


# ---------------------------------------------------------------------------
# list_all_ordered
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_all_ordered_returns_id_prev_hash_record_hash():
    service = await _make_service(3)
    rows = await service.repository.list_all_ordered()
    assert len(rows) == 3
    # Each row: (id, previous_hash, record_hash)
    for row in rows:
        assert len(row) == 3
        row_id, prev_hash, rec_hash = row
        assert isinstance(row_id, int)
        assert rec_hash  # must be non-empty


@pytest.mark.asyncio
async def test_list_all_ordered_hash_chain_links():
    service = await _make_service(4)
    rows = await service.repository.list_all_ordered()
    for i in range(1, len(rows)):
        _, prev_of_current, _ = rows[i]
        _, _, hash_of_previous = rows[i - 1]
        assert prev_of_current == hash_of_previous, (
            f'Hash chain broken between row {i} and {i+1}'
        )
