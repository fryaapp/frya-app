import pytest

from app.audit.repository import AuditRepository
from app.audit.service import AuditService


@pytest.mark.asyncio
async def test_audit_hash_chain_in_memory():
    repo = AuditRepository('memory://audit')
    service = AuditService(repo)
    await service.initialize()

    first = await service.log_event(
        {
            'event_id': 'e1',
            'source': 'test',
            'agent_name': 'agent',
            'action': 'A',
            'result': 'ok1',
            'approval_status': 'NOT_REQUIRED',
        }
    )
    second = await service.log_event(
        {
            'event_id': 'e2',
            'source': 'test',
            'agent_name': 'agent',
            'action': 'B',
            'result': 'ok2',
            'approval_status': 'NOT_REQUIRED',
        }
    )

    assert first.record_hash
    assert second.previous_hash == first.record_hash
    assert second.record_hash != first.record_hash
