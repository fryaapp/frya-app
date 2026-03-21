"""Bulk-Upload UI tests — tests 12–14."""
from __future__ import annotations

import importlib
import json
from pathlib import Path

from fastapi.testclient import TestClient


# ── Helpers (same pattern as test_bulk_upload_api.py) ────────────────────────

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


def _build_users_json() -> str:
    from app.auth.service import hash_password_pbkdf2
    return json.dumps([
        {'username': 'operator', 'role': 'operator', 'password_hash': hash_password_pbkdf2('op-pass')},
    ])


def _clear_caches() -> None:
    import app.config as config_module
    import app.dependencies as deps_module
    import app.auth.service as auth_service_module
    config_module.get_settings.cache_clear()
    auth_service_module.get_auth_service.cache_clear()
    for name in dir(deps_module):
        obj = getattr(deps_module, name)
        if callable(obj) and hasattr(obj, 'cache_clear'):
            obj.cache_clear()


def _build_app():
    _clear_caches()
    import app.main as main_module
    importlib.reload(main_module)
    return main_module.app


def _setup(tmp_path: Path, monkeypatch) -> TestClient:
    _prepare_data(tmp_path)
    monkeypatch.setenv('FRYA_DATABASE_URL', 'memory://db')
    monkeypatch.setenv('FRYA_REDIS_URL', 'memory://redis')
    monkeypatch.setenv('FRYA_DATA_DIR', str(tmp_path))
    monkeypatch.setenv('FRYA_RULES_DIR', str(tmp_path / 'rules'))
    monkeypatch.setenv('FRYA_VERFAHRENSDOKU_DIR', str(tmp_path / 'verfahrensdoku'))
    monkeypatch.setenv('FRYA_PAPERLESS_BASE_URL', 'http://paperless.local')
    monkeypatch.setenv('FRYA_AKAUNTING_BASE_URL', 'http://akaunting')
    monkeypatch.setenv('FRYA_N8N_BASE_URL', 'http://n8n')
    monkeypatch.setenv('FRYA_TELEGRAM_WEBHOOK_SECRET', 'tg-secret')
    monkeypatch.setenv('FRYA_TELEGRAM_ALLOWED_CHAT_IDS', '-1001')
    monkeypatch.setenv('FRYA_TELEGRAM_ALLOWED_DIRECT_CHAT_IDS', '1001')
    monkeypatch.setenv('FRYA_TELEGRAM_ALLOWED_USER_IDS', '1001')
    monkeypatch.setenv('FRYA_AUTH_USERS_JSON', _build_users_json())
    monkeypatch.setenv('FRYA_AUTH_SESSION_SECRET', 'test-secret-ui')
    monkeypatch.setenv('FRYA_AUTH_COOKIE_SECURE', 'false')
    app = _build_app()
    client = TestClient(app, raise_server_exceptions=True)
    client.__enter__()
    return client


def _login(client: TestClient) -> None:
    res = client.post(
        '/auth/login',
        data={'username': 'operator', 'password': 'op-pass', 'next': '/ui/upload'},
        follow_redirects=False,
    )
    assert res.status_code == 303


# ── Test 12: Upload page accessible ──────────────────────────────────────────

def test_upload_page_accessible(tmp_path, monkeypatch):
    """GET /ui/upload with auth → 200."""
    client = _setup(tmp_path, monkeypatch)
    try:
        _login(client)
        res = client.get('/ui/upload')
        assert res.status_code == 200
    finally:
        client.__exit__(None, None, None)


# ── Test 13: Upload page requires auth ────────────────────────────────────────

def test_upload_page_requires_auth(tmp_path, monkeypatch):
    """GET /ui/upload without auth → redirect to login (303) or 401."""
    client = _setup(tmp_path, monkeypatch)
    try:
        res = client.get('/ui/upload', follow_redirects=False)
        assert res.status_code in (303, 401), f'Expected 303 or 401, got {res.status_code}'
    finally:
        client.__exit__(None, None, None)


# ── Test 14: Upload page has drop-zone ────────────────────────────────────────

def test_upload_page_has_dropzone(tmp_path, monkeypatch):
    """Response contains the drop-zone HTML element."""
    client = _setup(tmp_path, monkeypatch)
    try:
        _login(client)
        res = client.get('/ui/upload')
        assert res.status_code == 200
        assert 'drop-zone' in res.text
        assert 'file-input' in res.text
        assert 'Dokumente hochladen' in res.text
    finally:
        client.__exit__(None, None, None)
