"""Lossless DF11 3-layer premultiplied compositor (260x310 RGBA / RGB)."""

from __future__ import annotations

import io
from functools import lru_cache
from typing import Literal

import numpy as np
from PIL import Image, ImageFilter, ImageOps

from backend.core.paths import ASSETS_DIR

DF11_WIDTH = 260
DF11_HEIGHT = 310
INNER_X0, INNER_Y0, INNER_X1, INNER_Y1 = 19, 17, 242, 293  # 223x276 incl. AA edge
CROWN_Y, EYES_Y, SHOULDERS_Y = 24, 112, 292

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
        lum = np.clip(253.0 - 11.0 * r2, 236.0, 254.0)
        rgb = np.stack([lum, lum, np.clip(lum + 1.0, 0, 255)], axis=2)
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


def _place_portrait(portrait: Image.Image, offset: tuple[float, float], scale: float) -> np.ndarray:
    canvas = np.zeros((DF11_HEIGHT, DF11_WIDTH, 4), dtype=np.uint8)
    scale = max(0.15, min(float(scale), 4.0))
    pw = max(1, round(portrait.width * scale))
    ph = max(1, round(portrait.height * scale))
    resized = portrait.convert("RGBA") if (pw, ph) == portrait.size else portrait.convert("RGBA").resize((pw, ph), Image.Resampling.LANCZOS)
    src = np.asarray(resized, dtype=np.uint8)

    x0 = round((DF11_WIDTH - pw) / 2.0 + float(offset[0]))
    y0 = round((DF11_HEIGHT - ph) / 2.0 + float(offset[1]))
    cx0, cy0 = max(0, x0), max(0, y0)
    cx1, cy1 = min(DF11_WIDTH, x0 + pw), min(DF11_HEIGHT, y0 + ph)
    if cx1 > cx0 and cy1 > cy0:
        canvas[cy0:cy1, cx0:cx1] = src[cy0 - y0 : cy1 - y0, cx0 - x0 : cx1 - x0]
    return canvas


def render_df11_card(
    portrait_rgba: Image.Image | None,
    portrait_offset: tuple[float, float] = (0.0, 0.0),
    portrait_scale: float = 1.0,
    bg_mode: BgMode = "white_df11",
    bg_custom_rgba: Image.Image | None = None,
    bg_blur: float = 0.0,
) -> Image.Image:
    """Composite Layer 1 + Layer 2, apply destination-in inner clip, and top with Layer 3 DF11 frame."""
    inner_mask_img, overlay_img = load_df11_assets()
    layer1 = _prepare_layer1(bg_mode, bg_custom_rgba, bg_blur)
    combined = layer1 if portrait_rgba is None else premul_over(layer1, _place_portrait(portrait_rgba, portrait_offset, portrait_scale))

    # Destination-in clip BEFORE frame overlay so the punched ring stays strictly Alpha == 0
    mask_f = np.asarray(inner_mask_img, dtype=np.float32)[:, :, None] / 255.0
    clipped = combined.copy()
    clipped_a = np.round(clipped[:, :, 3:4].astype(np.float32) * mask_f).astype(np.uint8)
    clipped[:, :, 3:4] = clipped_a
    clipped[:, :, :3] = np.where(clipped_a > 0, clipped[:, :, :3], 0)

    final_arr = premul_over(clipped, np.asarray(overlay_img, dtype=np.uint8))
    return Image.fromarray(final_arr, mode="RGBA")


def export_df11_bytes(card_rgba: Image.Image, fmt: Literal["png", "jpg"] = "png", compress_level: int = 6) -> bytes:
    """Encode a 260x310 DF11 card as official 32-bit RGBA PNG or 4:4:4 RGB JPEG over pure white."""
    rgba = card_rgba.convert("RGBA")
    if rgba.size != (DF11_WIDTH, DF11_HEIGHT):
        rgba = rgba.resize((DF11_WIDTH, DF11_HEIGHT), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    if fmt.lower() == "png":
        rgba.save(buf, format="PNG", compress_level=compress_level)
    elif fmt.lower() in ("jpg", "jpeg"):
        white = np.full((DF11_HEIGHT, DF11_WIDTH, 4), 255, dtype=np.uint8)
        flat = premul_over(white, np.asarray(rgba, dtype=np.uint8))[:, :, :3]
        Image.fromarray(flat, mode="RGB").save(buf, format="JPEG", quality=95, subsampling=0)
    else:
        raise ValueError(f"Formato de exportación no soportado: {fmt}")
    return buf.getvalue()
