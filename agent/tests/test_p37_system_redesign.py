"""Tests for P-37 System Redesign."""
import json
import pytest


def test_chat_history_store_append_and_load():
    from app.telegram.communicator.memory.chat_history_store import ChatHistoryStore
    import asyncio
    store = ChatHistoryStore('memory://')
    async def _run():
        await store.append('test-chat-1', 'Hallo', 'FRYA: Hallo!')
        await store.append('test-chat-1', 'Status?', 'FRYA: Alles gut.')
        history = await store.load('test-chat-1')
        assert len(history) == 4
        assert history[0]['role'] == 'user'
        assert history[1]['role'] == 'assistant'
    asyncio.get_event_loop().run_until_complete(_run())


def test_chat_history_store_max_messages():
    from app.telegram.communicator.memory.chat_history_store import ChatHistoryStore
    import asyncio
    store = ChatHistoryStore('memory://')
    store.MAX_MESSAGES = 4  # 2 pairs
    async def _run():
        await store.append('test-chat-2', 'A', 'B')
        await store.append('test-chat-2', 'C', 'D')
        await store.append('test-chat-2', 'E', 'F')
        history = await store.load('test-chat-2')
        assert len(history) == 4
        assert history[0]['content'] == 'C'
    asyncio.get_event_loop().run_until_complete(_run())


def test_communicator_prompt_has_ich_form():
    from app.telegram.communicator.prompts import COMMUNICATOR_SYSTEM_PROMPT
    assert 'Ich habe dein Dokument' in COMMUNICATOR_SYSTEM_PROMPT
    assert 'Korrigiere dich NICHT' in COMMUNICATOR_SYSTEM_PROMPT
    assert 'KONVERSATIONSGEDÄCHTNIS' in COMMUNICATOR_SYSTEM_PROMPT
    assert 'PRIVATMODUS' in COMMUNICATOR_SYSTEM_PROMPT


def test_semantic_prompt_has_private():
    from app.document_analysis.semantic_service import _SYSTEM_PROMPT
    assert 'PRIVATE' in _SYSTEM_PROMPT
    assert 'has_attachments' in _SYSTEM_PROMPT
    assert 'private_info' in _SYSTEM_PROMPT
    assert 'PAYSLIP' in _SYSTEM_PROMPT
    assert 'BEISPIELE' in _SYSTEM_PROMPT


def test_orchestrator_prompt_positive_rules():
    from app.orchestration.nodes import draft_action_with_llm
    import inspect
    source = inspect.getsource(draft_action_with_llm)
    assert 'HARTE REGELN' in source
    assert 'Höchstwert für confidence' in source
    assert 'invoice_create' in source
    assert 'reminder_personal' in source


def test_accounting_prompt_has_examples():
    from app.accounting_analyst.service import _SYSTEM_PROMPT
    assert 'BEISPIELE' in _SYSTEM_PROMPT
    assert 'Telefonrechnung' in _SYSTEM_PROMPT
    assert '4920' in _SYSTEM_PROMPT


def test_risk_prompt_has_examples():
    from app.risk_analyst.service import _SYSTEM_PROMPT
    assert 'BEISPIELE' in _SYSTEM_PROMPT
    assert 'AMOUNT_DEVIATION' in _SYSTEM_PROMPT
    assert 'Buchungsvorschläge erstellt der Accounting Analyst' in _SYSTEM_PROMPT


def test_memory_curator_prompt_has_datenschutz():
    from app.memory_curator.service import MemoryCuratorService
    import inspect
    source = inspect.getsource(MemoryCuratorService)
    assert 'DATENSCHUTZ' in source
    assert '[PERSON]' in source
    assert '[IBAN]' in source
    assert 'Persönliches' in source


def test_reminder_personal_intent():
    from app.telegram.communicator.intent_classifier import classify_intent
    assert classify_intent('Erinnere mich morgen um 9 an den Arzttermin') == 'REMINDER_PERSONAL'
    assert classify_intent('Vergiss nicht Blumen zu kaufen') == 'REMINDER_PERSONAL'
    assert classify_intent('Merk dir den Termin am Freitag') == 'REMINDER_PERSONAL'


def test_token_tracking_cost_estimation():
    from app.token_tracking import _estimate_cost
    cost = _estimate_cost('anthropic', 'claude-sonnet-4-6', 1000, 500)
    assert cost > 0
    cost_ionos = _estimate_cost('ionos', 'mistral', 1000, 500)
    assert cost_ionos > 0
    assert cost > cost_ionos  # Anthropic should be more expensive


def test_document_analysis_result_new_fields():
    from app.document_analysis.models import DocumentAnalysisResult
    fields = DocumentAnalysisResult.model_fields
    assert 'has_attachments' in fields
    assert 'is_business_relevant' in fields
    assert 'private_info' in fields
