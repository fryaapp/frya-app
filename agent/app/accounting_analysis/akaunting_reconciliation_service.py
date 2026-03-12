from __future__ import annotations

import uuid
from enum import Enum

import httpx
from pydantic import BaseModel

from app.accounting_analysis.models import AkauntingReconciliationInput, AkauntingReconciliationResult
from app.audit.service import AuditService
from app.connectors.accounting_akaunting import AkauntingConnector


class ReconciliationResult(str, Enum):
    MATCH_FOUND = 'MATCH_FOUND'
    NO_MATCH_FOUND = 'NO_MATCH_FOUND'
    AMBIGUOUS_MATCH = 'AMBIGUOUS_MATCH'
    PROBE_ERROR = 'PROBE_ERROR'
    AKAUNTING_UNAVAILABLE = 'AKAUNTING_UNAVAILABLE'


class AkauntingProbeResult(BaseModel):
    result: ReconciliationResult
    probe_fields: dict
    matches: list[dict]
    note: str
    actor: str = 'system:akaunting_probe_v1'
    is_read_only: bool = True
    akaunting_write_executed: bool = False

_ALLOWED_END_STATES = {
    'EXTERNAL_ACCOUNTING_COMPLETED',
    'EXTERNAL_RETURN_CLARIFICATION_COMPLETED',
}

_SUMMARY = {
    'FOUND': lambda t, i: f'Akaunting-Abgleich: {t}/{i} gefunden.',
    'NOT_FOUND': lambda t, i: f'Akaunting-Abgleich: {t}/{i} nicht gefunden.',
    'ERROR': lambda t, i: f'Akaunting-Abgleich {t}/{i} fehlgeschlagen.',
}


class AkauntingReconciliationService:
    def __init__(self, akaunting_connector: AkauntingConnector, audit_service: AuditService) -> None:
        self.akaunting_connector = akaunting_connector
        self.audit_service = audit_service

    async def lookup(self, payload: AkauntingReconciliationInput) -> AkauntingReconciliationResult:
        chronology = await self.audit_service.by_case(payload.case_id, limit=500)
        actions = {e.action for e in chronology}
        if not actions.intersection(_ALLOWED_END_STATES):
            raise ValueError(
                'Akaunting-Abgleich ist nur hinter einem konservativen Endzustand erlaubt '
                '(EXTERNAL_ACCOUNTING_COMPLETED oder EXTERNAL_RETURN_CLARIFICATION_COMPLETED).'
            )

        raw_data: dict | None = None
        error_detail: str | None = None
        try:
            raw_data = await self.akaunting_connector.get_object(payload.object_type, payload.object_id)
            status = 'FOUND'
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                status = 'NOT_FOUND'
            else:
                status = 'ERROR'
                error_detail = f'HTTP {exc.response.status_code}'
        except Exception as exc:
            status = 'ERROR'
            error_detail = str(exc)

        result = AkauntingReconciliationResult(
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
            'action': 'AKAUNTING_RECONCILIATION_LOOKUP',
            'result': status,
            'agent_name': 'akaunting-reconciliation-v1',
            'llm_output': result.model_dump(mode='json'),
        })

        return result

    async def probe_case(self, case_id: str, accounting_data: dict) -> AkauntingProbeResult:
        """Read-only probe: search Akaunting for matching documents. Never writes."""
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
            bill_matches = await self.akaunting_connector.search_bills(
                reference=reference,
                amount=amount,
                contact_name=contact_name,
            )
            invoice_matches = await self.akaunting_connector.search_invoices(
                reference=reference,
                amount=amount,
                contact_name=contact_name,
            )
            all_matches = bill_matches + invoice_matches
            # Deduplicate by id+type
            seen: set[str] = set()
            unique_matches: list[dict] = []
            for m in all_matches:
                key = f"{m.get('id', '')}-{m.get('type', '')}"
                if key not in seen:
                    seen.add(key)
                    unique_matches.append(m)
            matches = unique_matches[:5]

            if len(matches) == 0:
                result_status = ReconciliationResult.NO_MATCH_FOUND
                note = f'Keine Akaunting-Eintraege zu Referenz={reference}, Betrag={amount}, Kontakt={contact_name} gefunden.'
            elif len(matches) == 1:
                result_status = ReconciliationResult.MATCH_FOUND
                m = matches[0]
                note = (
                    f'Eindeutiger Treffer: id={m.get("id")}, Betrag={m.get("amount") or m.get("total")}, '
                    f'Referenz={m.get("document_number") or m.get("number") or "-"}, '
                    f'Kontakt={m.get("contact_name") or "-"}.'
                )
            else:
                result_status = ReconciliationResult.AMBIGUOUS_MATCH
                note = f'{len(matches)} Treffer gefunden – manuelle Pruefung erforderlich.'

        except (httpx.ConnectError, httpx.TimeoutException):
            result_status = ReconciliationResult.AKAUNTING_UNAVAILABLE
            note = 'Akaunting nicht erreichbar (Connection Error / Timeout).'
        except Exception as exc:
            result_status = ReconciliationResult.PROBE_ERROR
            note = f'Probe-Fehler: {exc}'

        probe_result = AkauntingProbeResult(
            result=result_status,
            probe_fields=probe_fields,
            matches=matches,
            note=note,
        )

        await self.audit_service.log_event({
            'event_id': str(uuid.uuid4()),
            'case_id': case_id,
            'source': 'akaunting_probe_v1',
            'action': 'AKAUNTING_PROBE_EXECUTED',
            'result': result_status.value,
            'agent_name': 'akaunting-probe-v1',
            'llm_output': probe_result.model_dump(mode='json'),
        })

        return probe_result
