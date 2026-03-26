from fastapi.testclient import TestClient

from tests.test_telegram_clarification_v1 import _configure_env, _send_allowed_text, _telegram_headers
from tests.test_api_surface import _build_app, _extract_csrf_token, _login_admin


def test_telegram_clarification_resolution_completed_updates_user_status(tmp_path, monkeypatch):
    _configure_env(monkeypatch, tmp_path)
    app = _build_app()

    with TestClient(app) as client:
        inbox = _send_allowed_text(client, 1001, 71, 'ich habe eine rueckfrage')
        case_id = inbox['case_id']

        _login_admin(client)
        ui_before = client.get(f'/ui/cases/{case_id}')
        assert ui_before.status_code == 200
        csrf = _extract_csrf_token(ui_before.text)

        requested = client.post(
            f'/inspect/cases/{case_id}/telegram-clarification-request',
            json={'question': 'Welche Rechnungsnummer steht auf deinem Beleg?'},
            headers={'x-frya-csrf-token': csrf},
        )
        assert requested.status_code == 200

        answered = client.post(
            '/webhooks/telegram',
            json={
                'update_id': 1002,
                'message': {
                    'message_id': 72,
                    'chat': {'id': 1310959044, 'type': 'private'},
                    'from': {'id': 1310959044, 'username': 'maze'},
                    'text': 'INV-8888',
                },
            },
            headers=_telegram_headers(),
        )
        assert answered.status_code == 200
        assert answered.json()['routing_status'] == 'CLARIFICATION_ANSWER_ACCEPTED'

        under_review = client.post(
            f'/inspect/cases/{case_id}/telegram-clarification-under-review',
            json={'note': 'Antwort wird operatorisch gesichtet.'},
            headers={'x-frya-csrf-token': csrf},
        )
        assert under_review.status_code == 200
        under_review_body = under_review.json()
        assert under_review_body['clarification_state'] == 'UNDER_REVIEW'

        case_under_review = client.get(f'/inspect/cases/{case_id}/json')
        assert case_under_review.status_code == 200
        case_under_review_body = case_under_review.json()
        assert case_under_review_body['telegram_clarification']['clarification_state'] == 'UNDER_REVIEW'
        assert case_under_review_body['telegram_ingress']['user_visible_status']['status_code'] == 'UNDER_REVIEW'

        review_items = client.get(f'/inspect/open-items/json?case_id={case_id}')
        assert review_items.status_code == 200
        assert review_items.json()[0]['status'] == 'OPEN'

        resolved = client.post(
            f'/inspect/cases/{case_id}/telegram-clarification-resolution',
            json={'decision': 'COMPLETED', 'note': 'Antwort reicht fuer diesen Klaerpunkt aus.'},
            headers={'x-frya-csrf-token': csrf},
        )
        assert resolved.status_code == 200
        resolved_body = resolved.json()
        assert resolved_body['clarification_state'] == 'COMPLETED'
        assert resolved_body['resolution_outcome'] == 'COMPLETED'

        case_completed = client.get(f'/inspect/cases/{case_id}/json')
        assert case_completed.status_code == 200
        completed_body = case_completed.json()
        assert completed_body['telegram_clarification']['clarification_state'] == 'COMPLETED'
        assert completed_body['telegram_ingress']['user_visible_status']['status_code'] == 'COMPLETED'

        open_items = client.get(f'/inspect/open-items/json?case_id={case_id}')
        assert open_items.status_code == 200
        assert open_items.json()[0]['status'] == 'COMPLETED'

        actions = [entry['action'] for entry in completed_body['chronology']]
        assert 'TELEGRAM_CLARIFICATION_UNDER_REVIEW' in actions
        assert 'TELEGRAM_CLARIFICATION_COMPLETED' in actions

        status_result = _send_allowed_text(client, 1003, 73, '/status')
        assert status_result['intent'] == 'status.overview'
        assert status_result['linked_case_id'] == case_id
        assert status_result['user_visible_status']['status_code'] == 'COMPLETED'

        late_reply = client.post(
            '/webhooks/telegram',
            json={
                'update_id': 1004,
                'message': {
                    'message_id': 74,
                    'reply_to_message': {'message_id': 9999},
                    'chat': {'id': 1310959044, 'type': 'private'},
                    'from': {'id': 1310959044, 'username': 'maze'},
                    'text': 'Nachtraegliche Antwort',
                },
            },
            headers=_telegram_headers(),
        )
        assert late_reply.status_code == 200
        assert late_reply.json()['routing_status'] == 'CLARIFICATION_NOT_OPEN'


def test_telegram_clarification_resolution_still_open_allows_follow_up(tmp_path, monkeypatch):
    _configure_env(monkeypatch, tmp_path)
    app = _build_app()

    with TestClient(app) as client:
        inbox = _send_allowed_text(client, 1011, 81, 'bitte noch mal pruefen')
        case_id = inbox['case_id']

        _login_admin(client)
        ui_before = client.get(f'/ui/cases/{case_id}')
        assert ui_before.status_code == 200
        csrf = _extract_csrf_token(ui_before.text)

        requested = client.post(
            f'/inspect/cases/{case_id}/telegram-clarification-request',
            json={'question': 'Welche Kundennummer steht im Dokument?'},
            headers={'x-frya-csrf-token': csrf},
        )
        assert requested.status_code == 200

        answered = client.post(
            '/webhooks/telegram',
            json={
                'update_id': 1012,
                'message': {
                    'message_id': 82,
                    'chat': {'id': 1310959044, 'type': 'private'},
                    'from': {'id': 1310959044, 'username': 'maze'},
                    'text': 'Unklar, vielleicht 123.',
                },
            },
            headers=_telegram_headers(),
        )
        assert answered.status_code == 200
        assert answered.json()['routing_status'] == 'CLARIFICATION_ANSWER_ACCEPTED'

        under_review = client.post(
            f'/inspect/cases/{case_id}/telegram-clarification-under-review',
            json={'note': 'Antwort reicht noch nicht.'},
            headers={'x-frya-csrf-token': csrf},
        )
        assert under_review.status_code == 200

        still_open = client.post(
            f'/inspect/cases/{case_id}/telegram-clarification-resolution',
            json={'decision': 'STILL_OPEN', 'note': 'Weitere Rueckfrage erforderlich.'},
            headers={'x-frya-csrf-token': csrf},
        )
        assert still_open.status_code == 200
        still_open_body = still_open.json()
        assert still_open_body['clarification_state'] == 'STILL_OPEN'
        assert still_open_body['resolution_outcome'] == 'STILL_OPEN'

        case_json = client.get(f'/inspect/cases/{case_id}/json')
        assert case_json.status_code == 200
        case_body = case_json.json()
        assert case_body['telegram_ingress']['user_visible_status']['status_code'] == 'NEEDS_FURTHER_REPLY'
        assert case_body['telegram_clarification']['clarification_state'] == 'STILL_OPEN'
        assert case_body['telegram_clarification']['follow_up_allowed'] is True
        assert len(case_body['telegram_clarification_rounds']) == 1

        open_items = client.get(f'/inspect/open-items/json?case_id={case_id}')
        assert open_items.status_code == 200
        assert open_items.json()[0]['status'] == 'OPEN'

        ui_after = client.get(f'/ui/cases/{case_id}')
        assert ui_after.status_code == 200
        assert 'Telegram-Klaerabschluss' not in ui_after.text
        assert 'Telegram Follow-up senden' in ui_after.text

        follow_up = client.post(
            f'/inspect/cases/{case_id}/telegram-clarification-request',
            json={'question': 'Bitte nenne die exakte Kundennummer.'},
            headers={'x-frya-csrf-token': csrf},
        )
        assert follow_up.status_code == 200
        follow_up_body = follow_up.json()
        assert follow_up_body['clarification_round'] == 2
        assert follow_up_body['parent_clarification_ref'] == still_open_body['clarification_ref']

        status_result = _send_allowed_text(client, 1013, 83, '/status')
        assert status_result['intent'] == 'status.overview'
        assert status_result['linked_case_id'] == case_id
        assert status_result['user_visible_status']['status_code'] == 'WAITING_FOR_YOUR_REPLY'
