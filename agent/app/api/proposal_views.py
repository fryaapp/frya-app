from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse

from app.auth.dependencies import require_operator
from app.dependencies import get_file_store
from app.memory.file_store import FileStore

router = APIRouter(prefix='/inspect/proposals', tags=['inspect'], dependencies=[Depends(require_operator)])


@router.get('', response_class=HTMLResponse)
async def proposals_view(file_store: FileStore = Depends(get_file_store)) -> str:
    files = file_store.list_files('system/proposals')
    links = ''.join(f"<li><a href='/inspect/proposals/{name}'>{name}</a></li>" for name in files)
    return f'<h1>System Proposals</h1><ul>{links}</ul>'


@router.get('/{file_name:path}', response_class=HTMLResponse)
async def proposal_detail(file_name: str, file_store: FileStore = Depends(get_file_store)) -> str:
    text = file_store.read_text(file_name)
    return f'<h1>{file_name}</h1><pre>{text}</pre>'
