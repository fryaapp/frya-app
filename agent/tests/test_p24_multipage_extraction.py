"""P-24 tests: Multi-page extraction fix + Netto/MwSt fallback."""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest


# ── Test 1: Multi-page invoice — net_amount and tax_amount found in page 2 ───

def test_multi_page_invoice_extraction():
    """Regex extractor must find NET + TAX amounts in multi-page text."""
    from app.document_analysis.service import DocumentAnalysisService

    svc = DocumentAnalysisService()
    text = (
        'Seite 1\n'
        '1&1 Telecom GmbH\n'
        'Rechnungsbetrag: 8,54 EUR\n'
        '\n'
        'Seite 2\n'
        'Einzelpositionen\n'
        'Zwischensumme Netto  7,18 EUR\n'
        '+ Mehrwertsteuer  1,36 EUR\n'
        'Gesamtbetrag  8,54 EUR\n'
    )
    lines = text.splitlines()
    amounts = svc._extract_amounts(lines, {})

    labels = {a.label for a in amounts}
    assert 'NET' in labels, f'NET not found in {labels}'
    assert 'TAX' in labels, f'TAX not found in {labels}'

    net = next(a for a in amounts if a.label == 'NET')
    assert net.amount == Decimal('7.18')
    # TAX 1.36 must be among the results (there may be multiple TAX entries)
    tax_amounts = [a.amount for a in amounts if a.label == 'TAX']
    assert Decimal('1.36') in tax_amounts, f'1.36 not in TAX amounts: {tax_amounts}'


# ── Test 2: Fallback net calculation when net/tax MISSING ────────────────────

def test_fallback_net_calculation():
    """If net MISSING but gross known → derive net=gross/1.19, tax=gross-net."""
    from app.accounting_analysis.service import AccountingAnalysisService
    from app.accounting_analysis.models import AccountingField, AmountSummary

    svc = AccountingAnalysisService()
    amount_summary = AmountSummary(
        total_amount=AccountingField(value=Decimal('8.54'), status='FOUND', confidence=0.85, source_kind='OCR_TEXT', evidence_excerpt='8.54'),
        currency=AccountingField(value='EUR', status='FOUND', confidence=0.9, source_kind='OCR_TEXT', evidence_excerpt='EUR'),
        net_amount=AccountingField(value=None, status='MISSING', confidence=0.0, source_kind='NONE', evidence_excerpt=None),
        tax_amount=AccountingField(value=None, status='MISSING', confidence=0.0, source_kind='NONE', evidence_excerpt=None),
    )

    tax_hint, risks = svc._tax_hint([], amount_summary)

    assert tax_hint.rate.status == 'FOUND', f'Expected FOUND, got {tax_hint.rate.status}'
    assert tax_hint.rate.value == '19%'
    assert tax_hint.rate.confidence == 0.55
    assert tax_hint.rate.source_kind == 'DERIVED'
    assert any(r.code == 'TAX_DERIVED_FROM_GROSS' for r in risks)


# ── Test 3: Missing MwSt still produces PROPOSED ─────────────────────────────

@pytest.mark.asyncio
async def test_missing_mwst_still_produces_proposal():
    """Fehlender MwSt-Split darf Buchungsvorschlag NICHT unterdrücken."""
    from app.accounting_analysis.service import AccountingAnalysisService
    from app.accounting_analysis.models import AccountingAnalysisInput, AccountingField, AccountingReviewDraft
    from app.document_analysis.models import (
        DocumentAnalysisResult, ExtractedField, DetectedAmount,
    )
    from datetime import date

    doc_analysis = DocumentAnalysisResult(
        analysis_version='document-analyst-semantic-v1',
        case_id='case-p24-test',
        document_ref='42',
        event_source='paperless_webhook',
        document_type=ExtractedField(value='INVOICE', status='FOUND', confidence=0.9, source_kind='OCR_TEXT', evidence_excerpt='INVOICE'),
        sender=ExtractedField(value='1&1 Telecom GmbH', status='FOUND', confidence=0.85, source_kind='OCR_TEXT', evidence_excerpt=None),
        recipient=ExtractedField(value='Fino Versand GbR', status='FOUND', confidence=0.85, source_kind='OCR_TEXT', evidence_excerpt=None),
        amounts=[DetectedAmount(label='TOTAL', amount=Decimal('8.54'), currency='EUR', status='FOUND', confidence=0.85, source_kind='OCR_TEXT', evidence_excerpt='8,54')],
        currency=ExtractedField(value='EUR', status='FOUND', confidence=0.9, source_kind='OCR_TEXT', evidence_excerpt=None),
        document_date=ExtractedField(value=date(2026, 1, 19), status='FOUND', confidence=0.85, source_kind='OCR_TEXT', evidence_excerpt=None),
        due_date=ExtractedField(value=None, status='MISSING', confidence=0.0, source_kind='NONE', evidence_excerpt=None),
        references=[],
        risks=[],
        annotations=[],
        warnings=[],
        missing_fields=[],
        recommended_next_step='ACCOUNTING_REVIEW',
        global_decision='ANALYZED',
        ready_for_accounting_review=True,
        overall_confidence=0.85,
    )

    review = AccountingReviewDraft(
        case_id='case-p24-test',
        document_ref='42',
        source_document_type='INVOICE',
        review_status='READY',
        ready_for_accounting_review=True,
        analysis_summary='test',
        sender='1&1 Telecom GmbH',
        recipient='Fino Versand GbR',
        total_amount='8.54',
        currency='EUR',
        document_date='2026-01-19',
        references=['151122582904'],
        next_step='ACCOUNTING_REVIEW',
    )

    payload = AccountingAnalysisInput(
        case_id='case-p24-test',
        accounting_review_ref='case-p24-test:42:accounting-review-v1',
        review_draft=review,
        document_analysis_result=doc_analysis,
    )

    result = await AccountingAnalysisService().analyze(payload)

    assert result.global_decision == 'PROPOSED', f'Expected PROPOSED, got {result.global_decision}'
    assert result.ready_for_accounting_confirmation is True
    # TAX_DERIVED_FROM_GROSS risk must be present (fallback used)
    assert any(r.code == 'TAX_DERIVED_FROM_GROSS' for r in result.accounting_risks)


# ── Test 4: Regex Netto/MwSt extraction from full text ───────────────────────

def test_regex_netto_extraction_from_full_text():
    """Regex-Fallback finds NET and TAX amounts from multi-page OCR text."""
    from app.document_analysis.service import DocumentAnalysisService

    svc = DocumentAnalysisService()
    text = 'Zwischensumme Netto  7,18 EUR\n+ Mehrwertsteuer  1,36 EUR'
    lines = text.splitlines()
    amounts = svc._extract_amounts(lines, {})

    labels = {a.label for a in amounts}
    assert 'NET' in labels
    assert 'TAX' in labels

    net_values = [a.amount for a in amounts if a.label == 'NET']
    tax_values = [a.amount for a in amounts if a.label == 'TAX']
    assert Decimal('7.18') in net_values
    assert Decimal('1.36') in tax_values


# ── Test 5: max_pages=3 in OCR call (AST check) ──────────────────────────────

def test_multipage_ocr_uses_max_pages_3():
    """run_lightocr must be called with max_pages=3 (not 1)."""
    import ast
    import pathlib

    nodes_src = pathlib.Path('agent/app/orchestration/nodes.py').read_text(encoding='utf-8-sig')
    tree = ast.parse(nodes_src)

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func_name = ''
            if isinstance(node.func, ast.Name):
                func_name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                func_name = node.func.attr
            if func_name == 'run_lightocr':
                for kw in node.keywords:
                    if kw.arg == 'max_pages':
                        assert isinstance(kw.value, ast.Constant), 'max_pages must be a literal'
                        assert kw.value.value == 3, f'max_pages should be 3, got {kw.value.value}'
                        return
    pytest.fail('run_lightocr call with max_pages keyword not found in nodes.py')
