# FRYA Ops-Checklisten

Stand: 2026-03-18

---

## Checkliste 0: Brevo als Mail-Provider (Paket 58 / Paket 22)

### 0.1 Brevo-Credentials

| Variable | Wert |
|----------|------|
| `FRYA_MAIL_PROVIDER` | `brevo` |
| `FRYA_BREVO_API_KEY` | aus Brevo-Dashboard → SMTP & API → API Keys |
| `FRYA_MAILGUN_FROM` | `noreply@myfrya.de` (Absenderadresse) |

**In `/opt/dms-staging/.env` ergaenzen**:
```
FRYA_MAIL_PROVIDER=brevo
FRYA_BREVO_API_KEY=HIER_BREVO_API_KEY
FRYA_MAILGUN_FROM=noreply@myfrya.de
```

### 0.2 Technisches Design

- Brevo API v3 Endpoint: `POST https://api.brevo.com/v3/smtp/email`
- Header: `api-key: {FRYA_BREVO_API_KEY}`
- Kein Brevo-SDK — nur HTTP via aiohttp
- Mailgun-Code bleibt als Fallback (Provider-Switch via `FRYA_MAIL_PROVIDER`)
- Tenant-spezifische Mail-Configs (SMTP/Mailgun per Tenant) funktionieren weiterhin
- Inbound-Webhook `/webhooks/mailgun` bleibt erhalten (Brevo Inbound requires Business plan — MVP uses Telegram for document ingestion)

### 0.3 Verifikationsschritte

- [ ] `FRYA_MAIL_PROVIDER=brevo` in `.env` gesetzt
- [ ] `FRYA_BREVO_API_KEY` in `.env` gesetzt
- [ ] Container neu gestartet
- [ ] Test: Passwort-Reset-Mail angefordert → Brevo-Dashboard zeigt gesendete Mail
- [ ] HTTP 201/202 in Logs bei Mail-Versand

---

## Checkliste 1: Mailgun (Legacy-Fallback, Paket 58)

### 1.1 Benoetigte ENV-Variablen

Alle Variablen mit `FRYA_`-Prefix (pydantic_settings liest sie aus `.env`):

| Variable | Pflicht | Beschreibung | Beispielwert |
|----------|---------|-------------|--------------|
| `FRYA_MAILGUN_WEBHOOK_SIGNING_KEY` | Ja (Inbound) | HMAC-Signing-Key fuer eingehende Mailgun-Webhooks. Mailgun-Dashboard → Sending → Domain Settings → HTTP Webhook Signing Key | `key-abc123...` |
| `FRYA_MAILGUN_API_KEY` | Ja (Outbound) | Mailgun API-Key fuer ausgehenden E-Mail-Versand (Passwort-Reset, Einladung) | `key-abc123...` |
| `FRYA_MAILGUN_DOMAIN` | Ja (Outbound) | Mailgun-Domain fuer ausgehenden Versand | `mg.myfrya.de` |
| `FRYA_MAILGUN_FROM` | Nein | Absenderadresse fuer System-Mails | `noreply@myfrya.de` |
| `FRYA_APP_BASE_URL` | Nein | Basis-URL fuer Passwort-Reset-Links | `https://app.myfrya.de` |

**In `/opt/dms-staging/.env` ergaenzen** (Platzhalter ersetzen):
```
FRYA_MAILGUN_WEBHOOK_SIGNING_KEY=HIER_WEBHOOK_SIGNING_KEY_EINTRAGEN
FRYA_MAILGUN_API_KEY=HIER_API_KEY_EINTRAGEN
FRYA_MAILGUN_DOMAIN=mg.myfrya.de
FRYA_MAILGUN_FROM=noreply@myfrya.de
FRYA_APP_BASE_URL=https://api.staging.myfrya.de
```

### 1.2 Wo in Mailgun konfigurieren

1. **Inbound-Routing (E-Mail-Ingestion)**:
   - Mailgun-Dashboard → Receiving → Create Route
   - Expression: `match_recipient(".*@mg.myfrya.de")` (oder spezifische Adresse)
   - Action: `forward("https://api.staging.myfrya.de/webhooks/mailgun")`
   - Prioritaet: 10

2. **Webhook Signing Key**:
   - Mailgun → Sending → Domain Settings → HTTP Webhook Signing Key
   - Diesen Key in `FRYA_MAILGUN_WEBHOOK_SIGNING_KEY` eintragen

3. **DNS** (fuer Outbound):
   - SPF, DKIM, MX-Eintraege gemaess Mailgun-Anleitung fuer `mg.myfrya.de`

### 1.3 Webhook-Endpoint

**URL**: `https://api.staging.myfrya.de/webhooks/mailgun`
**Methode**: POST
**Auth**: Keine (Mailgun-HMAC-Signatur wird intern validiert)

**Status-Check**:
```bash
curl -X POST https://api.staging.myfrya.de/webhooks/mailgun \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "timestamp=1234&token=abc&signature=xyz"
# Erwartet: 400 (Pflichtfelder vorhanden, Signatur falsch — kein 404)
# Aktuell: 400 ✅ (Endpoint erreichbar)
```

### 1.4 Verifikationsschritte

- [ ] `FRYA_MAILGUN_WEBHOOK_SIGNING_KEY` in `/opt/dms-staging/.env` gesetzt
- [ ] `FRYA_MAILGUN_API_KEY` in `/opt/dms-staging/.env` gesetzt
- [ ] `FRYA_MAILGUN_DOMAIN` in `/opt/dms-staging/.env` gesetzt
- [ ] Mailgun-Route auf `https://api.staging.myfrya.de/webhooks/mailgun` konfiguriert
- [ ] Test-Mail an konfigurierte Adresse gesendet
- [ ] Mailgun-Log zeigt erfolgreiche Webhook-Lieferung (200)
- [ ] Frya `/ui/email-intake` zeigt eingegangene Mail
- [ ] Passwort-Reset-Mail kommt an (E-Mail-Adresse bekannt)

---

## Checkliste 2: Backup-System aktivieren (Paket 61)

### 2.1 Voraussetzungen installieren (auf Staging)

```bash
# age installieren
apt-get install -y age
# Oder via GitHub-Release:
# curl -L https://github.com/FiloSottile/age/releases/latest/download/age-v1.x.x-linux-amd64.tar.gz | tar xz
# mv age/age age/age-keygen /usr/local/bin/

# rclone installieren (fuer S3-Upload)
curl https://rclone.org/install.sh | bash
```

**Aktueller Staging-Status**:
- `age`: ❌ nicht installiert
- `rclone`: ❌ nicht installiert
- Fallback: `s3cmd` koennte als Alternative verwendet werden

### 2.2 age-Schluesselpaar erzeugen

**Einmalig auf Mazes lokalem Rechner** (privater Key verlaesst nie den Rechner):
```bash
# Schluesselpaar generieren
age-keygen -o ~/.config/frya/backup.age

# Public Key exportieren und ins Repo committen
age-keygen -y ~/.config/frya/backup.age > keys/backup-public.age
```

**WICHTIG**: `keys/backup-public.age` ist aktuell ein Platzhalter (`age1xxx...`).
Vor dem ersten Backup-Lauf muss der echte Public Key eingetragen werden.

### 2.3 Benoetigte ENV-Variablen (Backup-Skripte)

Diese Variablen werden direkt in den Shell-Skripten gelesen (kein `FRYA_`-Prefix-Mapping noetig — Shell-Skripte, nicht der Python-App):

| Variable | Pflicht | Beschreibung |
|----------|---------|-------------|
| `FRYA_AGE_PUBLIC_KEY` | Ja | age public key (aus `keys/backup-public.age`) |
| `FRYA_AGE_PRIVATE_KEY_FILE` | Ja (restore) | Pfad zur age private key-Datei (Maze only) |
| `FRYA_S3_BACKUP_BUCKET` | Ja | S3-Bucket-Name, z.B. `frya-tenant-backups` |
| `FRYA_S3_ACCESS_KEY` | Ja | Hetzner Object Storage Access Key |
| `FRYA_S3_SECRET_KEY` | Ja | Hetzner Object Storage Secret Key |
| `FRYA_DB_HOST` | Nein | PostgreSQL-Host (default: `localhost`) |
| `FRYA_DB_PORT` | Nein | PostgreSQL-Port (default: `5432`) |
| `FRYA_DB_USER` | Nein | PostgreSQL-User (default: `frya`) |
| `FRYA_DB_PASSWORD` | Ja | PostgreSQL-Passwort |
| `FRYA_DB_NAME` | Nein | DB-Name (default: `frya_<tenant-id>`) |
| `FRYA_TELEGRAM_BOT_TOKEN` | Nein | Telegram-Bot fuer Failure-Alerts |
| `FRYA_TELEGRAM_CHAT_ID` | Nein | Telegram-Chat-ID fuer Alerts |

**In `/opt/dms-staging/.env` ergaenzen**:
```
FRYA_AGE_PUBLIC_KEY=age1HIER_ECHTEN_PUBLIC_KEY_EINTRAGEN
FRYA_S3_BACKUP_BUCKET=frya-backups-staging
FRYA_S3_ACCESS_KEY=F66Z0CSG2EPR3LD3D5UG
FRYA_S3_SECRET_KEY=HIER_HETZNER_SECRET_KEY
FRYA_DB_HOST=frya-postgres
FRYA_DB_PORT=5432
FRYA_DB_USER=frya
FRYA_DB_PASSWORD=HIER_DB_PASSWORT_AUS_ENV
```

### 2.4 Hetzner Object Storage

1. Hetzner Cloud Console → Object Storage → Bucket: **`frya-backups-staging`** (Falkenstein, angelegt ✅)
2. Credentials (S3-kompatibel): Access Key + Secret Key (generiert ✅)
3. Endpoint: `https://fsn1.your-objectstorage.com` (Hetzner Falkenstein)
4. S3-kompatible Konfiguration fuer rclone:
   ```
   # ~/.config/rclone/rclone.conf
   [frya-backups]
   type = s3
   provider = Other
   env_auth = false
   access_key_id = F66Z0CSG2EPR3LD3D5UG
   secret_access_key = HIER_SECRET_KEY_AUS_ENV
   endpoint = https://fsn1.your-objectstorage.com
   ```
   **Hinweis**: Alte Keys (O2WBOZSKJUBWIJBR037Y) sind kompromittiert und ersetzt.

### 2.5 Backup-Skripte

| Skript | Zweck | Aufruf |
|--------|-------|--------|
| `scripts/backup_tenant_postgres.sh` | PostgreSQL-Dump → age-verschluesselt → S3 | `./backup_tenant_postgres.sh <tenant-id>` |
| `scripts/backup_tenant_documents.sh` | Paperless-Dokumente → tar.gz → age → S3 | `./backup_tenant_documents.sh <tenant-id>` |
| `scripts/restore_tenant.sh` | Entschluesselung + Restore in Test-DB + Row-Check | `./restore_tenant.sh <tenant-id> <datum>` |
| `scripts/provision_tenant_volume.sh` | LUKS-Volume pro Tenant anlegen | `./provision_tenant_volume.sh <tenant-id>` |
| `scripts/mount_tenant_volume.sh` | LUKS-Volume mounten (via S3-Key) | `./mount_tenant_volume.sh <tenant-id>` |

**Alle Skripte haben LF-Line-Endings** (nach CRLF-Fix in diesem Commit).

### 2.6 Dry-Run (wenn Voraussetzungen erfuellt)

```bash
# Auf Staging, wenn age + rclone + Credentials gesetzt:
export FRYA_DB_HOST=frya-postgres
export FRYA_DB_PORT=5432
export FRYA_DB_USER=frya
export FRYA_DB_PASSWORD=$(grep STAGING_POSTGRES_PASSWORD /opt/dms-staging/.env | cut -d= -f2)
export FRYA_AGE_PUBLIC_KEY=$(grep -v '^#' keys/backup-public.age | head -1)
export FRYA_S3_BACKUP_BUCKET=frya-tenant-backups
export FRYA_S3_ACCESS_KEY=...
export FRYA_S3_SECRET_KEY=...

# Test-Lauf fuer 'staging'-Tenant
bash scripts/backup_tenant_postgres.sh staging
```

### 2.7 Verifikationsschritte

- [ ] `age` auf Staging installiert (`apt-get install age`)
- [ ] `rclone` auf Staging installiert
- [ ] age-Schluesselpaar erzeugt, Public Key in `keys/backup-public.age` eingetragen
- [ ] Hetzner Object Storage Bucket `frya-tenant-backups` angelegt
- [ ] S3-Credentials in `/opt/dms-staging/.env` gesetzt
- [ ] `FRYA_AGE_PUBLIC_KEY` in `.env` gesetzt (Public Key)
- [ ] rclone-Config auf Staging angelegt (`~/.config/rclone/rclone.conf`)
- [ ] Erster Backup-Lauf erfolgreich: `bash backup_tenant_postgres.sh frya`
- [ ] Backup in S3-Bucket sichtbar
- [ ] Restore-Test erfolgreich: `bash restore_tenant.sh frya <datum>`

---

## Checkliste 3: CRLF-Fix (abgeschlossen)

### Status: ✅ Erledigt

**Geaenderte Dateien**:
- `scripts/backup_tenant_documents.sh` — CRLF → LF
- `scripts/backup_tenant_postgres.sh` — CRLF → LF
- `scripts/mount_tenant_volume.sh` — CRLF → LF
- `scripts/provision_tenant_volume.sh` — CRLF → LF
- `scripts/restore_tenant.sh` — CRLF → LF
- `tmp_apply_tg_stage_fix.sh` — CRLF → LF
- `tmp_update_token.sh` — CRLF → LF
- `.gitattributes` — neu erstellt mit `*.sh text eol=lf`

**Verifikation auf Staging** (nach Deploy):
```bash
docker exec frya-agent file /app/scripts/*.sh
# Erwartet: "... ASCII text" (kein "with CRLF line terminators")
```

---

## Referenz: Alle FRYA-ENV-Variablen (Zusammenfassung)

### Python-App (config.py, FRYA_-Prefix)
```
FRYA_DATABASE_URL            Pflicht   PostgreSQL-Verbindung
FRYA_REDIS_URL               Pflicht   Redis-Verbindung
FRYA_AUTH_SESSION_SECRET     Pflicht   Session-Signatur (32+ Zeichen)
FRYA_PAPERLESS_BASE_URL      Pflicht   Paperless-URL intern
FRYA_AKAUNTING_BASE_URL      Pflicht   Akaunting-URL intern
FRYA_N8N_BASE_URL            Pflicht   n8n-URL intern

FRYA_MAILGUN_WEBHOOK_SIGNING_KEY  Mailgun Inbound
FRYA_MAILGUN_API_KEY              Mailgun Outbound
FRYA_MAILGUN_DOMAIN               Mailgun Domain
FRYA_MAILGUN_FROM                 Absenderadresse
FRYA_APP_BASE_URL                 Fuer Passwort-Reset-Links

FRYA_CONFIG_ENCRYPTION_KEY   Fernet-Key fuer API-Key-Verschluesselung

FRYA_MAIL_PROVIDER           'brevo' | 'mailgun' (default: mailgun)
FRYA_BREVO_API_KEY           Brevo API v3 Key (system mails wenn MAIL_PROVIDER=brevo)
```

### Shell-Skripte (kein Prefix-Mapping)
```
FRYA_AGE_PUBLIC_KEY          Pflicht fuer Backup
FRYA_AGE_PRIVATE_KEY_FILE    Pflicht fuer Restore (Maze only)
FRYA_S3_BACKUP_BUCKET        S3-Bucket-Name
FRYA_S3_ACCESS_KEY           Hetzner Object Storage
FRYA_S3_SECRET_KEY           Hetzner Object Storage
FRYA_DB_HOST/PORT/USER/PASSWORD/NAME  PostgreSQL fuer Skripte
```
