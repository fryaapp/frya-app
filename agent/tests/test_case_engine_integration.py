"""CaseEngine ← Document Analyst integration tests.

Tests the integrate_document_analysis() bridge function directly (unit-level)
and the finalize_document_review() orchestration hook.

Scenarios:
  1.  Match via reference → document assigned to existing case (CERTAIN)
  2.  No match → DRAFT case created with correct case_type
  3.  No match → DRAFT has document linked
  4.  No match → DRAFT has extracted reference persisted
  5.  Audit event logged: action='document_assigned_to_case'
  6.  Source-channel mapping: telegram/email/paperless_webhook → correct literal
  7.  REMINDER document type → 'dunning' case type
  8.  LETTER → 'correspondence', OTHER → 'other'
  9.  Cross-tenant isolation: reference match only within same tenant
 10.  Match via entity (vendor+amount+date) — Layer 2
 11.  Orchestration hook: finalize_document_review with tenant_id → sets case_engine_result
 12.  Orchestration hook: finalize_document_review without tenant_id → skips silently
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock


def _run(coro):
    return asyncio.run(coro)


def _repo():
    from app.case_engine.repository import CaseRepository
    return CaseRepository('memory://test')


# ── helper ────────────────────────────────────────────────────────────────────

async def _open_case_with_doc(repo, tenant_id, *, vendor_name=None, total_amount=None, due_date=None):
    """Create an OPEN case with ≥1 document so status transition works."""
    case = await repo.create_case(
        tenant_id=tenant_id,
        case_type='incoming_invoice',
        vendor_name=vendor_name,
        total_amount=total_amount,
        due_date=due_date,
    )
    await repo.add_document_to_case(
        case_id=case.id,
        document_source='paperless',
        document_source_id='setup-doc',
        assignment_confidence='CERTAIN',
        assignment_method='hard_reference',
    )
    await repo.update_case_status(case.id, 'OPEN', operator=True)
    return case


from app.case_engine.doc_analyst_integration import integrate_document_analysis


# ── Test 1: Reference match → assigned to existing case ───────────────────────

def test_match_by_reference_assigns_to_existing_case():
    async def run():
        repo = _repo()
        tenant_id = uuid.uuid4()

        case = await _open_case_with_doc(repo, tenant_id)
        await repo.add_reference(
            case_id=case.id,
            reference_type='invoice_number',
            reference_value='INV-2025-001',
        )

        result = await integrate_document_analysis(
            tenant_id=tenant_id,
            event_source='email',
            document_ref='email-msg-1',
            document_type_value='INVOICE',
            vendor_name='ACME GmbH',
            total_amount=Decimal('119.00'),
            currency='EUR',
            document_date=date(2025, 3, 1),
            due_date=date(2025, 3, 31),
            reference_values=['INV-2025-001'],
            filename='rechnung.pdf',
            overall_confidence=0.92,
            orchestration_case_id='doc-orch-1',
            repo=repo,
        )

        assert result['status'] == 'assigned'
        assert result['case_id'] == str(case.id)
        assert result['confidence'] == 'CERTAIN'
        assert result['method'] == 'hard_reference'
        assert result['created_draft'] is False

        # New document was added to the existing case
        docs = await repo.get_case_documents(case.id)
        sources = [d.document_source_id for d in docs]
        assert 'email-msg-1' in sources
    _run(run())


# ── Test 2: No match → DRAFT case created with correct type ───────────────────

def test_no_match_creates_draft_case():
    async def run():
        repo = _repo()
        tenant_id = uuid.uuid4()

        result = await integrate_document_analysis(
            tenant_id=tenant_id,
            event_source='telegram',
            document_ref='tg-msg-42',
            document_type_value='INVOICE',
            vendor_name='Unbekannt GmbH',
            total_amount=Decimal('250.00'),
            currency='EUR',
            document_date=date(2025, 2, 1),
            due_date=None,
            reference_values=[],
            filename=None,
            overall_confidence=0.75,
            orchestration_case_id='tg-orch-1',
            repo=repo,
        )

        assert result['status'] == 'draft_created'
        assert result['created_draft'] is True
        assert result['case_id'] is not None

        new_case = await repo.get_case(uuid.UUID(result['case_id']))
        assert new_case is not None
        assert new_case.status == 'DRAFT'
        assert new_case.case_type == 'incoming_invoice'
        assert new_case.vendor_name == 'Unbekannt GmbH'
        assert new_case.total_amount == Decimal('250.00')
    _run(run())


# ── Test 3: DRAFT case has document linked ────────────────────────────────────

def test_draft_case_has_document_linked():
    async def run():
        repo = _repo()
        tenant_id = uuid.uuid4()

        result = await integrate_document_analysis(
            tenant_id=tenant_id,
            event_source='paperless_webhook',
            document_ref='paperless-77',
            document_type_value='INVOICE',
            vendor_name=None,
            total_amount=None,
            currency=None,
            document_date=None,
            due_date=None,
            reference_values=[],
            filename='beleg.pdf',
            overall_confidence=0.50,
            orchestration_case_id='doc-orch-2',
            repo=repo,
        )

        assert result['created_draft'] is True
        docs = await repo.get_case_documents(uuid.UUID(result['case_id']))
        assert len(docs) == 1
        assert docs[0].document_source == 'paperless'
        assert docs[0].document_source_id == 'paperless-77'
        assert docs[0].filename == 'beleg.pdf'
    _run(run())


# ── Test 4: DRAFT case stores extracted reference ─────────────────────────────

def test_draft_case_stores_reference():
    async def run():
        repo = _repo()
        tenant_id = uuid.uuid4()

        result = await integrate_document_analysis(
            tenant_id=tenant_id,
            event_source='email',
            document_ref='email-88',
            document_type_value='INVOICE',
            vendor_name=None,
            total_amount=None,
            currency=None,
            document_date=None,
            due_date=None,
            reference_values=['INV-REF-999'],
            filename=None,
            overall_confidence=0.60,
            orchestration_case_id='doc-orch-3',
            repo=repo,
        )

        assert result['created_draft'] is True
        refs = await repo.get_case_references(uuid.UUID(result['case_id']))
        assert any(r.reference_value == 'INV-REF-999' for r in refs)
    _run(run())


# ── Test 5: Audit event logged ────────────────────────────────────────────────

def test_audit_event_logged():
    async def run():
        repo = _repo()
        tenant_id = uuid.uuid4()

        audit_svc = MagicMock()
        audit_svc.log_event = AsyncMock()

        await integrate_document_analysis(
            tenant_id=tenant_id,
            event_source='email',
            document_ref='email-99',
            document_type_value='INVOICE',
            vendor_name=None,
            total_amount=None,
            currency=None,
            document_date=None,
            due_date=None,
            reference_values=[],
            filename=None,
            overall_confidence=0.65,
            orchestration_case_id='doc-orch-4',
            repo=repo,
            audit_service=audit_svc,
        )

        audit_svc.log_event.assert_awaited_once()
        call_kwargs = audit_svc.log_event.call_args[0][0]
        assert call_kwargs['action'] == 'document_assigned_to_case'
        assert call_kwargs['agent_name'] == 'case-engine-integration'
        assert 'status=' in call_kwargs['result']
    _run(run())


# ── Test 6: Source-channel mapping ────────────────────────────────────────────

def test_source_channel_mapping():
    from app.case_engine.doc_analyst_integration import _map_source

    assert _map_source('telegram') == 'telegram'
    assert _map_source('telegram_document_analyst_start') == 'telegram'
    assert _map_source('email') == 'email'
    assert _map_source('paperless_webhook') == 'paperless'
    assert _map_source('paperless') == 'paperless'
    assert _map_source('api') == 'manual'
    assert _map_source('unknown_source') == 'manual'


# ── Test 7: REMINDER → dunning case type ──────────────────────────────────────

def test_reminder_creates_dunning_case():
    async def run():
        repo = _repo()
        tenant_id = uuid.uuid4()

        result = await integrate_document_analysis(
            tenant_id=tenant_id,
            event_source='email',
            document_ref='email-200',
            document_type_value='REMINDER',
            vendor_name='Stadtwerke',
            total_amount=Decimal('85.00'),
            currency='EUR',
            document_date=date(2025, 1, 15),
            due_date=date(2025, 2, 1),
            reference_values=['MAH-2025-001'],
            filename=None,
            overall_confidence=0.88,
            orchestration_case_id='doc-orch-5',
            repo=repo,
        )

        case = await repo.get_case(uuid.UUID(result['case_id']))
        assert case is not None
        assert case.case_type == 'dunning'
    _run(run())


# ── Test 8: Document type mapping coverage ────────────────────────────────────

def test_doc_type_mapping():
    from app.case_engine.doc_analyst_integration import _map_case_type

    assert _map_case_type('INVOICE') == 'incoming_invoice'
    assert _map_case_type('REMINDER') == 'dunning'
    assert _map_case_type('LETTER') == 'correspondence'
    assert _map_case_type('OTHER') == 'other'
    assert _map_case_type(None) == 'other'


# ── Test 9: Cross-tenant isolation ────────────────────────────────────────────

def test_cross_tenant_isolation():
    async def run():
        repo = _repo()
        t1 = uuid.uuid4()
        t2 = uuid.uuid4()

        # Case in t1 with a reference
        case_t1 = await _open_case_with_doc(repo, t1)
        await repo.add_reference(
            case_id=case_t1.id,
            reference_type='invoice_number',
            reference_value='INV-SHARED',
        )

        # t2 sends a document with the same reference — must NOT match t1's case
        result = await integrate_document_analysis(
            tenant_id=t2,
            event_source='email',
            document_ref='email-t2',
            document_type_value='INVOICE',
            vendor_name=None,
            total_amount=None,
            currency=None,
            document_date=None,
            due_date=None,
            reference_values=['INV-SHARED'],
            filename=None,
            overall_confidence=0.80,
            orchestration_case_id='doc-t2',
            repo=repo,
        )

        # t2 should get a new DRAFT case, not t1's case
        assert result['status'] == 'draft_created'
        assert result['case_id'] != str(case_t1.id)
    _run(run())


# ── Test 10: Layer 2 entity match ─────────────────────────────────────────────

def test_entity_match_assigns_case():
    async def run():
        repo = _repo()
        tenant_id = uuid.uuid4()

        case = await _open_case_with_doc(
            repo, tenant_id,
            vendor_name='ACME GmbH',
            total_amount=Decimal('500.00'),
            due_date=date(2025, 6, 30),
        )
        # No references on the case → Layer 1 will skip, Layer 2 should hit

        result = await integrate_document_analysis(
            tenant_id=tenant_id,
            event_source='paperless_webhook',
            document_ref='paperless-500',
            document_type_value='INVOICE',
            vendor_name='ACME GmbH',
            total_amount=Decimal('500.00'),
            currency='EUR',
            document_date=date(2025, 6, 1),  # within 90 days of due_date
            due_date=None,
            reference_values=[],
            filename=None,
            overall_confidence=0.85,
            orchestration_case_id='doc-entity-1',
            repo=repo,
        )

        assert result['status'] == 'assigned'
        assert result['case_id'] == str(case.id)
        assert result['confidence'] == 'HIGH'
        assert result['method'] == 'entity_amount'
    _run(run())


# ── Test 11: Orchestration hook — finalize_document_review with tenant_id ─────

def test_orchestration_hook_sets_case_engine_result(monkeypatch, tmp_path):
    """End-to-end: finalize_document_review stores case_engine_result in state."""
    import importlib

    # ── patch settings ────────────────────────────────────────────────────────
    monkeypatch.setenv('FRYA_DATABASE_URL', 'memory://db')
    monkeypatch.setenv('FRYA_REDIS_URL', 'memory://redis')
    monkeypatch.setenv('FRYA_DATA_DIR', str(tmp_path))
    monkeypatch.setenv('FRYA_RULES_DIR', str(tmp_path))
    monkeypatch.setenv('FRYA_VERFAHRENSDOKU_DIR', str(tmp_path))
    monkeypatch.setenv('FRYA_PAPERLESS_BASE_URL', 'http://paperless')
    monkeypatch.setenv('FRYA_AKAUNTING_BASE_URL', 'http://akaunting')
    monkeypatch.setenv('FRYA_N8N_BASE_URL', 'http://n8n')
    monkeypatch.setenv('FRYA_AUTH_SESSION_SECRET', 'test-ce-hook')
    monkeypatch.setenv('FRYA_AUTH_COOKIE_SECURE', 'false')

    import app.config as config_module
    import app.dependencies as deps_module
    config_module.get_settings.cache_clear()
    for name in dir(deps_module):
        obj = getattr(deps_module, name)
        if callable(obj) and hasattr(obj, 'cache_clear'):
            obj.cache_clear()

    import app.orchestration.nodes as nodes_module
    importlib.reload(nodes_module)

    async def run():
        from app.document_analysis.models import (
            DocumentAnalysisResult,
            ExtractedField,
            DetectedAmount,
        )
        tenant_id = uuid.uuid4()

        # Minimal analysis result for an invoice
        analysis_result = DocumentAnalysisResult(
            case_id='doc-hook-test',
            document_ref='paperless-101',
            event_source='paperless_webhook',
            document_type=ExtractedField(value='INVOICE', status='FOUND', confidence=0.95, source_kind='OCR_TEXT'),
            sender=ExtractedField(value='Hook GmbH', status='FOUND', confidence=0.90, source_kind='OCR_TEXT'),
            recipient=ExtractedField(value=None, status='MISSING', confidence=0.0, source_kind='NONE'),
            amounts=[DetectedAmount(label='TOTAL', amount=Decimal('42.00'), currency='EUR', status='FOUND', confidence=0.88, source_kind='OCR_TEXT')],
            currency=ExtractedField(value='EUR', status='FOUND', confidence=0.92, source_kind='OCR_TEXT'),
            document_date=ExtractedField(value=None, status='MISSING', confidence=0.0, source_kind='NONE'),
            due_date=ExtractedField(value=None, status='MISSING', confidence=0.0, source_kind='NONE'),
            references=[],
            recommended_next_step='HUMAN_REVIEW',
            global_decision='LOW_CONFIDENCE',
            overall_confidence=0.45,
        )

        state = {
            'case_id': 'doc-hook-test',
            'source': 'paperless_webhook',
            'tenant_id': str(tenant_id),
            'document_ref': 'paperless-101',
            'paperless_metadata': {'filename': 'hook-test.pdf'},
            'document_analysis': analysis_result.model_dump(mode='json'),
        }

        result_state = await nodes_module.finalize_document_review(state)

        # The hook should have populated case_engine_result
        ce = result_state.get('case_engine_result')
        assert ce is not None
        assert ce['status'] in ('assigned', 'draft_created')
        assert ce['case_id'] is not None

    _run(run())


# ── Test 12: Orchestration hook — no tenant_id → skips silently ───────────────

def test_orchestration_hook_skips_without_tenant_id(monkeypatch, tmp_path):
    """finalize_document_review without tenant_id must not crash and not set case_engine_result."""
    import importlib

    monkeypatch.setenv('FRYA_DATABASE_URL', 'memory://db')
    monkeypatch.setenv('FRYA_REDIS_URL', 'memory://redis')
    monkeypatch.setenv('FRYA_DATA_DIR', str(tmp_path))
    monkeypatch.setenv('FRYA_RULES_DIR', str(tmp_path))
    monkeypatch.setenv('FRYA_VERFAHRENSDOKU_DIR', str(tmp_path))
    monkeypatch.setenv('FRYA_PAPERLESS_BASE_URL', 'http://paperless')
    monkeypatch.setenv('FRYA_AKAUNTING_BASE_URL', 'http://akaunting')
    monkeypatch.setenv('FRYA_N8N_BASE_URL', 'http://n8n')
    monkeypatch.setenv('FRYA_AUTH_SESSION_SECRET', 'test-ce-skip')
    monkeypatch.setenv('FRYA_AUTH_COOKIE_SECURE', 'false')

    import app.config as config_module
    import app.dependencies as deps_module
    config_module.get_settings.cache_clear()
    for name in dir(deps_module):
        obj = getattr(deps_module, name)
        if callable(obj) and hasattr(obj, 'cache_clear'):
            obj.cache_clear()

    import app.orchestration.nodes as nodes_module
    importlib.reload(nodes_module)

    async def run():
        from app.document_analysis.models import (
            DocumentAnalysisResult,
            ExtractedField,
        )

        analysis_result = DocumentAnalysisResult(
            case_id='doc-skip-test',
            document_ref=None,
            event_source='api',
            document_type=ExtractedField(value='OTHER', status='UNCERTAIN', confidence=0.45, source_kind='OCR_TEXT'),
            sender=ExtractedField(value=None, status='MISSING', confidence=0.0, source_kind='NONE'),
            recipient=ExtractedField(value=None, status='MISSING', confidence=0.0, source_kind='NONE'),
            amounts=[],
            currency=ExtractedField(value=None, status='MISSING', confidence=0.0, source_kind='NONE'),
            document_date=ExtractedField(value=None, status='MISSING', confidence=0.0, source_kind='NONE'),
            due_date=ExtractedField(value=None, status='MISSING', confidence=0.0, source_kind='NONE'),
            references=[],
            recommended_next_step='HUMAN_REVIEW',
            global_decision='INCOMPLETE',
            overall_confidence=0.0,
        )

        state = {
            'case_id': 'doc-skip-test',
            'source': 'api',
            # no tenant_id in state or metadata
            'document_analysis': analysis_result.model_dump(mode='json'),
        }

        result_state = await nodes_module.finalize_document_review(state)
        # Must not raise and must not set case_engine_result
        assert 'case_engine_result' not in result_state

    _run(run())
