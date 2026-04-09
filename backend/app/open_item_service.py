"""Accounting Open Items Service — tracks receivables and payables."""
from __future__ import annotations

import logging
import uuid
from decimal import Decimal

from app.accounting.models import AccountingOpenItem, Booking
from app.accounting.repository import AccountingRepository

logger = logging.getLogger(__name__)


class AccountingOpenItemService:
    def __init__(self, repo: AccountingRepository) -> None:
        self._repo = repo

    async def create_from_booking(self, tenant_id: uuid.UUID, booking: Booking) -> AccountingOpenItem:
        """Create an open item from a booking (EXPENSE -> PAYABLE, INCOME -> RECEIVABLE)."""
        item_type = 'PAYABLE' if booking.booking_type == 'EXPENSE' else 'RECEIVABLE'
        return await self._repo.create_open_item(tenant_id, {
            'contact_id': booking.contact_id,
            'booking_id': booking.id,
            'case_id': booking.case_id,
            'item_type': item_type,
            'original_amount': booking.gross_amount,
            'currency': booking.currency,
            'invoice_number': booking.document_number,
            'invoice_date': booking.document_date,
            'due_date': None,  # Set from case due_date if available
        })

    async def record_payment(self, item_id: uuid.UUID, amount: Decimal) -> None:
        await self._repo.update_open_item_payment(item_id, amount)
        logger.info('Payment recorded: item=%s amount=%s', item_id, amount)

    async def list_payables(self, tenant_id: uuid.UUID) -> list[AccountingOpenItem]:
        return await self._repo.list_open_items(tenant_id, item_type='PAYABLE')

    async def list_receivables(self, tenant_id: uuid.UUID) -> list[AccountingOpenItem]:
        return await self._repo.list_open_items(tenant_id, item_type='RECEIVABLE')

    async def get_summary(self, tenant_id: uuid.UUID) -> dict:
        payables = await self.list_payables(tenant_id)
        receivables = await self.list_receivables(tenant_id)
        open_pay = [p for p in payables if p.status in ('OPEN', 'PARTIALLY_PAID', 'OVERDUE')]
        open_recv = [r for r in receivables if r.status in ('OPEN', 'PARTIALLY_PAID', 'OVERDUE')]
        return {
            'total_payable': float(sum(p.original_amount - p.paid_amount for p in open_pay)),
            'total_receivable': float(sum(r.original_amount - r.paid_amount for r in open_recv)),
            'payable_count': len(open_pay),
            'receivable_count': len(open_recv),
        }
