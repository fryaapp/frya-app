from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class BaseEvent(BaseModel):
    event_id: str
    source: str
    created_at: datetime = Field(default_factory=datetime.utcnow)


class CaseEvent(BaseEvent):
    case_id: str
    document_ref: str | None = None
    accounting_ref: str | None = None
    agent_name: str = 'frya-orchestrator'
    workflow_name: str | None = None
    approval_status: Literal['PENDING', 'APPROVED', 'REJECTED', 'NOT_REQUIRED'] = 'PENDING'
    llm_model: str | None = None
    llm_input_hash: str | None = None
    llm_output_hash: str | None = None
    action: str
    result: str


class TelegramIncomingEvent(BaseEvent):
    source: Literal['telegram'] = 'telegram'
    update_id: int | None = None
    raw_type: str = 'message'
    message_id: int | None = None
    chat_id: str
    chat_type: str | None = None
    sender_id: str | None = None
    sender_username: str | None = None
    text: str
