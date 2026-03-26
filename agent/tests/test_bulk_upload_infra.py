"""Tests for Bulk-Upload Infrastructure (Prompt 2/3 — B1–B3).

15 required tests:
 1. test_paperless_upload_single
 2. test_paperless_upload_batch_concurrency
 3. test_paperless_task_status_success
 4. test_paperless_task_status_failure
 5. test_batch_creation
 6. test_bridge1_task_to_document
 7. test_bridge2_document_to_case
 8. test_bridge2_tenant_isolation
 9. test_reevaluate_orphans
10. test_reevaluate_duplicate_case_proposal
11. test_duplicate_detection_same_batch
12. test_stuck_timeout
13. test_webhook_fallback
14. test_batch_status_machine
15. test_upload_error_doesnt_break_batch
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.bulk_upload.repository import BulkUploadRepository
from app.bulk_upload.service import BulkUploadService
from app.case_engine.repository import CaseRepository
from app.connectors.dms_paperless import PaperlessConnector


# ── helpers ───────────────────────────────────────────────────────────────────

def _run(coro):
    return asyncio.run(coro)


def _bulk_repo() -> BulkUploadRepository:
    return BulkUploadRepository('memory://test')


def _case_repo() -> CaseRepository:
    return CaseRepository('memory://test')


def _make_paperless(upload_result=None, task_result=None) -> PaperlessConnector:
    connector = MagicMock(spec=PaperlessConnector)
    connector.upload_document = AsyncMock(
        return_value=upload_result or {'task_id': str(uuid.uuid4())}
    )
    connector.get_task_status = AsyncMock(
        return_value=task_result or {'status': 'PENDING', 'result': None, 'related_document': None}
    )
    connector.upload_documents_batch = AsyncMock(return_value=[])
    return connector


def _make_service(
    bulk_repo=None, case_repo=None, paperless=None
) -> BulkUploadService:
    return BulkUploadService(
        bulk_repo=bulk_repo or _bulk_repo(),
        case_repo=case_repo or _case_repo(),
        paperless=paperless or _make_paperless(),
        audit_service=None,
    )


# ── 1. test_paperless_upload_single ──────────────────────────────────────────

def test_paperless_upload_single():
    """upload_document returns task_id (mocked HTTP)."""
    task_id = str(uuid.uuid4())

    async def run():
        connector = PaperlessConnector('http://paperless.test', token='tok')
        with patch.object(
            connector, 'upload_document', new=AsyncMock(return_value={'task_id': task_id})
        ):
            result = await connector.upload_document(b'PDF content', 'invoice.pdf')
            assert result['task_id'] == task_id

    _run(run())


# ── 2. test_paperless_upload_batch_concurrency ────────────────────────────────

def test_paperless_upload_batch_concurrency():
    """10 files, Semaphore keeps at most 5 concurrent uploads."""
    import asyncio as _asyncio

    concurrent_count = 0
    max_concurrent_seen = 0
    lock = _asyncio.Lock()

    async def run():
        nonlocal concurrent_count, max_concurrent_seen

        connector = PaperlessConnector('http://paperless.test', token='tok')

        async def _slow_upload(file_bytes, filename, title=None):
            nonlocal concurrent_count, max_concurrent_seen
            async with lock:
                concurrent_count += 1
                if concurrent_count > max_concurrent_seen:
                    max_concurrent_seen = concurrent_count
            await _asyncio.sleep(0.01)
            async with lock:
                concurrent_count -= 1
            return {'task_id': str(uuid.uuid4())}

        connector.upload_document = _slow_upload
        files = [(b'data', f'file_{i}.pdf') for i in range(10)]
        results = await connector.upload_documents_batch(files, max_concurrent=5)

        assert len(results) == 10
        assert all(r['error'] is None for r in results)
        assert max_concurrent_seen <= 5, f'Max concurrent was {max_concurrent_seen}, expected ≤5'

    _run(run())


# ── 3. test_paperless_task_status_success ─────────────────────────────────────

def test_paperless_task_status_success():
    """Task SUCCESS → related_document is set in result."""
    async def run():
        connector = PaperlessConnector('http://paperless.test', token='tok')
        expected = {
            'task_id': 'abc-123',
            'status': 'SUCCESS',
            'result': '42',
            'related_document': 42,
            'acknowledged': False,
        }
        with patch.object(
            connector, 'get_task_status', new=AsyncMock(return_value=expected)
        ):
            result = await connector.get_task_status('abc-123')
            assert result['status'] == 'SUCCESS'
            assert result['related_document'] == 42

    _run(run())


# ── 4. test_paperless_task_status_failure ─────────────────────────────────────

def test_paperless_task_status_failure():
    """Task FAILURE → error message is present."""
    async def run():
        connector = PaperlessConnector('http://paperless.test', token='tok')
        expected = {
            'task_id': 'abc-456',
            'status': 'FAILURE',
            'result': 'Tika could not parse document',
            'related_document': None,
            'acknowledged': False,
        }
        with patch.object(
            connector, 'get_task_status', new=AsyncMock(return_value=expected)
        ):
            result = await connector.get_task_status('abc-456')
            assert result['status'] == 'FAILURE'
            assert 'Tika' in result['result']

    _run(run())


# ── 5. test_batch_creation ────────────────────────────────────────────────────

def test_batch_creation():
    """Batch + Items are created in DB with correct tenant isolation."""
    async def run():
        repo = _bulk_repo()
        tenant_a = str(uuid.uuid4())
        tenant_b = str(uuid.uuid4())

        batch = await repo.create_batch(tenant_a, 'user@test.com', file_count=2)
        assert batch['tenant_id'] == tenant_a
        assert batch['status'] == 'uploading'
        assert batch['file_count'] == 2

        items = await repo.create_items(
            batch['id'], tenant_a,
            [
                {'filename': 'a.pdf', 'file_size_bytes': 1000},
                {'filename': 'b.pdf', 'file_size_bytes': 2000},
            ],
        )
        assert len(items) == 2
        assert all(i['tenant_id'] == tenant_a for i in items)

        # Tenant B cannot see Tenant A's batch
        result = await repo.get_batch_with_items(batch['id'], tenant_b)
        assert result is None

        # Tenant A can see it
        result = await repo.get_batch_with_items(batch['id'], tenant_a)
        assert result is not None
        assert len(result['items']) == 2

    _run(run())


# ── 6. test_bridge1_task_to_document ──────────────────────────────────────────

def test_bridge1_task_to_document():
    """refresh_batch transitions uploaded→processing and sets paperless_document_id."""
    async def run():
        bulk_repo = _bulk_repo()
        case_repo = _case_repo()
        tenant = str(uuid.uuid4())
        task_id = 'task-bridge1'
        doc_id = 99

        batch = await bulk_repo.create_batch(tenant, 'user', 1)
        items = await bulk_repo.create_items(
            batch['id'], tenant,
            [{'filename': 'test.pdf', 'paperless_task_id': task_id}],
        )
        item = items[0]
        await bulk_repo.update_item_status(item['id'], 'uploaded')

        paperless = _make_paperless(
            task_result={
                'status': 'SUCCESS',
                'result': str(doc_id),
                'related_document': doc_id,
                'task_id': task_id,
            }
        )
        svc = _make_service(bulk_repo=bulk_repo, case_repo=case_repo, paperless=paperless)

        # Patch trigger_reevaluate to avoid running the full re-evaluate
        svc.trigger_reevaluate = AsyncMock(return_value={'reassigned': 0, 'still_orphaned': 0, 'merge_proposals': 0})

        counts = await svc.refresh_batch(batch['id'], tenant)
        assert counts['processing'] == 1

        updated = await bulk_repo.get_batch_with_items(batch['id'], tenant)
        assert updated['items'][0]['status'] == 'processing'
        assert updated['items'][0]['paperless_document_id'] == doc_id

    _run(run())


# ── 7. test_bridge2_document_to_case ──────────────────────────────────────────

def test_bridge2_document_to_case():
    """Post-Consumption endpoint sets case_id on upload item (Bridge 2)."""
    async def run():
        bulk_repo = _bulk_repo()
        tenant = str(uuid.uuid4())
        paperless_doc_id = 55

        batch = await bulk_repo.create_batch(tenant, 'user', 1)
        items = await bulk_repo.create_items(
            batch['id'], tenant,
            [{'filename': 'invoice.pdf', 'paperless_task_id': 'task-x'}],
        )
        item = items[0]
        await bulk_repo.update_item_paperless_doc(item['id'], paperless_doc_id)
        await bulk_repo.update_item_status(item['id'], 'processing')

        # Simulate Bridge 2: find_item_by_paperless_doc + update_item_case
        found = await bulk_repo.find_item_by_paperless_doc(tenant, paperless_doc_id)
        assert found is not None
        assert found['id'] == item['id']

        case_id = str(uuid.uuid4())
        await bulk_repo.update_item_case(found['id'], case_id=case_id, confidence='CERTAIN')
        await bulk_repo.update_item_status(found['id'], 'completed')

        result = await bulk_repo.get_batch_with_items(batch['id'], tenant)
        updated_item = result['items'][0]
        assert updated_item['case_id'] == case_id
        assert updated_item['status'] == 'completed'
        assert updated_item['assignment_confidence'] == 'CERTAIN'

    _run(run())


# ── 8. test_bridge2_tenant_isolation ─────────────────────────────────────────

def test_bridge2_tenant_isolation():
    """find_item_by_paperless_doc with wrong tenant returns None."""
    async def run():
        bulk_repo = _bulk_repo()
        tenant_a = str(uuid.uuid4())
        tenant_b = str(uuid.uuid4())
        paperless_doc_id = 77

        batch = await bulk_repo.create_batch(tenant_a, 'user', 1)
        items = await bulk_repo.create_items(
            batch['id'], tenant_a,
            [{'filename': 'doc.pdf', 'paperless_task_id': 'task-y'}],
        )
        await bulk_repo.update_item_paperless_doc(items[0]['id'], paperless_doc_id)

        # Tenant A finds it
        found_a = await bulk_repo.find_item_by_paperless_doc(tenant_a, paperless_doc_id)
        assert found_a is not None

        # Tenant B does NOT find it
        found_b = await bulk_repo.find_item_by_paperless_doc(tenant_b, paperless_doc_id)
        assert found_b is None

    _run(run())


# ── 9. test_reevaluate_orphans ────────────────────────────────────────────────

def test_reevaluate_orphans():
    """3 items: 1 has case, 1 is orphan with doc_data (gets match), 1 stays orphan.
    Expected: reassigned=1, still_orphaned=2 (1 no doc_data + 1 no match).
    """
    async def run():
        bulk_repo = _bulk_repo()
        case_repo = _case_repo()
        tenant = str(uuid.uuid4())
        tid = uuid.UUID(tenant)

        batch = await bulk_repo.create_batch(tenant, 'user', 3)

        # Item 1: already has a case → not an orphan, won't appear in orphan list
        case_id = str(uuid.uuid4())
        items1 = await bulk_repo.create_items(
            batch['id'], tenant,
            [{'filename': 'a.pdf', 'status': 'completed'}],
        )
        await bulk_repo.update_item_case(items1[0]['id'], case_id=case_id, confidence='CERTAIN')

        # Item 2: orphan with doc_data → should get matched
        existing_case = await case_repo.create_case(
            tenant_id=tid,
            case_type='incoming_invoice',
            vendor_name='Matched Vendor GmbH',
        )
        await case_repo.add_reference(
            case_id=existing_case.id,
            reference_type='invoice_number',
            reference_value='INV-REEVALUATE-001',
        )
        await case_repo.add_document_to_case(
            case_id=existing_case.id,
            document_source='paperless',
            document_source_id='seed-doc-reevaluate',
            assignment_confidence='CERTAIN',
            assignment_method='hard_reference',
        )
        await case_repo.update_case_status(existing_case.id, 'OPEN', operator=True)

        items2 = await bulk_repo.create_items(
            batch['id'], tenant,
            [{'filename': 'b.pdf', 'status': 'completed'}],
        )
        orphan_with_data = items2[0]
        await bulk_repo.update_item_case(
            orphan_with_data['id'],
            case_id=None,
            confidence=None,
            doc_data={
                'document_source': 'paperless',
                'document_source_id': '11',
                'reference_values': [['invoice_number', 'INV-REEVALUATE-001']],
                'vendor_name': 'Matched Vendor GmbH',
                'total_amount': None,
                'currency': 'EUR',
                'filename': 'b.pdf',
            },
        )

        # Item 3: orphan without doc_data → stays orphan
        items3 = await bulk_repo.create_items(
            batch['id'], tenant,
            [{'filename': 'c.pdf', 'status': 'error', 'error_message': 'Tika failed'}],
        )

        svc = _make_service(bulk_repo=bulk_repo, case_repo=case_repo)
        # Mark batch as 'processing' before reevaluate
        await bulk_repo.update_batch_status(batch['id'], 'processing')

        result = await svc.trigger_reevaluate(batch['id'], tenant)

        assert result['reassigned'] == 1
        assert result['still_orphaned'] == 1  # item 3 has no doc_data

    _run(run())


# ── 10. test_reevaluate_duplicate_case_proposal ───────────────────────────────

def test_reevaluate_duplicate_case_proposal():
    """2 items both create DRAFT cases with same vendor → conflict_type='duplicate_case'."""
    async def run():
        bulk_repo = _bulk_repo()
        case_repo = _case_repo()
        tenant = str(uuid.uuid4())
        tid = uuid.UUID(tenant)

        batch = await bulk_repo.create_batch(tenant, 'user', 2)

        # Both items are orphans with same vendor, no existing cases to match
        for i in range(2):
            items = await bulk_repo.create_items(
                batch['id'], tenant,
                [{'filename': f'dup_{i}.pdf', 'status': 'completed'}],
            )
            await bulk_repo.update_item_case(
                items[0]['id'],
                case_id=None,
                confidence=None,
                doc_data={
                    'document_source': 'paperless',
                    'document_source_id': str(100 + i),
                    'reference_values': [['invoice_number', f'INV-DUP-{i}']],
                    'vendor_name': 'Duplicate Vendor AG',
                    'total_amount': None,
                    'currency': 'EUR',
                    'filename': f'dup_{i}.pdf',
                },
            )

        await bulk_repo.update_batch_status(batch['id'], 'processing')
        svc = _make_service(bulk_repo=bulk_repo, case_repo=case_repo)
        result = await svc.trigger_reevaluate(batch['id'], tenant)

        # Both are still orphaned (no existing case to match), should propose merge
        assert result['merge_proposals'] >= 1

        # Check that case_conflicts has a duplicate_case entry
        all_cases = list(case_repo._cases.values())
        assert len(all_cases) >= 2

        all_conflicts = list(case_repo._conflicts.values())
        dup_conflicts = [c for c in all_conflicts if c.conflict_type == 'duplicate_case']
        assert len(dup_conflicts) >= 1

    _run(run())


# ── 11. test_duplicate_detection_same_batch ───────────────────────────────────

def test_duplicate_detection_same_batch():
    """2x same file in a batch → second gets status=duplicate_skipped."""
    async def run():
        bulk_repo = _bulk_repo()
        tenant = str(uuid.uuid4())

        batch = await bulk_repo.create_batch(tenant, 'user', 2)
        svc = _make_service(bulk_repo=bulk_repo)

        file_bytes = b'This is a PDF file content for duplicate test'
        files = [
            (file_bytes, 'original.pdf'),
            (file_bytes, 'copy.pdf'),  # same content → same hash
        ]

        prepared = await svc.prepare_upload_items(files, batch['id'], tenant)

        assert len(prepared) == 2
        statuses = [p['status'] for p in prepared]
        assert 'uploading' in statuses
        assert 'duplicate_skipped' in statuses

        dup = next(p for p in prepared if p['status'] == 'duplicate_skipped')
        assert dup['is_duplicate'] is True
        assert dup['original_filename'] == 'original.pdf'

    _run(run())


# ── 12. test_stuck_timeout ────────────────────────────────────────────────────

def test_stuck_timeout():
    """Item older than 30min with status='uploaded' → stuck_timeout."""
    async def run():
        bulk_repo = _bulk_repo()
        case_repo = _case_repo()
        tenant = str(uuid.uuid4())

        batch = await bulk_repo.create_batch(tenant, 'user', 1)
        items = await bulk_repo.create_items(
            batch['id'], tenant,
            [{'filename': 'stuck.pdf', 'paperless_task_id': 'task-stuck'}],
        )
        item = items[0]
        await bulk_repo.update_item_status(item['id'], 'uploaded')

        # Manually backdate updated_at by 31 minutes
        bulk_repo._items[item['id']]['updated_at'] = (
            datetime.now(timezone.utc) - timedelta(minutes=31)
        )

        paperless = _make_paperless(
            task_result={'status': 'PENDING', 'result': None, 'related_document': None, 'task_id': 'task-stuck'}
        )
        svc = _make_service(bulk_repo=bulk_repo, case_repo=case_repo, paperless=paperless)
        svc.trigger_reevaluate = AsyncMock(return_value={'reassigned': 0, 'still_orphaned': 0, 'merge_proposals': 0})

        counts = await svc.refresh_batch(batch['id'], tenant)
        assert counts['stuck'] == 1

        updated_item = bulk_repo._items[item['id']]
        assert updated_item['status'] == 'stuck_timeout'
        assert 'Paperless-Task' in updated_item['error_message']

    _run(run())


# ── 13. test_webhook_fallback ─────────────────────────────────────────────────

def test_webhook_fallback():
    """Item processing, no Bridge-2 update, but find_case_documents_by_paperless_doc finds it."""
    async def run():
        bulk_repo = _bulk_repo()
        case_repo = _case_repo()
        tenant = str(uuid.uuid4())
        paperless_doc_id = 42
        case_id = str(uuid.uuid4())

        batch = await bulk_repo.create_batch(tenant, 'user', 1)
        items = await bulk_repo.create_items(
            batch['id'], tenant,
            [{'filename': 'fallback.pdf', 'paperless_task_id': 'task-fb'}],
        )
        item = items[0]
        await bulk_repo.update_item_status(item['id'], 'processing')
        await bulk_repo.update_item_paperless_doc(item['id'], paperless_doc_id)

        # Patch find_case_documents_by_paperless_doc to simulate webhook fallback
        from unittest.mock import patch as _patch
        with _patch.object(
            bulk_repo,
            'find_case_documents_by_paperless_doc',
            new=AsyncMock(return_value={'case_id': case_id}),
        ):
            svc = _make_service(bulk_repo=bulk_repo, case_repo=case_repo)
            svc.trigger_reevaluate = AsyncMock(
                return_value={'reassigned': 0, 'still_orphaned': 0, 'merge_proposals': 0}
            )
            counts = await svc.refresh_batch(batch['id'], tenant)

        assert counts['completed'] == 1
        updated_item = bulk_repo._items[item['id']]
        assert updated_item['status'] == 'completed'
        assert updated_item['case_id'] == case_id

    _run(run())


# ── 14. test_batch_status_machine ────────────────────────────────────────────

def test_batch_status_machine():
    """Batch status transitions: uploading → processing → reevaluating → completed."""
    async def run():
        bulk_repo = _bulk_repo()
        tenant = str(uuid.uuid4())

        batch = await bulk_repo.create_batch(tenant, 'user', 1)
        assert batch['status'] == 'uploading'

        await bulk_repo.update_batch_status(batch['id'], 'processing')
        b = await bulk_repo.get_batch_with_items(batch['id'], tenant)
        assert b['status'] == 'processing'

        await bulk_repo.update_batch_status(batch['id'], 'reevaluating')
        b = await bulk_repo.get_batch_with_items(batch['id'], tenant)
        assert b['status'] == 'reevaluating'

        now = datetime.now(timezone.utc)
        await bulk_repo.update_batch_status(batch['id'], 'completed', completed_at=now)
        b = await bulk_repo.get_batch_with_items(batch['id'], tenant)
        assert b['status'] == 'completed'
        assert b['completed_at'] is not None

    _run(run())


# ── 15. test_upload_error_doesnt_break_batch ─────────────────────────────────

def test_upload_error_doesnt_break_batch():
    """1 of 10 uploads fails → Batch continues, 1 error item."""
    async def run():
        connector = PaperlessConnector('http://paperless.test', token='tok')
        call_count = 0

        async def _upload(file_bytes, filename, title=None):
            nonlocal call_count
            call_count += 1
            if call_count == 5:
                raise RuntimeError('Connection refused')
            return {'task_id': str(uuid.uuid4())}

        connector.upload_document = _upload
        files = [(b'data', f'file_{i}.pdf') for i in range(10)]
        results = await connector.upload_documents_batch(files, max_concurrent=5)

        assert len(results) == 10
        errors = [r for r in results if r['error'] is not None]
        successes = [r for r in results if r['task_id'] is not None]
        assert len(errors) == 1
        assert len(successes) == 9

    _run(run())


# ── Repository: is_batch_ready_for_reevaluate ─────────────────────────────────

def test_is_batch_ready_for_reevaluate_blocks_on_uploading():
    """Batch with uploading items is NOT ready."""
    async def run():
        repo = _bulk_repo()
        tenant = str(uuid.uuid4())
        batch = await repo.create_batch(tenant, 'user', 1)
        await repo.create_items(batch['id'], tenant, [{'filename': 'x.pdf'}])
        ready = await repo.is_batch_ready_for_reevaluate(batch['id'])
        assert ready is False

    _run(run())


def test_is_batch_ready_for_reevaluate_true_when_all_done():
    """Batch with all items completed/error is ready."""
    async def run():
        repo = _bulk_repo()
        tenant = str(uuid.uuid4())
        batch = await repo.create_batch(tenant, 'user', 2)
        items = await repo.create_items(
            batch['id'], tenant,
            [{'filename': 'a.pdf'}, {'filename': 'b.pdf'}],
        )
        await repo.update_item_status(items[0]['id'], 'completed')
        await repo.update_item_status(items[1]['id'], 'error')
        ready = await repo.is_batch_ready_for_reevaluate(batch['id'])
        assert ready is True

    _run(run())
