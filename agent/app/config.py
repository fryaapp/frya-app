from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', env_prefix='FRYA_', extra='ignore')

    env: str = 'dev'
    host: str = '0.0.0.0'
    port: int = 8001

    data_dir: Path = Path('./data')
    rules_dir: Path = Path('./data/rules')
    verfahrensdoku_dir: Path = Path('./data/verfahrensdoku')

    database_url: str
    redis_url: str

    llm_model: str = 'openai/gpt-4o-mini'
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None

    paperless_base_url: str
    paperless_token: str | None = None

    akaunting_base_url: str
    akaunting_token: str | None = None

    telegram_bot_token: str | None = None
    telegram_default_chat_id: str | None = None
    telegram_allowed_chat_ids: str | None = None
    telegram_allowed_direct_chat_ids: str | None = None
    telegram_allowed_user_ids: str | None = None
    telegram_dedup_ttl_seconds: int = 86400

    n8n_base_url: str
    n8n_token: str | None = None
    n8n_default_workflow: str = 'default-frya-workflow'

    auth_users_json: str = '[]'
    auth_session_secret: str = 'dev-insecure-session-secret-change-me'
    auth_session_cookie_name: str = 'frya_session'
    auth_session_max_age_seconds: int = 28800
    auth_session_idle_timeout_seconds: int = 28800
    auth_cookie_secure: bool = True
    auth_cookie_samesite: str = 'lax'
    auth_cookie_domain: str | None = None
    auth_csrf_header: str = 'x-frya-csrf-token'


@lru_cache
def get_settings() -> Settings:
    return Settings()
