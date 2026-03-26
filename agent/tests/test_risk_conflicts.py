"""Integration tests for automatic CaseConflict creation in RiskAnalystService.

Uses the real CaseRepository memory backend to verify that HIGH/CRITICAL findings
result in CaseConflict records being written to the repository.
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.case_engine.repository import CaseRepository
from app.risk_analyst.service import RiskAnalystService

TENANT_ID = uuid.uuid4()


async def _create_open_case(
    repo: CaseRepository,
    *,
    vendor_name: str | None = 'Test GmbH',
    total_amount: Decimal | None = Decimal('1190.00'),
    metadata: dict | None = None,
) -> object:
    case = await repo.create_case(
        tenant_id=TENANT_ID,
        case_type='incoming_invoice',
        vendor_name=vendor_name,
        total_amount=total_amount,
        metadata=metadata or {},
    )
    await repo.add_document_to_case(
        case_id=case.id,
        document_source='manual',
        document_source_id='test-doc-001',
        assignment_confidence='HIGH',
        assignment_method='manual',
    )
    case = await repo.update_case_status(case.id, 'OPEN', operator=False)
    return case


def _svc(repo: CaseRepository) -> RiskAnalystService:
    return RiskAnalystService(repo=repo, model='', api_key=None, base_url=None)


# ---------------------------------------------------------------------------
# No conflict when all checks pass
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_no_conflict_created_when_all_ok():
    """A clean case with a good booking proposal generates no conflicts."""
    repo = CaseRepository('memory://test')
    await repo.initialize()
    bp = {
        'skr03_soll': '3300',
        'skr03_haben': '1600',
        'tax_rate': 19.0,
        'net_amount': '1000.00',
        'tax_amount': '190.00',
        'gross_amount': '1190.00',
        'confidence': 0.9,
    }
    case = await _create_open_case(repo, total_amount=Decimal('1190.00'), metadata={'booking_proposal': bp})

    svc = _svc(repo)
    report = await svc.analyze_case(case.id)

    assert report is not None
    conflicts = await repo.get_conflicts(case.id)
    assert len(conflicts) == 0


# ---------------------------------------------------------------------------
# Conflict created for HIGH: low booking confidence
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_conflict_created_for_low_confidence_booking():
    """Confidence < 0.5 → HIGH → CaseConflict with conflict_type='amount_mismatch'."""
    repo = CaseRepository('memory://test')
    await repo.initialize()
    bp = {
        'skr03_soll': '3300', 'skr03_haben': '1600',
        'confidence': 0.2,
    }
    case = await _create_open_case(repo, metadata={'booking_proposal': bp})

    svc = _svc(repo)
    report = await svc.analyze_case(case.id)

    assert report is not None
    assert report.overall_risk == 'HIGH'

    conflicts = await repo.get_conflicts(case.id)
    assert len(conflicts) >= 1
    conflict_types = {c.conflict_type for c in conflicts}
    # booking_plausibility HIGH → amount_mismatch
    assert 'amount_mismatch' in conflict_types


# ---------------------------------------------------------------------------
# Conflict created for HIGH: invalid tax rate
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_conflict_created_for_invalid_tax_rate():
    """Invalid tax rate 13% → HIGH → CaseConflict."""
    repo = CaseRepository('memory://test')
    await repo.initialize()
    bp = {
        'skr03_soll': '3300', 'skr03_haben': '1600',
        'tax_rate': 13.0,
        'net_amount': '1000.00',
        'tax_amount': '130.00',
        'gross_amount': '1130.00',
        'confidence': 0.85,
    }
    case = await _create_open_case(repo, total_amount=Decimal('1130.00'), metadata={'booking_proposal': bp})

    svc = _svc(repo)
    report = await svc.analyze_case(case.id)

    assert report is not None
    conflicts = await repo.get_conflicts(case.id)
    tax_conflicts = [c for c in conflicts if c.conflict_type == 'amount_mismatch']
    assert len(tax_conflicts) >= 1


# ---------------------------------------------------------------------------
# Conflict created for HIGH: duplicate case
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_conflict_created_for_duplicate_case():
    """Duplicate detection HIGH → CaseConflict with conflict_type='duplicate_case'."""
    repo = CaseRepository('memory://test')
    await repo.initialize()

    # Create two cases with same vendor + amount
    await _create_open_case(repo, vendor_name='ACME GmbH', total_amount=Decimal('500.00'))
    case2 = await _create_open_case(repo, vendor_name='ACME GmbH', total_amount=Decimal('500.00'))

    svc = _svc(repo)
    report = await svc.analyze_case(case2.id)

    assert report is not None
    conflicts = await repo.get_conflicts(case2.id)
    dup_conflicts = [c for c in conflicts if c.conflict_type == 'duplicate_case']
    assert len(dup_conflicts) >= 1
    assert 'risk-analyst-v1' in dup_conflicts[0].metadata.get('source', '')


# ---------------------------------------------------------------------------
# Conflict not created for MEDIUM findings
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_no_conflict_for_medium_finding():
    """MEDIUM findings do NOT create conflicts (only HIGH/CRITICAL do)."""
    repo = CaseRepository('memory://test')
    await repo.initialize()
    # vendor_consistency MEDIUM: case vendor vs doc_analysis vendor mismatch
    meta = {
        'document_analysis': {'vendor_name': 'XYZ Corp'},
        'booking_proposal': {
            'skr03_soll': '3300', 'skr03_haben': '1600',
            'confidence': 0.9,
            'tax_rate': 19.0,
            'net_amount': '1000.00',
            'tax_amount': '190.00',
            'gross_amount': '1190.00',
        },
    }
    case = await _create_open_case(
        repo,
        vendor_name='Lieferant ABC GmbH',
        total_amount=Decimal('1190.00'),
        metadata=meta,
    )

    svc = _svc(repo)
    report = await svc.analyze_case(case.id)

    # Vendor consistency should be MEDIUM
    vendor_check = next(
        (c for c in report.checks if c.check_type == 'vendor_consistency'), None
    )
    assert vendor_check is not None

    conflicts = await repo.get_conflicts(case.id)
    # No conflicts expected (MEDIUM is not auto-conflicted)
    assert len(conflicts) == 0


# ---------------------------------------------------------------------------
# Metadata written after analysis
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_risk_report_written_to_metadata():
    """After analyze_case, case.metadata['risk_report'] must be populated."""
    repo = CaseRepository('memory://test')
    await repo.initialize()
    case = await _create_open_case(repo)

    svc = _svc(repo)
    await svc.analyze_case(case.id)

    refreshed = await repo.get_case(case.id)
    assert 'risk_report' in refreshed.metadata
    rr = refreshed.metadata['risk_report']
    assert rr['analyst_version'] == 'risk-analyst-v1'
    assert len(rr['checks']) == 5


# ---------------------------------------------------------------------------
# scan_all_open_cases
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_scan_all_returns_all_open_cases():
    repo = CaseRepository('memory://test')
    await repo.initialize()
    await _create_open_case(repo)
    await _create_open_case(repo, vendor_name='Other GmbH', total_amount=Decimal('500.00'))

    svc = _svc(repo)
    reports = await svc.scan_all_open_cases(TENANT_ID)

    assert len(reports) == 2


@pytest.mark.asyncio
async def test_scan_all_sorted_high_first():
    repo = CaseRepository('memory://test')
    await repo.initialize()

    # Case with high risk (low confidence)
    await _create_open_case(
        repo,
        metadata={'booking_proposal': {'confidence': 0.1, 'skr03_soll': None, 'skr03_haben': None}},
    )
    # Case with OK (good booking proposal)
    bp_ok = {
        'skr03_soll': '3300', 'skr03_haben': '1600', 'confidence': 0.95,
        'tax_rate': 19.0, 'net_amount': '1000.00',
        'tax_amount': '190.00', 'gross_amount': '1190.00',
    }
    await _create_open_case(repo, metadata={'booking_proposal': bp_ok})

    svc = _svc(repo)
    reports = await svc.scan_all_open_cases(TENANT_ID)

    order = {'HIGH': 0, 'MEDIUM': 1, 'LOW': 2, 'OK': 3}
    risks = [r.overall_risk for r in reports]
    assert risks == sorted(risks, key=lambda r: order.get(r, 9))
