"""100% Offline, Zero-AI Pure-Optics DSP Engine (Linear Subpixel Resampling, WGIF OKLab & 8x8 Deblocking).

Strictly independent of onnxruntime or neural models: relies exclusively on deterministic NumPy + Pillow math.
"""

from __future__ import annotations

import math
from typing import Literal

import numpy as np
from PIL import Image

DF11_W = 260
DF11_H = 310
INNER_WIN_X0, INNER_WIN_Y0, INNER_WIN_X1, INNER_WIN_Y1 = 18.0, 16.0, 242.0, 294.0
INNER_WIN_W = INNER_WIN_X1 - INNER_WIN_X0  # 224.0
INNER_WIN_H = INNER_WIN_Y1 - INNER_WIN_Y0  # 278.0

FitMode = Literal["raw", "contain", "cover"]


def _init_srgb_luts() -> tuple[np.ndarray, np.ndarray]:
    v = np.arange(256, dtype=np.float32) / 255.0
    s2l = np.where(v <= 0.04045, v / 12.92, ((v + 0.055) / 1.055) ** 2.4).astype(np.float32)
    u = np.linspace(0.0, 1.0, 8192, dtype=np.float32)
    l2s = np.where(u <= 0.0031308, 12.92 * u, 1.055 * np.power(np.maximum(u, 0.0), 1.0 / 2.4) - 0.055)
    l2s_u8 = np.clip(np.round(l2s * 255.0), 0.0, 255.0).astype(np.uint8)
    return s2l, l2s_u8


_SRGB_TO_LIN_LUT, _LIN_TO_SRGB_LUT = _init_srgb_luts()

_OKLAB_M1_T = np.array(
    [
        [0.4122214708, 0.5363325363, 0.0514459929],
        [0.2119034982, 0.6806995451, 0.1073969566],
        [0.0883024619, 0.2817188376, 0.6299787005],
    ],
    dtype=np.float32,
).T

_OKLAB_M2_T = np.array(
    [
        [0.2104542553, 0.7936177850, -0.0040720468],
        [1.9779984951, -2.4285922050, 0.4505937099],
        [0.0259040371, 0.7827717662, -0.8086757660],
    ],
    dtype=np.float32,
).T


def fast_srgb_u8_to_oklab(rgb_u8: np.ndarray) -> np.ndarray:
    """LUT + CBRT conversion from uint8 sRGB [0..255] to float32 OKLab (L, a, b) (~4x faster than float power)."""
    lin = _SRGB_TO_LIN_LUT[rgb_u8]
    lms = lin @ _OKLAB_M1_T
    lms_cbrt = np.cbrt(np.maximum(lms, np.float32(0.0)))
    return (lms_cbrt @ _OKLAB_M2_T).astype(np.float32)


def srgb_u8_to_linear(rgb_u8: np.ndarray) -> np.ndarray:
    """Fast LUT conversion from uint8 sRGB [0..255] to float32 linear light [0..1]."""
    return _SRGB_TO_LIN_LUT[rgb_u8]


def linear_to_srgb_u8(lin_01: np.ndarray) -> np.ndarray:
    """Fast 8192-entry LUT conversion from float32 linear light [0..1] to uint8 sRGB [0..255]."""
    idx = np.clip(np.round(lin_01 * 8191.0), 0.0, 8191.0).astype(np.int32)
    return _LIN_TO_SRGB_LUT[idx]


def srgb_to_oklab(rgb_01: np.ndarray) -> np.ndarray:
    """Vectorized sRGB [0..1] -> Björn Ottosson OKLab (L, a, b)."""
    c = np.clip(rgb_01.astype(np.float32, copy=False), 0.0, 1.0)
    lin = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    r, g, b = lin[..., 0], lin[..., 1], lin[..., 2]
    l_ = np.cbrt(np.maximum(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b, 0.0))
    m_ = np.cbrt(np.maximum(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b, 0.0))
    s_ = np.cbrt(np.maximum(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b, 0.0))
    return np.stack(
        [
            0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_,
            1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_,
            0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_,
        ],
        axis=-1,
    ).astype(np.float32)


def oklab_to_srgb(lab: np.ndarray, preserve_hue_gamut: bool = False) -> np.ndarray:
    """Vectorized Björn Ottosson OKLab -> sRGB [0..1], with optional hue-preserving radial gamut clip."""
    L, a, b = lab[..., 0], lab[..., 1], lab[..., 2]
    l_ = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3
    m_ = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3
    s_ = (L - 0.0894841775 * a - 1.2914855480 * b) ** 3
    r = +4.0767416621 * l_ - 3.3077115913 * m_ + 0.2309699292 * s_
    g = -1.2684380046 * l_ + 2.6097574011 * m_ - 0.3413193965 * s_
    bl = -0.0041960863 * l_ - 0.7034186147 * m_ + 1.7076147010 * s_
    lin = np.stack([r, g, bl], axis=-1).astype(np.float32)
    if preserve_hue_gamut:
        y0 = np.clip(L, 0.0, 1.0)[..., None] ** 3
        y_safe = np.clip(y0, 1e-4, 1.0 - 1e-4)
        d = lin - y_safe
        pos_lim = np.where(d > 1e-6, (1.0 - y_safe) / np.maximum(d, 1e-6), 1.0)
        neg_lim = np.where(d < -1e-6, y_safe / np.maximum(-d, 1e-6), 1.0)
        scale = np.minimum(1.0, np.minimum(pos_lim.min(axis=-1, keepdims=True), neg_lim.min(axis=-1, keepdims=True)))
        lin = np.clip(y_safe + d * scale, 0.0, 1.0)
    else:
        lin = np.clip(lin, 0.0, 1.0)
    return np.where(lin <= 0.0031308, 12.92 * lin, 1.055 * (np.maximum(lin, 0.0) ** (1.0 / 2.4)) - 0.055).astype(np.float32)


def compute_oklab_harmonize_params(
    img_rgba: Image.Image,
    max_side: int = 320,
) -> tuple[float, float, float]:
    """Compute (lift_l, shift_a, shift_b) OKLab exposure & cast adjustments once (in < 2ms when max_side=320)."""
    im = img_rgba if img_rgba.mode == "RGBA" else img_rgba.convert("RGBA")
    w, h = im.size
    if w < 1 or h < 1:
        return (0.0, 0.0, 0.0)
    if max_side > 0 and max(w, h) > max_side:
        s = max_side / float(max(w, h))
        im = im.resize((max(1, round(w * s)), max(1, round(h * s))), Image.Resampling.NEAREST)
    arr = np.asarray(im, dtype=np.uint8)
    fg = arr[:, :, 3] > 24
    if not np.any(fg):
        return (0.0, 0.0, 0.0)
    lab = fast_srgb_u8_to_oklab(arr[:, :, :3])
    lift_l = 0.0
    shift_a = 0.0
    shift_b = 0.0
    if np.all(fg):
        # Full-scene opaque photo/capture: sample central portrait oval excluding extreme white/dark/saturated bg
        hh, ww = lab.shape[:2]
        yy_h, xx_h = np.mgrid[0:hh, 0:ww].astype(np.float32)
        roi_oval = (
            ((xx_h - ww * 0.50) / max(ww * 0.28, 1.0)) ** 2
            + ((yy_h - hh * 0.46) / max(hh * 0.36, 1.0)) ** 2
        ) <= 1.0
        ch_h = np.hypot(lab[:, :, 1], lab[:, :, 2])
        plausible_subj = roi_oval & (lab[:, :, 0] > 0.12) & (lab[:, :, 0] < 0.95) & (ch_h < 0.13)
        sample = lab[plausible_subj] if int(plausible_subj.sum()) >= 32 else lab[roi_oval]
        p92_l = float(np.percentile(sample[:, 0], 92))
        if p92_l < 0.70:
            lift_l = min(0.70 - p92_l, 0.12) * 0.60
        med_a = float(np.median(sample[:, 1]))
        if abs(med_a) > 0.055:
            shift_a = -(med_a - math.copysign(0.055, med_a)) * 0.25
        med_b = float(np.median(sample[:, 2]))
        if abs(med_b) > 0.085:
            shift_b = -(med_b - math.copysign(0.085, med_b)) * 0.25
    else:
        med_l = float(np.median(lab[fg, 0]))
        if med_l < 0.62:
            lift_l = min(0.62 - med_l, 0.14) * 0.75
        delta_a = float(np.median(lab[fg, 1])) - 0.025
        if abs(delta_a) > 0.025:
            shift_a = -delta_a * 0.35
        delta_b = float(np.median(lab[fg, 2])) - 0.045
        if abs(delta_b) > 0.025:
            shift_b = -delta_b * 0.35
    return (float(lift_l), float(shift_a), float(shift_b))


def apply_oklab_harmonize_params(
    img_rgba: Image.Image,
    params: tuple[float, float, float],
) -> Image.Image:
    """Apply precomputed (lift_l, shift_a, shift_b) OKLab adjustments to an RGBA layer (e.g. 260x310)."""
    lift_l, shift_a, shift_b = params
    if abs(lift_l) <= 1e-6 and abs(shift_a) <= 1e-6 and abs(shift_b) <= 1e-6:
        return img_rgba if img_rgba.mode == "RGBA" else img_rgba.convert("RGBA")
    arr = np.asarray(img_rgba if img_rgba.mode == "RGBA" else img_rgba.convert("RGBA"), dtype=np.uint8).copy()
    fg = arr[:, :, 3] > 0
    if not np.any(fg):
        return Image.fromarray(arr, mode="RGBA")
    lab = fast_srgb_u8_to_oklab(arr[:, :, :3])
    if np.all(fg):
        if lift_l > 1e-6:
            lab[:, :, 0] = np.clip(lab[:, :, 0] + lift_l * (1.0 - lab[:, :, 0]), 0.0, 0.99)
        if abs(shift_a) > 1e-6:
            lab[:, :, 1] += shift_a
        if abs(shift_b) > 1e-6:
            lab[:, :, 2] += shift_b
    else:
        if lift_l > 1e-6:
            lab[fg, 0] = np.clip(lab[fg, 0] + lift_l * (1.0 - lab[fg, 0]), 0.0, 0.99)
        if abs(shift_a) > 1e-6:
            lab[fg, 1] += shift_a
        if abs(shift_b) > 1e-6:
            lab[fg, 2] += shift_b
    arr[:, :, :3] = np.clip(np.round(oklab_to_srgb(lab, preserve_hue_gamut=True) * 255.0), 0, 255).astype(np.uint8)
    arr[:, :, :3] = np.where(arr[:, :, 3:4] > 0, arr[:, :, :3], 0)
    return Image.fromarray(arr, mode="RGBA")


def harmonize_oklab_pure_optics(img_rgba: Image.Image) -> Image.Image:
    """Zero-AI exposure lift and indoor cast normalization in OKLab space."""
    params = compute_oklab_harmonize_params(img_rgba, max_side=0)
    return apply_oklab_harmonize_params(img_rgba, params)


def deblock_jpeg_8x8_roi(
    rgb_f32: np.ndarray,
    grid_offset_x: int = 0,
    grid_offset_y: int = 0,
) -> np.ndarray:
    """Detect and gently smooth 8x8 DCT quantization seams before upscaling low-res JPEGs."""
    h, w = rgb_f32.shape[:2]
    if h < 16 or w < 16:
        return rgb_f32

    first_sx = (8 - (grid_offset_x % 8)) % 8
    if first_sx == 0:
        first_sx = 8
    first_ix = (first_sx + 4) if (first_sx + 4 < w) else max(1, first_sx - 4)

    first_sy = (8 - (grid_offset_y % 8)) % 8
    if first_sy == 0:
        first_sy = 8
    first_iy = (first_sy + 4) if (first_sy + 4 < h) else max(1, first_sy - 4)

    sx_cols = np.arange(first_sx, w, 8)
    ix_cols = np.arange(first_ix, w, 8)
    sy_rows = np.arange(first_sy, h, 8)
    iy_rows = np.arange(first_iy, h, 8)
    if len(sx_cols) == 0 or len(sy_rows) == 0:
        return rgb_f32

    seam_x = float(np.abs(rgb_f32[:, sx_cols, :] - rgb_f32[:, sx_cols - 1, :]).mean())
    int_x = float(np.abs(rgb_f32[:, ix_cols, :] - rgb_f32[:, ix_cols - 1, :]).mean()) if len(ix_cols) else seam_x
    seam_y = float(np.abs(rgb_f32[sy_rows, :, :] - rgb_f32[sy_rows - 1, :, :]).mean())
    int_y = float(np.abs(rgb_f32[iy_rows, :, :] - rgb_f32[iy_rows - 1, :, :]).mean()) if len(iy_rows) else seam_y

    blockiness = (seam_x + seam_y) / max(int_x + int_y, 0.75)
    if blockiness <= 1.18:
        return rgb_f32

    out = rgb_f32.copy()
    q_step = min(30.0, max(6.0, 2.25 * max(seam_x, seam_y)))
    strength = min(0.42, (blockiness - 1.18) * 0.50)

    dx = out[:, sx_cols, :] - out[:, sx_cols - 1, :]
    gx = np.clip(1.0 - np.abs(dx) / q_step, 0.0, 1.0) * strength
    adj_x = gx * dx
    out[:, sx_cols - 1, :] += adj_x
    out[:, sx_cols, :] -= adj_x

    dy = out[sy_rows, :, :] - out[sy_rows - 1, :, :]
    gy = np.clip(1.0 - np.abs(dy) / q_step, 0.0, 1.0) * strength
    adj_y = gy * dy
    out[sy_rows - 1, :, :] += adj_y
    out[sy_rows, :, :] -= adj_y
    return np.clip(out, 0.0, 255.0)


def compute_effective_scale(sw: int, sh: int, zoom: float, fit_mode: FitMode) -> float:
    z = max(0.08, min(float(zoom), 8.0))
    if fit_mode == "raw":
        return z
    if fit_mode == "cover":
        return max(INNER_WIN_W / max(sw, 1), INNER_WIN_H / max(sh, 1)) * z
    return min(INNER_WIN_W / max(sw, 1), INNER_WIN_H / max(sh, 1)) * z


def clamp_direct_pan(
    sw: int,
    sh: int,
    zoom: float,
    pan_x: float,
    pan_y: float,
    fit_mode: FitMode = "cover",
) -> tuple[float, float]:
    eff = compute_effective_scale(sw, sh, zoom, fit_mode)
    disp_w = sw * eff
    disp_h = sh * eff
    lim_x = abs(disp_w - INNER_WIN_W) * 0.5
    lim_y = abs(disp_h - INNER_WIN_H) * 0.5
    return float(np.clip(pan_x, -lim_x, lim_x)), float(np.clip(pan_y, -lim_y, lim_y))


def resample_linear_subpixel_rgba(
    src_rgba: Image.Image,
    zoom: float = 1.0,
    pan_x: float = 0.0,
    pan_y: float = 0.0,
    fit_mode: FitMode = "contain",
    clamp_to_inner: bool = False,
    dst_size: tuple[int, int] = (DF11_W, DF11_H),
) -> np.ndarray:
    """O(1) ROI linear-light premultiplied subpixel resampler (zero gamma darkening, zero O(zoom^2) blowup)."""
    rgba_im = src_rgba if src_rgba.mode == "RGBA" else src_rgba.convert("RGBA")
    sw, sh = rgba_im.size
    dw_tot, dh_tot = dst_size
    if sw < 1 or sh < 1:
        return np.zeros((dh_tot, dw_tot, 4), dtype=np.uint8)

    px, py = float(pan_x), float(pan_y)
    if clamp_to_inner and (dw_tot, dh_tot) == (DF11_W, DF11_H):
        px, py = clamp_direct_pan(sw, sh, zoom, px, py, fit_mode=fit_mode)

    eff_scale = compute_effective_scale(sw, sh, zoom, fit_mode)
    disp_w = sw * eff_scale
    disp_h = sh * eff_scale
    x0 = (dw_tot - disp_w) * 0.5 + px
    y0 = (dh_tot - disp_h) * 0.5 + py

    rx0 = round(x0)
    ry0 = round(y0)
    if (
        abs(eff_scale - 1.0) < 1e-4
        and abs(x0 - rx0) < 1e-3
        and abs(y0 - ry0) < 1e-3
    ):
        if (sw, sh) == (dw_tot, dh_tot) and rx0 == 0 and ry0 == 0:
            return np.asarray(rgba_im, dtype=np.uint8).copy()
        canvas = np.zeros((dh_tot, dw_tot, 4), dtype=np.uint8)
        cx0 = max(0, rx0)
        cy0 = max(0, ry0)
        cx1 = min(dw_tot, rx0 + sw)
        cy1 = min(dh_tot, ry0 + sh)
        if cx1 > cx0 and cy1 > cy0:
            src_arr = np.asarray(rgba_im, dtype=np.uint8)
            sub = src_arr[cy0 - ry0 : cy1 - ry0, cx0 - rx0 : cx1 - rx0]
            canvas[cy0:cy1, cx0:cx1, :3] = np.where(sub[:, :, 3:4] > 0, sub[:, :, :3], 0)
            canvas[cy0:cy1, cx0:cx1, 3] = sub[:, :, 3]
        return canvas

    dx0 = max(0, int(math.floor(x0)))
    dy0 = max(0, int(math.floor(y0)))
    dx1 = min(dw_tot, int(math.ceil(x0 + disp_w)))
    dy1 = min(dh_tot, int(math.ceil(y0 + disp_h)))

    canvas = np.zeros((dh_tot, dw_tot, 4), dtype=np.uint8)
    if dx1 <= dx0 or dy1 <= dy0:
        return canvas

    sx0 = (dx0 - x0) / eff_scale
    sy0 = (dy0 - y0) / eff_scale
    sx1 = (dx1 - x0) / eff_scale
    sy1 = (dy1 - y0) / eff_scale

    margin = max(4, int(math.ceil(3.0 / min(eff_scale, 1.0))))
    ix0 = max(0, int(math.floor(sx0)) - margin)
    iy0 = max(0, int(math.floor(sy0)) - margin)
    ix1 = min(sw, int(math.ceil(sx1)) + margin)
    iy1 = min(sh, int(math.ceil(sy1)) + margin)
    if ix1 <= ix0 or iy1 <= iy0:
        return canvas

    out_size = (dx1 - dx0, dy1 - dy0)
    rw = ix1 - ix0
    rh = iy1 - iy0
    if eff_scale < 0.28 and rw * rh > 650_000:
        pre_w = min(rw, max(out_size[0] * 2, round(rw * eff_scale * 2.2)))
        pre_h = min(rh, max(out_size[1] * 2, round(rh * eff_scale * 2.2)))
        roi_u8 = np.asarray(
            rgba_im.resize((pre_w, pre_h), Image.Resampling.BOX, box=(ix0, iy0, ix1, iy1)),
            dtype=np.uint8,
        )
        rx_scale = pre_w / float(rw)
        ry_scale = pre_h / float(rh)
    else:
        roi_u8 = np.asarray(rgba_im.crop((ix0, iy0, ix1, iy1)), dtype=np.uint8)
        pre_w, pre_h = rw, rh
        rx_scale = 1.0
        ry_scale = 1.0

    roi_a = roi_u8[:, :, 3].astype(np.float32) / 255.0

    if eff_scale > 1.20:
        rgb_deb = deblock_jpeg_8x8_roi(
            roi_u8[:, :, :3].astype(np.float32),
            grid_offset_x=ix0,
            grid_offset_y=iy0,
        )
        c01 = rgb_deb / 255.0
        roi_lin = np.where(c01 <= 0.04045, c01 / 12.92, ((c01 + 0.055) / 1.055) ** 2.4).astype(np.float32)
    else:
        roi_lin = srgb_u8_to_linear(roi_u8[:, :, :3])

    premul_roi = roi_lin * roi_a[:, :, None]

    rel_sx0 = (sx0 - ix0) * rx_scale
    rel_sy0 = (sy0 - iy0) * ry_scale
    rel_sx1 = (sx1 - ix0) * rx_scale
    rel_sy1 = (sy1 - iy0) * ry_scale

    pad_l = max(0, int(math.ceil(-rel_sx0)) + 2)
    pad_t = max(0, int(math.ceil(-rel_sy0)) + 2)
    pad_r = max(0, int(math.ceil(rel_sx1 - pre_w)) + 2)
    pad_b = max(0, int(math.ceil(rel_sy1 - pre_h)) + 2)

    if pad_l or pad_t or pad_r or pad_b:
        premul_roi = np.pad(premul_roi, ((pad_t, pad_b), (pad_l, pad_r), (0, 0)), mode="constant", constant_values=0.0)
        roi_a = np.pad(roi_a, ((pad_t, pad_b), (pad_l, pad_r)), mode="constant", constant_values=0.0)

    bx0 = rel_sx0 + pad_l
    by0 = rel_sy0 + pad_t
    bx1 = rel_sx1 + pad_l
    by1 = rel_sy1 + pad_t
    box = (float(bx0), float(by0), float(bx1), float(by1))

    kernel = Image.Resampling.LANCZOS if eff_scale <= 1.02 else Image.Resampling.BICUBIC

    out_a = np.asarray(Image.fromarray(roi_a, mode="F").resize(out_size, kernel, box=box), dtype=np.float32)
    out_a = np.clip(out_a, 0.0, 1.0)
    out_lin = np.empty((dy1 - dy0, dx1 - dx0, 3), dtype=np.float32)
    for c in range(3):
        ch = np.asarray(Image.fromarray(premul_roi[:, :, c], mode="F").resize(out_size, kernel, box=box), dtype=np.float32)
        out_lin[:, :, c] = ch

    safe_a = np.maximum(out_a[:, :, None], 1e-4)
    unpremul_lin = np.where(out_a[:, :, None] > 1e-4, np.clip(out_lin / safe_a, 0.0, 1.0), 0.0)
    out_rgb_u8 = linear_to_srgb_u8(unpremul_lin)
    out_a_u8 = np.clip(np.round(out_a * 255.0), 0.0, 255.0).astype(np.uint8)
    out_rgb_u8 = np.where(out_a_u8[:, :, None] > 0, out_rgb_u8, 0)

    canvas[dy0:dy1, dx0:dx1, :3] = out_rgb_u8
    canvas[dy0:dy1, dx0:dx1, 3] = out_a_u8
    return canvas


def _box_filter_f32(src: np.ndarray, r: int) -> np.ndarray:
    """Exact O(N) float32 2D box filter with replicate boundary (zero float64 promotion)."""
    if r <= 0:
        return src
    k = 2 * r + 1
    inv_area = np.float32(1.0 / (k * k))
    pad_y = np.pad(src, ((r, r), (r, r)), mode="edge")
    cs_y = np.empty((pad_y.shape[0] + 1, pad_y.shape[1]), dtype=np.float32)
    cs_y[0] = 0.0
    np.cumsum(pad_y, axis=0, dtype=np.float32, out=cs_y[1:])
    sum_y = cs_y[k:] - cs_y[:-k]

    cs_x = np.empty((sum_y.shape[0], sum_y.shape[1] + 1), dtype=np.float32)
    cs_x[:, 0] = 0.0
    np.cumsum(sum_y, axis=1, dtype=np.float32, out=cs_x[:, 1:])
    return (cs_x[:, k:] - cs_x[:, :-k]) * inv_area


def fast_tent_f32(src: np.ndarray, r: int = 1) -> np.ndarray:
    """Isotropic O(N) float32 cascaded tent filter replacing Pillow GaussianBlur on float planes."""
    return _box_filter_f32(_box_filter_f32(src, r), r)


def _wgif_single_channel(
    guide_l: np.ndarray,
    src: np.ndarray,
    r: int,
    eps_base: float,
    edge_pivot: float = 0.055,
) -> tuple[np.ndarray, np.ndarray]:
    """Weighted Guided Image Filter (uniform window LSQ) preserving step edges with zero overshoot halo."""
    mean_i = _box_filter_f32(guide_l, r)
    var_i = np.maximum(_box_filter_f32(guide_l * guide_l, r) - mean_i * mean_i, 0.0)
    std_i = np.sqrt(var_i)

    # Edge-weighted regularization: flat/micro-texture keeps eps_base; step edges collapse eps -> 0 (a_k -> 1)
    edge_ratio = std_i / max(edge_pivot, 1e-4)
    er2 = edge_ratio * edge_ratio
    eps_k = np.float32(eps_base) / (1.0 + er2 * er2)

    if src is guide_l:
        mean_p = mean_i
        cov_ip = var_i
    else:
        mean_p = _box_filter_f32(src, r)
        cov_ip = _box_filter_f32(guide_l * src, r) - mean_i * mean_p

    a_k = cov_ip / np.maximum(var_i + eps_k, 1e-7)
    b_k = mean_p - a_k * mean_i
    mean_a = _box_filter_f32(a_k, r)
    mean_b = _box_filter_f32(b_k, r)
    return mean_a * guide_l + mean_b, mean_a


def enhance_df11_pure_optics(
    combined_rgba: np.ndarray,
    amount: float = 0.0,
    upscale_hint: float = 1.0,
) -> np.ndarray:
    """Zero-AI WGIF OKLab optical enhancer applied strictly BEFORE DF11 inner mask clip and frame overlay."""
    amt = float(np.clip(amount, 0.0, 1.0))
    if amt <= 1e-3:
        return combined_rgba

    h, w = combined_rgba.shape[:2]
    x0, y0 = max(0, min(16, w)), max(0, min(14, h))
    x1, y1 = min(w, 245), min(h, 296)
    if x1 - x0 < 8 or y1 - y0 < 8:
        return combined_rgba

    out = combined_rgba.copy()
    roi = out[y0:y1, x0:x1]
    alpha_u8 = roi[:, :, 3]
    fg = alpha_u8 > 8
    if not np.any(fg):
        return out

    rgb_u8 = roi[:, :, :3].copy()
    # Extrapolate visible foreground colors ONLY into fully transparent (alpha == 0) neighbor pixels
    # so (0,0,0,0) never darkens hair edges while preserving 100% of semi-transparent strand RGB (alpha > 0).
    if np.any(alpha_u8 == 0):
        w_fg = alpha_u8.astype(np.float32) / 255.0
        if np.any(alpha_u8 > 0):
            den = np.maximum(fast_tent_f32(w_fg, 2), 1e-4)
            for c in range(3):
                num = fast_tent_f32(rgb_u8[:, :, c].astype(np.float32) * w_fg, 2)
                extrap = np.clip(np.round(num / den), 0.0, 255.0).astype(np.uint8)
                rgb_u8[:, :, c] = np.where(alpha_u8 > 0, rgb_u8[:, :, c], extrap)

    lab = fast_srgb_u8_to_oklab(rgb_u8)
    l_ch = lab[:, :, 0]
    a_ch = lab[:, :, 1]
    b_ch = lab[:, :, 2]

    # 1. Two-band WGIF luminance decomposition (fine acutance + subtle 3D mid-tone clarity)
    base_fine, mean_a_fine = _wgif_single_channel(l_ch, l_ch, r=1, eps_base=0.0026, edge_pivot=0.062)
    base_mid, _ = _wgif_single_channel(l_ch, base_fine, r=3, eps_base=0.0055, edge_pivot=0.075)

    d_fine = l_ch - base_fine
    d_mid = base_fine - base_mid

    # 2. Melanin- & specular-adaptive soft-coring deadzone tau(L) (protects Fitz V-VI shadows & Fitz I highlights)
    tau_l = 0.0022 * (1.0 + 1.35 * ((1.0 - l_ch) ** 2) + 1.15 * np.maximum(l_ch - 0.82, 0.0) / 0.18)
    d_fine_cored = np.sign(d_fine) * np.maximum(np.abs(d_fine) - tau_l, 0.0)
    d_mid_cored = np.sign(d_mid) * np.maximum(np.abs(d_mid) - 0.0018, 0.0)

    # 3. Gentle upper-frame skin-chroma moderation (excludes saturated red/orange kits C > 0.14; never blurs < 1.0x)
    chroma = np.hypot(a_ch, b_ch)
    c_skin_max = 0.025 + 0.11 * np.sin(np.clip(l_ch, 0.05, 0.95) * np.pi)
    in_skin_chroma = (chroma <= c_skin_max) & (a_ch >= -0.01) & (b_ch >= -0.005)
    yy_roi = np.arange(y0, y1, dtype=np.float32)[:, None]
    upper_face_gate = np.clip((200.0 - yy_roi) / 30.0, 0.0, 1.0)
    skin_mod = 1.0 - 0.28 * in_skin_chroma.astype(np.float32) * upper_face_gate

    upscale_damp = 1.0 / math.sqrt(max(1.0, min(float(upscale_hint), 4.0)))
    gain_fine = 1.55 * amt * upscale_damp * skin_mod
    gain_mid = 0.34 * amt * skin_mod

    # Asymptotic tanh ceiling prevents double-sharpening on already-crisp crests or re-imported cards
    max_delta = np.float32(0.034)
    delta_l = max_delta * np.tanh((gain_fine * d_fine_cored + gain_mid * d_mid_cored) / max_delta)
    lab[:, :, 0] = np.clip(l_ch + delta_l, 0.0, 1.0)

    # 4. Guided chroma denoise on OKLab (a, b) in flat regions (cleans 4:2:0 JPEG color blotches while keeping edges)
    flat_weight = np.clip(1.0 - mean_a_fine, 0.0, 1.0) * (0.45 * amt)
    a_smooth = fast_tent_f32(a_ch, 1)
    b_smooth = fast_tent_f32(b_ch, 1)
    lab[:, :, 1] = a_ch + flat_weight * (a_smooth - a_ch)
    lab[:, :, 2] = b_ch + flat_weight * (b_smooth - b_ch)

    enh_rgb = np.clip(np.round(oklab_to_srgb(lab, preserve_hue_gamut=True) * 255.0), 0.0, 255.0).astype(np.uint8)
    roi[:, :, :3] = np.where(alpha_u8[:, :, None] > 0, enh_rgb, 0)
    return out


def is_genuinely_precut_window(a_in: np.ndarray) -> bool:
    """Evaluate against the opaque bounding box [by0:by1, bx0:bx1] so panned/zoomed-out opaque photos never false-pass."""
    sup = a_in > 16
    if not np.any(sup):
        return True
    ys, xs = np.nonzero(sup)
    by0, by1 = int(ys.min()), int(ys.max()) + 1
    bx0, bx1 = int(xs.min()), int(xs.max()) + 1
    bh, bw = by1 - by0, bx1 - bx0
    if bh < 16 or bw < 16:
        return True
    ch, cw = max(6, min(42, bh // 3)), max(5, min(18, bw // 6))
    tl_zero = float((a_in[by0 : by0 + ch, bx0 : bx0 + cw] < 16).mean())
    tr_zero = float((a_in[by0 : by0 + ch, bx1 - cw : bx1] < 16).mean())
    top_bar_opaque = float((a_in[by0 : min(by0 + 3, by1), bx0 : bx1] > 235).mean())
    upper_zero = float((a_in[by0 : by0 + max(1, bh // 2), bx0 : bx1] < 16).mean())
    return (
        top_bar_opaque < 0.62
        and upper_zero >= 0.16
        and ((tl_zero > 0.45 and tr_zero > 0.45) or (upper_zero >= 0.28 and top_bar_opaque < 0.42))
    )


def _geodesic_8dir_fast(step_cost: np.ndarray, seed_mask: np.ndarray, passes: int = 2) -> np.ndarray:
    """Loop-free O(N) 8-directional geodesic solver via cumsum + minimum.accumulate + 1D shearing (< 3 ms, GIL-friendly)."""
    sh, sw = step_cost.shape
    c = np.minimum(step_cost, np.float32(2.0))
    inf = np.float32(10.0)
    geo = np.where(seed_mask, c * np.float32(0.20), inf).astype(np.float32)

    cy = np.zeros_like(c)
    cy[1:] = np.maximum(c[:-1], c[1:])
    cs_down = np.cumsum(cy, axis=0, dtype=np.float32)
    cy_u = np.zeros_like(c)
    cy_u[1:] = cy[:0:-1]
    cs_up = np.cumsum(cy_u, axis=0, dtype=np.float32)

    cx = np.zeros_like(c)
    cx[:, 1:] = np.maximum(c[:, :-1], c[:, 1:])
    cs_right = np.cumsum(cx, axis=1, dtype=np.float32)
    cx_l = np.zeros_like(c)
    cx_l[:, 1:] = cx[:, :0:-1]
    cs_left = np.cumsum(cx_l, axis=1, dtype=np.float32)

    w_pad = sw + sh
    buf = np.full(sh * w_pad, inf, dtype=np.float32)
    sk_2d = buf.reshape(sh, w_pad)
    unsk_view = buf[sh - 1 : -1].reshape(sh, w_pad - 1)[:, :sw]

    cbuf = np.zeros(sh * w_pad, dtype=np.float32)
    c_unsk = cbuf[sh - 1 : -1].reshape(sh, w_pad - 1)[:, :sw]
    c_sk = cbuf.reshape(sh, w_pad)

    diag_k = np.float32(1.4142135)
    c_unsk[:] = 0.0
    c_unsk[1:, 1:] = diag_k * np.maximum(c[:-1, :-1], c[1:, 1:])
    cs_se = np.cumsum(c_sk, axis=0, dtype=np.float32)
    cu1 = np.zeros_like(c_sk)
    cu1[1:] = c_sk[:0:-1]
    cs_nw = np.cumsum(cu1, axis=0, dtype=np.float32)

    cf = c[:, ::-1]
    c_unsk[:] = 0.0
    c_unsk[1:, 1:] = diag_k * np.maximum(cf[:-1, :-1], cf[1:, 1:])
    cs_sw = np.cumsum(c_sk, axis=0, dtype=np.float32)
    cu2 = np.zeros_like(c_sk)
    cu2[1:] = c_sk[:0:-1]
    cs_ne = np.cumsum(cu2, axis=0, dtype=np.float32)

    for _ in range(passes):
        geo = np.minimum.accumulate(geo - cs_down, axis=0) + cs_down
        geo = (np.minimum.accumulate(geo[::-1] - cs_up, axis=0) + cs_up)[::-1]
        geo = np.minimum.accumulate(geo - cs_right, axis=1) + cs_right
        geo = (np.minimum.accumulate(geo[:, ::-1] - cs_left, axis=1) + cs_left)[:, ::-1]

        buf.fill(inf)
        unsk_view[:] = geo
        res = np.minimum.accumulate(sk_2d - cs_se, axis=0) + cs_se
        sk_2d[:] = (np.minimum.accumulate(res[::-1] - cs_nw, axis=0) + cs_nw)[::-1]
        geo = unsk_view.copy()

        buf.fill(inf)
        unsk_view[:] = geo[:, ::-1]
        res = np.minimum.accumulate(sk_2d - cs_sw, axis=0) + cs_sw
        sk_2d[:] = (np.minimum.accumulate(res[::-1] - cs_ne, axis=0) + cs_ne)[::-1]
        geo = unsk_view[:, ::-1].copy()
    return geo


def _detect_side_shoulder_row(strip_lab: np.ndarray, strip_grad: np.ndarray, strip_sup: np.ndarray, min_y: int) -> int:
    """Find the first row y >= min_y along a lateral border strip where a jersey/suit shoulder seam enters."""
    sh = strip_lab.shape[0]
    y_start = max(18, min(min_y, sh - 8))
    if y_start >= sh - 4:
        return sh - 4
    w_vec = np.array([1.0, 2.0, 2.0], dtype=np.float32)
    row_med = np.median(strip_lab, axis=1)  # (sh, 3)
    row_g = strip_grad.max(axis=1)
    valid_row = strip_sup.mean(axis=1) > 0.75
    # Compare each row against a trailing 6-row background baseline above it
    for y in range(y_start, sh - 2):
        if not valid_row[y]:
            continue
        lo = max(2, y - 8)
        hi = max(3, y - 2)
        ref_slice = row_med[lo:hi]
        if len(ref_slice) == 0:
            continue
        ref = np.median(ref_slice, axis=0)
        d_jump = float(np.sqrt((((row_med[y] - ref) * w_vec) ** 2).sum()))
        g_base = float(np.median(row_g[lo:hi]))
        if (
            (row_g[y] > 0.052 and d_jump > 0.038)
            or (row_g[y] > max(0.082, g_base * 3.5) and d_jump > 0.015)
            or d_jump > 0.095
        ):
            return max(y_start, y - 1)
    return min(sh - 4, 102)


def clean_pure_contour_zero_ai(
    framed_260x310: Image.Image,
    pan_x: float = 0.0,
    pan_y: float = 0.0,
    scale: float = 1.0,
    tolerance: float = 0.5,
    is_known_precut: bool = False,
) -> Image.Image:
    """100% Free, Offline, Deterministic Zero-AI contour cleaner for DF11 Pure (220x276) & Dual.

    Strictly uses vectorized NumPy + Pillow (0% onnxruntime / neural weights):
    1. Bounding-box-aware pre-cutout fast-path (immune to panned/zoomed-out opaque margins).
    2. LUT OKLab + dynamic shoulder-stopped 2D illumination surface (WLS dome normalized by delta-phi) + K=4 prototypes.
    3. Loop-free 8-directional geodesic propagation with Sobel, hair micro-texture, and anthropometric resistance.
    4. Edge-preserving WGIF soft alpha matting (2-3 px anti-aliased ramp).
    5. Algebraic background unmixing with bilateral luminance guard (zero 1px trim blur, zero skin bleed on dark hair).
    """
    t_arr = np.asarray(framed_260x310 if framed_260x310.mode == "RGBA" else framed_260x310.convert("RGBA"), dtype=np.uint8)
    if t_arr.shape[:2] != (DF11_H, DF11_W):
        placed = resample_linear_subpixel_rgba(framed_260x310, fit_mode="contain", clamp_to_inner=False)
        t_arr = placed

    x0, y0, x1, y1 = 18, 16, 242, 294  # 224 x 278 inner window (covers PURE_CROP_BOX 20..240, 17..293)
    win = t_arr[y0:y1, x0:x1]
    h, w = win.shape[:2]
    a_in = win[:, :, 3]

    # Evaluate pre-cutout fast-path strictly inside PURE_CROP_BOX equivalent [1:277, 2:222]
    pure_sub_a = a_in[1:277, 2:222]
    if is_known_precut or is_genuinely_precut_window(pure_sub_a):
        out_full = np.zeros_like(t_arr)
        out_full[y0:y1, x0:x1] = win
        return Image.fromarray(out_full, mode="RGBA")

    tol = float(np.clip(tolerance, 0.0, 1.0))
    sc = float(np.clip(scale, 0.55, 2.2))

    # Track opaque support so panned/zoomed-out transparent margins stay strictly Alpha == 0
    a_f_full = a_in.astype(np.float32) * np.float32(1.0 / 255.0)
    sh, sw = h // 2, w // 2  # 139 x 112
    a_s = a_f_full.reshape(sh, 2, sw, 2).mean(axis=(1, 3))
    sup_s = a_s > 0.92
    if int(sup_s.sum()) < 64:
        out_full = np.zeros_like(t_arr)
        out_full[y0:y1, x0:x1] = win
        return Image.fromarray(out_full, mode="RGBA")

    # Bounding box of opaque support on the 2x grid (handles scale < 1.0 or clampPan=False shifts!)
    sys_idx, sxs_idx = np.nonzero(sup_s)
    s_by0, s_by1 = int(sys_idx.min()), int(sys_idx.max()) + 1
    s_bx0, s_bx1 = int(sxs_idx.min()), int(sxs_idx.max()) + 1

    lab = fast_srgb_u8_to_oklab(win[:, :, :3])
    lab_s = lab.reshape(sh, 2, sw, 2, 3).mean(axis=(1, 3))

    w_vec = np.array([1.0, 2.0, 2.0], dtype=np.float32)
    pad_lab = np.pad(lab, ((1, 1), (1, 1), (0, 0)), mode="edge")
    # Zero gradients across external alpha boundaries so opaque box border itself doesn't block seeding
    gx = (pad_lab[1:-1, 2:] - pad_lab[1:-1, :-2]) * w_vec
    gy = (pad_lab[2:, 1:-1] - pad_lab[:-2, 1:-1]) * w_vec
    grad_full = np.sqrt((gx * gx + gy * gy).sum(axis=-1)) * (a_in > 220)
    grad_s = grad_full.reshape(sh, 2, sw, 2).max(axis=(1, 3))

    l_mean = _box_filter_f32(lab[:, :, 0], 1)
    l_var = np.maximum(_box_filter_f32(lab[:, :, 0] * lab[:, :, 0], 1) - l_mean * l_mean, 0.0)
    tex_s = (np.sqrt(l_var) * (a_in > 220)).reshape(sh, 2, sw, 2).mean(axis=(1, 3))

    yy_s, xx_s = np.mgrid[0:sh, 0:sw].astype(np.float32)

    # Dynamic lateral border strips anchored to the actual opaque bounding box [s_bx0:s_bx1, s_by0:s_by1]
    lx0 = min(s_bx0 + 1, sw - 6)
    lx1 = min(lx0 + 5, sw - 1)
    rx1 = max(s_bx1 - 1, 6)
    rx0 = max(rx1 - 5, 1)

    min_sh_search = max(s_by0 + 18, int(round(36.0 + pan_y * 0.5)))
    y_cut_l = _detect_side_shoulder_row(lab_s[:, lx0:lx1], grad_s[:, lx0:lx1], sup_s[:, lx0:lx1], min_sh_search)
    y_cut_r = _detect_side_shoulder_row(lab_s[:, rx0:rx1], grad_s[:, rx0:rx1], sup_s[:, rx0:rx1], min_sh_search)

    left_strip = np.median(lab_s[:, lx0:lx1, :], axis=1).copy()
    right_strip = np.median(lab_s[:, rx0:rx1, :], axis=1).copy()
    if s_by0 > 0:
        left_strip[:s_by0] = left_strip[s_by0]
        right_strip[:s_by0] = right_strip[s_by0]
    if y_cut_l < sh:
        left_strip[y_cut_l:] = left_strip[max(s_by0, y_cut_l - 1)]
    if y_cut_r < sh:
        right_strip[y_cut_r:] = right_strip[max(s_by0, y_cut_r - 1)]

    span_w = max(float(rx1 - lx0), 12.0)
    alpha_x = np.clip((xx_s - float(lx0)) / span_w, 0.0, 1.0)[:, :, None]
    b_lin_s = (1.0 - alpha_x) * left_strip[:, None, :] + alpha_x * right_strip[:, None, :]

    # Vectorized WLS radial vignette dome fit per row normalized by delta_phi (solves office_staff & tunnel_club!)
    mid_x = 0.5 * float(lx0 + rx1)
    half_w = max(0.5 * span_w, 10.0)
    phi_x = np.clip(1.0 - ((xx_s - mid_x) / half_w) ** 2, 0.0, 1.0)
    d_phi = np.maximum(phi_x - 0.06, 0.0)

    # Estimate portrait horizontal center & crown from edge/texture saliency fused with user pan/zoom
    hint_cx = float(np.clip(sw * 0.5 + pan_x * 0.5, s_bx0 + 12.0, s_bx1 - 12.0))
    sal_s = (grad_s + 1.4 * tex_s) * sup_s
    head_band = (yy_s >= s_by0 + 3) & (yy_s <= min(s_by1, s_by0 + int(68 * sc))) & (np.abs(xx_s - hint_cx) <= 38.0 * sc)
    sal_sum = float(sal_s[head_band].sum())
    if sal_sum > 0.25:
        emp_cx = float((sal_s[head_band] * xx_s[head_band]).sum() / sal_sum)
        cx_s = float(np.clip(0.55 * emp_cx + 0.45 * hint_cx, s_bx0 + 12.0, s_bx1 - 12.0))
    else:
        cx_s = hint_cx

    # Estimate empirical crown row so head shield NEVER stamps floating hats above shifted portraits (RT-OPT-01)
    central_col = sup_s & (np.abs(xx_s - cx_s) <= 18.0 * sc)
    crown_rows = np.where((grad_s > 0.026) & central_col)[0]
    hint_crown = float(np.clip(6.0 + pan_y * 0.5 - (sc - 1.0) * 18.0, float(s_by0), float(max(s_by0, s_by1 - 24))))
    if len(crown_rows) > 0:
        emp_crown = float(np.percentile(crown_rows[: max(1, min(12, len(crown_rows)))], 15))
        crown_y_s = float(np.clip(0.70 * emp_crown + 0.30 * hint_crown, float(s_by0), float(max(s_by0, s_by1 - 20))))
    else:
        crown_y_s = hint_crown

    # Fit dome amplitude strictly outside the central head column on smooth, low-gradient background pixels
    head_excl = (np.abs(xx_s - cx_s) <= 23.0 * sc) & (yy_s >= crown_y_s - 2.0)
    smooth_bg = sup_s & (~head_excl) & (grad_s < 0.024) & (tex_s < 0.020) & (yy_s < min(y_cut_l, y_cut_r))
    w_dome = smooth_bg.astype(np.float32) * d_phi
    denom_row = (w_dome * d_phi).sum(axis=1, keepdims=True)  # (sh, 1)
    res_lab = lab_s - b_lin_s
    valid_dome_rows = (denom_row[:, 0] > 1.2)
    if np.any(valid_dome_rows):
        num_row = (w_dome[:, :, None] * res_lab).sum(axis=1)  # (sh, 3)
        dome_amp = np.zeros((sh, 3), dtype=np.float32)
        dome_amp[valid_dome_rows] = np.clip(
            num_row[valid_dome_rows] / np.maximum(denom_row[valid_dome_rows], 1.2),
            -0.14,
            0.22,
        )
        # Smooth dome amplitude vertically across valid upper rows and extrapolate downward cleanly
        last_valid = int(np.where(valid_dome_rows)[0].max())
        first_valid = int(np.where(valid_dome_rows)[0].min())
        if first_valid > 0:
            dome_amp[:first_valid] = dome_amp[first_valid]
        if last_valid < sh - 1:
            dome_amp[last_valid + 1 :] = dome_amp[last_valid]
        # 5-tap vertical box smooth on dome_amp
        dome_pad = np.pad(dome_amp, ((2, 2), (0, 0)), mode="edge")
        dome_amp = (dome_pad[:-4] + dome_pad[1:-3] + dome_pad[2:-2] + dome_pad[3:-1] + dome_pad[4:]) * np.float32(0.2)
    else:
        dome_amp = np.zeros((sh, 3), dtype=np.float32)

    bg_field_s = b_lin_s + phi_x[:, :, None] * dome_amp[:, None, :]

    # Exterior background seed zone anchored to opaque support box and safely outside head crown
    seed_w = max(5.0, min(12.0, 0.11 * float(s_bx1 - s_bx0)))
    bg_seed_s = sup_s & (
        (((xx_s < s_bx0 + seed_w) | (xx_s >= s_bx1 - seed_w)) & (yy_s < min(y_cut_l, y_cut_r) - 3.0))
        | ((xx_s < s_bx0 + 3.5) & (yy_s < y_cut_l - 2.5))
        | ((xx_s >= s_bx1 - 3.5) & (yy_s < y_cut_r - 2.5))
        | ((yy_s <= s_by0 + 2.5) & (np.abs(xx_s - cx_s) > 22.0 * sc))
    )
    if int(bg_seed_s.sum()) < 12:
        bg_seed_s = sup_s & ((xx_s <= s_bx0 + 2) | (xx_s >= s_bx1 - 3) | (yy_s <= s_by0 + 1))

    bg_pts = lab_s[bg_seed_s]
    q_bg = np.quantile(bg_pts[:, 0], [0.12, 0.38, 0.65, 0.90])
    protos_bg = np.stack([bg_pts[np.argmin(np.abs(bg_pts[:, 0] - q))] for q in q_bg], axis=0)
    for _ in range(3):
        lbl = np.argmin(((bg_pts[:, None, :] - protos_bg[None, :, :]) ** 2).sum(axis=-1), axis=1)
        for k in range(4):
            m = lbl == k
            if np.any(m):
                protos_bg[k] = bg_pts[m].mean(axis=0)

    diff_proto = (lab_s[:, :, None, :] - protos_bg[None, None, :, :]) * w_vec
    d_proto_s = np.sqrt(((diff_proto * diff_proto).sum(axis=-1)).min(axis=-1))
    diff_field = (lab_s - bg_field_s) * w_vec
    d_field_s = np.sqrt((diff_field * diff_field).sum(axis=-1))
    d_bg_s = np.minimum(d_proto_s, d_field_s)

    bg_noise = float(np.percentile(d_bg_s[bg_seed_s], 90)) + 0.015
    bg_tex = float(np.percentile(tex_s[bg_seed_s], 88)) + 0.009
    excess_bg = np.maximum(d_bg_s - bg_noise, 0.0)
    tex_excess = np.maximum(tex_s - bg_tex, 0.0)

    # Dynamic shoulder prior anchored by min so white-on-white shirts ALWAYS activate below neck height!
    sh_y_s = min(crown_y_s + 54.0 * sc, max(crown_y_s + 36.0 * sc, float(min(y_cut_l, y_cut_r)) - 2.0))
    shoulder_prior = np.clip((yy_s - sh_y_s) / max(22.0 * sc, 10.0), 0.0, 1.0)

    # Anthropometric core acts ONLY as geodesic step resistance below crown_y_s + 4 inside opaque support (NEVER blind alpha=1!)
    sup_eroded = (_box_filter_f32(sup_s.astype(np.float32), 1) >= 0.99)
    below_crown = yy_s >= (crown_y_s + 5.0)
    head_cy = crown_y_s + 36.0 * sc
    neck_y0 = crown_y_s + 50.0 * sc
    neck_y1 = crown_y_s + 88.0 * sc
    torso_cy = min(float(s_by1) - 4.0, crown_y_s + 116.0 * sc)
    fg_shield_s = sup_eroded & below_crown & (
        ((((xx_s - cx_s) / (13.5 * sc)) ** 2 + ((yy_s - head_cy) / (20.0 * sc)) ** 2) <= 1.0)
        | ((np.abs(xx_s - cx_s) <= 9.0 * sc) & (yy_s >= neck_y0) & (yy_s <= neck_y1))
        | ((((xx_s - cx_s) / (31.0 * sc)) ** 2 + ((yy_s - torso_cy) / (23.0 * sc)) ** 2) <= 1.0)
    )

    step_cost = (
        0.0003
        + 1.85 * excess_bg
        + 1.25 * tex_excess
        + (3.2 + 2.8 * shoulder_prior) * np.maximum(grad_s - 0.011, 0.0)
    ).astype(np.float32)
    step_cost = np.where(fg_shield_s, np.maximum(step_cost, np.float32(0.65)), step_cost)
    # Empty transparent outer margins (a_s <= 0.92) have zero cost and act as exterior seeds!
    ext_void_s = ~sup_s
    step_cost = np.where(ext_void_s, np.float32(0.0001), step_cost)

    valid_seed = ext_void_s | (
        bg_seed_s & (~fg_shield_s) & (d_bg_s < bg_noise * 2.9)
    ) | ((yy_s <= s_by0 + 1) & sup_s & (~fg_shield_s) & (np.abs(xx_s - cx_s) > 20.0 * sc) & (d_bg_s < bg_noise * 2.3))

    geo_s = _geodesic_8dir_fast(step_cost, valid_seed, passes=2)
    geo_full = np.asarray(
        Image.fromarray(geo_s, mode="F").resize((w, h), Image.Resampling.BILINEAR),
        dtype=np.float32,
    )

    thresh = float(0.075 + 0.145 * tol)
    fg_coarse = np.clip((geo_full - thresh * 0.55) / max(thresh * 0.65, 1e-4), 0.0, 1.0) * a_f_full

    bg_full_lab = np.stack(
        [
            np.asarray(
                Image.fromarray(bg_field_s[:, :, c], mode="F").resize((w, h), Image.Resampling.BILINEAR),
                dtype=np.float32,
            )
            for c in range(3)
        ],
        axis=-1,
    )
    diff_pf = (lab[:, :, None, :] - protos_bg[None, None, :, :]) * w_vec
    d_bg_full = np.minimum(
        np.sqrt(((diff_pf * diff_pf).sum(axis=-1)).min(axis=-1)),
        np.sqrt((((lab - bg_full_lab) * w_vec) ** 2).sum(axis=-1)),
    )
    solid_fg = (fg_coarse >= 0.50).astype(np.float32)
    inner_core = _box_filter_f32(solid_fg, 2) >= 0.99
    fg_w3 = np.maximum(_box_filter_f32(solid_fg, 3), 1e-4)
    local_fg_c = _box_filter_f32(d_bg_full * solid_fg, 3) / fg_w3
    high_c_rim = (~inner_core) & (fg_coarse > 0.0) & (local_fg_c > bg_noise * 2.2)
    if np.any(high_c_rim):
        c_gate = np.clip(
            (d_bg_full - bg_noise * 0.45) / np.maximum(np.minimum(local_fg_c * 0.50, bg_noise * 1.45), 1e-3),
            0.0,
            1.0,
        )
        fg_coarse = np.where(high_c_rim, fg_coarse * c_gate, fg_coarse)

    guide = lab[:, :, 0] + 0.35 * np.hypot(lab[:, :, 1], lab[:, :, 2])
    refined_a, _ = _wgif_single_channel(
        guide.astype(np.float32),
        fg_coarse.astype(np.float32),
        r=2,
        eps_base=0.00035,
        edge_pivot=0.042,
    )
    matte = np.clip((refined_a - 0.38) / 0.50, 0.0, 1.0) * a_f_full
    matte = np.where(matte < 0.025, 0.0, np.where(matte > 0.985, 1.0, matte))
    if np.any(matte > 0.0):
        fg_bridge = _box_filter_f32((matte > np.float32(0.04)).astype(np.float32), 2) > np.float32(0.01)
        fg_s = fg_bridge.reshape(sh, 2, sw, 2).any(axis=(1, 3))
        fg_seed_s = fg_shield_s & fg_s
        if np.any(fg_seed_s):
            conn_s = (
                _geodesic_8dir_fast(
                    np.where(fg_s, np.float32(0.0), np.float32(10.0)),
                    fg_seed_s,
                    passes=2,
                )
                < np.float32(1.0)
            )
            matte = np.where(np.repeat(np.repeat(conn_s, 2, axis=0), 2, axis=1), matte, np.float32(0.0))

    # Stage 5: Guarded sub-pixel Color-Line projection + algebraic background unmixing (0% AI)
    out_rgb = win[:, :, :3].astype(np.float32)
    if np.any(matte > 0.0):
        # Fast O(N) subgrid OKLab->sRGB via 8192-entry linear LUT (~2.6x faster than full-res float pow)
        L_s, a_s_ch, b_s_ch = bg_field_s[..., 0], bg_field_s[..., 1], bg_field_s[..., 2]
        l_ = (L_s + np.float32(0.39633778) * a_s_ch + np.float32(0.21580376) * b_s_ch) ** 3
        m_ = (L_s - np.float32(0.10556135) * a_s_ch - np.float32(0.06385417) * b_s_ch) ** 3
        s_ = (L_s - np.float32(0.08948418) * a_s_ch - np.float32(1.29148555) * b_s_ch) ** 3
        bg_lin_s = np.stack(
            [
                +np.float32(4.0767417) * l_ - np.float32(3.3077116) * m_ + np.float32(0.23096993) * s_,
                -np.float32(1.2684380) * l_ + np.float32(2.6097574) * m_ - np.float32(0.34131940) * s_,
                -np.float32(0.00419609) * l_ - np.float32(0.7034186) * m_ + np.float32(1.7076147) * s_,
            ],
            axis=-1,
        )
        bg_u8_s = linear_to_srgb_u8(np.clip(bg_lin_s, 0.0, 1.0))
        bg_full_rgb = np.asarray(
            Image.fromarray(bg_u8_s, mode="RGB").resize((w, h), Image.Resampling.BILINEAR),
            dtype=np.float32,
        )

        # 1. Eroded solid interior (2px inside matte >= 0.96) + 2-scale propagation (r=2 near, cascaded r=6 skirt reach)
        core_mask = (
            _box_filter_f32((matte >= np.float32(0.96)).astype(np.float32), 2) >= np.float32(0.99)
        ).astype(np.float32)
        w_c2 = _box_filter_f32(core_mask, 2)
        w_c6 = _box_filter_f32(w_c2, 4)
        has_core = w_c6 > np.float32(0.015)
        inv_w2 = np.float32(1.0) / np.maximum(w_c2, np.float32(1e-4))
        inv_w6 = np.float32(1.0) / np.maximum(w_c6, np.float32(1e-4))
        use_near = np.clip(w_c2 * np.float32(1.0 / 0.12), np.float32(0.0), np.float32(1.0))[:, :, None]

        f_near = np.empty_like(out_rgb)
        f_far = np.empty_like(out_rgb)
        for c in range(3):
            ch_m = _box_filter_f32(out_rgb[:, :, c] * core_mask, 2)
            f_near[:, :, c] = ch_m * inv_w2
            f_far[:, :, c] = _box_filter_f32(ch_m, 4) * inv_w6
        f_core = f_near * use_near + f_far * (np.float32(1.0) - use_near)

        # 2. Core homogeneity gate (protects striped kits, shoulder seams, polka dots & collar-to-skin junctions)
        lum_in = (out_rgb[:, :, 0] + out_rgb[:, :, 1] + out_rgb[:, :, 2]) * np.float32(1.0 / 3.0)
        w_c3 = np.maximum(_box_filter_f32(core_mask, 3), np.float32(1e-4))
        l_m3 = _box_filter_f32(lum_in * core_mask, 3) / w_c3
        l2_m3 = _box_filter_f32((lum_in * lum_in) * core_mask, 3) / w_c3
        core_std = np.sqrt(np.maximum(l2_m3 - l_m3 * l_m3, np.float32(0.0)))
        homog_gate = np.where(
            w_c3 > np.float32(0.04),
            np.clip((np.float32(30.0) - core_std) * np.float32(1.0 / 18.0), np.float32(0.0), np.float32(1.0)),
            np.float32(1.0),
        )

        # 3. Exterior-adjacent rim band (immunizes opaque sleeves touching DF11 frame borders x=18..241, y=293)
        has_near_ext = _box_filter_f32((matte < np.float32(0.25)).astype(np.float32), 5) > np.float32(0.015)
        rim_band = (matte > np.float32(0.0)) & (~(core_mask > np.float32(0.5))) & has_near_ext & has_core
        trust_full = np.zeros((h, w), dtype=np.float32)
        if np.any(rim_band):
            v_r = f_core[rim_band] - bg_full_rgb[rim_band]
            v2_r = (v_r * v_r).sum(axis=-1)
            vn_r = np.sqrt(v2_r)
            c_gate = np.clip((vn_r - np.float32(38.0)) * np.float32(1.0 / 44.0), np.float32(0.0), np.float32(1.0))
            t_raw = ((out_rgb[rim_band] - bg_full_rgb[rim_band]) * v_r).sum(axis=-1) / np.maximum(
                v2_r, np.float32(1.0)
            )
            a_proj = np.clip(t_raw, np.float32(0.0), np.float32(1.0))
            recon = bg_full_rgb[rim_band] + np.clip(t_raw, np.float32(-0.30), np.float32(1.0))[:, None] * v_r
            r_perp = np.sqrt(((out_rgb[rim_band] - recon) ** 2).sum(axis=-1))
            col_gate = np.clip(
                np.float32(1.0) - (r_perp - (np.float32(9.0) + np.float32(0.10) * vn_r)) * np.float32(1.0 / 18.0),
                np.float32(0.0),
                np.float32(1.0),
            )
            tr = homog_gate[rim_band] * c_gate * col_gate
            trust_full[rim_band] = tr
            m_rim = matte[rim_band]
            matte[rim_band] = m_rim * (np.float32(1.0) - tr) + np.minimum(m_rim, a_proj) * tr
            matte = np.where(
                matte < np.float32(0.025),
                np.float32(0.0),
                np.where(matte > np.float32(0.985), np.float32(1.0), matte),
            )

        edge_band = (matte > np.float32(0.0)) & (matte < np.float32(0.98))
        if np.any(edge_band):
            m_eb = matte[edge_band][:, None]
            bg_eb = bg_full_rgb[edge_band]
            fc_eb = f_core[edge_band]
            tr_eb = trust_full[edge_band]
            unmixed_eb = np.clip(
                (out_rgb[edge_band] - (np.float32(1.0) - m_eb) * bg_eb) / np.maximum(m_eb, np.float32(0.18)),
                np.float32(0.0),
                np.float32(255.0),
            )
            low_a_w = (
                np.clip((np.float32(0.40) - matte[edge_band]) * np.float32(1.0 / 0.40), np.float32(0.0), np.float32(1.0))
                * has_core[edge_band]
            )
            lum_agree = np.clip(
                np.float32(1.0) - np.abs(unmixed_eb.mean(axis=-1) - fc_eb.mean(axis=-1)) * np.float32(1.0 / 95.0),
                np.float32(0.0),
                np.float32(1.0),
            )
            w_stab = (low_a_w * np.maximum(lum_agree, tr_eb * np.float32(0.90)))[:, None]
            decontam = unmixed_eb * (np.float32(1.0) - w_stab) + fc_eb * w_stab
            pull = np.clip((np.float32(0.97) - matte[edge_band]) * np.float32(1.0 / 0.45), np.float32(0.0), np.float32(1.0))
            pull = np.where(tr_eb > np.float32(0.35), np.maximum(pull, tr_eb), pull)[:, None]
            out_rgb[edge_band] = (np.float32(1.0) - pull) * out_rgb[edge_band] + pull * decontam

    alpha_u8 = np.clip(np.round(matte * 255.0), 0.0, 255.0).astype(np.uint8)
    clean_win = np.zeros((h, w, 4), dtype=np.uint8)
    clean_win[:, :, :3] = np.where(alpha_u8[:, :, None] > 0, np.clip(np.round(out_rgb), 0, 255).astype(np.uint8), 0)
    clean_win[:, :, 3] = alpha_u8

    out_full = np.zeros_like(t_arr)
    out_full[y0:y1, x0:x1] = clean_win
    return Image.fromarray(out_full, mode="RGBA")

