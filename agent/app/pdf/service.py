"""PDF generation via Gotenberg (HTML -> PDF)."""
from __future__ import annotations

import logging
from pathlib import Path
from datetime import date, timedelta

import httpx
from jinja2 import Environment, FileSystemLoader

logger = logging.getLogger(__name__)

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / 'templates'
_jinja_env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)), autoescape=True)

GOTENBERG_URL = 'http://frya-gotenberg:3000/forms/chromium/convert/html'

DUNNING_LEVELS = {
    1: 'Zahlungserinnerung',
    2: '1. Mahnung',
    3: '2. Mahnung',
    4: 'Letzte Mahnung',
}


class PdfService:
    """Render Jinja2 HTML templates and convert to PDF via Gotenberg."""

    async def generate_invoice_pdf(
        self, invoice: dict, items: list[dict], contact: dict, tenant: dict,
    ) -> bytes:
        """Generate a PDF for an invoice.

        Args:
            invoice: Invoice data (invoice_number, invoice_date, due_date,
                     net_amount, tax_amount, gross_amount, tax_rate, payment_days).
            items: Line items (description, quantity, unit, unit_price,
                   tax_rate, total_price).
            contact: Recipient (name, street, zip, city).
            tenant: Sender company (company_name, street, zip, city,
                    iban, bic, tax_id, tax_number).

        Returns:
            Raw PDF bytes.
        """
        template = _jinja_env.get_template('invoice.html')
        html = template.render(
            invoice=invoice, items=items,
            contact=contact, tenant=tenant,
        )
        return await self._convert(html)

    async def generate_dunning_pdf(
        self, contact: dict, open_items: list[dict], tenant: dict,
        level: int = 1, interest_rate: float = 0, fee: float = 0,
    ) -> bytes:
        """Generate a dunning letter PDF.

        Args:
            contact: Recipient (name, street, zip, city).
            open_items: List of overdue items (invoice_number/reference,
                        remaining_amount, due_date, days_overdue).
            tenant: Sender company info.
            level: Dunning level 1-4.
            interest_rate: Late-payment interest as percentage.
            fee: Flat dunning fee in EUR.

        Returns:
            Raw PDF bytes.
        """
        total_base = sum(i.get('remaining_amount', 0) for i in open_items)
        interest_amount = total_base * interest_rate / 100 if interest_rate else 0
        total = total_base + interest_amount + fee
        payment_deadline = (date.today() + timedelta(days=14)).strftime('%d.%m.%Y')

        template = _jinja_env.get_template('dunning.html')
        html = template.render(
            contact=contact, open_items=open_items, tenant=tenant,
            dunning_level=DUNNING_LEVELS.get(level, 'Mahnung'),
            interest_rate=interest_rate, interest_amount=interest_amount,
            fee=fee, total=total, payment_deadline=payment_deadline,
        )
        return await self._convert(html)

    async def _convert(self, html: str) -> bytes:
        """Send HTML to Gotenberg and return the resulting PDF bytes."""
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                GOTENBERG_URL,
                files={'file': ('index.html', html.encode('utf-8'), 'text/html')},
                data={
                    'marginTop': '1',
                    'marginBottom': '1',
                    'marginLeft': '0.8',
                    'marginRight': '0.8',
                },
            )
            resp.raise_for_status()
            return resp.content
