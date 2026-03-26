"""Tests for Memory Curator file operations — init, append, read."""
from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import pytest

from app.memory_curator.service import MemoryCuratorService


def _svc(tmp_path: Path) -> MemoryCuratorService:
    return MemoryCuratorService(data_dir=tmp_path)


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Memory directory creation
# ---------------------------------------------------------------------------

def test_memory_dir_created_on_access(tmp_path):
    svc = _svc(tmp_path)
    tenant_id = uuid.uuid4()
    mem_dir = svc._memory_dir(tenant_id)
    assert mem_dir.exists()
    assert mem_dir.is_dir()
    assert mem_dir == tmp_path / 'memory' / str(tenant_id)


def test_memory_dir_different_per_tenant(tmp_path):
    svc = _svc(tmp_path)
    t1 = uuid.uuid4()
    t2 = uuid.uuid4()
    assert svc._memory_dir(t1) != svc._memory_dir(t2)


# ---------------------------------------------------------------------------
# Initial static files
# ---------------------------------------------------------------------------

def test_initial_files_all_created(tmp_path):
    svc = _svc(tmp_path)
    tenant_id = uuid.uuid4()
    mem_dir = svc._memory_dir(tenant_id)
    svc._ensure_static_files(mem_dir)

    for fname in ('agent.md', 'soul.md', 'user.md', 'memory.md', 'dms-state.md'):
        assert (mem_dir / fname).exists(), f'{fname} fehlt'


def test_agent_md_contains_frya(tmp_path):
    svc = _svc(tmp_path)
    tenant_id = uuid.uuid4()
    mem_dir = svc._memory_dir(tenant_id)
    svc._ensure_static_files(mem_dir)
    content = (mem_dir / 'agent.md').read_text(encoding='utf-8')
    assert 'FRYA' in content


def test_soul_md_contains_principles(tmp_path):
    svc = _svc(tmp_path)
    tenant_id = uuid.uuid4()
    mem_dir = svc._memory_dir(tenant_id)
    svc._ensure_static_files(mem_dir)
    content = (mem_dir / 'soul.md').read_text(encoding='utf-8')
    assert 'Genauigkeit' in content or 'Transparenz' in content


def test_user_md_and_memory_md_initially_empty(tmp_path):
    svc = _svc(tmp_path)
    tenant_id = uuid.uuid4()
    mem_dir = svc._memory_dir(tenant_id)
    svc._ensure_static_files(mem_dir)
    assert (mem_dir / 'user.md').read_text(encoding='utf-8') == ''
    assert (mem_dir / 'memory.md').read_text(encoding='utf-8') == ''


def test_ensure_static_files_does_not_overwrite_existing(tmp_path):
    svc = _svc(tmp_path)
    tenant_id = uuid.uuid4()
    mem_dir = svc._memory_dir(tenant_id)
    svc._ensure_static_files(mem_dir)

    (mem_dir / 'agent.md').write_text('custom_content', encoding='utf-8')
    (mem_dir / 'soul.md').write_text('custom_soul', encoding='utf-8')

    svc._ensure_static_files(mem_dir)

    assert (mem_dir / 'agent.md').read_text(encoding='utf-8') == 'custom_content'
    assert (mem_dir / 'soul.md').read_text(encoding='utf-8') == 'custom_soul'


def test_ensure_static_files_idempotent_multiple_calls(tmp_path):
    svc = _svc(tmp_path)
    tenant_id = uuid.uuid4()
    mem_dir = svc._memory_dir(tenant_id)
    for _ in range(3):
        svc._ensure_static_files(mem_dir)
    # Files still exist and unchanged
    assert 'FRYA' in (mem_dir / 'agent.md').read_text(encoding='utf-8')


# ---------------------------------------------------------------------------
# Daily log append
# ---------------------------------------------------------------------------

def test_daily_log_file_created(tmp_path):
    svc = _svc(tmp_path)
    tenant_id = uuid.uuid4()
    _run(svc.append_daily_log(tenant_id, 'Erster Eintrag'))
    mem_dir = svc._memory_dir(tenant_id)
    log_files = list(mem_dir.glob('????-??-??.md'))
    assert len(log_files) == 1


def test_daily_log_filename_is_date(tmp_path):
    from datetime import datetime, timezone
    svc = _svc(tmp_path)
    tenant_id = uuid.uuid4()
    _run(svc.append_daily_log(tenant_id, 'Test'))
    mem_dir = svc._memory_dir(tenant_id)
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    assert (mem_dir / f'{today}.md').exists()


def test_daily_log_contains_entry(tmp_path):
    svc = _svc(tmp_path)
    tenant_id = uuid.uuid4()
    _run(svc.append_daily_log(tenant_id, 'Telekom Rechnung 340€'))
    mem_dir = svc._memory_dir(tenant_id)
    log_files = list(mem_dir.glob('????-??-??.md'))
    content = log_files[0].read_text(encoding='utf-8')
    assert 'Telekom Rechnung 340€' in content


def test_daily_log_contains_timestamp(tmp_path):
    svc = _svc(tmp_path)
    tenant_id = uuid.uuid4()
    _run(svc.append_daily_log(tenant_id, 'Eintrag mit Timestamp'))
    mem_dir = svc._memory_dir(tenant_id)
    log_files = list(mem_dir.glob('????-??-??.md'))
    content = log_files[0].read_text(encoding='utf-8')
    # Timestamp format: [HH:MM:SS]
    import re
    assert re.search(r'\[\d{2}:\d{2}:\d{2}\]', content)


def test_daily_log_appends_multiple_entries(tmp_path):
    svc = _svc(tmp_path)
    tenant_id = uuid.uuid4()
    _run(svc.append_daily_log(tenant_id, 'Eintrag Alpha'))
    _run(svc.append_daily_log(tenant_id, 'Eintrag Beta'))
    _run(svc.append_daily_log(tenant_id, 'Eintrag Gamma'))
    mem_dir = svc._memory_dir(tenant_id)
    log_files = list(mem_dir.glob('????-??-??.md'))
    content = log_files[0].read_text(encoding='utf-8')
    assert 'Eintrag Alpha' in content
    assert 'Eintrag Beta' in content
    assert 'Eintrag Gamma' in content


def test_daily_log_append_strips_whitespace(tmp_path):
    svc = _svc(tmp_path)
    tenant_id = uuid.uuid4()
    _run(svc.append_daily_log(tenant_id, '   Leerzeichen   '))
    mem_dir = svc._memory_dir(tenant_id)
    log_files = list(mem_dir.glob('????-??-??.md'))
    content = log_files[0].read_text(encoding='utf-8')
    # Entry should be stripped but still present
    assert 'Leerzeichen' in content


def test_daily_log_separate_per_tenant(tmp_path):
    svc = _svc(tmp_path)
    t1 = uuid.uuid4()
    t2 = uuid.uuid4()
    _run(svc.append_daily_log(t1, 'Tenant-1-Eintrag'))
    _run(svc.append_daily_log(t2, 'Tenant-2-Eintrag'))

    mem_dir_1 = svc._memory_dir(t1)
    mem_dir_2 = svc._memory_dir(t2)
    log1 = list(mem_dir_1.glob('????-??-??.md'))[0].read_text(encoding='utf-8')
    log2 = list(mem_dir_2.glob('????-??-??.md'))[0].read_text(encoding='utf-8')

    assert 'Tenant-1-Eintrag' in log1
    assert 'Tenant-1-Eintrag' not in log2
    assert 'Tenant-2-Eintrag' in log2
    assert 'Tenant-2-Eintrag' not in log1


# ---------------------------------------------------------------------------
# Read file helper
# ---------------------------------------------------------------------------

def test_read_file_missing_returns_empty(tmp_path):
    svc = _svc(tmp_path)
    result = svc._read_file(tmp_path / 'nonexistent.md')
    assert result == ''


def test_read_file_returns_content(tmp_path):
    svc = _svc(tmp_path)
    p = tmp_path / 'test.md'
    p.write_text('Hallo Welt', encoding='utf-8')
    assert svc._read_file(p) == 'Hallo Welt'


# ---------------------------------------------------------------------------
# Write file helper
# ---------------------------------------------------------------------------

def test_write_file_creates_file(tmp_path):
    svc = _svc(tmp_path)
    p = tmp_path / 'subdir' / 'output.md'
    svc._write_file(p, 'Inhalt')
    assert p.exists()
    assert p.read_text(encoding='utf-8') == 'Inhalt'


def test_write_file_overwrites_existing(tmp_path):
    svc = _svc(tmp_path)
    p = tmp_path / 'file.md'
    p.write_text('alt', encoding='utf-8')
    svc._write_file(p, 'neu')
    assert p.read_text(encoding='utf-8') == 'neu'
