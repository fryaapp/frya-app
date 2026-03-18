"""Unit tests for risk_analyst/rules.py — each rule tested independently.

Positive (finding) and negative (OK) cases for all five checks.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from app.risk_analyst.rules import (
    check_amount_consistency,
    check_booking_plausibility,
    check_duplicate_detection,
    check_tax_plausibility,
    check_vendor_consistency,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _case(
    vendor_name: str | None = 'Lieferant GmbH',
    total_amount: Decimal | None = Decimal('1190.00'),
    metadata: dict | None = None,
    status: str = 'OPEN',
    days_ago: int = 0,
) -> MagicMock:
    c = MagicMock()
    c.id = uuid.uuid4()
    c.tenant_id = uuid.uuid4()
    c.case_number = 'CASE-2026-00001'
    c.vendor_name = vendor_name
    c.total_amount = total_amount
    c.currency = 'EUR'
    c.status = status
    c.created_at = datetime.utcnow() - timedelta(days=days_ago)
    c.metadata = metadata or {}
    return c


def _doc(metadata: dict | None = None) -> MagicMock:
    d = MagicMock()
    d.metadata = metadata or {}
    return d


# ---------------------------------------------------------------------------
# a) amount_consistency
# ---------------------------------------------------------------------------

def test_amount_ok_no_comparison_data():
    case = _case(total_amount=Decimal('1190.00'))
    result = check_amount_consistency(case, [])
    assert result.severity == 'OK'


def test_amount_ok_consistent_doc():
    doc = _doc({'gross_amount': '1190.00'})
    case = _case(total_amount=Decimal('1190.00'))
    result = check_amount_consistency(case, [doc])
    assert result.severity == 'OK'


def test_amount_medium_deviation_over_1pct():
    # Case: 1190.00, doc: 1200.00 → ~0.84% > 1%? No: (1200-1190)/1200=0.83%
    # Let's make it clearly over 1%: case=1000, doc=989 → 11/989=1.11%
    doc = _doc({'gross_amount': '989.00'})
    case = _case(total_amount=Decimal('1000.00'))
    result = check_amount_consistency(case, [doc])
    assert result.severity == 'MEDIUM'


def test_amount_high_deviation_over_10pct():
    doc = _doc({'gross_amount': '500.00'})
    case = _case(total_amount=Decimal('1190.00'))
    result = check_amount_consistency(case, [doc])
    assert result.severity == 'HIGH'
    assert '1190' in result.finding


def test_amount_no_case_amount_is_ok():
    case = _case(total_amount=None)
    result = check_amount_consistency(case, [])
    assert result.severity == 'OK'


def test_amount_from_booking_proposal_metadata():
    meta = {'booking_proposal': {'gross_amount': '500.00'}}
    case = _case(total_amount=Decimal('1190.00'), metadata=meta)
    result = check_amount_consistency(case, [])
    assert result.severity == 'HIGH'


def test_amount_from_document_analysis_metadata():
    meta = {'document_analysis': {'gross_amount': '1180.00'}}
    # 1190 vs 1180 → 10/1180 = 0.847% < 1% → OK
    case = _case(total_amount=Decimal('1190.00'), metadata=meta)
    result = check_amount_consistency(case, [])
    assert result.severity == 'OK'


# ---------------------------------------------------------------------------
# b) duplicate_detection
# ---------------------------------------------------------------------------

def _same_tenant_cases(tenant_id: uuid.UUID, *, n: int = 3) -> list[MagicMock]:
    cases = []
    for _ in range(n):
        c = _case()
        c.tenant_id = tenant_id
        cases.append(c)
    return cases


def test_duplicate_ok_no_matches():
    case = _case(vendor_name='ACME GmbH', total_amount=Decimal('500.00'))
    other = _case(vendor_name='ACME GmbH', total_amount=Decimal('999.00'))
    other.tenant_id = case.tenant_id
    result = check_duplicate_detection(case, [other])
    assert result.severity == 'OK'


def test_duplicate_high_same_vendor_amount_date():
    tid = uuid.uuid4()
    case = _case(vendor_name='ACME GmbH', total_amount=Decimal('500.00'))
    case.tenant_id = tid
    dup = _case(vendor_name='ACME GmbH', total_amount=Decimal('500.00'), days_ago=3)
    dup.tenant_id = tid
    result = check_duplicate_detection(case, [dup])
    assert result.severity == 'HIGH'
    assert 'Duplikat' in result.finding


def test_duplicate_skips_self():
    case = _case(vendor_name='ACME GmbH', total_amount=Decimal('500.00'))
    result = check_duplicate_detection(case, [case])  # case itself
    assert result.severity == 'OK'


def test_duplicate_date_too_old():
    tid = uuid.uuid4()
    case = _case(vendor_name='ACME GmbH', total_amount=Decimal('500.00'))
    case.tenant_id = tid
    old = _case(vendor_name='ACME GmbH', total_amount=Decimal('500.00'), days_ago=10)
    old.tenant_id = tid
    result = check_duplicate_detection(case, [old])
    assert result.severity == 'OK'


def test_duplicate_different_tenant_ignored():
    case = _case(vendor_name='ACME GmbH', total_amount=Decimal('500.00'))
    dup = _case(vendor_name='ACME GmbH', total_amount=Decimal('500.00'))
    # Different tenant_id
    result = check_duplicate_detection(case, [dup])
    assert result.severity == 'OK'


def test_duplicate_ok_no_vendor():
    case = _case(vendor_name=None, total_amount=Decimal('500.00'))
    result = check_duplicate_detection(case, [])
    assert result.severity == 'OK'


# ---------------------------------------------------------------------------
# c) tax_plausibility
# ---------------------------------------------------------------------------

def _bp(tax_rate=19.0, net='1000.00', tax='190.00', gross='1190.00') -> dict:
    return {
        'skr03_soll': '3300', 'skr03_haben': '1600',
        'tax_rate': tax_rate, 'net_amount': net,
        'tax_amount': tax, 'gross_amount': gross,
        'confidence': 0.9,
    }


def test_tax_ok_no_proposal():
    case = _case(metadata={})
    result = check_tax_plausibility(case)
    assert result.severity == 'OK'
    assert 'uebersprungen' in result.finding


def test_tax_ok_valid_19pct():
    case = _case(metadata={'booking_proposal': _bp()})
    result = check_tax_plausibility(case)
    assert result.severity == 'OK'


def test_tax_ok_valid_7pct():
    # Gross=107, Net=100, Tax=7
    case = _case(metadata={'booking_proposal': _bp(tax_rate=7.0, net='100.00', tax='7.00', gross='107.00')})
    result = check_tax_plausibility(case)
    assert result.severity == 'OK'


def test_tax_ok_valid_0pct():
    case = _case(metadata={'booking_proposal': _bp(tax_rate=0.0, net='500.00', tax='0.00', gross='500.00')})
    result = check_tax_plausibility(case)
    assert result.severity == 'OK'


def test_tax_high_invalid_rate():
    case = _case(metadata={'booking_proposal': _bp(tax_rate=13.0)})
    result = check_tax_plausibility(case)
    assert result.severity == 'HIGH'
    assert '13' in result.finding


def test_tax_high_arithmetic_mismatch():
    # Net=1000 + Tax=190 = 1190, but gross=1195 → diff=5 > 0.02
    case = _case(metadata={'booking_proposal': _bp(gross='1195.00')})
    result = check_tax_plausibility(case)
    assert result.severity == 'HIGH'
    assert 'Netto' in result.finding


def test_tax_ok_small_rounding():
    # 1000.00 + 190.00 = 1190.00 — exact, should be OK
    case = _case(metadata={'booking_proposal': _bp()})
    result = check_tax_plausibility(case)
    assert result.severity == 'OK'


# ---------------------------------------------------------------------------
# d) vendor_consistency
# ---------------------------------------------------------------------------

def test_vendor_ok_no_case_vendor():
    case = _case(vendor_name=None)
    result = check_vendor_consistency(case, [])
    assert result.severity == 'OK'


def test_vendor_ok_no_doc_vendor():
    case = _case(vendor_name='ACME GmbH')
    result = check_vendor_consistency(case, [])
    assert result.severity == 'OK'


def test_vendor_ok_identical():
    case = _case(vendor_name='ACME GmbH')
    doc = _doc({'vendor_name': 'ACME GmbH'})
    result = check_vendor_consistency(case, [doc])
    assert result.severity == 'OK'


def test_vendor_low_slight_typo():
    # 'ACME GmbH' vs 'Acme GmbH' → same after lower
    case = _case(vendor_name='ACME GmbH')
    doc = _doc({'vendor_name': 'Acme GmbH'})
    result = check_vendor_consistency(case, [doc])
    assert result.severity == 'OK'


def test_vendor_medium_different_name():
    case = _case(vendor_name='Lieferant ABC')
    doc = _doc({'vendor_name': 'XYZ Corp'})
    result = check_vendor_consistency(case, [doc])
    assert result.severity == 'MEDIUM'


def test_vendor_from_document_analysis_metadata():
    meta = {'document_analysis': {'vendor_name': 'XYZ Corp'}}
    case = _case(vendor_name='Lieferant ABC', metadata=meta)
    result = check_vendor_consistency(case, [])
    assert result.severity == 'MEDIUM'


# ---------------------------------------------------------------------------
# e) booking_plausibility
# ---------------------------------------------------------------------------

def test_booking_low_no_proposal():
    case = _case(metadata={})
    result = check_booking_plausibility(case)
    assert result.severity == 'LOW'


def test_booking_ok_good_proposal():
    meta = {'booking_proposal': _bp(tax_rate=19.0)}
    case = _case(metadata=meta)
    result = check_booking_plausibility(case)
    assert result.severity == 'OK'


def test_booking_high_low_confidence():
    meta = {'booking_proposal': {**_bp(), 'confidence': 0.3}}
    case = _case(metadata=meta)
    result = check_booking_plausibility(case)
    assert result.severity == 'HIGH'
    assert 'Konfidenz' in result.finding


def test_booking_medium_unknown_account():
    meta = {'booking_proposal': {**_bp(), 'skr03_soll': '9999', 'confidence': 0.9}}
    case = _case(metadata=meta)
    result = check_booking_plausibility(case)
    assert result.severity == 'MEDIUM'
    assert '9999' in result.finding


def test_booking_medium_missing_accounts():
    meta = {'booking_proposal': {'confidence': 0.8, 'skr03_soll': None, 'skr03_haben': None}}
    case = _case(metadata=meta)
    result = check_booking_plausibility(case)
    assert result.severity == 'MEDIUM'
