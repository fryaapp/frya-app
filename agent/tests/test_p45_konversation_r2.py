"""Tests for P-45: Konversations-Intelligenz Runde 2."""
import pytest


def test_extract_case_ref_doc_26():
    from app.telegram.communicator.context_resolver import extract_case_ref_from_text
    assert extract_case_ref_from_text('doc 26') == 'doc-26'
    assert extract_case_ref_from_text('doc-26') == 'doc-26'
    assert extract_case_ref_from_text('Doc26') == 'doc-26'
    assert extract_case_ref_from_text('Was ist mit doc 26?') == 'doc-26'


def test_extract_case_ref_vorgang():
    from app.telegram.communicator.context_resolver import extract_case_ref_from_text
    assert extract_case_ref_from_text('Vorgang 26') == 'doc-26'
    assert extract_case_ref_from_text('Fall 26') == 'doc-26'


def test_extract_case_ref_none():
    from app.telegram.communicator.context_resolver import extract_case_ref_from_text
    assert extract_case_ref_from_text('Hallo Frya') is None
    assert extract_case_ref_from_text('') is None


def test_conversation_memory_has_search_ref():
    from app.telegram.communicator.memory.models import ConversationMemory
    mem = ConversationMemory(
        conversation_memory_ref='test', chat_id='123',
        last_case_ref='doc-25', last_search_ref='uuid-vendor-match',
    )
    assert mem.last_case_ref == 'doc-25'
    assert mem.last_search_ref == 'uuid-vendor-match'


def test_build_memory_search_flag():
    from app.telegram.communicator.memory.conversation_store import build_updated_conversation_memory
    from app.telegram.communicator.memory.models import ConversationMemory
    prev = ConversationMemory(
        conversation_memory_ref='test', chat_id='123',
        last_case_ref='doc-25',
    )
    updated = build_updated_conversation_memory(
        chat_id='123', prev_memory=prev, intent='GENERAL_CONVERSATION',
        resolved_case_ref='vendor-uuid', resolved_document_ref=None,
        resolved_clarification_ref=None, resolved_open_item_id=None,
        context_resolution_status='FOUND',
        is_search_result=True,
    )
    # Primary ref should be preserved
    assert updated.last_case_ref == 'doc-25'
    # Search ref should be set
    assert updated.last_search_ref == 'vendor-uuid'


def test_build_memory_non_search_updates_primary():
    from app.telegram.communicator.memory.conversation_store import build_updated_conversation_memory
    from app.telegram.communicator.memory.models import ConversationMemory
    prev = ConversationMemory(
        conversation_memory_ref='test', chat_id='123',
        last_case_ref='doc-25', last_search_ref='old-search',
    )
    updated = build_updated_conversation_memory(
        chat_id='123', prev_memory=prev, intent='STATUS_OVERVIEW',
        resolved_case_ref='doc-30', resolved_document_ref=None,
        resolved_clarification_ref=None, resolved_open_item_id=None,
        context_resolution_status='FOUND',
        is_search_result=False,
    )
    # Primary ref should be updated
    assert updated.last_case_ref == 'doc-30'
    # Search ref should be preserved from prev
    assert updated.last_search_ref == 'old-search'


def test_build_memory_not_found_preserves_all():
    from app.telegram.communicator.memory.conversation_store import build_updated_conversation_memory
    from app.telegram.communicator.memory.models import ConversationMemory
    prev = ConversationMemory(
        conversation_memory_ref='test', chat_id='123',
        last_case_ref='doc-25', last_search_ref='vendor-search-1',
    )
    updated = build_updated_conversation_memory(
        chat_id='123', prev_memory=prev, intent='GREETING',
        resolved_case_ref=None, resolved_document_ref=None,
        resolved_clarification_ref=None, resolved_open_item_id=None,
        context_resolution_status='NOT_FOUND',
    )
    assert updated.last_case_ref == 'doc-25'
    assert updated.last_search_ref == 'vendor-search-1'
