import json
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from app.audit.service import AuditService
from app.open_items.service import OpenItemsService
from app.telegram.document_analyst_review_service import TelegramDocumentAnalystReviewService
from app.telegram.models import TelegramDocumentAnalystContextRecord, TelegramDocumentAnalystStartRecord

if TYPE_CHECKING:
    from app.telegram.document_analyst_merge_service import TelegramDocumentAnalystMergeService


class TelegramDocumentAnalystStartService:
    def __init__(
        self,
        audit_service: AuditService,
        open_items_service: OpenItemsService,
        review_service: TelegramDocumentAnalystReviewService,
        merge_service: 'TelegramDocumentAnalystMergeService | None' = None,
    ) -> None:
        self.audit_service = audit_service
        self.open_items_service = open_items_service
        self.review_service = review_service
        self.merge_service = merge_service

    async def start_runtime(
        self,
        case_id: str,
        *,
        actor: str,
        note: str | None,
        trigger: str,
        graph: Any,
    ) -> TelegramDocumentAnalystStartRecord:
        chronology = await self.audit_service.by_case(case_id, limit=1000)
        context_payload = self._latest_document_analyst_context_payload(chronology)
        if context_payload is None:
            raise ValueError('Kein Document-Analyst-Kontext fuer diesen Fall vorhanden.')

        context = TelegramDocumentAnalystContextRecord.model_validate(context_payload)
        source_case_id = context.source_case_id
        target_case_id = context.target_case_id
        source_chronology = chronology if source_case_id == case_id else await self.audit_service.by_case(source_case_id, limit=1000)
        target_chronology = chronology if target_case_id == case_id else await self.audit_service.by_case(target_case_id, limit=1000)

        start_payload = self._latest_document_analyst_start_payload(chronology)
        if start_payload is None and target_case_id != case_id:
            start_payload = self._latest_document_analyst_start_payload(target_chronology)
        if start_payload is None and source_case_id != case_id:
            start_payload = self._latest_document_analyst_start_payload(source_chronology)
        if start_payload is not None:
            existing = TelegramDocumentAnalystStartRecord.model_validate(start_payload)
            if existing.analysis_start_status in {
                'DOCUMENT_ANALYST_START_REQUESTED',
                'DOCUMENT_ANALYST_RUNTIME_STARTED',
            }:
                raise ValueError('Document-Analyst-Start fuer diesen Kontext wurde bereits ausgelost.')

        media_payload = self._latest_telegram_media_payload(source_chronology)
        if media_payload is None:
            raise ValueError('Kein gespeichertes Telegram-Dokument fuer den Document-Analyst-Start gefunden.')
        if media_payload.get('storage_status') != 'STORED':
            raise ValueError('Telegram-Dokument ist noch nicht sicher gespeichert.')

        ready_record = self._build_start_record(
            context=context,
            media_payload=media_payload,
            status='DOCUMENT_ANALYST_START_READY',
            actor=None,
            note=None,
            trigger='context_prepared',
        )
        if start_payload is None:
            await self._log_start_record(ready_record)

        requested_record = ready_record.model_copy(
            update={
                'analysis_start_status': 'DOCUMENT_ANALYST_START_REQUESTED',
                'actor': actor,
                'note': note or None,
                'trigger': trigger,
                'updated_at': datetime.utcnow(),
            }
        )
        await self._log_start_record(requested_record)

        runtime_case_id = context.target_case_id
        from app.case_engine.tenant_resolver import resolve_tenant_id as _resolve_tenant
        _tenant_id = await _resolve_tenant()
        graph_state = {
            'case_id': runtime_case_id,
            'source': 'telegram_document_analyst_start',
            'tenant_id': _tenant_id,
            'message': media_payload.get('caption_text') or media_payload.get('file_name') or context.telegram_document_ref,
            'document_ref': context.telegram_document_ref,
            'paperless_metadata': self._build_runtime_metadata(context, media_payload),
            'ocr_text': None,
            'preview_text': media_payload.get('caption_text') or media_payload.get('file_name') or context.telegram_document_ref,
        }

        try:
            result = await graph.ainvoke(graph_state)
        except Exception as exc:
            failed_record = requested_record.model_copy(
                update={
                    'analysis_start_status': 'DOCUMENT_ANALYST_RUNTIME_FAILED',
                    'runtime_case_id': runtime_case_id,
                    'runtime_error': str(exc),
                    'updated_at': datetime.utcnow(),
                }
            )
            await self._log_start_record(failed_record)
            raise ValueError(f'Document-Analyst-Runtime konnte nicht gestartet werden: {exc}') from exc

        output = result.get('output', {}) if isinstance(result, dict) else {}
        started_record = requested_record.model_copy(
            update={
                'analysis_start_status': 'DOCUMENT_ANALYST_RUNTIME_STARTED',
                'runtime_case_id': runtime_case_id,
                'runtime_output_status': str(output.get('status') or '') or None,
                'runtime_open_item_id': str(output.get('open_item_id') or '') or None,
                'runtime_problem_id': str(output.get('problem_id') or '') or None,
                'updated_at': datetime.utcnow(),
            }
        )
        await self._log_start_record(started_record)
        document_analysis_payload = result.get('document_analysis') if isinstance(result, dict) else None
        await self.review_service.mark_ready_from_start(
            started_record,
            document_analysis_payload=document_analysis_payload,
        )
        await self._complete_transition_open_items(context=context, media_payload=media_payload)

        if self.merge_service is not None:
            try:
                await self.merge_service.search_merge_candidate(
                    started_record,
                    document_analysis_payload=document_analysis_payload,
                )
            except Exception:
                pass  # Merge search is best-effort; never fail the start

        return started_record

    def build_ready_record(
        self,
        *,
        context: TelegramDocumentAnalystContextRecord,
    ) -> TelegramDocumentAnalystStartRecord:
        return self._build_start_record(
            context=context,
            media_payload={'document_intake_ref': context.document_intake_ref},
            status='DOCUMENT_ANALYST_START_READY',
            actor=None,
            note=None,
            trigger='context_prepared',
        )

    async def _complete_transition_open_items(
        self,
        *,
        context: TelegramDocumentAnalystContextRecord,
        media_payload: dict[str, Any],
    ) -> None:
        if context.analyst_context_open_item_id:
            await self.open_items_service.update_status(context.analyst_context_open_item_id, 'COMPLETED')
        media_open_item_id = media_payload.get('open_item_id')
        if isinstance(media_open_item_id, str) and media_open_item_id:
            await self.open_items_service.update_status(media_open_item_id, 'COMPLETED')

    def _build_runtime_metadata(
        self,
        context: TelegramDocumentAnalystContextRecord,
        media_payload: dict[str, Any],
    ) -> dict[str, Any]:
        file_name = media_payload.get('file_name')
        caption = media_payload.get('caption_text')
        return {
            'title': file_name or context.telegram_document_ref,
            'original_file_name': file_name,
            'filename': file_name,
            'preview': caption or file_name or context.telegram_document_ref,
            'mime_type': media_payload.get('mime_type'),
            'stored_relative_path': media_payload.get('stored_relative_path') or context.storage_path,
            'source_channel': 'telegram',
            'telegram_chat_ref': context.telegram_chat_ref,
            'telegram_message_ref': context.telegram_message_ref,
            'telegram_media_ref': context.telegram_media_ref,
            'media_domain': context.media_domain,
            'document_intake_ref': context.document_intake_ref,
            'document_context_link_reason': context.document_context_link_reason,
        }

    def _build_start_record(
        self,
        *,
        context: TelegramDocumentAnalystContextRecord,
        media_payload: dict[str, Any],
        status: str,
        actor: str | None,
        note: str | None,
        trigger: str,
    ) -> TelegramDocumentAnalystStartRecord:
        return TelegramDocumentAnalystStartRecord(
            start_ref=f'doc-start:{context.analyst_context_ref}',
            document_analyst_context_ref=context.analyst_context_ref,
            source_case_id=context.source_case_id,
            target_case_id=context.target_case_id,
            telegram_document_ref=context.telegram_document_ref,
            telegram_media_ref=context.telegram_media_ref,
            media_domain=context.media_domain,
            document_intake_ref=context.document_intake_ref or media_payload.get('document_intake_ref'),
            analysis_start_status=status,
            analysis_start_confidence=context.document_context_link_confidence,
            analysis_start_reason=self._start_reason(context),
            analysis_start_requires_operator=True,
            trigger=trigger,
            actor=actor,
            note=note,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )

    @staticmethod
    def _start_reason(context: TelegramDocumentAnalystContextRecord) -> str:
        if context.analyst_context_status == 'DOCUMENT_ANALYST_CONTEXT_ATTACHED':
            return 'linked_existing_document_context'
        if context.media_domain == 'DOCUMENT':
            return 'telegram_document_ready_for_operator_start'
        return 'telegram_media_requires_operator_confirmed_start'

    async def _log_start_record(self, record: TelegramDocumentAnalystStartRecord) -> None:
        payload = record.model_dump(mode='json')
        await self._log_start_event(record.source_case_id, record.analysis_start_status, payload)
        if record.target_case_id != record.source_case_id:
            await self._log_start_event(record.target_case_id, record.analysis_start_status, payload)

    async def _log_start_event(self, case_id: str, action: str, payload: dict[str, Any]) -> None:
        await self.audit_service.log_event(
            {
                'event_id': str(uuid.uuid4()),
                'case_id': case_id,
                'source': 'telegram',
                'document_ref': payload.get('telegram_document_ref'),
                'agent_name': 'document-analyst',
                'approval_status': 'NOT_REQUIRED',
                'action': action,
                'result': payload.get('start_ref') or action,
                'llm_output': payload,
            }
        )

    @staticmethod
    def _latest_document_analyst_context_payload(events: list[Any]) -> dict[str, Any] | None:
        for event in reversed(events):
            if getattr(event, 'action', None) not in {
                'DOCUMENT_ANALYST_CONTEXT_READY',
                'DOCUMENT_ANALYST_CONTEXT_ATTACHED',
                'DOCUMENT_ANALYST_PENDING',
            }:
                continue
            payload = TelegramDocumentAnalystStartService._normalize_payload(getattr(event, 'llm_output', None))
            if isinstance(payload, dict):
                return payload
        return None

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
            payload = TelegramDocumentAnalystStartService._normalize_payload(getattr(event, 'llm_output', None))
            if isinstance(payload, dict):
                return payload
        return None

    @staticmethod
    def _latest_telegram_media_payload(events: list[Any]) -> dict[str, Any] | None:
        for event in reversed(events):
            if getattr(event, 'action', None) not in {
                'TELEGRAM_MEDIA_STORED',
                'TELEGRAM_MEDIA_QUEUED',
                'TELEGRAM_DOCUMENT_STORED',
                'TELEGRAM_DOCUMENT_QUEUED',
                'DOCUMENT_INBOX_ACCEPTED',
                'DOCUMENT_INTAKE_LINKED',
            }:
                continue
            payload = TelegramDocumentAnalystStartService._normalize_payload(getattr(event, 'llm_output', None))
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
