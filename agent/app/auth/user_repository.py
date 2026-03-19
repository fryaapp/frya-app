"""DB-backed user repository with memory fallback for tests.

frya_users table:
  username TEXT PRIMARY KEY
  email TEXT UNIQUE (nullable)
  role TEXT NOT NULL DEFAULT 'operator'
  password_hash TEXT (nullable — user has no password yet, must use invite link)
  tenant_id TEXT (nullable)
  is_active BOOLEAN NOT NULL DEFAULT TRUE
  session_version INTEGER NOT NULL DEFAULT 1
  created_at / updated_at TIMESTAMPTZ
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

import asyncpg
from pydantic import BaseModel

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS frya_users (
    username TEXT PRIMARY KEY,
    email TEXT,
    role TEXT NOT NULL DEFAULT 'operator',
    password_hash TEXT,
    tenant_id TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    session_version INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""

_CREATE_EMAIL_INDEX = """
CREATE UNIQUE INDEX IF NOT EXISTS frya_users_email_idx
ON frya_users(LOWER(email))
WHERE email IS NOT NULL
"""


class UserRecord(BaseModel):
    username: str
    email: str | None = None
    role: str = 'operator'
    password_hash: str | None = None
    tenant_id: str | None = None
    is_active: bool = True
    session_version: int = 1
    created_at: datetime | None = None
    updated_at: datetime | None = None


class UserRepository:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self._memory: dict[str, UserRecord] = {}

    @property
    def is_memory(self) -> bool:
        return self.database_url.startswith('memory://')

    async def initialize(self) -> None:
        if self.is_memory:
            return
        conn = await asyncpg.connect(self.database_url)
        try:
            await conn.execute(_CREATE_TABLE)
            await conn.execute(_CREATE_EMAIL_INDEX)
        finally:
            await conn.close()

    # ── Lookup ────────────────────────────────────────────────────────────────

    async def find_by_email(self, email: str) -> UserRecord | None:
        if self.is_memory:
            el = email.strip().lower()
            return next(
                (u for u in self._memory.values()
                 if u.email and u.email.strip().lower() == el and u.is_active),
                None,
            )
        conn = await asyncpg.connect(self.database_url)
        try:
            row = await conn.fetchrow(
                "SELECT * FROM frya_users WHERE LOWER(email)=LOWER($1) AND is_active=TRUE",
                email,
            )
        finally:
            await conn.close()
        return _row(row)

    async def find_by_username(self, username: str) -> UserRecord | None:
        if self.is_memory:
            return self._memory.get(username)
        conn = await asyncpg.connect(self.database_url)
        try:
            row = await conn.fetchrow(
                "SELECT * FROM frya_users WHERE username=$1",
                username,
            )
        finally:
            await conn.close()
        return _row(row)

    async def list_users(self, *, limit: int = 100) -> list[UserRecord]:
        if self.is_memory:
            return list(self._memory.values())[:limit]
        conn = await asyncpg.connect(self.database_url)
        try:
            rows = await conn.fetch(
                "SELECT * FROM frya_users ORDER BY username LIMIT $1",
                limit,
            )
        finally:
            await conn.close()
        return [r for r in (_row(row) for row in rows) if r]

    # ── Writes ────────────────────────────────────────────────────────────────

    async def create_user(self, record: UserRecord) -> UserRecord:
        if self.is_memory:
            self._memory[record.username] = record
            return record
        conn = await asyncpg.connect(self.database_url)
        try:
            await conn.execute(
                """
                INSERT INTO frya_users
                    (username, email, role, password_hash, tenant_id, is_active, session_version)
                VALUES ($1,$2,$3,$4,$5,$6,$7)
                ON CONFLICT (username) DO NOTHING
                """,
                record.username, record.email, record.role, record.password_hash,
                record.tenant_id, record.is_active, record.session_version,
            )
        finally:
            await conn.close()
        return record

    async def update_password(self, username: str, password_hash: str) -> None:
        """Update password and increment session_version to invalidate all existing sessions."""
        if self.is_memory:
            u = self._memory.get(username)
            if u:
                self._memory[username] = u.model_copy(update={
                    'password_hash': password_hash,
                    'session_version': u.session_version + 1,
                    'updated_at': datetime.utcnow(),
                })
            return
        conn = await asyncpg.connect(self.database_url)
        try:
            await conn.execute(
                """
                UPDATE frya_users
                   SET password_hash=$1,
                       session_version=session_version+1,
                       updated_at=NOW()
                 WHERE username=$2
                """,
                password_hash, username,
            )
        finally:
            await conn.close()

    async def get_session_version(self, username: str) -> int:
        """Returns current session_version (default 1 if user not in DB)."""
        if self.is_memory:
            u = self._memory.get(username)
            return u.session_version if u else 1
        conn = await asyncpg.connect(self.database_url)
        try:
            row = await conn.fetchrow(
                "SELECT session_version FROM frya_users WHERE username=$1",
                username,
            )
        finally:
            await conn.close()
        return row['session_version'] if row else 1

    async def deactivate_by_tenant(self, tenant_id: str) -> int:
        """Deactivate all users belonging to a tenant. Returns count."""
        if self.is_memory:
            count = 0
            for username, u in list(self._memory.items()):
                if u.tenant_id == tenant_id and u.is_active:
                    self._memory[username] = u.model_copy(update={'is_active': False})
                    count += 1
            return count
        conn = await asyncpg.connect(self.database_url)
        try:
            result = await conn.execute(
                "UPDATE frya_users SET is_active=FALSE, updated_at=NOW() WHERE tenant_id=$1 AND is_active=TRUE",
                tenant_id,
            )
        finally:
            await conn.close()
        # asyncpg returns "UPDATE N"
        try:
            return int(result.split()[-1])
        except Exception:
            return 0


def _row(row: Any) -> UserRecord | None:
    if row is None:
        return None
    return UserRecord(**dict(row))
