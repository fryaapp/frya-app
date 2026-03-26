from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from app.audit.service import AuditService
from app.email_intake.models import EmailAttachmentRecord, EmailIntakeRecord
from app.open_items.service import OpenItemsService
from app.telegram.models import TelegramDocumentAnalystContextRecord, TelegramDocumentAnalystStartRecord


class EmailAnalystBridge:
    """Creates Document Analyst context records from email attachments."""

    def __init__(
        self,
        audit_service: AuditService,
        open_items_service: OpenItemsService,
    ) -> None:
        self.audit_service = audit_service
        self.open_items_service = open_items_service

    async def create_context_from_attachment(
        self,
        intake: EmailIntakeRecord,
        attachment: EmailAttachmentRecord,
        attachment_index: int,
    ) -> TelegramDocumentAnalystContextRecord:
        case_id = f'email-{intake.email_intake_id}-{attachment_index}'
        context_ref = f'doc-ctx:{case_id}:{attachment.attachment_id}'
        document_ref = f'email-att:{attachment.attachment_id}'
        confidence: str = 'MEDIUM' if intake.user_ref else 'LOW'
        context_reason = (
            'known_sender_email_match'
            if intake.user_ref
            else 'unknown_sender_no_user_ref'
        )

        ready = TelegramDocumentAnalystContextRecord(
            analyst_context_ref=context_ref,
            source_case_id=case_id,
            target_case_id=case_id,
            telegram_document_ref=document_ref,
            telegram_media_ref=attachment.attachment_id,
            media_domain='DOCUMENT',
            telegram_chat_ref=f'email:{intake.sender_email}',
            telegram_message_ref=f'email:{intake.email_intake_id}',
            telegram_thread_ref=f'email:{intake.email_intake_id}',
            document_intake_ref=attachment.attachment_id,
            document_intake_status='DOCUMENT_INBOX_ACCEPTED',
            analyst_context_status='DOCUMENT_ANALYST_CONTEXT_READY',
            document_context_link_confidence=confidence,
            document_context_link_reason=context_reason,
            operator_confirmation_required=True,
            source_channel='EMAIL',
            storage_path=attachment.storage_path,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        await self._log_context_event(case_id, 'DOCUMENT_ANALYST_CONTEXT_READY', ready)

        open_item = await self.open_items_service.create_item(
            case_id=case_id,
            title='E-Mail-Dokument pruefen und Analyst starten',
            description=(
                f'E-Mail-Anhang konservativ fuer Document-Analyst-Kontext vorbereitet.\n'
                f'Absender: {intake.sender_email}\n'
                f'Betreff: {intake.subject or "-"}\n'
                f'Datei: {attachment.file_name or "-"}\n'
                f'MIME: {attachment.mime_type or "-"}\n'
                f'Speicherpfad: {attachment.storage_path or "-"}\n'
                f'Konfidenz: {confidence}\n'
                f'Kein automatischer Analyst-Start. Operatorische Bestaetigung erforderlich.'
            ),
            source='email_intake',
            document_ref=document_ref,
        )

        final = ready.model_copy(
            update={
                'analyst_context_status': 'DOCUMENT_ANALYST_PENDING',
                'analyst_context_open_item_id': open_item.item_id,
                'analyst_context_open_item_title': open_item.title,
                'updated_at': datetime.utcnow(),
            }
        )
        await self._log_context_event(case_id, 'DOCUMENT_ANALYST_PENDING', final)

        start_record = TelegramDocumentAnalystStartRecord(
            start_ref=f'doc-start:{context_ref}',
            document_analyst_context_ref=context_ref,
            source_case_id=case_id,
            target_case_id=case_id,
            telegram_document_ref=document_ref,
            telegram_media_ref=attachment.attachment_id,
            media_domain='DOCUMENT',
            document_intake_ref=attachment.attachment_id,
            analysis_start_status='DOCUMENT_ANALYST_START_READY',
            analysis_start_confidence=confidence,
            analysis_start_reason='email_document_ready_for_operator_start',
            analysis_start_requires_operator=True,
            trigger='email_intake_context_prepared',
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        await self._log_start_event(case_id, start_record)

        await self.audit_service.log_event({
            'event_id': str(uuid.uuid4()),
            'case_id': case_id,
            'source': 'email',
            'document_ref': document_ref,
            'agent_name': 'document-analyst',
            'approval_status': 'NOT_REQUIRED',
            'action': 'EMAIL_DOCUMENT_ANALYST_CONTEXT_CREATED',
            'result': context_ref,
            'llm_output': {
                'email_intake_id': intake.email_intake_id,
                'attachment_id': attachment.attachment_id,
                'sender_email': intake.sender_email,
                'source_channel': 'EMAIL',
                'context_ref': context_ref,
                'case_id': case_id,
                'confidence': confidence,
            },
        })

        return final

    async def _log_context_event(
        self,
        case_id: str,
        action: str,
        record: TelegramDocumentAnalystContextRecord,
    ) -> None:
        await self.audit_service.log_event({
            'event_id': str(uuid.uuid4()),
            'case_id': case_id,
            'source': 'email',
            'document_ref': record.telegram_document_ref,
            'agent_name': 'document-analyst',
            'approval_status': 'NOT_REQUIRED',
            'action': action,
            'result': record.analyst_context_ref,
            'llm_output': record.model_dump(mode='json'),
        })

    async def _log_start_event(
        self,
        case_id: str,
        record: TelegramDocumentAnalystStartRecord,
    ) -> None:
        await self.audit_service.log_event({
            'event_id': str(uuid.uuid4()),
            'case_id': case_id,
            'source': 'email',
            'document_ref': record.telegram_document_ref,
            'agent_name': 'document-analyst',
            'approval_status': 'NOT_REQUIRED',
            'action': record.analysis_start_status,
            'result': record.start_ref,
            'llm_output': record.model_dump(mode='json'),
        })
