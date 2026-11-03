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
        probs = np.zeros((h, w, 6), dtype=np.float32)
        is_skin = (arr[:, :, 0] > 205) & (arr[:, :, 1] < 190)
        probs[:, :, 2] = np.where(is_skin, 0.94, 0.01)
        # Simulate MediaPipe 256x256 confusing white sleeves (|x-130|>45) with white background (p_clothes=0.03)!
        yy, xx = np.mgrid[0:h, 0:w]
        center_cloth = (yy >= 181) & (np.abs(xx - 130) <= 45) & ~is_skin
        probs[:, :, 4] = np.where(center_cloth, 0.90, 0.03)
        probs[:, :, 0] = np.clip(1.0 - probs[:, :, 2] - probs[:, :, 4], 0.0, 1.0)
        return probs

    def _fake_biref(im: Image.Image) -> Image.Image:
        # Simulate ItalMed9 asymmetry: BiRefNet finds right white shoulder (x>=130) at 255, misses left outer tip
        out = Image.new("RGBA", im.size, (0, 0, 0, 0))
        mask = Image.new("L", im.size, 0)
        mdraw = ImageDraw.Draw(mask)
        mdraw.ellipse([82, 42, 178, 178], fill=255)
        mdraw.polygon([(60, 214), (86, 181), (174, 181), (241, 214), (241, 292), (60, 292)], fill=255)
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
