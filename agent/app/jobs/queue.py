from __future__ import annotations

import json
import uuid
from collections import deque

from redis.asyncio import Redis


class RedisJobBackbone:
    def __init__(self, redis_url: str) -> None:
        self.redis_url = redis_url
        self._memory_queues: dict[str, deque[str]] = {
            'jobs': deque(),
            'retries': deque(),
            'dead-letter': deque(),
            'reminders': deque(),
        }

    def _is_memory(self) -> bool:
        return self.redis_url.startswith('memory://')

    async def push(self, queue: str, payload: dict) -> str:
        job_id = payload.get('job_id', str(uuid.uuid4()))
        payload['job_id'] = job_id
        encoded = json.dumps(payload, ensure_ascii=False)

        if self._is_memory():
            self._memory_queues.setdefault(queue, deque()).append(encoded)
            return job_id

        redis = Redis.from_url(self.redis_url, decode_responses=True)
        try:
            await redis.rpush(f'frya:{queue}', encoded)
            return job_id
        finally:
            await redis.close()

    async def pop(self, queue: str) -> dict | None:
        if self._is_memory():
            q = self._memory_queues.setdefault(queue, deque())
            if not q:
                return None
            return json.loads(q.popleft())

        redis = Redis.from_url(self.redis_url, decode_responses=True)
        try:
            value = await redis.lpop(f'frya:{queue}')
            return json.loads(value) if value else None
        finally:
            await redis.close()
