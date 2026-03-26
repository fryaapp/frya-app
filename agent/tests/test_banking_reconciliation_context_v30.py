"""Reconciliation Context tests — post-Akaunting removal.

After Akaunting removal, BankTransactionService has no external feed.
ReconciliationContextService.build() always sees 0 transactions.
Accounting context comes from internal bookings via get_accounting_repository().

These tests verify:
- Signal computation given empty banking feed
- Accounting lookup via internal repository
- Comparison rows, safety invariants, open items
- UI/inspect endpoint integration
"""
from __future__ import annotations

import importlib
import json
import uuid
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

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


def _make_booking_mock(*, doc_number: str, description: str, gross_amount: float, status: str = 'BOOKED'):
    """Create a mock booking object matching AccountingRepository.list_bookings() return."""
    b = MagicMock()
    b.id = uuid.uuid4()
    b.document_number = doc_number
    b.description = description
    b.gross_amount = Decimal(str(gross_amount))
    b.status = status
    return b


def _make_context_service(
    *,
    chronology: list | None = None,
    open_items: list[OpenItem] | None = None,
) -> ReconciliationContextService:
    audit = AsyncMock()
    audit.by_case = AsyncMock(return_value=chronology or [])

    open_items_service = AsyncMock()
    open_items_service.list_by_case = AsyncMock(return_value=open_items or [])

    return ReconciliationContextService(
        bank_service=MagicMock(),
        audit_service=audit,
        open_items_service=open_items_service,
    )


@pytest.mark.asyncio
async def test_reconciliation_context_missing_data_no_transactions():
    """No external transactions → MISSING_DATA signal (banking feed is empty)."""
    svc = _make_context_service(
        chronology=[_make_event('BANK_TRANSACTION_PROBE_EXECUTED', document_ref='INV-2026-101')],
        open_items=[_make_open_item('Banking Review pruefen')],
    )

    mock_repo = MagicMock()
    mock_repo.list_bookings = AsyncMock(return_value=[])

    with patch('app.dependencies.get_accounting_repository', return_value=mock_repo):
        context = await svc.build(
            case_id='bank-case-1',
            reference='INV-2026-101',
            amount=1450.0,
            contact_name='Alpha GmbH',
            doc_type='income',
            doc_date='2026-03-11',
        )

    # No external transactions → signal is MISSING_DATA
    assert context.match_signal == ReconciliationSignal.MISSING_DATA
    assert context.bank_write_executed is False
    assert context.no_financial_write is True


@pytest.mark.asyncio
async def test_reconciliation_context_with_accounting_found():
    """Internal bookings found → accounting_result is FOUND."""
    booking = _make_booking_mock(
        doc_number='INV-2026-101',
        description='Alpha GmbH invoice',
        gross_amount=1450.0,
    )

    svc = _make_context_service(
        chronology=[_make_event('BANK_TRANSACTION_PROBE_EXECUTED', document_ref='INV-2026-101')],
    )

    mock_repo = MagicMock()
    mock_repo.list_bookings = AsyncMock(return_value=[booking])

    with patch('app.dependencies.get_accounting_repository', return_value=mock_repo):
        context = await svc.build(
            case_id='bank-case-2',
            reference='INV-2026-101',
            amount=1450.0,
            contact_name='Alpha GmbH',
            doc_type='income',
        )

    assert context.accounting_result == 'FOUND'
    # Still MISSING_DATA because banking feed is empty
    assert context.match_signal == ReconciliationSignal.MISSING_DATA
    assert context.bank_write_executed is False


@pytest.mark.asyncio
async def test_reconciliation_context_accounting_not_found():
    """No matching bookings → accounting_result is NOT_FOUND."""
    svc = _make_context_service()

    mock_repo = MagicMock()
    mock_repo.list_bookings = AsyncMock(return_value=[])

    with patch('app.dependencies.get_accounting_repository', return_value=mock_repo):
        context = await svc.build(
            case_id='bank-case-3',
            reference='INV-2026-999',
            amount=320.0,
            contact_name='Beta GmbH',
            doc_type='income',
        )

    assert context.accounting_result == 'NOT_FOUND'
    assert 'Banking-Kontext fehlt' in ' '.join(context.missing_data)


@pytest.mark.asyncio
async def test_reconciliation_context_accounting_ambiguous():
    """Multiple matching bookings → accounting_result is AMBIGUOUS."""
    b1 = _make_booking_mock(doc_number='OUT-2026-042', description='Office Supply', gross_amount=89.90)
    b2 = _make_booking_mock(doc_number='OUT-2026-042', description='Office Supply 2', gross_amount=89.90)

    svc = _make_context_service()

    mock_repo = MagicMock()
    mock_repo.list_bookings = AsyncMock(return_value=[b1, b2])

    with patch('app.dependencies.get_accounting_repository', return_value=mock_repo):
        context = await svc.build(
            case_id='bank-case-4',
            reference='OUT-2026-042',
            amount=89.90,
            contact_name='Office Supply',
            doc_type='expense',
        )

    assert context.accounting_result == 'AMBIGUOUS'


@pytest.mark.asyncio
async def test_reconciliation_context_accounting_unavailable():
    """Repository raises → accounting_result is UNAVAILABLE."""
    svc = _make_context_service()

    mock_repo = MagicMock()
    mock_repo.list_bookings = AsyncMock(side_effect=Exception('DB down'))

    with patch('app.dependencies.get_accounting_repository', return_value=mock_repo):
        context = await svc.build(
            case_id='bank-case-5',
            reference='INV-2026-101',
            amount=1450.0,
            contact_name='Alpha GmbH',
            doc_type='income',
        )

    assert context.accounting_result == 'UNAVAILABLE'
    assert context.bank_write_executed is False


@pytest.mark.asyncio
async def test_reconciliation_context_safety_invariants():
    """Safety: bank_write_executed=False, is_read_only=True, no_financial_write=True."""
    svc = _make_context_service()

    mock_repo = MagicMock()
    mock_repo.list_bookings = AsyncMock(return_value=[])

    with patch('app.dependencies.get_accounting_repository', return_value=mock_repo):
        context = await svc.build(case_id='safety-case', amount=100.0)

    assert context.bank_write_executed is False
    assert context.is_read_only is True
    assert context.no_financial_write is True


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
    monkeypatch.setenv('FRYA_N8N_BASE_URL', 'http://n8n')
    monkeypatch.setenv('FRYA_AUTH_USERS_JSON', _build_users_json())
    monkeypatch.setenv('FRYA_AUTH_SESSION_SECRET', 'test-secret')
    monkeypatch.setenv('FRYA_AUTH_COOKIE_SECURE', 'false')

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
        # With no external transactions, signal is MISSING_DATA
        assert body['banking_reconciliation_context']['match_signal'] == 'MISSING_DATA'

        detail = client.get('/ui/cases/bank-case-ui-1')
        assert detail.status_code == 200
        assert 'Banking Reconciliation Workbench' in detail.text
        assert 'INV-2026-101' in detail.text
        assert 'Document vs Accounting vs Banking' in detail.text
