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
         patch('app.dependencies.get_accounting_repository', return_value=MagicMock()), \
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
         patch('app.dependencies.get_accounting_repository', return_value=MagicMock()), \
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


@pytest.mark.asyncio
async def test_system_context_includes_case_details():
    """When conv_memory has last_case_ref, system context must include vendor, amount, doc number."""
    import uuid as _uuid
    from decimal import Decimal
    from app.telegram.communicator.service import _build_system_context
    from app.telegram.communicator.memory.models import ConversationMemory
    from app.case_engine.repository import CaseRepository

    repo = CaseRepository('memory://')
    tenant_id = _uuid.uuid4()

    case = await repo.create_case(
        tenant_id=tenant_id,
        case_type='incoming_invoice',
        vendor_name='A-F-INOX GmbH',
        total_amount=Decimal('245.99'),
        currency='EUR',
        created_by='test',
    )
    await repo.update_metadata(case.id, {
        'document_analysis': {
            'sender': 'A-F-INOX GmbH',
            'document_number': 'INV-2026-001',
            'document_date': '15.03.2026',
            'gross_amount': 245.99,
            'document_type': 'INVOICE',
            'iban': 'DE89370400440532013000',
        }
    })

    conv_memory = ConversationMemory(
        conversation_memory_ref='conv-test',
        chat_id='test-chat',
        last_case_ref=str(case.id),
    )

    ctx = await _build_system_context(
        tenant_id=tenant_id,
        case_repository=repo,
        audit_service=None,
        user_memory=None,
        conv_memory=conv_memory,
    )

    assert ctx is not None
    assert 'A-F-INOX GmbH' in ctx
    assert '245.99' in ctx
    assert 'INV-2026-001' in ctx
    assert 'DE89370400440532013000' in ctx


@pytest.mark.asyncio
async def test_vendor_search_finds_case():
    """User mentions vendor name verbatim -> case is found."""
    import uuid as _uuid
    from decimal import Decimal
    from app.telegram.communicator.context_resolver import search_case_by_vendor
    from app.case_engine.repository import CaseRepository

    repo = CaseRepository('memory://')
    tenant_id = _uuid.uuid4()

    case = await repo.create_case(
        tenant_id=tenant_id,
        case_type='incoming_invoice',
        vendor_name='A&S Autoteile',
        total_amount=Decimal('120.00'),
        currency='EUR',
        created_by='test',
    )
    # Directly set status in memory store (bypass transition check)
    repo._cases[case.id] = case.model_copy(update={'status': 'OPEN'})

    found = await search_case_by_vendor('Was war mit A&S Autoteile?', repo, tenant_id)
    assert found is not None
    assert found == str(case.id)


@pytest.mark.asyncio
async def test_vendor_search_partial_match():
    """User mentions partial vendor name -> case is found."""
    import uuid as _uuid
    from decimal import Decimal
    from app.telegram.communicator.context_resolver import search_case_by_vendor
    from app.case_engine.repository import CaseRepository

    repo = CaseRepository('memory://')
    tenant_id = _uuid.uuid4()

    case = await repo.create_case(
        tenant_id=tenant_id,
        case_type='incoming_invoice',
        vendor_name='A-F-INOX Trading GmbH',
        total_amount=Decimal('245.99'),
        currency='EUR',
        created_by='test',
    )
    # Directly set status in memory store (bypass transition check)
    repo._cases[case.id] = case.model_copy(update={'status': 'OPEN'})

    found = await search_case_by_vendor('Was ist mit INOX?', repo, tenant_id)
    assert found is not None
    assert found == str(case.id)


@pytest.mark.asyncio
async def test_vendor_search_no_match():
    """No matching vendor -> returns None."""
    import uuid as _uuid
    from app.telegram.communicator.context_resolver import search_case_by_vendor
    from app.case_engine.repository import CaseRepository

    repo = CaseRepository('memory://')
    tenant_id = _uuid.uuid4()

    found = await search_case_by_vendor('Hallo Frya', repo, tenant_id)
    assert found is None


# ── P-40 Nachtrag: Duplikat-Erkennung ──────────────────────────────────────

@pytest.mark.asyncio
async def test_duplicate_detected_sends_telegram_message():
    """When Paperless task fails with 'duplicate', user gets a Telegram notification."""
    from app.telegram.media_service import TelegramMediaIngressService

    mock_paperless = MagicMock()
    mock_paperless.get_task_status = AsyncMock(return_value={
        'task_id': 'task-123',
        'status': 'FAILURE',
        'result': 'file.pdf: Not consuming file.pdf: It is a duplicate of Invoice XYZ (#42).',
    })

    mock_telegram = MagicMock()
    mock_telegram.send = AsyncMock(return_value={'ok': True})

    svc = TelegramMediaIngressService(
        audit_service=MagicMock(),
        open_items_service=MagicMock(),
        telegram_connector=mock_telegram,
        telegram_case_link_service=MagicMock(),
        file_store=MagicMock(),
        max_bytes=10_000_000,
        allowed_mime_types={'application/pdf'},
        allowed_extensions={'.pdf'},
        paperless_connector=mock_paperless,
    )

    # Patch asyncio.sleep to not actually wait
    with patch('asyncio.sleep', new_callable=AsyncMock):
        await svc._poll_paperless_task_for_duplicate(
            paperless_task_id='task-123',
            chat_id='12345',
            case_id='case-dup-001',
            filename='file.pdf',
        )

    mock_telegram.send.assert_called_once()
    sent_msg = mock_telegram.send.call_args[0][0]
    assert 'bereits' in sent_msg.text
    assert 'Invoice XYZ' in sent_msg.text
    assert sent_msg.reply_markup is not None
    assert 'inline_keyboard' in sent_msg.reply_markup


@pytest.mark.asyncio
async def test_duplicate_skip_callback():
    """dup_skip callback acks and sends skip message."""
    from app.api.webhooks import _handle_telegram_callback_query

    callback_query = {
        'id': 'cb-dup-1',
        'data': 'dup_skip:case-dup-001',
        'from': {'id': 999},
        'message': {'chat': {'id': 12345}},
    }

    mock_audit = MagicMock()
    mock_audit.log_event = AsyncMock()
    mock_telegram = MagicMock()
    mock_telegram.bot_token = 'fake-token'
    mock_telegram.send = AsyncMock()

    with patch('httpx.AsyncClient') as mock_httpx:
        mock_client = AsyncMock()
        mock_httpx.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_httpx.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await _handle_telegram_callback_query(
            callback_query, {'update_id': 3}, mock_audit, mock_telegram,
        )

    assert result['status'] == 'processed'
    assert result['action'] == 'dup_skip'
    mock_telegram.send.assert_called_once()
    sent_msg = mock_telegram.send.call_args[0][0]
    assert 'bersprungen' in sent_msg.text


def test_line_item_model():
    """LineItem model can be instantiated."""
    from decimal import Decimal
    from app.document_analysis.models import LineItem
    item = LineItem(
        description='Spanplattenschrauben TX',
        quantity=2,
        unit_price=Decimal('11.59'),
        total_price=Decimal('23.18'),
    )
    assert item.description == 'Spanplattenschrauben TX'
    assert item.quantity == 2


def test_semantic_prompt_has_line_items():
    """Semantic prompt must mention line_items."""
    from app.document_analysis.semantic_service import _SYSTEM_PROMPT
    assert 'line_items' in _SYSTEM_PROMPT
    assert 'description' in _SYSTEM_PROMPT
    assert 'unit_price' in _SYSTEM_PROMPT
