import importlib
import json
import re
from pathlib import Path
from urllib.parse import quote

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


def _login_admin(client: TestClient):
    res = client.post(
        '/auth/login',
        data={'username': 'admin', 'password': 'admin-pass', 'next': '/ui/dashboard'},
        follow_redirects=False,
    )
    assert res.status_code == 303


def test_api_surface(tmp_path, monkeypatch):
    _prepare_data(tmp_path)

    monkeypatch.setenv('FRYA_DATABASE_URL', 'memory://db')
    monkeypatch.setenv('FRYA_REDIS_URL', 'memory://redis')
    monkeypatch.setenv('FRYA_DATA_DIR', str(tmp_path))
    monkeypatch.setenv('FRYA_RULES_DIR', str(tmp_path / 'rules'))
    monkeypatch.setenv('FRYA_VERFAHRENSDOKU_DIR', str(tmp_path / 'verfahrensdoku'))
    monkeypatch.setenv('FRYA_PAPERLESS_BASE_URL', 'http://paperless')
    monkeypatch.setenv('FRYA_AKAUNTING_BASE_URL', 'http://akaunting')
    monkeypatch.setenv('FRYA_N8N_BASE_URL', 'http://n8n')
    monkeypatch.setenv('FRYA_TELEGRAM_WEBHOOK_SECRET', 'tg-secret')
    monkeypatch.setenv('FRYA_TELEGRAM_ALLOWED_CHAT_IDS', '-5200036710')
    monkeypatch.setenv('FRYA_TELEGRAM_ALLOWED_DIRECT_CHAT_IDS', '1310959044')
    monkeypatch.setenv('FRYA_TELEGRAM_ALLOWED_USER_IDS', '1310959044')
    monkeypatch.setenv('FRYA_AUTH_USERS_JSON', _build_users_json())
    monkeypatch.setenv('FRYA_AUTH_SESSION_SECRET', 'test-secret')
    monkeypatch.setenv('FRYA_AUTH_COOKIE_SECURE', 'false')

    app = _build_app()

    with TestClient(app) as client:
        assert client.get('/health').status_code == 200
        assert client.get('/status').status_code == 401

        anon_ui = client.get('/ui/dashboard', follow_redirects=False)
        assert anon_ui.status_code == 303
        assert '/auth/login' in anon_ui.headers['location']

        tg_payload = {
            'update_id': 111,
            'message': {
                'message_id': 7,
                'chat': {'id': -5200036710, 'type': 'group'},
                'from': {'id': 1310959044, 'username': 'maze'},
                'text': 'status',
            },
        }
        tg = client.post('/webhooks/telegram', json=tg_payload, headers={'x-telegram-bot-api-secret-token': 'tg-secret'})
        assert tg.status_code == 200
        tg_body = tg.json()
        assert tg_body['status'] == 'accepted'
        assert tg_body['intent'] == 'status.overview'
        tg_case_id = tg_body['case_id']

        tg_dup = client.post('/webhooks/telegram', json=tg_payload, headers={'x-telegram-bot-api-secret-token': 'tg-secret'})
        assert tg_dup.status_code == 200
        tg_dup_body = tg_dup.json()
        assert tg_dup_body['status'] == 'duplicate_ignored'

        tg_inbox_payload = {
            'update_id': 113,
            'message': {
                'message_id': 9,
                'chat': {'id': -5200036710, 'type': 'group'},
                'from': {'id': 1310959044, 'username': 'maze'},
                'text': 'bitte pruefe die rueckfrage aus telegram',
            },
        }
        tg_inbox = client.post('/webhooks/telegram', json=tg_inbox_payload, headers={'x-telegram-bot-api-secret-token': 'tg-secret'})
        assert tg_inbox.status_code == 200
        tg_inbox_body = tg_inbox.json()
        assert tg_inbox_body['status'] == 'accepted'
        assert tg_inbox_body['routing_status'] == 'ACCEPTED_TO_INBOX'
        assert tg_inbox_body['open_item_id']
        tg_inbox_case_id = tg_inbox_body['case_id']

        denied_payload = {
            'update_id': 112,
            'message': {
                'message_id': 8,
                'chat': {'id': -123456, 'type': 'group'},
                'from': {'id': 1310959044, 'username': 'maze'},
                'text': 'status',
            },
        }
        denied = client.post('/webhooks/telegram', json=denied_payload, headers={'x-telegram-bot-api-secret-token': 'tg-secret'})
        assert denied.status_code == 200
        denied_body = denied.json()
        assert denied_body['status'] == 'denied'
        denied_case = denied_body['case_id']

        secret_payload = {
            'update_id': 114,
            'message': {
                'message_id': 10,
                'chat': {'id': -5200036710, 'type': 'group'},
                'from': {'id': 1310959044, 'username': 'maze'},
                'text': 'status',
            },
        }
        secret_denied = client.post('/webhooks/telegram', json=secret_payload, headers={'x-telegram-bot-api-secret-token': 'wrong'})
        assert secret_denied.status_code == 200
        secret_denied_body = secret_denied.json()
        assert secret_denied_body['status'] == 'denied'

        _login_admin(client)

        rule_detail = client.get('/ui/rules/runtime_rules.yaml')
        assert rule_detail.status_code == 200
        csrf = _extract_csrf_token(rule_detail.text)

        assert client.get('/status').status_code == 200
        assert client.get('/inspect/rules').status_code == 200
        assert client.get('/inspect/verfahrensdoku').status_code == 200
        assert client.get('/inspect/open-items').status_code == 200

        run = client.post(
            '/agent/run',
            json={'case_id': 'case-api-1', 'message': 'Bitte Rechnung pruefen'},
            headers={'x-frya-csrf-token': csrf},
        )
        assert run.status_code == 200
        assert run.json()['status'] == 'ok'

        case_json = client.get('/inspect/cases/case-api-1/json')
        assert case_json.status_code == 200
        body = case_json.json()
        assert body['case_id'] == 'case-api-1'
        assert isinstance(body['chronology'], list)

        blocked_rule_update = client.put(
            '/inspect/rules/runtime_rules.yaml',
            json={'content': 'version: 2\nname: runtime\n', 'reason': 'test'},
            headers={'x-frya-csrf-token': csrf},
        )
        assert blocked_rule_update.status_code == 409
        blocked_detail = blocked_rule_update.json()['detail']
        assert blocked_detail['status'] == 'WAITING_APPROVAL'
        approval_id = blocked_detail['approval_id']

        approvals_json = client.get('/inspect/approvals/json?case_id=rule:runtime_rules.yaml')
        assert approvals_json.status_code == 200
        approvals = approvals_json.json()
        assert any(x['approval_id'] == approval_id and x['status'] == 'PENDING' for x in approvals)

        rule_detail_with_approval = client.get(f'/ui/rules/runtime_rules.yaml?approval_id={approval_id}')
        assert rule_detail_with_approval.status_code == 200
        assert 'Freigabe-Status' in rule_detail_with_approval.text
        assert approval_id in rule_detail_with_approval.text

        approve = client.post(
            f'/inspect/approvals/{approval_id}/decision',
            json={'decision': 'APPROVED', 'reason': 'ok'},
            headers={'x-frya-csrf-token': csrf},
        )
        assert approve.status_code == 200
        assert approve.json()['new_status'] == 'APPROVED'

        update_rule = client.put(
            '/inspect/rules/runtime_rules.yaml',
            json={'content': 'version: 2\nname: runtime\n', 'reason': 'test', 'approval_id': approval_id},
            headers={'x-frya-csrf-token': csrf},
        )
        assert update_rule.status_code == 200

        blocked_policy_update = client.put(
            '/inspect/rules/policies/runtime_policy.md',
            json={'content': 'Version: 2.0\n', 'reason': 'slash-case-test'},
            headers={'x-frya-csrf-token': csrf},
        )
        assert blocked_policy_update.status_code == 409
        blocked_policy_detail = blocked_policy_update.json()['detail']
        slash_approval_id = blocked_policy_detail['approval_id']
        slash_case_id = 'rule:policies/runtime_policy.md'
        slash_case_path = quote(slash_case_id, safe='')

        slash_approve = client.post(
            f'/inspect/approvals/{slash_approval_id}/decision',
            json={'decision': 'APPROVED', 'reason': 'ok'},
            headers={'x-frya-csrf-token': csrf},
        )
        assert slash_approve.status_code == 200

        slash_update = client.put(
            '/inspect/rules/policies/runtime_policy.md',
            json={'content': 'Version: 2.0\n', 'reason': 'slash-case-test', 'approval_id': slash_approval_id},
            headers={'x-frya-csrf-token': csrf},
        )
        assert slash_update.status_code == 200

        rule_case = client.get('/inspect/cases/rule:runtime_rules.yaml/json')
        assert rule_case.status_code == 200
        rule_case_body = rule_case.json()
        assert rule_case_body['latest_gate_summary'] is not None or len(rule_case_body['approvals']) >= 1

        slash_rule_case = client.get(f'/inspect/cases/{slash_case_path}/json')
        assert slash_rule_case.status_code == 200
        slash_rule_case_body = slash_rule_case.json()
        assert slash_rule_case_body['case_id'] == slash_case_id
        assert any(x['approval_id'] == slash_approval_id for x in slash_rule_case_body['approvals'])

        ui_cases = client.get('/ui/cases')
        assert ui_cases.status_code == 200
        assert f'/ui/cases/{slash_case_path}' in ui_cases.text

        ui_slash_case = client.get(f'/ui/cases/{slash_case_path}')
        assert ui_slash_case.status_code == 200
        assert slash_case_id in ui_slash_case.text

        rule_audit = client.get('/inspect/rules/audit/json')
        assert rule_audit.status_code == 200
        assert len(rule_audit.json()) >= 1

        tg_case_json = client.get(f'/inspect/cases/{tg_case_id}/json')
        assert tg_case_json.status_code == 200
        tg_case_body = tg_case_json.json()
        actions = [x['action'] for x in tg_case_body['chronology']]
        assert actions.count('TELEGRAM_WEBHOOK_RECEIVED') >= 2
        assert actions.count('TELEGRAM_INTENT_RECOGNIZED') == 1
        assert actions.count('TELEGRAM_ROUTED') == 1
        assert actions.count('TELEGRAM_REPLY_ATTEMPTED') == 1
        assert 'TELEGRAM_DUPLICATE_IGNORED' in actions
        assert tg_case_body['telegram_ingress']['routing_status'] == 'STATUS_REQUEST'
        assert tg_case_body['telegram_ingress']['authorization_status'] == 'AUTHORIZED'
        assert tg_case_body['telegram_case_link']['track_for_status'] is False
        assert tg_case_body['telegram_ingress']['user_visible_status']['status_code'] == 'NOT_AVAILABLE'

        denied_case_json = client.get(f'/inspect/cases/{denied_case}/json')
        assert denied_case_json.status_code == 200
        denied_case_body = denied_case_json.json()
        denied_actions = [x['action'] for x in denied_case_body['chronology']]
        assert 'TELEGRAM_WEBHOOK_RECEIVED' in denied_actions
        assert 'TELEGRAM_AUTH_DENIED' in denied_actions
        assert 'TELEGRAM_REPLY_ATTEMPTED' in denied_actions
        assert denied_case_body['telegram_ingress']['routing_status'] == 'REJECTED_UNAUTHORIZED'

        secret_case_json = client.get(f"/inspect/cases/{secret_denied_body['case_id']}/json")
        assert secret_case_json.status_code == 200
        assert secret_case_json.json()['telegram_ingress']['routing_status'] == 'REJECTED_SECRET'

        tg_inbox_case_json = client.get(f'/inspect/cases/{tg_inbox_case_id}/json')
        assert tg_inbox_case_json.status_code == 200
        tg_inbox_case_body = tg_inbox_case_json.json()
        assert tg_inbox_case_body['telegram_ingress']['routing_status'] == 'ACCEPTED_TO_INBOX'
        assert tg_inbox_case_body['telegram_ingress']['open_item_id'] == tg_inbox_body['open_item_id']
        assert tg_inbox_case_body['telegram_case_link']['track_for_status'] is True
        assert tg_inbox_case_body['telegram_ingress']['user_visible_status']['status_code'] == 'IN_QUEUE'

        tg_ui = client.get(f'/ui/cases/{tg_case_id}')
        assert tg_ui.status_code == 200
        assert 'Telegram Ingress' in tg_ui.text
        assert 'STATUS_REQUEST' in tg_ui.text

        tg_inbox_ui = client.get(f'/ui/cases/{tg_inbox_case_id}')
        assert tg_inbox_ui.status_code == 200
        assert 'Telegram Ingress' in tg_inbox_ui.text
        assert 'ACCEPTED_TO_INBOX' in tg_inbox_ui.text

        assert client.get('/inspect/audit').status_code == 200

        assert client.get('/ui').status_code in (200, 303)
        assert client.get('/ui/dashboard').status_code == 200
        assert client.get('/ui/cases').status_code == 200
        assert client.get('/ui/cases/case-api-1').status_code == 200
        assert client.get('/ui/open-items').status_code == 200
        assert client.get('/ui/problem-cases').status_code == 200
        assert client.get('/ui/rules').status_code == 200
        assert client.get('/ui/rules/runtime_rules.yaml').status_code == 200
        assert client.get('/ui/rules/audit').status_code == 200
        assert client.get('/ui/verfahrensdoku').status_code == 200
        assert client.get('/ui/system').status_code == 200


