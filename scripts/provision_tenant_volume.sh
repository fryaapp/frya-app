#!/usr/bin/env bash
# provision_tenant_volume.sh — Provision a LUKS-encrypted Hetzner Volume per tenant
#
# Usage: ./provision_tenant_volume.sh <tenant-id> <hetzner-volume-device>
#   e.g. ./provision_tenant_volume.sh acme-gmbh /dev/disk/by-id/scsi-0HC_Volume_12345678
#
# Prerequisites:
#   - cryptsetup installed
#   - s3cmd or rclone configured for FRYA_S3_KEY_BUCKET
#   - Environment: FRYA_S3_KEY_BUCKET, FRYA_S3_KEY_PREFIX, FRYA_S3_ACCESS_KEY, FRYA_S3_SECRET_KEY
#
# Key storage: LUKS key is stored in a SEPARATE Hetzner Object Storage bucket
# dedicated to key material (frya-luks-keys), never on the same server as data.
#
# NICHT TUN: Key-Management-System — simple S3 key storage ist der MVP-Ansatz.

set -euo pipefail

TENANT_ID="${1:?Usage: $0 <tenant-id> <volume-device>}"
VOLUME_DEV="${2:?Usage: $0 <tenant-id> <volume-device>}"

MOUNT_BASE="/opt/frya-tenants"
TENANT_DIR="${MOUNT_BASE}/${TENANT_ID}"
DATA_DIR="${TENANT_DIR}/data"
MAPPER_NAME="frya-${TENANT_ID}"
KEY_FILE="/tmp/frya-luks-${TENANT_ID}.key"

S3_KEY_BUCKET="${FRYA_S3_KEY_BUCKET:-frya-luks-keys}"
S3_KEY_PATH="${S3_KEY_BUCKET}/${TENANT_ID}/luks.key"

log() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*"; }

cleanup_key() {
    if [[ -f "${KEY_FILE}" ]]; then
        shred -uz "${KEY_FILE}" 2>/dev/null || rm -f "${KEY_FILE}"
    fi
}
trap cleanup_key EXIT

# ── 1. Validate device ────────────────────────────────────────────────────────
if [[ ! -b "${VOLUME_DEV}" ]]; then
    echo "ERROR: ${VOLUME_DEV} is not a block device" >&2
    exit 1
fi

# ── 2. Generate LUKS key (512-bit random) ────────────────────────────────────
log "Generating LUKS key for tenant ${TENANT_ID}..."
dd if=/dev/urandom bs=64 count=1 status=none > "${KEY_FILE}"
chmod 400 "${KEY_FILE}"

# ── 3. Upload key to S3 key bucket BEFORE formatting (fail-safe) ─────────────
log "Uploading LUKS key to s3://${S3_KEY_PATH}..."
if command -v rclone &>/dev/null; then
    rclone copyto "${KEY_FILE}" "frya-keys:${S3_KEY_PATH}" \
        --s3-access-key-id="${FRYA_S3_ACCESS_KEY}" \
        --s3-secret-access-key="${FRYA_S3_SECRET_KEY}"
elif command -v s3cmd &>/dev/null; then
    s3cmd put "${KEY_FILE}" "s3://${S3_KEY_PATH}" \
        --access_key="${FRYA_S3_ACCESS_KEY}" \
        --secret_key="${FRYA_S3_SECRET_KEY}" \
        --server-side-encryption
else
    echo "ERROR: Neither rclone nor s3cmd found. Install one before running this script." >&2
    exit 1
fi
log "Key uploaded to s3://${S3_KEY_PATH}"

# ── 4. Format volume with LUKS2 ──────────────────────────────────────────────
log "Formatting ${VOLUME_DEV} with LUKS2..."
cryptsetup luksFormat \
    --type luks2 \
    --cipher aes-xts-plain64 \
    --key-size 512 \
    --hash sha256 \
    --iter-time 2000 \
    --batch-mode \
    --key-file "${KEY_FILE}" \
    "${VOLUME_DEV}"

# ── 5. Open LUKS volume ───────────────────────────────────────────────────────
log "Opening LUKS volume as /dev/mapper/${MAPPER_NAME}..."
cryptsetup open --type luks --key-file "${KEY_FILE}" "${VOLUME_DEV}" "${MAPPER_NAME}"

# ── 6. Create ext4 filesystem ─────────────────────────────────────────────────
log "Creating ext4 filesystem..."
mkfs.ext4 -L "frya-${TENANT_ID}" "/dev/mapper/${MAPPER_NAME}"

# ── 7. Create mount point and mount ───────────────────────────────────────────
log "Mounting at ${DATA_DIR}..."
mkdir -p "${DATA_DIR}"
mount "/dev/mapper/${MAPPER_NAME}" "${DATA_DIR}"
chmod 700 "${DATA_DIR}"

# ── 8. Write /etc/crypttab entry (for auto-mount on reboot) ──────────────────
# Note: key must be fetched from S3 by mount script — see mount_tenant_volume.sh
LUKS_UUID=$(cryptsetup luksUUID "${VOLUME_DEV}")
log "LUKS UUID: ${LUKS_UUID}"
echo "# FRYA tenant ${TENANT_ID} — key in s3://${S3_KEY_PATH}" >> /etc/crypttab
echo "${MAPPER_NAME} UUID=${LUKS_UUID} /etc/luks-keys/frya-${TENANT_ID}.key luks,noauto" >> /etc/crypttab

# ── 9. Write /etc/fstab entry ─────────────────────────────────────────────────
echo "/dev/mapper/${MAPPER_NAME} ${DATA_DIR} ext4 defaults,noauto 0 2" >> /etc/fstab

log "Provisioning complete for tenant ${TENANT_ID}"
log "  Volume:  ${VOLUME_DEV}"
log "  Mapper:  /dev/mapper/${MAPPER_NAME}"
log "  Mount:   ${DATA_DIR}"
log "  LUKS UUID: ${LUKS_UUID}"
log "  Key at:  s3://${S3_KEY_PATH}"
log ""
log "IMPORTANT: Key is stored in s3://${S3_KEY_PATH}"
log "           NOT on this server. Retrieve before next mount."
