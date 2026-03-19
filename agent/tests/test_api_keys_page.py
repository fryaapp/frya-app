"""Tests for /ui/api-keys page."""
from __future__ import annotations

import importlib
import json
from pathlib import Path

from fastapi.testclient import TestClient


# ── helpers (reused from test_agent_config.py pattern) ───────────────────────

def _prepare_data(tmp_path: Path) -> None:
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
        '  - action: rule_policy_edit\n'
        '    mode: REQUIRE_USER_APPROVAL\n'
        '    strict_require: true\n',
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


def _build_users_json(admin_pass: str = 'admin-pass', operator_pass: str = 'op-pass') -> str:
    from app.auth.service import hash_password_pbkdf2
    return json.dumps([
        {'username': 'admin', 'role': 'admin', 'password_hash': hash_password_pbkdf2(admin_pass)},
        {'username': 'operator', 'role': 'operator', 'password_hash': hash_password_pbkdf2(operator_pass)},
    ])


def _clear_caches() -> None:
    import app.auth.service as auth_service_module
    import app.config as config_module
    import app.dependencies as deps_module
    config_module.get_settings.cache_clear()
    auth_service_module.get_auth_service.cache_clear()
    for name in dir(deps_module):
        obj = getattr(deps_module, name)
        if callable(obj) and hasattr(obj, 'cache_clear'):
            obj.cache_clear()


def _setup_env(monkeypatch, tmp_path):
    _prepare_data(tmp_path)
    monkeypatch.setenv('FRYA_DATABASE_URL', 'memory://db')
    monkeypatch.setenv('FRYA_REDIS_URL', 'memory://redis')
    monkeypatch.setenv('FRYA_DATA_DIR', str(tmp_path))
    monkeypatch.setenv('FRYA_RULES_DIR', str(tmp_path / 'rules'))
    monkeypatch.setenv('FRYA_VERFAHRENSDOKU_DIR', str(tmp_path / 'verfahrensdoku'))
    monkeypatch.setenv('FRYA_PAPERLESS_BASE_URL', 'http://paperless')
    monkeypatch.setenv('FRYA_AKAUNTING_BASE_URL', 'http://akaunting')
    monkeypatch.setenv('FRYA_AUTH_USERS_JSON', _build_users_json())
    monkeypatch.setenv('FRYA_AUTH_SESSION_SECRET', 'test-session-secret-32-bytes-xx')
    monkeypatch.setenv('FRYA_AUTH_COOKIE_SECURE', 'false')
    monkeypatch.setenv('FRYA_N8N_BASE_URL', 'http://n8n')


def _build_app():
    _clear_caches()
    import app.main as main_module
    importlib.reload(main_module)
    return main_module.app


def _login(client: TestClient, username: str, password: str):
    return client.post(
        '/auth/login',
        data={'username': username, 'password': password, 'next': '/ui/dashboard'},
        follow_redirects=False,
    )


# ── tests ─────────────────────────────────────────────────────────────────────

def test_api_keys_unauthenticated_returns_401(monkeypatch, tmp_path):
    _setup_env(monkeypatch, tmp_path)
    app = _build_app()
    client = TestClient(app)

    resp = client.get('/ui/api-keys', follow_redirects=False)
    # Not under /ui prefix path → returns 401 JSON or 303→login
    assert resp.status_code in (401, 303)


def test_api_keys_operator_returns_403(monkeypatch, tmp_path):
    _setup_env(monkeypatch, tmp_path)
    app = _build_app()
    client = TestClient(app)
    _login(client, 'operator', 'op-pass')

    resp = client.get('/ui/api-keys', follow_redirects=False)
    assert resp.status_code == 403


def test_api_keys_admin_returns_200(monkeypatch, tmp_path):
    _setup_env(monkeypatch, tmp_path)
    app = _build_app()
    client = TestClient(app)
    _login(client, 'admin', 'admin-pass')

    resp = client.get('/ui/api-keys')
    assert resp.status_code == 200


def test_api_keys_lists_all_services(monkeypatch, tmp_path):
    _setup_env(monkeypatch, tmp_path)
    app = _build_app()
    client = TestClient(app)
    _login(client, 'admin', 'admin-pass')

    resp = client.get('/ui/api-keys')
    assert resp.status_code == 200
    html = resp.text

    for service in ['IONOS', 'Brevo', 'Telegram', 'Hetzner', 'Paperless', 'OpenAI', 'n8n', 'age']:
        assert service in html, f'Dienst "{service}" fehlt im HTML'


def test_api_keys_missing_keys_shown_as_missing(monkeypatch, tmp_path):
    """When no keys are set, all ENV keys should appear with missing indicator."""
    _setup_env(monkeypatch, tmp_path)
    # Explicitly unset any key that might be set
    for var in ('FRYA_BREVO_API_KEY', 'FRYA_TELEGRAM_BOT_TOKEN', 'FRYA_PAPERLESS_TOKEN',
                'FRYA_OPENAI_API_KEY', 'FRYA_N8N_TOKEN'):
        monkeypatch.delenv(var, raising=False)

    app = _build_app()
    client = TestClient(app)
    _login(client, 'admin', 'admin-pass')

    resp = client.get('/ui/api-keys')
    assert resp.status_code == 200
    # Should contain "nicht gesetzt" text for missing keys
    assert 'nicht gesetzt' in resp.text


def test_api_keys_set_key_is_masked(monkeypatch, tmp_path):
    """When a key is set, last 4 chars should be visible, not the full key."""
    _setup_env(monkeypatch, tmp_path)
    monkeypatch.setenv('FRYA_BREVO_API_KEY', 'xkeysib-supersecretkey1234')

    app = _build_app()
    client = TestClient(app)
    _login(client, 'admin', 'admin-pass')

    resp = client.get('/ui/api-keys')
    assert resp.status_code == 200
    html = resp.text
    # Last 4 chars visible
    assert '1234' in html
    # Full key NOT present
    assert 'supersecretkey' not in html


def test_api_keys_no_key_leaked_in_response(monkeypatch, tmp_path):
    """Full API key values must never appear in the HTML response."""
    _setup_env(monkeypatch, tmp_path)
    secret = 'VERYSECRETVALUE_NEVER_SHOW_THIS'
    monkeypatch.setenv('FRYA_PAPERLESS_TOKEN', secret)

    app = _build_app()
    client = TestClient(app)
    _login(client, 'admin', 'admin-pass')

    resp = client.get('/ui/api-keys')
    assert resp.status_code == 200
    assert 'VERYSECRETVALUE_NEVER_SHOW_THIS' not in resp.text


def test_api_keys_tooltips_present(monkeypatch, tmp_path):
    """Tooltip text must be present in the HTML."""
    _setup_env(monkeypatch, tmp_path)
    app = _build_app()
    client = TestClient(app)
    _login(client, 'admin', 'admin-pass')

    resp = client.get('/ui/api-keys')
    assert resp.status_code == 200
    html = resp.text
    assert 'brevo.com' in html
    assert 'BotFather' in html
    assert 'Paperless' in html


def test_mask_helper():
    """Unit test for the _mask helper function."""
    from app.ui.router import _mask

    assert _mask(None) is None
    assert _mask('') is None
    assert _mask('abcd') == '****'
    assert _mask('1234567890') == '****7890'
    assert _mask('abc') == '****'
    # Full key not recoverable from masked value
    key = 'sk-supersecret-key-ABCD'
    masked = _mask(key)
    assert masked == '****ABCD'
    assert 'supersecret' not in masked
