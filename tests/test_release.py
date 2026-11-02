"""Release gate tests for DF11FaceStudio.exe PE binary, cold-start budget, and bundle isolation."""

from __future__ import annotations

import gzip
import sys
import time
from pathlib import Path

from backend.core.paths import WORKSPACE_ROOT


def test_native_launcher_exe_and_pe_header() -> None:
    exe = WORKSPACE_ROOT / "DF11FaceStudio.exe"
    assert exe.is_file(), "DF11FaceStudio.exe must be compiled at workspace root"
    raw = exe.read_bytes()
    assert raw[:2] == b"MZ", "DF11FaceStudio.exe must have a valid Win32 PE MZ header"
    assert 4_096 <= len(raw) <= 262_144, "Launcher binary must remain lightweight (< 256 KB)"


def test_frontend_dist_and_lazy_graph_gzip_budget() -> None:
    dist_dir = WORKSPACE_ROOT / "frontend" / "dist"
    index_html = dist_dir / "index.html"
    assert index_html.is_file(), "Production frontend/dist/index.html must exist"
    text = index_html.read_text(encoding="utf-8")
    assert "./assets/" in text

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
