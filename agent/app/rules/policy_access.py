from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.approvals.matrix import evaluate_approval_mode
from app.rules.loader import RuleLoader


REQUIRED_POLICY_ROLES: tuple[str, ...] = (
    'orchestrator_policy',
    'runtime_policy',
    'compliance_policy',
    'accounting_analyst_policy',
    'problemfall_policy',
    'approval_matrix_policy',
)


@dataclass(slots=True)
class PolicyGateDecision:
    blocked: bool
    requires_approval: bool
    deterministic_rule_path: bool
    reason: str
    consulted_policy_refs: list[dict[str, str]]
    decision_mode: str
    action_key: str
    requires_open_item: bool
    requires_problem_case: bool
    execution_allowed: bool


class PolicyAccessLayer:
    def __init__(self, loader: RuleLoader) -> None:
        self.loader = loader

    def _status_by_role(self) -> dict[str, dict[str, Any]]:
        mapping: dict[str, dict[str, Any]] = {}
        for item in self.loader.load_status():
            role = str(item.get('role') or '')
            if role:
                mapping[role] = item
        return mapping

    def required_policies_loaded(self) -> tuple[bool, list[str]]:
        status_by_role = self._status_by_role()
        missing: list[str] = []
        for role in REQUIRED_POLICY_ROLES:
            item = status_by_role.get(role)
            if not item or not item.get('loaded', False):
                missing.append(role)
        return (len(missing) == 0), missing

    def get_policy_refs(self, roles: list[str]) -> list[dict[str, str]]:
        status_by_role = self._status_by_role()
        refs: list[dict[str, str]] = []
        for role in roles:
            item = status_by_role.get(role)
            if not item or not item.get('loaded', False):
                continue
            refs.append(
                {
                    'policy_name': role,
                    'policy_version': str(item.get('version') or 'unknown'),
                    'policy_path': str(item.get('file') or ''),
                    'policy_registry_key': role,
                }
            )
        return refs

    def _matrix_payload(self, status_by_role: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
        matrix_doc = status_by_role.get('legacy_approval_matrix_schema')
        if not matrix_doc:
            return None
        if not matrix_doc.get('loaded', False):
            return None
        parsed = matrix_doc.get('parsed')
        return parsed if isinstance(parsed, dict) else None

    def evaluate_gate(self, intent: str, action_name: str, context: dict[str, Any] | None = None) -> PolicyGateDecision:
        ctx = dict(context or {})
        ok, missing = self.required_policies_loaded()
        status_by_role = self._status_by_role()

        consulted_roles = [
            'orchestrator_policy',
            'runtime_policy',
            'compliance_policy',
            'approval_matrix_policy',
            'problemfall_policy',
            'legacy_approval_matrix_schema',
        ]
        if intent == 'ACCOUNTING_QUERY':
            consulted_roles.append('accounting_analyst_policy')

        refs = self.get_policy_refs(consulted_roles)

        action = (action_name or '').lower()
        deterministic_rule_path = bool(
            ctx.get('deterministic_rule_path')
            or ctx.get('explicit_workflow_rule')
            or (intent == 'WORKFLOW_TRIGGER' and ('workflow' in action or 'n8n' in action))
        )
        ctx['explicit_workflow_rule'] = bool(ctx.get('explicit_workflow_rule') or deterministic_rule_path)

        matrix_decision = evaluate_approval_mode(
            action_name=action_name,
            context=ctx,
            matrix_payload=self._matrix_payload(status_by_role),
        )

        if not ok:
            return PolicyGateDecision(
                blocked=True,
                requires_approval=True,
                deterministic_rule_path=deterministic_rule_path,
                reason=f'Pflicht-Policies fehlen oder nicht ladbar: {", ".join(missing)}',
                consulted_policy_refs=refs,
                decision_mode='BLOCK_ESCALATE',
                action_key=matrix_decision.action_key,
                requires_open_item=True,
                requires_problem_case=True,
                execution_allowed=False,
            )

        return PolicyGateDecision(
            blocked=matrix_decision.mode == 'BLOCK_ESCALATE',
            requires_approval=matrix_decision.mode == 'REQUIRE_USER_APPROVAL',
            deterministic_rule_path=deterministic_rule_path,
            reason=matrix_decision.reason,
            consulted_policy_refs=refs,
            decision_mode=matrix_decision.mode,
            action_key=matrix_decision.action_key,
            requires_open_item=matrix_decision.requires_open_item,
            requires_problem_case=matrix_decision.requires_problem_case,
            execution_allowed=matrix_decision.execution_allowed,
        )
