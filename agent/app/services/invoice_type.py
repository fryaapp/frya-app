"""Rechnungstyp-Erkennung basierend auf Business-Profil und Rechnungsdaten.

Bestimmt automatisch:
- Kleinunternehmer §19 (0% MwSt, Hinweistext)
- Kleinbetragsrechnung §33 UStDV (<=250€, vereinfacht)
- Innergemeinschaftlich (EU + USt-IdNr, 0%)
- Reverse Charge §13b (0%)
- Standard B2B (19% + ZUGFeRD)
- Standard B2C (19%, kein ZUGFeRD)
"""
from __future__ import annotations

from datetime import date
from typing import Any

EU_COUNTRIES = frozenset({
    'AT', 'BE', 'BG', 'HR', 'CY', 'CZ', 'DK', 'EE', 'FI', 'FR', 'GR', 'HU',
    'IE', 'IT', 'LV', 'LT', 'LU', 'MT', 'NL', 'PL', 'PT', 'RO', 'SK', 'SI', 'ES', 'SE',
})


def determine_invoice_type(profile: dict, intent_data: dict) -> dict[str, Any]:
    """Bestimmt den Rechnungstyp basierend auf Profil und Rechnungsdaten.

    Prioritaet:
    1. Expliziter User-Override (z.B. "mit 19% MwSt")
    2. Produkt-Typ (Buecher = 7%)
    3. Profil-Default (Kleinunternehmer = 0%)
    4. Standard = 19%
    """
    recipient = intent_data.get('recipient', {})
    items = intent_data.get('items', [])

    # P-10 A2: Pruefen ob User explizit einen Steuersatz angegeben hat
    # NUR explicit_tax_rate zaehlt — items.tax_rate wird vom Communicator gesetzt
    # und spiegelt den Default, nicht den User-Wunsch
    user_tax_rate = intent_data.get('explicit_tax_rate')  # z.B. 19, 7, 0

    # Wenn User explizit einen Satz angibt, hat das hoechste Prio
    if user_tax_rate is not None and int(user_tax_rate) > 0:
        rate = int(user_tax_rate)
        return {
            'type': 'STANDARD_B2B' if rate == 19 else 'REDUCED_RATE',
            'tax_rate': rate,
            'tax_note': None,
            'show_tax_line': True,
            'e_invoice_required': False,
        }

    total_gross = _calculate_gross(items, profile)

    # === KLEINUNTERNEHMER §19 (nur wenn KEIN expliziter Override) ===
    if profile.get('is_kleinunternehmer'):
        return {
            'type': 'KLEINUNTERNEHMER',
            'tax_rate': 0,
            'tax_note': 'Gemaess § 19 UStG wird keine Umsatzsteuer berechnet.',
            'show_tax_line': False,
            'show_tax_id': False,
            'e_invoice_required': False,
        }

    # === KLEINBETRAGSRECHNUNG §33 UStDV ===
    if total_gross <= 250.00:
        return {
            'type': 'KLEINBETRAG',
            'tax_rate': _determine_tax_rate(items, profile),
            'tax_note': None,
            'show_tax_line': True,
            'simplified': True,
            'e_invoice_required': False,
        }

    # === INNERGEMEINSCHAFTLICH (EU, nicht DE) ===
    recipient_country = recipient.get('country', 'DE')
    recipient_ust_id = recipient.get('ust_id')
    if recipient_country != 'DE' and recipient_country in EU_COUNTRIES and recipient_ust_id:
        return {
            'type': 'INNERGEMEINSCHAFTLICH',
            'tax_rate': 0,
            'tax_note': 'Innergemeinschaftliche Lieferung. Steuerschuldnerschaft des Leistungsempfaengers.',
            'show_tax_line': True,
            'requires_recipient_ust_id': True,
            'requires_own_ust_id': True,
            'e_invoice_required': False,
        }

    # === REVERSE CHARGE §13b ===
    if intent_data.get('reverse_charge'):
        return {
            'type': 'REVERSE_CHARGE',
            'tax_rate': 0,
            'tax_note': 'Steuerschuldnerschaft des Leistungsempfaengers (Reverse Charge, §13b UStG).',
            'show_tax_line': True,
            'e_invoice_required': True,
        }

    # === STANDARD B2B ===
    if recipient.get('is_business', True):
        return {
            'type': 'STANDARD_B2B',
            'tax_rate': _determine_tax_rate(items, profile),
            'tax_note': None,
            'show_tax_line': True,
            'e_invoice_required': _is_einvoice_required(),
        }

    # === STANDARD B2C ===
    return {
        'type': 'STANDARD_B2C',
        'tax_rate': _determine_tax_rate(items, profile),
        'tax_note': None,
        'show_tax_line': True,
        'e_invoice_required': False,
    }


def _is_einvoice_required() -> bool:
    """Prueft ob E-Rechnung Pflicht ist (Uebergangsfristen)."""
    today = date.today()
    if today <= date(2026, 12, 31):
        return False
    if today <= date(2027, 12, 31):
        return False  # Nur Pflicht wenn Vorjahresumsatz > 800.000
    return True


_REDUCED_RATE_KEYWORDS = frozenset({
    'buch', 'buecher', 'bücher', 'ebook', 'e-book', 'publikation',
    'zeitung', 'zeitschrift', 'magazin', 'lebensmittel', 'nahrung',
    'exemplar', 'exemplare', 'lektüre', 'roman', 'sachbuch',
})


def _determine_tax_rate(items: list, profile: dict) -> int:
    """Bestimmt den MwSt-Satz.

    7% auf: Buecher, E-Books, digitale Publikationen, Lebensmittel
    19% auf: Alles andere
    """
    if not items:
        return profile.get('default_tax_rate') or 19

    # Wenn Items explizit tax_rate haben
    first_rate = items[0].get('tax_rate')
    if first_rate is not None:
        return int(first_rate)

    # P-10 A2: Ermaessigter Satz fuer Buecher/Lebensmittel
    for item in items:
        desc = (item.get('description') or '').lower()
        if any(kw in desc for kw in _REDUCED_RATE_KEYWORDS):
            return 7

    return profile.get('default_tax_rate') or 19


def _calculate_gross(items: list, profile: dict) -> float:
    """Berechnet Brutto-Gesamtbetrag."""
    total_net = sum(
        float(i.get('quantity', 1)) * float(i.get('unit_price', 0))
        for i in items
    )
    if profile.get('is_kleinunternehmer'):
        return total_net

    tax_rate = _determine_tax_rate(items, profile)
    return total_net * (1 + tax_rate / 100)
