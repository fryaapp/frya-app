"""Tests for E-Rechnung integration: DocAnalyst e-invoice fast path."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

lxml = pytest.importorskip('lxml', reason='lxml not installed; run: pip install lxml')

from app.e_invoice.parser import (
    EInvoiceData,
    EInvoiceLineItem,
    EInvoiceType,
    e_invoice_to_document_analysis_result,
    parse_xrechnung,
    detect_e_invoice,
)


# ─────────────────────────────────────────────────────────────────────
# Minimal CII XML fixture (shared across tests)
# ─────────────────────────────────────────────────────────────────────

_CII_XML = b'''\
<?xml version="1.0" encoding="UTF-8"?>
<rsm:CrossIndustryInvoice
  xmlns:rsm="urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100"
  xmlns:ram="urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100"
  xmlns:udt="urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100">
  <rsm:ExchangedDocumentContext>
    <ram:GuidelineSpecifiedDocumentContextParameter>
      <ram:ID>urn:cen.eu:en16931:2017</ram:ID>
    </ram:GuidelineSpecifiedDocumentContextParameter>
  </rsm:ExchangedDocumentContext>
  <rsm:ExchangedDocument>
    <ram:ID>INT-TEST-001</ram:ID>
    <ram:TypeCode>380</ram:TypeCode>
    <ram:IssueDateTime><udt:DateTimeString format="102">20260319</udt:DateTimeString></ram:IssueDateTime>
  </rsm:ExchangedDocument>
  <rsm:SupplyChainTradeTransaction>
    <ram:ApplicableHeaderTradeAgreement>
      <ram:SellerTradeParty><ram:Name>Integration Seller GmbH</ram:Name></ram:SellerTradeParty>
      <ram:BuyerTradeParty><ram:Name>Integration Buyer AG</ram:Name></ram:BuyerTradeParty>
    </ram:ApplicableHeaderTradeAgreement>
    <ram:ApplicableHeaderTradeDelivery/>
    <ram:ApplicableHeaderTradeSettlement>
      <ram:InvoiceCurrencyCode>EUR</ram:InvoiceCurrencyCode>
      <ram:SpecifiedTradeSettlementHeaderMonetarySummation>
        <ram:TaxBasisTotalAmount>1000.00</ram:TaxBasisTotalAmount>
        <ram:TaxTotalAmount currencyID="EUR">190.00</ram:TaxTotalAmount>
        <ram:GrandTotalAmount>1190.00</ram:GrandTotalAmount>
        <ram:DuePayableAmount>1190.00</ram:DuePayableAmount>
      </ram:SpecifiedTradeSettlementHeaderMonetarySummation>
    </ram:ApplicableHeaderTradeSettlement>
    <ram:IncludedSupplyChainTradeLineItem>
      <ram:AssociatedDocumentLineDocument><ram:LineID>1</ram:LineID></ram:AssociatedDocumentLineDocument>
      <ram:SpecifiedTradeProduct><ram:Name>Integrationstest Produkt</ram:Name></ram:SpecifiedTradeProduct>
      <ram:SpecifiedLineTradeAgreement>
        <ram:NetPriceProductTradePrice><ram:ChargeAmount>1000.00</ram:ChargeAmount></ram:NetPriceProductTradePrice>
      </ram:SpecifiedLineTradeAgreement>
      <ram:SpecifiedLineTradeDelivery><ram:BilledQuantity unitCode="C62">1.0</ram:BilledQuantity></ram:SpecifiedLineTradeDelivery>
      <ram:SpecifiedLineTradeSettlement>
        <ram:ApplicableTradeTax><ram:RateApplicablePercent>19.00</ram:RateApplicablePercent></ram:ApplicableTradeTax>
        <ram:SpecifiedTradeSettlementLineMonetarySummation><ram:LineTotalAmount>1000.00</ram:LineTotalAmount></ram:SpecifiedTradeSettlementLineMonetarySummation>
      </ram:SpecifiedLineTradeSettlement>
    </ram:IncludedSupplyChainTradeLineItem>
  </rsm:SupplyChainTradeTransaction>
</rsm:CrossIndustryInvoice>'''


# ─────────────────────────────────────────────────────────────────────
# Detection + parsing pipeline
# ─────────────────────────────────────────────────────────────────────

def test_detect_then_parse_cii_pipeline():
    """Full pipeline: detect → parse → EInvoiceData."""
    e_type = detect_e_invoice(_CII_XML)
    assert e_type == EInvoiceType.XRECHNUNG

    data = parse_xrechnung(_CII_XML)
    assert data.invoice_number == 'INT-TEST-001'
    assert data.total_gross == Decimal('1190.00')


def test_detect_then_convert_to_doc_result():
    """Pipeline: detect → parse → DocumentAnalysisResult."""
    e_type = detect_e_invoice(_CII_XML)
    assert e_type is not None

    data = parse_xrechnung(_CII_XML)
    result = e_invoice_to_document_analysis_result(
        data,
        case_id='integration-case',
        document_ref='doc-42',
        event_source='test',
    )

    assert result.overall_confidence == 1.0
    assert result.global_decision == 'ANALYZED'
    assert result.ready_for_accounting_review is True
    assert result.case_id == 'integration-case'
    assert result.document_ref == 'doc-42'
    assert result.event_source == 'test'


# ─────────────────────────────────────────────────────────────────────
# DocumentAnalysisResult fields from e-invoice
# ─────────────────────────────────────────────────────────────────────

def test_e_invoice_result_has_seller_as_sender():
    data = parse_xrechnung(_CII_XML)
    result = e_invoice_to_document_analysis_result(data, case_id='c1')
    assert result.sender.value == 'Integration Seller GmbH'
    assert result.sender.status == 'FOUND'
    assert result.sender.confidence == 1.0


def test_e_invoice_result_has_buyer_as_recipient():
    data = parse_xrechnung(_CII_XML)
    result = e_invoice_to_document_analysis_result(data, case_id='c1')
    assert result.recipient.value == 'Integration Buyer AG'
    assert result.recipient.status == 'FOUND'


def test_e_invoice_result_amounts_all_confidence_1():
    data = parse_xrechnung(_CII_XML)
    result = e_invoice_to_document_analysis_result(data, case_id='c1')
    for amount in result.amounts:
        assert amount.confidence == 1.0


def test_e_invoice_result_total_amount_correct():
    data = parse_xrechnung(_CII_XML)
    result = e_invoice_to_document_analysis_result(data, case_id='c1')
    total = next(a for a in result.amounts if a.label == 'TOTAL')
    assert total.amount == Decimal('1190.00')
    assert total.currency == 'EUR'


def test_e_invoice_result_date_fields():
    data = parse_xrechnung(_CII_XML)
    result = e_invoice_to_document_analysis_result(data, case_id='c1')
    assert result.document_date.value == date(2026, 3, 19)
    assert result.document_date.status == 'FOUND'
    assert result.document_date.confidence == 1.0


def test_e_invoice_result_analysis_version():
    data = parse_xrechnung(_CII_XML)
    result = e_invoice_to_document_analysis_result(data, case_id='c1')
    assert result.analysis_version == 'e-invoice-v1'


def test_e_invoice_result_no_warnings():
    data = parse_xrechnung(_CII_XML)
    result = e_invoice_to_document_analysis_result(data, case_id='c1')
    assert result.warnings == []


def test_e_invoice_result_no_missing_fields():
    data = parse_xrechnung(_CII_XML)
    result = e_invoice_to_document_analysis_result(data, case_id='c1')
    assert result.missing_fields == []


def test_e_invoice_result_recommended_accounting_review():
    data = parse_xrechnung(_CII_XML)
    result = e_invoice_to_document_analysis_result(data, case_id='c1')
    assert result.recommended_next_step == 'ACCOUNTING_REVIEW'


# ─────────────────────────────────────────────────────────────────────
# nodes.run_document_analyst e-invoice shortcut
# ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_run_document_analyst_e_invoice_skips_llm():
    """When pdf_bytes contains XRechnung XML, result comes from parser (confidence=1.0)."""
    from unittest.mock import AsyncMock, patch

    from app.orchestration.nodes import run_document_analyst

    state: dict = {
        'case_id': 'einvoice-test',
        'source': 'test',
        'pdf_bytes': _CII_XML,
    }

    # acompletion must never be called for e-invoice path
    with patch('app.orchestration.nodes.acompletion', new=AsyncMock(side_effect=AssertionError('LLM must not be called for e-invoice'))):
        result_state = await run_document_analyst(state)

    assert 'document_analysis' in result_state
    doc_analysis = result_state['document_analysis']
    assert doc_analysis['overall_confidence'] == 1.0
    assert doc_analysis['global_decision'] == 'ANALYZED'
    assert doc_analysis['analysis_version'] == 'e-invoice-v1'


@pytest.mark.asyncio
async def test_run_document_analyst_no_pdf_bytes_uses_normal_path():
    """Without pdf_bytes, normal OCR/LLM analysis is attempted (config-dependent)."""
    from unittest.mock import AsyncMock, MagicMock, patch

    from app.orchestration.nodes import run_document_analyst

    state: dict = {
        'case_id': 'normal-test',
        'source': 'test',
        'ocr_text': 'Rechnung Nr. 42 Betrag: 100,00 EUR',
    }

    mock_repo = MagicMock()
    mock_repo.get_config_or_fallback = AsyncMock(return_value={'model': '', 'provider': ''})
    mock_repo.decrypt_key_for_call = MagicMock(return_value=None)

    with patch('app.orchestration.nodes._build_document_context', new=AsyncMock(return_value={})), \
         patch('app.dependencies.get_document_analysis_service') as mock_svc_fn, \
         patch('app.orchestration.nodes.get_paperless_connector') as mock_paperless:

        mock_svc = MagicMock()
        mock_result = MagicMock()
        mock_result.model_dump.return_value = {'overall_confidence': 0.5, 'global_decision': 'ANALYZED'}
        mock_svc.analyze = AsyncMock(return_value=mock_result)
        mock_svc_fn.return_value = mock_svc

        mock_paperless.return_value.get_document = AsyncMock(return_value={})

        result_state = await run_document_analyst(state)

    # Normal path was used — not e-invoice
    doc_analysis = result_state.get('document_analysis', {})
    assert doc_analysis.get('analysis_version') != 'e-invoice-v1'


@pytest.mark.asyncio
async def test_run_document_analyst_e_invoice_parse_failure_falls_through():
    """If e-invoice parsing fails, fall through to normal analysis (no crash)."""
    from unittest.mock import AsyncMock, MagicMock, patch

    from app.orchestration.nodes import run_document_analyst

    # Broken XML — detect_e_invoice returns XRECHNUNG but parse_xrechnung raises
    broken_cii_xml = (
        b'<?xml version="1.0"?>'
        b'<rsm:CrossIndustryInvoice'
        b' xmlns:rsm="urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100"'
        b' xmlns:ram="urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100"'
        b' xmlns:udt="urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100">'
        b'<not-closed>'  # malformed
    )

    state: dict = {
        'case_id': 'fallthrough-test',
        'source': 'test',
        'pdf_bytes': broken_cii_xml,
        'ocr_text': 'Rechnung',
    }

    mock_svc = MagicMock()
    mock_result = MagicMock()
    mock_result.model_dump.return_value = {
        'overall_confidence': 0.5,
        'global_decision': 'ANALYZED',
        'analysis_version': 'document-analyst-v1',
    }
    mock_svc.analyze = AsyncMock(return_value=mock_result)

    with patch('app.orchestration.nodes._build_document_context', new=AsyncMock(return_value={})), \
         patch('app.orchestration.nodes.get_document_analysis_service', return_value=mock_svc), \
         patch('app.orchestration.nodes.get_paperless_connector') as mock_paperless:

        mock_paperless.return_value.get_document = AsyncMock(return_value={})

        # Must not raise — falls through to normal analysis
        result_state = await run_document_analyst(state)

    assert 'document_analysis' in result_state
    # Normal service was called (not e-invoice path)
    mock_svc.analyze.assert_called_once()
