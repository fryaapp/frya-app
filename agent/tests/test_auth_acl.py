import importlib
import json
import re
from pathlib import Path

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

    return json.dumps(
        [
            {
                'username': 'operator',
                'role': 'operator',
                'password_hash': hash_password_pbkdf2('operator-pass'),
            },
            {
                'username': 'admin',
                'role': 'admin',
                'password_hash': hash_password_pbkdf2('admin-pass'),
            },
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


def _login(client: TestClient, username: str, password: str, next_target: str = '/ui/dashboard'):
    return client.post(
        '/auth/login',
        data={'username': username, 'password': password, 'next': next_target},
        follow_redirects=False,
    )


def test_auth_acl_minimal_flow(tmp_path, monkeypatch):
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

    app = _build_app()

    with TestClient(app) as client:
        anon_ui = client.get('/ui/dashboard', follow_redirects=False)
        assert anon_ui.status_code == 303
        assert '/auth/login' in anon_ui.headers['location']

        anon_api = client.get('/inspect/rules/load-status/json')
        assert anon_api.status_code == 401
        assert anon_api.json()['detail'] == 'not_authenticated'

        bad_login = _login(client, 'operator', 'wrong-pass')
        assert bad_login.status_code == 401

        op_login = _login(client, 'operator', 'operator-pass')
        assert op_login.status_code == 303

        assert client.get('/ui/dashboard').status_code == 200
        assert client.get('/inspect/rules/load-status/json').status_code == 200

        rule_page = client.get('/ui/rules/runtime_rules.yaml')
        assert rule_page.status_code == 200
        operator_csrf = _extract_csrf_token(rule_page.text)

        op_write = client.put(
            '/inspect/rules/runtime_rules.yaml',
            json={'content': 'version: 2\nname: runtime\n', 'reason': 'operator-write'},
            headers={'x-frya-csrf-token': operator_csrf},
        )
        assert op_write.status_code == 403
        assert op_write.json()['detail'] == 'forbidden'

        op_run = client.post(
            '/agent/run',
            json={'case_id': 'acl-op-run', 'message': 'test'},
            headers={'x-frya-csrf-token': operator_csrf},
        )
        assert op_run.status_code == 403

        op_logout = client.post('/auth/logout', data={'csrf_token': operator_csrf}, follow_redirects=False)
        assert op_logout.status_code == 303

        admin_login = _login(client, 'admin', 'admin-pass')
        assert admin_login.status_code == 303

        admin_rule_page = client.get('/ui/rules/runtime_rules.yaml')
        assert admin_rule_page.status_code == 200
        admin_csrf = _extract_csrf_token(admin_rule_page.text)

        admin_write = client.put(
            '/inspect/rules/runtime_rules.yaml',
            json={'content': 'version: 3\nname: runtime\n', 'reason': 'admin-write'},
            headers={'x-frya-csrf-token': admin_csrf},
        )
        assert admin_write.status_code == 409
        approval_id = admin_write.json()['detail']['approval_id']

        approve = client.post(
            f'/inspect/approvals/{approval_id}/decision',
            json={'decision': 'APPROVED', 'reason': 'acl-approve'},
            headers={'x-frya-csrf-token': admin_csrf},
        )
        assert approve.status_code == 200

        admin_write_after_approval = client.put(
            '/inspect/rules/runtime_rules.yaml',
            json={'content': 'version: 3\nname: runtime\n', 'reason': 'admin-write', 'approval_id': approval_id},
            headers={'x-frya-csrf-token': admin_csrf},
        )
        assert admin_write_after_approval.status_code == 200

        bad_csrf = client.put(
            '/inspect/rules/runtime_rules.yaml',
            json={'content': 'version: 4\nname: runtime\n', 'reason': 'bad-csrf'},
            headers={'x-frya-csrf-token': 'wrong-token'},
        )
        assert bad_csrf.status_code == 403

        admin_run = client.post(
            '/agent/run',
            json={'case_id': 'acl-admin-run', 'message': 'Bitte pruefen'},
            headers={'x-frya-csrf-token': admin_csrf},
        )
        assert admin_run.status_code == 200

        admin_logout = client.post('/auth/logout', data={'csrf_token': admin_csrf}, follow_redirects=False)
        assert admin_logout.status_code == 303

        post_logout_ui = client.get('/ui/dashboard', follow_redirects=False)
        assert post_logout_ui.status_code == 303
        assert '/auth/login' in post_logout_ui.headers['location']
