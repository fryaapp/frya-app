from fastapi.testclient import TestClient

from tests.test_api_surface import _build_app, _extract_csrf_token, _login_admin
from tests.test_telegram_clarification_v1 import _configure_env, _send_allowed_text, _telegram_headers


def _request_initial_clarification(client: TestClient, case_id: str, csrf: str, question: str) -> dict:
    response = client.post(
        f'/inspect/cases/{case_id}/telegram-clarification-request',
        json={'question': question},
        headers={'x-frya-csrf-token': csrf},
    )
    assert response.status_code == 200
    return response.json()


def _answer_current_clarification(client: TestClient, update_id: int, message_id: int, text: str) -> dict:
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


def _mark_under_review(client: TestClient, case_id: str, csrf: str, note: str) -> dict:
    response = client.post(
        f'/inspect/cases/{case_id}/telegram-clarification-under-review',
        json={'note': note},
        headers={'x-frya-csrf-token': csrf},
    )
    assert response.status_code == 200
    return response.json()


def _resolve(client: TestClient, case_id: str, csrf: str, decision: str, note: str) -> dict:
    response = client.post(
        f'/inspect/cases/{case_id}/telegram-clarification-resolution',
        json={'decision': decision, 'note': note},
        headers={'x-frya-csrf-token': csrf},
    )
    assert response.status_code == 200
    return response.json()


def test_telegram_follow_up_round_can_complete_after_second_answer(tmp_path, monkeypatch):
    _configure_env(monkeypatch, tmp_path)
    app = _build_app()

    with TestClient(app) as client:
        inbox = _send_allowed_text(client, 3001, 301, 'ich brauche noch hilfe')
        case_id = inbox['case_id']

        _login_admin(client)
        ui_before = client.get(f'/ui/cases/{case_id}')
        assert ui_before.status_code == 200
        csrf = _extract_csrf_token(ui_before.text)

        round_one = _request_initial_clarification(client, case_id, csrf, 'Welche Rechnungsnummer steht im Beleg?')
        assert round_one['clarification_round'] == 1

        first_answer = _answer_current_clarification(client, 3002, 302, 'Ich sehe nur INV')
        assert first_answer['routing_status'] == 'CLARIFICATION_ANSWER_ACCEPTED'
        _mark_under_review(client, case_id, csrf, 'Antwort unvollstaendig.')
        first_still_open = _resolve(client, case_id, csrf, 'STILL_OPEN', 'Bitte exakte Nummer nachfragen.')
        assert first_still_open['clarification_state'] == 'STILL_OPEN'
        assert first_still_open['follow_up_allowed'] is True

        round_two = _request_initial_clarification(client, case_id, csrf, 'Bitte sende die exakte Rechnungsnummer.')
        assert round_two['clarification_round'] == 2
        assert round_two['follow_up_count'] == 1
        assert round_two['parent_clarification_ref'] == round_one['clarification_ref']

        second_answer = _answer_current_clarification(client, 3003, 303, 'INV-9901')
        assert second_answer['routing_status'] == 'CLARIFICATION_ANSWER_ACCEPTED'

        case_after_reply = client.get(f'/inspect/cases/{case_id}/json')
        assert case_after_reply.status_code == 200
        case_after_reply_body = case_after_reply.json()
        assert case_after_reply_body['telegram_clarification']['clarification_round'] == 2
        assert case_after_reply_body['telegram_clarification']['clarification_state'] == 'ANSWER_RECEIVED'
        assert case_after_reply_body['telegram_ingress']['user_visible_status']['status_code'] == 'REPLY_RECEIVED'
        assert len(case_after_reply_body['telegram_clarification_rounds']) == 2

        _mark_under_review(client, case_id, csrf, 'Zweite Antwort wird geprueft.')
        second_completed = _resolve(client, case_id, csrf, 'COMPLETED', 'Zweite Antwort reicht jetzt aus.')
        assert second_completed['clarification_state'] == 'COMPLETED'
        assert second_completed['clarification_round'] == 2

        completed_case = client.get(f'/inspect/cases/{case_id}/json')
        assert completed_case.status_code == 200
        completed_case_body = completed_case.json()
        assert completed_case_body['telegram_ingress']['user_visible_status']['status_code'] == 'COMPLETED'
        assert completed_case_body['telegram_clarification']['clarification_round'] == 2
        assert completed_case_body['telegram_clarification_rounds'][0]['clarification_round'] == 1
        assert completed_case_body['telegram_clarification_rounds'][1]['clarification_round'] == 2

        open_items = client.get(f'/inspect/open-items/json?case_id={case_id}')
        assert open_items.status_code == 200
        assert open_items.json()[0]['status'] == 'COMPLETED'

        status_result = _send_allowed_text(client, 3004, 304, '/status')
        assert status_result['linked_case_id'] == case_id
        assert status_result['user_visible_status']['status_code'] == 'COMPLETED'


def test_telegram_follow_up_cycle_stops_after_one_additional_round(tmp_path, monkeypatch):
    _configure_env(monkeypatch, tmp_path)
    app = _build_app()

    with TestClient(app) as client:
        inbox = _send_allowed_text(client, 3101, 311, 'bitte klaeren')
        case_id = inbox['case_id']

        _login_admin(client)
        ui_before = client.get(f'/ui/cases/{case_id}')
        assert ui_before.status_code == 200
        csrf = _extract_csrf_token(ui_before.text)

        _request_initial_clarification(client, case_id, csrf, 'Welche Referenz steht im Text?')
        _answer_current_clarification(client, 3102, 312, 'Vielleicht REF')
        _mark_under_review(client, case_id, csrf, 'Zu vage.')
        _resolve(client, case_id, csrf, 'STILL_OPEN', 'Follow-up ist sinnvoll.')

        _request_initial_clarification(client, case_id, csrf, 'Bitte nenne die exakte Referenz.')
        _answer_current_clarification(client, 3103, 313, 'Immer noch unklar')
        _mark_under_review(client, case_id, csrf, 'Auch die zweite Antwort reicht nicht.')
        second_still_open = _resolve(client, case_id, csrf, 'STILL_OPEN', 'Intern weiter offen, kein dritter Telegram-Zyklus.')
        assert second_still_open['clarification_state'] == 'STILL_OPEN'
        assert second_still_open['clarification_round'] == 2
        assert second_still_open['follow_up_allowed'] is False

        third_follow_up = client.post(
            f'/inspect/cases/{case_id}/telegram-clarification-request',
            json={'question': 'Dritte Rueckfrage'},
            headers={'x-frya-csrf-token': csrf},
        )
        assert third_follow_up.status_code == 409

        case_json = client.get(f'/inspect/cases/{case_id}/json')
        assert case_json.status_code == 200
        case_body = case_json.json()
        assert case_body['telegram_clarification']['clarification_round'] == 2
        assert case_body['telegram_clarification']['follow_up_block_reason'] == 'Maximal eine weitere Telegram-Rueckfrage wurde bereits genutzt.'
        assert case_body['telegram_clarification']['telegram_followup_exhausted'] is True
        assert case_body['telegram_clarification']['internal_followup_required'] is True
        assert case_body['telegram_clarification']['internal_followup_state'] == 'REQUIRED'
        assert case_body['telegram_ingress']['user_visible_status']['status_code'] == 'UNDER_INTERNAL_REVIEW'
        assert len(case_body['telegram_clarification_rounds']) == 2

        late_reply = client.post(
            '/webhooks/telegram',
            json={
                'update_id': 3104,
                'message': {
                    'message_id': 314,
                    'reply_to_message': {'message_id': 9999},
                    'chat': {'id': 1310959044, 'type': 'private'},
                    'from': {'id': 1310959044, 'username': 'maze'},
                    'text': 'Spaete Antwort',
                },
            },
            headers=_telegram_headers(),
        )
        assert late_reply.status_code == 200
        assert late_reply.json()['routing_status'] == 'CLARIFICATION_NOT_OPEN'

        status_result = _send_allowed_text(client, 3105, 315, '/status')
        assert status_result['linked_case_id'] == case_id
        assert status_result['user_visible_status']['status_code'] == 'UNDER_INTERNAL_REVIEW'
