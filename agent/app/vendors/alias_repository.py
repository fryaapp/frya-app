"""Vendor alias repository (frya_vendor_aliases)."""
from __future__ import annotations

import asyncpg


_ENSURE_TABLE = """\
CREATE TABLE IF NOT EXISTS frya_vendor_aliases (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id TEXT NOT NULL,
    canonical_name VARCHAR(255) NOT NULL,
    alias VARCHAR(255) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(tenant_id, alias)
);
"""


class VendorAliasRepository:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self._table_ok = False

    async def _conn(self) -> asyncpg.Connection:
        conn = await asyncpg.connect(self.database_url)
        if not self._table_ok:
            await conn.execute(_ENSURE_TABLE)
            self._table_ok = True
        return conn

    async def resolve(self, tenant_id: str, name: str) -> str:
        """Resolve a vendor name to its canonical form. Returns original if no alias."""
        conn = await self._conn()
        try:
            row = await conn.fetchrow(
                'SELECT canonical_name FROM frya_vendor_aliases WHERE tenant_id = $1 AND lower(alias) = lower($2)',
                tenant_id, name,
            )
            return row['canonical_name'] if row else name
        finally:
            await conn.close()

    async def add_alias(self, tenant_id: str, canonical: str, alias: str) -> None:
        conn = await self._conn()
        try:
            await conn.execute(
                """INSERT INTO frya_vendor_aliases (tenant_id, canonical_name, alias)
                   VALUES ($1, $2, $3)
                   ON CONFLICT (tenant_id, alias) DO UPDATE SET canonical_name = $2""",
                tenant_id, canonical, alias,
            )
        finally:
            await conn.close()

    async def get_all(self, tenant_id: str) -> list[dict]:
        conn = await self._conn()
        try:
            rows = await conn.fetch(
                'SELECT canonical_name, alias FROM frya_vendor_aliases WHERE tenant_id = $1 ORDER BY canonical_name',
                tenant_id,
            )
            return [dict(r) for r in rows]
        finally:
            await conn.close()
