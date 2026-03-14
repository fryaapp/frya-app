"""Banking operator reconciliation review service.

V1.3 — Conservative operator review step after a read-only probe.
V1.4 — Manual handoff path (after CONFIRMED) + clarification path (after REJECTED/RETURNED).

Boundary contract:
- Reads audit + open items to validate state.
- Writes ONLY to audit log and open items table (Frya-internal).
- Never writes to Akaunting, never triggers a payment, never finalises.
- bank_write_executed is always False (asserted by caller).
- no_financial_write is always True.
"""
from __future__ import annotations

import uuid

from app.audit.service import AuditService
from app.banking.models import (
    BankClarificationInput,
    BankClarificationResult,
    BankManualHandoffDecision,
    BankManualHandoffInput,
    BankManualHandoffResult,
    BankReconciliationDecision,
    BankReconciliationReviewInput,
    BankReconciliationReviewResult,
)
from app.open_items.service import OpenItemsService

_REVIEW_VERSION = 'bank-reconciliation-review-v1.3'
_HANDOFF_VERSION = 'bank-manual-handoff-v1.4'
_CLARIF_VERSION = 'bank-clarification-v1.4'
_ACTIVE_STATUSES = {'OPEN', 'WAITING_USER', 'WAITING_DATA', 'SCHEDULED'}


class BankReconciliationReviewService:
    """Operator review step for bank transaction candidates.

    After a read-only probe surfaces a candidate, an operator can CONFIRM
    or REJECT it.  This service records that decision in the audit log and
    creates / updates open items accordingly.

    It does NOT connect the transaction in Akaunting, does NOT trigger any
    payment, and does NOT finalise anything.
    """

    def __init__(
        self,
        audit_service: AuditService,
        open_items_service: OpenItemsService,
    ) -> None:
        self.audit_service = audit_service
        self.open_items_service = open_items_service

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def submit_review(
        self,
        payload: BankReconciliationReviewInput,
    ) -> BankReconciliationReviewResult:
        """Record operator decision on a bank transaction candidate.

        CONFIRMED → open item marked COMPLETED; follow-up item for manual
                    handoff / external matching created as WAITING_DATA.
        REJECTED  → open item COMPLETED; follow-up clarification item OPEN.

        Safety: bank_write_executed is always False; no Akaunting write.
        """
        review_id = str(uuid.uuid4())
        audit_event_id = str(uuid.uuid4())
        case_id = payload.case_id

        # Close any existing open review item for this case
        existing_items = await self.open_items_service.list_by_case(case_id)
        review_item_id: str | None = None
        review_item_title: str | None = None
        for item in existing_items:
            if (
                item.status in _ACTIVE_STATUSES
                and 'BANK_RECONCILIATION_REVIEW' in item.title.upper()
            ):
                await self.open_items_service.update_status(item.item_id, 'COMPLETED')
                review_item_id = item.item_id
                review_item_title = item.title
                break

        # Determine outcome
        if payload.decision == BankReconciliationDecision.CONFIRMED:
            outcome_status = 'BANK_RECONCILIATION_CONFIRMED'
            follow_up_title = (
                f'[Banking] Manuelle Abstimmung erforderlich: '
                f'Transaktion {payload.transaction_id or "?"} bestätigt'
            )
            follow_up_description = (
                f'Operator hat Banktransaktion {payload.transaction_id} als passend bestätigt '
                f'(Score {payload.confidence_score}/100, {", ".join(payload.reason_codes)}). '
                f'Manuelle Abstimmung / Handoff im externen System ausstehend. '
                f'Entscheidungsnotiz: {payload.decision_note or "-"}. '
                f'Kein automatischer Write. Kein Payment.'
            )
            follow_up_status: str = 'WAITING_DATA'
            summary = (
                f'Operator hat Kandidat {payload.transaction_id} BESTÄTIGT. '
                f'Score={payload.confidence_score}/100, Qualität={payload.match_quality}. '
                f'Folge-Open-Item für manuellen Handoff erstellt. Kein Akaunting-Write.'
            )
        else:
            outcome_status = 'BANK_RECONCILIATION_REJECTED'
            follow_up_title = (
                f'[Banking] Klärung erforderlich: '
                f'Transaktion {payload.transaction_id or "?"} abgelehnt'
            )
            follow_up_description = (
                f'Operator hat Banktransaktion {payload.transaction_id} als nicht passend abgelehnt. '
                f'Score war {payload.confidence_score}/100 ({", ".join(payload.reason_codes)}). '
                f'Ablehnungsgrund: {payload.decision_note or "-"}. '
                f'Klärung mit Auftraggeber oder erneuter Abgleich erforderlich.'
            )
            follow_up_status = 'OPEN'
            summary = (
                f'Operator hat Kandidat {payload.transaction_id} ABGELEHNT. '
                f'Score={payload.confidence_score}/100, Qualität={payload.match_quality}. '
                f'Folge-Open-Item für Klärung erstellt.'
            )

        # Create follow-up open item (create_item always starts OPEN, then set status)
        follow_up_item = await self.open_items_service.create_item(
            case_id=case_id,
            title=follow_up_title,
            description=follow_up_description,
            source=_REVIEW_VERSION,
        )
        # Set the desired status after creation
        if follow_up_status != 'OPEN':
            await self.open_items_service.update_status(follow_up_item.item_id, follow_up_status)  # type: ignore[arg-type]

        # Audit log
        await self.audit_service.log_event({
            'event_id': audit_event_id,
            'case_id': case_id,
            'source': payload.source,
            'agent_name': _REVIEW_VERSION,
            'action': (
                'BANK_RECONCILIATION_CONFIRMED'
                if payload.decision == BankReconciliationDecision.CONFIRMED
                else 'BANK_RECONCILIATION_REJECTED'
            ),
            'approval_status': (
                'APPROVED' if payload.decision == BankReconciliationDecision.CONFIRMED
                else 'REJECTED'
            ),
            'result': outcome_status,
            'llm_output': {
                'review_id': review_id,
                'transaction_id': payload.transaction_id,
                'decision': payload.decision.value,
                'decision_note': payload.decision_note,
                'decided_by': payload.decided_by,
                'confidence_score': payload.confidence_score,
                'match_quality': payload.match_quality,
                'reason_codes': payload.reason_codes,
                'candidate_amount': payload.candidate_amount,
                'candidate_currency': payload.candidate_currency,
                'candidate_reference': payload.candidate_reference,
                'candidate_date': payload.candidate_date,
                'candidate_contact': payload.candidate_contact,
                'probe_result': payload.probe_result,
                'outcome_status': outcome_status,
                'follow_up_open_item_id': follow_up_item.item_id,
                'bank_write_executed': False,
                'no_financial_write': True,
            },
        })

        result = BankReconciliationReviewResult(
            review_id=review_id,
            case_id=case_id,
            transaction_id=payload.transaction_id,
            decision=payload.decision,
            outcome_status=outcome_status,
            decision_note=payload.decision_note,
            decided_by=payload.decided_by,
            open_item_id=review_item_id,
            open_item_title=review_item_title,
            follow_up_open_item_id=follow_up_item.item_id,
            follow_up_open_item_title=follow_up_title,
            audit_event_id=audit_event_id,
            summary=summary,
            bank_write_executed=False,
            no_financial_write=True,
        )

        return result

    # ------------------------------------------------------------------
    # Manual Handoff (after CONFIRMED)
    # ------------------------------------------------------------------

    async def complete_manual_handoff(
        self,
        payload: BankManualHandoffInput,
    ) -> BankManualHandoffResult:
        """Record outcome of a manual banking handoff attempt.

        COMPLETED → closes the WAITING_DATA follow-up item; case resolved.
        RETURNED  → closes the WAITING_DATA item; creates a new OPEN
                    clarification item so the operator knows action is needed.

        Safety: bank_write_executed is always False; no Akaunting write.
        """
        handoff_id = str(uuid.uuid4())
        audit_event_id = str(uuid.uuid4())
        case_id = payload.case_id

        # Close the WAITING_DATA follow-up item from the prior CONFIRMED review
        existing_items = await self.open_items_service.list_by_case(case_id)
        closed_item_id: str | None = None
        for item in existing_items:
            if (
                item.status in _ACTIVE_STATUSES
                and 'MANUELLE ABSTIMMUNG' in item.title.upper()
            ):
                await self.open_items_service.update_status(item.item_id, 'COMPLETED')
                closed_item_id = item.item_id
                break

        # Determine outcome
        follow_up_item_id: str | None = None
        follow_up_item_title: str | None = None

        if payload.decision == BankManualHandoffDecision.COMPLETED:
            outcome_status = 'BANK_MANUAL_HANDOFF_COMPLETED'
            audit_action = 'BANK_MANUAL_HANDOFF_COMPLETED'
            summary = (
                f'Manueller Handoff für Transaktion {payload.transaction_id} ABGESCHLOSSEN. '
                f'Keine weiteren Aktionen erforderlich. Kein Akaunting-Write.'
            )
        else:
            outcome_status = 'BANK_MANUAL_HANDOFF_RETURNED'
            audit_action = 'BANK_MANUAL_HANDOFF_RETURNED'
            # Create clarification follow-up
            clarif_title = (
                f'[Banking] Klärung nach Rückgabe: '
                f'Transaktion {payload.transaction_id or "?"}'
            )
            clarif_description = (
                f'Manueller Handoff für Transaktion {payload.transaction_id} wurde zurückgegeben. '
                f'Klärungshinweis: {payload.note or "-"}. '
                f'Kein automatischer Write. Kein Payment.'
            )
            clarif_item = await self.open_items_service.create_item(
                case_id=case_id,
                title=clarif_title,
                description=clarif_description,
                source=_HANDOFF_VERSION,
            )
            follow_up_item_id = clarif_item.item_id
            follow_up_item_title = clarif_title
            summary = (
                f'Manueller Handoff für Transaktion {payload.transaction_id} ZURÜCKGEGEBEN. '
                f'Klärung erforderlich. Folge-Open-Item erstellt. Kein Akaunting-Write.'
            )

        # Audit log
        await self.audit_service.log_event({
            'event_id': audit_event_id,
            'case_id': case_id,
            'source': payload.source,
            'agent_name': _HANDOFF_VERSION,
            'action': audit_action,
            'approval_status': (
                'APPROVED' if payload.decision == BankManualHandoffDecision.COMPLETED
                else 'REJECTED'
            ),
            'result': outcome_status,
            'llm_output': {
                'handoff_id': handoff_id,
                'transaction_id': payload.transaction_id,
                'decision': payload.decision.value,
                'note': payload.note,
                'decided_by': payload.decided_by,
                'closed_open_item_id': closed_item_id,
                'follow_up_open_item_id': follow_up_item_id,
                'outcome_status': outcome_status,
                'bank_write_executed': False,
                'no_financial_write': True,
            },
        })

        return BankManualHandoffResult(
            handoff_id=handoff_id,
            case_id=case_id,
            transaction_id=payload.transaction_id,
            decision=payload.decision,
            outcome_status=outcome_status,
            note=payload.note,
            decided_by=payload.decided_by,
            closed_open_item_id=closed_item_id,
            follow_up_open_item_id=follow_up_item_id,
            follow_up_open_item_title=follow_up_item_title,
            audit_event_id=audit_event_id,
            summary=summary,
            bank_write_executed=False,
            no_financial_write=True,
        )

    # ------------------------------------------------------------------
    # Clarification (after REJECTED or RETURNED)
    # ------------------------------------------------------------------

    async def complete_clarification(
        self,
        payload: BankClarificationInput,
    ) -> BankClarificationResult:
        """Record completion of a banking clarification step.

        Closes the open OPEN clarification item and logs the resolution.

        Safety: bank_write_executed is always False; no Akaunting write.
        """
        clarification_id = str(uuid.uuid4())
        audit_event_id = str(uuid.uuid4())
        case_id = payload.case_id

        # Close the open clarification item
        existing_items = await self.open_items_service.list_by_case(case_id)
        closed_item_id: str | None = None
        for item in existing_items:
            if item.status in _ACTIVE_STATUSES and (
                'KLÄRUNG' in item.title.upper()
                or 'KLARUNG' in item.title.upper()
                or 'KLAERUNG' in item.title.upper()
                or 'KLÄRUNG NACH RÜCKGABE' in item.title.upper()
            ):
                await self.open_items_service.update_status(item.item_id, 'COMPLETED')
                closed_item_id = item.item_id
                break

        outcome_status = 'BANK_CLARIFICATION_COMPLETED'
        summary = (
            f'Klärung für Transaktion {payload.transaction_id} ABGESCHLOSSEN. '
            f'Auflösungshinweis: {payload.resolution_note or "-"}. '
            f'Kein Akaunting-Write.'
        )

        # Audit log
        await self.audit_service.log_event({
            'event_id': audit_event_id,
            'case_id': case_id,
            'source': payload.source,
            'agent_name': _CLARIF_VERSION,
            'action': 'BANK_CLARIFICATION_COMPLETED',
            'approval_status': 'APPROVED',
            'result': outcome_status,
            'llm_output': {
                'clarification_id': clarification_id,
                'transaction_id': payload.transaction_id,
                'resolution_note': payload.resolution_note,
                'decided_by': payload.decided_by,
                'closed_open_item_id': closed_item_id,
                'outcome_status': outcome_status,
                'bank_write_executed': False,
                'no_financial_write': True,
            },
        })

        return BankClarificationResult(
            clarification_id=clarification_id,
            case_id=case_id,
            transaction_id=payload.transaction_id,
            outcome_status=outcome_status,
            resolution_note=payload.resolution_note,
            decided_by=payload.decided_by,
            closed_open_item_id=closed_item_id,
            audit_event_id=audit_event_id,
            summary=summary,
            bank_write_executed=False,
            no_financial_write=True,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def get_latest_review(self, case_id: str) -> dict | None:
        """Return the most recent BANK_RECONCILIATION_* audit event for this case.

        The llm_output (which may be stored as a JSON string) is parsed and
        merged into the top-level dict for easy consumption.
        """
        import json as _json
        chronology = await self.audit_service.by_case(case_id, limit=500)
        for event in reversed(chronology):
            action = getattr(event, 'action', '') or ''
            if action.startswith('BANK_RECONCILIATION_'):
                raw_output = getattr(event, 'llm_output', None)
                if isinstance(raw_output, str):
                    try:
                        raw_output = _json.loads(raw_output)
                    except Exception:
                        pass
                base = {
                    'action': action,
                    'result': getattr(event, 'result', None),
                    'created_at': str(getattr(event, 'created_at', '')),
                }
                if isinstance(raw_output, dict):
                    base.update(raw_output)
                else:
                    base['llm_output'] = raw_output
                return base
        return None
