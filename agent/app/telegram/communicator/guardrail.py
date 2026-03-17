from __future__ import annotations

from app.telegram.communicator.models import CommunicatorIntentCode


def check_guardrail(intent: CommunicatorIntentCode | None) -> tuple[bool, str | None]:
    """Hard guardrail check for communicator intents.

    Returns (passed, reason):
    - passed=True  → message is safe to respond to
    - passed=False → message triggered a guardrail; respond with safe-limit text

    UNSUPPORTED_OR_RISKY always fails.
    All other recognized intents pass (their responses are pre-bounded and safe).
    None (fall-through) should never reach this function.
    """
    if intent == 'UNSUPPORTED_OR_RISKY':
        return False, 'Anfrage liegt ausserhalb des erlaubten Kommunikatorbereichs (Guardrail aktiv).'
    return True, None
