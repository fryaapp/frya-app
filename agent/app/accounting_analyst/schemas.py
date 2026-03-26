"""Schemas for the Accounting Analyst agent (SKR03 booking proposals)."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field

# Frequently used SKR03 accounts — shown in the UI dropdown / LLM prompt.
SKR03_COMMON_ACCOUNTS: dict[str, str] = {
    '1000': 'Kasse',
    '1200': 'Bank',
    '1400': 'Forderungen aus Lieferungen und Leistungen',
    '1571': 'Vorsteuer 7 %',
    '1576': 'Vorsteuer 19 %',
    '1600': 'Verbindlichkeiten aus Lieferungen und Leistungen',
    '3300': 'Wareneingang 19 % MwSt',
    '3400': 'Wareneingang 7 % MwSt',
    '3801': 'Umsatzsteuer 7 %',
    '3806': 'Umsatzsteuer 19 %',
    '4200': 'Raumkosten',
    '4300': 'Versicherungen',
    '4910': 'Porto und Versandkosten',
    '4920': 'Telefon und Internet',
    '4940': 'Werbekosten',
    '4980': 'Buchfuehrungskosten',
    '7000': 'Umsatzerloese 19 % MwSt',
    '7010': 'Umsatzerloese 7 % MwSt',
}


class CaseAnalysisInput(BaseModel):
    case_id: str
    case_type: str
    vendor_name: str | None = None
    total_amount: Decimal | None = None
    currency: str = 'EUR'
    due_date: date | None = None
    title: str | None = None
    document_type: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class BookingLine(BaseModel):
    account_number: str
    account_name: str
    amount: Decimal
    side: str  # 'SOLL' or 'HABEN'


class BookingProposal(BaseModel):
    approval_mode: str = 'PROPOSE_ONLY'
    case_id: str
    skr03_soll: str | None = None
    skr03_soll_name: str | None = None
    skr03_haben: str | None = None
    skr03_haben_name: str | None = None
    tax_rate: float | None = None
    tax_amount: Decimal | None = None
    net_amount: Decimal | None = None
    gross_amount: Decimal | None = None
    booking_lines: list[BookingLine] = Field(default_factory=list)
    reasoning: str | None = None
    confidence: float = 0.0
    status: str = 'PENDING'  # PENDING | CONFIRMED | REJECTED
    analyst_version: str = 'accounting-analyst-v1'
    created_at: str | None = None
