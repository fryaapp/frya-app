"""Tests for E-Rechnung generator: XRechnung XML and ZUGFeRD PDF."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

lxml = pytest.importorskip('lxml', reason='lxml not installed; run: pip install lxml')

from app.e_invoice.generator import _build_cii_xml, _build_minimal_pdf, generate_xrechnung_xml
from app.e_invoice.parser import EInvoiceData, EInvoiceLineItem


# ─────────────────────────────────────────────────────────────────────
# Fixture
# ─────────────────────────────────────────────────────────────────────

def _sample_invoice() -> EInvoiceData:
    return EInvoiceData(
        invoice_number='INV-2026-042',
        invoice_date=date(2026, 3, 19),
        due_date=date(2026, 4, 18),
        seller_name='FRYA GmbH',
        seller_tax_id='DE123456789',
        buyer_name='Musterkunde AG',
        buyer_tax_id='DE987654321',
        currency='EUR',
        total_net=Decimal('500.00'),
        total_tax=Decimal('95.00'),
        total_gross=Decimal('595.00'),
        payment_terms='30 Tage netto',
        iban='DE89370400440532013000',
        bic='COBADEFFXXX',
        reference='PO-2026-007',
        note='Vielen Dank fuer Ihren Auftrag.',
        line_items=[
            EInvoiceLineItem(
                description='Beratungsleistung',
                quantity=Decimal('5'),
                unit_price=Decimal('100.00'),
                net=Decimal('500.00'),
                tax_rate=Decimal('19'),
                tax=Decimal('95.00'),
            )
        ],
    )


# ─────────────────────────────────────────────────────────────────────
# XRechnung XML generation
# ─────────────────────────────────────────────────────────────────────

def test_generate_xrechnung_xml_returns_bytes():
    xml_bytes = generate_xrechnung_xml(_sample_invoice())
    assert isinstance(xml_bytes, bytes)
    assert len(xml_bytes) > 100


def test_generate_xrechnung_xml_is_valid():
    from lxml import etree
    xml_bytes = generate_xrechnung_xml(_sample_invoice())
    root = etree.fromstring(xml_bytes)
    assert root is not None


def test_generate_xrechnung_xml_root_element():
    from lxml import etree
    xml_bytes = generate_xrechnung_xml(_sample_invoice())
    root = etree.fromstring(xml_bytes)
    assert 'CrossIndustryInvoice' in root.tag


def test_generate_xrechnung_xml_has_invoice_number():
    xml_bytes = generate_xrechnung_xml(_sample_invoice())
    assert b'INV-2026-042' in xml_bytes


def test_generate_xrechnung_xml_has_seller():
    xml_bytes = generate_xrechnung_xml(_sample_invoice())
    assert b'FRYA GmbH' in xml_bytes


def test_generate_xrechnung_xml_has_buyer():
    xml_bytes = generate_xrechnung_xml(_sample_invoice())
    assert b'Musterkunde AG' in xml_bytes


def test_generate_xrechnung_xml_has_amounts():
    xml_bytes = generate_xrechnung_xml(_sample_invoice())
    assert b'500.00' in xml_bytes
    assert b'95.00' in xml_bytes
    assert b'595.00' in xml_bytes


def test_generate_xrechnung_xml_has_iban():
    xml_bytes = generate_xrechnung_xml(_sample_invoice())
    assert b'DE89370400440532013000' in xml_bytes


def test_generate_xrechnung_xml_has_bic():
    xml_bytes = generate_xrechnung_xml(_sample_invoice())
    assert b'COBADEFFXXX' in xml_bytes


def test_generate_xrechnung_xml_has_reference():
    xml_bytes = generate_xrechnung_xml(_sample_invoice())
    assert b'PO-2026-007' in xml_bytes


def test_generate_xrechnung_xml_has_line_items():
    from lxml import etree
    xml_bytes = generate_xrechnung_xml(_sample_invoice())
    root = etree.fromstring(xml_bytes)
    ns = {
        'rsm': 'urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100',
        'ram': 'urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100',
    }
    lines = root.xpath('rsm:SupplyChainTradeTransaction/ram:IncludedSupplyChainTradeLineItem', namespaces=ns)
    assert len(lines) == 1
    name_els = lines[0].xpath('ram:SpecifiedTradeProduct/ram:Name/text()', namespaces=ns)
    assert name_els[0] == 'Beratungsleistung'


def test_generate_xrechnung_xml_date_compact_format():
    xml_bytes = generate_xrechnung_xml(_sample_invoice())
    assert b'20260319' in xml_bytes  # invoice date as YYYYMMDD


def test_generate_xrechnung_xml_guideline_id():
    xml_bytes = generate_xrechnung_xml(_sample_invoice())
    assert b'urn:cen.eu:en16931' in xml_bytes


def test_generate_xrechnung_xml_cii_namespace():
    xml_bytes = generate_xrechnung_xml(_sample_invoice())
    assert b'CrossIndustryInvoice:100' in xml_bytes


def test_generate_xrechnung_xml_no_line_items_still_valid():
    from lxml import etree
    inv = _sample_invoice()
    inv.line_items = []
    xml_bytes = generate_xrechnung_xml(inv)
    root = etree.fromstring(xml_bytes)
    assert root is not None


def test_generate_xrechnung_xml_escapes_special_chars():
    inv = _sample_invoice()
    inv.seller_name = 'Müller & Söhne <GmbH>'
    xml_bytes = generate_xrechnung_xml(inv)
    assert b'&amp;' in xml_bytes
    assert b'&lt;' in xml_bytes
    # Raw < must not appear inside element values
    from lxml import etree
    etree.fromstring(xml_bytes)  # must not raise


def test_generate_xrechnung_xml_note():
    xml_bytes = generate_xrechnung_xml(_sample_invoice())
    assert b'Vielen Dank' in xml_bytes


def test_generate_xrechnung_xml_note_absent_when_none():
    inv = _sample_invoice()
    inv.note = None
    xml_bytes = generate_xrechnung_xml(inv)
    assert b'IncludedNote' not in xml_bytes


# ─────────────────────────────────────────────────────────────────────
# _build_cii_xml — round-trip check
# ─────────────────────────────────────────────────────────────────────

def test_build_cii_xml_round_trip_invoice_number():
    from lxml import etree
    from app.e_invoice.parser import parse_xrechnung
    inv = _sample_invoice()
    xml_str = _build_cii_xml(inv)
    parsed = parse_xrechnung(xml_str.encode('utf-8'))
    assert parsed.invoice_number == inv.invoice_number


def test_build_cii_xml_round_trip_seller():
    from app.e_invoice.parser import parse_xrechnung
    inv = _sample_invoice()
    parsed = parse_xrechnung(_build_cii_xml(inv).encode('utf-8'))
    assert parsed.seller_name == inv.seller_name


def test_build_cii_xml_round_trip_amounts():
    from app.e_invoice.parser import parse_xrechnung
    inv = _sample_invoice()
    parsed = parse_xrechnung(_build_cii_xml(inv).encode('utf-8'))
    assert parsed.total_gross == inv.total_gross
    assert parsed.total_net == inv.total_net
    assert parsed.total_tax == inv.total_tax


# ─────────────────────────────────────────────────────────────────────
# _build_minimal_pdf
# ─────────────────────────────────────────────────────────────────────

def test_build_minimal_pdf_is_pdf():
    pdf = _build_minimal_pdf('Seller GmbH', 'INV-001', '119.00 EUR')
    assert pdf[:4] == b'%PDF'


def test_build_minimal_pdf_has_eof():
    pdf = _build_minimal_pdf('Seller GmbH', 'INV-001', '119.00 EUR')
    assert b'%%EOF' in pdf


def test_build_minimal_pdf_contains_invoice_number():
    pdf = _build_minimal_pdf('Seller GmbH', 'INV-2026-TEST', '119.00 EUR')
    assert b'INV-2026-TEST' in pdf


def test_build_minimal_pdf_has_xref_table():
    pdf = _build_minimal_pdf('Seller', 'INV-1', '1.00 EUR')
    assert b'xref' in pdf
    assert b'startxref' in pdf


# ─────────────────────────────────────────────────────────────────────
# generate_zugferd_pdf (mocked facturx)
# ─────────────────────────────────────────────────────────────────────

def test_generate_zugferd_pdf_calls_facturx():
    mock_facturx = MagicMock()
    mock_facturx.generate_facturx_from_binary.return_value = b'%PDF-1.4 mock result'

    with patch.dict('sys.modules', {'facturx': mock_facturx}):
        from app.e_invoice import generator as gen_module
        import importlib
        importlib.reload(gen_module)
        result = gen_module.generate_zugferd_pdf(_sample_invoice())

    assert result == b'%PDF-1.4 mock result'
    mock_facturx.generate_facturx_from_binary.assert_called_once()


def test_generate_zugferd_pdf_uses_base_pdf_when_provided():
    mock_facturx = MagicMock()
    mock_facturx.generate_facturx_from_binary.return_value = b'%PDF-1.4 with xml'
    base_pdf = b'%PDF-1.4 existing pdf content'

    with patch.dict('sys.modules', {'facturx': mock_facturx}):
        from app.e_invoice import generator as gen_module
        import importlib
        importlib.reload(gen_module)
        gen_module.generate_zugferd_pdf(_sample_invoice(), base_pdf=base_pdf)

    call_args = mock_facturx.generate_facturx_from_binary.call_args
    assert call_args[0][0] == base_pdf


def test_generate_zugferd_pdf_no_facturx_raises():
    import sys
    original = sys.modules.pop('facturx', None)
    try:
        with patch.dict('sys.modules', {'facturx': None}):
            from app.e_invoice import generator as gen_module
            import importlib
            importlib.reload(gen_module)
            with pytest.raises(ImportError, match='factur-x'):
                gen_module.generate_zugferd_pdf(_sample_invoice())
    finally:
        if original is not None:
            sys.modules['facturx'] = original
