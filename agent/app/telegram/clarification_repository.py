from __future__ import annotations

import json
from collections.abc import Sequence

import asyncpg

from app.telegram.models import TelegramClarificationRecord


class TelegramClarificationRepository:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self._memory: dict[str, TelegramClarificationRecord] = {}

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
                CREATE TABLE IF NOT EXISTS frya_telegram_clarifications (
                    clarification_ref TEXT PRIMARY KEY,
                    linked_case_id TEXT NOT NULL,
                    telegram_thread_ref TEXT NOT NULL,
                    telegram_chat_ref TEXT NOT NULL,
                    telegram_case_ref TEXT NOT NULL,
                    telegram_case_link_id TEXT,
                    open_item_id TEXT,
                    open_item_title TEXT,
                    asked_by TEXT NOT NULL,
                    question_text TEXT NOT NULL,
                    clarification_round INTEGER NOT NULL DEFAULT 1,
                    parent_clarification_ref TEXT,
                    follow_up_count INTEGER NOT NULL DEFAULT 0,
                    max_follow_up_allowed INTEGER NOT NULL DEFAULT 1,
                    follow_up_allowed BOOLEAN NOT NULL DEFAULT FALSE,
                    follow_up_reason TEXT,
                    follow_up_block_reason TEXT,
                    telegram_followup_exhausted BOOLEAN NOT NULL DEFAULT FALSE,
                    internal_followup_required BOOLEAN NOT NULL DEFAULT FALSE,
                    internal_followup_state TEXT NOT NULL DEFAULT 'NOT_REQUIRED',
                    handoff_reason TEXT,
                    operator_guidance TEXT,
                    telegram_clarification_closed_for_user_input BOOLEAN NOT NULL DEFAULT FALSE,
                    internal_followup_closed_for_user_input BOOLEAN NOT NULL DEFAULT FALSE,
                    late_reply_policy TEXT NOT NULL DEFAULT 'REJECT_NOT_OPEN',
                    internal_followup_review_started_at TIMESTAMPTZ,
                    internal_followup_reviewed_by TEXT,
                    internal_followup_review_note TEXT,
                    internal_followup_resolved_at TIMESTAMPTZ,
                    internal_followup_resolved_by TEXT,
                    internal_followup_resolution_note TEXT,
                    clarification_state TEXT NOT NULL,
                    expected_reply_state TEXT NOT NULL,
                    delivery_state TEXT NOT NULL,
                    outgoing_message_id BIGINT,
                    outgoing_message_ref TEXT,
                    answer_case_id TEXT,
                    answer_text TEXT,
                    answer_message_ref TEXT,
                    answer_received_at TIMESTAMPTZ,
                    review_started_at TIMESTAMPTZ,
                    reviewed_by TEXT,
                    review_note TEXT,
                    resolution_outcome TEXT,
                    resolved_at TIMESTAMPTZ,
                    resolved_by TEXT,
                    resolution_note TEXT,
                    created_at TIMESTAMPTZ NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL
                )
                """
            )
            await conn.execute("ALTER TABLE frya_telegram_clarifications ADD COLUMN IF NOT EXISTS review_started_at TIMESTAMPTZ")
            await conn.execute("ALTER TABLE frya_telegram_clarifications ADD COLUMN IF NOT EXISTS reviewed_by TEXT")
            await conn.execute("ALTER TABLE frya_telegram_clarifications ADD COLUMN IF NOT EXISTS review_note TEXT")
            await conn.execute("ALTER TABLE frya_telegram_clarifications ADD COLUMN IF NOT EXISTS resolution_outcome TEXT")
            await conn.execute("ALTER TABLE frya_telegram_clarifications ADD COLUMN IF NOT EXISTS resolved_at TIMESTAMPTZ")
            await conn.execute("ALTER TABLE frya_telegram_clarifications ADD COLUMN IF NOT EXISTS resolved_by TEXT")
            await conn.execute("ALTER TABLE frya_telegram_clarifications ADD COLUMN IF NOT EXISTS clarification_round INTEGER NOT NULL DEFAULT 1")
            await conn.execute("ALTER TABLE frya_telegram_clarifications ADD COLUMN IF NOT EXISTS parent_clarification_ref TEXT")
            await conn.execute("ALTER TABLE frya_telegram_clarifications ADD COLUMN IF NOT EXISTS follow_up_count INTEGER NOT NULL DEFAULT 0")
            await conn.execute("ALTER TABLE frya_telegram_clarifications ADD COLUMN IF NOT EXISTS max_follow_up_allowed INTEGER NOT NULL DEFAULT 1")
            await conn.execute("ALTER TABLE frya_telegram_clarifications ADD COLUMN IF NOT EXISTS follow_up_allowed BOOLEAN NOT NULL DEFAULT FALSE")
            await conn.execute("ALTER TABLE frya_telegram_clarifications ADD COLUMN IF NOT EXISTS follow_up_reason TEXT")
            await conn.execute("ALTER TABLE frya_telegram_clarifications ADD COLUMN IF NOT EXISTS follow_up_block_reason TEXT")
            await conn.execute("ALTER TABLE frya_telegram_clarifications ADD COLUMN IF NOT EXISTS telegram_followup_exhausted BOOLEAN NOT NULL DEFAULT FALSE")
            await conn.execute("ALTER TABLE frya_telegram_clarifications ADD COLUMN IF NOT EXISTS internal_followup_required BOOLEAN NOT NULL DEFAULT FALSE")
            await conn.execute("ALTER TABLE frya_telegram_clarifications ADD COLUMN IF NOT EXISTS internal_followup_state TEXT NOT NULL DEFAULT 'NOT_REQUIRED'")
            await conn.execute("ALTER TABLE frya_telegram_clarifications ADD COLUMN IF NOT EXISTS handoff_reason TEXT")
            await conn.execute("ALTER TABLE frya_telegram_clarifications ADD COLUMN IF NOT EXISTS operator_guidance TEXT")
            await conn.execute("ALTER TABLE frya_telegram_clarifications ADD COLUMN IF NOT EXISTS telegram_clarification_closed_for_user_input BOOLEAN NOT NULL DEFAULT FALSE")
            await conn.execute("ALTER TABLE frya_telegram_clarifications ADD COLUMN IF NOT EXISTS internal_followup_closed_for_user_input BOOLEAN NOT NULL DEFAULT FALSE")
            await conn.execute("ALTER TABLE frya_telegram_clarifications ADD COLUMN IF NOT EXISTS late_reply_policy TEXT NOT NULL DEFAULT 'REJECT_NOT_OPEN'")
            await conn.execute("ALTER TABLE frya_telegram_clarifications ADD COLUMN IF NOT EXISTS internal_followup_review_started_at TIMESTAMPTZ")
            await conn.execute("ALTER TABLE frya_telegram_clarifications ADD COLUMN IF NOT EXISTS internal_followup_reviewed_by TEXT")
            await conn.execute("ALTER TABLE frya_telegram_clarifications ADD COLUMN IF NOT EXISTS internal_followup_review_note TEXT")
            await conn.execute("ALTER TABLE frya_telegram_clarifications ADD COLUMN IF NOT EXISTS internal_followup_resolved_at TIMESTAMPTZ")
            await conn.execute("ALTER TABLE frya_telegram_clarifications ADD COLUMN IF NOT EXISTS internal_followup_resolved_by TEXT")
            await conn.execute("ALTER TABLE frya_telegram_clarifications ADD COLUMN IF NOT EXISTS internal_followup_resolution_note TEXT")
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_frya_tg_clarifications_thread ON frya_telegram_clarifications(telegram_thread_ref, updated_at DESC)"
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_frya_tg_clarifications_case ON frya_telegram_clarifications(linked_case_id, updated_at DESC)"
            )
        finally:
            await conn.close()

    async def upsert(self, record: TelegramClarificationRecord) -> None:
        if self.is_memory:
            self._memory[record.clarification_ref] = record
            return
        conn = await asyncpg.connect(self.database_url)
        try:
            await conn.execute(
                """
                INSERT INTO frya_telegram_clarifications (
                    clarification_ref, linked_case_id, telegram_thread_ref, telegram_chat_ref, telegram_case_ref,
                    telegram_case_link_id, open_item_id, open_item_title, asked_by, question_text,
                    clarification_round, parent_clarification_ref, follow_up_count, max_follow_up_allowed,
                    follow_up_allowed, follow_up_reason, follow_up_block_reason,
                    telegram_followup_exhausted, internal_followup_required, internal_followup_state,
                    handoff_reason, operator_guidance, telegram_clarification_closed_for_user_input,
                    internal_followup_closed_for_user_input, late_reply_policy, internal_followup_review_started_at,
                    internal_followup_reviewed_by, internal_followup_review_note, internal_followup_resolved_at,
                    internal_followup_resolved_by, internal_followup_resolution_note, clarification_state,
                    expected_reply_state, delivery_state, outgoing_message_id, outgoing_message_ref, answer_case_id,
                    answer_text, answer_message_ref, answer_received_at, review_started_at, reviewed_by, review_note,
                    resolution_outcome, resolved_at, resolved_by, resolution_note, created_at, updated_at
                ) VALUES (
                    $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,
                    $11,$12,$13,$14,$15,$16,$17,$18,$19,$20,
                    $21,$22,$23,$24,$25,$26,$27,$28,$29,$30,
                    $31,$32,$33,$34,$35,$36,$37,$38,$39,$40,
                    $41,$42,$43,$44,$45,$46,$47,$48,$49
                )
                ON CONFLICT (clarification_ref)
                DO UPDATE SET
                    linked_case_id = EXCLUDED.linked_case_id,
                    telegram_thread_ref = EXCLUDED.telegram_thread_ref,
                    telegram_chat_ref = EXCLUDED.telegram_chat_ref,
                    telegram_case_ref = EXCLUDED.telegram_case_ref,
                    telegram_case_link_id = EXCLUDED.telegram_case_link_id,
                    open_item_id = EXCLUDED.open_item_id,
                    open_item_title = EXCLUDED.open_item_title,
                    asked_by = EXCLUDED.asked_by,
                    question_text = EXCLUDED.question_text,
                    clarification_round = EXCLUDED.clarification_round,
                    parent_clarification_ref = EXCLUDED.parent_clarification_ref,
                    follow_up_count = EXCLUDED.follow_up_count,
                    max_follow_up_allowed = EXCLUDED.max_follow_up_allowed,
                    follow_up_allowed = EXCLUDED.follow_up_allowed,
                    follow_up_reason = EXCLUDED.follow_up_reason,
                    follow_up_block_reason = EXCLUDED.follow_up_block_reason,
                    telegram_followup_exhausted = EXCLUDED.telegram_followup_exhausted,
                    internal_followup_required = EXCLUDED.internal_followup_required,
                    internal_followup_state = EXCLUDED.internal_followup_state,
                    handoff_reason = EXCLUDED.handoff_reason,
                    operator_guidance = EXCLUDED.operator_guidance,
                    telegram_clarification_closed_for_user_input = EXCLUDED.telegram_clarification_closed_for_user_input,
                    internal_followup_closed_for_user_input = EXCLUDED.internal_followup_closed_for_user_input,
                    late_reply_policy = EXCLUDED.late_reply_policy,
                    internal_followup_review_started_at = EXCLUDED.internal_followup_review_started_at,
                    internal_followup_reviewed_by = EXCLUDED.internal_followup_reviewed_by,
                    internal_followup_review_note = EXCLUDED.internal_followup_review_note,
                    internal_followup_resolved_at = EXCLUDED.internal_followup_resolved_at,
                    internal_followup_resolved_by = EXCLUDED.internal_followup_resolved_by,
                    internal_followup_resolution_note = EXCLUDED.internal_followup_resolution_note,
                    clarification_state = EXCLUDED.clarification_state,
                    expected_reply_state = EXCLUDED.expected_reply_state,
                    delivery_state = EXCLUDED.delivery_state,
                    outgoing_message_id = EXCLUDED.outgoing_message_id,
                    outgoing_message_ref = EXCLUDED.outgoing_message_ref,
                    answer_case_id = EXCLUDED.answer_case_id,
                    answer_text = EXCLUDED.answer_text,
                    answer_message_ref = EXCLUDED.answer_message_ref,
                    answer_received_at = EXCLUDED.answer_received_at,
                    review_started_at = EXCLUDED.review_started_at,
                    reviewed_by = EXCLUDED.reviewed_by,
                    review_note = EXCLUDED.review_note,
                    resolution_outcome = EXCLUDED.resolution_outcome,
                    resolved_at = EXCLUDED.resolved_at,
                    resolved_by = EXCLUDED.resolved_by,
                    resolution_note = EXCLUDED.resolution_note,
                    updated_at = EXCLUDED.updated_at
                """,
                record.clarification_ref,
                record.linked_case_id,
                record.telegram_thread_ref,
                record.telegram_chat_ref,
                record.telegram_case_ref,
                record.telegram_case_link_id,
                record.open_item_id,
                record.open_item_title,
                record.asked_by,
                record.question_text,
                record.clarification_round,
                record.parent_clarification_ref,
                record.follow_up_count,
                record.max_follow_up_allowed,
                record.follow_up_allowed,
                record.follow_up_reason,
                record.follow_up_block_reason,
                record.telegram_followup_exhausted,
                record.internal_followup_required,
                record.internal_followup_state,
                record.handoff_reason,
                record.operator_guidance,
                record.telegram_clarification_closed_for_user_input,
                record.internal_followup_closed_for_user_input,
                record.late_reply_policy,
                record.internal_followup_review_started_at,
                record.internal_followup_reviewed_by,
                record.internal_followup_review_note,
                record.internal_followup_resolved_at,
                record.internal_followup_resolved_by,
                record.internal_followup_resolution_note,
                record.clarification_state,
                record.expected_reply_state,
                record.delivery_state,
                record.outgoing_message_id,
                record.outgoing_message_ref,
                record.answer_case_id,
                record.answer_text,
                record.answer_message_ref,
                record.answer_received_at,
                record.review_started_at,
                record.reviewed_by,
                record.review_note,
                record.resolution_outcome,
                record.resolved_at,
                record.resolved_by,
                record.resolution_note,
                record.created_at,
                record.updated_at,
            )
        finally:
            await conn.close()

    async def get(self, clarification_ref: str) -> TelegramClarificationRecord | None:
        if self.is_memory:
            return self._memory.get(clarification_ref)
        conn = await asyncpg.connect(self.database_url)
        try:
            row = await conn.fetchrow(
                "SELECT * FROM frya_telegram_clarifications WHERE clarification_ref = $1",
                clarification_ref,
            )
            if row is None:
                return None
            return TelegramClarificationRecord(**json.loads(json.dumps(dict(row), default=str)))
        finally:
            await conn.close()

    async def latest_by_case(self, linked_case_id: str) -> TelegramClarificationRecord | None:
        if self.is_memory:
            matches = [x for x in self._memory.values() if x.linked_case_id == linked_case_id]
            if not matches:
                return None
            return sorted(matches, key=lambda item: item.updated_at, reverse=True)[0]
        conn = await asyncpg.connect(self.database_url)
        try:
            row = await conn.fetchrow(
                """
                SELECT * FROM frya_telegram_clarifications
                WHERE linked_case_id = $1
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                linked_case_id,
            )
            if row is None:
                return None
            return TelegramClarificationRecord(**json.loads(json.dumps(dict(row), default=str)))
        finally:
            await conn.close()

    async def list_by_case(self, linked_case_id: str) -> Sequence[TelegramClarificationRecord]:
        if self.is_memory:
            return sorted(
                [x for x in self._memory.values() if x.linked_case_id == linked_case_id],
                key=lambda item: (item.clarification_round, item.created_at, item.updated_at),
            )
        conn = await asyncpg.connect(self.database_url)
        try:
            rows = await conn.fetch(
                """
                SELECT * FROM frya_telegram_clarifications
                WHERE linked_case_id = $1
                ORDER BY clarification_round ASC, created_at ASC, updated_at ASC
                """,
                linked_case_id,
            )
            return [TelegramClarificationRecord(**json.loads(json.dumps(dict(row), default=str))) for row in rows]
        finally:
            await conn.close()

    async def open_by_thread(self, telegram_thread_ref: str) -> Sequence[TelegramClarificationRecord]:
        if self.is_memory:
            return sorted(
                [
                    x
                    for x in self._memory.values()
                    if x.telegram_thread_ref == telegram_thread_ref and x.clarification_state == 'OPEN'
                ],
                key=lambda item: item.updated_at,
                reverse=True,
            )
        conn = await asyncpg.connect(self.database_url)
        try:
            rows = await conn.fetch(
                """
                SELECT * FROM frya_telegram_clarifications
                WHERE telegram_thread_ref = $1
                  AND clarification_state = 'OPEN'
                ORDER BY updated_at DESC
                """,
                telegram_thread_ref,
            )
            return [TelegramClarificationRecord(**json.loads(json.dumps(dict(row), default=str))) for row in rows]
        finally:
            await conn.close()

    async def open_by_outgoing_message(
        self,
        telegram_thread_ref: str,
        outgoing_message_id: int,
    ) -> TelegramClarificationRecord | None:
        if self.is_memory:
            matches = [
                x
                for x in self._memory.values()
                if x.telegram_thread_ref == telegram_thread_ref
                and x.outgoing_message_id == outgoing_message_id
                and x.clarification_state == 'OPEN'
            ]
            if not matches:
                return None
            return sorted(matches, key=lambda item: item.updated_at, reverse=True)[0]
        conn = await asyncpg.connect(self.database_url)
        try:
            row = await conn.fetchrow(
                """
                SELECT * FROM frya_telegram_clarifications
                WHERE telegram_thread_ref = $1
                  AND outgoing_message_id = $2
                  AND clarification_state = 'OPEN'
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                telegram_thread_ref,
                outgoing_message_id,
            )
            if row is None:
                return None
            return TelegramClarificationRecord(**json.loads(json.dumps(dict(row), default=str)))
        finally:
            await conn.close()
