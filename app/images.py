"""Card image intake: auto-crop, normalise orientation, cap size, make a thumb."""
import base64
import io
import os
import secrets

import cv2
import numpy as np
from PIL import Image, ImageOps

from . import autocrop as autocrop_mod
from .db import UPLOAD_DIR

MAX_EDGE = 1600
THUMB_EDGE = 600
PREVIEW_EDGE = 460
ALLOWED = {"JPEG", "PNG", "WEBP", "HEIF", "HEIC", "GIF", "BMP", "TIFF"}


def decode(raw_bytes):
    """Bytes -> upright RGB PIL image, or None if unreadable/unsupported."""
    try:
        img = Image.open(io.BytesIO(raw_bytes))
        if (img.format or "").upper() not in ALLOWED:
            return None
        return ImageOps.exif_transpose(img).convert("RGB")
    except Exception:
        return None


def _pil_to_bgr(img):
    return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)


def _bgr_to_pil(bgr):
    return Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))


def prepare(raw_bytes, auto_crop=True):
    """(PIL image, was_cropped). Finds and straightens the card when asked.

    Auto-crop fails safe: if no card-shaped quadrilateral is found, the whole
    photo comes back unchanged rather than a guess.
    """
    img = decode(raw_bytes)
    if img is None:
        return None, False
    if not auto_crop:
        return img, False
    try:
        cropped, did = autocrop_mod.autocrop(_pil_to_bgr(img))
    except Exception:
        return img, False
    return (_bgr_to_pil(cropped) if did else img), did


def save_card_image(raw_bytes, auto_crop=True):
    """Store a card photo. Returns (filename, was_cropped); ('', False) if bad."""
    if not raw_bytes:
        return "", False
    img, cropped = prepare(raw_bytes, auto_crop)
    if img is None:
        return "", False

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
    return name, cropped


def preview_data_url(img, edge=PREVIEW_EDGE):
    """A small inline JPEG, so the browser can show the crop before saving."""
    if img is None:
        return ""
    small = img.copy()
    small.thumbnail((edge, edge), Image.LANCZOS)
    buf = io.BytesIO()
    small.save(buf, "JPEG", quality=78, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def encode_jpeg(img, quality=92):
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality)
    return buf.getvalue()


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
