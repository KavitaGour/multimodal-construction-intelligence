"""Safe image loading/validation for uploads."""
from __future__ import annotations

import io
import os
from typing import Optional, Tuple

from PIL import Image, ImageOps, UnidentifiedImageError

from config import ALLOWED_IMAGE_EXTENSIONS, MAX_IMAGE_SIDE_PX, MAX_UPLOAD_MB


def load_image(filename: str, data: Optional[bytes]) -> Tuple[Optional[Image.Image], Optional[str]]:
    """Validate and open an uploaded image.

    Returns (PIL image or None, user-friendly error message or None).
    """
    ext = os.path.splitext(filename or "")[1].lower()
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        allowed = ", ".join(e.strip(".").upper() for e in ALLOWED_IMAGE_EXTENSIONS)
        return None, f"Unsupported file type '{ext or 'unknown'}'. Please upload one of: {allowed}."
    if not data:
        return None, "The uploaded file is empty. Please choose a valid image."
    if len(data) > MAX_UPLOAD_MB * 1024 * 1024:
        return None, f"File is larger than {MAX_UPLOAD_MB} MB. Please upload a smaller image."
    try:
        Image.open(io.BytesIO(data)).verify()  # detects truncated / corrupt files
        img = Image.open(io.BytesIO(data))
        img = ImageOps.exif_transpose(img).convert("RGB")
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError):
        return None, "This file could not be read as an image. It may be corrupted or not a real JPG/PNG."
    except Exception:  # pragma: no cover - defensive catch-all
        return None, "Unexpected problem while reading the image. Please try another file."
    if img.width < 32 or img.height < 32:
        return None, "Image is too small to analyse (minimum 32x32 pixels)."
    img.thumbnail((MAX_IMAGE_SIDE_PX, MAX_IMAGE_SIDE_PX))
    return img, None
