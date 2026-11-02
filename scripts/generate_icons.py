"""Deterministic icon ladder + mono PNG + 7-layer Windows .ico generator from brand/master-1024.png (app-icon-studio)."""

from __future__ import annotations

import io
import shutil
import struct
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
BRAND_DIR = ROOT / "brand"
ICONS_DIR = ROOT / "assets" / "icons"
PUBLIC_DIR = ROOT / "frontend" / "public"
LADDER_SIZES = (16, 24, 32, 48, 64, 128, 256, 512, 1024)
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)


def _render_mark_mono_png(master: Image.Image, size: int = 512) -> Image.Image:
    """Derive exact anti-aliased single-color silhouette directly from brand/master-1024.png."""
    inner_mask = Image.new("L", (1024, 1024), 0)
    ImageDraw.Draw(inner_mask).rounded_rectangle((112, 112, 912, 912), radius=172, fill=255)
    arr = np.asarray(master, dtype=np.float32)
    gate = np.asarray(inner_mask, dtype=np.float32) / 255.0
    alpha_hi = np.clip((arr[:, :, :3].max(axis=-1) - 48.0) * 3.0, 0.0, 255.0) * gate
    mono = np.zeros((1024, 1024, 4), dtype=np.uint8)
    mono[:, :, :3] = (248, 250, 252)
    mono[:, :, 3] = np.round(alpha_hi).astype(np.uint8)
    return Image.fromarray(mono, mode="RGBA").resize((size, size), Image.Resampling.LANCZOS)


def _derive_size_variant(master: Image.Image, sz: int) -> Image.Image:
    if sz == 1024:
        return master.copy()
    if sz in (16, 24):
        # Tighter emblem framing + contrast/unsharp boost so 3 isometric layers stay crisp at 16/24px
        cropped = master.crop((56, 56, 968, 968)).resize((sz, sz), Image.Resampling.LANCZOS)
        rgb, a = cropped.convert("RGB"), cropped.getchannel("A")
        rgb = ImageEnhance.Contrast(rgb).enhance(1.18).filter(ImageFilter.UnsharpMask(radius=0.9, percent=135, threshold=2))
        out = rgb.convert("RGBA")
        out.putalpha(a)
        return out
    resized = master.resize((sz, sz), Image.Resampling.LANCZOS)
    if sz <= 32:
        resized = resized.filter(ImageFilter.SHARPEN)
    return resized


def _pack_exact_7_layer_ico(frames: dict[int, bytes], out_path: Path) -> None:
    """Pack PNG-compressed ICO frames with exact Windows ICONDIR + 7 ICONDIRENTRY records."""
    header = struct.pack("<HHH", 0, 1, len(ICO_SIZES))
    offset = 6 + 16 * len(ICO_SIZES)
    entries = bytearray()
    payloads = bytearray()
    for sz in ICO_SIZES:
        blob = frames[sz]
        dim_byte = 0 if sz == 256 else sz
        entries.extend(struct.pack("<BBBBHHII", dim_byte, dim_byte, 0, 0, 1, 32, len(blob), offset))
        payloads.extend(blob)
        offset += len(blob)
    out_path.write_bytes(bytes(header) + bytes(entries) + bytes(payloads))


def main() -> None:
    master_path = BRAND_DIR / "master-1024.png"
    if not master_path.is_file():
        raise FileNotFoundError(f"Missing SSOT master icon: {master_path}")

    ICONS_DIR.mkdir(parents=True, exist_ok=True)
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)

    master = Image.open(master_path).convert("RGBA")
    if master.size != (1024, 1024):
        raise ValueError(f"Expected 1024x1024 master-1024.png, got {master.size}")

    _render_mark_mono_png(master, 512).save(BRAND_DIR / "mark-mono.png", format="PNG", compress_level=9)

    png_blobs: dict[int, bytes] = {}
    for sz in LADDER_SIZES:
        variant = _derive_size_variant(master, sz)
        buf = io.BytesIO()
        variant.save(buf, format="PNG", compress_level=9)
        png_blobs[sz] = buf.getvalue()
        (ICONS_DIR / f"icon-{sz}.png").write_bytes(png_blobs[sz])

    _pack_exact_7_layer_ico(png_blobs, ICONS_DIR / "app.ico")
    shutil.copy2(ICONS_DIR / "app.ico", PUBLIC_DIR / "favicon.ico")
    shutil.copy2(ICONS_DIR / "icon-128.png", PUBLIC_DIR / "icon-128.png")


if __name__ == "__main__":
    main()
