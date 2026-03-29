# FRYA System-Diagnostic — 27.03.2026

## 1. Container-Status

| Container | Status | RAM | Funktion |
|-----------|--------|-----|----------|
| dms-staging-backend-1 | Up 6h | 238 MB | FastAPI Backend (Agent) |
| dms-staging-traefik-1 | Up 21h | 34 MB | Reverse Proxy + TLS |
| frya-ui | Up 33min | 5 MB | nginx + SPA |
| frya-postgres | Up 10d (healthy) | 83 MB | PostgreSQL |
| frya-redis | Up 10d (healthy) | 10 MB | Redis (Tokens, Cache) |
| frya-paperless | Up 6d (healthy) | 958 MB | Paperless-ngx (OCR) |
| frya-n8n | Up 8d (healthy) | 325 MB | n8n Workflow-Engine |
| frya-gotenberg | Up 10d | 15 MB | PDF-Konvertierung |
| frya-tika | Up 10d | 290 MB | Apache Tika (Dokument-Parsing) |
| frya-uptime-kuma | Up 2d (healthy) | 124 MB | Uptime-Monitoring |
| frya-watchtower | Up 10d (healthy) | 10 MB | Auto-Update Container |
| frya-keys-ui | Up 10d | 6 MB | API-Keys UI |

**Server:** 7.6 GB RAM, 2.8 GB belegt (37%), 4.8 GB verfügbar
**Disk:** 75 GB, 38 GB belegt (53%), 34 GB frei
**Fehlende Container:** Keine — alle 12 laufen

## 2. API Endpoints

| Endpoint | Method | HTTP | Response | Anmerkung |
|----------|--------|------|----------|-----------|
| /health | GET | 200 | `{"status":"ok","service":"frya-agent"}` | ✅ |
| /auth/login | POST | 200 | JWT Token | ✅ |
| /auth/refresh | POST | 422 | Validation Error | ⚠️ Braucht refresh_token im Body, nicht Bearer |
| /auth/forgot-password | POST | 200 | OK | ✅ |
| /auth/change-password | POST | 422 | Validation Error | ✅ Existiert (422 = fehlende Felder) |
| /auth/activate/:token | GET | 404 | Not Found | ❌ Endpoint fehlt |
| /greeting | GET | 200 | greeting + suggestions + urgent | ✅ |
| /activity-summary | GET | 200 | Counts + summary_text | ✅ |
| /chat | POST | 200 | reply + case_ref + suggestions | ✅ |
| /inbox | GET | 200 | count=38, items[] | ✅ |
| /documents | GET | 200 | count=33, items[] | ✅ |
| /cases | GET | 200 | count=38 | ✅ |
| /deadlines | GET | 200 | overdue/due_today/due_soon/skonto | ✅ |
| /bookings | GET | 200 | count=5, items[] | ✅ |
| /contacts | GET | 200 | count=17 | ✅ |
| /open-items | GET | 200 | count + items[] | ✅ |
| /reports/euer | GET | 200 | income/expenses/profit | ✅ Profit: -116.99€ |
| /reports/ust | GET | 200 | Q1: Zahllast 302.90€ | ✅ |
| /admin/verify-hash-chain | GET | 200 | valid=**false**, 10 errors | 🔴 KRITISCH |
| /settings | GET | 404 | Not Found | ❌ Endpoint fehlt |
| /finance/summary | GET | 200 | income/expenses/open items | ✅ |
| /feedback | POST | — | Nicht getestet (würde Daten erzeugen) | ⏭️ |
| /gdpr/export | GET | 500 | Internal Server Error | 🔴 FEHLER |
| /gdpr/delete | GET | 405 | Method Not Allowed | ⚠️ Braucht POST/DELETE |

## 3. WebSocket

| Test | Ergebnis |
|------|----------|
| Verbindung | ✅ Erfolgreich |
| Ping/Pong | ✅ `{"type":"pong"}` |
| Typing-Event | ✅ `type=typing` |
| Streaming | ⚠️ Kein Streaming — direkt message_complete |
| message_complete | ✅ Vollständige Antwort |
| context_type | ✅ Vorhanden (`none`) |
| suggestions | ✅ 3 Vorschläge geliefert |

**WS-URL:** `wss://api.staging.myfrya.de/api/v1/chat/stream?token=...`
**Anmerkung:** Chat antwortet direkt ohne Streaming-Chunks. Kein `chunk`-Event beobachtet.

## 4. Datenbank

**DB-Name:** `frya` (nicht `frya_db`!)
**Weitere DBs:** `akaunting` (legacy), `n8n`, `paperless`, `postgres`

| Tabelle | Rows |
|---------|------|
| frya_bookings | 18 |
| frya_contacts | 18 |
| frya_accounts | 36 |
| frya_open_items | 449 |
| frya_invoices | 0 |
| frya_invoice_items | 0 |
| frya_cost_centers | 0 |
| frya_projects | 0 |

**Hash-Chain:** 🔴 **UNGÜLTIG** — Alle 18 Buchungen haben Hash-Mismatch
**Offene Posten:** 449 Einträge in frya_open_items
**Akaunting-Tabellen:** Nicht geprüft (legacy DB `akaunting` existiert noch separat)
**Migrationen:** Kein Alembic-Version-Table gefunden

## 5. Frontend-Build

| Metrik | Wert |
|--------|------|
| Bundle-Größe | 26 MB (inkl. Logos 4.9+4.3 MB) |
| JS-Bundle | ~409 KB (gzip: 123 KB) |
| Fonts self-hosted | ✅ 6 .woff2 Dateien (Outfit, Plus Jakarta Sans, Material Symbols) |
| CDN-Calls | ✅ Keine externen Font-Calls |
| nginx SPA | ✅ try_files → index.html |
| API-Proxy | ✅ /api/ → backend:8001 |
| WebSocket-Proxy | ✅ /api/v1/chat/stream → backend:8001 (600s timeout) |
| Cache-Header | ✅ 30d immutable für statische Assets |
| Security | ✅ `deny all` für dotfiles |

**Achtung:** Alte JS-Bundles werden NICHT aufgeräumt — 5+ alte index-*.js Dateien im assets/ Ordner. Nur der neueste wird von index.html referenziert, aber Disk-Platz wird verschwendet.

## 6. Domain-Routing

| Domain | Routing | TLS |
|--------|---------|-----|
| app.staging.myfrya.de | ✅ → frya-ui | ✅ Let's Encrypt |
| www.myfrya.de | ✅ → frya-ui | ✅ Let's Encrypt |
| api.staging.myfrya.de | ✅ → backend | ✅ Let's Encrypt |
| myfrya.de (ohne www) | ❌ Anderer Server (88.198.219.246) | — |

## 7. Git

**Backend:** Kein Git-Repository auf dem Server. Deployment via SCP von lokalem Windows-Rechner.
**Frontend:** Kein Git-Repository auf dem Server. Build lokal, SCP dist/.
**Backups:** 14 agent.backup.* Verzeichnisse in /opt/dms-staging/

## 8. Fehler & Probleme

| # | Problem | Schwere | Details |
|---|---------|---------|---------|
| 1 | **Hash-Chain ungültig** | 🔴 KRITISCH | Alle 18 Buchungen haben Hash-Mismatch. GoBD-Konformität nicht gegeben. |
| 2 | **GDPR Export 500** | 🔴 KRITISCH | GET /gdpr/export gibt Internal Server Error. DSGVO-Export funktioniert nicht. |
| 3 | **Anthropic API Overloaded** | 🟠 MITTEL | Mehrere `overloaded_error` in den Logs. Chat fällt auf Fallback zurück ("nicht erreichbar"). |
| 4 | **Invite-Mail Redis-Bug** | 🟠 MITTEL | `PasswordResetService` wurde mit falscher URL initialisiert (database_url statt redis_url). **Fix deployed aber Backend-Container noch mit altem Code.** |
| 5 | **Settings-Endpoint 404** | 🟡 NIEDRIG | GET /api/v1/settings existiert nicht. Frontend nutzt eigenen Pfad. |
| 6 | **Auth Activate fehlt** | 🟡 NIEDRIG | GET /auth/activate/:token gibt 404. Invite-Flow nutzt Reset-Password statt Activate. |
| 7 | **Kein Streaming im WS** | 🟡 NIEDRIG | Chat liefert Antwort als ganzes `message_complete` statt Token-für-Token Streaming. |
| 8 | **Logo-Dateien zu groß** | 🟡 NIEDRIG | frya-avatar.png 4.9 MB, frya-banner.png 4.3 MB. Sollten komprimiert werden (<200 KB). |
| 9 | **Alte JS-Bundles** | 🟡 NIEDRIG | 5+ veraltete index-*.js Dateien in assets/. Aufräumen empfohlen. |
| 10 | **Kein Git auf Server** | 🟡 NIEDRIG | Keine Versionskontrolle auf dem Server. Deployment nur via SCP. |

## 9. Fehlende Endpoints

| Endpoint | Status |
|----------|--------|
| POST /auth/change-password | ✅ Existiert (422 = braucht Felder) |
| GET /gdpr/export | ❌ 500 Internal Server Error |
| DELETE /gdpr/delete | ⚠️ 405 Method Not Allowed (GET statt DELETE?) |
| POST /auth/forgot-password | ✅ Existiert (200) |
| GET /auth/activate/:token | ❌ 404 Not Found |
| GET /settings | ❌ 404 Not Found |

## 10. Empfohlene Nächste Schritte (Priorität)

1. 🔴 **Hash-Chain reparieren** — Buchungen neu hashen oder HMAC-Key prüfen
2. 🔴 **GDPR Export fixen** — 500er Error debuggen (wahrscheinlich fehlende DB-Spalte oder Serialisierung)
3. 🟠 **Backend neu deployen** — Container hat noch alten Code (invite-mail fix, etc.)
4. 🟠 **Logos komprimieren** — 4.9 MB Avatar auf ~150 KB, 4.3 MB Banner auf ~100 KB
5. 🟡 **Alte Bundles aufräumen** — assets/ Ordner bereinigen
6. 🟡 **DNS: myfrya.de** → gleichen Server wie www.myfrya.de routen
