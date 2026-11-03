"""Stateful modular session manager for Face Extractor, Shirt Extractor, and Step-by-Step Layer Composer."""

from __future__ import annotations

import base64
from collections import OrderedDict
import io
from pathlib import Path
import threading
from typing import Any

import numpy as np
from PIL import Image

from backend.core.compositor import render_df11_card
from backend.core.image_guard import load_guarded_image
from backend.services.head_neck import (
    DEFAULT_DF11_COLLAR,
    CropViewport,
    HeadFitParams,
    HeadNeckAsset,
    _harmonize_melanin_safe,
    compose_modular_df11,
    extract_clean_head_and_neck,
    fit_head_to_shirt_template,
    list_face_library_files,
    save_clean_face_to_library,
    suggest_safe_crop_viewport,
    viewport_to_head_fit,
)
from backend.services.kits import KitSpec, dress_or_frame_portrait, resolve_club_kit
from backend.services.templates import (
    ShirtTemplate,
    extract_collar_profile,
    rename_shirt_template,
    sanitize_shirt_template_rgba,
    save_new_shirt_template,
    sync_tshirt_templates_dir,
)

MAX_CACHED_HEADS = 48


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
        self._crop_is_precut: bool = False
        self._crop_name: str = ""
        self._crop_suggested_vp: CropViewport = CropViewport()

        # Staged raw shirt for interactive template extraction
        self._shirt_raw_img: Image.Image | None = None
        self._shirt_raw_bytes: bytes | None = None
        self._shirt_preview_img: Image.Image | None = None
        self._shirt_preview_params: tuple[bool, float, float, float, float] | None = None

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
        vp = suggest_safe_crop_viewport(g.image)
        with self._lock:
            self._crop_raw_img = g.image
            self._crop_is_precut = g.is_pre_cutout
            self._crop_name = Path(file_name).stem if file_name else "Retrato"
            self._crop_suggested_vp = vp

        alpha = np.asarray(g.image.convert("RGBA"), dtype=np.uint8)[:, :, 3]
        ys = np.where(alpha > 24)[0]
        crown_src_y = int(ys.min()) if len(ys) else 0
        w, h = g.image.size
        return {
            "rawDataUrl": _png_data_url(g.image),
            "width": w,
            "height": h,
            "isPreCutout": g.is_pre_cutout,
            "crownSrcY": crown_src_y,
            "suggestedViewport": {"zoom": vp.zoom, "panX": vp.pan_x, "panY": vp.pan_y},
            "fileName": file_name,
        }

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
                        "collarWidth": t.collar.collar_width,
                        "apexY": t.collar.apex[1],
                        "thumbDataUrl": self._cached_thumb(t.file_path),
                    }
                )
            except Exception:
                continue
        return out

    def _find_template(self, template_id: str) -> ShirtTemplate | None:
        if not template_id:
            return None
        items = sync_tshirt_templates_dir(
            tpl_dir=self.templates_dir,
            raw_archive_dir=self.raw_archive_dir,
            db_path=self.db_path,
        )
        return next((t for t in items if t.template_id == template_id), None)

    def stage_raw_shirt(self, raw_bytes: bytes, file_name: str = "") -> dict[str, Any]:
        g = load_guarded_image(raw_bytes)
        clean = sanitize_shirt_template_rgba(g.image, symmetrize_shoulders=True, shoulder_boost=0.0)
        with self._lock:
            self._shirt_raw_img = g.image
            self._shirt_raw_bytes = raw_bytes
            self._shirt_preview_img = clean
            self._shirt_preview_params = (True, 0.0, 1.0, 0.0, 0.0)
        collar = extract_collar_profile(clean)
        stem = Path(file_name).stem if file_name else "Camiseta_Club"
        return {
            "rawDataUrl": _png_data_url(g.image),
            "cleanShirtDataUrl": _png_data_url(clean),
            "collarWidth": collar.collar_width,
            "apexY": collar.apex[1],
            "suggestedName": stem,
        }

    def preview_shirt(self, opts: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            raw_img = self._shirt_raw_img
        if raw_img is None:
            raise ValueError("Sube primero una imagen con camiseta para extraer la plantilla.")
        params = (
            bool(opts.get("symmetrizeShoulders", True)),
            round(float(opts.get("shoulderBoost", 0.0)), 4),
            round(float(opts.get("zoom", 1.0)), 4),
            round(float(opts.get("panX", 0.0)), 2),
            round(float(opts.get("panY", 0.0)), 2),
        )
        clean = sanitize_shirt_template_rgba(
            raw_img,
            symmetrize_shoulders=params[0],
            shoulder_boost=params[1],
            zoom=params[2],
            pan_x=params[3],
            pan_y=params[4],
        )
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
        with self._lock:
            raw_img = self._shirt_raw_img
            raw_bytes = self._shirt_raw_bytes
            prev_img = self._shirt_preview_img
            prev_params = self._shirt_preview_params
        if prev_img is None and raw_img is None:
            raise ValueError("Extrae primero una camiseta antes de guardarla en tshirt_templates.")
        if raw_img is not None and any(k in opts for k in ("symmetrizeShoulders", "shoulderBoost", "zoom", "panX", "panY")):
            req_params = (
                bool(opts.get("symmetrizeShoulders", True)),
                round(float(opts.get("shoulderBoost", 0.0)), 4),
                round(float(opts.get("zoom", 1.0)), 4),
                round(float(opts.get("panX", 0.0)), 2),
                round(float(opts.get("panY", 0.0)), 2),
            )
            if prev_params != req_params or prev_img is None:
                prev_img = sanitize_shirt_template_rgba(
                    raw_img,
                    symmetrize_shoulders=req_params[0],
                    shoulder_boost=req_params[1],
                    zoom=req_params[2],
                    pan_x=req_params[3],
                    pan_y=req_params[4],
                )
                with self._lock:
                    self._shirt_preview_img = prev_img
                    self._shirt_preview_params = req_params
        assert prev_img is not None
        tpl = save_new_shirt_template(
            clean_rgba=prev_img,
            raw_bytes=raw_bytes,
            display_name=str(opts.get("displayName", "")),
            club_id=str(opts.get("clubId", "")),
            template_id=str(opts.get("templateId", "")),
            tpl_dir=self.templates_dir,
            raw_archive_dir=self.raw_archive_dir,
            db_path=self.db_path,
        )
        return {"savedTemplateId": tpl.template_id, "templates": self.list_templates()}

    def update_template_meta(self, template_id: str, display_name: str, club_id: str = "") -> dict[str, Any]:
        rename_shirt_template(
            template_id=template_id,
            display_name=display_name,
            club_id=club_id,
            tpl_dir=self.templates_dir,
            db_path=self.db_path,
        )
        return {"templates": self.list_templates()}

    # --- Tool 3: Step-by-Step Modular Layer Composer ---

    def compute_auto_fit(self, head_asset_id: str, template_id: str = "") -> dict[str, float]:
        asset = self.get_head_asset(head_asset_id)
        if asset is None:
            return {"scale": 1.0, "offsetX": 0.0, "offsetY": 0.0, "neckFill": 1.0}
        tpl = self._find_template(template_id) if template_id else None
        collar = tpl.collar if tpl is not None else DEFAULT_DF11_COLLAR
        fit = fit_head_to_shirt_template(asset, collar)
        return {"scale": fit.scale, "offsetX": fit.offset_x, "offsetY": fit.offset_y, "neckFill": fit.neck_fill}

    def compose_step_card(self, p: dict[str, Any], custom_bg: Image.Image | None = None) -> Image.Image:
        head_id = str(p.get("headAssetId", "")).strip()
        asset = self.get_head_asset(head_id) if head_id else None
        wear_mode = str(p.get("wearMode", "template"))
        bg_mode = p.get("bgMode", "white_df11")
        bg_blur = float(p.get("bgBlur", 0.0))
        scale = float(p.get("scale", 1.0))
        ox = float(p.get("offsetX", 0.0))
        oy = float(p.get("offsetY", 0.0))
        neck_fill = float(p.get("neckFill", 1.0))
        harmonize = bool(p.get("harmonize", True))

        if wear_mode in ("club", "staff_polo", "staff_suit"):
            if asset is None:
                return render_df11_card(None, bg_mode=bg_mode, bg_custom_rgba=custom_bg, bg_blur=bg_blur)
            cid = str(p.get("clubId", "1736"))
            base = resolve_club_kit(cid, db_path=self.db_path)
            if p.get("customKitDirty"):
                pri = str(p.get("customPrimary") or base.primary)
                sec = str(p.get("customSecondary") or base.secondary)
                pat = str(p.get("customPattern") or base.pattern)
                kit = KitSpec(base.club_id, base.name, pat, pri, sec, sec, "custom", base.crest_path)
            else:
                kit = base
            src_im = asset.rgba
            if harmonize:
                src_im = Image.fromarray(_harmonize_melanin_safe(np.asarray(src_im)), mode="RGBA")
            dressed = dress_or_frame_portrait(src_im, kit_mode=wear_mode, kit_spec=kit)  # type: ignore[arg-type]
            # Convert asset-space (scale, ox, oy) into relative 260x310 DF11 stage space so switching wearMode never shrinks/blows up
            base_fit = fit_head_to_shirt_template(asset, DEFAULT_DF11_COLLAR)
            rel_scale = float(np.clip(scale / max(base_fit.scale, 1e-4), 0.35, 2.2))
            rel_ox = ox - base_fit.offset_x
            rel_oy = oy - base_fit.offset_y
            return render_df11_card(
                portrait_rgba=dressed,
                portrait_offset=(rel_ox, rel_oy),
                portrait_scale=rel_scale,
                bg_mode=bg_mode,
                bg_custom_rgba=custom_bg,
                bg_blur=bg_blur,
            )

        tpl = self._find_template(str(p.get("templateId", "")).strip()) if wear_mode == "template" else None
        shirt_im = self._load_template_image(tpl) if tpl is not None else None
        collar = tpl.collar if tpl is not None else None
        fit = HeadFitParams(scale=scale, offset_x=ox, offset_y=oy, neck_fill=neck_fill, harmonize=harmonize)
        return compose_modular_df11(
            head_asset=asset,
            shirt_rgba=shirt_im,
            collar=collar,
            fit=fit,
            bg_mode=bg_mode,
            bg_custom_rgba=custom_bg,
            bg_blur=bg_blur,
        )
