from __future__ import annotations

import json
import uuid

from app.telegram.communicator.memory.models import ConversationMemory


class ConversationMemoryStore:
    """Stores conversation memory per chat_id.

    If url starts with 'memory://' uses an in-process dict (for tests).
    Otherwise uses Redis.
    """

    _KEY_PREFIX = 'frya:comm:conv:'
    _TTL = 86400  # 24h

    def __init__(self, url: str) -> None:
        self._url = url
        self._in_memory = url.startswith('memory://')
        self._store: dict[str, str] = {}
        self._redis = None

    def _redis_key(self, chat_id: str) -> str:
        return self._KEY_PREFIX + chat_id

    async def _get_redis(self):
        if self._redis is None:
            import redis.asyncio as aioredis
            self._redis = aioredis.from_url(self._url, decode_responses=True)
        return self._redis

    async def load(self, chat_id: str) -> ConversationMemory | None:
        if self._in_memory:
            raw = self._store.get(chat_id)
            if raw is None:
                return None
            return ConversationMemory.model_validate(json.loads(raw))
        try:
            r = await self._get_redis()
            raw = await r.get(self._redis_key(chat_id))
            if raw is None:
                return None
            return ConversationMemory.model_validate(json.loads(raw))
        except Exception:
            return None

    async def save(self, mem: ConversationMemory) -> None:
        raw = mem.model_dump_json()
        if self._in_memory:
            self._store[mem.chat_id] = raw
            return
        try:
            r = await self._get_redis()
            await r.set(self._redis_key(mem.chat_id), raw, ex=self._TTL)
        except Exception:
            pass

    async def clear(self, chat_id: str) -> None:
        if self._in_memory:
            self._store.pop(chat_id, None)
            return
        try:
            r = await self._get_redis()
            await r.delete(self._redis_key(chat_id))
        except Exception:
            pass


def build_updated_conversation_memory(
    *,
    chat_id: str,
    prev_memory: ConversationMemory | None,
    intent: str | None,
    resolved_case_ref: str | None,
    resolved_document_ref: str | None,
    resolved_clarification_ref: str | None,
    resolved_open_item_id: str | None,
    context_resolution_status: str | None,
) -> ConversationMemory:
    """Sticky merge: if context NOT_FOUND, preserve old refs."""
    if prev_memory is None:
        return ConversationMemory(
            conversation_memory_ref='conv-' + uuid.uuid4().hex[:8],
            chat_id=chat_id,
            last_case_ref=resolved_case_ref,
            last_document_ref=resolved_document_ref,
            last_clarification_ref=resolved_clarification_ref,
            last_open_item_id=resolved_open_item_id,
            last_intent=intent,
            last_context_resolution_status=context_resolution_status,
        )

    # Sticky: only update refs when FOUND (or AMBIGUOUS); preserve old values if new is None
    if context_resolution_status == 'NOT_FOUND':
        return ConversationMemory(
            conversation_memory_ref=prev_memory.conversation_memory_ref,
            chat_id=chat_id,
            last_case_ref=prev_memory.last_case_ref,
            last_document_ref=prev_memory.last_document_ref,
            last_clarification_ref=prev_memory.last_clarification_ref,
            last_open_item_id=prev_memory.last_open_item_id,
            last_intent=intent,
            last_context_resolution_status=context_resolution_status,
        )

    # FOUND or AMBIGUOUS: update with new refs, keep old if new is None
    return ConversationMemory(
        conversation_memory_ref=prev_memory.conversation_memory_ref,
        chat_id=chat_id,
        last_case_ref=resolved_case_ref if resolved_case_ref is not None else prev_memory.last_case_ref,
        last_document_ref=resolved_document_ref if resolved_document_ref is not None else prev_memory.last_document_ref,
        last_clarification_ref=resolved_clarification_ref if resolved_clarification_ref is not None else prev_memory.last_clarification_ref,
        last_open_item_id=resolved_open_item_id if resolved_open_item_id is not None else prev_memory.last_open_item_id,
        last_intent=intent,
        last_context_resolution_status=context_resolution_status,
    )
