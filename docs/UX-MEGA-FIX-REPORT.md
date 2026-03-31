# UX Mega-Fix Report — 31.03.2026

## 1. Trust Boundary

- Feld-Filterung implementiert: **JA** (provider-basiert)
- Provider-Check (Bedrock=voll, non-Bedrock=gefiltert): **JA**
- Betroffene Felder: IBANs, Steuernummern werden bei non-Bedrock Providern entfernt
- Datei: `agent/app/telegram/communicator/service.py` — `_filter_sensitive_context()`
- **Erkenntnis:** Es gab KEINE vorherige Feld-Filterung im Code. IBANs, Betraege etc. wurden IMMER an den LLM gesendet. Jetzt neu: Provider-basierter Filter (Bedrock EU = voll, andere = gefiltert).

## 2. Bedrock EU

- AWS Credentials konfiguriert: **JA** (in staging.env)
- Region: eu-central-1 (Frankfurt)
- Model: `anthropic.claude-sonnet-4-6-20250514-v1:0`
- DB-Migration vorbereitet: **JA** (`scripts/migrate_bedrock.sql`)
- LiteLLM Bedrock-Support: `bedrock/` Prefix wird automatisch gesetzt
- Bedrock-spezifisch: `api_key` und `api_base` werden NICHT an LiteLLM uebergeben (AWS Env Vars stattdessen)
- **Naechster Schritt:** `migrate_bedrock.sql` auf dem Staging-Server ausfuehren

## 3. LLM-Suggestions

- Communicator-Prompt erweitert: **JA** — SUGGESTIONS-Block mit Regeln + Beispielen
- Suggestions aus LLM extrahiert: **JA** — `_parse_llm_suggestions()` parst `SUGGESTIONS_JSON:` aus Antwort
- Statische Matrix als Fallback: **JA** — ResponseBuilder nutzt LLM-Suggestions > CONTEXT_SUGGESTIONS
- APPROVE-Intent ausgenommen (hat quick_action Buttons)
- max_tokens erhoet: 300 -> 450 (Suggestions brauchen ~50 extra Tokens)
- **Dateien:** `prompts.py`, `service.py`, `models.py`, `response_builder.py`, `chat_ws.py`, `customer_api.py`

## 4. Aufklappen

- CardListBlock: expand statt Chat-Befehl: **JA**
- Backend sendet ALLE Items mit `initial_count: 5`
- Frontend zeigt erste 5, Rest per Button aufklappbar
- Kein Server-Roundtrip mehr
- "Weniger anzeigen" Button zum Zuklappen
- **Dateien:** `response_builder.py` (_blocks_show_inbox), `CardListBlock.tsx`

## 5. Leere Blocks

- Null-Check im ResponseBuilder: **JA** — `_block_has_data()` Methode
- Filtert: leere key_value (alle Werte None/—/?), leere card_list (keine Items), leere table (keine Rows)
- Angewendet in `build()` nach Content-Block-Generation

## 6. Brevo

- API Key konfiguriert: **PRUEFEN** (FRYA_BREVO_API_KEY in .env auf Server setzen)
- Mail-Service existiert: **JA** (`mail_service.py` mit `_send_brevo()`)
- Attachment-Support hinzugefuegt: **JA** (fuer Invoice-PDF-Versand)
- Test-Mail: **Auf Server ausfuehren**

## 7. Erste Rechnung

- Invoice-Erstellung: **EXISTIERT** (`POST /api/v1/invoices`)
- Finalize: **EXISTIERT** (`POST /api/v1/invoices/{id}/finalize`)
- PDF-Generation: **EXISTIERT** (`GET /api/v1/invoices/{id}/pdf`)
- ZUGFeRD-Einbettung: **EXISTIERT** (Factur-X BASIC)
- Per E-Mail senden: **NEU** (`POST /api/v1/invoices/{id}/send`)
  - Generiert PDF, bettet ZUGFeRD ein, sendet per Brevo/Mailgun
  - Request: `{"recipient_email": "test@myfrya.de"}`
- **Datei:** `pdf_views.py`

## 8. Deploy-Pfad

- **Status:** Erfordert SSH-Zugang zum Staging-Server
- Pruefen: nginx root, aktueller Build-Pfad, Backend Docker context
- **Auf Server ausfuehren**

## Geaenderte Dateien

| Datei | Aenderung |
|-------|-----------|
| `agent/app/telegram/communicator/prompts.py` | +SUGGESTIONS Block im System-Prompt |
| `agent/app/telegram/communicator/service.py` | +Trust-Boundary Filter, +Suggestions Parser, Bedrock api_key Skip |
| `agent/app/telegram/communicator/models.py` | +llm_suggestions Feld in CommunicatorResult |
| `agent/app/agents/response_builder.py` | LLM-Suggestions Prioritaet, _block_has_data(), ALL items fuer inbox |
| `agent/app/api/chat_ws.py` | LLM-Suggestions Durchreichung an ResponseBuilder |
| `agent/app/api/customer_api.py` | LLM-Suggestions fuer REST-Endpoint |
| `agent/app/api/pdf_views.py` | +POST /invoices/{id}/send (PDF+Mail) |
| `agent/app/email/mail_service.py` | +Attachment-Support fuer Brevo |
| `ui/src/components/content/CardListBlock.tsx` | Client-side Expand/Collapse |
| `staging.env` | +AWS Bedrock Credentials |
| `scripts/migrate_bedrock.sql` | DB-Migration fuer Communicator auf Bedrock |
