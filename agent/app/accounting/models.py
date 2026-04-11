"""Accounting domain models."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

AccountType = Literal['EXPENSE', 'REVENUE', 'ASSET', 'LIABILITY', 'EQUITY']
ContactType = Literal['VENDOR', 'CUSTOMER', 'BOTH']
ContactCategory = Literal['CUSTOMER', 'SUPPLIER', 'BOTH', 'AUTHORITY', 'OTHER']
BookingType = Literal['INCOME', 'EXPENSE', 'TRANSFER', 'CORRECTION', 'REGULAR']
BookingStatus = Literal['DRAFT', 'BOOKED', 'CANCELLED']
OpenItemType = Literal['RECEIVABLE', 'PAYABLE']
OpenItemStatus = Literal['OPEN', 'PARTIALLY_PAID', 'PAID', 'OVERDUE', 'CANCELLED']
InvoiceStatus = Literal['DRAFT', 'SENT', 'PAID', 'OVERDUE', 'CANCELLED', 'REVERSED', 'VOID']


class Account(BaseModel):
    id: str
    tenant_id: str
    account_number: str
    name: str
    account_type: AccountType
    tax_rate: Decimal | None = None
    parent_account: str | None = None
    is_active: bool = True
    is_system: bool = False


class Contact(BaseModel):
    id: str
    tenant_id: str
    name: str
    display_name: str | None = None
    contact_type: ContactType = 'VENDOR'
    email: str | None = None
    phone: str | None = None
    address_street: str | None = None
    address_zip: str | None = None
    address_city: str | None = None
    address_country: str = 'Deutschland'
    tax_id: str | None = None
    tax_number: str | None = None
    iban: str | None = None
    bic: str | None = None
    default_account: str | None = None
    category: ContactCategory = 'OTHER'
    notes: str | None = None
    default_payment_terms_days: int = 14
    default_skonto_percent: Decimal | None = None
    default_skonto_days: int | None = None
    tags: list[str] = Field(default_factory=list)
    paperless_correspondent_id: int | None = None
    is_active: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None


class Booking(BaseModel):
    id: str
    tenant_id: str
    case_id: str | None = None
    contact_id: str | None = None
    cost_center_id: str | None = None
    project_id: str | None = None
    booking_number: int
    booking_date: date
    document_date: date | None = None
    description: str
    account_soll: str
    account_soll_name: str | None = None
    account_haben: str
    account_haben_name: str | None = None
    gross_amount: Decimal
    net_amount: Decimal | None = None
    tax_rate: Decimal | None = None
    tax_amount: Decimal | None = None
    currency: str = 'EUR'
    document_number: str | None = None
    document_ref: str | None = None
    booking_type: BookingType
    status: BookingStatus = 'BOOKED'
    source: str = 'frya-auto'
    cancelled_booking_id: str | None = None
    cancelled_at: datetime | None = None
    cancelled_by: str | None = None
    cancel_reason: str | None = None
    previous_hash: str | None = None
    booking_hash: str
    created_by: str | None = None
    created_at: datetime | None = None


class CostCenter(BaseModel):
    id: str
    tenant_id: str
    name: str
    description: str | None = None
    is_active: bool = True
    budget_amount: Decimal | None = None


class Project(BaseModel):
    id: str
    tenant_id: str
    name: str
    description: str | None = None
    is_active: bool = True
    budget_amount: Decimal | None = None
    start_date: date | None = None
    end_date: date | None = None


class AccountingOpenItem(BaseModel):
    id: str
    tenant_id: str
    contact_id: str
    contact_name: str | None = None  # P-08 A3: resolved via JOIN
    booking_id: str | None = None
    case_id: str | None = None
    item_type: OpenItemType
    original_amount: Decimal
    paid_amount: Decimal = Decimal('0.00')
    currency: str = 'EUR'
    invoice_number: str | None = None
    invoice_date: date | None = None
    due_date: date | None = None
    status: OpenItemStatus = 'OPEN'
    dunning_level: int = 0
    created_at: datetime | None = None
    paid_at: datetime | None = None


class Invoice(BaseModel):
    id: str
    tenant_id: str
    contact_id: str
    booking_id: str | None = None
    cost_center_id: str | None = None
    project_id: str | None = None
    invoice_number: str
    invoice_date: date
    due_date: date | None = None
    net_total: Decimal
    tax_total: Decimal
    gross_total: Decimal
    status: InvoiceStatus = 'DRAFT'
    pdf_path: str | None = None
    header_text: str | None = None
    footer_text: str | None = None
    payment_reference: str | None = None
    created_at: datetime | None = None


class InvoiceItem(BaseModel):
    id: str
    invoice_id: str
    position: int
    description: str
    quantity: Decimal = Decimal('1')
    unit: str = 'Stück'
    unit_price: Decimal
    tax_rate: Decimal = Decimal('19.00')
    net_amount: Decimal
    tax_amount: Decimal
    gross_amount: Decimal
    account_number: str = '7000'
