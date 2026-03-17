import json
import uuid
from datetime import datetime
from typing import Any, Literal

from app.audit.service import AuditService
from app.open_items.service import OpenItemsService
from app.telegram.document_analyst_followup_service import TelegramDocumentAnalystFollowupService
from app.telegram.models import TelegramDocumentAnalystReviewRecord, TelegramDocumentAnalystStartRecord


class TelegramDocumentAnalystReviewService:
    def __init__(
        self,
        audit_service: AuditService,
        open_items_service: OpenItemsService,
        followup_service: TelegramDocumentAnalystFollowupService,
    ) -> None:
        self.audit_service = audit_service
        self.open_items_service = open_items_service
        self.followup_service = followup_service

    async def mark_ready_from_start(
        self,
        start_record: TelegramDocumentAnalystStartRecord,
        *,
        document_analysis_payload: dict[str, Any] | None,
    ) -> TelegramDocumentAnalystReviewRecord:
        review_record = self._build_ready_record(start_record, document_analysis_payload)
        await self._log_review_record(review_record)
        return review_record

    async def resolve_review(
        self,
        case_id: str,
        *,
        decision: Literal['COMPLETED', 'STILL_OPEN'],
        reviewed_by: str,
        note: str | None,
        source: str,
    ) -> TelegramDocumentAnalystReviewRecord:
        chronology = await self.audit_service.by_case(case_id, limit=1000)
        start_payload = self._latest_document_analyst_start_payload(chronology)
        if start_payload is None:
            raise ValueError('Kein gestarteter Document-Analyst-Runtimepfad fuer diesen Fall vorhanden.')

        start_record = TelegramDocumentAnalystStartRecord.model_validate(start_payload)
        if start_record.analysis_start_status != 'DOCUMENT_ANALYST_RUNTIME_STARTED':
            raise ValueError('Document-Analyst-Runtime wurde fuer diesen Fall noch nicht erfolgreich gestartet.')

        review_payload = self._latest_document_analyst_review_payload(chronology)
        document_analysis_payload = self._latest_document_analysis_payload(chronology)

        current_review: TelegramDocumentAnalystReviewRecord | None = None
        if review_payload is not None:
            current_review = TelegramDocumentAnalystReviewRecord.model_validate(review_payload)
            if current_review.review_status in {
                'DOCUMENT_ANALYST_REVIEW_COMPLETED',
                'DOCUMENT_ANALYST_REVIEW_STILL_OPEN',
            }:
                raise ValueError('Document-Analyst-Review fuer diesen Fall wurde bereits abgeschlossen.')
        else:
            current_review = await self.mark_ready_from_start(
                start_record,
                document_analysis_payload=document_analysis_payload,
            )

        resolved = current_review.model_copy(
            update={
                'review_status': 'DOCUMENT_ANALYST_REVIEW_COMPLETED' if decision == 'COMPLETED' else 'DOCUMENT_ANALYST_REVIEW_STILL_OPEN',
                'review_outcome': self._review_outcome(decision, start_record.runtime_output_status),
                'review_guidance': self._review_guidance(decision, document_analysis_payload),
                'actor': reviewed_by,
                'note': note or None,
                'updated_at': datetime.utcnow(),
            }
        )
        await self._log_review_record(resolved)

        if decision == 'COMPLETED' and start_record.runtime_open_item_id:
            await self.open_items_service.update_status(start_record.runtime_open_item_id, 'COMPLETED')
        if decision == 'STILL_OPEN':
            await self.followup_service.mark_required_from_review(resolved, source=source)

        return resolved

    def _build_ready_record(
        self,
        start_record: TelegramDocumentAnalystStartRecord,
        document_analysis_payload: dict[str, Any] | None,
    ) -> TelegramDocumentAnalystReviewRecord:
        return TelegramDocumentAnalystReviewRecord(
            review_ref=f'doc-review:{start_record.start_ref}',
            document_analyst_start_ref=start_record.start_ref,
            document_analyst_context_ref=start_record.document_analyst_context_ref,
            source_case_id=start_record.source_case_id,
            target_case_id=start_record.target_case_id,
            telegram_document_ref=start_record.telegram_document_ref,
            telegram_media_ref=start_record.telegram_media_ref,
            document_intake_ref=start_record.document_intake_ref,
            runtime_case_id=start_record.runtime_case_id or start_record.target_case_id,
            runtime_output_status=start_record.runtime_output_status,
            runtime_open_item_id=start_record.runtime_open_item_id,
            runtime_problem_id=start_record.runtime_problem_id,
            runtime_decision=(document_analysis_payload or {}).get('global_decision'),
            runtime_next_step=(document_analysis_payload or {}).get('recommended_next_step'),
            review_status='DOCUMENT_ANALYST_REVIEW_READY',
            review_guidance=self._review_guidance('READY', document_analysis_payload),
            no_further_telegram_action=True,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )

    @staticmethod
    def _review_outcome(decision: str, runtime_output_status: str | None) -> str:
        if decision == 'COMPLETED':
            return 'OUTPUT_ACCEPTED'
        if runtime_output_status == 'INCOMPLETE':
            return 'OUTPUT_INCOMPLETE'
        return 'OUTPUT_NEEDS_MANUAL_FOLLOWUP'

    @staticmethod
    def _review_guidance(decision: str, document_analysis_payload: dict[str, Any] | None) -> str:
        next_step = (document_analysis_payload or {}).get('recommended_next_step') or '-'
        if decision == 'COMPLETED':
            return 'Analyse fuer diesen Schritt gesichtet. Kein weiterer Telegram-spezifischer Handgriff noetig.'
        if decision == 'READY':
            return f'Runtime-Output jetzt operatorisch pruefen. Naechster konservativer Schritt: {next_step}.'
        return f'Runtime-Output bleibt offen. Menschliche Nachbearbeitung gemass {next_step} fortsetzen.'

    async def _log_review_record(self, record: TelegramDocumentAnalystReviewRecord) -> None:
        payload = record.model_dump(mode='json')
        await self._log_review_event(record.source_case_id, record.review_status, payload)
        if record.target_case_id != record.source_case_id:
            await self._log_review_event(record.target_case_id, record.review_status, payload)

    async def _log_review_event(self, case_id: str, action: str, payload: dict[str, Any]) -> None:
        await self.audit_service.log_event(
            {
                'event_id': str(uuid.uuid4()),
                'case_id': case_id,
                'source': 'telegram',
                'document_ref': payload.get('telegram_document_ref'),
                'agent_name': 'document-analyst',
                'approval_status': 'NOT_REQUIRED',
                'action': action,
                'result': payload.get('review_ref') or action,
                'llm_output': payload,
            }
        )

    @staticmethod
    def _latest_document_analyst_start_payload(events: list[Any]) -> dict[str, Any] | None:
        for event in reversed(events):
            if getattr(event, 'action', None) not in {
                'DOCUMENT_ANALYST_START_READY',
                'DOCUMENT_ANALYST_START_REQUESTED',
                'DOCUMENT_ANALYST_RUNTIME_STARTED',
                'DOCUMENT_ANALYST_RUNTIME_FAILED',
            }:
                continue
            payload = TelegramDocumentAnalystReviewService._normalize_payload(getattr(event, 'llm_output', None))
            if isinstance(payload, dict):
                return payload
        return None

    @staticmethod
    def _latest_document_analyst_review_payload(events: list[Any]) -> dict[str, Any] | None:
        for event in reversed(events):
            if getattr(event, 'action', None) not in {
                'DOCUMENT_ANALYST_REVIEW_READY',
                'DOCUMENT_ANALYST_REVIEW_COMPLETED',
                'DOCUMENT_ANALYST_REVIEW_STILL_OPEN',
            }:
                continue
            payload = TelegramDocumentAnalystReviewService._normalize_payload(getattr(event, 'llm_output', None))
            if isinstance(payload, dict):
                return payload
        return None

    @staticmethod
    def _latest_document_analysis_payload(events: list[Any]) -> dict[str, Any] | None:
        for event in reversed(events):
            if getattr(event, 'action', None) != 'DOCUMENT_ANALYSIS_COMPLETED':
                continue
            payload = TelegramDocumentAnalystReviewService._normalize_payload(getattr(event, 'llm_output', None))
            if isinstance(payload, dict):
                return payload
        return None

    @staticmethod
    def _normalize_payload(payload: Any) -> Any:
        if payload is None or isinstance(payload, (dict, list, int, float, bool)):
            return payload
        if isinstance(payload, str):
            raw = payload.strip()
            if raw.startswith('{') or raw.startswith('['):
                try:
                    return json.loads(raw)
                except json.JSONDecodeError:
                    return payload
            return payload
        if hasattr(payload, 'model_dump'):
            return payload.model_dump(mode='json')
        return payload
