import pytest

from app.open_items.repository import OpenItemsRepository
from app.open_items.service import OpenItemsService


@pytest.mark.asyncio
async def test_open_items_persistence_and_status_transitions():
    repo = OpenItemsRepository('memory://open-items')
    service = OpenItemsService(repo, 'memory://redis')
    await service.initialize()

    item = await service.create_item(case_id='case-1', title='Titel', description='Beschreibung', source='test')
    assert item.status == 'OPEN'
    assert item.case_id == 'case-1'

    updated = await service.update_status(item.item_id, 'WAITING_USER')
    assert updated is not None
    assert updated.status == 'WAITING_USER'

    scheduled = await service.schedule_follow_up(item.item_id, '2030-01-01T00:00:00Z')
    assert scheduled is not None
    assert scheduled.status == 'SCHEDULED'
    assert scheduled.reminder_job_id is not None

    listed = await service.list_items()
    assert any(x.item_id == item.item_id for x in listed)

    by_case = await service.list_by_case('case-1')
    assert any(x.item_id == item.item_id for x in by_case)
