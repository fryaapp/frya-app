"""LLM-based OCR via LightOnOCR-2-1B (document_analyst agent).

Converts PDF pages to images and calls LightOnOCR via IONOS to extract
plain text. The returned text is then passed to document_analyst_semantic
(Mistral) for field classification — this forms the two-LLM pipeline:

  LightOnOCR (Stage 1) → raw text extraction from document image
  Mistral Semantic (Stage 2) → structured field classification

Used as fallback when ocr_text is absent or too short (< MIN_OCR_CHARS).
"""
from __future__ import annotations

import base64
import io
import logging
import os
from pathlib import Path

from litellm import acompletion

logger = logging.getLogger(__name__)

_LLM_TIMEOUT = float(os.environ.get('FRYA_LLM_TIMEOUT', '120'))

# Minimum OCR text length to consider it usable (below this → run LLM OCR)
MIN_OCR_CHARS = 80

_OCR_PROMPT = (
    'Extrahiere den vollständigen Text aus diesem Dokument. '
    'Gib NUR den extrahierten Text zurück — keine Erklärungen, '
    'keine Formatierung, kein Markdown.'
)


def _pdf_to_images_b64(pdf_bytes: bytes, max_pages: int = 3) -> list[str]:
    """Convert first `max_pages` PDF pages to base64-encoded PNG strings."""
    import fitz  # PyMuPDF

    doc = fitz.open(stream=pdf_bytes, filetype='pdf')
    images: list[str] = []
    for page_idx in range(min(len(doc), max_pages)):
        page = doc[page_idx]
        # 2× scale for readable OCR quality, clip to max 2000px wide
        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
        png_bytes = pix.tobytes('png')
        images.append(base64.b64encode(png_bytes).decode())
    doc.close()
    return images


async def run_lightocr(
    pdf_bytes: bytes,
    *,
    model: str,
    api_key: str | None,
    base_url: str | None,
    max_pages: int = 3,
) -> str:
    """Call LightOnOCR-2-1B to extract text from a PDF.

    Returns the extracted text or raises on hard failure.
    The caller should handle exceptions and fall back gracefully.
    """
    images_b64 = _pdf_to_images_b64(pdf_bytes, max_pages=max_pages)
    if not images_b64:
        raise ValueError('Could not render any PDF pages to images.')

    content: list[dict] = []
    for b64 in images_b64:
        content.append({
            'type': 'image_url',
            'image_url': {'url': f'data:image/png;base64,{b64}'},
        })
    content.append({'type': 'text', 'text': _OCR_PROMPT})

    call_kwargs: dict = {
        'model': model,
        'messages': [{'role': 'user', 'content': content}],
        'max_tokens': 2048,
        'temperature': 0.0,
        'timeout': _LLM_TIMEOUT,
    }
    if api_key:
        call_kwargs['api_key'] = api_key
    if base_url:
        call_kwargs['api_base'] = base_url

    completion = await acompletion(**call_kwargs)
    text = (completion.choices[0].message.content or '').strip()
    logger.info('LightOnOCR extracted %d chars from %d page(s)', len(text), len(images_b64))
    return text


def read_pdf_from_local_path(
    stored_relative_path: str | None,
    *,
    data_dir: str = '/app/data',
) -> bytes | None:
    """Read a PDF from the agent data volume by its stored relative path."""
    if not stored_relative_path:
        return None
    try:
        full = Path(data_dir) / stored_relative_path.lstrip('/')
        if full.exists() and full.is_file():
            return full.read_bytes()
    except Exception as exc:
        logger.debug('Could not read local PDF at %s: %s', stored_relative_path, exc)
    return None
