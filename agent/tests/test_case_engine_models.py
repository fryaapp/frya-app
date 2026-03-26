"""Tests for CaseEngine: CRUD via CaseRepository (memory backend)."""
from __future__ import annotations

import asyncio
import uuid
from decimal import Decimal


def _run(coro):
    return asyncio.run(coro)


def _repo():
    from app.case_engine.repository import CaseRepository
    return CaseRepository('memory://test')


TENANT = uuid.uuid4()


# ── Test 1: create_case generates case_number and status=DRAFT ────────────────

def test_create_case_defaults():
    async def run():
        repo = _repo()
        case = await repo.create_case(
            tenant_id=TENANT,
            case_type='incoming_invoice',
            title='Rechnung ACME',
            vendor_name='ACME GmbH',
        )
        assert case.case_number is not None
        assert case.case_number.startswith('CASE-')
        assert case.status == 'DRAFT'
        assert case.tenant_id == TENANT
        assert case.case_type == 'incoming_invoice'
    _run(run())


# ── Test 2: get_case retrieves stored case ────────────────────────────────────

def test_get_case():
    async def run():
        repo = _repo()
        case = await repo.create_case(tenant_id=TENANT, case_type='contract')
        fetched = await repo.get_case(case.id)
        assert fetched is not None
        assert fetched.id == case.id
        assert fetched.case_type == 'contract'
    _run(run())


# ── Test 3: get_case unknown → None ───────────────────────────────────────────

def test_get_case_unknown():
    async def run():
        repo = _repo()
        result = await repo.get_case(uuid.uuid4())
        assert result is None
    _run(run())


# ── Test 4: list_cases filters by tenant ──────────────────────────────────────

def test_list_cases_by_tenant():
    async def run():
        repo = _repo()
        t1 = uuid.uuid4()
        t2 = uuid.uuid4()
        await repo.create_case(tenant_id=t1, case_type='receipt')
        await repo.create_case(tenant_id=t1, case_type='salary')
        await repo.create_case(tenant_id=t2, case_type='other')
        cases_t1 = await repo.list_cases(t1)
        cases_t2 = await repo.list_cases(t2)
        assert len(cases_t1) == 2
        assert len(cases_t2) == 1
    _run(run())


# ── Test 5: list_cases filters by status ─────────────────────────────────────

def test_list_cases_by_status():
    async def run():
        repo = _repo()
        t = uuid.uuid4()
        c1 = await repo.create_case(tenant_id=t, case_type='incoming_invoice')
        # Add a doc so OPEN transition is allowed
        await repo.add_document_to_case(
            case_id=c1.id,
            document_source='paperless',
            document_source_id='doc-1',
            assignment_confidence='HIGH',
            assignment_method='manual',
        )
        await repo.update_case_status(c1.id, 'OPEN', operator=False)
        await repo.create_case(tenant_id=t, case_type='receipt')
        open_cases = await repo.list_cases(t, status='OPEN')
        draft_cases = await repo.list_cases(t, status='DRAFT')
        assert len(open_cases) == 1
        assert len(draft_cases) == 1
    _run(run())


# ── Test 6: case_number is sequential ────────────────────────────────────────

def test_case_numbers_sequential():
    async def run():
        repo = _repo()
        t = uuid.uuid4()
        c1 = await repo.create_case(tenant_id=t, case_type='other')
        c2 = await repo.create_case(tenant_id=t, case_type='other')
        n1 = int(c1.case_number.split('-')[2])
        n2 = int(c2.case_number.split('-')[2])
        assert n2 == n1 + 1
    _run(run())


# ── Test 7: add_document_to_case stores document ─────────────────────────────

def test_add_document_to_case():
    async def run():
        repo = _repo()
        case = await repo.create_case(tenant_id=TENANT, case_type='incoming_invoice')
        doc = await repo.add_document_to_case(
            case_id=case.id,
            document_source='paperless',
            document_source_id='paperless-42',
            assignment_confidence='HIGH',
            assignment_method='entity_amount',
            filename='rechnung.pdf',
        )
        assert doc.case_id == case.id
        assert doc.document_source == 'paperless'
        assert doc.filename == 'rechnung.pdf'
        docs = await repo.get_case_documents(case.id)
        assert len(docs) == 1
        assert docs[0].document_source_id == 'paperless-42'
    _run(run())


# ── Test 8: pagination ────────────────────────────────────────────────────────

def test_list_cases_pagination():
    async def run():
        repo = _repo()
        t = uuid.uuid4()
        for _ in range(5):
            await repo.create_case(tenant_id=t, case_type='other')
        page1 = await repo.list_cases(t, limit=2, offset=0)
        page2 = await repo.list_cases(t, limit=2, offset=2)
        assert len(page1) == 2
        assert len(page2) == 2
        ids1 = {c.id for c in page1}
        ids2 = {c.id for c in page2}
        assert ids1.isdisjoint(ids2)
    _run(run())


# ── Test 9: metadata stored on case ──────────────────────────────────────────

def test_case_metadata():
    async def run():
        repo = _repo()
        case = await repo.create_case(
            tenant_id=TENANT,
            case_type='other',
            metadata={'source': 'import', 'batch': 7},
        )
        assert case.metadata['source'] == 'import'
        assert case.metadata['batch'] == 7
    _run(run())


# ── Test 10: total_amount stored as Decimal ───────────────────────────────────

def test_case_total_amount():
    async def run():
        repo = _repo()
        case = await repo.create_case(
            tenant_id=TENANT,
            case_type='incoming_invoice',
            total_amount=Decimal('1234.56'),
        )
        fetched = await repo.get_case(case.id)
        assert fetched is not None
        assert fetched.total_amount == Decimal('1234.56')
    _run(run())
