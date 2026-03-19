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
    akaunting_email: str | None = None
    akaunting_password: str | None = None

    telegram_bot_token: str | None = None
    telegram_webhook_secret: str | None = None
    telegram_default_chat_id: str | None = None
    telegram_allowed_chat_ids: str | None = None
    telegram_allowed_direct_chat_ids: str | None = None
    telegram_allowed_user_ids: str | None = None
    telegram_dedup_ttl_seconds: int = 86400
    telegram_media_max_bytes: int = 10485760
    telegram_media_allowed_mime_types: str = 'image/jpeg,image/png,application/pdf'
    telegram_media_allowed_extensions: str = '.jpg,.jpeg,.png,.pdf'

    n8n_base_url: str
    n8n_token: str | None = None
    n8n_default_workflow: str = 'default-frya-workflow'

    auth_users_json: str = '[]'
    auth_session_secret: str
    auth_session_cookie_name: str = 'frya_session'
    auth_session_max_age_seconds: int = 28800
    auth_session_idle_timeout_seconds: int = 28800
    auth_cookie_secure: bool = True
    auth_cookie_samesite: str = 'lax'
    auth_cookie_domain: str | None = None
    auth_csrf_header: str = 'x-frya-csrf-token'

    config_encryption_key: str | None = None

    mailgun_webhook_signing_key: str = ''

    # Frya-Mailgun fallback for system mails (password reset, invitations)
    mailgun_api_key: str | None = None
    mailgun_domain: str | None = None
    mailgun_from: str = 'noreply@frya.app'

    # Base URL shown in password-reset links (e.g. https://app.myfrya.de)
    app_base_url: str = 'http://localhost:8001'

    # Mail provider switch: 'brevo' | 'mailgun' (default)
    # Set FRYA_MAIL_PROVIDER=brevo to route system mails via Brevo API v3
    mail_provider: str = 'mailgun'
    brevo_api_key: str | None = None

    # CaseEngine: default tenant for single-tenant deployments.
    # Used when no tenant_id is present in request context.
    # Set to the UUID of the tenant in frya_tenants, or leave empty to
    # use the first active tenant from the DB.
    default_tenant_id: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
