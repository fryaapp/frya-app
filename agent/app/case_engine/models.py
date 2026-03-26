from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

CaseType = Literal[
    'incoming_invoice',
    'outgoing_invoice',
    'contract',
    'notice',
    'tax_document',
    'correspondence',
    'receipt',
    'bank_statement',
    'dunning',
    'insurance',
    'salary',
    'other',
]

CaseStatus = Literal['DRAFT', 'OPEN', 'OVERDUE', 'PAID', 'CLOSED', 'DISCARDED', 'MERGED']

DocumentSource = Literal['paperless', 'email', 'telegram', 'manual']

AssignmentConfidence = Literal['CERTAIN', 'HIGH', 'MEDIUM', 'LOW']

AssignmentMethod = Literal['hard_reference', 'entity_amount', 'llm_inference', 'manual']

ConflictType = Literal[
    'duplicate_case',
    'amount_mismatch',
    'date_mismatch',
    'vendor_mismatch',
    'multi_match',
]

ConflictResolution = Literal['pending', 'resolved_auto', 'resolved_manual', 'ignored']


class CaseRecord(BaseModel):
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    tenant_id: uuid.UUID
    case_number: str | None = None
    title: str | None = None
    case_type: CaseType
    status: CaseStatus = 'DRAFT'
    vendor_name: str | None = None
    total_amount: Decimal | None = None
    currency: str = 'EUR'
    due_date: date | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    created_by: str | None = None
    merged_into_case_id: uuid.UUID | None = None
    metadata: dict = Field(default_factory=dict)


class CaseDocumentRecord(BaseModel):
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    case_id: uuid.UUID
    document_source: DocumentSource
    document_source_id: str
    document_type: str | None = None
    assignment_confidence: AssignmentConfidence
    assignment_method: AssignmentMethod
    assigned_at: datetime = Field(default_factory=datetime.utcnow)
    assigned_by: str | None = None
    filename: str | None = None
    metadata: dict = Field(default_factory=dict)


class CaseReferenceRecord(BaseModel):
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    case_id: uuid.UUID
    reference_type: str
    reference_value: str
    extracted_from_document_id: uuid.UUID | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class CaseConflictRecord(BaseModel):
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    case_id: uuid.UUID
    conflict_type: ConflictType
    description: str | None = None
    resolution: ConflictResolution | None = None
    resolved_by: str | None = None
    resolved_at: datetime | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    metadata: dict = Field(default_factory=dict)


class CaseAssignment(BaseModel):
    """Result of the assignment engine — not a DB record."""
    case_id: uuid.UUID
    confidence: AssignmentConfidence
    method: AssignmentMethod
