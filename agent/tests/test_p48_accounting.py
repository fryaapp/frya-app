"""Tests for P-48: Accounting tables + repository."""
import pytest
import uuid
from datetime import date
from decimal import Decimal


@pytest.mark.asyncio
async def test_accounting_repo_initialize():
    from app.accounting.repository import AccountingRepository
    repo = AccountingRepository('memory://')
    await repo.initialize()  # Should not raise


@pytest.mark.asyncio
async def test_skr03_seed():
    from app.accounting.repository import AccountingRepository
    repo = AccountingRepository('memory://')
    tid = uuid.uuid4()
    count = await repo.seed_skr03(tid)
    assert count == 36  # 36 accounts in SKR03_SEED
    accounts = await repo.list_accounts(tid)
    assert len(accounts) == 36
    assert any(a.account_number == '3300' for a in accounts)


@pytest.mark.asyncio
async def test_booking_hash_chain():
    from app.accounting.repository import compute_booking_hash
    h1 = compute_booking_hash({
        'booking_number': 1, 'booking_date': '2026-01-01',
        'account_soll': '3300', 'account_haben': '1600',
        'gross_amount': '100.00', 'description': 'Test',
        'created_at': '2026-01-01 10:00:00',
    }, '0' * 64)
    assert len(h1) == 64
    h2 = compute_booking_hash({
        'booking_number': 2, 'booking_date': '2026-01-02',
        'account_soll': '4200', 'account_haben': '1200',
        'gross_amount': '50.00', 'description': 'Miete',
        'created_at': '2026-01-02 10:00:00',
    }, h1)
    assert h2 != h1


@pytest.mark.asyncio
async def test_booking_number_sequence():
    from app.accounting.repository import AccountingRepository
    repo = AccountingRepository('memory://')
    tid = uuid.uuid4()
    n1 = await repo.get_next_booking_number(tid)
    assert n1 == 1


def test_validate_booking_date_future():
    from app.accounting.repository import validate_booking_date
    from datetime import timedelta
    with pytest.raises(ValueError, match='Zukunft'):
        validate_booking_date(date.today() + timedelta(days=1))


def test_validate_booking_date_too_old():
    from app.accounting.repository import validate_booking_date
    from datetime import timedelta
    with pytest.raises(ValueError, match='90 Tage'):
        validate_booking_date(date.today() - timedelta(days=91))


def test_validate_booking_date_ok():
    from app.accounting.repository import validate_booking_date
    validate_booking_date(date.today())  # Should not raise


@pytest.mark.asyncio
async def test_find_or_create_contact():
    from app.accounting.repository import AccountingRepository
    repo = AccountingRepository('memory://')
    tid = uuid.uuid4()
    c1 = await repo.find_or_create_contact(tid, 'Test GmbH')
    c2 = await repo.find_or_create_contact(tid, 'test gmbh')  # case-insensitive
    assert c1.id == c2.id


@pytest.mark.asyncio
async def test_insert_and_list_bookings():
    from app.accounting.repository import AccountingRepository, compute_booking_hash
    repo = AccountingRepository('memory://')
    tid = uuid.uuid4()

    prev_hash = await repo.get_last_booking_hash(tid)
    data = {
        'booking_number': 1, 'booking_date': date.today(),
        'description': 'Test booking', 'account_soll': '3300',
        'account_haben': '1600', 'gross_amount': Decimal('119.00'),
        'net_amount': Decimal('100.00'), 'tax_rate': Decimal('19.00'),
        'tax_amount': Decimal('19.00'), 'booking_type': 'EXPENSE',
        'booking_hash': compute_booking_hash({
            'booking_number': 1, 'booking_date': str(date.today()),
            'account_soll': '3300', 'account_haben': '1600',
            'gross_amount': '119.00', 'description': 'Test booking',
            'created_at': '2026-01-01',
        }, prev_hash),
    }
    booking = await repo.insert_booking(tid, data)
    assert booking.booking_number == 1
    assert booking.gross_amount == Decimal('119.00')

    bookings = await repo.list_bookings(tid)
    assert len(bookings) == 1
