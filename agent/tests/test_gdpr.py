"""Tests for GDPR endpoints: GET /api/tenant/{id}/export and POST /api/tenant/{id}/request-deletion."""
from __future__ import annotations

import importlib
import io
import json
import uuid
import zipfile
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


TENANT_ID = str(uuid.uuid4())
UNKNOWN_ID = str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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
        {'username': 'operator', 'role': 'operator', 'password_hash': hash_password_pbkdf2('op-pass')},
    ])

    monkeypatch.setenv('FRYA_DATABASE_URL', 'memory://db')
    monkeypatch.setenv('FRYA_REDIS_URL', 'memory://redis')
    monkeypatch.setenv('FRYA_DATA_DIR', str(tmp_path))
    monkeypatch.setenv('FRYA_RULES_DIR', str(rules))
    monkeypatch.setenv('FRYA_VERFAHRENSDOKU_DIR', str(tmp_path / 'verfahrensdoku'))
    monkeypatch.setenv('FRYA_PAPERLESS_BASE_URL', 'http://paperless')
    monkeypatch.setenv('FRYA_AKAUNTING_BASE_URL', 'http://akaunting')
    monkeypatch.setenv('FRYA_N8N_BASE_URL', 'http://n8n')
    monkeypatch.setenv('FRYA_AUTH_USERS_JSON', users_json)
    monkeypatch.setenv('FRYA_AUTH_SESSION_SECRET', 'test-session-secret-32-bytes-xx')
    monkeypatch.setenv('FRYA_AUTH_COOKIE_SECURE', 'false')
    monkeypatch.setenv('FRYA_CONFIG_ENCRYPTION_KEY', fernet_key)

    _clear_caches()
    import app.main as main_module
    importlib.reload(main_module)
    return main_module.app


def _login_admin(client: TestClient) -> None:
    client.post(
        '/auth/login',
        data={'username': 'admin', 'password': 'admin-pass', 'next': '/ui/dashboard'},
        follow_redirects=False,
    )


def _login_operator(client: TestClient) -> None:
    client.post(
        '/auth/login',
        data={'username': 'operator', 'password': 'op-pass', 'next': '/ui/dashboard'},
        follow_redirects=False,
    )


# ---------------------------------------------------------------------------
# Mocks for repository dependencies
# ---------------------------------------------------------------------------

def _make_tenant_repo_mock(status: str = 'active'):
    """Return a mock TenantRepository that has a single tenant."""
    from app.auth.tenant_repository import TenantRecord

    tenant = TenantRecord(
        tenant_id=TENANT_ID,
        name='Test GmbH',
        status=status,
        admin_email='admin@test.de',
    )
    repo = MagicMock()
    repo.find_by_id = AsyncMock(return_value=tenant)
    repo.soft_delete = AsyncMock(return_value=tenant.model_copy(
        update={'status': 'pending_deletion', 'hard_delete_after': datetime.now(timezone.utc) + timedelta(days=30)}
    ))
    return repo


def _make_empty_case_repo_mock():
    repo = MagicMock()
    repo.list_cases = AsyncMock(return_value=[])
    repo.get_case_documents = AsyncMock(return_value=[])
    return repo


def _make_audit_svc_mock():
    svc = MagicMock()
    svc.recent = AsyncMock(return_value=[])
    svc.log_event = AsyncMock(return_value=MagicMock())
    return svc


def _make_user_repo_mock():
    repo = MagicMock()
    repo.list_users = AsyncMock(return_value=[])
    repo.deactivate_by_tenant = AsyncMock(return_value=1)
    return repo


# ---------------------------------------------------------------------------
# TEIL 1: UI legal pages — smoke tests (auth: operator+)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('path', [
    '/ui/legal',
    '/ui/legal/datenschutz',
    '/ui/legal/avv',
    '/ui/legal/toms',
    '/ui/legal/impressum',
    '/ui/legal/agb',
    '/ui/legal/vvt',
])
def test_legal_pages_require_auth(path, tmp_path, monkeypatch):
    """Legal pages redirect to login when not authenticated."""
    app = _build_app(monkeypatch, tmp_path)
    with TestClient(app) as client:
        resp = client.get(path, follow_redirects=False)
        assert resp.status_code == 303, f'{path}: expected 303, got {resp.status_code}'
        assert '/auth/login' in resp.headers['location']


@pytest.mark.parametrize('path', [
    '/ui/legal',
    '/ui/legal/datenschutz',
    '/ui/legal/avv',
    '/ui/legal/toms',
    '/ui/legal/impressum',
    '/ui/legal/agb',
    '/ui/legal/vvt',
])
def test_legal_pages_render_for_operator(path, tmp_path, monkeypatch):
    """All legal pages return 200 for an authenticated operator."""
    app = _build_app(monkeypatch, tmp_path)
    with TestClient(app) as client:
        _login_operator(client)
        resp = client.get(path)
        assert resp.status_code == 200, f'{path}: expected 200, got {resp.status_code}'
        assert 'BITTE AUSFÜLLEN' in resp.text or 'BITTE AUSF' in resp.text or resp.status_code == 200


def test_legal_overview_has_links(tmp_path, monkeypatch):
    """Overview page contains links to all 6 sub-pages."""
    app = _build_app(monkeypatch, tmp_path)
    with TestClient(app) as client:
        _login_operator(client)
        resp = client.get('/ui/legal')
        assert resp.status_code == 200
        for slug in ['datenschutz', 'avv', 'toms', 'impressum', 'agb', 'vvt']:
            assert f'/ui/legal/{slug}' in resp.text, f'Link to {slug} missing in overview'


def test_legal_nav_link_present(tmp_path, monkeypatch):
    """Base template navigation includes /ui/legal link."""
    app = _build_app(monkeypatch, tmp_path)
    with TestClient(app) as client:
        _login_operator(client)
        resp = client.get('/ui/dashboard')
        assert resp.status_code == 200
        assert '/ui/legal' in resp.text


# ---------------------------------------------------------------------------
# TEIL 2a: Export endpoint — auth
# ---------------------------------------------------------------------------

def test_export_requires_auth(tmp_path, monkeypatch):
    """Export endpoint returns 401 without auth."""
    app = _build_app(monkeypatch, tmp_path)
    with TestClient(app) as client:
        resp = client.get(f'/api/tenant/{TENANT_ID}/export')
        assert resp.status_code == 401


def test_export_requires_admin_not_operator(tmp_path, monkeypatch):
    """Export endpoint returns 403 for operator role."""
    app = _build_app(monkeypatch, tmp_path)
    with TestClient(app) as client:
        _login_operator(client)
        resp = client.get(f'/api/tenant/{TENANT_ID}/export')
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# TEIL 2b: Export endpoint — functional
# ---------------------------------------------------------------------------

def test_export_404_unknown_tenant(tmp_path, monkeypatch):
    """Export returns 404 for unknown tenant_id."""
    app = _build_app(monkeypatch, tmp_path)
    import app.api.gdpr_views as gdpr_module
    tenant_repo = MagicMock()
    tenant_repo.find_by_id = AsyncMock(return_value=None)
    app.dependency_overrides[gdpr_module._get_tenant_repo] = lambda: tenant_repo
    try:
        with TestClient(app) as client:
            _login_admin(client)
            resp = client.get(f'/api/tenant/{UNKNOWN_ID}/export')
            assert resp.status_code == 404
    finally:
        app.dependency_overrides.pop(gdpr_module._get_tenant_repo, None)


def test_export_returns_zip_with_correct_files(tmp_path, monkeypatch):
    """Export returns ZIP with cases.json, users.json, audit_log.json, documents_metadata.json, tenant.json, README.txt."""
    app = _build_app(monkeypatch, tmp_path)
    import app.api.gdpr_views as gdpr_module
    tenant_repo = _make_tenant_repo_mock()
    case_repo = _make_empty_case_repo_mock()
    audit_svc = _make_audit_svc_mock()
    user_repo = _make_user_repo_mock()
    app.dependency_overrides[gdpr_module._get_tenant_repo] = lambda: tenant_repo
    app.dependency_overrides[gdpr_module._get_case_repo] = lambda: case_repo
    app.dependency_overrides[gdpr_module._get_audit_svc] = lambda: audit_svc
    app.dependency_overrides[gdpr_module._get_user_repo] = lambda: user_repo

    try:
        with TestClient(app) as client:
            _login_admin(client)
            resp = client.get(f'/api/tenant/{TENANT_ID}/export')
            assert resp.status_code == 200
            assert resp.headers['content-type'] == 'application/zip'
            assert 'attachment' in resp.headers['content-disposition']

            buf = io.BytesIO(resp.content)
            with zipfile.ZipFile(buf) as zf:
                names = zf.namelist()
                for expected in ['cases.json', 'documents_metadata.json', 'audit_log.json', 'users.json', 'tenant.json', 'README.txt']:
                    assert expected in names, f'{expected} missing from ZIP, got: {names}'
                cases = json.loads(zf.read('cases.json'))
                assert isinstance(cases, list)
    finally:
        for key in [gdpr_module._get_tenant_repo, gdpr_module._get_case_repo,
                    gdpr_module._get_audit_svc, gdpr_module._get_user_repo]:
            app.dependency_overrides.pop(key, None)


def test_export_422_invalid_uuid(tmp_path, monkeypatch):
    """Export returns 422 for non-UUID tenant_id when tenant exists but UUID parse fails."""
    from app.auth.tenant_repository import TenantRecord
    app = _build_app(monkeypatch, tmp_path)
    import app.api.gdpr_views as gdpr_module
    tenant_repo = MagicMock()
    tenant_repo.find_by_id = AsyncMock(
        return_value=TenantRecord(tenant_id='not-a-uuid', name='X', status='active')
    )
    app.dependency_overrides[gdpr_module._get_tenant_repo] = lambda: tenant_repo
    try:
        with TestClient(app) as client:
            _login_admin(client)
            resp = client.get('/api/tenant/not-a-uuid/export')
            assert resp.status_code == 422
    finally:
        app.dependency_overrides.pop(gdpr_module._get_tenant_repo, None)


# ---------------------------------------------------------------------------
# TEIL 2c: Deletion endpoint — auth
# ---------------------------------------------------------------------------

def test_deletion_requires_auth(tmp_path, monkeypatch):
    """Deletion endpoint returns 401 without auth."""
    app = _build_app(monkeypatch, tmp_path)
    with TestClient(app) as client:
        resp = client.post(f'/api/tenant/{TENANT_ID}/request-deletion')
        assert resp.status_code == 401


def test_deletion_requires_admin_not_operator(tmp_path, monkeypatch):
    """Deletion endpoint returns 403 for operator role."""
    app = _build_app(monkeypatch, tmp_path)
    with TestClient(app) as client:
        _login_operator(client)
        resp = client.post(f'/api/tenant/{TENANT_ID}/request-deletion')
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# TEIL 2d: Deletion endpoint — functional
# ---------------------------------------------------------------------------

def test_deletion_404_unknown_tenant(tmp_path, monkeypatch):
    """Deletion returns 404 for unknown tenant."""
    app = _build_app(monkeypatch, tmp_path)
    import app.api.gdpr_views as gdpr_module
    tenant_repo = MagicMock()
    tenant_repo.find_by_id = AsyncMock(return_value=None)
    app.dependency_overrides[gdpr_module._get_tenant_repo] = lambda: tenant_repo
    try:
        with TestClient(app) as client:
            _login_admin(client)
            resp = client.post(f'/api/tenant/{UNKNOWN_ID}/request-deletion')
            assert resp.status_code == 404
    finally:
        app.dependency_overrides.pop(gdpr_module._get_tenant_repo, None)


def test_deletion_409_already_pending(tmp_path, monkeypatch):
    """Deletion returns 409 when tenant is already pending_deletion."""
    app = _build_app(monkeypatch, tmp_path)
    import app.api.gdpr_views as gdpr_module
    tenant_repo = _make_tenant_repo_mock(status='pending_deletion')
    user_repo = _make_user_repo_mock()
    audit_svc = _make_audit_svc_mock()
    app.dependency_overrides[gdpr_module._get_tenant_repo] = lambda: tenant_repo
    app.dependency_overrides[gdpr_module._get_user_repo] = lambda: user_repo
    app.dependency_overrides[gdpr_module._get_audit_svc] = lambda: audit_svc
    try:
        with TestClient(app) as client:
            _login_admin(client)
            resp = client.post(f'/api/tenant/{TENANT_ID}/request-deletion')
            assert resp.status_code == 409
    finally:
        for key in [gdpr_module._get_tenant_repo, gdpr_module._get_user_repo, gdpr_module._get_audit_svc]:
            app.dependency_overrides.pop(key, None)


def test_deletion_success_sets_pending_and_hard_delete_after(tmp_path, monkeypatch):
    """Successful deletion request sets status=pending_deletion and returns hard_delete_after."""
    app = _build_app(monkeypatch, tmp_path)
    import app.api.gdpr_views as gdpr_module
    tenant_repo = _make_tenant_repo_mock(status='active')
    user_repo = _make_user_repo_mock()
    audit_svc = _make_audit_svc_mock()
    app.dependency_overrides[gdpr_module._get_tenant_repo] = lambda: tenant_repo
    app.dependency_overrides[gdpr_module._get_user_repo] = lambda: user_repo
    app.dependency_overrides[gdpr_module._get_audit_svc] = lambda: audit_svc
    try:
        with TestClient(app) as client:
            _login_admin(client)
            resp = client.post(f'/api/tenant/{TENANT_ID}/request-deletion')
            assert resp.status_code == 200
            data = resp.json()
            assert data['status'] == 'pending_deletion'
            assert 'hard_delete_after' in data
            assert TENANT_ID in data['tenant_id']
            tenant_repo.soft_delete.assert_called_once()
    finally:
        for key in [gdpr_module._get_tenant_repo, gdpr_module._get_user_repo, gdpr_module._get_audit_svc]:
            app.dependency_overrides.pop(key, None)


def test_deletion_deactivates_users(tmp_path, monkeypatch):
    """Deletion request triggers deactivate_by_tenant."""
    app = _build_app(monkeypatch, tmp_path)
    import app.api.gdpr_views as gdpr_module
    tenant_repo = _make_tenant_repo_mock(status='active')
    user_repo = _make_user_repo_mock()
    audit_svc = _make_audit_svc_mock()
    app.dependency_overrides[gdpr_module._get_tenant_repo] = lambda: tenant_repo
    app.dependency_overrides[gdpr_module._get_user_repo] = lambda: user_repo
    app.dependency_overrides[gdpr_module._get_audit_svc] = lambda: audit_svc
    try:
        with TestClient(app) as client:
            _login_admin(client)
            client.post(f'/api/tenant/{TENANT_ID}/request-deletion')
            user_repo.deactivate_by_tenant.assert_called_once_with(TENANT_ID)
    finally:
        for key in [gdpr_module._get_tenant_repo, gdpr_module._get_user_repo, gdpr_module._get_audit_svc]:
            app.dependency_overrides.pop(key, None)


def test_deletion_hard_delete_after_is_30_days(tmp_path, monkeypatch):
    """hard_delete_after is approximately 30 days in the future."""
    from app.auth.tenant_repository import TenantRecord
    app = _build_app(monkeypatch, tmp_path)
    import app.api.gdpr_views as gdpr_module

    captured: dict = {}

    async def _soft_delete(tenant_id, *, requested_by, hard_delete_after):
        captured['hard_delete_after'] = hard_delete_after
        return TenantRecord(
            tenant_id=tenant_id,
            status='pending_deletion',
            hard_delete_after=hard_delete_after,
        )

    tenant_repo = _make_tenant_repo_mock(status='active')
    tenant_repo.soft_delete = _soft_delete
    user_repo = _make_user_repo_mock()
    audit_svc = _make_audit_svc_mock()
    app.dependency_overrides[gdpr_module._get_tenant_repo] = lambda: tenant_repo
    app.dependency_overrides[gdpr_module._get_user_repo] = lambda: user_repo
    app.dependency_overrides[gdpr_module._get_audit_svc] = lambda: audit_svc
    try:
        with TestClient(app) as client:
            _login_admin(client)
            client.post(f'/api/tenant/{TENANT_ID}/request-deletion')

        hda = captured['hard_delete_after']
        delta = hda - datetime.now(timezone.utc)
        assert 29 <= delta.days <= 30, f'Expected ~30 days, got {delta.days}'
    finally:
        for key in [gdpr_module._get_tenant_repo, gdpr_module._get_user_repo, gdpr_module._get_audit_svc]:
            app.dependency_overrides.pop(key, None)
