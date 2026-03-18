"""Unit tests for AccountingAnalystService and BookingProposal schemas (Paket 22).

Covers:
1. Rule-based fallback for all major case types.
2. LLM path: happy path, markdown fence stripping, fallback on error.
3. build_accounting_analyst_service routing.
4. _parse_llm_response maps valid JSON correctly.
"""
from __future__ import annotations

import json
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.accounting_analyst.schemas import BookingProposal, CaseAnalysisInput, SKR03_COMMON_ACCOUNTS
from app.accounting_analyst.service import (
    AccountingAnalystService,
    _parse_llm_response,
    _rule_based_proposal,
    build_accounting_analyst_service,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_input(
    case_type: str = 'incoming_invoice',
    total_amount: Decimal | None = Decimal('1190.00'),
    vendor_name: str | None = 'Lieferant GmbH',
) -> CaseAnalysisInput:
    return CaseAnalysisInput(
        case_id='test-case-1',
        case_type=case_type,
        vendor_name=vendor_name,
        total_amount=total_amount,
        currency='EUR',
    )


def _invoice_proposal_json(confidence: float = 0.88) -> str:
    return json.dumps({
        'skr03_soll': '3300',
        'skr03_soll_name': 'Wareneingang 19 % MwSt',
        'skr03_haben': '1600',
        'skr03_haben_name': 'Verbindlichkeiten aus LuL',
        'tax_rate': 19.0,
        'tax_amount': 190.00,
        'net_amount': 1000.00,
        'gross_amount': 1190.00,
        'reasoning': 'Eingangsrechnung mit 19 % MwSt.',
        'confidence': confidence,
    })


def _mock_completion(content: str):
    msg = MagicMock()
    msg.content = content
    choice = MagicMock()
    choice.message = msg
    completion = MagicMock()
    completion.choices = [choice]
    return completion


# ---------------------------------------------------------------------------
# SKR03_COMMON_ACCOUNTS
# ---------------------------------------------------------------------------

def test_skr03_catalog_has_key_accounts():
    for acct in ('1600', '3300', '1400', '7000', '1200'):
        assert acct in SKR03_COMMON_ACCOUNTS


# ---------------------------------------------------------------------------
# Rule-based fallback
# ---------------------------------------------------------------------------

def test_rule_based_incoming_invoice():
    proposal = _rule_based_proposal(_make_input('incoming_invoice'))
    assert proposal.skr03_soll == '3300'
    assert proposal.skr03_haben == '1600'
    assert proposal.tax_rate == 19.0
    assert proposal.gross_amount == Decimal('1190.00')
    assert proposal.confidence == 0.5
    assert proposal.approval_mode == 'PROPOSE_ONLY'
    assert proposal.status == 'PENDING'


def test_rule_based_outgoing_invoice():
    proposal = _rule_based_proposal(_make_input('outgoing_invoice'))
    assert proposal.skr03_soll == '1400'
    assert proposal.skr03_haben == '7000'


def test_rule_based_bank_statement():
    proposal = _rule_based_proposal(_make_input('bank_statement'))
    assert proposal.skr03_soll == '4980'
    assert proposal.skr03_haben == '1200'


def test_rule_based_unknown_case_type():
    proposal = _rule_based_proposal(_make_input('other'))
    assert proposal.skr03_soll == '3300'
    assert proposal.skr03_haben == '1600'


def test_rule_based_no_amount():
    proposal = _rule_based_proposal(_make_input(total_amount=None))
    assert proposal.gross_amount is None
    assert proposal.net_amount == Decimal('0.00')


def test_rule_based_tax_calculation():
    proposal = _rule_based_proposal(_make_input(total_amount=Decimal('119.00')))
    assert proposal.tax_amount == Decimal('19.00')
    assert proposal.net_amount == Decimal('100.00')


# ---------------------------------------------------------------------------
# _parse_llm_response
# ---------------------------------------------------------------------------

def test_parse_llm_response_invoice():
    proposal = _parse_llm_response(_invoice_proposal_json(), _make_input())
    assert proposal.skr03_soll == '3300'
    assert proposal.skr03_haben == '1600'
    assert proposal.tax_rate == pytest.approx(19.0)
    assert proposal.gross_amount == Decimal('1190.0')
    assert proposal.net_amount == Decimal('1000.0')
    assert proposal.tax_amount == Decimal('190.0')
    assert proposal.confidence == pytest.approx(0.88)
    assert proposal.analyst_version == 'accounting-analyst-v1'
    assert proposal.approval_mode == 'PROPOSE_ONLY'


def test_parse_llm_response_strips_markdown_fences():
    wrapped = f'```json\n{_invoice_proposal_json()}\n```'
    proposal = _parse_llm_response(wrapped, _make_input())
    assert proposal.skr03_soll == '3300'


def test_parse_llm_response_invalid_json_raises():
    with pytest.raises(Exception):
        _parse_llm_response('not json at all', _make_input())


def test_parse_llm_response_uses_case_total_when_gross_missing():
    data = json.dumps({
        'skr03_soll': '3300', 'skr03_soll_name': 'test',
        'skr03_haben': '1600', 'skr03_haben_name': 'test',
        'tax_rate': 19.0, 'tax_amount': None, 'net_amount': None,
        'gross_amount': None,
        'reasoning': 'test', 'confidence': 0.7,
    })
    proposal = _parse_llm_response(data, _make_input(total_amount=Decimal('595.00')))
    assert proposal.gross_amount == Decimal('595.00')


# ---------------------------------------------------------------------------
# AccountingAnalystService.analyze — LLM path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_service_uses_llm_when_api_key_set():
    svc = AccountingAnalystService(
        model='openai/mistralai/Mistral-Small-24B-Instruct',
        api_key='test-key',
        base_url='https://openai.inference.de-txl.ionos.com/v1',
    )
    with patch(
        'app.accounting_analyst.service.acompletion',
        new=AsyncMock(return_value=_mock_completion(_invoice_proposal_json())),
    ) as mock_call:
        proposal = await svc.analyze(_make_input())
        assert mock_call.called
        assert proposal.skr03_soll == '3300'
        assert proposal.analyst_version == 'accounting-analyst-v1'


@pytest.mark.asyncio
async def test_service_passes_api_key_and_base_url():
    svc = AccountingAnalystService(
        model='openai/test-model',
        api_key='my-key',
        base_url='https://ionos.example.com/v1',
    )
    captured: list[dict] = []

    async def fake_completion(**kwargs):
        captured.append(kwargs)
        return _mock_completion(_invoice_proposal_json())

    with patch('app.accounting_analyst.service.acompletion', new=fake_completion):
        await svc.analyze(_make_input())

    assert captured[0]['api_key'] == 'my-key'
    assert captured[0]['api_base'] == 'https://ionos.example.com/v1'
    assert captured[0]['temperature'] == 0.0


@pytest.mark.asyncio
async def test_service_falls_back_on_llm_error():
    svc = AccountingAnalystService(model='m', api_key='key', base_url=None)
    with patch(
        'app.accounting_analyst.service.acompletion',
        new=AsyncMock(side_effect=RuntimeError('LLM down')),
    ):
        proposal = await svc.analyze(_make_input())
    assert proposal.analyst_version == 'accounting-analyst-v1'
    assert proposal.confidence == 0.5  # rule-based fallback


@pytest.mark.asyncio
async def test_service_falls_back_on_invalid_json():
    svc = AccountingAnalystService(model='m', api_key='key', base_url=None)
    with patch(
        'app.accounting_analyst.service.acompletion',
        new=AsyncMock(return_value=_mock_completion('not json')),
    ):
        proposal = await svc.analyze(_make_input())
    assert proposal.confidence == 0.5


@pytest.mark.asyncio
async def test_service_uses_rule_based_when_no_api_key():
    svc = AccountingAnalystService(model='m', api_key=None, base_url=None)
    with patch('app.accounting_analyst.service.acompletion') as mock_call:
        proposal = await svc.analyze(_make_input())
        assert not mock_call.called
    assert proposal.confidence == 0.5


# ---------------------------------------------------------------------------
# build_accounting_analyst_service routing
# ---------------------------------------------------------------------------

def test_build_service_returns_no_key_service_when_no_repo():
    svc = build_accounting_analyst_service(None, None)
    assert isinstance(svc, AccountingAnalystService)
    assert svc._api_key is None


def test_build_service_returns_no_key_when_no_config():
    repo = MagicMock()
    svc = build_accounting_analyst_service(repo, None)
    assert svc._api_key is None


def test_build_service_returns_no_key_when_decrypt_returns_none():
    repo = MagicMock()
    repo.decrypt_key_for_call.return_value = None
    config = {'model': 'mistralai/Mistral-Small-24B-Instruct', 'provider': 'ionos'}
    svc = build_accounting_analyst_service(repo, config)
    assert svc._api_key is None


def test_build_service_returns_keyed_service_when_key_present():
    repo = MagicMock()
    repo.decrypt_key_for_call.return_value = 'my-api-key'
    config = {
        'model': 'mistralai/Mistral-Small-24B-Instruct',
        'provider': 'ionos',
        'base_url': 'https://openai.inference.de-txl.ionos.com/v1',
    }
    svc = build_accounting_analyst_service(repo, config)
    assert svc._api_key == 'my-api-key'
    assert svc._model == 'openai/mistralai/Mistral-Small-24B-Instruct'
    assert svc._base_url == 'https://openai.inference.de-txl.ionos.com/v1'


def test_build_service_ionos_model_gets_openai_prefix():
    repo = MagicMock()
    repo.decrypt_key_for_call.return_value = 'key'
    config = {'model': 'mistralai/Mistral-Small-24B-Instruct', 'provider': 'ionos'}
    svc = build_accounting_analyst_service(repo, config)
    assert svc._model == 'openai/mistralai/Mistral-Small-24B-Instruct'


def test_build_service_returns_no_key_when_model_empty():
    repo = MagicMock()
    repo.decrypt_key_for_call.return_value = 'key'
    config = {'model': '', 'provider': 'ionos'}
    svc = build_accounting_analyst_service(repo, config)
    assert svc._api_key is None


def test_build_service_returns_no_key_when_decrypt_raises():
    repo = MagicMock()
    repo.decrypt_key_for_call.side_effect = RuntimeError('bad key')
    config = {'model': 'some-model', 'provider': 'ionos'}
    svc = build_accounting_analyst_service(repo, config)
    assert svc._api_key is None
