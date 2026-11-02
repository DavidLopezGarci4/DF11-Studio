"""Input validation, decompression-bomb protection, EXIF transpose, and sRGB normalization."""

from __future__ import annotations

import io
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Union

import numpy as np
from PIL import Image, ImageCms, ImageOps, UnidentifiedImageError

try:
    import pillow_avif  # noqa: F401
except ImportError:  # pragma: no cover
    pass

MAX_BYTES = 20 * 1024 * 1024  # 20 MB hard cap before bitmap decode
MAX_PIXELS = 25_000_000       # 25 MP decompression-bomb hard cap
MAX_SIDE_PX = 1536            # Max proportional dimension for Studio/Vision pipeline

ImageSource = Union[bytes, bytearray, str, Path, BinaryIO]


class ImageGuardError(ValueError):
    """Raised when an input image violates size, pixel, or format safety bounds."""


@dataclass(frozen=True, slots=True)
class GuardedImage:
    """Validated sRGB RGBA image ready for compositing or DirectML segmentation."""

    image: Image.Image
    is_pre_cutout: bool
    original_size: tuple[int, int]


def _read_bounded_bytes(source: ImageSource) -> bytes:
    if isinstance(source, (bytes, bytearray)):
        if len(source) > MAX_BYTES:
            raise ImageGuardError("El archivo supera el límite máximo permitido de 20 MB.")
        return bytes(source)

    if isinstance(source, (str, Path)):
        path = Path(source)
        if not path.is_file():
            raise ImageGuardError(f"No se encontró el archivo de imagen: {path.name}")
        if path.stat().st_size > MAX_BYTES:
            raise ImageGuardError("El archivo supera el límite máximo permitido de 20 MB.")
        with path.open("rb") as fh:
            data = fh.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise ImageGuardError("El archivo supera el límite máximo permitido de 20 MB.")
        return data

    if hasattr(source, "read"):
        if hasattr(source, "seek"):
            source.seek(0)
        data = source.read(MAX_BYTES + 1)
        if not isinstance(data, (bytes, bytearray)):
            raise ImageGuardError("Flujo de imagen binario inválido.")
        if len(data) > MAX_BYTES:
            raise ImageGuardError("El archivo supera el límite máximo permitido de 20 MB.")
        return bytes(data)

    raise ImageGuardError("Tipo de entrada de imagen no soportado.")


def _to_srgb_rgba(img: Image.Image) -> Image.Image:
    alpha = img.getchannel("A") if "A" in img.getbands() else None
    icc_bytes = img.info.get("icc_profile")
    if icc_bytes:
        try:
            src_prof = ImageCms.ImageCmsProfile(io.BytesIO(icc_bytes))
            dst_prof = ImageCms.createProfile("sRGB")
            base_mode = "CMYK" if img.mode == "CMYK" else "RGB"
            base = img if img.mode == base_mode else img.convert(base_mode)
            srgb_rgb = ImageCms.profileToProfile(base, src_prof, dst_prof, outputMode="RGB")
            rgba = srgb_rgb.convert("RGBA")
            if alpha is not None:
                rgba.putalpha(alpha)
            rgba.info.pop("icc_profile", None)
            return rgba
        except Exception:
            pass

    rgba = img.convert("RGBA")
    rgba.info.pop("icc_profile", None)
    return rgba


def load_guarded_image(source: ImageSource, max_side: int = MAX_SIDE_PX) -> GuardedImage:
    """Validate byte/pixel bounds, fix EXIF rotation, normalize to sRGB RGBA, and cap size."""
    raw = _read_bounded_bytes(source)
    if not raw:
        raise ImageGuardError("El archivo de imagen está vacío.")

    prev_max = Image.MAX_IMAGE_PIXELS
    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as opened:
                if opened.width * opened.height > MAX_PIXELS:
                    raise ImageGuardError("La imagen supera el límite de 25 MP (píxeles).")
                opened.load()
                transposed = ImageOps.exif_transpose(opened)
    except ImageGuardError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ImageGuardError("La imagen supera el límite de 25 MP (píxeles).") from exc
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as exc:
        raise ImageGuardError("Formato de imagen inválido, corrupto o no soportado.") from exc
    finally:
        Image.MAX_IMAGE_PIXELS = prev_max

    original_size = (transposed.width, transposed.height)
    rgba = _to_srgb_rgba(transposed)

    longest = max(rgba.width, rgba.height)
    if longest > max_side:
        scale = max_side / float(longest)
        new_size = (max(1, round(rgba.width * scale)), max(1, round(rgba.height * scale)))
        rgba = rgba.resize(new_size, Image.Resampling.LANCZOS)

    alpha_arr = np.asarray(rgba.getchannel("A"), dtype=np.uint8)
    is_pre_cutout = bool((alpha_arr < 16).mean() >= 0.03)
    return GuardedImage(image=rgba, is_pre_cutout=is_pre_cutout, original_size=original_size)
