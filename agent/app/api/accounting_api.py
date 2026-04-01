"""P-48: Accounting API endpoints."""
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth.dependencies import require_authenticated
from app.auth.models import AuthUser

logger = logging.getLogger(__name__)

router = APIRouter(prefix='/api/v1', tags=['accounting'])


async def _resolve_tenant() -> uuid.UUID:
    from app.case_engine.tenant_resolver import resolve_tenant_id
    tid = await resolve_tenant_id()
    if not tid:
        raise HTTPException(status_code=503, detail='tenant_unavailable')
    return uuid.UUID(tid)


def _get_repo():
    from app.dependencies import get_accounting_repository
    return get_accounting_repository()


def _get_booking_svc():
    from app.accounting.booking_service import BookingService
    return BookingService(_get_repo())


# ── Request/Response Models ──────────────────────────────────────────────────

class BookingCreateRequest(BaseModel):
    booking_date: str  # YYYY-MM-DD
    description: str
    account_soll: str
    account_haben: str
    gross_amount: float
    net_amount: float | None = None
    tax_rate: float | None = None
    tax_amount: float | None = None
    booking_type: str = 'EXPENSE'
    document_number: str | None = None
    contact_name: str | None = None

class PaymentRequest(BaseModel):
    amount: float

class InvoiceCreateRequest(BaseModel):
    contact_name: str
    items: list[dict]
    due_date: str | None = None
    header_text: str | None = None
    footer_text: str | None = None

class ContactCreateRequest(BaseModel):
    name: str
    contact_type: str = 'VENDOR'
    email: str | None = None
    phone: str | None = None
    tax_id: str | None = None
    iban: str | None = None


# ── Bookings ─────────────────────────────────────────────────────────────────

@router.post('/bookings')
async def create_booking(body: BookingCreateRequest, user: AuthUser = Depends(require_authenticated)) -> dict:
    tid = await _resolve_tenant()
    svc = _get_booking_svc()
    booking = await svc.create_manual_booking(
        tenant_id=tid, booking_date=date.fromisoformat(body.booking_date),
        description=body.description, account_soll=body.account_soll,
        account_haben=body.account_haben, gross_amount=Decimal(str(body.gross_amount)),
        booking_type=body.booking_type, created_by=user.username,
        net_amount=Decimal(str(body.net_amount)) if body.net_amount else None,
        tax_rate=Decimal(str(body.tax_rate)) if body.tax_rate else None,
        tax_amount=Decimal(str(body.tax_amount)) if body.tax_amount else None,
        document_number=body.document_number,
    )
    return {'status': 'created', 'booking_id': booking.id, 'booking_number': booking.booking_number}


@router.get('/bookings')
async def list_bookings(
    user: AuthUser = Depends(require_authenticated),
    date_from: str = '', date_to: str = '', status: str = '',
    limit: int = 100, offset: int = 0,
) -> dict:
    tid = await _resolve_tenant()
    repo = _get_repo()
    bookings = await repo.list_bookings(
        tid,
        date_from=date.fromisoformat(date_from) if date_from else None,
        date_to=date.fromisoformat(date_to) if date_to else None,
        status=status or None, limit=limit, offset=offset,
    )
    return {
        'count': len(bookings),
        'items': [b.model_dump(mode='json') for b in bookings],
    }


@router.get('/bookings/{booking_id}')
async def get_booking(booking_id: str, user: AuthUser = Depends(require_authenticated)) -> dict:
    tid = await _resolve_tenant()
    repo = _get_repo()
    bookings = await repo.list_bookings(tid, limit=10000)
    booking = next((b for b in bookings if b.id == booking_id), None)
    if not booking:
        raise HTTPException(status_code=404, detail='booking_not_found')
    return booking.model_dump(mode='json')


# ── Contacts ─────────────────────────────────────────────────────────────────

@router.get('/contacts')
async def list_contacts(user: AuthUser = Depends(require_authenticated)) -> dict:
    tid = await _resolve_tenant()
    contacts = await _get_repo().list_contacts(tid)
    return {'count': len(contacts), 'items': [c.model_dump(mode='json') for c in contacts]}


@router.post('/contacts')
async def create_contact(body: ContactCreateRequest, user: AuthUser = Depends(require_authenticated)) -> dict:
    tid = await _resolve_tenant()
    contact = await _get_repo().find_or_create_contact(
        tid, body.name, contact_type=body.contact_type,
    )
    return {'status': 'created', 'contact': contact.model_dump(mode='json')}


@router.get('/contacts/{contact_id}')
async def get_contact(contact_id: str, user: AuthUser = Depends(require_authenticated)) -> dict:
    tid = await _resolve_tenant()
    contacts = await _get_repo().list_contacts(tid)
    contact = next((c for c in contacts if c.id == contact_id), None)
    if not contact:
        raise HTTPException(status_code=404, detail='contact_not_found')
    return contact.model_dump(mode='json')


@router.get('/contacts/{contact_id}/dossier')
async def get_contact_dossier(contact_id: str, user: AuthUser = Depends(require_authenticated)) -> dict:
    """Komplette Kundenakte — Kontakt + Stats + letzte Buchungen + offene Posten."""
    tid = await _resolve_tenant()
    repo = _get_repo()

    contact = await repo.get_contact_by_id(tid, uuid.UUID(contact_id))
    if not contact:
        raise HTTPException(status_code=404, detail='Kontakt nicht gefunden')

    # Get bookings for this contact
    all_bookings = await repo.list_bookings(tid, limit=10000)
    contact_bookings = [b for b in all_bookings if b.contact_id == contact_id]
    contact_bookings.sort(key=lambda b: b.booking_date, reverse=True)
    recent = contact_bookings[:10]

    # Get open items for this contact
    try:
        open_items = await repo.list_open_items_by_contact(tid, uuid.UUID(contact_id))
    except Exception:
        open_items = []

    # Stats
    income = sum(float(b.gross_amount) for b in contact_bookings if b.booking_type == 'INCOME')
    expenses = sum(float(b.gross_amount) for b in contact_bookings if b.booking_type == 'EXPENSE')
    open_amount = sum(float(oi.original_amount - oi.paid_amount) for oi in open_items if oi.status in ('OPEN', 'OVERDUE', 'PARTIALLY_PAID'))
    overdue = [oi for oi in open_items if oi.status == 'OVERDUE' or (oi.due_date and oi.due_date < date.today() and oi.status == 'OPEN')]

    return {
        'contact': {
            'id': contact.id, 'name': contact.name,
            'display_name': contact.display_name,
            'category': getattr(contact, 'category', 'OTHER'),
            'contact_type': contact.contact_type,
            'email': contact.email, 'phone': contact.phone,
            'address': f'{contact.address_street or ""}, {contact.address_zip or ""} {contact.address_city or ""}'.strip(', ') or None,
            'tax_id': contact.tax_id, 'iban': contact.iban,
            'notes': contact.notes,
            'default_payment_terms_days': getattr(contact, 'default_payment_terms_days', 14),
        },
        'stats': {
            'total_revenue': income,
            'total_expenses': expenses,
            'open_amount': open_amount,
            'overdue_count': len(overdue),
            'booking_count': len(contact_bookings),
            'first_contact': min((b.booking_date.isoformat() for b in contact_bookings), default=None),
            'last_contact': max((b.booking_date.isoformat() for b in contact_bookings), default=None),
        },
        'recent_bookings': [
            {'booking_number': b.booking_number, 'date': b.booking_date.isoformat(),
             'description': b.description, 'amount': float(b.gross_amount), 'type': b.booking_type}
            for b in recent
        ],
        'open_items': [
            {'id': oi.id, 'amount': float(oi.original_amount),
             'paid': float(oi.paid_amount),
             'due_date': oi.due_date.isoformat() if oi.due_date else None,
             'status': oi.status}
            for oi in open_items
        ],
    }


# ── Open Items ───────────────────────────────────────────────────────────────

@router.get('/open-items')
async def list_open_items(
    user: AuthUser = Depends(require_authenticated),
    item_type: str = '', status: str = '',
) -> dict:
    tid = await _resolve_tenant()
    items = await _get_repo().list_open_items(
        tid, item_type=item_type or None, status=status or None,
    )
    return {'count': len(items), 'items': [i.model_dump(mode='json') for i in items]}


@router.post('/open-items/{item_id}/payment')
async def record_payment(item_id: str, body: PaymentRequest, user: AuthUser = Depends(require_authenticated)) -> dict:
    from app.accounting.open_item_service import AccountingOpenItemService
    svc = AccountingOpenItemService(_get_repo())
    await svc.record_payment(uuid.UUID(item_id), Decimal(str(body.amount)))
    return {'status': 'payment_recorded', 'amount': body.amount}


# ── Invoices ─────────────────────────────────────────────────────────────────

@router.post('/invoices')
async def create_invoice(body: InvoiceCreateRequest, user: AuthUser = Depends(require_authenticated)) -> dict:
    tid = await _resolve_tenant()
    from app.accounting.invoice_service import InvoiceService
    svc = InvoiceService(_get_repo())
    contact = await _get_repo().find_or_create_contact(tid, body.contact_name, contact_type='CUSTOMER')
    invoice = await svc.create_invoice(
        tenant_id=tid, contact_id=contact.id, items=body.items,
        due_date=date.fromisoformat(body.due_date) if body.due_date else None,
        header_text=body.header_text, footer_text=body.footer_text,
    )
    return {'status': 'created', 'invoice': invoice.model_dump(mode='json')}


@router.get('/invoices')
async def list_invoices(user: AuthUser = Depends(require_authenticated)) -> dict:
    tid = await _resolve_tenant()
    from app.accounting.invoice_service import InvoiceService
    invoices = await InvoiceService(_get_repo()).list_invoices(tid)
    return {'count': len(invoices), 'items': [i.model_dump(mode='json') for i in invoices]}


@router.get('/invoices/{invoice_id}')
async def get_invoice(invoice_id: str, user: AuthUser = Depends(require_authenticated)) -> dict:
    tid = await _resolve_tenant()
    invoices = await _get_repo().list_invoices(tid)
    inv = next((i for i in invoices if i.id == invoice_id), None)
    if not inv:
        raise HTTPException(status_code=404, detail='invoice_not_found')
    return inv.model_dump(mode='json')


@router.get('/invoices/{invoice_id}/items')
async def get_invoice_items(invoice_id: str, user: AuthUser = Depends(require_authenticated)) -> dict:
    """Return line items for an invoice from frya_invoice_items."""
    import asyncpg
    from app.dependencies import get_settings
    settings = get_settings()
    conn = await asyncpg.connect(settings.database_url)
    try:
        rows = await conn.fetch(
            "SELECT position, description, quantity, unit, unit_price, "
            "tax_rate, net_amount, tax_amount, gross_amount "
            "FROM frya_invoice_items WHERE invoice_id = $1::uuid ORDER BY position",
            invoice_id,
        )
        items = []
        for r in rows:
            d = dict(r)
            items.append({
                'position': d['position'],
                'description': d['description'],
                'quantity': float(d['quantity']),
                'unit': d['unit'],
                'unit_price': float(d['unit_price']),
                'tax_rate': float(d['tax_rate']),
                'net_amount': float(d['net_amount']),
                'tax_amount': float(d['tax_amount']),
                'gross_amount': float(d['gross_amount']),
            })
        return {'count': len(items), 'items': items}
    finally:
        await conn.close()


@router.post('/invoices/{invoice_id}/finalize')
async def finalize_invoice(invoice_id: str, user: AuthUser = Depends(require_authenticated)) -> dict:
    """Finalize a DRAFT invoice: set status=SENT, create booking + open item."""
    tid = await _resolve_tenant()
    repo = _get_repo()

    invoices = await repo.list_invoices(tid)
    inv = next((i for i in invoices if i.id == invoice_id), None)
    if not inv:
        raise HTTPException(status_code=404, detail='invoice_not_found')
    if inv.status != 'DRAFT':
        raise HTTPException(status_code=409, detail=f'Invoice is already {inv.status}')

    # 1. Create booking (Erlöse) — BEFORE status change so we can rollback
    booking_svc = _get_booking_svc()
    booking = await booking_svc.create_manual_booking(
        tenant_id=tid,
        booking_date=date.today(),
        description=f'Rechnung {inv.invoice_number} — {inv.gross_total}€',
        account_soll='1200',  # Forderungen aus L+L
        account_haben='7000',  # Umsatzerlöse 19%
        gross_amount=inv.gross_total,
        booking_type='INCOME',
        created_by=user.username,
        net_amount=inv.net_total,
        tax_rate=Decimal('19.00'),
        tax_amount=inv.tax_total,
        document_number=inv.invoice_number,
    )

    # 2. Create open item (Forderung)
    oi_due = inv.due_date if inv.due_date else (date.today() + timedelta(days=14))
    if isinstance(oi_due, str):
        oi_due = date.fromisoformat(oi_due)
    oi = await repo.create_open_item(tid, {
        'contact_id': inv.contact_id,
        'item_type': 'RECEIVABLE',
        'original_amount': float(inv.gross_total),
        'paid_amount': 0.0,
        'currency': 'EUR',
        'due_date': oi_due,
        'reference': inv.invoice_number,
        'status': 'OPEN',
        'case_id': None,
    })

    # 3. Update status to SENT (only after booking + OP succeeded)
    from app.dependencies import get_settings
    settings = get_settings()
    import asyncpg
    conn = await asyncpg.connect(settings.database_url)
    try:
        await conn.execute(
            "UPDATE frya_invoices SET status = 'SENT' WHERE id = $1::uuid",
            invoice_id,
        )
    finally:
        await conn.close()

    return {
        'status': 'finalized',
        'invoice_status': 'SENT',
        'booking_id': booking.id,
        'booking_number': booking.booking_number,
        'open_item_id': oi.id if oi else None,
    }


class SendInvoiceRequest(BaseModel):
    email: str = Field(..., description='Recipient email address')


@router.post('/invoices/{invoice_id}/send')
async def send_invoice_email(
    invoice_id: str,
    body: SendInvoiceRequest,
    user: AuthUser = Depends(require_authenticated),
) -> dict:
    """Generate PDF and send invoice via email (Brevo)."""
    import base64
    tid = await _resolve_tenant()
    repo = _get_repo()

    try:
        inv_uuid = uuid.UUID(invoice_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail='invalid_invoice_id') from exc

    invoice = await repo.get_invoice_by_id(tid, inv_uuid)
    if not invoice:
        raise HTTPException(status_code=404, detail='invoice_not_found')

    # ── Generate PDF (reuse logic from pdf_views) ────────────────────────
    from app.pdf.service import PdfService
    from app.config import get_settings
    settings = get_settings()
    pdf_service = PdfService()

    contact = await repo.get_contact_by_id(tid, uuid.UUID(invoice.contact_id))
    contact_dict = {
        'name': contact.name if contact else 'Unbekannt',
        'street': (contact.address_street or '') if contact else '',
        'zip': (contact.address_zip or '') if contact else '',
        'city': (contact.address_city or '') if contact else '',
    }

    tenant_dict = {
        'company_name': getattr(settings, 'company_name', 'Meine Firma GmbH'),
        'street': getattr(settings, 'company_street', 'Musterstr. 1'),
        'zip': getattr(settings, 'company_zip', '10115'),
        'city': getattr(settings, 'company_city', 'Berlin'),
        'iban': getattr(settings, 'company_iban', ''),
        'bic': getattr(settings, 'company_bic', ''),
        'tax_id': getattr(settings, 'company_tax_id', ''),
        'tax_number': getattr(settings, 'company_tax_number', ''),
    }

    tax_rate = 19.0
    if invoice.net_total and invoice.net_total > 0:
        tax_rate = float(round(invoice.tax_total / invoice.net_total * 100, 2))

    invoice_dict = {
        'invoice_number': invoice.invoice_number,
        'invoice_date': invoice.invoice_date.strftime('%d.%m.%Y') if invoice.invoice_date else '',
        'due_date': invoice.due_date.strftime('%d.%m.%Y') if invoice.due_date else '',
        'net_amount': float(invoice.net_total),
        'tax_amount': float(invoice.tax_total),
        'gross_amount': float(invoice.gross_total),
        'tax_rate': tax_rate,
        'payment_days': 14,
    }
    items_list = [{
        'description': f'Rechnung {invoice.invoice_number}',
        'quantity': 1,
        'unit': 'Stk',
        'unit_price': float(invoice.net_total),
        'tax_rate': tax_rate,
        'total_price': float(invoice.gross_total),
    }]

    pdf_bytes = await pdf_service.generate_invoice_pdf(
        invoice=invoice_dict, items=items_list,
        contact=contact_dict, tenant=tenant_dict,
    )

    # ZUGFeRD embedding (non-fatal)
    try:
        from app.e_invoice.generator import embed_zugferd
        zugferd_data = {
            'invoice_number': invoice.invoice_number,
            'invoice_date': invoice.invoice_date,
            'due_date': invoice.due_date,
            'net_amount': float(invoice.net_total),
            'tax_amount': float(invoice.tax_total),
            'gross_amount': float(invoice.gross_total),
            'currency': 'EUR',
            'seller_name': tenant_dict.get('company_name', ''),
            'seller_tax_id': tenant_dict.get('tax_id', ''),
            'buyer_name': contact_dict.get('name', ''),
            'iban': tenant_dict.get('iban', ''),
            'bic': tenant_dict.get('bic', ''),
            'items': items_list,
        }
        pdf_bytes = embed_zugferd(pdf_bytes, zugferd_data)
    except Exception as exc:
        logger.warning('ZUGFeRD embedding failed for send: %s', exc)

    # ── Send via mail service (Brevo) ────────────────────────────────────
    from app.dependencies import get_mail_service
    mail_service = get_mail_service()

    pdf_b64 = base64.b64encode(pdf_bytes).decode('ascii')
    filename = f'Rechnung_{invoice.invoice_number}.pdf'

    subject = f'Rechnung {invoice.invoice_number} — {tenant_dict.get("company_name", "")}'
    body_html = (
        f'<p>Sehr geehrte Damen und Herren,</p>'
        f'<p>anbei erhalten Sie Rechnung <strong>{invoice.invoice_number}</strong> '
        f'über <strong>{invoice.gross_total} EUR</strong>.</p>'
        f'<p>Zahlungsziel: {invoice_dict["due_date"]}</p>'
        f'<p>Mit freundlichen Grüßen<br/>{tenant_dict.get("company_name", "")}</p>'
    )
    body_text = (
        f'Rechnung {invoice.invoice_number} über {invoice.gross_total} EUR.\n'
        f'Zahlungsziel: {invoice_dict["due_date"]}\n'
        f'PDF im Anhang.\n\n'
        f'{tenant_dict.get("company_name", "")}'
    )

    await mail_service.send_mail(
        to=body.email,
        subject=subject,
        body_html=body_html,
        body_text=body_text,
        tenant_id=str(tid),
        attachments=[{'name': filename, 'content': pdf_b64}],
    )

    # ── If still DRAFT, also finalize ────────────────────────────────────
    if invoice.status == 'DRAFT':
        import asyncpg
        conn = await asyncpg.connect(settings.database_url)
        try:
            await conn.execute(
                "UPDATE frya_invoices SET status = 'SENT' WHERE id = $1::uuid",
                invoice_id,
            )
        finally:
            await conn.close()

    logger.info('Invoice %s sent via email to %s', invoice.invoice_number, body.email)
    return {
        'status': 'sent',
        'invoice_number': invoice.invoice_number,
        'email': body.email,
        'pdf_size': len(pdf_bytes),
    }


# ── Reports ──────────────────────────────────────────────────────────────────

@router.get('/reports/euer')
async def get_euer(user: AuthUser = Depends(require_authenticated), year: int = 0) -> dict:
    tid = await _resolve_tenant()
    if year == 0:
        year = date.today().year
    from app.accounting.euer_service import EuerService
    return await EuerService(_get_repo()).generate_euer(tid, year)


@router.get('/reports/ust')
async def get_ust(user: AuthUser = Depends(require_authenticated), year: int = 0, quarter: int = 0) -> dict:
    tid = await _resolve_tenant()
    if year == 0:
        year = date.today().year
    if quarter == 0:
        quarter = (date.today().month - 1) // 3 + 1
    from app.accounting.euer_service import EuerService
    return await EuerService(_get_repo()).generate_ust(tid, year, quarter)


@router.get('/reports/account-balances')
async def get_account_balances(user: AuthUser = Depends(require_authenticated)) -> dict:
    tid = await _resolve_tenant()
    repo = _get_repo()
    accounts = await repo.list_accounts(tid)
    balances = []
    for a in accounts:
        balance = await repo.get_account_balance(tid, a.account_number)
        if balance != 0:
            balances.append({
                'account_number': a.account_number,
                'name': a.name,
                'account_type': a.account_type,
                'balance': float(balance),
            })
    return {'count': len(balances), 'items': balances}


# ── Admin ────────────────────────────────────────────────────────────────────

@router.get('/admin/verify-hash-chain')
async def verify_hash_chain(user: AuthUser = Depends(require_authenticated)) -> dict:
    tid = await _resolve_tenant()
    return await _get_booking_svc().verify_hash_chain(tid)
