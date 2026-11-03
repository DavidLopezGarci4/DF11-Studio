"""Shirt-only template sanitizer, subpixel skin-spill decontaminator, and collar socket profiler."""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter, ImageOps

import backend.services.vision as vision_mod
from backend.core.compositor import DF11_HEIGHT, DF11_WIDTH, load_df11_assets
from backend.core.fm_config import safe_ntfs_replace
from backend.core.image_guard import load_guarded_image
from backend.core.paths import get_raw_tshirt_archive_dir, get_state_db_path, get_tshirt_templates_dir
from backend.services.kits import init_state_db

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".avif"}


@dataclass(frozen=True, slots=True)
class CollarProfile:
    left_rim: tuple[int, int]
    right_rim: tuple[int, int]
    apex: tuple[int, int]
    collar_width: int
    y_top_curve: tuple[int, ...]

    def to_json(self) -> str:
        return json.dumps(
            {
                "left_rim": list(self.left_rim),
                "right_rim": list(self.right_rim),
                "apex": list(self.apex),
                "collar_width": self.collar_width,
                "y_top_curve": list(self.y_top_curve),
            }
        )

    @classmethod
    def from_json(cls, raw: str) -> CollarProfile:
        d = json.loads(raw)
        return cls(
            left_rim=(int(d["left_rim"][0]), int(d["left_rim"][1])),
            right_rim=(int(d["right_rim"][0]), int(d["right_rim"][1])),
            apex=(int(d["apex"][0]), int(d["apex"][1])),
            collar_width=int(d["collar_width"]),
            y_top_curve=tuple(int(v) for v in d["y_top_curve"]),
        )


@dataclass(frozen=True, slots=True)
class ShirtTemplate:
    template_id: str
    filename: str
    display_name: str
    club_id: str
    file_path: Path
    collar: CollarProfile


def _needs_shirt_sanitization(im_rgba: Image.Image) -> bool:
    """Return True if the image is not yet a clean 260x310 shirt-only RGBA cutout."""
    if im_rgba.size != (DF11_WIDTH, DF11_HEIGHT):
        return True
    arr = np.asarray(im_rgba.convert("RGBA"), dtype=np.uint8)
    alpha = arr[:, :, 3]
    # Any opaque pixels in the head zone (y < 158) or outer DF11 ring means raw/unclean source
    if int(alpha[:158, :].max()) > 0 or int(alpha[:, :18].max()) > 0 or int(alpha[:, 243:].max()) > 0 or int(alpha[294:, :].max()) > 0:
        return True
    probs = vision_mod.segment_portrait_classes(im_rgba)
    skin_hair = probs[:, :, vision_mod.CLASS_FACE_SKIN] + probs[:, :, vision_mod.CLASS_BODY_SKIN] + probs[:, :, vision_mod.CLASS_HAIR]
    residual_skin_px = int(((skin_hair > 0.45) & (alpha > 48)).sum())
    return residual_skin_px > 40


def _frame_to_df11_stage(raw_rgba: Image.Image, zoom: float = 1.0, pan_x: float = 0.0, pan_y: float = 0.0) -> Image.Image:
    im = raw_rgba.convert("RGBA")
    if im.size == (DF11_WIDTH, DF11_HEIGHT) and abs(zoom - 1.0) < 1e-3 and abs(pan_x) < 0.5 and abs(pan_y) < 0.5:
        return im
    w, h = im.size
    fit_base = max(DF11_WIDTH / max(w, 1), DF11_HEIGHT / max(h, 1))
    eff = float(np.clip(fit_base * max(zoom, 0.25), 0.05, 8.0))
    nw, nh = max(1, round(w * eff)), max(1, round(h * eff))
    resized = im if (nw, nh) == (w, h) else im.resize((nw, nh), Image.Resampling.LANCZOS)
    stage = Image.new("RGBA", (DF11_WIDTH, DF11_HEIGHT), (0, 0, 0, 0))
    x0 = round((DF11_WIDTH - nw) * 0.5 + pan_x)
    y0 = round((DF11_HEIGHT - nh) * 0.5 + pan_y)
    stage.alpha_composite(resized, (x0, y0))
    return stage


def sanitize_shirt_template_rgba(
    raw_rgba: Image.Image,
    symmetrize_shoulders: bool = True,
    shoulder_boost: float = 0.0,
    zoom: float = 1.0,
    pan_x: float = 0.0,
    pan_y: float = 0.0,
) -> Image.Image:
    """Strip face, neck, background, and DF11 outer frame; preserve full white/dark shoulders to frame edges."""
    card = _frame_to_df11_stage(raw_rgba, zoom=zoom, pan_x=pan_x, pan_y=pan_y)

    arr = np.asarray(card, dtype=np.uint8).copy()
    rgb_f = arr[:, :, :3].astype(np.float32)

    # Mathematically un-composite baked DF11 inner-bevel shadow along edges while preserving diagonal sleeve stripes
    inner_mask_im, frame_ov_im = load_df11_assets()
    inner_mask_f = np.asarray(inner_mask_im, dtype=np.float32) / 255.0
    ov_arr = np.asarray(frame_ov_im, dtype=np.float32)
    ov_a = (ov_arr[:, :, 3:4] / 255.0) * (inner_mask_f[:, :, None] > 0.1)
    edge_band = np.zeros((DF11_HEIGHT, DF11_WIDTH, 1), dtype=bool)
    edge_band[:, 19:26, 0] = True
    edge_band[:, 235:242, 0] = True
    edge_band[286:293, :, 0] = True
    rgb_unbeveled = (rgb_f - ov_arr[:, :, :3] * ov_a) / np.maximum(1.0 - ov_a, 0.38)
    rgb_f = np.where(edge_band & (ov_a > 0.02), np.clip(rgb_unbeveled, 0.0, 255.0), rgb_f)

    probs = vision_mod.segment_portrait_classes(card)
    p_clothes = probs[:, :, vision_mod.CLASS_CLOTHES]
    p_skin_hair = (
        probs[:, :, vision_mod.CLASS_FACE_SKIN]
        + probs[:, :, vision_mod.CLASS_BODY_SKIN]
        + probs[:, :, vision_mod.CLASS_HAIR]
    )
    raw_a = arr[:, :, 3].astype(np.float32) / 255.0
    is_pre_cut = int((arr[:150, :18, 3] == 0).sum()) > 2000 and int(arr[:140, :, 3].max()) == 0
    biref_a = raw_a if is_pre_cut else (np.asarray(vision_mod.remove_background_birefnet(card), dtype=np.uint8)[:, :, 3].astype(np.float32) / 255.0) * raw_a

    yy, xx = np.mgrid[0:DF11_HEIGHT, 0:DF11_WIDTH].astype(np.float32)
    non_skin_gate = np.clip((0.36 - p_skin_hair) / 0.24, 0.0, 1.0)
    cloth_soft = np.where(yy >= 176.0, np.clip((p_clothes - 0.30) / 0.28, 0.0, 1.0) * non_skin_gate, 0.0)

    # True DF11 inner-window mirror axis is x = 130.0 (19 <-> 241 => x_mirror = 260 - x)
    x_mir = np.clip(260 - np.arange(DF11_WIDTH, dtype=np.int32), 0, DF11_WIDTH - 1)
    outer_shoulder_zone = (np.abs(xx - 130.0) >= 45.0) & (yy >= 188.0)

    # Outside the neck/collar opening (|x-130| >= 45, y >= 188), ANY foreground pixel with zero skin/hair IS the shirt
    # (prevents MediaPipe 256x256 false CLASS_BG scores on white shirts like Caucasian0 & ItalMed9 from chewing BiRefNet=1.0 shoulders)
    collar_neck_zone = np.clip((52.0 - np.abs(xx - 130.0)) / 10.0, 0.0, 1.0) * np.clip((232.0 - yy) / 14.0, 0.0, 1.0)
    collar_cloth_gate = np.clip((p_clothes - 0.90 * p_skin_hair - 0.12) / 0.42, 0.0, 1.0)
    effective_gate = collar_neck_zone * collar_cloth_gate + (1.0 - collar_neck_zone) * non_skin_gate
    effective_gate = np.where(yy < 162.0, 0.0, effective_gate)

    fg_shirt = np.maximum(biref_a, cloth_soft) * effective_gate
    if symmetrize_shoulders:
        fg_mirror = fg_shirt[:, x_mir]
        fg_shirt = np.where(outer_shoulder_zone & (non_skin_gate > 0.75), np.maximum(fg_shirt, fg_mirror * 0.98), fg_shirt)

    # Anatomical shoulder & downward sleeve solidity: sleeves below the shoulder slope never have transparent holes
    sleeve_cols = (np.abs(xx - 130.0) >= 46.0) & (yy >= 196.0) & (non_skin_gate > 0.80)
    solid_seed = np.where(sleeve_cols & (fg_shirt > 0.58), fg_shirt, 0.0)
    downward_solid = np.maximum.accumulate(solid_seed, axis=0)
    fg_shirt = np.where(sleeve_cols & (yy >= 206.0), np.maximum(fg_shirt, downward_solid), fg_shirt)

    if shoulder_boost > 0.01:
        # Optional white-on-white shoulder completion along natural trapezius/deltoid slope from detected mid-shoulder
        boost = float(np.clip(shoulder_boost, 0.0, 1.0))
        for side_sign, x_ref in ((-1, 62), (1, 198)):
            ys_ref = np.where(fg_shirt[180:245, x_ref] > 0.55)[0]
            if len(ys_ref):
                y_anchor = float(180 + ys_ref[0])
                slope = 0.48 - 0.14 * boost
                if side_sign < 0:
                    xs_side = np.arange(19, x_ref, dtype=np.float32)
                    y_curve = y_anchor + slope * (float(x_ref) - xs_side)
                    fill_zone = (yy[:, 19:x_ref] >= y_curve[None, :]) & (non_skin_gate[:, 19:x_ref] > 0.85)
                    fg_shirt[:, 19:x_ref] = np.where(fill_zone, np.maximum(fg_shirt[:, 19:x_ref], 0.98), fg_shirt[:, 19:x_ref])
                else:
                    xs_side = np.arange(x_ref + 1, 242, dtype=np.float32)
                    y_curve = y_anchor + slope * (xs_side - float(x_ref))
                    fill_zone = (yy[:, x_ref + 1 : 242] >= y_curve[None, :]) & (non_skin_gate[:, x_ref + 1 : 242] > 0.85)
                    fg_shirt[:, x_ref + 1 : 242] = np.where(
                        fill_zone, np.maximum(fg_shirt[:, x_ref + 1 : 242], 0.98), fg_shirt[:, x_ref + 1 : 242]
                    )

    # Normalized Gaussian RGB decontamination from pure interior fabric -> zero pink skin halo on collar rim
    w_pure = (fg_shirt > 0.85).astype(np.float32) * np.clip((0.06 - p_skin_hair) / 0.06, 0.0, 1.0)
    w_pure[:182, :] *= np.clip((p_clothes[:182, :] - 0.65) / 0.25, 0.0, 1.0)
    premul = np.concatenate([rgb_f * w_pure[:, :, None], w_pure[:, :, None] * 255.0], axis=-1).clip(0.0, 255.0).round().astype(np.uint8)
    blurred = np.asarray(Image.fromarray(premul, mode="RGBA").filter(ImageFilter.GaussianBlur(2.6)), dtype=np.float32)
    w_blur = blurred[:, :, 3:4] / 255.0
    pure_rgb = np.where(w_blur > 1e-3, blurred[:, :, :3] / np.maximum(w_blur, 1e-3), rgb_f)
    decontam_t = np.where(
        w_blur[:, :, 0] > 0.02,
        np.clip(p_skin_hair * 3.5 + (1.0 - effective_gate) * 1.15, 0.0, 1.0),
        0.0,
    )[:, :, None]
    clean_rgb = np.clip(np.round(rgb_f * (1.0 - decontam_t) + pure_rgb * decontam_t), 0.0, 255.0).astype(np.uint8)

    raw_alpha_img = Image.fromarray(np.clip(np.round(fg_shirt * 255.0), 0.0, 255.0).astype(np.uint8), mode="L")
    smooth_alpha = np.asarray(raw_alpha_img.filter(ImageFilter.GaussianBlur(0.65)), dtype=np.float32) / 255.0
    # Boost high-confidence interior (>0.78) back to 1.0 so GaussianBlur(0.65) never softens solid outer edges at x=19, 241
    crisp_alpha = np.where(fg_shirt > 0.85, np.maximum(smooth_alpha, 0.995), smooth_alpha)
    final_a = np.clip(np.round(crisp_alpha * inner_mask_f * 255.0), 0.0, 255.0).astype(np.uint8)
    final_a[:162, :] = 0
    final_a[:, :19] = 0
    final_a[:, 242:] = 0
    final_a[293:, :] = 0

    clean_rgb = np.where(final_a[:, :, None] > 0, clean_rgb, 0)
    out = np.concatenate([clean_rgb, final_a[:, :, None]], axis=-1)
    return Image.fromarray(out, mode="RGBA")


def extract_collar_profile(clean_shirt_rgba: Image.Image) -> CollarProfile:
    """Measure exact left/right collar rim peaks, deepest V/U apex, and shoulder curve from shirt alpha."""
    arr = np.asarray(clean_shirt_rgba.convert("RGBA"), dtype=np.uint8)
    alpha = arr[:, :, 3]
    y_top = np.full(DF11_WIDTH, DF11_HEIGHT, dtype=np.int32)
    for x in range(19, 242):
        ys = np.where(alpha[160:, x] > 120)[0]
        if len(ys):
            y_top[x] = int(ys[0] + 160)

    # 3-tap median smoothing across center collar search span to reject single-pixel noise
    sm = y_top.copy()
    for x in range(55, 206):
        sm[x] = int(np.median(y_top[x - 1 : x + 2]))

    left_slice = sm[62:123]
    x_l = int(62 + np.argmin(left_slice)) if int(left_slice.min()) < DF11_HEIGHT else 92
    y_l = int(sm[x_l]) if int(sm[x_l]) < DF11_HEIGHT else 196

    right_slice = sm[138:199]
    x_r = int(138 + np.argmin(right_slice)) if int(right_slice.min()) < DF11_HEIGHT else 168
    y_r = int(sm[x_r]) if int(sm[x_r]) < DF11_HEIGHT else 196

    if x_r - x_l < 36:
        x_l, x_r = 92, 168
        y_l = y_r = min(y_l, y_r, 198)

    mid_slice = sm[x_l + 4 : x_r - 3]
    if len(mid_slice) and int(mid_slice.max()) < DF11_HEIGHT:
        x_v = int(x_l + 4 + np.argmax(mid_slice))
        y_v = int(sm[x_v])
    else:
        x_v = (x_l + x_r) // 2
        y_v = max(y_l, y_r) + 26

    y_v = max(y_v, min(y_l, y_r) + 6)
    return CollarProfile(
        left_rim=(x_l, y_l),
        right_rim=(x_r, y_r),
        apex=(x_v, y_v),
        collar_width=max(40, x_r - x_l),
        y_top_curve=tuple(int(v) for v in y_top),
    )


def _atomic_write_png(im_rgba: Image.Image, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    im_rgba.save(buf, format="PNG", compress_level=6)
    fd, tname = tempfile.mkstemp(prefix=f".{dst.stem}_", suffix=".tmp", dir=str(dst.parent))
    tp = Path(tname)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(buf.getvalue())
        safe_ntfs_replace(tp, dst)
    finally:
        tp.unlink(missing_ok=True)


def sync_tshirt_templates_dir(
    tpl_dir: Path | None = None,
    raw_archive_dir: Path | None = None,
    db_path: Path | None = None,
    force_from_archive: bool = False,
) -> list[ShirtTemplate]:
    """Ensure every image in tshirt_templates is a clean shirt-only PNG, archiving raw originals safely."""
    folder = (tpl_dir or get_tshirt_templates_dir()).resolve()
    archive = (raw_archive_dir or get_raw_tshirt_archive_dir()).resolve()
    folder.mkdir(parents=True, exist_ok=True)

    with init_state_db(db_path or get_state_db_path()) as conn:
        existing = {
            row[0]: {
                "filename": row[1],
                "display_name": row[2],
                "club_id": row[3],
                "sha256": row[4],
                "mtime_ns": int(row[5]),
                "size": int(row[6]),
                "collar_json": row[7],
            }
            for row in conn.execute(
                "SELECT template_id, filename, display_name, club_id, sha256, mtime_ns, size, collar_json FROM shirt_templates"
            ).fetchall()
        }

        out: list[ShirtTemplate] = []
        seen_ids: set[str] = set()
        seen_lower: set[str] = set()
        candidates = sorted(
            (p for p in folder.iterdir() if p.is_file() and not p.name.startswith(".") and p.suffix.lower() in IMAGE_EXTS),
            key=lambda x: (x.stem.lower(), 0 if x.suffix.lower() == ".png" else 1, x.name),
        )
        for p in candidates:
            tid_low = p.stem.lower()
            if tid_low in seen_lower:
                try:
                    if p.stat().st_size <= 20 * 1024 * 1024:
                        dup_bytes = p.read_bytes()
                        dup_hash = hashlib.sha256(dup_bytes).hexdigest()
                        archive.mkdir(parents=True, exist_ok=True)
                        dup_bak = archive / f"{p.stem}_{dup_hash[:10]}{p.suffix.lower()}"
                        if not dup_bak.is_file():
                            dup_bak.write_bytes(dup_bytes)
                    p.unlink(missing_ok=True)
                except OSError:
                    pass
                continue
            tid = p.stem
            st = p.stat()
            cached = existing.get(tid) or next((v for k, v in existing.items() if k.lower() == tid_low), None)
            cached_key = next((k for k in existing if k.lower() == tid_low), tid)
            if (
                not force_from_archive
                and cached
                and cached["filename"].lower() == p.name.lower()
                and cached["mtime_ns"] == st.st_mtime_ns
                and cached["size"] == st.st_size
            ):
                seen_lower.add(tid_low)
                seen_ids.add(cached_key)
                out.append(
                    ShirtTemplate(
                        template_id=cached_key,
                        filename=p.name,
                        display_name=cached["display_name"],
                        club_id=cached["club_id"],
                        file_path=p,
                        collar=CollarProfile.from_json(cached["collar_json"]),
                    )
                )
                continue

            arch_re = re.compile(rf"^{re.escape(tid)}_[0-9a-f]{{10}}$", re.IGNORECASE)
            archived = (
                sorted(a for a in archive.iterdir() if a.is_file() and a.suffix.lower() in IMAGE_EXTS and arch_re.match(a.stem))
                if force_from_archive and archive.is_dir()
                else []
            )
            src_file = archived[-1] if archived else p
            try:
                guarded = load_guarded_image(src_file)
                raw_bytes = src_file.read_bytes()
                im = guarded.image
            except Exception:
                continue

            target_png = folder / f"{tid}.png"
            if force_from_archive or _needs_shirt_sanitization(im) or p.suffix.lower() != ".png":
                if not archived:
                    raw_hash = hashlib.sha256(raw_bytes).hexdigest()
                    archive.mkdir(parents=True, exist_ok=True)
                    backup_path = archive / f"{tid}_{raw_hash[:10]}{p.suffix.lower()}"
                    if not backup_path.is_file():
                        backup_path.write_bytes(raw_bytes)
                clean_im = sanitize_shirt_template_rgba(im)
                if p.resolve() == target_png.resolve() and p.name != target_png.name:
                    p.unlink(missing_ok=True)
                _atomic_write_png(clean_im, target_png)
                if p.resolve() != target_png.resolve():
                    p.unlink(missing_ok=True)
            else:
                clean_im = im
                if p.name != target_png.name:
                    _atomic_write_png(clean_im, target_png)

            actual_file = next((x for x in folder.iterdir() if x.is_file() and x.name.lower() == target_png.name.lower()), target_png)
            collar = extract_collar_profile(clean_im)
            clean_bytes = actual_file.read_bytes()
            clean_sha = hashlib.sha256(clean_bytes).hexdigest()
            clean_st = actual_file.stat()
            disp = cached["display_name"] if cached else tid
            cid = cached["club_id"] if cached else ""

            if cached_key != tid:
                conn.execute("DELETE FROM shirt_templates WHERE template_id=?", (cached_key,))
            conn.execute(
                "INSERT OR REPLACE INTO shirt_templates VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (tid, actual_file.name, disp, cid, clean_sha, clean_st.st_mtime_ns, clean_st.st_size, collar.to_json()),
            )
            seen_lower.add(tid_low)
            seen_ids.add(tid)
            out.append(
                ShirtTemplate(
                    template_id=tid,
                    filename=actual_file.name,
                    display_name=disp,
                    club_id=cid,
                    file_path=actual_file,
                    collar=collar,
                )
            )

        out.sort(key=lambda t: t.template_id.lower())

        for stale_id in set(existing.keys()) - seen_ids:
            conn.execute("DELETE FROM shirt_templates WHERE template_id=?", (stale_id,))

    return out


def rename_shirt_template(
    template_id: str,
    display_name: str,
    club_id: str = "",
    tpl_dir: Path | None = None,
    db_path: Path | None = None,
) -> ShirtTemplate:
    """Update human-friendly name and optional FM club_id binding for a shirt template."""
    clean_name = display_name.strip() or template_id
    clean_club = club_id.strip()
    items = sync_tshirt_templates_dir(tpl_dir=tpl_dir, db_path=db_path)
    match = next((t for t in items if t.template_id == template_id), None)
    if match is None:
        raise ValueError(f"Plantilla de camiseta no encontrada: {template_id}")
    with init_state_db(db_path or get_state_db_path()) as conn:
        if clean_club:
            conn.execute("UPDATE shirt_templates SET club_id='' WHERE club_id=? AND template_id!=?", (clean_club, template_id))
        conn.execute(
            "UPDATE shirt_templates SET display_name=?, club_id=? WHERE template_id=?",
            (clean_name, clean_club, template_id),
        )
    return ShirtTemplate(
        template_id=match.template_id,
        filename=match.filename,
        display_name=clean_name,
        club_id=clean_club,
        file_path=match.file_path,
        collar=match.collar,
    )


_WIN_RESERVED = frozenset(
    {"CON", "PRN", "AUX", "NUL"} | {f"COM{i}" for i in range(1, 10)} | {f"LPT{i}" for i in range(1, 10)}
)


def slugify_template_id(name: str, fallback: str = "Camiseta") -> str:
    slug = re.sub(r"[^A-Za-z0-9_-]+", "_", name.strip()).strip("_")[:48] or fallback
    return f"{slug}_tpl" if slug.upper() in _WIN_RESERVED else slug


def save_new_shirt_template(
    clean_rgba: Image.Image,
    raw_bytes: bytes | None,
    display_name: str,
    club_id: str = "",
    template_id: str = "",
    tpl_dir: Path | None = None,
    raw_archive_dir: Path | None = None,
    db_path: Path | None = None,
) -> ShirtTemplate:
    """Save a newly extracted shirt-only PNG into tshirt_templates and register its display name & club."""
    folder = (tpl_dir or get_tshirt_templates_dir()).resolve()
    archive = (raw_archive_dir or get_raw_tshirt_archive_dir()).resolve()
    folder.mkdir(parents=True, exist_ok=True)

    clean_disp = display_name.strip() or template_id.strip() or "Camiseta Club"
    tid = slugify_template_id(template_id or clean_disp, fallback="Camiseta_Club")
    target_png = folder / f"{tid}.png"

    if raw_bytes:
        raw_hash = hashlib.sha256(raw_bytes).hexdigest()
        archive.mkdir(parents=True, exist_ok=True)
        bpath = archive / f"{tid}_{raw_hash[:10]}.png"
        if not bpath.is_file():
            bpath.write_bytes(raw_bytes)

    _atomic_write_png(clean_rgba.convert("RGBA"), target_png)
    collar = extract_collar_profile(clean_rgba)
    clean_bytes = target_png.read_bytes()
    clean_sha = hashlib.sha256(clean_bytes).hexdigest()
    clean_st = target_png.stat()
    clean_club = club_id.strip()

    with init_state_db(db_path or get_state_db_path()) as conn:
        if clean_club:
            conn.execute("UPDATE shirt_templates SET club_id='' WHERE club_id=? AND template_id!=?", (clean_club, tid))
        conn.execute(
            "INSERT OR REPLACE INTO shirt_templates VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (tid, target_png.name, clean_disp, clean_club, clean_sha, clean_st.st_mtime_ns, clean_st.st_size, collar.to_json()),
        )

    return ShirtTemplate(
        template_id=tid,
        filename=target_png.name,
        display_name=clean_disp,
        club_id=clean_club,
        file_path=target_png,
        collar=collar,
    )


def get_club_shirt_template(
    club_id: str,
    tpl_dir: Path | None = None,
    db_path: Path | None = None,
) -> ShirtTemplate | None:
    """Return the first ShirtTemplate bound to club_id, if any."""
    cid = club_id.strip()
    if not cid:
        return None
    items = sync_tshirt_templates_dir(tpl_dir=tpl_dir, db_path=db_path)
    return next((t for t in items if t.club_id == cid), None)
