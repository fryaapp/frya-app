"""Test: Annotation action_suggested → Akaunting/Paperless integration in nodes.py."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.document_analysis.models import (
    Annotation,
    DetectedAmount,
    DocumentAnalysisResult,
    ExtractedField,
)
from decimal import Decimal


def _base_result(annotations: list[Annotation]) -> DocumentAnalysisResult:
    return DocumentAnalysisResult(
        case_id='ann-action-case',
        event_source='test',
        document_type=ExtractedField(value='INVOICE', status='FOUND', confidence=0.9, source_kind='OCR_TEXT'),
        sender=ExtractedField(value='Test GmbH', status='FOUND', confidence=0.9, source_kind='OCR_TEXT'),
        recipient=ExtractedField(value='Empfänger', status='FOUND', confidence=0.9, source_kind='OCR_TEXT'),
        amounts=[DetectedAmount(label='TOTAL', amount=Decimal('49.95'), currency='EUR', status='FOUND', confidence=0.9, source_kind='OCR_TEXT')],
        currency=ExtractedField(value='EUR', status='FOUND', confidence=0.9, source_kind='OCR_TEXT'),
        document_date=ExtractedField(value=None, status='MISSING', confidence=0.0, source_kind='NONE'),
        due_date=ExtractedField(value=None, status='MISSING', confidence=0.0, source_kind='NONE'),
        references=[],
        risks=[],
        annotations=annotations,
        warnings=[],
        missing_fields=[],
        recommended_next_step='ACCOUNTING_REVIEW',
        global_decision='ANALYZED',
        ready_for_accounting_review=True,
        overall_confidence=0.9,
    )


@pytest.mark.asyncio
async def test_check_payment_exists_queries_akaunting():
    """CHECK_PAYMENT_EXISTS annotation → Akaunting search_transactions called."""
    from app.orchestration import nodes as n

    result = _base_result([
        Annotation(type='payment_note', raw_text='bez. 3.5.25', interpreted='bezahlt', confidence=0.8, action_suggested='CHECK_PAYMENT_EXISTS'),
    ])

    queried: list[dict] = []

    async def fake_search_tx(**kwargs):
        queried.append(kwargs)
        return []  # no payment found

    mock_connector = MagicMock()
    mock_connector.search_transactions = fake_search_tx

    async def fake_ensure_item(case_id, *, title, description, source, desired_status, document_ref=None):
        return 'oi-test'

    with patch.object(n, '_ensure_case_open_item', fake_ensure_item), \
         patch.object(n, '_ensure_problem_case', AsyncMock(return_value='prob-id')), \
         patch.object(n, '_build_accounting_review_draft', return_value=None), \
         patch.object(n, '_document_result_summary', return_value='summary'), \
         patch.object(n, '_document_policy_refs', return_value=[]), \
         patch.object(n, '_transition_case_open_items', AsyncMock()), \
         patch('app.orchestration.nodes.get_audit_service') as mock_audit, \
         patch('app.orchestration.nodes.get_case_repository', return_value=MagicMock()), \
         patch('app.orchestration.nodes.get_akaunting_connector', return_value=mock_connector):
        mock_audit.return_value.log_event = AsyncMock()
        mock_audit.return_value.by_case = AsyncMock(return_value=[])

        state = {
            'case_id': 'ann-action-case',
            'source': 'test',
            'document_analysis': result.model_dump(mode='json'),
        }
        await n.finalize_document_review(state)

    # Akaunting was queried
    assert len(queried) >= 1


@pytest.mark.asyncio
async def test_flag_for_tax_advisor_tags_paperless():
    """FLAG_FOR_TAX_ADVISOR → Paperless add_tag('steuerberater') called."""
    from app.orchestration import nodes as n

    result = _base_result([
        Annotation(type='tax_advisor_note', raw_text='StB', interpreted='Steuerberater', confidence=0.7, action_suggested='FLAG_FOR_TAX_ADVISOR'),
    ])
    result = result.model_copy(update={'document_ref': '123'})  # numeric = downloadable

    tagged: list[tuple] = []

    async def fake_add_tag(doc_id, tag):
        tagged.append((doc_id, tag))

    mock_paperless = MagicMock()
    mock_paperless.add_tag = fake_add_tag

    async def fake_ensure_item(case_id, *, title, description, source, desired_status, document_ref=None):
        return 'oi-test'

    with patch.object(n, '_ensure_case_open_item', fake_ensure_item), \
         patch.object(n, '_ensure_problem_case', AsyncMock(return_value='p')), \
         patch.object(n, '_build_accounting_review_draft', return_value=None), \
         patch.object(n, '_document_result_summary', return_value='s'), \
         patch.object(n, '_document_policy_refs', return_value=[]), \
         patch.object(n, '_transition_case_open_items', AsyncMock()), \
         patch('app.orchestration.nodes.get_audit_service') as mock_audit, \
         patch('app.orchestration.nodes.get_case_repository', return_value=MagicMock()), \
         patch('app.orchestration.nodes.get_paperless_connector', return_value=mock_paperless):
        mock_audit.return_value.log_event = AsyncMock()
        mock_audit.return_value.by_case = AsyncMock(return_value=[])

        state = {
            'case_id': 'ann-action-case',
            'source': 'test',
            'document_analysis': result.model_dump(mode='json'),
        }
        await n.finalize_document_review(state)

    assert ('123', 'steuerberater') in tagged


@pytest.mark.asyncio
async def test_flag_problem_case_creates_problem():
    """FLAG_PROBLEM_CASE → _ensure_problem_case called."""
    from app.orchestration import nodes as n

    result = _base_result([
        Annotation(type='problem_note', raw_text='Mängel', interpreted='Problem', confidence=0.8, action_suggested='FLAG_PROBLEM_CASE'),
    ])

    problem_created = []

    async def fake_ensure_problem(case_id, *, title, details, document_ref=None):
        problem_created.append({'case_id': case_id, 'title': title})
        return 'prob-001'

    async def fake_ensure_item(case_id, *, title, description, source, desired_status, document_ref=None):
        return 'oi-test'

    with patch.object(n, '_ensure_case_open_item', fake_ensure_item), \
         patch.object(n, '_ensure_problem_case', fake_ensure_problem), \
         patch.object(n, '_build_accounting_review_draft', return_value=None), \
         patch.object(n, '_document_result_summary', return_value='s'), \
         patch.object(n, '_document_policy_refs', return_value=[]), \
         patch.object(n, '_transition_case_open_items', AsyncMock()), \
         patch('app.orchestration.nodes.get_audit_service') as mock_audit, \
         patch('app.orchestration.nodes.get_case_repository', return_value=MagicMock()):
        mock_audit.return_value.log_event = AsyncMock()
        mock_audit.return_value.by_case = AsyncMock(return_value=[])

        state = {'case_id': 'ann-action-case', 'source': 'test', 'document_analysis': result.model_dump(mode='json')}
        await n.finalize_document_review(state)

    assert any('problem' in p['title'].lower() or 'Problemvermerk' in p['title'] for p in problem_created)


@pytest.mark.asyncio
async def test_suggest_allocation_creates_open_item():
    """SUGGEST_ALLOCATION → open item 'Kostenaufteilung pruefen' created."""
    from app.orchestration import nodes as n

    result = _base_result([
        Annotation(type='allocation_note', raw_text='50/50', interpreted='halb privat', confidence=0.75, action_suggested='SUGGEST_ALLOCATION'),
    ])

    created_items = []

    async def fake_ensure_item(case_id, *, title, description, source, desired_status, document_ref=None):
        created_items.append(title)
        return 'oi-test'

    with patch.object(n, '_ensure_case_open_item', fake_ensure_item), \
         patch.object(n, '_ensure_problem_case', AsyncMock(return_value='p')), \
         patch.object(n, '_build_accounting_review_draft', return_value=None), \
         patch.object(n, '_document_result_summary', return_value='s'), \
         patch.object(n, '_document_policy_refs', return_value=[]), \
         patch.object(n, '_transition_case_open_items', AsyncMock()), \
         patch('app.orchestration.nodes.get_audit_service') as mock_audit, \
         patch('app.orchestration.nodes.get_case_repository', return_value=MagicMock()):
        mock_audit.return_value.log_event = AsyncMock()
        mock_audit.return_value.by_case = AsyncMock(return_value=[])

        state = {'case_id': 'ann-action-case', 'source': 'test', 'document_analysis': result.model_dump(mode='json')}
        await n.finalize_document_review(state)

    assert any('Kosten' in t or 'aufteil' in t.lower() for t in created_items)
