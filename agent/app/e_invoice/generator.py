"""E-Rechnung generator: ZUGFeRD (Factur-X) PDF and XRechnung CII XML.

Usage:
    xml_bytes = generate_xrechnung_xml(invoice_data)          # pure XML
    pdf_bytes = generate_zugferd_pdf(invoice_data)            # PDF + embedded XML
    pdf_bytes = generate_zugferd_pdf(invoice_data, base_pdf)  # embed into existing PDF
    pdf_bytes = embed_zugferd(pdf_bytes, invoice_data_dict)   # embed into existing PDF from dict
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.e_invoice.parser import EInvoiceData

logger = logging.getLogger(__name__)


def generate_xrechnung_xml(invoice_data: EInvoiceData) -> bytes:
    """Generate XRechnung CII XML (EN 16931 / Factur-X BASIC profile)."""
    return _build_cii_xml(invoice_data).encode('utf-8')


def generate_zugferd_pdf(invoice_data: EInvoiceData, base_pdf: bytes | None = None) -> bytes:
    """Embed ZUGFeRD XML into a PDF (BASIC profile).

    If base_pdf is None, a minimal placeholder PDF is generated automatically.
    Requires: pip install factur-x
    """
    try:
        import facturx  # type: ignore[import-untyped]
    except ImportError as exc:
        raise ImportError('factur-x library required: pip install factur-x') from exc

    xml_bytes = generate_xrechnung_xml(invoice_data)
    pdf_bytes = base_pdf or _build_minimal_pdf(
        company_name=invoice_data.seller_name or 'Unbekannt',
        invoice_number=invoice_data.invoice_number or 'unbekannt',
        total=f'{invoice_data.total_gross or 0} {invoice_data.currency}',
    )

    return facturx.generate_facturx_from_binary(
        pdf_bytes,
        xml_bytes,
        facturx_level='BASIC',
        check_xsd=False,
    )


# ─────────────────────────────────────────────────────────────────────
# ZUGFeRD embedding for outgoing invoices (from plain dict)
# ─────────────────────────────────────────────────────────────────────

def embed_zugferd(pdf_bytes: bytes, invoice_data: dict) -> bytes:
    """Embed ZUGFeRD/Factur-X XML into an existing PDF (EN 16931 BASIC profile).

    This function accepts a plain dict (from the invoice/PDF generation
    pipeline) rather than EInvoiceData, making it easy to call from
    PdfService or InvoiceService without importing the parser models.

    Args:
        pdf_bytes: Raw PDF bytes to embed the XML into.
        invoice_data: Dict with keys: seller_name, seller_tax_id,
            buyer_name, buyer_tax_id, invoice_number, invoice_date,
            due_date, net_amount, tax_amount, gross_amount, currency,
            iban, bic, items (list of dicts with description, quantity,
            unit_price, tax_rate, net_amount).

    Returns:
        PDF bytes with embedded ZUGFeRD XML attachment.

    Raises:
        ImportError: If factur-x library is not installed.
        ValueError: If PDF bytes are empty or invalid.
    """
    try:
        import facturx  # type: ignore[import-untyped]
    except ImportError as exc:
        raise ImportError('factur-x library required: pip install factur-x') from exc

    if not pdf_bytes:
        raise ValueError('Empty PDF bytes')

    xml_bytes = _build_zugferd_xml(invoice_data)

    return facturx.generate_facturx_from_binary(
        pdf_bytes,
        xml_bytes,
        facturx_level='BASIC',
        check_xsd=False,
    )


def _build_zugferd_xml(data: dict) -> bytes:
    """Build Factur-X CII XML (EN 16931 BASIC) from a plain invoice dict.

    Accepts the same field names used in the PDF generation pipeline.
    Returns UTF-8 encoded XML bytes.
    """
    from xml.sax.saxutils import escape

    def e(v: object) -> str:
        return escape(str(v)) if v is not None else ''

    def _fmt_date(d: object) -> str:
        if d is None:
            return ''
        if hasattr(d, 'strftime'):
            return d.strftime('%Y%m%d')  # type: ignore[union-attr]
        s = str(d).strip()
        # Handle DD.MM.YYYY format (German)
        if '.' in s and len(s) == 10:
            parts = s.split('.')
            if len(parts) == 3:
                return f'{parts[2]}{parts[1]}{parts[0]}'
        # Handle YYYY-MM-DD
        return s.replace('-', '')

    invoice_number = data.get('invoice_number', '')
    invoice_date = _fmt_date(data.get('invoice_date'))
    due_date = _fmt_date(data.get('due_date'))

    seller_name = data.get('seller_name') or data.get('company_name', '')
    seller_tax_id = data.get('seller_tax_id') or data.get('tax_id', '')
    buyer_name = data.get('buyer_name') or data.get('contact_name', '')
    buyer_tax_id = data.get('buyer_tax_id', '')
    currency = data.get('currency', 'EUR')

    net_amount = data.get('net_amount', 0)
    tax_amount = data.get('tax_amount', 0)
    gross_amount = data.get('gross_amount', 0)
    if not gross_amount and net_amount:
        gross_amount = float(net_amount) + float(tax_amount or 0)

    iban = data.get('iban', '')
    bic = data.get('bic', '')

    # Build line items XML
    lines_xml = ''
    items = data.get('items') or data.get('line_items') or []
    for i, item in enumerate(items, start=1):
        item_desc = item.get('description', '')
        item_qty = item.get('quantity', 1)
        item_price = item.get('unit_price', 0)
        item_tax_rate = item.get('tax_rate', 19)
        item_net = item.get('net_amount') or item.get('total_price', 0)
        lines_xml += f'''\
  <ram:IncludedSupplyChainTradeLineItem>
    <ram:AssociatedDocumentLineDocument>
      <ram:LineID>{i}</ram:LineID>
    </ram:AssociatedDocumentLineDocument>
    <ram:SpecifiedTradeProduct>
      <ram:Name>{e(item_desc)}</ram:Name>
    </ram:SpecifiedTradeProduct>
    <ram:SpecifiedLineTradeAgreement>
      <ram:NetPriceProductTradePrice>
        <ram:ChargeAmount>{item_price}</ram:ChargeAmount>
      </ram:NetPriceProductTradePrice>
    </ram:SpecifiedLineTradeAgreement>
    <ram:SpecifiedLineTradeDelivery>
      <ram:BilledQuantity unitCode="C62">{item_qty}</ram:BilledQuantity>
    </ram:SpecifiedLineTradeDelivery>
    <ram:SpecifiedLineTradeSettlement>
      <ram:ApplicableTradeTax>
        <ram:TypeCode>VAT</ram:TypeCode>
        <ram:CategoryCode>S</ram:CategoryCode>
        <ram:RateApplicablePercent>{item_tax_rate}</ram:RateApplicablePercent>
      </ram:ApplicableTradeTax>
      <ram:SpecifiedTradeSettlementLineMonetarySummation>
        <ram:LineTotalAmount>{item_net}</ram:LineTotalAmount>
      </ram:SpecifiedTradeSettlementLineMonetarySummation>
    </ram:SpecifiedLineTradeSettlement>
  </ram:IncludedSupplyChainTradeLineItem>
'''

    seller_tax_xml = f'<ram:SpecifiedTaxRegistration><ram:ID schemeID="VA">{e(seller_tax_id)}</ram:ID></ram:SpecifiedTaxRegistration>' if seller_tax_id else ''
    buyer_tax_xml = f'<ram:SpecifiedTaxRegistration><ram:ID schemeID="VA">{e(buyer_tax_id)}</ram:ID></ram:SpecifiedTaxRegistration>' if buyer_tax_id else ''
    iban_xml = f'<ram:PayeePartyCreditorFinancialAccount><ram:IBANID>{e(iban)}</ram:IBANID></ram:PayeePartyCreditorFinancialAccount>' if iban else ''
    bic_xml = f'<ram:PayeeSpecifiedCreditorFinancialInstitution><ram:BICID>{e(bic)}</ram:BICID></ram:PayeeSpecifiedCreditorFinancialInstitution>' if bic else ''
    due_date_xml = ''
    if due_date:
        due_date_xml = f'<ram:SpecifiedTradePaymentTerms><ram:DueDateDateTime><udt:DateTimeString format="102">{due_date}</udt:DateTimeString></ram:DueDateDateTime></ram:SpecifiedTradePaymentTerms>'

    xml_str = f'''<?xml version="1.0" encoding="UTF-8"?>
<rsm:CrossIndustryInvoice
  xmlns:rsm="urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100"
  xmlns:ram="urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100"
  xmlns:udt="urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100">
  <rsm:ExchangedDocumentContext>
    <ram:GuidelineSpecifiedDocumentContextParameter>
      <ram:ID>urn:cen.eu:en16931:2017#compliant#urn:factur-x.eu:1p0:basic</ram:ID>
    </ram:GuidelineSpecifiedDocumentContextParameter>
  </rsm:ExchangedDocumentContext>
  <rsm:ExchangedDocument>
    <ram:ID>{e(invoice_number)}</ram:ID>
    <ram:TypeCode>380</ram:TypeCode>
    <ram:IssueDateTime>
      <udt:DateTimeString format="102">{invoice_date}</udt:DateTimeString>
    </ram:IssueDateTime>
  </rsm:ExchangedDocument>
  <rsm:SupplyChainTradeTransaction>
    <ram:ApplicableHeaderTradeAgreement>
      <ram:SellerTradeParty>
        <ram:Name>{e(seller_name)}</ram:Name>
        {seller_tax_xml}
      </ram:SellerTradeParty>
      <ram:BuyerTradeParty>
        <ram:Name>{e(buyer_name)}</ram:Name>
        {buyer_tax_xml}
      </ram:BuyerTradeParty>
    </ram:ApplicableHeaderTradeAgreement>
    <ram:ApplicableHeaderTradeDelivery/>
    <ram:ApplicableHeaderTradeSettlement>
      <ram:InvoiceCurrencyCode>{e(currency)}</ram:InvoiceCurrencyCode>
      <ram:SpecifiedTradeSettlementPaymentMeans>
        {iban_xml}
        {bic_xml}
      </ram:SpecifiedTradeSettlementPaymentMeans>
      {due_date_xml}
      <ram:ApplicableTradeTax>
        <ram:TypeCode>VAT</ram:TypeCode>
        <ram:CategoryCode>S</ram:CategoryCode>
        <ram:BasisAmount>{net_amount}</ram:BasisAmount>
        <ram:CalculatedAmount>{tax_amount}</ram:CalculatedAmount>
      </ram:ApplicableTradeTax>
      <ram:SpecifiedTradeSettlementHeaderMonetarySummation>
        <ram:LineTotalAmount>{net_amount}</ram:LineTotalAmount>
        <ram:TaxBasisTotalAmount>{net_amount}</ram:TaxBasisTotalAmount>
        <ram:TaxTotalAmount currencyID="{e(currency)}">{tax_amount}</ram:TaxTotalAmount>
        <ram:GrandTotalAmount>{gross_amount}</ram:GrandTotalAmount>
        <ram:DuePayableAmount>{gross_amount}</ram:DuePayableAmount>
      </ram:SpecifiedTradeSettlementHeaderMonetarySummation>
    </ram:ApplicableHeaderTradeSettlement>
{lines_xml}  </rsm:SupplyChainTradeTransaction>
</rsm:CrossIndustryInvoice>'''

    return xml_str.encode('utf-8')


# ─────────────────────────────────────────────────────────────────────
# CII XML builder (Factur-X BASIC / XRechnung) — from EInvoiceData
# ─────────────────────────────────────────────────────────────────────

def _build_cii_xml(data: EInvoiceData) -> str:
    from xml.sax.saxutils import escape

    def e(v: object) -> str:
        return escape(str(v)) if v is not None else ''

    def _fmt_date(d: object) -> str:
        if d is None:
            return ''
        if hasattr(d, 'strftime'):
            return d.strftime('%Y%m%d')  # type: ignore[union-attr]
        return str(d).replace('-', '')

    invoice_date = _fmt_date(data.invoice_date)
    due_date = _fmt_date(data.due_date)

    total_net = data.total_net or Decimal('0.00')
    total_tax = data.total_tax or Decimal('0.00')
    total_gross = data.total_gross if data.total_gross is not None else total_net + total_tax

    # Line items
    lines_xml = ''
    for i, item in enumerate(data.line_items, start=1):
        lines_xml += f'''\
  <ram:IncludedSupplyChainTradeLineItem>
    <ram:AssociatedDocumentLineDocument>
      <ram:LineID>{i}</ram:LineID>
    </ram:AssociatedDocumentLineDocument>
    <ram:SpecifiedTradeProduct>
      <ram:Name>{e(item.description)}</ram:Name>
    </ram:SpecifiedTradeProduct>
    <ram:SpecifiedLineTradeAgreement>
      <ram:NetPriceProductTradePrice>
        <ram:ChargeAmount>{item.unit_price}</ram:ChargeAmount>
      </ram:NetPriceProductTradePrice>
    </ram:SpecifiedLineTradeAgreement>
    <ram:SpecifiedLineTradeDelivery>
      <ram:BilledQuantity unitCode="C62">{item.quantity}</ram:BilledQuantity>
    </ram:SpecifiedLineTradeDelivery>
    <ram:SpecifiedLineTradeSettlement>
      <ram:ApplicableTradeTax>
        <ram:TypeCode>VAT</ram:TypeCode>
        <ram:CategoryCode>S</ram:CategoryCode>
        <ram:RateApplicablePercent>{item.tax_rate}</ram:RateApplicablePercent>
      </ram:ApplicableTradeTax>
      <ram:SpecifiedTradeSettlementLineMonetarySummation>
        <ram:LineTotalAmount>{item.net}</ram:LineTotalAmount>
      </ram:SpecifiedTradeSettlementLineMonetarySummation>
    </ram:SpecifiedLineTradeSettlement>
  </ram:IncludedSupplyChainTradeLineItem>
'''

    seller_tax_xml = f'<ram:SpecifiedTaxRegistration><ram:ID schemeID="VA">{e(data.seller_tax_id)}</ram:ID></ram:SpecifiedTaxRegistration>' if data.seller_tax_id else ''
    buyer_tax_xml = f'<ram:SpecifiedTaxRegistration><ram:ID schemeID="VA">{e(data.buyer_tax_id)}</ram:ID></ram:SpecifiedTaxRegistration>' if data.buyer_tax_id else ''
    reference_xml = f'<ram:PaymentReference>{e(data.reference)}</ram:PaymentReference>' if data.reference else ''
    note_xml = f'<ram:IncludedNote><ram:Content>{e(data.note)}</ram:Content></ram:IncludedNote>' if data.note else ''
    iban_xml = f'<ram:PayeePartyCreditorFinancialAccount><ram:IBANID>{e(data.iban)}</ram:IBANID></ram:PayeePartyCreditorFinancialAccount>' if data.iban else ''
    bic_xml = f'<ram:PayeeSpecifiedCreditorFinancialInstitution><ram:BICID>{e(data.bic)}</ram:BICID></ram:PayeeSpecifiedCreditorFinancialInstitution>' if data.bic else ''
    payment_terms_xml = f'<ram:SpecifiedTradePaymentTerms><ram:Description>{e(data.payment_terms)}</ram:Description></ram:SpecifiedTradePaymentTerms>' if data.payment_terms else ''
    due_date_xml = ''
    if due_date:
        due_date_xml = f'<ram:SpecifiedTradePaymentTerms><ram:DueDateDateTime><udt:DateTimeString format="102">{due_date}</udt:DateTimeString></ram:DueDateDateTime></ram:SpecifiedTradePaymentTerms>'

    return f'''<?xml version="1.0" encoding="UTF-8"?>
<rsm:CrossIndustryInvoice
  xmlns:rsm="urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100"
  xmlns:ram="urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100"
  xmlns:udt="urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100">
  <rsm:ExchangedDocumentContext>
    <ram:GuidelineSpecifiedDocumentContextParameter>
      <ram:ID>urn:cen.eu:en16931:2017#compliant#urn:factur-x.eu:1p0:basic</ram:ID>
    </ram:GuidelineSpecifiedDocumentContextParameter>
  </rsm:ExchangedDocumentContext>
  <rsm:ExchangedDocument>
    <ram:ID>{e(data.invoice_number)}</ram:ID>
    <ram:TypeCode>380</ram:TypeCode>
    <ram:IssueDateTime>
      <udt:DateTimeString format="102">{invoice_date}</udt:DateTimeString>
    </ram:IssueDateTime>
    {note_xml}
  </rsm:ExchangedDocument>
  <rsm:SupplyChainTradeTransaction>
    <ram:ApplicableHeaderTradeAgreement>
      <ram:SellerTradeParty>
        <ram:Name>{e(data.seller_name)}</ram:Name>
        {seller_tax_xml}
      </ram:SellerTradeParty>
      <ram:BuyerTradeParty>
        <ram:Name>{e(data.buyer_name)}</ram:Name>
        {buyer_tax_xml}
      </ram:BuyerTradeParty>
    </ram:ApplicableHeaderTradeAgreement>
    <ram:ApplicableHeaderTradeDelivery/>
    <ram:ApplicableHeaderTradeSettlement>
      <ram:InvoiceCurrencyCode>{e(data.currency)}</ram:InvoiceCurrencyCode>
      {reference_xml}
      <ram:SpecifiedTradeSettlementPaymentMeans>
        {iban_xml}
        {bic_xml}
      </ram:SpecifiedTradeSettlementPaymentMeans>
      {payment_terms_xml}
      {due_date_xml}
      <ram:ApplicableTradeTax>
        <ram:TypeCode>VAT</ram:TypeCode>
        <ram:CategoryCode>S</ram:CategoryCode>
        <ram:BasisAmount>{total_net}</ram:BasisAmount>
        <ram:CalculatedAmount>{total_tax}</ram:CalculatedAmount>
      </ram:ApplicableTradeTax>
      <ram:SpecifiedTradeSettlementHeaderMonetarySummation>
        <ram:LineTotalAmount>{total_net}</ram:LineTotalAmount>
        <ram:TaxBasisTotalAmount>{total_net}</ram:TaxBasisTotalAmount>
        <ram:TaxTotalAmount currencyID="{e(data.currency)}">{total_tax}</ram:TaxTotalAmount>
        <ram:GrandTotalAmount>{total_gross}</ram:GrandTotalAmount>
        <ram:DuePayableAmount>{total_gross}</ram:DuePayableAmount>
      </ram:SpecifiedTradeSettlementHeaderMonetarySummation>
    </ram:ApplicableHeaderTradeSettlement>
{lines_xml}  </rsm:SupplyChainTradeTransaction>
</rsm:CrossIndustryInvoice>'''


# ─────────────────────────────────────────────────────────────────────
# Minimal PDF builder (no external dependencies)
# ─────────────────────────────────────────────────────────────────────

def _build_minimal_pdf(company_name: str, invoice_number: str, total: str) -> bytes:
    """Create a minimal valid PDF for ZUGFeRD XML embedding.

    Content is placeholder text — the ZUGFeRD XML carries all structured data.
    """
    def _safe(s: str) -> str:
        return s.replace('(', r'\(').replace(')', r'\)').replace('\\', r'\\')[:80]

    content = (
        f'BT /F1 12 Tf 50 780 Td (Rechnung {_safe(invoice_number)}) Tj '
        f'0 -24 Td ({_safe(company_name)}) Tj '
        f'0 -24 Td (Betrag: {_safe(total)}) Tj ET'
    )
    content_bytes = content.encode('latin-1')

    header = b'%PDF-1.4\n'
    obj1 = b'1 0 obj\n<</Type /Catalog /Pages 2 0 R>>\nendobj\n'
    obj2 = b'2 0 obj\n<</Type /Pages /Kids [3 0 R] /Count 1>>\nendobj\n'
    obj3 = (
        b'3 0 obj\n<</Type /Page /MediaBox [0 0 595 842] /Parent 2 0 R'
        b' /Resources <</Font <</F1 <</Type /Font /Subtype /Type1 /BaseFont /Helvetica>>>>>>'
        b' /Contents 4 0 R>>\nendobj\n'
    )
    stream_len = len(content_bytes)
    obj4 = f'4 0 obj\n<</Length {stream_len}>>\nstream\n'.encode() + content_bytes + b'\nendstream\nendobj\n'

    objs = [obj1, obj2, obj3, obj4]
    offsets: list[int] = []
    pos = len(header)
    for obj in objs:
        offsets.append(pos)
        pos += len(obj)

    xref_pos = pos
    xref_lines = [f'xref\n0 {len(objs) + 1}\n', '0000000000 65535 f \n']
    for offset in offsets:
        xref_lines.append(f'{offset:010d} 00000 n \n')
    xref_bytes = ''.join(xref_lines).encode()

    trailer = f'trailer\n<</Size {len(objs) + 1} /Root 1 0 R>>\nstartxref\n{xref_pos}\n%%EOF\n'.encode()

    return b''.join([header] + objs + [xref_bytes, trailer])
