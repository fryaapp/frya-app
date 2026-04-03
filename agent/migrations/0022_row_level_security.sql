-- Migration 0022: Row-Level Security fuer Multi-Tenant Isolation
-- P-13 Phase 3 + P-15 Fix: UUID::text Cast, FORCE RLS, NULL-Bypass
--
-- Fixes gegenueber V1:
--   1. tenant_id::text Cast fuer UUID-Spalten (uuid != text)
--   2. FORCE ROW LEVEL SECURITY (gilt auch fuer Table Owner)
--   3. current_tenant_id() IS NULL Bypass (Startup/System-Operationen)

BEGIN;

-- Hilfsfunktion: Aktuellen Tenant aus Session-Variable lesen
CREATE OR REPLACE FUNCTION current_tenant_id() RETURNS TEXT AS $$
BEGIN
    RETURN current_setting('app.current_tenant', true);
END;
$$ LANGUAGE plpgsql STABLE;

-- ============================================================
-- Dynamisches Setup: Fuer jede Tabelle RLS + FORCE + Policies
-- mit automatischem UUID::text Cast
-- ============================================================

DO $do$
DECLARE
    tbl TEXT;
    col_type TEXT;
    using_expr TEXT;
    check_expr TEXT;
BEGIN
    FOR tbl IN SELECT unnest(ARRAY[
        -- UUID tenant_id Tabellen
        'frya_accounts', 'frya_contacts', 'frya_cost_centers', 'frya_projects',
        'frya_bookings', 'frya_accounting_open_items', 'frya_invoices',
        'frya_legal_documents', 'document_upload_batches', 'document_upload_items',
        'case_cases',
        -- TEXT tenant_id Tabellen
        'frya_invoice_items', 'frya_user_preferences', 'frya_alpha_feedback',
        'frya_vendor_aliases', 'frya_dunning_config', 'frya_reminders',
        'frya_token_usage', 'case_documents', 'case_references', 'case_conflicts',
        'frya_approvals', 'frya_audit_log', 'frya_open_items',
        'frya_problem_cases', 'frya_telegram_case_links',
        'frya_email_intake', 'frya_email_attachments'
    ]) LOOP
        -- Spaltentyp bestimmen
        SELECT data_type INTO col_type
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = tbl AND column_name = 'tenant_id';

        IF col_type IS NULL THEN
            RAISE NOTICE 'SKIP: % hat keine tenant_id Spalte', tbl;
            CONTINUE;
        END IF;

        -- Expression je nach Typ (UUID braucht ::text Cast)
        IF col_type = 'uuid' THEN
            using_expr := 'current_tenant_id() IS NULL OR tenant_id::text = current_tenant_id()';
            check_expr := 'current_tenant_id() IS NULL OR tenant_id::text = current_tenant_id()';
        ELSE
            using_expr := 'current_tenant_id() IS NULL OR tenant_id = current_tenant_id()';
            check_expr := 'current_tenant_id() IS NULL OR tenant_id = current_tenant_id()';
        END IF;

        -- RLS aktivieren + FORCE (gilt auch fuer Table Owner)
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', tbl);
        EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', tbl);

        -- Alte Policies droppen
        EXECUTE format('DROP POLICY IF EXISTS tenant_isolation_select ON %I', tbl);
        EXECUTE format('DROP POLICY IF EXISTS tenant_isolation_insert ON %I', tbl);
        EXECUTE format('DROP POLICY IF EXISTS tenant_isolation_update ON %I', tbl);
        EXECUTE format('DROP POLICY IF EXISTS tenant_isolation_delete ON %I', tbl);

        -- Neue Policies mit NULL-Bypass (fuer Startup/System-Operationen ohne Tenant-Kontext)
        EXECUTE format('CREATE POLICY tenant_isolation_select ON %I FOR SELECT USING (%s)', tbl, using_expr);
        EXECUTE format('CREATE POLICY tenant_isolation_insert ON %I FOR INSERT WITH CHECK (%s)', tbl, check_expr);
        EXECUTE format('CREATE POLICY tenant_isolation_update ON %I FOR UPDATE USING (%s)', tbl, using_expr);
        EXECUTE format('CREATE POLICY tenant_isolation_delete ON %I FOR DELETE USING (%s)', tbl, using_expr);

        RAISE NOTICE 'RLS enabled for % (type: %)', tbl, col_type;
    END LOOP;
END $do$;

-- ============================================================
-- AUSNAHMEN (KEIN RLS):
-- - frya_users: Login muss cross-tenant funktionieren
-- - frya_business_profile: Eigene Tenant-Logik
-- - frya_tenants: Ist die Tenant-Tabelle selbst
-- - frya_agent_llm_config: Globale Config
-- - frya_rule_change_audit: Globale Config
-- ============================================================

COMMIT;
