"""Dunning (Mahnwesen) escalation service."""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone

import asyncpg

logger = logging.getLogger(__name__)

_DUNNING_TEXTS = {
    1: 'Kleine Erinnerung: Die Rechnung von {vendor} ueber {amount} EUR ist seit {days} Tagen faellig.',
    2: 'Zahlungserinnerung: Rechnung {ref} ueber {amount} EUR ist seit {days} Tagen ueberfaellig. Bitte um zeitnahe Begleichung.',
    3: 'Mahnung: Die Rechnung {ref} ueber {amount} EUR ist seit {days} Tagen ueberfaellig. Wir bitten dringend um Zahlung.',
    4: 'Letzte Mahnung: Rechnung {ref} ueber {amount} EUR seit {days} Tagen ueberfaellig. Ohne Zahlung innerhalb von 7 Tagen erfolgt die Weitergabe an ein Inkassobuero.',
}


class DunningService:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    async def check_and_escalate(self, tenant_id: str) -> list[dict]:
        """Check all overdue open items and escalate dunning level if needed."""
        conn = await asyncpg.connect(self.database_url)
        try:
            # Get dunning config for this tenant
            config_rows = await conn.fetch(
                'SELECT level, days_after_due, tone, template_key FROM frya_dunning_config WHERE tenant_id = $1 ORDER BY level',
                tenant_id,
            )
            if not config_rows:
                # Default config
                config = [
                    {'level': 1, 'days_after_due': 7},
                    {'level': 2, 'days_after_due': 21},
                    {'level': 3, 'days_after_due': 35},
                    {'level': 4, 'days_after_due': 49},
                ]
            else:
                config = [dict(r) for r in config_rows]

            # Get open items with due_date in the past
            items = await conn.fetch(
                """SELECT item_id, case_id, title, due_at, dunning_level
                   FROM frya_open_items
                   WHERE status IN ('OPEN', 'PENDING_APPROVAL', 'WAITING_USER')
                   AND due_at IS NOT NULL AND due_at < now()""",
            )

            today = date.today()
            escalated = []

            for item in items:
                due = item['due_at']
                if isinstance(due, datetime):
                    due = due.date()
                days_overdue = (today - due).days
                current_level = item['dunning_level'] or 0

                # Find the highest applicable level
                new_level = current_level
                for cfg in config:
                    if days_overdue >= cfg['days_after_due'] and cfg['level'] > current_level:
                        new_level = cfg['level']

                if new_level > current_level:
                    await conn.execute(
                        'UPDATE frya_open_items SET dunning_level = $2, dunning_last_sent = now() WHERE item_id = $1',
                        item['item_id'], new_level,
                    )
                    escalated.append({
                        'item_id': item['item_id'],
                        'case_id': item['case_id'],
                        'title': item['title'],
                        'days_overdue': days_overdue,
                        'old_level': current_level,
                        'new_level': new_level,
                    })
                    logger.info('Dunning escalated: %s level %d->%d (%d days)', item['item_id'], current_level, new_level, days_overdue)

            return escalated
        finally:
            await conn.close()

    def get_dunning_text(self, level: int, vendor: str = '?', amount: str = '?', ref: str = '?', days: int = 0) -> str:
        template = _DUNNING_TEXTS.get(level, _DUNNING_TEXTS.get(1, ''))
        return template.format(vendor=vendor, amount=amount, ref=ref, days=days)
