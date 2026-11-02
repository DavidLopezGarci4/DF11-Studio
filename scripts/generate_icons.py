"""Deterministic brand master + PNG ladder + 7-layer Windows .ico generator (app-icon-studio)."""

from __future__ import annotations

import io
import json
import shutil
import struct
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
BRAND_DIR = ROOT / "brand"
ICONS_DIR = ROOT / "assets" / "icons"
PUBLIC_DIR = ROOT / "frontend" / "public"
LADDER_SIZES = (16, 24, 32, 48, 64, 128, 256, 512, 1024)
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)


def _render_master_1024() -> Image.Image:
    img = Image.new("RGBA", (1024, 1024), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Outer Windows 11 squircle with 9% safe margin (92..932)
    draw.rounded_rectangle((92, 92, 932, 932), radius=196, fill=(9, 13, 22, 255), outline=(16, 185, 129, 255), width=18)
    draw.rounded_rectangle((124, 124, 900, 900), radius=168, fill=(17, 24, 39, 255))

    # Iconic DF11 vertical card frame (260:310 aspect -> 476 x 568 centered)
    cx0, cy0, cx1, cy1 = 274, 212, 750, 780
    draw.rounded_rectangle((cx0, cy0, cx1, cy1), radius=54, fill=(248, 250, 252, 255))
    draw.rounded_rectangle((cx0 + 28, cy0 + 28, cx1 - 28, cy1 - 28), radius=34, fill=(15, 23, 42, 255))

    # Stylized player silhouette + emerald club V-collar inside DF11 window
    draw.pieslice((334, 548, 690, 900), start=180, end=360, fill=(16, 185, 129, 255))
    draw.polygon([(462, 560), (512, 628), (562, 560)], fill=(248, 250, 252, 255))
    draw.ellipse((426, 316, 598, 510), fill=(241, 245, 249, 255))

    # Optical DF11 alignment ticks on left/right inner frame
    for y_tick in (398, 580):
        draw.line((cx0 + 34, y_tick, cx0 + 76, y_tick), fill=(56, 189, 248, 235), width=10)
        draw.line((cx1 - 76, y_tick, cx1 - 34, y_tick), fill=(56, 189, 248, 235), width=10)
    return img


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
    BRAND_DIR.mkdir(parents=True, exist_ok=True)
    ICONS_DIR.mkdir(parents=True, exist_ok=True)
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)

    palette = {"canvas": "#090D16", "surface": "#111827", "accent": "#10B981", "frame": "#F8FAFC", "guide": "#38BDF8"}
    (BRAND_DIR / "palette.json").write_text(json.dumps(palette, indent=2) + "\n", encoding="utf-8")
    (BRAND_DIR / "mark-mono.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256" fill="none">'
        '<rect x="52" y="32" width="152" height="192" rx="22" stroke="currentColor" stroke-width="14"/>'
        '<circle cx="128" cy="104" r="28" fill="currentColor"/>'
        '<path d="M80 198c8-28 30-44 48-44s40 16 48 44" fill="currentColor"/></svg>\n',
        encoding="utf-8",
    )

    master = _render_master_1024()
    master.save(BRAND_DIR / "master-1024.png", format="PNG", compress_level=9)

    png_blobs: dict[int, bytes] = {}
    for sz in LADDER_SIZES:
        resized = master if sz == 1024 else master.resize((sz, sz), Image.Resampling.LANCZOS)
        if sz <= 32:
            resized = resized.filter(ImageFilter.SHARPEN)
        out_png = ICONS_DIR / f"icon-{sz}.png"
        buf = io.BytesIO()
        resized.save(buf, format="PNG", compress_level=9)
        png_blobs[sz] = buf.getvalue()
        out_png.write_bytes(png_blobs[sz])

    _pack_exact_7_layer_ico(png_blobs, ICONS_DIR / "app.ico")
    shutil.copy2(ICONS_DIR / "app.ico", PUBLIC_DIR / "favicon.ico")
    shutil.copy2(ICONS_DIR / "icon-128.png", PUBLIC_DIR / "icon-128.png")


if __name__ == "__main__":
    main()
