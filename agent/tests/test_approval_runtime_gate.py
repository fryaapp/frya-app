import importlib
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
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

    return json.dumps(
        [
            {
                'username': 'admin',
                'role': 'admin',
                'password_hash': hash_password_pbkdf2('admin-pass'),
            }
        ]
    )


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
    assert m, 'csrf_token nicht im HTML gefunden'
    return m.group(1)


@pytest.mark.asyncio
async def test_agent_run_does_not_bypass_required_approval(monkeypatch, tmp_path: Path):
    _prepare_data(tmp_path)

    monkeypatch.setenv('FRYA_DATABASE_URL', 'memory://db')
    monkeypatch.setenv('FRYA_REDIS_URL', 'memory://redis')
    monkeypatch.setenv('FRYA_DATA_DIR', str(tmp_path))
    monkeypatch.setenv('FRYA_RULES_DIR', str(tmp_path / 'rules'))
    monkeypatch.setenv('FRYA_VERFAHRENSDOKU_DIR', str(tmp_path / 'verfahrensdoku'))
    monkeypatch.setenv('FRYA_PAPERLESS_BASE_URL', 'http://paperless')
    monkeypatch.setenv('FRYA_AKAUNTING_BASE_URL', 'http://akaunting')
    monkeypatch.setenv('FRYA_N8N_BASE_URL', 'http://n8n')
    monkeypatch.setenv('FRYA_AUTH_USERS_JSON', _build_users_json())
    monkeypatch.setenv('FRYA_AUTH_SESSION_SECRET', 'test-secret')
    monkeypatch.setenv('FRYA_AUTH_COOKIE_SECURE', 'false')

    async def _fake_acompletion(*args, **kwargs):
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=json.dumps(
                            {
                                'action': 'booking_finalize',
                                'reason': 'critical',
                                'reversible': False,
                                'confidence': 0.95,
                            }
                        )
                    )
                )
            ]
        )

    import app.orchestration.nodes as nodes_module

    monkeypatch.setattr(nodes_module, 'acompletion', _fake_acompletion)

    app = _build_app()

    with TestClient(app) as client:
        login = client.post(
            '/auth/login',
            data={'username': 'admin', 'password': 'admin-pass', 'next': '/ui/dashboard'},
            follow_redirects=False,
        )
        assert login.status_code == 303

        rule_detail = client.get('/ui/rules/policies/runtime_policy.md')
        assert rule_detail.status_code == 200
        csrf = _extract_csrf_token(rule_detail.text)

        run = client.post(
            '/agent/run',
            json={
                'case_id': 'case-approval-bypass',
                'message': 'Bitte Buchung finalisieren',
                'approved': True,
            },
            headers={'x-frya-csrf-token': csrf},
        )
        assert run.status_code == 200
        body = run.json()['result']['output']
        assert body['status'] == 'WAITING_APPROVAL'
        assert body['approval_mode'] == 'REQUIRE_USER_APPROVAL'
        assert body.get('approval_id')
