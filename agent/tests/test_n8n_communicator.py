"""Tests for POST /api/communicator/send-message.

n8n-Token auth (X-N8N-API-KEY or Bearer). No LLM. No session.
"""
from __future__ import annotations

import importlib
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


N8N_TOKEN = 'test-n8n-token-abc123'


def _clear_caches() -> None:
    import app.config as config_module
    import app.dependencies as deps_module

    config_module.get_settings.cache_clear()

    for name in dir(deps_module):
        obj = getattr(deps_module, name)
        if callable(obj) and hasattr(obj, 'cache_clear'):
            obj.cache_clear()


def _build_app(monkeypatch, tmp_path):
    rules = tmp_path / 'rules'
    policies = rules / 'policies'
    policies.mkdir(parents=True, exist_ok=True)
    (tmp_path / 'verfahrensdoku').mkdir(parents=True, exist_ok=True)
    (tmp_path / 'system' / 'proposals').mkdir(parents=True, exist_ok=True)
    (tmp_path / 'audit').mkdir(parents=True, exist_ok=True)
    (tmp_path / 'tasks').mkdir(parents=True, exist_ok=True)
    (tmp_path / 'memory').mkdir(parents=True, exist_ok=True)
    (tmp_path / 'agent.md').write_text('a', encoding='utf-8')
    (tmp_path / 'user.md').write_text('u', encoding='utf-8')
    (tmp_path / 'soul.md').write_text('s', encoding='utf-8')
    (tmp_path / 'memory.md').write_text('m', encoding='utf-8')
    (tmp_path / 'dms-state.md').write_text('d', encoding='utf-8')
    (tmp_path / 'audit' / 'problem_cases.md').write_text('# Problems\n', encoding='utf-8')
    (tmp_path / 'verfahrensdoku' / 'system_overview.md').write_text('# overview\n', encoding='utf-8')
    (rules / 'runtime_rules.yaml').write_text('version: 1\nname: runtime\n', encoding='utf-8')
    (rules / 'approval_matrix.yaml').write_text(
        'version: 1\nname: approval_matrix\nrules:\n'
        '  - action: rule_policy_edit\n    mode: REQUIRE_USER_APPROVAL\n    strict_require: true\n',
        encoding='utf-8',
    )
    (rules / 'rule_registry.yaml').write_text(
        'version: 1\nentries:\n'
        '  - file: policies/orchestrator_policy.md\n    role: orchestrator_policy\n    required: true\n'
        '  - file: policies/runtime_policy.md\n    role: runtime_policy\n    required: true\n'
        '  - file: policies/gobd_compliance_policy.md\n    role: compliance_policy\n    required: true\n'
        '  - file: policies/accounting_analyst_policy.md\n    role: accounting_analyst_policy\n    required: true\n'
        '  - file: policies/problemfall_policy.md\n    role: problemfall_policy\n    required: true\n'
        '  - file: policies/freigabematrix.md\n    role: approval_matrix_policy\n    required: true\n'
        '  - file: approval_matrix.yaml\n    role: legacy_approval_matrix_schema\n    required: false\n',
        encoding='utf-8',
    )
    for name in [
        'orchestrator_policy.md', 'runtime_policy.md', 'gobd_compliance_policy.md',
        'accounting_analyst_policy.md', 'problemfall_policy.md', 'freigabematrix.md',
    ]:
        (policies / name).write_text('Version: 1.0\n', encoding='utf-8')

    from app.auth.service import hash_password_pbkdf2
    from cryptography.fernet import Fernet
    fernet_key = Fernet.generate_key().decode()
    users_json = json.dumps([
        {'username': 'admin', 'role': 'admin', 'password_hash': hash_password_pbkdf2('admin-pass')},
    ])

    monkeypatch.setenv('FRYA_DATABASE_URL', 'memory://db')
    monkeypatch.setenv('FRYA_REDIS_URL', 'memory://redis')
    monkeypatch.setenv('FRYA_DATA_DIR', str(tmp_path))
    monkeypatch.setenv('FRYA_RULES_DIR', str(rules))
    monkeypatch.setenv('FRYA_VERFAHRENSDOKU_DIR', str(tmp_path / 'verfahrensdoku'))
    monkeypatch.setenv('FRYA_PAPERLESS_BASE_URL', 'http://paperless')
    monkeypatch.setenv('FRYA_AKAUNTING_BASE_URL', 'http://akaunting')
    monkeypatch.setenv('FRYA_AUTH_USERS_JSON', users_json)
    monkeypatch.setenv('FRYA_AUTH_SESSION_SECRET', 'test-session-secret-32-bytes-xx')
    monkeypatch.setenv('FRYA_AUTH_COOKIE_SECURE', 'false')
    monkeypatch.setenv('FRYA_N8N_BASE_URL', 'http://n8n')
    monkeypatch.setenv('FRYA_N8N_TOKEN', N8N_TOKEN)
    monkeypatch.setenv('FRYA_CONFIG_ENCRYPTION_KEY', fernet_key)

    _clear_caches()
    import app.main as main_module
    importlib.reload(main_module)
    return TestClient(main_module.app)


URL = '/api/communicator/send-message'


def _auth() -> dict:
    return {'X-N8N-API-KEY': N8N_TOKEN}


def _body(chat_id: str = '123456', text: str = 'Test-Nachricht') -> dict:
    return {'chat_id': chat_id, 'text': text}


# ---------------------------------------------------------------------------
# Auth tests
# ---------------------------------------------------------------------------

def test_send_message_unauthenticated_returns_401(monkeypatch, tmp_path):
    client = _build_app(monkeypatch, tmp_path)
    resp = client.post(URL, json=_body())
    assert resp.status_code == 401


def test_send_message_wrong_token_returns_401(monkeypatch, tmp_path):
    client = _build_app(monkeypatch, tmp_path)
    resp = client.post(URL, json=_body(), headers={'X-N8N-API-KEY': 'bad'})
    assert resp.status_code == 401


def test_send_message_bearer_accepted(monkeypatch, tmp_path):
    client = _build_app(monkeypatch, tmp_path)
    mock_connector = MagicMock()
    mock_connector.send = AsyncMock(return_value={'ok': True, 'status_code': 200, 'body': '{}'})
    with patch('app.api.communicator_send.get_telegram_connector', return_value=mock_connector):
        resp = client.post(
            URL,
            json=_body(),
            headers={'Authorization': f'Bearer {N8N_TOKEN}'},
        )
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Functional tests
# ---------------------------------------------------------------------------

def test_send_message_calls_telegram_connector(monkeypatch, tmp_path):
    client = _build_app(monkeypatch, tmp_path)
    mock_connector = MagicMock()
    mock_connector.send = AsyncMock(return_value={'ok': True, 'status_code': 200, 'body': '{}'})

    with patch('app.api.communicator_send.get_telegram_connector', return_value=mock_connector):
        resp = client.post(URL, json=_body(chat_id='999', text='Hallo Welt'), headers=_auth())

    assert resp.status_code == 200
    mock_connector.send.assert_called_once()
    call_arg = mock_connector.send.call_args[0][0]
    assert call_arg.target == '999'
    assert call_arg.text == 'Hallo Welt'


def test_send_message_returns_ok_true(monkeypatch, tmp_path):
    client = _build_app(monkeypatch, tmp_path)
    mock_connector = MagicMock()
    mock_connector.send = AsyncMock(return_value={'ok': True, 'status_code': 200, 'body': '{}'})

    with patch('app.api.communicator_send.get_telegram_connector', return_value=mock_connector):
        resp = client.post(URL, json=_body(), headers=_auth())

    assert resp.status_code == 200
    data = resp.json()
    assert data['ok'] is True
    assert 'detail' in data


def test_send_message_returns_ok_false_on_telegram_failure(monkeypatch, tmp_path):
    client = _build_app(monkeypatch, tmp_path)
    mock_connector = MagicMock()
    mock_connector.send = AsyncMock(return_value={
        'ok': False, 'reason': 'telegram_bot_token_missing',
    })

    with patch('app.api.communicator_send.get_telegram_connector', return_value=mock_connector):
        resp = client.post(URL, json=_body(), headers=_auth())

    assert resp.status_code == 200  # HTTP 200, but ok=False inside
    assert resp.json()['ok'] is False


def test_send_message_missing_chat_id_returns_422(monkeypatch, tmp_path):
    client = _build_app(monkeypatch, tmp_path)
    resp = client.post(URL, json={'text': 'no chat_id here'}, headers=_auth())
    assert resp.status_code == 422


def test_send_message_missing_text_returns_422(monkeypatch, tmp_path):
    client = _build_app(monkeypatch, tmp_path)
    resp = client.post(URL, json={'chat_id': '123'}, headers=_auth())
    assert resp.status_code == 422


def test_send_message_no_llm_call(monkeypatch, tmp_path):
    """send-message must never call litellm.acompletion."""
    client = _build_app(monkeypatch, tmp_path)
    mock_connector = MagicMock()
    mock_connector.send = AsyncMock(return_value={'ok': True})

    with (
        patch('app.api.communicator_send.get_telegram_connector', return_value=mock_connector),
        patch('litellm.acompletion', new=AsyncMock()) as mock_llm,
    ):
        client.post(URL, json=_body(), headers=_auth())

    mock_llm.assert_not_called()


def test_send_message_with_special_chars(monkeypatch, tmp_path):
    """Text with German umlauts and special characters must be passed through."""
    client = _build_app(monkeypatch, tmp_path)
    text = 'Überfällige Rechnung: 340,00 € — bitte begleichen! 🔔'
    mock_connector = MagicMock()
    mock_connector.send = AsyncMock(return_value={'ok': True})

    with patch('app.api.communicator_send.get_telegram_connector', return_value=mock_connector):
        resp = client.post(URL, json=_body(text=text), headers=_auth())

    assert resp.status_code == 200
    call_arg = mock_connector.send.call_args[0][0]
    assert call_arg.text == text
