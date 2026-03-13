from __future__ import annotations

import uuid

from app.audit.service import AuditService
from app.banking.models import BankProbeResult, BankTransactionProbeResult
from app.connectors.accounting_akaunting import AkauntingConnector

_PROBE_VERSION = 'bank-transaction-probe-v1'


class BankTransactionService:
    """Conservative read-only banking service.

    Boundary contract:
    - Reads bank transactions and accounts from Akaunting via GET-only calls.
    - Never initiates payments, transfers, or any write operation.
    - Every probe is logged to the audit service with action=BANK_TRANSACTION_PROBE_EXECUTED.
    - bank_write_executed is always False (asserted by caller).
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

        Returns MATCH_FOUND / NO_MATCH_FOUND / AMBIGUOUS_MATCH / PROBE_ERROR.
        """
        probe_fields = {
            'reference': reference,
            'amount': amount,
            'contact_name': contact_name,
            'date_from': date_from,
            'date_to': date_to,
        }

        matches: list[dict] = []
        result_status = BankProbeResult.NO_MATCH_FOUND
        note = 'Keine Treffer gefunden.'

        try:
            transactions = await self.akaunting_connector.search_transactions(
                reference=reference,
                amount=amount,
                contact_name=contact_name,
                date_from=date_from,
                date_to=date_to,
            )
            matches = transactions[:5]

            if len(matches) == 0:
                result_status = BankProbeResult.NO_MATCH_FOUND
                note = (
                    f'Keine Banktransaktionen zu Referenz={reference}, '
                    f'Betrag={amount}, Kontakt={contact_name} gefunden.'
                )
            elif len(matches) == 1:
                result_status = BankProbeResult.MATCH_FOUND
                m = matches[0]
                note = (
                    f'Eindeutiger Treffer: id={m.get("id")}, '
                    f'Betrag={m.get("amount")}, '
                    f'Datum={m.get("paid_at") or m.get("date") or "-"}, '
                    f'Kontakt={m.get("contact", {}).get("name") or m.get("contact_name") or "-"}.'
                )
            else:
                result_status = BankProbeResult.AMBIGUOUS_MATCH
                note = f'{len(matches)} Treffer gefunden – manuelle Pruefung erforderlich.'

        except Exception as exc:
            result_status = BankProbeResult.PROBE_ERROR
            note = f'Bank-Probe-Fehler: {exc}'

        probe_result = BankTransactionProbeResult(
            result=result_status,
            probe_fields=probe_fields,
            matches=matches,
            note=note,
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

    async def get_accounts(self) -> list[dict]:
        """Read-only: return available bank accounts from Akaunting."""
        return await self.akaunting_connector.search_accounts()
