"""3-Tier Club Kit Resolver (2D Kits FC'12/SS' -> Seed -> Custom) & P_clothes=0 Z-Stack Compositor."""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

import numpy as np
from defusedxml import ElementTree as SafeET
from PIL import Image

from backend.core.compositor import DF11_HEIGHT, DF11_WIDTH, EYES_Y, premul_over
from backend.core.paths import ASSETS_DIR, get_state_db_path
from backend.services.vision import (
    CLASS_BODY_SKIN,
    CLASS_CLOTHES,
    CLASS_FACE_SKIN,
    CLASS_HAIR,
    CLASS_OTHERS,
    detect_face_pose,
    oklab_to_srgb,
    segment_portrait_classes,
    srgb_to_oklab,
)

KitMode = Literal["original", "club", "staff_polo", "staff_suit"]
_KIT_TO_RE = re.compile(r"graphics/pictures/team/(\d+)/kits/home", re.IGNORECASE)
_LOGO_TO_RE = re.compile(r"graphics/pictures/club/(\d+)/logo", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class KitSpec:
    club_id: str
    name: str
    pattern: str
    primary: str
    secondary: str
    collar: str
    tier: Literal["custom", "2d_kit", "seed", "default"]
    crest_path: str | None = None


def init_state_db(db_path: Path | None = None) -> sqlite3.Connection:
    target = db_path or get_state_db_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(target), timeout=10.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.executescript(
        "CREATE TABLE IF NOT EXISTS fm_assets (club_id TEXT, kind TEXT, file_path TEXT, PRIMARY KEY (club_id, kind));"
        "CREATE TABLE IF NOT EXISTS kit_overrides (club_id TEXT PRIMARY KEY, primary_hex TEXT, secondary_hex TEXT, collar_hex TEXT, pattern TEXT);"
    )
    return conn


@lru_cache(maxsize=1)
def load_seed_kits() -> dict[str, dict[str, str]]:
    return json.loads((ASSETS_DIR / "kits" / "club_kits_seed.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _load_master_jersey() -> dict[str, np.ndarray]:
    with np.load(ASSETS_DIR / "kits" / "master_jersey.npz") as data:
        return {k: data[k] for k in data.files}


def _rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    return f"#{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}"


def calibrate_textile_albedo_rgb(hex_color: str) -> tuple[int, int, int]:
    """Clamp cloth lightness to OKLab L in [0.15, 0.95] so black keeps folds and white never clips."""
    h = hex_color.strip().lstrip("#")
    h = h if len(h) == 6 else "1E293B"
    rgb01 = np.array([int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)], dtype=np.float32) / 255.0
    lab = srgb_to_oklab(rgb01.reshape(1, 1, 3))
    lab[0, 0, 0] = np.clip(lab[0, 0, 0], 0.15, 0.95)
    rgb = np.clip(np.round(oklab_to_srgb(lab)[0, 0] * 255.0), 0, 255).astype(int)
    return (int(rgb[0]), int(rgb[1]), int(rgb[2]))


def _safe_local_png(cfg_dir: Path, rel_from: str, root: Path) -> Path | None:
    if not rel_from or rel_from.startswith(("\\\\", "//")) or ".." in Path(rel_from).parts:
        return None
    cand = (cfg_dir / f"{rel_from}.png").resolve()
    try:
        cand.relative_to(root.resolve())
    except ValueError:
        return None
    return cand if cand.is_file() else None


def index_fm_graphics_packs(graphics_root: Path, db_path: Path | None = None) -> int:
    """Single-pass indexer for 2D Kits (FC'12/SS') and Club Logos (strictly badge-only)."""
    if not graphics_root.is_dir():
        return 0
    rows: list[tuple[str, str, str]] = []
    for cfg in graphics_root.rglob("config.xml"):
        try:
            for _ev, elem in SafeET.iterparse(cfg, events=("end",)):
                if elem.tag == "record":
                    frm, to = elem.attrib.get("from", "").strip(), elem.attrib.get("to", "").strip()
                    m_kit = _KIT_TO_RE.search(to)
                    m_logo = None if m_kit else _LOGO_TO_RE.search(to)
                    if m_kit or m_logo:
                        png = _safe_local_png(cfg.parent, frm, graphics_root)
                        if png is not None:
                            rows.append(((m_kit or m_logo).group(1), "kit_home" if m_kit else "club_logo", str(png)))  # type: ignore[union-attr]
                    elem.clear()
        except Exception:
            continue
    with init_state_db(db_path) as conn:
        conn.executemany("INSERT OR REPLACE INTO fm_assets VALUES (?, ?, ?)", rows)
    return len(rows)


def save_kit_override(
    club_id: str, primary: str, secondary: str = "#F8FAFC", collar: str | None = None, pattern: str = "solid", db_path: Path | None = None
) -> None:
    with init_state_db(db_path) as conn:
        conn.execute("INSERT OR REPLACE INTO kit_overrides VALUES (?, ?, ?, ?, ?)", (str(club_id).strip(), primary, secondary, collar or secondary, pattern))


def _extract_2d_kit_colors(kit_png: Path) -> tuple[str, str, str, str]:
    arr = np.asarray(Image.open(kit_png).convert("RGBA"), dtype=np.uint8)
    h, w = arr.shape[:2]
    chest = arr[round(h * 0.35) : max(round(h * 0.72), 1), round(w * 0.32) : max(round(w * 0.68), 1)]
    opaque = chest[chest[:, :, 3] > 180][:, :3]
    if len(opaque) == 0:
        return ("#1E293B", "#F8FAFC", "#F8FAFC", "solid")
    if float(np.std(chest[:, :, :3].mean(axis=0))) > 28.0:
        q1 = tuple(int(v) for v in np.percentile(opaque, 25, axis=0).round())
        q3 = tuple(int(v) for v in np.percentile(opaque, 75, axis=0).round())
        return (_rgb_to_hex(q1), _rgb_to_hex(q3), _rgb_to_hex(q3), "stripes")
    return (_rgb_to_hex(tuple(int(v) for v in np.median(opaque, axis=0).round())), "#F8FAFC", "#F8FAFC", "solid")


def resolve_club_kit(club_id: str, db_path: Path | None = None) -> KitSpec:
    """Resolve club kit strictly via 3-Tier hierarchy (Custom -> 2D Kit -> Seed); never infer colors from crest."""
    cid = str(club_id).strip()
    seed = load_seed_kits().get(cid)
    club_name = seed["name"] if seed else f"Club {cid}"
    with init_state_db(db_path) as conn:
        cr = conn.execute("SELECT file_path FROM fm_assets WHERE club_id=? AND kind='club_logo'", (cid,)).fetchone()
        crest_path = cr[0] if cr and Path(cr[0]).is_file() else None
        ov = conn.execute("SELECT primary_hex, secondary_hex, collar_hex, pattern FROM kit_overrides WHERE club_id=?", (cid,)).fetchone()
        if ov:
            return KitSpec(cid, club_name, ov[3], ov[0], ov[1], ov[2], "custom", crest_path)
        kr = conn.execute("SELECT file_path FROM fm_assets WHERE club_id=? AND kind='kit_home'", (cid,)).fetchone()
        if kr and Path(kr[0]).is_file():
            p_hex, s_hex, c_hex, pat = _extract_2d_kit_colors(Path(kr[0]))
            return KitSpec(cid, club_name, pat, p_hex, s_hex, c_hex, "2d_kit", crest_path)
    if seed:
        return KitSpec(cid, club_name, seed["pattern"], seed["primary"], seed["secondary"], seed["collar"], "seed", crest_path)
    return KitSpec(cid, club_name, "solid", "#1E293B", "#F8FAFC", "#F8FAFC", "default", crest_path)


def _extend_short_torso_trapezoid(canvas: np.ndarray) -> np.ndarray:
    row_has_fg = np.where(canvas[:, 50:210, 3].max(axis=1) > 180)[0]
    if len(row_has_fg) == 0 or int(row_has_fg[-1]) >= 292 or int(row_has_fg[-1]) < 130:
        return canvas
    y_end = int(row_has_fg[-1])
    band = canvas[max(0, y_end - 8) : y_end + 1].mean(axis=0)
    out = canvas.copy()
    xs = np.arange(DF11_WIDTH, dtype=np.float32)
    for y in range(y_end, 294):
        flare = 1.0 + 0.08 * ((y - y_end) / max(294 - y_end, 1))
        out[y] = band[np.clip(np.round(130.0 + (xs - 130.0) / flare), 0, DF11_WIDTH - 1).astype(int)].round().astype(np.uint8)
    return out


def _render_z2_kit(kit: KitSpec, kit_mode: KitMode, collar_y: int, shift_x: int) -> tuple[np.ndarray, np.ndarray]:
    tpl = _load_master_jersey()
    th, tw = tpl["front_body_mask"].shape
    xx = np.broadcast_to(np.arange(tw, dtype=np.float32)[None, :], (th, tw))
    yy = np.broadcast_to(np.arange(th, dtype=np.float32)[:, None], (th, tw))
    dx = xx - 130.0
    p_rgb = np.array(calibrate_textile_albedo_rgb(kit.primary), dtype=np.float32)
    s_rgb = np.array(calibrate_textile_albedo_rgb(kit.secondary), dtype=np.float32)
    c_rgb = np.array(calibrate_textile_albedo_rgb(kit.collar), dtype=np.float32)

    if kit_mode == "staff_suit":
        cloth = np.broadcast_to(np.array(calibrate_textile_albedo_rgb("#F8FAFC"), dtype=np.float32), (th, tw, 3)).copy()
        t_m = tpl["staff_tie_mask"][:, :, None].astype(np.float32) / 255.0
        j_m = tpl["staff_jacket_mask"][:, :, None].astype(np.float32) / 255.0
        cloth = (cloth * (1.0 - t_m) + p_rgb * t_m) * (1.0 - j_m) + np.array(calibrate_textile_albedo_rgb("#161E2E"), dtype=np.float32) * j_m
    else:
        pat = "solid" if kit_mode == "staff_polo" else kit.pattern
        sel = (
            ((np.floor((dx + 130.0) / 18.0) % 2) == 0)[:, :, None] if pat == "stripes"
            else (dx < 0.0)[:, :, None] if pat == "halves"
            else ((np.floor(yy / 16.0) % 2) == 0)[:, :, None] if pat == "hoops"
            else (np.abs((dx + 25.0) - (yy - 55.0) * 0.95) > 16.0)[:, :, None] if pat == "sash"
            else np.ones((th, tw, 1), dtype=bool)
        )
        trim = tpl["collar_trim_mask"][:, :, None].astype(np.float32) / 255.0
        cloth = np.where(sel, p_rgb, s_rgb) * (1.0 - trim) + c_rgb * trim

    lit = np.clip(np.round(cloth * (tpl["shading_map"][:, :, None].astype(np.float32) / 128.0)), 0, 255).astype(np.uint8)
    z2_back = np.zeros((DF11_HEIGHT, DF11_WIDTH, 4), dtype=np.uint8)
    z2_front = np.zeros((DF11_HEIGHT, DF11_WIDTH, 4), dtype=np.uint8)
    y0, rows = max(0, collar_y - 18), min(th, DF11_HEIGHT - max(0, collar_y - 18))
    for dst, mask_key in ((z2_back, "back_collar_mask"), (z2_front, "front_body_mask")):
        sub = np.concatenate([lit[:rows], tpl[mask_key][:rows, :, None]], axis=-1)
        dst[y0 : y0 + rows] = np.roll(sub, shift_x, axis=1) if shift_x else sub
        if y0 + rows < DF11_HEIGHT and mask_key == "front_body_mask":
            dst[y0 + rows : DF11_HEIGHT] = dst[y0 + rows - 1 : y0 + rows]

    if kit.crest_path and Path(kit.crest_path).is_file():
        badge = np.asarray(Image.open(kit.crest_path).convert("RGBA").resize((18, 18), Image.Resampling.LANCZOS), dtype=np.uint8)
        bx, by = int(np.clip(156 + shift_x, 24, 215)), int(np.clip(collar_y + 34, 180, 272))
        patch = np.zeros((DF11_HEIGHT, DF11_WIDTH, 4), dtype=np.uint8)
        patch[by : by + 18, bx : bx + 18] = badge
        z2_front = premul_over(z2_front, patch)
    return z2_back, z2_front


def dress_or_frame_portrait(
    portrait_rgba: Image.Image,
    kit_mode: KitMode = "original",
    kit_spec: KitSpec | None = None,
    seg_probs_override: np.ndarray | None = None,
) -> Image.Image:
    """Align portrait to DF11 cranial geometry (260x310) and optionally execute P_clothes=0 Z0..Z3 kit swap."""
    pose = detect_face_pose(portrait_rgba)
    w, h = portrait_rgba.size
    if pose is not None:
        scale = float(np.clip(42.0 / max(pose.ipd, 14.0), 0.35, 2.4))
        nw, nh = max(1, round(w * scale)), max(1, round(h * scale))
        ox, oy, yaw = round(130.0 - pose.eye_center[0] * scale), round(float(EYES_Y) - pose.eye_center[1] * scale), pose.yaw
    else:
        ys, xs = np.where(np.asarray(portrait_rgba.getchannel("A"), dtype=np.uint8) > 24)
        top_y, fg_w = (int(ys.min()), max(int(xs.max() - xs.min() + 1), 100)) if len(ys) else (0, w)
        scale = float(np.clip(195.0 / fg_w, 0.4, 2.0))
        nw, nh = max(1, round(w * scale)), max(1, round(h * scale))
        ox, oy, yaw = round((DF11_WIDTH - nw) * 0.5), round(28.0 - top_y * scale), 0.0

    aligned = np.zeros((DF11_HEIGHT, DF11_WIDTH, 4), dtype=np.uint8)
    resized = np.asarray(portrait_rgba.convert("RGBA").resize((nw, nh), Image.Resampling.LANCZOS), dtype=np.uint8)
    cx0, cy0, cx1, cy1 = max(0, ox), max(0, oy), min(DF11_WIDTH, ox + nw), min(DF11_HEIGHT, oy + nh)
    if cx1 > cx0 and cy1 > cy0:
        aligned[cy0:cy1, cx0:cx1] = resized[cy0 - oy : cy1 - oy, cx0 - ox : cx1 - ox]
    if kit_mode == "original":
        return Image.fromarray(_extend_short_torso_trapezoid(aligned), mode="RGBA")

    if seg_probs_override is not None:
        probs = np.zeros((DF11_HEIGHT, DF11_WIDTH, 6), dtype=np.float32)
        for c in range(6):
            ch_img = Image.fromarray(seg_probs_override[:, :, c].astype(np.float32), mode="F").resize((nw, nh), Image.Resampling.BILINEAR)
            if cx1 > cx0 and cy1 > cy0:
                probs[cy0:cy1, cx0:cx1, c] = np.asarray(ch_img, dtype=np.float32)[cy0 - oy : cy1 - oy, cx0 - ox : cx1 - ox]
    else:
        probs = segment_portrait_classes(Image.fromarray(aligned, mode="RGBA"))

    collar_y, shift_x = 212, round(yaw * 8.0)
    skin_mask = ((probs[:, :, CLASS_FACE_SKIN] + probs[:, :, CLASS_BODY_SKIN]) > 0.45) & (aligned[:, :, 3] > 160)
    skin_rgb = np.median(aligned[skin_mask][:, :3], axis=0) if np.any(skin_mask) else np.array([204.0, 162.0, 138.0])
    neck_lab = srgb_to_oklab((skin_rgb.reshape(1, 1, 3) / 255.0).astype(np.float32))
    neck_lab[0, 0, 0] = max(0.18, float(neck_lab[0, 0, 0]) - 0.045)
    z1_neck = np.zeros((DF11_HEIGHT, DF11_WIDTH, 4), dtype=np.uint8)
    z1_neck[collar_y - 46 : collar_y + 26, :, :3] = np.clip(np.round(oklab_to_srgb(neck_lab)[0, 0] * 255.0), 0, 255).astype(np.uint8)
    z1_neck[collar_y - 46 : collar_y + 26, :, 3] = np.clip((26.0 - np.abs(np.arange(DF11_WIDTH, dtype=np.float32) - (130.0 + shift_x * 0.7))) * 85.0, 0.0, 255.0).astype(np.uint8)[None, :]

    z2_back, z2_front = _render_z2_kit(kit_spec or resolve_club_kit("0"), kit_mode, collar_y, shift_x)
    upper_gate = np.clip((collar_y - 26.0 - np.arange(DF11_HEIGHT, dtype=np.float32)[:, None]) / 10.0, 0.0, 1.0)
    occluder_p = np.clip(probs[:, :, CLASS_HAIR] + probs[:, :, CLASS_FACE_SKIN] + probs[:, :, CLASS_OTHERS], 0.0, 1.0)
    z3_head = aligned.copy()
    z3_head[:, :, 3] = np.clip(np.round(aligned[:, :, 3].astype(np.float32) * np.maximum((1.0 - probs[:, :, CLASS_CLOTHES]) * upper_gate, occluder_p)), 0, 255).astype(np.uint8)
    return Image.fromarray(premul_over(premul_over(premul_over(z2_back, z1_neck), z2_front), z3_head), mode="RGBA")
