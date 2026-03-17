from fastapi.testclient import TestClient

from tests.test_api_surface import _build_app, _extract_csrf_token, _login_admin
from tests.test_telegram_clarification_v1 import _configure_env, _send_allowed_text, _telegram_headers
from tests.test_telegram_clarification_followup_v1 import (
    _answer_current_clarification,
    _mark_under_review,
    _request_initial_clarification,
    _resolve,
)


def test_round_two_still_open_activates_internal_followup_path(tmp_path, monkeypatch):
    _configure_env(monkeypatch, tmp_path)
    app = _build_app()

    with TestClient(app) as client:
        inbox = _send_allowed_text(client, 3201, 321, 'bitte weiter pruefen')
        case_id = inbox['case_id']

        _login_admin(client)
        ui_before = client.get(f'/ui/cases/{case_id}')
        assert ui_before.status_code == 200
        csrf = _extract_csrf_token(ui_before.text)

        round_one = _request_initial_clarification(client, case_id, csrf, 'Welche Rechnungsnummer steht auf dem Beleg?')
        _answer_current_clarification(client, 3202, 322, 'Nur teilweise lesbar')
        _mark_under_review(client, case_id, csrf, 'Erste Antwort reicht nicht.')
        _resolve(client, case_id, csrf, 'STILL_OPEN', 'Follow-up sinnvoll.')

        round_two = _request_initial_clarification(client, case_id, csrf, 'Bitte sende die exakte Rechnungsnummer.')
        assert round_two['clarification_round'] == 2
        _answer_current_clarification(client, 3203, 323, 'Immer noch nicht sicher')
        _mark_under_review(client, case_id, csrf, 'Auch die zweite Antwort ist nicht belastbar.')
        final = _resolve(client, case_id, csrf, 'STILL_OPEN', 'Telegram endet, Fall intern weiterpruefen.')
        assert final['clarification_round'] == 2
        assert final['telegram_followup_exhausted'] is True
        assert final['internal_followup_required'] is True
        assert final['internal_followup_state'] == 'REQUIRED'
        assert final['telegram_clarification_closed_for_user_input'] is True
        assert final['late_reply_policy'] == 'REJECT_NOT_OPEN'

        case_json = client.get(f'/inspect/cases/{case_id}/json')
        assert case_json.status_code == 200
        case_body = case_json.json()
        clarification = case_body['telegram_clarification']
        assert clarification['clarification_round'] == 2
        assert clarification['clarification_state'] == 'STILL_OPEN'
        assert clarification['internal_followup_required'] is True
        assert clarification['internal_followup_state'] == 'REQUIRED'
        assert clarification['telegram_followup_exhausted'] is True
        assert clarification['telegram_clarification_closed_for_user_input'] is True
        assert clarification['handoff_reason'] == 'Telegram endet, Fall intern weiterpruefen.'
        assert 'keine weitere Telegram-Rueckfrage' in clarification['operator_guidance']
        assert case_body['telegram_ingress']['user_visible_status']['status_code'] == 'UNDER_INTERNAL_REVIEW'
        assert len(case_body['telegram_clarification_rounds']) == 2

        open_items = client.get(f'/inspect/open-items/json?case_id={case_id}')
        assert open_items.status_code == 200
        assert open_items.json()[0]['status'] == 'OPEN'

        actions = [entry['action'] for entry in case_body['chronology']]
        assert 'TELEGRAM_INTERNAL_FOLLOWUP_REQUIRED' in actions

        ui_after = client.get(f'/ui/cases/{case_id}')
        assert ui_after.status_code == 200
        assert 'Internal Follow-up Status' in ui_after.text
        assert 'REQUIRED' in ui_after.text
        assert 'Telegram endet, Fall intern weiterpruefen.' in ui_after.text
        assert 'Telegram Follow-up senden' not in ui_after.text

        status_result = _send_allowed_text(client, 3204, 324, '/status')
        assert status_result['linked_case_id'] == case_id
        assert status_result['user_visible_status']['status_code'] == 'UNDER_INTERNAL_REVIEW'


def test_after_telegram_end_late_reply_is_rejected_and_new_text_becomes_new_ingress(tmp_path, monkeypatch):
    _configure_env(monkeypatch, tmp_path)
    app = _build_app()

    with TestClient(app) as client:
        inbox = _send_allowed_text(client, 3301, 331, 'ich brauche noch klaerung')
        case_id = inbox['case_id']

        _login_admin(client)
        ui_before = client.get(f'/ui/cases/{case_id}')
        assert ui_before.status_code == 200
        csrf = _extract_csrf_token(ui_before.text)

        first = _request_initial_clarification(client, case_id, csrf, 'Welche Referenz steht auf dem Dokument?')
        _answer_current_clarification(client, 3302, 332, 'Vielleicht REF')
        _mark_under_review(client, case_id, csrf, 'Noch unklar.')
        _resolve(client, case_id, csrf, 'STILL_OPEN', 'Zweite Rueckfrage ist noch sinnvoll.')

        second = _request_initial_clarification(client, case_id, csrf, 'Bitte nenne die exakte Referenz.')
        _answer_current_clarification(client, 3303, 333, 'Immer noch keine exakte Referenz')
        _mark_under_review(client, case_id, csrf, 'Zweite Antwort ebenfalls unklar.')
        _resolve(client, case_id, csrf, 'STILL_OPEN', 'Telegram endet hier.')

        late_reply = client.post(
            '/webhooks/telegram',
            json={
                'update_id': 3304,
                'message': {
                    'message_id': 334,
                    'reply_to_message': {'message_id': 9999},
                    'chat': {'id': 1310959044, 'type': 'private'},
                    'from': {'id': 1310959044, 'username': 'maze'},
                    'text': 'Spaete Antwort auf die alte Frage',
                },
            },
            headers=_telegram_headers(),
        )
        assert late_reply.status_code == 200
        assert late_reply.json()['routing_status'] == 'CLARIFICATION_NOT_OPEN'

        late_reply_duplicate = client.post(
            '/webhooks/telegram',
            json={
                'update_id': 3304,
                'message': {
                    'message_id': 334,
                    'reply_to_message': {'message_id': 9999},
                    'chat': {'id': 1310959044, 'type': 'private'},
                    'from': {'id': 1310959044, 'username': 'maze'},
                    'text': 'Spaete Antwort auf die alte Frage',
                },
            },
            headers=_telegram_headers(),
        )
        assert late_reply_duplicate.status_code == 200
        assert late_reply_duplicate.json()['status'] == 'duplicate_ignored'

        new_text = client.post(
            '/webhooks/telegram',
            json={
                'update_id': 3305,
                'message': {
                    'message_id': 335,
                    'chat': {'id': 1310959044, 'type': 'private'},
                    'from': {'id': 1310959044, 'username': 'maze'},
                    'text': 'Dann bitte als neuen Eingang aufnehmen',
                },
            },
            headers=_telegram_headers(),
        )
        assert new_text.status_code == 200
        new_text_body = new_text.json()
        assert new_text_body['routing_status'] == 'ACCEPTED_TO_INBOX'
        assert new_text_body['linked_case_id'] == new_text_body['case_id']
        assert new_text_body['case_id'] != case_id

        original_status = _send_allowed_text(client, 3306, 336, '/status')
        assert original_status['linked_case_id'] == new_text_body['case_id']
