"""E-Rechnung parser: ZUGFeRD (Factur-X) and XRechnung (UBL / CII).

Supported formats:
- ZUGFeRD v1 / v2 / Factur-X: PDF with embedded XML attachment
- XRechnung CII: Cross-Industry-Invoice XML (urn:un:unece:uncefact...)
- XRechnung UBL: UBL 2.1 Invoice XML (urn:oasis:names:specification:ubl...)

Usage:
    e_type = detect_e_invoice(pdf_bytes)
    if e_type is EInvoiceType.ZUGFERD_V2:
        data = parse_zugferd(pdf_bytes)
    elif e_type is EInvoiceType.XRECHNUNG:
        data = parse_xrechnung(xml_bytes)
"""
from __future__ import annotations

import io
from datetime import date
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class EInvoiceType(str, Enum):
    ZUGFERD_V1 = 'ZUGFERD_V1'
    ZUGFERD_V2 = 'ZUGFERD_V2'
    XRECHNUNG = 'XRECHNUNG'


class EInvoiceLineItem(BaseModel):
    description: str = ''
    quantity: Decimal = Decimal('1')
    unit_price: Decimal = Decimal('0')
    net: Decimal = Decimal('0')
    tax_rate: Decimal = Decimal('0')
    tax: Decimal = Decimal('0')


class EInvoiceData(BaseModel):
    invoice_number: str | None = None
    invoice_date: date | None = None
    due_date: date | None = None
    seller_name: str | None = None
    seller_tax_id: str | None = None
    seller_address: str | None = None
    buyer_name: str | None = None
    buyer_tax_id: str | None = None
    line_items: list[EInvoiceLineItem] = Field(default_factory=list)
    total_net: Decimal | None = None
    total_tax: Decimal | None = None
    total_gross: Decimal | None = None
    currency: str = 'EUR'
    payment_terms: str | None = None
    iban: str | None = None
    bic: str | None = None
    reference: str | None = None
    note: str | None = None
    e_invoice_type: EInvoiceType | None = None


# ─────────────────────────────────────────────────────────────────────
# Namespace maps
# ─────────────────────────────────────────────────────────────────────

_NS_CII: dict[str, str] = {
    'rsm': 'urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100',
    'ram': 'urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100',
    'udt': 'urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100',
}

_NS_UBL: dict[str, str] = {
    'inv': 'urn:oasis:names:specification:ubl:schema:xsd:Invoice-2',
    'cac': 'urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2',
    'cbc': 'urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2',
}


# ─────────────────────────────────────────────────────────────────────
# Detection
# ─────────────────────────────────────────────────────────────────────

def detect_e_invoice(pdf_bytes: bytes) -> EInvoiceType | None:
    """Detect whether bytes are a ZUGFeRD PDF or XRechnung XML.

    Uses byte-pattern heuristics first (fast path), then falls back to
    facturx library for PDFs with compressed XML attachments.
    Returns None when content is not a recognised e-invoice format.
    """
    if not pdf_bytes:
        return None

    is_pdf = pdf_bytes[:4] == b'%PDF'

    if is_pdf:
        # Fast path: Embedded-XML attachment name found in raw PDF stream
        if b'factur-x.xml' in pdf_bytes:
            return EInvoiceType.ZUGFERD_V2
        if b'ZUGFeRD-invoice.xml' in pdf_bytes or b'zugferd-invoice.xml' in pdf_bytes:
            # ZUGFeRD v2 uses factur-x namespace; v1 uses zugferd namespace
            if b'urn:zugferd' in pdf_bytes:
                return EInvoiceType.ZUGFERD_V1
            return EInvoiceType.ZUGFERD_V2
        # Broader Factur-X / ZUGFeRD v2 detection via profile namespace
        if b'urn:factur-x.eu' in pdf_bytes or b'urn:cen.eu:en16931' in pdf_bytes:
            return EInvoiceType.ZUGFERD_V2
        # Fallback: XML may be compressed inside PDF streams — use facturx library
        try:
            import io as _io
            import facturx as _fx  # type: ignore[import-untyped]
            _result = _fx.get_facturx_xml_from_pdf(_io.BytesIO(pdf_bytes), check_xsd=False)
            if _result:
                return EInvoiceType.ZUGFERD_V2
        except Exception:
            pass
        return None

    # Not a PDF → check for raw XML e-invoice
    # CII (XRechnung / ZUGFeRD standalone XML)
    if b'CrossIndustryInvoice' in pdf_bytes and b'unece' in pdf_bytes:
        return EInvoiceType.XRECHNUNG
    # UBL Invoice
    if b'urn:oasis:names:specification:ubl' in pdf_bytes and b'Invoice' in pdf_bytes:
        return EInvoiceType.XRECHNUNG

    return None


# ─────────────────────────────────────────────────────────────────────
# Public parse functions
# ─────────────────────────────────────────────────────────────────────

def parse_zugferd(pdf_bytes: bytes) -> EInvoiceData:
    """Extract embedded XML from a ZUGFeRD / Factur-X PDF and parse it."""
    try:
        import facturx  # type: ignore[import-untyped]
    except ImportError as exc:
        raise ImportError('factur-x library required: pip install factur-x') from exc

    pdf_io = io.BytesIO(pdf_bytes)
    xml_attachments = facturx.get_facturx_xml_from_pdf(pdf_io, check_xsd=False)

    if not xml_attachments:
        raise ValueError('No XML attachment found in PDF')

    # facturx 2.x returns dict {filename: xml_bytes}; 1.x returns (filename, xml_bytes)
    if isinstance(xml_attachments, dict):
        xml_bytes = next(iter(xml_attachments.values()))
    elif isinstance(xml_attachments, tuple):
        xml_bytes = xml_attachments[1]
    else:
        xml_bytes = bytes(xml_attachments)

    data = parse_xrechnung(xml_bytes)
    data.e_invoice_type = EInvoiceType.ZUGFERD_V2
    return data


def parse_xrechnung(xml_bytes: bytes) -> EInvoiceData:
    """Parse XRechnung / Factur-X CII or UBL XML into EInvoiceData."""
    try:
        from lxml import etree
    except ImportError as exc:
        raise ImportError('lxml required: pip install lxml') from exc

    # Hardened parser: no external DTDs, no network access, no entity expansion.
    # This explicitly prevents XXE (XML External Entity) attacks.
    _safe_parser = etree.XMLParser(
        load_dtd=False,
        no_network=True,
        resolve_entities=False,
    )
    try:
        root = etree.fromstring(xml_bytes, _safe_parser)
    except etree.XMLSyntaxError as exc:
        raise ValueError(f'Invalid XML: {exc}') from exc

    tag: str = root.tag
    if 'CrossIndustryInvoice' in tag:
        return _parse_cii(root)
    if 'Invoice' in tag:
        return _parse_ubl(root)
    raise ValueError(f'Unknown e-invoice root element: {tag!r}')


# ─────────────────────────────────────────────────────────────────────
# CII parser
# ─────────────────────────────────────────────────────────────────────

def _x(node: Any, path: str, ns: dict[str, str]) -> str | None:
    result = node.xpath(path + '/text()', namespaces=ns)
    return str(result[0]).strip() if result else None


def _parse_cii(root: Any) -> EInvoiceData:
    ns = _NS_CII
    sctt = 'rsm:SupplyChainTradeTransaction'
    agreement = f'{sctt}/ram:ApplicableHeaderTradeAgreement'
    settlement = f'{sctt}/ram:ApplicableHeaderTradeSettlement'
    summation = f'{settlement}/ram:SpecifiedTradeSettlementHeaderMonetarySummation'

    invoice_number = _x(root, 'rsm:ExchangedDocument/ram:ID', ns)
    invoice_date = _parse_cii_date(_x(root, 'rsm:ExchangedDocument/ram:IssueDateTime/udt:DateTimeString', ns))

    seller_name = _x(root, f'{agreement}/ram:SellerTradeParty/ram:Name', ns)
    seller_tax_ids = root.xpath(f'{agreement}/ram:SellerTradeParty/ram:SpecifiedTaxRegistration/ram:ID/text()', namespaces=ns)
    seller_tax_id = str(seller_tax_ids[0]).strip() if seller_tax_ids else None

    addr_parts = []
    for field in ('ram:LineOne', 'ram:CityName', 'ram:PostcodeCode', 'ram:CountryID'):
        v = _x(root, f'{agreement}/ram:SellerTradeParty/ram:PostalTradeAddress/{field}', ns)
        if v:
            addr_parts.append(v)
    seller_address = ', '.join(addr_parts) or None

    buyer_name = _x(root, f'{agreement}/ram:BuyerTradeParty/ram:Name', ns)
    buyer_tax_ids = root.xpath(f'{agreement}/ram:BuyerTradeParty/ram:SpecifiedTaxRegistration/ram:ID/text()', namespaces=ns)
    buyer_tax_id = str(buyer_tax_ids[0]).strip() if buyer_tax_ids else None

    currency = _x(root, f'{settlement}/ram:InvoiceCurrencyCode', ns) or 'EUR'
    reference = _x(root, f'{settlement}/ram:PaymentReference', ns)
    payment_terms = _x(root, f'{settlement}/ram:SpecifiedTradePaymentTerms/ram:Description', ns)
    due_date = _parse_cii_date(_x(root, f'{settlement}/ram:SpecifiedTradePaymentTerms/ram:DueDateDateTime/udt:DateTimeString', ns))

    total_net = _dec(_x(root, f'{summation}/ram:TaxBasisTotalAmount', ns))
    total_tax_els = root.xpath(f'{summation}/ram:TaxTotalAmount/text()', namespaces=ns)
    total_tax = _dec(str(total_tax_els[0]).strip()) if total_tax_els else None
    total_gross = _dec(_x(root, f'{summation}/ram:GrandTotalAmount', ns))

    iban = _x(root, f'{settlement}/ram:SpecifiedTradeSettlementPaymentMeans/ram:PayeePartyCreditorFinancialAccount/ram:IBANID', ns)
    bic = _x(root, f'{settlement}/ram:SpecifiedTradeSettlementPaymentMeans/ram:PayeeSpecifiedCreditorFinancialInstitution/ram:BICID', ns)
    note = _x(root, 'rsm:ExchangedDocument/ram:IncludedNote/ram:Content', ns)

    line_items = [
        item
        for el in root.xpath(f'{sctt}/ram:IncludedSupplyChainTradeLineItem', namespaces=ns)
        if (item := _parse_cii_line(el, ns)) is not None
    ]

    return EInvoiceData(
        invoice_number=invoice_number,
        invoice_date=invoice_date,
        due_date=due_date,
        seller_name=seller_name,
        seller_tax_id=seller_tax_id,
        seller_address=seller_address,
        buyer_name=buyer_name,
        buyer_tax_id=buyer_tax_id,
        line_items=line_items,
        total_net=total_net,
        total_tax=total_tax,
        total_gross=total_gross,
        currency=currency,
        payment_terms=payment_terms,
        iban=iban,
        bic=bic,
        reference=reference,
        note=note,
        e_invoice_type=EInvoiceType.XRECHNUNG,
    )


def _parse_cii_line(el: Any, ns: dict[str, str]) -> EInvoiceLineItem | None:
    desc_els = el.xpath('ram:SpecifiedTradeProduct/ram:Name/text()', namespaces=ns)
    qty_els = el.xpath('ram:SpecifiedLineTradeDelivery/ram:BilledQuantity/text()', namespaces=ns)
    price_els = el.xpath('ram:SpecifiedLineTradeAgreement/ram:NetPriceProductTradePrice/ram:ChargeAmount/text()', namespaces=ns)
    net_els = el.xpath('ram:SpecifiedLineTradeSettlement/ram:SpecifiedTradeSettlementLineMonetarySummation/ram:LineTotalAmount/text()', namespaces=ns)
    tax_rate_els = el.xpath('ram:SpecifiedLineTradeSettlement/ram:ApplicableTradeTax/ram:RateApplicablePercent/text()', namespaces=ns)

    net = _dec(str(net_els[0]).strip()) or Decimal('0')
    tax_rate = _dec(str(tax_rate_els[0]).strip()) or Decimal('0') if tax_rate_els else Decimal('0')
    tax = (net * tax_rate / Decimal('100')).quantize(Decimal('0.01'))

    return EInvoiceLineItem(
        description=str(desc_els[0]).strip() if desc_els else '',
        quantity=_dec(str(qty_els[0]).strip()) or Decimal('1') if qty_els else Decimal('1'),
        unit_price=_dec(str(price_els[0]).strip()) or Decimal('0') if price_els else Decimal('0'),
        net=net,
        tax_rate=tax_rate,
        tax=tax,
    )


# ─────────────────────────────────────────────────────────────────────
# UBL parser
# ─────────────────────────────────────────────────────────────────────

def _parse_ubl(root: Any) -> EInvoiceData:
    ns = _NS_UBL

    invoice_number = _x(root, 'cbc:ID', ns)
    invoice_date = _parse_iso_date(_x(root, 'cbc:IssueDate', ns))
    due_date = _parse_iso_date(_x(root, 'cbc:DueDate', ns))
    currency = _x(root, 'cbc:DocumentCurrencyCode', ns) or 'EUR'
    note = _x(root, 'cbc:Note', ns)

    seller_name = _x(root, 'cac:AccountingSupplierParty/cac:Party/cac:PartyName/cbc:Name', ns)
    seller_tax_id = _x(root, 'cac:AccountingSupplierParty/cac:Party/cac:PartyTaxScheme/cbc:CompanyID', ns)

    addr_parts = []
    for field in ('cbc:StreetName', 'cbc:CityName', 'cbc:PostalZone', 'cac:Country/cbc:IdentificationCode'):
        v = _x(root, f'cac:AccountingSupplierParty/cac:Party/cac:PostalAddress/{field}', ns)
        if v:
            addr_parts.append(v)
    seller_address = ', '.join(addr_parts) or None

    buyer_name = _x(root, 'cac:AccountingCustomerParty/cac:Party/cac:PartyName/cbc:Name', ns)
    buyer_tax_id = _x(root, 'cac:AccountingCustomerParty/cac:Party/cac:PartyTaxScheme/cbc:CompanyID', ns)

    reference = _x(root, 'cbc:BuyerReference', ns) or _x(root, 'cac:OrderReference/cbc:ID', ns)
    iban = _x(root, 'cac:PaymentMeans/cac:PayeeFinancialAccount/cbc:ID', ns)
    payment_terms = _x(root, 'cac:PaymentTerms/cbc:Note', ns)

    total_net = _dec(_x(root, 'cac:LegalMonetaryTotal/cbc:TaxExclusiveAmount', ns))
    total_gross = _dec(_x(root, 'cac:LegalMonetaryTotal/cbc:TaxInclusiveAmount', ns))
    tax_total_els = root.xpath('cac:TaxTotal/cbc:TaxAmount/text()', namespaces=ns)
    total_tax = _dec(str(tax_total_els[0]).strip()) if tax_total_els else None

    line_items = [
        item
        for el in root.xpath('cac:InvoiceLine', namespaces=ns)
        if (item := _parse_ubl_line(el, ns)) is not None
    ]

    return EInvoiceData(
        invoice_number=invoice_number,
        invoice_date=invoice_date,
        due_date=due_date,
        seller_name=seller_name,
        seller_tax_id=seller_tax_id,
        seller_address=seller_address,
        buyer_name=buyer_name,
        buyer_tax_id=buyer_tax_id,
        line_items=line_items,
        total_net=total_net,
        total_tax=total_tax,
        total_gross=total_gross,
        currency=currency,
        payment_terms=payment_terms,
        iban=iban,
        bic=None,
        reference=reference,
        note=note,
        e_invoice_type=EInvoiceType.XRECHNUNG,
    )


def _parse_ubl_line(el: Any, ns: dict[str, str]) -> EInvoiceLineItem | None:
    desc_els = el.xpath('cac:Item/cbc:Description/text()', namespaces=ns) or el.xpath('cac:Item/cbc:Name/text()', namespaces=ns)
    qty_els = el.xpath('cbc:InvoicedQuantity/text()', namespaces=ns)
    price_els = el.xpath('cac:Price/cbc:PriceAmount/text()', namespaces=ns)
    net_els = el.xpath('cbc:LineExtensionAmount/text()', namespaces=ns)
    tax_rate_els = el.xpath('cac:Item/cac:ClassifiedTaxCategory/cbc:Percent/text()', namespaces=ns)

    net = _dec(str(net_els[0]).strip()) or Decimal('0') if net_els else Decimal('0')
    tax_rate = _dec(str(tax_rate_els[0]).strip()) or Decimal('0') if tax_rate_els else Decimal('0')
    tax = (net * tax_rate / Decimal('100')).quantize(Decimal('0.01'))

    return EInvoiceLineItem(
        description=str(desc_els[0]).strip() if desc_els else '',
        quantity=_dec(str(qty_els[0]).strip()) or Decimal('1') if qty_els else Decimal('1'),
        unit_price=_dec(str(price_els[0]).strip()) or Decimal('0') if price_els else Decimal('0'),
        net=net,
        tax_rate=tax_rate,
        tax=tax,
    )


# ─────────────────────────────────────────────────────────────────────
# DocumentAnalysisResult conversion
# ─────────────────────────────────────────────────────────────────────

def e_invoice_to_document_analysis_result(
    data: EInvoiceData,
    *,
    case_id: str,
    document_ref: str | None = None,
    event_source: str = 'e_invoice',
) -> Any:
    """Convert EInvoiceData to DocumentAnalysisResult with confidence=1.0.

    Machine-readable XML data is treated as ground truth — no LLM needed.
    """
    from app.document_analysis.models import (
        DetectedAmount,
        DocumentAnalysisResult,
        ExtractedField,
    )

    amounts: list[DetectedAmount] = []
    if data.total_net is not None:
        amounts.append(DetectedAmount(label='NET', amount=data.total_net, currency=data.currency, status='FOUND', confidence=1.0, source_kind='OCR_TEXT', evidence_excerpt='e-invoice XML'))
    if data.total_tax is not None:
        amounts.append(DetectedAmount(label='TAX', amount=data.total_tax, currency=data.currency, status='FOUND', confidence=1.0, source_kind='OCR_TEXT', evidence_excerpt='e-invoice XML'))
    if data.total_gross is not None:
        amounts.append(DetectedAmount(label='TOTAL', amount=data.total_gross, currency=data.currency, status='FOUND', confidence=1.0, source_kind='OCR_TEXT', evidence_excerpt='e-invoice XML'))

    references: list[ExtractedField] = []
    if data.invoice_number:
        references.append(ExtractedField(value=data.invoice_number, status='FOUND', confidence=1.0, source_kind='OCR_TEXT', evidence_excerpt='e-invoice XML', label='invoice_number'))
    if data.reference and data.reference != data.invoice_number:
        references.append(ExtractedField(value=data.reference, status='FOUND', confidence=1.0, source_kind='OCR_TEXT', evidence_excerpt='e-invoice XML', label='reference_number'))

    return DocumentAnalysisResult(
        analysis_version='e-invoice-v1',
        case_id=case_id,
        document_ref=document_ref,
        event_source=event_source,
        document_type=ExtractedField(value='INVOICE', status='FOUND', confidence=1.0, source_kind='OCR_TEXT', evidence_excerpt='E-Rechnung erkannt'),
        sender=ExtractedField(
            value=data.seller_name,
            status='FOUND' if data.seller_name else 'MISSING',
            confidence=1.0 if data.seller_name else 0.0,
            source_kind='OCR_TEXT',
            evidence_excerpt=data.seller_name or '',
        ),
        recipient=ExtractedField(
            value=data.buyer_name,
            status='FOUND' if data.buyer_name else 'MISSING',
            confidence=1.0 if data.buyer_name else 0.0,
            source_kind='OCR_TEXT',
            evidence_excerpt=data.buyer_name or '',
        ),
        amounts=amounts,
        currency=ExtractedField(value=data.currency, status='FOUND', confidence=1.0, source_kind='OCR_TEXT', evidence_excerpt=data.currency),
        document_date=ExtractedField(
            value=data.invoice_date,
            status='FOUND' if data.invoice_date else 'MISSING',
            confidence=1.0 if data.invoice_date else 0.0,
            source_kind='OCR_TEXT',
        ),
        due_date=ExtractedField(
            value=data.due_date,
            status='FOUND' if data.due_date else 'MISSING',
            confidence=1.0 if data.due_date else 0.0,
            source_kind='OCR_TEXT',
        ),
        references=references,
        risks=[],
        warnings=[],
        missing_fields=[],
        recommended_next_step='ACCOUNTING_REVIEW',
        global_decision='ANALYZED',
        ready_for_accounting_review=True,
        overall_confidence=1.0,
    )


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────

def _dec(value: str | None) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(value.strip().replace(',', '.'))
    except (InvalidOperation, ValueError):
        return None


def _parse_cii_date(value: str | None) -> date | None:
    """Parse CII compact date 'YYYYMMDD' or ISO 'YYYY-MM-DD'."""
    if not value:
        return None
    v = value.strip()
    if len(v) == 8 and v.isdigit():
        try:
            return date(int(v[:4]), int(v[4:6]), int(v[6:8]))
        except ValueError:
            return None
    return _parse_iso_date(v)


def _parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None
