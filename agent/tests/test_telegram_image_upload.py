"""Test: Telegram image (photo) → Paperless upload (mocked)."""
import json

from fastapi.testclient import TestClient

from app.connectors.dms_paperless import PaperlessConnector
from app.connectors.notifications_telegram import TelegramConnector
from tests.test_api_surface import _build_app
from tests.test_telegram_clarification_v1 import _configure_env, _telegram_headers
from tests.test_telegram_media_ingress_v1 import _media_payload


def test_telegram_image_uploaded_to_paperless(tmp_path, monkeypatch):
    """Telegram photo → local store → Paperless upload. Images treated same as PDFs."""
    _configure_env(monkeypatch, tmp_path)
    monkeypatch.setenv('FRYA_TELEGRAM_BOT_TOKEN', 'telegram-test-token')

    uploaded: list[dict] = []

    async def fake_send(self, message, disable_notification: bool = False):
        return {'ok': True, 'status_code': 200, 'body': json.dumps({'ok': True, 'result': {'message_id': 902}}), 'json': {'ok': True, 'result': {'message_id': 902}}}

    async def fake_get_file_info(self, file_id: str):
        return {'ok': True, 'status_code': 200, 'body': json.dumps({'ok': True, 'result': {'file_path': f'photos/{file_id}.jpg'}}), 'json': {'ok': True, 'result': {'file_path': f'photos/{file_id}.jpg'}}, 'reason': None}

    async def fake_download_file(self, file_path: str):
        return {'ok': True, 'status_code': 200, 'body': None, 'content': b'\xff\xd8\xff fake-jpeg', 'content_type': 'image/jpeg', 'reason': None}

    async def fake_upload_document(self, file_bytes: bytes, filename: str, title: str | None = None):
        uploaded.append({'filename': filename, 'title': title})
        return {'task_id': 'mock-task-id-img-001'}

    monkeypatch.setattr(TelegramConnector, 'send', fake_send)
    monkeypatch.setattr(TelegramConnector, 'get_file_info', fake_get_file_info)
    monkeypatch.setattr(TelegramConnector, 'download_file', fake_download_file)
    monkeypatch.setattr(PaperlessConnector, 'upload_document', fake_upload_document)

    app = _build_app()
    with TestClient(app) as client:
        response = client.post(
            '/webhooks/telegram',
            json=_media_payload(
                7002, 702,
                photo=[{'file_id': 'img-pl-1', 'file_unique_id': 'img-uniq-1', 'width': 800, 'height': 600, 'file_size': 50000}],
                caption='Kassenbon',
            ),
            headers=_telegram_headers(),
        )
        assert response.status_code == 200
        body = response.json()
        # Image is accepted
        assert body['routing_status'] in {'DOCUMENT_ACCEPTED', 'MEDIA_ACCEPTED'}

        # Paperless upload was called for the image too
        assert len(uploaded) == 1
        assert uploaded[0]['title'].startswith('frya:')
        assert body['case_id'] in uploaded[0]['title']
