"""Tests for Memory Curator API — endpoints, auth, schema round-trips."""
from __future__ import annotations

import importlib
import json
import re
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Shared test infrastructure (mirrors test_agent_config.py)
# ---------------------------------------------------------------------------

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
        {'username': 'admin', 'role': 'admin', 'password_hash': hash_password_pbkdf2('admin-pass')},
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


def _build_app():
    _clear_caches()
    import app.main as main_module
    importlib.reload(main_module)
    return main_module.app


def _extract_csrf_token(html: str) -> str:
    m = re.search(r'name="csrf_token"\s+value="([^"]+)"', html)
    if m:
        return m.group(1)
    m = re.search(r"CSRF\s*=\s*'([^']+)'", html)
    assert m, 'csrf_token nicht im HTML gefunden'
    return m.group(1)


def _setup_env(monkeypatch, tmp_path):
    _prepare_data(tmp_path)
    monkeypatch.setenv('FRYA_DATABASE_URL', 'memory://db')
    monkeypatch.setenv('FRYA_REDIS_URL', 'memory://redis')
    monkeypatch.setenv('FRYA_DATA_DIR', str(tmp_path))
    monkeypatch.setenv('FRYA_RULES_DIR', str(tmp_path / 'rules'))
    monkeypatch.setenv('FRYA_VERFAHRENSDOKU_DIR', str(tmp_path / 'verfahrensdoku'))
    monkeypatch.setenv('FRYA_PAPERLESS_BASE_URL', 'http://paperless')
    monkeypatch.setenv('FRYA_AKAUNTING_BASE_URL', 'http://akaunting')
    monkeypatch.setenv('FRYA_N8N_BASE_URL', 'http://n8n')
    monkeypatch.setenv('FRYA_AUTH_USERS_JSON', _build_users_json())
    monkeypatch.setenv('FRYA_AUTH_SESSION_SECRET', 'test-session-secret-32-bytes-xx')
    monkeypatch.setenv('FRYA_AUTH_COOKIE_SECURE', 'false')


def _get_operator_client(monkeypatch, tmp_path) -> TestClient:
    _setup_env(monkeypatch, tmp_path)
    app = _build_app()
    client = TestClient(app)
    client.post(
        '/auth/login',
        data={'username': 'operator', 'password': 'op-pass', 'next': '/ui/dashboard'},
        follow_redirects=False,
    )
    return client


# ---------------------------------------------------------------------------
# Auth — unauthenticated requests must be rejected
# ---------------------------------------------------------------------------

def test_curate_daily_requires_auth(monkeypatch, tmp_path):
    _setup_env(monkeypatch, tmp_path)
    app = _build_app()
    client = TestClient(app)  # no login
    tenant_id = str(uuid.uuid4())
    resp = client.post(f'/api/memory/curate-daily?tenant_id={tenant_id}')
    assert resp.status_code == 401


def test_state_requires_auth(monkeypatch, tmp_path):
    _setup_env(monkeypatch, tmp_path)
    app = _build_app()
    client = TestClient(app)
    resp = client.get(f'/api/memory/state?tenant_id={uuid.uuid4()}')
    assert resp.status_code == 401


def test_context_requires_auth(monkeypatch, tmp_path):
    _setup_env(monkeypatch, tmp_path)
    app = _build_app()
    client = TestClient(app)
    resp = client.get(f'/api/memory/context?tenant_id={uuid.uuid4()}')
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /api/memory/state — authenticated
# ---------------------------------------------------------------------------

def test_state_returns_dms_state_schema(monkeypatch, tmp_path):
    client = _get_operator_client(monkeypatch, tmp_path)
    tenant_id = str(uuid.uuid4())
    resp = client.get(f'/api/memory/state?tenant_id={tenant_id}')
    assert resp.status_code == 200
    data = resp.json()
    assert 'total_cases' in data
    assert 'open_cases' in data
    assert 'overdue_cases' in data
    assert 'system_health' in data
    assert 'generated_at' in data


def test_state_total_cases_is_integer(monkeypatch, tmp_path):
    client = _get_operator_client(monkeypatch, tmp_path)
    resp = client.get(f'/api/memory/state?tenant_id={uuid.uuid4()}')
    assert isinstance(resp.json()['total_cases'], int)


def test_state_invalid_uuid_returns_400(monkeypatch, tmp_path):
    client = _get_operator_client(monkeypatch, tmp_path)
    resp = client.get('/api/memory/state?tenant_id=not-a-uuid')
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# GET /api/memory/context — authenticated
# ---------------------------------------------------------------------------

def test_context_returns_context_and_tokens(monkeypatch, tmp_path):
    client = _get_operator_client(monkeypatch, tmp_path)
    tenant_id = str(uuid.uuid4())
    resp = client.get(f'/api/memory/context?tenant_id={tenant_id}')
    assert resp.status_code == 200
    data = resp.json()
    assert 'context' in data
    assert 'tokens_estimate' in data
    assert 'tenant_id' in data
    assert data['tenant_id'] == tenant_id


def test_context_contains_agent_section(monkeypatch, tmp_path):
    client = _get_operator_client(monkeypatch, tmp_path)
    resp = client.get(f'/api/memory/context?tenant_id={uuid.uuid4()}')
    assert '[AGENT]' in resp.json()['context']


def test_context_contains_frya(monkeypatch, tmp_path):
    client = _get_operator_client(monkeypatch, tmp_path)
    resp = client.get(f'/api/memory/context?tenant_id={uuid.uuid4()}')
    assert 'FRYA' in resp.json()['context']


def test_context_tokens_estimate_is_integer(monkeypatch, tmp_path):
    client = _get_operator_client(monkeypatch, tmp_path)
    resp = client.get(f'/api/memory/context?tenant_id={uuid.uuid4()}')
    assert isinstance(resp.json()['tokens_estimate'], int)


def test_context_invalid_uuid_returns_400(monkeypatch, tmp_path):
    client = _get_operator_client(monkeypatch, tmp_path)
    resp = client.get('/api/memory/context?tenant_id=bad')
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# POST /api/memory/curate-daily — CSRF required
# ---------------------------------------------------------------------------

def test_curate_daily_requires_csrf(monkeypatch, tmp_path):
    """POST without CSRF token must be rejected."""
    client = _get_operator_client(monkeypatch, tmp_path)
    resp = client.post(f'/api/memory/curate-daily?tenant_id={uuid.uuid4()}')
    assert resp.status_code == 403


def test_curate_daily_with_csrf_returns_curation_result(monkeypatch, tmp_path):
    client = _get_operator_client(monkeypatch, tmp_path)

    # Get CSRF token from any CSRF-enabled UI page (dashboard)
    dash = client.get('/ui/dashboard')
    assert dash.status_code == 200
    csrf = _extract_csrf_token(dash.text)

    tenant_id = str(uuid.uuid4())
    resp = client.post(
        f'/api/memory/curate-daily?tenant_id={tenant_id}',
        headers={'X-Frya-Csrf-Token': csrf},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert 'dms_state_updated' in data
    assert 'memory_md_updated' in data
    assert 'summary' in data
    assert 'Kuration' in data['summary']


def test_curate_daily_dms_state_updated_is_true(monkeypatch, tmp_path):
    client = _get_operator_client(monkeypatch, tmp_path)
    dash = client.get('/ui/dashboard')
    csrf = _extract_csrf_token(dash.text)

    resp = client.post(
        f'/api/memory/curate-daily?tenant_id={uuid.uuid4()}',
        headers={'X-Frya-Csrf-Token': csrf},
    )
    assert resp.status_code == 200
    assert resp.json()['dms_state_updated'] is True


def test_curate_daily_invalid_uuid_returns_400(monkeypatch, tmp_path):
    client = _get_operator_client(monkeypatch, tmp_path)
    dash = client.get('/ui/dashboard')
    csrf = _extract_csrf_token(dash.text)

    resp = client.post(
        '/api/memory/curate-daily?tenant_id=invalid',
        headers={'X-Frya-Csrf-Token': csrf},
    )
    assert resp.status_code == 400


def test_curate_daily_tenant_id_in_result(monkeypatch, tmp_path):
    client = _get_operator_client(monkeypatch, tmp_path)
    dash = client.get('/ui/dashboard')
    csrf = _extract_csrf_token(dash.text)

    tenant_id = str(uuid.uuid4())
    resp = client.post(
        f'/api/memory/curate-daily?tenant_id={tenant_id}',
        headers={'X-Frya-Csrf-Token': csrf},
    )
    assert resp.status_code == 200
    assert resp.json()['tenant_id'] == tenant_id


# ---------------------------------------------------------------------------
# Schema: CurationResult and DmsState
# ---------------------------------------------------------------------------

def test_curation_result_schema_defaults():
    from app.memory_curator.schemas import CurationResult
    r = CurationResult(tenant_id='abc')
    assert r.memory_md_updated is False
    assert r.dms_state_updated is False
    assert r.tokens_before == 0
    assert r.tokens_after == 0
    assert r.changes == []
    assert r.summary == ''


def test_dms_state_schema_defaults():
    from app.memory_curator.schemas import DmsState
    s = DmsState()
    assert s.total_cases == 0
    assert s.open_cases == 0
    assert s.overdue_cases == 0
    assert s.system_health == 'unknown'
    assert s.active_agents == []
    assert s.last_document_at is None


def test_curation_result_serialises():
    from app.memory_curator.schemas import CurationResult, MemoryUpdate
    r = CurationResult(
        tenant_id='t1',
        memory_md_updated=True,
        dms_state_updated=True,
        tokens_before=100,
        tokens_after=80,
        summary='Kuration OK',
        changes=[MemoryUpdate(file_path='/tmp/memory.md', changes_summary='updated', tokens_before=100, tokens_after=80)],
    )
    data = r.model_dump(mode='json')
    assert data['memory_md_updated'] is True
    assert data['tokens_before'] == 100
    assert data['changes'][0]['file_path'] == '/tmp/memory.md'


def test_dms_state_health_ok():
    from app.memory_curator.schemas import DmsState
    s = DmsState(total_cases=5, open_cases=3, overdue_cases=1, system_health='ok')
    assert s.system_health == 'ok'


def test_dms_state_serialises():
    from app.memory_curator.schemas import DmsState
    s = DmsState(total_cases=2, open_cases=2, system_health='ok', generated_at='2026-03-19T00:00:00Z')
    data = s.model_dump(mode='json')
    assert data['total_cases'] == 2
    assert data['system_health'] == 'ok'
    assert data['generated_at'] == '2026-03-19T00:00:00Z'
