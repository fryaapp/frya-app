# Wiring Fix Report — 27.03.2026

## Fix 1: IONOS Fast-Tier
- **Key-Quelle:** DB (`frya_agent_llm_config.api_key_encrypted`) via `LLMConfigRepository.decrypt_key_for_call()` → ENV fallback `FRYA_IONOS_API_KEY`
- **Änderung:** `tiered_orchestrator.py` — `_route_fast()` nutzt jetzt `_get_llm_config('orchestrator_router')` statt `os.environ.get('IONOS_API_KEY')`
- **routing bei Nicht-Regex-Frage:** `fast` ✅ (vorher: `fast_no_key`)

## Fix 2: ActionRouter Service-Registry
- **Neue Datei:** `agent/app/agents/service_registry.py`
- **Pattern:** `ServiceProxy` Klasse mit lazy Service-Resolution via `dependencies.py`
- **Verdrahtet:** 4/14 Services (die mit existierenden Methoden):
  - `euer_service.get_finance_summary` → `BookingService.get_finance_summary()`
  - `booking_service.list` → `repo.list_bookings()`
  - `open_item_service.list` → `repo.list_open_items()`
  - `contact_service.get_dossier` → Dossier-Logik
- **Nicht verdrahtet** (Methoden existieren nicht): inbox_service (approve/reject/defer/list_pending), deadline_service, invoice_service (prepare_form/finalize), settings_service, case_service
- **ActionRouter in TieredOrchestrator:** ✅ Wird beim ersten Aufruf mit Service-Registry initialisiert
- **Quick Action Test:** Nicht direkt testbar über REST (ActionRouter greift nur bei `quick_action` in Message)

## Fix 3: Form-Wrapper
- **Neue Datei:** `agent/app/services/form_handlers.py`
- **invoice `handle_invoice_form`:** ✅ → `InvoiceService.create_invoice()` + Contact find_or_create
- **contact `handle_contact_form`:** ✅ → `find_or_create_contact()` + DB-Update für Zusatzfelder
- **settings `handle_settings_form`:** ✅ → `frya_user_preferences` Upsert
- **form_submit WebSocket:** ✅ "FRYA: Rechnung RE-2026-005 erstellt (59.50€, Entwurf)."

## Geänderte Dateien

| Datei | Änderung |
|-------|----------|
| `agent/app/agents/tiered_orchestrator.py` | `_get_llm_config()` + `_route_fast()` nutzt DB-Config |
| `agent/app/agents/service_registry.py` | NEU — Lazy Service-Registry für ActionRouter |
| `agent/app/services/form_handlers.py` | NEU — Invoice/Contact/Settings Form-Handler |
| `agent/app/api/chat_ws.py` | ActionRouter in TieredOrchestrator, form_submit mit echten Handlers |

## Abschluss-Tests

| # | Test | Ergebnis |
|---|------|----------|
| 1 | Fast-Tier (Nicht-Regex: "Hat Anna bezahlt?") | ✅ `routing: fast` |
| 2 | Regex ("Was liegt in der Inbox?") | ✅ `routing: regex`, 2 actions |
| 3 | Hash-Chain | ✅ `valid: true, total: 25` |
| 4 | Normaler Chat ("Hallo Frya") | ✅ "Hallo Maze!", 2 suggestions |
| 5 | Form-Submit Invoice (WebSocket) | ✅ RE-2026-005 erstellt (59.50€) |
