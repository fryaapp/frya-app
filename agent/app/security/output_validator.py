"""Output validation for LLM-extracted data and booking proposals.

Two validators:
  validate_extraction()       — checks extracted fields against source OCR text
                                to detect hallucinated values
  validate_booking_proposal() — checks arithmetic consistency and valid SKR03
                                account numbers in booking proposals
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation


@dataclass
class ValidationFinding:
    """A single validation problem found in LLM output."""

    field: str
    issue: str
    severity: str   # 'LOW' | 'MEDIUM' | 'HIGH'
    detail: str = ''


@dataclass
class ValidationResult:
    """Aggregated result of output validation."""

    is_valid: bool
    findings: list[ValidationFinding] = field(default_factory=list)
    overall_severity: str = 'OK'    # 'OK' | 'LOW' | 'MEDIUM' | 'HIGH'
    hallucination_suspected: bool = False


# ---------------------------------------------------------------------------
# Severity helpers
# ---------------------------------------------------------------------------

_SEVERITY_RANK: dict[str, int] = {'OK': 0, 'LOW': 1, 'MEDIUM': 2, 'HIGH': 3}


def _max_severity(findings: list[ValidationFinding]) -> str:
    if not findings:
        return 'OK'
    return max((f.severity for f in findings), key=lambda s: _SEVERITY_RANK.get(s, 0))


# ---------------------------------------------------------------------------
# validate_extraction — hallucination detection
# ---------------------------------------------------------------------------

def _value_in_text(text: str, value: str) -> bool:
    """Case-insensitive substring check."""
    return value.strip().lower() in text.lower()


def _amount_in_text(text: str, amount: object) -> bool:
    """Check whether an amount appears in the text in any common representation."""
    if amount is None:
        return True
    try:
        d = Decimal(str(amount))
    except (InvalidOperation, ValueError):
        return True  # Cannot validate — pass through

    candidates: list[str] = [str(d)]

    if d == d.to_integral_value():
        int_val = int(d)
        candidates.append(str(int_val))
        # German thousands separator
        candidates.append(f'{int_val:,}'.replace(',', '.'))
    else:
        two_dec = f'{d:.2f}'
        candidates.append(two_dec)
        # German comma format: 340,00
        candidates.append(two_dec.replace('.', ','))
        # German full format: 1.340,00
        parts = two_dec.split('.')
        if len(parts) == 2:
            int_part, dec_part = parts
            try:
                german_full = f'{int(int_part):,}'.replace(',', '.') + ',' + dec_part
                candidates.append(german_full)
            except ValueError:
                pass

    return any(c in text for c in candidates)


def validate_extraction(input_text: str, extraction: dict) -> ValidationResult:
    """Validate that extracted fields actually appear in the source OCR text.

    Fields checked:
      vendor_name / sender  → must be a substring of input_text
      amount / total_amount → must appear in common numeric formats
      invoice_number        → must be a substring of input_text

    Missing or None values are silently skipped (nothing to validate).
    """
    findings: list[ValidationFinding] = []

    # Vendor / sender name
    vendor = extraction.get('vendor_name') or extraction.get('sender')
    if vendor and not _value_in_text(input_text, str(vendor)):
        findings.append(ValidationFinding(
            field='vendor_name',
            issue='not_found_in_source',
            severity='MEDIUM',
            detail=f'Value "{vendor}" not found in source text',
        ))

    # Amount
    amount = extraction.get('amount') or extraction.get('total_amount')
    if amount is not None and not _amount_in_text(input_text, amount):
        findings.append(ValidationFinding(
            field='amount',
            issue='not_found_in_source',
            severity='HIGH',
            detail=f'Amount {amount} not found in source text',
        ))

    # Invoice number
    inv_num = extraction.get('invoice_number')
    if inv_num and not _value_in_text(input_text, str(inv_num)):
        findings.append(ValidationFinding(
            field='invoice_number',
            issue='not_found_in_source',
            severity='MEDIUM',
            detail=f'Invoice number "{inv_num}" not found in source text',
        ))

    severity = _max_severity(findings)
    hallucination = any(f.issue == 'not_found_in_source' for f in findings)

    return ValidationResult(
        is_valid=not findings,
        findings=findings,
        overall_severity=severity,
        hallucination_suspected=hallucination,
    )


# ---------------------------------------------------------------------------
# validate_booking_proposal — arithmetic & SKR03 consistency
# ---------------------------------------------------------------------------

_VALID_TAX_RATES: frozenset[float] = frozenset({0.0, 7.0, 19.0})

# Known SKR03 account numbers accepted by the system
_KNOWN_SKR03_ACCOUNTS: frozenset[str] = frozenset({
    '1000', '1200', '1400', '1571', '1576', '1600',
    '3300', '3400', '3801', '3806',
    '4200', '4300', '4910', '4920', '4940', '4980',
    '7000', '7010',
})


def validate_booking_proposal(proposal: object) -> ValidationResult:
    """Validate a BookingProposal for consistency.

    Checks:
      1. tax_rate in {0.0, 7.0, 19.0} or None
      2. net + tax == gross (tolerance ±0.02 EUR)
      3. gross_amount > 0
      4. skr03_soll and skr03_haben are known account numbers
    """
    findings: list[ValidationFinding] = []

    # ── 1. Tax rate ──────────────────────────────────────────────────────────
    tax_rate = getattr(proposal, 'tax_rate', None)
    if tax_rate is not None:
        try:
            if float(tax_rate) not in _VALID_TAX_RATES:
                findings.append(ValidationFinding(
                    field='tax_rate',
                    issue='invalid_tax_rate',
                    severity='HIGH',
                    detail=f'Tax rate {tax_rate} is not a valid German VAT rate (0, 7, 19)',
                ))
        except (TypeError, ValueError):
            pass

    # ── 2. Arithmetic: net + tax == gross ────────────────────────────────────
    net = getattr(proposal, 'net_amount', None)
    tax = getattr(proposal, 'tax_amount', None)
    gross = getattr(proposal, 'gross_amount', None)

    if net is not None and tax is not None and gross is not None:
        try:
            net_d = Decimal(str(net))
            tax_d = Decimal(str(tax))
            gross_d = Decimal(str(gross))
            expected = (net_d + tax_d).quantize(Decimal('0.01'))
            actual = gross_d.quantize(Decimal('0.01'))
            diff = abs(expected - actual)
            if diff > Decimal('0.02'):
                findings.append(ValidationFinding(
                    field='gross_amount',
                    issue='arithmetic_mismatch',
                    severity='HIGH',
                    detail=f'net({net}) + tax({tax}) = {expected} but gross={gross} (diff={diff})',
                ))
        except (InvalidOperation, ValueError, TypeError):
            pass

    # ── 3. Positive amount ───────────────────────────────────────────────────
    if gross is not None:
        try:
            if Decimal(str(gross)) <= Decimal('0'):
                findings.append(ValidationFinding(
                    field='gross_amount',
                    issue='non_positive_amount',
                    severity='HIGH',
                    detail=f'Gross amount {gross} must be positive',
                ))
        except (InvalidOperation, ValueError):
            pass

    # ── 4. Known SKR03 accounts ──────────────────────────────────────────────
    soll = getattr(proposal, 'skr03_soll', None)
    if soll and str(soll) not in _KNOWN_SKR03_ACCOUNTS:
        findings.append(ValidationFinding(
            field='skr03_soll',
            issue='unknown_account',
            severity='MEDIUM',
            detail=f'Account {soll} not in known SKR03 account list',
        ))

    haben = getattr(proposal, 'skr03_haben', None)
    if haben and str(haben) not in _KNOWN_SKR03_ACCOUNTS:
        findings.append(ValidationFinding(
            field='skr03_haben',
            issue='unknown_account',
            severity='MEDIUM',
            detail=f'Account {haben} not in known SKR03 account list',
        ))

    severity = _max_severity(findings)
    return ValidationResult(
        is_valid=not findings,
        findings=findings,
        overall_severity=severity,
        hallucination_suspected=False,
    )
