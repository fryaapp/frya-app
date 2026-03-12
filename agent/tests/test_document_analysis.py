from __future__ import annotations

from decimal import Decimal

import pytest

from app.document_analysis.models import DocumentAnalysisInput
from app.document_analysis.service import DocumentAnalysisService


async def _analyze(ocr_text: str, *, metadata: dict | None = None, preview_text: str | None = None):
    service = DocumentAnalysisService()
    return await service.analyze(
        DocumentAnalysisInput(
            case_id='doc-test',
            document_ref='123',
            event_source='test',
            paperless_metadata=metadata or {},
            ocr_text=ocr_text,
            preview_text=preview_text,
            case_context={},
        )
    )


@pytest.mark.asyncio
async def test_document_analysis_invoice_extracts_core_fields():
    result = await _analyze(
        """
        Rechnung
        Absender: Muster GmbH
        Empfaenger: Frya GmbH
        Rechnungsnummer: RE-2026-1001
        Rechnungsdatum: 11.03.2026
        Gesamtbetrag: 1.190,00 EUR
        Netto: 1.000,00 EUR
        MwSt: 190,00 EUR
        """
    )

    assert result.document_type.value == 'INVOICE'
    assert result.sender.value == 'Muster GmbH'
    assert result.currency.value == 'EUR'
    assert result.global_decision == 'ANALYZED'
    assert result.ready_for_accounting_review is True
    assert 'amounts' not in result.missing_fields


@pytest.mark.asyncio
async def test_document_analysis_reminder_detects_due_date_and_reference():
    result = await _analyze(
        """
        Mahnung
        Absender: Beispiel AG
        Rechnungsnummer: RE-2026-7
        Faellig bis: 20.03.2026
        Offener Betrag: 450,00 EUR
        """
    )

    assert result.document_type.value == 'REMINDER'
    assert result.due_date.value is not None
    assert any(ref.value == 'RE-2026-7' for ref in result.references)
    assert [item.amount for item in result.amounts] == [Decimal('450.00')]
    assert result.recommended_next_step in {'ACCOUNTING_REVIEW', 'HUMAN_REVIEW'}


@pytest.mark.asyncio
async def test_document_analysis_reminder_review_ready_needs_due_date_and_reference():
    result = await _analyze(
        """
        Mahnung
        Absender: Beispiel AG
        Offener Betrag: 450,00 EUR
        """
    )

    assert result.document_type.value == 'REMINDER'
    assert result.ready_for_accounting_review is False
    assert result.global_decision == 'INCOMPLETE'


@pytest.mark.asyncio
async def test_document_analysis_letter_classifies_non_financial_scope():
    result = await _analyze(
        """
        Sehr geehrte Damen und Herren,
        wir bestaetigen den Eingang Ihrer Unterlagen.
        Mit freundlichen Gruessen
        Service Team
        """
    )

    assert result.document_type.value == 'LETTER'
    assert result.ready_for_accounting_review is False
    assert result.global_decision in {'ANALYZED', 'LOW_CONFIDENCE'}


@pytest.mark.asyncio
async def test_document_analysis_missing_invoice_fields_stops_cleanly():
    result = await _analyze(
        """
        Rechnung
        Absender: Muster GmbH
        Vielen Dank fuer Ihren Auftrag.
        """
    )

    assert result.document_type.value == 'INVOICE'
    assert result.global_decision == 'INCOMPLETE'
    assert 'amounts' in result.missing_fields
    assert 'document_date' in result.missing_fields


@pytest.mark.asyncio
async def test_document_analysis_conflicting_amounts_marks_conflict():
    result = await _analyze(
        """
        Rechnung
        Absender: Muster GmbH
        Rechnungsdatum: 11.03.2026
        Gesamtbetrag: 1.190,00 EUR
        Zu zahlen: 990,00 EUR
        """
    )

    assert result.global_decision == 'CONFLICT'
    assert any(risk.code == 'AMOUNT_CONFLICT' for risk in result.risks)
    assert result.ready_for_accounting_review is False


@pytest.mark.asyncio
async def test_document_analysis_empty_ocr_requests_recheck():
    result = await _analyze('', metadata={'title': 'scan.pdf'})

    assert result.global_decision == 'INCOMPLETE'
    assert result.recommended_next_step == 'OCR_RECHECK'
    assert any(risk.code == 'NO_OCR_TEXT' for risk in result.risks)
