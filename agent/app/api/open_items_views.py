from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse

from app.auth.dependencies import require_operator
from app.dependencies import get_open_items_service
from app.open_items.service import OpenItemsService

router = APIRouter(prefix='/inspect/open-items', tags=['inspect'], dependencies=[Depends(require_operator)])


@router.get('', response_class=HTMLResponse)
async def open_items_view(
    status: str | None = Query(default=None),
    case_id: str | None = Query(default=None),
    service: OpenItemsService = Depends(get_open_items_service),
) -> str:
    if case_id:
        items = await service.list_by_case(case_id)
    else:
        items = await service.list_items(status=status)
    rows = ''.join(
        f"<tr><td>{x.item_id}</td><td>{x.case_id}</td><td>{x.status}</td><td>{x.title}</td><td>{x.document_ref or ''}</td><td>{x.accounting_ref or ''}</td><td>{x.updated_at}</td></tr>"
        for x in items
    )
    return (
        '<h1>Open Items</h1>'
        '<p>Persistiert in PostgreSQL; Redis nur fuer Job-Backbone.</p>'
        '<table border="1" cellpadding="6"><tr><th>ID</th><th>Case</th><th>Status</th><th>Titel</th><th>DokRef</th><th>AccRef</th><th>Aktualisiert</th></tr>'
        f'{rows}</table>'
    )


@router.get('/json')
async def open_items_json(
    status: str | None = Query(default=None),
    case_id: str | None = Query(default=None),
    service: OpenItemsService = Depends(get_open_items_service),
) -> list[dict]:
    if case_id:
        items = await service.list_by_case(case_id)
    else:
        items = await service.list_items(status=status)
    return [x.model_dump() for x in items]
