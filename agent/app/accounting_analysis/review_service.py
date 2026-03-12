from __future__ import annotations

import json
import uuid

from app.accounting_analysis.models import (
    AccountingAnalysisResult,
    AccountingClarificationCompletionInput,
    AccountingClarificationCompletionResult,
    AccountingManualHandoffInput,
    AccountingManualHandoffResolutionInput,
    AccountingManualHandoffResolutionResult,
    AccountingManualHandoffResult,
    AccountingOperatorReviewDecisionInput,
    AccountingOperatorReviewDecisionResult,
    ExternalAccountingProcessResolutionInput,
    ExternalAccountingProcessResolutionResult,
    ExternalReturnClarificationCompletionInput,
    ExternalReturnClarificationCompletionResult,
)
from app.audit.models import AuditRecord
from app.audit.service import AuditService
from app.open_items.models import OpenItem, OpenItemStatus
from app.open_items.service import OpenItemsService
from app.problems.service import ProblemCaseService

_ACTIVE_ITEM_STATUSES: set[OpenItemStatus] = {'OPEN', 'WAITING_USER', 'WAITING_DATA', 'SCHEDULED'}


class AccountingOperatorReviewService:
    def __init__(
        self,
        audit_service: AuditService,
        open_items_service: OpenItemsService,
        problem_service: ProblemCaseService,
    ) -> None:
        self.audit_service = audit_service
        self.open_items_service = open_items_service
        self.problem_service = problem_service

    async def decide(self, payload: AccountingOperatorReviewDecisionInput) -> AccountingOperatorReviewDecisionResult:
        chronology = await self.audit_service.by_case(payload.case_id, limit=500)
        accounting_analysis = self._latest_accounting_analysis(chronology)
        if accounting_analysis is None:
            raise ValueError('Kein Accounting-Analyseergebnis fuer diesen Case vorhanden.')
        if accounting_analysis.global_decision != 'PROPOSED':
            raise ValueError('Accounting-Analyse ist nicht in einem bestaetigbaren Review-Zustand.')

        existing_decision = self._latest_operator_review(chronology, accounting_analysis.accounting_review_ref)
        if existing_decision is not None:
            raise ValueError('Accounting-Review-Entscheidung wurde fuer diesen Vorschlag bereits getroffen.')

        review_item_title = self._review_item_title(accounting_analysis)
        open_items = await self.open_items_service.list_by_case(payload.case_id)
        review_item = self._find_active_review_item(open_items, review_item_title, accounting_analysis.accounting_review_ref)
        if review_item is None:
            raise ValueError('Kein offenes operatorisches Review-Open-Item fuer diesen Vorschlag gefunden.')

        await self.open_items_service.update_status(review_item.item_id, 'COMPLETED')

        follow_up_open_item_id = None
        follow_up_open_item_title = None
        problem_case_id = None
        if payload.decision == 'CONFIRMED':
            outcome_status = 'ACCOUNTING_CONFIRMED_PENDING_MANUAL_HANDOFF'
            suggested_next_step = 'MANUAL_ACCOUNTING_HANDOFF'
        else:
            outcome_status = 'ACCOUNTING_REJECTED_REQUIRES_CLARIFICATION'
            suggested_next_step = 'ACCOUNTING_CLARIFICATION'
            follow_up_open_item_title = self._clarification_title(accounting_analysis)
            follow_up = await self._ensure_follow_up_open_item(
                case_id=payload.case_id,
                title=follow_up_open_item_title,
                description=self._follow_up_description(accounting_analysis, payload.decision_note),
                document_ref=review_item.document_ref,
                accounting_ref=accounting_analysis.accounting_review_ref,
                source='accounting_operator_review',
            )
            follow_up_open_item_id = follow_up.item_id
            problem = await self.problem_service.add_case(
                case_id=payload.case_id,
                title='Accounting review rejected',
                details=self._follow_up_description(accounting_analysis, payload.decision_note),
                severity='MEDIUM',
                exception_type='ACCOUNTING_REVIEW_REJECTED',
                document_ref=review_item.document_ref,
                accounting_ref=accounting_analysis.accounting_review_ref,
                created_by=payload.decided_by,
            )
            problem_case_id = problem.problem_id

        result = AccountingOperatorReviewDecisionResult(
            case_id=payload.case_id,
            accounting_review_ref=accounting_analysis.accounting_review_ref,
            booking_candidate_type=accounting_analysis.booking_candidate_type,
            decision=payload.decision,
            decision_note=payload.decision_note,
            review_item_title=review_item.title,
            review_item_id=review_item.item_id,
            outcome_status=outcome_status,
            suggested_next_step=suggested_next_step,
            follow_up_open_item_id=follow_up_open_item_id,
            follow_up_open_item_title=follow_up_open_item_title,
            problem_case_id=problem_case_id,
            manual_handoff=None,
            decided_by=payload.decided_by,
            execution_allowed=False,
            summary=self._summary(accounting_analysis, payload.decision, suggested_next_step, payload.decision_note),
        )

        await self.audit_service.log_event(
            {
                'event_id': str(uuid.uuid4()),
                'case_id': payload.case_id,
                'source': payload.source,
                'document_ref': review_item.document_ref,
                'accounting_ref': accounting_analysis.accounting_review_ref,
                'agent_name': 'accounting-operator-review',
                'approval_status': 'APPROVED' if payload.decision == 'CONFIRMED' else 'REJECTED',
                'action': self._audit_action(payload.decision),
                'result': result.summary,
                'llm_output': result.model_dump(mode='json'),
            }
        )
        return result

    async def mark_manual_handoff(self, payload: AccountingManualHandoffInput) -> AccountingManualHandoffResult:
        chronology = await self.audit_service.by_case(payload.case_id, limit=500)
        accounting_analysis = self._latest_accounting_analysis(chronology)
        if accounting_analysis is None:
            raise ValueError('Kein Accounting-Analyseergebnis fuer diesen Case vorhanden.')

        operator_review = self._latest_operator_review(chronology, accounting_analysis.accounting_review_ref)
        if operator_review is None or operator_review.decision != 'CONFIRMED':
            raise ValueError('Manueller Handoff ist erst nach bestaetigtem Accounting-Review moeglich.')

        existing_handoff = self._latest_manual_handoff(chronology, accounting_analysis.accounting_review_ref)
        if existing_handoff is not None:
            raise ValueError('Manueller Accounting-Handoff wurde fuer diesen Vorschlag bereits gesetzt.')

        handoff_open_item = await self._ensure_follow_up_open_item(
            case_id=payload.case_id,
            title=self._manual_handoff_title(accounting_analysis),
            description=self._manual_handoff_description(accounting_analysis, operator_review, payload.note),
            document_ref=self._document_ref_from_review(operator_review, chronology),
            accounting_ref=accounting_analysis.accounting_review_ref,
            source='accounting_manual_handoff',
        )

        result = AccountingManualHandoffResult(
            case_id=payload.case_id,
            accounting_review_ref=accounting_analysis.accounting_review_ref,
            booking_candidate_type=accounting_analysis.booking_candidate_type,
            status='READY_FOR_MANUAL_ACCOUNTING',
            suggested_next_step='MANUAL_ACCOUNTING_WORK',
            instruction_headline=self._manual_handoff_title(accounting_analysis),
            instruction_detail=self._manual_handoff_description(accounting_analysis, operator_review, payload.note),
            handoff_note=payload.note,
            open_item_id=handoff_open_item.item_id,
            open_item_title=handoff_open_item.title,
            handoff_marked_by=payload.decided_by,
            execution_allowed=False,
            external_write_performed=False,
            summary=self._manual_handoff_summary(accounting_analysis, handoff_open_item.title, payload.note),
        )

        await self.audit_service.log_event(
            {
                'event_id': str(uuid.uuid4()),
                'case_id': payload.case_id,
                'source': payload.source,
                'document_ref': handoff_open_item.document_ref,
                'accounting_ref': accounting_analysis.accounting_review_ref,
                'agent_name': 'accounting-manual-handoff',
                'approval_status': 'APPROVED',
                'action': 'ACCOUNTING_MANUAL_HANDOFF_READY',
                'result': result.summary,
                'llm_output': result.model_dump(mode='json'),
            }
        )
        return result

    async def resolve_manual_handoff(self, payload: AccountingManualHandoffResolutionInput) -> AccountingManualHandoffResolutionResult:
        chronology = await self.audit_service.by_case(payload.case_id, limit=500)
        accounting_analysis = self._latest_accounting_analysis(chronology)
        if accounting_analysis is None:
            raise ValueError('Kein Accounting-Analyseergebnis fuer diesen Case vorhanden.')

        handoff = self._latest_manual_handoff(chronology, accounting_analysis.accounting_review_ref)
        if handoff is None:
            raise ValueError('Kein manueller Accounting-Handoff fuer diesen Case vorhanden.')

        existing_resolution = self._latest_manual_handoff_resolution(chronology, accounting_analysis.accounting_review_ref)
        if existing_resolution is not None:
            raise ValueError('Der manuelle Accounting-Handoff wurde bereits abgeschlossen oder zurueckgegeben.')

        open_items = await self.open_items_service.list_by_case(payload.case_id)
        handoff_item = self._find_active_item_by_id(open_items, handoff.open_item_id)
        if handoff_item is None:
            raise ValueError('Kein offenes Handoff-Open-Item fuer diesen Case gefunden.')

        await self.open_items_service.update_status(handoff_item.item_id, 'COMPLETED')

        follow_up_open_item_id = None
        follow_up_open_item_title = None
        outside_process_open_item_id = None
        outside_process_open_item_title = None
        problem_case_id = None
        if payload.decision == 'COMPLETED':
            status = 'MANUAL_HANDOFF_COMPLETED'
            suggested_next_step = 'OUTSIDE_AGENT_ACCOUNTING_PROCESS'
            outside_process = await self._ensure_follow_up_open_item(
                case_id=payload.case_id,
                title=self._external_process_title(accounting_analysis),
                description=self._external_process_description(accounting_analysis, payload.note),
                document_ref=handoff_item.document_ref,
                accounting_ref=accounting_analysis.accounting_review_ref,
                source='external_accounting_process',
            )
            outside_process_open_item_id = outside_process.item_id
            outside_process_open_item_title = outside_process.title
        else:
            status = 'MANUAL_HANDOFF_RETURNED_FOR_CLARIFICATION'
            suggested_next_step = 'ACCOUNTING_CLARIFICATION'
            follow_up_open_item_title = self._manual_handoff_return_title(accounting_analysis)
            follow_up = await self._ensure_follow_up_open_item(
                case_id=payload.case_id,
                title=follow_up_open_item_title,
                description=self._manual_handoff_return_description(accounting_analysis, payload.note),
                document_ref=handoff_item.document_ref,
                accounting_ref=accounting_analysis.accounting_review_ref,
                source='accounting_manual_handoff',
            )
            follow_up_open_item_id = follow_up.item_id
            problem = await self.problem_service.add_case(
                case_id=payload.case_id,
                title='Accounting manual handoff returned',
                details=self._manual_handoff_return_description(accounting_analysis, payload.note),
                severity='MEDIUM',
                exception_type='ACCOUNTING_MANUAL_HANDOFF_RETURNED',
                document_ref=handoff_item.document_ref,
                accounting_ref=accounting_analysis.accounting_review_ref,
                created_by=payload.decided_by,
            )
            problem_case_id = problem.problem_id

        result = AccountingManualHandoffResolutionResult(
            case_id=payload.case_id,
            accounting_review_ref=accounting_analysis.accounting_review_ref,
            handoff_open_item_id=handoff_item.item_id,
            handoff_open_item_title=handoff_item.title,
            decision=payload.decision,
            status=status,
            suggested_next_step=suggested_next_step,
            resolution_note=payload.note,
            follow_up_open_item_id=follow_up_open_item_id,
            follow_up_open_item_title=follow_up_open_item_title,
            outside_process_open_item_id=outside_process_open_item_id,
            outside_process_open_item_title=outside_process_open_item_title,
            problem_case_id=problem_case_id,
            resolved_by=payload.decided_by,
            execution_allowed=False,
            external_write_performed=False,
            summary=self._manual_handoff_resolution_summary(payload.decision, handoff_item.title, payload.note),
        )

        await self.audit_service.log_event(
            {
                'event_id': str(uuid.uuid4()),
                'case_id': payload.case_id,
                'source': payload.source,
                'document_ref': handoff_item.document_ref,
                'accounting_ref': accounting_analysis.accounting_review_ref,
                'agent_name': 'accounting-manual-handoff',
                'approval_status': 'APPROVED' if payload.decision == 'COMPLETED' else 'REJECTED',
                'action': self._manual_handoff_resolution_action(payload.decision),
                'result': result.summary,
                'llm_output': result.model_dump(mode='json'),
            }
        )
        return result

    async def complete_clarification(self, payload: AccountingClarificationCompletionInput) -> AccountingClarificationCompletionResult:
        chronology = await self.audit_service.by_case(payload.case_id, limit=500)
        accounting_analysis = self._latest_accounting_analysis(chronology)
        if accounting_analysis is None:
            raise ValueError('Kein Accounting-Analyseergebnis fuer diesen Case vorhanden.')

        handoff_resolution = self._latest_manual_handoff_resolution(chronology, accounting_analysis.accounting_review_ref)
        if handoff_resolution is None or handoff_resolution.decision != 'RETURNED':
            raise ValueError('Accounting-Klaerabschluss ist erst nach RETURNED-Manual-Handoff moeglich.')

        existing_completion = self._latest_clarification_completion(chronology, accounting_analysis.accounting_review_ref)
        if existing_completion is not None:
            raise ValueError('Der Accounting-Klaerfall wurde bereits abgeschlossen.')

        if not handoff_resolution.follow_up_open_item_id:
            raise ValueError('Kein offenes Klaer-Open-Item fuer diesen Case referenziert.')

        open_items = await self.open_items_service.list_by_case(payload.case_id)
        clarification_item = self._find_active_item_by_id(open_items, handoff_resolution.follow_up_open_item_id)
        if clarification_item is None:
            raise ValueError('Kein offenes Klaer-Open-Item fuer diesen Case gefunden.')

        await self.open_items_service.update_status(clarification_item.item_id, 'COMPLETED')

        outside_process = await self._ensure_follow_up_open_item(
            case_id=payload.case_id,
            title=self._external_process_title(accounting_analysis),
            description=self._external_process_description(accounting_analysis, payload.note),
            document_ref=clarification_item.document_ref,
            accounting_ref=accounting_analysis.accounting_review_ref,
            source='external_accounting_process',
        )

        result = AccountingClarificationCompletionResult(
            case_id=payload.case_id,
            accounting_review_ref=accounting_analysis.accounting_review_ref,
            clarification_open_item_id=clarification_item.item_id,
            clarification_open_item_title=clarification_item.title,
            status='ACCOUNTING_CLARIFICATION_COMPLETED',
            suggested_next_step='OUTSIDE_AGENT_ACCOUNTING_PROCESS',
            clarification_note=payload.note,
            outside_process_open_item_id=outside_process.item_id,
            outside_process_open_item_title=outside_process.title,
            problem_case_id=handoff_resolution.problem_case_id,
            clarified_by=payload.decided_by,
            execution_allowed=False,
            external_write_performed=False,
            summary=self._clarification_completion_summary(clarification_item.title, payload.note),
        )

        await self.audit_service.log_event(
            {
                'event_id': str(uuid.uuid4()),
                'case_id': payload.case_id,
                'source': payload.source,
                'document_ref': clarification_item.document_ref,
                'accounting_ref': accounting_analysis.accounting_review_ref,
                'agent_name': 'accounting-clarification',
                'approval_status': 'APPROVED',
                'action': 'ACCOUNTING_CLARIFICATION_COMPLETED',
                'result': result.summary,
                'llm_output': result.model_dump(mode='json'),
            }
        )
        return result

    async def resolve_external_accounting_process(
        self,
        payload: ExternalAccountingProcessResolutionInput,
    ) -> ExternalAccountingProcessResolutionResult:
        chronology = await self.audit_service.by_case(payload.case_id, limit=500)
        accounting_analysis = self._latest_accounting_analysis(chronology)
        if accounting_analysis is None:
            raise ValueError('Kein Accounting-Analyseergebnis fuer diesen Case vorhanden.')

        if self._latest_external_accounting_process_resolution(chronology, accounting_analysis.accounting_review_ref) is not None:
            raise ValueError('Der externe Accounting-Prozess wurde fuer diesen Case bereits dokumentiert.')

        outside_context = self._outside_agent_context(chronology, accounting_analysis.accounting_review_ref)
        if outside_context is None:
            raise ValueError('Externer Accounting-Abschluss ist erst nach OUTSIDE_AGENT_ACCOUNTING_PROCESS moeglich.')

        outside_title = outside_context.get('outside_process_open_item_title') or self._external_process_title(accounting_analysis)
        open_items = await self.open_items_service.list_by_case(payload.case_id)
        outside_item = None
        outside_item_id = outside_context.get('outside_process_open_item_id')
        if outside_item_id:
            outside_item = self._find_active_item_by_id(open_items, outside_item_id)
        if outside_item is None:
            outside_item = await self._ensure_follow_up_open_item(
                case_id=payload.case_id,
                title=outside_title,
                description=self._external_process_description(accounting_analysis, payload.note),
                document_ref=outside_context.get('document_ref'),
                accounting_ref=accounting_analysis.accounting_review_ref,
                source='external_accounting_process',
            )

        await self.open_items_service.update_status(outside_item.item_id, 'COMPLETED')

        follow_up_open_item_id = None
        follow_up_open_item_title = None
        problem_case_id = None
        if payload.decision == 'COMPLETED':
            status = 'EXTERNAL_ACCOUNTING_COMPLETED'
            suggested_next_step = 'NO_FURTHER_AGENT_ACTION'
        else:
            status = 'EXTERNAL_ACCOUNTING_RETURNED'
            suggested_next_step = 'ACCOUNTING_CLARIFICATION'
            follow_up_open_item_title = self._external_return_title(accounting_analysis)
            follow_up = await self._ensure_follow_up_open_item(
                case_id=payload.case_id,
                title=follow_up_open_item_title,
                description=self._external_return_description(accounting_analysis, payload.note),
                document_ref=outside_item.document_ref,
                accounting_ref=accounting_analysis.accounting_review_ref,
                source='external_accounting_process',
            )
            follow_up_open_item_id = follow_up.item_id
            problem = await self.problem_service.add_case(
                case_id=payload.case_id,
                title='External accounting returned',
                details=self._external_return_description(accounting_analysis, payload.note),
                severity='MEDIUM',
                exception_type='EXTERNAL_ACCOUNTING_RETURNED',
                document_ref=outside_item.document_ref,
                accounting_ref=accounting_analysis.accounting_review_ref,
                created_by=payload.decided_by,
            )
            problem_case_id = problem.problem_id

        result = ExternalAccountingProcessResolutionResult(
            case_id=payload.case_id,
            accounting_review_ref=accounting_analysis.accounting_review_ref,
            outside_process_open_item_id=outside_item.item_id,
            outside_process_open_item_title=outside_item.title,
            decision=payload.decision,
            status=status,
            suggested_next_step=suggested_next_step,
            resolution_note=payload.note,
            follow_up_open_item_id=follow_up_open_item_id,
            follow_up_open_item_title=follow_up_open_item_title,
            problem_case_id=problem_case_id,
            resolved_by=payload.decided_by,
            execution_allowed=False,
            external_write_performed=False,
            summary=self._external_resolution_summary(payload.decision, outside_item.title, payload.note),
        )

        await self.audit_service.log_event(
            {
                'event_id': str(uuid.uuid4()),
                'case_id': payload.case_id,
                'source': payload.source,
                'document_ref': outside_item.document_ref,
                'accounting_ref': accounting_analysis.accounting_review_ref,
                'agent_name': 'external-accounting-process',
                'approval_status': 'APPROVED' if payload.decision == 'COMPLETED' else 'REJECTED',
                'action': self._external_resolution_action(payload.decision),
                'result': result.summary,
                'llm_output': result.model_dump(mode='json'),
            }
        )
        return result


    async def complete_external_return_clarification(
        self,
        payload: ExternalReturnClarificationCompletionInput,
    ) -> ExternalReturnClarificationCompletionResult:
        chronology = await self.audit_service.by_case(payload.case_id, limit=500)
        accounting_analysis = self._latest_accounting_analysis(chronology)
        if accounting_analysis is None:
            raise ValueError('Kein Accounting-Analyseergebnis fuer diesen Case vorhanden.')

        external_resolution = self._latest_external_accounting_process_resolution(chronology, accounting_analysis.accounting_review_ref)
        if external_resolution is None or external_resolution.decision != 'RETURNED':
            raise ValueError('Re-Klaerabschluss ist erst nach EXTERNAL_ACCOUNTING_RETURNED moeglich.')

        existing_completion = self._latest_external_return_clarification_completion(chronology, accounting_analysis.accounting_review_ref)
        if existing_completion is not None:
            raise ValueError('Der externe Ruecklauf wurde fuer diesen Case bereits erneut geklaert.')

        if not external_resolution.follow_up_open_item_id:
            raise ValueError('Kein offenes Re-Klaer-Open-Item fuer diesen Case referenziert.')

        open_items = await self.open_items_service.list_by_case(payload.case_id)
        clarification_item = self._find_active_item_by_id(open_items, external_resolution.follow_up_open_item_id)
        if clarification_item is None:
            raise ValueError('Kein offenes Re-Klaer-Open-Item fuer diesen Case gefunden.')

        await self.open_items_service.update_status(clarification_item.item_id, 'COMPLETED')

        result = ExternalReturnClarificationCompletionResult(
            case_id=payload.case_id,
            accounting_review_ref=accounting_analysis.accounting_review_ref,
            external_return_open_item_id=clarification_item.item_id,
            external_return_open_item_title=clarification_item.title,
            external_resolution_ref=external_resolution.outside_process_open_item_id,
            status='EXTERNAL_RETURN_CLARIFICATION_COMPLETED',
            suggested_next_step='NO_FURTHER_AGENT_ACTION',
            clarification_note=payload.note,
            problem_case_id=external_resolution.problem_case_id,
            clarified_by=payload.decided_by,
            execution_allowed=False,
            external_write_performed=False,
            summary=self._external_return_clarification_summary(clarification_item.title, payload.note),
        )

        await self.audit_service.log_event(
            {
                'event_id': str(uuid.uuid4()),
                'case_id': payload.case_id,
                'source': payload.source,
                'document_ref': clarification_item.document_ref,
                'accounting_ref': accounting_analysis.accounting_review_ref,
                'agent_name': 'external-return-clarification',
                'approval_status': 'APPROVED',
                'action': 'EXTERNAL_RETURN_CLARIFICATION_COMPLETED',
                'result': result.summary,
                'llm_output': result.model_dump(mode='json'),
            }
        )
        return result
    def _latest_accounting_analysis(self, chronology: list[AuditRecord]) -> AccountingAnalysisResult | None:
        for event in reversed(chronology):
            if event.action != 'ACCOUNTING_ANALYSIS_COMPLETED' or event.llm_output is None:
                continue
            payload = self._normalize_payload(event.llm_output)
            return AccountingAnalysisResult.model_validate(payload)
        return None

    def _latest_operator_review(
        self,
        chronology: list[AuditRecord],
        accounting_review_ref: str,
    ) -> AccountingOperatorReviewDecisionResult | None:
        for event in reversed(chronology):
            if event.action not in {'ACCOUNTING_OPERATOR_REVIEW_CONFIRMED', 'ACCOUNTING_OPERATOR_REVIEW_REJECTED'}:
                continue
            if event.llm_output is None:
                continue
            payload = self._normalize_payload(event.llm_output)
            result = AccountingOperatorReviewDecisionResult.model_validate(payload)
            if result.accounting_review_ref == accounting_review_ref:
                return result
        return None

    def _latest_manual_handoff(
        self,
        chronology: list[AuditRecord],
        accounting_review_ref: str,
    ) -> AccountingManualHandoffResult | None:
        for event in reversed(chronology):
            if event.action != 'ACCOUNTING_MANUAL_HANDOFF_READY' or event.llm_output is None:
                continue
            payload = self._normalize_payload(event.llm_output)
            result = AccountingManualHandoffResult.model_validate(payload)
            if result.accounting_review_ref == accounting_review_ref:
                return result
        return None

    def _latest_manual_handoff_resolution(
        self,
        chronology: list[AuditRecord],
        accounting_review_ref: str,
    ) -> AccountingManualHandoffResolutionResult | None:
        for event in reversed(chronology):
            if event.action not in {'ACCOUNTING_MANUAL_HANDOFF_COMPLETED', 'ACCOUNTING_MANUAL_HANDOFF_RETURNED'}:
                continue
            if event.llm_output is None:
                continue
            payload = self._normalize_payload(event.llm_output)
            result = AccountingManualHandoffResolutionResult.model_validate(payload)
            if result.accounting_review_ref == accounting_review_ref:
                return result
        return None

    def _latest_clarification_completion(
        self,
        chronology: list[AuditRecord],
        accounting_review_ref: str,
    ) -> AccountingClarificationCompletionResult | None:
        for event in reversed(chronology):
            if event.action != 'ACCOUNTING_CLARIFICATION_COMPLETED':
                continue
            if event.llm_output is None:
                continue
            payload = self._normalize_payload(event.llm_output)
            result = AccountingClarificationCompletionResult.model_validate(payload)
            if result.accounting_review_ref == accounting_review_ref:
                return result
        return None


    def _latest_external_return_clarification_completion(
        self,
        chronology: list[AuditRecord],
        accounting_review_ref: str,
    ) -> ExternalReturnClarificationCompletionResult | None:
        for event in reversed(chronology):
            if event.action != 'EXTERNAL_RETURN_CLARIFICATION_COMPLETED':
                continue
            if event.llm_output is None:
                continue
            payload = self._normalize_payload(event.llm_output)
            result = ExternalReturnClarificationCompletionResult.model_validate(payload)
            if result.accounting_review_ref == accounting_review_ref:
                return result
        return None
    def _latest_external_accounting_process_resolution(
        self,
        chronology: list[AuditRecord],
        accounting_review_ref: str,
    ) -> ExternalAccountingProcessResolutionResult | None:
        for event in reversed(chronology):
            if event.action not in {'EXTERNAL_ACCOUNTING_COMPLETED', 'EXTERNAL_ACCOUNTING_RETURNED'}:
                continue
            if event.llm_output is None:
                continue
            payload = self._normalize_payload(event.llm_output)
            result = ExternalAccountingProcessResolutionResult.model_validate(payload)
            if result.accounting_review_ref == accounting_review_ref:
                return result
        return None

    def _outside_agent_context(self, chronology: list[AuditRecord], accounting_review_ref: str) -> dict[str, object] | None:
        clarification = self._latest_clarification_completion(chronology, accounting_review_ref)
        if clarification is not None:
            return {
                'origin': 'clarification_completion',
                'outside_process_open_item_id': clarification.outside_process_open_item_id,
                'outside_process_open_item_title': clarification.outside_process_open_item_title,
                'problem_case_id': clarification.problem_case_id,
                'document_ref': self._document_ref_for_accounting_ref(chronology, accounting_review_ref),
            }
        handoff_resolution = self._latest_manual_handoff_resolution(chronology, accounting_review_ref)
        if handoff_resolution is not None and handoff_resolution.decision == 'COMPLETED':
            return {
                'origin': 'manual_handoff_completed',
                'outside_process_open_item_id': handoff_resolution.outside_process_open_item_id,
                'outside_process_open_item_title': handoff_resolution.outside_process_open_item_title,
                'problem_case_id': handoff_resolution.problem_case_id,
                'document_ref': self._document_ref_for_accounting_ref(chronology, accounting_review_ref),
            }
        return None

    def _normalize_payload(self, payload: object) -> object:
        if isinstance(payload, str):
            try:
                return json.loads(payload)
            except Exception:
                return payload
        return payload

    def _find_active_review_item(
        self,
        items: list[OpenItem],
        title: str,
        accounting_ref: str,
    ) -> OpenItem | None:
        for item in items:
            if item.title != title:
                continue
            if item.accounting_ref != accounting_ref:
                continue
            if item.status not in _ACTIVE_ITEM_STATUSES:
                continue
            return item
        return None

    def _find_active_item_by_id(self, items: list[OpenItem], item_id: str) -> OpenItem | None:
        for item in items:
            if item.item_id != item_id:
                continue
            if item.status not in _ACTIVE_ITEM_STATUSES:
                continue
            return item
        return None

    async def _ensure_follow_up_open_item(
        self,
        *,
        case_id: str,
        title: str,
        description: str,
        document_ref: str | None,
        accounting_ref: str,
        source: str,
    ) -> OpenItem:
        existing = await self.open_items_service.list_by_case(case_id)
        for item in existing:
            if item.title == title and item.accounting_ref == accounting_ref and item.status in _ACTIVE_ITEM_STATUSES:
                return item
        return await self.open_items_service.create_item(
            case_id=case_id,
            title=title,
            description=description,
            source=source,
            document_ref=document_ref,
            accounting_ref=accounting_ref,
        )

    def _review_item_title(self, analysis: AccountingAnalysisResult) -> str:
        if analysis.booking_candidate_type == 'REMINDER_REFERENCE_CHECK':
            return 'Mahnungsbezug pruefen'
        return 'Buchungsvorschlag pruefen'

    def _clarification_title(self, analysis: AccountingAnalysisResult) -> str:
        if analysis.booking_candidate_type == 'REMINDER_REFERENCE_CHECK':
            return 'Mahnungsbezug klaeren'
        return 'Buchungsvorschlag klaeren'

    def _manual_handoff_title(self, analysis: AccountingAnalysisResult) -> str:
        if analysis.booking_candidate_type == 'REMINDER_REFERENCE_CHECK':
            return 'Manuelle Reminder-Weiterbearbeitung uebergeben'
        return 'Manuelle Accounting-Uebergabe durchfuehren'

    def _manual_handoff_return_title(self, analysis: AccountingAnalysisResult) -> str:
        if analysis.booking_candidate_type == 'REMINDER_REFERENCE_CHECK':
            return 'Manuelle Reminder-Uebergabe klaeren'
        return 'Manuelle Accounting-Uebergabe klaeren'

    def _manual_handoff_description(
        self,
        analysis: AccountingAnalysisResult,
        operator_review: AccountingOperatorReviewDecisionResult,
        handoff_note: str | None,
    ) -> str:
        counterparty = analysis.supplier_or_counterparty_hint.value or '-'
        invoice_ref = analysis.invoice_reference_hint.value or '-'
        amount = analysis.amount_summary.total_amount.value or '-'
        currency = analysis.amount_summary.currency.value or ''
        note = handoff_note.strip() if handoff_note else '-'
        return (
            f'Bestaetigter Vorschlag {analysis.booking_candidate_type} fuer {counterparty}; '
            f'Referenz={invoice_ref}; Betrag={amount} {currency}; '
            f'naechster manueller Schritt ausserhalb Frya; review_note={operator_review.decision_note or "-"}; '
            f'handoff_note={note}; kein Akaunting-Write, keine Finalisierung, keine Zahlung.'
        )

    def _manual_handoff_summary(self, analysis: AccountingAnalysisResult, open_item_title: str, handoff_note: str | None) -> str:
        note = handoff_note.strip() if handoff_note else '-'
        return (
            f'status=READY_FOR_MANUAL_ACCOUNTING;candidate={analysis.booking_candidate_type};'
            f'next=MANUAL_ACCOUNTING_WORK;open_item={open_item_title};note={note};execution_allowed=false'
        )

    def _external_process_title(self, analysis: AccountingAnalysisResult) -> str:
        if analysis.booking_candidate_type == 'REMINDER_REFERENCE_CHECK':
            return 'Externen Reminder-Abschluss dokumentieren'
        return 'Externen Accounting-Abschluss dokumentieren'

    def _external_return_title(self, analysis: AccountingAnalysisResult) -> str:
        if analysis.booking_candidate_type == 'REMINDER_REFERENCE_CHECK':
            return 'Externen Reminder-Ruecklauf klaeren'
        return 'Externen Accounting-Ruecklauf klaeren'

    def _external_process_description(self, analysis: AccountingAnalysisResult, note: str | None) -> str:
        summary_note = note.strip() if note else '-'
        return (
            f'Externe menschliche Accounting-Bearbeitung fuer {analysis.booking_candidate_type} dokumentieren; '
            f'naechster Schritt ausserhalb Frya; note={summary_note}; kein Akaunting-Write, keine Finalisierung, keine Zahlung.'
        )

    def _external_return_description(self, analysis: AccountingAnalysisResult, note: str | None) -> str:
        summary_note = note.strip() if note else '-'
        return (
            f'Externe menschliche Accounting-Bearbeitung fuer {analysis.booking_candidate_type} kam mit Ruecklauf zurueck; '
            f'next=ACCOUNTING_CLARIFICATION; note={summary_note}; kein Akaunting-Write, keine Finalisierung, keine Zahlung.'
        )

    def _manual_handoff_return_description(self, analysis: AccountingAnalysisResult, resolution_note: str | None) -> str:
        note = resolution_note.strip() if resolution_note else '-'
        return (
            f'Manueller Accounting-Handoff fuer {analysis.booking_candidate_type} konnte nicht sauber uebernommen werden; '
            f'next=ACCOUNTING_CLARIFICATION; note={note}; kein Akaunting-Write, keine Finalisierung, keine Zahlung.'
        )

    def _clarification_completion_summary(self, clarification_item_title: str, clarification_note: str | None) -> str:
        note = clarification_note.strip() if clarification_note else '-'
        return (
            f'status=ACCOUNTING_CLARIFICATION_COMPLETED;next=OUTSIDE_AGENT_ACCOUNTING_PROCESS;'
            f'open_item={clarification_item_title};note={note};execution_allowed=false'
        )


    def _external_return_clarification_summary(self, clarification_item_title: str, clarification_note: str | None) -> str:
        note = clarification_note.strip() if clarification_note else '-'
        return (
            f'status=EXTERNAL_RETURN_CLARIFICATION_COMPLETED;next=NO_FURTHER_AGENT_ACTION;'
            f'open_item={clarification_item_title};note={note};execution_allowed=false'
        )
    def _external_resolution_summary(self, decision: str, outside_item_title: str, resolution_note: str | None) -> str:
        note = resolution_note.strip() if resolution_note else '-'
        if decision == 'COMPLETED':
            return (
                f'status=EXTERNAL_ACCOUNTING_COMPLETED;next=NO_FURTHER_AGENT_ACTION;'
                f'open_item={outside_item_title};note={note};execution_allowed=false'
            )
        return (
            f'status=EXTERNAL_ACCOUNTING_RETURNED;next=ACCOUNTING_CLARIFICATION;'
            f'open_item={outside_item_title};note={note};execution_allowed=false'
        )

    def _clarification_completion_summary(self, clarification_item_title: str, clarification_note: str | None) -> str:
        note = clarification_note.strip() if clarification_note else '-'
        return (
            f'status=ACCOUNTING_CLARIFICATION_COMPLETED;next=OUTSIDE_AGENT_ACCOUNTING_PROCESS;'
            f'open_item={clarification_item_title};note={note};execution_allowed=false'
        )

    def _manual_handoff_resolution_summary(
        self,
        decision: str,
        handoff_item_title: str,
        resolution_note: str | None,
    ) -> str:
        note = resolution_note.strip() if resolution_note else '-'
        if decision == 'COMPLETED':
            return (
                f'status=MANUAL_HANDOFF_COMPLETED;next=OUTSIDE_AGENT_ACCOUNTING_PROCESS;'
                f'open_item={handoff_item_title};note={note};execution_allowed=false'
            )
        return (
            f'status=MANUAL_HANDOFF_RETURNED_FOR_CLARIFICATION;next=ACCOUNTING_CLARIFICATION;'
            f'open_item={handoff_item_title};note={note};execution_allowed=false'
        )

    def _document_ref_from_review(
        self,
        operator_review: AccountingOperatorReviewDecisionResult,
        chronology: list[AuditRecord],
    ) -> str | None:
        for event in reversed(chronology):
            if event.accounting_ref == operator_review.accounting_review_ref and event.document_ref:
                return event.document_ref
        return None

    def _document_ref_for_accounting_ref(self, chronology: list[AuditRecord], accounting_review_ref: str) -> str | None:
        for event in reversed(chronology):
            if event.accounting_ref == accounting_review_ref and event.document_ref:
                return event.document_ref
        return None

        for event in reversed(chronology):
            if event.accounting_ref == operator_review.accounting_review_ref and event.document_ref:
                return event.document_ref
        return None

    def _follow_up_description(self, analysis: AccountingAnalysisResult, decision_note: str | None) -> str:
        note = decision_note.strip() if decision_note else '-'
        return (
            f'Operatorische Ablehnung fuer {analysis.booking_candidate_type};'
            f' next=ACCOUNTING_CLARIFICATION; note={note}'
        )

    def _summary(
        self,
        analysis: AccountingAnalysisResult,
        decision: str,
        suggested_next_step: str,
        decision_note: str | None,
    ) -> str:
        note = decision_note.strip() if decision_note else '-'
        return (
            f'decision={decision};candidate={analysis.booking_candidate_type};'
            f'next={suggested_next_step};note={note};execution_allowed=false'
        )

    def _audit_action(self, decision: str) -> str:
        if decision == 'CONFIRMED':
            return 'ACCOUNTING_OPERATOR_REVIEW_CONFIRMED'
        return 'ACCOUNTING_OPERATOR_REVIEW_REJECTED'

    def _manual_handoff_resolution_action(self, decision: str) -> str:
        if decision == 'COMPLETED':
            return 'ACCOUNTING_MANUAL_HANDOFF_COMPLETED'
        return 'ACCOUNTING_MANUAL_HANDOFF_RETURNED'

    def _external_resolution_action(self, decision: str) -> str:
        if decision == 'COMPLETED':
            return 'EXTERNAL_ACCOUNTING_COMPLETED'
        return 'EXTERNAL_ACCOUNTING_RETURNED'








