#!/usr/bin/env bash
# backup_tenant_documents.sh — Daily encrypted documents backup for a tenant
#
# Usage: ./backup_tenant_documents.sh <tenant-id>
#
# Environment: same as backup_tenant_postgres.sh
# Source dir:  /opt/frya-tenants/<tenant-id>/data/paperless/
# Destination: s3://frya-tenant-backups/<tenant>/docs/daily/YYYY-MM-DD.tar.gz.age

set -euo pipefail

TENANT_ID="${1:?Usage: $0 <tenant-id>}"
DATE=$(date -u +%Y-%m-%d)
MONTH=$(date -u +%Y-%m)
TIMESTAMP=$(date -u +%Y%m%dT%H%M%SZ)

SOURCE_DIR="/opt/frya-tenants/${TENANT_ID}/data/paperless"
S3_BUCKET="${FRYA_S3_BACKUP_BUCKET:-frya-tenant-backups}"
AGE_PUBLIC_KEY="${FRYA_AGE_PUBLIC_KEY:?FRYA_AGE_PUBLIC_KEY not set}"

ARCHIVE_FILE="/tmp/frya-docs-${TENANT_ID}-${TIMESTAMP}.tar.gz"
ENCRYPTED_FILE="${ARCHIVE_FILE}.age"

log() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*"; }

notify_failure() {
    local msg="$1"
    if [[ -n "${FRYA_TELEGRAM_BOT_TOKEN:-}" && -n "${FRYA_TELEGRAM_CHAT_ID:-}" ]]; then
        curl -s -X POST \
            "https://api.telegram.org/bot${FRYA_TELEGRAM_BOT_TOKEN}/sendMessage" \
            -d "chat_id=${FRYA_TELEGRAM_CHAT_ID}" \
            -d "text=❌ Docs-Backup FAILED: tenant=${TENANT_ID}%0A${msg}" \
            >/dev/null || true
    fi
    log "FAILURE: ${msg}"
}

cleanup() { rm -f "${ARCHIVE_FILE}" "${ENCRYPTED_FILE}" 2>/dev/null || true; }
trap cleanup EXIT

# ── 1. Check source directory ────────────────────────────────────────────────
if [[ ! -d "${SOURCE_DIR}" ]]; then
    notify_failure "Source dir missing: ${SOURCE_DIR}"
    exit 1
fi

# ── 2. tar + gzip ────────────────────────────────────────────────────────────
log "Archiving ${SOURCE_DIR}..."
tar -czf "${ARCHIVE_FILE}" -C "$(dirname "${SOURCE_DIR}")" "$(basename "${SOURCE_DIR}")" \
    || { notify_failure "tar failed for ${SOURCE_DIR}"; exit 1; }

ARCHIVE_SIZE=$(stat -c%s "${ARCHIVE_FILE}" 2>/dev/null || echo 0)
log "Archive: ${ARCHIVE_FILE} (${ARCHIVE_SIZE} bytes)"

if [[ "${ARCHIVE_SIZE}" -lt 100 ]]; then
    notify_failure "Archive suspiciously small (${ARCHIVE_SIZE} bytes)"
    exit 1
fi

# ── 3. Encrypt with age ───────────────────────────────────────────────────────
log "Encrypting with age..."
age -r "${AGE_PUBLIC_KEY}" -o "${ENCRYPTED_FILE}" "${ARCHIVE_FILE}" \
    || { notify_failure "age encryption failed"; exit 1; }

# ── 4. Upload to S3 ───────────────────────────────────────────────────────────
DAILY_KEY="${TENANT_ID}/docs/daily/${DATE}.tar.gz.age"
MONTHLY_KEY="${TENANT_ID}/docs/monthly/${MONTH}.tar.gz.age"

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

log "Uploading to s3://${S3_BUCKET}/${DAILY_KEY}..."
s3_upload "${DAILY_KEY}" || { notify_failure "S3 upload failed"; exit 1; }

if [[ "$(date -u +%d)" == "01" ]]; then
    s3_upload "${MONTHLY_KEY}" || log "WARNING: Monthly copy failed (non-fatal)"
fi

# Prune daily > 30 days
if command -v rclone &>/dev/null; then
    rclone delete "frya-backups:${S3_BUCKET}/${TENANT_ID}/docs/daily/" \
        --min-age 30d \
        --s3-access-key-id="${FRYA_S3_ACCESS_KEY}" \
        --s3-secret-access-key="${FRYA_S3_SECRET_KEY}" \
        2>/dev/null || true
fi

log "Docs backup completed: s3://${S3_BUCKET}/${DAILY_KEY}"
