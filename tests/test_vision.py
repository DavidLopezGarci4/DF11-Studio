"""RED->GREEN deterministic + DirectML tests for backend.services.vision."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from backend.services.vision import (
    CLASS_BODY_SKIN,
    CLASS_CLOTHES,
    CLASS_FACE_SKIN,
    CLASS_HAIR,
    ModelIntegrityError,
    ModelSpec,
    detect_face_pose,
    ensure_model,
    extract_clean_background,
    harmonize_df11_studio_grade,
    remove_background_birefnet,
    segment_portrait_classes,
)

SAMPLE_DF11 = Path(
    r"C:\Users\dace8\.gemini\antigravity\brain\dfcb63b5-d461-4041-9a3f-3dfd39556fdf\.user_uploaded\media_1793642363145_ab407598.png"
)


def test_sha256_guard_rejects_tampered_download_and_removes_part(tmp_path: Path) -> None:
    spec = ModelSpec(
        filename="tiny_test.onnx",
        url="https://example.invalid/tiny_test.onnx",
        sha256="0" * 64,
    )
    with pytest.raises(ModelIntegrityError):
        ensure_model(spec, models_dir=tmp_path, fetcher=lambda _url: b"corrupted-weights")
    assert not (tmp_path / "tiny_test.onnx").exists()
    assert not list(tmp_path.glob("*.part"))


def test_yunet_detects_eyes_ipd_and_frontal_yaw() -> None:
    img = Image.open(SAMPLE_DF11).convert("RGBA")
    pose = detect_face_pose(img)
    assert pose is not None
    assert 85.0 <= pose.eye_center[1] <= 135.0
    assert 105.0 <= pose.eye_center[0] <= 155.0
    assert 28.0 <= pose.ipd <= 65.0
    assert abs(pose.yaw) < 0.25


def test_selfie_multiclass_separates_hair_face_neck_and_clothes() -> None:
    img = Image.open(SAMPLE_DF11).convert("RGBA")
    seg = segment_portrait_classes(img)
    assert seg.shape == (img.height, img.width, 6)
    cls = seg.argmax(axis=-1)
    assert int((cls[25:65, 90:170] == CLASS_HAIR).sum()) > 200
    assert int((cls[95:165, 95:165] == CLASS_FACE_SKIN).sum()) > 500
    assert int((cls[175:225, 95:165] == CLASS_BODY_SKIN).sum()) > 150
    assert int((cls[235:290, 50:210] == CLASS_CLOTHES).sum()) > 2000


def test_birefnet_removes_background_with_clean_alpha() -> None:
    sample = Image.open(SAMPLE_DF11).convert("RGB")
    # Crop inner portrait (without transparent DF11 border) to simulate a raw uploaded photo
    raw_photo = sample.crop((22, 20, 238, 290)).convert("RGBA")
    cutout = remove_background_birefnet(raw_photo)
    alpha = np.asarray(cutout.getchannel("A"), dtype=np.uint8)
    assert int(alpha[5, 5]) < 25 and int(alpha[5, -6]) < 25
    assert int(alpha[110, 108]) > 240


def test_df11_studio_grade_harmonizes_dark_cast_preserving_alpha() -> None:
    arr = np.zeros((120, 120, 4), dtype=np.uint8)
    arr[20:100, 20:100] = (95, 75, 45, 255)  # Underexposed warm-tinted skin patch
    graded = harmonize_df11_studio_grade(Image.fromarray(arr, mode="RGBA"))
    out = np.asarray(graded, dtype=np.uint8)
    assert int(out[0, 0, 3]) == 0
    assert int(out[60, 60, 3]) == 255
    assert float(out[60, 60, :3].mean()) > float(arr[60, 60, :3].mean())


def test_extract_clean_background_gaussian_fills_foreground_hole() -> None:
    scene = np.zeros((200, 160, 4), dtype=np.uint8)
    scene[:, :] = (40, 85, 190, 255)  # Clean blue studio wall
    fg_mask = np.zeros((200, 160), dtype=np.uint8)
    scene[50:160, 45:115] = (250, 20, 20, 255)  # Bright red person in foreground
    fg_mask[50:160, 45:115] = 255

    clean_bg = extract_clean_background(Image.fromarray(scene, mode="RGBA"), fg_mask)
    bg_arr = np.asarray(clean_bg, dtype=np.uint8)
    r, g, b, a = bg_arr[105, 80]  # Center where red person stood
    assert a == 255 and b > 170 and r < 60
