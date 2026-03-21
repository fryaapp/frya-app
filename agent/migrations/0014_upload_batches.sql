-- Migration 0014: Bulk-Upload Batch-Tracking
-- document_upload_batches: one row per upload session
-- document_upload_items: one row per file in a batch

-- Batch-Header
CREATE TABLE IF NOT EXISTS document_upload_batches (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    uploaded_by VARCHAR(100) NOT NULL,
    file_count INT NOT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'uploading',
    -- Batch-Status: uploading → processing → reevaluating → completed → completed_with_errors
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_batches_tenant ON document_upload_batches(tenant_id);
CREATE INDEX IF NOT EXISTS idx_batches_status ON document_upload_batches(tenant_id, status);

-- Einzelne Items im Batch
CREATE TABLE IF NOT EXISTS document_upload_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    batch_id UUID NOT NULL REFERENCES document_upload_batches(id) ON DELETE CASCADE,
    tenant_id UUID NOT NULL,  -- Denormalisiert für Tenant-Isolation
    filename VARCHAR(500) NOT NULL,
    file_size_bytes INT,
    file_hash VARCHAR(64),  -- SHA256 für Intra-Batch Duplikat-Erkennung
    paperless_task_id VARCHAR(200),
    paperless_document_id INT,
    status VARCHAR(30) NOT NULL DEFAULT 'uploading',
    -- Item-Status: uploading → uploaded → processing → completed → error
    --              uploading → duplicate_skipped (wenn Hash-Duplikat in selbem Batch)
    --              uploaded → stuck_timeout (wenn Paperless-Task >30min PENDING)
    case_id UUID,  -- FK nicht enforced (darf NULL sein)
    assignment_confidence VARCHAR(20),  -- CERTAIN|HIGH|MEDIUM|LOW
    error_message TEXT,
    metadata JSONB NOT NULL DEFAULT '{}',  -- Speichert doc_data für Re-Evaluate
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_items_batch ON document_upload_items(batch_id);
CREATE INDEX IF NOT EXISTS idx_items_status ON document_upload_items(status);
CREATE INDEX IF NOT EXISTS idx_items_paperless_doc ON document_upload_items(tenant_id, paperless_document_id);
CREATE INDEX IF NOT EXISTS idx_items_batch_hash ON document_upload_items(batch_id, file_hash);
