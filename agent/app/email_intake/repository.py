from __future__ import annotations
import json
from datetime import datetime
from typing import Any
import asyncpg
from app.email_intake.models import EmailAttachmentRecord, EmailIntakeRecord

_CREATE_INTAKE = """
CREATE TABLE IF NOT EXISTS frya_email_intake (
    email_intake_id TEXT PRIMARY KEY,
    received_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    sender_email TEXT NOT NULL,
    sender_name TEXT,
    recipient_email TEXT,
    subject TEXT,
    body_plain TEXT,
    message_id TEXT UNIQUE,
    user_ref TEXT,
    intake_status TEXT NOT NULL DEFAULT 'RECEIVED',
    attachment_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""

_CREATE_ATTACHMENTS = """
CREATE TABLE IF NOT EXISTS frya_email_attachments (
    attachment_id TEXT PRIMARY KEY,
    email_intake_id TEXT NOT NULL REFERENCES frya_email_intake(email_intake_id),
    file_name TEXT,
    mime_type TEXT,
    file_size INTEGER,
    storage_path TEXT,
    sha256 TEXT,
    analyst_case_id TEXT,
    analyst_context_ref TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""


class EmailIntakeRepository:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self._memory_intakes: dict[str, EmailIntakeRecord] = {}
        self._memory_attachments: dict[str, list[EmailAttachmentRecord]] = {}

    @property
    def is_memory(self) -> bool:
        return self.database_url.startswith('memory://')

    async def initialize(self) -> None:
        if self.is_memory:
            return
        conn = await asyncpg.connect(self.database_url)
        try:
            await conn.execute(_CREATE_INTAKE)
            await conn.execute(_CREATE_ATTACHMENTS)
        finally:
            await conn.close()

    async def create_intake(self, record: EmailIntakeRecord) -> EmailIntakeRecord:
        if self.is_memory:
            self._memory_intakes[record.email_intake_id] = record
            return record
        conn = await asyncpg.connect(self.database_url)
        try:
            await conn.execute(
                """
                INSERT INTO frya_email_intake
                (email_intake_id, received_at, sender_email, sender_name, recipient_email,
                 subject, body_plain, message_id, user_ref, intake_status, attachment_count,
                 created_at, updated_at)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
                ON CONFLICT (email_intake_id) DO NOTHING
                """,
                record.email_intake_id, record.received_at, record.sender_email,
                record.sender_name, record.recipient_email, record.subject,
                record.body_plain, record.message_id, record.user_ref,
                record.intake_status, record.attachment_count,
                record.created_at, record.updated_at,
            )
        finally:
            await conn.close()
        return record

    async def add_attachment(self, att: EmailAttachmentRecord) -> EmailAttachmentRecord:
        if self.is_memory:
            self._memory_attachments.setdefault(att.email_intake_id, []).append(att)
            return att
        conn = await asyncpg.connect(self.database_url)
        try:
            await conn.execute(
                """
                INSERT INTO frya_email_attachments
                (attachment_id, email_intake_id, file_name, mime_type, file_size,
                 storage_path, sha256, analyst_case_id, analyst_context_ref, created_at)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
                ON CONFLICT (attachment_id) DO NOTHING
                """,
                att.attachment_id, att.email_intake_id, att.file_name,
                att.mime_type, att.file_size, att.storage_path, att.sha256,
                att.analyst_case_id, att.analyst_context_ref, att.created_at,
            )
        finally:
            await conn.close()
        return att

    async def update_status(self, email_intake_id: str, status: str) -> None:
        if self.is_memory:
            if email_intake_id in self._memory_intakes:
                r = self._memory_intakes[email_intake_id]
                self._memory_intakes[email_intake_id] = r.model_copy(update={'intake_status': status})
            return
        conn = await asyncpg.connect(self.database_url)
        try:
            await conn.execute(
                "UPDATE frya_email_intake SET intake_status=$1, updated_at=NOW() WHERE email_intake_id=$2",
                status, email_intake_id,
            )
        finally:
            await conn.close()

    async def update_attachment_count(self, email_intake_id: str, count: int) -> None:
        if self.is_memory:
            if email_intake_id in self._memory_intakes:
                r = self._memory_intakes[email_intake_id]
                self._memory_intakes[email_intake_id] = r.model_copy(update={'attachment_count': count})
            return
        conn = await asyncpg.connect(self.database_url)
        try:
            await conn.execute(
                "UPDATE frya_email_intake SET attachment_count=$1, updated_at=NOW() WHERE email_intake_id=$2",
                count, email_intake_id,
            )
        finally:
            await conn.close()

    async def update_attachment_analyst(
        self, attachment_id: str, analyst_case_id: str, analyst_context_ref: str
    ) -> None:
        if self.is_memory:
            for atts in self._memory_attachments.values():
                for i, a in enumerate(atts):
                    if a.attachment_id == attachment_id:
                        atts[i] = a.model_copy(update={
                            'analyst_case_id': analyst_case_id,
                            'analyst_context_ref': analyst_context_ref,
                        })
            return
        conn = await asyncpg.connect(self.database_url)
        try:
            await conn.execute(
                "UPDATE frya_email_attachments SET analyst_case_id=$1, analyst_context_ref=$2 WHERE attachment_id=$3",
                analyst_case_id, analyst_context_ref, attachment_id,
            )
        finally:
            await conn.close()

    async def get_by_id(self, email_intake_id: str) -> EmailIntakeRecord | None:
        if self.is_memory:
            return self._memory_intakes.get(email_intake_id)
        conn = await asyncpg.connect(self.database_url)
        try:
            row = await conn.fetchrow(
                "SELECT * FROM frya_email_intake WHERE email_intake_id=$1", email_intake_id
            )
        finally:
            await conn.close()
        if row is None:
            return None
        return self._row_to_record(dict(row))

    async def list_recent(self, limit: int = 50, offset: int = 0) -> list[EmailIntakeRecord]:
        if self.is_memory:
            items = sorted(self._memory_intakes.values(), key=lambda r: r.received_at, reverse=True)
            return items[offset:offset + limit]
        conn = await asyncpg.connect(self.database_url)
        try:
            rows = await conn.fetch(
                "SELECT * FROM frya_email_intake ORDER BY received_at DESC LIMIT $1 OFFSET $2",
                limit, offset,
            )
        finally:
            await conn.close()
        return [self._row_to_record(dict(r)) for r in rows]

    async def get_attachments(self, email_intake_id: str) -> list[EmailAttachmentRecord]:
        if self.is_memory:
            return list(self._memory_attachments.get(email_intake_id, []))
        conn = await asyncpg.connect(self.database_url)
        try:
            rows = await conn.fetch(
                "SELECT * FROM frya_email_attachments WHERE email_intake_id=$1 ORDER BY created_at",
                email_intake_id,
            )
        finally:
            await conn.close()
        return [self._att_row_to_record(dict(r)) for r in rows]

    async def find_by_user_ref(self, user_ref: str, limit: int = 5) -> list[EmailIntakeRecord]:
        if self.is_memory:
            results = [r for r in self._memory_intakes.values() if r.user_ref == user_ref]
            return sorted(results, key=lambda r: r.received_at, reverse=True)[:limit]
        conn = await asyncpg.connect(self.database_url)
        try:
            rows = await conn.fetch(
                "SELECT * FROM frya_email_intake WHERE user_ref=$1 ORDER BY received_at DESC LIMIT $2",
                user_ref, limit,
            )
        finally:
            await conn.close()
        return [self._row_to_record(dict(r)) for r in rows]

    async def message_id_exists(self, message_id: str) -> bool:
        if self.is_memory:
            return any(r.message_id == message_id for r in self._memory_intakes.values())
        conn = await asyncpg.connect(self.database_url)
        try:
            row = await conn.fetchrow(
                "SELECT email_intake_id FROM frya_email_intake WHERE message_id=$1", message_id
            )
        finally:
            await conn.close()
        return row is not None

    @staticmethod
    def _row_to_record(row: dict) -> EmailIntakeRecord:
        for k in ('received_at', 'created_at', 'updated_at'):
            if row.get(k) and not isinstance(row[k], datetime):
                row[k] = row[k]
        return EmailIntakeRecord(**row)

    @staticmethod
    def _att_row_to_record(row: dict) -> EmailAttachmentRecord:
        for k in ('created_at',):
            if row.get(k) and not isinstance(row[k], datetime):
                row[k] = row[k]
        return EmailAttachmentRecord(**row)
