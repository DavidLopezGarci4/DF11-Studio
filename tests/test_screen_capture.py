"""RED->GREEN tests for native PerMonitorV2 screen clipper, DRM/low-res guards, and independent bridge routing."""

from __future__ import annotations

import io
import subprocess
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from PIL import Image, ImageDraw

from backend.bridge import CapabilityError, StudioBridge
from backend.core.paths import WORKSPACE_ROOT


def _encode_png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_torso_only_png(w: int = 300, h: int = 190) -> bytes:
    im = Image.new("RGBA", (w, h), (245, 247, 250, 255))
    d = ImageDraw.Draw(im)
    # Crimson shirt filling almost the entire snipped torso rectangle (collar at y=14)
    d.polygon(
        [(20, 48), (95, 14), (150, 52), (205, 14), (280, 48), (290, h - 4), (10, h - 4)],
        fill=(200, 24, 38, 255),
    )
    # White crest on upper chest (y=58..86) that would be guillotined if placed above Y=162
    d.rectangle([185, 58, 212, 86], fill=(250, 250, 252, 255))
    return _encode_png(im)


def test_screen_clip_worker_stdout_self_test_and_df11_aspect_math() -> None:
    from backend.core.screen_capture import get_screen_clipper_cmd
    from backend.core.screen_clip_worker import _compute_selection_rect

    cmd = [*get_screen_clipper_cmd(), "--self-test"]
    proc = subprocess.run(cmd, cwd=str(WORKSPACE_ROOT), capture_output=True, timeout=10, check=False)
    assert proc.returncode == 0, f"--self-test failed: {proc.stderr.decode('utf-8', errors='replace')}"
    assert proc.stdout[:8] == b"\x89PNG\r\n\x1a\n", "--self-test must emit raw PNG bytes on stdout"
    with Image.open(io.BytesIO(proc.stdout)) as im:
        assert im.size == (64, 64)

    # Multi-monitor negative coordinates + Shift 260:310 DF11 aspect ratio lock
    rx, ry, rw, rh = _compute_selection_rect((-1600, -120), (-1340, 140), lock_df11_aspect=True)
    assert rx == -1600 and ry == -120
    assert abs((rw / rh) - (260.0 / 310.0)) < 0.01


def test_drm_black_frame_detector_distinguishes_drm_from_black_kit() -> None:
    from backend.core.screen_capture import detect_drm_black_frame

    # Hardware DRM blackout (video range 16,16,16 with thin player border)
    drm_arr = np.full((220, 200, 4), (12, 12, 12, 255), dtype=np.uint8)
    drm_arr[:6, :] = (220, 220, 220, 255)  # Outer browser chrome ignored by inner 80% ROI
    assert detect_drm_black_frame(Image.fromarray(drm_arr, mode="RGBA")) is True

    # Real black football kit with crest/stripes and normal contrast -> NOT flagged as DRM
    kit_arr = np.full((220, 200, 4), (18, 20, 24, 255), dtype=np.uint8)
    kit_arr[40:120, 65:135] = (215, 175, 145, 255)  # Skin/crest variance
    assert detect_drm_black_frame(Image.fromarray(kit_arr, mode="RGBA")) is False


def test_bridge_capture_cancellation_and_independent_targets(tmp_path: Path, monkeypatch) -> None:
    import backend.core.screen_capture as sc_mod
    import backend.services.vision as vision_mod

    bridge = StudioBridge(
        vault_dir=tmp_path / "vault",
        export_dir=tmp_path / "exports",
        db_path=tmp_path / "state.sqlite3",
        templates_dir=tmp_path / "templates",
        raw_archive_dir=tmp_path / "raw_shirts",
        extracted_faces_dir=tmp_path / "faces",
        sample_faces_dir=tmp_path / "samples",
    )

    # 1. User presses Esc -> capture returns None -> bridge reports cancelled=True cleanly
    monkeypatch.setattr(sc_mod, "capture_screen_png", lambda hwnd=None: None)
    cancelled = bridge.capture_screen_region("direct_photo")
    assert cancelled == {"cancelled": True}

    # 2. Tiny 110x130 screenshot routed to 'direct_photo' (0% AI) -> flags lowResWarning=True
    tiny_im = Image.new("RGBA", (110, 130), (45, 95, 175, 255))
    tiny_png = _encode_png(tiny_im)
    monkeypatch.setattr(
        sc_mod,
        "capture_screen_png",
        lambda hwnd=None: sc_mod.ScreenCaptureResult(
            png_bytes=tiny_png, width=110, height=130, drm_black_warning=False, low_res_warning=True
        ),
    )
    direct_out = bridge.capture_screen_region("direct_photo")
    assert direct_out["cancelled"] is False
    assert direct_out["target"] == "direct_photo"
    assert direct_out["lowResWarning"] is True
    assert direct_out["directPhotoId"].startswith("direct-")
    assert direct_out["previewDataUrl"].startswith("data:image/png;base64,")

    # 3. Screenshot routed independently to 'raw_face' -> stages face without auto-extracting
    face_out = bridge.capture_screen_region("raw_face")
    assert face_out["cancelled"] is False
    assert face_out["target"] == "raw_face"
    assert face_out["lowResWarning"] is True
    assert face_out["rawDataUrl"].startswith("data:image/png;base64,")
    assert "suggestedViewport" in face_out

    # 4. Headless torso screenshot routed independently to 'raw_shirt' -> auto-pans panY > 0 below Y=162!
    torso_png = _make_torso_only_png(300, 190)

    def _fake_seg(im: Image.Image) -> np.ndarray:
        arr = np.asarray(im.convert("RGBA"))
        h, w = arr.shape[:2]
        probs = np.zeros((h, w, 6), dtype=np.float32)
        is_red_shirt = (arr[:, :, 0] > 150) & (arr[:, :, 1] < 80)
        is_crest = (arr[:, :, 0] > 235) & (arr[:, :, 1] > 235) & (arr[:, :, 2] > 235) & (
            np.arange(h)[:, None] > 170 * (h // 310 if h >= 310 else 1)
        )
        cloth = is_red_shirt | is_crest
        probs[:, :, 4] = np.where(cloth, 0.96, 0.02)
        probs[:, :, 0] = 1.0 - probs[:, :, 4]
        return probs

    monkeypatch.setattr(vision_mod, "detect_face_pose", lambda im, score_thresh=0.55: None)
    monkeypatch.setattr(vision_mod, "segment_portrait_classes", _fake_seg)
    monkeypatch.setattr(vision_mod, "remove_background_birefnet", lambda im: im.convert("RGBA"))
    monkeypatch.setattr(
        sc_mod,
        "capture_screen_png",
        lambda hwnd=None: sc_mod.ScreenCaptureResult(
            png_bytes=torso_png, width=300, height=190, drm_black_warning=False, low_res_warning=False
        ),
    )

    shirt_out = bridge.capture_screen_region("raw_shirt")
    assert shirt_out["cancelled"] is False
    assert shirt_out["target"] == "raw_shirt"
    vp = shirt_out["suggestedViewport"]
    assert vp["panY"] > 25.0, f"Headless torso capture must auto-pan below Y=162, got {vp}"

    prev = bridge.preview_shirt_extraction(
        {"shirtSourceId": shirt_out["shirtSourceId"], **vp, "symmetrizeShoulders": False}
    )
    assert prev["cleanShirtDataUrl"].startswith("data:image/png;base64,")
    assert prev["collarWidth"] >= 20


def test_capture_save_png_blocks_vault_overlap_and_saves_clean_png(tmp_path: Path, monkeypatch) -> None:
    import backend.core.screen_capture as sc_mod

    vault = tmp_path / "vault"
    vault.mkdir(parents=True)
    safe_dir = tmp_path / "user_saves"
    safe_dir.mkdir(parents=True)

    bridge = StudioBridge(
        vault_dir=vault,
        export_dir=tmp_path / "exports",
        db_path=tmp_path / "state.sqlite3",
    )

    png_bytes = _encode_png(Image.new("RGBA", (180, 210), (20, 140, 90, 255)))
    monkeypatch.setattr(
        sc_mod,
        "capture_screen_png",
        lambda hwnd=None: sc_mod.ScreenCaptureResult(
            png_bytes=png_bytes, width=180, height=210, drm_black_warning=False, low_res_warning=False
        ),
    )

    class _FakeWindow:
        def __init__(self, target_file: Path | None) -> None:
            self._target_file = target_file

        def create_file_dialog(self, *_args: Any, **_kwargs: Any) -> Any:
            return str(self._target_file) if self._target_file else None

    # Attempting to save inside read-only NG_Regens vault MUST raise CapabilityError
    bridge._attach_window(_FakeWindow(vault / "illegal.png"))
    with pytest.raises(CapabilityError):
        bridge.capture_screen_region("save_png")

    # Saving to user-chosen safe path via native SAVE_DIALOG succeeds without polluting _approved_dirs
    dst = safe_dir / "mi_recorte.png"
    bridge._attach_window(_FakeWindow(dst))
    saved = bridge.capture_screen_region("save_png")
    assert saved["cancelled"] is False
    assert saved["target"] == "save_png"
    assert Path(saved["savedPath"]) == dst.resolve()
    assert dst.is_file() and dst.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    assert safe_dir.resolve() not in bridge._approved_dirs


def test_global_capture_hotkey_toggle_lifecycle(tmp_path: Path) -> None:
    bridge = StudioBridge(
        vault_dir=tmp_path / "vault",
        export_dir=tmp_path / "exports",
        db_path=tmp_path / "state.sqlite3",
    )
    off_res = bridge.toggle_capture_hotkey(False)
    assert off_res == {"hotkeyEnabled": False}
