"""CaseRepository — dual-mode (memory / PostgreSQL) CRUD for the CaseEngine."""
from __future__ import annotations

import json
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from app.case_engine.models import (
    CaseConflictRecord,
    CaseDocumentRecord,
    CaseReferenceRecord,
    CaseRecord,
)
from app.case_engine.status import StatusTransitionError, check_transition

# ── DDL ────────────────────────────────────────────────────────────────────────

_DDL = """
CREATE TABLE IF NOT EXISTS case_cases (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    case_number VARCHAR(50) UNIQUE,
    title VARCHAR(500),
    case_type VARCHAR(50) NOT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'DRAFT',
    vendor_name VARCHAR(500),
    total_amount NUMERIC(12,2),
    currency VARCHAR(3) NOT NULL DEFAULT 'EUR',
    due_date DATE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by VARCHAR(100),
    merged_into_case_id UUID REFERENCES case_cases(id),
    metadata JSONB NOT NULL DEFAULT '{}',
    CONSTRAINT case_cases_status_check
        CHECK (status IN ('DRAFT','OPEN','OVERDUE','PAID','CLOSED','DISCARDED','MERGED'))
);
CREATE INDEX IF NOT EXISTS idx_case_cases_tenant_status ON case_cases(tenant_id, status);

CREATE TABLE IF NOT EXISTS case_documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id UUID NOT NULL REFERENCES case_cases(id),
    document_source VARCHAR(30) NOT NULL,
    document_source_id VARCHAR(200) NOT NULL,
    document_type VARCHAR(50),
    assignment_confidence VARCHAR(20) NOT NULL,
    assignment_method VARCHAR(50) NOT NULL,
    assigned_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    assigned_by VARCHAR(100),
    filename VARCHAR(500),
    metadata JSONB NOT NULL DEFAULT '{}',
    CONSTRAINT case_documents_unique UNIQUE (case_id, document_source, document_source_id)
);
CREATE INDEX IF NOT EXISTS idx_case_documents_case_id ON case_documents(case_id);

CREATE TABLE IF NOT EXISTS case_references (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id UUID NOT NULL REFERENCES case_cases(id),
    reference_type VARCHAR(50) NOT NULL,
    reference_value VARCHAR(500) NOT NULL,
    extracted_from_document_id UUID REFERENCES case_documents(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_case_references_lookup ON case_references(reference_type, reference_value);
CREATE INDEX IF NOT EXISTS idx_case_references_case_id ON case_references(case_id);

CREATE TABLE IF NOT EXISTS case_conflicts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id UUID NOT NULL REFERENCES case_cases(id),
    conflict_type VARCHAR(50) NOT NULL,
    description TEXT,
    resolution VARCHAR(30),
    resolved_by VARCHAR(100),
    resolved_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata JSONB NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_case_conflicts_case_id ON case_conflicts(case_id);
"""


class CaseRepository:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        # memory backend
        self._cases: dict[uuid.UUID, CaseRecord] = {}
        self._documents: dict[uuid.UUID, CaseDocumentRecord] = {}
        self._references: dict[uuid.UUID, CaseReferenceRecord] = {}
        self._conflicts: dict[uuid.UUID, CaseConflictRecord] = {}
        self._year_seq: dict[int, int] = {}

    @property
    def is_memory(self) -> bool:
        return self.database_url.startswith('memory://')

    # ── lifecycle ─────────────────────────────────────────────────────────────

    async def initialize(self) -> None:
        if self.is_memory:
            return
        import asyncpg
        conn = await asyncpg.connect(self.database_url)
        try:
            await conn.execute(_DDL)
        finally:
            await conn.close()

    # ── case_number generation ─────────────────────────────────────────────────

    def _next_case_number_memory(self, year: int) -> str:
        self._year_seq[year] = self._year_seq.get(year, 0) + 1
        return f'CASE-{year}-{self._year_seq[year]:05d}'

    async def _next_case_number_pg(self, conn: Any, year: int) -> str:
        row = await conn.fetchrow(
            "SELECT COUNT(*) AS cnt FROM case_cases WHERE case_number LIKE $1",
            f'CASE-{year}-%',
        )
        num = (row['cnt'] or 0) + 1
        return f'CASE-{year}-{num:05d}'

    # ── create / get / list cases ──────────────────────────────────────────────

    async def create_case(
        self,
        *,
        tenant_id: uuid.UUID,
        case_type: str,
        title: str | None = None,
        vendor_name: str | None = None,
        total_amount: Decimal | None = None,
        currency: str = 'EUR',
        due_date: date | None = None,
        created_by: str | None = None,
        metadata: dict | None = None,
    ) -> CaseRecord:
        year = datetime.utcnow().year
        now = datetime.utcnow()
        meta = metadata or {}

        if self.is_memory:
            case_number = self._next_case_number_memory(year)
            record = CaseRecord(
                tenant_id=tenant_id,
                case_number=case_number,
                case_type=case_type,  # type: ignore[arg-type]
                title=title,
                vendor_name=vendor_name,
                total_amount=total_amount,
                currency=currency,
                due_date=due_date,
                created_by=created_by,
                metadata=meta,
                created_at=now,
                updated_at=now,
            )
            self._cases[record.id] = record
            return record

        import asyncpg
        conn = await asyncpg.connect(self.database_url)
        try:
            async with conn.transaction():
                case_number = await self._next_case_number_pg(conn, year)
                row_id = uuid.uuid4()
                await conn.execute(
                    """
                    INSERT INTO case_cases
                    (id, tenant_id, case_number, title, case_type, status,
                     vendor_name, total_amount, currency, due_date,
                     created_at, updated_at, created_by, metadata)
                    VALUES ($1,$2,$3,$4,$5,'DRAFT',$6,$7,$8,$9,$10,$11,$12,$13)
                    """,
                    row_id, tenant_id, case_number, title, case_type,
                    vendor_name, total_amount, currency, due_date,
                    now, now, created_by, json.dumps(meta),
                )
        finally:
            await conn.close()
        result = await self.get_case(row_id)
        assert result is not None
        return result

    async def get_case(self, case_id: uuid.UUID) -> CaseRecord | None:
        if self.is_memory:
            return self._cases.get(case_id)
        import asyncpg
        conn = await asyncpg.connect(self.database_url)
        try:
            row = await conn.fetchrow("SELECT * FROM case_cases WHERE id=$1", case_id)
        finally:
            await conn.close()
        return self._row_to_case(dict(row)) if row else None

    async def list_cases(
        self,
        tenant_id: uuid.UUID,
        *,
        status: str | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> list[CaseRecord]:
        if self.is_memory:
            items = [
                c for c in self._cases.values()
                if c.tenant_id == tenant_id
                and (status is None or c.status == status)
            ]
            items.sort(key=lambda c: c.created_at, reverse=True)
            return items[offset: offset + limit]

        import asyncpg
        conn = await asyncpg.connect(self.database_url)
        try:
            if status:
                rows = await conn.fetch(
                    "SELECT * FROM case_cases WHERE tenant_id=$1 AND status=$2 "
                    "ORDER BY created_at DESC LIMIT $3 OFFSET $4",
                    tenant_id, status, limit, offset,
                )
            else:
                rows = await conn.fetch(
                    "SELECT * FROM case_cases WHERE tenant_id=$1 "
                    "ORDER BY created_at DESC LIMIT $2 OFFSET $3",
                    tenant_id, limit, offset,
                )
        finally:
            await conn.close()
        return [self._row_to_case(dict(r)) for r in rows]

    # ── metadata ──────────────────────────────────────────────────────────────

    async def update_metadata(self, case_id: uuid.UUID, metadata_update: dict) -> 'CaseRecord':
        """Merge *metadata_update* into the case's existing metadata dict."""
        case = await self.get_case(case_id)
        if case is None:
            raise ValueError(f'Case {case_id} not found.')
        merged = {**case.metadata, **metadata_update}
        now = datetime.utcnow()

        if self.is_memory:
            updated = case.model_copy(update={'metadata': merged, 'updated_at': now})
            self._cases[case_id] = updated
            return updated

        import asyncpg
        conn = await asyncpg.connect(self.database_url)
        try:
            await conn.execute(
                'UPDATE case_cases SET metadata=$1, updated_at=$2 WHERE id=$3 AND tenant_id=$4',
                json.dumps(merged), now, case_id, case.tenant_id,
            )
        finally:
            await conn.close()
        result = await self.get_case(case_id)
        assert result is not None
        return result

    # ── status transitions ─────────────────────────────────────────────────────

    async def update_case_status(
        self,
        case_id: uuid.UUID,
        new_status: str,
        *,
        operator: bool = False,
    ) -> CaseRecord:
        case = await self.get_case(case_id)
        if case is None:
            raise ValueError(f'Case {case_id} not found.')

        check_transition(case.status, new_status, operator=operator)

        # Extra constraint: DRAFT → OPEN requires at least one document
        if case.status == 'DRAFT' and new_status == 'OPEN':
            docs = await self.get_case_documents(case_id)
            if not docs:
                raise StatusTransitionError(
                    'Cannot open a case with no documents (DRAFT → OPEN requires ≥1 document).'
                )

        now = datetime.utcnow()

        if self.is_memory:
            updated = case.model_copy(update={'status': new_status, 'updated_at': now})
            self._cases[case_id] = updated
            return updated

        import asyncpg
        conn = await asyncpg.connect(self.database_url)
        try:
            await conn.execute(
                "UPDATE case_cases SET status=$1, updated_at=$2 WHERE id=$3 AND tenant_id=$4",
                new_status, now, case_id, case.tenant_id,
            )
        finally:
            await conn.close()
        result = await self.get_case(case_id)
        assert result is not None
        return result

    # ── documents ─────────────────────────────────────────────────────────────

    async def add_document_to_case(
        self,
        *,
        case_id: uuid.UUID,
        document_source: str,
        document_source_id: str,
        assignment_confidence: str,
        assignment_method: str,
        document_type: str | None = None,
        assigned_by: str | None = None,
        filename: str | None = None,
        metadata: dict | None = None,
    ) -> CaseDocumentRecord:
        now = datetime.utcnow()
        meta = metadata or {}

        if self.is_memory:
            record = CaseDocumentRecord(
                case_id=case_id,
                document_source=document_source,  # type: ignore[arg-type]
                document_source_id=document_source_id,
                document_type=document_type,
                assignment_confidence=assignment_confidence,  # type: ignore[arg-type]
                assignment_method=assignment_method,  # type: ignore[arg-type]
                assigned_at=now,
                assigned_by=assigned_by,
                filename=filename,
                metadata=meta,
            )
            self._documents[record.id] = record
            return record

        import asyncpg
        conn = await asyncpg.connect(self.database_url)
        try:
            row_id = uuid.uuid4()
            await conn.execute(
                """
                INSERT INTO case_documents
                (id, case_id, document_source, document_source_id, document_type,
                 assignment_confidence, assignment_method, assigned_at, assigned_by,
                 filename, metadata)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
                ON CONFLICT ON CONSTRAINT case_documents_unique DO NOTHING
                """,
                row_id, case_id, document_source, document_source_id, document_type,
                assignment_confidence, assignment_method, now, assigned_by,
                filename, json.dumps(meta),
            )
        finally:
            await conn.close()
        # Fetch the actual record (may have been inserted or already existed)
        doc = await self._get_document_by_source(case_id, document_source, document_source_id)
        if doc is None:
            # Fallback: return a transient record (conflict case)
            return CaseDocumentRecord(
                id=row_id,
                case_id=case_id,
                document_source=document_source,  # type: ignore[arg-type]
                document_source_id=document_source_id,
                assignment_confidence=assignment_confidence,  # type: ignore[arg-type]
                assignment_method=assignment_method,  # type: ignore[arg-type]
            )
        return doc

    async def _get_document_by_source(
        self,
        case_id: uuid.UUID,
        source: str,
        source_id: str,
    ) -> CaseDocumentRecord | None:
        if self.is_memory:
            for doc in self._documents.values():
                if (
                    doc.case_id == case_id
                    and doc.document_source == source
                    and doc.document_source_id == source_id
                ):
                    return doc
            return None
        import asyncpg
        conn = await asyncpg.connect(self.database_url)
        try:
            row = await conn.fetchrow(
                "SELECT * FROM case_documents "
                "WHERE case_id=$1 AND document_source=$2 AND document_source_id=$3",
                case_id, source, source_id,
            )
        finally:
            await conn.close()
        return self._row_to_doc(dict(row)) if row else None

    async def get_case_documents(self, case_id: uuid.UUID) -> list[CaseDocumentRecord]:
        if self.is_memory:
            return [d for d in self._documents.values() if d.case_id == case_id]
        import asyncpg
        conn = await asyncpg.connect(self.database_url)
        try:
            rows = await conn.fetch(
                "SELECT * FROM case_documents WHERE case_id=$1 ORDER BY assigned_at",
                case_id,
            )
        finally:
            await conn.close()
        return [self._row_to_doc(dict(r)) for r in rows]

    # ── references ────────────────────────────────────────────────────────────

    async def get_case_references(self, case_id: uuid.UUID) -> list[CaseReferenceRecord]:
        if self.is_memory:
            return [r for r in self._references.values() if r.case_id == case_id]
        import asyncpg
        conn = await asyncpg.connect(self.database_url)
        try:
            rows = await conn.fetch(
                "SELECT * FROM case_references WHERE case_id=$1 ORDER BY created_at",
                case_id,
            )
        finally:
            await conn.close()
        return [
            CaseReferenceRecord(
                id=r['id'],
                case_id=r['case_id'],
                reference_type=r['reference_type'],
                reference_value=r['reference_value'],
                extracted_from_document_id=r.get('extracted_from_document_id'),
                created_at=r['created_at'],
            )
            for r in rows
        ]

    async def add_reference(
        self,
        *,
        case_id: uuid.UUID,
        reference_type: str,
        reference_value: str,
        extracted_from_document_id: uuid.UUID | None = None,
    ) -> CaseReferenceRecord:
        now = datetime.utcnow()

        if self.is_memory:
            # Dedup: skip if this (case_id, reference_type, reference_value) already exists
            for existing in self._references.values():
                if (
                    existing.case_id == case_id
                    and existing.reference_type == reference_type
                    and existing.reference_value == reference_value
                ):
                    return existing
            record = CaseReferenceRecord(
                case_id=case_id,
                reference_type=reference_type,
                reference_value=reference_value,
                extracted_from_document_id=extracted_from_document_id,
                created_at=now,
            )
            self._references[record.id] = record
            return record

        import asyncpg
        conn = await asyncpg.connect(self.database_url)
        try:
            row_id = uuid.uuid4()
            await conn.execute(
                """
                INSERT INTO case_references
                (id, case_id, reference_type, reference_value,
                 extracted_from_document_id, created_at)
                VALUES ($1,$2,$3,$4,$5,$6)
                ON CONFLICT ON CONSTRAINT case_references_unique DO NOTHING
                """,
                row_id, case_id, reference_type, reference_value,
                extracted_from_document_id, now,
            )
        finally:
            await conn.close()
        # Fetch the actual record (may have been inserted or already existed)
        existing_refs = await self.get_case_references(case_id)
        for ref in existing_refs:
            if ref.reference_type == reference_type and ref.reference_value == reference_value:
                return ref
        return CaseReferenceRecord(
            id=row_id,
            case_id=case_id,
            reference_type=reference_type,
            reference_value=reference_value,
            extracted_from_document_id=extracted_from_document_id,
            created_at=now,
        )

    async def find_cases_by_reference(
        self,
        tenant_id: uuid.UUID,
        reference_type: str,
        reference_value: str,
    ) -> list[CaseRecord]:
        """Return all cases (of this tenant) that have a matching reference."""
        if self.is_memory:
            matched_case_ids = {
                ref.case_id
                for ref in self._references.values()
                if ref.reference_type == reference_type
                and ref.reference_value == reference_value
            }
            return [
                c for c in self._cases.values()
                if c.id in matched_case_ids and c.tenant_id == tenant_id
            ]

        import asyncpg
        conn = await asyncpg.connect(self.database_url)
        try:
            rows = await conn.fetch(
                """
                SELECT c.* FROM case_cases c
                JOIN case_references r ON r.case_id = c.id
                WHERE c.tenant_id=$1 AND r.reference_type=$2 AND r.reference_value=$3
                """,
                tenant_id, reference_type, reference_value,
            )
        finally:
            await conn.close()
        return [self._row_to_case(dict(r)) for r in rows]

    async def list_active_cases_for_tenant(
        self, tenant_id: uuid.UUID
    ) -> list[CaseRecord]:
        """Return OPEN and OVERDUE cases for Layer 2 entity matching."""
        if self.is_memory:
            return [
                c for c in self._cases.values()
                if c.tenant_id == tenant_id and c.status in ('OPEN', 'OVERDUE')
            ]
        import asyncpg
        conn = await asyncpg.connect(self.database_url)
        try:
            rows = await conn.fetch(
                "SELECT * FROM case_cases WHERE tenant_id=$1 AND status IN ('OPEN','OVERDUE')",
                tenant_id,
            )
        finally:
            await conn.close()
        return [self._row_to_case(dict(r)) for r in rows]

    async def list_cases_by_status(
        self, tenant_id: uuid.UUID, status: str
    ) -> list[CaseRecord]:
        """Return cases with a specific status for a tenant."""
        if self.is_memory:
            return [
                c for c in self._cases.values()
                if c.tenant_id == tenant_id and c.status == status
            ]
        import asyncpg
        conn = await asyncpg.connect(self.database_url)
        try:
            rows = await conn.fetch(
                "SELECT * FROM case_cases WHERE tenant_id=$1 AND status=$2",
                tenant_id, status,
            )
        finally:
            await conn.close()
        return [self._row_to_case(dict(r)) for r in rows]

    # ── conflicts ─────────────────────────────────────────────────────────────

    async def create_conflict(
        self,
        *,
        case_id: uuid.UUID,
        conflict_type: str,
        description: str | None = None,
        metadata: dict | None = None,
    ) -> CaseConflictRecord:
        now = datetime.utcnow()
        meta = metadata or {}

        if self.is_memory:
            record = CaseConflictRecord(
                case_id=case_id,
                conflict_type=conflict_type,  # type: ignore[arg-type]
                description=description,
                resolution=None,
                created_at=now,
                metadata=meta,
            )
            self._conflicts[record.id] = record
            return record

        import asyncpg
        conn = await asyncpg.connect(self.database_url)
        try:
            row_id = uuid.uuid4()
            await conn.execute(
                """
                INSERT INTO case_conflicts
                (id, case_id, conflict_type, description, created_at, metadata)
                VALUES ($1,$2,$3,$4,$5,$6)
                """,
                row_id, case_id, conflict_type, description, now, json.dumps(meta),
            )
        finally:
            await conn.close()
        return CaseConflictRecord(
            id=row_id,
            case_id=case_id,
            conflict_type=conflict_type,  # type: ignore[arg-type]
            description=description,
            created_at=now,
            metadata=meta,
        )

    async def resolve_conflict(
        self,
        conflict_id: uuid.UUID,
        resolution: str,
        *,
        resolved_by: str | None = None,
    ) -> CaseConflictRecord:
        now = datetime.utcnow()

        if self.is_memory:
            conflict = self._conflicts.get(conflict_id)
            if conflict is None:
                raise ValueError(f'Conflict {conflict_id} not found.')
            updated = conflict.model_copy(update={
                'resolution': resolution,
                'resolved_by': resolved_by,
                'resolved_at': now,
            })
            self._conflicts[conflict_id] = updated
            return updated

        import asyncpg
        conn = await asyncpg.connect(self.database_url)
        try:
            await conn.execute(
                "UPDATE case_conflicts SET resolution=$1, resolved_by=$2, resolved_at=$3 WHERE id=$4",
                resolution, resolved_by, now, conflict_id,
            )
            row = await conn.fetchrow("SELECT * FROM case_conflicts WHERE id=$1", conflict_id)
        finally:
            await conn.close()
        assert row is not None
        return self._row_to_conflict(dict(row))

    async def get_conflicts(self, case_id: uuid.UUID) -> list[CaseConflictRecord]:
        if self.is_memory:
            return [c for c in self._conflicts.values() if c.case_id == case_id]
        import asyncpg
        conn = await asyncpg.connect(self.database_url)
        try:
            rows = await conn.fetch(
                "SELECT * FROM case_conflicts WHERE case_id=$1 ORDER BY created_at",
                case_id,
            )
        finally:
            await conn.close()
        return [self._row_to_conflict(dict(r)) for r in rows]

    # ── merge ─────────────────────────────────────────────────────────────────

    async def merge_cases(
        self,
        source_case_id: uuid.UUID,
        target_case_id: uuid.UUID,
        *,
        operator: bool = False,
    ) -> CaseRecord:
        """Merge *source* into *target*.

        - Validates source can transition to MERGED (requires OPEN status).
        - Moves all documents from source to target (skipping true duplicates).
        - Sets source.status = MERGED and source.merged_into_case_id = target.id.
        - Returns the updated source record.
        """
        source = await self.get_case(source_case_id)
        target = await self.get_case(target_case_id)
        if source is None:
            raise ValueError(f'Source case {source_case_id} not found.')
        if target is None:
            raise ValueError(f'Target case {target_case_id} not found.')

        check_transition(source.status, 'MERGED', operator=operator)

        now = datetime.utcnow()

        if self.is_memory:
            # Move non-conflicting documents
            for doc_id, doc in list(self._documents.items()):
                if doc.case_id != source_case_id:
                    continue
                conflict = any(
                    d.case_id == target_case_id
                    and d.document_source == doc.document_source
                    and d.document_source_id == doc.document_source_id
                    for d in self._documents.values()
                    if d.id != doc_id
                )
                if not conflict:
                    self._documents[doc_id] = doc.model_copy(
                        update={'case_id': target_case_id}
                    )
            # Mark source as MERGED
            updated = source.model_copy(update={
                'status': 'MERGED',
                'merged_into_case_id': target_case_id,
                'updated_at': now,
            })
            self._cases[source_case_id] = updated
            return updated

        import asyncpg
        conn = await asyncpg.connect(self.database_url)
        try:
            async with conn.transaction():
                # Move non-conflicting documents
                await conn.execute(
                    """
                    UPDATE case_documents cd
                    SET case_id = $1
                    WHERE cd.case_id = $2
                      AND NOT EXISTS (
                        SELECT 1 FROM case_documents cd2
                        WHERE cd2.case_id = $1
                          AND cd2.document_source = cd.document_source
                          AND cd2.document_source_id = cd.document_source_id
                      )
                    """,
                    target_case_id, source_case_id,
                )
                # Mark source as MERGED
                await conn.execute(
                    "UPDATE case_cases SET status='MERGED', merged_into_case_id=$1, updated_at=$2 WHERE id=$3",
                    target_case_id, now, source_case_id,
                )
        finally:
            await conn.close()

        result = await self.get_case(source_case_id)
        assert result is not None
        return result

    # ── row converters ────────────────────────────────────────────────────────

    @staticmethod
    def _row_to_case(row: dict) -> CaseRecord:
        row['metadata'] = row.get('metadata') or {}
        if isinstance(row['metadata'], str):
            row['metadata'] = json.loads(row['metadata'])
        return CaseRecord(**row)

    @staticmethod
    def _row_to_doc(row: dict) -> CaseDocumentRecord:
        row['metadata'] = row.get('metadata') or {}
        if isinstance(row['metadata'], str):
            row['metadata'] = json.loads(row['metadata'])
        return CaseDocumentRecord(**row)

    @staticmethod
    def _row_to_conflict(row: dict) -> CaseConflictRecord:
        row['metadata'] = row.get('metadata') or {}
        if isinstance(row['metadata'], str):
            row['metadata'] = json.loads(row['metadata'])
        return CaseConflictRecord(**row)
