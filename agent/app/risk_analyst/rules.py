"""Deterministic, rule-based risk checks — no LLM required.

Each function accepts CaseRecord (and optionally documents / all_cases) and
returns a single RiskCheck with the appropriate severity.
"""
from __future__ import annotations

import difflib
import logging
from datetime import date
from decimal import Decimal, InvalidOperation

logger = logging.getLogger(__name__)

from app.accounting_analyst.schemas import SKR03_COMMON_ACCOUNTS
from app.case_engine.models import CaseDocumentRecord, CaseRecord
from app.risk_analyst.schemas import RiskCheck

_ALLOWED_TAX_RATES = {0.0, 7.0, 19.0}


# ---------------------------------------------------------------------------
# a) Amount consistency
# ---------------------------------------------------------------------------

def check_amount_consistency(
    case: CaseRecord,
    documents: list[CaseDocumentRecord],
) -> RiskCheck:
    """Compare case.total_amount with amounts found in document/booking metadata."""
    case_id = str(case.id)
    case_amount = case.total_amount

    if case_amount is None:
        return RiskCheck(
            case_id=case_id,
            check_type='amount_consistency',
            severity='OK',
            finding='Kein Betrag im Vorgang — kein Vergleich moeglich.',
        )

    # Collect comparison amounts from multiple sources
    comparison_amounts: list[Decimal] = []

    # From document metadata (individual documents)
    for doc in documents:
        for key in ('gross_amount', 'total_amount', 'amount'):
            val = doc.metadata.get(key)
            if val is not None:
                try:
                    comparison_amounts.append(Decimal(str(val)))
                    break
                except (InvalidOperation, ValueError) as exc:
                    logger.debug('Document amount parsing failed for key %s: %s', key, exc)

    # From case-level document_analysis metadata
    doc_analysis = case.metadata.get('document_analysis')
    if isinstance(doc_analysis, dict):
        for key in ('gross_amount', 'total_amount', 'amount'):
            val = doc_analysis.get(key)
            if val is not None:
                try:
                    comparison_amounts.append(Decimal(str(val)))
                    break
                except (InvalidOperation, ValueError) as exc:
                    logger.debug('Case-level amount parsing failed for key %s: %s', key, exc)

    # From booking_proposal gross_amount
    bp = case.metadata.get('booking_proposal')
    if isinstance(bp, dict) and bp.get('gross_amount') is not None:
        try:
            comparison_amounts.append(Decimal(str(bp['gross_amount'])))
        except (InvalidOperation, ValueError) as exc:
            logger.debug('Booking proposal gross_amount parsing failed: %s', exc)

    if not comparison_amounts:
        return RiskCheck(
            case_id=case_id,
            check_type='amount_consistency',
            severity='OK',
            finding='Keine Vergleichsbetraege vorhanden — Pruefung uebersprungen.',
        )

    # Find worst deviation
    max_deviation = Decimal('0')
    worst_amount = comparison_amounts[0]
    for da in comparison_amounts:
        if da == Decimal('0'):
            continue
        deviation = abs(case_amount - da) / da
        if deviation > max_deviation:
            max_deviation = deviation
            worst_amount = da

    pct = float(max_deviation) * 100
    if pct > 10:
        return RiskCheck(
            case_id=case_id,
            check_type='amount_consistency',
            severity='HIGH',
            finding=(
                f'Betragsabweichung {pct:.1f} % zwischen Vorgang ({case_amount} EUR) '
                f'und Dokument/Vorschlag ({worst_amount} EUR).'
            ),
            recommendation='Betraege pruefen und korrigieren.',
        )
    if pct > 1:
        return RiskCheck(
            case_id=case_id,
            check_type='amount_consistency',
            severity='MEDIUM',
            finding=(
                f'Geringe Betragsabweichung {pct:.1f} % '
                f'({case_amount} EUR vs {worst_amount} EUR).'
            ),
            recommendation='Betraege auf Rundungsfehler pruefen.',
        )
    return RiskCheck(
        case_id=case_id,
        check_type='amount_consistency',
        severity='OK',
        finding=f'Betraege konsistent ({case_amount} EUR).',
    )


# ---------------------------------------------------------------------------
# b) Duplicate detection
# ---------------------------------------------------------------------------

def check_duplicate_detection(
    case: CaseRecord,
    all_cases: list[CaseRecord],
) -> RiskCheck:
    """Detect potential duplicate cases (same vendor + amount + date ±7 days)."""
    case_id = str(case.id)

    if case.vendor_name is None or case.total_amount is None:
        return RiskCheck(
            case_id=case_id,
            check_type='duplicate_detection',
            severity='OK',
            finding='Kein Vendor/Betrag gesetzt — Duplikatpruefung uebersprungen.',
        )

    vendor_lower = case.vendor_name.lower().strip()
    amount = case.total_amount
    case_date: date = case.created_at.date() if case.created_at else date.today()

    for other in all_cases:
        if other.id == case.id:
            continue
        if other.tenant_id != case.tenant_id:
            continue
        if other.vendor_name is None or other.total_amount is None:
            continue

        # Vendor similarity
        other_vendor = other.vendor_name.lower().strip()
        similarity = difflib.SequenceMatcher(None, vendor_lower, other_vendor).ratio()
        if similarity < 0.85:
            continue

        # Same amount (within 0.01 EUR)
        if abs(other.total_amount - amount) > Decimal('0.01'):
            continue

        # Date within ±7 days
        other_date: date = other.created_at.date() if other.created_at else date.today()
        if abs((case_date - other_date).days) > 7:
            continue

        return RiskCheck(
            case_id=case_id,
            check_type='duplicate_detection',
            severity='HIGH',
            finding=(
                f'Moegliches Duplikat: Vorgang {other.case_number or str(other.id)[:8]} '
                f'({other.vendor_name}, {other.total_amount} EUR, '
                f'{other_date.isoformat()}).'
            ),
            recommendation='Doppelten Vorgang pruefen und ggf. zusammenfuehren.',
        )

    return RiskCheck(
        case_id=case_id,
        check_type='duplicate_detection',
        severity='OK',
        finding='Kein Duplikat gefunden.',
    )


# ---------------------------------------------------------------------------
# c) Tax plausibility
# ---------------------------------------------------------------------------

def check_tax_plausibility(case: CaseRecord) -> RiskCheck:
    """Check German tax rate plausibility and Netto+Steuer=Brutto consistency."""
    case_id = str(case.id)
    bp = case.metadata.get('booking_proposal')

    if not isinstance(bp, dict):
        return RiskCheck(
            case_id=case_id,
            check_type='tax_plausibility',
            severity='OK',
            finding='Kein Buchungsvorschlag — Steuerpruefung uebersprungen.',
        )

    # Validate tax rate
    tax_rate = bp.get('tax_rate')
    if tax_rate is not None:
        try:
            rate = float(tax_rate)
        except (TypeError, ValueError):
            rate = None

        if rate is not None and rate not in _ALLOWED_TAX_RATES:
            return RiskCheck(
                case_id=case_id,
                check_type='tax_plausibility',
                severity='HIGH',
                finding=(
                    f'Ungueltiger Steuersatz {rate} % '
                    f'(erlaubt in DE: 0 %, 7 %, 19 %).'
                ),
                recommendation='Steuersatz im Buchungsvorschlag korrigieren.',
            )

    # Validate Netto + Steuer = Brutto
    try:
        net = Decimal(str(bp['net_amount'])) if bp.get('net_amount') is not None else None
        tax = Decimal(str(bp['tax_amount'])) if bp.get('tax_amount') is not None else None
        gross = Decimal(str(bp['gross_amount'])) if bp.get('gross_amount') is not None else None
    except (InvalidOperation, ValueError):
        return RiskCheck(
            case_id=case_id,
            check_type='tax_plausibility',
            severity='MEDIUM',
            finding='Betragsfelder im Buchungsvorschlag konnten nicht geparst werden.',
            recommendation='Buchungsvorschlag erneut generieren.',
        )

    if net is not None and tax is not None and gross is not None:
        deviation = abs((net + tax) - gross)
        if deviation > Decimal('0.02'):
            return RiskCheck(
                case_id=case_id,
                check_type='tax_plausibility',
                severity='HIGH',
                finding=(
                    f'Netto ({net}) + Steuer ({tax}) = {net + tax}, '
                    f'aber Brutto = {gross} (Differenz {deviation} EUR).'
                ),
                recommendation='Buchungsvorschlag erneut generieren.',
            )

    return RiskCheck(
        case_id=case_id,
        check_type='tax_plausibility',
        severity='OK',
        finding='Steuerberechnung plausibel.',
    )


# ---------------------------------------------------------------------------
# d) Vendor consistency
# ---------------------------------------------------------------------------

def check_vendor_consistency(
    case: CaseRecord,
    documents: list[CaseDocumentRecord],
) -> RiskCheck:
    """Compare vendor name in case vs documents/document_analysis."""
    case_id = str(case.id)

    if not case.vendor_name:
        return RiskCheck(
            case_id=case_id,
            check_type='vendor_consistency',
            severity='OK',
            finding='Kein Vendor-Name im Vorgang — Konsistenzpruefung uebersprungen.',
        )

    # Collect candidate vendor names from documents and case metadata
    doc_vendor: str | None = None

    # From case-level document_analysis
    doc_analysis = case.metadata.get('document_analysis')
    if isinstance(doc_analysis, dict):
        doc_vendor = (
            doc_analysis.get('vendor_name')
            or doc_analysis.get('sender')
            or doc_analysis.get('issuer')
        )

    # From individual document metadata (overrides if found)
    for doc in documents:
        candidate = doc.metadata.get('vendor_name') or doc.metadata.get('sender')
        if candidate:
            doc_vendor = str(candidate)
            break

    if not doc_vendor:
        return RiskCheck(
            case_id=case_id,
            check_type='vendor_consistency',
            severity='OK',
            finding='Kein Vendor-Name in Dokumenten — Konsistenzpruefung uebersprungen.',
        )

    similarity = difflib.SequenceMatcher(
        None,
        case.vendor_name.lower().strip(),
        doc_vendor.lower().strip(),
    ).ratio()

    if similarity < 0.6:
        return RiskCheck(
            case_id=case_id,
            check_type='vendor_consistency',
            severity='MEDIUM',
            finding=(
                f'Vendor-Name inkonsistent: Vorgang="{case.vendor_name}", '
                f'Dokument="{doc_vendor}" (Aehnlichkeit {similarity:.0%}).'
            ),
            recommendation='Vendor-Name im Vorgang pruefen und ggf. korrigieren.',
        )
    if similarity < 0.85:
        return RiskCheck(
            case_id=case_id,
            check_type='vendor_consistency',
            severity='LOW',
            finding=(
                f'Leichte Abweichung im Vendor-Namen: '
                f'"{case.vendor_name}" vs "{doc_vendor}" '
                f'(Aehnlichkeit {similarity:.0%}).'
            ),
        )
    return RiskCheck(
        case_id=case_id,
        check_type='vendor_consistency',
        severity='OK',
        finding=f'Vendor-Name konsistent ("{case.vendor_name}").',
    )


# ---------------------------------------------------------------------------
# e) Booking plausibility
# ---------------------------------------------------------------------------

def check_booking_plausibility(case: CaseRecord) -> RiskCheck:
    """Check if booking proposal is present and plausible."""
    case_id = str(case.id)
    bp = case.metadata.get('booking_proposal')

    if not isinstance(bp, dict):
        return RiskCheck(
            case_id=case_id,
            check_type='booking_plausibility',
            severity='LOW',
            finding='Kein Buchungsvorschlag vorhanden.',
            recommendation='Buchungsvorschlag erstellen (Accounting Analyst).',
        )

    issues: list[str] = []
    severity_val = 0  # maps to OK

    # Check confidence
    try:
        confidence = float(bp.get('confidence') or 0)
    except (TypeError, ValueError):
        confidence = 0.0

    if confidence < 0.5:
        issues.append(f'Niedrige Konfidenz ({confidence:.0%})')
        severity_val = max(severity_val, 3)  # HIGH

    # Check SKR03 accounts exist in catalog
    soll = str(bp.get('skr03_soll') or '').strip()
    haben = str(bp.get('skr03_haben') or '').strip()

    if soll and soll not in SKR03_COMMON_ACCOUNTS:
        issues.append(f'Soll-Konto {soll!r} nicht im SKR03-Katalog')
        severity_val = max(severity_val, 2)  # MEDIUM
    if haben and haben not in SKR03_COMMON_ACCOUNTS:
        issues.append(f'Haben-Konto {haben!r} nicht im SKR03-Katalog')
        severity_val = max(severity_val, 2)  # MEDIUM

    if not soll or not haben:
        issues.append('Buchungskonten unvollstaendig')
        severity_val = max(severity_val, 2)  # MEDIUM

    if issues:
        sev_map = {0: 'OK', 1: 'LOW', 2: 'MEDIUM', 3: 'HIGH', 4: 'CRITICAL'}
        sev = sev_map.get(severity_val, 'MEDIUM')
        return RiskCheck(
            case_id=case_id,
            check_type='booking_plausibility',
            severity=sev,  # type: ignore[arg-type]
            finding='Buchungsvorschlag problematisch: ' + '; '.join(issues) + '.',
            recommendation='Buchungsvorschlag pruefen oder neu generieren.',
        )

    return RiskCheck(
        case_id=case_id,
        check_type='booking_plausibility',
        severity='OK',
        finding=(
            f'Buchungsvorschlag plausibel '
            f'(Konfidenz {confidence:.0%}, Konten {soll}/{haben}).'
        ),
    )
