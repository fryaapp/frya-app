"""Prompt-injection detection for all external inputs entering LLM pipelines.

Deterministic regex-based approach — no LLM involved.

Risk thresholds:
  >= 0.7  → BLOCKED   (do not send to LLM, raise audit event)
  0.3-0.69 → SUSPECTED (proceed with cleaned text, cap confidence, audit)
  < 0.3   → CLEAN     (normal processing)

Two entry points:
  sanitize_ocr_text()     — strict mode for document OCR (Tika output)
  sanitize_user_message() — tolerant mode for Telegram user input
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Pattern registry
# Each entry: (compiled_regex, risk_contribution, pattern_name)
# ---------------------------------------------------------------------------

# Full injection phrases — high-risk regardless of context
_FULL_INJECTION_PATTERNS: list[tuple[re.Pattern, float, str]] = [
    # English
    (re.compile(r'ignore\s+(all\s+)?(previous|prior|above)\s+instructions?', re.I), 0.8, 'ignore_instructions_en'),
    (re.compile(r'forget\s+(your|all|previous|prior)\s+instructions?', re.I), 0.8, 'forget_instructions_en'),
    (re.compile(r'\bnew\s+instructions?\s*:', re.I), 0.7, 'new_instructions_en'),
    (re.compile(r'\byou\s+are\s+now\s+(a\s+)?\w', re.I), 0.7, 'you_are_now'),
    # German
    (re.compile(r'ignoriere\s+(alle?\s+)?(vorherigen?|deine|alle)\s+anweisungen?', re.I), 0.8, 'ignore_instructions_de'),
    (re.compile(r'vergiss\s+(alle?\s+)?(vorherigen?|deine|alle)\s+anweisungen?', re.I), 0.8, 'forget_instructions_de'),
    (re.compile(r'\bdu\s+bist\s+jetzt\b', re.I), 0.7, 'du_bist_jetzt'),
    (re.compile(r'\bneue\s+anweisungen?\s*:', re.I), 0.7, 'neue_anweisungen_de'),
    # Role/turn markers (chat-format injection)
    (re.compile(r'(?m)^ASSISTANT\s*:', re.M), 0.6, 'role_assistant'),
    (re.compile(r'(?m)^SYSTEM\s*:', re.M), 0.6, 'role_system'),
    (re.compile(r'(?m)^USER\s*:', re.M), 0.5, 'role_user'),
    # LLM-specific control tokens
    (re.compile(r'\[INST\]', re.I), 0.7, 'llm_token_inst'),
    (re.compile(r'<<SYS>>', re.I), 0.7, 'llm_token_sys'),
    (re.compile(r'<\|im_start\|>', re.I), 0.7, 'llm_token_chatml'),
    # System prompt references
    (re.compile(r'system[\s_-]+prompt', re.I), 0.6, 'system_prompt_ref'),
    (re.compile(r'\bprompt\s+injection\b', re.I), 0.5, 'prompt_injection_ref'),
]

# Context-dependent patterns — lower weight, especially for user messages
_CONTEXT_PATTERNS: list[tuple[re.Pattern, float, str]] = [
    (re.compile(r'\bignoriere\b', re.I), 0.2, 'ignoriere_standalone'),
    (re.compile(r'\bvergiss\b', re.I), 0.15, 'vergiss_standalone'),
]

# Unicode tricks — invisible/zero-width characters used to hide instructions
_UNICODE_TRICKS: list[tuple[str, float, str]] = [
    ('\u200b', 0.4, 'zero_width_space'),
    ('\u200c', 0.4, 'zero_width_nonjoiner'),
    ('\u200d', 0.4, 'zero_width_joiner'),
    ('\u2060', 0.4, 'word_joiner'),
    ('\ufeff', 0.3, 'bom_zwsp'),
    ('\u00ad', 0.15, 'soft_hyphen'),
]

_RISK_BLOCK = 0.7
_RISK_SUSPECT = 0.3


@dataclass
class SanitizedText:
    """Result of input sanitization."""

    original_text: str
    cleaned_text: str       # Zero-width chars removed
    injection_detected: bool
    detected_patterns: list[str] = field(default_factory=list)
    risk_score: float = 0.0
    is_blocked: bool = False    # risk_score >= 0.7
    is_suspected: bool = False  # 0.3 <= risk_score < 0.7


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _scan(text: str, *, context_weight_factor: float = 1.0) -> tuple[float, list[str]]:
    """Return (risk_score, detected_pattern_names).

    context_weight_factor < 1.0 reduces sensitivity for context-dependent patterns
    (used for user messages to avoid false-positives on normal German words).
    """
    score = 0.0
    found: list[str] = []

    for pattern, weight, name in _FULL_INJECTION_PATTERNS:
        if pattern.search(text):
            score += weight
            found.append(name)

    for pattern, weight, name in _CONTEXT_PATTERNS:
        if pattern.search(text):
            effective_weight = weight * context_weight_factor
            score += effective_weight
            found.append(name)

    for char, weight, name in _UNICODE_TRICKS:
        if char in text:
            score += weight
            found.append(name)

    return min(1.0, score), found


def _clean(text: str) -> str:
    """Strip invisible/zero-width characters that could hide injected content."""
    result = text
    for char, _, _ in _UNICODE_TRICKS:
        result = result.replace(char, '')
    return result


def _build(text: str, score: float, patterns: list[str]) -> SanitizedText:
    return SanitizedText(
        original_text=text,
        cleaned_text=_clean(text),
        injection_detected=bool(patterns),
        detected_patterns=patterns,
        risk_score=score,
        is_blocked=score >= _RISK_BLOCK,
        is_suspected=_RISK_SUSPECT <= score < _RISK_BLOCK,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def sanitize_ocr_text(text: str) -> SanitizedText:
    """Sanitize OCR-extracted document text before sending to LLM.

    Strict mode — legitimate invoices/letters do not contain prompt instructions.
    Any detected injection phrase is treated with full weight.
    """
    score, patterns = _scan(text, context_weight_factor=1.0)
    return _build(text, score, patterns)


def sanitize_user_message(text: str) -> SanitizedText:
    """Sanitize a Telegram/user message before sending to LLM.

    Tolerant mode — users may naturally use words like 'ignoriere' or 'vergiss'
    in German without malicious intent.  Only full injection phrases and structural
    control tokens (SYSTEM:, [INST], <<SYS>>) trigger high risk.
    """
    # Context-dependent patterns get 50% weight for user messages
    score, patterns = _scan(text, context_weight_factor=0.5)
    return _build(text, score, patterns)
