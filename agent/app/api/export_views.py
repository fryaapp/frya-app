"""GoBD + DATEV export endpoints."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response

from app.auth.dependencies import require_admin
from app.auth.models import AuthUser
from app.config import get_settings
from app.dependencies import get_akaunting_connector
from app.export.gobd_service import GoBDExportService
from app.export.datev_service import DATEVExportService

router = APIRouter(prefix='/api/v1/export', tags=['export'])


@router.get('/gobd')
async def export_gobd(
    date_from: str = Query(..., description='Start-Datum YYYY-MM-DD'),
    date_to: str = Query(..., description='End-Datum YYYY-MM-DD'),
    _admin: AuthUser = Depends(require_admin),
):
    """GoBD-konformer GDPdU-Export als ZIP-Download."""
    settings = get_settings()
    akaunting = get_akaunting_connector()
    service = GoBDExportService(settings.database_url, akaunting)

    d_from = date.fromisoformat(date_from)
    d_to = date.fromisoformat(date_to)
    zip_bytes = await service.generate_export(d_from, d_to)

    filename = f'FRYA_GoBD_Export_{date_from}_{date_to}.zip'
    return Response(
        content=zip_bytes,
        media_type='application/zip',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'},
    )


@router.get('/datev')
async def export_datev(
    date_from: str = Query(..., description='Start-Datum YYYY-MM-DD'),
    date_to: str = Query(..., description='End-Datum YYYY-MM-DD'),
    berater_nr: str = Query('', description='DATEV Berater-Nummer'),
    mandant_nr: str = Query('', description='DATEV Mandanten-Nummer'),
    _admin: AuthUser = Depends(require_admin),
):
    """DATEV-Buchungsstapel als ZIP-Download."""
    akaunting = get_akaunting_connector()
    service = DATEVExportService(akaunting)

    d_from = date.fromisoformat(date_from)
    d_to = date.fromisoformat(date_to)
    zip_bytes = await service.generate_export(d_from, d_to, berater_nr, mandant_nr)

    filename = f'FRYA_DATEV_Export_{date_from}_{date_to}.zip'
    return Response(
        content=zip_bytes,
        media_type='application/zip',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'},
    )
