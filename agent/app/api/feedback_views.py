"""API endpoints for alpha feedback — Bug-Report-System."""
from __future__ import annotations

import base64
import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.auth.dependencies import require_authenticated, require_operator, require_admin
from app.auth.models import AuthUser
from app.config import get_settings
from app.feedback.repository import FeedbackRepository

logger = logging.getLogger(__name__)
router = APIRouter(prefix='/api/v1/feedback', tags=['feedback'])

SCREENSHOTS_DIR = Path('/app/data/bugreports')


def _get_repo() -> FeedbackRepository:
    return FeedbackRepository(get_settings().database_url)


async def _get_user_ids(user: AuthUser) -> tuple[str, str]:
    from app.dependencies import get_user_repository
    user_repo = get_user_repository()
    db_user = await user_repo.find_by_username(user.username)
    if db_user is None:
        raise HTTPException(status_code=404, detail='User not found in DB')
    if user and getattr(user, 'tenant_id', None):
        tenant_id = str(user.tenant_id)
    else:
        from app.case_engine.tenant_resolver import resolve_tenant_id
        tenant_id = await resolve_tenant_id()
    if tenant_id is None:
        raise HTTPException(status_code=404, detail='No tenant configured')
    return tenant_id, db_user.username


def _save_screenshot(screenshot_data: str, feedback_id: str) -> str | None:
    """Speichert Base64-Screenshot als JPEG-Datei. Gibt den relativen Pfad zurueck."""
    if not screenshot_data:
        return None
    try:
        SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
        if ',' in screenshot_data:
            raw_b64 = screenshot_data.split(',', 1)[1]
        else:
            raw_b64 = screenshot_data
        img_bytes = base64.b64decode(raw_b64)
        filename = f'{feedback_id}.jpg'
        filepath = SCREENSHOTS_DIR / filename
        filepath.write_bytes(img_bytes)
        logger.info('Screenshot saved: %s (%d bytes)', filepath, len(img_bytes))
        return f'/api/v1/feedback/screenshots/{filename}'
    except Exception as exc:
        logger.warning('Screenshot save failed: %s', exc)
        return None


def _load_screenshot_b64(feedback_id: str, item: dict) -> str | None:
    """Laedt Screenshot als Base64-Data-URI fuer Inline-Einbettung in HTML."""
    img_file = SCREENSHOTS_DIR / f'{feedback_id}.jpg'
    if img_file.exists():
        b64 = base64.b64encode(img_file.read_bytes()).decode('ascii')
        return f'data:image/jpeg;base64,{b64}'
    if item.get('screenshot_data'):
        return item['screenshot_data']
    return None


def _status_class(status: str) -> str:
    mapping = {'NEW': 's-new', 'IN_PROGRESS': 's-progress', 'RESOLVED': 's-resolved'}
    return mapping.get(str(status).upper(), 's-new')


def _status_label(status: str) -> str:
    mapping = {'NEW': 'Neu', 'IN_PROGRESS': 'In Bearbeitung', 'RESOLVED': 'Geloest'}
    return mapping.get(str(status).upper(), status)


def _fmt_dt(created) -> str:
    if hasattr(created, 'strftime'):
        return created.strftime('%d.%m.%Y %H:%M')
    return str(created)[:16] if created else '—'


# ---------------------------------------------------------------------------
# Shared PDF HTML builder
# ---------------------------------------------------------------------------

_PDF_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
@page { size: A4; margin: 0; }
body { font-family: 'Helvetica Neue', Arial, sans-serif; background: #fff; color: #1a1a2e; font-size: 13px; }
.header { background: #E87830; color: #fff; padding: 24px 32px; display: flex; align-items: center; justify-content: space-between; }
.header-logo { font-size: 30px; font-weight: 800; letter-spacing: -1.5px; line-height: 1; }
.header-right { text-align: right; }
.header-title { font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 3px; opacity: 0.9; }
.header-date { font-size: 11px; opacity: 0.75; margin-top: 3px; }
.cover-body { padding: 40px 32px; }
.cover-headline { font-size: 34px; font-weight: 800; color: #1a1a2e; letter-spacing: -1px; margin-bottom: 6px; }
.cover-sub { font-size: 14px; color: #999; margin-bottom: 32px; }
.stats-row { display: flex; gap: 14px; margin-bottom: 36px; }
.stat-card { background: #f8f9fa; border: 1px solid #e8e8e8; border-radius: 12px; padding: 18px 22px; flex: 1; text-align: center; }
.stat-num { font-size: 38px; font-weight: 800; color: #E87830; line-height: 1; }
.stat-lbl { font-size: 11px; color: #aaa; margin-top: 5px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; }
.toc { background: #f8f9fa; border-radius: 12px; border: 1px solid #e8e8e8; overflow: hidden; }
.toc-hd { background: #1a1a2e; color: #fff; padding: 9px 16px; font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 2px; }
.toc-row { display: flex; align-items: center; padding: 9px 16px; border-bottom: 1px solid #e8e8e8; gap: 10px; }
.toc-num { background: #E87830; color: #fff; font-size: 10px; font-weight: 700; padding: 2px 8px; border-radius: 10px; white-space: nowrap; }
.toc-desc { flex: 1; color: #333; font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.toc-user { font-size: 10px; color: #aaa; white-space: nowrap; }
.s-badge { font-size: 10px; font-weight: 700; padding: 2px 8px; border-radius: 10px; white-space: nowrap; text-transform: uppercase; letter-spacing: 0.3px; }
.s-new { background: #FFF3E0; color: #E65100; }
.s-progress { background: #E3F2FD; color: #1565C0; }
.s-resolved { background: #E8F5E9; color: #2E7D32; }
.bug-page { padding: 32px; page-break-before: always; }
.bug-header-row { display: flex; align-items: flex-start; gap: 14px; margin-bottom: 20px; padding-bottom: 16px; border-bottom: 2px solid #f0f0f0; }
.bug-badge { background: #E87830; color: #fff; font-size: 11px; font-weight: 800; padding: 5px 14px; border-radius: 20px; white-space: nowrap; margin-top: 3px; }
.bug-title { font-size: 18px; font-weight: 700; color: #1a1a2e; flex: 1; line-height: 1.3; }
.meta-block { background: #f8f9fa; border: 1px solid #e8e8e8; border-radius: 10px; overflow: hidden; margin-bottom: 18px; }
.meta-row { display: flex; border-bottom: 1px solid #e8e8e8; }
.meta-key { width: 110px; padding: 8px 14px; font-size: 11px; font-weight: 700; color: #aaa; text-transform: uppercase; letter-spacing: 0.5px; flex-shrink: 0; }
.meta-val { padding: 8px 14px; font-size: 12px; color: #333; word-break: break-all; }
.meta-val code { font-family: 'Courier New', monospace; font-size: 10px; background: #fff; padding: 1px 5px; border-radius: 3px; border: 1px solid #ddd; }
.section-lbl { font-size: 10px; font-weight: 700; color: #ccc; text-transform: uppercase; letter-spacing: 2px; margin-bottom: 7px; }
.desc-card { background: #fff8f3; border-left: 4px solid #E87830; border-radius: 0 10px 10px 0; padding: 14px 18px; font-size: 13px; line-height: 1.75; white-space: pre-wrap; word-break: break-word; color: #2d2d2d; margin-bottom: 18px; }
.sysinfo-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 5px 24px; background: #f8f9fa; border: 1px solid #e8e8e8; border-radius: 10px; padding: 12px 16px; margin-bottom: 18px; }
.si-item { font-size: 11px; }
.si-key { font-weight: 700; color: #aaa; }
.si-val { color: #444; word-break: break-all; }
.screenshot-wrap { margin-bottom: 18px; }
.screenshot-wrap img { max-width: 100%; border-radius: 10px; border: 1px solid #e0e0e0; box-shadow: 0 3px 14px rgba(0,0,0,0.1); display: block; }
.footer { background: #f8f9fa; border-top: 1px solid #e8e8e8; padding: 10px 32px; font-size: 10px; color: #ccc; display: flex; justify-content: space-between; position: fixed; bottom: 0; left: 0; right: 0; }
"""


def _build_single_bug_html(item: dict, feedback_id: str, bug_num: int = 1) -> str:
    """Baut das HTML fuer einen einzelnen Bug-Report-PDF."""
    import datetime
    now_str = datetime.datetime.now().strftime('%d.%m.%Y %H:%M')
    created_str = _fmt_dt(item.get('created_at'))
    status = item.get('status', 'NEW')
    description = item.get('description', '(leer)')
    user_id = item.get('user_id', '—')
    page = item.get('page') or '—'
    short_id = str(item['id'])[:8]

    # Screenshot
    screenshot_html = ''
    img_data = _load_screenshot_b64(feedback_id, item)
    if img_data:
        screenshot_html = f'''
        <div class="section-lbl">Screenshot</div>
        <div class="screenshot-wrap">
          <img src="{img_data}" alt="Screenshot">
        </div>'''

    # System info
    sysinfo_html = ''
    si = item.get('system_info')
    if si and isinstance(si, dict):
        rows = ''.join(
            f'<div class="si-item"><span class="si-key">{k}:</span> <span class="si-val">{v}</span></div>'
            for k, v in si.items()
        )
        sysinfo_html = f'''
        <div class="section-lbl">Systeminfos</div>
        <div class="sysinfo-grid">{rows}</div>'''

    title_preview = description[:80] + ('…' if len(description) > 80 else '')

    return f'''<!DOCTYPE html>
<html lang="de">
<head><meta charset="utf-8"><style>{_PDF_CSS}</style></head>
<body>
  <div class="header">
    <div class="header-logo">FRYA</div>
    <div class="header-right">
      <div class="header-title">Bug Report</div>
      <div class="header-date">{now_str}</div>
    </div>
  </div>

  <div class="bug-page" style="page-break-before: avoid;">
    <div class="bug-header-row">
      <div class="bug-badge">Bug #{bug_num:02d}</div>
      <div class="bug-title">{title_preview}</div>
      <span class="s-badge {_status_class(status)}">{_status_label(status)}</span>
    </div>

    <div class="meta-block">
      <div class="meta-row"><div class="meta-key">ID</div><div class="meta-val"><code>{item['id']}</code></div></div>
      <div class="meta-row"><div class="meta-key">User</div><div class="meta-val"><strong>{user_id}</strong></div></div>
      <div class="meta-row"><div class="meta-key">Seite</div><div class="meta-val">{page}</div></div>
      <div class="meta-row"><div class="meta-key" style="border-bottom:none;">Datum</div><div class="meta-val" style="border-bottom:none;">{created_str}</div></div>
    </div>

    <div class="section-lbl">Beschreibung</div>
    <div class="desc-card">{description}</div>

    {sysinfo_html}
    {screenshot_html}
  </div>

  <div class="footer">
    <span>FRYA Bug Report · {short_id}</span>
    <span>Generiert am {now_str}</span>
  </div>
</body>
</html>'''


def _build_multi_bug_html(items: list[dict], feedback_ids: list[str]) -> str:
    """Baut das HTML fuer einen mehrseitigen Bug-Report-Export (Cover + 1 Seite pro Bug)."""
    import datetime
    now_str = datetime.datetime.now().strftime('%d.%m.%Y %H:%M')

    count = len(items)
    count_new = sum(1 for i in items if str(i.get('status', 'NEW')).upper() == 'NEW')
    count_progress = sum(1 for i in items if str(i.get('status', '')).upper() == 'IN_PROGRESS')
    count_resolved = sum(1 for i in items if str(i.get('status', '')).upper() == 'RESOLVED')

    # Table of contents rows
    toc_rows = ''
    for idx, item in enumerate(items, 1):
        desc = item.get('description', '')[:60] + ('…' if len(item.get('description', '')) > 60 else '')
        status = item.get('status', 'NEW')
        user_id = item.get('user_id', '—')
        toc_rows += f'''
        <div class="toc-row">
          <span class="toc-num">#{idx:02d}</span>
          <span class="toc-desc">{desc}</span>
          <span class="toc-user">{user_id}</span>
          <span class="s-badge {_status_class(status)}">{_status_label(status)}</span>
        </div>'''

    # Cover page
    cover = f'''
  <!-- COVER PAGE -->
  <div style="min-height: 297mm; display: flex; flex-direction: column; page-break-after: always;">
    <div class="header">
      <div class="header-logo">FRYA</div>
      <div class="header-right">
        <div class="header-title">Bug Report Export</div>
        <div class="header-date">{now_str}</div>
      </div>
    </div>
    <div class="cover-body" style="flex: 1;">
      <div class="cover-headline">Bug Report</div>
      <div class="cover-sub">Alpha-Feedback Export — {now_str}</div>
      <div class="stats-row">
        <div class="stat-card">
          <div class="stat-num">{count}</div>
          <div class="stat-lbl">Gesamt</div>
        </div>
        <div class="stat-card">
          <div class="stat-num" style="color:#E65100;">{count_new}</div>
          <div class="stat-lbl">Neu</div>
        </div>
        <div class="stat-card">
          <div class="stat-num" style="color:#1565C0;">{count_progress}</div>
          <div class="stat-lbl">In Bearb.</div>
        </div>
        <div class="stat-card">
          <div class="stat-num" style="color:#2E7D32;">{count_resolved}</div>
          <div class="stat-lbl">Geloest</div>
        </div>
      </div>
      <div class="toc">
        <div class="toc-hd">Inhaltsverzeichnis</div>
        {toc_rows}
      </div>
    </div>
  </div>'''

    # Individual bug pages
    bug_pages = ''
    for idx, item in enumerate(items, 1):
        fid = str(item['id'])
        created_str = _fmt_dt(item.get('created_at'))
        status = item.get('status', 'NEW')
        description = item.get('description', '(leer)')
        user_id = item.get('user_id', '—')
        page = item.get('page') or '—'
        title_preview = description[:80] + ('…' if len(description) > 80 else '')

        # Screenshot
        screenshot_html = ''
        img_data = _load_screenshot_b64(fid, item)
        if img_data:
            screenshot_html = f'''
            <div class="section-lbl" style="margin-top:4px;">Screenshot</div>
            <div class="screenshot-wrap">
              <img src="{img_data}" alt="Screenshot Bug #{idx:02d}">
            </div>'''

        # System info
        sysinfo_html = ''
        si = item.get('system_info')
        if si and isinstance(si, dict):
            rows = ''.join(
                f'<div class="si-item"><span class="si-key">{k}:</span> <span class="si-val">{v}</span></div>'
                for k, v in si.items()
            )
            sysinfo_html = f'''
            <div class="section-lbl" style="margin-top:4px;">Systeminfos</div>
            <div class="sysinfo-grid">{rows}</div>'''

        bug_pages += f'''
  <!-- BUG #{idx:02d} -->
  <div class="bug-page">
    <div class="bug-header-row">
      <div class="bug-badge">Bug #{idx:02d}</div>
      <div class="bug-title">{title_preview}</div>
      <span class="s-badge {_status_class(status)}">{_status_label(status)}</span>
    </div>

    <div class="meta-block">
      <div class="meta-row"><div class="meta-key">ID</div><div class="meta-val"><code>{fid}</code></div></div>
      <div class="meta-row"><div class="meta-key">User</div><div class="meta-val"><strong>{user_id}</strong></div></div>
      <div class="meta-row"><div class="meta-key">Seite</div><div class="meta-val">{page}</div></div>
      <div class="meta-row"><div class="meta-key" style="border-bottom:none;">Datum</div><div class="meta-val" style="border-bottom:none;">{created_str}</div></div>
    </div>

    <div class="section-lbl">Beschreibung</div>
    <div class="desc-card">{description}</div>

    {sysinfo_html}
    {screenshot_html}
  </div>'''

    return f'''<!DOCTYPE html>
<html lang="de">
<head><meta charset="utf-8"><style>{_PDF_CSS}</style></head>
<body>
  {cover}
  {bug_pages}
  <div class="footer">
    <span>FRYA Bug Report Export</span>
    <span>Generiert am {now_str} · {count} Bug{"s" if count != 1 else ""}</span>
  </div>
</body>
</html>'''


async def _html_to_pdf(html: str) -> bytes:
    """Sendet HTML an Gotenberg und gibt PDF-Bytes zurueck."""
    import httpx
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                'http://frya-gotenberg:3000/forms/chromium/convert/html',
                files={'file': ('index.html', html.encode('utf-8'), 'text/html')},
                data={
                    'marginTop': '0',
                    'marginBottom': '0',
                    'marginLeft': '0',
                    'marginRight': '0',
                    'preferCssPageSize': 'true',
                },
            )
            resp.raise_for_status()
            return resp.content
    except Exception as exc:
        logger.error('Gotenberg PDF generation failed: %s', exc)
        raise HTTPException(status_code=502, detail=f'PDF-Generierung fehlgeschlagen: {exc}')


# ---------------------------------------------------------------------------
# POST /api/v1/feedback — Neues Feedback erstellen
# ---------------------------------------------------------------------------

class FeedbackCreate(BaseModel):
    text: str | None = None
    description: str | None = None
    current_page: str | None = None
    page: str | None = None
    screenshot: str | None = None
    system_info: dict | None = None

    @property
    def resolved_description(self) -> str:
        value = self.text or self.description
        if not value:
            raise ValueError('Either "text" or "description" must be provided')
        return value

    @property
    def resolved_page(self) -> str | None:
        return self.current_page or self.page


@router.post('', status_code=201)
async def create_feedback(
    body: FeedbackCreate,
    user: AuthUser = Depends(require_authenticated),
):
    tenant_id, user_id = await _get_user_ids(user)
    repo = _get_repo()
    description = body.resolved_description
    page = body.resolved_page
    feedback_id_pre = str(uuid.uuid4())
    screenshot_url = _save_screenshot(body.screenshot, feedback_id_pre)

    feedback_id = await repo.create(
        tenant_id=tenant_id,
        user_id=user_id,
        description=description,
        page=page,
        screenshot_path=screenshot_url,
        screenshot_data=None,
        system_info=body.system_info,
        feedback_id=feedback_id_pre,
    )

    try:
        from app.dependencies import get_telegram_connector
        from app.connectors.contracts import NotificationMessage
        settings = get_settings()
        chat_id = settings.telegram_default_chat_id
        if chat_id:
            text = (
                f'Neues Alpha-Feedback:\n'
                f'Seite: {page or "(unbekannt)"}\n'
                f'User: {user.username}\n'
                f'---\n'
                f'"{description[:200]}"'
            )
            connector = get_telegram_connector()
            await connector.send(NotificationMessage(target=chat_id, text=text))
    except Exception as exc:
        logger.warning('Feedback Telegram notification failed: %s', exc)

    return {'feedback_id': feedback_id}


# ---------------------------------------------------------------------------
# GET /screenshots/{filename}
# ---------------------------------------------------------------------------

@router.get('/screenshots/{filename}')
async def get_screenshot(filename: str):
    import re
    if not re.match(r'^[a-f0-9\-]+\.jpg$', filename):
        raise HTTPException(status_code=400, detail='Invalid filename')
    filepath = SCREENSHOTS_DIR / filename
    if not filepath.exists():
        raise HTTPException(status_code=404, detail='Screenshot not found')
    return FileResponse(filepath, media_type='image/jpeg')


# ---------------------------------------------------------------------------
# GET /api/v1/feedback — Liste (Admin)
# ---------------------------------------------------------------------------

@router.get('')
async def list_feedback(user: AuthUser = Depends(require_admin)):
    repo = _get_repo()
    items = await repo.list_all()
    return items


# ---------------------------------------------------------------------------
# Status-Update
# ---------------------------------------------------------------------------

class StatusUpdate(BaseModel):
    status: str


@router.get('/{feedback_id}')
async def get_feedback_detail(
    feedback_id: str,
    user: AuthUser = Depends(require_admin),
):
    repo = _get_repo()
    item = await repo.get_by_id(feedback_id)
    if not item:
        raise HTTPException(status_code=404, detail='Feedback not found')
    if item.get('created_at'):
        item['created_at'] = item['created_at'].isoformat()
    return item


@router.patch('/{feedback_id}')
async def update_feedback_status(
    feedback_id: str,
    body: StatusUpdate,
    user: AuthUser = Depends(require_admin),
):
    if body.status not in ('NEW', 'IN_PROGRESS', 'RESOLVED'):
        raise HTTPException(status_code=400, detail='Invalid status')
    repo = _get_repo()
    await repo.update_status(feedback_id, body.status)
    return {'feedback_id': feedback_id, 'status': body.status}


# ---------------------------------------------------------------------------
# GET /{feedback_id}/pdf — Einzelner Bug als PDF
# ---------------------------------------------------------------------------

@router.get('/{feedback_id}/pdf')
async def export_feedback_pdf(
    feedback_id: str,
    user: AuthUser = Depends(require_admin),
):
    """Exportiert einen einzelnen Bug-Report als professionelles PDF."""
    import re as _re
    if not _re.match(r'^[a-f0-9\-]+$', feedback_id):
        raise HTTPException(status_code=400, detail='Invalid feedback_id')

    repo = _get_repo()
    item = await repo.get_by_id(feedback_id)
    if not item:
        raise HTTPException(status_code=404, detail='Feedback not found')

    html = _build_single_bug_html(item, feedback_id, bug_num=1)
    pdf_bytes = await _html_to_pdf(html)

    from fastapi.responses import Response as _Response
    short_id = feedback_id[:8]
    return _Response(
        content=pdf_bytes,
        media_type='application/pdf',
        headers={'Content-Disposition': f'attachment; filename="bugreport-{short_id}.pdf"'},
    )


# ---------------------------------------------------------------------------
# POST /export — Legacy JSON-Export (rueckwaertskompatibel)
# ---------------------------------------------------------------------------

class ExportRequest(BaseModel):
    feedback_ids: list[str]


@router.post('/export')
async def export_feedback(
    body: ExportRequest,
    user: AuthUser = Depends(require_admin),
):
    """Legacy-Export als Markdown-JSON (fuer Claude-Analyse)."""
    repo = _get_repo()
    items = []
    for fid in body.feedback_ids:
        item = await repo.get_by_id(fid)
        if item:
            items.append(item)

    if not items:
        raise HTTPException(status_code=404, detail='No feedback items found')

    md_lines = [
        '# FRYA Bug-Report Export',
        f'Exportiert: {__import__("datetime").datetime.now().strftime("%d.%m.%Y %H:%M")}',
        f'Anzahl: {len(items)}',
        '',
        '---',
        '',
    ]

    screenshots = {}
    for i, item in enumerate(items, 1):
        created = item.get('created_at')
        if hasattr(created, 'strftime'):
            created = created.strftime('%d.%m.%Y %H:%M')
        else:
            created = str(created)[:16] if created else 'unbekannt'

        md_lines.append(f'## Bug #{i}: {item.get("description", "")[:80]}')
        md_lines.append('')
        md_lines.append(f'- **ID:** `{item["id"]}`')
        md_lines.append(f'- **User:** {item.get("user_id", "?")}')
        md_lines.append(f'- **Seite:** {item.get("page", "?")}')
        md_lines.append(f'- **Status:** {item.get("status", "?")}')
        md_lines.append(f'- **Datum:** {created}')
        md_lines.append('')
        md_lines.append('### Beschreibung')
        md_lines.append(item.get('description', '(leer)'))
        md_lines.append('')

        si = item.get('system_info')
        if si and isinstance(si, dict):
            md_lines.append('### Systeminfos')
            for k, v in si.items():
                md_lines.append(f'- **{k}:** {v}')
            md_lines.append('')

        screenshot_url = item.get('screenshot_path')
        if screenshot_url:
            settings = get_settings()
            full_url = f'{settings.app_base_url.rstrip("/").replace("app.", "api.")}{screenshot_url}'
            screenshots[f'screenshot_{i}'] = full_url
            md_lines.append('### Screenshot')
            md_lines.append(f'![Bug {i} Screenshot]({full_url})')
            md_lines.append('')

        md_lines.append('---')
        md_lines.append('')

    await repo.mark_exported(body.feedback_ids)

    return {
        'markdown': '\n'.join(md_lines),
        'screenshots': screenshots,
        'count': len(items),
        'exported_ids': body.feedback_ids,
    }


# ---------------------------------------------------------------------------
# POST /export/pdf — Professioneller PDF-Export (mehrseitig)
# ---------------------------------------------------------------------------

@router.post('/export/pdf')
async def export_feedback_pdf_bulk(
    body: ExportRequest,
    user: AuthUser = Depends(require_admin),
):
    """Exportiert mehrere Bug-Reports als ein professionelles mehrseitiges PDF.

    Cover-Seite mit Statistiken + Inhaltsverzeichnis, danach ein Bug pro Seite
    mit Metadaten, Beschreibung, Systeminfos und Screenshot (inline base64).
    """
    if not body.feedback_ids:
        raise HTTPException(status_code=400, detail='Keine Feedback-IDs angegeben.')

    repo = _get_repo()
    items = []
    for fid in body.feedback_ids:
        import re as _re
        if not _re.match(r'^[a-f0-9\-]+$', str(fid)):
            continue
        item = await repo.get_by_id(str(fid))
        if item:
            items.append(item)

    if not items:
        raise HTTPException(status_code=404, detail='Keine Feedback-Eintraege gefunden.')

    html = _build_multi_bug_html(items, body.feedback_ids)
    pdf_bytes = await _html_to_pdf(html)

    await repo.mark_exported(body.feedback_ids)

    import datetime
    date_str = datetime.datetime.now().strftime('%Y-%m-%d')
    from fastapi.responses import Response as _Response
    return _Response(
        content=pdf_bytes,
        media_type='application/pdf',
        headers={
            'Content-Disposition': f'attachment; filename="frya-bugreport-export-{date_str}.pdf"',
        },
    )
