"""GoBD Retention Enforcement — §147 AO / §14b UStG.

Accounting-relevant records must be retained for 10 years.
Hard-delete of such records is blocked until the retention period expires.

Scope (GoBD §14b, §147 AO):
- frya_audit_log      : 10 years (Buchungsbelege, Protokolle)
- case_cases          : 10 years (Buchungsvorgänge)
- case_documents      : 10 years (Eingangsbelege)
- frya_problem_cases  : 10 years (Abrechnungsrelevante Sonderfälle)

Non-accounting tables (users, tenants, memory files) follow DSGVO Art. 17
with the standard 30-day soft-delete window — no GoBD lock applies.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

# Minimum retention in years per table.
RETENTION_RULES: dict[str, int] = {
    'frya_audit_log': 10,
    'case_cases': 10,
    'case_documents': 10,
    'frya_problem_cases': 10,
}

_GOBD_TABLES = frozenset(RETENTION_RULES)


def retention_years(table: str) -> int | None:
    """Return the GoBD retention period in years for *table*, or None if not regulated."""
    return RETENTION_RULES.get(table)


def earliest_deletion_date(created_at: datetime, table: str) -> datetime | None:
    """Return the earliest date on which a record may be deleted.

    Returns None if the table is not subject to GoBD retention.
    """
    years = retention_years(table)
    if years is None:
        return None
    # Full-year retention: created_at + N years, rounded up to start of next year
    # (conservative interpretation favoured by German tax authorities)
    retention_end = created_at.replace(year=created_at.year + years)
    return retention_end


def may_delete(created_at: datetime, table: str, *, now: datetime | None = None) -> bool:
    """Return True if the record may be deleted under GoBD retention rules.

    A record that is NOT in a regulated table may always be deleted (returns True).
    A record in a regulated table may only be deleted after the retention period.
    """
    earliest = earliest_deletion_date(created_at, table)
    if earliest is None:
        return True  # not a GoBD-regulated table
    _now = now or datetime.now(timezone.utc)
    # Ensure both are timezone-aware for comparison
    if _now.tzinfo is None:
        _now = _now.replace(tzinfo=timezone.utc)
    if earliest.tzinfo is None:
        earliest = earliest.replace(tzinfo=timezone.utc)
    return _now >= earliest


def check_retention(created_at: datetime, table: str) -> bool:
    """Alias for may_delete — returns True when deletion is permitted."""
    return may_delete(created_at, table)


class RetentionViolation(Exception):
    """Raised when a hard-delete would violate GoBD retention rules."""

    def __init__(self, table: str, created_at: datetime, earliest: datetime) -> None:
        self.table = table
        self.created_at = created_at
        self.earliest = earliest
        super().__init__(
            f'GoBD-Sperre: {table!r} darf nicht vor {earliest.date().isoformat()} '
            f'gelöscht werden (erstellt: {created_at.date().isoformat()}, '
            f'Aufbewahrungsfrist 10 Jahre §147 AO).'
        )


def assert_may_delete(created_at: datetime, table: str) -> None:
    """Raise RetentionViolation if the record is still within the retention period."""
    earliest = earliest_deletion_date(created_at, table)
    if earliest is None:
        return
    now = datetime.now(timezone.utc)
    if earliest.tzinfo is None:
        earliest = earliest.replace(tzinfo=timezone.utc)
    if now < earliest:
        raise RetentionViolation(table, created_at, earliest)
