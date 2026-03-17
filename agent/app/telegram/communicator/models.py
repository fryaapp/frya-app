from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

CommunicatorIntentCode = Literal[
    'GREETING',
    'STATUS_OVERVIEW',
    'NEEDS_FROM_USER',
    'DOCUMENT_ARRIVAL_CHECK',
    'LAST_CASE_EXPLANATION',
    'GENERAL_SAFE_HELP',
    'UNSUPPORTED_OR_RISKY',
]


class CommunicatorContextResolution(BaseModel):
    resolution_status: str  # FOUND, NOT_FOUND, AMBIGUOUS
    resolved_case_ref: str | None = None
    resolved_document_ref: str | None = None
    resolved_clarification_ref: str | None = None
    resolved_open_item_id: str | None = None
    context_reason: str | None = None
    open_item_state: str | None = None
    open_item_title: str | None = None
    clarification_question: str | None = None
    has_multiple_open_items: bool = False


class CommunicatorTurn(BaseModel):
    communicator_turn_ref: str
    intent: str
    guardrail_passed: bool
    truth_basis: str
    memory_used: bool = False
    conversation_memory_ref: str | None = None
    response_type: str
    context_resolution: CommunicatorContextResolution | None = None
    memory_types_used: list[str] = Field(default_factory=list)


class CommunicatorResult(BaseModel):
    handled: bool
    routing_status: str  # COMMUNICATOR_HANDLED, COMMUNICATOR_GUARDRAIL_TRIGGERED
    turn: CommunicatorTurn
    reply_text: str
