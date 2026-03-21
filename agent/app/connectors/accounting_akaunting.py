from __future__ import annotations

import logging

import httpx

from app.connectors.contracts import AccountingConnector

_PROBE_TIMEOUT = 8.0
_WRITE_TIMEOUT = 30.0

logger = logging.getLogger(__name__)


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

    async def get_categories(self, category_type: str | None = None) -> list[dict]:
        """Read-only: return Akaunting categories, optionally filtered by type.

        GET /api/categories?type=expense|income
        """
        params: dict[str, str] = {}
        if category_type:
            params['type'] = category_type
        try:
            async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT, auth=self._auth()) as client:
                response = await client.get(
                    f'{self.base_url}/api/categories',
                    headers=self._headers(),
                    params=params,
                )
                response.raise_for_status()
                data = response.json()
                items: list[dict] = data.get('data', data) if isinstance(data, dict) else data
                return items if isinstance(items, list) else []
        except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPStatusError) as exc:
            logger.warning('get_categories failed: %s', exc)
            return []

    async def search_or_create_contact(
        self,
        name: str,
        contact_type: str = 'vendor',
        email: str | None = None,
    ) -> dict:
        """Find an existing contact by name or create a new vendor contact.

        Returns the contact dict (with at least 'id').
        Raises on HTTP error from create call.
        """
        existing = await self.search_contacts(name=name)
        if existing:
            return existing[0]

        # Create new contact
        payload: dict = {
            'type': contact_type,
            'name': name,
            'currency_code': 'EUR',
            'enabled': True,
        }
        if email:
            payload['email'] = email

        async with httpx.AsyncClient(timeout=_WRITE_TIMEOUT, auth=self._auth()) as client:
            response = await client.post(
                f'{self.base_url}/api/contacts',
                headers={**self._headers(), 'Content-Type': 'application/json'},
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            return data.get('data', data) if isinstance(data, dict) else data

    async def create_bill_draft(
        self,
        data: dict,
        company_id: int = 1,
    ) -> dict:
        """Create an Eingangsrechnung (Bill) in Akaunting as 'draft' status.

        ALWAYS creates as draft — never as received or paid. This is PROPOSE_ONLY.

        data = {
            'vendor_name': str,               # required
            'bill_number': str | None,
            'billed_at': 'YYYY-MM-DD',
            'due_at': 'YYYY-MM-DD' | None,
            'amount': float,                  # gross total
            'currency_code': 'EUR',
            'category_name': str | None,      # matched against Akaunting categories
            'items': [{'name': str, 'quantity': 1, 'price': float}],
        }

        Returns: {'bill_id': int|None, 'contact_id': int|None, 'status': 'draft', ...}
        Raises: httpx.HTTPStatusError on API error.
        """
        vendor_name = str(data.get('vendor_name') or 'Unbekannter Lieferant')

        # 1. Find or create vendor contact
        contact = await self.search_or_create_contact(vendor_name, contact_type='vendor')
        contact_id = contact.get('id')

        # 2. Build bill payload
        items_raw = data.get('items') or []
        if not items_raw:
            # Build single item from amount
            items_raw = [{'name': vendor_name, 'quantity': 1, 'price': float(data.get('amount', 0))}]

        bill_items = [
            {
                'name': str(it.get('name') or vendor_name),
                'quantity': int(it.get('quantity') or 1),
                'price': float(it.get('price') or 0),
            }
            for it in items_raw
        ]

        bill_payload: dict = {
            'type': 'bill',
            'document_number': data.get('bill_number') or '',
            'status': 'draft',
            'issued_at': data.get('billed_at') or '',
            'due_at': data.get('due_at') or data.get('billed_at') or '',
            'currency_code': data.get('currency_code') or 'EUR',
            'currency_rate': 1,
            'contact_id': contact_id,
            'contact_name': vendor_name,
            'items': bill_items,
            'company_id': company_id,
        }

        if data.get('category_name'):
            bill_payload['category_name'] = data['category_name']

        async with httpx.AsyncClient(timeout=_WRITE_TIMEOUT, auth=self._auth()) as client:
            response = await client.post(
                f'{self.base_url}/api/documents',
                headers={**self._headers(), 'Content-Type': 'application/json'},
                json=bill_payload,
            )
            response.raise_for_status()
            resp_data = response.json()
            result = resp_data.get('data', resp_data) if isinstance(resp_data, dict) else resp_data
            bill_id = result.get('id') if isinstance(result, dict) else None
            logger.info('Akaunting bill draft created: id=%s vendor=%s', bill_id, vendor_name)
            return {
                'bill_id': bill_id,
                'contact_id': contact_id,
                'status': 'draft',
                'vendor_name': vendor_name,
                'currency_code': data.get('currency_code') or 'EUR',
                'raw': result,
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
        """Read-only search for banking transactions. GET only, no write.

        Note: Akaunting's /api/transactions?search=... returns 0 results for bare
        reference tokens (same issue as documents). Fix: fetch all transactions
        without a search param, then filter reference/contact/amount client-side.
        Date params (date_from/date_to) are passed server-side as they work correctly.
        """
        # Do NOT pass reference as search param — Akaunting returns 0 for bare tokens.
        # All field filtering happens client-side.
        params: dict[str, str] = {}
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
                # Client-side filters
                if reference:
                    ref_lower = reference.lower()
                    items = [
                        i for i in items
                        if ref_lower in (
                            i.get('reference') or i.get('number') or i.get('description') or ''
                        ).lower()
                    ]
                if contact_name:
                    cn_lower = contact_name.lower()
                    items = [
                        i for i in items
                        if cn_lower in (i.get('contact_name') or '').lower()
                        or cn_lower in (i.get('contact', {}) or {}).get('name', '').lower()
                        or cn_lower in (i.get('description') or '').lower()
                    ]
                if amount is not None:
                    tolerance = abs(amount) * 0.05
                    items = [
                        i for i in items
                        if abs(float(i.get('amount', 0) or 0) - amount) <= tolerance
                    ]
                return items[:10]
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

    async def create_invoice_draft(
        self,
        data: dict,
        company_id: int = 1,
    ) -> dict:
        """Create an Ausgangsrechnung (Invoice) in Akaunting as 'draft' status.

        data = {
            'customer_name': str,
            'invoice_number': str | None,
            'invoiced_at': 'YYYY-MM-DD',
            'due_at': 'YYYY-MM-DD' | None,
            'amount': float,
            'currency_code': 'EUR',
            'items': [{'name': str, 'quantity': 1, 'price': float}],
        }
        """
        customer_name = str(data.get('customer_name') or 'Unbekannter Kunde')
        contact = await self.search_or_create_contact(customer_name, contact_type='customer')
        contact_id = contact.get('id')

        items_raw = data.get('items') or []
        if not items_raw:
            items_raw = [{'name': data.get('service') or customer_name, 'quantity': 1, 'price': float(data.get('amount', 0))}]

        invoice_items = [
            {
                'name': str(it.get('name') or customer_name),
                'quantity': int(it.get('quantity') or 1),
                'price': float(it.get('price') or 0),
            }
            for it in items_raw
        ]

        payload: dict = {
            'type': 'invoice',
            'document_number': data.get('invoice_number') or '',
            'status': 'draft',
            'issued_at': data.get('invoiced_at') or '',
            'due_at': data.get('due_at') or data.get('invoiced_at') or '',
            'currency_code': data.get('currency_code') or 'EUR',
            'currency_rate': 1,
            'contact_id': contact_id,
            'contact_name': customer_name,
            'items': invoice_items,
            'company_id': company_id,
        }

        async with httpx.AsyncClient(timeout=_WRITE_TIMEOUT, auth=self._auth()) as client:
            response = await client.post(
                f'{self.base_url}/api/documents',
                headers={**self._headers(), 'Content-Type': 'application/json'},
                json=payload,
            )
            response.raise_for_status()
            resp_data = response.json()
            result = resp_data.get('data', resp_data) if isinstance(resp_data, dict) else resp_data
            invoice_id = result.get('id') if isinstance(result, dict) else None
            doc_number = result.get('document_number', '') if isinstance(result, dict) else ''
            logger.info('Akaunting invoice draft created: id=%s customer=%s', invoice_id, customer_name)
            return {
                'invoice_id': invoice_id,
                'document_number': doc_number,
                'contact_id': contact_id,
                'status': 'draft',
                'customer_name': customer_name,
            }

    async def get_open_items_summary(self) -> dict:
        """Aggregate unpaid invoices (receivables) and bills (payables)."""
        result: dict = {
            'receivables': [],
            'payables': [],
            'total_receivable': 0.0,
            'total_payable': 0.0,
        }
        try:
            # Unpaid invoices (Ausgangsrechnungen)
            invoices = await self.search_invoices()
            for inv in invoices:
                status = (inv.get('status') or '').lower()
                if status in ('draft', 'sent', 'viewed', 'partial'):
                    amount = float(inv.get('amount', inv.get('total', 0)) or 0)
                    due = inv.get('due_at') or ''
                    result['receivables'].append({
                        'contact': inv.get('contact_name') or '?',
                        'amount': amount,
                        'due_at': due,
                        'status': status,
                    })
                    result['total_receivable'] += amount

            # Unpaid bills (Eingangsrechnungen)
            bills = await self.search_bills()
            for bill in bills:
                status = (bill.get('status') or '').lower()
                if status in ('draft', 'received', 'partial'):
                    amount = float(bill.get('amount', bill.get('total', 0)) or 0)
                    due = bill.get('due_at') or ''
                    result['payables'].append({
                        'contact': bill.get('contact_name') or '?',
                        'amount': amount,
                        'due_at': due,
                        'status': status,
                    })
                    result['total_payable'] += amount
        except Exception as exc:
            logger.warning('get_open_items_summary failed: %s', exc)
        return result

    async def get_monthly_summary(self, year: int, month: int) -> dict:
        """Income and expense totals for a given month."""
        from calendar import monthrange
        last_day = monthrange(year, month)[1]
        date_from = f'{year:04d}-{month:02d}-01'
        date_to = f'{year:04d}-{month:02d}-{last_day:02d}'

        result: dict = {
            'month': f'{year:04d}-{month:02d}',
            'total_income': 0.0,
            'total_expense': 0.0,
            'profit': 0.0,
            'top_expenses': [],
        }
        try:
            txns = await self.search_transactions(date_from=date_from, date_to=date_to)
            expense_by_category: dict[str, float] = {}
            for tx in txns:
                tx_type = (tx.get('type') or '').lower()
                amount = float(tx.get('amount', 0) or 0)
                if tx_type == 'income':
                    result['total_income'] += amount
                elif tx_type == 'expense':
                    result['total_expense'] += amount
                    cat = tx.get('category', {})
                    cat_name = cat.get('name', 'Sonstiges') if isinstance(cat, dict) else 'Sonstiges'
                    expense_by_category[cat_name] = expense_by_category.get(cat_name, 0.0) + amount

            result['profit'] = round(result['total_income'] - result['total_expense'], 2)
            result['top_expenses'] = sorted(
                [{'category': k, 'amount': round(v, 2)} for k, v in expense_by_category.items()],
                key=lambda x: x['amount'],
                reverse=True,
            )[:5]
        except Exception as exc:
            logger.warning('get_monthly_summary failed: %s', exc)
        return result

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
