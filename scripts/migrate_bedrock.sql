-- Aufgabe 2: Bedrock EU Frankfurt — Communicator LLM Config Migration
-- Run on staging/production DB to switch communicator to Bedrock EU

-- Update communicator to Bedrock EU Frankfurt
UPDATE frya_agent_llm_config SET
  provider = 'bedrock',
  model = 'anthropic.claude-sonnet-4-6-20250514-v1:0',
  api_base = 'https://bedrock-runtime.eu-central-1.amazonaws.com',
  -- Note: Bedrock auth uses AWS env vars (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION_NAME)
  -- not the api_key_encrypted field. LiteLLM handles this automatically.
  updated_at = NOW()
WHERE agent_id = 'communicator';

-- Verify
SELECT agent_id, provider, model, api_base, updated_at
FROM frya_agent_llm_config
WHERE agent_id = 'communicator';
