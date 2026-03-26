"""Two-layer deterministic case assignment engine.

Layer 1 — Hard reference match:
  Looks up doc.reference_values in case_references.
  1 match  → CaseAssignment(confidence=CERTAIN, method=hard_reference)
  >1 match → None  (caller should create a multi_match conflict)

Layer 2 — Entity matching (vendor + amount + date):
  Compares against all OPEN/OVERDUE cases for the tenant.
  vendor: exact, contains, or Levenshtein ≤ 2
  amount: |case - doc| ≤ 0.01
  date:   |case_due - doc_date| ≤ 90 days (or missing → skip)
  1 match → CaseAssignment(confidence=HIGH, method=entity_amount)
  else    → None

HARD CONSTRAINT: LLM-assigned confidence is hard-capped at MEDIUM.
  Use cap_llm_confidence() before persisting any LLM-derived assignment.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from app.case_engine.models import AssignmentConfidence, CaseAssignment

if TYPE_CHECKING:
    from app.case_engine.repository import CaseRepository

# Confidence ranking: index 0 = highest confidence
_CONFIDENCE_ORDER: list[str] = ['CERTAIN', 'HIGH', 'MEDIUM', 'LOW']
_LLM_CAP = 'MEDIUM'
_LLM_CAP_IDX = _CONFIDENCE_ORDER.index(_LLM_CAP)


def cap_llm_confidence(confidence: str) -> AssignmentConfidence:
    """Hard-cap LLM-derived confidence at MEDIUM.

    CERTAIN / HIGH → MEDIUM
    MEDIUM         → MEDIUM
    LOW            → LOW
    """
    try:
        idx = _CONFIDENCE_ORDER.index(confidence)
    except ValueError:
        return _LLM_CAP  # type: ignore[return-value]
    return _CONFIDENCE_ORDER[max(idx, _LLM_CAP_IDX)]  # type: ignore[return-value]


# ── helpers ──────────────────────────────────────────────────────────────────

def _levenshtein(s1: str, s2: str) -> int:
    if len(s1) < len(s2):
        s1, s2 = s2, s1
    if not s2:
        return len(s1)
    prev = list(range(len(s2) + 1))
    for c1 in s1:
        curr = [prev[0] + 1]
        for j, c2 in enumerate(s2):
            cost = 0 if c1 == c2 else 1
            curr.append(min(prev[j + 1] + 1, curr[j] + 1, prev[j] + cost))
        prev = curr
    return prev[-1]


def _vendor_match(case_vendor: str | None, doc_vendor: str | None) -> bool:
    if not case_vendor or not doc_vendor:
        return False
    a = case_vendor.lower().strip()
    b = doc_vendor.lower().strip()
    return a == b or b in a or a in b or _levenshtein(a, b) <= 2


def _amount_match(case_amount: Decimal | None, doc_amount: float | None) -> bool:
    if case_amount is None or doc_amount is None:
        return False
    return abs(float(case_amount) - doc_amount) <= 0.01


def _date_within_90d(case_due: date | None, doc_date: date | None) -> bool:
    """True if within 90 days; True if either date is absent (non-disqualifying)."""
    if case_due is None or doc_date is None:
        return True
    return abs((case_due - doc_date).days) <= 90


# ── public API ────────────────────────────────────────────────────────────────

@dataclass
class DocumentData:
    """Minimal document metadata needed for case assignment."""
    document_source: str
    document_source_id: str
    reference_values: list[tuple[str, str]] = field(default_factory=list)
    vendor_name: str | None = None
    total_amount: float | None = None
    currency: str = 'EUR'
    document_date: date | None = None
    filename: str | None = None


class CaseAssignmentEngine:
    """Stateless assignment engine; requires a CaseRepository for lookups."""

    def __init__(self, repository: 'CaseRepository') -> None:
        self._repo = repository

    async def assign_document(
        self,
        tenant_id: uuid.UUID,
        doc: DocumentData,
    ) -> Optional[CaseAssignment]:
        """Try to assign *doc* to an existing case.

        Returns a CaseAssignment or None if no unambiguous match is found.
        """
        # ── Layer 1: exact reference match ───────────────────────────────────
        for ref_type, ref_value in (doc.reference_values or []):
            if not ref_value:
                continue
            matches = await self._repo.find_cases_by_reference(
                tenant_id, ref_type, ref_value
            )
            if len(matches) == 1:
                return CaseAssignment(
                    case_id=matches[0].id,
                    confidence='CERTAIN',
                    method='hard_reference',
                )
            if len(matches) > 1:
                # Ambiguous — caller must create a multi_match conflict
                return None

        # ── Layer 2: entity matching ──────────────────────────────────────────
        active = await self._repo.list_active_cases_for_tenant(tenant_id)
        hits = [
            c for c in active
            if (
                _vendor_match(c.vendor_name, doc.vendor_name)
                and _amount_match(c.total_amount, doc.total_amount)
                and _date_within_90d(c.due_date, doc.document_date)
            )
        ]

        if len(hits) == 1:
            return CaseAssignment(
                case_id=hits[0].id,
                confidence='HIGH',
                method='entity_amount',
            )

        return None
