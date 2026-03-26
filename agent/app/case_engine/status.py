"""Case status transition rules.

Allowed transitions:
  DRAFT      → OPEN (requires ≥1 document — enforced in repository), DISCARDED
  OPEN       → OVERDUE, PAID*, CLOSED*, MERGED, DISCARDED
  OVERDUE    → PAID*, CLOSED*
  PAID       → CLOSED*
  DISCARDED  → OPEN
  CLOSED     → (terminal)
  MERGED     → (terminal)

  * Requires operator=True
"""
from __future__ import annotations

# current_status → allowed target statuses
_TRANSITIONS: dict[str, frozenset[str]] = {
    'DRAFT': frozenset({'OPEN', 'DISCARDED'}),
    'OPEN': frozenset({'OVERDUE', 'PAID', 'CLOSED', 'MERGED', 'DISCARDED'}),
    'OVERDUE': frozenset({'PAID', 'CLOSED'}),
    'PAID': frozenset({'CLOSED'}),
    'DISCARDED': frozenset({'OPEN'}),
    'CLOSED': frozenset(),
    'MERGED': frozenset(),
}

# Transitions that require explicit operator confirmation
_OPERATOR_REQUIRED: frozenset[tuple[str, str]] = frozenset({
    ('OPEN', 'PAID'),
    ('OPEN', 'CLOSED'),
    ('OVERDUE', 'PAID'),
    ('OVERDUE', 'CLOSED'),
    ('PAID', 'CLOSED'),
})


class StatusTransitionError(ValueError):
    """Raised when a status transition is not allowed."""


def check_transition(current: str, new_status: str, *, operator: bool = False) -> None:
    """Raise StatusTransitionError if the transition is forbidden.

    Args:
        current: Current case status.
        new_status: Desired new status.
        operator: True if an authenticated operator initiated this transition.
    """
    allowed = _TRANSITIONS.get(current, frozenset())
    if new_status not in allowed:
        raise StatusTransitionError(
            f'Transition {current!r} → {new_status!r} is not allowed. '
            f'Allowed from {current!r}: {sorted(allowed) or "none"}.'
        )
    if (current, new_status) in _OPERATOR_REQUIRED and not operator:
        raise StatusTransitionError(
            f'Transition {current!r} → {new_status!r} requires operator=True.'
        )


def allowed_transitions(current: str) -> frozenset[str]:
    """Return the set of statuses reachable from *current*."""
    return _TRANSITIONS.get(current, frozenset())
