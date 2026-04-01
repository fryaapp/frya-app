"""Invoice template registry — Clean, Professional, Minimal.

Each template maps to a Jinja2 HTML file rendered via Gotenberg.
Template selection is stored in frya_user_preferences as `invoice_template`.
"""
from __future__ import annotations

import base64
import logging
from io import BytesIO
from pathlib import Path
from typing import Any

import httpx
from jinja2 import Environment, FileSystemLoader

logger = logging.getLogger(__name__)

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / 'templates'
_jinja_env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)), autoescape=True)

GOTENBERG_URL = 'http://frya-gotenberg:3000/forms/chromium/convert/html'

# Available templates
TEMPLATES: dict[str, dict[str, str]] = {
    'clean': {
        'file': 'invoice_clean.html',
        'title': 'Clean',
        'subtitle': 'Modern und aufgeraeumt — der Standard',
        'badge': 'Empfohlen',
    },
    'professional': {
        'file': 'invoice_professional.html',
        'title': 'Professional',
        'subtitle': 'Klassisch mit Header — fuer Geschaeftskunden',
        'badge': None,
    },
    'minimal': {
        'file': 'invoice_minimal.html',
        'title': 'Minimal',
        'subtitle': 'Nur das Noetigste — fuer Freelancer',
        'badge': None,
    },
}

DEFAULT_TEMPLATE = 'clean'

# Sample data for preview rendering
SAMPLE_INVOICE_DATA: dict[str, Any] = {
    'invoice_number': 'RE-2026-MUSTER',
    'invoice_date': '31.03.2026',
    'due_date': '14.04.2026',
    'net_amount': 300.00,
    'tax_amount': 57.00,
    'gross_amount': 357.00,
    'tax_rate': 19.0,
    'payment_days': 14,
}

SAMPLE_ITEMS: list[dict[str, Any]] = [
    {
        'description': 'Dienstleistung Beispiel',
        'quantity': 2,
        'unit': 'Std',
        'unit_price': 150.00,
        'tax_rate': 19,
        'total_price': 300.00,
    },
]

SAMPLE_CONTACT: dict[str, str] = {
    'name': 'Muster GmbH',
    'street': 'Musterstr. 1',
    'zip': '12345',
    'city': 'Musterstadt',
}


def get_template_name(template_key: str | None) -> str:
    """Resolve template key, fallback to default."""
    if template_key and template_key in TEMPLATES:
        return template_key
    return DEFAULT_TEMPLATE


async def render_invoice_pdf(
    template_key: str,
    invoice: dict,
    items: list[dict],
    contact: dict,
    tenant: dict,
    *,
    logo_b64: str | None = None,
    kleinunternehmer: bool = False,
    notes: str | None = None,
    skonto_percent: float | None = None,
    skonto_days: int | None = None,
) -> bytes:
    """Render invoice HTML with chosen template and convert to PDF via Gotenberg."""
    tpl_info = TEMPLATES.get(template_key, TEMPLATES[DEFAULT_TEMPLATE])
    template = _jinja_env.get_template(tpl_info['file'])

    # Build logo data-URI if available
    logo_url: str | None = None
    if logo_b64:
        logo_url = f'data:image/png;base64,{logo_b64}'

    html = template.render(
        invoice=invoice,
        items=items,
        contact=contact,
        tenant=tenant,
        logo_url=logo_url,
        kleinunternehmer=kleinunternehmer,
        notes=notes,
        skonto_percent=skonto_percent,
        skonto_days=skonto_days,
    )

    return await _html_to_pdf(html)


async def render_preview_pdf(
    template_key: str,
    tenant: dict,
    *,
    logo_b64: str | None = None,
    kleinunternehmer: bool = False,
) -> bytes:
    """Render a sample invoice for template preview."""
    return await render_invoice_pdf(
        template_key,
        SAMPLE_INVOICE_DATA,
        SAMPLE_ITEMS,
        SAMPLE_CONTACT,
        tenant,
        logo_b64=logo_b64,
        kleinunternehmer=kleinunternehmer,
    )


async def _html_to_pdf(html: str) -> bytes:
    """Convert HTML to PDF via Gotenberg."""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            GOTENBERG_URL,
            files={'file': ('index.html', html.encode('utf-8'), 'text/html')},
            data={
                'marginTop': '0',
                'marginBottom': '0',
                'marginLeft': '0',
                'marginRight': '0',
            },
        )
        resp.raise_for_status()
        return resp.content


async def get_company_data_for_template(user_id: str, tenant_id: str) -> dict[str, str]:
    """Load company data for template rendering.

    Primary source: frya_business_profile (canonical business data).
    Fallback: frya_user_preferences (legacy).
    """
    try:
        import asyncpg
        from app.dependencies import get_settings
        settings = get_settings()
        if settings.database_url.startswith('memory://'):
            return {'company_name': 'Meine Firma'}
        conn = await asyncpg.connect(settings.database_url)
        try:
            # Primary: frya_business_profile
            bp_row = await conn.fetchrow(
                "SELECT * FROM frya_business_profile "
                "WHERE tenant_id IN ($1, 'default', '') "
                "ORDER BY CASE WHEN tenant_id = $1 THEN 0 WHEN tenant_id = 'default' THEN 1 ELSE 2 END "
                "LIMIT 1",
                tenant_id or 'default',
            )
            if bp_row:
                bp = dict(bp_row)
                # Determine tax_id vs tax_number
                ust_id = bp.get('ust_id') or ''
                tax_number = bp.get('tax_number') or ''
                return {
                    'company_name': bp.get('company_name') or 'Meine Firma',
                    'legal_form': bp.get('company_legal_form') or '',
                    'street': bp.get('company_street') or '',
                    'zip': bp.get('company_zip') or '',
                    'city': bp.get('company_city') or '',
                    'tax_id': ust_id,
                    'tax_number': tax_number,
                    'iban': bp.get('company_iban') or '',
                    'bic': bp.get('company_bic') or '',
                    'bank': bp.get('company_bank') or '',
                    'phone': bp.get('company_phone') or '',
                    'email': bp.get('company_email') or '',
                    'website': bp.get('company_website') or '',
                }

            # Fallback: frya_user_preferences (legacy)
            rows = await conn.fetch(
                "SELECT key, value FROM frya_user_preferences "
                "WHERE tenant_id IN ($1, 'default', '') "
                "ORDER BY CASE WHEN tenant_id = $1 THEN 0 ELSE 1 END",
                tenant_id or 'default',
            )
            prefs: dict[str, str] = {}
            for r in reversed(rows):
                prefs[r['key']] = r['value']
        finally:
            await conn.close()
    except Exception as exc:
        logger.warning('Failed to load company data: %s', exc)
        prefs = {}

    # Build tenant dict from preferences (legacy path)
    street = prefs.get('company_street', '')
    zip_city = prefs.get('company_zip_city', '')
    if not street and not zip_city:
        addr = prefs.get('company_address', '')
        if addr:
            parts = addr.split(',', 1)
            street = parts[0].strip() if parts else addr
            zip_city = parts[1].strip() if len(parts) > 1 else ''

    _zip = ''
    _city = ''
    if zip_city:
        import re
        m = re.match(r'(\d{5})\s+(.*)', zip_city)
        if m:
            _zip = m.group(1)
            _city = m.group(2)
        else:
            _city = zip_city

    _tn = prefs.get('tax_number', '')
    return {
        'company_name': prefs.get('company_name', 'Meine Firma'),
        'legal_form': prefs.get('company_legal_form', ''),
        'street': street,
        'zip': _zip,
        'city': _city,
        'tax_id': _tn if _tn.startswith('DE') else '',
        'tax_number': _tn if not _tn.startswith('DE') else '',
        'iban': prefs.get('company_iban', ''),
        'bic': prefs.get('company_bic', ''),
        'bank': prefs.get('company_bank', ''),
        'phone': prefs.get('company_phone', ''),
        'email': prefs.get('company_email', ''),
        'website': prefs.get('company_website', ''),
    }


async def get_company_logo_b64(user_id: str, tenant_id: str) -> str | None:
    """Load logo Base64 from user preferences."""
    try:
        import asyncpg
        from app.dependencies import get_settings
        settings = get_settings()
        if settings.database_url.startswith('memory://'):
            return None
        conn = await asyncpg.connect(settings.database_url)
        try:
            row = await conn.fetchrow(
                "SELECT value FROM frya_user_preferences "
                "WHERE tenant_id IN ($1, 'default', '') AND key = 'company_logo_b64' "
                "ORDER BY CASE WHEN tenant_id = $1 THEN 0 ELSE 1 END LIMIT 1",
                tenant_id or 'default',
            )
            return row['value'] if row else None
        finally:
            await conn.close()
    except Exception as exc:
        logger.warning('Failed to load logo: %s', exc)
        return None
