"""Integration tests for Dual (Classic + Pure) atomic export, FM graphics collision detection, and NG_Regens variant sync."""

from __future__ import annotations

import base64
import io
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
from PIL import Image

from backend.bridge import CapabilityError, StudioBridge
from backend.core.fm_config import detect_fm_graphics_collision, upsert_fm_config_xml
from backend.services.sync import sync_ng_regens_batch


def _png_data_url_rgba(w: int, h: int, color: tuple[int, int, int, int]) -> str:
    arr = np.zeros((h, w, 4), dtype=np.uint8)
    arr[20 : h - 10, 15 : w - 15] = color
    buf = io.BytesIO()
    Image.fromarray(arr, mode="RGBA").save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def test_detect_fm_graphics_collision_identifies_shared_fm_graphics_ancestor(tmp_path: Path) -> None:
    fm_gfx = tmp_path / "Sports Interactive" / "Football Manager 2024" / "graphics"
    c_in_fm = fm_gfx / "faces" / "01_DF11_Classic"
    p_in_fm = fm_gfx / "faces" / "02_DF11_Pure"
    ext_pure = tmp_path / "DF11Studio" / "Exports" / "000_DF11_Pure_Override"

    assert detect_fm_graphics_collision(c_in_fm, p_in_fm) is True
    assert detect_fm_graphics_collision(c_in_fm, ext_pure) is False
    assert detect_fm_graphics_collision(tmp_path / "Exports" / "Classic", tmp_path / "Exports" / "Pure") is False


def test_bridge_dual_export_creations_asymmetric_autoname_facepack_2pc_and_legacy_jump(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    classic_exp = tmp_path / "Exports" / "Classic"
    pure_exp = tmp_path / "Exports" / "Pure"
    fp_classic = tmp_path / "FM" / "graphics" / "faces" / "Classic"
    fp_pure = tmp_path / "FM" / "graphics" / "faces" / "Pure"
    for d in (vault, classic_exp, pure_exp, fp_classic, fp_pure):
        d.mkdir(parents=True, exist_ok=True)

    bridge = StudioBridge(
        vault_dir=vault,
        export_dir=classic_exp,
        export_pure_dir=pure_exp,
        db_path=tmp_path / "state.sqlite3",
        templates_dir=tmp_path / "tpls",
        raw_archive_dir=tmp_path / "arch",
        extracted_faces_dir=tmp_path / "ext_faces",
        sample_faces_dir=tmp_path / "smp_faces",
    )

    boot = bridge.get_bootstrap_state()
    assert boot["exportPureDir"] == str(pure_exp.resolve())
    assert boot["exportVariant"] == "classic"
    assert bridge.set_export_variant("dual")["exportVariant"] == "dual"
    assert bridge.get_bootstrap_state()["exportVariant"] == "dual"

    # Load a pre-cutout transparent portrait into Direct Photo (0% AI)
    loaded = bridge.load_direct_photo_source(_png_data_url_rgba(220, 276, (180, 35, 45, 255)), "Jugador_Estrella.png")
    did = loaded["directPhotoId"]

    # Pre-seed an asymmetric file ONLY in pure_exp to verify RT-09 collision avoidance
    (pure_exp / "Jugador_Estrella.png").write_bytes(b"PROTECTED_EXISTING_PURE_FILE")

    res_creations = bridge.export_modular_card(
        {
            "step1Mode": "direct_photo",
            "directPhotoId": did,
            "uid": "",
            "fileLabel": "Jugador_Estrella",
            "fmt": "png",
            "exportTarget": "creations",
            "exportVariant": "dual",
            "updateConfigXml": False,
        }
    )
    # Existing pure_exp/Jugador_Estrella.png MUST remain untouched; both folders get Jugador_Estrella_2.png!
    assert (pure_exp / "Jugador_Estrella.png").read_bytes() == b"PROTECTED_EXISTING_PURE_FILE"
    c_saved = Path(res_creations["savedPath"])
    p_saved = Path(res_creations["savedPurePath"])
    assert c_saved.name == "Jugador_Estrella_2.png"
    assert p_saved.name == "Jugador_Estrella_2.png"
    assert Image.open(c_saved).size == (260, 310)
    assert Image.open(p_saved).size == (220, 276)

    # Atomic Pre-flight check: Dual export to 'facepack' when facepack_pure_dir is NOT configured yet must write NOTHING to fp_classic!
    bridge._approved_dirs.add(fp_classic.resolve())
    bridge._facepack_dir = fp_classic.resolve()
    with pytest.raises(ValueError, match="Pure"):
        bridge.export_modular_card(
            {
                "step1Mode": "direct_photo",
                "directPhotoId": did,
                "uid": "29184012",
                "exportTarget": "facepack",
                "exportVariant": "dual",
                "outDir": str(fp_classic),
                "updateConfigXml": True,
            }
        )
    assert not (fp_classic / "29184012.png").exists()
    assert not (fp_classic / "config.xml").exists()

    # Overlap guard: Pure folder cannot equal or be nested inside Classic folder
    nested_pure = fp_classic / "sub_pure"
    nested_pure.mkdir(parents=True, exist_ok=True)
    bridge._approved_dirs.add(nested_pure.resolve())
    with pytest.raises((ValueError, CapabilityError)):
        bridge.export_modular_card(
            {
                "step1Mode": "direct_photo",
                "directPhotoId": did,
                "uid": "29184012",
                "exportTarget": "facepack",
                "exportVariant": "dual",
                "outDir": str(fp_classic),
                "outPureDir": str(nested_pure),
                "updateConfigXml": True,
            }
        )

    # Approve independent fp_pure inside same FM/graphics tree -> succeeds AND reports fmGraphicsCollision warning
    bridge._approved_dirs.add(fp_pure.resolve())
    bridge._facepack_pure_dir = fp_pure.resolve()
    res_fp = bridge.export_modular_card(
        {
            "step1Mode": "direct_photo",
            "directPhotoId": did,
            "uid": "29184012",
            "exportTarget": "facepack",
            "exportVariant": "dual",
            "outDir": str(fp_classic),
            "outPureDir": str(fp_pure),
            "updateConfigXml": True,
        }
    )
    assert Image.open(fp_classic / "29184012.png").size == (260, 310)
    assert Image.open(fp_pure / "29184012.png").size == (220, 276)
    assert 'from="29184012"' in (fp_classic / "config.xml").read_text(encoding="utf-8")
    assert 'from="29184012"' in (fp_pure / "config.xml").read_text(encoding="utf-8")
    assert res_fp["fmGraphicsCollision"] is True

    # Legacy-jump export_studio_card also supports Pure and Dual
    bridge.upload_studio_image(_png_data_url_rgba(220, 276, (40, 120, 210, 255)), remove_bg=False, harmonize=False)
    res_legacy = bridge.export_studio_card(
        {
            "uid": "r-2002049102",
            "exportTarget": "facepack",
            "exportVariant": "dual",
            "outDir": str(fp_classic),
            "outPureDir": str(fp_pure),
            "updateConfigXml": True,
        }
    )
    assert Image.open(fp_classic / "r-2002049102.png").size == (260, 310)
    assert Image.open(fp_pure / "r-2002049102.png").size == (220, 276)
    assert res_legacy["savedPurePath"].endswith("r-2002049102.png")


def test_ng_regens_sync_materializes_missing_pure_on_classic_to_dual_transition(tmp_path: Path) -> None:
    vault = tmp_path / "NG_Regens"
    out_classic = tmp_path / "000_Classic"
    out_pure = tmp_path / "000_Pure"
    db_path = tmp_path / "state.sqlite3"
    vault.mkdir(parents=True)

    # Create 2 pre-cutout regen PNGs (is_pre_cutout=True -> no BiRefNet needed!) + vault config.xml
    for uid in ("r-2002042100", "r-2002042101"):
        arr = np.zeros((310, 260, 4), dtype=np.uint8)
        arr[40:300, 35:225] = (190, 145, 120, 255)
        Image.fromarray(arr, mode="RGBA").save(vault / f"{uid}.png", format="PNG")
    upsert_fm_config_xml(vault / "config.xml", ("r-2002042100", "r-2002042101"))

    # 1. Sync in Classic mode first
    r1 = sync_ng_regens_batch(
        vault_dir=vault,
        out_dir=out_classic,
        db_path=db_path,
        apply_club_kits=False,
        harmonize=False,
        variant="classic",
    )
    assert r1.processed == 2 and r1.skipped == 0
    assert Image.open(out_classic / "r-2002042100.png").size == (260, 310)
    assert not out_pure.exists()

    # 2. Switch to Dual mode on unchanged vault -> MUST NOT skip! Must materialize Pure folder + config.xml!
    r2 = sync_ng_regens_batch(
        vault_dir=vault,
        out_dir=out_classic,
        pure_out_dir=out_pure,
        db_path=db_path,
        apply_club_kits=False,
        harmonize=False,
        variant="dual",
    )
    assert r2.processed == 2 and r2.skipped == 0
    assert Image.open(out_pure / "r-2002042100.png").size == (220, 276)
    assert Image.open(out_pure / "r-2002042101.png").size == (220, 276)
    assert 'from="r-2002042100"' in (out_pure / "config.xml").read_text(encoding="utf-8")

    # 3. Re-run Dual -> both folders are now materialized & up-to-date -> skipped == 2!
    r3 = sync_ng_regens_batch(
        vault_dir=vault,
        out_dir=out_classic,
        pure_out_dir=out_pure,
        db_path=db_path,
        apply_club_kits=False,
        harmonize=False,
        variant="dual",
    )
    assert r3.processed == 0 and r3.skipped == 2

    # 4. Switch to Pure-only or Classic-only -> files already exist with matching signatures -> skipped == 2!
    r4 = sync_ng_regens_batch(
        vault_dir=vault,
        out_dir=out_classic,
        pure_out_dir=out_pure,
        db_path=db_path,
        apply_club_kits=False,
        harmonize=False,
        variant="pure",
    )
    assert r4.processed == 0 and r4.skipped == 2
    r5 = sync_ng_regens_batch(
        vault_dir=vault,
        out_dir=out_classic,
        db_path=db_path,
        apply_club_kits=False,
        harmonize=False,
        variant="classic",
    )
    assert r5.processed == 0 and r5.skipped == 2


def test_dual_export_2phase_rollback_and_direct_photo_explicit_cutout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import backend.core.fm_config as fm_mod
    import backend.services.vision as vision_mod

    classic_exp = tmp_path / "Exports" / "Classic"
    pure_exp = tmp_path / "Exports" / "Pure"
    classic_exp.mkdir(parents=True)
    pure_exp.mkdir(parents=True)

    bridge = StudioBridge(
        vault_dir=tmp_path / "vault",
        export_dir=classic_exp,
        export_pure_dir=pure_exp,
        db_path=tmp_path / "state.sqlite3",
    )

    # 1. Opaque Direct Photo loaded while previewVariant='pure' must NOT crash on load,
    #    must block Pure export until explicit cutout, and succeed after 1-click cutout_direct_photo_for_pure!
    opaque_buf = io.BytesIO()
    Image.new("RGB", (240, 280), (65, 120, 195)).save(opaque_buf, format="JPEG", quality=92)
    opaque_url = "data:image/jpeg;base64," + base64.b64encode(opaque_buf.getvalue()).decode("ascii")

    loaded_op = bridge.load_direct_photo_source(opaque_url, "Foto_Opaca.jpg", params={"previewVariant": "pure"})
    assert loaded_op["isPreCutout"] is False
    did = loaded_op["directPhotoId"]

    with pytest.raises(ValueError, match="Recortar fondo"):
        bridge.export_modular_card(
            {
                "step1Mode": "direct_photo",
                "directPhotoId": did,
                "uid": "900100",
                "exportVariant": "pure",
            }
        )

    def _fake_biref(im: Image.Image) -> Image.Image:
        out = im.convert("RGBA").copy()
        alpha = Image.new("L", out.size, 0)
        alpha.paste(255, (40, 30, 200, 270))
        out.putalpha(alpha)
        return out

    monkeypatch.setattr(vision_mod, "remove_background_birefnet", _fake_biref)
    cut_res = bridge.cutout_direct_photo_for_pure(did, params={"previewVariant": "pure"})
    assert cut_res["isPreCutout"] is True
    cut_prev = Image.open(io.BytesIO(base64.b64decode(cut_res["previewDataUrl"].split(",", 1)[1])))
    assert cut_prev.size == (220, 276)

    # 2. Simulate disk failure on the 2nd safe_ntfs_replace during Dual export:
    #    newly created Classic file MUST be rolled back; pre-existing Classic file MUST be preserved!
    real_replace = fm_mod.safe_ntfs_replace
    call_count = {"n": 0}

    def _fail_second_replace(src: Path, dst: Path, retries: int = 5) -> None:
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise OSError("Simulated disk full on Pure target")
        real_replace(src, dst, retries=retries)

    with patch.object(fm_mod, "safe_ntfs_replace", side_effect=_fail_second_replace):
        with pytest.raises(OSError, match="Simulated disk full"):
            bridge.export_modular_card(
                {
                    "step1Mode": "direct_photo",
                    "directPhotoId": did,
                    "uid": "900101",
                    "exportVariant": "dual",
                    "updateConfigXml": True,
                }
            )
    assert not (classic_exp / "900101.png").exists(), "Newly created Classic PNG must roll back when Pure commit fails"
    assert not (pure_exp / "900101.png").exists()
    assert not (classic_exp / "config.xml").exists()
