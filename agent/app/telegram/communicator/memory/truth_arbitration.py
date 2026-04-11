from __future__ import annotations

from app.core.intents import Intent
from app.telegram.communicator.memory.models import ConversationMemory, TruthAnnotation
from app.telegram.communicator.models import CommunicatorContextResolution

# Intents that require context resolution from DB/memory
_CONTEXT_INTENTS = frozenset({
    Intent.STATUS_OVERVIEW,
    'NEEDS_FROM_USER',
    'DOCUMENT_ARRIVAL_CHECK',
    'LAST_CASE_EXPLANATION',
})

# RC-2 Fix: Diese Intents nutzen ebenfalls ConversationMemory als Kontext-Fallback,
# damit Folgefragen ("Ja", "Den buche") den letzten case_ref sehen.
_CONV_MEMORY_INTENTS = frozenset({
    Intent.GENERAL_CONVERSATION,
    Intent.BOOKING_REQUEST,
    Intent.FINANCIAL_QUERY,
    Intent.REMINDER_PERSONAL,
})


class TruthArbitrator:
    """Determines the authoritative truth basis for a communicator turn.

    Hierarchy (lower priority = higher trust):
      0 AUDIT_DERIVED        — fresh from DB; no qualifier needed
      1 CONVERSATION_MEMORY  — cached from Redis; uncertainty phrase required
      4 UNKNOWN              — nothing found; honest response
    """

    def arbitrate(
        self,
        *,
        core_context: CommunicatorContextResolution | None,
        conv_memory: ConversationMemory | None,
        intent: str | None,
    ) -> tuple[CommunicatorContextResolution | None, TruthAnnotation]:
        # Non-context intents: no memory lookup for DB-context,
        # but for conversation-memory intents still return last_case_ref so
        # the LLM can resolve follow-up messages like "Ja", "Den", "Ok".
        if intent not in _CONTEXT_INTENTS:
            if intent in _CONV_MEMORY_INTENTS and conv_memory is not None:
                has_useful = bool(
                    conv_memory.last_case_ref
                    or conv_memory.last_document_ref
                    or conv_memory.last_open_item_id
                )
                if has_useful:
                    mem_ctx = CommunicatorContextResolution(
                        resolution_status='FOUND',
                        resolved_case_ref=conv_memory.last_case_ref,
                        resolved_document_ref=conv_memory.last_document_ref,
                        resolved_clarification_ref=conv_memory.last_clarification_ref,
                        resolved_open_item_id=conv_memory.last_open_item_id,
                        context_reason='Aus Konversationsgedaechtnis (Follow-up).',
                    )
                    return mem_ctx, TruthAnnotation.from_conv_memory()
            return None, TruthAnnotation.unknown()

        # Core DB context FOUND → highest trust
        if core_context is not None and core_context.resolution_status in ('FOUND', 'AMBIGUOUS'):
            return core_context, TruthAnnotation.audit_derived(sources=['audit_trail', 'open_items_db'])

        # Core NOT_FOUND → try conversation memory fallback
        if conv_memory is not None:
            has_useful = bool(
                conv_memory.last_case_ref
                or conv_memory.last_document_ref
                or conv_memory.last_clarification_ref
                or conv_memory.last_open_item_id
            )
            if has_useful:
                # Build a synthetic context from memory
                mem_ctx = CommunicatorContextResolution(
                    resolution_status='FOUND',
                    resolved_case_ref=conv_memory.last_case_ref,
                    resolved_document_ref=conv_memory.last_document_ref,
                    resolved_clarification_ref=conv_memory.last_clarification_ref,
                    resolved_open_item_id=conv_memory.last_open_item_id,
                    context_reason='Aus Konversationsgedaechtnis wiederhergestellt.',
                )
                return mem_ctx, TruthAnnotation.from_conv_memory()

        return core_context, TruthAnnotation.unknown()
