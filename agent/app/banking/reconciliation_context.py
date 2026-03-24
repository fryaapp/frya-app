"""Banking Reconciliation Context Service.

Builds a read-only operator work context that bundles:
  - document / case context
  - accounting / Buchhaltung context
  - banking / transaction context
  - reconciliation review / handoff / clarification status
  - match / mismatch / gap interpretation
  - next manual action

Conservative boundary:
  - GET only against Buchhaltung
  - no synthetic audit event from this builder
  - bank_write_executed is always False
  - no_financial_write is always True
"""
from __future__ import annotations

import hashlib
import json as _json
from datetime import datetime, timedelta, timezone
from typing import Any

from app.audit.service import AuditService
from app.banking.models import (
    BankProbeResult,
    FeedStatus,
    ReconciliationComparisonRow,
    ReconciliationContext,
    ReconciliationDecisionTrail,
    ReconciliationDimensionStatus,
    ReconciliationOpenItemSummary,
    ReconciliationSignal,
    ReviewGuidanceLevel,
    TransactionCandidate,
)
from app.banking.service import _determine_result, infer_doc_type
from app.open_items.service import OpenItemsService

_CONTEXT_VERSION = 'reconciliation-context-v1.6'
_ACTIVE_STATUSES = {'OPEN', 'WAITING_USER', 'WAITING_DATA', 'SCHEDULED'}


def _normalize_payload(payload: Any) -> Any:
    if isinstance(payload, str):
        try:
            return _json.loads(payload)
        except Exception:
            return payload
    return payload


def _latest_payload(events: list[Any], actions: set[str]) -> dict[str, Any] | None:
    for event in reversed(events):
        if getattr(event, 'action', None) not in actions:
            continue
        payload = _normalize_payload(getattr(event, 'llm_output', None))
        if isinstance(payload, dict):
            return payload
    return None


def _field_value(field: Any) -> Any:
    if isinstance(field, dict):
        return field.get('value')
    return None


def _to_float(value: Any) -> float | None:
    if value in (None, ''):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _first_non_empty(*values: Any) -> Any:
    for value in values:
        if value not in (None, '', [], {}):
            return value
    return None


def _date_window(doc_date: str | None, date_from: str | None, date_to: str | None) -> tuple[str | None, str | None]:
    if date_from or date_to:
        return date_from, date_to
    if not doc_date:
        return None, None
    try:
        parsed = datetime.fromisoformat(str(doc_date)[:10])
    except ValueError:
        return None, None
    return (
        (parsed - timedelta(days=21)).date().isoformat(),
        (parsed + timedelta(days=21)).date().isoformat(),
    )


def _token_overlap(needle: str, haystack: str) -> bool:
    needle_tokens = [t for t in needle.lower().replace('/', ' ').replace('-', ' ').split() if len(t) >= 4]
    haystack_lower = haystack.lower()
    return any(token in haystack_lower for token in needle_tokens)


def _extract_document_context(
    events: list[Any],
    reference: str | None,
    amount: float | None,
    contact_name: str | None,
    doc_type: str | None,
    doc_currency: str | None,
    doc_date: str | None,
) -> dict[str, Any]:
    accounting_review = _latest_payload(events, {'ACCOUNTING_REVIEW_DRAFT_READY'}) or {}
    accounting_analysis = _latest_payload(events, {'ACCOUNTING_ANALYSIS_COMPLETED'}) or {}
    bank_probe = _latest_payload(events, {'BANK_TRANSACTION_PROBE_EXECUTED', 'BANK_TEST_PROBE_EXECUTED'}) or {}

    review_refs = accounting_review.get('references') or []
    analysis_ref = _field_value(accounting_analysis.get('invoice_reference_hint'))
    analysis_contact = _field_value(accounting_analysis.get('supplier_or_counterparty_hint'))
    amount_summary = accounting_analysis.get('amount_summary') or {}
    analysis_amount = _field_value(amount_summary.get('total_amount'))
    analysis_currency = _field_value(amount_summary.get('currency'))

    probe_fields = bank_probe.get('probe_fields') or {}

    resolved_reference = _first_non_empty(reference, analysis_ref, review_refs[0] if review_refs else None, probe_fields.get('reference'))
    resolved_amount = _to_float(_first_non_empty(amount, analysis_amount, accounting_review.get('total_amount'), probe_fields.get('amount')))
    resolved_contact = _first_non_empty(contact_name, analysis_contact, accounting_review.get('sender'), probe_fields.get('contact_name'))
    resolved_currency = _first_non_empty(doc_currency, analysis_currency, accounting_review.get('currency'), 'EUR')
    resolved_date = _first_non_empty(doc_date, accounting_review.get('document_date'), accounting_review.get('due_date'))
    resolved_doc_type = infer_doc_type(
        resolved_reference,
        _first_non_empty(doc_type, probe_fields.get('doc_type')),
    )

    return {
        'reference': resolved_reference,
        'amount': resolved_amount,
        'contact_name': resolved_contact,
        'doc_currency': resolved_currency,
        'doc_date': resolved_date,
        'doc_type': resolved_doc_type,
    }


def _lookup_accounting_docs(
    reference: str | None,
    amount: float | None,
    contact_name: str | None,
    doc_type: str,
):
    async def _run() -> tuple[str | None, str, list[dict], dict[str, Any]]:
        """Search internal accounting bookings for matching documents."""
        docs: list[dict] = []
        try:
            from app.dependencies import get_accounting_repository
            import uuid as _uuid
            repo = get_accounting_repository()
            tenant_id = _uuid.UUID('00000000-0000-0000-0000-000000000000')
            bookings = await repo.list_bookings(tenant_id, limit=100)

            for b in bookings:
                score = 0
                if reference and reference.lower() in (b.document_number or '').lower():
                    score += 2
                if contact_name and contact_name.lower() in (b.description or '').lower():
                    score += 1
                if amount is not None and abs(float(b.gross_amount) - amount) <= abs(amount) * 0.05:
                    score += 2
                if score >= 2:
                    docs.append({
                        'id': str(b.id),
                        'document_number': b.document_number,
                        'status': b.status,
                        'amount': str(b.gross_amount),
                        'contact_name': b.description,
                    })

            docs = docs[:5]
        except Exception as exc:
            return 'UNAVAILABLE', f'Accounting-Lookup fehlgeschlagen: {exc}', [], {}

        if len(docs) == 1:
            doc = docs[0]
            result = 'FOUND'
            note = 'Buchung gefunden.'
            details = {
                'doc_id': str(doc.get('id') or doc.get('document_number') or ''),
                'doc_reference': str(doc.get('document_number') or ''),
                'doc_status': str(doc.get('status') or ''),
                'doc_amount': _to_float(doc.get('amount')),
                'doc_contact': str(doc.get('contact_name') or ''),
            }
            return result, note, docs[:5], details

        if len(docs) > 1:
            return 'AMBIGUOUS', f'{len(docs)} Buchungen gefunden.', docs[:5], {}

        return 'NOT_FOUND', 'Keine passende Buchung gefunden.', [], {}

    return _run()


def _bank_probe_from_live_data(
    transactions: list[dict],
    feed_status: FeedStatus | None,
    reference: str | None,
    amount: float | None,
    contact_name: str | None,
    date_from: str | None,
    date_to: str | None,
    doc_type: str,
) -> tuple[str, str, list[dict], list[TransactionCandidate]]:
    result, candidates, note = _determine_result(
        transactions=transactions[:10],
        has_filters=any(v is not None for v in [reference, amount, contact_name, date_from, date_to]),
        reference=reference,
        amount=amount,
        contact_name=contact_name,
        date_from=date_from,
        date_to=date_to,
        feed_total=feed_status.transactions_total if feed_status else len(transactions),
        doc_type=doc_type,
    )
    return result.value, note, transactions[:10], candidates


def _comparison_status_exact(doc_value: Any, bank_value: Any, accounting_value: Any = None) -> ReconciliationDimensionStatus:
    values = [value for value in (doc_value, accounting_value, bank_value) if value not in (None, '')]
    if len(values) <= 1:
        return ReconciliationDimensionStatus.MISSING
    normalized = {str(value).strip().lower() for value in values}
    if len(normalized) == 1:
        return ReconciliationDimensionStatus.MATCH
    return ReconciliationDimensionStatus.CONFLICT


def _comparison_status_amount(doc_value: float | None, acc_value: float | None, bank_value: float | None) -> tuple[ReconciliationDimensionStatus, str]:
    values = [value for value in (doc_value, acc_value, bank_value) if value is not None]
    if len(values) <= 1:
        return ReconciliationDimensionStatus.MISSING, 'Zu wenig Betragskontext.'
    baseline = values[0]
    if all(abs(value - baseline) < 0.01 for value in values[1:]):
        return ReconciliationDimensionStatus.MATCH, 'Betrag deckt sich exakt.'
    if baseline and all(abs(value - baseline) / abs(baseline) <= 0.05 for value in values[1:]):
        return ReconciliationDimensionStatus.PARTIAL, 'Betrag liegt nahe beieinander.'
    return ReconciliationDimensionStatus.CONFLICT, 'Betragswerte laufen auseinander.'


def _comparison_status_date(doc_date: str | None, bank_date: str | None) -> tuple[ReconciliationDimensionStatus, str]:
    if not doc_date or not bank_date:
        return ReconciliationDimensionStatus.MISSING, 'Datum im Dokument oder Banking fehlt.'
    try:
        doc_dt = datetime.fromisoformat(str(doc_date)[:10])
        bank_dt = datetime.fromisoformat(str(bank_date)[:10])
    except ValueError:
        return ReconciliationDimensionStatus.UNKNOWN, 'Datum nicht sauber parsebar.'
    delta_days = abs((bank_dt.date() - doc_dt.date()).days)
    if delta_days <= 3:
        return ReconciliationDimensionStatus.MATCH, 'Datum liegt sehr nah.'
    if delta_days <= 21:
        return ReconciliationDimensionStatus.PARTIAL, 'Datum liegt noch im plausiblen Fenster.'
    return ReconciliationDimensionStatus.CONFLICT, 'Datum ist deutlich entfernt.'


def _build_comparison_rows(
    reference: str | None,
    amount: float | None,
    contact_name: str | None,
    doc_date: str | None,
    doc_type: str,
    accounting_reference: str | None,
    accounting_amount: float | None,
    accounting_contact: str | None,
    best: TransactionCandidate | None,
) -> list[ReconciliationComparisonRow]:
    best_reasons = set(best.reason_codes if best else [])
    amount_status, amount_note = _comparison_status_amount(amount, accounting_amount, best.amount if best else None)
    date_status, date_note = _comparison_status_date(doc_date, best.date if best else None)

    reference_status = _comparison_status_exact(reference, best.reference if best else None, accounting_reference)
    reference_note = 'Referenz deckt sich.' if reference_status == ReconciliationDimensionStatus.MATCH else 'Referenz ist schwach, fehlt oder widerspricht.'
    if 'REFERENCE_WEAK' in best_reasons:
        reference_status = ReconciliationDimensionStatus.PARTIAL
        reference_note = 'Referenz nur schwach abgedeckt.'
    elif 'REFERENCE_NONE' in best_reasons or 'REFERENCE_MISSING' in best_reasons:
        reference_status = ReconciliationDimensionStatus.MISSING
        reference_note = 'Referenz fehlt im Banking-Kandidaten.'

    contact_status = _comparison_status_exact(contact_name, best.contact_name if best else None, accounting_contact)
    contact_note = 'Gegenpartei deckt sich.' if contact_status == ReconciliationDimensionStatus.MATCH else 'Gegenpartei ist schwach, fehlt oder widerspricht.'
    if 'CONTACT_WEAK' in best_reasons:
        contact_status = ReconciliationDimensionStatus.PARTIAL
        contact_note = 'Gegenpartei nur schwach erkennbar.'
    elif 'CONTACT_MISSING' in best_reasons:
        contact_status = ReconciliationDimensionStatus.MISSING
        contact_note = 'Keine belastbare Gegenpartei im Banking.'

    type_status = ReconciliationDimensionStatus.MISSING
    type_note = 'Dokument- oder Transaktionstyp fehlt.'
    if best and doc_type and doc_type != 'unknown' and best.tx_type:
        if best.tx_type == doc_type:
            type_status = ReconciliationDimensionStatus.MATCH
            type_note = 'Income/Expense-Richtung passt.'
        else:
            type_status = ReconciliationDimensionStatus.CONFLICT
            type_note = 'Income/Expense-Richtung widerspricht.'

    return [
        ReconciliationComparisonRow(
            field_key='amount',
            label='Betrag',
            document_value=amount,
            accounting_value=accounting_amount,
            banking_value=best.amount if best else None,
            status=amount_status,
            note=amount_note,
        ),
        ReconciliationComparisonRow(
            field_key='reference',
            label='Referenz',
            document_value=reference,
            accounting_value=accounting_reference,
            banking_value=best.reference if best else None,
            status=reference_status,
            note=reference_note,
        ),
        ReconciliationComparisonRow(
            field_key='contact',
            label='Gegenpartei',
            document_value=contact_name,
            accounting_value=accounting_contact,
            banking_value=best.contact_name if best else None,
            status=contact_status,
            note=contact_note,
        ),
        ReconciliationComparisonRow(
            field_key='date',
            label='Datum',
            document_value=doc_date,
            accounting_value=None,
            banking_value=best.date if best else None,
            status=date_status,
            note=date_note,
        ),
        ReconciliationComparisonRow(
            field_key='direction',
            label='Richtung',
            document_value=doc_type,
            accounting_value=None,
            banking_value=best.tx_type if best else None,
            status=type_status,
            note=type_note,
        ),
    ]


def _compute_signal_and_analysis(
    bank_result: str,
    best: TransactionCandidate | None,
    accounting_result: str | None,
) -> tuple[ReconciliationSignal, list[str], list[str], list[str]]:
    pro: list[str] = []
    contra: list[str] = []
    missing: list[str] = []

    if bank_result in (BankProbeResult.NO_TRANSACTIONS_AVAILABLE, 'NO_TRANSACTIONS_AVAILABLE'):
        missing.append('Banking-Kontext fehlt: Feed ist leer.')
        if accounting_result == 'FOUND':
            contra.append('Accounting-Kontext liegt vor, aber Banking-Bezug fehlt.')
        return ReconciliationSignal.MISSING_DATA, pro, contra, missing

    if bank_result in (BankProbeResult.PROBE_ERROR, 'PROBE_ERROR', BankProbeResult.BANK_UNAVAILABLE, 'BANK_UNAVAILABLE'):
        missing.append('Banking-Kontext konnte nicht belastbar geladen werden.')
        return ReconciliationSignal.MISSING_DATA, pro, contra, missing

    if best is None:
        contra.append('Kein Banking-Kandidat mit Score > 0 gefunden.')
        missing.append('Banking-Kontext vorhanden, aber ohne tragfähigen Match.')
        if accounting_result == 'FOUND':
            contra.append('Accounting-Beleg existiert, Banking-Kandidat fehlt.')
        elif accounting_result in ('NOT_FOUND', None):
            missing.append('Accounting-Kontext fehlt ebenfalls oder ist leer.')
        return ReconciliationSignal.MISSING_DATA, pro, contra, missing

    reasons = set(best.reason_codes)

    if 'AMOUNT_EXACT' in reasons:
        pro.append(f'Betrag exakt: {best.amount} {best.currency or "EUR"}.')
    elif 'AMOUNT_NEAR' in reasons:
        pro.append(f'Betrag nahe dran: {best.amount} {best.currency or "EUR"}.')
    elif 'AMOUNT_MISMATCH' in reasons:
        contra.append('Betrag widerspricht.')
    else:
        missing.append('Betrag im Banking nicht belastbar.')

    if 'REFERENCE_EXACT' in reasons or 'REFERENCE_MATCH' in reasons:
        pro.append(f'Referenz passt: {best.reference or "-"}.')
    elif 'REFERENCE_WEAK' in reasons:
        contra.append('Referenz nur schwach passend.')
    elif 'REFERENCE_MISSING' in reasons:
        missing.append('Referenz fehlt im Banking.')
    else:
        contra.append('Referenz passt nicht.')

    if 'CONTACT_EXACT' in reasons or 'CONTACT_MATCH' in reasons:
        pro.append(f'Gegenpartei passt: {best.contact_name or "-"}.')
    elif 'CONTACT_WEAK' in reasons:
        contra.append('Gegenpartei nur schwach passend.')
    elif 'CONTACT_MISSING' in reasons:
        missing.append('Gegenpartei fehlt im Banking.')

    if 'DATE_IN_RANGE' in reasons:
        pro.append(f'Datum passt: {best.date or "-"}.')
    elif 'DATE_NEAR' in reasons:
        pro.append(f'Datum plausibel nah: {best.date or "-"}.')
    elif 'DATE_STALE' in reasons:
        contra.append(f'Datum liegt zu weit weg: {best.date or "-"}.')
    elif 'DATE_UNKNOWN' in reasons:
        missing.append('Kein belastbares Banking-Datum.')

    if 'TYPE_MISMATCH' in reasons:
        contra.append('Income/Expense-Richtung widerspricht.')
    elif 'TYPE_MATCH' in reasons:
        pro.append('Income/Expense-Richtung passt.')

    if accounting_result == 'FOUND':
        pro.append('Accounting-Kontext ist vorhanden.')
    elif accounting_result == 'AMBIGUOUS':
        contra.append('Accounting-Kontext ist mehrdeutig.')
    elif accounting_result == 'NOT_FOUND':
        missing.append('Accounting-Kontext fehlt.')
    elif accounting_result == 'UNAVAILABLE':
        missing.append('Accounting-Kontext war nicht erreichbar.')

    if 'TYPE_MISMATCH' in reasons:
        return ReconciliationSignal.CONFLICT, pro, contra, missing
    if bank_result in (BankProbeResult.AMBIGUOUS_MATCH, 'AMBIGUOUS_MATCH'):
        contra.append('Mehrere plausible Banking-Kandidaten vorhanden.')
        return ReconciliationSignal.UNCLEAR, pro, contra, missing
    if (
        bank_result in (BankProbeResult.MATCH_FOUND, 'MATCH_FOUND')
        and 'AMOUNT_EXACT' in reasons
        and ('REFERENCE_EXACT' in reasons or 'REFERENCE_MATCH' in reasons)
        and 'TYPE_MISMATCH' not in reasons
    ):
        return ReconciliationSignal.PLAUSIBLE, pro, contra, missing
    if bank_result in (BankProbeResult.MATCH_FOUND, 'MATCH_FOUND', BankProbeResult.CANDIDATE_FOUND, 'CANDIDATE_FOUND'):
        return ReconciliationSignal.UNCLEAR, pro, contra, missing
    return ReconciliationSignal.MISSING_DATA, pro, contra, missing


def _next_action(
    signal: ReconciliationSignal,
    bank_result: str,
    review_outcome: str | None,
    handoff_status: str | None,
    clarification_status: str | None,
) -> str:
    if handoff_status == 'BANK_MANUAL_HANDOFF_COMPLETED':
        return 'Banking-Handoff ist abgeschlossen. Nur noch externen Abschluss dokumentieren.'
    if clarification_status == 'BANK_CLARIFICATION_COMPLETED':
        return 'Klärung ist abgeschlossen. Abgleich erneut mit präzisiertem Kontext prüfen.'
    if review_outcome == 'BANK_RECONCILIATION_CONFIRMED':
        return 'Review ist bestätigt. Manuellen Banking-Handoff im externen System abarbeiten.'
    if review_outcome == 'BANK_RECONCILIATION_REJECTED':
        return 'Review ist abgelehnt. Klärfall oder präzisierte Probe vorbereiten.'
    if signal == ReconciliationSignal.PLAUSIBLE:
        return 'Starker Match. Kandidat kurz prüfen und Banking-Review bestätigen.'
    if signal == ReconciliationSignal.UNCLEAR:
        if bank_result in (BankProbeResult.AMBIGUOUS_MATCH, 'AMBIGUOUS_MATCH'):
            return 'Mehrere plausible Kandidaten. Richtigen Treffer manuell auswählen.'
        return 'Unklarer Match. Referenz, Betrag und Gegenpartei manuell gegenprüfen.'
    if signal == ReconciliationSignal.CONFLICT:
        return 'Konflikt. Dokumentrichtung oder Transaktionstyp zuerst klären.'
    return 'Datenlücke schließen: fehlenden Banking- oder Accounting-Kontext ergänzen.'


def _current_stage(
    review_outcome: str | None,
    handoff_status: str | None,
    clarification_status: str | None,
) -> str:
    if handoff_status:
        return handoff_status
    if clarification_status:
        return clarification_status
    if review_outcome:
        return review_outcome
    return 'BANK_RECONCILIATION_REVIEW_PENDING'


def _next_action(
    signal: ReconciliationSignal,
    bank_result: str,
    review_outcome: str | None,
    handoff_ready_status: str | None,
    handoff_resolution_status: str | None,
    clarification_status: str | None,
    external_status: str | None,
) -> str:
    if external_status == 'EXTERNAL_BANKING_PROCESS_COMPLETED':
        return 'Externer Banking-Abschluss ist dokumentiert. Keine weitere Agentenaktion offen.'
    if external_status == 'OUTSIDE_AGENT_BANKING_PROCESS':
        return 'Externen manuellen Banking-Abschluss dokumentieren oder bewusst ausserhalb Frya belassen.'
    if clarification_status == 'BANKING_CLARIFICATION_COMPLETED':
        return 'Banking-Klaerung ist abgeschlossen. Externen Banking-Abschluss dokumentieren.'
    if clarification_status == 'BANKING_CLARIFICATION_OPEN':
        return 'Rueckgabegrund manuell klaeren und den Klaerabschluss dokumentieren.'
    if handoff_resolution_status == 'BANKING_HANDOFF_COMPLETED':
        return 'Banking-Handoff ist dokumentiert abgeschlossen. Externe Weiterbearbeitung bleibt ausserhalb Frya.'
    if handoff_resolution_status == 'BANKING_HANDOFF_RETURNED':
        return 'Banking-Handoff wurde zurueckgegeben. Klaerung oder erneute Pruefung vorbereiten.'
    if handoff_ready_status == 'BANKING_HANDOFF_READY':
        return 'Handoff ist bereit. Externe manuelle Weitergabe dokumentieren oder Rueckgabe markieren.'
    if clarification_status == 'BANK_CLARIFICATION_COMPLETED':
        return 'Klaerung ist abgeschlossen. Abgleich erneut mit praezisiertem Kontext pruefen.'
    if review_outcome == 'BANK_RECONCILIATION_CONFIRMED':
        return 'Review ist bestaetigt. Banking-Handoff explizit bereitstellen und extern manuell weitergeben.'
    if review_outcome == 'BANK_RECONCILIATION_REJECTED':
        return 'Review ist abgelehnt. Klaerfall oder praezisierte Probe vorbereiten.'
    if signal == ReconciliationSignal.PLAUSIBLE:
        return 'Starker Match. Kandidat kurz pruefen und Banking-Review bestaetigen.'
    if signal == ReconciliationSignal.UNCLEAR:
        if bank_result in (BankProbeResult.AMBIGUOUS_MATCH, 'AMBIGUOUS_MATCH'):
            return 'Mehrere plausible Kandidaten. Richtigen Treffer manuell auswaehlen.'
        return 'Unklarer Match. Referenz, Betrag und Gegenpartei manuell gegenpruefen.'
    if signal == ReconciliationSignal.CONFLICT:
        return 'Konflikt. Dokumentrichtung oder Transaktionstyp zuerst klaeren.'
    return 'Datenluecke schliessen: fehlenden Banking- oder Accounting-Kontext ergaenzen.'


def _current_stage(
    review_outcome: str | None,
    handoff_ready_status: str | None,
    handoff_resolution_status: str | None,
    clarification_status: str | None,
    external_status: str | None,
) -> str:
    if external_status:
        return external_status
    if clarification_status:
        return clarification_status
    if handoff_resolution_status:
        return handoff_resolution_status
    if handoff_ready_status:
        return handoff_ready_status
    if review_outcome:
        return review_outcome
    return 'BANK_RECONCILIATION_REVIEW_PENDING'


def _build_context_ref(
    case_id: str,
    reference: str | None,
    amount: float | None,
    doc_type: str,
    bank_result: str,
    best: TransactionCandidate | None,
    accounting_doc_id: str | None,
) -> str:
    raw = '|'.join(
        [
            case_id,
            str(reference or ''),
            str(amount or ''),
            doc_type or '',
            bank_result,
            str(best.transaction_id if best else ''),
            str(best.confidence_score if best else ''),
            str(accounting_doc_id or ''),
            _CONTEXT_VERSION,
        ]
    )
    digest = hashlib.sha1(raw.encode('utf-8')).hexdigest()[:12]
    return f'{case_id}:{_CONTEXT_VERSION}:{digest}'


def _derive_review_guidance(
    signal: ReconciliationSignal,
    bank_result: str,
    best: TransactionCandidate | None,
    missing: list[str],
    contra: list[str],
) -> tuple[ReviewGuidanceLevel, bool, str]:
    reasons = set(best.reason_codes if best else [])
    if signal == ReconciliationSignal.PLAUSIBLE and best and 'TYPE_MISMATCH' not in reasons:
        return (
            ReviewGuidanceLevel.CONFIRMABLE,
            True,
            'Kontext ist confirmbar: Betrag/Referenz tragen den Match und es gibt keinen Richtungs-Konflikt.',
        )
    if signal == ReconciliationSignal.CONFLICT:
        return (
            ReviewGuidanceLevel.REJECT_RECOMMENDED,
            False,
            'Konfliktfall: Review nur als Reject oder Rueckgabe in Klaerung.',
        )
    if signal == ReconciliationSignal.UNCLEAR:
        if bank_result in (BankProbeResult.AMBIGUOUS_MATCH.value, BankProbeResult.AMBIGUOUS_MATCH):
            return (
                ReviewGuidanceLevel.CLARIFICATION_NEEDED,
                False,
                'Mehrere plausible Kandidaten. Erst Auswahl oder Praezisierung, dann Review.',
            )
        return (
            ReviewGuidanceLevel.NOT_CONFIRMABLE,
            False,
            'Kontext ist noch nicht scharf genug fuer Confirm. Kandidaten und Luecken manuell pruefen.',
        )
    return (
        ReviewGuidanceLevel.NOT_CONFIRMABLE,
        False,
        'Nicht confirmbar: es fehlen belastbare Banking- oder Accounting-Daten.',
    )


def _build_operator_summary(
    signal: ReconciliationSignal,
    best: TransactionCandidate | None,
    accounting_result: str | None,
    active_items: list[ReconciliationOpenItemSummary],
    next_action: str,
) -> list[str]:
    lines: list[str] = []
    if best:
        lines.append(
            f'{signal.value}: bester Kandidat {best.transaction_id} mit {best.confidence_score}/100 '
            f'und {best.match_quality.value}.'
        )
    else:
        lines.append(f'{signal.value}: kein belastbarer Banking-Kandidat vorhanden.')
    lines.append(f'Accounting-Kontext: {accounting_result or "UNBEKANNT"}.')
    if active_items:
        lines.append(f'{len(active_items)} offene Folgearbeit(en): {", ".join(item.title for item in active_items[:3])}.')
    lines.append(next_action)
    return lines


class ReconciliationContextService:
    """Read-only reconciliation context builder."""

    def __init__(
        self,
        bank_service,
        audit_service: AuditService,
        open_items_service: OpenItemsService,
    ) -> None:
        self.bank_service = bank_service
        self.audit_service = audit_service
        self.open_items_service = open_items_service

    async def build(
        self,
        case_id: str,
        reference: str | None = None,
        amount: float | None = None,
        contact_name: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        doc_type: str | None = None,
        doc_currency: str | None = None,
        doc_date: str | None = None,
    ) -> ReconciliationContext:
        chronology = list(await self.audit_service.by_case(case_id, limit=500))
        document_context = _extract_document_context(
            chronology,
            reference=reference,
            amount=amount,
            contact_name=contact_name,
            doc_type=doc_type,
            doc_currency=doc_currency,
            doc_date=doc_date,
        )
        resolved_reference = document_context['reference']
        resolved_amount = document_context['amount']
        resolved_contact = document_context['contact_name']
        resolved_doc_type = document_context['doc_type']
        resolved_doc_currency = document_context['doc_currency']
        resolved_doc_date = document_context['doc_date']
        resolved_date_from, resolved_date_to = _date_window(resolved_doc_date, date_from, date_to)

        feed_status = FeedStatus(
            reachable=True, source_url='internal',
            accounts_available=0, transactions_total=0,
            note='FRYA-interne Buchhaltung',
        )
        transactions: list[dict] = []  # No external transaction source
        bank_result, bank_note, _matches, candidates = _bank_probe_from_live_data(
            transactions=transactions,
            feed_status=feed_status,
            reference=resolved_reference,
            amount=resolved_amount,
            contact_name=resolved_contact,
            date_from=resolved_date_from,
            date_to=resolved_date_to,
            doc_type=resolved_doc_type,
        )
        best = candidates[0] if candidates else None

        accounting_result, accounting_note, accounting_matches, accounting_details = await _lookup_accounting_docs(
            reference=resolved_reference,
            amount=resolved_amount,
            contact_name=resolved_contact,
            doc_type=resolved_doc_type,
        )

        latest_accounting_probe = _latest_payload(chronology, {'ACCOUNTING_PROBE_EXECUTED'}) or {}
        latest_review_outcome: str | None = None
        latest_review_decision: str | None = None
        latest_review_by: str | None = None
        latest_handoff_ready: str | None = None
        latest_handoff_resolution: str | None = None
        latest_clarification: str | None = None
        latest_external: str | None = None

        for event in reversed(chronology):
            action = getattr(event, 'action', '') or ''
            payload = _normalize_payload(getattr(event, 'llm_output', None))
            if action in {'BANK_RECONCILIATION_CONFIRMED', 'BANK_RECONCILIATION_REJECTED'} and latest_review_outcome is None:
                latest_review_outcome = action
                if isinstance(payload, dict):
                    latest_review_decision = payload.get('decision')
                    latest_review_by = payload.get('decided_by')
            elif action == 'BANKING_HANDOFF_READY' and latest_handoff_ready is None:
                latest_handoff_ready = action
            elif action in {'BANKING_HANDOFF_COMPLETED', 'BANKING_HANDOFF_RETURNED'} and latest_handoff_resolution is None:
                latest_handoff_resolution = action
            elif action == 'BANKING_CLARIFICATION_COMPLETED' and latest_clarification is None:
                latest_clarification = action
            elif action == 'EXTERNAL_BANKING_PROCESS_COMPLETED' and latest_external is None:
                latest_external = action

        if latest_external is None and (
            latest_clarification == 'BANKING_CLARIFICATION_COMPLETED'
            or latest_handoff_resolution == 'BANKING_HANDOFF_COMPLETED'
        ):
            latest_external = 'OUTSIDE_AGENT_BANKING_PROCESS'
        if latest_handoff_resolution == 'BANKING_HANDOFF_RETURNED' and latest_clarification is None:
            latest_clarification = 'BANKING_CLARIFICATION_OPEN'

        open_items = await self.open_items_service.list_by_case(case_id)
        active_items = [
            ReconciliationOpenItemSummary(
                item_id=item.item_id,
                title=item.title,
                status=item.status,
                description=item.description,
                due_at=item.due_at.isoformat() if getattr(item, 'due_at', None) else None,
            )
            for item in open_items
            if item.status in _ACTIVE_STATUSES
        ]

        signal, pro, contra, missing = _compute_signal_and_analysis(
            bank_result=bank_result,
            best=best,
            accounting_result=accounting_result,
        )
        comparison_rows = _build_comparison_rows(
            reference=resolved_reference,
            amount=resolved_amount,
            contact_name=resolved_contact,
            doc_date=resolved_doc_date,
            doc_type=resolved_doc_type,
            accounting_reference=accounting_details.get('doc_reference'),
            accounting_amount=accounting_details.get('doc_amount'),
            accounting_contact=accounting_details.get('doc_contact'),
            best=best,
        )
        next_action = _next_action(
            signal=signal,
            bank_result=bank_result,
            review_outcome=latest_review_outcome,
            handoff_ready_status=latest_handoff_ready,
            handoff_resolution_status=latest_handoff_resolution,
            clarification_status=latest_clarification,
            external_status=latest_external,
        )
        review_guidance, confirm_allowed, operator_guidance = _derive_review_guidance(
            signal=signal,
            bank_result=bank_result,
            best=best,
            missing=missing,
            contra=contra,
        )
        context_ref = _build_context_ref(
            case_id=case_id,
            reference=resolved_reference,
            amount=resolved_amount,
            doc_type=resolved_doc_type,
            bank_result=bank_result,
            best=best,
            accounting_doc_id=accounting_details.get('doc_id'),
        )

        ctx = ReconciliationContext(
            case_id=case_id,
            context_version=_CONTEXT_VERSION,
            built_at=datetime.now(timezone.utc).isoformat(),
            context_ref=context_ref,
            review_anchor_ref=context_ref,
            doc_reference=resolved_reference,
            doc_amount=resolved_amount,
            doc_currency=resolved_doc_currency,
            doc_date=resolved_doc_date,
            doc_contact=resolved_contact,
            doc_type=resolved_doc_type,
            bank_result=bank_result,
            bank_note=bank_note,
            bank_feed_reachable=feed_status.reachable,
            bank_feed_total=feed_status.transactions_total,
            best_candidate=best,
            all_candidates=candidates,
            accounting_result=accounting_result,
            accounting_doc_id=accounting_details.get('doc_id'),
            accounting_doc_reference=accounting_details.get('doc_reference'),
            accounting_contact=accounting_details.get('doc_contact'),
            accounting_doc_status=accounting_details.get('doc_status'),
            accounting_doc_amount=accounting_details.get('doc_amount'),
            accounting_note=accounting_note,
            accounting_probe_result=latest_accounting_probe.get('result') or (
                'MATCH_FOUND' if accounting_result == 'FOUND' else
                'AMBIGUOUS_MATCH' if accounting_result == 'AMBIGUOUS' else
                'NO_MATCH_FOUND' if accounting_result == 'NOT_FOUND' else
                'PROBE_ERROR' if accounting_result == 'UNAVAILABLE' else None
            ),
            accounting_probe_note=latest_accounting_probe.get('note') or accounting_note,
            accounting_probe_matches=latest_accounting_probe.get('matches') or accounting_matches,
            match_signal=signal,
            pro_match=pro,
            contra_match=contra,
            missing_data=missing,
            operator_summary=_build_operator_summary(
                signal=signal,
                best=best,
                accounting_result=accounting_result,
                active_items=active_items,
                next_action=next_action,
            ),
            best_candidate_reason_codes=list(best.reason_codes) if best else [],
            comparison_rows=comparison_rows,
            operator_guidance=operator_guidance,
            review_guidance=review_guidance,
            confirm_allowed=confirm_allowed,
            candidate_count=len(candidates),
            review_trail=ReconciliationDecisionTrail(
                review_decision=latest_review_decision,
                review_outcome=latest_review_outcome,
                review_by=latest_review_by,
                handoff_status=latest_handoff_resolution or latest_handoff_ready,
                handoff_ready_status=latest_handoff_ready,
                handoff_resolution_status=latest_handoff_resolution,
                clarification_status=latest_clarification,
                external_status=latest_external,
                current_stage=_current_stage(
                    review_outcome=latest_review_outcome,
                    handoff_ready_status=latest_handoff_ready,
                    handoff_resolution_status=latest_handoff_resolution,
                    clarification_status=latest_clarification,
                    external_status=latest_external,
                ),
            ),
            active_open_items=active_items,
            latest_review_decision=latest_review_decision,
            latest_review_outcome=latest_review_outcome,
            latest_review_by=latest_review_by,
            latest_handoff_status=latest_handoff_resolution or latest_handoff_ready,
            latest_handoff_ready_status=latest_handoff_ready,
            latest_handoff_resolution_status=latest_handoff_resolution,
            latest_clarification_status=latest_clarification,
            latest_external_status=latest_external,
            open_items_count=len(active_items),
            open_items_titles=[item.title for item in active_items],
            next_action=next_action,
            is_read_only=True,
            bank_write_executed=False,
            no_financial_write=True,
        )

        assert ctx.is_read_only is True
        assert ctx.bank_write_executed is False
        assert ctx.no_financial_write is True
        return ctx
