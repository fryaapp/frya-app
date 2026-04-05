"""P-19: Admin Token-Usage API."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query

from app.auth.dependencies import require_admin
from app.auth.models import AuthUser
from app.config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix='/api/v1/admin', tags=['admin'])


@router.get('/token-usage')
async def get_token_usage(
    user: AuthUser = Depends(require_admin),
    period: str = Query(default='30d', description='Zeitraum: today, 7d, 30d, all, oder custom'),
    date_from: str | None = Query(default=None, description='YYYY-MM-DD'),
    date_to: str | None = Query(default=None, description='YYYY-MM-DD'),
):
    """Token-Usage pro User und Provider mit Zeitraum-Filter."""
    import asyncpg

    settings = get_settings()

    # Zeitraum berechnen
    now = datetime.now(timezone.utc)
    if date_from and date_to:
        ts_from = datetime.fromisoformat(date_from).replace(tzinfo=timezone.utc)
        ts_to = datetime.fromisoformat(date_to).replace(
            hour=23, minute=59, second=59, tzinfo=timezone.utc,
        )
    elif period == 'today':
        ts_from = now.replace(hour=0, minute=0, second=0, microsecond=0)
        ts_to = now
    elif period == '7d':
        ts_from = now - timedelta(days=7)
        ts_to = now
    elif period == '30d':
        ts_from = now - timedelta(days=30)
        ts_to = now
    else:  # 'all'
        ts_from = datetime(2020, 1, 1, tzinfo=timezone.utc)
        ts_to = now

    conn = await asyncpg.connect(settings.database_url)
    try:
        # Pro User + Provider aggregieren
        rows = await conn.fetch("""
            SELECT
                t.tenant_id,
                u.username,
                u.email,
                t.provider,
                SUM(t.input_tokens)  AS input_tokens,
                SUM(t.output_tokens) AS output_tokens,
                SUM(t.total_tokens)  AS total_tokens,
                COUNT(*)             AS calls
            FROM frya_token_usage t
            LEFT JOIN frya_users u
                ON (t.tenant_id = u.tenant_id OR t.tenant_id = u.username)
            WHERE t.created_at >= $1 AND t.created_at <= $2
            GROUP BY t.tenant_id, u.username, u.email, t.provider
            ORDER BY SUM(t.total_tokens) DESC
        """, ts_from, ts_to)

        # Pro User zusammenfassen
        user_map: dict[str, dict] = {}
        for r in rows:
            tid = r['tenant_id'] or 'default'
            username = r['username'] or tid
            if username not in user_map:
                user_map[username] = {
                    'username': username,
                    'email': r['email'] or '',
                    'tenant_id': tid,
                    'ionos': {
                        'input_tokens': 0, 'output_tokens': 0,
                        'cost_eur': 0.0, 'calls': 0,
                    },
                    'bedrock': {
                        'input_tokens': 0, 'output_tokens': 0,
                        'cost_eur': 0.0, 'calls': 0,
                    },
                    'anthropic': {
                        'input_tokens': 0, 'output_tokens': 0,
                        'cost_eur': 0.0, 'calls': 0,
                    },
                    'total_cost_eur': 0.0,
                    'total_calls': 0,
                }

            provider = r['provider'] or 'ionos'
            bucket = provider if provider in ('ionos', 'bedrock', 'anthropic') else 'ionos'
            in_tok = r['input_tokens'] or 0
            out_tok = r['output_tokens'] or 0
            calls = r['calls'] or 0

            user_map[username][bucket]['input_tokens'] += in_tok
            user_map[username][bucket]['output_tokens'] += out_tok
            user_map[username][bucket]['calls'] += calls
            user_map[username]['total_calls'] += calls

        # Kosten berechnen
        for u in user_map.values():
            for prov in ('ionos', 'bedrock', 'anthropic'):
                bucket = u[prov]
                if bucket['input_tokens'] > 0 or bucket['output_tokens'] > 0:
                    if prov == 'ionos':
                        cost = (
                            bucket['input_tokens'] / 1_000_000 * 0.11
                            + bucket['output_tokens'] / 1_000_000 * 0.33
                        )
                    elif prov in ('bedrock', 'anthropic'):
                        cost = (
                            bucket['input_tokens'] / 1_000_000 * 2.75
                            + bucket['output_tokens'] / 1_000_000 * 13.80
                        )
                    else:
                        cost = 0
                    bucket['cost_eur'] = round(cost, 4)
                    u['total_cost_eur'] += cost
            u['total_cost_eur'] = round(u['total_cost_eur'], 4)

        # Global aggregieren
        global_stats = await conn.fetchrow("""
            SELECT
                SUM(total_tokens)        AS total_tokens,
                SUM(input_tokens)        AS total_input,
                SUM(output_tokens)       AS total_output,
                COUNT(*)                 AS total_calls,
                COUNT(DISTINCT tenant_id) AS active_users
            FROM frya_token_usage
            WHERE created_at >= $1 AND created_at <= $2
        """, ts_from, ts_to)

        total_tokens = global_stats['total_tokens'] or 0
        ionos_cost = sum(u['ionos']['cost_eur'] for u in user_map.values())
        bedrock_cost = sum(
            u['bedrock']['cost_eur'] + u['anthropic']['cost_eur']
            for u in user_map.values()
        )

        return {
            'period': {
                'from': ts_from.isoformat(),
                'to': ts_to.isoformat(),
                'label': period,
            },
            'global': {
                'total_tokens': total_tokens,
                'ionos_cost_eur': round(ionos_cost, 4),
                'bedrock_cost_eur': round(bedrock_cost, 4),
                'total_cost_eur': round(ionos_cost + bedrock_cost, 4),
                'total_calls': global_stats['total_calls'] or 0,
                'active_users': global_stats['active_users'] or 0,
            },
            'per_user': sorted(
                user_map.values(),
                key=lambda x: x['total_cost_eur'],
                reverse=True,
            ),
        }
    finally:
        await conn.close()
