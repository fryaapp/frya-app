"""CaseEngine API + UI integration tests.

Uses the existing test_api_surface pattern (memory backend, TestClient, operator login).
Covers:
  - REST /api/cases endpoints (create, get, list, status, document, reference, assign, merge, conflict)
  - Server-rendered /ui/vorgaenge pages (list, detail, forms)
  - Auth guard (401/redirect without login)
  - Tenant isolation
  - Forbidden status transitions
"""
from __future__ import annotations

import importlib
import json
import re
import uuid
from pathlib import Path

from fastapi.testclient import TestClient


# ── Helpers shared with test_api_surface ──────────────────────────────────────

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
        'orchestrator_policy.md',
        'runtime_policy.md',
        'gobd_compliance_policy.md',
        'accounting_analyst_policy.md',
        'problemfall_policy.md',
        'freigabematrix.md',
    ]:
        (policies / name).write_text('Version: 1.0\n', encoding='utf-8')


def _build_users_json() -> str:
    from app.auth.service import hash_password_pbkdf2
    return json.dumps([
        {'username': 'operator', 'role': 'operator', 'password_hash': hash_password_pbkdf2('op-pass')},
        {'username': 'admin', 'role': 'admin', 'password_hash': hash_password_pbkdf2('admin-pass')},
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


def _extract_csrf(html: str) -> str:
    m = re.search(r'name="csrf_token"\s+value="([^"]+)"', html)
    assert m, 'csrf_token not found in HTML'
    return m.group(1)


def _login_operator(client: TestClient) -> None:
    res = client.post(
        '/auth/login',
        data={'username': 'operator', 'password': 'op-pass', 'next': '/ui/dashboard'},
        follow_redirects=False,
    )
    assert res.status_code == 303


def _get_csrf(client: TestClient, path: str) -> str:
    res = client.get(path)
    assert res.status_code == 200
    return _extract_csrf(res.text)


# ── Fixtures ──────────────────────────────────────────────────────────────────

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
    monkeypatch.setenv('FRYA_AUTH_SESSION_SECRET', 'test-secret-ce')
    monkeypatch.setenv('FRYA_AUTH_COOKIE_SECURE', 'false')
    app = _build_app()
    client = TestClient(app, raise_server_exceptions=True)
    client.__enter__()
    return client


# ── Test 1: API requires auth ─────────────────────────────────────────────────

def test_api_requires_auth(tmp_path, monkeypatch):
    client = _setup(tmp_path, monkeypatch)
    try:
        res = client.get('/api/cases', params={'tenant_id': str(uuid.uuid4())})
        assert res.status_code == 401
    finally:
        client.__exit__(None, None, None)


# ── Test 2: Create case via REST API ──────────────────────────────────────────

def test_api_create_and_get_case(tmp_path, monkeypatch):
    client = _setup(tmp_path, monkeypatch)
    try:
        _login_operator(client)
        csrf = _get_csrf(client, '/ui/dashboard')
        tenant_id = str(uuid.uuid4())

        res = client.post(
            '/api/cases',
            json={'tenant_id': tenant_id, 'case_type': 'incoming_invoice', 'vendor_name': 'ACME GmbH'},
            headers={'x-frya-csrf-token': csrf},
        )
        assert res.status_code == 201
        body = res.json()
        assert body['status'] == 'DRAFT'
        assert body['vendor_name'] == 'ACME GmbH'
        case_id = body['id']

        # GET detail
        res2 = client.get(f'/api/cases/{case_id}')
        assert res2.status_code == 200
        detail = res2.json()
        assert detail['id'] == case_id
        assert detail['documents'] == []
    finally:
        client.__exit__(None, None, None)


# ── Test 3: List cases with tenant filter ─────────────────────────────────────

def test_api_list_cases_tenant_filter(tmp_path, monkeypatch):
    client = _setup(tmp_path, monkeypatch)
    try:
        _login_operator(client)
        csrf = _get_csrf(client, '/ui/dashboard')
        t1 = str(uuid.uuid4())
        t2 = str(uuid.uuid4())

        client.post('/api/cases', json={'tenant_id': t1, 'case_type': 'contract'}, headers={'x-frya-csrf-token': csrf})
        client.post('/api/cases', json={'tenant_id': t2, 'case_type': 'receipt'}, headers={'x-frya-csrf-token': csrf})

        res = client.get('/api/cases', params={'tenant_id': t1})
        assert res.status_code == 200
        cases = res.json()
        assert len(cases) == 1
        assert cases[0]['case_type'] == 'contract'
    finally:
        client.__exit__(None, None, None)


# ── Test 4: Add document to case ──────────────────────────────────────────────

def test_api_add_document(tmp_path, monkeypatch):
    client = _setup(tmp_path, monkeypatch)
    try:
        _login_operator(client)
        csrf = _get_csrf(client, '/ui/dashboard')
        tenant_id = str(uuid.uuid4())

        create_res = client.post(
            '/api/cases',
            json={'tenant_id': tenant_id, 'case_type': 'incoming_invoice'},
            headers={'x-frya-csrf-token': csrf},
        )
        case_id = create_res.json()['id']

        doc_res = client.post(
            f'/api/cases/{case_id}/documents',
            json={
                'document_source': 'paperless',
                'document_source_id': '42',
                'assignment_confidence': 'HIGH',
                'assignment_method': 'manual',
                'filename': 'rechnung.pdf',
            },
            headers={'x-frya-csrf-token': csrf},
        )
        assert doc_res.status_code == 200

        detail = client.get(f'/api/cases/{case_id}').json()
        assert len(detail['documents']) == 1
        assert detail['documents'][0]['filename'] == 'rechnung.pdf'
    finally:
        client.__exit__(None, None, None)


# ── Test 5: Add reference to case ─────────────────────────────────────────────

def test_api_add_reference(tmp_path, monkeypatch):
    client = _setup(tmp_path, monkeypatch)
    try:
        _login_operator(client)
        csrf = _get_csrf(client, '/ui/dashboard')
        tenant_id = str(uuid.uuid4())

        case_id = client.post(
            '/api/cases',
            json={'tenant_id': tenant_id, 'case_type': 'incoming_invoice'},
            headers={'x-frya-csrf-token': csrf},
        ).json()['id']

        ref_res = client.post(
            f'/api/cases/{case_id}/references',
            json={'reference_type': 'invoice_number', 'reference_value': 'INV-2024-001'},
            headers={'x-frya-csrf-token': csrf},
        )
        assert ref_res.status_code == 200

        detail = client.get(f'/api/cases/{case_id}').json()
        refs = detail.get('references', [])
        assert any(r['reference_value'] == 'INV-2024-001' for r in refs)
    finally:
        client.__exit__(None, None, None)


# ── Test 6: Status update DRAFT→OPEN (requires document first) ────────────────

def test_api_status_draft_to_open(tmp_path, monkeypatch):
    client = _setup(tmp_path, monkeypatch)
    try:
        _login_operator(client)
        csrf = _get_csrf(client, '/ui/dashboard')
        tenant_id = str(uuid.uuid4())

        case_id = client.post(
            '/api/cases',
            json={'tenant_id': tenant_id, 'case_type': 'incoming_invoice'},
            headers={'x-frya-csrf-token': csrf},
        ).json()['id']

        # Transition to OPEN without document should fail
        bad_res = client.patch(
            f'/api/cases/{case_id}/status',
            json={'status': 'OPEN'},
            headers={'x-frya-csrf-token': csrf},
        )
        assert bad_res.status_code == 422

        # Add document then retry
        client.post(
            f'/api/cases/{case_id}/documents',
            json={'document_source': 'manual', 'document_source_id': 'doc-1',
                  'assignment_confidence': 'MEDIUM', 'assignment_method': 'manual'},
            headers={'x-frya-csrf-token': csrf},
        )
        ok_res = client.patch(
            f'/api/cases/{case_id}/status',
            json={'status': 'OPEN'},
            headers={'x-frya-csrf-token': csrf},
        )
        assert ok_res.status_code == 200
        assert ok_res.json()['status'] == 'OPEN'
    finally:
        client.__exit__(None, None, None)


# ── Test 7: Status update OPEN→PAID ──────────────────────────────────────────

def test_api_status_open_to_paid(tmp_path, monkeypatch):
    client = _setup(tmp_path, monkeypatch)
    try:
        _login_operator(client)
        csrf = _get_csrf(client, '/ui/dashboard')
        tenant_id = str(uuid.uuid4())

        case_id = client.post(
            '/api/cases',
            json={'tenant_id': tenant_id, 'case_type': 'incoming_invoice'},
            headers={'x-frya-csrf-token': csrf},
        ).json()['id']
        client.post(
            f'/api/cases/{case_id}/documents',
            json={'document_source': 'manual', 'document_source_id': 'x',
                  'assignment_confidence': 'MEDIUM', 'assignment_method': 'manual'},
            headers={'x-frya-csrf-token': csrf},
        )
        client.patch(f'/api/cases/{case_id}/status', json={'status': 'OPEN'}, headers={'x-frya-csrf-token': csrf})

        paid_res = client.patch(
            f'/api/cases/{case_id}/status',
            json={'status': 'PAID'},
            headers={'x-frya-csrf-token': csrf},
        )
        assert paid_res.status_code == 200
        assert paid_res.json()['status'] == 'PAID'
    finally:
        client.__exit__(None, None, None)


# ── Test 8: Forbidden transition (DRAFT→PAID) ─────────────────────────────────

def test_api_forbidden_transition(tmp_path, monkeypatch):
    client = _setup(tmp_path, monkeypatch)
    try:
        _login_operator(client)
        csrf = _get_csrf(client, '/ui/dashboard')
        tenant_id = str(uuid.uuid4())

        case_id = client.post(
            '/api/cases',
            json={'tenant_id': tenant_id, 'case_type': 'receipt'},
            headers={'x-frya-csrf-token': csrf},
        ).json()['id']

        res = client.patch(
            f'/api/cases/{case_id}/status',
            json={'status': 'PAID'},
            headers={'x-frya-csrf-token': csrf},
        )
        assert res.status_code == 422
    finally:
        client.__exit__(None, None, None)


# ── Test 9: Merge two cases ───────────────────────────────────────────────────

def test_api_merge_cases(tmp_path, monkeypatch):
    client = _setup(tmp_path, monkeypatch)
    try:
        _login_operator(client)
        csrf = _get_csrf(client, '/ui/dashboard')
        tenant_id = str(uuid.uuid4())

        def _make_open_case() -> str:
            cid = client.post(
                '/api/cases',
                json={'tenant_id': tenant_id, 'case_type': 'incoming_invoice'},
                headers={'x-frya-csrf-token': csrf},
            ).json()['id']
            client.post(
                f'/api/cases/{cid}/documents',
                json={'document_source': 'manual', 'document_source_id': cid[:8],
                      'assignment_confidence': 'MEDIUM', 'assignment_method': 'manual'},
                headers={'x-frya-csrf-token': csrf},
            )
            client.patch(f'/api/cases/{cid}/status', json={'status': 'OPEN'}, headers={'x-frya-csrf-token': csrf})
            return cid

        source_id = _make_open_case()
        target_id = _make_open_case()

        merge_res = client.post(
            f'/api/cases/{source_id}/merge',
            json={'target_case_id': target_id},
            headers={'x-frya-csrf-token': csrf},
        )
        assert merge_res.status_code == 200

        source_detail = client.get(f'/api/cases/{source_id}').json()
        assert source_detail['status'] == 'MERGED'
    finally:
        client.__exit__(None, None, None)


# ── Test 10: Create and resolve conflict ──────────────────────────────────────

def test_api_create_resolve_conflict(tmp_path, monkeypatch):
    client = _setup(tmp_path, monkeypatch)
    try:
        _login_operator(client)
        csrf = _get_csrf(client, '/ui/dashboard')
        tenant_id = str(uuid.uuid4())

        case_id = client.post(
            '/api/cases',
            json={'tenant_id': tenant_id, 'case_type': 'dunning'},
            headers={'x-frya-csrf-token': csrf},
        ).json()['id']

        # Create conflict via repo directly (no dedicated POST in API for conflicts)
        from app.dependencies import get_case_repository
        import asyncio
        repo = get_case_repository()
        conflict = asyncio.run(repo.create_conflict(
            case_id=uuid.UUID(case_id),
            conflict_type='amount_mismatch',
            description='Betrag stimmt nicht',
        ))

        conflicts_res = client.get(f'/api/cases/{case_id}/conflicts')
        assert conflicts_res.status_code == 200
        conflicts = conflicts_res.json()
        assert len(conflicts) == 1
        conflict_id = conflicts[0]['id']

        resolve_res = client.patch(
            f'/api/cases/conflicts/{conflict_id}',
            json={'resolution': 'resolved_manual', 'resolved_by': 'operator'},
            headers={'x-frya-csrf-token': csrf},
        )
        assert resolve_res.status_code == 200
        assert resolve_res.json()['resolution'] == 'resolved_manual'
    finally:
        client.__exit__(None, None, None)


# ── Test 11: 404 for unknown case ─────────────────────────────────────────────

def test_api_unknown_case_404(tmp_path, monkeypatch):
    client = _setup(tmp_path, monkeypatch)
    try:
        _login_operator(client)
        res = client.get(f'/api/cases/{uuid.uuid4()}')
        assert res.status_code == 404
    finally:
        client.__exit__(None, None, None)


# ── Test 12: Auto-assign by reference ─────────────────────────────────────────

def test_api_assign_by_reference(tmp_path, monkeypatch):
    client = _setup(tmp_path, monkeypatch)
    try:
        _login_operator(client)
        csrf = _get_csrf(client, '/ui/dashboard')
        tenant_id = str(uuid.uuid4())

        case_id = client.post(
            '/api/cases',
            json={'tenant_id': tenant_id, 'case_type': 'incoming_invoice'},
            headers={'x-frya-csrf-token': csrf},
        ).json()['id']

        client.post(
            f'/api/cases/{case_id}/references',
            json={'reference_type': 'invoice_number', 'reference_value': 'INV-2025-999'},
            headers={'x-frya-csrf-token': csrf},
        )

        assign_res = client.post(
            '/api/cases/assign',
            json={
                'tenant_id': tenant_id,
                'document_source': 'paperless',
                'document_source_id': '77',
                'reference_values': [['invoice_number', 'INV-2025-999']],
            },
            headers={'x-frya-csrf-token': csrf},
        )
        assert assign_res.status_code == 200
        body = assign_res.json()
        assert body['case_id'] == case_id
        assert body['confidence'] == 'CERTAIN'
    finally:
        client.__exit__(None, None, None)


# ── Test 13: UI list page loads (anonymous → redirect) ────────────────────────

def test_ui_vorgaenge_list_anon_redirect(tmp_path, monkeypatch):
    client = _setup(tmp_path, monkeypatch)
    try:
        res = client.get('/ui/vorgaenge', follow_redirects=False)
        assert res.status_code == 303
        assert '/auth/login' in res.headers['location']
    finally:
        client.__exit__(None, None, None)


# ── Test 14: UI list page loads for operator ──────────────────────────────────

def test_ui_vorgaenge_list_ok(tmp_path, monkeypatch):
    client = _setup(tmp_path, monkeypatch)
    try:
        _login_operator(client)
        res = client.get('/ui/vorgaenge')
        assert res.status_code == 200
        assert 'Vorgaenge' in res.text
    finally:
        client.__exit__(None, None, None)


# ── Test 15: UI detail page renders case ─────────────────────────────────────

def test_ui_vorgang_detail_ok(tmp_path, monkeypatch):
    client = _setup(tmp_path, monkeypatch)
    try:
        _login_operator(client)
        csrf = _get_csrf(client, '/ui/dashboard')
        tenant_id = str(uuid.uuid4())

        case_id = client.post(
            '/api/cases',
            json={'tenant_id': tenant_id, 'case_type': 'contract', 'vendor_name': 'TestCorp'},
            headers={'x-frya-csrf-token': csrf},
        ).json()['id']

        res = client.get(f'/ui/vorgaenge/{case_id}', params={'tenant_id': tenant_id})
        assert res.status_code == 200
        assert 'TestCorp' in res.text
        assert 'contract' in res.text
    finally:
        client.__exit__(None, None, None)


# ── Test 16: UI detail 404 for unknown case ───────────────────────────────────

def test_ui_vorgang_detail_404(tmp_path, monkeypatch):
    client = _setup(tmp_path, monkeypatch)
    try:
        _login_operator(client)
        res = client.get(f'/ui/vorgaenge/{uuid.uuid4()}')
        assert res.status_code == 404
    finally:
        client.__exit__(None, None, None)


# ── Test 17: UI create form creates case and redirects to detail ──────────────

def test_ui_create_case_form(tmp_path, monkeypatch):
    client = _setup(tmp_path, monkeypatch)
    try:
        _login_operator(client)
        tenant_id = str(uuid.uuid4())
        csrf = _get_csrf(client, '/ui/vorgaenge')

        res = client.post(
            '/ui/vorgaenge',
            data={
                'tenant_id': tenant_id,
                'case_type': 'receipt',
                'vendor_name': 'Lidl',
                'csrf_token': csrf,
            },
            follow_redirects=False,
        )
        assert res.status_code == 303
        location = res.headers['location']
        assert '/ui/vorgaenge/' in location

        # Follow redirect to detail page
        detail_res = client.get(location)
        assert detail_res.status_code == 200
        assert 'Lidl' in detail_res.text
    finally:
        client.__exit__(None, None, None)


# ── Test 18: Tenant isolation — cannot see other tenant's cases ───────────────

def test_api_tenant_isolation(tmp_path, monkeypatch):
    client = _setup(tmp_path, monkeypatch)
    try:
        _login_operator(client)
        csrf = _get_csrf(client, '/ui/dashboard')
        t1 = str(uuid.uuid4())
        t2 = str(uuid.uuid4())

        client.post('/api/cases', json={'tenant_id': t1, 'case_type': 'receipt'}, headers={'x-frya-csrf-token': csrf})
        client.post('/api/cases', json={'tenant_id': t1, 'case_type': 'incoming_invoice'}, headers={'x-frya-csrf-token': csrf})
        client.post('/api/cases', json={'tenant_id': t2, 'case_type': 'contract'}, headers={'x-frya-csrf-token': csrf})

        t1_cases = client.get('/api/cases', params={'tenant_id': t1}).json()
        t2_cases = client.get('/api/cases', params={'tenant_id': t2}).json()

        assert len(t1_cases) == 2
        assert len(t2_cases) == 1
        assert all(c['tenant_id'] == t1 for c in t1_cases)
        assert all(c['tenant_id'] == t2 for c in t2_cases)
    finally:
        client.__exit__(None, None, None)
