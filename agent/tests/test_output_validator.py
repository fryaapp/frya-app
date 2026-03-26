"""Tests for output_validator — extraction validation and booking proposal checks."""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from app.security.output_validator import (
    ValidationFinding,
    ValidationResult,
    validate_booking_proposal,
    validate_extraction,
)


# ---------------------------------------------------------------------------
# validate_extraction — helpers
# ---------------------------------------------------------------------------

def _extraction(**kwargs) -> dict:
    return kwargs


# ---------------------------------------------------------------------------
# validate_extraction — all fields present
# ---------------------------------------------------------------------------

def test_all_fields_present_valid():
    text = 'Telekom GmbH, Rechnung RE-001, Betrag 340,00 EUR'
    result = validate_extraction(text, _extraction(
        sender='Telekom GmbH',
        invoice_number='RE-001',
        total_amount=Decimal('340.00'),
    ))
    assert result.is_valid
    assert result.findings == []


def test_empty_extraction_valid():
    result = validate_extraction('any text', {})
    assert result.is_valid


def test_none_values_not_validated():
    result = validate_extraction('text', _extraction(
        sender=None, total_amount=None, invoice_number=None,
    ))
    assert result.is_valid


# ---------------------------------------------------------------------------
# validate_extraction — hallucination detection
# ---------------------------------------------------------------------------

def test_hallucinated_vendor_detected():
    text = 'Betrag 340,00 EUR, Rechnung RE-001'
    result = validate_extraction(text, _extraction(sender='Fake Company AG'))
    assert not result.is_valid
    assert any(f.field == 'vendor_name' for f in result.findings)
    assert result.hallucination_suspected


def test_hallucinated_vendor_medium_severity():
    text = 'Betrag 100 EUR'
    result = validate_extraction(text, _extraction(sender='Invented GmbH'))
    vendor_finding = next((f for f in result.findings if f.field == 'vendor_name'), None)
    assert vendor_finding is not None
    assert vendor_finding.severity == 'MEDIUM'


def test_hallucinated_amount_detected():
    text = 'Telekom GmbH, Betrag 340,00 EUR'
    result = validate_extraction(text, _extraction(total_amount=Decimal('9999.00')))
    assert not result.is_valid
    assert any(f.field == 'amount' for f in result.findings)
    assert result.hallucination_suspected


def test_hallucinated_amount_high_severity():
    text = 'Telekom Betrag 100 EUR'
    result = validate_extraction(text, _extraction(total_amount=Decimal('9999.99')))
    amount_finding = next((f for f in result.findings if f.field == 'amount'), None)
    assert amount_finding is not None
    assert amount_finding.severity == 'HIGH'


def test_hallucinated_invoice_number_detected():
    text = 'Telekom GmbH Betrag 100 EUR'
    result = validate_extraction(text, _extraction(invoice_number='RE-9999-FAKE'))
    assert not result.is_valid
    assert any(f.field == 'invoice_number' for f in result.findings)


def test_multiple_hallucinations_all_detected():
    text = 'Betrag 50 EUR'
    result = validate_extraction(text, _extraction(
        sender='Ghost Corp',
        total_amount=Decimal('999.00'),
        invoice_number='FAKE-001',
    ))
    fields = [f.field for f in result.findings]
    assert 'vendor_name' in fields
    assert 'amount' in fields
    assert 'invoice_number' in fields


def test_overall_severity_high_when_amount_hallucinated():
    text = 'Betrag 100 EUR'
    result = validate_extraction(text, _extraction(total_amount=Decimal('9999.99')))
    if not result.is_valid:
        assert result.overall_severity == 'HIGH'


# ---------------------------------------------------------------------------
# validate_extraction — amount format matching
# ---------------------------------------------------------------------------

def test_amount_found_german_comma():
    text = 'Gesamtbetrag: 340,00 EUR'
    result = validate_extraction(text, _extraction(total_amount=Decimal('340.00')))
    assert not any(f.field == 'amount' for f in result.findings)


def test_amount_found_integer():
    text = 'Betrag: 500 EUR'
    result = validate_extraction(text, _extraction(total_amount=Decimal('500')))
    assert not any(f.field == 'amount' for f in result.findings)


def test_amount_found_dot_decimal():
    text = 'Invoice total: 1234.56 EUR'
    result = validate_extraction(text, _extraction(total_amount=Decimal('1234.56')))
    assert not any(f.field == 'amount' for f in result.findings)


def test_vendor_case_insensitive():
    text = 'TELEKOM GMBH Rechnung 340 EUR'
    result = validate_extraction(text, _extraction(sender='Telekom GmbH'))
    assert not any(f.field == 'vendor_name' for f in result.findings)


# ---------------------------------------------------------------------------
# validate_booking_proposal — helpers
# ---------------------------------------------------------------------------

def _proposal(**kwargs) -> MagicMock:
    p = MagicMock()
    p.tax_rate = kwargs.get('tax_rate', 19.0)
    p.net_amount = kwargs.get('net_amount', Decimal('100.00'))
    p.tax_amount = kwargs.get('tax_amount', Decimal('19.00'))
    p.gross_amount = kwargs.get('gross_amount', Decimal('119.00'))
    p.skr03_soll = kwargs.get('skr03_soll', '3300')
    p.skr03_haben = kwargs.get('skr03_haben', '1600')
    p.confidence = kwargs.get('confidence', 0.8)
    return p


# ---------------------------------------------------------------------------
# validate_booking_proposal — valid proposals
# ---------------------------------------------------------------------------

def test_valid_proposal_passes():
    result = validate_booking_proposal(_proposal())
    assert result.is_valid
    assert result.findings == []
    assert result.overall_severity == 'OK'


def test_valid_tax_rate_zero():
    result = validate_booking_proposal(_proposal(
        tax_rate=0.0, tax_amount=Decimal('0.00'),
        net_amount=Decimal('100.00'), gross_amount=Decimal('100.00'),
    ))
    assert not any(f.field == 'tax_rate' for f in result.findings)


def test_valid_tax_rate_seven():
    result = validate_booking_proposal(_proposal(
        tax_rate=7.0, net_amount=Decimal('100.00'),
        tax_amount=Decimal('7.00'), gross_amount=Decimal('107.00'),
    ))
    assert not any(f.field == 'tax_rate' for f in result.findings)


def test_valid_tax_rate_none():
    result = validate_booking_proposal(_proposal(tax_rate=None))
    assert not any(f.field == 'tax_rate' for f in result.findings)


def test_arithmetic_within_tolerance():
    # net=100.00, tax=19.01, gross=119.00 → diff=0.01 < 0.02 → OK
    result = validate_booking_proposal(_proposal(
        net_amount=Decimal('100.00'),
        tax_amount=Decimal('19.01'),
        gross_amount=Decimal('119.00'),
    ))
    assert not any(f.issue == 'arithmetic_mismatch' for f in result.findings)


def test_none_amounts_skip_arithmetic():
    result = validate_booking_proposal(_proposal(
        net_amount=None, tax_amount=None, gross_amount=None,
    ))
    assert not any(f.issue == 'arithmetic_mismatch' for f in result.findings)


# ---------------------------------------------------------------------------
# validate_booking_proposal — invalid proposals
# ---------------------------------------------------------------------------

def test_invalid_tax_rate_15_flagged():
    result = validate_booking_proposal(_proposal(tax_rate=15.0))
    assert not result.is_valid
    assert any(f.field == 'tax_rate' and f.issue == 'invalid_tax_rate' for f in result.findings)
    assert any(f.severity == 'HIGH' for f in result.findings if f.field == 'tax_rate')


def test_invalid_tax_rate_21_flagged():
    result = validate_booking_proposal(_proposal(tax_rate=21.0))
    assert any(f.field == 'tax_rate' for f in result.findings)


def test_arithmetic_mismatch_flagged():
    # net=100, tax=19, gross=200 → mismatch
    result = validate_booking_proposal(_proposal(
        net_amount=Decimal('100.00'),
        tax_amount=Decimal('19.00'),
        gross_amount=Decimal('200.00'),
    ))
    assert not result.is_valid
    assert any(f.field == 'gross_amount' and f.issue == 'arithmetic_mismatch' for f in result.findings)


def test_arithmetic_mismatch_high_severity():
    result = validate_booking_proposal(_proposal(
        net_amount=Decimal('100.00'),
        tax_amount=Decimal('19.00'),
        gross_amount=Decimal('200.00'),
    ))
    mismatch = next((f for f in result.findings if f.issue == 'arithmetic_mismatch'), None)
    if mismatch:
        assert mismatch.severity == 'HIGH'


def test_zero_amount_flagged():
    result = validate_booking_proposal(_proposal(gross_amount=Decimal('0.00')))
    assert not result.is_valid
    assert any(f.issue == 'non_positive_amount' for f in result.findings)


def test_negative_amount_flagged():
    result = validate_booking_proposal(_proposal(gross_amount=Decimal('-50.00')))
    assert not result.is_valid
    assert any(f.issue == 'non_positive_amount' for f in result.findings)


def test_unknown_soll_account_flagged():
    result = validate_booking_proposal(_proposal(skr03_soll='9999'))
    assert any(f.field == 'skr03_soll' and f.issue == 'unknown_account' for f in result.findings)


def test_unknown_haben_account_flagged():
    result = validate_booking_proposal(_proposal(skr03_haben='8888'))
    assert any(f.field == 'skr03_haben' and f.issue == 'unknown_account' for f in result.findings)


def test_unknown_account_medium_severity():
    result = validate_booking_proposal(_proposal(skr03_soll='9999'))
    finding = next((f for f in result.findings if f.field == 'skr03_soll'), None)
    if finding:
        assert finding.severity == 'MEDIUM'


def test_none_accounts_not_flagged():
    result = validate_booking_proposal(_proposal(skr03_soll=None, skr03_haben=None))
    assert not any(f.issue == 'unknown_account' for f in result.findings)


# ---------------------------------------------------------------------------
# validate_booking_proposal — known valid accounts
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('account', [
    '1000', '1200', '1400', '1571', '1576', '1600',
    '3300', '3400', '3801', '3806',
    '4200', '4300', '4910', '4920', '4940', '4980',
    '7000', '7010',
])
def test_all_known_skr03_accounts_pass(account):
    result = validate_booking_proposal(_proposal(skr03_soll=account, skr03_haben='1600'))
    assert not any(f.field == 'skr03_soll' for f in result.findings), \
        f'Account {account} should be valid'


# ---------------------------------------------------------------------------
# ValidationResult schema
# ---------------------------------------------------------------------------

def test_validation_result_is_dataclass():
    result = validate_booking_proposal(_proposal())
    assert isinstance(result, ValidationResult)
    assert isinstance(result.is_valid, bool)
    assert isinstance(result.findings, list)
    assert result.overall_severity in ('OK', 'LOW', 'MEDIUM', 'HIGH')
    assert isinstance(result.hallucination_suspected, bool)


def test_validation_finding_fields():
    finding = ValidationFinding(
        field='tax_rate', issue='invalid_tax_rate', severity='HIGH', detail='15% is invalid',
    )
    assert finding.field == 'tax_rate'
    assert finding.severity == 'HIGH'
