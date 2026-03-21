-- Migration 0016: User Preferences + Alpha Feedback
CREATE TABLE IF NOT EXISTS frya_user_preferences (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES frya_tenants(id),
    user_id UUID NOT NULL REFERENCES frya_users(id),
    key VARCHAR(100) NOT NULL,
    value TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(tenant_id, user_id, key)
);

CREATE INDEX IF NOT EXISTS idx_user_prefs_lookup ON frya_user_preferences(tenant_id, user_id, key);

CREATE TABLE IF NOT EXISTS frya_alpha_feedback (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES frya_tenants(id),
    user_id UUID NOT NULL REFERENCES frya_users(id),
    page VARCHAR(255),
    description TEXT NOT NULL,
    screenshot_path VARCHAR(500),
    status VARCHAR(50) NOT NULL DEFAULT 'NEW',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_feedback_status ON frya_alpha_feedback(status, created_at DESC);
