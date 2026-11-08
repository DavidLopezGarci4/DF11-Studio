"""RED->GREEN tests for v2 Shirt-Only Templates, Non-Destructive Head/Neck Extractor, CollarFunnel & NeckBridge."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from backend.core.compositor import DF11_HEIGHT, DF11_WIDTH
from backend.services.head_neck import (
    CropViewport,
    compose_modular_df11,
    extract_clean_head_and_neck,
    fit_head_to_shirt_template,
    suggest_safe_crop_viewport,
)
from backend.services.templates import (
    rename_shirt_template,
    sync_tshirt_templates_dir,
)


def _synthetic_dirty_card_with_face_and_vneck() -> Image.Image:
    """Create a 260x310 card with white wall, outer frame shadow, pink head/neck, and crimson V-neck shirt."""
    card = Image.new("RGBA", (DF11_WIDTH, DF11_HEIGHT), (250, 250, 252, 255))
    draw = ImageDraw.Draw(card)
    # Outer dark border that must be stripped
    draw.rectangle([4, 4, 255, 305], outline=(20, 20, 25, 220), width=4)
    # Head + neck skin (pinkish)
    draw.ellipse([80, 42, 180, 178], fill=(225, 175, 155, 255))
    draw.rectangle([94, 165, 166, 232], fill=(218, 168, 148, 255))
    # Crimson jersey with V-neck opening (left rim ~92,196; right rim ~168,196; apex ~130,228)
    draw.polygon(
        [(19, 232), (92, 196), (130, 228), (168, 196), (241, 232), (241, 292), (19, 292)],
        fill=(152, 32, 46, 255),
    )
    return card


def test_tshirt_template_sanitizer_archives_raw_strips_face_and_persists_club_binding(
    tmp_path: Path, monkeypatch
) -> None:
    import backend.services.vision as vision_mod

    # Deterministic segmentation stub: skin at y<228 inside neck, clothes on the V-neck polygon
    def _fake_seg(im: Image.Image) -> np.ndarray:
        arr = np.asarray(im.convert("RGBA"))
        h, w = arr.shape[:2]
        probs = np.zeros((h, w, 6), dtype=np.float32)
        is_red_shirt = (arr[:, :, 0] > 120) & (arr[:, :, 1] < 70)
        is_skin = (arr[:, :, 0] > 190) & (arr[:, :, 1] > 140) & (arr[:, :, 1] < 200)
        probs[:, :, 4] = np.where(is_red_shirt, 0.95, 0.01)
        probs[:, :, 2] = np.where(is_skin & ~is_red_shirt, 0.92, 0.02)
        probs[:, :, 0] = np.clip(1.0 - probs[:, :, 4] - probs[:, :, 2], 0.0, 1.0)
        return probs

    def _fake_biref(im: Image.Image) -> Image.Image:
        arr = np.asarray(im.convert("RGBA")).copy()
        is_wall = (arr[:, :, 0] > 240) & (arr[:, :, 1] > 240) & (arr[:, :, 2] > 240)
        arr[:, :, 3] = np.where(is_wall, 0, arr[:, :, 3])
        return Image.fromarray(arr, mode="RGBA")

    monkeypatch.setattr(vision_mod, "segment_portrait_classes", _fake_seg)
    monkeypatch.setattr(vision_mod, "remove_background_birefnet", _fake_biref)

    tpl_dir = tmp_path / "tshirt_templates"
    raw_archive = tmp_path / "cache" / "raw_tshirt_sources"
    db_path = tmp_path / "state.sqlite3"
    tpl_dir.mkdir(parents=True)
    _synthetic_dirty_card_with_face_and_vneck().save(tpl_dir / "CrimsonClub.png")

    items = sync_tshirt_templates_dir(tpl_dir=tpl_dir, raw_archive_dir=raw_archive, db_path=db_path)
    assert len(items) == 1
    tpl = items[0]
    assert tpl.template_id == "CrimsonClub"
    assert 60 <= tpl.collar.collar_width <= 92
    assert tpl.collar.apex[1] > tpl.collar.left_rim[1] + 12

    # Raw backup exists OUTSIDE tshirt_templates, and tshirt_templates holds ONLY clean PNGs
    assert len(list(raw_archive.glob("CrimsonClub_*.png"))) == 1
    assert [p.name for p in tpl_dir.iterdir()] == ["CrimsonClub.png"]

    cleaned = np.asarray(Image.open(tpl_dir / "CrimsonClub.png").convert("RGBA"))
    assert cleaned.shape == (DF11_HEIGHT, DF11_WIDTH, 4)
    # Head zone (y < 160) and outer DF11 ring (x < 18, y > 293) must be strictly Alpha == 0
    assert int(cleaned[:160, :, 3].max()) == 0
    assert int(cleaned[:, :18, 3].max()) == 0
    assert int(cleaned[294:, :, 3].max()) == 0

    # Rename & bind to Real Madrid (#1736) persists in SQLite
    updated = rename_shirt_template("CrimsonClub", display_name="Real Madrid Visitante", club_id="1736", tpl_dir=tpl_dir, db_path=db_path)
    assert updated.display_name == "Real Madrid Visitante" and updated.club_id == "1736"


def test_short_neck_bridge_closes_vneck_gap_and_collar_funnel_prevents_batwings(monkeypatch) -> None:
    import backend.services.vision as vision_mod
    from backend.services.vision import FacePose

    # Build a clean V-neck shirt template directly (collar opening x=92..168 at y=196, V-apex at 130,232)
    shirt = Image.new("RGBA", (DF11_WIDTH, DF11_HEIGHT), (0, 0, 0, 0))
    sdraw = ImageDraw.Draw(shirt)
    sdraw.polygon(
        [(19, 234), (92, 196), (130, 232), (168, 196), (241, 234), (241, 292), (19, 292)],
        fill=(25, 65, 145, 255),
    )

    # Build a cutout portrait that has:
    # 1) Tall hair near top (y=2) -> must NOT get chopped at top
    # 2) Short neck ending high AND wide residual dark trapezius wings (width 220px at bottom!)
    face_im = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    fdraw = ImageDraw.Draw(face_im)
    fdraw.ellipse([72, 2, 184, 70], fill=(30, 25, 22, 255))  # Tall hair reaching y=2
    fdraw.ellipse([76, 38, 180, 196], fill=(196, 146, 118, 255))  # Face skin ending at y=196 (short!)
    # Wide bat-wing trapezius artifact at y=188..208 (x=15..240) that is NOT marked as clothes
    fdraw.rectangle([15, 188, 240, 206], fill=(60, 50, 48, 255))

    def _fake_pose(_im: Image.Image, score_thresh: float = 0.55) -> FacePose:
        return FacePose(
            right_eye=(100.0, 112.0),
            left_eye=(156.0, 112.0),
            nose=(128.0, 138.0),
            eye_center=(128.0, 112.0),
            ipd=56.0,
            yaw=0.0,
            bbox=(74.0, 35.0, 108.0, 165.0),
        )

    def _fake_seg(im: Image.Image) -> np.ndarray:
        arr = np.asarray(im.convert("RGBA"))
        h, w = arr.shape[:2]
        probs = np.zeros((h, w, 6), dtype=np.float32)
        fg = arr[:, :, 3] > 20
        is_hair = fg & (arr[:, :, 0] < 45)
        is_face = fg & (arr[:, :, 0] > 150)
        probs[:, :, 1] = np.where(is_hair, 0.92, 0.01)
        probs[:, :, 3] = np.where(is_face, 0.92, 0.01)
        probs[:, :, 2] = np.where(fg & ~is_hair & ~is_face, 0.85, 0.01)
        probs[:, :, 0] = np.where(~fg, 0.97, 0.02)
        return probs

    monkeypatch.setattr(vision_mod, "detect_face_pose", _fake_pose)
    monkeypatch.setattr(vision_mod, "segment_portrait_classes", _fake_seg)

    vp = suggest_safe_crop_viewport(face_im)
    assert isinstance(vp, CropViewport)
    head_asset = extract_clean_head_and_neck(face_im, is_pre_cutout=True, crop_viewport=vp)

    from backend.services.templates import extract_collar_profile

    collar = extract_collar_profile(shirt)
    fit = fit_head_to_shirt_template(head_asset, collar)

    card = compose_modular_df11(
        head_asset=head_asset,
        shirt_rgba=shirt,
        collar=collar,
        fit=fit,
        bg_mode="transparent",
    )
    arr = np.asarray(card)
    assert arr.shape == (DF11_HEIGHT, DF11_WIDTH, 4)

    # 1. Anti-crown-chop: top inner row y=18..20 has space, hair is intact below y>=20
    assert int(arr[22:45, 115:145, 3].max()) == 255
    # 2. Zero neck gap inside V-neck socket (x=130, y=195..230 must be 100% opaque skin/collar)
    assert int(arr[195:230, 128:133, 3].min()) == 255
    # 3. Zero bat-wing overflow in both the scaled bat-wing zone (y=172..192, x=48..72) and right above shoulder slope (y=198..203, x=48..62)
    assert int(arr[172:192, 48:72, 3].max()) == 0
    assert int(arr[198:203, 48:62, 3].max()) == 0
    # 4. Outer DF11 cutout ring stays strictly Alpha == 0
    assert int(arr[0, 130, 3]) == 0 and int(arr[155, 0, 3]) == 0


def test_white_on_white_shirt_preserves_full_shoulders_even_when_p_clothes_drops(monkeypatch) -> None:
    import backend.services.vision as vision_mod
    from backend.services.templates import sanitize_shirt_template_rgba

    # Predominantly white shirt (RGB=242) over white DF11 wall (RGB=248), like ItalMed9 / Caucasian0
    card = Image.new("RGBA", (DF11_WIDTH, DF11_HEIGHT), (248, 248, 250, 255))
    draw = ImageDraw.Draw(card)
    draw.ellipse([82, 42, 178, 178], fill=(220, 175, 152, 255))
    draw.rectangle([94, 166, 166, 226], fill=(214, 168, 146, 255))
    draw.polygon(
        [(19, 214), (86, 181), (130, 227), (174, 181), (241, 214), (241, 292), (19, 292)],
        fill=(242, 243, 245, 255),
    )

    def _fake_seg(im: Image.Image) -> np.ndarray:
        arr = np.asarray(im.convert("RGBA"))
        h, w = arr.shape[:2]
        sx, sy = w / float(DF11_WIDTH), h / float(DF11_HEIGHT)
        probs = np.zeros((h, w, 6), dtype=np.float32)
        is_skin = (arr[:, :, 0] > 205) & (arr[:, :, 1] < 190)
        probs[:, :, 2] = np.where(is_skin, 0.94, 0.01)
        # Simulate MediaPipe 256x256 confusing white sleeves (|x-130|>45 in 1x) with white background (p_clothes=0.03)!
        yy, xx = np.mgrid[0:h, 0:w]
        center_cloth = (yy >= 181.0 * sy) & (np.abs(xx - 130.0 * sx) <= 45.0 * sx) & ~is_skin
        probs[:, :, 4] = np.where(center_cloth, 0.90, 0.03)
        probs[:, :, 0] = np.clip(1.0 - probs[:, :, 2] - probs[:, :, 4], 0.0, 1.0)
        return probs

    def _fake_biref(im: Image.Image) -> Image.Image:
        # Simulate ItalMed9 asymmetry: BiRefNet finds right white shoulder (x>=130 in 1x) at 255, misses left outer tip
        w, h = im.size
        sx, sy = w / float(DF11_WIDTH), h / float(DF11_HEIGHT)
        out = Image.new("RGBA", im.size, (0, 0, 0, 0))
        mask = Image.new("L", im.size, 0)
        mdraw = ImageDraw.Draw(mask)
        mdraw.ellipse([82 * sx, 42 * sy, 178 * sx, 178 * sy], fill=255)
        pts = [(x * sx, y * sy) for x, y in [(60, 214), (86, 181), (174, 181), (241, 214), (241, 292), (60, 292)]]
        mdraw.polygon(pts, fill=255)
        out.putalpha(mask)
        return out

    monkeypatch.setattr(vision_mod, "segment_portrait_classes", _fake_seg)
    monkeypatch.setattr(vision_mod, "remove_background_birefnet", _fake_biref)

    cleaned = np.asarray(sanitize_shirt_template_rgba(card, symmetrize_shoulders=True))
    # Both left (x=20..40) and right (x=220..240) white shoulders must be 100% finished down to y=218..280!
    assert int(cleaned[220:280, 21, 3].min()) >= 250
    assert int(cleaned[220:280, 239, 3].min()) >= 250
    # Head and neck stay completely stripped
    assert int(cleaned[:160, :, 3].max()) == 0


def test_asymmetric_dark_shoulder_over_white_wall_never_mirrors_white_halo(monkeypatch) -> None:
    import backend.services.vision as vision_mod
    from backend.services.templates import sanitize_shirt_template_rgba

    # Simulate a dark-shouldered shirt (like Rayo away/third or asymmetric pose) over a bright white studio wall:
    # Left shoulder sits higher (y=198), right shoulder sits lower (y=210), so y=200..208 on the right is white wall!
    card = Image.new("RGBA", (DF11_WIDTH, DF11_HEIGHT), (253, 253, 251, 255))
    draw = ImageDraw.Draw(card)
    draw.ellipse([82, 42, 178, 178], fill=(220, 175, 152, 255))
    draw.rectangle([96, 166, 164, 224], fill=(214, 168, 146, 255))
    draw.polygon(
        [(19, 198), (92, 184), (130, 224), (168, 188), (241, 210), (241, 292), (19, 292)],
        fill=(24, 26, 30, 255),
    )

    def _fake_seg(im: Image.Image) -> np.ndarray:
        arr = np.asarray(im.convert("RGBA"))
        h, w = arr.shape[:2]
        probs = np.zeros((h, w, 6), dtype=np.float32)
        is_dark_cloth = arr[:, :, 0] < 60
        is_skin = (arr[:, :, 0] > 195) & (arr[:, :, 1] < 190)
        probs[:, :, 4] = np.where(is_dark_cloth, 0.95, 0.02)
        probs[:, :, 2] = np.where(is_skin, 0.93, 0.01)
        probs[:, :, 0] = np.clip(1.0 - probs[:, :, 4] - probs[:, :, 2], 0.0, 1.0)
        return probs

    def _fake_biref(im: Image.Image) -> Image.Image:
        arr = np.asarray(im.convert("RGBA")).copy()
        is_wall = (arr[:, :, 0] > 245) & (arr[:, :, 1] > 245) & (arr[:, :, 2] > 245)
        arr[:, :, 3] = np.where(is_wall, 0, 255)
        return Image.fromarray(arr, mode="RGBA")

    monkeypatch.setattr(vision_mod, "segment_portrait_classes", _fake_seg)
    monkeypatch.setattr(vision_mod, "remove_background_birefnet", _fake_biref)

    cleaned = np.asarray(sanitize_shirt_template_rgba(card, symmetrize_shoulders=True, detail_crispness=0.45))
    # Right shoulder white background band (y=201..206, x=228) must NOT be turned opaque white by mirror symmetrization
    assert int(cleaned[202, 228, 3]) < 20
    # Dark fabric below (y=220..280, x=228) stays completely solid and dark
    assert int(cleaned[220:280, 228, 3].min()) >= 250
    assert int(cleaned[240, 228, 0]) < 45


def test_transparent_or_panned_dark_and_vertical_shirts_never_synthesize_black_blocks(monkeypatch) -> None:
    import backend.services.vision as vision_mod
    from backend.services.templates import sanitize_shirt_template_rgba

    def _fake_seg(im: Image.Image) -> np.ndarray:
        arr = np.asarray(im.convert("RGBA"))
        h, w = arr.shape[:2]
        probs = np.zeros((h, w, 6), dtype=np.float32)
        is_cloth = ((arr[:, :, 0] < 60) & (arr[:, :, 1] < 60)) | ((arr[:, :, 0] > 170) & (arr[:, :, 1] < 60))
        probs[:, :, 4] = np.where(is_cloth, 0.94, 0.02)
        probs[:, :, 0] = np.clip(1.0 - probs[:, :, 4], 0.0, 1.0)
        return probs

    def _fake_biref(im: Image.Image) -> Image.Image:
        arr = np.asarray(im.convert("RGBA")).copy()
        is_cloth = ((arr[:, :, 0] < 60) & (arr[:, :, 1] < 60)) | ((arr[:, :, 0] > 170) & (arr[:, :, 1] < 60))
        arr[:, :, 3] = np.where(is_cloth, 255, 0)
        return Image.fromarray(arr, mode="RGBA")

    monkeypatch.setattr(vision_mod, "segment_portrait_classes", _fake_seg)
    monkeypatch.setattr(vision_mod, "remove_background_birefnet", _fake_biref)

    # 1) Transparent 260x310 PNG with dark sleeve only on left side (raw_a == 0 on right)
    asym_cutout = Image.new("RGBA", (DF11_WIDTH, DF11_HEIGHT), (0, 0, 0, 0))
    d1 = ImageDraw.Draw(asym_cutout)
    d1.polygon([(20, 200), (92, 186), (130, 226), (168, 188), (185, 220), (185, 292), (20, 292)], fill=(22, 24, 28, 255))
    out1 = np.asarray(sanitize_shirt_template_rgba(asym_cutout, symmetrize_shoulders=True))
    assert int(out1[220, 220, 3]) == 0

    # 2) Opaque 260x310 dark shirt panned right (pan_x=35 -> left margin x=20..30 has raw_a == 0)
    dark_card = Image.new("RGBA", (DF11_WIDTH, DF11_HEIGHT), (245, 245, 248, 255))
    d2 = ImageDraw.Draw(dark_card)
    d2.polygon([(19, 204), (90, 186), (130, 224), (170, 186), (241, 204), (241, 292), (19, 292)], fill=(22, 24, 28, 255))
    out2 = np.asarray(sanitize_shirt_template_rgba(dark_card, symmetrize_shoulders=True, pan_x=35.0))
    assert int(out2[250, 25, 3]) == 0

    # 3) Vertical 600x900 red shirt at zoom=1.0 with shoulder_boost=0.4 -> outer raw_a==0 margins stay alpha==0
    vert_red = Image.new("RGBA", (600, 900), (245, 246, 248, 255))
    d3 = ImageDraw.Draw(vert_red)
    d3.polygon([(10, 590), (210, 535), (300, 650), (390, 535), (590, 590), (590, 885), (10, 885)], fill=(200, 20, 30, 255))
    out3 = np.asarray(sanitize_shirt_template_rgba(vert_red, symmetrize_shoulders=True, shoulder_boost=0.4))
    assert int(out3[260, 22, 3]) == 0
    assert int(out3[260, 48, 3]) >= 250 and int(out3[260, 48, 0]) > 150


def test_progressive_neck_thickening_scales_monotonically_across_collar_opening(monkeypatch) -> None:
    import backend.services.vision as vision_mod
    from backend.services.head_neck import HeadFitParams
    from backend.services.templates import extract_collar_profile
    from backend.services.vision import FacePose

    # Wide V-neck blue shirt template (collar opening x=86..174 at y=196, V-apex at 130,232 -> 88px wide)
    shirt = Image.new("RGBA", (DF11_WIDTH, DF11_HEIGHT), (0, 0, 0, 0))
    sdraw = ImageDraw.Draw(shirt)
    sdraw.polygon(
        [(19, 234), (86, 196), (130, 232), (174, 196), (241, 234), (241, 292), (19, 292)],
        fill=(25, 65, 145, 255),
    )
    collar = extract_collar_profile(shirt)

    # Portrait with a slim real neck (x=108..148 in 256x256) ending short at y=190
    face_im = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    fdraw = ImageDraw.Draw(face_im)
    fdraw.ellipse([78, 34, 178, 174], fill=(216, 165, 138, 255))
    fdraw.rectangle([108, 158, 148, 190], fill=(210, 158, 132, 255))

    def _fake_pose(_im: Image.Image, score_thresh: float = 0.55) -> FacePose:
        return FacePose(
            right_eye=(102.0, 106.0),
            left_eye=(154.0, 106.0),
            nose=(128.0, 132.0),
            eye_center=(128.0, 106.0),
            ipd=52.0,
            yaw=0.0,
            bbox=(76.0, 32.0, 104.0, 158.0),
        )

    def _fake_seg(im: Image.Image) -> np.ndarray:
        arr = np.asarray(im.convert("RGBA"))
        h, w = arr.shape[:2]
        probs = np.zeros((h, w, 6), dtype=np.float32)
        fg = arr[:, :, 3] > 20
        probs[:, :, 3] = np.where(fg, 0.92, 0.01)
        probs[:, :, 0] = np.where(~fg, 0.97, 0.02)
        return probs

    monkeypatch.setattr(vision_mod, "detect_face_pose", _fake_pose)
    monkeypatch.setattr(vision_mod, "segment_portrait_classes", _fake_seg)

    vp = suggest_safe_crop_viewport(face_im)
    head_asset = extract_clean_head_and_neck(face_im, is_pre_cutout=True, crop_viewport=vp)
    base_fit = fit_head_to_shirt_template(head_asset, collar)

    skin_counts: dict[float, int] = {}
    for nf in (0.0, 0.35, 0.70, 1.00, 1.40):
        card = compose_modular_df11(
            head_asset=head_asset,
            shirt_rgba=shirt,
            collar=collar,
            fit=HeadFitParams(
                scale=base_fit.scale,
                offset_x=base_fit.offset_x,
                offset_y=base_fit.offset_y,
                neck_fill=nf,
                harmonize=False,
            ),
            bg_mode="transparent",
        )
        arr = np.asarray(card)
        band = arr[184:218, 78:182]
        # Count warm skin pixels (R > 120, R > B + 15, alpha > 180) inside the collar opening band
        is_skin_px = (band[:, :, 3] > 180) & (band[:, :, 0] > 120) & (band[:, :, 0].astype(int) > band[:, :, 2].astype(int) + 15)
        skin_counts[nf] = int(is_skin_px.sum())

    assert skin_counts[0.0] < skin_counts[0.35] < skin_counts[0.70] < skin_counts[1.00] < skin_counts[1.40], skin_counts


def test_progressive_neck_narrows_already_wide_neck_and_unframes_transparent_wide_hair(monkeypatch) -> None:
    import backend.services.vision as vision_mod
    from backend.core.compositor import render_df11_card
    from backend.services.head_neck import HeadFitParams, prepare_facepack_card_for_head_extraction
    from backend.services.templates import extract_collar_profile
    from backend.services.vision import FacePose

    shirt = Image.new("RGBA", (DF11_WIDTH, DF11_HEIGHT), (0, 0, 0, 0))
    sdraw = ImageDraw.Draw(shirt)
    sdraw.polygon(
        [(19, 234), (86, 196), (130, 232), (174, 196), (241, 234), (241, 292), (19, 292)],
        fill=(25, 65, 145, 255),
    )
    collar = extract_collar_profile(shirt)

    # Portrait with an ALREADY WIDE real neck spanning x=76..180 all the way down to y=235
    face_im = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    fdraw = ImageDraw.Draw(face_im)
    fdraw.ellipse([78, 34, 178, 174], fill=(216, 165, 138, 255))
    fdraw.rectangle([76, 158, 180, 235], fill=(210, 158, 132, 255))

    def _fake_pose(_im: Image.Image, score_thresh: float = 0.55) -> FacePose:
        return FacePose(
            right_eye=(102.0, 106.0),
            left_eye=(154.0, 106.0),
            nose=(128.0, 132.0),
            eye_center=(128.0, 106.0),
            ipd=52.0,
            yaw=0.0,
            bbox=(76.0, 32.0, 104.0, 158.0),
        )

    def _fake_seg(im: Image.Image) -> np.ndarray:
        arr = np.asarray(im.convert("RGBA"))
        h, w = arr.shape[:2]
        probs = np.zeros((h, w, 6), dtype=np.float32)
        fg = arr[:, :, 3] > 20
        probs[:, :, 3] = np.where(fg, 0.92, 0.01)
        probs[:, :, 0] = np.where(~fg, 0.97, 0.02)
        return probs

    monkeypatch.setattr(vision_mod, "detect_face_pose", _fake_pose)
    monkeypatch.setattr(vision_mod, "segment_portrait_classes", _fake_seg)

    vp = suggest_safe_crop_viewport(face_im)
    head_asset = extract_clean_head_and_neck(face_im, is_pre_cutout=True, crop_viewport=vp)
    base_fit = fit_head_to_shirt_template(head_asset, collar)

    wide_counts: dict[float, int] = {}
    for nf in (0.0, 0.35, 0.70, 1.00, 1.40):
        card = compose_modular_df11(
            head_asset=head_asset,
            shirt_rgba=shirt,
            collar=collar,
            fit=HeadFitParams(
                scale=base_fit.scale,
                offset_x=base_fit.offset_x,
                offset_y=base_fit.offset_y,
                neck_fill=nf,
                harmonize=False,
            ),
            bg_mode="transparent",
        )
        arr = np.asarray(card)
        band = arr[184:218, 78:182]
        is_skin_px = (band[:, :, 3] > 180) & (band[:, :, 0] > 120) & (band[:, :, 0].astype(int) > band[:, :, 2].astype(int) + 15)
        wide_counts[nf] = int(is_skin_px.sum())

    assert wide_counts[0.0] < wide_counts[0.35] < wide_counts[0.70] < wide_counts[1.00] < wide_counts[1.40], wide_counts

    # Transparent DF11 card with wide dark hair covering upper-left window [24:90, 24:54] + chest while (40, 260) is (0,0,0,0)
    afro_person = Image.new("RGBA", (DF11_WIDTH, DF11_HEIGHT), (0, 0, 0, 0))
    adraw = ImageDraw.Draw(afro_person)
    adraw.rectangle([20, 20, 180, 140], fill=(28, 24, 22, 255))
    adraw.rectangle([90, 195, 170, 285], fill=(30, 60, 140, 255))
    trans_card = render_df11_card(afro_person, bg_mode="transparent")
    unframed, is_pre = prepare_facepack_card_for_head_extraction(trans_card)
    assert is_pre is False
    px_r, px_g, px_b, px_a = unframed.getpixel((40, 260))
    assert px_a == 255 and px_r > 200 and px_g > 200 and px_b > 200


def test_raised_head_preserves_cylindrical_neck_without_stretching_trapezius(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression test for QA Round 1 Point C: raising the head (offset_y < 0) must keep a cylindrical neck (~1.00-1.08x submandibular width) without flaring trapezius wings above the collar."""
    from backend.core.compositor import DF11_HEIGHT, DF11_WIDTH
    from backend.services.head_neck import (
        HeadFitParams,
        compose_modular_subject_rgba,
        extract_clean_head_and_neck,
        fit_head_to_shirt_template,
        suggest_safe_crop_viewport,
    )
    from backend.services.templates import extract_collar_profile
    from backend.services.vision import FacePose

    # Build a V-collar shirt (collar rims at x=82, y=206 and x=178, y=206, apex at x=130, y=236)
    shirt = Image.new("RGBA", (DF11_WIDTH, DF11_HEIGHT), (0, 0, 0, 0))
    sdraw = ImageDraw.Draw(shirt)
    sdraw.polygon(
        [(19, 232), (82, 206), (130, 236), (178, 206), (241, 232), (241, 292), (19, 292)],
        fill=(22, 24, 30, 255),
    )
    collar = extract_collar_profile(shirt)

    # Build a synthetic head with a cylindrical neck (width ~76 px: x=92..168) AND wide native trapezius wings below y=214 (width 136 px: x=62..198)
    face_im = Image.new("RGBA", (DF11_WIDTH, DF11_HEIGHT), (0, 0, 0, 0))
    fdraw = ImageDraw.Draw(face_im)
    fdraw.ellipse([78, 36, 182, 188], fill=(218, 174, 146, 255))
    # Cylindrical neck waist
    fdraw.rectangle([92, 168, 168, 214], fill=(212, 168, 140, 255))
    # Wide native trapezius flare in source portrait (which used to stretch upward when raising head)
    fdraw.polygon([(92, 206), (168, 206), (198, 248), (62, 248)], fill=(208, 164, 136, 255))

    def _fake_pose(_im: Image.Image, score_thresh: float = 0.55) -> FacePose:
        return FacePose(
            right_eye=(106.0, 108.0),
            left_eye=(154.0, 108.0),
            nose=(130.0, 134.0),
            eye_center=(130.0, 108.0),
            ipd=48.0,
            yaw=0.0,
            bbox=(80.0, 42.0, 100.0, 142.0),
        )

    def _fake_seg(im: Image.Image) -> np.ndarray:
        arr = np.asarray(im.convert("RGBA"))
        h, w = arr.shape[:2]
        probs = np.zeros((h, w, 6), dtype=np.float32)
        fg = arr[:, :, 3] > 20
        probs[:, :, 3] = np.where(fg, 0.94, 0.01)
        probs[:, :, 0] = np.where(~fg, 0.97, 0.02)
        return probs

    import backend.services.vision as vision_mod

    monkeypatch.setattr(vision_mod, "detect_face_pose", _fake_pose)
    monkeypatch.setattr(vision_mod, "segment_portrait_classes", _fake_seg)

    vp = suggest_safe_crop_viewport(face_im)
    head_asset = extract_clean_head_and_neck(face_im, is_pre_cutout=True, crop_viewport=vp)
    base_fit = fit_head_to_shirt_template(head_asset, collar)

    # Raise head by 16 px (offset_y - 16.0)
    raised_subj = compose_modular_subject_rgba(
        head_asset=head_asset,
        shirt_rgba=shirt,
        collar=collar,
        fit=HeadFitParams(
            scale=base_fit.scale,
            offset_x=base_fit.offset_x,
            offset_y=base_fit.offset_y - 16.0,
            neck_fill=1.0,
            harmonize=False,
        ),
    )
    subj_arr = np.asarray(raised_subj, dtype=np.uint8)
    shirt_arr = np.asarray(shirt, dtype=np.uint8)

    # Measure skin width just below the chin (submandibular waist) vs 4 px above the collar rim (y = 200)
    waist_row = subj_arr[172, :, 3] > 180
    waist_w = int(waist_row.sum())
    above_collar_skin = (subj_arr[200, :, 3] > 180) & (shirt_arr[200, :, 3] < 30)
    above_collar_w = int(above_collar_skin.sum())

    assert waist_w >= 60
    assert above_collar_w <= int(round(waist_w * 1.08)) + 2, (
        f"Neck above collar must remain cylindrical (got {above_collar_w}px vs waist {waist_w}px)"
    )


def test_headless_torso_white_shirt_extraction_clears_shoulder_air_and_keeps_white_chest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression test for QA Round 1 Point D: headless torso snip (panY=+84) on white background removes shoulder towers while keeping white chest intact."""
    import backend.services.vision as vision_mod
    from backend.services.templates import sanitize_shirt_template_rgba

    # Create a 270x140 headless torso crop on a bright white background (252, 252, 252)
    torso = Image.new("RGBA", (270, 140), (252, 252, 252, 255))
    tdraw = ImageDraw.Draw(torso)
    # Neck skin at top-center (y=0..42, x=98..172)
    tdraw.polygon([(98, 0), (172, 0), (160, 48), (110, 48)], fill=(214, 170, 142, 255))
    # Black sleeves on outer shoulders + white chest with red diagonal sash in center
    tdraw.polygon([(12, 52), (88, 18), (135, 52), (182, 18), (258, 52), (264, 139), (6, 139)], fill=(246, 246, 248, 255))
    tdraw.polygon([(12, 52), (82, 22), (62, 139), (6, 139)], fill=(22, 24, 28, 255))
    tdraw.polygon([(188, 22), (258, 52), (264, 139), (208, 139)], fill=(22, 24, 28, 255))

    def _fake_seg(im: Image.Image) -> np.ndarray:
        arr = np.asarray(im.convert("RGBA"))
        h, w = arr.shape[:2]
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        x1 = xx / 2.0
        y1 = yy / 2.0
        probs = np.zeros((h, w, 6), dtype=np.float32)
        in_Placed = (y1 >= 160.0) & (y1 <= 292.0)
        # Simulated slope of shoulders from y=178 at collar to y=210 at x=25/235
        shoulder_line = 176.0 + 0.36 * np.maximum(0.0, np.abs(x1 - 130.0) - 42.0)
        is_neck = in_Placed & (np.abs(x1 - 130.0) < 34.0) & (y1 < 208.0)
        is_shirt = in_Placed & (~is_neck) & (y1 >= shoulder_line)
        probs[:, :, vision_mod.CLASS_BODY_SKIN] = np.where(is_neck, 0.92, 0.02)
        probs[:, :, vision_mod.CLASS_CLOTHES] = np.where(is_shirt, 0.90, 0.03)
        probs[:, :, vision_mod.CLASS_BG] = np.where(~(is_neck | is_shirt), 0.92, 0.04)
        return probs

    def _fake_biref(im: Image.Image) -> Image.Image:
        arr = np.asarray(im.convert("RGBA")).copy()
        h, w = arr.shape[:2]
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        x1 = xx / 2.0
        y1 = yy / 2.0
        shoulder_line = 176.0 + 0.36 * np.maximum(0.0, np.abs(x1 - 130.0) - 42.0)
        fg = (y1 >= 160.0) & ((y1 >= shoulder_line) | (np.abs(x1 - 130.0) < 34.0))
        arr[:, :, 3] = np.where(fg, 255, 0).astype(np.uint8)
        return Image.fromarray(arr, mode="RGBA")

    monkeypatch.setattr(vision_mod, "segment_portrait_classes", _fake_seg)
    monkeypatch.setattr(vision_mod, "remove_background_birefnet", _fake_biref)

    cleaned = sanitize_shirt_template_rgba(torso, zoom=1.0, pan_x=0.0, pan_y=84.0, symmetrize_shoulders=True)
    c_arr = np.asarray(cleaned, dtype=np.uint8)
    alpha = c_arr[:, :, 3]

    # Above outer shoulders (y=162..182, x=25..65 and x=195..235) must have zero white towers
    left_air = int((alpha[162:182, 25:65] > 24).sum())
    right_air = int((alpha[162:182, 195:235] > 24).sum())
    assert left_air == 0 and right_air == 0, f"Expected 0 white tower pixels above shoulders, got L={left_air}, R={right_air}"

    # Central white chest (y=235..275, x=105..155) must remain solid
    chest_solid = int((alpha[235:275, 105:155] > 220).sum())
    assert chest_solid >= int(40 * 50 * 0.90), f"White chest must remain solid, got {chest_solid}/{40*50}"



