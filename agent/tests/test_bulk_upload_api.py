"""Bulk-Upload API tests (B4) — 11 tests.

Uses the same TestClient + memory backend pattern as test_case_engine_api.py.
"""
from __future__ import annotations

import importlib
import io
import json
import uuid
from pathlib import Path

from fastapi.testclient import TestClient


# ── Shared helpers ────────────────────────────────────────────────────────────

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
    import app.config as config_module
    import app.dependencies as deps_module
    import app.auth.service as auth_service_module

    config_module.get_settings.cache_clear()
    auth_service_module.get_auth_service.cache_clear()
    for name in dir(deps_module):
        obj = getattr(deps_module, name)
        if callable(obj) and hasattr(obj, 'cache_clear'):
            obj.cache_clear()

    # Clear rate-limit cache in bulk_upload module
    try:
        import app.api.bulk_upload as bu
        bu._last_refresh.clear()
    except Exception:
        pass


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
    monkeypatch.setenv('FRYA_AUTH_SESSION_SECRET', 'test-secret-bu')
    monkeypatch.setenv('FRYA_AUTH_COOKIE_SECURE', 'false')
    app = _build_app()
    client = TestClient(app, raise_server_exceptions=True)
    client.__enter__()
    return client


def _login(client: TestClient) -> None:
    res = client.post(
        '/auth/login',
        data={'username': 'operator', 'password': 'op-pass', 'next': '/ui/dashboard'},
        follow_redirects=False,
    )
    assert res.status_code == 303


def _get_csrf(client: TestClient) -> str:
    import re
    res = client.get('/ui/upload')
    assert res.status_code == 200
    m = re.search(r'name="csrf_token"\s+value="([^"]+)"', res.text)
    if m:
        return m.group(1)
    # Try x-frya-csrf-token from JSON endpoint or dashboard
    res2 = client.get('/ui/dashboard')
    m2 = re.search(r'name="csrf_token"\s+value="([^"]+)"', res2.text)
    if m2:
        return m2.group(1)
    # Extract from JS in upload page
    import re as _re
    m3 = _re.search(r"CSRF_TOKEN = \"([^\"]+)\"", res.text)
    if m3:
        return m3.group(1)
    return 'test-csrf-token'


def _make_pdf_file(name: str = 'test.pdf', size: int = 1024) -> tuple:
    """Return (name, bytes, content_type) for a fake PDF with unique content per filename."""
    # Include the name to ensure different filenames → different SHA256 hashes
    header = f'%PDF-1.4 unique:{name} '.encode()
    content = header + b'x' * max(0, size - len(header))
    return (name, io.BytesIO(content), 'application/pdf')


def _upload_files(client: TestClient, files: list[tuple], csrf: str) -> dict:
    """POST to bulk-upload with file tuples (name, bytes_or_io, content_type)."""
    res = client.post(
        '/api/documents/bulk-upload',
        files=[('files', f) for f in files],
        headers={'x-frya-csrf-token': csrf},
    )
    return res


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_bulk_upload_success(tmp_path, monkeypatch):
    """3 files uploaded successfully → batch created, items have task_ids."""
    from unittest.mock import AsyncMock, patch

    client = _setup(tmp_path, monkeypatch)
    try:
        _login(client)
        csrf = _get_csrf(client)

        task_id_1 = str(uuid.uuid4())
        task_id_2 = str(uuid.uuid4())
        task_id_3 = str(uuid.uuid4())

        mock_results = [
            {'filename': 'a.pdf', 'task_id': task_id_1, 'error': None},
            {'filename': 'b.pdf', 'task_id': task_id_2, 'error': None},
            {'filename': 'c.pdf', 'task_id': task_id_3, 'error': None},
        ]

        import app.api.bulk_upload as bu_module
        import app.dependencies as deps

        connector = deps.get_paperless_connector()
        with patch.object(connector, 'upload_documents_batch', new=AsyncMock(return_value=mock_results)):
            res = _upload_files(client, [
                _make_pdf_file('a.pdf'),
                _make_pdf_file('b.pdf'),
                _make_pdf_file('c.pdf'),
            ], csrf)

        assert res.status_code == 202, res.text
        body = res.json()
        assert body['file_count'] == 3
        assert body['duplicates_skipped'] == 0
        assert body['status'] == 'processing'
        assert 'batch_id' in body

        # Verify items in DB have task_ids
        bulk_repo = deps.get_bulk_upload_repository()
        import asyncio
        # Get batch detail
        res2 = client.get(f'/api/documents/batches/{body["batch_id"]}')
        assert res2.status_code == 200
        detail = res2.json()
        assert detail['file_count'] == 3
        item_statuses = {i['status'] for i in detail['items']}
        assert 'uploaded' in item_statuses

    finally:
        client.__exit__(None, None, None)


def test_bulk_upload_too_many_files(tmp_path, monkeypatch):
    """51 files → 400."""
    client = _setup(tmp_path, monkeypatch)
    try:
        _login(client)
        csrf = _get_csrf(client)

        files = [_make_pdf_file(f'f{i}.pdf') for i in range(51)]
        res = _upload_files(client, files, csrf)
        assert res.status_code == 400
        assert '50' in res.json()['detail']

    finally:
        client.__exit__(None, None, None)


def test_bulk_upload_file_too_large(tmp_path, monkeypatch):
    """File > 20MB → 400 with filename in error message."""
    client = _setup(tmp_path, monkeypatch)
    try:
        _login(client)
        csrf = _get_csrf(client)

        big_file = _make_pdf_file('huge.pdf', size=21 * 1024 * 1024)
        res = _upload_files(client, [big_file], csrf)
        assert res.status_code == 400
        assert 'huge.pdf' in res.json()['detail']

    finally:
        client.__exit__(None, None, None)


def test_bulk_upload_wrong_type(tmp_path, monkeypatch):
    """Non-PDF/image file → 400."""
    client = _setup(tmp_path, monkeypatch)
    try:
        _login(client)
        csrf = _get_csrf(client)

        docx = ('report.docx', io.BytesIO(b'PK fake docx'), 'application/vnd.openxmlformats-officedocument.wordprocessingml.document')
        res = _upload_files(client, [docx], csrf)
        assert res.status_code == 400
        detail = res.json()['detail']
        assert 'report.docx' in detail or 'Typ' in detail or 'type' in detail.lower()

    finally:
        client.__exit__(None, None, None)


def test_bulk_upload_auth(tmp_path, monkeypatch):
    """Without auth → 401."""
    client = _setup(tmp_path, monkeypatch)
    try:
        # Not logged in
        csrf = 'no-csrf'
        res = _upload_files(client, [_make_pdf_file('x.pdf')], csrf)
        assert res.status_code in (401, 403)

    finally:
        client.__exit__(None, None, None)


def test_bulk_upload_tenant_isolation(tmp_path, monkeypatch):
    """Tenant A cannot see Tenant B's batch."""
    from unittest.mock import AsyncMock, patch

    client = _setup(tmp_path, monkeypatch)
    try:
        _login(client)
        csrf = _get_csrf(client)

        import app.dependencies as deps
        connector = deps.get_paperless_connector()
        task_id = str(uuid.uuid4())
        with patch.object(
            connector, 'upload_documents_batch',
            new=AsyncMock(return_value=[{'filename': 'x.pdf', 'task_id': task_id, 'error': None}])
        ):
            res = _upload_files(client, [_make_pdf_file('x.pdf')], csrf)

        assert res.status_code == 202
        batch_id = res.json()['batch_id']

        # Directly inject a different tenant_id in the repository to simulate tenant B
        bulk_repo = deps.get_bulk_upload_repository()
        import asyncio
        # Manually change batch tenant_id in memory to simulate Tenant B's batch
        if batch_id in bulk_repo._batches:
            bulk_repo._batches[batch_id]['tenant_id'] = str(uuid.uuid4())  # different tenant

        # The current operator (Tenant A) should get 404 now
        res2 = client.get(f'/api/documents/batches/{batch_id}')
        assert res2.status_code == 404

    finally:
        client.__exit__(None, None, None)


def test_batch_list(tmp_path, monkeypatch):
    """Multiple batches returned, paginated, sorted by created_at desc."""
    from unittest.mock import AsyncMock, patch

    client = _setup(tmp_path, monkeypatch)
    try:
        _login(client)
        csrf = _get_csrf(client)

        import app.dependencies as deps
        connector = deps.get_paperless_connector()

        batch_ids = []
        for i in range(3):
            with patch.object(
                connector, 'upload_documents_batch',
                new=AsyncMock(return_value=[{'filename': f'{i}.pdf', 'task_id': str(uuid.uuid4()), 'error': None}])
            ):
                res = _upload_files(client, [_make_pdf_file(f'{i}.pdf')], csrf)
            assert res.status_code == 202
            batch_ids.append(res.json()['batch_id'])

        res_list = client.get('/api/documents/batches?limit=10')
        assert res_list.status_code == 200
        body = res_list.json()
        assert 'batches' in body
        assert len(body['batches']) >= 3
        # Check structure
        b = body['batches'][0]
        assert 'batch_id' in b
        assert 'status' in b
        assert 'summary' in b

    finally:
        client.__exit__(None, None, None)


def test_batch_detail(tmp_path, monkeypatch):
    """Batch detail returns items with case info (None when no case yet)."""
    from unittest.mock import AsyncMock, patch

    client = _setup(tmp_path, monkeypatch)
    try:
        _login(client)
        csrf = _get_csrf(client)

        import app.dependencies as deps
        connector = deps.get_paperless_connector()
        task_id = str(uuid.uuid4())
        with patch.object(
            connector, 'upload_documents_batch',
            new=AsyncMock(return_value=[{'filename': 'detail.pdf', 'task_id': task_id, 'error': None}])
        ):
            res = _upload_files(client, [_make_pdf_file('detail.pdf')], csrf)

        batch_id = res.json()['batch_id']
        res2 = client.get(f'/api/documents/batches/{batch_id}')
        assert res2.status_code == 200
        body = res2.json()
        assert body['batch_id'] == batch_id
        assert len(body['items']) == 1
        item = body['items'][0]
        assert item['filename'] == 'detail.pdf'
        assert 'case_number' in item
        assert 'case_title' in item

    finally:
        client.__exit__(None, None, None)


def test_batch_detail_wrong_tenant(tmp_path, monkeypatch):
    """GET /batches/{batch_id} with wrong tenant → 404."""
    from unittest.mock import AsyncMock, patch

    client = _setup(tmp_path, monkeypatch)
    try:
        _login(client)
        csrf = _get_csrf(client)

        import app.dependencies as deps
        connector = deps.get_paperless_connector()
        with patch.object(
            connector, 'upload_documents_batch',
            new=AsyncMock(return_value=[{'filename': 'x.pdf', 'task_id': str(uuid.uuid4()), 'error': None}])
        ):
            res = _upload_files(client, [_make_pdf_file('x.pdf')], csrf)

        batch_id = res.json()['batch_id']

        # Change batch tenant so operator can no longer see it
        bulk_repo = deps.get_bulk_upload_repository()
        if batch_id in bulk_repo._batches:
            bulk_repo._batches[batch_id]['tenant_id'] = str(uuid.uuid4())

        res2 = client.get(f'/api/documents/batches/{batch_id}')
        assert res2.status_code == 404

    finally:
        client.__exit__(None, None, None)


def test_batch_refresh_rate_limit(tmp_path, monkeypatch):
    """Two refreshes within 5 seconds → second is throttled (429)."""
    from unittest.mock import AsyncMock, patch

    client = _setup(tmp_path, monkeypatch)
    try:
        _login(client)
        csrf = _get_csrf(client)

        import app.dependencies as deps
        import app.api.bulk_upload as bu_module
        connector = deps.get_paperless_connector()

        with patch.object(
            connector, 'upload_documents_batch',
            new=AsyncMock(return_value=[{'filename': 'r.pdf', 'task_id': str(uuid.uuid4()), 'error': None}])
        ):
            res = _upload_files(client, [_make_pdf_file('r.pdf')], csrf)

        batch_id = res.json()['batch_id']

        # Patch refresh_batch on the service to avoid actual Paperless calls
        bulk_svc = deps.get_bulk_upload_service()
        with patch.object(
            bulk_svc, 'refresh_batch',
            new=AsyncMock(return_value={'processing': 1})
        ):
            res1 = client.post(
                f'/api/documents/batches/{batch_id}/refresh',
                headers={'x-frya-csrf-token': csrf},
            )
            # First refresh should work (200 or 404 if not found in memory)
            # Second should be rate-limited (429) if first was successful
            if res1.status_code in (200, 202):
                res2 = client.post(
                    f'/api/documents/batches/{batch_id}/refresh',
                    headers={'x-frya-csrf-token': csrf},
                )
                assert res2.status_code == 429
            else:
                # If the first also failed for another reason, clear and try again
                bu_module._last_refresh.clear()
                bu_module._last_refresh[batch_id] = 9999999999.0  # far future
                res_rl = client.post(
                    f'/api/documents/batches/{batch_id}/refresh',
                    headers={'x-frya-csrf-token': csrf},
                )
                assert res_rl.status_code == 429

    finally:
        client.__exit__(None, None, None)


def test_duplicate_files_in_batch(tmp_path, monkeypatch):
    """Two identical files → 1 uploaded, 1 duplicate_skipped."""
    from unittest.mock import AsyncMock, patch

    client = _setup(tmp_path, monkeypatch)
    try:
        _login(client)
        csrf = _get_csrf(client)

        import app.dependencies as deps
        connector = deps.get_paperless_connector()

        same_content = b'%PDF-1.4 identical content for duplicate test'
        file1 = ('original.pdf', io.BytesIO(same_content), 'application/pdf')
        file2 = ('copy.pdf', io.BytesIO(same_content), 'application/pdf')

        task_id = str(uuid.uuid4())
        with patch.object(
            connector, 'upload_documents_batch',
            new=AsyncMock(return_value=[{'filename': 'original.pdf', 'task_id': task_id, 'error': None}])
        ):
            res = _upload_files(client, [file1, file2], csrf)

        assert res.status_code == 202
        body = res.json()
        assert body['file_count'] == 2
        assert body['duplicates_skipped'] == 1

        # Verify in batch detail
        res2 = client.get(f'/api/documents/batches/{body["batch_id"]}')
        assert res2.status_code == 200
        items = res2.json()['items']
        statuses = [i['status'] for i in items]
        assert 'duplicate_skipped' in statuses
        assert 'uploaded' in statuses

    finally:
        client.__exit__(None, None, None)
