from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class AuditRecord(BaseModel):
    event_id: str
    case_id: str
    source: str
    document_ref: str | None = None
    accounting_ref: str | None = None
    agent_name: str
    workflow_name: str | None = None
    approval_status: Literal['PENDING', 'APPROVED', 'REJECTED', 'NOT_REQUIRED', 'CANCELLED', 'EXPIRED', 'REVOKED']
    llm_model: str | None = None
    llm_input_hash: str | None = None
    llm_output_hash: str | None = None
    llm_input: Any | None = None
    llm_output: Any | None = None
    action: str
    result: str
    policy_refs: list[dict[str, Any]] = Field(default_factory=list)
    previous_hash: str | None = None
    record_hash: str
    created_at: datetime = Field(default_factory=datetime.utcnow)


