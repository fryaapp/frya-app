from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


ReviewStatus = Literal['READY', 'NEEDS_HUMAN_REVIEW']


class AccountingReviewDraft(BaseModel):
    model_config = ConfigDict(extra='forbid')

    review_version: str = 'accounting-review-v1'
    case_id: str
    document_ref: str | None = None
    source_document_type: Literal['INVOICE', 'REMINDER']
    review_status: ReviewStatus
    ready_for_accounting_review: bool = False
    analysis_summary: str
    sender: str | None = None
    recipient: str | None = None
    total_amount: str | None = None
    currency: str | None = None
    document_date: str | None = None
    due_date: str | None = None
    references: list[str] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    suggested_review_focus: list[str] = Field(default_factory=list)
    next_step: str
