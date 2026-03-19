"""Tests for risk_analyst API — schema defaults and endpoint logic.

Uses schema-level tests (no HTTP client) to keep the tests fast and focused.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from app.risk_analyst.schemas import (
    CheckType,
    OverallRisk,
    RiskCheck,
    RiskReport,
    Severity,
    compute_overall_risk,
)


# ---------------------------------------------------------------------------
# RiskCheck defaults
# ---------------------------------------------------------------------------

def test_risk_check_required_fields():
    check = RiskCheck(
        case_id='abc',
        check_type='amount_consistency',
        severity='OK',
        finding='All good.',
    )
    assert check.case_id == 'abc'
    assert check.recommendation is None


def test_risk_check_with_recommendation():
    check = RiskCheck(
        case_id='abc',
        check_type='tax_plausibility',
        severity='HIGH',
        finding='Invalid tax rate.',
        recommendation='Fix the tax rate.',
    )
    assert check.recommendation == 'Fix the tax rate.'


def test_risk_check_all_severities_valid():
    for sev in ('CRITICAL', 'HIGH', 'MEDIUM', 'LOW', 'OK'):
        check = RiskCheck(
            case_id='x', check_type='duplicate_detection',
            severity=sev, finding='test',  # type: ignore[arg-type]
        )
        assert check.severity == sev


def test_risk_check_all_check_types_valid():
    for ct in (
        'amount_consistency', 'duplicate_detection', 'tax_plausibility',
        'vendor_consistency', 'booking_plausibility',
    ):
        check = RiskCheck(
            case_id='x', check_type=ct, severity='OK', finding='ok',  # type: ignore[arg-type]
        )
        assert check.check_type == ct


# ---------------------------------------------------------------------------
# RiskReport defaults
# ---------------------------------------------------------------------------

def test_risk_report_defaults():
    report = RiskReport(case_id='x')
    assert report.checks == []
    assert report.overall_risk == 'OK'
    assert report.summary == ''
    assert report.analyst_version == 'risk-analyst-v1'
    assert report.checked_at is None


def test_risk_report_serialises_without_error():
    check = RiskCheck(
        case_id='abc',
        check_type='amount_consistency',
        severity='HIGH',
        finding='Betrag abweichend.',
        recommendation='Pruefen.',
    )
    report = RiskReport(
        case_id='abc',
        checks=[check],
        overall_risk='HIGH',
        summary='Hohes Risiko.',
        checked_at='2026-03-18T10:00:00+00:00',
    )
    data = report.model_dump(mode='json')
    assert data['overall_risk'] == 'HIGH'
    assert data['checks'][0]['severity'] == 'HIGH'
    assert data['analyst_version'] == 'risk-analyst-v1'


# ---------------------------------------------------------------------------
# compute_overall_risk
# ---------------------------------------------------------------------------

def test_compute_overall_all_ok():
    checks = [
        RiskCheck(case_id='x', check_type='tax_plausibility', severity='OK', finding='ok'),
        RiskCheck(case_id='x', check_type='vendor_consistency', severity='OK', finding='ok'),
    ]
    assert compute_overall_risk(checks) == 'OK'


def test_compute_overall_single_medium():
    checks = [
        RiskCheck(case_id='x', check_type='vendor_consistency', severity='MEDIUM', finding='m'),
    ]
    assert compute_overall_risk(checks) == 'MEDIUM'


def test_compute_overall_mixed_low_and_medium():
    checks = [
        RiskCheck(case_id='x', check_type='booking_plausibility', severity='LOW', finding='l'),
        RiskCheck(case_id='x', check_type='vendor_consistency', severity='MEDIUM', finding='m'),
    ]
    assert compute_overall_risk(checks) == 'MEDIUM'


def test_compute_overall_high_wins():
    checks = [
        RiskCheck(case_id='x', check_type='amount_consistency', severity='HIGH', finding='h'),
        RiskCheck(case_id='x', check_type='vendor_consistency', severity='MEDIUM', finding='m'),
        RiskCheck(case_id='x', check_type='booking_plausibility', severity='LOW', finding='l'),
    ]
    assert compute_overall_risk(checks) == 'HIGH'


def test_compute_overall_empty():
    assert compute_overall_risk([]) == 'OK'


# ---------------------------------------------------------------------------
# build_risk_analyst_service — API-level (imported here for completeness)
# ---------------------------------------------------------------------------

def test_build_returns_service_without_key():
    from app.risk_analyst.service import build_risk_analyst_service
    from unittest.mock import MagicMock

    svc = build_risk_analyst_service(MagicMock(), None, None)
    assert svc._api_key is None
    assert svc._model == ''


def test_build_uses_ionos_prefix():
    from app.risk_analyst.service import build_risk_analyst_service
    from unittest.mock import MagicMock

    llm_repo = MagicMock()
    llm_repo.decrypt_key_for_call.return_value = 'my-key'
    config = {
        'model': 'openai/gpt-oss-120b',
        'provider': 'ionos',
        'base_url': 'https://openai.inference.de-txl.ionos.com/v1',
    }
    svc = build_risk_analyst_service(MagicMock(), llm_repo, config)
    assert svc._model == 'openai/openai/gpt-oss-120b'
    # IONOS always gets openai/ prefix — litellm strips outer openai/ → API receives openai/gpt-oss-120b
