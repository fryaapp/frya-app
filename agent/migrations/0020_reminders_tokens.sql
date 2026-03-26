-- 0020: Reminders + Token Tracking

CREATE TABLE IF NOT EXISTS frya_reminders (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    chat_id TEXT NOT NULL,
    reminder_text TEXT NOT NULL,
    remind_at TIMESTAMPTZ NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    source TEXT NOT NULL DEFAULT 'chat',
    document_ref TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_reminders_pending ON frya_reminders(status, remind_at) WHERE status = 'pending';

CREATE TABLE IF NOT EXISTS frya_token_usage (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    model TEXT NOT NULL,
    provider TEXT NOT NULL,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens INTEGER NOT NULL DEFAULT 0,
    estimated_cost_eur NUMERIC(10,6) NOT NULL DEFAULT 0,
    case_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_token_usage_tenant ON frya_token_usage(tenant_id, created_at);

ALTER TABLE frya_tenants ADD COLUMN IF NOT EXISTS token_budget_eur NUMERIC(10,2) DEFAULT 50.00;
ALTER TABLE frya_tenants ADD COLUMN IF NOT EXISTS token_budget_enabled BOOLEAN DEFAULT false;
