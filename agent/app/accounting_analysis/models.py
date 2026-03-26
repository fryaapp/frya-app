from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from app.accounting_review.models import AccountingReviewDraft
from app.document_analysis.models import DocumentAnalysisResult, FieldStatus, SourceKind

AccountingDecision = Literal['PROPOSED', 'LOW_CONFIDENCE', 'BLOCKED_FOR_REVIEW']
AccountingSuggestedNextStep = Literal['ACCOUNTING_CONFIRMATION', 'REMINDER_REFERENCE_REVIEW', 'HUMAN_REVIEW']
BookingCandidateType = Literal['INVOICE_STANDARD_EXPENSE', 'REMINDER_REFERENCE_CHECK', 'NO_CANDIDATE']
AccountingRiskSeverity = Literal['INFO', 'WARNING', 'HIGH']
AccountingOperatorDecision = Literal['CONFIRMED', 'REJECTED']
AccountingOperatorOutcomeStatus = Literal[
    'ACCOUNTING_CONFIRMED_PENDING_MANUAL_HANDOFF',
    'ACCOUNTING_REJECTED_REQUIRES_CLARIFICATION',
]
AccountingOperatorNextStep = Literal['MANUAL_ACCOUNTING_HANDOFF', 'ACCOUNTING_CLARIFICATION']
AccountingManualHandoffStatus = Literal['READY_FOR_MANUAL_ACCOUNTING']
AccountingManualHandoffNextStep = Literal['MANUAL_ACCOUNTING_WORK']
AccountingManualHandoffResolutionDecision = Literal['COMPLETED', 'RETURNED']
AccountingManualHandoffResolutionStatus = Literal[
    'MANUAL_HANDOFF_COMPLETED',
    'MANUAL_HANDOFF_RETURNED_FOR_CLARIFICATION',
]
AccountingManualHandoffResolutionNextStep = Literal[
    'OUTSIDE_AGENT_ACCOUNTING_PROCESS',
    'ACCOUNTING_CLARIFICATION',
]
AccountingClarificationCompletionStatus = Literal['ACCOUNTING_CLARIFICATION_COMPLETED']
AccountingClarificationCompletionNextStep = Literal['OUTSIDE_AGENT_ACCOUNTING_PROCESS']
ExternalAccountingProcessResolutionDecision = Literal['COMPLETED', 'RETURNED']
ExternalAccountingProcessResolutionStatus = Literal[
    'EXTERNAL_ACCOUNTING_COMPLETED',
    'EXTERNAL_ACCOUNTING_RETURNED',
]
ExternalAccountingProcessResolutionNextStep = Literal[
    'NO_FURTHER_AGENT_ACTION',
    'ACCOUNTING_CLARIFICATION',
]
ExternalReturnClarificationCompletionStatus = Literal['EXTERNAL_RETURN_CLARIFICATION_COMPLETED']
ExternalReturnClarificationCompletionNextStep = Literal['NO_FURTHER_AGENT_ACTION']

T = TypeVar('T')


class AccountingField(BaseModel, Generic[T]):
    model_config = ConfigDict(extra='forbid')

    value: T | None = None
    status: FieldStatus
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    source_kind: SourceKind = 'NONE'
    evidence_excerpt: str | None = None


class AccountingRisk(BaseModel):
    model_config = ConfigDict(extra='forbid')

    code: str
    severity: AccountingRiskSeverity
    message: str
    related_fields: list[str] = Field(default_factory=list)


class AmountSummary(BaseModel):
    model_config = ConfigDict(extra='forbid')

    total_amount: AccountingField[Decimal]
    currency: AccountingField[str]
    net_amount: AccountingField[Decimal]
    tax_amount: AccountingField[Decimal]


class TaxHint(BaseModel):
    model_config = ConfigDict(extra='forbid')

    rate: AccountingField[str]
    reason: str | None = None


class BookingCandidate(BaseModel):
    model_config = ConfigDict(extra='forbid')

    candidate_type: BookingCandidateType
    counterparty_hint: str | None = None
    invoice_reference_hint: str | None = None
    review_focus: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class AccountingAnalysisInput(BaseModel):
    model_config = ConfigDict(extra='forbid')

    case_id: str
    accounting_review_ref: str
    review_draft: AccountingReviewDraft
    document_analysis_result: DocumentAnalysisResult
    case_context: dict[str, Any] = Field(default_factory=dict)


class AccountingAnalysisResult(BaseModel):
    model_config = ConfigDict(extra='forbid')

    analysis_version: str = 'accounting-analyst-v1'
    case_id: str
    accounting_review_ref: str
    booking_candidate_type: BookingCandidateType
    supplier_or_counterparty_hint: AccountingField[str]
    invoice_reference_hint: AccountingField[str]
    amount_summary: AmountSummary
    due_date_hint: AccountingField[date]
    tax_hint: TaxHint
    booking_candidate: BookingCandidate | None = None
    booking_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    accounting_risks: list[AccountingRisk] = Field(default_factory=list)
    missing_accounting_fields: list[str] = Field(default_factory=list)
    suggested_next_step: AccountingSuggestedNextStep
    global_decision: AccountingDecision
    ready_for_user_approval: bool = False
    ready_for_accounting_confirmation: bool = False
    analysis_summary: str


class AccountingManualHandoffInput(BaseModel):
    model_config = ConfigDict(extra='forbid')

    case_id: str
    decided_by: str
    note: str | None = None
    source: str = 'accounting_manual_handoff'


class AccountingManualHandoffResult(BaseModel):
    model_config = ConfigDict(extra='forbid')

    handoff_version: str = 'accounting-handoff-v1'
    case_id: str
    accounting_review_ref: str
    booking_candidate_type: BookingCandidateType
    status: AccountingManualHandoffStatus
    suggested_next_step: AccountingManualHandoffNextStep
    instruction_headline: str
    instruction_detail: str
    handoff_note: str | None = None
    open_item_id: str
    open_item_title: str
    handoff_marked_by: str
    execution_allowed: bool = False
    external_write_performed: bool = False
    summary: str


class AccountingManualHandoffResolutionInput(BaseModel):
    model_config = ConfigDict(extra='forbid')

    case_id: str
    decision: AccountingManualHandoffResolutionDecision
    decided_by: str
    note: str | None = None
    source: str = 'accounting_manual_handoff_resolution'


class AccountingManualHandoffResolutionResult(BaseModel):
    model_config = ConfigDict(extra='forbid')

    case_id: str
    accounting_review_ref: str
    handoff_open_item_id: str
    handoff_open_item_title: str
    decision: AccountingManualHandoffResolutionDecision
    status: AccountingManualHandoffResolutionStatus
    suggested_next_step: AccountingManualHandoffResolutionNextStep
    resolution_note: str | None = None
    follow_up_open_item_id: str | None = None
    follow_up_open_item_title: str | None = None
    outside_process_open_item_id: str | None = None
    outside_process_open_item_title: str | None = None
    problem_case_id: str | None = None
    resolved_by: str
    execution_allowed: bool = False
    external_write_performed: bool = False
    summary: str


class AccountingClarificationCompletionInput(BaseModel):
    model_config = ConfigDict(extra='forbid')

    case_id: str
    decided_by: str
    note: str | None = None
    source: str = 'accounting_clarification_completion'


class AccountingClarificationCompletionResult(BaseModel):
    model_config = ConfigDict(extra='forbid')

    case_id: str
    accounting_review_ref: str
    clarification_open_item_id: str
    clarification_open_item_title: str
    status: AccountingClarificationCompletionStatus
    suggested_next_step: AccountingClarificationCompletionNextStep
    clarification_note: str | None = None
    outside_process_open_item_id: str | None = None
    outside_process_open_item_title: str | None = None
    problem_case_id: str | None = None
    clarified_by: str
    execution_allowed: bool = False
    external_write_performed: bool = False
    summary: str


class ExternalAccountingProcessResolutionInput(BaseModel):
    model_config = ConfigDict(extra='forbid')

    case_id: str
    decision: ExternalAccountingProcessResolutionDecision
    decided_by: str
    note: str | None = None
    source: str = 'external_accounting_process_resolution'


class ExternalAccountingProcessResolutionResult(BaseModel):
    model_config = ConfigDict(extra='forbid')

    case_id: str
    accounting_review_ref: str
    outside_process_open_item_id: str
    outside_process_open_item_title: str
    decision: ExternalAccountingProcessResolutionDecision
    status: ExternalAccountingProcessResolutionStatus
    suggested_next_step: ExternalAccountingProcessResolutionNextStep
    resolution_note: str | None = None
    follow_up_open_item_id: str | None = None
    follow_up_open_item_title: str | None = None
    problem_case_id: str | None = None
    resolved_by: str
    execution_allowed: bool = False
    external_write_performed: bool = False
    summary: str



class ExternalReturnClarificationCompletionInput(BaseModel):
    model_config = ConfigDict(extra='forbid')

    case_id: str
    decided_by: str
    note: str | None = None
    source: str = 'external_return_clarification_completion'


class ExternalReturnClarificationCompletionResult(BaseModel):
    model_config = ConfigDict(extra='forbid')

    case_id: str
    accounting_review_ref: str
    external_return_open_item_id: str
    external_return_open_item_title: str
    external_resolution_ref: str
    status: ExternalReturnClarificationCompletionStatus
    suggested_next_step: ExternalReturnClarificationCompletionNextStep
    clarification_note: str | None = None
    problem_case_id: str | None = None
    clarified_by: str
    execution_allowed: bool = False
    external_write_performed: bool = False
    summary: str

AccountingReconciliationStatus = Literal['FOUND', 'NOT_FOUND', 'ERROR']


class AccountingReconciliationInput(BaseModel):
    model_config = ConfigDict(extra='forbid')

    case_id: str
    object_type: str
    object_id: str
    triggered_by: str
    note: str | None = None
    source: str = 'accounting_reconciliation_lookup'


class AccountingReconciliationResult(BaseModel):
    model_config = ConfigDict(extra='forbid')

    reconciliation_version: str = 'accounting-reconciliation-v1'
    case_id: str
    object_type: str
    object_id: str
    status: AccountingReconciliationStatus
    raw_data: dict | None = None
    error_detail: str | None = None
    lookup_note: str | None = None
    triggered_by: str
    execution_allowed: bool = False
    external_write_performed: bool = False
    summary: str


class AccountingOperatorReviewDecisionInput(BaseModel):
    model_config = ConfigDict(extra='forbid')

    case_id: str
    decision: AccountingOperatorDecision
    decided_by: str
    decision_note: str | None = None
    source: str = 'accounting_operator_review'


class AccountingOperatorReviewDecisionResult(BaseModel):
    model_config = ConfigDict(extra='forbid')

    case_id: str
    accounting_review_ref: str
    booking_candidate_type: BookingCandidateType
    decision: AccountingOperatorDecision
    decision_note: str | None = None
    review_item_title: str
    review_item_id: str
    outcome_status: AccountingOperatorOutcomeStatus
    suggested_next_step: AccountingOperatorNextStep
    follow_up_open_item_id: str | None = None
    follow_up_open_item_title: str | None = None
    problem_case_id: str | None = None
    manual_handoff: AccountingManualHandoffResult | None = None
    decided_by: str
    execution_allowed: bool = False
    summary: str


