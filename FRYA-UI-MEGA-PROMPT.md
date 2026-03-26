# FRYA UI MEGA-PROMPT -- Vollstaendiges Implementation Briefing

> Stand: 24.03.2026 | Version: P-46
> Ziel: Die UI-Chat-Instanz baut die komplette FRYA-Kunden-App ohne Rueckfragen.

---

## 1. SYSTEM-UEBERBLICK

FRYA ist eine KI-gesteuerte Buchhaltungsassistentin fuer kleine und mittelstaendische Unternehmen. Sie empfaengt Belege (per Telegram, E-Mail, Web-Upload oder Bulk-Upload), analysiert sie automatisch mit 8 spezialisierten KI-Agenten, erstellt Buchungsvorschlaege, ueberwacht Fristen und kommuniziert proaktiv mit dem Nutzer -- alles auf Deutsch, in einem warmen, kompetenten und leicht witzigen Ton. Die UI ist ein reines Frontend ("dummes Terminal"), das ausschliesslich ueber die REST-API und WebSocket mit dem Backend kommuniziert.

### Tech-Stack Backend

| Komponente | Technologie |
|---|---|
| Web-Framework | FastAPI (Python 3.12) |
| Agent-Orchestrierung | LangGraph (State Machine) |
| LLM-Routing | LiteLLM (Multi-Provider) |
| DMS | Paperless-ngx |
| Buchhaltung | Akaunting |
| Datenbank | PostgreSQL |
| Cache | SQLite (Memory Curator) |
| Auth | Session (Web) + JWT (Mobile) Dual-Auth |

### Die 8 Agenten

| Agent | Koerperteil | Aufgabe |
|---|---|---|
| Orchestrator | Herz | Zentrale Steuerung, Routing, Gatekeeper |
| Communicator | Mund | Kommunikation mit dem Nutzer (Chat) |
| Document Analyst | Auge | OCR, Felderkennung, Dokumentklassifikation |
| Semantic Analyst | Stirn | Semantische Analyse, Kontext, Zusammenhaenge |
| Accounting Analyst | Hand | Buchhalterische Pruefung, Kontierung, SKR03/04 |
| Risk Analyst | Nase | Duplikaterkennung, Plausibilitaet, Risiko-Flags |
| Memory Curator | Gedaechtnis | Langzeitgedaechtnis, Nutzer-Praeferenzen, Kontext |
| Deadline Analyst | Uhr | Fristen, Skonto, Mahnungen, Erinnerungen |

### Tech-Stack Frontend (Ziel)

| Komponente | Technologie |
|---|---|
| Framework | React 19 |
| Build | Vite |
| Styling | Tailwind CSS |
| State Management | Zustand |
| Design System | Material Design 3 (M3) |
| Icons | Material Symbols Rounded |
| Fonts | Outfit (Headlines) + Plus Jakarta Sans (Body) |

### Architektur-Diagramm

```
+------------------+      HTTPS/WSS       +------------------+
|                  | <------------------> |                  |
|   React 19 SPA   |   REST + WebSocket   |   FastAPI        |
|   (Vite + TW)    |                      |   Backend        |
|                  |                      |                  |
+------------------+                      +--------+---------+
                                                   |
                                    +--------------+--------------+
                                    |              |              |
                              +-----+----+  +-----+----+  +-----+----+
                              | LangGraph|  | Paperless |  | Akaunting|
                              | 8 Agents |  | -ngx DMS  |  | Buchh.   |
                              +-----+----+  +----------+  +----------+
                                    |
                              +-----+----+
                              | LiteLLM  |
                              | (Multi-  |
                              |  Provider)|
                              +----------+
```

---

## 2. DATENFLUSS

### Flow A: Dokument-Upload bis Buchung (13 Schritte)

```
1.  Nutzer laedt Beleg hoch (Web-Upload / Telegram / E-Mail)
2.  Backend erstellt Paperless-Task (DMS-Ingestion)
3.  Paperless fuehrt OCR durch und speichert Dokument
4.  Orchestrator (Herz) erkennt neues Dokument via Polling/Webhook
5.  Document Analyst (Auge) extrahiert Felder: Absender, Betrag, Datum, Positionen
6.  Semantic Analyst (Stirn) analysiert Kontext und Zusammenhaenge
7.  Risk Analyst (Nase) prueft auf Duplikate, Plausibilitaet, Anomalien
8.  Accounting Analyst (Hand) erstellt Buchungsvorschlag (Konto, Gegenkonto, MwSt)
9.  Deadline Analyst (Uhr) erkennt Faelligkeiten, Skonto-Fristen
10. Orchestrator erstellt Case (CASE-2026-XXXXX) im Status DRAFT
11. Communicator (Mund) benachrichtigt Nutzer (Telegram/Chat)
12. Nutzer prueft und gibt frei (approve) oder korrigiert (correct)
13. Backend bucht in Akaunting, Case-Status -> BOOKED
```

### Flow B: Chat mit Frya (6 Schritte, WebSocket Streaming)

```
1. Client oeffnet WebSocket: ws://host/api/v1/chat/stream?token=JWT
2. Client sendet: {"type": "message", "text": "Wie viele offene Rechnungen habe ich?"}
3. Server sendet: {"type": "typing", "active": true}
4. Server streamt: {"type": "chunk", "text": "Du hast "} -> {"type": "chunk", "text": "5 offene..."} -> ...
5. Server sendet: {"type": "message_complete", "text": "...", "case_ref": null, "suggestions": [...]}
6. Server sendet: {"type": "typing", "active": false}
```

### Flow C: Bulk Upload (4 Schritte)

```
1. Nutzer waehlt bis zu 50 Dateien (PDF/PNG/JPG/TIFF, max. 20MB je Datei)
2. POST /api/documents/bulk-upload -> batch_id + status "processing"
3. UI pollt GET /api/documents/batches/{batch_id} fuer Fortschritt
   (oder POST .../refresh fuer aktiven Refresh, rate-limited 5s)
4. Jede Datei durchlaeuft individuell Flow A (Schritte 2-13)
```

### Flow D: Duplikat erkannt (4 Schritte)

```
1. Risk Analyst (Nase) erkennt Duplikat waehrend Analyse
2. Case erhaelt Risk-Flag "duplicate_detection"
3. Nutzer wird benachrichtigt (Telegram + Inbox)
4. Nutzer entscheidet: behalten (approve) oder verwerfen (reject)
```

### Flow E: Erinnerung / Frist (4 Schritte)

```
1. Deadline Analyst (Uhr) erkennt anstehende Frist oder Skonto-Ablauf
2. Erinnerung wird erstellt (reminder_create = AUTO)
3. Communicator benachrichtigt Nutzer via Telegram/Chat
4. Nutzer reagiert oder Frist wird als ueberfaellig markiert
```

---

## 3. API-REFERENZ

Basis-URL: `https://{tenant}.frya.de` (oder `http://localhost:8000` lokal)

Alle Endpoints erfordern Authentifizierung (Bearer JWT oder Session Cookie), sofern nicht anders angegeben.

### 3.1 Auth

#### POST /api/v1/auth/login

Kein Auth erforderlich.

```json
// Request
{"email": "admin", "password": "..."}

// Response 200
{"access_token": "eyJ...", "refresh_token": "eyJ...", "expires_in": 3600}
```

#### POST /api/v1/auth/refresh

Kein Auth erforderlich (nur refresh_token).

```json
// Request
{"refresh_token": "eyJ..."}

// Response 200
{"access_token": "eyJ...", "expires_in": 3600}
```

#### POST /api/v1/auth/logout

Auth: Bearer oder Session.

```json
// Response 200
{"status": "logged_out"}
```

### 3.2 Chat

#### POST /api/v1/chat (Synchron)

Auth: Bearer oder Session.

```json
// Request
{"message": "Hallo"}

// Response 200
{
  "reply": "FRYA: Hallo! Ich habe aktuell 5 offene Vorgaenge fuer dich -- alle im Status DRAFT.",
  "case_ref": null,
  "suggestions": ["Status-Uebersicht", "Offene Belege", "Frist-Check"]
}
```

#### WS /api/v1/chat/stream?token=JWT (WebSocket Streaming)

Siehe Abschnitt 4 fuer das vollstaendige Protokoll.

### 3.3 Inbox

#### GET /api/v1/inbox

Auth: Bearer oder Session.

Query-Parameter: `status` (pending|approved|rejected), `limit` (default 50), `offset` (default 0).

```json
// Response 200
{
  "count": 34,
  "items": [
    {
      "case_id": "uuid",
      "case_number": "CASE-2026-00031",
      "vendor_name": "Tito-Express IP & Marketing GmbH",
      "amount": 10.90,
      "currency": "EUR",
      "document_type": "Sonstiges",
      "status": "DRAFT",
      "confidence_label": null,
      "created_at": "2026-03-23T22:48:13.275208",
      "due_date": null,
      "booking_proposal": null
    }
  ]
}
```

#### POST /api/v1/inbox/{case_id}/approve

Auth: Bearer oder Session.

```json
// Request
{"action": "approve|correct|reject|defer", "corrections": null}

// Response 200
{"status": "processed", "result": {...}}
```

**Actions:**
- `approve` -- Buchungsvorschlag freigeben
- `correct` -- Korrektur senden (corrections-Objekt mitgeben)
- `reject` -- Beleg ablehnen
- `defer` -- Spaeter entscheiden

#### POST /api/v1/inbox/{case_id}/learn

Auth: Bearer oder Session.

```json
// Request
{"scope": "this_only|vendor_always|category_always|ask_every_time", "rule": "..."}

// Response 200
{"status": "accepted", "scope": "vendor_always"}
```

**Scopes:**
- `this_only` -- Nur fuer diesen Beleg
- `vendor_always` -- Immer so fuer diesen Lieferanten
- `category_always` -- Immer so fuer diese Kategorie
- `ask_every_time` -- Jedes Mal nachfragen

### 3.4 Documents

#### GET /api/v1/documents

Auth: Bearer oder Session.

Query-Parameter: `query` (Volltextsuche), `limit` (default 25), `offset` (default 0).

```json
// Response 200
{
  "count": 29,
  "items": [
    {
      "id": 29,
      "title": "frya:tg-1310959044-621:Invoice RR21181402.pdf",
      "correspondent": "...",
      "document_type": "...",
      "tags": ["1", "2"],
      "created_at": "2026-03-24T14:07:24.201690+01:00",
      "thumbnail_url": "/api/v1/documents/29/thumbnail"
    }
  ]
}
```

#### GET /api/v1/documents/{id}/thumbnail

Auth: Bearer oder Session.

Response: `image/png` binary (ca. 14 KB).

#### POST /api/v1/documents/upload

Auth: Bearer oder Session. Content-Type: `multipart/form-data`.

```json
// Response 200
{
  "ref": "web-upload-abc123",
  "status": "processing",
  "message": "Dokument angenommen. Analyse laeuft.",
  "task_id": "uuid"
}
```

#### POST /api/documents/bulk-upload

Auth: Operator+. Content-Type: `multipart/form-data`. CSRF-Token erforderlich.

Limits: Max. 50 Dateien, max. 20 MB pro Datei. Erlaubte Typen: PDF, PNG, JPG, TIFF.

```json
// Response 202
{
  "batch_id": "uuid",
  "file_count": 12,
  "duplicates_skipped": 1,
  "status": "processing"
}
```

#### GET /api/documents/batches

Auth: Operator+.

Query-Parameter: `limit` (default 20, max 100), `offset` (default 0).

```json
// Response 200
{
  "batches": [
    {
      "batch_id": "uuid",
      "file_count": 12,
      "status": "processing",
      "created_at": "2026-03-24T10:00:00",
      "completed_at": null,
      "uploaded_by": "admin",
      "summary": {
        "uploading": 0,
        "uploaded": 3,
        "processing": 5,
        "completed": 3,
        "error": 0,
        "stuck": 0,
        "duplicate_skipped": 1
      },
      "items": [...]
    }
  ],
  "total": 5
}
```

#### GET /api/documents/batches/{batch_id}

Auth: Operator+. Gibt Batch-Detail mit allen Items zurueck, angereichert mit Case-Nummer und Titel.

#### POST /api/documents/batches/{batch_id}/refresh

Auth: Operator+. CSRF-Token erforderlich. Rate-Limit: 1x pro 5 Sekunden pro Batch.

Pollt Paperless, fuehrt Bridge-Schritte aus, gibt aktuellen Batch-Status zurueck (gleiches Format wie GET).

### 3.5 Cases (Vorgaenge)

#### GET /api/v1/cases

Auth: Bearer oder Session.

Query-Parameter: `status` (DRAFT|OPEN|ANALYZED|PROPOSED|APPROVED|BOOKED|PAID|CLOSED), `limit` (default 50), `offset` (default 0).

```json
// Response 200
{
  "count": 34,
  "items": [
    {
      "case_id": "uuid",
      "case_number": "CASE-2026-00031",
      "vendor_name": "Stabilo Werkzeugfachmarkt",
      "amount": 86.28,
      "currency": "EUR",
      "status": "DRAFT",
      "document_analysis": {
        "sender": "Stabilo Werkzeugfachmarkt",
        "document_number": "RE-2026-1234"
      },
      "line_items": [
        {
          "description": "Bohrmaschine Makita HR2470",
          "quantity": 1,
          "unit_price": "72.50",
          "total_price": "86.28"
        }
      ]
    }
  ]
}
```

#### GET /api/v1/cases/{case_id}

Auth: Bearer oder Session.

Wie oben, plus:

```json
{
  "timeline": [
    {
      "action": "DOCUMENT_ANALYZED",
      "result": "Rechnung erkannt, 1 Position",
      "agent": "document_analyst",
      "created_at": "2026-03-23T22:48:15.000000"
    }
  ]
}
```

### 3.6 Deadlines (Fristen)

#### GET /api/v1/deadlines

Auth: Bearer oder Session.

```json
// Response 200
{
  "overdue": [],
  "due_today": [],
  "due_soon": [],
  "skonto_expiring": [],
  "summary": ""
}
```

Jedes Array enthaelt Objekte mit: `case_id`, `case_number`, `vendor_name`, `amount`, `due_date`, `days_remaining`.

### 3.7 Finance (Finanzen)

#### GET /api/v1/finance/summary

Auth: Bearer oder Session.

Query-Parameter: `period` (month|quarter|year).

```json
// Response 200
{
  "period": "March 2026",
  "income": 4070.0,
  "expenses": 89.9,
  "open_receivables": 0.0,
  "open_payables": 0.0,
  "overdue_count": 0,
  "overdue_amount": 0.0
}
```

### 3.8 Settings (Einstellungen)

#### GET /api/v1/preferences

Auth: Operator+.

```json
// Response 200
{
  "formal_address": "du",
  "formality_level": "casual",
  "emoji_enabled": "true",
  "notification_channel": "telegram",
  "theme": "system"
}
```

#### PUT /api/v1/preferences/{key}

Auth: Operator+.

Gueltige Keys: `formal_address`, `formality_level`, `emoji_enabled`, `notification_channel`, `theme`.

```json
// Request
{"value": "dark"}

// Response 200
{"key": "theme", "value": "dark"}
```

### 3.9 Feedback

#### POST /api/v1/feedback

Auth: Operator+. Content-Type: `multipart/form-data`.

Felder:
- `description` (string, required) -- Feedback-Text
- `page` (string, optional) -- Aktuelle Seite
- `screenshot` (file, optional) -- Screenshot als Datei

```json
// Response 201
{"feedback_id": "uuid"}
```

#### GET /api/v1/feedback

Auth: Admin only. Gibt alle Feedback-Eintraege zurueck.

#### PATCH /api/v1/feedback/{feedback_id}

Auth: Admin only.

```json
// Request
{"status": "NEW|IN_PROGRESS|RESOLVED"}

// Response 200
{"feedback_id": "uuid", "status": "IN_PROGRESS"}
```

---

## 4. WEBSOCKET-PROTOKOLL

### Verbindung

```
ws://{host}/api/v1/chat/stream?token={JWT_ACCESS_TOKEN}
```

HTTPS-Variante: `wss://` fuer Produktion.

### Client -> Server

| type | Felder | Beschreibung |
|---|---|---|
| `ping` | -- | Heartbeat (alle 30s empfohlen) |
| `message` | `text` (string) | Chat-Nachricht an Frya |

### Server -> Client

| type | Felder | Beschreibung |
|---|---|---|
| `pong` | -- | Heartbeat-Antwort |
| `typing` | `active` (bool) | Schreibindikator ein/aus |
| `chunk` | `text` (string) | Streaming-Text-Fragment |
| `message_complete` | `text`, `case_ref`, `suggestions` | Vollstaendige Antwort mit Kontext |
| `error` | `message` (string) | Fehlermeldung |

### Streaming-Flow (Normalfall)

```
Client:  {"type": "message", "text": "Hallo Frya"}
Server:  {"type": "typing", "active": true}
Server:  {"type": "chunk", "text": "FRYA: Hallo! "}
Server:  {"type": "chunk", "text": "Ich habe aktuell "}
Server:  {"type": "chunk", "text": "5 offene Vorgaenge..."}
Server:  {"type": "message_complete", "text": "FRYA: Hallo! Ich habe aktuell 5 offene Vorgaenge...", "case_ref": null, "suggestions": ["Status-Uebersicht", "Offene Belege", "Frist-Check"]}
Server:  {"type": "typing", "active": false}
```

### Nicht-Streaming-Fallback

Bei Modellen ohne Streaming-Faehigkeit sendet der Server direkt `message_complete` ohne vorherige `chunk`-Nachrichten.

### Reconnect-Strategie

- Bei Verbindungsabbruch: exponentielles Backoff (1s, 2s, 4s, 8s, max 30s)
- Bei `error`-Message: Nachricht anzeigen, Verbindung bleibt offen
- Bei HTTP 401 auf WebSocket-Connect: Token refreshen, dann reconnect

### Heartbeat

- Client sendet `{"type": "ping"}` alle 30 Sekunden
- Server antwortet `{"type": "pong"}`
- Kein Pong innerhalb 10s -> Reconnect

---

## 5. AUTH-SYSTEM

### Dual-Auth-Architektur

| Methode | Verwendung | Details |
|---|---|---|
| Session (Cookie) | Web-App | Starlette SessionMiddleware, 8h Timeout |
| JWT (Bearer) | Mobile / API | HS256, Access-Token 1h, Refresh-Token 30d |
| Dual-Auth | Alle Endpoints | `require_authenticated` prueft Bearer erst, dann Session |

### Login-Flow (Web)

```
1. POST /api/v1/auth/login mit email + password
2. Response: access_token + refresh_token + expires_in
3. access_token im Memory speichern (NICHT localStorage)
4. refresh_token in httpOnly Cookie (oder secure storage)
5. Bei 401: automatisch POST /api/v1/auth/refresh
6. Bei Refresh-Fehler: Redirect zu Login
```

### Rollen

| Rolle | Level | Zugriff |
|---|---|---|
| admin | 20 | Alles inkl. User-Management, Feedback-Verwaltung |
| operator | 10 | Alles ausser User-Management |
| customer | 5 | Nur /api/v1/* Endpoints, eigene Daten |

### Token-Refresh-Logik

```
- Access-Token laeuft nach 1h ab
- 5 Minuten vor Ablauf: proaktiver Refresh
- Bei 401 auf beliebigem Endpoint: Refresh + Retry (1x)
- Refresh-Token laeuft nach 30d ab -> Logout
```

### CSRF-Schutz

Endpoints mit Seiteneffekten (POST/PUT/DELETE) benoetigen ein CSRF-Token. Das Token wird im Session-Cookie transportiert oder als Header `X-CSRF-Token` mitgesendet. Betrifft alle Bulk-Upload- und Batch-Refresh-Endpoints.

---

## 6. DESIGN-SYSTEM

### Farbsystem (Material Design 3)

| Eigenschaft | Wert |
|---|---|
| Seed Color | `#E87830` (FRYA Orange) |
| Algorithmus | M3 Tonal Palette aus Seed Color generieren |
| Primary | Aus Seed abgeleitet |
| Secondary | Aus Seed abgeleitet (komplementaer) |
| Tertiary | Aus Seed abgeleitet |
| Error | M3 Standard Error Palette |
| Surface | M3 Neutral Tones |

### Typografie

| Verwendung | Font | Gewichte |
|---|---|---|
| Headlines (H1-H6) | Outfit | 500, 600, 700 |
| Body, Labels, Buttons | Plus Jakarta Sans | 400, 500, 600 |
| Monospace (Code, IDs) | JetBrains Mono (fallback) | 400 |

### Icons

- Bibliothek: **Material Symbols Rounded**
- Stil: Rounded, Weight 400, Grade 0, Optical Size 24
- Filled fuer aktive/selektierte Zustaende
- Outlined fuer inaktive Zustaende

### Theming

| Modus | Beschreibung |
|---|---|
| Light | Standard-Modus, helle Oberflaechen |
| Dark | Dunkler Modus, invertierte Surfaces |
| System | Folgt der Betriebssystem-Einstellung |

Gespeichert ueber: `PUT /api/v1/preferences/theme` mit Wert `light`, `dark` oder `system`.

### Sprache

- **Alles auf Deutsch.** Keine englischen UI-Texte.
- Alle Uebersetzungen sind statisch in der App enthalten (kein i18n-Service noetig).

### Vollstaendiges Uebersetzungsverzeichnis

Alle internen Bezeichnungen -> deutsche UI-Labels:

#### Confidence

| Key | Deutsch |
|---|---|
| CERTAIN | Sicher |
| HIGH | Hoch |
| MEDIUM | Mittel |
| LOW | Niedrig |
| UNKNOWN | Unbekannt |

#### Case Status

| Key | Deutsch |
|---|---|
| DRAFT | Entwurf |
| OPEN | Offen |
| ANALYZED | Analysiert |
| PROPOSED | Vorgeschlagen |
| APPROVED | Freigegeben |
| REJECTED | Abgelehnt |
| BOOKED | Gebucht |
| PAID | Bezahlt |
| CLOSED | Abgeschlossen |
| ARCHIVED | Archiviert |

#### Item Status

| Key | Deutsch |
|---|---|
| OPEN | Offen |
| WAITING_USER | Wartet auf User |
| WAITING_DATA | Wartet auf Daten |
| SCHEDULED | Geplant |
| PENDING_APPROVAL | Wartet auf Freigabe |
| COMPLETED | Erledigt |
| CANCELLED | Abgebrochen |

#### Approval Mode

| Key | Deutsch |
|---|---|
| AUTO | Automatisch |
| PROPOSE_ONLY | Vorschlag |
| REQUIRE_USER_APPROVAL | Freigabe noetig |
| BLOCK_ESCALATE | Gesperrt (Eskalation) |

#### Document Type

| Key | Deutsch |
|---|---|
| INVOICE | Rechnung |
| REMINDER | Mahnung |
| CONTRACT | Vertrag |
| NOTICE | Bescheid |
| TAX_DOCUMENT | Steuerdokument |
| RECEIPT | Quittung |
| BANK_STATEMENT | Kontoauszug |
| SALARY | Lohnabrechnung |
| INSURANCE | Versicherung |
| DUNNING | Inkasso |
| CORRESPONDENCE | Korrespondenz |
| OTHER | Sonstiges |
| LETTER | Brief |

#### Risk Flags

| Key | Deutsch |
|---|---|
| duplicate_detection | Moegliches Duplikat |
| amount_consistency | Betragsabweichung |
| tax_plausibility | Steuersatz pruefen |
| vendor_mismatch | Lieferant unklar |
| date_anomaly | Datumsauffaelligkeit |
| missing_fields | Fehlende Pflichtfelder |

#### Agenten

| Key | Deutsch |
|---|---|
| orchestrator | Orchestrator (Herz) |
| communicator | Kommunikator (Mund) |
| document_analyst | Document Analyst (Auge) |
| document_analyst_semantic | Semantische Analyse (Stirn) |
| accounting_analyst | Buchhaltungsanalyse (Hand) |
| deadline_analyst | Fristenanalyse (Ohr) |
| risk_consistency | Risiko & Konsistenz (Nase) |
| memory_curator | Gedaechtnis (Hirn) |

#### Mahnstufen

| Key | Deutsch |
|---|---|
| 0 | Keine Mahnung |
| 1 | Zahlungserinnerung |
| 2 | 1. Mahnung |
| 3 | 2. Mahnung |
| 4 | Inkasso-Warnung |

#### UI-Labels

| Key | Deutsch |
|---|---|
| OVERDUE | Ueberfaellig |
| DUE_SOON | Bald faellig |
| ON_TIME | Im Zeitplan |
| NO_DEADLINE | Keine Frist |
| ACTIVE | Aktiv |
| INACTIVE | Inaktiv |
| DRAFT | Entwurf |

---

## 7. APPROVAL MATRIX

Die Approval Matrix definiert, welche Aktionen automatisch ausgefuehrt werden und welche eine Nutzerfreigabe erfordern.

| Action | Default-Modus | UI-Verhalten |
|---|---|---|
| `booking_finalize` | REQUIRE_USER_APPROVAL | Buchungsvorschlag anzeigen, Nutzer muss "Freigeben" klicken |
| `payment_proposal_create` | PROPOSE_ONLY | Zahlungsvorschlag anzeigen, Nutzer kann annehmen oder ablehnen |
| `payment_execute` | BLOCK_ESCALATE | **IMMER blockiert.** UI zeigt "Zahlung manuell ausfuehren" |
| `document_classify` | AUTO | Laeuft im Hintergrund, kein UI-Eingriff |
| `document_analyze` | AUTO | Laeuft im Hintergrund, kein UI-Eingriff |
| `accounting_review` | AUTO | Laeuft im Hintergrund, kein UI-Eingriff |
| `case_create` | AUTO | Laeuft im Hintergrund, kein UI-Eingriff |
| `case_close` | PROPOSE_ONLY | Vorschlag "Vorgang schliessen?" mit Bestaetigung |
| `reminder_create` | AUTO | Erinnerung wird automatisch erstellt |
| `invoice_create` | REQUIRE_USER_APPROVAL | Ausgangsrechnung muss explizit freigegeben werden |

### UI-Logik nach Modus

- **AUTO**: Kein UI-Element noetig, Aktion passiert unsichtbar.
- **PROPOSE_ONLY**: Vorschlag-Card mit "Annehmen" / "Ablehnen" Buttons.
- **REQUIRE_USER_APPROVAL**: Vorschlag-Card mit "Freigeben" Button. Deutlich hervorgehoben.
- **BLOCK_ESCALATE**: Roter Hinweis "Manuelle Aktion erforderlich". Kein Freigabe-Button.

---

## 8. DIE 22 SCREENS

### Screen 1: Login / Onboarding

**Beschreibung:** Anmeldeseite mit E-Mail und Passwort. Minimalistisches Design mit FRYA-Logo und Orange-Akzent. Neukunden sehen nach Erstanmeldung einen kurzen Onboarding-Flow (3 Schritte: Willkommen, Paperless verbinden, Telegram verbinden).

**API-Endpoints:**
- `POST /api/v1/auth/login`

**Key UI-Elemente:**
- E-Mail-Feld
- Passwort-Feld (mit Toggle-Sichtbarkeit)
- "Anmelden" Button (Primary, Full-Width)
- FRYA-Logo zentriert oben
- Fehleranzeige bei falschem Login

---

### Screen 2: Dashboard (Uebersicht)

**Beschreibung:** Startseite nach Login. Zeigt KPIs, offene Aufgaben und den aktuellen Finanzbericht auf einen Blick. Die wichtigsten Zahlen sind in M3-Cards angeordnet.

**API-Endpoints:**
- `GET /api/v1/inbox?status=pending&limit=5`
- `GET /api/v1/finance/summary?period=month`
- `GET /api/v1/deadlines`
- `GET /api/v1/cases?status=DRAFT&limit=5`

**Key UI-Elemente:**
- KPI-Cards: Offene Belege (count), Einnahmen, Ausgaben, Ueberfaellige Fristen
- Liste der letzten 5 offenen Inbox-Items (vendor_name + amount + status)
- Finanz-Zusammenfassung (Einnahmen/Ausgaben Chart)
- Fristen-Warnung wenn `overdue.length > 0`
- Quick-Action: "Beleg hochladen"

---

### Screen 3: Chat (Frya Conversation)

**Beschreibung:** Vollbild-Chat-Interface mit Frya. Streaming-Nachrichten, Tipp-Indikator, Vorschlags-Chips. Frya antwortet in warmem, kompetentem Deutsch.

**API-Endpoints:**
- `WS /api/v1/chat/stream?token=JWT` (primaer)
- `POST /api/v1/chat` (Fallback ohne WebSocket)

**Key UI-Elemente:**
- Chat-Bubble-Layout (Nutzer rechts, Frya links)
- Frya-Avatar (mit Herz-Icon oder FRYA-Logo)
- Tipp-Indikator (drei animierte Punkte)
- Suggestion-Chips unter der letzten Frya-Nachricht (aus `suggestions` Array)
- Text-Eingabefeld mit Sende-Button
- Auto-Scroll zum neuesten Nachricht
- Markdown-Rendering fuer Frya-Antworten

---

### Screen 4: Inbox (Offene Belege)

**Beschreibung:** Liste aller offenen Belege, die auf Nutzer-Aktion warten. Filterbar nach Status. Jeder Eintrag zeigt Lieferant, Betrag und Dokumenttyp.

**API-Endpoints:**
- `GET /api/v1/inbox?status=pending&limit=50&offset=0`

**Key UI-Elemente:**
- Filter-Tabs: Ausstehend, Freigegeben, Abgelehnt
- List-Items mit: vendor_name, amount (formatiert: "10,90 EUR"), document_type (uebersetzt), created_at
- Confidence-Badge (Sicher/Hoch/Mittel/Niedrig) wenn vorhanden
- Pull-to-Refresh
- FAB: "Beleg hochladen"
- Leerer Zustand: "Keine offenen Belege. Frya hat alles im Griff."

---

### Screen 5: Beleg-Detail

**Beschreibung:** Detailansicht eines einzelnen Belegs aus der Inbox. Zeigt extrahierte Daten, Thumbnail und Aktions-Buttons.

**API-Endpoints:**
- `GET /api/v1/cases/{case_id}`
- `GET /api/v1/documents/{id}/thumbnail`

**Key UI-Elemente:**
- Dokument-Thumbnail (oben, klickbar fuer Vollansicht)
- Extrahierte Felder: Absender, Dokumentnummer, Datum, Betrag, MwSt
- Positionen-Liste (line_items: description, quantity, unit_price, total_price)
- Risiko-Flags (wenn vorhanden, als Chips mit Warnung-Icon)
- Aktions-Leiste unten: "Freigeben", "Korrigieren", "Ablehnen", "Spaeter"

---

### Screen 6: Buchungsvorschlag

**Beschreibung:** Zeigt den KI-generierten Buchungsvorschlag fuer einen Beleg. Konto, Gegenkonto, MwSt-Satz und Buchungstext.

**API-Endpoints:**
- `GET /api/v1/cases/{case_id}` (booking_proposal im Response)

**Key UI-Elemente:**
- Buchungs-Card: Konto (SKR03/04), Gegenkonto, Betrag netto, MwSt-Satz, MwSt-Betrag, Bruttobetrag
- Buchungstext (KI-generiert)
- Confidence-Indikator
- "Freigeben" Button (Primary)
- "Korrigieren" Button (Secondary)
- "Ablehnen" Button (Tertiary/Text)

---

### Screen 7: Korrektur-Dialog

**Beschreibung:** Formular zum Korrigieren eines Buchungsvorschlags. Alle Felder sind vorbefuellt mit den KI-Werten und koennen ueberschrieben werden.

**API-Endpoints:**
- `POST /api/v1/inbox/{case_id}/approve` mit `action: "correct"` und `corrections`-Objekt

**Key UI-Elemente:**
- Editierbare Felder: Konto, Gegenkonto, Betrag, MwSt-Satz, Buchungstext
- Lern-Optionen: "Nur diesmal", "Immer fuer diesen Lieferanten", "Immer fuer diese Kategorie"
- "Korrektur senden" Button
- "Abbrechen" Button

---

### Screen 8: Dokumente (Archiv)

**Beschreibung:** Durchsuchbares Dokumentenarchiv. Zeigt alle in Paperless gespeicherten Dokumente mit Thumbnails.

**API-Endpoints:**
- `GET /api/v1/documents?query=&limit=25&offset=0`

**Key UI-Elemente:**
- Suchleiste (Volltext)
- Grid-Ansicht mit Thumbnails (2 oder 3 Spalten)
- Oder Listen-Ansicht (umschaltbar)
- Jedes Item: Thumbnail, Titel, Dokumenttyp, Datum
- Infinite Scroll oder Pagination
- Leerer Zustand: "Noch keine Dokumente im Archiv."

---

### Screen 9: Dokument-Detail

**Beschreibung:** Vollansicht eines einzelnen Dokuments aus dem Archiv. Zeigt Thumbnail gross, Metadaten und verknuepften Case.

**API-Endpoints:**
- `GET /api/v1/documents/{id}/thumbnail`
- `GET /api/v1/cases/{case_id}` (wenn verknuepft)

**Key UI-Elemente:**
- Grosses Thumbnail / PDF-Viewer
- Metadaten: Titel, Correspondent, Dokumenttyp, Tags, Erstellungsdatum
- Link zum verknuepften Vorgang (wenn vorhanden)
- "Herunterladen" Button

---

### Screen 10: Upload (Einzeln)

**Beschreibung:** Einzelner Dokumenten-Upload per Drag & Drop oder Dateiauswahl. Unterstuetzt PDF, PNG, JPG, TIFF.

**API-Endpoints:**
- `POST /api/v1/documents/upload`

**Key UI-Elemente:**
- Drag & Drop Zone (grossflaechig, gestrichelte Border)
- "Datei auswaehlen" Button
- Fortschrittsanzeige nach Upload
- Statusmeldung: "Dokument angenommen. Analyse laeuft."
- Akzeptierte Formate: PDF, PNG, JPG, TIFF (Max. 20 MB)

---

### Screen 11: Bulk Upload (Waeschekorb)

**Beschreibung:** Massen-Upload von bis zu 50 Dokumenten. Zeigt Fortschritt pro Datei und Batch-Status.

**API-Endpoints:**
- `POST /api/documents/bulk-upload`
- `GET /api/documents/batches/{batch_id}`
- `POST /api/documents/batches/{batch_id}/refresh`
- `GET /api/documents/batches`

**Key UI-Elemente:**
- Multi-Datei-Auswahl (Drag & Drop fuer mehrere Dateien)
- Datei-Liste mit individuellem Status-Icon pro Datei
- Status-Icons: Hochladend (Spinner), Hochgeladen (Check), Verarbeitung (Zahnrad), Fertig (Gruener Check), Fehler (Rotes X), Duplikat (Gelbes Dreieck)
- Fortschrittsbalken gesamt
- "Aktualisieren" Button (ruft /refresh auf)
- Batch-History (fruehere Uploads)
- Summary: "12 Dateien, 10 verarbeitet, 1 Duplikat, 1 Fehler"

---

### Screen 12: Vorgaenge (Cases)

**Beschreibung:** Liste aller Vorgaenge mit Filterfunktion nach Status. Hauptidentifikator ist vendor_name + amount, nicht die Case-ID.

**API-Endpoints:**
- `GET /api/v1/cases?status=DRAFT&limit=50&offset=0`

**Key UI-Elemente:**
- Filter-Chips: Entwurf, Offen, Analysiert, Vorgeschlagen, Freigegeben, Gebucht, Bezahlt, Abgeschlossen
- List-Items: vendor_name (primaer), amount + currency, status (uebersetzt, farbcodiert), created_at
- Case-Number als sekundaere Info (klein, grau)
- Sortierung: Neueste zuerst

---

### Screen 13: Vorgang-Detail

**Beschreibung:** Detailansicht eines Vorgangs mit Timeline aller Aktionen, extrahierten Daten und Buchungsvorschlag.

**API-Endpoints:**
- `GET /api/v1/cases/{case_id}`

**Key UI-Elemente:**
- Header: vendor_name, amount, status-Badge
- Dokument-Zusammenfassung: Absender, Dokumentnummer, Datum
- Positionen-Tabelle (line_items)
- MwSt-Aufschluesselung (Brutto, Netto, MwSt-Satz, MwSt-Betrag)
- Timeline (chronologisch): Jeder Eintrag zeigt Agent-Name (uebersetzt), Aktion, Ergebnis, Zeitstempel
- Aktions-Buttons je nach Status (Freigeben, Korrigieren, etc.)

---

### Screen 14: Fristen-Uebersicht

**Beschreibung:** Dashboard aller offenen Fristen, Faelligkeiten und Skonto-Ablaufdaten. Farblich priorisiert.

**API-Endpoints:**
- `GET /api/v1/deadlines`

**Key UI-Elemente:**
- Abschnitte: "Ueberfaellig" (rot), "Heute faellig" (orange), "Bald faellig" (gelb), "Skonto laeuft ab" (blau)
- Jeder Eintrag: vendor_name, amount, due_date, days_remaining
- Leerer Zustand pro Abschnitt: "Keine Eintraege"
- Summary-Text oben (aus API)

---

### Screen 15: Finanz-Dashboard

**Beschreibung:** Finanzuebersicht mit Einnahmen, Ausgaben, offenen Forderungen und Verbindlichkeiten. Periodenwahl (Monat/Quartal/Jahr).

**API-Endpoints:**
- `GET /api/v1/finance/summary?period=month`

**Key UI-Elemente:**
- Perioden-Tabs: Monat, Quartal, Jahr
- KPI-Cards: Einnahmen, Ausgaben, Offene Forderungen, Offene Verbindlichkeiten
- Ueberfaellig-Warnung: "X Vorgaenge ueberfaellig (Summe: Y EUR)"
- Einfaches Balken- oder Liniendiagramm (Einnahmen vs. Ausgaben)

---

### Screen 16: Erinnerungen

**Beschreibung:** Liste aktiver Erinnerungen, die Frya automatisch erstellt hat. Nutzer kann Erinnerungen bestaetigen oder verschieben.

**API-Endpoints:**
- `GET /api/v1/deadlines` (Erinnerungen sind Teil der Fristen-Daten)

**Key UI-Elemente:**
- Erinnerungs-Cards mit: Betreff, Faelligkeitsdatum, verknuepfter Vorgang
- Aktionen: "Erledigt", "Verschieben", "Details ansehen"
- Zeitliche Sortierung

---

### Screen 17: Einstellungen

**Beschreibung:** Nutzer-Einstellungen fuer FRYA: Anrede, Formalitaet, Emojis, Benachrichtigungskanal, Theme.

**API-Endpoints:**
- `GET /api/v1/preferences`
- `PUT /api/v1/preferences/{key}`

**Key UI-Elemente:**
- Toggle: Formelle Anrede (du/Sie)
- Dropdown: Formalitaet (casual/formal)
- Toggle: Emojis aktiviert
- Dropdown: Benachrichtigungskanal (telegram/email/push)
- Theme-Auswahl: Hell / Dunkel / System (3 Radio-Buttons oder Segmented Button)
- Jede Aenderung wird sofort gespeichert (kein "Speichern"-Button)

---

### Screen 18: Profil / Account

**Beschreibung:** Nutzer-Profil mit E-Mail, Rolle und Passwort-Aenderung.

**API-Endpoints:**
- Auth-Endpoints fuer Passwort-Aenderung (wenn implementiert)

**Key UI-Elemente:**
- Anzeige: E-Mail, Rolle (admin/operator/customer uebersetzt)
- "Passwort aendern" Dialog
- "Abmelden" Button
- Account-Loeschung (Link zu Rechtliches)

---

### Screen 19: Rechtliches

**Beschreibung:** DSGVO-konforme Rechtsseiten: Datenschutzerklaerung, AGB, Impressum, AVV, TOMs, VVT, Verfahrensdokumentation.

**API-Endpoints:**
- Statische Inhalte (kein API-Call noetig, oder vom Backend serviert)

**Key UI-Elemente:**
- Navigation mit 7 Unterseiten: Datenschutz, AVV, TOMs, Impressum, AGB, VVT, Verfahrensdokumentation
- Scroll-Layout fuer lange Texte
- "Daten exportieren" Button (DSGVO Art. 15)
- "Account loeschen" Button (DSGVO Art. 17)

---

### Screen 20: Feedback

**Beschreibung:** Feedback-Formular fuer Alpha-Tester. Text + optionaler Screenshot.

**API-Endpoints:**
- `POST /api/v1/feedback`

**Key UI-Elemente:**
- Textfeld fuer Beschreibung (mehrzeilig, min. 10 Zeichen)
- Optionales Screenshot-Upload (Dateiauswahl oder Kamera)
- Aktuelle Seite wird automatisch mitgesendet (page-Parameter)
- "Feedback senden" Button
- Erfolgs-Toast: "Danke fuer dein Feedback!"

---

### Screen 21: 2FA Setup

**Beschreibung:** Einrichtung der Zwei-Faktor-Authentifizierung (Post-Alpha Feature, Platzhalter-Screen).

**API-Endpoints:**
- Noch nicht implementiert

**Key UI-Elemente:**
- QR-Code Anzeige (fuer Authenticator-App)
- Eingabefeld fuer 6-stelligen Code
- "Aktivieren" Button
- Hinweis: "Dieses Feature ist in Vorbereitung."

---

### Screen 22: Benachrichtigungen

**Beschreibung:** Liste aller Benachrichtigungen (in-app Notifications). Neue Belege, Fristen, Statusaenderungen.

**API-Endpoints:**
- Zukuenftiger Endpoint (aktuell ueber Chat/Telegram)

**Key UI-Elemente:**
- Chronologische Liste mit Icon + Text + Zeitstempel
- Ungelesen-Badge im Navigation-Icon
- "Alle als gelesen markieren"
- Klick auf Notification -> Navigation zum relevanten Screen

---

## 9. ARCHITEKTUR-REGELN

### Unveraenderliche Regeln

1. **Die UI ist ein dummes Terminal.** Keine Geschaeftslogik im Frontend. Alles kommt von der API. Die UI ruft Endpoints auf, zeigt Daten an, sendet Nutzer-Aktionen zurueck.

2. **Keine LLM-Modellnamen sichtbar.** Der Nutzer sieht nie "GPT-4", "Claude", "Mistral" oder aehnliches. Frya ist die Entitaet, nicht das Modell.

3. **Alles auf Deutsch.** Jeder Text, jeder Button, jede Fehlermeldung, jeder Tooltip. Keine englischen Strings in der UI. Ausnahme: Technische Identifier wie `case_id` in URLs.

4. **Frya ist eine Entitaet.** Sie hat eine Persoenlichkeit: warm, kompetent, leicht witzig. Sie sagt "ich", nicht "das System". Die UI reflektiert das durch warme Farben (Orange), runde Ecken, freundliche Leerstaende.

5. **Multi-Tenant.** Jeder Kunde hat seine eigene Subdomain (`firma.frya.de`). Tenant-Isolation ist Backend-seitig, die UI muss nur die Subdomain korrekt im API-Call verwenden.

6. **Keine finanziellen Entscheidungen durch die UI.** Die UI zeigt Vorschlaege an und sendet Nutzer-Entscheidungen zurueck. Die UI berechnet nie Betraege, MwSt oder Buchungssaetze selbst.

7. **Case-Nummern als Identifier.** Format: `CASE-2026-XXXXX`. Die `case_id` (UUID) ist nur fuer API-Calls, nie als Anzeige fuer den Nutzer.

8. **Vendor + Betrag als primaere Anzeige.** In Listen immer den Lieferantennamen und Betrag prominent zeigen, nicht die Case-Nummer.

9. **Keine Case-IDs als Hauptidentifikator zeigen.** `vendor_name + amount` bevorzugen. Case-Number nur sekundaer.

10. **Line Items werden extrahiert.** Positionen (Beschreibung, Menge, Einzelpreis, Gesamtpreis) sind im API-Response vorhanden und muessen angezeigt werden.

11. **MwSt-Aufschluesselung.** Brutto, Netto, MwSt-Satz und MwSt-Betrag aus den Case-Details anzeigen.

12. **Memory Curator statt Mini-Kontext.** Der Chat-Kontext wird backend-seitig verwaltet. Die UI muss nur die Chat-Messages senden und empfangen, kein Kontext-Management.

13. **Passwoerter nie im Chat anzeigen.** Wenn Passwoerter eingegeben werden, direkt verarbeiten, nie in Chat-Bubbles oder Logs zeigen.

### Fehlerbehandlung

- **401 Unauthorized:** Token refreshen, bei Fehlschlag -> Login-Screen
- **403 Forbidden:** "Keine Berechtigung fuer diese Aktion"
- **404 Not Found:** "Nicht gefunden" mit Zurueck-Navigation
- **429 Rate Limited:** Retry nach angegebener Zeit, Spinner anzeigen
- **500+ Server Error:** "Etwas ist schiefgelaufen. Bitte versuche es spaeter erneut."
- **WebSocket Disconnect:** Automatischer Reconnect mit exponential Backoff

### Performance-Richtlinien

- Lazy-Loading fuer Thumbnails
- Infinite Scroll statt Pagination wo moeglich
- Debounce fuer Suchfelder (300ms)
- Optimistic UI fuer Approve/Reject Aktionen
- Skeleton-Loading-States fuer alle Datenlisten

---

## 10. SKILLS

Die folgenden Skills stehen der UI-Chat-Instanz zur Verfuegung und MUESSEN als MCP-Skills im Projekt-Setup aktiviert werden:

### frontend-design (Anthropic)

Quelle: Anthropic-eigener Skill fuer Frontend-Design-Entscheidungen. Wird verwendet fuer Layout-Entscheidungen, Spacing, visuelle Hierarchie und M3-Implementierung.

### web-design-guidelines (Vercel)

Quelle: Vercel v0 Skill. Enthielt Richtlinien fuer modernes Web-Design: Accessibility, responsive Layouts, Farbkontraste, Touch-Targets (min. 48px).

### react-best-practices (Vercel)

Quelle: Vercel v0 Skill. React-spezifische Best Practices: Hooks, Suspense, Error Boundaries, React 19 Features (use(), Server Components Awareness).

### composition-patterns (Vercel)

Quelle: Vercel v0 Skill. Kompositions-Patterns fuer React: Compound Components, Render Props, Slots, Provider Pattern, Container/Presentational Split.

### react-native-skills (Vercel)

Quelle: Vercel v0 Skill. Fuer zukuenftige mobile App-Entwicklung. Nicht fuer die Web-App relevant, aber als Referenz fuer spaetere React Native Migration.

---

## 11. POST-ALPHA FEATURES

Die folgenden Features sind geplant, aber NICHT im aktuellen Alpha-Scope. Die UI sollte dafuer keine Implementierung enthalten, aber das Layout sollte erweiterbar sein.

| Feature | Beschreibung | Prio |
|---|---|---|
| Kostenstellen | Buchungen auf Kostenstellen verteilen | Hoch |
| Fax-Schnittstelle | Belege per Fax empfangen | Mittel |
| iOS App | Native iOS App (React Native) | Hoch |
| CSV Export | Buchungen als CSV exportieren | Mittel |
| SEPA-Ueberweisungen | Zahlungen direkt ausfuehren | Niedrig |
| Bank API | Kontosaetze automatisch abrufen (FinTS/PSD2) | Mittel |
| Onboarding-Flow | Gefuehrte Ersteinrichtung (Paperless, Telegram, Akaunting) | Hoch |
| Pipeline-Status-Polling | Upload-Status in Echtzeit abfragen (aktuell nur Paperless-intern) | Mittel |
| 2FA | Zwei-Faktor-Authentifizierung | Mittel |

---

**Ende des Briefings.** Dieses Dokument enthaelt alle Informationen, die fuer die vollstaendige Implementierung der FRYA-Kunden-UI benoetigt werden. Keine Rueckfragen erforderlich.
