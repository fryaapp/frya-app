from __future__ import annotations

import json

from app.audit.hash_chain import record_hash, sha256_text
from app.audit.models import AuditRecord
from app.audit.repository import AuditRepository


class AuditService:
    def __init__(self, repository: AuditRepository) -> None:
        self.repository = repository

    async def initialize(self) -> None:
        await self.repository.setup()

    async def log_event(self, payload: dict) -> AuditRecord:
        prev_hash = await self.repository.last_hash()
        llm_input = payload.get('llm_input')
        llm_output = payload.get('llm_output')

        record_payload = {
            'event_id': payload['event_id'],
            'case_id': payload.get('case_id', 'uncategorized'),
            'source': payload.get('source', 'agent'),
            'document_ref': payload.get('document_ref'),
            'accounting_ref': payload.get('accounting_ref'),
            'agent_name': payload.get('agent_name', 'frya-orchestrator'),
            'workflow_name': payload.get('workflow_name'),
            'approval_status': payload.get('approval_status', 'PENDING'),
            'llm_model': payload.get('llm_model'),
            'llm_input_hash': sha256_text(json.dumps(llm_input, sort_keys=True)) if llm_input is not None else None,
            'llm_output_hash': sha256_text(json.dumps(llm_output, sort_keys=True)) if llm_output is not None else None,
            'llm_input': llm_input,
            'llm_output': llm_output,
            'action': payload['action'],
            'result': payload['result'],
            'policy_refs': payload.get('policy_refs', []),
            'previous_hash': prev_hash,
        }
        record_payload['record_hash'] = record_hash(record_payload, prev_hash)

        record = AuditRecord(**record_payload)
        await self.repository.append(record)
        return record

    async def recent(self, limit: int = 100) -> list[AuditRecord]:
        records = await self.repository.list_recent(limit=limit)
        return list(records)

    async def recent_for_tenant(
        self, tenant_id: str, case_ids: list[str] | None = None, limit: int = 500
    ) -> list[AuditRecord]:
        """Return recent audit records scoped to a single tenant (GDPR-compliant)."""
        records = await self.repository.list_recent_for_tenant(
            tenant_id=tenant_id, case_ids=case_ids or [], limit=limit
        )
        return list(records)

    async def by_case(self, case_id: str, limit: int = 500) -> list[AuditRecord]:
        return list(await self.repository.list_by_case(case_id=case_id, limit=limit))

    async def case_ids(self, limit: int = 200) -> list[str]:
        return await self.repository.list_case_ids(limit=limit)

    async def verify_chain(self) -> dict:
        """Verify hash-chain integrity across all audit records.

        Returns {valid, entries_checked, first_broken_at (id or None)}.
        """
        rows = await self.repository.list_all_ordered()
        prev_hash: str | None = None
        for row_id, stored_prev, stored_hash in rows:
            if stored_prev != prev_hash:
                return {
                    'valid': False,
                    'entries_checked': row_id,
                    'first_broken_at': row_id,
                    'reason': f'previous_hash mismatch at id={row_id}',
                }
            prev_hash = stored_hash
        return {
            'valid': True,
            'entries_checked': len(rows),
            'first_broken_at': None,
        }
