from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ProblemCase(BaseModel):
    problem_id: str
    case_id: str
    title: str
    details: str
    severity: str = 'MEDIUM'
    exception_type: str | None = None
    document_ref: str | None = None
    accounting_ref: str | None = None
    created_by: str = 'agent'
    created_at: datetime = Field(default_factory=datetime.utcnow)
