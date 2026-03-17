from __future__ import annotations

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

    if normalized in {'/start', 'start', '/hilfe', 'hilfe', 'help', 'was kannst du'}:
        return TelegramIntent(name='help.basic', raw_text=text)

    if normalized in {'/status', 'status', 'wie ist der stand', 'gib mir den status'}:
        return TelegramIntent(name='status.overview', raw_text=text)

    return TelegramIntent(name='unknown', raw_text=text)
