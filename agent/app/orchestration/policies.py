from __future__ import annotations


def action_requires_approval(action_name: str) -> bool:
    irreversible = {'post_booking', 'finalize_invoice', 'payment_execute'}
    return action_name.lower() in irreversible


def may_execute(action_name: str, approved: bool, deterministic_rule: bool = False) -> bool:
    if action_requires_approval(action_name):
        return approved or deterministic_rule
    return True
