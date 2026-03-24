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

import logging
import uuid

from app.audit.service import AuditService

logger = logging.getLogger(__name__)
from app.banking.models import (
    BankClarificationInput,
    BankClarificationResult,
    BankingClarificationCompletionInput,
    BankingClarificationCompletionResult,
    ExternalBankingProcessCompletionInput,
    ExternalBankingProcessCompletionResult,
    ExternalBankingProcessDecision,
    BankingHandoffReadyInput,
    BankingHandoffReadyResult,
    BankingHandoffResolutionDecision,
    BankingHandoffResolutionInput,
    BankingHandoffResolutionResult,
    BankManualHandoffDecision,
    BankManualHandoffInput,
    BankManualHandoffResult,
    BankReconciliationDecision,
    BankReconciliationReviewInput,
    BankReconciliationReviewResult,
    ReconciliationContext,
)
from app.banking.reconciliation_context import ReconciliationContextService
from app.open_items.service import OpenItemsService

_REVIEW_VERSION = 'bank-reconciliation-review-v1.6'
_HANDOFF_VERSION = 'banking-handoff-v1.0'
_CLARIF_VERSION = 'bank-clarification-v1.5'
_EXTERNAL_VERSION = 'external-banking-process-v1.0'
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
        reconciliation_context_service: ReconciliationContextService,
    ) -> None:
        self.audit_service = audit_service
        self.open_items_service = open_items_service
        self.reconciliation_context_service = reconciliation_context_service

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
        context = await self.reconciliation_context_service.build(case_id=case_id)
        if payload.workbench_ref != context.review_anchor_ref:
            raise ValueError(
                'Workbench-Stand passt nicht mehr zum aktuellen Reconciliation Context. '
                'Review nur auf aktuellem Workbench-Stand zulässig.'
            )

        candidate, candidate_rank = self._select_candidate(context, payload.transaction_id)
        if payload.decision == BankReconciliationDecision.CONFIRMED and not context.confirm_allowed:
            raise ValueError(
                f'Confirm ist fuer diesen Workbench-Stand nicht erlaubt: {context.operator_guidance}'
            )

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
            flow_label = 'Expense' if context.doc_type == 'expense' else 'Income'
            follow_up_title = (
                f'[Banking] Manuellen Handoff vorbereiten: '
                f'{flow_label}-Kandidat {candidate.transaction_id if candidate else payload.transaction_id or "?"} bestaetigt'
            )
            follow_up_description = (
                f'Workbench-basiertes Review bestaetigt Kandidat {candidate.transaction_id if candidate else payload.transaction_id}. '
                f'Workbench={context.review_anchor_ref}, Signal={context.match_signal.value}, '
                f'Guidance={context.review_guidance.value}. '
                f'Reasons: {", ".join(candidate.reason_codes if candidate else payload.reason_codes)}. '
                f'Manuelle Abstimmung / Handoff im externen System ausstehend. '
                f'Entscheidungsnotiz: {payload.decision_note or "-"}. '
                f'Kein automatischer Write. Kein Payment.'
            )
            follow_up_status: str = 'WAITING_DATA'
            summary = (
                f'Operator hat Kandidat {candidate.transaction_id if candidate else payload.transaction_id} BESTAETIGT. '
                f'Workbench={context.review_anchor_ref}, Signal={context.match_signal.value}. '
                f'Folge-Open-Item für manuellen Handoff erstellt. Kein Akaunting-Write.'
            )
        else:
            outcome_status = 'BANK_RECONCILIATION_REJECTED'
            follow_up_title = self._rejected_follow_up_title(context, candidate, payload)
            follow_up_description = (
                f'Workbench-basiertes Review lehnt Kandidat {candidate.transaction_id if candidate else payload.transaction_id} ab. '
                f'Workbench={context.review_anchor_ref}, Signal={context.match_signal.value}, '
                f'Guidance={context.review_guidance.value}. '
                f'Reasons: {", ".join(candidate.reason_codes if candidate else payload.reason_codes)}. '
                f'Ablehnungsgrund: {payload.decision_note or "-"}. '
                f'Klärung mit Auftraggeber oder erneuter Abgleich erforderlich.'
            )
            follow_up_status = 'OPEN'
            summary = (
                f'Operator hat Kandidat {candidate.transaction_id if candidate else payload.transaction_id} ABGELEHNT. '
                f'Workbench={context.review_anchor_ref}, Signal={context.match_signal.value}. '
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
                'transaction_id': candidate.transaction_id if candidate else payload.transaction_id,
                'decision': payload.decision.value,
                'decision_note': payload.decision_note,
                'decided_by': payload.decided_by,
                'workbench_ref': context.review_anchor_ref,
                'workbench_signal': context.match_signal.value,
                'workbench_guidance': context.operator_guidance,
                'review_guidance': context.review_guidance.value,
                'confirm_allowed': context.confirm_allowed,
                'candidate_rank': candidate_rank,
                'confidence_score': candidate.confidence_score if candidate else payload.confidence_score,
                'match_quality': candidate.match_quality.value if candidate else payload.match_quality,
                'reason_codes': candidate.reason_codes if candidate else payload.reason_codes,
                'candidate_amount': candidate.amount if candidate else payload.candidate_amount,
                'candidate_currency': candidate.currency if candidate else payload.candidate_currency,
                'candidate_reference': candidate.reference if candidate else payload.candidate_reference,
                'candidate_date': candidate.date if candidate else payload.candidate_date,
                'candidate_contact': candidate.contact_name if candidate else payload.candidate_contact,
                'tx_type': candidate.tx_type if candidate else payload.tx_type,
                'probe_result': payload.probe_result,
                'probe_note': payload.probe_note,
                'outcome_status': outcome_status,
                'follow_up_open_item_id': follow_up_item.item_id,
                'bank_write_executed': False,
                'no_financial_write': True,
            },
        })

        result = BankReconciliationReviewResult(
            review_id=review_id,
            case_id=case_id,
            transaction_id=candidate.transaction_id if candidate else payload.transaction_id,
            workbench_ref=context.review_anchor_ref,
            workbench_signal=context.match_signal.value,
            decision=payload.decision,
            outcome_status=outcome_status,
            decision_note=payload.decision_note,
            decided_by=payload.decided_by,
            review_guidance=context.review_guidance.value,
            confirm_allowed=context.confirm_allowed,
            candidate_rank=candidate_rank,
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

    async def mark_handoff_ready(
        self,
        payload: BankingHandoffReadyInput,
    ) -> BankingHandoffReadyResult:
        """Create an explicit operator handoff state after a confirmed review."""
        handoff_id = str(uuid.uuid4())
        audit_event_id = str(uuid.uuid4())
        case_id = payload.case_id
        chronology = list(await self.audit_service.by_case(case_id, limit=500))
        latest_review = self._latest_payload_from_actions(
            chronology,
            {'BANK_RECONCILIATION_CONFIRMED', 'BANK_RECONCILIATION_REJECTED'},
        )
        latest_ready = self._latest_payload_from_actions(chronology, {'BANKING_HANDOFF_READY'})
        latest_resolution = self._latest_payload_from_actions(
            chronology,
            {'BANKING_HANDOFF_COMPLETED', 'BANKING_HANDOFF_RETURNED'},
        )
        if not latest_review or latest_review.get('action') != 'BANK_RECONCILIATION_CONFIRMED':
            raise ValueError('Handoff nur nach bestaetigtem Banking-Review zulaessig.')
        if payload.review_ref != latest_review.get('review_id'):
            raise ValueError('Review-Ref passt nicht zum letzten bestaetigten Banking-Review.')
        if payload.workbench_ref != latest_review.get('workbench_ref'):
            raise ValueError('Workbench-Ref passt nicht zum bestaetigten Review-Kontext.')
        if latest_resolution and latest_resolution.get('review_ref') == payload.review_ref:
            raise ValueError('Dieser Handoff wurde bereits abgeschlossen oder zurueckgegeben.')
        if latest_ready and latest_ready.get('review_ref') == payload.review_ref:
            raise ValueError('Fuer diesen Review existiert bereits ein offener Handoff-Stand.')

        existing_items = await self.open_items_service.list_by_case(case_id)
        closed_item_id: str | None = None
        closed_item_title: str | None = None
        review_follow_up_id = latest_review.get('follow_up_open_item_id')
        for item in existing_items:
            if item.status not in _ACTIVE_STATUSES:
                continue
            if review_follow_up_id and item.item_id == review_follow_up_id:
                await self.open_items_service.update_status(item.item_id, 'COMPLETED')
                closed_item_id = item.item_id
                closed_item_title = item.title
                break
            if (
                not review_follow_up_id
                and 'HANDOFF VORBEREITEN' in item.title.upper()
            ):
                await self.open_items_service.update_status(item.item_id, 'COMPLETED')
                closed_item_id = item.item_id
                closed_item_title = item.title
                break

        transaction_id = payload.transaction_id or latest_review.get('transaction_id')
        candidate_reference = latest_review.get('candidate_reference')
        tx_type = latest_review.get('tx_type') or 'unknown'
        flow_label = 'Expense' if tx_type == 'expense' else 'Income'
        handoff_guidance = (
            'Bestaetigten Kandidaten ausserhalb Frya manuell weitergeben und die manuelle Uebernahme dokumentieren.'
        )
        next_manual_step = 'Manuelle Weitergabe im Banking-/Accounting-Prozess bestaetigen oder Rueckgabe dokumentieren.'
        required_external_action = (
            'Kein Write durch Frya. Externe manuelle Abstimmung oder Uebernahme im Zielprozess dokumentieren.'
        )
        handoff_title = (
            f'[Banking] Manuellen Handoff durchfuehren: '
            f'{flow_label}-Kandidat {transaction_id or "?"}'
        )
        handoff_description = (
            f'Bestaetigtes Banking-Review {payload.review_ref} mit Workbench {payload.workbench_ref}. '
            f'Transaktion {transaction_id or "?"}, Referenz {candidate_reference or "-"}. '
            f'Hinweis: {payload.handoff_note or "-"}. '
            f'{required_external_action}'
        )
        handoff_item = await self.open_items_service.create_item(
            case_id=case_id,
            title=handoff_title,
            description=handoff_description,
            source=_HANDOFF_VERSION,
        )

        await self.audit_service.log_event({
            'event_id': audit_event_id,
            'case_id': case_id,
            'source': payload.source,
            'agent_name': _HANDOFF_VERSION,
            'action': 'BANKING_HANDOFF_READY',
            'approval_status': 'APPROVED',
            'result': 'BANKING_HANDOFF_READY',
            'llm_output': {
                'handoff_id': handoff_id,
                'review_ref': payload.review_ref,
                'workbench_ref': payload.workbench_ref,
                'transaction_id': transaction_id,
                'candidate_reference': candidate_reference,
                'handoff_state': 'READY',
                'handoff_note': payload.handoff_note,
                'handed_off_by': payload.handed_off_by,
                'handoff_guidance': handoff_guidance,
                'next_manual_step': next_manual_step,
                'required_external_action': required_external_action,
                'closed_open_item_id': closed_item_id,
                'closed_open_item_title': closed_item_title,
                'handoff_open_item_id': handoff_item.item_id,
                'handoff_open_item_title': handoff_title,
                'bank_write_executed': False,
                'no_financial_write': True,
            },
        })

        return BankingHandoffReadyResult(
            handoff_id=handoff_id,
            case_id=case_id,
            review_ref=payload.review_ref,
            workbench_ref=payload.workbench_ref,
            transaction_id=transaction_id,
            candidate_reference=candidate_reference,
            handoff_note=payload.handoff_note,
            handed_off_by=payload.handed_off_by,
            handoff_guidance=handoff_guidance,
            next_manual_step=next_manual_step,
            required_external_action=required_external_action,
            closed_open_item_id=closed_item_id,
            closed_open_item_title=closed_item_title,
            handoff_open_item_id=handoff_item.item_id,
            handoff_open_item_title=handoff_title,
            audit_event_id=audit_event_id,
            summary=(
                f'Handoff fuer Review {payload.review_ref} ist bereit. '
                f'Transaktion {transaction_id or "?"} wurde zur manuellen Weitergabe uebergeben.'
            ),
            bank_write_executed=False,
            no_financial_write=True,
        )

    async def resolve_handoff(
        self,
        payload: BankingHandoffResolutionInput,
    ) -> BankingHandoffResolutionResult:
        """Resolve an explicit banking handoff that is already READY."""
        resolution_id = str(uuid.uuid4())
        audit_event_id = str(uuid.uuid4())
        case_id = payload.case_id
        chronology = list(await self.audit_service.by_case(case_id, limit=500))
        latest_ready = self._latest_payload_from_actions(chronology, {'BANKING_HANDOFF_READY'})
        latest_resolution = self._latest_payload_from_actions(
            chronology,
            {'BANKING_HANDOFF_COMPLETED', 'BANKING_HANDOFF_RETURNED'},
        )
        if not latest_ready:
            raise ValueError('Kein offener Banking-Handoff vorhanden.')
        if payload.handoff_ref != latest_ready.get('handoff_id'):
            raise ValueError('Handoff-Ref passt nicht zum aktuellen Banking-Handoff.')
        if latest_resolution and latest_resolution.get('handoff_ref') == payload.handoff_ref:
            raise ValueError('Dieser Banking-Handoff wurde bereits abgeschlossen.')

        existing_items = await self.open_items_service.list_by_case(case_id)
        handoff_open_item_id = latest_ready.get('handoff_open_item_id')
        handoff_open_item_title = latest_ready.get('handoff_open_item_title')
        closed_item_id: str | None = None
        for item in existing_items:
            if item.status not in _ACTIVE_STATUSES:
                continue
            if handoff_open_item_id and item.item_id == handoff_open_item_id:
                await self.open_items_service.update_status(item.item_id, 'COMPLETED')
                closed_item_id = item.item_id
                handoff_open_item_title = item.title
                break

        follow_up_item_id: str | None = None
        follow_up_item_title: str | None = None
        outside_process_open_item_id: str | None = None
        outside_process_open_item_title: str | None = None
        if payload.decision == BankingHandoffResolutionDecision.COMPLETED:
            status = 'BANKING_HANDOFF_COMPLETED'
            next_step = 'OUTSIDE_AGENT_BANKING_PROCESS'
            outside_process_open_item_title = self._external_process_title(
                latest_ready.get('transaction_id'),
                latest_ready.get('candidate_reference'),
            )
            outside_process_item = await self._ensure_open_item(
                existing_items,
                case_id=case_id,
                title=outside_process_open_item_title,
                description=self._external_process_description(
                    latest_ready.get('transaction_id'),
                    latest_ready.get('candidate_reference'),
                    payload.resolution_note,
                ),
                source=_EXTERNAL_VERSION,
            )
            outside_process_open_item_id = outside_process_item.item_id
            outside_process_open_item_title = outside_process_item.title
            summary = (
                f'Banking-Handoff {payload.handoff_ref} ist als manuell uebernommen dokumentiert. '
                f'Externer Banking-Abschluss steht noch zur Dokumentation aus. '
                f'Kein Bank-Write durch Frya.'
            )
        else:
            status = 'BANKING_HANDOFF_RETURNED'
            next_step = 'BANKING_CLARIFICATION_OPEN'
            follow_up_item_title = (
                f'[Banking] Handoff-Ruecklauf klaeren: '
                f'Transaktion {latest_ready.get("transaction_id") or "?"}'
            )
            follow_up_item = await self.open_items_service.create_item(
                case_id=case_id,
                title=follow_up_item_title,
                description=(
                    f'Banking-Handoff {payload.handoff_ref} wurde zurueckgegeben. '
                    f'Rueckmeldung: {payload.resolution_note or "-"}. '
                    f'Kein automatischer Write. Keine Zahlung.'
                ),
                source=_HANDOFF_VERSION,
            )
            follow_up_item_id = follow_up_item.item_id
            summary = (
                f'Banking-Handoff {payload.handoff_ref} wurde konservativ zurueckgegeben. '
                f'Klaer-Open-Item erstellt.'
            )

        await self.audit_service.log_event({
            'event_id': audit_event_id,
            'case_id': case_id,
            'source': payload.source,
            'agent_name': _HANDOFF_VERSION,
            'action': status,
            'approval_status': (
                'APPROVED' if payload.decision == BankingHandoffResolutionDecision.COMPLETED else 'REJECTED'
            ),
            'result': status,
            'llm_output': {
                'resolution_id': resolution_id,
                'handoff_ref': payload.handoff_ref,
                'review_ref': latest_ready.get('review_ref'),
                'workbench_ref': latest_ready.get('workbench_ref'),
                'transaction_id': latest_ready.get('transaction_id'),
                'candidate_reference': latest_ready.get('candidate_reference'),
                'decision': payload.decision.value,
                'status': status,
                'suggested_next_step': next_step,
                'resolution_note': payload.resolution_note,
                'resolved_by': payload.resolved_by,
                'handoff_open_item_id': closed_item_id or handoff_open_item_id,
                'handoff_open_item_title': handoff_open_item_title,
                'follow_up_open_item_id': follow_up_item_id,
                'follow_up_open_item_title': follow_up_item_title,
                'outside_process_open_item_id': outside_process_open_item_id,
                'outside_process_open_item_title': outside_process_open_item_title,
                'clarification_state': (
                    'OPEN'
                    if payload.decision == BankingHandoffResolutionDecision.RETURNED
                    else None
                ),
                'clarification_ref': (
                    resolution_id
                    if payload.decision == BankingHandoffResolutionDecision.RETURNED
                    else None
                ),
                'bank_write_executed': False,
                'no_financial_write': True,
            },
        })

        return BankingHandoffResolutionResult(
            resolution_id=resolution_id,
            handoff_ref=payload.handoff_ref,
            case_id=case_id,
            review_ref=latest_ready.get('review_ref'),
            workbench_ref=latest_ready.get('workbench_ref'),
            transaction_id=latest_ready.get('transaction_id'),
            candidate_reference=latest_ready.get('candidate_reference'),
            decision=payload.decision,
            status=status,
            suggested_next_step=next_step,
            resolution_note=payload.resolution_note,
            resolved_by=payload.resolved_by,
            handoff_open_item_id=closed_item_id or handoff_open_item_id,
            handoff_open_item_title=handoff_open_item_title,
            follow_up_open_item_id=follow_up_item_id,
            follow_up_open_item_title=follow_up_item_title,
            outside_process_open_item_id=outside_process_open_item_id,
            outside_process_open_item_title=outside_process_open_item_title,
            audit_event_id=audit_event_id,
            summary=summary,
            bank_write_executed=False,
            no_financial_write=True,
        )

    async def complete_manual_handoff(
        self,
        payload: BankManualHandoffInput,
    ) -> BankManualHandoffResult:
        """Backward-compatible wrapper for handoff resolution."""
        chronology = list(await self.audit_service.by_case(payload.case_id, limit=500))
        latest_ready = self._latest_payload_from_actions(chronology, {'BANKING_HANDOFF_READY'})
        if not latest_ready:
            raise ValueError('Kein Banking-Handoff im Status READY vorhanden.')
        resolution = await self.resolve_handoff(
            BankingHandoffResolutionInput(
                case_id=payload.case_id,
                handoff_ref=latest_ready['handoff_id'],
                decision=BankingHandoffResolutionDecision(payload.decision.value),
                resolution_note=payload.note,
                resolved_by=payload.decided_by,
                source=payload.source,
            )
        )
        return BankManualHandoffResult(
            handoff_id=resolution.handoff_ref,
            case_id=resolution.case_id,
            transaction_id=resolution.transaction_id,
            decision=BankManualHandoffDecision(resolution.decision.value),
            outcome_status=resolution.status,
            note=resolution.resolution_note,
            decided_by=resolution.resolved_by,
            closed_open_item_id=resolution.handoff_open_item_id,
            follow_up_open_item_id=resolution.follow_up_open_item_id,
            follow_up_open_item_title=resolution.follow_up_open_item_title,
            audit_event_id=resolution.audit_event_id,
            summary=resolution.summary,
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
        chronology = list(await self.audit_service.by_case(payload.case_id, limit=500))
        latest_resolution = self._latest_payload_from_actions(
            chronology,
            {'BANKING_HANDOFF_RETURNED'},
        )
        if latest_resolution:
            completion = await self.complete_banking_clarification(
                BankingClarificationCompletionInput(
                    case_id=payload.case_id,
                    clarification_ref=latest_resolution.get('clarification_ref') or latest_resolution.get('resolution_id'),
                    clarification_note=payload.resolution_note,
                    clarified_by=payload.decided_by,
                    source=payload.source,
                )
            )
            return BankClarificationResult(
                clarification_id=completion.clarification_completion_id,
                case_id=completion.case_id,
                transaction_id=completion.transaction_id,
                outcome_status=completion.status,
                resolution_note=completion.clarification_note,
                decided_by=completion.clarified_by,
                closed_open_item_id=completion.clarification_open_item_id,
                audit_event_id=completion.audit_event_id,
                summary=completion.summary,
                bank_write_executed=False,
                no_financial_write=True,
            )
        # Legacy fallback for old banking clarification flow.
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

    async def complete_banking_clarification(
        self,
        payload: BankingClarificationCompletionInput,
    ) -> BankingClarificationCompletionResult:
        """Resolve a clarification opened by BANKING_HANDOFF_RETURNED."""
        clarification_completion_id = str(uuid.uuid4())
        audit_event_id = str(uuid.uuid4())
        case_id = payload.case_id
        chronology = list(await self.audit_service.by_case(case_id, limit=500))
        latest_resolution = self._latest_payload_from_actions(
            chronology,
            {'BANKING_HANDOFF_RETURNED', 'BANKING_HANDOFF_COMPLETED'},
        )
        latest_completion = self._latest_payload_from_actions(
            chronology,
            {'BANKING_CLARIFICATION_COMPLETED'},
        )
        if not latest_resolution or latest_resolution.get('status') != 'BANKING_HANDOFF_RETURNED':
            raise ValueError('Banking-Klaerabschluss nur nach BANKING_HANDOFF_RETURNED zulaessig.')
        expected_ref = latest_resolution.get('clarification_ref') or latest_resolution.get('resolution_id')
        if payload.clarification_ref != expected_ref:
            raise ValueError('Clarification-Ref passt nicht zum aktuellen Banking-Rueckgabezustand.')
        if latest_completion and latest_completion.get('clarification_ref') == payload.clarification_ref:
            raise ValueError('Dieser Banking-Klaerfall wurde bereits abgeschlossen.')

        existing_items = await self.open_items_service.list_by_case(case_id)
        closed_item_id: str | None = None
        closed_item_title: str | None = None
        clarification_open_item_id = latest_resolution.get('follow_up_open_item_id')
        for item in existing_items:
            if item.status not in _ACTIVE_STATUSES:
                continue
            if clarification_open_item_id and item.item_id == clarification_open_item_id:
                await self.open_items_service.update_status(item.item_id, 'COMPLETED')
                closed_item_id = item.item_id
                closed_item_title = item.title
                break
            if 'HANDOFF-RUECKLAUF KLAEREN' in item.title.upper():
                await self.open_items_service.update_status(item.item_id, 'COMPLETED')
                closed_item_id = item.item_id
                closed_item_title = item.title
                break

        status = 'BANKING_CLARIFICATION_COMPLETED'
        suggested_next_step = 'OUTSIDE_AGENT_BANKING_PROCESS'
        outside_process_open_item_title = self._external_process_title(
            latest_resolution.get('transaction_id'),
            latest_resolution.get('candidate_reference'),
        )
        outside_process_item = await self._ensure_open_item(
            existing_items,
            case_id=case_id,
            title=outside_process_open_item_title,
            description=self._external_process_description(
                latest_resolution.get('transaction_id'),
                latest_resolution.get('candidate_reference'),
                payload.clarification_note,
            ),
            source=_EXTERNAL_VERSION,
        )
        summary = (
            f'Banking-Klaerung fuer Transaktion {latest_resolution.get("transaction_id")} abgeschlossen. '
            f'Rueckgabegrund dokumentiert; externer Banking-Abschluss steht noch zur Dokumentation aus. '
            f'Kein Bank-Write durch Frya.'
        )

        await self.audit_service.log_event({
            'event_id': audit_event_id,
            'case_id': case_id,
            'source': payload.source,
            'agent_name': _CLARIF_VERSION,
            'action': status,
            'approval_status': 'APPROVED',
            'result': status,
            'llm_output': {
                'clarification_completion_id': clarification_completion_id,
                'clarification_ref': payload.clarification_ref,
                'handoff_ref': latest_resolution.get('handoff_ref'),
                'review_ref': latest_resolution.get('review_ref'),
                'workbench_ref': latest_resolution.get('workbench_ref'),
                'transaction_id': latest_resolution.get('transaction_id'),
                'candidate_reference': latest_resolution.get('candidate_reference'),
                'status': status,
                'clarification_state': 'COMPLETED',
                'clarification_note': payload.clarification_note,
                'clarified_by': payload.clarified_by,
                'clarification_guidance': 'Rueckgabegrund ist manuell geklaert und als konservativer Abschluss dokumentiert.',
                'required_manual_evidence': 'Kurznotiz, welche manuelle Rueckfrage oder Pruefung den Ruecklauf geklaert hat.',
                'next_manual_step': 'Kein weiterer Schritt in Frya. Externe Finanzrealitaet bleibt ausserhalb des Agenten.',
                'suggested_next_step': suggested_next_step,
                'clarification_open_item_id': closed_item_id or clarification_open_item_id,
                'clarification_open_item_title': closed_item_title or latest_resolution.get('follow_up_open_item_title'),
                'outside_process_open_item_id': outside_process_item.item_id,
                'outside_process_open_item_title': outside_process_item.title,
                'bank_write_executed': False,
                'no_financial_write': True,
            },
        })

        return BankingClarificationCompletionResult(
            clarification_completion_id=clarification_completion_id,
            clarification_ref=payload.clarification_ref,
            case_id=case_id,
            handoff_ref=latest_resolution.get('handoff_ref'),
            review_ref=latest_resolution.get('review_ref'),
            workbench_ref=latest_resolution.get('workbench_ref'),
            transaction_id=latest_resolution.get('transaction_id'),
            candidate_reference=latest_resolution.get('candidate_reference'),
            status=status,
            clarification_state='COMPLETED',
            clarification_note=payload.clarification_note,
            clarified_by=payload.clarified_by,
            clarification_open_item_id=closed_item_id or clarification_open_item_id,
            clarification_open_item_title=closed_item_title or latest_resolution.get('follow_up_open_item_title'),
            outside_process_open_item_id=outside_process_item.item_id,
            outside_process_open_item_title=outside_process_item.title,
            audit_event_id=audit_event_id,
            suggested_next_step=suggested_next_step,
            summary=summary,
            bank_write_executed=False,
            no_financial_write=True,
        )

    async def complete_external_banking_process(
        self,
        payload: ExternalBankingProcessCompletionInput,
    ) -> ExternalBankingProcessCompletionResult:
        """Document the manual external banking completion outside Frya."""
        external_resolution_id = str(uuid.uuid4())
        audit_event_id = str(uuid.uuid4())
        case_id = payload.case_id
        chronology = list(await self.audit_service.by_case(case_id, limit=500))
        outside_context = self._outside_agent_banking_context(chronology)
        if outside_context is None:
            raise ValueError('Externer Banking-Abschluss erst nach OUTSIDE_AGENT_BANKING_PROCESS moeglich.')

        latest_external = self._latest_payload_from_actions(
            chronology,
            {'EXTERNAL_BANKING_PROCESS_COMPLETED'},
        )
        if latest_external and latest_external.get('transaction_id') == outside_context.get('transaction_id'):
            raise ValueError('Der externe Banking-Abschluss wurde fuer diesen Fall bereits dokumentiert.')

        existing_items = await self.open_items_service.list_by_case(case_id)
        outside_process_item = await self._ensure_open_item(
            existing_items,
            case_id=case_id,
            title=outside_context.get('outside_process_open_item_title') or self._external_process_title(
                outside_context.get('transaction_id'),
                outside_context.get('candidate_reference'),
            ),
            description=self._external_process_description(
                outside_context.get('transaction_id'),
                outside_context.get('candidate_reference'),
                payload.resolution_note,
            ),
            source=_EXTERNAL_VERSION,
            preferred_item_id=outside_context.get('outside_process_open_item_id'),
        )
        await self.open_items_service.update_status(outside_process_item.item_id, 'COMPLETED')

        result = ExternalBankingProcessCompletionResult(
            external_resolution_id=external_resolution_id,
            case_id=case_id,
            transaction_id=outside_context.get('transaction_id'),
            review_ref=outside_context.get('review_ref'),
            workbench_ref=outside_context.get('workbench_ref'),
            handoff_ref=outside_context.get('handoff_ref'),
            clarification_ref=outside_context.get('clarification_ref'),
            candidate_reference=outside_context.get('candidate_reference'),
            decision=ExternalBankingProcessDecision.COMPLETED,
            status='EXTERNAL_BANKING_PROCESS_COMPLETED',
            external_banking_outcome='MANUALLY_COMPLETED_OUTSIDE_FRYA',
            no_further_agent_action_reason='Externer manueller Banking-Prozess wurde ausserhalb Frya dokumentiert abgeschlossen.',
            resolution_note=payload.resolution_note,
            resolved_by=payload.resolved_by,
            outside_process_open_item_id=outside_process_item.item_id,
            outside_process_open_item_title=outside_process_item.title,
            source_internal_status=outside_context.get('source_status'),
            audit_event_id=audit_event_id,
            suggested_next_step='NO_FURTHER_AGENT_ACTION',
            summary=(
                f'Externer Banking-Abschluss fuer Transaktion {outside_context.get("transaction_id")} '
                f'ist dokumentiert. Kein weiterer Frya-Schritt offen.'
            ),
            bank_write_executed=False,
            no_financial_write=True,
        )

        await self.audit_service.log_event({
            'event_id': audit_event_id,
            'case_id': case_id,
            'source': payload.source,
            'agent_name': _EXTERNAL_VERSION,
            'action': 'EXTERNAL_BANKING_PROCESS_COMPLETED',
            'approval_status': 'APPROVED',
            'result': result.status,
            'llm_output': result.model_dump(mode='json'),
        })
        return result

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
                    except Exception as exc:
                        logger.debug('latest_reconciliation_payload: JSON parse failed: %s', exc)
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

    def _latest_payload_from_actions(
        self,
        chronology: list,
        actions: set[str],
    ) -> dict | None:
        import json as _json

        for event in reversed(chronology):
            action = getattr(event, 'action', '') or ''
            if action not in actions:
                continue
            raw_output = getattr(event, 'llm_output', None)
            if isinstance(raw_output, str):
                try:
                    raw_output = _json.loads(raw_output)
                except Exception as exc:
                    logger.debug('_latest_payload_from_actions: JSON parse failed: %s', exc)
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

    def _select_candidate(
        self,
        context: ReconciliationContext,
        transaction_id: str | int | None,
    ):
        if not context.all_candidates:
            return None, None
        if transaction_id is None and context.best_candidate is not None:
            return context.best_candidate, 1
        for index, candidate in enumerate(context.all_candidates, start=1):
            if str(candidate.transaction_id) == str(transaction_id):
                return candidate, index
        raise ValueError('Kandidat nicht im aktuellen Workbench-Stand vorhanden.')

    def _rejected_follow_up_title(
        self,
        context: ReconciliationContext,
        candidate,
        payload: BankReconciliationReviewInput,
    ) -> str:
        tx_id = candidate.transaction_id if candidate else payload.transaction_id or '?'
        if context.match_signal.value == 'CONFLICT':
            return f'[Banking] Konflikt klaeren: Transaktion {tx_id}'
        if context.match_signal.value == 'UNCLEAR':
            return f'[Banking] Mehrdeutigen Abgleich klaeren: Transaktion {tx_id}'
        if context.match_signal.value == 'MISSING_DATA':
            return f'[Banking] Fehlende Abgleichsdaten klaeren: Transaktion {tx_id}'
        return f'[Banking] Klaerung erforderlich: Transaktion {tx_id} abgelehnt'

    def _outside_agent_banking_context(self, chronology: list) -> dict | None:
        latest_external = self._latest_payload_from_actions(
            chronology,
            {'EXTERNAL_BANKING_PROCESS_COMPLETED'},
        )
        if latest_external is not None:
            return {
                'status': latest_external.get('status'),
                'source_status': latest_external.get('source_internal_status') or latest_external.get('status'),
                'review_ref': latest_external.get('review_ref'),
                'workbench_ref': latest_external.get('workbench_ref'),
                'handoff_ref': latest_external.get('handoff_ref'),
                'clarification_ref': latest_external.get('clarification_ref'),
                'transaction_id': latest_external.get('transaction_id'),
                'candidate_reference': latest_external.get('candidate_reference'),
                'outside_process_open_item_id': latest_external.get('outside_process_open_item_id'),
                'outside_process_open_item_title': latest_external.get('outside_process_open_item_title'),
                'resolution_recorded': True,
            }

        latest_clarification = self._latest_payload_from_actions(
            chronology,
            {'BANKING_CLARIFICATION_COMPLETED'},
        )
        if latest_clarification is not None:
            return {
                'status': 'OUTSIDE_AGENT_BANKING_PROCESS',
                'source_status': latest_clarification.get('status'),
                'review_ref': latest_clarification.get('review_ref'),
                'workbench_ref': latest_clarification.get('workbench_ref'),
                'handoff_ref': latest_clarification.get('handoff_ref'),
                'clarification_ref': latest_clarification.get('clarification_ref'),
                'transaction_id': latest_clarification.get('transaction_id'),
                'candidate_reference': latest_clarification.get('candidate_reference'),
                'outside_process_open_item_id': latest_clarification.get('outside_process_open_item_id'),
                'outside_process_open_item_title': latest_clarification.get('outside_process_open_item_title'),
                'resolution_recorded': False,
            }

        latest_handoff_resolution = self._latest_payload_from_actions(
            chronology,
            {'BANKING_HANDOFF_COMPLETED', 'BANKING_HANDOFF_RETURNED'},
        )
        if latest_handoff_resolution is not None and latest_handoff_resolution.get('decision') == 'COMPLETED':
            return {
                'status': 'OUTSIDE_AGENT_BANKING_PROCESS',
                'source_status': latest_handoff_resolution.get('status'),
                'review_ref': latest_handoff_resolution.get('review_ref'),
                'workbench_ref': latest_handoff_resolution.get('workbench_ref'),
                'handoff_ref': latest_handoff_resolution.get('handoff_ref'),
                'clarification_ref': None,
                'transaction_id': latest_handoff_resolution.get('transaction_id'),
                'candidate_reference': latest_handoff_resolution.get('candidate_reference'),
                'outside_process_open_item_id': latest_handoff_resolution.get('outside_process_open_item_id'),
                'outside_process_open_item_title': latest_handoff_resolution.get('outside_process_open_item_title'),
                'resolution_recorded': False,
            }

        return None

    async def _ensure_open_item(
        self,
        existing_items: list,
        *,
        case_id: str,
        title: str,
        description: str,
        source: str,
        preferred_item_id: str | None = None,
    ):
        if preferred_item_id:
            for item in existing_items:
                if item.item_id == preferred_item_id and item.status in _ACTIVE_STATUSES:
                    return item
        for item in existing_items:
            if item.title == title and item.status in _ACTIVE_STATUSES:
                return item
        return await self.open_items_service.create_item(
            case_id=case_id,
            title=title,
            description=description,
            source=source,
        )

    def _external_process_title(
        self,
        transaction_id: str | int | None,
        candidate_reference: str | None,
    ) -> str:
        ref = candidate_reference or f'Transaktion {transaction_id or "?"}'
        return f'[Banking] Externen Banking-Abschluss dokumentieren: {ref}'

    def _external_process_description(
        self,
        transaction_id: str | int | None,
        candidate_reference: str | None,
        note: str | None,
    ) -> str:
        return (
            f'Konservativer read-only Banking-Fall fuer Transaktion {transaction_id or "?"} '
            f'und Referenz {candidate_reference or "-"}. '
            f'Nur dokumentieren, dass die externe manuelle Weiterbearbeitung ausserhalb Frya erfolgt oder abgeschlossen wurde. '
            f'Notiz: {note or "-"}. Kein Bank-Write. Kein Akaunting-Write. Keine Zahlung.'
        )
