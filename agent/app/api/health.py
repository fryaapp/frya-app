from __future__ import annotations

from fastapi import APIRouter, Depends

from app.auth.dependencies import require_operator
from app.auth.models import AuthUser
from app.config import get_settings

router = APIRouter(tags=['health'])


@router.get('/health')
async def health() -> dict:
    return {'status': 'ok', 'service': 'frya-agent'}


@router.get('/status')
async def status(_user: AuthUser = Depends(require_operator)) -> dict:
    settings = get_settings()
    rules_dir_exists = settings.rules_dir.exists()
    registry_exists = (settings.rules_dir / 'rule_registry.yaml').exists()

    return {
        'mode': settings.env,
        'architecture': {
            'agent_is_backend': True,
            'separate_backend_service_target': False,
            'legacy_backend_service': 'legacy_only_if_present',
        },
        'sources_of_truth': {
            'financial': 'frya_accounting_postgresql',
            'document': 'paperless',
            'decision': 'frya_audit_log_postgresql',
        },
        'storage': {
            'open_items': 'postgresql',
            'problem_cases': 'postgresql',
            'audit': 'postgresql_append_only_hash_chain',
            'queue_backbone': 'redis',
            'deterministic_scheduling': 'n8n',
        },
        'rules_runtime': {
            'rules_dir': str(settings.rules_dir),
            'rules_dir_exists': rules_dir_exists,
            'rule_registry_exists': registry_exists,
        },
        'service_map': {
            'remain': [
                'agent',
                'traefik',
                'n8n',
                'redis',
                'paperless',
                'tika',
                'gotenberg',
                'postgres',
                'uptime-kuma',
                'keys-ui',
                'watchtower',
            ],
            'legacy_only': ['separate-backend-service'],
            'optional_extensions': ['paperless-ai', 'paperless-gpt'],
            'critical_no_blind_auto_update': ['paperless', 'postgres', 'agent', 'n8n', 'traefik'],
        },
        'integrations': {
            'n8n': settings.n8n_base_url,
            'paperless': settings.paperless_base_url,
        },
        'safety': {
            'python_scheduler': 'disabled',
            'watchtower_blind_updates_for_critical': 'not_allowed_by_architecture',
        },
    }
