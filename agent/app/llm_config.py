from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

import asyncpg
from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

IONOS_BASE_URL = 'https://openai.inference.de-txl.ionos.com/v1'

# Canonical agent catalog — source of truth for planned architecture.
# agent_status: 'active' = implemented & deployed, 'planned' = defined but not yet wired.
# target_model / provider reflect the intended production config.
# Notes on model mapping (verified 2026-03-18 against IONOS /v1/models):
#   - 405B target: IONOS has "Meta-Llama-3.1-405B-Instruct-FP8" (FP8-quantised, same model)
#   - LightOnOCR: IONOS id is "lightonai/LightOnOCR-2-1B" (org name differs from HF listing)
#   - Mistral-Small-24B-Instruct-2501: IONOS lists without version suffix
#   - GPT-OSS 120B: IONOS id is "openai/gpt-oss-120b"
#   - communicator: Anthropic direct (claude-sonnet-4-6) via FRYA_ANTHROPIC_API_KEY
AGENT_CATALOG: dict[str, dict] = {
    'orchestrator': {
        'label': 'Orchestrator',
        'provider': 'ionos',
        'target_model': 'meta-llama/Meta-Llama-3.1-405B-Instruct-FP8',
        'base_url': IONOS_BASE_URL,
        'agent_status': 'active',
        'note': 'IONOS DE — 405B-Instruct-FP8 (FP8-quantised, target: 405B-Instruct)',
    },
    'communicator': {
        'label': 'Kommunikator',
        'provider': 'anthropic',
        'target_model': 'claude-sonnet-4-6',
        'base_url': None,
        'agent_status': 'active',
        'note': 'Anthropic — Claude Sonnet 4.6 (direkter Anthropic-Key via FRYA_ANTHROPIC_API_KEY)',
    },
    'document_analyst': {
        'label': 'Document Analyst (OCR)',
        'provider': 'ionos',
        'target_model': 'lightonai/LightOnOCR-2-1B',
        'base_url': IONOS_BASE_URL,
        'agent_status': 'active',
        'note': 'IONOS DE — LightOnOCR-2-1B (IONOS id differs from HF: LightOn/LightOn-OCR-2-1B)',
    },
    'document_analyst_semantic': {
        'label': 'Document Analyst (Semantik)',
        'provider': 'ionos',
        'target_model': 'mistralai/Mistral-Small-24B-Instruct',
        'base_url': IONOS_BASE_URL,
        'agent_status': 'active',
        'note': 'IONOS DE — Mistral-Small-24B (IONOS ohne -2501 Suffix)',
    },
    'accounting_analyst': {
        'label': 'Accounting Analyst',
        'provider': 'ionos',
        'target_model': 'mistralai/Mistral-Small-24B-Instruct',
        'base_url': IONOS_BASE_URL,
        'agent_status': 'active',
        'note': 'IONOS DE — Mistral-Small-24B (SKR03 Buchungsvorschlaege)',
    },
    'deadline_analyst': {
        'label': 'Deadline Analyst',
        'provider': 'ionos',
        'target_model': 'mistralai/Mistral-Small-24B-Instruct',
        'base_url': IONOS_BASE_URL,
        'agent_status': 'active',
        'note': 'IONOS DE — Mistral-Small-24B (Fristueberwachung, Skonto-Warnung)',
    },
    'risk_consistency': {
        'label': 'Risk & Konsistenzpruefer',
        'provider': 'ionos',
        'target_model': 'openai/gpt-oss-120b',
        'base_url': IONOS_BASE_URL,
        'agent_status': 'active',
        'note': 'IONOS DE — GPT-OSS 120B (Risikoanalyse, Konsistenzpruefung)',
    },
    'memory_curator': {
        'label': 'Memory Curator',
        'provider': 'ionos',
        'target_model': 'meta-llama/Meta-Llama-3.1-405B-Instruct-FP8',
        'base_url': IONOS_BASE_URL,
        'agent_status': 'active',
        'note': 'IONOS DE — Llama-3.1-405B-Instruct-FP8 (Langzeitgedächtnis-Kuration)',
    },
}

# Ordered list used for UI display and API validation
KNOWN_AGENTS: tuple[str, ...] = tuple(AGENT_CATALOG.keys())

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS frya_agent_llm_config (
    agent_id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    api_key_encrypted TEXT,
    base_url TEXT,
    is_active BOOLEAN DEFAULT true,
    agent_status VARCHAR(20) DEFAULT 'active',
    last_health_check TIMESTAMPTZ,
    last_health_status TEXT,
    updated_at TIMESTAMPTZ DEFAULT NOW()
)
"""

_SEED_AGENT = """
INSERT INTO frya_agent_llm_config (agent_id, provider, model, base_url, agent_status)
VALUES ($1, $2, $3, $4, $5)
ON CONFLICT (agent_id) DO NOTHING
"""


def _get_fernet(encryption_key: str | None) -> Fernet | None:
    if not encryption_key:
        return None
    return Fernet(encryption_key.encode() if isinstance(encryption_key, str) else encryption_key)


def encrypt_api_key(plaintext: str, encryption_key: str | None) -> str | None:
    if not plaintext:
        return None
    fernet = _get_fernet(encryption_key)
    if fernet is None:
        raise ValueError('FRYA_CONFIG_ENCRYPTION_KEY is required to store API keys')
    return fernet.encrypt(plaintext.encode()).decode()


def decrypt_api_key(ciphertext: str | None, encryption_key: str | None) -> str | None:
    if not ciphertext:
        return None
    fernet = _get_fernet(encryption_key)
    if fernet is None:
        return None
    try:
        return fernet.decrypt(ciphertext.encode()).decode()
    except InvalidToken:
        logger.warning('Failed to decrypt API key — invalid token or wrong encryption key')
        return None


class LLMConfigRepository:
    def __init__(self, database_url: str, redis_url: str, encryption_key: str | None = None) -> None:
        self.database_url = database_url
        self.redis_url = redis_url
        self.encryption_key = encryption_key
        self._memory_store: dict[str, dict] = {}
        self._redis = None

    @property
    def is_memory(self) -> bool:
        return self.database_url.startswith('memory://')

    async def setup(self) -> None:
        if self.is_memory:
            # Seed all agents to memory store (ON CONFLICT DO NOTHING semantics)
            now = datetime.now(timezone.utc).isoformat()
            for agent_id, meta in AGENT_CATALOG.items():
                if agent_id not in self._memory_store:
                    self._memory_store[agent_id] = {
                        'agent_id': agent_id,
                        'provider': meta['provider'],
                        'model': meta['target_model'],
                        'api_key_encrypted': None,
                        'base_url': meta.get('base_url'),
                        'is_active': meta['agent_status'] == 'active',
                        'agent_status': meta['agent_status'],
                        'last_health_check': None,
                        'last_health_status': None,
                        'updated_at': now,
                    }
            return

        conn = await asyncpg.connect(self.database_url)
        try:
            await conn.execute(_CREATE_TABLE)
            # Idempotent: add column to existing tables that predate this schema
            await conn.execute(
                "ALTER TABLE frya_agent_llm_config "
                "ADD COLUMN IF NOT EXISTS agent_status VARCHAR(20) DEFAULT 'active'"
            )
            # Ensure existing rows have agent_status set
            await conn.execute(
                "UPDATE frya_agent_llm_config SET agent_status = 'active' "
                "WHERE agent_status IS NULL"
            )
            # Seed all 8 agents (ON CONFLICT DO NOTHING — never overwrites existing configs)
            for agent_id, meta in AGENT_CATALOG.items():
                await conn.execute(
                    _SEED_AGENT,
                    agent_id, meta['provider'], meta['target_model'],
                    meta.get('base_url'), meta['agent_status'],
                )
        finally:
            await conn.close()

    async def _get_redis(self):
        if self._redis is not None:
            return self._redis
        if self.redis_url.startswith('memory://'):
            return None
        try:
            import redis.asyncio as aioredis
            self._redis = aioredis.from_url(self.redis_url, decode_responses=True)
            return self._redis
        except Exception:
            return None

    def _cache_key(self, agent_id: str) -> str:
        return f'frya:llm_config:{agent_id}'

    async def _cache_get(self, agent_id: str) -> dict | None:
        r = await self._get_redis()
        if r is None:
            return None
        try:
            raw = await r.get(self._cache_key(agent_id))
            return json.loads(raw) if raw else None
        except Exception:
            return None

    async def _cache_set(self, agent_id: str, data: dict) -> None:
        r = await self._get_redis()
        if r is None:
            return
        try:
            await r.set(self._cache_key(agent_id), json.dumps(data), ex=300)
        except Exception:
            pass

    async def _cache_delete(self, agent_id: str) -> None:
        r = await self._get_redis()
        if r is None:
            return
        try:
            await r.delete(self._cache_key(agent_id))
        except Exception:
            pass

    async def get_config(self, agent_id: str) -> dict | None:
        cached = await self._cache_get(agent_id)
        if cached is not None:
            return cached

        if self.is_memory:
            row = self._memory_store.get(agent_id)
            if row:
                await self._cache_set(agent_id, row)
            return row

        conn = await asyncpg.connect(self.database_url)
        try:
            row = await conn.fetchrow(
                'SELECT * FROM frya_agent_llm_config WHERE agent_id = $1',
                agent_id,
            )
        finally:
            await conn.close()

        if row is None:
            return None

        data = dict(row)
        if data.get('last_health_check'):
            data['last_health_check'] = data['last_health_check'].isoformat()
        if data.get('updated_at'):
            data['updated_at'] = data['updated_at'].isoformat()

        await self._cache_set(agent_id, data)
        return data

    async def get_all_configs(self) -> list[dict]:
        if self.is_memory:
            return list(self._memory_store.values())

        conn = await asyncpg.connect(self.database_url)
        try:
            rows = await conn.fetch('SELECT * FROM frya_agent_llm_config ORDER BY agent_id')
        finally:
            await conn.close()

        result = []
        for row in rows:
            data = dict(row)
            if data.get('last_health_check'):
                data['last_health_check'] = data['last_health_check'].isoformat()
            if data.get('updated_at'):
                data['updated_at'] = data['updated_at'].isoformat()
            result.append(data)
        return result

    async def upsert_config(
        self,
        agent_id: str,
        provider: str,
        model: str,
        api_key: str | None = None,
        base_url: str | None = None,
        *,
        clear_key: bool = False,
    ) -> dict:
        encrypted_key = encrypt_api_key(api_key, self.encryption_key) if api_key else None
        now = datetime.now(timezone.utc)

        if self.is_memory:
            existing = self._memory_store.get(agent_id, {})
            if clear_key:
                keep_key = None
            else:
                keep_key = encrypted_key or existing.get('api_key_encrypted')
            record = {
                'agent_id': agent_id,
                'provider': provider,
                'model': model,
                'api_key_encrypted': keep_key,
                'base_url': base_url,
                'is_active': True,
                'agent_status': existing.get('agent_status', 'active'),
                'last_health_check': existing.get('last_health_check'),
                'last_health_status': existing.get('last_health_status'),
                'updated_at': now.isoformat(),
            }
            self._memory_store[agent_id] = record
            await self._cache_delete(agent_id)
            return record

        conn = await asyncpg.connect(self.database_url)
        try:
            if encrypted_key:
                row = await conn.fetchrow(
                    """
                    INSERT INTO frya_agent_llm_config (agent_id, provider, model, api_key_encrypted, base_url, updated_at)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    ON CONFLICT (agent_id) DO UPDATE SET
                        provider = EXCLUDED.provider,
                        model = EXCLUDED.model,
                        api_key_encrypted = EXCLUDED.api_key_encrypted,
                        base_url = EXCLUDED.base_url,
                        updated_at = EXCLUDED.updated_at
                    RETURNING *
                    """,
                    agent_id, provider, model, encrypted_key, base_url, now,
                )
            elif clear_key:
                row = await conn.fetchrow(
                    """
                    INSERT INTO frya_agent_llm_config (agent_id, provider, model, base_url, updated_at)
                    VALUES ($1, $2, $3, $4, $5)
                    ON CONFLICT (agent_id) DO UPDATE SET
                        provider = EXCLUDED.provider,
                        model = EXCLUDED.model,
                        api_key_encrypted = NULL,
                        base_url = EXCLUDED.base_url,
                        updated_at = EXCLUDED.updated_at
                    RETURNING *
                    """,
                    agent_id, provider, model, base_url, now,
                )
            else:
                row = await conn.fetchrow(
                    """
                    INSERT INTO frya_agent_llm_config (agent_id, provider, model, base_url, updated_at)
                    VALUES ($1, $2, $3, $4, $5)
                    ON CONFLICT (agent_id) DO UPDATE SET
                        provider = EXCLUDED.provider,
                        model = EXCLUDED.model,
                        base_url = EXCLUDED.base_url,
                        updated_at = EXCLUDED.updated_at
                    RETURNING *
                    """,
                    agent_id, provider, model, base_url, now,
                )
        finally:
            await conn.close()

        await self._cache_delete(agent_id)
        data = dict(row)
        if data.get('last_health_check'):
            data['last_health_check'] = data['last_health_check'].isoformat()
        if data.get('updated_at'):
            data['updated_at'] = data['updated_at'].isoformat()
        return data

    async def update_health_status(self, agent_id: str, status: str) -> None:
        now = datetime.now(timezone.utc)

        if self.is_memory:
            if agent_id in self._memory_store:
                self._memory_store[agent_id]['last_health_check'] = now.isoformat()
                self._memory_store[agent_id]['last_health_status'] = status
            await self._cache_delete(agent_id)
            return

        conn = await asyncpg.connect(self.database_url)
        try:
            await conn.execute(
                """
                UPDATE frya_agent_llm_config
                SET last_health_check = $1, last_health_status = $2
                WHERE agent_id = $3
                """,
                now, status, agent_id,
            )
        finally:
            await conn.close()
        await self._cache_delete(agent_id)

    def get_env_fallback(self) -> dict:
        return {
            'provider': os.environ.get('FRYA_LLM_PROVIDER', ''),
            'model': os.environ.get('FRYA_LLM_MODEL', ''),
            'api_key_set': bool(os.environ.get('FRYA_LLM_API_KEY') or os.environ.get('FRYA_OPENAI_API_KEY') or os.environ.get('FRYA_ANTHROPIC_API_KEY')),
        }

    async def get_config_or_fallback(self, agent_id: str) -> dict:
        config = await self.get_config(agent_id)
        if config is not None:
            return config
        fallback = self.get_env_fallback()
        return {
            'agent_id': agent_id,
            'provider': fallback['provider'],
            'model': fallback['model'],
            'api_key_encrypted': None,
            'base_url': None,
            'is_active': False,
            'agent_status': AGENT_CATALOG.get(agent_id, {}).get('agent_status', 'active'),
            'last_health_check': None,
            'last_health_status': None,
            'updated_at': None,
            '_from_env': True,
        }

    def decrypt_key_for_call(self, config: dict) -> str | None:
        key = decrypt_api_key(config.get('api_key_encrypted'), self.encryption_key)
        if key:
            return key
        # Env-var fallback based on provider
        provider = (config.get('provider') or '').strip().lower()
        if provider == 'anthropic':
            return os.environ.get('FRYA_ANTHROPIC_API_KEY') or None
        if provider == 'ionos':
            return os.environ.get('FRYA_IONOS_API_KEY') or None
        if provider == 'openai':
            return os.environ.get('FRYA_OPENAI_API_KEY') or None
        # Generic fallback
        return os.environ.get('FRYA_LLM_API_KEY') or os.environ.get('FRYA_OPENAI_API_KEY') or None
