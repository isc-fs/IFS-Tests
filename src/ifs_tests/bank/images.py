"""Convert mirrored FS-Quiz images to small WebP files named by content, served from /media/."""

from __future__ import annotations

import hashlib
import io
from pathlib import Path

from PIL import Image

MAX_BYTES = 150_000
MAX_SIDE = 1600
Image.MAX_IMAGE_PIXELS = 40_000_000


def media_name(source: bytes) -> str:
    return hashlib.sha256(source).hexdigest()[:32] + ".webp"


def _encode(img: Image.Image) -> bytes:
    for side in (MAX_SIDE, 1200, 900):
        img.thumbnail((side, side))
        for quality in (80, 65, 50):
            out = io.BytesIO()
            img.save(out, "WEBP", quality=quality, method=6)
            if out.tell() <= MAX_BYTES:
                return out.getvalue()
    return out.getvalue()


def to_media(source: Path, media_dir: Path) -> str:
    """Write `source` to `media_dir` as WebP (once) and return its file name."""
    data = source.read_bytes()
    name = media_name(data)
    target = media_dir / name
    if not target.exists():
        with Image.open(io.BytesIO(data)) as img:
            img.load()
            webp = _encode(img.convert("RGBA" if "A" in img.getbands() or img.mode == "P" else "RGB"))
        media_dir.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".tmp")
        tmp.write_bytes(webp)
        tmp.replace(target)
    return name
