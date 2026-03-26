"""Tests for P-43: Memory Architecture."""
import pytest
import uuid


@pytest.mark.asyncio
async def test_context_assembly_includes_cases():
    """get_context_assembly returns AKTUELLE VORGAENGE block when cases exist."""
    from decimal import Decimal
    from app.memory_curator.service import MemoryCuratorService
    from app.case_engine.repository import CaseRepository
    from pathlib import Path
    import tempfile

    repo = CaseRepository('memory://test')
    tid = uuid.uuid4()
    await repo.create_case(tenant_id=tid, case_type='incoming_invoice',
                           vendor_name='Test GmbH', total_amount=Decimal('100.00'),
                           currency='EUR', created_by='test')

    with tempfile.TemporaryDirectory() as tmpdir:
        svc = MemoryCuratorService(data_dir=Path(tmpdir), case_repository=repo)
        ctx = await svc.get_context_assembly(tid)
    assert '[AGENT]' in ctx
    assert '[PRINZIPIEN]' in ctx
    assert '[AKTUELLE VORGAENGE]' in ctx
    assert 'Test GmbH' in ctx


@pytest.mark.asyncio
async def test_build_current_case_detail():
    """_build_current_case_detail returns formatted case text."""
    from decimal import Decimal
    from app.memory_curator.service import MemoryCuratorService
    from app.case_engine.repository import CaseRepository
    from pathlib import Path
    import tempfile

    repo = CaseRepository('memory://test')
    tid = uuid.uuid4()
    case = await repo.create_case(tenant_id=tid, case_type='incoming_invoice',
                                   vendor_name='Detail GmbH', total_amount=Decimal('50.00'),
                                   currency='EUR', created_by='test')
    await repo.update_metadata(case.id, {
        'document_analysis': {'document_number': 'INV-001', 'sender': 'Detail GmbH'}
    })

    with tempfile.TemporaryDirectory() as tmpdir:
        svc = MemoryCuratorService(data_dir=Path(tmpdir), case_repository=repo)
        detail = await svc._build_current_case_detail(tid, str(case.id))
    assert detail is not None
    assert 'Detail GmbH' in detail
    assert 'INV-001' in detail


@pytest.mark.asyncio
async def test_context_assembly_with_effective_case_ref():
    """get_context_assembly includes AKTUELLER VORGANG when effective_case_ref is given."""
    from decimal import Decimal
    from app.memory_curator.service import MemoryCuratorService
    from app.case_engine.repository import CaseRepository
    from pathlib import Path
    import tempfile

    repo = CaseRepository('memory://test')
    tid = uuid.uuid4()
    case = await repo.create_case(tenant_id=tid, case_type='incoming_invoice',
                                   vendor_name='Vorgang GmbH', total_amount=Decimal('200.00'),
                                   currency='EUR', created_by='test')

    with tempfile.TemporaryDirectory() as tmpdir:
        svc = MemoryCuratorService(data_dir=Path(tmpdir), case_repository=repo)
        ctx = await svc.get_context_assembly(tid, effective_case_ref=str(case.id))
    assert '[AKTUELLER VORGANG]' in ctx
    assert 'Vorgang GmbH' in ctx


def test_memory_curator_context_has_required_blocks():
    """Verify the context assembly returns the expected block structure."""
    from app.memory_curator.service import MemoryCuratorService
    assert hasattr(MemoryCuratorService, 'get_context_assembly')
    assert hasattr(MemoryCuratorService, '_build_current_case_detail')
