from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any

from app.audit.service import AuditService
from app.open_items.service import OpenItemsService
from app.telegram.models import (
    TelegramDocumentAnalystOcrRecheckRecord,
    TelegramDocumentAnalystReviewRecord,
)


def _normalize(payload: Any) -> Any:
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


class TelegramDocumentAnalystOcrRecheckService:
    def __init__(
        self,
        audit_service: AuditService,
        open_items_service: OpenItemsService,
    ) -> None:
        self.audit_service = audit_service
        self.open_items_service = open_items_service

    async def request_recheck(
        self,
        case_id: str,
        *,
        actor: str,
        note: str | None,
        graph: Any,
    ) -> TelegramDocumentAnalystOcrRecheckRecord:
        chronology = await self.audit_service.by_case(case_id, limit=1000)

        # Guard: must be REVIEW_STILL_OPEN with review_outcome=OUTPUT_INCOMPLETE
        review_payload = self._latest_review_payload(chronology)
        if review_payload is None:
            raise ValueError('Kein Document-Analyst-Review fuer diesen Fall vorhanden.')
        review = TelegramDocumentAnalystReviewRecord.model_validate(review_payload)
        if review.review_status != 'DOCUMENT_ANALYST_REVIEW_STILL_OPEN':
            raise ValueError('OCR-Recheck ist nur nach REVIEW_STILL_OPEN erlaubt.')
        if review.review_outcome != 'OUTPUT_INCOMPLETE':
            raise ValueError('OCR-Recheck ist nur bei review_outcome=OUTPUT_INCOMPLETE erlaubt.')

        # Doppelstart-Sperre
        existing_payload = self._latest_ocr_recheck_payload(chronology)
        if existing_payload is not None:
            existing = TelegramDocumentAnalystOcrRecheckRecord.model_validate(existing_payload)
            if existing.ocr_recheck_status in {
                'DOCUMENT_ANALYST_OCR_RECHECK_REQUESTED',
                'DOCUMENT_ANALYST_OCR_RECHECK_RUNNING',
            }:
                raise ValueError('OCR-Recheck fuer diesen Fall wurde bereits ausgeloest.')

        start_payload = self._latest_start_payload(chronology)

        recheck_ref = 'doc-ocr-recheck:' + uuid.uuid4().hex[:12]
        requested = TelegramDocumentAnalystOcrRecheckRecord(
            ocr_recheck_ref=recheck_ref,
            review_ref=review.review_ref,
            source_case_id=review.source_case_id,
            target_case_id=review.target_case_id,
            telegram_document_ref=review.telegram_document_ref,
            ocr_recheck_status='DOCUMENT_ANALYST_OCR_RECHECK_REQUESTED',
            force_ocr=True,
            actor=actor,
            note=note,
        )
        await self._log_record(requested)

        # Build graph state with force_ocr flag
        base_metadata: dict = {}
        if start_payload is not None:
            raw_meta = start_payload.get('paperless_metadata')
            if isinstance(raw_meta, dict):
                base_metadata = raw_meta

        from app.case_engine.tenant_resolver import resolve_tenant_id as _resolve_tenant
        _tenant_id = await _resolve_tenant()
        graph_state = {
            'case_id': review.runtime_case_id,
            'source': 'document_analyst_ocr_recheck',
            'tenant_id': _tenant_id,
            'message': review.telegram_document_ref,
            'document_ref': review.telegram_document_ref,
            'paperless_metadata': {**base_metadata, 'force_ocr': True, 'deskew': True},
            'ocr_text': None,
            'preview_text': review.telegram_document_ref,
            'force_ocr': True,
        }

        running = requested.model_copy(
            update={
                'ocr_recheck_status': 'DOCUMENT_ANALYST_OCR_RECHECK_RUNNING',
                'updated_at': datetime.utcnow(),
            }
        )
        await self._log_record(running)

        try:
            result = await graph.ainvoke(graph_state)
        except Exception as exc:
            failed = running.model_copy(
                update={
                    'ocr_recheck_status': 'DOCUMENT_ANALYST_OCR_RECHECK_FAILED',
                    'error': str(exc),
                    'updated_at': datetime.utcnow(),
                }
            )
            await self._log_record(failed)
            raise ValueError(f'OCR-Recheck konnte nicht ausgefuehrt werden: {exc}') from exc

        output = result.get('output', {}) if isinstance(result, dict) else {}
        output_status = str(output.get('status') or '') or None
        open_item_id = str(output.get('open_item_id') or '') or None

        if output_status == 'INCOMPLETE':
            fail_item = await self.open_items_service.create_item(
                case_id=review.source_case_id,
                title='Manuelle Nachbearbeitung erforderlich (OCR)',
                description=(
                    'OCR-Recheck lieferte weiterhin unvollstaendigen Output. '
                    'Manuelle Nachbearbeitung notwendig.'
                ),
                source='document-analyst-ocr-recheck',
            )
            final = running.model_copy(
                update={
                    'ocr_recheck_status': 'DOCUMENT_ANALYST_OCR_RECHECK_FAILED',
                    'recheck_output_status': output_status,
                    'recheck_open_item_id': fail_item.item_id,
                    'updated_at': datetime.utcnow(),
                }
            )
        else:
            final = running.model_copy(
                update={
                    'ocr_recheck_status': 'DOCUMENT_ANALYST_OCR_RECHECK_COMPLETED',
                    'recheck_output_status': output_status,
                    'recheck_open_item_id': open_item_id,
                    'updated_at': datetime.utcnow(),
                }
            )

        await self._log_record(final)
        return final

    async def _log_record(self, record: TelegramDocumentAnalystOcrRecheckRecord) -> None:
        payload = record.model_dump(mode='json')
        await self.audit_service.log_event({
            'event_id': str(uuid.uuid4()),
            'case_id': record.source_case_id,
            'source': 'telegram',
            'document_ref': record.telegram_document_ref,
            'agent_name': 'document-analyst',
            'approval_status': 'NOT_REQUIRED',
            'action': record.ocr_recheck_status,
            'result': record.ocr_recheck_ref,
            'llm_output': payload,
        })
        if record.target_case_id != record.source_case_id:
            await self.audit_service.log_event({
                'event_id': str(uuid.uuid4()),
                'case_id': record.target_case_id,
                'source': 'telegram',
                'document_ref': record.telegram_document_ref,
                'agent_name': 'document-analyst',
                'approval_status': 'NOT_REQUIRED',
                'action': record.ocr_recheck_status,
                'result': record.ocr_recheck_ref,
                'llm_output': payload,
            })

    @staticmethod
    def _latest_review_payload(events: list[Any]) -> dict[str, Any] | None:
        for event in reversed(events):
            if getattr(event, 'action', None) not in {
                'DOCUMENT_ANALYST_REVIEW_READY',
                'DOCUMENT_ANALYST_REVIEW_COMPLETED',
                'DOCUMENT_ANALYST_REVIEW_STILL_OPEN',
            }:
                continue
            payload = _normalize(getattr(event, 'llm_output', None))
            if isinstance(payload, dict):
                return payload
        return None

    @staticmethod
    def _latest_start_payload(events: list[Any]) -> dict[str, Any] | None:
        for event in reversed(events):
            if getattr(event, 'action', None) not in {
                'DOCUMENT_ANALYST_START_READY',
                'DOCUMENT_ANALYST_START_REQUESTED',
                'DOCUMENT_ANALYST_RUNTIME_STARTED',
            }:
                continue
            payload = _normalize(getattr(event, 'llm_output', None))
            if isinstance(payload, dict):
                return payload
        return None

    @staticmethod
    def _latest_ocr_recheck_payload(events: list[Any]) -> dict[str, Any] | None:
        for event in reversed(events):
            if getattr(event, 'action', None) not in {
                'DOCUMENT_ANALYST_OCR_RECHECK_REQUESTED',
                'DOCUMENT_ANALYST_OCR_RECHECK_RUNNING',
                'DOCUMENT_ANALYST_OCR_RECHECK_COMPLETED',
                'DOCUMENT_ANALYST_OCR_RECHECK_FAILED',
            }:
                continue
            payload = _normalize(getattr(event, 'llm_output', None))
            if isinstance(payload, dict):
                return payload
        return None
