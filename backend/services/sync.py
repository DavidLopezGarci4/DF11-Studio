"""Non-destructive NG_Regens vault scanner, OneDrive/FM27 sentinel, squad mapper, and Live Disk Sync."""

from __future__ import annotations

import os
import re
import shutil
import tempfile
import threading
import time
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

from defusedxml import ElementTree as SafeET

from backend.core.compositor import BgMode, export_df11_bytes, render_df11_card
from backend.core.fm_config import safe_ntfs_replace, upsert_fm_config_xml, validate_fm_uid
from backend.core.image_guard import load_guarded_image
from backend.core.paths import get_default_vault_dir
from backend.services.kits import dress_or_frame_portrait, init_state_db, load_seed_kits, resolve_club_kit
from backend.services.vision import harmonize_df11_studio_grade, remove_background_birefnet

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


def assign_uids_to_club(uids: Iterable[str], club_id: str, db_path: Path | None = None) -> int:
    _ensure_sync_tables(db_path)
    rows = [(validate_fm_uid(u), str(club_id).strip()) for u in uids]
    with init_state_db(db_path) as conn:
        conn.executemany("INSERT OR REPLACE INTO squad_map VALUES (?, ?)", rows)
    return len(rows)


def import_squad_club_mappings(raw_text: str, db_path: Path | None = None) -> int:
    """Lightweight CSV / HTML / Clipboard importer mapping regen UIDs to Club IDs."""
    _ensure_sync_tables(db_path)
    by_name = {v["name"].lower(): cid for cid, v in load_seed_kits().items()}
    mapped: list[tuple[str, str]] = []
    for raw_line in raw_text.splitlines():
        tokens = [t.strip() for t in re.split(r"[,;\t|]+", _HTML_TAG_RE.sub(",", raw_line).strip()) if t.strip()]
        uid = next((t for t in tokens if _UID_TOKEN_RE.fullmatch(t)), None)
        if not uid:
            continue
        for tok in tokens:
            if tok != uid and (tok.isdigit() and len(tok) <= 9 or tok.lower() in by_name):
                mapped.append((validate_fm_uid(uid), tok if tok.isdigit() else by_name[tok.lower()]))
                break
    if mapped:
        with init_state_db(db_path) as conn:
            conn.executemany("INSERT OR REPLACE INTO squad_map VALUES (?, ?)", mapped)
    return len(mapped)


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
) -> tuple[str, int, int, str]:
    st = src_png.stat()
    guarded = load_guarded_image(src_png)
    use_kit = bool(apply_club_kits and club_id)
    tpl_sig = ""
    if use_kit and club_tpl is not None and club_tpl[0].is_file():
        from backend.services.head_neck import (
            HeadFitParams,
            compose_modular_df11,
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
        card = compose_modular_df11(head_asset=head_asset, shirt_rgba=shirt_im, collar=collar, fit=fit, bg_mode=bg_mode)
    else:
        cutout = guarded.image if guarded.is_pre_cutout else remove_background_birefnet(guarded.image)
        if harmonize:
            cutout = harmonize_df11_studio_grade(cutout)
        kit = resolve_club_kit(club_id, db_path=db_path) if use_kit and club_id else None
        card = render_df11_card(portrait_rgba=dress_or_frame_portrait(cutout, kit_mode="club" if use_kit else "original", kit_spec=kit), bg_mode=bg_mode)
    png_bytes = export_df11_bytes(card, fmt="png", compress_level=4)

    out_dir.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{uid}_", suffix=".tmp", dir=str(out_dir))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(png_bytes)
        safe_ntfs_replace(tmp_path, out_dir / f"{uid}.png")
    finally:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
    return (uid, st.st_mtime_ns, st.st_size, f"{club_id or ''}:{int(apply_club_kits)}:{int(harmonize)}:{bg_mode}{tpl_sig}")


def sync_ng_regens_batch(
    vault_dir: Path, out_dir: Path, db_path: Path | None = None, apply_club_kits: bool = True, harmonize: bool = True,
    bg_mode: BgMode = "white_df11", allow_shrink: bool = False, cancel_event: threading.Event | None = None,
    progress_cb: Callable[[int, int], None] | None = None, templates_dir: Path | None = None,
) -> SyncResult:
    from backend.core.paths import get_tshirt_templates_dir
    from backend.services.templates import sync_tshirt_templates_dir

    if cancel_event is not None and cancel_event.is_set():
        return SyncResult(0, 0, 0, cancelled=True)
    _ensure_sync_tables(db_path)
    entries = scan_ng_regens_vault(vault_dir)
    tpl_root = (templates_dir or get_tshirt_templates_dir()).resolve()
    if apply_club_kits and tpl_root.is_dir() and any(tpl_root.iterdir()):
        sync_tshirt_templates_dir(tpl_dir=tpl_root, db_path=db_path)
    with init_state_db(db_path) as conn:
        prev_manifest = {r[0]: (r[1], r[2], r[3]) for r in conn.execute("SELECT uid, mtime_ns, size, sig FROM regen_manifest")}
        squad_clubs = dict(conn.execute("SELECT uid, club_id FROM squad_map").fetchall())
        club_tpls: dict[str, tuple[Path, str, str]] = {}
        for cid_raw, fname_raw, collar_raw, sha_raw in conn.execute(
            "SELECT club_id, filename, collar_json, sha256 FROM shirt_templates WHERE club_id != '' ORDER BY LOWER(template_id) ASC"
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

    todo: list[tuple[str, Path, str | None, tuple[Path, str, str] | None]] = []
    skipped = 0
    for uid, src_png in entries.items():
        st, cid = src_png.stat(), squad_clubs.get(uid)
        ctpl = club_tpls.get(cid) if (apply_club_kits and cid) else None
        if ctpl is not None and not ctpl[0].is_file():
            ctpl = None
        tpl_sig = f":tpl={ctpl[2][:10]}" if ctpl is not None else ""
        sig = f"{cid or ''}:{int(apply_club_kits)}:{int(harmonize)}:{bg_mode}{tpl_sig}"
        if prev_manifest.get(uid) == (st.st_mtime_ns, st.st_size, sig) and (out_dir / f"{uid}.png").is_file():
            skipped += 1
        else:
            todo.append((uid, src_png, cid, ctpl))

    completed_rows: list[tuple[str, int, int, str]] = []
    failed = 0
    cancelled = False
    if todo:
        with ThreadPoolExecutor(max_workers=8) as pool:
            futs = {
                pool.submit(_process_single_regen, u, p, out_dir, c, apply_club_kits, harmonize, bg_mode, db_path, ct): u
                for u, p, c, ct in todo
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
    exported_uids = [u for u in entries if (out_dir / f"{u}.png").is_file()]
    if exported_uids:
        upsert_fm_config_xml(out_dir / "config.xml", exported_uids)
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
