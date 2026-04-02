from __future__ import annotations

import json
from collections.abc import Sequence

import asyncpg

from app.audit.models import AuditRecord


class AuditRepository:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self._memory_records: list[AuditRecord] = []

    @property
    def is_memory(self) -> bool:
        return self.database_url.startswith('memory://')

    @staticmethod
    def _normalize_policy_refs(raw_value: object) -> list[dict]:
        if raw_value is None:
            return []

        if isinstance(raw_value, list):
            return [x for x in raw_value if isinstance(x, dict)]

        if isinstance(raw_value, dict):
            return [raw_value]

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
            if isinstance(parsed, dict):
                return [parsed]
            return []

        return []

    async def setup(self) -> None:
        if self.is_memory:
            return
        conn = await asyncpg.connect(self.database_url)
        try:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS frya_audit_log (
                    id BIGSERIAL PRIMARY KEY,
                    event_id TEXT NOT NULL,
                    case_id TEXT NOT NULL,
                    source TEXT NOT NULL,
                    document_ref TEXT,
                    accounting_ref TEXT,
                    agent_name TEXT NOT NULL,
                    workflow_name TEXT,
                    approval_status TEXT NOT NULL,
                    llm_model TEXT,
                    llm_input_hash TEXT,
                    llm_output_hash TEXT,
                    llm_input_json JSONB,
                    llm_output_json JSONB,
                    action TEXT NOT NULL,
                    result TEXT NOT NULL,
                    policy_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
                    previous_hash TEXT,
                    record_hash TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            await conn.execute("ALTER TABLE frya_audit_log ADD COLUMN IF NOT EXISTS case_id TEXT")
            await conn.execute("ALTER TABLE frya_audit_log ADD COLUMN IF NOT EXISTS policy_refs JSONB NOT NULL DEFAULT '[]'::jsonb")
            await conn.execute("ALTER TABLE frya_audit_log ADD COLUMN IF NOT EXISTS llm_input_json JSONB")
            await conn.execute("ALTER TABLE frya_audit_log ADD COLUMN IF NOT EXISTS llm_output_json JSONB")
            await conn.execute("UPDATE frya_audit_log SET case_id = COALESCE(case_id, 'legacy')")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_frya_audit_case_id ON frya_audit_log(case_id)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_frya_audit_created_at ON frya_audit_log(created_at)")
            await conn.execute("ALTER TABLE frya_audit_log ADD COLUMN IF NOT EXISTS tenant_id TEXT")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_tenant ON frya_audit_log(tenant_id)")
        finally:
            await conn.close()

    async def append(self, record: AuditRecord) -> None:
        if self.is_memory:
            self._memory_records.append(record)
            return

        conn = await asyncpg.connect(self.database_url)
        try:
            await conn.execute(
                """
                INSERT INTO frya_audit_log (
                  event_id, case_id, source, document_ref, accounting_ref, agent_name, workflow_name,
                  approval_status, llm_model, llm_input_hash, llm_output_hash, llm_input_json, llm_output_json, action, result,
                  policy_refs, previous_hash, record_hash, created_at
                )
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12::jsonb,$13::jsonb,$14,$15,$16::jsonb,$17,$18,$19)
                """,
                record.event_id,
                record.case_id,
                record.source,
                record.document_ref,
                record.accounting_ref,
                record.agent_name,
                record.workflow_name,
                record.approval_status,
                record.llm_model,
                record.llm_input_hash,
                record.llm_output_hash,
                json.dumps(record.llm_input) if record.llm_input is not None else None,
                json.dumps(record.llm_output) if record.llm_output is not None else None,
                record.action,
                record.result,
                json.dumps(record.policy_refs),
                record.previous_hash,
                record.record_hash,
                record.created_at,
            )
        finally:
            await conn.close()

    async def last_hash(self) -> str | None:
        if self.is_memory:
            return self._memory_records[-1].record_hash if self._memory_records else None

        conn = await asyncpg.connect(self.database_url)
        try:
            row = await conn.fetchrow('SELECT record_hash FROM frya_audit_log ORDER BY id DESC LIMIT 1')
            return row['record_hash'] if row else None
        finally:
            await conn.close()

    async def list_recent(self, limit: int = 100) -> Sequence[AuditRecord]:
        if self.is_memory:
            return list(reversed(self._memory_records[-limit:]))

        conn = await asyncpg.connect(self.database_url)
        try:
            rows = await conn.fetch(
                'SELECT event_id, case_id, source, document_ref, accounting_ref, agent_name, workflow_name, '
                'approval_status, llm_model, llm_input_hash, llm_output_hash, llm_input_json, llm_output_json, action, result, '
                'policy_refs, previous_hash, record_hash, created_at '
                'FROM frya_audit_log ORDER BY created_at DESC LIMIT $1',
                limit,
            )
            records: list[AuditRecord] = []
            for row in rows:
                payload = dict(row)
                payload['policy_refs'] = self._normalize_policy_refs(payload.get('policy_refs'))
                payload['llm_input'] = payload.pop('llm_input_json', None)
                payload['llm_output'] = payload.pop('llm_output_json', None)
                records.append(AuditRecord(**json.loads(json.dumps(payload, default=str))))
            return records
        finally:
            await conn.close()

    async def list_recent_for_tenant(
        self, tenant_id: str, case_ids: list[str], limit: int = 500
    ) -> Sequence[AuditRecord]:
        """Return recent audit records scoped to a single tenant.

        Matches records whose case_id starts with 'tenant:{tenant_id}'
        OR whose case_id is in the provided list of tenant case IDs.
        """
        tenant_prefix = f'tenant:{tenant_id}'
        if self.is_memory:
            filtered = [
                r for r in self._memory_records
                if r.case_id.startswith(tenant_prefix) or r.case_id in case_ids
            ]
            filtered.sort(key=lambda x: x.created_at, reverse=True)
            return filtered[:limit]

        conn = await asyncpg.connect(self.database_url)
        try:
            rows = await conn.fetch(
                'SELECT event_id, case_id, source, document_ref, accounting_ref, agent_name, workflow_name, '
                'approval_status, llm_model, llm_input_hash, llm_output_hash, llm_input_json, llm_output_json, action, result, '
                'policy_refs, previous_hash, record_hash, created_at '
                'FROM frya_audit_log '
                'WHERE case_id LIKE $1 OR case_id = ANY($2::text[]) '
                'ORDER BY created_at DESC LIMIT $3',
                tenant_prefix + '%',
                case_ids,
                limit,
            )
            records: list[AuditRecord] = []
            for row in rows:
                payload = dict(row)
                payload['policy_refs'] = self._normalize_policy_refs(payload.get('policy_refs'))
                payload['llm_input'] = payload.pop('llm_input_json', None)
                payload['llm_output'] = payload.pop('llm_output_json', None)
                records.append(AuditRecord(**json.loads(json.dumps(payload, default=str))))
            return records
        finally:
            await conn.close()

    async def list_by_case(self, case_id: str, limit: int = 500) -> Sequence[AuditRecord]:
        if self.is_memory:
            filtered = [r for r in self._memory_records if r.case_id == case_id]
            return sorted(filtered, key=lambda x: x.created_at)[:limit]

        conn = await asyncpg.connect(self.database_url)
        try:
            rows = await conn.fetch(
                'SELECT event_id, case_id, source, document_ref, accounting_ref, agent_name, workflow_name, '
                'approval_status, llm_model, llm_input_hash, llm_output_hash, llm_input_json, llm_output_json, action, result, '
                'policy_refs, previous_hash, record_hash, created_at '
                'FROM frya_audit_log WHERE case_id = $1 ORDER BY created_at ASC LIMIT $2',
                case_id,
                limit,
            )
            records: list[AuditRecord] = []
            for row in rows:
                payload = dict(row)
                payload['policy_refs'] = self._normalize_policy_refs(payload.get('policy_refs'))
                payload['llm_input'] = payload.pop('llm_input_json', None)
                payload['llm_output'] = payload.pop('llm_output_json', None)
                records.append(AuditRecord(**json.loads(json.dumps(payload, default=str))))
            return records
        finally:
            await conn.close()

    async def list_case_ids(self, limit: int = 200) -> list[str]:
        if self.is_memory:
            seen = sorted({r.case_id for r in self._memory_records if r.case_id})
            return seen[:limit]

        conn = await asyncpg.connect(self.database_url)
        try:
            rows = await conn.fetch(
                'SELECT case_id FROM frya_audit_log GROUP BY case_id ORDER BY MAX(created_at) DESC LIMIT $1',
                limit,
            )
            return [r['case_id'] for r in rows if r['case_id']]
        finally:
            await conn.close()

    async def list_all_ordered(self, batch_size: int = 1000) -> list[tuple[int, str | None, str]]:
        """Return (id, previous_hash, record_hash) for all rows ordered by id ASC.

        Used exclusively for hash-chain integrity verification.
        """
        if self.is_memory:
            return [
                (i + 1, r.previous_hash, r.record_hash)
                for i, r in enumerate(self._memory_records)
            ]

        conn = await asyncpg.connect(self.database_url)
        try:
            rows = await conn.fetch(
                'SELECT id, previous_hash, record_hash FROM frya_audit_log ORDER BY id ASC',
            )
            return [(r['id'], r['previous_hash'], r['record_hash']) for r in rows]
        finally:
            await conn.close()