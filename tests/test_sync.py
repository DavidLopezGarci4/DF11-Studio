"""RED->GREEN deterministic tests for NG_Regens vault scanner, OneDrive sentinel, and Live Disk Sync."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import numpy as np
from PIL import Image

from backend.services.sync import (
    QuiescentVaultWatcher,
    assign_uids_to_club,
    check_fm_storage_health,
    import_squad_club_mappings,
    scan_ng_regens_vault,
    sync_ng_regens_batch,
)


def _make_cutout_png(path: Path, shirt_rgb: tuple[int, int, int] = (30, 100, 210)) -> None:
    arr = np.zeros((240, 240, 4), dtype=np.uint8)
    arr[40:240, 55:185] = (*shirt_rgb, 255)
    arr[35:130, 85:155] = (210, 168, 142, 255)
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(arr, mode="RGBA").save(path, format="PNG")


def test_scanner_blocks_cwe22_and_unc_smb_and_keeps_vault_untouched(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    outside = tmp_path / "secret.png"
    _make_cutout_png(outside)
    _make_cutout_png(vault / "faces" / "regen1.png")
    cfg = vault / "config.xml"
    cfg.write_text(
        '<record><list id="maps">'
        '<record from="../secret" to="graphics/pictures/person/r-2001/portrait"/>'
        '<record from="\\\\192.0.2.9\\smb\\leak" to="graphics/pictures/person/r-2002/portrait"/>'
        '<record from="faces/regen1" to="graphics/pictures/person/r-2003/portrait"/>'
        "</list></record>",
        encoding="utf-8",
    )
    orig_bytes = cfg.read_bytes()
    entries = scan_ng_regens_vault(vault)
    assert list(entries.keys()) == ["r-2003"]
    assert cfg.read_bytes() == orig_bytes  # Vault config.xml never renamed or mutated


def test_onedrive_sentinel_flags_onedrive_path_with_steam_and_gamepass_guidance(tmp_path: Path) -> None:
    fake_od = tmp_path / "OneDrive" / "Documentos" / "Sports Interactive" / "Football Manager 2027"
    rep = check_fm_storage_health(fake_od)
    assert rep.in_onedrive is True and rep.warning is True
    assert '--user_data_location="D:\\FM27 Data"' in rep.steam_launch_arg
    assert "Game Pass" in rep.gamepass_guide and "OneDrive" in rep.gamepass_guide


def test_squad_importer_parses_csv_html_and_tags_my_club(tmp_path: Path) -> None:
    db = tmp_path / "state.sqlite3"
    text = (
        "UID,Club\n"
        "r-2002049102,Real Madrid\n"
        "<tr><td>r-2002049103</td><td>1708</td></tr>\n"
    )
    count = import_squad_club_mappings(text, db_path=db)
    assert count == 2
    assert assign_uids_to_club(["r-2002049104"], "776", db_path=db) == 1


def test_squad_importer_ignores_age_and_shirt_numbers_and_matches_custom_clubs(tmp_path: Path) -> None:
    from backend.services.kits import init_state_db, upsert_custom_club_entry

    db = tmp_path / "squad_hardened.sqlite3"
    upsert_custom_club_entry("999123", "CD Numancia B", db_path=db)

    # Multi-column FM Ctrl+P export containing Age (19, 29) and Shirt Number (7, 10) BEFORE Club column!
    fm_export = (
        "| UID | Nombre | Edad | Dorsal | Club |\n"
        "| r-2002049102 | Isi Palazón | 29 | 7 | Rayo Vallecano |\n"
        "| r-2002049105 | Canterano Soria | 19 | 10 | CD Numancia B |\n"
        "| r-2002049109 | Juvenil Libre | 17 | 14 | Sin Equipo Desconocido |\n"
    )
    mapped = import_squad_club_mappings(fm_export, db_path=db)
    assert mapped == 2

    with init_state_db(db) as conn:
        rows = dict(conn.execute("SELECT uid, club_id FROM squad_map").fetchall())
        roster = {
            r[0]: (r[1], r[2])
            for r in conn.execute("SELECT uid, club_id, player_name FROM save_squad_roster WHERE save_id='default'").fetchall()
        }
    assert rows == {
        "r-2002049102": "1744",
        "r-2002049105": "999123",
    }
    assert "r-2002049109" not in rows, "Short numeric stats (17, 14) must NEVER be misidentified as club_id"
    assert roster["r-2002049102"] == ("1744", "Isi Palazón")
    assert roster["r-2002049105"] == ("999123", "Canterano Soria")


def test_incremental_batch_sync_and_50pct_shrink_guard(tmp_path: Path) -> None:
    db, vault, out_dir = tmp_path / "state.sqlite3", tmp_path / "vault", tmp_path / "000_DF11_Regens_Override"
    for i in range(4):
        _make_cutout_png(vault / f"p{i}.png")
    recs = "".join(f'<record from="p{i}" to="graphics/pictures/person/r-300{i}/portrait"/>' for i in range(4))
    (vault / "config.xml").write_text(f'<record><list id="maps">{recs}</list></record>', encoding="utf-8")
    assign_uids_to_club(["r-3000"], "1736", db_path=db)

    r1 = sync_ng_regens_batch(vault, out_dir, db_path=db, apply_club_kits=True)
    assert r1.processed == 4 and r1.skipped == 0 and not r1.aborted_by_shrink_guard
    card0 = Image.open(out_dir / "r-3000.png")
    assert card0.size == (260, 310) and card0.getpixel((14, 155))[3] == 0

    # Incremental second run skips all 4 unchanged regens
    r2 = sync_ng_regens_batch(vault, out_dir, db_path=db, apply_club_kits=True)
    assert r2.processed == 0 and r2.skipped == 4

    # Truncate vault config from 4 -> 1 regen (< 50%): Shrink Guard must block wipe!
    (vault / "config.xml").write_text(
        '<record><list id="maps"><record from="p0" to="graphics/pictures/person/r-3000/portrait"/></list></record>',
        encoding="utf-8",
    )
    r3 = sync_ng_regens_batch(vault, out_dir, db_path=db)
    assert r3.aborted_by_shrink_guard is True


def test_quiescence_watcher_waits_for_stable_write_and_cancellation(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _make_cutout_png(vault / "a.png")
    cfg = vault / "config.xml"
    cfg.write_text('<record><list id="maps"><record from="a" to="graphics/pictures/person/r-91/portrait"/></list></record>', encoding="utf-8")

    triggered: list[int] = []
    watcher = QuiescentVaultWatcher(vault, on_quiescent=lambda: triggered.append(1), quiescence_sec=0.12)
    assert watcher.poll_once() is False  # First observation starts debounce window
    time.sleep(0.15)
    assert watcher.poll_once() is True and len(triggered) == 1
    assert watcher.poll_once() is False  # No duplicate fire when unchanged

    cancel = threading.Event()
    cancel.set()
    res = sync_ng_regens_batch(vault, tmp_path / "out_cancel", db_path=tmp_path / "c.db", cancel_event=cancel)
    assert res.cancelled is True and res.processed == 0


def test_batch_sync_isolates_corrupt_regen_without_losing_valid_cards(tmp_path: Path) -> None:
    db, vault, out_dir = tmp_path / "iso.db", tmp_path / "vault_iso", tmp_path / "out_iso"
    _make_cutout_png(vault / "good.png")
    (vault / "corrupt.png").write_bytes(b"not-a-valid-png")
    (vault / "config.xml").write_text(
        '<record><list id="maps">'
        '<record from="good" to="graphics/pictures/person/r-501/portrait"/>'
        '<record from="corrupt" to="graphics/pictures/person/r-502/portrait"/>'
        "</list></record>",
        encoding="utf-8",
    )
    rep = sync_ng_regens_batch(vault, out_dir, db_path=db, apply_club_kits=False)
    assert rep.processed == 1 and rep.failed == 1
    assert (out_dir / "r-501.png").is_file()
    cfg_text = (out_dir / "config.xml").read_text(encoding="utf-8")
    assert "r-501" in cfg_text and "r-502" not in cfg_text


def test_batch_sync_ignores_staff_and_archived_templates_and_uses_active_player_kit(
    tmp_path: Path, monkeypatch
) -> None:
    from PIL import ImageDraw
    import backend.services.vision as vision_mod
    from backend.services.templates import save_new_shirt_template
    from backend.services.vision import FacePose

    def _fake_pose(_im: Image.Image, score_thresh: float = 0.55) -> FacePose:
        w, h = _im.size
        return FacePose(
            right_eye=(w * 0.40, h * 0.35),
            left_eye=(w * 0.60, h * 0.35),
            nose=(w * 0.50, h * 0.44),
            eye_center=(w * 0.50, h * 0.35),
            ipd=w * 0.20,
            yaw=0.0,
            bbox=(w * 0.30, h * 0.14, w * 0.40, h * 0.42),
        )

    def _fake_seg(im: Image.Image) -> np.ndarray:
        arr = np.asarray(im.convert("RGBA"))
        h, w = arr.shape[:2]
        probs = np.zeros((h, w, 6), dtype=np.float32)
        fg = arr[:, :, 3] > 20
        is_cloth = fg & (arr[:, :, 2] > 170)
        probs[:, :, 4] = np.where(is_cloth, 0.94, 0.01)
        probs[:, :, 3] = np.where(fg & ~is_cloth, 0.92, 0.01)
        probs[:, :, 0] = np.clip(1.0 - probs[:, :, 4] - probs[:, :, 3], 0.0, 1.0)
        return probs

    monkeypatch.setattr(vision_mod, "detect_face_pose", _fake_pose)
    monkeypatch.setattr(vision_mod, "segment_portrait_classes", _fake_seg)
    monkeypatch.setattr(vision_mod, "remove_background_birefnet", lambda im: im.convert("RGBA"))

    db, vault, out_dir, tpl_dir = tmp_path / "sync_cat.db", tmp_path / "vault_cat", tmp_path / "out_cat", tmp_path / "tpl_cat"
    _make_cutout_png(vault / "rm_regen.png")
    _make_cutout_png(vault / "fcb_regen.png")
    (vault / "config.xml").write_text(
        '<record><list id="maps">'
        '<record from="rm_regen" to="graphics/pictures/person/r-4001/portrait"/>'
        '<record from="fcb_regen" to="graphics/pictures/person/r-4002/portrait"/>'
        "</list></record>",
        encoding="utf-8",
    )
    assign_uids_to_club(["r-4001"], "1736", db_path=db)
    assign_uids_to_club(["r-4002"], "999777", db_path=db)

    def _shirt_rgba(rgb: tuple[int, int, int]) -> Image.Image:
        im = Image.new("RGBA", (260, 310), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        d.polygon([(19, 224), (92, 196), (130, 228), (168, 196), (241, 224), (241, 292), (19, 292)], fill=(*rgb, 255))
        return im

    # Alphabetically first 'Abrigo_Staff' (green) is STAFF; 'Club_2025_26' (yellow) is archived player;
    # 'Zz_Titular_2627' (crimson red) is the ONLY active player shirt for #1736!
    save_new_shirt_template(
        clean_rgba=_shirt_rgba((15, 190, 45)),
        raw_bytes=None,
        display_name="Abrigo Staff",
        template_id="Abrigo_Staff",
        club_id="1736",
        category="staff",
        is_active_for_club=True,
        tpl_dir=tpl_dir,
        db_path=db,
    )
    save_new_shirt_template(
        clean_rgba=_shirt_rgba((210, 200, 15)),
        raw_bytes=None,
        display_name="Club 2025/26",
        template_id="Club_2025_26",
        club_id="1736",
        category="player",
        is_active_for_club=False,
        tpl_dir=tpl_dir,
        db_path=db,
    )
    save_new_shirt_template(
        clean_rgba=_shirt_rgba((205, 22, 35)),
        raw_bytes=None,
        display_name="Zz Titular 26/27",
        template_id="Zz_Titular_2627",
        club_id="1736",
        category="player",
        is_active_for_club=True,
        tpl_dir=tpl_dir,
        db_path=db,
    )
    # Club #999777 ONLY has a Staff suit (bright green) -> regen r-4002 must NOT wear the Staff suit!
    save_new_shirt_template(
        clean_rgba=_shirt_rgba((15, 210, 45)),
        raw_bytes=None,
        display_name="Traje Mister 999777",
        template_id="Aa_Staff_999777",
        club_id="999777",
        category="staff",
        is_active_for_club=True,
        tpl_dir=tpl_dir,
        db_path=db,
    )

    rep = sync_ng_regens_batch(vault, out_dir, db_path=db, apply_club_kits=True, templates_dir=tpl_dir)
    assert rep.processed == 2 and rep.failed == 0
    card_rm = np.asarray(Image.open(out_dir / "r-4001.png").convert("RGBA"))
    # Chest pixel (255, 80) must be crimson red from Zz_Titular_2627 (R > 160, G < 60), NOT green staff or yellow archive!
    assert int(card_rm[255, 80, 0]) > 160 and int(card_rm[255, 80, 1]) < 60

    card_other = np.asarray(Image.open(out_dir / "r-4002.png").convert("RGBA"))
    # Must NOT wear bright green Aa_Staff_999777 (G > R + 120)
    assert not (int(card_other[255, 80, 1]) > int(card_other[255, 80, 0]) + 100)

