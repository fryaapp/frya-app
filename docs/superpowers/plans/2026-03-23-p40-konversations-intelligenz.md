# P-40: Konversations-Intelligenz + Semantic Fix + Vendor-Suche

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 5 bugs that make Frya forget context after booking approval, unable to show case details, unable to find cases by vendor name, misclassify invoices as PRIVATE, and create duplicate Paperless tags.

**Architecture:** All fixes are in the existing agent backend. BUG 1 adds logging to the callback memory update. BUG 2 extends `_build_system_context()` to fetch full case details when `conv_memory.last_case_ref` is set. BUG 3 adds a vendor-name search fallback. BUG 4 adds a priority classification rule to the semantic prompt. BUG 5 switches tag collection to a set.

**Tech Stack:** Python 3.11, FastAPI, asyncpg, Redis, litellm, Paperless-ngx API

**Spec:** `C:\Users\lenovo\Downloads\DEV-V3-PAKET-P-40-Konversations-Intelligenz.md`

---

## File Map

| File | Change | Bug |
|------|--------|-----|
| `agent/app/api/webhooks.py:902-918` | Add logger.info to memory update, log exceptions instead of pass | BUG 1 |
| `agent/app/telegram/communicator/service.py:139-202` | Add `conv_memory` param to `_build_system_context()`, fetch case details when `last_case_ref` set | BUG 2 |
| `agent/app/telegram/communicator/service.py:376-381` | Pass `conv_memory` to `_build_system_context()` call | BUG 2 |
| `agent/app/case_engine/doc_analyst_integration.py:186-256` | Store `document_analysis` dict into `case.metadata` after assignment | BUG 2 |
| `agent/app/telegram/communicator/service.py:253-262` | Add vendor-search fallback when context resolver returns NOT_FOUND | BUG 3 |
| `agent/app/telegram/communicator/context_resolver.py` | Add `_search_case_by_vendor()` helper | BUG 3 |
| `agent/app/document_analysis/semantic_service.py:106-131` | Add Regel 13 business-relevance priority | BUG 4 |
| `agent/app/orchestration/nodes.py:690-702` | Switch tag_ids from list to set for deduplication | BUG 5 |
| `agent/tests/test_p40_konversations_intelligenz.py` | New test file for all 5 bugs | ALL |

---

### Task 1: BUG 1 — Add logging to callback memory update (webhooks.py)

**Files:**
- Modify: `agent/app/api/webhooks.py:902-918`
- Test: `agent/tests/test_p40_konversations_intelligenz.py`

The memory update code exists but silently swallows exceptions. Add `logger.info` to confirm the code path is reached and `logger.warning` on failure.

- [ ] **Step 1: Write the failing test**

```python
# agent/tests/test_p40_konversations_intelligenz.py
"""Tests for P-40: Konversations-Intelligenz."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_conversation_memory_updated_after_approval():
    """After booking approval callback, conversation memory must contain the case_id."""
    from app.telegram.communicator.memory.conversation_store import ConversationMemoryStore

    store = ConversationMemoryStore('memory://')

    # Simulate: no prior memory for this chat
    chat_id = '12345'
    mem_before = await store.load(chat_id)
    assert mem_before is None

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

    # Mock the booking approval service chain
    mock_approval_record = MagicMock()
    mock_approval_record.status = 'PENDING'
    mock_approval_record.action_type = 'booking_finalize'
    mock_approval_record.approval_id = 'appr-001'

    with patch('app.api.webhooks._get_approval_svc') as mock_get_approval, \
         patch('app.api.webhooks._get_oi_svc') as mock_get_oi, \
         patch('app.api.webhooks.get_akaunting_connector') as mock_get_ak, \
         patch('app.api.webhooks.BookingApprovalService') as MockBAS, \
         patch('httpx.AsyncClient') as mock_httpx:

        mock_approval_svc = MagicMock()
        mock_approval_svc.list_by_case = AsyncMock(return_value=[mock_approval_record])
        mock_get_approval.return_value = mock_approval_svc

        mock_get_oi.return_value = MagicMock()
        mock_get_ak.return_value = MagicMock()

        mock_bas_instance = MagicMock()
        mock_bas_instance.process_response = AsyncMock(return_value={
            'decision': 'APPROVE', 'approval_status': 'APPROVED',
        })
        MockBAS.return_value = mock_bas_instance

        # httpx for answerCallbackQuery
        mock_client = AsyncMock()
        mock_httpx.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_httpx.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await _handle_telegram_callback_query(
            callback_query, {'update_id': 1}, mock_audit, mock_telegram,
            conversation_store=store,
            chat_history_store=mock_chat_history,
        )

    assert result['status'] == 'processed'
    assert result['action'] == 'APPROVE'

    # Memory must now contain the case ref
    mem_after = await store.load(chat_id)
    assert mem_after is not None
    assert mem_after.last_case_ref == 'case-abc'
    assert mem_after.last_intent == 'BOOKING_RESPONSE'


@pytest.mark.asyncio
async def test_chat_history_contains_approval():
    """After booking approval, chat history store.append is called."""
    from app.telegram.communicator.memory.chat_history_store import ChatHistoryStore

    store = ChatHistoryStore('memory://')
    chat_id = '12345'

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

    with patch('app.api.webhooks._get_approval_svc') as mock_get_approval, \
         patch('app.api.webhooks._get_oi_svc'), \
         patch('app.api.webhooks.get_akaunting_connector'), \
         patch('app.api.webhooks.BookingApprovalService') as MockBAS, \
         patch('httpx.AsyncClient') as mock_httpx:

        mock_approval_svc = MagicMock()
        mock_approval_svc.list_by_case = AsyncMock(return_value=[mock_approval_record])
        mock_get_approval.return_value = mock_approval_svc

        mock_bas_instance = MagicMock()
        mock_bas_instance.process_response = AsyncMock(return_value={
            'decision': 'REJECT', 'approval_status': 'REJECTED',
        })
        MockBAS.return_value = mock_bas_instance

        mock_client = AsyncMock()
        mock_httpx.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_httpx.return_value.__aexit__ = AsyncMock(return_value=False)

        await _handle_telegram_callback_query(
            callback_query, {'update_id': 2}, mock_audit, mock_telegram,
            conversation_store=None,
            chat_history_store=store,
        )

    history = await store.load(chat_id)
    assert len(history) >= 2
    assert 'abgelehnt' in history[0]['content'].lower() or 'abgelehnt' in history[1]['content'].lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd agent && python -m pytest tests/test_p40_konversations_intelligenz.py -v --no-header -x 2>&1 | head -40`

- [ ] **Step 3: Add logging to webhooks.py callback memory update**

In `agent/app/api/webhooks.py`, replace the silent `except Exception: pass` blocks with logged versions:

```python
# Line 902-918: Replace the memory update block
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
```

- [ ] **Step 4: Run tests**

Run: `cd agent && python -m pytest tests/test_p40_konversations_intelligenz.py::test_conversation_memory_updated_after_approval tests/test_p40_konversations_intelligenz.py::test_chat_history_contains_approval -v --no-header`

- [ ] **Step 5: Commit**

```bash
git add agent/tests/test_p40_konversations_intelligenz.py agent/app/api/webhooks.py
git commit -m "fix(P-40): BUG1 — add logging to callback memory update path"
```

---

### Task 2: BUG 2 — Case details in system context + persist document_analysis

**Files:**
- Modify: `agent/app/telegram/communicator/service.py:139-202, 376-381`
- Modify: `agent/app/case_engine/doc_analyst_integration.py:186-256`
- Test: `agent/tests/test_p40_konversations_intelligenz.py`

Two parts: (A) Store document_analysis in case.metadata during integration. (B) Extend `_build_system_context()` to fetch full case details when `conv_memory.last_case_ref` is set.

- [ ] **Step 1: Write test for case details in system context**

Append to `agent/tests/test_p40_konversations_intelligenz.py`:

```python
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
    # Store document_analysis in metadata
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd agent && python -m pytest tests/test_p40_konversations_intelligenz.py::test_system_context_includes_case_details -v --no-header -x`
Expected: FAIL — `_build_system_context()` doesn't accept `conv_memory` param.

- [ ] **Step 3: Extend `_build_system_context()` in service.py**

In `agent/app/telegram/communicator/service.py`, modify `_build_system_context` signature and add case-detail fetching:

```python
async def _build_system_context(
    tenant_id: Any,
    case_repository: Any,
    audit_service: Any,
    user_memory: Any,
    conv_memory: 'ConversationMemory | None' = None,
) -> str | None:
    """Fetch live system data and format as a [SYSTEMKONTEXT] block for the LLM."""
    parts: list[str] = []

    # ── Detailed case context from conversation memory ──────────────────────
    if conv_memory and conv_memory.last_case_ref and case_repository is not None:
        try:
            import uuid as _uuid_mod
            case_detail = await case_repository.get_case(_uuid_mod.UUID(conv_memory.last_case_ref))
            if case_detail:
                detail_parts = []
                detail_parts.append(f'Aktueller Vorgang: {case_detail.case_number or case_detail.id}')
                detail_parts.append(f'Vendor: {case_detail.vendor_name}')
                detail_parts.append(f'Betrag: {case_detail.total_amount} {case_detail.currency}')
                detail_parts.append(f'Status: {case_detail.status}')

                meta = case_detail.metadata or {}
                if meta.get('document_analysis'):
                    analysis = meta['document_analysis']
                    if analysis.get('document_number'):
                        detail_parts.append(f'Rechnungsnummer: {analysis["document_number"]}')
                    if analysis.get('document_date'):
                        detail_parts.append(f'Datum: {analysis["document_date"]}')
                    if analysis.get('line_items'):
                        items_str = ', '.join(str(item) for item in analysis['line_items'][:5])
                        detail_parts.append(f'Positionen: {items_str}')
                    if analysis.get('sender'):
                        detail_parts.append(f'Absender: {analysis["sender"]}')
                    if analysis.get('iban'):
                        detail_parts.append(f'IBAN: {analysis["iban"]}')

                if meta.get('booking_proposal'):
                    bp = meta['booking_proposal']
                    detail_parts.append(f'Buchung: {bp.get("skr03_soll_name")} -> {bp.get("skr03_haben_name")}')

                parts.append('Vorgang-Details:\n' + '\n'.join(f'  - {p}' for p in detail_parts))
        except Exception as _exc:
            logger.debug('system_context: case detail fetch failed: %s', _exc)

    # (rest of existing function unchanged)
```

- [ ] **Step 4: Update the caller in `try_handle_turn()` to pass `conv_memory`**

In `agent/app/telegram/communicator/service.py`, at line ~376, change:

```python
                    sys_ctx = await _build_system_context(
                        tenant_id=_tenant_id,
                        case_repository=_case_repo,
                        audit_service=audit_service,
                        user_memory=prev_user_memory,
                        conv_memory=conv_memory,
                    )
```

- [ ] **Step 5: Store document_analysis in case.metadata during integration**

In `agent/app/case_engine/doc_analyst_integration.py`, after the `add_document_to_case` calls (for both the assigned and draft_created paths), add metadata persistence. Add this right before the `if audit_service is not None:` block (~line 258):

```python
    # Persist document_analysis summary in case metadata for communicator context
    _case_uuid = uuid.UUID(result['case_id'])
    try:
        await repo.update_metadata(_case_uuid, {
            'document_analysis': {
                'sender': vendor_name,
                'document_number': ref_tuples[0][1] if ref_tuples else None,
                'document_date': str(document_date) if document_date else None,
                'gross_amount': float(total_amount) if total_amount is not None else None,
                'document_type': document_type_value,
            }
        })
    except Exception:
        pass  # metadata update must not break the integration flow
```

- [ ] **Step 6: Run tests**

Run: `cd agent && python -m pytest tests/test_p40_konversations_intelligenz.py::test_system_context_includes_case_details -v --no-header`

- [ ] **Step 7: Commit**

```bash
git add agent/app/telegram/communicator/service.py agent/app/case_engine/doc_analyst_integration.py agent/tests/test_p40_konversations_intelligenz.py
git commit -m "fix(P-40): BUG2 — case details in system context + persist document_analysis"
```

---

### Task 3: BUG 3 — Vendor name search fallback

**Files:**
- Modify: `agent/app/telegram/communicator/context_resolver.py`
- Modify: `agent/app/telegram/communicator/service.py:253-262`
- Test: `agent/tests/test_p40_konversations_intelligenz.py`

When the context resolver returns NOT_FOUND, search active cases by vendor name mentioned in the user's message.

- [ ] **Step 1: Write tests for vendor search**

Append to `agent/tests/test_p40_konversations_intelligenz.py`:

```python
@pytest.mark.asyncio
async def test_vendor_search_finds_case():
    """User mentions vendor name verbatim → case is found."""
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

    found = await search_case_by_vendor('Was war mit A&S Autoteile?', repo, tenant_id)
    assert found is not None
    assert found == str(case.id)


@pytest.mark.asyncio
async def test_vendor_search_partial_match():
    """User mentions partial vendor name → case is found."""
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

    found = await search_case_by_vendor('Was ist mit INOX?', repo, tenant_id)
    assert found is not None
    assert found == str(case.id)


@pytest.mark.asyncio
async def test_vendor_search_no_match():
    """No matching vendor → returns None."""
    import uuid as _uuid
    from app.telegram.communicator.context_resolver import search_case_by_vendor
    from app.case_engine.repository import CaseRepository

    repo = CaseRepository('memory://')
    tenant_id = _uuid.uuid4()

    found = await search_case_by_vendor('Hallo Frya', repo, tenant_id)
    assert found is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd agent && python -m pytest tests/test_p40_konversations_intelligenz.py::test_vendor_search_finds_case -v --no-header -x`
Expected: ImportError — `search_case_by_vendor` does not exist yet.

- [ ] **Step 3: Add `search_case_by_vendor()` to context_resolver.py**

Append to `agent/app/telegram/communicator/context_resolver.py`:

```python
async def search_case_by_vendor(
    text: str,
    case_repository: Any,
    tenant_id: Any,
) -> str | None:
    """Search for a case whose vendor_name matches text from the user message.

    Returns case_id (str) or None.
    """
    if not text or case_repository is None or tenant_id is None:
        return None

    all_cases = await case_repository.list_active_cases_for_tenant(tenant_id)
    text_lower = text.lower()

    # Pass 1: vendor name appears in user text (or vice versa)
    for case in all_cases:
        vendor = (getattr(case, 'vendor_name', None) or '').lower()
        if not vendor:
            continue
        if vendor in text_lower or text_lower in vendor:
            return str(case.id)

    # Pass 2: any word >3 chars from user text matches inside a vendor name
    words = [w for w in text_lower.split() if len(w) > 3]
    for case in all_cases:
        vendor = (getattr(case, 'vendor_name', None) or '').lower()
        if not vendor:
            continue
        if any(word in vendor for word in words):
            return str(case.id)

    return None
```

- [ ] **Step 4: Integrate vendor search into communicator service.py**

In `agent/app/telegram/communicator/service.py`, import the new function at the top (line 12):

```python
from app.telegram.communicator.context_resolver import resolve_context, search_case_by_vendor
```

Then after step 6 (context resolution, ~line 262), add a vendor-search fallback. Insert AFTER the `resolve_context` block and BEFORE step 7 (truth arbitration):

```python
        # ── Step 6b: vendor-name fallback when context not found ───────────
        if (
            intent in _CONTEXT_INTENTS
            and (core_ctx is None or core_ctx.resolution_status == 'NOT_FOUND')
            and case_repository is not None
        ):
            _tenant_for_vendor = None
            if case_repository is not None and case_id and case_id != 'unknown':
                try:
                    import uuid as _uuid_mod
                    _co = await case_repository.get_case(_uuid_mod.UUID(case_id))
                    if _co:
                        _tenant_for_vendor = _co.tenant_id
                except Exception:
                    pass
            # Also try tenant from existing case lookup done later
            if _tenant_for_vendor is None and conv_memory and conv_memory.last_case_ref:
                try:
                    import uuid as _uuid_mod
                    _co2 = await case_repository.get_case(_uuid_mod.UUID(conv_memory.last_case_ref))
                    if _co2:
                        _tenant_for_vendor = _co2.tenant_id
                except Exception:
                    pass

            if _tenant_for_vendor is not None:
                vendor_case_id = await search_case_by_vendor(
                    normalized.text or '', case_repository, _tenant_for_vendor,
                )
                if vendor_case_id:
                    core_ctx = CommunicatorContextResolution(
                        resolution_status='FOUND',
                        resolved_case_ref=vendor_case_id,
                        context_reason='Vendor-Name im Text erkannt.',
                    )
```

- [ ] **Step 5: Run tests**

Run: `cd agent && python -m pytest tests/test_p40_konversations_intelligenz.py -k vendor -v --no-header`
Expected: All 3 vendor tests PASS.

- [ ] **Step 6: Commit**

```bash
git add agent/app/telegram/communicator/context_resolver.py agent/app/telegram/communicator/service.py agent/tests/test_p40_konversations_intelligenz.py
git commit -m "fix(P-40): BUG3 — vendor-name search fallback in communicator"
```

---

### Task 4: BUG 4 — Semantic prompt business-relevance priority rule

**Files:**
- Modify: `agent/app/document_analysis/semantic_service.py:106-131`
- Test: `agent/tests/test_p40_konversations_intelligenz.py`

Add Regel 13 to the semantic prompt: documents with USt-ID, Rechnungsnummer, line items with prices, or MwSt indicators are ALWAYS classified as INVOICE.

- [ ] **Step 1: Write test**

Append to `agent/tests/test_p40_konversations_intelligenz.py`:

```python
def test_semantic_prompt_has_business_relevance_check():
    """Semantic prompt must contain the Geschaeftsrelevanz-Check rule."""
    from app.document_analysis.semantic_service import _SYSTEM_PROMPT
    assert 'USt-IDNr' in _SYSTEM_PROMPT
    assert 'IMMER' in _SYSTEM_PROMPT
    # The rule must explicitly state that documents with USt-ID are always INVOICE
    assert 'Rechnungsnummer' in _SYSTEM_PROMPT
    # PRIVATE definition must mention "OHNE jegliche geschaeftliche Merkmale"
    prompt_lower = _SYSTEM_PROMPT.lower()
    assert 'geschäftsrelevanz' in prompt_lower or 'geschaeftsrelevanz' in prompt_lower or 'priorität' in prompt_lower or 'prioritaet' in prompt_lower
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd agent && python -m pytest tests/test_p40_konversations_intelligenz.py::test_semantic_prompt_has_business_relevance_check -v --no-header -x`

- [ ] **Step 3: Add Regel 13 to semantic prompt**

In `agent/app/document_analysis/semantic_service.py`, insert AFTER the document type table (after line ~131 `| OTHER | Keines der obigen Muster passt |`) and BEFORE the MULTI-DOKUMENT section:

```
PRIORITÄT bei Dokumenttyp-Erkennung:
Ein Dokument ist IMMER geschäftsrelevant (is_business_relevant=true)
und IMMER eine Rechnung (document_type="INVOICE") wenn MINDESTENS EINES zutrifft:
- Es enthält eine USt-IDNr. oder Steuernummer
- Es enthält eine Rechnungsnummer
- Es enthält Positionen mit Preisen (Artikelliste, Einzelpreise, Gesamtpreise)
- Es enthält "Rechnung" oder "Invoice" als Dokumentüberschrift
- Es enthält MwSt-Angaben (19%, 7%, "Mehrwertsteuer", "Umsatzsteuer")
Auch wenn der Absender wie eine Privatperson klingt (z.B. "Ahmad Fayad"):
Wenn das Dokument geschäftliche Merkmale hat, ist es eine Rechnung.
document_type="PRIVATE" ist NUR für Dokumente OHNE jegliche geschäftliche Merkmale
(kein Betrag, keine Rechnungsnummer, keine USt-IDNr., keine Positionen).
```

- [ ] **Step 4: Run test**

Run: `cd agent && python -m pytest tests/test_p40_konversations_intelligenz.py::test_semantic_prompt_has_business_relevance_check -v --no-header`

- [ ] **Step 5: Commit**

```bash
git add agent/app/document_analysis/semantic_service.py agent/tests/test_p40_konversations_intelligenz.py
git commit -m "fix(P-40): BUG4 — Geschaeftsrelevanz-Prioritaet in Semantic Prompt"
```

---

### Task 5: BUG 5 — Tag deduplication with set

**Files:**
- Modify: `agent/app/orchestration/nodes.py:690-702`
- Test: `agent/tests/test_p40_konversations_intelligenz.py`

Switch tag_ids from list to set to prevent duplicate tags.

- [ ] **Step 1: Write test**

Append to `agent/tests/test_p40_konversations_intelligenz.py`:

```python
def test_tags_no_duplicates():
    """Tag collection in writeback must deduplicate IDs."""
    # Simulate the tag merging logic
    existing_tags = [1, 2, 3]
    new_tag_analysiert = 2  # already exists
    new_tag_vst = 4

    tag_ids = set(existing_tags)
    tag_ids.add(new_tag_analysiert)
    tag_ids.add(new_tag_vst)

    result = sorted(tag_ids)
    assert result == [1, 2, 3, 4]
    assert len(result) == 4  # no duplicates
```

- [ ] **Step 2: Run test (passes — it's a logic test)**

Run: `cd agent && python -m pytest tests/test_p40_konversations_intelligenz.py::test_tags_no_duplicates -v --no-header`

- [ ] **Step 3: Refactor tag handling in nodes.py to use set**

In `agent/app/orchestration/nodes.py`, replace lines 690-702:

**Old:**
```python
    # ── Tags (merge with existing — never overwrite) ─────────────────────
    existing_doc = await connector.get_document(document_ref)
    tag_ids: list[int] = list(existing_doc.get('tags', []))
    analysiert_id = await connector.find_or_create_tag('frya:analysiert', '#2196F3')
    if analysiert_id is not None and analysiert_id not in tag_ids:
        tag_ids.append(analysiert_id)
    # Add vorsteuer-relevant for invoices
    if analysis.document_type.status in ('FOUND', 'UNCERTAIN') and analysis.document_type.value == 'INVOICE':
        vst_id = await connector.find_or_create_tag('vorsteuer-relevant', '#673AB7')
        if vst_id is not None and vst_id not in tag_ids:
            tag_ids.append(vst_id)
    if tag_ids:
        patch_data['tags'] = tag_ids
```

**New:**
```python
    # ── Tags (merge with existing — never overwrite, deduplicate) ────────
    existing_doc = await connector.get_document(document_ref)
    tag_ids: set[int] = set(existing_doc.get('tags', []))
    analysiert_id = await connector.find_or_create_tag('frya:analysiert', '#2196F3')
    if analysiert_id is not None:
        tag_ids.add(analysiert_id)
    # Add vorsteuer-relevant for invoices
    if analysis.document_type.status in ('FOUND', 'UNCERTAIN') and analysis.document_type.value == 'INVOICE':
        vst_id = await connector.find_or_create_tag('vorsteuer-relevant', '#673AB7')
        if vst_id is not None:
            tag_ids.add(vst_id)
    if tag_ids:
        patch_data['tags'] = sorted(tag_ids)
```

- [ ] **Step 4: Run all tests**

Run: `cd agent && python -m pytest tests/test_p40_konversations_intelligenz.py -v --no-header`

- [ ] **Step 5: Commit**

```bash
git add agent/app/orchestration/nodes.py agent/tests/test_p40_konversations_intelligenz.py
git commit -m "fix(P-40): BUG5 — deduplicate tags with set in Paperless writeback"
```

---

### Task 6: Full test suite + final commit

- [ ] **Step 1: Run full test suite**

Run: `cd agent && python -m pytest tests/ -v --no-header --tb=short 2>&1 | tail -30`

- [ ] **Step 2: Fix any failures**

- [ ] **Step 3: Final commit**

```bash
git add -A
git commit -m "fix(P-40): Konversations-Intelligenz + Semantic Fix + Vendor-Suche"
```

---

## Verification Checklist

After deploy, verify these 7 items:

1. `grep -c "logger.info.*Callback memory\|logger.warning.*Callback" agent/app/api/webhooks.py` → ≥ 4
2. `grep -c "document_analysis\|document_number\|Vorgang-Details" agent/app/telegram/communicator/service.py` → ≥ 3
3. `grep -c "search_case_by_vendor\|vendor_name.*lower" agent/app/telegram/communicator/context_resolver.py` → ≥ 3
4. `grep -c "Geschäftsrelevanz\|PRIORITÄT\|USt-IDNr.*IMMER" agent/app/document_analysis/semantic_service.py` → ≥ 1
5. `grep -c "set(existing\|tag_ids.*set\|sorted(tag" agent/app/orchestration/nodes.py` → ≥ 1
6. All tests green
7. Health endpoint returns 200
