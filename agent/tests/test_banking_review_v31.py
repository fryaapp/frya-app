from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.banking.models import (
    BankReconciliationDecision,
    BankReconciliationReviewInput,
    MatchQuality,
    ReconciliationContext,
    ReconciliationDecisionTrail,
    ReconciliationSignal,
    ReviewGuidanceLevel,
    TransactionCandidate,
)
from app.banking.review_service import BankReconciliationReviewService


def _make_context(
    *,
    signal: ReconciliationSignal,
    confirm_allowed: bool,
    tx_type: str = 'income',
    tx_id: int = 6,
) -> ReconciliationContext:
    candidate = TransactionCandidate(
        transaction_id=tx_id,
        amount=1450.0,
        currency='EUR',
        date='2026-03-12',
        reference='INV-2026-101' if tx_type == 'income' else 'OUT-2026-042',
        contact_name='Alpha GmbH' if tx_type == 'income' else 'Office Supply GmbH',
        tx_type=tx_type,
        confidence_score=85,
        match_quality=MatchQuality.HIGH,
        reason_codes=['AMOUNT_EXACT', 'REFERENCE_EXACT', 'TYPE_MATCH'],
    )
    return ReconciliationContext(
        case_id='bank-case-1',
        context_ref='bank-case-1:reconciliation-context-v1.6:abcdef123456',
        review_anchor_ref='bank-case-1:reconciliation-context-v1.6:abcdef123456',
        built_at='2026-03-14T10:00:00+00:00',
        doc_reference=candidate.reference,
        doc_amount=candidate.amount,
        doc_currency='EUR',
        doc_contact=candidate.contact_name,
        doc_type=tx_type,
        bank_result='MATCH_FOUND' if signal == ReconciliationSignal.PLAUSIBLE else 'CANDIDATE_FOUND',
        best_candidate=candidate,
        all_candidates=[candidate],
        accounting_result='FOUND',
        accounting_doc_id='101',
        match_signal=signal,
        operator_guidance='Test guidance',
        review_guidance=ReviewGuidanceLevel.CONFIRMABLE if confirm_allowed else ReviewGuidanceLevel.NOT_CONFIRMABLE,
        confirm_allowed=confirm_allowed,
        candidate_count=1,
        review_trail=ReconciliationDecisionTrail(current_stage='BANK_RECONCILIATION_REVIEW_PENDING'),
    )


def _make_service(context: ReconciliationContext) -> BankReconciliationReviewService:
    audit = AsyncMock()
    audit.log_event = AsyncMock()
    audit.by_case = AsyncMock(return_value=[])

    open_items = AsyncMock()
    open_items.list_by_case = AsyncMock(return_value=[])
    open_items.update_status = AsyncMock(return_value=None)
    open_items.create_item = AsyncMock(
        return_value=type(
            'OpenItemStub',
            (),
            {'item_id': 'oi-1', 'title': 'Follow-up', 'status': 'OPEN'},
        )()
    )

    reconciliation_context_service = AsyncMock()
    reconciliation_context_service.build = AsyncMock(return_value=context)

    return BankReconciliationReviewService(
        audit_service=audit,
        open_items_service=open_items,
        reconciliation_context_service=reconciliation_context_service,
    )


def _make_payload(
    *,
    decision: BankReconciliationDecision,
    tx_id: int = 6,
    workbench_ref: str = 'bank-case-1:reconciliation-context-v1.6:abcdef123456',
    signal: str = 'PLAUSIBLE',
) -> BankReconciliationReviewInput:
    return BankReconciliationReviewInput(
        case_id='bank-case-1',
        transaction_id=tx_id,
        candidate_amount=1450.0,
        candidate_currency='EUR',
        candidate_date='2026-03-12',
        candidate_reference='INV-2026-101',
        candidate_contact='Alpha GmbH',
        confidence_score=85,
        match_quality='HIGH',
        reason_codes=['AMOUNT_EXACT', 'REFERENCE_EXACT', 'TYPE_MATCH'],
        tx_type='income',
        probe_result='MATCH_FOUND',
        probe_note='Probe ok',
        workbench_ref=workbench_ref,
        workbench_signal=signal,
        workbench_guidance='Test guidance',
        review_guidance='CONFIRMABLE',
        candidate_rank=1,
        decision=decision,
        decision_note='note',
        decided_by='admin',
    )


@pytest.mark.asyncio
async def test_plausible_confirm_stores_workbench_ref():
    context = _make_context(signal=ReconciliationSignal.PLAUSIBLE, confirm_allowed=True)
    service = _make_service(context)

    result = await service.submit_review(_make_payload(decision=BankReconciliationDecision.CONFIRMED))

    assert result.workbench_ref == context.review_anchor_ref
    assert result.workbench_signal == 'PLAUSIBLE'
    assert result.confirm_allowed is True


@pytest.mark.asyncio
async def test_missing_data_blocks_confirm():
    context = _make_context(signal=ReconciliationSignal.MISSING_DATA, confirm_allowed=False)
    service = _make_service(context)

    with pytest.raises(ValueError, match='Confirm ist fuer diesen Workbench-Stand nicht erlaubt'):
        await service.submit_review(_make_payload(decision=BankReconciliationDecision.CONFIRMED, signal='MISSING_DATA'))


@pytest.mark.asyncio
async def test_conflict_reject_creates_conflict_follow_up():
    context = _make_context(signal=ReconciliationSignal.CONFLICT, confirm_allowed=False)
    service = _make_service(context)

    result = await service.submit_review(_make_payload(decision=BankReconciliationDecision.REJECTED, signal='CONFLICT'))

    assert result.outcome_status == 'BANK_RECONCILIATION_REJECTED'
    assert 'Konflikt' in (result.follow_up_open_item_title or '')


@pytest.mark.asyncio
async def test_expense_match_can_be_confirmed():
    context = _make_context(
        signal=ReconciliationSignal.PLAUSIBLE,
        confirm_allowed=True,
        tx_type='expense',
        tx_id=7,
    )
    service = _make_service(context)
    payload = _make_payload(
        decision=BankReconciliationDecision.CONFIRMED,
        tx_id=7,
    )
    payload.candidate_reference = 'OUT-2026-042'
    payload.candidate_contact = 'Office Supply GmbH'
    payload.tx_type = 'expense'

    result = await service.submit_review(payload)

    assert result.decision == BankReconciliationDecision.CONFIRMED
    assert result.transaction_id == 7
    assert result.confirm_allowed is True


@pytest.mark.asyncio
async def test_stale_workbench_ref_is_rejected():
    context = _make_context(signal=ReconciliationSignal.PLAUSIBLE, confirm_allowed=True)
    service = _make_service(context)

    with pytest.raises(ValueError, match='Workbench-Stand passt nicht mehr'):
        await service.submit_review(
            _make_payload(
                decision=BankReconciliationDecision.CONFIRMED,
                workbench_ref='bank-case-1:reconciliation-context-v1.6:stale',
            )
        )
