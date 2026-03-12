from __future__ import annotations

import json
from collections.abc import Sequence

import asyncpg

from app.open_items.models import OpenItem


class OpenItemsRepository:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self._memory: dict[str, OpenItem] = {}

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
                CREATE TABLE IF NOT EXISTS frya_open_items (
                    item_id TEXT PRIMARY KEY,
                    case_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    status TEXT NOT NULL,
                    source TEXT NOT NULL,
                    document_ref TEXT,
                    accounting_ref TEXT,
                    due_at TIMESTAMPTZ,
                    reminder_job_id TEXT,
                    created_at TIMESTAMPTZ NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL
                )
                """
            )
            await conn.execute("ALTER TABLE frya_open_items ADD COLUMN IF NOT EXISTS case_id TEXT")
            await conn.execute("ALTER TABLE frya_open_items ADD COLUMN IF NOT EXISTS document_ref TEXT")
            await conn.execute("ALTER TABLE frya_open_items ADD COLUMN IF NOT EXISTS accounting_ref TEXT")
            await conn.execute("UPDATE frya_open_items SET case_id = COALESCE(case_id, 'legacy')")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_frya_open_items_case_id ON frya_open_items(case_id)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_frya_open_items_status ON frya_open_items(status)")
        finally:
            await conn.close()

    async def upsert(self, item: OpenItem) -> None:
        if self.is_memory:
            self._memory[item.item_id] = item
            return

        conn = await asyncpg.connect(self.database_url)
        try:
            await conn.execute(
                """
                INSERT INTO frya_open_items (
                    item_id, case_id, title, description, status, source, document_ref, accounting_ref,
                    due_at, reminder_job_id, created_at, updated_at
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
                ON CONFLICT (item_id)
                DO UPDATE SET
                    case_id = EXCLUDED.case_id,
                    title = EXCLUDED.title,
                    description = EXCLUDED.description,
                    status = EXCLUDED.status,
                    source = EXCLUDED.source,
                    document_ref = EXCLUDED.document_ref,
                    accounting_ref = EXCLUDED.accounting_ref,
                    due_at = EXCLUDED.due_at,
                    reminder_job_id = EXCLUDED.reminder_job_id,
                    updated_at = EXCLUDED.updated_at
                """,
                item.item_id,
                item.case_id,
                item.title,
                item.description,
                item.status,
                item.source,
                item.document_ref,
                item.accounting_ref,
                item.due_at,
                item.reminder_job_id,
                item.created_at,
                item.updated_at,
            )
        finally:
            await conn.close()

    async def get(self, item_id: str) -> OpenItem | None:
        if self.is_memory:
            return self._memory.get(item_id)

        conn = await asyncpg.connect(self.database_url)
        try:
            row = await conn.fetchrow('SELECT * FROM frya_open_items WHERE item_id = $1', item_id)
            if row is None:
                return None
            return OpenItem(**json.loads(json.dumps(dict(row), default=str)))
        finally:
            await conn.close()

    async def list(self, status: str | None = None, limit: int = 200) -> Sequence[OpenItem]:
        if self.is_memory:
            values = list(self._memory.values())
            if status:
                values = [x for x in values if x.status == status]
            return sorted(values, key=lambda x: x.updated_at, reverse=True)[:limit]

        conn = await asyncpg.connect(self.database_url)
        try:
            if status:
                rows = await conn.fetch(
                    'SELECT * FROM frya_open_items WHERE status = $1 ORDER BY updated_at DESC LIMIT $2',
                    status,
                    limit,
                )
            else:
                rows = await conn.fetch('SELECT * FROM frya_open_items ORDER BY updated_at DESC LIMIT $1', limit)

            return [OpenItem(**json.loads(json.dumps(dict(r), default=str))) for r in rows]
        finally:
            await conn.close()

    async def list_by_case(self, case_id: str, limit: int = 200) -> Sequence[OpenItem]:
        if self.is_memory:
            values = [x for x in self._memory.values() if x.case_id == case_id]
            return sorted(values, key=lambda x: x.updated_at, reverse=True)[:limit]

        conn = await asyncpg.connect(self.database_url)
        try:
            rows = await conn.fetch(
                'SELECT * FROM frya_open_items WHERE case_id = $1 ORDER BY updated_at DESC LIMIT $2',
                case_id,
                limit,
            )
            return [OpenItem(**json.loads(json.dumps(dict(r), default=str))) for r in rows]
        finally:
            await conn.close()
