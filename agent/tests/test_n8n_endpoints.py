"""Tests for n8n webhook endpoints — POST /api/n8n/*.

Auth: X-N8N-API-KEY or Authorization: Bearer.
All endpoints require a valid n8n token; 401 without it.
"""
from __future__ import annotations

import importlib
import json
import uuid
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Test fixtures / helpers
# ---------------------------------------------------------------------------

TENANT_ID = str(uuid.uuid4())
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
    from pathlib import Path
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


def _auth_headers() -> dict:
    return {'X-N8N-API-KEY': N8N_TOKEN}


def _bearer_headers() -> dict:
    return {'Authorization': f'Bearer {N8N_TOKEN}'}


def _tenant_body() -> dict:
    return {'tenant_id': TENANT_ID}


# ---------------------------------------------------------------------------
# Auth tests — all endpoints must return 401 without token
# ---------------------------------------------------------------------------

ENDPOINTS = [
    '/api/n8n/fristen-check',
    '/api/n8n/skonto-warnung',
    '/api/n8n/mahnwesen',
    '/api/n8n/frist-eskalation',
    '/api/n8n/paperless-post-consumption',
    '/api/n8n/tages-summary',
]


@pytest.mark.parametrize('endpoint', ENDPOINTS)
def test_n8n_endpoint_unauthenticated_returns_401(monkeypatch, tmp_path, endpoint):
    client = _build_app(monkeypatch, tmp_path)
    resp = client.post(endpoint, json=_tenant_body())
    assert resp.status_code == 401


@pytest.mark.parametrize('endpoint', ENDPOINTS)
def test_n8n_endpoint_wrong_token_returns_401(monkeypatch, tmp_path, endpoint):
    client = _build_app(monkeypatch, tmp_path)
    resp = client.post(endpoint, json=_tenant_body(), headers={'X-N8N-API-KEY': 'wrong-token'})
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Auth acceptance: both header styles
# ---------------------------------------------------------------------------

def test_fristen_check_accepts_x_n8n_api_key(monkeypatch, tmp_path):
    """X-N8N-API-KEY header is accepted."""
    client = _build_app(monkeypatch, tmp_path)
    mock_report = MagicMock()
    mock_report.model_dump.return_value = {
        'overdue': [], 'due_today': [], 'due_soon': [], 'skonto_expiring': [], 'summary': 'ok',
    }
    with patch('app.api.n8n_endpoints.build_deadline_analyst_service') as mock_build:
        svc = MagicMock()
        svc.check_all_deadlines = AsyncMock(return_value=mock_report)
        mock_build.return_value = svc
        resp = client.post('/api/n8n/fristen-check', json=_tenant_body(), headers=_auth_headers())
    assert resp.status_code == 200


def test_fristen_check_accepts_bearer_token(monkeypatch, tmp_path):
    """Authorization: Bearer <token> is also accepted."""
    client = _build_app(monkeypatch, tmp_path)
    mock_report = MagicMock()
    mock_report.model_dump.return_value = {
        'overdue': [], 'due_today': [], 'due_soon': [], 'skonto_expiring': [], 'summary': 'ok',
    }
    with patch('app.api.n8n_endpoints.build_deadline_analyst_service') as mock_build:
        svc = MagicMock()
        svc.check_all_deadlines = AsyncMock(return_value=mock_report)
        mock_build.return_value = svc
        resp = client.post('/api/n8n/fristen-check', json=_tenant_body(), headers=_bearer_headers())
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# POST /api/n8n/fristen-check
# ---------------------------------------------------------------------------

def test_fristen_check_returns_report(monkeypatch, tmp_path):
    client = _build_app(monkeypatch, tmp_path)
    expected = {
        'overdue': [{'case_id': 'c1', 'days_overdue': 3}],
        'due_today': [],
        'due_soon': [],
        'skonto_expiring': [],
        'summary': 'Fristen-Report',
    }
    mock_report = MagicMock()
    mock_report.model_dump.return_value = expected
    with patch('app.api.n8n_endpoints.build_deadline_analyst_service') as mock_build:
        svc = MagicMock()
        svc.check_all_deadlines = AsyncMock(return_value=mock_report)
        mock_build.return_value = svc
        resp = client.post('/api/n8n/fristen-check', json=_tenant_body(), headers=_auth_headers())
    assert resp.status_code == 200
    data = resp.json()
    assert data['summary'] == 'Fristen-Report'


def test_fristen_check_invalid_tenant_uuid_returns_400(monkeypatch, tmp_path):
    client = _build_app(monkeypatch, tmp_path)
    resp = client.post(
        '/api/n8n/fristen-check',
        json={'tenant_id': 'not-a-uuid'},
        headers=_auth_headers(),
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# POST /api/n8n/skonto-warnung
# ---------------------------------------------------------------------------

def test_skonto_warnung_returns_only_skonto(monkeypatch, tmp_path):
    client = _build_app(monkeypatch, tmp_path)
    skonto_item = MagicMock()
    skonto_item.model_dump.return_value = {'case_id': 'c1', 'warning_type': 'skonto_expiring'}
    mock_report = MagicMock()
    mock_report.skonto_expiring = [skonto_item]
    with patch('app.api.n8n_endpoints.build_deadline_analyst_service') as mock_build:
        svc = MagicMock()
        svc.check_all_deadlines = AsyncMock(return_value=mock_report)
        mock_build.return_value = svc
        resp = client.post('/api/n8n/skonto-warnung', json=_tenant_body(), headers=_auth_headers())
    assert resp.status_code == 200
    data = resp.json()
    assert data['count'] == 1
    assert 'skonto_expiring' in data
    assert 'checked_at' in data


def test_skonto_warnung_empty_list(monkeypatch, tmp_path):
    client = _build_app(monkeypatch, tmp_path)
    mock_report = MagicMock()
    mock_report.skonto_expiring = []
    with patch('app.api.n8n_endpoints.build_deadline_analyst_service') as mock_build:
        svc = MagicMock()
        svc.check_all_deadlines = AsyncMock(return_value=mock_report)
        mock_build.return_value = svc
        resp = client.post('/api/n8n/skonto-warnung', json=_tenant_body(), headers=_auth_headers())
    assert resp.status_code == 200
    assert resp.json()['count'] == 0


# ---------------------------------------------------------------------------
# POST /api/n8n/mahnwesen
# ---------------------------------------------------------------------------

def test_mahnwesen_returns_overdue_outgoing(monkeypatch, tmp_path):
    client = _build_app(monkeypatch, tmp_path)
    case = MagicMock()
    case.id = uuid.uuid4()
    case.case_number = 'CASE-2026-00001'
    case.title = 'Rechnung an Mustermann'
    case.vendor_name = 'Mustermann GmbH'
    case.total_amount = Decimal('500.00')
    case.currency = 'EUR'
    case.due_date = date(2026, 1, 1)
    case.created_at = datetime(2026, 1, 1)
    case.case_type = 'outgoing_invoice'

    with patch('app.api.n8n_endpoints.get_case_repository') as mock_repo_fn:
        repo = MagicMock()
        repo.list_cases = AsyncMock(return_value=[case])
        mock_repo_fn.return_value = repo
        resp = client.post('/api/n8n/mahnwesen', json=_tenant_body(), headers=_auth_headers())

    assert resp.status_code == 200
    data = resp.json()
    assert data['count'] == 1
    assert data['cases'][0]['case_number'] == 'CASE-2026-00001'


def test_mahnwesen_filters_non_outgoing(monkeypatch, tmp_path):
    """incoming_invoice cases must not appear in mahnwesen."""
    client = _build_app(monkeypatch, tmp_path)
    case = MagicMock()
    case.id = uuid.uuid4()
    case.case_number = 'CASE-2026-00002'
    case.title = 'Eingangsrechnung'
    case.vendor_name = 'Lieferant GmbH'
    case.total_amount = Decimal('100.00')
    case.currency = 'EUR'
    case.due_date = date(2026, 1, 1)
    case.created_at = datetime(2026, 1, 1)
    case.case_type = 'incoming_invoice'  # should be filtered out

    with patch('app.api.n8n_endpoints.get_case_repository') as mock_repo_fn:
        repo = MagicMock()
        repo.list_cases = AsyncMock(return_value=[case])
        mock_repo_fn.return_value = repo
        resp = client.post('/api/n8n/mahnwesen', json=_tenant_body(), headers=_auth_headers())

    assert resp.status_code == 200
    assert resp.json()['count'] == 0


# ---------------------------------------------------------------------------
# POST /api/n8n/frist-eskalation
# ---------------------------------------------------------------------------

def test_frist_eskalation_creates_problem_for_overdue_14_days(monkeypatch, tmp_path):
    client = _build_app(monkeypatch, tmp_path)
    from datetime import timedelta
    case = MagicMock()
    case.id = uuid.uuid4()
    case.case_number = 'CASE-2026-00003'
    case.title = 'Ueberfaellige Rechnung'
    case.total_amount = Decimal('999.00')
    case.currency = 'EUR'
    case.due_date = date.today() - timedelta(days=20)

    problem = MagicMock()
    problem.problem_id = str(uuid.uuid4())

    with (
        patch('app.api.n8n_endpoints.get_case_repository') as mock_repo_fn,
        patch('app.api.n8n_endpoints.get_problem_case_service') as mock_prob_fn,
    ):
        repo = MagicMock()
        repo.list_cases = AsyncMock(return_value=[case])
        mock_repo_fn.return_value = repo

        prob_svc = MagicMock()
        prob_svc.add_case = AsyncMock(return_value=problem)
        mock_prob_fn.return_value = prob_svc

        resp = client.post('/api/n8n/frist-eskalation', json=_tenant_body(), headers=_auth_headers())

    assert resp.status_code == 200
    data = resp.json()
    assert data['escalated_count'] == 1
    assert data['escalated'][0]['case_number'] == 'CASE-2026-00003'
    assert data['escalated'][0]['days_overdue'] == 20


def test_frist_eskalation_skips_cases_within_14_days(monkeypatch, tmp_path):
    """Cases overdue ≤14 days must NOT be escalated."""
    client = _build_app(monkeypatch, tmp_path)
    from datetime import timedelta
    case = MagicMock()
    case.id = uuid.uuid4()
    case.case_number = 'CASE-2026-00004'
    case.title = 'Fast ueberfaellig'
    case.total_amount = Decimal('100.00')
    case.currency = 'EUR'
    case.due_date = date.today() - timedelta(days=10)

    with patch('app.api.n8n_endpoints.get_case_repository') as mock_repo_fn:
        repo = MagicMock()
        repo.list_cases = AsyncMock(return_value=[case])
        mock_repo_fn.return_value = repo
        resp = client.post('/api/n8n/frist-eskalation', json=_tenant_body(), headers=_auth_headers())

    assert resp.status_code == 200
    assert resp.json()['escalated_count'] == 0


def test_frist_eskalation_skips_no_due_date(monkeypatch, tmp_path):
    """Cases without a due_date must be skipped."""
    client = _build_app(monkeypatch, tmp_path)
    case = MagicMock()
    case.id = uuid.uuid4()
    case.case_number = 'CASE-2026-00005'
    case.title = 'Kein Faelligkeitsdatum'
    case.total_amount = None
    case.currency = 'EUR'
    case.due_date = None

    with patch('app.api.n8n_endpoints.get_case_repository') as mock_repo_fn:
        repo = MagicMock()
        repo.list_cases = AsyncMock(return_value=[case])
        mock_repo_fn.return_value = repo
        resp = client.post('/api/n8n/frist-eskalation', json=_tenant_body(), headers=_auth_headers())

    assert resp.status_code == 200
    assert resp.json()['escalated_count'] == 0


# ---------------------------------------------------------------------------
# POST /api/n8n/paperless-post-consumption
# ---------------------------------------------------------------------------

def test_paperless_post_consumption_calls_assignment(monkeypatch, tmp_path):
    client = _build_app(monkeypatch, tmp_path)
    case_id = str(uuid.uuid4())
    assignment_result = MagicMock()
    assignment_result.case_id = case_id
    assignment_result.confidence = 'HIGH'
    assignment_result.method = 'entity_amount'
    assignment_result.model_dump.return_value = {
        'case_id': case_id,
        'confidence': 'HIGH',
        'method': 'entity_amount',
    }
    with patch('app.case_engine.assignment.CaseAssignmentEngine') as mock_engine_cls:
        engine = MagicMock()
        engine.assign_document = AsyncMock(return_value=assignment_result)
        mock_engine_cls.return_value = engine
        with patch('app.api.n8n_endpoints.get_case_repository') as mock_repo_fn:
            mock_repo = MagicMock()
            mock_repo.add_document_to_case = AsyncMock()
            mock_repo_fn.return_value = mock_repo
            resp = client.post(
                '/api/n8n/paperless-post-consumption',
                json={
                    'tenant_id': TENANT_ID,
                    'document_source_id': 'doc-42',
                    'vendor_name': 'Telekom GmbH',
                    'filename': 'rechnung.pdf',
                },
                headers=_auth_headers(),
            )
    assert resp.status_code == 200
    data = resp.json()
    assert data['assigned'] is True
    assert data['method'] == 'entity_amount'


def test_paperless_post_consumption_invalid_tenant_returns_400(monkeypatch, tmp_path):
    client = _build_app(monkeypatch, tmp_path)
    resp = client.post(
        '/api/n8n/paperless-post-consumption',
        json={'tenant_id': 'bad-uuid', 'document_source_id': 'doc-1'},
        headers=_auth_headers(),
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# POST /api/n8n/tages-summary
# ---------------------------------------------------------------------------

def test_tages_summary_returns_case_counts(monkeypatch, tmp_path):
    client = _build_app(monkeypatch, tmp_path)

    async def _fake_list_cases(tid, status=None, limit=1000):
        if status == 'OPEN':
            return [MagicMock(), MagicMock()]  # 2 open
        if status == 'OVERDUE':
            return [MagicMock()]  # 1 overdue
        return []

    with (
        patch('app.api.n8n_endpoints.get_case_repository') as mock_repo_fn,
        patch('app.memory_curator.service.MemoryCuratorService', side_effect=Exception('no curator')),
    ):
        repo = MagicMock()
        repo.list_cases = _fake_list_cases
        mock_repo_fn.return_value = repo
        resp = client.post('/api/n8n/tages-summary', json=_tenant_body(), headers=_auth_headers())

    assert resp.status_code == 200
    data = resp.json()
    assert data['case_counts']['open'] == 2
    assert data['case_counts']['overdue'] == 1
    assert data['total_open'] == 3
    assert 'date' in data
    assert 'generated_at' in data


def test_tages_summary_dms_state_none_on_failure(monkeypatch, tmp_path):
    """If MemoryCuratorService raises, dms_state should be None (graceful)."""
    client = _build_app(monkeypatch, tmp_path)
    with (
        patch('app.api.n8n_endpoints.get_case_repository') as mock_repo_fn,
        patch('app.memory_curator.service.MemoryCuratorService', side_effect=ImportError('not found')),
    ):
        repo = MagicMock()
        repo.list_cases = AsyncMock(return_value=[])
        mock_repo_fn.return_value = repo
        resp = client.post('/api/n8n/tages-summary', json=_tenant_body(), headers=_auth_headers())
    assert resp.status_code == 200
    assert resp.json()['dms_state'] is None


def test_tages_summary_tenant_id_in_response(monkeypatch, tmp_path):
    client = _build_app(monkeypatch, tmp_path)
    with (
        patch('app.api.n8n_endpoints.get_case_repository') as mock_repo_fn,
        patch('app.memory_curator.service.MemoryCuratorService', side_effect=Exception),
    ):
        repo = MagicMock()
        repo.list_cases = AsyncMock(return_value=[])
        mock_repo_fn.return_value = repo
        resp = client.post('/api/n8n/tages-summary', json=_tenant_body(), headers=_auth_headers())
    assert resp.json()['tenant_id'] == TENANT_ID
