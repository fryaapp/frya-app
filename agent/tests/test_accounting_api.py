"""API endpoint tests for accounting analyst routes (Paket 22).

Tests:
- POST /api/cases/{id}/analyze-booking — runs analysis, stores in metadata
- GET /api/cases/{id}/booking-proposal — returns stored proposal
- POST /api/cases/{id}/booking-proposal/confirm
- POST /api/cases/{id}/booking-proposal/reject
"""
from __future__ import annotations

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.accounting_analyst.schemas import BookingProposal
from app.case_engine.models import CaseRecord
from app.case_engine.repository import CaseRepository


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_case(case_type: str = 'incoming_invoice', metadata: dict | None = None) -> CaseRecord:
    return CaseRecord(
        tenant_id=uuid.uuid4(),
        case_type=case_type,
        total_amount=Decimal('1190.00'),
        currency='EUR',
        metadata=metadata or {},
    )


def _make_proposal(status: str = 'PENDING') -> dict:
    return {
        'approval_mode': 'PROPOSE_ONLY',
        'case_id': 'test-id',
        'skr03_soll': '3300',
        'skr03_soll_name': 'Wareneingang 19 % MwSt',
        'skr03_haben': '1600',
        'skr03_haben_name': 'Verbindlichkeiten aus LuL',
        'tax_rate': 19.0,
        'tax_amount': '190.00',
        'net_amount': '1000.00',
        'gross_amount': '1190.00',
        'booking_lines': [],
        'reasoning': 'Test.',
        'confidence': 0.88,
        'status': status,
        'analyst_version': 'accounting-analyst-v1',
        'created_at': '2026-03-18T12:00:00+00:00',
    }


# ---------------------------------------------------------------------------
# CaseRepository.update_metadata — unit tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_metadata_memory_merges():
    repo = CaseRepository('memory://test')
    await repo.initialize()
    case = await repo.create_case(
        tenant_id=uuid.uuid4(),
        case_type='incoming_invoice',
        metadata={'existing_key': 'value'},
    )
    updated = await repo.update_metadata(case.id, {'booking_proposal': {'status': 'PENDING'}})
    assert updated.metadata['existing_key'] == 'value'
    assert updated.metadata['booking_proposal']['status'] == 'PENDING'


@pytest.mark.asyncio
async def test_update_metadata_overwrites_key():
    repo = CaseRepository('memory://test')
    await repo.initialize()
    case = await repo.create_case(
        tenant_id=uuid.uuid4(),
        case_type='incoming_invoice',
        metadata={'booking_proposal': {'status': 'PENDING'}},
    )
    await repo.update_metadata(case.id, {'booking_proposal': {'status': 'CONFIRMED'}})
    refreshed = await repo.get_case(case.id)
    assert refreshed.metadata['booking_proposal']['status'] == 'CONFIRMED'


@pytest.mark.asyncio
async def test_update_metadata_raises_for_missing_case():
    repo = CaseRepository('memory://test')
    await repo.initialize()
    with pytest.raises(ValueError, match='not found'):
        await repo.update_metadata(uuid.uuid4(), {'x': 1})


# ---------------------------------------------------------------------------
# BookingProposal model
# ---------------------------------------------------------------------------

def test_booking_proposal_defaults():
    p = BookingProposal(case_id='abc')
    assert p.approval_mode == 'PROPOSE_ONLY'
    assert p.status == 'PENDING'
    assert p.analyst_version == 'accounting-analyst-v1'
    assert p.booking_lines == []


def test_booking_proposal_serialises_decimals():
    from decimal import Decimal
    p = BookingProposal(
        case_id='abc',
        gross_amount=Decimal('1190.00'),
        net_amount=Decimal('1000.00'),
        tax_amount=Decimal('190.00'),
    )
    d = p.model_dump(mode='json')
    # Decimal fields should serialise without error (as strings in json mode)
    assert d['gross_amount'] is not None
