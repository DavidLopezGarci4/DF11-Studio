"""Stateful modular session manager for Face Extractor, Shirt Extractor, and Step-by-Step Layer Composer."""

from __future__ import annotations

import base64
from collections import OrderedDict
import io
import math
from pathlib import Path
import threading
from typing import Any

import numpy as np
from PIL import Image

from backend.core.compositor import (
    DF11_HEIGHT,
    DF11_WIDTH,
    SingleCardVariant,
    has_df11_outer_ring,
    is_df11_pure_size,
    render_df11_card,
    render_df11_pure_card,
    unfeather_pure_perimeter_rgba,
    unmix_df11_classic_bevel_rgba,
)
from backend.core.dsp import (
    FitMode,
    apply_oklab_harmonize_params,
    clamp_direct_pan,
    clean_pure_contour_zero_ai,
    compute_effective_scale,
    compute_oklab_harmonize_params,
    enhance_df11_pure_optics,
    resample_linear_subpixel_rgba,
)
from backend.core.fm_config import VALID_FM_UID_RE
from backend.core.image_guard import load_guarded_image
from backend.services.head_neck import (
    DEFAULT_DF11_COLLAR,
    CropViewport,
    HeadFitParams,
    HeadNeckAsset,
    _harmonize_melanin_safe,
    compose_modular_df11,
    compose_modular_subject_rgba,
    extract_clean_head_and_neck,
    fit_head_to_shirt_template,
    list_face_library_files,
    prepare_facepack_card_for_head_extraction,
    save_clean_face_to_library,
    suggest_safe_crop_viewport,
    viewport_to_head_fit,
)
from backend.services.kits import KitSpec, dress_or_frame_portrait, load_merged_clubs, resolve_club_kit
from backend.services.templates import (
    CollarProfile,
    IMAGE_EXTS,
    ShirtTemplate,
    _has_df11_outer_ring,
    delete_shirt_template,
    extract_collar_profile,
    normalize_template_category,
    rename_shirt_template,
    sanitize_shirt_template_rgba,
    save_new_shirt_template,
    set_active_club_shirt_template,
    sync_tshirt_templates_dir,
)

MAX_CACHED_HEADS = 48
MAX_CACHED_SHIRTS = 48


def _finite_float(val: Any, default: float, lo: float, hi: float) -> float:
    try:
        f = float(val)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(f):
        return default
    return float(np.clip(f, lo, hi))


def _infer_raw_ext(raw_bytes: bytes, file_name: str = "") -> str:
    ext = Path(file_name).suffix.lower() if file_name else ""
    if ext in IMAGE_EXTS:
        return ext
    if raw_bytes.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if raw_bytes[:4] == b"RIFF" and raw_bytes[8:12] == b"WEBP":
        return ".webp"
    if len(raw_bytes) >= 12 and raw_bytes[4:12] in (b"ftypavif", b"ftypavis"):
        return ".avif"
    return ".png"


def _png_data_url(img: Image.Image, compress_level: int = 4) -> str:
    buf = io.BytesIO()
    img.save(buf, format="PNG", compress_level=compress_level)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def _thumb_data_url(img: Image.Image, max_side: int = 96) -> str:
    im = img.convert("RGBA").copy()
    im.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    return _png_data_url(im, compress_level=4)


class ModularWorkflowSession:
    """Bounded-memory thread-safe session backing Herramienta Caras, Herramienta Camisetas, and Montaje Paso a Paso."""

    def __init__(
        self,
        templates_dir: Path,
        raw_archive_dir: Path,
        extracted_faces_dir: Path,
        sample_faces_dir: Path,
        db_path: Path,
    ) -> None:
        self.templates_dir = templates_dir.resolve()
        self.raw_archive_dir = raw_archive_dir.resolve()
        self.extracted_faces_dir = extracted_faces_dir.resolve()
        self.sample_faces_dir = sample_faces_dir.resolve()
        self.db_path = db_path

        self._lock = threading.RLock()
        self._seq = 0
        self._head_assets: OrderedDict[str, HeadNeckAsset] = OrderedDict()
        self._disk_face_cache: OrderedDict[tuple[str, int, int], str] = OrderedDict()
        self._shirt_png_cache: OrderedDict[tuple[str, int, int], Image.Image] = OrderedDict()
        self._thumb_cache: OrderedDict[tuple[str, int, int], str] = OrderedDict()

        # Staged raw face for pre-extraction wheel-crop
        self._crop_raw_img: Image.Image | None = None
        self._crop_raw_bytes: bytes | None = None
        self._crop_file_name: str = ""
        self._crop_is_precut: bool = False
        self._crop_name: str = ""
        self._crop_suggested_vp: CropViewport = CropViewport()

        # Staged raw shirt for interactive template extraction (with LRU for multi-upload Undo/Redo)
        self._shirt_seq = 0
        self._shirt_sources: OrderedDict[str, tuple[Image.Image, bytes, str]] = OrderedDict()
        self._shirt_active_id: str = ""
        self._shirt_raw_img: Image.Image | None = None
        self._shirt_raw_bytes: bytes | None = None
        self._shirt_raw_ext: str = ".png"
        self._shirt_preview_img: Image.Image | None = None
        self._shirt_preview_params: tuple[str, bool, float, float, float, float, float] | None = None

        # Ad-hoc shirts isolated from assembled FM facepack cards & last remixed card for instant mode toggle
        self._adhoc_seq = 0
        self._adhoc_shirts: OrderedDict[str, tuple[Image.Image, CollarProfile, bytes | None, str, str]] = OrderedDict()
        self._last_facepack_card: tuple[bytes, str] | None = None

        # Direct Photo + DF11 Frame sources (100% offline, 0% AI, LRU-bounded)
        self._direct_seq = 0
        self._direct_photos: OrderedDict[str, tuple[Image.Image, bool, str, tuple[float, float, float]]] = OrderedDict()
        self._pure_zero_ai_cache: OrderedDict[tuple[Any, ...], Image.Image] = OrderedDict()

    @staticmethod
    def _extract_direct_df11_inner_crop(card_rgba: Image.Image) -> tuple[Image.Image, bool]:
        """Extract 224x278 inner window from a 260x310 DF11 Classic card with exact 0% AI bevel unmixing."""
        return unmix_df11_classic_bevel_rgba(card_rgba)

    def _put_direct_photo(
        self,
        rgba: Image.Image,
        is_precut: bool,
        label: str,
        harm_params: tuple[float, float, float] = (0.0, 0.0, 0.0),
    ) -> str:
        with self._lock:
            self._direct_seq += 1
            did = f"direct-{self._direct_seq}"
            self._direct_photos[did] = (rgba, is_precut, label, harm_params)
            while len(self._direct_photos) > MAX_CACHED_HEADS:
                self._direct_photos.popitem(last=False)
            return did

    def has_direct_photo(self, direct_photo_id: str) -> bool:
        did = str(direct_photo_id or "").strip()
        if not did:
            return False
        with self._lock:
            return did in self._direct_photos

    def get_direct_photo(
        self, direct_photo_id: str
    ) -> tuple[Image.Image, bool, str, tuple[float, float, float]] | None:
        did = str(direct_photo_id or "").strip()
        if not did:
            return None
        with self._lock:
            entry = self._direct_photos.get(did)
            if entry is not None:
                self._direct_photos.move_to_end(did)
            return entry

    def load_direct_photo(
        self,
        raw_bytes: bytes,
        file_name: str = "",
        extra_params: dict[str, Any] | None = None,
        custom_bg: Image.Image | None = None,
    ) -> dict[str, Any]:
        """Load any image directly into a 260x310 DF11 frame with 100% offline, 0% AI optical framing."""
        g = load_guarded_image(raw_bytes)
        if has_df11_outer_ring(g.image):
            prep_im, prep_precut = self._extract_direct_df11_inner_crop(g.image)
        elif is_df11_pure_size(g.image.size):
            p_alpha = np.asarray(g.image.convert("RGBA"), dtype=np.uint8)[:, :, 3]
            is_pure_cut = bool(
                g.is_pre_cutout or (int(p_alpha[:55, :20].max()) == 0 and int(p_alpha[:55, -20:].max()) == 0)
            )
            if is_pure_cut:
                unfeathered = unfeather_pure_perimeter_rgba(g.image)
                win_arr = np.zeros((278, 224, 4), dtype=np.uint8)
                uf_arr = np.asarray(unfeathered, dtype=np.uint8)
                win_arr[1:277, 2:222] = uf_arr
                l_slv = uf_arr[:, 0, 3] >= 245
                if np.any(l_slv):
                    win_arr[1:277, 1][l_slv] = uf_arr[:, 0][l_slv]
                r_slv = uf_arr[:, -1, 3] >= 245
                if np.any(r_slv):
                    win_arr[1:277, 222][r_slv] = uf_arr[:, -1][r_slv]
                    win_arr[1:277, 223][r_slv] = uf_arr[:, -1][r_slv]
                prep_im, prep_precut = Image.fromarray(win_arr, mode="RGBA"), True
            else:
                prep_im, prep_precut = g.image, False
        else:
            prep_im, prep_precut = g.image, g.is_pre_cutout
        harm_params = compute_oklab_harmonize_params(prep_im)
        stem = Path(file_name).stem.strip() if file_name else ""
        detected_uid = stem if VALID_FM_UID_RE.fullmatch(stem) else ""
        label = stem or "Foto_Directa"
        did = self._put_direct_photo(prep_im, prep_precut, label, harm_params)

        base_p = dict(extra_params or {})
        has_explicit_bg_replace = "directBgReplace" in base_p
        eff_bg_replace = False if prep_precut else bool(base_p.get("directBgReplace", False))
        eff_bg_mode = str(base_p.get("bgMode", "white_df11") or "white_df11")
        if eff_bg_replace and not prep_precut and eff_bg_mode == "transparent":
            eff_bg_mode = "white_df11"
        clamp_pan = bool(base_p.get("clampPan", not prep_precut))
        comp_params = {
            **base_p,
            "step1Mode": "direct_photo",
            "directPhotoId": did,
            "directBgReplace": eff_bg_replace,
            "bgMode": eff_bg_mode,
            "scale": 1.0,
            "offsetX": 0.0,
            "offsetY": 0.0,
            "clampPan": clamp_pan,
        }
        w, h = prep_im.size
        out_res: dict[str, Any] = {
            "directPhotoId": did,
            "fileName": file_name,
            "label": label,
            "detectedUid": detected_uid,
            "width": w,
            "height": h,
            "isPreCutout": prep_precut,
            "clampPan": clamp_pan,
            "autoFit": {"scale": 1.0, "offsetX": 0.0, "offsetY": 0.0, "neckFill": 1.0},
            "previewDataUrl": _png_data_url(self.compose_step_card(comp_params, custom_bg=custom_bg)),
        }
        if has_explicit_bg_replace:
            out_res["directBgReplace"] = eff_bg_replace
            out_res["bgMode"] = eff_bg_mode
        return out_res

    def cutout_direct_photo_for_pure(
        self,
        direct_photo_id: str,
        extra_params: dict[str, Any] | None = None,
        custom_bg: Image.Image | None = None,
    ) -> dict[str, Any]:
        """100% Zero-AI contour preview helper (preserves lossless Direct Photo source with zero ONNX calls)."""
        entry = self.get_direct_photo(direct_photo_id)
        if entry is None:
            raise ValueError("La foto directa activa ya no está en memoria; vuelve a cargarla.")
        raw_im, is_precut, label, _harm = entry
        w, h = raw_im.size
        prev_scale = _finite_float((extra_params or {}).get("scale", 1.0), 1.0, 0.08, 8.0)
        prev_ox = _finite_float((extra_params or {}).get("offsetX", 0.0), 0.0, -2000.0, 2000.0)
        prev_oy = _finite_float((extra_params or {}).get("offsetY", 0.0), 0.0, -2000.0, 2000.0)
        clamp_pan = bool((extra_params or {}).get("clampPan", not is_precut))
        comp_params = {
            **(extra_params or {}),
            "step1Mode": "direct_photo",
            "directPhotoId": direct_photo_id,
            "scale": prev_scale,
            "offsetX": prev_ox,
            "offsetY": prev_oy,
            "clampPan": clamp_pan,
            "previewVariant": "pure",
        }
        return {
            "directPhotoId": direct_photo_id,
            "label": label,
            "width": w,
            "height": h,
            "isPreCutout": is_precut,
            "clampPan": clamp_pan,
            "autoFit": {"scale": prev_scale, "offsetX": prev_ox, "offsetY": prev_oy, "neckFill": 1.0},
            "previewDataUrl": _png_data_url(self.compose_step_card(comp_params, custom_bg=custom_bg, variant="pure")),
        }

    def load_facepack_card_for_pure(
        self,
        raw_bytes: bytes,
        file_name: str = "",
        extra_params: dict[str, Any] | None = None,
        custom_bg: Image.Image | None = None,
    ) -> dict[str, Any]:
        """Load an existing FM Facepack card (260x310 Classic or 220x276 Pure) for 0% AI Pure/Dual conversion."""
        merged_params = {**(extra_params or {}), "previewVariant": "pure"}
        return self.load_direct_photo(
            raw_bytes=raw_bytes,
            file_name=file_name,
            extra_params=merged_params,
            custom_bg=custom_bg,
        )

    def _put_head_asset(self, asset: HeadNeckAsset) -> str:
        with self._lock:
            self._seq += 1
            aid = f"head-{self._seq}"
            self._head_assets[aid] = asset
            while len(self._head_assets) > MAX_CACHED_HEADS:
                self._head_assets.popitem(last=False)
            return aid

    def get_head_asset(self, head_asset_id: str) -> HeadNeckAsset | None:
        with self._lock:
            asset = self._head_assets.get(head_asset_id)
            if asset is not None:
                self._head_assets.move_to_end(head_asset_id)
            return asset

    def _cached_thumb(self, path: Path) -> str:
        st = path.stat()
        key = (str(path), st.st_mtime_ns, st.st_size)
        with self._lock:
            if key in self._thumb_cache:
                self._thumb_cache.move_to_end(key)
                return self._thumb_cache[key]
        guarded = load_guarded_image(path)
        url = _thumb_data_url(guarded.image)
        with self._lock:
            self._thumb_cache[key] = url
            while len(self._thumb_cache) > 64:
                self._thumb_cache.popitem(last=False)
        return url

    def _load_template_image(self, tpl: ShirtTemplate) -> Image.Image:
        st = tpl.file_path.stat()
        key = (str(tpl.file_path), st.st_mtime_ns, st.st_size)
        with self._lock:
            if key in self._shirt_png_cache:
                self._shirt_png_cache.move_to_end(key)
                return self._shirt_png_cache[key]
        im = load_guarded_image(tpl.file_path).image
        with self._lock:
            self._shirt_png_cache[key] = im
            while len(self._shirt_png_cache) > 32:
                self._shirt_png_cache.popitem(last=False)
        return im

    # --- Tool 1: Face Extractor & Pre-Crop ---

    def stage_raw_face(self, raw_bytes: bytes, file_name: str = "") -> dict[str, Any]:
        g = load_guarded_image(raw_bytes)
        prep_img, prep_precut = prepare_facepack_card_for_head_extraction(g.image, g.is_pre_cutout)
        vp = suggest_safe_crop_viewport(prep_img)
        with self._lock:
            self._crop_raw_img = prep_img
            self._crop_raw_bytes = raw_bytes
            self._crop_file_name = file_name
            self._crop_is_precut = prep_precut
            self._crop_name = Path(file_name).stem if file_name else "Retrato"
            self._crop_suggested_vp = vp

        alpha = np.asarray(prep_img.convert("RGBA"), dtype=np.uint8)[:, :, 3]
        ys = np.where(alpha > 24)[0]
        crown_src_y = int(ys.min()) if len(ys) else 0
        w, h = prep_img.size
        return {
            "rawDataUrl": _png_data_url(prep_img),
            "width": w,
            "height": h,
            "isPreCutout": prep_precut,
            "crownSrcY": crown_src_y,
            "suggestedViewport": {"zoom": vp.zoom, "panX": vp.pan_x, "panY": vp.pan_y},
            "fileName": file_name,
        }

    def promote_staged_crop_to_direct_photo(
        self,
        extra_params: dict[str, Any] | None = None,
        custom_bg: Image.Image | None = None,
    ) -> dict[str, Any]:
        """Rescue a staged crop into Direct Photo + DF11 Frame with 0% AI and lossless raw-bytes fidelity."""
        with self._lock:
            raw_bytes = self._crop_raw_bytes
            raw_img = self._crop_raw_img
            fname = self._crop_file_name or (f"{self._crop_name}.png" if self._crop_name else "")
        if raw_bytes is None and raw_img is None:
            raise ValueError("No hay ningún recorte en espera para pasar a Foto Directa.")
        if raw_bytes is None:
            buf = io.BytesIO()
            assert raw_img is not None
            raw_img.save(buf, format="PNG")
            raw_bytes = buf.getvalue()
        return self.load_direct_photo(
            raw_bytes=raw_bytes,
            file_name=fname,
            extra_params=extra_params,
            custom_bg=custom_bg,
        )

    def extract_staged_face(self, opts: dict[str, Any], custom_bg: Image.Image | None = None) -> dict[str, Any]:
        with self._lock:
            raw_img = self._crop_raw_img
            is_precut = self._crop_is_precut
            crop_name = self._crop_name
            sug_vp = self._crop_suggested_vp
        if raw_img is None:
            raise ValueError("Selecciona o sube primero una imagen para recortar la cara y cuello.")
        vp = CropViewport(
            zoom=float(opts.get("zoom", sug_vp.zoom)),
            pan_x=float(opts.get("panX", sug_vp.pan_x)),
            pan_y=float(opts.get("panY", sug_vp.pan_y)),
        )
        remove_bg = bool(opts.get("removeBg", True))
        asset = extract_clean_head_and_neck(
            raw_img,
            is_pre_cutout=is_precut,
            crop_viewport=vp,
            remove_bg=remove_bg,
        )
        aid = self._put_head_asset(asset)
        tpl_id = str(opts.get("templateId", "")).strip()
        user_adjusted_vp = (
            abs(vp.zoom - sug_vp.zoom) > 1e-3
            or abs(vp.pan_x - sug_vp.pan_x) > 0.5
            or abs(vp.pan_y - sug_vp.pan_y) > 0.5
        )
        base_fit = self.compute_auto_fit(aid, tpl_id)
        if user_adjusted_vp and not tpl_id:
            vfit = viewport_to_head_fit(asset, vp)
            fit_dict = {"scale": vfit.scale, "offsetX": vfit.offset_x, "offsetY": vfit.offset_y, "neckFill": 1.0}
        elif user_adjusted_vp:
            z_ratio = vp.zoom / max(sug_vp.zoom, 1e-4)
            fit_dict = {
                "scale": round(float(np.clip(base_fit["scale"] * z_ratio, 0.10, 2.4)), 4),
                "offsetX": round(base_fit["offsetX"] + (vp.pan_x - sug_vp.pan_x), 1),
                "offsetY": round(base_fit["offsetY"] + (vp.pan_y - sug_vp.pan_y), 1),
                "neckFill": base_fit["neckFill"],
            }
        else:
            fit_dict = base_fit

        comp_params = {
            **opts,
            "headAssetId": aid,
            "scale": fit_dict["scale"],
            "offsetX": fit_dict["offsetX"],
            "offsetY": fit_dict["offsetY"],
            "neckFill": fit_dict["neckFill"],
        }
        return {
            "headAssetId": aid,
            "suggestedName": crop_name or "Cara_Extraida",
            "headPreviewDataUrl": _png_data_url(asset.rgba),
            "autoFit": fit_dict,
            "previewDataUrl": _png_data_url(self.compose_step_card(comp_params, custom_bg=custom_bg)),
        }

    def list_faces(self) -> list[dict[str, str]]:
        rows = list_face_library_files(self.extracted_faces_dir, self.sample_faces_dir)
        out: list[dict[str, str]] = []
        for fid, name, path, kind in rows:
            try:
                out.append({"faceId": fid, "name": name, "kind": kind, "thumbDataUrl": self._cached_thumb(path)})
            except Exception:
                continue
        return out

    def _resolve_face_path(self, face_id: str) -> tuple[Path, str]:
        if ":" not in face_id:
            raise ValueError("Identificador de cara inválido.")
        prefix, fname = face_id.split(":", 1)
        if not fname or Path(fname).name != fname or ".." in fname:
            raise ValueError("Ruta de cara no permitida.")
        root = self.extracted_faces_dir if prefix == "ext" else self.sample_faces_dir if prefix == "smp" else None
        if root is None:
            raise ValueError("Origen de biblioteca de caras desconocido.")
        cand = (root / fname).resolve()
        cand.relative_to(root.resolve())
        if not cand.is_file():
            raise ValueError(f"Archivo de cara no encontrado: {fname}")
        return cand, cand.stem

    def load_face_from_library(
        self, face_id: str, template_id: str = "", extra_params: dict[str, Any] | None = None, custom_bg: Image.Image | None = None
    ) -> dict[str, Any]:
        path, stem = self._resolve_face_path(face_id)
        st = path.stat()
        ckey = (face_id, st.st_mtime_ns, st.st_size)
        with self._lock:
            aid = self._disk_face_cache.get(ckey)
            if aid is not None:
                self._disk_face_cache.move_to_end(ckey)
        asset = self.get_head_asset(aid) if aid else None
        g = load_guarded_image(path)
        if asset is None:
            vp = suggest_safe_crop_viewport(g.image)
            asset = extract_clean_head_and_neck(g.image, is_pre_cutout=g.is_pre_cutout, crop_viewport=vp, remove_bg=True)
            aid = self._put_head_asset(asset)
            with self._lock:
                self._disk_face_cache[ckey] = aid
                while len(self._disk_face_cache) > MAX_CACHED_HEADS:
                    self._disk_face_cache.popitem(last=False)

        assert aid is not None
        fit_dict = self.compute_auto_fit(aid, template_id)
        comp_params = {
            **(extra_params or {}),
            "headAssetId": aid,
            "templateId": template_id,
            "scale": fit_dict["scale"],
            "offsetX": fit_dict["offsetX"],
            "offsetY": fit_dict["offsetY"],
            "neckFill": fit_dict["neckFill"],
        }
        return {
            "headAssetId": aid,
            "name": stem,
            "isPreCutout": g.is_pre_cutout,
            "sourcePath": str(path),
            "headPreviewDataUrl": _png_data_url(asset.rgba),
            "autoFit": fit_dict,
            "previewDataUrl": _png_data_url(self.compose_step_card(comp_params, custom_bg=custom_bg)),
        }

    def save_face_to_library(self, head_asset_id: str, name: str) -> dict[str, Any]:
        asset = self.get_head_asset(head_asset_id)
        if asset is None:
            raise ValueError("No hay ninguna cara extraída activa para guardar.")
        fid, slug, _ = save_clean_face_to_library(asset.rgba, name, extracted_dir=self.extracted_faces_dir)
        return {"faceId": fid, "name": slug, "faces": self.list_faces()}

    # --- Tool 2: Shirt Template Extractor & Registry ---

    def list_templates(self) -> list[dict[str, Any]]:
        items = sync_tshirt_templates_dir(
            tpl_dir=self.templates_dir,
            raw_archive_dir=self.raw_archive_dir,
            db_path=self.db_path,
        )
        out: list[dict[str, Any]] = []
        for t in items:
            try:
                out.append(
                    {
                        "templateId": t.template_id,
                        "filename": t.filename,
                        "displayName": t.display_name,
                        "clubId": t.club_id,
                        "clubName": t.club_name,
                        "season": t.season,
                        "isActiveForClub": t.is_active_for_club,
                        "category": t.category,
                        "collarWidth": t.collar.collar_width,
                        "apexY": t.collar.apex[1],
                        "thumbDataUrl": self._cached_thumb(t.file_path),
                    }
                )
            except Exception:
                continue
        return out

    def _find_template(self, template_id: str) -> ShirtTemplate | None:
        if not template_id or template_id.startswith("adhoc:"):
            return None
        items = sync_tshirt_templates_dir(
            tpl_dir=self.templates_dir,
            raw_archive_dir=self.raw_archive_dir,
            db_path=self.db_path,
        )
        return next((t for t in items if t.template_id == template_id), None)

    def has_shirt_reference(self, template_id: str) -> bool:
        tid = str(template_id or "").strip()
        if not tid:
            return False
        if tid.startswith("adhoc:"):
            with self._lock:
                return tid in self._adhoc_shirts
        return self._find_template(tid) is not None

    def _resolve_shirt_layer(self, template_id: str) -> tuple[Image.Image | None, CollarProfile | None]:
        tid = str(template_id or "").strip()
        if not tid:
            return None, None
        if tid.startswith("adhoc:"):
            with self._lock:
                entry = self._adhoc_shirts.get(tid)
                if entry is not None:
                    self._adhoc_shirts.move_to_end(tid)
                    return entry[0], entry[1]
            return None, None
        tpl = self._find_template(tid)
        if tpl is None:
            return None, None
        return self._load_template_image(tpl), tpl.collar

    @staticmethod
    def _suggest_headless_shirt_viewport(w: int, h: int) -> dict[str, float]:
        fit_base = min(260.0 / max(w, 1), 310.0 / max(h, 1))
        base_w, base_h = w * fit_base, h * fit_base
        zoom = float(np.clip(min(226.0 / max(base_w, 1.0), 124.0 / max(base_h, 1.0)), 0.35, 2.2))
        nh = max(1, round(h * fit_base * zoom))
        pan_y = round(max(28.0, (294.0 - nh) - (310.0 - nh) * 0.5), 1)
        return {"zoom": round(zoom, 3), "panX": 0.0, "panY": pan_y}

    def stage_raw_shirt(
        self, raw_bytes: bytes, file_name: str = "", auto_torso_frame: bool = False
    ) -> dict[str, Any]:
        g = load_guarded_image(raw_bytes)
        raw_ext = _infer_raw_ext(raw_bytes, file_name)
        with self._lock:
            self._shirt_seq += 1
            sid = f"shirt-src-{self._shirt_seq}"
            self._shirt_sources[sid] = (g.image, raw_bytes, raw_ext)
            while len(self._shirt_sources) > MAX_CACHED_SHIRTS:
                self._shirt_sources.popitem(last=False)
            self._shirt_active_id = sid
            self._shirt_raw_img = g.image
            self._shirt_raw_bytes = raw_bytes
            self._shirt_raw_ext = raw_ext
            self._shirt_preview_img = None
            self._shirt_preview_params = None
        w, h = g.image.size
        stem = Path(file_name).stem if file_name else "Camiseta_Club"
        sug_vp = {"zoom": 1.0, "panX": 0.0, "panY": 0.0}
        if auto_torso_frame and (w, h) != (260, 310) and not is_df11_pure_size((w, h)):
            from backend.services.vision import detect_face_pose

            if detect_face_pose(g.image) is None:
                sug_vp = self._suggest_headless_shirt_viewport(w, h)
        return {
            "shirtSourceId": sid,
            "rawDataUrl": _png_data_url(g.image),
            "width": w,
            "height": h,
            "suggestedName": stem,
            "suggestedViewport": sug_vp,
        }

    def _resolve_shirt_source(self, source_id: str) -> tuple[str, Image.Image | None, bytes | None, str]:
        with self._lock:
            if source_id:
                if source_id not in self._shirt_sources:
                    raise ValueError(
                        "La camiseta original ya no está en memoria; vuelve a subirla antes de extraer o guardar."
                    )
                self._shirt_sources.move_to_end(source_id)
                im, rb, ext = self._shirt_sources[source_id]
                return source_id, im, rb, ext
            return self._shirt_active_id, self._shirt_raw_img, self._shirt_raw_bytes, self._shirt_raw_ext

    @staticmethod
    def _parse_shirt_params(sid: str, opts: dict[str, Any]) -> tuple[str, bool, float, float, float, float, float]:
        return (
            sid,
            bool(opts.get("symmetrizeShoulders", True)),
            round(_finite_float(opts.get("shoulderBoost", 0.0), 0.0, 0.0, 1.0), 4),
            round(_finite_float(opts.get("zoom", 1.0), 1.0, 0.20, 4.0), 4),
            round(_finite_float(opts.get("panX", 0.0), 0.0, -2000.0, 2000.0), 2),
            round(_finite_float(opts.get("panY", 0.0), 0.0, -2000.0, 2000.0), 2),
            round(_finite_float(opts.get("detailCrispness", 0.35), 0.35, 0.0, 1.0), 4),
        )

    @staticmethod
    def _ensure_nonempty_shirt(clean_rgba: Image.Image) -> None:
        opaque_px = int((np.asarray(clean_rgba, dtype=np.uint8)[:, :, 3] > 128).sum())
        if opaque_px < 200:
            raise ValueError(
                "No se detectó ninguna camiseta en la zona inferior del lienzo; ajusta la posición hacia la guía verde antes de extraer."
            )

    def preview_shirt(self, opts: dict[str, Any]) -> dict[str, Any]:
        req_sid = str(opts.get("shirtSourceId") or "").strip()
        sid, raw_img, _, _ = self._resolve_shirt_source(req_sid)
        if raw_img is None:
            raise ValueError("Sube primero una imagen con camiseta para extraer la plantilla.")
        params = self._parse_shirt_params(sid, opts)
        clean = sanitize_shirt_template_rgba(
            raw_img,
            symmetrize_shoulders=params[1],
            shoulder_boost=params[2],
            zoom=params[3],
            pan_x=params[4],
            pan_y=params[5],
            detail_crispness=params[6],
        )
        self._ensure_nonempty_shirt(clean)
        with self._lock:
            self._shirt_preview_img = clean
            self._shirt_preview_params = params
        collar = extract_collar_profile(clean)
        return {
            "cleanShirtDataUrl": _png_data_url(clean),
            "collarWidth": collar.collar_width,
            "apexY": collar.apex[1],
        }

    def save_staged_shirt(self, opts: dict[str, Any]) -> dict[str, Any]:
        req_sid = str(opts.get("shirtSourceId") or "").strip()
        sid, raw_img, raw_bytes, raw_ext = self._resolve_shirt_source(req_sid)
        with self._lock:
            prev_img = self._shirt_preview_img
            prev_params = self._shirt_preview_params
        if prev_img is None and raw_img is None:
            raise ValueError("Extrae primero una camiseta antes de guardarla en tshirt_templates.")
        if raw_img is not None and (
            prev_img is None
            or (prev_params is not None and prev_params[0] != sid)
            or any(
                k in opts
                for k in ("symmetrizeShoulders", "shoulderBoost", "zoom", "panX", "panY", "detailCrispness")
            )
        ):
            req_params = self._parse_shirt_params(sid, opts)
            if prev_params != req_params or prev_img is None:
                prev_img = sanitize_shirt_template_rgba(
                    raw_img,
                    symmetrize_shoulders=req_params[1],
                    shoulder_boost=req_params[2],
                    zoom=req_params[3],
                    pan_x=req_params[4],
                    pan_y=req_params[5],
                    detail_crispness=req_params[6],
                )
                self._ensure_nonempty_shirt(prev_img)
                with self._lock:
                    self._shirt_preview_img = prev_img
                    self._shirt_preview_params = req_params
        assert prev_img is not None
        self._ensure_nonempty_shirt(prev_img)
        tpl = save_new_shirt_template(
            clean_rgba=prev_img,
            raw_bytes=raw_bytes,
            display_name=str(opts.get("displayName", "")),
            club_id=str(opts.get("clubId", "")),
            template_id=str(opts.get("templateId", "")),
            tpl_dir=self.templates_dir,
            raw_archive_dir=self.raw_archive_dir,
            db_path=self.db_path,
            raw_ext=raw_ext,
            club_name=str(opts.get("clubName", "")),
            season=str(opts.get("season", "")),
            is_active_for_club=bool(opts.get("isActiveForClub", True)),
            replace_previous_for_club=bool(opts.get("replacePreviousForClub", False)),
            category=normalize_template_category(str(opts.get("category", "player"))),
        )
        return {
            "savedTemplateId": tpl.template_id,
            "templates": self.list_templates(),
            "clubs": load_merged_clubs(self.db_path),
        }

    def update_template_meta(
        self,
        template_id: str,
        display_name: str,
        club_id: str = "",
        club_name: str = "",
        season: str = "",
        is_active_for_club: bool = True,
        category: str | None = None,
    ) -> dict[str, Any]:
        rename_shirt_template(
            template_id=template_id,
            display_name=display_name,
            club_id=club_id,
            tpl_dir=self.templates_dir,
            db_path=self.db_path,
            club_name=club_name,
            season=season,
            is_active_for_club=is_active_for_club,
            category=category,
        )
        return {"templates": self.list_templates(), "clubs": load_merged_clubs(self.db_path)}

    def activate_club_template(self, template_id: str) -> dict[str, Any]:
        tpl = set_active_club_shirt_template(
            template_id=template_id,
            tpl_dir=self.templates_dir,
            db_path=self.db_path,
        )
        return {"activeTemplateId": tpl.template_id, "templates": self.list_templates()}

    def delete_template(self, template_id: str) -> dict[str, Any]:
        deleted_id = delete_shirt_template(
            template_id=template_id,
            tpl_dir=self.templates_dir,
            db_path=self.db_path,
        )
        with self._lock:
            target_prefix = str((self.templates_dir / f"{deleted_id}.png").resolve()).lower()
            for cache_dict in (self._shirt_png_cache, self._thumb_cache):
                stale_keys = [k for k in cache_dict if k[0].lower() == target_prefix]
                for sk in stale_keys:
                    cache_dict.pop(sk, None)
        return {"deletedTemplateId": deleted_id, "templates": self.list_templates()}

    # --- Tool 3: Step-by-Step Modular Layer Composer & Facepack Card Remix ---

    def remix_facepack_card(
        self,
        raw_bytes: bytes,
        file_name: str = "",
        remix_mode: str = "swap_shirt",
        active_template_id: str = "",
        extra_params: dict[str, Any] | None = None,
        custom_bg: Image.Image | None = None,
    ) -> dict[str, Any]:
        g = load_guarded_image(raw_bytes)
        raw_ext = _infer_raw_ext(raw_bytes, file_name)
        stem = Path(file_name).stem.strip() if file_name else ""
        detected_uid = stem if VALID_FM_UID_RE.fullmatch(stem) else ""
        label = stem or "Ficha_Facepack"
        mode = "swap_face" if str(remix_mode or "").strip() == "swap_face" else "swap_shirt"

        with self._lock:
            self._last_facepack_card = (raw_bytes, file_name)

        base_params = dict(extra_params or {})
        if mode == "swap_face":
            clean_shirt = sanitize_shirt_template_rgba(g.image, symmetrize_shoulders=True, detail_crispness=0.35)
            self._ensure_nonempty_shirt(clean_shirt)
            collar = extract_collar_profile(clean_shirt)
            with self._lock:
                self._adhoc_seq += 1
                adhoc_id = f"adhoc:shirt-{self._adhoc_seq}"
                self._adhoc_shirts[adhoc_id] = (clean_shirt, collar, raw_bytes, raw_ext, f"Camiseta {label}")
                while len(self._adhoc_shirts) > MAX_CACHED_SHIRTS:
                    self._adhoc_shirts.popitem(last=False)

            cur_head_id = str(base_params.get("headAssetId", "")).strip()
            fit_dict = self.compute_auto_fit(cur_head_id, adhoc_id) if cur_head_id else {"scale": 1.0, "offsetX": 0.0, "offsetY": 0.0, "neckFill": 1.0}
            comp_params = {
                **base_params,
                "wearMode": "template",
                "templateId": adhoc_id,
                "scale": fit_dict["scale"],
                "offsetX": fit_dict["offsetX"],
                "offsetY": fit_dict["offsetY"],
                "neckFill": fit_dict["neckFill"],
            }
            return {
                "remixMode": "swap_face",
                "detectedUid": detected_uid,
                "cardLabel": label,
                "adhocShirtId": adhoc_id,
                "adhocShirtLabel": f"Camiseta ficha {label}",
                "adhocShirtThumbDataUrl": _thumb_data_url(clean_shirt),
                "collarWidth": collar.collar_width,
                "apexY": collar.apex[1],
                "autoFit": fit_dict,
                "previewDataUrl": _png_data_url(self.compose_step_card(comp_params, custom_bg=custom_bg)),
            }

        prep_im, prep_precut = prepare_facepack_card_for_head_extraction(g.image, g.is_pre_cutout)
        vp = suggest_safe_crop_viewport(prep_im)
        asset = extract_clean_head_and_neck(prep_im, is_pre_cutout=prep_precut, crop_viewport=vp, remove_bg=True)
        aid = self._put_head_asset(asset)

        target_tid = str(active_template_id or "").strip()
        if not target_tid or target_tid.startswith("adhoc:") or not self.has_shirt_reference(target_tid):
            items = sync_tshirt_templates_dir(tpl_dir=self.templates_dir, raw_archive_dir=self.raw_archive_dir, db_path=self.db_path)
            first_player = next((t for t in items if t.category == "player"), None)
            target_tid = first_player.template_id if first_player else ""

        fit_dict = self.compute_auto_fit(aid, target_tid)
        comp_params = {
            **base_params,
            "headAssetId": aid,
            "wearMode": "template",
            "templateId": target_tid,
            "scale": fit_dict["scale"],
            "offsetX": fit_dict["offsetX"],
            "offsetY": fit_dict["offsetY"],
            "neckFill": fit_dict["neckFill"],
        }
        return {
            "remixMode": "swap_shirt",
            "detectedUid": detected_uid,
            "cardLabel": label,
            "headAssetId": aid,
            "templateId": target_tid,
            "isPreCutout": prep_precut,
            "autoFit": fit_dict,
            "previewDataUrl": _png_data_url(self.compose_step_card(comp_params, custom_bg=custom_bg)),
        }

    def switch_facepack_remix_mode(
        self,
        remix_mode: str,
        active_template_id: str = "",
        extra_params: dict[str, Any] | None = None,
        custom_bg: Image.Image | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            cached = self._last_facepack_card
        if cached is None:
            raise ValueError("Carga primero una ficha del Pack de Faces de Football Manager.")
        raw_bytes, file_name = cached
        return self.remix_facepack_card(
            raw_bytes=raw_bytes,
            file_name=file_name,
            remix_mode=remix_mode,
            active_template_id=active_template_id,
            extra_params=extra_params,
            custom_bg=custom_bg,
        )

    def save_adhoc_shirt_to_templates(self, opts: dict[str, Any]) -> dict[str, Any]:
        adhoc_id = str(opts.get("adhocShirtId") or "").strip()
        with self._lock:
            entry = self._adhoc_shirts.get(adhoc_id)
        if entry is None:
            raise ValueError("La camiseta aislada de la ficha ya no está en memoria.")
        clean_shirt, _collar, raw_bytes, raw_ext, default_label = entry
        tpl = save_new_shirt_template(
            clean_rgba=clean_shirt,
            raw_bytes=raw_bytes,
            display_name=str(opts.get("displayName") or default_label),
            club_id=str(opts.get("clubId", "")),
            template_id=str(opts.get("templateId", "")),
            tpl_dir=self.templates_dir,
            raw_archive_dir=self.raw_archive_dir,
            db_path=self.db_path,
            raw_ext=raw_ext,
            club_name=str(opts.get("clubName", "")),
            season=str(opts.get("season", "")),
            is_active_for_club=bool(opts.get("isActiveForClub", True)),
            category=normalize_template_category(str(opts.get("category", "player"))),
        )
        return {
            "savedTemplateId": tpl.template_id,
            "templates": self.list_templates(),
            "clubs": load_merged_clubs(self.db_path),
        }

    def compute_auto_fit(self, head_asset_id: str, template_id: str = "") -> dict[str, float]:
        asset = self.get_head_asset(head_asset_id)
        if asset is None:
            return {"scale": 1.0, "offsetX": 0.0, "offsetY": 0.0, "neckFill": 1.0}
        _shirt_im, collar = self._resolve_shirt_layer(template_id)
        use_collar = collar if collar is not None else DEFAULT_DF11_COLLAR
        fit = fit_head_to_shirt_template(asset, use_collar)
        return {"scale": fit.scale, "offsetX": fit.offset_x, "offsetY": fit.offset_y, "neckFill": fit.neck_fill}

    def _get_cached_pure_zero_ai(
        self,
        direct_id: str,
        placed_unenhanced: Image.Image,
        is_precut: bool,
        scale: float,
        eff_px: float,
        eff_py: float,
        clamp_pan: bool,
        harmonize: bool,
        pure_tol: float,
    ) -> Image.Image:
        if is_precut:
            return clean_pure_contour_zero_ai(placed_unenhanced, is_known_precut=True)
        cache_key = (
            direct_id,
            round(scale, 4),
            round(eff_px, 2),
            round(eff_py, 2),
            int(clamp_pan),
            round(pure_tol, 2),
        )
        with self._lock:
            hit = self._pure_zero_ai_cache.get(cache_key)
            if hit is not None:
                self._pure_zero_ai_cache.move_to_end(cache_key)
                return hit
        cleaned = clean_pure_contour_zero_ai(
            placed_unenhanced,
            pan_x=float(np.clip(eff_px, -65.0, 65.0)),
            pan_y=float(np.clip(eff_py, -55.0, 55.0)),
            scale=scale,
            tolerance=pure_tol,
            is_known_precut=False,
        )
        with self._lock:
            self._pure_zero_ai_cache[cache_key] = cleaned
            while len(self._pure_zero_ai_cache) > 32:
                self._pure_zero_ai_cache.popitem(last=False)
        return cleaned

    def _build_step_subjects_pair(
        self,
        p: dict[str, Any],
        need_classic: bool = True,
        need_pure: bool = False,
    ) -> tuple[Image.Image | None, Image.Image | None, float]:
        """Build geometrically locked (classic_subject, pure_subject, eff_upscale_hint) with 0% AI in Pure/Direct Photo."""
        step1_mode = str(p.get("step1Mode", "modular")).strip().lower()
        scale = _finite_float(p.get("scale", 1.0), 1.0, 0.10, 4.0)
        ox = _finite_float(p.get("offsetX", 0.0), 0.0, -2000.0, 2000.0)
        oy = _finite_float(p.get("offsetY", 0.0), 0.0, -2000.0, 2000.0)
        neck_fill = _finite_float(p.get("neckFill", 1.0), 1.0, 0.0, 1.5)
        harmonize = bool(p.get("harmonize", True))
        enhance_q = _finite_float(p.get("enhanceQuality", 0.0), 0.0, 0.0, 1.0)
        pure_tol = _finite_float(p.get("pureContourTolerance", 0.5), 0.5, 0.0, 1.0)

        if step1_mode == "direct_photo":
            direct_id = str(p.get("directPhotoId", "")).strip()
            entry = self.get_direct_photo(direct_id) if direct_id else None
            if entry is None:
                return None, None, 1.0
            raw_im, is_precut, _lbl, harm_params = entry
            fit_mode: FitMode = "contain" if is_precut else "cover"
            clamp_pan = bool(p.get("clampPan", not is_precut))
            eff_s = compute_effective_scale(raw_im.width, raw_im.height, scale, fit_mode)
            eff_px, eff_py = (
                clamp_direct_pan(raw_im.width, raw_im.height, scale, ox, oy, fit_mode=fit_mode)
                if clamp_pan
                else (ox, oy)
            )
            placed_arr = resample_linear_subpixel_rgba(
                raw_im,
                zoom=scale,
                pan_x=ox,
                pan_y=oy,
                fit_mode=fit_mode,
                clamp_to_inner=clamp_pan,
            )
            placed_im = Image.fromarray(placed_arr, mode="RGBA")
            replace_direct_bg = bool(p.get("directBgReplace", False))
            pure_base: Image.Image | None = None
            if need_pure or (need_classic and replace_direct_bg and not is_precut):
                pure_base = self._get_cached_pure_zero_ai(
                    direct_id=direct_id,
                    placed_unenhanced=placed_im,
                    is_precut=is_precut,
                    scale=scale,
                    eff_px=eff_px,
                    eff_py=eff_py,
                    clamp_pan=clamp_pan,
                    harmonize=harmonize,
                    pure_tol=pure_tol,
                )
                if harmonize:
                    pure_base = apply_oklab_harmonize_params(pure_base, harm_params)

            classic_im: Image.Image | None = None
            if need_classic:
                if replace_direct_bg and pure_base is not None:
                    c_src = pure_base
                else:
                    c_src = apply_oklab_harmonize_params(placed_im, harm_params) if harmonize else placed_im
                if enhance_q > 1e-3:
                    enh_arr = enhance_df11_pure_optics(
                        np.asarray(c_src, dtype=np.uint8),
                        amount=enhance_q,
                        upscale_hint=max(1.0, eff_s),
                    )
                    classic_im = Image.fromarray(enh_arr, mode="RGBA")
                    if c_src is pure_base and need_pure:
                        pure_base = classic_im
                else:
                    classic_im = c_src

            return classic_im, pure_base, max(1.0, eff_s)

        head_id = str(p.get("headAssetId", "")).strip()
        asset = self.get_head_asset(head_id) if head_id else None
        wear_mode = str(p.get("wearMode", "template"))

        if wear_mode in ("club", "staff_polo", "staff_suit"):
            if asset is None:
                return None, None, 1.0
            cid = str(p.get("clubId", "1736"))
            base = resolve_club_kit(cid, db_path=self.db_path)
            if p.get("customKitDirty"):
                pri = str(p.get("customPrimary") or base.primary)
                sec = str(p.get("customSecondary") or base.secondary)
                pat = str(p.get("customPattern") or base.pattern)
                kit = KitSpec(base.club_id, base.name, pat, pri, sec, sec, "custom", crest_path=base.crest_path)
            else:
                kit = base
            src_im = asset.rgba
            if harmonize:
                src_im = Image.fromarray(_harmonize_melanin_safe(np.asarray(src_im)), mode="RGBA")
            dressed = dress_or_frame_portrait(src_im, kit_mode=wear_mode, kit_spec=kit)  # type: ignore[arg-type]
            base_fit = fit_head_to_shirt_template(asset, DEFAULT_DF11_COLLAR)
            rel_scale = float(np.clip(scale / max(base_fit.scale, 1e-4), 0.35, 2.2))
            rel_ox = ox - base_fit.offset_x
            rel_oy = oy - base_fit.offset_y
            placed_arr = resample_linear_subpixel_rgba(
                dressed,
                zoom=rel_scale,
                pan_x=rel_ox,
                pan_y=rel_oy,
                fit_mode="raw",
                clamp_to_inner=False,
                dst_size=(DF11_WIDTH, DF11_HEIGHT),
            )
            base_im = Image.fromarray(placed_arr, mode="RGBA")
            pure_im = (
                clean_pure_contour_zero_ai(base_im, pan_x=rel_ox, pan_y=rel_oy, scale=rel_scale, tolerance=pure_tol)
                if need_pure
                else None
            )
            if need_classic and enhance_q > 1e-3:
                placed_arr = enhance_df11_pure_optics(placed_arr, amount=enhance_q, upscale_hint=max(1.0, rel_scale))
                classic_im = Image.fromarray(placed_arr, mode="RGBA")
            else:
                classic_im = base_im if need_classic else None
            return classic_im, pure_im, max(1.0, rel_scale)

        shirt_im, collar = self._resolve_shirt_layer(str(p.get("templateId", "")).strip()) if wear_mode == "template" else (None, None)
        if asset is None and shirt_im is None:
            return None, None, 1.0
        fit = HeadFitParams(scale=scale, offset_x=ox, offset_y=oy, neck_fill=neck_fill, harmonize=harmonize)
        mod_subj = compose_modular_subject_rgba(
            head_asset=asset,
            shirt_rgba=shirt_im,
            collar=collar,
            fit=fit,
            enhance_quality=enhance_q,
        )
        pure_mod = (
            clean_pure_contour_zero_ai(mod_subj, pan_x=ox, pan_y=oy, scale=scale, tolerance=pure_tol)
            if (need_pure and mod_subj is not None)
            else mod_subj
        )
        return (mod_subj if need_classic else None), pure_mod, 1.0

    def compose_step_card(
        self,
        p: dict[str, Any],
        custom_bg: Image.Image | None = None,
        variant: SingleCardVariant | None = None,
    ) -> Image.Image:
        eff_variant: SingleCardVariant = (
            "pure" if str(variant or p.get("previewVariant") or "classic").strip().lower() == "pure" else "classic"
        )
        enhance_q = _finite_float(p.get("enhanceQuality", 0.0), 0.0, 0.0, 1.0)
        step1_mode = str(p.get("step1Mode", "modular")).strip().lower()
        classic_subj, pure_subj, up_hint = self._build_step_subjects_pair(
            p,
            need_classic=(eff_variant == "classic"),
            need_pure=(eff_variant == "pure"),
        )
        if eff_variant == "pure":
            return render_df11_pure_card(
                pure_subj,
                enhance_quality=(enhance_q if step1_mode in ("direct_photo",) or p.get("wearMode") in ("club", "staff_polo", "staff_suit") else 0.0),
                upscale_hint=up_hint,
            )
        bg_mode = p.get("bgMode", "white_df11")
        bg_blur = _finite_float(p.get("bgBlur", 0.0), 0.0, 0.0, 24.0)
        return render_df11_card(
            portrait_rgba=classic_subj,
            portrait_offset=(0.0, 0.0),
            portrait_scale=1.0,
            bg_mode=bg_mode,
            bg_custom_rgba=custom_bg,
            bg_blur=bg_blur,
            enhance_quality=0.0,
        )

    def compose_step_dual_cards(
        self,
        p: dict[str, Any],
        custom_bg: Image.Image | None = None,
    ) -> tuple[Image.Image, Image.Image]:
        """Pixel-locked Dual-Sink: preserves Classic's natural/selected background while cleaning Pure to Alpha=0 (0% AI)."""
        enhance_q = _finite_float(p.get("enhanceQuality", 0.0), 0.0, 0.0, 1.0)
        step1_mode = str(p.get("step1Mode", "modular")).strip().lower()
        classic_subj, pure_subj, up_hint = self._build_step_subjects_pair(p, need_classic=True, need_pure=True)
        bg_mode = p.get("bgMode", "white_df11")
        bg_blur = _finite_float(p.get("bgBlur", 0.0), 0.0, 0.0, 24.0)
        classic_im = render_df11_card(
            portrait_rgba=classic_subj,
            portrait_offset=(0.0, 0.0),
            portrait_scale=1.0,
            bg_mode=bg_mode,
            bg_custom_rgba=custom_bg,
            bg_blur=bg_blur,
            enhance_quality=0.0,
        )
        pure_already_enhanced = (
            step1_mode == "direct_photo" and pure_subj is not None and pure_subj is classic_subj and enhance_q > 1e-3
        )
        pure_im = render_df11_pure_card(
            pure_subj,
            enhance_quality=(
                0.0
                if pure_already_enhanced
                else (enhance_q if step1_mode in ("direct_photo",) or p.get("wearMode") in ("club", "staff_polo", "staff_suit") else 0.0)
            ),
            upscale_hint=up_hint,
        )
        return classic_im, pure_im
