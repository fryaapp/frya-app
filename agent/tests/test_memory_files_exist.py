"""Tests: core memory files exist and are non-empty."""
from __future__ import annotations

import os

import pytest


DATA_DIR = os.path.join(os.path.dirname(__file__), '..', 'data')

REQUIRED_MEMORY_FILES = ['agent.md', 'soul.md', 'user.md', 'memory.md']


@pytest.mark.parametrize('filename', REQUIRED_MEMORY_FILES)
def test_memory_file_exists(filename: str):
    path = os.path.join(DATA_DIR, filename)
    assert os.path.isfile(path), f'Memory file missing: {path}'


@pytest.mark.parametrize('filename', REQUIRED_MEMORY_FILES)
def test_memory_file_non_empty(filename: str):
    path = os.path.join(DATA_DIR, filename)
    size = os.path.getsize(path)
    assert size > 0, f'Memory file is empty: {path}'


@pytest.mark.parametrize('filename', REQUIRED_MEMORY_FILES)
def test_memory_file_has_content(filename: str):
    path = os.path.join(DATA_DIR, filename)
    with open(path, encoding='utf-8') as f:
        content = f.read().strip()
    assert len(content) > 50, (
        f'Memory file has too little content (placeholder?): {path} — {len(content)} chars'
    )
