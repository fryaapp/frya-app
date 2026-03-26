"""Repository for frya_tenants table.

frya_tenants (created in Paket 59, we ADD soft-delete columns here):
  tenant_id TEXT PRIMARY KEY
  name TEXT NOT NULL
  status TEXT NOT NULL DEFAULT 'active'   -- active | pending_deletion | deleted
  admin_email TEXT
  mail_config JSONB
  deletion_requested_at TIMESTAMPTZ
  deletion_requested_by TEXT
  hard_delete_after TIMESTAMPTZ           -- 30 days after deletion_requested_at
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

import asyncpg
from pydantic import BaseModel

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS frya_tenants (
    tenant_id TEXT PRIMARY KEY,
    name TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active',
    admin_email TEXT,
    mail_config JSONB,
    deletion_requested_at TIMESTAMPTZ,
    deletion_requested_by TEXT,
    hard_delete_after TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""

# Add soft-delete columns to existing table (Paket 59 may have created it without them)
_ALTER_STATEMENTS = [
    "ALTER TABLE frya_tenants ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'active'",
    "ALTER TABLE frya_tenants ADD COLUMN IF NOT EXISTS deletion_requested_at TIMESTAMPTZ",
    "ALTER TABLE frya_tenants ADD COLUMN IF NOT EXISTS deletion_requested_by TEXT",
    "ALTER TABLE frya_tenants ADD COLUMN IF NOT EXISTS hard_delete_after TIMESTAMPTZ",
]


class TenantRecord(BaseModel):
    tenant_id: str
    name: str = ''
    status: str = 'active'
    admin_email: str | None = None
    mail_config: dict[str, Any] | None = None
    deletion_requested_at: datetime | None = None
    deletion_requested_by: str | None = None
    hard_delete_after: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class TenantRepository:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self._memory: dict[str, TenantRecord] = {}

    @property
    def is_memory(self) -> bool:
        return self.database_url.startswith('memory://')

    async def initialize(self) -> None:
        if self.is_memory:
            return
        conn = await asyncpg.connect(self.database_url)
        try:
            await conn.execute(_CREATE_TABLE)
            for stmt in _ALTER_STATEMENTS:
                try:
                    await conn.execute(stmt)
                except Exception:
                    pass  # Column may already exist
        finally:
            await conn.close()

    async def find_by_id(self, tenant_id: str) -> TenantRecord | None:
        if self.is_memory:
            return self._memory.get(tenant_id)
        conn = await asyncpg.connect(self.database_url)
        try:
            row = await conn.fetchrow(
                "SELECT * FROM frya_tenants WHERE tenant_id=$1", tenant_id
            )
        finally:
            await conn.close()
        return _row(row)

    async def list_active(self) -> list[TenantRecord]:
        if self.is_memory:
            return [t for t in self._memory.values() if t.status == 'active']
        conn = await asyncpg.connect(self.database_url)
        try:
            rows = await conn.fetch(
                "SELECT * FROM frya_tenants WHERE status='active' ORDER BY name"
            )
        finally:
            await conn.close()
        return [r for r in (_row(row) for row in rows) if r]

    async def list_pending_hard_delete(self) -> list[TenantRecord]:
        """Tenants whose hard_delete_after has passed."""
        if self.is_memory:
            now = datetime.utcnow()
            return [
                t for t in self._memory.values()
                if t.status == 'pending_deletion'
                and t.hard_delete_after is not None
                and t.hard_delete_after <= now
            ]
        conn = await asyncpg.connect(self.database_url)
        try:
            rows = await conn.fetch(
                """SELECT * FROM frya_tenants
                   WHERE status='pending_deletion'
                     AND hard_delete_after <= NOW()"""
            )
        finally:
            await conn.close()
        return [r for r in (_row(row) for row in rows) if r]

    async def create_tenant(self, record: TenantRecord) -> TenantRecord:
        if self.is_memory:
            self._memory[record.tenant_id] = record
            return record
        conn = await asyncpg.connect(self.database_url)
        try:
            await conn.execute(
                """
                INSERT INTO frya_tenants (tenant_id, name, status, admin_email, mail_config)
                VALUES ($1,$2,$3,$4,$5)
                ON CONFLICT (tenant_id) DO NOTHING
                """,
                record.tenant_id, record.name, record.status,
                record.admin_email,
                __import__('json').dumps(record.mail_config) if record.mail_config else None,
            )
        finally:
            await conn.close()
        return record

    async def soft_delete(
        self,
        tenant_id: str,
        *,
        requested_by: str,
        hard_delete_after: datetime,
    ) -> TenantRecord | None:
        if self.is_memory:
            t = self._memory.get(tenant_id)
            if t is None or t.status != 'active':
                return None
            updated = t.model_copy(update={
                'status': 'pending_deletion',
                'deletion_requested_at': datetime.utcnow(),
                'deletion_requested_by': requested_by,
                'hard_delete_after': hard_delete_after,
                'updated_at': datetime.utcnow(),
            })
            self._memory[tenant_id] = updated
            return updated
        conn = await asyncpg.connect(self.database_url)
        try:
            row = await conn.fetchrow(
                """
                UPDATE frya_tenants
                   SET status='pending_deletion',
                       deletion_requested_at=NOW(),
                       deletion_requested_by=$1,
                       hard_delete_after=$2,
                       updated_at=NOW()
                 WHERE tenant_id=$3
                   AND status='active'
                RETURNING *
                """,
                requested_by, hard_delete_after, tenant_id,
            )
        finally:
            await conn.close()
        return _row(row)

    async def mark_hard_deleted(self, tenant_id: str) -> None:
        if self.is_memory:
            t = self._memory.get(tenant_id)
            if t:
                self._memory[tenant_id] = t.model_copy(update={
                    'status': 'deleted',
                    'updated_at': datetime.utcnow(),
                })
            return
        conn = await asyncpg.connect(self.database_url)
        try:
            await conn.execute(
                "UPDATE frya_tenants SET status='deleted', updated_at=NOW() WHERE tenant_id=$1",
                tenant_id,
            )
        finally:
            await conn.close()


def _row(row: Any) -> TenantRecord | None:
    if row is None:
        return None
    d = dict(row)
    # mail_config may come back as str or dict depending on asyncpg version
    if isinstance(d.get('mail_config'), str):
        import json
        try:
            d['mail_config'] = json.loads(d['mail_config'])
        except Exception:
            d['mail_config'] = None
    return TenantRecord(**d)
