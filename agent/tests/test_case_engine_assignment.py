"""Tests for CaseEngine: two-layer assignment and LLM confidence cap."""
from __future__ import annotations

import asyncio
import uuid
from datetime import date
from decimal import Decimal


def _run(coro):
    return asyncio.run(coro)


def _repo():
    from app.case_engine.repository import CaseRepository
    return CaseRepository('memory://test')


TENANT = uuid.uuid4()


# ── LLM confidence cap (pure function) ───────────────────────────────────────

def test_llm_cap_certain_to_medium():
    from app.case_engine.assignment import cap_llm_confidence
    assert cap_llm_confidence('CERTAIN') == 'MEDIUM'


def test_llm_cap_high_to_medium():
    from app.case_engine.assignment import cap_llm_confidence
    assert cap_llm_confidence('HIGH') == 'MEDIUM'


def test_llm_cap_medium_stays_medium():
    from app.case_engine.assignment import cap_llm_confidence
    assert cap_llm_confidence('MEDIUM') == 'MEDIUM'


def test_llm_cap_low_stays_low():
    from app.case_engine.assignment import cap_llm_confidence
    assert cap_llm_confidence('LOW') == 'LOW'


# ── Layer 1: exact reference match → CERTAIN ─────────────────────────────────

def test_layer1_exact_reference_match():
    async def run():
        from app.case_engine.assignment import CaseAssignmentEngine, DocumentData

        repo = _repo()
        case = await repo.create_case(
            tenant_id=TENANT,
            case_type='incoming_invoice',
            vendor_name='ACME GmbH',
            total_amount=Decimal('500.00'),
        )
        await repo.add_reference(
            case_id=case.id,
            reference_type='invoice_number',
            reference_value='INV-2026-999',
        )

        engine = CaseAssignmentEngine(repo)
        doc = DocumentData(
            document_source='paperless',
            document_source_id='p-001',
            reference_values=[('invoice_number', 'INV-2026-999')],
            vendor_name='ACME GmbH',
            total_amount=500.0,
        )
        result = await engine.assign_document(TENANT, doc)

        assert result is not None
        assert result.case_id == case.id
        assert result.confidence == 'CERTAIN'
        assert result.method == 'hard_reference'
    _run(run())


# ── Layer 1: multiple matches → None (ambiguous) ─────────────────────────────

def test_layer1_ambiguous_reference_returns_none():
    async def run():
        from app.case_engine.assignment import CaseAssignmentEngine, DocumentData

        t = uuid.uuid4()
        repo = _repo()

        for _ in range(2):
            c = await repo.create_case(tenant_id=t, case_type='incoming_invoice')
            await repo.add_reference(
                case_id=c.id,
                reference_type='order_number',
                reference_value='ORD-SAME',
            )

        engine = CaseAssignmentEngine(repo)
        doc = DocumentData(
            document_source='email',
            document_source_id='e-001',
            reference_values=[('order_number', 'ORD-SAME')],
        )
        result = await engine.assign_document(t, doc)
        assert result is None
    _run(run())


# ── Layer 2: entity match (vendor + amount + date) → HIGH ────────────────────

def test_layer2_entity_match():
    async def run():
        from app.case_engine.assignment import CaseAssignmentEngine, DocumentData

        t = uuid.uuid4()
        repo = _repo()

        case = await repo.create_case(
            tenant_id=t,
            case_type='incoming_invoice',
            vendor_name='Muster GmbH',
            total_amount=Decimal('299.99'),
            due_date=date(2026, 4, 1),
        )
        # Must be OPEN for Layer 2 to consider it
        await repo.add_document_to_case(
            case_id=case.id,
            document_source='manual',
            document_source_id='seed-1',
            assignment_confidence='LOW',
            assignment_method='manual',
        )
        await repo.update_case_status(case.id, 'OPEN')

        engine = CaseAssignmentEngine(repo)
        doc = DocumentData(
            document_source='paperless',
            document_source_id='p-002',
            vendor_name='Muster GmbH',
            total_amount=299.99,
            document_date=date(2026, 3, 28),
        )
        result = await engine.assign_document(t, doc)

        assert result is not None
        assert result.case_id == case.id
        assert result.confidence == 'HIGH'
        assert result.method == 'entity_amount'
    _run(run())


# ── Layer 2: fuzzy vendor match (Levenshtein ≤ 2) ────────────────────────────

def test_layer2_fuzzy_vendor_match():
    async def run():
        from app.case_engine.assignment import CaseAssignmentEngine, DocumentData

        t = uuid.uuid4()
        repo = _repo()

        case = await repo.create_case(
            tenant_id=t,
            case_type='incoming_invoice',
            vendor_name='Muster GmbH',
            total_amount=Decimal('100.00'),
        )
        await repo.add_document_to_case(
            case_id=case.id,
            document_source='manual',
            document_source_id='s-1',
            assignment_confidence='LOW',
            assignment_method='manual',
        )
        await repo.update_case_status(case.id, 'OPEN')

        engine = CaseAssignmentEngine(repo)
        # 'Muster Gmbh' vs 'Muster GmbH' — case-insensitive exact match
        doc = DocumentData(
            document_source='email',
            document_source_id='e-fuzz',
            vendor_name='Muster Gmbh',
            total_amount=100.0,
        )
        result = await engine.assign_document(t, doc)
        assert result is not None
        assert result.confidence == 'HIGH'
    _run(run())


# ── Layer 2: no match → None ─────────────────────────────────────────────────

def test_layer2_no_match():
    async def run():
        from app.case_engine.assignment import CaseAssignmentEngine, DocumentData

        t = uuid.uuid4()
        repo = _repo()

        case = await repo.create_case(
            tenant_id=t,
            case_type='incoming_invoice',
            vendor_name='ACME Corp',
            total_amount=Decimal('500.00'),
        )
        await repo.add_document_to_case(
            case_id=case.id,
            document_source='manual',
            document_source_id='s-2',
            assignment_confidence='LOW',
            assignment_method='manual',
        )
        await repo.update_case_status(case.id, 'OPEN')

        engine = CaseAssignmentEngine(repo)
        doc = DocumentData(
            document_source='paperless',
            document_source_id='p-999',
            vendor_name='Completely Different GmbH',
            total_amount=999.0,
        )
        result = await engine.assign_document(t, doc)
        assert result is None
    _run(run())


# ── Layer 2: DRAFT cases are not considered ───────────────────────────────────

def test_layer2_ignores_draft_cases():
    async def run():
        from app.case_engine.assignment import CaseAssignmentEngine, DocumentData

        t = uuid.uuid4()
        repo = _repo()

        # Create a DRAFT case (no documents → can't open)
        await repo.create_case(
            tenant_id=t,
            case_type='incoming_invoice',
            vendor_name='Draft Vendor GmbH',
            total_amount=Decimal('200.00'),
        )

        engine = CaseAssignmentEngine(repo)
        doc = DocumentData(
            document_source='email',
            document_source_id='e-draft',
            vendor_name='Draft Vendor GmbH',
            total_amount=200.0,
        )
        result = await engine.assign_document(t, doc)
        assert result is None  # DRAFT cases not considered in Layer 2
    _run(run())


# ── Cross-tenant isolation ────────────────────────────────────────────────────

def test_cross_tenant_isolation():
    async def run():
        from app.case_engine.assignment import CaseAssignmentEngine, DocumentData

        t1 = uuid.uuid4()
        t2 = uuid.uuid4()
        repo = _repo()

        case = await repo.create_case(
            tenant_id=t1,
            case_type='incoming_invoice',
            vendor_name='Shared Vendor GmbH',
            total_amount=Decimal('100.00'),
        )
        await repo.add_document_to_case(
            case_id=case.id,
            document_source='manual',
            document_source_id='s-iso',
            assignment_confidence='LOW',
            assignment_method='manual',
        )
        await repo.update_case_status(case.id, 'OPEN')

        engine = CaseAssignmentEngine(repo)
        # t2 has no cases → should get None even though t1 has a matching case
        doc = DocumentData(
            document_source='email',
            document_source_id='e-iso',
            vendor_name='Shared Vendor GmbH',
            total_amount=100.0,
        )
        result = await engine.assign_document(t2, doc)
        assert result is None
    _run(run())
