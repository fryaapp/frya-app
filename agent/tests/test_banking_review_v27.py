"""V1.3 Banking Reconciliation Review unit tests.

Covers:
- CONFIRMED path: outcome_status, audit event, follow-up open item (WAITING_DATA)
- REJECTED path: outcome_status, audit event, follow-up open item (OPEN)
- Safety: bank_write_executed always False, no_financial_write always True
- Audit event action names correct
- Open item titles contain meaningful info
- get_latest_review returns last audit event
- Both paths produce a review_id (UUID)
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.banking.models import (
    BankReconciliationDecision,
    BankReconciliationReviewInput,
    ReconciliationContext,
    ReconciliationDecisionTrail,
    ReconciliationSignal,
    ReviewGuidanceLevel,
    TransactionCandidate,
)
from app.banking.review_service import BankReconciliationReviewService
from app.open_items.models import OpenItem


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_open_item(item_id: str | None = None, title: str = 'BANK_RECONCILIATION_REVIEW: TX-1', status: str = 'OPEN') -> OpenItem:
    return OpenItem(
        item_id=item_id or str(uuid.uuid4()),
        case_id='doc-1',
        title=title,
        description='Pending banking review',
        status=status,  # type: ignore[arg-type]
        source='test',
    )


def _make_created_item(item_id: str | None = None, title: str = 'Follow-up') -> OpenItem:
    return OpenItem(
        item_id=item_id or str(uuid.uuid4()),
        case_id='doc-1',
        title=title,
        description='Follow-up item',
        status='OPEN',
        source='test',
    )


def _make_service(
    existing_items: list[OpenItem] | None = None,
    created_item: OpenItem | None = None,
    chronology: list | None = None,
    reconciliation_context: ReconciliationContext | None = None,
) -> BankReconciliationReviewService:
    audit = AsyncMock()
    audit.log_event = AsyncMock(return_value=None)
    audit.by_case = AsyncMock(return_value=chronology or [])

    oi = AsyncMock()
    oi.list_by_case = AsyncMock(return_value=existing_items or [])
    oi.update_status = AsyncMock(return_value=None)
    oi.create_item = AsyncMock(return_value=created_item or _make_created_item())

    context_service = AsyncMock()
    context_service.build = AsyncMock(return_value=reconciliation_context or _make_reconciliation_context())

    return BankReconciliationReviewService(
        audit_service=audit,
        open_items_service=oi,
        reconciliation_context_service=context_service,
    )


def _make_reconciliation_context(
    *,
    signal: ReconciliationSignal = ReconciliationSignal.PLAUSIBLE,
    confirm_allowed: bool = True,
    tx_id: int = 1,
    tx_type: str = 'income',
) -> ReconciliationContext:
    candidate = TransactionCandidate(
        transaction_id=tx_id,
        amount=250.0,
        currency='EUR',
        date='2026-03-01',
        reference='INV-2026-001',
        contact_name='Muster GmbH',
        tx_type=tx_type,
        confidence_score=70,
        match_quality='HIGH',
        reason_codes=['AMOUNT_EXACT', 'REFERENCE_EXACT', 'TYPE_MATCH'],
    )
    secondary = TransactionCandidate(
        transaction_id=2,
        amount=75.5,
        currency='EUR',
        date='2026-03-05',
        reference='OUT-2026-007',
        contact_name='Other Corp',
        tx_type='income',
        confidence_score=25,
        match_quality='LOW',
        reason_codes=['AMOUNT_NEAR'],
    )
    return ReconciliationContext(
        case_id='doc-1',
        context_ref='doc-1:reconciliation-context-v1.6:abc123',
        review_anchor_ref='doc-1:reconciliation-context-v1.6:abc123',
        built_at='2026-03-14T10:00:00+00:00',
        doc_reference='INV-2026-001',
        doc_amount=250.0,
        doc_currency='EUR',
        doc_type='income',
        bank_result='MATCH_FOUND',
        bank_feed_reachable=True,
        bank_feed_total=3,
        best_candidate=candidate,
        all_candidates=[candidate, secondary],
        accounting_result='FOUND',
        accounting_doc_id='101',
        match_signal=signal,
        review_guidance=ReviewGuidanceLevel.CONFIRMABLE if confirm_allowed else ReviewGuidanceLevel.NOT_CONFIRMABLE,
        operator_guidance='Test guidance',
        confirm_allowed=confirm_allowed,
        candidate_count=1,
        review_trail=ReconciliationDecisionTrail(current_stage='BANK_RECONCILIATION_REVIEW_PENDING'),
    )


def _confirm_payload(case_id: str = 'doc-1', tx_id: int = 1) -> BankReconciliationReviewInput:
    return BankReconciliationReviewInput(
        case_id=case_id,
        transaction_id=tx_id,
        candidate_amount=250.0,
        candidate_currency='EUR',
        candidate_date='2026-03-01',
        candidate_reference='INV-2026-001',
        candidate_contact='Muster GmbH',
        confidence_score=70,
        match_quality='HIGH',
        reason_codes=['AMOUNT_EXACT', 'REFERENCE_MATCH'],
        tx_type='income',
        probe_result='MATCH_FOUND',
        probe_note='Eindeutiger Treffer.',
        workbench_ref='doc-1:reconciliation-context-v1.6:abc123',
        workbench_signal='PLAUSIBLE',
        workbench_guidance='Test guidance',
        review_guidance='CONFIRMABLE',
        candidate_rank=1,
        decision=BankReconciliationDecision.CONFIRMED,
        decision_note='Passt zu Rechnung INV-2026-001.',
        decided_by='operator@frya.de',
    )


def _reject_payload(case_id: str = 'doc-1', tx_id: int = 2) -> BankReconciliationReviewInput:
    return BankReconciliationReviewInput(
        case_id=case_id,
        transaction_id=tx_id,
        candidate_amount=75.50,
        candidate_currency='EUR',
        candidate_date='2026-03-05',
        candidate_reference='OUT-2026-007',
        confidence_score=25,
        match_quality='LOW',
        reason_codes=['AMOUNT_NEAR'],
        tx_type='income',
        probe_result='CANDIDATE_FOUND',
        probe_note='Schwacher Kandidat.',
        workbench_ref='doc-1:reconciliation-context-v1.6:abc123',
        workbench_signal='UNCLEAR',
        workbench_guidance='Test guidance',
        review_guidance='CLARIFICATION_NEEDED',
        candidate_rank=1,
        decision=BankReconciliationDecision.REJECTED,
        decision_note='Betrag passt nicht zu erwarteter Rechnung.',
        decided_by='operator@frya.de',
    )


# ---------------------------------------------------------------------------
# CONFIRMED path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_confirm_outcome_status():
    svc = _make_service()
    result = await svc.submit_review(_confirm_payload())
    assert result.outcome_status == 'BANK_RECONCILIATION_CONFIRMED'


@pytest.mark.asyncio
async def test_confirm_decision_stored():
    svc = _make_service()
    result = await svc.submit_review(_confirm_payload())
    assert result.decision == BankReconciliationDecision.CONFIRMED


@pytest.mark.asyncio
async def test_confirm_follow_up_item_created():
    follow_up = _make_created_item(title='[Banking] Manuelle Abstimmung erforderlich: Transaktion 1 bestaetigt')
    svc = _make_service(created_item=follow_up)
    result = await svc.submit_review(_confirm_payload())
    assert result.follow_up_open_item_id == follow_up.item_id


@pytest.mark.asyncio
async def test_confirm_audit_action_name():
    audit = AsyncMock()
    audit.log_event = AsyncMock(return_value=None)
    audit.by_case = AsyncMock(return_value=[])
    oi = AsyncMock()
    oi.list_by_case = AsyncMock(return_value=[])
    oi.update_status = AsyncMock(return_value=None)
    oi.create_item = AsyncMock(return_value=_make_created_item())

    context_service = AsyncMock()
    context_service.build = AsyncMock(return_value=_make_reconciliation_context())

    svc = BankReconciliationReviewService(
        audit_service=audit,
        open_items_service=oi,
        reconciliation_context_service=context_service,
    )
    await svc.submit_review(_confirm_payload())

    call_kwargs = audit.log_event.call_args[0][0]
    assert call_kwargs['action'] == 'BANK_RECONCILIATION_CONFIRMED'
    assert call_kwargs['approval_status'] == 'APPROVED'


# ---------------------------------------------------------------------------
# REJECTED path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reject_outcome_status():
    svc = _make_service()
    result = await svc.submit_review(_reject_payload())
    assert result.outcome_status == 'BANK_RECONCILIATION_REJECTED'


@pytest.mark.asyncio
async def test_reject_decision_stored():
    svc = _make_service()
    result = await svc.submit_review(_reject_payload())
    assert result.decision == BankReconciliationDecision.REJECTED


@pytest.mark.asyncio
async def test_reject_audit_action_name():
    audit = AsyncMock()
    audit.log_event = AsyncMock(return_value=None)
    audit.by_case = AsyncMock(return_value=[])
    oi = AsyncMock()
    oi.list_by_case = AsyncMock(return_value=[])
    oi.update_status = AsyncMock(return_value=None)
    oi.create_item = AsyncMock(return_value=_make_created_item())

    context_service = AsyncMock()
    context_service.build = AsyncMock(return_value=_make_reconciliation_context())

    svc = BankReconciliationReviewService(
        audit_service=audit,
        open_items_service=oi,
        reconciliation_context_service=context_service,
    )
    await svc.submit_review(_reject_payload())

    call_kwargs = audit.log_event.call_args[0][0]
    assert call_kwargs['action'] == 'BANK_RECONCILIATION_REJECTED'
    assert call_kwargs['approval_status'] == 'REJECTED'


# ---------------------------------------------------------------------------
# Safety invariants — always hold for both paths
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize('payload_fn', [_confirm_payload, _reject_payload])
async def test_safety_bank_write_executed_false(payload_fn):
    svc = _make_service()
    result = await svc.submit_review(payload_fn())
    assert result.bank_write_executed is False, 'bank_write_executed must be False'


@pytest.mark.asyncio
@pytest.mark.parametrize('payload_fn', [_confirm_payload, _reject_payload])
async def test_safety_no_financial_write_true(payload_fn):
    svc = _make_service()
    result = await svc.submit_review(payload_fn())
    assert result.no_financial_write is True, 'no_financial_write must be True'


@pytest.mark.asyncio
@pytest.mark.parametrize('payload_fn', [_confirm_payload, _reject_payload])
async def test_review_id_is_uuid(payload_fn):
    svc = _make_service()
    result = await svc.submit_review(payload_fn())
    parsed = uuid.UUID(result.review_id)
    assert str(parsed) == result.review_id


@pytest.mark.asyncio
@pytest.mark.parametrize('payload_fn', [_confirm_payload, _reject_payload])
async def test_audit_event_id_is_uuid(payload_fn):
    svc = _make_service()
    result = await svc.submit_review(payload_fn())
    parsed = uuid.UUID(result.audit_event_id)
    assert str(parsed) == result.audit_event_id


# ---------------------------------------------------------------------------
# Audit payload content
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_audit_payload_contains_candidate_snapshot():
    audit = AsyncMock()
    captured = {}
    async def capture(ev):
        captured.update(ev)
    audit.log_event = capture
    audit.by_case = AsyncMock(return_value=[])
    oi = AsyncMock()
    oi.list_by_case = AsyncMock(return_value=[])
    oi.update_status = AsyncMock(return_value=None)
    oi.create_item = AsyncMock(return_value=_make_created_item())

    context_service = AsyncMock()
    context_service.build = AsyncMock(return_value=_make_reconciliation_context())

    svc = BankReconciliationReviewService(
        audit_service=audit,
        open_items_service=oi,
        reconciliation_context_service=context_service,
    )
    await svc.submit_review(_confirm_payload())

    output = captured.get('llm_output', {})
    assert output.get('confidence_score') == 70
    assert output.get('match_quality') == 'HIGH'
    assert 'AMOUNT_EXACT' in output.get('reason_codes', [])
    assert output.get('candidate_amount') == 250.0
    assert output.get('candidate_reference') == 'INV-2026-001'
    assert output.get('workbench_ref') == 'doc-1:reconciliation-context-v1.6:abc123'
    assert output.get('bank_write_executed') is False
    assert output.get('no_financial_write') is True


# ---------------------------------------------------------------------------
# Open item: existing review item closed, follow-up created
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_existing_review_item_completed_on_confirm():
    existing = _make_open_item(title='BANK_RECONCILIATION_REVIEW: TX', status='OPEN')
    oi = AsyncMock()
    oi.list_by_case = AsyncMock(return_value=[existing])
    oi.update_status = AsyncMock(return_value=None)
    oi.create_item = AsyncMock(return_value=_make_created_item())

    audit = AsyncMock()
    audit.log_event = AsyncMock(return_value=None)
    audit.by_case = AsyncMock(return_value=[])

    context_service = AsyncMock()
    context_service.build = AsyncMock(return_value=_make_reconciliation_context())

    svc = BankReconciliationReviewService(
        audit_service=audit,
        open_items_service=oi,
        reconciliation_context_service=context_service,
    )
    result = await svc.submit_review(_confirm_payload())

    # First call: complete the existing review item; second call: set follow-up to WAITING_DATA
    calls = [str(c) for c in oi.update_status.call_args_list]
    assert any(existing.item_id in c and 'COMPLETED' in c for c in calls), \
        f'Expected COMPLETED call for {existing.item_id}, got: {calls}'
    assert result.open_item_id == existing.item_id


# ---------------------------------------------------------------------------
# get_latest_review
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_latest_review_returns_none_when_no_review():
    svc = _make_service(chronology=[])
    result = await svc.get_latest_review('doc-1')
    assert result is None


@pytest.mark.asyncio
async def test_get_latest_review_returns_last_event():
    event = MagicMock()
    event.action = 'BANK_RECONCILIATION_CONFIRMED'
    event.result = 'BANK_RECONCILIATION_CONFIRMED'
    event.created_at = '2026-03-14T10:00:00'
    event.llm_output = {'decision': 'CONFIRMED', 'transaction_id': 1, 'bank_write_executed': False}

    svc = _make_service(chronology=[event])
    result = await svc.get_latest_review('doc-1')
    assert result is not None
    assert result['action'] == 'BANK_RECONCILIATION_CONFIRMED'
