"""Test: Paperless upload failure → error reply to user, no silent failure."""
import json

import httpx
import pytest

from fastapi.testclient import TestClient

from app.connectors.dms_paperless import PaperlessConnector
from app.connectors.notifications_telegram import TelegramConnector
from tests.test_api_surface import _build_app
from tests.test_telegram_clarification_v1 import _configure_env, _telegram_headers
from tests.test_telegram_media_ingress_v1 import _media_payload


def test_paperless_unreachable_sends_error_reply(tmp_path, monkeypatch):
    """When Paperless upload fails, user gets error message (no silent failure)."""
    _configure_env(monkeypatch, tmp_path)
    monkeypatch.setenv('FRYA_TELEGRAM_BOT_TOKEN', 'telegram-test-token')

    sent_messages: list[str] = []

    async def fake_send(self, message, disable_notification: bool = False):
        sent_messages.append(message.text)
        return {'ok': True, 'status_code': 200, 'body': json.dumps({'ok': True, 'result': {'message_id': 903}}), 'json': {'ok': True, 'result': {'message_id': 903}}}

    async def fake_get_file_info(self, file_id: str):
        return {'ok': True, 'status_code': 200, 'body': json.dumps({'ok': True, 'result': {'file_path': f'documents/{file_id}.pdf'}}), 'json': {'ok': True, 'result': {'file_path': f'documents/{file_id}.pdf'}}, 'reason': None}

    async def fake_download_file(self, file_path: str):
        return {'ok': True, 'status_code': 200, 'body': None, 'content': b'%PDF-1.4 fail', 'content_type': 'application/pdf', 'reason': None}

    async def fake_upload_document_fails(self, file_bytes: bytes, filename: str, title: str | None = None):
        raise httpx.ConnectError('Connection refused — Paperless not reachable')

    monkeypatch.setattr(TelegramConnector, 'send', fake_send)
    monkeypatch.setattr(TelegramConnector, 'get_file_info', fake_get_file_info)
    monkeypatch.setattr(TelegramConnector, 'download_file', fake_download_file)
    monkeypatch.setattr(PaperlessConnector, 'upload_document', fake_upload_document_fails)

    app = _build_app()
    with TestClient(app) as client:
        response = client.post(
            '/webhooks/telegram',
            json=_media_payload(
                7003, 703,
                document={'file_id': 'pdf-fail-1', 'file_unique_id': 'fail-uniq-1', 'file_name': 'beleg_fail.pdf', 'mime_type': 'application/pdf', 'file_size': 128},
            ),
            headers=_telegram_headers(),
        )
        assert response.status_code == 200
        body = response.json()

        # Response indicates failure
        assert body.get('command_status') == 'UPLOAD_FAILED' or body.get('routing_status') not in {'DOCUMENT_ACCEPTED'}

        # At least one message sent to user
        assert len(sent_messages) >= 1
        # Error message contains "versuch" or failure indication
        error_msgs = [m for m in sent_messages if 'versuch' in m.lower() or 'fehler' in m.lower() or 'verarbeiten' in m.lower()]
        assert len(error_msgs) >= 1, f'Expected error reply to user, got: {sent_messages}'
