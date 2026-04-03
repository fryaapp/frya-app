"""Token usage tracking for all LLM calls.

P-19: Globaler LiteLLM-Callback + pro-User/pro-Provider Tracking.
Trackt JEDEN LLM-Call automatisch ueber litellm.success_callback.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Any

import asyncpg

logger = logging.getLogger(__name__)

# ── Preistabelle (EUR pro 1M Tokens) ────────────────────────────────────────

PRICING_EUR_PER_MTOK: dict[str, dict[str, float]] = {
    # IONOS
    'mistral-small-24b': {'input': 0.11, 'output': 0.33},
    'mistral-small-latest': {'input': 0.11, 'output': 0.33},
    'gpt-oss-120b': {'input': 0.65, 'output': 0.86},
    'llama-3.1-405b': {'input': 1.79, 'output': 1.79},
    'llama-3.1-405b-instruct': {'input': 1.79, 'output': 1.79},
    # Bedrock
    'claude-sonnet-4-6': {'input': 2.75, 'output': 13.80},
    'eu.anthropic.claude-sonnet-4-6': {'input': 2.75, 'output': 13.80},
    'anthropic.claude-sonnet-4-6': {'input': 2.75, 'output': 13.80},
    # Anthropic Direct
    'claude-sonnet-4-20250514': {'input': 3.00, 'output': 15.00},
    # LightOn OCR
    'lighton-ocr-2-1b': {'input': 0.05, 'output': 0.15},
    # Fallback
    '_default': {'input': 0.50, 'output': 1.50},
}


def _detect_provider(model: str) -> str:
    """Erkennt den Provider aus dem Modellnamen."""
    m = model.lower()
    if 'bedrock/' in m or 'eu.anthropic' in m:
        return 'bedrock'
    if 'anthropic/' in m or 'claude' in m:
        return 'anthropic'
    if 'openai/' in m and ('ionos' in m or 'mistral' in m or 'llama' in m or 'gpt-oss' in m or 'lighton' in m):
        return 'ionos'
    if 'openai/' in m:
        return 'ionos'  # Default fuer openai/ prefix = IONOS
    return 'unknown'


def _get_pricing(model: str) -> dict[str, float]:
    """Findet die Preise fuer ein Modell."""
    m = model.lower()
    for key, prices in PRICING_EUR_PER_MTOK.items():
        if key in m:
            return prices
    return PRICING_EUR_PER_MTOK['_default']


def calculate_cost(provider: str, model: str, input_tokens: int, output_tokens: int) -> float:
    """Berechnet Kosten in EUR."""
    prices = _get_pricing(model)
    return (input_tokens / 1_000_000 * prices['input']) + (output_tokens / 1_000_000 * prices['output'])


# ── Globaler Tenant-Kontext (Thread-Local) ───────────────────────────────────
# Wird vor jedem LLM-Call gesetzt, damit der Callback weiss welcher User.

_context = threading.local()


def set_tracking_context(tenant_id: str, agent_id: str = '', case_id: str = '') -> None:
    """Setzt den Tenant-Kontext fuer das naechste LLM-Call Tracking."""
    _context.tenant_id = tenant_id
    _context.agent_id = agent_id
    _context.case_id = case_id


def get_tracking_context() -> tuple[str, str, str]:
    """Liest den aktuellen Tracking-Kontext."""
    return (
        getattr(_context, 'tenant_id', 'default'),
        getattr(_context, 'agent_id', ''),
        getattr(_context, 'case_id', ''),
    )


# ── Direkte Log-Funktion (Kompatibilitaet) ──────────────────────────────────

async def log_token_usage(
    database_url: str,
    tenant_id: str,
    agent_id: str,
    model: str,
    provider: str,
    response: Any,
    case_id: str | None = None,
) -> None:
    """Speichert Token-Usage direkt (Legacy-Kompatibilitaet)."""
    usage = getattr(response, 'usage', None)
    if not usage:
        return
    input_tokens = getattr(usage, 'prompt_tokens', 0) or 0
    output_tokens = getattr(usage, 'completion_tokens', 0) or 0
    total_tokens = input_tokens + output_tokens
    cost = calculate_cost(provider, model, input_tokens, output_tokens)

    if database_url.startswith('memory://'):
        return
    try:
        conn = await asyncpg.connect(database_url)
        try:
            await conn.execute(
                """INSERT INTO frya_token_usage
                   (tenant_id, agent_id, model, provider, input_tokens, output_tokens, total_tokens, estimated_cost_eur, case_id)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)""",
                tenant_id, agent_id, model, provider, input_tokens, output_tokens, total_tokens, cost, case_id,
            )
        finally:
            await conn.close()
    except Exception as exc:
        logger.debug('token_tracking: log failed: %s', exc)


# ── LiteLLM Callback (automatisch fuer ALLE Calls) ──────────────────────────

async def _litellm_success_callback(kwargs: dict, completion_response: Any, start_time: Any, end_time: Any) -> None:
    """Wird nach jedem erfolgreichen LLM-Call automatisch aufgerufen."""
    try:
        from app.dependencies import get_settings
        settings = get_settings()
        if settings.database_url.startswith('memory://'):
            return

        model = kwargs.get('model', 'unknown')
        usage = getattr(completion_response, 'usage', None)
        if not usage:
            return

        input_tokens = getattr(usage, 'prompt_tokens', 0) or 0
        output_tokens = getattr(usage, 'completion_tokens', 0) or 0
        total_tokens = input_tokens + output_tokens

        if total_tokens == 0:
            return

        provider = _detect_provider(model)
        cost = calculate_cost(provider, model, input_tokens, output_tokens)
        tenant_id, agent_id, case_id = get_tracking_context()

        conn = await asyncpg.connect(settings.database_url)
        try:
            await conn.execute(
                """INSERT INTO frya_token_usage
                   (tenant_id, agent_id, model, provider, input_tokens, output_tokens, total_tokens, estimated_cost_eur, case_id)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)""",
                tenant_id, agent_id, model, provider, input_tokens, output_tokens, total_tokens, cost, case_id or None,
            )
        finally:
            await conn.close()
    except Exception as exc:
        logger.debug('litellm callback: %s', exc)


def install_litellm_callback() -> None:
    """Registriert den Token-Tracking Callback bei LiteLLM.

    Aufruf einmal beim App-Start (lifespan).
    """
    try:
        import litellm
        litellm.success_callback = [_litellm_success_callback]
        logger.info('Token-Tracking: LiteLLM success_callback installiert')
    except ImportError:
        logger.warning('Token-Tracking: litellm nicht verfuegbar')
    except Exception as exc:
        logger.warning('Token-Tracking: Callback-Installation fehlgeschlagen: %s', exc)
