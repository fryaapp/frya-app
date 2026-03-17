from fastapi.testclient import TestClient

from tests.test_api_surface import _build_app, _extract_csrf_token, _login_admin
from tests.test_telegram_clarification_followup_v1 import (
    _answer_current_clarification,
    _mark_under_review,
    _request_initial_clarification,
    _resolve,
)
from tests.test_telegram_clarification_v1 import _configure_env, _send_allowed_text, _telegram_headers


def _reach_internal_followup_required(client: TestClient, case_id: str, csrf: str) -> None:
    _request_initial_clarification(client, case_id, csrf, 'Welche Rechnungsnummer steht auf dem Dokument?')
    _answer_current_clarification(client, 4102, 412, 'Nur teilweise sichtbar')
    _mark_under_review(client, case_id, csrf, 'Erste Antwort reicht nicht.')
    _resolve(client, case_id, csrf, 'STILL_OPEN', 'Eine weitere Rueckfrage ist noch sinnvoll.')

    _request_initial_clarification(client, case_id, csrf, 'Bitte sende die exakte Rechnungsnummer.')
    _answer_current_clarification(client, 4103, 413, 'Weiterhin nicht belastbar')
    _mark_under_review(client, case_id, csrf, 'Auch nach der zweiten Antwort bleibt der Fall unklar.')
    _resolve(client, case_id, csrf, 'STILL_OPEN', 'Telegram endet hier. Intern weiterpruefen.')


def test_internal_followup_can_be_taken_under_review_and_completed(tmp_path, monkeypatch):
    _configure_env(monkeypatch, tmp_path)
    app = _build_app()

    with TestClient(app) as client:
        inbox = _send_allowed_text(client, 4101, 411, 'bitte intern weiter pruefen')
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
        under_review_body = under_review.json()
        assert under_review_body['internal_followup_state'] == 'UNDER_REVIEW'
        assert under_review_body['internal_followup_reviewed_by'] == 'admin'
        assert under_review_body['internal_followup_review_note'] == 'Interne Nachbearbeitung wurde uebernommen.'

        case_under_review = client.get(f'/inspect/cases/{case_id}/json')
        assert case_under_review.status_code == 200
        case_under_review_body = case_under_review.json()
        assert case_under_review_body['telegram_clarification']['internal_followup_state'] == 'UNDER_REVIEW'
        assert case_under_review_body['telegram_ingress']['user_visible_status']['status_code'] == 'UNDER_INTERNAL_REVIEW'

        completed = client.post(
            f'/inspect/cases/{case_id}/telegram-internal-followup-resolution',
            json={'decision': 'COMPLETED', 'note': 'Intern abgeschlossen, keine weitere Telegram-Aktion.'},
            headers={'x-frya-csrf-token': csrf},
        )
        assert completed.status_code == 200
        completed_body = completed.json()
        assert completed_body['internal_followup_state'] == 'COMPLETED'
        assert completed_body['internal_followup_required'] is False
        assert completed_body['internal_followup_resolved_by'] == 'admin'
        assert completed_body['internal_followup_resolution_note'] == 'Intern abgeschlossen, keine weitere Telegram-Aktion.'

        case_completed = client.get(f'/inspect/cases/{case_id}/json')
        assert case_completed.status_code == 200
        completed_case_body = case_completed.json()
        clarification = completed_case_body['telegram_clarification']
        assert clarification['clarification_state'] == 'STILL_OPEN'
        assert clarification['internal_followup_state'] == 'COMPLETED'
        assert clarification['internal_followup_closed_for_user_input'] is True
        assert completed_case_body['telegram_ingress']['user_visible_status']['status_code'] == 'COMPLETED'

        open_items = client.get(f'/inspect/open-items/json?case_id={case_id}')
        assert open_items.status_code == 200
        assert open_items.json()[0]['status'] == 'COMPLETED'

        actions = [entry['action'] for entry in completed_case_body['chronology']]
        assert 'TELEGRAM_INTERNAL_FOLLOWUP_REQUIRED' in actions
        assert 'TELEGRAM_INTERNAL_FOLLOWUP_UNDER_REVIEW' in actions
        assert 'TELEGRAM_INTERNAL_FOLLOWUP_COMPLETED' in actions

        ui_after = client.get(f'/ui/cases/{case_id}')
        assert ui_after.status_code == 200
        assert 'Internal Follow-up Status' in ui_after.text
        assert 'TELEGRAM_INTERNAL_FOLLOWUP_COMPLETED' in ui_after.text
        assert 'Interne Nachbearbeitung wurde abgeschlossen' in ui_after.text

        status_result = _send_allowed_text(client, 4104, 414, '/status')
        assert status_result['linked_case_id'] == case_id
        assert status_result['user_visible_status']['status_code'] == 'COMPLETED'


def test_internal_followup_completion_keeps_old_clarification_closed_for_input(tmp_path, monkeypatch):
    _configure_env(monkeypatch, tmp_path)
    app = _build_app()

    with TestClient(app) as client:
        inbox = _send_allowed_text(client, 4201, 421, 'bitte weiter intern pruefen')
        case_id = inbox['case_id']

        _login_admin(client)
        ui_before = client.get(f'/ui/cases/{case_id}')
        assert ui_before.status_code == 200
        csrf = _extract_csrf_token(ui_before.text)

        _reach_internal_followup_required(client, case_id, csrf)
        review = client.post(
            f'/inspect/cases/{case_id}/telegram-internal-followup-under-review',
            json={'note': 'Wird intern final geprueft.'},
            headers={'x-frya-csrf-token': csrf},
        )
        assert review.status_code == 200
        complete = client.post(
            f'/inspect/cases/{case_id}/telegram-internal-followup-resolution',
            json={'decision': 'COMPLETED', 'note': 'Intern final abgeschlossen.'},
            headers={'x-frya-csrf-token': csrf},
        )
        assert complete.status_code == 200

        late_reply = client.post(
            '/webhooks/telegram',
            json={
                'update_id': 4204,
                'message': {
                    'message_id': 424,
                    'reply_to_message': {'message_id': 9999},
                    'chat': {'id': 1310959044, 'type': 'private'},
                    'from': {'id': 1310959044, 'username': 'maze'},
                    'text': 'Spaete Antwort nach internem Abschluss',
                },
            },
            headers=_telegram_headers(),
        )
        assert late_reply.status_code == 200
        assert late_reply.json()['routing_status'] == 'CLARIFICATION_NOT_OPEN'

        late_reply_duplicate = client.post(
            '/webhooks/telegram',
            json={
                'update_id': 4204,
                'message': {
                    'message_id': 424,
                    'reply_to_message': {'message_id': 9999},
                    'chat': {'id': 1310959044, 'type': 'private'},
                    'from': {'id': 1310959044, 'username': 'maze'},
                    'text': 'Spaete Antwort nach internem Abschluss',
                },
            },
            headers=_telegram_headers(),
        )
        assert late_reply_duplicate.status_code == 200
        assert late_reply_duplicate.json()['status'] == 'duplicate_ignored'

        status_result = _send_allowed_text(client, 4205, 425, '/status')
        assert status_result['linked_case_id'] == case_id
        assert status_result['user_visible_status']['status_code'] == 'COMPLETED'

        new_text = client.post(
            '/webhooks/telegram',
            json={
                'update_id': 4206,
                'message': {
                    'message_id': 426,
                    'chat': {'id': 1310959044, 'type': 'private'},
                    'from': {'id': 1310959044, 'username': 'maze'},
                    'text': 'Neues Anliegen nach internem Abschluss',
                },
            },
            headers=_telegram_headers(),
        )
        assert new_text.status_code == 200
        new_text_body = new_text.json()
        assert new_text_body['routing_status'] == 'ACCEPTED_TO_INBOX'
        assert new_text_body['case_id'] != case_id
