from __future__ import annotations

from enum import Enum

from pydantic import BaseModel


class BankProbeResult(str, Enum):
    MATCH_FOUND = 'MATCH_FOUND'
    CANDIDATE_FOUND = 'CANDIDATE_FOUND'
    NO_MATCH_FOUND = 'NO_MATCH_FOUND'
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
    actor: str = 'system:bank_transaction_probe_v1.1'
    is_read_only: bool = True
    bank_write_executed: bool = False


class BankAccountSummary(BaseModel):
    """Lightweight summary of a bank account from Akaunting."""
    account_id: str | int | None = None
    name: str | None = None
    number: str | None = None
    currency_code: str | None = None
    balance: float | None = None
