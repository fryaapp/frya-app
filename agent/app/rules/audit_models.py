from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class RuleChangeAuditRecord(BaseModel):
    change_id: str
    file_name: str
    old_version: str | None = None
    new_version: str | None = None
    old_content: str
    new_content: str
    changed_by: str
    reason: str
    changed_at: datetime = Field(default_factory=datetime.utcnow)
