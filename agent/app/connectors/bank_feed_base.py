from __future__ import annotations

from app.connectors.contracts import BankFeedConnector


class FutureBankFeedConnector(BankFeedConnector):
    """Provider-neutral boundary for future transaction feeds."""

    async def ingest_transactions(self, payload: dict) -> list[dict]:
        transactions = payload.get('transactions', [])
        return transactions if isinstance(transactions, list) else []

    async def match_transactions(self, transactions: list[dict]) -> list[dict]:
        matches: list[dict] = []
        for tx in transactions:
            matches.append(
                {
                    'transaction_id': tx.get('id'),
                    'match_status': 'UNMATCHED',
                    'reason': 'Kein deterministischer Matching-Workflow hinterlegt.',
                }
            )
        return matches
