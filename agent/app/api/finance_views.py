"""API endpoint for financial summary."""
from __future__ import annotations

import logging
import uuid
from datetime import date
from decimal import Decimal
from enum import Enum

from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth.dependencies import require_authenticated
from app.auth.models import AuthUser

logger = logging.getLogger(__name__)
router = APIRouter(prefix='/api/v1/finance', tags=['finance'])


async def _resolve_tenant() -> uuid.UUID:
    from app.case_engine.tenant_resolver import resolve_tenant_id
    tid = await resolve_tenant_id()
    if not tid:
        raise HTTPException(status_code=503, detail='tenant_unavailable')
    return uuid.UUID(tid)


def _get_repo():
    from app.dependencies import get_accounting_repository
    return get_accounting_repository()


class Period(str, Enum):
    month = 'month'
    quarter = 'quarter'
    year = 'year'


def _period_range(period: Period) -> tuple[date, date]:
    """Return (date_from, date_to) for the requested period relative to today."""
    today = date.today()
    if period == Period.month:
        date_from = today.replace(day=1)
    elif period == Period.quarter:
        q_month = ((today.month - 1) // 3) * 3 + 1
        date_from = today.replace(month=q_month, day=1)
    else:  # year
        date_from = today.replace(month=1, day=1)
    return date_from, today


@router.get('/summary')
async def get_finance_summary(
    user: AuthUser = Depends(require_authenticated),
    period: Period = Query(Period.month, description='Zeitraum: month, quarter oder year'),
) -> dict:
    """Financial summary: income, expenses, open receivables/payables, overdue."""
    tenant_id = await _resolve_tenant()
    date_from, date_to = _period_range(period)

    repo = _get_repo()

    # --- bookings summary ---
    from app.accounting.booking_service import BookingService
    svc = BookingService(repo)
    summary = await svc.get_finance_summary(tenant_id, date_from, date_to)

    # --- open items ---
    open_receivables = Decimal('0')
    open_payables = Decimal('0')
    overdue_count = 0
    overdue_amount = Decimal('0')
    try:
        open_items = await repo.list_open_items(tenant_id)
        today = date.today()
        for item in open_items:
            if item.status in ('PAID', 'CANCELLED'):
                continue
            remaining = item.original_amount - (item.paid_amount or Decimal('0'))
            if item.item_type == 'RECEIVABLE':
                open_receivables += remaining
            elif item.item_type == 'PAYABLE':
                open_payables += remaining
            if (
                item.status in ('OPEN', 'PARTIALLY_PAID')
                and item.due_date is not None
                and item.due_date < today
            ):
                overdue_count += 1
                overdue_amount += remaining
    except Exception as exc:
        logger.warning('Finance summary: failed to fetch open items: %s', exc)

    return {
        'period': period.value,
        'income': summary['total_income'],
        'expenses': summary['total_expense'],
        'open_receivables': float(open_receivables),
        'open_payables': float(open_payables),
        'overdue_count': overdue_count,
        'overdue_amount': float(overdue_amount),
    }
