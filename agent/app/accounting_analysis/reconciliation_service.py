"""Accounting reconciliation service — searches internal bookings for matches.

Performs reconciliation with lookups against the FRYA accounting_bookings table.
"""
from __future__ import annotations

import uuid
from enum import Enum

from pydantic import BaseModel

from app.accounting_analysis.models import AccountingReconciliationInput, AccountingReconciliationResult
from app.audit.service import AuditService


class ReconciliationResult(str, Enum):
    MATCH_FOUND = 'MATCH_FOUND'
    NO_MATCH_FOUND = 'NO_MATCH_FOUND'
    AMBIGUOUS_MATCH = 'AMBIGUOUS_MATCH'
    PROBE_ERROR = 'PROBE_ERROR'
    ACCOUNTING_UNAVAILABLE = 'ACCOUNTING_UNAVAILABLE'


class AccountingProbeResult(BaseModel):
    result: ReconciliationResult
    probe_fields: dict
    matches: list[dict]
    note: str
    actor: str = 'system:accounting_probe_v1'
    is_read_only: bool = True
    accounting_write_executed: bool = False


_ALLOWED_END_STATES = {
    'EXTERNAL_ACCOUNTING_COMPLETED',
    'EXTERNAL_RETURN_CLARIFICATION_COMPLETED',
}

_SUMMARY = {
    'FOUND': lambda t, i: f'Buchhaltungs-Abgleich: {t}/{i} gefunden.',
    'NOT_FOUND': lambda t, i: f'Buchhaltungs-Abgleich: {t}/{i} nicht gefunden.',
    'ERROR': lambda t, i: f'Buchhaltungs-Abgleich {t}/{i} fehlgeschlagen.',
}


class AccountingReconciliationService:
    def __init__(self, audit_service: AuditService) -> None:
        self.audit_service = audit_service

    async def lookup(self, payload: AccountingReconciliationInput) -> AccountingReconciliationResult:
        chronology = await self.audit_service.by_case(payload.case_id, limit=500)
        actions = {e.action for e in chronology}
        if not actions.intersection(_ALLOWED_END_STATES):
            raise ValueError(
                'Buchhaltungs-Abgleich ist nur hinter einem konservativen Endzustand erlaubt '
                '(EXTERNAL_ACCOUNTING_COMPLETED oder EXTERNAL_RETURN_CLARIFICATION_COMPLETED).'
            )

        # Lookup in internal accounting tables
        raw_data: dict | None = None
        error_detail: str | None = None
        try:
            from app.dependencies import get_accounting_repository
            repo = get_accounting_repository()
            import uuid as _uuid
            tenant_id = _uuid.UUID('00000000-0000-0000-0000-000000000000')
            bookings = await repo.list_bookings(tenant_id, limit=50)
            matching = [
                b for b in bookings
                if str(getattr(b, 'id', '')) == payload.object_id
                or str(getattr(b, 'document_number', '')) == payload.object_id
            ]
            if matching:
                b = matching[0]
                raw_data = {
                    'id': str(b.id),
                    'booking_number': b.booking_number,
                    'description': b.description,
                    'gross_amount': str(b.gross_amount),
                }
                status = 'FOUND'
            else:
                status = 'NOT_FOUND'
        except Exception as exc:
            status = 'ERROR'
            error_detail = str(exc)

        result = AccountingReconciliationResult(
            case_id=payload.case_id,
            object_type=payload.object_type,
            object_id=payload.object_id,
            status=status,
            raw_data=raw_data,
            error_detail=error_detail,
            lookup_note=payload.note,
            triggered_by=payload.triggered_by,
            execution_allowed=False,
            external_write_performed=False,
            summary=_SUMMARY[status](payload.object_type, payload.object_id),
        )

        await self.audit_service.log_event({
            'event_id': str(uuid.uuid4()),
            'case_id': payload.case_id,
            'source': payload.source,
            'action': 'ACCOUNTING_RECONCILIATION_LOOKUP',
            'result': status,
            'agent_name': 'accounting-reconciliation-v1',
            'llm_output': result.model_dump(mode='json'),
        })

        return result

    async def probe_case(self, case_id: str, accounting_data: dict) -> AccountingProbeResult:
        """Read-only probe: search internal bookings for matching documents. Never writes."""
        reference = accounting_data.get('document_number') or accounting_data.get('invoice_number')
        amount_raw = accounting_data.get('amount') or accounting_data.get('total_amount')
        contact_name = accounting_data.get('contact_name') or accounting_data.get('sender')

        try:
            amount = float(amount_raw) if amount_raw is not None else None
        except (TypeError, ValueError):
            amount = None

        probe_fields = {
            'reference': reference,
            'amount': amount,
            'contact_name': contact_name,
        }

        matches: list[dict] = []
        result_status = ReconciliationResult.NO_MATCH_FOUND
        note = 'Keine Treffer gefunden.'

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
                    matches.append({
                        'id': str(b.id),
                        'booking_number': b.booking_number,
                        'description': b.description,
                        'gross_amount': str(b.gross_amount),
                        'document_number': b.document_number,
                        'score': score,
                    })

            matches = sorted(matches, key=lambda m: m.get('score', 0), reverse=True)[:5]

            if len(matches) == 0:
                result_status = ReconciliationResult.NO_MATCH_FOUND
                note = f'Keine Buchungen zu Referenz={reference}, Betrag={amount}, Kontakt={contact_name} gefunden.'
            elif len(matches) == 1:
                result_status = ReconciliationResult.MATCH_FOUND
                m = matches[0]
                note = (
                    f'Eindeutiger Treffer: id={m.get("id")}, Betrag={m.get("gross_amount")}, '
                    f'Referenz={m.get("document_number") or "-"}, '
                    f'Beschreibung={m.get("description") or "-"}.'
                )
            else:
                result_status = ReconciliationResult.AMBIGUOUS_MATCH
                note = f'{len(matches)} Treffer gefunden – manuelle Pruefung erforderlich.'

        except Exception as exc:
            result_status = ReconciliationResult.PROBE_ERROR
            note = f'Probe-Fehler: {exc}'

        probe_result = AccountingProbeResult(
            result=result_status,
            probe_fields=probe_fields,
            matches=matches,
            note=note,
        )

        await self.audit_service.log_event({
            'event_id': str(uuid.uuid4()),
            'case_id': case_id,
            'source': 'accounting_probe_v1',
            'action': 'ACCOUNTING_PROBE_EXECUTED',
            'result': result_status.value,
            'agent_name': 'accounting-probe-v1',
            'llm_output': probe_result.model_dump(mode='json'),
        })

        return probe_result
