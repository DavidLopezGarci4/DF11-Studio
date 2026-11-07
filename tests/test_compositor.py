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


def test_fm_config_xml_escapes_entities_and_deduplicates_subfolder_targets(tmp_path: Path) -> None:
    cfg = tmp_path / "config.xml"
    cfg.write_text(
        '<record><list id="maps">'
        '<record from="club_a&amp;b/logo" to="graphics/pictures/club/10/logo"/>'
        '<record from="faces/29184012" to="graphics/pictures/person/29184012/portrait"/>'
        "</list></record>",
        encoding="utf-8",
    )
    upsert_fm_config_xml(cfg, ["29184012"])
    # Re-updating must succeed (well-formed XML with &amp; preserved) and remove stale faces/29184012
    upsert_fm_config_xml(cfg, ["r-101"])
    text = cfg.read_text(encoding="utf-8")
    assert "club_a&amp;b/logo" in text
    assert "faces/29184012" not in text
    assert text.count("graphics/pictures/person/29184012/portrait") == 1


def test_fm_config_xml_preserves_multi_target_from_icons_and_shared_defaults(tmp_path: Path) -> None:
    cfg = tmp_path / "config.xml"
    cfg.write_text(
        '<record>\n'
        '\t<boolean id="preload" value="true"/>\n'
        '\t<boolean id="amap" value="false"/>\n'
        '\t<list id="maps">\n'
        '\t\t<record from="10001" to="graphics/pictures/person/10001/portrait"/>\n'
        '\t\t<record from="10001" to="graphics/pictures/person/10001/icon"/>\n'
        '\t\t<record from="29184012" to="graphics/pictures/person/29184012/icon"/>\n'
        '\t\t<record from="faces/29184012" to="graphics/pictures/person/29184012/portrait"/>\n'
        '\t\t<record from="default" to="graphics/pictures/person/5001/portrait"/>\n'
        '\t\t<record from="default" to="graphics/pictures/person/5002/portrait"/>\n'
        '\t</list>\n'
        '</record>\n',
        encoding="utf-8",
    )
    upsert_fm_config_xml(cfg, ["29184012"])
    text = cfg.read_text(encoding="utf-8")
    assert 'id="preload" value="true"' in text
    assert '<record from="10001" to="graphics/pictures/person/10001/portrait"/>' in text
    assert '<record from="10001" to="graphics/pictures/person/10001/icon"/>' in text
    assert '<record from="29184012" to="graphics/pictures/person/29184012/icon"/>' in text
    assert '<record from="29184012" to="graphics/pictures/person/29184012/portrait"/>' in text
    assert "faces/29184012" not in text
    assert '<record from="default" to="graphics/pictures/person/5001/portrait"/>' in text
    assert '<record from="default" to="graphics/pictures/person/5002/portrait"/>' in text


def test_official_white_df11_photometric_gradient_and_pure_sleeve_closure() -> None:
    from backend.core.compositor import _build_preset_bg, pad_pure_to_df11_canvas

    bg = _build_preset_bg("white_df11")
    assert bg.shape == (DF11_HEIGHT, DF11_WIDTH, 4)
    # Strictly neutral achromatic studio background (R == G == B)
    assert np.array_equal(bg[:, :, 0], bg[:, :, 1])
    assert np.array_equal(bg[:, :, 1], bg[:, :, 2])
    # Vertical studio gradient below top softbox border: crown (y=43) > mid-chest (y=155) > lower torso (y=260)
    assert int(bg[43, 130, 0]) >= 253
    assert int(bg[43, 130, 0]) > int(bg[155, 130, 0]) > int(bg[260, 130, 0])
    # Top and lateral softbox perimeter falloff without corner double-darkening pinch
    assert int(bg[22, 130, 0]) < int(bg[43, 130, 0])
    assert int(bg[120, 22, 0]) == int(bg[120, 238, 0])
    assert int(bg[120, 22, 0]) < int(bg[120, 130, 0])

    # 220x276 Pure cutout placed onto Classic white_df11 closes both x=19 (1px) and x=240..241 (2px) sleeve columns
    pure = np.zeros((276, 220, 4), dtype=np.uint8)
    pure[200:276, :, :3] = [20, 32, 64]
    pure[200:276, :, 3] = 255
    pure[200:276, 0, 3] = 220
    pure[200:276, -1, 3] = 220
    stage = pad_pure_to_df11_canvas(Image.fromarray(pure, mode="RGBA"), unfeather_edges=True)
    classic = np.asarray(render_df11_card(portrait_rgba=stage, bg_mode="white_df11"))
    assert int(classic[245, 19, 2]) < 95
    assert int(classic[245, 240, 2]) < 95
    assert int(classic[245, 241, 2]) < 110


def test_dark_capture_classic_white_df11_zero_ai_halo_and_stripe_integrity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PIL import ImageDraw
    import backend.services.vision as vis_mod
    from backend.services.studio_workflow import ModularWorkflowSession

    def _forbid_onnx(*_a: object, **_kw: object) -> None:
        raise AssertionError("Zero-AI violation: ONNX session pool must never be invoked for Classic Capa Blanca DF11!")

    monkeypatch.setattr(vis_mod, "_run_session", _forbid_onnx)
    monkeypatch.setattr(vis_mod, "_get_ort", _forbid_onnx)
    monkeypatch.setattr(vis_mod, "ensure_model", _forbid_onnx)

    # Synthetic 170x210 upscaled dark-screen capture (#0E1420) with half-white / half-black striped kit
    cap = Image.new("RGBA", (170, 210), (14, 20, 32, 255))
    draw = ImageDraw.Draw(cap)
    draw.ellipse([54, 22, 116, 112], fill=(204, 158, 132, 255))
    draw.rectangle([70, 102, 100, 145], fill=(194, 148, 122, 255))
    draw.polygon([(0, 209), (0, 152), (62, 132), (85, 132), (85, 209)], fill=(244, 245, 247, 255))
    draw.polygon([(85, 132), (108, 132), (169, 152), (169, 209), (85, 209)], fill=(22, 25, 31, 255))
    buf = io.BytesIO()
    cap.save(buf, format="PNG")

    sess = ModularWorkflowSession(
        templates_dir=tmp_path / "tpls",
        extracted_faces_dir=tmp_path / "faces",
        sample_faces_dir=tmp_path / "samples",
        raw_archive_dir=tmp_path / "raw",
        db_path=tmp_path / "state.sqlite3",
    )
    loaded = sess.load_direct_photo(buf.getvalue(), "Dark_Cap.png", extra_params={"directBgReplace": False})
    did = loaded["directPhotoId"]
    assert loaded["directBgReplace"] is False

    # Option 1: Keep original dark capture background
    card_orig = np.asarray(
        sess.compose_step_card(
            {"step1Mode": "direct_photo", "directPhotoId": did, "directBgReplace": False, "bgMode": "white_df11"}
        )
    )
    assert float(card_orig[42, 42, :3].mean()) < 45.0

    # Option 2: Apply Official DF11 White Layer (0% AI) -> bright background, zero dark moat on white shoulder, intact stripe seam
    card_white, card_pure = sess.compose_step_dual_cards(
        {
            "step1Mode": "direct_photo",
            "directPhotoId": did,
            "directBgReplace": True,
            "bgMode": "white_df11",
            "enhanceQuality": 0.4,
        }
    )
    cw_arr = np.asarray(card_white)
    cp_arr = np.asarray(card_pure)
    assert float(cw_arr[42, 42, :3].mean()) > 235.0
    # Left white shoulder exterior & boundary must stay bright (no black Lanczos/dark-UI moat!)
    assert float(cw_arr[195:235, 32:65, :3].min(axis=-1).mean()) > 218.0
    # Central white-to-black stripe seam in Pure must remain 100% opaque (zero color-line holes!)
    assert int(cp_arr[215:265, 102:118, 3].min()) == 255


