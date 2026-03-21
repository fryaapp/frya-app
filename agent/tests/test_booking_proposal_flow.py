"""Test: Booking proposal flow — Accounting Analyst → PENDING_APPROVAL Open Item."""
import json
import pytest
from decimal import Decimal
from datetime import date

from app.accounting_analysis.models import (
    AccountingAnalysisResult,
    AccountingField,
    AmountSummary,
    BookingCandidate,
    TaxHint,
)
from app.booking.approval_service import (
    format_booking_proposal_message,
    skr03_to_akaunting_category,
)
from app.document_analysis.models import Annotation


def _make_accounting_result(
    decision='PROPOSED',
    confidence=0.88,
    vendor='Hetzner Online GmbH',
    total=Decimal('6.38'),
    risks=None,
) -> AccountingAnalysisResult:
    return AccountingAnalysisResult(
        case_id='test-case',
        accounting_review_ref='rev-001',
        booking_candidate_type='INVOICE_STANDARD_EXPENSE',
        supplier_or_counterparty_hint=AccountingField(value=vendor, status='FOUND', confidence=confidence, source_kind='OCR_TEXT'),
        invoice_reference_hint=AccountingField(value='RE-001', status='FOUND', confidence=confidence, source_kind='OCR_TEXT'),
        amount_summary=AmountSummary(
            total_amount=AccountingField(value=total, status='FOUND', confidence=confidence, source_kind='OCR_TEXT'),
            currency=AccountingField(value='EUR', status='FOUND', confidence=confidence, source_kind='OCR_TEXT'),
            net_amount=AccountingField(value=Decimal('5.36'), status='FOUND', confidence=confidence, source_kind='OCR_TEXT'),
            tax_amount=AccountingField(value=Decimal('1.02'), status='FOUND', confidence=confidence, source_kind='OCR_TEXT'),
        ),
        due_date_hint=AccountingField(value=None, status='MISSING', confidence=0.0, source_kind='NONE'),
        tax_hint=TaxHint(rate=AccountingField(value='19.0', status='FOUND', confidence=0.9, source_kind='OCR_TEXT')),
        booking_candidate=BookingCandidate(
            candidate_type='INVOICE_STANDARD_EXPENSE',
            counterparty_hint='Telekommunikation',
        ),
        booking_confidence=confidence,
        accounting_risks=risks or [],
        suggested_next_step='ACCOUNTING_CONFIRMATION',
        global_decision=decision,
        ready_for_user_approval=True,
        ready_for_accounting_confirmation=True,
        analysis_summary='Rechnung Hetzner 6.38 EUR',
    )


def test_format_proposal_high_confidence_no_risks():
    """High confidence + no risks → short, direct message."""
    result = _make_accounting_result(confidence=0.88)
    msg = format_booking_proposal_message(result)
    assert 'Hetzner Online GmbH' in msg
    assert '6' in msg  # amount
    assert 'buchen' in msg.lower() or 'Soll ich' in msg


def test_format_proposal_medium_confidence_warns():
    """Medium confidence → message includes uncertainty warning."""
    result = _make_accounting_result(confidence=0.65)
    msg = format_booking_proposal_message(result)
    assert 'sicher' in msg.lower() or 'check' in msg.lower()


def test_format_proposal_includes_payment_annotation():
    """payment_note annotation → Communicator mentions payment check."""
    result = _make_accounting_result(confidence=0.88)
    ann = Annotation(
        type='payment_note',
        raw_text='bez. 3.5.25',
        interpreted='bezahlt am 03.05.2025',
        confidence=0.8,
        action_suggested='CHECK_PAYMENT_EXISTS',
    )
    msg = format_booking_proposal_message(result, annotations=[ann])
    assert 'bez.' in msg or 'Zahlungseingang' in msg or 'bezahlt' in msg.lower()


def test_format_proposal_includes_allocation_annotation():
    """allocation_note annotation → Communicator mentions split."""
    result = _make_accounting_result(confidence=0.88)
    ann = Annotation(
        type='allocation_note',
        raw_text='50/50',
        interpreted='halb privat halb betrieblich',
        confidence=0.75,
        action_suggested='SUGGEST_ALLOCATION',
    )
    msg = format_booking_proposal_message(result, annotations=[ann])
    assert 'aufteilen' in msg.lower() or '50/50' in msg or 'privat' in msg.lower()


def test_format_proposal_tax_advisor_mentioned():
    """tax_advisor annotation → message mentions steuerberater."""
    result = _make_accounting_result(confidence=0.88)
    ann = Annotation(
        type='tax_advisor_note',
        raw_text='StB',
        interpreted='Steuerberater-Relevanz',
        confidence=0.7,
        action_suggested='FLAG_FOR_TAX_ADVISOR',
    )
    msg = format_booking_proposal_message(result, annotations=[ann])
    assert 'steuerberater' in msg.lower() or 'markiert' in msg.lower()


def test_skr03_to_akaunting_category_known():
    """SKR03 4920 → Telekommunikation."""
    cat = skr03_to_akaunting_category('4920')
    assert cat == 'Telekommunikation'


def test_skr03_to_akaunting_category_unknown():
    """Unknown SKR03 → Sonstiges fallback."""
    cat = skr03_to_akaunting_category('9999')
    assert cat == 'Sonstiges'


def test_skr03_to_akaunting_category_none():
    """None → Sonstiges."""
    cat = skr03_to_akaunting_category(None)
    assert cat == 'Sonstiges'
