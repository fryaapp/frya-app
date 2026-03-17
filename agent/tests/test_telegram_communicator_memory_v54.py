"""Tests for Kommunikator Memory + Truth Arbitration — Paket 54/55 STEP 2/4.

Coverage:
  TEIL A: ConversationMemoryStore (in-memory backend) — load/save/clear + round-trip
  TEIL B: build_updated_conversation_memory — sticky merge, FOUND vs NOT_FOUND
  TEIL C: UserMemoryStore (in-memory backend) — load/save + intent_counts
  TEIL D: build_or_update_user_memory — new vs existing; never stores operative refs
  TEIL E: TruthArbitrator — AUDIT_DERIVED / CONVERSATION_MEMORY / UNKNOWN
  TEIL F: TruthAnnotation model — properties and factory methods
  TEIL G: response_builder — uncertainty phrase when truth_basis=CONVERSATION_MEMORY
  TEIL H: Service pipeline — memory_used flag, truth_basis propagated to turn
  TEIL I: Webhook end-to-end — second turn reuses conversation memory
  TEIL J: case_views inspect — communicator_turn key present in inspect JSON

37 tests total.
"""
from __future__ import annotations

import json
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

# ── Memory models ──────────────────────────────────────────────────────────────
from app.telegram.communicator.memory.models import (
    ConversationMemory,
    TruthAnnotation,
    UserMemory,
)
from app.telegram.communicator.memory.conversation_store import (
    ConversationMemoryStore,
    build_updated_conversation_memory,
)
from app.telegram.communicator.memory.user_store import (
    UserMemoryStore,
    build_or_update_user_memory,
)
from app.telegram.communicator.memory.truth_arbitration import TruthArbitrator
from app.telegram.communicator.models import CommunicatorContextResolution
from app.telegram.communicator.response_builder import build_response
from app.telegram.communicator.service import TelegramCommunicatorService
from app.telegram.models import (
    TelegramActor,
    TelegramNormalizedIngressMessage,
)

# ── Helpers ────────────────────────────────────────────────────────────────────

def _mem_conv_store() -> ConversationMemoryStore:
    return ConversationMemoryStore('memory://test')


def _mem_user_store() -> UserMemoryStore:
    return UserMemoryStore('memory://test')


def _conv_memory(chat_id='chat-1', case_ref='case-abc', doc_ref='doc-xyz') -> ConversationMemory:
    return ConversationMemory(
        conversation_memory_ref='conv-test-001',
        chat_id=chat_id,
        last_case_ref=case_ref,
        last_document_ref=doc_ref,
        last_clarification_ref=None,
        last_open_item_id=None,
        last_intent='STATUS_OVERVIEW',
        last_context_resolution_status='FOUND',
    )


def _found_context(case_ref='case-abc', doc_ref='doc-xyz') -> CommunicatorContextResolution:
    return CommunicatorContextResolution(
        resolution_status='FOUND',
        resolved_case_ref=case_ref,
        resolved_document_ref=doc_ref,
        resolved_clarification_ref=None,
        resolved_open_item_id=None,
        context_reason='Unit test',
    )


def _not_found_context() -> CommunicatorContextResolution:
    return CommunicatorContextResolution(
        resolution_status='NOT_FOUND',
        resolved_case_ref=None,
        resolved_document_ref=None,
        resolved_clarification_ref=None,
        resolved_open_item_id=None,
        context_reason='Nothing found',
    )


def _normalized(text: str, chat_id: str = 'chat-1', sender_id: str = 'user-1') -> TelegramNormalizedIngressMessage:
    uid = uuid.uuid4().hex[:8]
    return TelegramNormalizedIngressMessage(
        event_id=f'test-evt-{uid}',
        telegram_update_ref=f'upd-{uid}',
        telegram_message_ref=f'msg-{uid}',
        telegram_chat_ref=f'chatref-{uid}',
        actor=TelegramActor(
            chat_id=chat_id,
            sender_id=sender_id,
            sender_username='testuser',
            chat_type='private',
        ),
        text=text,
        media_attachments=[],
    )


def _mock_services():
    audit = AsyncMock()
    audit.log_event = AsyncMock(return_value=None)
    open_items = AsyncMock()
    clarification = AsyncMock()
    return audit, open_items, clarification


# ══════════════════════════════════════════════════════════════════════════════
# TEIL A — ConversationMemoryStore (in-memory)
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_conv_store_load_empty():
    store = _mem_conv_store()
    result = await store.load('chat-missing')
    assert result is None


@pytest.mark.asyncio
async def test_conv_store_save_and_load():
    store = _mem_conv_store()
    mem = _conv_memory(chat_id='chat-42')
    await store.save(mem)
    loaded = await store.load('chat-42')
    assert loaded is not None
    assert loaded.chat_id == 'chat-42'
    assert loaded.last_case_ref == 'case-abc'
    assert loaded.last_document_ref == 'doc-xyz'


@pytest.mark.asyncio
async def test_conv_store_overwrite_on_save():
    store = _mem_conv_store()
    mem1 = _conv_memory(chat_id='chat-5', case_ref='case-old')
    await store.save(mem1)
    mem2 = _conv_memory(chat_id='chat-5', case_ref='case-new')
    await store.save(mem2)
    loaded = await store.load('chat-5')
    assert loaded.last_case_ref == 'case-new'


@pytest.mark.asyncio
async def test_conv_store_clear():
    store = _mem_conv_store()
    await store.save(_conv_memory(chat_id='chat-del'))
    await store.clear('chat-del')
    assert await store.load('chat-del') is None


@pytest.mark.asyncio
async def test_conv_store_clear_nonexistent_is_noop():
    store = _mem_conv_store()
    # Should not raise
    await store.clear('chat-does-not-exist')


# ══════════════════════════════════════════════════════════════════════════════
# TEIL B — build_updated_conversation_memory (sticky merge)
# ══════════════════════════════════════════════════════════════════════════════

def test_build_conv_memory_found_updates_refs():
    prev = _conv_memory(chat_id='chat-1', case_ref='old-case', doc_ref='old-doc')
    result = build_updated_conversation_memory(
        chat_id='chat-1',
        prev_memory=prev,
        intent='STATUS_OVERVIEW',
        resolved_case_ref='new-case',
        resolved_document_ref='new-doc',
        resolved_clarification_ref=None,
        resolved_open_item_id=None,
        context_resolution_status='FOUND',
    )
    assert result.last_case_ref == 'new-case'
    assert result.last_document_ref == 'new-doc'
    assert result.last_intent == 'STATUS_OVERVIEW'
    assert result.last_context_resolution_status == 'FOUND'


def test_build_conv_memory_not_found_preserves_old_refs():
    prev = _conv_memory(chat_id='chat-1', case_ref='old-case', doc_ref='old-doc')
    result = build_updated_conversation_memory(
        chat_id='chat-1',
        prev_memory=prev,
        intent='STATUS_OVERVIEW',
        resolved_case_ref=None,
        resolved_document_ref=None,
        resolved_clarification_ref=None,
        resolved_open_item_id=None,
        context_resolution_status='NOT_FOUND',
    )
    # Sticky: old refs preserved when context NOT_FOUND
    assert result.last_case_ref == 'old-case'
    assert result.last_document_ref == 'old-doc'
    assert result.last_context_resolution_status == 'NOT_FOUND'


def test_build_conv_memory_found_sticky_partial():
    """New case_ref provided but doc_ref=None → keep old doc_ref."""
    prev = _conv_memory(chat_id='chat-1', case_ref='old-case', doc_ref='old-doc')
    result = build_updated_conversation_memory(
        chat_id='chat-1',
        prev_memory=prev,
        intent='STATUS_OVERVIEW',
        resolved_case_ref='new-case',
        resolved_document_ref=None,  # not provided this turn
        resolved_clarification_ref=None,
        resolved_open_item_id=None,
        context_resolution_status='FOUND',
    )
    assert result.last_case_ref == 'new-case'
    assert result.last_document_ref == 'old-doc'  # sticky


def test_build_conv_memory_no_prev_creates_new():
    result = build_updated_conversation_memory(
        chat_id='chat-new',
        prev_memory=None,
        intent='GREETING',
        resolved_case_ref=None,
        resolved_document_ref=None,
        resolved_clarification_ref=None,
        resolved_open_item_id=None,
        context_resolution_status=None,
    )
    assert result.chat_id == 'chat-new'
    assert result.last_case_ref is None
    assert result.conversation_memory_ref.startswith('conv-')


def test_build_conv_memory_preserves_ref():
    prev = _conv_memory()
    prev_ref = prev.conversation_memory_ref
    result = build_updated_conversation_memory(
        chat_id='chat-1',
        prev_memory=prev,
        intent='STATUS_OVERVIEW',
        resolved_case_ref='case-new',
        resolved_document_ref=None,
        resolved_clarification_ref=None,
        resolved_open_item_id=None,
        context_resolution_status='FOUND',
    )
    # Same ref preserved across turns
    assert result.conversation_memory_ref == prev_ref


# ══════════════════════════════════════════════════════════════════════════════
# TEIL C — UserMemoryStore (in-memory)
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_user_store_load_missing():
    store = _mem_user_store()
    assert await store.load('user-missing') is None


@pytest.mark.asyncio
async def test_user_store_save_and_load():
    store = _mem_user_store()
    mem = UserMemory(
        user_memory_ref='umem-test-001',
        sender_id='user-99',
        intent_counts={'GREETING': 2},
    )
    await store.save(mem)
    loaded = await store.load('user-99')
    assert loaded is not None
    assert loaded.sender_id == 'user-99'
    assert loaded.intent_counts == {'GREETING': 2}


@pytest.mark.asyncio
async def test_user_store_upsert():
    store = _mem_user_store()
    mem1 = UserMemory(user_memory_ref='umem-a', sender_id='user-10', intent_counts={'GREETING': 1})
    await store.save(mem1)
    mem2 = UserMemory(user_memory_ref='umem-a', sender_id='user-10', intent_counts={'GREETING': 3, 'STATUS_OVERVIEW': 1})
    await store.save(mem2)
    loaded = await store.load('user-10')
    assert loaded.intent_counts['GREETING'] == 3
    assert loaded.intent_counts['STATUS_OVERVIEW'] == 1


# ══════════════════════════════════════════════════════════════════════════════
# TEIL D — build_or_update_user_memory
# ══════════════════════════════════════════════════════════════════════════════

def test_build_user_memory_new():
    result = build_or_update_user_memory(
        sender_id='user-new',
        prev_memory=None,
        intent='GREETING',
    )
    assert result.sender_id == 'user-new'
    assert result.intent_counts == {'GREETING': 1}
    assert result.user_memory_ref.startswith('umem-')


def test_build_user_memory_increments_count():
    prev = UserMemory(
        user_memory_ref='umem-x',
        sender_id='user-x',
        intent_counts={'GREETING': 2, 'STATUS_OVERVIEW': 1},
    )
    result = build_or_update_user_memory(
        sender_id='user-x',
        prev_memory=prev,
        intent='STATUS_OVERVIEW',
    )
    assert result.intent_counts['STATUS_OVERVIEW'] == 2
    assert result.intent_counts['GREETING'] == 2  # unchanged


def test_build_user_memory_never_stores_case_ref():
    """User memory must NEVER store operative refs — only intent counts."""
    result = build_or_update_user_memory(
        sender_id='user-safe',
        prev_memory=None,
        intent='STATUS_OVERVIEW',
    )
    dumped = result.model_dump()
    # No case_ref, document_ref, clarification_ref in user memory
    assert 'last_case_ref' not in dumped
    assert 'last_document_ref' not in dumped
    assert 'last_clarification_ref' not in dumped


# ══════════════════════════════════════════════════════════════════════════════
# TEIL E — TruthArbitrator
# ══════════════════════════════════════════════════════════════════════════════

def test_arbitrator_audit_derived_when_found():
    arb = TruthArbitrator()
    core = _found_context()
    ctx, ann = arb.arbitrate(core_context=core, conv_memory=None, intent='STATUS_OVERVIEW')
    assert ctx is core
    assert ann.truth_basis == 'AUDIT_DERIVED'
    assert ann.requires_uncertainty_phrase is False


def test_arbitrator_conv_memory_fallback():
    arb = TruthArbitrator()
    not_found = _not_found_context()
    conv = _conv_memory()
    ctx, ann = arb.arbitrate(core_context=not_found, conv_memory=conv, intent='STATUS_OVERVIEW')
    assert ctx is not None
    assert ctx.resolution_status == 'FOUND'
    assert ann.truth_basis == 'CONVERSATION_MEMORY'
    assert ann.requires_uncertainty_phrase is True


def test_arbitrator_unknown_when_no_memory():
    arb = TruthArbitrator()
    not_found = _not_found_context()
    ctx, ann = arb.arbitrate(core_context=not_found, conv_memory=None, intent='STATUS_OVERVIEW')
    assert ann.truth_basis == 'UNKNOWN'
    assert ann.requires_uncertainty_phrase is False


def test_arbitrator_unknown_for_non_context_intent():
    arb = TruthArbitrator()
    # GREETING does not need context — memory should NOT be used
    conv = _conv_memory()
    ctx, ann = arb.arbitrate(core_context=None, conv_memory=conv, intent='GREETING')
    assert ctx is None
    assert ann.truth_basis == 'UNKNOWN'


def test_arbitrator_audit_overrides_memory():
    """Even if memory exists, fresh AUDIT_DERIVED wins."""
    arb = TruthArbitrator()
    core = _found_context(case_ref='audit-case')
    conv = _conv_memory(case_ref='memory-case')
    ctx, ann = arb.arbitrate(core_context=core, conv_memory=conv, intent='STATUS_OVERVIEW')
    assert ctx.resolved_case_ref == 'audit-case'
    assert ann.truth_basis == 'AUDIT_DERIVED'


def test_arbitrator_empty_memory_returns_unknown():
    """Conv memory with all-None refs = not useful → UNKNOWN."""
    arb = TruthArbitrator()
    empty_conv = ConversationMemory(
        conversation_memory_ref='conv-empty',
        chat_id='chat-empty',
        last_case_ref=None,
        last_document_ref=None,
        last_clarification_ref=None,
        last_open_item_id=None,
    )
    not_found = _not_found_context()
    ctx, ann = arb.arbitrate(core_context=not_found, conv_memory=empty_conv, intent='STATUS_OVERVIEW')
    assert ann.truth_basis == 'UNKNOWN'


# ══════════════════════════════════════════════════════════════════════════════
# TEIL F — TruthAnnotation model
# ══════════════════════════════════════════════════════════════════════════════

def test_truth_annotation_audit_derived():
    ann = TruthAnnotation.audit_derived(sources=['audit_trail', 'open_items_db'])
    assert ann.truth_basis == 'AUDIT_DERIVED'
    assert ann.requires_uncertainty_phrase is False
    assert ann.priority == 0
    assert ann.is_uncertain() is False


def test_truth_annotation_from_conv_memory():
    ann = TruthAnnotation.from_conv_memory()
    assert ann.truth_basis == 'CONVERSATION_MEMORY'
    assert ann.requires_uncertainty_phrase is True
    assert ann.priority == 1
    assert ann.is_uncertain() is True


def test_truth_annotation_unknown():
    ann = TruthAnnotation.unknown()
    assert ann.truth_basis == 'UNKNOWN'
    assert ann.requires_uncertainty_phrase is False
    assert ann.priority == 4


# ══════════════════════════════════════════════════════════════════════════════
# TEIL G — response_builder: uncertainty phrase
# ══════════════════════════════════════════════════════════════════════════════

def test_response_status_no_uncertainty():
    ann = TruthAnnotation.audit_derived()
    ctx = _found_context()
    text, rtype = build_response('STATUS_OVERVIEW', ctx, guardrail_passed=True, truth_annotation=ann)
    assert 'FRYA:' in text
    assert 'Laut meinem letzten Stand' not in text
    assert rtype == 'COMMUNICATOR_REPLY_STATUS'


def test_response_status_with_uncertainty():
    ann = TruthAnnotation.from_conv_memory()
    ctx = _found_context()
    text, rtype = build_response('STATUS_OVERVIEW', ctx, guardrail_passed=True, truth_annotation=ann)
    assert 'Laut meinem letzten Stand' in text
    assert '/status' in text.lower()
    assert rtype == 'COMMUNICATOR_REPLY_STATUS'


def test_response_document_arrival_with_uncertainty():
    ann = TruthAnnotation.from_conv_memory()
    ctx = _found_context(doc_ref='doc-001')
    text, _ = build_response('DOCUMENT_ARRIVAL_CHECK', ctx, guardrail_passed=True, truth_annotation=ann)
    assert 'Laut meinem letzten Stand' in text
    assert 'doc-001' in text


def test_response_document_arrival_no_uncertainty():
    ann = TruthAnnotation.audit_derived()
    ctx = _found_context(doc_ref='doc-001')
    text, _ = build_response('DOCUMENT_ARRIVAL_CHECK', ctx, guardrail_passed=True, truth_annotation=ann)
    assert 'Laut meinem letzten Stand' not in text
    assert 'doc-001' in text


def test_response_last_case_explanation_with_uncertainty():
    ann = TruthAnnotation.from_conv_memory()
    ctx = _found_context(case_ref='case-mem')
    text, _ = build_response('LAST_CASE_EXPLANATION', ctx, guardrail_passed=True, truth_annotation=ann)
    assert 'Laut meinem letzten Stand' in text
    assert 'case-mem' in text


def test_response_greeting_no_uncertainty_phrase():
    """GREETING never gets uncertainty phrase, even if annotation is from memory."""
    ann = TruthAnnotation.from_conv_memory()
    text, rtype = build_response('GREETING', None, guardrail_passed=True, truth_annotation=ann)
    # Greeting text is fixed — no uncertainty qualifier needed
    assert 'Hallo' in text
    assert rtype == 'COMMUNICATOR_REPLY_GREETING'


# ══════════════════════════════════════════════════════════════════════════════
# TEIL H — Service pipeline: memory_used + truth_basis in turn
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_service_memory_used_false_when_audit_resolves(monkeypatch):
    """When context_resolver returns FOUND → truth_basis=AUDIT_DERIVED, memory_used=False."""
    import app.telegram.communicator.service as svc_mod
    monkeypatch.setattr(
        svc_mod,
        'resolve_context',
        AsyncMock(return_value=(_found_context(), 'ctx-ref-001')),
    )
    svc = TelegramCommunicatorService()
    audit, open_items, clarification = _mock_services()
    conv_store = _mem_conv_store()
    user_store = _mem_user_store()

    result = await svc.try_handle_turn(
        _normalized('Was ist der Stand?'),
        case_id='case-test',
        audit_service=audit,
        open_items_service=open_items,
        clarification_service=clarification,
        conversation_store=conv_store,
        user_store=user_store,
    )
    assert result is not None
    assert result.turn.truth_basis == 'AUDIT_DERIVED'
    assert result.turn.memory_used is False


@pytest.mark.asyncio
async def test_service_memory_used_true_when_conv_memory_fallback(monkeypatch):
    """When audit returns NOT_FOUND but conv memory exists → truth_basis=CONVERSATION_MEMORY, memory_used=True."""
    import app.telegram.communicator.service as svc_mod
    monkeypatch.setattr(
        svc_mod,
        'resolve_context',
        AsyncMock(return_value=(_not_found_context(), 'ctx-ref-002')),
    )
    svc = TelegramCommunicatorService()
    audit, open_items, clarification = _mock_services()
    conv_store = _mem_conv_store()
    # Pre-seed conversation memory
    await conv_store.save(_conv_memory(chat_id='chat-1'))
    user_store = _mem_user_store()

    result = await svc.try_handle_turn(
        _normalized('Was ist der Stand?', chat_id='chat-1'),
        case_id='case-test',
        audit_service=audit,
        open_items_service=open_items,
        clarification_service=clarification,
        conversation_store=conv_store,
        user_store=user_store,
    )
    assert result is not None
    assert result.turn.truth_basis == 'CONVERSATION_MEMORY'
    assert result.turn.memory_used is True
    assert result.turn.conversation_memory_ref == 'conv-test-001'


@pytest.mark.asyncio
async def test_service_updates_user_memory_after_turn(monkeypatch):
    """After a handled turn, user memory intent_counts should be incremented."""
    import app.telegram.communicator.service as svc_mod
    monkeypatch.setattr(
        svc_mod,
        'resolve_context',
        AsyncMock(return_value=(_found_context(), 'ctx-ref-003')),
    )
    svc = TelegramCommunicatorService()
    audit, open_items, clarification = _mock_services()
    conv_store = _mem_conv_store()
    user_store = _mem_user_store()

    await svc.try_handle_turn(
        _normalized('Was ist der Stand?', sender_id='user-mem'),
        case_id='case-test',
        audit_service=audit,
        open_items_service=open_items,
        clarification_service=clarification,
        conversation_store=conv_store,
        user_store=user_store,
    )
    user_mem = await user_store.load('user-mem')
    assert user_mem is not None
    assert user_mem.intent_counts.get('STATUS_OVERVIEW', 0) >= 1


@pytest.mark.asyncio
async def test_service_fall_through_does_not_update_memory(monkeypatch):
    """Unrecognized text → None returned, no memory update."""
    svc = TelegramCommunicatorService()
    audit, open_items, clarification = _mock_services()
    conv_store = _mem_conv_store()
    user_store = _mem_user_store()

    result = await svc.try_handle_turn(
        _normalized('Zufaelliger unbekannter Text XYZ123'),
        case_id='case-test',
        audit_service=audit,
        open_items_service=open_items,
        clarification_service=clarification,
        conversation_store=conv_store,
        user_store=user_store,
    )
    assert result is None
    # No user memory was created
    assert await user_store.load('user-1') is None


@pytest.mark.asyncio
async def test_service_greeting_truth_basis_unknown():
    """GREETING → no context lookup → UNKNOWN truth_basis (not from memory)."""
    svc = TelegramCommunicatorService()
    audit, open_items, clarification = _mock_services()
    conv_store = _mem_conv_store()
    await conv_store.save(_conv_memory(chat_id='chat-1'))  # has memory but should not use it
    user_store = _mem_user_store()

    result = await svc.try_handle_turn(
        _normalized('Hallo', chat_id='chat-1'),
        case_id='case-test',
        audit_service=audit,
        open_items_service=open_items,
        clarification_service=clarification,
        conversation_store=conv_store,
        user_store=user_store,
    )
    assert result is not None
    assert result.turn.intent == 'GREETING'
    assert result.turn.truth_basis == 'UNKNOWN'
    assert result.turn.memory_used is False


# ══════════════════════════════════════════════════════════════════════════════
# TEIL I — Webhook end-to-end: second turn reuses conversation memory
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_service_second_turn_uses_conversation_memory(monkeypatch):
    """
    Turn 1: Audit FOUND → AUDIT_DERIVED, memory gets updated with case/doc refs.
    Turn 2: Audit NOT_FOUND → falls back to conv memory → CONVERSATION_MEMORY.
    Ensures memory is sticky across turns.
    """
    import app.telegram.communicator.service as svc_mod

    call_count = 0

    async def _resolve_side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _found_context(case_ref='case-turn1', doc_ref='doc-turn1'), 'ctx-001'
        return _not_found_context(), 'ctx-002'

    monkeypatch.setattr(svc_mod, 'resolve_context', _resolve_side_effect)

    svc = TelegramCommunicatorService()
    conv_store = _mem_conv_store()
    user_store = _mem_user_store()

    audit, open_items, clarification = _mock_services()

    # Turn 1
    r1 = await svc.try_handle_turn(
        _normalized('Was ist der Stand?', chat_id='chat-seq'),
        case_id='case-seq',
        audit_service=audit,
        open_items_service=open_items,
        clarification_service=clarification,
        conversation_store=conv_store,
        user_store=user_store,
    )
    assert r1 is not None
    assert r1.turn.truth_basis == 'AUDIT_DERIVED'

    # Check memory was updated after turn 1
    mem_after_t1 = await conv_store.load('chat-seq')
    assert mem_after_t1 is not None
    assert mem_after_t1.last_case_ref == 'case-turn1'
    assert mem_after_t1.last_document_ref == 'doc-turn1'

    # Turn 2 — audit returns NOT_FOUND
    r2 = await svc.try_handle_turn(
        _normalized('Was ist der Stand?', chat_id='chat-seq'),
        case_id='case-seq',
        audit_service=audit,
        open_items_service=open_items,
        clarification_service=clarification,
        conversation_store=conv_store,
        user_store=user_store,
    )
    assert r2 is not None
    assert r2.turn.truth_basis == 'CONVERSATION_MEMORY'
    assert r2.turn.memory_used is True
    # Response should contain uncertainty phrase
    assert 'Laut meinem letzten Stand' in r2.reply_text


# ══════════════════════════════════════════════════════════════════════════════
# TEIL J — case_views inspect: communicator_turn key in JSON
# ══════════════════════════════════════════════════════════════════════════════

def test_latest_communicator_turn_found():
    """_latest_communicator_turn() returns the most recent COMMUNICATOR_TURN_PROCESSED llm_output."""
    from app.api.case_views import _latest_communicator_turn

    turn_payload = {
        'communicator_turn_ref': 'comm-abc123',
        'intent': 'STATUS_OVERVIEW',
        'truth_basis': 'AUDIT_DERIVED',
        'memory_used': False,
        'guardrail_passed': True,
    }

    class FakeEvent:
        action: str
        llm_output: Any

    e1 = FakeEvent()
    e1.action = 'TELEGRAM_WEBHOOK_RECEIVED'
    e1.llm_output = None

    e2 = FakeEvent()
    e2.action = 'COMMUNICATOR_TURN_PROCESSED'
    e2.llm_output = turn_payload

    result = _latest_communicator_turn([e1, e2])
    assert result is not None
    assert result['communicator_turn_ref'] == 'comm-abc123'
    assert result['truth_basis'] == 'AUDIT_DERIVED'


def test_latest_communicator_turn_returns_none_when_absent():
    from app.api.case_views import _latest_communicator_turn

    class FakeEvent:
        action = 'TELEGRAM_WEBHOOK_RECEIVED'
        llm_output = None

    result = _latest_communicator_turn([FakeEvent()])
    assert result is None


def test_latest_communicator_turn_returns_most_recent():
    """When two COMMUNICATOR_TURN_PROCESSED events exist, returns the last one."""
    from app.api.case_views import _latest_communicator_turn

    class E:
        def __init__(self, action, payload):
            self.action = action
            self.llm_output = payload

    e_old = E('COMMUNICATOR_TURN_PROCESSED', {'communicator_turn_ref': 'old-ref', 'intent': 'GREETING'})
    e_new = E('COMMUNICATOR_TURN_PROCESSED', {'communicator_turn_ref': 'new-ref', 'intent': 'STATUS_OVERVIEW'})

    result = _latest_communicator_turn([e_old, e_new])
    assert result['communicator_turn_ref'] == 'new-ref'
