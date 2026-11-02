"""Zero-port pywebview js_api bridge with capability-handle directory safety and lazy AI imports."""

from __future__ import annotations

import base64
import io
import os
import tempfile
import threading
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from backend import __version__
from backend.core.paths import get_default_vault_dir, get_models_dir, get_state_db_path, get_studio_root


class CapabilityError(PermissionError):
    """Raised when IPC attempts to write to a directory not approved by native OS dialog or config."""


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
        self._approved_dirs: set[Path] = {self._export_dir}
        self._window: Any = None
        self._raw_img: Any = None
        self._raw_is_precut: bool = False
        self._fg_cut_cache: tuple[int, Any] | None = None
        self._cutout_key: tuple[int, bool, bool] | None = None
        self._cutout_img: Any = None
        self._dressed_key: tuple[Any, ...] | None = None
        self._dressed_img: Any = None
        self._custom_bg_img: Any = None
        self._cancel_sync = threading.Event()
        self._watcher: Any = None
        self._live_opts: dict[str, Any] = {"applyClubKits": True, "harmonize": True}

    def _attach_window(self, window: Any) -> None:
        self._window = window

    def _require_approved(self, folder: Path) -> Path:
        r = folder.resolve()
        if r == self._vault_dir or r not in self._approved_dirs:
            raise CapabilityError(f"Directorio de escritura no autorizado: {r}")
        return r

    def get_bootstrap_state(self) -> dict[str, Any]:
        from backend.services.kits import init_state_db, load_seed_kits
        from backend.services.sync import check_fm_storage_health

        m = get_models_dir()
        ok = all((m / f).is_file() for f in ("face_detection_yunet_2023mar.onnx", "selfie_multiclass_256x256.onnx", "birefnet-general-lite.onnx"))
        theme = "dark"
        if self._db_path.is_file():
            with init_state_db(self._db_path) as c:
                row = c.execute("SELECT pref_val FROM app_prefs WHERE pref_key='theme'").fetchone()
                if row and row[0] in ("dark", "light"):
                    theme = row[0]
        return {
            "version": __version__,
            "clubs": load_seed_kits(),
            "vaultDir": str(self._vault_dir),
            "exportDir": str(self._export_dir),
            "storageHealth": asdict(check_fm_storage_health(self._export_dir)),
            "hasModels": ok,
            "liveWatching": self._watcher is not None,
            "theme": theme,
        }

    def set_ui_theme(self, theme: str) -> dict[str, str]:
        from backend.services.kits import init_state_db

        val = "light" if str(theme).lower() == "light" else "dark"
        with init_state_db(self._db_path) as c:
            c.execute("INSERT OR REPLACE INTO app_prefs VALUES ('theme', ?)", (val,))
        return {"theme": val}

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
        if role == "vault":
            self._vault_dir = c
        else:
            if c == self._vault_dir:
                raise CapabilityError("La carpeta de salida no puede coincidir con la bóveda NG_Regens de solo lectura.")
            self._approved_dirs.add(c)
            self._export_dir = c
        return {"path": str(c), "storageHealth": asdict(check_fm_storage_health(c))}

    def _get_fg_cutout(self) -> Any:
        from backend.services.vision import remove_background_birefnet

        if self._raw_img is None:
            return None
        if self._raw_is_precut:
            return self._raw_img
        raw_id = id(self._raw_img)
        if self._fg_cut_cache is None or self._fg_cut_cache[0] != raw_id:
            self._fg_cut_cache = (raw_id, remove_background_birefnet(self._raw_img))
        return self._fg_cut_cache[1]

    def _ensure_cutout(self, remove_bg: bool, harmonize: bool) -> Any:
        from backend.services.vision import harmonize_df11_studio_grade

        if self._raw_img is None:
            return None
        key = (id(self._raw_img), bool(remove_bg), bool(harmonize))
        if self._cutout_key != key or self._cutout_img is None:
            cut = self._get_fg_cutout() if (self._raw_is_precut or remove_bg) else self._raw_img
            self._cutout_img = harmonize_df11_studio_grade(cut) if harmonize else cut
            self._cutout_key = key
            self._dressed_key = None
        return self._cutout_img

    def _resolve_studio_kit(self, cid: str, p: dict[str, Any]) -> Any:
        from backend.services.kits import KitSpec, resolve_club_kit

        base = resolve_club_kit(cid, db_path=self._db_path)
        if not p.get("customKitDirty"):
            return base
        pri = str(p.get("customPrimary") or base.primary)
        sec = str(p.get("customSecondary") or base.secondary)
        pat = str(p.get("customPattern") or base.pattern)
        return KitSpec(base.club_id, base.name, pat, pri, sec, sec, "custom", base.crest_path)

    def _compose(self, p: dict[str, Any]) -> Any:
        from backend.core.compositor import render_df11_card
        from backend.services.kits import dress_or_frame_portrait

        cut = self._ensure_cutout(bool(p.get("removeBg", True)), bool(p.get("harmonize", True)))
        if cut is None:
            return render_df11_card(None, bg_mode=p.get("bgMode", "white_df11"), bg_custom_rgba=self._custom_bg_img, bg_blur=float(p.get("bgBlur", 0.0)))
        kmode, cid = p.get("kitMode", "original"), str(p.get("clubId", "1736"))
        kit = self._resolve_studio_kit(cid, p) if kmode != "original" else None
        dkey = (id(cut), kmode, kit.club_id if kit else "", kit.pattern if kit else "", kit.primary if kit else "", kit.secondary if kit else "", kit.collar if kit else "")
        if self._dressed_key != dkey or self._dressed_img is None:
            self._dressed_img = dress_or_frame_portrait(cut, kit_mode=kmode, kit_spec=kit)
            self._dressed_key = dkey
        return render_df11_card(
            portrait_rgba=self._dressed_img,
            portrait_offset=(float(p.get("offsetX", 0.0)), float(p.get("offsetY", 0.0))),
            portrait_scale=float(p.get("scale", 1.0)),
            bg_mode=p.get("bgMode", "white_df11"),
            bg_custom_rgba=self._custom_bg_img,
            bg_blur=float(p.get("bgBlur", 0.0)),
        )

    def upload_studio_image(
        self, data_url: str, remove_bg: bool = True, harmonize: bool = True, extract_bg: bool = False, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        from backend.core.image_guard import load_guarded_image
        from backend.services.vision import extract_clean_background

        g = load_guarded_image(_decode_b64(data_url))
        self._raw_img = g.image
        self._raw_is_precut = g.is_pre_cutout
        self._fg_cut_cache = None
        self._cutout_key = None
        self._dressed_key = None
        eff_remove = True if extract_bg else bool(remove_bg)
        bg_url = ""
        if extract_bg:
            alpha = self._get_fg_cutout().getchannel("A")
            self._custom_bg_img = extract_clean_background(g.image, alpha)
            bg_url = _to_data_url(self._custom_bg_img)
        merged = {**(params or {}), "removeBg": eff_remove, "harmonize": harmonize}
        if extract_bg:
            merged["bgMode"] = "custom"
        return {"isPreCutout": g.is_pre_cutout, "originalSize": list(g.original_size), "previewDataUrl": _to_data_url(self._compose(merged)), "cleanBgDataUrl": bg_url}

    def extract_studio_background(self, params: dict[str, Any] | None = None) -> dict[str, str]:
        from backend.services.vision import extract_clean_background

        if self._raw_img is None:
            raise ValueError("Sube o pega primero un retrato en el Estudio para extraer su fondo.")
        alpha = self._get_fg_cutout().getchannel("A")
        self._custom_bg_img = extract_clean_background(self._raw_img, alpha)
        merged = {**(params or {}), "removeBg": True, "bgMode": "custom"}
        return {"cleanBgDataUrl": _to_data_url(self._custom_bg_img), "previewDataUrl": _to_data_url(self._compose(merged))}

    def upload_custom_background(self, data_url: str, params: dict[str, Any] | None = None) -> dict[str, str]:
        from backend.core.image_guard import load_guarded_image

        self._custom_bg_img = load_guarded_image(_decode_b64(data_url)).image
        merged = {**(params or {}), "bgMode": "custom"}
        return {"bgDataUrl": _to_data_url(self._custom_bg_img), "previewDataUrl": _to_data_url(self._compose(merged))}

    def render_studio_preview(self, params: dict[str, Any]) -> dict[str, str]:
        return {"previewDataUrl": _to_data_url(self._compose(params))}

    def export_studio_card(self, params: dict[str, Any]) -> dict[str, str]:
        from backend.core.compositor import export_df11_bytes
        from backend.core.fm_config import safe_ntfs_replace, upsert_fm_config_xml, validate_fm_uid
        from backend.services.kits import save_kit_override

        if self._raw_img is None:
            raise ValueError("Sube o selecciona un retrato antes de exportar la ficha DF11.")
        uid, fmt = validate_fm_uid(str(params.get("uid", ""))), ("jpg" if str(params.get("fmt", "png")).lower() in ("jpg", "jpeg") else "png")
        tdir = self._require_approved(Path(params["outDir"]) if params.get("outDir") else self._export_dir)
        if params.get("customKitDirty") and params.get("kitMode", "original") != "original":
            kit = self._resolve_studio_kit(str(params.get("clubId", "1736")), params)
            save_kit_override(kit.club_id, kit.primary, kit.secondary, pattern=kit.pattern, db_path=self._db_path)
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
        from backend.services.sync import scan_ng_regens_vault

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
        return asdict(
            sync_ng_regens_batch(
                self._vault_dir,
                self._export_dir,
                db_path=self._db_path,
                apply_club_kits=bool(o.get("applyClubKits", True)),
                harmonize=bool(o.get("harmonize", True)),
                bg_mode=o.get("bgMode", "white_df11"),
                allow_shrink=bool(o.get("allowShrink", False)),
                cancel_event=self._cancel_sync,
            )
        )

    def cancel_regens_sync(self) -> bool:
        self._cancel_sync.set()
        return True

    def toggle_live_watch(self, enabled: bool, opts: dict[str, Any] | None = None) -> dict[str, bool]:
        from backend.services.sync import QuiescentVaultWatcher, sync_ng_regens_batch

        if self._watcher is not None:
            self._watcher.stop()
            self._watcher = None
        if not enabled:
            return {"watching": False}
        if opts:
            self._live_opts = dict(opts)
        self._watcher = QuiescentVaultWatcher(
            lambda: self._vault_dir,
            on_quiescent=lambda: sync_ng_regens_batch(
                self._vault_dir,
                self._export_dir,
                db_path=self._db_path,
                apply_club_kits=bool(self._live_opts.get("applyClubKits", True)),
                harmonize=bool(self._live_opts.get("harmonize", True)),
            ),
        )
        self._watcher.start()
        return {"watching": True}

    def load_regen_into_studio(self, uid: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        from backend.services.sync import scan_ng_regens_vault

        e = scan_ng_regens_vault(self._vault_dir)
        if uid not in e:
            raise ValueError(f"Regen {uid} no encontrado.")
        b64 = "data:image/png;base64," + base64.b64encode(e[uid].read_bytes()).decode("ascii")
        return {"uid": uid, **self.upload_studio_image(b64, remove_bg=True, harmonize=True, extract_bg=False, params=params)}

    def probe_architecture_health(self) -> dict[str, Any]:
        try:
            import sqlite3
            import onnxruntime as ort

            t0 = time.perf_counter()
            if self._db_path.is_file():
                conn = sqlite3.connect(f"file:{self._db_path}?mode=ro", uri=True, timeout=2.0)
                try:
                    conn.execute("SELECT 1").fetchone()
                finally:
                    conn.close()
            p = ort.get_available_providers()
            return {"dmlActive": "DmlExecutionProvider" in p, "providers": p, "sqliteLatencyMs": round((time.perf_counter() - t0) * 1000.0, 2)}
        except Exception:
            return {"dmlActive": False, "providers": ["CPUExecutionProvider"], "sqliteLatencyMs": 0.0}
