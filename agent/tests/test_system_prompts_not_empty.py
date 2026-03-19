"""Tests: all agent system prompts are non-empty (no placeholders)."""
from __future__ import annotations

import pytest


MIN_PROMPT_LENGTH = 100


def test_communicator_prompt_not_empty():
    from app.telegram.communicator.prompts import COMMUNICATOR_SYSTEM_PROMPT
    assert len(COMMUNICATOR_SYSTEM_PROMPT) > MIN_PROMPT_LENGTH, (
        f'COMMUNICATOR_SYSTEM_PROMPT too short ({len(COMMUNICATOR_SYSTEM_PROMPT)} chars) — placeholder?'
    )


def test_communicator_prompt_contains_key_sections():
    from app.telegram.communicator.prompts import COMMUNICATOR_SYSTEM_PROMPT
    assert 'DU DARFST NICHT' in COMMUNICATOR_SYSTEM_PROMPT
    assert 'FRYA: ' in COMMUNICATOR_SYSTEM_PROMPT


def test_document_analyst_semantic_prompt_not_empty():
    from app.document_analysis.semantic_service import _SYSTEM_PROMPT
    assert len(_SYSTEM_PROMPT) > MIN_PROMPT_LENGTH, (
        f'Doc Analyst Semantic _SYSTEM_PROMPT too short — placeholder?'
    )


def test_document_analyst_semantic_prompt_has_new_types():
    from app.document_analysis.semantic_service import _SYSTEM_PROMPT
    for doc_type in ('CONTRACT', 'NOTICE', 'TAX_DOCUMENT', 'DUNNING'):
        assert doc_type in _SYSTEM_PROMPT, (
            f"New document type '{doc_type}' missing from Doc Analyst Semantic prompt"
        )


def test_document_analyst_semantic_prompt_has_references():
    from app.document_analysis.semantic_service import _SYSTEM_PROMPT
    assert 'references' in _SYSTEM_PROMPT


def test_accounting_analyst_prompt_not_empty():
    from app.accounting_analyst.service import _SYSTEM_PROMPT
    assert len(_SYSTEM_PROMPT) > MIN_PROMPT_LENGTH, (
        f'Accounting Analyst _SYSTEM_PROMPT too short — placeholder?'
    )


def test_accounting_analyst_prompt_has_confidence_cap():
    from app.accounting_analyst.service import _SYSTEM_PROMPT
    assert '0.90' in _SYSTEM_PROMPT, 'Missing confidence cap 0.90 in Accounting Analyst prompt'


def test_risk_analyst_prompt_not_empty():
    from app.risk_analyst.service import _SYSTEM_PROMPT
    assert len(_SYSTEM_PROMPT) > MIN_PROMPT_LENGTH, (
        f'Risk Analyst _SYSTEM_PROMPT too short — placeholder?'
    )


def test_risk_analyst_prompt_is_adversarial():
    from app.risk_analyst.service import _SYSTEM_PROMPT
    assert 'adversarial' in _SYSTEM_PROMPT.lower() or 'Fehler' in _SYSTEM_PROMPT


def test_risk_analyst_prompt_has_anomaly_types():
    from app.risk_analyst.service import _SYSTEM_PROMPT
    for anomaly in ('AMOUNT_DEVIATION', 'DUPLICATE_SUSPECT', 'TIMELINE_ANOMALY'):
        assert anomaly in _SYSTEM_PROMPT, f"Anomaly type '{anomaly}' missing from Risk Analyst prompt"


def test_orchestrator_prompt_not_empty():
    import importlib
    import sys
    # Import without running the full app
    import app.orchestration.nodes as nodes_mod
    # The prompt is built at call time — check the module loaded
    import inspect
    source = inspect.getsource(nodes_mod)
    assert 'Orchestrator' in source
    assert 'approval_hint' in source, 'New approval_hint field missing from Orchestrator prompt'
