from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field

FieldStatus = Literal['FOUND', 'MISSING', 'UNCERTAIN', 'CONFLICT']
SourceKind = Literal['OCR_TEXT', 'PAPERLESS_METADATA', 'PREVIEW_TEXT', 'CASE_CONTEXT', 'DERIVED', 'NONE']
DocumentTypeValue = Literal['INVOICE', 'REMINDER', 'LETTER', 'CONTRACT', 'NOTICE', 'TAX_DOCUMENT', 'RECEIPT', 'BANK_STATEMENT', 'SALARY', 'INSURANCE', 'DUNNING', 'CORRESPONDENCE', 'PAYSLIP', 'OFFER', 'CREDIT_NOTE', 'DELIVERY_NOTE', 'PRIVATE', 'AGB', 'WIDERRUF', 'OTHER']
AnalysisDecision = Literal['ANALYZED', 'INCOMPLETE', 'LOW_CONFIDENCE', 'CONFLICT']
RecommendedNextStep = Literal['ACCOUNTING_REVIEW', 'HUMAN_REVIEW', 'OCR_RECHECK', 'GENERAL_REVIEW']
RiskSeverity = Literal['INFO', 'WARNING', 'HIGH']
AnnotationType = Literal[
    'payment_note', 'status_note', 'problem_note', 'payment_method',
    'correction_note', 'warning_note', 'allocation_note', 'tax_advisor_note',
    'check_mark', 'date_note', 'unknown',
]
AnnotationAction = Literal['CHECK_PAYMENT_EXISTS', 'FLAG_PROBLEM_CASE', 'SUGGEST_ALLOCATION', 'FLAG_FOR_TAX_ADVISOR', 'NONE']

T = TypeVar('T')


class ExtractedField(BaseModel, Generic[T]):
    model_config = ConfigDict(extra='forbid')

    value: T | None = None
    status: FieldStatus
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    source_kind: SourceKind = 'NONE'
    evidence_excerpt: str | None = None
    label: str | None = None  # Optional type label, e.g. 'invoice_number' for references


class DetectedAmount(BaseModel):
    model_config = ConfigDict(extra='forbid')

    label: str
    amount: Decimal | None = None
    currency: str | None = None
    status: FieldStatus
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    source_kind: SourceKind = 'NONE'
    evidence_excerpt: str | None = None


class Annotation(BaseModel):
    model_config = ConfigDict(extra='forbid')

    type: AnnotationType
    raw_text: str
    interpreted: str
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    action_suggested: AnnotationAction = 'NONE'


class DocumentRisk(BaseModel):
    model_config = ConfigDict(extra='forbid')

    code: str
    severity: RiskSeverity
    message: str
    related_fields: list[str] = Field(default_factory=list)


class DocumentAnalysisInput(BaseModel):
    model_config = ConfigDict(extra='forbid')

    case_id: str
    document_ref: str | None = None
    event_source: str
    paperless_metadata: dict[str, Any] = Field(default_factory=dict)
    ocr_text: str | None = None
    preview_text: str | None = None
    case_context: dict[str, Any] = Field(default_factory=dict)


class DocumentAnalysisResult(BaseModel):
    model_config = ConfigDict(extra='forbid')

    analysis_version: str = 'document-analyst-v1'
    case_id: str
    document_ref: str | None = None
    event_source: str
    document_type: ExtractedField[DocumentTypeValue]
    sender: ExtractedField[str]
    recipient: ExtractedField[str]
    amounts: list[DetectedAmount] = Field(default_factory=list)
    currency: ExtractedField[str]
    document_date: ExtractedField[date]
    due_date: ExtractedField[date]
    references: list[ExtractedField[str]] = Field(default_factory=list)
    risks: list[DocumentRisk] = Field(default_factory=list)
    annotations: list[Annotation] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    recommended_next_step: RecommendedNextStep
    global_decision: AnalysisDecision
    ready_for_accounting_review: bool = False
    overall_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    has_attachments: bool = False
    is_business_relevant: bool = True
    private_info: str | None = None
