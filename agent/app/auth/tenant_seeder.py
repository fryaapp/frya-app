"""Seed default data for new Alpha-Tester tenants.

Each new customer tenant gets:
- SKR03 Kontenrahmen (36 standard accounts)
- Default user preferences (dark theme, German language)
- Empty business profile placeholder
"""
from __future__ import annotations

import logging
import uuid
from typing import Sequence

import asyncpg

logger = logging.getLogger(__name__)

# ── SKR03 seed accounts: (account_number, name, account_type) ────────────
SKR03_SEED_ACCOUNTS: Sequence[tuple[str, str, str]] = (
    ('1000', 'Kasse', 'asset'),
    ('1200', 'Bank', 'asset'),
    ('1400', 'Forderungen aus L+L', 'asset'),
    ('1600', 'Verbindlichkeiten aus L+L', 'liability'),
    ('1700', 'Sonstige Verbindlichkeiten', 'liability'),
    ('1800', 'USt-Vorauszahlungen', 'asset'),
    ('1776', 'Umsatzsteuer 19%', 'liability'),
    ('1771', 'Umsatzsteuer 7%', 'liability'),
    ('1570', 'Vorsteuer 19%', 'asset'),
    ('1571', 'Vorsteuer 7%', 'asset'),
    ('2000', 'Aufwendungen fuer Roh-/Hilfsstoffe', 'expense'),
    ('3300', 'Wareneingang 7%', 'expense'),
    ('3400', 'Wareneingang 19%', 'expense'),
    ('4100', 'Loehne und Gehaelter', 'expense'),
    ('4120', 'Gehaelter', 'expense'),
    ('4130', 'Gesetzliche Sozialaufwendungen', 'expense'),
    ('4200', 'Raumkosten', 'expense'),
    ('4210', 'Miete', 'expense'),
    ('4250', 'Reinigung', 'expense'),
    ('4300', 'Versicherungen', 'expense'),
    ('4400', 'Kfz-Kosten', 'expense'),
    ('4500', 'Reparaturen', 'expense'),
    ('4600', 'Werbekosten', 'expense'),
    ('4650', 'Bewirtung', 'expense'),
    ('4700', 'Porto', 'expense'),
    ('4800', 'Telefon/Internet', 'expense'),
    ('4900', 'Verschiedene betriebliche Aufwendungen', 'expense'),
    ('4910', 'Buerokosten', 'expense'),
    ('4920', 'Rechts-/Beratungskosten', 'expense'),
    ('4950', 'Abschreibungen', 'expense'),
    ('8000', 'Erloese', 'revenue'),
    ('8100', 'Steuerfreie Erloese', 'revenue'),
    ('8300', 'Erloese 7%', 'revenue'),
    ('8400', 'Erloese 19%', 'revenue'),
    ('8900', 'Sonstige Erloese', 'revenue'),
    ('9000', 'Eigenkapital', 'equity'),
)


async def seed_tenant_defaults(
    database_url: str,
    tenant_id: str,
    username: str,
) -> None:
    """Seed default data for a freshly created tenant.

    Called right after tenant + user creation in the invitation flow.
    All inserts use ON CONFLICT DO NOTHING so the function is idempotent.
    """
    conn = await asyncpg.connect(database_url)
    try:
        tid = uuid.UUID(tenant_id)

        # 1. SKR03 Kontenrahmen ------------------------------------------------
        for account_number, name, account_type in SKR03_SEED_ACCOUNTS:
            await conn.execute(
                """
                INSERT INTO frya_accounts
                    (id, tenant_id, account_number, name, account_type,
                     is_active, is_system, created_at)
                VALUES ($1, $2, $3, $4, $5, TRUE, TRUE, NOW())
                ON CONFLICT (tenant_id, account_number) DO NOTHING
                """,
                uuid.uuid4(), tid, account_number, name, account_type,
            )

        # 2. Default user preferences -----------------------------------------
        defaults = [
            ('theme', 'dark'),
            ('language', 'de'),
            ('display_name', username),
        ]
        for key, value in defaults:
            await conn.execute(
                """
                INSERT INTO frya_user_preferences
                    (id, tenant_id, user_id, key, value, updated_at)
                VALUES ($1, $2, $3, $4, $5, NOW())
                ON CONFLICT (tenant_id, user_id, key) DO NOTHING
                """,
                str(uuid.uuid4()), tenant_id, username, key, value,
            )

        # 3. Empty business profile placeholder --------------------------------
        await conn.execute(
            """
            INSERT INTO frya_business_profile
                (user_id, tenant_id, company_name, created_at, updated_at)
            VALUES ($1, $2, '', NOW(), NOW())
            ON CONFLICT (user_id, tenant_id) DO NOTHING
            """,
            username, tenant_id,
        )

        logger.info(
            'Tenant %s seeded: %d accounts + user defaults for %s',
            tenant_id, len(SKR03_SEED_ACCOUNTS), username,
        )
    finally:
        await conn.close()
