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
    lab = srgb_to_oklab(arr[:, :, :3].astype(np.float32) / 255.0)
    lift_l = 0.0
    shift_a = 0.0
    shift_b = 0.0
    if np.all(fg):
        # Full-scene opaque photo (e.g. Direct Photo mode): preserve stadium/kit hues, lift only truly dim scenes
        p92_l = float(np.percentile(lab[:, :, 0], 92))
        if p92_l < 0.70:
            lift_l = min(0.70 - p92_l, 0.12) * 0.60
        med_a = float(np.median(lab[:, :, 1]))
        if abs(med_a) > 0.055:
            shift_a = -(med_a - math.copysign(0.055, med_a)) * 0.25
        med_b = float(np.median(lab[:, :, 2]))
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
    lab = srgb_to_oklab(arr[:, :, :3].astype(np.float32) / 255.0)
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

    kernel = Image.Resampling.LANCZOS if eff_scale <= 1.35 else Image.Resampling.BICUBIC

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

    lab = srgb_to_oklab(rgb_u8.astype(np.float32) / 255.0)
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
