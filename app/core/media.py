"""Static creative boundary: verify bytes and stamp server-side media facts.

Static kinds (image / banner / design comp) share one decoder path. Motion
formats add frame extraction here later; the scoring pipeline stays media-blind.
"""

from __future__ import annotations

import hashlib
import io
from typing import Optional

from app.core.models import MediaInfo

SUPPORTED_MIMES = {"image/jpeg", "image/png"}
MAX_IMAGE_BYTES = 15 * 1024 * 1024  # matches browser-side check in form.html
MAX_IMAGE_PIXELS = 40_000_000  # a small compressed file can decode to hundreds of MB

KINDS = ("image", "banner", "design")
KIND_LABELS = {"image": "Image ad", "banner": "Banner", "design": "Design comp"}

# Common IAB display sizes; anything else is allowed but flagged, never blocked.
BANNER_SIZES = {(300, 250), (336, 280), (728, 90), (300, 600), (320, 50),
                (970, 250), (160, 600), (300, 50), (468, 60)}


class ImageInvalid(ValueError):
    pass


def normalize_kind(raw: object) -> str:
    """Whitelist the client-supplied creative type (never trusted, never a path)."""
    kind = str(raw or "image").strip().lower()
    if kind not in KINDS:
        raise ImageInvalid(f"unknown creative type: {raw!r}")
    return kind


def verify_image(content: bytes, filename: str, content_type: str) -> tuple[bytes, str, str]:
    """Validate BEFORE any LLM call. Returns (content, verified_mime, sha256)."""
    if len(content) > MAX_IMAGE_BYTES:
        raise ImageInvalid(f"image over {MAX_IMAGE_BYTES // (1024 * 1024)}MB limit")
    if content_type not in SUPPORTED_MIMES:
        raise ImageInvalid(f"unsupported media type: {content_type}")
    from PIL import Image, UnidentifiedImageError

    Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS  # also guards the thumbnail decode path
    try:
        img = Image.open(io.BytesIO(content))
        width, height = img.size
        img.verify()
    except (UnidentifiedImageError, OSError, ValueError) as e:
        raise ImageInvalid(f"malformed image content: {e}") from e
    if width * height > MAX_IMAGE_PIXELS:
        raise ImageInvalid(f"image over {MAX_IMAGE_PIXELS // 1_000_000}MP pixel limit")
    # Re-open (verify() closes) to confirm decoded format matches claimed MIME.
    img = Image.open(io.BytesIO(content))
    decoded_mime = Image.MIME.get(img.format, "")
    if decoded_mime != content_type:
        raise ImageInvalid(f"MIME mismatch: claimed {content_type}, decoded {decoded_mime or 'unknown'}")
    # ponytail: filename never touches the filesystem (in-memory only), safe to ignore beyond this.
    checksum = "sha256:" + hashlib.sha256(content).hexdigest()
    return content, decoded_mime, checksum


def verify_creative(content: bytes, filename: str, content_type: str,
                    kind: object = "image") -> tuple[bytes, str, str, MediaInfo]:
    """Verify one static creative and stamp the facts the model must not supply."""
    kind = normalize_kind(kind)
    content, mime, checksum = verify_image(content, filename, content_type)
    from PIL import Image

    with Image.open(io.BytesIO(content)) as img:
        width, height = img.size
    media = MediaInfo(kind=kind, mime=mime, checksum=checksum,
                      width=width, height=height, bytes=len(content))
    return content, mime, checksum, media


def banner_size_warning(media: MediaInfo) -> Optional[str]:
    """Warn (never block) when a banner is not a standard IAB slot size."""
    if media.kind != "banner" or (media.width, media.height) in BANNER_SIZES:
        return None
    return (f"banner {media.width}×{media.height} is not a standard IAB size; "
            "real slot rendering may differ")
