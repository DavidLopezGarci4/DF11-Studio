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
    assert boot["version"] == "1.1.0" and "1736" in boot["clubs"]
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


def test_bridge_kit_preview_isolation_extract_bg_and_watcher_lifecycle(tmp_path: Path) -> None:
    from backend.services.kits import resolve_club_kit

    vault, out_dir, db = tmp_path / "vault_ro", tmp_path / "out_ok", tmp_path / "state.sqlite3"
    vault.mkdir(parents=True)
    bridge = StudioBridge(vault_dir=vault, export_dir=out_dir, db_path=db)

    with pytest.raises(ValueError):
        bridge.export_studio_card({"uid": "29184012"})

    bridge.upload_studio_image(_sample_png_data_url(), remove_bg=False, harmonize=False, params={"kitMode": "club", "clubId": "1736"})
    # Preview with custom pattern/secondary must NOT mutate SQLite until explicit export
    bridge.render_studio_preview({
        "removeBg": False, "harmonize": True, "kitMode": "club", "clubId": "1736",
        "customKitDirty": True, "customPrimary": "#112233", "customSecondary": "#AABBCC", "customPattern": "stripes",
    })
    assert resolve_club_kit("1736", db_path=db).tier == "seed"

    # Extract clean background directly from stored raw portrait (works for paste/drop/jump)
    ext = bridge.extract_studio_background({"removeBg": False, "harmonize": True})
    assert ext["cleanBgDataUrl"].startswith("data:image/png;base64,") and ext["previewDataUrl"].startswith("data:image/png;base64,")

    # Vault must never be writable as export target
    with pytest.raises(CapabilityError):
        bridge.export_studio_card({"uid": "29184012", "outDir": str(vault)})

    # Explicit export persists custom kit override to SQLite
    bridge.export_studio_card({
        "uid": "29184012", "kitMode": "club", "clubId": "1736",
        "customKitDirty": True, "customPrimary": "#112233", "customSecondary": "#AABBCC", "customPattern": "stripes",
    })
    saved_kit = resolve_club_kit("1736", db_path=db)
    assert saved_kit.tier == "custom" and saved_kit.pattern == "stripes" and saved_kit.secondary.upper() == "#AABBCC"

    # Re-toggling live watch stops prior watcher cleanly
    bridge.toggle_live_watch(True, {"applyClubKits": False, "harmonize": False})
    first_watcher = bridge._watcher
    bridge.toggle_live_watch(True, {"applyClubKits": True, "harmonize": True})
    assert first_watcher._stop.is_set()
    bridge.toggle_live_watch(False)
    assert bridge._watcher is None


def test_bridge_extract_bg_on_opaque_portrait_with_remove_bg_false_and_theme_pref(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import backend.services.vision as vision_mod

    calls = 0

    def _fake_birefnet(img: Image.Image) -> Image.Image:
        nonlocal calls
        calls += 1
        out = img.convert("RGBA").copy()
        alpha = Image.new("L", out.size, 0)
        alpha.paste(255, (70, 50, 150, 200))
        out.putalpha(alpha)
        return out

    monkeypatch.setattr(vision_mod, "remove_background_birefnet", _fake_birefnet)

    opaque = Image.new("RGBA", (220, 220), (40, 85, 190, 255))
    opaque.paste((185, 35, 35, 255), (70, 50, 150, 200))
    buf = io.BytesIO()
    opaque.save(buf, format="PNG")
    opaque_url = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")

    db = tmp_path / "prefs.sqlite3"
    bridge = StudioBridge(vault_dir=tmp_path / "v", export_dir=tmp_path / "o", db_path=db)
    up = bridge.upload_studio_image(opaque_url, remove_bg=False, harmonize=False)
    assert up["isPreCutout"] is False and calls == 0

    ext = bridge.extract_studio_background({"removeBg": False, "harmonize": False})
    assert calls == 1  # Cached across both mask extraction and _compose(removeBg=True)
    bg_img = Image.open(io.BytesIO(base64.b64decode(ext["cleanBgDataUrl"].split(",", 1)[1]))).convert("RGBA")
    cx_r, cx_g, cx_b, _ = bg_img.getpixel((110, 120))
    assert cx_b > 150 and cx_r < 80, f"Expected reconstructed blue wall, got {(cx_r, cx_g, cx_b)}"

    assert bridge.set_ui_theme("light")["theme"] == "light"
    reloaded = StudioBridge(vault_dir=tmp_path / "v", export_dir=tmp_path / "o", db_path=db)
    assert reloaded.get_bootstrap_state()["theme"] == "light"


def test_bridge_native_open_dialog_remembers_last_directory_and_choose_directory(tmp_path: Path) -> None:
    img_dir = tmp_path / "MyPortraits"
    img_dir.mkdir(parents=True)
    img_file = img_dir / "cr7.png"
    img_file.write_bytes(base64.b64decode(_sample_png_data_url().split(",", 1)[1]))

    bg_dir = tmp_path / "MyBackgrounds"
    bg_dir.mkdir(parents=True)
    bg_file = bg_dir / "stadium.png"
    bg_file.write_bytes(base64.b64decode(_sample_png_data_url().split(",", 1)[1]))

    db = tmp_path / "dialog_prefs.sqlite3"
    seen_calls: list[tuple[int, str, tuple[str, ...]]] = []

    class _FakeWin:
        def __init__(self, next_path: Path | None) -> None:
            self.next_path = next_path

        def create_file_dialog(
            self,
            dialog_type: int = 10,
            directory: str = "",
            allow_multiple: bool = False,
            save_filename: str = "",
            file_types: tuple[str, ...] = (),
        ) -> tuple[str, ...] | None:
            seen_calls.append((dialog_type, directory, tuple(file_types)))
            return (str(self.next_path),) if self.next_path else None

    bridge = StudioBridge(vault_dir=tmp_path / "v", export_dir=tmp_path / "o", db_path=db)
    bridge._attach_window(_FakeWin(img_file))

    res = bridge.pick_and_upload_studio_image(remove_bg=False, harmonize=True, extract_bg=False)
    assert res is not None and res["previewDataUrl"].startswith("data:image/png;base64,")
    assert seen_calls[-1][2] == ("Imágenes DF11 (*.png;*.jpg;*.jpeg;*.webp;*.avif)",)

    # Cancelled dialog returns None without erasing the remembered folder
    bridge._attach_window(_FakeWin(None))
    assert bridge.pick_and_upload_studio_image() is None

    # New instance reloads remembered portrait directory from SQLite app_prefs
    bridge2 = StudioBridge(vault_dir=tmp_path / "v", export_dir=tmp_path / "o", db_path=db)
    bridge2._attach_window(_FakeWin(img_file))
    bridge2.pick_and_upload_studio_image(remove_bg=False, harmonize=False)
    assert Path(seen_calls[-1][1]).resolve() == img_dir.resolve()

    # Custom background picker remembers its last folder too
    bridge2._attach_window(_FakeWin(bg_file))
    bg_res = bridge2.pick_and_upload_custom_background({"bgMode": "custom"})
    assert bg_res is not None and bg_res["previewDataUrl"].startswith("data:image/png;base64,")
    bridge2._attach_window(_FakeWin(bg_file))
    bridge2.pick_and_upload_custom_background({"bgMode": "custom"})
    assert Path(seen_calls[-1][1]).resolve() == bg_dir.resolve()


def test_bridge_modular_face_extractor_shirt_extractor_and_step_composer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import numpy as np
    import backend.services.vision as vision_mod

    def _fast_seg(im: Image.Image) -> np.ndarray:
        arr = np.asarray(im.convert("RGBA"))
        h, w = arr.shape[:2]
        probs = np.zeros((h, w, 6), dtype=np.float32)
        fg = arr[:, :, 3] > 20
        is_cloth = fg & (arr[:, :, 2] > 180)
        probs[:, :, 4] = np.where(is_cloth, 0.92, 0.02)
        probs[:, :, 3] = np.where(fg & ~is_cloth, 0.90, 0.02)
        probs[:, :, 0] = np.where(~fg, 0.96, 0.02)
        return probs

    monkeypatch.setattr(vision_mod, "segment_portrait_classes", _fast_seg)
    monkeypatch.setattr(vision_mod, "remove_background_birefnet", lambda im: im.convert("RGBA"))
    monkeypatch.setattr(vision_mod, "detect_face_pose", lambda _im, score_thresh=0.55: None)

    bridge = StudioBridge(
        vault_dir=tmp_path / "vault",
        export_dir=tmp_path / "export",
        db_path=tmp_path / "state.sqlite3",
        templates_dir=tmp_path / "tshirt_templates",
        raw_archive_dir=tmp_path / "raw_archive",
        extracted_faces_dir=tmp_path / "caras_extraidas",
        sample_faces_dir=tmp_path / "caras_prueba",
    )

    # 1. Shirt Extractor Tool: load -> preview with shoulderBoost -> save to tshirt_templates -> rename & bind club
    shirt_stage = bridge.load_raw_shirt_source(_sample_png_data_url(), file_name="BlancaClub.png")
    assert shirt_stage["cleanShirtDataUrl"].startswith("data:image/png;base64,")
    shirt_prev = bridge.preview_shirt_extraction({"symmetrizeShoulders": True, "shoulderBoost": 0.25})
    assert shirt_prev["cleanShirtDataUrl"].startswith("data:image/png;base64,")
    saved_tpl = bridge.save_shirt_template({"displayName": "Real Madrid Blanca", "clubId": "1736", "templateId": "RM_Blanca"})
    assert saved_tpl["savedTemplateId"] == "RM_Blanca" and len(saved_tpl["templates"]) == 1
    meta = bridge.update_shirt_template_meta("RM_Blanca", "Real Madrid Local", "1736")
    assert meta["templates"][0]["displayName"] == "Real Madrid Local"

    # 2. Face Extractor Tool: stage raw -> extract from wheel-crop -> save to face library -> security guard
    face_stage = bridge.load_raw_face_source(_sample_png_data_url(), file_name="Jugador1.png")
    assert "suggestedViewport" in face_stage
    ext_face = bridge.extract_face_from_crop({"zoom": 1.1, "panX": 2.0, "panY": -3.0, "templateId": "RM_Blanca"})
    aid = ext_face["headAssetId"]
    assert aid.startswith("head-") and ext_face["previewDataUrl"].startswith("data:image/png;base64,")
    saved_face = bridge.save_extracted_face(aid, "Delantero_Estrella")
    assert saved_face["faceId"] == "ext:Delantero_Estrella.png" and len(saved_face["faces"]) == 1

    with pytest.raises(ValueError):
        bridge.load_saved_face("ext:../evil.png")

    reloaded_face = bridge.load_saved_face("ext:Delantero_Estrella.png", template_id="RM_Blanca")
    assert reloaded_face["headAssetId"].startswith("head-")

    # 3. Step-by-Step Composer: render preview & atomic export
    mod_prev = bridge.render_modular_preview({
        "headAssetId": aid,
        "wearMode": "template",
        "templateId": "RM_Blanca",
        "bgMode": "white_df11",
        "scale": 1.0,
        "offsetX": 0,
        "offsetY": 0,
        "neckFill": 1.0,
        "harmonize": True,
    })
    assert mod_prev["previewDataUrl"].startswith("data:image/png;base64,")
    exp = bridge.export_modular_card({
        "uid": "r-909090",
        "fmt": "png",
        "updateConfigXml": True,
        "headAssetId": aid,
        "wearMode": "template",
        "templateId": "RM_Blanca",
        "bgMode": "white_df11",
    })
    assert Path(exp["savedPath"]).is_file() and (tmp_path / "export" / "config.xml").is_file()


def test_bridge_judgment_day_regressions_highres_modes_corrupt_files_and_caps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import numpy as np
    import backend.services.vision as vision_mod
    from backend.services.vision import FacePose

    def _fast_seg(im: Image.Image) -> np.ndarray:
        arr = np.asarray(im.convert("RGBA"))
        h, w = arr.shape[:2]
        probs = np.zeros((h, w, 6), dtype=np.float32)
        fg = arr[:, :, 3] > 20
        is_cloth = fg & (arr[:, :, 2] > 180)
        probs[:, :, 4] = np.where(is_cloth, 0.92, 0.02)
        probs[:, :, 3] = np.where(fg & ~is_cloth, 0.90, 0.02)
        probs[:, :, 0] = np.where(~fg, 0.96, 0.02)
        return probs

    def _scaled_pose(im: Image.Image, score_thresh: float = 0.55) -> FacePose:
        w, h = im.size
        cx, cy = w * 0.5, h * 0.36
        ipd = w * 0.19
        return FacePose(
            right_eye=(cx - ipd * 0.5, cy),
            left_eye=(cx + ipd * 0.5, cy),
            nose=(cx, cy + ipd * 0.45),
            eye_center=(cx, cy),
            ipd=ipd,
            yaw=0.0,
            bbox=(cx - ipd, cy - ipd, ipd * 2.0, ipd * 2.4),
        )

    monkeypatch.setattr(vision_mod, "segment_portrait_classes", _fast_seg)
    monkeypatch.setattr(vision_mod, "remove_background_birefnet", lambda im: im.convert("RGBA"))
    monkeypatch.setattr(vision_mod, "detect_face_pose", _scaled_pose)

    tpl_dir = tmp_path / "tshirt_templates"
    smp_dir = tmp_path / "caras_prueba"
    tpl_dir.mkdir(parents=True)
    smp_dir.mkdir(parents=True)

    # Corrupt files + uppercase .PNG + duplicate stem (.jpg + .png) must not crash listing or duplicate IDs
    (tpl_dir / "broken.png").write_bytes(b"not-a-valid-png")
    (smp_dir / "corrupt.png").write_bytes(b"corrupt")
    clean_shirt = Image.new("RGBA", (260, 310), (0, 0, 0, 0))
    clean_shirt.paste((30, 80, 220, 255), (25, 205, 235, 290))
    clean_shirt.save(tpl_dir / "DupKit.PNG", format="PNG")
    clean_shirt.convert("RGB").save(tpl_dir / "DupKit.jpg", format="JPEG")

    out_dir = tmp_path / "export"
    bridge = StudioBridge(
        vault_dir=tmp_path / "vault",
        export_dir=out_dir,
        db_path=tmp_path / "state.sqlite3",
        templates_dir=tpl_dir,
        raw_archive_dir=tmp_path / "raw_archive",
        extracted_faces_dir=tmp_path / "caras_extraidas",
        sample_faces_dir=smp_dir,
    )

    tpls = bridge.list_shirt_templates()
    assert [t["templateId"] for t in tpls] == ["DupKit"]
    assert bridge.list_saved_faces() == []

    # High-res 1200x1400 portrait without templateId must auto-fit cleanly (never raw 1:1 scale=1.0)
    hi = Image.new("RGBA", (1200, 1400), (0, 0, 0, 0))
    hi.paste((215, 170, 145, 255), (240, 60, 960, 1100))
    buf = io.BytesIO()
    hi.save(buf, format="PNG")
    hi_url = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")

    staged = bridge.load_raw_face_source(hi_url, file_name="HiResCut.png")
    ext = bridge.extract_face_from_crop({**staged["suggestedViewport"], "templateId": "", "wearMode": "none"})
    assert ext["autoFit"]["scale"] < 0.65

    # Pre-cutout portrait must refuse extract_studio_background instead of synthesizing pitch-black #000000
    with pytest.raises(ValueError):
        bridge.extract_studio_background({"modular": True, "headAssetId": ext["headAssetId"]})

    # Switching from wearMode='none' to 'club' with the same autoFit scale keeps canonical DF11 head size
    club_prev = bridge.render_modular_preview({
        "headAssetId": ext["headAssetId"],
        "wearMode": "club",
        "clubId": "1736",
        "scale": ext["autoFit"]["scale"],
        "offsetX": ext["autoFit"]["offsetX"],
        "offsetY": ext["autoFit"]["offsetY"],
        "bgMode": "transparent",
    })
    club_im = Image.open(io.BytesIO(base64.b64decode(club_prev["previewDataUrl"].split(",", 1)[1]))).convert("RGBA")
    assert np.asarray(club_im)[95:160, 95:165, 3].mean() > 180.0

    # Missing/evicted headAssetId must raise instead of exporting a blank/headless card
    with pytest.raises(ValueError):
        bridge.export_modular_card({"uid": "29184012", "headAssetId": "head-99999", "wearMode": "club"})

    # Vault directory must never be allowed to equal export directory
    class _SameDirWin:
        def create_file_dialog(self, *args: object, **kwargs: object) -> tuple[str, ...]:
            return (str(out_dir),)

    bridge._attach_window(_SameDirWin())
    with pytest.raises(CapabilityError):
        bridge.choose_directory("vault")


