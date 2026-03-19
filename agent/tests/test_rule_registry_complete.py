"""Tests: rule_registry.yaml is complete and all required files exist on disk."""
from __future__ import annotations

import os

import pytest
import yaml


RULES_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'rules')

REQUIRED_ROLES = {
    'orchestrator_policy',
    'runtime_policy',
    'compliance_policy',
    'accounting_analyst_policy',
    'problemfall_policy',
    'approval_matrix_policy',
    'document_analyst_policy',
    'risk_consistency_policy',
    'memory_curator_policy',
    'deadline_analyst_policy',
    'communicator_policy',
    'document_workflows',
}


def _load_registry() -> list[dict]:
    registry_path = os.path.join(RULES_DIR, 'rule_registry.yaml')
    with open(registry_path, encoding='utf-8') as f:
        data = yaml.safe_load(f)
    return data['entries']


def test_registry_file_exists():
    path = os.path.join(RULES_DIR, 'rule_registry.yaml')
    assert os.path.isfile(path), f'rule_registry.yaml not found at {path}'


def test_registry_loads_without_error():
    entries = _load_registry()
    assert isinstance(entries, list)
    assert len(entries) > 0


def test_all_required_roles_present():
    entries = _load_registry()
    roles = {e['role'] for e in entries}
    missing = REQUIRED_ROLES - roles
    assert not missing, f'Missing required roles in rule_registry.yaml: {missing}'


def test_required_entries_have_required_true():
    entries = _load_registry()
    for entry in entries:
        if entry['role'] in REQUIRED_ROLES:
            assert entry.get('required') is True, (
                f"Entry with role '{entry['role']}' should have required=true"
            )


_ALL_REQUIRED_FILES = {
    'policies/orchestrator_policy.md',
    'policies/runtime_policy.md',
    'policies/gobd_compliance_policy.md',
    'policies/accounting_analyst_policy.md',
    'policies/problemfall_policy.md',
    'policies/freigabematrix.md',
    'policies/document_analyst_policy.md',
    'policies/risk_consistency_policy.md',
    'policies/memory_curator_policy.md',
    'policies/deadline_analyst_policy.md',
    'policies/communicator_policy.md',
    'document_workflows.yaml',
}


def test_all_required_files_exist_on_disk():
    """Verify all 11 policies + document_workflows.yaml exist on disk."""
    missing_files = []
    for relative_path in _ALL_REQUIRED_FILES:
        file_path = os.path.join(RULES_DIR, relative_path)
        if not os.path.isfile(file_path):
            missing_files.append(relative_path)
    assert not missing_files, f'Required rule files missing on disk: {missing_files}'


def test_all_required_files_non_empty():
    """Verify all 11 policies + document_workflows.yaml are non-empty."""
    empty_files = []
    for relative_path in _ALL_REQUIRED_FILES:
        file_path = os.path.join(RULES_DIR, relative_path)
        if os.path.isfile(file_path) and os.path.getsize(file_path) == 0:
            empty_files.append(relative_path)
    assert not empty_files, f'Required rule files are empty: {empty_files}'
