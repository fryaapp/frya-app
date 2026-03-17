from __future__ import annotations

from pydantic import BaseModel, Field


class TruthAnnotation(BaseModel):
    truth_basis: str  # AUDIT_DERIVED, CONVERSATION_MEMORY, USER_MEMORY, INFERENCE, UNKNOWN
    requires_uncertainty_phrase: bool
    priority: int
    sources: list[str] = Field(default_factory=list)

    def is_uncertain(self) -> bool:
        return self.requires_uncertainty_phrase

    @classmethod
    def audit_derived(cls, sources: list[str] | None = None) -> 'TruthAnnotation':
        return cls(
            truth_basis='AUDIT_DERIVED',
            requires_uncertainty_phrase=False,
            priority=0,
            sources=sources or [],
        )

    @classmethod
    def from_conv_memory(cls) -> 'TruthAnnotation':
        return cls(
            truth_basis='CONVERSATION_MEMORY',
            requires_uncertainty_phrase=True,
            priority=1,
            sources=['conversation_memory'],
        )

    @classmethod
    def unknown(cls) -> 'TruthAnnotation':
        return cls(
            truth_basis='UNKNOWN',
            requires_uncertainty_phrase=False,
            priority=4,
            sources=[],
        )


class ConversationMemory(BaseModel):
    conversation_memory_ref: str
    chat_id: str
    last_case_ref: str | None = None
    last_document_ref: str | None = None
    last_clarification_ref: str | None = None
    last_open_item_id: str | None = None
    last_intent: str | None = None
    last_context_resolution_status: str | None = None


class UserMemory(BaseModel):
    user_memory_ref: str
    sender_id: str
    intent_counts: dict[str, int] = Field(default_factory=dict)
    preferred_brevity: str | None = None
