"""EÜR + USt reports from frya_bookings."""
from __future__ import annotations

import logging
import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from app.accounting.repository import AccountingRepository

logger = logging.getLogger(__name__)


class EuerService:
    def __init__(self, repo: AccountingRepository) -> None:
        self._repo = repo

    async def generate_euer(self, tenant_id: uuid.UUID, year: int) -> dict:
        """Generate EÜR (Einnahmen-Überschuss-Rechnung) for a year."""
        date_from = date(year, 1, 1)
        date_to = date(year, 12, 31)
        bookings = await self._repo.list_bookings(
            tenant_id, date_from=date_from, date_to=date_to, status='BOOKED', limit=10000,
        )

        income_by_account: dict[str, Decimal] = {}
        expense_by_account: dict[str, Decimal] = {}

        for b in bookings:
            if b.booking_type == 'INCOME':
                key = f'{b.account_haben} {b.account_haben_name or ""}'.strip()
                income_by_account[key] = income_by_account.get(key, Decimal('0')) + b.gross_amount
            elif b.booking_type == 'EXPENSE':
                key = f'{b.account_soll} {b.account_soll_name or ""}'.strip()
                expense_by_account[key] = expense_by_account.get(key, Decimal('0')) + b.gross_amount

        total_income = sum(income_by_account.values(), Decimal('0'))
        total_expense = sum(expense_by_account.values(), Decimal('0'))
        profit = total_income - total_expense

        return {
            'year': year,
            'income': {k: float(v) for k, v in sorted(income_by_account.items())},
            'expenses': {k: float(v) for k, v in sorted(expense_by_account.items())},
            'total_income': float(total_income),
            'total_expenses': float(total_expense),
            'profit': float(profit),
            'booking_count': len(bookings),
        }

    async def generate_ust(self, tenant_id: uuid.UUID, year: int, quarter: int) -> dict:
        """Generate USt-Voranmeldung for a quarter."""
        month_start = (quarter - 1) * 3 + 1
        date_from = date(year, month_start, 1)
        month_end = quarter * 3
        if month_end == 12:
            date_to = date(year, 12, 31)
        else:
            date_to = date(year, month_end + 1, 1)
            from datetime import timedelta
            date_to = date_to - timedelta(days=1)

        bookings = await self._repo.list_bookings(
            tenant_id, date_from=date_from, date_to=date_to, status='BOOKED', limit=10000,
        )

        ust_collected = Decimal('0')  # Umsatzsteuer (from income)
        vst_deductible = Decimal('0')  # Vorsteuer (from expenses)

        for b in bookings:
            tax = b.tax_amount or Decimal('0')
            if b.booking_type == 'INCOME':
                ust_collected += tax
            elif b.booking_type == 'EXPENSE':
                vst_deductible += tax

        zahllast = ust_collected - vst_deductible

        return {
            'year': year,
            'quarter': quarter,
            'period': f'Q{quarter} {year}',
            'umsatzsteuer': float(ust_collected),
            'vorsteuer': float(vst_deductible),
            'zahllast': float(zahllast),
            'booking_count': len(bookings),
        }
