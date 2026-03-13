from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from app.accounting_analysis.akaunting_reconciliation_service import (
    AkauntingReconciliationService,
    ReconciliationResult,
)
from app.accounting_analysis.models import AkauntingReconciliationInput


def _make_audit_event(action: str) -> MagicMock:
    e = MagicMock()
    e.action = action
    return e


def _make_service(get_object_side_effect=None, get_object_return=None):
    connector = MagicMock()
    if get_object_side_effect is not None:
        connector.get_object = AsyncMock(side_effect=get_object_side_effect)
    else:
        connector.get_object = AsyncMock(return_value=get_object_return or {})

    audit = MagicMock()
    audit.by_case = AsyncMock(return_value=[_make_audit_event('EXTERNAL_ACCOUNTING_COMPLETED')])
    audit.log_event = AsyncMock()

    return AkauntingReconciliationService(connector, audit), connector, audit


def _make_input(**kwargs) -> AkauntingReconciliationInput:
    defaults = {
        'case_id': 'test-case-1',
        'object_type': 'bills',
        'object_id': '42',
        'triggered_by': 'admin',
    }
    defaults.update(kwargs)
    return AkauntingReconciliationInput(**defaults)


@pytest.mark.asyncio
async def test_lookup_found():
    svc, connector, audit = _make_service(get_object_return={'id': 42, 'status': 'received'})

    result = await svc.lookup(_make_input())

    assert result.status == 'FOUND'
    assert result.raw_data == {'id': 42, 'status': 'received'}
    assert result.error_detail is None
    assert result.execution_allowed is False
    assert result.external_write_performed is False
    assert result.case_id == 'test-case-1'
    assert result.object_type == 'bills'
    assert result.object_id == '42'
    audit.log_event.assert_awaited_once()
    logged = audit.log_event.call_args[0][0]
    assert logged['action'] == 'AKAUNTING_RECONCILIATION_LOOKUP'
    assert logged['result'] == 'FOUND'


@pytest.mark.asyncio
async def test_lookup_not_found():
    response_mock = MagicMock()
    response_mock.status_code = 404
    exc = httpx.HTTPStatusError('not found', request=MagicMock(), response=response_mock)

    svc, _, audit = _make_service(get_object_side_effect=exc)

    result = await svc.lookup(_make_input())

    assert result.status == 'NOT_FOUND'
    assert result.raw_data is None
    assert result.execution_allowed is False
    assert result.external_write_performed is False
    logged = audit.log_event.call_args[0][0]
    assert logged['result'] == 'NOT_FOUND'


@pytest.mark.asyncio
async def test_lookup_error_on_non_404_http():
    response_mock = MagicMock()
    response_mock.status_code = 500
    exc = httpx.HTTPStatusError('server error', request=MagicMock(), response=response_mock)

    svc, _, audit = _make_service(get_object_side_effect=exc)

    result = await svc.lookup(_make_input())

    assert result.status == 'ERROR'
    assert result.error_detail == 'HTTP 500'
    assert result.raw_data is None
    assert result.execution_allowed is False
    assert result.external_write_performed is False
    logged = audit.log_event.call_args[0][0]
    assert logged['result'] == 'ERROR'


@pytest.mark.asyncio
async def test_lookup_error_on_network_exception():
    svc, _, _ = _make_service(get_object_side_effect=ConnectionError('timeout'))

    result = await svc.lookup(_make_input())

    assert result.status == 'ERROR'
    assert result.error_detail is not None
    assert result.execution_allowed is False
    assert result.external_write_performed is False


@pytest.mark.asyncio
async def test_lookup_blocked_when_no_end_state():
    svc, connector, audit = _make_service(get_object_return={'id': 1})
    audit.by_case = AsyncMock(return_value=[_make_audit_event('ACCOUNTING_ANALYST_READY')])

    with pytest.raises(ValueError, match='konservativen Endzustand'):
        await svc.lookup(_make_input())

    connector.get_object.assert_not_awaited()
    audit.log_event.assert_not_awaited()


@pytest.mark.asyncio
async def test_lookup_blocked_when_no_events():
    svc, connector, audit = _make_service(get_object_return={'id': 1})
    audit.by_case = AsyncMock(return_value=[])

    with pytest.raises(ValueError, match='konservativen Endzustand'):
        await svc.lookup(_make_input())

    connector.get_object.assert_not_awaited()


@pytest.mark.asyncio
async def test_lookup_allowed_after_external_return_clarification():
    svc, connector, audit = _make_service(get_object_return={'id': 99})
    audit.by_case = AsyncMock(
        return_value=[_make_audit_event('EXTERNAL_RETURN_CLARIFICATION_COMPLETED')]
    )

    result = await svc.lookup(_make_input(object_type='invoices', object_id='99'))

    assert result.status == 'FOUND'
    assert result.execution_allowed is False
    assert result.external_write_performed is False


@pytest.mark.asyncio
async def test_lookup_always_sets_safe_flags():
    """execution_allowed and external_write_performed are always False - no exceptions."""
    svc, _, _ = _make_service(get_object_return={'id': 1})

    result = await svc.lookup(_make_input())

    assert result.execution_allowed is False
    assert result.external_write_performed is False
    assert result.reconciliation_version == 'akaunting-reconciliation-v1'


# ---------------------------------------------------------------------------
# Probe V1 tests
# ---------------------------------------------------------------------------

def _make_probe_service(search_bills_return=None, search_invoices_return=None, side_effect=None):
    connector = MagicMock()
    if side_effect is not None:
        connector.search_bills = AsyncMock(side_effect=side_effect)
        connector.search_invoices = AsyncMock(side_effect=side_effect)
    else:
        connector.search_bills = AsyncMock(return_value=search_bills_return or [])
        connector.search_invoices = AsyncMock(return_value=search_invoices_return or [])

    audit = MagicMock()
    audit.log_event = AsyncMock()

    return AkauntingReconciliationService(connector, audit), connector, audit


@pytest.mark.asyncio
async def test_match_found():
    """1 Treffer -> MATCH_FOUND."""
    bill = {'id': 1, 'document_number': 'INV-001', 'amount': '100.00', 'contact_name': 'ACME GmbH'}
    svc, _, audit = _make_probe_service(search_bills_return=[bill])

    result = await svc.probe_case('test-case-1', {'document_number': 'INV-001'})

    assert result.result == ReconciliationResult.MATCH_FOUND
    assert len(result.matches) == 1
    assert result.akaunting_write_executed is False
    assert result.is_read_only is True
    audit.log_event.assert_awaited_once()
    logged = audit.log_event.call_args[0][0]
    assert logged['action'] == 'AKAUNTING_PROBE_EXECUTED'
    assert logged['result'] == 'MATCH_FOUND'


@pytest.mark.asyncio
async def test_no_match_found():
    """0 Treffer -> NO_MATCH_FOUND."""
    svc, _, audit = _make_probe_service(search_bills_return=[], search_invoices_return=[])

    result = await svc.probe_case('test-case-2', {'document_number': 'MISSING-999'})

    assert result.result == ReconciliationResult.NO_MATCH_FOUND
    assert result.matches == []
    assert result.akaunting_write_executed is False
    logged = audit.log_event.call_args[0][0]
    assert logged['result'] == 'NO_MATCH_FOUND'


@pytest.mark.asyncio
async def test_ambiguous_match():
    """2+ Treffer -> AMBIGUOUS_MATCH."""
    bill1 = {'id': 1, 'document_number': 'INV-001', 'amount': '100.00', 'type': 'bill'}
    bill2 = {'id': 2, 'document_number': 'INV-001', 'amount': '100.00', 'type': 'bill2'}
    svc, _, audit = _make_probe_service(search_bills_return=[bill1, bill2])

    result = await svc.probe_case('test-case-3', {'document_number': 'INV-001'})

    assert result.result == ReconciliationResult.AMBIGUOUS_MATCH
    assert len(result.matches) >= 2
    assert result.akaunting_write_executed is False
    logged = audit.log_event.call_args[0][0]
    assert logged['result'] == 'AMBIGUOUS_MATCH'


@pytest.mark.asyncio
async def test_probe_error():
    """Exception (non-connection) -> PROBE_ERROR."""
    svc, _, audit = _make_probe_service(side_effect=RuntimeError('unexpected db error'))

    result = await svc.probe_case('test-case-4', {})

    assert result.result == ReconciliationResult.PROBE_ERROR
    assert result.akaunting_write_executed is False
    logged = audit.log_event.call_args[0][0]
    assert logged['result'] == 'PROBE_ERROR'


@pytest.mark.asyncio
async def test_read_only_guaranteed():
    """akaunting_write_executed ist immer False - auch bei Fehler."""
    svc, _, _ = _make_probe_service(side_effect=Exception('oops'))

    result = await svc.probe_case('test-case-5', {'amount': 999.99})

    assert result.akaunting_write_executed is False
    assert result.is_read_only is True
    assert result.actor == 'system:akaunting_probe_v1'


@pytest.mark.asyncio
async def test_audit_event_written():
    """Audit-Eintrag AKAUNTING_PROBE_EXECUTED wird bei jedem Aufruf geschrieben."""
    svc, _, audit = _make_probe_service(search_bills_return=[])

    await svc.probe_case('test-case-6', {'document_number': 'X-1'})

    audit.log_event.assert_awaited_once()
    call_payload = audit.log_event.call_args[0][0]
    assert call_payload['action'] == 'AKAUNTING_PROBE_EXECUTED'
    assert call_payload['case_id'] == 'test-case-6'
    assert 'result' in call_payload
