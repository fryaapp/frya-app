"""Tests for CaseEngine: case merging."""
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


async def _open_case(repo, tenant, case_type='incoming_invoice'):
    """Create and open a case with one seed document."""
    case = await repo.create_case(tenant_id=tenant, case_type=case_type)
    await repo.add_document_to_case(
        case_id=case.id,
        document_source='manual',
        document_source_id=f'seed-{case.id}',
        assignment_confidence='LOW',
        assignment_method='manual',
    )
    return await repo.update_case_status(case.id, 'OPEN')


# ── Merge: source → MERGED, merged_into_case_id set ─────────────────────────

def test_merge_sets_source_status():
    async def run():
        repo = _repo()
        source = await _open_case(repo, TENANT)
        target = await _open_case(repo, TENANT)

        result = await repo.merge_cases(source.id, target.id)
        assert result.status == 'MERGED'
        assert result.merged_into_case_id == target.id
    _run(run())


# ── Merge: documents from source are moved to target ─────────────────────────

def test_merge_moves_documents_to_target():
    async def run():
        repo = _repo()
        source = await _open_case(repo, TENANT)
        target = await _open_case(repo, TENANT)

        # Add an extra document to source
        await repo.add_document_to_case(
            case_id=source.id,
            document_source='paperless',
            document_source_id='pl-src-1',
            assignment_confidence='HIGH',
            assignment_method='entity_amount',
            filename='rechnung_src.pdf',
        )

        source_docs_before = await repo.get_case_documents(source.id)
        assert len(source_docs_before) == 2  # seed + pl-src-1

        await repo.merge_cases(source.id, target.id)

        target_docs = await repo.get_case_documents(target.id)
        source_docs_after = await repo.get_case_documents(source.id)

        # All source docs moved (the 2 source docs + 1 target seed = 3 in target)
        doc_source_ids = {d.document_source_id for d in target_docs}
        assert 'pl-src-1' in doc_source_ids
        # Source has no documents left (or only conflicts that could not move)
        assert len(source_docs_after) == 0
    _run(run())


# ── Merge: duplicate documents are not moved (dedup) ─────────────────────────

def test_merge_skips_duplicate_documents():
    async def run():
        repo = _repo()
        source = await _open_case(repo, TENANT)
        target = await _open_case(repo, TENANT)

        # Add the SAME document to both cases
        for case_id in (source.id, target.id):
            await repo.add_document_to_case(
                case_id=case_id,
                document_source='paperless',
                document_source_id='shared-doc',
                assignment_confidence='HIGH',
                assignment_method='entity_amount',
            )

        await repo.merge_cases(source.id, target.id)

        target_docs = await repo.get_case_documents(target.id)
        # Only 1 copy of 'shared-doc' in target (not 2)
        shared = [d for d in target_docs if d.document_source_id == 'shared-doc']
        assert len(shared) == 1
    _run(run())


# ── Merge: source not found → ValueError ─────────────────────────────────────

def test_merge_source_not_found():
    async def run():
        repo = _repo()
        target = await _open_case(repo, TENANT)
        with pytest.raises(ValueError, match='not found'):
            await repo.merge_cases(uuid.uuid4(), target.id)
    _run(run())


# ── Merge: DRAFT case cannot be merged ───────────────────────────────────────

def test_merge_draft_source_not_allowed():
    async def run():
        from app.case_engine.status import StatusTransitionError
        repo = _repo()
        source = await repo.create_case(tenant_id=TENANT, case_type='other')
        target = await _open_case(repo, TENANT)
        with pytest.raises(StatusTransitionError):
            await repo.merge_cases(source.id, target.id)
    _run(run())


# ── Merge: source case is re-fetchable and confirms MERGED ───────────────────

def test_merge_source_fetchable_after_merge():
    async def run():
        repo = _repo()
        source = await _open_case(repo, TENANT)
        target = await _open_case(repo, TENANT)

        await repo.merge_cases(source.id, target.id)

        fetched = await repo.get_case(source.id)
        assert fetched is not None
        assert fetched.status == 'MERGED'
        assert fetched.merged_into_case_id == target.id
    _run(run())
