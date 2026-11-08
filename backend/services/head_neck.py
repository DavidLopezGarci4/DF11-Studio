"""Non-destructive Head & Neck Extractor, CollarFunnelMask, and Directional Columnar OKLab NeckBridge."""

from __future__ import annotations

from dataclasses import dataclass
import io
import math
import os
from pathlib import Path
import re
import tempfile
from typing import Literal

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

import backend.services.vision as vision_mod
from backend.core.compositor import (
    BgMode,
    DF11_HEIGHT,
    DF11_WIDTH,
    is_df11_pure_size,
    pad_pure_to_df11_canvas,
    premul_over,
    render_df11_card,
)
from backend.core.dsp import (
    enhance_df11_pure_optics,
    oklab_to_srgb,
    resample_linear_subpixel_rgba,
    srgb_to_oklab,
)
from backend.core.fm_config import safe_ntfs_replace
from backend.core.paths import get_caras_prueba_dir, get_extracted_faces_dir
from backend.services.templates import CollarProfile, IMAGE_EXTS, _has_df11_outer_ring
from backend.services.vision import FacePose

CROWN_SAFE_Y = 21.0
MAX_HEAD_ASSET_SIDE = 640
DEFAULT_DF11_COLLAR = CollarProfile(
    left_rim=(91, 198),
    right_rim=(169, 198),
    apex=(130, 226),
    collar_width=78,
    y_top_curve=tuple([198] * DF11_WIDTH),
)


@dataclass(frozen=True, slots=True)
class CropViewport:
    """User-selected framing in 260x310 DF11 stage space before extraction."""

    zoom: float = 1.0
    pan_x: float = 0.0
    pan_y: float = 0.0


@dataclass(frozen=True, slots=True)
class HeadNeckAsset:
    rgba: Image.Image
    skin_mask: Image.Image
    body_skin_mask: Image.Image
    front_occluder_alpha: Image.Image
    pose: FacePose | None
    crown_y: int
    chin_y: float
    skin_oklab: tuple[float, float, float]
    viewport: CropViewport
    roi_box: tuple[int, int, int, int] = (0, 0, DF11_WIDTH, DF11_HEIGHT)
    raw_size: tuple[int, int] = (DF11_WIDTH, DF11_HEIGHT)
    is_pre_cutout: bool = True
    source_rgba: Image.Image | None = None
    source_fg_alpha: Image.Image | None = None


@dataclass(frozen=True, slots=True)
class HeadFitParams:
    scale: float = 1.0
    offset_x: float = 0.0
    offset_y: float = 0.0
    neck_fill: float = 1.0
    harmonize: bool = True


def prepare_facepack_card_for_head_extraction(raw_rgba: Image.Image, default_is_precut: bool = False) -> tuple[Image.Image, bool]:
    """Unframe an already-assembled 260x310 Classic or 220x276 Pure DF11 card for clean head extraction."""
    im = raw_rgba.convert("RGBA")
    if is_df11_pure_size(im.size):
        p_alpha = np.asarray(im, dtype=np.uint8)[:, :, 3]
        top_clear = int(p_alpha[:55, :20].max()) == 0 and int(p_alpha[:55, -20:].max()) == 0
        return pad_pure_to_df11_canvas(im, unfeather_edges=False), (True if top_clear else default_is_precut)
    if not _has_df11_outer_ring(im):
        return im, default_is_precut

    arr = np.asarray(im, dtype=np.uint8).copy()
    alpha = arr[:, :, 3]
    tl_opaque = float((alpha[24:90, 24:54] > 220).mean())
    tr_opaque = float((alpha[24:90, 206:236] > 220).mean())
    if max(tl_opaque, tr_opaque) >= 0.55:
        # Composite semi-transparent/transparent interior pixels over neutral light studio backdrop before solidifying alpha
        a_f = arr[:, :, 3:4].astype(np.float32) / 255.0
        arr[:, :, :3] = np.clip(
            np.round(arr[:, :, :3].astype(np.float32) * a_f + 240.0 * (1.0 - a_f)),
            0.0,
            255.0,
        ).astype(np.uint8)
        # Replicate interior [21:290, 22:238] outward so BiRefNet strips wall cleanly
        arr[:21, 22:238, :3] = arr[21:22, 22:238, :3]
        arr[290:, 22:238, :3] = arr[289:290, 22:238, :3]
        arr[:, :22, :3] = arr[:, 22:23, :3]
        arr[:, 238:, :3] = arr[:, 237:238, :3]
        arr[:, :, 3] = 255
        return Image.fromarray(arr, mode="RGBA"), False

    # Transparent-background DF11 card: strip the 3D silver bevel frame ring outside the inner window
    arr[:21, :, :] = 0
    arr[290:, :, :] = 0
    arr[:, :22, :] = 0
    arr[:, 238:, :] = 0
    return Image.fromarray(arr, mode="RGBA"), True


def suggest_safe_crop_viewport(raw_rgba: Image.Image) -> CropViewport:
    """Suggest initial wheel-zoom and pan so the head & neck fill DF11 without chopping the crown."""
    w, h = raw_rgba.size
    fit_base = min(DF11_WIDTH / max(w, 1), DF11_HEIGHT / max(h, 1))
    pose = vision_mod.detect_face_pose(raw_rgba)
    alpha = np.asarray(raw_rgba.convert("RGBA"), dtype=np.uint8)[:, :, 3]
    ys = np.where(alpha > 24)[0]
    crown_src = float(ys.min()) if len(ys) else 0.0

    if pose is None:
        return CropViewport(zoom=1.0, pan_x=0.0, pan_y=0.0)

    desired_total_scale = 42.5 / max(pose.ipd, 14.0)
    zoom = float(np.clip(desired_total_scale / max(fit_base, 1e-4), 0.45, 3.2))
    eff_scale = fit_base * zoom

    eyes_target_y = 113.0
    crown_canvas_y = eyes_target_y - (pose.eye_center[1] - crown_src) * eff_scale
    if crown_canvas_y < CROWN_SAFE_Y:
        eyes_target_y = min(121.0, eyes_target_y + (CROWN_SAFE_Y - crown_canvas_y) * 0.65)
        max_eff = (eyes_target_y - CROWN_SAFE_Y) / max(pose.eye_center[1] - crown_src, 1.0)
        zoom = float(np.clip(min(zoom, max_eff / max(fit_base, 1e-4)), 0.35, 3.2))
        eff_scale = fit_base * zoom

    disp_w, disp_h = w * eff_scale, h * eff_scale
    x0_ideal = 130.0 - pose.eye_center[0] * eff_scale
    y0_ideal = eyes_target_y - pose.eye_center[1] * eff_scale
    pan_x = round(x0_ideal - (DF11_WIDTH - disp_w) * 0.5, 1)
    pan_y = round(y0_ideal - (DF11_HEIGHT - disp_h) * 0.5, 1)
    return CropViewport(zoom=round(zoom, 3), pan_x=pan_x, pan_y=pan_y)


def _compute_context_expanded_roi(size: tuple[int, int], vp: CropViewport) -> tuple[int, int, int, int]:
    """Map user CropViewport back to raw image coordinates with +40% shoulder/neck context padding."""
    w, h = size
    fit_base = min(DF11_WIDTH / max(w, 1), DF11_HEIGHT / max(h, 1))
    eff_scale = max(fit_base * max(vp.zoom, 0.25), 1e-4)
    disp_w, disp_h = w * eff_scale, h * eff_scale
    x0 = (DF11_WIDTH - disp_w) * 0.5 + vp.pan_x
    y0 = (DF11_HEIGHT - disp_h) * 0.5 + vp.pan_y

    src_x0 = (0.0 - x0) / eff_scale
    src_y0 = (0.0 - y0) / eff_scale
    src_x1 = (DF11_WIDTH - x0) / eff_scale
    src_y1 = (DF11_HEIGHT - y0) / eff_scale

    bw, bh = max(src_x1 - src_x0, 32.0), max(src_y1 - src_y0, 32.0)
    rx0 = max(0, int(np.floor(src_x0 - 0.40 * bw)))
    ry0 = max(0, int(np.floor(src_y0 - 0.25 * bh)))
    rx1 = min(w, int(np.ceil(src_x1 + 0.40 * bw)))
    ry1 = min(h, int(np.ceil(src_y1 + 0.48 * bh)))

    if (rx1 - rx0) * (ry1 - ry0) >= 0.72 * (w * h) or rx1 - rx0 < 48 or ry1 - ry0 < 48:
        return (0, 0, w, h)
    return (rx0, ry0, rx1, ry1)


def extract_clean_head_and_neck(
    raw_rgba: Image.Image,
    is_pre_cutout: bool = False,
    crop_viewport: CropViewport | None = None,
    remove_bg: bool = True,
) -> HeadNeckAsset:
    """Extract clean Head + Neck (stripping CLASS_CLOTHES and isolating beard-free skin chrominance)."""
    vp = crop_viewport or CropViewport()
    rx0, ry0, rx1, ry1 = _compute_context_expanded_roi(raw_rgba.size, vp)
    roi = raw_rgba.convert("RGBA").crop((rx0, ry0, rx1, ry1))
    if max(roi.size) > MAX_HEAD_ASSET_SIDE:
        shrink = MAX_HEAD_ASSET_SIDE / float(max(roi.size))
        roi = roi.resize(
            (max(1, round(roi.width * shrink)), max(1, round(roi.height * shrink))),
            Image.Resampling.LANCZOS,
        )
    src_scene = None if is_pre_cutout else roi.copy()
    fg_rgba = roi if (is_pre_cutout or not remove_bg) else vision_mod.remove_background_birefnet(roi)
    src_fg_alpha = fg_rgba.getchannel("A") if (not is_pre_cutout and remove_bg) else None
    arr = np.asarray(fg_rgba.convert("RGBA"), dtype=np.uint8).copy()
    h, w = arr.shape[:2]

    probs = vision_mod.segment_portrait_classes(fg_rgba)
    p_hair = probs[:, :, vision_mod.CLASS_HAIR]
    p_body = probs[:, :, vision_mod.CLASS_BODY_SKIN]
    p_face = probs[:, :, vision_mod.CLASS_FACE_SKIN]
    p_clothes = probs[:, :, vision_mod.CLASS_CLOTHES]
    p_others = probs[:, :, vision_mod.CLASS_OTHERS]

    # Strip old jersey/collar pixels cleanly and decontaminate 1.5px upward from clean skin/hair
    cloth_keep = np.clip((0.52 - p_clothes) / 0.34, 0.0, 1.0)
    raw_a = arr[:, :, 3].astype(np.float32) / 255.0
    clean_a = np.clip(np.round(raw_a * cloth_keep * 255.0), 0.0, 255.0).astype(np.uint8)

    rgb_f = arr[:, :, :3].astype(np.float32)
    w_non_cloth = np.clip((0.20 - p_clothes) / 0.20, 0.0, 1.0) * (clean_a > 140)
    premul = np.concatenate([rgb_f * w_non_cloth[:, :, None], w_non_cloth[:, :, None] * 255.0], axis=-1).clip(0.0, 255.0).round().astype(np.uint8)
    blurred = np.asarray(Image.fromarray(premul, mode="RGBA").filter(ImageFilter.GaussianBlur(2.2)), dtype=np.float32)
    wb = blurred[:, :, 3:4] / 255.0
    safe_rgb = np.where(wb > 1e-3, blurred[:, :, :3] / np.maximum(wb, 1e-3), rgb_f)
    decontam = np.where(wb[:, :, 0] > 0.02, np.clip(p_clothes * 2.5, 0.0, 1.0), 0.0)[:, :, None]
    arr[:, :, :3] = np.clip(np.round(rgb_f * (1.0 - decontam) + safe_rgb * decontam), 0.0, 255.0).astype(np.uint8)
    arr[:, :, 3] = clean_a
    arr[:, :, :3] = np.where(clean_a[:, :, None] > 0, arr[:, :, :3], 0)

    clean_im = Image.fromarray(arr, mode="RGBA")
    pose = vision_mod.detect_face_pose(clean_im)

    ys = np.where(clean_a > 28)[0]
    crown_y = int(ys.min()) if len(ys) else 0
    fg_bot = int(ys.max()) if len(ys) else h - 1
    chin_y = float(pose.eye_center[1] + 1.78 * pose.ipd) if pose is not None else float(crown_y + 0.72 * max(fg_bot - crown_y, 60))

    # Sample beard-free facial skin chrominance in OKLab from upper cheeks/forehead
    lab_full = srgb_to_oklab(arr[:, :, :3].astype(np.float32) / 255.0)
    yy = np.arange(h, dtype=np.float32)[:, None]
    if pose is not None:
        upper_face_band = (yy >= pose.eye_center[1] - 0.38 * pose.ipd) & (yy <= pose.eye_center[1] + 0.80 * pose.ipd)
    else:
        upper_face_band = (yy >= crown_y + 0.18 * (fg_bot - crown_y)) & (yy <= crown_y + 0.52 * (fg_bot - crown_y))

    cheek_sel = upper_face_band & (p_face > 0.58) & (p_hair < 0.15) & (clean_a > 180)
    if int(cheek_sel.sum()) < 25:
        cheek_sel = ((p_face + p_body) > 0.50) & (clean_a > 160)
    if int(cheek_sel.sum()) >= 10:
        med_lab = np.median(lab_full[cheek_sel], axis=0)
        skin_oklab = (float(np.clip(med_lab[0], 0.24, 0.90)), float(med_lab[1]), float(med_lab[2]))
    else:
        skin_oklab = (0.68, 0.032, 0.058)

    # Smart occluder mask: strictly hair (where p_hair > p_body) + accessories so neck skin never bleeds into z5 over shirt
    hair_only = np.where(p_hair > p_body + 0.04, p_hair, p_hair * 0.15)
    occ_p = np.clip(hair_only + p_others, 0.0, 1.0)
    trunc_cols = (clean_a[max(0, h - 2) :, :].max(axis=0) > 80) & (occ_p[max(0, h - 2) :, :].max(axis=0) > 0.35)
    if np.any(trunc_cols):
        kernel = np.ones(5, dtype=np.float32)
        trunc_dilated = np.convolve(trunc_cols.astype(np.float32), kernel, mode="same") > 0.5
        bottom_tuck = np.clip(((h - 2.0) - yy) / 10.0, 0.0, 1.0)
        occ_p = np.where(trunc_dilated[None, :], occ_p * bottom_tuck, occ_p)
        cx_src = float(pose.eye_center[0]) if pose is not None else w * 0.5
        half_neck_src = float(pose.ipd * 0.82) if pose is not None else w * 0.22
        xx_src = np.arange(w, dtype=np.float32)[None, :]
        outer_bottom_cut = (np.abs(xx_src - cx_src) > half_neck_src) & trunc_dilated[None, :] & (yy >= h - 9.0)
        corner_fade = np.clip(((h - 1.5) - yy) / 7.5, 0.0, 1.0)
        clean_a = np.where(outer_bottom_cut, np.round(clean_a.astype(np.float32) * corner_fade).astype(np.uint8), clean_a)
        arr[:, :, 3] = clean_a
        arr[:, :, :3] = np.where(clean_a[:, :, None] > 0, arr[:, :, :3], 0)
        clean_im = Image.fromarray(arr, mode="RGBA")

    skin_u8 = np.clip(np.round((p_face + p_body) * 255.0), 0.0, 255.0).astype(np.uint8)
    # Exclude dark beard pixels from body_skin_mask by gating against face/cheek lightness floor
    clean_neck_skin = p_body * ((lab_full[:, :, 0] > (skin_oklab[0] - 0.16)).astype(np.float32))
    body_u8 = np.clip(np.round(clean_neck_skin * 255.0), 0.0, 255.0).astype(np.uint8)
    occ_u8 = np.clip(np.round(occ_p * (clean_a.astype(np.float32) / 255.0) * 255.0), 0.0, 255.0).astype(np.uint8)

    return HeadNeckAsset(
        rgba=clean_im,
        skin_mask=Image.fromarray(skin_u8, mode="L"),
        body_skin_mask=Image.fromarray(body_u8, mode="L"),
        front_occluder_alpha=Image.fromarray(occ_u8, mode="L"),
        pose=pose,
        crown_y=crown_y,
        chin_y=chin_y,
        skin_oklab=skin_oklab,
        viewport=vp,
        roi_box=(rx0, ry0, rx1, ry1),
        raw_size=raw_rgba.size,
        is_pre_cutout=is_pre_cutout,
        source_rgba=src_scene,
        source_fg_alpha=src_fg_alpha,
    )


def viewport_to_head_fit(head_asset: HeadNeckAsset, vp: CropViewport | None = None) -> HeadFitParams:
    """Map a 260x310 pre-crop CropViewport directly into HeadFitParams for head_asset."""
    use_vp = vp or head_asset.viewport
    rw, rh = head_asset.raw_size
    rx0, ry0, rx1, _ = head_asset.roi_box
    roi_w = max(rx1 - rx0, 1)
    roi_scale = head_asset.rgba.width / float(roi_w)
    fit_base = min(DF11_WIDTH / max(rw, 1), DF11_HEIGHT / max(rh, 1))
    eff_scale = max(fit_base * max(use_vp.zoom, 0.20), 1e-4)
    disp_w, disp_h = rw * eff_scale, rh * eff_scale
    raw_x0 = (DF11_WIDTH - disp_w) * 0.5 + use_vp.pan_x
    raw_y0 = (DF11_HEIGHT - disp_h) * 0.5 + use_vp.pan_y

    scale = float(np.clip(eff_scale / max(roi_scale, 1e-4), 0.10, 2.4))
    pw, ph = head_asset.rgba.width * scale, head_asset.rgba.height * scale
    x0 = raw_x0 + rx0 * eff_scale
    y0 = raw_y0 + ry0 * eff_scale
    offset_x = round(x0 - (DF11_WIDTH - pw) * 0.5, 1)
    offset_y = round(y0 - (DF11_HEIGHT - ph) * 0.5, 1)
    return HeadFitParams(scale=round(scale, 4), offset_x=offset_x, offset_y=offset_y, neck_fill=1.0, harmonize=True)


def fit_head_to_shirt_template(head_asset: HeadNeckAsset, collar: CollarProfile) -> HeadFitParams:
    """Compute natural scale and (offset_x, offset_y) seating head into collar with Crown Ceiling Guard."""
    w, h = head_asset.rgba.size
    cx_collar = 0.5 * (collar.left_rim[0] + collar.right_rim[0])
    _, y_v = collar.apex
    alpha = np.asarray(head_asset.rgba, dtype=np.uint8)[:, :, 3]
    ys_fg = np.where(alpha > 28)[0]
    fg_bot_src = float(ys_fg.max()) if len(ys_fg) else float(h - 1)
    # Collar width is outer peak-to-peak (~83px on DF11); target IPD ~42.5px (~0.51 * outer peak width)
    target_ipd = float(np.clip(collar.collar_width * 0.515, 39.5, 45.0))

    if head_asset.pose is not None:
        scale = float(np.clip(target_ipd / max(head_asset.pose.ipd, 14.0), 0.10, 2.4))
        # Authentic DF11 eye line sits ~113.5px above y=0 (i.e. y_v - 113.0 for V-apex=227)
        eyes_y_target = float(np.clip(y_v - 113.0, 111.0, 120.0))
        # If portrait has a short neck cut above y_v, seat up to +4.5px lower to minimize artificial bridge
        bot_at_base = eyes_y_target + (fg_bot_src - head_asset.pose.eye_center[1]) * scale
        if bot_at_base < y_v - 4.0:
            seat_drop = min(4.5, (y_v - 4.0 - bot_at_base) * 0.32)
            eyes_y_target = min(120.5, eyes_y_target + seat_drop)

        above_eyes = max(0.0, head_asset.pose.eye_center[1] - float(head_asset.crown_y))
        crown_canvas = eyes_y_target - above_eyes * scale
        if crown_canvas < CROWN_SAFE_Y:
            eyes_y_target = min(122.0, eyes_y_target + (CROWN_SAFE_Y - crown_canvas) * 0.65)
            crown_canvas = eyes_y_target - above_eyes * scale
            if crown_canvas < CROWN_SAFE_Y and above_eyes > 1.0:
                scale = float(np.clip((eyes_y_target - CROWN_SAFE_Y) / above_eyes, 0.10, 2.4))
        nw, nh = max(1, round(w * scale)), max(1, round(h * scale))
        neck_axis_x = head_asset.pose.eye_center[0] + head_asset.pose.yaw * 0.10 * head_asset.pose.ipd
        x0 = cx_collar - neck_axis_x * scale
        y0 = eyes_y_target - head_asset.pose.eye_center[1] * scale
    else:
        ys, xs = np.where(alpha > 28)
        fg_w = max(int(xs.max() - xs.min() + 1), 80) if len(xs) else w
        scale = float(np.clip((collar.collar_width * 1.75) / fg_w, 0.10, 2.0))
        nw, nh = max(1, round(w * scale)), max(1, round(h * scale))
        x0 = cx_collar - nw * 0.5
        y0 = max(CROWN_SAFE_Y, 28.0) - head_asset.crown_y * scale

    offset_x = round(x0 - (DF11_WIDTH - nw) * 0.5, 1)
    offset_y = round(y0 - (DF11_HEIGHT - nh) * 0.5, 1)
    return HeadFitParams(scale=round(scale, 4), offset_x=offset_x, offset_y=offset_y, neck_fill=1.0, harmonize=True)


def _harmonize_melanin_safe(arr_rgba: np.ndarray) -> np.ndarray:
    """Lift genuinely underexposed dim photos (92nd percentile L < 0.70) without bleaching dark skin."""
    out = arr_rgba.copy()
    fg = out[:, :, 3] > 28
    if not np.any(fg):
        return out
    lab = srgb_to_oklab(out[:, :, :3].astype(np.float32) / 255.0)
    p92_l = float(np.percentile(lab[fg, 0], 92))
    if p92_l < 0.70:
        lift = min(0.70 - p92_l, 0.12) * 0.65
        lab[fg, 0] = np.clip(lab[fg, 0] + lift * (1.0 - lab[fg, 0]), 0.0, 0.99)
    for ch, neutral in ((1, 0.028), (2, 0.048)):
        delta = float(np.median(lab[fg, ch])) - neutral
        if abs(delta) > 0.032:
            lab[fg, ch] -= delta * 0.28
    out[:, :, :3] = np.clip(np.round(oklab_to_srgb(lab, preserve_hue_gamut=True) * 255.0), 0.0, 255.0).astype(np.uint8)
    return out


def _place_layer(im: Image.Image, scale: float, offset_x: float, offset_y: float, mode: Literal["RGBA", "L"]) -> np.ndarray:
    scale = float(np.clip(scale, 0.08, 4.0))
    if mode == "RGBA":
        return resample_linear_subpixel_rgba(
            im,
            zoom=scale,
            pan_x=float(offset_x),
            pan_y=float(offset_y),
            fit_mode="raw",
            dst_size=(DF11_WIDTH, DF11_HEIGHT),
        )
    im_l = im if im.mode == "L" else im.convert("L")
    if im_l.width < 1 or im_l.height < 1:
        return np.zeros((DF11_HEIGHT, DF11_WIDTH), dtype=np.uint8)
    ox = float(offset_x)
    oy = float(offset_y)
    if (
        im_l.size == (DF11_WIDTH, DF11_HEIGHT)
        and abs(scale - 1.0) < 1e-4
        and abs(ox) < 1e-3
        and abs(oy) < 1e-3
    ):
        return np.asarray(im_l, dtype=np.uint8).copy()
    disp_w = im_l.width * scale
    disp_h = im_l.height * scale
    x0 = (DF11_WIDTH - disp_w) * 0.5 + ox
    y0 = (DF11_HEIGHT - disp_h) * 0.5 + oy
    inv_s = 1.0 / scale
    transformed = im_l.transform(
        (DF11_WIDTH, DF11_HEIGHT),
        Image.Transform.AFFINE,
        (inv_s, 0.0, -x0 * inv_s, 0.0, inv_s, -y0 * inv_s),
        resample=Image.Resampling.BILINEAR,
        fillcolor=0,
    )
    return np.asarray(transformed, dtype=np.uint8)


def _measure_cylindrical_neck_waist(
    z3_head: np.ndarray,
    placed_skin: np.ndarray,
    placed_body_skin: np.ndarray,
    chin_canvas_y: float,
    cx_head: float,
    ipd_c: float,
) -> tuple[float, float]:
    """Measure the true vertical sternocleidomastoid neck waist in [chin_y - 0.52*ipd, chin_y - 0.06*ipd] (ignoring trapezius)."""
    ipd_eff = float(np.clip(ipd_c, 32.0, 56.0))
    y_scan0 = max(60, int(round(chin_canvas_y - 0.52 * ipd_eff)))
    y_scan1 = min(DF11_HEIGHT - 1, max(y_scan0 + 4, int(round(chin_canvas_y - 0.06 * ipd_eff))))

    alpha = z3_head[:, :, 3]
    skin_u8 = np.maximum(placed_skin, placed_body_skin)
    valid = (alpha > 150) & (skin_u8 > 90)

    r_lefts: list[float] = []
    r_rights: list[float] = []
    for y in range(y_scan0, y_scan1 + 1):
        xs = np.where(valid[y])[0]
        if len(xs) < 12:
            xs = np.where(alpha[y] > 165)[0]
        if len(xs) >= 12:
            xl = float(np.percentile(xs, 3))
            xr = float(np.percentile(xs, 97))
            rl = cx_head - xl
            rr = xr - cx_head
            if rl >= 14.0 and rr >= 14.0:
                r_lefts.append(rl)
                r_rights.append(rr)

    lo_r = 0.78 * ipd_eff
    hi_r = 0.96 * ipd_eff
    if len(r_lefts) >= 3:
        r_l0 = float(np.clip(np.percentile(r_lefts, 25), lo_r, hi_r))
        r_r0 = float(np.clip(np.percentile(r_rights, 25), lo_r, hi_r))
        # Balance slight pose asymmetry so neck cylinder stays anatomically harmonious
        r_mean = 0.5 * (r_l0 + r_r0)
        r_l0 = float(np.clip(0.65 * r_l0 + 0.35 * r_mean, lo_r, hi_r))
        r_r0 = float(np.clip(0.65 * r_r0 + 0.35 * r_mean, lo_r, hi_r))
    else:
        r_l0 = r_r0 = 0.88 * ipd_eff
    return r_l0, r_r0


def _scale_neck_radii(r_l0: float, r_r0: float, neck_fill: float) -> tuple[float, float]:
    f_neck = float(np.clip(neck_fill, 0.0, 1.5)) if math.isfinite(float(neck_fill)) else 1.0
    if f_neck <= 1.0:
        scale_f = 0.58 + 0.42 * f_neck
    else:
        ov = (f_neck - 1.0) / 0.5
        scale_f = 1.0 + 0.22 * ov
    return r_l0 * scale_f, r_r0 * scale_f


def _build_collar_funnel_mask(
    collar: CollarProfile,
    shirt_alpha: np.ndarray,
    chin_canvas_y: float,
    placed_occ: np.ndarray,
    neck_fill: float = 1.0,
    cx_head: float | None = None,
    r_l0: float | None = None,
    r_r0: float | None = None,
    ipd_c: float = 43.0,
) -> np.ndarray:
    """Keep full head/ears above jaw; trim native z3 trapezius wings to a vertical cylinder above collar.y_top_curve[x]."""
    x_l, y_l = collar.left_rim
    x_r, y_r = collar.right_rim
    _, y_v = collar.apex
    cx_col = 0.5 * (x_l + x_r)
    cx_h = float(cx_head) if cx_head is not None else cx_col
    ipd_eff = float(np.clip(ipd_c, 32.0, 56.0))
    rl_base = float(r_l0) if r_l0 is not None else 0.88 * ipd_eff
    rr_base = float(r_r0) if r_r0 is not None else 0.88 * ipd_eff
    r_l, r_r = _scale_neck_radii(rl_base, rr_base, neck_fill)

    yy, xx = np.mgrid[0:DF11_HEIGHT, 0:DF11_WIDTH].astype(np.float32)

    # 1. Smoothly narrow from full canvas width above gonion (chin_y - 36) to the true cylindrical neck waist at (chin_y - 12)
    y_jaw_top = chin_canvas_y - 36.0
    y_neck_start = chin_canvas_y - 12.0
    u_jaw = np.clip((yy - y_jaw_top) / max(y_neck_start - y_jaw_top, 6.0), 0.0, 1.0)
    h_jaw = u_jaw * u_jaw * (3.0 - 2.0 * u_jaw)

    # Smooth centerline alignment from head center (cx_h) at chin down to collar center (cx_col) at apex
    t_axis = np.clip((yy - y_neck_start) / max(float(y_v) - y_neck_start, 10.0), 0.0, 1.0)
    cx_y = (1.0 - t_axis) * cx_h + t_axis * cx_col

    # Above y_neck_start, allow head/ears width up to 1.25 * ipd (not 140px which let bat-wings at x=48..72 escape!)
    head_ear_half_w = max(56.0, ipd_eff * 1.28)
    cyl_left_x = cx_y - ((1.0 - h_jaw) * head_ear_half_w + h_jaw * r_l)
    cyl_right_x = cx_y + ((1.0 - h_jaw) * head_ear_half_w + h_jaw * r_r)
    # Above y_jaw_top (ears/hair/cheeks), keep full canvas width
    cyl_left_x = np.where(yy < y_jaw_top, 0.0, cyl_left_x)
    cyl_right_x = np.where(yy < y_jaw_top, float(DF11_WIDTH), cyl_right_x)

    # 2. Column-exact shirt ceiling curve y_shirt(x)
    y_curve_arr = np.asarray(collar.y_top_curve, dtype=np.float32)
    if y_curve_arr.shape[0] != DF11_WIDTH:
        y_curve_arr = np.full(DF11_WIDTH, float(min(y_l, y_r)), dtype=np.float32)
    y_shirt_x = y_curve_arr[None, :]

    # Inside wide collars (where cylinder is narrower than [x_l, x_r]), allow low clavicular base strictly below collar rim
    y_clav_l = float(y_l - 1) + 0.62 * np.maximum(0.0, (cx_y - r_l) - xx)
    y_clav_r = float(y_r - 1) + 0.62 * np.maximum(0.0, xx - (cx_y + r_r))
    in_clav_pocket = (
        (yy >= y_neck_start)
        & (xx >= float(x_l - 1))
        & (xx <= float(x_r + 1))
        & (
            ((xx < cyl_left_x) & (yy >= y_clav_l))
            | ((xx > cyl_right_x) & (yy >= y_clav_r))
        )
    )

    in_cylinder = (xx >= cyl_left_x) & (xx <= cyl_right_x)
    # Below y_neck_start and above the opaque shirt fabric, strictly forbid neck/trapezius outside [x_l - 1, x_r + 1]
    in_collar_x_window = (yy < y_neck_start) | ((xx >= float(x_l - 1)) & (xx <= float(x_r + 1)))

    # Behind opaque shirt fabric (shirt_alpha > 190), allow a +4px socket plug so the collar seam is 100% sealed
    behind_opaque_shirt = (
        (yy >= y_shirt_x - 1.0)
        & (yy <= float(y_v + 16))
        & (shirt_alpha > 190)
        & (xx >= np.minimum(cyl_left_x, float(x_l)) - 4.0)
        & (xx <= np.maximum(cyl_right_x, float(x_r)) + 4.0)
    )

    raw_keep = ((in_cylinder | in_clav_pocket) & in_collar_x_window & (yy <= float(y_v + 18))) | behind_opaque_shirt
    mask_im = Image.fromarray((raw_keep.astype(np.uint8) * 255), mode="L").filter(ImageFilter.GaussianBlur(1.35))
    funnel = np.asarray(mask_im, dtype=np.float32) / 255.0

    # Non-truncated hair/glasses occluders (placed_occ) can extend outside jaw width down to collar rim
    y_rim = float(min(y_l, y_r))
    hair_grace = (placed_occ.astype(np.float32) / 255.0) * np.clip(((y_rim + 16.0) - yy) / 8.0, 0.0, 1.0)
    funnel = np.maximum(funnel, hair_grace)

    # Hard physical barrier: above the shirt's column top y_shirt(x) (or outside opaque shirt below y_neck_start),
    # never allow non-hair skin to protrude outside the collar opening or cylinder
    exposed_air_trapezius = (
        (yy >= y_neck_start)
        & (~raw_keep)
        & (shirt_alpha < 210)
        & (placed_occ < 96)
    ).astype(np.uint8) * 255
    air_soft = np.asarray(Image.fromarray(exposed_air_trapezius, mode="L").filter(ImageFilter.GaussianBlur(1.2)), dtype=np.float32) / 255.0
    funnel = funnel * (1.0 - air_soft)
    funnel = np.where((funnel < 0.03) & (placed_occ < 64), 0.0, funnel)
    return funnel


def _build_directional_neck_bridge(
    z3_head: np.ndarray,
    placed_skin: np.ndarray,
    placed_body_skin: np.ndarray,
    skin_oklab: tuple[float, float, float],
    collar: CollarProfile,
    shirt_alpha: np.ndarray,
    chin_canvas_y: float,
    neck_fill: float,
    cx_head: float | None = None,
    r_l0: float | None = None,
    r_r0: float | None = None,
    ipd_c: float = 43.0,
) -> tuple[np.ndarray, np.ndarray]:
    """Synthesize seam-free columnar OKLab cylindrical neck bridge without trapezius flaring above collar."""
    bridge = np.zeros((DF11_HEIGHT, DF11_WIDTH, 4), dtype=np.uint8)
    z3_soft = z3_head.copy()
    f_neck = float(np.clip(neck_fill, 0.0, 1.5)) if math.isfinite(float(neck_fill)) else 1.0
    if f_neck <= 0.005:
        return bridge, z3_soft

    x_l, y_l = collar.left_rim
    x_r, y_r = collar.right_rim
    _, y_v = collar.apex
    y_rim = min(y_l, y_r)
    cx_col = 0.5 * (x_l + x_r)
    cx_h = float(cx_head) if cx_head is not None else cx_col
    w_col = float(max(x_r - x_l, 40))

    if r_l0 is None or r_r0 is None:
        r_l0, r_r0 = _measure_cylindrical_neck_waist(
            z3_head, placed_skin, placed_body_skin, chin_canvas_y, cx_h, ipd_c
        )
    r_l, r_r = _scale_neck_radii(float(r_l0), float(r_r0), f_neck)

    fg_ys_center = np.where(z3_head[:, max(0, int(cx_h) - 18) : min(DF11_WIDTH, int(cx_h) + 19), 3] > 180)[0]
    fg_bot_y = int(fg_ys_center.max()) if len(fg_ys_center) else int(round(chin_canvas_y))

    y_top = max(128, min(int(round(chin_canvas_y - 10.0)), y_rim - 8, fg_bot_y - 16))
    y_bot = min(DF11_HEIGHT - 18, int(round(y_v + 8.0 + 8.0 * min(f_neck, 1.5))))
    if y_bot <= y_top + 2:
        return bridge, z3_soft

    l0, a0, b0 = skin_oklab
    head_lab = srgb_to_oklab(z3_head[:, :, :3].astype(np.float32) / 255.0)
    valid_skin = (placed_skin > 135) & (z3_head[:, :, 3] > 190)

    col_l = np.full(DF11_WIDTH, max(0.18, l0 - 0.035), dtype=np.float32)
    col_a = np.full(DF11_WIDTH, a0, dtype=np.float32)
    col_b = np.full(DF11_WIDTH, b0, dtype=np.float32)
    col_has = np.zeros(DF11_WIDTH, dtype=bool)
    y_cut_col = np.full(DF11_WIDTH, fg_bot_y, dtype=np.int32)

    scan_x0 = max(0, int(min(x_l, cx_h - r_l)) - 16)
    scan_x1 = min(DF11_WIDTH, int(max(x_r, cx_h + r_r)) + 17)
    for x in range(scan_x0, scan_x1):
        ys_opaque = np.where(z3_head[:, x, 3] > 180)[0]
        if len(ys_opaque):
            y_cut_col[x] = int(ys_opaque[-1])
        ys_face = np.where(valid_skin[: min(DF11_HEIGHT, y_v), x])[0]
        if len(ys_face) >= 4:
            col_l[x] = float(np.clip(np.median(head_lab[ys_face, x, 0]) - 0.032, l0 - 0.24, l0 + 0.12))
            col_has[x] = True
        ys_neck = np.where((placed_body_skin[:, x] > 125) & (z3_head[:, x, 3] > 205))[0]
        if len(ys_neck) >= 3:
            tail = ys_neck[-min(6, len(ys_neck)) :]
            col_l[x] = 0.15 * col_l[x] + 0.85 * float(np.median(head_lab[tail, x, 0]))
            col_a[x] = 0.25 * a0 + 0.75 * float(np.median(head_lab[tail, x, 1]))
            col_b[x] = 0.25 * b0 + 0.75 * float(np.median(head_lab[tail, x, 2]))
            col_has[x] = True

    if np.any(col_has):
        valid_xs = np.where(col_has)[0]
        all_xs = np.arange(DF11_WIDTH, dtype=np.float32)
        col_l = np.interp(all_xs, valid_xs.astype(np.float32), col_l[valid_xs]).astype(np.float32)
        col_a = np.interp(all_xs, valid_xs.astype(np.float32), col_a[valid_xs]).astype(np.float32)
        col_b = np.interp(all_xs, valid_xs.astype(np.float32), col_b[valid_xs]).astype(np.float32)

    gx = np.exp(-0.5 * (np.arange(-15, 16, dtype=np.float32) / 6.0) ** 2)
    gx /= gx.sum()
    col_l = np.convolve(np.pad(col_l, 15, mode="edge"), gx, mode="valid")
    col_a = np.convolve(np.pad(col_a, 15, mode="edge"), gx, mode="valid")
    col_b = np.convolve(np.pad(col_b, 15, mode="edge"), gx, mode="valid")

    yy, xx = np.mgrid[0:DF11_HEIGHT, 0:DF11_WIDTH].astype(np.float32)
    t_axis = np.clip((yy - float(y_top)) / max(float(y_v - y_top), 8.0), 0.0, 1.0)
    cx_y = (1.0 - t_axis) * cx_h + t_axis * cx_col

    # Pure vertical cylinder [cx(y) - r_L, cx(y) + r_R] clamped to collar inner bounds [x_l, x_r] above shirt fabric
    cyl_l = np.maximum(cx_y - r_l, float(x_l))
    cyl_r = np.minimum(cx_y + r_r, float(x_r))

    y_curve_arr = np.asarray(collar.y_top_curve, dtype=np.float32)
    if y_curve_arr.shape[0] != DF11_WIDTH:
        y_curve_arr = np.full(DF11_WIDTH, float(y_rim), dtype=np.float32)
    y_shirt_x = y_curve_arr[None, :]

    # Clavicular floor strictly inside wide collars (only near the collar base, never lifting trapezius on head raise!)
    y_clav_l = float(y_l - 1) + 0.62 * np.maximum(0.0, cyl_l - xx)
    y_clav_r = float(y_r - 1) + 0.62 * np.maximum(0.0, xx - cyl_r)
    in_clav_pocket = (
        (yy >= float(y_top))
        & (yy <= float(y_bot))
        & (xx >= float(x_l))
        & (xx <= float(x_r))
        & (
            ((xx < cyl_l) & (yy >= y_clav_l))
            | ((xx > cyl_r) & (yy >= y_clav_r))
        )
    )

    in_cyl_band = (yy >= float(y_top)) & (yy <= float(y_bot)) & (xx >= cyl_l) & (xx <= cyl_r)
    in_visible_neck = (in_cyl_band | in_clav_pocket) & ((yy <= y_shirt_x + 2.0) | (shirt_alpha < 245))

    # Hidden socket plug behind opaque shirt fabric (+4px margin so zero gaps ever appear along the collar rim)
    socket_plug = (
        (yy >= y_shirt_x - 1.0)
        & (yy <= float(y_v + 12))
        & (shirt_alpha > 190)
        & (xx >= np.minimum(cyl_l, float(x_l)) - 4.0)
        & (xx <= np.maximum(cyl_r, float(x_r)) + 4.0)
    )

    raw_mask = in_visible_neck | socket_plug
    mask_im = Image.fromarray((raw_mask.astype(np.uint8) * 255), mode="L").filter(ImageFilter.GaussianBlur(1.35))
    alpha_f = np.asarray(mask_im, dtype=np.float32) / 255.0
    alpha_f = np.where(socket_plug, 1.0, alpha_f)

    if f_neck < 0.16:
        alpha_f *= float(np.clip(f_neck / 0.16, 0.20, 1.0))

    # Strictly forbid any bridge pixels outside [x_l, x_r] or outside the cylinder above y_shirt(x) where shirt is transparent
    forbid_air = (shirt_alpha < 210) & (
        (xx < float(x_l))
        | (xx > float(x_r))
        | ((xx < cyl_l - 0.5) & (yy < y_clav_l))
        | ((xx > cyl_r + 0.5) & (yy < y_clav_r))
    )
    alpha_f = np.where(forbid_air, 0.0, alpha_f)

    # Cross-dissolve flat horizontal bottom cut of Z3 over opaque Z2 (curving +4.5px up on sides for natural beard/chin arc)
    eff_w = np.maximum(cyl_r - cyl_l, 28.0)
    arc_lift = 4.5 * np.clip(((xx - cx_y) / (0.48 * eff_w)) ** 2, 0.0, 1.2)
    y_end_grid = y_cut_col[None, :].astype(np.float32) - arc_lift
    needs_dissolve = (y_cut_col[None, :] < (y_v + 4)) & (alpha_f > 0.96) & (yy >= float(chin_canvas_y - 10.0))
    fade_z3 = np.clip((y_end_grid - yy) / 8.5, 0.0, 1.0)
    z3_a_f = z3_soft[:, :, 3].astype(np.float32) / 255.0
    z3_a_new = np.where(needs_dissolve, z3_a_f * fade_z3, z3_a_f)
    z3_soft[:, :, 3] = np.clip(np.round(z3_a_new * 255.0), 0.0, 255.0).astype(np.uint8)
    z3_soft[:, :, :3] = np.where(z3_soft[:, :, 3:4] > 0, z3_soft[:, :, :3], 0)

    half_span = np.maximum(0.5 * (cyl_r - cyl_l), 14.0)
    subchin_shadow = -0.036 * np.exp(-np.maximum(0.0, yy - chin_canvas_y) / 11.0)
    cyl_shadow = -0.022 * np.clip(((xx - cx_y) / half_span) ** 2, 0.0, 1.2)
    rng = np.random.default_rng(1711)
    grain = rng.normal(0.0, 0.0028, size=(DF11_HEIGHT, DF11_WIDTH)).astype(np.float32)

    lab = np.zeros((DF11_HEIGHT, DF11_WIDTH, 3), dtype=np.float32)
    lab[:, :, 0] = np.clip(col_l[None, :] + subchin_shadow + cyl_shadow + grain, 0.14, 0.96)
    lab[:, :, 1] = col_a[None, :]
    lab[:, :, 2] = col_b[None, :]

    rgb = np.clip(np.round(oklab_to_srgb(lab) * 255.0), 0.0, 255.0).astype(np.uint8)
    a_u8 = np.clip(np.round(alpha_f * 255.0), 0.0, 255.0).astype(np.uint8)
    bridge[:, :, :3] = np.where(a_u8[:, :, None] > 0, rgb, 0)
    bridge[:, :, 3] = a_u8
    return bridge, z3_soft


def compose_modular_subject_rgba(
    head_asset: HeadNeckAsset | None,
    shirt_rgba: Image.Image | None,
    collar: CollarProfile | None,
    fit: HeadFitParams | None = None,
    enhance_quality: float = 0.0,
) -> Image.Image:
    """Build frame-free, Alpha=0 background 260x310 subject RGBA (Z1..Z5 + optional WGIF pure-optics)."""
    if head_asset is None and shirt_rgba is None:
        return Image.new("RGBA", (DF11_WIDTH, DF11_HEIGHT), (0, 0, 0, 0))

    f = fit or HeadFitParams()
    layer2 = np.zeros((DF11_HEIGHT, DF11_WIDTH, 4), dtype=np.uint8)

    shirt_arr = (
        np.asarray(shirt_rgba.convert("RGBA").resize((DF11_WIDTH, DF11_HEIGHT), Image.Resampling.LANCZOS), dtype=np.uint8)
        if shirt_rgba is not None
        else None
    )

    if head_asset is not None:
        z3 = _place_layer(head_asset.rgba, f.scale, f.offset_x, f.offset_y, "RGBA")
        if f.harmonize:
            z3 = _harmonize_melanin_safe(z3)
        placed_skin = _place_layer(head_asset.skin_mask, f.scale, f.offset_x, f.offset_y, "L")
        placed_body = _place_layer(head_asset.body_skin_mask, f.scale, f.offset_x, f.offset_y, "L")
        placed_occ = _place_layer(head_asset.front_occluder_alpha, f.scale, f.offset_x, f.offset_y, "L")

        disp_w = head_asset.rgba.width * f.scale
        disp_h = head_asset.rgba.height * f.scale
        x0_placed = (DF11_WIDTH - disp_w) * 0.5 + f.offset_x
        y0_placed = (DF11_HEIGHT - disp_h) * 0.5 + f.offset_y
        chin_canvas_y = y0_placed + head_asset.chin_y * f.scale
        if head_asset.pose is not None:
            cx_head = x0_placed + (head_asset.pose.eye_center[0] + head_asset.pose.yaw * 0.10 * head_asset.pose.ipd) * f.scale
            ipd_c = float(head_asset.pose.ipd * f.scale)
        else:
            cx_head = DF11_WIDTH * 0.5 + f.offset_x
            ipd_c = 43.0

        if shirt_arr is not None and collar is not None:
            y_rim = min(collar.left_rim[1], collar.right_rim[1])
            r_l0, r_r0 = _measure_cylindrical_neck_waist(
                z3, placed_skin, placed_body, chin_canvas_y, cx_head, ipd_c
            )
            funnel = _build_collar_funnel_mask(
                collar,
                shirt_arr[:, :, 3],
                chin_canvas_y,
                placed_occ,
                neck_fill=f.neck_fill,
                cx_head=cx_head,
                r_l0=r_l0,
                r_r0=r_r0,
                ipd_c=ipd_c,
            )
            z3[:, :, 3] = np.clip(np.round(z3[:, :, 3].astype(np.float32) * funnel), 0.0, 255.0).astype(np.uint8)
            z3[:, :, :3] = np.where(z3[:, :, 3:4] > 0, z3[:, :, :3], 0)

            # Z1: Dark inner-collar fabric backing strictly inside lower collar V-socket (never above shirt rim!)
            z1 = np.zeros((DF11_HEIGHT, DF11_WIDTH, 4), dtype=np.uint8)
            x_l, x_r = collar.left_rim[0], collar.right_rim[0]
            _, y_v = collar.apex
            yy, xx = np.mgrid[0:DF11_HEIGHT, 0:DF11_WIDTH]
            back_sock = (yy >= y_rim + 12) & (yy <= y_v + 6) & (xx >= x_l + 6) & (xx <= x_r - 6)
            z1[back_sock] = (18, 20, 26, 255)

            # Z2: Directional Columnar OKLab NeckBridge + Z3 bottom-cut cross-dissolve
            z2, z3_dissolved = _build_directional_neck_bridge(
                z3_head=z3,
                placed_skin=placed_skin,
                placed_body_skin=placed_body,
                skin_oklab=head_asset.skin_oklab,
                collar=collar,
                shirt_alpha=shirt_arr[:, :, 3],
                chin_canvas_y=chin_canvas_y,
                neck_fill=f.neck_fill,
                cx_head=cx_head,
                r_l0=r_l0,
                r_r0=r_r0,
                ipd_c=ipd_c,
            )

            under_shirt = premul_over(premul_over(z1, z2), z3_dissolved)

            # 2.2px Collar-rim Ambient Occlusion on neck right where shirt collar rests on skin
            shirt_blur = np.asarray(
                Image.fromarray(shirt_arr[:, :, 3], mode="L").filter(ImageFilter.GaussianBlur(2.2)),
                dtype=np.float32,
            ) / 255.0
            in_collar_zone = ((yy >= y_rim - 4) & (yy <= y_v + 6) & (xx >= x_l - 6) & (xx <= x_r + 6)).astype(np.float32)
            ao_factor = 1.0 - 0.14 * shirt_blur * in_collar_zone
            under_shirt[:, :, :3] = np.clip(np.round(under_shirt[:, :, :3].astype(np.float32) * ao_factor[:, :, None]), 0.0, 255.0).astype(np.uint8)

            # Z4: Clean Shirt Template
            with_shirt = premul_over(under_shirt, shirt_arr)

            # Z5: Non-truncated Hair / Glasses occluders in front of collar rim (5px smooth ramp)
            z5 = z3.copy()
            yy_f = yy.astype(np.float32)
            occ_gate = np.clip((yy_f - (float(y_rim) - 10.0)) / 5.0, 0.0, 1.0) * np.clip(((float(y_v) + 12.0) - yy_f) / 5.0, 0.0, 1.0)
            raw_z5_a = np.clip(
                np.round((placed_occ.astype(np.float32) / 255.0) * funnel * occ_gate * 255.0),
                0.0,
                255.0,
            ).astype(np.uint8)
            z5[:, :, 3] = np.minimum(raw_z5_a, z3[:, :, 3])
            z5[:, :, :3] = np.where(z5[:, :, 3:4] > 0, z5[:, :, :3], 0)
            layer2 = premul_over(with_shirt, z5)
        else:
            layer2 = z3
    elif shirt_arr is not None:
        layer2 = shirt_arr

    if float(enhance_quality) > 1e-3:
        layer2 = enhance_df11_pure_optics(layer2, amount=float(enhance_quality), upscale_hint=max(1.0, float(f.scale)))
    return Image.fromarray(layer2, mode="RGBA")


def compose_modular_df11(
    head_asset: HeadNeckAsset | None,
    shirt_rgba: Image.Image | None,
    collar: CollarProfile | None,
    fit: HeadFitParams | None = None,
    bg_mode: BgMode = "white_df11",
    bg_custom_rgba: Image.Image | None = None,
    bg_blur: float = 0.0,
    enhance_quality: float = 0.0,
) -> Image.Image:
    """Fuse Z0(Bg) + Z1(BackCollar) + Z2(NeckBridge) + Z3(Head) + Z4(Shirt) + Z5(HairOccluders) + Z6(DF11Frame)."""
    if head_asset is None and shirt_rgba is None:
        return render_df11_card(None, bg_mode=bg_mode, bg_custom_rgba=bg_custom_rgba, bg_blur=bg_blur)

    subject_im = compose_modular_subject_rgba(
        head_asset=head_asset,
        shirt_rgba=shirt_rgba,
        collar=collar,
        fit=fit,
        enhance_quality=enhance_quality,
    )
    return render_df11_card(
        portrait_rgba=subject_im,
        portrait_offset=(0.0, 0.0),
        portrait_scale=1.0,
        bg_mode=bg_mode,
        bg_custom_rgba=bg_custom_rgba,
        bg_blur=bg_blur,
        enhance_quality=0.0,
    )


def list_face_library_files(
    extracted_dir: Path | None = None,
    sample_dir: Path | None = None,
) -> list[tuple[str, str, Path, str]]:
    """Return [(face_id, display_name, path, source_kind)] from caras_extraidas and caras_prueba."""
    ext_folder = (extracted_dir or get_extracted_faces_dir()).resolve()
    smp_folder = (sample_dir or get_caras_prueba_dir()).resolve()
    items: list[tuple[str, str, Path, str]] = []
    if ext_folder.is_dir():
        for p in sorted(ext_folder.iterdir()):
            if p.is_file() and not p.name.startswith(".") and p.suffix.lower() in IMAGE_EXTS:
                items.append((f"ext:{p.name}", p.stem, p, "extraida"))
    if smp_folder.is_dir():
        for p in sorted(smp_folder.iterdir()):
            if p.is_file() and not p.name.startswith(".") and p.suffix.lower() in IMAGE_EXTS:
                items.append((f"smp:{p.name}", p.stem, p, "prueba"))
    return items


def save_clean_face_to_library(
    clean_head_rgba: Image.Image,
    name: str,
    extracted_dir: Path | None = None,
) -> tuple[str, str, Path]:
    """Atomically save a clean extracted Head+Neck PNG into caras_extraidas."""
    from backend.services.templates import slugify_template_id

    folder = (extracted_dir or get_extracted_faces_dir()).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    slug = slugify_template_id(name, fallback="Cara_Extraida")
    dst = folder / f"{slug}.png"
    buf = io.BytesIO()
    clean_head_rgba.convert("RGBA").save(buf, format="PNG", compress_level=6)
    fd, tname = tempfile.mkstemp(prefix=f".{slug}_", suffix=".tmp", dir=str(folder))
    tp = Path(tname)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(buf.getvalue())
        safe_ntfs_replace(tp, dst)
    finally:
        tp.unlink(missing_ok=True)
    return (f"ext:{dst.name}", slug, dst)
