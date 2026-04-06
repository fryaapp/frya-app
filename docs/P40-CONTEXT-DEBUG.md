# Kontext-Verlust Debug Report

Erstellt: 2026-04-06
Analyst: P40-ContextDebugger

---

## Chat-History Mechanismus

### Zwei parallele Speicher

**1. ChatHistoryStore (Redis)**
- Datei: `agent/app/telegram/communicator/memory/chat_history_store.py`
- Schluessel: `frya:chat_history:{chat_id}` (z.B. `frya:chat_history:web-<user_id>`)
- Ring-Buffer: letzte 20 Nachrichten (10 User+Assistant-Paare)
- TTL: 24 Stunden
- Fallback: In-Memory dict wenn `redis_url` mit `memory://` beginnt
- Wird an den LLM uebergeben: ja, als `messages`-Array vor der User-Nachricht in `build_llm_context_payload()` (service.py Zeile 294-299)
- Wird befuellt: NUR bei erfolgreichen LLM-Calls in `service.py` Zeile 875-876

**2. ConversationMemoryStore (Redis)**
- Datei: `agent/app/telegram/communicator/memory/conversation_store.py`
- Schluessel: `frya:comm:conv:{chat_id}`
- TTL: 24 Stunden
- Speichert: `last_case_ref`, `last_document_ref`, `last_intent`, `last_open_item_id`, `last_search_ref`
- Wird an den LLM uebergeben: indirekt — als FALLKONTEXT-Block in `build_llm_context_payload()` (service.py Zeile 239-259)
- Sticky-Merge: Bei `NOT_FOUND` bleibt der alte `last_case_ref` erhalten (conversation_store.py Zeile 118-129)

### Wie Chat-ID aufgebaut wird

Im Web-Chat (chat_ws.py Zeile 788-790):
```
actor.chat_id = f'web-{user_id}'
```

Beide Stores verwenden diese `chat_id` als Schluessel — konsistent.

### Wie Chat-History dem LLM uebergeben wird

In `build_llm_context_payload()` (service.py Zeile 293-299):
```python
messages = [system_msg]
if chat_history:
    for msg in chat_history:
        if msg.get('content', '').strip():
            messages.append(msg)
messages.append({'role': 'user', 'content': '\n'.join(lines)})
```

Der [FALLKONTEXT]-Block (mit `last_case_ref`, `letzte_turns`) wird als Content der letzten User-Message angehaengt. Die Chat-History steht davor als normale messages.

---

## `last_case_ref` — Wo wird es gesetzt und gelesen

### Gesetzt
- In `conversation_store.py` `build_updated_conversation_memory()`: bei jedem Communicator-Turn wenn `resolution_status != NOT_FOUND`
- Wird NICHT geloescht nach einer Antwort — bleibt 24h aktiv (Sticky-Merge-Prinzip)
- Bei `is_search_result=True` landet das Ergebnis in `last_search_ref` (nicht `last_case_ref`) um den Haupt-Kontext nicht zu ueberschreiben

### Gelesen
- In `_build_system_context()` (service.py Zeile 318-320): als `_effective_case_ref` Fallback
- In `build_llm_context_payload()` (service.py Zeile 243-244): in `letzte_turns`-Block
- In `TruthArbitrator.arbitrate()` (truth_arbitration.py Zeile 40-57): als Memory-Fallback fuer Context-Intents

---

## Wie der Orchestrator Follow-up-Nachrichten erkennt

### "Den buche" / "Ändere den Betrag"

1. TieredOrchestrator (`tiered_orchestrator.py`) prueft Regex-Patterns -> keine Match
2. `_needs_deep()` -> False (kurze Nachricht)
3. LLM-Klassifikation via Mistral -> gibt `UNKNOWN` zurueck -> wird zu `COMPLEX`/`deep`
4. Intent-Classifier (`intent_classifier.py`) klassifiziert als `GENERAL_CONVERSATION` (catch-all)
5. `TruthArbitrator.arbitrate()` wird aufgerufen mit `intent='GENERAL_CONVERSATION'`
6. **PROBLEM (vor Fix):** TruthArbitrator gibt `(None, TruthAnnotation.unknown())` zurueck fuer Non-Context-Intents — der `last_case_ref` aus `conv_memory` wird IGNORIERT
7. `_build_system_context()` bekommt `effective_case_ref=None`, fallback auf `conv_memory.last_case_ref` existiert — aber nur wenn Memory Curator funktioniert
8. `build_llm_context_payload()` bekommt `context_resolution=None` -> LLM sieht nur `letzte_turns` ohne expliziten `resolved_case_ref`

### Kurze Antworten ("Ja", "Ok", "Den")

- Landen direkt bei `GENERAL_CONVERSATION`
- Ohne den Memory-Kontext weiss der LLM nicht welcher Beleg gemeint ist
- Vendor-Name-Suche (`search_case_by_vendor`) findet nichts bei einsilbigen Worten

---

## Root Causes gefunden

### RC-1: Regex/Fast-Route speichert keine Chat-History

**Problem:** Wenn TieredOrchestrator per Regex oder Fast-LLM antwortet (SHOW_INBOX, SHOW_FINANCE, CREATE_INVOICE etc.), wird `chat_history_store.append()` NICHT aufgerufen. Der naechste GENERAL_CONVERSATION-Turn sieht eine leere oder alte History — der LLM weiss nicht, was kurz vorher angezeigt wurde.

**Betroffener Code:** `chat_ws.py` Zeile 1485-1528 (Shortcircuit-Block)

**Fix: implementiert JA**
- Datei: `agent/app/api/chat_ws.py`
- Nach `await websocket.send_json(response_payload)` und vor `continue` wird jetzt `get_chat_history_store().append()` aufgerufen

---

### RC-2: TruthArbitrator ignoriert ConversationMemory fuer GENERAL_CONVERSATION

**Problem:** `TruthArbitrator.arbitrate()` gibt fuer alle Non-Context-Intents sofort `(None, TruthAnnotation.unknown())` zurueck. Das bedeutet: `effective_ctx = None`, kein `resolved_case_ref` im FALLKONTEXT. Bei Folgefragen wie "Ja", "Ok", "Den buche" hat der LLM keinen Kontext ueber den letzten Beleg.

**Betroffener Code:** `truth_arbitration.py` Zeile 32-34 (vor Fix)

**Fix: implementiert JA**
- Datei: `agent/app/telegram/communicator/memory/truth_arbitration.py`
- Neue frozenset `_CONV_MEMORY_INTENTS` hinzugefuegt: `GENERAL_CONVERSATION`, `BOOKING_REQUEST`, `FINANCIAL_QUERY`, `REMINDER_PERSONAL`
- Fuer diese Intents: wenn `conv_memory` einen `last_case_ref` hat, wird ein synthetischer Context mit `TruthAnnotation.from_conv_memory()` zurueckgegeben
- Effekt: `effective_ctx.resolved_case_ref` ist jetzt befuellt -> `_build_system_context()` laedt den Fall-Detail-Kontext

---

### RC-3: `build_llm_context_payload()` schreibt `last_case_ref` nicht explizit wenn `context_resolution` None

**Problem:** Selbst wenn `conv_memory.last_case_ref` vorhanden ist, wurde der FALLKONTEXT nur mit `letzte_turns: [intent=..., case_ref=...]` befuellt — kein separater `resolved_case_ref`-Eintrag. Der LLM muss den Kontext aus dem `letzte_turns`-String ableiten, was unzuverlaessig ist.

**Betroffener Code:** `service.py` Zeile 239-259

**Fix: implementiert JA**
- Datei: `agent/app/telegram/communicator/service.py`
- Wenn `context_resolution is None` aber `conv_memory.last_case_ref` vorhanden: zusaetzliche Zeilen `resolved_case_ref: <ref>` und `context_from: conversation_memory` in den FALLKONTEXT geschrieben
- Ausserdem: `last_search_ref` wird jetzt auch in `letzte_turns` angezeigt (bisher fehlte das)

---

### RC-4: Communicator-Service bekommt frische `case_id` bei jedem Web-Turn

**Problem:** In `_get_communicator_reply()` (chat_ws.py Zeile 805) wird bei jedem Web-Chat-Turn eine neue `case_id` generiert:
```python
case_id = f'web-{user_id}-{uuid.uuid4().hex[:8]}'
```
Die `resolve_context()`-Funktion sucht nach Audit-Events fuer diese `case_id` — findet naturlich nichts. Das ist konstruktionsbedingt (Web-Chat hat keine Case-ID), aber bedeutet: `core_ctx` ist immer `NOT_FOUND`, der Fallback auf `conv_memory` ist der einzige Kontext-Weg.

**Betroffener Code:** `chat_ws.py` Zeile 805, `context_resolver.py` Zeile 17-117

**Fix: NEIN** (kein einfacher Fix ohne Architekturanpassung; die `conv_memory`-Fixes aus RC-2/RC-3 mildern das Problem ausreichend)

---

### RC-5: APPROVE-Intent loest case_id ueber Vendor-Name auf — ignoriert `last_case_ref`

**Problem:** In `chat_ws.py` Zeile 1126-1159 wird bei APPROVE eine Vendor-Name-Suche in der DB gemacht. Aber der `conv_memory.last_case_ref` wird nicht zuerst gecheckt. Wenn der User "Den freigeben" sagt direkt nach einem SHOW_CASE-Turn, sollte der `last_case_ref` priorisiert werden.

**Betroffener Code:** `chat_ws.py` Zeile 1098-1175 (APPROVE-Shortcircuit-Block)

**Fix: NEIN** (benoetigt separate Story; die bestehende Vendor-Match-Logik funktioniert fuer die meisten Faelle)

---

## Implementierte Fixes

### Fix 1: Shortcircuit-Chat-History

**Datei:** `agent/app/api/chat_ws.py`

**Aenderung:** Nach dem Shortcircuit-Block (Zeile ~1527) wird vor `await websocket.send_json(response_payload)` jetzt die Chat-History gespeichert:

```python
# RC-4 Fix: Chat-History auch bei Shortcircuit speichern
try:
    _hist_store = get_chat_history_store()
    _sc_hist_reply = _shortcircuit_reply or ''
    if _sc_hist_reply:
        await _hist_store.append(f'web-{user_id}', text, _sc_hist_reply)
except Exception as _hist_exc:
    logger.debug('Shortcircuit history append failed: %s', _hist_exc)
```

**Wirkung:** Der naechste LLM-Turn sieht im `chat_history`-Array was kurz vorher geantwortet wurde (z.B. "3 Belege warten auf deine Freigabe."). Folgefragen wie "Gib mir mehr Details zum ersten" sind jetzt loesbar.

---

### Fix 2: TruthArbitrator ConversationMemory fuer Folgefragen

**Datei:** `agent/app/telegram/communicator/memory/truth_arbitration.py`

**Aenderung:** Neue frozenset `_CONV_MEMORY_INTENTS` + erweiterter `arbitrate()`-Code:

```python
_CONV_MEMORY_INTENTS = frozenset({
    'GENERAL_CONVERSATION', 'BOOKING_REQUEST',
    'FINANCIAL_QUERY', 'REMINDER_PERSONAL',
})

# In arbitrate():
if intent not in _CONTEXT_INTENTS:
    if intent in _CONV_MEMORY_INTENTS and conv_memory is not None:
        has_useful = bool(conv_memory.last_case_ref or ...)
        if has_useful:
            mem_ctx = CommunicatorContextResolution(
                resolution_status='FOUND',
                resolved_case_ref=conv_memory.last_case_ref,
                ...
                context_reason='Aus Konversationsgedaechtnis (Follow-up).',
            )
            return mem_ctx, TruthAnnotation.from_conv_memory()
    return None, TruthAnnotation.unknown()
```

**Wirkung:** `effective_ctx.resolved_case_ref` ist jetzt befuellt fuer GENERAL_CONVERSATION-Turns wenn ein frueher gesehener Beleg im Memory steht. `_build_system_context()` laedt die Fall-Details und stellt sie dem LLM zur Verfuegung.

---

### Fix 3: Expliziter resolved_case_ref im FALLKONTEXT

**Datei:** `agent/app/telegram/communicator/service.py`

**Aenderung:** In `build_llm_context_payload()` — wenn `context_resolution` None aber `conv_memory.last_case_ref` bekannt:

```python
if parts:
    lines.append(f'letzte_turns: [{", ".join(parts)}]')
    # RC-3 Fix: resolved_case_ref explizit nennen fuer Folgefragen
    if context_resolution is None and conversation_memory.last_case_ref:
        lines.append(f'resolved_case_ref: {conversation_memory.last_case_ref}')
        lines.append('context_from: conversation_memory')
```

**Wirkung:** Der LLM sieht im FALLKONTEXT einen klar benannten `resolved_case_ref` — nicht nur den mehrdeutigen `letzte_turns`-String. Das verbessert zuverlaessig die Kontextaufloesung bei Folgefragen.

---

## Verbleibende offene Punkte

| ID | Problem | Aufwand | Empfehlung |
|----|---------|---------|------------|
| RC-4 | `case_id` im Web-Chat ist immer fresh UUID — Context-Resolver findet nichts | Mittel | Separates Ticket; conv_memory-Fixes mildern dies |
| RC-5 | APPROVE ignoriert `last_case_ref` aus conv_memory | Klein | In APPROVE-Block zuerst `conv_memory.last_case_ref` pruefen |
| RC-6 | `BUILD_REQUEST` und `BOOKING_REQUEST` landen in `GENERAL_CONVERSATION` wenn TieredOrchestrator Regex matcht (APPROVE) | Klein | APPROVE-Regex praezisieren |

---

## Betroffene Dateien (Zusammenfassung)

| Datei | Aenderung |
|-------|-----------|
| `agent/app/api/chat_ws.py` | Shortcircuit-Block speichert jetzt Chat-History |
| `agent/app/telegram/communicator/memory/truth_arbitration.py` | `_CONV_MEMORY_INTENTS` + Memory-Fallback fuer Folgefragen |
| `agent/app/telegram/communicator/service.py` | Expliziter `resolved_case_ref` im FALLKONTEXT + `last_search_ref` in `letzte_turns` |
