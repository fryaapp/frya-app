from __future__ import annotations

import uuid

from app.audit.service import AuditService
from app.banking.models import (
    BankProbeResult,
    BankTransactionProbeResult,
    FeedStatus,
    MatchQuality,
    TransactionCandidate,
)
from app.connectors.accounting_akaunting import AkauntingConnector

_PROBE_VERSION = 'bank-transaction-probe-v1.2'

# Score thresholds
_HIGH_CONFIDENCE_MIN = 60
_MEDIUM_CONFIDENCE_MIN = 30


def _score_transaction(
    tx: dict,
    reference: str | None,
    amount: float | None,
    contact_name: str | None,
    date_from: str | None,
    date_to: str | None,
) -> tuple[int, list[str]]:
    """Score a single transaction candidate against search criteria.

    Returns (score 0-100, reason_codes).
    Higher score = better match. Advisory only; never triggers writes.

    Scoring weights:
      Amount:    40 pts (AMOUNT_EXACT: diff < 0.01) or 25 pts (AMOUNT_NEAR: diff < 5%)
      Reference: 30 pts (REFERENCE_MATCH: substring)
      Contact:   20 pts (CONTACT_MATCH: substring)
      Date:      10 pts (DATE_IN_RANGE)
    """
    score = 0
    reasons: list[str] = []

    # Amount match: highest weight (40 pts)
    if amount is not None:
        tx_amount = None
        for key in ('amount', 'total', 'price'):
            raw = tx.get(key)
            if raw is not None:
                try:
                    tx_amount = float(raw)
                    break
                except (TypeError, ValueError):
                    pass
        if tx_amount is not None:
            if abs(tx_amount - amount) < 0.01:
                score += 40
                reasons.append('AMOUNT_EXACT')
            elif abs(amount) > 0 and abs(tx_amount - amount) / abs(amount) < 0.05:
                score += 25
                reasons.append('AMOUNT_NEAR')

    # Reference match (30 pts)
    if reference:
        ref_fields = [
            tx.get('reference') or '',
            tx.get('number') or '',
            tx.get('document_number') or '',
            tx.get('description') or '',
        ]
        haystack = ' '.join(str(f) for f in ref_fields).lower()
        if reference.lower() in haystack:
            score += 30
            reasons.append('REFERENCE_MATCH')

    # Contact match (20 pts)
    if contact_name:
        contact_fields = [
            tx.get('contact_name') or '',
            (tx.get('contact') or {}).get('name') or '',
        ]
        haystack = ' '.join(contact_fields).lower()
        if contact_name.lower() in haystack:
            score += 20
            reasons.append('CONTACT_MATCH')

    # Date range (10 pts)
    if date_from or date_to:
        tx_date = (
            tx.get('paid_at') or tx.get('issued_at') or
            tx.get('date') or tx.get('created_at') or ''
        )
        if tx_date:
            tx_date_str = str(tx_date)[:10]
            in_range = True
            if date_from and tx_date_str < date_from[:10]:
                in_range = False
            if date_to and tx_date_str > date_to[:10]:
                in_range = False
            if in_range:
                score += 10
                reasons.append('DATE_IN_RANGE')

    return score, reasons


def _build_candidate(tx: dict, score: int, reasons: list[str]) -> TransactionCandidate:
    """Build a structured TransactionCandidate from a raw transaction dict."""
    if score >= _HIGH_CONFIDENCE_MIN:
        quality = MatchQuality.HIGH
    elif score >= _MEDIUM_CONFIDENCE_MIN:
        quality = MatchQuality.MEDIUM
    else:
        quality = MatchQuality.LOW

    amount_raw = tx.get('amount') or tx.get('total') or tx.get('price')
    try:
        amount_val = float(amount_raw) if amount_raw is not None else None
    except (TypeError, ValueError):
        amount_val = None

    contact = tx.get('contact') or {}
    contact_name_val = tx.get('contact_name') or (contact.get('name') if isinstance(contact, dict) else None)
    account = tx.get('account') or {}
    account_name_val = tx.get('account_name') or (account.get('name') if isinstance(account, dict) else None)
    currency_val = tx.get('currency_code') or (account.get('currency_code') if isinstance(account, dict) else None)
    tx_date = tx.get('paid_at') or tx.get('issued_at') or tx.get('date') or tx.get('created_at')

    return TransactionCandidate(
        transaction_id=tx.get('id'),
        amount=amount_val,
        currency=currency_val,
        date=str(tx_date)[:10] if tx_date else None,
        reference=tx.get('reference') or tx.get('number') or tx.get('document_number'),
        contact_name=contact_name_val,
        account_name=account_name_val,
        description=tx.get('description') or tx.get('notes'),
        confidence_score=score,
        match_quality=quality,
        reason_codes=reasons,
    )


def _determine_result(
    transactions: list[dict],
    has_filters: bool,
    reference: str | None,
    amount: float | None,
    contact_name: str | None,
    date_from: str | None,
    date_to: str | None,
) -> tuple[BankProbeResult, list[TransactionCandidate], str]:
    """Core matching logic. Returns (result_enum, candidates, note).

    Result logic:
    - NO_TRANSACTIONS_AVAILABLE: feed returned 0 transactions (feed may be empty or staging)
    - MATCH_FOUND:     exactly one candidate with HIGH confidence (score >= 60)
    - AMBIGUOUS_MATCH: two+ candidates with HIGH confidence
    - CANDIDATE_FOUND: one+ candidates with MEDIUM confidence, no HIGH
    - NO_MATCH_FOUND:  transactions exist but nothing scored > 0
    """
    if not transactions:
        return (
            BankProbeResult.NO_TRANSACTIONS_AVAILABLE,
            [],
            'Kein Treffer: Feed erreichbar, aber keine Transaktionen im System vorhanden.',
        )

    if not has_filters:
        # No filters: informational — show available transactions as LOW candidates
        candidates = [
            _build_candidate(tx, score=0, reasons=['AVAILABLE_TRANSACTION'])
            for tx in transactions[:5]
        ]
        return (
            BankProbeResult.NO_TRANSACTIONS_AVAILABLE
            if not transactions else BankProbeResult.NO_MATCH_FOUND,
            candidates,
            (
                f'{len(transactions)} Transaktion(en) im System verfuegbar. '
                'Bitte Suchfelder (Referenz, Betrag, Kontakt) fuer gezielten Abgleich nutzen.'
            ),
        )

    # Score each transaction
    scored: list[tuple[int, list[str], dict]] = []
    for tx in transactions:
        score, reasons = _score_transaction(tx, reference, amount, contact_name, date_from, date_to)
        if score > 0:
            scored.append((score, reasons, tx))

    scored.sort(key=lambda x: x[0], reverse=True)
    candidates = [_build_candidate(tx, score, reasons) for score, reasons, tx in scored[:5]]

    high_conf = [c for c in candidates if c.match_quality == MatchQuality.HIGH]
    medium_conf = [c for c in candidates if c.match_quality == MatchQuality.MEDIUM]

    if len(high_conf) == 1:
        c = high_conf[0]
        return (
            BankProbeResult.MATCH_FOUND,
            candidates,
            (
                f'Eindeutiger Treffer: ID={c.transaction_id}, '
                f'Betrag={c.amount} {c.currency or ""}, '
                f'Datum={c.date or "-"}, '
                f'Kontakt={c.contact_name or "-"}, '
                f'Score={c.confidence_score}/100 ({", ".join(c.reason_codes)}).'
            ),
        )
    elif len(high_conf) >= 2:
        return (
            BankProbeResult.AMBIGUOUS_MATCH,
            candidates,
            (
                f'{len(high_conf)} Kandidaten mit hoher Uebereinstimmung – '
                f'manuelle Pruefung erforderlich. Scores: '
                f'{", ".join(str(c.confidence_score) for c in high_conf[:3])}.'
            ),
        )
    elif medium_conf:
        c = medium_conf[0]
        return (
            BankProbeResult.CANDIDATE_FOUND,
            candidates,
            (
                f'{len(medium_conf)} moegliche Kandidaten (mittlere Uebereinstimmung). '
                f'Bester: ID={c.transaction_id}, Score={c.confidence_score}/100 '
                f'({", ".join(c.reason_codes)}). Manuelle Sichtung empfohlen.'
            ),
        )
    elif candidates:
        return (
            BankProbeResult.CANDIDATE_FOUND,
            candidates,
            (
                f'{len(candidates)} schwache Kandidaten (Score < {_MEDIUM_CONFIDENCE_MIN}). '
                'Kein sicherer Treffer. Suchfelder praezisieren oder manuell pruefen.'
            ),
        )
    else:
        return (
            BankProbeResult.NO_MATCH_FOUND,
            [],
            (
                f'Keine passenden Banktransaktionen zu Referenz={reference}, '
                f'Betrag={amount}, Kontakt={contact_name}.'
            ),
        )


class BankTransactionService:
    """Conservative read-only banking service.

    Boundary contract:
    - Reads bank transactions and accounts from Akaunting via GET-only calls.
    - Never initiates payments, transfers, or any write operation.
    - Every probe is logged to the audit service.
    - bank_write_executed is always False (asserted by caller).

    V1.1: Candidate scoring (confidence_score, match_quality, reason_codes).
    V1.2: FeedStatus on every result; NO_TRANSACTIONS_AVAILABLE distinct result;
          probe_test_transactions() for operator-supplied test data.
    """

    def __init__(
        self,
        akaunting_connector: AkauntingConnector,
        audit_service: AuditService,
    ) -> None:
        self.akaunting_connector = akaunting_connector
        self.audit_service = audit_service

    async def probe_transactions(
        self,
        case_id: str,
        reference: str | None = None,
        amount: float | None = None,
        contact_name: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> BankTransactionProbeResult:
        """Read-only probe: search Akaunting banking transactions. Never writes.

        V1.2: also fetches FeedStatus so operators can see feed health inline.
        """
        has_filters = any(v is not None for v in [reference, amount, contact_name, date_from, date_to])
        probe_fields = {
            'reference': reference,
            'amount': amount,
            'contact_name': contact_name,
            'date_from': date_from,
            'date_to': date_to,
        }

        result_status = BankProbeResult.NO_MATCH_FOUND
        matches: list[dict] = []
        candidates: list[TransactionCandidate] = []
        note = 'Keine Treffer gefunden.'
        feed_status: FeedStatus | None = None

        try:
            # V1.2: get feed health first
            raw_status = await self.akaunting_connector.get_feed_status()
            feed_status = FeedStatus(**raw_status)

            transactions = await self.akaunting_connector.search_transactions(
                reference=reference,
                amount=amount,
                contact_name=contact_name,
                date_from=date_from,
                date_to=date_to,
            )
            matches = transactions[:10]

            result_status, candidates, note = _determine_result(
                transactions=matches,
                has_filters=has_filters,
                reference=reference,
                amount=amount,
                contact_name=contact_name,
                date_from=date_from,
                date_to=date_to,
            )

        except Exception as exc:
            result_status = BankProbeResult.PROBE_ERROR
            note = f'Bank-Probe-Fehler: {exc}'

        probe_result = BankTransactionProbeResult(
            result=result_status,
            probe_fields=probe_fields,
            matches=matches,
            candidates=candidates,
            note=note,
            feed_status=feed_status,
            is_test_data=False,
        )

        await self.audit_service.log_event({
            'event_id': str(uuid.uuid4()),
            'case_id': case_id,
            'source': _PROBE_VERSION,
            'action': 'BANK_TRANSACTION_PROBE_EXECUTED',
            'result': result_status.value,
            'agent_name': _PROBE_VERSION,
            'llm_output': probe_result.model_dump(mode='json'),
        })

        return probe_result

    async def probe_test_transactions(
        self,
        case_id: str,
        test_transactions: list[dict],
        reference: str | None = None,
        amount: float | None = None,
        contact_name: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> BankTransactionProbeResult:
        """Read-only probe on operator-supplied test transactions.

        V1.2: allows demonstrating the scoring pipeline without live Akaunting data.
        The result is clearly flagged with is_test_data=True and logged as
        BANK_TEST_PROBE_EXECUTED (not BANK_TRANSACTION_PROBE_EXECUTED).

        Safety: same invariants as probe_transactions — no writes, no payments.
        """
        has_filters = any(v is not None for v in [reference, amount, contact_name, date_from, date_to])
        probe_fields = {
            'reference': reference,
            'amount': amount,
            'contact_name': contact_name,
            'date_from': date_from,
            'date_to': date_to,
            '_test_transaction_count': len(test_transactions),
        }

        # Feed status: still call to show real feed health alongside test results
        feed_status: FeedStatus | None = None
        try:
            raw_status = await self.akaunting_connector.get_feed_status()
            feed_status = FeedStatus(**raw_status)
        except Exception:
            pass

        result_status, candidates, note = _determine_result(
            transactions=test_transactions,
            has_filters=has_filters,
            reference=reference,
            amount=amount,
            contact_name=contact_name,
            date_from=date_from,
            date_to=date_to,
        )

        note = f'[TESTDATEN] {note}'

        probe_result = BankTransactionProbeResult(
            result=result_status,
            probe_fields=probe_fields,
            matches=test_transactions[:10],
            candidates=candidates,
            note=note,
            feed_status=feed_status,
            is_test_data=True,
        )

        await self.audit_service.log_event({
            'event_id': str(uuid.uuid4()),
            'case_id': case_id,
            'source': _PROBE_VERSION,
            'action': 'BANK_TEST_PROBE_EXECUTED',
            'result': result_status.value,
            'agent_name': _PROBE_VERSION,
            'llm_output': probe_result.model_dump(mode='json'),
        })

        return probe_result

    async def get_accounts(self) -> list[dict]:
        """Read-only: return available bank accounts from Akaunting."""
        return await self.akaunting_connector.search_accounts()

    async def get_feed_status(self) -> FeedStatus:
        """Read-only: return live feed health metadata."""
        raw = await self.akaunting_connector.get_feed_status()
        return FeedStatus(**raw)
