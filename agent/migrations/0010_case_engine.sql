-- Migration 0010: CaseEngine tables
-- Apply on staging: psql $DATABASE_URL -f migrations/0010_case_engine.sql

CREATE TABLE IF NOT EXISTS case_cases (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    case_number VARCHAR(50) UNIQUE,
    title VARCHAR(500),
    case_type VARCHAR(50) NOT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'DRAFT',
    vendor_name VARCHAR(500),
    total_amount NUMERIC(12,2),
    currency VARCHAR(3) NOT NULL DEFAULT 'EUR',
    due_date DATE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by VARCHAR(100),
    merged_into_case_id UUID REFERENCES case_cases(id),
    metadata JSONB NOT NULL DEFAULT '{}',
    CONSTRAINT case_cases_status_check
        CHECK (status IN ('DRAFT','OPEN','OVERDUE','PAID','CLOSED','DISCARDED','MERGED'))
);

CREATE INDEX IF NOT EXISTS idx_case_cases_tenant_id     ON case_cases(tenant_id);
CREATE INDEX IF NOT EXISTS idx_case_cases_status        ON case_cases(status);
CREATE INDEX IF NOT EXISTS idx_case_cases_tenant_status ON case_cases(tenant_id, status);

CREATE TABLE IF NOT EXISTS case_documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id UUID NOT NULL REFERENCES case_cases(id),
    document_source VARCHAR(30) NOT NULL,
    document_source_id VARCHAR(200) NOT NULL,
    document_type VARCHAR(50),
    assignment_confidence VARCHAR(20) NOT NULL,
    assignment_method VARCHAR(50) NOT NULL,
    assigned_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    assigned_by VARCHAR(100),
    filename VARCHAR(500),
    metadata JSONB NOT NULL DEFAULT '{}',
    CONSTRAINT case_documents_unique UNIQUE (case_id, document_source, document_source_id)
);

CREATE INDEX IF NOT EXISTS idx_case_documents_case_id ON case_documents(case_id);

CREATE TABLE IF NOT EXISTS case_references (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id UUID NOT NULL REFERENCES case_cases(id),
    reference_type VARCHAR(50) NOT NULL,
    reference_value VARCHAR(500) NOT NULL,
    extracted_from_document_id UUID REFERENCES case_documents(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_case_references_lookup  ON case_references(reference_type, reference_value);
CREATE INDEX IF NOT EXISTS idx_case_references_case_id ON case_references(case_id);

CREATE TABLE IF NOT EXISTS case_conflicts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id UUID NOT NULL REFERENCES case_cases(id),
    conflict_type VARCHAR(50) NOT NULL,
    description TEXT,
    resolution VARCHAR(30),
    resolved_by VARCHAR(100),
    resolved_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata JSONB NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_case_conflicts_case_id ON case_conflicts(case_id);
