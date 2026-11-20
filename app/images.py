"""Card image intake: validate, normalise orientation, cap size, make a thumb."""
import io
import os
import secrets

from PIL import Image, ImageOps

from .db import UPLOAD_DIR

MAX_EDGE = 1600
THUMB_EDGE = 600
ALLOWED = {"JPEG", "PNG", "WEBP", "HEIF", "HEIC", "GIF", "BMP", "TIFF"}


def save_card_image(raw_bytes):
    """Store a card photo. Returns the stored filename, or '' if unusable."""
    if not raw_bytes:
        return ""
    try:
        img = Image.open(io.BytesIO(raw_bytes))
        fmt = (img.format or "").upper()
        if fmt not in ALLOWED:
            return ""
        img = ImageOps.exif_transpose(img).convert("RGB")
    except Exception:
        return ""

    os.makedirs(UPLOAD_DIR, exist_ok=True)
    stem = secrets.token_hex(8)
    name = f"{stem}.jpg"

    full = img.copy()
    full.thumbnail((MAX_EDGE, MAX_EDGE), Image.LANCZOS)
    full.save(os.path.join(UPLOAD_DIR, name), "JPEG", quality=88, optimize=True)

    thumb = img.copy()
    thumb.thumbnail((THUMB_EDGE, THUMB_EDGE), Image.LANCZOS)
    thumb.save(os.path.join(UPLOAD_DIR, f"{stem}_thumb.jpg"), "JPEG",
               quality=82, optimize=True)
    return name


def thumb_name(filename):
    if not filename:
        return ""
    stem, _ext = os.path.splitext(filename)
    candidate = f"{stem}_thumb.jpg"
    if os.path.exists(os.path.join(UPLOAD_DIR, candidate)):
        return candidate
    return filename


def delete_card_image(filename):
    if not filename:
        return
    stem, _ext = os.path.splitext(filename)
    for candidate in (filename, f"{stem}_thumb.jpg"):
        path = os.path.join(UPLOAD_DIR, candidate)
        # Keep deletes inside the upload dir even if a stray name shows up.
        if os.path.commonpath([os.path.abspath(path), os.path.abspath(UPLOAD_DIR)]) \
                != os.path.abspath(UPLOAD_DIR):
            continue
        if os.path.exists(path):
            os.remove(path)
