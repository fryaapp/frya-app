"""Image preprocessing pipeline for GDPR-compliant document upload.

Every uploaded image is:
1. EXIF-rotated (apply orientation before stripping metadata)
2. EXIF-stripped (remove GPS, device info, all metadata)
3. Resized to max 2000px on the longest side
4. Compressed as JPEG 85%
5. Wrapped into an A4 PDF (image centered, 150 DPI)

PDFs pass through unchanged.
"""
from __future__ import annotations

import io
import logging
from pathlib import PurePosixPath

from PIL import Image, ImageOps

logger = logging.getLogger(__name__)

IMAGE_EXTENSIONS: frozenset[str] = frozenset({
    '.jpg', '.jpeg', '.png', '.heic', '.heif',
    '.webp', '.bmp', '.tiff', '.tif',
})

MAX_DIMENSION: int = 2000
JPEG_QUALITY: int = 85

# A4 at 150 DPI
_A4_WIDTH_PX = int(210 / 25.4 * 150)   # 1240
_A4_HEIGHT_PX = int(297 / 25.4 * 150)  # 1754


def is_image(filename: str) -> bool:
    """Return True if *filename* has a recognised image extension."""
    ext = PurePosixPath(filename).suffix.lower()
    return ext in IMAGE_EXTENSIONS


def process_image_to_pdf(
    image_bytes: bytes,
    filename: str,
) -> tuple[bytes, str]:
    """Convert an image to a GDPR-safe, optimised PDF.

    Returns:
        (pdf_bytes, new_filename)  where new_filename ends in ``.pdf``.
    """
    img = Image.open(io.BytesIO(image_bytes))

    # Step 1: apply EXIF rotation BEFORE stripping metadata
    img = _apply_exif_rotation(img)

    # Step 2: strip all EXIF / metadata
    img = _strip_exif(img)

    # Step 3: ensure RGB (PDF does not support RGBA / palette with alpha)
    if img.mode in ('RGBA', 'LA'):
        background = Image.new('RGB', img.size, (255, 255, 255))
        background.paste(img, mask=img.split()[-1])
        img = background
    elif img.mode != 'RGB':
        img = img.convert('RGB')

    # Step 4: resize — longest side <= MAX_DIMENSION
    w, h = img.size
    if max(w, h) > MAX_DIMENSION:
        ratio = MAX_DIMENSION / max(w, h)
        new_w = int(w * ratio)
        new_h = int(h * ratio)
        img = img.resize((new_w, new_h), Image.LANCZOS)

    # Step 5: compress as JPEG 85% into a temporary buffer
    jpeg_buf = io.BytesIO()
    img.save(jpeg_buf, format='JPEG', quality=JPEG_QUALITY, optimize=True)
    jpeg_buf.seek(0)
    img_jpeg = Image.open(jpeg_buf)

    # Step 6: wrap into A4 PDF
    pdf_bytes = _image_to_pdf(img_jpeg)

    # Build new filename
    stem = PurePosixPath(filename).stem
    new_filename = f'{stem}.pdf'

    logger.info(
        'Image preprocessed: %s -> %s (%d bytes -> %d bytes)',
        filename, new_filename, len(image_bytes), len(pdf_bytes),
    )

    return pdf_bytes, new_filename


def _apply_exif_rotation(img: Image.Image) -> Image.Image:
    """Apply EXIF orientation tag so the image is upright.

    Uses Pillow's ``ImageOps.exif_transpose`` which handles all 8
    orientation values and returns a copy without the orientation tag.
    """
    try:
        return ImageOps.exif_transpose(img) or img
    except Exception:
        return img


def _strip_exif(img: Image.Image) -> Image.Image:
    """Return a copy of *img* with ALL metadata removed.

    Creates a brand-new Image with only pixel data — no EXIF, IPTC,
    XMP, GPS, device info, or any other metadata survives.
    """
    data = list(img.getdata())
    clean = Image.new(img.mode, img.size)
    clean.putdata(data)
    return clean


def _image_to_pdf(img: Image.Image) -> bytes:
    """Render *img* centred on an A4 page and return PDF bytes.

    The image is placed at 150 DPI, centred both horizontally and
    vertically on the A4 canvas (white background).
    """
    # Create white A4 canvas
    canvas = Image.new('RGB', (_A4_WIDTH_PX, _A4_HEIGHT_PX), (255, 255, 255))

    # Scale image to fit within A4 with some margin (95% of page)
    max_w = int(_A4_WIDTH_PX * 0.95)
    max_h = int(_A4_HEIGHT_PX * 0.95)

    img_w, img_h = img.size
    if img_w > max_w or img_h > max_h:
        ratio = min(max_w / img_w, max_h / img_h)
        img = img.resize(
            (int(img_w * ratio), int(img_h * ratio)),
            Image.LANCZOS,
        )

    # Centre on canvas
    img_w, img_h = img.size
    x = (_A4_WIDTH_PX - img_w) // 2
    y = (_A4_HEIGHT_PX - img_h) // 2
    canvas.paste(img, (x, y))

    buf = io.BytesIO()
    canvas.save(buf, format='PDF', resolution=150.0)
    return buf.getvalue()
