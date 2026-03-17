from fastapi.testclient import TestClient

from tests.test_api_surface import _build_app, _extract_csrf_token, _login_admin
from tests.test_telegram_clarification_v1 import _configure_env
from tests.test_telegram_document_analyst_review_v1 import (
    _build_started_case,
    _patch_media_io,
    _patch_paperless_fast,
)


def _build_review_still_open_case(client: TestClient) -> tuple[str, dict]:
    case_id, start_body = _build_started_case(client)
    csrf = _extract_csrf_token(client.get(f'/ui/cases/{case_id}').text)
    review_response = client.post(
        f'/inspect/cases/{case_id}/document-analyst-review',
        json={'decision': 'STILL_OPEN', 'note': 'OCR/Textbasis reicht noch nicht.'},
        headers={'x-frya-csrf-token': csrf},
    )
    assert review_response.status_code == 200
    return case_id, start_body


def test_document_analyst_review_still_open_creates_followup_required(tmp_path, monkeypatch):
    _configure_env(monkeypatch, tmp_path)
    monkeypatch.setenv('FRYA_TELEGRAM_BOT_TOKEN', 'telegram-test-token')
    _patch_media_io(monkeypatch)
    _patch_paperless_fast(monkeypatch)

    app = _build_app()

    with TestClient(app) as client:
        case_id, start_body = _build_review_still_open_case(client)
        case_json = client.get(f'/inspect/cases/{case_id}/json')
        assert case_json.status_code == 200
        body = case_json.json()

        assert body['document_analyst_review']['review_status'] == 'DOCUMENT_ANALYST_REVIEW_STILL_OPEN'
        assert body['document_analyst_followup']['followup_status'] == 'DOCUMENT_ANALYST_FOLLOWUP_REQUIRED'
        assert body['document_analyst_followup']['runtime_open_item_id'] == start_body['runtime_open_item_id']
        assert body['document_analyst_followup']['telegram_data_request_allowed'] is True

        actions = [entry['action'] for entry in body['chronology']]
        assert 'DOCUMENT_ANALYST_FOLLOWUP_REQUIRED' in actions


def test_document_analyst_followup_request_data_creates_clarification_on_runtime_item(tmp_path, monkeypatch):
    _configure_env(monkeypatch, tmp_path)
    monkeypatch.setenv('FRYA_TELEGRAM_BOT_TOKEN', 'telegram-test-token')
    _patch_media_io(monkeypatch)
    _patch_paperless_fast(monkeypatch)

    app = _build_app()

    with TestClient(app) as client:
        case_id, start_body = _build_review_still_open_case(client)
        _login_admin(client)
        csrf = _extract_csrf_token(client.get(f'/ui/cases/{case_id}').text)

        followup_response = client.post(
            f'/inspect/cases/{case_id}/document-analyst-followup',
            json={
                'mode': 'REQUEST_DATA',
                'note': 'Bessere Lesbarkeit benoetigt.',
                'question': 'Bitte sende eine schaerfere Aufnahme oder das Dokument als PDF erneut.',
            },
            headers={'x-frya-csrf-token': csrf},
        )
        assert followup_response.status_code == 200
        followup_body = followup_response.json()
        assert followup_body['followup_status'] == 'DOCUMENT_ANALYST_FOLLOWUP_DATA_REQUESTED'
        assert followup_body['linked_clarification_ref']
        assert followup_body['data_request_question'].startswith('Bitte sende eine schaerfere Aufnahme')

        case_json = client.get(f'/inspect/cases/{case_id}/json')
        body = case_json.json()
        assert body['document_analyst_followup']['followup_status'] == 'DOCUMENT_ANALYST_FOLLOWUP_DATA_REQUESTED'
        assert body['document_analyst_followup']['linked_clarification_ref'] == body['telegram_clarification']['clarification_ref']
        assert body['telegram_clarification']['clarification_state'] == 'OPEN'
        assert body['telegram_clarification']['open_item_id'] == start_body['runtime_open_item_id']

        runtime_item = next(item for item in body['open_items'] if item['item_id'] == start_body['runtime_open_item_id'])
        assert runtime_item['status'] == 'WAITING_USER'
        prep_item = next(item for item in body['open_items'] if item['title'] == 'Document Analyst Eingang vorbereiten')
        assert prep_item['status'] == 'COMPLETED'

        actions = [entry['action'] for entry in body['chronology']]
        assert 'DOCUMENT_ANALYST_FOLLOWUP_REQUIRED' in actions
        assert 'DOCUMENT_ANALYST_FOLLOWUP_DATA_REQUESTED' in actions
        assert 'TELEGRAM_CLARIFICATION_REQUESTED' in actions

        ui_case = client.get(f'/ui/cases/{case_id}')
        assert ui_case.status_code == 200
        assert 'Document Analyst Follow-up' in ui_case.text
        assert 'DOCUMENT_ANALYST_FOLLOWUP_DATA_REQUESTED' in ui_case.text


def test_document_analyst_followup_close_conservatively_completes_runtime_item(tmp_path, monkeypatch):
    _configure_env(monkeypatch, tmp_path)
    monkeypatch.setenv('FRYA_TELEGRAM_BOT_TOKEN', 'telegram-test-token')
    _patch_media_io(monkeypatch)
    _patch_paperless_fast(monkeypatch)

    app = _build_app()

    with TestClient(app) as client:
        case_id, start_body = _build_review_still_open_case(client)
        _login_admin(client)
        csrf = _extract_csrf_token(client.get(f'/ui/cases/{case_id}').text)

        followup_response = client.post(
            f'/inspect/cases/{case_id}/document-analyst-followup',
            json={
                'mode': 'CLOSE_CONSERVATIVELY',
                'note': 'Fuer diesen Telegram-Pfad kein weiterer Schritt noetig.',
            },
            headers={'x-frya-csrf-token': csrf},
        )
        assert followup_response.status_code == 200
        followup_body = followup_response.json()
        assert followup_body['followup_status'] == 'DOCUMENT_ANALYST_FOLLOWUP_COMPLETED'
        assert followup_body['followup_mode'] == 'CLOSE_CONSERVATIVELY'
        assert followup_body['no_further_telegram_action'] is True

        case_json = client.get(f'/inspect/cases/{case_id}/json')
        body = case_json.json()
        runtime_item = next(item for item in body['open_items'] if item['item_id'] == start_body['runtime_open_item_id'])
        assert runtime_item['status'] == 'COMPLETED'
        assert body['document_analyst_followup']['followup_status'] == 'DOCUMENT_ANALYST_FOLLOWUP_COMPLETED'
        assert body['telegram_clarification'] is None


def test_document_analyst_followup_blocks_duplicate_request(tmp_path, monkeypatch):
    _configure_env(monkeypatch, tmp_path)
    monkeypatch.setenv('FRYA_TELEGRAM_BOT_TOKEN', 'telegram-test-token')
    _patch_media_io(monkeypatch)
    _patch_paperless_fast(monkeypatch)

    app = _build_app()

    with TestClient(app) as client:
        case_id, _ = _build_review_still_open_case(client)
        _login_admin(client)
        csrf = _extract_csrf_token(client.get(f'/ui/cases/{case_id}').text)

        first = client.post(
            f'/inspect/cases/{case_id}/document-analyst-followup',
            json={
                'mode': 'REQUEST_DATA',
                'note': 'Erste Rueckfrage',
                'question': 'Bitte sende das Dokument noch einmal klarer.',
            },
            headers={'x-frya-csrf-token': csrf},
        )
        assert first.status_code == 200

        duplicate = client.post(
            f'/inspect/cases/{case_id}/document-analyst-followup',
            json={
                'mode': 'REQUEST_DATA',
                'note': 'Zweite Rueckfrage',
                'question': 'Bitte nochmal alles senden.',
            },
            headers={'x-frya-csrf-token': csrf},
        )
        assert duplicate.status_code == 409
        assert 'bereits gesetzt' in duplicate.json()['detail']
