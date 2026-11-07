"""Non-destructive NG_Regens vault scanner, OneDrive/FM27 sentinel, squad mapper, and Live Disk Sync."""

from __future__ import annotations

import os
import re
import shutil
import tempfile
import threading
import time
import unicodedata
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

from defusedxml import ElementTree as SafeET

from PIL import Image

from backend.core.compositor import (
    BgMode,
    CardVariant,
    export_df11_bytes,
    has_df11_outer_ring,
    is_df11_pure_size,
    render_df11_card,
    render_df11_pure_card,
    unfeather_pure_perimeter_rgba,
    unmix_df11_classic_bevel_rgba,
)
from backend.core.dsp import (
    clean_pure_contour_zero_ai,
    harmonize_oklab_pure_optics,
    is_genuinely_precut_window,
    resample_linear_subpixel_rgba,
)
from backend.core.fm_config import safe_ntfs_replace, upsert_fm_config_xml, validate_fm_uid
from backend.core.image_guard import load_guarded_image
from backend.core.paths import get_default_vault_dir
from backend.services.kits import (
    dress_or_frame_portrait,
    get_active_save_id,
    init_state_db,
    load_merged_clubs,
    normalize_save_id,
    resolve_club_kit,
)

_PORTRAIT_TO_RE = re.compile(r"graphics/pictures/person/((?:r-)?[0-9]{1,12})/portrait", re.IGNORECASE)
_UID_TOKEN_RE = re.compile(r"\b((?:r-)?[0-9]{4,12})\b")
_HTML_TAG_RE = re.compile(r"<[^>]+>")


@dataclass(frozen=True, slots=True)
class StorageHealthReport:
    target_path: str
    in_onedrive: bool
    free_gb: float
    warning: bool
    steam_launch_arg: str
    gamepass_guide: str


@dataclass(frozen=True, slots=True)
class SyncResult:
    total_found: int
    processed: int
    skipped: int
    failed: int = 0
    cancelled: bool = False
    aborted_by_shrink_guard: bool = False


def _ensure_sync_tables(db_path: Path | None) -> None:
    with init_state_db(db_path):
        pass


def detect_ng_regens_app_config() -> Path:
    """Read-only probe for NG_Regens (com.cprrylow) directory without mutating external files."""
    for env_key in ("APPDATA", "LOCALAPPDATA"):
        base = os.environ.get(env_key)
        if base and (Path(base) / "com.cprrylow").is_dir():
            return Path(base) / "com.cprrylow"
    return get_default_vault_dir()


def scan_ng_regens_vault(vault_dir: Path) -> dict[str, Path]:
    """Stream vault config.xml safely (blocking XXE, CWE-22 path traversal, and UNC/SMB leaks)."""
    cfg = vault_dir / "config.xml"
    if not cfg.is_file():
        return {}
    vault_root = vault_dir.resolve()
    entries: dict[str, Path] = {}
    try:
        for _ev, elem in SafeET.iterparse(cfg, events=("end",)):
            if elem.tag == "record":
                frm, to = elem.attrib.get("from", "").strip(), elem.attrib.get("to", "").strip()
                m = _PORTRAIT_TO_RE.search(to)
                if m and frm and not frm.startswith(("\\\\", "//")) and ":" not in frm:
                    rel = Path(frm)
                    if not rel.is_absolute() and ".." not in rel.parts:
                        cand = (vault_dir / f"{frm}.png").resolve()
                        try:
                            cand.relative_to(vault_root)
                            if cand.is_file():
                                entries[validate_fm_uid(m.group(1))] = cand
                        except Exception:
                            pass
                elem.clear()
    except Exception:
        return {}
    return entries


def check_fm_storage_health(target_path: Path) -> StorageHealthReport:
    """Detect OneDrive sync hazards and low system-drive space for FM26/FM27 facepacks."""
    parts_low = [p.lower() for p in target_path.parts]
    od_env = os.environ.get("OneDrive", "").lower()
    in_od = ("onedrive" in parts_low) or bool(od_env and str(target_path).lower().startswith(od_env))
    probe = target_path
    while not probe.exists() and probe.parent != probe:
        probe = probe.parent
    try:
        free_gb = round(shutil.disk_usage(probe).free / (1024.0**3), 1)
    except OSError:
        free_gb = 100.0
    return StorageHealthReport(
        target_path=str(target_path),
        in_onedrive=in_od,
        free_gb=free_gb,
        warning=in_od or (free_gb < 50.0),
        steam_launch_arg='--user_data_location="D:\\FM27 Data"',
        gamepass_guide=(
            "En Xbox / Microsoft Store Game Pass --user_data_location no está soportado por SEGA: "
            "abre Ajustes de OneDrive -> Sincronización y copia de seguridad -> Elegir carpetas y desmarca 'Sports Interactive'."
        ),
    )


def _norm_club_key(raw: str) -> str:
    nfkd = unicodedata.normalize("NFKD", str(raw or ""))
    stripped = "".join(ch for ch in nfkd if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", stripped.strip().lower())


def assign_uids_to_club(
    uids: Iterable[str],
    club_id: str,
    db_path: Path | None = None,
    save_id: str | None = None,
) -> int:
    _ensure_sync_tables(db_path)
    active_sid = get_active_save_id(db_path)
    eff_sid = normalize_save_id(save_id) if save_id else active_sid
    cid = str(club_id).strip()
    clean_uids = [validate_fm_uid(u) for u in uids]
    if not clean_uids:
        return 0
    with init_state_db(db_path) as conn:
        for u in clean_uids:
            conn.execute(
                "INSERT INTO save_squad_roster (save_id, uid, club_id, player_name, category) VALUES (?, ?, ?, '', 'player') "
                "ON CONFLICT(save_id, uid) DO UPDATE SET club_id=excluded.club_id",
                (eff_sid, u, cid),
            )
        if eff_sid == active_sid:
            conn.executemany("INSERT OR REPLACE INTO squad_map VALUES (?, ?)", [(u, cid) for u in clean_uids])
    return len(clean_uids)


def import_squad_club_mappings(
    raw_text: str,
    db_path: Path | None = None,
    save_id: str | None = None,
) -> int:
    """Hardened CSV / HTML / FM Ctrl+P table importer mapping UIDs to Club IDs without Age/Shirt false positives."""
    _ensure_sync_tables(db_path)
    active_sid = get_active_save_id(db_path)
    eff_sid = normalize_save_id(save_id) if save_id else active_sid

    merged_clubs = load_merged_clubs(db_path)
    known_ids: set[str] = set(merged_clubs.keys())
    by_name: dict[str, str] = {}
    for cid, spec in merged_clubs.items():
        nk = _norm_club_key(spec.get("name", ""))
        if nk:
            by_name[nk] = cid
    with init_state_db(db_path) as conn:
        for cid_raw, cname_raw in conn.execute(
            "SELECT DISTINCT club_id, club_name FROM shirt_templates WHERE club_id != ''"
        ).fetchall():
            cid_s = str(cid_raw).strip()
            nk = _norm_club_key(str(cname_raw))
            if cid_s:
                known_ids.add(cid_s)
                if nk:
                    by_name.setdefault(nk, cid_s)

    club_col_idx: int | None = None
    name_col_idx: int | None = None
    roster_rows: list[tuple[str, str, str]] = []

    for raw_line in raw_text.splitlines():
        tokens = [t.strip() for t in re.split(r"[,;\t|]+", _HTML_TAG_RE.sub(",", raw_line).strip()) if t.strip()]
        if not tokens:
            continue
        uid_tok = next((t for t in tokens if _UID_TOKEN_RE.fullmatch(t)), None)
        if not uid_tok:
            norm_hdrs = [_norm_club_key(t) for t in tokens]
            if any(h in ("uid", "id", "id unico", "unique id") for h in norm_hdrs):
                club_col_idx = next(
                    (i for i, h in enumerate(norm_hdrs) if h in ("club", "equipo", "team", "club actual", "division")),
                    None,
                )
                name_col_idx = next(
                    (i for i, h in enumerate(norm_hdrs) if h in ("nombre", "name", "jugador", "player", "nombre completo")),
                    None,
                )
            continue

        clean_uid = validate_fm_uid(uid_tok)
        matched_cid: str | None = None

        if club_col_idx is not None and 0 <= club_col_idx < len(tokens) and tokens[club_col_idx] != uid_tok:
            ctok = tokens[club_col_idx]
            cnk = _norm_club_key(ctok)
            raw_num = ctok[1:] if ctok.startswith("#") else ctok
            if cnk in by_name:
                matched_cid = by_name[cnk]
            elif raw_num.isdigit() and 1 <= len(raw_num) <= 12 and (ctok.startswith("#") or len(raw_num) >= 3 or raw_num in known_ids):
                matched_cid = raw_num

        if matched_cid is None:
            for tok in tokens:
                if tok == uid_tok:
                    continue
                nk = _norm_club_key(tok)
                if nk in by_name:
                    matched_cid = by_name[nk]
                    break
                if tok.startswith("#") and tok[1:].isdigit() and 1 <= len(tok[1:]) <= 12:
                    matched_cid = tok[1:]
                    break

        if matched_cid is None:
            if len(tokens) == 2:
                other = tokens[1] if tokens[0] == uid_tok else tokens[0]
                if other.isdigit() and 1 <= len(other) <= 12:
                    matched_cid = other
            else:
                for tok in tokens:
                    if tok != uid_tok and tok.isdigit() and tok in known_ids and int(tok) >= 100:
                        matched_cid = tok
                        break

        if matched_cid is None:
            continue

        player_name = ""
        if name_col_idx is not None and 0 <= name_col_idx < len(tokens):
            cand_name = tokens[name_col_idx]
            if cand_name != uid_tok and _norm_club_key(cand_name) not in by_name and not cand_name.isdigit():
                player_name = cand_name[:80]
        elif len(tokens) >= 3:
            for tok in tokens:
                if (
                    tok != uid_tok
                    and tok != matched_cid
                    and _norm_club_key(tok) not in by_name
                    and not tok.lstrip("#").isdigit()
                    and any(ch.isalpha() for ch in tok)
                ):
                    player_name = tok[:80]
                    break

        roster_rows.append((clean_uid, matched_cid, player_name))

    if roster_rows:
        with init_state_db(db_path) as conn:
            for u, cid, pname in roster_rows:
                conn.execute(
                    "INSERT INTO save_squad_roster (save_id, uid, club_id, player_name, category) VALUES (?, ?, ?, ?, 'player') "
                    "ON CONFLICT(save_id, uid) DO UPDATE SET club_id=excluded.club_id, "
                    "player_name=CASE WHEN excluded.player_name != '' THEN excluded.player_name ELSE save_squad_roster.player_name END",
                    (eff_sid, u, cid, pname),
                )
            if eff_sid == active_sid:
                conn.executemany(
                    "INSERT OR REPLACE INTO squad_map VALUES (?, ?)",
                    [(u, cid) for u, cid, _ in roster_rows],
                )
    return len(roster_rows)


def _parse_manifest_sigs(raw_sig: str) -> tuple[str, str]:
    s = str(raw_sig or "")
    if s.startswith("c=") and "||p=" in s:
        c_part, p_part = s[2:].split("||p=", 1)
        return c_part, p_part
    return s, ""


def _atomic_write_png(dst_dir: Path, uid: str, png_bytes: bytes) -> None:
    dst_dir.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{uid}_", suffix=".tmp", dir=str(dst_dir))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(png_bytes)
        safe_ntfs_replace(tmp_path, dst_dir / f"{uid}.png")
    finally:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)


def _process_single_regen(
    uid: str,
    src_png: Path,
    out_dir: Path,
    club_id: str | None,
    apply_club_kits: bool,
    harmonize: bool,
    bg_mode: BgMode,
    db_path: Path | None,
    club_tpl: tuple[Path, str, str] | None = None,
    pure_out_dir: Path | None = None,
    need_classic: bool = True,
    need_pure: bool = False,
    prev_c_sig: str = "",
    prev_p_sig: str = "",
) -> tuple[str, int, int, str]:
    st = src_png.stat()
    guarded = load_guarded_image(src_png)
    use_kit = bool(apply_club_kits and club_id)
    tpl_sig = ""
    if use_kit and club_tpl is not None and club_tpl[0].is_file():
        from backend.services.head_neck import (
            HeadFitParams,
            compose_modular_subject_rgba,
            extract_clean_head_and_neck,
            fit_head_to_shirt_template,
            suggest_safe_crop_viewport,
        )
        from backend.services.templates import CollarProfile

        shirt_im = load_guarded_image(club_tpl[0]).image
        collar = CollarProfile.from_json(club_tpl[1])
        tpl_sig = f":tpl={club_tpl[2][:10]}"
        vp = suggest_safe_crop_viewport(guarded.image)
        head_asset = extract_clean_head_and_neck(guarded.image, is_pre_cutout=guarded.is_pre_cutout, crop_viewport=vp)
        auto_fit = fit_head_to_shirt_template(head_asset, collar)
        fit = HeadFitParams(scale=auto_fit.scale, offset_x=auto_fit.offset_x, offset_y=auto_fit.offset_y, neck_fill=1.0, harmonize=harmonize)
        subject_rgba = compose_modular_subject_rgba(head_asset=head_asset, shirt_rgba=shirt_im, collar=collar, fit=fit)
    else:
        raw_im = guarded.image
        if has_df11_outer_ring(raw_im):
            prep_im, is_precut = unmix_df11_classic_bevel_rgba(raw_im)
        elif is_df11_pure_size(raw_im.size):
            p_alpha = raw_im.convert("RGBA").getchannel("A")
            import numpy as np

            p_arr = np.asarray(p_alpha, dtype=np.uint8)
            if is_genuinely_precut_window(p_arr):
                unfeathered = unfeather_pure_perimeter_rgba(raw_im)
                win = Image.new("RGBA", (224, 278), (0, 0, 0, 0))
                win.paste(unfeathered, (2, 1))
                prep_im, is_precut = win, True
            else:
                prep_im, is_precut = raw_im, False
        else:
            import numpy as np

            a_arr = np.asarray(raw_im.convert("RGBA"), dtype=np.uint8)[:, :, 3]
            prep_im = raw_im
            is_precut = bool(guarded.is_pre_cutout and is_genuinely_precut_window(a_arr))

        framed_arr = resample_linear_subpixel_rgba(
            prep_im,
            zoom=1.0,
            pan_x=0.0,
            pan_y=0.0,
            fit_mode="contain" if is_precut else "cover",
            clamp_to_inner=not is_precut,
        )
        framed_im = Image.fromarray(framed_arr, mode="RGBA")
        if harmonize:
            framed_im = harmonize_oklab_pure_optics(framed_im)
        cutout_im = framed_im if is_precut else clean_pure_contour_zero_ai(framed_im, is_known_precut=False)
        if use_kit and club_id:
            kit = resolve_club_kit(club_id, db_path=db_path)
            subject_rgba = dress_or_frame_portrait(cutout_im, kit_mode="club", kit_spec=kit)
            subject_rgba = clean_pure_contour_zero_ai(subject_rgba)
        else:
            subject_rgba = cutout_im

    c_sig_out = prev_c_sig
    p_sig_out = prev_p_sig
    if need_classic:
        classic_card = render_df11_card(portrait_rgba=subject_rgba, bg_mode=bg_mode)
        _atomic_write_png(out_dir, uid, export_df11_bytes(classic_card, fmt="png", compress_level=4))
        c_sig_out = f"v2_p0ai:{club_id or ''}:{int(apply_club_kits)}:{int(harmonize)}:{bg_mode}{tpl_sig}"
    if need_pure and pure_out_dir is not None:
        pure_card = render_df11_pure_card(subject_rgba)
        _atomic_write_png(pure_out_dir, uid, export_df11_bytes(pure_card, fmt="png", compress_level=4))
        p_sig_out = f"v2_p0ai:{club_id or ''}:{int(apply_club_kits)}:{int(harmonize)}:pure{tpl_sig}"

    packed_sig = f"c={c_sig_out}||p={p_sig_out}" if p_sig_out else c_sig_out
    return (uid, st.st_mtime_ns, st.st_size, packed_sig)


def sync_ng_regens_batch(
    vault_dir: Path, out_dir: Path, db_path: Path | None = None, apply_club_kits: bool = True, harmonize: bool = True,
    bg_mode: BgMode = "white_df11", allow_shrink: bool = False, cancel_event: threading.Event | None = None,
    progress_cb: Callable[[int, int], None] | None = None, templates_dir: Path | None = None,
    pure_out_dir: Path | None = None, variant: CardVariant = "classic",
) -> SyncResult:
    from backend.core.paths import get_tshirt_templates_dir

    eff_variant: CardVariant = variant if variant in ("classic", "pure", "dual") else "classic"
    want_classic = eff_variant in ("classic", "dual")
    want_pure = eff_variant in ("pure", "dual")
    if want_pure and pure_out_dir is None:
        raise ValueError("Se requiere una carpeta de salida DF11 Pure para sincronizar en modo Pure o Dual.")
    if want_classic and want_pure and pure_out_dir is not None:
        ra, rb = out_dir.resolve(), pure_out_dir.resolve()
        if ra == rb or ra.is_relative_to(rb) or rb.is_relative_to(ra):
            raise ValueError("Las carpetas de salida Classic y DF11 Pure no pueden ser la misma ni estar anidadas.")

    if cancel_event is not None and cancel_event.is_set():
        return SyncResult(0, 0, 0, cancelled=True)
    _ensure_sync_tables(db_path)
    entries = scan_ng_regens_vault(vault_dir)
    tpl_root = (templates_dir or get_tshirt_templates_dir()).resolve()
    if apply_club_kits and tpl_root.is_dir() and any(tpl_root.iterdir()):
        from backend.services.templates import sync_tshirt_templates_dir

        sync_tshirt_templates_dir(tpl_dir=tpl_root, db_path=db_path)
    with init_state_db(db_path) as conn:
        prev_manifest = {r[0]: (r[1], r[2], r[3]) for r in conn.execute("SELECT uid, mtime_ns, size, sig FROM regen_manifest")}
        squad_clubs = dict(conn.execute("SELECT uid, club_id FROM squad_map").fetchall())
        club_tpls: dict[str, tuple[Path, str, str]] = {}
        for cid_raw, fname_raw, collar_raw, sha_raw in conn.execute(
            "SELECT club_id, filename, collar_json, sha256 FROM shirt_templates "
            "WHERE club_id != '' AND COALESCE(category, 'player') = 'player' "
            "ORDER BY COALESCE(is_active_for_club, 1) DESC, LOWER(template_id) ASC"
        ).fetchall():
            cid_s, fname_s = str(cid_raw), str(fname_raw)
            if cid_s in club_tpls or not fname_s or Path(fname_s).name != fname_s or ".." in fname_s:
                continue
            cand = (tpl_root / fname_s).resolve()
            try:
                cand.relative_to(tpl_root)
                if cand.is_file():
                    club_tpls[cid_s] = (cand, str(collar_raw), str(sha_raw))
            except ValueError:
                continue
    if len(prev_manifest) >= 2 and len(entries) < len(prev_manifest) * 0.5 and not allow_shrink:
        return SyncResult(len(entries), 0, 0, aborted_by_shrink_guard=True)

    todo: list[tuple[str, Path, str | None, tuple[Path, str, str] | None, bool, bool, str, str]] = []
    skipped = 0
    for uid, src_png in entries.items():
        st, cid = src_png.stat(), squad_clubs.get(uid)
        ctpl = club_tpls.get(cid) if (apply_club_kits and cid) else None
        if ctpl is not None and not ctpl[0].is_file():
            ctpl = None
        tpl_sig = f":tpl={ctpl[2][:10]}" if ctpl is not None else ""
        target_c_sig = f"v2_p0ai:{cid or ''}:{int(apply_club_kits)}:{int(harmonize)}:{bg_mode}{tpl_sig}"
        target_p_sig = f"v2_p0ai:{cid or ''}:{int(apply_club_kits)}:{int(harmonize)}:pure{tpl_sig}"
        prev_row = prev_manifest.get(uid)
        if prev_row is not None and prev_row[0] == st.st_mtime_ns and prev_row[1] == st.st_size:
            prev_c, prev_p = _parse_manifest_sigs(prev_row[2])
        else:
            prev_c, prev_p = "", ""
        classic_ok = (prev_c == target_c_sig) and (out_dir / f"{uid}.png").is_file()
        pure_ok = (pure_out_dir is not None) and (prev_p == target_p_sig) and (pure_out_dir / f"{uid}.png").is_file()
        need_c = want_classic and not classic_ok
        need_p = want_pure and not pure_ok
        if not need_c and not need_p:
            skipped += 1
        else:
            todo.append((uid, src_png, cid, ctpl, need_c, need_p, prev_c if classic_ok else "", prev_p if pure_ok else ""))

    completed_rows: list[tuple[str, int, int, str]] = []
    failed = 0
    cancelled = False
    if todo:
        with ThreadPoolExecutor(max_workers=8) as pool:
            futs = {
                pool.submit(
                    _process_single_regen,
                    u,
                    p,
                    out_dir,
                    c,
                    apply_club_kits,
                    harmonize,
                    bg_mode,
                    db_path,
                    ct,
                    pure_out_dir,
                    nc,
                    np_flag,
                    pc_sig,
                    pp_sig,
                ): u
                for u, p, c, ct, nc, np_flag, pc_sig, pp_sig in todo
            }
            for idx, fut in enumerate(as_completed(futs), 1):
                if cancel_event is not None and cancel_event.is_set():
                    cancelled = True
                    for pending in futs:
                        pending.cancel()
                    break
                try:
                    completed_rows.append(fut.result())
                except Exception:
                    failed += 1
                if progress_cb:
                    progress_cb(idx, len(todo))
    if completed_rows:
        with init_state_db(db_path) as conn:
            conn.executemany("INSERT OR REPLACE INTO regen_manifest VALUES (?, ?, ?, ?)", completed_rows)
    if want_classic:
        exported_uids = [u for u in entries if (out_dir / f"{u}.png").is_file()]
        if exported_uids:
            upsert_fm_config_xml(out_dir / "config.xml", exported_uids)
    if want_pure and pure_out_dir is not None:
        exported_pure_uids = [u for u in entries if (pure_out_dir / f"{u}.png").is_file()]
        if exported_pure_uids:
            upsert_fm_config_xml(pure_out_dir / "config.xml", exported_pure_uids)
    return SyncResult(len(entries), len(completed_rows), skipped, failed=failed, cancelled=cancelled)


class QuiescentVaultWatcher:
    """650ms Quiescence Debounce monitor preventing race reads while NG_Regens writes config.xml."""

    def __init__(self, vault_dir: Path | Callable[[], Path], on_quiescent: Callable[[], None], quiescence_sec: float = 0.65) -> None:
        self.vault_dir, self.on_quiescent, self.quiescence_sec = vault_dir, on_quiescent, quiescence_sec
        self._pending_sig: tuple[Path, int, int] | None = None
        self._fired_sig: tuple[Path, int, int] | None = None
        self._last_change_ts = 0.0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _current_vault(self) -> Path:
        return self.vault_dir() if callable(self.vault_dir) else self.vault_dir

    def poll_once(self) -> bool:
        try:
            vdir = self._current_vault()
            cfg = vdir / "config.xml"
            if not cfg.is_file() or (st := cfg.stat()).st_size < 16:
                return False
            sig, now = (vdir, st.st_mtime_ns, st.st_size), time.monotonic()
            if sig == self._fired_sig:
                return False
            if sig != self._pending_sig:
                self._pending_sig, self._last_change_ts = sig, now
                return False
            if (now - self._last_change_ts) >= self.quiescence_sec:
                with cfg.open("rb") as fh:
                    fh.seek(max(0, st.st_size - 64))
                    if b"</record>" not in fh.read():
                        return False
                self._fired_sig = sig
                self.on_quiescent()
                return True
        except OSError:
            return False
        return False

    def start(self, interval_sec: float = 0.25) -> None:
        if not (self._thread and self._thread.is_alive()):
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, args=(interval_sec,), daemon=True)
            self._thread.start()

    def _loop(self, interval_sec: float) -> None:
        while not self._stop.wait(interval_sec):
            try:
                self.poll_once()
            except Exception:
                continue

    def stop(self) -> None:
        self._stop.set()
