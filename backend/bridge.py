"""Zero-port pywebview js_api bridge with capability-handle directory safety and lazy AI imports."""

from __future__ import annotations
import base64, io, os, tempfile, threading, time
from dataclasses import asdict
from pathlib import Path
from typing import Any
from backend import __version__
from backend.core.paths import get_default_vault_dir, get_models_dir, get_state_db_path, get_studio_root


class CapabilityError(PermissionError):
    """Raised when IPC attempts to access a directory not approved by native OS dialog or config."""


def _to_data_url(img: Any) -> str:
    buf = io.BytesIO()
    img.save(buf, format="PNG", compress_level=4)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def _decode_b64(s: str) -> bytes:
    return base64.b64decode(s.split(",", 1)[1] if "," in s else s)


class StudioBridge:
    def __init__(self, vault_dir: Path | None = None, export_dir: Path | None = None, db_path: Path | None = None) -> None:
        self._db_path = db_path or get_state_db_path()
        self._vault_dir = (vault_dir or get_default_vault_dir()).resolve()
        self._export_dir = (export_dir or (get_studio_root() / "Exports" / "000_DF11_Regens_Override")).resolve()
        self._approved_dirs: set[Path] = {self._vault_dir, self._export_dir}
        self._window: Any = None
        self._cutout_img: Any = None
        self._custom_bg_img: Any = None
        self._cancel_sync = threading.Event()
        self._watcher: Any = None

    def attach_window(self, window: Any) -> None:
        self._window = window

    def _require_approved(self, folder: Path) -> Path:
        r = folder.resolve()
        if r not in self._approved_dirs:
            raise CapabilityError(f"Directorio no autorizado: {r}")
        return r

    def get_bootstrap_state(self) -> dict[str, Any]:
        from backend.services.kits import load_seed_kits
        from backend.services.sync import check_fm_storage_health
        m = get_models_dir()
        ok = all((m / f).is_file() for f in ("face_detection_yunet_2023mar.onnx", "selfie_multiclass_256x256.onnx", "birefnet-general-lite.onnx"))
        return {"version": __version__, "clubs": load_seed_kits(), "vaultDir": str(self._vault_dir), "exportDir": str(self._export_dir), "storageHealth": asdict(check_fm_storage_health(self._export_dir)), "hasModels": ok}

    def warmup_vision_async(self) -> bool:
        def _w() -> None:
            try:
                from PIL import Image
                from backend.services.vision import detect_face_pose, segment_portrait_classes
                d = Image.new("RGBA", (128, 128), (128, 128, 128, 255))
                detect_face_pose(d)
                segment_portrait_classes(d)
            except Exception:
                pass
        threading.Thread(target=_w, daemon=True).start()
        return True

    def choose_directory(self, role: str) -> dict[str, Any] | None:
        import webview
        from backend.services.sync import check_fm_storage_health
        res = self._window.create_file_dialog(webview.FOLDER_DIALOG) if self._window else None
        if not res:
            return None
        c = Path(res[0]).resolve()
        self._approved_dirs.add(c)
        if role == "vault":
            self._vault_dir = c
        else:
            self._export_dir = c
        return {"path": str(c), "storageHealth": asdict(check_fm_storage_health(c))}

    def upload_studio_image(self, data_url: str, remove_bg: bool = True, harmonize: bool = True, extract_bg: bool = False) -> dict[str, Any]:
        from backend.core.compositor import render_df11_card
        from backend.core.image_guard import load_guarded_image
        from backend.services.kits import dress_or_frame_portrait
        from backend.services.vision import extract_clean_background, harmonize_df11_studio_grade, remove_background_birefnet
        g = load_guarded_image(_decode_b64(data_url))
        cut = g.image if (g.is_pre_cutout or not remove_bg) else remove_background_birefnet(g.image)
        self._cutout_img = harmonize_df11_studio_grade(cut) if harmonize else cut
        bg_url = ""
        if extract_bg:
            self._custom_bg_img = extract_clean_background(g.image, self._cutout_img.getchannel("A"))
            bg_url = _to_data_url(self._custom_bg_img)
        card = render_df11_card(portrait_rgba=dress_or_frame_portrait(self._cutout_img, kit_mode="original"), bg_mode="custom" if extract_bg else "white_df11", bg_custom_rgba=self._custom_bg_img)
        return {"isPreCutout": g.is_pre_cutout, "originalSize": list(g.original_size), "previewDataUrl": _to_data_url(card), "cleanBgDataUrl": bg_url}

    def upload_custom_background(self, data_url: str) -> dict[str, str]:
        from backend.core.image_guard import load_guarded_image
        self._custom_bg_img = load_guarded_image(_decode_b64(data_url)).image
        return {"bgDataUrl": _to_data_url(self._custom_bg_img)}

    def _compose(self, p: dict[str, Any]) -> Any:
        from backend.core.compositor import render_df11_card
        from backend.services.kits import dress_or_frame_portrait, resolve_club_kit, save_kit_override
        if self._cutout_img is None:
            return render_df11_card(None, bg_mode=p.get("bgMode", "white_df11"))
        kmode, cid = p.get("kitMode", "original"), str(p.get("clubId", "1736"))
        if p.get("customPrimary"):
            save_kit_override(cid, p["customPrimary"], p.get("customSecondary", "#F8FAFC"), pattern=p.get("customPattern", "solid"), db_path=self._db_path)
        kit = resolve_club_kit(cid, db_path=self._db_path) if kmode != "original" else None
        return render_df11_card(portrait_rgba=dress_or_frame_portrait(self._cutout_img, kit_mode=kmode, kit_spec=kit), portrait_offset=(float(p.get("offsetX", 0.0)), float(p.get("offsetY", 0.0))), portrait_scale=float(p.get("scale", 1.0)), bg_mode=p.get("bgMode", "white_df11"), bg_custom_rgba=self._custom_bg_img, bg_blur=float(p.get("bgBlur", 0.0)))

    def render_studio_preview(self, params: dict[str, Any]) -> dict[str, str]:
        return {"previewDataUrl": _to_data_url(self._compose(params))}

    def export_studio_card(self, params: dict[str, Any]) -> dict[str, str]:
        from backend.core.compositor import export_df11_bytes
        from backend.core.fm_config import safe_ntfs_replace, upsert_fm_config_xml, validate_fm_uid
        uid, fmt = validate_fm_uid(str(params.get("uid", ""))), ("jpg" if str(params.get("fmt", "png")).lower() in ("jpg", "jpeg") else "png")
        tdir = self._require_approved(Path(params["outDir"]) if params.get("outDir") else self._export_dir)
        tdir.mkdir(parents=True, exist_ok=True)
        fd, tname = tempfile.mkstemp(prefix=f".{uid}_", suffix=".tmp", dir=str(tdir))
        tp, dst = Path(tname), tdir / f"{uid}.{fmt}"
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(export_df11_bytes(self._compose(params), fmt=fmt))  # type: ignore[arg-type]
            safe_ntfs_replace(tp, dst)
        finally:
            tp.unlink(missing_ok=True)
        if params.get("updateConfigXml", True) and fmt == "png":
            upsert_fm_config_xml(tdir / "config.xml", [uid])
        return {"savedPath": str(dst)}

    def scan_vault_summary(self) -> dict[str, Any]:
        from backend.services.kits import init_state_db
        from backend.services.sync import _ensure_sync_tables, scan_ng_regens_vault
        _ensure_sync_tables(self._db_path)
        e = scan_ng_regens_vault(self._vault_dir)
        with init_state_db(self._db_path) as c:
            clubs = dict(c.execute("SELECT uid, club_id FROM squad_map").fetchall())
        return {"totalFound": len(e), "sample": [{"uid": u, "clubId": clubs.get(u, "")} for u in list(e.keys())[:24]]}

    def tag_my_club(self, uids: list[str], club_id: str) -> dict[str, int]:
        from backend.services.sync import assign_uids_to_club
        return {"updated": assign_uids_to_club(uids, club_id, db_path=self._db_path)}

    def import_squad_text(self, raw_text: str) -> dict[str, int]:
        from backend.services.sync import import_squad_club_mappings
        return {"mapped": import_squad_club_mappings(raw_text, db_path=self._db_path)}

    def start_regens_sync(self, o: dict[str, Any]) -> dict[str, Any]:
        from backend.services.sync import sync_ng_regens_batch
        self._cancel_sync.clear()
        return asdict(sync_ng_regens_batch(self._vault_dir, self._export_dir, db_path=self._db_path, apply_club_kits=bool(o.get("applyClubKits", True)), harmonize=bool(o.get("harmonize", True)), bg_mode=o.get("bgMode", "white_df11"), allow_shrink=bool(o.get("allowShrink", False)), cancel_event=self._cancel_sync))

    def cancel_regens_sync(self) -> bool:
        self._cancel_sync.set()
        return True

    def toggle_live_watch(self, enabled: bool) -> dict[str, bool]:
        from backend.services.sync import QuiescentVaultWatcher, sync_ng_regens_batch
        if not enabled:
            if self._watcher:
                self._watcher.stop()
            return {"watching": False}
        self._watcher = QuiescentVaultWatcher(self._vault_dir, on_quiescent=lambda: sync_ng_regens_batch(self._vault_dir, self._export_dir, db_path=self._db_path))
        self._watcher.start()
        return {"watching": True}

    def load_regen_into_studio(self, uid: str) -> dict[str, Any]:
        from backend.services.sync import scan_ng_regens_vault
        e = scan_ng_regens_vault(self._vault_dir)
        if uid not in e:
            raise ValueError(f"Regen {uid} no encontrado.")
        return {"uid": uid, **self.upload_studio_image("data:image/png;base64," + base64.b64encode(e[uid].read_bytes()).decode("ascii"), remove_bg=False, harmonize=True, extract_bg=False)}

    def probe_architecture_health(self) -> dict[str, Any]:
        import onnxruntime as ort
        from backend.services.kits import init_state_db
        t0 = time.perf_counter()
        with init_state_db(self._db_path) as c:
            c.execute("SELECT 1").fetchone()
        p = ort.get_available_providers()
        return {"dmlActive": "DmlExecutionProvider" in p, "providers": p, "sqliteLatencyMs": round((time.perf_counter() - t0) * 1000.0, 2)}
