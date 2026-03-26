"""BulkUploadService — coordinates the upload flow and bridge logic.

Re-evaluate strategy:
  When Bridge 2 fires (paperless_post_consumption), the full document data
  (reference_values, vendor_name, total_amount, etc.) from the n8n webhook
  is stored in document_upload_items.metadata['doc_data'].
  In trigger_reevaluate, this data is read and CaseAssignmentEngine is called
  again without re-running the (expensive) Document Analyst OCR.

Webhook fallback (B3.6):
  For items with status='processing' (Bridge 1 done, Bridge 2 not yet), we check
  case_documents WHERE document_source='paperless' AND document_source_id=str(paperless_doc_id).
  This catches cases where the n8n webhook fired but Bridge 2 didn't update upload_items cleanly.
"""
from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.audit.service import AuditService
    from app.bulk_upload.repository import BulkUploadRepository
    from app.case_engine.repository import CaseRepository
    from app.connectors.dms_paperless import PaperlessConnector

logger = logging.getLogger(__name__)

_STUCK_TIMEOUT_MINUTES = 30


class BulkUploadService:
    def __init__(
        self,
        bulk_repo: 'BulkUploadRepository',
        case_repo: 'CaseRepository',
        paperless: 'PaperlessConnector',
        audit_service: 'AuditService | None' = None,
    ) -> None:
        self.bulk_repo = bulk_repo
        self.case_repo = case_repo
        self.paperless = paperless
        self.audit_service = audit_service

    # ── B3.4: Duplicate detection ──────────────────────────────────────────────

    async def prepare_upload_items(
        self,
        files: list[tuple[bytes, str]],
        batch_id: str,
        tenant_id: str | uuid.UUID,
    ) -> list[dict]:
        """Prepare item records and detect intra-batch duplicates via SHA256.

        1. Compute SHA256 hash per file.
        2. If hash already seen in this batch → status='duplicate_skipped'.
        3. Otherwise → status='uploading'.

        Returns list of dicts: {filename, file_hash, file_size_bytes,
                                status, is_duplicate, original_filename}
        """
        seen_hashes: dict[str, str] = {}  # hash → first filename
        result = []

        for file_bytes, filename in files:
            file_hash = hashlib.sha256(file_bytes).hexdigest()

            # Check existing items in DB for this batch (cross-call dedup)
            existing = await self.bulk_repo.find_duplicate_hash(batch_id, file_hash)

            if file_hash in seen_hashes or existing is not None:
                original = seen_hashes.get(file_hash) or (existing['filename'] if existing else filename)
                result.append({
                    'filename': filename,
                    'file_hash': file_hash,
                    'file_size_bytes': len(file_bytes),
                    'status': 'duplicate_skipped',
                    'is_duplicate': True,
                    'original_filename': original,
                })
            else:
                seen_hashes[file_hash] = filename
                result.append({
                    'filename': filename,
                    'file_hash': file_hash,
                    'file_size_bytes': len(file_bytes),
                    'status': 'uploading',
                    'is_duplicate': False,
                    'original_filename': None,
                })

        return result

    # ── B3.1: Bridge 1 + B3.5 + B3.6: refresh_batch ──────────────────────────

    async def refresh_batch(
        self, batch_id: str, tenant_id: str | uuid.UUID
    ) -> dict[str, Any]:
        """Update the status of all items in a batch.

        For each item:
        1. status='uploaded': GET task_status from Paperless
           - SUCCESS → paperless_document_id set, status='processing'
           - FAILURE → status='error'
           - PENDING/STARTED >30min → status='stuck_timeout'
           - PENDING/STARTED <30min → no change
        2. status='processing': check if Bridge 2 already fired (case_id set → completed)
           OR webhook fallback: check case_documents directly.
        3. After loop: if is_batch_ready_for_reevaluate AND batch not yet completed → trigger.

        Returns: {total, uploading, uploaded, processing, completed, error, stuck}
        """
        tid = str(tenant_id)
        batch_data = await self.bulk_repo.get_batch_with_items(batch_id, tid)
        if batch_data is None:
            raise ValueError(f'Batch {batch_id} not found for tenant {tid}')

        items = batch_data.get('items', [])
        counts: dict[str, int] = {
            'total': len(items),
            'uploading': 0,
            'uploaded': 0,
            'processing': 0,
            'completed': 0,
            'error': 0,
            'stuck': 0,
            'duplicate_skipped': 0,
        }

        for item in items:
            status = item['status']

            if status == 'uploaded':
                # Bridge 1: check Paperless task status
                task_id = item.get('paperless_task_id')
                if task_id:
                    try:
                        task = await self.paperless.get_task_status(task_id)
                        task_status = task.get('status', 'PENDING')

                        if task_status == 'SUCCESS':
                            doc_id = task.get('related_document')
                            if doc_id:
                                await self.bulk_repo.update_item_paperless_doc(item['id'], doc_id)
                            await self.bulk_repo.update_item_status(item['id'], 'processing')
                            counts['processing'] += 1
                            await self._audit('BULK_ITEM_BRIDGE1_COMPLETED', item, {
                                'paperless_document_id': doc_id,
                            })
                        elif task_status == 'FAILURE':
                            error_msg = task.get('result') or 'Paperless processing failed.'
                            await self.bulk_repo.update_item_status(
                                item['id'], 'error', error_message=error_msg
                            )
                            counts['error'] += 1
                        else:
                            # PENDING or STARTED — check for stuck (B3.5)
                            stuck = await self.bulk_repo.get_stuck_items(
                                batch_id, _STUCK_TIMEOUT_MINUTES
                            )
                            stuck_ids = {s['id'] for s in stuck}
                            if item['id'] in stuck_ids:
                                await self.bulk_repo.update_item_status(
                                    item['id'], 'stuck_timeout',
                                    error_message=(
                                        'Paperless-Task hat nach 30 Minuten nicht geantwortet. '
                                        'Bitte prüfe das Dokument manuell in Paperless.'
                                    ),
                                )
                                counts['stuck'] += 1
                            else:
                                counts['uploaded'] += 1
                    except Exception as exc:
                        logger.warning('Task status check failed for item %s: %s', item['id'], exc)
                        counts['uploaded'] += 1
                else:
                    counts['uploaded'] += 1

            elif status == 'processing':
                # Check if Bridge 2 already set case_id
                if item.get('case_id'):
                    await self.bulk_repo.update_item_status(item['id'], 'completed')
                    counts['completed'] += 1
                else:
                    # B3.6: Webhook fallback — check case_documents directly
                    doc_id = item.get('paperless_document_id')
                    if doc_id:
                        found = await self.bulk_repo.find_case_documents_by_paperless_doc(
                            tenant_id, doc_id
                        )
                        if found:
                            await self.bulk_repo.update_item_case(
                                item['id'],
                                case_id=found['case_id'],
                                confidence='CERTAIN',
                            )
                            await self.bulk_repo.update_item_status(item['id'], 'completed')
                            counts['completed'] += 1
                            await self._audit('BULK_ITEM_WEBHOOK_FALLBACK', item, {
                                'case_id': found['case_id'],
                                'paperless_document_id': doc_id,
                            })
                        else:
                            counts['processing'] += 1
                    else:
                        counts['processing'] += 1

            else:
                counts[status] = counts.get(status, 0) + 1

        # After loop: check if batch is ready for re-evaluate
        batch_status = batch_data.get('status', '')
        if batch_status not in ('completed', 'completed_with_errors', 'reevaluating'):
            ready = await self.bulk_repo.is_batch_ready_for_reevaluate(batch_id)
            if ready:
                await self.trigger_reevaluate(batch_id, tenant_id)

        return counts

    # ── B3.3: Re-Evaluate Orphans ─────────────────────────────────────────────

    async def trigger_reevaluate(
        self, batch_id: str, tenant_id: str | uuid.UUID
    ) -> dict[str, Any]:
        """Second pass: re-assign orphan items after batch completion.

        Strategy for doc_data:
          When Bridge 2 fires, it stores the full document analysis payload in
          document_upload_items.metadata['doc_data']. We read it here to re-run
          CaseAssignmentEngine without re-running the Document Analyst (OCR).
          If doc_data is absent (item never hit Bridge 2), we skip re-evaluation
          for that item — it stays as orphan for manual assignment.

        Steps:
          1. batch.status = 'reevaluating'
          2. Get orphan items (completed + no case_id, or error)
          3. For each orphan with doc_data: re-run assign_document_to_case
          4. Check for duplicate case proposals (same vendor, new DRAFTs)
          5. batch.status = 'completed' or 'completed_with_errors'
          6. Audit event BULK_REEVALUATE_COMPLETED
        """
        from app.case_engine.assignment import CaseAssignmentEngine, DocumentData

        tid = str(tenant_id)
        await self.bulk_repo.update_batch_status(batch_id, 'reevaluating')

        orphans = await self.bulk_repo.get_orphan_items(batch_id)
        reassigned = 0
        still_orphaned = 0
        new_draft_cases: list[dict] = []  # {case_id, vendor_name, item_id}

        engine = CaseAssignmentEngine(self.case_repo)

        for orphan in orphans:
            doc_data = (orphan.get('metadata') or {}).get('doc_data')
            if not doc_data:
                # No analysis data available → skip, stays as orphan
                still_orphaned += 1
                continue

            # Reconstruct DocumentData from stored doc_data
            ref_values = doc_data.get('reference_values', [])
            # reference_values stored as [[type, value], ...] or [(type, value), ...]
            typed_refs = [
                (rv[0], rv[1]) if isinstance(rv, (list, tuple)) and len(rv) == 2 else ('invoice_number', rv)
                for rv in ref_values
                if rv
            ]

            doc = DocumentData(
                document_source=doc_data.get('document_source', 'paperless'),
                document_source_id=doc_data.get('document_source_id', orphan['filename']),
                reference_values=typed_refs,
                vendor_name=doc_data.get('vendor_name'),
                total_amount=float(doc_data['total_amount']) if doc_data.get('total_amount') else None,
                currency=doc_data.get('currency', 'EUR'),
                document_date=None,
                filename=orphan['filename'],
            )

            try:
                tid_uuid = uuid.UUID(tid)
                assignment = await engine.assign_document(tid_uuid, doc)

                if assignment is not None:
                    await self.case_repo.add_document_to_case(
                        case_id=assignment.case_id,
                        document_source=doc.document_source,
                        document_source_id=doc.document_source_id,
                        assignment_confidence=assignment.confidence,
                        assignment_method=assignment.method,
                        filename=orphan['filename'],
                    )
                    await self.bulk_repo.update_item_case(
                        orphan['id'],
                        case_id=str(assignment.case_id),
                        confidence=assignment.confidence,
                    )
                    await self.bulk_repo.update_item_status(orphan['id'], 'completed')
                    reassigned += 1
                    await self._audit('CASE_REASSIGNMENT_VIA_REEVALUATE', orphan, {
                        'case_id': str(assignment.case_id),
                        'confidence': assignment.confidence,
                        'method': assignment.method,
                    })
                else:
                    # Still no match → create DRAFT for manual assignment
                    from app.case_engine.doc_analyst_integration import (
                        integrate_document_analysis,
                        map_reference_type,
                    )
                    typed_ref_mapped = [
                        (map_reference_type(t), v) for t, v in typed_refs
                    ]
                    result = await integrate_document_analysis(
                        tenant_id=tid_uuid,
                        event_source='paperless',
                        document_ref=doc.document_source_id,
                        document_type_value=doc_data.get('document_type'),
                        vendor_name=doc.vendor_name,
                        total_amount=None,
                        currency=doc.currency,
                        document_date=None,
                        due_date=None,
                        reference_values=typed_ref_mapped,
                        filename=orphan['filename'],
                        overall_confidence=0.5,
                        orchestration_case_id=f'reevaluate-{orphan["id"]}',
                        repo=self.case_repo,
                    )
                    new_case_id = result.get('case_id')
                    if result.get('created_draft') and new_case_id and doc.vendor_name:
                        new_draft_cases.append({
                            'case_id': new_case_id,
                            'vendor_name': doc.vendor_name,
                            'item_id': orphan['id'],
                        })
                    still_orphaned += 1

            except Exception as exc:
                logger.warning('Re-evaluate failed for item %s: %s', orphan['id'], exc)
                still_orphaned += 1

        # B3.3 step 4: detect duplicate case proposals
        merge_proposals = 0
        merge_proposals += await self._propose_duplicate_cases(new_draft_cases)

        # Determine final batch status
        final_status = 'completed' if still_orphaned == 0 else 'completed_with_errors'
        now = datetime.now(timezone.utc)
        await self.bulk_repo.update_batch_status(batch_id, final_status, completed_at=now)

        summary = {
            'reassigned': reassigned,
            'still_orphaned': still_orphaned,
            'merge_proposals': merge_proposals,
        }
        await self._audit('BULK_REEVALUATE_COMPLETED', {'batch_id': batch_id}, summary)
        return summary

    async def _propose_duplicate_cases(
        self, new_draft_cases: list[dict]
    ) -> int:
        """If 2+ items in batch each created a DRAFT with the same vendor_name → propose merge.

        Only PROPOSE — no auto-merge.
        """
        if len(new_draft_cases) < 2:
            return 0

        # Group by vendor_name
        by_vendor: dict[str, list[dict]] = {}
        for entry in new_draft_cases:
            vendor = (entry.get('vendor_name') or '').strip().lower()
            if vendor:
                by_vendor.setdefault(vendor, []).append(entry)

        proposals = 0
        for vendor, entries in by_vendor.items():
            if len(entries) < 2:
                continue
            # Create conflict proposals for all but the first case
            primary_case_id = uuid.UUID(entries[0]['case_id'])
            for dup in entries[1:]:
                try:
                    await self.case_repo.create_conflict(
                        case_id=primary_case_id,
                        conflict_type='duplicate_case',
                        description=(
                            f'Mögliches Duplikat: Case {dup["case_id"]} hat denselben '
                            f'Vendor "{vendor}" und wurde im gleichen Bulk-Upload erstellt.'
                        ),
                        metadata={
                            'duplicate_case_id': dup['case_id'],
                            'vendor_name': vendor,
                        },
                    )
                    proposals += 1
                except Exception as exc:
                    logger.warning('Failed to create duplicate_case conflict: %s', exc)

        return proposals

    # ── audit helper ───────────────────────────────────────────────────────────

    async def _audit(self, event_type: str, item: dict, details: dict) -> None:
        if self.audit_service is None:
            return
        try:
            await self.audit_service.log_event({
                'event_id': str(uuid.uuid4()),
                'case_id': str(item.get('batch_id', item.get('id', ''))),
                'source': 'bulk-upload',
                'agent_name': 'bulk-upload-service',
                'approval_status': 'NOT_REQUIRED',
                'action': event_type,
                'result': str(details),
                'llm_output': details,
            })
        except Exception as exc:
            logger.warning('Audit log failed for %s: %s', event_type, exc)
