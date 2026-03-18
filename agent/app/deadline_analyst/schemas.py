"""Schemas for the Deadline Analyst agent — Fristüberwachung."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

Priority = Literal['CRITICAL', 'HIGH', 'MEDIUM', 'LOW']
WarningType = Literal['overdue', 'due_today', 'due_soon', 'skonto_expiring', 'escalation']


class FristConfig(BaseModel):
    """Tunable thresholds for deadline classification."""
    skonto_warning_days: int = 3
    due_soon_days: int = 7
    escalation_after_days: int = 14


class SkontoInfo(BaseModel):
    """Skonto (early-payment discount) metadata extracted from case.metadata."""
    skonto_rate: float
    skonto_days: int
    skonto_date: date
    skonto_amount: Decimal | None = None
    days_until_expiry: int


class DeadlineCheck(BaseModel):
    """Single-case deadline analysis result."""
    case_id: str
    case_number: str | None = None
    vendor_name: str | None = None
    amount: Decimal | None = None
    currency: str = 'EUR'
    due_date: date
    days_until_due: int          # negative = already overdue
    skonto_info: SkontoInfo | None = None
    priority: Priority
    warning_type: WarningType
    status: str                   # current CaseStatus


class DeadlineReport(BaseModel):
    """Full deadline scan for a tenant."""
    tenant_id: str
    checked_at: str
    total_cases_checked: int
    overdue: list[DeadlineCheck] = Field(default_factory=list)
    due_today: list[DeadlineCheck] = Field(default_factory=list)
    due_soon: list[DeadlineCheck] = Field(default_factory=list)
    skonto_expiring: list[DeadlineCheck] = Field(default_factory=list)
    summary_text: str = ''
    total_overdue_amount: Decimal | None = None
    analyst_version: str = 'deadline-analyst-v1'
