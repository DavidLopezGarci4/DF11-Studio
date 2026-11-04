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
    assert boot["version"] == "1.5.0" and "1736" in boot["clubs"] and "1744" in boot["clubs"]
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

    # 1. Shirt Extractor Tool: stage raw on canvas -> frame (zoom/pan) -> extract on click -> save -> rename & bind club
    shirt_stage = bridge.load_raw_shirt_source(_sample_png_data_url(), file_name="BlancaClub.png")
    assert shirt_stage["rawDataUrl"].startswith("data:image/png;base64,")
    assert "cleanShirtDataUrl" not in shirt_stage
    assert shirt_stage["width"] == 220 and shirt_stage["height"] == 220
    assert shirt_stage["suggestedViewport"] == {"zoom": 1.0, "panX": 0.0, "panY": 0.0}
    shirt_prev = bridge.preview_shirt_extraction(
        {"zoom": 0.92, "panX": 4.0, "panY": 6.0, "symmetrizeShoulders": True, "shoulderBoost": 0.25}
    )
    assert shirt_prev["cleanShirtDataUrl"].startswith("data:image/png;base64,")
    saved_tpl = bridge.save_shirt_template(
        {
            "displayName": "Real Madrid Blanca",
            "clubId": "1736",
            "templateId": "RM_Blanca",
            "zoom": 0.92,
            "panX": 4.0,
            "panY": 6.0,
            "symmetrizeShoulders": True,
            "shoulderBoost": 0.25,
        }
    )
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


def test_shirt_extractor_opaque_pan_eviction_and_df11_bevel_signature(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import numpy as np
    import backend.services.vision as vision_mod
    from backend.core.compositor import render_df11_card
    from backend.services.templates import _frame_to_df11_stage, _has_df11_outer_ring

    # 1. DF11 outer-ring signature: True on genuine DF11 cards, False on opaque photos & clean cutouts
    df11_card = render_df11_card(None, bg_mode="white_df11")
    assert _has_df11_outer_ring(df11_card) is True
    assert _has_df11_outer_ring(Image.new("RGBA", (260, 310), (245, 245, 245, 255))) is False
    assert _has_df11_outer_ring(Image.new("RGBA", (260, 310), (0, 0, 0, 0))) is False

    # 2. 1:1 scale parity on 1536x1536 image at zoom=0.20 (52px wide, not clamped to 77px)
    big_stage = _frame_to_df11_stage(Image.new("RGBA", (1536, 1536), (30, 90, 200, 255)), zoom=0.20)
    big_a = np.asarray(big_stage)[:, :, 3]
    xs_nonzero = np.where(big_a.max(axis=0) > 0)[0]
    assert 50 <= int(xs_nonzero[-1] - xs_nonzero[0] + 1) <= 54

    # 3. Opaque RGB jersey photo panned downward (y0 >= 140) MUST invoke BiRefNet and strip solid gray wall
    biref_calls = {"n": 0}

    def _biref_strip_gray(im: Image.Image) -> Image.Image:
        biref_calls["n"] += 1
        arr = np.asarray(im.convert("RGBA")).copy()
        is_blue_jersey = (arr[:, :, 2] > 170) & (arr[:, :, 0] < 80)
        arr[:, :, 3] = np.where(is_blue_jersey, 255, 0)
        return Image.fromarray(arr, mode="RGBA")

    def _seg_jersey(im: Image.Image) -> np.ndarray:
        arr = np.asarray(im.convert("RGBA"))
        probs = np.zeros((arr.shape[0], arr.shape[1], 6), dtype=np.float32)
        is_blue_jersey = (arr[:, :, 2] > 170) & (arr[:, :, 0] < 80)
        probs[:, :, 4] = np.where(is_blue_jersey, 0.94, 0.02)
        probs[:, :, 0] = np.where(~is_blue_jersey, 0.94, 0.02)
        return probs

    monkeypatch.setattr(vision_mod, "remove_background_birefnet", _biref_strip_gray)
    monkeypatch.setattr(vision_mod, "segment_portrait_classes", _seg_jersey)

    opaque_src = Image.new("RGB", (500, 400), (200, 200, 200))
    opaque_src.paste((25, 95, 220), (120, 90, 380, 390))
    buf = io.BytesIO()
    opaque_src.save(buf, format="JPEG", quality=95)
    jpg_url = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")

    bridge = StudioBridge(
        vault_dir=tmp_path / "vault",
        export_dir=tmp_path / "export",
        db_path=tmp_path / "state.sqlite3",
        templates_dir=tmp_path / "tshirt_templates",
        raw_archive_dir=tmp_path / "raw_archive",
        extracted_faces_dir=tmp_path / "caras_extraidas",
        sample_faces_dir=tmp_path / "caras_prueba",
    )

    staged = bridge.load_raw_shirt_source(jpg_url, file_name="CamisetaAzul.jpg")
    assert biref_calls["n"] == 0
    prev = bridge.preview_shirt_extraction(
        {"shirtSourceId": staged["shirtSourceId"], "zoom": 1.0, "panX": 0.0, "panY": 95.0}
    )
    assert biref_calls["n"] == 1
    clean_im = Image.open(io.BytesIO(base64.b64decode(prev["cleanShirtDataUrl"].split(",", 1)[1]))).convert("RGBA")
    clean_arr = np.asarray(clean_im)
    # Gray wall outside blue shirt at (25, 220) must be transparent; center shirt at (130, 240) must be opaque
    assert int(clean_arr[220, 25, 3]) == 0
    assert int(clean_arr[240, 130, 3]) > 240

    saved = bridge.save_shirt_template(
        {
            "shirtSourceId": staged["shirtSourceId"],
            "displayName": "Azul_Local",
            "templateId": "Azul_Local",
            "zoom": 1.0,
            "panX": 0.0,
            "panY": 95.0,
        }
    )
    assert saved["savedTemplateId"] == "Azul_Local"
    # Raw JPEG archive preserves .jpg suffix instead of hardcoding .png
    assert any(p.suffix == ".jpg" for p in (tmp_path / "raw_archive").iterdir())

    # 4. Evicted/unknown shirtSourceId must raise ValueError instead of substituting another shirt
    with pytest.raises(ValueError, match="memoria"):
        bridge.save_shirt_template({"shirtSourceId": "shirt-src-99999", "displayName": "Wrong"})

    # 5. Off-canvas empty shirt extraction must raise ValueError instead of saving a blank PNG
    with pytest.raises(ValueError, match="camiseta"):
        bridge.preview_shirt_extraction(
            {"shirtSourceId": staged["shirtSourceId"], "zoom": 0.5, "panX": 0.0, "panY": -220.0}
        )


def test_v120_custom_clubs_multi_season_templates_deletion_and_legacy_migration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sqlite3
    import numpy as np
    import backend.services.vision as vision_mod
    from backend.services.templates import CollarProfile, get_club_shirt_template, sanitize_shirt_template_rgba

    def _fast_seg(im: Image.Image) -> np.ndarray:
        arr = np.asarray(im.convert("RGBA"))
        probs = np.zeros((arr.shape[0], arr.shape[1], 6), dtype=np.float32)
        fg = (arr[:, :, 3] > 20) & ~((arr[:, :, 0] > 245) & (arr[:, :, 1] > 245) & (arr[:, :, 2] > 245))
        probs[:, :, 4] = np.where(fg, 0.94, 0.02)
        probs[:, :, 0] = np.where(~fg, 0.94, 0.02)
        return probs

    def _fast_biref(im: Image.Image) -> Image.Image:
        arr = np.asarray(im.convert("RGBA")).copy()
        is_bg = (arr[:, :, 0] > 245) & (arr[:, :, 1] > 245) & (arr[:, :, 2] > 245)
        arr[:, :, 3] = np.where(is_bg, 0, arr[:, :, 3])
        return Image.fromarray(arr, mode="RGBA")

    monkeypatch.setattr(vision_mod, "segment_portrait_classes", _fast_seg)
    monkeypatch.setattr(vision_mod, "remove_background_birefnet", _fast_biref)

    # 1. Shoulder color-coherence: dark asymmetric sleeves on white wall must NOT mirror white wall above lower sleeve
    asym = Image.new("RGBA", (260, 310), (252, 252, 250, 255))
    asym.paste((22, 24, 28, 255), (20, 215, 130, 292))   # Left dark shoulder high (y=215)
    asym.paste((22, 24, 28, 255), (130, 236, 240, 292))  # Right dark shoulder lower (y=236)
    clean_asym = sanitize_shirt_template_rgba(asym, symmetrize_shoulders=True, detail_crispness=0.5)
    asym_arr = np.asarray(clean_asym)
    assert int(asym_arr[224, 225, 3]) == 0, "White background above lower dark right sleeve must stay transparent"
    assert int(asym_arr[250, 225, 3]) > 240

    # 2. Legacy 8-column v1.1.0 SQLite migration + single-active-per-club invariant
    db = tmp_path / "legacy_state.sqlite3"
    tpl_dir = tmp_path / "tshirt_templates"
    tpl_dir.mkdir(parents=True)
    for tid_legacy in ("Barca_Old1", "Barca_Old2"):
        im_leg = Image.new("RGBA", (260, 310), (0, 0, 0, 0))
        im_leg.paste((0, 77, 152, 255), (25, 205, 235, 290))
        im_leg.save(tpl_dir / f"{tid_legacy}.png", format="PNG")
    dummy_collar = CollarProfile((90, 198), (170, 198), (130, 222), 80, tuple([198] * 260)).to_json()
    raw_conn = sqlite3.connect(str(db))
    raw_conn.execute(
        "CREATE TABLE shirt_templates (template_id TEXT PRIMARY KEY, filename TEXT NOT NULL, display_name TEXT NOT NULL, "
        "club_id TEXT NOT NULL DEFAULT '', sha256 TEXT NOT NULL, mtime_ns INTEGER NOT NULL, size INTEGER NOT NULL, collar_json TEXT NOT NULL)"
    )
    for idx_l, tid_legacy in enumerate(("Barca_Old1", "Barca_Old2")):
        st_l = (tpl_dir / f"{tid_legacy}.png").stat()
        raw_conn.execute(
            "INSERT INTO shirt_templates VALUES (?, ?, ?, '1708', 'abc', ?, ?, ?)",
            (tid_legacy, f"{tid_legacy}.png", tid_legacy, st_l.st_mtime_ns + idx_l, st_l.st_size, dummy_collar),
        )
    raw_conn.commit()
    raw_conn.close()

    bridge = StudioBridge(
        vault_dir=tmp_path / "vault",
        export_dir=tmp_path / "export",
        db_path=db,
        templates_dir=tpl_dir,
        raw_archive_dir=tmp_path / "raw_archive",
        extracted_faces_dir=tmp_path / "caras_extraidas",
        sample_faces_dir=tmp_path / "caras_prueba",
    )
    migrated = bridge.list_shirt_templates()
    barca_active = [t for t in migrated if t["clubId"] == "1708" and t["isActiveForClub"]]
    assert len(barca_active) == 1

    # 3. Custom #ClubID + FM Graphics config.xml club importer
    with pytest.raises(ValueError):
        bridge.upsert_custom_club("invalid-abc", "Club Malo")
    custom_res = bridge.upsert_custom_club("#2000554433", "AD Alcorcón B")
    assert custom_res["clubs"]["2000554433"]["name"] == "AD Alcorcón B"
    assert bridge.get_bootstrap_state()["clubs"]["2000554433"]["name"] == "AD Alcorcón B"

    gfx_dir = tmp_path / "fm_graphics" / "logos"
    gfx_dir.mkdir(parents=True)
    Image.new("RGBA", (32, 32), (200, 10, 20, 255)).save(gfx_dir / "998877.png", format="PNG")
    (gfx_dir / "config.xml").write_text(
        '<record><list id="maps"><record from="998877" to="graphics/pictures/club/998877/logo"/></list></record>',
        encoding="utf-8",
    )

    class _GfxWin:
        def create_file_dialog(self, *args: object, **kwargs: object) -> tuple[str, ...]:
            return (str(gfx_dir.parent),)

    bridge._attach_window(_GfxWin())
    imp = bridge.import_clubs_from_fm_graphics()
    assert imp is not None and imp["importedCount"] == 1 and "998877" in imp["clubs"]

    # 4. Multi-season club shirts, switching active titular, auto-promotion on delete, and replacePreviousForClub
    shirt_buf = io.BytesIO()
    asym.save(shirt_buf, format="PNG")
    shirt_url = "data:image/png;base64," + base64.b64encode(shirt_buf.getvalue()).decode("ascii")
    s1 = bridge.load_raw_shirt_source(shirt_url, file_name="Rayo25.png")
    bridge.preview_shirt_extraction({"shirtSourceId": s1["shirtSourceId"], "detailCrispness": 0.45})
    bridge.save_shirt_template(
        {
            "shirtSourceId": s1["shirtSourceId"],
            "displayName": "Rayo Vallecano",
            "clubId": "1744",
            "season": "2025/26",
            "templateId": "Rayo_2526",
            "isActiveForClub": True,
            "detailCrispness": 0.45,
        }
    )
    bridge.save_shirt_template(
        {
            "shirtSourceId": s1["shirtSourceId"],
            "displayName": "Rayo Vallecano Nueva",
            "clubId": "1744",
            "season": "2026/27",
            "templateId": "Rayo_2627",
            "isActiveForClub": True,
            "detailCrispness": 0.60,
        }
    )
    active_1744 = get_club_shirt_template("1744", tpl_dir=tpl_dir, db_path=db)
    assert active_1744 is not None and active_1744.template_id == "Rayo_2627"

    # Switch active back to 2025/26 season
    bridge.set_active_club_shirt_template("Rayo_2526")
    switched = get_club_shirt_template("1744", tpl_dir=tpl_dir, db_path=db)
    assert switched is not None and switched.template_id == "Rayo_2526"

    # Delete 2025/26 -> file removed and 2026/27 auto-promoted back to active!
    with pytest.raises(ValueError):
        bridge.delete_shirt_template("../evil")
    del_res = bridge.delete_shirt_template("Rayo_2526")
    assert del_res["deletedTemplateId"] == "Rayo_2526"
    assert not (tpl_dir / "Rayo_2526.png").exists()
    promoted = get_club_shirt_template("1744", tpl_dir=tpl_dir, db_path=db)
    assert promoted is not None and promoted.template_id == "Rayo_2627" and promoted.is_active_for_club is True

    # Explicit replacePreviousForClub=True removes older templates of #1744
    bridge.save_shirt_template(
        {
            "shirtSourceId": s1["shirtSourceId"],
            "displayName": "Rayo Definitiva",
            "clubId": "1744",
            "season": "2027/28",
            "templateId": "Rayo_2728",
            "replacePreviousForClub": True,
        }
    )
    assert not (tpl_dir / "Rayo_2627.png").exists()
    assert (tpl_dir / "Rayo_2728.png").is_file()

    # Long displayName + distinct seasons must never collide on 48-char slug truncation,
    # and naming custom club on season 2 synchronizes clubName onto sibling season 1!
    long_title = "Equipacion Oficial Titular Historica Club Deportivo Soria"
    r_s1 = bridge.save_shirt_template(
        {
            "shirtSourceId": s1["shirtSourceId"],
            "displayName": long_title,
            "clubId": "999888",
            "clubName": "",
            "season": "2025/26",
            "templateId": "",
            "isActiveForClub": True,
        }
    )
    r_s2 = bridge.save_shirt_template(
        {
            "shirtSourceId": s1["shirtSourceId"],
            "displayName": long_title,
            "clubId": "999888",
            "clubName": "CD Soria CF",
            "season": "2026/27",
            "templateId": "",
            "isActiveForClub": True,
        }
    )
    assert r_s1["savedTemplateId"] != r_s2["savedTemplateId"]
    soria_tpls = [t for t in r_s2["templates"] if t["clubId"] == "999888"]
    assert len(soria_tpls) == 2
    assert {t["clubName"] for t in soria_tpls} == {"CD Soria CF"}


def test_v130_template_categories_facepack_remix_and_dual_export_targets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import numpy as np
    from PIL import ImageDraw
    import backend.services.vision as vision_mod
    from backend.core.compositor import render_df11_card
    from backend.services.templates import get_club_shirt_template
    from backend.services.vision import FacePose

    def _fake_pose(_im: Image.Image, score_thresh: float = 0.55) -> FacePose:
        w, h = _im.size
        return FacePose(
            right_eye=(w * 0.40, h * 0.36),
            left_eye=(w * 0.60, h * 0.36),
            nose=(w * 0.50, h * 0.45),
            eye_center=(w * 0.50, h * 0.36),
            ipd=w * 0.20,
            yaw=0.0,
            bbox=(w * 0.28, h * 0.14, w * 0.44, h * 0.46),
        )

    def _fake_seg(im: Image.Image) -> np.ndarray:
        arr = np.asarray(im.convert("RGBA"))
        h, w = arr.shape[:2]
        probs = np.zeros((h, w, 6), dtype=np.float32)
        is_crimson = (arr[:, :, 0] > 130) & (arr[:, :, 1] < 60) & (arr[:, :, 3] > 40)
        is_navy = (arr[:, :, 2] > 130) & (arr[:, :, 0] < 60) & (arr[:, :, 3] > 40)
        is_cloth = is_crimson | is_navy
        is_skin = (arr[:, :, 0] > 185) & (arr[:, :, 1] > 130) & (arr[:, :, 1] < 205) & (arr[:, :, 3] > 40)
        probs[:, :, 4] = np.where(is_cloth, 0.95, 0.01)
        probs[:, :, 3] = np.where(is_skin & ~is_cloth, 0.92, 0.01)
        probs[:, :, 0] = np.clip(1.0 - probs[:, :, 4] - probs[:, :, 3], 0.0, 1.0)
        return probs

    def _fake_biref(im: Image.Image) -> Image.Image:
        arr = np.asarray(im.convert("RGBA")).copy()
        is_white_bg = (arr[:, :, 0] > 212) & (arr[:, :, 1] > 212) & (arr[:, :, 2] > 212)
        arr[:, :, 3] = np.where(is_white_bg, 0, arr[:, :, 3])
        return Image.fromarray(arr, mode="RGBA")

    monkeypatch.setattr(vision_mod, "detect_face_pose", _fake_pose)
    monkeypatch.setattr(vision_mod, "segment_portrait_classes", _fake_seg)
    monkeypatch.setattr(vision_mod, "remove_background_birefnet", _fake_biref)

    tpl_dir = tmp_path / "tshirt_templates"
    export_dir = tmp_path / "my_creations"
    facepack_dir = tmp_path / "fm_megapack_faces"
    tpl_dir.mkdir(parents=True)
    facepack_dir.mkdir(parents=True)

    # Seed one clean player navy shirt template & one staff navy jacket template
    navy_shirt = Image.new("RGBA", (260, 310), (0, 0, 0, 0))
    ndraw = ImageDraw.Draw(navy_shirt)
    ndraw.polygon([(19, 224), (92, 196), (130, 228), (168, 196), (241, 224), (241, 292), (19, 292)], fill=(25, 55, 175, 255))
    navy_shirt.save(tpl_dir / "Navy_Player.png", format="PNG")

    db_path = tmp_path / "state.sqlite3"
    bridge = StudioBridge(
        vault_dir=tmp_path / "vault",
        export_dir=export_dir,
        db_path=db_path,
        templates_dir=tpl_dir,
        raw_archive_dir=tmp_path / "raw_archive",
        extracted_faces_dir=tmp_path / "caras_extraidas",
        sample_faces_dir=tmp_path / "caras_prueba",
    )

    # 1. Default category == 'player', plus saving & updating a 'staff' template
    initial_tpls = bridge.list_shirt_templates()
    assert initial_tpls[0]["category"] == "player"

    suit_buf = io.BytesIO()
    navy_shirt.save(suit_buf, format="PNG")
    suit_url = "data:image/png;base64," + base64.b64encode(suit_buf.getvalue()).decode("ascii")
    s_src = bridge.load_raw_shirt_source(suit_url, file_name="Traje_Mister.png")
    bridge.preview_shirt_extraction({"shirtSourceId": s_src["shirtSourceId"]})
    saved_staff = bridge.save_shirt_template(
        {
            "shirtSourceId": s_src["shirtSourceId"],
            "displayName": "Traje Entrenador",
            "templateId": "Traje_Staff",
            "clubId": "1736",
            "category": "staff",
            "isActiveForClub": True,
        }
    )
    by_id = {t["templateId"]: t for t in saved_staff["templates"]}
    assert by_id["Traje_Staff"]["category"] == "staff"
    bridge.update_shirt_template_meta({"templateId": "Navy_Player", "displayName": "Titular 1736", "clubId": "1736", "category": "player", "isActiveForClub": True})
    # Player kit lookup for club #1736 must prefer 'player' category over 'staff'
    club_kit = get_club_shirt_template("1736", tpl_dir=tpl_dir, db_path=db_path)
    assert club_kit is not None and club_kit.template_id == "Navy_Player"

    # 2. Build a genuine assembled DF11 facepack card (<29184012>.png) with DF11 outer alpha=0 ring + white wall + crimson shirt + pink face
    raw_person = Image.new("RGBA", (260, 310), (0, 0, 0, 0))
    pdraw = ImageDraw.Draw(raw_person)
    pdraw.ellipse([84, 44, 176, 176], fill=(220, 172, 148, 255))
    pdraw.rectangle([98, 162, 162, 226], fill=(214, 165, 140, 255))
    pdraw.polygon([(19, 224), (92, 196), (130, 228), (168, 196), (241, 224), (241, 292), (19, 292)], fill=(185, 24, 38, 255))
    assembled_card = render_df11_card(raw_person, bg_mode="white_df11")
    facepack_card_path = facepack_dir / "29184012.png"
    assembled_card.save(facepack_card_path, format="PNG")
    (facepack_dir / "config.xml").write_text(
        '<record>\n\t<boolean id="preload" value="false"/>\n\t<boolean id="amap" value="false"/>\n\t<list id="maps">\n'
        '\t\t<record from="111111" to="graphics/pictures/person/111111/portrait"/>\n'
        '\t\t<record from="29184012" to="graphics/pictures/person/29184012/portrait"/>\n'
        "\t</list>\n</record>\n",
        encoding="utf-8",
    )

    class _FacepackDialogWin:
        def create_file_dialog(self, *args: object, **kwargs: object) -> tuple[str, ...]:
            return (str(facepack_card_path),)

    bridge._attach_window(_FacepackDialogWin())

    # 2A. Remix Mode 'swap_shirt': extracts footballer head+neck (stripping white DF11 wall AND crimson shirt) onto Navy_Player
    remix_a = bridge.pick_facepack_card("swap_shirt", "Navy_Player", {"bgMode": "transparent"})
    assert remix_a is not None
    assert remix_a["detectedUid"] == "29184012"
    assert remix_a["facepackDir"] == str(facepack_dir.resolve())
    assert bridge.get_bootstrap_state()["facepackDir"] == str(facepack_dir.resolve())
    head_asset = bridge._mod().get_head_asset(remix_a["headAssetId"])
    assert head_asset is not None
    # Upper-left interior corner of DF11 card (30, 30) MUST be transparent (white DF11 background stripped, not mistaken for pre-cutout!)
    assert int(np.asarray(head_asset.rgba)[30, 30, 3]) == 0
    prev_a = np.asarray(Image.open(io.BytesIO(base64.b64decode(remix_a["previewDataUrl"].split(",", 1)[1]))).convert("RGBA"))
    # Chest now wears Navy_Player (blue > red), NOT the old crimson shirt!
    assert int(prev_a[255, 80, 2]) > int(prev_a[255, 80, 0]) + 60

    # 2B. Switch remix mode to 'swap_face': isolates crimson shirt from 29184012.png into adhocShirtId so a new face mounts on it
    remix_b = bridge.switch_facepack_remix_mode("swap_face", "", {"bgMode": "transparent"})
    adhoc_id = remix_b["adhocShirtId"]
    assert adhoc_id.startswith("adhoc:")
    # Compose new face (head_asset) onto adhocShirtId -> chest wears the original crimson shirt (red > blue)!
    comp_b = bridge.render_modular_preview(
        {
            "headAssetId": remix_a["headAssetId"],
            "wearMode": "template",
            "templateId": adhoc_id,
            "scale": remix_a["autoFit"]["scale"],
            "offsetX": remix_a["autoFit"]["offsetX"],
            "offsetY": remix_a["autoFit"]["offsetY"],
            "neckFill": 1.0,
            "bgMode": "transparent",
        }
    )
    prev_b = np.asarray(Image.open(io.BytesIO(base64.b64decode(comp_b["previewDataUrl"].split(",", 1)[1]))).convert("RGBA"))
    assert int(prev_b[255, 80, 0]) > int(prev_b[255, 80, 2]) + 80

    # 3. Dual Export Target: Option 1 (Creations folder) & Option 2 (FM Facepack folder overwriting 29184012.png)
    exp1 = bridge.export_modular_card(
        {
            "uid": "29184012",
            "exportTarget": "creations",
            "headAssetId": remix_a["headAssetId"],
            "wearMode": "template",
            "templateId": "Navy_Player",
            "scale": remix_a["autoFit"]["scale"],
            "offsetX": remix_a["autoFit"]["offsetX"],
            "offsetY": remix_a["autoFit"]["offsetY"],
            "neckFill": 1.0,
            "fmt": "png",
            "updateConfigXml": True,
        }
    )
    assert Path(exp1["savedPath"]).resolve() == (export_dir / "29184012.png").resolve()
    assert (export_dir / "29184012.png").is_file()

    cfg_mtime_before = (facepack_dir / "config.xml").stat().st_mtime_ns
    exp2 = bridge.export_modular_card(
        {
            "uid": "29184012",
            "exportTarget": "facepack",
            "headAssetId": remix_a["headAssetId"],
            "wearMode": "template",
            "templateId": adhoc_id,
            "scale": remix_a["autoFit"]["scale"],
            "offsetX": remix_a["autoFit"]["offsetX"],
            "offsetY": remix_a["autoFit"]["offsetY"],
            "neckFill": 1.0,
            "fmt": "png",
            "updateConfigXml": True,
        }
    )
    assert Path(exp2["savedPath"]).resolve() == facepack_card_path.resolve()
    # Existing megapack config.xml already had 29184012 mapped -> fast-path preserves file untouched without clobbering 111111!
    assert (facepack_dir / "config.xml").stat().st_mtime_ns == cfg_mtime_before
    assert 'from="111111"' in (facepack_dir / "config.xml").read_text(encoding="utf-8")

    # Unapproved arbitrary outDir on facepack target must still raise CapabilityError
    with pytest.raises(CapabilityError):
        bridge.export_modular_card(
            {
                "uid": "29184012",
                "exportTarget": "facepack",
                "outDir": str(tmp_path / "unapproved_dir"),
                "headAssetId": remix_a["headAssetId"],
                "wearMode": "template",
                "templateId": "Navy_Player",
            }
        )


def test_v130_round1_vault_overlap_adhoc_eviction_and_regen_jump_guards(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import numpy as np
    import backend.services.vision as vision_mod
    from backend.services.sync import assign_uids_to_club
    from backend.services.templates import get_club_shirt_template

    monkeypatch.setattr(vision_mod, "segment_portrait_classes", lambda im: np.zeros((im.height, im.width, 6), dtype=np.float32))
    monkeypatch.setattr(vision_mod, "remove_background_birefnet", lambda im: im.convert("RGBA"))
    monkeypatch.setattr(vision_mod, "detect_face_pose", lambda _im, score_thresh=0.55: None)

    vault_root = tmp_path / "ng_vault_parent" / "vault_ro"
    vault_sub = vault_root / "faces_sub"
    vault_sub.mkdir(parents=True)
    export_dir = tmp_path / "creations_out"
    facepack_dir = tmp_path / "fm_faces_out"
    facepack_dir.mkdir(parents=True)
    tpl_dir = tmp_path / "tshirt_templates"
    tpl_dir.mkdir(parents=True)
    db_path = tmp_path / "round1.sqlite3"

    raw_png = base64.b64decode(_sample_png_data_url().split(",", 1)[1])
    (vault_sub / "r1.png").write_bytes(raw_png)
    (vault_root / "config.xml").write_text(
        '<record><list id="maps"><record from="faces_sub/r1" to="graphics/pictures/person/r-8801/portrait"/></list></record>',
        encoding="utf-8",
    )

    bridge = StudioBridge(
        vault_dir=vault_root,
        export_dir=export_dir,
        db_path=db_path,
        templates_dir=tpl_dir,
        raw_archive_dir=tmp_path / "raw_archive",
        extracted_faces_dir=tmp_path / "caras_extraidas",
        sample_faces_dir=tmp_path / "caras_prueba",
    )

    # 1. Bidirectional vault overlap guard on choose_directory (both subfolder & parent of vault_ro must be blocked!)
    class _DirWin:
        def __init__(self, target: Path) -> None:
            self.target = target
            self.last_init_dir = ""

        def create_file_dialog(self, _dtype: int = 20, directory: str = "", **_kw: object) -> tuple[str, ...]:
            self.last_init_dir = directory
            return (str(self.target),)

    for bad_dir in (vault_sub, vault_root.parent):
        bridge._attach_window(_DirWin(bad_dir))
        with pytest.raises(CapabilityError):
            bridge.choose_directory("facepack")
        with pytest.raises(CapabilityError):
            bridge.choose_directory("export")

    # 2. pick_facepack_card must NOT default to vault_root, must NOT overwrite last_image_dir, and must NOT approve vault_sub!
    portraits_dir = tmp_path / "MyPortraits"
    portraits_dir.mkdir()
    (portraits_dir / "me.png").write_bytes(raw_png)
    bridge._attach_window(_DirWin(portraits_dir / "me.png"))
    bridge.pick_raw_face_source()
    assert Path(bridge._get_pref("last_image_dir")).resolve() == portraits_dir.resolve()

    vault_file_win = _DirWin(vault_sub / "r1.png")
    bridge._attach_window(vault_file_win)
    remix_vault = bridge.pick_facepack_card("swap_shirt", "", {"bgMode": "transparent"})
    assert remix_vault is not None
    # Initial dialog directory for unset last_facepack_dir must fall back to export_dir (not vault_root!)
    assert not Path(vault_file_win.last_init_dir).resolve().is_relative_to(vault_root.resolve())
    # Picking a file inside vault_sub must NEVER set facepackDir or clobber last_image_dir
    assert remix_vault["facepackDir"] == ""
    assert bridge.get_bootstrap_state()["facepackDir"] == ""
    assert Path(bridge._get_pref("last_image_dir")).resolve() == portraits_dir.resolve()

    # 3. Missing/evicted templateId or adhoc:shirt-N in export_modular_card must raise ValueError even when headAssetId is valid!
    with pytest.raises(ValueError, match="camiseta|plantilla"):
        bridge.export_modular_card(
            {
                "uid": "29184012",
                "exportTarget": "creations",
                "headAssetId": remix_vault["headAssetId"],
                "wearMode": "template",
                "templateId": "adhoc:shirt-9999",
            }
        )

    # 4. Club #555000 has ONLY a 'staff' suit -> get_club_shirt_template & load_regen_into_studio must NOT assign Staff to regen!
    shirt_im = Image.new("RGBA", (260, 310), (0, 0, 0, 0))
    shirt_im.paste((25, 65, 165, 255), (25, 205, 235, 290))
    s_buf = io.BytesIO()
    shirt_im.save(s_buf, format="PNG")
    s_url = "data:image/png;base64," + base64.b64encode(s_buf.getvalue()).decode("ascii")
    st_src = bridge.load_raw_shirt_source(s_url, file_name="Staff555.png")
    bridge.preview_shirt_extraction({"shirtSourceId": st_src["shirtSourceId"]})
    bridge.save_shirt_template(
        {
            "shirtSourceId": st_src["shirtSourceId"],
            "displayName": "Traje Staff 555",
            "templateId": "Staff_555000",
            "clubId": "555000",
            "category": "staff",
            "isActiveForClub": True,
        }
    )
    assert get_club_shirt_template("555000", tpl_dir=tpl_dir, db_path=db_path) is None
    assert get_club_shirt_template("555000", tpl_dir=tpl_dir, db_path=db_path, category="staff") is not None

    assign_uids_to_club(["r-8801"], "555000", db_path=db_path)
    jumped = bridge.load_regen_into_studio("r-8801")
    assert jumped["matchedTemplateId"] == ""

    # Staff-only catalog must NOT auto-select a Staff suit when remixing a footballer card in swap_shirt mode
    remix_staff_only = bridge.load_facepack_card(s_url, "29184012.png", "swap_shirt", "", {})
    assert remix_staff_only["templateId"] == ""

    # 5. export_studio_card (legacy-jump path) supports exportTarget='facepack' into approved facepackDir
    bridge._attach_window(_DirWin(facepack_dir))
    bridge.choose_directory("facepack")
    exp_legacy_fp = bridge.export_studio_card(
        {
            "uid": "r-8801",
            "exportTarget": "facepack",
            "fmt": "jpg",
            "updateConfigXml": True,
        }
    )
    assert Path(exp_legacy_fp["savedPath"]).resolve() == (facepack_dir / "r-8801.png").resolve()
    assert (facepack_dir / "r-8801.png").is_file()






