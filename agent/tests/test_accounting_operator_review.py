from __future__ import annotations

import importlib
import json
import re
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
                'username': 'operator',
                'role': 'operator',
                'password_hash': hash_password_pbkdf2('operator-pass'),
            },
            {
                'username': 'admin',
                'role': 'admin',
                'password_hash': hash_password_pbkdf2('admin-pass'),
            },
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


def _extract_csrf_token(html: str) -> str:
    match = re.search(r'name="csrf_token"\s+value="([^"]+)"', html)
    assert match, 'csrf_token nicht im HTML gefunden'
    return match.group(1)


def _configure_env(monkeypatch, tmp_path: Path) -> None:
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


def _login(client: TestClient, username: str, password: str) -> None:
    response = client.post(
        '/auth/login',
        data={'username': username, 'password': password, 'next': '/ui/dashboard'},
        follow_redirects=False,
    )
    assert response.status_code == 303


@pytest.mark.asyncio
async def test_accounting_operator_confirm_can_be_handed_off_manually(monkeypatch, tmp_path: Path):
    _prepare_data(tmp_path)
    _configure_env(monkeypatch, tmp_path)

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
        webhook = client.post('/webhooks/paperless/document', json={'document_id': '123', 'title': 'rechnung-123.pdf'})
        assert webhook.status_code == 200
        assert webhook.json()['analysis_status'] == 'ACCOUNTING_ANALYST_READY'

        _login(client, 'admin', 'admin-pass')
        case_page = client.get('/ui/cases/doc-123')
        assert case_page.status_code == 200
        csrf = _extract_csrf_token(case_page.text)

        decision = client.post(
            '/inspect/cases/doc-123/accounting-review-decision',
            json={'decision': 'CONFIRMED', 'note': 'Klarer Standardfall.'},
            headers={'x-frya-csrf-token': csrf},
        )
        assert decision.status_code == 200

        handoff = client.post(
            '/inspect/cases/doc-123/accounting-manual-handoff',
            json={'note': 'Manuell in den Buchhaltungsprozess uebergeben.'},
            headers={'x-frya-csrf-token': csrf},
        )
        assert handoff.status_code == 200
        handoff_body = handoff.json()
        assert handoff_body['status'] == 'READY_FOR_MANUAL_ACCOUNTING'
        assert handoff_body['suggested_next_step'] == 'MANUAL_ACCOUNTING_WORK'
        assert handoff_body['open_item_title'] == 'Manuelle Accounting-Uebergabe durchfuehren'
        assert handoff_body['execution_allowed'] is False

        duplicate = client.post(
            '/inspect/cases/doc-123/accounting-manual-handoff',
            json={'note': 'zweites mal'},
            headers={'x-frya-csrf-token': csrf},
        )
        assert duplicate.status_code == 409

        case_json = client.get('/inspect/cases/doc-123/json')
        assert case_json.status_code == 200
        case_body = case_json.json()
        assert case_body['accounting_operator_review']['decision'] == 'CONFIRMED'
        assert case_body['accounting_manual_handoff']['status'] == 'READY_FOR_MANUAL_ACCOUNTING'
        assert case_body['accounting_manual_handoff']['suggested_next_step'] == 'MANUAL_ACCOUNTING_WORK'
        assert any(event['action'] == 'ACCOUNTING_OPERATOR_REVIEW_CONFIRMED' for event in case_body['chronology'])
        assert any(event['action'] == 'ACCOUNTING_MANUAL_HANDOFF_READY' for event in case_body['chronology'])
        assert any(item['title'] == 'Buchungsvorschlag pruefen' and item['status'] == 'COMPLETED' for item in case_body['open_items'])
        assert any(item['title'] == 'Manuelle Accounting-Uebergabe durchfuehren' and item['status'] == 'OPEN' for item in case_body['open_items'])

        case_detail = client.get('/ui/cases/doc-123')
        assert case_detail.status_code == 200
        assert 'Manual Accounting Handoff' in case_detail.text
        assert 'READY_FOR_MANUAL_ACCOUNTING' in case_detail.text
        assert 'Manuelle Accounting-Uebergabe durchfuehren' in case_detail.text


@pytest.mark.asyncio
async def test_accounting_operator_reject_stays_without_manual_handoff(monkeypatch, tmp_path: Path):
    _prepare_data(tmp_path)
    _configure_env(monkeypatch, tmp_path)

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
        webhook = client.post('/webhooks/paperless/document', json={'document_id': '456', 'title': 'mahnung-1.pdf'})
        assert webhook.status_code == 200
        assert webhook.json()['analysis_status'] == 'ACCOUNTING_ANALYST_READY'

        _login(client, 'admin', 'admin-pass')
        case_page = client.get('/ui/cases/doc-456')
        assert case_page.status_code == 200
        csrf = _extract_csrf_token(case_page.text)

        decision = client.post(
            '/inspect/cases/doc-456/accounting-review-decision',
            json={'decision': 'REJECTED', 'note': 'Referenz muss manuell geklaert werden.'},
            headers={'x-frya-csrf-token': csrf},
        )
        assert decision.status_code == 200
        body = decision.json()
        assert body['decision'] == 'REJECTED'
        assert body['follow_up_open_item_title'] == 'Mahnungsbezug klaeren'
        assert body['problem_case_id']
        assert body['execution_allowed'] is False

        handoff = client.post(
            '/inspect/cases/doc-456/accounting-manual-handoff',
            json={'note': 'sollte scheitern'},
            headers={'x-frya-csrf-token': csrf},
        )
        assert handoff.status_code == 409

        case_json = client.get('/inspect/cases/doc-456/json')
        assert case_json.status_code == 200
        case_body = case_json.json()
        assert case_body['accounting_operator_review']['decision'] == 'REJECTED'
        assert case_body['accounting_manual_handoff'] is None
        assert any(event['action'] == 'ACCOUNTING_OPERATOR_REVIEW_REJECTED' for event in case_body['chronology'])
        assert not any(event['action'] == 'ACCOUNTING_MANUAL_HANDOFF_READY' for event in case_body['chronology'])
        assert any(item['title'] == 'Mahnungsbezug pruefen' and item['status'] == 'COMPLETED' for item in case_body['open_items'])
        assert any(item['title'] == 'Mahnungsbezug klaeren' and item['status'] == 'OPEN' for item in case_body['open_items'])
        assert any(problem['exception_type'] == 'ACCOUNTING_REVIEW_REJECTED' for problem in case_body['exceptions'])

        case_detail = client.get('/ui/cases/doc-456')
        assert case_detail.status_code == 200
        assert 'REJECTED' in case_detail.text
        assert 'Mahnungsbezug klaeren' in case_detail.text


@pytest.mark.asyncio
async def test_accounting_operator_review_requires_admin_role(monkeypatch, tmp_path: Path):
    _prepare_data(tmp_path)
    _configure_env(monkeypatch, tmp_path)

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
        webhook = client.post('/webhooks/paperless/document', json={'document_id': '123', 'title': 'rechnung-123.pdf'})
        assert webhook.status_code == 200

        _login(client, 'operator', 'operator-pass')
        case_page = client.get('/ui/cases/doc-123')
        assert case_page.status_code == 200
        csrf = _extract_csrf_token(case_page.text)

        denied = client.post(
            '/inspect/cases/doc-123/accounting-review-decision',
            json={'decision': 'CONFIRMED', 'note': 'nicht erlaubt'},
            headers={'x-frya-csrf-token': csrf},
        )
        assert denied.status_code == 403


@pytest.mark.asyncio
async def test_accounting_manual_handoff_requires_confirmed_review(monkeypatch, tmp_path: Path):
    _prepare_data(tmp_path)
    _configure_env(monkeypatch, tmp_path)

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
        webhook = client.post('/webhooks/paperless/document', json={'document_id': '123', 'title': 'rechnung-123.pdf'})
        assert webhook.status_code == 200

        _login(client, 'admin', 'admin-pass')
        case_page = client.get('/ui/cases/doc-123')
        assert case_page.status_code == 200
        csrf = _extract_csrf_token(case_page.text)

        handoff = client.post(
            '/inspect/cases/doc-123/accounting-manual-handoff',
            json={'note': 'zu frueh'},
            headers={'x-frya-csrf-token': csrf},
        )
        assert handoff.status_code == 409


def test_accounting_operator_review_service_normalizes_stringified_audit_payloads():
    from app.accounting_analysis.models import AccountingAnalysisResult
    from app.accounting_analysis.review_service import AccountingOperatorReviewService
    from app.audit.models import AuditRecord

    analysis = AccountingAnalysisResult.model_validate(
        {
            'case_id': 'doc-x',
            'accounting_review_ref': 'doc-x:1:accounting-review-v1',
            'booking_candidate_type': 'INVOICE_STANDARD_EXPENSE',
            'supplier_or_counterparty_hint': {'value': 'Muster GmbH', 'status': 'FOUND', 'confidence': 0.9, 'source_kind': 'CASE_CONTEXT', 'evidence_excerpt': 'Muster GmbH'},
            'invoice_reference_hint': {'value': 'RE-1', 'status': 'FOUND', 'confidence': 0.9, 'source_kind': 'CASE_CONTEXT', 'evidence_excerpt': 'RE-1'},
            'amount_summary': {
                'total_amount': {'value': '1190.00', 'status': 'FOUND', 'confidence': 0.9, 'source_kind': 'CASE_CONTEXT', 'evidence_excerpt': '1190.00'},
                'currency': {'value': 'EUR', 'status': 'FOUND', 'confidence': 0.9, 'source_kind': 'CASE_CONTEXT', 'evidence_excerpt': 'EUR'},
                'net_amount': {'value': '1000.00', 'status': 'FOUND', 'confidence': 0.9, 'source_kind': 'CASE_CONTEXT', 'evidence_excerpt': '1000.00'},
                'tax_amount': {'value': '190.00', 'status': 'FOUND', 'confidence': 0.9, 'source_kind': 'CASE_CONTEXT', 'evidence_excerpt': '190.00'},
            },
            'due_date_hint': {'value': None, 'status': 'MISSING', 'confidence': 0.0, 'source_kind': 'NONE', 'evidence_excerpt': None},
            'tax_hint': {'rate': {'value': '19%', 'status': 'FOUND', 'confidence': 0.7, 'source_kind': 'DERIVED', 'evidence_excerpt': 'tax/net'}, 'reason': 'ok'},
            'booking_candidate': {'candidate_type': 'INVOICE_STANDARD_EXPENSE', 'counterparty_hint': 'Muster GmbH', 'invoice_reference_hint': 'RE-1', 'review_focus': [], 'notes': []},
            'booking_confidence': 0.85,
            'accounting_risks': [],
            'missing_accounting_fields': [],
            'suggested_next_step': 'ACCOUNTING_CONFIRMATION',
            'global_decision': 'PROPOSED',
            'ready_for_user_approval': False,
            'ready_for_accounting_confirmation': True,
            'analysis_summary': 'summary',
        }
    )

    service = AccountingOperatorReviewService(audit_service=None, open_items_service=None, problem_service=None)
    record = AuditRecord(
        event_id='evt-1',
        case_id='doc-x',
        source='test',
        agent_name='accounting-analyst',
        approval_status='NOT_REQUIRED',
        action='ACCOUNTING_ANALYSIS_COMPLETED',
        result='ok',
        llm_output=json.dumps(analysis.model_dump(mode='json')),
        record_hash='hash',
    )

    parsed = service._latest_accounting_analysis([record])
    assert parsed is not None
    assert parsed.accounting_review_ref == 'doc-x:1:accounting-review-v1'

@pytest.mark.asyncio
async def test_accounting_manual_handoff_can_be_completed(monkeypatch, tmp_path: Path):
    _prepare_data(tmp_path)
    _configure_env(monkeypatch, tmp_path)

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
        webhook = client.post('/webhooks/paperless/document', json={'document_id': '123', 'title': 'rechnung-123.pdf'})
        assert webhook.status_code == 200

        _login(client, 'admin', 'admin-pass')
        case_page = client.get('/ui/cases/doc-123')
        assert case_page.status_code == 200
        csrf = _extract_csrf_token(case_page.text)

        decision = client.post(
            '/inspect/cases/doc-123/accounting-review-decision',
            json={'decision': 'CONFIRMED', 'note': 'Klarer Standardfall.'},
            headers={'x-frya-csrf-token': csrf},
        )
        assert decision.status_code == 200

        handoff = client.post(
            '/inspect/cases/doc-123/accounting-manual-handoff',
            json={'note': 'Manuell in den Buchhaltungsprozess uebergeben.'},
            headers={'x-frya-csrf-token': csrf},
        )
        assert handoff.status_code == 200

        resolution = client.post(
            '/inspect/cases/doc-123/accounting-manual-handoff-resolution',
            json={'decision': 'COMPLETED', 'note': 'Von Accounting uebernommen.'},
            headers={'x-frya-csrf-token': csrf},
        )
        assert resolution.status_code == 200
        resolution_body = resolution.json()
        assert resolution_body['status'] == 'MANUAL_HANDOFF_COMPLETED'
        assert resolution_body['suggested_next_step'] == 'OUTSIDE_AGENT_ACCOUNTING_PROCESS'
        assert resolution_body['follow_up_open_item_title'] is None
        assert resolution_body['problem_case_id'] is None
        assert resolution_body['execution_allowed'] is False

        duplicate = client.post(
            '/inspect/cases/doc-123/accounting-manual-handoff-resolution',
            json={'decision': 'COMPLETED', 'note': 'nochmal'},
            headers={'x-frya-csrf-token': csrf},
        )
        assert duplicate.status_code == 409

        case_json = client.get('/inspect/cases/doc-123/json')
        assert case_json.status_code == 200
        case_body = case_json.json()
        assert case_body['accounting_manual_handoff_resolution']['status'] == 'MANUAL_HANDOFF_COMPLETED'
        assert any(event['action'] == 'ACCOUNTING_MANUAL_HANDOFF_COMPLETED' for event in case_body['chronology'])
        assert any(item['title'] == 'Manuelle Accounting-Uebergabe durchfuehren' and item['status'] == 'COMPLETED' for item in case_body['open_items'])
        assert not any(item['title'] == 'Manuelle Accounting-Uebergabe klaeren' and item['status'] == 'OPEN' for item in case_body['open_items'])

        case_detail = client.get('/ui/cases/doc-123')
        assert case_detail.status_code == 200
        assert 'Manual Handoff Abschluss' in case_detail.text
        assert 'MANUAL_HANDOFF_COMPLETED' in case_detail.text
        assert 'OUTSIDE_AGENT_ACCOUNTING_PROCESS' in case_detail.text


@pytest.mark.asyncio
async def test_accounting_manual_handoff_can_be_returned_for_clarification(monkeypatch, tmp_path: Path):
    _prepare_data(tmp_path)
    _configure_env(monkeypatch, tmp_path)

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
        webhook = client.post('/webhooks/paperless/document', json={'document_id': '456', 'title': 'mahnung-1.pdf'})
        assert webhook.status_code == 200

        _login(client, 'admin', 'admin-pass')
        case_page = client.get('/ui/cases/doc-456')
        assert case_page.status_code == 200
        csrf = _extract_csrf_token(case_page.text)

        decision = client.post(
            '/inspect/cases/doc-456/accounting-review-decision',
            json={'decision': 'CONFIRMED', 'note': 'Konservativ weitergeben.'},
            headers={'x-frya-csrf-token': csrf},
        )
        assert decision.status_code == 200

        handoff = client.post(
            '/inspect/cases/doc-456/accounting-manual-handoff',
            json={'note': 'Reminder manuell pruefen lassen.'},
            headers={'x-frya-csrf-token': csrf},
        )
        assert handoff.status_code == 200

        resolution = client.post(
            '/inspect/cases/doc-456/accounting-manual-handoff-resolution',
            json={'decision': 'RETURNED', 'note': 'Referenzlage weiter unklar.'},
            headers={'x-frya-csrf-token': csrf},
        )
        assert resolution.status_code == 200
        resolution_body = resolution.json()
        assert resolution_body['status'] == 'MANUAL_HANDOFF_RETURNED_FOR_CLARIFICATION'
        assert resolution_body['suggested_next_step'] == 'ACCOUNTING_CLARIFICATION'
        assert resolution_body['follow_up_open_item_title'] == 'Manuelle Reminder-Uebergabe klaeren'
        assert resolution_body['problem_case_id']
        assert resolution_body['execution_allowed'] is False

        case_json = client.get('/inspect/cases/doc-456/json')
        assert case_json.status_code == 200
        case_body = case_json.json()
        assert case_body['accounting_manual_handoff_resolution']['status'] == 'MANUAL_HANDOFF_RETURNED_FOR_CLARIFICATION'
        assert any(event['action'] == 'ACCOUNTING_MANUAL_HANDOFF_RETURNED' for event in case_body['chronology'])
        assert any(item['title'] == 'Manuelle Reminder-Weiterbearbeitung uebergeben' and item['status'] == 'COMPLETED' for item in case_body['open_items'])
        assert any(item['title'] == 'Manuelle Reminder-Uebergabe klaeren' and item['status'] == 'OPEN' for item in case_body['open_items'])
        assert any(problem['exception_type'] == 'ACCOUNTING_MANUAL_HANDOFF_RETURNED' for problem in case_body['exceptions'])

        case_detail = client.get('/ui/cases/doc-456')
        assert case_detail.status_code == 200
        assert 'MANUAL_HANDOFF_RETURNED_FOR_CLARIFICATION' in case_detail.text
        assert 'Manuelle Reminder-Uebergabe klaeren' in case_detail.text

@pytest.mark.asyncio
async def test_accounting_clarification_can_be_completed_after_returned_manual_handoff(monkeypatch, tmp_path: Path):
    _prepare_data(tmp_path)
    _configure_env(monkeypatch, tmp_path)

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
        webhook = client.post('/webhooks/paperless/document', json={'document_id': '456', 'title': 'mahnung-1.pdf'})
        assert webhook.status_code == 200

        _login(client, 'admin', 'admin-pass')
        case_page = client.get('/ui/cases/doc-456')
        assert case_page.status_code == 200
        csrf = _extract_csrf_token(case_page.text)

        assert client.post(
            '/inspect/cases/doc-456/accounting-review-decision',
            json={'decision': 'CONFIRMED', 'note': 'Konservativ weitergeben.'},
            headers={'x-frya-csrf-token': csrf},
        ).status_code == 200
        assert client.post(
            '/inspect/cases/doc-456/accounting-manual-handoff',
            json={'note': 'Reminder manuell pruefen lassen.'},
            headers={'x-frya-csrf-token': csrf},
        ).status_code == 200
        assert client.post(
            '/inspect/cases/doc-456/accounting-manual-handoff-resolution',
            json={'decision': 'RETURNED', 'note': 'Referenzlage weiter unklar.'},
            headers={'x-frya-csrf-token': csrf},
        ).status_code == 200

        completion = client.post(
            '/inspect/cases/doc-456/accounting-clarification-complete',
            json={'note': 'Rechnungsbezug manuell geklaert und ausserhalb Frya dokumentiert.'},
            headers={'x-frya-csrf-token': csrf},
        )
        assert completion.status_code == 200
        completion_body = completion.json()
        assert completion_body['status'] == 'ACCOUNTING_CLARIFICATION_COMPLETED'
        assert completion_body['suggested_next_step'] == 'OUTSIDE_AGENT_ACCOUNTING_PROCESS'
        assert completion_body['clarification_open_item_title'] == 'Manuelle Reminder-Uebergabe klaeren'
        assert completion_body['problem_case_id']
        assert completion_body['execution_allowed'] is False

        duplicate = client.post(
            '/inspect/cases/doc-456/accounting-clarification-complete',
            json={'note': 'nochmal'},
            headers={'x-frya-csrf-token': csrf},
        )
        assert duplicate.status_code == 409

        case_json = client.get('/inspect/cases/doc-456/json')
        assert case_json.status_code == 200
        case_body = case_json.json()
        assert case_body['accounting_clarification_completion']['status'] == 'ACCOUNTING_CLARIFICATION_COMPLETED'
        assert any(event['action'] == 'ACCOUNTING_CLARIFICATION_COMPLETED' for event in case_body['chronology'])
        assert any(item['title'] == 'Manuelle Reminder-Uebergabe klaeren' and item['status'] == 'COMPLETED' for item in case_body['open_items'])

        case_detail = client.get('/ui/cases/doc-456')
        assert case_detail.status_code == 200
        assert 'Accounting Klaerabschluss' in case_detail.text
        assert 'ACCOUNTING_CLARIFICATION_COMPLETED' in case_detail.text
        assert 'OUTSIDE_AGENT_ACCOUNTING_PROCESS' in case_detail.text


@pytest.mark.asyncio
async def test_accounting_clarification_requires_returned_manual_handoff(monkeypatch, tmp_path: Path):
    _prepare_data(tmp_path)
    _configure_env(monkeypatch, tmp_path)

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
        webhook = client.post('/webhooks/paperless/document', json={'document_id': '123', 'title': 'rechnung-123.pdf'})
        assert webhook.status_code == 200

        _login(client, 'admin', 'admin-pass')
        case_page = client.get('/ui/cases/doc-123')
        assert case_page.status_code == 200
        csrf = _extract_csrf_token(case_page.text)

        assert client.post(
            '/inspect/cases/doc-123/accounting-review-decision',
            json={'decision': 'CONFIRMED', 'note': 'Klarer Standardfall.'},
            headers={'x-frya-csrf-token': csrf},
        ).status_code == 200
        assert client.post(
            '/inspect/cases/doc-123/accounting-manual-handoff',
            json={'note': 'Manuell uebergeben.'},
            headers={'x-frya-csrf-token': csrf},
        ).status_code == 200

        completion = client.post(
            '/inspect/cases/doc-123/accounting-clarification-complete',
            json={'note': 'zu frueh'},
            headers={'x-frya-csrf-token': csrf},
        )
        assert completion.status_code == 409

@pytest.mark.asyncio
async def test_external_accounting_process_can_be_completed(monkeypatch, tmp_path: Path):
    _prepare_data(tmp_path)
    _configure_env(monkeypatch, tmp_path)

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
        assert client.post('/webhooks/paperless/document', json={'document_id': '123', 'title': 'rechnung-123.pdf'}).status_code == 200

        _login(client, 'admin', 'admin-pass')
        case_page = client.get('/ui/cases/doc-123')
        assert case_page.status_code == 200
        csrf = _extract_csrf_token(case_page.text)

        assert client.post(
            '/inspect/cases/doc-123/accounting-review-decision',
            json={'decision': 'CONFIRMED', 'note': 'Klarer Standardfall.'},
            headers={'x-frya-csrf-token': csrf},
        ).status_code == 200
        assert client.post(
            '/inspect/cases/doc-123/accounting-manual-handoff',
            json={'note': 'Manuell in den Buchhaltungsprozess uebergeben.'},
            headers={'x-frya-csrf-token': csrf},
        ).status_code == 200
        assert client.post(
            '/inspect/cases/doc-123/accounting-manual-handoff-resolution',
            json={'decision': 'COMPLETED', 'note': 'Von Accounting uebernommen.'},
            headers={'x-frya-csrf-token': csrf},
        ).status_code == 200

        resolution = client.post(
            '/inspect/cases/doc-123/external-accounting-resolution',
            json={'decision': 'COMPLETED', 'note': 'Extern sauber verbucht und abgelegt.'},
            headers={'x-frya-csrf-token': csrf},
        )
        assert resolution.status_code == 200
        body = resolution.json()
        assert body['status'] == 'EXTERNAL_ACCOUNTING_COMPLETED'
        assert body['suggested_next_step'] == 'NO_FURTHER_AGENT_ACTION'
        assert body['outside_process_open_item_title'] == 'Externen Accounting-Abschluss dokumentieren'
        assert body['follow_up_open_item_title'] is None
        assert body['execution_allowed'] is False

        duplicate = client.post(
            '/inspect/cases/doc-123/external-accounting-resolution',
            json={'decision': 'COMPLETED', 'note': 'nochmal'},
            headers={'x-frya-csrf-token': csrf},
        )
        assert duplicate.status_code == 409

        case_json = client.get('/inspect/cases/doc-123/json')
        assert case_json.status_code == 200
        case_body = case_json.json()
        assert case_body['outside_agent_accounting_process']['status'] == 'EXTERNAL_ACCOUNTING_COMPLETED'
        assert case_body['outside_agent_accounting_process']['resolution_recorded'] is True
        assert case_body['external_accounting_process_resolution']['status'] == 'EXTERNAL_ACCOUNTING_COMPLETED'
        assert any(event['action'] == 'EXTERNAL_ACCOUNTING_COMPLETED' for event in case_body['chronology'])
        assert any(item['title'] == 'Externen Accounting-Abschluss dokumentieren' and item['status'] == 'COMPLETED' for item in case_body['open_items'])
        assert not any(problem['exception_type'] == 'EXTERNAL_ACCOUNTING_RETURNED' for problem in case_body['exceptions'])

        case_detail = client.get('/ui/cases/doc-123')
        assert case_detail.status_code == 200
        assert 'Outside-Agent Accounting' in case_detail.text
        assert 'Externer Accounting-Abschluss' in case_detail.text
        assert 'EXTERNAL_ACCOUNTING_COMPLETED' in case_detail.text
        assert 'Externen Accounting-Abschluss dokumentieren' in case_detail.text


@pytest.mark.asyncio
async def test_external_accounting_process_can_be_returned(monkeypatch, tmp_path: Path):
    _prepare_data(tmp_path)
    _configure_env(monkeypatch, tmp_path)

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
        assert client.post('/webhooks/paperless/document', json={'document_id': '456', 'title': 'mahnung-1.pdf'}).status_code == 200

        _login(client, 'admin', 'admin-pass')
        case_page = client.get('/ui/cases/doc-456')
        assert case_page.status_code == 200
        csrf = _extract_csrf_token(case_page.text)

        assert client.post(
            '/inspect/cases/doc-456/accounting-review-decision',
            json={'decision': 'CONFIRMED', 'note': 'Konservativ weitergeben.'},
            headers={'x-frya-csrf-token': csrf},
        ).status_code == 200
        assert client.post(
            '/inspect/cases/doc-456/accounting-manual-handoff',
            json={'note': 'Reminder manuell pruefen lassen.'},
            headers={'x-frya-csrf-token': csrf},
        ).status_code == 200
        assert client.post(
            '/inspect/cases/doc-456/accounting-manual-handoff-resolution',
            json={'decision': 'RETURNED', 'note': 'Referenzlage weiter unklar.'},
            headers={'x-frya-csrf-token': csrf},
        ).status_code == 200
        assert client.post(
            '/inspect/cases/doc-456/accounting-clarification-complete',
            json={'note': 'Rechnungsbezug manuell geklaert und ausserhalb Frya dokumentiert.'},
            headers={'x-frya-csrf-token': csrf},
        ).status_code == 200

        resolution = client.post(
            '/inspect/cases/doc-456/external-accounting-resolution',
            json={'decision': 'RETURNED', 'note': 'Externer Prozess kam mit weiterem Klaerbedarf zurueck.'},
            headers={'x-frya-csrf-token': csrf},
        )
        assert resolution.status_code == 200
        body = resolution.json()
        assert body['status'] == 'EXTERNAL_ACCOUNTING_RETURNED'
        assert body['suggested_next_step'] == 'ACCOUNTING_CLARIFICATION'
        assert body['outside_process_open_item_title'] == 'Externen Reminder-Abschluss dokumentieren'
        assert body['follow_up_open_item_title'] == 'Externen Reminder-Ruecklauf klaeren'
        assert body['problem_case_id']
        assert body['execution_allowed'] is False

        case_json = client.get('/inspect/cases/doc-456/json')
        assert case_json.status_code == 200
        case_body = case_json.json()
        assert case_body['outside_agent_accounting_process']['status'] == 'EXTERNAL_ACCOUNTING_RETURNED'
        assert case_body['outside_agent_accounting_process']['resolution_recorded'] is True
        assert case_body['external_accounting_process_resolution']['status'] == 'EXTERNAL_ACCOUNTING_RETURNED'
        assert any(event['action'] == 'EXTERNAL_ACCOUNTING_RETURNED' for event in case_body['chronology'])
        assert any(item['title'] == 'Externen Reminder-Abschluss dokumentieren' and item['status'] == 'COMPLETED' for item in case_body['open_items'])
        assert any(item['title'] == 'Externen Reminder-Ruecklauf klaeren' and item['status'] == 'OPEN' for item in case_body['open_items'])
        assert any(problem['exception_type'] == 'EXTERNAL_ACCOUNTING_RETURNED' for problem in case_body['exceptions'])

        case_detail = client.get('/ui/cases/doc-456')
        assert case_detail.status_code == 200
        assert 'Externer Accounting-Abschluss' in case_detail.text
        assert 'EXTERNAL_ACCOUNTING_RETURNED' in case_detail.text
        assert 'Externen Reminder-Ruecklauf klaeren' in case_detail.text

@pytest.mark.asyncio
async def test_external_return_clarification_can_be_completed(monkeypatch, tmp_path: Path):
    _prepare_data(tmp_path)
    _configure_env(monkeypatch, tmp_path)

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
        assert client.post('/webhooks/paperless/document', json={'document_id': '456', 'title': 'mahnung-1.pdf'}).status_code == 200

        _login(client, 'admin', 'admin-pass')
        case_page = client.get('/ui/cases/doc-456')
        assert case_page.status_code == 200
        csrf = _extract_csrf_token(case_page.text)

        assert client.post(
            '/inspect/cases/doc-456/accounting-review-decision',
            json={'decision': 'CONFIRMED', 'note': 'Konservativ weitergeben.'},
            headers={'x-frya-csrf-token': csrf},
        ).status_code == 200
        assert client.post(
            '/inspect/cases/doc-456/accounting-manual-handoff',
            json={'note': 'Reminder manuell pruefen lassen.'},
            headers={'x-frya-csrf-token': csrf},
        ).status_code == 200
        assert client.post(
            '/inspect/cases/doc-456/accounting-manual-handoff-resolution',
            json={'decision': 'RETURNED', 'note': 'Referenzlage weiter unklar.'},
            headers={'x-frya-csrf-token': csrf},
        ).status_code == 200
        assert client.post(
            '/inspect/cases/doc-456/accounting-clarification-complete',
            json={'note': 'Rechnungsbezug manuell geklaert und ausserhalb Frya dokumentiert.'},
            headers={'x-frya-csrf-token': csrf},
        ).status_code == 200
        assert client.post(
            '/inspect/cases/doc-456/external-accounting-resolution',
            json={'decision': 'RETURNED', 'note': 'Externer Prozess kam mit weiterem Klaerbedarf zurueck.'},
            headers={'x-frya-csrf-token': csrf},
        ).status_code == 200

        completion = client.post(
            '/inspect/cases/doc-456/external-return-clarification-complete',
            json={'note': 'Externen Ruecklauf erneut menschlich geklaert und konservativ abgeschlossen.'},
            headers={'x-frya-csrf-token': csrf},
        )
        assert completion.status_code == 200
        body = completion.json()
        assert body['status'] == 'EXTERNAL_RETURN_CLARIFICATION_COMPLETED'
        assert body['suggested_next_step'] == 'NO_FURTHER_AGENT_ACTION'
        assert body['external_return_open_item_title'] == 'Externen Reminder-Ruecklauf klaeren'
        assert body['problem_case_id']
        assert body['execution_allowed'] is False

        duplicate = client.post(
            '/inspect/cases/doc-456/external-return-clarification-complete',
            json={'note': 'nochmal'},
            headers={'x-frya-csrf-token': csrf},
        )
        assert duplicate.status_code == 409

        case_json = client.get('/inspect/cases/doc-456/json')
        assert case_json.status_code == 200
        case_body = case_json.json()
        assert case_body['outside_agent_accounting_process']['status'] == 'EXTERNAL_RETURN_CLARIFICATION_COMPLETED'
        assert case_body['outside_agent_accounting_process']['reclarification_recorded'] is True
        assert case_body['external_return_clarification_completion']['status'] == 'EXTERNAL_RETURN_CLARIFICATION_COMPLETED'
        assert any(event['action'] == 'EXTERNAL_RETURN_CLARIFICATION_COMPLETED' for event in case_body['chronology'])
        assert any(item['title'] == 'Externen Reminder-Ruecklauf klaeren' and item['status'] == 'COMPLETED' for item in case_body['open_items'])

        case_detail = client.get('/ui/cases/doc-456')
        assert case_detail.status_code == 200
        assert 'Re-Klaerabschluss nach externem Ruecklauf' in case_detail.text
        assert 'EXTERNAL_RETURN_CLARIFICATION_COMPLETED' in case_detail.text
        assert 'Externen Reminder-Ruecklauf klaeren' in case_detail.text


@pytest.mark.asyncio
async def test_external_return_clarification_requires_external_return(monkeypatch, tmp_path: Path):
    _prepare_data(tmp_path)
    _configure_env(monkeypatch, tmp_path)

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
        assert client.post('/webhooks/paperless/document', json={'document_id': '123', 'title': 'rechnung-123.pdf'}).status_code == 200

        _login(client, 'admin', 'admin-pass')
        case_page = client.get('/ui/cases/doc-123')
        assert case_page.status_code == 200
        csrf = _extract_csrf_token(case_page.text)

        assert client.post(
            '/inspect/cases/doc-123/accounting-review-decision',
            json={'decision': 'CONFIRMED', 'note': 'Klarer Standardfall.'},
            headers={'x-frya-csrf-token': csrf},
        ).status_code == 200
        assert client.post(
            '/inspect/cases/doc-123/accounting-manual-handoff',
            json={'note': 'Manuell in den Buchhaltungsprozess uebergeben.'},
            headers={'x-frya-csrf-token': csrf},
        ).status_code == 200
        assert client.post(
            '/inspect/cases/doc-123/accounting-manual-handoff-resolution',
            json={'decision': 'COMPLETED', 'note': 'Von Accounting uebernommen.'},
            headers={'x-frya-csrf-token': csrf},
        ).status_code == 200
        assert client.post(
            '/inspect/cases/doc-123/external-accounting-resolution',
            json={'decision': 'COMPLETED', 'note': 'Extern sauber verbucht und abgelegt.'},
            headers={'x-frya-csrf-token': csrf},
        ).status_code == 200

        completion = client.post(
            '/inspect/cases/doc-123/external-return-clarification-complete',
            json={'note': 'zu frueh'},
            headers={'x-frya-csrf-token': csrf},
        )
        assert completion.status_code == 409
