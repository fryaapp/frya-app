from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, HTMLResponse

from app.auth.dependencies import require_operator
from app.config import get_settings
from app.dependencies import get_file_store
from app.memory.file_store import FileStore

router = APIRouter(prefix='/inspect/verfahrensdoku', tags=['inspect'], dependencies=[Depends(require_operator)])


@router.get('', response_class=HTMLResponse)
async def list_docs(file_store: FileStore = Depends(get_file_store)) -> str:
    files = file_store.list_files('verfahrensdoku')
    items = ''.join(f"<li><a href='/inspect/verfahrensdoku/{f.split('/')[-1]}'>{f}</a></li>" for f in files)
    return f'<h1>Verfahrensdokumentation</h1><ul>{items}</ul>'


@router.get('/{file_name}')
async def download_doc(file_name: str):
    settings = get_settings()
    base_dir = settings.verfahrensdoku_dir.resolve()
    target = (base_dir / file_name).resolve()
    if not target.is_relative_to(base_dir):
        raise HTTPException(status_code=400, detail='Ungültiger Dateipfad')
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail='Dokument nicht gefunden')
    return FileResponse(path=target, filename=file_name, media_type='text/markdown')
