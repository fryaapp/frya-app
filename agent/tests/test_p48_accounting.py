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


@pytest.mark.asyncio
async def test_booking_service_create_from_case():
    from app.accounting.booking_service import BookingService
    from app.accounting.repository import AccountingRepository
    repo = AccountingRepository('memory://')
    svc = BookingService(repo)
    tid = uuid.uuid4()

    booking = await svc.create_booking_from_case(
        case_id=str(uuid.uuid4()), tenant_id=tid,
        vendor_name='Test Vendor GmbH', description='Wareneingang Test',
        account_soll='3300', account_soll_name='Wareneingang 19%',
        account_haben='1600', account_haben_name='Verbindlichkeiten LuL',
        gross_amount=Decimal('119.00'), net_amount=Decimal('100.00'),
        tax_rate=Decimal('19.00'), tax_amount=Decimal('19.00'),
        document_number='INV-001',
    )
    assert booking.booking_number == 1
    assert booking.gross_amount == Decimal('119.00')
    assert booking.booking_hash
    assert len(booking.booking_hash) == 64

    # Contact should have been created
    contacts = await repo.list_contacts(tid)
    assert len(contacts) == 1
    assert contacts[0].name == 'Test Vendor GmbH'


@pytest.mark.asyncio
async def test_booking_service_cancel():
    from app.accounting.booking_service import BookingService
    from app.accounting.repository import AccountingRepository
    repo = AccountingRepository('memory://')
    svc = BookingService(repo)
    tid = uuid.uuid4()

    booking = await svc.create_booking_from_case(
        case_id=str(uuid.uuid4()), tenant_id=tid,
        vendor_name='Cancel Test', description='Test',
        account_soll='3300', account_soll_name='Wareneingang',
        account_haben='1600', account_haben_name='Verbindlichkeiten',
        gross_amount=Decimal('50.00'),
    )

    reversal = await svc.cancel_booking(
        booking_id=booking.id, tenant_id=tid,
        reason='Falsch gebucht', cancelled_by='admin',
    )
    assert reversal.booking_type == 'CORRECTION'
    assert reversal.account_soll == '1600'  # Swapped
    assert reversal.account_haben == '3300'  # Swapped


@pytest.mark.asyncio
async def test_verify_hash_chain():
    from app.accounting.booking_service import BookingService
    from app.accounting.repository import AccountingRepository
    repo = AccountingRepository('memory://')
    svc = BookingService(repo)
    tid = uuid.uuid4()

    await svc.create_booking_from_case(
        case_id=str(uuid.uuid4()), tenant_id=tid,
        vendor_name='V1', description='B1',
        account_soll='3300', account_soll_name='W',
        account_haben='1600', account_haben_name='V',
        gross_amount=Decimal('100.00'),
    )
    await svc.create_booking_from_case(
        case_id=str(uuid.uuid4()), tenant_id=tid,
        vendor_name='V2', description='B2',
        account_soll='4200', account_soll_name='M',
        account_haben='1200', account_haben_name='B',
        gross_amount=Decimal('50.00'),
    )

    result = await svc.verify_hash_chain(tid)
    assert result['valid'] is True
    assert result['total'] == 2


@pytest.mark.asyncio
async def test_contact_service():
    from app.accounting.contact_service import ContactService
    from app.accounting.repository import AccountingRepository
    repo = AccountingRepository('memory://')
    svc = ContactService(repo)
    tid = uuid.uuid4()

    c = await svc.find_or_create_from_analysis(tid, {'sender': 'LUMO UG'})
    assert c.name == 'LUMO UG'
    assert c.contact_type == 'VENDOR'


@pytest.mark.asyncio
async def test_open_item_from_booking():
    from app.accounting.booking_service import BookingService
    from app.accounting.open_item_service import AccountingOpenItemService
    from app.accounting.repository import AccountingRepository
    repo = AccountingRepository('memory://')
    booking_svc = BookingService(repo)
    oi_svc = AccountingOpenItemService(repo)
    tid = uuid.uuid4()

    booking = await booking_svc.create_booking_from_case(
        case_id=str(uuid.uuid4()), tenant_id=tid,
        vendor_name='OI Test GmbH', description='Test',
        account_soll='3300', account_soll_name='Wareneingang',
        account_haben='1600', account_haben_name='Verbindlichkeiten',
        gross_amount=Decimal('100.00'),
    )
    oi = await oi_svc.create_from_booking(tid, booking)
    assert oi.item_type == 'PAYABLE'
    assert oi.original_amount == Decimal('100.00')
    assert oi.status == 'OPEN'


@pytest.mark.asyncio
async def test_open_item_summary():
    from app.accounting.booking_service import BookingService
    from app.accounting.open_item_service import AccountingOpenItemService
    from app.accounting.repository import AccountingRepository
    repo = AccountingRepository('memory://')
    booking_svc = BookingService(repo)
    oi_svc = AccountingOpenItemService(repo)
    tid = uuid.uuid4()

    b = await booking_svc.create_booking_from_case(
        case_id=str(uuid.uuid4()), tenant_id=tid,
        vendor_name='Summary Test', description='T',
        account_soll='3300', account_soll_name='W',
        account_haben='1600', account_haben_name='V',
        gross_amount=Decimal('200.00'),
    )
    await oi_svc.create_from_booking(tid, b)
    summary = await oi_svc.get_summary(tid)
    assert summary['total_payable'] == 200.0
    assert summary['payable_count'] == 1


@pytest.mark.asyncio
async def test_create_invoice():
    from app.accounting.invoice_service import InvoiceService
    from app.accounting.repository import AccountingRepository
    repo = AccountingRepository('memory://')
    svc = InvoiceService(repo)
    tid = uuid.uuid4()

    contact = await repo.find_or_create_contact(tid, 'Kunde A')
    invoice = await svc.create_invoice(
        tenant_id=tid, contact_id=contact.id,
        items=[
            {'description': 'Beratung', 'quantity': 2, 'unit_price': 100, 'tax_rate': 19},
            {'description': 'Material', 'quantity': 1, 'unit_price': 50, 'tax_rate': 19},
        ],
    )
    assert invoice.invoice_number.startswith('RE-')
    assert invoice.net_total == Decimal('250')
    assert invoice.gross_total == Decimal('297.50')


@pytest.mark.asyncio
async def test_euer_report():
    from app.accounting.booking_service import BookingService
    from app.accounting.euer_service import EuerService
    from app.accounting.repository import AccountingRepository
    repo = AccountingRepository('memory://')
    booking_svc = BookingService(repo)
    euer_svc = EuerService(repo)
    tid = uuid.uuid4()

    await booking_svc.create_booking_from_case(
        case_id=str(uuid.uuid4()), tenant_id=tid,
        vendor_name='Expense Corp', description='Büromaterial',
        account_soll='4210', account_soll_name='Bürobedarf',
        account_haben='1600', account_haben_name='Verbindlichkeiten',
        gross_amount=Decimal('119.00'), tax_amount=Decimal('19.00'),
    )

    report = await euer_svc.generate_euer(tid, date.today().year)
    assert report['total_expenses'] == 119.0
    assert report['profit'] == -119.0


@pytest.mark.asyncio
async def test_ust_voranmeldung():
    from app.accounting.booking_service import BookingService
    from app.accounting.euer_service import EuerService
    from app.accounting.repository import AccountingRepository
    repo = AccountingRepository('memory://')
    booking_svc = BookingService(repo)
    euer_svc = EuerService(repo)
    tid = uuid.uuid4()

    await booking_svc.create_booking_from_case(
        case_id=str(uuid.uuid4()), tenant_id=tid,
        vendor_name='USt Test', description='Einkauf',
        account_soll='3300', account_soll_name='Wareneingang',
        account_haben='1600', account_haben_name='Verbindlichkeiten',
        gross_amount=Decimal('119.00'), tax_amount=Decimal('19.00'),
    )

    quarter = (date.today().month - 1) // 3 + 1
    report = await euer_svc.generate_ust(tid, date.today().year, quarter)
    assert report['vorsteuer'] == 19.0
    assert report['zahllast'] == -19.0


@pytest.mark.asyncio
async def test_context_assembly_includes_buchhaltung():
    """Context assembly should include [BUCHHALTUNG] block when accounting repo is provided."""
    from app.memory_curator.service import MemoryCuratorService
    from app.accounting.repository import AccountingRepository
    from app.accounting.booking_service import BookingService
    from app.case_engine.repository import CaseRepository
    from pathlib import Path
    import tempfile

    acct_repo = AccountingRepository('memory://')
    case_repo = CaseRepository('memory://')
    tid = uuid.uuid4()

    # Create a booking
    svc = BookingService(acct_repo)
    await svc.create_booking_from_case(
        case_id=str(uuid.uuid4()), tenant_id=tid,
        vendor_name='Context Test', description='Test Buchung',
        account_soll='3300', account_soll_name='Wareneingang',
        account_haben='1600', account_haben_name='Verbindlichkeiten',
        gross_amount=Decimal('50.00'),
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        mem_svc = MemoryCuratorService(
            data_dir=Path(tmpdir),
            case_repository=case_repo,
            accounting_repository=acct_repo,
        )
        ctx = await mem_svc.get_context_assembly(tid)
    assert '[BUCHHALTUNG]' in ctx
    assert 'Test Buchung' in ctx
    assert '50.00' in ctx or '50.0' in ctx


def test_communicator_prompt_has_buchhaltung():
    from app.telegram.communicator.prompts import COMMUNICATOR_SYSTEM_PROMPT
    assert 'Buchungsjournal' in COMMUNICATOR_SYSTEM_PROMPT
    assert 'BUCHHALTUNG' in COMMUNICATOR_SYSTEM_PROMPT
