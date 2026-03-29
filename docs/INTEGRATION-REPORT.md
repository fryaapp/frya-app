# Integration Report — 27.03.2026

## Flow-Dokumentation

### AKTUELLER FLOW (VOR Änderung):
1. User sendet `{"type": "message", "text": "..."}` über WebSocket oder POST /chat
2. `_get_communicator_reply()` → baut TelegramNormalizedIngressMessage → ruft `communicator.try_handle_turn()` auf
3. Communicator: 12-Step Pipeline (Intent-Klassifikation, Context-Resolution, Guardrail, LLM-Call, etc.)
4. Response: `{"type": "message_complete", "text": "...", "case_ref": null, "context_type": "...", "suggestions": [...]}`
5. Kein Intent-Routing außer `INTENT_TO_CONTEXT` Mapping + `_detect_context_type()` Keyword-Fallback

### NEUER FLOW (NACH Integration):
1. User sendet `{"type": "message", "text": "...", "quick_action": {...}}` (quick_action optional)
2. **NEU:** `TieredOrchestrator.route()` → Intent + Routing-Tier (regex/fast/deep)
   - Regex: 12 Patterns, <5ms
   - Fast: Mistral 24B Intent-Klassifikation, ~250ms (wenn IONOS_API_KEY verfügbar)
   - Deep: Fallthrough (intent=COMPLEX)
3. Communicator-Pipeline (unverändert) → natürlichsprachliche Antwort
4. **NEU:** `ResponseBuilder.build()` → content_blocks + actions basierend auf Intent
5. Response: `{"type": "message_complete", "text": "...", "case_ref": null, "context_type": "...", "suggestions": [...], "content_blocks": [...], "actions": [...], "routing": "regex|fast|deep"}`
6. **NEU:** `form_submit` als neuer msg_type akzeptiert (placeholder, Services noch nicht verdrahtet)

## Änderungen

| Datei | Was |
|-------|-----|
| `agent/app/api/chat_ws.py` | TieredOrchestrator + ResponseBuilder Integration, form_submit Handler, Docstring erweitert |
| `agent/app/api/customer_api.py` | ChatResponse um content_blocks/actions/routing erweitert, TieredOrchestrator in REST-Handler |

## Service-Registry

Die ActionRouter HANDLERS referenzieren 14 Service-Methoden. Status:

| Handler | Service-Methode | Existiert? |
|---------|----------------|------------|
| approve | inbox_service.approve | ❌ |
| reject | inbox_service.reject | ❌ |
| defer | inbox_service.defer | ❌ |
| show_inbox | inbox_service.list_pending | ❌ |
| show_deadlines | deadline_service.list | ❌ |
| show_finance | euer_service.get_finance_summary | ✅ (BookingService) |
| show_contact | contact_service.get_dossier | ❌ (aber /dossier Endpoint existiert) |
| show_bookings | booking_service.list | ❌ (list_bookings existiert) |
| show_open_items | open_item_service.list | ❌ (list_open_items existiert) |
| create_invoice | invoice_service.prepare_form | ❌ |
| finalize_invoice | invoice_service.finalize | ❌ |
| export_datev | euer_service.export_datev | ✅ (als API-Endpoint) |
| show_settings | settings_service.get | ❌ |
| update_setting | settings_service.update | ❌ |

**Fazit:** ActionRouter ist noch NICHT aktiv verdrahtet (keine Service-Registry instanziiert). Der TieredOrchestrator nutzt nur Regex + Fast-Tier für Intent-Erkennung, die EIGENTLICHE Daten-Abfrage läuft weiterhin über den Communicator.

Form-Service-Methoden (create_from_form, etc.) existieren ebenfalls nicht — form_submit wird akzeptiert aber gibt Placeholder-Antwort.

## Test-Ergebnisse

| Test | Ergebnis |
|------|----------|
| Alter Flow (Hallo Frya) | ✅ reply + suggestions + actions (2) |
| Neue Felder (content_blocks, actions) | ✅ Vorhanden in Response |
| Routing (Inbox = Regex) | ✅ `routing: "regex"` |
| Routing (Finanzen = Regex) | ✅ `routing: "regex"`, Actions: "EÜR als PDF", "DATEV Export" |
| Routing (Hallo = Fast) | ✅ `routing: "fast_no_key"` (IONOS_API_KEY fehlt als ENV im Container) |
| Hash-Chain | ✅ `{"valid":true,"total":25,"errors":[]}` |
| Chat Backward-Compat | ✅ text, suggestions, case_ref unverändert vorhanden |

## Was NICHT verdrahtet werden konnte

1. **ActionRouter Service-Registry:** Die bestehenden Services sind als Singletons in `dependencies.py` (via `@lru_cache`) organisiert, nicht als DI-Container. Eine Service-Registry müsste manuell in `main.py` gebaut werden. Das ist eine Architektur-Entscheidung.

2. **Form-Service-Methoden:** `create_from_form()`, `update_from_form()`, `correct_from_form()` existieren nicht auf den Services. Diese müssen als Wrapper implementiert werden.

3. **IONOS_API_KEY im Container:** Die ENV-Variable ist nicht im Docker-Compose gesetzt. Der Fast-Tier fällt auf `fast_no_key` zurück (= kein Mistral-Call, nur Regex).

→ Dokumentiert in diesem Report. Keine `ARCHITECTURE-DECISIONS-NEEDED.md` nötig, da die Entscheidungen klar sind (Service-Registry bauen, Form-Wrapper schreiben, ENV-Var setzen).
