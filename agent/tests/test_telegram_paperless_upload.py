"""Test: Telegram PDF → Paperless upload (mocked)."""
import json
import pytest

from fastapi.testclient import TestClient

from app.connectors.dms_paperless import PaperlessConnector
from app.connectors.notifications_telegram import TelegramConnector
from tests.test_api_surface import _build_app
from tests.test_telegram_clarification_v1 import _configure_env, _telegram_headers
from tests.test_telegram_media_ingress_v1 import _media_payload


def test_telegram_pdf_uploaded_to_paperless(tmp_path, monkeypatch):
    """Telegram PDF → local store → Paperless upload → task_id in audit."""
    _configure_env(monkeypatch, tmp_path)
    monkeypatch.setenv('FRYA_TELEGRAM_BOT_TOKEN', 'telegram-test-token')

    uploaded: list[dict] = []

    async def fake_send(self, message, disable_notification: bool = False):
        return {'ok': True, 'status_code': 200, 'body': json.dumps({'ok': True, 'result': {'message_id': 901}}), 'json': {'ok': True, 'result': {'message_id': 901}}}

    async def fake_get_file_info(self, file_id: str):
        return {'ok': True, 'status_code': 200, 'body': json.dumps({'ok': True, 'result': {'file_path': f'documents/{file_id}.pdf'}}), 'json': {'ok': True, 'result': {'file_path': f'documents/{file_id}.pdf'}}, 'reason': None}

    async def fake_download_file(self, file_path: str):
        return {'ok': True, 'status_code': 200, 'body': None, 'content': b'%PDF-1.4 test', 'content_type': 'application/pdf', 'reason': None}

    async def fake_upload_document(self, file_bytes: bytes, filename: str, title: str | None = None):
        uploaded.append({'filename': filename, 'title': title, 'size': len(file_bytes)})
        return {'task_id': 'mock-task-id-001'}

    monkeypatch.setattr(TelegramConnector, 'send', fake_send)
    monkeypatch.setattr(TelegramConnector, 'get_file_info', fake_get_file_info)
    monkeypatch.setattr(TelegramConnector, 'download_file', fake_download_file)
    monkeypatch.setattr(PaperlessConnector, 'upload_document', fake_upload_document)

    app = _build_app()
    with TestClient(app) as client:
        response = client.post(
            '/webhooks/telegram',
            json=_media_payload(
                7001, 701,
                document={'file_id': 'pdf-pl-1', 'file_unique_id': 'pl-uniq-1', 'file_name': 'rechnung.pdf', 'mime_type': 'application/pdf', 'file_size': 256},
                caption='Rechnung hochladen',
            ),
            headers=_telegram_headers(),
        )
        assert response.status_code == 200
        body = response.json()
        assert body['routing_status'] == 'DOCUMENT_ACCEPTED'

        # Paperless upload was called
        assert len(uploaded) == 1
        assert uploaded[0]['filename'] == 'rechnung.pdf'
        # Title encodes case_id for webhook correlation
        assert uploaded[0]['title'].startswith('frya:')
        assert body['case_id'] in uploaded[0]['title']

        # Audit event logged for Paperless upload
        from tests.test_api_surface import _login_admin
        _login_admin(client)
        case_id = body['case_id']
        audit_resp = client.get(f'/inspect/cases/{case_id}/json')
        assert audit_resp.status_code == 200
