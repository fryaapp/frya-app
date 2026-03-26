"""Tests for GoBD retention enforcement (app/gobd/retention.py)."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.gobd.retention import (
    RETENTION_RULES,
    RetentionViolation,
    assert_may_delete,
    earliest_deletion_date,
    may_delete,
    retention_years,
)

_UTC = timezone.utc


def _dt(year: int, month: int = 1, day: int = 1) -> datetime:
    return datetime(year, month, day, tzinfo=_UTC)


# ---------------------------------------------------------------------------
# retention_years
# ---------------------------------------------------------------------------

def test_retention_years_regulated_tables():
    for table in RETENTION_RULES:
        assert retention_years(table) == 10


def test_retention_years_unknown_table():
    assert retention_years('frya_users') is None
    assert retention_years('nonexistent') is None


# ---------------------------------------------------------------------------
# earliest_deletion_date
# ---------------------------------------------------------------------------

def test_earliest_deletion_date_10_years():
    created = _dt(2020, 5, 15)
    earliest = earliest_deletion_date(created, 'frya_audit_log')
    assert earliest is not None
    assert earliest.year == 2030
    assert earliest.month == 5
    assert earliest.day == 15


def test_earliest_deletion_date_unregulated():
    created = _dt(2020, 1, 1)
    assert earliest_deletion_date(created, 'frya_users') is None


# ---------------------------------------------------------------------------
# may_delete
# ---------------------------------------------------------------------------

def test_may_delete_before_retention_period():
    created = _dt(2020, 1, 1)
    # Now is 2026 — still within 10-year window
    now = _dt(2026, 3, 19)
    for table in RETENTION_RULES:
        assert may_delete(created, table, now=now) is False


def test_may_delete_after_retention_period():
    created = _dt(2010, 1, 1)
    # Now is 2026 — past 10-year window (2010 + 10 = 2020)
    now = _dt(2026, 3, 19)
    for table in RETENTION_RULES:
        assert may_delete(created, table, now=now) is True


def test_may_delete_exactly_at_retention_boundary():
    created = _dt(2016, 6, 1)
    # Exactly at boundary: 2016 + 10 = 2026-06-01
    now = _dt(2026, 6, 1)
    for table in RETENTION_RULES:
        assert may_delete(created, table, now=now) is True


def test_may_delete_unregulated_table_always_true():
    created = _dt(2024, 1, 1)
    now = _dt(2024, 1, 2)
    assert may_delete(created, 'frya_users', now=now) is True
    assert may_delete(created, 'frya_tenants', now=now) is True


def test_may_delete_naive_datetime_treated_as_utc():
    """Naive datetimes (no tzinfo) must not raise — treated as UTC."""
    created = datetime(2020, 1, 1)  # naive
    now = datetime(2026, 3, 19)     # naive
    # Should not raise, should return False (still in retention window)
    result = may_delete(created, 'frya_audit_log', now=now)
    assert result is False


# ---------------------------------------------------------------------------
# assert_may_delete / RetentionViolation
# ---------------------------------------------------------------------------

def test_assert_may_delete_raises_within_retention():
    created = _dt(2020, 1, 1)
    with pytest.raises(RetentionViolation) as exc_info:
        # Pass explicit 'now' via monkeypatching is not needed because 2026 < 2030
        assert_may_delete(created, 'case_cases')
    exc = exc_info.value
    assert exc.table == 'case_cases'
    assert exc.created_at == created
    assert exc.earliest.year == 2030
    assert 'GoBD-Sperre' in str(exc)


def test_assert_may_delete_ok_after_retention():
    # Created 15 years ago
    created = datetime(2000, 1, 1, tzinfo=_UTC)
    # Should not raise — 2000 + 10 = 2010, already past
    assert_may_delete(created, 'frya_audit_log')


def test_assert_may_delete_unregulated_never_raises():
    created = _dt(2024, 1, 1)
    assert_may_delete(created, 'frya_users')  # must not raise


# ---------------------------------------------------------------------------
# RetentionViolation fields
# ---------------------------------------------------------------------------

def test_retention_violation_attributes():
    created = _dt(2020, 3, 1)
    earliest = _dt(2030, 3, 1)
    exc = RetentionViolation('case_documents', created, earliest)
    assert exc.table == 'case_documents'
    assert exc.created_at == created
    assert exc.earliest == earliest
    assert '2030-03-01' in str(exc)
    assert '2020-03-01' in str(exc)
