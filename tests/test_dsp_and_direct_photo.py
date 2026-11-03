from __future__ import annotations

import base64
import io
from pathlib import Path
import subprocess
import sys
import time

import numpy as np
from PIL import Image, ImageDraw
import pytest

from backend.bridge import StudioBridge
from backend.core.compositor import DF11_HEIGHT, DF11_WIDTH, render_df11_card


def _png_data_url(im: Image.Image) -> str:
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def _decode_data_url_rgba(data_url: str) -> np.ndarray:
    raw = base64.b64decode(data_url.split(",", 1)[1])
    return np.asarray(Image.open(io.BytesIO(raw)).convert("RGBA"), dtype=np.uint8)


def test_dsp_module_is_strictly_zero_ai_and_zero_onnxruntime() -> None:
    code = (
        "import sys; sys.modules['onnxruntime'] = None; "
        "import backend.core.dsp as dsp; "
        "import numpy as np; from PIL import Image; "
        "im = Image.new('RGBA', (260, 310), (180, 140, 120, 255)); "
        "out = dsp.enhance_df11_pure_optics(np.asarray(im), amount=0.6); "
        "assert out.shape == (310, 260, 4)"
    )
    res = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 0, res.stderr


def test_linear_subpixel_resampler_and_shirt_alpha_no_double_premultiply(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.core.dsp import resample_linear_subpixel_rgba
    from backend.services.templates import sanitize_shirt_template_rgba
    import backend.services.vision as vision_mod

    # 1. Red/green 2x2 pixel checkerboard downscaled 2x -> linear-light optical yellow (~188, 188, 0), NOT gamma mud (~127, 127, 0)
    rg = np.zeros((620, 520, 4), dtype=np.uint8)
    rg[:, :, 3] = 255
    mask_odd = (np.indices((620, 520)).sum(axis=0) % 2) == 0
    rg[mask_odd, 0] = 255
    rg[~mask_odd, 1] = 255
    out_lin = resample_linear_subpixel_rgba(Image.fromarray(rg, mode="RGBA"), zoom=1.0, pan_x=0.0, pan_y=0.0, fit_mode="contain")
    mid_px = out_lin[155, 130]
    assert int(mid_px[0]) >= 170 and int(mid_px[1]) >= 170, mid_px

    # 2. Semi-transparent gray shirt border (RGB=180, alpha=128) must NOT blow up to RGB=255 via double premultiplication
    def _fake_seg(im: Image.Image) -> np.ndarray:
        h, w = im.height, im.width
        probs = np.zeros((h, w, 6), dtype=np.float32)
        probs[:, :, 4] = 0.96
        return probs

    monkeypatch.setattr(vision_mod, "segment_portrait_classes", _fake_seg)
    monkeypatch.setattr(vision_mod, "remove_background_birefnet", lambda im: im.convert("RGBA"))

    semi_shirt = Image.new("RGBA", (DF11_WIDTH, DF11_HEIGHT), (0, 0, 0, 0))
    arr_s = np.asarray(semi_shirt, dtype=np.uint8).copy()
    arr_s[210:285, 50:210] = (180, 180, 180, 255)
    arr_s[208:210, 50:210] = (180, 180, 180, 128)
    clean_shirt = np.asarray(sanitize_shirt_template_rgba(Image.fromarray(arr_s, mode="RGBA"), symmetrize_shoulders=False, detail_crispness=0.0))
    semi_band = clean_shirt[207:211, 90:170]
    semi_pixels = semi_band[(semi_band[:, :, 3] > 40) & (semi_band[:, :, 3] < 220)]
    assert len(semi_pixels) > 0
    assert int(semi_pixels[:, 0].max()) <= 205, semi_pixels[:, 0].max()


def test_wgif_pure_optics_enhances_micro_detail_without_halos_or_frame_ringing() -> None:
    from backend.core.dsp import deblock_jpeg_8x8_roi

    # Portrait with fine eye/fabric detail on left half and sharp dark silhouette (RGB=28) against white_df11 (RGB=246) on right half
    portrait = Image.new("RGBA", (DF11_WIDTH, DF11_HEIGHT), (246, 246, 246, 255))
    arr = np.asarray(portrait, dtype=np.uint8).copy()
    yy, xx = np.mgrid[0:DF11_HEIGHT, 0:DF11_WIDTH]
    fine_tex = ((xx // 2 + yy // 2) % 2 == 0) & (xx >= 45) & (xx <= 115) & (yy >= 80) & (yy <= 220)
    arr[fine_tex] = (148, 128, 116, 255)
    arr[(~fine_tex) & (xx >= 45) & (xx <= 115) & (yy >= 80) & (yy <= 220)] = (168, 146, 132, 255)
    # High-contrast dark hair/suit block next to bright studio background
    arr[(xx >= 150) & (xx <= 210) & (yy >= 70) & (yy <= 250)] = (28, 30, 34, 255)
    # Saturated red badge (#EF0107) with subtle crest line
    arr[(xx >= 70) & (xx <= 100) & (yy >= 235) & (yy <= 265)] = (239, 1, 7, 255)
    arr[(xx == 85) & (yy >= 240) & (yy <= 260)] = (205, 12, 16, 255)

    src_im = Image.fromarray(arr, mode="RGBA")
    c0 = np.asarray(render_df11_card(src_im, bg_mode="white_df11", enhance_quality=0.0))
    c5 = np.asarray(render_df11_card(src_im, bg_mode="white_df11", enhance_quality=0.5))
    c10 = np.asarray(render_df11_card(src_im, bg_mode="white_df11", enhance_quality=1.0))

    std0 = float(c0[95:205, 55:105, :3].astype(np.float32).std())
    std5 = float(c5[95:205, 55:105, :3].astype(np.float32).std())
    std10 = float(c10[95:205, 55:105, :3].astype(np.float32).std())
    assert std0 < std5 < std10, (std0, std5, std10)

    # Zero bright halo overshoot outside the dark hair/suit edge (background was 246 -> must NOT spike to 254-255)
    bg_next_to_edge = c10[90:230, 146:150, 0]
    assert int(bg_next_to_edge.max()) <= 249, int(bg_next_to_edge.max())

    # Punched outer ring stays strictly Alpha == 0
    assert int(c10[12:16, 40:220, 3].max()) == 0
    assert int(c10[40:270, 11:18, 3].max()) == 0

    # Saturated red badge keeps red dominance (no hue shift into yellow/orange: G stays low)
    badge_px = c10[245, 78]
    assert int(badge_px[0]) > 215 and int(badge_px[1]) < 35

    # Deterministic 8x8 JPEG blockiness reduction
    blocky = np.zeros((64, 64, 3), dtype=np.float32)
    for by in range(8):
        for bx in range(8):
            blocky[by * 8 : (by + 1) * 8, bx * 8 : (bx + 1) * 8] = 110.0 + ((bx + by) % 2) * 10.0
    deblocked = deblock_jpeg_8x8_roi(blocky)
    seam_before = float(np.abs(blocky[:, 8, 0] - blocky[:, 7, 0]).mean())
    seam_after = float(np.abs(deblocked[:, 8, 0] - deblocked[:, 7, 0]).mean())
    assert seam_after < seam_before


def test_direct_photo_mode_supports_4_cardinal_pan_zoom_and_export_with_zero_ai(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import backend.services.vision as vision_mod

    def _forbid_ai(*_a: object, **_kw: object) -> None:
        raise AssertionError("ONNX AI must NEVER be invoked in Direct Photo + DF11 Frame or Pure-Optics quality mode!")

    monkeypatch.setattr(vision_mod, "detect_face_pose", _forbid_ai)
    monkeypatch.setattr(vision_mod, "segment_portrait_classes", _forbid_ai)
    monkeypatch.setattr(vision_mod, "remove_background_birefnet", _forbid_ai)

    # Create a horizontal press photo (420x280) with a bright gold star marker at center (210, 140) on dark navy
    photo = Image.new("RGB", (420, 280), (22, 38, 72))
    pdraw = ImageDraw.Draw(photo)
    pdraw.ellipse([194, 124, 226, 156], fill=(250, 210, 40))
    data_url = _png_data_url(photo)

    export_dir = tmp_path / "exports"
    bridge = StudioBridge(
        vault_dir=tmp_path / "vault_ro",
        export_dir=export_dir,
        db_path=tmp_path / "direct.sqlite3",
        templates_dir=tmp_path / "tshirt_templates",
        raw_archive_dir=tmp_path / "raw_archive",
        extracted_faces_dir=tmp_path / "caras_extraidas",
        sample_faces_dir=tmp_path / "caras_prueba",
    )

    loaded = bridge.load_direct_photo_source(data_url, "29184012.png", {"enhanceQuality": 0.5})
    direct_id = loaded["directPhotoId"]
    assert direct_id.startswith("direct-")
    assert loaded["detectedUid"] == "29184012"
    base_card = _decode_data_url_rgba(loaded["previewDataUrl"])
    assert base_card.shape == (DF11_HEIGHT, DF11_WIDTH, 4)
    # Punched outer ring strictly Alpha == 0, while top/bottom inside DF11 window have NO empty white bars (cover fit!)
    assert int(base_card[12:16, 40:220, 3].max()) == 0
    assert int(base_card[30, 130, 2]) > 45 and int(base_card[30, 130, 0]) < 80
    assert int(base_card[280, 130, 2]) > 45 and int(base_card[280, 130, 0]) < 80

    def _gold_centroid(pan_x: float, pan_y: float, scale: float = 1.35) -> tuple[float, float]:
        res = bridge.render_modular_preview(
            {
                "step1Mode": "direct_photo",
                "directPhotoId": direct_id,
                "scale": scale,
                "offsetX": pan_x,
                "offsetY": pan_y,
                "clampPan": True,
                "harmonize": False,
                "enhanceQuality": 0.4,
                "bgMode": "white_df11",
            }
        )
        arr = _decode_data_url_rgba(res["previewDataUrl"])
        inner = arr[25:285, 25:235]
        gold = (inner[:, :, 0] > 200) & (inner[:, :, 1] > 160) & (inner[:, :, 2] < 90)
        ys, xs = np.nonzero(gold)
        assert len(xs) > 10
        return float(xs.mean() + 25.0), float(ys.mean() + 25.0)

    cx0, cy0 = _gold_centroid(0.0, 0.0)
    _, cy_north = _gold_centroid(0.0, -20.0)
    _, cy_south = _gold_centroid(0.0, +20.0)
    cx_west, _ = _gold_centroid(-20.0, 0.0)
    cx_east, _ = _gold_centroid(+20.0, 0.0)

    assert cy_north < cy0 < cy_south, (cy_north, cy0, cy_south)
    assert cx_west < cx0 < cx_east, (cx_west, cx0, cx_east)

    # Export direct photo card without any headAssetId or shirt templateId!
    exp = bridge.export_modular_card(
        {
            "uid": "29184012",
            "exportTarget": "creations",
            "step1Mode": "direct_photo",
            "directPhotoId": direct_id,
            "scale": 1.25,
            "offsetX": 10.0,
            "offsetY": -8.0,
            "clampPan": True,
            "enhanceQuality": 0.65,
            "fmt": "png",
            "updateConfigXml": True,
        }
    )
    assert Path(exp["savedPath"]).is_file()

    # Evicted/unknown directPhotoId must raise ValueError cleanly
    with pytest.raises(ValueError, match="foto directa"):
        bridge.export_modular_card(
            {
                "uid": "29184012",
                "exportTarget": "creations",
                "step1Mode": "direct_photo",
                "directPhotoId": "direct-9999",
            }
        )


def test_studio_bridge_direct_photo_works_with_onnxruntime_blocked_in_subprocess(tmp_path: Path) -> None:
    root_dir = Path(__file__).resolve().parents[1]
    code = f"""
import base64, io, sys
from pathlib import Path
sys.modules['onnxruntime'] = None
from PIL import Image
from backend.bridge import StudioBridge

assert sys.modules.get('onnxruntime') is None
tmp = Path({str(tmp_path)!r})
im = Image.new('RGB', (360, 440), (42, 68, 108))
buf = io.BytesIO()
im.save(buf, format='PNG')
durl = 'data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode('ascii')

bridge = StudioBridge(
    vault_dir=tmp / 'vault',
    export_dir=tmp / 'exports',
    db_path=tmp / 'no_ort.sqlite3',
    templates_dir=tmp / 'tpls',
    raw_archive_dir=tmp / 'raw',
    extracted_faces_dir=tmp / 'faces',
    sample_faces_dir=tmp / 'samples',
)
loaded = bridge.load_direct_photo_source(durl, '19004512.png', {{'harmonize': True, 'enhanceQuality': 0.6}})
prev = bridge.render_modular_preview({{
    'step1Mode': 'direct_photo',
    'directPhotoId': loaded['directPhotoId'],
    'scale': 1.15,
    'offsetX': 6.0,
    'offsetY': -4.0,
    'clampPan': True,
    'harmonize': True,
    'enhanceQuality': 0.7,
    'bgMode': 'white_df11',
}})
raw_out = base64.b64decode(prev['previewDataUrl'].split(',', 1)[1])
out_im = Image.open(io.BytesIO(raw_out))
assert out_im.size == (260, 310)
assert sys.modules.get('onnxruntime') is None
"""
    res = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(root_dir),
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 0, res.stderr


def test_direct_photo_reloads_opaque_and_transparent_df11_cards_1_to_1_without_border_damage(
    tmp_path: Path,
) -> None:
    from backend.core.compositor import load_df11_assets
    from backend.core.dsp import compute_effective_scale

    assert compute_effective_scale(224, 278, 1.0, "cover") == pytest.approx(1.0)
    assert compute_effective_scale(224, 278, 1.0, "contain") == pytest.approx(1.0)

    inner_mask_im, overlay_im = load_df11_assets()
    clear_win = (np.asarray(inner_mask_im, dtype=np.uint8) == 255) & (
        np.asarray(overlay_im, dtype=np.uint8)[:, :, 3] == 0
    )
    assert int(clear_win.sum()) > 30_000

    bridge = StudioBridge(
        vault_dir=tmp_path / "vault_ro",
        export_dir=tmp_path / "exports",
        db_path=tmp_path / "roundtrip.sqlite3",
        templates_dir=tmp_path / "tshirt_templates",
        raw_archive_dir=tmp_path / "raw_archive",
        extracted_faces_dir=tmp_path / "caras_extraidas",
        sample_faces_dir=tmp_path / "caras_prueba",
    )

    # 1. Opaque 260x310 DF11 card with distinct colored markers near all 4 inner bevel edges + 1px central grid
    opaque_subject = np.zeros((DF11_HEIGHT, DF11_WIDTH, 4), dtype=np.uint8)
    opaque_subject[:, :] = (36, 58, 96, 255)
    yy, xx = np.mgrid[0:DF11_HEIGHT, 0:DF11_WIDTH]
    grid_mask = (xx >= 70) & (xx < 190) & (yy >= 75) & (yy < 235) & (((xx + yy) % 2) == 0)
    opaque_subject[grid_mask] = (210, 185, 145, 255)
    opaque_subject[22:288, 22:36] = (220, 48, 52, 255)    # Left edge stripe inside 21-22px zone
    opaque_subject[22:288, 224:238] = (44, 185, 98, 255)  # Right edge stripe inside 21-22px zone
    opaque_subject[22:34, 40:220] = (238, 196, 42, 255)   # Top edge stripe
    opaque_subject[276:288, 40:220] = (195, 72, 210, 255) # Bottom edge stripe
    opaque_df11 = render_df11_card(Image.fromarray(opaque_subject, mode="RGBA"), bg_mode="white_df11")
    opaque_orig_arr = np.asarray(opaque_df11, dtype=np.uint8)

    loaded_op = bridge.load_direct_photo_source(
        _png_data_url(opaque_df11),
        "10002001.png",
        {"harmonize": False, "enhanceQuality": 0.0, "bgMode": "white_df11"},
    )
    assert loaded_op["width"] == 224
    assert loaded_op["height"] == 278
    assert loaded_op["isPreCutout"] is False
    reloaded_op_arr = _decode_data_url_rgba(loaded_op["previewDataUrl"])

    # Bit-exact 1:1 fidelity across the entire clear interior (even 1px shift or 1% shrink fails the 1px grid)
    diff_op = np.abs(reloaded_op_arr[:, :, :3].astype(np.int16) - opaque_orig_arr[:, :, :3].astype(np.int16))
    assert int(diff_op[clear_win].max()) == 0, int(diff_op[clear_win].max())
    # All 4 edge stripes stay razor-sharp at their exact pixel coordinates without 21-22px border smear
    assert int(reloaded_op_arr[155, 23, 0]) > 160 and int(reloaded_op_arr[155, 36, 0]) < 50
    assert int(reloaded_op_arr[155, 236, 1]) > 135 and int(reloaded_op_arr[155, 223, 1]) < 75
    assert int(reloaded_op_arr[24, 130, 0]) > 175 and int(reloaded_op_arr[34, 130, 0]) < 50
    assert int(reloaded_op_arr[285, 130, 2]) > 150 and int(reloaded_op_arr[275, 130, 2]) < 110

    # Panning with clampPan=False on transparent bg must never expose alpha==0 corners from the cropped 224x278 source
    panned_op = bridge.render_modular_preview(
        {
            "step1Mode": "direct_photo",
            "directPhotoId": loaded_op["directPhotoId"],
            "scale": 1.0,
            "offsetX": 14.0,
            "offsetY": 14.0,
            "clampPan": False,
            "harmonize": False,
            "enhanceQuality": 0.0,
            "bgMode": "transparent",
        }
    )
    panned_op_arr = _decode_data_url_rgba(panned_op["previewDataUrl"])
    assert int(panned_op_arr[30:36, 32:38, 3].min()) == 255

    # 2. Transparent 260x310 DF11 card with shoulders touching the inner perimeter (x=19..241, y=240..293)
    cutout_subject = np.zeros((DF11_HEIGHT, DF11_WIDTH, 4), dtype=np.uint8)
    cutout_subject[70:245, 85:175] = (206, 162, 134, 255)   # Head/neck
    cutout_subject[235:294, 18:242] = (28, 112, 208, 255)   # Full-width kit shoulders touching inner frame
    trans_df11 = render_df11_card(Image.fromarray(cutout_subject, mode="RGBA"), bg_mode="transparent")
    trans_orig_arr = np.asarray(trans_df11, dtype=np.uint8)

    loaded_tr = bridge.load_direct_photo_source(
        _png_data_url(trans_df11),
        "10002002.png",
        {"harmonize": False, "enhanceQuality": 0.0, "bgMode": "transparent"},
    )
    assert loaded_tr["width"] == 224
    assert loaded_tr["height"] == 278
    assert loaded_tr["isPreCutout"] is True
    reloaded_tr_arr = _decode_data_url_rgba(loaded_tr["previewDataUrl"])

    # Bit-exact 1:1 interior fidelity (scale == 1.0000, NOT 1.1151) AND zero erased 3-4px inner shoulder perimeter
    diff_tr = np.abs(reloaded_tr_arr.astype(np.int16) - trans_orig_arr.astype(np.int16))
    assert int(diff_tr[clear_win].max()) == 0, int(diff_tr[clear_win].max())
    assert int(reloaded_tr_arr[255:282, 21:24, 3].min()) == 255
    assert int(reloaded_tr_arr[255:282, 236:239, 3].min()) == 255


def test_direct_photo_high_res_3000x4000_luz_df11_preview_is_under_150ms(tmp_path: Path) -> None:
    # Build a dim 3000x4000 (12 MP) full-scene photo without slow Python pixel loops
    arr_small = np.full((200, 150, 3), (38, 44, 62), dtype=np.uint8)
    arr_small[55:145, 45:105] = (96, 78, 68)
    hi_res = Image.fromarray(arr_small, mode="RGB").resize((3000, 4000), Image.Resampling.NEAREST)
    buf = io.BytesIO()
    hi_res.save(buf, format="JPEG", quality=85)
    data_url = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")

    bridge = StudioBridge(
        vault_dir=tmp_path / "vault_ro",
        export_dir=tmp_path / "exports",
        db_path=tmp_path / "perf.sqlite3",
        templates_dir=tmp_path / "tshirt_templates",
        raw_archive_dir=tmp_path / "raw_archive",
        extracted_faces_dir=tmp_path / "caras_extraidas",
        sample_faces_dir=tmp_path / "caras_prueba",
    )
    loaded = bridge.load_direct_photo_source(data_url, "30004000.jpg", {"harmonize": True, "enhanceQuality": 0.5})
    direct_id = loaded["directPhotoId"]

    # Warm-up call
    bridge.render_modular_preview(
        {
            "step1Mode": "direct_photo",
            "directPhotoId": direct_id,
            "scale": 1.0,
            "offsetX": 0.0,
            "offsetY": 0.0,
            "clampPan": True,
            "harmonize": False,
            "enhanceQuality": 0.5,
            "bgMode": "white_df11",
        }
    )

    t0 = time.perf_counter()
    res_on = bridge.render_modular_preview(
        {
            "step1Mode": "direct_photo",
            "directPhotoId": direct_id,
            "scale": 1.08,
            "offsetX": 6.0,
            "offsetY": -5.0,
            "clampPan": True,
            "harmonize": True,
            "enhanceQuality": 0.5,
            "bgMode": "white_df11",
        }
    )
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    assert elapsed_ms < 150.0, f"Expected < 150ms for 3000x4000 Luz DF11 preview, got {elapsed_ms:.1f}ms"

    res_off = bridge.render_modular_preview(
        {
            "step1Mode": "direct_photo",
            "directPhotoId": direct_id,
            "scale": 1.08,
            "offsetX": 6.0,
            "offsetY": -5.0,
            "clampPan": True,
            "harmonize": False,
            "enhanceQuality": 0.5,
            "bgMode": "white_df11",
        }
    )
    arr_on = _decode_data_url_rgba(res_on["previewDataUrl"])
    arr_off = _decode_data_url_rgba(res_off["previewDataUrl"])
    assert float(arr_on[100:210, 80:180, :3].mean()) > float(arr_off[100:210, 80:180, :3].mean()) + 2.0


def test_wgif_preserves_bright_semitransparent_hair_strand_on_transparent_bg() -> None:
    portrait = np.zeros((DF11_HEIGHT, DF11_WIDTH, 4), dtype=np.uint8)
    # Opaque head core at x=85..175
    portrait[80:220, 85:175] = (212, 182, 128, 255)
    # Wispy bright blonde hair strand (alpha=90) located 12px away from the core (x=71..73)
    portrait[105:165, 71:74] = (224, 198, 142, 90)

    out = np.asarray(
        render_df11_card(
            Image.fromarray(portrait, mode="RGBA"),
            bg_mode="transparent",
            enhance_quality=1.0,
        ),
        dtype=np.uint8,
    )
    strand_px = out[135, 72]
    assert int(strand_px[3]) == 90
    assert int(strand_px[0]) >= 200 and int(strand_px[1]) >= 175 and int(strand_px[2]) >= 120, strand_px
