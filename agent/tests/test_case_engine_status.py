"""Tests for CaseEngine: status transition rules."""
from __future__ import annotations

import asyncio
import uuid

import pytest


def _run(coro):
    return asyncio.run(coro)


def _repo():
    from app.case_engine.repository import CaseRepository
    return CaseRepository('memory://test')


TENANT = uuid.uuid4()


# ── Pure transition logic (no DB needed) ─────────────────────────────────────

def test_allowed_transitions_no_exception():
    from app.case_engine.status import check_transition
    # DRAFT → DISCARDED
    check_transition('DRAFT', 'DISCARDED')
    # OPEN → OVERDUE
    check_transition('OPEN', 'OVERDUE')
    # OPEN → MERGED
    check_transition('OPEN', 'MERGED')
    # DISCARDED → OPEN
    check_transition('DISCARDED', 'OPEN')
    # OVERDUE → PAID with operator
    check_transition('OVERDUE', 'PAID', operator=True)


def test_forbidden_transition_raises():
    from app.case_engine.status import StatusTransitionError, check_transition
    with pytest.raises(StatusTransitionError):
        check_transition('CLOSED', 'OPEN')


def test_merged_is_terminal():
    from app.case_engine.status import StatusTransitionError, check_transition
    with pytest.raises(StatusTransitionError):
        check_transition('MERGED', 'OPEN')
    with pytest.raises(StatusTransitionError):
        check_transition('MERGED', 'CLOSED')


def test_paid_closed_require_operator():
    from app.case_engine.status import StatusTransitionError, check_transition
    for current, target in [
        ('OPEN', 'PAID'),
        ('OPEN', 'CLOSED'),
        ('OVERDUE', 'PAID'),
        ('OVERDUE', 'CLOSED'),
        ('PAID', 'CLOSED'),
    ]:
        with pytest.raises(StatusTransitionError, match='operator'):
            check_transition(current, target, operator=False)


def test_paid_closed_allowed_with_operator():
    from app.case_engine.status import check_transition
    for current, target in [
        ('OPEN', 'PAID'),
        ('OPEN', 'CLOSED'),
        ('OVERDUE', 'PAID'),
        ('OVERDUE', 'CLOSED'),
        ('PAID', 'CLOSED'),
    ]:
        check_transition(current, target, operator=True)  # must not raise


# ── Repository-level transitions (includes min-doc check) ────────────────────

def test_draft_to_open_without_docs_fails():
    async def run():
        from app.case_engine.status import StatusTransitionError
        repo = _repo()
        case = await repo.create_case(tenant_id=TENANT, case_type='other')
        with pytest.raises(StatusTransitionError, match='document'):
            await repo.update_case_status(case.id, 'OPEN')
    _run(run())


def test_draft_to_open_with_doc_succeeds():
    async def run():
        repo = _repo()
        case = await repo.create_case(tenant_id=TENANT, case_type='incoming_invoice')
        await repo.add_document_to_case(
            case_id=case.id,
            document_source='email',
            document_source_id='msg-001',
            assignment_confidence='MEDIUM',
            assignment_method='manual',
        )
        updated = await repo.update_case_status(case.id, 'OPEN')
        assert updated.status == 'OPEN'
    _run(run())


def test_draft_to_discarded_without_docs_ok():
    async def run():
        repo = _repo()
        case = await repo.create_case(tenant_id=TENANT, case_type='other')
        updated = await repo.update_case_status(case.id, 'DISCARDED')
        assert updated.status == 'DISCARDED'
    _run(run())


def test_open_to_paid_requires_operator():
    async def run():
        from app.case_engine.status import StatusTransitionError
        repo = _repo()
        case = await repo.create_case(tenant_id=TENANT, case_type='incoming_invoice')
        await repo.add_document_to_case(
            case_id=case.id,
            document_source='paperless',
            document_source_id='doc-99',
            assignment_confidence='HIGH',
            assignment_method='entity_amount',
        )
        await repo.update_case_status(case.id, 'OPEN')
        with pytest.raises(StatusTransitionError):
            await repo.update_case_status(case.id, 'PAID', operator=False)
        # With operator=True it must work
        updated = await repo.update_case_status(case.id, 'PAID', operator=True)
        assert updated.status == 'PAID'
    _run(run())


def test_closed_is_terminal_via_repo():
    async def run():
        from app.case_engine.status import StatusTransitionError
        repo = _repo()
        case = await repo.create_case(tenant_id=TENANT, case_type='other')
        await repo.add_document_to_case(
            case_id=case.id,
            document_source='manual',
            document_source_id='x-1',
            assignment_confidence='LOW',
            assignment_method='manual',
        )
        await repo.update_case_status(case.id, 'OPEN')
        await repo.update_case_status(case.id, 'CLOSED', operator=True)
        with pytest.raises(StatusTransitionError):
            await repo.update_case_status(case.id, 'OPEN')
    _run(run())


def test_allowed_transitions_helper():
    from app.case_engine.status import allowed_transitions
    assert 'OPEN' in allowed_transitions('DRAFT')
    assert 'PAID' in allowed_transitions('OPEN')
    assert allowed_transitions('CLOSED') == frozenset()
    assert allowed_transitions('MERGED') == frozenset()
