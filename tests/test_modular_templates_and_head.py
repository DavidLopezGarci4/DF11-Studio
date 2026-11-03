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

