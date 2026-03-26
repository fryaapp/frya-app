"""E-Rechnung API: parse ZUGFeRD/XRechnung + generate ZUGFeRD PDF / XRechnung XML."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response

logger = logging.getLogger(__name__)

from app.auth.dependencies import require_operator
from app.auth.models import AuthUser
from app.e_invoice.parser import EInvoiceData, detect_e_invoice, parse_xrechnung, parse_zugferd

router = APIRouter(prefix='/api/e-invoice', tags=['e-invoice'])


@router.post('/parse', response_model=EInvoiceData)
async def parse_e_invoice(
    file: UploadFile = File(...),
    _user: AuthUser = Depends(require_operator),
) -> EInvoiceData:
    """Upload a ZUGFeRD PDF or XRechnung XML — returns structured EInvoiceData."""
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail='Leere Datei.')

    detected = detect_e_invoice(content)
    if detected is None:
        raise HTTPException(
            status_code=422,
            detail='Keine E-Rechnung erkannt (kein ZUGFeRD-PDF oder XRechnung-XML).',
        )

    try:
        if content[:4] == b'%PDF':
            return parse_zugferd(content)
        return parse_xrechnung(content)
    except ImportError as exc:
        logger.warning('E-invoice parse failed (missing library): %s', exc)
        raise HTTPException(status_code=503, detail='Erforderliche Bibliothek nicht installiert.') from exc
    except ValueError as exc:
        # ValueError from parser = user-facing parse error (malformed XML etc.) — safe to show
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post('/generate-zugferd')
async def generate_zugferd(
    invoice_data: EInvoiceData,
    _user: AuthUser = Depends(require_operator),
) -> Response:
    """Generate a ZUGFeRD-compliant PDF with embedded CII XML (BASIC profile)."""
    try:
        from app.e_invoice.generator import generate_zugferd_pdf
        pdf_bytes = generate_zugferd_pdf(invoice_data)
    except ImportError as exc:
        logger.warning('ZUGFeRD generation failed (missing library): %s', exc)
        raise HTTPException(status_code=503, detail='factur-x Bibliothek nicht installiert.') from exc
    except Exception as exc:
        logger.exception('ZUGFeRD generation failed for invoice %s', invoice_data.invoice_number)
        raise HTTPException(status_code=500, detail='ZUGFeRD-Generierung fehlgeschlagen.') from exc

    filename = f'rechnung-{invoice_data.invoice_number or "export"}.pdf'
    return Response(
        content=pdf_bytes,
        media_type='application/pdf',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'},
    )


@router.post('/generate-xrechnung')
async def generate_xrechnung(
    invoice_data: EInvoiceData,
    _user: AuthUser = Depends(require_operator),
) -> Response:
    """Generate XRechnung CII XML (EN 16931 / Factur-X BASIC profile)."""
    try:
        from app.e_invoice.generator import generate_xrechnung_xml
        xml_bytes = generate_xrechnung_xml(invoice_data)
    except Exception as exc:
        logger.exception('XRechnung generation failed for invoice %s', invoice_data.invoice_number)
        raise HTTPException(status_code=500, detail='XRechnung-Generierung fehlgeschlagen.') from exc

    filename = f'xrechnung-{invoice_data.invoice_number or "export"}.xml'
    return Response(
        content=xml_bytes,
        media_type='application/xml',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'},
    )
