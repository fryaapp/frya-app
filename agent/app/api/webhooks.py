from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request

from app.approvals.service import ApprovalService
from app.audit.service import AuditService
from app.config import get_settings
from app.connectors.contracts import NotificationMessage
from app.connectors.notifications_telegram import TelegramConnector
from app.dependencies import (
    get_approval_service,
    get_audit_service,
    get_open_items_service,
    get_policy_access_layer,
    get_problem_case_service,
    get_telegram_connector,
    get_telegram_deduplicator,
)
from app.open_items.service import OpenItemsService
from app.problems.service import ProblemCaseService
from app.schemas.events import TelegramIncomingEvent
from app.telegram.dedup import TelegramUpdateDeduplicator
from app.telegram.intent_v1 import TelegramIntent, detect_intent

router = APIRouter(prefix='/webhooks', tags=['webhooks'])


TELEGRAM_V1_INTENTS: tuple[str, ...] = (
    'status.overview',
    'open_items.list',
    'problem_cases.list',
    'case.show',
    'approval.respond',
    'help.basic',
)


def _extract_telegram_message(payload: dict) -> tuple[str | None, dict | None]:
    for key in ('message', 'edited_message', 'channel_post', 'edited_channel_post'):
        candidate = payload.get(key)
        if isinstance(candidate, dict):
            return key, candidate
    return None, None


def _normalize_telegram_update(payload: dict) -> TelegramIncomingEvent | None:
    raw_type, message = _extract_telegram_message(payload)
    if message is None:
        return None

    chat = message.get('chat') or {}
    chat_id = chat.get('id')
    if chat_id is None:
        return None

    text = message.get('text') or message.get('caption') or ''
    if not isinstance(text, str) or not text.strip():
        return None

    sender = message.get('from') or {}
    sender_id = sender.get('id')

    return TelegramIncomingEvent(
        event_id=str(uuid.uuid4()),
        source='telegram',
        update_id=payload.get('update_id'),
        raw_type=raw_type or 'message',
        message_id=message.get('message_id'),
        chat_id=str(chat_id),
        chat_type=chat.get('type'),
        sender_id=str(sender_id) if sender_id is not None else None,
        sender_username=sender.get('username'),
        text=text.strip(),
    )


def _split_allowlist(raw: str | None) -> set[str]:
    if not raw:
        return set()
    normalized = raw.replace(';', ',').replace('\n', ',')
    return {token.strip() for token in normalized.split(',') if token.strip()}


def _authorized_for_telegram(event: TelegramIncomingEvent) -> tuple[bool, str]:
    settings = get_settings()

    allowed_group_chats = _split_allowlist(settings.telegram_allowed_chat_ids)
    if settings.telegram_default_chat_id:
        allowed_group_chats.add(settings.telegram_default_chat_id.strip())

    allowed_direct_chats = _split_allowlist(settings.telegram_allowed_direct_chat_ids)
    allowed_chats = allowed_group_chats.union(allowed_direct_chats)
    allowed_users = _split_allowlist(settings.telegram_allowed_user_ids)

    if not allowed_chats:
        return False, 'allowlist_missing'

    if event.chat_id not in allowed_chats:
        if event.chat_type == 'private':
            return False, 'private_chat_not_allowed'
        return False, 'chat_not_allowed'

    if allowed_users:
        if not event.sender_id:
            return False, 'sender_missing'
        if event.sender_id not in allowed_users:
            return False, 'user_not_allowed'

    return True, 'authorized'


def _build_telegram_dedup_key(normalized: TelegramIncomingEvent, payload: dict) -> str:
    return TelegramUpdateDeduplicator.build_key(normalized.update_id, payload)


def _deny_reply() -> str:
    return 'FRYA: Zugriff abgelehnt. Dieser Telegram-Chat ist nicht autorisiert.'


def _help_reply() -> str:
    return (
        'FRYA Telegram V1\n'
        'Kommandos:\n'
        '- status\n'
        '- offene punkte\n'
        '- problemfaelle\n'
        '- zeige fall <case_id>\n'
        '- freigeben <approval_id|case_id>\n'
        '- ablehnen <approval_id|case_id>\n'
        '- hilfe'
    )


async def _handle_status_overview(
    open_items_service: OpenItemsService,
    problem_service: ProblemCaseService,
    approval_service: ApprovalService,
) -> tuple[str, dict]:
    open_items = await open_items_service.list_items()
    problems = await problem_service.recent(limit=10)
    approvals = await approval_service.recent(limit=100)
    pending_approvals = [x for x in approvals if x.status == 'PENDING']

    policy_access = get_policy_access_layer()
    policies_ok, missing = policy_access.required_policies_loaded()

    reply = (
        'FRYA Status\n'
        f'- open_items: {len(open_items)}\n'
        f'- problem_cases: {len(problems)}\n'
        f'- pending_approvals: {len(pending_approvals)}\n'
        f'- policies_loaded: {policies_ok}\n'
        f'- missing_policy_roles: {", ".join(missing) if missing else "-"}'
    )

    return reply, {
        'status': 'OK',
        'intent': 'status.overview',
        'open_items': len(open_items),
        'problem_cases': len(problems),
        'pending_approvals': len(pending_approvals),
        'policies_loaded': policies_ok,
        'missing_policy_roles': missing,
    }


async def _handle_open_items_list(open_items_service: OpenItemsService) -> tuple[str, dict]:
    items = await open_items_service.list_items(status='OPEN')
    top = items[:5]

    if not top:
        return (
            'Open Items: keine offenen Punkte.',
            {'status': 'OK', 'intent': 'open_items.list', 'count': 0},
        )

    lines = ['Open Items (max 5):']
    for item in top:
        lines.append(f'- {item.item_id} | case={item.case_id} | {item.title}')

    return '\n'.join(lines), {
        'status': 'OK',
        'intent': 'open_items.list',
        'count': len(items),
        'shown': len(top),
    }


async def _handle_problem_cases_list(problem_service: ProblemCaseService) -> tuple[str, dict]:
    cases = await problem_service.recent(limit=5)
    if not cases:
        return (
            'Problemfaelle: keine offenen Eintraege.',
            {'status': 'OK', 'intent': 'problem_cases.list', 'count': 0},
        )

    lines = ['Problemfaelle (max 5):']
    for case in cases:
        lines.append(f'- {case.problem_id} | case={case.case_id} | severity={case.severity} | {case.title}')

    return '\n'.join(lines), {
        'status': 'OK',
        'intent': 'problem_cases.list',
        'count': len(cases),
    }


async def _handle_case_show(
    case_id: str | None,
    audit_service: AuditService,
    open_items_service: OpenItemsService,
    problem_service: ProblemCaseService,
    approval_service: ApprovalService,
) -> tuple[str, dict]:
    if not case_id:
        return (
            'Case-ID fehlt. Beispiel: zeige fall <case_id>',
            {'status': 'BLOCKED', 'intent': 'case.show', 'reason': 'case_id_missing'},
        )

    chronology = await audit_service.by_case(case_id, limit=50)
    open_items = await open_items_service.list_by_case(case_id)
    problems = await problem_service.by_case(case_id, limit=20)
    approvals = await approval_service.list_by_case(case_id, limit=20)

    if not chronology and not open_items and not problems and not approvals:
        return (
            f'Case {case_id}: nicht gefunden.',
            {'status': 'NOT_FOUND', 'intent': 'case.show', 'case_id': case_id},
        )

    last_action = chronology[-1].action if chronology else '-'
    last_result = chronology[-1].result if chronology else '-'
    pending = len([a for a in approvals if a.status == 'PENDING'])

    reply = (
        f'Case {case_id}\n'
        f'- chronology_events: {len(chronology)}\n'
        f'- open_items: {len(open_items)}\n'
        f'- problem_cases: {len(problems)}\n'
        f'- pending_approvals: {pending}\n'
        f'- last_action: {last_action}\n'
        f'- last_result: {last_result}'
    )

    return reply, {
        'status': 'OK',
        'intent': 'case.show',
        'case_id': case_id,
        'chronology_events': len(chronology),
        'open_items': len(open_items),
        'problem_cases': len(problems),
        'pending_approvals': pending,
    }


async def _resolve_approval_target(target_ref: str, approval_service: ApprovalService):
    by_id = await approval_service.get(target_ref)
    if by_id is not None:
        return by_id

    by_case = await approval_service.list_by_case(target_ref, limit=50)
    pending = [x for x in by_case if x.status == 'PENDING']
    if pending:
        return pending[0]

    return None


async def _handle_approval_respond(
    intent: TelegramIntent,
    approval_service: ApprovalService,
    sender_marker: str,
) -> tuple[str, dict]:
    if not intent.target_ref or not intent.decision:
        return (
            'Freigabe-Kommando unvollstaendig. Beispiel: freigeben <approval_id|case_id>',
            {'status': 'BLOCKED', 'intent': 'approval.respond', 'reason': 'target_or_decision_missing'},
        )

    record = await _resolve_approval_target(intent.target_ref, approval_service)
    if record is None:
        return (
            f'Keine passende Freigabe gefunden fuer: {intent.target_ref}',
            {
                'status': 'NOT_FOUND',
                'intent': 'approval.respond',
                'target_ref': intent.target_ref,
                'decision': intent.decision,
            },
        )

    if record.status != 'PENDING':
        return (
            f'Freigabe bereits entschieden: {record.approval_id} ({record.status})',
            {
                'status': 'BLOCKED',
                'intent': 'approval.respond',
                'approval_id': record.approval_id,
                'current_status': record.status,
            },
        )

    updated = await approval_service.decide_approval(
        approval_id=record.approval_id,
        decision=intent.decision,
        decided_by=sender_marker,
        reason='telegram_v1_operator_command',
    )

    if updated is None:
        return (
            'Freigabe konnte nicht aktualisiert werden.',
            {'status': 'ERROR', 'intent': 'approval.respond', 'approval_id': record.approval_id},
        )

    return (
        f'Freigabe gesetzt: {updated.approval_id} -> {updated.status} (case={updated.case_id})',
        {
            'status': 'OK',
            'intent': 'approval.respond',
            'approval_id': updated.approval_id,
            'case_id': updated.case_id,
            'new_status': updated.status,
        },
    )


async def _handle_telegram_intent(
    intent: TelegramIntent,
    normalized: TelegramIncomingEvent,
    audit_service: AuditService,
    open_items_service: OpenItemsService,
    problem_service: ProblemCaseService,
    approval_service: ApprovalService,
) -> tuple[str, dict]:
    if intent.name == 'help.basic':
        return _help_reply(), {'status': 'OK', 'intent': intent.name}

    if intent.name == 'status.overview':
        return await _handle_status_overview(open_items_service, problem_service, approval_service)

    if intent.name == 'open_items.list':
        return await _handle_open_items_list(open_items_service)

    if intent.name == 'problem_cases.list':
        return await _handle_problem_cases_list(problem_service)

    if intent.name == 'case.show':
        return await _handle_case_show(intent.case_id, audit_service, open_items_service, problem_service, approval_service)

    if intent.name == 'approval.respond':
        sender_marker = f'telegram:{normalized.sender_id or normalized.chat_id}'
        return await _handle_approval_respond(intent, approval_service, sender_marker)

    return (
        'Unbekannter Befehl. Nutze "hilfe" fuer verfuegbare Telegram-V1-Kommandos.',
        {'status': 'BLOCKED', 'intent': 'unknown', 'reason': 'unsupported_intent'},
    )


@router.post('/paperless/document')
async def paperless_document_webhook(
    payload: dict,
    request: Request,
    audit_service: AuditService = Depends(get_audit_service),
    open_items_service: OpenItemsService = Depends(get_open_items_service),
) -> dict:
    document_id = str(payload.get('document_id', 'unknown'))
    case_id = f'doc-{document_id}'

    await audit_service.log_event(
        {
            'event_id': str(uuid.uuid4()),
            'case_id': case_id,
            'source': 'paperless',
            'document_ref': document_id,
            'agent_name': 'frya-orchestrator',
            'approval_status': 'NOT_REQUIRED',
            'action': 'DOCUMENT_WEBHOOK_RECEIVED',
            'result': 'Document webhook accepted for analysis',
            'llm_input': payload,
        }
    )

    try:
        result = await request.app.state.graph.ainvoke(
            {
                'case_id': case_id,
                'source': 'paperless_webhook',
                'message': str(payload.get('title') or payload.get('original_file_name') or f'document {document_id}'),
                'document_ref': document_id,
                'paperless_metadata': payload,
                'ocr_text': payload.get('content') or payload.get('ocr_text') or payload.get('document_text'),
                'preview_text': payload.get('title') or payload.get('original_file_name'),
            }
        )
    except Exception as exc:
        item = await open_items_service.create_item(
            case_id=case_id,
            title='Dokumentenanalyse fehlgeschlagen',
            description=f'Document Analyst konnte nicht ausgefuehrt werden: {exc}',
            source='paperless_webhook',
            document_ref=document_id,
        )
        problem = await get_problem_case_service().add_case(
            case_id=case_id,
            title='Document analysis failed',
            details=str(exc),
            severity='HIGH',
            exception_type='DOCUMENT_ANALYSIS_FAILED',
            document_ref=document_id,
            created_by='paperless-webhook',
        )
        await audit_service.log_event(
            {
                'event_id': str(uuid.uuid4()),
                'case_id': case_id,
                'source': 'paperless',
                'document_ref': document_id,
                'agent_name': 'frya-orchestrator',
                'approval_status': 'NOT_REQUIRED',
                'action': 'DOCUMENT_ANALYSIS_FAILED',
                'result': str(exc),
                'llm_input': payload,
            }
        )
        return {
            'status': 'error',
            'case_id': case_id,
            'document_id': document_id,
            'open_item_id': item.item_id,
            'problem_id': problem.problem_id,
            'error': str(exc),
        }

    output = result.get('output', {}) if isinstance(result, dict) else {}
    return {
        'status': 'accepted',
        'case_id': case_id,
        'document_id': document_id,
        'analysis_status': output.get('status'),
        'recommended_next_step': output.get('recommended_next_step'),
        'open_item_id': output.get('open_item_id'),
        'problem_id': output.get('problem_id'),
        'result': output,
    }


@router.post('/telegram')
async def telegram_webhook(
    payload: dict,
    audit_service: AuditService = Depends(get_audit_service),
    telegram_connector: TelegramConnector = Depends(get_telegram_connector),
    deduplicator: TelegramUpdateDeduplicator = Depends(get_telegram_deduplicator),
    open_items_service: OpenItemsService = Depends(get_open_items_service),
    problem_service: ProblemCaseService = Depends(get_problem_case_service),
    approval_service: ApprovalService = Depends(get_approval_service),
) -> dict:
    normalized = _normalize_telegram_update(payload)
    if normalized is None:
        ignored_case = f"tg-ignored-{payload.get('update_id', uuid.uuid4())}"
        await audit_service.log_event(
            {
                'event_id': str(uuid.uuid4()),
                'case_id': ignored_case,
                'source': 'telegram',
                'agent_name': 'frya-orchestrator',
                'approval_status': 'NOT_REQUIRED',
                'action': 'TELEGRAM_WEBHOOK_IGNORED',
                'result': 'Unsupported update type or empty text',
                'llm_input': payload,
            }
        )
        return {'status': 'ignored', 'reason': 'unsupported_or_empty_message'}
    message_key = normalized.message_id or normalized.update_id or str(uuid.uuid4())
    case_id = f'tg-{normalized.chat_id}-{message_key}'

    await audit_service.log_event(
        {
            'event_id': str(uuid.uuid4()),
            'case_id': case_id,
            'source': 'telegram',
            'agent_name': 'frya-orchestrator',
            'approval_status': 'NOT_REQUIRED',
            'action': 'TELEGRAM_WEBHOOK_RECEIVED',
            'result': 'Message accepted for processing',
            'llm_input': {
                'raw_update': payload,
                'chat_id': normalized.chat_id,
                'sender_id': normalized.sender_id,
                'message_id': normalized.message_id,
                'text': normalized.text,
            },
        }
    )

    dedup_key = _build_telegram_dedup_key(normalized, payload)
    is_first_seen = await deduplicator.acquire(dedup_key)
    if not is_first_seen:
        await audit_service.log_event(
            {
                'event_id': str(uuid.uuid4()),
                'case_id': case_id,
                'source': 'telegram',
                'agent_name': 'frya-orchestrator',
                'approval_status': 'NOT_REQUIRED',
                'action': 'TELEGRAM_DUPLICATE_IGNORED',
                'result': dedup_key,
                'llm_input': {
                    'chat_id': normalized.chat_id,
                    'sender_id': normalized.sender_id,
                    'update_id': normalized.update_id,
                },
            }
        )
        return {
            'status': 'duplicate_ignored',
            'case_id': case_id,
            'reason': 'duplicate_update',
            'update_id': normalized.update_id,
        }

    is_authorized, auth_reason = _authorized_for_telegram(normalized)
    if not is_authorized:
        await audit_service.log_event(
            {
                'event_id': str(uuid.uuid4()),
                'case_id': case_id,
                'source': 'telegram',
                'agent_name': 'frya-orchestrator',
                'approval_status': 'NOT_REQUIRED',
                'action': 'TELEGRAM_AUTH_DENIED',
                'result': auth_reason,
                'llm_input': {
                    'chat_id': normalized.chat_id,
                    'sender_id': normalized.sender_id,
                    'auth_result': 'denied',
                },
            }
        )

        deny_result = await telegram_connector.send(
            NotificationMessage(
                target=normalized.chat_id,
                text=_deny_reply(),
                metadata={'case_id': case_id, 'update_id': normalized.update_id},
            )
        )

        await audit_service.log_event(
            {
                'event_id': str(uuid.uuid4()),
                'case_id': case_id,
                'source': 'telegram',
                'agent_name': 'frya-orchestrator',
                'approval_status': 'NOT_REQUIRED',
                'action': 'TELEGRAM_REPLY_ATTEMPTED',
                'result': str(deny_result),
                'llm_output': {'intent': 'auth.denied', 'reply_ok': bool(deny_result.get('ok', False))},
            }
        )

        return {
            'status': 'denied',
            'case_id': case_id,
            'reason': auth_reason,
            'reply_ok': bool(deny_result.get('ok', False)),
        }

    intent = detect_intent(normalized.text)
    await audit_service.log_event(
        {
            'event_id': str(uuid.uuid4()),
            'case_id': case_id,
            'source': 'telegram',
            'agent_name': 'frya-orchestrator',
            'approval_status': 'NOT_REQUIRED',
            'action': 'TELEGRAM_INTENT_RECOGNIZED',
            'result': intent.name,
            'llm_input': {
                'intent': intent.name,
                'chat_id': normalized.chat_id,
                'sender_id': normalized.sender_id,
                'auth_result': 'authorized',
                'supported_intents': TELEGRAM_V1_INTENTS,
            },
        }
    )

    reply_text, command_result = await _handle_telegram_intent(
        intent=intent,
        normalized=normalized,
        audit_service=audit_service,
        open_items_service=open_items_service,
        problem_service=problem_service,
        approval_service=approval_service,
    )

    await audit_service.log_event(
        {
            'event_id': str(uuid.uuid4()),
            'case_id': case_id,
            'source': 'telegram',
            'agent_name': 'frya-orchestrator',
            'approval_status': 'NOT_REQUIRED',
            'action': 'TELEGRAM_COMMAND_HANDLED',
            'result': str(command_result.get('status', 'UNKNOWN')),
            'llm_input': {
                'intent': intent.name,
                'chat_id': normalized.chat_id,
                'sender_id': normalized.sender_id,
                'case_ref': command_result.get('case_id') or intent.case_id,
            },
            'llm_output': command_result,
        }
    )

    reply_result = await telegram_connector.send(
        NotificationMessage(
            target=normalized.chat_id,
            text=reply_text,
            metadata={'case_id': case_id, 'update_id': normalized.update_id, 'intent': intent.name},
        )
    )

    await audit_service.log_event(
        {
            'event_id': str(uuid.uuid4()),
            'case_id': case_id,
            'source': 'telegram',
            'agent_name': 'frya-orchestrator',
            'approval_status': 'NOT_REQUIRED',
            'action': 'TELEGRAM_REPLY_ATTEMPTED',
            'result': str(reply_result),
            'llm_output': {
                'intent': intent.name,
                'reply_ok': bool(reply_result.get('ok', False)),
                'reply_reason': reply_result.get('reason'),
            },
        }
    )

    return {
        'status': 'accepted',
        'case_id': case_id,
        'intent': intent.name,
        'command_status': command_result.get('status', 'UNKNOWN'),
        'reply_ok': bool(reply_result.get('ok', False)),
        'reply_reason': reply_result.get('reason'),
    }
