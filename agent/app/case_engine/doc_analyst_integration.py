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

import logging
import uuid
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Any

logger = logging.getLogger(__name__)

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
    'CREDIT_NOTE': 'other',
}


def _map_source(event_source: str) -> str:
    """Normalise event_source → CaseEngine DocumentSource literal."""
    if event_source.startswith('telegram'):
        return 'telegram'
    return _SOURCE_MAP.get(event_source, 'manual')


def _map_case_type(document_type_value: str | None) -> str:
    return _DOCTYPE_TO_CASETYPE.get(document_type_value or 'OTHER', 'other')


async def _is_own_company(sender_name: str | None, tenant_id: uuid.UUID) -> bool:
    """P-10 A1: Check if sender matches the user's own company (outgoing invoice).

    Uses fuzzy matching: 'Mycelium Enterprises' matches 'Mycelium Enterprises UG'.
    """
    if not sender_name or not sender_name.strip():
        return False
    try:
        import asyncpg
        from app.dependencies import get_settings
        conn = await asyncpg.connect(get_settings().database_url)
        try:
            bp = await conn.fetchrow(
                "SELECT company_name FROM frya_business_profile "
                "WHERE tenant_id IN ($1::text, 'default', '') LIMIT 1",
                str(tenant_id),
            )
            if not bp or not bp['company_name']:
                return False
            own_name = bp['company_name'].strip().lower()
            sender_lower = sender_name.strip().lower()
            # Exact or prefix/suffix match
            if own_name == sender_lower:
                return True
            if sender_lower.startswith(own_name) or own_name.startswith(sender_lower):
                return True
            # Remove legal suffixes for comparison
            for suffix in (' ug', ' gmbh', ' ag', ' e.k.', ' ohg', ' kg', ' gbr'):
                own_clean = own_name.rstrip(suffix).strip()
                sender_clean = sender_lower.rstrip(suffix).strip()
                if own_clean and sender_clean and (own_clean == sender_clean):
                    return True
            return False
        finally:
            await conn.close()
    except Exception as exc:
        logger.warning('_is_own_company check failed: %s', exc)
        return False


def _confidence_from_float(score: float) -> str:
    """Map overall_confidence float → AssignmentConfidence string (capped at MEDIUM)."""
    if score >= 0.9:
        return 'HIGH'
    if score >= 0.7:
        return 'MEDIUM'
    return 'LOW'


# ── reference type mapping ────────────────────────────────────────────────────

_KNOWN_REF_TYPES: frozenset[str] = frozenset({
    'invoice_number',
    'customer_number',
    'reference_number',
    'dunning_number',
    'order_number',
    'contract_number',
})

_REF_TYPE_ALIASES: dict[str, str] = {
    'reference': 'reference_number',
    'reminder_number': 'dunning_number',
    'ref': 'reference_number',
    'order': 'order_number',
    'contract': 'contract_number',
}


def map_reference_type(raw_type: str) -> str:
    """Normalise an analysis reference type to a canonical case_references.reference_type.

    Unknown types are stored as 'other' — never silently dropped.
    """
    normalized = raw_type.lower().strip().replace(' ', '_')
    if normalized in _KNOWN_REF_TYPES:
        return normalized
    return _REF_TYPE_ALIASES.get(normalized, 'other')


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
    reference_values: list[tuple[str, str]],
    filename: str | None,
    overall_confidence: float,
    orchestration_case_id: str,
    line_items: list[dict] | None = None,
    net_amount: Decimal | None = None,
    tax_amount: Decimal | None = None,
    analysis_version: str | None = None,
    is_business_relevant: bool | None = None,
    private_info: str | None = None,
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
        reference_values:       List of (reference_type, reference_value) tuples.
                                Types are normalised via map_reference_type().
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

    # Normalise reference types and filter empty values
    ref_tuples: list[tuple[str, str]] = [
        (map_reference_type(ref_type), ref_value)
        for ref_type, ref_value in reference_values
        if ref_value
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
            except Exception as exc:
                logger.debug('integrate_document_analysis: add_reference skipped (duplicate?): %s', exc)

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

        # P-10 A1: Check if this is the user's OWN outgoing invoice
        if case_type == 'incoming_invoice' and vendor_name:
            try:
                if await _is_own_company(vendor_name, tenant_id):
                    case_type = 'outgoing_invoice'
                    logger.info('Detected external outgoing invoice from own company: %s', vendor_name)
            except Exception as exc:
                logger.warning('Own-company check failed: %s', exc)
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
            except Exception as exc:
                logger.debug('integrate_document_analysis: add_reference (draft) skipped (duplicate?): %s', exc)

        result = {
            'status': 'draft_created',
            'case_id': str(new_case.id),
            'confidence': _confidence_from_float(overall_confidence),
            'method': 'llm_inference',
            'created_draft': True,
        }

    # Persist document_analysis summary in case metadata for communicator context
    _case_uuid = uuid.UUID(result['case_id'])
    try:
        await repo.update_metadata(_case_uuid, {
            'document_analysis': {
                'analysis_version': analysis_version,
                'overall_confidence': overall_confidence,
                'sender': vendor_name,
                'document_number': ref_tuples[0][1] if ref_tuples else None,
                'document_date': str(document_date) if document_date else None,
                'gross_amount': float(total_amount) if total_amount is not None else None,
                'net_amount': float(net_amount) if net_amount is not None else None,
                'tax_amount': float(tax_amount) if tax_amount is not None else None,
                'document_type': document_type_value,
                'is_business_relevant': is_business_relevant,
                'private_info': private_info,
                'line_items': line_items or [],
            }
        })
    except Exception as exc:
        logger.warning('integrate_document_analysis: metadata update failed: %s', exc)

    # Write FRYA analysis text back to Paperless "content" field
    if document_ref and document_ref.isdigit() and event_source in ('paperless_webhook', 'paperless'):
        try:
            from app.dependencies import get_paperless_connector
            pc = get_paperless_connector()
            # Build a human-readable analysis summary for Paperless
            analysis_lines = []
            if vendor_name:
                analysis_lines.append(f'Absender: {vendor_name}')
            if document_type_value:
                analysis_lines.append(f'Dokumenttyp: {document_type_value}')
            if total_amount is not None:
                analysis_lines.append(f'Betrag: {total_amount} {currency or "EUR"}')
            if net_amount is not None:
                analysis_lines.append(f'Netto: {net_amount} {currency or "EUR"}')
            if tax_amount is not None:
                analysis_lines.append(f'MwSt: {tax_amount} {currency or "EUR"}')
            if document_date:
                analysis_lines.append(f'Datum: {document_date}')
            if due_date:
                analysis_lines.append(f'Faellig: {due_date}')
            for ref_type, ref_value in ref_tuples:
                analysis_lines.append(f'{ref_type}: {ref_value}')
            if line_items:
                for li in line_items[:10]:
                    desc = li.get('description', '')
                    price = li.get('total_price', li.get('unit_price', ''))
                    if desc:
                        analysis_lines.append(f'  - {desc} {price}')
            if private_info:
                analysis_lines.append(f'Privat-Info: {private_info}')
            if is_business_relevant is False:
                analysis_lines.append('Geschaeftsrelevanz: Nein (privates Dokument)')

            content_text = '\n'.join(analysis_lines)
            if content_text:
                await pc.update_document_metadata(int(document_ref), {'content': content_text})
                logger.info('Wrote FRYA analysis back to Paperless doc %s (%d chars)', document_ref, len(content_text))
        except Exception as exc:
            logger.warning('Paperless content writeback failed for doc %s: %s', document_ref, exc)

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
