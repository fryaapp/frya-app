"""Business Profile Service: CRUD + Compliance fuer frya_business_profile.

Single Source of Truth fuer alle geschaeftsrelevanten Daten eines Users.
Ersetzt die losen Eintraege in frya_user_preferences.
"""
from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# Erlaubte Felder fuer upsert (Whitelist)
_ALLOWED_FIELDS = frozenset({
    'company_name', 'company_legal_form', 'company_street', 'company_zip',
    'company_city', 'tax_number', 'ust_id', 'tax_office', 'is_kleinunternehmer',
    'company_iban', 'company_bic', 'company_bank', 'company_email',
    'company_phone', 'company_website', 'default_payment_terms_days',
    'default_hourly_rate', 'default_service_description', 'invoice_template',
    'company_logo_b64', 'default_skonto_percent', 'default_skonto_days',
    'invoice_number_prefix', 'ust_voranmeldung', 'company_country',
    'default_tax_rate',
})

# Type casts for specific fields
_BOOLEAN_FIELDS = frozenset({'is_kleinunternehmer'})
_INTEGER_FIELDS = frozenset({'default_payment_terms_days', 'default_skonto_days', 'default_tax_rate'})
_DECIMAL_FIELDS = frozenset({'default_hourly_rate', 'default_skonto_percent'})


class BusinessProfileService:
    """CRUD + Compliance-Check fuer das Business-Profil."""

    async def get(self, user_id: str, tenant_id: str) -> dict | None:
        """Laedt das Business-Profil (mit tenant-Fallback)."""
        try:
            import asyncpg
            from app.dependencies import get_settings
            conn = await asyncpg.connect(get_settings().database_url)
            try:
                row = await conn.fetchrow(
                    "SELECT * FROM frya_business_profile "
                    "WHERE user_id = $1 AND tenant_id IN ($2, 'default', '') "
                    "ORDER BY CASE WHEN tenant_id = $2 THEN 0 WHEN tenant_id = 'default' THEN 1 ELSE 2 END "
                    "LIMIT 1",
                    user_id, tenant_id or 'default',
                )
                return dict(row) if row else None
            finally:
                await conn.close()
        except Exception as exc:
            logger.warning('BusinessProfileService.get failed: %s', exc)
            return None

    async def upsert_field(self, user_id: str, tenant_id: str, field: str, value: Any) -> None:
        """Setzt ein einzelnes Feld (nach Chat-Eingabe)."""
        if field not in _ALLOWED_FIELDS:
            raise ValueError(f"Feld '{field}' nicht erlaubt")

        # Type conversion
        if field in _BOOLEAN_FIELDS:
            if isinstance(value, str):
                value = value.lower() in ('true', 'ja', 'yes', '1')
        elif field in _INTEGER_FIELDS:
            value = int(value) if value else None
        elif field in _DECIMAL_FIELDS:
            value = float(str(value).replace(',', '.')) if value else None

        try:
            import asyncpg
            from app.dependencies import get_settings
            conn = await asyncpg.connect(get_settings().database_url)
            try:
                # Use parameterized query with dynamic column (safe: field is whitelisted)
                await conn.execute(
                    f"INSERT INTO frya_business_profile (user_id, tenant_id, {field}) "
                    f"VALUES ($1, $2, $3) "
                    f"ON CONFLICT (user_id, tenant_id) "
                    f"DO UPDATE SET {field} = $3, updated_at = NOW()",
                    user_id, tenant_id or 'default', value,
                )
            finally:
                await conn.close()
        except Exception as exc:
            logger.error('BusinessProfileService.upsert_field failed: %s', exc)
            raise

    async def upsert_fields(self, user_id: str, tenant_id: str, fields: dict[str, Any]) -> None:
        """Setzt mehrere Felder gleichzeitig."""
        for field, value in fields.items():
            if field in _ALLOWED_FIELDS:
                await self.upsert_field(user_id, tenant_id, field, value)

    async def get_for_template(self, user_id: str, tenant_id: str) -> dict[str, str]:
        """Laedt Profil-Daten im Format fuer Template-Rendering."""
        profile = await self.get(user_id, tenant_id)
        if not profile:
            return {'company_name': 'Meine Firma'}

        return {
            'company_name': profile.get('company_name') or 'Meine Firma',
            'legal_form': profile.get('company_legal_form') or '',
            'street': profile.get('company_street') or '',
            'zip': profile.get('company_zip') or '',
            'city': profile.get('company_city') or '',
            'tax_id': profile.get('ust_id') or '',
            'tax_number': profile.get('tax_number') or '',
            'iban': profile.get('company_iban') or '',
            'bic': profile.get('company_bic') or '',
            'bank': profile.get('company_bank') or '',
            'phone': profile.get('company_phone') or '',
            'email': profile.get('company_email') or '',
            'website': profile.get('company_website') or '',
        }
