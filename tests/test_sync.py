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
