import json
import uuid
from datetime import datetime
from typing import Any, Literal

from app.audit.service import AuditService
from app.open_items.service import OpenItemsService
from app.telegram.clarification_service import TelegramClarificationService
from app.telegram.models import (
    TelegramDocumentAnalystFollowupRecord,
    TelegramDocumentAnalystReviewRecord,
)
from app.telegram.service import TelegramCaseLinkService


class TelegramDocumentAnalystFollowupService:
    def __init__(
        self,
        audit_service: AuditService,
        open_items_service: OpenItemsService,
        telegram_case_link_service: TelegramCaseLinkService,
        telegram_clarification_service: TelegramClarificationService,
    ) -> None:
        self.audit_service = audit_service
        self.open_items_service = open_items_service
        self.telegram_case_link_service = telegram_case_link_service
        self.telegram_clarification_service = telegram_clarification_service

    async def mark_required_from_review(
        self,
        review_record: TelegramDocumentAnalystReviewRecord,
        *,
        source: str,
    ) -> TelegramDocumentAnalystFollowupRecord:
        if review_record.review_status != 'DOCUMENT_ANALYST_REVIEW_STILL_OPEN':
            raise ValueError('Document-Analyst-Follow-up ist nur hinter REVIEW_STILL_OPEN zulaessig.')

        chronology = await self.audit_service.by_case(review_record.source_case_id, limit=1000)
        existing_payload = self._latest_followup_payload(chronology)
        if existing_payload is not None:
            existing = TelegramDocumentAnalystFollowupRecord.model_validate(existing_payload)
            if existing.review_ref == review_record.review_ref:
                return existing

        required = self._build_required_record(review_record)
        await self._log_followup_record(required, source=source)
        return required

    async def execute_followup(
        self,
        case_id: str,
        *,
        mode: Literal['REQUEST_DATA', 'INTERNAL_ONLY', 'CLOSE_CONSERVATIVELY'],
        actor: str,
        note: str | None,
        source: str,
        question_text: str | None = None,
    ) -> TelegramDocumentAnalystFollowupRecord:
        chronology = await self.audit_service.by_case(case_id, limit=1000)
        review_payload = self._latest_review_payload(chronology)
        if review_payload is None:
            raise ValueError('Kein offener Document-Analyst-Review fuer diesen Fall vorhanden.')

        review_record = TelegramDocumentAnalystReviewRecord.model_validate(review_payload)
        if review_record.review_status != 'DOCUMENT_ANALYST_REVIEW_STILL_OPEN':
            raise ValueError('Document-Analyst-Follow-up ist nur hinter REVIEW_STILL_OPEN erlaubt.')

        followup_payload = self._latest_followup_payload(chronology)
        followup_record = (
            TelegramDocumentAnalystFollowupRecord.model_validate(followup_payload)
            if followup_payload is not None
            else await self.mark_required_from_review(review_record, source=source)
        )
        if followup_record.followup_status in {
            'DOCUMENT_ANALYST_FOLLOWUP_DATA_REQUESTED',
            'DOCUMENT_ANALYST_FOLLOWUP_COMPLETED',
            'DOCUMENT_ANALYST_FOLLOWUP_WITHDRAWN',
            'DOCUMENT_ANALYST_FOLLOWUP_INTERNAL_ONLY',
        }:
            raise ValueError('Document-Analyst-Follow-up fuer diesen Fall wurde bereits gesetzt.')

        if mode == 'REQUEST_DATA':
            return await self._request_data(
                followup_record=followup_record,
                actor=actor,
                note=note,
                question_text=question_text,
                source=source,
            )
        if mode == 'INTERNAL_ONLY':
            return await self._internal_only(
                followup_record=followup_record,
                actor=actor,
                note=note,
                source=source,
            )
        return await self._close_conservatively(
            followup_record=followup_record,
            actor=actor,
            note=note,
            source=source,
        )

    async def withdraw_data_request(
        self,
        case_id: str,
        *,
        actor: str,
        note: str | None,
        source: str,
    ) -> TelegramDocumentAnalystFollowupRecord:
        """Withdraw an open Telegram data request and take over internally.

        Guard: only from DATA_REQUESTED state.
        Effect:
          - Telegram clarification: OPEN -> WITHDRAWN
          - Followup: DATA_REQUESTED -> WITHDRAWN
          - Open item: WAITING_USER -> OPEN (internal handling continues)
          - no_further_telegram_action = True
          - Late user replies -> CLARIFICATION_NOT_OPEN
        """
        chronology = await self.audit_service.by_case(case_id, limit=1000)
        followup_payload = self._latest_followup_payload(chronology)
        if followup_payload is None:
            raise ValueError('Kein Document-Analyst-Follow-up fuer diesen Fall vorhanden.')

        followup_record = TelegramDocumentAnalystFollowupRecord.model_validate(followup_payload)
        if followup_record.followup_status != 'DOCUMENT_ANALYST_FOLLOWUP_DATA_REQUESTED':
            raise ValueError(
                f'Rueckzug ist nur aus Zustand DATA_REQUESTED moeglich, '
                f'aktuell: {followup_record.followup_status}.'
            )
        if not followup_record.linked_clarification_ref:
            raise ValueError('Kein verknuepfter Telegram-Klaerungsref fuer Rueckzug vorhanden.')

        # Withdraw the Telegram clarification (OPEN -> WITHDRAWN)
        linked_case_id = followup_record.source_case_id
        await self.telegram_clarification_service.withdraw_clarification(
            linked_case_id=linked_case_id,
            withdrawn_by=actor,
            note=note,
            source=source,
        )

        updated = followup_record.model_copy(
            update={
                'followup_status': 'DOCUMENT_ANALYST_FOLLOWUP_WITHDRAWN',
                'telegram_data_request_withdraw_allowed': False,
                'internal_takeover_allowed': True,
                'no_further_telegram_action': True,
                'linked_clarification_state': 'WITHDRAWN',
                'withdraw_reason': (note or '').strip() or 'Datennachforderung wurde operatorisch zurueckgezogen.',
                'actor': actor,
                'note': (note or '').strip() or None,
                'updated_at': datetime.utcnow(),
            }
        )
        await self._log_followup_record(updated, source=source)
        return updated

    async def activate_internal_takeover(
        self,
        case_id: str,
        *,
        actor: str,
        note: str | None,
        source: str,
    ) -> TelegramDocumentAnalystFollowupRecord:
        """Activate explicit internal takeover after a withdrawn data request.

        Guard: only from WITHDRAWN state.
        Effect: WITHDRAWN -> INTERNAL_ONLY.
        Open item: already OPEN from withdraw step, no change needed.
        No Telegram messages sent.
        """
        chronology = await self.audit_service.by_case(case_id, limit=1000)
        followup_payload = self._latest_followup_payload(chronology)
        if followup_payload is None:
            raise ValueError('Kein Document-Analyst-Follow-up fuer diesen Fall vorhanden.')

        followup_record = TelegramDocumentAnalystFollowupRecord.model_validate(followup_payload)
        if followup_record.followup_status != 'DOCUMENT_ANALYST_FOLLOWUP_WITHDRAWN':
            raise ValueError(
                f'Interne Uebernahme ist nur aus Zustand WITHDRAWN moeglich, '
                f'aktuell: {followup_record.followup_status}.'
            )

        updated = followup_record.model_copy(
            update={
                'followup_status': 'DOCUMENT_ANALYST_FOLLOWUP_INTERNAL_ONLY',
                'followup_mode': 'INTERNAL_ONLY',
                'internal_takeover_allowed': False,
                'internal_takeover_reason': (note or '').strip() or 'Datennachforderung zurueckgezogen. Interne Nachbearbeitung aktiv.',
                'no_further_telegram_action': True,
                'actor': actor,
                'note': (note or '').strip() or None,
                'updated_at': datetime.utcnow(),
            }
        )
        await self._log_followup_record(updated, source=source)
        return updated

    async def complete_internal(
        self,
        case_id: str,
        *,
        actor: str,
        note: str | None,
        source: str,
    ) -> TelegramDocumentAnalystFollowupRecord:
        """Conservative internal completion after INTERNAL_ONLY takeover.

        Guard: only from INTERNAL_ONLY state.
        Effect: INTERNAL_ONLY -> COMPLETED.
        Open item: -> COMPLETED.
        Clarification: WITHDRAWN + internal_followup_state -> COMPLETED (user sees 'Intern abgeschlossen').
        No Telegram messages sent.
        """
        chronology = await self.audit_service.by_case(case_id, limit=1000)
        followup_payload = self._latest_followup_payload(chronology)
        if followup_payload is None:
            raise ValueError('Kein Document-Analyst-Follow-up fuer diesen Fall vorhanden.')

        followup_record = TelegramDocumentAnalystFollowupRecord.model_validate(followup_payload)
        if followup_record.followup_status != 'DOCUMENT_ANALYST_FOLLOWUP_INTERNAL_ONLY':
            raise ValueError(
                f'Interner Abschluss ist nur aus Zustand INTERNAL_ONLY moeglich, '
                f'aktuell: {followup_record.followup_status}.'
            )

        if followup_record.runtime_open_item_id:
            await self.open_items_service.update_status(followup_record.runtime_open_item_id, 'COMPLETED')

        # Mark WITHDRAWN clarification as internally completed so user sees honest status
        if followup_record.linked_clarification_ref:
            try:
                await self.telegram_clarification_service.close_internal_for_withdrawn(
                    linked_case_id=followup_record.source_case_id,
                    closed_by=actor,
                    note=note,
                    source=source,
                )
            except ValueError:
                pass  # Clarification state mismatch: don't fail the completion

        updated = followup_record.model_copy(
            update={
                'followup_status': 'DOCUMENT_ANALYST_FOLLOWUP_COMPLETED',
                'no_further_telegram_action': True,
                'actor': actor,
                'note': (note or '').strip() or None,
                'updated_at': datetime.utcnow(),
            }
        )
        await self._log_followup_record(updated, source=source)
        return updated

    async def _request_data(
        self,
        *,
        followup_record: TelegramDocumentAnalystFollowupRecord,
        actor: str,
        note: str | None,
        question_text: str | None,
        source: str,
    ) -> TelegramDocumentAnalystFollowupRecord:
        if not followup_record.telegram_data_request_allowed:
            raise ValueError('Telegram-Datennachforderung ist fuer diesen Reviewpfad nicht erlaubt.')
        question = (question_text or '').strip()
        if not question:
            raise ValueError('Datennachforderung braucht eine konkrete Rueckfrage.')

        telegram_case_link = await self.telegram_case_link_service.get_by_case(followup_record.source_case_id)
        if telegram_case_link is None or not telegram_case_link.track_for_status:
            raise ValueError('Kein verknuepfter Telegram-Fall fuer Datennachforderung verfuegbar.')
        if not followup_record.runtime_open_item_id:
            raise ValueError('Kein Runtime-Open-Item fuer Telegram-Datennachforderung vorhanden.')

        runtime_open_item = await self._find_open_item(
            followup_record.runtime_case_id,
            followup_record.runtime_open_item_id,
        )
        cloned_link = telegram_case_link.model_copy(
            update={
                'open_item_id': followup_record.runtime_open_item_id,
                'open_item_title': runtime_open_item.get('title') or telegram_case_link.open_item_title,
            }
        )
        clarification = await self.telegram_clarification_service.request_clarification(
            linked_case_id=telegram_case_link.linked_case_id or followup_record.source_case_id,
            telegram_case_link=cloned_link,
            question_text=question,
            asked_by=actor,
            source=source,
        )
        updated = followup_record.model_copy(
            update={
                'followup_status': 'DOCUMENT_ANALYST_FOLLOWUP_DATA_REQUESTED',
                'followup_mode': 'REQUEST_DATA',
                'followup_reason': followup_record.followup_reason or 'Fehlende Daten werden konservativ beim Nutzer nachgefordert.',
                'linked_clarification_ref': clarification.clarification_ref,
                'linked_clarification_state': clarification.clarification_state,
                'data_request_question': question,
                'no_further_telegram_action': False,
                'actor': actor,
                'note': (note or '').strip() or None,
                'updated_at': datetime.utcnow(),
            }
        )
        await self._log_followup_record(updated, source=source)
        return updated

    async def _internal_only(
        self,
        *,
        followup_record: TelegramDocumentAnalystFollowupRecord,
        actor: str,
        note: str | None,
        source: str,
    ) -> TelegramDocumentAnalystFollowupRecord:
        if followup_record.runtime_open_item_id:
            await self.open_items_service.update_status(followup_record.runtime_open_item_id, 'OPEN')
        updated = followup_record.model_copy(
            update={
                'followup_status': 'DOCUMENT_ANALYST_FOLLOWUP_INTERNAL_ONLY',
                'followup_mode': 'INTERNAL_ONLY',
                'followup_reason': (note or '').strip() or followup_record.followup_reason or 'Interne Nachbearbeitung ist sinnvoller als weitere Telegram-Nachforderung.',
                'no_further_telegram_action': True,
                'actor': actor,
                'note': (note or '').strip() or None,
                'updated_at': datetime.utcnow(),
            }
        )
        await self._log_followup_record(updated, source=source)
        return updated

    async def _close_conservatively(
        self,
        *,
        followup_record: TelegramDocumentAnalystFollowupRecord,
        actor: str,
        note: str | None,
        source: str,
    ) -> TelegramDocumentAnalystFollowupRecord:
        if followup_record.runtime_open_item_id:
            await self.open_items_service.update_status(followup_record.runtime_open_item_id, 'COMPLETED')
        updated = followup_record.model_copy(
            update={
                'followup_status': 'DOCUMENT_ANALYST_FOLLOWUP_COMPLETED',
                'followup_mode': 'CLOSE_CONSERVATIVELY',
                'followup_reason': (note or '').strip() or followup_record.followup_reason or 'Weiterer Telegram- oder Analyseaufwand lohnt fuer diesen konservativen Schritt aktuell nicht.',
                'no_further_telegram_action': True,
                'actor': actor,
                'note': (note or '').strip() or None,
                'updated_at': datetime.utcnow(),
            }
        )
        await self._log_followup_record(updated, source=source)
        return updated

    def _build_required_record(
        self,
        review_record: TelegramDocumentAnalystReviewRecord,
    ) -> TelegramDocumentAnalystFollowupRecord:
        telegram_allowed, reason = self._followup_policy(review_record)
        return TelegramDocumentAnalystFollowupRecord(
            followup_ref=f'doc-followup:{review_record.review_ref}',
            review_ref=review_record.review_ref,
            document_analyst_start_ref=review_record.document_analyst_start_ref,
            document_analyst_context_ref=review_record.document_analyst_context_ref,
            source_case_id=review_record.source_case_id,
            target_case_id=review_record.target_case_id,
            telegram_document_ref=review_record.telegram_document_ref,
            telegram_media_ref=review_record.telegram_media_ref,
            document_intake_ref=review_record.document_intake_ref,
            runtime_case_id=review_record.runtime_case_id,
            runtime_output_status=review_record.runtime_output_status,
            runtime_open_item_id=review_record.runtime_open_item_id,
            runtime_problem_id=review_record.runtime_problem_id,
            followup_status='DOCUMENT_ANALYST_FOLLOWUP_REQUIRED',
            followup_mode=None,
            followup_reason=reason,
            telegram_data_request_allowed=telegram_allowed,
            # withdraw is allowed whenever a Telegram data request is possible
            telegram_data_request_withdraw_allowed=telegram_allowed,
            internal_resolution_allowed=True,
            # internal takeover is always allowed as conservative fallback
            internal_takeover_allowed=True,
            no_further_telegram_action=not telegram_allowed,
            actor=None,
            note=None,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )

    @staticmethod
    def _followup_policy(review_record: TelegramDocumentAnalystReviewRecord) -> tuple[bool, str]:
        next_step = (review_record.runtime_next_step or '').upper()
        if next_step == 'OCR_RECHECK':
            return (
                True,
                'Dokumentqualitaet oder OCR reicht nicht aus. Nutzer kann bessere Aufnahme oder fehlende Lesedaten liefern.',
            )
        if review_record.review_outcome == 'OUTPUT_INCOMPLETE':
            return (
                False,
                'Runtime-Output bleibt unvollstaendig. Interne Nachbearbeitung oder konservativer Abschluss pruefen.',
            )
        return (
            False,
            'Review blieb offen. Interne Nachbearbeitung oder konservativer Abschluss pruefen.',
        )

    async def _find_open_item(self, case_id: str, item_id: str) -> dict[str, Any]:
        items = await self.open_items_service.list_by_case(case_id)
        for item in items:
            if item.item_id == item_id:
                return item.model_dump(mode='json')
        return {}

    async def _log_followup_record(
        self,
        record: TelegramDocumentAnalystFollowupRecord,
        *,
        source: str,
    ) -> None:
        payload = record.model_dump(mode='json')
        await self._log_followup_event(record.source_case_id, record.followup_status, payload, source=source)
        if record.target_case_id != record.source_case_id:
            await self._log_followup_event(record.target_case_id, record.followup_status, payload, source=source)

    async def _log_followup_event(
        self,
        case_id: str,
        action: str,
        payload: dict[str, Any],
        *,
        source: str,
    ) -> None:
        await self.audit_service.log_event(
            {
                'event_id': str(uuid.uuid4()),
                'case_id': case_id,
                'source': source,
                'document_ref': payload.get('telegram_document_ref'),
                'agent_name': 'document-analyst',
                'approval_status': 'NOT_REQUIRED',
                'action': action,
                'result': payload.get('followup_ref') or action,
                'llm_output': payload,
            }
        )

    @staticmethod
    def _latest_review_payload(events: list[Any]) -> dict[str, Any] | None:
        for event in reversed(events):
            if getattr(event, 'action', None) not in {
                'DOCUMENT_ANALYST_REVIEW_READY',
                'DOCUMENT_ANALYST_REVIEW_COMPLETED',
                'DOCUMENT_ANALYST_REVIEW_STILL_OPEN',
            }:
                continue
            payload = TelegramDocumentAnalystFollowupService._normalize_payload(getattr(event, 'llm_output', None))
            if isinstance(payload, dict):
                return payload
        return None

    @staticmethod
    def _latest_followup_payload(events: list[Any]) -> dict[str, Any] | None:
        for event in reversed(events):
            if getattr(event, 'action', None) not in {
                'DOCUMENT_ANALYST_FOLLOWUP_REQUIRED',
                'DOCUMENT_ANALYST_FOLLOWUP_DATA_REQUESTED',
                'DOCUMENT_ANALYST_FOLLOWUP_WITHDRAWN',
                'DOCUMENT_ANALYST_FOLLOWUP_INTERNAL_ONLY',
                'DOCUMENT_ANALYST_FOLLOWUP_COMPLETED',
            }:
                continue
            payload = TelegramDocumentAnalystFollowupService._normalize_payload(getattr(event, 'llm_output', None))
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
