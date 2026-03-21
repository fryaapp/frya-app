"""Booking approval flow — channel-agnostic.

Handles the user decision after the Accounting Analyst creates a BOOKING_PROPOSAL:
  APPROVE  → create Akaunting bill draft, mark open item COMPLETED
  REJECT   → mark open item CANCELLED, ask Communicator for follow-up
  CORRECT  → re-validate with corrected fields, then proceed as APPROVE
  DEFER    → keep PENDING_APPROVAL, no follow-up now

The booking proposal message is formatted here and stored in the approval context
so any channel (Telegram, Browser, App) can display it.
"""
from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any

import yaml

from app.accounting_analysis.models import AccountingAnalysisResult
from app.approvals.service import ApprovalService
from app.audit.service import AuditService
from app.connectors.accounting_akaunting import AkauntingConnector
from app.document_analysis.models import Annotation
from app.open_items.service import OpenItemsService

logger = logging.getLogger(__name__)

_SKR03_MAP_PATH = Path(__file__).parent.parent.parent / 'data' / 'config' / 'skr03_akaunting_map.yaml'

_DECISION_ALIASES: dict[str, str] = {
    'APPROVE': 'APPROVE',
    'APPROVED': 'APPROVE',
    'JA': 'APPROVE',
    'BUCHEN': 'APPROVE',
    'PASST': 'APPROVE',
    'OK': 'APPROVE',
    'REJECT': 'REJECT',
    'REJECTED': 'REJECT',
    'NEIN': 'REJECT',
    'FALSCH': 'REJECT',
    'STIMMT NICHT': 'REJECT',
    'ABLEHNEN': 'REJECT',
    'CORRECT': 'CORRECT',
    'KORRIGIEREN': 'CORRECT',
    'DEFER': 'DEFER',
    'SPÄTER': 'DEFER',
    'NICHT JETZT': 'DEFER',
    'LATER': 'DEFER',
}


def _load_skr03_map() -> dict:
    try:
        if _SKR03_MAP_PATH.exists():
            with open(_SKR03_MAP_PATH, encoding='utf-8') as f:
                return yaml.safe_load(f) or {}
    except Exception as exc:
        logger.warning('Could not load SKR03 map: %s', exc)
    return {}


def skr03_to_akaunting_category(skr03_konto: str | None) -> str:
    """Map a SKR03 account number to an Akaunting category name."""
    if not skr03_konto:
        return 'Sonstiges'
    data = _load_skr03_map()
    # Try exact key match (YAML keys may be int or str)
    for key in (skr03_konto, int(skr03_konto) if skr03_konto.isdigit() else None):
        if key is not None and key in data:
            entry = data[key]
            if isinstance(entry, dict):
                return str(entry.get('akaunting_category') or 'Sonstiges')
    default = data.get('default', {})
    return str(default.get('akaunting_category', 'Sonstiges')) if isinstance(default, dict) else 'Sonstiges'


def format_booking_proposal_message(
    accounting_analysis: AccountingAnalysisResult,
    annotations: list[Annotation] | None = None,
    source_channel: str = 'UNKNOWN',
) -> str:
    """Format a human-readable booking proposal message.

    High confidence + no risks → short and direct.
    Medium confidence or risk flags → add warnings.
    Annotation notes → mention relevant findings.
    """
    amt = accounting_analysis.amount_summary
    total = amt.total_amount.value
    currency = amt.currency.value or 'EUR'
    vendor = accounting_analysis.supplier_or_counterparty_hint.value or '?'
    candidate = accounting_analysis.booking_candidate
    confidence = accounting_analysis.booking_confidence
    risks = accounting_analysis.accounting_risks
    decision = accounting_analysis.global_decision

    # Format amount
    if total is not None:
        amount_str = f'{total:,.2f} €'.replace(',', 'X').replace('.', ',').replace('X', '.')
    else:
        amount_str = '? €'

    # Determine category label
    category_label = ''
    if candidate and candidate.counterparty_hint:
        category_label = candidate.counterparty_hint
    elif candidate and candidate.review_focus:
        category_label = candidate.review_focus[0]

    # Core message
    lines: list[str] = []
    if confidence >= 0.80 and not risks:
        lines.append(f'FRYA: {vendor} — {amount_str} — Betriebsausgabe{f" {category_label}" if category_label else ""}.')
        lines.append('Soll ich das so buchen?')
    elif confidence >= 0.60:
        lines.append(f'FRYA: {vendor} — {amount_str}{f" — {category_label}" if category_label else ""}.')
        lines.append('Ich bin mir nicht ganz sicher — check mal ob das stimmt.')
    else:
        lines.append(f'FRYA: {vendor} — {amount_str}.')
        lines.append('Die Daten sind unvollständig. Soll ich trotzdem einen Buchungsentwurf anlegen?')

    # Risk warnings
    for risk in risks:
        if risk.code == 'DUPLICATE_DETECTED':
            lines.append('Achtung: Sieht nach einem Duplikat aus.')
        elif risk.code == 'TAX_PLAUSIBILITY':
            lines.append('Der Steuersatz kommt mir komisch vor.')
        elif risk.severity == 'HIGH':
            lines.append(f'Achtung: {risk.message}')

    # Annotation notes
    for ann in (annotations or []):
        if ann.action_suggested == 'CHECK_PAYMENT_EXISTS':
            lines.append(f"Übrigens, da steht '{ann.raw_text}' drauf — soll ich prüfen ob der Zahlungseingang existiert?")
        elif ann.action_suggested == 'SUGGEST_ALLOCATION':
            lines.append(f"Hinweis: '{ann.raw_text}' — Soll ich das aufteilen (privat/betrieblich)?")
        elif ann.action_suggested == 'FLAG_FOR_TAX_ADVISOR':
            lines.append('Hab den Beleg für deinen Steuerberater markiert.')

    return '\n'.join(lines)


class BookingApprovalService:
    """Channel-agnostic service to handle booking proposal approval flow."""

    def __init__(
        self,
        approval_service: ApprovalService,
        open_items_service: OpenItemsService,
        audit_service: AuditService,
        akaunting_connector: AkauntingConnector,
    ) -> None:
        self.approval_service = approval_service
        self.open_items_service = open_items_service
        self.audit_service = audit_service
        self.akaunting_connector = akaunting_connector

    async def process_response(
        self,
        case_id: str,
        approval_id: str,
        decision_raw: str,
        decided_by: str = 'user',
        correction_payload: dict | None = None,
        source: str = 'api',
    ) -> dict[str, Any]:
        """Process user response to a booking proposal.

        Returns: {
            'decision': str,
            'approval_status': str,
            'open_item_status': str,
            'akaunting_bill_id': int|None,
            'message': str,
        }
        """
        decision = _DECISION_ALIASES.get(decision_raw.upper().strip(), decision_raw.upper().strip())

        # Fetch approval record to get booking proposal context
        approval = await self.approval_service.repository.get(approval_id)
        if approval is None:
            return {'decision': decision, 'error': f'Approval {approval_id} not found', 'message': 'Freigabe nicht gefunden.'}

        ctx = approval.approval_context or {}
        accounting_payload = ctx.get('accounting_analysis') or {}
        open_item_id = approval.open_item_id

        if decision == 'APPROVE':
            return await self._handle_approve(
                case_id=case_id,
                approval_id=approval_id,
                accounting_payload=accounting_payload,
                correction_payload=correction_payload,
                open_item_id=open_item_id,
                decided_by=decided_by,
                source=source,
            )
        elif decision == 'REJECT':
            return await self._handle_reject(
                case_id=case_id,
                approval_id=approval_id,
                open_item_id=open_item_id,
                decided_by=decided_by,
                source=source,
            )
        elif decision == 'CORRECT':
            return await self._handle_correct(
                case_id=case_id,
                approval_id=approval_id,
                accounting_payload=accounting_payload,
                correction_payload=correction_payload or {},
                open_item_id=open_item_id,
                decided_by=decided_by,
                source=source,
            )
        elif decision == 'DEFER':
            return await self._handle_defer(
                case_id=case_id,
                approval_id=approval_id,
                open_item_id=open_item_id,
                decided_by=decided_by,
            )
        else:
            return {'decision': decision, 'error': f'Unknown decision: {decision}', 'message': 'Unbekannte Antwort.'}

    async def _handle_approve(
        self,
        *,
        case_id: str,
        approval_id: str,
        accounting_payload: dict,
        correction_payload: dict | None,
        open_item_id: str | None,
        decided_by: str,
        source: str,
    ) -> dict[str, Any]:
        # Build bill data from accounting analysis
        bill_data = _build_bill_data(accounting_payload, correction_payload)
        bill_result: dict = {}
        akaunting_bill_id = None
        try:
            bill_result = await self.akaunting_connector.create_bill_draft(bill_data)
            akaunting_bill_id = bill_result.get('bill_id')
        except Exception as exc:
            logger.warning('Akaunting bill draft failed for case %s: %s', case_id, exc)
            bill_result = {'error': str(exc)}

        # Update approval
        await self.approval_service.decide_approval(
            approval_id=approval_id,
            decision='APPROVED',
            decided_by=decided_by,
            reason='User approved booking via Frya',
            source=source,
        )

        # Mark open item COMPLETED
        if open_item_id:
            await self.open_items_service.update_status(open_item_id, 'COMPLETED')

        await self.audit_service.log_event({
            'event_id': str(uuid.uuid4()),
            'case_id': case_id,
            'source': source,
            'agent_name': 'booking-approval',
            'approval_status': 'APPROVED',
            'action': 'USER_APPROVED_BOOKING',
            'result': f'Bill draft created. Akaunting bill_id={akaunting_bill_id}',
            'llm_output': bill_result,
        })

        return {
            'decision': 'APPROVE',
            'approval_status': 'APPROVED',
            'open_item_status': 'COMPLETED',
            'akaunting_bill_id': akaunting_bill_id,
            'akaunting_result': bill_result,
            'message': 'Buchungsentwurf wurde in Akaunting angelegt.',
        }

    async def _handle_reject(
        self,
        *,
        case_id: str,
        approval_id: str,
        open_item_id: str | None,
        decided_by: str,
        source: str,
    ) -> dict[str, Any]:
        await self.approval_service.decide_approval(
            approval_id=approval_id,
            decision='REJECTED',
            decided_by=decided_by,
            reason='User rejected booking proposal',
            source=source,
        )
        if open_item_id:
            await self.open_items_service.update_status(open_item_id, 'CANCELLED')

        await self.audit_service.log_event({
            'event_id': str(uuid.uuid4()),
            'case_id': case_id,
            'source': source,
            'agent_name': 'booking-approval',
            'approval_status': 'REJECTED',
            'action': 'USER_REJECTED_BOOKING',
            'result': 'User rejected the booking proposal.',
        })
        return {
            'decision': 'REJECT',
            'approval_status': 'REJECTED',
            'open_item_status': 'CANCELLED',
            'akaunting_bill_id': None,
            'message': 'Buchungsvorschlag abgelehnt. Soll ich ihn anders buchen oder komplett ignorieren?',
        }

    async def _handle_correct(
        self,
        *,
        case_id: str,
        approval_id: str,
        accounting_payload: dict,
        correction_payload: dict,
        open_item_id: str | None,
        decided_by: str,
        source: str,
    ) -> dict[str, Any]:
        # Apply correction and re-validate
        from app.security.output_validator import validate_booking_proposal

        corrected_payload = {**accounting_payload, **correction_payload}

        # If SKR03 account changed, update category
        if 'skr03_soll' in correction_payload:
            corrected_payload['category_name'] = skr03_to_akaunting_category(correction_payload['skr03_soll'])

        # Validate corrected proposal
        validation = validate_booking_proposal(type('P', (), corrected_payload)())
        if validation.findings and any(f.severity == 'HIGH' for f in validation.findings):
            return {
                'decision': 'CORRECT',
                'approval_status': 'PENDING',
                'open_item_status': 'PENDING_APPROVAL',
                'akaunting_bill_id': None,
                'message': f'Korrektur ungültig: {validation.findings[0].detail if validation.findings else "Unbekannter Fehler"}',
            }

        # Correction valid → approve with corrected data
        return await self._handle_approve(
            case_id=case_id,
            approval_id=approval_id,
            accounting_payload=accounting_payload,
            correction_payload=corrected_payload,
            open_item_id=open_item_id,
            decided_by=decided_by,
            source=source,
        )

    async def _handle_defer(
        self,
        *,
        case_id: str,
        approval_id: str,
        open_item_id: str | None,
        decided_by: str,
    ) -> dict[str, Any]:
        # Do nothing — keep PENDING_APPROVAL, will appear in next daily summary
        await self.audit_service.log_event({
            'event_id': str(uuid.uuid4()),
            'case_id': case_id,
            'source': 'api',
            'agent_name': 'booking-approval',
            'approval_status': 'PENDING',
            'action': 'USER_DEFERRED_BOOKING',
            'result': 'User deferred booking decision.',
        })
        return {
            'decision': 'DEFER',
            'approval_status': 'PENDING',
            'open_item_status': 'PENDING_APPROVAL',
            'akaunting_bill_id': None,
            'message': 'Buchungsvorschlag aufgeschoben. Erscheint in der nächsten Tages-Übersicht.',
        }


def _build_bill_data(accounting_payload: dict, correction: dict | None) -> dict:
    """Extract bill creation data from AccountingAnalysisResult payload."""
    merged = {**accounting_payload, **(correction or {})}

    # Extract from AccountingAnalysisResult structure
    amt = merged.get('amount_summary') or {}
    total_field = amt.get('total_amount') or {}
    currency_field = amt.get('currency') or {}

    vendor = (
        (merged.get('supplier_or_counterparty_hint') or {}).get('value')
        or merged.get('vendor_name')
        or 'Unbekannter Lieferant'
    )
    total = (
        total_field.get('value')
        or merged.get('amount')
    )
    currency = currency_field.get('value') or merged.get('currency_code') or 'EUR'
    due_date = (
        (merged.get('due_date_hint') or {}).get('value')
        or merged.get('due_at')
    )
    reference = (
        (merged.get('invoice_reference_hint') or {}).get('value')
        or merged.get('bill_number')
    )

    # SKR03 → Akaunting category
    skr03_soll = merged.get('skr03_soll')
    category_name = merged.get('category_name') or skr03_to_akaunting_category(str(skr03_soll) if skr03_soll else None)

    return {
        'vendor_name': vendor,
        'bill_number': reference,
        'billed_at': str(merged.get('billed_at') or ''),
        'due_at': str(due_date) if due_date else None,
        'amount': float(total) if total else 0.0,
        'currency_code': currency,
        'category_name': category_name,
        'items': merged.get('items') or [],
    }
