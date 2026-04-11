"""Token usage tracking for all LLM calls."""
from __future__ import annotations
import logging
import asyncpg
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_COST_PER_1K = {
    'anthropic': {'input': 0.003, 'output': 0.015},
    'ionos': {'input': 0.0002, 'output': 0.0006},
    'openai': {'input': 0.0005, 'output': 0.0015},
}

def _estimate_cost(provider: str, model: str, input_tokens: int, output_tokens: int) -> float:
    rates = _COST_PER_1K.get(provider, _COST_PER_1K.get('ionos', {'input': 0.0002, 'output': 0.0006}))
    return (input_tokens / 1000 * rates['input']) + (output_tokens / 1000 * rates['output'])

async def log_token_usage(
    database_url: str,
    tenant_id: str,
    agent_id: str,
    model: str,
    provider: str,
    response,
    case_id: str | None = None,
) -> None:
    usage = getattr(response, 'usage', None)
    if not usage:
        return
    input_tokens = getattr(usage, 'prompt_tokens', 0) or 0
    output_tokens = getattr(usage, 'completion_tokens', 0) or 0
    total_tokens = input_tokens + output_tokens
    cost = _estimate_cost(provider, model, input_tokens, output_tokens)

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
