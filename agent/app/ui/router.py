from __future__ import annotations

import json
import os
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.status import HTTP_303_SEE_OTHER

from app.accounting_analysis.akaunting_reconciliation_service import AkauntingReconciliationService
from app.accounting_analysis.models import (
    AccountingClarificationCompletionInput,
    AccountingOperatorReviewDecisionInput,
    ExternalAccountingProcessResolutionInput,
    ExternalReturnClarificationCompletionInput,
)
from app.accounting_analysis.review_service import AccountingOperatorReviewService
from app.approvals.presentation import approval_next_step, latest_gate_summary
from app.approvals.service import ApprovalService
from app.audit.service import AuditService
from app.auth.csrf import get_csrf_token, require_csrf
from app.auth.dependencies import require_admin, require_operator
from app.auth.models import AuthUser
from app.banking.models import (
    BankingClarificationCompletionInput,
    ExternalBankingProcessCompletionInput,
    BankingHandoffReadyInput,
    BankingHandoffResolutionDecision,
    BankingHandoffResolutionInput,
    BankReconciliationReviewInput,
)
from app.banking.review_service import BankReconciliationReviewService
from app.cases.urls import ui_case_href
from app.config import get_settings
from app.banking.reconciliation_context import ReconciliationContextService
from app.banking.service import BankTransactionService
from app.dependencies import (
    get_accounting_operator_review_service,
    get_akaunting_reconciliation_service,
    get_approval_service,
    get_audit_service,
    get_bank_reconciliation_review_service,
    get_reconciliation_context_service,
    get_bank_transaction_service,
    get_case_repository,
    get_email_intake_repository,
    get_file_store,
    get_llm_config_repository,
    get_open_items_service,
    get_policy_access_layer,
    get_problem_case_service,
    get_telegram_case_link_service,
    get_telegram_clarification_service,
    get_telegram_document_analyst_followup_service,
    get_telegram_document_analyst_review_service,
    get_telegram_document_analyst_start_service,
    get_rule_change_audit_service,
    get_rule_loader,
)
from app.memory.file_store import FileStore
from app.open_items.models import OpenItem
from app.open_items.service import OpenItemsService
from app.problems.service import ProblemCaseService
from app.rules.audit_service import RuleChangeAuditService
from app.rules.loader import RuleLoader
from app.rules.policy_access import REQUIRED_POLICY_ROLES, PolicyAccessLayer
from app.telegram.document_analyst_followup_service import TelegramDocumentAnalystFollowupService
from app.telegram.document_analyst_review_service import TelegramDocumentAnalystReviewService
from app.telegram.document_analyst_start_service import TelegramDocumentAnalystStartService
from app.telegram.clarification_service import TelegramClarificationService
from app.telegram.models import TelegramCaseLinkRecord, TelegramClarificationRecord, TelegramUserVisibleStatus
from app.telegram.service import TelegramCaseLinkService
from app.case_engine.status import StatusTransitionError, allowed_transitions

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).resolve().parent / 'templates'))
router = APIRouter(prefix='/ui', tags=['ui'], dependencies=[Depends(require_operator)])


def _ctx(request: Request, **kwargs: Any) -> dict[str, Any]:
    auth_user = getattr(request.state, 'auth_user', None)
    base = {
        'request': request,
        'internal_notice': 'Interne Operator-UI mit Session-Auth/ACL.',
        'auth_user': auth_user,
        'csrf_token': get_csrf_token(request),
        'case_href': ui_case_href,
    }
    base.update(kwargs)
    return base


def _priority_of(item: OpenItem) -> str:
    if item.due_at is None:
        return 'UNSET'

    due = item.due_at
    if due.tzinfo is None:
        due = due.replace(tzinfo=timezone.utc)

    now = datetime.now(timezone.utc)
    if due <= now:
        return 'HIGH'
    if due <= now + timedelta(hours=24):
        return 'HIGH'
    if due <= now + timedelta(hours=72):
        return 'MEDIUM'
    return 'LOW'


def _case_kind(case_id: str) -> str:
    if case_id.startswith('doc-'):
        return 'Dokument'
    if case_id.startswith('tg-'):
        return 'Telegram'
    if case_id.startswith('rule:'):
        return 'Rule-Aenderung'
    if case_id.startswith('system-'):
        return 'System'
    return 'Allgemein'


def _collect_refs(events: list[Any], problems: list[Any], open_items: list[Any]) -> tuple[list[str], list[str]]:
    doc_refs = {e.document_ref for e in events if getattr(e, 'document_ref', None)}
    doc_refs.update({p.document_ref for p in problems if p.document_ref})
    doc_refs.update({o.document_ref for o in open_items if o.document_ref})

    acc_refs = {e.accounting_ref for e in events if getattr(e, 'accounting_ref', None)}
    acc_refs.update({p.accounting_ref for p in problems if p.accounting_ref})
    acc_refs.update({o.accounting_ref for o in open_items if o.accounting_ref})

    return sorted(doc_refs), sorted(acc_refs)


def _collect_policy_refs(events: list[Any]) -> list[dict[str, str]]:
    refs: list[dict[str, str]] = []
    seen: set[tuple[str | None, str | None, str | None]] = set()
    for event in events:
        for ref in getattr(event, 'policy_refs', []):
            key = (ref.get('policy_name'), ref.get('policy_version'), ref.get('policy_path'))
            if key in seen:
                continue
            seen.add(key)
            refs.append(ref)
    return refs


def _normalize_payload(payload: Any) -> Any:
    if isinstance(payload, str):
        try:
            return json.loads(payload)
        except Exception:
            return payload
    return payload


def _latest_telegram_received(events: list[Any]) -> dict[str, Any] | None:
    for event in reversed(events):
        if getattr(event, 'action', None) != 'TELEGRAM_WEBHOOK_RECEIVED':
            continue
        payload = _normalize_payload(getattr(event, 'llm_input', None))
        if isinstance(payload, dict):
            return {'action': event.action, 'created_at': str(getattr(event, 'created_at', '')), **payload}
    return None


def _latest_telegram_route(events: list[Any]) -> dict[str, Any] | None:
    for event in reversed(events):
        if getattr(event, 'action', None) not in {
            'TELEGRAM_ROUTED',
            'TELEGRAM_AUTH_DENIED',
            'TELEGRAM_SECRET_DENIED',
        }:
            continue
        payload = _normalize_payload(getattr(event, 'llm_output', None))
        if isinstance(payload, dict):
            return {'action': event.action, 'created_at': str(getattr(event, 'created_at', '')), **payload}
    return None


def _latest_telegram_reply(events: list[Any]) -> dict[str, Any] | None:
    for event in reversed(events):
        if getattr(event, 'action', None) != 'TELEGRAM_REPLY_ATTEMPTED':
            continue
        payload = _normalize_payload(getattr(event, 'llm_output', None))
        if isinstance(payload, dict):
            return {'action': event.action, 'created_at': str(getattr(event, 'created_at', '')), **payload}
    return None


def _latest_telegram_duplicate(events: list[Any]) -> dict[str, Any] | None:
    for event in reversed(events):
        if getattr(event, 'action', None) != 'TELEGRAM_DUPLICATE_IGNORED':
            continue
        payload = _normalize_payload(getattr(event, 'llm_output', None))
        if isinstance(payload, dict):
            return {'action': event.action, 'created_at': str(getattr(event, 'created_at', '')), **payload}
    return None


def _telegram_ingress(
    events: list[Any],
    case_link: TelegramCaseLinkRecord | None = None,
    user_visible_status: TelegramUserVisibleStatus | None = None,
) -> dict[str, Any] | None:
    received = _latest_telegram_received(events)
    route = _latest_telegram_route(events)
    reply = _latest_telegram_reply(events)
    duplicate = _latest_telegram_duplicate(events)
    if not received and not route and not reply and not duplicate:
        return None

    reply_ok = reply.get('reply_ok') if isinstance(reply, dict) else None
    reply_reason = reply.get('reply_reason') if isinstance(reply, dict) else None
    if reply_ok is True:
        reply_status = 'SENT'
    elif reply_reason == 'telegram_bot_token_missing':
        reply_status = 'SKIPPED_NO_TOKEN'
    elif reply is not None:
        reply_status = 'FAILED'
    else:
        reply_status = 'NOT_ATTEMPTED'

    return {
        'telegram_update_ref': (received or {}).get('telegram_update_ref'),
        'telegram_message_ref': (received or {}).get('telegram_message_ref'),
        'telegram_chat_ref': (received or {}).get('telegram_chat_ref'),
        'telegram_thread_ref': case_link.telegram_thread_ref if case_link else None,
        'chat_type': (received or {}).get('chat_type'),
        'sender_id': (received or {}).get('sender_id'),
        'sender_username': (received or {}).get('sender_username'),
        'text_preview': (received or {}).get('text'),
        'routing_status': (route or {}).get('routing_status') or (route or {}).get('result'),
        'intent_name': (route or {}).get('intent_name'),
        'authorization_status': (route or {}).get('authorization_status'),
        'auth_reason': (route or {}).get('auth_reason'),
        'open_item_id': (route or {}).get('open_item_id'),
        'open_item_title': (route or {}).get('open_item_title'),
        'next_manual_step': (route or {}).get('next_manual_step'),
        'ack_template': (route or {}).get('ack_template'),
        'duplicate_ignored': duplicate is not None,
        'duplicate_at': (duplicate or {}).get('created_at'),
        'reply_status': reply_status,
        'reply_ok': reply_ok,
        'reply_reason': reply_reason,
        'received_at': (received or {}).get('created_at'),
        'routed_at': (route or {}).get('created_at'),
        'replied_at': (reply or {}).get('created_at'),
        'linked_case_id': case_link.linked_case_id if case_link else None,
        'track_for_status': case_link.track_for_status if case_link else False,
        'user_visible_status': user_visible_status.model_dump(mode='json') if user_visible_status else None,
    }


def _telegram_clarification_payload(record: TelegramClarificationRecord | None) -> dict[str, Any] | None:
    if record is None:
        return None
    return record.model_dump(mode='json')


def _telegram_clarification_rounds_payload(records: list[TelegramClarificationRecord]) -> list[dict[str, Any]]:
    return [record.model_dump(mode='json') for record in records]


def _latest_telegram_media(events: list[Any]) -> dict[str, Any] | None:
    for event in reversed(events):
        if getattr(event, 'action', None) not in {
            'TELEGRAM_MEDIA_STORED',
            'TELEGRAM_MEDIA_QUEUED',
            'TELEGRAM_MEDIA_REJECTED',
            'TELEGRAM_MEDIA_DOWNLOAD_FAILED',
            'TELEGRAM_DOCUMENT_STORED',
            'TELEGRAM_DOCUMENT_QUEUED',
            'TELEGRAM_DOCUMENT_REJECTED',
            'TELEGRAM_DOCUMENT_DOWNLOAD_FAILED',
            'DOCUMENT_INBOX_ACCEPTED',
            'DOCUMENT_INTAKE_LINKED',
        }:
            continue
        payload = _normalize_payload(getattr(event, 'llm_output', None))
        if isinstance(payload, dict):
            return {'action': event.action, 'created_at': str(getattr(event, 'created_at', '')), **payload}
    return None


def _latest_telegram_notification(events: list[Any]) -> dict[str, Any] | None:
    for event in reversed(events):
        if getattr(event, 'action', None) not in {
            'TELEGRAM_NOTIFICATION_SENT',
            'TELEGRAM_NOTIFICATION_SKIPPED',
            'TELEGRAM_NOTIFICATION_FAILED',
        }:
            continue
        payload = _normalize_payload(getattr(event, 'llm_output', None))
        if isinstance(payload, dict):
            return {'action': event.action, 'created_at': str(getattr(event, 'created_at', '')), **payload}
    return None


def _latest_document_analyst_context(events: list[Any]) -> dict[str, Any] | None:
    for event in reversed(events):
        if getattr(event, 'action', None) not in {
            'DOCUMENT_ANALYST_CONTEXT_READY',
            'DOCUMENT_ANALYST_CONTEXT_ATTACHED',
            'DOCUMENT_ANALYST_PENDING',
        }:
            continue
        payload = _normalize_payload(getattr(event, 'llm_output', None))
        if isinstance(payload, dict):
            return {'action': event.action, 'created_at': str(getattr(event, 'created_at', '')), **payload}
    return None


def _latest_document_analyst_start(events: list[Any]) -> dict[str, Any] | None:
    for event in reversed(events):
        if getattr(event, 'action', None) not in {
            'DOCUMENT_ANALYST_START_READY',
            'DOCUMENT_ANALYST_START_REQUESTED',
            'DOCUMENT_ANALYST_RUNTIME_STARTED',
            'DOCUMENT_ANALYST_RUNTIME_FAILED',
        }:
            continue
        payload = _normalize_payload(getattr(event, 'llm_output', None))
        if isinstance(payload, dict):
            return {'action': event.action, 'created_at': str(getattr(event, 'created_at', '')), **payload}
    return None


def _latest_document_analysis(events: list[Any]) -> dict[str, Any] | None:
    for event in reversed(events):
        if getattr(event, 'action', None) != 'DOCUMENT_ANALYSIS_COMPLETED':
            continue
        payload = _normalize_payload(getattr(event, 'llm_output', None))
        if isinstance(payload, dict):
            return {'action': event.action, 'created_at': str(getattr(event, 'created_at', '')), **payload}
    return None


def _latest_document_analyst_review(events: list[Any]) -> dict[str, Any] | None:
    for event in reversed(events):
        if getattr(event, 'action', None) not in {
            'DOCUMENT_ANALYST_REVIEW_READY',
            'DOCUMENT_ANALYST_REVIEW_COMPLETED',
            'DOCUMENT_ANALYST_REVIEW_STILL_OPEN',
        }:
            continue
        payload = _normalize_payload(getattr(event, 'llm_output', None))
        if isinstance(payload, dict):
            return {'action': event.action, 'created_at': str(getattr(event, 'created_at', '')), **payload}
    return None


def _latest_document_analyst_followup(events: list[Any]) -> dict[str, Any] | None:
    for event in reversed(events):
        if getattr(event, 'action', None) not in {
            'DOCUMENT_ANALYST_FOLLOWUP_REQUIRED',
            'DOCUMENT_ANALYST_FOLLOWUP_DATA_REQUESTED',
            'DOCUMENT_ANALYST_FOLLOWUP_INTERNAL_ONLY',
            'DOCUMENT_ANALYST_FOLLOWUP_COMPLETED',
        }:
            continue
        payload = _normalize_payload(getattr(event, 'llm_output', None))
        if isinstance(payload, dict):
            return {'action': event.action, 'created_at': str(getattr(event, 'created_at', '')), **payload}
    return None


def _latest_accounting_review(events: list[Any]) -> dict[str, Any] | None:
    for event in reversed(events):
        if getattr(event, 'action', None) == 'ACCOUNTING_REVIEW_DRAFT_READY' and getattr(event, 'llm_output', None):
            payload = _normalize_payload(event.llm_output)
            if isinstance(payload, dict):
                return payload
    return None


def _latest_accounting_analysis(events: list[Any]) -> dict[str, Any] | None:
    for event in reversed(events):
        if getattr(event, 'action', None) == 'ACCOUNTING_ANALYSIS_COMPLETED' and getattr(event, 'llm_output', None):
            payload = _normalize_payload(event.llm_output)
            if isinstance(payload, dict):
                return payload
    return None


def _latest_accounting_operator_review(events: list[Any]) -> dict[str, Any] | None:
    for event in reversed(events):
        if getattr(event, 'action', None) not in {'ACCOUNTING_OPERATOR_REVIEW_CONFIRMED', 'ACCOUNTING_OPERATOR_REVIEW_REJECTED'}:
            continue
        if not getattr(event, 'llm_output', None):
            continue
        payload = _normalize_payload(event.llm_output)
        if isinstance(payload, dict):
            return payload
    return None


def _latest_accounting_manual_handoff(events: list[Any]) -> dict[str, Any] | None:
    for event in reversed(events):
        if getattr(event, 'action', None) != 'ACCOUNTING_MANUAL_HANDOFF_READY':
            continue
        if not getattr(event, 'llm_output', None):
            continue
        payload = _normalize_payload(event.llm_output)
        if isinstance(payload, dict):
            return payload
    return None


def _latest_accounting_manual_handoff_resolution(events: list[Any]) -> dict[str, Any] | None:
    for event in reversed(events):
        if getattr(event, 'action', None) not in {'ACCOUNTING_MANUAL_HANDOFF_COMPLETED', 'ACCOUNTING_MANUAL_HANDOFF_RETURNED'}:
            continue
        if not getattr(event, 'llm_output', None):
            continue
        payload = _normalize_payload(event.llm_output)
        if isinstance(payload, dict):
            return payload
    return None


def _latest_accounting_clarification_completion(events: list[Any]) -> dict[str, Any] | None:
    for event in reversed(events):
        if getattr(event, 'action', None) != 'ACCOUNTING_CLARIFICATION_COMPLETED':
            continue
        if not getattr(event, 'llm_output', None):
            continue
        payload = _normalize_payload(event.llm_output)
        if isinstance(payload, dict):
            return payload
    return None



def _latest_external_accounting_process_resolution(events: list[Any]) -> dict[str, Any] | None:
    for event in reversed(events):
        if getattr(event, 'action', None) not in {'EXTERNAL_ACCOUNTING_COMPLETED', 'EXTERNAL_ACCOUNTING_RETURNED'}:
            continue
        if not getattr(event, 'llm_output', None):
            continue
        payload = _normalize_payload(event.llm_output)
        if isinstance(payload, dict):
            return payload
    return None


def _latest_external_return_clarification_completion(events: list[Any]) -> dict[str, Any] | None:
    for event in reversed(events):
        if getattr(event, 'action', None) != 'EXTERNAL_RETURN_CLARIFICATION_COMPLETED':
            continue
        if not getattr(event, 'llm_output', None):
            continue
        payload = _normalize_payload(event.llm_output)
        if isinstance(payload, dict):
            return payload
    return None


def _latest_akaunting_probe(events: list[Any]) -> dict[str, Any] | None:
    for event in reversed(events):
        if getattr(event, 'action', None) != 'AKAUNTING_PROBE_EXECUTED':
            continue
        if not getattr(event, 'llm_output', None):
            continue
        payload = _normalize_payload(event.llm_output)
        if isinstance(payload, dict):
            return payload
    return None


def _latest_bank_transaction(events: list[Any]) -> dict[str, Any] | None:
    for event in reversed(events):
        if getattr(event, 'action', None) != 'BANK_TRANSACTION_PROBE_EXECUTED':
            continue
        if not getattr(event, 'llm_output', None):
            continue
        payload = _normalize_payload(event.llm_output)
        if isinstance(payload, dict):
            return payload
    return None


def _latest_bank_reconciliation_review(events: list[Any]) -> dict[str, Any] | None:
    for event in reversed(events):
        if getattr(event, 'action', None) not in {'BANK_RECONCILIATION_CONFIRMED', 'BANK_RECONCILIATION_REJECTED'}:
            continue
        if not getattr(event, 'llm_output', None):
            continue
        payload = _normalize_payload(event.llm_output)
        if isinstance(payload, dict):
            return payload
    return None


def _latest_bank_handoff_ready(events: list[Any]) -> dict[str, Any] | None:
    for event in reversed(events):
        if getattr(event, 'action', None) != 'BANKING_HANDOFF_READY':
            continue
        if not getattr(event, 'llm_output', None):
            continue
        payload = _normalize_payload(event.llm_output)
        if isinstance(payload, dict):
            return payload
    return None


def _latest_bank_handoff_resolution(events: list[Any]) -> dict[str, Any] | None:
    for event in reversed(events):
        if getattr(event, 'action', None) not in {'BANKING_HANDOFF_COMPLETED', 'BANKING_HANDOFF_RETURNED'}:
            continue
        if not getattr(event, 'llm_output', None):
            continue
        payload = _normalize_payload(event.llm_output)
        if isinstance(payload, dict):
            return payload
    return None


def _latest_bank_clarification(events: list[Any]) -> dict[str, Any] | None:
    latest_completion: dict[str, Any] | None = None
    latest_return: dict[str, Any] | None = None
    for event in reversed(events):
        action = getattr(event, 'action', None)
        if latest_completion is None and action == 'BANKING_CLARIFICATION_COMPLETED' and getattr(event, 'llm_output', None):
            payload = _normalize_payload(event.llm_output)
            if isinstance(payload, dict):
                latest_completion = payload
        if latest_return is None and action == 'BANKING_HANDOFF_RETURNED' and getattr(event, 'llm_output', None):
            payload = _normalize_payload(event.llm_output)
            if isinstance(payload, dict):
                latest_return = payload
        if latest_completion is not None and latest_return is not None:
            break
    if latest_completion is not None:
        return latest_completion
    if latest_return is None:
        return None
    return {
        'status': 'BANKING_CLARIFICATION_OPEN',
        'clarification_state': latest_return.get('clarification_state') or 'OPEN',
        'clarification_ref': latest_return.get('clarification_ref') or latest_return.get('resolution_id'),
        'handoff_ref': latest_return.get('handoff_ref'),
        'review_ref': latest_return.get('review_ref'),
        'workbench_ref': latest_return.get('workbench_ref'),
        'transaction_id': latest_return.get('transaction_id'),
        'candidate_reference': latest_return.get('candidate_reference'),
        'clarification_guidance': 'Rueckgabegrund manuell klaeren und den Klaerabschluss dokumentieren.',
        'required_manual_evidence': 'Kurznotiz, welche Rueckfrage oder Pruefung den Banking-Ruecklauf klaert.',
        'next_manual_step': 'Klaerung dokumentieren oder den Fall bewusst offen halten.',
        'clarification_open_item_id': latest_return.get('follow_up_open_item_id'),
        'clarification_open_item_title': latest_return.get('follow_up_open_item_title'),
        'bank_write_executed': False,
        'no_financial_write': True,
    }


def _latest_external_banking_process_resolution(events: list[Any]) -> dict[str, Any] | None:
    for event in reversed(events):
        if getattr(event, 'action', None) != 'EXTERNAL_BANKING_PROCESS_COMPLETED':
            continue
        if not getattr(event, 'llm_output', None):
            continue
        payload = _normalize_payload(event.llm_output)
        if isinstance(payload, dict):
            return payload
    return None


def _outside_agent_banking_process(
    bank_handoff_resolution: dict[str, Any] | None,
    bank_clarification: dict[str, Any] | None,
    external_banking_process_resolution: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if external_banking_process_resolution:
        return {
            'status': external_banking_process_resolution.get('status'),
            'suggested_next_step': external_banking_process_resolution.get('suggested_next_step'),
            'outside_process_open_item_id': external_banking_process_resolution.get('outside_process_open_item_id'),
            'outside_process_open_item_title': external_banking_process_resolution.get('outside_process_open_item_title'),
            'source_status': external_banking_process_resolution.get('source_internal_status'),
            'resolution_recorded': True,
        }
    if bank_clarification and bank_clarification.get('status') == 'BANKING_CLARIFICATION_COMPLETED':
        return {
            'status': 'OUTSIDE_AGENT_BANKING_PROCESS',
            'suggested_next_step': 'EXTERNAL_BANKING_PROCESS_COMPLETION',
            'outside_process_open_item_id': bank_clarification.get('outside_process_open_item_id'),
            'outside_process_open_item_title': bank_clarification.get('outside_process_open_item_title') or '[Banking] Externen Banking-Abschluss dokumentieren',
            'source_status': bank_clarification.get('status'),
            'resolution_recorded': False,
        }
    if bank_handoff_resolution and bank_handoff_resolution.get('decision') == 'COMPLETED':
        return {
            'status': 'OUTSIDE_AGENT_BANKING_PROCESS',
            'suggested_next_step': 'EXTERNAL_BANKING_PROCESS_COMPLETION',
            'outside_process_open_item_id': bank_handoff_resolution.get('outside_process_open_item_id'),
            'outside_process_open_item_title': bank_handoff_resolution.get('outside_process_open_item_title') or '[Banking] Externen Banking-Abschluss dokumentieren',
            'source_status': bank_handoff_resolution.get('status'),
            'resolution_recorded': False,
        }
    return None

def _should_build_reconciliation_context(
    events: list[Any],
    document_refs: list[str],
    accounting_refs: list[str],
) -> bool:
    actions = {getattr(event, 'action', '') or '' for event in events}
    if any(action.startswith('BANK_') or action.startswith('AKAUNTING_') for action in actions):
        return True
    refs = [*document_refs, *accounting_refs]
    return any(str(ref).upper().startswith(('INV-', 'OUT-', 'EXP-', 'REC-', 'BILL-')) for ref in refs)


def _outside_agent_accounting_process(
    manual_handoff_resolution: dict[str, Any] | None,
    clarification_completion: dict[str, Any] | None,
    external_resolution: dict[str, Any] | None,
    external_return_clarification_completion: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if external_return_clarification_completion:
        return {
            'status': external_return_clarification_completion.get('status'),
            'suggested_next_step': external_return_clarification_completion.get('suggested_next_step'),
            'outside_process_open_item_id': external_return_clarification_completion.get('external_return_open_item_id'),
            'outside_process_open_item_title': external_return_clarification_completion.get('external_return_open_item_title'),
            'source_status': external_return_clarification_completion.get('status'),
            'resolution_recorded': True,
            'reclarification_recorded': True,
        }
    if external_resolution:
        return {
            'status': external_resolution.get('status'),
            'suggested_next_step': external_resolution.get('suggested_next_step'),
            'outside_process_open_item_id': external_resolution.get('outside_process_open_item_id'),
            'outside_process_open_item_title': external_resolution.get('outside_process_open_item_title'),
            'source_status': external_resolution.get('status'),
            'resolution_recorded': True,
            'reclarification_recorded': False,
        }
    if clarification_completion and clarification_completion.get('suggested_next_step') == 'OUTSIDE_AGENT_ACCOUNTING_PROCESS':
        return {
            'status': 'OUTSIDE_AGENT_ACCOUNTING_PROCESS',
            'suggested_next_step': 'EXTERNAL_ACCOUNTING_RESOLUTION',
            'outside_process_open_item_id': clarification_completion.get('outside_process_open_item_id'),
            'outside_process_open_item_title': clarification_completion.get('outside_process_open_item_title'),
            'source_status': clarification_completion.get('status'),
            'resolution_recorded': False,
            'reclarification_recorded': False,
        }
    if manual_handoff_resolution and manual_handoff_resolution.get('decision') == 'COMPLETED':
        return {
            'status': 'OUTSIDE_AGENT_ACCOUNTING_PROCESS',
            'suggested_next_step': 'EXTERNAL_ACCOUNTING_RESOLUTION',
            'outside_process_open_item_id': manual_handoff_resolution.get('outside_process_open_item_id'),
            'outside_process_open_item_title': manual_handoff_resolution.get('outside_process_open_item_title'),
            'source_status': manual_handoff_resolution.get('status'),
            'resolution_recorded': False,
            'reclarification_recorded': False,
        }
    return None
def _can_submit_accounting_review(accounting_analysis: dict[str, Any] | None, operator_review: dict[str, Any] | None) -> bool:
    if operator_review is not None:
        return False
    if not accounting_analysis:
        return False
    return accounting_analysis.get('global_decision') == 'PROPOSED'


def _can_complete_accounting_clarification(
    manual_handoff_resolution: dict[str, Any] | None,
    clarification_completion: dict[str, Any] | None,
) -> bool:
    if clarification_completion is not None:
        return False
    if not manual_handoff_resolution:
        return False
    return manual_handoff_resolution.get('decision') == 'RETURNED'



def _can_resolve_external_accounting_process(
    outside_agent_accounting_process: dict[str, Any] | None,
    external_resolution: dict[str, Any] | None,
) -> bool:
    if external_resolution is not None:
        return False
    if not outside_agent_accounting_process:
        return False
    return outside_agent_accounting_process.get('resolution_recorded') is False


def _can_complete_external_return_clarification(
    external_resolution: dict[str, Any] | None,
    external_return_clarification_completion: dict[str, Any] | None,
) -> bool:
    if external_return_clarification_completion is not None:
        return False
    if not external_resolution:
        return False
    return external_resolution.get('decision') == 'RETURNED'


def _can_submit_bank_review(reconciliation_context: Any | None) -> bool:
    if not reconciliation_context:
        return False
    trail = getattr(reconciliation_context, 'review_trail', None)
    if trail and any([trail.review_outcome, trail.handoff_status, trail.clarification_status]):
        return False
    return bool(getattr(reconciliation_context, 'best_candidate', None))


def _can_request_telegram_clarification(
    telegram_case_link: dict[str, Any] | None,
    telegram_clarification: dict[str, Any] | None,
) -> bool:
    if not telegram_case_link:
        return False
    if not telegram_case_link.get('track_for_status'):
        return False
    if telegram_clarification and telegram_clarification.get('clarification_state') in {'OPEN', 'ANSWER_RECEIVED', 'UNDER_REVIEW', 'AMBIGUOUS'}:
        return False
    if telegram_clarification and telegram_clarification.get('clarification_state') == 'STILL_OPEN':
        return bool(telegram_clarification.get('follow_up_allowed'))
    return True


def _can_mark_telegram_clarification_under_review(telegram_clarification: dict[str, Any] | None) -> bool:
    if not telegram_clarification:
        return False
    return telegram_clarification.get('clarification_state') == 'ANSWER_RECEIVED'


def _can_resolve_telegram_clarification(telegram_clarification: dict[str, Any] | None) -> bool:
    if not telegram_clarification:
        return False
    return telegram_clarification.get('clarification_state') == 'UNDER_REVIEW'


def _can_mark_telegram_internal_followup_under_review(telegram_clarification: dict[str, Any] | None) -> bool:
    if not telegram_clarification:
        return False
    return (
        telegram_clarification.get('clarification_state') == 'STILL_OPEN'
        and bool(telegram_clarification.get('internal_followup_required'))
        and telegram_clarification.get('internal_followup_state') == 'REQUIRED'
    )


def _can_complete_telegram_internal_followup(telegram_clarification: dict[str, Any] | None) -> bool:
    if not telegram_clarification:
        return False
    return (
        telegram_clarification.get('clarification_state') == 'STILL_OPEN'
        and telegram_clarification.get('internal_followup_state') == 'UNDER_REVIEW'
    )


def _can_start_document_analyst(
    document_analyst_context: dict[str, Any] | None,
    document_analyst_start: dict[str, Any] | None,
) -> bool:
    if not document_analyst_context:
        return False
    if document_analyst_context.get('analyst_context_status') not in {
        'DOCUMENT_ANALYST_PENDING',
        'DOCUMENT_ANALYST_CONTEXT_ATTACHED',
        'DOCUMENT_ANALYST_CONTEXT_READY',
    }:
        return False
    if not document_analyst_start:
        return True
    return document_analyst_start.get('analysis_start_status') not in {
        'DOCUMENT_ANALYST_START_REQUESTED',
        'DOCUMENT_ANALYST_RUNTIME_STARTED',
    }


def _can_review_document_analyst(
    document_analyst_start: dict[str, Any] | None,
    document_analyst_review: dict[str, Any] | None,
) -> bool:
    if not document_analyst_start:
        return False
    if document_analyst_start.get('analysis_start_status') != 'DOCUMENT_ANALYST_RUNTIME_STARTED':
        return False
    if not document_analyst_review:
        return True
    return document_analyst_review.get('review_status') == 'DOCUMENT_ANALYST_REVIEW_READY'


def _can_manage_document_analyst_followup(
    document_analyst_review: dict[str, Any] | None,
    document_analyst_followup: dict[str, Any] | None,
) -> bool:
    if not document_analyst_review:
        return False
    if document_analyst_review.get('review_status') != 'DOCUMENT_ANALYST_REVIEW_STILL_OPEN':
        return False
    if not document_analyst_followup:
        return True
    return document_analyst_followup.get('followup_status') in {
        'DOCUMENT_ANALYST_FOLLOWUP_REQUIRED',
        'DOCUMENT_ANALYST_FOLLOWUP_INTERNAL_ONLY',
    }


def _can_mark_bank_handoff_ready(
    bank_review: dict[str, Any] | None,
    bank_handoff_ready: dict[str, Any] | None,
    bank_handoff_resolution: dict[str, Any] | None,
) -> bool:
    if not bank_review:
        return False
    if bank_review.get('decision') != 'CONFIRMED':
        return False
    if bank_handoff_resolution is not None:
        return False
    return bank_handoff_ready is None


def _can_resolve_bank_handoff(
    bank_handoff_ready: dict[str, Any] | None,
    bank_handoff_resolution: dict[str, Any] | None,
) -> bool:
    return bank_handoff_ready is not None and bank_handoff_resolution is None


def _can_complete_bank_clarification(
    bank_handoff_resolution: dict[str, Any] | None,
    bank_clarification: dict[str, Any] | None,
) -> bool:
    if not bank_handoff_resolution:
        return False
    if bank_handoff_resolution.get('decision') != 'RETURNED':
        return False
    if not bank_clarification:
        return True
    return bank_clarification.get('status') == 'BANKING_CLARIFICATION_OPEN'


def _can_complete_external_banking_process(
    outside_agent_banking_process: dict[str, Any] | None,
    external_banking_process_resolution: dict[str, Any] | None,
) -> bool:
    if external_banking_process_resolution is not None:
        return False
    if not outside_agent_banking_process:
        return False
    return outside_agent_banking_process.get('resolution_recorded') is False

@router.get('', include_in_schema=False)
async def ui_root() -> RedirectResponse:
    return RedirectResponse(url='/ui/dashboard', status_code=HTTP_303_SEE_OTHER)


@router.get('/dashboard', response_class=HTMLResponse)
async def dashboard(
    request: Request,
    audit_service: AuditService = Depends(get_audit_service),
    open_items_service: OpenItemsService = Depends(get_open_items_service),
    problem_service: ProblemCaseService = Depends(get_problem_case_service),
    rule_change_service: RuleChangeAuditService = Depends(get_rule_change_audit_service),
    policy_access: PolicyAccessLayer = Depends(get_policy_access_layer),
    approval_service: ApprovalService = Depends(get_approval_service),
) -> HTMLResponse:
    settings = get_settings()

    recent_cases = await audit_service.case_ids(limit=15)
    open_items = await open_items_service.list_items()
    problem_cases = await problem_service.recent(limit=10)
    rule_changes = await rule_change_service.recent(limit=10)
    approvals = await approval_service.recent(limit=200)
    pending_approvals = [item for item in approvals if item.status == 'PENDING']

    counter = Counter(item.status for item in open_items)
    health = {'status': 'ok', 'service': 'frya-agent', 'llm_model': settings.llm_model}
    policies_ok, policies_missing = policy_access.required_policies_loaded()
    summary = {
        'recent_cases': len(recent_cases),
        'open_items': len(open_items),
        'problem_cases': len(problem_cases),
        'policy_missing': len(policies_missing),
        'pending_approvals': len(pending_approvals),
    }

    return TEMPLATES.TemplateResponse(
        request,
        'dashboard.html',
        _ctx(
            request,
            title='Dashboard',
            health=health,
            architecture={
                'agent_is_backend': True,
                'separate_backend_service_target': False,
            },
            recent_cases=recent_cases,
            open_item_counts=dict(counter),
            problem_cases=problem_cases,
            rule_changes=rule_changes,
            pending_approvals=pending_approvals[:10],
            policies_ok=policies_ok,
            policies_missing=policies_missing,
            summary=summary,
        ),
    )


@router.get('/cases', response_class=HTMLResponse)
async def ui_cases(
    request: Request,
    audit_service: AuditService = Depends(get_audit_service),
) -> HTMLResponse:
    case_ids = await audit_service.case_ids(limit=300)

    latest_by_case: dict[str, Any] = {}
    try:
        recent_events = await audit_service.recent(limit=2000)
        for event in recent_events:
            if event.case_id and event.case_id not in latest_by_case:
                latest_by_case[event.case_id] = event
    except Exception:
        latest_by_case = {}

    case_rows: list[dict[str, Any]] = []
    for cid in case_ids:
        latest = latest_by_case.get(cid)
        case_rows.append(
            {
                'case_id': cid,
                'kind': _case_kind(cid),
                'last_action': latest.action if latest else '-',
                'last_result': latest.result if latest else '-',
                'last_activity': latest.created_at if latest else None,
            }
        )

    return TEMPLATES.TemplateResponse(
        request,
        'cases_list.html',
        _ctx(request, title='Cases', case_rows=case_rows),
    )


@router.post('/cases/{case_id:path}/accounting-review-decision', dependencies=[Depends(require_csrf)])
async def ui_case_accounting_review_decision(
    request: Request,
    case_id: str,
    decision: str = Form(...),
    note: str = Form(default=''),
    review_service: AccountingOperatorReviewService = Depends(get_accounting_operator_review_service),
    current_user: AuthUser = Depends(require_admin),
) -> RedirectResponse:
    try:
        result = await review_service.decide(
            AccountingOperatorReviewDecisionInput(
                case_id=case_id,
                decision=decision,
                decided_by=current_user.username,
                decision_note=note or None,
                source='ui_case_detail',
            )
        )
        msg = f'Accounting Review {result.decision} gespeichert.'
    except ValueError as exc:
        msg = str(exc)
    return RedirectResponse(url=f'{ui_case_href(case_id)}?msg={quote(msg)}', status_code=HTTP_303_SEE_OTHER)


@router.post('/cases/{case_id:path}/accounting-clarification-complete', dependencies=[Depends(require_csrf)])
async def ui_case_accounting_clarification_complete(
    request: Request,
    case_id: str,
    note: str = Form(default=''),
    review_service: AccountingOperatorReviewService = Depends(get_accounting_operator_review_service),
    current_user: AuthUser = Depends(require_admin),
) -> RedirectResponse:
    try:
        result = await review_service.complete_clarification(
            AccountingClarificationCompletionInput(
                case_id=case_id,
                decided_by=current_user.username,
                note=note or None,
                source='ui_case_detail',
            )
        )
        msg = f'Accounting Klaerabschluss {result.status} gespeichert.'
    except ValueError as exc:
        msg = str(exc)
    return RedirectResponse(url=f'{ui_case_href(case_id)}?msg={quote(msg)}', status_code=HTTP_303_SEE_OTHER)


@router.post('/cases/{case_id:path}/external-accounting-resolution', dependencies=[Depends(require_csrf)])
async def ui_case_external_accounting_resolution(
    request: Request,
    case_id: str,
    decision: str = Form(...),
    note: str = Form(default=''),
    review_service: AccountingOperatorReviewService = Depends(get_accounting_operator_review_service),
    current_user: AuthUser = Depends(require_admin),
) -> RedirectResponse:
    try:
        result = await review_service.resolve_external_accounting_process(
            ExternalAccountingProcessResolutionInput(
                case_id=case_id,
                decision=decision,
                decided_by=current_user.username,
                note=note or None,
                source='ui_case_detail',
            )
        )
        msg = f'Externer Accounting-Abschluss {result.status} gespeichert.'
    except ValueError as exc:
        msg = str(exc)
    return RedirectResponse(url=f'{ui_case_href(case_id)}?msg={quote(msg)}', status_code=HTTP_303_SEE_OTHER)



@router.post('/cases/{case_id:path}/external-return-clarification-complete', dependencies=[Depends(require_csrf)])
async def ui_case_external_return_clarification_complete(
    request: Request,
    case_id: str,
    note: str = Form(default=''),
    review_service: AccountingOperatorReviewService = Depends(get_accounting_operator_review_service),
    current_user: AuthUser = Depends(require_admin),
) -> RedirectResponse:
    try:
        result = await review_service.complete_external_return_clarification(
            ExternalReturnClarificationCompletionInput(
                case_id=case_id,
                decided_by=current_user.username,
                note=note or None,
                source='ui_case_detail',
            )
        )
        msg = f'Externer Ruecklauf {result.status} gespeichert.'
    except ValueError as exc:
        msg = str(exc)
    return RedirectResponse(url=f'{ui_case_href(case_id)}?msg={quote(msg)}', status_code=HTTP_303_SEE_OTHER)

@router.post('/cases/{case_id:path}/akaunting-probe', dependencies=[Depends(require_csrf)])
async def ui_case_akaunting_probe(
    request: Request,
    case_id: str,
    reconciliation_service: AkauntingReconciliationService = Depends(get_akaunting_reconciliation_service),
) -> RedirectResponse:
    try:
        await reconciliation_service.probe_case(case_id=case_id, accounting_data={})
        msg = 'Akaunting-Abgleich ausgefuehrt.'
    except Exception as exc:
        msg = f'Probe-Fehler: {exc}'
    return RedirectResponse(url=f'{ui_case_href(case_id)}?msg={quote(msg)}', status_code=HTTP_303_SEE_OTHER)


@router.post('/cases/{case_id:path}/bank-transaction-probe', dependencies=[Depends(require_csrf)])
async def ui_case_bank_transaction_probe(
    request: Request,
    case_id: str,
    reference: str | None = Form(default=None),
    amount: str | None = Form(default=None),
    contact_name: str | None = Form(default=None),
    date_from: str | None = Form(default=None),
    date_to: str | None = Form(default=None),
    bank_service: BankTransactionService = Depends(get_bank_transaction_service),
) -> RedirectResponse:
    try:
        amount_float: float | None = float(amount) if amount and amount.strip() else None
        result = await bank_service.probe_transactions(
            case_id=case_id,
            reference=reference or None,
            amount=amount_float,
            contact_name=contact_name or None,
            date_from=date_from or None,
            date_to=date_to or None,
        )
        assert result.bank_write_executed is False, 'Bank safety invariant violated'
        msg = f'Bank-Probe: {result.result.value}'
    except Exception as exc:
        msg = f'Bank-Probe-Fehler: {exc}'
    return RedirectResponse(url=f'{ui_case_href(case_id)}?msg={quote(msg)}', status_code=HTTP_303_SEE_OTHER)


@router.post('/cases/{case_id:path}/bank-reconciliation-review', dependencies=[Depends(require_csrf)])
async def ui_case_bank_reconciliation_review(
    request: Request,
    case_id: str,
    decision: str = Form(...),
    note: str = Form(default=''),
    transaction_id: str | None = Form(default=None),
    candidate_amount: str | None = Form(default=None),
    candidate_currency: str | None = Form(default=None),
    candidate_date: str | None = Form(default=None),
    candidate_reference: str | None = Form(default=None),
    candidate_contact: str | None = Form(default=None),
    candidate_description: str | None = Form(default=None),
    confidence_score: str = Form(default='0'),
    match_quality: str = Form(default='LOW'),
    reason_codes: str = Form(default=''),
    tx_type: str | None = Form(default=None),
    probe_result: str = Form(default=''),
    probe_note: str = Form(default=''),
    workbench_ref: str = Form(...),
    workbench_signal: str = Form(default=''),
    workbench_guidance: str = Form(default=''),
    review_guidance: str = Form(default=''),
    candidate_rank: str | None = Form(default=None),
    review_service: BankReconciliationReviewService = Depends(get_bank_reconciliation_review_service),
    current_user: AuthUser = Depends(require_operator),
) -> RedirectResponse:
    try:
        result = await review_service.submit_review(
            BankReconciliationReviewInput(
                case_id=case_id,
                transaction_id=transaction_id,
                candidate_amount=float(candidate_amount) if candidate_amount not in (None, '') else None,
                candidate_currency=candidate_currency or None,
                candidate_date=candidate_date or None,
                candidate_reference=candidate_reference or None,
                candidate_contact=candidate_contact or None,
                candidate_description=candidate_description or None,
                confidence_score=int(confidence_score or '0'),
                match_quality=match_quality,
                reason_codes=[code for code in reason_codes.split(',') if code],
                tx_type=tx_type or None,
                probe_result=probe_result,
                probe_note=probe_note,
                workbench_ref=workbench_ref,
                workbench_signal=workbench_signal,
                workbench_guidance=workbench_guidance,
                review_guidance=review_guidance,
                candidate_rank=int(candidate_rank) if candidate_rank not in (None, '') else None,
                decision=decision,
                decision_note=note or '',
                decided_by=current_user.username,
                source='ui_case_detail',
            )
        )
        msg = f'Banking Review {result.decision} gespeichert.'
    except ValueError as exc:
        msg = str(exc)
    return RedirectResponse(url=f'{ui_case_href(case_id)}?msg={quote(msg)}', status_code=HTTP_303_SEE_OTHER)


@router.post('/cases/{case_id:path}/banking-handoff-ready', dependencies=[Depends(require_csrf)])
async def ui_case_banking_handoff_ready(
    request: Request,
    case_id: str,
    review_ref: str = Form(...),
    workbench_ref: str = Form(...),
    transaction_id: str | None = Form(default=None),
    note: str = Form(default=''),
    review_service: BankReconciliationReviewService = Depends(get_bank_reconciliation_review_service),
    current_user: AuthUser = Depends(require_operator),
) -> RedirectResponse:
    try:
        result = await review_service.mark_handoff_ready(
            BankingHandoffReadyInput(
                case_id=case_id,
                review_ref=review_ref,
                workbench_ref=workbench_ref,
                transaction_id=transaction_id,
                handoff_note=note or '',
                handed_off_by=current_user.username,
                source='ui_case_detail',
            )
        )
        msg = f'Banking Handoff {result.handoff_state} gespeichert.'
    except ValueError as exc:
        msg = str(exc)
    return RedirectResponse(url=f'{ui_case_href(case_id)}?msg={quote(msg)}', status_code=HTTP_303_SEE_OTHER)


@router.post('/cases/{case_id:path}/banking-handoff-resolution', dependencies=[Depends(require_csrf)])
async def ui_case_banking_handoff_resolution(
    request: Request,
    case_id: str,
    handoff_ref: str = Form(...),
    decision: str = Form(...),
    note: str = Form(default=''),
    review_service: BankReconciliationReviewService = Depends(get_bank_reconciliation_review_service),
    current_user: AuthUser = Depends(require_operator),
) -> RedirectResponse:
    try:
        result = await review_service.resolve_handoff(
            BankingHandoffResolutionInput(
                case_id=case_id,
                handoff_ref=handoff_ref,
                decision=BankingHandoffResolutionDecision(decision),
                resolution_note=note or '',
                resolved_by=current_user.username,
                source='ui_case_detail',
            )
        )
        msg = f'Banking Handoff {result.decision} gespeichert.'
    except ValueError as exc:
        msg = str(exc)
    return RedirectResponse(url=f'{ui_case_href(case_id)}?msg={quote(msg)}', status_code=HTTP_303_SEE_OTHER)


@router.post('/cases/{case_id:path}/banking-clarification-complete', dependencies=[Depends(require_csrf)])
async def ui_case_banking_clarification_complete(
    request: Request,
    case_id: str,
    clarification_ref: str = Form(...),
    note: str = Form(default=''),
    review_service: BankReconciliationReviewService = Depends(get_bank_reconciliation_review_service),
    current_user: AuthUser = Depends(require_operator),
) -> RedirectResponse:
    try:
        result = await review_service.complete_banking_clarification(
            BankingClarificationCompletionInput(
                case_id=case_id,
                clarification_ref=clarification_ref,
                clarification_note=note or '',
                clarified_by=current_user.username,
                source='ui_case_detail',
            )
        )
        msg = f'Banking Klaerabschluss {result.status} gespeichert.'
    except ValueError as exc:
        msg = str(exc)
    return RedirectResponse(url=f'{ui_case_href(case_id)}?msg={quote(msg)}', status_code=HTTP_303_SEE_OTHER)


@router.post('/cases/{case_id:path}/external-banking-process-complete', dependencies=[Depends(require_csrf)])
async def ui_case_external_banking_process_complete(
    request: Request,
    case_id: str,
    note: str = Form(default=''),
    review_service: BankReconciliationReviewService = Depends(get_bank_reconciliation_review_service),
    current_user: AuthUser = Depends(require_operator),
) -> RedirectResponse:
    try:
        result = await review_service.complete_external_banking_process(
            ExternalBankingProcessCompletionInput(
                case_id=case_id,
                resolution_note=note or '',
                resolved_by=current_user.username,
                source='ui_case_detail',
            )
        )
        msg = f'Externer Banking-Abschluss {result.status} gespeichert.'
    except ValueError as exc:
        msg = str(exc)
    return RedirectResponse(url=f'{ui_case_href(case_id)}?msg={quote(msg)}', status_code=HTTP_303_SEE_OTHER)


@router.post('/cases/{case_id:path}/telegram-clarification-request', dependencies=[Depends(require_csrf)])
async def ui_case_telegram_clarification_request(
    request: Request,
    case_id: str,
    question: str = Form(...),
    telegram_case_link_service: TelegramCaseLinkService = Depends(get_telegram_case_link_service),
    telegram_clarification_service: TelegramClarificationService = Depends(get_telegram_clarification_service),
    current_user: AuthUser = Depends(require_operator),
) -> RedirectResponse:
    try:
        link = await telegram_case_link_service.get_by_case(case_id)
        if link is None or not link.track_for_status:
            raise ValueError('Kein verknuepfter Telegram-Fall fuer Rueckfrage verfuegbar.')
        result = await telegram_clarification_service.request_clarification(
            linked_case_id=link.linked_case_id or case_id,
            telegram_case_link=link,
            question_text=question,
            asked_by=current_user.username,
            source='ui_case_detail',
        )
        msg = f'Telegram-Rueckfrage {result.clarification_state} gespeichert.'
    except ValueError as exc:
        msg = str(exc)
    return RedirectResponse(url=f'{ui_case_href(case_id)}?msg={quote(msg)}', status_code=HTTP_303_SEE_OTHER)


@router.post('/cases/{case_id:path}/telegram-clarification-under-review', dependencies=[Depends(require_csrf)])
async def ui_case_telegram_clarification_under_review(
    case_id: str,
    note: str = Form(default=''),
    telegram_clarification_service: TelegramClarificationService = Depends(get_telegram_clarification_service),
    current_user: AuthUser = Depends(require_operator),
) -> RedirectResponse:
    try:
        result = await telegram_clarification_service.mark_under_review(
            linked_case_id=case_id,
            reviewed_by=current_user.username,
            note=note,
            source='ui_case_detail',
        )
        msg = f'Telegram-Klaerung {result.clarification_state} gesetzt.'
    except ValueError as exc:
        msg = str(exc)
    return RedirectResponse(url=f'{ui_case_href(case_id)}?msg={quote(msg)}', status_code=HTTP_303_SEE_OTHER)


@router.post('/cases/{case_id:path}/telegram-clarification-resolution', dependencies=[Depends(require_csrf)])
async def ui_case_telegram_clarification_resolution(
    case_id: str,
    decision: str = Form(...),
    note: str = Form(default=''),
    telegram_clarification_service: TelegramClarificationService = Depends(get_telegram_clarification_service),
    current_user: AuthUser = Depends(require_operator),
) -> RedirectResponse:
    try:
        result = await telegram_clarification_service.resolve_clarification(
            linked_case_id=case_id,
            decision=decision,
            resolved_by=current_user.username,
            note=note,
            source='ui_case_detail',
        )
        msg = f'Telegram-Klaerung {result.clarification_state} gespeichert.'
    except ValueError as exc:
        msg = str(exc)
    return RedirectResponse(url=f'{ui_case_href(case_id)}?msg={quote(msg)}', status_code=HTTP_303_SEE_OTHER)


@router.post('/cases/{case_id:path}/telegram-internal-followup-under-review', dependencies=[Depends(require_csrf)])
async def ui_case_telegram_internal_followup_under_review(
    case_id: str,
    note: str = Form(default=''),
    telegram_clarification_service: TelegramClarificationService = Depends(get_telegram_clarification_service),
    current_user: AuthUser = Depends(require_operator),
) -> RedirectResponse:
    try:
        result = await telegram_clarification_service.mark_internal_followup_under_review(
            linked_case_id=case_id,
            reviewed_by=current_user.username,
            note=note,
            source='ui_case_detail',
        )
        msg = f'Telegram-interne Nachbearbeitung {result.internal_followup_state} gesetzt.'
    except ValueError as exc:
        msg = str(exc)
    return RedirectResponse(url=f'{ui_case_href(case_id)}?msg={quote(msg)}', status_code=HTTP_303_SEE_OTHER)


@router.post('/cases/{case_id:path}/telegram-internal-followup-resolution', dependencies=[Depends(require_csrf)])
async def ui_case_telegram_internal_followup_resolution(
    case_id: str,
    note: str = Form(default=''),
    telegram_clarification_service: TelegramClarificationService = Depends(get_telegram_clarification_service),
    current_user: AuthUser = Depends(require_operator),
) -> RedirectResponse:
    try:
        result = await telegram_clarification_service.complete_internal_followup(
            linked_case_id=case_id,
            resolved_by=current_user.username,
            note=note,
            source='ui_case_detail',
        )
        msg = f'Telegram-interne Nachbearbeitung {result.internal_followup_state} gespeichert.'
    except ValueError as exc:
        msg = str(exc)
    return RedirectResponse(url=f'{ui_case_href(case_id)}?msg={quote(msg)}', status_code=HTTP_303_SEE_OTHER)


@router.post('/cases/{case_id:path}/document-analyst-start', dependencies=[Depends(require_csrf)])
async def ui_case_document_analyst_start(
    request: Request,
    case_id: str,
    note: str = Form(default=''),
    document_analyst_start_service: TelegramDocumentAnalystStartService = Depends(get_telegram_document_analyst_start_service),
    current_user: AuthUser = Depends(require_operator),
) -> RedirectResponse:
    try:
        result = await document_analyst_start_service.start_runtime(
            case_id,
            actor=current_user.username,
            note=note,
            trigger='ui_case_detail',
            graph=request.app.state.graph,
        )
        msg = f'Document-Analyst-Start {result.analysis_start_status} gespeichert.'
    except ValueError as exc:
        msg = str(exc)
    return RedirectResponse(url=f'{ui_case_href(case_id)}?msg={quote(msg)}', status_code=HTTP_303_SEE_OTHER)


@router.post('/cases/{case_id:path}/document-analyst-review', dependencies=[Depends(require_csrf)])
async def ui_case_document_analyst_review(
    case_id: str,
    decision: str = Form(...),
    note: str = Form(default=''),
    document_analyst_review_service: TelegramDocumentAnalystReviewService = Depends(get_telegram_document_analyst_review_service),
    current_user: AuthUser = Depends(require_operator),
) -> RedirectResponse:
    try:
        result = await document_analyst_review_service.resolve_review(
            case_id,
            decision=decision,
            reviewed_by=current_user.username,
            note=note,
            source='ui_case_detail',
        )
        msg = f'Document-Analyst-Review {result.review_status} gespeichert.'
    except ValueError as exc:
        msg = str(exc)
    return RedirectResponse(url=f'{ui_case_href(case_id)}?msg={quote(msg)}', status_code=HTTP_303_SEE_OTHER)


@router.post('/cases/{case_id:path}/document-analyst-followup', dependencies=[Depends(require_csrf)])
async def ui_case_document_analyst_followup(
    case_id: str,
    mode: str = Form(...),
    note: str = Form(default=''),
    question: str = Form(default=''),
    document_analyst_followup_service: TelegramDocumentAnalystFollowupService = Depends(get_telegram_document_analyst_followup_service),
    current_user: AuthUser = Depends(require_operator),
) -> RedirectResponse:
    try:
        result = await document_analyst_followup_service.execute_followup(
            case_id,
            mode=mode,
            actor=current_user.username,
            note=note,
            source='ui_case_detail',
            question_text=question,
        )
        msg = f'Document-Analyst-Follow-up {result.followup_status} gespeichert.'
    except ValueError as exc:
        msg = str(exc)
    return RedirectResponse(url=f'{ui_case_href(case_id)}?msg={quote(msg)}', status_code=HTTP_303_SEE_OTHER)


@router.get('/cases/{case_id:path}', response_class=HTMLResponse)
async def ui_case_detail(
    request: Request,
    case_id: str,
    audit_service: AuditService = Depends(get_audit_service),
    open_items_service: OpenItemsService = Depends(get_open_items_service),
    problem_service: ProblemCaseService = Depends(get_problem_case_service),
    approval_service: ApprovalService = Depends(get_approval_service),
    reconciliation_context_service: ReconciliationContextService = Depends(get_reconciliation_context_service),
    telegram_case_link_service: TelegramCaseLinkService = Depends(get_telegram_case_link_service),
    telegram_clarification_service: TelegramClarificationService = Depends(get_telegram_clarification_service),
) -> HTMLResponse:
    chronology = await audit_service.by_case(case_id, limit=1000)
    open_items = await open_items_service.list_by_case(case_id)
    problems = await problem_service.by_case(case_id)
    approvals = await approval_service.list_by_case(case_id)

    if not chronology and not open_items and not problems and not approvals:
        raise HTTPException(status_code=404, detail='Case nicht gefunden')

    document_refs, accounting_refs = _collect_refs(chronology, problems, open_items)
    approvals_from_audit = [e for e in chronology if e.approval_status in {'APPROVED', 'REJECTED', 'PENDING', 'CANCELLED', 'EXPIRED', 'REVOKED'}]
    decisions = [e for e in chronology if e.action not in {'SYSTEM_STARTUP'}]
    exceptions = [p for p in problems]
    policy_refs = _collect_policy_refs(chronology)
    latest_gate = latest_gate_summary(chronology)
    accounting_review = _latest_accounting_review(chronology)
    accounting_analysis = _latest_accounting_analysis(chronology)
    accounting_operator_review = _latest_accounting_operator_review(chronology)
    accounting_manual_handoff = _latest_accounting_manual_handoff(chronology)
    accounting_manual_handoff_resolution = _latest_accounting_manual_handoff_resolution(chronology)
    accounting_clarification_completion = _latest_accounting_clarification_completion(chronology)
    external_accounting_process_resolution = _latest_external_accounting_process_resolution(chronology)
    external_return_clarification_completion = _latest_external_return_clarification_completion(chronology)
    outside_agent_accounting_process = _outside_agent_accounting_process(
        accounting_manual_handoff_resolution,
        accounting_clarification_completion,
        external_accounting_process_resolution,
        external_return_clarification_completion,
    )
    akaunting_probe = _latest_akaunting_probe(chronology)
    bank_transaction_probe = _latest_bank_transaction(chronology)
    bank_reconciliation_review = _latest_bank_reconciliation_review(chronology)
    banking_handoff_ready = _latest_bank_handoff_ready(chronology)
    banking_handoff_resolution = _latest_bank_handoff_resolution(chronology)
    bank_clarification = _latest_bank_clarification(chronology)
    external_banking_process_resolution = _latest_external_banking_process_resolution(chronology)
    telegram_case_link = await telegram_case_link_service.get_by_case(case_id)
    telegram_user_status = None
    telegram_clarification = None
    telegram_clarification_rounds: list[TelegramClarificationRecord] = []
    if telegram_case_link is not None:
        linked_case_id = telegram_case_link.linked_case_id or case_id
        telegram_clarification = await telegram_clarification_service.latest_by_case(linked_case_id)
        telegram_clarification_rounds = await telegram_clarification_service.list_by_case(linked_case_id)
        linked_open_items = open_items if linked_case_id == case_id else await open_items_service.list_by_case(linked_case_id)
        linked_problems = problems if linked_case_id == case_id else await problem_service.by_case(linked_case_id)
        linked_chronology = chronology if linked_case_id == case_id else await audit_service.by_case(linked_case_id, limit=200)
        telegram_user_status = await telegram_case_link_service.build_user_visible_status(
            telegram_case_link,
            linked_open_items,
            linked_problems,
            linked_chronology,
            telegram_clarification,
        )
    telegram_ingress = _telegram_ingress(chronology, telegram_case_link, telegram_user_status)
    telegram_media = _latest_telegram_media(chronology)
    document_analyst_context = _latest_document_analyst_context(chronology)
    document_analyst_start = _latest_document_analyst_start(chronology)
    document_analysis = _latest_document_analysis(chronology)
    document_analyst_review = _latest_document_analyst_review(chronology)
    document_analyst_followup = _latest_document_analyst_followup(chronology)
    telegram_notification = _latest_telegram_notification(chronology)
    outside_agent_banking_process = _outside_agent_banking_process(
        banking_handoff_resolution,
        bank_clarification,
        external_banking_process_resolution,
    )
    reconciliation_context = None
    if _should_build_reconciliation_context(chronology, document_refs, accounting_refs):
        reconciliation_context = await reconciliation_context_service.build(case_id=case_id)

    return TEMPLATES.TemplateResponse(
        request,
        'case_detail.html',
        _ctx(
            request,
            title=f'Case {case_id}',
            case_id=case_id,
            chronology=chronology,
            document_refs=document_refs,
            accounting_refs=accounting_refs,
            approvals=approvals,
            approvals_from_audit=approvals_from_audit,
            decisions=decisions,
            exceptions=exceptions,
            open_items=open_items,
            policy_refs=policy_refs,
            latest_gate=latest_gate,
            accounting_review=accounting_review,
            accounting_analysis=accounting_analysis,
            accounting_operator_review=accounting_operator_review,
            accounting_manual_handoff=accounting_manual_handoff,
            accounting_manual_handoff_resolution=accounting_manual_handoff_resolution,
            accounting_clarification_completion=accounting_clarification_completion,
            outside_agent_accounting_process=outside_agent_accounting_process,
            external_accounting_process_resolution=external_accounting_process_resolution,
            external_return_clarification_completion=external_return_clarification_completion,
            akaunting_probe=akaunting_probe,
            bank_transaction_probe=bank_transaction_probe,
            bank_reconciliation_review=bank_reconciliation_review,
            banking_handoff_ready=banking_handoff_ready,
            banking_handoff_resolution=banking_handoff_resolution,
            bank_clarification=bank_clarification,
            outside_agent_banking_process=outside_agent_banking_process,
            external_banking_process_resolution=external_banking_process_resolution,
            telegram_ingress=telegram_ingress,
            telegram_media=telegram_media,
            document_analyst_context=document_analyst_context,
            document_analyst_start=document_analyst_start,
            document_analysis=document_analysis,
            document_analyst_review=document_analyst_review,
            document_analyst_followup=document_analyst_followup,
            telegram_notification=telegram_notification,
            telegram_case_link=telegram_case_link.model_dump(mode='json') if telegram_case_link else None,
            telegram_clarification=_telegram_clarification_payload(telegram_clarification),
            telegram_clarification_rounds=_telegram_clarification_rounds_payload(telegram_clarification_rounds),
            reconciliation_context=reconciliation_context,
            can_request_telegram_clarification=_can_request_telegram_clarification(
                telegram_case_link.model_dump(mode='json') if telegram_case_link else None,
                _telegram_clarification_payload(telegram_clarification),
            ),
            can_mark_telegram_clarification_under_review=_can_mark_telegram_clarification_under_review(
                _telegram_clarification_payload(telegram_clarification),
            ),
            can_resolve_telegram_clarification=_can_resolve_telegram_clarification(
                _telegram_clarification_payload(telegram_clarification),
            ),
            can_mark_telegram_internal_followup_under_review=_can_mark_telegram_internal_followup_under_review(
                _telegram_clarification_payload(telegram_clarification),
            ),
            can_complete_telegram_internal_followup=_can_complete_telegram_internal_followup(
                _telegram_clarification_payload(telegram_clarification),
            ),
            can_start_document_analyst=_can_start_document_analyst(
                document_analyst_context,
                document_analyst_start,
            ),
            can_review_document_analyst=_can_review_document_analyst(
                document_analyst_start,
                document_analyst_review,
            ),
            can_manage_document_analyst_followup=_can_manage_document_analyst_followup(
                document_analyst_review,
                document_analyst_followup,
            ),
            can_submit_bank_review=_can_submit_bank_review(reconciliation_context),
            can_mark_bank_handoff_ready=_can_mark_bank_handoff_ready(
                bank_reconciliation_review,
                banking_handoff_ready,
                banking_handoff_resolution,
            ),
            can_resolve_bank_handoff=_can_resolve_bank_handoff(
                banking_handoff_ready,
                banking_handoff_resolution,
            ),
            can_complete_bank_clarification=_can_complete_bank_clarification(
                banking_handoff_resolution,
                bank_clarification,
            ),
            can_complete_external_banking_process=_can_complete_external_banking_process(
                outside_agent_banking_process,
                external_banking_process_resolution,
            ),
            can_submit_accounting_review=_can_submit_accounting_review(accounting_analysis, accounting_operator_review),
            can_complete_accounting_clarification=_can_complete_accounting_clarification(accounting_manual_handoff_resolution, accounting_clarification_completion),
            can_resolve_external_accounting_process=_can_resolve_external_accounting_process(outside_agent_accounting_process, external_accounting_process_resolution),
            can_complete_external_return_clarification=_can_complete_external_return_clarification(external_accounting_process_resolution, external_return_clarification_completion),
            approval_next_step=approval_next_step,
            message=request.query_params.get('msg'),
        ),
    )


@router.get('/open-items', response_class=HTMLResponse)
async def ui_open_items(
    request: Request,
    status: str = Query(default='ALL'),
    priority: str = Query(default='ALL'),
    open_items_service: OpenItemsService = Depends(get_open_items_service),
) -> HTMLResponse:
    all_items = await open_items_service.list_items()

    rows: list[dict[str, Any]] = []
    for item in all_items:
        p = _priority_of(item)
        rows.append({'item': item, 'priority': p})

    status_counts = Counter(r['item'].status for r in rows)
    priority_counts = Counter(r['priority'] for r in rows)

    status_norm = status.upper()
    priority_norm = priority.upper()

    filtered = rows
    if status_norm != 'ALL':
        filtered = [r for r in filtered if r['item'].status == status_norm]
    if priority_norm != 'ALL':
        filtered = [r for r in filtered if r['priority'] == priority_norm]

    return TEMPLATES.TemplateResponse(
        request,
        'open_items.html',
        _ctx(
            request,
            title='Open Items',
            rows=filtered,
            selected_status=status_norm,
            selected_priority=priority_norm,
            statuses=['ALL', 'OPEN', 'WAITING_USER', 'WAITING_DATA', 'SCHEDULED', 'COMPLETED', 'CANCELLED'],
            priorities=['ALL', 'HIGH', 'MEDIUM', 'LOW', 'UNSET'],
            priority_note='Priority wird in V1 transparent aus due_at abgeleitet (HIGH/MEDIUM/LOW/UNSET).',
            status_counts=dict(status_counts),
            priority_counts=dict(priority_counts),
            total_count=len(rows),
            filtered_count=len(filtered),
        ),
    )


@router.get('/problem-cases', response_class=HTMLResponse)
async def ui_problem_cases(
    request: Request,
    type: str = Query(default='ALL'),
    risk: str = Query(default='ALL'),
    status: str = Query(default='ALL'),
    service: ProblemCaseService = Depends(get_problem_case_service),
) -> HTMLResponse:
    problems = await service.recent(limit=500)

    type_norm = type
    risk_norm = risk.upper()
    status_norm = status.upper()

    rows: list[dict[str, Any]] = []
    for p in problems:
        row_status = 'OPEN'
        row_type = p.exception_type or 'UNSET'
        row_risk = (p.severity or 'UNKNOWN').upper()
        rows.append({'problem': p, 'type': row_type, 'risk': row_risk, 'status': row_status})

    filtered = rows
    if type_norm != 'ALL':
        filtered = [r for r in filtered if r['type'] == type_norm]
    if risk_norm != 'ALL':
        filtered = [r for r in filtered if r['risk'] == risk_norm]
    if status_norm != 'ALL':
        filtered = [r for r in filtered if r['status'] == status_norm]

    type_options = sorted({'ALL', *[r['type'] for r in rows]})
    risk_options = sorted({'ALL', *[r['risk'] for r in rows]})

    return TEMPLATES.TemplateResponse(
        request,
        'problem_cases.html',
        _ctx(
            request,
            title='Problem Cases',
            rows=filtered,
            selected_type=type_norm,
            selected_risk=risk_norm,
            selected_status=status_norm,
            type_options=type_options,
            risk_options=risk_options,
            status_options=['ALL', 'OPEN'],
            status_note='Problem-Case-Status-Lifecycle ist aktuell noch nicht als separates Backend-Modell implementiert; V1 zeigt transparent OPEN.',
        ),
    )


@router.get('/rules', response_class=HTMLResponse)
async def ui_rules(
    request: Request,
    loader: RuleLoader = Depends(get_rule_loader),
) -> HTMLResponse:
    status_items = loader.load_status()
    return TEMPLATES.TemplateResponse(
        request,
        'rules_list.html',
        _ctx(request, title='Rules', status_items=status_items),
    )


@router.get('/rules/audit', response_class=HTMLResponse)
async def ui_rules_audit(
    request: Request,
    rule_change_service: RuleChangeAuditService = Depends(get_rule_change_audit_service),
) -> HTMLResponse:
    changes = await rule_change_service.recent(limit=300)
    return TEMPLATES.TemplateResponse(
        request,
        'rules_audit.html',
        _ctx(request, title='Rules Audit', changes=changes),
    )


@router.get('/rules/{file_name:path}', response_class=HTMLResponse)
async def ui_rule_detail(
    request: Request,
    file_name: str,
    loader: RuleLoader = Depends(get_rule_loader),
    approval_service: ApprovalService = Depends(get_approval_service),
) -> HTMLResponse:
    document = loader.load_rule_document(file_name)
    if not document['loaded']:
        raise HTTPException(status_code=404, detail='Regeldatei nicht gefunden oder nicht ladbar')

    msg = request.query_params.get('msg')
    approval_id = request.query_params.get('approval_id')
    approval_record = await approval_service.get(approval_id) if approval_id else None
    return TEMPLATES.TemplateResponse(
        request,
        'rule_detail.html',
        _ctx(
            request,
            title=f'Rule {file_name}',
            doc=document,
            message=msg,
            approval_id=approval_id,
            approval_record=approval_record,
            approval_next_step=approval_next_step,
        ),
    )


@router.post('/rules/{file_name:path}', dependencies=[Depends(require_csrf)])
async def ui_rule_update(
    request: Request,
    file_name: str,
    content: str = Form(...),
    reason: str = Form(...),
    approval_id: str | None = Form(default=None),
    loader: RuleLoader = Depends(get_rule_loader),
    policy_access: PolicyAccessLayer = Depends(get_policy_access_layer),
    approval_service: ApprovalService = Depends(get_approval_service),
    audit_service: AuditService = Depends(get_audit_service),
    rule_change_service: RuleChangeAuditService = Depends(get_rule_change_audit_service),
    current_user: AuthUser = Depends(require_admin),
) -> RedirectResponse:
    gate = policy_access.evaluate_gate(
        intent='WORKFLOW_TRIGGER',
        action_name='rule_policy_edit',
        context={'side_effect': True, 'confidence': 1.0},
    )
    case_id = f'rule:{file_name}'
    approved_record = await approval_service.get(approval_id) if approval_id else None
    approved_for_write = bool(
        approved_record
        and approved_record.status == 'APPROVED'
        and approved_record.case_id == case_id
        and approved_record.action_type == gate.action_key
        and approved_record.scope_ref == file_name
    )
    if not approved_for_write:
        approval = await approval_service.request_approval(
            case_id=case_id,
            action_type=gate.action_key,
            requested_by=current_user.username,
            scope_ref=file_name,
            reason=reason,
            policy_refs=gate.consulted_policy_refs,
            required_mode=gate.decision_mode,
            approval_context={'file_name': file_name, 'reason': reason},
            source='ui_rules',
        )
        return RedirectResponse(
            url=(
                f'/ui/rules/{file_name}?msg={quote("Freigabe erforderlich vor Rule-Update.")}'
                f'&approval_id={approval.approval_id}'
            ),
            status_code=HTTP_303_SEE_OTHER,
        )

    old_doc = loader.load_rule_document(file_name)
    old_content = old_doc['content'] if old_doc['loaded'] and old_doc['content'] is not None else ''
    old_version = old_doc.get('version') if old_doc['loaded'] else None

    loader.save_rule_file(file_name, content)
    new_doc = loader.load_rule_document(file_name)
    if not new_doc['loaded']:
        raise HTTPException(status_code=400, detail=f"Datei konnte nicht geladen werden: {new_doc.get('error')}")

    change_record = await rule_change_service.record_change(
        file_name=file_name,
        old_content=old_content,
        new_content=new_doc['content'] or '',
        changed_by=current_user.username,
        reason=reason,
        old_version=old_version,
        new_version=new_doc.get('version'),
    )

    await audit_service.log_event(
        {
            'event_id': str(uuid.uuid4()),
            'case_id': f'rule:{file_name}',
            'source': 'ui_rules',
            'agent_name': 'frya-policy-layer',
            'approval_status': 'APPROVED',
            'action': 'RULE_FILE_UPDATED_UI',
            'result': f'{file_name} updated by {current_user.username};approval_id={approved_record.approval_id}',
            'llm_input': {'old_version': old_version, 'new_version': new_doc.get('version'), 'approval_id': approved_record.approval_id},
            'llm_output': {'reason': reason, 'change_id': change_record.change_id, 'required_mode': gate.decision_mode},
            'policy_refs': gate.consulted_policy_refs,
        }
    )

    return RedirectResponse(
        url=f'/ui/rules/{file_name}?msg=Gespeichert&approval_id={approved_record.approval_id}',
        status_code=HTTP_303_SEE_OTHER,
    )


@router.get('/verfahrensdoku', response_class=HTMLResponse)
async def ui_verfahrensdoku(
    request: Request,
    file_store: FileStore = Depends(get_file_store),
) -> HTMLResponse:
    files = file_store.list_files('verfahrensdoku')
    return TEMPLATES.TemplateResponse(
        request,
        'verfahrensdoku.html',
        _ctx(request, title='Verfahrensdokumentation', files=files),
    )


@router.get('/system', response_class=HTMLResponse)
async def ui_system(
    request: Request,
    loader: RuleLoader = Depends(get_rule_loader),
    policy_access: PolicyAccessLayer = Depends(get_policy_access_layer),
) -> HTMLResponse:
    settings = get_settings()
    status = loader.load_status()
    entries = loader.list_rule_entries()
    required_ok, required_missing = policy_access.required_policies_loaded()

    connectors = [
        {'name': 'paperless', 'base_url': settings.paperless_base_url, 'configured': bool(settings.paperless_base_url)},
        {'name': 'akaunting', 'base_url': settings.akaunting_base_url, 'configured': bool(settings.akaunting_base_url)},
        {'name': 'n8n', 'base_url': settings.n8n_base_url, 'configured': bool(settings.n8n_base_url)},
    ]

    models = {
        'litellm_model': settings.llm_model,
        'openai_key_configured': bool(settings.openai_api_key),
        'anthropic_key_configured': bool(settings.anthropic_api_key),
    }

    feature_state = {
        'required_policy_roles': list(REQUIRED_POLICY_ROLES),
        'required_policies_loaded': required_ok,
        'missing_required_roles': required_missing,
        'explicit_feature_toggles_model': 'not_implemented_yet',
    }

    return TEMPLATES.TemplateResponse(
        request,
        'system.html',
        _ctx(
            request,
            title='System',
            connectors=connectors,
            rule_registry_entries=entries,
            rule_load_status=status,
            models=models,
            feature_state=feature_state,
        ),
    )


@router.get('/email-intake', response_class=HTMLResponse)
async def email_intake_list(request: Request):
    repo = get_email_intake_repository()
    intakes = await repo.list_recent(limit=50)
    csrf_token = get_csrf_token(request)
    return TEMPLATES.TemplateResponse(
        request,
        'email_intake_list.html',
        {
            'request': request,
            'auth_user': getattr(request.state, 'auth_user', None),
            'csrf_token': csrf_token,
            'intakes': [i.model_dump(mode='json') for i in intakes],
            'title': 'E-Mail-Eingänge',
        },
    )


@router.get('/email-intake/{email_intake_id}', response_class=HTMLResponse)
async def email_intake_detail(request: Request, email_intake_id: str):
    repo = get_email_intake_repository()
    intake = await repo.get_by_id(email_intake_id)
    if intake is None:
        raise HTTPException(status_code=404, detail='Nicht gefunden.')
    attachments = await repo.get_attachments(email_intake_id)
    csrf_token = get_csrf_token(request)
    return TEMPLATES.TemplateResponse(
        request,
        'email_intake_detail.html',
        {
            'request': request,
            'auth_user': getattr(request.state, 'auth_user', None),
            'csrf_token': csrf_token,
            'intake': intake.model_dump(mode='json'),
            'attachments': [a.model_dump(mode='json') for a in attachments],
            'title': f'E-Mail {email_intake_id}',
        },
    )


# ── CaseEngine UI (/ui/vorgaenge) ─────────────────────────────────────────────

_ALL_CASE_TYPES: list[str] = [
    'incoming_invoice', 'outgoing_invoice', 'contract', 'notice',
    'tax_document', 'correspondence', 'receipt', 'bank_statement',
    'dunning', 'insurance', 'salary', 'other',
]
_ALL_CASE_STATUSES: list[str] = ['DRAFT', 'OPEN', 'OVERDUE', 'PAID', 'CLOSED', 'DISCARDED', 'MERGED']


@router.get('/vorgaenge', response_class=HTMLResponse)
async def vorgaenge_list(
    request: Request,
    tenant_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    case_type: str | None = Query(default=None),
    q: str | None = Query(default=None),
):
    repo = get_case_repository()
    rows: list[dict] = []

    if tenant_id:
        try:
            tid = uuid.UUID(tenant_id)
        except ValueError:
            tid = None
        if tid:
            cases = await repo.list_cases(
                tid,
                status=status or None,
                offset=0,
                limit=200,
            )
            if q:
                q_lower = q.lower()
                cases = [
                    c for c in cases
                    if q_lower in (c.vendor_name or '').lower()
                    or q_lower in (c.case_number or '').lower()
                ]
            if case_type:
                cases = [c for c in cases if c.case_type == case_type]

            for c in cases:
                docs = await repo.get_case_documents(c.id)
                conflicts = await repo.get_conflicts(c.id)
                rows.append({
                    'case': c.model_dump(mode='json'),
                    'doc_count': len(docs),
                    'conflict_count': len(conflicts),
                })

    return TEMPLATES.TemplateResponse(
        request,
        'vorgaenge_list.html',
        _ctx(
            request,
            title='Vorgaenge',
            rows=rows,
            tenant_id=tenant_id or '',
            all_statuses=_ALL_CASE_STATUSES,
            all_types=_ALL_CASE_TYPES,
            selected_status=status or '',
            selected_type=case_type or '',
            query=q or '',
        ),
    )


@router.post('/vorgaenge', response_class=HTMLResponse)
async def vorgaenge_create(
    request: Request,
    _csrf: None = Depends(require_csrf),
    tenant_id: str = Form(...),
    case_type: str = Form(...),
    title: str | None = Form(default=None),
    vendor_name: str | None = Form(default=None),
    total_amount: str | None = Form(default=None),
    due_date: str | None = Form(default=None),
):
    from decimal import Decimal
    from datetime import date as _date
    repo = get_case_repository()
    tid = uuid.UUID(tenant_id)
    amount = Decimal(total_amount) if total_amount else None
    due = _date.fromisoformat(due_date) if due_date else None

    case = await repo.create_case(
        tenant_id=tid,
        case_type=case_type,
        title=title or None,
        vendor_name=vendor_name or None,
        total_amount=amount,
        due_date=due,
    )
    return RedirectResponse(
        url=f'/ui/vorgaenge/{case.id}?tenant_id={tenant_id}',
        status_code=HTTP_303_SEE_OTHER,
    )


@router.get('/vorgaenge/{case_id}', response_class=HTMLResponse)
async def vorgang_detail(
    request: Request,
    case_id: str,
    tenant_id: str | None = Query(default=None),
    msg: str | None = Query(default=None),
):
    repo = get_case_repository()
    settings = get_settings()
    try:
        cid = uuid.UUID(case_id)
    except ValueError:
        raise HTTPException(status_code=404, detail='Ungueltige Vorgang-ID.')
    case = await repo.get_case(cid)
    if case is None:
        raise HTTPException(status_code=404, detail='Vorgang nicht gefunden.')

    docs = await repo.get_case_documents(cid)
    refs = await repo.get_case_references(cid)
    conflicts = await repo.get_conflicts(cid)

    allowed_next = sorted(allowed_transitions(case.status))

    timeline: list[dict] = []
    if case.created_at:
        timeline.append({
            'ts': case.created_at.isoformat(),
            'label': 'Vorgang erstellt',
            'detail': f'Status: {case.status}',
        })
    for doc in sorted(docs, key=lambda d: d.assigned_at or datetime.min):
        timeline.append({
            'ts': doc.assigned_at.isoformat() if doc.assigned_at else None,
            'label': f'Dokument zugeordnet ({doc.document_source})',
            'detail': doc.filename or doc.document_source_id,
        })

    return TEMPLATES.TemplateResponse(
        request,
        'vorgang_detail.html',
        _ctx(
            request,
            title=f'Vorgang {case.case_number or case_id[:8]}',
            case_data=case.model_dump(mode='json'),
            documents=[d.model_dump(mode='json') for d in docs],
            references=[r.model_dump(mode='json') for r in refs],
            conflicts=[c.model_dump(mode='json') for c in conflicts],
            allowed_next=allowed_next,
            timeline=timeline,
            tenant_id=tenant_id or '',
            paperless_url=settings.paperless_base_url.rstrip('/') if settings.paperless_base_url else '',
            msg=msg or '',
        ),
    )


@router.post('/vorgaenge/{case_id}/status', response_class=HTMLResponse)
async def vorgang_update_status(
    request: Request,
    case_id: str,
    _csrf: None = Depends(require_csrf),
    new_status: str = Form(...),
    tenant_id: str = Form(default=''),
):
    repo = get_case_repository()
    cid = uuid.UUID(case_id)
    try:
        await repo.update_case_status(cid, new_status, operator=True)
    except (StatusTransitionError, ValueError) as exc:
        msg = str(exc)
        return RedirectResponse(
            url=f'/ui/vorgaenge/{case_id}?tenant_id={tenant_id}&msg={quote(msg, safe="")}',
            status_code=HTTP_303_SEE_OTHER,
        )
    return RedirectResponse(
        url=f'/ui/vorgaenge/{case_id}?tenant_id={tenant_id}',
        status_code=HTTP_303_SEE_OTHER,
    )


@router.post('/vorgaenge/{case_id}/document', response_class=HTMLResponse)
async def vorgang_add_document(
    request: Request,
    case_id: str,
    _csrf: None = Depends(require_csrf),
    document_source: str = Form(...),
    document_source_id: str = Form(...),
    filename: str | None = Form(default=None),
    tenant_id: str = Form(default=''),
):
    repo = get_case_repository()
    cid = uuid.UUID(case_id)
    operator_name = getattr(getattr(request.state, 'auth_user', None), 'username', 'operator')
    await repo.add_document_to_case(
        case_id=cid,
        document_source=document_source,
        document_source_id=document_source_id,
        assignment_confidence='MEDIUM',
        assignment_method='manual',
        filename=filename or None,
        assigned_by=operator_name,
    )
    return RedirectResponse(
        url=f'/ui/vorgaenge/{case_id}?tenant_id={tenant_id}',
        status_code=HTTP_303_SEE_OTHER,
    )


@router.post('/vorgaenge/{case_id}/reference', response_class=HTMLResponse)
async def vorgang_add_reference(
    request: Request,
    case_id: str,
    _csrf: None = Depends(require_csrf),
    reference_type: str = Form(...),
    reference_value: str = Form(...),
    tenant_id: str = Form(default=''),
):
    repo = get_case_repository()
    cid = uuid.UUID(case_id)
    await repo.add_reference(
        case_id=cid,
        reference_type=reference_type,
        reference_value=reference_value,
    )
    return RedirectResponse(
        url=f'/ui/vorgaenge/{case_id}?tenant_id={tenant_id}',
        status_code=HTTP_303_SEE_OTHER,
    )


@router.post('/vorgaenge/{case_id}/conflict/{conflict_id}/resolve', response_class=HTMLResponse)
async def vorgang_resolve_conflict(
    request: Request,
    case_id: str,
    conflict_id: str,
    _csrf: None = Depends(require_csrf),
    resolution: str = Form(...),
    tenant_id: str = Form(default=''),
):
    repo = get_case_repository()
    cfid = uuid.UUID(conflict_id)
    resolved_by = getattr(getattr(request.state, 'auth_user', None), 'username', 'operator')
    await repo.resolve_conflict(cfid, resolution, resolved_by=resolved_by)
    return RedirectResponse(
        url=f'/ui/vorgaenge/{case_id}?tenant_id={tenant_id}',
        status_code=HTTP_303_SEE_OTHER,
    )


@router.post('/vorgaenge/{case_id}/merge', response_class=HTMLResponse)
async def vorgang_merge(
    request: Request,
    case_id: str,
    _csrf: None = Depends(require_csrf),
    target_case_id: str = Form(...),
    tenant_id: str = Form(default=''),
):
    repo = get_case_repository()
    cid = uuid.UUID(case_id)
    tid = uuid.UUID(target_case_id)
    try:
        await repo.merge_cases(cid, tid, operator=True)
    except (StatusTransitionError, ValueError) as exc:
        msg = str(exc)
        return RedirectResponse(
            url=f'/ui/vorgaenge/{case_id}?tenant_id={tenant_id}&msg={quote(msg, safe="")}',
            status_code=HTTP_303_SEE_OTHER,
        )
    return RedirectResponse(
        url=f'/ui/vorgaenge/{target_case_id}?tenant_id={tenant_id}',
        status_code=HTTP_303_SEE_OTHER,
    )


@router.post('/vorgaenge/{case_id}/analyze-booking', response_class=HTMLResponse)
async def vorgang_analyze_booking(
    request: Request,
    case_id: str,
    _csrf: None = Depends(require_csrf),
    tenant_id: str = Form(default=''),
):
    from app.accounting_analyst.schemas import CaseAnalysisInput
    from app.accounting_analyst.service import build_accounting_analyst_service

    repo = get_case_repository()
    cid = uuid.UUID(case_id)
    case = await repo.get_case(cid)
    if case is None:
        raise HTTPException(status_code=404, detail='Vorgang nicht gefunden.')

    llm_repo = get_llm_config_repository()
    config = await llm_repo.get_config('accounting_analyst')
    svc = build_accounting_analyst_service(llm_repo, config)

    doc_type: str | None = None
    if isinstance(case.metadata.get('document_analysis'), dict):
        doc_type = case.metadata['document_analysis'].get('document_type')

    case_input = CaseAnalysisInput(
        case_id=str(case.id),
        case_type=case.case_type,
        vendor_name=case.vendor_name,
        total_amount=case.total_amount,
        currency=case.currency,
        due_date=case.due_date,
        title=case.title,
        document_type=doc_type,
        metadata=case.metadata,
    )
    proposal = await svc.analyze(case_input)
    await repo.update_metadata(cid, {'booking_proposal': proposal.model_dump(mode='json')})
    return RedirectResponse(
        url=f'/ui/vorgaenge/{case_id}?tenant_id={tenant_id}',
        status_code=HTTP_303_SEE_OTHER,
    )


@router.post('/vorgaenge/{case_id}/booking-proposal/confirm', response_class=HTMLResponse)
async def vorgang_confirm_booking(
    request: Request,
    case_id: str,
    _csrf: None = Depends(require_csrf),
    tenant_id: str = Form(default=''),
):
    await _vorgang_set_proposal_status(case_id, 'CONFIRMED')
    return RedirectResponse(
        url=f'/ui/vorgaenge/{case_id}?tenant_id={tenant_id}',
        status_code=HTTP_303_SEE_OTHER,
    )


@router.post('/vorgaenge/{case_id}/booking-proposal/reject', response_class=HTMLResponse)
async def vorgang_reject_booking(
    request: Request,
    case_id: str,
    _csrf: None = Depends(require_csrf),
    tenant_id: str = Form(default=''),
):
    await _vorgang_set_proposal_status(case_id, 'REJECTED')
    return RedirectResponse(
        url=f'/ui/vorgaenge/{case_id}?tenant_id={tenant_id}',
        status_code=HTTP_303_SEE_OTHER,
    )


async def _vorgang_set_proposal_status(case_id: str, status: str) -> None:
    repo = get_case_repository()
    cid = uuid.UUID(case_id)
    case = await repo.get_case(cid)
    if case is None:
        raise HTTPException(status_code=404, detail='Vorgang nicht gefunden.')
    proposal = case.metadata.get('booking_proposal')
    if not proposal:
        raise HTTPException(status_code=404, detail='Kein Buchungsvorschlag vorhanden.')
    proposal['status'] = status
    await repo.update_metadata(cid, {'booking_proposal': proposal})


@router.post('/vorgaenge/{case_id}/risk-check', response_class=HTMLResponse)
async def vorgang_risk_check(
    request: Request,
    case_id: str,
    _csrf: None = Depends(require_csrf),
    tenant_id: str = Form(default=''),
):
    from app.risk_analyst.service import build_risk_analyst_service

    repo = get_case_repository()
    cid = uuid.UUID(case_id)
    case = await repo.get_case(cid)
    if case is None:
        raise HTTPException(status_code=404, detail='Vorgang nicht gefunden.')

    llm_repo = get_llm_config_repository()
    config = await llm_repo.get_config('risk_consistency')
    svc = build_risk_analyst_service(repo, llm_repo, config)
    await svc.analyze_case(cid)
    return RedirectResponse(
        url=f'/ui/vorgaenge/{case_id}?tenant_id={tenant_id}',
        status_code=HTTP_303_SEE_OTHER,
    )


# ── Fristen-Dashboard ─────────────────────────────────────────────────────────

@router.get('/fristen', response_class=HTMLResponse)
async def fristen_dashboard(
    request: Request,
    tenant_id: str | None = Query(default=None),
    msg: str | None = Query(default=None),
):
    from app.deadline_analyst.service import build_deadline_analyst_service
    settings = get_settings()
    tid_str = tenant_id or settings.default_tenant_id or ''

    empty_report = {
        'tenant_id': tid_str,
        'checked_at': '',
        'total_cases_checked': 0,
        'overdue': [],
        'due_today': [],
        'due_soon': [],
        'skonto_expiring': [],
        'summary_text': '',
        'total_overdue_amount': None,
        'analyst_version': 'deadline-analyst-v1',
    }

    if not tid_str:
        return TEMPLATES.TemplateResponse(
            request,
            'fristen.html',
            _ctx(request, title='Fristen', report=empty_report, tenant_id='', msg=msg or ''),
        )

    try:
        tid = uuid.UUID(tid_str)
    except ValueError:
        raise HTTPException(status_code=400, detail='Ungueltige Tenant-ID.')

    repo = get_case_repository()
    llm_repo = get_llm_config_repository()
    config = await llm_repo.get_config('deadline_analyst')
    svc = build_deadline_analyst_service(repo, llm_repo, config)
    report = await svc.check_all_deadlines(tid)

    return TEMPLATES.TemplateResponse(
        request,
        'fristen.html',
        _ctx(
            request,
            title='Fristen-Dashboard',
            report=report.model_dump(mode='json'),
            tenant_id=tid_str,
            msg=msg or '',
        ),
    )


@router.post('/fristen/check-now', response_class=HTMLResponse)
async def fristen_check_now(
    request: Request,
    _csrf: None = Depends(require_csrf),
    tenant_id: str = Form(default=''),
):
    from app.deadline_analyst.service import build_deadline_analyst_service
    if not tenant_id:
        return RedirectResponse(url='/ui/fristen', status_code=HTTP_303_SEE_OTHER)

    try:
        tid = uuid.UUID(tenant_id)
    except ValueError:
        return RedirectResponse(url='/ui/fristen', status_code=HTTP_303_SEE_OTHER)

    repo = get_case_repository()
    llm_repo = get_llm_config_repository()
    config = await llm_repo.get_config('deadline_analyst')
    svc = build_deadline_analyst_service(repo, llm_repo, config)
    await svc.check_all_deadlines(tid)

    return RedirectResponse(
        url=f'/ui/fristen?tenant_id={tenant_id}',
        status_code=HTTP_303_SEE_OTHER,
    )


# ── API-Keys overview ─────────────────────────────────────────────────────────

def _mask(value: str | None) -> str | None:
    """Return ****last4 for non-empty values, None otherwise."""
    if not value:
        return None
    if len(value) <= 4:
        return '****'
    return f'****{value[-4:]}'


@router.get('/api-keys', response_class=HTMLResponse)
async def api_keys_page(
    request: Request,
    auth_user: AuthUser = Depends(require_admin),
):
    settings = get_settings()
    repo = get_llm_config_repository()

    # Collect active-agent API keys from DB
    all_configs = await repo.get_all_configs()
    active_agents_with_key = [
        c for c in all_configs
        if c.get('agent_status', 'active') == 'active' and c.get('api_key_encrypted')
    ]
    ionos_set_count = len(active_agents_with_key)
    ionos_active_count = sum(
        1 for c in all_configs if c.get('agent_status', 'active') == 'active'
    )
    ionos_masked = (
        f'{ionos_set_count}/{ionos_active_count} Agenten'
        if ionos_set_count > 0
        else None
    )

    api_keys = [
        {
            'service': 'IONOS AI Hub',
            'sub_label': 'Active agents',
            'variable': 'DB: frya_agent_llm_config.api_key_encrypted',
            'masked': ionos_masked,
            'is_set': ionos_set_count > 0,
            'source': 'db',
            'edit_url': '/agent-config',
            'tooltip': 'IONOS Cloud Console \u2192 AI Model Hub \u2192 API Keys',
        },
        {
            'service': 'Brevo',
            'sub_label': None,
            'variable': 'FRYA_BREVO_API_KEY',
            'masked': _mask(settings.brevo_api_key),
            'is_set': bool(settings.brevo_api_key),
            'source': 'env',
            'edit_url': None,
            'tooltip': 'brevo.com \u2192 Settings \u2192 SMTP & API \u2192 API Keys',
        },
        {
            'service': 'Telegram Bot',
            'sub_label': None,
            'variable': 'FRYA_TELEGRAM_BOT_TOKEN',
            'masked': _mask(settings.telegram_bot_token),
            'is_set': bool(settings.telegram_bot_token),
            'source': 'env',
            'edit_url': None,
            'tooltip': 't.me/BotFather \u2192 /mybots \u2192 API Token',
        },
        {
            'service': 'Hetzner S3',
            'sub_label': 'Access Key',
            'variable': 'FRYA_S3_ACCESS_KEY',
            'masked': _mask(os.environ.get('FRYA_S3_ACCESS_KEY')),
            'is_set': bool(os.environ.get('FRYA_S3_ACCESS_KEY')),
            'source': 'env',
            'edit_url': None,
            'tooltip': 'Hetzner Console \u2192 Object Storage \u2192 S3 Credentials',
        },
        {
            'service': 'Hetzner S3',
            'sub_label': 'Secret Key',
            'variable': 'FRYA_S3_SECRET_KEY',
            'masked': _mask(os.environ.get('FRYA_S3_SECRET_KEY')),
            'is_set': bool(os.environ.get('FRYA_S3_SECRET_KEY')),
            'source': 'env',
            'edit_url': None,
            'tooltip': 'Hetzner Console \u2192 Object Storage \u2192 S3 Credentials',
        },
        {
            'service': 'Paperless',
            'sub_label': None,
            'variable': 'FRYA_PAPERLESS_TOKEN',
            'masked': _mask(settings.paperless_token),
            'is_set': bool(settings.paperless_token),
            'source': 'env',
            'edit_url': None,
            'tooltip': 'Paperless Admin \u2192 API Token',
        },
        {
            'service': 'OpenAI (Fallback)',
            'sub_label': None,
            'variable': 'FRYA_OPENAI_API_KEY',
            'masked': _mask(settings.openai_api_key),
            'is_set': bool(settings.openai_api_key),
            'source': 'env',
            'edit_url': None,
            'tooltip': 'platform.openai.com \u2192 API Keys',
        },
        {
            'service': 'n8n',
            'sub_label': None,
            'variable': 'FRYA_N8N_TOKEN',
            'masked': _mask(settings.n8n_token),
            'is_set': bool(settings.n8n_token),
            'source': 'env',
            'edit_url': None,
            'tooltip': 'n8n Settings \u2192 API \u2192 Create API Key',
        },
        {
            'service': 'age Backup',
            'sub_label': None,
            'variable': 'FRYA_AGE_PUBLIC_KEY',
            'masked': _mask(os.environ.get('FRYA_AGE_PUBLIC_KEY')),
            'is_set': bool(os.environ.get('FRYA_AGE_PUBLIC_KEY')),
            'source': 'env',
            'edit_url': None,
            'tooltip': 'Terminal: age-keygen \u2192 Public Key (age1...)',
        },
    ]

    return TEMPLATES.TemplateResponse(
        request,
        'api_keys.html',
        {**_ctx(request, auth_user=auth_user), 'title': 'API-Keys', 'api_keys': api_keys},
    )



