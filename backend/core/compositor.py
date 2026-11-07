"""Lossless DF11 3-layer premultiplied compositor (260x310 RGBA / RGB)."""

from __future__ import annotations

import io
from functools import lru_cache
from typing import Literal

import numpy as np
from PIL import Image, ImageFilter, ImageOps

from backend.core.dsp import (
    FitMode,
    clean_pure_contour_zero_ai,
    compute_effective_scale,
    enhance_df11_pure_optics,
    resample_linear_subpixel_rgba,
)
from backend.core.paths import ASSETS_DIR

DF11_WIDTH = 260
DF11_HEIGHT = 310
INNER_X0, INNER_Y0, INNER_X1, INNER_Y1 = 19, 17, 242, 293  # 223x276 incl. AA edge
CROWN_Y, EYES_Y, SHOULDERS_Y = 24, 112, 292

DF11_PURE_WIDTH = 220
DF11_PURE_HEIGHT = 276
PURE_CROP_X0, PURE_CROP_Y0, PURE_CROP_X1, PURE_CROP_Y1 = 20, 17, 240, 293
PURE_CROP_BOX = (PURE_CROP_X0, PURE_CROP_Y0, PURE_CROP_X1, PURE_CROP_Y1)
PURE_EDGE_FEATHER_RATIO = 220.0 / 255.0

CardVariant = Literal["classic", "pure", "dual"]
SingleCardVariant = Literal["classic", "pure"]

BgMode = Literal[
    "transparent",
    "white_df11",
    "pearl_studio",
    "stadium_bokeh",
    "tunnel_club",
    "office_staff",
    "custom",
]


@lru_cache(maxsize=1)
def load_df11_assets() -> tuple[Image.Image, Image.Image]:
    """Load cached lossless DF11 inner window mask (L) and symmetric frame overlay (RGBA)."""
    frames_dir = ASSETS_DIR / "frames"
    mask = Image.open(frames_dir / "df11_inner_mask.png").convert("L")
    overlay = Image.open(frames_dir / "df11_frame_overlay.png").convert("RGBA")
    mask.load()
    overlay.load()
    return mask, overlay


def premul_over(bottom: np.ndarray, top: np.ndarray) -> np.ndarray:
    """Porter-Duff source-over in float32 premultiplied RGBA space (zero dark halos)."""
    b = bottom.astype(np.float32) / 255.0
    t = top.astype(np.float32) / 255.0
    ba, ta = b[:, :, 3:4], t[:, :, 3:4]
    out_a = ta + ba * (1.0 - ta)
    out_rgb_pre = t[:, :, :3] * ta + b[:, :, :3] * ba * (1.0 - ta)
    safe_a = np.where(out_a > 1e-6, out_a, 1.0)
    out_rgb = np.where(out_a > 1e-6, out_rgb_pre / safe_a, 0.0)
    out = np.concatenate([out_rgb, out_a], axis=2)
    return np.clip(np.round(out * 255.0), 0, 255).astype(np.uint8)


@lru_cache(maxsize=8)
def _build_preset_bg(mode: str) -> np.ndarray:
    yy, xx = np.mgrid[0:DF11_HEIGHT, 0:DF11_WIDTH].astype(np.float32)
    nx = (xx - 130.0) / 130.0
    ny = (yy - 135.0) / 155.0
    r2 = np.clip(nx * nx + ny * ny, 0.0, 1.6)
    out = np.zeros((DF11_HEIGHT, DF11_WIDTH, 4), dtype=np.uint8)
    if mode == "transparent":
        return out
    if mode == "white_df11":
        v_grad = 255.0 - 0.115 * np.clip(yy - 30.0, 0.0, 262.0)
        dx = np.minimum(np.maximum(xx - 19.0, 0.0), np.maximum(241.0 - xx, 0.0))
        dy = np.minimum(np.maximum(yy - 17.0, 0.0), np.maximum(292.0 - yy, 0.0))
        sx = np.clip(1.0 - dx / 28.0, 0.0, 1.0) ** 2
        sy = np.clip(1.0 - dy / 26.0, 0.0, 1.0) ** 2
        s_edge = sx + sy - sx * sy
        lum = np.clip(v_grad - 17.5 * s_edge, 206.0, 255.0)
        rgb = np.stack([lum, lum, lum], axis=2)
    elif mode == "pearl_studio":
        rgb = np.stack([245.0 - 18.0 * r2, 247.0 - 16.0 * r2, 251.0 - 12.0 * r2], axis=2)
    elif mode == "stadium_bokeh":
        pitch = np.clip((yy - 190.0) / 120.0, 0.0, 1.0)
        sky = 1.0 - pitch
        flare = np.exp(-(((xx - 65.0) / 48.0) ** 2 + ((yy - 68.0) / 42.0) ** 2))
        flare2 = np.exp(-(((xx - 200.0) / 45.0) ** 2 + ((yy - 74.0) / 40.0) ** 2))
        glow = 75.0 * (flare + flare2)
        rgb = np.stack(
            [22.0 * sky + 28.0 * pitch + glow, 34.0 * sky + 76.0 * pitch + glow, 58.0 * sky + 42.0 * pitch + glow * 0.9],
            axis=2,
        )
    elif mode == "tunnel_club":
        beam = np.exp(-((nx * 1.4) ** 2 + ((yy - 60.0) / 160.0) ** 2))
        rgb = np.stack([26.0 + 44.0 * beam, 33.0 + 52.0 * beam, 48.0 + 68.0 * beam], axis=2)
    else:  # office_staff
        warm = 1.0 - 0.35 * r2
        rgb = np.stack([68.0 * warm + 18.0, 56.0 * warm + 16.0, 48.0 * warm + 16.0], axis=2)
    out[:, :, :3] = np.clip(np.round(rgb), 0, 255).astype(np.uint8)
    out[:, :, 3] = 255
    return out


def _prepare_layer1(bg_mode: BgMode, bg_custom_rgba: Image.Image | None, bg_blur: float) -> np.ndarray:
    if bg_mode == "custom" and bg_custom_rgba is not None:
        fitted = ImageOps.fit(bg_custom_rgba.convert("RGBA"), (DF11_WIDTH, DF11_HEIGHT), Image.Resampling.LANCZOS)
        if bg_blur > 0.05:
            fitted = fitted.filter(ImageFilter.GaussianBlur(radius=min(float(bg_blur), 24.0)))
        return np.asarray(fitted, dtype=np.uint8)
    arr = _build_preset_bg(bg_mode if bg_mode != "custom" else "white_df11")
    if bg_blur > 0.05 and bg_mode != "transparent":
        blurred = Image.fromarray(arr, mode="RGBA").filter(ImageFilter.GaussianBlur(radius=min(float(bg_blur), 24.0)))
        return np.asarray(blurred, dtype=np.uint8)
    return arr.copy()


def _place_portrait(
    portrait: Image.Image,
    offset: tuple[float, float],
    scale: float,
    fit_mode: FitMode = "raw",
    clamp_to_inner: bool = False,
) -> np.ndarray:
    return resample_linear_subpixel_rgba(
        portrait,
        zoom=float(scale),
        pan_x=float(offset[0]),
        pan_y=float(offset[1]),
        fit_mode=fit_mode,
        clamp_to_inner=clamp_to_inner,
        dst_size=(DF11_WIDTH, DF11_HEIGHT),
    )


def render_df11_card(
    portrait_rgba: Image.Image | None,
    portrait_offset: tuple[float, float] = (0.0, 0.0),
    portrait_scale: float = 1.0,
    bg_mode: BgMode = "white_df11",
    bg_custom_rgba: Image.Image | None = None,
    bg_blur: float = 0.0,
    enhance_quality: float = 0.0,
    fit_mode: FitMode = "raw",
    clamp_to_inner: bool = False,
    upscale_hint: float | None = None,
) -> Image.Image:
    """Composite Layer 1 + Layer 2, apply optional pure-optics WGIF, clip inner mask, and top with DF11 frame."""
    inner_mask_img, overlay_img = load_df11_assets()
    layer1 = _prepare_layer1(bg_mode, bg_custom_rgba, bg_blur)
    if portrait_rgba is None:
        combined = layer1
    else:
        placed = _place_portrait(
            portrait_rgba,
            portrait_offset,
            portrait_scale,
            fit_mode=fit_mode,
            clamp_to_inner=clamp_to_inner,
        )
        combined = premul_over(layer1, placed)
        if float(enhance_quality) > 1e-3:
            eff_s = (
                float(upscale_hint)
                if upscale_hint is not None
                else compute_effective_scale(portrait_rgba.width, portrait_rgba.height, portrait_scale, fit_mode)
            )
            combined = enhance_df11_pure_optics(combined, amount=float(enhance_quality), upscale_hint=max(1.0, eff_s))

    # Destination-in clip BEFORE frame overlay so the punched ring stays strictly Alpha == 0
    mask_f = np.asarray(inner_mask_img, dtype=np.float32)[:, :, None] / 255.0
    clipped = combined.copy()
    clipped_a = np.round(clipped[:, :, 3:4].astype(np.float32) * mask_f).astype(np.uint8)
    clipped[:, :, 3:4] = clipped_a
    clipped[:, :, :3] = np.where(clipped_a > 0, clipped[:, :, :3], 0)

    final_arr = premul_over(clipped, np.asarray(overlay_img, dtype=np.uint8))
    return Image.fromarray(final_arr, mode="RGBA")


def is_df11_pure_size(size: tuple[int, int]) -> bool:
    """Return True if dimensions match official DF11 Pure (220x276 px)."""
    return size == (DF11_PURE_WIDTH, DF11_PURE_HEIGHT)


def has_df11_outer_ring(im_rgba: Image.Image) -> bool:
    """Return True if image is a 260x310 DF11 Classic card with transparent outer margin and frame AA ring."""
    if im_rgba.size != (DF11_WIDTH, DF11_HEIGHT):
        return False
    a = np.asarray(im_rgba if im_rgba.mode == "RGBA" else im_rgba.convert("RGBA"), dtype=np.uint8)[:, :, 3]
    if int(a[0, :].max()) > 0 or int(a[-1, :].max()) > 0 or int(a[:, 0].max()) > 0 or int(a[:, -1].max()) > 0:
        return False
    return (
        0 < int(a[:, 2:18].max()) <= 125
        and 0 < int(a[:, 243:258].max()) <= 125
        and int(a[180:285, 30:230].max()) > 240
    )


@lru_cache(maxsize=1)
def _df11_win_dead_ring_lookup() -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Precompute nearest valid interior pixel indices for outer mask<8 dead ring inside [16:294, 18:242]."""
    mask_im, _ov_im = load_df11_assets()
    m_win = np.asarray(mask_im, dtype=np.uint8)[16:294, 18:242]
    dead = m_win < 8
    valid = m_win >= 245
    eroded = np.zeros_like(valid)
    eroded[1:-1, 1:-1] = (
        valid[1:-1, 1:-1] & valid[:-2, 1:-1] & valid[2:, 1:-1] & valid[1:-1, :-2] & valid[1:-1, 2:]
    )
    boundary = valid & (~eroded)
    by, bx = np.nonzero(boundary)
    dy, dx = np.nonzero(dead)
    d2 = (dy[:, None] - by[None, :]) ** 2 + (dx[:, None] - bx[None, :]) ** 2
    nearest = np.argmin(d2, axis=1)
    return dy, dx, by[nearest], bx[nearest]


def unmix_df11_classic_bevel_rgba(card_260x310: Image.Image) -> tuple[Image.Image, bool]:
    """Invert df11_frame_overlay + df11_inner_mask inside [16:294, 18:242] (224x278) in premultiplied RGBA space.

    - Leaves clear_win (a_ov == 0 and m == 255) 100% bit-exact (diff == 0).
    - Recovers true un-darkened RGB under the 3D frame bevel shadow (max error <= 1/255).
    - Strips the ghost bevel ring from transparent Classic cards so Pure exports stay strictly Alpha == 0.
    """
    rgba = card_260x310 if card_260x310.mode == "RGBA" else card_260x310.convert("RGBA")
    crop_arr = np.asarray(rgba.crop((18, 16, 242, 294)), dtype=np.uint8).copy()
    if not has_df11_outer_ring(rgba):
        is_pre = bool(float(np.mean(crop_arr[18:276, 20:222, 3] < 250)) >= 0.02)
        return Image.fromarray(crop_arr, mode="RGBA"), is_pre

    mask_im, ov_im = load_df11_assets()
    m_win = np.asarray(mask_im, dtype=np.uint8)[16:294, 18:242]
    ov_win = np.asarray(ov_im, dtype=np.uint8)[16:294, 18:242]

    a_card = crop_arr[:, :, 3:4].astype(np.float32) * np.float32(1.0 / 255.0)
    a_ov = ov_win[:, :, 3:4].astype(np.float32) * np.float32(1.0 / 255.0)
    m_f = m_win[:, :, None].astype(np.float32) * np.float32(1.0 / 255.0)

    # Unmix strictly where m >= 8 and frame overlay actually modified pixels (a_ov > 0 or m < 255)
    needs_unmix = (m_win >= 8) & ((ov_win[:, :, 3] > 0) | (m_win < 255))
    if np.any(needs_unmix):
        c_card = crop_arr[:, :, :3].astype(np.float32)
        c_ov = ov_win[:, :, :3].astype(np.float32)
        diff_a = a_card - a_ov
        a_orig = np.where(
            a_card >= np.float32(0.995),
            np.float32(1.0),
            np.clip(diff_a / np.maximum(m_f * (np.float32(1.0) - a_ov), np.float32(0.03)), 0.0, 1.0),
        )
        # Zero out ghost frame bevel pixels where underlying card was empty transparent
        a_orig = np.where(a_orig < np.float32(0.025), np.float32(0.0), a_orig)
        c_clean = np.clip(
            (c_card * a_card - c_ov * a_ov) / np.maximum(diff_a, np.float32(0.03)),
            0.0,
            255.0,
        )
        c_clean = np.where(a_orig > 0.0, c_clean, 0.0)

        crop_arr[:, :, :3] = np.where(
            needs_unmix[:, :, None],
            np.round(c_clean).astype(np.uint8),
            crop_arr[:, :, :3],
        )
        crop_arr[:, :, 3:4] = np.where(
            needs_unmix[:, :, None],
            np.round(a_orig * 255.0).astype(np.uint8),
            crop_arr[:, :, 3:4],
        )

    interior_a = crop_arr[18:276, 20:222, 3]
    is_precut = bool(float(np.mean(interior_a < 250)) >= 0.02)
    if not is_precut:
        dy, dx, ny, nx = _df11_win_dead_ring_lookup()
        crop_arr[dy, dx, :3] = crop_arr[ny, nx, :3]
        crop_arr[:, :, 3] = 255
    else:
        dead = m_win < 8
        crop_arr[dead] = 0
    return Image.fromarray(crop_arr, mode="RGBA"), is_precut


@lru_cache(maxsize=1)
def _build_pure_perimeter_feather() -> np.ndarray:
    """Symmetric 1px perimeter alpha feather matching shipped DF11 Pure FM27 megapacks (~220/255 edges, ~190/255 corners)."""
    f = np.ones((DF11_PURE_HEIGHT, DF11_PURE_WIDTH), dtype=np.float32)
    r = np.float32(PURE_EDGE_FEATHER_RATIO)
    f[:, 0] *= r
    f[:, -1] *= r
    f[0, :] *= r
    f[-1, :] *= r
    return f


def unfeather_pure_perimeter_rgba(pure_rgba: Image.Image) -> Image.Image:
    """Idempotently invert the 1px Pure perimeter feather on opaque sleeves/bottom when re-importing a 220x276 Pure card."""
    im = pure_rgba if pure_rgba.mode == "RGBA" else pure_rgba.convert("RGBA")
    if im.size != (DF11_PURE_WIDTH, DF11_PURE_HEIGHT):
        return im
    arr = np.asarray(im, dtype=np.uint8).copy()
    f = _build_pure_perimeter_feather()
    edge = f < 0.999
    a_f = arr[:, :, 3].astype(np.float32)
    # Restore full 255 opacity where pixel matches a feathered opaque silhouette (e.g. >= 200*f)
    restored = np.where(edge & (a_f >= 205.0 * f), np.clip(np.round(a_f / np.maximum(f, 0.5)), 0.0, 255.0), a_f)
    arr[:, :, 3] = restored.astype(np.uint8)
    return Image.fromarray(arr, mode="RGBA")


def pad_pure_to_df11_canvas(pure_rgba: Image.Image, unfeather_edges: bool = False) -> Image.Image:
    """Place a 220x276 DF11 Pure card bit-exact at (20, 17) inside a 260x310 stage (zero scale distortion)."""
    im = unfeather_pure_perimeter_rgba(pure_rgba) if unfeather_edges else pure_rgba.convert("RGBA")
    if im.size != (DF11_PURE_WIDTH, DF11_PURE_HEIGHT):
        return im
    stage = Image.new("RGBA", (DF11_WIDTH, DF11_HEIGHT), (0, 0, 0, 0))
    stage.paste(im, (PURE_CROP_X0, PURE_CROP_Y0))
    # Extend outer sleeve columns into x=19 and x=240..241 when unfeathering for Classic inner window [19..241]
    if unfeather_edges:
        st_arr = np.asarray(stage, dtype=np.uint8).copy()
        left_sleeve = st_arr[PURE_CROP_Y0:PURE_CROP_Y1, PURE_CROP_X0, 3] >= 245
        if np.any(left_sleeve):
            st_arr[PURE_CROP_Y0:PURE_CROP_Y1, PURE_CROP_X0 - 1][left_sleeve] = st_arr[
                PURE_CROP_Y0:PURE_CROP_Y1, PURE_CROP_X0
            ][left_sleeve]
        right_sleeve = st_arr[PURE_CROP_Y0:PURE_CROP_Y1, PURE_CROP_X1 - 1, 3] >= 245
        if np.any(right_sleeve):
            right_px = st_arr[PURE_CROP_Y0:PURE_CROP_Y1, PURE_CROP_X1 - 1][right_sleeve]
            st_arr[PURE_CROP_Y0:PURE_CROP_Y1, PURE_CROP_X1][right_sleeve] = right_px
            st_arr[PURE_CROP_Y0:PURE_CROP_Y1, PURE_CROP_X1 + 1][right_sleeve] = right_px
        return Image.fromarray(st_arr, mode="RGBA")
    return stage


def _heal_pure_bottom_corners(crop_arr: np.ndarray) -> np.ndarray:
    """Heal 6x6 bottom-corner bites and bevel darkening in legacy tshirt_templates using per-column vertical medians."""
    out = crop_arr
    # Bottom-left corner triangle (275 - y) + x <= 5: y in [270..275], x in [0..5]
    if float(out[261:267, 1:5, 3].mean()) > 235.0 and (int(out[275, 0, 3]) < 245 or int(out[275, 1, 3]) < 250):
        for x in range(6):
            if int(out[264, x, 3]) > 220 or int(out[264, 1, 3]) > 235:
                col_ref = np.median(out[261:267, x, :3].astype(np.float32), axis=0)
                col_ref_lum = float(col_ref.mean())
                y_start = 270 + x
                col_rgb = out[y_start:276, x, :3].astype(np.float32)
                col_a = out[y_start:276, x, 3]
                darkened = (col_a < 250) | (col_rgb.mean(axis=-1) < col_ref_lum * 0.78)
                out[y_start:276, x, :3] = np.where(
                    darkened[:, None],
                    np.round(col_ref).astype(np.uint8),
                    out[y_start:276, x, :3],
                )
                out[y_start:276, x, 3] = 255

    # Bottom-right corner triangle (275 - y) + (219 - x) <= 5: y in [270..275], x in [214..219]
    if float(out[261:267, 215:219, 3].mean()) > 235.0 and (int(out[275, 219, 3]) < 245 or int(out[275, 218, 3]) < 250):
        for x in range(214, 220):
            if int(out[264, x, 3]) > 220 or int(out[264, 218, 3]) > 235:
                col_ref = np.median(out[261:267, x, :3].astype(np.float32), axis=0)
                col_ref_lum = float(col_ref.mean())
                y_start = 270 + (219 - x)
                col_rgb = out[y_start:276, x, :3].astype(np.float32)
                col_a = out[y_start:276, x, 3]
                darkened = (col_a < 250) | (col_rgb.mean(axis=-1) < col_ref_lum * 0.78)
                out[y_start:276, x, :3] = np.where(
                    darkened[:, None],
                    np.round(col_ref).astype(np.uint8),
                    out[y_start:276, x, :3],
                )
                out[y_start:276, x, 3] = 255

    # Restore y=275 interior row from df11_inner_mask's Alpha=252 up to 255 before perimeter feathering
    mid_solid = (out[273, 6:214, 3] == 255) & (out[275, 6:214, 3] >= 230)
    if np.any(mid_solid):
        out[275, 6:214, 3] = np.where(mid_solid, 255, out[275, 6:214, 3])
    return out


def render_df11_pure_card(
    subject_260x310: Image.Image | None,
    enhance_quality: float = 0.0,
    upscale_hint: float = 1.0,
    ensure_zero_ai_alpha: bool = False,
    pure_tolerance: float = 0.5,
) -> Image.Image:
    """Render an official 220x276 RGBA DF11 Pure card (Alpha=0 background, 0% frame, 1px perimeter feather)."""
    if subject_260x310 is None:
        return Image.new("RGBA", (DF11_PURE_WIDTH, DF11_PURE_HEIGHT), (0, 0, 0, 0))
    im = subject_260x310 if subject_260x310.mode == "RGBA" else subject_260x310.convert("RGBA")
    if im.size == (DF11_PURE_WIDTH, DF11_PURE_HEIGHT):
        im = pad_pure_to_df11_canvas(im, unfeather_edges=True)
    elif im.size == (DF11_WIDTH, DF11_HEIGHT) and has_df11_outer_ring(im):
        unmixed_win, is_pre = unmix_df11_classic_bevel_rgba(im)
        stage = Image.new("RGBA", (DF11_WIDTH, DF11_HEIGHT), (0, 0, 0, 0))
        stage.paste(unmixed_win, (18, 16))
        im = stage if is_pre else clean_pure_contour_zero_ai(stage, tolerance=pure_tolerance)
    elif im.size != (DF11_WIDTH, DF11_HEIGHT):
        placed = _place_portrait(im, (0.0, 0.0), 1.0, fit_mode="contain", clamp_to_inner=False)
        im = Image.fromarray(placed, mode="RGBA")

    if ensure_zero_ai_alpha:
        im = clean_pure_contour_zero_ai(im, tolerance=pure_tolerance)

    arr_260 = np.asarray(im, dtype=np.uint8)
    if float(enhance_quality) > 1e-3:
        arr_260 = enhance_df11_pure_optics(arr_260, amount=float(enhance_quality), upscale_hint=max(1.0, float(upscale_hint)))

    crop = arr_260[PURE_CROP_Y0:PURE_CROP_Y1, PURE_CROP_X0:PURE_CROP_X1].copy()
    crop = _heal_pure_bottom_corners(crop)
    feather = _build_pure_perimeter_feather()
    feathered_a = np.clip(np.round(crop[:, :, 3].astype(np.float32) * feather), 0.0, 255.0).astype(np.uint8)
    crop[:, :, 3] = feathered_a
    crop[:, :, :3] = np.where(feathered_a[:, :, None] > 0, crop[:, :, :3], 0)
    return Image.fromarray(crop, mode="RGBA")


def export_df11_bytes(card_rgba: Image.Image, fmt: Literal["png", "jpg"] = "png", compress_level: int = 6) -> bytes:
    """Encode a 260x310 Classic or 220x276 Pure DF11 card as official 72-DPI RGBA PNG (or 4:4:4 JPEG for Classic)."""
    rgba = card_rgba.convert("RGBA")
    w, h = rgba.size
    if (w, h) not in ((DF11_WIDTH, DF11_HEIGHT), (DF11_PURE_WIDTH, DF11_PURE_HEIGHT)):
        raise ValueError(f"Dimensiones DF11 no válidas para exportación: {w}x{h} (esperado 260x310 o 220x276).")
    fmt_low = fmt.lower()
    if (w, h) == (DF11_PURE_WIDTH, DF11_PURE_HEIGHT) and fmt_low != "png":
        raise ValueError("El formato oficial DF11 Pure (220×276, fondo transparente Alpha = 0) exige exportación en PNG.")
    buf = io.BytesIO()
    if fmt_low == "png":
        rgba.save(buf, format="PNG", compress_level=compress_level, dpi=(72, 72))
    elif fmt_low in ("jpg", "jpeg"):
        white = np.full((h, w, 4), 255, dtype=np.uint8)
        flat = premul_over(white, np.asarray(rgba, dtype=np.uint8))[:, :, :3]
        Image.fromarray(flat, mode="RGB").save(buf, format="JPEG", quality=95, subsampling=0, dpi=(72, 72))
    else:
        raise ValueError(f"Formato de exportación no soportado: {fmt}")
    return buf.getvalue()
