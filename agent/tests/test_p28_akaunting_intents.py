"""P-28 tests: Akaunting connector extensions + intent handler responses + flow state."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch


# ── Connector tests ──────────────────────────────────────────────────────────

def test_connector_has_create_invoice_draft():
    from app.connectors.accounting_akaunting import AkauntingConnector
    c = AkauntingConnector(base_url='http://test', email='a', password='b')
    assert hasattr(c, 'create_invoice_draft')


def test_connector_has_get_open_items_summary():
    from app.connectors.accounting_akaunting import AkauntingConnector
    c = AkauntingConnector(base_url='http://test', email='a', password='b')
    assert hasattr(c, 'get_open_items_summary')


def test_connector_has_get_monthly_summary():
    from app.connectors.accounting_akaunting import AkauntingConnector
    c = AkauntingConnector(base_url='http://test', email='a', password='b')
    assert hasattr(c, 'get_monthly_summary')


# ── Response builder tests ───────────────────────────────────────────────────

def test_response_financial_query():
    from app.telegram.communicator.response_builder import build_response
    text, code = build_response(
        intent='FINANCIAL_QUERY',
        guardrail_passed=True,
        ctx=None,
        # user_text='offene rechnungen',
    )
    assert 'Finanzdaten' in text or 'Akaunting' in text
    assert code == 'COMMUNICATOR_REPLY_FINANCIAL_QUERY'


def test_response_create_invoice():
    from app.telegram.communicator.response_builder import build_response
    text, code = build_response(
        intent='CREATE_INVOICE',
        guardrail_passed=True,
        ctx=None,
        # user_text='erstelle eine rechnung',
    )
    assert 'Kundenname' in text
    assert code == 'COMMUNICATOR_REPLY_CREATE_INVOICE'


def test_response_export_request():
    from app.telegram.communicator.response_builder import build_response
    text, code = build_response(
        intent='EXPORT_REQUEST',
        guardrail_passed=True,
        ctx=None,
        # user_text='datev export',
    )
    assert 'Entwicklung' in text
    assert code == 'COMMUNICATOR_REPLY_EXPORT_REQUEST'


def test_response_booking_request():
    from app.telegram.communicator.response_builder import build_response
    text, code = build_response(
        intent='BOOKING_REQUEST',
        guardrail_passed=True,
        ctx=None,
        # user_text='bitte buchen',
    )
    assert 'Buchungsvorschlag' in text
    assert code == 'COMMUNICATOR_REPLY_BOOKING_REQUEST'


def test_response_reminder_request():
    from app.telegram.communicator.response_builder import build_response
    text, code = build_response(
        intent='REMINDER_REQUEST',
        guardrail_passed=True,
        ctx=None,
        # user_text='erinnere mich',
    )
    assert 'Erinnerung' in text
    assert code == 'COMMUNICATOR_REPLY_REMINDER_REQUEST'


def test_response_create_customer():
    from app.telegram.communicator.response_builder import build_response
    text, code = build_response(
        intent='CREATE_CUSTOMER',
        guardrail_passed=True,
        ctx=None,
        # user_text='kunden anlegen',
    )
    assert 'Kontakt' in text or 'Kunden' in text
    assert code == 'COMMUNICATOR_REPLY_CREATE_CUSTOMER'


# ── Flow state tests ─────────────────────────────────────────────────────────

def test_flow_state_set_get_clear():
    from app.telegram.communicator.memory.user_store import (
        set_active_flow, get_active_flow, clear_active_flow,
    )
    set_active_flow('chat-123', {'type': 'CREATE_INVOICE', 'step': 1})
    flow = get_active_flow('chat-123')
    assert flow is not None
    assert flow['type'] == 'CREATE_INVOICE'
    assert flow['step'] == 1

    clear_active_flow('chat-123')
    assert get_active_flow('chat-123') is None


def test_flow_state_not_set():
    from app.telegram.communicator.memory.user_store import get_active_flow
    assert get_active_flow('nonexistent-chat') is None


def test_existing_intents_unaffected():
    """Verify existing response_builder intents still work."""
    from app.telegram.communicator.response_builder import build_response
    text, code = build_response(
        intent='GREETING', ctx=None, guardrail_passed=True,
    )
    assert 'FRYA' in text
    assert code == 'COMMUNICATOR_REPLY_GREETING'
