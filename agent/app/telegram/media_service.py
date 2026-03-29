from __future__ import annotations

import asyncio
import hashlib
import os
import uuid
from datetime import datetime
from pathlib import Path

import logging

from app.audit.service import AuditService
from app.connectors.dms_paperless import PaperlessConnector
from app.memory.file_store import FileStore
from app.open_items.service import OpenItemsService
from app.telegram.models import (
    TelegramDocumentAnalystStartRecord,
    TelegramDocumentAnalystContextRecord,
    TelegramMediaAttachment,
    TelegramMediaIngressRecord,
    TelegramNormalizedIngressMessage,
    TelegramRoutingResult,
)
from app.connectors.notifications_telegram import TelegramConnector
from app.telegram.service import TelegramCaseLinkService

logger = logging.getLogger(__name__)


class TelegramMediaIngressService:
    def __init__(
        self,
        audit_service: AuditService,
        open_items_service: OpenItemsService,
        telegram_connector: TelegramConnector,
        telegram_case_link_service: TelegramCaseLinkService,
        file_store: FileStore,
        max_bytes: int,
        allowed_mime_types: set[str],
        allowed_extensions: set[str],
        paperless_connector: PaperlessConnector | None = None,
    ) -> None:
        self.audit_service = audit_service
        self.open_items_service = open_items_service
        self.telegram_connector = telegram_connector
        self.telegram_case_link_service = telegram_case_link_service
        self.file_store = file_store
        self.max_bytes = max_bytes
        self.allowed_mime_types = {x.lower() for x in allowed_mime_types if x}
        self.allowed_extensions = {x.lower() for x in allowed_extensions if x}
        self.paperless_connector = paperless_connector

    async def _poll_paperless_task_for_duplicate(
        self,
        paperless_task_id: str,
        chat_id: str,
        case_id: str,
        filename: str,
    ) -> None:
        """Background task: poll Paperless task status and notify user on duplicate."""
        if self.paperless_connector is None or not paperless_task_id:
            return
        try:
            # Wait for Paperless to start consuming (usually takes 5-15s)
            for _ in range(6):
                await asyncio.sleep(5)
                task_info = await self.paperless_connector.get_task_status(paperless_task_id)
                status = (task_info.get('status') or '').upper()

                if status == 'SUCCESS':
                    logger.info('Paperless task %s succeeded for %s', paperless_task_id, filename)
                    return

                if status == 'FAILURE':
                    result_text = str(task_info.get('result') or '')
                    if 'duplicate' in result_text.lower():
                        # Extract original document title from error message
                        # Format: "... It is a duplicate of {title} (#{id})."
                        original_title = result_text
                        import re
                        m = re.search(r'duplicate of (.+?) \(#(\d+)\)', result_text)
                        if m:
                            original_title = m.group(1)
                            original_id = m.group(2)
                        else:
                            original_id = None

                        dup_msg = (
                            f'FRYA: Dieses Dokument habe ich bereits.\n'
                            f'\U0001f4c4 {original_title}\n'
                        )
                        if original_id:
                            dup_msg += f'Paperless-ID: #{original_id}\n'
                        dup_msg += '\nSoll ich es trotzdem nochmal verarbeiten?'

                        keyboard = {
                            'inline_keyboard': [
                                [
                                    {'text': '\u23ed\ufe0f \u00dcberspringen', 'callback_data': f'dup_skip:{case_id}'},
                                    {'text': '\U0001f504 Trotzdem verarbeiten', 'callback_data': f'dup_force:{case_id}:{original_id or ""}'},
                                ],
                            ]
                        }

                        from app.connectors.contracts import NotificationMessage
                        await self.telegram_connector.send(
                            NotificationMessage(target=chat_id, text=dup_msg, reply_markup=keyboard)
                        )
                        logger.info('Duplicate detected for %s, notified chat %s', filename, chat_id)
                    else:
                        logger.warning('Paperless task %s failed (non-duplicate): %s', paperless_task_id, result_text)
                    return

                # PENDING or other → keep polling
        except Exception as exc:
            logger.debug('Paperless duplicate poll failed: %s', exc)

    async def handle_media_ingress(
        self,
        normalized: TelegramNormalizedIngressMessage,
        case_id: str,
        sender_label: str,
        thread_ref: str,
    ) -> tuple[TelegramRoutingResult, str, dict]:
        attachment = self._pick_attachment(normalized.media_attachments)
        if attachment is None:
            route = self._rejected_route(
                case_id=case_id,
                thread_ref=thread_ref,
                status='DOCUMENT_UNSUPPORTED',
                label='Nicht unterstuetzt',
                detail='Dieser Telegram-Medientyp wird in V1 nicht verarbeitet.',
                next_step='Nur Bild oder PDF senden.',
                attachment=attachment,
            )
            return route, 'FRYA: Dieser Telegram-Medientyp wird in V1 nicht verarbeitet. Bitte Bild oder PDF senden.', {
                'status': 'UNSUPPORTED',
                'intent': 'media.unsupported',
            }

        rejection_reason = self._validate_attachment(attachment)
        if rejection_reason is not None:
            status = self._rejected_status(attachment, rejection_reason)
            label = 'Datei zu gross' if rejection_reason == 'file_too_large' else 'Nicht unterstuetzt'
            detail = (
                'Die Datei ist zu gross fuer den sicheren Telegram-Intake.'
                if rejection_reason == 'file_too_large'
                else 'Dieser Datei- oder Medientyp wird in V1 nicht verarbeitet.'
            )
            route = self._rejected_route(
                case_id=case_id,
                thread_ref=thread_ref,
                status=status,
                label=label,
                detail=detail,
                next_step='Zulaessiges Bild oder PDF senden.',
                attachment=attachment,
            )
            record = self._base_record(normalized, case_id, thread_ref, attachment)
            record = record.model_copy(
                update={
                    'download_status': 'SKIPPED',
                    'storage_status': 'SKIPPED',
                    'document_intake_status': 'NOT_APPLICABLE',
                    'rejection_reason': rejection_reason,
                    'updated_at': datetime.utcnow(),
                }
            )
            await self._log_media_event(case_id, self._event_name(attachment, 'REJECTED'), record.model_dump(mode='json'))
            reply = (
                'FRYA: Datei zu gross. Bitte eine kleinere Datei senden.'
                if rejection_reason == 'file_too_large'
                else 'FRYA: Dieser Dateityp wird in V1 nicht verarbeitet. Bitte Bild oder PDF senden.'
            )
            return route, reply, {
                'status': rejection_reason.upper(),
                'intent': 'media.ingress',
                'media': record.model_dump(mode='json'),
            }

        record = self._base_record(normalized, case_id, thread_ref, attachment)
        await self._log_media_event(case_id, self._event_name(attachment, 'ACCEPTED'), record.model_dump(mode='json'))

        file_info = await self.telegram_connector.get_file_info(attachment.telegram_file_id)
        if not bool(file_info.get('ok', False)):
            failed = record.model_copy(
                update={
                    'download_status': 'FAILED',
                    'storage_status': 'SKIPPED',
                    'document_intake_status': 'NOT_APPLICABLE',
                    'rejection_reason': file_info.get('reason') or 'telegram_get_file_failed',
                    'updated_at': datetime.utcnow(),
                }
            )
            await self._log_media_event(case_id, self._event_name(attachment, 'DOWNLOAD_FAILED'), failed.model_dump(mode='json'))
            route = self._rejected_route(
                case_id=case_id,
                thread_ref=thread_ref,
                status=self._download_failed_status(attachment),
                label='Speicherung fehlgeschlagen',
                detail='Die Datei konnte nicht sicher von Telegram geholt werden.',
                next_step='Datei erneut senden oder intern pruefen.',
                attachment=attachment,
            )
            return route, 'FRYA: Datei erkannt, aber die sichere Speicherung ist fehlgeschlagen. Bitte spaeter erneut senden.', {
                'status': 'DOWNLOAD_FAILED',
                'intent': 'media.ingress',
                'media': failed.model_dump(mode='json'),
            }

        file_path = ((file_info.get('json') or {}).get('result') or {}).get('file_path')
        if not file_path:
            failed = record.model_copy(
                update={
                    'download_status': 'FAILED',
                    'storage_status': 'SKIPPED',
                    'document_intake_status': 'NOT_APPLICABLE',
                    'rejection_reason': 'telegram_file_path_missing',
                    'updated_at': datetime.utcnow(),
                }
            )
            await self._log_media_event(case_id, self._event_name(attachment, 'DOWNLOAD_FAILED'), failed.model_dump(mode='json'))
            route = self._rejected_route(
                case_id=case_id,
                thread_ref=thread_ref,
                status=self._download_failed_status(attachment),
                label='Speicherung fehlgeschlagen',
                detail='Telegram lieferte keinen gueltigen Dateipfad.',
                next_step='Datei erneut senden oder intern pruefen.',
                attachment=attachment,
            )
            return route, 'FRYA: Datei erkannt, aber Telegram hat keinen gueltigen Dateipfad geliefert.', {
                'status': 'DOWNLOAD_FAILED',
                'intent': 'media.ingress',
                'media': failed.model_dump(mode='json'),
            }

        download = await self.telegram_connector.download_file(file_path)
        if not bool(download.get('ok', False)):
            failed = record.model_copy(
                update={
                    'download_status': 'FAILED',
                    'storage_status': 'SKIPPED',
                    'document_intake_status': 'NOT_APPLICABLE',
                    'rejection_reason': download.get('reason') or 'telegram_file_download_failed',
                    'updated_at': datetime.utcnow(),
                }
            )
            await self._log_media_event(case_id, self._event_name(attachment, 'DOWNLOAD_FAILED'), failed.model_dump(mode='json'))
            route = self._rejected_route(
                case_id=case_id,
                thread_ref=thread_ref,
                status=self._download_failed_status(attachment),
                label='Speicherung fehlgeschlagen',
                detail='Die Datei konnte nicht sicher heruntergeladen werden.',
                next_step='Datei erneut senden oder intern pruefen.',
                attachment=attachment,
            )
            return route, 'FRYA: Datei erkannt, aber der sichere Download ist fehlgeschlagen.', {
                'status': 'DOWNLOAD_FAILED',
                'intent': 'media.ingress',
                'media': failed.model_dump(mode='json'),
            }

        content = download.get('content') or b''
        stored_relative_path = self._build_storage_path(case_id, attachment)
        self.file_store.write_bytes(stored_relative_path, content)
        sha256 = hashlib.sha256(content).hexdigest()

        stored = record.model_copy(
            update={
                'download_status': 'DOWNLOADED',
                'storage_status': 'STORED',
                'stored_relative_path': stored_relative_path,
                'sha256': sha256,
                'updated_at': datetime.utcnow(),
            }
        )
        await self._log_media_event(case_id, self._event_name(attachment, 'STORED'), stored.model_dump(mode='json'))

        # ── Upload to Paperless (Single Source of Truth) ──────────────────────
        paperless_task_id: str | None = None
        if self.paperless_connector is not None:
            # Image preprocessing: strip EXIF (GDPR), resize, wrap as PDF
            from app.preprocessing.image_processor import is_image, process_image_to_pdf

            _pl_filename = attachment.file_name or Path(stored_relative_path).name
            _pl_content = content
            if is_image(_pl_filename):
                try:
                    _pl_content, _pl_filename = process_image_to_pdf(_pl_content, _pl_filename)
                except Exception as _pp_exc:
                    logger.warning('Image preprocessing failed for %s: %s', _pl_filename, _pp_exc)
                    # Fall through with original bytes

            # Encode case_id in title so the post-consumption webhook can correlate
            _pl_title = f'frya:{case_id}:{_pl_filename}'
            try:
                _pl_result = await self.paperless_connector.upload_document(
                    _pl_content,
                    filename=_pl_filename,
                    title=_pl_title,
                )
                paperless_task_id = _pl_result.get('task_id') if isinstance(_pl_result, dict) else str(_pl_result)
                await self._log_media_event(
                    case_id,
                    self._event_name(attachment, 'UPLOADED_TO_PAPERLESS'),
                    {
                        **stored.model_dump(mode='json'),
                        'paperless_task_id': paperless_task_id,
                        'telegram_chat_id': normalized.actor.chat_id,
                    },
                )
                logger.info('Telegram file %s uploaded to Paperless, task_id=%s', attachment.file_name, paperless_task_id)
                # Fire-and-forget: poll Paperless task status and notify on duplicate
                if paperless_task_id:
                    asyncio.create_task(self._poll_paperless_task_for_duplicate(
                        paperless_task_id=paperless_task_id,
                        chat_id=normalized.actor.chat_id,
                        case_id=case_id,
                        filename=attachment.file_name or stored_relative_path,
                    ))
            except Exception as _pl_exc:
                logger.warning('Paperless upload failed for %s: %s', attachment.file_name, _pl_exc)
                await self._log_media_event(
                    case_id,
                    self._event_name(attachment, 'UPLOAD_FAILED'),
                    {**stored.model_dump(mode='json'), 'error': str(_pl_exc)},
                )
                # Return error reply so the user knows — do not continue silently
                return (
                    self._rejected_route(
                        case_id=case_id,
                        thread_ref=thread_ref,
                        status='DOCUMENT_UPLOAD_FAILED' if attachment.media_kind == 'document' else 'MEDIA_UPLOAD_FAILED',
                        label='Verarbeitung fehlgeschlagen',
                        detail='Beleg konnte nicht an das Dokumentenmanagementsystem übergeben werden.',
                        next_step='Versuch es nochmal.',
                        attachment=attachment,
                    ),
                    'FRYA: Konnte den Beleg nicht verarbeiten — versuch\'s nochmal.',
                    {'status': 'UPLOAD_FAILED', 'intent': 'media.ingress', 'error': str(_pl_exc)},
                )

        context_case_link = await self.telegram_case_link_service.latest_trackable_for_message(
            normalized,
            exclude_case_id=case_id,
        )
        linked_context_case_id = None
        linked_context_reason = None
        intake_status = 'NOT_APPLICABLE'
        if attachment.media_kind == 'document':
            intake_status = 'DOCUMENT_INTAKE_PENDING'
            if context_case_link is not None:
                linked_context_case_id = context_case_link.linked_case_id or context_case_link.case_id
                linked_context_reason = 'latest_trackable_same_thread'
                intake_status = 'DOCUMENT_INTAKE_LINKED'

        title_prefix = 'Bild' if attachment.media_kind == 'photo' else 'Dokumenteingang'
        document_ref = f'tg-media:{stored.media_ref}'
        open_item = await self.open_items_service.create_item(
            case_id=case_id,
            title=f'[Telegram] {title_prefix} pruefen: {sender_label}',
            description=(
                f'Telegram-{title_prefix.lower()} konservativ in die Operator-Queue aufgenommen.\n'
                f'Chat: {normalized.telegram_chat_ref}\n'
                f'Sender: {sender_label}\n'
                f'Datei: {attachment.file_name or "-"}\n'
                f'MIME: {attachment.mime_type or "-"}\n'
                f'Groesse: {attachment.file_size or "-"}\n'
                f'Caption: {normalized.text or "-"}\n'
                f'Speicherpfad: {stored_relative_path}\n'
                f'Dokumenten-Intake: {intake_status}\n'
                f'Kontext-Fall: {linked_context_case_id or "-"}'
            ),
            source='telegram',
            document_ref=document_ref,
        )
        queued = stored.model_copy(
            update={
                'open_item_id': open_item.item_id,
                'open_item_title': open_item.title,
                'document_ref': document_ref,
                'document_intake_ref': open_item.item_id if attachment.media_kind == 'document' else None,
                'document_intake_status': (
                    'DOCUMENT_INBOX_ACCEPTED'
                    if attachment.media_kind == 'document' and intake_status == 'DOCUMENT_INTAKE_PENDING'
                    else intake_status
                ),
                'linked_context_case_id': linked_context_case_id,
                'linked_context_reason': linked_context_reason,
                'updated_at': datetime.utcnow(),
            }
        )
        await self._log_media_event(case_id, self._event_name(attachment, 'QUEUED'), queued.model_dump(mode='json'))
        document_analyst_context = None
        document_analyst_start = None
        if attachment.media_kind == 'document':
            await self._log_media_event(case_id, 'DOCUMENT_INBOX_ACCEPTED', queued.model_dump(mode='json'))
            if linked_context_case_id is not None:
                await self._log_media_event(case_id, 'DOCUMENT_INTAKE_LINKED', queued.model_dump(mode='json'))
        document_analyst_context = await self._prepare_document_analyst_context(
            normalized=normalized,
            queued=queued,
            source_case_id=case_id,
            target_case_id=linked_context_case_id or case_id,
            attachment=attachment,
        )
        document_analyst_start = await self._prepare_document_analyst_start_ready(document_analyst_context)

        route = TelegramRoutingResult(
            case_id=case_id,
            routing_status='DOCUMENT_ACCEPTED' if attachment.media_kind == 'document' else 'MEDIA_ACCEPTED',
            intent_name='document.ingress' if attachment.media_kind == 'document' else 'media.ingress',
            ack_template='ACK_DOCUMENT_ACCEPTED' if attachment.media_kind == 'document' else 'ACK_MEDIA_ACCEPTED',
            authorization_status='AUTHORIZED',
            open_item_id=open_item.item_id,
            open_item_title=open_item.title,
            next_manual_step=(
                'Telegram-Dokument im Dokumenten-Intake pruefen.'
                if attachment.media_kind == 'document'
                else 'Telegram-Medien-Eingang in der Operator-Queue pruefen.'
            ),
            telegram_thread_ref=thread_ref,
            linked_case_id=case_id,
            linked_open_item_id=open_item.item_id,
            track_for_status=True,
            user_visible_status_code='IN_QUEUE',
            user_visible_status_label='In operatorischer Pruefung',
            user_visible_status_detail=(
                'Dein Telegram-Dokument wurde aufgenommen und dem internen Dokumenteneingang zugeordnet.'
                if attachment.media_kind == 'document'
                else 'Dein Telegram-Dokument wurde aufgenommen und wartet auf operatorische Pruefung.'
            ),
        )
        reply_text = (
            'FRYA: Dokument angenommen.\n'
            'Es wurde sicher gespeichert und dem internen Dokumenteneingang zugeordnet.\n'
            f'Ref: {case_id}'
            if attachment.media_kind == 'document'
            else
            'FRYA: Bild angenommen.\n'
            'Es wurde sicher gespeichert und fuer die interne Operator-Queue aufgenommen.\n'
            f'Ref: {case_id}'
        )
        return route, reply_text, {
            'status': queued.document_intake_status if attachment.media_kind == 'document' else 'MEDIA_QUEUED',
            'intent': 'document.ingress' if attachment.media_kind == 'document' else 'media.ingress',
            'open_item_id': open_item.item_id,
            'linked_case_id': case_id,
            'media': queued.model_dump(mode='json'),
            'document_analyst_context': (
                document_analyst_context.model_dump(mode='json')
                if document_analyst_context is not None
                else None
            ),
            'document_analyst_start': (
                document_analyst_start.model_dump(mode='json')
                if document_analyst_start is not None
                else None
            ),
            'user_visible_status': {
                'status_code': 'IN_QUEUE',
                'status_label': 'In operatorischer Pruefung',
                'status_detail': (
                    'Dein Telegram-Dokument wurde aufgenommen und dem internen Dokumenteneingang zugeordnet.'
                    if attachment.media_kind == 'document'
                    else 'Dein Telegram-Dokument wurde aufgenommen und wartet auf operatorische Pruefung.'
                ),
                'linked_case_id': case_id,
                'open_item_id': open_item.item_id,
                'open_item_title': open_item.title,
            },
        }

    async def _prepare_document_analyst_context(
        self,
        normalized: TelegramNormalizedIngressMessage,
        queued: TelegramMediaIngressRecord,
        source_case_id: str,
        target_case_id: str,
        attachment: TelegramMediaAttachment,
    ) -> TelegramDocumentAnalystContextRecord:
        context_ref = f'doc-ctx:{source_case_id}:{queued.media_ref}'
        link_confidence = 'MEDIUM' if queued.linked_context_case_id else 'LOW'
        context_reason = queued.linked_context_reason or 'no_clear_existing_context'
        ready = TelegramDocumentAnalystContextRecord(
            analyst_context_ref=context_ref,
            source_case_id=source_case_id,
            target_case_id=target_case_id,
            telegram_document_ref=queued.document_ref or f'tg-media:{queued.media_ref}',
            telegram_media_ref=queued.media_ref,
            media_domain=queued.media_domain,
            telegram_chat_ref=queued.telegram_chat_ref,
            telegram_message_ref=queued.telegram_message_ref,
            telegram_thread_ref=queued.telegram_thread_ref,
            document_intake_ref=queued.document_intake_ref,
            document_intake_status=queued.document_intake_status,
            analyst_context_status='DOCUMENT_ANALYST_CONTEXT_READY',
            document_context_link_confidence=link_confidence,
            document_context_link_reason=context_reason,
            operator_confirmation_required=True,
            storage_path=queued.stored_relative_path,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        await self._log_document_analyst_event(source_case_id, 'DOCUMENT_ANALYST_CONTEXT_READY', ready)

        target_open_item = await self.open_items_service.create_item(
            case_id=target_case_id,
            title='Document Analyst Eingang vorbereiten',
            description=(
                f'Telegram-{"Dokument" if attachment.media_kind == "document" else "Bild"} konservativ fuer den Document-Analyst-Kontext vorbereitet.\n'
                f'Quelle: {source_case_id}\n'
                f'Telegram-Chat: {normalized.telegram_chat_ref}\n'
                f'Telegram-Message: {normalized.telegram_message_ref}\n'
                f'Dokument-Ref: {queued.document_ref or "-"}\n'
                f'Dokumenten-Intake: {queued.document_intake_ref or "-"} ({queued.document_intake_status or "-"})\n'
                f'Kontext-Ziel: {target_case_id}\n'
                f'Link-Confidence: {link_confidence}\n'
                f'Link-Grund: {context_reason}\n'
                f'Speicherpfad: {queued.stored_relative_path or "-"}\n'
                'Keine automatische Vollanalyse. Operatorische Bestaetigung bleibt erforderlich.'
            ),
            source='document_analyst',
            document_ref=queued.document_ref,
        )
        final_status = (
            'DOCUMENT_ANALYST_CONTEXT_ATTACHED'
            if queued.linked_context_case_id
            else 'DOCUMENT_ANALYST_PENDING'
        )
        final_record = ready.model_copy(
            update={
                'analyst_context_status': final_status,
                'analyst_context_open_item_id': target_open_item.item_id,
                'analyst_context_open_item_title': target_open_item.title,
                'updated_at': datetime.utcnow(),
            }
        )
        await self._log_document_analyst_event(source_case_id, final_status, final_record)
        if target_case_id != source_case_id:
            await self._log_document_analyst_event(target_case_id, final_status, final_record)
        return final_record

    async def _prepare_document_analyst_start_ready(
        self,
        context: TelegramDocumentAnalystContextRecord,
    ) -> TelegramDocumentAnalystStartRecord:
        ready_record = TelegramDocumentAnalystStartRecord(
            start_ref=f'doc-start:{context.analyst_context_ref}',
            document_analyst_context_ref=context.analyst_context_ref,
            source_case_id=context.source_case_id,
            target_case_id=context.target_case_id,
            telegram_document_ref=context.telegram_document_ref,
            telegram_media_ref=context.telegram_media_ref,
            media_domain=context.media_domain,
            document_intake_ref=context.document_intake_ref,
            analysis_start_status='DOCUMENT_ANALYST_START_READY',
            analysis_start_confidence=context.document_context_link_confidence,
            analysis_start_reason=(
                'linked_existing_document_context'
                if context.analyst_context_status == 'DOCUMENT_ANALYST_CONTEXT_ATTACHED'
                else 'telegram_document_ready_for_operator_start'
                if context.media_domain == 'DOCUMENT'
                else 'telegram_media_requires_operator_confirmed_start'
            ),
            analysis_start_requires_operator=True,
            trigger='context_prepared',
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        await self._log_document_analyst_start_event(context.source_case_id, ready_record)
        if context.target_case_id != context.source_case_id:
            await self._log_document_analyst_start_event(context.target_case_id, ready_record)
        return ready_record

    async def _log_media_event(self, case_id: str, action: str, payload: dict) -> None:
        await self.audit_service.log_event(
            {
                'event_id': str(uuid.uuid4()),
                'case_id': case_id,
                'source': 'telegram',
                'agent_name': 'frya-orchestrator',
                'approval_status': 'NOT_REQUIRED',
                'action': action,
                'result': payload.get('media_ref') or payload.get('rejection_reason') or action,
                'llm_output': payload,
            }
        )

    async def _log_document_analyst_event(
        self,
        case_id: str,
        action: str,
        payload: TelegramDocumentAnalystContextRecord,
    ) -> None:
        await self.audit_service.log_event(
            {
                'event_id': str(uuid.uuid4()),
                'case_id': case_id,
                'source': 'telegram',
                'document_ref': payload.telegram_document_ref,
                'agent_name': 'document-analyst',
                'approval_status': 'NOT_REQUIRED',
                'action': action,
                'result': payload.analyst_context_ref,
                'llm_output': payload.model_dump(mode='json'),
            }
        )

    async def _log_document_analyst_start_event(
        self,
        case_id: str,
        payload: TelegramDocumentAnalystStartRecord,
    ) -> None:
        await self.audit_service.log_event(
            {
                'event_id': str(uuid.uuid4()),
                'case_id': case_id,
                'source': 'telegram',
                'document_ref': payload.telegram_document_ref,
                'agent_name': 'document-analyst',
                'approval_status': 'NOT_REQUIRED',
                'action': payload.analysis_start_status,
                'result': payload.start_ref,
                'llm_output': payload.model_dump(mode='json'),
            }
        )

    def _base_record(
        self,
        normalized: TelegramNormalizedIngressMessage,
        case_id: str,
        thread_ref: str,
        attachment: TelegramMediaAttachment,
    ) -> TelegramMediaIngressRecord:
        return TelegramMediaIngressRecord(
            media_ref=str(uuid.uuid4()),
            case_id=case_id,
            telegram_chat_ref=normalized.telegram_chat_ref,
            telegram_message_ref=normalized.telegram_message_ref,
            telegram_thread_ref=thread_ref,
            media_kind=attachment.media_kind,
            media_domain='DOCUMENT' if attachment.media_kind == 'document' else 'PHOTO',
            telegram_file_id=attachment.telegram_file_id,
            telegram_file_unique_id=attachment.telegram_file_unique_id,
            file_name=attachment.file_name,
            mime_type=attachment.mime_type,
            file_size=attachment.file_size,
            caption_text=normalized.text or None,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )

    def _validate_attachment(self, attachment: TelegramMediaAttachment) -> str | None:
        size = attachment.file_size or 0
        if size and size > self.max_bytes:
            return 'file_too_large'

        if attachment.media_kind == 'photo':
            return None

        file_name = attachment.file_name or ''
        ext = Path(file_name).suffix.lower()
        mime = (attachment.mime_type or '').lower()
        if mime == 'application/pdf':
            return None
        if ext == '.pdf':
            return None
        return 'unsupported_media_type'

    @staticmethod
    def _pick_attachment(attachments: list[TelegramMediaAttachment]) -> TelegramMediaAttachment | None:
        if not attachments:
            return None
        return attachments[0]

    @staticmethod
    def _rejected_route(
        case_id: str,
        thread_ref: str,
        status: str,
        label: str,
        detail: str,
        next_step: str,
        attachment: TelegramMediaAttachment | None,
    ) -> TelegramRoutingResult:
        ack_map = {
            'MEDIA_TOO_LARGE': 'ACK_MEDIA_TOO_LARGE',
            'MEDIA_UNSUPPORTED': 'ACK_MEDIA_UNSUPPORTED',
            'MEDIA_DOWNLOAD_FAILED': 'ACK_MEDIA_FAILED',
            'DOCUMENT_TOO_LARGE': 'ACK_DOCUMENT_TOO_LARGE',
            'DOCUMENT_UNSUPPORTED': 'ACK_DOCUMENT_UNSUPPORTED',
            'DOCUMENT_DOWNLOAD_FAILED': 'ACK_DOCUMENT_FAILED',
            'DOCUMENT_UPLOAD_FAILED': 'ACK_DOCUMENT_FAILED',
            'MEDIA_UPLOAD_FAILED': 'ACK_MEDIA_FAILED',
        }
        return TelegramRoutingResult(
            case_id=case_id,
            routing_status=status,
            intent_name='document.ingress' if attachment and attachment.media_kind == 'document' else 'media.ingress',
            ack_template=ack_map[status],
            authorization_status='AUTHORIZED',
            next_manual_step=next_step,
            telegram_thread_ref=thread_ref,
            linked_case_id=case_id,
            user_visible_status_code='NOT_AVAILABLE',
            user_visible_status_label=label,
            user_visible_status_detail=detail,
        )

    @staticmethod
    def _event_name(attachment: TelegramMediaAttachment, suffix: str) -> str:
        prefix = 'TELEGRAM_DOCUMENT' if attachment.media_kind == 'document' else 'TELEGRAM_MEDIA'
        return f'{prefix}_{suffix}'

    @staticmethod
    def _download_failed_status(attachment: TelegramMediaAttachment) -> str:
        return 'DOCUMENT_DOWNLOAD_FAILED' if attachment.media_kind == 'document' else 'MEDIA_DOWNLOAD_FAILED'

    @staticmethod
    def _rejected_status(attachment: TelegramMediaAttachment, rejection_reason: str) -> str:
        is_too_large = rejection_reason == 'file_too_large'
        if attachment.media_kind == 'document':
            return 'DOCUMENT_TOO_LARGE' if is_too_large else 'DOCUMENT_UNSUPPORTED'
        return 'MEDIA_TOO_LARGE' if is_too_large else 'MEDIA_UNSUPPORTED'

    @staticmethod
    def _safe_file_name(file_name: str | None, attachment: TelegramMediaAttachment) -> str:
        raw_name = Path(file_name or '').name.strip()
        if raw_name:
            stem = ''.join(ch if ch.isalnum() or ch in {'-', '_', '.'} else '_' for ch in raw_name)
            return stem[:120]
        ext = '.jpg' if attachment.media_kind == 'photo' else '.bin'
        return f'telegram_media{ext}'

    def _build_storage_path(self, case_id: str, attachment: TelegramMediaAttachment) -> str:
        file_name = self._safe_file_name(attachment.file_name, attachment)
        ext = Path(file_name).suffix.lower()
        if not ext:
            ext = '.jpg' if attachment.media_kind == 'photo' else '.bin'
            file_name = f'{file_name}{ext}'
        folder = datetime.utcnow().strftime('telegram/media/%Y/%m/%d')
        return os.path.join(folder, case_id, f'{uuid.uuid4()}_{file_name}').replace('\\', '/')
