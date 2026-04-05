"""Rechnungstyp-Erkennung und Steuerberechnung.

DIESE DATEI IST DIE EINZIGE STELLE DIE STEUERBETRAEGE BERECHNET.
Keine andere Datei darf MwSt berechnen oder Steuersaetze bestimmen.

P-27: Zentrale Steuer-Entscheidung:
  - Kleinunternehmer ss19 = IMMER 0%, KEINE MwSt-Zeile
  - Regulaer = Netto + MwSt + Brutto
  - Reverse Charge ss13b = 0%, Hinweis
  - Kleinbetrag ss33 UStDV = <=250 EUR brutto, vereinfacht
  - Innergemeinschaftlich = 0%, EU + USt-IdNr
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Any

EU_COUNTRIES = frozenset({
    'AT', 'BE', 'BG', 'HR', 'CY', 'CZ', 'DK', 'EE', 'FI', 'FR', 'GR', 'HU',
    'IE', 'IT', 'LV', 'LT', 'LU', 'MT', 'NL', 'PL', 'PT', 'RO', 'SK', 'SI', 'ES', 'SE',
})


class InvoiceType(Enum):
    """Rechnungstyp — bestimmt Steuerberechnung und PDF-Layout."""
    KLEINUNTERNEHMER = "kleinunternehmer"    # ss19 UStG — KEINE MwSt
    REGULAR_19 = "regular_19"                # ss14 UStG, 19%
    REGULAR_7 = "regular_7"                  # ss14 UStG, 7%
    REGULAR_0 = "regular_0"                  # Steuerbefreit
    REVERSE_CHARGE = "reverse_charge"        # ss13b UStG
    INNERGEMEINSCHAFTLICH = "innergemeinschaftlich"  # EU 0%
    KLEINBETRAG = "kleinbetrag"              # ss33 UStDV, <=250 EUR brutto


def determine_invoice_type(
    is_kleinunternehmer: bool,
    net_amount: Decimal,
    tax_rate: int = 19,
    is_reverse_charge: bool = False,
    recipient_country: str = 'DE',
    recipient_ust_id: str | None = None,
    explicit_tax_rate: int | None = None,
) -> InvoiceType:
    """EINE Stelle die entscheidet. Kein LLM, kein Frontend.

    Prioritaet:
      1. Kleinunternehmer -> IMMER ss19, NIEMALS MwSt
      2. Expliziter User-Override (z.B. "mit 19% MwSt") — NUR fuer Nicht-KU
      3. Reverse Charge -> ss13b
      4. Innergemeinschaftlich -> EU 0%
      5. Regulaer -> 19% / 7% / 0%
    """
    # REGEL 1: Kleinunternehmer -> IMMER ss19, NIEMALS MwSt, KEIN Override
    if is_kleinunternehmer:
        return InvoiceType.KLEINUNTERNEHMER

    # REGEL 2: Reverse Charge -> ss13b
    if is_reverse_charge:
        return InvoiceType.REVERSE_CHARGE

    # REGEL 3: Innergemeinschaftlich (EU, nicht DE, mit USt-IdNr)
    if recipient_country != 'DE' and recipient_country in EU_COUNTRIES and recipient_ust_id:
        return InvoiceType.INNERGEMEINSCHAFTLICH

    # REGEL 4: Expliziter User-Override fuer Steuersatz
    _rate = explicit_tax_rate if explicit_tax_rate is not None else tax_rate

    # REGEL 5: Regulaer
    if _rate == 7:
        return InvoiceType.REGULAR_7
    elif _rate == 0:
        return InvoiceType.REGULAR_0
    else:
        return InvoiceType.REGULAR_19


def calculate_invoice_amounts(
    invoice_type: InvoiceType,
    net_amount: Decimal,
    tax_rate: int = 19,
) -> dict[str, Any]:
    """Berechnet Betraege basierend auf Rechnungstyp.

    Returns:
        Dict mit net_amount, tax_rate, tax_amount, gross_amount,
        tax_hint, show_tax_line, show_net_gross_split.
    """
    # KLEINUNTERNEHMER: NUR Gesamtbetrag, KEINE MwSt, KEIN Netto/Brutto Split
    if invoice_type == InvoiceType.KLEINUNTERNEHMER:
        return {
            'net_amount': net_amount,
            'tax_rate': 0,
            'tax_amount': Decimal('0'),
            'gross_amount': net_amount,
            'tax_hint': 'Kein Umsatzsteuerausweis aufgrund Anwendung der Kleinunternehmerregelung gemaess \u00a7 19 UStG.',
            'show_tax_line': False,
            'show_net_gross_split': False,
        }

    # REVERSE CHARGE: Keine MwSt, Hinweis auf ss13b
    if invoice_type == InvoiceType.REVERSE_CHARGE:
        return {
            'net_amount': net_amount,
            'tax_rate': 0,
            'tax_amount': Decimal('0'),
            'gross_amount': net_amount,
            'tax_hint': 'Steuerschuldnerschaft des Leistungsempfaengers gemaess \u00a7 13b UStG.',
            'show_tax_line': False,
            'show_net_gross_split': False,
        }

    # INNERGEMEINSCHAFTLICH: Keine MwSt, Hinweis
    if invoice_type == InvoiceType.INNERGEMEINSCHAFTLICH:
        return {
            'net_amount': net_amount,
            'tax_rate': 0,
            'tax_amount': Decimal('0'),
            'gross_amount': net_amount,
            'tax_hint': 'Innergemeinschaftliche Lieferung. Steuerschuldnerschaft des Leistungsempfaengers.',
            'show_tax_line': False,
            'show_net_gross_split': False,
        }

    # REGULAER: Netto + MwSt + Brutto
    _rate = tax_rate
    if invoice_type == InvoiceType.REGULAR_7:
        _rate = 7
    elif invoice_type == InvoiceType.REGULAR_0:
        _rate = 0
    elif invoice_type == InvoiceType.REGULAR_19:
        _rate = 19

    tax_amount = (net_amount * Decimal(_rate) / Decimal('100')).quantize(Decimal('0.01'))
    gross_amount = net_amount + tax_amount
    return {
        'net_amount': net_amount,
        'tax_rate': _rate,
        'tax_amount': tax_amount,
        'gross_amount': gross_amount,
        'tax_hint': None,
        'show_tax_line': _rate > 0,
        'show_net_gross_split': True,
    }


# ---------------------------------------------------------------------------
# Legacy-kompatible Wrapper (fuer bestehende Aufrufe in invoice_pipeline)
# ---------------------------------------------------------------------------

_REDUCED_RATE_KEYWORDS = frozenset({
    'buch', 'buecher', 'buecher', 'ebook', 'e-book', 'publikation',
    'zeitung', 'zeitschrift', 'magazin', 'lebensmittel', 'nahrung',
    'exemplar', 'exemplare', 'lektuere', 'roman', 'sachbuch',
})


def determine_tax_rate_from_items(items: list, default_rate: int = 19) -> int:
    """Bestimmt den MwSt-Satz aus Items (7% fuer Buecher etc.)."""
    if not items:
        return default_rate
    first_rate = items[0].get('tax_rate')
    if first_rate is not None:
        return int(first_rate)
    for item in items:
        desc = (item.get('description') or '').lower()
        if any(kw in desc for kw in _REDUCED_RATE_KEYWORDS):
            return 7
    return default_rate


def _is_einvoice_required() -> bool:
    """Prueft ob E-Rechnung Pflicht ist (Uebergangsfristen)."""
    today = date.today()
    if today <= date(2026, 12, 31):
        return False
    if today <= date(2027, 12, 31):
        return False
    return True
