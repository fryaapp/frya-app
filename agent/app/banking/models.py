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
