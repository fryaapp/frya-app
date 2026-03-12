from __future__ import annotations

import uuid

from app.rules.audit_models import RuleChangeAuditRecord
from app.rules.audit_repository import RuleChangeAuditRepository


class RuleChangeAuditService:
    def __init__(self, repository: RuleChangeAuditRepository) -> None:
        self.repository = repository

    async def initialize(self) -> None:
        await self.repository.setup()

    async def record_change(
        self,
        file_name: str,
        old_content: str,
        new_content: str,
        changed_by: str,
        reason: str,
        old_version: str | None = None,
        new_version: str | None = None,
    ) -> RuleChangeAuditRecord:
        record = RuleChangeAuditRecord(
            change_id=str(uuid.uuid4()),
            file_name=file_name,
            old_version=old_version,
            new_version=new_version,
            old_content=old_content,
            new_content=new_content,
            changed_by=changed_by,
            reason=reason,
        )
        await self.repository.append(record)
        return record

    async def recent(self, limit: int = 100) -> list[RuleChangeAuditRecord]:
        return list(await self.repository.list_recent(limit=limit))
