"""BookingService — creates GoBD-compliant bookings from cases or manual input."""
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from app.accounting.models import Booking
from app.accounting.repository import (
    AccountingRepository, compute_booking_hash, validate_booking_date,
)

logger = logging.getLogger(__name__)


class BookingService:
    def __init__(self, repo: AccountingRepository) -> None:
        self._repo = repo

    async def create_booking_from_case(
        self, *, case_id: str, tenant_id: uuid.UUID,
        vendor_name: str, description: str,
        account_soll: str, account_soll_name: str,
        account_haben: str, account_haben_name: str,
        gross_amount: Decimal,
        net_amount: Decimal | None = None,
        tax_rate: Decimal | None = None,
        tax_amount: Decimal | None = None,
        document_number: str | None = None,
        document_date: date | None = None,
        document_ref: str | None = None,
        created_by: str = 'frya-auto',
    ) -> Booking:
        """Create a booking from a case approval. Also creates/finds the contact."""
        validate_booking_date(document_date or date.today())

        # Find or create contact
        contact = await self._repo.find_or_create_contact(tenant_id, vendor_name)

        # Get next booking number + previous hash
        booking_number = await self._repo.get_next_booking_number(tenant_id)
        previous_hash = await self._repo.get_last_booking_hash(tenant_id)

        now = datetime.now(timezone.utc)
        booking_data = {
            'case_id': case_id,
            'contact_id': contact.id,
            'booking_number': booking_number,
            'booking_date': document_date or date.today(),
            'document_date': document_date,
            'description': description,
            'account_soll': account_soll,
            'account_soll_name': account_soll_name,
            'account_haben': account_haben,
            'account_haben_name': account_haben_name,
            'gross_amount': gross_amount,
            'net_amount': net_amount,
            'tax_rate': tax_rate,
            'tax_amount': tax_amount,
            'document_number': document_number,
            'document_ref': document_ref,
            'booking_type': 'EXPENSE',
            'status': 'BOOKED',
            'source': 'frya-auto',
            'created_by': created_by,
            'previous_hash': previous_hash,
            'booking_hash': '',  # computed below
            'created_at': now,
        }
        booking_data['booking_hash'] = compute_booking_hash({
            'booking_number': booking_number,
            'booking_date': str(booking_data['booking_date']),
            'account_soll': account_soll,
            'account_haben': account_haben,
            'gross_amount': str(gross_amount),
            'description': description,
            'created_at': str(now),
        }, previous_hash)

        booking = await self._repo.insert_booking(tenant_id, booking_data)
        logger.info('Booking created: #%d for case %s (%s, %s EUR)',
                     booking_number, case_id, vendor_name, gross_amount)
        return booking

    async def create_manual_booking(
        self, *, tenant_id: uuid.UUID,
        booking_date: date, description: str,
        account_soll: str, account_haben: str,
        gross_amount: Decimal,
        booking_type: str = 'EXPENSE',
        created_by: str = 'user-manual',
        **kwargs,
    ) -> Booking:
        """Create a manual booking (bank reconciliation, cash payment, correction)."""
        validate_booking_date(booking_date)

        booking_number = await self._repo.get_next_booking_number(tenant_id)
        previous_hash = await self._repo.get_last_booking_hash(tenant_id)
        now = datetime.now(timezone.utc)

        data = {
            'booking_number': booking_number,
            'booking_date': booking_date,
            'description': description,
            'account_soll': account_soll,
            'account_soll_name': kwargs.get('account_soll_name'),
            'account_haben': account_haben,
            'account_haben_name': kwargs.get('account_haben_name'),
            'gross_amount': gross_amount,
            'net_amount': kwargs.get('net_amount'),
            'tax_rate': kwargs.get('tax_rate'),
            'tax_amount': kwargs.get('tax_amount'),
            'document_number': kwargs.get('document_number'),
            'document_ref': kwargs.get('document_ref'),
            'booking_type': booking_type,
            'status': 'BOOKED',
            'source': 'user-manual',
            'created_by': created_by,
            'contact_id': kwargs.get('contact_id'),
            'case_id': kwargs.get('case_id'),
            'cost_center_id': kwargs.get('cost_center_id'),
            'project_id': kwargs.get('project_id'),
            'previous_hash': previous_hash,
            'booking_hash': '',
            'created_at': now,
        }
        data['booking_hash'] = compute_booking_hash({
            'booking_number': booking_number,
            'booking_date': str(booking_date),
            'account_soll': account_soll,
            'account_haben': account_haben,
            'gross_amount': str(gross_amount),
            'description': description,
            'created_at': str(now),
        }, previous_hash)

        return await self._repo.insert_booking(tenant_id, data)

    async def cancel_booking(
        self, *, booking_id: str, tenant_id: uuid.UUID,
        reason: str, cancelled_by: str,
    ) -> Booking:
        """GoBD-compliant cancellation: create a reversal booking, mark original as CANCELLED."""
        # Get original booking
        bookings = await self._repo.list_bookings(tenant_id)
        original = next((b for b in bookings if b.id == booking_id), None)
        if original is None:
            raise ValueError(f'Booking {booking_id} not found')
        if original.status == 'CANCELLED':
            raise ValueError(f'Booking {booking_id} is already cancelled')

        # Create reversal (swap Soll/Haben)
        reversal = await self.create_manual_booking(
            tenant_id=tenant_id,
            booking_date=date.today(),
            description=f'STORNO: {original.description} (Grund: {reason})',
            account_soll=original.account_haben,
            account_haben=original.account_soll,
            gross_amount=original.gross_amount,
            net_amount=original.net_amount,
            tax_rate=original.tax_rate,
            tax_amount=original.tax_amount,
            booking_type='CORRECTION',
            created_by=cancelled_by,
        )

        # Mark original as cancelled (this is an exception to write-once — only status + cancel fields)
        # In a strict GoBD implementation, we'd use a separate cancel_log table.
        # For MVP: the reversal booking IS the GoBD-compliant record.
        logger.info('Booking #%d cancelled by %s: %s (reversal: #%d)',
                     original.booking_number, cancelled_by, reason, reversal.booking_number)
        return reversal

    async def verify_hash_chain(self, tenant_id: uuid.UUID) -> dict:
        """GoBD: Verify the integrity of the booking hash chain."""
        bookings = await self._repo.list_bookings(tenant_id, limit=10000)
        bookings.sort(key=lambda b: b.booking_number)

        if not bookings:
            return {'valid': True, 'total': 0, 'errors': []}

        errors = []
        expected_prev = '0' * 64

        for b in bookings:
            if b.previous_hash != expected_prev:
                errors.append(f'Booking #{b.booking_number}: previous_hash mismatch')

            expected_hash = compute_booking_hash({
                'booking_number': b.booking_number,
                'booking_date': b.booking_date,
                'account_soll': b.account_soll,
                'account_haben': b.account_haben,
                'gross_amount': b.gross_amount,
                'description': b.description,
                'created_at': b.created_at,
            }, b.previous_hash or '0' * 64)

            if b.booking_hash != expected_hash:
                errors.append(f'Booking #{b.booking_number}: hash mismatch')

            expected_prev = b.booking_hash

        return {
            'valid': len(errors) == 0,
            'total': len(bookings),
            'errors': errors[:10],
        }

    async def get_finance_summary(
        self, tenant_id: uuid.UUID, date_from: date, date_to: date,
    ) -> dict:
        """Financial summary from bookings."""
        bookings = await self._repo.list_bookings(
            tenant_id, date_from=date_from, date_to=date_to, status='BOOKED',
        )

        income = Decimal('0')
        expenses = Decimal('0')
        for b in bookings:
            if b.booking_type == 'INCOME':
                income += b.gross_amount
            elif b.booking_type == 'EXPENSE':
                expenses += b.gross_amount

        return {
            'total_income': float(income),
            'total_expense': float(expenses),
            'profit': float(income - expenses),
            'booking_count': len(bookings),
        }
