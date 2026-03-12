from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse

from app.auth.csrf import require_csrf
from app.auth.dependencies import require_admin, require_operator
from app.auth.models import AuthUser
from app.dependencies import get_problem_case_service
from app.problems.service import ProblemCaseService

router = APIRouter(prefix='/inspect/problem-cases', tags=['inspect'], dependencies=[Depends(require_operator)])


@router.get('', response_class=HTMLResponse)
async def problem_cases_view(service: ProblemCaseService = Depends(get_problem_case_service)) -> str:
    cases = await service.recent(limit=200)
    rows = ''.join(
        f"<tr><td>{c.created_at}</td><td>{c.case_id}</td><td>{c.severity}</td><td>{c.title}</td><td>{c.exception_type or ''}</td></tr>"
        for c in cases
    )
    return (
        '<h1>Problemfaelle</h1>'
        '<table border="1" cellpadding="6"><tr><th>Zeit</th><th>Case</th><th>Severity</th><th>Titel</th><th>Exception</th></tr>'
        f'{rows}</table>'
    )


@router.get('/json')
async def problem_cases_json(service: ProblemCaseService = Depends(get_problem_case_service)) -> list[dict]:
    cases = await service.recent(limit=200)
    return [c.model_dump() for c in cases]


@router.post('', dependencies=[Depends(require_csrf)])
async def create_problem_case(
    payload: dict,
    service: ProblemCaseService = Depends(get_problem_case_service),
    current_user: AuthUser = Depends(require_admin),
) -> dict:
    created = await service.add_case(
        case_id=payload['case_id'],
        title=payload['title'],
        details=payload['details'],
        severity=payload.get('severity', 'MEDIUM'),
        exception_type=payload.get('exception_type'),
        document_ref=payload.get('document_ref'),
        accounting_ref=payload.get('accounting_ref'),
        created_by=current_user.username,
    )
    return {'status': 'ok', 'problem_id': created.problem_id}
