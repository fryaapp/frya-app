-- 0019: Two-factor authentication (TOTP)
-- Adds TOTP secret, enabled flag, and backup codes to frya_users.

ALTER TABLE frya_users ADD COLUMN IF NOT EXISTS totp_secret VARCHAR(64);
ALTER TABLE frya_users ADD COLUMN IF NOT EXISTS totp_enabled BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE frya_users ADD COLUMN IF NOT EXISTS totp_backup_codes TEXT;
