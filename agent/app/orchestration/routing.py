from __future__ import annotations

from app.orchestration.state import AgentState


def route_after_classification(state: AgentState) -> str:
    intent = state.get('intent', 'UNKNOWN')
    if intent == 'DOCUMENT_REVIEW':
        return 'run_document_analyst'
    if intent in {'ACCOUNTING_QUERY', 'WORKFLOW_TRIGGER'}:
        return 'draft_action_with_llm'
    return 'finalize_unknown'


def route_after_draft(state: AgentState) -> str:
    return 'apply_policy_constraints'
