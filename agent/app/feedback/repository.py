"""Alpha feedback repository (frya_alpha_feedback)."""
from __future__ import annotations

from typing import Any

import asyncpg


_ENSURE_TABLE = """\
CREATE TABLE IF NOT EXISTS frya_alpha_feedback (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    user_id UUID NOT NULL,
    page VARCHAR(255),
    description TEXT NOT NULL,
    screenshot_path VARCHAR(500),
    status VARCHAR(50) NOT NULL DEFAULT 'NEW',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


class FeedbackRepository:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self._table_ok = False

    async def _conn(self) -> asyncpg.Connection:
        conn = await asyncpg.connect(self.database_url)
        if not self._table_ok:
            await conn.execute(_ENSURE_TABLE)
            self._table_ok = True
        return conn

    async def create(
        self,
        tenant_id: str,
        user_id: str,
        description: str,
        page: str | None = None,
        screenshot_path: str | None = None,
    ) -> str:
        conn = await self._conn()
        try:
            row = await conn.fetchrow(
                """INSERT INTO frya_alpha_feedback (tenant_id, user_id, page, description, screenshot_path)
                   VALUES ($1::uuid, $2::uuid, $3, $4, $5)
                   RETURNING id::text""",
                tenant_id, user_id, page, description, screenshot_path,
            )
            return row['id']
        finally:
            await conn.close()

    async def list_all(self, limit: int = 100) -> list[dict[str, Any]]:
        conn = await self._conn()
        try:
            rows = await conn.fetch(
                'SELECT id::text, tenant_id::text, user_id::text, page, description, screenshot_path, status, created_at '
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
                "UPDATE frya_alpha_feedback SET status = $2 WHERE id = $1::uuid",
                feedback_id, status,
            )
        finally:
            await conn.close()
