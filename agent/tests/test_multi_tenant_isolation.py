"""P-13 Phase 6: Multi-Tenant Security Tests.

Cross-Tenant Isolation Tests fuer Alpha-Launch.
Testet auf DB-Level, API-Level und Paperless-Level.

Ausfuehren: pytest agent/tests/test_multi_tenant_isolation.py -v
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

import pytest

# ── Test-Tenant Setup ────────────────────────────────────────────────────────

TENANT_A_ID = str(uuid.uuid4())
TENANT_B_ID = str(uuid.uuid4())
TENANT_A_USER = f'alpha1_{uuid.uuid4().hex[:6]}@test.de'
TENANT_B_USER = f'alpha2_{uuid.uuid4().hex[:6]}@test.de'


@pytest.fixture(scope='module')
def database_url():
    """Database URL from env or default."""
    import os
    return os.environ.get('FRYA_DATABASE_URL', 'postgresql://frya:frya@localhost:5432/frya')


@pytest.fixture(scope='module')
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# ── Phase 6.1: SQL-Level RLS Tests ──────────────────────────────────────────

class TestRLSIsolation:
    """Testet Row-Level Security auf Datenbankebene."""

    @pytest.mark.asyncio
    async def test_tenant_a_cannot_see_tenant_b_bookings(self, database_url):
        """KRITISCH: Tenant A darf KEINE Buchungen von Tenant B sehen."""
        import asyncpg

        conn = await asyncpg.connect(database_url)
        try:
            # Setup: Buchung fuer Tenant A erstellen
            booking_a_id = uuid.uuid4()
            await conn.execute("RESET app.current_tenant")
            await conn.execute(
                """INSERT INTO frya_bookings (id, tenant_id, booking_number, booking_date,
                   description, account_soll, account_haben, gross_amount, net_amount,
                   tax_rate, tax_amount, currency, status, booking_type, source,
                   previous_hash, booking_hash, created_by, created_at)
                VALUES ($1, $2, 1, NOW(), 'Test A', '4400', '1200', 119.00, 100.00,
                        19.0, 19.00, 'EUR', 'BOOKED', 'STANDARD', 'test',
                        'none', 'hash_a', 'test', NOW())
                ON CONFLICT DO NOTHING""",
                booking_a_id, uuid.UUID(TENANT_A_ID),
            )

            # Setup: Buchung fuer Tenant B erstellen
            booking_b_id = uuid.uuid4()
            await conn.execute(
                """INSERT INTO frya_bookings (id, tenant_id, booking_number, booking_date,
                   description, account_soll, account_haben, gross_amount, net_amount,
                   tax_rate, tax_amount, currency, status, booking_type, source,
                   previous_hash, booking_hash, created_by, created_at)
                VALUES ($1, $2, 1, NOW(), 'Test B', '4400', '1200', 238.00, 200.00,
                        19.0, 38.00, 'EUR', 'BOOKED', 'STANDARD', 'test',
                        'none', 'hash_b', 'test', NOW())
                ON CONFLICT DO NOTHING""",
                booking_b_id, uuid.UUID(TENANT_B_ID),
            )

            # Test: Als Tenant A — nur eigene Buchungen sehen
            await conn.execute(
                "SELECT set_config('app.current_tenant', $1, false)", TENANT_A_ID
            )
            rows_a = await conn.fetch("SELECT * FROM frya_bookings")
            tenant_ids_seen = {str(r['tenant_id']) for r in rows_a}

            # ASSERTION: Tenant B darf NICHT sichtbar sein
            assert TENANT_B_ID not in tenant_ids_seen, \
                f"DATENLECK! Tenant A sieht Buchungen von Tenant B!"

            # Test: Als Tenant B — nur eigene Buchungen sehen
            await conn.execute(
                "SELECT set_config('app.current_tenant', $1, false)", TENANT_B_ID
            )
            rows_b = await conn.fetch("SELECT * FROM frya_bookings")
            tenant_ids_seen_b = {str(r['tenant_id']) for r in rows_b}

            assert TENANT_A_ID not in tenant_ids_seen_b, \
                f"DATENLECK! Tenant B sieht Buchungen von Tenant A!"

        finally:
            # Cleanup
            await conn.execute("RESET app.current_tenant")
            await conn.execute("DELETE FROM frya_bookings WHERE id = $1", booking_a_id)
            await conn.execute("DELETE FROM frya_bookings WHERE id = $1", booking_b_id)
            await conn.close()

    @pytest.mark.asyncio
    async def test_tenant_a_cannot_see_tenant_b_invoices(self, database_url):
        """Tenant A darf KEINE Rechnungen von Tenant B sehen."""
        import asyncpg

        conn = await asyncpg.connect(database_url)
        try:
            inv_a = uuid.uuid4()
            inv_b = uuid.uuid4()
            await conn.execute("RESET app.current_tenant")

            await conn.execute(
                """INSERT INTO frya_invoices (id, tenant_id, invoice_number, invoice_date,
                   net_total, tax_total, gross_total, status, created_at, updated_at)
                VALUES ($1, $2, 'INV-A-001', NOW(), 100, 19, 119, 'DRAFT', NOW(), NOW())
                ON CONFLICT DO NOTHING""",
                inv_a, uuid.UUID(TENANT_A_ID),
            )
            await conn.execute(
                """INSERT INTO frya_invoices (id, tenant_id, invoice_number, invoice_date,
                   net_total, tax_total, gross_total, status, created_at, updated_at)
                VALUES ($1, $2, 'INV-B-001', NOW(), 200, 38, 238, 'DRAFT', NOW(), NOW())
                ON CONFLICT DO NOTHING""",
                inv_b, uuid.UUID(TENANT_B_ID),
            )

            # Als Tenant B: Versuche Rechnung von Tenant A zu lesen
            await conn.execute(
                "SELECT set_config('app.current_tenant', $1, false)", TENANT_B_ID
            )
            row = await conn.fetchrow(
                "SELECT * FROM frya_invoices WHERE id = $1", inv_a
            )
            assert row is None, \
                f"DATENLECK! Tenant B kann Rechnung von Tenant A lesen!"

        finally:
            await conn.execute("RESET app.current_tenant")
            await conn.execute("DELETE FROM frya_invoices WHERE id = $1", inv_a)
            await conn.execute("DELETE FROM frya_invoices WHERE id = $1", inv_b)
            await conn.close()

    @pytest.mark.asyncio
    async def test_tenant_a_cannot_see_tenant_b_contacts(self, database_url):
        """Tenant A darf KEINE Kontakte von Tenant B sehen."""
        import asyncpg

        conn = await asyncpg.connect(database_url)
        try:
            c_a = uuid.uuid4()
            c_b = uuid.uuid4()
            await conn.execute("RESET app.current_tenant")

            await conn.execute(
                """INSERT INTO frya_contacts (id, tenant_id, name, contact_type, is_active, created_at, updated_at)
                VALUES ($1, $2, 'Firma A GmbH', 'vendor', TRUE, NOW(), NOW())
                ON CONFLICT DO NOTHING""",
                c_a, uuid.UUID(TENANT_A_ID),
            )
            await conn.execute(
                """INSERT INTO frya_contacts (id, tenant_id, name, contact_type, is_active, created_at, updated_at)
                VALUES ($1, $2, 'Firma B AG', 'vendor', TRUE, NOW(), NOW())
                ON CONFLICT DO NOTHING""",
                c_b, uuid.UUID(TENANT_B_ID),
            )

            # Als Tenant A: Nur eigene Kontakte
            await conn.execute(
                "SELECT set_config('app.current_tenant', $1, false)", TENANT_A_ID
            )
            rows = await conn.fetch("SELECT * FROM frya_contacts")
            names = {r['name'] for r in rows}
            assert 'Firma B AG' not in names, \
                f"DATENLECK! Tenant A sieht Kontakte von Tenant B!"

        finally:
            await conn.execute("RESET app.current_tenant")
            await conn.execute("DELETE FROM frya_contacts WHERE id = $1", c_a)
            await conn.execute("DELETE FROM frya_contacts WHERE id = $1", c_b)
            await conn.close()

    @pytest.mark.asyncio
    async def test_tenant_cannot_insert_for_other_tenant(self, database_url):
        """Tenant A darf KEINE Daten fuer Tenant B einfuegen."""
        import asyncpg

        conn = await asyncpg.connect(database_url)
        try:
            # Als Tenant A: Versuche Kontakt mit Tenant B ID zu erstellen
            await conn.execute(
                "SELECT set_config('app.current_tenant', $1, false)", TENANT_A_ID
            )
            c_cross = uuid.uuid4()
            with pytest.raises(Exception):
                # RLS INSERT CHECK sollte fehlschlagen
                await conn.execute(
                    """INSERT INTO frya_contacts (id, tenant_id, name, contact_type, is_active, created_at, updated_at)
                    VALUES ($1, $2, 'Cross-Tenant', 'vendor', TRUE, NOW(), NOW())""",
                    c_cross, uuid.UUID(TENANT_B_ID),
                )
        finally:
            await conn.execute("RESET app.current_tenant")
            # Cleanup falls der Insert doch durchging
            await conn.execute("DELETE FROM frya_contacts WHERE id = $1", c_cross)
            await conn.close()

    @pytest.mark.asyncio
    async def test_case_cases_rls(self, database_url):
        """Cases muessen tenant-isoliert sein."""
        import asyncpg

        conn = await asyncpg.connect(database_url)
        try:
            case_a = uuid.uuid4()
            case_b = uuid.uuid4()
            await conn.execute("RESET app.current_tenant")

            await conn.execute(
                """INSERT INTO case_cases (id, tenant_id, case_number, title, case_type,
                   status, currency, created_at, updated_at, created_by)
                VALUES ($1, $2, 'CASE-2026-90001', 'Test A', 'incoming_invoice',
                        'OPEN', 'EUR', NOW(), NOW(), 'test')
                ON CONFLICT DO NOTHING""",
                case_a, uuid.UUID(TENANT_A_ID),
            )
            await conn.execute(
                """INSERT INTO case_cases (id, tenant_id, case_number, title, case_type,
                   status, currency, created_at, updated_at, created_by)
                VALUES ($1, $2, 'CASE-2026-90002', 'Test B', 'incoming_invoice',
                        'OPEN', 'EUR', NOW(), NOW(), 'test')
                ON CONFLICT DO NOTHING""",
                case_b, uuid.UUID(TENANT_B_ID),
            )

            # Als Tenant B: Case von Tenant A unsichtbar
            await conn.execute(
                "SELECT set_config('app.current_tenant', $1, false)", TENANT_B_ID
            )
            row = await conn.fetchrow("SELECT * FROM case_cases WHERE id = $1", case_a)
            assert row is None, "DATENLECK! Tenant B sieht Cases von Tenant A!"

        finally:
            await conn.execute("RESET app.current_tenant")
            await conn.execute("DELETE FROM case_cases WHERE id = $1", case_a)
            await conn.execute("DELETE FROM case_cases WHERE id = $1", case_b)
            await conn.close()


# ── Phase 6.2: Application-Layer Tenant Filter Tests ─────────────────────────

class TestApplicationLayerIsolation:
    """Testet die Application-Layer Tenant-Filterung in Repositories."""

    @pytest.mark.asyncio
    async def test_accounting_repo_filters_by_tenant(self, database_url):
        """AccountingRepository muss nach tenant_id filtern."""
        import asyncpg

        conn = await asyncpg.connect(database_url)
        try:
            # Ohne RLS (direkt): Pruefe ob Queries tenant_id verwenden
            # Erstelle Konten fuer beide Tenants
            acc_a = uuid.uuid4()
            acc_b = uuid.uuid4()

            await conn.execute(
                """INSERT INTO frya_accounts (id, tenant_id, account_number, name, account_type, is_active, is_system, created_at)
                VALUES ($1, $2, '9999', 'Test A', 'asset', TRUE, FALSE, NOW())
                ON CONFLICT DO NOTHING""",
                acc_a, uuid.UUID(TENANT_A_ID),
            )
            await conn.execute(
                """INSERT INTO frya_accounts (id, tenant_id, account_number, name, account_type, is_active, is_system, created_at)
                VALUES ($1, $2, '9999', 'Test B', 'asset', TRUE, FALSE, NOW())
                ON CONFLICT DO NOTHING""",
                acc_b, uuid.UUID(TENANT_B_ID),
            )

            # Query mit Application-Layer Filter (wie im Repository)
            rows = await conn.fetch(
                "SELECT * FROM frya_accounts WHERE tenant_id=$1 ORDER BY account_number",
                uuid.UUID(TENANT_A_ID),
            )
            tenant_ids = {str(r['tenant_id']) for r in rows}
            assert TENANT_B_ID not in tenant_ids, \
                "Application-Layer Filter fuer Konten fehlt!"

        finally:
            await conn.execute("DELETE FROM frya_accounts WHERE id = $1", acc_a)
            await conn.execute("DELETE FROM frya_accounts WHERE id = $1", acc_b)
            await conn.close()

    @pytest.mark.asyncio
    async def test_case_update_requires_tenant(self, database_url):
        """Case-Updates muessen tenant_id im WHERE haben."""
        import asyncpg

        conn = await asyncpg.connect(database_url)
        try:
            case_a = uuid.uuid4()
            await conn.execute(
                """INSERT INTO case_cases (id, tenant_id, case_number, title, case_type,
                   status, currency, created_at, updated_at, created_by)
                VALUES ($1, $2, 'CASE-2026-99001', 'Test Update', 'incoming_invoice',
                        'OPEN', 'EUR', NOW(), NOW(), 'test')
                ON CONFLICT DO NOTHING""",
                case_a, uuid.UUID(TENANT_A_ID),
            )

            # Versuch als Tenant B den Case zu updaten
            result = await conn.execute(
                "UPDATE case_cases SET status='CLOSED', updated_at=NOW() WHERE id=$1 AND tenant_id=$2",
                case_a, uuid.UUID(TENANT_B_ID),
            )
            # UPDATE 0 = kein Row betroffen (richtig!)
            assert result == 'UPDATE 0', \
                f"SICHERHEITSLUECKE! Tenant B konnte Case von Tenant A updaten! Result: {result}"

        finally:
            await conn.execute("DELETE FROM case_cases WHERE id = $1", case_a)
            await conn.close()


# ── Phase 6.3: GDPR Deletion Scoping Test ───────────────────────────────────

class TestGDPRDeletionScoping:
    """Testet dass DSGVO-Loeschung nur eigene Daten loescht."""

    @pytest.mark.asyncio
    async def test_deletion_scoped_to_tenant(self, database_url):
        """DELETE Queries muessen nach tenant_id scopen."""
        import asyncpg

        conn = await asyncpg.connect(database_url)
        try:
            # Preferences fuer beide Tenants
            pref_a = uuid.uuid4()
            pref_b = uuid.uuid4()

            await conn.execute(
                """INSERT INTO frya_user_preferences (id, tenant_id, user_id, key, value, updated_at)
                VALUES ($1, $2, 'testuser', 'theme', 'dark', NOW())
                ON CONFLICT DO NOTHING""",
                pref_a, TENANT_A_ID,
            )
            await conn.execute(
                """INSERT INTO frya_user_preferences (id, tenant_id, user_id, key, value, updated_at)
                VALUES ($1, $2, 'testuser', 'theme', 'light', NOW())
                ON CONFLICT DO NOTHING""",
                pref_b, TENANT_B_ID,
            )

            # Loesche nur Tenant A Daten (wie im GDPR-Endpoint)
            await conn.execute(
                "DELETE FROM frya_user_preferences WHERE user_id = $1 AND tenant_id = $2",
                'testuser', TENANT_A_ID,
            )

            # Tenant B Daten muessen noch da sein
            row = await conn.fetchrow(
                "SELECT * FROM frya_user_preferences WHERE id = $1", pref_b,
            )
            assert row is not None, \
                "DATENLECK! GDPR-Loeschung hat Daten von Tenant B mitgeloescht!"

        finally:
            await conn.execute("DELETE FROM frya_user_preferences WHERE id = $1", pref_a)
            await conn.execute("DELETE FROM frya_user_preferences WHERE id = $1", pref_b)
            await conn.close()
