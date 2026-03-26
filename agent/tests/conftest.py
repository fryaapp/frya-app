"""Global test fixtures.

Clears the LLM config repository lru_cache between tests to prevent DB state
seeded in one test (e.g., test_agent_config.py::setup) from leaking into
communicator tests that expect TEMPLATE path (no model configured).
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def clear_llm_config_cache():
    """Clear only the llm_config_repository lru_cache after each test."""
    yield
    try:
        import app.dependencies as deps_module
        fn = getattr(deps_module, 'get_llm_config_repository', None)
        if fn is not None and hasattr(fn, 'cache_clear'):
            fn.cache_clear()
    except Exception:
        pass


@pytest.fixture(autouse=True)
def mock_paperless_upload(monkeypatch):
    """Default: Paperless upload succeeds in tests unless overridden.

    Tests that specifically test upload failure should override
    PaperlessConnector.upload_document themselves (their monkeypatch runs after
    this fixture and takes precedence).
    """
    from app.connectors.dms_paperless import PaperlessConnector

    _call_count = [0]

    async def _default_upload(self, file_bytes: bytes, filename: str, title: str | None = None):
        _call_count[0] += 1
        return {'task_id': f'test-task-{_call_count[0]:04d}'}

    monkeypatch.setattr(PaperlessConnector, 'upload_document', _default_upload)
