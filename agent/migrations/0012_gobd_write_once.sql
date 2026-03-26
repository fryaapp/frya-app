-- Migration 0012: GoBD Write-Once Enforcement
-- Revokes UPDATE and DELETE on immutable audit/document tables.
-- INSERT and SELECT remain fully granted.
-- Idempotent: REVOKE is a no-op if privilege not held.

-- frya_audit_log: append-only, hash-chained — never modify or delete
REVOKE UPDATE, DELETE, TRUNCATE ON frya_audit_log FROM frya;

-- case_documents: GoBD requires document assignments to be immutable
REVOKE UPDATE, DELETE, TRUNCATE ON case_documents FROM frya;

-- case_references: extracted references must not be tampered with
REVOKE UPDATE, DELETE, TRUNCATE ON case_references FROM frya;
