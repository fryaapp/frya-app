from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.status import HTTP_303_SEE_OTHER

from app.api.agent_config import router as agent_config_router
from app.api.cases import router as case_engine_router
from app.api.communicator_send import router as communicator_send_router
from app.api.deadlines import router as deadlines_router
from app.api.n8n_endpoints import router as n8n_router
from app.api.risks import router as risks_router
from app.api.memory import router as memory_router
from app.api.email_intake_views import router as email_intake_router
from app.api.user_views import router as user_router
from app.api.tenant_views import router as tenant_router
from app.api.gdpr_views import router as gdpr_router
from app.api.preferences_views import router as preferences_router
from app.api.feedback_views import router as feedback_router
from app.api.dunning_views import router as dunning_router
from app.api.export_views import router as export_router
from app.api.approval_views import router as approval_router
from app.api.booking_approval import router as booking_approval_router
from app.api.audit_views import router as audit_router
from app.api.case_views import router as case_router
from app.api.health import router as health_router
from app.api.open_items_views import router as open_items_router
from app.api.problem_views import router as problem_router
from app.api.proposal_views import router as proposal_router
from app.api.rules_views import router as rules_router
from app.api.verfahrensdoku_views import router as verfahrensdoku_router
from app.api.e_invoice_views import router as e_invoice_router
from app.api.backfill_views import router as backfill_router
from app.api.bulk_upload import router as bulk_upload_router
from app.api.accounting_api import router as accounting_router
from app.api.greeting_views import router as greeting_router
from app.api.template_views import router as template_router
from app.api.finance_views import router as finance_router
from app.api.auth_views import router as auth_views_router
from app.api.customer_api import router as customer_router
from app.api.pdf_views import router as pdf_router
from app.api.webhooks import router as webhooks_router
from app.api.ws import router as ws_router
from app.api.chat_ws import router as chat_ws_router
from app.api.activity_views import router as activity_router
from app.api.admin_views import router as admin_router
from app.approvals.service import ApprovalService
from app.audit.service import AuditService
from app.auth.csrf import require_csrf
from app.auth.dependencies import require_admin
from app.auth.models import AuthUser
from app.auth.router import router as auth_router
from app.auth.totp_router import router as totp_router
from app.config import get_settings
from app.dependencies import (
    get_approval_service,
    get_audit_service,
    get_case_repository,
    get_email_intake_repository,
    get_llm_config_repository,
    get_open_items_service,
    get_policy_access_layer,
    get_problem_case_service,
    get_rule_change_audit_service,
    get_telegram_case_link_service,
    get_telegram_clarification_service,
    get_user_repository,
    get_tenant_repository,
)
from app.open_items.service import OpenItemsService
from app.orchestration.graph import build_graph
from app.problems.service import ProblemCaseService
from app.rules.audit_service import RuleChangeAuditService
from app.rules.policy_access import REQUIRED_POLICY_ROLES
from app.ui.router import router as ui_router

_logger = logging.getLogger(__name__)

AUTH_TEMPLATES = Jinja2Templates(directory=str(Path(__file__).resolve().parent / 'ui' / 'templates'))


class _SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add defensive HTTP security headers to every response."""

    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers.setdefault('X-Frame-Options', 'DENY')
        response.headers.setdefault('X-Content-Type-Options', 'nosniff')
        response.headers.setdefault('X-XSS-Protection', '1; mode=block')
        response.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
        response.headers.setdefault(
            'Strict-Transport-Security',
            'max-age=31536000; includeSubDomains',
        )
        return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    # P-12b: Initialize global connection pool
    from app.dependencies import init_db_pool, close_db_pool
    await init_db_pool()

    # P-19: Token-Tracking Callback installieren
    from app.token_tracking import install_litellm_callback
    install_litellm_callback()

    audit_service: AuditService = get_audit_service()
    open_items_service: OpenItemsService = get_open_items_service()
    problem_service: ProblemCaseService = get_problem_case_service()
    rule_change_service: RuleChangeAuditService = get_rule_change_audit_service()
    approval_service: ApprovalService = get_approval_service()
    telegram_case_link_service = get_telegram_case_link_service()
    telegram_clarification_service = get_telegram_clarification_service()

    await audit_service.initialize()
    await open_items_service.initialize()
    await problem_service.initialize()
    await rule_change_service.initialize()
    await approval_service.initialize()
    await telegram_case_link_service.initialize()
    await telegram_clarification_service.initialize()

    email_intake_repo = get_email_intake_repository()
    await email_intake_repo.initialize()

    case_repo = get_case_repository()
    await case_repo.initialize()

    user_repo = get_user_repository()
    await user_repo.initialize()

    # ── Bootstrap admin ───────────────────────────────────────────────────────
    # If FRYA_INITIAL_ADMIN_USERNAME + FRYA_INITIAL_ADMIN_PASSWORD are set and
    # the user does not yet exist in the DB, create it now.  Idempotent: the
    # existing row is never touched on subsequent restarts.
    _boot_settings = get_settings()
    _boot_username = _boot_settings.initial_admin_username
    _boot_password = _boot_settings.initial_admin_password
    if _boot_username and _boot_password:
        _existing_admin = await user_repo.find_by_username(_boot_username)
        if _existing_admin is None:
            from app.auth.service import hash_password_pbkdf2
            from app.auth.user_repository import UserRecord as _UserRecord
            await user_repo.create_user(_UserRecord(
                username=_boot_username,
                email=_boot_settings.initial_admin_email,
                role='admin',
                password_hash=hash_password_pbkdf2(_boot_password),
                is_active=True,
            ))
            await audit_service.log_event({
                'event_id': str(uuid.uuid4()),
                'case_id': 'system-bootstrap',
                'source': 'system',
                'agent_name': 'frya-bootstrap',
                'approval_status': 'NOT_REQUIRED',
                'action': 'ADMIN_BOOTSTRAP_CREATED',
                'result': _boot_username,
                'llm_output': {'username': _boot_username},
            })

    # P-31: Firebase Admin SDK + Push-Token-Tabelle
    try:
        from app.services.push_service import init_firebase, ensure_push_tokens_table
        init_firebase()
        await ensure_push_tokens_table()
    except Exception as _push_exc:
        _logger.warning('Firebase/Push init failed (non-fatal): %s', _push_exc)

    tenant_repo = get_tenant_repository()
    await tenant_repo.initialize()

    llm_config_repo = get_llm_config_repository()
    await llm_config_repo.setup()

    # AVV document storage
    try:
        from app.legal.avv_repository import AvvRepository
        _avv_repo = AvvRepository(_boot_settings.database_url, _boot_settings.data_dir)
        await _avv_repo.initialize()
    except Exception as _avv_exc:
        _logger.warning('AVV repository init failed: %s', _avv_exc)

    # Accounting tables + SKR03
    try:
        from app.accounting.repository import AccountingRepository
        _acct_repo = AccountingRepository(_boot_settings.database_url)
        await _acct_repo.initialize()
        # Seed SKR03 for default tenant
        from app.case_engine.tenant_resolver import resolve_tenant_id as _resolve_acct_tid
        _acct_tid = await _resolve_acct_tid()
        if _acct_tid:
            import uuid as _uuid_acct
            count = await _acct_repo.seed_skr03(_uuid_acct.UUID(_acct_tid))
            if count:
                _logger.info('SKR03 seeded: %d accounts', count)
    except Exception as exc:
        _logger.warning('Accounting init failed: %s', exc)

    app.state.graph = build_graph()

    policy_access = get_policy_access_layer()
    ok, missing = policy_access.required_policies_loaded()
    startup_policy_refs = policy_access.get_policy_refs(list(REQUIRED_POLICY_ROLES))

    await audit_service.log_event(
        {
            'event_id': str(uuid.uuid4()),
            'case_id': 'system-startup',
            'source': 'system',
            'agent_name': 'frya-bootstrap',
            'approval_status': 'NOT_REQUIRED',
            'action': 'SYSTEM_STARTUP',
            'result': 'Agent backend initialized',
            'policy_refs': startup_policy_refs,
        }
    )

    await audit_service.log_event(
        {
            'event_id': str(uuid.uuid4()),
            'case_id': 'system-policies',
            'source': 'system',
            'agent_name': 'frya-bootstrap',
            'approval_status': 'NOT_REQUIRED',
            'action': 'POLICY_LOAD_STATUS',
            'result': 'all_required_loaded' if ok else f'missing_required={missing}',
            'policy_refs': startup_policy_refs,
        }
    )

    yield

    # P-12b: Close global connection pool on shutdown
    await close_db_pool()


app = FastAPI(title='FRYA Agent Backend', version='0.3.0', lifespan=lifespan)
settings = get_settings()

# P-30: CORS for Capacitor mobile app (Android: https://localhost, iOS: capacitor://localhost)
_CORS_ORIGINS = [
    'https://localhost',        # Capacitor Android WebView
    'capacitor://localhost',    # Capacitor iOS
    'http://localhost',
    'https://app.myfrya.de',
    'https://www.myfrya.de',
    'https://staging.myfrya.de',
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.auth_session_secret,
    session_cookie=settings.auth_session_cookie_name,
    max_age=settings.auth_session_max_age_seconds,
    same_site=settings.auth_cookie_samesite,
    https_only=settings.auth_cookie_secure,
    domain=settings.auth_cookie_domain,
)
app.add_middleware(_SecurityHeadersMiddleware)


@app.exception_handler(HTTPException)
async def auth_exception_handler(request: Request, exc: HTTPException):
    if exc.status_code == 401:
        if request.url.path.startswith('/ui'):
            next_target = request.url.path
            if request.url.query:
                next_target = f'{next_target}?{request.url.query}'
            encoded_next = quote(next_target, safe='')
            return RedirectResponse(url=f'/auth/login?next={encoded_next}', status_code=HTTP_303_SEE_OTHER)
        return JSONResponse(status_code=401, content={'detail': 'not_authenticated'})

    if exc.status_code == 403:
        if request.url.path.startswith('/ui'):
            return AUTH_TEMPLATES.TemplateResponse(
                request,
                '403.html',
                {
                    'request': request,
                    'title': 'Forbidden',
                    'message': 'Keine Berechtigung fuer diese Aktion.',
                },
                status_code=403,
            )
        return JSONResponse(status_code=403, content={'detail': 'forbidden'})

    return await http_exception_handler(request, exc)


ui_static_dir = Path(__file__).resolve().parent / 'ui' / 'static'
app.mount('/ui/static', StaticFiles(directory=str(ui_static_dir)), name='ui_static')

@app.get('/')
async def root():
    return RedirectResponse(url='/ui/dashboard', status_code=HTTP_303_SEE_OTHER)


app.include_router(health_router)
app.include_router(auth_router)
app.include_router(totp_router)
app.include_router(webhooks_router)
app.include_router(ws_router)
app.include_router(chat_ws_router)
app.include_router(audit_router)
app.include_router(case_router)
app.include_router(open_items_router)
app.include_router(problem_router)
app.include_router(proposal_router)
app.include_router(rules_router)
app.include_router(approval_router)
app.include_router(booking_approval_router)
app.include_router(verfahrensdoku_router)
app.include_router(e_invoice_router)
app.include_router(backfill_router)
app.include_router(bulk_upload_router)
app.include_router(agent_config_router)
app.include_router(case_engine_router)
app.include_router(deadlines_router)
app.include_router(n8n_router)
app.include_router(communicator_send_router)
app.include_router(risks_router)
app.include_router(memory_router)
app.include_router(email_intake_router)
app.include_router(user_router)
app.include_router(tenant_router)
app.include_router(gdpr_router)
app.include_router(preferences_router)
app.include_router(feedback_router)
app.include_router(dunning_router)
app.include_router(export_router)
app.include_router(customer_router)
app.include_router(auth_views_router)
app.include_router(accounting_router)
app.include_router(greeting_router)
app.include_router(template_router)
app.include_router(finance_router)
app.include_router(activity_router)
app.include_router(pdf_router)
app.include_router(admin_router)
app.include_router(ui_router)


@app.post('/agent/run')
async def run_agent_case(
    payload: dict,
    _admin: AuthUser = Depends(require_admin),
    _csrf: None = Depends(require_csrf),
):
    graph = app.state.graph
    audit_service: AuditService = get_audit_service()
    approval_service: ApprovalService = get_approval_service()

    case_id = payload.get('case_id', str(uuid.uuid4()))

    approved = bool(payload.get('approved', False))
    approval_id = payload.get('approval_id')
    approval_decision = payload.get('approval_decision')

    if approved and not approval_id:
        approved = False

    if approval_id and approval_decision:
        try:
            decided = await approval_service.decide_approval(
                approval_id=approval_id,
                decision=str(approval_decision),
                decided_by=str(payload.get('decided_by', 'api-user')),
                reason=payload.get('decision_reason'),
                source='agent_run',
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if decided is None:
            raise HTTPException(status_code=404, detail='Approval nicht gefunden')
        approved = decided.status == 'APPROVED'
        approval_id = decided.approval_id

    state = {
        'case_id': case_id,
        'source': payload.get('source', 'api'),
        'tenant_id': payload.get('tenant_id') or None,
        'message': payload.get('message', payload.get('ocr_text', '')),
        'document_ref': payload.get('document_ref'),
        'paperless_metadata': payload.get('paperless_metadata') or {},
        'ocr_text': payload.get('ocr_text'),
        'preview_text': payload.get('preview_text'),
        'approved': approved,
        'approval_id': approval_id,
    }
    result = await graph.ainvoke(state)

    output = result.get('output', {}) if isinstance(result, dict) else {}
    policy_refs = output.get('policy_refs', []) if isinstance(output, dict) else []
    status_value = str(output.get('status', 'UNKNOWN'))
    decision_mode = str(output.get('approval_mode', 'UNKNOWN'))
    action_key = str(output.get('action_key', 'unknown_action'))
    gate_reason = str(output.get('policy_gate_reason', ''))
    approval_id = str(output.get('approval_id') or approval_id or '')

    approval_status = 'NOT_REQUIRED'
    if status_value == 'WAITING_APPROVAL':
        approval_status = 'PENDING'
    elif decision_mode == 'BLOCK_ESCALATE':
        approval_status = 'REJECTED'
    elif approved or status_value == 'READY_FOR_DETERMINISTIC_EXECUTION':
        approval_status = 'APPROVED'

    await audit_service.log_event(
        {
            'event_id': str(uuid.uuid4()),
            'case_id': case_id,
            'source': state.get('source', 'api'),
            'agent_name': 'frya-orchestrator',
            'approval_status': approval_status,
            'workflow_name': 'n8n' if output.get('deterministic_rule_path') else None,
            'action': 'APPROVAL_GATE_DECISION',
            'result': f'mode={decision_mode};action={action_key};status={status_value};approval_id={approval_id or "-"};reason={gate_reason}',
            'llm_output': {
                'status': status_value,
                'approval_mode': decision_mode,
                'action_key': action_key,
                'approval_id': approval_id or None,
                'execution_allowed': output.get('execution_allowed', False),
            },
            'policy_refs': policy_refs,
        }
    )

    await audit_service.log_event(
        {
            'event_id': str(uuid.uuid4()),
            'case_id': case_id,
            'source': state.get('source', 'api'),
            'agent_name': 'frya-orchestrator',
            'approval_status': approval_status,
            'workflow_name': 'n8n' if output.get('deterministic_rule_path') else None,
            'action': 'AGENT_RUN_COMPLETED',
            'result': status_value,
            'llm_output': output,
            'policy_refs': policy_refs,
        }
    )

    return {'status': 'ok', 'case_id': case_id, 'result': result}


