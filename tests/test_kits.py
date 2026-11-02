"""RED->GREEN deterministic tests for 3-Tier Kit Resolver and P_clothes=0 Z-Stack compositor."""

from __future__ import annotations

from pathlib import Path
import numpy as np
from PIL import Image

from backend.core.paths import WORKSPACE_ROOT
from backend.services.kits import (
    calibrate_textile_albedo_rgb,
    dress_or_frame_portrait,
    index_fm_graphics_packs,
    init_state_db,
    resolve_club_kit,
    save_kit_override,
)
from backend.services.vision import srgb_to_oklab

SAMPLE_DF11 = WORKSPACE_ROOT / "tests" / "fixtures" / "sample_portrait.png"


def test_albedo_calibration_clamps_pure_black_and_white_oklab() -> None:
    blk, wht = calibrate_textile_albedo_rgb("#000000"), calibrate_textile_albedo_rgb("#FFFFFF")
    l_blk = float(srgb_to_oklab(np.array([[blk]], dtype=np.float32) / 255.0)[0, 0, 0])
    l_wht = float(srgb_to_oklab(np.array([[wht]], dtype=np.float32) / 255.0)[0, 0, 0])
    assert 0.14 <= l_blk <= 0.18 and 0.93 <= l_wht <= 0.96


def test_crest_never_drives_kit_color_and_3tier_hierarchy(tmp_path: Path) -> None:
    db_path, gfx = tmp_path / "state.sqlite3", tmp_path / "graphics"
    (gfx / "logos").mkdir(parents=True)
    Image.new("RGBA", (64, 64), (0, 200, 40, 255)).save(gfx / "logos" / "776.png")
    (gfx / "logos" / "config.xml").write_text('<record><list id="maps"><record from="776" to="graphics/pictures/club/776/logo"/></list></record>', encoding="utf-8")
    index_fm_graphics_packs(gfx, db_path=db_path)

    it_kit = resolve_club_kit("776", db_path=db_path)
    assert it_kit.tier == "seed" and it_kit.crest_path and it_kit.crest_path.endswith("776.png")
    r, g, b = calibrate_textile_albedo_rgb(it_kit.primary)
    assert b > r + 70 and b > g

    (gfx / "kits").mkdir(parents=True)
    Image.new("RGBA", (120, 120), (120, 30, 190, 255)).save(gfx / "kits" / "rm_home.png")
    (gfx / "kits" / "config.xml").write_text('<record><list id="maps"><record from="rm_home" to="graphics/pictures/team/1736/kits/home"/></list></record>', encoding="utf-8")
    index_fm_graphics_packs(gfx, db_path=db_path)
    t1 = resolve_club_kit("1736", db_path=db_path)
    pr, pg, pb = calibrate_textile_albedo_rgb(t1.primary)
    assert t1.tier == "2d_kit" and pb > pg + 60 and pr > pg + 30

    save_kit_override("1736", primary="#10B981", secondary="#FFFFFF", pattern="solid", db_path=db_path)
    t3 = resolve_club_kit("1736", db_path=db_path)
    assert t3.tier == "custom" and t3.primary.upper() == "#10B981"


def test_zstack_erases_old_shirt_and_keeps_hair_occluder_on_top(tmp_path: Path) -> None:
    src = Image.open(SAMPLE_DF11).convert("RGBA").crop((20, 18, 240, 292))
    arr = np.asarray(src, dtype=np.uint8).copy()
    arr[130:245, 55:70] = (25, 20, 18, 255)
    seg = np.zeros((arr.shape[0], arr.shape[1], 6), dtype=np.float32)
    seg[30:155, 70:150, 3], seg[155:205, 82:138, 2], seg[195:, :, 4] = 1.0, 1.0, 1.0
    seg[130:245, 55:70, :] = 0.0
    seg[130:245, 55:70, 1] = 1.0

    dressed = dress_or_frame_portrait(Image.fromarray(arr, mode="RGBA"), kit_mode="club", kit_spec=resolve_club_kit("1736", db_path=tmp_path / "s.db"), seg_probs_override=seg)
    out = np.asarray(dressed, dtype=np.uint8)
    rc_r, rc_g, rc_b, rc_a = out[265, 175]
    assert dressed.size == (260, 310) and rc_a == 255 and rc_r > 195 and rc_g > 195 and rc_b > 195
    assert float(out[225:255, 70:92, :3].min()) < 65.0


def test_trapezoid_extension_reaches_y292_on_short_1to1_cutout() -> None:
    arr = np.zeros((220, 220, 4), dtype=np.uint8)
    arr[35:220, 45:175], arr[35:130, 75:145] = (30, 90, 200, 255), (215, 170, 145, 255)
    out = np.asarray(dress_or_frame_portrait(Image.fromarray(arr, mode="RGBA"), kit_mode="original"), dtype=np.uint8)
    assert int(out[291, 130, 3]) == 255 and int(out[291, 130, 2]) > 150


def test_init_state_db_closes_sqlite_handles_on_windows(tmp_path: Path) -> None:
    db_file = tmp_path / "ephemeral_state.sqlite3"
    with init_state_db(db_file) as conn:
        conn.execute("INSERT OR REPLACE INTO squad_map VALUES ('r-1', '1736')")
    # On Windows NTFS, unlink raises PermissionError if any sqlite3/WAL handle leaked
    db_file.unlink()
    assert not db_file.exists()
