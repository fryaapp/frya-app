"""CaseEngine ← Document Analyst bridge.

Converts DocumentAnalysisResult fields (after OCR + extraction) into
CaseEngine operations:

  1. Run the two-layer deterministic assignment engine.
  2. Hit  → link the incoming document to the matched case.
  3. Miss → create a new DRAFT case for operator review.

The caller must supply a *tenant_id* (UUID).  If none is available the
caller should skip the integration entirely.

Source-channel mapping (event_source → DocumentSource):
  'telegram' / 'telegram_*' → 'telegram'
  'email'                   → 'email'
  'paperless_webhook'       → 'paperless'
  everything else           → 'manual'

Document-type mapping (DocumentTypeValue → CaseType):
  'INVOICE'  → 'incoming_invoice'
  'REMINDER' → 'dunning'
  'LETTER'   → 'correspondence'
  'OTHER'    → 'other'
"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.audit.service import AuditService
    from app.case_engine.repository import CaseRepository


# ── mappings ──────────────────────────────────────────────────────────────────

_SOURCE_MAP: dict[str, str] = {
    'telegram': 'telegram',
    'email': 'email',
    'paperless_webhook': 'paperless',
    'paperless': 'paperless',
    'api': 'manual',
    'manual': 'manual',
}

_DOCTYPE_TO_CASETYPE: dict[str, str] = {
    'INVOICE': 'incoming_invoice',
    'REMINDER': 'dunning',
    'LETTER': 'correspondence',
    'OTHER': 'other',
}


def _map_source(event_source: str) -> str:
    """Normalise event_source → CaseEngine DocumentSource literal."""
    if event_source.startswith('telegram'):
        return 'telegram'
    return _SOURCE_MAP.get(event_source, 'manual')


def _map_case_type(document_type_value: str | None) -> str:
    return _DOCTYPE_TO_CASETYPE.get(document_type_value or 'OTHER', 'other')


def _confidence_from_float(score: float) -> str:
    """Map overall_confidence float → AssignmentConfidence string (capped at MEDIUM)."""
    if score >= 0.9:
        return 'HIGH'
    if score >= 0.7:
        return 'MEDIUM'
    return 'LOW'


# ── main entry point ──────────────────────────────────────────────────────────

async def integrate_document_analysis(
    *,
    tenant_id: uuid.UUID,
    event_source: str,
    document_ref: str | None,
    document_type_value: str | None,
    vendor_name: str | None,
    total_amount: Decimal | None,
    currency: str | None,
    document_date: date | None,
    due_date: date | None,
    reference_values: list[str],
    filename: str | None,
    overall_confidence: float,
    orchestration_case_id: str,
    repo: 'CaseRepository',
    audit_service: 'AuditService | None' = None,
) -> dict[str, Any]:
    """Run the CaseEngine integration step for a single document.

    Args:
        tenant_id:              Tenant the document belongs to.
        event_source:           Source channel from the orchestration state
                                (e.g. 'telegram', 'email', 'paperless_webhook').
        document_ref:           Opaque document reference from the orchestration
                                state (paperless ID, email message-id, …).
        document_type_value:    Extracted document type ('INVOICE', 'REMINDER', …).
        vendor_name:            Extracted sender / vendor name.
        total_amount:           Extracted total amount (Decimal or None).
        currency:               Extracted currency code ('EUR', …).
        document_date:          Extracted document date.
        due_date:               Extracted due date.
        reference_values:       List of extracted reference strings (e.g. invoice
                                numbers).  Each is stored as 'invoice_number'.
        filename:               Original filename if available.
        overall_confidence:     Overall extraction confidence (0.0–1.0).
        orchestration_case_id:  The orchestration-layer case_id for audit logs.
        repo:                   CaseRepository instance.
        audit_service:          If provided, emits a 'document_assigned_to_case'
                                audit event.

    Returns:
        A dict with keys:
          status:        'assigned' | 'draft_created'
          case_id:       str  (UUID of the matched or newly created case)
          confidence:    str  (e.g. 'CERTAIN', 'HIGH', 'MEDIUM', 'LOW')
          method:        str  (e.g. 'hard_reference', 'entity_amount', 'llm_inference')
          created_draft: bool
    """
    from app.case_engine.assignment import CaseAssignmentEngine, DocumentData

    document_source = _map_source(event_source)
    doc_source_id = document_ref or orchestration_case_id

    # References are stored as 'invoice_number' type (the most common label)
    ref_tuples: list[tuple[str, str]] = [
        ('invoice_number', v) for v in reference_values if v
    ]

    # total_amount must be float for the assignment engine's amount matcher
    total_amount_float: float | None = float(total_amount) if total_amount is not None else None

    doc = DocumentData(
        document_source=document_source,
        document_source_id=doc_source_id,
        reference_values=ref_tuples,
        vendor_name=vendor_name,
        total_amount=total_amount_float,
        currency=currency or 'EUR',
        document_date=document_date,
        filename=filename,
    )

    engine = CaseAssignmentEngine(repo)
    assignment = await engine.assign_document(tenant_id, doc)

    if assignment is not None:
        # ── Hit: link document to the matched case ────────────────────────────
        await repo.add_document_to_case(
            case_id=assignment.case_id,
            document_source=document_source,
            document_source_id=doc_source_id,
            assignment_confidence=assignment.confidence,
            assignment_method=assignment.method,
            document_type=document_type_value,
            filename=filename,
            assigned_by='document-analyst',
        )
        # Also persist newly found references on the matched case
        for ref_type, ref_value in ref_tuples:
            try:
                await repo.add_reference(
                    case_id=assignment.case_id,
                    reference_type=ref_type,
                    reference_value=ref_value,
                )
            except Exception:
                pass  # duplicate reference — ignore

        result: dict[str, Any] = {
            'status': 'assigned',
            'case_id': str(assignment.case_id),
            'confidence': assignment.confidence,
            'method': assignment.method,
            'created_draft': False,
        }

    else:
        # ── Miss: create a new DRAFT case for operator review ─────────────────
        case_type = _map_case_type(document_type_value)
        new_case = await repo.create_case(
            tenant_id=tenant_id,
            case_type=case_type,
            vendor_name=vendor_name,
            total_amount=total_amount,
            currency=currency or 'EUR',
            due_date=due_date,
            created_by='document-analyst',
        )
        await repo.add_document_to_case(
            case_id=new_case.id,
            document_source=document_source,
            document_source_id=doc_source_id,
            assignment_confidence=_confidence_from_float(overall_confidence),
            assignment_method='llm_inference',
            document_type=document_type_value,
            filename=filename,
            assigned_by='document-analyst',
        )
        for ref_type, ref_value in ref_tuples:
            try:
                await repo.add_reference(
                    case_id=new_case.id,
                    reference_type=ref_type,
                    reference_value=ref_value,
                )
            except Exception:
                pass

        result = {
            'status': 'draft_created',
            'case_id': str(new_case.id),
            'confidence': _confidence_from_float(overall_confidence),
            'method': 'llm_inference',
            'created_draft': True,
        }

    if audit_service is not None:
        await audit_service.log_event({
            'event_id': str(uuid.uuid4()),
            'case_id': orchestration_case_id,
            'source': document_source,
            'agent_name': 'case-engine-integration',
            'approval_status': 'NOT_REQUIRED',
            'action': 'document_assigned_to_case',
            'result': (
                f"status={result['status']};"
                f"case_id={result['case_id']};"
                f"confidence={result['confidence']};"
                f"method={result['method']}"
            ),
            'llm_output': result,
        })

    return result
