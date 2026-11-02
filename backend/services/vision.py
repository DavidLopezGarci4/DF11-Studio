"""DirectML ONNX vision engines (YuNet, Selfie-Multiclass, BiRefNet-Lite) + OKLab & Gaussian tools."""

from __future__ import annotations

import hashlib
import os
import threading
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import onnxruntime as ort
from PIL import Image, ImageFilter

from backend.core.fm_config import safe_ntfs_replace
from backend.core.paths import get_models_dir

CLASS_BG, CLASS_HAIR, CLASS_BODY_SKIN, CLASS_FACE_SKIN, CLASS_CLOTHES, CLASS_OTHERS = range(6)


class ModelIntegrityError(RuntimeError):
    """Raised when an ONNX weight file fails SHA-256 verification or download."""


@dataclass(frozen=True, slots=True)
class ModelSpec:
    filename: str
    url: str
    sha256: str


@dataclass(frozen=True, slots=True)
class FacePose:
    right_eye: tuple[float, float]
    left_eye: tuple[float, float]
    nose: tuple[float, float]
    eye_center: tuple[float, float]
    ipd: float
    yaw: float
    bbox: tuple[float, float, float, float]


YUNET_SPEC = ModelSpec(
    filename="face_detection_yunet_2023mar.onnx",
    url="https://huggingface.co/opencv/face_detection_yunet/resolve/main/face_detection_yunet_2023mar.onnx",
    sha256="8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4",
)
SELFIE_SEG_SPEC = ModelSpec(
    filename="selfie_multiclass_256x256.onnx",
    url="https://huggingface.co/senty-au/selfie_multiclass_256x256-ONNX/resolve/main/onnx/model.onnx",
    sha256="35ec1ecd9ee7f85073c99c00020b7f6751b69506eeacf683bc8665f6117f85b0",
)
BIREFNET_SPEC = ModelSpec(
    filename="birefnet-general-lite.onnx",
    url="https://huggingface.co/onnx-community/BiRefNet_lite-ONNX/resolve/main/onnx/model_fp16.onnx",
    sha256="d39b897ceb16ae654c1731f3dba0cf9b368d9cae74b5a57459b455cc8bfec402",
)

_VERIFIED_FILES: dict[Path, tuple[int, int]] = {}
_SESSIONS: dict[str, tuple[ort.InferenceSession, threading.Lock]] = {}
_SESSION_INIT_LOCK = threading.Lock()


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(1024 * 512):
            h.update(chunk)
    return h.hexdigest()


def ensure_model(
    spec: ModelSpec,
    models_dir: Path | None = None,
    fetcher: Callable[[str], bytes] | None = None,
) -> Path:
    """Verify local ONNX model SHA-256 or atomically download via .part file."""
    target_dir = models_dir or get_models_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    dst = target_dir / spec.filename

    if dst.is_file():
        st = dst.stat()
        sig = (st.st_mtime_ns, st.st_size)
        if _VERIFIED_FILES.get(dst) == sig:
            return dst
        if _sha256_file(dst).lower() == spec.sha256.lower():
            _VERIFIED_FILES[dst] = sig
            return dst

    part = target_dir / f"{spec.filename}.{os.getpid()}.part"
    try:
        h = hashlib.sha256()
        if fetcher is not None:
            data = fetcher(spec.url)
            h.update(data)
            part.write_bytes(data)
        else:
            req = urllib.request.Request(spec.url, headers={"User-Agent": "DF11FaceStudio/1.0"})
            with urllib.request.urlopen(req, timeout=180) as resp, part.open("wb") as out:
                while chunk := resp.read(1024 * 256):
                    h.update(chunk)
                    out.write(chunk)
        if h.hexdigest().lower() != spec.sha256.lower():
            raise ModelIntegrityError(f"SHA-256 inválido para {spec.filename}.")
        safe_ntfs_replace(part, dst)
        st = dst.stat()
        _VERIFIED_FILES[dst] = (st.st_mtime_ns, st.st_size)
        return dst
    except ModelIntegrityError:
        raise
    except Exception as exc:
        raise ModelIntegrityError(f"Error aprovisionando {spec.filename}: {exc}") from exc
    finally:
        if part.exists():
            part.unlink(missing_ok=True)


def _build_session(model_path: Path, force_cpu: bool = False) -> ort.InferenceSession:
    so = ort.SessionOptions()
    so.log_severity_level = 3
    so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_BASIC
    so.intra_op_num_threads = 8
    so.inter_op_num_threads = 1
    so.enable_mem_pattern = False
    so.add_session_config_entry("session.intra_op.allow_spinning", "0")
    avail = ort.get_available_providers()
    providers = ["CPUExecutionProvider"] if force_cpu or "DmlExecutionProvider" not in avail else ["DmlExecutionProvider", "CPUExecutionProvider"]
    return ort.InferenceSession(str(model_path), sess_options=so, providers=providers)


def _get_session(spec: ModelSpec) -> tuple[ort.InferenceSession, threading.Lock]:
    with _SESSION_INIT_LOCK:
        if spec.filename in _SESSIONS:
            return _SESSIONS[spec.filename]
        sess = _build_session(ensure_model(spec), force_cpu=False)
        pair = (sess, threading.Lock())
        _SESSIONS[spec.filename] = pair
        return pair


def _run_session(spec: ModelSpec, feed: dict[str, np.ndarray]) -> tuple[ort.InferenceSession, list[np.ndarray]]:
    """Run ONNX inference; on DirectML DXGI_ERROR_DEVICE_RESET / CP1252 error, fall back cleanly to CPU."""
    sess, lock = _get_session(spec)
    with lock:
        try:
            return sess, list(sess.run(None, feed))
        except Exception:
            cpu_sess = _build_session(ensure_model(spec), force_cpu=True)
            with _SESSION_INIT_LOCK:
                _SESSIONS[spec.filename] = (cpu_sess, lock)
            return cpu_sess, list(cpu_sess.run(None, feed))


def detect_face_pose(img_rgba: Image.Image, score_thresh: float = 0.55) -> FacePose | None:
    """Detect primary eyes, IPD, nose, and yaw in < 1 ms via YuNet ONNX."""
    w, h = img_rgba.size
    scale = min(640.0 / max(w, 1), 640.0 / max(h, 1))
    nw, nh = max(1, round(w * scale)), max(1, round(h * scale))
    canvas = Image.new("RGB", (640, 640), (0, 0, 0))
    canvas.paste(img_rgba.convert("RGB").resize((nw, nh), Image.Resampling.BILINEAR), (0, 0))
    bgr = np.asarray(canvas, dtype=np.float32)[:, :, ::-1].transpose(2, 0, 1)[None, ...]

    sess, raw_outs = _run_session(YUNET_SPEC, {"input": bgr})
    outs = dict(zip([o.name for o in sess.get_outputs()], raw_outs))

    best_score = score_thresh
    best_kps: np.ndarray | None = None
    best_box: tuple[float, float, float, float] = (0.0, 0.0, float(w), float(h))
    for stride in (8, 16, 32):
        rows = cols = 640 // stride
        gy, gx = np.mgrid[0:rows, 0:cols].astype(np.float32)
        scores = np.sqrt(np.clip(outs[f"cls_{stride}"][0, :, 0], 0.0, 1.0) * np.clip(outs[f"obj_{stride}"][0, :, 0], 0.0, 1.0))
        idx = int(np.argmax(scores))
        sc = float(scores[idx])
        if sc > best_score:
            best_score = sc
            cx, cy = float(gx.ravel()[idx]), float(gy.ravel()[idx])
            kps = ((outs[f"kps_{stride}"][0, idx].reshape(5, 2) + np.array([[cx, cy]])) * stride) / scale
            bb = outs[f"bbox_{stride}"][0, idx]
            bx = ((cx + float(bb[0])) * stride) / scale
            by = ((cy + float(bb[1])) * stride) / scale
            bw = (float(np.exp(bb[2])) * stride) / scale
            bh = (float(np.exp(bb[3])) * stride) / scale
            best_kps = kps
            best_box = (bx - bw * 0.5, by - bh * 0.5, bw, bh)

    if best_kps is None:
        return None
    reye = (float(best_kps[0, 0]), float(best_kps[0, 1]))
    leye = (float(best_kps[1, 0]), float(best_kps[1, 1]))
    nose = (float(best_kps[2, 0]), float(best_kps[2, 1]))
    ec = ((reye[0] + leye[0]) * 0.5, (reye[1] + leye[1]) * 0.5)
    ipd = max(float(np.hypot(leye[0] - reye[0], leye[1] - reye[1])), 1.0)
    yaw = float(np.clip((nose[0] - ec[0]) / ipd, -0.6, 0.6))
    return FacePose(right_eye=reye, left_eye=leye, nose=nose, eye_center=ec, ipd=ipd, yaw=yaw, bbox=best_box)


def segment_portrait_classes(img_rgba: Image.Image) -> np.ndarray:
    """Return (H, W, 6) softmax probabilities [bg, hair, body_skin, face_skin, clothes, others]."""
    w, h = img_rgba.size
    inp = np.asarray(img_rgba.convert("RGB").resize((256, 256), Image.Resampling.BILINEAR), dtype=np.float32)[None, ...] / 255.0
    _, raw_outs = _run_session(SELFIE_SEG_SPEC, {"input_29": inp})
    logits = raw_outs[0][0]
    shifted = np.exp(logits - logits.max(axis=-1, keepdims=True))
    probs_256 = shifted / np.maximum(shifted.sum(axis=-1, keepdims=True), 1e-6)
    if (w, h) == (256, 256):
        return probs_256.astype(np.float32)
    chans = [
        np.asarray(Image.fromarray(probs_256[:, :, c], mode="F").resize((w, h), Image.Resampling.BILINEAR), dtype=np.float32)
        for c in range(6)
    ]
    return np.stack(chans, axis=-1)


def remove_background_birefnet(img_rgba: Image.Image) -> Image.Image:
    """Segment raw photo foreground via BiRefNet-Lite DirectML with 1.5px edge defringing."""
    w, h = img_rgba.size
    rgb = img_rgba.convert("RGB")
    arr = np.asarray(rgb.resize((1024, 1024), Image.Resampling.BILINEAR), dtype=np.float32) / 255.0
    mean = np.array([0.485, 0.456, 0.406], dtype=np.float32)
    std = np.array([0.229, 0.224, 0.225], dtype=np.float32)
    inp = ((arr - mean) / std).transpose(2, 0, 1)[None, ...]

    _, raw_outs = _run_session(BIREFNET_SPEC, {"input_image": inp})
    logits = raw_outs[0][0, 0]
    matte_1024 = 1.0 / (1.0 + np.exp(-np.clip(logits.astype(np.float32), -30.0, 30.0)))
    alpha_img = Image.fromarray(np.clip(np.round(matte_1024 * 255.0), 0, 255).astype(np.uint8), mode="L").resize(
        (w, h), Image.Resampling.BILINEAR
    )

    # 1.5px foreground color decontamination along semi-transparent hair/shoulder boundary
    eroded_rgb = np.asarray(rgb.filter(ImageFilter.MinFilter(3)), dtype=np.float32)
    orig_rgb = np.asarray(rgb, dtype=np.float32)
    alpha_f = np.asarray(alpha_img, dtype=np.float32)[:, :, None] / 255.0
    edge_band = ((alpha_f > 0.04) & (alpha_f < 0.92)).astype(np.float32)
    clean_rgb = np.clip(np.round(orig_rgb * (1.0 - 0.65 * edge_band) + eroded_rgb * (0.65 * edge_band)), 0, 255).astype(np.uint8)
    out = Image.fromarray(clean_rgb, mode="RGB").convert("RGBA")
    out.putalpha(alpha_img)
    return out


def srgb_to_oklab(rgb_01: np.ndarray) -> np.ndarray:
    """Vectorized sRGB [0..1] -> Björn Ottosson OKLab (L, a, b)."""
    lin = np.where(rgb_01 <= 0.04045, rgb_01 / 12.92, ((rgb_01 + 0.055) / 1.055) ** 2.4)
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


def oklab_to_srgb(lab: np.ndarray) -> np.ndarray:
    """Vectorized Björn Ottosson OKLab -> clamped sRGB [0..1]."""
    L, a, b = lab[..., 0], lab[..., 1], lab[..., 2]
    l_ = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3
    m_ = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3
    s_ = (L - 0.0894841775 * a - 1.2914855480 * b) ** 3
    r = +4.0767416621 * l_ - 3.3077115913 * m_ + 0.2309699292 * s_
    g = -1.2684380046 * l_ + 2.6097574011 * m_ - 0.3413193965 * s_
    bl = -0.0041960863 * l_ - 0.7034186147 * m_ + 1.7076147010 * s_
    lin = np.clip(np.stack([r, g, bl], axis=-1), 0.0, 1.0)
    return np.where(lin <= 0.0031308, 12.92 * lin, 1.055 * (lin ** (1.0 / 2.4)) - 0.055).astype(np.float32)


def harmonize_df11_studio_grade(img_rgba: Image.Image) -> Image.Image:
    """Normalize exposure and indoor color casts in OKLab space while keeping alpha untouched."""
    arr = np.asarray(img_rgba.convert("RGBA"), dtype=np.uint8).copy()
    fg = arr[:, :, 3] > 24
    if not np.any(fg):
        return Image.fromarray(arr, mode="RGBA")
    lab = srgb_to_oklab(arr[:, :, :3].astype(np.float32) / 255.0)
    med_l = float(np.median(lab[fg, 0]))
    if med_l < 0.62:
        lift = min(0.62 - med_l, 0.14) * 0.75
        lab[fg, 0] = np.clip(lab[fg, 0] + lift * (1.0 - lab[fg, 0]), 0.0, 0.99)
    # Gently damp heavy warm/green indoor white-balance casts without desaturating skin
    for ch, neutral in ((1, 0.025), (2, 0.045)):
        delta = float(np.median(lab[fg, ch])) - neutral
        if abs(delta) > 0.025:
            lab[fg, ch] -= delta * 0.35
    arr[:, :, :3] = np.clip(np.round(oklab_to_srgb(lab) * 255.0), 0, 255).astype(np.uint8)
    return Image.fromarray(arr, mode="RGBA")


def extract_clean_background(scene_rgba: Image.Image, fg_mask: np.ndarray | Image.Image) -> Image.Image:
    """5-line Normalized Gaussian Convolution: seamless clean background without foreground ghosts."""
    rgb = np.asarray(scene_rgba.convert("RGB"), dtype=np.float32)
    mask_img = fg_mask if isinstance(fg_mask, Image.Image) else Image.fromarray(np.asarray(fg_mask, dtype=np.uint8), mode="L")
    w_bg = 1.0 - np.asarray(mask_img.resize(scene_rgba.size, Image.Resampling.BILINEAR).filter(ImageFilter.MaxFilter(5)), dtype=np.float32)[..., None] / 255.0
    premul = np.concatenate([rgb * w_bg, w_bg * 255.0], axis=-1).round().clip(0, 255).astype(np.uint8)
    blurred = np.asarray(Image.fromarray(premul, mode="RGBA").filter(ImageFilter.GaussianBlur(max(24.0, max(scene_rgba.size) * 0.24))), dtype=np.float32)
    out_rgb = np.clip(np.round(blurred[:, :, :3] / np.maximum(blurred[:, :, 3:4] / 255.0, 1e-3)), 0, 255).astype(np.uint8)
    return Image.fromarray(out_rgb, mode="RGB").convert("RGBA")
