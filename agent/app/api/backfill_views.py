"""Admin endpoint: backfill Paperless documents with metadata from CaseEngine."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.auth.dependencies import require_admin
from app.auth.models import AuthUser
from app.dependencies import get_case_repository, get_paperless_connector

logger = logging.getLogger(__name__)

router = APIRouter(prefix='/api/v1/admin', tags=['admin'])

# Same mapping as in nodes.py — keep in sync
_DOCUMENT_TYPE_MAP: dict[str, str] = {
    'INVOICE': 'Eingangsrechnung',
    'REMINDER': 'Mahnung',
    'CONTRACT': 'Vertrag',
    'NOTICE': 'Bescheid',
    'TAX_DOCUMENT': 'Steuerdokument',
    'RECEIPT': 'Quittung',
    'BANK_STATEMENT': 'Kontoauszug',
    'PAYSLIP': 'Lohnabrechnung',
    'INSURANCE': 'Versicherung',
    'OFFER': 'Angebot',
    'CREDIT_NOTE': 'Gutschrift',
    'DELIVERY_NOTE': 'Lieferschein',
    'LETTER': 'Brief',
    'PRIVATE': 'Privat',
    'AGB': 'AGB',
    'WIDERRUF': 'Sonstiges',
    'OTHER': 'Sonstiges',
}


class BackfillResponse(BaseModel):
    updated: int
    skipped: int
    errors: int
    details: list[dict[str, Any]]


@router.post('/backfill-paperless', response_model=BackfillResponse)
async def backfill_paperless(
    current_user: AuthUser = Depends(require_admin),
) -> BackfillResponse:
    """Backfill all Paperless documents with metadata from CaseEngine.

    For each Paperless document, look up matching case via document_source_id,
    then set correspondent, document_type, tags, title, and custom fields.
    """
    paperless = get_paperless_connector()
    case_repo = get_case_repository()
    paperless.invalidate_custom_field_cache()

    documents = await paperless.list_all_documents()
    field_ids = await paperless.get_custom_field_ids()

    updated = 0
    skipped = 0
    errors = 0
    details: list[dict[str, Any]] = []

    for doc in documents:
        doc_id = doc.get('id')
        if doc_id is None:
            continue

        try:
            # Find case linked to this Paperless document
            case_doc = await _find_case_for_document(case_repo, str(doc_id))
            if case_doc is None:
                skipped += 1
                details.append({'doc_id': doc_id, 'status': 'skipped', 'reason': 'no_case_found'})
                continue

            case = await case_repo.get_case(case_doc.case_id)
            if case is None:
                skipped += 1
                details.append({'doc_id': doc_id, 'status': 'skipped', 'reason': 'case_deleted'})
                continue

            patch_data: dict = {}

            # Correspondent from vendor_name
            if case.vendor_name:
                corr_id = await paperless.find_or_create_correspondent(case.vendor_name)
                if corr_id is not None:
                    patch_data['correspondent'] = corr_id

            # Document type
            if case_doc.document_type:
                dt_name = _DOCUMENT_TYPE_MAP.get(case_doc.document_type, 'Sonstiges')
                dt_id = await paperless.find_or_create_document_type(dt_name)
                if dt_id is not None:
                    patch_data['document_type'] = dt_id

            # Tags (merge with existing — never overwrite)
            existing_doc = await paperless.get_document(str(doc_id))
            tag_ids: list[int] = list(existing_doc.get('tags', []))
            analysiert_id = await paperless.find_or_create_tag('frya:analysiert', '#2196F3')
            if analysiert_id is not None and analysiert_id not in tag_ids:
                tag_ids.append(analysiert_id)
            if case_doc.document_type == 'INVOICE':
                vst_id = await paperless.find_or_create_tag('vorsteuer-relevant', '#673AB7')
                if vst_id is not None and vst_id not in tag_ids:
                    tag_ids.append(vst_id)
            if case.status == 'BOOKED':
                booked_id = await paperless.find_or_create_tag('frya:gebucht', '#4CAF50')
                if booked_id is not None and booked_id not in tag_ids:
                    tag_ids.append(booked_id)
            if tag_ids:
                patch_data['tags'] = tag_ids

            # Title: "Vendor — Betrag€ — Datum"
            title_parts: list[str] = []
            if case.vendor_name:
                title_parts.append(case.vendor_name)
            if case.total_amount is not None:
                currency = case.currency or 'EUR'
                title_parts.append(f'{float(case.total_amount):.2f}{currency}')
            if case.due_date:
                title_parts.append(case.due_date.strftime('%b %Y'))
            if title_parts:
                patch_data['title'] = ' — '.join(title_parts)

            # Custom fields
            custom_fields: list[dict] = []
            if 'frya_case_id' in field_ids:
                custom_fields.append({'field': field_ids['frya_case_id'], 'value': str(case.id)})
            if 'frya_status' in field_ids:
                custom_fields.append({'field': field_ids['frya_status'], 'value': case.status.lower()})
            if case.total_amount is not None and 'betrag_brutto' in field_ids:
                custom_fields.append({'field': field_ids['betrag_brutto'], 'value': str(case.total_amount)})
            if custom_fields:
                patch_data['custom_fields'] = custom_fields

            if patch_data:
                ok = await paperless.update_document_metadata(doc_id, patch_data)
                if ok:
                    updated += 1
                    details.append({'doc_id': doc_id, 'status': 'updated', 'fields': list(patch_data.keys())})
                else:
                    errors += 1
                    details.append({'doc_id': doc_id, 'status': 'error', 'reason': 'patch_failed'})
            else:
                skipped += 1
                details.append({'doc_id': doc_id, 'status': 'skipped', 'reason': 'no_data'})

        except Exception as exc:
            errors += 1
            details.append({'doc_id': doc_id, 'status': 'error', 'reason': str(exc)})
            logger.warning('Backfill error for doc %s: %s', doc_id, exc)

    return BackfillResponse(updated=updated, skipped=skipped, errors=errors, details=details)


async def _find_case_for_document(case_repo: Any, paperless_doc_id: str) -> Any:
    """Search all cases for a document linked to this Paperless document ID."""
    import asyncpg
    if case_repo.is_memory:
        for doc in case_repo._documents.values():
            if doc.document_source == 'paperless' and doc.document_source_id == paperless_doc_id:
                return doc
        return None
    conn = await asyncpg.connect(case_repo.database_url)
    try:
        row = await conn.fetchrow(
            "SELECT * FROM case_documents WHERE document_source='paperless' AND document_source_id=$1 LIMIT 1",
            paperless_doc_id,
        )
    finally:
        await conn.close()
    if row is None:
        return None
    return case_repo._row_to_doc(dict(row))
