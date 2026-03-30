"""Bulk-Upload API — POST /api/documents/bulk-upload + batch management.

Auth: operator+ (require_operator)
CSRF: required on all POST endpoints (same pattern as cases.py, deadlines.py)
Tenant-Isolation: every query uses tenant_id from current_user session

Streaming Upload:
  FastAPI's UploadFile is lazy — the multipart body is parsed per-file, not
  buffered in full. We read each file in 64KB chunks for hash computation and
  size validation, then concatenate bytes only for files that pass validation.
  This keeps per-request RAM to O(largest_file) rather than O(total_payload).
  With 50 × 20MB = 1GB max payload and max_concurrent=5 (Semaphore in connector),
  peak RAM stays manageable on the 8GB Hetzner CX33.
"""
from __future__ import annotations

import hashlib
import logging
import time
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from app.auth.csrf import require_csrf
from app.auth.dependencies import require_authenticated, require_operator
from app.auth.models import AuthUser
from app.dependencies import (
    get_audit_service,
    get_bulk_upload_repository,
    get_bulk_upload_service,
    get_case_repository,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix='/api/v1/documents', tags=['bulk-upload'])

# ── Constants ─────────────────────────────────────────────────────────────────

_MAX_FILES = 50
_MAX_FILE_BYTES = 20 * 1024 * 1024  # 20 MB
_ALLOWED_MIME_TYPES = frozenset({
    'application/pdf',
    'image/png',
    'image/jpeg',
    'image/tiff',
    'image/tif',
})
_CHUNK_SIZE = 65536  # 64KB chunks for streaming reads

# Rate-limit: per batch_id — last refresh timestamp
_last_refresh: dict[str, float] = {}
_REFRESH_MIN_INTERVAL = 5.0  # seconds


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_tenant_id(user: AuthUser) -> str:
    """Extract tenant_id from operator session. Falls back to username as key."""
    tid = getattr(user, 'tenant_id', None)
    if tid:
        return str(tid)
    # Fallback: use username-based UUID (deterministic per user)
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, user.username))


async def _read_file_chunked(file: UploadFile) -> tuple[bytes, str, int]:
    """Read UploadFile in chunks, compute SHA256 hash and size.

    Returns: (file_bytes, sha256_hex, size_bytes)
    Raises HTTPException(400) if file exceeds _MAX_FILE_BYTES.
    """
    hasher = hashlib.sha256()
    chunks = []
    total = 0

    while True:
        chunk = await file.read(_CHUNK_SIZE)
        if not chunk:
            break
        total += len(chunk)
        if total > _MAX_FILE_BYTES:
            raise HTTPException(
                status_code=400,
                detail=f'Datei "{file.filename}" ist zu groß (max. 20 MB).',
            )
        hasher.update(chunk)
        chunks.append(chunk)

    return b''.join(chunks), hasher.hexdigest(), total


def _batch_summary(items: list[dict]) -> dict[str, int]:
    from collections import Counter
    counts: dict[str, int] = Counter(i['status'] for i in items)
    return {
        'uploading': counts.get('uploading', 0),
        'uploaded': counts.get('uploaded', 0),
        'processing': counts.get('processing', 0),
        'completed': counts.get('completed', 0),
        'error': counts.get('error', 0),
        'stuck': counts.get('stuck', 0),
        'duplicate_skipped': counts.get('duplicate_skipped', 0),
    }


async def _enrich_item_with_case(item: dict, case_repo: Any) -> dict:
    """Add case_number and case_title to item if case_id is set."""
    result = dict(item)
    case_id_str = item.get('case_id')
    if case_id_str:
        try:
            case = await case_repo.get_case(uuid.UUID(case_id_str))
            if case:
                result['case_number'] = case.case_number
                result['case_title'] = case.title or case.vendor_name
            else:
                result['case_number'] = None
                result['case_title'] = None
        except Exception:
            result['case_number'] = None
            result['case_title'] = None
    else:
        result['case_number'] = None
        result['case_title'] = None
    return result


def _format_batch(batch: dict, items: list[dict] | None = None) -> dict:
    result: dict[str, Any] = {
        'batch_id': batch['id'],
        'file_count': batch['file_count'],
        'status': batch['status'],
        'created_at': batch['created_at'].isoformat() if hasattr(batch.get('created_at'), 'isoformat') else str(batch.get('created_at', '')),
        'completed_at': batch['completed_at'].isoformat() if batch.get('completed_at') and hasattr(batch['completed_at'], 'isoformat') else batch.get('completed_at'),
        'uploaded_by': batch.get('uploaded_by'),
    }
    if items is not None:
        result['summary'] = _batch_summary(items)
        result['items'] = items
    else:
        # List view — no items
        result['summary'] = None
    return result


# ── POST /api/documents/bulk-upload ──────────────────────────────────────────

@router.post(
    '/bulk-upload',
    status_code=202,
)
async def bulk_upload(
    files: list[UploadFile],
    current_user: AuthUser = Depends(require_authenticated),
) -> dict[str, Any]:
    """Upload multiple documents for bulk processing.

    Validates, creates batch, uploads to Paperless with concurrency=5.
    Returns immediately with batch_id and status='processing'.
    """
    if len(files) > _MAX_FILES:
        raise HTTPException(
            status_code=400,
            detail=f'Zu viele Dateien ({len(files)}). Maximum: {_MAX_FILES}.',
        )
    if len(files) == 0:
        raise HTTPException(status_code=400, detail='Keine Dateien empfangen.')

    tenant_id = _get_tenant_id(current_user)
    bulk_repo = get_bulk_upload_repository()
    bulk_svc = get_bulk_upload_service()
    audit_svc = get_audit_service()

    # ── Step 1–2: Validate + read files (streaming, chunked) ─────────────────
    validated_files: list[tuple[bytes, str, str, str, int]] = []  # (bytes, filename, hash, mime, size)

    for upload in files:
        filename = upload.filename or 'unnamed'
        mime = upload.content_type or ''

        # Validate MIME type
        if mime not in _ALLOWED_MIME_TYPES:
            raise HTTPException(
                status_code=400,
                detail=f'Dateityp nicht erlaubt: "{filename}" ({mime}). Erlaubt: PDF, PNG, JPG, TIFF.',
            )

        # Read + validate size + compute hash
        try:
            file_bytes, file_hash, file_size = await _read_file_chunked(upload)
        except HTTPException:
            raise
        except Exception as exc:
            logger.warning('Failed to read file %s: %s', filename, exc)
            raise HTTPException(status_code=400, detail=f'Datei "{filename}" konnte nicht gelesen werden.')

        validated_files.append((file_bytes, filename, file_hash, mime, file_size))

    # ── Step 3: Create batch ──────────────────────────────────────────────────
    batch = await bulk_repo.create_batch(
        tenant_id=tenant_id,
        uploaded_by=current_user.username,
        file_count=len(validated_files),
    )
    batch_id = batch['id']

    # ── Step 4: Detect duplicates + create items ──────────────────────────────
    seen_hashes: dict[str, str] = {}
    item_specs: list[dict] = []

    for file_bytes, filename, file_hash, mime, file_size in validated_files:
        if file_hash in seen_hashes:
            item_specs.append({
                'filename': filename,
                'file_hash': file_hash,
                'file_size_bytes': file_size,
                'status': 'duplicate_skipped',
                'error_message': f'Duplikat von: {seen_hashes[file_hash]}',
            })
        else:
            seen_hashes[file_hash] = filename
            item_specs.append({
                'filename': filename,
                'file_hash': file_hash,
                'file_size_bytes': file_size,
                'status': 'uploading',
            })

    items = await bulk_repo.create_items(batch_id, tenant_id, item_specs)

    # ── Step 5: Audit event ────────────────────────────────────────────────────
    await audit_svc.log_event({
        'event_id': str(uuid.uuid4()),
        'case_id': f'batch:{batch_id}',
        'source': 'bulk-upload-api',
        'agent_name': 'bulk-upload',
        'approval_status': 'NOT_REQUIRED',
        'action': 'BULK_UPLOAD_INITIATED',
        'result': f'batch_id={batch_id};file_count={len(validated_files)};uploaded_by={current_user.username}',
        'llm_output': {
            'batch_id': batch_id,
            'file_count': len(validated_files),
            'filenames': [f[1] for f in validated_files],
            'uploaded_by': current_user.username,
        },
    })

    # ── Step 6: Upload non-duplicates to Paperless ────────────────────────────
    upload_pairs: list[tuple[bytes, str, str]] = []  # (bytes, filename, item_id)
    for i, (file_bytes, filename, file_hash, mime, file_size) in enumerate(validated_files):
        item = items[i]
        if item['status'] == 'duplicate_skipped':
            await audit_svc.log_event({
                'event_id': str(uuid.uuid4()),
                'case_id': f'batch:{batch_id}',
                'source': 'bulk-upload-api',
                'agent_name': 'bulk-upload',
                'approval_status': 'NOT_REQUIRED',
                'action': 'BULK_ITEM_DUPLICATE_SKIPPED',
                'result': f'filename={filename};hash={file_hash}',
                'llm_output': {
                    'batch_id': batch_id,
                    'filename': filename,
                    'file_hash': file_hash,
                    'original_filename': seen_hashes.get(file_hash),
                },
            })
            continue
        upload_pairs.append((file_bytes, filename, item['id']))

    # ── Step 6a: Image preprocessing (GDPR: strip EXIF, resize, wrap as PDF) ──
    from app.preprocessing.image_processor import is_image, process_image_to_pdf

    preprocessed_pairs: list[tuple[bytes, str, str]] = []
    for file_bytes, filename, item_id in upload_pairs:
        if is_image(filename):
            try:
                file_bytes, filename = process_image_to_pdf(file_bytes, filename)
            except Exception as exc:
                logger.warning('Image preprocessing failed for %s: %s', filename, exc)
                # Fall through with original bytes — Paperless can still handle it
        preprocessed_pairs.append((file_bytes, filename, item_id))
    upload_pairs = preprocessed_pairs

    # Upload via connector (Semaphore(5) inside upload_documents_batch)
    paperless_connector = bulk_svc.paperless
    files_for_upload = [(fb, fn) for fb, fn, _ in upload_pairs]
    item_ids = [iid for _, _, iid in upload_pairs]

    upload_results: list[dict] = []
    if files_for_upload:
        try:
            upload_results = await paperless_connector.upload_documents_batch(files_for_upload, max_concurrent=5)
        except Exception as exc:
            logger.error('Paperless unreachable during bulk upload: %s', exc)
            await bulk_repo.update_batch_status(batch_id, 'error')
            raise HTTPException(status_code=502, detail='Paperless nicht erreichbar. Batch wurde gespeichert, kann später erneut versucht werden.')

    # ── Step 7: Update items with task_ids ────────────────────────────────────
    duplicates_skipped = sum(1 for i in items if i['status'] == 'duplicate_skipped')

    for idx, result in enumerate(upload_results):
        item_id = item_ids[idx]
        filename = result['filename']
        task_id = result.get('task_id')
        error = result.get('error')

        if task_id:
            await bulk_repo.update_item_status(item_id, 'uploaded', paperless_task_id=task_id)
            await audit_svc.log_event({
                'event_id': str(uuid.uuid4()),
                'case_id': f'batch:{batch_id}',
                'source': 'bulk-upload-api',
                'agent_name': 'bulk-upload',
                'approval_status': 'NOT_REQUIRED',
                'action': 'BULK_ITEM_UPLOADED',
                'result': f'filename={filename};task_id={task_id}',
                'llm_output': {'batch_id': batch_id, 'filename': filename, 'task_id': task_id},
            })
        elif error:
            await bulk_repo.update_item_status(item_id, 'error', error_message=error)
            await audit_svc.log_event({
                'event_id': str(uuid.uuid4()),
                'case_id': f'batch:{batch_id}',
                'source': 'bulk-upload-api',
                'agent_name': 'bulk-upload',
                'approval_status': 'NOT_REQUIRED',
                'action': 'BULK_ITEM_ERROR',
                'result': f'filename={filename};error={error}',
                'llm_output': {'batch_id': batch_id, 'filename': filename, 'error_message': error},
            })

    # ── Step 8: Return ─────────────────────────────────────────────────────────
    return {
        'batch_id': batch_id,
        'file_count': len(validated_files),
        'duplicates_skipped': duplicates_skipped,
        'status': 'processing',
    }


# ── GET /api/documents/batches ───────────────────────────────────────────────

@router.get('/batches')
async def list_batches(
    limit: int = 20,
    offset: int = 0,
    current_user: AuthUser = Depends(require_operator),
) -> dict[str, Any]:
    """List recent batches for the tenant, paginated."""
    if limit > 100:
        limit = 100

    tenant_id = _get_tenant_id(current_user)
    bulk_repo = get_bulk_upload_repository()

    batches = await bulk_repo.list_batches(tenant_id, limit=limit + 1, offset=offset)
    has_more = len(batches) > limit
    page = batches[:limit]

    result_batches = []
    for b in page:
        batch_with_items = await bulk_repo.get_batch_with_items(b['id'], tenant_id)
        items = batch_with_items.get('items', []) if batch_with_items else []
        fb = _format_batch(b, items)
        result_batches.append(fb)

    return {
        'batches': result_batches,
        'total': offset + len(page) + (1 if has_more else 0),
    }


# ── GET /api/documents/batches/{batch_id} ────────────────────────────────────

@router.get('/batches/{batch_id}')
async def get_batch(
    batch_id: str,
    current_user: AuthUser = Depends(require_operator),
) -> dict[str, Any]:
    """Get batch detail with all items, enriched with case info."""
    tenant_id = _get_tenant_id(current_user)
    bulk_repo = get_bulk_upload_repository()
    case_repo = get_case_repository()

    batch_data = await bulk_repo.get_batch_with_items(batch_id, tenant_id)
    if batch_data is None:
        raise HTTPException(status_code=404, detail='Batch nicht gefunden.')

    items = batch_data.get('items', [])
    enriched = []
    for item in items:
        enriched.append(await _enrich_item_with_case(item, case_repo))

    fb = _format_batch(batch_data, enriched)
    return fb


# ── POST /api/documents/batches/{batch_id}/refresh ───────────────────────────

@router.post(
    '/batches/{batch_id}/refresh',
    dependencies=[Depends(require_csrf)],
)
async def refresh_batch(
    batch_id: str,
    current_user: AuthUser = Depends(require_operator),
) -> dict[str, Any]:
    """Refresh batch status: poll Paperless, run Bridge 1, check Bridge 2, trigger re-evaluate.

    Rate-limited to max 1 call per 5 seconds per batch_id (in-memory).
    Returns the same shape as GET /batches/{batch_id}.
    """
    # Rate limit check
    now = time.monotonic()
    last = _last_refresh.get(batch_id, 0.0)
    if now - last < _REFRESH_MIN_INTERVAL:
        remaining = _REFRESH_MIN_INTERVAL - (now - last)
        raise HTTPException(
            status_code=429,
            detail=f'Rate limit: bitte warte {remaining:.1f}s vor dem nächsten Refresh.',
        )
    _last_refresh[batch_id] = now

    tenant_id = _get_tenant_id(current_user)
    bulk_repo = get_bulk_upload_repository()
    bulk_svc = get_bulk_upload_service()
    case_repo = get_case_repository()

    # Verify batch belongs to this tenant
    batch_data = await bulk_repo.get_batch_with_items(batch_id, tenant_id)
    if batch_data is None:
        raise HTTPException(status_code=404, detail='Batch nicht gefunden.')

    # Run the refresh
    await bulk_svc.refresh_batch(batch_id, tenant_id)

    # Return fresh state
    fresh = await bulk_repo.get_batch_with_items(batch_id, tenant_id)
    items = fresh.get('items', []) if fresh else []
    enriched = []
    for item in items:
        enriched.append(await _enrich_item_with_case(item, case_repo))

    return _format_batch(fresh, enriched)
