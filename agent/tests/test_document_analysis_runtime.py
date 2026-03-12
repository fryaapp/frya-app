from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


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

    (rules / 'rule_registry.yaml').write_text(
        'version: 1\nentries:\n'
        '  - file: policies/orchestrator_policy.md\n    role: orchestrator_policy\n    required: true\n'
        '  - file: policies/runtime_policy.md\n    role: runtime_policy\n    required: true\n'
        '  - file: policies/gobd_compliance_policy.md\n    role: compliance_policy\n    required: true\n'
        '  - file: policies/accounting_analyst_policy.md\n    role: accounting_analyst_policy\n    required: true\n'
        '  - file: policies/problemfall_policy.md\n    role: problemfall_policy\n    required: true\n'
        '  - file: policies/freigabematrix.md\n    role: approval_matrix_policy\n    required: true\n'
        '  - file: policies/document_analyst_policy.md\n    role: document_analyst_policy\n    required: false\n'
        '  - file: output_schemas.yaml\n    role: output_schemas\n    required: false\n',
        encoding='utf-8',
    )
    (rules / 'output_schemas.yaml').write_text('version: 1\nname: output_schemas\nschemas:\n', encoding='utf-8')
    for name in [
        'orchestrator_policy.md',
        'runtime_policy.md',
        'gobd_compliance_policy.md',
        'accounting_analyst_policy.md',
        'problemfall_policy.md',
        'freigabematrix.md',
        'document_analyst_policy.md',
    ]:
        (policies / name).write_text('Version: 1.0\n', encoding='utf-8')


def _build_users_json() -> str:
    from app.auth.service import hash_password_pbkdf2

    return json.dumps(
        [
            {
                'username': 'admin',
                'role': 'admin',
                'password_hash': hash_password_pbkdf2('admin-pass'),
            }
        ]
    )


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


@pytest.mark.asyncio
async def test_paperless_runtime_path_returns_structured_invoice_result(monkeypatch, tmp_path: Path):
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
    monkeypatch.setenv('FRYA_AUTH_SESSION_SECRET', 'test-secret')
    monkeypatch.setenv('FRYA_AUTH_COOKIE_SECURE', 'false')

    async def _fake_get_document(self, doc_id: str) -> dict:
        return {
            'id': doc_id,
            'title': 'rechnung-123.pdf',
            'content': 'Rechnung\nAbsender: Muster GmbH\nEmpfaenger: Frya GmbH\nRechnungsnummer: RE-1\nRechnungsdatum: 11.03.2026\nGesamtbetrag: 1.190,00 EUR\nNetto: 1.000,00 EUR\nMwSt: 190,00 EUR',
        }

    import app.connectors.dms_paperless as paperless_module

    monkeypatch.setattr(paperless_module.PaperlessConnector, 'get_document', _fake_get_document)

    app = _build_app()

    with TestClient(app) as client:
        from app.dependencies import get_open_items_service

        stale_item = await get_open_items_service().create_item(
            case_id='doc-123',
            title='Accounting Review vorbereiten',
            description='legacy review item',
            source='document_analyst',
            document_ref='123',
        )

        response = client.post('/webhooks/paperless/document', json={'document_id': '123', 'title': 'rechnung-123.pdf'})
        assert response.status_code == 200
        body = response.json()
        assert body['status'] == 'accepted'
        assert body['analysis_status'] == 'ACCOUNTING_ANALYST_READY'
        assert body['result']['document_analysis']['document_type']['value'] == 'INVOICE'
        assert body['result']['accounting_review']['review_status'] == 'READY'
        assert body['result']['accounting_analysis']['booking_candidate_type'] == 'INVOICE_STANDARD_EXPENSE'
        assert body['result']['ready_for_accounting_confirmation'] is True
        assert body['open_item_id']

        login = client.post('/auth/login', data={'username': 'admin', 'password': 'admin-pass', 'next': '/ui/dashboard'}, follow_redirects=False)
        assert login.status_code == 303

        case_json = client.get('/inspect/cases/doc-123/json')
        assert case_json.status_code == 200
        case_body = case_json.json()
        assert any(event['action'] == 'ACCOUNTING_REVIEW_DRAFT_READY' for event in case_body['chronology'])
        assert any(event['action'] == 'ACCOUNTING_ANALYSIS_COMPLETED' for event in case_body['chronology'])
        assert case_body['accounting_review']['review_status'] == 'READY'
        assert case_body['accounting_analysis']['booking_candidate_type'] == 'INVOICE_STANDARD_EXPENSE'
        assert any(item['title'] == 'Buchungsvorschlag pruefen' and item['status'] == 'OPEN' for item in case_body['open_items'])
        assert any(item['title'] == 'Accounting Review durchfuehren' and item['status'] == 'COMPLETED' for item in case_body['open_items'])
        assert any(item['item_id'] == stale_item.item_id and item['status'] == 'COMPLETED' for item in case_body['open_items'])

        case_detail = client.get('/ui/cases/doc-123')
        assert case_detail.status_code == 200
        assert 'Accounting Review' in case_detail.text
        assert 'Accounting Analyst' in case_detail.text
        assert 'INVOICE_STANDARD_EXPENSE' in case_detail.text


@pytest.mark.asyncio
async def test_paperless_runtime_path_stops_cleanly_on_empty_ocr(monkeypatch, tmp_path: Path):
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
    monkeypatch.setenv('FRYA_AUTH_SESSION_SECRET', 'test-secret')
    monkeypatch.setenv('FRYA_AUTH_COOKIE_SECURE', 'false')

    async def _fake_get_document(self, doc_id: str) -> dict:
        return {'id': doc_id, 'title': 'scan.pdf', 'content': ''}

    import app.connectors.dms_paperless as paperless_module

    monkeypatch.setattr(paperless_module.PaperlessConnector, 'get_document', _fake_get_document)

    app = _build_app()

    with TestClient(app) as client:
        response = client.post('/webhooks/paperless/document', json={'document_id': '999', 'title': 'scan.pdf'})
        assert response.status_code == 200
        body = response.json()
        assert body['status'] == 'accepted'
        assert body['analysis_status'] == 'INCOMPLETE'
        assert body['result']['recommended_next_step'] == 'OCR_RECHECK'
        assert body['result']['accounting_review'] is None
        assert body['result'].get('accounting_analysis') is None
        assert body['open_item_id']


@pytest.mark.asyncio
async def test_paperless_runtime_path_builds_reminder_review_candidate(monkeypatch, tmp_path: Path):
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
    monkeypatch.setenv('FRYA_AUTH_SESSION_SECRET', 'test-secret')
    monkeypatch.setenv('FRYA_AUTH_COOKIE_SECURE', 'false')

    async def _fake_get_document(self, doc_id: str) -> dict:
        return {
            'id': doc_id,
            'title': 'mahnung-1.pdf',
            'created_date': '2026-03-11',
            'content': 'Mahnung\nAbsender: Beispiel AG\nRechnungsnummer: RE-1\nFaellig bis: 20.03.2026\nOffener Betrag: 450,00 EUR',
        }

    import app.connectors.dms_paperless as paperless_module

    monkeypatch.setattr(paperless_module.PaperlessConnector, 'get_document', _fake_get_document)

    app = _build_app()

    with TestClient(app) as client:
        response = client.post('/webhooks/paperless/document', json={'document_id': '456', 'title': 'mahnung-1.pdf'})
        assert response.status_code == 200
        body = response.json()
        assert body['analysis_status'] == 'ACCOUNTING_ANALYST_READY'
        assert body['result']['accounting_review']['source_document_type'] == 'REMINDER'
        assert body['result']['accounting_analysis']['booking_candidate_type'] == 'REMINDER_REFERENCE_CHECK'
        assert body['result']['accounting_analysis']['suggested_next_step'] == 'REMINDER_REFERENCE_REVIEW'
        assert body['result']['ready_for_accounting_confirmation'] is False

        login = client.post('/auth/login', data={'username': 'admin', 'password': 'admin-pass', 'next': '/ui/dashboard'}, follow_redirects=False)
        assert login.status_code == 303
        case_json = client.get('/inspect/cases/doc-456/json')
        assert case_json.status_code == 200
        case_body = case_json.json()
        assert case_body['accounting_analysis']['booking_candidate_type'] == 'REMINDER_REFERENCE_CHECK'
        assert any(item['title'] == 'Mahnungsbezug pruefen' and item['status'] == 'OPEN' for item in case_body['open_items'])


@pytest.mark.asyncio
async def test_letter_case_stays_human_review_without_accounting_review_draft(monkeypatch, tmp_path: Path):
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
    monkeypatch.setenv('FRYA_AUTH_SESSION_SECRET', 'test-secret')
    monkeypatch.setenv('FRYA_AUTH_COOKIE_SECURE', 'false')

    async def _fake_get_document(self, doc_id: str) -> dict:
        return {
            'id': doc_id,
            'title': 'brief.pdf',
            'content': 'Sehr geehrte Damen und Herren,\nwir bestaetigen den Eingang Ihrer Unterlagen.\nMit freundlichen Gruessen',
        }

    import app.connectors.dms_paperless as paperless_module

    monkeypatch.setattr(paperless_module.PaperlessConnector, 'get_document', _fake_get_document)

    app = _build_app()

    with TestClient(app) as client:
        response = client.post('/webhooks/paperless/document', json={'document_id': '789', 'title': 'brief.pdf'})
        assert response.status_code == 200
        body = response.json()
        assert body['analysis_status'] == 'LOW_CONFIDENCE'
        assert body['result']['recommended_next_step'] == 'HUMAN_REVIEW'
        assert body['result']['accounting_review'] is None
        assert body['result'].get('accounting_analysis') is None
