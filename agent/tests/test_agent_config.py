import asyncio
import importlib
import json
import re
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient


def _prepare_data(tmp_path: Path) -> None:
    rules = tmp_path / 'rules'
    policies = rules / 'policies'
    policies.mkdir(parents=True, exist_ok=True)
    (tmp_path / 'verfahrensdoku').mkdir(parents=True, exist_ok=True)
    (tmp_path / 'system' / 'proposals').mkdir(parents=True, exist_ok=True)
    (tmp_path / 'audit').mkdir(parents=True, exist_ok=True)
    (tmp_path / 'tasks').mkdir(parents=True, exist_ok=True)
    (tmp_path / 'memory').mkdir(parents=True, exist_ok=True)

    (tmp_path / 'agent.md').write_text('a', encoding='utf-8')
    (tmp_path / 'user.md').write_text('u', encoding='utf-8')
    (tmp_path / 'soul.md').write_text('s', encoding='utf-8')
    (tmp_path / 'memory.md').write_text('m', encoding='utf-8')
    (tmp_path / 'dms-state.md').write_text('d', encoding='utf-8')
    (tmp_path / 'audit' / 'problem_cases.md').write_text('# Problems\n', encoding='utf-8')
    (tmp_path / 'verfahrensdoku' / 'system_overview.md').write_text('# overview\n', encoding='utf-8')
    (rules / 'runtime_rules.yaml').write_text('version: 1\nname: runtime\n', encoding='utf-8')
    (rules / 'approval_matrix.yaml').write_text(
        'version: 1\nname: approval_matrix\nrules:\n'
        '  - action: rule_policy_edit\n'
        '    mode: REQUIRE_USER_APPROVAL\n'
        '    strict_require: true\n',
        encoding='utf-8',
    )
    (rules / 'rule_registry.yaml').write_text(
        'version: 1\nentries:\n'
        '  - file: policies/orchestrator_policy.md\n    role: orchestrator_policy\n    required: true\n'
        '  - file: policies/runtime_policy.md\n    role: runtime_policy\n    required: true\n'
        '  - file: policies/gobd_compliance_policy.md\n    role: compliance_policy\n    required: true\n'
        '  - file: policies/accounting_analyst_policy.md\n    role: accounting_analyst_policy\n    required: true\n'
        '  - file: policies/problemfall_policy.md\n    role: problemfall_policy\n    required: true\n'
        '  - file: policies/freigabematrix.md\n    role: approval_matrix_policy\n    required: true\n'
        '  - file: approval_matrix.yaml\n    role: legacy_approval_matrix_schema\n    required: false\n',
        encoding='utf-8',
    )
    for name in [
        'orchestrator_policy.md',
        'runtime_policy.md',
        'gobd_compliance_policy.md',
        'accounting_analyst_policy.md',
        'problemfall_policy.md',
        'freigabematrix.md',
    ]:
        (policies / name).write_text('Version: 1.0\n', encoding='utf-8')


def _build_users_json() -> str:
    from app.auth.service import hash_password_pbkdf2
    return json.dumps([
        {'username': 'admin', 'role': 'admin', 'password_hash': hash_password_pbkdf2('admin-pass')},
    ])


def _clear_caches() -> None:
    import app.auth.service as auth_service_module
    import app.config as config_module
    import app.dependencies as deps_module

    config_module.get_settings.cache_clear()
    auth_service_module.get_auth_service.cache_clear()

    for name in dir(deps_module):
        obj = getattr(deps_module, name)
        if callable(obj) and hasattr(obj, 'cache_clear'):
            obj.cache_clear()


def _build_app():
    _clear_caches()
    import app.main as main_module
    importlib.reload(main_module)
    return main_module.app


def _extract_csrf_token(html: str) -> str:
    m = re.search(r'name="csrf_token"\s+value="([^"]+)"', html)
    if m:
        return m.group(1)
    m = re.search(r"CSRF\s*=\s*'([^']+)'", html)
    assert m, 'csrf_token nicht im HTML gefunden'
    return m.group(1)


def _login(client: TestClient, username: str, password: str):
    return client.post(
        '/auth/login',
        data={'username': username, 'password': password, 'next': '/ui/dashboard'},
        follow_redirects=False,
    )


FERNET_KEY = Fernet.generate_key().decode()


def _setup_env(monkeypatch, tmp_path):
    _prepare_data(tmp_path)
    monkeypatch.setenv('FRYA_DATABASE_URL', 'memory://db')
    monkeypatch.setenv('FRYA_REDIS_URL', 'memory://redis')
    monkeypatch.setenv('FRYA_DATA_DIR', str(tmp_path))
    monkeypatch.setenv('FRYA_RULES_DIR', str(tmp_path / 'rules'))
    monkeypatch.setenv('FRYA_VERFAHRENSDOKU_DIR', str(tmp_path / 'verfahrensdoku'))
    monkeypatch.setenv('FRYA_PAPERLESS_BASE_URL', 'http://paperless')
    monkeypatch.setenv('FRYA_AKAUNTING_BASE_URL', 'http://akaunting')
    monkeypatch.setenv('FRYA_AUTH_USERS_JSON', _build_users_json())
    monkeypatch.setenv('FRYA_AUTH_SESSION_SECRET', 'test-session-secret-32-bytes-xx')
    monkeypatch.setenv('FRYA_AUTH_COOKIE_SECURE', 'false')
    monkeypatch.setenv('FRYA_N8N_BASE_URL', 'http://n8n')
    monkeypatch.setenv('FRYA_CONFIG_ENCRYPTION_KEY', FERNET_KEY)


def _get_admin_client(monkeypatch, tmp_path):
    _setup_env(monkeypatch, tmp_path)
    app = _build_app()
    client = TestClient(app)
    _login(client, 'admin', 'admin-pass')
    return client


# ---------- Encryption round-trip ----------

def test_encryption_roundtrip():
    from app.llm_config import decrypt_api_key, encrypt_api_key

    key = FERNET_KEY
    plaintext = 'sk-test-key-1234567890'
    encrypted = encrypt_api_key(plaintext, key)
    assert encrypted is not None
    assert encrypted != plaintext
    decrypted = decrypt_api_key(encrypted, key)
    assert decrypted == plaintext


def test_encryption_wrong_key():
    from app.llm_config import decrypt_api_key, encrypt_api_key

    key1 = FERNET_KEY
    key2 = Fernet.generate_key().decode()
    encrypted = encrypt_api_key('secret', key1)
    result = decrypt_api_key(encrypted, key2)
    assert result is None


def test_encryption_empty():
    from app.llm_config import decrypt_api_key, encrypt_api_key

    assert encrypt_api_key('', FERNET_KEY) is None
    assert decrypt_api_key(None, FERNET_KEY) is None
    assert decrypt_api_key('', FERNET_KEY) is None


# ---------- GET never returns api_key ----------

def test_get_configs_never_returns_api_key(monkeypatch, tmp_path):
    client = _get_admin_client(monkeypatch, tmp_path)

    # Get CSRF token from agent-config page
    page = client.get('/agent-config')
    assert page.status_code == 200
    csrf = _extract_csrf_token(page.text)

    # Save a config with an API key
    resp = client.post(
        '/api/agent-config/orchestrator',
        json={'provider': 'openai', 'model': 'gpt-4o-mini', 'api_key': 'sk-secret-key'},
        headers={'X-Frya-Csrf-Token': csrf},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data['api_key_set'] is True
    assert 'api_key' not in data
    assert 'api_key_encrypted' not in data

    # GET list should also not return api_key
    resp = client.get('/api/agent-config')
    assert resp.status_code == 200
    for config in resp.json():
        assert 'api_key' not in config
        assert 'api_key_encrypted' not in config
        if config['agent_id'] == 'orchestrator':
            assert config['api_key_set'] is True


# ---------- Health check writes last_health_status ----------

def test_health_check_writes_status(monkeypatch, tmp_path):
    client = _get_admin_client(monkeypatch, tmp_path)

    page = client.get('/agent-config')
    csrf = _extract_csrf_token(page.text)

    # Save config first
    client.post(
        '/api/agent-config/communicator',
        json={'provider': 'openai', 'model': 'gpt-4o-mini', 'api_key': 'sk-fake'},
        headers={'X-Frya-Csrf-Token': csrf},
    )

    # Health check will fail (no real API key) but should still write status
    resp = client.post(
        '/api/agent-config/communicator/check',
        headers={'X-Frya-Csrf-Token': csrf},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert 'status' in data
    assert data['agent_id'] == 'communicator'

    # Verify status was persisted
    resp = client.get('/api/agent-config')
    configs = resp.json()
    comm_cfg = [c for c in configs if c['agent_id'] == 'communicator'][0]
    assert comm_cfg['last_health_status'] is not None


# ---------- ENV fallback ----------

def test_env_fallback_when_no_db_entry(monkeypatch, tmp_path):
    _setup_env(monkeypatch, tmp_path)
    monkeypatch.setenv('FRYA_LLM_MODEL', 'openai/gpt-4o-mini')

    from app.llm_config import LLMConfigRepository

    repo = LLMConfigRepository('memory://db', 'memory://redis', FERNET_KEY)

    import asyncio
    config = asyncio.get_event_loop().run_until_complete(
        repo.get_config_or_fallback('orchestrator')
    )
    assert config['agent_id'] == 'orchestrator'
    assert config.get('_from_env') is True
    assert config['model'] == 'openai/gpt-4o-mini'


# ---------- Auth blocks unauthenticated ----------

def test_unauthenticated_blocked(monkeypatch, tmp_path):
    _setup_env(monkeypatch, tmp_path)
    app = _build_app()
    client = TestClient(app)

    # API endpoint should return 401
    resp = client.get('/api/agent-config')
    assert resp.status_code == 401

    # UI page should also return 401 (not under /ui prefix, so no redirect)
    resp = client.get('/agent-config', follow_redirects=False)
    assert resp.status_code == 401


# ---------- Save requires provider + model ----------

def test_save_requires_provider_and_model(monkeypatch, tmp_path):
    client = _get_admin_client(monkeypatch, tmp_path)
    page = client.get('/agent-config')
    csrf = _extract_csrf_token(page.text)

    resp = client.post(
        '/api/agent-config/orchestrator',
        json={'provider': '', 'model': ''},
        headers={'X-Frya-Csrf-Token': csrf},
    )
    assert resp.status_code == 422


# ---------- Unknown agent rejected ----------

def test_unknown_agent_rejected(monkeypatch, tmp_path):
    client = _get_admin_client(monkeypatch, tmp_path)
    page = client.get('/agent-config')
    csrf = _extract_csrf_token(page.text)

    resp = client.post(
        '/api/agent-config/nonexistent',
        json={'provider': 'openai', 'model': 'gpt-4o'},
        headers={'X-Frya-Csrf-Token': csrf},
    )
    assert resp.status_code == 400


# ---------- UI page renders all agent cards ----------

def test_ui_page_renders_agent_cards(monkeypatch, tmp_path):
    client = _get_admin_client(monkeypatch, tmp_path)
    page = client.get('/agent-config')
    assert page.status_code == 200
    # All 8 agents must appear
    for agent_id in [
        'orchestrator', 'communicator', 'document_analyst',
        'document_analyst_semantic', 'accounting_analyst',
        'deadline_analyst', 'risk_consistency', 'memory_curator',
    ]:
        assert agent_id in page.text, f'Agent "{agent_id}" nicht im HTML'
    # Planned badge must appear for at least one planned agent
    assert 'Geplant' in page.text


# ---------- Planned agents cannot be saved ----------

def test_planned_agent_cannot_be_saved(monkeypatch, tmp_path):
    client = _get_admin_client(monkeypatch, tmp_path)
    page = client.get('/agent-config')
    csrf = _extract_csrf_token(page.text)

    for planned_agent in ['deadline_analyst', 'risk_consistency', 'memory_curator']:
        resp = client.post(
            f'/api/agent-config/{planned_agent}',
            json={'provider': 'ionos', 'model': 'mistralai/Mistral-Small-24B-Instruct'},
            headers={'X-Frya-Csrf-Token': csrf},
        )
        assert resp.status_code == 400, f'{planned_agent} sollte 400 zurueckgeben'
        assert 'planned' in resp.json().get('detail', '').lower()


# ---------- Planned agents cannot be health-checked ----------

def test_planned_agent_cannot_be_health_checked(monkeypatch, tmp_path):
    client = _get_admin_client(monkeypatch, tmp_path)
    page = client.get('/agent-config')
    csrf = _extract_csrf_token(page.text)

    resp = client.post(
        '/api/agent-config/risk_consistency/check',
        headers={'X-Frya-Csrf-Token': csrf},
    )
    assert resp.status_code == 400
    assert 'planned' in resp.json().get('detail', '').lower()


# ---------- Seed: all 8 agents seeded after setup ----------

def test_all_8_agents_seeded_after_setup():
    """After setup(), memory store contains all 8 agents with correct statuses."""
    import asyncio
    from app.llm_config import LLMConfigRepository

    repo = LLMConfigRepository('memory://db', 'memory://redis')
    asyncio.run(repo.setup())

    configs = asyncio.run(repo.get_all_configs())
    agent_ids = {c['agent_id'] for c in configs}

    expected = {
        'orchestrator', 'communicator', 'document_analyst',
        'document_analyst_semantic', 'accounting_analyst',
        'deadline_analyst', 'risk_consistency', 'memory_curator',
    }
    assert expected == agent_ids, f'Fehlende Agenten: {expected - agent_ids}'

    by_id = {c['agent_id']: c for c in configs}

    # Planned agents (accounting_analyst ist jetzt active — Paket 22 Accounting Analyst)
    for planned in ('deadline_analyst', 'risk_consistency', 'memory_curator'):
        assert by_id[planned]['agent_status'] == 'planned', f'{planned} sollte planned sein'

    # Active agents
    for active in ('orchestrator', 'communicator', 'document_analyst', 'document_analyst_semantic', 'accounting_analyst'):
        assert by_id[active]['agent_status'] == 'active', f'{active} sollte active sein'

    # Idempotent: second setup() call does not duplicate entries
    asyncio.run(repo.setup())
    configs2 = asyncio.run(repo.get_all_configs())
    assert len(configs2) == len(configs)


# ---------- CSRF required for POST ----------

def test_csrf_required_for_post(monkeypatch, tmp_path):
    client = _get_admin_client(monkeypatch, tmp_path)
    resp = client.post(
        '/api/agent-config/orchestrator',
        json={'provider': 'openai', 'model': 'gpt-4o'},
    )
    assert resp.status_code == 403


# ---------- Orchestrator uses DB model ----------

class _MockLLMConfigRepo:
    def __init__(self, model: str = '', provider: str = '', base_url: str | None = None):
        self._config = {
            'agent_id': 'orchestrator',
            'model': model,
            'provider': provider,
            'api_key_encrypted': None,
            'base_url': base_url,
        }

    async def get_config_or_fallback(self, agent_id: str) -> dict:
        c = dict(self._config)
        c['agent_id'] = agent_id
        return c

    def decrypt_key_for_call(self, config: dict) -> str | None:
        return None


def _make_llm_response(content: str) -> MagicMock:
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = content
    resp.model = 'test-model'
    return resp


def _run(coro):
    return asyncio.run(coro)


def test_orchestrator_uses_db_model():
    """draft_action_with_llm reads model from LLM repository, not from settings."""
    from app.orchestration.nodes import draft_action_with_llm

    mock_repo = _MockLLMConfigRepo(model='gpt-4o-mini', provider='openai')
    captured: dict = {}

    async def mock_acompletion(**kwargs):
        captured.update(kwargs)
        return _make_llm_response('{"action": "NONE", "reason": "ok", "reversible": true}')

    with patch('app.dependencies.get_llm_config_repository', return_value=mock_repo):
        with patch('app.orchestration.nodes.acompletion', new=mock_acompletion):
            state = _run(draft_action_with_llm({'message': 'Teste Aktion', 'case_id': 'c1'}))

    assert captured.get('model') == 'openai/gpt-4o-mini'
    assert state['planned_action']['action'] == 'NONE'


def test_orchestrator_env_fallback_empty_model():
    """When no model configured (neither DB nor ENV), LLM is skipped → action NONE."""
    from app.orchestration.nodes import draft_action_with_llm

    mock_repo = _MockLLMConfigRepo(model='', provider='')
    mock_acompletion = AsyncMock()

    with patch('app.dependencies.get_llm_config_repository', return_value=mock_repo):
        with patch('app.orchestration.nodes.acompletion', mock_acompletion):
            state = _run(draft_action_with_llm({'message': 'Etwas tun', 'case_id': 'c2'}))

    mock_acompletion.assert_not_awaited()
    assert state['planned_action']['action'] == 'NONE'
    assert 'No LLM model configured' in state['planned_action']['reason']


def test_orchestrator_ionos_maps_to_openai_prefix():
    """IONOS provider → litellm model string has openai/ prefix."""
    from app.orchestration.nodes import draft_action_with_llm

    mock_repo = _MockLLMConfigRepo(
        model='meta-llama/Meta-Llama-3.3-70B-Instruct',
        provider='ionos',
        base_url='https://openai.inference.de-txl.ionos.com/v1',
    )
    captured: dict = {}

    async def mock_acompletion(**kwargs):
        captured.update(kwargs)
        return _make_llm_response('{"action": "NONE", "reason": "test", "reversible": true}')

    with patch('app.dependencies.get_llm_config_repository', return_value=mock_repo):
        with patch('app.orchestration.nodes.acompletion', new=mock_acompletion):
            _run(draft_action_with_llm({'message': 'Test IONOS', 'case_id': 'c3'}))

    assert captured.get('model') == 'openai/meta-llama/Meta-Llama-3.3-70B-Instruct'
    assert captured.get('api_base') == 'https://openai.inference.de-txl.ionos.com/v1'


def test_orchestrator_llm_exception_graceful():
    """If litellm raises, planned_action is NONE with LLM unavailable reason."""
    from app.orchestration.nodes import draft_action_with_llm

    mock_repo = _MockLLMConfigRepo(model='gpt-4o', provider='openai')

    async def fail(**kwargs):
        raise RuntimeError('connection refused')

    with patch('app.dependencies.get_llm_config_repository', return_value=mock_repo):
        with patch('app.orchestration.nodes.acompletion', new=fail):
            state = _run(draft_action_with_llm({'message': 'Test', 'case_id': 'c4'}))

    assert state['planned_action']['action'] == 'NONE'
    assert 'LLM unavailable' in state['planned_action']['reason']


# ---------- Document analyst stores model from repo ----------

def test_document_analyst_config_loaded(monkeypatch, tmp_path):
    """run_document_analyst stores model from get_config_or_fallback in state."""
    from app.orchestration.nodes import run_document_analyst

    class _DocAnalystRepo(_MockLLMConfigRepo):
        def __init__(self):
            super().__init__(model='claude-haiku-4-5', provider='anthropic')

    mock_repo = _DocAnalystRepo()

    with patch('app.dependencies.get_llm_config_repository', return_value=mock_repo):
        state = _run(run_document_analyst({
            'case_id': 'c5',
            'document_ref': 'doc-001',
            'paperless_metadata': {'title': 'Test'},
            'source': 'paperless_webhook',
        }))

    assert state.get('document_analyst_model') == 'claude-haiku-4-5'


def test_document_analyst_env_fallback(monkeypatch, tmp_path):
    """When DB has no model, document_analyst_model is None (ENV fallback stores nothing extra)."""
    from app.orchestration.nodes import run_document_analyst

    mock_repo = _MockLLMConfigRepo(model='', provider='')

    with patch('app.dependencies.get_llm_config_repository', return_value=mock_repo):
        state = _run(run_document_analyst({
            'case_id': 'c6',
            'document_ref': 'doc-002',
            'paperless_metadata': {},
            'source': 'paperless_webhook',
        }))

    # Empty model string → stored as None
    assert state.get('document_analyst_model') is None
