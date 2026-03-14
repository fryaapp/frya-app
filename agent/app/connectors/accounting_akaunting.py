from __future__ import annotations

import httpx

from app.connectors.contracts import AccountingConnector

_PROBE_TIMEOUT = 8.0


class AkauntingConnector(AccountingConnector):
    """Akaunting connector starts intentionally conservative.

    Financial truth is Akaunting. This connector exposes read and draft boundaries only.

    Auth: prefers HTTP Basic Auth (email + password). Falls back to Bearer token if set.
    Endpoints: uses /api/documents?search=type:bill|invoice (Akaunting v3 unified endpoint).
    """

    def __init__(
        self,
        base_url: str,
        token: str | None = None,
        email: str | None = None,
        password: str | None = None,
    ) -> None:
        self.base_url = base_url.rstrip('/')
        self.token = token
        self.email = email
        self.password = password

    def _auth(self) -> httpx.BasicAuth | None:
        """Return Basic Auth if credentials are set, else None."""
        if self.email and self.password:
            return httpx.BasicAuth(self.email, self.password)
        return None

    def _headers(self) -> dict[str, str]:
        headers = {'Accept': 'application/json'}
        if not (self.email and self.password) and self.token:
            headers['Authorization'] = f'Bearer {self.token}'
        return headers

    async def get_object(self, object_type: str, object_id: str) -> dict:
        async with httpx.AsyncClient(timeout=20, auth=self._auth()) as client:
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
        """Read-only search for bills (Eingangsrechnungen). GET only, no write.

        Uses /api/documents?search=type:bill (Akaunting v3 documents endpoint).
        """
        # Only pass type:bill to Akaunting – bare reference tokens cause HTTP 500.
        # Reference, contact_name and amount are filtered client-side below.
        params: dict[str, str] = {'search': 'type:bill'}
        if date_from:
            params['date_from'] = date_from
        if date_to:
            params['date_to'] = date_to
        try:
            async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT, auth=self._auth()) as client:
                response = await client.get(
                    f'{self.base_url}/api/documents',
                    headers=self._headers(),
                    params=params,
                )
                response.raise_for_status()
                data = response.json()
                items: list[dict] = data.get('data', data) if isinstance(data, dict) else data
                if not isinstance(items, list):
                    return []
                if reference:
                    ref_lower = reference.lower()
                    items = [
                        i for i in items
                        if ref_lower in (i.get('document_number') or i.get('number') or i.get('reference') or '').lower()
                    ]
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
        except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPStatusError):
            return []  # search_bills error boundary

    async def search_invoices(
        self,
        reference: str | None = None,
        amount: float | None = None,
        contact_name: str | None = None,
    ) -> list[dict]:
        """Read-only search for invoices (Ausgangsrechnungen). GET only, no write.

        Uses /api/documents?search=type:invoice (Akaunting v3 documents endpoint).
        """
        # Only pass type:invoice to Akaunting – bare reference tokens cause HTTP 500.
        # Reference, contact_name and amount are filtered client-side below.
        params: dict[str, str] = {'search': 'type:invoice'}
        try:
            async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT, auth=self._auth()) as client:
                response = await client.get(
                    f'{self.base_url}/api/documents',
                    headers=self._headers(),
                    params=params,
                )
                response.raise_for_status()
                data = response.json()
                items: list[dict] = data.get('data', data) if isinstance(data, dict) else data
                if not isinstance(items, list):
                    return []
                if reference:
                    ref_lower = reference.lower()
                    items = [
                        i for i in items
                        if ref_lower in (i.get('document_number') or i.get('number') or i.get('reference') or '').lower()
                    ]
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
        except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPStatusError):
            return []  # search_invoices error boundary

    async def search_contacts(self, name: str | None = None) -> list[dict]:
        """Read-only search for contacts. GET only, no write."""
        params: dict[str, str] = {}
        if name:
            params['search'] = name
        try:
            async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT, auth=self._auth()) as client:
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
        except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPStatusError):
            return []  # search_contacts error boundary

    async def search_transactions(
        self,
        reference: str | None = None,
        amount: float | None = None,
        contact_name: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> list[dict]:
        """Read-only search for banking transactions. GET only, no write."""
        params: dict[str, str] = {}
        if reference:
            params['search'] = reference
        if date_from:
            params['date_from'] = date_from
        if date_to:
            params['date_to'] = date_to
        try:
            async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT, auth=self._auth()) as client:
                response = await client.get(
                    f'{self.base_url}/api/transactions',
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
                        if abs(float(i.get('amount', 0) or 0) - amount) <= tolerance
                    ]
                return items[:5]
        except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPStatusError):
            return []

    async def search_accounts(self) -> list[dict]:
        """Read-only: return all bank accounts. GET only, no write."""
        try:
            async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT, auth=self._auth()) as client:
                response = await client.get(
                    f'{self.base_url}/api/accounts',
                    headers=self._headers(),
                )
                response.raise_for_status()
                data = response.json()
                items: list[dict] = data.get('data', data) if isinstance(data, dict) else data
                if not isinstance(items, list):
                    return []
                return items[:20]
        except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPStatusError):
            return []

    async def get_feed_status(self) -> dict:
        """Read-only: probe feed health — account count + total transaction count.

        Returns:
            {
                'reachable': bool,
                'source_url': str,
                'accounts_available': int,
                'transactions_total': int,
                'note': str,
            }
        V1.2: used to populate FeedStatus on every probe result.
        """
        status = {
            'reachable': False,
            'source_url': self.base_url,
            'accounts_available': 0,
            'transactions_total': 0,
            'note': '',
        }
        try:
            async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT, auth=self._auth()) as client:
                # Account count
                acc_resp = await client.get(
                    f'{self.base_url}/api/accounts',
                    headers=self._headers(),
                )
                acc_resp.raise_for_status()
                acc_data = acc_resp.json()
                acc_items = acc_data.get('data', acc_data) if isinstance(acc_data, dict) else acc_data
                acc_meta = acc_data.get('meta', {}) if isinstance(acc_data, dict) else {}
                status['accounts_available'] = (
                    acc_meta.get('total')
                    or (len(acc_items) if isinstance(acc_items, list) else 0)
                )

                # Transaction total — fetch with limit=1 just to read meta.total
                tx_resp = await client.get(
                    f'{self.base_url}/api/transactions',
                    headers=self._headers(),
                    params={'limit': '1'},
                )
                tx_resp.raise_for_status()
                tx_data = tx_resp.json()
                tx_items = tx_data.get('data', tx_data) if isinstance(tx_data, dict) else tx_data
                tx_meta = tx_data.get('meta', {}) if isinstance(tx_data, dict) else {}
                status['transactions_total'] = (
                    tx_meta.get('total')
                    or (len(tx_items) if isinstance(tx_items, list) else 0)
                )

                status['reachable'] = True
                status['note'] = (
                    f'Feed erreichbar. Konten: {status["accounts_available"]}, '
                    f'Transaktionen gesamt: {status["transactions_total"]}.'
                )
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            status['note'] = f'Feed nicht erreichbar: {exc}'
        except httpx.HTTPStatusError as exc:
            status['note'] = f'Feed HTTP-Fehler {exc.response.status_code}: {exc.response.text[:120]}'
        except Exception as exc:
            status['note'] = f'Feed-Fehler: {exc}'
        return status
