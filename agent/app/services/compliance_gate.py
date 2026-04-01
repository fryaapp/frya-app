"""Compliance-Gate: HARTE CODE-VALIDIERUNG fuer alle Dokumente.

Architektur-Regel (P-05):
  - Reine Python-Validierung. Kein LLM. Kein Override.
  - Der Gate sitzt in der Pipeline VOR der Dokumenterstellung.
  - Kein Communicator kann den Gate umgehen.
  - Exakte Fehlermeldungen pro fehlendem Feld.

Geprueft werden:
  1. Absender-Daten (aus frya_business_profile) — fuer §14 UStG
  2. Empfaenger-Daten (aus invoice_data) — fuer §14 UStG
  3. Dokumentdaten (line_items, Steuersatz, etc.)
  4. Typ-spezifische Pruefungen (Kleinunternehmer, Reverse Charge, etc.)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ComplianceResult
# ---------------------------------------------------------------------------

@dataclass
class ComplianceResult:
    """Ergebnis einer Compliance-Pruefung."""
    passed: bool
    missing: list[str] = field(default_factory=list)
    missing_sender: list[str] = field(default_factory=list)
    missing_recipient: list[str] = field(default_factory=list)
    missing_document: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Pflichtfeld-Definitionen pro Dokumenttyp
# ---------------------------------------------------------------------------

REQUIRED_FIELDS: dict[str, dict[str, Any]] = {
    'invoice': {
        'sender': {
            'company_name': 'Firmenname',
            'company_street': 'Firmenadresse (Strasse)',
            'company_zip': 'Firmenadresse (PLZ)',
            'company_city': 'Firmenadresse (Ort)',
        },
        'sender_tax': {  # Mindestens eines von beiden
            'tax_number': 'Steuernummer',
            'ust_id': 'USt-IdNr',
        },
        'recipient': {
            'contact_name': 'Empfaenger-Name',
            'contact_street': 'Empfaenger-Adresse (Strasse)',
            'contact_zip': 'Empfaenger-Adresse (PLZ)',
            'contact_city': 'Empfaenger-Adresse (Ort)',
        },
        'document': {
            'line_items': 'Mindestens eine Rechnungsposition',
        },
    },
    'dunning': {
        'sender': {
            'company_name': 'Firmenname',
            'company_street': 'Firmenadresse (Strasse)',
            'company_zip': 'Firmenadresse (PLZ)',
            'company_city': 'Firmenadresse (Ort)',
        },
        'sender_tax': {
            'tax_number': 'Steuernummer',
            'ust_id': 'USt-IdNr',
        },
        'recipient': {
            'contact_name': 'Empfaenger-Name',
            'contact_street': 'Empfaenger-Adresse (Strasse)',
            'contact_zip': 'Empfaenger-Adresse (PLZ)',
            'contact_city': 'Empfaenger-Adresse (Ort)',
        },
        'document': {
            'original_invoice_number': 'Bezug auf Originalrechnung',
            'due_date': 'Faelligkeitsdatum der Originalrechnung',
            'outstanding_amount': 'Offener Betrag',
        },
    },
    'credit_note': {
        'sender': {
            'company_name': 'Firmenname',
            'company_street': 'Firmenadresse (Strasse)',
            'company_zip': 'Firmenadresse (PLZ)',
            'company_city': 'Firmenadresse (Ort)',
        },
        'sender_tax': {
            'tax_number': 'Steuernummer',
            'ust_id': 'USt-IdNr',
        },
        'recipient': {
            'contact_name': 'Empfaenger-Name',
            'contact_street': 'Empfaenger-Adresse (Strasse)',
            'contact_zip': 'Empfaenger-Adresse (PLZ)',
            'contact_city': 'Empfaenger-Adresse (Ort)',
        },
        'document': {
            'original_invoice_number': 'Bezug auf Originalrechnung',
            'credit_reason': 'Grund der Gutschrift',
            'line_items': 'Positionen die gutgeschrieben werden',
        },
    },
}

# Erlaubte feste Steuersaetze (§12 UStG)
VALID_TAX_RATES = frozenset({0, 7, 19})


# ---------------------------------------------------------------------------
# Feld -> menschliche Frage (fuer portionsweises Abfragen von Sender-Daten)
# ---------------------------------------------------------------------------

FIELD_QUESTIONS: dict[str, str] = {
    'company_name': 'Wie heisst dein Unternehmen? (z.B. "Max Mustermann Coaching" oder "Mustermann GmbH")',
    'company_street': 'Deine Geschaeftsadresse — Strasse und Hausnummer?',
    'company_zip': 'PLZ und Ort?',
    'company_city': 'PLZ und Ort?',
    'tax_number': 'Deine Steuernummer oder USt-Identifikationsnummer? (z.B. "236/5478/1234" oder "DE123456789")',
    'ust_id': 'Deine Steuernummer oder USt-Identifikationsnummer?',
    'company_iban': 'Deine IBAN fuer die Bankverbindung auf Rechnungen?',
    'company_email': 'Deine geschaeftliche E-Mail-Adresse?',
    'company_phone': 'Deine geschaeftliche Telefonnummer? (optional)',
    'is_kleinunternehmer': 'Bist du Kleinunternehmer nach §19 UStG? (Dann wird auf deinen Rechnungen keine MwSt ausgewiesen.)',
}


def _field_to_question(field: str) -> str:
    return FIELD_QUESTIONS.get(field, f'Bitte gib {field} an.')


# ---------------------------------------------------------------------------
# HARTE VALIDIERUNG — kein LLM, kein Override
# ---------------------------------------------------------------------------

def validate(doc_type: str, data: dict) -> ComplianceResult:
    """Harte Code-Validierung. Kein LLM. Kein Override.

    Args:
        doc_type: 'invoice', 'dunning', 'credit_note'
        data: Merged dict mit Absender-Daten (from business profile)
              UND Empfaenger/Dokument-Daten (from invoice_data).
              Keys: company_name, company_street, ..., contact_name,
              contact_street, ..., line_items, tax_rate, etc.

    Returns:
        ComplianceResult mit passed=True/False und Listen fehlender Felder.
    """
    fields = REQUIRED_FIELDS.get(doc_type)
    if not fields:
        return ComplianceResult(
            passed=False,
            missing=[f'Unbekannter Dokumenttyp: {doc_type}'],
        )

    missing_sender: list[str] = []
    missing_recipient: list[str] = []
    missing_document: list[str] = []

    # --- Sender-Felder pruefen ---
    for fld, label in fields.get('sender', {}).items():
        val = data.get(fld)
        if not val or (isinstance(val, str) and val.strip() in ('', 'None', 'null')):
            missing_sender.append(label)

    # --- Steuer: Mindestens tax_number ODER ust_id ---
    if 'sender_tax' in fields:
        tax_fields = fields['sender_tax']
        if not any(
            data.get(f) and str(data.get(f, '')).strip() not in ('', 'None', 'null')
            for f in tax_fields
        ):
            missing_sender.append('Steuernummer oder USt-IdNr')

    # --- Empfaenger-Felder pruefen ---
    for fld, label in fields.get('recipient', {}).items():
        val = data.get(fld)
        if not val or (isinstance(val, str) and val.strip() in ('', 'None', 'null')):
            missing_recipient.append(label)

    # --- Dokument-Felder pruefen ---
    for fld, label in fields.get('document', {}).items():
        if fld == 'line_items':
            items = data.get('line_items') or data.get('items') or []
            if not items:
                missing_document.append(label)
            else:
                _validate_line_items(items, missing_document)
        else:
            val = data.get(fld)
            if not val or (isinstance(val, str) and val.strip() in ('', 'None', 'null')):
                missing_document.append(label)

    # --- Steuersatz-Pruefung (nur fuer Rechnungen) ---
    if doc_type == 'invoice':
        tax_rate = data.get('tax_rate')
        if tax_rate is not None and int(tax_rate) not in VALID_TAX_RATES:
            missing_document.append(
                f'Ungueltiger Steuersatz: {tax_rate}%. Erlaubt: 0%, 7%, 19%.',
            )

        # Typ-spezifische Pruefungen
        if data.get('is_kleinunternehmer'):
            if tax_rate is not None and int(tax_rate) != 0:
                missing_document.append('Kleinunternehmer: Steuersatz muss 0% sein')
            if not data.get('tax_note'):
                missing_document.append('Kleinunternehmer: §19-Hinweis fehlt')

        if data.get('is_innergemeinschaftlich') and not data.get('recipient_ust_id'):
            missing_recipient.append('Innergemeinschaftlich: USt-IdNr des Empfaengers')

        if data.get('is_reverse_charge') and not data.get('reverse_charge_note'):
            missing_document.append(
                'Reverse Charge: Hinweis "Steuerschuldnerschaft des Leistungsempfaengers" fehlt',
            )

    all_missing = missing_sender + missing_recipient + missing_document
    return ComplianceResult(
        passed=len(all_missing) == 0,
        missing=all_missing,
        missing_sender=missing_sender,
        missing_recipient=missing_recipient,
        missing_document=missing_document,
    )


def _validate_line_items(items: list, missing: list[str]) -> None:
    """Prueft einzelne Positionen auf Vollstaendigkeit."""
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        pos = i + 1
        desc = item.get('description', '')
        if not desc or (isinstance(desc, str) and desc.strip() in ('', 'None')):
            missing.append(f'Position {pos}: Beschreibung der Leistung')
        qty = item.get('quantity')
        if qty is None or (isinstance(qty, (int, float)) and qty <= 0):
            missing.append(f'Position {pos}: Menge (muss > 0 sein)')
        price = item.get('unit_price')
        if price is None:
            missing.append(f'Position {pos}: Einzelpreis')
        elif isinstance(price, (int, float)) and price < 0:
            missing.append(f'Position {pos}: Einzelpreis (darf nicht negativ sein)')


# ---------------------------------------------------------------------------
# Legacy API (Absender-Pruefung fuer portionsweises Onboarding)
# ---------------------------------------------------------------------------

# §14 UStG + GoBD: Was braucht welche Felder?
COMPLIANCE_REQUIREMENTS: dict[str, dict[str, Any]] = {
    'create_invoice': {
        'required_fields': [
            'company_name', 'company_street', 'company_zip', 'company_city',
            'tax_number|ust_id', 'company_iban',
        ],
        'description': 'Ausgangsrechnung erstellen',
        'law': '§14 Abs.4 UStG',
    },
    'send_invoice_email': {
        'required_fields': [
            'company_name', 'company_street', 'company_zip', 'company_city',
            'tax_number|ust_id', 'company_iban', 'company_email',
        ],
        'description': 'Rechnung per E-Mail versenden',
        'law': '§14 Abs.4 UStG + Absenderangabe',
    },
    'create_einvoice': {
        'required_fields': [
            'company_name', 'company_street', 'company_zip', 'company_city',
            'tax_number|ust_id', 'company_iban', 'company_email',
        ],
        'description': 'E-Rechnung (ZUGFeRD/XRechnung) erstellen',
        'law': '§14 Abs.1 UStG + EN 16931',
    },
    'create_dunning': {
        'required_fields': [
            'company_name', 'company_street', 'company_zip', 'company_city',
            'tax_number|ust_id',
        ],
        'description': 'Mahnung erstellen',
        'law': '§286 BGB',
    },
    'export_datev': {
        'required_fields': ['company_name', 'tax_number|ust_id'],
        'description': 'DATEV-Export',
        'law': 'GoBD',
    },
}


async def get_business_profile(user_id: str, tenant_id: str) -> dict | None:
    """Load business profile from DB. Falls back across tenant_ids."""
    try:
        import asyncpg
        from app.dependencies import get_settings
        settings = get_settings()
        if settings.database_url.startswith('memory://'):
            return None
        conn = await asyncpg.connect(settings.database_url)
        try:
            row = await conn.fetchrow(
                "SELECT * FROM frya_business_profile "
                "WHERE user_id = $1 AND tenant_id IN ($2, 'default', '') "
                "ORDER BY CASE WHEN tenant_id = $2 THEN 0 WHEN tenant_id = 'default' THEN 1 ELSE 2 END "
                "LIMIT 1",
                user_id, tenant_id or 'default',
            )
            return dict(row) if row else None
        finally:
            await conn.close()
    except Exception as exc:
        logger.warning('get_business_profile failed: %s', exc)
        return None


async def check_compliance(
    user_id: str, tenant_id: str, action: str,
) -> tuple[bool, list[str], dict | None]:
    """Legacy: Prueft ob eine Aktion erlaubt ist (nur Absender-Daten).

    Wird weiterhin fuer portionsweises Onboarding genutzt.
    Fuer die harte Gesamtvalidierung: validate() verwenden.

    Returns: (erlaubt, fehlende_fragen, profil)
    """
    req = COMPLIANCE_REQUIREMENTS.get(action)
    if not req:
        return True, [], None

    profile = await get_business_profile(user_id, tenant_id)
    if not profile:
        # Kein Profil -> alle Felder fehlen, erste Frage stellen
        first_field = req['required_fields'][0]
        if '|' in first_field:
            first_field = first_field.split('|')[0]
        return False, [_field_to_question(first_field)], None

    missing: list[str] = []
    for field_spec in req['required_fields']:
        if '|' in field_spec:
            fields = field_spec.split('|')
            if not any(profile.get(f) for f in fields):
                missing.append(_field_to_question(fields[0]))
        else:
            val = profile.get(field_spec)
            if not val or (isinstance(val, str) and val.strip() in ('', 'None', 'null')):
                missing.append(_field_to_question(field_spec))

    return len(missing) == 0, missing[:1], profile  # Nur ERSTE fehlende Frage


async def count_missing_fields(user_id: str, tenant_id: str, action: str) -> int:
    """Zaehlt fehlende Felder fuer eine Aktion."""
    req = COMPLIANCE_REQUIREMENTS.get(action)
    if not req:
        return 0
    profile = await get_business_profile(user_id, tenant_id)
    if not profile:
        return len(req['required_fields'])

    count = 0
    for field_spec in req['required_fields']:
        if '|' in field_spec:
            fields = field_spec.split('|')
            if not any(profile.get(f) for f in fields):
                count += 1
        else:
            val = profile.get(field_spec)
            if not val or (isinstance(val, str) and val.strip() in ('', 'None', 'null')):
                count += 1
    return count
