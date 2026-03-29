# Wirklich-Gefixt Report — 28.03.2026

## Bug 1: "Unbekannter Nachrichtentyp: None"

- **Root Cause:** ZWEI Ursachen:
  1. Frontend `sendAction()` sendete `type: 'action'` (gefixt in vorheriger Session)
  2. Jeder unbekannte WS msg_type vom Server wurde als Error-Message angezeigt (error.message = "Unbekannter Nachrichtentyp: X")
- **Fix:** `fryaStore.ts` — default case im switch handler: zeigt Text wenn vorhanden, ignoriert sonst still. NIE "Unbekannter Nachrichtentyp" dem User zeigen.
- **Deployed:** Ja, 28.03.2026 00:12 UTC
- **curl-Beweis:**
```
TEXT: Hallo! Was kann ich für dich tun?
FEHLER: NEIN ✅
content_blocks: 0 (type: list)
actions: 2 (type: list)
```

## Bug 2: Content-Blocks nicht sichtbar

- **Root Cause:** `fryaStore.ts` `message_complete` Handler speicherte `msg.content_blocks` und `msg.actions` NICHT in die Message. Sie kamen vom Server aber wurden verworfen.
- **Fix:** `fryaStore.ts` Zeile 227-245 — `content_blocks` und `actions` aus `msg` extrahieren und in ChatMessage speichern.
- **Deployed:** Ja, 28.03.2026 00:12 UTC
- **curl-Beweis (WS Inbox):**
```
TEXT: In deiner Inbox liegen aktuell 5 offene Vorgänge...
content_blocks: 1
  block_type=card_list items=20
  first_item: IONOS SE: 2,25 €
actions: 2
  Abarbeiten → Inbox abarbeiten
  Nur dringende → Nur dringende Belege
```

## Bug 3: Neue Agenten in Operator-UI

- **Root Cause:** `AGENT_CATALOG` in `llm_config.py` hatte nur 8 Agenten. Die neuen (orchestrator_router, communicator_fallback) fehlten.
- **Fix:** `llm_config.py` — 2 Einträge zu `AGENT_CATALOG` hinzugefügt. `KNOWN_AGENTS` wird automatisch daraus generiert.
- **Deployed:** Ja, 28.03.2026 00:12 UTC
- **Beweis:**
```
KNOWN_AGENTS (10): ('orchestrator', 'communicator', ..., 'orchestrator_router', 'communicator_fallback')
orchestrator_router: True
communicator_fallback: True
```

## Bug 4: BugReport Overlay abgeschnitten

- **Root Cause:** `maxHeight: 'calc(100vh - 64px)'` + `overflow: 'hidden'` auf dem Outer-Container.
- **Fix:** `BugReportOverlay.tsx` — `maxHeight: '85vh'`, `overflow: 'visible'` (Body hat eigenes overflowY: auto).
- **Deployed:** Ja, 28.03.2026 00:12 UTC

## Hash-Chain
```json
{"valid":true,"total":25,"errors":[]}
```

## Geänderte Dateien
| Datei | Fix |
|-------|-----|
| ui/src/stores/fryaStore.ts | Bug 1+2: content_blocks/actions in Store, default case |
| ui/src/components/layout/BugReportOverlay.tsx | Bug 4: max-height + overflow |
| agent/app/llm_config.py | Bug 3: orchestrator_router + communicator_fallback in AGENT_CATALOG |
