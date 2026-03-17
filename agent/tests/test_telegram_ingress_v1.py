from fastapi.testclient import TestClient

from tests.test_api_surface import _build_app, _build_users_json, _clear_caches, _login_admin, _prepare_data


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


def test_telegram_unsupported_message_is_safe(tmp_path, monkeypatch):
    _configure_env(monkeypatch, tmp_path)
    app = _build_app()

    payload = {
        'update_id': 501,
        'message': {
            'message_id': 99,
            'chat': {'id': -5200036710, 'type': 'group'},
            'from': {'id': 1310959044, 'username': 'maze'},
            'sticker': {'file_id': 'x'},
        },
    }

    with TestClient(app) as client:
        response = client.post('/webhooks/telegram', json=payload, headers={'x-telegram-bot-api-secret-token': 'tg-secret'})
        assert response.status_code == 200
        body = response.json()
        assert body['status'] == 'ignored'
        assert body['reason'] == 'unsupported_message_type'

        _login_admin(client)
        case_json = client.get('/inspect/cases/tg--5200036710-99/json')
        assert case_json.status_code == 200
        telegram = case_json.json()['telegram_ingress']
        assert telegram['routing_status'] == 'UNSUPPORTED_MESSAGE_TYPE'
        assert telegram['authorization_status'] == 'AUTHORIZED'


def test_telegram_does_not_execute_approval_from_chat(tmp_path, monkeypatch):
    # Paket 54: 'freigeben' is now a risky substring caught by the communicator
    # guardrail. It returns a safe-limit response (COMMUNICATOR_GUARDRAIL_TRIGGERED)
    # instead of falling through to the operator inbox — a stricter, correct behavior.
    _configure_env(monkeypatch, tmp_path)
    app = _build_app()

    payload = {
        'update_id': 601,
        'message': {
            'message_id': 100,
            'chat': {'id': -5200036710, 'type': 'group'},
            'from': {'id': 1310959044, 'username': 'maze'},
            'text': 'freigeben case-abc',
        },
    }

    with TestClient(app) as client:
        response = client.post('/webhooks/telegram', json=payload, headers={'x-telegram-bot-api-secret-token': 'tg-secret'})
        assert response.status_code == 200
        body = response.json()
        assert body['status'] == 'accepted'
        # Communicator V0 guardrail intercepts 'freigeben' → safe limit response
        assert body['routing_status'] == 'COMMUNICATOR_GUARDRAIL_TRIGGERED'

        _login_admin(client)
        case_json = client.get(f"/inspect/cases/{body['case_id']}/json")
        assert case_json.status_code == 200
        telegram = case_json.json()['telegram_ingress']
        assert telegram['intent_name'] == 'communicator.unsupported_or_risky'
        # No open item created for safe-limit (track_for_status=False)
        assert telegram.get('open_item_id') is None
