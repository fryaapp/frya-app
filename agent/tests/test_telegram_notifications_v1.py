import json

from fastapi.testclient import TestClient

from app.connectors.notifications_telegram import TelegramConnector
from tests.test_api_surface import _build_app, _extract_csrf_token, _login_admin
from tests.test_telegram_clarification_v1 import _configure_env, _send_allowed_text
from tests.test_telegram_internal_followup_resolution_v1 import _reach_internal_followup_required


def test_telegram_internal_followup_notifications_are_sent_and_visible(tmp_path, monkeypatch):
    _configure_env(monkeypatch, tmp_path)
    monkeypatch.setenv('FRYA_TELEGRAM_BOT_TOKEN', 'telegram-test-token')

    sent_messages: list[str] = []

    async def fake_send(self, message, disable_notification: bool = False):
        sent_messages.append(message.text)
        message_id = 700 + len(sent_messages)
        return {
            'ok': True,
            'status_code': 200,
            'body': json.dumps({'ok': True, 'result': {'message_id': message_id}}),
            'json': {'ok': True, 'result': {'message_id': message_id}},
        }

    monkeypatch.setattr(TelegramConnector, 'send', fake_send)

    app = _build_app()

    with TestClient(app) as client:
        inbox = _send_allowed_text(client, 5101, 511, 'bitte nachbearbeiten')
        case_id = inbox['case_id']

        _login_admin(client)
        ui_before = client.get(f'/ui/cases/{case_id}')
        assert ui_before.status_code == 200
        csrf = _extract_csrf_token(ui_before.text)

        _reach_internal_followup_required(client, case_id, csrf)

        under_review = client.post(
            f'/inspect/cases/{case_id}/telegram-internal-followup-under-review',
            json={'note': 'Interne Nachbearbeitung wurde uebernommen.'},
            headers={'x-frya-csrf-token': csrf},
        )
        assert under_review.status_code == 200

        completed = client.post(
            f'/inspect/cases/{case_id}/telegram-internal-followup-resolution',
            json={'decision': 'COMPLETED', 'note': 'Intern abgeschlossen, keine weitere Telegram-Aktion.'},
            headers={'x-frya-csrf-token': csrf},
        )
        assert completed.status_code == 200

        assert any('Es ist keine weitere Antwort in Telegram noetig.' in text for text in sent_messages)
        assert any('Der Telegram-Klaerpunkt ist abgeschlossen.' in text for text in sent_messages)

        case_json = client.get(f'/inspect/cases/{case_id}/json')
        assert case_json.status_code == 200
        body = case_json.json()
        notification = body['telegram_notification']
        assert notification['notification_type'] == 'INTERNAL_FOLLOWUP_COMPLETED'
        assert notification['delivery_state'] == 'SENT'
        actions = [entry['action'] for entry in body['chronology']]
        assert 'TELEGRAM_NOTIFICATION_SENT' in actions

        ui_after = client.get(f'/ui/cases/{case_id}')
        assert ui_after.status_code == 200
        assert 'Telegram Notification' in ui_after.text
        assert 'INTERNAL_FOLLOWUP_COMPLETED' in ui_after.text
