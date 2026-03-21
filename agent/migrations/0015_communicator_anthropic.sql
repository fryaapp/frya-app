-- Migration 0015: Switch communicator agent from IONOS/Llama to Anthropic/Claude Sonnet 4.6
-- The seed logic uses ON CONFLICT DO NOTHING, so existing rows must be updated explicitly.

UPDATE frya_agent_llm_config
SET
    provider   = 'anthropic',
    model      = 'claude-sonnet-4-6',
    base_url   = NULL,
    updated_at = NOW()
WHERE agent_id = 'communicator';
