from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from app.audit.service import AuditService
from app.open_items.service import OpenItemsService
from app.telegram.models import (
    TelegramDocumentAnalystDeepPathRecord,
    TelegramDocumentAnalystReviewRecord,
)


class TelegramDocumentAnalystDeepPathService:
    def __init__(
        self,
        audit_service: AuditService,
        open_items_service: OpenItemsService,
    ) -> None:
        self.audit_service = audit_service
        self.open_items_service = open_items_service

    async def process_after_review(
        self,
        review_record: TelegramDocumentAnalystReviewRecord,
        *,
        document_analysis_payload: dict[str, Any] | None,
    ) -> TelegramDocumentAnalystDeepPathRecord:
        """Automatically called after REVIEW_COMPLETED. Always PROPOSE_ONLY — never auto-booking."""
        deep_path_ref = 'doc-deep-path:' + uuid.uuid4().hex[:12]

        doc_type: str | None = None
        sender_value: str | None = None
        amount_value: Any = None
        currency_value: str | None = None

        if document_analysis_payload:
            doc_type = (document_analysis_payload.get('document_type') or {}).get('value')
            sender_value = (document_analysis_payload.get('sender') or {}).get('value')
            amounts = document_analysis_payload.get('amounts') or []
            if amounts and isinstance(amounts[0], dict):
                amount_value = amounts[0].get('amount')
                currency_value = amounts[0].get('currency')
            currency_raw = (document_analysis_payload.get('currency') or {}).get('value')
            if currency_raw:
                currency_value = currency_raw

        can_propose = bool(doc_type == 'INVOICE' and sender_value and amount_value is not None)

        ready = TelegramDocumentAnalystDeepPathRecord(
            deep_path_ref=deep_path_ref,
            review_ref=review_record.review_ref,
            source_case_id=review_record.source_case_id,
            target_case_id=review_record.target_case_id,
            telegram_document_ref=review_record.telegram_document_ref,
            deep_path_status='DOCUMENT_ANALYST_DEEP_PATH_READY',
            propose_only=True,
            document_type=doc_type,
        )
        await self._log_record(ready)

        if can_propose:
            booking_proposal = {
                'propose_only': True,
                'document_type': doc_type,
                'sender': sender_value,
                'amount': str(amount_value),
                'currency': currency_value or 'EUR',
                'document_ref': review_record.telegram_document_ref,
                'case_id': review_record.runtime_case_id,
            }
            open_item = await self.open_items_service.create_item(
                case_id=review_record.source_case_id,
                title='Buchungsvorschlag pruefen',
                description=(
                    f'PROPOSE_ONLY: Lieferant={sender_value}, '
                    f'Betrag={amount_value} {currency_value or "EUR"}. '
                    f'Bitte Buchungsvorschlag pruefen und bestaetigen.'
                ),
                source='document-analyst-deep-path',
                document_ref=review_record.telegram_document_ref,
            )
            triggered = ready.model_copy(
                update={
                    'deep_path_status': 'DOCUMENT_ANALYST_DEEP_PATH_TRIGGERED',
                    'booking_proposal': booking_proposal,
                    'booking_open_item_id': open_item.item_id,
                    'updated_at': datetime.utcnow(),
                }
            )
            await self._log_record(triggered)
            completed = triggered.model_copy(
                update={
                    'deep_path_status': 'DOCUMENT_ANALYST_DEEP_PATH_COMPLETED',
                    'note': (
                        f'Buchungsvorschlag erstellt fuer {sender_value} / '
                        f'{amount_value} {currency_value or "EUR"}.'
                    ),
                    'updated_at': datetime.utcnow(),
                }
            )
        else:
            completed = ready.model_copy(
                update={
                    'deep_path_status': 'DOCUMENT_ANALYST_DEEP_PATH_COMPLETED',
                    'note': 'Kein Auto-Vorschlag moeglich. Dokumenttyp oder Felder unvollstaendig.',
                    'updated_at': datetime.utcnow(),
                }
            )

        await self._log_record(completed)
        return completed

    async def _log_record(self, record: TelegramDocumentAnalystDeepPathRecord) -> None:
        payload = record.model_dump(mode='json')
        await self.audit_service.log_event({
            'event_id': str(uuid.uuid4()),
            'case_id': record.source_case_id,
            'source': 'telegram',
            'document_ref': record.telegram_document_ref,
            'agent_name': 'document-analyst',
            'approval_status': 'NOT_REQUIRED',
            'action': record.deep_path_status,
            'result': record.deep_path_ref,
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
                'action': record.deep_path_status,
                'result': record.deep_path_ref,
                'llm_output': payload,
            })
