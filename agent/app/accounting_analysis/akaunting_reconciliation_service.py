from __future__ import annotations

import uuid

import httpx

from app.accounting_analysis.models import AkauntingReconciliationInput, AkauntingReconciliationResult
from app.audit.service import AuditService
from app.connectors.accounting_akaunting import AkauntingConnector

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
