from __future__ import annotations

from app.open_items.service import OpenItemsService


class FollowUpOrchestrator:
    """Delegates follow-up timing to n8n via OpenItemsService.

    This module intentionally does not run a local Python scheduler.
    """

    def __init__(self, service: OpenItemsService) -> None:
        self.service = service

    async def schedule_via_n8n(self, item_id: str, remind_at_iso: str):
        return await self.service.schedule_follow_up(item_id, remind_at_iso)
