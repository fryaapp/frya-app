"""Repository for third-party AVV document management."""
from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class AvvDocument(BaseModel):
    id: str
    tenant_id: str
    provider_name: str
    document_type: str = 'AVV'
    version: int = 1
    filename: str
    file_path: str
    file_size_bytes: int | None = None
    uploaded_by: str | None = None
    notes: str | None = None
    uploaded_at: str | None = None
    is_current: bool = True


class AvvRepository:
    def __init__(self, database_url: str, data_dir: Path) -> None:
        self._url = database_url
        self._data_dir = data_dir
        self._is_memory = database_url.startswith('memory://')
        self._docs: list[AvvDocument] = []

    async def initialize(self) -> None:
        if self._is_memory:
            return
        import asyncpg
        conn = await asyncpg.connect(self._url)
        try:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS frya_legal_documents (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    tenant_id UUID NOT NULL,
                    provider_name VARCHAR(255) NOT NULL,
                    document_type VARCHAR(100) DEFAULT 'AVV',
                    version INTEGER NOT NULL DEFAULT 1,
                    filename VARCHAR(500) NOT NULL,
                    file_path VARCHAR(1000) NOT NULL,
                    file_size_bytes INTEGER,
                    uploaded_by VARCHAR(255),
                    notes TEXT,
                    uploaded_at TIMESTAMPTZ DEFAULT NOW(),
                    is_current BOOLEAN DEFAULT TRUE
                )
            """)
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_legal_docs_tenant ON frya_legal_documents(tenant_id)"
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_legal_docs_provider ON frya_legal_documents(tenant_id, provider_name)"
            )
        finally:
            await conn.close()

    async def upload(
        self, *, tenant_id: str, provider_name: str, document_type: str,
        filename: str, file_bytes: bytes, uploaded_by: str, notes: str = '',
    ) -> AvvDocument:
        slug = re.sub(r'[^a-z0-9]+', '-', provider_name.lower()).strip('-')

        # Get next version
        existing = await self.list_by_provider(tenant_id, provider_name)
        next_version = max((d.version for d in existing), default=0) + 1

        # Save file
        rel_dir = Path('legal') / tenant_id / 'avv' / slug
        abs_dir = self._data_dir / rel_dir
        abs_dir.mkdir(parents=True, exist_ok=True)
        file_path = rel_dir / f'v{next_version}_{filename}'
        (self._data_dir / file_path).write_bytes(file_bytes)

        # Mark old versions as not current
        if not self._is_memory:
            import asyncpg
            conn = await asyncpg.connect(self._url)
            try:
                await conn.execute(
                    "UPDATE frya_legal_documents SET is_current=FALSE "
                    "WHERE tenant_id=$1 AND provider_name=$2 AND document_type=$3",
                    uuid.UUID(tenant_id), provider_name, document_type,
                )
                row = await conn.fetchrow(
                    "INSERT INTO frya_legal_documents (tenant_id, provider_name, document_type, version, filename, file_path, file_size_bytes, uploaded_by, notes) "
                    "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9) RETURNING *",
                    uuid.UUID(tenant_id), provider_name, document_type, next_version,
                    filename, str(file_path), len(file_bytes), uploaded_by, notes,
                )
                return AvvDocument(
                    id=str(row['id']), tenant_id=str(row['tenant_id']),
                    provider_name=row['provider_name'], document_type=row['document_type'],
                    version=row['version'], filename=row['filename'],
                    file_path=row['file_path'], file_size_bytes=row['file_size_bytes'],
                    uploaded_by=row['uploaded_by'], notes=row['notes'],
                    uploaded_at=str(row['uploaded_at'])[:19] if row['uploaded_at'] else None,
                    is_current=row['is_current'],
                )
            finally:
                await conn.close()
        else:
            doc = AvvDocument(
                id=str(uuid.uuid4()), tenant_id=tenant_id,
                provider_name=provider_name, document_type=document_type,
                version=next_version, filename=filename,
                file_path=str(file_path), file_size_bytes=len(file_bytes),
                uploaded_by=uploaded_by, notes=notes,
                uploaded_at=datetime.utcnow().isoformat()[:19],
            )
            # Mark old as not current
            for d in self._docs:
                if d.provider_name == provider_name and d.document_type == document_type:
                    d.is_current = False
            self._docs.append(doc)
            return doc

    async def list_all(self, tenant_id: str) -> list[AvvDocument]:
        if self._is_memory:
            return [d for d in self._docs if d.tenant_id == tenant_id]
        import asyncpg
        conn = await asyncpg.connect(self._url)
        try:
            rows = await conn.fetch(
                "SELECT * FROM frya_legal_documents WHERE tenant_id=$1 ORDER BY provider_name, version DESC",
                uuid.UUID(tenant_id),
            )
            return [self._row_to_doc(dict(r)) for r in rows]
        finally:
            await conn.close()

    async def list_by_provider(self, tenant_id: str, provider_name: str) -> list[AvvDocument]:
        if self._is_memory:
            return [d for d in self._docs if d.tenant_id == tenant_id and d.provider_name == provider_name]
        import asyncpg
        conn = await asyncpg.connect(self._url)
        try:
            rows = await conn.fetch(
                "SELECT * FROM frya_legal_documents WHERE tenant_id=$1 AND provider_name=$2 ORDER BY version DESC",
                uuid.UUID(tenant_id), provider_name,
            )
            return [self._row_to_doc(dict(r)) for r in rows]
        finally:
            await conn.close()

    async def get_by_id(self, doc_id: str) -> AvvDocument | None:
        if self._is_memory:
            return next((d for d in self._docs if d.id == doc_id), None)
        import asyncpg
        conn = await asyncpg.connect(self._url)
        try:
            row = await conn.fetchrow(
                "SELECT * FROM frya_legal_documents WHERE id=$1", uuid.UUID(doc_id),
            )
            return self._row_to_doc(dict(row)) if row else None
        finally:
            await conn.close()

    @staticmethod
    def _row_to_doc(row: dict) -> AvvDocument:
        return AvvDocument(
            id=str(row['id']), tenant_id=str(row['tenant_id']),
            provider_name=row['provider_name'], document_type=row.get('document_type', 'AVV'),
            version=row['version'], filename=row['filename'],
            file_path=row['file_path'], file_size_bytes=row.get('file_size_bytes'),
            uploaded_by=row.get('uploaded_by'), notes=row.get('notes'),
            uploaded_at=str(row['uploaded_at'])[:19] if row.get('uploaded_at') else None,
            is_current=row.get('is_current', True),
        )
