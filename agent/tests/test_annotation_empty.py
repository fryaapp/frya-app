"""Test: No handwritten notes → annotations = []."""
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


def test_empty_annotations_when_no_notes():
    svc = _make_service()
    llm_json = json.dumps({
        'document_type': 'INVOICE',
        'sender': 'Hetzner Online GmbH',
        'recipient': 'Max Mustermann',
        'total_amount': 6.38,
        'currency': 'EUR',
        'document_date': '01.03.2025',
        'invoice_number': 'R2025001',
        'confidence': 0.92,
        'annotations': [],
    })
    payload = DocumentAnalysisInput(
        case_id='no-notes-case',
        event_source='test',
        ocr_text='Rechnung Hetzner Online GmbH\nBetrag: 6,38 EUR\nRechnungsnummer: R2025001',
    )
    result = svc._parse_llm_response(llm_json, payload)
    assert result.annotations == []


def test_empty_annotations_when_field_missing():
    """LLM omits annotations field entirely → empty list, no error."""
    svc = _make_service()
    llm_json = json.dumps({
        'document_type': 'LETTER',
        'sender': None,
        'recipient': None,
        'total_amount': None,
        'currency': None,
        'confidence': 0.4,
        # no 'annotations' key at all
    })
    payload = DocumentAnalysisInput(case_id='missing-field', event_source='test', ocr_text='Brief')
    result = svc._parse_llm_response(llm_json, payload)
    assert result.annotations == []


def test_none_annotations_treated_as_empty():
    svc = _make_service()
    llm_json = json.dumps({
        'document_type': 'RECEIPT',
        'sender': 'Shop',
        'confidence': 0.7,
        'annotations': None,
    })
    payload = DocumentAnalysisInput(case_id='null-ann', event_source='test', ocr_text='Quittung')
    result = svc._parse_llm_response(llm_json, payload)
    assert result.annotations == []
