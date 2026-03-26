from __future__ import annotations
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field


class EmailIntakeRecord(BaseModel):
    email_intake_id: str
    received_at: datetime
    sender_email: str
    sender_name: str | None = None
    recipient_email: str | None = None
    subject: str | None = None
    body_plain: str | None = None
    message_id: str | None = None
    user_ref: str | None = None
    intake_status: Literal['RECEIVED', 'PROCESSING', 'COMPLETED', 'FAILED'] = 'RECEIVED'
    attachment_count: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class EmailAttachmentRecord(BaseModel):
    attachment_id: str
    email_intake_id: str
    file_name: str | None = None
    mime_type: str | None = None
    file_size: int | None = None
    storage_path: str | None = None
    sha256: str | None = None
    analyst_case_id: str | None = None
    analyst_context_ref: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
