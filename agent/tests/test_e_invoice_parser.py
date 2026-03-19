"""Tests for E-Rechnung parser: ZUGFeRD detection, CII + UBL field extraction."""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from app.e_invoice.parser import (
    EInvoiceData,
    EInvoiceType,
    _parse_cii_date,
    _parse_iso_date,
    detect_e_invoice,
    e_invoice_to_document_analysis_result,
)

lxml = pytest.importorskip('lxml', reason='lxml not installed; run: pip install lxml')


# ─────────────────────────────────────────────────────────────────────
# Fixtures
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
    <ram:ID>INV-2024-001</ram:ID>
    <ram:TypeCode>380</ram:TypeCode>
    <ram:IssueDateTime><udt:DateTimeString format="102">20240115</udt:DateTimeString></ram:IssueDateTime>
    <ram:IncludedNote><ram:Content>Testrechnung</ram:Content></ram:IncludedNote>
  </rsm:ExchangedDocument>
  <rsm:SupplyChainTradeTransaction>
    <ram:ApplicableHeaderTradeAgreement>
      <ram:SellerTradeParty>
        <ram:Name>Test GmbH</ram:Name>
        <ram:PostalTradeAddress>
          <ram:LineOne>Musterstrasse 1</ram:LineOne>
          <ram:CityName>Berlin</ram:CityName>
          <ram:PostcodeCode>10115</ram:PostcodeCode>
          <ram:CountryID>DE</ram:CountryID>
        </ram:PostalTradeAddress>
        <ram:SpecifiedTaxRegistration><ram:ID schemeID="VA">DE123456789</ram:ID></ram:SpecifiedTaxRegistration>
      </ram:SellerTradeParty>
      <ram:BuyerTradeParty>
        <ram:Name>Kaeufer GmbH</ram:Name>
        <ram:SpecifiedTaxRegistration><ram:ID schemeID="VA">DE987654321</ram:ID></ram:SpecifiedTaxRegistration>
      </ram:BuyerTradeParty>
    </ram:ApplicableHeaderTradeAgreement>
    <ram:ApplicableHeaderTradeDelivery/>
    <ram:ApplicableHeaderTradeSettlement>
      <ram:InvoiceCurrencyCode>EUR</ram:InvoiceCurrencyCode>
      <ram:PaymentReference>INV-REF-001</ram:PaymentReference>
      <ram:SpecifiedTradeSettlementPaymentMeans>
        <ram:PayeePartyCreditorFinancialAccount>
          <ram:IBANID>DE89370400440532013000</ram:IBANID>
        </ram:PayeePartyCreditorFinancialAccount>
        <ram:PayeeSpecifiedCreditorFinancialInstitution>
          <ram:BICID>COBADEFFXXX</ram:BICID>
        </ram:PayeeSpecifiedCreditorFinancialInstitution>
      </ram:SpecifiedTradeSettlementPaymentMeans>
      <ram:SpecifiedTradePaymentTerms>
        <ram:Description>30 Tage netto</ram:Description>
        <ram:DueDateDateTime><udt:DateTimeString format="102">20240215</udt:DateTimeString></ram:DueDateDateTime>
      </ram:SpecifiedTradePaymentTerms>
      <ram:SpecifiedTradeSettlementHeaderMonetarySummation>
        <ram:TaxBasisTotalAmount>100.00</ram:TaxBasisTotalAmount>
        <ram:TaxTotalAmount currencyID="EUR">19.00</ram:TaxTotalAmount>
        <ram:GrandTotalAmount>119.00</ram:GrandTotalAmount>
        <ram:DuePayableAmount>119.00</ram:DuePayableAmount>
      </ram:SpecifiedTradeSettlementHeaderMonetarySummation>
    </ram:ApplicableHeaderTradeSettlement>
    <ram:IncludedSupplyChainTradeLineItem>
      <ram:AssociatedDocumentLineDocument><ram:LineID>1</ram:LineID></ram:AssociatedDocumentLineDocument>
      <ram:SpecifiedTradeProduct><ram:Name>Test Produkt</ram:Name></ram:SpecifiedTradeProduct>
      <ram:SpecifiedLineTradeAgreement>
        <ram:NetPriceProductTradePrice><ram:ChargeAmount>100.00</ram:ChargeAmount></ram:NetPriceProductTradePrice>
      </ram:SpecifiedLineTradeAgreement>
      <ram:SpecifiedLineTradeDelivery><ram:BilledQuantity unitCode="C62">1.0</ram:BilledQuantity></ram:SpecifiedLineTradeDelivery>
      <ram:SpecifiedLineTradeSettlement>
        <ram:ApplicableTradeTax><ram:RateApplicablePercent>19.00</ram:RateApplicablePercent></ram:ApplicableTradeTax>
        <ram:SpecifiedTradeSettlementLineMonetarySummation><ram:LineTotalAmount>100.00</ram:LineTotalAmount></ram:SpecifiedTradeSettlementLineMonetarySummation>
      </ram:SpecifiedLineTradeSettlement>
    </ram:IncludedSupplyChainTradeLineItem>
  </rsm:SupplyChainTradeTransaction>
</rsm:CrossIndustryInvoice>'''

_UBL_XML = b'''\
<?xml version="1.0" encoding="UTF-8"?>
<Invoice
  xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
  xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
  xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
  <cbc:ID>UBL-2024-001</cbc:ID>
  <cbc:IssueDate>2024-01-20</cbc:IssueDate>
  <cbc:DueDate>2024-02-20</cbc:DueDate>
  <cbc:InvoiceTypeCode>380</cbc:InvoiceTypeCode>
  <cbc:DocumentCurrencyCode>EUR</cbc:DocumentCurrencyCode>
  <cbc:BuyerReference>PO-2024-42</cbc:BuyerReference>
  <cac:AccountingSupplierParty>
    <cac:Party>
      <cac:PartyName><cbc:Name>UBL Seller GmbH</cbc:Name></cac:PartyName>
      <cac:PartyTaxScheme><cbc:CompanyID>DE111222333</cbc:CompanyID></cac:PartyTaxScheme>
      <cac:PostalAddress>
        <cbc:StreetName>Hauptstrasse 10</cbc:StreetName>
        <cbc:CityName>Hamburg</cbc:CityName>
        <cbc:PostalZone>20095</cbc:PostalZone>
        <cac:Country><cbc:IdentificationCode>DE</cbc:IdentificationCode></cac:Country>
      </cac:PostalAddress>
    </cac:Party>
  </cac:AccountingSupplierParty>
  <cac:AccountingCustomerParty>
    <cac:Party>
      <cac:PartyName><cbc:Name>UBL Buyer GmbH</cbc:Name></cac:PartyName>
      <cac:PartyTaxScheme><cbc:CompanyID>DE444555666</cbc:CompanyID></cac:PartyTaxScheme>
    </cac:Party>
  </cac:AccountingCustomerParty>
  <cac:PaymentMeans>
    <cac:PayeeFinancialAccount><cbc:ID>DE75512108001245126199</cbc:ID></cac:PayeeFinancialAccount>
  </cac:PaymentMeans>
  <cac:TaxTotal>
    <cbc:TaxAmount currencyID="EUR">38.00</cbc:TaxAmount>
  </cac:TaxTotal>
  <cac:LegalMonetaryTotal>
    <cbc:LineExtensionAmount currencyID="EUR">200.00</cbc:LineExtensionAmount>
    <cbc:TaxExclusiveAmount currencyID="EUR">200.00</cbc:TaxExclusiveAmount>
    <cbc:TaxInclusiveAmount currencyID="EUR">238.00</cbc:TaxInclusiveAmount>
    <cbc:PayableAmount currencyID="EUR">238.00</cbc:PayableAmount>
  </cac:LegalMonetaryTotal>
  <cac:InvoiceLine>
    <cbc:ID>1</cbc:ID>
    <cbc:InvoicedQuantity unitCode="C62">2.0</cbc:InvoicedQuantity>
    <cbc:LineExtensionAmount currencyID="EUR">200.00</cbc:LineExtensionAmount>
    <cac:Item>
      <cbc:Description>UBL Produkt Alpha</cbc:Description>
      <cac:ClassifiedTaxCategory><cbc:Percent>19</cbc:Percent></cac:ClassifiedTaxCategory>
    </cac:Item>
    <cac:Price><cbc:PriceAmount currencyID="EUR">100.00</cbc:PriceAmount></cac:Price>
  </cac:InvoiceLine>
</Invoice>'''


# ─────────────────────────────────────────────────────────────────────
# detect_e_invoice
# ─────────────────────────────────────────────────────────────────────

def test_detect_e_invoice_plain_pdf_returns_none():
    plain_pdf = b'%PDF-1.4\nsome random content without xml attachment'
    assert detect_e_invoice(plain_pdf) is None


def test_detect_e_invoice_empty_returns_none():
    assert detect_e_invoice(b'') is None


def test_detect_e_invoice_zugferd_v2_facturx():
    fake_pdf = b'%PDF-1.4\nfactur-x.xml\nsome content'
    assert detect_e_invoice(fake_pdf) == EInvoiceType.ZUGFERD_V2


def test_detect_e_invoice_zugferd_v2_cen_namespace():
    fake_pdf = b'%PDF-1.4\nurn:cen.eu:en16931 some content'
    assert detect_e_invoice(fake_pdf) == EInvoiceType.ZUGFERD_V2


def test_detect_e_invoice_zugferd_v1():
    fake_pdf = b'%PDF-1.4\nZUGFeRD-invoice.xml\nurn:zugferd namespace'
    assert detect_e_invoice(fake_pdf) == EInvoiceType.ZUGFERD_V1


def test_detect_e_invoice_zugferd_v2_lowercase():
    fake_pdf = b'%PDF-1.4\nzugferd-invoice.xml\nsome content'
    assert detect_e_invoice(fake_pdf) == EInvoiceType.ZUGFERD_V2


def test_detect_e_invoice_xrechnung_cii():
    assert detect_e_invoice(_CII_XML) == EInvoiceType.XRECHNUNG


def test_detect_e_invoice_xrechnung_ubl():
    assert detect_e_invoice(_UBL_XML) == EInvoiceType.XRECHNUNG


def test_detect_e_invoice_random_bytes_returns_none():
    assert detect_e_invoice(b'\x00\x01\x02\x03random garbage') is None


# ─────────────────────────────────────────────────────────────────────
# parse_xrechnung — CII format
# ─────────────────────────────────────────────────────────────────────

def test_parse_xrechnung_cii_invoice_number():
    from app.e_invoice.parser import parse_xrechnung
    data = parse_xrechnung(_CII_XML)
    assert data.invoice_number == 'INV-2024-001'


def test_parse_xrechnung_cii_invoice_date():
    from app.e_invoice.parser import parse_xrechnung
    from datetime import date
    data = parse_xrechnung(_CII_XML)
    assert data.invoice_date == date(2024, 1, 15)


def test_parse_xrechnung_cii_due_date():
    from app.e_invoice.parser import parse_xrechnung
    from datetime import date
    data = parse_xrechnung(_CII_XML)
    assert data.due_date == date(2024, 2, 15)


def test_parse_xrechnung_cii_seller():
    from app.e_invoice.parser import parse_xrechnung
    data = parse_xrechnung(_CII_XML)
    assert data.seller_name == 'Test GmbH'
    assert data.seller_tax_id == 'DE123456789'
    assert 'Berlin' in (data.seller_address or '')


def test_parse_xrechnung_cii_buyer():
    from app.e_invoice.parser import parse_xrechnung
    data = parse_xrechnung(_CII_XML)
    assert data.buyer_name == 'Kaeufer GmbH'
    assert data.buyer_tax_id == 'DE987654321'


def test_parse_xrechnung_cii_amounts():
    from app.e_invoice.parser import parse_xrechnung
    data = parse_xrechnung(_CII_XML)
    assert data.total_net == Decimal('100.00')
    assert data.total_tax == Decimal('19.00')
    assert data.total_gross == Decimal('119.00')
    assert data.currency == 'EUR'


def test_parse_xrechnung_cii_payment():
    from app.e_invoice.parser import parse_xrechnung
    data = parse_xrechnung(_CII_XML)
    assert data.iban == 'DE89370400440532013000'
    assert data.bic == 'COBADEFFXXX'
    assert data.reference == 'INV-REF-001'
    assert data.payment_terms == '30 Tage netto'


def test_parse_xrechnung_cii_note():
    from app.e_invoice.parser import parse_xrechnung
    data = parse_xrechnung(_CII_XML)
    assert data.note == 'Testrechnung'


def test_parse_xrechnung_cii_line_items():
    from app.e_invoice.parser import parse_xrechnung
    data = parse_xrechnung(_CII_XML)
    assert len(data.line_items) == 1
    item = data.line_items[0]
    assert item.description == 'Test Produkt'
    assert item.quantity == Decimal('1.0')
    assert item.unit_price == Decimal('100.00')
    assert item.net == Decimal('100.00')
    assert item.tax_rate == Decimal('19.00')
    assert item.tax == Decimal('19.00')


def test_parse_xrechnung_cii_e_invoice_type():
    from app.e_invoice.parser import parse_xrechnung
    data = parse_xrechnung(_CII_XML)
    assert data.e_invoice_type == EInvoiceType.XRECHNUNG


def test_parse_xrechnung_invalid_xml_raises():
    from app.e_invoice.parser import parse_xrechnung
    with pytest.raises(ValueError, match='Invalid XML'):
        parse_xrechnung(b'not valid xml at all <')


def test_parse_xrechnung_unknown_root_raises():
    from app.e_invoice.parser import parse_xrechnung
    with pytest.raises(ValueError, match='Unknown e-invoice root element'):
        parse_xrechnung(b'<?xml version="1.0"?><UnknownRoot/>')


# ─────────────────────────────────────────────────────────────────────
# parse_xrechnung — UBL format
# ─────────────────────────────────────────────────────────────────────

def test_parse_xrechnung_ubl_invoice_number():
    from app.e_invoice.parser import parse_xrechnung
    data = parse_xrechnung(_UBL_XML)
    assert data.invoice_number == 'UBL-2024-001'


def test_parse_xrechnung_ubl_dates():
    from app.e_invoice.parser import parse_xrechnung
    from datetime import date
    data = parse_xrechnung(_UBL_XML)
    assert data.invoice_date == date(2024, 1, 20)
    assert data.due_date == date(2024, 2, 20)


def test_parse_xrechnung_ubl_seller():
    from app.e_invoice.parser import parse_xrechnung
    data = parse_xrechnung(_UBL_XML)
    assert data.seller_name == 'UBL Seller GmbH'
    assert data.seller_tax_id == 'DE111222333'
    assert 'Hamburg' in (data.seller_address or '')


def test_parse_xrechnung_ubl_buyer():
    from app.e_invoice.parser import parse_xrechnung
    data = parse_xrechnung(_UBL_XML)
    assert data.buyer_name == 'UBL Buyer GmbH'
    assert data.buyer_tax_id == 'DE444555666'


def test_parse_xrechnung_ubl_amounts():
    from app.e_invoice.parser import parse_xrechnung
    data = parse_xrechnung(_UBL_XML)
    assert data.total_net == Decimal('200.00')
    assert data.total_tax == Decimal('38.00')
    assert data.total_gross == Decimal('238.00')
    assert data.currency == 'EUR'


def test_parse_xrechnung_ubl_iban():
    from app.e_invoice.parser import parse_xrechnung
    data = parse_xrechnung(_UBL_XML)
    assert data.iban == 'DE75512108001245126199'


def test_parse_xrechnung_ubl_reference():
    from app.e_invoice.parser import parse_xrechnung
    data = parse_xrechnung(_UBL_XML)
    assert data.reference == 'PO-2024-42'


def test_parse_xrechnung_ubl_line_items():
    from app.e_invoice.parser import parse_xrechnung
    data = parse_xrechnung(_UBL_XML)
    assert len(data.line_items) == 1
    item = data.line_items[0]
    assert item.description == 'UBL Produkt Alpha'
    assert item.quantity == Decimal('2.0')
    assert item.unit_price == Decimal('100.00')
    assert item.net == Decimal('200.00')
    assert item.tax_rate == Decimal('19')
    assert item.tax == Decimal('38.00')


# ─────────────────────────────────────────────────────────────────────
# parse_zugferd (mocked facturx)
# ─────────────────────────────────────────────────────────────────────

def test_parse_zugferd_extracts_xml_and_parses():
    """parse_zugferd must extract embedded XML via facturx and parse it."""
    from app.e_invoice.parser import parse_zugferd

    fake_pdf = b'%PDF-1.4 fake content'

    mock_facturx = MagicMock()
    mock_facturx.get_facturx_xml_from_pdf.return_value = {'factur-x.xml': _CII_XML}

    with patch.dict('sys.modules', {'facturx': mock_facturx}):
        data = parse_zugferd(fake_pdf)

    assert data.invoice_number == 'INV-2024-001'
    assert data.seller_name == 'Test GmbH'
    assert data.e_invoice_type == EInvoiceType.ZUGFERD_V2


def test_parse_zugferd_handles_tuple_return():
    """Older facturx returns (filename, xml_bytes) tuple."""
    from app.e_invoice.parser import parse_zugferd

    mock_facturx = MagicMock()
    mock_facturx.get_facturx_xml_from_pdf.return_value = ('factur-x.xml', _CII_XML)

    with patch.dict('sys.modules', {'facturx': mock_facturx}):
        data = parse_zugferd(b'%PDF-1.4 test')

    assert data.invoice_number == 'INV-2024-001'


def test_parse_zugferd_no_facturx_raises():
    from app.e_invoice.parser import parse_zugferd
    import sys
    original = sys.modules.pop('facturx', None)
    try:
        with patch.dict('sys.modules', {'facturx': None}):
            with pytest.raises(ImportError, match='factur-x'):
                parse_zugferd(b'%PDF-1.4')
    finally:
        if original is not None:
            sys.modules['facturx'] = original


# ─────────────────────────────────────────────────────────────────────
# e_invoice_to_document_analysis_result
# ─────────────────────────────────────────────────────────────────────

def test_conversion_confidence_is_1():
    from app.e_invoice.parser import parse_xrechnung
    data = parse_xrechnung(_CII_XML)
    result = e_invoice_to_document_analysis_result(data, case_id='test-case')
    assert result.overall_confidence == 1.0


def test_conversion_global_decision_analyzed():
    from app.e_invoice.parser import parse_xrechnung
    data = parse_xrechnung(_CII_XML)
    result = e_invoice_to_document_analysis_result(data, case_id='test-case')
    assert result.global_decision == 'ANALYZED'


def test_conversion_document_type_invoice():
    from app.e_invoice.parser import parse_xrechnung
    data = parse_xrechnung(_CII_XML)
    result = e_invoice_to_document_analysis_result(data, case_id='test-case')
    assert result.document_type.value == 'INVOICE'
    assert result.document_type.confidence == 1.0


def test_conversion_ready_for_accounting_review():
    from app.e_invoice.parser import parse_xrechnung
    data = parse_xrechnung(_CII_XML)
    result = e_invoice_to_document_analysis_result(data, case_id='test-case')
    assert result.ready_for_accounting_review is True


def test_conversion_analysis_version():
    from app.e_invoice.parser import parse_xrechnung
    data = parse_xrechnung(_CII_XML)
    result = e_invoice_to_document_analysis_result(data, case_id='test-case')
    assert result.analysis_version == 'e-invoice-v1'


def test_conversion_amounts_mapped():
    from app.e_invoice.parser import parse_xrechnung
    data = parse_xrechnung(_CII_XML)
    result = e_invoice_to_document_analysis_result(data, case_id='test-case')
    labels = {a.label for a in result.amounts}
    assert 'TOTAL' in labels
    assert 'NET' in labels
    assert 'TAX' in labels
    total = next(a for a in result.amounts if a.label == 'TOTAL')
    assert total.amount == Decimal('119.00')
    assert total.confidence == 1.0


def test_conversion_references_include_invoice_number():
    from app.e_invoice.parser import parse_xrechnung
    data = parse_xrechnung(_CII_XML)
    result = e_invoice_to_document_analysis_result(data, case_id='test-case')
    ref_values = [r.value for r in result.references]
    assert 'INV-2024-001' in ref_values


def test_conversion_no_risks():
    from app.e_invoice.parser import parse_xrechnung
    data = parse_xrechnung(_CII_XML)
    result = e_invoice_to_document_analysis_result(data, case_id='test-case')
    assert result.risks == []


def test_conversion_sender_from_seller():
    from app.e_invoice.parser import parse_xrechnung
    data = parse_xrechnung(_CII_XML)
    result = e_invoice_to_document_analysis_result(data, case_id='test-case')
    assert result.sender.value == 'Test GmbH'
    assert result.sender.status == 'FOUND'


# ─────────────────────────────────────────────────────────────────────
# Helper functions
# ─────────────────────────────────────────────────────────────────────

def test_parse_cii_date_compact():
    from datetime import date
    assert _parse_cii_date('20240315') == date(2024, 3, 15)


def test_parse_cii_date_iso():
    from datetime import date
    assert _parse_cii_date('2024-03-15') == date(2024, 3, 15)


def test_parse_cii_date_none():
    assert _parse_cii_date(None) is None
    assert _parse_cii_date('') is None


def test_parse_iso_date():
    from datetime import date
    assert _parse_iso_date('2024-12-31') == date(2024, 12, 31)
    assert _parse_iso_date(None) is None
    assert _parse_iso_date('not-a-date') is None
