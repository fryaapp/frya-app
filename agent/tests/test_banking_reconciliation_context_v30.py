from __future__ import annotations

import importlib
import json
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.banking.models import ReconciliationSignal, ReconciliationDimensionStatus
from app.banking.reconciliation_context import ReconciliationContextService
from app.open_items.models import OpenItem


def _make_event(action: str, payload: dict | None = None, document_ref: str | None = None):
    return SimpleNamespace(
        action=action,
        llm_output=payload or {},
        created_at='2026-03-14T10:00:00+00:00',
        document_ref=document_ref,
        accounting_ref=None,
        policy_refs=[],
        approval_status=None,
        source='test',
        result=action,
        agent_name='test-agent',
    )


def _make_open_item(title: str, status: str = 'OPEN') -> OpenItem:
    return OpenItem(
        item_id=str(uuid.uuid4()),
        case_id='doc-test',
        title=title,
        description='test',
        status=status,
        source='test',
    )


def _make_context_service(
    *,
    transactions: list[dict],
    feed_total: int,
    invoices: list[dict] | None = None,
    bills: list[dict] | None = None,
    chronology: list | None = None,
    open_items: list[OpenItem] | None = None,
) -> ReconciliationContextService:
    connector = AsyncMock()
    connector.get_feed_status = AsyncMock(
        return_value={
            'reachable': True,
            'source_url': 'http://akaunting',
            'accounts_available': 1,
            'transactions_total': feed_total,
            'note': 'ok',
        }
    )
    connector.search_transactions = AsyncMock(return_value=transactions)
    connector.search_invoices = AsyncMock(return_value=invoices or [])
    connector.search_bills = AsyncMock(return_value=bills or [])

    audit = AsyncMock()
    audit.by_case = AsyncMock(return_value=chronology or [])

    open_items_service = AsyncMock()
    open_items_service.list_by_case = AsyncMock(return_value=open_items or [])

    return ReconciliationContextService(
        bank_service=MagicMock(),
        akaunting_connector=connector,
        audit_service=audit,
        open_items_service=open_items_service,
    )


@pytest.mark.asyncio
async def test_reconciliation_context_builds_plausible_income_match():
    svc = _make_context_service(
        transactions=[
            {
                'id': 6,
                'amount': '1450.00',
                'currency_code': 'EUR',
                'paid_at': '2026-03-12',
                'reference': 'INV-2026-101',
                'contact_name': 'Alpha GmbH',
                'type': 'income',
            }
        ],
        feed_total=4,
        invoices=[
            {
                'id': 101,
                'document_number': 'INV-2026-101',
                'amount': '1450.00',
                'status': 'sent',
                'contact_name': 'Alpha GmbH',
            }
        ],
        chronology=[_make_event('BANK_TRANSACTION_PROBE_EXECUTED', document_ref='INV-2026-101')],
        open_items=[_make_open_item('Banking Review pruefen')],
    )

    context = await svc.build(
        case_id='bank-case-1',
        reference='INV-2026-101',
        amount=1450.0,
        contact_name='Alpha GmbH',
        doc_type='income',
        doc_date='2026-03-11',
    )

    assert context.match_signal == ReconciliationSignal.PLAUSIBLE
    assert context.bank_result == 'MATCH_FOUND'
    assert context.accounting_result == 'FOUND'
    assert context.best_candidate is not None
    assert 'REFERENCE_EXACT' in context.best_candidate.reason_codes
    assert 'TYPE_MATCH' in context.best_candidate.reason_codes
    amount_row = next(row for row in context.comparison_rows if row.field_key == 'amount')
    assert amount_row.status == ReconciliationDimensionStatus.MATCH
    assert context.bank_write_executed is False
    assert context.no_financial_write is True


@pytest.mark.asyncio
async def test_reconciliation_context_builds_plausible_expense_match():
    svc = _make_context_service(
        transactions=[
            {
                'id': 7,
                'amount': '89.90',
                'currency_code': 'EUR',
                'paid_at': '2026-03-10',
                'reference': 'OUT-2026-042',
                'contact_name': 'Office Supply GmbH',
                'type': 'expense',
            }
        ],
        feed_total=4,
        bills=[
            {
                'id': 42,
                'document_number': 'OUT-2026-042',
                'amount': '89.90',
                'status': 'received',
                'contact_name': 'Office Supply GmbH',
            }
        ],
        chronology=[_make_event('BANK_TRANSACTION_PROBE_EXECUTED', document_ref='OUT-2026-042')],
    )

    context = await svc.build(
        case_id='bank-case-2',
        reference='OUT-2026-042',
        amount=89.90,
        contact_name='Office Supply GmbH',
        doc_type='expense',
        doc_date='2026-03-09',
    )

    assert context.doc_type == 'expense'
    assert context.match_signal == ReconciliationSignal.PLAUSIBLE
    assert context.best_candidate is not None
    assert context.best_candidate.tx_type == 'expense'
    assert 'TYPE_MATCH' in context.best_candidate.reason_codes


@pytest.mark.asyncio
async def test_reconciliation_context_marks_ambiguous_candidates_as_unclear():
    tx = {
        'amount': '320.00',
        'currency_code': 'EUR',
        'paid_at': '2026-03-03',
        'reference': 'INV-2026-003',
        'contact_name': 'Beta GmbH',
        'type': 'income',
    }
    svc = _make_context_service(
        transactions=[{'id': 5, **tx}, {'id': 8, **tx}],
        feed_total=4,
        invoices=[{'id': 3, 'document_number': 'INV-2026-003', 'amount': '320.00', 'status': 'sent', 'contact_name': 'Beta GmbH'}],
    )

    context = await svc.build(
        case_id='bank-case-3',
        reference='INV-2026-003',
        amount=320.0,
        contact_name='Beta GmbH',
        doc_type='income',
    )

    assert context.bank_result == 'AMBIGUOUS_MATCH'
    assert context.match_signal == ReconciliationSignal.UNCLEAR
    assert len(context.all_candidates) >= 2


@pytest.mark.asyncio
async def test_reconciliation_context_marks_type_mismatch_as_conflict():
    svc = _make_context_service(
        transactions=[
            {
                'id': 77,
                'amount': '1450.00',
                'currency_code': 'EUR',
                'paid_at': '2026-03-12',
                'reference': 'INV-2026-101',
                'contact_name': 'Alpha GmbH',
                'type': 'expense',
            }
        ],
        feed_total=4,
        invoices=[{'id': 101, 'document_number': 'INV-2026-101', 'amount': '1450.00', 'status': 'sent'}],
    )

    context = await svc.build(
        case_id='bank-case-4',
        reference='INV-2026-101',
        amount=1450.0,
        contact_name='Alpha GmbH',
        doc_type='income',
    )

    assert context.match_signal == ReconciliationSignal.CONFLICT
    assert any('Richtung' in row.label and row.status == ReconciliationDimensionStatus.CONFLICT for row in context.comparison_rows)
    assert any('Income/Expense-Richtung widerspricht.' == item for item in context.contra_match)


@pytest.mark.asyncio
async def test_reconciliation_context_reports_missing_accounting_context():
    svc = _make_context_service(
        transactions=[
            {
                'id': 6,
                'amount': '1450.00',
                'currency_code': 'EUR',
                'paid_at': '2026-03-12',
                'reference': 'INV-2026-101',
                'contact_name': 'Alpha GmbH',
                'type': 'income',
            }
        ],
        feed_total=4,
        invoices=[],
    )

    context = await svc.build(
        case_id='bank-case-5',
        reference='INV-2026-101',
        amount=1450.0,
        contact_name='Alpha GmbH',
        doc_type='income',
    )

    assert context.accounting_result == 'NOT_FOUND'
    assert 'Accounting-Kontext fehlt.' in context.missing_data
    assert context.bank_write_executed is False


def _prepare_data(tmp_path: Path) -> None:
    rules = tmp_path / 'rules'
    policies = rules / 'policies'
    policies.mkdir(parents=True, exist_ok=True)
    (tmp_path / 'verfahrensdoku').mkdir(parents=True, exist_ok=True)
    (tmp_path / 'system' / 'proposals').mkdir(parents=True, exist_ok=True)
    (tmp_path / 'audit').mkdir(parents=True, exist_ok=True)
    (tmp_path / 'tasks').mkdir(parents=True, exist_ok=True)
    (tmp_path / 'memory').mkdir(parents=True, exist_ok=True)

    for name, value in {
        'agent.md': 'a',
        'user.md': 'u',
        'soul.md': 's',
        'memory.md': 'm',
        'dms-state.md': 'd',
    }.items():
        (tmp_path / name).write_text(value, encoding='utf-8')
    (tmp_path / 'audit' / 'problem_cases.md').write_text('# Problems\n', encoding='utf-8')
    (rules / 'rule_registry.yaml').write_text(
        'version: 1\nentries:\n'
        '  - file: policies/orchestrator_policy.md\n    role: orchestrator_policy\n    required: true\n'
        '  - file: policies/runtime_policy.md\n    role: runtime_policy\n    required: true\n'
        '  - file: policies/gobd_compliance_policy.md\n    role: compliance_policy\n    required: true\n'
        '  - file: policies/accounting_analyst_policy.md\n    role: accounting_analyst_policy\n    required: true\n'
        '  - file: policies/problemfall_policy.md\n    role: problemfall_policy\n    required: true\n'
        '  - file: policies/freigabematrix.md\n    role: approval_matrix_policy\n    required: true\n',
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
async def test_reconciliation_context_is_visible_in_inspect_and_ui(monkeypatch, tmp_path: Path):
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

    async def _fake_feed_status(self):
        return {
            'reachable': True,
            'source_url': 'http://akaunting',
            'accounts_available': 1,
            'transactions_total': 4,
            'note': 'ok',
        }

    async def _fake_search_transactions(self, **kwargs):
        return [
            {
                'id': 6,
                'amount': '1450.00',
                'currency_code': 'EUR',
                'paid_at': '2026-03-12',
                'reference': 'INV-2026-101',
                'contact_name': 'Alpha GmbH',
                'type': 'income',
            }
        ]

    async def _fake_search_invoices(self, **kwargs):
        return [
            {
                'id': 101,
                'document_number': 'INV-2026-101',
                'amount': '1450.00',
                'status': 'sent',
                'contact_name': 'Alpha GmbH',
            }
        ]

    async def _fake_search_bills(self, **kwargs):
        return []

    import app.connectors.accounting_akaunting as akaunting_module

    monkeypatch.setattr(akaunting_module.AkauntingConnector, 'get_feed_status', _fake_feed_status)
    monkeypatch.setattr(akaunting_module.AkauntingConnector, 'search_transactions', _fake_search_transactions)
    monkeypatch.setattr(akaunting_module.AkauntingConnector, 'search_invoices', _fake_search_invoices)
    monkeypatch.setattr(akaunting_module.AkauntingConnector, 'search_bills', _fake_search_bills)

    app = _build_app()

    from app.dependencies import get_audit_service

    await get_audit_service().log_event(
        {
            'event_id': str(uuid.uuid4()),
            'case_id': 'bank-case-ui-1',
            'source': 'test',
            'action': 'BANK_TRANSACTION_PROBE_EXECUTED',
            'result': 'MATCH_FOUND',
            'document_ref': 'INV-2026-101',
            'llm_output': {'probe_fields': {'reference': 'INV-2026-101', 'amount': 1450.0, 'contact_name': 'Alpha GmbH'}},
        }
    )

    with TestClient(app) as client:
        login = client.post(
            '/auth/login',
            data={'username': 'admin', 'password': 'admin-pass', 'next': '/ui/dashboard'},
            follow_redirects=False,
        )
        assert login.status_code == 303

        case_json = client.get('/inspect/cases/bank-case-ui-1/json')
        assert case_json.status_code == 200
        body = case_json.json()
        assert body['banking_reconciliation_context']['doc_reference'] == 'INV-2026-101'
        assert body['banking_reconciliation_context']['match_signal'] == 'PLAUSIBLE'
        assert body['banking_reconciliation_context']['best_candidate']['transaction_id'] == 6

        detail = client.get('/ui/cases/bank-case-ui-1')
        assert detail.status_code == 200
        assert 'Banking Reconciliation Workbench' in detail.text
        assert 'INV-2026-101' in detail.text
        assert 'Document vs Accounting vs Banking' in detail.text
