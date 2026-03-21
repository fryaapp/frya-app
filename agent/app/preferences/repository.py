"""User preferences repository (frya_user_preferences)."""
from __future__ import annotations

import asyncpg


_ENSURE_TABLE = """\
CREATE TABLE IF NOT EXISTS frya_user_preferences (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    user_id UUID NOT NULL,
    key VARCHAR(100) NOT NULL,
    value TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(tenant_id, user_id, key)
);
"""


class UserPreferencesRepository:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self._table_ok = False

    async def _conn(self) -> asyncpg.Connection:
        conn = await asyncpg.connect(self.database_url)
        if not self._table_ok:
            await conn.execute(_ENSURE_TABLE)
            self._table_ok = True
        return conn

    async def get_preference(self, tenant_id: str, user_id: str, key: str) -> str | None:
        conn = await self._conn()
        try:
            row = await conn.fetchrow(
                'SELECT value FROM frya_user_preferences WHERE tenant_id = $1::uuid AND user_id = $2::uuid AND key = $3',
                tenant_id, user_id, key,
            )
            return row['value'] if row else None
        finally:
            await conn.close()

    async def set_preference(self, tenant_id: str, user_id: str, key: str, value: str) -> None:
        conn = await self._conn()
        try:
            await conn.execute(
                """INSERT INTO frya_user_preferences (tenant_id, user_id, key, value, updated_at)
                   VALUES ($1::uuid, $2::uuid, $3, $4, now())
                   ON CONFLICT (tenant_id, user_id, key) DO UPDATE SET value = $4, updated_at = now()""",
                tenant_id, user_id, key, value,
            )
        finally:
            await conn.close()

    async def get_all_preferences(self, tenant_id: str, user_id: str) -> dict[str, str]:
        conn = await self._conn()
        try:
            rows = await conn.fetch(
                'SELECT key, value FROM frya_user_preferences WHERE tenant_id = $1::uuid AND user_id = $2::uuid',
                tenant_id, user_id,
            )
            return {r['key']: r['value'] for r in rows}
        finally:
            await conn.close()
