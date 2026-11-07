"""Forensic DF11 Pure (220x276 RGBA) compositor, corner healing, Zero-AI Direct Photo, and 1:1 round-trip tests."""

from __future__ import annotations

import io
import struct
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
from PIL import Image, ImageDraw

from backend.core.compositor import (
    DF11_HEIGHT,
    DF11_WIDTH,
    export_df11_bytes,
    load_df11_assets,
    render_df11_card,
)
from backend.core.paths import WORKSPACE_ROOT
from backend.services.head_neck import (
    HeadFitParams,
    HeadNeckAsset,
    CropViewport,
    prepare_facepack_card_for_head_extraction,
)
from backend.services.studio_workflow import ModularWorkflowSession
from backend.services.templates import CollarProfile, _frame_to_df11_stage


def _extract_png_phys(png_bytes: bytes) -> tuple[int, int, int] | None:
    pos = 8
    while pos + 8 <= len(png_bytes):
        length = struct.unpack(">I", png_bytes[pos : pos + 4])[0]
        ctype = png_bytes[pos + 4 : pos + 8]
        chunk_data = png_bytes[pos + 8 : pos + 8 + length]
        if ctype == b"pHYs" and length == 9:
            return struct.unpack(">IIB", chunk_data)
        pos += 12 + length
    return None


def _make_synthetic_head_asset() -> HeadNeckAsset:
    rgba = np.zeros((DF11_HEIGHT, DF11_WIDTH, 4), dtype=np.uint8)
    skin = np.zeros((DF11_HEIGHT, DF11_WIDTH), dtype=np.uint8)
    body = np.zeros((DF11_HEIGHT, DF11_WIDTH), dtype=np.uint8)
    occ = np.zeros((DF11_HEIGHT, DF11_WIDTH), dtype=np.uint8)
    yy, xx = np.mgrid[0:DF11_HEIGHT, 0:DF11_WIDTH]
    head_ellipse = (((xx - 130.0) / 42.0) ** 2 + ((yy - 112.0) / 56.0) ** 2) <= 1.0
    neck_rect = (np.abs(xx - 130.0) <= 22.0) & (yy >= 150) & (yy <= 215)
    fg = head_ellipse | neck_rect
    rgba[fg] = (214, 168, 142, 255)
    skin[head_ellipse] = 255
    body[neck_rect] = 255
    return HeadNeckAsset(
        rgba=Image.fromarray(rgba, mode="RGBA"),
        skin_mask=Image.fromarray(skin, mode="L"),
        body_skin_mask=Image.fromarray(body, mode="L"),
        front_occluder_alpha=Image.fromarray(occ, mode="L"),
        pose=None,
        crown_y=56,
        chin_y=168.0,
        skin_oklab=(0.74, 0.035, 0.062),
        viewport=CropViewport(),
    )


def _make_legacy_curved_corner_shirt() -> tuple[Image.Image, CollarProfile]:
    """Simulate an existing shirt template in tshirt_templates/ whose corners were bitten by df11_inner_mask."""
    inner_mask_im, _ = load_df11_assets()
    mask_f = np.asarray(inner_mask_im, dtype=np.float32) / 255.0
    arr = np.zeros((DF11_HEIGHT, DF11_WIDTH, 4), dtype=np.uint8)
    yy, xx = np.mgrid[0:DF11_HEIGHT, 0:DF11_WIDTH]
    torso = (yy >= 198) & (yy < 293) & (xx >= 19) & (xx < 242)
    v_cut = (yy < 226) & (np.abs(xx - 130) < (226 - yy) * 1.35)
    fabric = torso & ~v_cut
    arr[fabric, :3] = (172, 18, 34)
    arr[fabric, 3] = np.clip(np.round(255.0 * mask_f[fabric]), 0.0, 255.0).astype(np.uint8)
    # Simulate dark bevel contamination at bottom-left/right corners like ItalMed0.png
    arr[290:293, 20:24, :3] = (74, 4, 22)
    arr[290:293, 236:240, :3] = (74, 4, 22)
    collar = CollarProfile(
        left_rim=(92, 198),
        right_rim=(168, 198),
        apex=(130, 226),
        collar_width=76,
        y_top_curve=tuple([198] * DF11_WIDTH),
    )
    return Image.fromarray(arr, mode="RGBA"), collar


def test_render_df11_pure_card_spec_corner_healing_and_png_phys() -> None:
    from backend.core.compositor import DF11_PURE_HEIGHT, DF11_PURE_WIDTH, render_df11_pure_card
    from backend.services.head_neck import compose_modular_subject_rgba

    head = _make_synthetic_head_asset()
    legacy_shirt, collar = _make_legacy_curved_corner_shirt()
    # Precondition: legacy shirt indeed has curved transparency bite at (292, 20)
    legacy_arr = np.asarray(legacy_shirt)
    assert legacy_arr[292, 20, 3] < 32

    subject = compose_modular_subject_rgba(
        head_asset=head,
        shirt_rgba=legacy_shirt,
        collar=collar,
        fit=HeadFitParams(),
        enhance_quality=0.5,
    )
    assert subject.size == (DF11_WIDTH, DF11_HEIGHT)
    subj_arr = np.asarray(subject)
    # Subject background must be strictly Alpha == 0 with zero frame bevel pixels
    assert int(subj_arr[25:80, 22:60, 3].max()) == 0

    pure = render_df11_pure_card(subject)
    assert pure.size == (DF11_PURE_WIDTH, DF11_PURE_HEIGHT) == (220, 276)
    p_arr = np.asarray(pure)

    # Top background must be strictly Alpha == 0 and RGB == (0,0,0)
    assert int(p_arr[5:55, 5:45, 3].max()) == 0
    assert int(p_arr[5:55, 5:45, :3].max()) == 0

    # Bottom shirt interior (including healed 6x6 corner zones inside 1px feather) must be solid Alpha == 255
    assert int(p_arr[270:275, 1:219, 3].min()) == 255
    # Healed corner color must match clean red shirt (~172), not dark bevel (74)
    assert int(p_arr[274, 1, 0]) >= 150
    assert int(p_arr[274, 218, 0]) >= 150

    # 1px perimeter feather on left/right/bottom shirt edges (~220/255) and bottom corners (~185..191/255)
    assert 215 <= int(p_arr[250, 0, 3]) <= 224
    assert 215 <= int(p_arr[250, 219, 3]) <= 224
    assert 215 <= int(p_arr[275, 110, 3]) <= 224
    assert 185 <= int(p_arr[275, 0, 3]) <= 192
    assert 185 <= int(p_arr[275, 219, 3]) <= 192

    # PNG export writes 72 DPI (2835 ppm) and preserves 220x276; JPG is forbidden on Pure
    png_bytes = export_df11_bytes(pure, fmt="png")
    decoded = Image.open(io.BytesIO(png_bytes))
    assert decoded.size == (220, 276)
    assert decoded.mode == "RGBA"
    assert _extract_png_phys(png_bytes) == (2835, 2835, 1)

    with pytest.raises(ValueError, match="PNG"):
        export_df11_bytes(pure, fmt="jpg")


def test_pure_220x276_roundtrip_across_direct_photo_shirt_stage_and_head_prep(tmp_path: Path) -> None:
    from backend.core.compositor import pad_pure_to_df11_canvas, render_df11_pure_card

    # Build a crisp synthetic 220x276 Pure card with high-frequency 1px checkerboard crest
    src_260 = np.zeros((310, 260, 4), dtype=np.uint8)
    yy, xx = np.mgrid[0:310, 0:260]
    person = (((xx - 130.0) / 40.0) ** 2 + ((yy - 112.0) / 54.0) ** 2 <= 1.0) | ((yy >= 198) & (yy < 293) & (xx >= 20) & (xx < 240))
    src_260[person] = (30, 90, 190, 255)
    # 1px checkerboard crest at (x=155..175, y=230..250) to catch any resampling blur!
    crest = (yy >= 230) & (yy < 250) & (xx >= 155) & (xx < 175)
    checker = ((xx + yy) % 2) == 0
    src_260[crest & checker] = (250, 240, 40, 255)
    src_260[crest & ~checker] = (20, 25, 35, 255)

    pure_card = render_df11_pure_card(Image.fromarray(src_260, mode="RGBA"))
    pure_bytes = export_df11_bytes(pure_card, fmt="png")

    # 1. Direct Photo round-trip: must hit eff_scale == 1.0 fast-path with ZERO resampling blur on 1px crest
    sess = ModularWorkflowSession(
        templates_dir=tmp_path / "tpls",
        raw_archive_dir=tmp_path / "arch",
        extracted_faces_dir=tmp_path / "faces",
        sample_faces_dir=tmp_path / "samples",
        db_path=tmp_path / "state.sqlite3",
    )
    loaded = sess.load_direct_photo(pure_bytes, file_name="29184012.png")
    assert loaded["detectedUid"] == "29184012"
    assert loaded["isPreCutout"] is True

    re_pure = sess.compose_step_card(
        {
            "step1Mode": "direct_photo",
            "directPhotoId": loaded["directPhotoId"],
            "scale": 1.0,
            "offsetX": 0.0,
            "offsetY": 0.0,
            "harmonize": False,
            "enhanceQuality": 0.0,
        },
        variant="pure",
    )
    assert re_pure.size == (220, 276)
    orig_crest = np.asarray(pure_card)[230 - 17 : 250 - 17, 155 - 20 : 175 - 20]
    rt_crest = np.asarray(re_pure)[230 - 17 : 250 - 17, 155 - 20 : 175 - 20]
    assert np.array_equal(orig_crest, rt_crest), "1px crest must survive Direct Photo round-trip bit-exact without resampling"

    # 2. _frame_to_df11_stage (Shirt Extractor): must place at (20, 17) with 0% scale blow-up
    staged = _frame_to_df11_stage(pure_card, zoom=1.0, pan_x=0.0, pan_y=0.0, scale_mult=1)
    assert staged.size == (260, 310)
    staged_crest = np.asarray(staged)[230:250, 155:175]
    assert np.array_equal(staged_crest, src_260[230:250, 155:175]), "Shirt stage must map Pure card 1:1 to (20, 17)"

    # 3. prepare_facepack_card_for_head_extraction: must wrap to (260, 310) with is_precut=True
    prep_head, is_pre = prepare_facepack_card_for_head_extraction(pure_card, default_is_precut=True)
    assert prep_head.size == (260, 310)
    assert is_pre is True
    assert np.array_equal(np.asarray(prep_head)[230:250, 155:175], src_260[230:250, 155:175])
    assert pad_pure_to_df11_canvas(pure_card).size == (260, 310)


def test_direct_photo_pure_and_batch_sync_zero_ai_contract(tmp_path: Path) -> None:
    # 1. Subprocess test blocking onnxruntime completely across Studio Direct Photo, Classic->Pure, and Batch Sync!
    code = """
import io, sys
from pathlib import Path
sys.modules["onnxruntime"] = None
import numpy as np
from PIL import Image, ImageDraw
from backend.core.compositor import pad_pure_to_df11_canvas, render_df11_card
from backend.core.fm_config import upsert_fm_config_xml
from backend.services.studio_workflow import ModularWorkflowSession
from backend.services.sync import sync_ng_regens_batch

sess = ModularWorkflowSession(
    templates_dir=Path(%r),
    raw_archive_dir=Path(%r),
    extracted_faces_dir=Path(%r),
    sample_faces_dir=Path(%r),
    db_path=Path(%r),
)
# A. Transparent PNG works in Pure with 0%% AI
rgba = np.zeros((276, 220, 4), dtype=np.uint8)
rgba[40:275, 20:200] = (180, 40, 50, 255)
buf = io.BytesIO()
Image.fromarray(rgba, "RGBA").save(buf, format="PNG")
res = sess.load_direct_photo(buf.getvalue(), "cut.png")
pure_im = sess.compose_step_card({"step1Mode": "direct_photo", "directPhotoId": res["directPhotoId"]}, variant="pure")
assert pure_im.size == (220, 276)

# B. Opaque portrait (white shirt on white studio background!) cleans contour with 0%% AI in Pure & Dual
gt_pure = Image.new("RGBA", (220, 276), (0, 0, 0, 0))
d = ImageDraw.Draw(gt_pure)
d.ellipse([70, 24, 150, 140], fill=(205, 160, 135, 255))
d.rectangle([90, 128, 130, 185], fill=(195, 150, 125, 255))
# White shirt with dark collar on white studio backdrop (full DF11 shoulder span to side borders)
d.polygon([(0, 275), (0, 206), (82, 174), (138, 174), (219, 206), (219, 275)], fill=(240, 241, 244, 255))
d.arc([74, 156, 146, 208], start=10, end=170, fill=(28, 30, 35, 255), width=8)
# Subtle shoulder seam shadow along full shoulder slope so geodesic + gradient locks onto white-on-white shoulder
d.line([(0, 206), (82, 174)], fill=(198, 201, 207, 255), width=2)
d.line([(138, 174), (219, 206)], fill=(198, 201, 207, 255), width=2)

classic_card = render_df11_card(portrait_rgba=pad_pure_to_df11_canvas(gt_pure, unfeather_edges=True), bg_mode="white_df11")
opaque_portrait = Image.new("RGBA", (220, 276), (246, 247, 249, 255))
opaque_portrait.alpha_composite(gt_pure)
buf_op = io.BytesIO()
opaque_portrait.convert("RGB").save(buf_op, format="JPEG", quality=95)

res_op = sess.load_direct_photo(buf_op.getvalue(), "raw.jpg", extra_params={"previewVariant": "pure"})
assert res_op["isPreCutout"] is False
c_dual, p_dual = sess.compose_step_dual_cards(
    {"step1Mode": "direct_photo", "directPhotoId": res_op["directPhotoId"], "bgMode": "transparent", "harmonize": False}
)
c_arr = np.asarray(c_dual)
p_arr = np.asarray(p_dual)
# Classic preserves opaque background inside inner window when directBgReplace=False
assert int(c_arr[30, 35, 3]) == 255
# Pure cleans upper corners to Alpha == 0 with 0%% AI!
assert int(p_arr[:30, :16, 3].max()) == 0
assert int(p_arr[:30, -16:, 3].max()) == 0
gt_mask = np.asarray(gt_pure)[:, :, 3] > 127
pred_mask = p_arr[:, :, 3] > 127
iou = float((gt_mask & pred_mask).sum()) / max(float((gt_mask | pred_mask).sum()), 1.0)
assert iou >= 0.92, f"Expected white-on-white Zero-AI IoU >= 0.92, got {iou:.3f}"

# C. Classic 260x310 facepack card -> Pure (0%% AI bevel unmix + contour clean)
buf_card = io.BytesIO()
classic_card.save(buf_card, format="PNG")
fp_res = sess.load_facepack_card_for_pure(buf_card.getvalue(), "1915386672.png")
assert fp_res["detectedUid"] == "1915386672"

# D. Batch NG_Regens sync in Dual mode with apply_club_kits=False runs 100%% Zero-AI
vault = Path(%r)
vault.mkdir(parents=True, exist_ok=True)
classic_card.save(vault / "2002042001.png")
upsert_fm_config_xml(vault / "config.xml", ["2002042001"])
out_c = Path(%r)
out_p = Path(%r)
sync_res = sync_ng_regens_batch(
    vault_dir=vault,
    out_dir=out_c,
    pure_out_dir=out_p,
    db_path=Path(%r),
    apply_club_kits=False,
    harmonize=True,
    variant="dual",
)
assert sync_res.processed == 1 and sync_res.failed == 0
p_synced = np.asarray(Image.open(out_p / "2002042001.png").convert("RGBA"))
assert p_synced.shape == (276, 220, 4)
assert int(p_synced[:30, :16, 3].max()) == 0
assert "onnxruntime" not in sys.modules or sys.modules["onnxruntime"] is None
""" % (
        str(tmp_path / "t"),
        str(tmp_path / "a"),
        str(tmp_path / "f"),
        str(tmp_path / "s"),
        str(tmp_path / "db.sqlite3"),
        str(tmp_path / "vault"),
        str(tmp_path / "out_c"),
        str(tmp_path / "out_p"),
        str(tmp_path / "sync_db.sqlite3"),
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(WORKSPACE_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, f"Subprocess failed:\nSTDOUT: {proc.stdout}\nSTDERR: {proc.stderr}"

    # 2. LRU Zero-AI cache reuses contour across optical slider changes (enhanceQuality) and invalidates on tolerance/pan
    sess = ModularWorkflowSession(
        templates_dir=tmp_path / "t2",
        raw_archive_dir=tmp_path / "a2",
        extracted_faces_dir=tmp_path / "f2",
        sample_faces_dir=tmp_path / "s2",
        db_path=tmp_path / "db2.sqlite3",
    )
    opaque_buf = io.BytesIO()
    Image.new("RGB", (260, 310), (90, 110, 130)).save(opaque_buf, format="PNG")
    loaded = sess.load_direct_photo(opaque_buf.getvalue(), "jugador.png")
    did = loaded["directPhotoId"]
    assert loaded["isPreCutout"] is False

    import backend.services.studio_workflow as sw_mod

    with patch.object(sw_mod, "clean_pure_contour_zero_ai", wraps=sw_mod.clean_pure_contour_zero_ai) as m_zero_ai:
        c_im, p_im = sess.compose_step_dual_cards(
            {"step1Mode": "direct_photo", "directPhotoId": did, "enhanceQuality": 0.1, "pureContourTolerance": 0.5}
        )
        assert c_im.size == (260, 310)
        assert p_im.size == (220, 276)
        assert m_zero_ai.call_count == 1
        # Changing enhanceQuality or bgMode hits the pre-enhance Zero-AI LRU cache (0 extra geodesic calls!)
        sess.compose_step_dual_cards(
            {"step1Mode": "direct_photo", "directPhotoId": did, "enhanceQuality": 0.85, "pureContourTolerance": 0.5}
        )
        assert m_zero_ai.call_count == 1
        # Changing pureContourTolerance recomputes cleanly
        sess.compose_step_card(
            {"step1Mode": "direct_photo", "directPhotoId": did, "pureContourTolerance": 0.72},
            variant="pure",
        )
        assert m_zero_ai.call_count == 2
