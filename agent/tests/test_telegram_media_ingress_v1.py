import json

from fastapi.testclient import TestClient

from app.connectors.notifications_telegram import TelegramConnector
from tests.test_api_surface import _build_app, _login_admin
from tests.test_telegram_clarification_v1 import _configure_env, _telegram_headers


def _media_payload(update_id: int, message_id: int, document: dict | None = None, photo: list[dict] | None = None, caption: str = '') -> dict:
    message = {
        'message_id': message_id,
        'chat': {'id': 1310959044, 'type': 'private'},
        'from': {'id': 1310959044, 'username': 'maze'},
    }
    if caption:
        message['caption'] = caption
    if document is not None:
        message['document'] = document
    if photo is not None:
        message['photo'] = photo
    return {'update_id': update_id, 'message': message}


def test_telegram_media_pdf_is_stored_and_queued(tmp_path, monkeypatch):
    _configure_env(monkeypatch, tmp_path)
    monkeypatch.setenv('FRYA_TELEGRAM_BOT_TOKEN', 'telegram-test-token')

    sent_messages: list[str] = []

    async def fake_send(self, message, disable_notification: bool = False):
        sent_messages.append(message.text)
        return {
            'ok': True,
            'status_code': 200,
            'body': json.dumps({'ok': True, 'result': {'message_id': 900 + len(sent_messages)}}),
            'json': {'ok': True, 'result': {'message_id': 900 + len(sent_messages)}},
        }

    async def fake_get_file_info(self, file_id: str):
        return {
            'ok': True,
            'status_code': 200,
            'body': json.dumps({'ok': True, 'result': {'file_path': f'documents/{file_id}.pdf'}}),
            'json': {'ok': True, 'result': {'file_path': f'documents/{file_id}.pdf'}},
            'reason': None,
        }

    async def fake_download_file(self, file_path: str):
        return {
            'ok': True,
            'status_code': 200,
            'body': None,
            'content': b'%PDF-1.4 test pdf',
            'content_type': 'application/pdf',
            'reason': None,
        }

    monkeypatch.setattr(TelegramConnector, 'send', fake_send)
    monkeypatch.setattr(TelegramConnector, 'get_file_info', fake_get_file_info)
    monkeypatch.setattr(TelegramConnector, 'download_file', fake_download_file)

    app = _build_app()

    with TestClient(app) as client:
        response = client.post(
            '/webhooks/telegram',
            json=_media_payload(
                6101,
                611,
                document={
                    'file_id': 'pdf-file-1',
                    'file_unique_id': 'pdf-uniq-1',
                    'file_name': 'beleg.pdf',
                    'mime_type': 'application/pdf',
                    'file_size': 512,
                },
                caption='Rechnung von Telegram',
            ),
            headers=_telegram_headers(),
        )
        assert response.status_code == 200
        body = response.json()
        assert body['routing_status'] == 'DOCUMENT_ACCEPTED'
        assert body['command_status'] == 'DOCUMENT_INBOX_ACCEPTED'
        assert body['document_analyst_context']['analyst_context_status'] == 'DOCUMENT_ANALYST_PENDING'
        assert body['document_analyst_context']['target_case_id'] == body['case_id']
        media = body['media']
        assert media['media_domain'] == 'DOCUMENT'
        assert media['storage_status'] == 'STORED'
        assert media['download_status'] == 'DOWNLOADED'
        assert media['document_intake_status'] == 'DOCUMENT_INBOX_ACCEPTED'
        assert media['document_intake_ref'] == body['open_item_id']
        stored_path = tmp_path / media['stored_relative_path']
        assert stored_path.exists()
        assert stored_path.read_bytes() == b'%PDF-1.4 test pdf'

        duplicate = client.post(
            '/webhooks/telegram',
            json=_media_payload(
                6101,
                611,
                document={
                    'file_id': 'pdf-file-1',
                    'file_unique_id': 'pdf-uniq-1',
                    'file_name': 'beleg.pdf',
                    'mime_type': 'application/pdf',
                    'file_size': 512,
                },
                caption='Rechnung von Telegram',
            ),
            headers=_telegram_headers(),
        )
        assert duplicate.status_code == 200
        assert duplicate.json()['status'] == 'duplicate_ignored'

        case_id = body['case_id']
        _login_admin(client)
        case_json = client.get(f'/inspect/cases/{case_id}/json')
        assert case_json.status_code == 200
        case_body = case_json.json()
        assert case_body['telegram_media']['storage_status'] == 'STORED'
        assert case_body['telegram_media']['document_intake_status'] == 'DOCUMENT_INBOX_ACCEPTED'
        assert case_body['telegram_media']['open_item_id'] == body['open_item_id']
        assert case_body['document_analyst_context']['analyst_context_status'] == 'DOCUMENT_ANALYST_PENDING'
        assert case_body['document_analyst_context']['analyst_context_open_item_id']
        assert case_body['telegram_ingress']['reply_status'] == 'SENT'

        ui_case = client.get(f'/ui/cases/{case_id}')
        assert ui_case.status_code == 200
        assert 'Telegram Media' in ui_case.text
        assert 'Document Analyst Context' in ui_case.text
        assert 'Queue / Intake' in ui_case.text
        assert 'beleg.pdf' in ui_case.text


def test_telegram_media_too_large_is_rejected_safely(tmp_path, monkeypatch):
    _configure_env(monkeypatch, tmp_path)
    monkeypatch.setenv('FRYA_TELEGRAM_BOT_TOKEN', 'telegram-test-token')
    monkeypatch.setenv('FRYA_TELEGRAM_MEDIA_MAX_BYTES', '128')

    async def fake_send(self, message, disable_notification: bool = False):
        return {
            'ok': True,
            'status_code': 200,
            'body': json.dumps({'ok': True, 'result': {'message_id': 950}}),
            'json': {'ok': True, 'result': {'message_id': 950}},
        }

    monkeypatch.setattr(TelegramConnector, 'send', fake_send)

    app = _build_app()

    with TestClient(app) as client:
        response = client.post(
            '/webhooks/telegram',
            json=_media_payload(
                6201,
                621,
                document={
                    'file_id': 'pdf-file-2',
                    'file_unique_id': 'pdf-uniq-2',
                    'file_name': 'gross.pdf',
                    'mime_type': 'application/pdf',
                    'file_size': 2048,
                },
            ),
            headers=_telegram_headers(),
        )
        assert response.status_code == 200
        body = response.json()
        assert body['routing_status'] == 'DOCUMENT_TOO_LARGE'
        assert body['command_status'] == 'FILE_TOO_LARGE'
        assert body['media']['storage_status'] == 'SKIPPED'


def test_telegram_photo_is_prepared_for_document_analyst_context(tmp_path, monkeypatch):
    _configure_env(monkeypatch, tmp_path)
    monkeypatch.setenv('FRYA_TELEGRAM_BOT_TOKEN', 'telegram-test-token')

    async def fake_send(self, message, disable_notification: bool = False):
        return {
            'ok': True,
            'status_code': 200,
            'body': json.dumps({'ok': True, 'result': {'message_id': 955}}),
            'json': {'ok': True, 'result': {'message_id': 955}},
        }

    async def fake_get_file_info(self, file_id: str):
        return {
            'ok': True,
            'status_code': 200,
            'body': json.dumps({'ok': True, 'result': {'file_path': f'photos/{file_id}.jpg'}}),
            'json': {'ok': True, 'result': {'file_path': f'photos/{file_id}.jpg'}},
            'reason': None,
        }

    async def fake_download_file(self, file_path: str):
        return {
            'ok': True,
            'status_code': 200,
            'body': None,
            'content': b'jpeg-data',
            'content_type': 'image/jpeg',
            'reason': None,
        }

    monkeypatch.setattr(TelegramConnector, 'send', fake_send)
    monkeypatch.setattr(TelegramConnector, 'get_file_info', fake_get_file_info)
    monkeypatch.setattr(TelegramConnector, 'download_file', fake_download_file)

    app = _build_app()

    with TestClient(app) as client:
        response = client.post(
            '/webhooks/telegram',
            json=_media_payload(
                6251,
                625,
                photo=[
                    {
                        'file_id': 'photo-file-1',
                        'file_unique_id': 'photo-uniq-1',
                        'file_size': 256,
                        'width': 100,
                        'height': 100,
                    }
                ],
                caption='Foto vom Beleg',
            ),
            headers=_telegram_headers(),
        )
        assert response.status_code == 200
        body = response.json()
        assert body['routing_status'] == 'MEDIA_ACCEPTED'
        assert body['document_analyst_context']['analyst_context_status'] == 'DOCUMENT_ANALYST_PENDING'
        assert body['document_analyst_context']['media_domain'] == 'PHOTO'
        assert body['document_analyst_context']['document_intake_ref'] is None


def test_telegram_media_unsupported_type_is_rejected_safely(tmp_path, monkeypatch):
    _configure_env(monkeypatch, tmp_path)
    monkeypatch.setenv('FRYA_TELEGRAM_BOT_TOKEN', 'telegram-test-token')

    async def fake_send(self, message, disable_notification: bool = False):
        return {
            'ok': True,
            'status_code': 200,
            'body': json.dumps({'ok': True, 'result': {'message_id': 960}}),
            'json': {'ok': True, 'result': {'message_id': 960}},
        }

    monkeypatch.setattr(TelegramConnector, 'send', fake_send)

    app = _build_app()

    with TestClient(app) as client:
        response = client.post(
            '/webhooks/telegram',
            json=_media_payload(
                6301,
                631,
                document={
                    'file_id': 'txt-file-1',
                    'file_unique_id': 'txt-uniq-1',
                    'file_name': 'notizen.txt',
                    'mime_type': 'text/plain',
                    'file_size': 64,
                },
            ),
            headers=_telegram_headers(),
        )
        assert response.status_code == 200
        body = response.json()
        assert body['routing_status'] == 'DOCUMENT_UNSUPPORTED'
        assert body['command_status'] == 'UNSUPPORTED_MEDIA_TYPE'
        assert body['media']['download_status'] == 'SKIPPED'


def test_telegram_document_links_to_latest_trackable_case_conservatively(tmp_path, monkeypatch):
    _configure_env(monkeypatch, tmp_path)
    monkeypatch.setenv('FRYA_TELEGRAM_BOT_TOKEN', 'telegram-test-token')

    async def fake_send(self, message, disable_notification: bool = False):
        return {
            'ok': True,
            'status_code': 200,
            'body': json.dumps({'ok': True, 'result': {'message_id': 980}}),
            'json': {'ok': True, 'result': {'message_id': 980}},
        }

    async def fake_get_file_info(self, file_id: str):
        return {
            'ok': True,
            'status_code': 200,
            'body': json.dumps({'ok': True, 'result': {'file_path': f'documents/{file_id}.pdf'}}),
            'json': {'ok': True, 'result': {'file_path': f'documents/{file_id}.pdf'}},
            'reason': None,
        }

    async def fake_download_file(self, file_path: str):
        return {
            'ok': True,
            'status_code': 200,
            'body': None,
            'content': b'%PDF-1.4 linked context',
            'content_type': 'application/pdf',
            'reason': None,
        }

    monkeypatch.setattr(TelegramConnector, 'send', fake_send)
    monkeypatch.setattr(TelegramConnector, 'get_file_info', fake_get_file_info)
    monkeypatch.setattr(TelegramConnector, 'download_file', fake_download_file)

    app = _build_app()

    with TestClient(app) as client:
        inbox = client.post(
            '/webhooks/telegram',
            json={
                'update_id': 6401,
                'message': {
                    'message_id': 641,
                    'chat': {'id': 1310959044, 'type': 'private'},
                    'from': {'id': 1310959044, 'username': 'maze'},
                    'text': 'Hier kommt gleich ein PDF dazu',
                },
            },
            headers=_telegram_headers(),
        )
        assert inbox.status_code == 200
        inbox_body = inbox.json()
        assert inbox_body['routing_status'] == 'ACCEPTED_TO_INBOX'

        doc = client.post(
            '/webhooks/telegram',
            json=_media_payload(
                6402,
                642,
                document={
                    'file_id': 'pdf-file-ctx',
                    'file_unique_id': 'pdf-uniq-ctx',
                    'file_name': 'kontext.pdf',
                    'mime_type': 'application/pdf',
                    'file_size': 512,
                },
            ),
            headers=_telegram_headers(),
        )
        assert doc.status_code == 200
        body = doc.json()
        assert body['routing_status'] == 'DOCUMENT_ACCEPTED'
        assert body['linked_case_id'] == body['case_id']
        assert body['media']['linked_context_case_id'] == inbox_body['case_id']
        assert body['media']['document_intake_status'] == 'DOCUMENT_INTAKE_LINKED'
        assert body['document_analyst_context']['analyst_context_status'] == 'DOCUMENT_ANALYST_CONTEXT_ATTACHED'
        assert body['document_analyst_context']['target_case_id'] == inbox_body['case_id']

        _login_admin(client)
        source_case_json = client.get(f"/inspect/cases/{body['case_id']}/json")
        assert source_case_json.status_code == 200
        assert source_case_json.json()['document_analyst_context']['target_case_id'] == inbox_body['case_id']

        linked_case_json = client.get(f"/inspect/cases/{inbox_body['case_id']}/json")
        assert linked_case_json.status_code == 200
        linked_case_body = linked_case_json.json()
        assert linked_case_body['document_analyst_context']['analyst_context_status'] == 'DOCUMENT_ANALYST_CONTEXT_ATTACHED'
        assert linked_case_body['document_analyst_context']['source_case_id'] == body['case_id']
        assert any(
            item['title'] == 'Document Analyst Eingang vorbereiten' and item['source'] == 'document_analyst'
            for item in linked_case_body['open_items']
        )
