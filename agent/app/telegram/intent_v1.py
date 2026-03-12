from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(slots=True)
class TelegramIntent:
    name: str
    raw_text: str
    case_id: str | None = None
    decision: str | None = None
    target_ref: str | None = None


def _normalize(text: str) -> str:
    return ' '.join((text or '').strip().lower().split())


def detect_intent(text: str) -> TelegramIntent:
    normalized = _normalize(text)

    if not normalized:
        return TelegramIntent(name='unknown', raw_text=text)

    if normalized in {'hilfe', 'help', 'was kannst du'}:
        return TelegramIntent(name='help.basic', raw_text=text)

    if normalized in {'status', 'wie ist der stand', 'gib mir den status'}:
        return TelegramIntent(name='status.overview', raw_text=text)

    if normalized in {'offene punkte', 'zeig open items', 'open items'}:
        return TelegramIntent(name='open_items.list', raw_text=text)

    if normalized in {'problemfaelle', 'problemfälle', 'welche faelle sind kritisch', 'welche fälle sind kritisch'}:
        return TelegramIntent(name='problem_cases.list', raw_text=text)

    case_match = re.search(r'(?:zeige\s+fall|fall)\s+([a-zA-Z0-9._:-]+)', normalized)
    if case_match:
        return TelegramIntent(name='case.show', raw_text=text, case_id=case_match.group(1))

    approval_match = re.match(r'^(freigeben|genehmigen|approve|ablehnen|reject)\s+([a-zA-Z0-9._:-]+)$', normalized)
    if approval_match:
        verb = approval_match.group(1)
        target = approval_match.group(2)
        decision = 'APPROVED' if verb in {'freigeben', 'genehmigen', 'approve'} else 'REJECTED'
        return TelegramIntent(name='approval.respond', raw_text=text, decision=decision, target_ref=target)

    if normalized.startswith('was ist mit fall '):
        token = normalized.replace('was ist mit fall ', '', 1).replace('?', '').strip()
        if token:
            return TelegramIntent(name='case.show', raw_text=text, case_id=token)

    return TelegramIntent(name='unknown', raw_text=text)