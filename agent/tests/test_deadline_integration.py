"""Integration tests for DeadlineAnalystService with CaseRepository memory backend.

Tests the full pipeline:
- Create cases with/without due_date
- Run check_all_deadlines
- Verify OVERDUE auto-set, categorisation, metadata update
- Verify skonto detection
- Verify sort order (most urgent first)
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

from app.case_engine.repository import CaseRepository
from app.deadline_analyst.schemas import FristConfig
from app.deadline_analyst.service import DeadlineAnalystService


TODAY = date.today()
TENANT_ID = uuid.uuid4()


async def _create_case(repo: CaseRepository, *, due_date: date | None, status: str = 'OPEN',
                       amount: Decimal | None = None, metadata: dict | None = None):
    """Create a case and optionally force its status."""
    case = await repo.create_case(
        tenant_id=TENANT_ID,
        case_type='incoming_invoice',
        vendor_name='Test GmbH',
        total_amount=amount or Decimal('595.00'),
        due_date=due_date,
        metadata=metadata or {},
    )
    if status == 'OPEN' and case.status == 'DRAFT':
        # Add a document so we can open it
        await repo.add_document_to_case(
            case_id=case.id,
            document_source='manual',
            document_source_id='test-doc-1',
            assignment_confidence='HIGH',
            assignment_method='manual',
        )
        case = await repo.update_case_status(case.id, 'OPEN', operator=False)
    return case


def _svc(repo: CaseRepository) -> DeadlineAnalystService:
    return DeadlineAnalystService(repo=repo, model='', api_key=None, base_url=None)


# ---------------------------------------------------------------------------
# OPEN → OVERDUE auto-set
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_overdue_case_gets_set_to_overdue():
    repo = CaseRepository('memory://test')
    await repo.initialize()
    await _create_case(repo, due_date=TODAY - timedelta(days=5))

    svc = _svc(repo)
    report = await svc.check_all_deadlines(TENANT_ID)

    assert len(report.overdue) == 1
    overdue_check = report.overdue[0]
    assert overdue_check.status == 'OVERDUE'
    assert overdue_check.days_until_due == -5

    # Verify in DB
    case = await repo.get_case(uuid.UUID(overdue_check.case_id))
    assert case.status == 'OVERDUE'


@pytest.mark.asyncio
async def test_already_overdue_case_stays_overdue():
    repo = CaseRepository('memory://test')
    await repo.initialize()
    case = await _create_case(repo, due_date=TODAY - timedelta(days=3))
    # Force to OVERDUE first
    await repo.update_case_status(case.id, 'OVERDUE')

    svc = _svc(repo)
    report = await svc.check_all_deadlines(TENANT_ID)

    assert len(report.overdue) == 1
    assert report.overdue[0].status == 'OVERDUE'


@pytest.mark.asyncio
async def test_case_without_due_date_not_checked():
    repo = CaseRepository('memory://test')
    await repo.initialize()
    await _create_case(repo, due_date=None)

    svc = _svc(repo)
    report = await svc.check_all_deadlines(TENANT_ID)

    assert report.total_cases_checked == 0
    assert len(report.overdue) == 0


# ---------------------------------------------------------------------------
# Categorisation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_due_today_categorised_correctly():
    repo = CaseRepository('memory://test')
    await repo.initialize()
    await _create_case(repo, due_date=TODAY)

    svc = _svc(repo)
    report = await svc.check_all_deadlines(TENANT_ID)

    assert len(report.due_today) == 1
    assert len(report.overdue) == 0
    assert report.due_today[0].days_until_due == 0


@pytest.mark.asyncio
async def test_due_soon_categorised_correctly():
    repo = CaseRepository('memory://test')
    await repo.initialize()
    await _create_case(repo, due_date=TODAY + timedelta(days=5))

    svc = _svc(repo)
    report = await svc.check_all_deadlines(TENANT_ID)

    assert len(report.due_soon) == 1
    assert len(report.overdue) == 0


@pytest.mark.asyncio
async def test_multiple_categories_in_one_report():
    repo = CaseRepository('memory://test')
    await repo.initialize()
    await _create_case(repo, due_date=TODAY - timedelta(days=2))   # overdue
    await _create_case(repo, due_date=TODAY)                        # due_today
    await _create_case(repo, due_date=TODAY + timedelta(days=4))   # due_soon
    await _create_case(repo, due_date=TODAY + timedelta(days=30))  # not urgent

    svc = _svc(repo)
    report = await svc.check_all_deadlines(TENANT_ID)

    assert report.total_cases_checked == 4
    assert len(report.overdue) == 1
    assert len(report.due_today) == 1
    assert len(report.due_soon) == 2  # 4 days + 30 days both in 'due_soon'


@pytest.mark.asyncio
async def test_overdue_sorted_most_urgent_first():
    repo = CaseRepository('memory://test')
    await repo.initialize()
    await _create_case(repo, due_date=TODAY - timedelta(days=1))
    await _create_case(repo, due_date=TODAY - timedelta(days=10))
    await _create_case(repo, due_date=TODAY - timedelta(days=5))

    svc = _svc(repo)
    report = await svc.check_all_deadlines(TENANT_ID)

    days = [c.days_until_due for c in report.overdue]
    assert days == sorted(days)  # most overdue (most negative) first


# ---------------------------------------------------------------------------
# Metadata update
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_deadline_metadata_written_to_case():
    repo = CaseRepository('memory://test')
    await repo.initialize()
    case = await _create_case(repo, due_date=TODAY + timedelta(days=5))

    svc = _svc(repo)
    await svc.check_all_deadlines(TENANT_ID)

    refreshed = await repo.get_case(case.id)
    assert 'deadline_last_checked' in refreshed.metadata
    assert refreshed.metadata['deadline_priority'] == 'MEDIUM'


@pytest.mark.asyncio
async def test_critical_priority_in_metadata():
    repo = CaseRepository('memory://test')
    await repo.initialize()
    case = await _create_case(repo, due_date=TODAY - timedelta(days=3))

    svc = _svc(repo)
    await svc.check_all_deadlines(TENANT_ID)

    refreshed = await repo.get_case(case.id)
    assert refreshed.metadata['deadline_priority'] == 'CRITICAL'


# ---------------------------------------------------------------------------
# Skonto detection
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_skonto_expiring_detected():
    repo = CaseRepository('memory://test')
    await repo.initialize()
    skonto_date = (TODAY + timedelta(days=2)).isoformat()
    await _create_case(
        repo,
        due_date=TODAY + timedelta(days=30),
        metadata={'skonto_rate': 2.0, 'skonto_days': 14, 'skonto_date': skonto_date},
    )

    svc = _svc(repo)
    report = await svc.check_all_deadlines(TENANT_ID)

    assert len(report.skonto_expiring) == 1
    si = report.skonto_expiring[0].skonto_info
    assert si is not None
    assert si.days_until_expiry == 2


@pytest.mark.asyncio
async def test_skonto_not_expiring_not_in_list():
    repo = CaseRepository('memory://test')
    await repo.initialize()
    skonto_date = (TODAY + timedelta(days=10)).isoformat()
    await _create_case(
        repo,
        due_date=TODAY + timedelta(days=30),
        metadata={'skonto_rate': 2.0, 'skonto_days': 14, 'skonto_date': skonto_date},
    )

    svc = _svc(repo)
    report = await svc.check_all_deadlines(TENANT_ID)

    assert len(report.skonto_expiring) == 0


# ---------------------------------------------------------------------------
# check_single_case
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_check_single_case_overdue():
    repo = CaseRepository('memory://test')
    await repo.initialize()
    case = await _create_case(repo, due_date=TODAY - timedelta(days=7))

    svc = _svc(repo)
    check = await svc.check_single_case(case.id)

    assert check is not None
    assert check.priority == 'CRITICAL'
    assert check.days_until_due == -7


@pytest.mark.asyncio
async def test_check_single_case_no_due_date_returns_none():
    repo = CaseRepository('memory://test')
    await repo.initialize()
    case = await repo.create_case(
        tenant_id=TENANT_ID,
        case_type='incoming_invoice',
        due_date=None,
    )

    svc = _svc(repo)
    check = await svc.check_single_case(case.id)
    assert check is None


@pytest.mark.asyncio
async def test_check_single_case_not_found_returns_none():
    repo = CaseRepository('memory://test')
    await repo.initialize()
    svc = _svc(repo)
    check = await svc.check_single_case(uuid.uuid4())
    assert check is None


# ---------------------------------------------------------------------------
# total_overdue_amount
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_total_overdue_amount_summed():
    repo = CaseRepository('memory://test')
    await repo.initialize()
    await _create_case(repo, due_date=TODAY - timedelta(days=1), amount=Decimal('1000.00'))
    await _create_case(repo, due_date=TODAY - timedelta(days=2), amount=Decimal('500.00'))

    svc = _svc(repo)
    report = await svc.check_all_deadlines(TENANT_ID)

    assert report.total_overdue_amount == Decimal('1500.00')


# ---------------------------------------------------------------------------
# get_skonto_info
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_skonto_info_returns_info():
    repo = CaseRepository('memory://test')
    await repo.initialize()
    skonto_date = (TODAY + timedelta(days=3)).isoformat()
    case = await repo.create_case(
        tenant_id=TENANT_ID,
        case_type='incoming_invoice',
        total_amount=Decimal('1190.00'),
        metadata={'skonto_rate': 2.0, 'skonto_days': 14, 'skonto_date': skonto_date},
    )

    svc = _svc(repo)
    info = await svc.get_skonto_info(case.id)

    assert info is not None
    assert info.skonto_rate == 2.0
    assert info.days_until_expiry == 3
    assert info.skonto_amount == Decimal('23.80')


@pytest.mark.asyncio
async def test_get_skonto_info_not_found_returns_none():
    repo = CaseRepository('memory://test')
    await repo.initialize()
    svc = _svc(repo)
    info = await svc.get_skonto_info(uuid.uuid4())
    assert info is None
