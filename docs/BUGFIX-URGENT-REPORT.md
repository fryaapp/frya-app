# Bugfix Report — 27.03.2026

## Bug 1: Unbekannter Nachrichtentyp
- **Root Cause:** Frontend `sendAction()` sendete `type: 'action'` — Backend kennt nur `message`, `ping`, `form_submit`. Backend antwortete mit "Unbekannter Nachrichtentyp: action".
- **Fix:** `fryaStore.ts` — `sendAction()` sendet jetzt `type: 'message'` mit `quick_action` Feld (wie der REST-Handler)
- **Test:** "hallo" → "Hallo! Was kann ich für dich tun?" ✅ (kein Fehler)

## Bug 2: Content-Blocks nicht sichtbar
- **Root Cause (Stufe 1):** ResponseBuilder wurde mit `agent_results={}` aufgerufen — keine Daten für content_blocks
- **Fix:** chat_ws.py + customer_api.py — Nach TieredOrchestrator Routing werden die Daten via Service-Registry geholt (`inbox_service.list_pending()`, `euer_service.get_finance_summary()`, etc.) und an den ResponseBuilder weitergegeben
- **Root Cause (Stufe 2):** `_conf_color(None)` crashed mit `TypeError: '>=' not supported between NoneType and float`
- **Fix:** `response_builder.py` — `_conf_color()` behandelt `None` als `"warning"`
- **Root Cause (Stufe 3):** Finance ResponseBuilder erwartete `results["summary"]` aber Service liefert `{total_income, total_expenses, ...}` direkt
- **Fix:** ResponseBuilder akzeptiert beide Formate
- **Test:**
  - Inbox → card_list mit 20 Items + 2 Actions ✅
  - Finanzen → key_value Block (Einnahmen: 2.586,40€, Ausgaben, Ergebnis) + 2 Actions ✅

## Bug 3: Greeting
- **\u2026 gefixt:** ✅ Placeholder jetzt "Nachricht an Frya…" (echte Ellipse)
- **Doppelte Warnung gefixt:** ✅ `buildPrompt()` zeigt jetzt `status_summary` statt `urgent.text` → urgent nur in roter Box
- **Name in Begrüßung:** ✅ "Abend Maze!" (war schon funktional aus dem display_name Fix)

## Bug 4: Bug-Report
- Nicht getestet in dieser Session — war in den Screenshots nicht kaputt

## Bug 5: FRYA: Prefix
- **Fix:** chat_ws.py + customer_api.py — `reply_text.startswith('FRYA:')` → Strip
- **Test:** "hallo" → "Hallo! Was kann ich für dich tun?" (kein FRYA: Prefix) ✅

## Geänderte Dateien
| Datei | Fix |
|-------|-----|
| ui/src/stores/fryaStore.ts | Bug 1: sendAction → type: 'message' mit quick_action |
| ui/src/components/GreetingScreen.tsx | Bug 3a: Placeholder, Bug 3b: buildPrompt |
| agent/app/api/chat_ws.py | Bug 2: Service-Fetch, Bug 5: Strip FRYA: |
| agent/app/api/customer_api.py | Bug 2: Service-Fetch, Bug 5: Strip FRYA: |
| agent/app/agents/response_builder.py | Bug 2: _conf_color(None), Finance field names |
