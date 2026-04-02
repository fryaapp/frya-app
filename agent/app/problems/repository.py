from __future__ import annotations

import json
from collections.abc import Sequence

import asyncpg

from app.problems.models import ProblemCase


class ProblemCaseRepository:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self._memory: list[ProblemCase] = []

    @property
    def is_memory(self) -> bool:
        return self.database_url.startswith('memory://')

    async def setup(self) -> None:
        if self.is_memory:
            return
        conn = await asyncpg.connect(self.database_url)
        try:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS frya_problem_cases (
                    id BIGSERIAL PRIMARY KEY,
                    problem_id TEXT UNIQUE NOT NULL,
                    case_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    details TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    exception_type TEXT,
                    document_ref TEXT,
                    accounting_ref TEXT,
                    created_by TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_frya_problem_case_id ON frya_problem_cases(case_id)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_frya_problem_created_at ON frya_problem_cases(created_at)")
            await conn.execute("ALTER TABLE frya_problem_cases ADD COLUMN IF NOT EXISTS tenant_id TEXT")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_problem_cases_tenant ON frya_problem_cases(tenant_id)")
        finally:
            await conn.close()

    async def append(self, problem: ProblemCase) -> None:
        if self.is_memory:
            self._memory.append(problem)
            return

        conn = await asyncpg.connect(self.database_url)
        try:
            await conn.execute(
                """
                INSERT INTO frya_problem_cases (
                    problem_id, case_id, title, details, severity, exception_type,
                    document_ref, accounting_ref, created_by, created_at
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
                ON CONFLICT (problem_id)
                DO NOTHING
                """,
                problem.problem_id,
                problem.case_id,
                problem.title,
                problem.details,
                problem.severity,
                problem.exception_type,
                problem.document_ref,
                problem.accounting_ref,
                problem.created_by,
                problem.created_at,
            )
        finally:
            await conn.close()

    async def list_recent(self, limit: int = 200) -> Sequence[ProblemCase]:
        if self.is_memory:
            return list(reversed(self._memory[-limit:]))

        conn = await asyncpg.connect(self.database_url)
        try:
            rows = await conn.fetch('SELECT * FROM frya_problem_cases ORDER BY created_at DESC LIMIT $1', limit)
            return [ProblemCase(**json.loads(json.dumps(dict(r), default=str))) for r in rows]
        finally:
            await conn.close()

    async def list_by_case(self, case_id: str, limit: int = 200) -> Sequence[ProblemCase]:
        if self.is_memory:
            filtered = [x for x in self._memory if x.case_id == case_id]
            return sorted(filtered, key=lambda x: x.created_at, reverse=True)[:limit]

        conn = await asyncpg.connect(self.database_url)
        try:
            rows = await conn.fetch(
                'SELECT * FROM frya_problem_cases WHERE case_id = $1 ORDER BY created_at DESC LIMIT $2',
                case_id,
                limit,
            )
            return [ProblemCase(**json.loads(json.dumps(dict(r), default=str))) for r in rows]
        finally:
            await conn.close()
