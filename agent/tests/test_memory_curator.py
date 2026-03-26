"""Tests for MemoryCuratorService — Daily Curation, Context Assembly, DmsState."""
from __future__ import annotations

import asyncio
import uuid
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.memory_curator.schemas import CurationResult, DmsState
from app.memory_curator.service import MemoryCuratorService, _count_tokens


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_case(status: str = 'OPEN') -> MagicMock:
    c = MagicMock()
    c.id = uuid.uuid4()
    c.tenant_id = uuid.uuid4()
    c.status = status
    c.created_at = '2026-03-18T10:00:00'
    return c


def _make_case_repo(cases: list) -> MagicMock:
    repo = MagicMock()
    repo.list_active_cases_for_tenant = AsyncMock(return_value=cases)
    return repo


def _make_audit_svc() -> MagicMock:
    svc = MagicMock()
    svc.log_event = AsyncMock(return_value=None)
    return svc


def _make_llm_repo(model: str = '', provider: str = '') -> MagicMock:
    repo = MagicMock()
    repo.get_config_or_fallback = AsyncMock(return_value={
        'agent_id': 'memory_curator',
        'model': model,
        'provider': provider,
        'api_key_encrypted': None,
        'base_url': None,
    })
    repo.get_all_configs = AsyncMock(return_value=[
        {'agent_id': 'orchestrator', 'agent_status': 'active'},
        {'agent_id': 'memory_curator', 'agent_status': 'active'},
    ])
    repo.decrypt_key_for_call = MagicMock(return_value=None)
    return repo


def _svc(tmp_path: Path, *, case_repo=None, audit_svc=None, llm_repo=None) -> MemoryCuratorService:
    return MemoryCuratorService(
        data_dir=tmp_path,
        llm_config_repository=llm_repo,
        case_repository=case_repo or _make_case_repo([]),
        audit_service=audit_svc or _make_audit_svc(),
    )


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# _count_tokens
# ---------------------------------------------------------------------------

def test_count_tokens_empty():
    assert _count_tokens('') == 1  # min 1


def test_count_tokens_basic():
    text = 'a' * 400
    assert _count_tokens(text) == 100


# ---------------------------------------------------------------------------
# Static file initialization
# ---------------------------------------------------------------------------

def test_ensure_static_files_creates_defaults(tmp_path):
    tenant_id = uuid.uuid4()
    svc = _svc(tmp_path)
    mem_dir = svc._memory_dir(tenant_id)
    svc._ensure_static_files(mem_dir)

    assert (mem_dir / 'agent.md').exists()
    assert (mem_dir / 'soul.md').exists()
    assert (mem_dir / 'user.md').exists()
    assert (mem_dir / 'memory.md').exists()
    assert (mem_dir / 'dms-state.md').exists()

    agent_content = (mem_dir / 'agent.md').read_text(encoding='utf-8')
    assert 'FRYA' in agent_content


def test_ensure_static_files_idempotent(tmp_path):
    """Calling twice does not overwrite existing files."""
    tenant_id = uuid.uuid4()
    svc = _svc(tmp_path)
    mem_dir = svc._memory_dir(tenant_id)
    svc._ensure_static_files(mem_dir)

    # Write custom content
    (mem_dir / 'agent.md').write_text('custom', encoding='utf-8')
    svc._ensure_static_files(mem_dir)
    assert (mem_dir / 'agent.md').read_text(encoding='utf-8') == 'custom'


# ---------------------------------------------------------------------------
# append_daily_log
# ---------------------------------------------------------------------------

def test_append_daily_log_creates_file(tmp_path):
    tenant_id = uuid.uuid4()
    svc = _svc(tmp_path)
    _run(svc.append_daily_log(tenant_id, 'Testnachricht'))
    mem_dir = svc._memory_dir(tenant_id)
    log_files = list(mem_dir.glob('*.md'))
    assert len(log_files) >= 1
    content = log_files[0].read_text(encoding='utf-8')
    assert 'Testnachricht' in content


def test_append_daily_log_appends(tmp_path):
    tenant_id = uuid.uuid4()
    svc = _svc(tmp_path)
    _run(svc.append_daily_log(tenant_id, 'Eintrag 1'))
    _run(svc.append_daily_log(tenant_id, 'Eintrag 2'))
    mem_dir = svc._memory_dir(tenant_id)
    log_files = list(mem_dir.glob('*.md'))
    content = log_files[0].read_text(encoding='utf-8')
    assert 'Eintrag 1' in content
    assert 'Eintrag 2' in content


# ---------------------------------------------------------------------------
# get_dms_state
# ---------------------------------------------------------------------------

def test_get_dms_state_counts_correctly(tmp_path):
    tenant_id = uuid.uuid4()
    cases = [_make_case('OPEN'), _make_case('OPEN'), _make_case('OVERDUE')]
    svc = _svc(tmp_path, case_repo=_make_case_repo(cases))
    state = _run(svc.get_dms_state(tenant_id))

    assert state.open_cases == 2
    assert state.overdue_cases == 1
    assert state.total_cases == 3
    assert state.system_health == 'ok'
    assert state.generated_at is not None


def test_get_dms_state_no_case_repo(tmp_path):
    tenant_id = uuid.uuid4()
    svc = MemoryCuratorService(data_dir=tmp_path)
    state = _run(svc.get_dms_state(tenant_id))
    assert state.total_cases == 0
    assert state.system_health == 'ok'


def test_get_dms_state_includes_active_agents(tmp_path):
    tenant_id = uuid.uuid4()
    svc = _svc(tmp_path, llm_repo=_make_llm_repo())
    state = _run(svc.get_dms_state(tenant_id))
    assert 'orchestrator' in state.active_agents
    assert 'memory_curator' in state.active_agents


def test_get_dms_state_case_repo_exception_swallowed(tmp_path):
    tenant_id = uuid.uuid4()
    repo = MagicMock()
    repo.list_active_cases_for_tenant = AsyncMock(side_effect=RuntimeError('DB down'))
    svc = _svc(tmp_path, case_repo=repo)
    state = _run(svc.get_dms_state(tenant_id))
    assert state.total_cases == 0


# ---------------------------------------------------------------------------
# get_context_assembly
# ---------------------------------------------------------------------------

def test_get_context_assembly_empty_state(tmp_path):
    tenant_id = uuid.uuid4()
    svc = _svc(tmp_path)
    ctx = _run(svc.get_context_assembly(tenant_id))
    assert '[AGENT]' in ctx
    assert '[PRINZIPIEN]' in ctx
    assert 'FRYA' in ctx


def test_get_context_assembly_includes_memory(tmp_path):
    tenant_id = uuid.uuid4()
    svc = _svc(tmp_path)
    mem_dir = svc._memory_dir(tenant_id)
    svc._ensure_static_files(mem_dir)
    (mem_dir / 'memory.md').write_text('Wichtige Erinnerung: X', encoding='utf-8')

    ctx = _run(svc.get_context_assembly(tenant_id))
    assert 'Wichtige Erinnerung' in ctx
    assert 'LANGZEITGEDAECHTNISS' in ctx


def test_get_context_assembly_includes_daily_log(tmp_path):
    tenant_id = uuid.uuid4()
    svc = _svc(tmp_path)
    _run(svc.append_daily_log(tenant_id, 'Telekom Rechnung 340€ angekommen'))
    ctx = _run(svc.get_context_assembly(tenant_id))
    assert 'Telekom' in ctx


def test_get_context_assembly_includes_dms_state(tmp_path):
    tenant_id = uuid.uuid4()
    svc = _svc(tmp_path)
    mem_dir = svc._memory_dir(tenant_id)
    svc._ensure_static_files(mem_dir)
    (mem_dir / 'dms-state.md').write_text('# DMS State\n- Open: 5', encoding='utf-8')
    ctx = _run(svc.get_context_assembly(tenant_id))
    assert 'DMS-STATE' in ctx


# ---------------------------------------------------------------------------
# curate_daily — without LLM (no model configured)
# ---------------------------------------------------------------------------

def test_curate_daily_updates_dms_state(tmp_path):
    tenant_id = uuid.uuid4()
    cases = [_make_case('OPEN'), _make_case('OVERDUE')]
    svc = _svc(tmp_path, case_repo=_make_case_repo(cases))
    result = _run(svc.curate_daily(tenant_id))

    assert isinstance(result, CurationResult)
    assert result.dms_state_updated is True
    assert str(tenant_id) == result.tenant_id


def test_curate_daily_writes_dms_state_file(tmp_path):
    tenant_id = uuid.uuid4()
    cases = [_make_case('OPEN')]
    svc = _svc(tmp_path, case_repo=_make_case_repo(cases))
    _run(svc.curate_daily(tenant_id))

    state_path = svc._memory_dir(tenant_id) / 'dms-state.md'
    assert state_path.exists()
    content = state_path.read_text(encoding='utf-8')
    assert 'DMS State' in content


def test_curate_daily_no_memory_update_without_llm(tmp_path):
    """Without LLM model configured, memory.md is NOT updated."""
    tenant_id = uuid.uuid4()
    svc = _svc(tmp_path, llm_repo=_make_llm_repo(model=''))
    result = _run(svc.curate_daily(tenant_id))
    # No LLM → memory_md_updated stays False
    assert result.memory_md_updated is False


def test_curate_daily_writes_audit_event(tmp_path):
    tenant_id = uuid.uuid4()
    audit = _make_audit_svc()
    svc = _svc(tmp_path, audit_svc=audit)
    _run(svc.curate_daily(tenant_id))

    audit.log_event.assert_called_once()
    call_args = audit.log_event.call_args[0][0]
    assert call_args['action'] == 'MEMORY_CURATED'
    assert call_args['agent_name'] == 'memory-curator-v1'


def test_curate_daily_result_has_summary(tmp_path):
    tenant_id = uuid.uuid4()
    svc = _svc(tmp_path)
    result = _run(svc.curate_daily(tenant_id))
    assert len(result.summary) > 0
    assert 'Kuration' in result.summary


# ---------------------------------------------------------------------------
# curate_daily — with LLM mock
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_curate_daily_with_llm_updates_memory(tmp_path):
    """When LLM returns content, memory.md is updated."""
    from unittest.mock import patch

    tenant_id = uuid.uuid4()
    llm_repo = _make_llm_repo(model='meta-llama/Meta-Llama-3.1-405B-Instruct-FP8', provider='ionos')
    audit = _make_audit_svc()
    svc = _svc(tmp_path, llm_repo=llm_repo, audit_svc=audit)

    # Add some daily log content
    await svc.append_daily_log(tenant_id, 'Telekom GmbH Rechnung 340€ eingegangen')

    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock()]
    mock_resp.choices[0].message.content = 'Telekom GmbH ist regelmäßiger Lieferant. Rechnungen ca. 340€/Monat.'

    with patch('litellm.acompletion', new=AsyncMock(return_value=mock_resp)):
        result = await svc.curate_daily(tenant_id)

    assert result.memory_md_updated is True
    mem_path = svc._memory_dir(tenant_id) / 'memory.md'
    content = mem_path.read_text(encoding='utf-8')
    assert 'Telekom' in content


@pytest.mark.asyncio
async def test_curate_daily_llm_failure_swallowed(tmp_path):
    """LLM failure does not crash curation — dms-state still updated."""
    from unittest.mock import patch

    tenant_id = uuid.uuid4()
    llm_repo = _make_llm_repo(model='some-model', provider='ionos')
    svc = _svc(tmp_path, llm_repo=llm_repo)

    await svc.append_daily_log(tenant_id, 'Test Eintrag')

    with patch('litellm.acompletion', new=AsyncMock(side_effect=RuntimeError('LLM down'))):
        result = await svc.curate_daily(tenant_id)

    assert result.memory_md_updated is False
    assert result.dms_state_updated is True


@pytest.mark.asyncio
async def test_curate_daily_memory_token_limit_enforced(tmp_path):
    """LLM response exceeding token limit is truncated."""
    from unittest.mock import patch

    tenant_id = uuid.uuid4()
    llm_repo = _make_llm_repo(model='some-model', provider='ionos')
    svc = _svc(tmp_path, llm_repo=llm_repo)

    await svc.append_daily_log(tenant_id, 'Test')

    # LLM returns more than 2000 tokens worth of content
    huge_text = 'x' * 10000
    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock()]
    mock_resp.choices[0].message.content = huge_text

    with patch('litellm.acompletion', new=AsyncMock(return_value=mock_resp)):
        result = await svc.curate_daily(tenant_id)

    if result.memory_md_updated:
        assert result.tokens_after <= 2000 + 10  # small margin for '[gekürzt]'
