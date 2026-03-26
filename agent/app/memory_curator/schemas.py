"""Pydantic schemas for Memory Curator."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class MemoryUpdate(BaseModel):
    """Represents a single file update performed by the curator."""
    file_path: str
    changes_summary: str
    tokens_before: int = 0
    tokens_after: int = 0


class DmsState(BaseModel):
    """Current state of the DMS system, derived from DB (no LLM needed)."""
    total_cases: int = 0
    open_cases: int = 0
    overdue_cases: int = 0
    last_document_at: str | None = None
    active_agents: list[str] = Field(default_factory=list)
    system_health: str = 'unknown'
    generated_at: str | None = None


class CurationResult(BaseModel):
    """Result of a daily curation run."""
    memory_md_updated: bool = False
    dms_state_updated: bool = False
    user_md_updated: bool = False
    tokens_before: int = 0
    tokens_after: int = 0
    changes: list[MemoryUpdate] = Field(default_factory=list)
    summary: str = ''
    tenant_id: str = ''
