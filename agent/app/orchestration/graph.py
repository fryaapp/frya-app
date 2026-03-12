from __future__ import annotations

from langgraph.graph import END, StateGraph

from app.dependencies import get_policy_access_layer
from app.orchestration.nodes import (
    apply_policy_constraints,
    classify_intent,
    draft_action_with_llm,
    enforce_approval_gate,
    finalize_document_review,
    run_accounting_analyst,
    run_document_analyst,
)
from app.orchestration.routing import route_after_classification, route_after_draft
from app.orchestration.state import AgentState


async def finalize_unknown(state: AgentState) -> AgentState:
    policy_access = get_policy_access_layer()
    refs = policy_access.get_policy_refs(['orchestrator_policy', 'runtime_policy', 'compliance_policy'])
    state['output'] = {
        'status': 'UNKNOWN_INTENT',
        'message': 'Fall konnte nicht sicher klassifiziert werden. Open Item erstellen und Rueckfrage ausloesen.',
        'policy_refs': refs,
    }
    state['policy_refs_consulted'] = refs
    return state


def build_graph():
    graph = StateGraph(AgentState)
    graph.add_node('classify_intent', classify_intent)
    graph.add_node('run_document_analyst', run_document_analyst)
    graph.add_node('finalize_document_review', finalize_document_review)
    graph.add_node('run_accounting_analyst', run_accounting_analyst)
    graph.add_node('draft_action_with_llm', draft_action_with_llm)
    graph.add_node('apply_policy_constraints', apply_policy_constraints)
    graph.add_node('enforce_approval_gate', enforce_approval_gate)
    graph.add_node('finalize_unknown', finalize_unknown)

    graph.set_entry_point('classify_intent')
    graph.add_conditional_edges('classify_intent', route_after_classification, {
        'run_document_analyst': 'run_document_analyst',
        'draft_action_with_llm': 'draft_action_with_llm',
        'finalize_unknown': 'finalize_unknown',
    })
    graph.add_conditional_edges('draft_action_with_llm', route_after_draft, {
        'apply_policy_constraints': 'apply_policy_constraints',
    })

    graph.add_edge('run_document_analyst', 'finalize_document_review')
    graph.add_edge('finalize_document_review', 'run_accounting_analyst')
    graph.add_edge('run_accounting_analyst', END)
    graph.add_edge('apply_policy_constraints', 'enforce_approval_gate')
    graph.add_edge('enforce_approval_gate', END)
    graph.add_edge('finalize_unknown', END)

    return graph.compile()
