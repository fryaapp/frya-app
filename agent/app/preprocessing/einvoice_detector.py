"""E-Invoice detection for incoming PDF documents.

Detects ZUGFeRD / Factur-X / XRechnung embedded XML in PDF files and
extracts structured invoice data without requiring OCR.  Machine-readable
XML is treated as ground truth (confidence = 1.0).

Usage in the document-analysis pipeline:
    from app.preprocessing.einvoice_detector import extract_einvoice_data

    if content_type == "application/pdf":
        result = extract_einvoice_data(pdf_bytes)
        if result is not None:
            # Structured e-invoice data — skip OCR
            return result
"""
from __future__ import annotations

import logging
from typing import Any

from lxml import etree

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────
# Namespace constants
# ─────────────────────────────────────────────────────────────────────

_NS_CII = {
    'rsm': 'urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100',
    'ram': 'urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100',
    'udt': 'urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100',
}

_NS_UBL = {
    'inv': 'urn:oasis:names:specification:ubl:schema:xsd:Invoice-2',
    'cac': 'urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2',
    'cbc': 'urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2',
}

# Factur-X / ZUGFeRD conformance levels (from most to least complete)
_LEVEL_MAP = {
    'extended': 'EXTENDED',
    'en 16931': 'EN16931',
    'en16931': 'EN16931',
    'comfort': 'COMFORT',
    'basic': 'BASIC',
    'basicwl': 'BASIC_WL',
    'minimum': 'MINIMUM',
}


# ─────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────

def extract_einvoice_data(pdf_bytes: bytes) -> dict | None:
    """Extract structured invoice data from a ZUGFeRD / Factur-X PDF.

    Returns a dict with invoice fields if the PDF contains a valid
    e-invoice XML attachment, or None if no e-invoice is detected.

    The returned dict contains:
        source, level, invoice_number, issue_date, vendor_name,
        vendor_tax_id, total_gross, total_net, tax_amount, currency,
        line_items
    """
    if not pdf_bytes or pdf_bytes[:4] != b'%PDF':
        return None

    xml_bytes = _extract_xml_from_pdf(pdf_bytes)
    if xml_bytes is None:
        return None

    try:
        level = _detect_level_from_xml(xml_bytes)
        return _parse_xml(xml_bytes, level)
    except Exception as exc:
        logger.debug('E-invoice XML parsing failed: %s', exc)
        return None


# ─────────────────────────────────────────────────────────────────────
# XML extraction from PDF
# ─────────────────────────────────────────────────────────────────────

def _extract_xml_from_pdf(pdf_bytes: bytes) -> bytes | None:
    """Use factur-x library to extract embedded XML from a PDF."""
    try:
        from facturx import get_facturx_xml_from_pdf
    except ImportError:
        logger.warning('factur-x library not installed; e-invoice detection unavailable')
        return None

    import io
    try:
        result = get_facturx_xml_from_pdf(io.BytesIO(pdf_bytes), check_xsd=False)
    except Exception as exc:
        logger.debug('facturx XML extraction failed: %s', exc)
        return None

    if not result:
        return None

    # facturx 2.x returns dict {filename: xml_bytes}; 1.x returns (filename, xml_bytes)
    if isinstance(result, dict):
        return next(iter(result.values()), None)
    if isinstance(result, tuple):
        return result[1] if len(result) >= 2 else None
    return bytes(result) if result else None


def _detect_level_from_xml(xml_bytes: bytes) -> str:
    """Detect the Factur-X / ZUGFeRD conformance level from XML content."""
    lower = xml_bytes.lower()
    for key, level in _LEVEL_MAP.items():
        if key.encode() in lower:
            return level
    return 'BASIC'


# ─────────────────────────────────────────────────────────────────────
# XML parsing
# ─────────────────────────────────────────────────────────────────────

def _parse_xml(xml_bytes: bytes, level: str) -> dict:
    """Parse e-invoice XML (CII or UBL) into a structured dict.

    Returns dict with keys:
        source, level, invoice_number, issue_date, vendor_name,
        vendor_tax_id, total_gross, total_net, tax_amount, currency,
        line_items
    """
    # Hardened parser: no external DTDs, no network, no entity expansion (XXE protection)
    safe_parser = etree.XMLParser(
        load_dtd=False,
        no_network=True,
        resolve_entities=False,
    )
    root = etree.fromstring(xml_bytes, safe_parser)
    ns = _detect_namespace(root)

    tag: str = root.tag
    if 'CrossIndustryInvoice' in tag:
        return _parse_cii(root, ns, level)
    if 'Invoice' in tag:
        return _parse_ubl(root, ns, level)

    raise ValueError(f'Unknown e-invoice root element: {tag!r}')


def _detect_namespace(root: Any) -> dict[str, str]:
    """Detect whether the XML uses CII or UBL namespaces."""
    tag: str = root.tag
    if 'CrossIndustryInvoice' in tag or 'uncefact' in tag:
        return _NS_CII
    if 'Invoice' in tag and 'oasis' in tag:
        return _NS_UBL
    # Fallback: try to detect from child namespaces
    nsmap = dict(root.nsmap) if hasattr(root, 'nsmap') else {}
    for uri in nsmap.values():
        if uri and 'uncefact' in str(uri):
            return _NS_CII
        if uri and 'oasis' in str(uri):
            return _NS_UBL
    return _NS_CII


def _xpath_text(root: Any, ns: dict[str, str], xpath: str) -> str | None:
    """Extract text from a single XPath match, or None."""
    results = root.xpath(xpath + '/text()', namespaces=ns)
    return str(results[0]).strip() if results else None


# ─────────────────────────────────────────────────────────────────────
# CII (Cross-Industry Invoice) parser
# ─────────────────────────────────────────────────────────────────────

def _parse_cii(root: Any, ns: dict[str, str], level: str) -> dict:
    sctt = 'rsm:SupplyChainTradeTransaction'
    agreement = f'{sctt}/ram:ApplicableHeaderTradeAgreement'
    settlement = f'{sctt}/ram:ApplicableHeaderTradeSettlement'
    summation = f'{settlement}/ram:SpecifiedTradeSettlementHeaderMonetarySummation'

    invoice_number = _xpath_text(root, ns, 'rsm:ExchangedDocument/ram:ID')
    issue_date = _xpath_text(root, ns, 'rsm:ExchangedDocument/ram:IssueDateTime/udt:DateTimeString')

    vendor_name = _xpath_text(root, ns, f'{agreement}/ram:SellerTradeParty/ram:Name')
    tax_ids = root.xpath(
        f'{agreement}/ram:SellerTradeParty/ram:SpecifiedTaxRegistration/ram:ID/text()',
        namespaces=ns,
    )
    vendor_tax_id = str(tax_ids[0]).strip() if tax_ids else None

    currency = _xpath_text(root, ns, f'{settlement}/ram:InvoiceCurrencyCode') or 'EUR'

    total_net = _xpath_text(root, ns, f'{summation}/ram:TaxBasisTotalAmount')
    tax_els = root.xpath(f'{summation}/ram:TaxTotalAmount/text()', namespaces=ns)
    tax_amount = str(tax_els[0]).strip() if tax_els else None
    total_gross = _xpath_text(root, ns, f'{summation}/ram:GrandTotalAmount')

    line_items = _parse_line_items(root, ns)

    return {
        'source': 'zugferd',
        'level': level,
        'invoice_number': invoice_number,
        'issue_date': _normalize_date(issue_date),
        'vendor_name': vendor_name,
        'vendor_tax_id': vendor_tax_id,
        'total_gross': total_gross,
        'total_net': total_net,
        'tax_amount': tax_amount,
        'currency': currency,
        'line_items': line_items,
    }


# ─────────────────────────────────────────────────────────────────────
# UBL parser
# ─────────────────────────────────────────────────────────────────────

def _parse_ubl(root: Any, ns: dict[str, str], level: str) -> dict:
    invoice_number = _xpath_text(root, ns, 'cbc:ID')
    issue_date = _xpath_text(root, ns, 'cbc:IssueDate')

    vendor_name = _xpath_text(root, ns, 'cac:AccountingSupplierParty/cac:Party/cac:PartyName/cbc:Name')
    vendor_tax_id = _xpath_text(root, ns, 'cac:AccountingSupplierParty/cac:Party/cac:PartyTaxScheme/cbc:CompanyID')

    currency = _xpath_text(root, ns, 'cbc:DocumentCurrencyCode') or 'EUR'

    total_net = _xpath_text(root, ns, 'cac:LegalMonetaryTotal/cbc:TaxExclusiveAmount')
    tax_els = root.xpath('cac:TaxTotal/cbc:TaxAmount/text()', namespaces=ns)
    tax_amount = str(tax_els[0]).strip() if tax_els else None
    total_gross = _xpath_text(root, ns, 'cac:LegalMonetaryTotal/cbc:TaxInclusiveAmount')

    line_items = _parse_ubl_line_items(root, ns)

    return {
        'source': 'xrechnung',
        'level': level,
        'invoice_number': invoice_number,
        'issue_date': issue_date,
        'vendor_name': vendor_name,
        'vendor_tax_id': vendor_tax_id,
        'total_gross': total_gross,
        'total_net': total_net,
        'tax_amount': tax_amount,
        'currency': currency,
        'line_items': line_items,
    }


# ─────────────────────────────────────────────────────────────────────
# Line item parsers
# ─────────────────────────────────────────────────────────────────────

def _parse_line_items(root: Any, ns: dict[str, str]) -> list[dict]:
    """Parse CII line items."""
    items: list[dict] = []
    for el in root.xpath(
        'rsm:SupplyChainTradeTransaction/ram:IncludedSupplyChainTradeLineItem',
        namespaces=ns,
    ):
        desc_els = el.xpath('ram:SpecifiedTradeProduct/ram:Name/text()', namespaces=ns)
        qty_els = el.xpath('ram:SpecifiedLineTradeDelivery/ram:BilledQuantity/text()', namespaces=ns)
        price_els = el.xpath(
            'ram:SpecifiedLineTradeAgreement/ram:NetPriceProductTradePrice/ram:ChargeAmount/text()',
            namespaces=ns,
        )
        net_els = el.xpath(
            'ram:SpecifiedLineTradeSettlement/ram:SpecifiedTradeSettlementLineMonetarySummation/ram:LineTotalAmount/text()',
            namespaces=ns,
        )
        tax_rate_els = el.xpath(
            'ram:SpecifiedLineTradeSettlement/ram:ApplicableTradeTax/ram:RateApplicablePercent/text()',
            namespaces=ns,
        )

        items.append({
            'description': str(desc_els[0]).strip() if desc_els else '',
            'quantity': str(qty_els[0]).strip() if qty_els else '1',
            'unit_price': str(price_els[0]).strip() if price_els else '0',
            'net_amount': str(net_els[0]).strip() if net_els else '0',
            'tax_rate': str(tax_rate_els[0]).strip() if tax_rate_els else '0',
        })
    return items


def _parse_ubl_line_items(root: Any, ns: dict[str, str]) -> list[dict]:
    """Parse UBL line items."""
    items: list[dict] = []
    for el in root.xpath('cac:InvoiceLine', namespaces=ns):
        desc_els = (
            el.xpath('cac:Item/cbc:Description/text()', namespaces=ns)
            or el.xpath('cac:Item/cbc:Name/text()', namespaces=ns)
        )
        qty_els = el.xpath('cbc:InvoicedQuantity/text()', namespaces=ns)
        price_els = el.xpath('cac:Price/cbc:PriceAmount/text()', namespaces=ns)
        net_els = el.xpath('cbc:LineExtensionAmount/text()', namespaces=ns)
        tax_rate_els = el.xpath('cac:Item/cac:ClassifiedTaxCategory/cbc:Percent/text()', namespaces=ns)

        items.append({
            'description': str(desc_els[0]).strip() if desc_els else '',
            'quantity': str(qty_els[0]).strip() if qty_els else '1',
            'unit_price': str(price_els[0]).strip() if price_els else '0',
            'net_amount': str(net_els[0]).strip() if net_els else '0',
            'tax_rate': str(tax_rate_els[0]).strip() if tax_rate_els else '0',
        })
    return items


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────

def _normalize_date(value: str | None) -> str | None:
    """Normalize CII compact date (YYYYMMDD) to ISO format (YYYY-MM-DD)."""
    if not value:
        return None
    v = value.strip()
    if len(v) == 8 and v.isdigit():
        return f'{v[:4]}-{v[4:6]}-{v[6:8]}'
    return v
