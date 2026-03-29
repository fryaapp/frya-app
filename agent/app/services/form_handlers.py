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
