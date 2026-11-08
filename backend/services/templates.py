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
from backend.core.compositor import (
    DF11_HEIGHT,
    DF11_WIDTH,
    is_df11_pure_size,
    load_df11_assets,
    pad_pure_to_df11_canvas,
)
from backend.core.dsp import (
    _wgif_single_channel,
    fast_tent_f32,
    linear_to_srgb_u8,
    oklab_to_srgb,
    srgb_to_oklab,
    srgb_u8_to_linear,
)
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
    from backend.core.compositor import has_df11_outer_ring

    return has_df11_outer_ring(im_rgba)


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
    if is_df11_pure_size(im.size):
        im = pad_pure_to_df11_canvas(im, unfeather_edges=True)
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


def _flood_fill_mask_np(domain: np.ndarray, seeds: np.ndarray, eight_conn: bool = True) -> np.ndarray:
    """Pure-NumPy O(N) barrier-scanline flood fill inside `domain` from `seeds` (zero scipy dependency)."""
    dom = np.asarray(domain, dtype=bool)
    cur = np.asarray(seeds, dtype=bool) & dom
    if not np.any(cur):
        return cur
    bar = (~dom).astype(np.int32)
    bh = np.cumsum(bar, axis=1)
    bv = np.cumsum(bar, axis=0)
    inf_val = np.int32(1 << 29)
    neg_inf = np.int32(-1)
    for _ in range(18):
        prev = cur
        # Left-to-right (bh non-decreasing: minimum.accumulate) & right-to-left (maximum.accumulate)
        s_h_min = np.where(cur, bh, inf_val)
        s_h_max = np.where(cur, bh, neg_inf)
        cur = cur | ((np.minimum.accumulate(s_h_min, axis=1) == bh) & dom)
        cur = cur | ((np.maximum.accumulate(s_h_max[:, ::-1], axis=1)[:, ::-1] == bh) & dom)
        # Top-to-bottom (bv non-decreasing: minimum.accumulate) & bottom-to-top (maximum.accumulate)
        s_v_min = np.where(cur, bv, inf_val)
        s_v_max = np.where(cur, bv, neg_inf)
        cur = cur | ((np.minimum.accumulate(s_v_min, axis=0) == bv) & dom)
        cur = cur | ((np.maximum.accumulate(s_v_max[::-1, :], axis=0)[::-1, :] == bv) & dom)
        if eight_conn:
            p = np.pad(cur, 1, mode="constant", constant_values=False)
            diag = p[:-2, :-2] | p[:-2, 2:] | p[2:, :-2] | p[2:, 2:]
            cur = cur | (diag & dom)
        if np.array_equal(cur, prev):
            break
    return cur


def _erode_3x3_bool_np(mask: np.ndarray) -> np.ndarray:
    p = np.pad(np.asarray(mask, dtype=bool), 1, mode="edge")
    return (
        p[1:-1, 1:-1]
        & p[:-2, 1:-1]
        & p[2:, 1:-1]
        & p[1:-1, :-2]
        & p[1:-1, 2:]
        & p[:-2, :-2]
        & p[:-2, 2:]
        & p[2:, :-2]
        & p[2:, 2:]
    )


def _build_corner_bridged_vision_card(arr_2x: np.ndarray) -> Image.Image:
    """Extrapolate canvas background from top-left/top-right corners so torso crops never form a synthetic card box."""
    h2, w2 = arr_2x.shape[:2]
    alpha_u8 = arr_2x[:, :, 3]
    if int(alpha_u8.min()) == 255:
        return Image.fromarray(arr_2x, mode="RGBA")
    ys_op, xs_op = np.where(alpha_u8 > 200)
    if len(ys_op) < 32:
        bg = Image.new("RGBA", (w2, h2), (242, 244, 248, 255))
        bg.alpha_composite(Image.fromarray(arr_2x, mode="RGBA"))
        return bg

    y0, y1 = int(ys_op.min()), int(ys_op.max())
    x0, x1 = int(xs_op.min()), int(xs_op.max())
    rgb = arr_2x[:, :, :3].astype(np.float32)

    y_band1 = min(y1 + 1, y0 + max(10, min(28, (y1 - y0) // 4)))
    span_w = max(1, x1 - x0 + 1)
    side_w = max(8, min(52, span_w // 5))

    tl_patch = rgb[y0:y_band1, x0 : min(x1 + 1, x0 + side_w)]
    tr_patch = rgb[y0:y_band1, max(x0, x1 + 1 - side_w) : x1 + 1]
    tl_med = np.median(tl_patch.reshape(-1, 3), axis=0) if tl_patch.size else np.array([244.0, 245.0, 247.0], dtype=np.float32)
    tr_med = np.median(tr_patch.reshape(-1, 3), axis=0) if tr_patch.size else tl_med

    # Smooth horizontal gradient bridging left corner to right corner across the central neck opening
    t_x = np.linspace(0.0, 1.0, w2, dtype=np.float32)[:, None]
    top_bridge_row = (1.0 - t_x) * tl_med[None, :] + t_x * tr_med[None, :]

    canvas = np.empty((h2, w2, 3), dtype=np.float32)
    canvas[:, :, :] = top_bridge_row[None, :, :]

    # Replicate actual left/right border columns of the placed rectangle outward on rows [y0:y1+1]
    for y in range(y0, y1 + 1):
        row_a = alpha_u8[y] > 200
        if np.any(row_a):
            rx0 = int(np.argmax(row_a))
            rx1 = int(w2 - 1 - np.argmax(row_a[::-1]))
            l_col = np.median(rgb[y, rx0 : min(w2, rx0 + 6)], axis=0)
            r_col = np.median(rgb[y, max(0, rx1 - 5) : rx1 + 1], axis=0)
            canvas[y, :rx0] = l_col
            canvas[y, rx1 + 1 :] = r_col
            canvas[y, rx0 : rx1 + 1] = rgb[y, rx0 : rx1 + 1]

    if y1 + 1 < h2:
        canvas[y1 + 1 :, :] = canvas[y1 : y1 + 1, :]

    # Blend semi-transparent edge pixels of arr_2x smoothly over extrapolated canvas
    a_f = (alpha_u8.astype(np.float32) / 255.0)[:, :, None]
    comp_rgb = np.clip(np.round(rgb * a_f + canvas * (1.0 - a_f)), 0.0, 255.0).astype(np.uint8)
    out_rgba = np.concatenate([comp_rgb, np.full((h2, w2, 1), 255, dtype=np.uint8)], axis=-1)
    return Image.fromarray(out_rgba, mode="RGBA")


def _apply_oklab_textile_crispness(rgb_2x: np.ndarray, fg_mask: np.ndarray, amount: float) -> np.ndarray:
    """Enhance micro-contrast of crests, sponsors, and stitching strictly in float32 OKLab Lightness."""
    amt = float(np.clip(amount, 0.0, 1.0)) if math.isfinite(float(amount)) else 0.35
    if amt <= 0.01:
        return rgb_2x
    srgb01 = np.clip(rgb_2x / 255.0, 0.0, 1.0).astype(np.float32)
    lab = srgb_to_oklab(srgb01)
    l_chan = lab[:, :, 0]
    l_blur = fast_tent_f32(l_chan, r=1)
    interior = np.clip((fg_mask - 0.82) / 0.16, 0.0, 1.0)
    raw_detail = l_chan - l_blur
    cored = np.sign(raw_detail) * np.maximum(np.abs(raw_detail) - 0.0018, 0.0)
    detail = np.clip(cored, -0.055, 0.055)
    lab[:, :, 0] = np.clip(l_chan + detail * (0.95 * amt) * interior, 0.0, 1.0)
    return np.clip(oklab_to_srgb(lab, preserve_hue_gamut=True) * 255.0, 0.0, 255.0).astype(np.float32)


def sanitize_shirt_template_rgba(
    raw_rgba: Image.Image,
    symmetrize_shoulders: bool = True,
    shoulder_boost: float = 0.0,
    zoom: float = 1.0,
    pan_x: float = 0.0,
    pan_y: float = 0.0,
    detail_crispness: float = 0.35,
) -> Image.Image:
    """2x super-sampled (520x620) shirt extractor with Corner-Bridged Vision, WGIF Matting, and Pure-NumPy Topology."""
    zoom_c, px_c, py_c = _sanitize_viewport(zoom, pan_x, pan_y)
    raw_src_rgba = raw_rgba.convert("RGBA")
    raw_src_a = np.asarray(raw_src_rgba, dtype=np.uint8)[:, :, 3]
    is_pure_cut = (
        is_df11_pure_size(raw_src_rgba.size)
        and int(raw_src_a[:60, :20].max()) == 0
        and int(raw_src_a[:60, -20:].max()) == 0
    )
    if is_df11_pure_size(raw_src_rgba.size):
        raw_src_rgba = pad_pure_to_df11_canvas(raw_src_rgba, unfeather_edges=True)
        raw_src_a = np.asarray(raw_src_rgba, dtype=np.uint8)[:, :, 3]
    is_pre_cut = is_pure_cut or (
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

    vision_card = _build_corner_bridged_vision_card(arr) if int(arr[:, :, 3].min()) < 255 else card_2x

    probs = vision_mod.segment_portrait_classes(vision_card)
    p_bg = probs[:, :, vision_mod.CLASS_BG]
    p_clothes = probs[:, :, vision_mod.CLASS_CLOTHES]
    p_others = probs[:, :, vision_mod.CLASS_OTHERS]
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

    # Unify clothes + lower-torso accessories (ties/lapels/zippers for Staff templates) below y > 182
    tie_ramp = np.clip((yy - 182.0) / 14.0, 0.0, 1.0)
    p_garment = np.clip(p_clothes + p_others * tie_ramp * np.clip((0.35 - p_skin_hair) / 0.25, 0.0, 1.0), 0.0, 1.0)

    # Edge-Guided Collar Matting (expanded down to yy <= 220 so headless torso crops with neck skin at y=168..215 are covered)
    p_skin_eff = p_skin_hair
    neck_seed = (
        (np.abs(xx - 130.0) < 38.0)
        & (yy >= 135.0)
        & (yy <= 220.0)
        & (p_skin_hair > 0.72)
        & (p_garment < 0.18)
        & (raw_a > 0.85)
    )
    skin_px_count = int(neck_seed.sum())
    if skin_px_count >= 50:
        band_y0, band_y1 = 162 * ss, min(h2, 242 * ss)
        lab_neck = vision_mod.srgb_to_oklab(np.clip(rgb_f[neck_seed] / 255.0, 0.0, 1.0).reshape(-1, 1, 3))[:, 0, :]
        skin_med = np.median(lab_neck, axis=0)
        lab_band = vision_mod.srgb_to_oklab(np.clip(rgb_f[band_y0:band_y1] / 255.0, 0.0, 1.0))
        d_l = (lab_band[:, :, 0] - float(skin_med[0])) * 0.65
        d_ab = np.hypot(lab_band[:, :, 1] - float(skin_med[1]), lab_band[:, :, 2] - float(skin_med[2])) * 2.6
        d_skin = np.hypot(d_l, d_ab)
        ps_band = p_skin_hair[band_y0:band_y1]
        pc_band = p_garment[band_y0:band_y1]
        fabric_snap = (
            np.clip((d_skin - 0.14) / 0.11, 0.0, 1.0)
            * np.clip((0.74 - ps_band) / 0.34, 0.0, 1.0)
            * np.clip((pc_band - 0.05) / 0.22, 0.25, 1.0)
        )
        p_skin_eff = p_skin_hair.copy()
        p_skin_eff[band_y0:band_y1] = ps_band * (1.0 - 0.84 * fabric_snap)

    # Exterior Background Color Suppression in OKLab (strictly seeded outside central neck channel |x-130| >= 44)
    lab_2x = srgb_to_oklab(np.clip(rgb_f / 255.0, 0.0, 1.0))
    bg_ext_mask = np.zeros((h2, w2), dtype=bool)
    if not is_pre_cut:
        ys_r, xs_r = np.where(raw_a > 0.85)
        if len(ys_r) >= 64:
            ry0 = float(ys_r.min()) / ss
            rx0 = float(xs_r.min()) / ss
            rx1 = float(xs_r.max()) / ss
            outer_x = np.abs(xx - 130.0) >= 44.0
            # Seed background from upper exterior air above shoulders ONLY where BiRefNet is genuinely low (< 0.35)
            # AND MediaPipe also sees background (p_bg > 0.45) rather than garment (p_garment < 0.25)
            upper_air_seed = (
                outer_x
                & (yy >= max(12.0, ry0))
                & (yy <= min(192.0, max(186.0, ry0 + 36.0)))
                & (raw_a > 0.85)
                & (biref_a < 0.35)
                & (p_bg > 0.45)
                & (p_garment < 0.25)
                & (p_skin_eff < 0.32)
            )
            # Only seed lateral margins where BiRefNet is genuinely low (< 0.30) above y <= 212 so sleeves at x=19..241 are never sampled
            lat_margin_seed = (
                ((xx <= max(24.0, rx0 + 6.0)) | (xx >= min(236.0, rx1 - 6.0)))
                & (yy >= max(168.0, ry0))
                & (yy <= 212.0)
                & (raw_a > 0.85)
                & (biref_a < 0.30)
                & (p_bg > 0.50)
                & (p_garment < 0.22)
                & (p_skin_eff < 0.32)
            )
            bg_seeds = upper_air_seed | lat_margin_seed
            if int(bg_seeds.sum()) >= 20:
                bg_med = np.median(lab_2x[bg_seeds], axis=0)
                d_bg = np.hypot(
                    (lab_2x[:, :, 0] - float(bg_med[0])) * 0.85,
                    np.hypot(lab_2x[:, :, 1] - float(bg_med[1]), lab_2x[:, :, 2] - float(bg_med[2])) * 2.3,
                )
                # Only suppress exterior background where BiRefNet is NOT confident (< 0.55) OR in the upper shoulder air (yy < 204)
                # where MediaPipe has zero garment confidence (p_garment < 0.28 and p_bg > 0.52)
                bg_domain = (
                    (raw_a > 0.1)
                    & (d_bg < 0.048)
                    & (p_garment < 0.28)
                    & ((biref_a < 0.48) | ((yy < 204.0) & (p_bg > 0.55)))
                )
                bg_ext_mask = _flood_fill_mask_np(bg_domain, bg_seeds, eight_conn=True)

    non_skin_gate = np.clip((0.36 - p_skin_eff) / 0.24, 0.0, 1.0)
    w_has_skin = float(np.clip(skin_px_count / 120.0, 0.15, 1.0))
    collar_neck_zone = (
        np.clip((52.0 - np.abs(xx - 130.0)) / 10.0, 0.0, 1.0)
        * np.clip((232.0 - yy) / 14.0, 0.0, 1.0)
        * w_has_skin
    )
    collar_cloth_gate = np.clip((p_garment - 0.90 * p_skin_eff - 0.10) / 0.40, 0.0, 1.0)
    effective_gate = collar_neck_zone * collar_cloth_gate + (1.0 - collar_neck_zone) * non_skin_gate
    effective_gate = np.where(yy < 162.0, 0.0, effective_gate)

    cloth_conf = np.where(
        yy >= 170.0,
        np.clip((p_garment - 0.24) / 0.32, 0.0, 1.0) * np.clip((0.68 - p_bg) / 0.42, 0.0, 1.0) * non_skin_gate * raw_a,
        0.0,
    )
    # Trust BiRefNet across the shirt body (so white-on-white sleeves where MediaPipe p_clothes drops to 0.03 stay at 1.0!),
    # while bg_ext_mask and effective_gate cleanly remove exterior background and neck skin
    biref_gated = biref_a
    fg_shirt = np.maximum(biref_gated, cloth_conf) * effective_gate
    fg_shirt = np.where(bg_ext_mask, 0.0, fg_shirt)

    sleeve_solid_band = fg_shirt[188 * ss :, :] > 0.65
    has_col_solid = sleeve_solid_band.any(axis=0)
    first_solid_y = np.where(has_col_solid, 188 * ss + sleeve_solid_band.argmax(axis=0), h2 - 1)
    ref_col_rgb = rgb_f[np.minimum(first_solid_y + 4, h2 - 1), np.arange(w2)]

    x_mir = np.clip(w2 - 1 - np.arange(w2, dtype=np.int32), 0, w2 - 1)
    outer_shoulder_zone = (np.abs(xx - 130.0) >= 45.0) & (yy >= 188.0)

    if symmetrize_shoulders:
        fg_mirror = fg_shirt[:, x_mir]
        diff_mir = np.abs(rgb_f - rgb_f[:, x_mir, :]).max(axis=-1) / 255.0
        diff_col = np.abs(rgb_f - ref_col_rgb[None, :, :]).max(axis=-1) / 255.0
        not_bg_over_dark_sleeve = ~(has_col_solid[None, :] & (diff_col > 0.28) & (p_garment < 0.38))
        cloth_coherent = (
            ((diff_mir < 0.20) | (has_col_solid[None, :] & (diff_col < 0.16)))
            & not_bg_over_dark_sleeve
            & ((~bg_ext_mask) | (diff_mir < 0.08))
            & ((biref_a[:, x_mir] > 0.65) | (p_garment > 0.28))
        )
        need_sym = (
            outer_shoulder_zone
            & (raw_a > 0.5)
            & (raw_a[:, x_mir] > 0.5)
            & (non_skin_gate > 0.75)
            & (fg_shirt < 0.65)
            & cloth_coherent
        )
        fg_shirt = np.where(need_sym, np.maximum(fg_shirt, fg_mirror * 0.98), fg_shirt)

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
                col_iter = range(x1_s - 1, x0_s - 1, -1) if side_sign < 0 else range(x0_s, x1_s)
                for xc in col_iter:
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

    # Pure-NumPy topological hole healing (heals white crests/umbro/sponsors while keeping neck opening exterior)
    solid_bin = fg_shirt > 0.52
    ext_seeds = np.zeros((h2, w2), dtype=bool)
    ext_seeds[0, :] = True
    ext_seeds[-1, :] = True
    ext_seeds[:, 0] = True
    ext_seeds[:, -1] = True
    ext_seeds[: 164 * ss, :] = True
    skin_hole_seed = (np.abs(xx - 130.0) < 48.0) & (yy < 232.0) & (p_skin_hair > 0.35)
    ext_bg_reach = _flood_fill_mask_np(~solid_bin, ext_seeds | skin_hole_seed, eight_conn=False)
    enclosed_holes = (~solid_bin) & (~ext_bg_reach) & (yy >= 184.0) & (raw_a > 0.80) & (p_skin_eff < 0.25)
    fg_shirt = np.where(enclosed_holes, np.maximum(fg_shirt, 0.98), fg_shirt)

    # Keep only foreground connected to the main torso component (eliminates floating shoulder/hair islands)
    support_bin = fg_shirt > 0.14
    torso_seeds = support_bin & (np.abs(xx - 130.0) <= 95.0) & (yy >= 205.0) & (yy <= 290.0)
    if np.any(torso_seeds):
        connected_torso = _flood_fill_mask_np(support_bin, torso_seeds, eight_conn=True)
        fg_shirt = np.where(connected_torso, fg_shirt, 0.0)

    # Edge-Guided Alpha Refinement (r=2 preserves thin sleeve stripes while snapping silhouette to textile edges)
    core_solid = _erode_3x3_bool_np(fg_shirt > 0.90)
    guided_a, _ = _wgif_single_channel(
        lab_2x[:, :, 0].astype(np.float32),
        fg_shirt.astype(np.float32),
        r=2,
        eps_base=0.0004,
        edge_pivot=0.045,
    )
    fg_shirt = np.clip(np.where(core_solid, np.maximum(guided_a, 0.99), guided_a), 0.0, 1.0) * raw_a
    fg_shirt = np.where((bg_ext_mask & (fg_shirt < 0.75)) | (yy < 162.0), 0.0, fg_shirt)

    # Boundary-only RGB decontamination: 100% untouched original pixels inside opaque fabric (fg_shirt >= 0.93)
    w_pure = (fg_shirt > 0.90).astype(np.float32) * np.clip((0.06 - p_skin_eff) / 0.06, 0.0, 1.0)
    w_pure[: 182 * ss, :] *= np.clip((p_garment[: 182 * ss, :] - 0.60) / 0.25, 0.0, 1.0)
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
    smooth_alpha_2x = np.asarray(raw_alpha_img.filter(ImageFilter.GaussianBlur(0.75)), dtype=np.float32) / 255.0
    crisp_alpha_2x = np.where(fg_shirt > 0.88, np.maximum(smooth_alpha_2x, 0.996), smooth_alpha_2x)

    # Linear-light single-premultiplied 2x -> 1x Lanczos SSAA downsampling (avoids Pillow RGBA double-premultiply)
    clean_u8_2x = np.clip(np.round(clean_rgb_2x), 0.0, 255.0).astype(np.uint8)
    lin_2x = srgb_u8_to_linear(clean_u8_2x)
    alpha_f_2x = crisp_alpha_2x.astype(np.float32)
    premul_lin_2x = lin_2x * alpha_f_2x[:, :, None]

    a_1x = np.asarray(
        Image.fromarray(alpha_f_2x, mode="F").resize((DF11_WIDTH, DF11_HEIGHT), Image.Resampling.LANCZOS),
        dtype=np.float32,
    )
    a_1x = np.clip(a_1x, 0.0, 1.0)
    a_1x = np.where(a_1x > 0.985, 1.0, a_1x)

    lin_1x = np.empty((DF11_HEIGHT, DF11_WIDTH, 3), dtype=np.float32)
    for c in range(3):
        ch_1x = np.asarray(
            Image.fromarray(premul_lin_2x[:, :, c], mode="F").resize((DF11_WIDTH, DF11_HEIGHT), Image.Resampling.LANCZOS),
            dtype=np.float32,
        )
        lin_1x[:, :, c] = ch_1x
    safe_a_1x = np.maximum(a_1x[:, :, None], 1e-4)
    unpremul_lin_1x = np.where(a_1x[:, :, None] > 1e-4, np.clip(lin_1x / safe_a_1x, 0.0, 1.0), 0.0)
    rgb_1x = linear_to_srgb_u8(unpremul_lin_1x)

    rect_mask_f = inner_mask_f.copy()
    rect_mask_f[260:293, 19:242] = 1.0
    final_a = np.clip(np.round(a_1x * rect_mask_f * 255.0), 0.0, 255.0).astype(np.uint8)
    final_a[:162, :] = 0
    final_a[:, :19] = 0
    final_a[:, 242:] = 0
    final_a[293:, :] = 0

    clean_rgb = np.where(final_a[:, :, None] > 0, rgb_1x, 0)
    out = np.concatenate([clean_rgb, final_a[:, :, None]], axis=-1)
    return Image.fromarray(out, mode="RGBA")


def extract_collar_profile(clean_shirt_rgba: Image.Image) -> CollarProfile:
    """Measure exact symmetric inner left/right collar rim peaks, deepest V/U apex, and shoulder curve from shirt alpha."""
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
    if int(left_slice.min()) < DF11_HEIGHT:
        y_min_l = int(left_slice.min())
        # Pick the innermost (rightmost) point of the left collar crest plateau (+2px tolerance)
        cand_l = np.where(left_slice <= y_min_l + 2)[0]
        x_l = int(62 + cand_l[-1]) if len(cand_l) else int(62 + np.argmin(left_slice))
        y_l = int(sm[x_l])
    else:
        x_l, y_l = 92, 196

    right_slice = sm[138:199]
    if int(right_slice.min()) < DF11_HEIGHT:
        y_min_r = int(right_slice.min())
        # Pick the innermost (leftmost) point of the right collar crest plateau (+2px tolerance)
        cand_r = np.where(right_slice <= y_min_r + 2)[0]
        x_r = int(138 + cand_r[0]) if len(cand_r) else int(138 + np.argmin(right_slice))
        y_r = int(sm[x_r])
    else:
        x_r, y_r = 168, 196

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
