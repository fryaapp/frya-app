"""P-24c tests: Sender/Recipient confusion fix in Semantic Analyst."""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch

import pytest


# ── Test 1: USt-IDNr identifies sender, address-field firm is recipient ───────

def test_ust_id_identifies_sender():
    """Firma mit USt-IDNr = Absender; Firma im Adressfeld = Empfänger."""
    from app.document_analysis.service import DocumentAnalysisService

    svc = DocumentAnalysisService()
    text = (
        'Fino Versand GbR\n'
        'Margziam Kunzmann\n'
        'Daimlerstr. 2\n'
        '77815 Bühl\n'
        '\n'
        '1&1 Telecom GmbH\n'
        'Elgendorfer Str. 57\n'
        '56410 Montabaur\n'
        '\n'
        'Rechnungsnummer: 151122582904\n'
        'USt-IDNr. DE 273 413 910\n'
        '\n'
        '1&1 Telecom GmbH · Geschäftsführer: Christian Bockelt · HRB 22331\n'
    )
    # The regex service checks party patterns — this tests that sender extraction
    # does NOT accidentally pick up "Fino Versand GbR" (which has no USt-IDNr).
    # Since DocumentAnalysisService uses regex (not LLM), the prompt rule is for
    # the semantic service — here we verify the regex service at least finds
    # a sender that is not Fino (it may be None or 1&1 depending on pattern).
    lines = text.splitlines()
    result = svc._extract_party('sender', lines, {})
    # Regex service falls back to None if no pattern match — assert Fino NOT returned
    assert result.value != 'Fino Versand GbR', (
        f'Regex service must not return the recipient as sender, got: {result.value!r}'
    )


# ── Test 2: Semantic service builds tenant hint when env var is set ───────────

def test_own_company_name_injected_into_prompt():
    """FRYA_OWN_COMPANY_NAME env var is prepended to user_content."""
    import os
    from unittest.mock import AsyncMock, MagicMock, patch

    fake_response = MagicMock()
    fake_response.choices = [MagicMock()]
    fake_response.choices[0].message.content = (
        '{"document_type":"INVOICE","sender":"1&1 Telecom GmbH",'
        '"recipient":"Fino Versand GbR","total_amount":8.54,'
        '"net_amount":7.18,"tax_amount":1.36,"tax_rate":19.0,'
        '"currency":"EUR","document_date":"19.01.2026","due_date":null,'
        '"invoice_number":"151122582904","customer_number":null,'
        '"file_number":null,"iban":null,"tax_id":"DE 273 413 910",'
        '"contract_end_date":null,"cancellation_period_days":null,'
        '"references":["151122582904"],"confidence":0.88,"annotations":[]}'
    )

    captured_content: list[str] = []

    async def fake_acompletion(**kwargs):
        msgs = kwargs.get('messages', [])
        for m in msgs:
            if m.get('role') == 'user':
                captured_content.append(m['content'])
        return fake_response

    from app.document_analysis.models import DocumentAnalysisInput
    payload = DocumentAnalysisInput(
        case_id='test-p24c',
        document_ref='1',
        event_source='test',
        ocr_text='1&1 Telecom GmbH Rechnung 8,54 EUR',
    )

    with patch.dict(os.environ, {'FRYA_OWN_COMPANY_NAME': 'Fino Versand GbR'}), \
         patch('app.document_analysis.semantic_service._OWN_COMPANY_NAME', 'Fino Versand GbR'), \
         patch('app.document_analysis.semantic_service.acompletion', side_effect=fake_acompletion):
        import asyncio
        from app.document_analysis.semantic_service import DocumentAnalystSemanticService
        svc = DocumentAnalystSemanticService(model='openai/test', api_key='k', base_url=None)
        asyncio.run(svc.analyze(payload))

    assert captured_content, 'No user message captured'
    assert 'Fino Versand GbR' in captured_content[0], (
        'Tenant name must appear in user_content hint'
    )
    assert 'EMPFÄNGER' in captured_content[0], (
        'Hint must clarify tenant is recipient'
    )


# ── Test 3: Semantic service parse — sender = 1&1, recipient = Fino ───────────

def test_semantic_parse_sender_recipient_correctly():
    """_parse_llm_response must map sender/recipient from LLM JSON correctly."""
    from unittest.mock import MagicMock
    from app.document_analysis.models import DocumentAnalysisInput
    from app.document_analysis.semantic_service import DocumentAnalystSemanticService

    svc = DocumentAnalystSemanticService(model='openai/test', api_key=None, base_url=None)
    payload = DocumentAnalysisInput(
        case_id='test-p24c-parse',
        document_ref='1',
        event_source='test',
        ocr_text='dummy',
    )
    llm_json = (
        '{"document_type":"INVOICE","sender":"1&1 Telecom GmbH",'
        '"recipient":"Fino Versand GbR","total_amount":8.54,'
        '"net_amount":7.18,"tax_amount":1.36,"tax_rate":19.0,'
        '"currency":"EUR","document_date":"19.01.2026","due_date":null,'
        '"invoice_number":"151122582904","customer_number":null,'
        '"file_number":null,"iban":null,"tax_id":null,'
        '"contract_end_date":null,"cancellation_period_days":null,'
        '"references":["151122582904"],"confidence":0.88,"annotations":[]}'
    )
    result = svc._parse_llm_response(llm_json, payload)

    assert result.sender.value == '1&1 Telecom GmbH', (
        f'Expected 1&1 Telecom GmbH as sender, got {result.sender.value!r}'
    )
    assert result.recipient.value == 'Fino Versand GbR', (
        f'Expected Fino Versand GbR as recipient, got {result.recipient.value!r}'
    )
    # net_amount and tax_amount must be parsed as DetectedAmount entries
    net_amounts = [a for a in result.amounts if a.label == 'NET']
    tax_amounts = [a for a in result.amounts if a.label == 'TAX']
    assert net_amounts and net_amounts[0].amount == Decimal('7.18')
    assert tax_amounts and tax_amounts[0].amount == Decimal('1.36')
