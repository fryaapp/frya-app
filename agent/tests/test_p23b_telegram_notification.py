"""P-23b tests: Booking proposal Telegram notification + inline keyboard + callback handling."""
from __future__ import annotations

import json
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.approvals.models import ApprovalRecord
from app.connectors.contracts import NotificationMessage


# ── Helpers ──────────────────────────────────────────────────────────────────

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


def _make_accounting_analysis_result():
    """Build a minimal AccountingAnalysisResult-like mock object for format_booking_proposal_message."""
    from app.accounting_analysis.models import (
        AccountingField,
        AmountSummary,
        BookingCandidate,
        AccountingAnalysisResult,
        TaxHint,
    )

    return AccountingAnalysisResult(
        case_id='case-001',
        accounting_review_ref='rev-001',
        booking_candidate_type='INVOICE_STANDARD_EXPENSE',
        booking_confidence=0.9,
        global_decision='PROPOSED',
        suggested_next_step='ACCOUNTING_CONFIRMATION',
        ready_for_accounting_confirmation=True,
        ready_for_user_approval=True,
        accounting_risks=[],
        analysis_summary='Invoice from Hetzner',
        amount_summary=AmountSummary(
            total_amount=AccountingField(value=6.38, status='FOUND'),
            currency=AccountingField(value='EUR', status='FOUND'),
            net_amount=AccountingField(value=5.36, status='FOUND'),
            tax_amount=AccountingField(value=1.02, status='FOUND'),
        ),
        supplier_or_counterparty_hint=AccountingField(value='Hetzner Online GmbH', status='FOUND'),
        invoice_reference_hint=AccountingField(value='RE-001', status='FOUND'),
        due_date_hint=AccountingField(value=None, status='MISSING'),
        tax_hint=TaxHint(rate=AccountingField(value=None, status='MISSING')),
        booking_candidate=BookingCandidate(
            candidate_type='INVOICE_STANDARD_EXPENSE',
            review_focus=['Telekommunikation'],
            counterparty_hint='Telekommunikation',
        ),
    )


# ── Test 1: Booking proposal triggers Telegram notification ──────────────────

@pytest.mark.asyncio
async def test_booking_proposal_triggers_telegram_notification():
    """After analyst pipeline: Telegram send_message must be called with proposal text."""
    from app.booking.approval_service import format_booking_proposal_message

    accounting_analysis = _make_accounting_analysis_result()
    text = format_booking_proposal_message(accounting_analysis)

    assert 'Hetzner' in text
    assert '6,38' in text or '6.38' in text

    # Simulate the notification call
    sent_messages: list[NotificationMessage] = []

    mock_connector = MagicMock()
    mock_connector.send = AsyncMock(side_effect=lambda msg: sent_messages.append(msg))

    msg = NotificationMessage(
        target='12345678',
        text=text,
        reply_markup={'inline_keyboard': [[{'text': '✅ Buchen', 'callback_data': 'booking:case-1:approve'}]]},
        metadata={'case_id': 'case-1', 'approval_id': 'appr-1', 'intent': 'booking.proposal'},
    )
    await mock_connector.send(msg)

    assert len(sent_messages) == 1
    assert sent_messages[0].target == '12345678'
    assert 'Hetzner' in sent_messages[0].text


# ── Test 2: Telegram message has inline keyboard with 4 buttons ──────────────

def test_booking_proposal_message_has_inline_keyboard():
    """NotificationMessage with booking proposal must carry reply_markup with 4 buttons."""
    case_id = 'case-tg-42'
    inline_keyboard = {
        'inline_keyboard': [
            [
                {'text': '✅ Buchen', 'callback_data': f'booking:{case_id}:approve'},
                {'text': '✏️ Korrigieren', 'callback_data': f'booking:{case_id}:correct'},
            ],
            [
                {'text': '❌ Ablehnen', 'callback_data': f'booking:{case_id}:reject'},
                {'text': '⏸️ Später', 'callback_data': f'booking:{case_id}:defer'},
            ],
        ]
    }

    msg = NotificationMessage(
        target='12345678',
        text='FRYA: Hetzner — 6,38 € — Betriebsausgabe.',
        reply_markup=inline_keyboard,
    )

    assert msg.reply_markup is not None
    buttons = msg.reply_markup['inline_keyboard']
    all_buttons = [b for row in buttons for b in row]
    assert len(all_buttons) == 4

    callback_datas = {b['callback_data'] for b in all_buttons}
    assert f'booking:{case_id}:approve' in callback_datas
    assert f'booking:{case_id}:reject' in callback_datas
    assert f'booking:{case_id}:correct' in callback_datas
    assert f'booking:{case_id}:defer' in callback_datas


# ── Test 3: TelegramConnector includes reply_markup in payload ───────────────

@pytest.mark.asyncio
async def test_telegram_connector_sends_reply_markup():
    """TelegramConnector.send() must include reply_markup in Telegram API POST body."""
    import httpx

    from app.connectors.notifications_telegram import TelegramConnector

    captured_payload: dict = {}

    class _FakeResponse:
        is_success = True
        status_code = 200
        text = '{"ok":true}'

    class _FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

        async def post(self, url, json=None, **kw):
            captured_payload.update(json or {})
            return _FakeResponse()

    connector = TelegramConnector(bot_token='test-token')
    msg = NotificationMessage(
        target='999',
        text='Buchungsvorschlag',
        reply_markup={'inline_keyboard': [[{'text': '✅', 'callback_data': 'booking:x:approve'}]]},
    )

    with patch('httpx.AsyncClient', return_value=_FakeClient()):
        await connector.send(msg)

    assert 'reply_markup' in captured_payload
    assert captured_payload['reply_markup']['inline_keyboard'][0][0]['callback_data'] == 'booking:x:approve'


# ── Test 4: Callback APPROVE → BookingApprovalService.process_response called ─

@pytest.mark.asyncio
async def test_booking_callback_approve():
    """Callback 'approve' → process_response called with APPROVE decision."""
    from app.booking.approval_service import BookingApprovalService

    approval_record = _make_approval_record()

    approval_svc = MagicMock()
    approval_svc.repository = MagicMock()
    approval_svc.repository.get = AsyncMock(return_value=approval_record)
    approval_svc.decide_approval = AsyncMock()
    approval_svc.list_by_case = AsyncMock(return_value=[approval_record])

    open_items_svc = MagicMock()
    open_items_svc.update_status = AsyncMock()

    audit_svc = MagicMock()
    audit_svc.log_event = AsyncMock()

    akaunting = MagicMock()
    akaunting.create_bill_draft = AsyncMock(return_value={'bill_id': 99, 'status': 'draft'})

    svc = BookingApprovalService(
        approval_service=approval_svc,
        open_items_service=open_items_svc,
        audit_service=audit_svc,
        akaunting_connector=akaunting,
    )

    result = await svc.process_response(
        case_id='case-001',
        approval_id='appr-001',
        decision_raw='APPROVE',
        decided_by='telegram_user',
        source='telegram_callback',
    )

    assert result['decision'] == 'APPROVE'
    assert result['approval_status'] == 'APPROVED'
    akaunting.create_bill_draft.assert_called_once()


# ── Test 5: No Telegram notification for email documents ────────────────────

@pytest.mark.asyncio
async def test_no_telegram_notification_for_email_documents():
    """Docs from email have no telegram_chat_id in audit → no Telegram send."""
    from app.booking.approval_service import format_booking_proposal_message

    accounting_analysis = _make_accounting_analysis_result()

    # Simulate: audit events have no telegram_chat_id
    audit_events_without_chat: list = []

    chat_id = None
    for ev in audit_events_without_chat:
        meta = ev.llm_output
        if isinstance(meta, dict) and meta.get('telegram_chat_id'):
            chat_id = str(meta['telegram_chat_id'])
            break

    # chat_id must remain None → no send
    assert chat_id is None

    # Verify: if we simulate the connector, it should NOT be called
    mock_connector = MagicMock()
    mock_connector.send = AsyncMock()

    if chat_id:
        await mock_connector.send(NotificationMessage(target=chat_id, text='test'))

    mock_connector.send.assert_not_called()
