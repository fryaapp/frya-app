from __future__ import annotations

import importlib
import json
import re
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.banking.models import (
    BankingClarificationCompletionInput,
    ExternalBankingProcessCompletionInput,
    BankingHandoffReadyInput,
    BankingHandoffResolutionDecision,
    BankingHandoffResolutionInput,
    ReconciliationContext,
)
from app.banking.review_service import BankReconciliationReviewService
from app.open_items.models import OpenItem


def _event(action: str, payload: dict | None = None):
    return SimpleNamespace(
        action=action,
        llm_output=payload or {},
        created_at='2026-03-14T10:00:00+00:00',
        document_ref='INV-2026-101',
        accounting_ref='INV-2026-101',
        policy_refs=[],
        approval_status=None,
        source='test',
        result=action,
        agent_name='test-agent',
    )


def _review_payload() -> dict:
    return {
        'review_id': 'review-1',
        'workbench_ref': 'bank-case-1:reconciliation-context-v1.6:anchor',
        'transaction_id': 6,
        'candidate_reference': 'INV-2026-101',
        'tx_type': 'income',
        'decision': 'CONFIRMED',
        'follow_up_open_item_id': 'oi-review',
        'follow_up_open_item_title': '[Banking] Manuellen Handoff vorbereiten: Income-Kandidat 6 bestaetigt',
        'reason_codes': ['AMOUNT_EXACT', 'REFERENCE_EXACT', 'TYPE_MATCH'],
    }


def _handoff_ready_payload() -> dict:
    return {
        'handoff_id': 'handoff-1',
        'review_ref': 'review-1',
        'workbench_ref': 'bank-case-1:reconciliation-context-v1.6:anchor',
        'transaction_id': 6,
        'candidate_reference': 'INV-2026-101',
        'handoff_open_item_id': 'oi-handoff',
        'handoff_open_item_title': '[Banking] Manuellen Handoff durchfuehren: Income-Kandidat 6',
    }


def _open_item(item_id: str, title: str, status: str) -> OpenItem:
    return OpenItem(
        item_id=item_id,
        case_id='bank-case-1',
        title=title,
        description='test',
        status=status,
        source='test',
    )


def _service(*, chronology: list, existing_items: list[OpenItem], created_item: OpenItem | None = None):
    audit = AsyncMock()
    audit.log_event = AsyncMock(return_value=None)
    audit.by_case = AsyncMock(return_value=chronology)

    open_items = AsyncMock()
    open_items.list_by_case = AsyncMock(return_value=existing_items)
    open_items.update_status = AsyncMock(return_value=None)
    open_items.create_item = AsyncMock(
        return_value=created_item
        or _open_item('oi-created', '[Banking] Follow-up', 'OPEN')
    )

    context_service = AsyncMock()
    context_service.build = AsyncMock(
        return_value=ReconciliationContext(
            case_id='bank-case-1',
            context_ref='ctx',
            review_anchor_ref='ctx',
            built_at='2026-03-14T10:00:00+00:00',
            bank_result='MATCH_FOUND',
        )
    )

    return BankReconciliationReviewService(
        audit_service=audit,
        open_items_service=open_items,
        reconciliation_context_service=context_service,
    ), audit, open_items


@pytest.mark.asyncio
async def test_handoff_ready_binds_to_confirmed_review_and_closes_review_item():
    review_item = _open_item('oi-review', _review_payload()['follow_up_open_item_title'], 'WAITING_DATA')
    created_item = _open_item('oi-handoff', '[Banking] Manuellen Handoff durchfuehren: Income-Kandidat 6', 'OPEN')
    service, audit, open_items = _service(
        chronology=[_event('BANK_RECONCILIATION_CONFIRMED', _review_payload())],
        existing_items=[review_item],
        created_item=created_item,
    )

    result = await service.mark_handoff_ready(
        BankingHandoffReadyInput(
            case_id='bank-case-1',
            review_ref='review-1',
            workbench_ref='bank-case-1:reconciliation-context-v1.6:anchor',
            transaction_id=6,
            handoff_note='An Banking-Team uebergeben.',
            handed_off_by='admin',
        )
    )

    assert result.outcome_status == 'BANKING_HANDOFF_READY'
    assert result.review_ref == 'review-1'
    assert result.workbench_ref.endswith(':anchor')
    assert result.closed_open_item_id == 'oi-review'
    assert result.handoff_open_item_id == 'oi-handoff'
    open_items.update_status.assert_awaited_with('oi-review', 'COMPLETED')
    audit.log_event.assert_awaited()


@pytest.mark.asyncio
async def test_handoff_ready_rejects_stale_review_ref():
    service, _, _ = _service(
        chronology=[_event('BANK_RECONCILIATION_CONFIRMED', _review_payload())],
        existing_items=[],
    )

    with pytest.raises(ValueError, match='Review-Ref passt nicht'):
        await service.mark_handoff_ready(
            BankingHandoffReadyInput(
                case_id='bank-case-1',
                review_ref='review-stale',
                workbench_ref='bank-case-1:reconciliation-context-v1.6:anchor',
            )
        )


@pytest.mark.asyncio
async def test_handoff_completed_closes_handoff_item_and_stays_write_free():
    handoff_item = _open_item('oi-handoff', _handoff_ready_payload()['handoff_open_item_title'], 'OPEN')
    service, audit, open_items = _service(
        chronology=[
            _event('BANK_RECONCILIATION_CONFIRMED', _review_payload()),
            _event('BANKING_HANDOFF_READY', _handoff_ready_payload()),
        ],
        existing_items=[handoff_item],
    )

    result = await service.resolve_handoff(
        BankingHandoffResolutionInput(
            case_id='bank-case-1',
            handoff_ref='handoff-1',
            decision=BankingHandoffResolutionDecision.COMPLETED,
            resolution_note='Von externer Stelle uebernommen.',
            resolved_by='admin',
        )
    )

    assert result.status == 'BANKING_HANDOFF_COMPLETED'
    assert result.follow_up_open_item_id is None
    assert result.bank_write_executed is False
    assert result.no_financial_write is True
    open_items.update_status.assert_awaited_with('oi-handoff', 'COMPLETED')
    audit.log_event.assert_awaited()


@pytest.mark.asyncio
async def test_handoff_returned_creates_clarification_follow_up():
    handoff_item = _open_item('oi-handoff', _handoff_ready_payload()['handoff_open_item_title'], 'OPEN')
    clarif_item = _open_item('oi-clarif', '[Banking] Handoff-Ruecklauf klaeren: Transaktion 6', 'OPEN')
    service, _, open_items = _service(
        chronology=[
            _event('BANK_RECONCILIATION_CONFIRMED', _review_payload()),
            _event('BANKING_HANDOFF_READY', _handoff_ready_payload()),
        ],
        existing_items=[handoff_item],
        created_item=clarif_item,
    )

    result = await service.resolve_handoff(
        BankingHandoffResolutionInput(
            case_id='bank-case-1',
            handoff_ref='handoff-1',
            decision=BankingHandoffResolutionDecision.RETURNED,
            resolution_note='Externe Stelle braucht weitere Klaerung.',
            resolved_by='admin',
        )
    )

    assert result.status == 'BANKING_HANDOFF_RETURNED'
    assert result.follow_up_open_item_id == 'oi-clarif'
    assert 'Klaeren' in result.follow_up_open_item_title or 'klaeren' in result.follow_up_open_item_title


@pytest.mark.asyncio
async def test_banking_clarification_completed_binds_to_returned_handoff():
    handoff_item = _open_item('oi-handoff', _handoff_ready_payload()['handoff_open_item_title'], 'COMPLETED')
    clarif_item = _open_item('oi-clarif', '[Banking] Handoff-Ruecklauf klaeren: Transaktion 6', 'OPEN')
    returned_payload = {
        **_handoff_ready_payload(),
        'resolution_id': 'resolution-1',
        'handoff_ref': 'handoff-1',
        'review_ref': 'review-1',
        'workbench_ref': 'bank-case-1:reconciliation-context-v1.6:anchor',
        'transaction_id': 6,
        'candidate_reference': 'INV-2026-101',
        'status': 'BANKING_HANDOFF_RETURNED',
        'decision': 'RETURNED',
        'clarification_ref': 'resolution-1',
        'follow_up_open_item_id': 'oi-clarif',
        'follow_up_open_item_title': clarif_item.title,
    }
    service, audit, open_items = _service(
        chronology=[
            _event('BANK_RECONCILIATION_CONFIRMED', _review_payload()),
            _event('BANKING_HANDOFF_READY', _handoff_ready_payload()),
            _event('BANKING_HANDOFF_RETURNED', returned_payload),
        ],
        existing_items=[handoff_item, clarif_item],
    )

    result = await service.complete_banking_clarification(
        BankingClarificationCompletionInput(
            case_id='bank-case-1',
            clarification_ref='resolution-1',
            clarification_note='Rueckfrage mit externer Stelle geklaert.',
            clarified_by='admin',
        )
    )

    assert result.status == 'BANKING_CLARIFICATION_COMPLETED'
    assert result.review_ref == 'review-1'
    assert result.handoff_ref == 'handoff-1'
    assert result.clarification_open_item_id == 'oi-clarif'
    assert result.bank_write_executed is False
    assert result.no_financial_write is True
    open_items.update_status.assert_awaited_with('oi-clarif', 'COMPLETED')
    audit.log_event.assert_awaited()


@pytest.mark.asyncio
async def test_external_banking_process_completed_binds_to_handoff_completed():
    handoff_item = _open_item('oi-handoff', _handoff_ready_payload()['handoff_open_item_title'], 'COMPLETED')
    outside_item = _open_item('oi-outside', '[Banking] Externen Banking-Abschluss dokumentieren: INV-2026-101', 'OPEN')
    completed_payload = {
        **_handoff_ready_payload(),
        'resolution_id': 'resolution-1',
        'handoff_ref': 'handoff-1',
        'review_ref': 'review-1',
        'workbench_ref': 'bank-case-1:reconciliation-context-v1.6:anchor',
        'transaction_id': 6,
        'candidate_reference': 'INV-2026-101',
        'status': 'BANKING_HANDOFF_COMPLETED',
        'decision': 'COMPLETED',
        'outside_process_open_item_id': 'oi-outside',
        'outside_process_open_item_title': outside_item.title,
    }
    service, audit, open_items = _service(
        chronology=[
            _event('BANK_RECONCILIATION_CONFIRMED', _review_payload()),
            _event('BANKING_HANDOFF_READY', _handoff_ready_payload()),
            _event('BANKING_HANDOFF_COMPLETED', completed_payload),
        ],
        existing_items=[handoff_item, outside_item],
    )

    result = await service.complete_external_banking_process(
        ExternalBankingProcessCompletionInput(
            case_id='bank-case-1',
            resolution_note='Extern abgeschlossen.',
            resolved_by='admin',
        )
    )

    assert result.status == 'EXTERNAL_BANKING_PROCESS_COMPLETED'
    assert result.review_ref == 'review-1'
    assert result.handoff_ref == 'handoff-1'
    assert result.transaction_id == 6
    assert result.outside_process_open_item_id == 'oi-outside'
    assert result.bank_write_executed is False
    assert result.no_financial_write is True
    open_items.update_status.assert_awaited_with('oi-outside', 'COMPLETED')
    audit.log_event.assert_awaited()


@pytest.mark.asyncio
async def test_external_banking_process_completed_binds_to_clarification_completed():
    handoff_item = _open_item('oi-handoff', _handoff_ready_payload()['handoff_open_item_title'], 'COMPLETED')
    clarif_item = _open_item('oi-clarif', '[Banking] Handoff-Ruecklauf klaeren: Transaktion 6', 'COMPLETED')
    outside_item = _open_item('oi-outside', '[Banking] Externen Banking-Abschluss dokumentieren: INV-2026-101', 'OPEN')
    returned_payload = {
        **_handoff_ready_payload(),
        'resolution_id': 'resolution-1',
        'handoff_ref': 'handoff-1',
        'review_ref': 'review-1',
        'workbench_ref': 'bank-case-1:reconciliation-context-v1.6:anchor',
        'transaction_id': 6,
        'candidate_reference': 'INV-2026-101',
        'status': 'BANKING_HANDOFF_RETURNED',
        'decision': 'RETURNED',
        'clarification_ref': 'resolution-1',
        'follow_up_open_item_id': 'oi-clarif',
        'follow_up_open_item_title': clarif_item.title,
    }
    clarification_payload = {
        'clarification_completion_id': 'clar-comp-1',
        'clarification_ref': 'resolution-1',
        'handoff_ref': 'handoff-1',
        'review_ref': 'review-1',
        'workbench_ref': 'bank-case-1:reconciliation-context-v1.6:anchor',
        'transaction_id': 6,
        'candidate_reference': 'INV-2026-101',
        'status': 'BANKING_CLARIFICATION_COMPLETED',
        'clarification_state': 'COMPLETED',
        'outside_process_open_item_id': 'oi-outside',
        'outside_process_open_item_title': outside_item.title,
    }
    service, audit, open_items = _service(
        chronology=[
            _event('BANK_RECONCILIATION_CONFIRMED', _review_payload()),
            _event('BANKING_HANDOFF_READY', _handoff_ready_payload()),
            _event('BANKING_HANDOFF_RETURNED', returned_payload),
            _event('BANKING_CLARIFICATION_COMPLETED', clarification_payload),
        ],
        existing_items=[handoff_item, clarif_item, outside_item],
    )

    result = await service.complete_external_banking_process(
        ExternalBankingProcessCompletionInput(
            case_id='bank-case-1',
            resolution_note='Extern nach Klaerung erledigt.',
            resolved_by='admin',
        )
    )

    assert result.status == 'EXTERNAL_BANKING_PROCESS_COMPLETED'
    assert result.review_ref == 'review-1'
    assert result.clarification_ref == 'resolution-1'
    assert result.outside_process_open_item_id == 'oi-outside'
    open_items.update_status.assert_awaited_with('oi-outside', 'COMPLETED')
    audit.log_event.assert_awaited()


@pytest.mark.asyncio
async def test_external_banking_process_completion_requires_internal_end_state():
    service, _, _ = _service(
        chronology=[_event('BANK_RECONCILIATION_REJECTED', {**_review_payload(), 'decision': 'REJECTED'})],
        existing_items=[],
    )

    with pytest.raises(ValueError, match='OUTSIDE_AGENT_BANKING_PROCESS'):
        await service.complete_external_banking_process(
            ExternalBankingProcessCompletionInput(
                case_id='bank-case-1',
                resolution_note='sollte nicht gehen',
                resolved_by='admin',
            )
        )


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


def _extract_csrf_token(html: str) -> str:
    match = re.search(r'name="csrf_token"\s+value="([^"]+)"', html)
    assert match, 'csrf_token nicht im HTML gefunden'
    return match.group(1)


@pytest.mark.asyncio
async def test_banking_handoff_visible_in_inspect_and_ui(monkeypatch, tmp_path: Path):
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

    from app.dependencies import get_audit_service, get_open_items_service

    open_items = get_open_items_service()
    review_item = await open_items.create_item(
        case_id='bank-case-ui-2',
        title='[Banking] Manuellen Handoff vorbereiten: Income-Kandidat 6 bestaetigt',
        description='Review bestaetigt.',
        source='test',
    )
    await open_items.update_status(review_item.item_id, 'WAITING_DATA')

    audit = get_audit_service()
    await audit.log_event(
        {
            'event_id': str(uuid.uuid4()),
            'case_id': 'bank-case-ui-2',
            'source': 'test',
            'action': 'BANK_TRANSACTION_PROBE_EXECUTED',
            'result': 'MATCH_FOUND',
            'document_ref': 'INV-2026-101',
            'llm_output': {'probe_fields': {'reference': 'INV-2026-101', 'amount': 1450.0, 'contact_name': 'Alpha GmbH'}},
        }
    )
    await audit.log_event(
        {
            'event_id': str(uuid.uuid4()),
            'case_id': 'bank-case-ui-2',
            'source': 'test',
            'action': 'BANK_RECONCILIATION_CONFIRMED',
            'result': 'BANK_RECONCILIATION_CONFIRMED',
            'document_ref': 'INV-2026-101',
            'llm_output': {
                'review_id': 'review-1',
                'transaction_id': 6,
                'decision': 'CONFIRMED',
                'workbench_ref': 'bank-case-ui-2:reconciliation-context-v1.6:anchor',
                'candidate_reference': 'INV-2026-101',
                'review_guidance': 'CONFIRMABLE',
                'reason_codes': ['AMOUNT_EXACT', 'REFERENCE_EXACT', 'TYPE_MATCH'],
                'follow_up_open_item_id': review_item.item_id,
                'follow_up_open_item_title': review_item.title,
                'bank_write_executed': False,
                'no_financial_write': True,
            },
        }
    )

    with TestClient(app) as client:
        login = client.post(
            '/auth/login',
            data={'username': 'admin', 'password': 'admin-pass', 'next': '/ui/dashboard'},
            follow_redirects=False,
        )
        assert login.status_code == 303

        case_page = client.get('/ui/cases/bank-case-ui-2')
        assert case_page.status_code == 200
        csrf = _extract_csrf_token(case_page.text)

        ready = client.post(
            '/inspect/cases/bank-case-ui-2/banking/handoff-ready',
            json={
                'review_ref': 'review-1',
                'workbench_ref': 'bank-case-ui-2:reconciliation-context-v1.6:anchor',
                'transaction_id': 6,
                'note': 'An Banking-Team uebergeben.',
            },
            headers={'x-frya-csrf-token': csrf},
        )
        assert ready.status_code == 200
        ready_body = ready.json()
        assert ready_body['outcome_status'] == 'BANKING_HANDOFF_READY'

        resolution = client.post(
            '/inspect/cases/bank-case-ui-2/banking/handoff-resolution',
            json={
                'handoff_ref': ready_body['handoff_id'],
                'decision': 'COMPLETED',
                'note': 'Externe Weitergabe dokumentiert.',
            },
            headers={'x-frya-csrf-token': csrf},
        )
        assert resolution.status_code == 200
        resolution_body = resolution.json()
        assert resolution_body['status'] == 'BANKING_HANDOFF_COMPLETED'

        case_json = client.get('/inspect/cases/bank-case-ui-2/json')
        assert case_json.status_code == 200
        body = case_json.json()
        assert body['banking_handoff_ready']['review_ref'] == 'review-1'
        assert body['banking_handoff_resolution']['status'] == 'BANKING_HANDOFF_COMPLETED'

        detail = client.get('/ui/cases/bank-case-ui-2')
        assert detail.status_code == 200
        assert 'Banking Handoff' in detail.text
        assert 'review-1' in detail.text
        assert 'BANKING_HANDOFF_COMPLETED' in detail.text

        external_completion = client.post(
            '/inspect/cases/bank-case-ui-2/external-banking-process-complete',
            json={'note': 'Extern dokumentiert abgeschlossen.'},
            headers={'x-frya-csrf-token': csrf},
        )
        assert external_completion.status_code == 200
        external_body = external_completion.json()
        assert external_body['status'] == 'EXTERNAL_BANKING_PROCESS_COMPLETED'

        case_json = client.get('/inspect/cases/bank-case-ui-2/json')
        assert case_json.status_code == 200
        body = case_json.json()
        assert body['outside_agent_banking_process']['status'] == 'EXTERNAL_BANKING_PROCESS_COMPLETED'
        assert body['external_banking_process_resolution']['status'] == 'EXTERNAL_BANKING_PROCESS_COMPLETED'

        detail = client.get('/ui/cases/bank-case-ui-2')
        assert detail.status_code == 200
        assert 'Externer Banking-Abschluss' in detail.text
        assert 'EXTERNAL_BANKING_PROCESS_COMPLETED' in detail.text


@pytest.mark.asyncio
async def test_banking_returned_clarification_visible_in_inspect_and_ui(monkeypatch, tmp_path: Path):
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

    from app.dependencies import get_audit_service, get_open_items_service

    open_items = get_open_items_service()
    review_item = await open_items.create_item(
        case_id='bank-case-ui-3',
        title='[Banking] Manuellen Handoff vorbereiten: Expense-Kandidat 7 bestaetigt',
        description='Review bestaetigt.',
        source='test',
    )
    await open_items.update_status(review_item.item_id, 'WAITING_DATA')

    audit = get_audit_service()
    await audit.log_event(
        {
            'event_id': str(uuid.uuid4()),
            'case_id': 'bank-case-ui-3',
            'source': 'test',
            'action': 'BANK_TRANSACTION_PROBE_EXECUTED',
            'result': 'MATCH_FOUND',
            'document_ref': 'OUT-2026-042',
            'llm_output': {'probe_fields': {'reference': 'OUT-2026-042', 'amount': 89.9, 'contact_name': 'City Shop'}},
        }
    )
    await audit.log_event(
        {
            'event_id': str(uuid.uuid4()),
            'case_id': 'bank-case-ui-3',
            'source': 'test',
            'action': 'BANK_RECONCILIATION_CONFIRMED',
            'result': 'BANK_RECONCILIATION_CONFIRMED',
            'document_ref': 'OUT-2026-042',
            'llm_output': {
                'review_id': 'review-7',
                'transaction_id': 7,
                'decision': 'CONFIRMED',
                'workbench_ref': 'bank-case-ui-3:reconciliation-context-v1.6:anchor',
                'candidate_reference': 'OUT-2026-042',
                'review_guidance': 'CONFIRMABLE',
                'reason_codes': ['AMOUNT_EXACT', 'REFERENCE_EXACT', 'TYPE_MATCH'],
                'follow_up_open_item_id': review_item.item_id,
                'follow_up_open_item_title': review_item.title,
                'tx_type': 'expense',
                'bank_write_executed': False,
                'no_financial_write': True,
            },
        }
    )

    with TestClient(app) as client:
        login = client.post(
            '/auth/login',
            data={'username': 'admin', 'password': 'admin-pass', 'next': '/ui/dashboard'},
            follow_redirects=False,
        )
        assert login.status_code == 303

        case_page = client.get('/ui/cases/bank-case-ui-3')
        assert case_page.status_code == 200
        csrf = _extract_csrf_token(case_page.text)

        ready = client.post(
            '/inspect/cases/bank-case-ui-3/banking/handoff-ready',
            json={
                'review_ref': 'review-7',
                'workbench_ref': 'bank-case-ui-3:reconciliation-context-v1.6:anchor',
                'transaction_id': 7,
                'note': 'An Banking-Team uebergeben.',
            },
            headers={'x-frya-csrf-token': csrf},
        )
        assert ready.status_code == 200
        ready_body = ready.json()

        returned = client.post(
            '/inspect/cases/bank-case-ui-3/banking/handoff-resolution',
            json={
                'handoff_ref': ready_body['handoff_id'],
                'decision': 'RETURNED',
                'note': 'Rueckfrage noetig.',
            },
            headers={'x-frya-csrf-token': csrf},
        )
        assert returned.status_code == 200
        returned_body = returned.json()
        assert returned_body['status'] == 'BANKING_HANDOFF_RETURNED'

        clarification = client.post(
            '/inspect/cases/bank-case-ui-3/bank-clarification-complete',
            json={
                'clarification_ref': returned_body['resolution_id'],
                'note': 'Rueckfrage mit externer Stelle abgeschlossen.',
            },
            headers={'x-frya-csrf-token': csrf},
        )
        assert clarification.status_code == 200
        clarification_body = clarification.json()
        assert clarification_body['status'] == 'BANKING_CLARIFICATION_COMPLETED'

        case_json = client.get('/inspect/cases/bank-case-ui-3/json')
        assert case_json.status_code == 200
        body = case_json.json()
        assert body['bank_clarification']['status'] == 'BANKING_CLARIFICATION_COMPLETED'
        assert body['bank_clarification']['review_ref'] == 'review-7'
        assert body['banking_handoff_resolution']['status'] == 'BANKING_HANDOFF_RETURNED'

        detail = client.get('/ui/cases/bank-case-ui-3')
        assert detail.status_code == 200
        assert 'Banking Klaerung' in detail.text
        assert 'BANKING_CLARIFICATION_COMPLETED' in detail.text

        external_completion = client.post(
            '/inspect/cases/bank-case-ui-3/external-banking-process-complete',
            json={'note': 'Extern nach Ruecklauf dokumentiert abgeschlossen.'},
            headers={'x-frya-csrf-token': csrf},
        )
        assert external_completion.status_code == 200
        external_body = external_completion.json()
        assert external_body['status'] == 'EXTERNAL_BANKING_PROCESS_COMPLETED'

        case_json = client.get('/inspect/cases/bank-case-ui-3/json')
        assert case_json.status_code == 200
        body = case_json.json()
        assert body['outside_agent_banking_process']['status'] == 'EXTERNAL_BANKING_PROCESS_COMPLETED'
        assert body['external_banking_process_resolution']['status'] == 'EXTERNAL_BANKING_PROCESS_COMPLETED'

        detail = client.get('/ui/cases/bank-case-ui-3')
        assert detail.status_code == 200
        assert 'Outside-Agent Banking' in detail.text
        assert 'EXTERNAL_BANKING_PROCESS_COMPLETED' in detail.text
