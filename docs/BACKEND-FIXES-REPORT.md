# Backend-Fixes Report — 27.03.2026

## Fix 1: Name-Update via Chat

- **Gewählte Option:** A (Intent-Detection im Chat-Handler + Persistence in frya_user_preferences)
- **Was geändert:**
  - `agent/app/api/chat_ws.py` — Regex-basierte Name-Erkennung + DB-Persist-Funktion
  - `agent/app/api/customer_api.py` — Gleiche Logik für synchronen POST /chat
  - `agent/app/api/greeting_views.py` — display_name aus frya_user_preferences lesen

- **Erkannte Patterns:**
  - "Ich heiße X" / "Mein Name ist X" / "Nenn mich X" / "Ich bin X"
  - Mindestens 2 Zeichen, filtert Füllwörter (da, ja, ok, etc.)

- **Persistence:** Key-Value in `frya_user_preferences` (tenant_id, user_id, key='display_name', value=Name)
- **DB-Permission-Fix:** `GRANT ALL ON frya_user_preferences TO frya_app;` war nötig

- **Test-Ergebnis:**
  ```
  VOR:  Greeting = "Noch fleißig testkunde?"
  Chat: "Ich heiße Maze" → "Das weiß ich bereits — hi nochmal, Maze!"
  NACH: Greeting = "Noch fleißig Maze?"
  DB:   frya_user_preferences: user_id=testkunde, key=display_name, value=Maze
  ```

## Fix 2: PDF-Rechnungen

- **PDF-Library:** Gotenberg (HTML → PDF via Jinja2-Templates) — war bereits vorhanden
- **generate_pdf Status:** ✅ funktioniert (41 KB PDF, korrekt formatiert)
- **Rechnungsnummer-Format:** RE-YYYY-NNN (z.B. RE-2026-004)
- **Advisory Lock:** Ja (get_next_invoice_number nutzt pg_advisory_xact_lock)

### Neuer Endpoint: POST /invoices/{id}/finalize

**Was passiert:**
1. Prüft ob Invoice DRAFT ist (409 wenn schon SENT)
2. Erstellt Buchung (Konto 1200 Forderungen → 7000 Umsatzerlöse)
3. Erstellt Offenen Posten (RECEIVABLE, OPEN)
4. Setzt Invoice-Status auf SENT (nur nach erfolgreicher Buchung + OP)

**Test-Ergebnis:**
```
CREATE:   RE-2026-004, 119.00€, Status: DRAFT ✅
FINALIZE: booking_number=22, open_item_id=f9d64179... ✅
PDF:      HTTP 200, 41757 bytes ✅
```

### Chat-Intent CREATE_INVOICE

Der Intent `invoice_create` existiert bereits in INTENT_TO_CONTEXT (chat_ws.py).
Der Orchestrator routet "Erstelle eine Rechnung" über den Accounting Analyst.

## Geänderte Dateien

| Datei | Änderung |
|-------|----------|
| `agent/app/api/chat_ws.py` | +`_extract_name_intent()`, +`_persist_display_name()`, Name-Check nach Communicator-Reply |
| `agent/app/api/customer_api.py` | Name-Check im sync POST /chat Handler |
| `agent/app/api/greeting_views.py` | +`_get_display_name()`, Greeting nutzt display_name statt username |
| `agent/app/api/accounting_api.py` | +`POST /invoices/{id}/finalize` Endpoint, `timedelta` Import |

## Nicht gemacht (Frontend-Seite)

→ Dokumentiert in FRONTEND-CHANGES-NEEDED.md (nicht erstellt, da keine Frontend-Änderungen nötig)

Die Frontend-Seiten nutzen bereits die bestehenden API-Responses. Der Greeting-Endpoint gibt jetzt automatisch den richtigen Namen zurück — das Frontend zeigt ihn ohne Änderung korrekt an.

Für Rechnungen: Das Frontend hat noch keine dedizierte Invoice-UI. Falls gewünscht:
- Invoice-Erstellung über Chat funktioniert bereits
- Eine dedizierte "/invoices" Seite mit Liste + PDF-Download wäre sinnvoll
- Finalize-Button in der Invoice-Detail-Ansicht
