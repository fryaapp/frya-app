"""Invoice Service — create, finalize, and generate PDF invoices."""
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from app.accounting.models import Invoice, InvoiceItem
from app.accounting.repository import AccountingRepository

logger = logging.getLogger(__name__)


class InvoiceService:
    def __init__(self, repo: AccountingRepository) -> None:
        self._repo = repo

    async def create_invoice(
        self, *, tenant_id: uuid.UUID, contact_id: str,
        items: list[dict], due_date: date | None = None,
        header_text: str | None = None, footer_text: str | None = None,
    ) -> Invoice:
        """Create a draft invoice with line items."""
        invoice_number = await self._repo.get_next_invoice_number(tenant_id)

        net_total = Decimal('0')
        tax_total = Decimal('0')
        for item in items:
            qty = Decimal(str(item.get('quantity', 1)))
            price = Decimal(str(item['unit_price']))
            rate = Decimal(str(item.get('tax_rate', 19)))
            net = qty * price
            tax = net * rate / 100
            item['net_amount'] = net
            item['tax_amount'] = tax
            item['gross_amount'] = net + tax
            net_total += net
            tax_total += tax

        invoice = await self._repo.create_invoice(tenant_id, {
            'contact_id': contact_id,
            'invoice_number': invoice_number,
            'invoice_date': date.today(),
            'due_date': due_date,
            'net_total': net_total,
            'tax_total': tax_total,
            'gross_total': net_total + tax_total,
            'header_text': header_text,
            'footer_text': footer_text,
        })

        logger.info('Invoice %s created: %s EUR', invoice_number, net_total + tax_total)
        return invoice

    async def list_invoices(self, tenant_id: uuid.UUID) -> list[Invoice]:
        return await self._repo.list_invoices(tenant_id)
