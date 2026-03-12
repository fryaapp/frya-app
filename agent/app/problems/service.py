from __future__ import annotations

import uuid

from app.problems.models import ProblemCase
from app.problems.repository import ProblemCaseRepository


class ProblemCaseService:
    def __init__(self, repository: ProblemCaseRepository) -> None:
        self.repository = repository

    async def initialize(self) -> None:
        await self.repository.setup()

    async def add_case(
        self,
        case_id: str,
        title: str,
        details: str,
        severity: str = 'MEDIUM',
        exception_type: str | None = None,
        document_ref: str | None = None,
        accounting_ref: str | None = None,
        created_by: str = 'agent',
    ) -> ProblemCase:
        problem = ProblemCase(
            problem_id=str(uuid.uuid4()),
            case_id=case_id,
            title=title,
            details=details,
            severity=severity,
            exception_type=exception_type,
            document_ref=document_ref,
            accounting_ref=accounting_ref,
            created_by=created_by,
        )
        await self.repository.append(problem)
        return problem

    async def recent(self, limit: int = 200) -> list[ProblemCase]:
        return list(await self.repository.list_recent(limit=limit))

    async def by_case(self, case_id: str, limit: int = 200) -> list[ProblemCase]:
        return list(await self.repository.list_by_case(case_id=case_id, limit=limit))
