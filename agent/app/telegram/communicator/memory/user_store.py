from __future__ import annotations

import json
import time
import uuid
from typing import Any

from app.telegram.communicator.memory.models import UserMemory

# ── Flow State (in-memory, TTL-based) ────────────────────────────────────────
_FLOW_TTL = 1800  # 30 minutes
_flow_store: dict[str, tuple[dict[str, Any], float]] = {}


def set_active_flow(chat_id: str, flow: dict[str, Any]) -> None:
    _flow_store[chat_id] = (flow, time.time())


def get_active_flow(chat_id: str) -> dict[str, Any] | None:
    entry = _flow_store.get(chat_id)
    if entry is None:
        return None
    flow, ts = entry
    if time.time() - ts > _FLOW_TTL:
        _flow_store.pop(chat_id, None)
        return None
    return flow


def clear_active_flow(chat_id: str) -> None:
    _flow_store.pop(chat_id, None)


class UserMemoryStore:
    """Stores user memory per sender_id.

    If url starts with 'memory://' uses an in-process dict (for tests).
    Otherwise uses asyncpg (PostgreSQL).
    """

    _TABLE = 'frya_user_memory'

    def __init__(self, url: str) -> None:
        self._url = url
        self._in_memory = url.startswith('memory://')
        self._store: dict[str, str] = {}
        self._pool = None

    async def _get_pool(self):
        if self._pool is None:
            import asyncpg
            self._pool = await asyncpg.create_pool(self._url)
            await self._ensure_table()
        return self._pool

    async def _ensure_table(self):
        pool = self._pool
        async with pool.acquire() as conn:
            await conn.execute(f'''
                CREATE TABLE IF NOT EXISTS {self._TABLE} (
                    sender_id TEXT PRIMARY KEY,
                    memory_json JSONB NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            ''')

    async def load(self, sender_id: str) -> UserMemory | None:
        if self._in_memory:
            raw = self._store.get(sender_id)
            if raw is None:
                return None
            return UserMemory.model_validate(json.loads(raw))
        try:
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    f'SELECT memory_json FROM {self._TABLE} WHERE sender_id = $1',
                    sender_id,
                )
                if row is None:
                    return None
                return UserMemory.model_validate(json.loads(row['memory_json']))
        except Exception:
            return None

    async def save(self, mem: UserMemory) -> None:
        raw = mem.model_dump_json()
        if self._in_memory:
            self._store[mem.sender_id] = raw
            return
        try:
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                await conn.execute(
                    f'''
                    INSERT INTO {self._TABLE} (sender_id, memory_json, updated_at)
                    VALUES ($1, $2::jsonb, NOW())
                    ON CONFLICT (sender_id) DO UPDATE
                      SET memory_json = EXCLUDED.memory_json,
                          updated_at = NOW()
                    ''',
                    mem.sender_id,
                    raw,
                )
        except Exception:
            pass


def build_or_update_user_memory(
    *,
    sender_id: str,
    prev_memory: UserMemory | None,
    intent: str | None,
) -> UserMemory:
    """Build or update user memory. Only stores intent_counts — never operative refs."""
    if prev_memory is None:
        counts: dict[str, int] = {}
        if intent:
            counts[intent] = 1
        return UserMemory(
            user_memory_ref='umem-' + uuid.uuid4().hex[:8],
            sender_id=sender_id,
            intent_counts=counts,
        )

    counts = dict(prev_memory.intent_counts)
    if intent:
        counts[intent] = counts.get(intent, 0) + 1
    return UserMemory(
        user_memory_ref=prev_memory.user_memory_ref,
        sender_id=sender_id,
        intent_counts=counts,
        preferred_brevity=prev_memory.preferred_brevity,
    )
