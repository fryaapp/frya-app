from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from litellm import acompletion

from app.auth.csrf import ensure_csrf_token, get_csrf_token, require_csrf
from app.auth.dependencies import require_admin
from app.auth.models import AuthUser
from app.dependencies import get_llm_config_repository
from app.llm_config import AGENT_CATALOG, KNOWN_AGENTS, LLMConfigRepository

logger = logging.getLogger(__name__)

router = APIRouter(tags=['agent-config'])

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / 'ui' / 'templates'))


@router.get('/agent-config', response_class=HTMLResponse)
async def agent_config_page(
    request: Request,
    auth_user: AuthUser = Depends(require_admin),
):
    csrf_token = await ensure_csrf_token(request)
    repo: LLMConfigRepository = get_llm_config_repository()

    agents = []
    for agent_id in KNOWN_AGENTS:
        config = await repo.get_config_or_fallback(agent_id)
        catalog = AGENT_CATALOG.get(agent_id, {})
        agent_status = config.get('agent_status') or catalog.get('agent_status', 'active')
        agents.append({
            'agent_id': agent_id,
            'label': catalog.get('label', agent_id),
            'provider': config.get('provider', ''),
            'model': config.get('model', ''),
            'base_url': config.get('base_url', ''),
            'api_key_set': bool(config.get('api_key_encrypted')),
            'is_active': config.get('is_active', False),
            'agent_status': agent_status,
            'last_health_status': config.get('last_health_status'),
            'last_health_check': config.get('last_health_check'),
            'from_env': config.get('_from_env', False),
            'note': catalog.get('note', ''),
            'target_model': catalog.get('target_model', ''),
        })

    return TEMPLATES.TemplateResponse(
        request,
        'agent_config.html',
        {
            'request': request,
            'csrf_token': csrf_token,
            'auth_user': auth_user,
            'title': 'Agent-Konfiguration',
            'agents': agents,
        },
    )


@router.get('/api/agent-config')
async def list_configs(
    _admin: AuthUser = Depends(require_admin),
):
    repo: LLMConfigRepository = get_llm_config_repository()
    configs = await repo.get_all_configs()

    result = []
    for c in configs:
        result.append({
            'agent_id': c['agent_id'],
            'provider': c['provider'],
            'model': c['model'],
            'base_url': c.get('base_url'),
            'api_key_set': bool(c.get('api_key_encrypted')),
            'is_active': c.get('is_active', False),
            'agent_status': c.get('agent_status', 'active'),
            'last_health_status': c.get('last_health_status'),
            'last_health_check': c.get('last_health_check'),
            'updated_at': c.get('updated_at'),
        })
    return result


@router.post('/api/agent-config/{agent_id}')
async def save_config(
    agent_id: str,
    request: Request,
    _admin: AuthUser = Depends(require_admin),
    _csrf: None = Depends(require_csrf),
):
    if agent_id not in KNOWN_AGENTS:
        raise HTTPException(status_code=400, detail=f'Unbekannter Agent: {agent_id}')

    # Reject writes to planned agents
    catalog_status = AGENT_CATALOG.get(agent_id, {}).get('agent_status', 'active')
    if catalog_status == 'planned':
        raise HTTPException(
            status_code=400,
            detail=f'Agent "{agent_id}" ist noch nicht implementiert (Status: planned)',
        )

    body = await request.json()
    provider = body.get('provider', '').strip()
    model = body.get('model', '').strip()
    api_key = body.get('api_key', '').strip() or None
    base_url = body.get('base_url', '').strip() or None

    if not provider or not model:
        raise HTTPException(status_code=422, detail='Provider und Modell sind Pflichtfelder')

    repo: LLMConfigRepository = get_llm_config_repository()
    record = await repo.upsert_config(
        agent_id=agent_id,
        provider=provider,
        model=model,
        api_key=api_key,
        base_url=base_url,
    )

    return {
        'status': 'ok',
        'agent_id': record['agent_id'],
        'provider': record['provider'],
        'model': record['model'],
        'api_key_set': bool(record.get('api_key_encrypted')),
        'base_url': record.get('base_url'),
    }


@router.post('/api/agent-config/{agent_id}/check')
async def health_check(
    agent_id: str,
    _admin: AuthUser = Depends(require_admin),
    _csrf: None = Depends(require_csrf),
):
    if agent_id not in KNOWN_AGENTS:
        raise HTTPException(status_code=400, detail=f'Unbekannter Agent: {agent_id}')

    # Reject health checks for planned agents
    catalog_status = AGENT_CATALOG.get(agent_id, {}).get('agent_status', 'active')
    if catalog_status == 'planned':
        raise HTTPException(
            status_code=400,
            detail=f'Agent "{agent_id}" ist noch nicht implementiert (Status: planned)',
        )

    repo: LLMConfigRepository = get_llm_config_repository()
    config = await repo.get_config(agent_id)

    if config is None:
        raise HTTPException(status_code=404, detail='Keine Konfiguration fuer diesen Agent')

    model_id = config.get('model', '')
    provider = config.get('provider', '')
    base_url = config.get('base_url') or None
    api_key = repo.decrypt_key_for_call(config)

    # IONOS AI Hub uses OpenAI-compatible API — always use openai/ prefix
    if provider == 'ionos':
        litellm_model = f'openai/{model_id}'
    elif provider and '/' not in model_id:
        litellm_model = f'{provider}/{model_id}'
    else:
        litellm_model = model_id

    kwargs: dict = {
        'model': litellm_model,
        'messages': [{'role': 'user', 'content': 'ping'}],
        'max_tokens': 5,
        'timeout': 20.0,
    }
    if api_key:
        kwargs['api_key'] = api_key
    if base_url:
        kwargs['api_base'] = base_url

    try:
        resp = await acompletion(**kwargs)
        status = f'ok — {resp.model}'
    except Exception as exc:
        status = f'error — {type(exc).__name__}: {str(exc)[:200]}'
        logger.warning('Health check failed for %s: %s', agent_id, status)

    await repo.update_health_status(agent_id, status)

    return {
        'status': status,
        'agent_id': agent_id,
    }
