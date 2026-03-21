from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


OpenItemStatus = Literal['OPEN', 'WAITING_USER', 'WAITING_DATA', 'SCHEDULED', 'COMPLETED', 'CANCELLED', 'PENDING_APPROVAL']


class OpenItem(BaseModel):
    item_id: str
    case_id: str
    title: str
    description: str
    status: OpenItemStatus = 'OPEN'
    source: str = 'agent'
    document_ref: str | None = None
    accounting_ref: str | None = None
    due_at: datetime | None = None
    reminder_job_id: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
