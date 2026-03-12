# FRYA Agent

FRYA Agent ist das einzige Backend fuer Fallanalyse, Freigabeprozesse, Audit-Logging und orchestrierte Ausfuehrung.

## Architekturleitplanken
- Akaunting = Financial Truth
- Paperless = Document Truth
- PostgreSQL Audit Log = Decision Truth
- Open Items = PostgreSQL (operativ)
- Problem Cases = PostgreSQL (operativ)
- Redis = Queue/Job-Backbone
- n8n = deterministische Workflows und Scheduling
- LiteLLM = einzige LLM-Abstraktion

## Legacy-Hinweis
Ein separater alter Backend-Service kann in Bestandsumgebungen noch existieren, ist aber nicht Teil der Zielarchitektur.

## Kritische Services und Update-Sicherheit
Kritische Services (paperless, akaunting, mariadb, postgres, agent, n8n, traefik) duerfen architektonisch nicht auf blinde Auto-Updates angewiesen sein.

## Start lokal
```bash
python -m venv .venv
. .venv/bin/activate
pip install -e .[dev]
uvicorn app.main:app --reload
```

## Browser-Inspektionsoberflaeche
- /health
- /status
- /inspect/audit
- /inspect/cases
- /inspect/open-items
- /inspect/problem-cases
- /inspect/approvals
- /inspect/proposals
- /inspect/rules
- /inspect/verfahrensdoku

## Operator-UI (Server-Rendered)
- /ui/dashboard
- /ui/cases
- /ui/open-items
- /ui/problem-cases
- /ui/rules
- /ui/rules/audit
- /ui/verfahrensdoku
- /ui/system

Hinweis: intern, session-geschuetzt (operator/admin ACL).

## Rule Loading Voraussetzung
Rule Loading ist nur belastbar, wenn der Runtime-Pfad `FRYA_RULES_DIR` existiert und `rule_registry.yaml` enthaelt.
Bei fehlendem `/app/data/rules` ist der Policy-Status nicht gruen (`Required loaded: False`).

## Telegram V1 (Operator-Kanal)
Telegram ist kein freier Chatbot-Kanal. V1 ist eng und deterministisch.

Unterstuetzte Intents:
- `status.overview`
- `open_items.list`
- `problem_cases.list`
- `case.show`
- `approval.respond`
- `help.basic`

### Telegram ENV
- `FRYA_TELEGRAM_BOT_TOKEN` (Pflicht fuer Replies)
- `FRYA_TELEGRAM_DEFAULT_CHAT_ID` (optional, wird zur Gruppen-Allowlist addiert)
- `FRYA_TELEGRAM_ALLOWED_CHAT_IDS` (kommagetrennte Gruppen-Allowlist)
- `FRYA_TELEGRAM_ALLOWED_DIRECT_CHAT_IDS` (kommagetrennte Direktchat-Allowlist)
- `FRYA_TELEGRAM_ALLOWED_USER_IDS` (optionale kommagetrennte User-Allowlist)
- `FRYA_TELEGRAM_DEDUP_TTL_SECONDS` (optional, default 86400)

### Telegram Betriebsregeln
- Autorisierte Chats: normaler V1-Intent-Pfad mit deterministischen Antworten.
- Nicht autorisierte Chats/User: kurze Deny-Antwort ohne operative Daten.
- Doppelte Updates (gleiche `update_id`) werden per Redis-basierter Dedup-Logik geblockt.
- Bei Duplicate wird keine zweite Fachverarbeitung und keine zweite Reply ausgefuehrt.
- Duplicate-Faelle bleiben nachvollziehbar im Audit (`TELEGRAM_DUPLICATE_IGNORED`).

### Telegram E2E Checkliste
1. `FRYA_TELEGRAM_BOT_TOKEN` gesetzt.
2. HTTPS-Route erreichbar: `POST /webhooks/telegram`.
3. Telegram Webhook zeigt auf `<public-base-url>/webhooks/telegram`.
4. Group- und/oder Direktchat in Allowlist (`FRYA_TELEGRAM_ALLOWED_CHAT_IDS`, `FRYA_TELEGRAM_ALLOWED_DIRECT_CHAT_IDS`).
5. Optional User-Filter setzen (`FRYA_TELEGRAM_ALLOWED_USER_IDS`).
6. Autorisierten Test senden (`hilfe`, `status`, `offene punkte`).
7. Deny-Test aus nicht erlaubtem Chat/User senden.
8. Duplicate-Test: identisches Update nur einmal verarbeiten.
9. Audit pruefen auf:
   - `TELEGRAM_WEBHOOK_RECEIVED`
   - `TELEGRAM_AUTH_DENIED` (bei nicht autorisiertem Test)
   - `TELEGRAM_INTENT_RECOGNIZED`
   - `TELEGRAM_COMMAND_HANDLED`
   - `TELEGRAM_REPLY_ATTEMPTED`
   - `TELEGRAM_DUPLICATE_IGNORED` (bei Duplicate-Test)
10. Case in `/inspect/cases/{case_id}` sichtbar.

## Staging-Dauerloesung fuer `/app/data/rules`
Der Agent laeuft in Staging mit persistentem Volume auf `/app/data`.
Ein frisches oder leeres Volume ueberdeckt den Image-Inhalt und fuehrt ohne Bootstrap zu leerem Rule-Loading.

Dauerloesung im Agent-Container:
- Repo-Defaults werden beim Build nach `/opt/frya-default-data` kopiert.
- Beim Start wird geprueft, ob Pflichtdateien fehlen (`agent.md`, `user.md`, `soul.md`, `memory.md`, `dms-state.md`, `rules/rule_registry.yaml`).
- Falls unvollstaendig: Defaults werden idempotent nach `/app/data` kopiert (`cp -an`).
- Persistente Wahrheit bleibt das Volume auf `/app/data`.

Damit ist Rule-Loading auch bei frischem Volume reproduzierbar, ohne manuelles Kopieren in Docker-Volume-Pfade.

## Staging-Checkliste Rule-Loading
1. `docker exec frya-agent ls -la /app/data/rules`
2. `docker exec frya-agent test -f /app/data/rules/rule_registry.yaml && echo OK`
3. `curl -ks https://agent.staging.myfrya.de/inspect/rules/load-status/json`
4. `curl -ks https://agent.staging.myfrya.de/ui/system`
5. Erwartung:
   - `loaded` gefuellt
   - `failed=[]`
   - `Required loaded: True`
   - `Missing roles: []`

## Freigabematrix / Approval-Haertung
Operative Modi pro Aktion:
- `AUTO`
- `PROPOSE_ONLY`
- `REQUIRE_USER_APPROVAL`
- `BLOCK_ESCALATE`

Der Gate-Entscheid wird im Orchestrierungs-Pfad ermittelt und als Audit-Event `APPROVAL_GATE_DECISION` geschrieben.
Kritische Aktionen (z. B. `payment_execute`) sind blockiert. Aktionen mit Freigabepflicht erzeugen einen Approval-Record und verknuepfen Open Items.

Approval-Status unterstuetzt:
- `PENDING`
- `APPROVED`
- `REJECTED`
- `CANCELLED`
- `EXPIRED`
- `REVOKED`
