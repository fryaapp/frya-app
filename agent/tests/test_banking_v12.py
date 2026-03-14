"""V1.2 Banking service unit tests.

Covers:
- NO_TRANSACTIONS_AVAILABLE: feed returned 0 transactions
- NO_MATCH_FOUND: transactions exist but none score > 0
- CANDIDATE_FOUND (MEDIUM): partial match
- MATCH_FOUND (HIGH): single definitive match
- AMBIGUOUS_MATCH: two+ HIGH matches
- is_test_data flag on test-probe
- Safety invariants (is_read_only, bank_write_executed)
- feed_status attached to every result
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.banking.models import BankProbeResult, FeedStatus, MatchQuality
from app.banking.service import BankTransactionService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_EMPTY_FEED_STATUS = {
    'reachable': True,
    'source_url': 'https://akaunting.test',
    'accounts_available': 1,
    'transactions_total': 0,
    'note': 'Feed erreichbar. Konten: 1, Transaktionen gesamt: 0.',
}

_FULL_FEED_STATUS = {
    'reachable': True,
    'source_url': 'https://akaunting.test',
    'accounts_available': 1,
    'transactions_total': 3,
    'note': 'Feed erreichbar. Konten: 1, Transaktionen gesamt: 3.',
}


def _make_service(transactions: list[dict], feed_status: dict | None = None) -> BankTransactionService:
    """Build service with mocked connector and audit."""
    connector = AsyncMock()
    connector.search_transactions = AsyncMock(return_value=transactions)
    connector.get_feed_status = AsyncMock(return_value=feed_status or _EMPTY_FEED_STATUS)
    connector.search_accounts = AsyncMock(return_value=[{'id': 1, 'name': 'Test Bank'}])

    audit = AsyncMock()
    audit.log_event = AsyncMock()

    return BankTransactionService(connector, audit)


_TX_EXACT_AMOUNT = {
    'id': 101,
    'amount': '250.00',
    'currency_code': 'EUR',
    'paid_at': '2026-03-01 00:00:00',
    'reference': 'REF-2026-001',
    'contact_name': 'Muster GmbH',
    'description': 'Eingangsrechnung',
}

_TX_WRONG_AMOUNT = {
    'id': 102,
    'amount': '999.99',
    'currency_code': 'EUR',
    'paid_at': '2026-01-15 00:00:00',
    'reference': 'UNRELATED',
    'contact_name': 'Other Corp',
    'description': 'Andere Buchung',
}

_TX_NEAR_AMOUNT = {
    'id': 103,
    'amount': '251.00',   # within 5% of 250
    'currency_code': 'EUR',
    'paid_at': '2026-03-05 00:00:00',
    'reference': 'REF-2026-002',
    'contact_name': 'Muster GmbH',
    'description': 'Korrektur',
}

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_transactions_available_when_feed_empty():
    """Feed reachable but 0 transactions → NO_TRANSACTIONS_AVAILABLE."""
    svc = _make_service(transactions=[])
    result = await svc.probe_transactions('doc-1', amount=250.0)
    assert result.result == BankProbeResult.NO_TRANSACTIONS_AVAILABLE
    assert result.bank_write_executed is False
    assert result.is_read_only is True
    assert result.is_test_data is False
    assert result.feed_status is not None
    assert result.feed_status.reachable is True


@pytest.mark.asyncio
async def test_no_match_found_when_transactions_exist_but_nothing_scores():
    """Transactions exist but no score > 0 → NO_MATCH_FOUND."""
    svc = _make_service(transactions=[_TX_WRONG_AMOUNT], feed_status=_FULL_FEED_STATUS)
    result = await svc.probe_transactions('doc-1', amount=250.0)
    assert result.result == BankProbeResult.NO_MATCH_FOUND
    assert result.candidates == []
    assert result.bank_write_executed is False


@pytest.mark.asyncio
async def test_candidate_found_medium_confidence():
    """AMOUNT_NEAR (25pts) + CONTACT_MATCH (20pts) = 45pts → MEDIUM → CANDIDATE_FOUND."""
    svc = _make_service(transactions=[_TX_NEAR_AMOUNT], feed_status=_FULL_FEED_STATUS)
    result = await svc.probe_transactions('doc-1', amount=250.0, contact_name='Muster')
    assert result.result == BankProbeResult.CANDIDATE_FOUND
    assert len(result.candidates) == 1
    c = result.candidates[0]
    assert c.match_quality == MatchQuality.MEDIUM
    assert 'AMOUNT_NEAR' in c.reason_codes
    assert 'CONTACT_MATCH' in c.reason_codes
    assert c.confidence_score == 45
    assert result.bank_write_executed is False


@pytest.mark.asyncio
async def test_candidate_found_low_confidence():
    """AMOUNT_NEAR (25pts) alone = 25pts < 30 → LOW quality, still CANDIDATE_FOUND."""
    svc = _make_service(transactions=[_TX_NEAR_AMOUNT], feed_status=_FULL_FEED_STATUS)
    result = await svc.probe_transactions('doc-1', amount=250.0)
    assert result.result == BankProbeResult.CANDIDATE_FOUND
    assert len(result.candidates) == 1
    c = result.candidates[0]
    assert c.match_quality == MatchQuality.LOW
    assert 'AMOUNT_NEAR' in c.reason_codes
    assert c.confidence_score == 25
    assert result.bank_write_executed is False


@pytest.mark.asyncio
async def test_match_found_high_confidence_exact_amount():
    """AMOUNT_EXACT (40pts) + REFERENCE_MATCH (30pts) = 70pts → HIGH → MATCH_FOUND."""
    svc = _make_service(transactions=[_TX_EXACT_AMOUNT], feed_status=_FULL_FEED_STATUS)
    result = await svc.probe_transactions('doc-1', amount=250.0, reference='REF-2026-001')
    assert result.result == BankProbeResult.MATCH_FOUND
    assert len(result.candidates) == 1
    c = result.candidates[0]
    assert c.match_quality == MatchQuality.HIGH
    assert c.confidence_score == 70
    assert 'AMOUNT_EXACT' in c.reason_codes
    assert 'REFERENCE_MATCH' in c.reason_codes
    assert result.bank_write_executed is False


@pytest.mark.asyncio
async def test_ambiguous_match_two_high_confidence():
    """Two HIGH-confidence candidates → AMBIGUOUS_MATCH."""
    tx_b = dict(_TX_EXACT_AMOUNT)
    tx_b['id'] = 999
    tx_b['reference'] = 'REF-2026-001'
    svc = _make_service(transactions=[_TX_EXACT_AMOUNT, tx_b], feed_status=_FULL_FEED_STATUS)
    result = await svc.probe_transactions('doc-1', amount=250.0, reference='REF-2026-001')
    assert result.result == BankProbeResult.AMBIGUOUS_MATCH
    assert len([c for c in result.candidates if c.match_quality == MatchQuality.HIGH]) >= 2
    assert result.bank_write_executed is False


@pytest.mark.asyncio
async def test_contact_and_date_scoring():
    """AMOUNT_EXACT (40) + CONTACT_MATCH (20) + DATE_IN_RANGE (10) = 70pts → HIGH."""
    svc = _make_service(transactions=[_TX_EXACT_AMOUNT], feed_status=_FULL_FEED_STATUS)
    result = await svc.probe_transactions(
        'doc-1',
        amount=250.0,
        contact_name='Muster',
        date_from='2026-02-01',
        date_to='2026-03-31',
    )
    assert result.result == BankProbeResult.MATCH_FOUND
    c = result.candidates[0]
    assert c.confidence_score == 70
    assert 'AMOUNT_EXACT' in c.reason_codes
    assert 'CONTACT_MATCH' in c.reason_codes
    assert 'DATE_IN_RANGE' in c.reason_codes


@pytest.mark.asyncio
async def test_safety_invariants_always_hold():
    """bank_write_executed always False, is_read_only always True."""
    svc = _make_service(transactions=[_TX_EXACT_AMOUNT], feed_status=_FULL_FEED_STATUS)
    for kwargs in [
        {},
        {'amount': 250.0},
        {'reference': 'REF', 'amount': 250.0},
    ]:
        result = await svc.probe_transactions('doc-1', **kwargs)
        assert result.bank_write_executed is False, f'Safety violated for kwargs={kwargs}'
        assert result.is_read_only is True, f'is_read_only violated for kwargs={kwargs}'


@pytest.mark.asyncio
async def test_probe_test_transactions_is_flagged():
    """probe_test_transactions: is_test_data=True, same scoring, audit=BANK_TEST_PROBE_EXECUTED."""
    svc = _make_service(transactions=[], feed_status=_EMPTY_FEED_STATUS)

    test_txs = [dict(_TX_EXACT_AMOUNT)]
    result = await svc.probe_test_transactions(
        'doc-1',
        test_transactions=test_txs,
        amount=250.0,
        reference='REF-2026-001',
    )
    assert result.is_test_data is True
    assert result.bank_write_executed is False
    assert result.result == BankProbeResult.MATCH_FOUND
    assert '[TESTDATEN]' in result.note
    # audit event should use BANK_TEST_PROBE_EXECUTED
    svc.audit_service.log_event.assert_called_once()
    call_args = svc.audit_service.log_event.call_args[0][0]
    assert call_args['action'] == 'BANK_TEST_PROBE_EXECUTED'


@pytest.mark.asyncio
async def test_feed_status_always_attached():
    """feed_status is always populated (not None) on successful probe."""
    svc = _make_service(transactions=[], feed_status=_EMPTY_FEED_STATUS)
    result = await svc.probe_transactions('doc-1')
    assert result.feed_status is not None
    assert isinstance(result.feed_status, FeedStatus)
    assert result.feed_status.reachable is True


@pytest.mark.asyncio
async def test_actor_is_v12():
    """actor field must identify v1.2."""
    svc = _make_service(transactions=[])
    result = await svc.probe_transactions('doc-1')
    assert 'v1.2' in result.actor


@pytest.mark.asyncio
async def test_no_filters_returns_available_transaction_candidates():
    """No filters + transactions exist: show AVAILABLE_TRANSACTION candidates."""
    svc = _make_service(transactions=[_TX_EXACT_AMOUNT, _TX_WRONG_AMOUNT], feed_status=_FULL_FEED_STATUS)
    result = await svc.probe_transactions('doc-1')  # no filters
    # Still NO_MATCH_FOUND (informational listing, not a match)
    assert result.result == BankProbeResult.NO_MATCH_FOUND
    # But candidates list shows what's available
    assert len(result.candidates) > 0
    assert all('AVAILABLE_TRANSACTION' in c.reason_codes for c in result.candidates)
    assert result.bank_write_executed is False
