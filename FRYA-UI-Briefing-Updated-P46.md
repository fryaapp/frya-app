# FRYA UI-Briefing — Stand P-46 (24.03.2026)

## A. API-Endpoints (mit echten Response-Beispielen)

### Auth

**POST /api/v1/auth/login**
```
Request: {"email": "admin", "password": "..."}
Response: {"access_token": "eyJ...", "refresh_token": "eyJ...", "expires_in": 3600}
```

**POST /api/v1/auth/refresh**
```
Request: {"refresh_token": "eyJ..."}
Response: {"access_token": "eyJ...", "expires_in": 3600}
```

**POST /api/v1/auth/logout** (Auth required)
```
Response: {"status": "logged_out"}
```

### Chat

**POST /api/v1/chat** (Auth required)
```
Request: {"message": "Hallo"}
Response: {
  "reply": "FRYA: Hallo! Ich habe aktuell 5 offene Vorgänge für dich — alle im Status DRAFT.",
  "case_ref": null,
  "suggestions": ["Status-Übersicht", "Offene Belege", "Frist-Check"]
}
```

**WS /api/v1/chat/stream?token=JWT** (WebSocket)
```
→ {"type": "ping"}
← {"type": "pong"}

→ {"type": "message", "text": "Hallo"}
← {"type": "typing", "active": true}
← {"type": "chunk", "text": "FRYA: Hallo! "}
← {"type": "chunk", "text": "Ich habe aktuell "}
← {"type": "chunk", "text": "5 offene Vorgänge..."}
← {"type": "message_complete", "text": "FRYA: Hallo! Ich habe...", "case_ref": null, "suggestions": [...]}
```

### Inbox

**GET /api/v1/inbox?status=pending&limit=50&offset=0** (Auth required)
```
Response: {
  "count": 34,
  "items": [{
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
  }]
}
```

**POST /api/v1/inbox/{case_id}/approve** (Auth required)
```
Request: {"action": "approve|correct|reject|defer", "corrections": null}
Response: {"status": "processed", "result": {...}}
```

**POST /api/v1/inbox/{case_id}/learn** (Auth required)
```
Request: {"scope": "this_only|vendor_always|category_always|ask_every_time", "rule": "..."}
Response: {"status": "accepted", "scope": "vendor_always"}
```

### Cases

**GET /api/v1/cases?status=DRAFT&limit=50&offset=0** (Auth required)
```
Response: {
  "count": 34,
  "items": [{
    "case_id": "uuid",
    "case_number": "CASE-2026-00031",
    "vendor_name": "Stabilo Werkzeugfachmarkt",
    "amount": 86.28,
    "currency": "EUR",
    "status": "DRAFT",
    "document_analysis": {"sender": "...", "document_number": "..."},
    "line_items": [{"description": "...", "quantity": 1, "total_price": "..."}]
  }]
}
```

**GET /api/v1/cases/{case_id}** (Auth required)
```
Response: Wie oben, plus "timeline": [{action, result, agent, created_at}]
```

### Documents

**GET /api/v1/documents?query=&limit=25&offset=0** (Auth required)
```
Response: {
  "count": 29,
  "items": [{
    "id": 29,
    "title": "frya:tg-1310959044-621:Invoice RR21181402.pdf",
    "correspondent": "...",
    "document_type": "...",
    "tags": ["1", "2"],
    "created_at": "2026-03-24T14:07:24.201690+01:00",
    "thumbnail_url": "/api/v1/documents/29/thumbnail"
  }]
}
```

**GET /api/v1/documents/{id}/thumbnail** (Auth required)
```
Response: image/png binary (14494 bytes typical)
```

**POST /api/v1/documents/upload** (Auth required, multipart/form-data)
```
Response: {"ref": "web-upload-abc123", "status": "processing", "message": "Dokument angenommen. Analyse läuft.", "task_id": "uuid"}
```

### Deadlines

**GET /api/v1/deadlines** (Auth required)
```
Response: {
  "overdue": [],
  "due_today": [],
  "due_soon": [],
  "skonto_expiring": [],
  "summary": ""
}
```

### Finance

**GET /api/v1/finance/summary?period=month|quarter|year** (Auth required)
```
Response: {
  "period": "March 2026",
  "income": 4070.0,
  "expenses": 89.9,
  "open_receivables": 0.0,
  "open_payables": 0.0,
  "overdue_count": 0,
  "overdue_amount": 0.0
}
```

---

## B. Was sich seit dem Original-Briefing geändert hat

- **Case-Nummern:** `CASE-2026-XXXXX` (nicht `doc-N`). `doc-N` ist die Orchestration-ID.
- **Line Items:** Positionen werden extrahiert (description, quantity, unit_price, total_price)
- **MwSt-Aufschlüsselung:** Brutto, Netto, MwSt-Satz, MwSt-Betrag in Case-Details
- **Duplikat-Erkennung:** Paperless-Task-Polling nach Upload, Telegram-Warnung mit Buttons
- **Analyse-Notifications:** INCOMPLETE/LOW_CONFIDENCE → Telegram-Nachricht (kein stilles Warten)
- **Memory Curator:** Ersetzt den Mini-Kontext. 7+ Blöcke: AGENT, NUTZER, PRINZIPIEN, LANGZEITGEDÄCHTNIS, HEUTE, GESTERN, DMS-STATE, AKTUELLE VORGÄNGE, AKTUELLER VORGANG
- **Risky-Filter entfernt:** "bezahlt", "überwiesen" etc. nicht mehr blockiert. Orchestrator ist Gatekeeper.
- **Chat-History:** Als messages-Array an LLM (nicht als Text im System-Prompt)
- **[AKTUELLER VORGANG]** wird in die User-Message eingebaut (nicht im System-Prompt versteckt)
- **Kostenstellen:** Post-Alpha Feature (noch nicht implementiert)

---

## C. Auth-System

| Methode | Verwendung | Details |
|---------|------------|---------|
| Session (Cookie) | Web-App | Starlette SessionMiddleware, 8h Timeout |
| JWT (Bearer) | Mobile / API | HS256, Access 1h, Refresh 30d |
| Dual-Auth | Alle Endpoints | `require_authenticated` prüft Bearer erst, dann Session |

**Rollen:**
| Rolle | Level | Zugriff |
|-------|-------|---------|
| admin | 20 | Alles |
| operator | 10 | Alles außer User-Management |
| customer | 5 | Nur /api/v1/* Endpoints, eigene Daten |

---

## D. WebSocket-Protokoll

### Verbindung
```
ws://host/api/v1/chat/stream?token=JWT_ACCESS_TOKEN
```

### Client → Server
| type | Felder | Beschreibung |
|------|--------|-------------|
| `ping` | - | Heartbeat |
| `message` | `text` | Chat-Nachricht |

### Server → Client
| type | Felder | Beschreibung |
|------|--------|-------------|
| `pong` | - | Heartbeat-Antwort |
| `typing` | `active` (bool) | Schreibindikator |
| `chunk` | `text` | Streaming-Text-Fragment |
| `message_complete` | `text`, `case_ref`, `suggestions` | Vollständige Antwort |
| `error` | `message` | Fehlermeldung |

### Streaming-Flow
1. Client sendet `{"type": "message", "text": "..."}`
2. Server: `typing` → `chunk` × N → `message_complete` → `typing off`
3. Bei nicht-streaming-fähigem Modell: direkt `message_complete`

---

## E. Approval Matrix

| Action | Default-Modus | Beschreibung |
|--------|--------------|-------------|
| booking_finalize | REQUIRE_USER_APPROVAL | Buchung freigeben |
| payment_proposal_create | PROPOSE_ONLY | Zahlungsvorschlag |
| payment_execute | BLOCK_ESCALATE | Zahlung ausführen (IMMER blockiert) |
| document_classify | AUTO | Dokumentklassifikation |
| document_analyze | AUTO | Dokumentanalyse |
| accounting_review | AUTO | Buchhalterische Prüfung |
| case_create | AUTO | Vorgang anlegen |
| case_close | PROPOSE_ONLY | Vorgang schließen |
| reminder_create | AUTO | Erinnerung anlegen |
| invoice_create | REQUIRE_USER_APPROVAL | Ausgangsrechnung |

---

## F. Übersetzungen

### Confidence
| Key | Deutsch |
|-----|---------|
| CERTAIN | Sicher |
| HIGH | Hoch |
| MEDIUM | Mittel |
| LOW | Niedrig |

### Case Status
| Key | Deutsch |
|-----|---------|
| DRAFT | Entwurf |
| OPEN | Offen |
| OVERDUE | Überfällig |
| PAID | Bezahlt |
| CLOSED | Abgeschlossen |

### Document Type
| Key | Deutsch |
|-----|---------|
| INVOICE | Rechnung |
| REMINDER | Mahnung |
| CONTRACT | Vertrag |
| NOTICE | Bescheid |
| TAX_DOCUMENT | Steuerdokument |
| RECEIPT | Quittung |
| BANK_STATEMENT | Kontoauszug |
| PAYSLIP | Lohnabrechnung |
| INSURANCE | Versicherung |
| PRIVATE | Privat |
| LETTER | Brief |
| OTHER | Sonstiges |

---

## G. Was die UI NICHT tun darf

- Kein LLM-Modellname sichtbar
- Kein LLM-Routing in der UI
- Alles auf Deutsch
- Keine Buchungen/Zahlungen direkt ausführen — nur Vorschläge
- Keine Case-IDs als Hauptidentifikator zeigen (vendor_name + amount bevorzugen)

---

## H. Offene Backend-Items die UI betreffen

- **Kostenstellen:** Nach Alpha geplant
- **Fax-Schnittstelle:** Verschoben
- **Onboarding-Flow:** Noch zu bauen
- **FRYA_JWT_SECRET:** Muss auf dem Server als Env-Var gesetzt werden (aktuell leer = unsicher)
- **Document Upload via API:** Funktioniert, aber Pipeline-Status-Polling fehlt noch in der API (nur Paperless-intern)
