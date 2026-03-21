"""Test: annotations extracted from OCR text with handwritten notes."""
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.document_analysis.models import DocumentAnalysisInput
from app.document_analysis.semantic_service import DocumentAnalystSemanticService


def _make_service():
    svc = DocumentAnalystSemanticService.__new__(DocumentAnalystSemanticService)
    svc._model = 'openai/test-model'
    svc._api_key = 'test-key'
    svc._base_url = None
    from app.document_analysis.service import DocumentAnalysisService
    svc._fallback = DocumentAnalysisService()
    return svc


def _payload(ocr_text: str) -> DocumentAnalysisInput:
    return DocumentAnalysisInput(
        case_id='test-case-ann',
        event_source='test',
        ocr_text=ocr_text,
        document_ref='doc-1',
    )


def _llm_response(annotations: list[dict], doc_type: str = 'INVOICE', confidence: float = 0.85) -> str:
    return json.dumps({
        'document_type': doc_type,
        'sender': 'Test GmbH',
        'recipient': 'Max Mustermann',
        'total_amount': 49.95,
        'currency': 'EUR',
        'document_date': '01.01.2025',
        'due_date': '15.01.2025',
        'invoice_number': 'RE-2025-001',
        'confidence': confidence,
        'annotations': annotations,
    })


def test_annotation_payment_note_extracted():
    svc = _make_service()
    llm_json = _llm_response([{
        'type': 'payment_note',
        'raw_text': 'bez. 3.5.25',
        'interpreted': 'Zahlungsvermerk: bezahlt am 03.05.2025',
        'confidence': 0.8,
        'action_suggested': 'CHECK_PAYMENT_EXISTS',
    }])
    result = svc._parse_llm_response(llm_json, _payload('Rechnung Betrag 49,95 EUR bez. 3.5.25'))
    assert len(result.annotations) == 1
    ann = result.annotations[0]
    assert ann.type == 'payment_note'
    assert ann.raw_text == 'bez. 3.5.25'
    assert ann.action_suggested == 'CHECK_PAYMENT_EXISTS'
    assert ann.confidence == pytest.approx(0.8)


def test_annotation_empty_when_no_notes():
    svc = _make_service()
    llm_json = _llm_response([])
    result = svc._parse_llm_response(llm_json, _payload('Rechnung ohne Vermerke'))
    assert result.annotations == []


def test_annotation_multiple_types():
    svc = _make_service()
    llm_json = _llm_response([
        {'type': 'tax_advisor_note', 'raw_text': 'StB', 'interpreted': 'Steuerberater-Relevanz', 'confidence': 0.7, 'action_suggested': 'FLAG_FOR_TAX_ADVISOR'},
        {'type': 'allocation_note', 'raw_text': '50/50', 'interpreted': 'Halb privat halb betrieblich', 'confidence': 0.75, 'action_suggested': 'SUGGEST_ALLOCATION'},
    ])
    result = svc._parse_llm_response(llm_json, _payload('Rechnung StB 50/50'))
    assert len(result.annotations) == 2
    types = {a.type for a in result.annotations}
    assert 'tax_advisor_note' in types
    assert 'allocation_note' in types


def test_annotation_invalid_type_becomes_unknown():
    svc = _make_service()
    llm_json = _llm_response([{
        'type': 'nonexistent_type',
        'raw_text': 'xyz',
        'interpreted': 'unbekannt',
        'confidence': 0.5,
        'action_suggested': 'NONE',
    }])
    result = svc._parse_llm_response(llm_json, _payload('Dokument'))
    assert len(result.annotations) == 1
    assert result.annotations[0].type == 'unknown'


def test_annotation_invalid_action_becomes_none():
    svc = _make_service()
    llm_json = _llm_response([{
        'type': 'status_note',
        'raw_text': 'ERLEDIGT',
        'interpreted': 'Erledigt',
        'confidence': 0.9,
        'action_suggested': 'INVALID_ACTION',
    }])
    result = svc._parse_llm_response(llm_json, _payload('Dokument ERLEDIGT'))
    assert result.annotations[0].action_suggested == 'NONE'
