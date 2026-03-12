from __future__ import annotations

from app.jobs.queue import RedisJobBackbone


class ReminderQueue:
    def __init__(self, backbone: RedisJobBackbone) -> None:
        self.backbone = backbone

    async def enqueue(self, payload: dict) -> str:
        return await self.backbone.push('reminders', payload)
