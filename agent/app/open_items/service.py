from __future__ import annotations

import json
import uuid
from datetime import datetime

from redis.asyncio import Redis

from app.connectors.contracts import WorkflowConnector
from app.open_items.models import OpenItem, OpenItemStatus
from app.open_items.repository import OpenItemsRepository


class OpenItemsService:
    def __init__(
        self,
        repository: OpenItemsRepository,
        redis_url: str,
        workflow_connector: WorkflowConnector | None = None,
    ) -> None:
        self.repository = repository
        self.redis_url = redis_url
        self.workflow_connector = workflow_connector
        self._memory_jobs: dict[str, dict] = {}

    async def initialize(self) -> None:
        await self.repository.setup()

    def _use_memory_queue(self) -> bool:
        return self.redis_url.startswith('memory://')

    async def _enqueue(self, queue: str, payload: dict) -> str:
        job_id = payload.get('job_id', str(uuid.uuid4()))
        payload['job_id'] = job_id
        if self._use_memory_queue():
            self._memory_jobs[job_id] = {'queue': queue, 'payload': payload}
            return job_id

        redis = Redis.from_url(self.redis_url, decode_responses=True)
        try:
            await redis.rpush(f'frya:{queue}', json.dumps(payload))
            return job_id
        finally:
            await redis.close()

    async def create_item(
        self,
        case_id: str,
        title: str,
        description: str,
        source: str = 'agent',
        document_ref: str | None = None,
        accounting_ref: str | None = None,
    ) -> OpenItem:
        now = datetime.utcnow()
        item = OpenItem(
            item_id=str(uuid.uuid4()),
            case_id=case_id,
            title=title,
            description=description,
            source=source,
            document_ref=document_ref,
            accounting_ref=accounting_ref,
            created_at=now,
            updated_at=now,
        )
        await self.repository.upsert(item)
        await self._enqueue('open-items', {'type': 'OPEN_ITEM_CREATED', 'item_id': item.item_id, 'case_id': case_id})
        return item

    async def update_status(self, item_id: str, status: OpenItemStatus) -> OpenItem | None:
        current = await self.repository.get(item_id)
        if current is None:
            return None
        updated = current.model_copy(update={'status': status, 'updated_at': datetime.utcnow()})
        await self.repository.upsert(updated)
        await self._enqueue(
            'open-items',
            {'type': 'OPEN_ITEM_STATUS_CHANGED', 'item_id': item_id, 'case_id': updated.case_id, 'status': status},
        )
        return updated

    async def schedule_follow_up(self, item_id: str, remind_at_iso: str) -> OpenItem | None:
        """No local Python scheduler.

        Follow-up timing is delegated to n8n. Frya only persists intent and emits deterministic trigger.
        """
        current = await self.repository.get(item_id)
        if current is None:
            return None

        payload = {'type': 'FOLLOW_UP_REQUESTED', 'item_id': item_id, 'case_id': current.case_id, 'remind_at': remind_at_iso}
        queue_job_id = await self._enqueue('jobs', payload)

        external_job_id = None
        if self.workflow_connector is not None:
            trigger_result = await self.workflow_connector.trigger(
                workflow_name='frya-follow-up',
                payload=payload,
                idempotency_key=queue_job_id,
            )
            if trigger_result.get('ok'):
                external_job_id = queue_job_id

        updated = current.model_copy(
            update={
                'status': 'SCHEDULED',
                'reminder_job_id': external_job_id or queue_job_id,
                'updated_at': datetime.utcnow(),
            }
        )
        await self.repository.upsert(updated)
        return updated

    async def list_items(self, status: OpenItemStatus | None = None) -> list[OpenItem]:
        return list(await self.repository.list(status=status))

    async def list_by_case(self, case_id: str) -> list[OpenItem]:
        return list(await self.repository.list_by_case(case_id=case_id))
