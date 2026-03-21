#!/usr/bin/env bash
# seed_admin.sh — create or reset the admin user directly in the DB.
# Usage: ./scripts/seed_admin.sh <username> <password> [email]
# Run on the staging server (where postgres is reachable via Docker network).
# Example: ./scripts/seed_admin.sh admin "SuperSecret123!" admin@myfrya.de

set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "Usage: $0 <username> <password> [email]"
  exit 1
fi

USERNAME="$1"
PASSWORD="$2"
EMAIL="${3:-}"

# Derive the DB URL from .env
if [[ -f .env ]]; then
  source <(grep -E '^(STAGING_POSTGRES_PASSWORD|FRYA_DATABASE_URL)=' .env | sed 's/^/export /')
fi

DB_CONTAINER="${DB_CONTAINER:-frya-postgres}"
DB_USER="${DB_USER:-frya}"
DB_NAME="${DB_NAME:-frya}"

# Hash the password using Python (same algorithm as the app: pbkdf2_sha256)
PW_HASH=$(docker exec "$DB_CONTAINER" python3 -c "
import hashlib, secrets, base64
password = '''$PASSWORD'''
salt = secrets.token_bytes(16)
digest = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 390000)
salt_b64 = base64.b64encode(salt).decode()
digest_b64 = base64.b64encode(digest).decode()
print(f'pbkdf2_sha256\$390000\${salt_b64}\${digest_b64}')
" 2>/dev/null || python3 -c "
import hashlib, secrets, base64
password = '''$PASSWORD'''
salt = secrets.token_bytes(16)
digest = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 390000)
salt_b64 = base64.b64encode(salt).decode()
digest_b64 = base64.b64encode(digest).decode()
print(f'pbkdf2_sha256\$390000\${salt_b64}\${digest_b64}')
")

EMAIL_SQL="NULL"
if [[ -n "$EMAIL" ]]; then
  EMAIL_SQL="'$EMAIL'"
fi

docker exec -i "$DB_CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" <<SQL
INSERT INTO frya_users (username, email, role, password_hash, is_active, session_version)
VALUES ('$USERNAME', $EMAIL_SQL, 'admin', '$PW_HASH', TRUE, 1)
ON CONFLICT (username) DO UPDATE
  SET password_hash = EXCLUDED.password_hash,
      role = 'admin',
      is_active = TRUE,
      session_version = frya_users.session_version + 1,
      updated_at = NOW();
SELECT username, email, role, is_active, session_version FROM frya_users WHERE username='$USERNAME';
SQL

echo ""
echo "Admin '$USERNAME' seeded successfully."
echo "Login at: https://api.staging.myfrya.de/auth/login"
