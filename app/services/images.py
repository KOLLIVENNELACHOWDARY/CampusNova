"""Complaint photo pipeline (Jahnavi). Uses OpenCV when it is installed, otherwise Pillow (same behaviour).
The Vercel deployment uses Pillow because OpenCV alone is ~150 MB of the 500 MB function size limit.

Untrusted bytes in, safe files out:
  1. size limits (non-empty, <= MAX_UPLOAD_MB)
  2. the file's *content* is sniffed from magic bytes (the client's filename / content-type are never trusted)
  3. OpenCV must be able to decode it (rejects truncated / corrupt / fake images) and the pixel count is capped
     (decompression-bomb guard)
  4. the image is re-encoded: that strips EXIF/GPS metadata and any appended payload; large images are downscaled
     to at most MAX_SIDE px; a JPEG thumbnail is made
  5. stored in the database (no disk needed, so it works on Vercel); the sha256 of the re-encoded image is stored so the
     same photo is not attached twice
"""
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import io

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.timeutil import utcnow
from app.models import Complaint, ComplaintImage
from app.services.common import BusinessRuleError, NotFoundError

try:  # optional: faster/stronger decoder when available
    import cv2
except ImportError:  # pragma: no cover - exercised by tests via _use_opencv
    cv2 = None
from PIL import Image, ImageOps

Image.MAX_IMAGE_PIXELS = None  # we enforce our own cap (MAX_PIXELS) *before* decoding pixels

MAX_SIDE = 1600
THUMB_SIDE = 320
MAX_PIXELS = 40_000_000
MAGIC = ((b"\xff\xd8\xff", "image/jpeg", ".jpg"), (b"\x89PNG\r\n\x1a\n", "image/png", ".png"))


class ImageRejected(BusinessRuleError):
    """The upload is not an acceptable image (maps to 400/413/415 in the API layer)."""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


@dataclass
class ProcessedImage:
    data: bytes
    thumb: bytes
    width: int
    height: int
    content_type: str
    extension: str
    sha256: str


def sniff_type(data: bytes) -> Optional[tuple[str, str]]:
    for magic, ctype, ext in MAGIC:
        if data.startswith(magic):
            return ctype, ext
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp", ".webp"
    return None


def _use_opencv() -> bool:
    return cv2 is not None


def _decode(data: bytes) -> Optional[np.ndarray]:
    """BGR/RGB-agnostic uint8 array (height, width, 3) with EXIF rotation applied, or None if undecodable."""
    if _use_opencv():
        img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)  # IMREAD_COLOR also applies EXIF rotation
        return None if img is None or img.size == 0 else img
    try:
        with Image.open(io.BytesIO(data)) as im:
            if im.width * im.height > MAX_PIXELS:  # header says it is huge: refuse before allocating pixels
                raise ImageRejected("The image dimensions are too large.", 413)
            im = ImageOps.exif_transpose(im).convert("RGB")
            return np.asarray(im)[:, :, ::-1].copy()  # keep the same BGR layout OpenCV uses
    except ImageRejected:
        raise
    except Exception:
        return None


def _resize(img: np.ndarray, longest: int) -> np.ndarray:
    h, w = img.shape[:2]
    scale = longest / max(h, w)
    if scale >= 1:
        return img
    size = (max(1, round(w * scale)), max(1, round(h * scale)))
    if _use_opencv():
        return cv2.resize(img, size, interpolation=cv2.INTER_AREA)
    return np.asarray(Image.fromarray(img[:, :, ::-1]).resize(size, Image.LANCZOS))[:, :, ::-1].copy()


def _encode_jpeg(img: np.ndarray, quality: int) -> Optional[bytes]:
    if _use_opencv():
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, quality])
        return buf.tobytes() if ok else None
    out = io.BytesIO()
    Image.fromarray(img[:, :, ::-1]).save(out, format="JPEG", quality=quality, optimize=True)  # no exif= argument: metadata dropped
    return out.getvalue()


def process_image(data: bytes, max_bytes: Optional[int] = None) -> ProcessedImage:
    limit = max_bytes if max_bytes is not None else settings.max_upload_mb * 1024 * 1024
    if not data:
        raise ImageRejected("The uploaded file is empty.")
    if len(data) > limit:
        raise ImageRejected(f"The image is larger than {settings.max_upload_mb} MB.", 413)
    kind = sniff_type(data)
    if kind is None:
        raise ImageRejected("Only JPEG, PNG or WebP photos are accepted.", 415)
    img = _decode(data)
    if img is None:
        raise ImageRejected("The file is not a valid image (it may be corrupted).", 400)
    h, w = img.shape[:2]
    if h * w > MAX_PIXELS:
        raise ImageRejected("The image dimensions are too large.", 413)
    if min(h, w) < 16:
        raise ImageRejected("The image is too small to be useful.", 400)
    img = _resize(img, MAX_SIDE)
    out_bytes, thumb = _encode_jpeg(img, 88), _encode_jpeg(_resize(img, THUMB_SIDE), 80)
    if out_bytes is None or thumb is None:
        raise ImageRejected("The image could not be processed.", 400)
    return ProcessedImage(out_bytes, thumb, img.shape[1], img.shape[0], "image/jpeg", ".jpg", hashlib.sha256(out_bytes).hexdigest())


def _safe_name(name: Optional[str]) -> str:
    base = Path((name or "photo").replace("\\", "/")).name
    cleaned = "".join(ch for ch in base if ch.isalnum() or ch in "._- ")[:100].strip()
    return cleaned or "photo"


def add_image(db: Session, complaint_id: int, uploader_id: int, filename: Optional[str], data: bytes) -> ComplaintImage:
    c = db.get(Complaint, complaint_id)
    if c is None:
        raise NotFoundError(f"complaint {complaint_id} not found")
    count = db.scalar(select(func.count()).select_from(ComplaintImage).where(ComplaintImage.complaint_id == complaint_id)) or 0
    if count >= settings.max_images_per_complaint:
        raise ImageRejected(f"A complaint can have at most {settings.max_images_per_complaint} photos.", 409)
    p = process_image(data)
    if db.scalar(select(ComplaintImage.id).where(ComplaintImage.complaint_id == complaint_id, ComplaintImage.sha256 == p.sha256)):
        raise ImageRejected("This photo is already attached to the complaint.", 409)
    img = ComplaintImage(complaint_id=complaint_id, image_path=f"db:{p.sha256}", thumbnail_path=f"db:{p.sha256}:thumb",
                         uploaded_by=uploader_id, uploaded_at=utcnow(), original_name=_safe_name(filename),
                         content_type=p.content_type, size_bytes=len(p.data), width=p.width, height=p.height,
                         sha256=p.sha256, data=p.data, thumb_data=p.thumb)
    db.add(img)
    db.commit()
    return img


def image_bytes(db: Session, image_id: int, thumbnail: bool = False) -> tuple[ComplaintImage, bytes]:
    img = db.get(ComplaintImage, image_id)
    if img is None:
        raise NotFoundError(f"image {image_id} not found")
    blob = img.thumb_data if thumbnail and img.thumb_data else img.data
    if not blob:
        raise NotFoundError("image data not found")
    return img, bytes(blob)
