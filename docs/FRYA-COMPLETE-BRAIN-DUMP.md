# FRYA — Kompletter Projekt-Kontext (für NotebookLM)

Stand: 27.03.2026

---

## 1. Was ist FRYA?

FRYA ist eine KI-Buchhaltungsassistentin für Kleinunternehmer und Freelancer in Deutschland. Der User chattet mit Frya, wirft Belege rein (PDF/Foto), und Frya erledigt die Buchhaltung automatisch: OCR, Buchungsvorschlag, Freigabe, GoBD-konforme Buchung, Fristüberwachung, Mahnungen, EÜR, USt-Voranmeldung, DATEV-Export.

### Tech-Stack
- **Frontend:** React 19 + Vite + TypeScript + Zustand (State) + Tailwind v4
- **Backend:** Python FastAPI + LiteLLM (Multi-LLM) + PostgreSQL + Redis
- **LLM-Agents:** Anthropic Claude Sonnet (Communicator), IONOS Mistral-Small-24B (Router, Fallback), Llama 405B (Deep Orchestrator), LightOnOCR (Dokumentenanalyse), GPT-OSS 120B (Risikoanalyse)
- **Infrastruktur:** Hetzner VPS, Docker Compose, Traefik (Reverse Proxy + TLS), Gotenberg (PDF), Paperless-ngx (OCR), n8n (Workflows), Brevo (Mail)
- **Domains:** app.staging.myfrya.de, www.myfrya.de, api.staging.myfrya.de

### Design-System
- Material Design 3 mit Seed-Farbe #E87830 (FRYA Orange)
- Fonts: Outfit (Display), Plus Jakarta Sans (Body), Material Symbols Rounded (Icons)
- Dark Mode als Default, Light Mode als Option

---

## 2. Architektur

### Frontend (nach Rebuild 27.03.2026)
- KEIN React Router — State-driven: Login → Greeting → Chat
- Unified Store (fryaStore.ts) mit Auth + Chat + WebSocket
- 13 Content-Block-Komponenten (CardBlock, FormBlock, ChartBlock, etc.)
- Chat-Interface wie Claude.ai aber wärmer
- Drag & Drop Upload auf gesamte Chat-Area
- BugReportOverlay als unabhaengiges Modal (funktioniert auf jeder Seite)

### Backend Pipeline
```
User-Nachricht → TieredOrchestrator (3 Ebenen)
  Ebene 1: Regex-Patterns (<5ms) → 12 Intents
  Ebene 2: Mistral 24B Intent-Klassifikation (~250ms)
  Ebene 3: Deep Orchestrator / Communicator (2-30s)
→ Communicator (Anthropic Claude Sonnet) generiert Text
→ Service-Registry holt Daten (Inbox, Finance, etc.)
→ ResponseBuilder baut content_blocks + actions
→ WebSocket sendet message_complete an Frontend
```

### Datenbank-Tabellen
- frya_users (username, email, role, password_hash, tenant_id, totp)
- frya_user_preferences (key-value: display_name, theme, etc.)
- frya_user_memory (intent_counts, preferred_brevity)
- frya_bookings (GoBD: Write-Once, Hash-Chain, Advisory Lock)
- frya_contacts (18 Felder inkl. category, skonto, tags)
- frya_accounts (36 SKR03-Konten pro Tenant)
- frya_open_items (Forderungen/Verbindlichkeiten)
- frya_invoices + frya_invoice_items (Ausgangsrechnungen)
- frya_agent_llm_config (10 LLM-Agents mit Provider/Model/Key)
- frya_cases (Dokumenten-Pipeline: DRAFT → OPEN → BOOKED)

### GoBD-Konformitaet
- Buchungen sind Write-Once (kein UPDATE, kein DELETE)
- Hash-Chain: SHA-256, pipe-separated, created_at auf Sekunden normalisiert
- Advisory Lock: pg_advisory_xact_lock verhindert parallele Buchungsnummern
- Stornierung: Gegenbuchung (nicht Loeschung)
- Verify-Endpoint: GET /admin/verify-hash-chain

---

## 3. Session 27.03.2026 — Was gebaut wurde

### Backend-Fixes
1. **Hash-Chain repariert** — Root Cause: datetime Mikrosekunden-Drift + JSON Unicode-Escaping. Fix: pipe-separated Format, created_at auf Sekunden, gross_amount auf 2 Dezimalstellen. 25 Buchungen rehasht, alle valid.

2. **Display-Name persistent** — Chat "Ich heiße X" → Regex-Erkennung → frya_user_preferences upsert. Greeting zeigt "Abend Maze!" statt "testkunde".

3. **PDF-Rechnungen** — InvoiceService: create (DRAFT) → finalize (SENT + Buchung + Open Item) → PDF via Gotenberg (41KB). Lückenlose Nummern: RE-2026-001 bis RE-2026-005.

4. **GDPR Export gefixt** — 500er Bug: case.case_id → str(case.id). Jetzt ZIP mit tenant.json, cases.json, documents_metadata.json, audit_log.json, users.json.

5. **Anthropic Fallback** — try-except um litellm.acompletion: APIError/Timeout/InternalServerError → IONOS Mistral-Small-24B als Fallback. Gleicher System-Prompt.

6. **Kontakt-Erweiterung** — +6 DB-Spalten (category, default_payment_terms_days, default_skonto_percent, default_skonto_days, tags, paperless_correspondent_id). 14 Contacts → SUPPLIER, 3 → CUSTOMER migriert.

7. **Dossier-Endpoint** — GET /contacts/{id}/dossier: Kontakt + Stats (Revenue, Expenses, Open Amount) + Recent Bookings + Open Items.

8. **TieredOrchestrator** — 3-Ebenen Intent-Routing: Regex (12 Patterns, <5ms) → Mistral 24B Fast (DB-Config, ~250ms) → Deep (Llama 405B). Integriert in WebSocket + REST Chat.

9. **ActionRouter** — 14 Handler fuer Button-Klicks: approve, reject, defer, list_pending, show_deadlines, show_finance, get_dossier, list_bookings, list_open_items, prepare_form, finalize, export_datev, show_settings, update_setting, mark_private.

10. **ResponseBuilder** — Baut content_blocks (card_list, key_value, chart, form, export, progress, alert) + actions (primary/secondary/text Buttons) aus Intent + Daten.

11. **Settings-Endpoint** — GET/PUT /api/v1/settings: Liest/schreibt frya_user_preferences (display_name, theme, formal_address, notification_channel).

12. **Form-System** — 4 Form-Schemas (Invoice, Contact, Settings, Correction) + form_submit WS Handler + form_handlers.py Wrapper.

### Frontend-Rebuild
- Kompletter Neubau: Router entfernt, 14 alte Pages in _deprecated/ verschoben
- Neuer State-Flow: Login → GreetingScreen → ChatView
- fryaStore.ts: Auth + Chat + WebSocket in einem Store
- 13 Content-Block-Komponenten: Inline-Styles mit CSS Custom Properties
- ChatMessage: User (rechts, primary-container) + Frya (links, Avatar + Text + Blocks + Actions)
- Responsive: Mobile + Desktop gleicher Code
- BugReportOverlay: Screenshot + Textarea + Absenden (POST /feedback)

### Bugfixes
- "Unbekannter Nachrichtentyp: None" → sendAction nutzte type:'action' statt type:'message' mit quick_action
- Content-Blocks leer → 3 Root Causes: agent_results={}, _conf_color(None) crash, Finance field name mismatch
- Greeting: \u2026 → echte Ellipse, Doppelte Warnung → nur in roter Box
- FRYA: Prefix → gestrippt in WS + REST Handler

---

## 4. Server-Infrastruktur

### Container (12 Stueck, alle laufen)
| Container | RAM | Funktion |
|-----------|-----|----------|
| dms-staging-backend-1 | 238 MB | FastAPI Backend |
| frya-ui | 5 MB | nginx + SPA |
| frya-postgres | 83 MB | PostgreSQL |
| frya-redis | 10 MB | Token-Cache |
| frya-paperless | 958 MB | OCR |
| frya-n8n | 325 MB | Workflows |
| frya-gotenberg | 15 MB | PDF-Konvertierung |
| frya-tika | 290 MB | Dokument-Parsing |
| dms-staging-traefik-1 | 34 MB | Reverse Proxy |
| frya-uptime-kuma | 124 MB | Monitoring |
| frya-watchtower | 10 MB | Auto-Updates |
| frya-keys-ui | 6 MB | API-Keys UI |

Server: Hetzner, 7.6 GB RAM, 75 GB Disk (53% belegt)

### Deployment
- Frontend: npm run build → scp dist/ → docker compose restart frya-ui
- Backend: scp .py → docker cp → docker stop/start
- Kein Git auf Server, kein CI/CD

### Domains
- app.staging.myfrya.de → frya-ui (TLS via Let's Encrypt)
- www.myfrya.de → frya-ui (TLS via Let's Encrypt)
- api.staging.myfrya.de → Backend (TLS via Let's Encrypt)
- myfrya.de (ohne www) → anderer Server (Hetzner DNS manuell aendern!)

---

## 5. API Endpoints

### Auth
- POST /auth/login → JWT Token
- POST /auth/refresh → neuer Token
- POST /auth/forgot-password → Reset-Mail via Brevo
- POST /auth/reset-password → Passwort setzen

### Chat
- POST /chat → Synchroner Chat (text + content_blocks + actions + routing)
- WS /chat/stream → WebSocket (typing, chunk, message_complete, form_submit)

### Daten
- GET /inbox → 38 Cases (DRAFT/OPEN)
- POST /inbox/{id}/approve → Freigabe/Ablehnung
- GET /deadlines → Ueberfaellig/Heute/Bald/Skonto
- GET /contacts → 18 Kontakte
- GET /contacts/{id}/dossier → Kundenakte
- GET /bookings → 25 Buchungen
- GET /open-items → 449 Offene Posten
- GET /finance/summary → Einnahmen/Ausgaben
- GET /reports/euer → EÜR
- GET /reports/ust → USt-Voranmeldung
- POST /invoices → Rechnung erstellen (DRAFT)
- POST /invoices/{id}/finalize → SENT + Buchung + OP
- GET /invoices/{id}/pdf → PDF Download
- GET /settings → User-Einstellungen
- PUT /settings → Einstellungen aendern
- GET /admin/verify-hash-chain → GoBD Integritaetspruefung
- GET /gdpr/export → DSGVO Datenexport (ZIP)
- GET /greeting → Personalisierte Begruessung

---

## 6. LLM-Agents (10 in DB)

| Agent | Provider | Model | Aufgabe |
|-------|----------|-------|---------|
| communicator | Anthropic | claude-sonnet-4-6 | Chat-Antworten |
| communicator_fallback | IONOS | Mistral-Small-24B | Fallback bei Anthropic-Ausfall |
| orchestrator | IONOS | Llama-3.1-405B-FP8 | Komplexe Multi-Agent-Tasks |
| orchestrator_router | IONOS | Mistral-Small-24B | Fast Intent-Klassifikation |
| document_analyst | IONOS | LightOnOCR-2-1B | Beleg-OCR |
| document_analyst_semantic | IONOS | Mistral-Small-24B | Semantische Analyse |
| accounting_analyst | IONOS | Mistral-Small-24B | SKR03 Buchungsvorschlaege |
| deadline_analyst | IONOS | Mistral-Small-24B | Fristueberwachung |
| memory_curator | IONOS | GPT-OSS-120B | Chat-Kontext-Analyse |
| risk_consistency | IONOS | GPT-OSS-120B | Risikoanalyse |

---

## 7. Offene Punkte / Naechste Schritte

1. **Text-Streaming** — Communicator gibt Text als Ganzes, kein Token-fuer-Token Streaming
2. **DNS myfrya.de** — Root-Domain zeigt auf falschen Server
3. **Multi-Tenant API** — Separater Invite-Endpoint fuer programmatisches Onboarding
4. **CI/CD** — Kein Git auf Server, kein automatisiertes Deployment
5. **Approve-Flow im Chat** — ActionRouter approve/reject/defer sind verdrahtet aber muessen im Frontend getestet werden
6. **Chart-Blöcke** — Donut-Chart im Frontend gebaut (SVG), aber Backend liefert noch keine chart-Daten
7. **Mahnung** — Dunning-PDF existiert (Gotenberg), aber kein Chat-Intent dafuer
8. **Backup-Strategie** — 14 Backups auf Server, aber kein automatisierter Backup-Job
9. **Mobile Testing** — Responsive CSS vorhanden, aber nicht visuell getestet
10. **Bedrock EU** — Fuer Produktion: Anthropic ueber AWS Bedrock (stabiler als direkte API)

---

## 8. Maze's Praeferenzen

- "FRYA" und "das Frontend" = die Chat-App (www.myfrya.de)
- "Backend" = die Operator UI (api.staging.myfrya.de)
- Design soll warm, dunkel, luxurioes-minimal sein — KEIN generisches SaaS
- Immer RuFlo v3.5 maximal nutzen (Swarms, Model-Routing, Security)
- Passwoerter nie im Chat anzeigen
- IONOS LiteLLM: immer openai/ Prefix
- Proaktive Design/UX-Vorschlaege erwuenscht
- Deutsch in allen User-facing Texten
