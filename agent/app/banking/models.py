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
    # Scoring (read-only, advisory only)
    confidence_score: int = 0  # 0-100
    match_quality: MatchQuality = MatchQuality.LOW
    reason_codes: list[str] = []  # e.g. ['AMOUNT_EXACT', 'REFERENCE_MATCH']


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
    # V1.2: True when probe ran on caller-supplied test data, not live Akaunting
    is_test_data: bool = False


class BankAccountSummary(BaseModel):
    """Lightweight summary of a bank account from Akaunting."""
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

    CONFIRMED: candidate is accepted as matching the case (no Akaunting write).
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
    # Probe result context
    probe_result: str = ''           # BankProbeResult enum value
    probe_note: str = ''
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
    decision: BankReconciliationDecision
    outcome_status: str   # 'BANK_RECONCILIATION_CONFIRMED' | 'BANK_RECONCILIATION_REJECTED'
    decision_note: str
    decided_by: str
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


class BankManualHandoffInput(BaseModel):
    """Operator input after initiating / completing manual banking reconciliation.

    Conservative: records the outcome of a human action in an external system.
    No write to Akaunting, no payment, no finalization.
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
    No write to Akaunting, no payment, no finalization.
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
