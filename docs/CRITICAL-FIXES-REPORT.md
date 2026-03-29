# Critical Fixes Report — 27.03.2026

## Fix 1: Hash-Chain

- **Root Cause:** D (Datetime-Precision + JSON Serialization)
  - `created_at` hatte Mikrosekunden-Drift zwischen Python `str(datetime.now())` bei CREATE und `str(asyncpg_datetime)` bei VERIFY
  - `json.dumps()` escaped Unicode (em-dash → `\u2014`) unterschiedlich je nach Kontext
  - Keine deterministische Normalisierung der Felder vor dem Hashen
- **Was geändert:**
  - `agent/app/accounting/repository.py` — `compute_booking_hash()` komplett umgebaut:
    - Pipe-separiertes Format statt JSON (`|`-getrennt, kein Unicode-Escaping)
    - `created_at` auf Sekunden-Präzision normalisiert (`strftime('%Y-%m-%dT%H:%M:%S')`)
    - `gross_amount` auf 2 Dezimalstellen normalisiert (`f'{float(amount):.2f}'`)
  - `agent/app/accounting/booking_service.py` — Verify nutzt dieselbe Normalisierung (native Typen statt `str()`)
- **Hash-Neuberechnung:** Ja (24 Buchungen im Staging rehasht — Testdaten)
- **DB-Permission-Fix:** `GRANT ALL ON frya_user_preferences TO frya_app;`
- **booking_type Fix:** 2 Buchungen hatten `OUTGOING_INVOICE` (ungültiger Literal) → auf `INCOME` korrigiert

### Verify-Ergebnis

| | Vorher | Nachher |
|---|---|---|
| Status | `{"valid": false, "total": 18, "errors": ["Booking #1: hash mismatch", ...]}` | `{"valid": true, "total": 25, "errors": []}` |
| Neue Buchung | n/a | #25 erstellt → Chain bleibt valid ✅ |

## Fix 2: GDPR Export

- **Root Cause:** Code-Bug — `case.case_id` statt `case.id` (CaseRecord hat kein `case_id` Attribut)
- **Was geändert:** `agent/app/api/gdpr_views.py` Zeile 81: `case.case_id` → `str(case.id)`
- **Export Format:** ZIP-Archiv mit JSON-Dateien

| Datei | Inhalt | Größe |
|-------|--------|-------|
| tenant.json | Tenant-Metadaten | 320 B |
| cases.json | Alle Cases | 30 KB |
| documents_metadata.json | Dokument-Metadaten | 23 KB |
| audit_log.json | Audit-Log (500 Events) | 925 KB |
| users.json | User-Daten (ohne password_hash) | 1.9 KB |
| README.txt | Erklärung | 471 B |

| | Vorher | Nachher |
|---|---|---|
| HTTP | 500 Internal Server Error | 200 OK |
| Content-Type | n/a | application/zip |
| Größe | n/a | 124 KB |

- **Delete-Endpoint:** GET /gdpr/delete gibt 405 (Method Not Allowed) — erwartet DELETE/POST. Nicht gefixt (war nicht im Scope).

## Fix 3: Anthropic Fallback

- **Implementierung:** Option B (try-except im Communicator)
- **Fallback-Modell:** `openai/Mistral-Small-24B-Instruct-2501` (IONOS DE)
- **Trigger:** `litellm.exceptions.APIError`, `litellm.exceptions.Timeout`, `litellm.exceptions.InternalServerError`
- **Normal-Chat nach Fix:** ✅ "FRYA: Ja, alles klar hier — bei dir auch, Maze?"
- **Fallback getestet:** Nein (Anthropic war zum Testzeitpunkt erreichbar). Code ist syntaktisch korrekt und deployed.

## Geänderte Dateien

| Datei | Fix | Änderung |
|-------|-----|----------|
| `agent/app/accounting/repository.py` | 1 | `compute_booking_hash()` — deterministisches pipe-Format |
| `agent/app/accounting/booking_service.py` | 1 | `verify_hash_chain()` — native Typen statt str() |
| `agent/app/api/gdpr_views.py` | 2 | `case.case_id` → `str(case.id)` |
| `agent/app/telegram/communicator/service.py` | 3 | Fallback auf IONOS Mistral bei Anthropic-Fehler |
