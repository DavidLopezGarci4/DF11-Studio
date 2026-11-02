"""RED->GREEN deterministic tests for DF11 lossless compositor and FM config.xml."""

from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from backend.core.compositor import (
    DF11_HEIGHT,
    DF11_WIDTH,
    export_df11_bytes,
    load_df11_assets,
    render_df11_card,
)
from backend.core.fm_config import FMConfigError, upsert_fm_config_xml, validate_fm_uid


def test_df11_frame_assets_geometry_and_punched_ring() -> None:
    inner_mask, overlay = load_df11_assets()
    assert inner_mask.size == (DF11_WIDTH, DF11_HEIGHT)
    assert overlay.size == (DF11_WIDTH, DF11_HEIGHT)

    ov = np.asarray(overlay)
    assert int(ov[:, :, :3].max()) == 0  # Zero jersey tint contamination
    assert int(np.abs(ov[:, :, 3].astype(int) - ov[::-1, :, 3].astype(int)).max()) == 0
    assert int(ov[155, 6, 3]) > 30  # Outer drop shadow intact
    # Punched Alpha==0 ring on all 4 sides
    assert int(ov[35:275, 11:18, 3].max()) == 0
    assert int(ov[35:275, 243:250, 3].max()) == 0
    assert int(ov[10:16, 35:225, 3].max()) == 0
    assert int(ov[294:300, 35:225, 3].max()) == 0


def test_destination_in_clip_preserves_alpha_zero_ring() -> None:
    custom_bg = Image.new("RGBA", (300, 350), (255, 20, 40, 255))
    portrait = Image.new("RGBA", (400, 400), (20, 180, 90, 255))
    card = render_df11_card(
        portrait_rgba=portrait,
        bg_mode="custom",
        bg_custom_rgba=custom_bg,
        bg_blur=4.0,
    )
    assert card.size == (DF11_WIDTH, DF11_HEIGHT) and card.mode == "RGBA"
    for rx, ry in [(14, 155), (246, 155), (130, 12), (130, 297)]:
        assert card.getpixel((rx, ry)) == (0, 0, 0, 0)
    assert card.getpixel((130, 155))[3] == 255


def test_transparent_layer1_keeps_unoccluded_window_transparent() -> None:
    portrait = Image.new("RGBA", (80, 80), (200, 150, 120, 255))
    card = render_df11_card(
        portrait_rgba=portrait,
        portrait_offset=(0.0, 60.0),
        bg_mode="transparent",
    )
    # Upper interior has no background, only subtle edge vignette or zero alpha at x=130, y=70
    assert card.getpixel((130, 70))[3] == 0
    assert card.getpixel((130, 215))[3] == 255


def test_export_png_rgba_and_jpg_rgb_over_white() -> None:
    portrait = Image.new("RGBA", (180, 220), (40, 100, 210, 255))
    card = render_df11_card(portrait_rgba=portrait, bg_mode="white_df11")

    png_bytes = export_df11_bytes(card, fmt="png")
    png_img = Image.open(io.BytesIO(png_bytes))
    assert png_img.mode == "RGBA" and png_img.size == (260, 310)
    assert png_img.getpixel((14, 155))[3] == 0

    jpg_bytes = export_df11_bytes(card, fmt="jpg")
    jpg_img = Image.open(io.BytesIO(jpg_bytes))
    assert jpg_img.mode == "RGB" and jpg_img.size == (260, 310)
    r, g, b = jpg_img.getpixel((14, 155))
    assert r >= 252 and g >= 252 and b >= 252


def test_fm_config_xml_validation_and_idempotent_atomic_upsert(tmp_path: Path) -> None:
    assert validate_fm_uid("29184012") == "29184012"
    assert validate_fm_uid("r-2002049102") == "r-2002049102"
    for bad in ["", "../123", '123" />', "abc", "r-1234567890123"]:
        with pytest.raises(FMConfigError):
            validate_fm_uid(bad)

    cfg = tmp_path / "config.xml"
    upsert_fm_config_xml(cfg, ["29184012", "r-2002049102"])
    upsert_fm_config_xml(cfg, ["29184012", "19005544"])  # Idempotent update
    text = cfg.read_text(encoding="utf-8")
    assert text.count('from="29184012"') == 1
    assert 'to="graphics/pictures/person/r-2002049102/portrait"' in text
    assert 'to="graphics/pictures/person/19005544/portrait"' in text
