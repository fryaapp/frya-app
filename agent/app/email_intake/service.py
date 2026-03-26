from __future__ import annotations

import hashlib
import hmac
import logging
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from app.audit.service import AuditService
from app.email_intake.analyst_bridge import EmailAnalystBridge
from app.email_intake.models import EmailAttachmentRecord, EmailIntakeRecord
from app.email_intake.repository import EmailIntakeRepository
from app.memory.file_store import FileStore
from app.open_items.service import OpenItemsService

logger = logging.getLogger(__name__)

_ALLOWED_MIME = {
    'application/pdf',
    'image/jpeg',
    'image/png',
    'image/tiff',
    'image/webp',
}
_ALLOWED_EXT = {'.pdf', '.jpg', '.jpeg', '.png', '.tiff', '.tif', '.webp'}


def _is_document_attachment(file_name: str | None, mime_type: str | None) -> bool:
    mime = (mime_type or '').lower()
    if mime in _ALLOWED_MIME:
        return True
    ext = Path(file_name or '').suffix.lower()
    return ext in _ALLOWED_EXT


def _safe_file_name(name: str | None) -> str:
    raw = Path(name or '').name.strip()
    if not raw:
        return 'attachment.bin'
    safe = ''.join(ch if ch.isalnum() or ch in {'-', '_', '.'} else '_' for ch in raw)
    return safe[:120]


class EmailIntakeService:
    def __init__(
        self,
        repository: EmailIntakeRepository,
        audit_service: AuditService,
        open_items_service: OpenItemsService,
        file_store: FileStore,
        mailgun_signing_key: str,
    ) -> None:
        self.repository = repository
        self.audit_service = audit_service
        self.open_items_service = open_items_service
        self.file_store = file_store
        self.mailgun_signing_key = mailgun_signing_key
        self._bridge = EmailAnalystBridge(audit_service, open_items_service)

    def verify_mailgun_signature(
        self, timestamp: str, token: str, signature: str
    ) -> bool:
        if not self.mailgun_signing_key:
            return False
        h = hmac.new(
            self.mailgun_signing_key.encode('utf-8'),
            f'{timestamp}{token}'.encode('utf-8'),
            hashlib.sha256,
        )
        return hmac.compare_digest(h.hexdigest(), signature)

    async def handle_webhook(
        self,
        *,
        timestamp: str,
        token: str,
        signature: str,
        sender: str,
        recipient: str | None,
        subject: str | None,
        body_plain: str | None,
        message_id: str | None,
        attachments: list[dict],  # [{'file_name', 'mime_type', 'content': bytes}]
    ) -> EmailIntakeRecord:
        if not self.verify_mailgun_signature(timestamp, token, signature):
            raise ValueError('Ungueltige Mailgun-Signatur.')

        if message_id and await self.repository.message_id_exists(message_id):
            # Duplicate — find and return existing
            existing_list = await self.repository.list_recent(limit=200)
            for e in existing_list:
                if e.message_id == message_id:
                    return e
            raise ValueError('Duplikat-Mail erkannt, aber Eintrag nicht auffindbar.')

        email_intake_id = 'email-' + uuid.uuid4().hex[:16]
        now = datetime.utcnow()

        sender_name = None
        sender_email = sender.strip()
        if '<' in sender:
            parts = sender.rsplit('<', 1)
            sender_name = parts[0].strip().strip('"')
            sender_email = parts[1].strip().rstrip('>')

        record = EmailIntakeRecord(
            email_intake_id=email_intake_id,
            received_at=now,
            sender_email=sender_email,
            sender_name=sender_name,
            recipient_email=recipient,
            subject=subject,
            body_plain=(body_plain or '')[:2000] if body_plain else None,
            message_id=message_id,
            intake_status='RECEIVED',
            attachment_count=len(attachments),
            created_at=now,
            updated_at=now,
        )
        await self.repository.create_intake(record)

        await self.audit_service.log_event({
            'event_id': str(uuid.uuid4()),
            'case_id': email_intake_id,
            'source': 'email',
            'agent_name': 'frya-orchestrator',
            'approval_status': 'NOT_REQUIRED',
            'action': 'EMAIL_INTAKE_RECEIVED',
            'result': email_intake_id,
            'llm_output': {
                'email_intake_id': email_intake_id,
                'sender_email': sender_email,
                'sender_name': sender_name,
                'subject': subject,
                'attachment_count': len(attachments),
                'message_id': message_id,
            },
        })

        document_attachments: list[tuple[int, EmailAttachmentRecord]] = []

        for idx, att in enumerate(attachments):
            att_id = 'att-' + uuid.uuid4().hex[:16]
            file_name = att.get('file_name')
            mime_type = att.get('mime_type')
            content: bytes = att.get('content', b'')
            safe_name = _safe_file_name(file_name)
            ext = Path(safe_name).suffix.lower()
            if not ext:
                ext = '.bin'
                safe_name = f'{safe_name}{ext}'

            folder = now.strftime('email/attachments/%Y/%m/%d')
            rel_path = os.path.join(folder, email_intake_id, f'{att_id}_{safe_name}').replace('\\', '/')
            self.file_store.write_bytes(rel_path, content)
            sha256 = hashlib.sha256(content).hexdigest()

            att_record = EmailAttachmentRecord(
                attachment_id=att_id,
                email_intake_id=email_intake_id,
                file_name=file_name or safe_name,
                mime_type=mime_type,
                file_size=len(content),
                storage_path=rel_path,
                sha256=sha256,
                created_at=now,
            )
            await self.repository.add_attachment(att_record)

            if _is_document_attachment(file_name, mime_type):
                document_attachments.append((idx, att_record))

        if document_attachments:
            await self.repository.update_status(email_intake_id, 'PROCESSING')
            record = record.model_copy(update={'intake_status': 'PROCESSING'})
            for att_idx, (orig_idx, att_record) in enumerate(document_attachments):
                try:
                    context = await self._bridge.create_context_from_attachment(
                        intake=record,
                        attachment=att_record,
                        attachment_index=att_idx,
                    )
                    await self.repository.update_attachment_analyst(
                        att_record.attachment_id,
                        context.source_case_id,
                        context.analyst_context_ref,
                    )
                except Exception as exc:
                    logger.warning(
                        'Email analyst bridge failed for %s att %s: %s',
                        email_intake_id, att_record.attachment_id, exc,
                    )

        return record

    async def forward_to_analyst_manually(
        self,
        email_intake_id: str,
        *,
        actor: str,
    ) -> list[Any]:
        from app.telegram.models import TelegramDocumentAnalystContextRecord  # local to avoid circulars
        record = await self.repository.get_by_id(email_intake_id)
        if record is None:
            raise ValueError(f'E-Mail-Eingang {email_intake_id} nicht gefunden.')

        attachments = await self.repository.get_attachments(email_intake_id)
        doc_atts = [
            (idx, att) for idx, att in enumerate(attachments)
            if _is_document_attachment(att.file_name, att.mime_type)
        ]
        if not doc_atts:
            raise ValueError('Keine Dokument-Anhaenge in dieser Mail fuer Analyst-Weitergabe vorhanden.')

        results: list[TelegramDocumentAnalystContextRecord] = []
        for att_idx, (orig_idx, att) in enumerate(doc_atts):
            if att.analyst_case_id:
                continue
            context = await self._bridge.create_context_from_attachment(
                intake=record,
                attachment=att,
                attachment_index=att_idx,
            )
            await self.repository.update_attachment_analyst(
                att.attachment_id,
                context.source_case_id,
                context.analyst_context_ref,
            )
            results.append(context)

        if results:
            await self.repository.update_status(email_intake_id, 'PROCESSING')

        return results
