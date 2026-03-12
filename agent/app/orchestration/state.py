from __future__ import annotations

from typing import Any, Literal, TypedDict


class AgentState(TypedDict, total=False):
    case_id: str
    source: str
    message: str
    document_ref: str | None
    paperless_metadata: dict[str, Any]
    ocr_text: str | None
    preview_text: str | None
    case_context: dict[str, Any]
    accounting_review: dict[str, Any]
    accounting_analysis: dict[str, Any]
    intent: Literal['DOCUMENT_REVIEW', 'ACCOUNTING_QUERY', 'WORKFLOW_TRIGGER', 'UNKNOWN']
    requires_approval: bool
    approved: bool
    approval_id: str | None
    planned_action: dict[str, Any]
    document_analysis: dict[str, Any]
    deterministic_rule_path: bool
    policy_blocked: bool
    policy_gate_reason: str
    policy_refs_consulted: list[dict[str, str]]
    approval_mode: Literal['AUTO', 'PROPOSE_ONLY', 'REQUIRE_USER_APPROVAL', 'BLOCK_ESCALATE']
    gate_action_key: str
    gate_requires_open_item: bool
    gate_requires_problem_case: bool
    execution_allowed: bool
    output: dict[str, Any]

