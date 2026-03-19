"""Tests for Document Analyst OCR/Semantic split (Paket 22).

Verifies that:
1. When document_analyst_semantic has an API key → DocumentAnalystSemanticService is used.
2. When no API key is configured → regex DocumentAnalysisService is used (fallback).
3. When the LLM call fails → SemanticService falls back to regex automatically.
4. _parse_llm_response maps a valid JSON response to DocumentAnalysisResult correctly.
5. _build_document_analysis_service routing logic is correct.
6. Existing DocumentAnalysisService (regex) is unaffected by the split.
"""
from __future__ import annotations

import asyncio
import json
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.document_analysis.models import DocumentAnalysisInput, DocumentAnalysisResult
from app.document_analysis.semantic_service import DocumentAnalystSemanticService, _parse_date
from app.document_analysis.service import DocumentAnalysisService
from app.orchestration.nodes import _build_document_analysis_service


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_input(ocr_text: str = '', case_id: str = 'test-case') -> DocumentAnalysisInput:
    return DocumentAnalysisInput(
        case_id=case_id,
        document_ref='doc-ref-1',
        event_source='test',
        ocr_text=ocr_text,
    )


def _invoice_json(confidence: float = 0.92) -> str:
    return json.dumps({
        'document_type': 'INVOICE',
        'sender': 'Lieferant GmbH',
        'recipient': 'Kunde AG',
        'total_amount': 1190.00,
        'currency': 'EUR',
        'document_date': '15.03.2026',
        'due_date': '15.04.2026',
        'invoice_number': 'RE-2026-042',
        'confidence': confidence,
    })


def _mock_completion(content: str):
    msg = MagicMock()
    msg.content = content
    choice = MagicMock()
    choice.message = msg
    completion = MagicMock()
    completion.choices = [choice]
    return completion


# ---------------------------------------------------------------------------
# _parse_date helper
# ---------------------------------------------------------------------------

def test_parse_date_german_format():
    d = _parse_date('15.03.2026')
    assert d is not None
    assert d.year == 2026 and d.month == 3 and d.day == 15


def test_parse_date_iso_format():
    d = _parse_date('2026-03-15')
    assert d is not None
    assert d.year == 2026 and d.month == 3 and d.day == 15


def test_parse_date_none():
    assert _parse_date(None) is None
    assert _parse_date('') is None
    assert _parse_date('not-a-date') is None


# ---------------------------------------------------------------------------
# _parse_llm_response — unit tests
# ---------------------------------------------------------------------------

def test_parse_llm_response_invoice():
    svc = DocumentAnalystSemanticService(model='test-model', api_key=None, base_url=None)
    payload = _make_input('Rechnung über 1190 EUR')
    result = svc._parse_llm_response(_invoice_json(), payload)

    assert isinstance(result, DocumentAnalysisResult)
    assert result.analysis_version == 'document-analyst-semantic-v1'
    assert result.document_type.value == 'INVOICE'
    assert result.sender.value == 'Lieferant GmbH'
    assert result.recipient.value == 'Kunde AG'
    assert len(result.amounts) == 1
    assert result.amounts[0].amount == Decimal('1190.0')
    assert result.amounts[0].currency == 'EUR'
    assert result.currency.value == 'EUR'
    assert result.document_date.value is not None
    assert result.document_date.value.year == 2026
    assert result.due_date.value is not None
    assert len(result.references) == 1
    assert result.references[0].value == 'RE-2026-042'
    assert result.overall_confidence == pytest.approx(0.92)


def test_parse_llm_response_missing_fields_yields_incomplete():
    svc = DocumentAnalystSemanticService(model='test-model', api_key=None, base_url=None)
    # Invoice without sender/amounts/date → INCOMPLETE decision
    minimal_json = json.dumps({
        'document_type': 'INVOICE',
        'sender': None,
        'recipient': None,
        'total_amount': None,
        'currency': None,
        'document_date': None,
        'due_date': None,
        'invoice_number': None,
        'confidence': 0.6,
    })
    result = svc._parse_llm_response(minimal_json, _make_input('Rechnung'))
    assert result.global_decision == 'INCOMPLETE'
    assert 'sender' in result.missing_fields or 'amounts' in result.missing_fields


def test_parse_llm_response_strips_markdown_fences():
    svc = DocumentAnalystSemanticService(model='test-model', api_key=None, base_url=None)
    wrapped = f'```json\n{_invoice_json()}\n```'
    result = svc._parse_llm_response(wrapped, _make_input('Rechnung'))
    assert result.document_type.value == 'INVOICE'


def test_parse_llm_response_invalid_json_raises():
    svc = DocumentAnalystSemanticService(model='test-model', api_key=None, base_url=None)
    with pytest.raises(Exception):
        svc._parse_llm_response('not json at all', _make_input('text'))


def test_parse_llm_response_unknown_doc_type_becomes_other():
    svc = DocumentAnalystSemanticService(model='test-model', api_key=None, base_url=None)
    data = json.dumps({'document_type': 'VERTRAG', 'confidence': 0.5})
    result = svc._parse_llm_response(data, _make_input('text'))
    assert result.document_type.value == 'OTHER'


# ---------------------------------------------------------------------------
# SemanticService.analyze — happy path (mocked LLM)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_semantic_service_analyze_uses_llm():
    svc = DocumentAnalystSemanticService(
        model='openai/mistralai/Mistral-Small-24B-Instruct',
        api_key='test-api-key',
        base_url='https://openai.inference.de-txl.ionos.com/v1',
    )
    payload = _make_input('Rechnung über 1190 EUR von Lieferant GmbH')

    with patch('app.document_analysis.semantic_service.acompletion', new=AsyncMock(
        return_value=_mock_completion(_invoice_json())
    )) as mock_call:
        result = await svc.analyze(payload)
        assert mock_call.called
        assert result.analysis_version == 'document-analyst-semantic-v1'
        assert result.document_type.value == 'INVOICE'


@pytest.mark.asyncio
async def test_semantic_service_passes_api_key_and_base_url():
    svc = DocumentAnalystSemanticService(
        model='openai/test-model',
        api_key='my-secret-key',
        base_url='https://ionos.example.com/v1',
    )

    captured: list[dict] = []

    async def fake_completion(**kwargs):
        captured.append(kwargs)
        return _mock_completion(_invoice_json())

    with patch('app.document_analysis.semantic_service.acompletion', new=fake_completion):
        await svc.analyze(_make_input('Rechnung text'))

    assert len(captured) == 1
    assert captured[0]['api_key'] == 'my-secret-key'
    assert captured[0]['api_base'] == 'https://ionos.example.com/v1'
    assert captured[0]['temperature'] == 0.0


# ---------------------------------------------------------------------------
# SemanticService.analyze — fallback on LLM error
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_semantic_service_falls_back_on_llm_error():
    fallback = DocumentAnalysisService()
    svc = DocumentAnalystSemanticService(
        model='openai/test-model',
        api_key='key',
        base_url=None,
        fallback_service=fallback,
    )
    payload = _make_input('Rechnung von ABC GmbH über 500 EUR Rechnungsdatum 01.03.2026')

    with patch('app.document_analysis.semantic_service.acompletion',
               new=AsyncMock(side_effect=RuntimeError('LLM unreachable'))):
        result = await svc.analyze(payload)

    # Fallback regex service returns v1 version
    assert result.analysis_version == 'document-analyst-v1'
    assert isinstance(result, DocumentAnalysisResult)


@pytest.mark.asyncio
async def test_semantic_service_falls_back_on_invalid_json():
    svc = DocumentAnalystSemanticService(model='m', api_key='k', base_url=None)
    payload = _make_input('Rechnung text')

    with patch('app.document_analysis.semantic_service.acompletion',
               new=AsyncMock(return_value=_mock_completion('this is not json'))):
        result = await svc.analyze(payload)

    assert result.analysis_version == 'document-analyst-v1'


@pytest.mark.asyncio
async def test_semantic_service_delegates_to_fallback_when_no_ocr_text():
    fallback = DocumentAnalysisService()
    svc = DocumentAnalystSemanticService(model='m', api_key='k', base_url=None,
                                         fallback_service=fallback)
    payload = _make_input('')  # empty OCR text

    with patch('app.document_analysis.semantic_service.acompletion') as mock_call:
        result = await svc.analyze(payload)
        assert not mock_call.called  # LLM not called when no text
    assert result.analysis_version == 'document-analyst-v1'


# ---------------------------------------------------------------------------
# _build_document_analysis_service routing
# ---------------------------------------------------------------------------

def test_build_service_returns_regex_when_no_repo():
    svc = _build_document_analysis_service(None, None)
    assert isinstance(svc, DocumentAnalysisService)


def test_build_service_returns_regex_when_no_config():
    repo = MagicMock()
    svc = _build_document_analysis_service(repo, None)
    assert isinstance(svc, DocumentAnalysisService)


def test_build_service_returns_regex_when_no_api_key():
    repo = MagicMock()
    repo.decrypt_key_for_call.return_value = None  # no key
    config = {
        'model': 'mistralai/Mistral-Small-24B-Instruct',
        'provider': 'ionos',
        'base_url': 'https://openai.inference.de-txl.ionos.com/v1',
        'api_key_encrypted': None,
    }
    svc = _build_document_analysis_service(repo, config)
    assert isinstance(svc, DocumentAnalysisService)


def test_build_service_returns_semantic_when_key_present():
    repo = MagicMock()
    repo.decrypt_key_for_call.return_value = 'decrypted-api-key'
    config = {
        'model': 'mistralai/Mistral-Small-24B-Instruct',
        'provider': 'ionos',
        'base_url': 'https://openai.inference.de-txl.ionos.com/v1',
        'api_key_encrypted': 'gAAAAA...',
    }
    svc = _build_document_analysis_service(repo, config)
    assert isinstance(svc, DocumentAnalystSemanticService)


def test_build_service_ionos_model_gets_openai_prefix():
    repo = MagicMock()
    repo.decrypt_key_for_call.return_value = 'key'
    config = {
        'model': 'mistralai/Mistral-Small-24B-Instruct',
        'provider': 'ionos',
        'base_url': 'https://openai.inference.de-txl.ionos.com/v1',
    }
    svc = _build_document_analysis_service(repo, config)
    assert isinstance(svc, DocumentAnalystSemanticService)
    assert svc._model == 'openai/mistralai/Mistral-Small-24B-Instruct'


def test_build_service_returns_regex_when_model_empty():
    repo = MagicMock()
    repo.decrypt_key_for_call.return_value = 'key'
    config = {'model': '', 'provider': 'ionos', 'api_key_encrypted': 'gAAAAA...'}
    svc = _build_document_analysis_service(repo, config)
    assert isinstance(svc, DocumentAnalysisService)


def test_build_service_returns_regex_when_decrypt_raises():
    repo = MagicMock()
    repo.decrypt_key_for_call.side_effect = RuntimeError('bad key')
    config = {'model': 'some-model', 'provider': 'ionos', 'api_key_encrypted': 'gAAAAA...'}
    svc = _build_document_analysis_service(repo, config)
    assert isinstance(svc, DocumentAnalysisService)


# ---------------------------------------------------------------------------
# Regression: existing regex DocumentAnalysisService unaffected
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_regex_service_still_works_for_invoice():
    svc = DocumentAnalysisService()
    payload = DocumentAnalysisInput(
        case_id='reg-test',
        document_ref=None,
        event_source='test',
        ocr_text=(
            'Rechnung\nAbsender: Lieferant GmbH\n'
            'Rechnungsnummer: RE-2026-099\n'
            'Rechnungsdatum: 15.03.2026\n'
            'Gesamtbetrag: 1.190,00 EUR'
        ),
    )
    result = await svc.analyze(payload)
    assert result.analysis_version == 'document-analyst-v1'
    assert result.document_type.value == 'INVOICE'
    assert result.global_decision in ('ANALYZED', 'INCOMPLETE', 'LOW_CONFIDENCE')
