"""Ring-buffer chat history in Redis for LLM context window."""
from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


def _context_data_to_text(ctx: dict) -> str:
    """Wandelt context_data in einen lesbaren String um.
    Wird direkt an den assistant-content angehaengt.
    Sprint-03-03: Kein separates context_data-Feld — Daten stehen im content.
    """
    parts = []

    items = ctx.get('items', [])
    for item in items[:8]:
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, dict):
            name = item.get('vendor', item.get('name', '?'))
            amount = item.get('amount', '')
            status = item.get('status', '')
            parts.append(f"{name} {amount}€ {status}".strip())

    for key, label in [('income', 'Einnahmen'), ('einnahmen', 'Einnahmen'),
                       ('expenses', 'Ausgaben'), ('ausgaben', 'Ausgaben'),
                       ('result', 'Ergebnis'), ('profit', 'Ergebnis')]:
        if key in ctx:
            parts.append(f"{label}: {ctx[key]}€")

    count = ctx.get('count')
    if count and count > 8:
        parts.append(f"+ {count - 8} weitere")

    return " | ".join(parts) if parts else ""


class ChatHistoryStore:
    """Stores last N message pairs (user+assistant) in Redis for LLM context."""

    MAX_MESSAGES = 20  # 10 pairs
    TTL_SECONDS = 86400  # 24h

    def __init__(self, redis_url: str) -> None:
        self._redis_url = redis_url
        self._redis: Any = None

    def _is_memory(self) -> bool:
        return self._redis_url.startswith('memory://')

    async def _get_redis(self) -> Any:
        if self._is_memory():
            return None
        if self._redis is not None:
            return self._redis
        try:
            import redis.asyncio as aioredis
            self._redis = aioredis.from_url(self._redis_url, decode_responses=True)
            return self._redis
        except Exception:
            return None

    def _key(self, chat_id: str) -> str:
        return f'frya:chat_history:{chat_id}'

    # In-memory fallback for tests
    _mem_store: dict[str, list[dict]] = {}

    async def load(self, chat_id: str) -> list[dict]:
        if self._is_memory():
            return list(self._mem_store.get(chat_id, []))[-self.MAX_MESSAGES:]
        r = await self._get_redis()
        if r is None:
            return []
        try:
            raw = await r.get(self._key(chat_id))
            if not raw:
                return []
            messages = json.loads(raw)
            return messages[-self.MAX_MESSAGES:]
        except (json.JSONDecodeError, TypeError, Exception):
            return []

    async def append(
        self,
        chat_id: str,
        user_msg: str,
        assistant_msg: str,
        context_data: dict | None = None,
    ) -> None:
        history = await self.load(chat_id)
        history.append({'role': 'user', 'content': user_msg})
        entry: dict = {'role': 'assistant', 'content': assistant_msg}
        if context_data:
            # Sprint-03-03: Daten-Summary DIREKT im content-Feld — kein separates context_data
            summary_text = _context_data_to_text(context_data)
            if summary_text:
                entry['content'] = f"{assistant_msg}\n\n[Gezeigte Daten: {summary_text}]"
        # KEIN context_data-Feld. NUR role + content. Wie bei ChatGPT.
        history.append(entry)
        history = history[-self.MAX_MESSAGES:]

        if self._is_memory():
            self._mem_store[chat_id] = history
            return

        r = await self._get_redis()
        if r is None:
            return
        try:
            await r.set(self._key(chat_id), json.dumps(history), ex=self.TTL_SECONDS)
        except Exception as exc:
            logger.debug('chat_history_store: append failed: %s', exc)

    @staticmethod
    def format_for_llm(history: list, max_messages: int = 6) -> str:
        """DEPRECATED (Sprint-03-03): History wird jetzt als messages-Array uebergeben.
        Daten-Summary steht direkt im content-Feld (kein separates context_data mehr).
        Nicht mehr aufrufen — wird in einem kuenftigen Sprint entfernt.
        """
        recent = history[-max_messages:]
        lines = []
        for msg in recent:
            role = 'User' if msg.get('role') == 'user' else 'Frya'
            content = (msg.get('content') or '')[:200]
            lines.append(f'{role}: {content}')
            ctx = msg.get('context_data')
            if ctx and isinstance(ctx, dict):
                items = ctx.get('items', [])
                if items:
                    lines.append(f'  [Gezeigte Daten: {", ".join(str(i) for i in items[:5])}]')
                for key in ('income', 'expenses', 'result', 'einnahmen', 'ausgaben', 'profit'):
                    if key in ctx:
                        lines.append(f'  [{key}: {ctx[key]}]')
                if ctx.get('count'):
                    lines.append(f'  [Anzahl: {ctx["count"]}]')
        return '\n'.join(lines)
