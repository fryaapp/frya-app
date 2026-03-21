"""Paket 54 – Telegram Kommunikator V0 tests.

Covers:
- Intent classification: GREETING, STATUS_OVERVIEW, NEEDS_FROM_USER,
  DOCUMENT_ARRIVAL_CHECK, GENERAL_SAFE_HELP, LAST_CASE_EXPLANATION,
  UNSUPPORTED_OR_RISKY, None (fall-through)
- Guardrail: safe intents pass, UNSUPPORTED_OR_RISKY blocked
- Response builder: FRYA: prefix, correct response types, no context fallback
- Service try_handle_turn: handled/fallthrough/risky, audit event logged
- No audit for fall-through (zero side-effects on unrecognized text)
- Webhook end-to-end: COMMUNICATOR_HANDLED, COMMUNICATOR_GUARDRAIL_TRIGGERED,
  ACCEPTED_TO_INBOX (backward compat for unrecognized text)
- Audit/Inspect consistency after communicator turn
"""
from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from app.telegram.communicator.guardrail import check_guardrail
from app.telegram.communicator.intent_classifier import classify_intent
from app.telegram.communicator.models import CommunicatorContextResolution
from app.telegram.communicator.response_builder import build_response
from tests.test_api_surface import (
    _build_app,
    _build_users_json,
    _clear_caches,
    _login_admin,
    _prepare_data,
)

# ─────────────────────────────────────────────────────────────────────────────
# Test helpers
# ─────────────────────────────────────────────────────────────────────────────

_TG_HEADERS = {'x-telegram-bot-api-secret-token': 'tg-secret'}


def _configure_env(monkeypatch, tmp_path):
    _prepare_data(tmp_path)
    monkeypatch.setenv('FRYA_DATABASE_URL', 'memory://db')
    monkeypatch.setenv('FRYA_REDIS_URL', 'memory://redis')
    monkeypatch.setenv('FRYA_DATA_DIR', str(tmp_path))
    monkeypatch.setenv('FRYA_RULES_DIR', str(tmp_path / 'rules'))
    monkeypatch.setenv('FRYA_VERFAHRENSDOKU_DIR', str(tmp_path / 'verfahrensdoku'))
    monkeypatch.setenv('FRYA_PAPERLESS_BASE_URL', 'http://paperless')
    monkeypatch.setenv('FRYA_AKAUNTING_BASE_URL', 'http://akaunting')
    monkeypatch.setenv('FRYA_N8N_BASE_URL', 'http://n8n')
    monkeypatch.setenv('FRYA_TELEGRAM_WEBHOOK_SECRET', 'tg-secret')
    monkeypatch.setenv('FRYA_TELEGRAM_ALLOWED_CHAT_IDS', '-5200036710')
    monkeypatch.setenv('FRYA_TELEGRAM_ALLOWED_DIRECT_CHAT_IDS', '1310959044')
    monkeypatch.setenv('FRYA_TELEGRAM_ALLOWED_USER_IDS', '1310959044')
    monkeypatch.setenv('FRYA_AUTH_USERS_JSON', _build_users_json())
    monkeypatch.setenv('FRYA_AUTH_SESSION_SECRET', 'test-secret')
    monkeypatch.setenv('FRYA_AUTH_COOKIE_SECURE', 'false')
    _clear_caches()


def _tg_text(update_id: int, message_id: int, text: str, chat_id: int = -5200036710) -> dict:
    return {
        'update_id': update_id,
        'message': {
            'message_id': message_id,
            'chat': {'id': chat_id, 'type': 'group' if chat_id < 0 else 'private'},
            'from': {'id': 1310959044, 'username': 'maze'},
            'text': text,
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# Async mock services for service-level tests
# ─────────────────────────────────────────────────────────────────────────────

class _MockAuditService:
    def __init__(self):
        self.events: list[dict] = []

    async def log_event(self, event: dict) -> None:
        self.events.append(event)

    async def by_case(self, case_id: str, limit: int = 200) -> list:
        return []


class _MockClarificationService:
    async def latest_by_case(self, case_id: str):
        return None


class _MockOpenItemsService:
    async def list_by_case(self, case_id: str) -> list:
        return []


def _run(coro):
    return asyncio.run(coro)


# ═════════════════════════════════════════════════════════════════════════════
# TEIL 1 – classify_intent unit tests
# ═════════════════════════════════════════════════════════════════════════════

def test_classify_greeting_hallo():
    assert classify_intent('Hallo') == 'GREETING'


def test_classify_greeting_hi():
    assert classify_intent('hi') == 'GREETING'


def test_classify_greeting_phrase():
    assert classify_intent('Guten Morgen') == 'GREETING'


def test_classify_greeting_hi_frya():
    assert classify_intent('Hi Frya') == 'GREETING'


def test_classify_status_overview_phrase():
    # "aktueller stand" is in _STATUS_PHRASES, not in V1 shortlist
    assert classify_intent('Aktueller Stand bitte') == 'STATUS_OVERVIEW'


def test_classify_status_single_token():
    # 'status' is STATUS_OVERVIEW at classifier level
    # (V1 intercepts it in webhook context before communicator runs)
    assert classify_intent('status') == 'STATUS_OVERVIEW'


def test_classify_needs_from_user():
    assert classify_intent('Was brauchst du noch von mir?') == 'NEEDS_FROM_USER'


def test_classify_needs_was_fehlt():
    assert classify_intent('Was fehlt noch?') == 'NEEDS_FROM_USER'


def test_classify_document_arrival_check():
    assert classify_intent('Ist das Dokument angekommen?') == 'DOCUMENT_ARRIVAL_CHECK'


def test_classify_document_arrival_hat_geklappt():
    assert classify_intent('Hat das geklappt?') == 'DOCUMENT_ARRIVAL_CHECK'


def test_classify_general_safe_help():
    assert classify_intent('Wie funktioniert das?') == 'GENERAL_SAFE_HELP'


def test_classify_last_case_explanation():
    assert classify_intent('Was ist mein Fall?') == 'LAST_CASE_EXPLANATION'


def test_classify_risky_zahlung_frei():
    assert classify_intent('Mach die Zahlung frei') == 'UNSUPPORTED_OR_RISKY'


def test_classify_risky_freigabe():
    assert classify_intent('Freigabe erteilen bitte') == 'UNSUPPORTED_OR_RISKY'


def test_classify_risky_loeschen():
    assert classify_intent('Loesche meinen Vorgang') == 'UNSUPPORTED_OR_RISKY'


def test_classify_risky_overrides_greeting_pattern():
    # Risky substring must override even if greeting token is present
    assert classify_intent('Hallo bitte Zahlung freigeben') == 'UNSUPPORTED_OR_RISKY'


def test_classify_unrecognized_returns_general_conversation():
    assert classify_intent('Irgendwas komplett zufaelliges ohne muster') == 'GENERAL_CONVERSATION'


def test_classify_operator_prose_returns_general_conversation():
    assert classify_intent('Bitte pruefe meinen letzten Eingang') == 'GENERAL_CONVERSATION'


def test_classify_empty_returns_none():
    assert classify_intent('') is None


def test_classify_whitespace_only_returns_none():
    assert classify_intent('   ') is None


def test_classify_general_conversation():
    """Nachrichten die keinen spezifischen Intent treffen → GENERAL_CONVERSATION"""
    assert classify_intent('Ich habe heute grosses vor') == 'GENERAL_CONVERSATION'
    assert classify_intent('Das Wetter ist schoen heute') == 'GENERAL_CONVERSATION'
    assert classify_intent('Danke fuer die Info') == 'GENERAL_CONVERSATION'
    assert classify_intent('Hmm okay') == 'GENERAL_CONVERSATION'


def test_classify_extended_greeting():
    assert classify_intent('Bist du da') == 'GREETING'
    assert classify_intent('Guten Morgen') == 'GREETING'


def test_classify_extended_status():
    assert classify_intent('Was liegt an') == 'STATUS_OVERVIEW'
    assert classify_intent('Was steht an') == 'STATUS_OVERVIEW'
    assert classify_intent('Was gibts neues') == 'STATUS_OVERVIEW'


def test_classify_extended_last_case():
    assert classify_intent('Was war die letzte Rechnung') == 'LAST_CASE_EXPLANATION'
    assert classify_intent('Warum ist er noch nicht geprueft') == 'LAST_CASE_EXPLANATION'
    assert classify_intent('Sag mir mal was die letzte Rechnung war') == 'LAST_CASE_EXPLANATION'


def test_classify_never_returns_none_for_safe_input():
    """classify_intent darf fuer nicht-riskanten Input NIEMALS None zurueckgeben."""
    safe_inputs = [
        'Hallo', 'Was liegt an', 'Ich habe heute grosses vor',
        'Sag mir was die letzte Rechnung war', 'Bist du da',
        'Danke', 'Okay cool', 'Wie geht es dir', 'Hmm',
        'Kannst du mir helfen', 'Was machst du so',
    ]
    for text in safe_inputs:
        result = classify_intent(text)
        assert result is not None, f"classify_intent('{text}') returned None — darf nicht passieren"


# ═════════════════════════════════════════════════════════════════════════════
# TEIL 2 – guardrail unit tests
# ═════════════════════════════════════════════════════════════════════════════

def test_guardrail_passes_greeting():
    passed, reason = check_guardrail('GREETING')
    assert passed is True
    assert reason is None


def test_guardrail_passes_status_overview():
    passed, reason = check_guardrail('STATUS_OVERVIEW')
    assert passed is True
    assert reason is None


def test_guardrail_passes_needs_from_user():
    passed, reason = check_guardrail('NEEDS_FROM_USER')
    assert passed is True


def test_guardrail_passes_document_arrival_check():
    passed, reason = check_guardrail('DOCUMENT_ARRIVAL_CHECK')
    assert passed is True


def test_guardrail_passes_general_safe_help():
    passed, reason = check_guardrail('GENERAL_SAFE_HELP')
    assert passed is True


def test_guardrail_blocks_unsupported_or_risky():
    passed, reason = check_guardrail('UNSUPPORTED_OR_RISKY')
    assert passed is False
    assert reason is not None
    assert len(reason) > 0


# ═════════════════════════════════════════════════════════════════════════════
# TEIL 3 – build_response unit tests
# ═════════════════════════════════════════════════════════════════════════════

def test_build_response_greeting_type_and_frya_prefix():
    text, rtype = build_response('GREETING', None, guardrail_passed=True)
    assert rtype == 'COMMUNICATOR_REPLY_GREETING'
    assert text.startswith('FRYA:')


def test_build_response_safe_limit_when_guardrail_fails():
    text, rtype = build_response('UNSUPPORTED_OR_RISKY', None, guardrail_passed=False)
    assert rtype == 'COMMUNICATOR_REPLY_SAFE_LIMIT'
    assert text.startswith('FRYA:')


def test_build_response_safe_limit_for_unsupported_intent_regardless_of_guardrail():
    # UNSUPPORTED_OR_RISKY intent always yields safe limit (redundant safety)
    text, rtype = build_response('UNSUPPORTED_OR_RISKY', None, guardrail_passed=True)
    assert rtype == 'COMMUNICATOR_REPLY_SAFE_LIMIT'


def test_build_response_status_no_context():
    text, rtype = build_response('STATUS_OVERVIEW', None, guardrail_passed=True)
    assert rtype == 'COMMUNICATOR_REPLY_STATUS'
    assert text.startswith('FRYA:')
    assert 'keinen' in text.lower() or 'kein' in text.lower()


def test_build_response_status_with_context_found_includes_ref():
    ctx = CommunicatorContextResolution(
        resolution_status='FOUND',
        resolved_case_ref='case-ref-001',
        resolved_document_ref='doc-xyz',
    )
    text, rtype = build_response('STATUS_OVERVIEW', ctx, guardrail_passed=True)
    assert rtype == 'COMMUNICATOR_REPLY_STATUS'
    assert 'case-ref-001' in text


def test_build_response_status_with_open_clarification():
    ctx = CommunicatorContextResolution(
        resolution_status='FOUND',
        resolved_case_ref='case-ref-002',
        resolved_clarification_ref='clar-abc',
    )
    text, rtype = build_response('STATUS_OVERVIEW', ctx, guardrail_passed=True)
    assert rtype == 'COMMUNICATOR_REPLY_STATUS'
    assert 'Rueckfrage' in text or 'rueckfrage' in text.lower()


def test_build_response_needs_no_context():
    text, rtype = build_response('NEEDS_FROM_USER', None, guardrail_passed=True)
    assert rtype == 'COMMUNICATOR_REPLY_NEEDS'
    assert text.startswith('FRYA:')


def test_build_response_document_arrival_no_context():
    text, rtype = build_response('DOCUMENT_ARRIVAL_CHECK', None, guardrail_passed=True)
    assert rtype == 'COMMUNICATOR_REPLY_EXPLANATION'
    assert text.startswith('FRYA:')


def test_build_response_document_arrival_with_doc_ref():
    ctx = CommunicatorContextResolution(
        resolution_status='FOUND',
        resolved_document_ref='doc-ref-42',
    )
    text, rtype = build_response('DOCUMENT_ARRIVAL_CHECK', ctx, guardrail_passed=True)
    assert rtype == 'COMMUNICATOR_REPLY_EXPLANATION'
    assert 'doc-ref-42' in text


def test_build_response_safe_help():
    text, rtype = build_response('GENERAL_SAFE_HELP', None, guardrail_passed=True)
    assert rtype == 'COMMUNICATOR_REPLY_SAFE_HELP'
    assert 'FRYA' in text


def test_build_response_unknown_intent_fallback():
    # None intent with guardrail passed → safe limit fallback
    text, rtype = build_response(None, None, guardrail_passed=True)
    assert rtype == 'COMMUNICATOR_REPLY_SAFE_LIMIT'


# ═════════════════════════════════════════════════════════════════════════════
# TEIL 4 – service try_handle_turn unit tests
# ═════════════════════════════════════════════════════════════════════════════

def _make_normalized(text: str, update_id: int = 1, message_id: int = 1):
    """Build a minimal TelegramNormalizedIngressMessage for testing."""
    from app.telegram.models import TelegramActor, TelegramNormalizedIngressMessage
    return TelegramNormalizedIngressMessage(
        event_id=f'test-evt-{update_id}',
        telegram_update_ref=f'upd-{update_id}',
        telegram_message_ref=f'msg-{message_id}',
        telegram_chat_ref='chat--5200036710',
        text=text,
        actor=TelegramActor(chat_id='-5200036710', sender_id='1310959044', sender_username='maze'),
    )


def test_service_try_handle_turn_greeting():
    from app.telegram.communicator.service import TelegramCommunicatorService

    svc = TelegramCommunicatorService()
    audit = _MockAuditService()
    result = _run(svc.try_handle_turn(
        _make_normalized('Hallo', update_id=101),
        'case-comm-001',
        audit_service=audit,
        open_items_service=_MockOpenItemsService(),
        clarification_service=_MockClarificationService(),
    ))

    assert result is not None
    assert result.handled is True
    assert result.turn.intent == 'GREETING'
    assert result.routing_status == 'COMMUNICATOR_HANDLED'
    assert result.turn.guardrail_passed is True
    assert result.reply_text.startswith('FRYA:')


def test_service_try_handle_turn_unrecognized_returns_general_conversation():
    """Unrecognized text is now handled as GENERAL_CONVERSATION — never falls through."""
    from app.telegram.communicator.service import TelegramCommunicatorService

    svc = TelegramCommunicatorService()
    audit = _MockAuditService()
    result = _run(svc.try_handle_turn(
        _make_normalized('absolut zufaelliger text xyz 123', update_id=102),
        'case-comm-002',
        audit_service=audit,
        open_items_service=_MockOpenItemsService(),
        clarification_service=_MockClarificationService(),
    ))

    assert result is not None
    assert result.turn.intent == 'GENERAL_CONVERSATION'
    assert result.handled is True


def test_service_audit_logged_for_general_conversation():
    """GENERAL_CONVERSATION must produce exactly one audit event."""
    from app.telegram.communicator.service import TelegramCommunicatorService

    svc = TelegramCommunicatorService()
    audit = _MockAuditService()
    _run(svc.try_handle_turn(
        _make_normalized('Das hier passt keinem Muster', update_id=103),
        'case-comm-003',
        audit_service=audit,
        open_items_service=_MockOpenItemsService(),
        clarification_service=_MockClarificationService(),
    ))

    assert len(audit.events) == 1
    assert audit.events[0]['action'] == 'COMMUNICATOR_TURN_PROCESSED'


def test_service_try_handle_turn_risky_sets_guardrail_triggered():
    from app.telegram.communicator.service import TelegramCommunicatorService

    svc = TelegramCommunicatorService()
    audit = _MockAuditService()
    result = _run(svc.try_handle_turn(
        _make_normalized('Mach die Zahlung frei', update_id=104),
        'case-comm-004',
        audit_service=audit,
        open_items_service=_MockOpenItemsService(),
        clarification_service=_MockClarificationService(),
    ))

    assert result is not None
    assert result.routing_status == 'COMMUNICATOR_GUARDRAIL_TRIGGERED'
    assert result.turn.intent == 'UNSUPPORTED_OR_RISKY'
    assert result.turn.guardrail_passed is False
    assert result.reply_text.startswith('FRYA:')


def test_service_audit_logged_for_handled_turn():
    """COMMUNICATOR_TURN_PROCESSED must be logged for every handled turn."""
    from app.telegram.communicator.service import TelegramCommunicatorService

    svc = TelegramCommunicatorService()
    audit = _MockAuditService()
    _run(svc.try_handle_turn(
        _make_normalized('Was brauchst du noch von mir?', update_id=105),
        'case-comm-005',
        audit_service=audit,
        open_items_service=_MockOpenItemsService(),
        clarification_service=_MockClarificationService(),
    ))

    assert len(audit.events) == 1
    ev = audit.events[0]
    assert ev['action'] == 'COMMUNICATOR_TURN_PROCESSED'
    assert ev['agent_name'] == 'frya-communicator'
    assert ev['result'] == 'NEEDS_FROM_USER'
    assert ev['case_id'] == 'case-comm-005'


def test_service_audit_logged_for_risky_turn():
    """Risky/guardrail-triggered turns must also be audited."""
    from app.telegram.communicator.service import TelegramCommunicatorService

    svc = TelegramCommunicatorService()
    audit = _MockAuditService()
    _run(svc.try_handle_turn(
        _make_normalized('Zahlung freigeben', update_id=106),
        'case-comm-006',
        audit_service=audit,
        open_items_service=_MockOpenItemsService(),
        clarification_service=_MockClarificationService(),
    ))

    assert len(audit.events) == 1
    ev = audit.events[0]
    assert ev['action'] == 'COMMUNICATOR_TURN_PROCESSED'
    assert ev['result'] == 'UNSUPPORTED_OR_RISKY'


def test_service_turn_ref_is_unique_per_call():
    from app.telegram.communicator.service import TelegramCommunicatorService

    svc = TelegramCommunicatorService()
    audit = _MockAuditService()

    r1 = _run(svc.try_handle_turn(
        _make_normalized('Hallo', update_id=107),
        'case-comm-007',
        audit_service=audit,
        open_items_service=_MockOpenItemsService(),
        clarification_service=_MockClarificationService(),
    ))
    r2 = _run(svc.try_handle_turn(
        _make_normalized('Hallo', update_id=108),
        'case-comm-008',
        audit_service=audit,
        open_items_service=_MockOpenItemsService(),
        clarification_service=_MockClarificationService(),
    ))

    assert r1.turn.communicator_turn_ref != r2.turn.communicator_turn_ref


# ═════════════════════════════════════════════════════════════════════════════
# TEIL 5 – webhook end-to-end tests
# ═════════════════════════════════════════════════════════════════════════════

def test_webhook_greeting_communicator_handled(tmp_path, monkeypatch):
    _configure_env(monkeypatch, tmp_path)
    app = _build_app()

    with TestClient(app) as client:
        response = client.post(
            '/webhooks/telegram',
            json=_tg_text(3001, 301, 'Hallo'),
            headers=_TG_HEADERS,
        )
        assert response.status_code == 200
        body = response.json()
        assert body['status'] == 'accepted'
        assert body['routing_status'] == 'COMMUNICATOR_HANDLED'
        assert body['intent'] == 'communicator.greeting'
        assert body['command_status'] == 'COMMUNICATOR_HANDLED'


def test_webhook_risky_request_guardrail_triggered(tmp_path, monkeypatch):
    _configure_env(monkeypatch, tmp_path)
    app = _build_app()

    with TestClient(app) as client:
        response = client.post(
            '/webhooks/telegram',
            json=_tg_text(3002, 302, 'Mach die Zahlung frei'),
            headers=_TG_HEADERS,
        )
        assert response.status_code == 200
        body = response.json()
        assert body['status'] == 'accepted'
        assert body['routing_status'] == 'COMMUNICATOR_GUARDRAIL_TRIGGERED'
        assert body['intent'] == 'communicator.unsupported_or_risky'
        assert body['command_status'] == 'COMMUNICATOR_GUARDRAIL_TRIGGERED'


def test_webhook_unrecognized_handled_as_general_conversation(tmp_path, monkeypatch):
    """Unrecognized text is now handled by communicator as GENERAL_CONVERSATION."""
    _configure_env(monkeypatch, tmp_path)
    app = _build_app()

    with TestClient(app) as client:
        response = client.post(
            '/webhooks/telegram',
            json=_tg_text(3003, 303, 'Bitte pruefe meinen letzten Eingang'),
            headers=_TG_HEADERS,
        )
        assert response.status_code == 200
        body = response.json()
        assert body['status'] == 'accepted'
        assert body['routing_status'] == 'COMMUNICATOR_HANDLED'
        assert body['intent'] == 'communicator.general_conversation'


def test_webhook_needs_from_user_communicator_handled(tmp_path, monkeypatch):
    _configure_env(monkeypatch, tmp_path)
    app = _build_app()

    with TestClient(app) as client:
        response = client.post(
            '/webhooks/telegram',
            json=_tg_text(3004, 304, 'Was brauchst du noch von mir?'),
            headers=_TG_HEADERS,
        )
        assert response.status_code == 200
        body = response.json()
        assert body['status'] == 'accepted'
        assert body['routing_status'] == 'COMMUNICATOR_HANDLED'
        assert body['intent'] == 'communicator.needs_from_user'


def test_webhook_document_arrival_check_handled(tmp_path, monkeypatch):
    _configure_env(monkeypatch, tmp_path)
    app = _build_app()

    with TestClient(app) as client:
        response = client.post(
            '/webhooks/telegram',
            json=_tg_text(3005, 305, 'Ist das Dokument angekommen?'),
            headers=_TG_HEADERS,
        )
        assert response.status_code == 200
        body = response.json()
        assert body['routing_status'] == 'COMMUNICATOR_HANDLED'
        assert 'document_arrival_check' in body['intent']


def test_webhook_status_phrase_not_in_v1_handled_by_communicator(tmp_path, monkeypatch):
    """Status phrases not in the V1 shortlist ('status', 'wie ist der stand', etc.)
    must be handled by the communicator, not fall through to inbox."""
    _configure_env(monkeypatch, tmp_path)
    app = _build_app()

    with TestClient(app) as client:
        response = client.post(
            '/webhooks/telegram',
            json=_tg_text(3006, 306, 'Aktueller Stand bitte'),
            headers=_TG_HEADERS,
        )
        assert response.status_code == 200
        body = response.json()
        assert body['status'] == 'accepted'
        assert body['routing_status'] == 'COMMUNICATOR_HANDLED'
        assert 'status_overview' in body['intent']


def test_webhook_safe_help_handled_by_communicator(tmp_path, monkeypatch):
    _configure_env(monkeypatch, tmp_path)
    app = _build_app()

    with TestClient(app) as client:
        response = client.post(
            '/webhooks/telegram',
            json=_tg_text(3007, 307, 'Wie funktioniert das?'),
            headers=_TG_HEADERS,
        )
        assert response.status_code == 200
        body = response.json()
        assert body['routing_status'] == 'COMMUNICATOR_HANDLED'
        assert 'general_safe_help' in body['intent']


# ═════════════════════════════════════════════════════════════════════════════
# TEIL 6 – audit/inspect consistency after communicator turn
# ═════════════════════════════════════════════════════════════════════════════

def test_audit_chain_inspect_after_greeting_turn(tmp_path, monkeypatch):
    _configure_env(monkeypatch, tmp_path)
    app = _build_app()

    with TestClient(app) as client:
        # Send greeting
        response = client.post(
            '/webhooks/telegram',
            json=_tg_text(3010, 310, 'Hallo Frya'),
            headers=_TG_HEADERS,
        )
        assert response.status_code == 200
        body = response.json()
        case_id = body['case_id']
        assert case_id

        # Inspect audit chain
        _login_admin(client)
        inspect = client.get(f'/inspect/cases/{case_id}/json')
        assert inspect.status_code == 200
        data = inspect.json()

        audit_actions = [ev['action'] for ev in data.get('chronology', [])]
        assert 'COMMUNICATOR_TURN_PROCESSED' in audit_actions

        # Telegram ingress record reflects communicator routing
        tg = data['telegram_ingress']
        assert tg['routing_status'] == 'COMMUNICATOR_HANDLED'
        assert tg['intent_name'] == 'communicator.greeting'


def test_audit_chain_inspect_after_guardrail_triggered(tmp_path, monkeypatch):
    _configure_env(monkeypatch, tmp_path)
    app = _build_app()

    with TestClient(app) as client:
        response = client.post(
            '/webhooks/telegram',
            json=_tg_text(3011, 311, 'Freigabe erteilen'),
            headers=_TG_HEADERS,
        )
        assert response.status_code == 200
        body = response.json()
        case_id = body['case_id']

        _login_admin(client)
        inspect = client.get(f'/inspect/cases/{case_id}/json')
        assert inspect.status_code == 200
        data = inspect.json()

        audit_actions = [ev['action'] for ev in data.get('chronology', [])]
        assert 'COMMUNICATOR_TURN_PROCESSED' in audit_actions

        tg = data['telegram_ingress']
        assert tg['routing_status'] == 'COMMUNICATOR_GUARDRAIL_TRIGGERED'


def test_inspect_communicator_turn_llm_output_fields(tmp_path, monkeypatch):
    """COMMUNICATOR_TURN_PROCESSED audit event must carry intent and guardrail info."""
    _configure_env(monkeypatch, tmp_path)
    app = _build_app()

    with TestClient(app) as client:
        response = client.post(
            '/webhooks/telegram',
            json=_tg_text(3012, 312, 'Was brauchst du noch von mir?'),
            headers=_TG_HEADERS,
        )
        body = response.json()
        case_id = body['case_id']

        _login_admin(client)
        inspect = client.get(f'/inspect/cases/{case_id}/json')
        data = inspect.json()

        comm_events = [
            ev for ev in data.get('chronology', [])
            if ev['action'] == 'COMMUNICATOR_TURN_PROCESSED'
        ]
        assert len(comm_events) == 1
        ev = comm_events[0]
        assert ev['result'] == 'NEEDS_FROM_USER'
        assert ev['agent_name'] == 'frya-communicator'

        llm_output = ev.get('llm_output', {})
        assert llm_output.get('intent') == 'NEEDS_FROM_USER'
        assert llm_output.get('guardrail_passed') is True
