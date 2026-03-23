"""Tests for P-43: Memory Architecture + _RISKY_SUBSTRINGS removal."""
from __future__ import annotations


def test_risky_substrings_removed():
    """_RISKY_SUBSTRINGS should no longer exist."""
    import app.telegram.communicator.intent_classifier as ic
    assert not hasattr(ic, '_RISKY_SUBSTRINGS')


def test_bezahlt_not_blocked():
    """'bezahlt' in a question should not be blocked."""
    from app.telegram.communicator.intent_classifier import classify_intent
    result = classify_intent('Wieviel MwSt habe ich bezahlt?')
    assert result != 'UNSUPPORTED_OR_RISKY'


def test_ueberwiesen_not_blocked():
    """'überwiesen' in a status question should not be blocked."""
    from app.telegram.communicator.intent_classifier import classify_intent
    result = classify_intent('Wurde die Rechnung schon überwiesen?')
    assert result != 'UNSUPPORTED_OR_RISKY'


def test_empty_text_returns_none():
    from app.telegram.communicator.intent_classifier import classify_intent
    result = classify_intent('')
    assert result is None


def test_long_text_blocked():
    from app.telegram.communicator.intent_classifier import classify_intent
    result = classify_intent('a' * 5001)
    assert result == 'UNSUPPORTED_OR_RISKY'
