from fastapi.testclient import TestClient

from tests.test_api_surface import _build_app, _clear_caches, _login_admin, _prepare_data, _build_users_json


def _configure_env(monkeypatch, tmp_path):
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
    _clear_caches()


def test_telegram_status_tracks_last_linked_case(tmp_path, monkeypatch):
    _configure_env(monkeypatch, tmp_path)
    app = _build_app()

    inbox_payload = {
        'update_id': 701,
        'message': {
            'message_id': 21,
            'chat': {'id': 1310959044, 'type': 'private'},
            'from': {'id': 1310959044, 'username': 'maze'},
            'text': 'bitte pruefe meinen letzten eingang',
        },
    }
    status_payload = {
        'update_id': 702,
        'message': {
            'message_id': 22,
            'chat': {'id': 1310959044, 'type': 'private'},
            'from': {'id': 1310959044, 'username': 'maze'},
            'text': '/status',
        },
    }

    with TestClient(app) as client:
        inbox = client.post('/webhooks/telegram', json=inbox_payload, headers={'x-telegram-bot-api-secret-token': 'tg-secret'})
        assert inbox.status_code == 200
        inbox_body = inbox.json()
        assert inbox_body['routing_status'] == 'ACCEPTED_TO_INBOX'

        inbox_dup = client.post('/webhooks/telegram', json=inbox_payload, headers={'x-telegram-bot-api-secret-token': 'tg-secret'})
        assert inbox_dup.status_code == 200
        assert inbox_dup.json()['status'] == 'duplicate_ignored'

        status = client.post('/webhooks/telegram', json=status_payload, headers={'x-telegram-bot-api-secret-token': 'tg-secret'})
        assert status.status_code == 200
        status_body = status.json()
        assert status_body['intent'] == 'status.overview'
        assert status_body['linked_case_id'] == inbox_body['case_id']
        assert status_body['user_visible_status']['status_code'] == 'IN_QUEUE'

        _login_admin(client)
        inbox_case_json = client.get(f"/inspect/cases/{inbox_body['case_id']}/json")
        assert inbox_case_json.status_code == 200
        inbox_case = inbox_case_json.json()
        assert inbox_case['telegram_case_link']['track_for_status'] is True
        assert inbox_case['telegram_ingress']['user_visible_status']['status_code'] == 'IN_QUEUE'
        assert inbox_case['telegram_ingress']['reply_status'] == 'SKIPPED_NO_TOKEN'

        open_items = client.get(f"/inspect/open-items/json?case_id={inbox_body['case_id']}")
        assert open_items.status_code == 200
        assert len(open_items.json()) == 1

        status_case_json = client.get(f"/inspect/cases/{status_body['case_id']}/json")
        assert status_case_json.status_code == 200
        status_case = status_case_json.json()
        assert status_case['telegram_ingress']['linked_case_id'] == inbox_body['case_id']
        assert status_case['telegram_ingress']['user_visible_status']['status_code'] == 'IN_QUEUE'

        status_ui = client.get(f"/ui/cases/{status_body['case_id']}")
        assert status_ui.status_code == 200
        assert 'Telegram Statussicht' in status_ui.text
        assert 'In operatorischer Pruefung' in status_ui.text


def test_telegram_status_without_linked_case_is_safe(tmp_path, monkeypatch):
    _configure_env(monkeypatch, tmp_path)
    app = _build_app()

    payload = {
        'update_id': 801,
        'message': {
            'message_id': 31,
            'chat': {'id': 1310959044, 'type': 'private'},
            'from': {'id': 1310959044, 'username': 'maze'},
            'text': 'status',
        },
    }

    with TestClient(app) as client:
        response = client.post('/webhooks/telegram', json=payload, headers={'x-telegram-bot-api-secret-token': 'tg-secret'})
        assert response.status_code == 200
        body = response.json()
        assert body['intent'] == 'status.overview'
        assert body['user_visible_status']['status_code'] == 'NOT_AVAILABLE'

        _login_admin(client)
        case_json = client.get(f"/inspect/cases/{body['case_id']}/json")
        assert case_json.status_code == 200
        telegram = case_json.json()['telegram_ingress']
        assert telegram['user_visible_status']['status_code'] == 'NOT_AVAILABLE'
        assert telegram['linked_case_id'] is None
