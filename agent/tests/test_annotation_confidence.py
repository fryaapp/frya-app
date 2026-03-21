"""Test: Annotation confidence handling and bounds."""
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


def _payload(text='Dokument'):
    return DocumentAnalysisInput(case_id='conf-test', event_source='test', ocr_text=text)


def test_annotation_confidence_clamped_to_range():
    """Confidence outside [0,1] is clamped correctly."""
    svc = _make_service()
    llm_json = json.dumps({
        'document_type': 'INVOICE', 'sender': 'X', 'confidence': 0.8,
        'annotations': [
            {'type': 'payment_note', 'raw_text': 'bez.', 'interpreted': 'bezahlt', 'confidence': 1.5, 'action_suggested': 'CHECK_PAYMENT_EXISTS'},
            {'type': 'status_note', 'raw_text': 'ok', 'interpreted': 'erledigt', 'confidence': -0.3, 'action_suggested': 'NONE'},
        ],
    })
    result = svc._parse_llm_response(llm_json, _payload())
    assert result.annotations[0].confidence == pytest.approx(1.0)
    assert result.annotations[1].confidence == pytest.approx(0.0)


def test_annotation_missing_confidence_defaults_to_half():
    """Missing confidence field → defaults to 0.5."""
    svc = _make_service()
    llm_json = json.dumps({
        'document_type': 'INVOICE', 'sender': 'X', 'confidence': 0.8,
        'annotations': [
            {'type': 'date_note', 'raw_text': '3.5.25', 'interpreted': 'Datum', 'action_suggested': 'NONE'},
        ],
    })
    result = svc._parse_llm_response(llm_json, _payload())
    assert result.annotations[0].confidence == pytest.approx(0.5)


def test_annotation_non_dict_entries_skipped():
    """Non-dict annotation entries are ignored gracefully."""
    svc = _make_service()
    llm_json = json.dumps({
        'document_type': 'RECEIPT', 'sender': 'Shop', 'confidence': 0.75,
        'annotations': ['not a dict', 42, None, {'type': 'status_note', 'raw_text': 'OK', 'interpreted': 'OK', 'confidence': 0.9, 'action_suggested': 'NONE'}],
    })
    result = svc._parse_llm_response(llm_json, _payload())
    # Only the valid dict entry is parsed
    assert len(result.annotations) == 1
    assert result.annotations[0].type == 'status_note'
