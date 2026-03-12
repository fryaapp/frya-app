from __future__ import annotations

from typing import Any


def parse_gate_result(result: str | None) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for part in (result or '').split(';'):
        if '=' not in part:
            continue
        key, value = part.split('=', 1)
        key = key.strip()
        if key:
            parsed[key] = value.strip()
    return parsed


def approval_next_step(status: str) -> str:
    mapping = {
        'PENDING': 'Freigabe entscheiden und den Folgepfad danach erneut ausfuehren.',
        'APPROVED': 'Freigegebene Aktion darf jetzt kontrolliert weiterlaufen.',
        'REJECTED': 'Vorschlag anpassen oder als Problemfall weiterbearbeiten.',
        'CANCELLED': 'Vorgang nur bei neuem Bedarf erneut anfordern.',
        'EXPIRED': 'Neue Freigabe anfordern oder Frist sauber verlaengern.',
        'REVOKED': 'Auswirkung pruefen und nur mit neuer Freigabe erneut anstossen.',
    }
    return mapping.get(status, 'Status pruefen und operativen Folgepfad manuell festlegen.')


def gate_next_step(mode: str) -> str:
    mapping = {
        'AUTO': 'Deterministischer Pfad darf ohne weiteren Approval-Schritt laufen.',
        'PROPOSE_ONLY': 'Vorschlag sichtbar machen und explizit entscheiden, bevor etwas ausgefuehrt wird.',
        'REQUIRE_USER_APPROVAL': 'Approval einholen und danach den konkreten Seiteneffekt erneut anstossen.',
        'BLOCK_ESCALATE': 'Blocker beheben oder als Problemfall eskalieren, bevor irgendetwas weiterlaeuft.',
    }
    return mapping.get(mode, 'Freigabemodus operativ pruefen.')


def latest_gate_summary(events: list[Any]) -> dict[str, str] | None:
    for event in reversed(events):
        if getattr(event, 'action', '') != 'APPROVAL_GATE_DECISION':
            continue
        parsed = parse_gate_result(getattr(event, 'result', ''))
        mode = parsed.get('mode', 'UNKNOWN')
        return {
            'mode': mode,
            'action_key': parsed.get('action', 'unknown_action'),
            'status': parsed.get('status', 'UNKNOWN'),
            'approval_id': parsed.get('approval_id', '-'),
            'reason': parsed.get('reason', ''),
            'next_step': gate_next_step(mode),
        }
    return None
