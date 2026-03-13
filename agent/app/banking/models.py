from __future__ import annotations

from enum import Enum

from pydantic import BaseModel


class BankProbeResult(str, Enum):
    MATCH_FOUND = 'MATCH_FOUND'
    NO_MATCH_FOUND = 'NO_MATCH_FOUND'
    AMBIGUOUS_MATCH = 'AMBIGUOUS_MATCH'
    PROBE_ERROR = 'PROBE_ERROR'
    BANK_UNAVAILABLE = 'BANK_UNAVAILABLE'


class BankTransactionProbeResult(BaseModel):
    """Result of a read-only bank transaction probe.

    Safety invariants:
    - is_read_only is always True
    - bank_write_executed is always False
    """

    result: BankProbeResult
    probe_fields: dict
    matches: list[dict]
    note: str
    actor: str = 'system:bank_transaction_probe_v1'
    is_read_only: bool = True
    bank_write_executed: bool = False


class BankAccountSummary(BaseModel):
    """Lightweight summary of a bank account from Akaunting."""
    account_id: str | int | None
    name: str | None
    number: str | None
    currency_code: str | None
    balance: float | None
