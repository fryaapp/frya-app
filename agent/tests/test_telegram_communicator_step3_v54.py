"""Kommunikator STEP 3/4 tests — natural context, truth, guardrails, memory visibility.

Coverage (28 tests):
  TEIL A: Context resolver — open_item_state/title/clarification_question / AMBIGUOUS
  TEIL B: Response builder — NEEDS_FROM_USER with WAITING_USER/WAITING_DATA states
  TEIL C: Response builder — STATUS_OVERVIEW with clarification question surfaced
  TEIL D: Response builder — DOCUMENT_ARRIVAL_CHECK honest variants
  TEIL E: Response builder — LAST_CASE_EXPLANATION with open item context
  TEIL F: Intent classifier — new risky patterns (cross-case / file-send)
  TEIL G: Intent classifier — new natural-language phrases
  TEIL H: Service pipeline — memory_types_used populated correctly
  TEIL I: Guardrail — no case leaks, AMBIGUOUS handled safely
  TEIL J: Truth arbitration — core always overrides memory
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.telegram.communicator.context_resolver import resolve_context
from app.telegram.communicator.guardrail import check_guardrail
from app.telegram.communicator.intent_classifier import classify_intent
from app.telegram.communicator.memory.conversation_store import ConversationMemoryStore
from app.telegram.communicator.memory.models import ConversationMemory, TruthAnnotation
from app.telegram.communicator.memory.user_store import UserMemoryStore
from app.telegram.communicator.models import CommunicatorContextResolution
from app.telegram.communicator.response_builder import build_response
from app.telegram.communicator.service import TelegramCommunicatorService
from app.telegram.models import TelegramActor, TelegramNormalizedIngressMessage
import uuid


# ── Helpers ──────────────────────────────────────────────────────────────────

def _ctx(
    *,
    status='FOUND',
    case_ref='case-abc',
    doc_ref=None,
    clar_ref=None,
    clar_question=None,
    item_id=None,
    item_state=None,
    item_title=None,
    multiple=False,
) -> CommunicatorContextResolution:
    return CommunicatorContextResolution(
        resolution_status=status,
        resolved_case_ref=case_ref,
        resolved_document_ref=doc_ref,
        resolved_clarification_ref=clar_ref,
        resolved_open_item_id=item_id,
        context_reason='Unit test',
        open_item_state=item_state,
        open_item_title=item_title,
        clarification_question=clar_question,
        has_multiple_open_items=multiple,
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


def _mock_svc():
    audit = AsyncMock()
    audit.log_event = AsyncMock(return_value=None)
    open_items = AsyncMock()
    clarification = AsyncMock()
    return audit, open_items, clarification


# ══════════════════════════════════════════════════════════════════════════════
# TEIL A — Context resolver: richer context fields
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_context_resolver_pulls_item_state_waiting_user():
    """open_item_state=WAITING_USER is pulled from open items service."""
    item = MagicMock()
    item.item_id = 'item-001'
    item.status = 'WAITING_USER'
    item.title = 'Kontoauszug nachreichen'
    item.description = 'Bitte sende uns den Kontoauszug.'

    audit = AsyncMock()
    audit.by_case = AsyncMock(return_value=[])
    clar = AsyncMock()
    clar.latest_by_case = AsyncMock(return_value=None)
    oi = AsyncMock()
    oi.list_by_case = AsyncMock(return_value=[item])

    ctx, ref = await resolve_context(
        'case-test',
        audit_service=audit,
        clarification_service=clar,
        open_items_service=oi,
    )
    assert ctx.resolution_status == 'FOUND'
    assert ctx.open_item_state == 'WAITING_USER'
    assert ctx.open_item_title == 'Kontoauszug nachreichen'
    assert ctx.resolved_open_item_id == 'item-001'
    assert ref.startswith('ctx-')


@pytest.mark.asyncio
async def test_context_resolver_pulls_clarification_question():
    """clarification_question is extracted from the open clarification record."""
    clar_record = MagicMock()
    clar_record.clarification_ref = 'clar-xyz'
    clar_record.clarification_state = 'OPEN'
    clar_record.question_text = 'Bitte sende uns deine Steuer-ID.'

    audit = AsyncMock()
    audit.by_case = AsyncMock(return_value=[])
    clar = AsyncMock()
    clar.latest_by_case = AsyncMock(return_value=clar_record)
    oi = AsyncMock()
    oi.list_by_case = AsyncMock(return_value=[])

    ctx, _ = await resolve_context(
        'case-q',
        audit_service=audit,
        clarification_service=clar,
        open_items_service=oi,
    )
    assert ctx.resolution_status == 'FOUND'
    assert ctx.clarification_question == 'Bitte sende uns deine Steuer-ID.'
    assert ctx.resolved_clarification_ref == 'clar-xyz'


@pytest.mark.asyncio
async def test_context_resolver_ambiguous_when_multiple_items():
    """AMBIGUOUS when 2+ active open items."""
    def _item(iid, status):
        m = MagicMock()
        m.item_id = iid
        m.status = status
        m.title = f'Title {iid}'
        m.description = ''
        return m

    audit = AsyncMock()
    audit.by_case = AsyncMock(return_value=[])
    clar = AsyncMock()
    clar.latest_by_case = AsyncMock(return_value=None)
    oi = AsyncMock()
    oi.list_by_case = AsyncMock(return_value=[
        _item('item-a', 'WAITING_USER'),
        _item('item-b', 'WAITING_DATA'),
    ])

    ctx, _ = await resolve_context(
        'case-amb',
        audit_service=audit,
        clarification_service=clar,
        open_items_service=oi,
    )
    assert ctx.resolution_status == 'AMBIGUOUS'
    assert ctx.has_multiple_open_items is True
    assert ctx.resolved_open_item_id == 'item-a'  # first one, conservative


@pytest.mark.asyncio
async def test_context_resolver_not_found_when_nothing():
    """NOT_FOUND when no doc, no clar, no open items."""
    audit = AsyncMock()
    audit.by_case = AsyncMock(return_value=[])
    clar = AsyncMock()
    clar.latest_by_case = AsyncMock(return_value=None)
    oi = AsyncMock()
    oi.list_by_case = AsyncMock(return_value=[])

    ctx, _ = await resolve_context(
        'case-empty',
        audit_service=audit,
        clarification_service=clar,
        open_items_service=oi,
    )
    assert ctx.resolution_status == 'NOT_FOUND'
    assert ctx.resolved_case_ref is None


@pytest.mark.asyncio
async def test_context_resolver_truncates_long_clarification_question():
    """clarification_question is truncated to 200 chars to avoid operator leaks."""
    long_q = 'X' * 300
    clar_record = MagicMock()
    clar_record.clarification_ref = 'clar-long'
    clar_record.clarification_state = 'OPEN'
    clar_record.question_text = long_q

    audit = AsyncMock()
    audit.by_case = AsyncMock(return_value=[])
    clar = AsyncMock()
    clar.latest_by_case = AsyncMock(return_value=clar_record)
    oi = AsyncMock()
    oi.list_by_case = AsyncMock(return_value=[])

    ctx, _ = await resolve_context(
        'case-q',
        audit_service=audit,
        clarification_service=clar,
        open_items_service=oi,
    )
    assert ctx.clarification_question is not None
    assert len(ctx.clarification_question) <= 200


# ══════════════════════════════════════════════════════════════════════════════
# TEIL B — response_builder: NEEDS_FROM_USER natural states
# ══════════════════════════════════════════════════════════════════════════════

def test_needs_waiting_user_with_title():
    ctx = _ctx(item_id='item-1', item_state='WAITING_USER', item_title='Personalausweis')
    text, rtype = build_response('NEEDS_FROM_USER', ctx, guardrail_passed=True)
    assert 'warten' in text.lower() or 'angabe' in text.lower()
    assert 'Personalausweis' in text
    assert rtype == 'COMMUNICATOR_REPLY_NEEDS'


def test_needs_waiting_data_with_title():
    ctx = _ctx(item_id='item-2', item_state='WAITING_DATA', item_title='Kontoauszug letzter Monat')
    text, rtype = build_response('NEEDS_FROM_USER', ctx, guardrail_passed=True)
    assert 'unterlagen' in text.lower() or 'warten' in text.lower()
    assert 'Kontoauszug' in text
    assert rtype == 'COMMUNICATOR_REPLY_NEEDS'


def test_needs_waiting_user_no_title():
    ctx = _ctx(item_id='item-3', item_state='WAITING_USER', item_title=None)
    text, rtype = build_response('NEEDS_FROM_USER', ctx, guardrail_passed=True)
    assert 'angabe' in text.lower() or 'warten' in text.lower()
    assert rtype == 'COMMUNICATOR_REPLY_NEEDS'


def test_needs_with_clarification_question():
    ctx = _ctx(
        clar_ref='clar-1',
        clar_question='Bitte sende uns deine Steuer-ID.',
    )
    text, _ = build_response('NEEDS_FROM_USER', ctx, guardrail_passed=True)
    assert 'Steuer-ID' in text
    assert 'Rueckfrage' in text or 'rueckfrage' in text.lower()


def test_needs_no_context_honest_answer():
    text, rtype = build_response('NEEDS_FROM_USER', None, guardrail_passed=True)
    assert 'nichts' in text.lower()
    assert rtype == 'COMMUNICATOR_REPLY_NEEDS'


def test_needs_ambiguous_includes_note():
    ctx = _ctx(
        status='AMBIGUOUS',
        item_id='item-a',
        item_state='WAITING_USER',
        item_title='Rechnung',
        multiple=True,
    )
    text, _ = build_response('NEEDS_FROM_USER', ctx, guardrail_passed=True)
    assert 'Rechnung' in text
    # Conservative: mentions multiple open points
    assert 'weitere' in text.lower()


# ══════════════════════════════════════════════════════════════════════════════
# TEIL C — response_builder: STATUS_OVERVIEW with clarification surfaced
# ══════════════════════════════════════════════════════════════════════════════

def test_status_with_clarification_question_in_response():
    ctx = _ctx(
        clar_ref='clar-1',
        clar_question='Ist das Dokument vollstaendig?',
    )
    text, rtype = build_response('STATUS_OVERVIEW', ctx, guardrail_passed=True)
    assert 'Ist das Dokument vollstaendig?' in text
    assert rtype == 'COMMUNICATOR_REPLY_STATUS'


def test_status_with_open_item_state_in_response():
    ctx = _ctx(item_id='item-x', item_state='WAITING_DATA', item_title='Einkommensnachweis')
    text, _ = build_response('STATUS_OVERVIEW', ctx, guardrail_passed=True)
    assert 'Einkommensnachweis' in text


def test_status_not_found_honest():
    text, rtype = build_response('STATUS_OVERVIEW', None, guardrail_passed=True)
    assert 'keinen' in text.lower()
    assert rtype == 'COMMUNICATOR_REPLY_STATUS'


def test_status_uncertainty_phrase_included_when_memory():
    ann = TruthAnnotation.from_conv_memory()
    ctx = _ctx(doc_ref='doc-001')
    text, _ = build_response('STATUS_OVERVIEW', ctx, guardrail_passed=True, truth_annotation=ann)
    assert 'Laut meinem letzten Stand' in text
    assert '/status' in text


# ══════════════════════════════════════════════════════════════════════════════
# TEIL D — response_builder: DOCUMENT_ARRIVAL_CHECK
# ══════════════════════════════════════════════════════════════════════════════

def test_doc_arrival_found_natural():
    ctx = _ctx(doc_ref='doc-abc123')
    text, rtype = build_response('DOCUMENT_ARRIVAL_CHECK', ctx, guardrail_passed=True)
    assert 'doc-abc123' in text
    assert 'angekommen' in text.lower()
    assert 'Laut meinem letzten Stand' not in text
    assert rtype == 'COMMUNICATOR_REPLY_EXPLANATION'


def test_doc_arrival_no_doc_but_case_found():
    ctx = _ctx(doc_ref=None)  # case found, no doc
    text, rtype = build_response('DOCUMENT_ARRIVAL_CHECK', ctx, guardrail_passed=True)
    assert 'noch kein' in text.lower() or 'noch keinen' in text.lower()
    assert rtype == 'COMMUNICATOR_REPLY_EXPLANATION'


def test_doc_arrival_null_context():
    text, rtype = build_response('DOCUMENT_ARRIVAL_CHECK', None, guardrail_passed=True)
    assert 'noch keinen' in text.lower() or 'noch kein' in text.lower()
    assert rtype == 'COMMUNICATOR_REPLY_EXPLANATION'


def test_doc_arrival_uncertainty_when_memory():
    ann = TruthAnnotation.from_conv_memory()
    ctx = _ctx(doc_ref='doc-mem')
    text, _ = build_response('DOCUMENT_ARRIVAL_CHECK', ctx, guardrail_passed=True, truth_annotation=ann)
    assert 'Laut meinem letzten Stand' in text
    assert 'doc-mem' in text


# ══════════════════════════════════════════════════════════════════════════════
# TEIL E — response_builder: LAST_CASE_EXPLANATION with context
# ══════════════════════════════════════════════════════════════════════════════

def test_last_case_with_open_item_context():
    ctx = _ctx(
        case_ref='case-xyz',
        item_id='item-1',
        item_state='WAITING_DATA',
        item_title='Lohnsteuerbescheinigung',
    )
    text, rtype = build_response('LAST_CASE_EXPLANATION', ctx, guardrail_passed=True)
    assert 'case-xyz' in text
    assert 'Lohnsteuerbescheinigung' in text
    assert rtype == 'COMMUNICATOR_REPLY_EXPLANATION'


def test_last_case_with_clarification_question():
    ctx = _ctx(
        case_ref='case-q',
        clar_ref='clar-1',
        clar_question='Welches Konto soll verwendet werden?',
    )
    text, _ = build_response('LAST_CASE_EXPLANATION', ctx, guardrail_passed=True)
    assert 'Welches Konto soll verwendet werden?' in text


def test_last_case_no_context():
    text, rtype = build_response('LAST_CASE_EXPLANATION', None, guardrail_passed=True)
    assert 'keinen' in text.lower()
    assert rtype == 'COMMUNICATOR_REPLY_EXPLANATION'


# ══════════════════════════════════════════════════════════════════════════════
# TEIL F — intent_classifier: new risky patterns
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize('text', [
    'Zeig mir alle Faelle',
    'Zeig mir alle Vorgaenge',
    'Schick mir das Dokument',
    'Schick mir die Datei',
    'Liste alle Faelle',
    'Liste aller Vorgaenge',
    'zeig mir alle meine dateien',
])
def test_risky_cross_case_patterns(text):
    """Cross-case navigation and file-send attempts → UNSUPPORTED_OR_RISKY."""
    result = classify_intent(text)
    assert result == 'UNSUPPORTED_OR_RISKY', f'Expected UNSUPPORTED_OR_RISKY for: {text!r}, got {result!r}'


def test_risky_guardrail_blocks_cross_case():
    """UNSUPPORTED_OR_RISKY → guardrail fails → safe limit response."""
    passed, reason = check_guardrail('UNSUPPORTED_OR_RISKY')
    assert passed is False
    assert reason is not None


# ══════════════════════════════════════════════════════════════════════════════
# TEIL G — intent_classifier: new natural phrases
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize('text,expected_intent', [
    ('Mein letzter Eingang', 'STATUS_OVERVIEW'),
    ('Was ist mit meinem Fall?', 'STATUS_OVERVIEW'),
    ('Was ist der naechste Schritt?', 'NEEDS_FROM_USER'),
    ('Was erwartet ihr noch von mir?', 'NEEDS_FROM_USER'),
    ('Was wird bei mir bearbeitet?', 'LAST_CASE_EXPLANATION'),
])
def test_new_natural_phrases(text, expected_intent):
    result = classify_intent(text)
    assert result == expected_intent, f'{text!r}: expected {expected_intent!r}, got {result!r}'


# ══════════════════════════════════════════════════════════════════════════════
# TEIL H — service: memory_types_used populated correctly
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_service_memory_types_conv_memory_used(monkeypatch):
    """When audit NOT_FOUND and conv memory contributes → memory_types_used=['conversation_memory', 'user_memory']."""
    import app.telegram.communicator.service as svc_mod

    not_found = CommunicatorContextResolution(
        resolution_status='NOT_FOUND', context_reason='nope'
    )
    monkeypatch.setattr(svc_mod, 'resolve_context', AsyncMock(return_value=(not_found, 'ctx-001')))

    conv_store = ConversationMemoryStore('memory://test')
    await conv_store.save(ConversationMemory(
        conversation_memory_ref='conv-001',
        chat_id='chat-1',
        last_case_ref='case-old',
        last_document_ref=None,
    ))
    user_store = UserMemoryStore('memory://test')
    audit, open_items, clar = _mock_svc()

    svc = TelegramCommunicatorService()
    result = await svc.try_handle_turn(
        _normalized('Was ist der Stand?', chat_id='chat-1'),
        case_id='case-test',
        audit_service=audit,
        open_items_service=open_items,
        clarification_service=clar,
        conversation_store=conv_store,
        user_store=user_store,
    )
    assert result is not None
    assert 'conversation_memory' in result.turn.memory_types_used
    assert 'user_memory' in result.turn.memory_types_used


@pytest.mark.asyncio
async def test_service_memory_types_empty_when_audit_resolves(monkeypatch):
    """When audit FOUND → memory_types_used does NOT include conversation_memory."""
    import app.telegram.communicator.service as svc_mod

    found = CommunicatorContextResolution(
        resolution_status='FOUND',
        resolved_case_ref='case-fresh',
        context_reason='found',
    )
    monkeypatch.setattr(svc_mod, 'resolve_context', AsyncMock(return_value=(found, 'ctx-002')))

    conv_store = ConversationMemoryStore('memory://test')
    user_store = UserMemoryStore('memory://test')
    audit, open_items, clar = _mock_svc()

    svc = TelegramCommunicatorService()
    result = await svc.try_handle_turn(
        _normalized('Was ist der Stand?'),
        case_id='case-test',
        audit_service=audit,
        open_items_service=open_items,
        clarification_service=clar,
        conversation_store=conv_store,
        user_store=user_store,
    )
    assert result is not None
    assert 'conversation_memory' not in result.turn.memory_types_used
    assert result.turn.truth_basis == 'AUDIT_DERIVED'


# ══════════════════════════════════════════════════════════════════════════════
# TEIL I — No case leaks / AMBIGUOUS handled safely
# ══════════════════════════════════════════════════════════════════════════════

def test_response_does_not_leak_operator_field_names():
    """Internal field names (item_id, clarification_ref, etc.) must not appear in response."""
    ctx = _ctx(
        doc_ref='doc-001',
        clar_ref='clar-abc',
        clar_question='Bitte Ausweis?',
        item_id='item-xyz',
        item_state='WAITING_USER',
        item_title='Ausweis',
    )
    text, _ = build_response('STATUS_OVERVIEW', ctx, guardrail_passed=True)
    # Internal ref names must NOT be in the user-facing text
    assert 'clarification_ref' not in text
    assert 'open_item_id' not in text
    assert 'item_id' not in text


def test_ambiguous_context_resolves_without_error():
    """AMBIGUOUS resolution must produce a safe, non-crashing response."""
    ctx = _ctx(
        status='AMBIGUOUS',
        doc_ref=None,
        item_id='item-1',
        item_state='WAITING_USER',
        item_title='Mietvertrag',
        multiple=True,
    )
    text, rtype = build_response('STATUS_OVERVIEW', ctx, guardrail_passed=True)
    assert 'FRYA:' in text
    assert rtype == 'COMMUNICATOR_REPLY_STATUS'
    # Mentions the multiple-items note
    assert 'weitere' in text.lower()


def test_risky_response_never_leaks_case_ref():
    """UNSUPPORTED_OR_RISKY response must not contain case refs or internal IDs."""
    text, rtype = build_response(
        'UNSUPPORTED_OR_RISKY',
        _ctx(case_ref='case-secret'),
        guardrail_passed=False,
    )
    assert 'case-secret' not in text
    assert rtype == 'COMMUNICATOR_REPLY_SAFE_LIMIT'
