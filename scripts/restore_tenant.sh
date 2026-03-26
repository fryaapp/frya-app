#!/usr/bin/env bash
# restore_tenant.sh — Decrypt backup and restore to a temporary DB, then row-count check
#
# Usage: ./restore_tenant.sh <tenant-id> <backup-date>
#   e.g. ./restore_tenant.sh acme-gmbh 2026-03-18
#
# Environment: FRYA_S3_BACKUP_BUCKET, FRYA_S3_ACCESS_KEY, FRYA_S3_SECRET_KEY
#              FRYA_AGE_PRIVATE_KEY_FILE  (path to age private key, Maze only)
#              FRYA_DB_HOST, FRYA_DB_PORT, FRYA_DB_USER, FRYA_DB_PASSWORD
#
# Monthly restore test: run on the 1st of each month for all active tenants.
# Outputs a human-readable report. Non-zero exit = failure.

set -euo pipefail

TENANT_ID="${1:?Usage: $0 <tenant-id> <backup-date>}"
BACKUP_DATE="${2:?Usage: $0 <tenant-id> <backup-date>}"

S3_BUCKET="${FRYA_S3_BACKUP_BUCKET:-frya-tenant-backups}"
AGE_KEY="${FRYA_AGE_PRIVATE_KEY_FILE:?FRYA_AGE_PRIVATE_KEY_FILE not set}"
DB_HOST="${FRYA_DB_HOST:-localhost}"
DB_PORT="${FRYA_DB_PORT:-5432}"
DB_USER="${FRYA_DB_USER:-frya}"
RESTORE_DB="frya_restore_${TENANT_ID}_${BACKUP_DATE//-/}"

ENCRYPTED_FILE="/tmp/frya-restore-${TENANT_ID}-${BACKUP_DATE}.sql.gz.age"
DECRYPTED_FILE="/tmp/frya-restore-${TENANT_ID}-${BACKUP_DATE}.sql.gz"
S3_KEY="${TENANT_ID}/postgres/daily/${BACKUP_DATE}.sql.gz.age"

log() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*"; }
section() { echo ""; echo "═══ $* ═══"; }

cleanup() {
    rm -f "${ENCRYPTED_FILE}" "${DECRYPTED_FILE}" 2>/dev/null || true
    log "Dropping temporary DB ${RESTORE_DB}..."
    PGPASSWORD="${FRYA_DB_PASSWORD:-}" psql \
        -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" -d postgres \
        -c "DROP DATABASE IF EXISTS ${RESTORE_DB};" 2>/dev/null || true
}
trap cleanup EXIT

section "FRYA Backup Restore Test"
log "Tenant:  ${TENANT_ID}"
log "Date:    ${BACKUP_DATE}"
log "S3 key:  s3://${S3_BUCKET}/${S3_KEY}"
log "Test DB: ${RESTORE_DB}"

# ── 1. Download encrypted backup ──────────────────────────────────────────────
section "Step 1: Download"
if command -v rclone &>/dev/null; then
    rclone copyto "frya-backups:${S3_BUCKET}/${S3_KEY}" "${ENCRYPTED_FILE}" \
        --s3-access-key-id="${FRYA_S3_ACCESS_KEY}" \
        --s3-secret-access-key="${FRYA_S3_SECRET_KEY}"
else
    s3cmd get "s3://${S3_BUCKET}/${S3_KEY}" "${ENCRYPTED_FILE}" \
        --access_key="${FRYA_S3_ACCESS_KEY}" \
        --secret_key="${FRYA_S3_SECRET_KEY}"
fi
ENCRYPTED_SIZE=$(stat -c%s "${ENCRYPTED_FILE}" 2>/dev/null || echo 0)
log "Downloaded: ${ENCRYPTED_SIZE} bytes"

# ── 2. Decrypt with age ───────────────────────────────────────────────────────
section "Step 2: Decrypt"
age --decrypt \
    --identity "${AGE_KEY}" \
    --output "${DECRYPTED_FILE}" \
    "${ENCRYPTED_FILE}"
DECRYPTED_SIZE=$(stat -c%s "${DECRYPTED_FILE}" 2>/dev/null || echo 0)
log "Decrypted: ${DECRYPTED_SIZE} bytes"

if [[ "${DECRYPTED_SIZE}" -lt 100 ]]; then
    log "ERROR: Decrypted file suspiciously small"
    exit 1
fi

# ── 3. Create temporary restore database ─────────────────────────────────────
section "Step 3: Create temp DB"
PGPASSWORD="${FRYA_DB_PASSWORD:-}" psql \
    -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" -d postgres \
    -c "CREATE DATABASE ${RESTORE_DB} OWNER ${DB_USER};"
log "Created ${RESTORE_DB}"

# ── 4. Restore ────────────────────────────────────────────────────────────────
section "Step 4: Restore"
PGPASSWORD="${FRYA_DB_PASSWORD:-}" psql \
    -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" -d "${RESTORE_DB}" \
    < <(zcat "${DECRYPTED_FILE}")
log "Restore complete"

# ── 5. Row-count check ────────────────────────────────────────────────────────
section "Step 5: Row counts"
PGPASSWORD="${FRYA_DB_PASSWORD:-}" psql \
    -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" -d "${RESTORE_DB}" \
    -c "
SELECT
    schemaname,
    tablename,
    n_live_tup AS estimated_rows
FROM pg_stat_user_tables
ORDER BY tablename;
" | tee /tmp/frya-restore-rowcount-${TENANT_ID}-${BACKUP_DATE}.txt

TOTAL_ROWS=$(PGPASSWORD="${FRYA_DB_PASSWORD:-}" psql \
    -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" -d "${RESTORE_DB}" \
    -t -c "SELECT COALESCE(SUM(n_live_tup),0) FROM pg_stat_user_tables;" | tr -d ' ')

log "Total estimated rows: ${TOTAL_ROWS}"

if [[ "${TOTAL_ROWS}" -lt 1 ]]; then
    log "WARNING: Restored database appears empty"
    exit 1
fi

section "RESULT"
log "✅ Restore test PASSED"
log "   Tenant:     ${TENANT_ID}"
log "   Date:       ${BACKUP_DATE}"
log "   Total rows: ${TOTAL_ROWS}"
log "   Report:     /tmp/frya-restore-rowcount-${TENANT_ID}-${BACKUP_DATE}.txt"
