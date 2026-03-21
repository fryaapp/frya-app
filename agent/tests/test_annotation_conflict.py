"""Test: OCR amount vs. handwritten note creates conflict detection."""
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


def test_payment_note_with_different_amount_is_present():
    """Payment note with amount different from invoice → annotation present with CHECK_PAYMENT_EXISTS."""
    svc = _make_service()
    llm_json = json.dumps({
        'document_type': 'INVOICE',
        'sender': 'Lieferant GmbH',
        'recipient': 'Kunde AG',
        'total_amount': 49.95,
        'currency': 'EUR',
        'document_date': '01.03.2025',
        'invoice_number': 'RE-001',
        'confidence': 0.6,  # Lower confidence due to conflict
        'annotations': [{
            'type': 'payment_note',
            'raw_text': '45,00 bezahlt',
            'interpreted': 'Zahlungsvermerk: bezahlt 45,00 EUR — weicht von Rechnungsbetrag 49,95 EUR ab',
            'confidence': 0.65,
            'action_suggested': 'CHECK_PAYMENT_EXISTS',
        }],
    })
    payload = DocumentAnalysisInput(
        case_id='conflict-case',
        event_source='test',
        ocr_text='Rechnung Betrag: 49,95 EUR\n\n45,00 bezahlt',
        document_ref='doc-conflict',
    )
    result = svc._parse_llm_response(llm_json, payload)
    assert len(result.annotations) == 1
    ann = result.annotations[0]
    assert ann.type == 'payment_note'
    assert ann.action_suggested == 'CHECK_PAYMENT_EXISTS'
    # The LLM lowered confidence to 0.6 to signal conflict
    assert result.overall_confidence <= 0.7


def test_no_conflict_when_annotations_empty():
    svc = _make_service()
    llm_json = json.dumps({
        'document_type': 'INVOICE',
        'sender': 'Lieferant GmbH',
        'recipient': 'Kunde AG',
        'total_amount': 49.95,
        'currency': 'EUR',
        'confidence': 0.9,
        'annotations': [],
    })
    payload = DocumentAnalysisInput(case_id='no-conflict', event_source='test', ocr_text='Rechnung 49,95 EUR')
    result = svc._parse_llm_response(llm_json, payload)
    assert result.annotations == []
    assert result.overall_confidence == pytest.approx(0.9)
