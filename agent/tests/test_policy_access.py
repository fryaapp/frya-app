from pathlib import Path

from app.rules.loader import RuleLoader
from app.rules.policy_access import PolicyAccessLayer


def _write_required_registry(rules: Path) -> None:
    (rules / 'rule_registry.yaml').write_text(
        'version: 1\nentries:\n'
        '  - file: policies/orchestrator_policy.md\n    role: orchestrator_policy\n    required: true\n'
        '  - file: policies/runtime_policy.md\n    role: runtime_policy\n    required: true\n'
        '  - file: policies/gobd_compliance_policy.md\n    role: compliance_policy\n    required: true\n'
        '  - file: policies/accounting_analyst_policy.md\n    role: accounting_analyst_policy\n    required: true\n'
        '  - file: policies/problemfall_policy.md\n    role: problemfall_policy\n    required: true\n'
        '  - file: policies/freigabematrix.md\n    role: approval_matrix_policy\n    required: true\n',
        encoding='utf-8',
    )


def _write_required_policy_files(policies: Path) -> None:
    for name in [
        'orchestrator_policy.md',
        'runtime_policy.md',
        'gobd_compliance_policy.md',
        'accounting_analyst_policy.md',
        'problemfall_policy.md',
        'freigabematrix.md',
    ]:
        (policies / name).write_text('Version: 1.0\n', encoding='utf-8')


def test_policy_access_loads_required_roles(tmp_path: Path):
    rules = tmp_path / 'rules'
    policies = rules / 'policies'
    policies.mkdir(parents=True, exist_ok=True)

    _write_required_registry(rules)
    _write_required_policy_files(policies)

    layer = PolicyAccessLayer(RuleLoader(rules))
    ok, missing = layer.required_policies_loaded()
    assert ok is True
    assert missing == []

    gate = layer.evaluate_gate(intent='ACCOUNTING_QUERY', action_name='post_booking')
    assert gate.requires_approval is True
    assert gate.blocked is False
    assert gate.decision_mode == 'REQUIRE_USER_APPROVAL'
    assert len(gate.consulted_policy_refs) >= 5


def test_policy_access_matrix_modes(tmp_path: Path):
    rules = tmp_path / 'rules'
    policies = rules / 'policies'
    policies.mkdir(parents=True, exist_ok=True)

    _write_required_registry(rules)
    _write_required_policy_files(policies)

    layer = PolicyAccessLayer(RuleLoader(rules))

    auto_gate = layer.evaluate_gate(intent='DOCUMENT_REVIEW', action_name='set_tag', context={'confidence': 0.95})
    assert auto_gate.decision_mode == 'AUTO'
    assert auto_gate.execution_allowed is True

    propose_gate = layer.evaluate_gate(intent='DOCUMENT_REVIEW', action_name='buchungsvorschlag', context={'confidence': 0.91})
    assert propose_gate.decision_mode == 'PROPOSE_ONLY'
    assert propose_gate.execution_allowed is False

    approval_gate = layer.evaluate_gate(intent='ACCOUNTING_QUERY', action_name='booking_finalize', context={'confidence': 0.9})
    assert approval_gate.decision_mode == 'REQUIRE_USER_APPROVAL'
    assert approval_gate.requires_approval is True

    blocked_gate = layer.evaluate_gate(intent='ACCOUNTING_QUERY', action_name='payment_execute', context={'confidence': 0.99})
    assert blocked_gate.decision_mode == 'BLOCK_ESCALATE'
    assert blocked_gate.blocked is True


def test_policy_access_blocks_on_missing_required_policies(tmp_path: Path):
    rules = tmp_path / 'rules'
    rules.mkdir(parents=True, exist_ok=True)
    (rules / 'rule_registry.yaml').write_text(
        'version: 1\nentries:\n'
        '  - file: policies/orchestrator_policy.md\n    role: orchestrator_policy\n    required: true\n',
        encoding='utf-8',
    )

    layer = PolicyAccessLayer(RuleLoader(rules))
    gate = layer.evaluate_gate(intent='DOCUMENT_REVIEW', action_name='set_tag', context={'confidence': 0.95})

    assert gate.blocked is True
    assert gate.decision_mode == 'BLOCK_ESCALATE'
    assert gate.requires_problem_case is True
