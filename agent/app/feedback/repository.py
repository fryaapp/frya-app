"""Alpha feedback repository (frya_alpha_feedback)."""
from __future__ import annotations

from typing import Any

import asyncpg


_ENSURE_TABLE = """\
CREATE TABLE IF NOT EXISTS frya_alpha_feedback (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    page VARCHAR(255),
    description TEXT NOT NULL,
    screenshot_path VARCHAR(500),
    screenshot_data TEXT,
    system_info JSONB,
    status VARCHAR(50) NOT NULL DEFAULT 'NEW',
    exported BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

_MIGRATE_COLS = [
    "ALTER TABLE frya_alpha_feedback ADD COLUMN IF NOT EXISTS screenshot_data TEXT",
    "ALTER TABLE frya_alpha_feedback ADD COLUMN IF NOT EXISTS system_info JSONB",
    "ALTER TABLE frya_alpha_feedback ADD COLUMN IF NOT EXISTS exported BOOLEAN NOT NULL DEFAULT false",
]


class FeedbackRepository:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self._table_ok = False

    async def _conn(self) -> asyncpg.Connection:
        conn = await asyncpg.connect(self.database_url)
        if not self._table_ok:
            await conn.execute(_ENSURE_TABLE)
            for sql in _MIGRATE_COLS:
                try:
                    await conn.execute(sql)
                except Exception:
                    pass  # Column already exists
            self._table_ok = True
        return conn

    async def create(
        self,
        tenant_id: str,
        user_id: str,
        description: str,
        page: str | None = None,
        screenshot_path: str | None = None,
        screenshot_data: str | None = None,
        system_info: dict | None = None,
    ) -> str:
        import json
        conn = await self._conn()
        try:
            row = await conn.fetchrow(
                """INSERT INTO frya_alpha_feedback
                   (tenant_id, user_id, page, description, screenshot_path, screenshot_data, system_info)
                   VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb)
                   RETURNING id::text""",
                tenant_id, user_id, page, description, screenshot_path,
                screenshot_data,
                json.dumps(system_info) if system_info else None,
            )
            return row['id']
        finally:
            await conn.close()

    async def get_by_id(self, feedback_id: str) -> dict[str, Any] | None:
        conn = await self._conn()
        try:
            row = await conn.fetchrow(
                'SELECT id::text, tenant_id::text, user_id::text, page, description, '
                'screenshot_path, screenshot_data, system_info, status, exported, created_at '
                'FROM frya_alpha_feedback WHERE id = $1',
                feedback_id,
            )
            return dict(row) if row else None
        finally:
            await conn.close()

    async def list_all(self, limit: int = 100) -> list[dict[str, Any]]:
        conn = await self._conn()
        try:
            rows = await conn.fetch(
                'SELECT id::text, tenant_id::text, user_id::text, page, description, '
                'screenshot_path, status, exported, created_at '
                'FROM frya_alpha_feedback ORDER BY created_at DESC LIMIT $1',
                limit,
            )
            return [dict(r) for r in rows]
        finally:
            await conn.close()

    async def update_status(self, feedback_id: str, status: str) -> None:
        conn = await self._conn()
        try:
            await conn.execute(
                "UPDATE frya_alpha_feedback SET status = $2 WHERE id = $1",
                feedback_id, status,
            )
        finally:
            await conn.close()

    async def mark_exported(self, feedback_ids: list[str]) -> int:
        conn = await self._conn()
        try:
            result = await conn.execute(
                "UPDATE frya_alpha_feedback SET exported = true WHERE id = ANY($1::uuid[])",
                feedback_ids,
            )
            return int(result.split()[-1])  # "UPDATE N"
        finally:
            await conn.close()
