from __future__ import annotations

import json
from collections.abc import Sequence

import asyncpg

from app.rules.audit_models import RuleChangeAuditRecord


class RuleChangeAuditRepository:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self._memory: list[RuleChangeAuditRecord] = []

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
                CREATE TABLE IF NOT EXISTS frya_rule_change_audit (
                    id BIGSERIAL PRIMARY KEY,
                    change_id TEXT UNIQUE NOT NULL,
                    file_name TEXT NOT NULL,
                    old_version TEXT,
                    new_version TEXT,
                    old_content TEXT NOT NULL,
                    new_content TEXT NOT NULL,
                    changed_by TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    changed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_frya_rule_change_file ON frya_rule_change_audit(file_name)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_frya_rule_change_time ON frya_rule_change_audit(changed_at)")
        finally:
            await conn.close()

    async def append(self, record: RuleChangeAuditRecord) -> None:
        if self.is_memory:
            self._memory.append(record)
            return

        conn = await asyncpg.connect(self.database_url)
        try:
            await conn.execute(
                """
                INSERT INTO frya_rule_change_audit (
                    change_id, file_name, old_version, new_version, old_content, new_content,
                    changed_by, reason, changed_at
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
                """,
                record.change_id,
                record.file_name,
                record.old_version,
                record.new_version,
                record.old_content,
                record.new_content,
                record.changed_by,
                record.reason,
                record.changed_at,
            )
        finally:
            await conn.close()

    async def list_recent(self, limit: int = 100) -> Sequence[RuleChangeAuditRecord]:
        if self.is_memory:
            return list(reversed(self._memory[-limit:]))

        conn = await asyncpg.connect(self.database_url)
        try:
            rows = await conn.fetch(
                'SELECT change_id, file_name, old_version, new_version, old_content, new_content, '
                'changed_by, reason, changed_at FROM frya_rule_change_audit '
                'ORDER BY changed_at DESC LIMIT $1',
                limit,
            )
            return [RuleChangeAuditRecord(**json.loads(json.dumps(dict(r), default=str))) for r in rows]
        finally:
            await conn.close()
