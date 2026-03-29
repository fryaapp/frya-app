"""Schemas for the Risk/Consistency Analyst agent (Paket 22)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Severity = Literal['CRITICAL', 'HIGH', 'MEDIUM', 'LOW', 'OK']
OverallRisk = Literal['HIGH', 'MEDIUM', 'LOW', 'OK']
CheckType = Literal[
    'amount_consistency',
    'duplicate_detection',
    'tax_plausibility',
    'vendor_consistency',
    'booking_plausibility',
    'timeline_check',
]

_SEVERITY_ORDER: dict[str, int] = {
    'CRITICAL': 4,
    'HIGH': 3,
    'MEDIUM': 2,
    'LOW': 1,
    'OK': 0,
}


class RiskCheck(BaseModel):
    case_id: str
    check_type: CheckType
    severity: Severity
    finding: str
    recommendation: str | None = None


class RiskReport(BaseModel):
    case_id: str
    checks: list[RiskCheck] = Field(default_factory=list)
    overall_risk: OverallRisk = 'OK'
    summary: str = ''
    analyst_version: str = 'risk-analyst-v1'
    checked_at: str | None = None


def compute_overall_risk(checks: list[RiskCheck]) -> OverallRisk:
    """Determine overall risk level from a list of checks."""
    max_sev = max((_SEVERITY_ORDER.get(c.severity, 0) for c in checks), default=0)
    if max_sev >= 3:
        return 'HIGH'
    if max_sev == 2:
        return 'MEDIUM'
    if max_sev == 1:
        return 'LOW'
    return 'OK'
