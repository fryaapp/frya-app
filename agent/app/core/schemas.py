"""Typisierte Response-Schemas fuer die Kommunikation zwischen Services und ResponseBuilder.

VORHER: Services geben willkuerliche Dicts zurueck, ResponseBuilder raet was drin ist.
NACHHER: Services geben ServiceResult zurueck, ResponseBuilder weiss exakt was er bekommt.

Schrittweise Umstellung: Alte Dicts werden per compat_wrap() gewrapped bis der Service
umgestellt ist. Kein Big-Bang.
"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel

from app.core.intents import Intent


class ServiceResult(BaseModel):
    """Was jeder Service an den ResponseBuilder zurueckgibt."""

    success: bool
    intent: Intent
    data: dict[str, Any] = {}
    message: str = ""
    error: Optional[str] = None


class ContentBlock(BaseModel):
    """Ein Content-Block fuer das Frontend."""

    block_type: str  # card_list, key_value, chart, table, text, alert, card, card_group
    data: dict[str, Any]


class MessageResponse(BaseModel):
    """Komplette Antwort an den User (was das Frontend bekommt)."""

    text: str
    content_blocks: list[ContentBlock] = []
    actions: list[dict[str, Any]] = []
    suggestions: list[str] = []
    context_type: Optional[str] = None


class ApprovalResult(ServiceResult):
    """Ergebnis einer Freigabe/Ablehnung — erweitert ServiceResult."""

    # Die Standard-Keys die der ResponseBuilder fuer APPROVE erwartet:
    # data.approved (bool), data.status (str), data.next_item (dict|None),
    # data.booking_id (str|None), data.message (str)
    pass


class FinanceSummaryResult(ServiceResult):
    """Ergebnis einer Finanzuebersicht — erweitert ServiceResult."""

    # Die Standard-Keys die der ResponseBuilder fuer SHOW_FINANCE erwartet:
    # data.total_income (float), data.total_expenses (float),
    # data.profit (float), data.booking_count (int)
    pass


def compat_wrap(raw_dict: dict, intent: Intent) -> ServiceResult:
    """Temporaerer Wrapper fuer noch nicht umgestellte Services.

    Wrapped einen alten Dict-Return in ein ServiceResult.
    Wird Service fuer Service entfernt.
    """
    return ServiceResult(
        success=True,
        intent=intent,
        data=raw_dict,
    )


def unwrap(result: ServiceResult | dict, intent: Intent | None = None) -> dict:
    """Extrahiere die Daten — akzeptiert sowohl ServiceResult als auch raw dict.

    Das ist die Bruecke fuer den ResponseBuilder: Er kann beide Formate verarbeiten.
    """
    if isinstance(result, ServiceResult):
        return result.data
    # Legacy dict — einfach durchreichen
    return result
