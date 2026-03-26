#!/usr/bin/env bash
# backup_tenant_postgres.sh — Daily encrypted PostgreSQL backup for a tenant
#
# Usage: ./backup_tenant_postgres.sh <tenant-id>
#
# Environment variables:
#   FRYA_DB_HOST, FRYA_DB_PORT, FRYA_DB_USER, FRYA_DB_PASSWORD
#   FRYA_S3_BACKUP_BUCKET  (e.g. frya-tenant-backups)
#   FRYA_S3_ACCESS_KEY, FRYA_S3_SECRET_KEY
#   FRYA_AGE_PUBLIC_KEY    (age public key for encryption)
#   FRYA_TELEGRAM_BOT_TOKEN, FRYA_TELEGRAM_CHAT_ID  (for failure alerts)
#
# Retention: 30 daily + 12 monthly (managed via S3 lifecycle policy)
# Encryption: age (https://age-encryption.org), public key in repo at keys/backup-public.age

set -euo pipefail

TENANT_ID="${1:?Usage: $0 <tenant-id>}"
DATE=$(date -u +%Y-%m-%d)
MONTH=$(date -u +%Y-%m)
YEAR=$(date -u +%Y)
TIMESTAMP=$(date -u +%Y%m%dT%H%M%SZ)

DB_HOST="${FRYA_DB_HOST:-localhost}"
DB_PORT="${FRYA_DB_PORT:-5432}"
DB_USER="${FRYA_DB_USER:-frya}"
DB_NAME="${FRYA_DB_NAME:-frya_${TENANT_ID}}"
S3_BUCKET="${FRYA_S3_BACKUP_BUCKET:-frya-tenant-backups}"
AGE_PUBLIC_KEY="${FRYA_AGE_PUBLIC_KEY:?FRYA_AGE_PUBLIC_KEY not set}"

BACKUP_FILE="/tmp/frya-backup-${TENANT_ID}-${TIMESTAMP}.sql.gz"
ENCRYPTED_FILE="${BACKUP_FILE}.age"

log() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*"; }

notify_failure() {
    local msg="$1"
    if [[ -n "${FRYA_TELEGRAM_BOT_TOKEN:-}" && -n "${FRYA_TELEGRAM_CHAT_ID:-}" ]]; then
        curl -s -X POST \
            "https://api.telegram.org/bot${FRYA_TELEGRAM_BOT_TOKEN}/sendMessage" \
            -d "chat_id=${FRYA_TELEGRAM_CHAT_ID}" \
            -d "text=❌ Backup FAILED: tenant=${TENANT_ID}%0A${msg}" \
            >/dev/null || true
    fi
    log "FAILURE: ${msg}"
}

cleanup() {
    rm -f "${BACKUP_FILE}" "${ENCRYPTED_FILE}" 2>/dev/null || true
}
trap cleanup EXIT

# ── 1. pg_dump → gzip ────────────────────────────────────────────────────────
log "Starting pg_dump for ${DB_NAME}..."
PGPASSWORD="${FRYA_DB_PASSWORD:-}" pg_dump \
    -h "${DB_HOST}" \
    -p "${DB_PORT}" \
    -U "${DB_USER}" \
    -d "${DB_NAME}" \
    --no-password \
    --format=plain \
    --compress=9 \
    --file="${BACKUP_FILE}" \
    || { notify_failure "pg_dump failed for ${DB_NAME}"; exit 1; }

BACKUP_SIZE=$(stat -c%s "${BACKUP_FILE}" 2>/dev/null || echo 0)
log "Dump complete: ${BACKUP_FILE} (${BACKUP_SIZE} bytes)"

if [[ "${BACKUP_SIZE}" -lt 100 ]]; then
    notify_failure "Backup suspiciously small (${BACKUP_SIZE} bytes) — aborting"
    exit 1
fi

# ── 2. Encrypt with age ───────────────────────────────────────────────────────
log "Encrypting with age..."
age -r "${AGE_PUBLIC_KEY}" -o "${ENCRYPTED_FILE}" "${BACKUP_FILE}" \
    || { notify_failure "age encryption failed"; exit 1; }

# ── 3. Upload to S3 ───────────────────────────────────────────────────────────
# Daily path:   s3://frya-tenant-backups/<tenant>/postgres/daily/YYYY-MM-DD.sql.gz.age
# Monthly copy: s3://frya-tenant-backups/<tenant>/postgres/monthly/YYYY-MM.sql.gz.age
DAILY_KEY="${TENANT_ID}/postgres/daily/${DATE}.sql.gz.age"
MONTHLY_KEY="${TENANT_ID}/postgres/monthly/${MONTH}.sql.gz.age"

log "Uploading to s3://${S3_BUCKET}/${DAILY_KEY}..."
s3_upload() {
    if command -v rclone &>/dev/null; then
        rclone copyto "${ENCRYPTED_FILE}" "frya-backups:${S3_BUCKET}/$1" \
            --s3-access-key-id="${FRYA_S3_ACCESS_KEY}" \
            --s3-secret-access-key="${FRYA_S3_SECRET_KEY}"
    else
        s3cmd put "${ENCRYPTED_FILE}" "s3://${S3_BUCKET}/$1" \
            --access_key="${FRYA_S3_ACCESS_KEY}" \
            --secret_key="${FRYA_S3_SECRET_KEY}" \
            --server-side-encryption
    fi
}

s3_upload "${DAILY_KEY}" || { notify_failure "S3 upload failed (daily)"; exit 1; }
log "Daily backup uploaded."

# Monthly copy (first day of month or if monthly doesn't exist)
if [[ "$(date -u +%d)" == "01" ]]; then
    s3_upload "${MONTHLY_KEY}" || log "WARNING: Monthly copy failed (non-fatal)"
    log "Monthly backup copied."
fi

# ── 4. Retention: delete daily backups older than 30 days ────────────────────
CUTOFF=$(date -u -d "30 days ago" +%Y-%m-%d 2>/dev/null || date -u -v-30d +%Y-%m-%d)
log "Pruning daily backups before ${CUTOFF}..."
# List and delete old daily backups (best-effort, non-fatal)
if command -v rclone &>/dev/null; then
    rclone delete "frya-backups:${S3_BUCKET}/${TENANT_ID}/postgres/daily/" \
        --min-age 30d \
        --s3-access-key-id="${FRYA_S3_ACCESS_KEY}" \
        --s3-secret-access-key="${FRYA_S3_SECRET_KEY}" \
        2>/dev/null || true
fi

log "Backup completed successfully: s3://${S3_BUCKET}/${DAILY_KEY}"
