-- Migration 0017: Vendor Aliases
CREATE TABLE IF NOT EXISTS frya_vendor_aliases (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id TEXT NOT NULL,
    canonical_name VARCHAR(255) NOT NULL,
    alias VARCHAR(255) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(tenant_id, alias)
);

CREATE INDEX IF NOT EXISTS idx_vendor_alias_lookup ON frya_vendor_aliases(tenant_id, alias);
