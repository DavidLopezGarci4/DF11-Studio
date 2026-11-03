"""Shirt-only template sanitizer (2x SSAA + Guided Collar Matting + OKLab Crispness) and multi-season catalog."""

from __future__ import annotations

import hashlib
import io
import json
import math
import os
import re
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

import backend.services.vision as vision_mod
from backend.core.compositor import DF11_HEIGHT, DF11_WIDTH, load_df11_assets
from backend.core.fm_config import safe_ntfs_replace
from backend.core.image_guard import load_guarded_image
from backend.core.paths import get_raw_tshirt_archive_dir, get_state_db_path, get_tshirt_templates_dir
from backend.services.kits import init_state_db, load_merged_clubs, validate_club_id

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".avif"}
_TEMPLATES_LOCK = threading.RLock()


@dataclass(frozen=True, slots=True)
class CollarProfile:
    left_rim: tuple[int, int]
    right_rim: tuple[int, int]
    apex: tuple[int, int]
    collar_width: int
    y_top_curve: tuple[int, ...]

    def to_json(self) -> str:
        return json.dumps(
            {
                "left_rim": list(self.left_rim),
                "right_rim": list(self.right_rim),
                "apex": list(self.apex),
                "collar_width": self.collar_width,
                "y_top_curve": list(self.y_top_curve),
            }
        )

    @classmethod
    def from_json(cls, raw: str) -> CollarProfile:
        d = json.loads(raw)
        return cls(
            left_rim=(int(d["left_rim"][0]), int(d["left_rim"][1])),
            right_rim=(int(d["right_rim"][0]), int(d["right_rim"][1])),
            apex=(int(d["apex"][0]), int(d["apex"][1])),
            collar_width=int(d["collar_width"]),
            y_top_curve=tuple(int(v) for v in d["y_top_curve"]),
        )


def normalize_template_category(raw: str) -> str:
    return "staff" if str(raw or "").strip().lower() == "staff" else "player"


@dataclass(frozen=True, slots=True)
class ShirtTemplate:
    template_id: str
    filename: str
    display_name: str
    club_id: str
    file_path: Path
    collar: CollarProfile
    club_name: str = ""
    season: str = ""
    is_active_for_club: bool = True
    category: str = "player"


def _needs_shirt_sanitization(im_rgba: Image.Image) -> bool:
    """Return True if the image is not yet a clean 260x310 shirt-only RGBA cutout."""
    if im_rgba.size != (DF11_WIDTH, DF11_HEIGHT):
        return True
    arr = np.asarray(im_rgba.convert("RGBA"), dtype=np.uint8)
    alpha = arr[:, :, 3]
    if int(alpha[:158, :].max()) > 0 or int(alpha[:, :18].max()) > 0 or int(alpha[:, 243:].max()) > 0 or int(alpha[294:, :].max()) > 0:
        return True
    probs = vision_mod.segment_portrait_classes(im_rgba)
    skin_hair = probs[:, :, vision_mod.CLASS_FACE_SKIN] + probs[:, :, vision_mod.CLASS_BODY_SKIN] + probs[:, :, vision_mod.CLASS_HAIR]
    residual_skin_px = int(((skin_hair > 0.45) & (alpha > 48)).sum())
    return residual_skin_px > 40


def _has_df11_outer_ring(im_rgba: Image.Image) -> bool:
    if im_rgba.size != (DF11_WIDTH, DF11_HEIGHT):
        return False
    a = np.asarray(im_rgba.convert("RGBA"), dtype=np.uint8)[:, :, 3]
    if int(a[0, :].max()) > 0 or int(a[-1, :].max()) > 0 or int(a[:, 0].max()) > 0 or int(a[:, -1].max()) > 0:
        return False
    return (
        0 < int(a[:, 2:18].max()) <= 125
        and 0 < int(a[:, 243:258].max()) <= 125
        and int(a[180:285, 30:230].max()) > 240
    )


def _sanitize_viewport(zoom: float = 1.0, pan_x: float = 0.0, pan_y: float = 0.0) -> tuple[float, float, float]:
    zf = float(zoom) if math.isfinite(float(zoom)) else 1.0
    xf = float(pan_x) if math.isfinite(float(pan_x)) else 0.0
    yf = float(pan_y) if math.isfinite(float(pan_y)) else 0.0
    return (
        float(np.clip(zf, 0.20, 4.0)),
        float(np.clip(xf, -2000.0, 2000.0)),
        float(np.clip(yf, -2000.0, 2000.0)),
    )


def _frame_to_df11_stage(
    raw_rgba: Image.Image,
    zoom: float = 1.0,
    pan_x: float = 0.0,
    pan_y: float = 0.0,
    scale_mult: int = 1,
) -> Image.Image:
    zoom_c, px_c, py_c = _sanitize_viewport(zoom, pan_x, pan_y)
    sm = max(1, int(scale_mult))
    tw, th = DF11_WIDTH * sm, DF11_HEIGHT * sm
    im = raw_rgba.convert("RGBA")
    if sm == 1 and im.size == (tw, th) and abs(zoom_c - 1.0) < 1e-3 and abs(px_c) < 0.5 and abs(py_c) < 0.5:
        return im
    w, h = im.size
    fit_base = min(DF11_WIDTH / max(w, 1), DF11_HEIGHT / max(h, 1))
    eff = fit_base * zoom_c * sm
    nw, nh = max(1, round(w * eff)), max(1, round(h * eff))
    resized = im if (nw, nh) == (w, h) else im.resize((nw, nh), Image.Resampling.LANCZOS)
    stage = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
    x0 = round((tw - nw) * 0.5 + px_c * sm)
    y0 = round((th - nh) * 0.5 + py_c * sm)
    stage.alpha_composite(resized, (x0, y0))
    return stage


def _apply_oklab_textile_crispness(rgb_2x: np.ndarray, fg_mask: np.ndarray, amount: float) -> np.ndarray:
    """Enhance micro-contrast of crests, sponsors, and stitching strictly in OKLab Lightness (zero color halos)."""
    amt = float(np.clip(amount, 0.0, 1.0)) if math.isfinite(float(amount)) else 0.35
    if amt <= 0.01:
        return rgb_2x
    srgb01 = np.clip(rgb_2x / 255.0, 0.0, 1.0).astype(np.float32)
    lab = vision_mod.srgb_to_oklab(srgb01)
    l_chan = lab[:, :, 0]
    l_u8 = np.clip(np.round(l_chan * 255.0), 0.0, 255.0).astype(np.uint8)
    l_blur = np.asarray(Image.fromarray(l_u8, mode="L").filter(ImageFilter.GaussianBlur(1.15)), dtype=np.float32) / 255.0
    interior = np.clip((fg_mask - 0.82) / 0.16, 0.0, 1.0)
    detail = np.clip(l_chan - l_blur, -0.055, 0.055)
    lab[:, :, 0] = np.clip(l_chan + detail * (0.90 * amt) * interior, 0.0, 1.0)
    return np.clip(vision_mod.oklab_to_srgb(lab) * 255.0, 0.0, 255.0).astype(np.float32)


def sanitize_shirt_template_rgba(
    raw_rgba: Image.Image,
    symmetrize_shoulders: bool = True,
    shoulder_boost: float = 0.0,
    zoom: float = 1.0,
    pan_x: float = 0.0,
    pan_y: float = 0.0,
    detail_crispness: float = 0.35,
) -> Image.Image:
    """2x super-sampled (520x620) shirt extractor with Guided Collar Matting and OKLab L micro-sharpening."""
    zoom_c, px_c, py_c = _sanitize_viewport(zoom, pan_x, pan_y)
    raw_src_rgba = raw_rgba.convert("RGBA")
    raw_src_a = np.asarray(raw_src_rgba, dtype=np.uint8)[:, :, 3]
    is_pre_cut = (
        raw_src_rgba.size == (DF11_WIDTH, DF11_HEIGHT)
        and int(raw_src_a[:140, :].max()) == 0
        and int((raw_src_a[:150, :18] == 0).sum()) > 2000
    )

    inner_mask_im, frame_ov_im = load_df11_assets()
    inner_mask_f = np.asarray(inner_mask_im, dtype=np.float32) / 255.0

    # Un-composite baked DF11 inner-bevel shadow at native 260x310 before 2x super-sampling
    if _has_df11_outer_ring(raw_src_rgba) and abs(zoom_c - 1.0) < 1e-3 and abs(px_c) < 0.5 and abs(py_c) < 0.5:
        src_arr = np.asarray(raw_src_rgba, dtype=np.uint8).copy()
        src_rgb = src_arr[:, :, :3].astype(np.float32)
        ov_arr = np.asarray(frame_ov_im, dtype=np.float32)
        ov_a = (ov_arr[:, :, 3:4] / 255.0) * (inner_mask_f[:, :, None] > 0.1)
        edge_band = np.zeros((DF11_HEIGHT, DF11_WIDTH, 1), dtype=bool)
        edge_band[:, 19:26, 0] = True
        edge_band[:, 235:242, 0] = True
        edge_band[286:293, :, 0] = True
        rgb_unbeveled = (src_rgb - ov_arr[:, :, :3] * ov_a) / np.maximum(1.0 - ov_a, 0.38)
        src_arr[:, :, :3] = np.where(edge_band & (ov_a > 0.02), np.clip(rgb_unbeveled, 0.0, 255.0), src_rgb).round().astype(np.uint8)
        raw_src_rgba = Image.fromarray(src_arr, mode="RGBA")

    ss = 2
    w2, h2 = DF11_WIDTH * ss, DF11_HEIGHT * ss
    card_2x = _frame_to_df11_stage(raw_src_rgba, zoom=zoom_c, pan_x=px_c, pan_y=py_c, scale_mult=ss)
    arr = np.asarray(card_2x, dtype=np.uint8).copy()
    rgb_f = arr[:, :, :3].astype(np.float32)
    raw_a = arr[:, :, 3].astype(np.float32) / 255.0

    if int(arr[:, :, 3].min()) < 255:
        vision_card = Image.new("RGBA", (w2, h2), (136, 138, 142, 255))
        vision_card.alpha_composite(card_2x)
    else:
        vision_card = card_2x

    probs = vision_mod.segment_portrait_classes(vision_card)
    p_clothes = probs[:, :, vision_mod.CLASS_CLOTHES]
    p_skin_hair = (
        probs[:, :, vision_mod.CLASS_FACE_SKIN]
        + probs[:, :, vision_mod.CLASS_BODY_SKIN]
        + probs[:, :, vision_mod.CLASS_HAIR]
    )
    biref_a = (
        raw_a
        if is_pre_cut
        else (np.asarray(vision_mod.remove_background_birefnet(vision_card), dtype=np.uint8)[:, :, 3].astype(np.float32) / 255.0)
        * raw_a
    )

    yy2, xx2 = np.mgrid[0:h2, 0:w2].astype(np.float32)
    xx = (xx2 + 0.5) / ss
    yy = (yy2 + 0.5) / ss

    # Edge-Guided Collar Matting: prevent coarse 256x256 MediaPipe blur from chewing crisp colored/white collar ribs
    p_skin_eff = p_skin_hair
    neck_seed = (np.abs(xx - 130.0) < 34.0) & (yy >= 135.0) & (yy <= 198.0) & (p_skin_hair > 0.78) & (p_clothes < 0.15) & (raw_a > 0.85)
    if int(neck_seed.sum()) >= 80:
        band_y0, band_y1 = 166 * ss, min(h2, 238 * ss)
        lab_neck = vision_mod.srgb_to_oklab(np.clip(rgb_f[neck_seed] / 255.0, 0.0, 1.0).reshape(-1, 1, 3))[:, 0, :]
        skin_med = np.median(lab_neck, axis=0)
        lab_band = vision_mod.srgb_to_oklab(np.clip(rgb_f[band_y0:band_y1] / 255.0, 0.0, 1.0))
        d_l = (lab_band[:, :, 0] - float(skin_med[0])) * 0.65
        d_ab = np.hypot(lab_band[:, :, 1] - float(skin_med[1]), lab_band[:, :, 2] - float(skin_med[2])) * 2.6
        d_skin = np.hypot(d_l, d_ab)
        ps_band = p_skin_hair[band_y0:band_y1]
        pc_band = p_clothes[band_y0:band_y1]
        fabric_snap = (
            np.clip((d_skin - 0.15) / 0.11, 0.0, 1.0)
            * np.clip((0.72 - ps_band) / 0.34, 0.0, 1.0)
            * np.clip((pc_band - 0.06) / 0.22, 0.25, 1.0)
        )
        p_skin_eff = p_skin_hair.copy()
        p_skin_eff[band_y0:band_y1] = ps_band * (1.0 - 0.82 * fabric_snap)

    non_skin_gate = np.clip((0.36 - p_skin_eff) / 0.24, 0.0, 1.0)
    cloth_soft = np.where(yy >= 176.0, np.clip((p_clothes - 0.30) / 0.28, 0.0, 1.0) * non_skin_gate * raw_a, 0.0)

    x_mir = np.clip(w2 - 1 - np.arange(w2, dtype=np.int32), 0, w2 - 1)
    outer_shoulder_zone = (np.abs(xx - 130.0) >= 45.0) & (yy >= 188.0)

    collar_neck_zone = np.clip((52.0 - np.abs(xx - 130.0)) / 10.0, 0.0, 1.0) * np.clip((232.0 - yy) / 14.0, 0.0, 1.0)
    collar_cloth_gate = np.clip((p_clothes - 0.90 * p_skin_eff - 0.12) / 0.42, 0.0, 1.0)
    effective_gate = collar_neck_zone * collar_cloth_gate + (1.0 - collar_neck_zone) * non_skin_gate
    effective_gate = np.where(yy < 162.0, 0.0, effective_gate)

    fg_shirt = np.maximum(biref_a, cloth_soft) * effective_gate
    sleeve_solid_band = fg_shirt[188 * ss :, :] > 0.65
    has_col_solid = sleeve_solid_band.any(axis=0)
    first_solid_y = np.where(has_col_solid, 188 * ss + sleeve_solid_band.argmax(axis=0), h2 - 1)
    ref_col_rgb = rgb_f[np.minimum(first_solid_y + 4, h2 - 1), np.arange(w2)]

    if symmetrize_shoulders:
        fg_mirror = fg_shirt[:, x_mir]
        diff_mir = np.abs(rgb_f - rgb_f[:, x_mir, :]).max(axis=-1) / 255.0
        diff_col = np.abs(rgb_f - ref_col_rgb[None, :, :]).max(axis=-1) / 255.0
        not_bg_over_dark_sleeve = ~(has_col_solid[None, :] & (diff_col > 0.30) & (p_clothes < 0.35))
        cloth_coherent = ((diff_mir < 0.22) | (has_col_solid[None, :] & (diff_col < 0.18))) & not_bg_over_dark_sleeve
        need_sym = (
            outer_shoulder_zone
            & (raw_a > 0.5)
            & (raw_a[:, x_mir] > 0.5)
            & (non_skin_gate > 0.75)
            & (fg_shirt < 0.65)
            & cloth_coherent
        )
        fg_shirt = np.where(need_sym, np.maximum(fg_shirt, fg_mirror * 0.98), fg_shirt)

    sleeve_cols = (np.abs(xx - 130.0) >= 46.0) & (yy >= 196.0) & (raw_a > 0.5) & (non_skin_gate > 0.80)
    solid_seed = np.where(sleeve_cols & (fg_shirt > 0.58), fg_shirt, 0.0)
    downward_solid = np.maximum.accumulate(solid_seed, axis=0)
    fg_shirt = np.where(sleeve_cols & (yy >= 206.0), np.maximum(fg_shirt, downward_solid), fg_shirt)

    if shoulder_boost > 0.01:
        fg_pre_boost = fg_shirt.copy()
        boost = float(np.clip(shoulder_boost, 0.0, 1.0))
        fill_ref_rgb = ref_col_rgb.copy()
        for side_sign, x_ref_1x in ((-1, 62), (1, 198)):
            x_ref = x_ref_1x * ss
            ys_ref = np.where(fg_shirt[180 * ss : 245 * ss, x_ref] > 0.55)[0]
            if len(ys_ref):
                y_anchor_2x = 180 * ss + int(ys_ref[0])
                y_anchor = float(y_anchor_2x) / ss
                anchor_rgb = rgb_f[min(y_anchor_2x + 4, h2 - 1), x_ref]
                slope = 0.48 - 0.14 * boost
                if side_sign < 0:
                    x0_s, x1_s = 19 * ss, x_ref
                    xs_1x = (np.arange(x0_s, x1_s, dtype=np.float32) + 0.5) / ss
                    y_curve = y_anchor + slope * (float(x_ref_1x) - xs_1x)
                    fill_zone = (
                        (yy[:, x0_s:x1_s] >= y_curve[None, :])
                        & (raw_a[:, x0_s:x1_s] > 0.5)
                        & (non_skin_gate[:, x0_s:x1_s] > 0.85)
                    )
                    fg_shirt[:, x0_s:x1_s] = np.where(fill_zone, np.maximum(fg_shirt[:, x0_s:x1_s], 0.98), fg_shirt[:, x0_s:x1_s])
                    last_rgb = anchor_rgb
                    for xc in range(x1_s - 1, x0_s - 1, -1):
                        if has_col_solid[xc]:
                            last_rgb = fill_ref_rgb[xc]
                        else:
                            fill_ref_rgb[xc] = last_rgb
                else:
                    x0_s, x1_s = x_ref + 1, 242 * ss
                    xs_1x = (np.arange(x0_s, x1_s, dtype=np.float32) + 0.5) / ss
                    y_curve = y_anchor + slope * (xs_1x - float(x_ref_1x))
                    fill_zone = (
                        (yy[:, x0_s:x1_s] >= y_curve[None, :])
                        & (raw_a[:, x0_s:x1_s] > 0.5)
                        & (non_skin_gate[:, x0_s:x1_s] > 0.85)
                    )
                    fg_shirt[:, x0_s:x1_s] = np.where(fill_zone, np.maximum(fg_shirt[:, x0_s:x1_s], 0.98), fg_shirt[:, x0_s:x1_s])
                    last_rgb = anchor_rgb
                    for xc in range(x0_s, x1_s):
                        if has_col_solid[xc]:
                            last_rgb = fill_ref_rgb[xc]
                        else:
                            fill_ref_rgb[xc] = last_rgb
        boost_fill_t = np.where(
            fg_shirt > fg_pre_boost + 0.05,
            np.clip((0.40 - fg_pre_boost) / 0.40, 0.0, 1.0),
            0.0,
        )[:, :, None]
        rgb_f = rgb_f * (1.0 - boost_fill_t) + fill_ref_rgb[None, :, :] * boost_fill_t

    # Boundary-only RGB decontamination: 100% untouched original pixels inside opaque fabric (fg_shirt >= 0.93)
    w_pure = (fg_shirt > 0.90).astype(np.float32) * np.clip((0.06 - p_skin_eff) / 0.06, 0.0, 1.0)
    w_pure[: 182 * ss, :] *= np.clip((p_clothes[: 182 * ss, :] - 0.65) / 0.25, 0.0, 1.0)
    premul_dec = np.concatenate([rgb_f * w_pure[:, :, None], w_pure[:, :, None] * 255.0], axis=-1).clip(0.0, 255.0).round().astype(np.uint8)
    blurred = np.asarray(Image.fromarray(premul_dec, mode="RGBA").filter(ImageFilter.GaussianBlur(3.2)), dtype=np.float32)
    w_blur = blurred[:, :, 3:4] / 255.0
    pure_rgb = np.where(w_blur > 1e-3, blurred[:, :, :3] / np.maximum(w_blur, 1e-3), rgb_f)
    rim_weight = np.clip((0.93 - fg_shirt) / 0.45, 0.0, 1.0)
    decontam_t = np.where(
        (w_blur[:, :, 0] > 0.02) & (rim_weight > 0.0),
        rim_weight * np.clip(p_skin_eff * 3.2 + (1.0 - effective_gate) * 0.95, 0.0, 1.0),
        0.0,
    )[:, :, None]
    clean_rgb_2x = rgb_f * (1.0 - decontam_t) + pure_rgb * decontam_t
    clean_rgb_2x = _apply_oklab_textile_crispness(clean_rgb_2x, fg_shirt, detail_crispness)

    raw_alpha_img = Image.fromarray(np.clip(np.round(fg_shirt * 255.0), 0.0, 255.0).astype(np.uint8), mode="L")
    smooth_alpha_2x = np.asarray(raw_alpha_img.filter(ImageFilter.GaussianBlur(0.85)), dtype=np.float32) / 255.0
    crisp_alpha_2x = np.where(fg_shirt > 0.88, np.maximum(smooth_alpha_2x, 0.996), smooth_alpha_2x)

    # Premultiplied-alpha 2x -> 1x Lanczos SSAA downsampling (zero dark halo on edges, razor-sharp crests)
    pm_2x = np.concatenate(
        [clean_rgb_2x * crisp_alpha_2x[:, :, None], crisp_alpha_2x[:, :, None] * 255.0],
        axis=-1,
    ).clip(0.0, 255.0).round().astype(np.uint8)
    pm_1x = np.asarray(
        Image.fromarray(pm_2x, mode="RGBA").resize((DF11_WIDTH, DF11_HEIGHT), Image.Resampling.LANCZOS),
        dtype=np.float32,
    )
    a_1x = np.clip(pm_1x[:, :, 3] / 255.0, 0.0, 1.0)
    a_1x = np.where(a_1x > 0.985, 1.0, a_1x)
    rgb_1x = np.where(a_1x[:, :, None] > 1e-3, pm_1x[:, :, :3] / np.maximum(a_1x[:, :, None], 1e-3), 0.0)

    final_a = np.clip(np.round(a_1x * inner_mask_f * 255.0), 0.0, 255.0).astype(np.uint8)
    final_a[:162, :] = 0
    final_a[:, :19] = 0
    final_a[:, 242:] = 0
    final_a[293:, :] = 0

    clean_rgb = np.where(final_a[:, :, None] > 0, np.clip(np.round(rgb_1x), 0.0, 255.0).astype(np.uint8), 0)
    out = np.concatenate([clean_rgb, final_a[:, :, None]], axis=-1)
    return Image.fromarray(out, mode="RGBA")


def extract_collar_profile(clean_shirt_rgba: Image.Image) -> CollarProfile:
    """Measure exact left/right collar rim peaks, deepest V/U apex, and shoulder curve from shirt alpha."""
    arr = np.asarray(clean_shirt_rgba.convert("RGBA"), dtype=np.uint8)
    alpha = arr[:, :, 3]
    y_top = np.full(DF11_WIDTH, DF11_HEIGHT, dtype=np.int32)
    for x in range(19, 242):
        ys = np.where(alpha[160:, x] > 120)[0]
        if len(ys):
            y_top[x] = int(ys[0] + 160)

    sm = y_top.copy()
    for x in range(55, 206):
        sm[x] = int(np.median(y_top[x - 1 : x + 2]))

    left_slice = sm[62:123]
    x_l = int(62 + np.argmin(left_slice)) if int(left_slice.min()) < DF11_HEIGHT else 92
    y_l = int(sm[x_l]) if int(sm[x_l]) < DF11_HEIGHT else 196

    right_slice = sm[138:199]
    x_r = int(138 + np.argmin(right_slice)) if int(right_slice.min()) < DF11_HEIGHT else 168
    y_r = int(sm[x_r]) if int(sm[x_r]) < DF11_HEIGHT else 196

    if x_r - x_l < 36:
        x_l, x_r = 92, 168
        y_l = y_r = min(y_l, y_r, 198)

    mid_slice = sm[x_l + 4 : x_r - 3]
    if len(mid_slice) and int(mid_slice.max()) < DF11_HEIGHT:
        x_v = int(x_l + 4 + np.argmax(mid_slice))
        y_v = int(sm[x_v])
    else:
        x_v = (x_l + x_r) // 2
        y_v = max(y_l, y_r) + 26

    y_v = max(y_v, min(y_l, y_r) + 6)
    return CollarProfile(
        left_rim=(x_l, y_l),
        right_rim=(x_r, y_r),
        apex=(x_v, y_v),
        collar_width=max(40, x_r - x_l),
        y_top_curve=tuple(int(v) for v in y_top),
    )


def _atomic_write_png(im_rgba: Image.Image, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    im_rgba.save(buf, format="PNG", optimize=True, compress_level=9)
    fd, tname = tempfile.mkstemp(prefix=f".{dst.stem}_", suffix=".tmp", dir=str(dst.parent))
    tp = Path(tname)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(buf.getvalue())
        safe_ntfs_replace(tp, dst)
    finally:
        tp.unlink(missing_ok=True)


def _is_placeholder_club_name(name: str, club_id: str) -> bool:
    n = name.strip()
    return not n or n == f"Club #{club_id}" or n == f"Club FM #{club_id}"


def _resolve_club_display_name(club_id: str, explicit_name: str, clubs_map: dict[str, dict[str, str]]) -> str:
    if not club_id:
        return ""
    clean_exp = explicit_name.strip()[:80]
    known = str(clubs_map.get(club_id, {}).get("name") or "").strip()
    if clean_exp and not _is_placeholder_club_name(clean_exp, club_id):
        return clean_exp
    if known:
        return known
    return clean_exp or f"Club #{club_id}"


def sync_tshirt_templates_dir(
    tpl_dir: Path | None = None,
    raw_archive_dir: Path | None = None,
    db_path: Path | None = None,
    force_from_archive: bool = False,
) -> list[ShirtTemplate]:
    """Ensure every image in tshirt_templates is a clean shirt-only PNG, archiving raw originals safely."""
    folder = (tpl_dir or get_tshirt_templates_dir()).resolve()
    archive = (raw_archive_dir or get_raw_tshirt_archive_dir()).resolve()
    state_db = db_path or get_state_db_path()

    with _TEMPLATES_LOCK:
        folder.mkdir(parents=True, exist_ok=True)
        clubs_map = load_merged_clubs(state_db)
        with init_state_db(state_db) as conn:
            existing = {
                row[0]: {
                    "filename": row[1],
                    "display_name": row[2],
                    "club_id": str(row[3] or ""),
                    "sha256": row[4],
                    "mtime_ns": int(row[5]),
                    "size": int(row[6]),
                    "collar_json": row[7],
                    "club_name": str(row[8] or ""),
                    "season": str(row[9] or ""),
                    "is_active_for_club": bool(int(row[10]) if row[10] is not None else 1),
                    "category": normalize_template_category(str(row[11] or "player")),
                }
                for row in conn.execute(
                    "SELECT template_id, filename, display_name, club_id, sha256, mtime_ns, size, collar_json, "
                    "club_name, season, is_active_for_club, category FROM shirt_templates"
                ).fetchall()
            }

        out: list[ShirtTemplate] = []
        seen_ids: set[str] = set()
        seen_lower: set[str] = set()
        pending_deletes: list[str] = []
        pending_upserts: list[tuple[str, str, str, str, str, int, int, str, str, str, int, str]] = []

        candidates = sorted(
            (p for p in folder.iterdir() if p.is_file() and not p.name.startswith(".") and p.suffix.lower() in IMAGE_EXTS),
            key=lambda x: (x.stem.lower(), 0 if x.suffix.lower() == ".png" else 1, x.name),
        )
        for p in candidates:
            tid_low = p.stem.lower()
            if tid_low in seen_lower:
                try:
                    if p.stat().st_size <= 20 * 1024 * 1024:
                        dup_bytes = p.read_bytes()
                        dup_hash = hashlib.sha256(dup_bytes).hexdigest()
                        archive.mkdir(parents=True, exist_ok=True)
                        dup_bak = archive / f"{p.stem}_{dup_hash[:10]}{p.suffix.lower()}"
                        if not dup_bak.is_file():
                            dup_bak.write_bytes(dup_bytes)
                    p.unlink(missing_ok=True)
                except OSError:
                    pass
                continue
            tid = p.stem
            st = p.stat()
            cached = existing.get(tid) or next((v for k, v in existing.items() if k.lower() == tid_low), None)
            cached_key = next((k for k in existing if k.lower() == tid_low), tid)
            if (
                not force_from_archive
                and cached
                and cached["filename"].lower() == p.name.lower()
                and cached["mtime_ns"] == st.st_mtime_ns
                and cached["size"] == st.st_size
            ):
                seen_lower.add(tid_low)
                seen_ids.add(cached_key)
                cid_c = cached["club_id"]
                cname_c = _resolve_club_display_name(cid_c, cached["club_name"], clubs_map)
                out.append(
                    ShirtTemplate(
                        template_id=cached_key,
                        filename=p.name,
                        display_name=cached["display_name"],
                        club_id=cid_c,
                        file_path=p,
                        collar=CollarProfile.from_json(cached["collar_json"]),
                        club_name=cname_c,
                        season=cached["season"],
                        is_active_for_club=bool(cached["is_active_for_club"]) if cid_c else False,
                        category=cached["category"],
                    )
                )
                continue

            arch_re = re.compile(rf"^{re.escape(tid)}_[0-9a-f]{{10}}$", re.IGNORECASE)
            archived = (
                sorted(a for a in archive.iterdir() if a.is_file() and a.suffix.lower() in IMAGE_EXTS and arch_re.match(a.stem))
                if force_from_archive and archive.is_dir()
                else []
            )
            src_file = archived[-1] if archived else p
            try:
                guarded = load_guarded_image(src_file)
                raw_bytes = src_file.read_bytes()
                im = guarded.image
            except Exception:
                continue

            target_png = folder / f"{tid}.png"
            if force_from_archive or _needs_shirt_sanitization(im) or p.suffix.lower() != ".png":
                if not archived:
                    raw_hash = hashlib.sha256(raw_bytes).hexdigest()
                    archive.mkdir(parents=True, exist_ok=True)
                    backup_path = archive / f"{tid}_{raw_hash[:10]}{p.suffix.lower()}"
                    if not backup_path.is_file():
                        backup_path.write_bytes(raw_bytes)
                clean_im = sanitize_shirt_template_rgba(im)
                if p.resolve() == target_png.resolve() and p.name != target_png.name:
                    p.unlink(missing_ok=True)
                _atomic_write_png(clean_im, target_png)
                if p.resolve() != target_png.resolve():
                    p.unlink(missing_ok=True)
            else:
                clean_im = im
                if p.name != target_png.name:
                    _atomic_write_png(clean_im, target_png)

            actual_file = next((x for x in folder.iterdir() if x.is_file() and x.name.lower() == target_png.name.lower()), target_png)
            collar = extract_collar_profile(clean_im)
            clean_bytes = actual_file.read_bytes()
            clean_sha = hashlib.sha256(clean_bytes).hexdigest()
            clean_st = actual_file.stat()
            disp = cached["display_name"] if cached else tid
            cid = cached["club_id"] if cached else ""
            cname = _resolve_club_display_name(cid, cached["club_name"] if cached else "", clubs_map)
            season = cached["season"] if cached else ""
            cat = cached["category"] if cached else "player"
            is_act = int(bool(cached["is_active_for_club"])) if (cached and cid) else (1 if cid else 0)

            if cached_key != tid:
                pending_deletes.append(cached_key)
            pending_upserts.append(
                (tid, actual_file.name, disp, cid, clean_sha, clean_st.st_mtime_ns, clean_st.st_size, collar.to_json(), cname, season, is_act, cat)
            )
            seen_lower.add(tid_low)
            seen_ids.add(tid)
            out.append(
                ShirtTemplate(
                    template_id=tid,
                    filename=actual_file.name,
                    display_name=disp,
                    club_id=cid,
                    file_path=actual_file,
                    collar=collar,
                    club_name=cname,
                    season=season,
                    is_active_for_club=bool(is_act),
                    category=cat,
                )
            )

        out.sort(key=lambda t: t.template_id.lower())
        stale_ids = list(set(existing.keys()) - seen_ids)

        # Enforce invariant: every assigned (club_id, category) pair in `out` has strictly 1 active titular template
        by_club: dict[tuple[str, str], list[int]] = {}
        for idx, item in enumerate(out):
            if item.club_id:
                by_club.setdefault((item.club_id, item.category), []).append(idx)
        active_fixes: list[tuple[int, str]] = []
        for _club_cat_k, idxs in by_club.items():
            act_idxs = [i for i in idxs if out[i].is_active_for_club]
            if len(act_idxs) == 1:
                continue
            chosen_idx = act_idxs[0] if act_idxs else idxs[0]
            for i in idxs:
                want_act = i == chosen_idx
                if out[i].is_active_for_club != want_act:
                    t_old = out[i]
                    out[i] = ShirtTemplate(
                        template_id=t_old.template_id,
                        filename=t_old.filename,
                        display_name=t_old.display_name,
                        club_id=t_old.club_id,
                        file_path=t_old.file_path,
                        collar=t_old.collar,
                        club_name=t_old.club_name,
                        season=t_old.season,
                        is_active_for_club=want_act,
                        category=t_old.category,
                    )
                    active_fixes.append((1 if want_act else 0, t_old.template_id))

        if pending_deletes or pending_upserts or stale_ids or active_fixes:
            with init_state_db(state_db) as conn:
                for dk in pending_deletes:
                    conn.execute("DELETE FROM shirt_templates WHERE template_id=?", (dk,))
                for row_vals in pending_upserts:
                    conn.execute(
                        "INSERT OR REPLACE INTO shirt_templates "
                        "(template_id, filename, display_name, club_id, sha256, mtime_ns, size, collar_json, club_name, season, is_active_for_club, category) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        row_vals,
                    )
                for stale_id in stale_ids:
                    conn.execute("DELETE FROM shirt_templates WHERE template_id=?", (stale_id,))
                for act_val, fix_tid in active_fixes:
                    conn.execute("UPDATE shirt_templates SET is_active_for_club=? WHERE template_id=?", (act_val, fix_tid))

        return out


def _ensure_club_has_one_active(conn: object, club_id: str, category: str = "player", prefer_other_than: str = "") -> None:
    if not club_id:
        return
    cat = normalize_template_category(category)
    c = conn  # sqlite3.Connection
    active_rows = c.execute(  # type: ignore[attr-defined]
        "SELECT template_id FROM shirt_templates WHERE club_id=? AND category=? AND is_active_for_club=1 ORDER BY mtime_ns DESC",
        (club_id, cat),
    ).fetchall()
    if len(active_rows) > 1:
        keep_tid = str(active_rows[0][0])
        c.execute(  # type: ignore[attr-defined]
            "UPDATE shirt_templates SET is_active_for_club=0 WHERE club_id=? AND category=? AND template_id!=?",
            (club_id, cat, keep_tid),
        )
    elif len(active_rows) == 0:
        cand_row = (
            c.execute(  # type: ignore[attr-defined]
                "SELECT template_id FROM shirt_templates WHERE club_id=? AND category=? AND template_id!=? ORDER BY mtime_ns DESC LIMIT 1",
                (club_id, cat, prefer_other_than),
            ).fetchone()
            if prefer_other_than
            else None
        )
        if cand_row is None:
            cand_row = c.execute(  # type: ignore[attr-defined]
                "SELECT template_id FROM shirt_templates WHERE club_id=? AND category=? ORDER BY mtime_ns DESC LIMIT 1",
                (club_id, cat),
            ).fetchone()
        if cand_row:
            c.execute(  # type: ignore[attr-defined]
                "UPDATE shirt_templates SET is_active_for_club=1 WHERE template_id=?",
                (str(cand_row[0]),),
            )


def rename_shirt_template(
    template_id: str,
    display_name: str,
    club_id: str = "",
    tpl_dir: Path | None = None,
    db_path: Path | None = None,
    club_name: str = "",
    season: str = "",
    is_active_for_club: bool = True,
    category: str | None = None,
) -> ShirtTemplate:
    """Update human-friendly name, FM club_id/club_name, season tag, category, and active-kit flag for a shirt template."""
    state_db = db_path or get_state_db_path()
    clean_name = display_name.strip()[:80] or template_id
    clean_club = validate_club_id(club_id)
    clean_season = season.strip()[:24]

    with _TEMPLATES_LOCK:
        items = sync_tshirt_templates_dir(tpl_dir=tpl_dir, db_path=state_db)
        match = next((t for t in items if t.template_id == template_id), None)
        if match is None:
            raise ValueError(f"Plantilla de camiseta no encontrada: {template_id}")
        old_club = match.club_id
        old_cat = match.category
        clean_cat = normalize_template_category(category) if category is not None else match.category
        clubs_map = load_merged_clubs(state_db)
        resolved_cname = _resolve_club_display_name(clean_club, club_name, clubs_map)
        act_flag = 1 if (clean_club and is_active_for_club) else 0

        with init_state_db(state_db) as conn:
            if clean_club and resolved_cname:
                if not _is_placeholder_club_name(resolved_cname, clean_club) or clean_club not in clubs_map:
                    conn.execute("INSERT OR REPLACE INTO custom_clubs VALUES (?, ?)", (clean_club, resolved_cname))
                conn.execute("UPDATE shirt_templates SET club_name=? WHERE club_id=?", (resolved_cname, clean_club))
            if clean_club and act_flag == 1:
                conn.execute(
                    "UPDATE shirt_templates SET is_active_for_club=0 WHERE club_id=? AND category=? AND template_id!=?",
                    (clean_club, clean_cat, template_id),
                )
            conn.execute(
                "UPDATE shirt_templates SET display_name=?, club_id=?, club_name=?, season=?, is_active_for_club=?, category=? WHERE template_id=?",
                (clean_name, clean_club, resolved_cname, clean_season, act_flag, clean_cat, template_id),
            )
            if old_club and (old_club != clean_club or old_cat != clean_cat):
                _ensure_club_has_one_active(conn, old_club, old_cat)
            if clean_club:
                _ensure_club_has_one_active(conn, clean_club, clean_cat, prefer_other_than=template_id if not is_active_for_club else "")

        refreshed = sync_tshirt_templates_dir(tpl_dir=tpl_dir, db_path=state_db)
        return next((t for t in refreshed if t.template_id == template_id), match)


def set_active_club_shirt_template(
    template_id: str,
    tpl_dir: Path | None = None,
    db_path: Path | None = None,
) -> ShirtTemplate:
    """Promote a historical/seasonal shirt template to be the active titular shirt of its assigned club_id and category."""
    state_db = db_path or get_state_db_path()
    with _TEMPLATES_LOCK:
        items = sync_tshirt_templates_dir(tpl_dir=tpl_dir, db_path=state_db)
        match = next((t for t in items if t.template_id == template_id), None)
        if match is None:
            raise ValueError(f"Plantilla de camiseta no encontrada: {template_id}")
        if not match.club_id:
            raise ValueError("Asigna primero un #ID de club a la camiseta antes de marcarla como titular activa.")
        with init_state_db(state_db) as conn:
            conn.execute(
                "UPDATE shirt_templates SET is_active_for_club=0 WHERE club_id=? AND category=?",
                (match.club_id, match.category),
            )
            conn.execute("UPDATE shirt_templates SET is_active_for_club=1 WHERE template_id=?", (template_id,))
        refreshed = sync_tshirt_templates_dir(tpl_dir=tpl_dir, db_path=state_db)
        return next((t for t in refreshed if t.template_id == template_id), match)


def delete_shirt_template(
    template_id: str,
    tpl_dir: Path | None = None,
    db_path: Path | None = None,
) -> str:
    """Safely delete a shirt template PNG from tshirt_templates and remove its metadata from SQLite."""
    tid_req = str(template_id or "").strip()
    if not tid_req or "/" in tid_req or "\\" in tid_req or ".." in tid_req:
        raise ValueError("Identificador de plantilla inválido.")
    folder = (tpl_dir or get_tshirt_templates_dir()).resolve()
    state_db = db_path or get_state_db_path()

    with _TEMPLATES_LOCK:
        items = sync_tshirt_templates_dir(tpl_dir=folder, db_path=state_db)
        match = next((t for t in items if t.template_id == tid_req), None)
        if match is None:
            raise ValueError(f"Plantilla de camiseta no encontrada: {tid_req}")
        resolved_file = match.file_path.resolve()
        if resolved_file.parent != folder:
            raise ValueError("Ruta de plantilla fuera de tshirt_templates.")
        resolved_file.unlink(missing_ok=True)
        with init_state_db(state_db) as conn:
            conn.execute("DELETE FROM shirt_templates WHERE template_id=?", (match.template_id,))
            if match.club_id:
                _ensure_club_has_one_active(conn, match.club_id, match.category)
        return match.template_id


_WIN_RESERVED = frozenset(
    {"CON", "PRN", "AUX", "NUL"} | {f"COM{i}" for i in range(1, 10)} | {f"LPT{i}" for i in range(1, 10)}
)


def slugify_template_id(name: str, fallback: str = "Camiseta") -> str:
    slug = re.sub(r"[^A-Za-z0-9_-]+", "_", name.strip()).strip("_")[:48] or fallback
    return f"{slug}_tpl" if slug.upper() in _WIN_RESERVED else slug


def save_new_shirt_template(
    clean_rgba: Image.Image,
    raw_bytes: bytes | None,
    display_name: str,
    club_id: str = "",
    template_id: str = "",
    tpl_dir: Path | None = None,
    raw_archive_dir: Path | None = None,
    db_path: Path | None = None,
    raw_ext: str = ".png",
    club_name: str = "",
    season: str = "",
    is_active_for_club: bool = True,
    replace_previous_for_club: bool = False,
    category: str = "player",
) -> ShirtTemplate:
    """Save a newly extracted shirt-only PNG into tshirt_templates and register its club_id, season, category & active status."""
    folder = (tpl_dir or get_tshirt_templates_dir()).resolve()
    archive = (raw_archive_dir or get_raw_tshirt_archive_dir()).resolve()
    state_db = db_path or get_state_db_path()
    ext_norm = raw_ext.lower() if raw_ext and raw_ext.lower() in IMAGE_EXTS else ".png"
    clean_cat = normalize_template_category(category)

    with _TEMPLATES_LOCK:
        folder.mkdir(parents=True, exist_ok=True)
        clean_club = validate_club_id(club_id)
        clean_season = season.strip()[:24]
        fallback_lbl = "Traje_Staff" if clean_cat == "staff" else "Camiseta_Club"
        clean_disp = display_name.strip()[:80] or template_id.strip()[:80] or ("Traje Staff" if clean_cat == "staff" else "Camiseta Club")
        season_slug = re.sub(r"[^A-Za-z0-9_-]+", "_", clean_season).strip("_")[:24]
        if template_id.strip():
            tid = slugify_template_id(template_id.strip(), fallback=fallback_lbl)
        elif season_slug:
            base_part = re.sub(r"[^A-Za-z0-9_-]+", "_", clean_disp).strip("_")[: max(12, 48 - len(season_slug) - 1)] or fallback_lbl
            tid = slugify_template_id(f"{base_part}_{season_slug}", fallback=fallback_lbl)
        else:
            tid = slugify_template_id(clean_disp, fallback=fallback_lbl)
        target_png = folder / f"{tid}.png"

        if raw_bytes:
            raw_hash = hashlib.sha256(raw_bytes).hexdigest()
            archive.mkdir(parents=True, exist_ok=True)
            bpath = archive / f"{tid}_{raw_hash[:10]}{ext_norm}"
            if not bpath.is_file():
                bpath.write_bytes(raw_bytes)

        _atomic_write_png(clean_rgba.convert("RGBA"), target_png)
        collar = extract_collar_profile(clean_rgba)
        clean_bytes = target_png.read_bytes()
        clean_sha = hashlib.sha256(clean_bytes).hexdigest()
        clean_st = target_png.stat()

        clubs_map = load_merged_clubs(state_db)
        resolved_cname = _resolve_club_display_name(clean_club, club_name, clubs_map)
        act_flag = 1 if (clean_club and is_active_for_club) else 0

        with init_state_db(state_db) as conn:
            if clean_club and resolved_cname:
                if not _is_placeholder_club_name(resolved_cname, clean_club) or clean_club not in clubs_map:
                    conn.execute("INSERT OR REPLACE INTO custom_clubs VALUES (?, ?)", (clean_club, resolved_cname))
                conn.execute("UPDATE shirt_templates SET club_name=? WHERE club_id=?", (resolved_cname, clean_club))
            if clean_club and replace_previous_for_club:
                old_rows = conn.execute(
                    "SELECT template_id, filename FROM shirt_templates WHERE club_id=? AND category=? AND LOWER(template_id)!=LOWER(?)",
                    (clean_club, clean_cat, tid),
                ).fetchall()
                for old_tid, old_fname in old_rows:
                    old_fp = (folder / str(old_fname)).resolve()
                    if old_fp.parent == folder:
                        old_fp.unlink(missing_ok=True)
                    conn.execute("DELETE FROM shirt_templates WHERE template_id=?", (str(old_tid),))
                act_flag = 1
            elif clean_club and act_flag == 1:
                conn.execute(
                    "UPDATE shirt_templates SET is_active_for_club=0 WHERE club_id=? AND category=? AND LOWER(template_id)!=LOWER(?)",
                    (clean_club, clean_cat, tid),
                )

            conn.execute("DELETE FROM shirt_templates WHERE LOWER(template_id)=LOWER(?) AND template_id!=?", (tid, tid))
            conn.execute(
                "INSERT OR REPLACE INTO shirt_templates "
                "(template_id, filename, display_name, club_id, sha256, mtime_ns, size, collar_json, club_name, season, is_active_for_club, category) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (tid, target_png.name, clean_disp, clean_club, clean_sha, clean_st.st_mtime_ns, clean_st.st_size, collar.to_json(), resolved_cname, clean_season, act_flag, clean_cat),
            )
            if clean_club:
                _ensure_club_has_one_active(conn, clean_club, clean_cat)

        refreshed = sync_tshirt_templates_dir(tpl_dir=folder, raw_archive_dir=archive, db_path=state_db)
        return next(
            (t for t in refreshed if t.template_id == tid),
            ShirtTemplate(
                template_id=tid,
                filename=target_png.name,
                display_name=clean_disp,
                club_id=clean_club,
                file_path=target_png,
                collar=collar,
                club_name=resolved_cname,
                season=clean_season,
                is_active_for_club=bool(act_flag),
                category=clean_cat,
            ),
        )


def get_club_shirt_template(
    club_id: str,
    tpl_dir: Path | None = None,
    db_path: Path | None = None,
    category: str | None = "player",
) -> ShirtTemplate | None:
    """Return the active titular ShirtTemplate bound to club_id matching category (defaults strictly to 'player')."""
    cid = club_id.strip().lstrip("#")
    if not cid:
        return None
    items = sync_tshirt_templates_dir(tpl_dir=tpl_dir, db_path=db_path)
    if category in ("player", "staff"):
        return (
            next((t for t in items if t.club_id == cid and t.category == category and t.is_active_for_club), None)
            or next((t for t in items if t.club_id == cid and t.category == category), None)
        )
    return (
        next((t for t in items if t.club_id == cid and t.is_active_for_club), None)
        or next((t for t in items if t.club_id == cid), None)
    )
