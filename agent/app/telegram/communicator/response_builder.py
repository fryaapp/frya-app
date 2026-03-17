from __future__ import annotations

from app.telegram.communicator.models import CommunicatorContextResolution

_UNCERTAINTY_PREFIX = 'Laut meinem letzten Stand'
_UNCERTAINTY_SUFFIX = '(Tippe /status fuer eine frische Abfrage.)'

# Intents that can carry the uncertainty phrase
_CONTEXT_INTENTS = frozenset({
    'STATUS_OVERVIEW',
    'NEEDS_FROM_USER',
    'DOCUMENT_ARRIVAL_CHECK',
    'LAST_CASE_EXPLANATION',
})


def _wrap(body: str, *, uncertain: bool = False) -> str:
    """Wrap response body with FRYA: prefix and optional uncertainty qualifier."""
    if uncertain:
        return f'FRYA: {_UNCERTAINTY_PREFIX}: {body} {_UNCERTAINTY_SUFFIX}'
    return f'FRYA: {body}'


def build_response(
    intent: str | None,
    ctx: CommunicatorContextResolution | None,
    *,
    guardrail_passed: bool,
    truth_annotation=None,
) -> tuple[str, str]:
    """Build (text, response_type) for a communicator turn.

    truth_annotation: TruthAnnotation | None — if from_conv_memory(), adds uncertainty phrase.
    """
    uncertain = (
        truth_annotation is not None
        and truth_annotation.requires_uncertainty_phrase
        and intent in _CONTEXT_INTENTS
    )

    # ── Safe limit (guardrail or unsupported intent) ──────────────────────────
    if not guardrail_passed or intent == 'UNSUPPORTED_OR_RISKY':
        return (
            'FRYA: Diese Anfrage liegt ausserhalb meines erlaubten Bereichs. '
            'Ich kann dir bei Freigaben, Zahlungen oder systemweiten Aktionen nicht helfen.',
            'COMMUNICATOR_REPLY_SAFE_LIMIT',
        )

    if intent is None:
        return (
            'FRYA: Ich habe deine Anfrage nicht einordnen koennen.',
            'COMMUNICATOR_REPLY_SAFE_LIMIT',
        )

    # ── GREETING ──────────────────────────────────────────────────────────────
    if intent == 'GREETING':
        return (
            'FRYA: Hallo! Ich bin Frya. Wie kann ich dir helfen?',
            'COMMUNICATOR_REPLY_GREETING',
        )

    # ── STATUS_OVERVIEW ───────────────────────────────────────────────────────
    if intent == 'STATUS_OVERVIEW':
        if ctx is None or ctx.resolution_status == 'NOT_FOUND':
            return (
                _wrap('Ich habe keinen offenen Fall fuer dich gefunden.', uncertain=uncertain),
                'COMMUNICATOR_REPLY_STATUS',
            )
        parts: list[str] = []
        if ctx.resolved_case_ref:
            parts.append(f'Fall {ctx.resolved_case_ref}')
        if ctx.clarification_question:
            parts.append(f'Offene Rueckfrage: {ctx.clarification_question}')
        elif ctx.resolved_clarification_ref:
            parts.append('Es liegt eine offene Rueckfrage vor.')
        if ctx.open_item_title:
            parts.append(f'Offener Punkt: {ctx.open_item_title}')
        if ctx.has_multiple_open_items:
            parts.append('Es gibt weitere offene Punkte.')
        body = ' '.join(parts) if parts else 'Dein Fall wird bearbeitet.'
        return _wrap(body, uncertain=uncertain), 'COMMUNICATOR_REPLY_STATUS'

    # ── NEEDS_FROM_USER ───────────────────────────────────────────────────────
    if intent == 'NEEDS_FROM_USER':
        if ctx is None or ctx.resolution_status == 'NOT_FOUND':
            return (
                _wrap('Aktuell fehlt uns nichts von dir.', uncertain=uncertain),
                'COMMUNICATOR_REPLY_NEEDS',
            )
        parts = []
        if ctx.clarification_question:
            parts.append(f'Es gibt eine offene Rueckfrage: {ctx.clarification_question}')
        elif ctx.open_item_state in ('WAITING_USER', 'WAITING_DATA'):
            state_word = 'Angabe' if ctx.open_item_state == 'WAITING_USER' else 'Unterlagen'
            if ctx.open_item_title:
                parts.append(f'Wir warten auf deine {state_word}: {ctx.open_item_title}.')
            else:
                parts.append(f'Wir warten auf deine {state_word}.')
        elif ctx.open_item_title:
            parts.append(f'Offener Punkt: {ctx.open_item_title}.')
        else:
            parts.append('Wir warten auf deine Angabe.')
        if ctx.has_multiple_open_items:
            parts.append('Es gibt weitere offene Punkte.')
        body = ' '.join(parts) if parts else 'Wir warten auf deine Angabe.'
        return _wrap(body, uncertain=uncertain), 'COMMUNICATOR_REPLY_NEEDS'

    # ── DOCUMENT_ARRIVAL_CHECK ────────────────────────────────────────────────
    if intent == 'DOCUMENT_ARRIVAL_CHECK':
        if ctx is None:
            return (
                _wrap('Wir haben noch keinen Dokumenteneingang fuer deinen Fall gefunden.', uncertain=uncertain),
                'COMMUNICATOR_REPLY_EXPLANATION',
            )
        if ctx.resolved_document_ref:
            body = f'Ja, dein Dokument {ctx.resolved_document_ref} ist angekommen.'
            return _wrap(body, uncertain=uncertain), 'COMMUNICATOR_REPLY_EXPLANATION'
        # Case found but no doc
        return (
            _wrap('Wir haben noch keinen Dokumenteneingang fuer deinen Fall.', uncertain=uncertain),
            'COMMUNICATOR_REPLY_EXPLANATION',
        )

    # ── LAST_CASE_EXPLANATION ─────────────────────────────────────────────────
    if intent == 'LAST_CASE_EXPLANATION':
        if ctx is None or ctx.resolution_status == 'NOT_FOUND':
            return (
                _wrap('Wir haben keinen Fall fuer dich gefunden.', uncertain=uncertain),
                'COMMUNICATOR_REPLY_EXPLANATION',
            )
        parts = []
        if ctx.resolved_case_ref:
            parts.append(f'Dein Fall: {ctx.resolved_case_ref}.')
        if ctx.clarification_question:
            parts.append(f'Offene Rueckfrage: {ctx.clarification_question}')
        elif ctx.open_item_title:
            parts.append(f'Offene Punkte: {ctx.open_item_title}.')
        body = ' '.join(parts) if parts else 'Dein Fall wird bearbeitet.'
        return _wrap(body, uncertain=uncertain), 'COMMUNICATOR_REPLY_EXPLANATION'

    # ── GENERAL_SAFE_HELP ─────────────────────────────────────────────────────
    if intent == 'GENERAL_SAFE_HELP':
        return (
            'FRYA: Ich bin FRYA, dein digitaler Assistent fuer Dokument- und Buchungsprozesse. '
            'Du kannst mich nach dem Status deines Falls, offenen Punkten oder eingegangenen '
            'Dokumenten fragen.',
            'COMMUNICATOR_REPLY_SAFE_HELP',
        )

    # Fallback
    return (
        'FRYA: Ich habe deine Anfrage nicht einordnen koennen.',
        'COMMUNICATOR_REPLY_SAFE_LIMIT',
    )
