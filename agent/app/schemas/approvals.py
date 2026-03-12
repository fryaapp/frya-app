from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ApprovalDecision(BaseModel):
    case_id: str
    decision: Literal['APPROVE', 'REJECT', 'REQUEST_CHANGES']
    decided_by: str
    reason: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
