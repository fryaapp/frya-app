from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.accounting_analysis.models import AccountingAnalysisInput
from app.accounting_analysis.service import AccountingAnalysisService
from app.accounting_review.models import AccountingReviewDraft
from app.document_analysis.models import DocumentAnalysisInput
from app.document_analysis.service import DocumentAnalysisService


async def _document_analysis(ocr_text: str, *, metadata: dict | None = None):
    service = DocumentAnalysisService()
    return await service.analyze(
        DocumentAnalysisInput(
            case_id='doc-test',
            document_ref='123',
            event_source='test',
            paperless_metadata=metadata or {},
            ocr_text=ocr_text,
            preview_text=None,
            case_context={},
        )
    )


def _review_ref(case_id: str, document_ref: str, version: str = 'accounting-review-v1') -> str:
    return f'{case_id}:{document_ref}:{version}'


@pytest.mark.asyncio
async def test_accounting_analysis_invoice_builds_conservative_booking_candidate():
    document_analysis = await _document_analysis(
        '''
        Rechnung
        Absender: Muster GmbH
        Empfaenger: Frya GmbH
        Rechnungsnummer: RE-2026-1001
        Rechnungsdatum: 11.03.2026
        Gesamtbetrag: 1.190,00 EUR
        Netto: 1.000,00 EUR
        MwSt: 190,00 EUR
        '''
    )
    review = AccountingReviewDraft(
        case_id='doc-test',
        document_ref='123',
        source_document_type='INVOICE',
        review_status='READY',
        ready_for_accounting_review=True,
        analysis_summary='review ready',
        sender='Muster GmbH',
        recipient='Frya GmbH',
        total_amount='1190.00',
        currency='EUR',
        document_date='2026-03-11',
        due_date=None,
        references=['RE-2026-1001'],
        suggested_review_focus=['Rechnung pruefen'],
        next_step='ACCOUNTING_REVIEW',
    )

    result = await AccountingAnalysisService().analyze(
        AccountingAnalysisInput(
            case_id='doc-test',
            accounting_review_ref=_review_ref('doc-test', '123'),
            review_draft=review,
            document_analysis_result=document_analysis,
            case_context={},
        )
    )

    assert result.global_decision == 'PROPOSED'
    assert result.booking_candidate_type == 'INVOICE_STANDARD_EXPENSE'
    assert result.ready_for_accounting_confirmation is True
    assert result.suggested_next_step == 'ACCOUNTING_CONFIRMATION'
    assert result.amount_summary.total_amount.value == Decimal('1190.00')
    assert result.tax_hint.rate.value == '19%'


@pytest.mark.asyncio
async def test_accounting_analysis_reminder_stays_review_focused():
    document_analysis = await _document_analysis(
        '''
        Mahnung
        Absender: Beispiel Energie AG
        Rechnungsnummer: RE-2026-77
        Faellig bis: 18.03.2026
        Offener Betrag: 450,00 EUR
        ''',
        metadata={'created_date': '2026-03-11'},
    )
    review = AccountingReviewDraft(
        case_id='doc-test',
        document_ref='456',
        source_document_type='REMINDER',
        review_status='READY',
        ready_for_accounting_review=True,
        analysis_summary='review ready',
        sender='Beispiel Energie AG',
        recipient='Frya GmbH',
        total_amount='450.00',
        currency='EUR',
        document_date='2026-03-11',
        due_date='2026-03-18',
        references=['RE-2026-77'],
        suggested_review_focus=['Mahnung pruefen'],
        next_step='ACCOUNTING_REVIEW',
    )

    result = await AccountingAnalysisService().analyze(
        AccountingAnalysisInput(
            case_id='doc-test',
            accounting_review_ref=_review_ref('doc-test', '456'),
            review_draft=review,
            document_analysis_result=document_analysis,
            case_context={},
        )
    )

    assert result.global_decision == 'PROPOSED'
    assert result.booking_candidate_type == 'REMINDER_REFERENCE_CHECK'
    assert result.ready_for_accounting_confirmation is False
    assert result.suggested_next_step == 'REMINDER_REFERENCE_REVIEW'
    assert any(risk.code == 'REMINDER_REQUIRES_REFERENCE_REVIEW' for risk in result.accounting_risks)


@pytest.mark.asyncio
async def test_accounting_analysis_missing_invoice_reference_blocks_candidate():
    document_analysis = await _document_analysis(
        '''
        Rechnung
        Absender: Muster GmbH
        Rechnungsdatum: 11.03.2026
        Gesamtbetrag: 1.190,00 EUR
        Netto: 1.000,00 EUR
        MwSt: 190,00 EUR
        '''
    )
    review = AccountingReviewDraft(
        case_id='doc-test',
        document_ref='789',
        source_document_type='INVOICE',
        review_status='READY',
        ready_for_accounting_review=True,
        analysis_summary='review ready',
        sender='Muster GmbH',
        recipient='Frya GmbH',
        total_amount='1190.00',
        currency='EUR',
        document_date='2026-03-11',
        due_date=None,
        references=[],
        suggested_review_focus=['Rechnung pruefen'],
        next_step='ACCOUNTING_REVIEW',
    )

    result = await AccountingAnalysisService().analyze(
        AccountingAnalysisInput(
            case_id='doc-test',
            accounting_review_ref=_review_ref('doc-test', '789'),
            review_draft=review,
            document_analysis_result=document_analysis,
            case_context={},
        )
    )

    assert result.global_decision == 'LOW_CONFIDENCE'
    assert result.booking_candidate_type == 'NO_CANDIDATE'
    assert 'invoice_reference_hint' in result.missing_accounting_fields
    assert result.ready_for_accounting_confirmation is False


@pytest.mark.asyncio
async def test_accounting_analysis_conflict_case_blocks_for_review():
    document_analysis = await _document_analysis(
        '''
        Rechnung
        Absender: Muster GmbH
        Rechnungsnummer: RE-2026-1002
        Rechnungsdatum: 11.03.2026
        Gesamtbetrag: 1.190,00 EUR
        Zu zahlen: 990,00 EUR
        '''
    )
    review = AccountingReviewDraft(
        case_id='doc-test',
        document_ref='321',
        source_document_type='INVOICE',
        review_status='READY',
        ready_for_accounting_review=True,
        analysis_summary='review ready',
        sender='Muster GmbH',
        recipient='Frya GmbH',
        total_amount='1190.00',
        currency='EUR',
        document_date='2026-03-11',
        due_date=None,
        references=['RE-2026-1002'],
        suggested_review_focus=['Rechnung pruefen'],
        next_step='ACCOUNTING_REVIEW',
    )

    result = await AccountingAnalysisService().analyze(
        AccountingAnalysisInput(
            case_id='doc-test',
            accounting_review_ref=_review_ref('doc-test', '321'),
            review_draft=review,
            document_analysis_result=document_analysis,
            case_context={},
        )
    )

    assert result.global_decision == 'BLOCKED_FOR_REVIEW'
    assert result.booking_candidate_type == 'NO_CANDIDATE'
    assert any(risk.code == 'AMOUNT_CONFLICT' for risk in result.accounting_risks)
