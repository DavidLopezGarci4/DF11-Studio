"""DirectML ONNX vision engines (YuNet, Selfie-Multiclass, BiRefNet-Lite) + OKLab & Gaussian tools."""

from __future__ import annotations

import hashlib
import os
import threading
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
from PIL import Image, ImageFilter

if TYPE_CHECKING:
    import onnxruntime as ort

from backend.core.dsp import (
    harmonize_oklab_pure_optics as harmonize_df11_studio_grade,
    oklab_to_srgb,
    srgb_to_oklab,
)
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
_SESSIONS: dict[str, ort.InferenceSession] = {}
_INFER_LOCK = threading.RLock()
_DML_DISABLED = False


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
    """Verify local ONNX model SHA-256 or atomically download via thread-isolated .part file."""
    with _INFER_LOCK:
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

        part = target_dir / f"{spec.filename}.{os.getpid()}.{threading.get_ident()}.part"
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


def _get_ort() -> Any:
    import onnxruntime as ort_mod

    return ort_mod


def _build_session(model_path: Path, force_cpu: bool = False) -> ort.InferenceSession:
    ort_mod = _get_ort()
    use_cpu = force_cpu or _DML_DISABLED
    so = ort_mod.SessionOptions()
    so.log_severity_level = 3
    so.graph_optimization_level = ort_mod.GraphOptimizationLevel.ORT_ENABLE_BASIC
    so.intra_op_num_threads = 2 if use_cpu else 8
    so.inter_op_num_threads = 1
    so.enable_mem_pattern = False
    if use_cpu:
        so.enable_cpu_mem_arena = False
    so.add_session_config_entry("session.intra_op.allow_spinning", "0")
    avail = ort_mod.get_available_providers()
    providers = ["CPUExecutionProvider"] if use_cpu or "DmlExecutionProvider" not in avail else ["DmlExecutionProvider", "CPUExecutionProvider"]
    return ort_mod.InferenceSession(str(model_path), sess_options=so, providers=providers)


def _get_or_create_session_locked(spec: ModelSpec) -> ort.InferenceSession:
    sess = _SESSIONS.get(spec.filename)
    if sess is not None and not (_DML_DISABLED and "DmlExecutionProvider" in sess.get_providers()):
        return sess
    if sess is not None:
        _SESSIONS.pop(spec.filename, None)
    new_sess = _build_session(ensure_model(spec), force_cpu=_DML_DISABLED)
    _SESSIONS[spec.filename] = new_sess
    return new_sess


def _run_session(spec: ModelSpec, feed: dict[str, np.ndarray]) -> tuple[ort.InferenceSession, list[np.ndarray]]:
    """Run ONNX inference under unified lock; on DirectML DXGI_ERROR_DEVICE_RESET, release ALL D3D12 refs and fall back to CPU."""
    global _DML_DISABLED
    import gc

    with _INFER_LOCK:
        sess = _get_or_create_session_locked(spec)
        try:
            return sess, list(sess.run(None, feed))
        except Exception:
            _DML_DISABLED = True
            _SESSIONS.clear()
            del sess
            gc.collect()
            cpu_sess = _build_session(ensure_model(spec), force_cpu=True)
            _SESSIONS[spec.filename] = cpu_sess
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


def extract_clean_background(scene_rgba: Image.Image, fg_mask: np.ndarray | Image.Image) -> Image.Image:
    """Normalized Gaussian Convolution: seamless clean background without foreground ghosts or transparent-zero black fill."""
    rgba = np.asarray(scene_rgba.convert("RGBA"), dtype=np.float32)
    rgb, scene_a = rgba[:, :, :3], rgba[:, :, 3:4] / 255.0
    mask_img = fg_mask if isinstance(fg_mask, Image.Image) else Image.fromarray(np.asarray(fg_mask, dtype=np.uint8), mode="L")
    w_bg = (
        1.0
        - np.asarray(mask_img.resize(scene_rgba.size, Image.Resampling.BILINEAR).filter(ImageFilter.MaxFilter(5)), dtype=np.float32)[..., None]
        / 255.0
    ) * scene_a
    if float(w_bg.max()) < 1e-2:
        return Image.new("RGBA", scene_rgba.size, (244, 245, 247, 255))
    premul = np.concatenate([rgb * w_bg, w_bg * 255.0], axis=-1).round().clip(0, 255).astype(np.uint8)
    blurred = np.asarray(Image.fromarray(premul, mode="RGBA").filter(ImageFilter.GaussianBlur(max(24.0, max(scene_rgba.size) * 0.24))), dtype=np.float32)
    denom = blurred[:, :, 3:4] / 255.0
    neutral = np.array([244.0, 245.0, 247.0], dtype=np.float32)
    out_rgb = np.clip(np.round(np.where(denom > 1e-3, blurred[:, :, :3] / np.maximum(denom, 1e-3), neutral)), 0, 255).astype(np.uint8)
    return Image.fromarray(out_rgb, mode="RGB").convert("RGBA")
