"""RED->GREEN deterministic tests for backend.core.image_guard."""

from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageCms

from backend.core.image_guard import MAX_BYTES, MAX_SIDE_PX, ImageGuardError, load_guarded_image


def test_rejects_payload_over_20mb() -> None:
    huge = b"\x89PNG\r\n\x1a\n" + b"\x00" * (MAX_BYTES + 1)
    with pytest.raises(ImageGuardError, match="20 MB"):
        load_guarded_image(huge)


def test_rejects_decompression_bomb_over_25mp() -> None:
    bomb = Image.new("L", (6000, 5000), color=128)
    buf = io.BytesIO()
    bomb.save(buf, format="PNG", compress_level=9)
    assert buf.tell() < 200_000
    with pytest.raises(ImageGuardError, match="25 MP"):
        load_guarded_image(buf.getvalue())


def test_resets_stream_cursor_before_reading() -> None:
    buf = io.BytesIO()
    Image.new("RGB", (120, 140), (40, 90, 180)).save(buf, format="PNG")
    buf.seek(37)
    guarded = load_guarded_image(buf)
    assert guarded.image.mode == "RGBA" and guarded.image.size == (120, 140)


def test_applies_exif_orientation_6_to_upright() -> None:
    raw = Image.new("RGB", (200, 100), (20, 20, 20))
    raw.paste((240, 30, 30), (0, 0, 40, 100))
    exif = raw.getexif()
    exif[0x0112] = 6
    buf = io.BytesIO()
    raw.save(buf, format="JPEG", quality=98, exif=exif.tobytes())
    guarded = load_guarded_image(buf.getvalue())
    assert guarded.image.size == (100, 200)
    r, g, b, a = guarded.image.getpixel((50, 10))
    assert r > 200 and g < 60 and b < 60 and a == 255


def test_converts_cmyk_and_icc_profile_to_srgb_rgba() -> None:
    cmyk_buf = io.BytesIO()
    Image.new("CMYK", (64, 64), (0, 200, 200, 10)).save(cmyk_buf, format="JPEG")
    assert load_guarded_image(cmyk_buf.getvalue()).image.mode == "RGBA"

    rgba = Image.new("RGBA", (64, 64), (180, 90, 45, 128))
    xyz_profile = ImageCms.ImageCmsProfile(ImageCms.createProfile("XYZ")).tobytes()
    icc_buf = io.BytesIO()
    rgba.save(icc_buf, format="PNG", icc_profile=xyz_profile)
    out_icc = load_guarded_image(icc_buf.getvalue())
    assert out_icc.image.mode == "RGBA" and out_icc.image.getpixel((10, 10))[3] == 128


def test_decodes_webp_jfif_and_avif(tmp_path: Path) -> None:
    src = Image.new("RGBA", (80, 96), (30, 140, 220, 255))
    for ext, fmt, mode in [("webp", "WEBP", "RGBA"), ("jfif", "JPEG", "RGB"), ("avif", "AVIF", "RGBA")]:
        p = tmp_path / f"sample.{ext}"
        src.convert(mode).save(p, format=fmt)
        assert load_guarded_image(p).image.size == (80, 96)


def test_distinguishes_opaque_screenshot_from_true_cutout() -> None:
    buf_opaque = io.BytesIO()
    Image.new("RGBA", (250, 250), (120, 130, 140, 255)).save(buf_opaque, format="PNG")
    assert load_guarded_image(buf_opaque.getvalue()).is_pre_cutout is False

    arr = np.zeros((250, 250, 4), dtype=np.uint8)
    arr[40:250, 60:190] = (200, 160, 140, 255)
    cutout_buf = io.BytesIO()
    Image.fromarray(arr, mode="RGBA").save(cutout_buf, format="PNG")
    assert load_guarded_image(cutout_buf.getvalue()).is_pre_cutout is True


def test_downscales_longest_side_proportionally() -> None:
    buf = io.BytesIO()
    Image.new("RGB", (3072, 1536), (90, 110, 130)).save(buf, format="JPEG")
    guarded = load_guarded_image(buf.getvalue())
    assert guarded.original_size == (3072, 1536) and guarded.image.size == (MAX_SIDE_PX, 768)


def test_rejects_svg_or_corrupt_bytes() -> None:
    with pytest.raises(ImageGuardError):
        load_guarded_image(b"<svg xmlns='http://www.w3.org/2000/svg'></svg>")
