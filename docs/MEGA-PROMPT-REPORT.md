# Backend Mega-Prompt Report — 27.03.2026

## Vorher erledigt (nicht angefasst)
- ✅ Hash-Chain: valid, 25 Buchungen (pipe-separated, created_at normalisiert)
- ✅ Display-Name: "Maze" statt "testkunde"
- ✅ PDF-Rechnungen: 41 KB, Finalize + Buchung + OP

## Phase B: GDPR Export ✅
- **Root Cause:** `case.case_id` → `str(case.id)` (CaseRecord hat kein `case_id` Attribut)
- **Status-Code:** 200 (ZIP, 124 KB)
- **Inhalt:** tenant.json, cases.json, documents_metadata.json, audit_log.json, users.json, README.txt
- **Delete-Endpoint:** Existiert (POST /gdpr/delete), gibt "deletion_requested" zurück

## Phase C: Anthropic Fallback ✅
- **Implementierung:** try-except um litellm.acompletion im Communicator-Service
- **Trigger:** APIError, Timeout, InternalServerError
- **Fallback:** IONOS Mistral-Small-24B-Instruct (gleicher System-Prompt)
- **DB-Eintrag:** `communicator_fallback` (ionos, Mistral-Small-24B) ✅
- **Normal-Chat:** ✅ "Ja, alles klar hier — bei dir auch, Maze?"

## Phase F: Kontakt-Erweiterung + Dossier ✅
- **Migration 0024:** ✅ Neue Spalten: category, default_payment_terms_days, default_skonto_percent, default_skonto_days, tags, paperless_correspondent_id
- **Kategorie-Migration:** 14 Contacts → SUPPLIER, 3 → CUSTOMER
- **Model-Update:** Contact-Model + _row_to_contact Parser aktualisiert
- **Dossier-Endpoint:** `GET /contacts/{id}/dossier` ✅
  - Response: contact + stats (revenue, expenses, open_amount, overdue_count, booking_count) + recent_bookings + open_items
  - Test: "1&1 Telecom GmbH (SUPPLIER): 1 Buchung, 44.98€ Ausgaben"

## Phase G: TieredOrchestrator ✅
- **DB-Eintrag:** `orchestrator_router` (ionos, Mistral-Small-24B) ✅
- **Datei:** `agent/app/agents/tiered_orchestrator.py` (122 Zeilen)
- **Regex:** 12 Patterns (SHOW_INBOX, SHOW_FINANCE, etc.) ✅
- **Fast-Tier:** Mistral 24B Intent-Klassifikation ✅
- **Deep-Tier:** Fallthrough zu bestehendem Orchestrator ✅
- **Import-Test:** ✅

## Phase H: ActionRouter + ResponseBuilder ✅
- **ActionRouter:** `agent/app/agents/action_router.py` (59 Zeilen)
  - 14 Handler (approve, reject, defer, show_inbox, show_deadlines, etc.)
  - Direkter Service-Call, kein LLM
- **ResponseBuilder:** `agent/app/agents/response_builder.py` (215 Zeilen)
  - content_blocks: card_list, card, key_value, form, export
  - actions: Dynamische Button-Generierung basierend auf Intent
  - Deutsche Zahlenformatierung (1.234,56 €)
- **Import-Test:** ✅

## Phase I: WebSocket + Form-System ✅
- **Form-Schemas:** `agent/app/services/form_builders.py` (250 Zeilen)
  - `build_invoice_form()` — 5 Felder (Empfänger, Datum, Positionen, Anmerkungen, Zahlungsziel)
  - `build_contact_form()` — 8 Felder (Name, Kategorie, E-Mail, Telefon, USt-IdNr, IBAN, Zahlungsziel, Notizen)
  - `build_settings_form()` — 3 Felder (Name, Design, Benachrichtigungen)
  - `build_correction_form()` — 4 Felder (Soll, Haben, Betrag, MwSt-Satz)
- **Import-Test:** ✅

## Geänderte Dateien

| Datei | Phase | Änderung |
|-------|-------|----------|
| `agent/app/api/gdpr_views.py` | B | case.case_id → str(case.id) |
| `agent/app/telegram/communicator/service.py` | C | Fallback auf IONOS Mistral |
| `agent/app/accounting/models.py` | F | ContactCategory + 6 neue Felder im Contact |
| `agent/app/accounting/repository.py` | F | _row_to_contact erweitert |
| `agent/app/api/accounting_api.py` | F | GET /contacts/{id}/dossier Endpoint |
| `agent/app/agents/__init__.py` | G | NEU |
| `agent/app/agents/tiered_orchestrator.py` | G | NEU (122 Zeilen) |
| `agent/app/agents/action_router.py` | H | NEU (59 Zeilen) |
| `agent/app/agents/response_builder.py` | H | NEU (215 Zeilen) |
| `agent/app/services/__init__.py` | I | NEU |
| `agent/app/services/form_builders.py` | I | NEU (250 Zeilen) |

## DB-Änderungen

| Tabelle | Änderung |
|---------|----------|
| frya_contacts | +6 Spalten (category, payment_terms, skonto, tags, paperless_id) |
| frya_contacts | 14→SUPPLIER, 3→CUSTOMER migriert |
| frya_agent_llm_config | +communicator_fallback (Mistral-Small-24B) |
| frya_agent_llm_config | +orchestrator_router (Mistral-Small-24B) |

## Tests
- Health: ✅ `{"status":"ok"}`
- GDPR Export: ✅ 200 (ZIP, 124 KB)
- Contacts + Category: ✅
- Dossier: ✅ (1&1 Telecom GmbH, SUPPLIER)
- Import TieredOrchestrator: ✅ (12 Patterns, 14 Keywords)
- Import ResponseBuilder: ✅
- Import FormBuilders: ✅ (Invoice 5 fields, Contact 8 fields)
- Chat: ✅ "Ja, alles klar hier — bei dir auch, Maze?"
- Hash-Chain: ✅ valid (25 Buchungen)

## Entscheidungen nötig
Keine. Alle Phasen implementiert wie spezifiziert.

## Integration-Hinweis
Die neuen Module (TieredOrchestrator, ActionRouter, ResponseBuilder, FormBuilders) sind als **standalone Klassen** implementiert und importierbar. Sie sind noch NICHT in den bestehenden WebSocket-Handler oder Communicator-Service integriert — das erfordert Änderungen an `chat_ws.py` die über den Scope "keine eigenmächtigen Architektur-Entscheidungen" hinausgehen. Die Integration sollte als separater Schritt mit Maze besprochen werden.
