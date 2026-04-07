"""Zentrale Intent-Registry. ALLE Intent-Strings werden hier definiert.
Kein String-Literal im restlichen Code. Immer Intent.XYZ importieren.

Stand: 07.04.2026
Quelle: Refactor Fix 2 (Schwachstelle 2)
Intents: 38
"""

from enum import StrEnum
import logging
import re

logger = logging.getLogger(__name__)


class Intent(StrEnum):
    # ─── Inbox ────────────────────────────────────────────────────────
    SHOW_INBOX = "SHOW_INBOX"
    PROCESS_INBOX = "PROCESS_INBOX"
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    SKIP = "SKIP"

    # ─── Finanzen ─────────────────────────────────────────────────────
    SHOW_FINANCE = "SHOW_FINANCE"
    SHOW_FINANCIAL_OVERVIEW = "SHOW_FINANCIAL_OVERVIEW"
    SHOW_EXPENSE_CATEGORIES = "SHOW_EXPENSE_CATEGORIES"
    SHOW_PROFIT_LOSS = "SHOW_PROFIT_LOSS"
    SHOW_REVENUE_TREND = "SHOW_REVENUE_TREND"
    SHOW_FORECAST = "SHOW_FORECAST"

    # ─── Kontakte + Buchungen ─────────────────────────────────────────
    SHOW_CONTACT = "SHOW_CONTACT"
    SHOW_CONTACTS = "SHOW_CONTACTS"
    SHOW_BOOKINGS = "SHOW_BOOKINGS"
    SHOW_OPEN_ITEMS = "SHOW_OPEN_ITEMS"

    # ─── Rechnungen ───────────────────────────────────────────────────
    CREATE_INVOICE = "CREATE_INVOICE"
    EDIT_INVOICE = "EDIT_INVOICE"
    SEND_INVOICE = "SEND_INVOICE"
    VOID_INVOICE = "VOID_INVOICE"
    CANCEL_INVOICE = "CANCEL_INVOICE"
    SHOW_INVOICE = "SHOW_INVOICE"

    # ─── Belege ───────────────────────────────────────────────────────
    SHOW_CASE = "SHOW_CASE"

    # ─── Fristen ──────────────────────────────────────────────────────
    SHOW_DEADLINES = "SHOW_DEADLINES"

    # ─── Export ───────────────────────────────────────────────────────
    SHOW_EXPORT = "SHOW_EXPORT"

    # ─── Kontakte erstellen ───────────────────────────────────────────
    CREATE_CONTACT = "CREATE_CONTACT"
    CREATE_REMINDER = "CREATE_REMINDER"

    # ─── Templates / Logo ─────────────────────────────────────────────
    CHOOSE_TEMPLATE = "CHOOSE_TEMPLATE"
    SET_TEMPLATE = "SET_TEMPLATE"
    UPLOAD_LOGO = "UPLOAD_LOGO"
    CHANGE_KU_STATUS = "CHANGE_KU_STATUS"

    # ─── System ───────────────────────────────────────────────────────
    SETTINGS = "SETTINGS"
    STATUS_OVERVIEW = "STATUS_OVERVIEW"
    UPLOAD = "UPLOAD"
    GREETING = "GREETING"
    SMALL_TALK = "SMALL_TALK"
    GENERAL_CONVERSATION = "GENERAL_CONVERSATION"
    BOOKING_REQUEST = "BOOKING_REQUEST"
    FINANCIAL_QUERY = "FINANCIAL_QUERY"
    REMINDER_PERSONAL = "REMINDER_PERSONAL"

    # ─── Orchestration (Legacy) ───────────────────────────────────────
    DOCUMENT_REVIEW = "DOCUMENT_REVIEW"
    ACCOUNTING_QUERY = "ACCOUNTING_QUERY"
    WORKFLOW_TRIGGER = "WORKFLOW_TRIGGER"

    # ─── Fallback ─────────────────────────────────────────────────────
    UNKNOWN = "UNKNOWN"


def parse_intent(raw_string: str) -> Intent:
    """Validiert den vom LLM zurueckgegebenen Intent-String.
    Gibt Intent.UNKNOWN zurueck bei unbekannten Strings."""
    if not raw_string:
        return Intent.UNKNOWN
    cleaned = raw_string.strip().upper()
    try:
        return Intent(cleaned)
    except ValueError:
        logger.warning("Unbekannter Intent vom LLM: '%s' → UNKNOWN", raw_string)
        return Intent.UNKNOWN
