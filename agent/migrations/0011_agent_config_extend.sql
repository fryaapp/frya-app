-- Migration 0011: Extend frya_agent_llm_config with agent_status + seed 8-agent catalog
-- Idempotent: safe to run multiple times.

-- 1. Add agent_status column (idempotent on PG 9.6+)
ALTER TABLE frya_agent_llm_config
    ADD COLUMN IF NOT EXISTS agent_status VARCHAR(20) DEFAULT 'active';

-- 2. Ensure existing rows are marked active
UPDATE frya_agent_llm_config
    SET agent_status = 'active'
    WHERE agent_status IS NULL;

-- 3. Seed all 8 agents — ON CONFLICT DO NOTHING preserves existing provider/model/api_key
INSERT INTO frya_agent_llm_config (agent_id, provider, model, base_url, agent_status) VALUES
    ('orchestrator',             'ionos',   'meta-llama/Meta-Llama-3.1-405B-Instruct-FP8', 'https://openai.inference.de-txl.ionos.com/v1', 'active'),
    ('communicator',             'bedrock',  'anthropic.claude-sonnet-4-6-v1',              NULL,                                           'active'),
    ('document_analyst',         'ionos',   'lightonai/LightOnOCR-2-1B',                   'https://openai.inference.de-txl.ionos.com/v1', 'active'),
    ('document_analyst_semantic','ionos',   'mistralai/Mistral-Small-24B-Instruct',        'https://openai.inference.de-txl.ionos.com/v1', 'planned'),
    ('accounting_analyst',       'ionos',   'mistralai/Mistral-Small-24B-Instruct',        'https://openai.inference.de-txl.ionos.com/v1', 'planned'),
    ('deadline_analyst',         'ionos',   'mistralai/Mistral-Small-24B-Instruct',        'https://openai.inference.de-txl.ionos.com/v1', 'planned'),
    ('risk_consistency',         'ionos',   'openai/gpt-oss-120b',                         'https://openai.inference.de-txl.ionos.com/v1', 'planned'),
    ('memory_curator',           'ionos',   'openai/gpt-oss-120b',                         'https://openai.inference.de-txl.ionos.com/v1', 'planned')
ON CONFLICT (agent_id) DO NOTHING;
