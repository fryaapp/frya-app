"""API endpoint tests for deadline routes (Paket 22).

Tests:
- DeadlineReport and DeadlineCheck schema defaults
- build_deadline_analyst_service routing (via API layer logic)
- FristConfig defaults
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.deadline_analyst.schemas import (
    DeadlineCheck,
    DeadlineReport,
    FristConfig,
    SkontoInfo,
)
from app.deadline_analyst.service import _template_summary


TODAY = date.today()


# ---------------------------------------------------------------------------
# Schema defaults
# ---------------------------------------------------------------------------

def test_deadline_check_defaults():
    check = DeadlineCheck(
        case_id='abc',
        due_date=TODAY,
        days_until_due=0,
        priority='HIGH',
        warning_type='due_today',
        status='OPEN',
    )
    assert check.currency == 'EUR'
    assert check.vendor_name is None
    assert check.skonto_info is None


def test_deadline_report_defaults():
    report = DeadlineReport(tenant_id='t', checked_at='2026-03-18T12:00:00+00:00', total_cases_checked=0)
    assert report.overdue == []
    assert report.due_today == []
    assert report.due_soon == []
    assert report.skonto_expiring == []
    assert report.analyst_version == 'deadline-analyst-v1'
    assert report.total_overdue_amount is None


def test_frist_config_defaults():
    fc = FristConfig()
    assert fc.skonto_warning_days == 3
    assert fc.due_soon_days == 7
    assert fc.escalation_after_days == 14


def test_skonto_info_model():
    si = SkontoInfo(
        skonto_rate=2.0,
        skonto_days=14,
        skonto_date=TODAY + timedelta(days=5),
        skonto_amount=Decimal('23.80'),
        days_until_expiry=5,
    )
    assert si.skonto_rate == 2.0
    assert si.skonto_amount == Decimal('23.80')


# ---------------------------------------------------------------------------
# Report serialisation
# ---------------------------------------------------------------------------

def test_report_serialises_without_error():
    check = DeadlineCheck(
        case_id='abc',
        due_date=TODAY - timedelta(days=3),
        days_until_due=-3,
        priority='CRITICAL',
        warning_type='overdue',
        status='OVERDUE',
        amount=Decimal('1190.00'),
    )
    report = DeadlineReport(
        tenant_id='t1',
        checked_at='2026-03-18T08:00:00+00:00',
        total_cases_checked=1,
        overdue=[check],
        summary_text='1 Rechnung ueberfaellig.',
        total_overdue_amount=Decimal('1190.00'),
    )
    data = report.model_dump(mode='json')
    assert data['overdue'][0]['priority'] == 'CRITICAL'
    assert data['analyst_version'] == 'deadline-analyst-v1'


# ---------------------------------------------------------------------------
# Template summary edge cases
# ---------------------------------------------------------------------------

def _make_check(days: int) -> DeadlineCheck:
    wt = 'overdue' if days < 0 else ('due_today' if days == 0 else 'due_soon')
    pr = 'CRITICAL' if days < 0 else ('HIGH' if days == 0 else 'MEDIUM')
    return DeadlineCheck(
        case_id=str(uuid.uuid4()),
        due_date=TODAY + timedelta(days=days),
        days_until_due=days,
        priority=pr,
        warning_type=wt,
        status='OPEN',
        amount=Decimal('500.00'),
        currency='EUR',
    )


def test_summary_amount_in_overdue_text():
    checks = [_make_check(-1), _make_check(-2)]
    text = _template_summary(checks, [], [], [])
    assert 'EUR' in text
    assert 'ueberfaellig' in text.lower()


def test_summary_ends_with_period():
    text = _template_summary([_make_check(-1)], [], [], [])
    assert text.endswith('.')


def test_summary_all_green_no_data():
    text = _template_summary([], [], [], [])
    assert 'gruenen' in text.lower()
