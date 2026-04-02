"""PDF generation endpoints for invoices and dunning letters."""
from __future__ import annotations

import logging
import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.auth.dependencies import require_authenticated
from app.auth.models import AuthUser

logger = logging.getLogger(__name__)

router = APIRouter(prefix='/api/v1', tags=['pdf'])


# ── Helpers ──────────────────────────────────────────────────────────────────

async def _resolve_tenant(user=None) -> uuid.UUID:
    if user and getattr(user, 'tenant_id', None):
        return uuid.UUID(str(user.tenant_id))
    from app.case_engine.tenant_resolver import resolve_tenant_id
    tid = await resolve_tenant_id()
    if not tid:
        raise HTTPException(status_code=503, detail='tenant_unavailable')
    return uuid.UUID(tid)


def _get_repo():
    from app.dependencies import get_accounting_repository
    return get_accounting_repository()


def _get_pdf_service():
    from app.pdf.service import PdfService
    return PdfService()


def _build_tenant_dict(settings) -> dict:
    """Build tenant dict from settings for PDF templates.

    In production this would come from a tenant-settings table;
    for now we use sensible defaults that can be overridden.
    """
    return {
        'company_name': getattr(settings, 'company_name', 'Meine Firma GmbH'),
        'street': getattr(settings, 'company_street', 'Musterstr. 1'),
        'zip': getattr(settings, 'company_zip', '10115'),
        'city': getattr(settings, 'company_city', 'Berlin'),
        'iban': getattr(settings, 'company_iban', ''),
        'bic': getattr(settings, 'company_bic', ''),
        'tax_id': getattr(settings, 'company_tax_id', ''),
        'tax_number': getattr(settings, 'company_tax_number', ''),
    }


def _contact_to_dict(contact) -> dict:
    return {
        'name': contact.name,
        'street': contact.address_street or '',
        'zip': contact.address_zip or '',
        'city': contact.address_city or '',
    }


# ── Request / Response Models ────────────────────────────────────────────────

class DunningGenerateRequest(BaseModel):
    open_item_ids: list[str] = Field(
        ..., description='IDs of overdue accounting open items',
    )
    level: int = Field(1, ge=1, le=4, description='Dunning level 1-4')
    interest_rate: float = Field(0, ge=0, description='Late interest rate %')
    fee: float = Field(0, ge=0, description='Flat dunning fee in EUR')


class DunningGenerateResponse(BaseModel):
    status: str
    contact_name: str
    items_count: int
    total: float


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get('/invoices/{invoice_id}/pdf')
async def get_invoice_pdf(
    invoice_id: str,
    user: AuthUser = Depends(require_authenticated),
) -> Response:
    """Generate and return an invoice as PDF (binary)."""
    tenant_id = await _resolve_tenant(user)
    repo = _get_repo()
    pdf_service = _get_pdf_service()

    try:
        inv_uuid = uuid.UUID(invoice_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail='invalid_invoice_id') from exc

    invoice = await repo.get_invoice_by_id(tenant_id, inv_uuid)
    if not invoice:
        raise HTTPException(status_code=404, detail='invoice_not_found')

    # Load contact
    contact = await repo.get_contact_by_id(tenant_id, uuid.UUID(invoice.contact_id))
    contact_dict = _contact_to_dict(contact) if contact else {'name': 'Unbekannt', 'street': '', 'zip': '', 'city': ''}

    # Build invoice data dict for template
    from app.config import get_settings
    settings = get_settings()

    # Load company data from business_profile (P-04/P-05 fix)
    try:
        from app.pdf.template_registry import (
            get_company_data_for_template, get_company_logo_b64,
            render_invoice_pdf as _render_tpl_pdf, get_template_name,
        )
        tenant_dict = await get_company_data_for_template('', str(tenant_id))
        logo_b64 = await get_company_logo_b64('', str(tenant_id))
    except Exception as exc:
        logger.warning('Template-aware tenant load failed: %s', exc)
        tenant_dict = _build_tenant_dict(settings)
        logo_b64 = None

    # Load user preferences for template + kleinunternehmer
    kleinunternehmer = False
    template_key = 'clean'
    skonto_pct = None
    skonto_days = None
    try:
        import asyncpg as _apg_prefs
        _prefs_conn = await _apg_prefs.connect(settings.database_url)
        try:
            _pref_rows = await _prefs_conn.fetch(
                "SELECT key, value FROM frya_user_preferences "
                "WHERE tenant_id IN ($1, 'default', '') "
                "AND key IN ('invoice_template', 'kleinunternehmer', "
                "'default_skonto_percent', 'default_skonto_days') "
                "ORDER BY CASE WHEN tenant_id = $1 THEN 0 ELSE 1 END",
                str(tenant_id),
            )
            _pdict: dict[str, str] = {}
            for r in reversed(_pref_rows):
                _pdict[r['key']] = r['value']
            template_key = get_template_name(_pdict.get('invoice_template'))
            kleinunternehmer = _pdict.get('kleinunternehmer') == 'true'
            skonto_pct = float(_pdict['default_skonto_percent']) if _pdict.get('default_skonto_percent') else None
            skonto_days = int(_pdict['default_skonto_days']) if _pdict.get('default_skonto_days') else None
        finally:
            await _prefs_conn.close()
    except Exception as exc:
        logger.warning('Prefs load for PDF failed: %s', exc)

    # Load line items from frya_invoice_items (fallback to summary)
    items_list = []
    try:
        import asyncpg as _apg_items
        _items_conn = await _apg_items.connect(settings.database_url)
        try:
            item_rows = await _items_conn.fetch(
                "SELECT description, quantity, unit, unit_price, tax_rate, "
                "net_amount, tax_amount, gross_amount "
                "FROM frya_invoice_items WHERE invoice_id = $1 ORDER BY position",
                inv_uuid,
            )
            for ir in item_rows:
                qty = float(ir['quantity'] or 1)
                # P-04 3a: whole numbers without decimal
                if qty == int(qty):
                    qty = int(qty)
                items_list.append({
                    'description': ir['description'] or '',
                    'quantity': qty,
                    'unit': ir['unit'] or 'Stk',
                    'unit_price': float(ir['unit_price'] or 0),
                    'tax_rate': float(ir['tax_rate'] or 19),
                    'total_price': float(ir['gross_amount'] or 0),
                })
        finally:
            await _items_conn.close()
    except Exception as exc:
        logger.warning('Failed to load invoice items for PDF: %s', exc)

    # P-05: FIXED tax_rate from items, not division
    tax_rate = 19.0
    if kleinunternehmer:
        tax_rate = 0.0
    elif items_list:
        tax_rate = float(items_list[0].get('tax_rate', 19))

    invoice_dict = {
        'invoice_number': invoice.invoice_number,
        'invoice_date': invoice.invoice_date.strftime('%d.%m.%Y') if invoice.invoice_date else '',
        'due_date': invoice.due_date.strftime('%d.%m.%Y') if invoice.due_date else '',
        'net_amount': float(invoice.net_total),
        'tax_amount': 0.0 if kleinunternehmer else float(invoice.tax_total),
        'gross_amount': float(invoice.net_total) if kleinunternehmer else float(invoice.gross_total),
        'tax_rate': tax_rate,
        'payment_days': 14,
    }

    if not items_list:
        items_list = [
            {
                'description': f'Rechnung {invoice.invoice_number}',
                'quantity': 1, 'unit': 'Stk',
                'unit_price': float(invoice.net_total),
                'tax_rate': tax_rate,
                'total_price': float(invoice.gross_total),
            },
        ]

    # Use template system (P-04 fix)
    try:
        pdf_bytes = await _render_tpl_pdf(
            template_key, invoice_dict, items_list,
            contact_dict, tenant_dict,
            logo_b64=logo_b64,
            kleinunternehmer=kleinunternehmer,
            skonto_percent=skonto_pct,
            skonto_days=skonto_days,
        )
    except Exception as exc:
        logger.warning('Template PDF failed, using legacy: %s', exc)
        pdf_bytes = await pdf_service.generate_invoice_pdf(
            invoice=invoice_dict, items=items_list,
            contact=contact_dict, tenant=tenant_dict,
        )

    # ── ZUGFeRD / Factur-X embedding (EN 16931 BASIC) ────────────────────
    # Embed structured CII XML into the generated PDF so recipients can
    # process it as an e-invoice.  Failure is non-fatal — the plain PDF
    # is returned if embedding fails.
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
        logger.info('ZUGFeRD embedded into invoice %s', invoice.invoice_number)
    except Exception as exc:
        logger.warning('ZUGFeRD-Einbettung fehlgeschlagen fuer %s: %s', invoice.invoice_number, exc)

    filename = f'Rechnung_{invoice.invoice_number}.pdf'
    return Response(
        content=pdf_bytes,
        media_type='application/pdf',
        headers={'Content-Disposition': f'inline; filename="{filename}"'},
    )


@router.post('/invoices/{invoice_id}/send')
async def send_invoice_email(
    invoice_id: str,
    body: dict,
    user: AuthUser = Depends(require_authenticated),
) -> dict:
    """Aufgabe 7: Generate invoice PDF and send via email."""
    import base64
    tenant_id = await _resolve_tenant(user)
    repo = _get_repo()
    pdf_service = _get_pdf_service()

    recipient_email = body.get('recipient_email', '')
    if not recipient_email or '@' not in recipient_email:
        raise HTTPException(status_code=400, detail='recipient_email required')

    try:
        inv_uuid = uuid.UUID(invoice_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail='invalid_invoice_id') from exc

    invoice = await repo.get_invoice_by_id(tenant_id, inv_uuid)
    if not invoice:
        raise HTTPException(status_code=404, detail='invoice_not_found')

    # Load contact
    contact = await repo.get_contact_by_id(tenant_id, uuid.UUID(invoice.contact_id))
    contact_dict = _contact_to_dict(contact) if contact else {'name': 'Unbekannt', 'street': '', 'zip': '', 'city': ''}

    from app.config import get_settings
    settings = get_settings()
    tenant_dict = _build_tenant_dict(settings)

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
    items_list = [
        {
            'description': f'Rechnung {invoice.invoice_number}',
            'quantity': 1,
            'unit': 'Stk',
            'unit_price': float(invoice.net_total),
            'tax_rate': tax_rate,
            'total_price': float(invoice.gross_total),
        },
    ]

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

    # Send via mail service
    from app.dependencies import get_mail_service
    mail_svc = get_mail_service()
    filename = f'Rechnung_{invoice.invoice_number}.pdf'
    contact_name = contact_dict.get('name', 'Kunde')

    await mail_svc.send_mail(
        to=recipient_email,
        subject=f'Rechnung {invoice.invoice_number} von {tenant_dict.get("company_name", "FRYA")}',
        body_html=(
            f'<p>Sehr geehrte(r) {contact_name},</p>'
            f'<p>anbei erhalten Sie Rechnung <strong>{invoice.invoice_number}</strong> '
            f'über <strong>{float(invoice.gross_total):.2f} EUR</strong>.</p>'
            f'<p>Zahlbar bis: {invoice_dict["due_date"]}</p>'
            f'<p>Mit freundlichen Gr&uuml;&szlig;en</p>'
        ),
        body_text=(
            f'Rechnung {invoice.invoice_number} - {float(invoice.gross_total):.2f} EUR\n'
            f'Zahlbar bis: {invoice_dict["due_date"]}\n'
        ),
        attachments=[{
            'name': filename,
            'content': base64.b64encode(pdf_bytes).decode('ascii'),
        }],
    )

    logger.info('Invoice %s sent to %s (%d bytes PDF)', invoice.invoice_number, recipient_email, len(pdf_bytes))
    return {
        'status': 'sent',
        'invoice_number': invoice.invoice_number,
        'recipient': recipient_email,
        'pdf_size_bytes': len(pdf_bytes),
    }


@router.post('/dunning/{contact_id}/generate')
async def generate_dunning_pdf(
    contact_id: str,
    body: DunningGenerateRequest,
    user: AuthUser = Depends(require_authenticated),
) -> Response:
    """Generate a dunning letter PDF for a contact's overdue items."""
    tenant_id = await _resolve_tenant(user)
    repo = _get_repo()
    pdf_service = _get_pdf_service()

    try:
        contact_uuid = uuid.UUID(contact_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail='invalid_contact_id') from exc

    contact = await repo.get_contact_by_id(tenant_id, contact_uuid)
    if not contact:
        raise HTTPException(status_code=404, detail='contact_not_found')

    # Resolve open items -- fetch all for contact once, then filter
    today = date.today()
    requested_ids = set(body.open_item_ids)
    all_items = await repo.list_open_items_by_contact(tenant_id, contact_uuid)

    open_items_data: list[dict] = []
    for item in all_items:
        if item.id in requested_ids:
            remaining = float(item.original_amount - item.paid_amount)
            days_overdue = (today - item.due_date).days if item.due_date else 0
            open_items_data.append({
                'invoice_number': item.invoice_number or '',
                'reference': item.invoice_number or item.id[:8],
                'remaining_amount': remaining,
                'due_date': item.due_date.strftime('%d.%m.%Y') if item.due_date else '',
                'days_overdue': max(days_overdue, 0),
            })

    if not open_items_data:
        raise HTTPException(
            status_code=404,
            detail='no_matching_open_items',
        )

    from app.config import get_settings
    tenant_dict = _build_tenant_dict(get_settings())
    contact_dict = _contact_to_dict(contact)

    pdf_bytes = await pdf_service.generate_dunning_pdf(
        contact=contact_dict,
        open_items=open_items_data,
        tenant=tenant_dict,
        level=body.level,
        interest_rate=body.interest_rate,
        fee=body.fee,
    )

    total_base = sum(i['remaining_amount'] for i in open_items_data)
    interest_amount = total_base * body.interest_rate / 100 if body.interest_rate else 0
    total = total_base + interest_amount + body.fee

    filename = f'Mahnung_{contact.name}_{today.strftime("%Y%m%d")}.pdf'
    return Response(
        content=pdf_bytes,
        media_type='application/pdf',
        headers={'Content-Disposition': f'inline; filename="{filename}"'},
    )
