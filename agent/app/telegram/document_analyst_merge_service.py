from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any

from app.audit.service import AuditService
from app.telegram.models import (
    TelegramDocumentAnalystMergeCandidateRecord,
    TelegramDocumentAnalystStartRecord,
)

_MERGE_THRESHOLD = 0.85


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


class TelegramDocumentAnalystMergeService:
    def __init__(self, audit_service: AuditService) -> None:
        self.audit_service = audit_service

    async def search_merge_candidate(
        self,
        start_record: TelegramDocumentAnalystStartRecord,
        *,
        document_analysis_payload: dict[str, Any] | None,
    ) -> TelegramDocumentAnalystMergeCandidateRecord | None:
        """Search other cases for a merge candidate. Never auto-merges — PROPOSE_ONLY."""
        if not document_analysis_payload:
            return None

        sender = (document_analysis_payload.get('sender') or {}).get('value')
        amounts = document_analysis_payload.get('amounts') or []
        amount: Any = None
        if amounts and isinstance(amounts[0], dict):
            amount = amounts[0].get('amount')
        doc_ref = start_record.telegram_document_ref

        if not sender:
            return None

        all_case_ids = await self.audit_service.case_ids(limit=200)
        this_case_id = start_record.source_case_id

        best_score = 0.0
        best_case_id: str | None = None
        best_reasons: list[str] = []

        for other_case_id in all_case_ids:
            if other_case_id == this_case_id:
                continue
            other_chronology = await self.audit_service.by_case(other_case_id, limit=500)
            other_analysis = self._latest_analysis_payload(other_chronology)
            if not other_analysis:
                continue
            score, reasons = self._calculate_confidence(
                sender=sender,
                amount=amount,
                doc_ref=doc_ref,
                other_payload=other_analysis,
            )
            if score > best_score:
                best_score = score
                best_case_id = other_case_id
                best_reasons = reasons

        if best_score < _MERGE_THRESHOLD or best_case_id is None:
            return None

        merge_ref = 'doc-merge:' + uuid.uuid4().hex[:12]
        record = TelegramDocumentAnalystMergeCandidateRecord(
            merge_ref=merge_ref,
            start_ref=start_record.start_ref,
            source_case_id=start_record.source_case_id,
            target_case_id=start_record.target_case_id,
            telegram_document_ref=start_record.telegram_document_ref,
            candidate_case_id=best_case_id,
            confidence_score=round(best_score, 2),
            match_reasons=best_reasons,
            merge_status='DOCUMENT_ANALYST_MERGE_CANDIDATE_FOUND',
        )
        await self._log_record(record)
        return record

    async def confirm_merge(
        self,
        case_id: str,
        *,
        actor: str,
        note: str | None,
    ) -> TelegramDocumentAnalystMergeCandidateRecord:
        chronology = await self.audit_service.by_case(case_id, limit=1000)
        payload = self._latest_merge_payload(chronology)
        if payload is None:
            raise ValueError('Kein Merge-Kandidat fuer diesen Fall vorhanden.')
        record = TelegramDocumentAnalystMergeCandidateRecord.model_validate(payload)
        if record.merge_status != 'DOCUMENT_ANALYST_MERGE_CANDIDATE_FOUND':
            raise ValueError(
                f'Merge kann nur aus MERGE_CANDIDATE_FOUND bestaetigt werden, '
                f'aktuell: {record.merge_status}.'
            )
        updated = record.model_copy(
            update={
                'merge_status': 'DOCUMENT_ANALYST_MERGE_CONFIRMED',
                'actor': actor,
                'note': note,
                'updated_at': datetime.utcnow(),
            }
        )
        await self._log_record(updated)
        return updated

    async def reject_merge(
        self,
        case_id: str,
        *,
        actor: str,
        note: str | None,
    ) -> TelegramDocumentAnalystMergeCandidateRecord:
        chronology = await self.audit_service.by_case(case_id, limit=1000)
        payload = self._latest_merge_payload(chronology)
        if payload is None:
            raise ValueError('Kein Merge-Kandidat fuer diesen Fall vorhanden.')
        record = TelegramDocumentAnalystMergeCandidateRecord.model_validate(payload)
        if record.merge_status != 'DOCUMENT_ANALYST_MERGE_CANDIDATE_FOUND':
            raise ValueError(
                f'Merge kann nur aus MERGE_CANDIDATE_FOUND abgelehnt werden, '
                f'aktuell: {record.merge_status}.'
            )
        updated = record.model_copy(
            update={
                'merge_status': 'DOCUMENT_ANALYST_MERGE_REJECTED',
                'actor': actor,
                'note': note,
                'updated_at': datetime.utcnow(),
            }
        )
        await self._log_record(updated)
        return updated

    @staticmethod
    def _calculate_confidence(
        *,
        sender: str,
        amount: Any,
        doc_ref: str,
        other_payload: dict[str, Any],
    ) -> tuple[float, list[str]]:
        score = 0.0
        reasons: list[str] = []

        other_sender = (other_payload.get('sender') or {}).get('value') or ''
        if sender and other_sender and sender.strip().lower() == other_sender.strip().lower():
            score += 0.5
            reasons.append(f'Sender stimmt ueberein: {sender!r}')

        other_amounts = other_payload.get('amounts') or []
        if amount is not None and other_amounts:
            for other_amt_obj in other_amounts:
                if not isinstance(other_amt_obj, dict):
                    continue
                other_amt = other_amt_obj.get('amount')
                if other_amt is None:
                    continue
                try:
                    a1 = float(amount)
                    a2 = float(other_amt)
                    if a1 > 0 and abs(a1 - a2) / a1 <= 0.01:
                        score += 0.35
                        reasons.append(f'Betrag stimmt ueberein: {a1}')
                        break
                except (TypeError, ValueError, ZeroDivisionError):
                    pass

        other_doc_ref = (other_payload.get('document_ref') or '').lower()
        if doc_ref and other_doc_ref and (
            doc_ref.lower() in other_doc_ref or other_doc_ref in doc_ref.lower()
        ):
            score += 0.15
            reasons.append(f'Dokumentreferenz aehnlich: {doc_ref!r}')

        return score, reasons

    async def _log_record(self, record: TelegramDocumentAnalystMergeCandidateRecord) -> None:
        payload = record.model_dump(mode='json')
        await self.audit_service.log_event({
            'event_id': str(uuid.uuid4()),
            'case_id': record.source_case_id,
            'source': 'telegram',
            'document_ref': record.telegram_document_ref,
            'agent_name': 'document-analyst',
            'approval_status': 'NOT_REQUIRED',
            'action': record.merge_status,
            'result': record.merge_ref,
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
                'action': record.merge_status,
                'result': record.merge_ref,
                'llm_output': payload,
            })

    @staticmethod
    def _latest_analysis_payload(events: list[Any]) -> dict[str, Any] | None:
        for event in reversed(events):
            if getattr(event, 'action', None) != 'DOCUMENT_ANALYSIS_COMPLETED':
                continue
            payload = _normalize(getattr(event, 'llm_output', None))
            if isinstance(payload, dict):
                return payload
        return None

    @staticmethod
    def _latest_merge_payload(events: list[Any]) -> dict[str, Any] | None:
        for event in reversed(events):
            if getattr(event, 'action', None) not in {
                'DOCUMENT_ANALYST_MERGE_CANDIDATE_FOUND',
                'DOCUMENT_ANALYST_MERGE_CONFIRMED',
                'DOCUMENT_ANALYST_MERGE_REJECTED',
            }:
                continue
            payload = _normalize(getattr(event, 'llm_output', None))
            if isinstance(payload, dict):
                return payload
        return None
