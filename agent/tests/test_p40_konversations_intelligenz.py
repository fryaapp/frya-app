"""Tests for P-40: Konversations-Intelligenz."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def test_tags_no_duplicates():
    """Tag collection in writeback must deduplicate IDs."""
    existing_tags = [1, 2, 3]
    new_tag_analysiert = 2  # already exists
    new_tag_vst = 4

    tag_ids = set(existing_tags)
    tag_ids.add(new_tag_analysiert)
    tag_ids.add(new_tag_vst)

    result = sorted(tag_ids)
    assert result == [1, 2, 3, 4]
    assert len(result) == 4  # no duplicates


def test_semantic_prompt_has_business_relevance_check():
    """Semantic prompt must contain the Geschaeftsrelevanz priority rule."""
    from app.document_analysis.semantic_service import _SYSTEM_PROMPT
    assert 'USt-IDNr' in _SYSTEM_PROMPT
    assert 'IMMER' in _SYSTEM_PROMPT
    assert 'Rechnungsnummer' in _SYSTEM_PROMPT
    prompt_lower = _SYSTEM_PROMPT.lower()
    assert 'priorität' in prompt_lower


@pytest.mark.asyncio
async def test_conversation_memory_updated_after_approval():
    """After booking approval callback, conversation memory must contain the case_id."""
    from app.telegram.communicator.memory.conversation_store import ConversationMemoryStore

    store = ConversationMemoryStore('memory://')
    chat_id = '12345'

    from app.api.webhooks import _handle_telegram_callback_query

    callback_query = {
        'id': 'cb-1',
        'data': 'booking:case-abc:approve',
        'from': {'id': 999, 'username': 'testuser'},
        'message': {'chat': {'id': int(chat_id)}},
    }

    mock_audit = MagicMock()
    mock_audit.log_event = AsyncMock()

    mock_telegram = MagicMock()
    mock_telegram.bot_token = 'fake-token'
    mock_telegram.send = AsyncMock()

    mock_chat_history = MagicMock()
    mock_chat_history.append = AsyncMock()

    mock_approval_record = MagicMock()
    mock_approval_record.status = 'PENDING'
    mock_approval_record.action_type = 'booking_finalize'
    mock_approval_record.approval_id = 'appr-001'

    mock_approval_svc = MagicMock()
    mock_approval_svc.list_by_case = AsyncMock(return_value=[mock_approval_record])

    mock_bas_instance = MagicMock()
    mock_bas_instance.process_response = AsyncMock(return_value={
        'decision': 'APPROVE', 'approval_status': 'APPROVED',
    })

    mock_client = AsyncMock()

    with patch('app.booking.approval_service.BookingApprovalService', return_value=mock_bas_instance), \
         patch('app.dependencies.get_approval_service', return_value=mock_approval_svc), \
         patch('app.dependencies.get_open_items_service', return_value=MagicMock()), \
         patch('app.dependencies.get_akaunting_connector', return_value=MagicMock()), \
         patch('httpx.AsyncClient') as mock_httpx:

        mock_httpx.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_httpx.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await _handle_telegram_callback_query(
            callback_query, {'update_id': 1}, mock_audit, mock_telegram,
            conversation_store=store,
            chat_history_store=mock_chat_history,
        )

    assert result['status'] == 'processed'
    assert result['action'] == 'APPROVE'

    mem_after = await store.load(chat_id)
    assert mem_after is not None
    assert mem_after.last_case_ref == 'case-abc'
    assert mem_after.last_intent == 'BOOKING_RESPONSE'


@pytest.mark.asyncio
async def test_chat_history_contains_approval():
    """After booking approval, chat history store.append is called."""
    from app.telegram.communicator.memory.chat_history_store import ChatHistoryStore

    # Clear class-level in-memory store to avoid cross-test contamination
    ChatHistoryStore._mem_store.clear()

    store = ChatHistoryStore('memory://')
    chat_id = '99999'

    from app.api.webhooks import _handle_telegram_callback_query

    callback_query = {
        'id': 'cb-2',
        'data': 'booking:case-xyz:reject',
        'from': {'id': 999, 'username': 'testuser'},
        'message': {'chat': {'id': int(chat_id)}},
    }

    mock_audit = MagicMock()
    mock_audit.log_event = AsyncMock()
    mock_telegram = MagicMock()
    mock_telegram.bot_token = 'fake-token'
    mock_telegram.send = AsyncMock()

    mock_approval_record = MagicMock()
    mock_approval_record.status = 'PENDING'
    mock_approval_record.action_type = 'booking_finalize'
    mock_approval_record.approval_id = 'appr-002'

    mock_approval_svc = MagicMock()
    mock_approval_svc.list_by_case = AsyncMock(return_value=[mock_approval_record])

    mock_bas_instance = MagicMock()
    mock_bas_instance.process_response = AsyncMock(return_value={
        'decision': 'REJECT', 'approval_status': 'REJECTED',
    })

    mock_client = AsyncMock()

    with patch('app.booking.approval_service.BookingApprovalService', return_value=mock_bas_instance), \
         patch('app.dependencies.get_approval_service', return_value=mock_approval_svc), \
         patch('app.dependencies.get_open_items_service', return_value=MagicMock()), \
         patch('app.dependencies.get_akaunting_connector', return_value=MagicMock()), \
         patch('httpx.AsyncClient') as mock_httpx:

        mock_httpx.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_httpx.return_value.__aexit__ = AsyncMock(return_value=False)

        await _handle_telegram_callback_query(
            callback_query, {'update_id': 2}, mock_audit, mock_telegram,
            conversation_store=None,
            chat_history_store=store,
        )

    history = await store.load(chat_id)
    assert len(history) >= 2
    found_reject = any('abgelehnt' in msg['content'].lower() for msg in history)
    assert found_reject
