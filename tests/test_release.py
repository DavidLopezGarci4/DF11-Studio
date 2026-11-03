"""Release gate tests for DF11FaceStudio.exe PE binary, cold-start budget, and bundle isolation."""

from __future__ import annotations

import gzip
import json
import sys
import time
from pathlib import Path

from backend import __version__
from backend.core.paths import WORKSPACE_ROOT


def test_native_launcher_exe_and_pe_header() -> None:
    exe = WORKSPACE_ROOT / "DF11FaceStudio.exe"
    assert exe.is_file(), "DF11FaceStudio.exe must be compiled at workspace root"
    raw = exe.read_bytes()
    assert raw[:2] == b"MZ", "DF11FaceStudio.exe must have a valid Win32 PE MZ header"
    assert 4_096 <= len(raw) <= 262_144, "Launcher binary must remain lightweight (< 256 KB)"
    utf16_ver = f"{__version__}.0".encode("utf-16-le")
    assert utf16_ver in raw, f"DF11FaceStudio.exe PE version resource must match {__version__}.0"


def test_frontend_dist_and_lazy_graph_gzip_budget() -> None:
    dist_dir = WORKSPACE_ROOT / "frontend" / "dist"
    index_html = dist_dir / "index.html"
    assert index_html.is_file(), "Production frontend/dist/index.html must exist"
    text = index_html.read_text(encoding="utf-8")
    assert "./assets/" in text

    changelog_cfg = json.loads(
        (WORKSPACE_ROOT / "frontend" / "src" / "config" / "changelog.user.json").read_text(encoding="utf-8")
    )
    assert changelog_cfg["currentVersion"] == __version__

    js_concat = "\n".join(p.read_text(encoding="utf-8") for p in (dist_dir / "assets").glob("*.js"))
    assert __version__ in js_concat, f"frontend/dist JS bundle must embed current version {__version__}"
    assert "shirt-extractor-canvas" in js_concat, "frontend/dist JS bundle must embed ShirtExtractorTool canvas"

    graph_chunks = list((dist_dir / "assets").glob("AppArchitectureGraph-*.js"))
    assert len(graph_chunks) == 1, "AppArchitectureGraph must be isolated in its own lazy chunk"
    gz_size = len(gzip.compress(graph_chunks[0].read_bytes()))
    assert gz_size < 10_240, f"AppArchitectureGraph gzip size ({gz_size} B) must stay < 10 KB"


def test_cold_start_bridge_import_budget_excludes_onnx() -> None:
    # Verify StudioBridge cold instantiation stays < 0.5s and does not eagerly import onnxruntime
    saved_ort = sys.modules.pop("onnxruntime", None)
    try:
        t0 = time.perf_counter()
        from backend.bridge import StudioBridge

        bridge = StudioBridge()
        elapsed = time.perf_counter() - t0
        assert bridge is not None
        assert elapsed < 0.5, f"Cold StudioBridge instantiation took {elapsed:.3f}s (> 0.5s)"
        assert "onnxruntime" not in sys.modules, "onnxruntime must remain lazily imported until warmup/inference"
    finally:
        if saved_ort is not None:
            sys.modules["onnxruntime"] = saved_ort


def test_desktop_launcher_preserves_stable_webview_origin_and_storage() -> None:
    src = (WORKSPACE_ROOT / "run_desktop.py").read_text(encoding="utf-8")
    assert "private_mode=False" in src
    assert "storage_path=str(profile_dir)" in src
    assert "_pick_ephemeral_port" not in src and "http_port=" not in src
