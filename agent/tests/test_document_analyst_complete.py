"""Paket 56 — Document Analyst complete paths.

Tests for:
1. OCR-Recheck-Pfad (REVIEW_STILL_OPEN + OUTPUT_INCOMPLETE → recheck → COMPLETED / FAILED)
2. Deep-Path (REVIEW_COMPLETED → propose booking if INVOICE with fields, else note)
3. Auto-Merge (confidence >= 0.85 → MERGE_CANDIDATE_FOUND; < 0.85 → no candidate)
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from app.audit.models import AuditRecord
from app.audit.repository import AuditRepository
from app.audit.service import AuditService
from app.open_items.repository import OpenItemsRepository
from app.open_items.service import OpenItemsService
from app.telegram.document_analyst_deep_path_service import TelegramDocumentAnalystDeepPathService
from app.telegram.document_analyst_merge_service import TelegramDocumentAnalystMergeService
from app.telegram.document_analyst_ocr_recheck_service import TelegramDocumentAnalystOcrRecheckService
from app.telegram.models import (
    TelegramDocumentAnalystOcrRecheckRecord,
    TelegramDocumentAnalystReviewRecord,
    TelegramDocumentAnalystStartRecord,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _audit_service() -> AuditService:
    repo = AuditRepository('memory://db')
    return AuditService(repo)


def _open_items_service(audit_svc: AuditService | None = None) -> OpenItemsService:
    repo = OpenItemsRepository('memory://db')
    return OpenItemsService(repo, 'memory://redis')


def _review_record(
    *,
    review_status: str = 'DOCUMENT_ANALYST_REVIEW_STILL_OPEN',
    review_outcome: str = 'OUTPUT_INCOMPLETE',
    runtime_case_id: str = 'case-rt-1',
    source_case_id: str = 'case-src-1',
    target_case_id: str = 'case-src-1',
    telegram_document_ref: str = 'doc-ref-1',
    runtime_open_item_id: str | None = None,
) -> TelegramDocumentAnalystReviewRecord:
    return TelegramDocumentAnalystReviewRecord(
        review_ref='review-ref-1',
        document_analyst_start_ref='start-ref-1',
        document_analyst_context_ref='ctx-ref-1',
        source_case_id=source_case_id,
        target_case_id=target_case_id,
        telegram_document_ref=telegram_document_ref,
        telegram_media_ref='media-ref-1',
        runtime_case_id=runtime_case_id,
        runtime_output_status='INCOMPLETE',
        runtime_open_item_id=runtime_open_item_id,
        review_status=review_status,
        review_outcome=review_outcome,
    )


def _start_record(
    *,
    source_case_id: str = 'case-src-1',
    target_case_id: str = 'case-src-1',
    telegram_document_ref: str = 'doc-ref-1',
    runtime_output_status: str | None = 'INCOMPLETE',
) -> TelegramDocumentAnalystStartRecord:
    return TelegramDocumentAnalystStartRecord(
        start_ref='start-ref-1',
        document_analyst_context_ref='ctx-ref-1',
        source_case_id=source_case_id,
        target_case_id=target_case_id,
        telegram_document_ref=telegram_document_ref,
        telegram_media_ref='media-ref-1',
        media_domain='DOCUMENT',
        analysis_start_status='DOCUMENT_ANALYST_RUNTIME_STARTED',
        analysis_start_confidence='MEDIUM',
        runtime_output_status=runtime_output_status,
    )


async def _seed_review(audit: AuditService, review: TelegramDocumentAnalystReviewRecord) -> None:
    await audit.log_event({
        'event_id': str(uuid.uuid4()),
        'case_id': review.source_case_id,
        'source': 'telegram',
        'agent_name': 'document-analyst',
        'approval_status': 'NOT_REQUIRED',
        'action': review.review_status,
        'result': review.review_ref,
        'llm_output': review.model_dump(mode='json'),
    })


async def _seed_start(audit: AuditService, start: TelegramDocumentAnalystStartRecord) -> None:
    await audit.log_event({
        'event_id': str(uuid.uuid4()),
        'case_id': start.source_case_id,
        'source': 'telegram',
        'agent_name': 'document-analyst',
        'approval_status': 'NOT_REQUIRED',
        'action': start.analysis_start_status,
        'result': start.start_ref,
        'llm_output': start.model_dump(mode='json'),
    })


class _FakeGraph:
    def __init__(self, output_status: str = 'COMPLETE', open_item_id: str | None = None):
        self.calls: list[dict] = []
        self.output_status = output_status
        self.open_item_id = open_item_id

    async def ainvoke(self, state: dict) -> dict:
        self.calls.append(state)
        return {
            'output': {'status': self.output_status, 'open_item_id': self.open_item_id},
            'document_analysis': None,
        }


class _FailingGraph:
    async def ainvoke(self, state: dict) -> dict:
        raise RuntimeError('Graph kaputt')


# ===========================================================================
# OCR-RECHECK TESTS
# ===========================================================================

def test_ocr_recheck_success_calls_graph_with_force_ocr():
    """Successful recheck: graph called with force_ocr=True, status=COMPLETED."""
    audit = _audit_service()
    items = _open_items_service()
    svc = TelegramDocumentAnalystOcrRecheckService(audit, items)
    review = _review_record()
    graph = _FakeGraph(output_status='COMPLETE')

    async def run():
        await _seed_review(audit, review)
        result = await svc.request_recheck(
            review.source_case_id,
            actor='operator',
            note=None,
            graph=graph,
        )
        return result

    result = asyncio.run(run())
    assert result.ocr_recheck_status == 'DOCUMENT_ANALYST_OCR_RECHECK_COMPLETED'
    assert result.recheck_output_status == 'COMPLETE'
    assert graph.calls, 'Graph wurde nicht aufgerufen'
    assert graph.calls[0]['paperless_metadata']['force_ocr'] is True
    assert graph.calls[0]['force_ocr'] is True
    assert graph.calls[0]['source'] == 'document_analyst_ocr_recheck'


def test_ocr_recheck_incomplete_result_creates_failed_state_and_open_item():
    """If recheck still returns INCOMPLETE: status=FAILED, open item created."""
    audit = _audit_service()
    items = _open_items_service()
    svc = TelegramDocumentAnalystOcrRecheckService(audit, items)
    review = _review_record()
    graph = _FakeGraph(output_status='INCOMPLETE')

    async def run():
        await _seed_review(audit, review)
        result = await svc.request_recheck(
            review.source_case_id,
            actor='operator',
            note='Zweiter Versuch',
            graph=graph,
        )
        all_items = await items.list_by_case(review.source_case_id)
        return result, all_items

    result, all_items = asyncio.run(run())
    assert result.ocr_recheck_status == 'DOCUMENT_ANALYST_OCR_RECHECK_FAILED'
    assert result.recheck_output_status == 'INCOMPLETE'
    assert result.recheck_open_item_id is not None
    manual_item = next(
        (i for i in all_items if 'Manuelle Nachbearbeitung' in (i.title or '')),
        None,
    )
    assert manual_item is not None, 'Kein Open Item fuer manuelle Nachbearbeitung erstellt'


def test_ocr_recheck_doppelstart_blocked():
    """Second OCR-Recheck request while first is REQUESTED/RUNNING raises ValueError (→ 409)."""
    audit = _audit_service()
    items = _open_items_service()
    svc = TelegramDocumentAnalystOcrRecheckService(audit, items)
    review = _review_record()

    # Use a graph that never completes (simulates RUNNING state by checking between calls)
    # We just seed a REQUESTED record manually to simulate the guard
    recheck_record = TelegramDocumentAnalystOcrRecheckRecord(
        ocr_recheck_ref='doc-ocr-recheck:test001',
        review_ref=review.review_ref,
        source_case_id=review.source_case_id,
        target_case_id=review.target_case_id,
        telegram_document_ref=review.telegram_document_ref,
        ocr_recheck_status='DOCUMENT_ANALYST_OCR_RECHECK_REQUESTED',
        force_ocr=True,
        actor='operator',
    )

    async def run():
        await _seed_review(audit, review)
        # Seed an already-REQUESTED recheck
        await audit.log_event({
            'event_id': str(uuid.uuid4()),
            'case_id': review.source_case_id,
            'source': 'telegram',
            'agent_name': 'document-analyst',
            'approval_status': 'NOT_REQUIRED',
            'action': 'DOCUMENT_ANALYST_OCR_RECHECK_REQUESTED',
            'result': recheck_record.ocr_recheck_ref,
            'llm_output': recheck_record.model_dump(mode='json'),
        })
        # Second request should be blocked
        with pytest.raises(ValueError, match='bereits ausgeloest'):
            await svc.request_recheck(
                review.source_case_id,
                actor='operator',
                note=None,
                graph=_FakeGraph(),
            )

    asyncio.run(run())


def test_ocr_recheck_guard_rejects_wrong_review_outcome():
    """OCR-Recheck is only allowed for OUTPUT_INCOMPLETE, not OUTPUT_NEEDS_MANUAL_FOLLOWUP."""
    audit = _audit_service()
    items = _open_items_service()
    svc = TelegramDocumentAnalystOcrRecheckService(audit, items)
    review = _review_record(review_outcome='OUTPUT_NEEDS_MANUAL_FOLLOWUP')

    async def run():
        await _seed_review(audit, review)
        with pytest.raises(ValueError, match='OUTPUT_INCOMPLETE'):
            await svc.request_recheck(
                review.source_case_id,
                actor='operator',
                note=None,
                graph=_FakeGraph(),
            )

    asyncio.run(run())


def test_ocr_recheck_graph_exception_logs_failed():
    """If graph raises, OCR-Recheck logs FAILED state."""
    audit = _audit_service()
    items = _open_items_service()
    svc = TelegramDocumentAnalystOcrRecheckService(audit, items)
    review = _review_record()

    async def run():
        await _seed_review(audit, review)
        with pytest.raises(ValueError, match='Graph kaputt'):
            await svc.request_recheck(
                review.source_case_id,
                actor='operator',
                note=None,
                graph=_FailingGraph(),
            )
        # Verify FAILED was logged
        chronology = await audit.by_case(review.source_case_id, limit=100)
        actions = [e.action for e in chronology]
        assert 'DOCUMENT_ANALYST_OCR_RECHECK_FAILED' in actions

    asyncio.run(run())


# ===========================================================================
# DEEP-PATH TESTS
# ===========================================================================

def test_deep_path_invoice_with_full_fields_creates_booking_proposal():
    """INVOICE + sender + amount → TRIGGERED → open item 'Buchungsvorschlag pruefen'."""
    audit = _audit_service()
    items = _open_items_service()
    svc = TelegramDocumentAnalystDeepPathService(audit, items)
    review = _review_record(
        review_status='DOCUMENT_ANALYST_REVIEW_COMPLETED',
        review_outcome='OUTPUT_ACCEPTED',
    )
    analysis = {
        'document_type': {'value': 'INVOICE', 'status': 'FOUND', 'confidence': 0.95},
        'sender': {'value': 'Lieferant GmbH', 'status': 'FOUND', 'confidence': 0.9},
        'amounts': [{'label': 'total', 'amount': '1234.56', 'currency': 'EUR', 'status': 'FOUND', 'confidence': 0.9}],
        'currency': {'value': 'EUR', 'status': 'FOUND', 'confidence': 0.9},
    }

    async def run():
        result = await svc.process_after_review(review, document_analysis_payload=analysis)
        all_items = await items.list_by_case(review.source_case_id)
        return result, all_items

    result, all_items = asyncio.run(run())
    assert result.deep_path_status == 'DOCUMENT_ANALYST_DEEP_PATH_COMPLETED'
    assert result.propose_only is True
    assert result.booking_proposal is not None
    assert result.booking_proposal['propose_only'] is True
    assert result.booking_proposal['sender'] == 'Lieferant GmbH'
    assert result.booking_proposal['amount'] == '1234.56'
    assert result.booking_open_item_id is not None
    booking_item = next(
        (i for i in all_items if i.item_id == result.booking_open_item_id),
        None,
    )
    assert booking_item is not None
    assert 'Buchungsvorschlag' in booking_item.title


def test_deep_path_no_auto_booking_without_invoice_type():
    """Non-INVOICE document type → no booking proposal, clean completion."""
    audit = _audit_service()
    items = _open_items_service()
    svc = TelegramDocumentAnalystDeepPathService(audit, items)
    review = _review_record(
        review_status='DOCUMENT_ANALYST_REVIEW_COMPLETED',
        review_outcome='OUTPUT_ACCEPTED',
    )
    analysis = {
        'document_type': {'value': 'LETTER', 'status': 'FOUND', 'confidence': 0.9},
        'sender': {'value': 'Absender AG', 'status': 'FOUND', 'confidence': 0.9},
        'amounts': [],
    }

    async def run():
        result = await svc.process_after_review(review, document_analysis_payload=analysis)
        all_items = await items.list_by_case(review.source_case_id)
        return result, all_items

    result, all_items = asyncio.run(run())
    assert result.deep_path_status == 'DOCUMENT_ANALYST_DEEP_PATH_COMPLETED'
    assert result.booking_proposal is None
    assert result.booking_open_item_id is None
    assert result.note is not None and 'Kein Auto-Vorschlag' in result.note
    booking_items = [i for i in all_items if 'Buchungsvorschlag' in (i.title or '')]
    assert not booking_items, 'Kein Buchungsvorschlag erlaubt ohne INVOICE-Typ'


def test_deep_path_no_proposal_when_sender_missing():
    """INVOICE but no sender → no proposal."""
    audit = _audit_service()
    items = _open_items_service()
    svc = TelegramDocumentAnalystDeepPathService(audit, items)
    review = _review_record(
        review_status='DOCUMENT_ANALYST_REVIEW_COMPLETED',
        review_outcome='OUTPUT_ACCEPTED',
    )
    analysis = {
        'document_type': {'value': 'INVOICE', 'status': 'FOUND', 'confidence': 0.9},
        'sender': {'value': None, 'status': 'MISSING', 'confidence': 0.0},
        'amounts': [{'label': 'total', 'amount': '500.00', 'currency': 'EUR', 'status': 'FOUND', 'confidence': 0.9}],
    }

    async def run():
        return await svc.process_after_review(review, document_analysis_payload=analysis)

    result = asyncio.run(run())
    assert result.deep_path_status == 'DOCUMENT_ANALYST_DEEP_PATH_COMPLETED'
    assert result.booking_proposal is None


def test_deep_path_logs_ready_triggered_completed_states():
    """Three audit events logged: READY → TRIGGERED → COMPLETED."""
    audit = _audit_service()
    items = _open_items_service()
    svc = TelegramDocumentAnalystDeepPathService(audit, items)
    review = _review_record(
        review_status='DOCUMENT_ANALYST_REVIEW_COMPLETED',
        review_outcome='OUTPUT_ACCEPTED',
    )
    analysis = {
        'document_type': {'value': 'INVOICE', 'status': 'FOUND', 'confidence': 0.95},
        'sender': {'value': 'Firma X', 'status': 'FOUND', 'confidence': 0.9},
        'amounts': [{'label': 'total', 'amount': '999.00', 'currency': 'EUR', 'status': 'FOUND', 'confidence': 0.9}],
    }

    async def run():
        await svc.process_after_review(review, document_analysis_payload=analysis)
        return await audit.by_case(review.source_case_id, limit=100)

    chronology = asyncio.run(run())
    actions = [e.action for e in chronology]
    assert 'DOCUMENT_ANALYST_DEEP_PATH_READY' in actions
    assert 'DOCUMENT_ANALYST_DEEP_PATH_TRIGGERED' in actions
    assert 'DOCUMENT_ANALYST_DEEP_PATH_COMPLETED' in actions


# ===========================================================================
# AUTO-MERGE TESTS
# ===========================================================================

async def _seed_analysis_in_case(
    audit: AuditService,
    case_id: str,
    sender: str,
    amount: str,
    doc_ref: str,
) -> None:
    analysis_payload = {
        'case_id': case_id,
        'document_ref': doc_ref,
        'sender': {'value': sender, 'status': 'FOUND', 'confidence': 0.9},
        'amounts': [{'label': 'total', 'amount': amount, 'currency': 'EUR', 'status': 'FOUND', 'confidence': 0.9}],
        'global_decision': 'ANALYZED',
    }
    await audit.log_event({
        'event_id': str(uuid.uuid4()),
        'case_id': case_id,
        'source': 'agent',
        'agent_name': 'document-analyst',
        'approval_status': 'NOT_REQUIRED',
        'action': 'DOCUMENT_ANALYSIS_COMPLETED',
        'result': 'analyzed',
        'llm_output': analysis_payload,
    })


def test_merge_high_confidence_creates_candidate():
    """Sender + amount match → confidence >= 0.85 → MERGE_CANDIDATE_FOUND, no auto-merge."""
    audit = _audit_service()
    svc = TelegramDocumentAnalystMergeService(audit)

    CASE_A = 'case-merge-a'
    CASE_B = 'case-merge-b'
    SENDER = 'Lieferant GmbH'
    AMOUNT = '1500.00'

    start = _start_record(source_case_id=CASE_A, target_case_id=CASE_A)
    analysis_a = {
        'document_type': {'value': 'INVOICE', 'status': 'FOUND', 'confidence': 0.9},
        'sender': {'value': SENDER, 'status': 'FOUND', 'confidence': 0.9},
        'amounts': [{'label': 'total', 'amount': AMOUNT, 'currency': 'EUR', 'status': 'FOUND', 'confidence': 0.9}],
    }

    async def run():
        await _seed_analysis_in_case(audit, CASE_B, SENDER, AMOUNT, 'doc-b')
        result = await svc.search_merge_candidate(start, document_analysis_payload=analysis_a)
        return result

    result = asyncio.run(run())
    assert result is not None
    assert result.merge_status == 'DOCUMENT_ANALYST_MERGE_CANDIDATE_FOUND'
    assert result.candidate_case_id == CASE_B
    assert result.confidence_score >= 0.85
    # No auto-merge: operator must confirm
    assert 'MERGE_CONFIRMED' not in result.merge_status


def test_merge_low_confidence_no_candidate():
    """Only document ref similarity (0.15) → below threshold → no candidate."""
    audit = _audit_service()
    svc = TelegramDocumentAnalystMergeService(audit)

    CASE_A = 'case-low-a'
    CASE_B = 'case-low-b'

    start = _start_record(source_case_id=CASE_A, target_case_id=CASE_A, telegram_document_ref='doc-shared')
    analysis_a = {
        'sender': {'value': 'Firma Alpha', 'status': 'FOUND', 'confidence': 0.9},
        'amounts': [{'label': 'total', 'amount': '100.00', 'currency': 'EUR', 'status': 'FOUND', 'confidence': 0.9}],
    }

    async def run():
        # Case B has different sender, different amount, similar doc ref
        await _seed_analysis_in_case(audit, CASE_B, 'Firma Beta', '999.00', 'doc-shared')
        return await svc.search_merge_candidate(start, document_analysis_payload=analysis_a)

    result = asyncio.run(run())
    assert result is None, 'Kein Kandidat bei niedriger Konfidenz erwartet'


def test_merge_confirm_sets_confirmed_status():
    """MERGE_CONFIRMED after MERGE_CANDIDATE_FOUND: status updated, case remains standalone."""
    audit = _audit_service()
    svc = TelegramDocumentAnalystMergeService(audit)

    CASE_A = 'case-conf-a'
    CASE_B = 'case-conf-b'

    async def run():
        # Create a candidate by running high-confidence search
        start = _start_record(source_case_id=CASE_A, target_case_id=CASE_A)
        analysis_a = {
            'sender': {'value': 'Lieferant X', 'status': 'FOUND', 'confidence': 0.9},
            'amounts': [{'label': 'total', 'amount': '750.00', 'currency': 'EUR', 'status': 'FOUND', 'confidence': 0.9}],
        }
        await _seed_analysis_in_case(audit, CASE_B, 'Lieferant X', '750.00', 'doc-x')
        candidate = await svc.search_merge_candidate(start, document_analysis_payload=analysis_a)
        assert candidate is not None

        # Operator confirms
        confirmed = await svc.confirm_merge(CASE_A, actor='admin', note='Verknuepfung bestaetigt')
        return confirmed

    result = asyncio.run(run())
    assert result.merge_status == 'DOCUMENT_ANALYST_MERGE_CONFIRMED'
    assert result.candidate_case_id == CASE_B
    assert result.actor == 'admin'


def test_merge_reject_keeps_case_standalone():
    """MERGE_REJECTED after MERGE_CANDIDATE_FOUND: status REJECTED, no merge."""
    audit = _audit_service()
    svc = TelegramDocumentAnalystMergeService(audit)

    CASE_A = 'case-rej-a'
    CASE_B = 'case-rej-b'

    async def run():
        start = _start_record(source_case_id=CASE_A, target_case_id=CASE_A)
        analysis_a = {
            'sender': {'value': 'Lieferant Y', 'status': 'FOUND', 'confidence': 0.9},
            'amounts': [{'label': 'total', 'amount': '320.00', 'currency': 'EUR', 'status': 'FOUND', 'confidence': 0.9}],
        }
        await _seed_analysis_in_case(audit, CASE_B, 'Lieferant Y', '320.00', 'doc-y')
        candidate = await svc.search_merge_candidate(start, document_analysis_payload=analysis_a)
        assert candidate is not None

        rejected = await svc.reject_merge(CASE_A, actor='admin', note='Nicht dasselbe Dokument')
        return rejected

    result = asyncio.run(run())
    assert result.merge_status == 'DOCUMENT_ANALYST_MERGE_REJECTED'
    assert result.candidate_case_id == CASE_B


def test_merge_no_candidate_without_analysis():
    """No document_analysis_payload → no search, no candidate."""
    audit = _audit_service()
    svc = TelegramDocumentAnalystMergeService(audit)
    start = _start_record()

    async def run():
        return await svc.search_merge_candidate(start, document_analysis_payload=None)

    result = asyncio.run(run())
    assert result is None


def test_merge_no_candidate_without_sender():
    """Analysis without sender → no search."""
    audit = _audit_service()
    svc = TelegramDocumentAnalystMergeService(audit)
    start = _start_record()
    analysis = {
        'sender': {'value': None, 'status': 'MISSING', 'confidence': 0.0},
        'amounts': [{'label': 'total', 'amount': '100.00', 'currency': 'EUR', 'status': 'FOUND', 'confidence': 0.9}],
    }

    async def run():
        return await svc.search_merge_candidate(start, document_analysis_payload=analysis)

    result = asyncio.run(run())
    assert result is None


def test_merge_confirm_requires_candidate_found():
    """confirm_merge raises ValueError if no MERGE_CANDIDATE_FOUND record."""
    audit = _audit_service()
    svc = TelegramDocumentAnalystMergeService(audit)

    async def run():
        with pytest.raises(ValueError, match='Kein Merge-Kandidat'):
            await svc.confirm_merge('case-empty', actor='admin', note=None)

    asyncio.run(run())


def test_merge_reject_requires_candidate_found():
    """reject_merge raises ValueError if no MERGE_CANDIDATE_FOUND record."""
    audit = _audit_service()
    svc = TelegramDocumentAnalystMergeService(audit)

    async def run():
        with pytest.raises(ValueError, match='Kein Merge-Kandidat'):
            await svc.reject_merge('case-empty', actor='admin', note=None)

    asyncio.run(run())


# ===========================================================================
# INSPECT JSON INTEGRATION
# ===========================================================================

def test_inspect_json_includes_new_fields(tmp_path, monkeypatch):
    """Case inspect JSON contains document_analyst_ocr_recheck, deep_path, merge_candidate keys."""
    from tests.test_api_surface import _build_app, _extract_csrf_token, _login_admin
    from tests.test_telegram_clarification_v1 import _configure_env, _telegram_headers
    from tests.test_telegram_media_ingress_v1 import _media_payload
    from fastapi.testclient import TestClient

    _configure_env(monkeypatch, tmp_path)
    monkeypatch.setenv('FRYA_TELEGRAM_BOT_TOKEN', 'telegram-test-token')

    from app.connectors.notifications_telegram import TelegramConnector
    import json as _json

    async def fake_send(self, message, disable_notification=False):
        return {'ok': True, 'status_code': 200, 'body': _json.dumps({'ok': True, 'result': {'message_id': 1}}), 'json': {'ok': True, 'result': {'message_id': 1}}}

    async def fake_get_file_info(self, file_id):
        return {'ok': True, 'status_code': 200, 'body': _json.dumps({'ok': True, 'result': {'file_path': f'documents/{file_id}.pdf'}}), 'json': {'ok': True, 'result': {'file_path': f'documents/{file_id}.pdf'}}, 'reason': None}

    async def fake_download_file(self, file_path):
        return {'ok': True, 'status_code': 200, 'body': None, 'content': b'%PDF-1.4', 'content_type': 'application/pdf', 'reason': None}

    monkeypatch.setattr(TelegramConnector, 'send', fake_send)
    monkeypatch.setattr(TelegramConnector, 'get_file_info', fake_get_file_info)
    monkeypatch.setattr(TelegramConnector, 'download_file', fake_download_file)

    class _FakeCompletedGraph:
        async def ainvoke(self, state):
            return {'output': {'status': 'COMPLETE', 'open_item_id': None}, 'document_analysis': None}

    app = _build_app()
    with TestClient(app) as client:
        client.app.state.graph = _FakeCompletedGraph()
        resp = client.post(
            '/webhooks/telegram',
            json=_media_payload(7001, 701, document={'file_id': 'new-pdf-1', 'file_unique_id': 'new-pdf-uniq-1', 'file_name': 'test.pdf', 'mime_type': 'application/pdf', 'file_size': 256}),
            headers=_telegram_headers(),
        )
        assert resp.status_code == 200
        case_id = resp.json()['case_id']

        _login_admin(client)
        case_json = client.get(f'/inspect/cases/{case_id}/json')
        assert case_json.status_code == 200
        body = case_json.json()

        # All three new keys must exist (value may be None if not triggered)
        assert 'document_analyst_ocr_recheck' in body
        assert 'document_analyst_deep_path' in body
        assert 'document_analyst_merge_candidate' in body
