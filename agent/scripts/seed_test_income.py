"""Seed test income bookings + open items for real-testing."""
import asyncio
import uuid
from datetime import date
from decimal import Decimal


async def main():
    from app.dependencies import get_accounting_repository
    from app.accounting.booking_service import BookingService
    from app.accounting.open_item_service import AccountingOpenItemService
    from app.case_engine.tenant_resolver import resolve_tenant_id

    tid_str = await resolve_tenant_id()
    if not tid_str:
        print('No tenant')
        return

    tid = uuid.UUID(tid_str)
    repo = get_accounting_repository()
    booking_svc = BookingService(repo)
    oi_svc = AccountingOpenItemService(repo)

    # Check if income bookings already exist
    existing = await repo.list_bookings(tid, limit=1000)
    if any(b.booking_type == 'INCOME' for b in existing):
        print('Income bookings already exist, skipping seed')
        return

    test_invoices = [
        {
            'contact_name': 'Anna Schmidt',
            'description': 'Einzelcoaching 60min — März 2026',
            'gross_amount': Decimal('120.00'),
            'net_amount': Decimal('100.84'),
            'tax_rate': Decimal('19.0'),
            'tax_amount': Decimal('19.16'),
            'account_soll': '1400',
            'account_soll_name': 'Forderungen aus LuL',
            'account_haben': '7000',
            'account_haben_name': 'Umsatzerlöse 19%',
            'document_number': 'RE-2026-001',
            'booking_date': date(2026, 3, 10),
        },
        {
            'contact_name': 'Praxis Dr. Weber',
            'description': 'Gruppencoaching 4x90min — Februar 2026',
            'gross_amount': Decimal('480.00'),
            'net_amount': Decimal('403.36'),
            'tax_rate': Decimal('19.0'),
            'tax_amount': Decimal('76.64'),
            'account_soll': '1400',
            'account_soll_name': 'Forderungen aus LuL',
            'account_haben': '7000',
            'account_haben_name': 'Umsatzerlöse 19%',
            'document_number': 'RE-2026-002',
            'booking_date': date(2026, 2, 28),
        },
        {
            'contact_name': 'Coaching Institut Süd GmbH',
            'description': 'Workshop Schattenarbeit — Tagessatz',
            'gross_amount': Decimal('1200.00'),
            'net_amount': Decimal('1008.40'),
            'tax_rate': Decimal('19.0'),
            'tax_amount': Decimal('191.60'),
            'account_soll': '1400',
            'account_soll_name': 'Forderungen aus LuL',
            'account_haben': '7000',
            'account_haben_name': 'Umsatzerlöse 19%',
            'document_number': 'RE-2026-003',
            'booking_date': date(2026, 3, 15),
        },
        {
            'contact_name': 'Anna Schmidt',
            'description': 'Einzelcoaching 60min — Februar 2026',
            'gross_amount': Decimal('120.00'),
            'net_amount': Decimal('100.84'),
            'tax_rate': Decimal('19.0'),
            'tax_amount': Decimal('19.16'),
            'account_soll': '1400',
            'account_soll_name': 'Forderungen aus LuL',
            'account_haben': '7000',
            'account_haben_name': 'Umsatzerlöse 19%',
            'document_number': 'RE-2026-004',
            'booking_date': date(2026, 2, 15),
        },
    ]

    for inv in test_invoices:
        contact_name = inv.pop('contact_name')
        contact = await repo.find_or_create_contact(tid, contact_name, contact_type='CUSTOMER')
        booking = await booking_svc.create_manual_booking(
            tenant_id=tid,
            booking_date=inv['booking_date'],
            description=inv['description'],
            account_soll=inv['account_soll'],
            account_haben=inv['account_haben'],
            gross_amount=inv['gross_amount'],
            booking_type='INCOME',
            created_by='test-seed',
            contact_id=contact.id,
            net_amount=inv.get('net_amount'),
            tax_rate=inv.get('tax_rate'),
            tax_amount=inv.get('tax_amount'),
            document_number=inv.get('document_number'),
            account_soll_name=inv.get('account_soll_name'),
            account_haben_name=inv.get('account_haben_name'),
        )
        print(f'  Created: #{booking.booking_number} {contact_name} — {inv["gross_amount"]} EUR (INCOME)')

        # Create open item
        oi = await oi_svc.create_from_booking(tid, booking)
        print(f'    Open Item: {oi.item_type} {oi.original_amount} EUR')

    # Mark some as paid
    all_items = await repo.list_open_items(tid, item_type='RECEIVABLE')
    for item in all_items:
        # Praxis Weber (RE-2026-002) and Anna Schmidt Feb (RE-2026-004) are paid
        if item.invoice_number in ('RE-2026-002', 'RE-2026-004'):
            await repo.update_open_item_payment(uuid.UUID(item.id), item.original_amount)
            print(f'    Marked PAID: {item.invoice_number}')

    print('\nDone!')


if __name__ == '__main__':
    asyncio.run(main())
