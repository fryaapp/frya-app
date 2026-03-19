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
