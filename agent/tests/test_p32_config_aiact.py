"""P-32 tests: Model catalog + EU AI Act labels."""


def test_model_catalog_has_ionos():
    from app.api.agent_config import MODEL_CATALOG
    assert any(m['provider'] == 'ionos' for m in MODEL_CATALOG)


def test_model_catalog_has_anthropic():
    from app.api.agent_config import MODEL_CATALOG
    assert any(m['provider'] == 'anthropic' for m in MODEL_CATALOG)


def test_model_catalog_has_custom():
    from app.api.agent_config import MODEL_CATALOG
    assert any(m['id'] == 'custom' for m in MODEL_CATALOG)


def test_model_catalog_lookup():
    from app.api.agent_config import _MODEL_CATALOG_BY_ID
    entry = _MODEL_CATALOG_BY_ID.get('ionos/mistralai/Mistral-Small-24B-Instruct')
    assert entry is not None
    assert entry['provider'] == 'ionos'
    assert entry['model'] == 'mistralai/Mistral-Small-24B-Instruct'


def test_ai_act_texts_loadable():
    import yaml
    from pathlib import Path
    path = Path(__file__).resolve().parent.parent / 'data' / 'config' / 'ai_act_texts.yaml'
    with open(path, encoding='utf-8') as f:
        data = yaml.safe_load(f)
    assert 'first_encounter_telegram' in data
    assert 'booking_proposal_footer' in data
    assert 'kuenstliche' in data['first_encounter_telegram'].lower() or 'ki' in data['first_encounter_telegram'].lower()


def test_booking_proposal_has_ki_label():
    from decimal import Decimal
    from app.booking.approval_service import format_booking_proposal_message
    from app.accounting_analysis.models import (
        AccountingAnalysisResult, AccountingField, AmountSummary, BookingCandidate, TaxHint,
    )
    result = AccountingAnalysisResult(
        case_id='test',
        accounting_review_ref='test:1',
        booking_candidate_type='INVOICE_STANDARD_EXPENSE',
        supplier_or_counterparty_hint=AccountingField(value='Test GmbH', status='FOUND', confidence=0.9, source_kind='OCR_TEXT', evidence_excerpt=None),
        invoice_reference_hint=AccountingField(value='RE-001', status='FOUND', confidence=0.9, source_kind='OCR_TEXT', evidence_excerpt=None),
        amount_summary=AmountSummary(
            total_amount=AccountingField(value=Decimal('100'), status='FOUND', confidence=0.9, source_kind='OCR_TEXT', evidence_excerpt=None),
            currency=AccountingField(value='EUR', status='FOUND', confidence=0.9, source_kind='OCR_TEXT', evidence_excerpt=None),
            net_amount=AccountingField(value=None, status='MISSING', confidence=0, source_kind='NONE', evidence_excerpt=None),
            tax_amount=AccountingField(value=None, status='MISSING', confidence=0, source_kind='NONE', evidence_excerpt=None),
        ),
        due_date_hint=AccountingField(value=None, status='MISSING', confidence=0, source_kind='NONE', evidence_excerpt=None),
        tax_hint=TaxHint(rate=AccountingField(value='19%', status='FOUND', confidence=0.7, source_kind='DERIVED', evidence_excerpt=None), reason='test'),
        booking_candidate=BookingCandidate(candidate_type='INVOICE_STANDARD_EXPENSE', counterparty_hint='Test GmbH', invoice_reference_hint='RE-001', review_focus=[], notes=[]),
        booking_confidence=0.85,
        accounting_risks=[],
        missing_accounting_fields=[],
        suggested_next_step='ACCOUNTING_CONFIRMATION',
        global_decision='PROPOSED',
        ready_for_user_approval=False,
        ready_for_accounting_confirmation=True,
        analysis_summary='test',
    )
    msg = format_booking_proposal_message(result)
    assert 'KI-generiert' in msg
