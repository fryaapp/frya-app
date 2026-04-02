from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import asyncpg

from app.approvals.models import ApprovalRecord


class ApprovalRepository:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self._memory: dict[str, ApprovalRecord] = {}

    @property
    def is_memory(self) -> bool:
        return self.database_url.startswith('memory://')

    @staticmethod
    def _normalize_json_dict(raw_value: object) -> dict[str, Any]:
        if isinstance(raw_value, dict):
            return {str(k): v for k, v in raw_value.items()}
        if isinstance(raw_value, str):
            text = raw_value.strip()
            if not text:
                return {}
            try:
                parsed = json.loads(text)
            except Exception:
                return {}
            if isinstance(parsed, dict):
                return {str(k): v for k, v in parsed.items()}
        return {}

    @staticmethod
    def _normalize_json_list(raw_value: object) -> list[dict[str, Any]]:
        if isinstance(raw_value, list):
            return [x for x in raw_value if isinstance(x, dict)]
        if isinstance(raw_value, str):
            text = raw_value.strip()
            if not text:
                return []
            try:
                parsed = json.loads(text)
            except Exception:
                return []
            if isinstance(parsed, list):
                return [x for x in parsed if isinstance(x, dict)]
        return []

    @classmethod
    def _record_from_row(cls, raw: dict[str, Any]) -> ApprovalRecord:
        payload = json.loads(json.dumps(raw, default=str))
        payload['approval_context'] = cls._normalize_json_dict(payload.get('approval_context'))
        payload['policy_refs'] = cls._normalize_json_list(payload.get('policy_refs'))
        return ApprovalRecord(**payload)

    async def setup(self) -> None:
        if self.is_memory:
            return

        conn = await asyncpg.connect(self.database_url)
        try:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS frya_approvals (
                    id BIGSERIAL PRIMARY KEY,
                    approval_id TEXT UNIQUE NOT NULL,
                    case_id TEXT NOT NULL,
                    action_type TEXT NOT NULL,
                    scope_ref TEXT,
                    required_mode TEXT NOT NULL DEFAULT 'REQUIRE_USER_APPROVAL',
                    approval_context JSONB NOT NULL DEFAULT '{}'::jsonb,
                    status TEXT NOT NULL,
                    requested_by TEXT NOT NULL,
                    requested_at TIMESTAMPTZ NOT NULL,
                    decided_by TEXT,
                    decided_at TIMESTAMPTZ,
                    expires_at TIMESTAMPTZ,
                    open_item_id TEXT,
                    reason TEXT,
                    policy_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
                    audit_event_id TEXT
                )
                """
            )
            await conn.execute("ALTER TABLE frya_approvals ADD COLUMN IF NOT EXISTS required_mode TEXT NOT NULL DEFAULT 'REQUIRE_USER_APPROVAL'")
            await conn.execute("ALTER TABLE frya_approvals ADD COLUMN IF NOT EXISTS approval_context JSONB NOT NULL DEFAULT '{}'::jsonb")
            await conn.execute("ALTER TABLE frya_approvals ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ")
            await conn.execute("ALTER TABLE frya_approvals ADD COLUMN IF NOT EXISTS open_item_id TEXT")
            await conn.execute("ALTER TABLE frya_approvals ADD COLUMN IF NOT EXISTS tenant_id TEXT")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_approvals_tenant ON frya_approvals(tenant_id)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_frya_approvals_case_id ON frya_approvals(case_id)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_frya_approvals_status ON frya_approvals(status)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_frya_approvals_case_status ON frya_approvals(case_id, status)")
        finally:
            await conn.close()

    async def upsert(self, record: ApprovalRecord) -> None:
        if self.is_memory:
            self._memory[record.approval_id] = record
            return

        conn = await asyncpg.connect(self.database_url)
        try:
            await conn.execute(
                """
                INSERT INTO frya_approvals (
                    approval_id, case_id, action_type, scope_ref, required_mode, approval_context, status,
                    requested_by, requested_at, decided_by, decided_at, expires_at, open_item_id, reason,
                    policy_refs, audit_event_id, tenant_id
                ) VALUES ($1,$2,$3,$4,$5,$6::jsonb,$7,$8,$9,$10,$11,$12,$13,$14,$15::jsonb,$16,$17)
                ON CONFLICT (approval_id)
                DO UPDATE SET
                    case_id = EXCLUDED.case_id,
                    action_type = EXCLUDED.action_type,
                    scope_ref = EXCLUDED.scope_ref,
                    required_mode = EXCLUDED.required_mode,
                    approval_context = EXCLUDED.approval_context,
                    status = EXCLUDED.status,
                    requested_by = EXCLUDED.requested_by,
                    requested_at = EXCLUDED.requested_at,
                    decided_by = EXCLUDED.decided_by,
                    decided_at = EXCLUDED.decided_at,
                    expires_at = EXCLUDED.expires_at,
                    open_item_id = EXCLUDED.open_item_id,
                    reason = EXCLUDED.reason,
                    policy_refs = EXCLUDED.policy_refs,
                    audit_event_id = EXCLUDED.audit_event_id,
                    tenant_id = EXCLUDED.tenant_id
                """,
                record.approval_id,
                record.case_id,
                record.action_type,
                record.scope_ref,
                record.required_mode,
                json.dumps(record.approval_context),
                record.status,
                record.requested_by,
                record.requested_at,
                record.decided_by,
                record.decided_at,
                record.expires_at,
                record.open_item_id,
                record.reason,
                json.dumps(record.policy_refs),
                record.audit_event_id,
                record.tenant_id,
            )
        finally:
            await conn.close()

    async def get(self, approval_id: str) -> ApprovalRecord | None:
        if self.is_memory:
            return self._memory.get(approval_id)

        conn = await asyncpg.connect(self.database_url)
        try:
            row = await conn.fetchrow(
                'SELECT approval_id, case_id, action_type, scope_ref, required_mode, approval_context, status, '
                'requested_by, requested_at, decided_by, decided_at, expires_at, open_item_id, reason, '
                'policy_refs, audit_event_id '
                'FROM frya_approvals WHERE approval_id = $1',
                approval_id,
            )
            if row is None:
                return None
            return self._record_from_row(dict(row))
        finally:
            await conn.close()

    async def find_pending(self, case_id: str, action_type: str, scope_ref: str | None = None) -> ApprovalRecord | None:
        if self.is_memory:
            for record in self._memory.values():
                if record.case_id == case_id and record.action_type == action_type and record.scope_ref == scope_ref and record.status == 'PENDING':
                    return record
            return None

        conn = await asyncpg.connect(self.database_url)
        try:
            row = await conn.fetchrow(
                'SELECT approval_id, case_id, action_type, scope_ref, required_mode, approval_context, status, '
                'requested_by, requested_at, decided_by, decided_at, expires_at, open_item_id, reason, '
                'policy_refs, audit_event_id '
                'FROM frya_approvals WHERE case_id = $1 AND action_type = $2 '
                'AND ((scope_ref IS NULL AND $3::text IS NULL) OR scope_ref = $3) '
                "AND status = 'PENDING' ORDER BY requested_at DESC LIMIT 1",
                case_id,
                action_type,
                scope_ref,
            )
            if row is None:
                return None
            return self._record_from_row(dict(row))
        finally:
            await conn.close()

    async def list_by_case(self, case_id: str, limit: int = 200) -> Sequence[ApprovalRecord]:
        if self.is_memory:
            entries = [x for x in self._memory.values() if x.case_id == case_id]
            return sorted(entries, key=lambda x: x.requested_at, reverse=True)[:limit]

        conn = await asyncpg.connect(self.database_url)
        try:
            rows = await conn.fetch(
                'SELECT approval_id, case_id, action_type, scope_ref, required_mode, approval_context, status, '
                'requested_by, requested_at, decided_by, decided_at, expires_at, open_item_id, reason, '
                'policy_refs, audit_event_id '
                'FROM frya_approvals WHERE case_id = $1 ORDER BY requested_at DESC LIMIT $2',
                case_id,
                limit,
            )
            return [self._record_from_row(dict(r)) for r in rows]
        finally:
            await conn.close()

    async def list_recent(self, limit: int = 200) -> Sequence[ApprovalRecord]:
        if self.is_memory:
            entries = sorted(self._memory.values(), key=lambda x: x.requested_at, reverse=True)
            return entries[:limit]

        conn = await asyncpg.connect(self.database_url)
        try:
            rows = await conn.fetch(
                'SELECT approval_id, case_id, action_type, scope_ref, required_mode, approval_context, status, '
                'requested_by, requested_at, decided_by, decided_at, expires_at, open_item_id, reason, '
                'policy_refs, audit_event_id '
                'FROM frya_approvals ORDER BY requested_at DESC LIMIT $1',
                limit,
            )
            return [self._record_from_row(dict(r)) for r in rows]
        finally:
            await conn.close()
