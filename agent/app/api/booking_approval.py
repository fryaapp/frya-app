"""Booking approval API endpoints — channel-agnostic.

POST /api/v1/bookings/{case_id}/respond
    Body: {
        "approval_id": str,
        "decision": "APPROVE" | "REJECT" | "CORRECT" | "DEFER",
        "correction": {...} | null    # only for CORRECT
    }

Also handles Telegram inline keyboard callback queries via:
POST /api/v1/bookings/{case_id}/telegram-callback
    Body: { "approval_id": str, "callback_data": "APPROVE|REJECT|CORRECT|DEFER" }
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.approvals.service import ApprovalService
from app.audit.service import AuditService
from app.booking.approval_service import BookingApprovalService
from app.connectors.accounting_akaunting import AkauntingConnector
from app.dependencies import (
    get_approval_service,
    get_audit_service,
    get_open_items_service,
)
from app.open_items.service import OpenItemsService

router = APIRouter(prefix='/api/v1/bookings', tags=['booking-approval'])


def _get_booking_approval_service(
    approval_service: ApprovalService = Depends(get_approval_service),
    open_items_service: OpenItemsService = Depends(get_open_items_service),
    audit_service: AuditService = Depends(get_audit_service),
) -> BookingApprovalService:
    from app.dependencies import get_akaunting_connector
    return BookingApprovalService(
        approval_service=approval_service,
        open_items_service=open_items_service,
        audit_service=audit_service,
        akaunting_connector=get_akaunting_connector(),
    )


class BookingResponsePayload(BaseModel):
    approval_id: str
    decision: str  # APPROVE | REJECT | CORRECT | DEFER
    decided_by: str = 'user'
    correction: dict | None = None


@router.post('/{case_id}/respond')
async def respond_to_booking_proposal(
    case_id: str,
    payload: BookingResponsePayload,
    booking_approval_service: BookingApprovalService = Depends(_get_booking_approval_service),
) -> dict:
    """Process user response to a booking proposal.

    Works for all channels — Telegram, Browser, App.
    """
    result = await booking_approval_service.process_response(
        case_id=case_id,
        approval_id=payload.approval_id,
        decision_raw=payload.decision,
        decided_by=payload.decided_by,
        correction_payload=payload.correction,
        source='booking_approval_api',
    )
    if 'error' in result:
        raise HTTPException(status_code=404, detail=result['error'])
    return result


class TelegramCallbackPayload(BaseModel):
    approval_id: str
    callback_data: str  # "APPROVE" | "REJECT" | "CORRECT" | "DEFER"
    decided_by: str = 'user'


@router.post('/{case_id}/telegram-callback')
async def telegram_booking_callback(
    case_id: str,
    payload: TelegramCallbackPayload,
    booking_approval_service: BookingApprovalService = Depends(_get_booking_approval_service),
) -> dict:
    """Handle Telegram inline keyboard callback for booking approval."""
    result = await booking_approval_service.process_response(
        case_id=case_id,
        approval_id=payload.approval_id,
        decision_raw=payload.callback_data,
        decided_by=payload.decided_by,
        source='telegram_callback',
    )
    if 'error' in result:
        raise HTTPException(status_code=404, detail=result['error'])
    return result
