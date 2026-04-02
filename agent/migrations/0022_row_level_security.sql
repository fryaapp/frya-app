-- Migration 0022: Row-Level Security fuer Multi-Tenant Isolation
-- P-13 Phase 3: Zweite Sicherheitsebene neben Application-Layer

BEGIN;

-- Hilfsfunktion: Aktuellen Tenant aus Session-Variable lesen
CREATE OR REPLACE FUNCTION current_tenant_id() RETURNS TEXT AS $$
BEGIN
    RETURN current_setting('app.current_tenant', true);
END;
$$ LANGUAGE plpgsql STABLE;


-- ============================================================
-- 1) frya_accounts
-- ============================================================
ALTER TABLE frya_accounts ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_isolation_select ON frya_accounts;
DROP POLICY IF EXISTS tenant_isolation_insert ON frya_accounts;
DROP POLICY IF EXISTS tenant_isolation_update ON frya_accounts;
DROP POLICY IF EXISTS tenant_isolation_delete ON frya_accounts;

CREATE POLICY tenant_isolation_select ON frya_accounts
    FOR SELECT USING (tenant_id = current_tenant_id());

CREATE POLICY tenant_isolation_insert ON frya_accounts
    FOR INSERT WITH CHECK (tenant_id = current_tenant_id());

CREATE POLICY tenant_isolation_update ON frya_accounts
    FOR UPDATE USING (tenant_id = current_tenant_id());

CREATE POLICY tenant_isolation_delete ON frya_accounts
    FOR DELETE USING (tenant_id = current_tenant_id());


-- ============================================================
-- 2) frya_contacts
-- ============================================================
ALTER TABLE frya_contacts ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_isolation_select ON frya_contacts;
DROP POLICY IF EXISTS tenant_isolation_insert ON frya_contacts;
DROP POLICY IF EXISTS tenant_isolation_update ON frya_contacts;
DROP POLICY IF EXISTS tenant_isolation_delete ON frya_contacts;

CREATE POLICY tenant_isolation_select ON frya_contacts
    FOR SELECT USING (tenant_id = current_tenant_id());

CREATE POLICY tenant_isolation_insert ON frya_contacts
    FOR INSERT WITH CHECK (tenant_id = current_tenant_id());

CREATE POLICY tenant_isolation_update ON frya_contacts
    FOR UPDATE USING (tenant_id = current_tenant_id());

CREATE POLICY tenant_isolation_delete ON frya_contacts
    FOR DELETE USING (tenant_id = current_tenant_id());


-- ============================================================
-- 3) frya_cost_centers
-- ============================================================
ALTER TABLE frya_cost_centers ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_isolation_select ON frya_cost_centers;
DROP POLICY IF EXISTS tenant_isolation_insert ON frya_cost_centers;
DROP POLICY IF EXISTS tenant_isolation_update ON frya_cost_centers;
DROP POLICY IF EXISTS tenant_isolation_delete ON frya_cost_centers;

CREATE POLICY tenant_isolation_select ON frya_cost_centers
    FOR SELECT USING (tenant_id = current_tenant_id());

CREATE POLICY tenant_isolation_insert ON frya_cost_centers
    FOR INSERT WITH CHECK (tenant_id = current_tenant_id());

CREATE POLICY tenant_isolation_update ON frya_cost_centers
    FOR UPDATE USING (tenant_id = current_tenant_id());

CREATE POLICY tenant_isolation_delete ON frya_cost_centers
    FOR DELETE USING (tenant_id = current_tenant_id());


-- ============================================================
-- 4) frya_projects
-- ============================================================
ALTER TABLE frya_projects ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_isolation_select ON frya_projects;
DROP POLICY IF EXISTS tenant_isolation_insert ON frya_projects;
DROP POLICY IF EXISTS tenant_isolation_update ON frya_projects;
DROP POLICY IF EXISTS tenant_isolation_delete ON frya_projects;

CREATE POLICY tenant_isolation_select ON frya_projects
    FOR SELECT USING (tenant_id = current_tenant_id());

CREATE POLICY tenant_isolation_insert ON frya_projects
    FOR INSERT WITH CHECK (tenant_id = current_tenant_id());

CREATE POLICY tenant_isolation_update ON frya_projects
    FOR UPDATE USING (tenant_id = current_tenant_id());

CREATE POLICY tenant_isolation_delete ON frya_projects
    FOR DELETE USING (tenant_id = current_tenant_id());


-- ============================================================
-- 5) frya_bookings
-- ============================================================
ALTER TABLE frya_bookings ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_isolation_select ON frya_bookings;
DROP POLICY IF EXISTS tenant_isolation_insert ON frya_bookings;
DROP POLICY IF EXISTS tenant_isolation_update ON frya_bookings;
DROP POLICY IF EXISTS tenant_isolation_delete ON frya_bookings;

CREATE POLICY tenant_isolation_select ON frya_bookings
    FOR SELECT USING (tenant_id = current_tenant_id());

CREATE POLICY tenant_isolation_insert ON frya_bookings
    FOR INSERT WITH CHECK (tenant_id = current_tenant_id());

CREATE POLICY tenant_isolation_update ON frya_bookings
    FOR UPDATE USING (tenant_id = current_tenant_id());

CREATE POLICY tenant_isolation_delete ON frya_bookings
    FOR DELETE USING (tenant_id = current_tenant_id());


-- ============================================================
-- 6) frya_accounting_open_items
-- ============================================================
ALTER TABLE frya_accounting_open_items ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_isolation_select ON frya_accounting_open_items;
DROP POLICY IF EXISTS tenant_isolation_insert ON frya_accounting_open_items;
DROP POLICY IF EXISTS tenant_isolation_update ON frya_accounting_open_items;
DROP POLICY IF EXISTS tenant_isolation_delete ON frya_accounting_open_items;

CREATE POLICY tenant_isolation_select ON frya_accounting_open_items
    FOR SELECT USING (tenant_id = current_tenant_id());

CREATE POLICY tenant_isolation_insert ON frya_accounting_open_items
    FOR INSERT WITH CHECK (tenant_id = current_tenant_id());

CREATE POLICY tenant_isolation_update ON frya_accounting_open_items
    FOR UPDATE USING (tenant_id = current_tenant_id());

CREATE POLICY tenant_isolation_delete ON frya_accounting_open_items
    FOR DELETE USING (tenant_id = current_tenant_id());


-- ============================================================
-- 7) frya_invoices
-- ============================================================
ALTER TABLE frya_invoices ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_isolation_select ON frya_invoices;
DROP POLICY IF EXISTS tenant_isolation_insert ON frya_invoices;
DROP POLICY IF EXISTS tenant_isolation_update ON frya_invoices;
DROP POLICY IF EXISTS tenant_isolation_delete ON frya_invoices;

CREATE POLICY tenant_isolation_select ON frya_invoices
    FOR SELECT USING (tenant_id = current_tenant_id());

CREATE POLICY tenant_isolation_insert ON frya_invoices
    FOR INSERT WITH CHECK (tenant_id = current_tenant_id());

CREATE POLICY tenant_isolation_update ON frya_invoices
    FOR UPDATE USING (tenant_id = current_tenant_id());

CREATE POLICY tenant_isolation_delete ON frya_invoices
    FOR DELETE USING (tenant_id = current_tenant_id());


-- ============================================================
-- 8) frya_invoice_items
-- ============================================================
ALTER TABLE frya_invoice_items ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_isolation_select ON frya_invoice_items;
DROP POLICY IF EXISTS tenant_isolation_insert ON frya_invoice_items;
DROP POLICY IF EXISTS tenant_isolation_update ON frya_invoice_items;
DROP POLICY IF EXISTS tenant_isolation_delete ON frya_invoice_items;

CREATE POLICY tenant_isolation_select ON frya_invoice_items
    FOR SELECT USING (tenant_id = current_tenant_id());

CREATE POLICY tenant_isolation_insert ON frya_invoice_items
    FOR INSERT WITH CHECK (tenant_id = current_tenant_id());

CREATE POLICY tenant_isolation_update ON frya_invoice_items
    FOR UPDATE USING (tenant_id = current_tenant_id());

CREATE POLICY tenant_isolation_delete ON frya_invoice_items
    FOR DELETE USING (tenant_id = current_tenant_id());


-- ============================================================
-- 9) frya_user_preferences
-- ============================================================
ALTER TABLE frya_user_preferences ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_isolation_select ON frya_user_preferences;
DROP POLICY IF EXISTS tenant_isolation_insert ON frya_user_preferences;
DROP POLICY IF EXISTS tenant_isolation_update ON frya_user_preferences;
DROP POLICY IF EXISTS tenant_isolation_delete ON frya_user_preferences;

CREATE POLICY tenant_isolation_select ON frya_user_preferences
    FOR SELECT USING (tenant_id = current_tenant_id());

CREATE POLICY tenant_isolation_insert ON frya_user_preferences
    FOR INSERT WITH CHECK (tenant_id = current_tenant_id());

CREATE POLICY tenant_isolation_update ON frya_user_preferences
    FOR UPDATE USING (tenant_id = current_tenant_id());

CREATE POLICY tenant_isolation_delete ON frya_user_preferences
    FOR DELETE USING (tenant_id = current_tenant_id());


-- ============================================================
-- 10) frya_alpha_feedback
-- ============================================================
ALTER TABLE frya_alpha_feedback ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_isolation_select ON frya_alpha_feedback;
DROP POLICY IF EXISTS tenant_isolation_insert ON frya_alpha_feedback;
DROP POLICY IF EXISTS tenant_isolation_update ON frya_alpha_feedback;
DROP POLICY IF EXISTS tenant_isolation_delete ON frya_alpha_feedback;

CREATE POLICY tenant_isolation_select ON frya_alpha_feedback
    FOR SELECT USING (tenant_id = current_tenant_id());

CREATE POLICY tenant_isolation_insert ON frya_alpha_feedback
    FOR INSERT WITH CHECK (tenant_id = current_tenant_id());

CREATE POLICY tenant_isolation_update ON frya_alpha_feedback
    FOR UPDATE USING (tenant_id = current_tenant_id());

CREATE POLICY tenant_isolation_delete ON frya_alpha_feedback
    FOR DELETE USING (tenant_id = current_tenant_id());


-- ============================================================
-- 11) frya_vendor_aliases
-- ============================================================
ALTER TABLE frya_vendor_aliases ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_isolation_select ON frya_vendor_aliases;
DROP POLICY IF EXISTS tenant_isolation_insert ON frya_vendor_aliases;
DROP POLICY IF EXISTS tenant_isolation_update ON frya_vendor_aliases;
DROP POLICY IF EXISTS tenant_isolation_delete ON frya_vendor_aliases;

CREATE POLICY tenant_isolation_select ON frya_vendor_aliases
    FOR SELECT USING (tenant_id = current_tenant_id());

CREATE POLICY tenant_isolation_insert ON frya_vendor_aliases
    FOR INSERT WITH CHECK (tenant_id = current_tenant_id());

CREATE POLICY tenant_isolation_update ON frya_vendor_aliases
    FOR UPDATE USING (tenant_id = current_tenant_id());

CREATE POLICY tenant_isolation_delete ON frya_vendor_aliases
    FOR DELETE USING (tenant_id = current_tenant_id());


-- ============================================================
-- 12) frya_dunning_config
-- ============================================================
ALTER TABLE frya_dunning_config ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_isolation_select ON frya_dunning_config;
DROP POLICY IF EXISTS tenant_isolation_insert ON frya_dunning_config;
DROP POLICY IF EXISTS tenant_isolation_update ON frya_dunning_config;
DROP POLICY IF EXISTS tenant_isolation_delete ON frya_dunning_config;

CREATE POLICY tenant_isolation_select ON frya_dunning_config
    FOR SELECT USING (tenant_id = current_tenant_id());

CREATE POLICY tenant_isolation_insert ON frya_dunning_config
    FOR INSERT WITH CHECK (tenant_id = current_tenant_id());

CREATE POLICY tenant_isolation_update ON frya_dunning_config
    FOR UPDATE USING (tenant_id = current_tenant_id());

CREATE POLICY tenant_isolation_delete ON frya_dunning_config
    FOR DELETE USING (tenant_id = current_tenant_id());


-- ============================================================
-- 13) frya_legal_documents
-- ============================================================
ALTER TABLE frya_legal_documents ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_isolation_select ON frya_legal_documents;
DROP POLICY IF EXISTS tenant_isolation_insert ON frya_legal_documents;
DROP POLICY IF EXISTS tenant_isolation_update ON frya_legal_documents;
DROP POLICY IF EXISTS tenant_isolation_delete ON frya_legal_documents;

CREATE POLICY tenant_isolation_select ON frya_legal_documents
    FOR SELECT USING (tenant_id = current_tenant_id());

CREATE POLICY tenant_isolation_insert ON frya_legal_documents
    FOR INSERT WITH CHECK (tenant_id = current_tenant_id());

CREATE POLICY tenant_isolation_update ON frya_legal_documents
    FOR UPDATE USING (tenant_id = current_tenant_id());

CREATE POLICY tenant_isolation_delete ON frya_legal_documents
    FOR DELETE USING (tenant_id = current_tenant_id());


-- ============================================================
-- 14) frya_reminders
-- ============================================================
ALTER TABLE frya_reminders ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_isolation_select ON frya_reminders;
DROP POLICY IF EXISTS tenant_isolation_insert ON frya_reminders;
DROP POLICY IF EXISTS tenant_isolation_update ON frya_reminders;
DROP POLICY IF EXISTS tenant_isolation_delete ON frya_reminders;

CREATE POLICY tenant_isolation_select ON frya_reminders
    FOR SELECT USING (tenant_id = current_tenant_id());

CREATE POLICY tenant_isolation_insert ON frya_reminders
    FOR INSERT WITH CHECK (tenant_id = current_tenant_id());

CREATE POLICY tenant_isolation_update ON frya_reminders
    FOR UPDATE USING (tenant_id = current_tenant_id());

CREATE POLICY tenant_isolation_delete ON frya_reminders
    FOR DELETE USING (tenant_id = current_tenant_id());


-- ============================================================
-- 15) frya_token_usage
-- ============================================================
ALTER TABLE frya_token_usage ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_isolation_select ON frya_token_usage;
DROP POLICY IF EXISTS tenant_isolation_insert ON frya_token_usage;
DROP POLICY IF EXISTS tenant_isolation_update ON frya_token_usage;
DROP POLICY IF EXISTS tenant_isolation_delete ON frya_token_usage;

CREATE POLICY tenant_isolation_select ON frya_token_usage
    FOR SELECT USING (tenant_id = current_tenant_id());

CREATE POLICY tenant_isolation_insert ON frya_token_usage
    FOR INSERT WITH CHECK (tenant_id = current_tenant_id());

CREATE POLICY tenant_isolation_update ON frya_token_usage
    FOR UPDATE USING (tenant_id = current_tenant_id());

CREATE POLICY tenant_isolation_delete ON frya_token_usage
    FOR DELETE USING (tenant_id = current_tenant_id());


-- ============================================================
-- 16) document_upload_batches
-- ============================================================
ALTER TABLE document_upload_batches ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_isolation_select ON document_upload_batches;
DROP POLICY IF EXISTS tenant_isolation_insert ON document_upload_batches;
DROP POLICY IF EXISTS tenant_isolation_update ON document_upload_batches;
DROP POLICY IF EXISTS tenant_isolation_delete ON document_upload_batches;

CREATE POLICY tenant_isolation_select ON document_upload_batches
    FOR SELECT USING (tenant_id = current_tenant_id());

CREATE POLICY tenant_isolation_insert ON document_upload_batches
    FOR INSERT WITH CHECK (tenant_id = current_tenant_id());

CREATE POLICY tenant_isolation_update ON document_upload_batches
    FOR UPDATE USING (tenant_id = current_tenant_id());

CREATE POLICY tenant_isolation_delete ON document_upload_batches
    FOR DELETE USING (tenant_id = current_tenant_id());


-- ============================================================
-- 17) document_upload_items
-- ============================================================
ALTER TABLE document_upload_items ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_isolation_select ON document_upload_items;
DROP POLICY IF EXISTS tenant_isolation_insert ON document_upload_items;
DROP POLICY IF EXISTS tenant_isolation_update ON document_upload_items;
DROP POLICY IF EXISTS tenant_isolation_delete ON document_upload_items;

CREATE POLICY tenant_isolation_select ON document_upload_items
    FOR SELECT USING (tenant_id = current_tenant_id());

CREATE POLICY tenant_isolation_insert ON document_upload_items
    FOR INSERT WITH CHECK (tenant_id = current_tenant_id());

CREATE POLICY tenant_isolation_update ON document_upload_items
    FOR UPDATE USING (tenant_id = current_tenant_id());

CREATE POLICY tenant_isolation_delete ON document_upload_items
    FOR DELETE USING (tenant_id = current_tenant_id());


-- ============================================================
-- 18) case_cases
-- ============================================================
ALTER TABLE case_cases ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_isolation_select ON case_cases;
DROP POLICY IF EXISTS tenant_isolation_insert ON case_cases;
DROP POLICY IF EXISTS tenant_isolation_update ON case_cases;
DROP POLICY IF EXISTS tenant_isolation_delete ON case_cases;

CREATE POLICY tenant_isolation_select ON case_cases
    FOR SELECT USING (tenant_id = current_tenant_id());

CREATE POLICY tenant_isolation_insert ON case_cases
    FOR INSERT WITH CHECK (tenant_id = current_tenant_id());

CREATE POLICY tenant_isolation_update ON case_cases
    FOR UPDATE USING (tenant_id = current_tenant_id());

CREATE POLICY tenant_isolation_delete ON case_cases
    FOR DELETE USING (tenant_id = current_tenant_id());


-- ============================================================
-- 19) case_documents
-- ============================================================
ALTER TABLE case_documents ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_isolation_select ON case_documents;
DROP POLICY IF EXISTS tenant_isolation_insert ON case_documents;
DROP POLICY IF EXISTS tenant_isolation_update ON case_documents;
DROP POLICY IF EXISTS tenant_isolation_delete ON case_documents;

CREATE POLICY tenant_isolation_select ON case_documents
    FOR SELECT USING (tenant_id = current_tenant_id());

CREATE POLICY tenant_isolation_insert ON case_documents
    FOR INSERT WITH CHECK (tenant_id = current_tenant_id());

CREATE POLICY tenant_isolation_update ON case_documents
    FOR UPDATE USING (tenant_id = current_tenant_id());

CREATE POLICY tenant_isolation_delete ON case_documents
    FOR DELETE USING (tenant_id = current_tenant_id());


-- ============================================================
-- 20) case_references
-- ============================================================
ALTER TABLE case_references ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_isolation_select ON case_references;
DROP POLICY IF EXISTS tenant_isolation_insert ON case_references;
DROP POLICY IF EXISTS tenant_isolation_update ON case_references;
DROP POLICY IF EXISTS tenant_isolation_delete ON case_references;

CREATE POLICY tenant_isolation_select ON case_references
    FOR SELECT USING (tenant_id = current_tenant_id());

CREATE POLICY tenant_isolation_insert ON case_references
    FOR INSERT WITH CHECK (tenant_id = current_tenant_id());

CREATE POLICY tenant_isolation_update ON case_references
    FOR UPDATE USING (tenant_id = current_tenant_id());

CREATE POLICY tenant_isolation_delete ON case_references
    FOR DELETE USING (tenant_id = current_tenant_id());


-- ============================================================
-- 21) case_conflicts
-- ============================================================
ALTER TABLE case_conflicts ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_isolation_select ON case_conflicts;
DROP POLICY IF EXISTS tenant_isolation_insert ON case_conflicts;
DROP POLICY IF EXISTS tenant_isolation_update ON case_conflicts;
DROP POLICY IF EXISTS tenant_isolation_delete ON case_conflicts;

CREATE POLICY tenant_isolation_select ON case_conflicts
    FOR SELECT USING (tenant_id = current_tenant_id());

CREATE POLICY tenant_isolation_insert ON case_conflicts
    FOR INSERT WITH CHECK (tenant_id = current_tenant_id());

CREATE POLICY tenant_isolation_update ON case_conflicts
    FOR UPDATE USING (tenant_id = current_tenant_id());

CREATE POLICY tenant_isolation_delete ON case_conflicts
    FOR DELETE USING (tenant_id = current_tenant_id());


-- ============================================================
-- 22) frya_approvals
-- ============================================================
ALTER TABLE frya_approvals ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_isolation_select ON frya_approvals;
DROP POLICY IF EXISTS tenant_isolation_insert ON frya_approvals;
DROP POLICY IF EXISTS tenant_isolation_update ON frya_approvals;
DROP POLICY IF EXISTS tenant_isolation_delete ON frya_approvals;

CREATE POLICY tenant_isolation_select ON frya_approvals
    FOR SELECT USING (tenant_id = current_tenant_id());

CREATE POLICY tenant_isolation_insert ON frya_approvals
    FOR INSERT WITH CHECK (tenant_id = current_tenant_id());

CREATE POLICY tenant_isolation_update ON frya_approvals
    FOR UPDATE USING (tenant_id = current_tenant_id());

CREATE POLICY tenant_isolation_delete ON frya_approvals
    FOR DELETE USING (tenant_id = current_tenant_id());


-- ============================================================
-- 23) frya_audit_log
-- ============================================================
ALTER TABLE frya_audit_log ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_isolation_select ON frya_audit_log;
DROP POLICY IF EXISTS tenant_isolation_insert ON frya_audit_log;
DROP POLICY IF EXISTS tenant_isolation_update ON frya_audit_log;
DROP POLICY IF EXISTS tenant_isolation_delete ON frya_audit_log;

CREATE POLICY tenant_isolation_select ON frya_audit_log
    FOR SELECT USING (tenant_id = current_tenant_id());

CREATE POLICY tenant_isolation_insert ON frya_audit_log
    FOR INSERT WITH CHECK (tenant_id = current_tenant_id());

CREATE POLICY tenant_isolation_update ON frya_audit_log
    FOR UPDATE USING (tenant_id = current_tenant_id());

CREATE POLICY tenant_isolation_delete ON frya_audit_log
    FOR DELETE USING (tenant_id = current_tenant_id());


-- ============================================================
-- 24) frya_open_items
-- ============================================================
ALTER TABLE frya_open_items ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_isolation_select ON frya_open_items;
DROP POLICY IF EXISTS tenant_isolation_insert ON frya_open_items;
DROP POLICY IF EXISTS tenant_isolation_update ON frya_open_items;
DROP POLICY IF EXISTS tenant_isolation_delete ON frya_open_items;

CREATE POLICY tenant_isolation_select ON frya_open_items
    FOR SELECT USING (tenant_id = current_tenant_id());

CREATE POLICY tenant_isolation_insert ON frya_open_items
    FOR INSERT WITH CHECK (tenant_id = current_tenant_id());

CREATE POLICY tenant_isolation_update ON frya_open_items
    FOR UPDATE USING (tenant_id = current_tenant_id());

CREATE POLICY tenant_isolation_delete ON frya_open_items
    FOR DELETE USING (tenant_id = current_tenant_id());


-- ============================================================
-- 25) frya_problem_cases
-- ============================================================
ALTER TABLE frya_problem_cases ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_isolation_select ON frya_problem_cases;
DROP POLICY IF EXISTS tenant_isolation_insert ON frya_problem_cases;
DROP POLICY IF EXISTS tenant_isolation_update ON frya_problem_cases;
DROP POLICY IF EXISTS tenant_isolation_delete ON frya_problem_cases;

CREATE POLICY tenant_isolation_select ON frya_problem_cases
    FOR SELECT USING (tenant_id = current_tenant_id());

CREATE POLICY tenant_isolation_insert ON frya_problem_cases
    FOR INSERT WITH CHECK (tenant_id = current_tenant_id());

CREATE POLICY tenant_isolation_update ON frya_problem_cases
    FOR UPDATE USING (tenant_id = current_tenant_id());

CREATE POLICY tenant_isolation_delete ON frya_problem_cases
    FOR DELETE USING (tenant_id = current_tenant_id());


-- ============================================================
-- 26) frya_telegram_case_links
-- ============================================================
ALTER TABLE frya_telegram_case_links ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_isolation_select ON frya_telegram_case_links;
DROP POLICY IF EXISTS tenant_isolation_insert ON frya_telegram_case_links;
DROP POLICY IF EXISTS tenant_isolation_update ON frya_telegram_case_links;
DROP POLICY IF EXISTS tenant_isolation_delete ON frya_telegram_case_links;

CREATE POLICY tenant_isolation_select ON frya_telegram_case_links
    FOR SELECT USING (tenant_id = current_tenant_id());

CREATE POLICY tenant_isolation_insert ON frya_telegram_case_links
    FOR INSERT WITH CHECK (tenant_id = current_tenant_id());

CREATE POLICY tenant_isolation_update ON frya_telegram_case_links
    FOR UPDATE USING (tenant_id = current_tenant_id());

CREATE POLICY tenant_isolation_delete ON frya_telegram_case_links
    FOR DELETE USING (tenant_id = current_tenant_id());


-- ============================================================
-- 27) frya_email_intake
-- ============================================================
ALTER TABLE frya_email_intake ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_isolation_select ON frya_email_intake;
DROP POLICY IF EXISTS tenant_isolation_insert ON frya_email_intake;
DROP POLICY IF EXISTS tenant_isolation_update ON frya_email_intake;
DROP POLICY IF EXISTS tenant_isolation_delete ON frya_email_intake;

CREATE POLICY tenant_isolation_select ON frya_email_intake
    FOR SELECT USING (tenant_id = current_tenant_id());

CREATE POLICY tenant_isolation_insert ON frya_email_intake
    FOR INSERT WITH CHECK (tenant_id = current_tenant_id());

CREATE POLICY tenant_isolation_update ON frya_email_intake
    FOR UPDATE USING (tenant_id = current_tenant_id());

CREATE POLICY tenant_isolation_delete ON frya_email_intake
    FOR DELETE USING (tenant_id = current_tenant_id());


-- ============================================================
-- 28) frya_email_attachments
-- ============================================================
ALTER TABLE frya_email_attachments ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_isolation_select ON frya_email_attachments;
DROP POLICY IF EXISTS tenant_isolation_insert ON frya_email_attachments;
DROP POLICY IF EXISTS tenant_isolation_update ON frya_email_attachments;
DROP POLICY IF EXISTS tenant_isolation_delete ON frya_email_attachments;

CREATE POLICY tenant_isolation_select ON frya_email_attachments
    FOR SELECT USING (tenant_id = current_tenant_id());

CREATE POLICY tenant_isolation_insert ON frya_email_attachments
    FOR INSERT WITH CHECK (tenant_id = current_tenant_id());

CREATE POLICY tenant_isolation_update ON frya_email_attachments
    FOR UPDATE USING (tenant_id = current_tenant_id());

CREATE POLICY tenant_isolation_delete ON frya_email_attachments
    FOR DELETE USING (tenant_id = current_tenant_id());


-- ============================================================
-- AUSNAHMEN (KEIN RLS):
-- - frya_users: Login muss cross-tenant funktionieren
-- - frya_business_profile: Eigene Tenant-Logik mit Fallback
-- - frya_tenants: Ist die Tenant-Tabelle selbst
-- - frya_agent_llm_config: Globale Config
-- - frya_rule_change_audit: Globale Config
-- ============================================================

-- HINWEIS: RLS gilt NICHT fuer den Table Owner (normalerweise der Admin-User).
-- Fuer den normalen App-User (frya_app) gilt RLS.
-- Der Admin-User kann mit FORCE ROW LEVEL SECURITY erzwungen werden
-- falls gewuenscht, aber fuer Alpha reicht es so.

COMMIT;
