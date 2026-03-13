from __future__ import annotations

import httpx

from app.connectors.contracts import AccountingConnector

_PROBE_TIMEOUT = 8.0


class AkauntingConnector(AccountingConnector):
    """Akaunting connector starts intentionally conservative.

    Financial truth is Akaunting. This connector exposes read and draft boundaries only.
    """

    def __init__(self, base_url: str, token: str | None) -> None:
        self.base_url = base_url.rstrip('/')
        self.token = token

    def _headers(self) -> dict[str, str]:
        headers = {'Accept': 'application/json'}
        if self.token:
            headers['Authorization'] = f'Bearer {self.token}'
        return headers

    async def get_object(self, object_type: str, object_id: str) -> dict:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(
                f'{self.base_url}/api/{object_type}/{object_id}',
                headers=self._headers(),
            )
            response.raise_for_status()
            return response.json()

    async def create_booking_draft(self, payload: dict) -> dict:
        return {
            'status': 'stub',
            'message': 'create_booking_draft ist als sicherer Stub implementiert und fuehrt keine Buchung aus.',
            'payload': payload,
        }

    async def search_bills(
        self,
        reference: str | None = None,
        amount: float | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        contact_name: str | None = None,
    ) -> list[dict]:
        """Read-only search for bills (Eingangsrechnungen). GET only, no write."""
        params: dict[str, str] = {}
        if reference:
            params['search'] = reference
        if date_from:
            params['date_from'] = date_from
        if date_to:
            params['date_to'] = date_to
        try:
            async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT) as client:
                response = await client.get(
                    f'{self.base_url}/api/bills',
                    headers=self._headers(),
                    params=params,
                )
                response.raise_for_status()
                data = response.json()
                items: list[dict] = data.get('data', data) if isinstance(data, dict) else data
                if not isinstance(items, list):
                    return []
                if contact_name:
                    cn_lower = contact_name.lower()
                    items = [
                        i for i in items
                        if cn_lower in (i.get('contact_name') or '').lower()
                        or cn_lower in (i.get('contact', {}) or {}).get('name', '').lower()
                    ]
                if amount is not None:
                    tolerance = abs(amount) * 0.05
                    items = [
                        i for i in items
                        if abs(float(i.get('amount', i.get('total', 0)) or 0) - amount) <= tolerance
                    ]
                return items[:5]
        except httpx.ConnectError:
            return []
        except httpx.TimeoutException:
            return []

    async def search_invoices(
        self,
        reference: str | None = None,
        amount: float | None = None,
        contact_name: str | None = None,
    ) -> list[dict]:
        """Read-only search for invoices (Ausgangsrechnungen). GET only, no write."""
        params: dict[str, str] = {}
        if reference:
            params['search'] = reference
        try:
            async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT) as client:
                response = await client.get(
                    f'{self.base_url}/api/invoices',
                    headers=self._headers(),
                    params=params,
                )
                response.raise_for_status()
                data = response.json()
                items: list[dict] = data.get('data', data) if isinstance(data, dict) else data
                if not isinstance(items, list):
                    return []
                if contact_name:
                    cn_lower = contact_name.lower()
                    items = [
                        i for i in items
                        if cn_lower in (i.get('contact_name') or '').lower()
                        or cn_lower in (i.get('contact', {}) or {}).get('name', '').lower()
                    ]
                if amount is not None:
                    tolerance = abs(amount) * 0.05
                    items = [
                        i for i in items
                        if abs(float(i.get('amount', i.get('total', 0)) or 0) - amount) <= tolerance
                    ]
                return items[:5]
        except httpx.ConnectError:
            return []
        except httpx.TimeoutException:
            return []

    async def search_contacts(self, name: str | None = None) -> list[dict]:
        """Read-only search for contacts. GET only, no write."""
        params: dict[str, str] = {}
        if name:
            params['search'] = name
        try:
            async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT) as client:
                response = await client.get(
                    f'{self.base_url}/api/contacts',
                    headers=self._headers(),
                    params=params,
                )
                response.raise_for_status()
                data = response.json()
                items: list[dict] = data.get('data', data) if isinstance(data, dict) else data
                if not isinstance(items, list):
                    return []
                return items[:5]
        except httpx.ConnectError:
            return []
        except httpx.TimeoutException:
            return []
