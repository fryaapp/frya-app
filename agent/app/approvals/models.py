from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


ApprovalStatus = Literal['PENDING', 'APPROVED', 'REJECTED', 'CANCELLED', 'EXPIRED', 'REVOKED']


class ApprovalRecord(BaseModel):
    approval_id: str
    case_id: str
    action_type: str
    scope_ref: str | None = None
    required_mode: str = 'REQUIRE_USER_APPROVAL'
    approval_context: dict[str, Any] = Field(default_factory=dict)
    status: ApprovalStatus = 'PENDING'
    requested_by: str
    requested_at: datetime = Field(default_factory=datetime.utcnow)
    decided_by: str | None = None
    decided_at: datetime | None = None
    expires_at: datetime | None = None
    open_item_id: str | None = None
    reason: str | None = None
    policy_refs: list[dict[str, Any]] = Field(default_factory=list)
    audit_event_id: str | None = None
    tenant_id: str | None = None
