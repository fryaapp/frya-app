"""Paket 55 – Communicator V1 LLM-Integration Tests.

Prueft:
- LLM-Call erhalt korrekten Kontext-Payload (FALLKONTEXT im user-message)
- Guardrail blockt VOR LLM-Call — litellm.acompletion darf NICHT aufgerufen werden
- Fallback bei Exception (litellm.acompletion wirft)
- truth_basis=AUDIT_DERIVED → kein Uncertainty-Qualifier in Antwort
- truth_basis=CONVERSATION_MEMORY → Uncertainty-Phrase am Ende vorhanden
- truth_basis=UNKNOWN → LLM wird aufgerufen, llm_called=True
- Audit-Event COMMUNICATOR_LLM_ERROR wird bei Fehler geschrieben
- llm_called=True in Turn/Inspect wenn LLM-Call erfolgreich
- llm_called=False in Turn/Inspect bei Guardrail-Block
- response_source korrekt in allen Pfaden
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from tests.test_api_surface import (
    _build_app,
    _build_users_json,
    _clear_caches,
    _login_admin,
    _prepare_data,
)

# ─────────────────────────────────────────────────────────────────────────────
# Shared helpers
# ─────────────────────────────────────────────────────────────────────────────

_TG_HEADERS = {'x-telegram-bot-api-secret-token': 'tg-secret'}


def _configure_env(monkeypatch, tmp_path, *, llm_model: str = '', llm_provider: str = ''):
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
    if llm_model:
        monkeypatch.setenv('FRYA_LLM_MODEL', llm_model)
    if llm_provider:
        monkeypatch.setenv('FRYA_LLM_PROVIDER', llm_provider)
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
    def __init__(self, items: list | None = None):
        self._items = items or []

    async def list_by_case(self, case_id: str) -> list:
        return self._items


class _MockLLMConfigRepo:
    """Injects a known model config without needing env or DB."""

    def __init__(self, model: str = 'claude-sonnet-4-5', provider: str = 'anthropic'):
        self._config = {
            'agent_id': 'communicator',
            'model': model,
            'provider': provider,
            'api_key_encrypted': None,
            'base_url': None,
        }

    async def get_config_or_fallback(self, agent_id: str) -> dict:
        return self._config

    def decrypt_key_for_call(self, config: dict) -> str | None:
        return None


def _make_normalized(text: str, chat_id: str = '-5200036710', update_id: int = 1):
    from app.telegram.models import TelegramActor, TelegramNormalizedIngressMessage
    return TelegramNormalizedIngressMessage(
        event_id=f'test-llm-{update_id}',
        telegram_update_ref=f'upd-{update_id}',
        telegram_message_ref=f'msg-{update_id}',
        telegram_chat_ref=f'chat-{chat_id}',
        text=text,
        actor=TelegramActor(chat_id=chat_id, sender_id='1310959044', sender_username='maze'),
    )


def _make_llm_response(content: str, model: str = 'claude-sonnet-4-5') -> MagicMock:
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = content
    resp.model = model
    return resp


def _run(coro):
    return asyncio.run(coro)


# ═════════════════════════════════════════════════════════════════════════════
# TEST 1 – LLM-Call erhalt korrekten Kontext-Payload
# ═════════════════════════════════════════════════════════════════════════════

def test_llm_call_receives_fallkontext_in_payload():
    from app.telegram.communicator.service import TelegramCommunicatorService

    svc = TelegramCommunicatorService()
    audit = _MockAuditService()
    mock_repo = _MockLLMConfigRepo()
    captured_kwargs: dict = {}

    async def mock_acompletion(**kwargs):
        captured_kwargs.update(kwargs)
        return _make_llm_response('FRYA: Dein Fall laeuft gut.')

    with patch('litellm.acompletion', new=mock_acompletion):
        result = _run(svc.try_handle_turn(
            _make_normalized('Aktueller Stand bitte', update_id=201),
            'case-llm-001',
            audit_service=audit,
            open_items_service=_MockOpenItemsService(),
            clarification_service=_MockClarificationService(),
            llm_config_repository=mock_repo,
        ))

    assert result is not None
    assert result.turn.llm_called is True
    assert result.turn.response_source == 'LLM'
    # Payload must contain FALLKONTEXT block
    messages = captured_kwargs.get('messages', [])
    user_msg = next((m for m in messages if m['role'] == 'user'), None)
    assert user_msg is not None
    assert '[FALLKONTEXT]' in user_msg['content']
    assert 'truth_basis:' in user_msg['content']
    assert 'resolution_status:' in user_msg['content']
    assert 'Nutzernachricht: Aktueller Stand bitte' in user_msg['content']
    # System prompt must be present
    sys_msg = next((m for m in messages if m['role'] == 'system'), None)
    assert sys_msg is not None
    # Anthropic prompt caching wraps content in a list of dicts
    sys_content = sys_msg['content']
    if isinstance(sys_content, list):
        sys_text = ' '.join(block.get('text', '') for block in sys_content)
    else:
        sys_text = sys_content
    assert 'FRYA' in sys_text
    assert 'Buchhaltungs' in sys_text


# ═════════════════════════════════════════════════════════════════════════════
# TEST 2 – Guardrail blockt VOR LLM-Call
# ═════════════════════════════════════════════════════════════════════════════

def test_guardrail_blocks_before_llm_call():
    from app.telegram.communicator.service import TelegramCommunicatorService

    svc = TelegramCommunicatorService()
    audit = _MockAuditService()
    mock_repo = _MockLLMConfigRepo()
    mock_acompletion = AsyncMock()

    with patch('litellm.acompletion', mock_acompletion):
        result = _run(svc.try_handle_turn(
            _make_normalized('Mach die Zahlung frei', update_id=202),
            'case-llm-002',
            audit_service=audit,
            open_items_service=_MockOpenItemsService(),
            clarification_service=_MockClarificationService(),
            llm_config_repository=mock_repo,
        ))

    assert result is not None
    assert result.turn.intent == 'UNSUPPORTED_OR_RISKY'
    assert result.turn.guardrail_passed is False
    assert result.turn.llm_called is False
    assert result.turn.response_source == 'GUARDRAIL'
    assert result.routing_status == 'COMMUNICATOR_GUARDRAIL_TRIGGERED'
    assert result.reply_text.startswith('FRYA:')
    # LLM mock must NOT have been called
    mock_acompletion.assert_not_awaited()

    # Audit must NOT contain COMMUNICATOR_LLM_ERROR for guardrail block
    audit_actions = [e['action'] for e in audit.events]
    assert 'COMMUNICATOR_LLM_ERROR' not in audit_actions


# ═════════════════════════════════════════════════════════════════════════════
# TEST 3 – Fallback bei Exception
# ═════════════════════════════════════════════════════════════════════════════

def test_fallback_response_on_llm_exception():
    from app.telegram.communicator.service import TelegramCommunicatorService

    svc = TelegramCommunicatorService()
    audit = _MockAuditService()
    mock_repo = _MockLLMConfigRepo()

    async def mock_acompletion_fail(**kwargs):
        raise Exception('API error: auth failed')

    with patch('litellm.acompletion', new=mock_acompletion_fail):
        result = _run(svc.try_handle_turn(
            _make_normalized('Was brauchst du noch von mir?', update_id=203),
            'case-llm-003',
            audit_service=audit,
            open_items_service=_MockOpenItemsService(),
            clarification_service=_MockClarificationService(),
            llm_config_repository=mock_repo,
        ))

    assert result is not None
    assert result.turn.llm_called is False
    assert result.turn.response_source == 'FALLBACK'
    assert 'nicht erreichbar' in result.reply_text
    assert result.reply_text.startswith('FRYA:')


# ═════════════════════════════════════════════════════════════════════════════
# TEST 4 – Audit COMMUNICATOR_LLM_ERROR bei Fehler
# ═════════════════════════════════════════════════════════════════════════════

def test_llm_error_audit_event_written():
    from app.telegram.communicator.service import TelegramCommunicatorService

    svc = TelegramCommunicatorService()
    audit = _MockAuditService()
    mock_repo = _MockLLMConfigRepo()

    async def mock_acompletion_fail(**kwargs):
        raise RuntimeError('network timeout')

    with patch('litellm.acompletion', new=mock_acompletion_fail):
        _run(svc.try_handle_turn(
            _make_normalized('Aktueller Stand bitte', update_id=204),
            'case-llm-004',
            audit_service=audit,
            open_items_service=_MockOpenItemsService(),
            clarification_service=_MockClarificationService(),
            llm_config_repository=mock_repo,
        ))

    error_events = [e for e in audit.events if e['action'] == 'COMMUNICATOR_LLM_ERROR']
    assert len(error_events) == 1
    err = error_events[0]
    assert err['agent_name'] == 'frya-communicator'
    assert err['result'] == 'LLM_CALL_FAILED'
    assert err['case_id'] == 'case-llm-004'
    llm_out = err.get('llm_output', {})
    assert 'error_message' in llm_out
    assert 'RuntimeError' in llm_out['error_message']
    assert 'intent' in llm_out


# ═════════════════════════════════════════════════════════════════════════════
# TEST 5 – truth_basis=AUDIT_DERIVED → kein Uncertainty-Qualifier
# ═════════════════════════════════════════════════════════════════════════════

def test_audit_derived_no_uncertainty_suffix():
    from app.telegram.communicator.service import TelegramCommunicatorService
    from app.telegram.communicator.prompts import UNCERTAINTY_SUFFIX

    svc = TelegramCommunicatorService()
    audit = _MockAuditService()
    mock_repo = _MockLLMConfigRepo()

    # Provide a real open item so resolve_context returns FOUND → AUDIT_DERIVED
    class _MockOpenItem:
        item_id = 'oi-audit-001'
        status = 'OPEN'
        title = 'Rechnung einreichen'
        description = None

    open_items_svc = _MockOpenItemsService(items=[_MockOpenItem()])

    async def mock_acompletion(**kwargs):
        return _make_llm_response('FRYA: Dein Fall ist in Bearbeitung.')

    with patch('litellm.acompletion', new=mock_acompletion):
        result = _run(svc.try_handle_turn(
            _make_normalized('Was brauchst du noch von mir?', update_id=205),
            'case-llm-005',
            audit_service=audit,
            open_items_service=open_items_svc,
            clarification_service=_MockClarificationService(),
            llm_config_repository=mock_repo,
        ))

    assert result is not None
    assert result.turn.truth_basis == 'AUDIT_DERIVED'
    assert result.turn.llm_called is True
    # Uncertainty suffix must NOT be in the response
    assert UNCERTAINTY_SUFFIX not in result.reply_text


# ═════════════════════════════════════════════════════════════════════════════
# TEST 6 – truth_basis=CONVERSATION_MEMORY → Uncertainty-Phrase am Ende
# ═════════════════════════════════════════════════════════════════════════════

def test_conversation_memory_appends_uncertainty_suffix():
    from app.telegram.communicator.memory.conversation_store import ConversationMemoryStore
    from app.telegram.communicator.memory.models import ConversationMemory
    from app.telegram.communicator.prompts import UNCERTAINTY_SUFFIX
    from app.telegram.communicator.service import TelegramCommunicatorService

    svc = TelegramCommunicatorService()
    audit = _MockAuditService()
    mock_repo = _MockLLMConfigRepo()

    # Pre-load conversation memory with a case ref (to trigger CONVERSATION_MEMORY path)
    store = ConversationMemoryStore('memory://test-conv')
    mem = ConversationMemory(
        conversation_memory_ref='conv-test-mem',
        chat_id='-5200036710',
        last_case_ref='case-old-xyz',
        last_intent='STATUS_OVERVIEW',
        last_context_resolution_status='FOUND',
    )
    _run(store.save(mem))

    # No DB items → resolve_context returns NOT_FOUND → TruthArbitrator uses conv_memory
    async def mock_acompletion(**kwargs):
        return _make_llm_response('FRYA: Dein letzter Fall wird bearbeitet.')

    with patch('litellm.acompletion', new=mock_acompletion):
        result = _run(svc.try_handle_turn(
            _make_normalized('Was ist der Stand?', update_id=206),
            'case-llm-006',
            audit_service=audit,
            open_items_service=_MockOpenItemsService(),
            clarification_service=_MockClarificationService(),
            conversation_store=store,
            llm_config_repository=mock_repo,
        ))

    assert result is not None
    assert result.turn.truth_basis == 'CONVERSATION_MEMORY'
    assert result.turn.llm_called is True
    # Uncertainty suffix MUST be appended
    assert UNCERTAINTY_SUFFIX in result.reply_text


# ═════════════════════════════════════════════════════════════════════════════
# TEST 7 – truth_basis=UNKNOWN → LLM wird aufgerufen, llm_called=True
# ═════════════════════════════════════════════════════════════════════════════

def test_unknown_truth_basis_llm_is_called():
    from app.telegram.communicator.service import TelegramCommunicatorService

    svc = TelegramCommunicatorService()
    audit = _MockAuditService()
    mock_repo = _MockLLMConfigRepo()

    async def mock_acompletion(**kwargs):
        return _make_llm_response('FRYA: Ich habe aktuell keinen verknuepften Fall fuer dich.')

    with patch('litellm.acompletion', new=mock_acompletion):
        result = _run(svc.try_handle_turn(
            _make_normalized('Wie laeuft mein Fall?', update_id=207),
            'case-llm-007',
            audit_service=audit,
            open_items_service=_MockOpenItemsService(),
            clarification_service=_MockClarificationService(),
            llm_config_repository=mock_repo,
        ))

    assert result is not None
    assert result.turn.truth_basis == 'UNKNOWN'
    assert result.turn.llm_called is True
    assert result.turn.response_source == 'LLM'
    assert result.reply_text.startswith('FRYA:')


# ═════════════════════════════════════════════════════════════════════════════
# TEST 8 – llm_called=True in Audit wenn LLM-Call erfolgreich
# ═════════════════════════════════════════════════════════════════════════════

def test_llm_called_true_in_audit_event():
    from app.telegram.communicator.service import TelegramCommunicatorService

    svc = TelegramCommunicatorService()
    audit = _MockAuditService()
    mock_repo = _MockLLMConfigRepo(model='claude-sonnet-4-5', provider='anthropic')

    async def mock_acompletion(**kwargs):
        return _make_llm_response('FRYA: Alles laeuft.', model='claude-sonnet-4-5')

    with patch('litellm.acompletion', new=mock_acompletion):
        _run(svc.try_handle_turn(
            _make_normalized('Hallo Frya', update_id=208),
            'case-llm-008',
            audit_service=audit,
            open_items_service=_MockOpenItemsService(),
            clarification_service=_MockClarificationService(),
            llm_config_repository=mock_repo,
        ))

    turn_events = [e for e in audit.events if e['action'] == 'COMMUNICATOR_TURN_PROCESSED']
    assert len(turn_events) == 1
    llm_out = turn_events[0].get('llm_output', {})
    assert llm_out.get('llm_called') is True
    assert llm_out.get('response_source') == 'LLM'
    assert llm_out.get('model_used') is not None


# ═════════════════════════════════════════════════════════════════════════════
# TEST 9 – llm_called=False im Audit bei Guardrail-Block
# ═════════════════════════════════════════════════════════════════════════════

def test_llm_called_false_in_audit_on_guardrail():
    from app.telegram.communicator.service import TelegramCommunicatorService

    svc = TelegramCommunicatorService()
    audit = _MockAuditService()
    mock_repo = _MockLLMConfigRepo()
    mock_acompletion = AsyncMock()

    with patch('litellm.acompletion', mock_acompletion):
        _run(svc.try_handle_turn(
            _make_normalized('Freigabe erteilen', update_id=209),
            'case-llm-009',
            audit_service=audit,
            open_items_service=_MockOpenItemsService(),
            clarification_service=_MockClarificationService(),
            llm_config_repository=mock_repo,
        ))

    mock_acompletion.assert_not_awaited()

    turn_events = [e for e in audit.events if e['action'] == 'COMMUNICATOR_TURN_PROCESSED']
    assert len(turn_events) == 1
    llm_out = turn_events[0].get('llm_output', {})
    assert llm_out.get('llm_called') is False
    assert llm_out.get('response_source') == 'GUARDRAIL'


# ═════════════════════════════════════════════════════════════════════════════
# TEST 10 – FRYA:-Prefix wird erzwungen wenn LLM ihn weglässt
# ═════════════════════════════════════════════════════════════════════════════

def test_frya_prefix_enforced_on_llm_response():
    from app.telegram.communicator.service import TelegramCommunicatorService

    svc = TelegramCommunicatorService()
    audit = _MockAuditService()
    mock_repo = _MockLLMConfigRepo()

    async def mock_acompletion(**kwargs):
        # LLM forgets the FRYA: prefix
        return _make_llm_response('Dein Fall ist in Bearbeitung.')

    with patch('litellm.acompletion', new=mock_acompletion):
        result = _run(svc.try_handle_turn(
            _make_normalized('Aktueller Stand bitte', update_id=210),
            'case-llm-010',
            audit_service=audit,
            open_items_service=_MockOpenItemsService(),
            clarification_service=_MockClarificationService(),
            llm_config_repository=mock_repo,
        ))

    assert result is not None
    assert result.reply_text.startswith('FRYA:')
    assert result.turn.response_source == 'LLM'


# ═════════════════════════════════════════════════════════════════════════════
# TEST 11 – Inspect-JSON: llm_called und response_source nach LLM-Call
# (Webhook-level: verifiziert Audit-Event via /inspect/cases/json)
# ═════════════════════════════════════════════════════════════════════════════

def test_inspect_shows_llm_called_true_after_llm_turn(tmp_path, monkeypatch):
    _configure_env(
        monkeypatch, tmp_path,
        llm_model='claude-sonnet-4-5',
        llm_provider='anthropic',
    )

    async def mock_acompletion(**kwargs):
        return _make_llm_response('FRYA: Dein Fall laeuft.', model='claude-sonnet-4-5')

    import litellm as _litellm
    monkeypatch.setattr(_litellm, 'acompletion', mock_acompletion)

    app = _build_app()
    with TestClient(app) as client:
        resp = client.post(
            '/webhooks/telegram',
            json=_tg_text(5001, 501, 'Hallo Frya'),
            headers=_TG_HEADERS,
        )
        assert resp.status_code == 200
        case_id = resp.json()['case_id']

        _login_admin(client)
        inspect = client.get(f'/inspect/cases/{case_id}/json')
        assert inspect.status_code == 200
        data = inspect.json()

        comm_turn = data.get('communicator_turn')
        assert comm_turn is not None, 'communicator_turn fehlt im Inspect'
        assert comm_turn.get('llm_called') is True
        assert comm_turn.get('response_source') == 'LLM'
        assert comm_turn.get('model_used') is not None


# ═════════════════════════════════════════════════════════════════════════════
# TEST 12 – Inspect-JSON: llm_called=False nach Guardrail-Block
# ═════════════════════════════════════════════════════════════════════════════

def test_inspect_shows_llm_called_false_on_guardrail(tmp_path, monkeypatch):
    _configure_env(
        monkeypatch, tmp_path,
        llm_model='claude-sonnet-4-5',
        llm_provider='anthropic',
    )

    mock_acompletion = AsyncMock()
    import litellm as _litellm
    monkeypatch.setattr(_litellm, 'acompletion', mock_acompletion)

    app = _build_app()
    with TestClient(app) as client:
        resp = client.post(
            '/webhooks/telegram',
            json=_tg_text(5002, 502, 'Zahlung freigeben bitte'),
            headers=_TG_HEADERS,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body['routing_status'] == 'COMMUNICATOR_GUARDRAIL_TRIGGERED'
        case_id = body['case_id']

        _login_admin(client)
        inspect = client.get(f'/inspect/cases/{case_id}/json')
        assert inspect.status_code == 200
        data = inspect.json()

        comm_turn = data.get('communicator_turn')
        assert comm_turn is not None
        assert comm_turn.get('llm_called') is False
        assert comm_turn.get('response_source') == 'GUARDRAIL'

    # LLM must not have been called
    mock_acompletion.assert_not_awaited()
