# FRYA Backup Report — 07.04.2026

## Git
- Commit: 53a1e91 (P-49c: Freigeben-Haenger gefixt)
- Tag: v5-pre-refactor
- Branch: master
- Remote: https://github.com/fryaapp/frya-app.git (pushed inkl. Tag)

## Datenbank
- Dump (custom): frya-backup-20260407.dump (760 KB)
- Dump (SQL): frya-backup-20260407.sql (2.7 MB)
- Tabellen: 36
- Buchungen: 34
- Kontakte: 64
- Rechnungen: 74
- Konten: 324
- Offene Posten: 138
- Cases: 36
- Approvals: 43
- Users: 11
- Feedback: 27

## Docker
- Container: 10 laufend
- compose-20260407.yml: gesichert (13 KB)
- containers-20260407.txt: gesichert
- env-20260407.env: gesichert (3.4 KB)
- env-names-backend-20260407.txt: gesichert
- env-names-agent-20260407.txt: gesichert

## Backend
- backend-20260407.tar.gz (790 KB)
- Enthaelt: agent/ komplett (ohne __pycache__, .venv)

## Frontend
- package-20260407.json: gesichert
- package-lock-20260407.json: gesichert
- capacitor-config-20260407.ts: gesichert

## Redis
- Keys: 10 (Chat-History, ConversationMemory, pending_invoice)
- redis-20260407.rdb: gesichert (18 KB)

## Nginx
- nginx-20260407.conf: gesichert (1.8 KB)

## Firebase
- firebase-sa-20260407.json: gesichert (2.4 KB)

## Gesichert auf
- Server: /opt/dms-staging/backups/
- Lokal: C:\Users\lenovo\Documents\Frya App\backups\

## Wiederherstellung
Falls noetig:
1. `git checkout v5-pre-refactor`
2. `docker exec frya-postgres pg_restore -U frya -d frya --clean /tmp/frya-backup-20260407.dump`
3. Backend: `tar xzf backend-20260407.tar.gz` → `docker compose build --no-cache` → `up -d`
4. Frontend: deploy wie gewohnt
5. Redis: `docker cp redis-20260407.rdb frya-redis:/data/dump.rdb` → `docker restart frya-redis`
