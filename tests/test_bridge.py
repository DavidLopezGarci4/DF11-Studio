"""RED->GREEN deterministic tests for zero-port pywebview StudioBridge IPC and capability handles."""

from __future__ import annotations

import base64, io
from pathlib import Path
import pytest
from PIL import Image
from backend.bridge import CapabilityError, StudioBridge


def _sample_png_data_url() -> str:
    img = Image.new("RGBA", (220, 220), (0, 0, 0, 0))
    img.paste((35, 110, 215, 255), (45, 40, 175, 220))
    img.paste((215, 170, 145, 255), (75, 35, 145, 125))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def test_bridge_bootstrap_and_capability_guard_blocks_unapproved_paths(tmp_path: Path) -> None:
    bridge = StudioBridge(vault_dir=tmp_path / "vault", export_dir=tmp_path / "approved_out", db_path=tmp_path / "state.sqlite3")
    boot = bridge.get_bootstrap_state()
    assert boot["version"] == "1.0.0" and "1736" in boot["clubs"]
    bridge.upload_studio_image(_sample_png_data_url(), remove_bg=False, harmonize=True, extract_bg=False)
    with pytest.raises(CapabilityError):
        bridge.export_studio_card({"uid": "29184012", "fmt": "png", "outDir": str(tmp_path / "unapproved_evil")})


def test_bridge_studio_upload_render_and_export_with_config_xml(tmp_path: Path) -> None:
    out_dir = tmp_path / "approved_out"
    bridge = StudioBridge(vault_dir=tmp_path / "vault", export_dir=out_dir, db_path=tmp_path / "state.sqlite3")
    up = bridge.upload_studio_image(_sample_png_data_url(), remove_bg=False, harmonize=True, extract_bg=True)
    assert up["isPreCutout"] is True and up["previewDataUrl"].startswith("data:image/png;base64,") and up["cleanBgDataUrl"].startswith("data:image/png;base64,")
    prev = bridge.render_studio_preview({"kitMode": "club", "clubId": "1736", "bgMode": "white_df11", "scale": 1.0, "offsetX": 0, "offsetY": 0})
    assert prev["previewDataUrl"].startswith("data:image/png;base64,")
    exp = bridge.export_studio_card({"uid": "r-2002049102", "fmt": "png", "updateConfigXml": True})
    assert Path(exp["savedPath"]).is_file() and (out_dir / "config.xml").is_file()


def test_bridge_loads_regen_from_vault_into_studio(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir(parents=True)
    (vault / "p1.png").write_bytes(base64.b64decode(_sample_png_data_url().split(",", 1)[1]))
    (vault / "config.xml").write_text('<record><list id="maps"><record from="p1" to="graphics/pictures/person/r-7788/portrait"/></list></record>', encoding="utf-8")
    bridge = StudioBridge(vault_dir=vault, export_dir=tmp_path / "out", db_path=tmp_path / "state.sqlite3")
    assert bridge.scan_vault_summary()["totalFound"] == 1
    jumped = bridge.load_regen_into_studio("r-7788")
    assert jumped["uid"] == "r-7788" and jumped["previewDataUrl"].startswith("data:image/png;base64,")
