"""Accounting repository — PostgreSQL storage for bookings, contacts, accounts, etc."""
from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from app.accounting.models import (
    Account, AccountingOpenItem, Booking, Contact, CostCenter,
    Invoice, InvoiceItem, Project,
)

logger = logging.getLogger(__name__)


# ── SKR03 Seed Data ──────────────────────────────────────────────────────────

SKR03_SEED: list[tuple[str, str, str, float | None]] = [
    # Aktiva
    ('1000', 'Kasse', 'ASSET', None),
    ('1200', 'Bank', 'ASSET', None),
    ('1400', 'Forderungen aus Lieferungen und Leistungen', 'ASSET', None),
    ('1571', 'Abziehbare Vorsteuer 7%', 'ASSET', 7.00),
    ('1576', 'Abziehbare Vorsteuer 19%', 'ASSET', 19.00),
    # Passiva
    ('1600', 'Verbindlichkeiten aus Lieferungen und Leistungen', 'LIABILITY', None),
    ('1776', 'Umsatzsteuer 19%', 'LIABILITY', 19.00),
    ('1771', 'Umsatzsteuer 7%', 'LIABILITY', 7.00),
    # Aufwand
    ('3300', 'Wareneingang 19% Vorsteuer', 'EXPENSE', 19.00),
    ('3400', 'Wareneingang 7% Vorsteuer', 'EXPENSE', 7.00),
    ('4100', 'Löhne und Gehälter', 'EXPENSE', None),
    ('4200', 'Raumkosten/Miete', 'EXPENSE', 19.00),
    ('4210', 'Bürobedarf', 'EXPENSE', 19.00),
    ('4300', 'Versicherungen', 'EXPENSE', 0.00),
    ('4500', 'Kfz-Kosten', 'EXPENSE', 19.00),
    ('4510', 'Kfz-Steuern', 'EXPENSE', 0.00),
    ('4520', 'Kfz-Versicherungen', 'EXPENSE', 0.00),
    ('4530', 'Kfz-Laufende Kosten', 'EXPENSE', 19.00),
    ('4600', 'Werbekosten', 'EXPENSE', 19.00),
    ('4650', 'Bewirtungskosten', 'EXPENSE', 19.00),
    ('4660', 'Reisekosten', 'EXPENSE', 19.00),
    ('4900', 'Sonstige betriebliche Aufwendungen', 'EXPENSE', 19.00),
    ('4910', 'Porto', 'EXPENSE', 19.00),
    ('4920', 'Telefon', 'EXPENSE', 19.00),
    ('4930', 'Bürobedarf (Sonstig)', 'EXPENSE', 19.00),
    ('4940', 'Zeitschriften/Bücher', 'EXPENSE', 7.00),
    ('4950', 'Software/IT', 'EXPENSE', 19.00),
    ('4955', 'Internet/Hosting', 'EXPENSE', 19.00),
    ('4960', 'Fortbildungskosten', 'EXPENSE', 19.00),
    ('4970', 'Nebenkosten des Geldverkehrs', 'EXPENSE', 0.00),
    ('4980', 'Buchführungskosten', 'EXPENSE', 19.00),
    # Erlöse
    ('7000', 'Umsatzerlöse 19% USt', 'REVENUE', 19.00),
    ('7010', 'Umsatzerlöse 7% USt', 'REVENUE', 7.00),
    ('7100', 'Steuerfreie Umsätze', 'REVENUE', 0.00),
    # Privat
    ('1800', 'Privatentnahmen', 'EQUITY', None),
    ('1890', 'Privateinlagen', 'EQUITY', None),
]


def compute_booking_hash(booking_data: dict, previous_hash: str) -> str:
    """GoBD: SHA-256 hash-chain for booking journal."""
    payload = json.dumps({
        'previous_hash': previous_hash,
        'booking_number': booking_data['booking_number'],
        'booking_date': str(booking_data['booking_date']),
        'account_soll': booking_data['account_soll'],
        'account_haben': booking_data['account_haben'],
        'gross_amount': str(booking_data['gross_amount']),
        'description': booking_data['description'],
        'created_at': str(booking_data['created_at']),
    }, sort_keys=True)
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


MAX_PAST_DAYS = 90

def validate_booking_date(booking_date: date) -> None:
    """GoBD: Booking date must not be in the future or too far in the past."""
    today = date.today()
    if booking_date > today:
        raise ValueError('Buchungsdatum darf nicht in der Zukunft liegen')
    if (today - booking_date).days > MAX_PAST_DAYS:
        raise ValueError(f'Buchungsdatum darf max {MAX_PAST_DAYS} Tage in der Vergangenheit liegen')


class AccountingRepository:
    def __init__(self, database_url: str) -> None:
        self._url = database_url
        self._is_memory = database_url.startswith('memory://')
        # In-memory stores for tests
        self._accounts: dict[uuid.UUID, Account] = {}
        self._contacts: dict[uuid.UUID, Contact] = {}
        self._bookings: dict[uuid.UUID, Booking] = {}
        self._cost_centers: dict[uuid.UUID, CostCenter] = {}
        self._projects: dict[uuid.UUID, Project] = {}
        self._open_items: dict[uuid.UUID, AccountingOpenItem] = {}
        self._invoices: dict[uuid.UUID, Invoice] = {}
        self._invoice_items: list[InvoiceItem] = []

    async def initialize(self) -> None:
        """Create all 8 accounting tables (idempotent)."""
        if self._is_memory:
            return
        import asyncpg
        conn = await asyncpg.connect(self._url)
        try:
            # 1. Accounts
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS frya_accounts (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    tenant_id UUID NOT NULL,
                    account_number VARCHAR(10) NOT NULL,
                    name VARCHAR(255) NOT NULL,
                    account_type VARCHAR(20) NOT NULL,
                    tax_rate DECIMAL(5,2),
                    parent_account VARCHAR(10),
                    is_active BOOLEAN DEFAULT TRUE,
                    is_system BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE(tenant_id, account_number)
                )
            """)

            # 2. Contacts
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS frya_contacts (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    tenant_id UUID NOT NULL,
                    name VARCHAR(500) NOT NULL,
                    display_name VARCHAR(255),
                    contact_type VARCHAR(20) NOT NULL DEFAULT 'VENDOR',
                    email VARCHAR(255),
                    phone VARCHAR(100),
                    address_street VARCHAR(255),
                    address_zip VARCHAR(20),
                    address_city VARCHAR(255),
                    address_country VARCHAR(100) DEFAULT 'Deutschland',
                    tax_id VARCHAR(50),
                    tax_number VARCHAR(50),
                    iban VARCHAR(50),
                    bic VARCHAR(20),
                    default_account VARCHAR(10),
                    communication_style VARCHAR(20) DEFAULT 'normal',
                    notes TEXT,
                    is_active BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_contacts_tenant ON frya_contacts(tenant_id)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_contacts_name ON frya_contacts(tenant_id, name)")

            # 3. Cost Centers
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS frya_cost_centers (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    tenant_id UUID NOT NULL,
                    name VARCHAR(255) NOT NULL,
                    description TEXT,
                    is_active BOOLEAN DEFAULT TRUE,
                    budget_amount DECIMAL(12,2),
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE(tenant_id, name)
                )
            """)

            # 4. Projects
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS frya_projects (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    tenant_id UUID NOT NULL,
                    name VARCHAR(255) NOT NULL,
                    description TEXT,
                    is_active BOOLEAN DEFAULT TRUE,
                    budget_amount DECIMAL(12,2),
                    start_date DATE,
                    end_date DATE,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE(tenant_id, name)
                )
            """)

            # 5. Bookings (HERZSTÜCK — GoBD: Write-Once!)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS frya_bookings (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    tenant_id UUID NOT NULL,
                    case_id UUID,
                    contact_id UUID REFERENCES frya_contacts(id),
                    cost_center_id UUID REFERENCES frya_cost_centers(id),
                    project_id UUID REFERENCES frya_projects(id),
                    booking_number INTEGER NOT NULL,
                    booking_date DATE NOT NULL,
                    document_date DATE,
                    description TEXT NOT NULL,
                    account_soll VARCHAR(10) NOT NULL,
                    account_soll_name VARCHAR(255),
                    account_haben VARCHAR(10) NOT NULL,
                    account_haben_name VARCHAR(255),
                    gross_amount DECIMAL(12,2) NOT NULL,
                    net_amount DECIMAL(12,2),
                    tax_rate DECIMAL(5,2),
                    tax_amount DECIMAL(12,2),
                    currency VARCHAR(3) DEFAULT 'EUR',
                    document_number VARCHAR(255),
                    document_ref VARCHAR(255),
                    booking_type VARCHAR(20) NOT NULL,
                    status VARCHAR(20) DEFAULT 'BOOKED',
                    source VARCHAR(20) DEFAULT 'frya-auto',
                    cancelled_booking_id UUID REFERENCES frya_bookings(id),
                    cancelled_at TIMESTAMPTZ,
                    cancelled_by VARCHAR(255),
                    cancel_reason TEXT,
                    previous_hash VARCHAR(64),
                    booking_hash VARCHAR(64) NOT NULL,
                    created_by VARCHAR(255),
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE(tenant_id, booking_number)
                )
            """)
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_bookings_tenant ON frya_bookings(tenant_id)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_bookings_date ON frya_bookings(tenant_id, booking_date)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_bookings_case ON frya_bookings(case_id)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_bookings_contact ON frya_bookings(contact_id)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_bookings_status ON frya_bookings(tenant_id, status)")

            # 6. Accounting Open Items
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS frya_accounting_open_items (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    tenant_id UUID NOT NULL,
                    contact_id UUID NOT NULL REFERENCES frya_contacts(id),
                    booking_id UUID REFERENCES frya_bookings(id),
                    case_id UUID,
                    item_type VARCHAR(20) NOT NULL,
                    original_amount DECIMAL(12,2) NOT NULL,
                    paid_amount DECIMAL(12,2) DEFAULT 0.00,
                    currency VARCHAR(3) DEFAULT 'EUR',
                    invoice_number VARCHAR(255),
                    invoice_date DATE,
                    due_date DATE,
                    status VARCHAR(20) DEFAULT 'OPEN',
                    dunning_level INTEGER DEFAULT 0,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW(),
                    paid_at TIMESTAMPTZ
                )
            """)
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_acc_oi_tenant ON frya_accounting_open_items(tenant_id)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_acc_oi_status ON frya_accounting_open_items(tenant_id, status)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_acc_oi_contact ON frya_accounting_open_items(contact_id)")

            # 7. Invoices
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS frya_invoices (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    tenant_id UUID NOT NULL,
                    contact_id UUID NOT NULL REFERENCES frya_contacts(id),
                    booking_id UUID REFERENCES frya_bookings(id),
                    cost_center_id UUID REFERENCES frya_cost_centers(id),
                    project_id UUID REFERENCES frya_projects(id),
                    invoice_number VARCHAR(50) NOT NULL,
                    invoice_date DATE NOT NULL,
                    due_date DATE,
                    net_total DECIMAL(12,2) NOT NULL,
                    tax_total DECIMAL(12,2) NOT NULL,
                    gross_total DECIMAL(12,2) NOT NULL,
                    status VARCHAR(20) DEFAULT 'DRAFT',
                    sent_at TIMESTAMPTZ,
                    sent_via VARCHAR(20),
                    pdf_path VARCHAR(500),
                    header_text TEXT,
                    footer_text TEXT,
                    payment_reference VARCHAR(255),
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE(tenant_id, invoice_number)
                )
            """)

            # 8. Invoice Items
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS frya_invoice_items (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    invoice_id UUID NOT NULL REFERENCES frya_invoices(id) ON DELETE CASCADE,
                    position INTEGER NOT NULL,
                    description TEXT NOT NULL,
                    quantity DECIMAL(10,3) DEFAULT 1,
                    unit VARCHAR(50) DEFAULT 'Stück',
                    unit_price DECIMAL(12,2) NOT NULL,
                    tax_rate DECIMAL(5,2) DEFAULT 19.00,
                    net_amount DECIMAL(12,2) NOT NULL,
                    tax_amount DECIMAL(12,2) NOT NULL,
                    gross_amount DECIMAL(12,2) NOT NULL,
                    account_number VARCHAR(10) DEFAULT '7000'
                )
            """)

            logger.info('Accounting tables initialized (8 tables)')
        finally:
            await conn.close()

    async def seed_skr03(self, tenant_id: uuid.UUID) -> int:
        """Seed SKR03 accounts for a tenant. Returns count of inserted accounts."""
        if self._is_memory:
            count = 0
            for num, name, atype, tax in SKR03_SEED:
                aid = uuid.uuid4()
                self._accounts[aid] = Account(
                    id=str(aid), tenant_id=str(tenant_id),
                    account_number=num, name=name, account_type=atype,
                    tax_rate=Decimal(str(tax)) if tax is not None else None,
                    is_system=True,
                )
                count += 1
            return count

        import asyncpg
        conn = await asyncpg.connect(self._url)
        count = 0
        try:
            for num, name, atype, tax in SKR03_SEED:
                try:
                    await conn.execute(
                        "INSERT INTO frya_accounts (tenant_id, account_number, name, account_type, tax_rate, is_system) "
                        "VALUES ($1, $2, $3, $4, $5, TRUE) ON CONFLICT (tenant_id, account_number) DO NOTHING",
                        tenant_id, num, name, atype,
                        Decimal(str(tax)) if tax is not None else None,
                    )
                    count += 1
                except Exception as exc:
                    logger.warning('SKR03 seed failed for %s: %s', num, exc)
        finally:
            await conn.close()
        return count

    async def get_next_booking_number(self, tenant_id: uuid.UUID) -> int:
        """GoBD: Gap-free booking numbers per tenant with advisory lock."""
        if self._is_memory:
            existing = [b.booking_number for b in self._bookings.values() if b.tenant_id == str(tenant_id)]
            return max(existing, default=0) + 1

        import asyncpg
        conn = await asyncpg.connect(self._url)
        try:
            lock_key = hash(str(tenant_id)) & 0x7FFFFFFF
            await conn.execute(f'SELECT pg_advisory_xact_lock({lock_key})')
            row = await conn.fetchrow(
                'SELECT COALESCE(MAX(booking_number), 0) + 1 as next_num FROM frya_bookings WHERE tenant_id = $1',
                tenant_id,
            )
            return row['next_num']
        finally:
            await conn.close()

    async def get_last_booking_hash(self, tenant_id: uuid.UUID) -> str:
        """Get the hash of the last booking for hash-chain continuation."""
        if self._is_memory:
            tenant_bookings = [b for b in self._bookings.values() if b.tenant_id == str(tenant_id)]
            if not tenant_bookings:
                return '0' * 64
            tenant_bookings.sort(key=lambda b: b.booking_number)
            return tenant_bookings[-1].booking_hash

        import asyncpg
        conn = await asyncpg.connect(self._url)
        try:
            row = await conn.fetchrow(
                'SELECT booking_hash FROM frya_bookings WHERE tenant_id = $1 ORDER BY booking_number DESC LIMIT 1',
                tenant_id,
            )
            return row['booking_hash'] if row else '0' * 64
        finally:
            await conn.close()

    async def insert_booking(self, tenant_id: uuid.UUID, data: dict) -> Booking:
        """Insert a new booking (GoBD: write-once, no updates)."""
        if self._is_memory:
            bid = uuid.uuid4()
            booking = Booking(id=str(bid), tenant_id=str(tenant_id), **data)
            self._bookings[bid] = booking
            return booking

        import asyncpg
        conn = await asyncpg.connect(self._url)
        try:
            row = await conn.fetchrow("""
                INSERT INTO frya_bookings (
                    tenant_id, case_id, contact_id, cost_center_id, project_id,
                    booking_number, booking_date, document_date, description,
                    account_soll, account_soll_name, account_haben, account_haben_name,
                    gross_amount, net_amount, tax_rate, tax_amount, currency,
                    document_number, document_ref, booking_type, status, source,
                    previous_hash, booking_hash, created_by
                ) VALUES (
                    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13,
                    $14, $15, $16, $17, $18, $19, $20, $21, $22, $23, $24, $25, $26
                ) RETURNING *
            """,
                tenant_id,
                uuid.UUID(data['case_id']) if data.get('case_id') else None,
                uuid.UUID(data['contact_id']) if data.get('contact_id') else None,
                uuid.UUID(data['cost_center_id']) if data.get('cost_center_id') else None,
                uuid.UUID(data['project_id']) if data.get('project_id') else None,
                data['booking_number'], data['booking_date'], data.get('document_date'),
                data['description'], data['account_soll'], data.get('account_soll_name'),
                data['account_haben'], data.get('account_haben_name'),
                data['gross_amount'], data.get('net_amount'), data.get('tax_rate'),
                data.get('tax_amount'), data.get('currency', 'EUR'),
                data.get('document_number'), data.get('document_ref'),
                data['booking_type'], data.get('status', 'BOOKED'),
                data.get('source', 'frya-auto'),
                data.get('previous_hash'), data['booking_hash'],
                data.get('created_by'),
            )
            return self._row_to_booking(dict(row))
        finally:
            await conn.close()

    async def list_bookings(
        self, tenant_id: uuid.UUID, *, date_from: date | None = None,
        date_to: date | None = None, status: str | None = None,
        limit: int = 100, offset: int = 0,
    ) -> list[Booking]:
        if self._is_memory:
            result = [b for b in self._bookings.values() if b.tenant_id == str(tenant_id)]
            if date_from:
                result = [b for b in result if b.booking_date >= date_from]
            if date_to:
                result = [b for b in result if b.booking_date <= date_to]
            if status:
                result = [b for b in result if b.status == status]
            result.sort(key=lambda b: b.booking_number, reverse=True)
            return result[offset:offset + limit]

        import asyncpg
        conn = await asyncpg.connect(self._url)
        try:
            query = 'SELECT * FROM frya_bookings WHERE tenant_id = $1'
            params: list = [tenant_id]
            idx = 2
            if date_from:
                query += f' AND booking_date >= ${idx}'
                params.append(date_from)
                idx += 1
            if date_to:
                query += f' AND booking_date <= ${idx}'
                params.append(date_to)
                idx += 1
            if status:
                query += f' AND status = ${idx}'
                params.append(status)
                idx += 1
            query += f' ORDER BY booking_number DESC LIMIT ${idx} OFFSET ${idx + 1}'
            params.extend([limit, offset])
            rows = await conn.fetch(query, *params)
            return [self._row_to_booking(dict(r)) for r in rows]
        finally:
            await conn.close()

    # ── Contact CRUD ─────────────────────────────────────────────────────────

    async def find_or_create_contact(self, tenant_id: uuid.UUID, name: str, **kwargs) -> Contact:
        if self._is_memory:
            for c in self._contacts.values():
                if c.tenant_id == str(tenant_id) and c.name.lower() == name.lower():
                    return c
            cid = uuid.uuid4()
            contact = Contact(id=str(cid), tenant_id=str(tenant_id), name=name, **kwargs)
            self._contacts[cid] = contact
            return contact

        import asyncpg
        conn = await asyncpg.connect(self._url)
        try:
            row = await conn.fetchrow(
                "SELECT * FROM frya_contacts WHERE tenant_id=$1 AND LOWER(name)=LOWER($2) LIMIT 1",
                tenant_id, name,
            )
            if row:
                return self._row_to_contact(dict(row))
            row = await conn.fetchrow(
                "INSERT INTO frya_contacts (tenant_id, name, display_name, contact_type) "
                "VALUES ($1, $2, $3, $4) RETURNING *",
                tenant_id, name, kwargs.get('display_name', name),
                kwargs.get('contact_type', 'VENDOR'),
            )
            return self._row_to_contact(dict(row))
        finally:
            await conn.close()

    async def list_contacts(self, tenant_id: uuid.UUID) -> list[Contact]:
        if self._is_memory:
            return [c for c in self._contacts.values() if c.tenant_id == str(tenant_id)]
        import asyncpg
        conn = await asyncpg.connect(self._url)
        try:
            rows = await conn.fetch("SELECT * FROM frya_contacts WHERE tenant_id=$1 ORDER BY name", tenant_id)
            return [self._row_to_contact(dict(r)) for r in rows]
        finally:
            await conn.close()

    # ── Accounts ─────────────────────────────────────────────────────────────

    async def list_accounts(self, tenant_id: uuid.UUID) -> list[Account]:
        if self._is_memory:
            return [a for a in self._accounts.values() if a.tenant_id == str(tenant_id)]
        import asyncpg
        conn = await asyncpg.connect(self._url)
        try:
            rows = await conn.fetch(
                "SELECT * FROM frya_accounts WHERE tenant_id=$1 ORDER BY account_number", tenant_id)
            return [Account(
                id=str(r['id']), tenant_id=str(r['tenant_id']),
                account_number=r['account_number'], name=r['name'],
                account_type=r['account_type'], tax_rate=r['tax_rate'],
                parent_account=r.get('parent_account'), is_active=r['is_active'],
                is_system=r['is_system'],
            ) for r in rows]
        finally:
            await conn.close()

    async def get_account_balance(
        self, tenant_id: uuid.UUID, account_number: str,
        date_from: date | None = None, date_to: date | None = None,
    ) -> Decimal:
        """Calculate balance for an account (Soll - Haben)."""
        if self._is_memory:
            soll = sum(b.gross_amount for b in self._bookings.values()
                       if b.tenant_id == str(tenant_id) and b.account_soll == account_number and b.status == 'BOOKED')
            haben = sum(b.gross_amount for b in self._bookings.values()
                        if b.tenant_id == str(tenant_id) and b.account_haben == account_number and b.status == 'BOOKED')
            return soll - haben

        import asyncpg
        conn = await asyncpg.connect(self._url)
        try:
            q_soll = "SELECT COALESCE(SUM(gross_amount), 0) FROM frya_bookings WHERE tenant_id=$1 AND account_soll=$2 AND status='BOOKED'"
            q_haben = "SELECT COALESCE(SUM(gross_amount), 0) FROM frya_bookings WHERE tenant_id=$1 AND account_haben=$2 AND status='BOOKED'"
            params = [tenant_id, account_number]
            soll = await conn.fetchval(q_soll, *params)
            haben = await conn.fetchval(q_haben, *params)
            return Decimal(str(soll)) - Decimal(str(haben))
        finally:
            await conn.close()

    # ── Row mappers ──────────────────────────────────────────────────────────

    @staticmethod
    def _row_to_booking(row: dict) -> Booking:
        return Booking(
            id=str(row['id']), tenant_id=str(row['tenant_id']),
            case_id=str(row['case_id']) if row.get('case_id') else None,
            contact_id=str(row['contact_id']) if row.get('contact_id') else None,
            cost_center_id=str(row['cost_center_id']) if row.get('cost_center_id') else None,
            project_id=str(row['project_id']) if row.get('project_id') else None,
            booking_number=row['booking_number'],
            booking_date=row['booking_date'], document_date=row.get('document_date'),
            description=row['description'],
            account_soll=row['account_soll'], account_soll_name=row.get('account_soll_name'),
            account_haben=row['account_haben'], account_haben_name=row.get('account_haben_name'),
            gross_amount=row['gross_amount'], net_amount=row.get('net_amount'),
            tax_rate=row.get('tax_rate'), tax_amount=row.get('tax_amount'),
            currency=row.get('currency', 'EUR'),
            document_number=row.get('document_number'), document_ref=row.get('document_ref'),
            booking_type=row['booking_type'], status=row.get('status', 'BOOKED'),
            source=row.get('source', 'frya-auto'),
            cancelled_booking_id=str(row['cancelled_booking_id']) if row.get('cancelled_booking_id') else None,
            cancelled_at=row.get('cancelled_at'), cancelled_by=row.get('cancelled_by'),
            cancel_reason=row.get('cancel_reason'),
            previous_hash=row.get('previous_hash'), booking_hash=row['booking_hash'],
            created_by=row.get('created_by'), created_at=row.get('created_at'),
        )

    @staticmethod
    def _row_to_contact(row: dict) -> Contact:
        return Contact(
            id=str(row['id']), tenant_id=str(row['tenant_id']),
            name=row['name'], display_name=row.get('display_name'),
            contact_type=row.get('contact_type', 'VENDOR'),
            email=row.get('email'), phone=row.get('phone'),
            address_street=row.get('address_street'), address_zip=row.get('address_zip'),
            address_city=row.get('address_city'), address_country=row.get('address_country', 'Deutschland'),
            tax_id=row.get('tax_id'), tax_number=row.get('tax_number'),
            iban=row.get('iban'), bic=row.get('bic'),
            default_account=row.get('default_account'), notes=row.get('notes'),
            is_active=row.get('is_active', True),
            created_at=row.get('created_at'), updated_at=row.get('updated_at'),
        )
