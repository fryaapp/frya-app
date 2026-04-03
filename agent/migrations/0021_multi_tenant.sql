-- Migration 0021: Multi-Tenant Alpha - tenant_id zu allen Tabellen
-- P-13 Phase 2: Luecken schliessen
--
-- Adds tenant_id TEXT to all tables that reference case/invoice data
-- but do not yet carry a tenant_id column.
-- Uses ADD COLUMN IF NOT EXISTS (PostgreSQL 9.6+).
-- Backfills from parent tables where a FK relationship exists.

BEGIN;

-- ============================================================
-- 1. frya_approvals
-- ============================================================
ALTER TABLE frya_approvals
    ADD COLUMN IF NOT EXISTS tenant_id TEXT;

CREATE INDEX IF NOT EXISTS idx_approvals_tenant
    ON frya_approvals(tenant_id);

UPDATE frya_approvals
SET    tenant_id = (
           SELECT tenant_id::text
           FROM   case_cases
           WHERE  case_cases.id::text = frya_approvals.case_id
           LIMIT  1
       )
WHERE  tenant_id IS NULL;

-- ============================================================
-- 2. frya_audit_log
-- ============================================================
ALTER TABLE frya_audit_log
    ADD COLUMN IF NOT EXISTS tenant_id TEXT;

CREATE INDEX IF NOT EXISTS idx_audit_tenant
    ON frya_audit_log(tenant_id);

UPDATE frya_audit_log
SET    tenant_id = (
           SELECT tenant_id::text
           FROM   case_cases
           WHERE  case_cases.id::text = frya_audit_log.case_id
           LIMIT  1
       )
WHERE  tenant_id IS NULL;

-- ============================================================
-- 3. frya_open_items
-- ============================================================
ALTER TABLE frya_open_items
    ADD COLUMN IF NOT EXISTS tenant_id TEXT;

CREATE INDEX IF NOT EXISTS idx_open_items_tenant
    ON frya_open_items(tenant_id);

UPDATE frya_open_items
SET    tenant_id = (
           SELECT tenant_id::text
           FROM   case_cases
           WHERE  case_cases.id::text = frya_open_items.case_id
           LIMIT  1
       )
WHERE  tenant_id IS NULL;

-- ============================================================
-- 4. frya_problem_cases
-- ============================================================
ALTER TABLE frya_problem_cases
    ADD COLUMN IF NOT EXISTS tenant_id TEXT;

CREATE INDEX IF NOT EXISTS idx_problem_cases_tenant
    ON frya_problem_cases(tenant_id);

UPDATE frya_problem_cases
SET    tenant_id = (
           SELECT tenant_id::text
           FROM   case_cases
           WHERE  case_cases.id::text = frya_problem_cases.case_id
           LIMIT  1
       )
WHERE  tenant_id IS NULL;

-- ============================================================
-- 5. frya_telegram_case_links
-- ============================================================
ALTER TABLE frya_telegram_case_links
    ADD COLUMN IF NOT EXISTS tenant_id TEXT;

CREATE INDEX IF NOT EXISTS idx_tg_links_tenant
    ON frya_telegram_case_links(tenant_id);

UPDATE frya_telegram_case_links
SET    tenant_id = (
           SELECT tenant_id::text
           FROM   case_cases
           WHERE  case_cases.id::text = frya_telegram_case_links.case_id
           LIMIT  1
       )
WHERE  tenant_id IS NULL;

-- ============================================================
-- 6. frya_email_intake  (neues Feature - kein Backfill noetig)
-- ============================================================
ALTER TABLE frya_email_intake
    ADD COLUMN IF NOT EXISTS tenant_id TEXT;

CREATE INDEX IF NOT EXISTS idx_email_intake_tenant
    ON frya_email_intake(tenant_id);

-- ============================================================
-- 7. frya_email_attachments  (neues Feature - kein Backfill noetig)
-- ============================================================
ALTER TABLE frya_email_attachments
    ADD COLUMN IF NOT EXISTS tenant_id TEXT;

CREATE INDEX IF NOT EXISTS idx_email_attachments_tenant
    ON frya_email_attachments(tenant_id);

-- ============================================================
-- 8. case_documents
-- ============================================================
ALTER TABLE case_documents
    ADD COLUMN IF NOT EXISTS tenant_id TEXT;

CREATE INDEX IF NOT EXISTS idx_case_documents_tenant
    ON case_documents(tenant_id);

UPDATE case_documents
SET    tenant_id = (
           SELECT tenant_id::text
           FROM   case_cases
           WHERE  case_cases.id = case_documents.case_id::uuid
           LIMIT  1
       )
WHERE  tenant_id IS NULL;

-- ============================================================
-- 9. case_references
-- ============================================================
ALTER TABLE case_references
    ADD COLUMN IF NOT EXISTS tenant_id TEXT;

CREATE INDEX IF NOT EXISTS idx_case_references_tenant
    ON case_references(tenant_id);

UPDATE case_references
SET    tenant_id = (
           SELECT tenant_id::text
           FROM   case_cases
           WHERE  case_cases.id = case_references.case_id::uuid
           LIMIT  1
       )
WHERE  tenant_id IS NULL;

-- ============================================================
-- 10. case_conflicts
-- ============================================================
ALTER TABLE case_conflicts
    ADD COLUMN IF NOT EXISTS tenant_id TEXT;

CREATE INDEX IF NOT EXISTS idx_case_conflicts_tenant
    ON case_conflicts(tenant_id);

UPDATE case_conflicts
SET    tenant_id = (
           SELECT tenant_id::text
           FROM   case_cases
           WHERE  case_cases.id = case_conflicts.case_id::uuid
           LIMIT  1
       )
WHERE  tenant_id IS NULL;

-- ============================================================
-- 11. frya_invoice_items  (Backfill ueber frya_invoices)
-- ============================================================
ALTER TABLE frya_invoice_items
    ADD COLUMN IF NOT EXISTS tenant_id TEXT;

CREATE INDEX IF NOT EXISTS idx_invoice_items_tenant
    ON frya_invoice_items(tenant_id);

UPDATE frya_invoice_items
SET    tenant_id = (
           SELECT tenant_id::text
           FROM   frya_invoices
           WHERE  frya_invoices.id = frya_invoice_items.invoice_id
           LIMIT  1
       )
WHERE  tenant_id IS NULL;

-- ============================================================
-- HINWEIS: frya_users.tenant_id bleibt NULLABLE.
-- Admin-User haben keinen Tenant und duerfen keinen haben.
-- KEIN ALTER TABLE frya_users ALTER COLUMN tenant_id SET NOT NULL.
-- ============================================================

COMMIT;
