-- Migration 0018: Dunning (Mahnwesen)
ALTER TABLE frya_open_items ADD COLUMN IF NOT EXISTS dunning_level INTEGER NOT NULL DEFAULT 0;
ALTER TABLE frya_open_items ADD COLUMN IF NOT EXISTS dunning_last_sent TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS frya_dunning_config (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id TEXT NOT NULL,
    level INTEGER NOT NULL,
    days_after_due INTEGER NOT NULL,
    tone VARCHAR(50) NOT NULL DEFAULT 'freundlich',
    template_key VARCHAR(100),
    UNIQUE(tenant_id, level)
);
