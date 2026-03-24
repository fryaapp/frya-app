from __future__ import annotations

from enum import Enum

from pydantic import BaseModel


class BankProbeResult(str, Enum):
    MATCH_FOUND = 'MATCH_FOUND'
    CANDIDATE_FOUND = 'CANDIDATE_FOUND'
    NO_MATCH_FOUND = 'NO_MATCH_FOUND'
    # V1.2: feed reachable but returned 0 transactions (distinct from NO_MATCH_FOUND)
    NO_TRANSACTIONS_AVAILABLE = 'NO_TRANSACTIONS_AVAILABLE'
    AMBIGUOUS_MATCH = 'AMBIGUOUS_MATCH'
    PROBE_ERROR = 'PROBE_ERROR'
    BANK_UNAVAILABLE = 'BANK_UNAVAILABLE'


class MatchQuality(str, Enum):
    HIGH = 'HIGH'
    MEDIUM = 'MEDIUM'
    LOW = 'LOW'


class TransactionCandidate(BaseModel):
    """A single scored transaction candidate from a bank probe.

    Conservative: purely read-only data. No booking, no write, no payment.
    """
    transaction_id: str | int | None = None
    amount: float | None = None
    currency: str | None = None
    date: str | None = None
    reference: str | None = None
    contact_name: str | None = None
    account_name: str | None = None
    description: str | None = None
    # V1.5: transaction type from source system ('income' | 'expense' | None)
    tx_type: str | None = None
    # Scoring (read-only, advisory only)
    confidence_score: int = 0  # 0-100
    match_quality: MatchQuality = MatchQuality.LOW
    reason_codes: list[str] = []  # e.g. ['AMOUNT_EXACT', 'REFERENCE_MATCH', 'TYPE_MISMATCH']


class FeedStatus(BaseModel):
    """Read-only metadata about the banking feed. Not financial truth.

    V1.2: attached to every probe result so operators can see whether the
    feed was reachable and how many transactions were available for matching.
    """
    reachable: bool = False
    source_url: str | None = None
    accounts_available: int = 0
    transactions_total: int = 0   # raw count from feed before client-side filter
    note: str = ''


class BankTransactionProbeResult(BaseModel):
    """Result of a read-only bank transaction probe.

    Safety invariants (asserted by caller):
    - is_read_only is always True
    - bank_write_executed is always False
    """
    result: BankProbeResult
    probe_fields: dict
    # V1: raw matches list (backward compat)
    matches: list[dict]
    # V1.1: structured candidates with scoring
    candidates: list[TransactionCandidate] = []
    note: str
    actor: str = 'system:bank_transaction_probe_v1.2'
    is_read_only: bool = True
    bank_write_executed: bool = False
    # V1.2: live feed metadata
    feed_status: FeedStatus | None = None
    # V1.2: True when probe ran on caller-supplied test data, not live Buchhaltung
    is_test_data: bool = False


# ---------------------------------------------------------------------------
# V1.5 — Reconciliation Context
# ---------------------------------------------------------------------------

class ReconciliationSignal(str, Enum):
    """Operator-facing traffic-light for a reconciliation case.

    Advisory only. Does not trigger any write or decision.
    """
    PLAUSIBLE = 'PLAUSIBLE'       # strong match — proceed to review
    UNCLEAR = 'UNCLEAR'           # weak or ambiguous — manual inspection needed
    CONFLICT = 'CONFLICT'         # contradicting signals (e.g. type mismatch)
    MISSING_DATA = 'MISSING_DATA' # no candidate or critical context absent


class ReconciliationDimensionStatus(str, Enum):
    MATCH = 'MATCH'
    PARTIAL = 'PARTIAL'
    CONFLICT = 'CONFLICT'
    MISSING = 'MISSING'
    UNKNOWN = 'UNKNOWN'


class ReviewGuidanceLevel(str, Enum):
    CONFIRMABLE = 'CONFIRMABLE'
    CLARIFICATION_NEEDED = 'CLARIFICATION_NEEDED'
    REJECT_RECOMMENDED = 'REJECT_RECOMMENDED'
    NOT_CONFIRMABLE = 'NOT_CONFIRMABLE'


class ReconciliationComparisonRow(BaseModel):
    field_key: str
    label: str
    document_value: str | float | None = None
    accounting_value: str | float | None = None
    banking_value: str | float | None = None
    status: ReconciliationDimensionStatus = ReconciliationDimensionStatus.UNKNOWN
    note: str = ''


class ReconciliationOpenItemSummary(BaseModel):
    item_id: str
    title: str
    status: str
    description: str | None = None
    due_at: str | None = None


class ReconciliationDecisionTrail(BaseModel):
    review_decision: str | None = None
    review_outcome: str | None = None
    review_by: str | None = None
    handoff_status: str | None = None
    handoff_ready_status: str | None = None
    handoff_resolution_status: str | None = None
    clarification_status: str | None = None
    external_status: str | None = None
    current_stage: str | None = None


class ReconciliationContext(BaseModel):
    """V1.5: Read-only reconciliation work context for an operator.

    Bundles document, accounting, and banking context into one view.
    Advisory only. No financial system is written.

    Safety invariants:
    - is_read_only is always True
    - bank_write_executed is always False
    - no_financial_write is always True
    """
    case_id: str
    context_version: str = 'reconciliation-context-v1.6'
    built_at: str               # ISO timestamp
    context_ref: str
    review_anchor_ref: str

    # Document / case context (from probe fields)
    doc_reference: str | None = None
    doc_amount: float | None = None
    doc_currency: str | None = None
    doc_date: str | None = None
    doc_contact: str | None = None
    doc_type: str | None = None  # 'income' | 'expense' | 'unknown'

    # Banking probe summary
    bank_result: str            # BankProbeResult.value
    bank_note: str = ''
    bank_feed_reachable: bool = False
    bank_feed_total: int = 0
    best_candidate: TransactionCandidate | None = None
    all_candidates: list[TransactionCandidate] = []

    # Accounting context (from internal booking lookup — read-only)
    accounting_result: str | None = None  # 'FOUND'|'NOT_FOUND'|'AMBIGUOUS'|'UNAVAILABLE'
    accounting_doc_id: str | None = None
    accounting_doc_reference: str | None = None
    accounting_contact: str | None = None
    accounting_doc_status: str | None = None
    accounting_doc_amount: float | None = None
    accounting_note: str = ''
    accounting_probe_result: str | None = None
    accounting_probe_note: str = ''
    accounting_probe_matches: list[dict] = []

    # Match analysis — operator-facing signals
    match_signal: ReconciliationSignal = ReconciliationSignal.MISSING_DATA
    pro_match: list[str] = []        # reasons supporting a match
    contra_match: list[str] = []     # reasons against
    missing_data: list[str] = []     # what is absent / unresolved
    operator_summary: list[str] = []
    best_candidate_reason_codes: list[str] = []
    comparison_rows: list[ReconciliationComparisonRow] = []
    operator_guidance: str = ''
    review_guidance: ReviewGuidanceLevel = ReviewGuidanceLevel.NOT_CONFIRMABLE
    confirm_allowed: bool = False
    candidate_count: int = 0
    review_trail: ReconciliationDecisionTrail | None = None
    active_open_items: list[ReconciliationOpenItemSummary] = []

    # Decision history (from audit log — read-only)
    latest_review_decision: str | None = None   # 'CONFIRMED' | 'REJECTED'
    latest_review_outcome: str | None = None    # 'BANK_RECONCILIATION_CONFIRMED' etc.
    latest_review_by: str | None = None
    latest_handoff_status: str | None = None    # 'BANK_MANUAL_HANDOFF_COMPLETED' etc.
    latest_handoff_ready_status: str | None = None
    latest_handoff_resolution_status: str | None = None
    latest_clarification_status: str | None = None
    latest_external_status: str | None = None

    # Open follow-up items
    open_items_count: int = 0
    open_items_titles: list[str] = []

    # Operator-facing plain-text next action
    next_action: str = ''

    # Safety invariants
    is_read_only: bool = True
    bank_write_executed: bool = False
    no_financial_write: bool = True


class BankAccountSummary(BaseModel):
    """Lightweight summary of a bank account from Buchhaltung."""
    account_id: str | int | None = None
    name: str | None = None
    number: str | None = None
    currency_code: str | None = None
    balance: float | None = None


# ---------------------------------------------------------------------------
# V1.3 — Operator Banking Reconciliation Review
# ---------------------------------------------------------------------------

class BankReconciliationDecision(str, Enum):
    """Operator's decision on a bank transaction candidate.

    CONFIRMED: candidate is accepted as matching the case (no Buchhaltung write).
    REJECTED:  candidate is dismissed; follow-up clarification needed.
    """
    CONFIRMED = 'CONFIRMED'
    REJECTED = 'REJECTED'


class BankReconciliationReviewInput(BaseModel):
    """Input payload for an operator banking review decision.

    Conservative: contains a snapshot of the candidate that was reviewed,
    plus the operator's decision. No financial system is written.
    """
    case_id: str
    # Snapshot of the candidate under review (from a prior probe result)
    transaction_id: str | int | None = None
    candidate_amount: float | None = None
    candidate_currency: str | None = None
    candidate_date: str | None = None
    candidate_reference: str | None = None
    candidate_contact: str | None = None
    candidate_description: str | None = None
    confidence_score: int = 0
    match_quality: str = 'LOW'
    reason_codes: list[str] = []
    tx_type: str | None = None
    # Probe result context
    probe_result: str = ''           # BankProbeResult enum value
    probe_note: str = ''
    workbench_ref: str
    workbench_signal: str = ''
    workbench_guidance: str = ''
    review_guidance: str = ''
    candidate_rank: int | None = None
    # Operator decision
    decision: BankReconciliationDecision
    decision_note: str = ''
    decided_by: str = 'operator'
    source: str = 'bank-reconciliation-review'


class BankReconciliationReviewResult(BaseModel):
    """Result returned after an operator banking review decision.

    Safety invariants:
    - bank_write_executed is always False
    - no_financial_write is always True
    """
    review_id: str
    case_id: str
    transaction_id: str | int | None = None
    workbench_ref: str
    workbench_signal: str
    decision: BankReconciliationDecision
    outcome_status: str   # 'BANK_RECONCILIATION_CONFIRMED' | 'BANK_RECONCILIATION_REJECTED'
    decision_note: str
    decided_by: str
    review_guidance: str = ''
    confirm_allowed: bool = False
    candidate_rank: int | None = None
    open_item_id: str | None = None
    open_item_title: str | None = None
    follow_up_open_item_id: str | None = None
    follow_up_open_item_title: str | None = None
    audit_event_id: str
    summary: str
    # Safety fields — always False / True
    bank_write_executed: bool = False
    no_financial_write: bool = True


# ---------------------------------------------------------------------------
# V1.4 — Banking Manual Handoff + Clarification paths
# ---------------------------------------------------------------------------

class BankManualHandoffDecision(str, Enum):
    """Outcome of a banking manual handoff attempt.

    COMPLETED: external manual reconciliation succeeded — case can be closed.
    RETURNED:  external party returned the case; clarification needed before retry.
    """
    COMPLETED = 'COMPLETED'
    RETURNED = 'RETURNED'


class BankingHandoffResolutionDecision(str, Enum):
    COMPLETED = 'COMPLETED'
    RETURNED = 'RETURNED'


class ExternalBankingProcessDecision(str, Enum):
    COMPLETED = 'COMPLETED'


class BankingHandoffReadyInput(BaseModel):
    case_id: str
    review_ref: str
    workbench_ref: str
    transaction_id: str | int | None = None
    handoff_note: str = ''
    handed_off_by: str = 'operator'
    source: str = 'banking-handoff-ready'


class BankingHandoffReadyResult(BaseModel):
    handoff_id: str
    case_id: str
    review_ref: str
    workbench_ref: str
    transaction_id: str | int | None = None
    candidate_reference: str | None = None
    handoff_state: str = 'READY'
    outcome_status: str = 'BANKING_HANDOFF_READY'
    handoff_note: str = ''
    handed_off_by: str
    handoff_guidance: str
    next_manual_step: str
    required_external_action: str
    closed_open_item_id: str | None = None
    closed_open_item_title: str | None = None
    handoff_open_item_id: str | None = None
    handoff_open_item_title: str | None = None
    audit_event_id: str
    summary: str
    bank_write_executed: bool = False
    no_financial_write: bool = True


class BankingHandoffResolutionInput(BaseModel):
    case_id: str
    handoff_ref: str
    decision: BankingHandoffResolutionDecision
    resolution_note: str = ''
    resolved_by: str = 'operator'
    source: str = 'banking-handoff-resolution'


class BankingHandoffResolutionResult(BaseModel):
    resolution_id: str
    handoff_ref: str
    case_id: str
    review_ref: str
    workbench_ref: str
    transaction_id: str | int | None = None
    candidate_reference: str | None = None
    decision: BankingHandoffResolutionDecision
    status: str
    suggested_next_step: str
    resolution_note: str = ''
    resolved_by: str
    handoff_open_item_id: str | None = None
    handoff_open_item_title: str | None = None
    follow_up_open_item_id: str | None = None
    follow_up_open_item_title: str | None = None
    outside_process_open_item_id: str | None = None
    outside_process_open_item_title: str | None = None
    audit_event_id: str
    summary: str
    bank_write_executed: bool = False
    no_financial_write: bool = True


class BankingClarificationCompletionInput(BaseModel):
    case_id: str
    clarification_ref: str
    clarification_note: str = ''
    clarified_by: str = 'operator'
    source: str = 'banking-clarification-complete'


class BankingClarificationCompletionResult(BaseModel):
    clarification_completion_id: str
    clarification_ref: str
    case_id: str
    handoff_ref: str
    review_ref: str
    workbench_ref: str
    transaction_id: str | int | None = None
    candidate_reference: str | None = None
    status: str = 'BANKING_CLARIFICATION_COMPLETED'
    clarification_state: str = 'COMPLETED'
    clarification_note: str = ''
    clarified_by: str
    clarification_open_item_id: str | None = None
    clarification_open_item_title: str | None = None
    outside_process_open_item_id: str | None = None
    outside_process_open_item_title: str | None = None
    audit_event_id: str
    suggested_next_step: str = 'OUTSIDE_AGENT_BANKING_PROCESS'
    summary: str
    bank_write_executed: bool = False
    no_financial_write: bool = True


class ExternalBankingProcessCompletionInput(BaseModel):
    case_id: str
    resolution_note: str = ''
    resolved_by: str = 'operator'
    source: str = 'external-banking-process-complete'


class ExternalBankingProcessCompletionResult(BaseModel):
    external_resolution_id: str
    case_id: str
    transaction_id: str | int | None = None
    review_ref: str
    workbench_ref: str
    handoff_ref: str | None = None
    clarification_ref: str | None = None
    candidate_reference: str | None = None
    decision: ExternalBankingProcessDecision = ExternalBankingProcessDecision.COMPLETED
    status: str = 'EXTERNAL_BANKING_PROCESS_COMPLETED'
    external_banking_outcome: str = 'MANUALLY_COMPLETED_OUTSIDE_FRYA'
    no_further_agent_action_reason: str = 'Externer manueller Banking-Prozess wurde dokumentiert abgeschlossen.'
    resolution_note: str = ''
    resolved_by: str
    outside_process_open_item_id: str | None = None
    outside_process_open_item_title: str | None = None
    source_internal_status: str
    audit_event_id: str
    suggested_next_step: str = 'NO_FURTHER_AGENT_ACTION'
    summary: str
    bank_write_executed: bool = False
    no_financial_write: bool = True


class BankManualHandoffInput(BaseModel):
    """Operator input after initiating / completing manual banking reconciliation.

    Conservative: records the outcome of a human action in an external system.
    No write to Buchhaltung, no payment, no finalization.
    """
    case_id: str
    transaction_id: str | int | None = None
    decision: BankManualHandoffDecision
    note: str = ''
    decided_by: str = 'operator'
    source: str = 'bank-manual-handoff'


class BankManualHandoffResult(BaseModel):
    """Result of a banking manual handoff step.

    Safety invariants: bank_write_executed=False, no_financial_write=True.
    """
    handoff_id: str
    case_id: str
    transaction_id: str | int | None = None
    decision: BankManualHandoffDecision
    outcome_status: str    # BANK_MANUAL_HANDOFF_COMPLETED | BANK_MANUAL_HANDOFF_RETURNED
    note: str
    decided_by: str
    closed_open_item_id: str | None = None
    follow_up_open_item_id: str | None = None
    follow_up_open_item_title: str | None = None
    audit_event_id: str
    summary: str
    bank_write_executed: bool = False
    no_financial_write: bool = True


class BankClarificationInput(BaseModel):
    """Operator input to resolve a banking clarification item (after REJECTED or RETURNED).

    Conservative: records that the clarification step is done.
    No write to Buchhaltung, no payment, no finalization.
    """
    case_id: str
    transaction_id: str | int | None = None
    resolution_note: str = ''
    decided_by: str = 'operator'
    source: str = 'bank-clarification'


class BankClarificationResult(BaseModel):
    """Result of completing a banking clarification step.

    Safety invariants: bank_write_executed=False, no_financial_write=True.
    """
    clarification_id: str
    case_id: str
    transaction_id: str | int | None = None
    outcome_status: str    # BANK_CLARIFICATION_COMPLETED
    resolution_note: str
    decided_by: str
    closed_open_item_id: str | None = None
    audit_event_id: str
    summary: str
    bank_write_executed: bool = False
    no_financial_write: bool = True
