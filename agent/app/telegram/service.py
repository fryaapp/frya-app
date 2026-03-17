from __future__ import annotations

import uuid
from datetime import datetime

from app.audit.models import AuditRecord
from app.open_items.models import OpenItem
from app.problems.models import ProblemCase
from app.telegram.models import (
    TelegramCaseLinkRecord,
    TelegramClarificationRecord,
    TelegramNormalizedIngressMessage,
    TelegramRoutingResult,
    TelegramUserVisibleStatus,
)
from app.telegram.repository import TelegramCaseLinkRepository


class TelegramCaseLinkService:
    def __init__(self, repository: TelegramCaseLinkRepository) -> None:
        self.repository = repository

    async def initialize(self) -> None:
        await self.repository.setup()

    @staticmethod
    def build_thread_ref(normalized: TelegramNormalizedIngressMessage) -> str:
        sender_key = normalized.actor.sender_id or normalized.actor.chat_id
        return f"{normalized.telegram_chat_ref}:{sender_key}"

    async def upsert_case_link(
        self,
        normalized: TelegramNormalizedIngressMessage,
        route: TelegramRoutingResult,
        reply_status: str,
        reply_reason: str | None = None,
        problem_case_id: str | None = None,
    ) -> TelegramCaseLinkRecord:
        now = datetime.utcnow()
        existing = await self.repository.get_by_case(route.case_id)
        record = TelegramCaseLinkRecord(
            link_id=existing.link_id if existing else str(uuid.uuid4()),
            case_id=route.case_id,
            telegram_update_ref=normalized.telegram_update_ref,
            telegram_message_ref=normalized.telegram_message_ref,
            telegram_chat_ref=normalized.telegram_chat_ref,
            telegram_thread_ref=route.telegram_thread_ref or self.build_thread_ref(normalized),
            sender_id=normalized.actor.sender_id,
            sender_username=normalized.actor.sender_username,
            routing_status=route.routing_status,
            authorization_status=route.authorization_status,
            intent_name=route.intent_name,
            open_item_id=route.open_item_id or route.linked_open_item_id,
            open_item_title=route.open_item_title,
            problem_case_id=problem_case_id or route.linked_problem_case_id,
            linked_case_id=route.linked_case_id,
            track_for_status=route.track_for_status,
            reply_status=reply_status,
            reply_reason=reply_reason,
            created_at=existing.created_at if existing else now,
            updated_at=now,
        )
        await self.repository.upsert(record)
        return record

    async def get_by_case(self, case_id: str) -> TelegramCaseLinkRecord | None:
        return await self.repository.get_by_case(case_id)

    async def latest_trackable_for_message(
        self,
        normalized: TelegramNormalizedIngressMessage,
        exclude_case_id: str | None = None,
    ) -> TelegramCaseLinkRecord | None:
        return await self.repository.find_latest_trackable(
            telegram_thread_ref=self.build_thread_ref(normalized),
            exclude_case_id=exclude_case_id,
        )

    async def latest_trackable_for_linked_case(self, linked_case_id: str) -> TelegramCaseLinkRecord | None:
        return await self.repository.find_latest_trackable_for_linked_case(linked_case_id)

    async def build_user_visible_status(
        self,
        record: TelegramCaseLinkRecord | None,
        open_items: list[OpenItem],
        problems: list[ProblemCase],
        chronology: list[AuditRecord],
        clarification: TelegramClarificationRecord | None = None,
    ) -> TelegramUserVisibleStatus:
        if record is None:
            return TelegramUserVisibleStatus(
                status_code='NOT_AVAILABLE',
                status_label='Kein verknuepfter Eingang',
                status_detail='Zu diesem Telegram-Eingang liegt noch kein verknuepfter Fall vor.',
            )

        if record.authorization_status != 'AUTHORIZED':
            return TelegramUserVisibleStatus(
                status_code='REJECTED',
                status_label='Nicht angenommen',
                status_detail='Dieser Telegram-Eingang wurde aus Sicherheitsgruenden nicht verarbeitet.',
                linked_case_id=record.linked_case_id or record.case_id,
                last_update_at=record.updated_at,
            )

        if record.routing_status == 'UNSUPPORTED_MESSAGE_TYPE':
            return TelegramUserVisibleStatus(
                status_code='NOT_AVAILABLE',
                status_label='Nicht unterstuetzt',
                status_detail='Dieser Telegram-Typ wird in V1 nur als Hinweis beantwortet und nicht weiterverarbeitet.',
                linked_case_id=record.linked_case_id or record.case_id,
                last_update_at=record.updated_at,
            )

        if record.routing_status == 'CLARIFICATION_ANSWER_AMBIGUOUS':
            return TelegramUserVisibleStatus(
                status_code='UNDER_REVIEW',
                status_label='Antwort wird geprueft',
                status_detail='Deine Antwort ist eingegangen, konnte aber nicht eindeutig zugeordnet werden und wird manuell geprueft.',
                linked_case_id=record.linked_case_id or record.case_id,
                last_update_at=record.updated_at,
            )

        if record.routing_status == 'CLARIFICATION_NOT_OPEN':
            return TelegramUserVisibleStatus(
                status_code='NOT_AVAILABLE',
                status_label='Keine offene Rueckfrage',
                status_detail='Zu diesem Telegram-Eingang liegt aktuell keine offene Rueckfrage vor.',
                linked_case_id=record.linked_case_id or record.case_id,
                last_update_at=record.updated_at,
            )

        active_items = [item for item in open_items if item.status not in {'COMPLETED', 'CANCELLED'}]
        latest_item = sorted(open_items, key=lambda item: item.updated_at, reverse=True)[0] if open_items else None
        latest_problem = sorted(problems, key=lambda problem: problem.created_at, reverse=True)[0] if problems else None
        meaningful_actions = [
            event.action
            for event in chronology
            if event.action not in {
                'TELEGRAM_WEBHOOK_RECEIVED',
                'TELEGRAM_INTENT_RECOGNIZED',
                'TELEGRAM_ROUTED',
                'TELEGRAM_REPLY_ATTEMPTED',
                'TELEGRAM_DUPLICATE_IGNORED',
                'TELEGRAM_AUTH_DENIED',
                'TELEGRAM_SECRET_DENIED',
            }
        ]

        if clarification and clarification.clarification_state == 'OPEN':
            detail = 'Frya hat eine Rueckfrage gestellt und wartet auf deine Antwort.'
            if clarification.clarification_round > 1:
                detail = 'Frya hat eine weitere Rueckfrage gestellt und wartet auf deine Antwort.'
            return TelegramUserVisibleStatus(
                status_code='WAITING_FOR_YOUR_REPLY',
                status_label='Warten auf deine Antwort',
                status_detail=detail,
                linked_case_id=record.linked_case_id or record.case_id,
                open_item_id=clarification.open_item_id,
                open_item_title=clarification.open_item_title,
                last_update_at=clarification.updated_at,
            )

        if clarification and clarification.clarification_state == 'WITHDRAWN':
            if clarification.internal_followup_state == 'COMPLETED':
                return TelegramUserVisibleStatus(
                    status_code='COMPLETED',
                    status_label='Intern abgeschlossen',
                    status_detail=(
                        'Die interne Nachbearbeitung ist abgeschlossen. '
                        'Es ist keine Telegram-Antwort mehr erforderlich.'
                    ),
                    linked_case_id=record.linked_case_id or record.case_id,
                    open_item_id=clarification.open_item_id,
                    open_item_title=clarification.open_item_title,
                    last_update_at=clarification.internal_followup_resolved_at or clarification.updated_at,
                )
            return TelegramUserVisibleStatus(
                status_code='UNDER_INTERNAL_REVIEW',
                status_label='Intern in Bearbeitung',
                status_detail=(
                    'Die Anfrage wurde intern uebernommen. '
                    'Es ist keine Telegram-Antwort mehr erforderlich.'
                ),
                linked_case_id=record.linked_case_id or record.case_id,
                open_item_id=clarification.open_item_id,
                open_item_title=clarification.open_item_title,
                last_update_at=clarification.updated_at,
            )

        if clarification and clarification.clarification_state == 'ANSWER_RECEIVED':
            return TelegramUserVisibleStatus(
                status_code='REPLY_RECEIVED',
                status_label='Antwort erhalten',
                status_detail='Deine Antwort ist eingegangen und wird intern geprueft.',
                linked_case_id=record.linked_case_id or record.case_id,
                open_item_id=clarification.open_item_id,
                open_item_title=clarification.open_item_title,
                last_update_at=clarification.answer_received_at or clarification.updated_at,
            )

        if clarification and clarification.clarification_state == 'UNDER_REVIEW':
            return TelegramUserVisibleStatus(
                status_code='UNDER_REVIEW',
                status_label='Antwort in Pruefung',
                status_detail='Deine Antwort wird aktuell operatorisch geprueft.',
                linked_case_id=record.linked_case_id or record.case_id,
                open_item_id=clarification.open_item_id,
                open_item_title=clarification.open_item_title,
                last_update_at=clarification.review_started_at or clarification.updated_at,
            )

        if clarification and clarification.internal_followup_state in {'REQUIRED', 'UNDER_REVIEW', 'IN_PROGRESS'}:
            detail = 'Deine Angaben wurden erhalten. Der Fall wird intern weiter geprueft. Es gibt keine weitere Telegram-Rueckfrage.'
            if clarification.internal_followup_state == 'UNDER_REVIEW':
                detail = 'Deine Angaben wurden erhalten. Der Fall ist in interner Nachbearbeitung. Es gibt keine weitere Telegram-Rueckfrage.'
            return TelegramUserVisibleStatus(
                status_code='UNDER_INTERNAL_REVIEW',
                status_label='Intern weiter in Pruefung',
                status_detail=detail,
                linked_case_id=record.linked_case_id or record.case_id,
                open_item_id=clarification.open_item_id,
                open_item_title=clarification.open_item_title,
                last_update_at=(
                    clarification.internal_followup_review_started_at
                    or clarification.resolved_at
                    or clarification.updated_at
                ),
            )

        if clarification and clarification.internal_followup_state == 'COMPLETED':
            return TelegramUserVisibleStatus(
                status_code='COMPLETED',
                status_label='Intern abgeschlossen',
                status_detail='Deine Angaben wurden intern weiterbearbeitet. Dieser Telegram-Klaerpunkt ist abgeschlossen.',
                linked_case_id=record.linked_case_id or record.case_id,
                open_item_id=clarification.open_item_id,
                open_item_title=clarification.open_item_title,
                last_update_at=clarification.internal_followup_resolved_at or clarification.updated_at,
            )

        if clarification and clarification.clarification_state == 'STILL_OPEN':
            if clarification.follow_up_allowed:
                return TelegramUserVisibleStatus(
                    status_code='NEEDS_FURTHER_REPLY',
                    status_label='Weitere Klaerung noetig',
                    status_detail='Deine Antwort reicht noch nicht aus. Es ist genau eine weitere Rueckfrage moeglich.',
                    linked_case_id=record.linked_case_id or record.case_id,
                    open_item_id=clarification.open_item_id,
                    open_item_title=clarification.open_item_title,
                    last_update_at=clarification.resolved_at or clarification.updated_at,
                )
            return TelegramUserVisibleStatus(
                status_code='UNDER_INTERNAL_REVIEW',
                status_label='Intern weiter in Pruefung',
                status_detail='Deine Angaben wurden erhalten. Der Fall wird intern weiter geprueft. Es gibt keine weitere Telegram-Rueckfrage.',
                linked_case_id=record.linked_case_id or record.case_id,
                open_item_id=clarification.open_item_id,
                open_item_title=clarification.open_item_title,
                last_update_at=clarification.resolved_at or clarification.updated_at,
            )

        if clarification and clarification.clarification_state == 'COMPLETED':
            return TelegramUserVisibleStatus(
                status_code='COMPLETED',
                status_label='Klaerung abgeschlossen',
                status_detail='Deine Rueckfrage-Antwort wurde operatorisch gesichtet und fuer diesen Klaerpunkt abgeschlossen.',
                linked_case_id=record.linked_case_id or record.case_id,
                open_item_id=clarification.open_item_id,
                open_item_title=clarification.open_item_title,
                last_update_at=clarification.resolved_at or clarification.updated_at,
            )

        if latest_problem or any(item.status in {'WAITING_USER', 'WAITING_DATA'} for item in active_items):
            return TelegramUserVisibleStatus(
                status_code='NEEDS_CLARIFICATION',
                status_label='Klaerung noetig',
                status_detail='Dein letzter Eingang braucht noch manuelle Klaerung oder zusaetzliche Informationen.',
                linked_case_id=record.linked_case_id or record.case_id,
                open_item_id=latest_item.item_id if latest_item else None,
                open_item_title=latest_item.title if latest_item else None,
                problem_case_id=latest_problem.problem_id if latest_problem else None,
                last_update_at=(latest_problem.created_at if latest_problem else latest_item.updated_at if latest_item else record.updated_at),
            )

        if any(item.status == 'SCHEDULED' for item in active_items) or (meaningful_actions and not active_items and not latest_item):
            return TelegramUserVisibleStatus(
                status_code='IN_PROGRESS',
                status_label='In Bearbeitung',
                status_detail='Dein letzter Eingang wird intern bearbeitet.',
                linked_case_id=record.linked_case_id or record.case_id,
                open_item_id=latest_item.item_id if latest_item else None,
                open_item_title=latest_item.title if latest_item else None,
                last_update_at=latest_item.updated_at if latest_item else record.updated_at,
            )

        if any(item.status == 'OPEN' for item in active_items):
            return TelegramUserVisibleStatus(
                status_code='IN_QUEUE',
                status_label='In operatorischer Pruefung',
                status_detail='Dein letzter Eingang wartet aktuell auf operatorische Pruefung.',
                linked_case_id=record.linked_case_id or record.case_id,
                open_item_id=latest_item.item_id if latest_item else None,
                open_item_title=latest_item.title if latest_item else None,
                last_update_at=latest_item.updated_at if latest_item else record.updated_at,
            )

        if latest_item and latest_item.status == 'COMPLETED':
            return TelegramUserVisibleStatus(
                status_code='COMPLETED',
                status_label='Abgeschlossen',
                status_detail='Dein letzter Eingang wurde intern abgeschlossen.',
                linked_case_id=record.linked_case_id or record.case_id,
                open_item_id=latest_item.item_id,
                open_item_title=latest_item.title,
                last_update_at=latest_item.updated_at,
            )

        if record.track_for_status:
            return TelegramUserVisibleStatus(
                status_code='RECEIVED',
                status_label='Empfangen',
                status_detail='Dein letzter Eingang wurde aufgenommen, hat aber noch keinen weiterfuehrenden Bearbeitungsstatus.',
                linked_case_id=record.linked_case_id or record.case_id,
                last_update_at=record.updated_at,
            )

        return TelegramUserVisibleStatus(
            status_code='NOT_AVAILABLE',
            status_label='Kein verknuepfter Fall',
            status_detail='Zu deinem letzten Telegram-Eingang liegt noch kein verknuepfter Fall vor.',
            linked_case_id=record.linked_case_id,
            last_update_at=record.updated_at,
        )
