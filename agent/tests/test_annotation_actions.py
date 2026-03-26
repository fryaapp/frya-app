"""Test: action_suggested triggers correct orchestrator actions in finalize_document_review."""
import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from app.document_analysis.models import (
    Annotation,
    DetectedAmount,
    DocumentAnalysisResult,
    ExtractedField,
)


def _base_result(**kwargs) -> DocumentAnalysisResult:
    defaults = dict(
        case_id='action-test',
        event_source='test',
        document_type=ExtractedField(value='INVOICE', status='FOUND', confidence=0.9, source_kind='OCR_TEXT'),
        sender=ExtractedField(value='Test GmbH', status='FOUND', confidence=0.9, source_kind='OCR_TEXT'),
        recipient=ExtractedField(value='Empfänger', status='FOUND', confidence=0.9, source_kind='OCR_TEXT'),
        amounts=[DetectedAmount(label='TOTAL', amount='49.95', currency='EUR', status='FOUND', confidence=0.9, source_kind='OCR_TEXT')],
        currency=ExtractedField(value='EUR', status='FOUND', confidence=0.9, source_kind='OCR_TEXT'),
        document_date=ExtractedField(value=None, status='MISSING', confidence=0.0, source_kind='NONE'),
        due_date=ExtractedField(value=None, status='MISSING', confidence=0.0, source_kind='NONE'),
        references=[],
        risks=[],
        annotations=[],
        warnings=[],
        missing_fields=[],
        recommended_next_step='ACCOUNTING_REVIEW',
        global_decision='ANALYZED',
        ready_for_accounting_review=True,
        overall_confidence=0.9,
    )
    defaults.update(kwargs)
    return DocumentAnalysisResult(**defaults)


@pytest.mark.asyncio
async def test_check_payment_exists_creates_open_item():
    """CHECK_PAYMENT_EXISTS → open item 'Zahlungsvermerk pruefen' created."""
    from app.orchestration import nodes as n

    result = _base_result(annotations=[
        Annotation(type='payment_note', raw_text='bez. 3.5.25', interpreted='bezahlt am 03.05.2025', confidence=0.8, action_suggested='CHECK_PAYMENT_EXISTS'),
    ])

    created_items: list[str] = []

    async def fake_ensure_open_item(case_id, *, title, description, source, desired_status, document_ref=None):
        created_items.append(title)
        return 'open-item-id'

    async def fake_log_event(event):
        pass

    async def fake_audit_by_case(case_id, limit=100):
        return []

    with patch.object(n, '_ensure_case_open_item', fake_ensure_open_item), \
         patch.object(n, '_ensure_problem_case', AsyncMock(return_value='prob-id')), \
         patch.object(n, '_build_accounting_review_draft', return_value=None), \
         patch.object(n, '_document_result_summary', return_value='summary'), \
         patch.object(n, '_document_policy_refs', return_value=[]), \
         patch.object(n, '_transition_case_open_items', AsyncMock()), \
         patch('app.orchestration.nodes.get_audit_service') as mock_audit, \
         patch('app.orchestration.nodes.get_case_repository', return_value=MagicMock()):
        mock_audit.return_value.log_event = fake_log_event
        mock_audit.return_value.by_case = fake_audit_by_case

        state = {
            'case_id': 'action-test',
            'source': 'test',
            'document_analysis': result.model_dump(mode='json'),
        }
        await n.finalize_document_review(state)

    assert any('Zahlungsvermerk' in t for t in created_items), f'Expected Zahlungsvermerk open item, got: {created_items}'


@pytest.mark.asyncio
async def test_flag_for_tax_advisor_logs_event():
    """FLAG_FOR_TAX_ADVISOR → TAX_ADVISOR_FLAG_SET audit event."""
    from app.orchestration import nodes as n

    result = _base_result(annotations=[
        Annotation(type='tax_advisor_note', raw_text='StB', interpreted='Steuerberater-Relevanz', confidence=0.7, action_suggested='FLAG_FOR_TAX_ADVISOR'),
    ])

    logged_actions: list[str] = []

    async def fake_log_event(event):
        logged_actions.append(event.get('action', ''))

    with patch.object(n, '_ensure_case_open_item', AsyncMock(return_value='oi')), \
         patch.object(n, '_ensure_problem_case', AsyncMock(return_value='pi')), \
         patch.object(n, '_build_accounting_review_draft', return_value=None), \
         patch.object(n, '_document_result_summary', return_value='summary'), \
         patch.object(n, '_document_policy_refs', return_value=[]), \
         patch.object(n, '_transition_case_open_items', AsyncMock()), \
         patch('app.orchestration.nodes.get_audit_service') as mock_audit, \
         patch('app.orchestration.nodes.get_case_repository', return_value=MagicMock()):
        mock_audit.return_value.log_event = fake_log_event
        mock_audit.return_value.by_case = AsyncMock(return_value=[])

        state = {
            'case_id': 'action-test',
            'source': 'test',
            'document_analysis': result.model_dump(mode='json'),
        }
        await n.finalize_document_review(state)

    assert 'TAX_ADVISOR_FLAG_SET' in logged_actions, f'Expected TAX_ADVISOR_FLAG_SET, got: {logged_actions}'
