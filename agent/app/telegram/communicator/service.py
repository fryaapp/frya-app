from __future__ import annotations

import uuid
from typing import Any

from app.telegram.communicator.context_resolver import resolve_context
from app.telegram.communicator.guardrail import check_guardrail
from app.telegram.communicator.intent_classifier import classify_intent
from app.telegram.communicator.memory.conversation_store import (
    ConversationMemoryStore,
    build_updated_conversation_memory,
)
from app.telegram.communicator.memory.truth_arbitration import TruthArbitrator
from app.telegram.communicator.memory.user_store import (
    UserMemoryStore,
    build_or_update_user_memory,
)
from app.telegram.communicator.models import (
    CommunicatorResult,
    CommunicatorTurn,
)
from app.telegram.communicator.response_builder import build_response
from app.telegram.models import TelegramNormalizedIngressMessage

_CONTEXT_INTENTS = frozenset({
    'STATUS_OVERVIEW',
    'NEEDS_FROM_USER',
    'DOCUMENT_ARRIVAL_CHECK',
    'LAST_CASE_EXPLANATION',
})


class TelegramCommunicatorService:
    """12-step communicator pipeline.

    Stateless: all state is in stores passed per-call.
    """

    async def try_handle_turn(
        self,
        normalized: TelegramNormalizedIngressMessage,
        case_id: str,
        *,
        audit_service: Any,
        open_items_service: Any,
        clarification_service: Any,
        conversation_store: ConversationMemoryStore | None = None,
        user_store: UserMemoryStore | None = None,
    ) -> CommunicatorResult | None:
        # ── Step 1: classify ────────────────────────────────────────────────
        intent = classify_intent(normalized.text)

        # ── Step 2: fall-through (no audit, no memory update) ───────────────
        if intent is None:
            return None

        # ── Step 3: guardrail ───────────────────────────────────────────────
        guardrail_passed, _guardrail_reason = check_guardrail(intent)

        # ── Step 4: load ConversationMemory ─────────────────────────────────
        chat_id = normalized.actor.chat_id
        conv_memory = None
        if conversation_store is not None:
            conv_memory = await conversation_store.load(chat_id)

        # ── Step 5: load UserMemory ──────────────────────────────────────────
        sender_id = normalized.actor.sender_id or chat_id
        prev_user_memory = None
        if user_store is not None:
            prev_user_memory = await user_store.load(sender_id)

        # ── Step 6: resolve context (only for context-needing intents) ───────
        core_ctx = None
        ctx_ref = None
        if intent in _CONTEXT_INTENTS:
            core_ctx, ctx_ref = await resolve_context(
                case_id,
                audit_service=audit_service,
                clarification_service=clarification_service,
                open_items_service=open_items_service,
            )

        # ── Step 7: truth arbitration ────────────────────────────────────────
        arbitrator = TruthArbitrator()
        effective_ctx, truth_annotation = arbitrator.arbitrate(
            core_context=core_ctx,
            conv_memory=conv_memory,
            intent=intent,
        )

        memory_used = truth_annotation.truth_basis == 'CONVERSATION_MEMORY'
        conv_memory_ref = conv_memory.conversation_memory_ref if (memory_used and conv_memory) else None

        # ── Step 8: build response ───────────────────────────────────────────
        reply_text, response_type = build_response(
            intent,
            effective_ctx,
            guardrail_passed=guardrail_passed,
            truth_annotation=truth_annotation,
        )

        # ── Step 9: build CommunicatorTurn ──────────────────────────────────
        turn_ref = 'comm-' + uuid.uuid4().hex[:12]

        memory_types_used: list[str] = []
        if memory_used:
            memory_types_used.append('conversation_memory')
        if user_store is not None:
            memory_types_used.append('user_memory')

        routing_status = (
            'COMMUNICATOR_GUARDRAIL_TRIGGERED' if not guardrail_passed
            else 'COMMUNICATOR_HANDLED'
        )

        turn = CommunicatorTurn(
            communicator_turn_ref=turn_ref,
            intent=intent,
            guardrail_passed=guardrail_passed,
            truth_basis=truth_annotation.truth_basis,
            memory_used=memory_used,
            conversation_memory_ref=conv_memory_ref,
            response_type=response_type,
            context_resolution=effective_ctx,
            memory_types_used=memory_types_used,
        )

        # ── Step 10: audit ───────────────────────────────────────────────────
        llm_output: dict = {
            'communicator_turn_ref': turn_ref,
            'intent': intent,
            'guardrail_passed': guardrail_passed,
            'truth_basis': truth_annotation.truth_basis,
            'memory_used': memory_used,
            'response_type': response_type,
            'memory_types_used': memory_types_used,
            'context_resolution': (
                effective_ctx.model_dump(mode='json') if effective_ctx else None
            ),
        }
        await audit_service.log_event({
            'event_id': 'comm-evt-' + uuid.uuid4().hex[:12],
            'action': 'COMMUNICATOR_TURN_PROCESSED',
            'agent_name': 'frya-communicator',
            'result': intent,
            'case_id': case_id,
            'llm_output': llm_output,
        })

        # ── Step 11: update conversation memory ──────────────────────────────
        if conversation_store is not None:
            updated_conv = build_updated_conversation_memory(
                chat_id=chat_id,
                prev_memory=conv_memory,
                intent=intent,
                resolved_case_ref=effective_ctx.resolved_case_ref if effective_ctx else None,
                resolved_document_ref=effective_ctx.resolved_document_ref if effective_ctx else None,
                resolved_clarification_ref=effective_ctx.resolved_clarification_ref if effective_ctx else None,
                resolved_open_item_id=effective_ctx.resolved_open_item_id if effective_ctx else None,
                context_resolution_status=effective_ctx.resolution_status if effective_ctx else None,
            )
            await conversation_store.save(updated_conv)

        # ── Step 12: update user memory ───────────────────────────────────────
        if user_store is not None:
            new_user_mem = build_or_update_user_memory(
                sender_id=sender_id,
                prev_memory=prev_user_memory,
                intent=intent,
            )
            await user_store.save(new_user_mem)

        return CommunicatorResult(
            handled=True,
            routing_status=routing_status,
            turn=turn,
            reply_text=reply_text,
        )
