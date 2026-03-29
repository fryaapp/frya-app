"""Form-Schemas fuer Chat-basierte Formulare."""
from __future__ import annotations
from datetime import date
from uuid import uuid4


def build_invoice_form(contact=None, items=None) -> dict:
    return {
        "form_id": str(uuid4()),
        "form_type": "invoice",
        "title": "Neue Rechnung",
        "fields": [
            {
                "key": "contact_name",
                "label": "Empf\u00e4nger",
                "type": "text",
                "value": contact.name if contact else None,
                "required": True,
                "editable": True,
            },
            {
                "key": "date",
                "label": "Rechnungsdatum",
                "type": "date",
                "value": date.today().isoformat(),
                "required": True,
                "editable": True,
            },
            {
                "key": "items",
                "label": "Positionen",
                "type": "line_items",
                "value": items
                or [
                    {
                        "description": "",
                        "quantity": 1,
                        "unit_price": 0.0,
                        "tax_rate": 19.0,
                    }
                ],
                "required": True,
                "editable": True,
            },
            {
                "key": "notes",
                "label": "Anmerkungen",
                "type": "textarea",
                "value": "Zahlbar innerhalb von 14 Tagen.",
                "required": False,
                "editable": True,
            },
            {
                "key": "payment_terms_days",
                "label": "Zahlungsziel (Tage)",
                "type": "number",
                "value": (
                    getattr(contact, "default_payment_terms_days", 14)
                    if contact
                    else 14
                ),
                "required": True,
                "editable": True,
                "validation": {"min": 1, "max": 365},
            },
        ],
        "submit_label": "Rechnung erstellen",
        "cancel_label": "Abbrechen",
    }


def build_contact_form(contact=None) -> dict:
    return {
        "form_id": str(uuid4()),
        "form_type": "contact",
        "title": "Kontakt bearbeiten" if contact else "Neuer Kontakt",
        "fields": [
            {
                "key": "name",
                "label": "Name / Firma",
                "type": "text",
                "value": contact.name if contact else None,
                "required": True,
                "editable": True,
            },
            {
                "key": "category",
                "label": "Kategorie",
                "type": "select",
                "value": (
                    getattr(contact, "category", "CUSTOMER") if contact else "CUSTOMER"
                ),
                "required": True,
                "editable": True,
                "options": [
                    {"value": "CUSTOMER", "label": "Kunde"},
                    {"value": "SUPPLIER", "label": "Lieferant"},
                    {"value": "BOTH", "label": "Beides"},
                    {"value": "AUTHORITY", "label": "Beh\u00f6rde"},
                    {"value": "OTHER", "label": "Sonstige"},
                ],
            },
            {
                "key": "email",
                "label": "E-Mail",
                "type": "email",
                "value": getattr(contact, "email", None) if contact else None,
                "required": False,
                "editable": True,
            },
            {
                "key": "phone",
                "label": "Telefon",
                "type": "phone",
                "value": getattr(contact, "phone", None) if contact else None,
                "required": False,
                "editable": True,
            },
            {
                "key": "tax_id",
                "label": "USt-IdNr.",
                "type": "text",
                "value": getattr(contact, "tax_id", None) if contact else None,
                "required": False,
                "editable": True,
            },
            {
                "key": "iban",
                "label": "IBAN",
                "type": "text",
                "value": getattr(contact, "iban", None) if contact else None,
                "required": False,
                "editable": True,
            },
            {
                "key": "default_payment_terms_days",
                "label": "Standard-Zahlungsziel (Tage)",
                "type": "number",
                "value": (
                    getattr(contact, "default_payment_terms_days", 14)
                    if contact
                    else 14
                ),
                "required": False,
                "editable": True,
            },
            {
                "key": "notes",
                "label": "Notizen",
                "type": "textarea",
                "value": getattr(contact, "notes", None) if contact else None,
                "required": False,
                "editable": True,
            },
        ],
        "submit_label": "Speichern",
    }


def build_settings_form(settings: dict) -> dict:
    return {
        "form_id": str(uuid4()),
        "form_type": "settings",
        "title": "Einstellungen",
        "fields": [
            {
                "key": "display_name",
                "label": "Dein Name",
                "type": "text",
                "value": settings.get("display_name", ""),
                "required": False,
                "editable": True,
            },
            {
                "key": "theme",
                "label": "Design",
                "type": "select",
                "value": settings.get("theme", "system"),
                "required": True,
                "editable": True,
                "options": [
                    {"value": "light", "label": "Hell"},
                    {"value": "dark", "label": "Dunkel"},
                    {"value": "system", "label": "System"},
                ],
            },
            {
                "key": "notification_channel",
                "label": "Benachrichtigungen",
                "type": "select",
                "value": settings.get("notification_channel", "in_app"),
                "required": True,
                "editable": True,
                "options": [
                    {"value": "in_app", "label": "Nur in der App"},
                    {"value": "telegram", "label": "Telegram"},
                    {"value": "email", "label": "E-Mail"},
                ],
            },
        ],
        "submit_label": "Speichern",
    }


def build_correction_form(case_data: dict) -> dict:
    return {
        "form_id": str(uuid4()),
        "form_type": "correction",
        "title": "Buchung korrigieren",
        "fields": [
            {
                "key": "debit_account",
                "label": "Konto (Soll)",
                "type": "text",
                "value": case_data.get("proposed_debit", ""),
                "required": True,
                "editable": True,
            },
            {
                "key": "credit_account",
                "label": "Gegenkonto (Haben)",
                "type": "text",
                "value": case_data.get("proposed_credit", "1800"),
                "required": True,
                "editable": True,
            },
            {
                "key": "amount",
                "label": "Betrag",
                "type": "currency",
                "value": case_data.get("amount", 0),
                "required": True,
                "editable": True,
            },
            {
                "key": "tax_rate",
                "label": "MwSt-Satz",
                "type": "select",
                "value": case_data.get("tax_rate", 19.0),
                "required": True,
                "editable": True,
                "options": [
                    {"value": 0.0, "label": "0% (steuerfrei)"},
                    {"value": 7.0, "label": "7% (erm\u00e4\u00dfigt)"},
                    {"value": 19.0, "label": "19% (regul\u00e4r)"},
                ],
            },
        ],
        "submit_label": "Korrektur speichern",
    }
