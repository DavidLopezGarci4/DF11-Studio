"""RED->GREEN binary ICONDIR & PNG ladder verification for app-icon-studio Windows desktop assets."""

from __future__ import annotations

import json
import struct
from PIL import Image

from backend.core.paths import ASSETS_DIR, WORKSPACE_ROOT


def test_brand_masters_and_png_ladder_exist() -> None:
    brand_dir = WORKSPACE_ROOT / "brand"
    assert (brand_dir / "master-1024.png").is_file()
    assert (brand_dir / "mark-mono.svg").is_file()
    assert (brand_dir / "mark-mono.png").is_file()
    palette = json.loads((brand_dir / "palette.json").read_text(encoding="utf-8"))
    for key in ("primary", "secondary", "edge", "onDark", "onLight", "accent"):
        assert key in palette
    assert palette["accent"] == "#10B981"

    master = Image.open(brand_dir / "master-1024.png")
    assert master.size == (1024, 1024) and master.mode == "RGBA"
    assert master.getpixel((4, 4))[3] == 0 and master.getpixel((512, 512))[3] == 255

    for s in (16, 24, 32, 48, 64, 128, 256, 512, 1024):
        p = ASSETS_DIR / "icons" / f"icon-{s}.png"
        assert p.is_file()
        im = Image.open(p)
        assert im.size == (s, s) and im.mode == "RGBA"


def test_windows_app_ico_contains_exact_7_layers_binary_header() -> None:
    ico_path = ASSETS_DIR / "icons" / "app.ico"
    assert ico_path.is_file()
    raw = ico_path.read_bytes()
    reserved, ico_type, count = struct.unpack("<HHH", raw[:6])
    assert reserved == 0 and ico_type == 1 and count == 7

    widths = []
    for i in range(count):
        w, h = struct.unpack("<BB", raw[6 + i * 16 : 8 + i * 16])
        widths.append(256 if w == 0 else w)
        assert (256 if h == 0 else h) == widths[-1]
    assert sorted(widths) == [16, 24, 32, 48, 64, 128, 256]
