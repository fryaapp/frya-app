#!/usr/bin/env bash
# mount_tenant_volume.sh — Fetch LUKS key from S3 and mount tenant volume
# Called on server startup (e.g., from systemd or cloud-init)
#
# Usage: ./mount_tenant_volume.sh <tenant-id>
#
# Environment: FRYA_S3_KEY_BUCKET, FRYA_S3_ACCESS_KEY, FRYA_S3_SECRET_KEY

set -euo pipefail

TENANT_ID="${1:?Usage: $0 <tenant-id>}"
MAPPER_NAME="frya-${TENANT_ID}"
DATA_DIR="/opt/frya-tenants/${TENANT_ID}/data"
KEY_FILE="/run/luks/frya-${TENANT_ID}.key"  # tmpfs — in-memory only
S3_KEY_BUCKET="${FRYA_S3_KEY_BUCKET:-frya-luks-keys}"
S3_KEY_PATH="${S3_KEY_BUCKET}/${TENANT_ID}/luks.key"

log() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*"; }

# Mount /run/luks as tmpfs if not already mounted
if ! mountpoint -q /run/luks 2>/dev/null; then
    mkdir -p /run/luks
    mount -t tmpfs -o size=1m,mode=700 tmpfs /run/luks
fi

cleanup_key() { shred -uz "${KEY_FILE}" 2>/dev/null || rm -f "${KEY_FILE}"; }
trap cleanup_key EXIT

# ── 1. Check if already mounted ───────────────────────────────────────────────
if mountpoint -q "${DATA_DIR}" 2>/dev/null; then
    log "Already mounted: ${DATA_DIR}"
    exit 0
fi

# ── 2. Fetch key from S3 ──────────────────────────────────────────────────────
log "Fetching LUKS key from s3://${S3_KEY_PATH}..."
if command -v rclone &>/dev/null; then
    rclone copyto "frya-keys:${S3_KEY_PATH}" "${KEY_FILE}" \
        --s3-access-key-id="${FRYA_S3_ACCESS_KEY}" \
        --s3-secret-access-key="${FRYA_S3_SECRET_KEY}"
else
    s3cmd get "s3://${S3_KEY_PATH}" "${KEY_FILE}" \
        --access_key="${FRYA_S3_ACCESS_KEY}" \
        --secret_key="${FRYA_S3_SECRET_KEY}"
fi
chmod 400 "${KEY_FILE}"

# ── 3. Open LUKS volume (if not already open) ────────────────────────────────
if [[ ! -e "/dev/mapper/${MAPPER_NAME}" ]]; then
    VOLUME_DEV=$(blkid -l -t LABEL="frya-${TENANT_ID}" -o device)
    log "Opening ${VOLUME_DEV} as ${MAPPER_NAME}..."
    cryptsetup open --type luks --key-file "${KEY_FILE}" "${VOLUME_DEV}" "${MAPPER_NAME}"
fi

# ── 4. Mount ──────────────────────────────────────────────────────────────────
mkdir -p "${DATA_DIR}"
mount "/dev/mapper/${MAPPER_NAME}" "${DATA_DIR}"
log "Mounted ${DATA_DIR}"
