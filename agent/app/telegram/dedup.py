from __future__ import annotations

import hashlib
import json
from collections import deque

from redis.asyncio import Redis


class TelegramUpdateDeduplicator:
    def __init__(self, redis_url: str, ttl_seconds: int = 86400) -> None:
        self.redis_url = redis_url
        self.ttl_seconds = ttl_seconds
        self._memory_seen: deque[str] = deque(maxlen=5000)

    def _is_memory(self) -> bool:
        return self.redis_url.startswith('memory://')

    @staticmethod
    def build_key(update_id: int | None, payload: dict) -> str:
        if update_id is not None:
            return f'update:{update_id}'

        canonical = json.dumps(payload, sort_keys=True, ensure_ascii=True, separators=(',', ':'))
        digest = hashlib.sha256(canonical.encode('utf-8')).hexdigest()
        return f'payload:{digest}'

    async def acquire(self, dedup_key: str) -> bool:
        if self._is_memory():
            if dedup_key in self._memory_seen:
                return False
            self._memory_seen.append(dedup_key)
            return True

        redis = Redis.from_url(self.redis_url, decode_responses=True)
        try:
            redis_key = f'frya:telegram:dedup:{dedup_key}'
            result = await redis.set(redis_key, '1', ex=self.ttl_seconds, nx=True)
            return bool(result)
        finally:
            await redis.close()
