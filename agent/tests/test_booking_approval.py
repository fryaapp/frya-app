"""Test: Booking approval flow — APPROVE/REJECT/CORRECT/DEFER."""
import pytest
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from app.booking.approval_service import BookingApprovalService
from app.approvals.models import ApprovalRecord
from datetime import datetime


def _make_approval_record(approval_id='appr-001', case_id='case-001', open_item_id='oi-001'):
    return ApprovalRecord(
        approval_id=approval_id,
        case_id=case_id,
        action_type='booking_finalize',
        required_mode='REQUIRE_USER_APPROVAL',
        approval_context={
            'accounting_analysis': {
                'supplier_or_counterparty_hint': {'value': 'Hetzner Online GmbH', 'status': 'FOUND'},
                'amount_summary': {
                    'total_amount': {'value': '6.38', 'status': 'FOUND'},
                    'currency': {'value': 'EUR', 'status': 'FOUND'},
                },
                'invoice_reference_hint': {'value': 'RE-001', 'status': 'FOUND'},
            },
        },
        status='PENDING',
        requested_by='accounting-analyst',
        requested_at=datetime.utcnow(),
        open_item_id=open_item_id,
        policy_refs=[],
    )


def _make_service(booking_result=None, approval_record=None):
    approval_svc = MagicMock()
    approval_svc.repository = MagicMock()
    approval_svc.repository.get = AsyncMock(return_value=approval_record or _make_approval_record())
    approval_svc.decide_approval = AsyncMock()

    open_items_svc = MagicMock()
    open_items_svc.update_status = AsyncMock()

    audit_svc = MagicMock()
    audit_svc.log_event = AsyncMock()

    booking_svc = MagicMock()
    _mock_booking = MagicMock()
    _mock_booking.id = 'booking-42'
    _mock_booking.booking_number = 42
    booking_svc.create_booking_from_case = AsyncMock(
        return_value=_mock_booking,
    )

    return BookingApprovalService(
        approval_service=approval_svc,
        open_items_service=open_items_svc,
        audit_service=audit_svc,
        booking_service=booking_svc,
    )


@pytest.mark.asyncio
async def test_approve_creates_booking():
    """APPROVE -> booking created, open item COMPLETED."""
    svc = _make_service()
    result = await svc.process_response('case-001', 'appr-001', 'APPROVE', 'user')

    assert result['decision'] == 'APPROVE'
    assert result['approval_status'] == 'APPROVED'
    assert result['open_item_status'] == 'COMPLETED'
    assert result['booking_id'] == 'booking-42'
    svc.booking_service.create_booking_from_case.assert_called_once()
    svc.open_items_service.update_status.assert_called_with('oi-001', 'COMPLETED')


@pytest.mark.asyncio
async def test_approve_aliases_ja_buchen():
    """'JA', 'BUCHEN', 'PASST' all map to APPROVE."""
    for alias in ('JA', 'BUCHEN', 'PASST', 'ok'):
        svc = _make_service()
        result = await svc.process_response('case-001', 'appr-001', alias, 'user')
        assert result['decision'] == 'APPROVE', f'Expected APPROVE for {alias}'


@pytest.mark.asyncio
async def test_reject_no_booking_call():
    """REJECT -> no booking call, open item CANCELLED."""
    svc = _make_service()
    result = await svc.process_response('case-001', 'appr-001', 'REJECT', 'user')

    assert result['decision'] == 'REJECT'
    assert result['approval_status'] == 'REJECTED'
    assert result['open_item_status'] == 'CANCELLED'
    assert result['booking_id'] is None
    svc.booking_service.create_booking_from_case.assert_not_called()
    svc.open_items_service.update_status.assert_called_with('oi-001', 'CANCELLED')


@pytest.mark.asyncio
async def test_defer_keeps_pending_approval():
    """DEFER -> open item stays PENDING_APPROVAL, no booking call."""
    svc = _make_service()
    result = await svc.process_response('case-001', 'appr-001', 'DEFER', 'user')

    assert result['decision'] == 'DEFER'
    assert result['approval_status'] == 'PENDING'
    assert result['open_item_status'] == 'PENDING_APPROVAL'
    assert result['booking_id'] is None
    svc.booking_service.create_booking_from_case.assert_not_called()
    svc.open_items_service.update_status.assert_not_called()


@pytest.mark.asyncio
async def test_approve_audit_event_logged():
    """APPROVE -> USER_APPROVED_BOOKING audit event logged."""
    svc = _make_service()
    await svc.process_response('case-001', 'appr-001', 'APPROVE', 'user')

    calls = [call.args[0] for call in svc.audit_service.log_event.call_args_list]
    actions = [c.get('action') for c in calls]
    assert 'USER_APPROVED_BOOKING' in actions


@pytest.mark.asyncio
async def test_reject_audit_event_logged():
    """REJECT -> USER_REJECTED_BOOKING audit event logged."""
    svc = _make_service()
    await svc.process_response('case-001', 'appr-001', 'REJECT', 'user')

    calls = [call.args[0] for call in svc.audit_service.log_event.call_args_list]
    actions = [c.get('action') for c in calls]
    assert 'USER_REJECTED_BOOKING' in actions
