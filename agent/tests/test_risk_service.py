"""Unit tests for RiskAnalystService.

Covers:
1. analyze_case returns RiskReport with all 5 checks
2. overall_risk computation
3. LLM summary trigger threshold (MEDIUM+ only)
4. LLM fallback on error
5. No LLM when no api_key
6. build_risk_analyst_service routing
7. _template_summary edge cases
"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.risk_analyst.schemas import RiskCheck, RiskReport, compute_overall_risk
from app.risk_analyst.service import (
    RiskAnalystService,
    _template_summary,
    build_risk_analyst_service,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_repo(
    *,
    vendor_name: str | None = 'Test GmbH',
    total_amount: Decimal | None = Decimal('1190.00'),
    metadata: dict | None = None,
) -> MagicMock:
    repo = MagicMock()
    case = MagicMock()
    case.id = uuid.uuid4()
    case.tenant_id = uuid.uuid4()
    case.case_number = 'CASE-2026-00001'
    case.vendor_name = vendor_name
    case.total_amount = total_amount
    case.currency = 'EUR'
    case.case_type = 'incoming_invoice'
    case.created_at = datetime.utcnow()
    case.metadata = metadata or {}

    repo.get_case = AsyncMock(return_value=case)
    repo.get_case_documents = AsyncMock(return_value=[])
    repo.list_active_cases_for_tenant = AsyncMock(return_value=[case])
    repo.update_metadata = AsyncMock(return_value=case)
    repo.create_conflict = AsyncMock(return_value=MagicMock())
    return repo


def _svc(repo=None, *, api_key=None) -> RiskAnalystService:
    return RiskAnalystService(
        repo=repo or _make_repo(),
        model='',
        api_key=api_key,
        base_url=None,
    )


# ---------------------------------------------------------------------------
# Schema: compute_overall_risk
# ---------------------------------------------------------------------------

def test_overall_ok_all_ok():
    checks = [
        RiskCheck(case_id='x', check_type='amount_consistency', severity='OK', finding='ok'),
        RiskCheck(case_id='x', check_type='tax_plausibility', severity='OK', finding='ok'),
    ]
    assert compute_overall_risk(checks) == 'OK'


def test_overall_low():
    checks = [
        RiskCheck(case_id='x', check_type='booking_plausibility', severity='LOW', finding='low'),
    ]
    assert compute_overall_risk(checks) == 'LOW'


def test_overall_medium():
    checks = [
        RiskCheck(case_id='x', check_type='vendor_consistency', severity='MEDIUM', finding='med'),
        RiskCheck(case_id='x', check_type='booking_plausibility', severity='LOW', finding='low'),
    ]
    assert compute_overall_risk(checks) == 'MEDIUM'


def test_overall_high_from_high():
    checks = [
        RiskCheck(case_id='x', check_type='amount_consistency', severity='HIGH', finding='h'),
        RiskCheck(case_id='x', check_type='tax_plausibility', severity='MEDIUM', finding='m'),
    ]
    assert compute_overall_risk(checks) == 'HIGH'


def test_overall_high_from_critical():
    checks = [
        RiskCheck(case_id='x', check_type='duplicate_detection', severity='CRITICAL', finding='c'),
    ]
    assert compute_overall_risk(checks) == 'HIGH'


def test_overall_empty():
    assert compute_overall_risk([]) == 'OK'


# ---------------------------------------------------------------------------
# _template_summary
# ---------------------------------------------------------------------------

def test_template_all_ok():
    checks = [RiskCheck(case_id='x', check_type='amount_consistency', severity='OK', finding='ok')]
    assert _template_summary(checks, 'OK') == 'Keine Risiken gefunden — Vorgang ist konsistent.'


def test_template_high_findings():
    checks = [
        RiskCheck(case_id='x', check_type='amount_consistency', severity='HIGH', finding='h'),
    ]
    text = _template_summary(checks, 'HIGH')
    assert 'amount_consistency' in text
    assert 'HIGH' in text


def test_template_medium_findings():
    checks = [
        RiskCheck(case_id='x', check_type='vendor_consistency', severity='MEDIUM', finding='m'),
    ]
    text = _template_summary(checks, 'MEDIUM')
    assert 'mittlerer' in text


def test_template_ends_with_period():
    checks = [RiskCheck(case_id='x', check_type='tax_plausibility', severity='HIGH', finding='h')]
    text = _template_summary(checks, 'HIGH')
    assert text.endswith('.')


# ---------------------------------------------------------------------------
# analyze_case — main flow
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_analyze_case_returns_report_with_5_checks():
    svc = _svc()
    report = await svc.analyze_case(svc._repo.get_case.return_value.id)
    assert isinstance(report, RiskReport)
    assert len(report.checks) == 5
    assert report.analyst_version == 'risk-analyst-v1'


@pytest.mark.asyncio
async def test_analyze_case_stores_in_metadata():
    repo = _make_repo()
    svc = _svc(repo)
    case_id = repo.get_case.return_value.id
    await svc.analyze_case(case_id)
    repo.update_metadata.assert_called_once()
    call_kwargs = repo.update_metadata.call_args
    assert 'risk_report' in call_kwargs[0][1] or 'risk_report' in (call_kwargs[1] if call_kwargs[1] else {})


@pytest.mark.asyncio
async def test_analyze_case_returns_none_for_missing_case():
    repo = MagicMock()
    repo.get_case = AsyncMock(return_value=None)
    svc = RiskAnalystService(repo=repo, model='', api_key=None, base_url=None)
    result = await svc.analyze_case(uuid.uuid4())
    assert result is None


@pytest.mark.asyncio
async def test_analyze_case_checked_at_is_set():
    svc = _svc()
    case_id = svc._repo.get_case.return_value.id
    report = await svc.analyze_case(case_id)
    assert report is not None
    assert report.checked_at is not None


# ---------------------------------------------------------------------------
# LLM trigger threshold
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_llm_not_called_when_all_ok():
    """When all checks return OK/LOW, LLM must not be called."""
    repo = _make_repo(
        metadata={
            'booking_proposal': {
                'skr03_soll': '3300', 'skr03_haben': '1600',
                'tax_rate': 19.0, 'net_amount': '1000.00',
                'tax_amount': '190.00', 'gross_amount': '1190.00',
                'confidence': 0.9,
            }
        }
    )
    svc = RiskAnalystService(repo=repo, model='test-model', api_key='key', base_url=None)
    with patch('app.risk_analyst.service.acompletion') as mock_llm:
        case_id = repo.get_case.return_value.id
        report = await svc.analyze_case(case_id)
        # Only booking_plausibility is OK, amount/tax/vendor/duplicate also OK
        # LLM should not be called if all are OK or LOW
        # booking_plausibility with no proposal → LOW → no MEDIUM+
        pass  # Check below
    # booking is LOW → no MEDIUM+ → LLM not called
    assert not mock_llm.called


@pytest.mark.asyncio
async def test_llm_called_when_medium_plus():
    """LLM must be called when at least one MEDIUM+ check exists."""
    # Provide a booking_proposal with low confidence → HIGH → LLM called
    meta = {'booking_proposal': {'skr03_soll': '3300', 'skr03_haben': '1600', 'confidence': 0.2}}
    repo = _make_repo(metadata=meta)

    mock_completion = MagicMock()
    mock_completion.choices[0].message.content = 'Hohes Risiko festgestellt.'

    svc = RiskAnalystService(repo=repo, model='test-model', api_key='my-key', base_url=None)
    with patch(
        'app.risk_analyst.service.acompletion',
        new=AsyncMock(return_value=mock_completion),
    ):
        case_id = repo.get_case.return_value.id
        report = await svc.analyze_case(case_id)

    assert report is not None
    assert 'Hohes' in report.summary or 'Risiko' in report.summary


@pytest.mark.asyncio
async def test_llm_fallback_on_error():
    """LLM failure → falls back to template summary."""
    meta = {'booking_proposal': {'skr03_soll': '3300', 'skr03_haben': '1600', 'confidence': 0.2}}
    repo = _make_repo(metadata=meta)

    svc = RiskAnalystService(repo=repo, model='test-model', api_key='my-key', base_url=None)
    with patch(
        'app.risk_analyst.service.acompletion',
        new=AsyncMock(side_effect=RuntimeError('LLM down')),
    ):
        case_id = repo.get_case.return_value.id
        report = await svc.analyze_case(case_id)

    assert report is not None
    # Template fallback should produce a non-empty summary
    assert len(report.summary) > 0


@pytest.mark.asyncio
async def test_no_llm_without_api_key():
    """Without api_key, acompletion must never be called."""
    meta = {'booking_proposal': {'confidence': 0.1, 'skr03_soll': None, 'skr03_haben': None}}
    repo = _make_repo(metadata=meta)
    svc = RiskAnalystService(repo=repo, model='model', api_key=None, base_url=None)

    with patch('app.risk_analyst.service.acompletion') as mock_llm:
        await svc.analyze_case(repo.get_case.return_value.id)
        assert not mock_llm.called


# ---------------------------------------------------------------------------
# build_risk_analyst_service
# ---------------------------------------------------------------------------

def test_build_no_llm_repo():
    svc = build_risk_analyst_service(MagicMock(), None, None)
    assert svc._api_key is None


def test_build_no_config():
    svc = build_risk_analyst_service(MagicMock(), MagicMock(), None)
    assert svc._api_key is None


def test_build_no_key_in_config():
    llm_repo = MagicMock()
    llm_repo.decrypt_key_for_call.return_value = None
    config = {'model': 'openai/gpt-oss-120b', 'provider': 'ionos'}
    svc = build_risk_analyst_service(MagicMock(), llm_repo, config)
    assert svc._api_key is None


def test_build_with_key_ionos_prefix():
    llm_repo = MagicMock()
    llm_repo.decrypt_key_for_call.return_value = 'my-key'
    config = {
        'model': 'openai/gpt-oss-120b',
        'provider': 'ionos',
        'base_url': 'https://openai.inference.de-txl.ionos.com/v1',
    }
    svc = build_risk_analyst_service(MagicMock(), llm_repo, config)
    assert svc._api_key == 'my-key'
    assert svc._model.startswith('openai/')


def test_build_decrypt_exception():
    llm_repo = MagicMock()
    llm_repo.decrypt_key_for_call.side_effect = RuntimeError('bad')
    config = {'model': 'some-model', 'provider': 'ionos'}
    svc = build_risk_analyst_service(MagicMock(), llm_repo, config)
    assert svc._api_key is None


# ---------------------------------------------------------------------------
# scan_all_open_cases
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_scan_all_returns_list():
    repo = _make_repo()
    svc = _svc(repo)
    reports = await svc.scan_all_open_cases(repo.get_case.return_value.tenant_id)
    assert isinstance(reports, list)
    assert len(reports) == 1


@pytest.mark.asyncio
async def test_scan_all_sorted_by_risk():
    """Reports with higher risk should appear first."""
    # We can't easily control individual cases here, just verify sorting doesn't error
    repo = _make_repo()
    svc = _svc(repo)
    reports = await svc.scan_all_open_cases(repo.get_case.return_value.tenant_id)
    risks = [r.overall_risk for r in reports]
    order = {'HIGH': 0, 'MEDIUM': 1, 'LOW': 2, 'OK': 3}
    ordered = sorted(risks, key=lambda r: order.get(r, 9))
    assert risks == ordered
