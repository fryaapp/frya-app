from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class TelegramActor(BaseModel):
    chat_id: str
    chat_type: str | None = None
    sender_id: str | None = None
    sender_username: str | None = None


class TelegramMediaAttachment(BaseModel):
    media_kind: Literal['photo', 'document']
    telegram_file_id: str
    telegram_file_unique_id: str | None = None
    file_name: str | None = None
    mime_type: str | None = None
    file_size: int | None = None


class TelegramNormalizedIngressMessage(BaseModel):
    event_id: str
    source: Literal['telegram'] = 'telegram'
    raw_type: str = 'message'
    text: str
    update_id: int | None = None
    message_id: int | None = None
    reply_to_message_id: int | None = None
    telegram_update_ref: str
    telegram_message_ref: str
    telegram_reply_to_message_ref: str | None = None
    telegram_chat_ref: str
    actor: TelegramActor
    media_attachments: list[TelegramMediaAttachment] = Field(default_factory=list)


class TelegramRoutingResult(BaseModel):
    case_id: str
    routing_status: Literal[
        'STATUS_REQUEST',
        'HELP_REQUEST',
        'ACCEPTED_TO_INBOX',
        'MEDIA_ACCEPTED',
        'DOCUMENT_ACCEPTED',
        'MEDIA_TOO_LARGE',
        'DOCUMENT_TOO_LARGE',
        'MEDIA_UNSUPPORTED',
        'DOCUMENT_UNSUPPORTED',
        'MEDIA_DOWNLOAD_FAILED',
        'DOCUMENT_DOWNLOAD_FAILED',
        'MEDIA_UPLOAD_FAILED',
        'DOCUMENT_UPLOAD_FAILED',
        'CLARIFICATION_ANSWER_ACCEPTED',
        'CLARIFICATION_ANSWER_AMBIGUOUS',
        'CLARIFICATION_NOT_OPEN',
        'REJECTED_UNAUTHORIZED',
        'REJECTED_SECRET',
        'UNSUPPORTED_MESSAGE_TYPE',
        'DUPLICATE_IGNORED',
        'COMMUNICATOR_HANDLED',
        'COMMUNICATOR_GUARDRAIL_TRIGGERED',
    ]
    intent_name: str
    ack_template: Literal[
        'ACK_STATUS',
        'ACK_HELP',
        'ACK_ACCEPTED',
        'ACK_MEDIA_ACCEPTED',
        'ACK_DOCUMENT_ACCEPTED',
        'ACK_MEDIA_TOO_LARGE',
        'ACK_DOCUMENT_TOO_LARGE',
        'ACK_MEDIA_UNSUPPORTED',
        'ACK_DOCUMENT_UNSUPPORTED',
        'ACK_MEDIA_FAILED',
        'ACK_DOCUMENT_FAILED',
        'ACK_CLARIFICATION_RECEIVED',
        'ACK_CLARIFICATION_AMBIGUOUS',
        'ACK_CLARIFICATION_NOT_OPEN',
        'ACK_UNAUTHORIZED',
        'ACK_SECRET_DENIED',
        'ACK_UNSUPPORTED',
        'ACK_DUPLICATE',
        'ACK_COMMUNICATOR',
    ]
    authorization_status: Literal['AUTHORIZED', 'DENIED', 'SECRET_DENIED', 'SKIPPED']
    auth_reason: str | None = None
    open_item_id: str | None = None
    open_item_title: str | None = None
    next_manual_step: str | None = None
    reply_required: bool = True
    telegram_thread_ref: str | None = None
    linked_case_id: str | None = None
    linked_open_item_id: str | None = None
    linked_problem_case_id: str | None = None
    clarification_ref: str | None = None
    track_for_status: bool = False
    user_visible_status_code: str | None = None
    user_visible_status_label: str | None = None
    user_visible_status_detail: str | None = None


class TelegramCaseLinkRecord(BaseModel):
    link_id: str
    case_id: str
    telegram_update_ref: str
    telegram_message_ref: str
    telegram_chat_ref: str
    telegram_thread_ref: str
    sender_id: str | None = None
    sender_username: str | None = None
    routing_status: str
    authorization_status: str
    intent_name: str
    open_item_id: str | None = None
    open_item_title: str | None = None
    problem_case_id: str | None = None
    linked_case_id: str | None = None
    track_for_status: bool = False
    reply_status: str = 'NOT_ATTEMPTED'
    reply_reason: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class TelegramUserVisibleStatus(BaseModel):
    status_code: Literal[
        'RECEIVED',
        'IN_QUEUE',
        'IN_PROGRESS',
        'NEEDS_CLARIFICATION',
        'WAITING_FOR_YOUR_REPLY',
        'REPLY_RECEIVED',
        'UNDER_REVIEW',
        'NEEDS_FURTHER_REPLY',
        'UNDER_INTERNAL_REVIEW',
        'COMPLETED',
        'REJECTED',
        'NOT_AVAILABLE',
    ]
    status_label: str
    status_detail: str
    linked_case_id: str | None = None
    open_item_id: str | None = None
    open_item_title: str | None = None
    problem_case_id: str | None = None
    last_update_at: datetime | None = None


class TelegramClarificationRecord(BaseModel):
    clarification_ref: str
    linked_case_id: str
    telegram_thread_ref: str
    telegram_chat_ref: str
    telegram_case_ref: str
    telegram_case_link_id: str | None = None
    open_item_id: str | None = None
    open_item_title: str | None = None
    asked_by: str
    question_text: str
    clarification_round: int = 1
    parent_clarification_ref: str | None = None
    follow_up_count: int = 0
    max_follow_up_allowed: int = 1
    follow_up_allowed: bool = False
    follow_up_reason: str | None = None
    follow_up_block_reason: str | None = None
    telegram_followup_exhausted: bool = False
    internal_followup_required: bool = False
    internal_followup_state: Literal['NOT_REQUIRED', 'REQUIRED', 'UNDER_REVIEW', 'IN_PROGRESS', 'COMPLETED'] = 'NOT_REQUIRED'
    handoff_reason: str | None = None
    operator_guidance: str | None = None
    telegram_clarification_closed_for_user_input: bool = False
    internal_followup_closed_for_user_input: bool = False
    late_reply_policy: str = 'REJECT_NOT_OPEN'
    internal_followup_review_started_at: datetime | None = None
    internal_followup_reviewed_by: str | None = None
    internal_followup_review_note: str | None = None
    internal_followup_resolved_at: datetime | None = None
    internal_followup_resolved_by: str | None = None
    internal_followup_resolution_note: str | None = None
    clarification_state: Literal['OPEN', 'ANSWER_RECEIVED', 'UNDER_REVIEW', 'STILL_OPEN', 'AMBIGUOUS', 'COMPLETED', 'WITHDRAWN'] = 'OPEN'
    expected_reply_state: Literal[
        'WAITING_FOR_REPLY',
        'ANSWER_RECEIVED',
        'UNDER_OPERATOR_REVIEW',
        'FOLLOWUP_NEEDED',
        'INTERNAL_REVIEW_CONTINUES',
        'AMBIGUOUS_ROUTING',
        'CLOSED',
    ] = 'WAITING_FOR_REPLY'
    delivery_state: Literal['PENDING', 'SENT', 'FAILED'] = 'PENDING'
    outgoing_message_id: int | None = None
    outgoing_message_ref: str | None = None
    answer_case_id: str | None = None
    answer_text: str | None = None
    answer_message_ref: str | None = None
    answer_received_at: datetime | None = None
    review_started_at: datetime | None = None
    reviewed_by: str | None = None
    review_note: str | None = None
    resolution_outcome: Literal['PENDING', 'COMPLETED', 'STILL_OPEN', 'WITHDRAWN'] = 'PENDING'
    resolved_at: datetime | None = None
    resolved_by: str | None = None
    resolution_note: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

class TelegramMediaIngressRecord(BaseModel):
    media_ref: str
    case_id: str
    telegram_chat_ref: str
    telegram_message_ref: str
    telegram_thread_ref: str
    media_kind: Literal['photo', 'document']
    media_domain: Literal['PHOTO', 'DOCUMENT']
    telegram_file_id: str
    telegram_file_unique_id: str | None = None
    file_name: str | None = None
    mime_type: str | None = None
    file_size: int | None = None
    download_status: Literal['PENDING', 'DOWNLOADED', 'FAILED', 'SKIPPED'] = 'PENDING'
    storage_status: Literal['PENDING', 'STORED', 'FAILED', 'SKIPPED'] = 'PENDING'
    stored_relative_path: str | None = None
    sha256: str | None = None
    open_item_id: str | None = None
    open_item_title: str | None = None
    document_ref: str | None = None
    document_intake_ref: str | None = None
    document_intake_status: Literal['NOT_APPLICABLE', 'DOCUMENT_INBOX_ACCEPTED', 'DOCUMENT_INTAKE_PENDING', 'DOCUMENT_INTAKE_LINKED'] = 'NOT_APPLICABLE'
    linked_context_case_id: str | None = None
    linked_context_reason: str | None = None
    rejection_reason: str | None = None
    caption_text: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class TelegramDocumentAnalystContextRecord(BaseModel):
    analyst_context_ref: str
    source_case_id: str
    target_case_id: str
    telegram_document_ref: str
    telegram_media_ref: str
    media_domain: Literal['PHOTO', 'DOCUMENT']
    telegram_chat_ref: str
    telegram_message_ref: str
    telegram_thread_ref: str
    document_intake_ref: str | None = None
    document_intake_status: Literal['NOT_APPLICABLE', 'DOCUMENT_INBOX_ACCEPTED', 'DOCUMENT_INTAKE_LINKED'] | None = None
    analyst_context_status: Literal[
        'DOCUMENT_ANALYST_CONTEXT_READY',
        'DOCUMENT_ANALYST_CONTEXT_ATTACHED',
        'DOCUMENT_ANALYST_PENDING',
    ]
    analyst_context_open_item_id: str | None = None
    analyst_context_open_item_title: str | None = None
    document_context_link_confidence: Literal['LOW', 'MEDIUM']
    document_context_link_reason: str | None = None
    operator_confirmation_required: bool = True
    source_channel: Literal['TELEGRAM', 'EMAIL', 'MANUAL'] = 'TELEGRAM'
    storage_path: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class TelegramDocumentAnalystStartRecord(BaseModel):
    start_ref: str
    document_analyst_context_ref: str
    source_case_id: str
    target_case_id: str
    telegram_document_ref: str
    telegram_media_ref: str
    media_domain: Literal['PHOTO', 'DOCUMENT']
    document_intake_ref: str | None = None
    analysis_start_status: Literal[
        'DOCUMENT_ANALYST_START_READY',
        'DOCUMENT_ANALYST_START_REQUESTED',
        'DOCUMENT_ANALYST_RUNTIME_STARTED',
        'DOCUMENT_ANALYST_RUNTIME_FAILED',
    ]
    analysis_start_confidence: Literal['LOW', 'MEDIUM']
    analysis_start_reason: str | None = None
    analysis_start_requires_operator: bool = True
    trigger: str | None = None
    actor: str | None = None
    note: str | None = None
    runtime_case_id: str | None = None
    runtime_output_status: str | None = None
    runtime_open_item_id: str | None = None
    runtime_problem_id: str | None = None
    runtime_error: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class TelegramDocumentAnalystReviewRecord(BaseModel):
    review_ref: str
    document_analyst_start_ref: str
    document_analyst_context_ref: str
    source_case_id: str
    target_case_id: str
    telegram_document_ref: str
    telegram_media_ref: str
    document_intake_ref: str | None = None
    runtime_case_id: str
    runtime_output_status: str | None = None
    runtime_open_item_id: str | None = None
    runtime_problem_id: str | None = None
    runtime_decision: str | None = None
    runtime_next_step: str | None = None
    review_status: Literal[
        'DOCUMENT_ANALYST_REVIEW_READY',
        'DOCUMENT_ANALYST_REVIEW_COMPLETED',
        'DOCUMENT_ANALYST_REVIEW_STILL_OPEN',
    ]
    review_outcome: Literal['OUTPUT_ACCEPTED', 'OUTPUT_INCOMPLETE', 'OUTPUT_NEEDS_MANUAL_FOLLOWUP'] | None = None
    review_guidance: str | None = None
    no_further_telegram_action: bool = True
    actor: str | None = None
    note: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class TelegramDocumentAnalystFollowupRecord(BaseModel):
    followup_ref: str
    review_ref: str
    document_analyst_start_ref: str
    document_analyst_context_ref: str
    source_case_id: str
    target_case_id: str
    telegram_document_ref: str
    telegram_media_ref: str
    document_intake_ref: str | None = None
    runtime_case_id: str
    runtime_output_status: str | None = None
    runtime_open_item_id: str | None = None
    runtime_problem_id: str | None = None
    followup_status: Literal[
        'DOCUMENT_ANALYST_FOLLOWUP_REQUIRED',
        'DOCUMENT_ANALYST_FOLLOWUP_DATA_REQUESTED',
        'DOCUMENT_ANALYST_FOLLOWUP_WAITING_USER',
        'DOCUMENT_ANALYST_FOLLOWUP_WITHDRAWN',
        'DOCUMENT_ANALYST_FOLLOWUP_INTERNAL_ONLY',
        'DOCUMENT_ANALYST_FOLLOWUP_COMPLETED',
    ]
    followup_mode: Literal['REQUEST_DATA', 'INTERNAL_ONLY', 'CLOSE_CONSERVATIVELY'] | None = None
    followup_reason: str | None = None
    telegram_data_request_allowed: bool = False
    telegram_data_request_withdraw_allowed: bool = False
    internal_resolution_allowed: bool = True
    internal_takeover_allowed: bool = False
    no_further_telegram_action: bool = True
    linked_clarification_ref: str | None = None
    linked_clarification_state: str | None = None
    data_request_question: str | None = None
    withdraw_reason: str | None = None
    internal_takeover_reason: str | None = None
    actor: str | None = None
    note: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class TelegramDocumentAnalystOcrRecheckRecord(BaseModel):
    ocr_recheck_ref: str
    review_ref: str
    source_case_id: str
    target_case_id: str
    telegram_document_ref: str
    ocr_recheck_status: Literal[
        'DOCUMENT_ANALYST_OCR_RECHECK_REQUESTED',
        'DOCUMENT_ANALYST_OCR_RECHECK_RUNNING',
        'DOCUMENT_ANALYST_OCR_RECHECK_COMPLETED',
        'DOCUMENT_ANALYST_OCR_RECHECK_FAILED',
    ]
    force_ocr: bool = True
    recheck_output_status: str | None = None
    recheck_open_item_id: str | None = None
    actor: str | None = None
    note: str | None = None
    error: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class TelegramDocumentAnalystDeepPathRecord(BaseModel):
    deep_path_ref: str
    review_ref: str
    source_case_id: str
    target_case_id: str
    telegram_document_ref: str
    deep_path_status: Literal[
        'DOCUMENT_ANALYST_DEEP_PATH_READY',
        'DOCUMENT_ANALYST_DEEP_PATH_TRIGGERED',
        'DOCUMENT_ANALYST_DEEP_PATH_COMPLETED',
    ]
    propose_only: bool = True
    document_type: str | None = None
    booking_proposal: dict | None = None
    booking_open_item_id: str | None = None
    note: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class TelegramDocumentAnalystMergeCandidateRecord(BaseModel):
    merge_ref: str
    start_ref: str
    source_case_id: str
    target_case_id: str
    telegram_document_ref: str
    candidate_case_id: str | None = None
    confidence_score: float = 0.0
    match_reasons: list[str] = Field(default_factory=list)
    merge_status: Literal[
        'DOCUMENT_ANALYST_MERGE_CANDIDATE_FOUND',
        'DOCUMENT_ANALYST_MERGE_CONFIRMED',
        'DOCUMENT_ANALYST_MERGE_REJECTED',
    ]
    actor: str | None = None
    note: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class TelegramNotificationRecord(BaseModel):
    notification_ref: str
    linked_case_id: str
    telegram_chat_ref: str | None = None
    telegram_case_ref: str | None = None
    telegram_case_link_id: str | None = None
    notification_type: Literal[
        'INTERNAL_REVIEW_STARTED',
        'CLARIFICATION_COMPLETED',
        'INTERNAL_FOLLOWUP_COMPLETED',
    ]
    notification_key: str
    trigger_action: str
    message_text: str
    state: Literal['NOTIFICATION_ELIGIBLE', 'NOTIFICATION_SENT', 'NOTIFICATION_SKIPPED', 'NOTIFICATION_FAILED']
    delivery_state: Literal['PENDING', 'SENT', 'FAILED', 'SKIPPED'] = 'PENDING'
    delivery_reason: str | None = None
    sent_message_id: int | None = None
    linked_open_item_id: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
