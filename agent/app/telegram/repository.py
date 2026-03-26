from __future__ import annotations

import json
from collections.abc import Sequence

import asyncpg

from app.telegram.models import TelegramCaseLinkRecord


class TelegramCaseLinkRepository:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self._memory: dict[str, TelegramCaseLinkRecord] = {}

    @property
    def is_memory(self) -> bool:
        return self.database_url.startswith('memory://')

    async def setup(self) -> None:
        if self.is_memory:
            return
        conn = await asyncpg.connect(self.database_url)
        try:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS frya_telegram_case_links (
                    link_id TEXT PRIMARY KEY,
                    case_id TEXT UNIQUE NOT NULL,
                    telegram_update_ref TEXT NOT NULL,
                    telegram_message_ref TEXT NOT NULL,
                    telegram_chat_ref TEXT NOT NULL,
                    telegram_thread_ref TEXT NOT NULL,
                    sender_id TEXT,
                    sender_username TEXT,
                    routing_status TEXT NOT NULL,
                    authorization_status TEXT NOT NULL,
                    intent_name TEXT NOT NULL,
                    open_item_id TEXT,
                    open_item_title TEXT,
                    problem_case_id TEXT,
                    linked_case_id TEXT,
                    track_for_status BOOLEAN NOT NULL DEFAULT FALSE,
                    reply_status TEXT NOT NULL DEFAULT 'NOT_ATTEMPTED',
                    reply_reason TEXT,
                    created_at TIMESTAMPTZ NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL
                )
                """
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_frya_tg_case_links_thread ON frya_telegram_case_links(telegram_thread_ref, updated_at DESC)"
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_frya_tg_case_links_track ON frya_telegram_case_links(track_for_status, telegram_thread_ref, updated_at DESC)"
            )
        finally:
            await conn.close()

    async def upsert(self, record: TelegramCaseLinkRecord) -> None:
        if self.is_memory:
            self._memory[record.case_id] = record
            return

        conn = await asyncpg.connect(self.database_url)
        try:
            await conn.execute(
                """
                INSERT INTO frya_telegram_case_links (
                    link_id, case_id, telegram_update_ref, telegram_message_ref, telegram_chat_ref,
                    telegram_thread_ref, sender_id, sender_username, routing_status, authorization_status,
                    intent_name, open_item_id, open_item_title, problem_case_id, linked_case_id,
                    track_for_status, reply_status, reply_reason, created_at, updated_at
                ) VALUES (
                    $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,
                    $11,$12,$13,$14,$15,$16,$17,$18,$19,$20
                )
                ON CONFLICT (case_id)
                DO UPDATE SET
                    link_id = EXCLUDED.link_id,
                    telegram_update_ref = EXCLUDED.telegram_update_ref,
                    telegram_message_ref = EXCLUDED.telegram_message_ref,
                    telegram_chat_ref = EXCLUDED.telegram_chat_ref,
                    telegram_thread_ref = EXCLUDED.telegram_thread_ref,
                    sender_id = EXCLUDED.sender_id,
                    sender_username = EXCLUDED.sender_username,
                    routing_status = EXCLUDED.routing_status,
                    authorization_status = EXCLUDED.authorization_status,
                    intent_name = EXCLUDED.intent_name,
                    open_item_id = EXCLUDED.open_item_id,
                    open_item_title = EXCLUDED.open_item_title,
                    problem_case_id = EXCLUDED.problem_case_id,
                    linked_case_id = EXCLUDED.linked_case_id,
                    track_for_status = EXCLUDED.track_for_status,
                    reply_status = EXCLUDED.reply_status,
                    reply_reason = EXCLUDED.reply_reason,
                    updated_at = EXCLUDED.updated_at
                """,
                record.link_id,
                record.case_id,
                record.telegram_update_ref,
                record.telegram_message_ref,
                record.telegram_chat_ref,
                record.telegram_thread_ref,
                record.sender_id,
                record.sender_username,
                record.routing_status,
                record.authorization_status,
                record.intent_name,
                record.open_item_id,
                record.open_item_title,
                record.problem_case_id,
                record.linked_case_id,
                record.track_for_status,
                record.reply_status,
                record.reply_reason,
                record.created_at,
                record.updated_at,
            )
        finally:
            await conn.close()

    async def get_by_case(self, case_id: str) -> TelegramCaseLinkRecord | None:
        if self.is_memory:
            return self._memory.get(case_id)

        conn = await asyncpg.connect(self.database_url)
        try:
            row = await conn.fetchrow("SELECT * FROM frya_telegram_case_links WHERE case_id = $1", case_id)
            if row is None:
                return None
            return TelegramCaseLinkRecord(**json.loads(json.dumps(dict(row), default=str)))
        finally:
            await conn.close()

    async def find_latest_trackable(
        self,
        telegram_thread_ref: str,
        exclude_case_id: str | None = None,
    ) -> TelegramCaseLinkRecord | None:
        if self.is_memory:
            values = [
                record
                for record in self._memory.values()
                if record.telegram_thread_ref == telegram_thread_ref
                and record.track_for_status
                and (exclude_case_id is None or record.case_id != exclude_case_id)
            ]
            if not values:
                return None
            return sorted(values, key=lambda item: item.updated_at, reverse=True)[0]

        conn = await asyncpg.connect(self.database_url)
        try:
            if exclude_case_id:
                row = await conn.fetchrow(
                    """
                    SELECT * FROM frya_telegram_case_links
                    WHERE telegram_thread_ref = $1
                      AND track_for_status = TRUE
                      AND case_id <> $2
                    ORDER BY updated_at DESC
                    LIMIT 1
                    """,
                    telegram_thread_ref,
                    exclude_case_id,
                )
            else:
                row = await conn.fetchrow(
                    """
                    SELECT * FROM frya_telegram_case_links
                    WHERE telegram_thread_ref = $1
                      AND track_for_status = TRUE
                    ORDER BY updated_at DESC
                    LIMIT 1
                    """,
                    telegram_thread_ref,
                )
            if row is None:
                return None
            return TelegramCaseLinkRecord(**json.loads(json.dumps(dict(row), default=str)))
        finally:
            await conn.close()

    async def find_latest_trackable_for_linked_case(self, linked_case_id: str) -> TelegramCaseLinkRecord | None:
        if self.is_memory:
            values = [
                record
                for record in self._memory.values()
                if record.track_for_status and (record.linked_case_id == linked_case_id or record.case_id == linked_case_id)
            ]
            if not values:
                return None
            return sorted(values, key=lambda item: item.updated_at, reverse=True)[0]

        conn = await asyncpg.connect(self.database_url)
        try:
            row = await conn.fetchrow(
                """
                SELECT * FROM frya_telegram_case_links
                WHERE track_for_status = TRUE
                  AND (linked_case_id = $1 OR case_id = $1)
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                linked_case_id,
            )
            if row is None:
                return None
            return TelegramCaseLinkRecord(**json.loads(json.dumps(dict(row), default=str)))
        finally:
            await conn.close()

    async def list_recent(self, limit: int = 50) -> Sequence[TelegramCaseLinkRecord]:
        if self.is_memory:
            return sorted(self._memory.values(), key=lambda item: item.updated_at, reverse=True)[:limit]

        conn = await asyncpg.connect(self.database_url)
        try:
            rows = await conn.fetch(
                "SELECT * FROM frya_telegram_case_links ORDER BY updated_at DESC LIMIT $1",
                limit,
            )
            return [TelegramCaseLinkRecord(**json.loads(json.dumps(dict(row), default=str))) for row in rows]
        finally:
            await conn.close()
