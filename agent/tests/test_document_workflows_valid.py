"""Tests: document_workflows.yaml is valid and well-formed."""
from __future__ import annotations

import os

import pytest
import yaml


WORKFLOWS_PATH = os.path.join(
    os.path.dirname(__file__), '..', 'data', 'rules', 'document_workflows.yaml'
)


def _load_workflows() -> dict:
    with open(WORKFLOWS_PATH, encoding='utf-8') as f:
        return yaml.safe_load(f)


def _get_types(data: dict) -> dict:
    """Support both top-level types and nested 'document_types' key."""
    if 'document_types' in data:
        return data['document_types']
    return data


def test_file_exists():
    assert os.path.isfile(WORKFLOWS_PATH), f'document_workflows.yaml not found at {WORKFLOWS_PATH}'


def test_file_parseable():
    data = _load_workflows()
    assert isinstance(data, dict)


def test_document_types_present():
    data = _load_workflows()
    types = _get_types(data)
    assert isinstance(types, dict)
    assert len(types) > 0


def test_all_types_have_chain():
    data = _load_workflows()
    for doc_type, config in _get_types(data).items():
        assert 'agent_chain' in config or 'chain' in config, (
            f"Document type '{doc_type}' missing 'agent_chain'/'chain' key"
        )
        chain = config.get('agent_chain') or config.get('chain', [])
        assert isinstance(chain, list), f"chain for '{doc_type}' must be a list"
        assert len(chain) > 0, f"chain for '{doc_type}' must not be empty"


def test_all_types_have_approval_default():
    data = _load_workflows()
    for doc_type, config in _get_types(data).items():
        assert 'approval_default' in config, (
            f"Document type '{doc_type}' missing 'approval_default' key"
        )
        assert isinstance(config['approval_default'], str), (
            f"approval_default for '{doc_type}' must be a string"
        )
        assert len(config['approval_default']) > 0, (
            f"approval_default for '{doc_type}' must not be empty"
        )


def test_chain_agents_are_known():
    known_agents = {
        'document_analyst', 'document_analyst_semantic', 'doc_analyst_semantic',
        'accounting_analyst', 'deadline_analyst', 'risk_consistency',
        'memory_curator', 'communicator', 'orchestrator',
        'doc_analyst_ocr', 'case_engine_assign',
    }
    data = _load_workflows()
    for doc_type, config in _get_types(data).items():
        chain = config.get('agent_chain') or config.get('chain', [])
        for agent in chain:
            assert agent in known_agents, (
                f"Unknown agent '{agent}' in chain for '{doc_type}'"
            )
