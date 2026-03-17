import json

from fastapi.testclient import TestClient

from app.connectors.notifications_telegram import TelegramConnector
from tests.test_api_surface import _extract_csrf_token, _login_admin
from tests.test_telegram_clarification_v1 import _configure_env, _telegram_headers
from tests.test_telegram_media_ingress_v1 import _media_payload


class _FakeGraph:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def ainvoke(self, state: dict) -> dict:
        self.calls.append(state)
        return {
            'document_analysis': {'case_id': state['case_id'], 'document_ref': state['document_ref']},
            'output': {
                'status': 'INCOMPLETE',
                'open_item_id': 'analysis-open-item-1',
                'problem_id': None,
            },
        }


class _FailingGraph:
    async def ainvoke(self, state: dict) -> dict:
        raise RuntimeError('runtime kaputt')


def _patch_media_io(monkeypatch, content: bytes = b'%PDF-1.4 test pdf', *, mime_type: str = 'application/pdf', suffix: str = '.pdf') -> None:
    async def fake_send(self, message, disable_notification: bool = False):
        return {
            'ok': True,
            'status_code': 200,
            'body': json.dumps({'ok': True, 'result': {'message_id': 990}}),
            'json': {'ok': True, 'result': {'message_id': 990}},
        }

    async def fake_get_file_info(self, file_id: str):
        return {
            'ok': True,
            'status_code': 200,
            'body': json.dumps({'ok': True, 'result': {'file_path': f'documents/{file_id}{suffix}'}}),
            'json': {'ok': True, 'result': {'file_path': f'documents/{file_id}{suffix}'}},
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


def test_document_analyst_start_route_starts_runtime_and_completes_prep_items(tmp_path, monkeypatch):
    _configure_env(monkeypatch, tmp_path)
    monkeypatch.setenv('FRYA_TELEGRAM_BOT_TOKEN', 'telegram-test-token')
    _patch_media_io(monkeypatch)

    from tests.test_api_surface import _build_app

    app = _build_app()

    with TestClient(app) as client:
        fake_graph = _FakeGraph()
        client.app.state.graph = fake_graph
        response = client.post(
            '/webhooks/telegram',
            json=_media_payload(
                6501,
                651,
                document={
                    'file_id': 'startable-pdf-1',
                    'file_unique_id': 'startable-pdf-uniq-1',
                    'file_name': 'startbar.pdf',
                    'mime_type': 'application/pdf',
                    'file_size': 512,
                },
                caption='Telegram PDF fuer Analyse',
            ),
            headers=_telegram_headers(),
        )
        assert response.status_code == 200
        body = response.json()
        case_id = body['case_id']
        assert body['document_analyst_start']['analysis_start_status'] == 'DOCUMENT_ANALYST_START_READY'

        _login_admin(client)
        ui_case = client.get(f'/ui/cases/{case_id}')
        assert ui_case.status_code == 200
        assert 'Document Analyst Start' in ui_case.text
        csrf = _extract_csrf_token(ui_case.text)

        start_response = client.post(
            f'/inspect/cases/{case_id}/document-analyst-start',
            json={'note': 'Operator startet den konservativen Analyselauf.'},
            headers={'x-frya-csrf-token': csrf},
        )
        assert start_response.status_code == 200
        start_body = start_response.json()
        assert start_body['analysis_start_status'] == 'DOCUMENT_ANALYST_RUNTIME_STARTED'
        assert start_body['runtime_output_status'] == 'INCOMPLETE'
        assert fake_graph.calls
        assert fake_graph.calls[0]['case_id'] == case_id
        assert fake_graph.calls[0]['source'] == 'telegram_document_analyst_start'
        assert fake_graph.calls[0]['document_ref'] == body['document_analyst_context']['telegram_document_ref']

        case_json = client.get(f'/inspect/cases/{case_id}/json')
        assert case_json.status_code == 200
        case_body = case_json.json()
        assert case_body['document_analyst_start']['analysis_start_status'] == 'DOCUMENT_ANALYST_RUNTIME_STARTED'
        assert case_body['document_analyst_start']['runtime_open_item_id'] == 'analysis-open-item-1'
        prep_item = next(item for item in case_body['open_items'] if item['title'] == 'Document Analyst Eingang vorbereiten')
        queue_item = next(item for item in case_body['open_items'] if item['title'].startswith('[Telegram] Dokumenteingang pruefen'))
        assert prep_item['status'] == 'COMPLETED'
        assert queue_item['status'] == 'COMPLETED'

        ui_case_after = client.get(f'/ui/cases/{case_id}')
        assert ui_case_after.status_code == 200
        assert 'DOCUMENT_ANALYST_RUNTIME_STARTED' in ui_case_after.text


def test_document_analyst_start_route_blocks_duplicate_start(tmp_path, monkeypatch):
    _configure_env(monkeypatch, tmp_path)
    monkeypatch.setenv('FRYA_TELEGRAM_BOT_TOKEN', 'telegram-test-token')
    _patch_media_io(monkeypatch)

    from tests.test_api_surface import _build_app

    app = _build_app()

    with TestClient(app) as client:
        client.app.state.graph = _FakeGraph()
        response = client.post(
            '/webhooks/telegram',
            json=_media_payload(
                6601,
                661,
                document={
                    'file_id': 'dup-pdf-1',
                    'file_unique_id': 'dup-pdf-uniq-1',
                    'file_name': 'dup.pdf',
                    'mime_type': 'application/pdf',
                    'file_size': 512,
                },
            ),
            headers=_telegram_headers(),
        )
        case_id = response.json()['case_id']

        _login_admin(client)
        csrf = _extract_csrf_token(client.get(f'/ui/cases/{case_id}').text)

        first = client.post(
            f'/inspect/cases/{case_id}/document-analyst-start',
            json={'note': 'start 1'},
            headers={'x-frya-csrf-token': csrf},
        )
        assert first.status_code == 200

        duplicate = client.post(
            f'/inspect/cases/{case_id}/document-analyst-start',
            json={'note': 'start 2'},
            headers={'x-frya-csrf-token': csrf},
        )
        assert duplicate.status_code == 409
        assert 'bereits ausgelost' in duplicate.json()['detail']


def test_document_analyst_start_route_logs_failed_runtime(tmp_path, monkeypatch):
    _configure_env(monkeypatch, tmp_path)
    monkeypatch.setenv('FRYA_TELEGRAM_BOT_TOKEN', 'telegram-test-token')
    _patch_media_io(monkeypatch, content=b'jpeg-data', mime_type='image/jpeg', suffix='.jpg')

    from tests.test_api_surface import _build_app

    app = _build_app()

    with TestClient(app) as client:
        client.app.state.graph = _FailingGraph()
        response = client.post(
            '/webhooks/telegram',
            json=_media_payload(
                6701,
                671,
                photo=[
                    {
                        'file_id': 'photo-start-1',
                        'file_unique_id': 'photo-start-uniq-1',
                        'file_size': 128,
                        'width': 100,
                        'height': 100,
                    }
                ],
                caption='Foto fuer Analyst-Start',
            ),
            headers=_telegram_headers(),
        )
        assert response.status_code == 200
        case_id = response.json()['case_id']

        _login_admin(client)
        csrf = _extract_csrf_token(client.get(f'/ui/cases/{case_id}').text)
        failed = client.post(
            f'/inspect/cases/{case_id}/document-analyst-start',
            json={'note': 'start fail'},
            headers={'x-frya-csrf-token': csrf},
        )
        assert failed.status_code == 409
        assert 'Runtime konnte nicht gestartet werden' in failed.json()['detail']

        case_json = client.get(f'/inspect/cases/{case_id}/json')
        case_body = case_json.json()
        assert case_body['document_analyst_start']['analysis_start_status'] == 'DOCUMENT_ANALYST_RUNTIME_FAILED'
        assert case_body['document_analyst_start']['runtime_error'] == 'runtime kaputt'
