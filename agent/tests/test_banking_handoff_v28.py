"""V1.4 Banking Manual Handoff + Clarification unit tests.

Covers:
- COMPLETED handoff path: outcome_status, audit event, no follow-up item
- RETURNED handoff path: outcome_status, audit event, follow-up clarification item (OPEN)
- Clarification path: outcome_status, audit event, closed item
- Safety: bank_write_executed always False, no_financial_write always True
- Audit event action names correct
- IDs are valid UUIDs
- Existing WAITING_DATA item is closed on handoff
- Existing clarification item is closed on clarification complete
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.banking.models import (
    BankClarificationInput,
    BankManualHandoffDecision,
    BankManualHandoffInput,
)
from app.banking.review_service import BankReconciliationReviewService
from app.open_items.models import OpenItem


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_open_item(
    item_id: str | None = None,
    title: str = '[Banking] Manuelle Abstimmung erforderlich: Transaktion 1 bestätigt',
    status: str = 'WAITING_DATA',
) -> OpenItem:
    return OpenItem(
        item_id=item_id or str(uuid.uuid4()),
        case_id='doc-1',
        title=title,
        description='Pending handoff',
        status=status,  # type: ignore[arg-type]
        source='test',
    )


def _make_clarif_item(
    item_id: str | None = None,
    title: str = '[Banking] Klärung erforderlich: Transaktion 2 abgelehnt',
    status: str = 'OPEN',
) -> OpenItem:
    return OpenItem(
        item_id=item_id or str(uuid.uuid4()),
        case_id='doc-1',
        title=title,
        description='Pending clarification',
        status=status,  # type: ignore[arg-type]
        source='test',
    )


def _make_created_item(item_id: str | None = None, title: str = 'Follow-up') -> OpenItem:
    return OpenItem(
        item_id=item_id or str(uuid.uuid4()),
        case_id='doc-1',
        title=title,
        description='Follow-up item',
        status='OPEN',
        source='test',
    )


def _make_service(
    existing_items: list[OpenItem] | None = None,
    created_item: OpenItem | None = None,
    chronology: list | None = None,
) -> BankReconciliationReviewService:
    audit = AsyncMock()
    audit.log_event = AsyncMock(return_value=None)
    audit.by_case = AsyncMock(return_value=chronology or [])

    oi = AsyncMock()
    oi.list_by_case = AsyncMock(return_value=existing_items or [])
    oi.update_status = AsyncMock(return_value=None)
    oi.create_item = AsyncMock(return_value=created_item or _make_created_item())

    return BankReconciliationReviewService(audit_service=audit, open_items_service=oi)


def _completed_handoff_payload(case_id: str = 'doc-1', tx_id: int = 1) -> BankManualHandoffInput:
    return BankManualHandoffInput(
        case_id=case_id,
        transaction_id=tx_id,
        decision=BankManualHandoffDecision.COMPLETED,
        note='Manuell im Akaunting-UI abgestimmt.',
        decided_by='operator@frya.de',
    )


def _returned_handoff_payload(case_id: str = 'doc-1', tx_id: int = 1) -> BankManualHandoffInput:
    return BankManualHandoffInput(
        case_id=case_id,
        transaction_id=tx_id,
        decision=BankManualHandoffDecision.RETURNED,
        note='Gegenseite konnte Referenz nicht bestätigen.',
        decided_by='operator@frya.de',
    )


def _clarification_payload(case_id: str = 'doc-1', tx_id: int = 2) -> BankClarificationInput:
    return BankClarificationInput(
        case_id=case_id,
        transaction_id=tx_id,
        resolution_note='Auftraggeber hat Zahlung bestätigt. Erneuter Abgleich folgt.',
        decided_by='operator@frya.de',
    )


# ---------------------------------------------------------------------------
# COMPLETED handoff path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_handoff_completed_outcome_status():
    svc = _make_service()
    result = await svc.complete_manual_handoff(_completed_handoff_payload())
    assert result.outcome_status == 'BANK_MANUAL_HANDOFF_COMPLETED'


@pytest.mark.asyncio
async def test_handoff_completed_decision_stored():
    svc = _make_service()
    result = await svc.complete_manual_handoff(_completed_handoff_payload())
    assert result.decision == BankManualHandoffDecision.COMPLETED


@pytest.mark.asyncio
async def test_handoff_completed_no_follow_up_item():
    svc = _make_service()
    result = await svc.complete_manual_handoff(_completed_handoff_payload())
    assert result.follow_up_open_item_id is None


@pytest.mark.asyncio
async def test_handoff_completed_audit_action():
    audit = AsyncMock()
    audit.log_event = AsyncMock(return_value=None)
    audit.by_case = AsyncMock(return_value=[])
    oi = AsyncMock()
    oi.list_by_case = AsyncMock(return_value=[])
    oi.update_status = AsyncMock(return_value=None)
    oi.create_item = AsyncMock(return_value=_make_created_item())

    svc = BankReconciliationReviewService(audit_service=audit, open_items_service=oi)
    await svc.complete_manual_handoff(_completed_handoff_payload())

    call_kwargs = audit.log_event.call_args[0][0]
    assert call_kwargs['action'] == 'BANK_MANUAL_HANDOFF_COMPLETED'
    assert call_kwargs['approval_status'] == 'COMPLETED'


@pytest.mark.asyncio
async def test_handoff_completed_closes_waiting_data_item():
    waiting_item = _make_open_item(status='WAITING_DATA')
    svc = _make_service(existing_items=[waiting_item])
    result = await svc.complete_manual_handoff(_completed_handoff_payload())
    assert result.closed_open_item_id == waiting_item.item_id


# ---------------------------------------------------------------------------
# RETURNED handoff path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_handoff_returned_outcome_status():
    svc = _make_service()
    result = await svc.complete_manual_handoff(_returned_handoff_payload())
    assert result.outcome_status == 'BANK_MANUAL_HANDOFF_RETURNED'


@pytest.mark.asyncio
async def test_handoff_returned_creates_clarification_item():
    created = _make_created_item(title='[Banking] Klärung nach Rückgabe: Transaktion 1')
    svc = _make_service(created_item=created)
    result = await svc.complete_manual_handoff(_returned_handoff_payload())
    assert result.follow_up_open_item_id == created.item_id


@pytest.mark.asyncio
async def test_handoff_returned_audit_action():
    audit = AsyncMock()
    audit.log_event = AsyncMock(return_value=None)
    audit.by_case = AsyncMock(return_value=[])
    oi = AsyncMock()
    oi.list_by_case = AsyncMock(return_value=[])
    oi.update_status = AsyncMock(return_value=None)
    oi.create_item = AsyncMock(return_value=_make_created_item())

    svc = BankReconciliationReviewService(audit_service=audit, open_items_service=oi)
    await svc.complete_manual_handoff(_returned_handoff_payload())

    call_kwargs = audit.log_event.call_args[0][0]
    assert call_kwargs['action'] == 'BANK_MANUAL_HANDOFF_RETURNED'
    assert call_kwargs['approval_status'] == 'RETURNED'


# ---------------------------------------------------------------------------
# Clarification path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_clarification_completed_outcome_status():
    svc = _make_service()
    result = await svc.complete_clarification(_clarification_payload())
    assert result.outcome_status == 'BANK_CLARIFICATION_COMPLETED'


@pytest.mark.asyncio
async def test_clarification_completed_audit_action():
    audit = AsyncMock()
    audit.log_event = AsyncMock(return_value=None)
    audit.by_case = AsyncMock(return_value=[])
    oi = AsyncMock()
    oi.list_by_case = AsyncMock(return_value=[])
    oi.update_status = AsyncMock(return_value=None)
    oi.create_item = AsyncMock(return_value=_make_created_item())

    svc = BankReconciliationReviewService(audit_service=audit, open_items_service=oi)
    await svc.complete_clarification(_clarification_payload())

    call_kwargs = audit.log_event.call_args[0][0]
    assert call_kwargs['action'] == 'BANK_CLARIFICATION_COMPLETED'
    assert call_kwargs['approval_status'] == 'COMPLETED'


@pytest.mark.asyncio
async def test_clarification_closes_open_item():
    clarif_item = _make_clarif_item(status='OPEN')
    svc = _make_service(existing_items=[clarif_item])
    result = await svc.complete_clarification(_clarification_payload())
    assert result.closed_open_item_id == clarif_item.item_id


@pytest.mark.asyncio
async def test_clarification_resolution_note_stored():
    svc = _make_service()
    payload = _clarification_payload()
    result = await svc.complete_clarification(payload)
    assert result.resolution_note == payload.resolution_note


# ---------------------------------------------------------------------------
# Safety invariants — always hold for all paths
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize('payload_fn,method', [
    (_completed_handoff_payload, 'complete_manual_handoff'),
    (_returned_handoff_payload, 'complete_manual_handoff'),
    (_clarification_payload, 'complete_clarification'),
])
async def test_safety_bank_write_executed_false(payload_fn, method):
    svc = _make_service()
    result = await getattr(svc, method)(payload_fn())
    assert result.bank_write_executed is False, 'bank_write_executed must be False'


@pytest.mark.asyncio
@pytest.mark.parametrize('payload_fn,method', [
    (_completed_handoff_payload, 'complete_manual_handoff'),
    (_returned_handoff_payload, 'complete_manual_handoff'),
    (_clarification_payload, 'complete_clarification'),
])
async def test_safety_no_financial_write_true(payload_fn, method):
    svc = _make_service()
    result = await getattr(svc, method)(payload_fn())
    assert result.no_financial_write is True, 'no_financial_write must be True'


@pytest.mark.asyncio
@pytest.mark.parametrize('payload_fn,method,id_field', [
    (_completed_handoff_payload, 'complete_manual_handoff', 'handoff_id'),
    (_returned_handoff_payload, 'complete_manual_handoff', 'handoff_id'),
    (_clarification_payload, 'complete_clarification', 'clarification_id'),
])
async def test_result_id_is_uuid(payload_fn, method, id_field):
    svc = _make_service()
    result = await getattr(svc, method)(payload_fn())
    raw = getattr(result, id_field)
    parsed = uuid.UUID(raw)
    assert str(parsed) == raw


@pytest.mark.asyncio
@pytest.mark.parametrize('payload_fn,method', [
    (_completed_handoff_payload, 'complete_manual_handoff'),
    (_returned_handoff_payload, 'complete_manual_handoff'),
    (_clarification_payload, 'complete_clarification'),
])
async def test_audit_event_id_is_uuid(payload_fn, method):
    svc = _make_service()
    result = await getattr(svc, method)(payload_fn())
    parsed = uuid.UUID(result.audit_event_id)
    assert str(parsed) == result.audit_event_id
