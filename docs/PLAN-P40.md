# P-40 Plan

Erstellt: 2026-04-06
Basis-Analyse: agent/app/, ui/src/

---

## Bestandsaufnahme Backend-Architektur

### Zwei Backend-Stacks

Das Projekt hat zwei separate FastAPI-Backends:

**backend/app/** (legacy, einfacher Stack)
- Paperless-Connector vorhanden (PaperlessConnector, `paperless_base_url`, `paperless_token`)
- Einfachere Struktur: contact_service, invoice_service, booking_service
- Kein WebSocket-Chat-Endpoint

**agent/app/** (aktueller Haupt-Stack)
- FastAPI mit LangGraph-Orchestrierung (`orchestration/graph.py`)
- WebSocket-Chat: `/api/v1/chat/stream` (`api/chat_ws.py` — 670+ Zeilen)
- TieredOrchestrator + ActionRouter + ResponseBuilder (Phase G/H/I)
- Communicator-Pipeline (Telegram-Adapter, wird auch fuer Web-Chat verwendet)
- Bulk-Upload: `/api/v1/documents/bulk-upload`
- ConversationMemoryStore (Redis, TTL 24h)
- ChatHistoryStore (Redis, TTL 24h, 20 Messages Ring-Buffer)

### Haupt-Einstiegspunkte

| Weg | Datei | Beschreibung |
|-----|-------|--------------|
| WS `/api/v1/chat/stream` | `agent/app/api/chat_ws.py` | Haupt-Chat-Kanal |
| POST `/api/v1/chat` | `agent/app/api/chat_ws.py` | REST-Fallback |
| POST `/api/v1/documents/bulk-upload` | `agent/app/api/bulk_upload.py` | Datei-Upload |
| POST `/agent/run` | `agent/app/main.py` | LangGraph-Orchestrator (intern) |

### Orchestrierungs-Fluss

```
User-Nachricht (WS)
  -> sanitize_user_message()          [Prompt-Injection-Guard]
  -> TieredOrchestrator.route()       [Intent-Erkennung: regex/fast/deep]
  -> ActionRouter (quick_action)      [Short-circuit fuer bekannte Actions]
  -> CommunicatorService.try_handle_turn()  [Fallback: volle Pipeline]
  -> ResponseBuilder.build()          [content_blocks + actions zusammenstellen]
  -> WebSocket send message_complete
```

---

## Content-Block-Typen (aus Code)

Registriert in `ui/src/components/content/ContentBlock.tsx` (switch-case):

| block_type | Komponente | Beschreibung |
|------------|------------|--------------|
| `card` | CardBlock | Einzelner Beleg mit Feldern/Badge |
| `card_group` | CardGroupBlock | Accordion-Gruppen (Vendor/Referenz) |
| `card_list` | CardListBlock | Liste von Cards, erweiterbar (initial_count: 5) |
| `table` | TableBlock | Tabellenansicht |
| `chart` | ChartBlock | Diagramme (Finanzen) |
| `form` | FormBlock | Eingabeformulare |
| `document` | DocumentBlock | Dokumentvorschau |
| `key_value` | KeyValueBlock | Schluessel-Wert-Paare |
| `progress` | ProgressBlock | Fortschrittsbalken |
| `alert` | AlertBlock | Statusmeldungen (success/info/warning/error) |
| `export` | ExportBlock | Export-Buttons (PDF, DATEV) |
| `status` | StatusBlock | Status-Anzeige |
| `action` | ActionButton | Klickbarer Button (inline) |

### Grouping-Logik (Backend)

`agent/app/services/grouping_service.py` ist vollstaendig implementiert:
- Strategie 1: Gleiche `reference_value` (Rechnungsnummer etc.) → Gruppe
- Strategie 2: Gleicher Vendor-Name (>=2 Belege) → Gruppe
- Erkennt Mahnungsketten (`dunning_chain`)
- Berechnet `total_amount`, `highest_badge`, `warning`

`ResponseBuilder._blocks_show_inbox()` ruft `group_inbox_items()` auf und erzeugt `card_group`-Blocks. Der `card_group`-Block wird an den Frontend-`CardGroupBlock` uebergeben (Accordion mit "Alle freigeben"-Button). Das Feature ist also **vollstaendig implementiert und aktiv**.

---

## Kontext-Verlust Root Causes

### 1. Pending-Flow State ist WebSocket-Instanz-gebunden

```python
# chat_ws.py, Zeile ~935
_pending_flow = getattr(websocket, '_frya_pending_flow', None)
```

Der `pending_flow` wird direkt am `websocket`-Objekt als Attribut gespeichert. Bei WebSocket-Disconnect (Netzwerk-Ausfall, App in Hintergrund, Reconnect) geht dieser State verloren. Kein Redis/DB-Backup.

### 2. ConversationMemoryStore: Redis-TTL und Fehlerbehandlung

```python
# conversation_store.py
_TTL = 86400  # 24h
```

Der Store verwendet Redis mit 24h TTL. Bei Redis-Fehler (Verbindung) gibt `load()` `None` zurueck und `save()` loggt nur einen Warning — kein Crash, aber der Kontext ist weg. `last_case_ref` und `last_search_ref` werden nicht persistent in DB gesichert.

### 3. Chat-ID-Konstruktion ist nicht stabil

```python
# chat_ws.py
case_id = f'web-{user_id}-{uuid.uuid4().hex[:8]}'
# actor.chat_id = f'web-{user_id}'
```

Die `chat_id` fuer den ConversationMemoryStore ist `web-{user_id}` (stabil), aber die `case_id` enthaelt eine zufaellige UUID pro Turn. Das bedeutet: Kontext-Lookup ueber `case_id` schlaegt immer fehl; nur der actor-basierte `chat_id`-Key ist konsistent.

### 4. TieredOrchestrator-Kontext ist zustandslos

Der TieredOrchestrator selbst ist zustandslos — er bekommt keinen vorherigen `last_case_ref` direkt uebergeben. Der Kontext muss aus dem ConversationMemoryStore (via CommunicatorService) kommen. Wenn der TieredOrchestrator einen Short-circuit macht (ActionRouter handhabt die Anfrage komplett), wird der ConversationMemoryStore moeglicherweise nicht aktualisiert.

### 5. ChatHistoryStore-Key vs. ConversationMemoryStore-Key

- `ChatHistoryStore` verwendet Key `frya:chat_history:{chat_id}` mit `chat_id = f'web-{user_id}'`
- `ConversationMemoryStore` verwendet Key `frya:comm:conv:{chat_id}` mit demselben Schema

Bei Redis-Ausfall liefert ChatHistoryStore eine leere Liste (kein Fallback), ConversationMemoryStore liefert `None` (kein Fallback). Der LLM-Kontext ist dann leer — der Assistent "vergisst" alles.

### 6. Frontend-Seite: messages sind In-Memory (Zustand geht bei App-Neustart verloren)

`fryaStore.ts`: `messages: []` — kein LocalStorage-Backup. Bei App-Reload ist die Chat-History fuer den User unsichtbar, auch wenn sie im Redis des Backends noch vorhanden ist. Es gibt keinen Mechanismus, die Chat-History beim Reconnect nachzuladen.

---

## Feature-Bewertungen

### A: Ladebalken beim Upload

**Aktueller Zustand:**
- Upload-Flow (ChatView.tsx): Drag-and-Drop → `api.postFormData('/documents/bulk-upload', form)` → fire-and-forget, keine Progress-Rueckmeldung
- `PipelineStatus.tsx` und `FileStatus`-Typen existieren bereits (pending/uploading/processing/done/error/duplicate)
- WebSocket-Nachrichtentyp `notification` mit `notification_type: 'document_processed'` existiert (Backend sendet push nach Paperless-Webhook)
- Ein neuer WS-Nachrichtentyp `upload_progress` ist **nicht** implementiert

**Fehlende Teile:**
1. Backend muss nach `bulk-upload` pro Datei WS-Push senden (`chat_registry.send_to_user()` existiert bereits)
2. Frontend muss Upload-State pro Datei tracken (FileStatus-Store fehlt im fryaStore)
3. GreetingScreen/ChatView muessen PipelineStatus-Komponente einbinden

**Aufwand: 6-8h**
- Backend: bulk_upload.py → nach jedem Paperless-Upload `chat_registry.send_to_user()` aufrufen mit `{type: 'upload_progress', filename, status}` (2h)
- fryaStore: uploadFiles-State + Handler fuer `upload_progress`-Messages (2h)
- Frontend: PipelineStatus in ChatView/GreetingScreen einbinden (2h)
- Testen + Edge Cases (2h)

**Umsetzbar: JA** — alle Infrastruktur-Bausteine (chat_registry, PipelineStatus, FileStatus-Typen) sind vorhanden.

---

### B: Durchsuchbares Archiv ("Zeig mir alles von Allianz")

**Aktueller Zustand:**
- `paperless_base_url` und `PaperlessConnector` sind im backend/app vorhanden, aber im agent/app-Stack ist der Connector zustaendig via `get_paperless_connector()` in dependencies.py
- In `agent/app/main.py` wird `paperless_metadata` an den LangGraph-State uebergeben
- Es gibt KEINEN dedizierten "Archiv-Suche"-Intent im TieredOrchestrator
- Der Communicator kann Vendor-Suche (`vendor_search`-Intent, Zeile 614 in chat_ws.py als TYPING_HINT vorhanden), aber kein Full-Text-Archiv-Browse

**Was fehlt:**
1. Ein neuer Intent `ARCHIVE_SEARCH` im TieredOrchestrator
2. ActionHandler der `/api/v1/paperless/search?q=Allianz` aufruft (oder direkt Paperless-API)
3. ResponseBuilder-Block `_blocks_archive_search()` → `card_list`-Block mit Ergebnissen
4. Optional: Paperless Full-Text-Search-Endpoint im agent/app wrappen

**Aufwand: 8-12h**
- TieredOrchestrator Intent-Erweiterung (1h)
- Paperless-Wrapper-Endpoint + ActionHandler (3h)
- ResponseBuilder Block (2h)
- Frontend: CardListBlock reicht aus, kein neuer Block noetig (0h)
- Testen (2-4h)

**Umsetzbar: JA** — Paperless-Connector ist vorhanden, CardListBlock rendert Ergebnisse.

---

### C: Gespeicherte Filter / Ordner

**Aktueller Zustand:**
- Keine Filter-Persistenz vorhanden
- `frya_user_preferences`-Tabelle existiert bereits (Key/Value, tenant_id + user_id) — koennte als Speicher dienen
- Kein UI-Konzept fuer Ordner/gespeicherte Filter

**Vorgeschlagene Datenbankstruktur:**

```sql
CREATE TABLE frya_saved_filters (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES frya_tenants(id),
    user_id TEXT NOT NULL,
    name TEXT NOT NULL,                    -- "Allianz Q1", "Offene Rechnungen"
    filter_type TEXT NOT NULL,             -- 'inbox', 'archive', 'bookings'
    filter_params JSONB NOT NULL DEFAULT '{}',
    -- z.B. {"vendor": "Allianz", "status": "open", "date_from": "2026-01-01"}
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(tenant_id, user_id, name)
);
```

**Aufwand: 10-14h**
- DB-Migration + Repository (2h)
- API-Endpoints (CRUD: POST/GET/DELETE `/api/v1/filters`) (2h)
- Chat-Intent `SAVE_FILTER` + `SHOW_FILTER` im TieredOrchestrator (2h)
- ResponseBuilder: Filter-Liste als `card_list` mit Quick-Action-Buttons (2h)
- Frontend: keine neue Komponente noetig, Quick-Actions reichen (0h)
- Testen (2-6h)

**Umsetzbar: JA** — aber nur mittlere Prioritaet, da nutzervolumen gering.

---

### D: Dokumenten-Gruppierung (Status)

**Aktueller Zustand: VOLLSTAENDIG IMPLEMENTIERT UND AKTIV**

- `agent/app/services/grouping_service.py`: `group_inbox_items()` mit 2 Strategien (Referenz + Vendor)
- `agent/app/agents/response_builder.py`, Zeile 172-203: `_blocks_show_inbox()` ruft `group_inbox_items()` auf und erzeugt `card_group`-Block
- `ui/src/components/content/CardGroupBlock.tsx`: Accordion-Komponente mit Expand/Collapse-Animation, "Alle freigeben"-Button, Warning-Anzeige
- ContentBlock.tsx registriert `card_group` → `CardGroupBlock`

**Bekannte Luecken:**
1. `highest_badge` wird aus `confidence_label` oder `badge.label` aus dem Item ermittelt — wenn das Item kein Badge hat, faellt es auf `'Niedrig'` zurueck (moeglicherweise inkorrekt)
2. Der `total_amount` im Gruppen-Header zeigt floats ohne EUR-Formatierung (Backend gibt rohen float zurueck, `_eur()`-Hilfsmethode ist im ResponseBuilder vorhanden aber muss dort korrekt genutzt werden)
3. Dunning-Chain-Erkennung basiert auf String-Match ("mahnung") — kein strukturiertes Feld

**Aufwand fuer Bugfixes: 2-3h**

---

## Implementierungs-Reihenfolge

### Prioritaet 1 (Sofort, P-40a): Kontext-Verlust beheben — 8-10h

Root Causes sind identifiziert und behebbar:

1. **Pending-Flow-State in Redis persistieren** (statt WebSocket-Attribut)
   - Neuer Redis-Key `frya:pending_flow:{user_id}` mit 30min TTL
   - `chat_ws.py`: statt `websocket._frya_pending_flow` → `await redis.get/set`
   - Schutzt vor Reconnect-Verlust
   - Datei: `agent/app/api/chat_ws.py`, `agent/app/telegram/communicator/memory/conversation_store.py`
   - Aufwand: 3h

2. **Redis-Fehler Graceful Fallback** (kein silent Data Loss)
   - ChatHistoryStore und ConversationMemoryStore: In-Memory-Fallback wenn Redis unavailable
   - Aufwand: 1h

3. **last_case_ref durch TieredOrchestrator-Pfad durchschleifen**
   - Wenn ActionRouter Short-circuit greift, ConversationMemoryStore trotzdem updaten
   - `chat_ws.py`: nach jedem `routing_result` den ConversationMemoryStore aktualisieren
   - Aufwand: 2h

4. **Chat-History bei Reconnect nachladen** (Frontend)
   - `fryaStore.ts` connect(): nach erfolgreicher WS-Verbindung `/api/v1/chat/history` abfragen
   - Neuer Backend-Endpoint `GET /api/v1/chat/history?limit=20`
   - Aufwand: 2-3h

### Prioritaet 2 (P-40b): Ladebalken Upload — 6-8h

Alle Bausteine vorhanden, nur Verdrahtung fehlt.

1. `bulk_upload.py`: Nach jedem Paperless-Upload → `chat_registry.send_to_user(user_id, {type: 'upload_progress', ...})`
2. `fryaStore.ts`: Handler fuer `upload_progress` + uploadFiles-State
3. ChatView/GreetingScreen: PipelineStatus einbinden

### Prioritaet 3 (P-40c): Archiv-Suche — 8-12h

Erfordert neuen Intent + Paperless-Wrapper. Hohes Nutzwert-Feature.

### Prioritaet 4 (P-40d): Dokumenten-Gruppierung Bugfixes — 2-3h

Feature ist live, aber Badge-Formatierung und Amount-Darstellung koennen verbessert werden.

### Prioritaet 5 (P-40e): Gespeicherte Filter — 10-14h

Niedrigste Prioritaet. Erfordert neue DB-Tabelle und CRUD-Endpoints.

---

## Zusammenfassung Aufwand

| Feature | Aufwand | Prioritaet |
|---------|---------|------------|
| P-40a Kontext-Verlust-Fix | 8-10h | KRITISCH |
| P-40b Ladebalken Upload | 6-8h | HOCH |
| P-40c Archiv-Suche | 8-12h | MITTEL |
| P-40d Grouping Bugfixes | 2-3h | NIEDRIG |
| P-40e Gespeicherte Filter | 10-14h | NIEDRIG |
| **Gesamt** | **34-47h** | |
