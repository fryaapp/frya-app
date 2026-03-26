"""P-50 TEIL 4: Activity Summary endpoint."""
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth.dependencies import require_authenticated
from app.auth.models import AuthUser

logger = logging.getLogger(__name__)
router = APIRouter(prefix='/api/v1', tags=['activity'])


async def _resolve_tenant_uuid() -> uuid.UUID:
    """Resolve the single-tenant UUID. Raises 503 if unavailable."""
    from app.case_engine.tenant_resolver import resolve_tenant_id
    tid = await resolve_tenant_id()
    if not tid:
        raise HTTPException(status_code=503, detail='tenant_unavailable')
    return uuid.UUID(tid)


def _build_summary_text(
    auto_booked: int,
    waiting_for_user: int,
    new_documents: int,
    new_deadlines: int,
    payments_received: int,
) -> str:
    """Build a short German summary text (no LLM)."""
    parts: list[str] = []
    if auto_booked > 0:
        parts.append(
            f"hab ich {auto_booked} Beleg{'e' if auto_booked > 1 else ''} "
            f"automatisch gebucht"
        )
    if waiting_for_user > 0:
        parts.append(f"{waiting_for_user} brauchen noch deine Freigabe")
    if new_deadlines > 0:
        parts.append(
            f"{new_deadlines} neue Frist{'en' if new_deadlines > 1 else ''}"
        )
    if payments_received > 0:
        parts.append(
            f"{payments_received} Zahlung{'en' if payments_received > 1 else ''} eingegangen"
        )
    if parts:
        return "Seit deinem letzten Besuch " + " und ".join(parts) + "."
    return "Alles ruhig seitdem."


@router.get('/activity-summary')
async def get_activity_summary(
    user: AuthUser = Depends(require_authenticated),
    since: str | None = Query(
        default=None,
        description='ISO datetime, e.g. 2026-03-24T00:00:00Z. Default: 24h ago.',
    ),
) -> dict:
    """Return an activity summary with counts and a human-readable text."""
    # Parse 'since' parameter.
    if since:
        try:
            since_dt = datetime.fromisoformat(since.replace('Z', '+00:00'))
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail='Invalid since parameter. Expected ISO datetime.',
            )
    else:
        since_dt = datetime.now(timezone.utc) - timedelta(hours=24)

    tenant_id = await _resolve_tenant_uuid()

    new_documents = 0
    auto_booked = 0
    waiting_for_user = 0
    new_deadlines = 0
    new_bookings = 0
    payments_received = 0

    # --- new_documents: audit events for document uploads since `since` ---
    try:
        from app.dependencies import get_audit_service
        audit_svc = get_audit_service()
        recent_events = await audit_svc.recent(limit=500)
        for ev in recent_events:
            if ev.created_at.tzinfo is None:
                ev_ts = ev.created_at.replace(tzinfo=timezone.utc)
            else:
                ev_ts = ev.created_at
            if ev_ts < since_dt:
                continue
            if ev.action in (
                'DOCUMENT_UPLOADED', 'BULK_UPLOAD', 'EMAIL_INTAKE',
                'AGENT_RUN_COMPLETED',
            ) and ev.source in ('upload', 'email', 'paperless', 'api', 'n8n'):
                new_documents += 1
    except Exception as exc:
        logger.warning('Activity: audit count failed: %s', exc)

    # --- auto_booked: cases that moved to BOOKED since `since` ---
    # --- waiting_for_user: cases in DRAFT/OPEN status ---
    try:
        from app.dependencies import get_case_repository
        case_repo = get_case_repository()
        all_cases = await case_repo.list_cases(tenant_id, limit=500)
        for c in all_cases:
            if c.status in ('DRAFT', 'OPEN'):
                waiting_for_user += 1
            if c.status == 'BOOKED' and c.updated_at >= since_dt.replace(tzinfo=None):
                auto_booked += 1
    except Exception as exc:
        logger.warning('Activity: case count failed: %s', exc)

    # --- new_bookings: bookings created since `since` ---
    try:
        from app.dependencies import get_accounting_repository
        acc_repo = get_accounting_repository()
        bookings = await acc_repo.list_bookings(
            tenant_id,
            date_from=since_dt.date() if hasattr(since_dt, 'date') else None,
        )
        new_bookings = len(bookings)
    except Exception as exc:
        logger.warning('Activity: bookings count failed: %s', exc)

    # --- new_deadlines: cases with due_date created/updated since `since` ---
    try:
        from app.dependencies import get_case_repository
        case_repo = get_case_repository()
        cases_with_deadline = await case_repo.list_cases(tenant_id, limit=500)
        for c in cases_with_deadline:
            if (
                c.due_date is not None
                and c.created_at >= since_dt.replace(tzinfo=None)
            ):
                new_deadlines += 1
    except Exception as exc:
        logger.warning('Activity: deadlines count failed: %s', exc)

    # --- payments_received: open items marked as paid since `since` ---
    try:
        from app.dependencies import get_accounting_repository
        acc_repo = get_accounting_repository()
        open_items = await acc_repo.list_open_items(tenant_id)
        since_date = since_dt.date() if hasattr(since_dt, 'date') else date.today()
        for item in open_items:
            if item.status == 'PAID':
                paid_at = getattr(item, 'updated_at', None) or getattr(item, 'paid_at', None)
                if paid_at is not None:
                    paid_date = paid_at.date() if hasattr(paid_at, 'date') else paid_at
                    if paid_date >= since_date:
                        payments_received += 1
    except Exception as exc:
        logger.warning('Activity: payments count failed: %s', exc)

    summary_text = _build_summary_text(
        auto_booked=auto_booked,
        waiting_for_user=waiting_for_user,
        new_documents=new_documents,
        new_deadlines=new_deadlines,
        payments_received=payments_received,
    )

    return {
        'since': since_dt.isoformat(),
        'new_documents': new_documents,
        'auto_booked': auto_booked,
        'waiting_for_user': waiting_for_user,
        'new_deadlines': new_deadlines,
        'payments_received': payments_received,
        'new_bookings': new_bookings,
        'summary_text': summary_text,
    }
