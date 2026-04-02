"""Invoice template preview + selection + logo upload API endpoints."""
from __future__ import annotations

import base64
import logging
from io import BytesIO

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from app.auth.dependencies import require_authenticated
from app.auth.models import AuthUser

logger = logging.getLogger(__name__)

router = APIRouter(prefix='/api/v1/invoice-templates', tags=['templates'])


async def _resolve_tenant_id(user=None) -> str:
    if user and getattr(user, 'tenant_id', None):
        return str(user.tenant_id)
    from app.case_engine.tenant_resolver import resolve_tenant_id
    tid = await resolve_tenant_id()
    return tid or 'default'


@router.get('/{template_name}/preview')
async def get_template_preview(
    template_name: str,
    user: AuthUser = Depends(require_authenticated),
) -> Response:
    """Generate a sample invoice PDF for template preview."""
    from app.pdf.template_registry import (
        TEMPLATES, get_company_data_for_template,
        get_company_logo_b64, render_preview_pdf,
    )

    if template_name not in TEMPLATES:
        raise HTTPException(404, f"Template '{template_name}' nicht gefunden")

    tenant_id = await _resolve_tenant_id(user)
    company_data = await get_company_data_for_template(user.username, tenant_id)
    logo_b64 = await get_company_logo_b64(user.username, tenant_id)

    # Check Kleinunternehmer status
    kleinunternehmer = False
    try:
        import asyncpg
        from app.dependencies import get_settings
        conn = await asyncpg.connect(get_settings().database_url)
        try:
            row = await conn.fetchrow(
                "SELECT value FROM frya_user_preferences "
                "WHERE tenant_id = $1 AND key = 'kleinunternehmer'",
                tenant_id,
            )
            kleinunternehmer = row and row['value'] == 'true'
        finally:
            await conn.close()
    except Exception:
        pass

    try:
        pdf_bytes = await render_preview_pdf(
            template_name, company_data,
            logo_b64=logo_b64, kleinunternehmer=kleinunternehmer,
        )
    except Exception as exc:
        logger.error('Template preview generation failed: %s', exc)
        raise HTTPException(500, f'PDF-Generierung fehlgeschlagen: {exc}')

    return Response(
        content=pdf_bytes,
        media_type='application/pdf',
        headers={'Content-Disposition': f'inline; filename="preview-{template_name}.pdf"'},
    )


@router.get('/')
async def list_templates(
    user: AuthUser = Depends(require_authenticated),
) -> dict:
    """List available invoice templates."""
    from app.pdf.template_registry import TEMPLATES

    items = []
    for key, info in TEMPLATES.items():
        items.append({
            'key': key,
            'title': info['title'],
            'subtitle': info['subtitle'],
            'badge': info.get('badge'),
            'preview_url': f'/api/v1/invoice-templates/{key}/preview',
        })
    return {'templates': items}


class SetTemplateRequest(BaseModel):
    template: str


@router.post('/select')
async def select_template(
    body: SetTemplateRequest,
    user: AuthUser = Depends(require_authenticated),
) -> dict:
    """Set the user's preferred invoice template."""
    from app.pdf.template_registry import TEMPLATES

    if body.template not in TEMPLATES:
        raise HTTPException(400, f"Unbekanntes Template: '{body.template}'")

    tenant_id = await _resolve_tenant_id(user)

    try:
        import asyncpg
        from app.dependencies import get_settings
        conn = await asyncpg.connect(get_settings().database_url)
        try:
            await conn.execute(
                """INSERT INTO frya_user_preferences (tenant_id, user_id, key, value, updated_at)
                   VALUES ($1, $2, 'invoice_template', $3, NOW())
                   ON CONFLICT (tenant_id, user_id, key) DO UPDATE
                     SET value = EXCLUDED.value, updated_at = NOW()""",
                tenant_id, user.username, body.template,
            )
        finally:
            await conn.close()
    except Exception as exc:
        logger.error('Failed to save template preference: %s', exc)
        raise HTTPException(500, 'Template-Einstellung konnte nicht gespeichert werden.')

    title = TEMPLATES[body.template]['title']
    return {
        'status': 'ok',
        'template': body.template,
        'message': f'Rechnungs-Template auf "{title}" geaendert.',
    }


# ---------------------------------------------------------------------------
# Logo Upload
# ---------------------------------------------------------------------------

_LOGO_MAX_BYTES = 5 * 1024 * 1024  # 5 MB
_LOGO_MAX_WIDTH = 400
_LOGO_ALLOWED_TYPES = {'image/png', 'image/jpeg', 'image/svg+xml', 'image/webp'}


def _process_logo(file_bytes: bytes, content_type: str) -> bytes:
    """Process uploaded logo: strip EXIF, resize, convert to PNG."""
    if content_type == 'image/svg+xml':
        # SVG: store as-is (can't resize with PIL)
        return file_bytes

    from PIL import Image

    img = Image.open(BytesIO(file_bytes))

    # Strip EXIF by rebuilding the image
    data = list(img.getdata())
    clean = Image.new(img.mode, img.size)
    clean.putdata(data)
    img = clean

    # Preserve transparency for PNG/WebP
    if img.mode == 'RGBA':
        pass
    elif img.mode != 'RGB':
        img = img.convert('RGBA')

    # Resize: max 400px wide, proportional
    if img.width > _LOGO_MAX_WIDTH:
        ratio = _LOGO_MAX_WIDTH / img.width
        new_h = int(img.height * ratio)
        img = img.resize((_LOGO_MAX_WIDTH, new_h), Image.LANCZOS)

    # Save as PNG
    buf = BytesIO()
    img.save(buf, format='PNG', optimize=True)
    return buf.getvalue()


@router.post('/logo')
async def upload_logo(
    file: UploadFile,
    user: AuthUser = Depends(require_authenticated),
) -> dict:
    """Upload a company logo for invoice PDFs."""
    if not file.content_type or file.content_type not in _LOGO_ALLOWED_TYPES:
        raise HTTPException(400, 'Nur PNG, JPG, SVG oder WebP erlaubt.')

    content = await file.read()
    if len(content) > _LOGO_MAX_BYTES:
        raise HTTPException(400, 'Logo zu gross (max 5 MB).')

    try:
        processed = _process_logo(content, file.content_type)
    except Exception as exc:
        logger.error('Logo processing failed: %s', exc)
        raise HTTPException(400, f'Logo konnte nicht verarbeitet werden: {exc}')

    # Store as base64 in preferences
    logo_b64 = base64.b64encode(processed).decode('utf-8')
    tenant_id = await _resolve_tenant_id(user)

    try:
        import asyncpg
        from app.dependencies import get_settings
        conn = await asyncpg.connect(get_settings().database_url)
        try:
            await conn.execute(
                """INSERT INTO frya_user_preferences (tenant_id, user_id, key, value, updated_at)
                   VALUES ($1, $2, 'company_logo_b64', $3, NOW())
                   ON CONFLICT (tenant_id, user_id, key) DO UPDATE
                     SET value = EXCLUDED.value, updated_at = NOW()""",
                tenant_id, user.username, logo_b64,
            )
        finally:
            await conn.close()
    except Exception as exc:
        logger.error('Failed to save logo: %s', exc)
        raise HTTPException(500, 'Logo konnte nicht gespeichert werden.')

    # Generate preview with logo
    from app.pdf.template_registry import (
        TEMPLATES, get_company_data_for_template, render_preview_pdf,
    )
    # Get user's selected template
    template_name = 'clean'
    try:
        import asyncpg as _apg
        from app.dependencies import get_settings as _gs
        _conn = await _apg.connect(_gs().database_url)
        try:
            _r = await _conn.fetchrow(
                "SELECT value FROM frya_user_preferences "
                "WHERE tenant_id = $1 AND key = 'invoice_template'",
                tenant_id,
            )
            if _r and _r['value'] in TEMPLATES:
                template_name = _r['value']
        finally:
            _conn.close()
    except Exception:
        pass

    return {
        'status': 'ok',
        'message': 'Logo gespeichert!',
        'preview_url': f'/api/v1/invoice-templates/{template_name}/preview',
        'content_blocks': [{
            'block_type': 'document',
            'data': {
                'title': 'Rechnungs-Vorschau mit Logo',
                'url': f'/api/v1/invoice-templates/{template_name}/preview',
                'format': 'PDF',
            },
        }],
        'actions': [
            {'label': 'Sieht gut aus!', 'chat_text': 'Logo passt!', 'style': 'primary'},
            {'label': 'Anderes Logo', 'chat_text': 'Anderes Logo hochladen', 'style': 'text'},
        ],
    }


@router.delete('/logo')
async def delete_logo(
    user: AuthUser = Depends(require_authenticated),
) -> dict:
    """Delete the company logo."""
    tenant_id = await _resolve_tenant_id(user)
    try:
        import asyncpg
        from app.dependencies import get_settings
        conn = await asyncpg.connect(get_settings().database_url)
        try:
            await conn.execute(
                "DELETE FROM frya_user_preferences "
                "WHERE tenant_id = $1 AND key = 'company_logo_b64'",
                tenant_id,
            )
        finally:
            await conn.close()
    except Exception as exc:
        logger.error('Failed to delete logo: %s', exc)
        raise HTTPException(500, 'Logo konnte nicht geloescht werden.')

    return {'status': 'ok', 'message': 'Logo entfernt.'}
