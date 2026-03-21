"""Test: All 10 annotation pattern types parse correctly."""
import json
import pytest

from app.document_analysis.models import DocumentAnalysisInput
from app.document_analysis.semantic_service import DocumentAnalystSemanticService


def _make_service():
    svc = DocumentAnalystSemanticService.__new__(DocumentAnalystSemanticService)
    svc._model = 'test'
    svc._api_key = 'k'
    svc._base_url = None
    from app.document_analysis.service import DocumentAnalysisService
    svc._fallback = DocumentAnalysisService()
    return svc


def _payload():
    return DocumentAnalysisInput(case_id='ann-pat', event_source='test', ocr_text='Dokument mit Vermerk')


def _single_annotation(ann_type: str, action: str) -> str:
    return json.dumps({
        'document_type': 'INVOICE', 'sender': 'A', 'recipient': 'B',
        'total_amount': 10.0, 'currency': 'EUR', 'confidence': 0.8,
        'annotations': [{'type': ann_type, 'raw_text': 'raw', 'interpreted': 'interp', 'confidence': 0.7, 'action_suggested': action}],
    })


@pytest.mark.parametrize('ann_type,action', [
    ('payment_note', 'CHECK_PAYMENT_EXISTS'),
    ('status_note', 'NONE'),
    ('problem_note', 'FLAG_PROBLEM_CASE'),
    ('payment_method', 'NONE'),
    ('correction_note', 'NONE'),
    ('warning_note', 'NONE'),
    ('allocation_note', 'SUGGEST_ALLOCATION'),
    ('tax_advisor_note', 'FLAG_FOR_TAX_ADVISOR'),
    ('check_mark', 'NONE'),
    ('date_note', 'NONE'),
])
def test_annotation_type_parses(ann_type, action):
    svc = _make_service()
    result = svc._parse_llm_response(_single_annotation(ann_type, action), _payload())
    assert len(result.annotations) == 1
    ann = result.annotations[0]
    assert ann.type == ann_type
    assert ann.action_suggested == action
