"""Zero-port pywebview js_api bridge with capability-handle directory safety and lazy AI imports."""

from __future__ import annotations

import base64
import io
import json
import os
import re
import tempfile
import threading
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from backend import __version__
from backend.core.paths import (
    get_caras_prueba_dir,
    get_default_pure_export_dir,
    get_default_vault_dir,
    get_extracted_faces_dir,
    get_models_dir,
    get_raw_tshirt_archive_dir,
    get_state_db_path,
    get_studio_root,
    get_tshirt_templates_dir,
)


class CapabilityError(PermissionError):
    """Raised when IPC attempts to write to a directory not approved by native OS dialog or config."""


def _to_data_url(img: Any) -> str:
    buf = io.BytesIO()
    img.save(buf, format="PNG", compress_level=4)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


_MAX_IMAGE_BYTES = 20 * 1024 * 1024
_MAX_B64_CHARS = (_MAX_IMAGE_BYTES * 4) // 3 + 4096
_WIN_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
)
_INVALID_WIN_FILENAME_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')
_GENERIC_LABELS = frozenset({"", "foto directa", "foto_directa", "retrato", "cara extraída", "cara_extraida"})


def _sanitize_creation_stem(raw_text: str) -> str:
    cleaned = str(raw_text or "").strip()
    if cleaned.lower().endswith((".png", ".jpg", ".jpeg")):
        cleaned = Path(cleaned).stem.strip()
    cleaned = _INVALID_WIN_FILENAME_RE.sub("_", cleaned).strip(" .")
    if len(cleaned) > 80:
        cleaned = cleaned[:80].rstrip(" .")
    if not cleaned or cleaned in {".", ".."} or cleaned.upper() in _WIN_RESERVED_NAMES:
        return ""
    return cleaned


def _decode_b64(s: str) -> bytes:
    payload = s.split(",", 1)[1] if "," in s else s
    if len(payload) > _MAX_B64_CHARS:
        from backend.core.image_guard import ImageGuardError

        raise ImageGuardError("El archivo supera el límite máximo permitido de 20 MB.")
    raw = base64.b64decode(payload)
    if len(raw) > _MAX_IMAGE_BYTES:
        from backend.core.image_guard import ImageGuardError

        raise ImageGuardError("El archivo supera el límite máximo permitido de 20 MB.")
    return raw


def _read_guarded_file(path: Path) -> bytes:
    if not path.is_file():
        from backend.core.image_guard import ImageGuardError

        raise ImageGuardError(f"No se encontró el archivo de imagen: {path.name}")
    if path.stat().st_size > _MAX_IMAGE_BYTES:
        from backend.core.image_guard import ImageGuardError

        raise ImageGuardError("El archivo supera el límite máximo permitido de 20 MB.")
    with path.open("rb") as fh:
        data = fh.read(_MAX_IMAGE_BYTES + 1)
    if len(data) > _MAX_IMAGE_BYTES:
        from backend.core.image_guard import ImageGuardError

        raise ImageGuardError("El archivo supera el límite máximo permitido de 20 MB.")
    return data


def _paths_overlap(a: Path, b: Path) -> bool:
    ra, rb = a.resolve(), b.resolve()
    return ra == rb or ra.is_relative_to(rb) or rb.is_relative_to(ra)


class StudioBridge:
    def __init__(
        self,
        vault_dir: Path | None = None,
        export_dir: Path | None = None,
        db_path: Path | None = None,
        templates_dir: Path | None = None,
        raw_archive_dir: Path | None = None,
        extracted_faces_dir: Path | None = None,
        sample_faces_dir: Path | None = None,
        export_pure_dir: Path | None = None,
    ) -> None:
        self._db_path = db_path or get_state_db_path()
        self._vault_dir = (vault_dir or get_default_vault_dir()).resolve()
        self._export_dir = (export_dir or (get_studio_root() / "Exports" / "000_DF11_Regens_Override")).resolve()
        self._export_pure_dir = (export_pure_dir or get_default_pure_export_dir()).resolve()
        self._facepack_dir: Path | None = None
        self._facepack_pure_dir: Path | None = None
        self._export_variant: str = "classic"
        self._templates_dir = (templates_dir or get_tshirt_templates_dir()).resolve()
        self._raw_archive_dir = (raw_archive_dir or get_raw_tshirt_archive_dir()).resolve()
        self._extracted_faces_dir = (extracted_faces_dir or get_extracted_faces_dir()).resolve()
        self._sample_faces_dir = (sample_faces_dir or get_caras_prueba_dir()).resolve()
        self._approved_dirs: set[Path] = {self._export_dir, self._export_pure_dir}
        self._window: Any = None
        self._addon_window: Any = None
        self._addon_open: bool = False
        self._shutting_down: bool = False
        self._pending_addon_capture: dict[str, Any] | None = None
        self._mod_lock = threading.Lock()
        self._sync_lock = threading.Lock()
        self._mod_session: Any = None
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
        self._hotkey_mgr: Any = None
        self._live_opts: dict[str, Any] = {
            "applyClubKits": True,
            "harmonize": True,
            "bgMode": "white_df11",
            "variant": "classic",
        }

    def _mod(self) -> Any:
        if self._mod_session is None:
            with self._mod_lock:
                if self._mod_session is None:
                    from backend.services.studio_workflow import ModularWorkflowSession

                    self._mod_session = ModularWorkflowSession(
                        templates_dir=self._templates_dir,
                        raw_archive_dir=self._raw_archive_dir,
                        extracted_faces_dir=self._extracted_faces_dir,
                        sample_faces_dir=self._sample_faces_dir,
                        db_path=self._db_path,
                    )
        return self._mod_session

    def _get_pref(self, key: str, default: str = "") -> str:
        from backend.services.kits import init_state_db

        if not self._db_path.is_file():
            return default
        with init_state_db(self._db_path) as c:
            row = c.execute("SELECT pref_val FROM app_prefs WHERE pref_key=?", (key,)).fetchone()
            return str(row[0]) if row and row[0] else default

    def _set_pref(self, key: str, val: str) -> None:
        from backend.services.kits import init_state_db

        with init_state_db(self._db_path) as c:
            c.execute("INSERT OR REPLACE INTO app_prefs VALUES (?, ?)", (key, str(val)))

    def _resolve_dialog_dir(self, pref_key: str, fallback: Path | None = None) -> str:
        saved = self._get_pref(pref_key)
        if saved:
            cand = Path(saved)
            if cand.is_dir():
                return str(cand.resolve())
            if cand.parent.is_dir():
                return str(cand.parent.resolve())
        if fallback:
            if fallback.is_dir():
                return str(fallback.resolve())
            if fallback.parent.is_dir():
                return str(fallback.parent.resolve())
        pics = Path.home() / "Pictures"
        return str(pics.resolve()) if pics.is_dir() else str(Path.home().resolve())

    def _attach_window(self, window: Any) -> None:
        self._window = window

    def _attach_addon_window(self, addon_win: Any) -> None:
        self._addon_window = addon_win

    def _on_addon_closing(self) -> bool:
        if self._shutting_down:
            return False
        self.restore_from_capture_addon()
        return True

    def _shutdown_windows(self) -> None:
        self._shutting_down = True
        if self._hotkey_mgr is not None:
            try:
                self._hotkey_mgr.stop()
            except Exception:
                pass
            self._hotkey_mgr = None
        if self._watcher is not None:
            try:
                self._watcher.stop()
            except Exception:
                pass
            self._watcher = None
        if self._addon_window is not None and hasattr(self._addon_window, "destroy"):
            try:
                self._addon_window.destroy()
            except Exception:
                pass
            self._addon_window = None

    def _require_approved(self, folder: Path) -> Path:
        r = folder.resolve()
        if _paths_overlap(r, self._vault_dir) or r not in self._approved_dirs:
            raise CapabilityError(f"Directorio de escritura no autorizado: {r}")
        return r

    def get_bootstrap_state(self) -> dict[str, Any]:
        from backend.core.fm_config import detect_fm_graphics_collision
        from backend.services.kits import list_save_profiles, load_merged_clubs
        from backend.services.sync import check_fm_storage_health

        saved_export = self._get_pref("last_export_dir")
        saved_export_pure = self._get_pref("last_export_pure_dir")
        saved_facepack = self._get_pref("last_facepack_dir")
        saved_facepack_pure = self._get_pref("last_facepack_pure_dir")
        saved_vault = self._get_pref("last_vault_dir")
        raw_variant = self._get_pref("export_variant", self._export_variant)
        self._export_variant = raw_variant if raw_variant in ("classic", "pure", "dual") else "classic"

        cand_export = (
            Path(saved_export).resolve()
            if saved_export and (Path(saved_export).is_dir() or Path(saved_export).parent.is_dir())
            else None
        )
        cand_export_pure = (
            Path(saved_export_pure).resolve()
            if saved_export_pure and (Path(saved_export_pure).is_dir() or Path(saved_export_pure).parent.is_dir())
            else None
        )
        cand_facepack = Path(saved_facepack).resolve() if saved_facepack and Path(saved_facepack).is_dir() else None
        cand_facepack_pure = (
            Path(saved_facepack_pure).resolve() if saved_facepack_pure and Path(saved_facepack_pure).is_dir() else None
        )

        if saved_vault and Path(saved_vault).is_dir():
            cand_v = Path(saved_vault).resolve()
            eff_exp = cand_export if cand_export is not None else self._export_dir
            eff_exp_pure = cand_export_pure if cand_export_pure is not None else self._export_pure_dir
            if (
                not _paths_overlap(cand_v, eff_exp)
                and not _paths_overlap(cand_v, eff_exp_pure)
                and (cand_facepack is None or not _paths_overlap(cand_v, cand_facepack))
                and (cand_facepack_pure is None or not _paths_overlap(cand_v, cand_facepack_pure))
            ):
                self._vault_dir = cand_v
                self._approved_dirs = {d for d in self._approved_dirs if not _paths_overlap(d, self._vault_dir)}

        if cand_export is not None and not _paths_overlap(cand_export, self._vault_dir):
            self._export_dir = cand_export
            self._approved_dirs.add(self._export_dir)
        if (
            cand_export_pure is not None
            and not _paths_overlap(cand_export_pure, self._vault_dir)
            and not _paths_overlap(cand_export_pure, self._export_dir)
        ):
            self._export_pure_dir = cand_export_pure
            self._approved_dirs.add(self._export_pure_dir)
        if cand_facepack is not None and not _paths_overlap(cand_facepack, self._vault_dir):
            self._facepack_dir = cand_facepack
            self._approved_dirs.add(self._facepack_dir)
        if (
            cand_facepack_pure is not None
            and not _paths_overlap(cand_facepack_pure, self._vault_dir)
            and (self._facepack_dir is None or not _paths_overlap(cand_facepack_pure, self._facepack_dir))
        ):
            self._facepack_pure_dir = cand_facepack_pure
            self._approved_dirs.add(self._facepack_pure_dir)

        m = get_models_dir()
        ok = all((m / f).is_file() for f in ("face_detection_yunet_2023mar.onnx", "selfie_multiclass_256x256.onnx", "birefnet-general-lite.onnx"))
        raw_theme = self._get_pref("theme", "dark")
        theme = raw_theme if raw_theme in ("dark", "light") else "dark"
        save_profiles = (
            list_save_profiles(self._db_path)
            if self._db_path.is_file()
            else [{"saveId": "default", "displayName": "Partida Principal", "isActive": True}]
        )
        active_save = next((p["saveId"] for p in save_profiles if p["isActive"]), "default")
        return {
            "version": __version__,
            "clubs": load_merged_clubs(self._db_path),
            "vaultDir": str(self._vault_dir),
            "exportDir": str(self._export_dir),
            "exportPureDir": str(self._export_pure_dir),
            "facepackDir": str(self._facepack_dir) if self._facepack_dir else "",
            "facepackPureDir": str(self._facepack_pure_dir) if self._facepack_pure_dir else "",
            "exportVariant": self._export_variant,
            "fmGraphicsCollision": detect_fm_graphics_collision(self._export_dir, self._export_pure_dir),
            "fmFacepackCollision": detect_fm_graphics_collision(self._facepack_dir, self._facepack_pure_dir),
            "storageHealth": asdict(check_fm_storage_health(self._export_dir)),
            "hasModels": ok,
            "liveWatching": self._watcher is not None,
            "captureHotkey": bool(self._hotkey_mgr and self._hotkey_mgr.is_running),
            "activeSaveId": active_save,
            "saveProfiles": save_profiles,
            "theme": theme,
        }

    def set_export_variant(self, variant: str) -> dict[str, str]:
        v = str(variant or "classic").strip().lower()
        val = v if v in ("classic", "pure", "dual") else "classic"
        self._export_variant = val
        self._set_pref("export_variant", val)
        return {"exportVariant": val}

    def set_ui_theme(self, theme: str) -> dict[str, str]:
        val = "light" if str(theme).lower() == "light" else "dark"
        self._set_pref("theme", val)
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
        from backend.core.fm_config import detect_fm_graphics_collision
        from backend.services.sync import check_fm_storage_health

        if role == "vault":
            pref_key = "last_vault_dir"
            fallback = self._vault_dir
        elif role == "facepack":
            pref_key = "last_facepack_dir"
            fallback = self._facepack_dir or self._export_dir
        elif role == "facepack_pure":
            pref_key = "last_facepack_pure_dir"
            fallback = self._facepack_pure_dir or self._export_pure_dir
        elif role == "export_pure":
            pref_key = "last_export_pure_dir"
            fallback = self._export_pure_dir
        else:
            pref_key = "last_export_dir"
            fallback = self._export_dir
        init_dir = self._resolve_dialog_dir(pref_key, fallback)
        res = self._window.create_file_dialog(webview.FOLDER_DIALOG, directory=init_dir) if self._window else None
        if not res:
            return None
        c = Path(res[0]).resolve()
        if role == "vault":
            if (
                _paths_overlap(c, self._export_dir)
                or _paths_overlap(c, self._export_pure_dir)
                or (self._facepack_dir is not None and _paths_overlap(c, self._facepack_dir))
                or (self._facepack_pure_dir is not None and _paths_overlap(c, self._facepack_pure_dir))
            ):
                raise CapabilityError("La bóveda NG_Regens de solo lectura no puede solaparse con la carpeta de salida.")
            self._vault_dir = c
            self._approved_dirs = {d for d in self._approved_dirs if not _paths_overlap(d, c)}
        elif role == "facepack":
            if _paths_overlap(c, self._vault_dir):
                raise CapabilityError("La carpeta del Pack de Faces no puede solaparse con la bóveda NG_Regens de solo lectura.")
            if self._facepack_pure_dir is not None and _paths_overlap(c, self._facepack_pure_dir):
                raise CapabilityError("La carpeta del Pack Classic y la del Pack DF11 Pure deben ser independientes.")
            self._approved_dirs.add(c)
            self._facepack_dir = c
        elif role == "facepack_pure":
            if _paths_overlap(c, self._vault_dir):
                raise CapabilityError("La carpeta del Pack DF11 Pure no puede solaparse con la bóveda NG_Regens de solo lectura.")
            if self._facepack_dir is not None and _paths_overlap(c, self._facepack_dir):
                raise CapabilityError("La carpeta del Pack DF11 Pure y la del Pack Classic deben ser independientes.")
            self._approved_dirs.add(c)
            self._facepack_pure_dir = c
        elif role == "export_pure":
            if _paths_overlap(c, self._vault_dir):
                raise CapabilityError("La carpeta de salida Pure no puede solaparse con la bóveda NG_Regens de solo lectura.")
            if _paths_overlap(c, self._export_dir):
                raise CapabilityError("La carpeta DF11 Pure y la carpeta Classic deben ser independientes.")
            self._approved_dirs.add(c)
            self._export_pure_dir = c
        else:
            if _paths_overlap(c, self._vault_dir):
                raise CapabilityError("La carpeta de salida no puede solaparse con la bóveda NG_Regens de solo lectura.")
            if _paths_overlap(c, self._export_pure_dir):
                raise CapabilityError("La carpeta Classic y la carpeta DF11 Pure deben ser independientes.")
            self._approved_dirs.add(c)
            self._export_dir = c
        self._set_pref(pref_key, str(c))
        return {
            "path": str(c),
            "storageHealth": asdict(check_fm_storage_health(c)),
            "fmGraphicsCollision": detect_fm_graphics_collision(self._export_dir, self._export_pure_dir),
            "fmFacepackCollision": detect_fm_graphics_collision(self._facepack_dir, self._facepack_pure_dir),
        }

    def _pick_image_file(
        self,
        pref_key: str,
        fallback_dir: Path | None = None,
        sync_last_image: bool = True,
    ) -> Path | None:
        import webview

        if not self._window:
            return None
        init_dir = self._resolve_dialog_dir(pref_key, fallback_dir if fallback_dir is not None else self._vault_dir)
        res = self._window.create_file_dialog(
            webview.OPEN_DIALOG,
            directory=init_dir,
            allow_multiple=False,
            file_types=("Imágenes DF11 (*.png;*.jpg;*.jpeg;*.webp;*.avif)",),
        )
        if not res:
            return None
        chosen = Path(res[0]).resolve()
        if not chosen.is_file():
            return None
        if pref_key != "last_facepack_dir" or not _paths_overlap(chosen.parent, self._vault_dir):
            self._set_pref(pref_key, str(chosen.parent))
        if sync_last_image and pref_key != "last_image_dir":
            self._set_pref("last_image_dir", str(chosen.parent))
        return chosen

    def pick_and_upload_studio_image(
        self, remove_bg: bool = True, harmonize: bool = True, extract_bg: bool = False, params: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        chosen = self._pick_image_file("last_image_dir")
        if chosen is None:
            return None
        b64 = "data:image/png;base64," + base64.b64encode(_read_guarded_file(chosen)).decode("ascii")
        out = self.upload_studio_image(b64, remove_bg=remove_bg, harmonize=harmonize, extract_bg=extract_bg, params=params)
        return {**out, "fileName": chosen.name, "directory": str(chosen.parent)}

    def pick_and_upload_custom_background(self, params: dict[str, Any] | None = None) -> dict[str, str] | None:
        chosen = self._pick_image_file("last_bg_dir")
        if chosen is None:
            return None
        b64 = "data:image/png;base64," + base64.b64encode(_read_guarded_file(chosen)).decode("ascii")
        out = self.upload_custom_background(b64, params=params)
        return {**out, "fileName": chosen.name, "directory": str(chosen.parent)}

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

    def _compose_legacy_subject(self, p: dict[str, Any], require_cutout: bool = False) -> Any:
        import numpy as np
        from PIL import Image
        from backend.core.compositor import _place_portrait
        from backend.core.dsp import enhance_df11_pure_optics
        from backend.services.kits import dress_or_frame_portrait

        cut = self._ensure_cutout(bool(p.get("removeBg", True)) or require_cutout, bool(p.get("harmonize", True)))
        if cut is None:
            return None
        kmode, cid = p.get("kitMode", "original"), str(p.get("clubId", "1736"))
        kit = self._resolve_studio_kit(cid, p) if kmode != "original" else None
        dkey = (id(cut), kmode, kit.club_id if kit else "", kit.pattern if kit else "", kit.primary if kit else "", kit.secondary if kit else "", kit.collar if kit else "")
        if self._dressed_key != dkey or self._dressed_img is None:
            self._dressed_img = dress_or_frame_portrait(cut, kit_mode=kmode, kit_spec=kit)
            self._dressed_key = dkey
        ox, oy = float(p.get("offsetX", 0.0)), float(p.get("offsetY", 0.0))
        scale = float(p.get("scale", 1.0))
        enh = float(p.get("enhanceQuality", 0.0))
        placed = _place_portrait(self._dressed_img, (ox, oy), scale)
        if enh > 1e-3:
            placed = enhance_df11_pure_optics(placed, amount=enh, upscale_hint=max(1.0, scale))
        return Image.fromarray(placed, mode="RGBA")

    def _compose(self, p: dict[str, Any], variant: str | None = None) -> Any:
        from backend.core.compositor import render_df11_card, render_df11_pure_card

        eff_var = "pure" if str(variant or p.get("previewVariant") or "classic").strip().lower() == "pure" else "classic"
        subj = self._compose_legacy_subject(p, require_cutout=(eff_var == "pure"))
        if eff_var == "pure":
            return render_df11_pure_card(subj)
        return render_df11_card(
            portrait_rgba=subj,
            portrait_offset=(0.0, 0.0),
            portrait_scale=1.0,
            bg_mode=p.get("bgMode", "white_df11"),
            bg_custom_rgba=self._custom_bg_img,
            bg_blur=float(p.get("bgBlur", 0.0)),
            enhance_quality=0.0,
        )

    def _compose_dual(self, p: dict[str, Any]) -> tuple[Any, Any]:
        from backend.core.compositor import render_df11_card, render_df11_pure_card

        subj = self._compose_legacy_subject(p, require_cutout=True)
        classic_im = render_df11_card(
            portrait_rgba=subj,
            portrait_offset=(0.0, 0.0),
            portrait_scale=1.0,
            bg_mode=p.get("bgMode", "white_df11"),
            bg_custom_rgba=self._custom_bg_img,
            bg_blur=float(p.get("bgBlur", 0.0)),
            enhance_quality=0.0,
        )
        return classic_im, render_df11_pure_card(subj)

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
        if str((params or {}).get("step1Mode", "modular")).strip().lower() == "direct_photo":
            raise ValueError(
                "En modo Foto Directa el fondo original ya forma parte de la foto; cambia a Modo Capas si deseas aislar el retrato."
            )
        from backend.services.vision import extract_clean_background, remove_background_birefnet

        merged = {**(params or {}), "removeBg": True, "bgMode": "custom"}
        if merged.get("modular"):
            head_id = str(merged.get("headAssetId", "")).strip()
            asset = self._mod().get_head_asset(head_id) if head_id else None
            if asset is not None:
                if asset.is_pre_cutout or asset.source_rgba is None:
                    raise ValueError("Esta imagen ya viene recortada sin fondo; elige un fondo de estudio o sube un fondo propio.")
                alpha = asset.source_fg_alpha or remove_background_birefnet(asset.source_rgba).getchannel("A")
                self._custom_bg_img = extract_clean_background(asset.source_rgba, alpha)
            else:
                if self._raw_img is None:
                    raise ValueError("Sube o pega primero un retrato en el Estudio para extraer su fondo.")
                if self._raw_is_precut:
                    raise ValueError("Esta imagen ya viene recortada sin fondo; elige un fondo de estudio o sube un fondo propio.")
                alpha = self._get_fg_cutout().getchannel("A")
                self._custom_bg_img = extract_clean_background(self._raw_img, alpha)
            card = self._mod().compose_step_card(merged, custom_bg=self._custom_bg_img)
            return {"cleanBgDataUrl": _to_data_url(self._custom_bg_img), "previewDataUrl": _to_data_url(card)}

        if self._raw_img is None:
            raise ValueError("Sube o pega primero un retrato en el Estudio para extraer su fondo.")
        alpha = self._get_fg_cutout().getchannel("A")
        self._custom_bg_img = extract_clean_background(self._raw_img, alpha)
        return {"cleanBgDataUrl": _to_data_url(self._custom_bg_img), "previewDataUrl": _to_data_url(self._compose(merged))}

    def upload_custom_background(self, data_url: str, params: dict[str, Any] | None = None) -> dict[str, str]:
        from backend.core.image_guard import load_guarded_image

        self._custom_bg_img = load_guarded_image(_decode_b64(data_url)).image
        merged = {**(params or {}), "bgMode": "custom"}
        card = self._mod().compose_step_card(merged, custom_bg=self._custom_bg_img) if merged.get("modular") else self._compose(merged)
        return {"bgDataUrl": _to_data_url(self._custom_bg_img), "previewDataUrl": _to_data_url(card)}

    def render_studio_preview(self, params: dict[str, Any]) -> dict[str, str]:
        return {"previewDataUrl": _to_data_url(self._compose(params))}

    def _resolve_export_dirs(
        self,
        params: dict[str, Any],
        export_target: str,
        export_variant: str,
    ) -> tuple[Path | None, Path | None]:
        classic_dir: Path | None = None
        pure_dir: Path | None = None
        if export_variant in ("classic", "dual"):
            raw_out = str(params.get("outDir") or "").strip()
            if export_target == "facepack":
                cand_c = Path(raw_out) if raw_out else self._facepack_dir
                if cand_c is None:
                    raise ValueError("Selecciona primero la carpeta del Pack de Faces de Football Manager.")
                classic_dir = self._require_approved(cand_c)
            else:
                cand_c = Path(raw_out) if raw_out else self._export_dir
                classic_dir = self._require_approved(cand_c)

        if export_variant in ("pure", "dual"):
            raw_pure = str(params.get("outPureDir") or "").strip()
            fallback_raw = str(params.get("outDir") or "").strip() if export_variant == "pure" else ""
            if export_target == "facepack":
                cand_p = (
                    Path(raw_pure)
                    if raw_pure
                    else (Path(fallback_raw) if fallback_raw else self._facepack_pure_dir)
                )
                if cand_p is None:
                    raise ValueError("Selecciona primero la carpeta del Pack de Faces DF11 Pure de Football Manager.")
                pure_dir = self._require_approved(cand_p)
            else:
                cand_p = (
                    Path(raw_pure)
                    if raw_pure
                    else (Path(fallback_raw) if fallback_raw else self._export_pure_dir)
                )
                pure_dir = self._require_approved(cand_p)

        if classic_dir is not None and pure_dir is not None and _paths_overlap(classic_dir, pure_dir):
            raise ValueError("Las carpetas de exportación Classic y DF11 Pure deben ser independientes y no pueden solaparse.")
        return classic_dir, pure_dir

    def _resolve_export_stem_and_uid(
        self,
        raw_uid: str,
        export_target: str,
        check_targets: list[tuple[Path, str]],
        fallback_label: str = "",
    ) -> tuple[str, str | None]:
        from backend.core.fm_config import VALID_FM_UID_RE, validate_fm_uid

        if export_target == "facepack":
            valid_uid = validate_fm_uid(raw_uid)
            return valid_uid, valid_uid

        cleaned = str(raw_uid or "").strip()
        if VALID_FM_UID_RE.fullmatch(cleaned):
            return cleaned, cleaned
        if cleaned:
            if "/" in cleaned or "\\" in cleaned or ".." in cleaned:
                raise ValueError("El nombre de archivo no puede contener rutas ni barras.")
            stem = _sanitize_creation_stem(cleaned)
            if not stem:
                raise ValueError("Nombre de archivo no válido para Nuestras creaciones.")
            return stem, None

        lbl = str(fallback_label or "").strip()
        cand_base = _sanitize_creation_stem(lbl) if lbl.lower() not in _GENERIC_LABELS else ""
        base = cand_base or f"DF11_{time.strftime('%Y%m%d_%H%M%S')}"
        stem = base
        idx = 2
        while any((d / f"{stem}.{ext}").exists() for d, ext in check_targets):
            stem = f"{base}_{idx}"
            idx += 1
        return stem, None

    def _commit_card_exports_atomic(
        self,
        file_stem: str,
        fm_uid: str | None,
        update_xml: bool,
        export_variant: str,
        classic_target: tuple[Path, str, bytes] | None,
        pure_target: tuple[Path, str, bytes] | None,
    ) -> dict[str, Any]:
        from backend.core.fm_config import detect_fm_graphics_collision, safe_ntfs_replace, upsert_fm_config_xml

        plans: list[tuple[str, Path, str, bytes]] = []
        if classic_target is not None:
            plans.append(("classic", classic_target[0], classic_target[1], classic_target[2]))
        if pure_target is not None:
            plans.append(("pure", pure_target[0], pure_target[1], pure_target[2]))

        staged: list[tuple[str, Path, Path, bool]] = []
        committed: list[tuple[Path, bool]] = []
        try:
            for kind, tdir, ext, payload in plans:
                tdir.mkdir(parents=True, exist_ok=True)
                dst = tdir / f"{file_stem}.{ext}"
                existed_before = dst.exists()
                fd, tname = tempfile.mkstemp(prefix=f".{file_stem[:24]}_", suffix=".tmp", dir=str(tdir))
                tp = Path(tname)
                staged.append((kind, tp, dst, existed_before))
                with os.fdopen(fd, "wb") as fh:
                    fh.write(payload)
                    fh.flush()
                    os.fsync(fh.fileno())

            for _kind, tp, dst, existed_before in staged:
                safe_ntfs_replace(tp, dst)
                committed.append((dst, existed_before))
        except Exception:
            for done_dst, existed_before in committed:
                if not existed_before:
                    try:
                        done_dst.unlink(missing_ok=True)
                    except OSError:
                        pass
            raise
        finally:
            for _kind, tp, _dst, _existed in staged:
                if tp.exists():
                    tp.unlink(missing_ok=True)

        if fm_uid is not None and update_xml:
            for _kind, tdir, ext, _payload in plans:
                if ext == "png":
                    upsert_fm_config_xml(tdir / "config.xml", [fm_uid])

        by_kind = {kind: str(dst) for kind, _tp, dst, _ex in staged}
        c_dir = classic_target[0] if classic_target is not None else None
        p_dir = pure_target[0] if pure_target is not None else None
        primary_saved = by_kind.get("classic") or by_kind.get("pure") or ""
        return {
            "savedPath": primary_saved,
            "savedPurePath": by_kind.get("pure", ""),
            "exportVariant": export_variant,
            "fmGraphicsCollision": detect_fm_graphics_collision(c_dir, p_dir) if export_variant == "dual" else False,
        }

    def export_studio_card(self, params: dict[str, Any]) -> dict[str, Any]:
        from backend.core.compositor import export_df11_bytes
        from backend.services.kits import save_kit_override

        if self._raw_img is None:
            raise ValueError("Sube o selecciona un retrato antes de exportar la ficha DF11.")
        export_target = str(params.get("exportTarget", "creations")).strip().lower()
        raw_var = str(params.get("exportVariant") or "classic").strip().lower()
        export_variant = raw_var if raw_var in ("classic", "pure", "dual") else "classic"
        fmt = "jpg" if str(params.get("fmt", "png")).lower() in ("jpg", "jpeg") else "png"
        if export_target == "facepack":
            fmt = "png"
        elif export_variant in ("pure", "dual") and fmt != "png":
            raise ValueError("El formato oficial DF11 Pure exige exportación en PNG transparente (32-bit RGBA).")

        classic_dir, pure_dir = self._resolve_export_dirs(params, export_target, export_variant)
        check_targets: list[tuple[Path, str]] = []
        if classic_dir is not None:
            check_targets.append((classic_dir, fmt))
        if pure_dir is not None:
            check_targets.append((pure_dir, "png"))
        file_stem, fm_uid = self._resolve_export_stem_and_uid(
            str(params.get("uid", "")),
            export_target,
            check_targets,
            str(params.get("fileLabel", "")),
        )
        if params.get("customKitDirty") and params.get("kitMode", "original") != "original":
            kit = self._resolve_studio_kit(str(params.get("clubId", "1736")), params)
            save_kit_override(kit.club_id, kit.primary, kit.secondary, pattern=kit.pattern, db_path=self._db_path)

        if export_variant == "dual":
            c_im, p_im = self._compose_dual(params)
            assert classic_dir is not None and pure_dir is not None
            c_target = (classic_dir, fmt, export_df11_bytes(c_im, fmt=fmt))  # type: ignore[arg-type]
            p_target = (pure_dir, "png", export_df11_bytes(p_im, fmt="png"))
        elif export_variant == "pure":
            p_im = self._compose(params, variant="pure")
            assert pure_dir is not None
            c_target = None
            p_target = (pure_dir, "png", export_df11_bytes(p_im, fmt="png"))
        else:
            c_im = self._compose(params, variant="classic")
            assert classic_dir is not None
            c_target = (classic_dir, fmt, export_df11_bytes(c_im, fmt=fmt))  # type: ignore[arg-type]
            p_target = None

        return self._commit_card_exports_atomic(
            file_stem=file_stem,
            fm_uid=fm_uid,
            update_xml=bool(params.get("updateConfigXml", True)),
            export_variant=export_variant,
            classic_target=c_target,
            pure_target=p_target,
        )

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

    def import_squad_text(self, raw_text: str, save_id: str = "") -> dict[str, int]:
        from backend.services.sync import import_squad_club_mappings

        return {"mapped": import_squad_club_mappings(raw_text, db_path=self._db_path, save_id=save_id or None)}

    def list_save_profiles(self) -> list[dict[str, Any]]:
        from backend.services.kits import list_save_profiles

        return list_save_profiles(self._db_path)

    def upsert_save_profile(self, save_id: str, display_name: str, activate: bool = True) -> dict[str, Any]:
        from backend.services.kits import get_active_save_id, upsert_save_profile

        profiles = upsert_save_profile(save_id, display_name, activate=bool(activate), db_path=self._db_path)
        return {"activeSaveId": get_active_save_id(self._db_path), "saveProfiles": profiles}

    def set_active_save_profile(self, save_id: str) -> dict[str, Any]:
        from backend.services.kits import get_active_save_id, set_active_save_profile

        profiles = set_active_save_profile(save_id, db_path=self._db_path)
        return {"activeSaveId": get_active_save_id(self._db_path), "saveProfiles": profiles}

    def start_regens_sync(self, o: dict[str, Any]) -> dict[str, Any]:
        from backend.services.sync import sync_ng_regens_batch

        raw_var = str(o.get("variant") or "classic").strip().lower()
        variant = raw_var if raw_var in ("classic", "pure", "dual") else "classic"
        out_dir = self._require_approved(self._export_dir)
        pure_out_dir = self._require_approved(self._export_pure_dir) if variant in ("pure", "dual") else None
        if variant == "dual" and pure_out_dir is not None and _paths_overlap(out_dir, pure_out_dir):
            raise ValueError("Las carpetas Classic y DF11 Pure para NG_Regens deben ser independientes.")
        self._cancel_sync.clear()
        with self._sync_lock:
            return asdict(
                sync_ng_regens_batch(
                    self._vault_dir,
                    out_dir,
                    db_path=self._db_path,
                    apply_club_kits=bool(o.get("applyClubKits", True)),
                    harmonize=bool(o.get("harmonize", True)),
                    bg_mode=o.get("bgMode", "white_df11"),
                    allow_shrink=bool(o.get("allowShrink", False)),
                    cancel_event=self._cancel_sync,
                    templates_dir=self._templates_dir,
                    pure_out_dir=pure_out_dir,
                    variant=variant,  # type: ignore[arg-type]
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
        self._require_approved(self._export_dir)
        if opts:
            self._live_opts = dict(opts)
        raw_var = str(self._live_opts.get("variant") or "classic").strip().lower()
        live_var = raw_var if raw_var in ("classic", "pure", "dual") else "classic"
        if live_var in ("pure", "dual"):
            pure_chk = self._require_approved(self._export_pure_dir)
            if live_var == "dual" and _paths_overlap(self._export_dir, pure_chk):
                raise ValueError("Las carpetas Classic y DF11 Pure para Live Sync deben ser independientes.")

        def _run_live() -> None:
            with self._sync_lock:
                rv = str(self._live_opts.get("variant") or "classic").strip().lower()
                lv = rv if rv in ("classic", "pure", "dual") else "classic"
                p_out = self._require_approved(self._export_pure_dir) if lv in ("pure", "dual") else None
                sync_ng_regens_batch(
                    self._vault_dir,
                    self._require_approved(self._export_dir),
                    db_path=self._db_path,
                    apply_club_kits=bool(self._live_opts.get("applyClubKits", True)),
                    harmonize=bool(self._live_opts.get("harmonize", True)),
                    bg_mode=self._live_opts.get("bgMode", "white_df11"),
                    templates_dir=self._templates_dir,
                    pure_out_dir=p_out,
                    variant=lv,  # type: ignore[arg-type]
                )

        self._watcher = QuiescentVaultWatcher(lambda: self._vault_dir, on_quiescent=_run_live)
        self._watcher.start()
        return {"watching": True}

    def load_regen_into_studio(self, uid: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        from backend.services.kits import init_state_db
        from backend.services.sync import scan_ng_regens_vault
        from backend.services.templates import get_club_shirt_template

        e = scan_ng_regens_vault(self._vault_dir)
        if uid not in e:
            raise ValueError(f"Regen {uid} no encontrado.")
        club_id = ""
        if self._db_path.is_file():
            with init_state_db(self._db_path) as c:
                row = c.execute("SELECT club_id FROM squad_map WHERE uid=?", (uid,)).fetchone()
                club_id = str(row[0]) if row and row[0] else ""
        matched_tpl = get_club_shirt_template(club_id, tpl_dir=self._templates_dir, db_path=self._db_path) if club_id else None
        tpl_id = matched_tpl.template_id if matched_tpl is not None else ""

        raw_bytes = _read_guarded_file(e[uid])
        b64 = "data:image/png;base64," + base64.b64encode(raw_bytes).decode("ascii")
        staged = self._mod().stage_raw_face(raw_bytes, file_name=f"{uid}.png")
        ext_opts = {
            **staged["suggestedViewport"],
            "templateId": tpl_id,
            "wearMode": "template",
            "clubId": club_id or "1736",
        }
        extracted = self._mod().extract_staged_face(ext_opts, custom_bg=self._custom_bg_img)
        legacy = self.upload_studio_image(b64, remove_bg=True, harmonize=True, extract_bg=False, params=params)
        return {
            **legacy,
            "uid": uid,
            "clubId": club_id,
            "matchedTemplateId": tpl_id,
            "headAssetId": extracted["headAssetId"],
            "autoFit": extracted["autoFit"],
            "previewDataUrl": extracted["previewDataUrl"],
        }

    # --- Modular 3-Tool & Step-by-Step Layer API ---

    def _sync_legacy_raw(self, raw_img: Any, is_precut: bool) -> None:
        self._raw_img = raw_img
        self._raw_is_precut = is_precut
        self._fg_cut_cache = None
        self._cutout_key = None
        self._dressed_key = None

    def _route_captured_png(
        self,
        res: Any,
        tgt: str,
        params: dict[str, Any] | None = None,
        dialog_win: Any = None,
    ) -> dict[str, Any]:
        meta: dict[str, Any] = {
            "cancelled": False,
            "target": tgt,
            "captureWidth": res.width,
            "captureHeight": res.height,
            "drmWarning": res.drm_black_warning,
            "lowResWarning": res.low_res_warning,
        }
        stamp = int(time.time() * 1000) % 1_000_000
        if tgt == "direct_photo":
            out = self._mod().load_direct_photo(
                res.png_bytes,
                file_name=f"Captura_{stamp}.png",
                extra_params=params,
                custom_bg=self._custom_bg_img,
            )
            return {**out, **meta}
        if tgt == "raw_face":
            out = self._mod().stage_raw_face(res.png_bytes, file_name=f"Captura_Cara_{stamp}.png")
            self._sync_legacy_raw(self._mod()._crop_raw_img, self._mod()._crop_is_precut)
            return {**out, **meta}
        if tgt == "raw_shirt":
            out = self._mod().stage_raw_shirt(
                res.png_bytes,
                file_name=f"Captura_Camiseta_{stamp}.png",
                auto_torso_frame=True,
            )
            return {**out, **meta}

        import webview
        from backend.core.fm_config import safe_ntfs_replace

        active_dlg_win = dialog_win or self._window
        if not active_dlg_win:
            return {"cancelled": True}
        init_dir = self._resolve_dialog_dir("last_clip_save_dir", self._export_dir)
        dlg = active_dlg_win.create_file_dialog(
            webview.SAVE_DIALOG,
            directory=init_dir,
            save_filename=f"Recorte_DF11_{stamp}.png",
            file_types=("Imagen PNG (*.png)",),
        )
        if not dlg:
            return {"cancelled": True}
        raw_dst = dlg[0] if isinstance(dlg, (list, tuple)) else str(dlg)
        dst = Path(raw_dst).resolve()
        if dst.suffix.lower() != ".png":
            dst = dst.with_suffix(".png")
        if _paths_overlap(dst, self._vault_dir):
            raise CapabilityError("No se permite guardar recortes dentro de la bóveda NG_Regens de solo lectura.")
        dst.parent.mkdir(parents=True, exist_ok=True)
        fd, tname = tempfile.mkstemp(prefix=".clip_", suffix=".tmp", dir=str(dst.parent))
        tp = Path(tname)
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(res.png_bytes)
            safe_ntfs_replace(tp, dst)
        finally:
            tp.unlink(missing_ok=True)
        self._set_pref("last_clip_save_dir", str(dst.parent))
        return {**meta, "savedPath": str(dst), "fileName": dst.name}

    def capture_screen_region(
        self, target: str = "direct_photo", params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        import backend.core.screen_capture as sc_mod

        tgt = str(target or "direct_photo").strip().lower()
        if tgt not in ("direct_photo", "raw_face", "raw_shirt", "save_png"):
            raise ValueError(f"Destino de captura no soportado: {target}")
        res = sc_mod.capture_screen_png(
            host_window=self._window,
            extra_windows=[self._addon_window] if self._addon_open else None,
        )
        if res is None:
            return {"cancelled": True}
        return self._route_captured_png(res, tgt, params=params, dialog_win=self._window)

    def open_capture_addon(self, default_target: str = "direct_photo", theme: str = "dark") -> dict[str, Any]:
        tgt = str(default_target or "direct_photo").strip().lower()
        if tgt not in ("direct_photo", "raw_face", "raw_shirt", "save_png"):
            tgt = "direct_photo"
        thm = "light" if str(theme).strip().lower() == "light" else "dark"
        if self._addon_window is None:
            return {"addonOpen": False, "target": tgt}
        if hasattr(self._addon_window, "evaluate_js"):
            try:
                self._addon_window.evaluate_js(
                    f"window.__df11SetAddonState && window.__df11SetAddonState({json.dumps(tgt)}, {json.dumps(thm)})"
                )
            except Exception:
                pass
        if self._window is not None and hasattr(self._window, "hide"):
            try:
                self._window.hide()
            except Exception:
                pass
        if hasattr(self._addon_window, "show"):
            self._addon_window.show()
        self._addon_open = True
        return {"addonOpen": True, "target": tgt}

    def restore_from_capture_addon(self) -> dict[str, Any]:
        self._addon_open = False
        if self._addon_window is not None and hasattr(self._addon_window, "hide"):
            try:
                self._addon_window.hide()
            except Exception:
                pass
        if self._window is not None:
            try:
                if hasattr(self._window, "show"):
                    self._window.show()
                if hasattr(self._window, "restore"):
                    self._window.restore()
            except Exception:
                pass
        return {"addonOpen": False}

    def capture_from_addon(self, target: str = "direct_photo", keep_pinned: bool = False) -> dict[str, Any]:
        import backend.core.screen_capture as sc_mod

        tgt = str(target or "direct_photo").strip().lower()
        if tgt not in ("direct_photo", "raw_face", "raw_shirt", "save_png"):
            raise ValueError(f"Destino de captura no soportado: {target}")

        if self._window is not None and hasattr(self._window, "hide"):
            try:
                self._window.hide()
            except Exception:
                pass
        if self._addon_window is not None and hasattr(self._addon_window, "hide"):
            try:
                self._addon_window.hide()
            except Exception:
                pass

        res = sc_mod.capture_screen_png(
            host_window=self._addon_window,
            extra_windows=[self._window],
            restore_after=False,
        )
        if res is None:
            if self._addon_window is not None and hasattr(self._addon_window, "show"):
                self._addon_window.show()
            return {"cancelled": True}

        if tgt == "save_png":
            if self._addon_window is not None and hasattr(self._addon_window, "show"):
                self._addon_window.show()
            out = self._route_captured_png(res, tgt, dialog_win=self._addon_window or self._window)
            if not out.get("cancelled"):
                self._pending_addon_capture = out
                if self._window is not None and hasattr(self._window, "evaluate_js"):
                    try:
                        self._window.evaluate_js("window.dispatchEvent(new CustomEvent('df11:addon-capture'))")
                    except Exception:
                        pass
            return out

        out = self._route_captured_png(res, tgt)
        self._pending_addon_capture = out
        if self._window is not None and hasattr(self._window, "evaluate_js"):
            try:
                self._window.evaluate_js("window.dispatchEvent(new CustomEvent('df11:addon-capture'))")
            except Exception:
                pass

        if bool(keep_pinned):
            if self._addon_window is not None and hasattr(self._addon_window, "show"):
                self._addon_window.show()
            self._addon_open = True
        else:
            self.restore_from_capture_addon()
        return out

    def consume_addon_capture(self) -> dict[str, Any] | None:
        payload = self._pending_addon_capture
        self._pending_addon_capture = None
        return payload

    def toggle_capture_hotkey(self, enabled: bool) -> dict[str, bool]:
        import backend.core.screen_capture as sc_mod

        if not enabled:
            if self._hotkey_mgr is not None:
                self._hotkey_mgr.stop()
                self._hotkey_mgr = None
            return {"hotkeyEnabled": False}
        if self._hotkey_mgr is None:
            def _fire() -> None:
                if self._addon_open and self._addon_window is not None:
                    try:
                        self._addon_window.evaluate_js(
                            "window.__df11TriggerAddonCapture && window.__df11TriggerAddonCapture()"
                        )
                        return
                    except Exception:
                        pass
                if self._window is not None:
                    try:
                        self._window.evaluate_js("window.dispatchEvent(new CustomEvent('df11:hotkey-capture'))")
                    except Exception:
                        pass

            self._hotkey_mgr = sc_mod.GlobalCaptureHotkey(_fire)
        ok = self._hotkey_mgr.start()
        return {"hotkeyEnabled": bool(ok)}

    def pick_raw_face_source(self) -> dict[str, Any] | None:
        chosen = self._pick_image_file("last_image_dir")
        if chosen is None:
            return None
        out = self._mod().stage_raw_face(_read_guarded_file(chosen), file_name=chosen.name)
        self._sync_legacy_raw(self._mod()._crop_raw_img, self._mod()._crop_is_precut)
        return {**out, "directory": str(chosen.parent)}

    def load_raw_face_source(self, data_url: str, file_name: str = "") -> dict[str, Any]:
        out = self._mod().stage_raw_face(_decode_b64(data_url), file_name=file_name)
        self._sync_legacy_raw(self._mod()._crop_raw_img, self._mod()._crop_is_precut)
        return out

    def pick_direct_photo_source(self, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
        chosen = self._pick_image_file("last_image_dir")
        if chosen is None:
            return None
        out = self._mod().load_direct_photo(
            _read_guarded_file(chosen),
            file_name=chosen.name,
            extra_params=params,
            custom_bg=self._custom_bg_img,
        )
        return {**out, "directory": str(chosen.parent)}

    def load_direct_photo_source(
        self, data_url: str, file_name: str = "", params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        return self._mod().load_direct_photo(
            _decode_b64(data_url),
            file_name=file_name,
            extra_params=params,
            custom_bg=self._custom_bg_img,
        )

    def cutout_direct_photo_for_pure(
        self, direct_photo_id: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        return self._mod().cutout_direct_photo_for_pure(
            direct_photo_id=str(direct_photo_id or ""),
            extra_params=params,
            custom_bg=self._custom_bg_img,
        )

    def extract_face_from_crop(self, opts: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._mod().extract_staged_face(opts or {}, custom_bg=self._custom_bg_img)

    def list_saved_faces(self) -> list[dict[str, str]]:
        return self._mod().list_faces()

    def load_saved_face(self, face_id: str, template_id: str = "", params: dict[str, Any] | None = None) -> dict[str, Any]:
        from backend.core.image_guard import load_guarded_image

        out = self._mod().load_face_from_library(face_id, template_id=template_id, extra_params=params, custom_bg=self._custom_bg_img)
        src_path = out.get("sourcePath")
        if src_path and Path(src_path).is_file():
            g = load_guarded_image(Path(src_path))
            self._sync_legacy_raw(g.image, g.is_pre_cutout)
        return out

    def save_extracted_face(self, head_asset_id: str, name: str) -> dict[str, Any]:
        return self._mod().save_face_to_library(head_asset_id, name)

    def list_shirt_templates(self) -> list[dict[str, Any]]:
        return self._mod().list_templates()

    def pick_raw_shirt_source(self) -> dict[str, Any] | None:
        chosen = self._pick_image_file("last_shirt_dir")
        if chosen is None:
            return None
        out = self._mod().stage_raw_shirt(_read_guarded_file(chosen), file_name=chosen.name)
        return {**out, "directory": str(chosen.parent)}

    def load_raw_shirt_source(self, data_url: str, file_name: str = "") -> dict[str, Any]:
        return self._mod().stage_raw_shirt(_decode_b64(data_url), file_name=file_name)

    def preview_shirt_extraction(self, opts: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._mod().preview_shirt(opts or {})

    def save_shirt_template(self, opts: dict[str, Any]) -> dict[str, Any]:
        return self._mod().save_staged_shirt(opts)

    def update_shirt_template_meta(
        self,
        template_id: str | dict[str, Any],
        display_name: str = "",
        club_id: str = "",
        club_name: str = "",
        season: str = "",
        is_active_for_club: bool = True,
        category: str | None = None,
    ) -> dict[str, Any]:
        if isinstance(template_id, dict):
            d = template_id
            cat_val = str(d["category"]) if d.get("category") is not None else None
            return self._mod().update_template_meta(
                template_id=str(d.get("templateId", "")),
                display_name=str(d.get("displayName", "")),
                club_id=str(d.get("clubId", "")),
                club_name=str(d.get("clubName", "")),
                season=str(d.get("season", "")),
                is_active_for_club=bool(d.get("isActiveForClub", True)),
                category=cat_val,
            )
        return self._mod().update_template_meta(
            template_id=str(template_id),
            display_name=display_name,
            club_id=club_id,
            club_name=club_name,
            season=season,
            is_active_for_club=bool(is_active_for_club),
            category=category,
        )

    def set_active_club_shirt_template(self, template_id: str) -> dict[str, Any]:
        return self._mod().activate_club_template(str(template_id))

    def delete_shirt_template(self, template_id: str) -> dict[str, Any]:
        return self._mod().delete_template(str(template_id))

    def upsert_custom_club(self, club_id: str, club_name: str) -> dict[str, Any]:
        from backend.services.kits import upsert_custom_club_entry

        clubs = upsert_custom_club_entry(club_id, club_name, db_path=self._db_path)
        return {"clubs": clubs, "templates": self._mod().list_templates()}

    def import_clubs_from_fm_graphics(self) -> dict[str, Any] | None:
        import webview
        from backend.services.kits import index_fm_graphics_packs, load_merged_clubs

        if not self._window:
            return None
        init_dir = self._resolve_dialog_dir("last_fm_graphics_dir", self._export_dir.parent)
        res = self._window.create_file_dialog(webview.FOLDER_DIALOG, directory=init_dir)
        if not res:
            return None
        chosen = Path(res[0]).resolve()
        if not chosen.is_dir():
            return None
        self._set_pref("last_fm_graphics_dir", str(chosen))
        count = index_fm_graphics_packs(chosen, db_path=self._db_path)
        return {"path": str(chosen), "importedCount": count, "clubs": load_merged_clubs(self._db_path)}

    def pick_facepack_card(
        self, remix_mode: str = "swap_shirt", active_template_id: str = "", params: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        chosen = self._pick_image_file(
            "last_facepack_dir",
            fallback_dir=self._facepack_dir or self._export_dir,
            sync_last_image=False,
        )
        if chosen is None:
            return None
        parent_dir = chosen.parent.resolve()
        if not _paths_overlap(parent_dir, self._vault_dir) and (
            self._facepack_pure_dir is None or not _paths_overlap(parent_dir, self._facepack_pure_dir)
        ):
            self._facepack_dir = parent_dir
            self._approved_dirs.add(parent_dir)
            self._set_pref("last_facepack_dir", str(parent_dir))
        out = self._mod().remix_facepack_card(
            _read_guarded_file(chosen),
            file_name=chosen.name,
            remix_mode=remix_mode,
            active_template_id=active_template_id,
            extra_params=params,
            custom_bg=self._custom_bg_img,
        )
        return {**out, "facepackDir": str(self._facepack_dir) if self._facepack_dir else ""}

    def load_facepack_card(
        self,
        data_url: str,
        file_name: str = "",
        remix_mode: str = "swap_shirt",
        active_template_id: str = "",
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        out = self._mod().remix_facepack_card(
            _decode_b64(data_url),
            file_name=file_name,
            remix_mode=remix_mode,
            active_template_id=active_template_id,
            extra_params=params,
            custom_bg=self._custom_bg_img,
        )
        return {**out, "facepackDir": str(self._facepack_dir) if self._facepack_dir else ""}

    def switch_facepack_remix_mode(
        self, remix_mode: str, active_template_id: str = "", params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        out = self._mod().switch_facepack_remix_mode(
            remix_mode=remix_mode,
            active_template_id=active_template_id,
            extra_params=params,
            custom_bg=self._custom_bg_img,
        )
        return {**out, "facepackDir": str(self._facepack_dir) if self._facepack_dir else ""}

    def save_adhoc_shirt_template(self, opts: dict[str, Any]) -> dict[str, Any]:
        return self._mod().save_adhoc_shirt_to_templates(opts)

    def auto_fit_head_to_template(self, head_asset_id: str, template_id: str) -> dict[str, float]:
        return self._mod().compute_auto_fit(head_asset_id, template_id)

    def render_modular_preview(self, params: dict[str, Any]) -> dict[str, str]:
        return {"previewDataUrl": _to_data_url(self._mod().compose_step_card(params, custom_bg=self._custom_bg_img))}

    def export_modular_card(self, params: dict[str, Any]) -> dict[str, Any]:
        from backend.core.compositor import export_df11_bytes
        from backend.services.kits import save_kit_override

        step1_mode = str(params.get("step1Mode", "modular")).strip().lower()
        wear_mode = str(params.get("wearMode", "template"))
        fallback_label = str(params.get("fileLabel", "")).strip()
        if step1_mode == "direct_photo":
            direct_id = str(params.get("directPhotoId", "")).strip()
            direct_entry = self._mod().get_direct_photo(direct_id) if direct_id else None
            if direct_entry is None:
                raise ValueError("La foto directa activa ya no está en memoria; vuelve a cargarla antes de exportar.")
            if not fallback_label:
                fallback_label = str(direct_entry[2] or "").strip()
        else:
            head_id = str(params.get("headAssetId", "")).strip()
            tpl_id = str(params.get("templateId", "")).strip()
            if wear_mode == "template" and tpl_id and not self._mod().has_shirt_reference(tpl_id):
                raise ValueError("La camiseta seleccionada ya no está disponible; vuelve a elegir una plantilla antes de exportar.")
            if head_id:
                if self._mod().get_head_asset(head_id) is None:
                    raise ValueError("La cara activa ya no está en memoria; vuelve a cargarla antes de exportar.")
            else:
                if wear_mode != "template" or not tpl_id:
                    raise ValueError("Añade una cara o selecciona una plantilla válida antes de exportar la ficha DF11.")

        export_target = str(params.get("exportTarget", "creations")).strip().lower()
        raw_var = str(params.get("exportVariant") or "classic").strip().lower()
        export_variant = raw_var if raw_var in ("classic", "pure", "dual") else "classic"
        fmt = "jpg" if str(params.get("fmt", "png")).lower() in ("jpg", "jpeg") else "png"
        if export_target == "facepack":
            fmt = "png"
        elif export_variant in ("pure", "dual") and fmt != "png":
            raise ValueError("El formato oficial DF11 Pure exige exportación en PNG transparente (32-bit RGBA).")

        classic_dir, pure_dir = self._resolve_export_dirs(params, export_target, export_variant)
        check_targets: list[tuple[Path, str]] = []
        if classic_dir is not None:
            check_targets.append((classic_dir, fmt))
        if pure_dir is not None:
            check_targets.append((pure_dir, "png"))
        file_stem, fm_uid = self._resolve_export_stem_and_uid(
            str(params.get("uid", "")),
            export_target,
            check_targets,
            fallback_label,
        )
        if step1_mode != "direct_photo" and params.get("customKitDirty") and wear_mode in ("club", "staff_polo", "staff_suit"):
            kit = self._resolve_studio_kit(str(params.get("clubId", "1736")), params)
            save_kit_override(kit.club_id, kit.primary, kit.secondary, pattern=kit.pattern, db_path=self._db_path)

        if export_variant == "dual":
            c_im, p_im = self._mod().compose_step_dual_cards(params, custom_bg=self._custom_bg_img)
            assert classic_dir is not None and pure_dir is not None
            c_target = (classic_dir, fmt, export_df11_bytes(c_im, fmt=fmt))  # type: ignore[arg-type]
            p_target = (pure_dir, "png", export_df11_bytes(p_im, fmt="png"))
        elif export_variant == "pure":
            p_im = self._mod().compose_step_card(params, custom_bg=self._custom_bg_img, variant="pure")
            assert pure_dir is not None
            c_target = None
            p_target = (pure_dir, "png", export_df11_bytes(p_im, fmt="png"))
        else:
            c_im = self._mod().compose_step_card(params, custom_bg=self._custom_bg_img, variant="classic")
            assert classic_dir is not None
            c_target = (classic_dir, fmt, export_df11_bytes(c_im, fmt=fmt))  # type: ignore[arg-type]
            p_target = None

        return self._commit_card_exports_atomic(
            file_stem=file_stem,
            fm_uid=fm_uid,
            update_xml=bool(params.get("updateConfigXml", True)),
            export_variant=export_variant,
            classic_target=c_target,
            pure_target=p_target,
        )

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
