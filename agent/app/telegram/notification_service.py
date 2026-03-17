from __future__ import annotations

import json
import uuid
from datetime import datetime

from app.audit.service import AuditService
from app.connectors.contracts import NotificationMessage
from app.connectors.notifications_telegram import TelegramConnector
from app.telegram.models import TelegramNotificationRecord
from app.telegram.service import TelegramCaseLinkService


class TelegramNotificationService:
    def __init__(
        self,
        audit_service: AuditService,
        telegram_case_link_service: TelegramCaseLinkService,
        telegram_connector: TelegramConnector,
    ) -> None:
        self.audit_service = audit_service
        self.telegram_case_link_service = telegram_case_link_service
        self.telegram_connector = telegram_connector

    async def send_case_notification(
        self,
        linked_case_id: str,
        notification_type: str,
        trigger_action: str,
        message_text: str,
        source: str,
        linked_open_item_id: str | None = None,
    ) -> TelegramNotificationRecord:
        latest_link = await self.telegram_case_link_service.latest_trackable_for_linked_case(linked_case_id)
        notification_key = f'{linked_case_id}:{notification_type}:{trigger_action}'
        existing = await self._existing_notification(linked_case_id, notification_key)
        if existing is not None:
            return existing

        record = TelegramNotificationRecord(
            notification_ref=str(uuid.uuid4()),
            linked_case_id=linked_case_id,
            telegram_chat_ref=latest_link.telegram_chat_ref if latest_link else None,
            telegram_case_ref=latest_link.case_id if latest_link else None,
            telegram_case_link_id=latest_link.link_id if latest_link else None,
            notification_type=notification_type,
            notification_key=notification_key,
            trigger_action=trigger_action,
            message_text=message_text,
            state='NOTIFICATION_ELIGIBLE',
            linked_open_item_id=linked_open_item_id or (latest_link.open_item_id if latest_link else None),
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        await self.audit_service.log_event(
            {
                'event_id': str(uuid.uuid4()),
                'case_id': linked_case_id,
                'source': source,
                'agent_name': 'frya-orchestrator',
                'approval_status': 'NOT_REQUIRED',
                'action': 'TELEGRAM_NOTIFICATION_ELIGIBLE',
                'result': notification_type,
                'llm_output': record.model_dump(mode='json'),
            }
        )

        if latest_link is None:
            skipped = record.model_copy(
                update={
                    'state': 'NOTIFICATION_SKIPPED',
                    'delivery_state': 'SKIPPED',
                    'delivery_reason': 'no_trackable_case_link',
                    'updated_at': datetime.utcnow(),
                }
            )
            await self._log_notification_result(source, skipped)
            return skipped

        reply = await self.telegram_connector.send(
            NotificationMessage(
                target=latest_link.telegram_chat_ref.replace('tg-chat:', ''),
                text=message_text,
                metadata={
                    'case_id': linked_case_id,
                    'notification_type': notification_type,
                    'trigger_action': trigger_action,
                },
            ),
            disable_notification=False,
        )
        state, delivery_state, delivery_reason, sent_message_id = self._delivery_result(reply)
        final = record.model_copy(
            update={
                'state': state,
                'delivery_state': delivery_state,
                'delivery_reason': delivery_reason,
                'sent_message_id': sent_message_id,
                'updated_at': datetime.utcnow(),
            }
        )
        await self._log_notification_result(source, final)
        return final

    async def _existing_notification(
        self,
        linked_case_id: str,
        notification_key: str,
    ) -> TelegramNotificationRecord | None:
        chronology = await self.audit_service.by_case(linked_case_id, limit=300)
        for event in reversed(chronology):
            if event.action not in {
                'TELEGRAM_NOTIFICATION_SENT',
                'TELEGRAM_NOTIFICATION_SKIPPED',
                'TELEGRAM_NOTIFICATION_FAILED',
            }:
                continue
            payload = self._normalize_payload(getattr(event, 'llm_output', None))
            if not isinstance(payload, dict):
                continue
            if payload.get('notification_key') != notification_key:
                continue
            return TelegramNotificationRecord(**payload)
        return None

    async def _log_notification_result(self, source: str, record: TelegramNotificationRecord) -> None:
        action = {
            'NOTIFICATION_SENT': 'TELEGRAM_NOTIFICATION_SENT',
            'NOTIFICATION_SKIPPED': 'TELEGRAM_NOTIFICATION_SKIPPED',
            'NOTIFICATION_FAILED': 'TELEGRAM_NOTIFICATION_FAILED',
        }[record.state]
        await self.audit_service.log_event(
            {
                'event_id': str(uuid.uuid4()),
                'case_id': record.linked_case_id,
                'source': source,
                'agent_name': 'frya-orchestrator',
                'approval_status': 'NOT_REQUIRED',
                'action': action,
                'result': record.notification_type,
                'llm_output': record.model_dump(mode='json'),
            }
        )

    @staticmethod
    def _normalize_payload(payload: object) -> object:
        if isinstance(payload, str):
            try:
                return json.loads(payload)
            except Exception:
                return payload
        return payload

    @staticmethod
    def _delivery_result(reply: dict) -> tuple[str, str, str | None, int | None]:
        reason = reply.get('reason')
        sent_message_id = None
        body = reply.get('body')
        if isinstance(body, str):
            try:
                payload = json.loads(body)
            except Exception:
                payload = None
            if isinstance(payload, dict):
                sent_message_id = ((payload.get('result') or {}).get('message_id'))
        if bool(reply.get('ok', False)):
            return 'NOTIFICATION_SENT', 'SENT', reason, sent_message_id
        if reason == 'telegram_bot_token_missing':
            return 'NOTIFICATION_SKIPPED', 'SKIPPED', reason, sent_message_id
        return 'NOTIFICATION_FAILED', 'FAILED', reason, sent_message_id
