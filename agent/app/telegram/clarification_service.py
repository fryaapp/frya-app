from __future__ import annotations

import json
import uuid
from datetime import datetime

from app.audit.service import AuditService
from app.connectors.contracts import NotificationMessage
from app.connectors.notifications_telegram import TelegramConnector
from app.open_items.service import OpenItemsService
from app.telegram.clarification_repository import TelegramClarificationRepository
from app.telegram.models import TelegramCaseLinkRecord, TelegramClarificationRecord, TelegramNormalizedIngressMessage
from app.telegram.notification_service import TelegramNotificationService


class TelegramClarificationService:
    def __init__(
        self,
        repository: TelegramClarificationRepository,
        audit_service: AuditService,
        open_items_service: OpenItemsService,
        telegram_connector: TelegramConnector,
        telegram_notification_service: TelegramNotificationService,
    ) -> None:
        self.repository = repository
        self.audit_service = audit_service
        self.open_items_service = open_items_service
        self.telegram_connector = telegram_connector
        self.telegram_notification_service = telegram_notification_service

    async def initialize(self) -> None:
        await self.repository.setup()

    async def latest_by_case(self, linked_case_id: str) -> TelegramClarificationRecord | None:
        return await self.repository.latest_by_case(linked_case_id)

    async def list_by_case(self, linked_case_id: str) -> list[TelegramClarificationRecord]:
        return list(await self.repository.list_by_case(linked_case_id))

    async def request_clarification(
        self,
        linked_case_id: str,
        telegram_case_link: TelegramCaseLinkRecord,
        question_text: str,
        asked_by: str,
        source: str,
    ) -> TelegramClarificationRecord:
        question = question_text.strip()
        if not question:
            raise ValueError('Rueckfrage darf nicht leer sein.')

        latest = await self.repository.latest_by_case(linked_case_id)
        if latest is not None and latest.clarification_state not in {'COMPLETED', 'STILL_OPEN'}:
            raise ValueError('Fuer diesen Fall ist bereits eine Telegram-Rueckfrage aktiv oder noch in Pruefung.')
        follow_up_count = 0
        clarification_round = 1
        parent_clarification_ref = None
        follow_up_reason = None
        follow_up_block_reason = None
        if latest is not None and latest.clarification_state == 'STILL_OPEN':
            if latest.follow_up_allowed is not True:
                raise ValueError(latest.follow_up_block_reason or 'Weitere Telegram-Rueckfrage ist fuer diesen Fall nicht mehr erlaubt.')
            follow_up_count = latest.follow_up_count + 1
            clarification_round = latest.clarification_round + 1
            parent_clarification_ref = latest.clarification_ref
            follow_up_reason = latest.follow_up_reason or latest.resolution_note
            if clarification_round > 2 or follow_up_count > latest.max_follow_up_allowed:
                raise ValueError('Es ist maximal eine weitere Telegram-Rueckfrage pro Fall erlaubt.')

        existing_open = await self.repository.open_by_thread(telegram_case_link.telegram_thread_ref)
        if existing_open:
            raise ValueError('Es gibt bereits eine offene Telegram-Rueckfrage fuer diesen Thread.')

        now = datetime.utcnow()
        record = TelegramClarificationRecord(
            clarification_ref=str(uuid.uuid4()),
            linked_case_id=linked_case_id,
            telegram_thread_ref=telegram_case_link.telegram_thread_ref,
            telegram_chat_ref=telegram_case_link.telegram_chat_ref,
            telegram_case_ref=telegram_case_link.case_id,
            telegram_case_link_id=telegram_case_link.link_id,
            open_item_id=telegram_case_link.open_item_id,
            open_item_title=telegram_case_link.open_item_title,
            asked_by=asked_by,
            question_text=question,
            clarification_round=clarification_round,
            parent_clarification_ref=parent_clarification_ref,
            follow_up_count=follow_up_count,
            max_follow_up_allowed=1,
            follow_up_allowed=False,
            follow_up_reason=follow_up_reason,
            follow_up_block_reason='Antwort ausstehend.',
            telegram_followup_exhausted=False,
            internal_followup_required=False,
            internal_followup_state='NOT_REQUIRED',
            handoff_reason=None,
            operator_guidance=None,
            telegram_clarification_closed_for_user_input=False,
            internal_followup_closed_for_user_input=False,
            late_reply_policy='REJECT_NOT_OPEN',
            internal_followup_review_started_at=None,
            internal_followup_reviewed_by=None,
            internal_followup_review_note=None,
            internal_followup_resolved_at=None,
            internal_followup_resolved_by=None,
            internal_followup_resolution_note=None,
            clarification_state='OPEN',
            expected_reply_state='WAITING_FOR_REPLY',
            delivery_state='PENDING',
            created_at=now,
            updated_at=now,
        )
        await self.repository.upsert(record)

        if telegram_case_link.open_item_id:
            await self.open_items_service.update_status(telegram_case_link.open_item_id, 'WAITING_USER')

        await self.audit_service.log_event(
            {
                'event_id': str(uuid.uuid4()),
                'case_id': linked_case_id,
                'source': 'telegram',
                'agent_name': 'frya-orchestrator',
                'approval_status': 'NOT_REQUIRED',
                'action': 'TELEGRAM_CLARIFICATION_REQUESTED',
                'result': record.clarification_ref,
                'llm_output': record.model_dump(mode='json'),
            }
        )

        result = await self.telegram_connector.send(
            NotificationMessage(
                target=telegram_case_link.telegram_chat_ref.replace('tg-chat:', ''),
                text=(
                    'FRYA Rueckfrage\n'
                    f'{record.question_text}\n'
                    'Bitte antworte direkt in diesem Chat. Deine Antwort wird dem offenen Anliegen zugeordnet.'
                ),
                metadata={'case_id': linked_case_id, 'telegram_clarification_ref': record.clarification_ref},
            )
        )
        delivery_state, reply_reason, outgoing_message_id = self._delivery_state(result)
        updated = record.model_copy(
            update={
                'delivery_state': delivery_state,
                'outgoing_message_id': outgoing_message_id,
                'outgoing_message_ref': f'tg-message:{outgoing_message_id}' if outgoing_message_id is not None else None,
                'updated_at': datetime.utcnow(),
            }
        )
        await self.repository.upsert(updated)

        await self.audit_service.log_event(
            {
                'event_id': str(uuid.uuid4()),
                'case_id': linked_case_id,
                'source': 'telegram',
                'agent_name': 'frya-orchestrator',
                'approval_status': 'NOT_REQUIRED',
                'action': 'TELEGRAM_CLARIFICATION_DELIVERY',
                'result': delivery_state,
                'llm_output': {
                    **updated.model_dump(mode='json'),
                    'reply_reason': reply_reason,
                },
            }
        )
        return updated

    async def resolve_incoming_answer(
        self,
        normalized: TelegramNormalizedIngressMessage,
        answer_case_id: str,
    ) -> tuple[str, TelegramClarificationRecord | None]:
        thread_ref = f"{normalized.telegram_chat_ref}:{normalized.actor.sender_id or normalized.actor.chat_id}"
        if normalized.reply_to_message_id is not None:
            matched = await self.repository.open_by_outgoing_message(thread_ref, normalized.reply_to_message_id)
            if matched is not None:
                return 'MATCHED', matched

        open_items = list(await self.repository.open_by_thread(thread_ref))
        if not open_items:
            return 'NOT_OPEN', None
        if len(open_items) > 1:
            return 'AMBIGUOUS', None
        return 'MATCHED', open_items[0]

    async def accept_answer(
        self,
        record: TelegramClarificationRecord,
        answer_case_id: str,
        normalized: TelegramNormalizedIngressMessage,
    ) -> TelegramClarificationRecord:
        updated = record.model_copy(
            update={
                'clarification_state': 'ANSWER_RECEIVED',
                'expected_reply_state': 'ANSWER_RECEIVED',
                'answer_case_id': answer_case_id,
                'answer_text': normalized.text,
                'answer_message_ref': normalized.telegram_message_ref,
                'answer_received_at': datetime.utcnow(),
                'resolution_outcome': 'PENDING',
                'follow_up_allowed': False,
                'follow_up_block_reason': 'Antwort ist eingegangen und wird gesichtet.',
                'telegram_followup_exhausted': False,
                'internal_followup_required': False,
                'internal_followup_state': 'NOT_REQUIRED',
                'handoff_reason': None,
                'operator_guidance': None,
                'telegram_clarification_closed_for_user_input': False,
                'internal_followup_closed_for_user_input': False,
                'internal_followup_review_started_at': None,
                'internal_followup_reviewed_by': None,
                'internal_followup_review_note': None,
                'internal_followup_resolved_at': None,
                'internal_followup_resolved_by': None,
                'internal_followup_resolution_note': None,
                'updated_at': datetime.utcnow(),
            }
        )
        await self.repository.upsert(updated)
        if updated.open_item_id:
            await self.open_items_service.update_status(updated.open_item_id, 'WAITING_DATA')
        await self.audit_service.log_event(
            {
                'event_id': str(uuid.uuid4()),
                'case_id': updated.linked_case_id,
                'source': 'telegram',
                'agent_name': 'frya-orchestrator',
                'approval_status': 'NOT_REQUIRED',
                'action': 'TELEGRAM_CLARIFICATION_ANSWER_ACCEPTED',
                'result': updated.clarification_ref,
                'llm_input': {
                    'answer_case_id': answer_case_id,
                    'telegram_message_ref': normalized.telegram_message_ref,
                    'telegram_reply_to_message_ref': normalized.telegram_reply_to_message_ref,
                },
                'llm_output': updated.model_dump(mode='json'),
            }
        )
        return updated

    async def mark_under_review(
        self,
        linked_case_id: str,
        reviewed_by: str,
        note: str | None,
        source: str,
    ) -> TelegramClarificationRecord:
        record = await self.repository.latest_by_case(linked_case_id)
        if record is None:
            raise ValueError('Keine Telegram-Klaerung fuer diesen Fall vorhanden.')
        if record.clarification_state != 'ANSWER_RECEIVED':
            raise ValueError('Telegram-Klaerung ist nicht im Zustand REPLY_RECEIVED.')

        updated = record.model_copy(
            update={
                'clarification_state': 'UNDER_REVIEW',
                'expected_reply_state': 'UNDER_OPERATOR_REVIEW',
                'review_started_at': datetime.utcnow(),
                'reviewed_by': reviewed_by,
                'review_note': (note or '').strip() or None,
                'follow_up_allowed': False,
                'follow_up_block_reason': 'Telegram-Antwort ist in operatorischer Sichtung.',
                'telegram_followup_exhausted': False,
                'internal_followup_required': False,
                'internal_followup_state': 'NOT_REQUIRED',
                'handoff_reason': None,
                'operator_guidance': None,
                'telegram_clarification_closed_for_user_input': False,
                'internal_followup_closed_for_user_input': False,
                'internal_followup_review_started_at': None,
                'internal_followup_reviewed_by': None,
                'internal_followup_review_note': None,
                'internal_followup_resolved_at': None,
                'internal_followup_resolved_by': None,
                'internal_followup_resolution_note': None,
                'updated_at': datetime.utcnow(),
            }
        )
        await self.repository.upsert(updated)
        if updated.open_item_id:
            await self.open_items_service.update_status(updated.open_item_id, 'OPEN')
        await self.audit_service.log_event(
            {
                'event_id': str(uuid.uuid4()),
                'case_id': updated.linked_case_id,
                'source': source,
                'agent_name': 'frya-orchestrator',
                'approval_status': 'NOT_REQUIRED',
                'action': 'TELEGRAM_CLARIFICATION_UNDER_REVIEW',
                'result': updated.clarification_ref,
                'llm_output': updated.model_dump(mode='json'),
            }
        )
        return updated

    async def resolve_clarification(
        self,
        linked_case_id: str,
        decision: str,
        resolved_by: str,
        note: str | None,
        source: str,
    ) -> TelegramClarificationRecord:
        if decision not in {'COMPLETED', 'STILL_OPEN'}:
            raise ValueError('Unzulaessige Telegram-Klaerentscheidung.')

        record = await self.repository.latest_by_case(linked_case_id)
        if record is None:
            raise ValueError('Keine Telegram-Klaerung fuer diesen Fall vorhanden.')
        if record.clarification_state not in {'ANSWER_RECEIVED', 'UNDER_REVIEW'}:
            raise ValueError('Telegram-Klaerung ist nicht im aufloesbaren Zustand.')

        updated = record
        if record.clarification_state == 'ANSWER_RECEIVED':
            updated = await self.mark_under_review(
                linked_case_id=linked_case_id,
                reviewed_by=resolved_by,
                note='Automatisch in operatorische Sichtung uebernommen.',
                source=source,
            )

        final_status = decision
        expected_reply_state = 'CLOSED'
        follow_up_allowed = False
        follow_up_reason = None
        follow_up_block_reason = 'Telegram-Klaerung abgeschlossen.'
        telegram_followup_exhausted = False
        internal_followup_required = False
        internal_followup_state = 'NOT_REQUIRED'
        handoff_reason = None
        operator_guidance = None
        telegram_clarification_closed_for_user_input = decision == 'COMPLETED'
        internal_followup_closed_for_user_input = decision == 'COMPLETED'
        if decision == 'STILL_OPEN':
            if updated.clarification_round < 2 and updated.follow_up_count < updated.max_follow_up_allowed:
                expected_reply_state = 'FOLLOWUP_NEEDED'
                follow_up_allowed = True
                follow_up_reason = (note or '').strip() or 'Vorherige Nutzerantwort reicht noch nicht aus.'
                follow_up_block_reason = None
                telegram_clarification_closed_for_user_input = False
                internal_followup_closed_for_user_input = False
            else:
                expected_reply_state = 'INTERNAL_REVIEW_CONTINUES'
                follow_up_allowed = False
                follow_up_block_reason = 'Maximal eine weitere Telegram-Rueckfrage wurde bereits genutzt.'
                telegram_followup_exhausted = True
                internal_followup_required = True
                internal_followup_state = 'REQUIRED'
                handoff_reason = (note or '').strip() or 'Zweite Nutzerantwort reicht weiterhin nicht aus.'
                operator_guidance = (
                    'Telegram endet hier. Fall intern weiterpruefen, vorhandene Antworten gegen den Sachverhalt halten '
                    'und keine weitere Telegram-Rueckfrage ausloesen.'
                )
                telegram_clarification_closed_for_user_input = True
                internal_followup_closed_for_user_input = True
        final = updated.model_copy(
            update={
                'clarification_state': final_status,
                'expected_reply_state': expected_reply_state,
                'resolution_outcome': decision,
                'resolved_at': datetime.utcnow(),
                'resolved_by': resolved_by,
                'resolution_note': (note or '').strip() or None,
                'follow_up_allowed': follow_up_allowed,
                'follow_up_reason': follow_up_reason,
                'follow_up_block_reason': follow_up_block_reason,
                'telegram_followup_exhausted': telegram_followup_exhausted,
                'internal_followup_required': internal_followup_required,
                'internal_followup_state': internal_followup_state,
                'handoff_reason': handoff_reason,
                'operator_guidance': operator_guidance,
                'telegram_clarification_closed_for_user_input': telegram_clarification_closed_for_user_input,
                'internal_followup_closed_for_user_input': internal_followup_closed_for_user_input,
                'late_reply_policy': 'REJECT_NOT_OPEN',
                'internal_followup_review_started_at': None,
                'internal_followup_reviewed_by': None,
                'internal_followup_review_note': None,
                'internal_followup_resolved_at': None,
                'internal_followup_resolved_by': None,
                'internal_followup_resolution_note': None,
                'updated_at': datetime.utcnow(),
            }
        )
        await self.repository.upsert(final)
        if final.open_item_id:
            next_status = 'COMPLETED' if decision == 'COMPLETED' else 'OPEN'
            await self.open_items_service.update_status(final.open_item_id, next_status)
        await self.audit_service.log_event(
            {
                'event_id': str(uuid.uuid4()),
                'case_id': final.linked_case_id,
                'source': source,
                'agent_name': 'frya-orchestrator',
                'approval_status': 'NOT_REQUIRED',
                'action': f'TELEGRAM_CLARIFICATION_{decision}',
                'result': final.clarification_ref,
                'llm_output': final.model_dump(mode='json'),
            }
        )
        if final.internal_followup_required:
            await self.audit_service.log_event(
                {
                    'event_id': str(uuid.uuid4()),
                    'case_id': final.linked_case_id,
                    'source': source,
                    'agent_name': 'frya-orchestrator',
                    'approval_status': 'NOT_REQUIRED',
                    'action': 'TELEGRAM_INTERNAL_FOLLOWUP_REQUIRED',
                    'result': final.clarification_ref,
                    'llm_output': {
                        'clarification_ref': final.clarification_ref,
                        'clarification_round': final.clarification_round,
                        'internal_followup_state': final.internal_followup_state,
                        'internal_followup_required': final.internal_followup_required,
                        'telegram_followup_exhausted': final.telegram_followup_exhausted,
                        'handoff_reason': final.handoff_reason,
                        'operator_guidance': final.operator_guidance,
                        'telegram_clarification_closed_for_user_input': final.telegram_clarification_closed_for_user_input,
                        'late_reply_policy': final.late_reply_policy,
                        'open_item_id': final.open_item_id,
                        'open_item_title': final.open_item_title,
                    },
                }
            )
            await self.telegram_notification_service.send_case_notification(
                linked_case_id=final.linked_case_id,
                notification_type='INTERNAL_REVIEW_STARTED',
                trigger_action='TELEGRAM_INTERNAL_FOLLOWUP_REQUIRED',
                message_text=(
                    'FRYA Update\n'
                    'Deine Angaben wurden erhalten. Der Fall wird intern weiter geprueft.\n'
                    'Es ist keine weitere Antwort in Telegram noetig.'
                ),
                source=source,
                linked_open_item_id=final.open_item_id,
            )
        elif decision == 'COMPLETED':
            await self.telegram_notification_service.send_case_notification(
                linked_case_id=final.linked_case_id,
                notification_type='CLARIFICATION_COMPLETED',
                trigger_action='TELEGRAM_CLARIFICATION_COMPLETED',
                message_text=(
                    'FRYA Update\n'
                    'Die angeforderte Klaerung ist abgeschlossen.\n'
                    'Fuer diesen Klaerpunkt ist keine weitere Telegram-Antwort offen.'
                ),
                source=source,
                linked_open_item_id=final.open_item_id,
            )
        return final

    async def mark_internal_followup_under_review(
        self,
        linked_case_id: str,
        reviewed_by: str,
        note: str | None,
        source: str,
    ) -> TelegramClarificationRecord:
        record = await self.repository.latest_by_case(linked_case_id)
        if record is None:
            raise ValueError('Keine Telegram-Klaerung fuer diesen Fall vorhanden.')
        if record.clarification_state != 'STILL_OPEN' or not record.internal_followup_required:
            raise ValueError('Kein interner Telegram-Nachbearbeitungspfad fuer diesen Fall aktiv.')
        if record.internal_followup_state != 'REQUIRED':
            raise ValueError('Interner Telegram-Nachbearbeitungspfad ist nicht im aufnehmbaren Zustand.')

        updated = record.model_copy(
            update={
                'internal_followup_state': 'UNDER_REVIEW',
                'internal_followup_review_started_at': datetime.utcnow(),
                'internal_followup_reviewed_by': reviewed_by,
                'internal_followup_review_note': (note or '').strip() or None,
                'internal_followup_closed_for_user_input': True,
                'telegram_clarification_closed_for_user_input': True,
                'updated_at': datetime.utcnow(),
            }
        )
        await self.repository.upsert(updated)
        if updated.open_item_id:
            await self.open_items_service.update_status(updated.open_item_id, 'OPEN')
        await self.audit_service.log_event(
            {
                'event_id': str(uuid.uuid4()),
                'case_id': updated.linked_case_id,
                'source': source,
                'agent_name': 'frya-orchestrator',
                'approval_status': 'NOT_REQUIRED',
                'action': 'TELEGRAM_INTERNAL_FOLLOWUP_UNDER_REVIEW',
                'result': updated.clarification_ref,
                'llm_output': updated.model_dump(mode='json'),
            }
        )
        return updated

    async def complete_internal_followup(
        self,
        linked_case_id: str,
        resolved_by: str,
        note: str | None,
        source: str,
    ) -> TelegramClarificationRecord:
        record = await self.repository.latest_by_case(linked_case_id)
        if record is None:
            raise ValueError('Keine Telegram-Klaerung fuer diesen Fall vorhanden.')
        if record.clarification_state != 'STILL_OPEN' or not record.telegram_followup_exhausted:
            raise ValueError('Kein abgeschlossener Telegram-Follow-up-Strang fuer diesen Fall vorhanden.')
        if record.internal_followup_state != 'UNDER_REVIEW':
            raise ValueError('Interner Telegram-Nachbearbeitungspfad ist nicht im abschliessbaren Zustand.')

        updated = record.model_copy(
            update={
                'internal_followup_required': False,
                'internal_followup_state': 'COMPLETED',
                'internal_followup_resolved_at': datetime.utcnow(),
                'internal_followup_resolved_by': resolved_by,
                'internal_followup_resolution_note': (note or '').strip() or None,
                'internal_followup_closed_for_user_input': True,
                'telegram_clarification_closed_for_user_input': True,
                'operator_guidance': (
                    'Telegram ist fuer diesen Klaerpunkt beendet. Interne Nachbearbeitung wurde abgeschlossen '
                    'und es ist keine weitere Telegram-Rueckfrage vorgesehen.'
                ),
                'updated_at': datetime.utcnow(),
            }
        )
        await self.repository.upsert(updated)
        if updated.open_item_id:
            await self.open_items_service.update_status(updated.open_item_id, 'COMPLETED')
        await self.audit_service.log_event(
            {
                'event_id': str(uuid.uuid4()),
                'case_id': updated.linked_case_id,
                'source': source,
                'agent_name': 'frya-orchestrator',
                'approval_status': 'NOT_REQUIRED',
                'action': 'TELEGRAM_INTERNAL_FOLLOWUP_COMPLETED',
                'result': updated.clarification_ref,
                'llm_output': updated.model_dump(mode='json'),
            }
        )
        await self.telegram_notification_service.send_case_notification(
            linked_case_id=updated.linked_case_id,
            notification_type='INTERNAL_FOLLOWUP_COMPLETED',
            trigger_action='TELEGRAM_INTERNAL_FOLLOWUP_COMPLETED',
            message_text=(
                'FRYA Update\n'
                'Dein Anliegen wurde intern weiterbearbeitet.\n'
                'Der Telegram-Klaerpunkt ist abgeschlossen.'
            ),
            source=source,
            linked_open_item_id=updated.open_item_id,
        )
        return updated

    async def withdraw_clarification(
        self,
        linked_case_id: str,
        withdrawn_by: str,
        note: str | None,
        source: str,
    ) -> TelegramClarificationRecord:
        """Withdraw an OPEN Telegram clarification (data request) without waiting for user reply.

        Conservative boundary:
        - Only from OPEN state (before user has replied)
        - Sets clarification_state=WITHDRAWN, closes for user input
        - Open item: WAITING_USER -> OPEN (internal follow-up can continue)
        - Late replies will be rejected as CLARIFICATION_NOT_OPEN
        - No new Telegram loop triggered
        """
        record = await self.repository.latest_by_case(linked_case_id)
        if record is None:
            raise ValueError('Keine Telegram-Klaerung fuer diesen Fall vorhanden.')
        if record.clarification_state != 'OPEN':
            raise ValueError(
                f'Telegram-Klaerung kann nur aus Zustand OPEN zurueckgezogen werden, '
                f'aktuell: {record.clarification_state}.'
            )

        updated = record.model_copy(
            update={
                'clarification_state': 'WITHDRAWN',
                'expected_reply_state': 'CLOSED',
                'resolution_outcome': 'WITHDRAWN',
                'resolved_at': datetime.utcnow(),
                'resolved_by': withdrawn_by,
                'resolution_note': (note or '').strip() or 'Datennachforderung wurde operatorisch zurueckgezogen.',
                'follow_up_allowed': False,
                'follow_up_block_reason': 'Datennachforderung wurde zurueckgezogen.',
                'telegram_followup_exhausted': False,
                'internal_followup_required': False,
                'internal_followup_state': 'NOT_REQUIRED',
                'telegram_clarification_closed_for_user_input': True,
                'internal_followup_closed_for_user_input': False,
                'late_reply_policy': 'REJECT_NOT_OPEN',
                'updated_at': datetime.utcnow(),
            }
        )
        await self.repository.upsert(updated)

        if updated.open_item_id:
            # Reopen: internal operator takes over
            await self.open_items_service.update_status(updated.open_item_id, 'OPEN')

        await self.audit_service.log_event(
            {
                'event_id': str(uuid.uuid4()),
                'case_id': updated.linked_case_id,
                'source': source,
                'agent_name': 'frya-orchestrator',
                'approval_status': 'NOT_REQUIRED',
                'action': 'TELEGRAM_CLARIFICATION_WITHDRAWN',
                'result': updated.clarification_ref,
                'llm_output': {
                    **updated.model_dump(mode='json'),
                    'withdrawn_by': withdrawn_by,
                    'withdraw_note': (note or '').strip() or None,
                },
            }
        )
        return updated

    async def close_internal_for_withdrawn(
        self,
        linked_case_id: str,
        *,
        closed_by: str,
        note: str | None,
        source: str,
    ) -> TelegramClarificationRecord:
        """Mark WITHDRAWN clarification as internally completed.

        Used after the operator completes the internal follow-up path that
        was activated via withdraw. The user-visible status transitions from
        UNDER_INTERNAL_REVIEW to COMPLETED (Intern abgeschlossen).

        Guard: only from WITHDRAWN state.
        No Telegram messages sent.
        """
        record = await self.repository.latest_by_case(linked_case_id)
        if record is None:
            raise ValueError('Keine Telegram-Klaerung fuer diesen Fall vorhanden.')
        if record.clarification_state != 'WITHDRAWN':
            raise ValueError(
                f'Interner Abschluss ist nur fuer WITHDRAWN Klaerungen moeglich, '
                f'aktuell: {record.clarification_state}.'
            )

        updated = record.model_copy(
            update={
                'internal_followup_state': 'COMPLETED',
                'internal_followup_resolved_at': datetime.utcnow(),
                'internal_followup_resolved_by': closed_by,
                'internal_followup_resolution_note': (note or '').strip() or 'Interne Nachbearbeitung nach Rueckzug abgeschlossen.',
                'updated_at': datetime.utcnow(),
            }
        )
        await self.repository.upsert(updated)
        await self.audit_service.log_event(
            {
                'event_id': str(uuid.uuid4()),
                'case_id': updated.linked_case_id,
                'source': source,
                'agent_name': 'frya-orchestrator',
                'approval_status': 'NOT_REQUIRED',
                'action': 'TELEGRAM_CLARIFICATION_INTERNAL_COMPLETED',
                'result': updated.clarification_ref,
                'llm_output': {
                    'clarification_ref': updated.clarification_ref,
                    'clarification_state': updated.clarification_state,
                    'internal_followup_state': 'COMPLETED',
                    'closed_by': closed_by,
                    'close_note': (note or '').strip() or None,
                },
            }
        )
        return updated

    async def mark_ambiguous(
        self,
        telegram_case_ref: str,
        telegram_thread_ref: str,
        note: str,
    ) -> None:
        await self.audit_service.log_event(
            {
                'event_id': str(uuid.uuid4()),
                'case_id': telegram_case_ref,
                'source': 'telegram',
                'agent_name': 'frya-orchestrator',
                'approval_status': 'NOT_REQUIRED',
                'action': 'TELEGRAM_CLARIFICATION_ANSWER_AMBIGUOUS',
                'result': note,
                'llm_output': {
                    'telegram_thread_ref': telegram_thread_ref,
                    'status': 'AMBIGUOUS_ROUTING',
                },
            }
        )

    @staticmethod
    def _delivery_state(result: dict) -> tuple[str, str | None, int | None]:
        reason = result.get('reason')
        outgoing_message_id = None
        body = result.get('body')
        if isinstance(body, str):
            try:
                payload = json.loads(body)
            except Exception:
                payload = None
            if isinstance(payload, dict):
                outgoing_message_id = ((payload.get('result') or {}).get('message_id'))

        if bool(result.get('ok', False)):
            return 'SENT', reason, outgoing_message_id
        return 'FAILED', reason, outgoing_message_id
