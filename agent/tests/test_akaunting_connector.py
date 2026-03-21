"""Test: AkauntingConnector.create_bill_draft() and related methods."""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call
from decimal import Decimal

import httpx

from app.connectors.accounting_akaunting import AkauntingConnector
from app.booking.approval_service import skr03_to_akaunting_category


def _connector() -> AkauntingConnector:
    return AkauntingConnector(
        base_url='http://akaunting.test',
        email='admin@test.de',
        password='secret',
    )


class _FakeResponse:
    def __init__(self, status_code=200, data=None):
        self.status_code = status_code
        self._data = data or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(f'HTTP {self.status_code}', request=MagicMock(), response=MagicMock(status_code=self.status_code))

    def json(self):
        return self._data


def _shared_fake_client(responses: list):
    """Return a factory that shares a single response iterator across all client instances."""
    _iter = iter(responses)

    class _Client:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def get(self, url, **kw): return next(_iter)
        async def post(self, url, **kw): return next(_iter)

    return lambda **kw: _Client()


@pytest.mark.asyncio
async def test_create_bill_draft_vendor_exists_no_contact_created(monkeypatch):
    """If vendor found in contacts → no POST contact, just POST bill."""
    responses = [
        _FakeResponse(200, {'data': [{'id': 7, 'name': 'Hetzner Online GmbH', 'type': 'vendor'}]}),  # GET contacts
        _FakeResponse(200, {'data': {'id': 101, 'type': 'bill', 'status': 'draft'}}),               # POST bill
    ]
    monkeypatch.setattr(httpx, 'AsyncClient', _shared_fake_client(responses))

    connector = _connector()
    result = await connector.create_bill_draft({
        'vendor_name': 'Hetzner Online GmbH',
        'bill_number': 'RE-2026-001',
        'billed_at': '2026-03-01',
        'amount': 6.38,
        'currency_code': 'EUR',
    })

    assert result['status'] == 'draft'
    assert result['bill_id'] == 101
    assert result['contact_id'] == 7


@pytest.mark.asyncio
async def test_create_bill_draft_vendor_missing_creates_contact(monkeypatch):
    """If vendor not found → POST contact first, then POST bill."""
    responses = [
        _FakeResponse(200, {'data': []}),                                                              # GET contacts (empty)
        _FakeResponse(200, {'data': {'id': 12, 'name': 'Neuer Vendor GmbH', 'type': 'vendor'}}),     # POST contact
        _FakeResponse(200, {'data': {'id': 202, 'type': 'bill', 'status': 'draft'}}),                # POST bill
    ]
    monkeypatch.setattr(httpx, 'AsyncClient', _shared_fake_client(responses))

    connector = _connector()
    result = await connector.create_bill_draft({
        'vendor_name': 'Neuer Vendor GmbH',
        'amount': 100.00,
        'currency_code': 'EUR',
    })

    assert result['bill_id'] == 202
    assert result['contact_id'] == 12


@pytest.mark.asyncio
async def test_create_bill_draft_always_draft_status(monkeypatch):
    """Bill payload always has status='draft' and type='bill'."""
    bill_payload_sent = []
    _get_resp = _FakeResponse(200, {'data': [{'id': 3, 'name': 'Test GmbH'}]})
    _post_resp = _FakeResponse(200, {'data': {'id': 303, 'status': 'draft'}})

    class CapturingClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass

        async def get(self, url, **kw):
            return _get_resp

        async def post(self, url, **kwargs):
            body = kwargs.get('json') or {}
            bill_payload_sent.append(body)
            return _post_resp

    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: CapturingClient())

    connector = _connector()
    await connector.create_bill_draft({'vendor_name': 'Test GmbH', 'amount': 50.0})

    assert len(bill_payload_sent) == 1
    assert bill_payload_sent[0].get('status') == 'draft'
    assert bill_payload_sent[0].get('type') == 'bill'


@pytest.mark.asyncio
async def test_get_categories_returns_list(monkeypatch):
    """get_categories() returns category list."""
    class CatClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def get(self, url, **kw):
            return _FakeResponse(200, {'data': [
                {'id': 1, 'name': 'Telekommunikation', 'type': 'expense'},
                {'id': 2, 'name': 'Miete', 'type': 'expense'},
            ]})

    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: CatClient())

    connector = _connector()
    cats = await connector.get_categories()
    assert len(cats) == 2
    assert cats[0]['name'] == 'Telekommunikation'


@pytest.mark.asyncio
async def test_create_bill_draft_category_name_in_payload(monkeypatch):
    """category_name is included in bill payload when provided."""
    payload_sent = []

    class CapturingClient:
        def __init__(self):
            self._get_called = False

        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass

        async def get(self, url, **kw):
            return _FakeResponse(200, {'data': [{'id': 5, 'name': 'Telco AG'}]})

        async def post(self, url, **kw):
            payload_sent.append(kw.get('json') or {})
            return _FakeResponse(200, {'data': {'id': 500, 'status': 'draft'}})

    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: CapturingClient())

    connector = _connector()
    await connector.create_bill_draft({
        'vendor_name': 'Telco AG',
        'amount': 29.99,
        'category_name': 'Telekommunikation',
    })

    assert payload_sent[0].get('category_name') == 'Telekommunikation'


def test_skr03_to_category_4920():
    assert skr03_to_akaunting_category('4920') == 'Telekommunikation'


def test_skr03_to_category_4210():
    assert skr03_to_akaunting_category('4210') == 'Miete'


def test_skr03_to_category_unknown():
    assert skr03_to_akaunting_category('9999') == 'Sonstiges'
