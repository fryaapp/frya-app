from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from app.accounting_analysis.akaunting_reconciliation_service import AkauntingReconciliationService
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
