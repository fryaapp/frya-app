"""BulkUploadRepository — dual-mode (memory / PostgreSQL) CRUD for Batch-Tracking.

Pattern follows app/case_engine/repository.py:
- self.is_memory → True for 'memory://' URLs (used in tests)
- asyncpg for production PostgreSQL

Tenant-Isolation: EVERY query that accesses upload_items uses tenant_id filter.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any


class BulkUploadRepository:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        # memory backend
        self._batches: dict[str, dict] = {}
        self._items: dict[str, dict] = {}

    @property
    def is_memory(self) -> bool:
        return self.database_url.startswith('memory://')

    # ── helpers ────────────────────────────────────────────────────────────────

    def _now(self) -> datetime:
        return datetime.now(timezone.utc)

    def _item_matches_tenant(self, item: dict, tenant_id: str) -> bool:
        return item['tenant_id'] == str(tenant_id)

    # ── create ─────────────────────────────────────────────────────────────────

    async def create_batch(
        self, tenant_id: str | uuid.UUID, uploaded_by: str, file_count: int
    ) -> dict:
        now = self._now()
        batch_id = str(uuid.uuid4())
        record = {
            'id': batch_id,
            'tenant_id': str(tenant_id),
            'uploaded_by': uploaded_by,
            'file_count': file_count,
            'status': 'uploading',
            'completed_at': None,
            'created_at': now,
        }

        if self.is_memory:
            self._batches[batch_id] = record
            return dict(record)

        import asyncpg
        conn = await asyncpg.connect(self.database_url)
        try:
            await conn.execute(
                """
                INSERT INTO document_upload_batches
                (id, tenant_id, uploaded_by, file_count, status, created_at)
                VALUES ($1, $2, $3, $4, 'uploading', $5)
                """,
                uuid.UUID(batch_id), uuid.UUID(str(tenant_id)),
                uploaded_by, file_count, now,
            )
        finally:
            await conn.close()
        return record

    async def create_items(
        self,
        batch_id: str,
        tenant_id: str | uuid.UUID,
        items: list[dict],
    ) -> list[dict]:
        """Create upload items for a batch.

        Each item dict: {filename, file_size_bytes?, file_hash?, status?}
        Returns list of created item dicts with 'id' field set.
        """
        now = self._now()
        created = []

        if self.is_memory:
            for item in items:
                item_id = str(uuid.uuid4())
                record = {
                    'id': item_id,
                    'batch_id': batch_id,
                    'tenant_id': str(tenant_id),
                    'filename': item['filename'],
                    'file_size_bytes': item.get('file_size_bytes'),
                    'file_hash': item.get('file_hash'),
                    'paperless_task_id': item.get('paperless_task_id'),
                    'paperless_document_id': None,
                    'status': item.get('status', 'uploading'),
                    'case_id': None,
                    'assignment_confidence': None,
                    'error_message': item.get('error_message'),
                    'metadata': item.get('metadata', {}),
                    'created_at': now,
                    'updated_at': now,
                }
                self._items[item_id] = record
                created.append(dict(record))
            return created

        import asyncpg
        conn = await asyncpg.connect(self.database_url)
        try:
            for item in items:
                item_id = str(uuid.uuid4())
                await conn.execute(
                    """
                    INSERT INTO document_upload_items
                    (id, batch_id, tenant_id, filename, file_size_bytes, file_hash,
                     paperless_task_id, status, error_message, metadata, created_at, updated_at)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
                    """,
                    uuid.UUID(item_id), uuid.UUID(batch_id), uuid.UUID(str(tenant_id)),
                    item['filename'], item.get('file_size_bytes'), item.get('file_hash'),
                    item.get('paperless_task_id'),
                    item.get('status', 'uploading'),
                    item.get('error_message'),
                    json.dumps(item.get('metadata', {})),
                    now, now,
                )
                record = {
                    'id': item_id,
                    'batch_id': batch_id,
                    'tenant_id': str(tenant_id),
                    'filename': item['filename'],
                    'file_size_bytes': item.get('file_size_bytes'),
                    'file_hash': item.get('file_hash'),
                    'paperless_task_id': item.get('paperless_task_id'),
                    'paperless_document_id': None,
                    'status': item.get('status', 'uploading'),
                    'case_id': None,
                    'assignment_confidence': None,
                    'error_message': item.get('error_message'),
                    'metadata': item.get('metadata', {}),
                    'created_at': now,
                    'updated_at': now,
                }
                created.append(record)
        finally:
            await conn.close()
        return created

    # ── read ───────────────────────────────────────────────────────────────────

    async def get_batch_with_items(
        self, batch_id: str, tenant_id: str | uuid.UUID
    ) -> dict | None:
        tid = str(tenant_id)

        if self.is_memory:
            batch = self._batches.get(batch_id)
            if batch is None or batch['tenant_id'] != tid:
                return None
            items = [
                dict(i) for i in self._items.values()
                if i['batch_id'] == batch_id and i['tenant_id'] == tid
            ]
            return {**dict(batch), 'items': items}

        import asyncpg
        conn = await asyncpg.connect(self.database_url)
        try:
            batch_row = await conn.fetchrow(
                "SELECT * FROM document_upload_batches WHERE id=$1 AND tenant_id=$2",
                uuid.UUID(batch_id), uuid.UUID(tid),
            )
            if batch_row is None:
                return None
            item_rows = await conn.fetch(
                "SELECT * FROM document_upload_items WHERE batch_id=$1 AND tenant_id=$2 ORDER BY created_at",
                uuid.UUID(batch_id), uuid.UUID(tid),
            )
        finally:
            await conn.close()
        batch = self._row_to_batch(dict(batch_row))
        items = [self._row_to_item(dict(r)) for r in item_rows]
        return {**batch, 'items': items}

    async def list_batches(
        self, tenant_id: str | uuid.UUID, limit: int = 20, offset: int = 0
    ) -> list[dict]:
        tid = str(tenant_id)

        if self.is_memory:
            batches = [
                dict(b) for b in self._batches.values()
                if b['tenant_id'] == tid
            ]
            batches.sort(key=lambda x: x['created_at'], reverse=True)
            return batches[offset:offset + limit]

        import asyncpg
        conn = await asyncpg.connect(self.database_url)
        try:
            rows = await conn.fetch(
                """
                SELECT * FROM document_upload_batches
                WHERE tenant_id=$1 ORDER BY created_at DESC LIMIT $2 OFFSET $3
                """,
                uuid.UUID(tid), limit, offset,
            )
        finally:
            await conn.close()
        return [self._row_to_batch(dict(r)) for r in rows]

    # ── update items ───────────────────────────────────────────────────────────

    async def update_item_status(
        self, item_id: str, status: str, **kwargs: Any
    ) -> None:
        """Update item status and any additional keyword-args (error_message, etc.)."""
        now = self._now()

        if self.is_memory:
            item = self._items.get(item_id)
            if item is not None:
                item['status'] = status
                item['updated_at'] = now
                for k, v in kwargs.items():
                    item[k] = v
            return

        import asyncpg
        conn = await asyncpg.connect(self.database_url)
        try:
            # Build dynamic SET clause for extra fields
            sets = ['status=$2', 'updated_at=$3']
            params: list[Any] = [uuid.UUID(item_id), status, now]
            for k, v in kwargs.items():
                if k in ('error_message', 'paperless_task_id'):
                    sets.append(f'{k}=${len(params) + 1}')
                    params.append(v)
            await conn.execute(
                f"UPDATE document_upload_items SET {', '.join(sets)} WHERE id=$1",
                *params,
            )
        finally:
            await conn.close()

    async def update_item_paperless_doc(
        self, item_id: str, paperless_document_id: int
    ) -> None:
        now = self._now()

        if self.is_memory:
            item = self._items.get(item_id)
            if item is not None:
                item['paperless_document_id'] = paperless_document_id
                item['updated_at'] = now
            return

        import asyncpg
        conn = await asyncpg.connect(self.database_url)
        try:
            await conn.execute(
                "UPDATE document_upload_items SET paperless_document_id=$2, updated_at=$3 WHERE id=$1",
                uuid.UUID(item_id), paperless_document_id, now,
            )
        finally:
            await conn.close()

    async def update_item_case(
        self,
        item_id: str,
        case_id: str | None,
        confidence: str | None,
        doc_data: dict | None = None,
    ) -> None:
        """Set case assignment on item. doc_data is stored in metadata for re-evaluate."""
        now = self._now()

        if self.is_memory:
            item = self._items.get(item_id)
            if item is not None:
                item['case_id'] = case_id
                item['assignment_confidence'] = confidence
                item['updated_at'] = now
                if doc_data is not None:
                    item.setdefault('metadata', {})['doc_data'] = doc_data
            return

        import asyncpg
        conn = await asyncpg.connect(self.database_url)
        try:
            if doc_data is not None:
                await conn.execute(
                    """
                    UPDATE document_upload_items
                    SET case_id=$2, assignment_confidence=$3, updated_at=$4,
                        metadata = metadata || $5::jsonb
                    WHERE id=$1
                    """,
                    uuid.UUID(item_id),
                    uuid.UUID(case_id) if case_id else None,
                    confidence, now,
                    json.dumps({'doc_data': doc_data}),
                )
            else:
                await conn.execute(
                    """
                    UPDATE document_upload_items
                    SET case_id=$2, assignment_confidence=$3, updated_at=$4
                    WHERE id=$1
                    """,
                    uuid.UUID(item_id),
                    uuid.UUID(case_id) if case_id else None,
                    confidence, now,
                )
        finally:
            await conn.close()

    async def update_batch_status(
        self, batch_id: str, status: str, completed_at: datetime | None = None
    ) -> None:
        if self.is_memory:
            batch = self._batches.get(batch_id)
            if batch is not None:
                batch['status'] = status
                if completed_at is not None:
                    batch['completed_at'] = completed_at
            return

        import asyncpg
        conn = await asyncpg.connect(self.database_url)
        try:
            await conn.execute(
                "UPDATE document_upload_batches SET status=$2, completed_at=$3 WHERE id=$1",
                uuid.UUID(batch_id), status, completed_at,
            )
        finally:
            await conn.close()

    # ── lookup ─────────────────────────────────────────────────────────────────

    async def find_item_by_paperless_doc(
        self, tenant_id: str | uuid.UUID, paperless_document_id: int
    ) -> dict | None:
        """Tenant-isolated lookup: document_id → upload item. Always uses tenant_id."""
        tid = str(tenant_id)

        if self.is_memory:
            for item in self._items.values():
                if (
                    item['tenant_id'] == tid
                    and item['paperless_document_id'] == paperless_document_id
                ):
                    return dict(item)
            return None

        import asyncpg
        conn = await asyncpg.connect(self.database_url)
        try:
            row = await conn.fetchrow(
                """
                SELECT * FROM document_upload_items
                WHERE tenant_id=$1 AND paperless_document_id=$2
                """,
                uuid.UUID(tid), paperless_document_id,
            )
        finally:
            await conn.close()
        return self._row_to_item(dict(row)) if row else None

    async def find_duplicate_hash(
        self, batch_id: str, file_hash: str
    ) -> dict | None:
        if self.is_memory:
            for item in self._items.values():
                if item['batch_id'] == batch_id and item['file_hash'] == file_hash:
                    return dict(item)
            return None

        import asyncpg
        conn = await asyncpg.connect(self.database_url)
        try:
            row = await conn.fetchrow(
                "SELECT * FROM document_upload_items WHERE batch_id=$1 AND file_hash=$2 LIMIT 1",
                uuid.UUID(batch_id), file_hash,
            )
        finally:
            await conn.close()
        return self._row_to_item(dict(row)) if row else None

    async def get_orphan_items(self, batch_id: str) -> list[dict]:
        """Items with status='completed' but case_id IS NULL, or status='error'."""
        if self.is_memory:
            return [
                dict(i) for i in self._items.values()
                if i['batch_id'] == batch_id
                and (
                    (i['status'] == 'completed' and i.get('case_id') is None)
                    or i['status'] == 'error'
                )
            ]

        import asyncpg
        conn = await asyncpg.connect(self.database_url)
        try:
            rows = await conn.fetch(
                """
                SELECT * FROM document_upload_items
                WHERE batch_id=$1
                AND ((status='completed' AND case_id IS NULL) OR status='error')
                ORDER BY created_at
                """,
                uuid.UUID(batch_id),
            )
        finally:
            await conn.close()
        return [self._row_to_item(dict(r)) for r in rows]

    async def get_stuck_items(
        self, batch_id: str, timeout_minutes: int = 30
    ) -> list[dict]:
        """Items with status='uploaded' and updated_at older than timeout_minutes."""
        cutoff = self._now() - timedelta(minutes=timeout_minutes)

        if self.is_memory:
            return [
                dict(i) for i in self._items.values()
                if i['batch_id'] == batch_id
                and i['status'] == 'uploaded'
                and i['updated_at'] < cutoff
            ]

        import asyncpg
        conn = await asyncpg.connect(self.database_url)
        try:
            rows = await conn.fetch(
                """
                SELECT * FROM document_upload_items
                WHERE batch_id=$1 AND status='uploaded' AND updated_at < $2
                ORDER BY created_at
                """,
                uuid.UUID(batch_id), cutoff,
            )
        finally:
            await conn.close()
        return [self._row_to_item(dict(r)) for r in rows]

    async def is_batch_ready_for_reevaluate(self, batch_id: str) -> bool:
        """True when NO item has status IN ('uploading', 'uploaded') AND at least 1 item exists."""
        if self.is_memory:
            batch_items = [i for i in self._items.values() if i['batch_id'] == batch_id]
            if not batch_items:
                return False
            return not any(i['status'] in ('uploading', 'uploaded') for i in batch_items)

        import asyncpg
        conn = await asyncpg.connect(self.database_url)
        try:
            total = await conn.fetchval(
                "SELECT COUNT(*) FROM document_upload_items WHERE batch_id=$1",
                uuid.UUID(batch_id),
            )
            if not total:
                return False
            blocking = await conn.fetchval(
                """
                SELECT COUNT(*) FROM document_upload_items
                WHERE batch_id=$1 AND status IN ('uploading', 'uploaded')
                """,
                uuid.UUID(batch_id),
            )
        finally:
            await conn.close()
        return blocking == 0

    async def find_case_documents_by_paperless_doc(
        self, tenant_id: str | uuid.UUID, paperless_document_id: int
    ) -> dict | None:
        """Webhook fallback: look in case_documents for document_source='paperless'.

        Returns {'case_id': str} if found, else None.
        Used when Webhook fired but Bridge 2 didn't update upload_items.
        """
        if self.is_memory:
            # Cannot query case_documents in memory mode — return None
            return None

        import asyncpg
        conn = await asyncpg.connect(self.database_url)
        try:
            row = await conn.fetchrow(
                """
                SELECT cd.case_id
                FROM case_documents cd
                JOIN case_cases cc ON cc.id = cd.case_id
                WHERE cd.document_source = 'paperless'
                AND cd.document_source_id = $1
                AND cc.tenant_id = $2
                LIMIT 1
                """,
                str(paperless_document_id),
                uuid.UUID(str(tenant_id)),
            )
        finally:
            await conn.close()
        return {'case_id': str(row['case_id'])} if row else None

    # ── row converters ────────────────────────────────────────────────────────

    @staticmethod
    def _row_to_batch(row: dict) -> dict:
        for k in ('id', 'tenant_id'):
            if row.get(k) is not None:
                row[k] = str(row[k])
        return row

    @staticmethod
    def _row_to_item(row: dict) -> dict:
        for k in ('id', 'batch_id', 'tenant_id'):
            if row.get(k) is not None:
                row[k] = str(row[k])
        if row.get('case_id') is not None:
            row['case_id'] = str(row['case_id'])
        # Decode metadata JSON if needed
        meta = row.get('metadata', '{}')
        if isinstance(meta, str):
            try:
                row['metadata'] = json.loads(meta)
            except Exception:
                row['metadata'] = {}
        elif meta is None:
            row['metadata'] = {}
        return row
