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

async def _resolve_tenant() -> uuid.UUID:
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
    tenant_id = await _resolve_tenant()
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
    tenant_dict = _build_tenant_dict(get_settings())

    # Determine dominant tax rate from invoice totals
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

    # For now provide a single summary line item (invoice_items table
    # integration can be added when that data is populated).
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
        invoice=invoice_dict,
        items=items_list,
        contact=contact_dict,
        tenant=tenant_dict,
    )

    filename = f'Rechnung_{invoice.invoice_number}.pdf'
    return Response(
        content=pdf_bytes,
        media_type='application/pdf',
        headers={'Content-Disposition': f'inline; filename="{filename}"'},
    )


@router.post('/dunning/{contact_id}/generate')
async def generate_dunning_pdf(
    contact_id: str,
    body: DunningGenerateRequest,
    user: AuthUser = Depends(require_authenticated),
) -> Response:
    """Generate a dunning letter PDF for a contact's overdue items."""
    tenant_id = await _resolve_tenant()
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
