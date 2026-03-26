import json

from fastapi.testclient import TestClient

from app.connectors.notifications_telegram import TelegramConnector
from tests.test_api_surface import _extract_csrf_token, _login_admin
from tests.test_telegram_clarification_v1 import _configure_env, _telegram_headers
from tests.test_telegram_media_ingress_v1 import _media_payload


def _patch_media_io(monkeypatch, *, content: bytes = b'jpeg-data', mime_type: str = 'image/jpeg', suffix: str = '.jpg') -> None:
    async def fake_send(self, message, disable_notification: bool = False):
        return {
            'ok': True,
            'status_code': 200,
            'body': json.dumps({'ok': True, 'result': {'message_id': 991}}),
            'json': {'ok': True, 'result': {'message_id': 991}},
        }

    async def fake_get_file_info(self, file_id: str):
        return {
            'ok': True,
            'status_code': 200,
            'body': json.dumps({'ok': True, 'result': {'file_path': f'media/{file_id}{suffix}'}}),
            'json': {'ok': True, 'result': {'file_path': f'media/{file_id}{suffix}'}},
            'reason': None,
        }

    async def fake_download_file(self, file_path: str):
        return {
            'ok': True,
            'status_code': 200,
            'body': None,
            'content': content,
            'content_type': mime_type,
            'reason': None,
        }

    monkeypatch.setattr(TelegramConnector, 'send', fake_send)
    monkeypatch.setattr(TelegramConnector, 'get_file_info', fake_get_file_info)
    monkeypatch.setattr(TelegramConnector, 'download_file', fake_download_file)


def _patch_paperless_fast(monkeypatch) -> None:
    import app.connectors.dms_paperless as paperless_module

    async def fake_get_document(self, document_id: str):
        return {'id': document_id, 'title': 'telegram-doc'}

    monkeypatch.setattr(paperless_module.PaperlessConnector, 'get_document', fake_get_document)


def _build_started_case(client: TestClient) -> tuple[str, dict]:
    response = client.post(
        '/webhooks/telegram',
        json=_media_payload(
            6801,
            681,
            photo=[
                {
                    'file_id': 'review-photo-1',
                    'file_unique_id': 'review-photo-uniq-1',
                    'file_size': 128,
                    'width': 100,
                    'height': 100,
                }
            ],
            caption='Telegram Bild fuer Review',
        ),
        headers=_telegram_headers(),
    )
    assert response.status_code == 200
    body = response.json()
    case_id = body['case_id']

    _login_admin(client)
    csrf = _extract_csrf_token(client.get(f'/ui/cases/{case_id}').text)
    start_response = client.post(
        f'/inspect/cases/{case_id}/document-analyst-start',
        json={'note': 'Start fuer Review-Test'},
        headers={'x-frya-csrf-token': csrf},
    )
    assert start_response.status_code == 200
    return case_id, start_response.json()


def test_document_analyst_review_still_open_keeps_runtime_item_visible(tmp_path, monkeypatch):
    _configure_env(monkeypatch, tmp_path)
    monkeypatch.setenv('FRYA_TELEGRAM_BOT_TOKEN', 'telegram-test-token')
    _patch_media_io(monkeypatch)
    _patch_paperless_fast(monkeypatch)

    from tests.test_api_surface import _build_app

    app = _build_app()

    with TestClient(app) as client:
        case_id, start_body = _build_started_case(client)
        case_json_before = client.get(f'/inspect/cases/{case_id}/json')
        before = case_json_before.json()
        assert before['document_analyst_review']['review_status'] == 'DOCUMENT_ANALYST_REVIEW_READY'
        assert before['document_analysis']['global_decision'] == 'INCOMPLETE'

        csrf = _extract_csrf_token(client.get(f'/ui/cases/{case_id}').text)
        review_response = client.post(
            f'/inspect/cases/{case_id}/document-analyst-review',
            json={'decision': 'STILL_OPEN', 'note': 'OCR/Textbasis reicht noch nicht.'},
            headers={'x-frya-csrf-token': csrf},
        )
        assert review_response.status_code == 200
        review_body = review_response.json()
        assert review_body['review_status'] == 'DOCUMENT_ANALYST_REVIEW_STILL_OPEN'
        assert review_body['review_outcome'] == 'OUTPUT_INCOMPLETE'
        assert review_body['runtime_open_item_id'] == start_body['runtime_open_item_id']

        case_json_after = client.get(f'/inspect/cases/{case_id}/json')
        assert case_json_after.status_code == 200
        after = case_json_after.json()
        assert after['document_analyst_review']['review_status'] == 'DOCUMENT_ANALYST_REVIEW_STILL_OPEN'
        assert after['document_analyst_review']['runtime_problem_id']
        runtime_item = next(item for item in after['open_items'] if item['item_id'] == start_body['runtime_open_item_id'])
        assert runtime_item['title'] == 'Dokumentdaten pruefen'
        assert runtime_item['status'] == 'WAITING_DATA'
        prep_item = next(item for item in after['open_items'] if item['title'] == 'Document Analyst Eingang vorbereiten')
        assert prep_item['status'] == 'COMPLETED'
        assert any(problem['title'] == 'Document analysis requires review' for problem in after['exceptions'])

        ui_case = client.get(f'/ui/cases/{case_id}')
        assert ui_case.status_code == 200
        assert 'Document Analyst Review' in ui_case.text
        assert 'DOCUMENT_ANALYST_REVIEW_STILL_OPEN' in ui_case.text
        assert 'Dokumentdaten pruefen' in ui_case.text


def test_document_analyst_review_completed_closes_runtime_item(tmp_path, monkeypatch):
    _configure_env(monkeypatch, tmp_path)
    monkeypatch.setenv('FRYA_TELEGRAM_BOT_TOKEN', 'telegram-test-token')
    _patch_media_io(monkeypatch)
    _patch_paperless_fast(monkeypatch)

    from tests.test_api_surface import _build_app

    app = _build_app()

    with TestClient(app) as client:
        case_id, start_body = _build_started_case(client)
        csrf = _extract_csrf_token(client.get(f'/ui/cases/{case_id}').text)

        review_response = client.post(
            f'/inspect/cases/{case_id}/document-analyst-review',
            json={'decision': 'COMPLETED', 'note': 'Fuer diesen konservativen Schritt gesichtet.'},
            headers={'x-frya-csrf-token': csrf},
        )
        assert review_response.status_code == 200
        review_body = review_response.json()
        assert review_body['review_status'] == 'DOCUMENT_ANALYST_REVIEW_COMPLETED'
        assert review_body['review_outcome'] == 'OUTPUT_ACCEPTED'

        case_json_after = client.get(f'/inspect/cases/{case_id}/json')
        after = case_json_after.json()
        runtime_item = next(item for item in after['open_items'] if item['item_id'] == start_body['runtime_open_item_id'])
        assert runtime_item['status'] == 'COMPLETED'
        assert after['document_analyst_review']['review_status'] == 'DOCUMENT_ANALYST_REVIEW_COMPLETED'


def test_document_analyst_review_blocks_duplicate_resolution(tmp_path, monkeypatch):
    _configure_env(monkeypatch, tmp_path)
    monkeypatch.setenv('FRYA_TELEGRAM_BOT_TOKEN', 'telegram-test-token')
    _patch_media_io(monkeypatch)
    _patch_paperless_fast(monkeypatch)

    from tests.test_api_surface import _build_app

    app = _build_app()

    with TestClient(app) as client:
        case_id, _ = _build_started_case(client)
        csrf = _extract_csrf_token(client.get(f'/ui/cases/{case_id}').text)
        first = client.post(
            f'/inspect/cases/{case_id}/document-analyst-review',
            json={'decision': 'STILL_OPEN', 'note': 'erster review'},
            headers={'x-frya-csrf-token': csrf},
        )
        assert first.status_code == 200

        duplicate = client.post(
            f'/inspect/cases/{case_id}/document-analyst-review',
            json={'decision': 'COMPLETED', 'note': 'zweiter review'},
            headers={'x-frya-csrf-token': csrf},
        )
        assert duplicate.status_code == 409
        assert 'bereits abgeschlossen' in duplicate.json()['detail']
