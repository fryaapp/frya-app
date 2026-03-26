from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, Request

from app.approvals.service import ApprovalService
from app.audit.service import AuditService
from app.config import get_settings
from app.connectors.contracts import NotificationMessage
from app.connectors.notifications_telegram import TelegramConnector
from app.dependencies import (
    get_approval_service,
    get_audit_service,
    get_case_repository,
    get_email_intake_repository,
    get_llm_config_repository,
    get_open_items_service,
    get_policy_access_layer,
    get_problem_case_service,
    get_telegram_case_link_service,
    get_telegram_clarification_service,
    get_chat_history_store,
    get_communicator_conversation_store,
    get_communicator_user_store,
    get_telegram_communicator_service,
    get_telegram_connector,
    get_telegram_deduplicator,
    get_telegram_media_ingress_service,
    get_telegram_document_analyst_start_service,
)
from app.open_items.service import OpenItemsService
from app.telegram.document_analyst_start_service import TelegramDocumentAnalystStartService
from app.problems.service import ProblemCaseService
from app.telegram.clarification_service import TelegramClarificationService
from app.telegram.communicator.memory.chat_history_store import ChatHistoryStore
from app.telegram.communicator.memory.conversation_store import (
    ConversationMemoryStore,
    build_updated_conversation_memory,
)
from app.telegram.communicator.memory.user_store import UserMemoryStore
from app.telegram.communicator.service import TelegramCommunicatorService
from app.telegram.dedup import TelegramUpdateDeduplicator
from app.telegram.intent_v1 import TelegramIntent, detect_intent
from app.telegram.media_service import TelegramMediaIngressService
from app.telegram.models import (
    TelegramActor,
    TelegramMediaAttachment,
    TelegramNormalizedIngressMessage,
    TelegramRoutingResult,
    TelegramUserVisibleStatus,
)
from app.telegram.service import TelegramCaseLinkService

router = APIRouter(prefix='/webhooks', tags=['webhooks'])


TELEGRAM_V1_INTENTS: tuple[str, ...] = (
    'status.overview',
    'help.basic',
)


def _extract_telegram_message(payload: dict) -> tuple[str | None, dict | None]:
    for key in ('message', 'edited_message', 'channel_post', 'edited_channel_post'):
        candidate = payload.get(key)
        if isinstance(candidate, dict):
            return key, candidate
    return None, None


def _normalize_telegram_update(payload: dict) -> TelegramNormalizedIngressMessage | None:
    raw_type, message = _extract_telegram_message(payload)
    if message is None:
        return None

    chat = message.get('chat') or {}
    chat_id = chat.get('id')
    if chat_id is None:
        return None

    sender = message.get('from') or {}
    sender_id = sender.get('id')
    message_id = message.get('message_id')
    reply_to_message = message.get('reply_to_message') or {}
    reply_to_message_id = reply_to_message.get('message_id')
    update_id = payload.get('update_id')
    text = message.get('text') or message.get('caption') or ''
    media_attachments = _extract_telegram_media(message)

    return TelegramNormalizedIngressMessage(
        event_id=str(uuid.uuid4()),
        raw_type=raw_type or 'message',
        text=text.strip() if isinstance(text, str) else '',
        update_id=update_id,
        message_id=message_id,
        reply_to_message_id=reply_to_message_id,
        telegram_update_ref=f"tg-update:{update_id if update_id is not None else 'unknown'}",
        telegram_message_ref=f"tg-message:{message_id if message_id is not None else 'unknown'}",
        telegram_reply_to_message_ref=(
            f"tg-message:{reply_to_message_id}" if reply_to_message_id is not None else None
        ),
        telegram_chat_ref=f'tg-chat:{chat_id}',
        actor=TelegramActor(
            chat_id=str(chat_id),
            chat_type=chat.get('type'),
            sender_id=str(sender_id) if sender_id is not None else None,
            sender_username=sender.get('username'),
        ),
        media_attachments=media_attachments,
    )


def _extract_telegram_media(message: dict) -> list[TelegramMediaAttachment]:
    attachments: list[TelegramMediaAttachment] = []

    photos = message.get('photo')
    if isinstance(photos, list) and photos:
        largest = sorted(
            [photo for photo in photos if isinstance(photo, dict)],
            key=lambda item: (item.get('file_size') or 0, item.get('width') or 0, item.get('height') or 0),
            reverse=True,
        )[0]
        if largest.get('file_id'):
            attachments.append(
                TelegramMediaAttachment(
                    media_kind='photo',
                    telegram_file_id=str(largest['file_id']),
                    telegram_file_unique_id=str(largest.get('file_unique_id')) if largest.get('file_unique_id') else None,
                    file_name='telegram_photo.jpg',
                    mime_type='image/jpeg',
                    file_size=largest.get('file_size'),
                )
            )

    document = message.get('document')
    if isinstance(document, dict) and document.get('file_id'):
        attachments.append(
            TelegramMediaAttachment(
                media_kind='document',
                telegram_file_id=str(document['file_id']),
                telegram_file_unique_id=str(document.get('file_unique_id')) if document.get('file_unique_id') else None,
                file_name=document.get('file_name'),
                mime_type=document.get('mime_type'),
                file_size=document.get('file_size'),
            )
        )

    return attachments


def _split_allowlist(raw: str | None) -> set[str]:
    if not raw:
        return set()
    normalized = raw.replace(';', ',').replace('\n', ',')
    return {token.strip() for token in normalized.split(',') if token.strip()}


def _authorized_for_telegram(event: TelegramNormalizedIngressMessage) -> tuple[bool, str]:
    settings = get_settings()

    allowed_group_chats = _split_allowlist(settings.telegram_allowed_chat_ids)
    if settings.telegram_default_chat_id:
        allowed_group_chats.add(settings.telegram_default_chat_id.strip())

    allowed_direct_chats = _split_allowlist(settings.telegram_allowed_direct_chat_ids)
    allowed_chats = allowed_group_chats.union(allowed_direct_chats)
    allowed_users = _split_allowlist(settings.telegram_allowed_user_ids)

    if not allowed_chats:
        return False, 'allowlist_missing'

    if event.actor.chat_id not in allowed_chats:
        if event.actor.chat_type == 'private':
            return False, 'private_chat_not_allowed'
        return False, 'chat_not_allowed'

    if allowed_users:
        if not event.actor.sender_id:
            return False, 'sender_missing'
        if event.actor.sender_id not in allowed_users:
            return False, 'user_not_allowed'

    return True, 'authorized'


def _webhook_secret_valid(request: Request) -> tuple[bool, str]:
    settings = get_settings()
    expected = (settings.telegram_webhook_secret or '').strip()
    if not expected:
        return True, 'not_configured'
    received = request.headers.get('x-telegram-bot-api-secret-token', '').strip()
    if received != expected:
        return False, 'secret_token_invalid'
    return True, 'secret_token_valid'


def _build_telegram_dedup_key(normalized: TelegramNormalizedIngressMessage, payload: dict) -> str:
    return TelegramUpdateDeduplicator.build_key(normalized.update_id, payload)


def _build_case_id(normalized: TelegramNormalizedIngressMessage) -> str:
    message_key = normalized.message_id or normalized.update_id or str(uuid.uuid4())
    return f'tg-{normalized.actor.chat_id}-{message_key}'


def _build_thread_ref(normalized: TelegramNormalizedIngressMessage) -> str:
    sender_key = normalized.actor.sender_id or normalized.actor.chat_id
    return f"{normalized.telegram_chat_ref}:{sender_key}"


def _sender_label(normalized: TelegramNormalizedIngressMessage) -> str:
    if normalized.actor.sender_username:
        return f"@{normalized.actor.sender_username}"
    if normalized.actor.sender_id:
        return f"user:{normalized.actor.sender_id}"
    return normalized.telegram_chat_ref


def _deny_reply() -> str:
    return 'FRYA: Zugriff abgelehnt. Dieser Telegram-Chat ist nicht autorisiert.'


def _secret_deny_reply() -> str:
    return 'FRYA: Telegram-Webhook abgewiesen. Secret-Pruefung fehlgeschlagen.'


def _unsupported_reply() -> str:
    return 'FRYA: Dieser Telegram-Typ wird in V1 nicht verarbeitet. Bitte Text, Bild oder PDF senden.'


def _accepted_reply(case_id: str) -> str:
    return (
        'FRYA: Nachricht angenommen.\n'
        'Sie wurde fuer die interne Operator-Queue aufgenommen.\n'
        f'Ref: {case_id}'
    )


def _reply_state(result: dict) -> tuple[str, str | None]:
    reason = result.get('reason')
    if bool(result.get('ok', False)):
        return 'SENT', reason
    if reason == 'telegram_bot_token_missing':
        return 'SKIPPED_NO_TOKEN', reason
    return 'FAILED', reason


def _help_reply() -> str:
    return (
        'FRYA Telegram V1\n'
        'Unterstuetzt:\n'
        '- /start oder hilfe\n'
        '- /status oder status\n'
        '- sonstiger Text wird als Operator-Eingang aufgenommen\n'
        '- Bild wird sicher fuer die Operator-Queue aufgenommen\n'
        '- PDF wird sicher fuer den internen Dokumenteneingang aufgenommen'
    )


def _clarification_received_reply() -> str:
    return 'FRYA: Antwort erhalten. Sie wurde dem offenen Anliegen zugeordnet und wird intern geprueft.'


def _clarification_ambiguous_reply() -> str:
    return 'FRYA: Deine Antwort ist eingegangen, konnte aber nicht eindeutig zugeordnet werden. Sie wird manuell geprueft.'


def _clarification_not_open_reply() -> str:
    return 'FRYA: Aktuell ist keine offene Rueckfrage fuer deinen letzten Telegram-Eingang vorhanden.'


def _status_reply(status: TelegramUserVisibleStatus) -> str:
    return (
        'FRYA Status\n'
        f'- status: {status.status_label}\n'
        f'- detail: {status.status_detail}\n'
        f'- ref: {status.linked_case_id or "-"}'
    )


async def _handle_status_overview(
    normalized: TelegramNormalizedIngressMessage,
    case_id: str,
    open_items_service: OpenItemsService,
    problem_service: ProblemCaseService,
    approval_service: ApprovalService,
    audit_service: AuditService,
    telegram_case_link_service: TelegramCaseLinkService,
    clarification_service: TelegramClarificationService,
) -> tuple[TelegramRoutingResult, str, dict]:
    latest_trackable = await telegram_case_link_service.latest_trackable_for_message(
        normalized,
        exclude_case_id=case_id,
    )
    if latest_trackable is not None:
        linked_case_id = latest_trackable.linked_case_id or latest_trackable.case_id
        linked_open_items = await open_items_service.list_by_case(linked_case_id)
        linked_problems = await problem_service.by_case(linked_case_id)
        linked_chronology = await audit_service.by_case(linked_case_id, limit=200)
        linked_clarification = await clarification_service.latest_by_case(linked_case_id)
        status_view = await telegram_case_link_service.build_user_visible_status(
            latest_trackable,
            linked_open_items,
            linked_problems,
            linked_chronology,
            linked_clarification,
        )
        route = TelegramRoutingResult(
            case_id=case_id,
            routing_status='STATUS_REQUEST',
            intent_name='status.overview',
            ack_template='ACK_STATUS',
            authorization_status='AUTHORIZED',
            next_manual_step='Kein weiterer Telegram-Schritt offen.',
            telegram_thread_ref=_build_thread_ref(normalized),
            linked_case_id=status_view.linked_case_id,
            linked_open_item_id=status_view.open_item_id,
            linked_problem_case_id=status_view.problem_case_id,
            user_visible_status_code=status_view.status_code,
            user_visible_status_label=status_view.status_label,
            user_visible_status_detail=status_view.status_detail,
        )
        return route, _status_reply(status_view), {
            'status': 'OK',
            'intent': 'status.overview',
            'linked_case_id': status_view.linked_case_id,
            'user_visible_status': status_view.model_dump(mode='json'),
        }

    open_items = await open_items_service.list_items()
    problems = await problem_service.recent(limit=10)
    approvals = await approval_service.recent(limit=100)
    pending_approvals = [x for x in approvals if x.status == 'PENDING']

    policy_access = get_policy_access_layer()
    policies_ok, missing = policy_access.required_policies_loaded()

    status_view = TelegramUserVisibleStatus(
        status_code='NOT_AVAILABLE',
        status_label='Kein verknuepfter Fall',
        status_detail='Zu deinem letzten Telegram-Eingang liegt noch kein verknuepfter Fall vor.',
    )
    route = TelegramRoutingResult(
        case_id=case_id,
        routing_status='STATUS_REQUEST',
        intent_name='status.overview',
        ack_template='ACK_STATUS',
        authorization_status='AUTHORIZED',
        next_manual_step='Einen Telegram-Eingang zuerst als Textnachricht anlegen.',
        telegram_thread_ref=_build_thread_ref(normalized),
        user_visible_status_code=status_view.status_code,
        user_visible_status_label=status_view.status_label,
        user_visible_status_detail=status_view.status_detail,
    )
    return route, _status_reply(status_view), {
        'status': 'OK',
        'intent': 'status.overview',
        'open_items': len(open_items),
        'problem_cases': len(problems),
        'pending_approvals': len(pending_approvals),
        'policies_loaded': policies_ok,
        'missing_policy_roles': missing,
        'user_visible_status': status_view.model_dump(mode='json'),
    }


async def _route_telegram_message(
    normalized: TelegramNormalizedIngressMessage,
    case_id: str,
    open_items_service: OpenItemsService,
    problem_service: ProblemCaseService,
    approval_service: ApprovalService,
    audit_service: AuditService,
    telegram_case_link_service: TelegramCaseLinkService,
    clarification_service: TelegramClarificationService,
    communicator_service: TelegramCommunicatorService,
    conversation_store: ConversationMemoryStore | None = None,
    user_store: UserMemoryStore | None = None,
    llm_config_repository: Any = None,
    case_repository: Any = None,
    email_intake_repository: Any = None,
    chat_history_store: Any = None,
) -> tuple[TelegramRoutingResult, str, dict]:
    intent: TelegramIntent = detect_intent(normalized.text)

    if intent.name == 'help.basic':
        route = TelegramRoutingResult(
            case_id=case_id,
            routing_status='HELP_REQUEST',
            intent_name=intent.name,
            ack_template='ACK_HELP',
            authorization_status='AUTHORIZED',
            next_manual_step='Kein weiterer Telegram-Schritt offen.',
            telegram_thread_ref=_build_thread_ref(normalized),
        )
        return route, _help_reply(), {'status': 'OK', 'intent': intent.name}

    if intent.name == 'status.overview':
        return await _handle_status_overview(
            normalized=normalized,
            case_id=case_id,
            open_items_service=open_items_service,
            problem_service=problem_service,
            approval_service=approval_service,
            audit_service=audit_service,
            telegram_case_link_service=telegram_case_link_service,
            clarification_service=clarification_service,
        )

    # ── Communicator V0: try natural language handling before operator inbox ──
    # Handles: GREETING, STATUS_OVERVIEW, NEEDS_FROM_USER, DOCUMENT_ARRIVAL_CHECK,
    #          LAST_CASE_EXPLANATION, GENERAL_SAFE_HELP, UNSUPPORTED_OR_RISKY.
    # Returns None for truly unrecognized text → falls through to ACCEPTED_TO_INBOX.
    comm_result = await communicator_service.try_handle_turn(
        normalized=normalized,
        case_id=case_id,
        audit_service=audit_service,
        open_items_service=open_items_service,
        clarification_service=clarification_service,
        conversation_store=conversation_store,
        user_store=user_store,
        llm_config_repository=llm_config_repository,
        case_repository=case_repository,
        email_intake_repository=email_intake_repository,
        chat_history_store=chat_history_store,
    )
    if comm_result is not None:
        _is_general_conv = comm_result.turn.intent == 'GENERAL_CONVERSATION'
        _gen_conv_open_item_id: str | None = None
        if _is_general_conv:
            _gen_item = await open_items_service.create_item(
                case_id=case_id,
                title=f'[Communicator] {_sender_label(normalized)}',
                description=(
                    f'Kommunikator hat geantwortet.\n'
                    f'Chat: {normalized.telegram_chat_ref}\n'
                    f'Sender: {_sender_label(normalized)}\n'
                    f'Text: {normalized.text}'
                ),
                source='telegram',
            )
            _gen_conv_open_item_id = _gen_item.item_id
        comm_route = TelegramRoutingResult(
            case_id=case_id,
            routing_status=comm_result.routing_status,
            intent_name='communicator.' + comm_result.turn.intent.lower(),
            ack_template='ACK_COMMUNICATOR',
            authorization_status='AUTHORIZED',
            next_manual_step=(
                'Kommunikator hat geantwortet — Rueckfrage bei Bedarf moeglich.'
                if _is_general_conv
                else 'Kommunikator hat geantwortet. Kein weiterer Telegram-Schritt offen.'
            ),
            telegram_thread_ref=_build_thread_ref(normalized),
            track_for_status=_is_general_conv,
            linked_case_id=case_id if _is_general_conv else None,
            open_item_id=_gen_conv_open_item_id,
            linked_open_item_id=_gen_conv_open_item_id,
            user_visible_status_code='COMMUNICATOR_REPLIED' if _is_general_conv else None,
            user_visible_status_label='Beantwortet' if _is_general_conv else None,
            user_visible_status_detail='Deine Nachricht wurde beantwortet.' if _is_general_conv else None,
        )
        return comm_route, comm_result.reply_text, {
            'status': comm_result.routing_status,
            'intent': comm_result.turn.intent,
            'communicator_turn_ref': comm_result.turn.communicator_turn_ref,
            'guardrail_passed': comm_result.turn.guardrail_passed,
            'response_type': comm_result.turn.response_type,
            'open_item_id': _gen_conv_open_item_id,
            'context_resolution': (
                comm_result.turn.context_resolution.model_dump(mode='json')
                if comm_result.turn.context_resolution else None
            ),
        }
    # ─────────────────────────────────────────────────────────────────────────

    inbox_item = await open_items_service.create_item(
        case_id=case_id,
        title=f'[Telegram] Nachricht pruefen: {_sender_label(normalized)}',
        description=(
            'Telegram-Eingang konservativ in die Operator-Queue aufgenommen.\n'
            f'Chat: {normalized.telegram_chat_ref}\n'
            f'Sender: {_sender_label(normalized)}\n'
            f'Text: {normalized.text}'
        ),
        source='telegram',
    )
    route = TelegramRoutingResult(
        case_id=case_id,
        routing_status='ACCEPTED_TO_INBOX',
        intent_name='operator_text',
        ack_template='ACK_ACCEPTED',
        authorization_status='AUTHORIZED',
        open_item_id=inbox_item.item_id,
        open_item_title=inbox_item.title,
        next_manual_step='Telegram-Eingang in der Operator-Queue pruefen.',
        telegram_thread_ref=_build_thread_ref(normalized),
        linked_case_id=case_id,
        linked_open_item_id=inbox_item.item_id,
        track_for_status=True,
        user_visible_status_code='IN_QUEUE',
        user_visible_status_label='In operatorischer Pruefung',
        user_visible_status_detail='Dein letzter Eingang wartet aktuell auf operatorische Pruefung.',
    )
    return route, _accepted_reply(case_id), {
        'status': 'ACCEPTED_TO_INBOX',
        'intent': 'operator_text',
        'open_item_id': inbox_item.item_id,
        'open_item_title': inbox_item.title,
        'linked_case_id': case_id,
        'user_visible_status': {
            'status_code': 'IN_QUEUE',
            'status_label': 'In operatorischer Pruefung',
            'status_detail': 'Dein letzter Eingang wartet aktuell auf operatorische Pruefung.',
            'linked_case_id': case_id,
            'open_item_id': inbox_item.item_id,
            'open_item_title': inbox_item.title,
        },
    }


async def _route_telegram_clarification_answer(
    normalized: TelegramNormalizedIngressMessage,
    case_id: str,
    clarification_service: TelegramClarificationService,
) -> tuple[TelegramRoutingResult, str, dict] | None:
    if not normalized.text:
        return None

    intent = detect_intent(normalized.text)
    if intent.name in {'status.overview', 'help.basic'}:
        return None

    resolution, record = await clarification_service.resolve_incoming_answer(normalized, answer_case_id=case_id)
    if resolution == 'NOT_OPEN':
        if normalized.reply_to_message_id is None:
            return None
        route = TelegramRoutingResult(
            case_id=case_id,
            routing_status='CLARIFICATION_NOT_OPEN',
            intent_name='clarification.not_open',
            ack_template='ACK_CLARIFICATION_NOT_OPEN',
            authorization_status='AUTHORIZED',
            next_manual_step='Falls noetig, den Eingang als neuen Operator-Text senden.',
            telegram_thread_ref=_build_thread_ref(normalized),
            linked_case_id=case_id,
            user_visible_status_code='NOT_AVAILABLE',
            user_visible_status_label='Keine offene Rueckfrage',
            user_visible_status_detail='Fuer diesen Telegram-Eingang liegt keine offene Rueckfrage vor.',
        )
        return route, _clarification_not_open_reply(), {
            'status': 'NOT_OPEN',
            'intent': 'clarification.answer',
        }

    if resolution == 'AMBIGUOUS':
        route = TelegramRoutingResult(
            case_id=case_id,
            routing_status='CLARIFICATION_ANSWER_AMBIGUOUS',
            intent_name='clarification.ambiguous',
            ack_template='ACK_CLARIFICATION_AMBIGUOUS',
            authorization_status='AUTHORIZED',
            next_manual_step='Antwort manuell einer offenen Rueckfrage zuordnen.',
            telegram_thread_ref=_build_thread_ref(normalized),
            linked_case_id=case_id,
            user_visible_status_code='UNDER_REVIEW',
            user_visible_status_label='Antwort wird geprueft',
            user_visible_status_detail='Deine Antwort ist eingegangen und wird manuell einer Rueckfrage zugeordnet.',
        )
        await clarification_service.mark_ambiguous(case_id, _build_thread_ref(normalized), 'multiple_open_clarifications')
        return route, _clarification_ambiguous_reply(), {
            'status': 'AMBIGUOUS_ROUTING',
            'intent': 'clarification.answer',
        }

    if record is None:
        return None

    updated = await clarification_service.accept_answer(record, case_id, normalized)
    route = TelegramRoutingResult(
        case_id=case_id,
        routing_status='CLARIFICATION_ANSWER_ACCEPTED',
        intent_name='clarification.answer',
        ack_template='ACK_CLARIFICATION_RECEIVED',
        authorization_status='AUTHORIZED',
        next_manual_step='Antwort intern pruefen und den Fall weiterbearbeiten.',
        telegram_thread_ref=_build_thread_ref(normalized),
        linked_case_id=updated.linked_case_id,
        linked_open_item_id=updated.open_item_id,
        clarification_ref=updated.clarification_ref,
        user_visible_status_code='REPLY_RECEIVED',
        user_visible_status_label='Antwort erhalten',
        user_visible_status_detail='Deine Antwort ist eingegangen und liegt der internen Pruefung vor.',
    )
    return route, _clarification_received_reply(), {
        'status': 'ANSWER_RECEIVED',
        'intent': 'clarification.answer',
        'linked_case_id': updated.linked_case_id,
        'clarification_ref': updated.clarification_ref,
        'user_visible_status': {
            'status_code': 'REPLY_RECEIVED',
            'status_label': 'Antwort erhalten',
            'status_detail': 'Deine Antwort ist eingegangen und liegt der internen Pruefung vor.',
            'linked_case_id': updated.linked_case_id,
            'open_item_id': updated.open_item_id,
            'open_item_title': updated.open_item_title,
        },
    }


async def _log_telegram_route(
    audit_service: AuditService,
    normalized: TelegramNormalizedIngressMessage,
    route: TelegramRoutingResult,
    command_result: dict,
) -> None:
    await audit_service.log_event(
        {
            'event_id': str(uuid.uuid4()),
            'case_id': route.case_id,
            'source': 'telegram',
            'agent_name': 'frya-orchestrator',
            'approval_status': 'NOT_REQUIRED',
            'action': 'TELEGRAM_ROUTED',
            'result': route.routing_status,
            'llm_input': {
                'telegram_update_ref': normalized.telegram_update_ref,
                'telegram_message_ref': normalized.telegram_message_ref,
                'telegram_chat_ref': normalized.telegram_chat_ref,
            },
            'llm_output': {
                **route.model_dump(),
                'command_result': command_result,
            },
        }
    )


@router.post('/paperless/document')
async def paperless_document_webhook(
    payload: dict,
    request: Request,
    audit_service: AuditService = Depends(get_audit_service),
    open_items_service: OpenItemsService = Depends(get_open_items_service),
) -> dict:
    document_id = str(payload.get('document_id', 'unknown'))
    # If Telegram upload encoded frya:{case_id}: in the title, reuse that case_id
    # so the Paperless webhook continues the same case instead of creating a new one.
    _title = str(payload.get('title') or '')
    if _title.startswith('frya:') and _title.count(':') >= 2:
        case_id = _title.split(':')[1]
    else:
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

    from app.case_engine.tenant_resolver import resolve_tenant_id as _resolve_tenant
    _tenant_id = await _resolve_tenant()

    try:
        result = await request.app.state.graph.ainvoke(
            {
                'case_id': case_id,
                'source': 'paperless_webhook',
                'tenant_id': _tenant_id,
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

    # ── Telegram result notification (only for Telegram-originated documents) ──
    # If the title encoded frya:{case_id}:, we know the source was Telegram.
    # Retrieve the chat_id stored in the TELEGRAM_DOCUMENT_UPLOADED_TO_PAPERLESS event.
    if _title.startswith('frya:') and _title.count(':') >= 2:
        try:
            import json as _json
            _tg_events = await audit_service.by_case(case_id, limit=200)
            # Find the Paperless upload event that holds the telegram_chat_id
            _upload_event = next(
                (e for e in _tg_events if getattr(e, 'action', None) in {
                    'TELEGRAM_DOCUMENT_UPLOADED_TO_PAPERLESS',
                    'TELEGRAM_MEDIA_UPLOADED_TO_PAPERLESS',
                }),
                None,
            )
            if _upload_event is not None:
                _upload_meta = _upload_event.llm_output
                if isinstance(_upload_meta, str):
                    try:
                        _upload_meta = _json.loads(_upload_meta)
                    except Exception:
                        _upload_meta = {}
                _chat_id = (_upload_meta or {}).get('telegram_chat_id')
                if _chat_id:
                    # Find analysis result
                    _analysis_event = next(
                        (e for e in reversed(_tg_events) if getattr(e, 'action', None) == 'DOCUMENT_ANALYSIS_COMPLETED'),
                        None,
                    )
                    if _analysis_event is not None:
                        _raw = _analysis_event.llm_output
                        if isinstance(_raw, str):
                            try:
                                _raw = _json.loads(_raw)
                            except Exception:
                                _raw = {}
                        _p = _raw if isinstance(_raw, dict) else {}
                        _decision = _p.get('global_decision', 'UNKNOWN')
                        _doc_type = (_p.get('document_type') or {}).get('value') or '?'
                        _sender_val = (_p.get('sender') or {}).get('value') or '?'
                        _amounts = _p.get('amounts') or []
                        _total = next(
                            (a.get('amount') for a in _amounts if isinstance(a, dict) and a.get('label') == 'TOTAL' and a.get('status') == 'FOUND'),
                            None,
                        )
                        _currency = (_p.get('currency') or {}).get('value') or ''
                        _confidence = _p.get('overall_confidence', 0.0)
                        _conf_pct = f'{int(float(_confidence) * 100)}%' if _confidence else '?'
                        _missing = _p.get('missing_fields') or []
                        if _decision in {'COMPLETED', 'ANALYZED'}:
                            _amount_str = f'{_total} {_currency}'.strip() if _total else '?'
                            _result_text = (
                                f'FRYA: Dokument analysiert.\n'
                                f'Typ: {_doc_type} | Absender: {_sender_val}\n'
                                f'Betrag: {_amount_str} | Konfidenz: {_conf_pct}\n'
                                f'Ref: {case_id}'
                            )
                        else:
                            _missing_str = ', '.join(_missing) if _missing else '—'
                            _result_text = (
                                f'FRYA: Dokument analysiert — unvollständig.\n'
                                f'Typ: {_doc_type} | Konfidenz: {_conf_pct}\n'
                                f'Fehlende Felder: {_missing_str}\n'
                                f'Ref: {case_id}'
                            )
                        await get_telegram_connector().send(
                            NotificationMessage(
                                target=_chat_id,
                                text=_result_text,
                                metadata={'case_id': case_id, 'intent': 'document.analysis_result'},
                            )
                        )
        except Exception:
            pass  # Notification failure never blocks the response

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


async def _handle_telegram_callback_query(
    callback_query: dict,
    raw_payload: dict,
    audit_service: AuditService,
    telegram_connector: TelegramConnector,
    conversation_store: ConversationMemoryStore | None = None,
    chat_history_store: 'ChatHistoryStore | None' = None,
) -> dict:
    """Handle Telegram inline keyboard callback_query (booking approval buttons).

    callback_data format: "booking:{case_id}:approve|reject|correct|defer"
    """
    callback_id = callback_query.get('id', '')
    callback_data = callback_query.get('data', '')
    chat = (callback_query.get('message') or {}).get('chat') or {}
    chat_id = str(chat.get('id', ''))
    from_user = callback_query.get('from') or {}
    update_id = raw_payload.get('update_id')

    # ── Handle duplicate document callbacks ──────────────────────────────────
    if callback_data.startswith('dup_skip:') or callback_data.startswith('dup_force:'):
        _dup_parts = callback_data.split(':')
        _dup_action = _dup_parts[0]  # dup_skip or dup_force
        _dup_case_id = _dup_parts[1] if len(_dup_parts) > 1 else ''

        if _dup_action == 'dup_skip':
            _ack_text = '\u2705 Duplikat übersprungen.'
        else:
            _ack_text = '\U0001f504 Dokument wird erneut verarbeitet...'
            # For dup_force: delete the original in Paperless so re-upload succeeds
            _original_doc_id = _dup_parts[2] if len(_dup_parts) > 2 and _dup_parts[2] else None
            if _original_doc_id:
                try:
                    from app.dependencies import get_paperless_connector
                    _pc = get_paperless_connector()
                    if _pc is not None:
                        import httpx as _httpx
                        async with _httpx.AsyncClient(timeout=20) as _cl:
                            await _cl.delete(
                                f'{_pc.base_url}/api/documents/{_original_doc_id}/',
                                headers={'Authorization': f'Token {_pc.token}'},
                            )
                        logger.info('Duplicate force: deleted Paperless doc #%s for case %s', _original_doc_id, _dup_case_id)
                except Exception as _del_exc:
                    logger.warning('Duplicate force: failed to delete doc #%s: %s', _original_doc_id, _del_exc)

        # Ack callback
        if callback_id and telegram_connector.bot_token:
            import httpx as _httpx
            async with _httpx.AsyncClient(timeout=10) as _cl:
                await _cl.post(
                    f'https://api.telegram.org/bot{telegram_connector.bot_token}/answerCallbackQuery',
                    json={'callback_query_id': callback_id},
                )
        # Send response to chat
        if chat_id and telegram_connector.bot_token:
            await telegram_connector.send(NotificationMessage(target=chat_id, text=_ack_text))

        return {'status': 'processed', 'action': _dup_action, 'case_id': _dup_case_id}

    if not callback_data.startswith('booking:'):
        # Unknown callback — ack and ignore
        if callback_id and telegram_connector.bot_token:
            import httpx as _httpx
            async with _httpx.AsyncClient(timeout=10) as _cl:
                await _cl.post(
                    f'https://api.telegram.org/bot{telegram_connector.bot_token}/answerCallbackQuery',
                    json={'callback_query_id': callback_id},
                )
        return {'status': 'ignored', 'reason': 'unknown_callback_data'}

    parts = callback_data.split(':')
    if len(parts) < 3:
        return {'status': 'ignored', 'reason': 'malformed_callback_data'}

    case_id = parts[1]
    action = parts[2].upper()  # APPROVE | REJECT | CORRECT | DEFER

    await audit_service.log_event(
        {
            'event_id': str(uuid.uuid4()),
            'case_id': case_id,
            'source': 'telegram_callback',
            'agent_name': 'frya-orchestrator',
            'approval_status': 'NOT_REQUIRED',
            'action': 'TELEGRAM_BOOKING_CALLBACK_RECEIVED',
            'result': f'{action} from chat {chat_id}',
            'llm_input': {
                'callback_data': callback_data,
                'update_id': update_id,
                'sender_id': str(from_user.get('id', '')),
            },
        }
    )

    from app.accounting.booking_service import BookingService
    from app.booking.approval_service import BookingApprovalService
    from app.dependencies import (
        get_accounting_repository,
        get_approval_service as _get_approval_svc,
        get_open_items_service as _get_oi_svc,
    )

    _approval_svc = _get_approval_svc()
    # Look up the pending booking approval for this case
    _pending = [
        r for r in await _approval_svc.list_by_case(case_id)
        if r.status == 'PENDING' and r.action_type == 'booking_finalize'
    ]
    if not _pending:
        return {'status': 'not_found', 'case_id': case_id, 'reason': 'no_pending_booking_approval'}
    _approval_id = _pending[0].approval_id

    booking_svc = BookingApprovalService(
        approval_service=_approval_svc,
        open_items_service=_get_oi_svc(),
        audit_service=audit_service,
        booking_service=BookingService(get_accounting_repository()),
    )

    result = await booking_svc.process_response(
        case_id=case_id,
        approval_id=_approval_id,
        decision_raw=action,
        decided_by=str(from_user.get('username') or from_user.get('id') or 'telegram_user'),
        source='telegram_callback',
    )

    # ── Update ConversationMemory so Frya remembers this approval ──────────
    if conversation_store is not None and chat_id:
        try:
            _prev_mem = await conversation_store.load(chat_id)
            _updated_mem = build_updated_conversation_memory(
                chat_id=chat_id,
                prev_memory=_prev_mem,
                intent='BOOKING_RESPONSE',
                resolved_case_ref=case_id,
                resolved_document_ref=None,
                resolved_clarification_ref=None,
                resolved_open_item_id=None,
                context_resolution_status='FOUND',
            )
            await conversation_store.save(_updated_mem)
            logger.info('Callback memory updated: chat_id=%s case_id=%s action=%s', chat_id, case_id, action)
        except Exception as exc:
            logger.warning('Callback memory update failed: chat_id=%s error=%s', chat_id, exc)
    else:
        logger.warning('Callback memory skipped: conversation_store=%s chat_id=%s', conversation_store is not None, chat_id)

    # ── Append to ChatHistory so LLM context includes the approval ─────────
    _action_labels = {
        'APPROVE': 'Buchung freigegeben',
        'REJECT': 'Buchung abgelehnt',
        'CORRECT': 'Korrektur angefordert',
        'DEFER': 'Buchung zurückgestellt',
    }
    if chat_history_store is not None and chat_id:
        try:
            await chat_history_store.append(
                chat_id,
                f'[User hat {_action_labels.get(action, action)} für {case_id}]',
                f'FRYA: {_action_labels.get(action, action)}.',
            )
            logger.info('Callback chat_history updated: chat_id=%s action=%s', chat_id, action)
        except Exception as exc:
            logger.warning('Callback chat_history update failed: %s', exc)
    else:
        logger.warning('Callback chat_history skipped: store=%s chat_id=%s', chat_history_store is not None, chat_id)

    # Ack the callback so Telegram removes the loading spinner
    if callback_id and telegram_connector.bot_token:
        import httpx as _httpx
        async with _httpx.AsyncClient(timeout=10) as _cl:
            await _cl.post(
                f'https://api.telegram.org/bot{telegram_connector.bot_token}/answerCallbackQuery',
                json={'callback_query_id': callback_id},
            )

    # Send confirmation message to the user
    if chat_id and telegram_connector.bot_token:
        _ack_texts = {
            'APPROVE': '✅ Buchung wurde freigegeben.',
            'REJECT': '❌ Buchung wurde abgelehnt.',
            'CORRECT': '✏️ Bitte schick mir die Korrektur als Nachricht.',
            'DEFER': '⏸️ Buchung zurückgestellt. Du kannst sie später freigeben.',
        }
        _ack = _ack_texts.get(action, f'Aktion "{action}" verarbeitet.')
        await telegram_connector.send(NotificationMessage(target=chat_id, text=_ack))

    return {'status': 'processed', 'case_id': case_id, 'action': action, 'result': result}


@router.post('/telegram')
async def telegram_webhook(
    payload: dict,
    request: Request,
    audit_service: AuditService = Depends(get_audit_service),
    telegram_connector: TelegramConnector = Depends(get_telegram_connector),
    deduplicator: TelegramUpdateDeduplicator = Depends(get_telegram_deduplicator),
    telegram_case_link_service: TelegramCaseLinkService = Depends(get_telegram_case_link_service),
    clarification_service: TelegramClarificationService = Depends(get_telegram_clarification_service),
    telegram_media_ingress_service: TelegramMediaIngressService = Depends(get_telegram_media_ingress_service),
    open_items_service: OpenItemsService = Depends(get_open_items_service),
    problem_service: ProblemCaseService = Depends(get_problem_case_service),
    approval_service: ApprovalService = Depends(get_approval_service),
    communicator_service: TelegramCommunicatorService = Depends(get_telegram_communicator_service),
    conversation_store: ConversationMemoryStore = Depends(get_communicator_conversation_store),
    user_store: UserMemoryStore = Depends(get_communicator_user_store),
    llm_config_repository: Any = Depends(get_llm_config_repository),
    case_repository: Any = Depends(get_case_repository),
    email_intake_repository: Any = Depends(get_email_intake_repository),
    document_analyst_start_service: TelegramDocumentAnalystStartService = Depends(get_telegram_document_analyst_start_service),
) -> dict:
    # ── Inline keyboard callback_query (booking approval buttons) ────────────
    callback_query = payload.get('callback_query')
    if isinstance(callback_query, dict):
        return await _handle_telegram_callback_query(
            callback_query, payload, audit_service, telegram_connector,
            conversation_store=conversation_store,
            chat_history_store=get_chat_history_store(),
        )

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
                'result': 'Unsupported update type or malformed payload',
                'llm_input': payload,
            }
        )
        return {'status': 'ignored', 'reason': 'unsupported_or_malformed_payload'}

    case_id = _build_case_id(normalized)
    await audit_service.log_event(
        {
            'event_id': str(uuid.uuid4()),
            'case_id': case_id,
            'source': 'telegram',
            'agent_name': 'frya-orchestrator',
            'approval_status': 'NOT_REQUIRED',
            'action': 'TELEGRAM_WEBHOOK_RECEIVED',
            'result': 'Message accepted for verification',
            'llm_input': {
                'telegram_update_ref': normalized.telegram_update_ref,
                'telegram_message_ref': normalized.telegram_message_ref,
                'telegram_chat_ref': normalized.telegram_chat_ref,
                'chat_type': normalized.actor.chat_type,
                'sender_id': normalized.actor.sender_id,
                'sender_username': normalized.actor.sender_username,
                'text': normalized.text,
                'media_attachments': [item.model_dump(mode='json') for item in normalized.media_attachments],
            },
        }
    )

    secret_valid, secret_reason = _webhook_secret_valid(request)
    if not secret_valid:
        route = TelegramRoutingResult(
            case_id=case_id,
            routing_status='REJECTED_SECRET',
            intent_name='webhook.secret',
            ack_template='ACK_SECRET_DENIED',
            authorization_status='SECRET_DENIED',
            auth_reason=secret_reason,
            reply_required=False,
            next_manual_step='Webhook-Secret pruefen.',
            telegram_thread_ref=_build_thread_ref(normalized),
            linked_case_id=case_id,
        )
        await telegram_case_link_service.upsert_case_link(
            normalized=normalized,
            route=route,
            reply_status='NOT_ATTEMPTED',
            reply_reason=secret_reason,
        )
        await audit_service.log_event(
            {
                'event_id': str(uuid.uuid4()),
                'case_id': case_id,
                'source': 'telegram',
                'agent_name': 'frya-orchestrator',
                'approval_status': 'NOT_REQUIRED',
                'action': 'TELEGRAM_SECRET_DENIED',
                'result': secret_reason,
                'llm_output': route.model_dump(),
            }
        )
        return {'status': 'denied', 'case_id': case_id, 'reason': secret_reason}

    dedup_key = _build_telegram_dedup_key(normalized, payload)
    is_first_seen = await deduplicator.acquire(dedup_key)
    if not is_first_seen:
        route = TelegramRoutingResult(
            case_id=case_id,
            routing_status='DUPLICATE_IGNORED',
            intent_name='duplicate',
            ack_template='ACK_DUPLICATE',
            authorization_status='SKIPPED',
            auth_reason='duplicate_update',
            reply_required=False,
            next_manual_step='Keine weitere Agentenaktion offen.',
            telegram_thread_ref=_build_thread_ref(normalized),
            linked_case_id=case_id,
        )
        await audit_service.log_event(
            {
                'event_id': str(uuid.uuid4()),
                'case_id': case_id,
                'source': 'telegram',
                'agent_name': 'frya-orchestrator',
                'approval_status': 'NOT_REQUIRED',
                'action': 'TELEGRAM_DUPLICATE_IGNORED',
                'result': dedup_key,
                'llm_output': route.model_dump(),
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
        route = TelegramRoutingResult(
            case_id=case_id,
            routing_status='REJECTED_UNAUTHORIZED',
            intent_name='auth.denied',
            ack_template='ACK_UNAUTHORIZED',
            authorization_status='DENIED',
            auth_reason=auth_reason,
            next_manual_step='Allowlist fuer Chat/User pruefen.',
            telegram_thread_ref=_build_thread_ref(normalized),
            linked_case_id=case_id,
            user_visible_status_code='REJECTED',
            user_visible_status_label='Nicht angenommen',
            user_visible_status_detail='Dieser Telegram-Eingang wurde aus Sicherheitsgruenden nicht verarbeitet.',
        )
        await audit_service.log_event(
            {
                'event_id': str(uuid.uuid4()),
                'case_id': case_id,
                'source': 'telegram',
                'agent_name': 'frya-orchestrator',
                'approval_status': 'NOT_REQUIRED',
                'action': 'TELEGRAM_AUTH_DENIED',
                'result': auth_reason,
                'llm_output': route.model_dump(),
            }
        )
        deny_result = await telegram_connector.send(
            NotificationMessage(
                target=normalized.actor.chat_id,
                text=_deny_reply(),
                metadata={'case_id': case_id, 'telegram_update_ref': normalized.telegram_update_ref},
            )
        )
        await telegram_case_link_service.upsert_case_link(
            normalized=normalized,
            route=route,
            reply_status=_reply_state(deny_result)[0],
            reply_reason=_reply_state(deny_result)[1],
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
                'llm_output': {
                    **route.model_dump(),
                    'reply_ok': bool(deny_result.get('ok', False)),
                    'reply_reason': deny_result.get('reason'),
                },
            }
        )
        return {'status': 'denied', 'case_id': case_id, 'reason': auth_reason, 'reply_ok': bool(deny_result.get('ok', False))}

    if not normalized.text and not normalized.media_attachments:
        route = TelegramRoutingResult(
            case_id=case_id,
            routing_status='UNSUPPORTED_MESSAGE_TYPE',
            intent_name='unsupported',
            ack_template='ACK_UNSUPPORTED',
            authorization_status='AUTHORIZED',
            next_manual_step='Textnachricht senden oder diesen Eingang ignorieren.',
            telegram_thread_ref=_build_thread_ref(normalized),
            linked_case_id=case_id,
            user_visible_status_code='NOT_AVAILABLE',
            user_visible_status_label='Nicht unterstuetzt',
            user_visible_status_detail='Dieser Telegram-Typ wird in V1 nur als Hinweis beantwortet und nicht weiterverarbeitet.',
        )
        await _log_telegram_route(audit_service, normalized, route, {'status': 'UNSUPPORTED'})
        reply_result = await telegram_connector.send(
            NotificationMessage(
                target=normalized.actor.chat_id,
                text=_unsupported_reply(),
                metadata={'case_id': case_id, 'telegram_update_ref': normalized.telegram_update_ref},
            )
        )
        await telegram_case_link_service.upsert_case_link(
            normalized=normalized,
            route=route,
            reply_status=_reply_state(reply_result)[0],
            reply_reason=_reply_state(reply_result)[1],
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
                    **route.model_dump(),
                    'reply_ok': bool(reply_result.get('ok', False)),
                    'reply_reason': reply_result.get('reason'),
                },
            }
        )
        return {'status': 'ignored', 'case_id': case_id, 'reason': 'unsupported_message_type', 'reply_ok': bool(reply_result.get('ok', False))}

    if normalized.media_attachments:
        route, reply_text, command_result = await telegram_media_ingress_service.handle_media_ingress(
            normalized=normalized,
            case_id=case_id,
            sender_label=_sender_label(normalized),
            thread_ref=_build_thread_ref(normalized),
        )
        await _log_telegram_route(audit_service, normalized, route, command_result)
        reply_result = await telegram_connector.send(
            NotificationMessage(
                target=normalized.actor.chat_id,
                text=reply_text,
                metadata={
                    'case_id': case_id,
                    'telegram_update_ref': normalized.telegram_update_ref,
                    'intent': route.intent_name,
                },
            )
        )
        await telegram_case_link_service.upsert_case_link(
            normalized=normalized,
            route=route,
            reply_status=_reply_state(reply_result)[0],
            reply_reason=_reply_state(reply_result)[1],
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
                    **route.model_dump(),
                    'reply_ok': bool(reply_result.get('ok', False)),
                    'reply_reason': reply_result.get('reason'),
                },
            }
        )
        # ── Auto-trigger Document Analyst ────────────────────────────────────
        # If FRYA_AUTO_TRIGGER_DOCUMENT_ANALYST=true and the document was accepted,
        # Document Analyst is triggered automatically via the Paperless post-consumption
        # webhook (POST /webhooks/paperless/document) after the file is uploaded to
        # Paperless in TelegramMediaIngressService. No direct trigger here.

        return {
            'status': 'accepted' if route.routing_status in {'MEDIA_ACCEPTED', 'DOCUMENT_ACCEPTED'} else 'ignored',
            'case_id': case_id,
            'intent': route.intent_name,
            'routing_status': route.routing_status,
            'command_status': command_result.get('status', 'UNKNOWN'),
            'open_item_id': route.open_item_id,
            'linked_case_id': route.linked_case_id,
            'document_analyst_context': command_result.get('document_analyst_context'),
            'document_analyst_start': command_result.get('document_analyst_start'),
            'user_visible_status': {
                'status_code': route.user_visible_status_code,
                'status_label': route.user_visible_status_label,
                'status_detail': route.user_visible_status_detail,
                'linked_case_id': route.linked_case_id,
                'open_item_id': route.linked_open_item_id or route.open_item_id,
            },
            'media': command_result.get('media'),
            'reply_ok': bool(reply_result.get('ok', False)),
            'reply_reason': reply_result.get('reason'),
        }

    clarification_route = await _route_telegram_clarification_answer(
        normalized=normalized,
        case_id=case_id,
        clarification_service=clarification_service,
    )
    if clarification_route is not None:
        route, reply_text, command_result = clarification_route
        await _log_telegram_route(audit_service, normalized, route, command_result)
        reply_result = await telegram_connector.send(
            NotificationMessage(
                target=normalized.actor.chat_id,
                text=reply_text,
                metadata={
                    'case_id': case_id,
                    'telegram_update_ref': normalized.telegram_update_ref,
                    'intent': route.intent_name,
                    'clarification_ref': route.clarification_ref,
                },
            )
        )
        await telegram_case_link_service.upsert_case_link(
            normalized=normalized,
            route=route,
            reply_status=_reply_state(reply_result)[0],
            reply_reason=_reply_state(reply_result)[1],
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
                    **route.model_dump(),
                    'reply_ok': bool(reply_result.get('ok', False)),
                    'reply_reason': reply_result.get('reason'),
                },
            }
        )
        return {
            'status': 'accepted',
            'case_id': case_id,
            'intent': route.intent_name,
            'routing_status': route.routing_status,
            'command_status': command_result.get('status', 'UNKNOWN'),
            'open_item_id': route.open_item_id,
            'linked_case_id': route.linked_case_id,
            'clarification_ref': route.clarification_ref,
            'user_visible_status': command_result.get('user_visible_status'),
            'reply_ok': bool(reply_result.get('ok', False)),
            'reply_reason': reply_result.get('reason'),
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
                'telegram_update_ref': normalized.telegram_update_ref,
                'telegram_message_ref': normalized.telegram_message_ref,
                'telegram_chat_ref': normalized.telegram_chat_ref,
                'supported_intents': TELEGRAM_V1_INTENTS,
            },
        }
    )

    route, reply_text, command_result = await _route_telegram_message(
        normalized=normalized,
        case_id=case_id,
        open_items_service=open_items_service,
        problem_service=problem_service,
        approval_service=approval_service,
        audit_service=audit_service,
        telegram_case_link_service=telegram_case_link_service,
        clarification_service=clarification_service,
        communicator_service=communicator_service,
        conversation_store=conversation_store,
        user_store=user_store,
        llm_config_repository=llm_config_repository,
        case_repository=case_repository,
        email_intake_repository=email_intake_repository,
        chat_history_store=get_chat_history_store(),
    )
    await _log_telegram_route(audit_service, normalized, route, command_result)

    reply_result = await telegram_connector.send(
        NotificationMessage(
            target=normalized.actor.chat_id,
            text=reply_text,
            metadata={
                'case_id': case_id,
                'telegram_update_ref': normalized.telegram_update_ref,
                'intent': route.intent_name,
            },
        )
    )
    await telegram_case_link_service.upsert_case_link(
        normalized=normalized,
        route=route,
        reply_status=_reply_state(reply_result)[0],
        reply_reason=_reply_state(reply_result)[1],
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
                **route.model_dump(),
                'reply_ok': bool(reply_result.get('ok', False)),
                'reply_reason': reply_result.get('reason'),
            },
        }
    )

    return {
        'status': 'accepted',
        'case_id': case_id,
        'intent': route.intent_name,
        'routing_status': route.routing_status,
        'command_status': command_result.get('status', 'UNKNOWN'),
        'open_item_id': route.open_item_id,
        'linked_case_id': route.linked_case_id,
        'user_visible_status': {
            'status_code': route.user_visible_status_code,
            'status_label': route.user_visible_status_label,
            'status_detail': route.user_visible_status_detail,
            'linked_case_id': route.linked_case_id,
            'open_item_id': route.linked_open_item_id or route.open_item_id,
            'problem_case_id': route.linked_problem_case_id,
        }
        if route.user_visible_status_code
        else command_result.get('user_visible_status'),
        'reply_ok': bool(reply_result.get('ok', False)),
        'reply_reason': reply_result.get('reason'),
    }
