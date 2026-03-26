import asyncio
from datetime import datetime

from fastapi.testclient import TestClient

from app.telegram.models import TelegramClarificationRecord
from tests.test_api_surface import (
    _build_app,
    _build_users_json,
    _clear_caches,
    _extract_csrf_token,
    _login_admin,
    _prepare_data,
)


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


def _telegram_headers():
    return {'x-telegram-bot-api-secret-token': 'tg-secret'}


def _send_allowed_text(client: TestClient, update_id: int, message_id: int, text: str) -> dict:
    response = client.post(
        '/webhooks/telegram',
        json={
            'update_id': update_id,
            'message': {
                'message_id': message_id,
                'chat': {'id': 1310959044, 'type': 'private'},
                'from': {'id': 1310959044, 'username': 'maze'},
                'text': text,
            },
        },
        headers=_telegram_headers(),
    )
    assert response.status_code == 200
    return response.json()


def _get_csrf_for_case(client: TestClient, case_id: str) -> str:
    response = client.get(f'/ui/cases/{case_id}')
    assert response.status_code == 200
    return _extract_csrf_token(response.text)


def test_telegram_clarification_request_and_answer_link_to_existing_case(tmp_path, monkeypatch):
    _configure_env(monkeypatch, tmp_path)
    app = _build_app()

    with TestClient(app) as client:
        inbox_body = _send_allowed_text(client, 901, 41, 'ich brauche hilfe bei meiner rechnung')
        original_case_id = inbox_body['case_id']

        _login_admin(client)
        initial_ui = client.get(f'/ui/cases/{original_case_id}')
        assert initial_ui.status_code == 200
        assert 'Telegram Rueckfrage senden' in initial_ui.text
        csrf = _extract_csrf_token(initial_ui.text)

        clarification_request = client.post(
            f'/inspect/cases/{original_case_id}/telegram-clarification-request',
            json={'question': 'Welche Rechnungsnummer steht auf deinem Beleg?'},
            headers={'x-frya-csrf-token': csrf},
        )
        assert clarification_request.status_code == 200
        clarification_body = clarification_request.json()
        assert clarification_body['clarification_state'] == 'OPEN'
        assert clarification_body['delivery_state'] == 'FAILED'

        open_items_waiting = client.get(f'/inspect/open-items/json?case_id={original_case_id}')
        assert open_items_waiting.status_code == 200
        waiting_items = open_items_waiting.json()
        assert len(waiting_items) == 1
        assert waiting_items[0]['status'] == 'WAITING_USER'

        original_case_json = client.get(f'/inspect/cases/{original_case_id}/json')
        assert original_case_json.status_code == 200
        original_case = original_case_json.json()
        assert original_case['telegram_clarification']['question_text'] == 'Welche Rechnungsnummer steht auf deinem Beleg?'
        assert original_case['telegram_clarification']['clarification_state'] == 'OPEN'
        assert original_case['telegram_ingress']['user_visible_status']['status_code'] == 'WAITING_FOR_YOUR_REPLY'

        answer_response = client.post(
            '/webhooks/telegram',
            json={
                'update_id': 902,
                'message': {
                    'message_id': 42,
                    'chat': {'id': 1310959044, 'type': 'private'},
                    'from': {'id': 1310959044, 'username': 'maze'},
                    'text': 'Die Rechnungsnummer ist INV-4711.',
                },
            },
            headers=_telegram_headers(),
        )
        assert answer_response.status_code == 200
        answer_body = answer_response.json()
        assert answer_body['routing_status'] == 'CLARIFICATION_ANSWER_ACCEPTED'
        assert answer_body['linked_case_id'] == original_case_id
        assert answer_body['clarification_ref'] == clarification_body['clarification_ref']

        original_case_after = client.get(f'/inspect/cases/{original_case_id}/json')
        assert original_case_after.status_code == 200
        original_after_body = original_case_after.json()
        assert original_after_body['telegram_clarification']['clarification_state'] == 'ANSWER_RECEIVED'
        assert original_after_body['telegram_clarification']['answer_text'] == 'Die Rechnungsnummer ist INV-4711.'
        assert original_after_body['telegram_ingress']['user_visible_status']['status_code'] == 'REPLY_RECEIVED'

        open_items_after = client.get(f'/inspect/open-items/json?case_id={original_case_id}')
        assert open_items_after.status_code == 200
        answered_items = open_items_after.json()
        assert len(answered_items) == 1
        assert answered_items[0]['status'] == 'WAITING_DATA'

        original_actions = [entry['action'] for entry in original_after_body['chronology']]
        assert 'TELEGRAM_CLARIFICATION_REQUESTED' in original_actions
        assert 'TELEGRAM_CLARIFICATION_DELIVERY' in original_actions
        assert 'TELEGRAM_CLARIFICATION_ANSWER_ACCEPTED' in original_actions

        status_body = _send_allowed_text(client, 903, 43, '/status')
        assert status_body['intent'] == 'status.overview'
        assert status_body['linked_case_id'] == original_case_id
        assert status_body['user_visible_status']['status_code'] == 'REPLY_RECEIVED'

        final_ui = client.get(f'/ui/cases/{original_case_id}')
        assert final_ui.status_code == 200
        assert 'Telegram Rueckfrage' in final_ui.text
        assert 'Die Rechnungsnummer ist INV-4711.' in final_ui.text
        assert 'Antwort erhalten' in final_ui.text
        assert 'Telegram Rueckfrage senden' not in final_ui.text

        second_request = client.post(
            f'/inspect/cases/{original_case_id}/telegram-clarification-request',
            json={'question': 'Noch eine Frage'},
            headers={'x-frya-csrf-token': csrf},
        )
        assert second_request.status_code == 409


def test_telegram_reply_without_open_clarification_is_rejected_safely(tmp_path, monkeypatch):
    _configure_env(monkeypatch, tmp_path)
    app = _build_app()

    with TestClient(app) as client:
        response = client.post(
            '/webhooks/telegram',
            json={
                'update_id': 911,
                'message': {
                    'message_id': 51,
                    'reply_to_message': {'message_id': 999},
                    'chat': {'id': 1310959044, 'type': 'private'},
                    'from': {'id': 1310959044, 'username': 'maze'},
                    'text': 'Antwort ohne offene Rueckfrage',
                },
            },
            headers=_telegram_headers(),
        )
        assert response.status_code == 200
        body = response.json()
        assert body['routing_status'] == 'CLARIFICATION_NOT_OPEN'

        _login_admin(client)
        case_json = client.get(f"/inspect/cases/{body['case_id']}/json")
        assert case_json.status_code == 200
        case_body = case_json.json()
        assert case_body['telegram_ingress']['routing_status'] == 'CLARIFICATION_NOT_OPEN'
        assert case_body['telegram_ingress']['user_visible_status']['status_code'] == 'NOT_AVAILABLE'
        assert case_body['telegram_clarification'] is None


def test_telegram_clarification_answer_becomes_ambiguous_with_multiple_open_threads(tmp_path, monkeypatch):
    _configure_env(monkeypatch, tmp_path)
    app = _build_app()

    with TestClient(app) as client:
        case_one = _send_allowed_text(client, 921, 61, 'erster fall fuer rueckfrage')
        case_two = _send_allowed_text(client, 922, 62, 'zweiter fall fuer rueckfrage')

        _login_admin(client)
        from app.dependencies import get_telegram_case_link_service, get_telegram_clarification_repository

        case_link_service = get_telegram_case_link_service()
        clarification_repository = get_telegram_clarification_repository()

        link_one = asyncio.run(case_link_service.get_by_case(case_one['case_id']))
        link_two = asyncio.run(case_link_service.get_by_case(case_two['case_id']))
        assert link_one is not None
        assert link_two is not None

        now = datetime.utcnow()
        asyncio.run(
            clarification_repository.upsert(
                TelegramClarificationRecord(
                    clarification_ref='clar-1',
                    linked_case_id=case_one['case_id'],
                    telegram_thread_ref=link_one.telegram_thread_ref,
                    telegram_chat_ref=link_one.telegram_chat_ref,
                    telegram_case_ref=link_one.case_id,
                    telegram_case_link_id=link_one.link_id,
                    open_item_id=case_one['open_item_id'],
                    open_item_title=link_one.open_item_title,
                    asked_by='admin',
                    question_text='Frage 1',
                    clarification_state='OPEN',
                    expected_reply_state='WAITING_FOR_REPLY',
                    delivery_state='SENT',
                    outgoing_message_id=701,
                    outgoing_message_ref='tg-message:701',
                    created_at=now,
                    updated_at=now,
                )
            )
        )
        asyncio.run(
            clarification_repository.upsert(
                TelegramClarificationRecord(
                    clarification_ref='clar-2',
                    linked_case_id=case_two['case_id'],
                    telegram_thread_ref=link_two.telegram_thread_ref,
                    telegram_chat_ref=link_two.telegram_chat_ref,
                    telegram_case_ref=link_two.case_id,
                    telegram_case_link_id=link_two.link_id,
                    open_item_id=case_two['open_item_id'],
                    open_item_title=link_two.open_item_title,
                    asked_by='admin',
                    question_text='Frage 2',
                    clarification_state='OPEN',
                    expected_reply_state='WAITING_FOR_REPLY',
                    delivery_state='SENT',
                    outgoing_message_id=702,
                    outgoing_message_ref='tg-message:702',
                    created_at=now,
                    updated_at=now,
                )
            )
        )

        answer = client.post(
            '/webhooks/telegram',
            json={
                'update_id': 923,
                'message': {
                    'message_id': 63,
                    'chat': {'id': 1310959044, 'type': 'private'},
                    'from': {'id': 1310959044, 'username': 'maze'},
                    'text': 'Diese Antwort ist mehrdeutig.',
                },
            },
            headers=_telegram_headers(),
        )
        assert answer.status_code == 200
        answer_body = answer.json()
        assert answer_body['routing_status'] == 'CLARIFICATION_ANSWER_AMBIGUOUS'

        case_json = client.get(f"/inspect/cases/{answer_body['case_id']}/json")
        assert case_json.status_code == 200
        case_body = case_json.json()
        assert case_body['telegram_ingress']['user_visible_status']['status_code'] == 'UNDER_REVIEW'
        assert case_body['telegram_clarification'] is None

        actions = [entry['action'] for entry in case_body['chronology']]
        assert 'TELEGRAM_CLARIFICATION_ANSWER_AMBIGUOUS' in actions
