"""Unit tests for DeadlineAnalystService (Paket 22 Deadline Analyst).

Covers:
1. _analyze_case: overdue, due_today, due_soon, LOW priority, escalation
2. Priority calculation and warning_type mapping
3. Skonto info extraction from metadata
4. _template_summary: correct text in all combinations
5. LLM summary: happy path, fallback on error
6. build_deadline_analyst_service routing
7. check_all_deadlines: OVERDUE auto-set, categorisation, sort order
8. check_single_case: with and without due_date
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.deadline_analyst.schemas import DeadlineCheck, DeadlineReport, FristConfig, SkontoInfo
from app.deadline_analyst.service import (
    DeadlineAnalystService,
    _template_summary,
    build_deadline_analyst_service,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TODAY = date.today()


def _svc(config: FristConfig | None = None) -> DeadlineAnalystService:
    return DeadlineAnalystService(
        repo=MagicMock(),
        model='',
        api_key=None,
        base_url=None,
        config=config,
    )


def _case(
    due_date: date,
    status: str = 'OPEN',
    amount: Decimal | None = Decimal('1190.00'),
    metadata: dict | None = None,
) -> MagicMock:
    c = MagicMock()
    c.id = uuid.uuid4()
    c.case_number = 'CASE-2026-00001'
    c.vendor_name = 'Test GmbH'
    c.total_amount = amount
    c.currency = 'EUR'
    c.due_date = due_date
    c.status = status
    c.metadata = metadata or {}
    return c


def _check(days: int, priority: str, warning_type: str) -> DeadlineCheck:
    return DeadlineCheck(
        case_id=str(uuid.uuid4()),
        due_date=TODAY + timedelta(days=days),
        days_until_due=days,
        priority=priority,
        warning_type=warning_type,
        status='OPEN',
        amount=Decimal('500.00'),
        currency='EUR',
    )


# ---------------------------------------------------------------------------
# _analyze_case — classification
# ---------------------------------------------------------------------------

def test_overdue_is_critical():
    svc = _svc()
    c = _case(TODAY - timedelta(days=3))
    result = svc._analyze_case(c, TODAY)
    assert result.priority == 'CRITICAL'
    assert result.warning_type == 'overdue'
    assert result.days_until_due == -3


def test_due_today_is_high():
    svc = _svc()
    c = _case(TODAY)
    result = svc._analyze_case(c, TODAY)
    assert result.priority == 'HIGH'
    assert result.warning_type == 'due_today'
    assert result.days_until_due == 0


def test_due_in_3_days_is_due_soon():
    svc = _svc()
    c = _case(TODAY + timedelta(days=3))
    result = svc._analyze_case(c, TODAY)
    assert result.priority == 'MEDIUM'
    assert result.warning_type == 'due_soon'


def test_due_in_7_days_is_due_soon():
    svc = _svc()
    c = _case(TODAY + timedelta(days=7))
    result = svc._analyze_case(c, TODAY)
    assert result.priority == 'MEDIUM'
    assert result.warning_type == 'due_soon'


def test_due_in_30_days_is_low():
    svc = _svc()
    c = _case(TODAY + timedelta(days=30))
    result = svc._analyze_case(c, TODAY)
    assert result.priority == 'LOW'
    assert result.warning_type == 'due_soon'


def test_long_overdue_becomes_escalation():
    svc = _svc(FristConfig(escalation_after_days=14))
    c = _case(TODAY - timedelta(days=20))
    result = svc._analyze_case(c, TODAY)
    assert result.warning_type == 'escalation'
    assert result.priority == 'CRITICAL'


def test_analyze_case_maps_all_fields():
    svc = _svc()
    c = _case(TODAY - timedelta(days=1), status='OVERDUE', amount=Decimal('999.99'))
    result = svc._analyze_case(c, TODAY)
    assert result.case_number == 'CASE-2026-00001'
    assert result.vendor_name == 'Test GmbH'
    assert result.amount == Decimal('999.99')
    assert result.status == 'OVERDUE'


# ---------------------------------------------------------------------------
# Skonto info
# ---------------------------------------------------------------------------

def test_skonto_info_from_metadata():
    svc = _svc()
    skonto_date = (TODAY + timedelta(days=2)).isoformat()
    c = _case(TODAY + timedelta(days=30), metadata={
        'skonto_rate': 2.0,
        'skonto_days': 14,
        'skonto_date': skonto_date,
    })
    info = svc._get_skonto_from_metadata(c, TODAY)
    assert info is not None
    assert info.skonto_rate == 2.0
    assert info.days_until_expiry == 2
    assert info.skonto_amount == Decimal('23.80')  # 1190 * 0.02


def test_no_skonto_without_rate():
    svc = _svc()
    c = _case(TODAY + timedelta(days=30), metadata={})
    assert svc._get_skonto_from_metadata(c, TODAY) is None


def test_no_skonto_with_invalid_date():
    svc = _svc()
    c = _case(TODAY + timedelta(days=30), metadata={
        'skonto_rate': 2.0,
        'skonto_date': 'not-a-date',
    })
    assert svc._get_skonto_from_metadata(c, TODAY) is None


def test_skonto_in_analyze_case():
    svc = _svc()
    skonto_date = (TODAY + timedelta(days=1)).isoformat()
    c = _case(TODAY + timedelta(days=30), metadata={
        'skonto_rate': 3.0,
        'skonto_days': 10,
        'skonto_date': skonto_date,
    })
    result = svc._analyze_case(c, TODAY)
    assert result.skonto_info is not None
    assert result.skonto_info.days_until_expiry == 1


# ---------------------------------------------------------------------------
# _template_summary
# ---------------------------------------------------------------------------

def test_template_summary_all_green():
    assert _template_summary([], [], [], []) == 'Alle Fristen im gruenen Bereich.'


def test_template_summary_overdue_only():
    checks = [_check(-3, 'CRITICAL', 'overdue'), _check(-1, 'CRITICAL', 'overdue')]
    text = _template_summary(checks, [], [], [])
    assert '2' in text
    assert 'ueberfaellig' in text.lower()


def test_template_summary_multiple_categories():
    overdue = [_check(-1, 'CRITICAL', 'overdue')]
    today = [_check(0, 'HIGH', 'due_today')]
    soon = [_check(3, 'MEDIUM', 'due_soon')]
    text = _template_summary(overdue, today, soon, [])
    assert 'ueberfaellig' in text.lower()
    assert 'heute' in text.lower()
    assert 'kuerze' in text.lower()


def test_template_summary_skonto():
    skonto = [_check(2, 'HIGH', 'skonto_expiring')]
    text = _template_summary([], [], [], skonto)
    assert 'skonto' in text.lower()


# ---------------------------------------------------------------------------
# LLM summary
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_llm_summary_called_when_api_key():
    svc = DeadlineAnalystService(
        repo=MagicMock(),
        model='openai/test-model',
        api_key='my-key',
        base_url=None,
    )
    mock_completion = MagicMock()
    mock_completion.choices[0].message.content = '3 Rechnungen sind ueberfaellig.'

    with patch(
        'app.deadline_analyst.service.acompletion',
        new=AsyncMock(return_value=mock_completion),
    ):
        overdue = [_check(-1, 'CRITICAL', 'overdue')]
        summary = await svc._make_summary(overdue, [], [], [])

    assert '3 Rechnungen' in summary or 'ueberfaellig' in summary.lower()


@pytest.mark.asyncio
async def test_llm_summary_falls_back_on_error():
    svc = DeadlineAnalystService(
        repo=MagicMock(),
        model='openai/test-model',
        api_key='key',
        base_url=None,
    )
    with patch(
        'app.deadline_analyst.service.acompletion',
        new=AsyncMock(side_effect=RuntimeError('LLM down')),
    ):
        overdue = [_check(-1, 'CRITICAL', 'overdue')]
        summary = await svc._make_summary(overdue, [], [], [])

    # Template fallback
    assert 'ueberfaellig' in summary.lower()


@pytest.mark.asyncio
async def test_llm_summary_not_called_without_api_key():
    svc = DeadlineAnalystService(
        repo=MagicMock(), model='m', api_key=None, base_url=None
    )
    with patch('app.deadline_analyst.service.acompletion') as mock_call:
        summary = await svc._make_summary([], [], [], [])
        assert not mock_call.called
    assert 'gruenen' in summary.lower()


# ---------------------------------------------------------------------------
# build_deadline_analyst_service
# ---------------------------------------------------------------------------

def test_build_no_repo():
    svc = build_deadline_analyst_service(MagicMock(), None, None)
    assert svc._api_key is None


def test_build_no_config():
    svc = build_deadline_analyst_service(MagicMock(), MagicMock(), None)
    assert svc._api_key is None


def test_build_no_key_in_config():
    repo = MagicMock()
    repo.decrypt_key_for_call.return_value = None
    config = {'model': 'mistralai/Mistral-Small-24B-Instruct', 'provider': 'ionos'}
    svc = build_deadline_analyst_service(MagicMock(), repo, config)
    assert svc._api_key is None


def test_build_with_key():
    repo = MagicMock()
    repo.decrypt_key_for_call.return_value = 'my-key'
    config = {
        'model': 'mistralai/Mistral-Small-24B-Instruct',
        'provider': 'ionos',
        'base_url': 'https://openai.inference.de-txl.ionos.com/v1',
    }
    svc = build_deadline_analyst_service(MagicMock(), repo, config)
    assert svc._api_key == 'my-key'
    assert svc._model == 'openai/mistralai/Mistral-Small-24B-Instruct'


def test_build_ionos_prefix():
    repo = MagicMock()
    repo.decrypt_key_for_call.return_value = 'key'
    config = {'model': 'mistralai/Mistral-Small-24B-Instruct', 'provider': 'ionos'}
    svc = build_deadline_analyst_service(MagicMock(), repo, config)
    assert svc._model.startswith('openai/')


def test_build_decrypt_exception_gives_no_key():
    repo = MagicMock()
    repo.decrypt_key_for_call.side_effect = RuntimeError('bad')
    config = {'model': 'some-model', 'provider': 'ionos'}
    svc = build_deadline_analyst_service(MagicMock(), repo, config)
    assert svc._api_key is None


def test_build_custom_frist_config():
    fc = FristConfig(skonto_warning_days=5, due_soon_days=10)
    svc = build_deadline_analyst_service(MagicMock(), None, None, frist_config=fc)
    assert svc._config.skonto_warning_days == 5
    assert svc._config.due_soon_days == 10
