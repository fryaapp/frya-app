"""Form submission handlers — map form_submit data to existing service calls."""
from __future__ import annotations

import logging
import uuid
from datetime import date
from decimal import Decimal

logger = logging.getLogger(__name__)


async def _resolve_tenant() -> uuid.UUID:
    from app.case_engine.tenant_resolver import resolve_tenant_id
    tid = await resolve_tenant_id()
    if not tid:
        raise RuntimeError('tenant_unavailable')
    return uuid.UUID(tid)


def _get_repo():
    from app.dependencies import get_accounting_repository
    return get_accounting_repository()


async def handle_invoice_form(form_data: dict, user_id: str) -> dict:
    """Form → InvoiceService.create_invoice."""
    from app.accounting.invoice_service import InvoiceService
    tid = await _resolve_tenant()
    repo = _get_repo()
    svc = InvoiceService(repo)

    contact_name = form_data.get('contact_name', 'Unbekannt')
    contact = await repo.find_or_create_contact(tid, contact_name, contact_type='CUSTOMER')

    due_days = int(form_data.get('payment_terms_days', 14))
    due_date = date.today() + __import__('datetime').timedelta(days=due_days)

    invoice = await svc.create_invoice(
        tenant_id=tid,
        contact_id=contact.id,
        items=form_data.get('items', []),
        due_date=due_date,
        header_text=None,
        footer_text=form_data.get('notes'),
    )

    return {
        'invoice_id': invoice.id,
        'invoice_number': invoice.invoice_number,
        'gross_total': str(invoice.gross_total),
        'status': invoice.status,
    }


async def handle_invoice_send(form_data: dict, user_id: str) -> dict:
    """Create invoice + finalize + send via email in one step.

    Called when the communicator confirms invoice sending.
    form_data expected: contact_name, email, items, payment_terms_days
    """
    import base64
    from datetime import timedelta
    from app.accounting.invoice_service import InvoiceService

    tid = await _resolve_tenant()
    repo = _get_repo()
    svc = InvoiceService(repo)

    contact_name = form_data.get('contact_name', 'Unbekannt')
    email = form_data.get('email', '')
    contact = await repo.find_or_create_contact(tid, contact_name, contact_type='CUSTOMER')

    # Update contact email if provided
    if email:
        try:
            from app.dependencies import get_settings
            import asyncpg
            conn = await asyncpg.connect(get_settings().database_url)
            try:
                await conn.execute(
                    "UPDATE frya_contacts SET email = $2 WHERE id = $1::uuid",
                    contact.id, email,
                )
            finally:
                await conn.close()
        except Exception as exc:
            logger.warning('Contact email update failed: %s', exc)

    due_days = int(form_data.get('payment_terms_days', 14))
    due_date = date.today() + timedelta(days=due_days)

    # 1. Create invoice
    invoice = await svc.create_invoice(
        tenant_id=tid,
        contact_id=contact.id,
        items=form_data.get('items', []),
        due_date=due_date,
        header_text=None,
        footer_text=form_data.get('notes'),
    )

    if not email:
        return {
            'invoice_id': invoice.id,
            'invoice_number': invoice.invoice_number,
            'gross_total': str(invoice.gross_total),
            'status': 'created_no_email',
            'message': f'Rechnung {invoice.invoice_number} erstellt, aber keine E-Mail-Adresse angegeben.',
        }

    # 2. Generate PDF
    from app.pdf.service import PdfService
    from app.config import get_settings
    settings = get_settings()
    pdf_service = PdfService()

    contact_dict = {
        'name': contact.name,
        'street': contact.address_street or '',
        'zip': contact.address_zip or '',
        'city': contact.address_city or '',
    }
    tenant_dict = {
        'company_name': getattr(settings, 'company_name', 'Meine Firma GmbH'),
        'street': getattr(settings, 'company_street', 'Musterstr. 1'),
        'zip': getattr(settings, 'company_zip', '10115'),
        'city': getattr(settings, 'company_city', 'Berlin'),
        'iban': getattr(settings, 'company_iban', ''),
        'bic': getattr(settings, 'company_bic', ''),
        'tax_id': getattr(settings, 'company_tax_id', ''),
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
        'payment_days': due_days,
    }
    items_list = [{
        'description': f'Rechnung {invoice.invoice_number}',
        'quantity': 1, 'unit': 'Stk',
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
        pdf_bytes = embed_zugferd(pdf_bytes, {
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
        })
    except Exception as exc:
        logger.warning('ZUGFeRD embedding failed: %s', exc)

    # 3. Send via Brevo
    from app.dependencies import get_mail_service
    mail_service = get_mail_service()

    pdf_b64 = base64.b64encode(pdf_bytes).decode('ascii')
    filename = f'Rechnung_{invoice.invoice_number}.pdf'
    company = tenant_dict.get('company_name', '')

    await mail_service.send_mail(
        to=email,
        subject=f'Rechnung {invoice.invoice_number} — {company}',
        body_html=(
            f'<p>Sehr geehrte Damen und Herren,</p>'
            f'<p>anbei erhalten Sie Rechnung <strong>{invoice.invoice_number}</strong> '
            f'über <strong>{invoice.gross_total} EUR</strong>.</p>'
            f'<p>Zahlungsziel: {invoice_dict["due_date"]}</p>'
            f'<p>Mit freundlichen Grüßen<br/>{company}</p>'
        ),
        body_text=(
            f'Rechnung {invoice.invoice_number} über {invoice.gross_total} EUR.\n'
            f'Zahlungsziel: {invoice_dict["due_date"]}\nPDF im Anhang.\n\n{company}'
        ),
        tenant_id=str(tid),
        attachments=[{'name': filename, 'content': pdf_b64}],
    )

    # 4. Finalize (DRAFT → SENT)
    if invoice.status == 'DRAFT':
        try:
            import asyncpg
            conn = await asyncpg.connect(settings.database_url)
            try:
                await conn.execute(
                    "UPDATE frya_invoices SET status = 'SENT' WHERE id = $1::uuid",
                    str(invoice.id),
                )
            finally:
                await conn.close()
        except Exception as exc:
            logger.warning('Invoice status update failed: %s', exc)

    logger.info('Invoice %s created and sent to %s', invoice.invoice_number, email)
    return {
        'invoice_id': invoice.id,
        'invoice_number': invoice.invoice_number,
        'gross_total': str(invoice.gross_total),
        'email': email,
        'status': 'sent',
    }


async def handle_contact_form(form_data: dict, user_id: str) -> dict:
    """Form → find_or_create_contact + update fields."""
    tid = await _resolve_tenant()
    repo = _get_repo()

    name = form_data.get('name', 'Unbekannt')
    contact_type = form_data.get('category', 'VENDOR')
    # Map category → contact_type
    cat_map = {'CUSTOMER': 'CUSTOMER', 'SUPPLIER': 'VENDOR', 'BOTH': 'BOTH'}
    ct = cat_map.get(contact_type, 'VENDOR')

    contact = await repo.find_or_create_contact(tid, name, contact_type=ct)

    # Update additional fields via direct DB call
    try:
        from app.dependencies import get_settings
        import asyncpg
        conn = await asyncpg.connect(get_settings().database_url)
        try:
            await conn.execute(
                """UPDATE frya_contacts SET
                    email = COALESCE($2, email),
                    phone = COALESCE($3, phone),
                    tax_id = COALESCE($4, tax_id),
                    iban = COALESCE($5, iban),
                    notes = COALESCE($6, notes),
                    default_payment_terms_days = COALESCE($7, default_payment_terms_days),
                    category = COALESCE($8, category),
                    updated_at = NOW()
                WHERE id = $1::uuid""",
                contact.id,
                form_data.get('email'),
                form_data.get('phone'),
                form_data.get('tax_id'),
                form_data.get('iban'),
                form_data.get('notes'),
                int(form_data['default_payment_terms_days']) if form_data.get('default_payment_terms_days') else None,
                form_data.get('category'),
            )
        finally:
            await conn.close()
    except Exception as exc:
        logger.warning('Contact update failed: %s', exc)

    return {'contact_id': contact.id, 'name': name, 'status': 'saved'}


async def handle_settings_form(form_data: dict, user_id: str) -> dict:
    """Form → frya_user_preferences upsert."""
    try:
        from app.dependencies import get_settings
        import asyncpg
        settings = get_settings()
        if settings.database_url.startswith('memory://'):
            return {'status': 'skipped'}
        conn = await asyncpg.connect(settings.database_url)
        try:
            for key, value in form_data.items():
                if key in ('display_name', 'theme', 'notification_channel', 'formal_address'):
                    # P-06: Validate display_name before saving
                    if key == 'display_name':
                        from app.api.chat_ws import is_plausible_name
                        is_name, conf = is_plausible_name(str(value))
                        if not is_name or conf < 0.6:
                            continue  # Skip invalid name
                        value = str(value).strip().title()
                    await conn.execute(
                        """INSERT INTO frya_user_preferences (tenant_id, user_id, key, value, updated_at)
                        VALUES ('default', $1, $2, $3, NOW())
                        ON CONFLICT (tenant_id, user_id, key) DO UPDATE
                          SET value = EXCLUDED.value, updated_at = NOW()""",
                        user_id, key, str(value),
                    )
        finally:
            await conn.close()
    except Exception as exc:
        logger.warning('Settings update failed: %s', exc)
        return {'status': 'error', 'message': str(exc)}
    return {'status': 'saved'}
