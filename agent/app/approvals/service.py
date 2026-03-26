from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from app.approvals.models import ApprovalRecord
from app.approvals.repository import ApprovalRepository
from app.audit.service import AuditService

if TYPE_CHECKING:
    from app.open_items.service import OpenItemsService


_DECISION_ALIASES: dict[str, str] = {
    'APPROVED': 'APPROVED',
    'APPROVE': 'APPROVED',
    'FREIGEBEN': 'APPROVED',
    'GENEHMIGEN': 'APPROVED',
    'REJECTED': 'REJECTED',
    'REJECT': 'REJECTED',
    'ABLEHNEN': 'REJECTED',
    'DENY': 'REJECTED',
    'CANCELLED': 'CANCELLED',
    'CANCEL': 'CANCELLED',
    'ABBRECHEN': 'CANCELLED',
    'REVOKED': 'REVOKED',
    'REVOKE': 'REVOKED',
    'WIDERRUFEN': 'REVOKED',
    'EXPIRED': 'EXPIRED',
    'EXPIRE': 'EXPIRED',
    'ABGELAUFEN': 'EXPIRED',
}

_OPEN_ITEM_TARGET_BY_DECISION: dict[str, str] = {
    'APPROVED': 'COMPLETED',
    'REJECTED': 'OPEN',
    'CANCELLED': 'CANCELLED',
    'REVOKED': 'CANCELLED',
    'EXPIRED': 'WAITING_USER',
}

_ACTIVE_OPEN_ITEM_STATUSES = {'OPEN', 'WAITING_USER', 'WAITING_DATA', 'SCHEDULED', 'PENDING_APPROVAL'}
_ALLOWED_STATUS_TRANSITIONS: dict[str, set[str]] = {
    'PENDING': {'APPROVED', 'REJECTED', 'CANCELLED', 'EXPIRED', 'REVOKED'},
    'APPROVED': {'REVOKED'},
}


class ApprovalService:
    def __init__(
        self,
        repository: ApprovalRepository,
        open_items_service: OpenItemsService | None = None,
        audit_service: AuditService | None = None,
    ) -> None:
        self.repository = repository
        self.open_items_service = open_items_service
        self.audit_service = audit_service

    async def initialize(self) -> None:
        await self.repository.setup()

    @staticmethod
    def _utcnow() -> datetime:
        return datetime.utcnow()

    @staticmethod
    def _as_utc_naive(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    async def _log_audit(
        self,
        *,
        action: str,
        record: ApprovalRecord,
        source: str,
        result: str,
        llm_input: dict[str, Any] | None = None,
        llm_output: dict[str, Any] | None = None,
    ) -> None:
        if self.audit_service is None:
            return

        await self.audit_service.log_event(
            {
                'event_id': str(uuid.uuid4()),
                'case_id': record.case_id,
                'source': source,
                'agent_name': 'frya-approval-service',
                'approval_status': record.status,
                'action': action,
                'result': result,
                'llm_input': llm_input,
                'llm_output': llm_output,
                'policy_refs': record.policy_refs,
            }
        )

    async def _ensure_pending_open_item(
        self,
        *,
        case_id: str,
        action_type: str,
        reason: str | None,
        open_item_id: str | None,
    ) -> str | None:
        if open_item_id:
            return open_item_id
        if self.open_items_service is None:
            return None

        title = f'Freigabe ausstehend: {action_type}'
        description = reason or 'Freigabe erforderlich.'
        existing = await self.open_items_service.list_by_case(case_id)
        for item in existing:
            if item.title == title and item.status in _ACTIVE_OPEN_ITEM_STATUSES:
                if item.status != 'WAITING_USER':
                    await self.open_items_service.update_status(item.item_id, 'WAITING_USER')  # type: ignore[arg-type]
                return item.item_id

        created = await self.open_items_service.create_item(
            case_id=case_id,
            title=title,
            description=description,
            source='approval_service',
        )
        await self.open_items_service.update_status(created.item_id, 'WAITING_USER')  # type: ignore[arg-type]
        return created.item_id

    async def _expire_if_needed(self, record: ApprovalRecord | None, *, source: str = 'approval_service') -> ApprovalRecord | None:
        if record is None or record.status != 'PENDING':
            return record

        expires_at = self._as_utc_naive(record.expires_at)
        if expires_at is None or expires_at > self._utcnow():
            return record

        updated = record.model_copy(
            update={
                'status': 'EXPIRED',
                'decided_by': 'system',
                'decided_at': self._utcnow(),
                'reason': record.reason or 'Approval expired',
            }
        )
        await self.repository.upsert(updated)
        await self._sync_open_item_after_decision(updated)
        await self._log_audit(
            action='APPROVAL_STATUS_CHANGED',
            record=updated,
            source=source,
            result=f'approval_id={updated.approval_id};action={updated.action_type};from=PENDING;to=EXPIRED;reason={updated.reason or "-"}',
            llm_output={
                'approval_id': updated.approval_id,
                'action_type': updated.action_type,
                'status': updated.status,
                'required_mode': updated.required_mode,
                'open_item_id': updated.open_item_id,
            },
        )
        return updated

    async def request_approval(
        self,
        case_id: str,
        action_type: str,
        requested_by: str,
        scope_ref: str | None = None,
        reason: str | None = None,
        policy_refs: list[dict[str, Any]] | None = None,
        audit_event_id: str | None = None,
        required_mode: str = 'REQUIRE_USER_APPROVAL',
        approval_context: dict[str, Any] | None = None,
        expires_at: datetime | None = None,
        open_item_id: str | None = None,
        source: str = 'approval_service',
    ) -> ApprovalRecord:
        existing = await self.repository.find_pending(case_id=case_id, action_type=action_type, scope_ref=scope_ref)
        existing = await self._expire_if_needed(existing, source=source)
        if existing is not None:
            if existing.open_item_id is None:
                linked_open_item_id = await self._ensure_pending_open_item(
                    case_id=case_id,
                    action_type=action_type,
                    reason=reason,
                    open_item_id=None,
                )
                if linked_open_item_id:
                    existing = existing.model_copy(update={'open_item_id': linked_open_item_id})
                    await self.repository.upsert(existing)
            return existing

        linked_open_item_id = await self._ensure_pending_open_item(
            case_id=case_id,
            action_type=action_type,
            reason=reason,
            open_item_id=open_item_id,
        )

        record = ApprovalRecord(
            approval_id=str(uuid.uuid4()),
            case_id=case_id,
            action_type=action_type,
            scope_ref=scope_ref,
            required_mode=required_mode,
            approval_context=approval_context or {},
            status='PENDING',
            requested_by=requested_by,
            requested_at=self._utcnow(),
            expires_at=expires_at,
            open_item_id=linked_open_item_id,
            reason=reason,
            policy_refs=policy_refs or [],
            audit_event_id=audit_event_id,
        )
        await self.repository.upsert(record)
        await self._log_audit(
            action='APPROVAL_REQUESTED',
            record=record,
            source=source,
            result=(
                f'approval_id={record.approval_id};action={record.action_type};mode={record.required_mode};'
                f'status={record.status};open_item_id={record.open_item_id or "-"};reason={record.reason or "-"}'
            ),
            llm_input={
                'case_id': case_id,
                'action_type': action_type,
                'requested_by': requested_by,
                'scope_ref': scope_ref,
                'expires_at': expires_at.isoformat() if expires_at else None,
            },
            llm_output={
                'approval_id': record.approval_id,
                'required_mode': record.required_mode,
                'approval_context': record.approval_context,
                'open_item_id': record.open_item_id,
            },
        )
        return record

    def _normalize_decision(self, decision: str) -> str:
        mapped = _DECISION_ALIASES.get((decision or '').strip().upper())
        if mapped is None:
            raise ValueError('Ungueltige Entscheidung')
        return mapped

    async def _sync_open_item_after_decision(self, record: ApprovalRecord) -> None:
        if self.open_items_service is None:
            return
        if not record.open_item_id:
            return

        target_status = _OPEN_ITEM_TARGET_BY_DECISION.get(record.status)
        if not target_status:
            return

        await self.open_items_service.update_status(record.open_item_id, target_status)  # type: ignore[arg-type]

    async def decide_approval(
        self,
        approval_id: str,
        decision: str,
        decided_by: str,
        reason: str | None = None,
        source: str = 'approval_service',
    ) -> ApprovalRecord | None:
        current = await self.get(approval_id)
        if current is None:
            return None

        mapped = self._normalize_decision(decision)
        allowed_targets = _ALLOWED_STATUS_TRANSITIONS.get(current.status, set())
        if mapped not in allowed_targets:
            raise ValueError(f'Statusuebergang {current.status} -> {mapped} nicht zulaessig')

        updated = current.model_copy(
            update={
                'status': mapped,
                'decided_by': decided_by,
                'decided_at': self._utcnow(),
                'reason': reason or current.reason,
            }
        )
        await self.repository.upsert(updated)
        await self._sync_open_item_after_decision(updated)
        await self._log_audit(
            action='APPROVAL_STATUS_CHANGED',
            record=updated,
            source=source,
            result=(
                f'approval_id={updated.approval_id};action={updated.action_type};from={current.status};to={updated.status};'
                f'decided_by={decided_by};reason={updated.reason or "-"}'
            ),
            llm_input={
                'decision': decision,
                'decided_by': decided_by,
                'reason': reason,
            },
            llm_output={
                'approval_id': updated.approval_id,
                'status': updated.status,
                'required_mode': updated.required_mode,
                'open_item_id': updated.open_item_id,
            },
        )
        return updated

    async def attach_open_item(self, approval_id: str, open_item_id: str) -> ApprovalRecord | None:
        current = await self.repository.get(approval_id)
        if current is None:
            return None
        updated = current.model_copy(update={'open_item_id': open_item_id})
        await self.repository.upsert(updated)
        return updated

    async def get(self, approval_id: str) -> ApprovalRecord | None:
        record = await self.repository.get(approval_id)
        return await self._expire_if_needed(record)

    async def list_by_case(self, case_id: str, limit: int = 200) -> list[ApprovalRecord]:
        entries = list(await self.repository.list_by_case(case_id=case_id, limit=limit))
        resolved: list[ApprovalRecord] = []
        for entry in entries:
            current = await self._expire_if_needed(entry)
            if current is not None:
                resolved.append(current)
        return resolved

    async def recent(self, limit: int = 200) -> list[ApprovalRecord]:
        entries = list(await self.repository.list_recent(limit=limit))
        resolved: list[ApprovalRecord] = []
        for entry in entries:
            current = await self._expire_if_needed(entry)
            if current is not None:
                resolved.append(current)
        return resolved
