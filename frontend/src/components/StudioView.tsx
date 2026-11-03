import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Check,
  Crop,
  Crosshair,
  Download,
  FolderOpen,
  ImagePlus,
  Layers,
  Loader2,
  Redo2,
  RotateCcw,
  Scissors,
  Shirt,
  Sparkles,
  Trash2,
  Undo2,
  Upload,
} from 'lucide-react';
import FaceExtractorTool from './FaceExtractorTool';
import ShirtExtractorTool from './ShirtExtractorTool';
import {
  ClubSeed,
  CropViewportDTO,
  ExtractedFaceResponse,
  SavedFaceInfo,
  ShirtTemplateInfo,
  StagedFaceResponse,
  StorageHealth,
  callBridge,
} from '../lib/ipc';

export interface StudioJumpPayload {
  uid: string;
  previewDataUrl: string;
  clubId?: string;
  headAssetId?: string;
  matchedTemplateId?: string;
  isPreCutout?: boolean;
  autoFit?: { scale: number; offsetX: number; offsetY: number; neckFill: number };
}

interface Props {
  clubs: Record<string, ClubSeed>;
  exportDir: string;
  onExportDirChange: (dir: string, sh?: StorageHealth) => void;
  initialJump: StudioJumpPayload | null;
  onConsumeJump?: () => void;
}

const UID_RE = /^(?:r-)?[0-9]{1,12}$/;
type ToolTab = 'composer' | 'face_tool' | 'shirt_tool';
type WearMode = 'template' | 'none' | 'club' | 'staff_polo' | 'staff_suit';
type BgMode = 'transparent' | 'white_df11' | 'pearl_studio' | 'stadium_bokeh' | 'tunnel_club' | 'office_staff' | 'custom';

interface LayerSnapshot {
  headAssetId: string;
  faceLabel: string;
  wearMode: WearMode;
  templateId: string;
  clubId: string;
  scale: number;
  offsetX: number;
  offsetY: number;
  neckFill: number;
  harmonize: boolean;
  bgMode: BgMode;
  bgBlur: number;
  customKitDirty: boolean;
  customPrimary: string;
  customSecondary: string;
  customPattern: string;
}

const INITIAL_SNAP: LayerSnapshot = {
  headAssetId: '',
  faceLabel: '',
  wearMode: 'template',
  templateId: '',
  clubId: '1736',
  scale: 1.0,
  offsetX: 0,
  offsetY: 0,
  neckFill: 1.0,
  harmonize: true,
  bgMode: 'white_df11',
  bgBlur: 0,
  customKitDirty: false,
  customPrimary: '#F7F8FA',
  customSecondary: '#1E293B',
  customPattern: 'solid',
};

export default function StudioView({ clubs, exportDir, onExportDirChange, initialJump, onConsumeJump }: Props) {
  const [toolTab, setToolTab] = useState<ToolTab>('composer');
  const [templates, setTemplates] = useState<ShirtTemplateInfo[]>([]);
  const [faces, setFaces] = useState<SavedFaceInfo[]>([]);

  const [history, setHistory] = useState<{ past: LayerSnapshot[]; present: LayerSnapshot; future: LayerSnapshot[] }>({
    past: [],
    present: INITIAL_SNAP,
    future: [],
  });
  const snap = history.present;

  // Inline pre-extraction wheel-crop state on the main 260x310 canvas
  const [cropStage, setCropStage] = useState<StagedFaceResponse | null>(null);
  const [cropVp, setCropVp] = useState<CropViewportDTO>({ zoom: 1, panX: 0, panY: 0 });
  const [removeBgCrop, setRemoveBgCrop] = useState(true);

  const [previewUrl, setPreviewUrl] = useState('');
  const [busy, setBusy] = useState(false);
  const [errorMsg, setErrorMsg] = useState('');
  const [savedMsg, setSavedMsg] = useState('');
  const [showGuides, setShowGuides] = useState(true);
  const [stageSkin, setStageSkin] = useState<'fm_dark' | 'fm_light' | 'checker'>('fm_dark');
  const [hasExtractedBg, setHasExtractedBg] = useState(false);
  const [canExtractBg, setCanExtractBg] = useState(false);

  // Inline template rename/club binding state
  const [tplNameDraft, setTplNameDraft] = useState('');
  const [tplClubDraft, setTplClubDraft] = useState('');

  const [uid, setUid] = useState('');
  const [fmt, setFmt] = useState<'png' | 'jpg'>('png');
  const [updateXml, setUpdateXml] = useState(true);

  const dragRef = useRef<{ sx: number; sy: number; ox: number; oy: number; baseSnap?: LayerSnapshot } | null>(null);
  const reqSeqRef = useRef(0);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const bgInputRef = useRef<HTMLInputElement>(null);

  const commitSnap = useCallback((updater: (prev: LayerSnapshot) => LayerSnapshot) => {
    setHistory((h) => {
      const next = updater(h.present);
      if (JSON.stringify(next) === JSON.stringify(h.present)) return h;
      const past = [...h.past.slice(-34), h.present];
      return { past, present: next, future: [] };
    });
  }, []);

  const replaceLiveSnap = useCallback((updater: (prev: LayerSnapshot) => LayerSnapshot) => {
    setHistory((h) => ({ ...h, present: updater(h.present) }));
  }, []);

  const handleUndo = useCallback(() => {
    setCropStage(null);
    setHistory((h) => {
      if (h.past.length === 0) return h;
      const prev = h.past[h.past.length - 1];
      return { past: h.past.slice(0, -1), present: prev, future: [h.present, ...h.future] };
    });
  }, []);

  const handleRedo = useCallback(() => {
    setCropStage(null);
    setHistory((h) => {
      if (h.future.length === 0) return h;
      const [next, ...rest] = h.future;
      return { past: [...h.past, h.present], present: next, future: rest };
    });
  }, []);

  const handleClearCanvas = useCallback(() => {
    if (cropStage) {
      setCropStage(null);
      return;
    }
    if (!snap.headAssetId && !previewUrl) return;
    setPreviewUrl('');
    setCanExtractBg(false);
    commitSnap((s) => ({
      ...s,
      headAssetId: '',
      faceLabel: '',
      scale: 1.0,
      offsetX: 0,
      offsetY: 0,
    }));
  }, [cropStage, snap.headAssetId, previewUrl, commitSnap]);

  // Load templates & saved faces on mount
  useEffect(() => {
    callBridge<ShirtTemplateInfo[]>('list_shirt_templates')
      .then((tpls) => {
        if (Array.isArray(tpls)) {
          setTemplates(tpls);
          if (tpls.length > 0) {
            setHistory((h) =>
              h.present.templateId ? h : { ...h, present: { ...h.present, templateId: tpls[0].templateId } },
            );
          }
        }
      })
      .catch(() => {});
    callBridge<SavedFaceInfo[]>('list_saved_faces')
      .then((fcs) => {
        if (Array.isArray(fcs)) setFaces(fcs);
      })
      .catch(() => {});
  }, []);

  // Sync inline template name/club drafts when selected template changes
  useEffect(() => {
    const active = templates.find((t) => t.templateId === snap.templateId);
    setTplNameDraft(active?.displayName ?? '');
    setTplClubDraft(active?.clubId ?? '');
  }, [templates, snap.templateId]);

  // Handle jump from NG_Regens Sync tab
  useEffect(() => {
    if (!initialJump) return;
    setToolTab('composer');
    setCropStage(null);
    setUid(initialJump.uid);
    setPreviewUrl(initialJump.previewDataUrl);
    setCanExtractBg(!initialJump.isPreCutout);
    const matchedTpl = initialJump.matchedTemplateId
      ? { templateId: initialJump.matchedTemplateId }
      : initialJump.clubId
      ? templates.find((t) => t.clubId === initialJump.clubId)
      : undefined;
    commitSnap((s) => ({
      ...s,
      headAssetId: initialJump.headAssetId ?? 'legacy-jump',
      faceLabel: initialJump.uid,
      wearMode: matchedTpl ? 'template' : initialJump.clubId && clubs[initialJump.clubId] ? 'club' : 'none',
      templateId: matchedTpl ? matchedTpl.templateId : s.templateId,
      clubId: initialJump.clubId && clubs[initialJump.clubId] ? initialJump.clubId : s.clubId,
      scale: initialJump.autoFit?.scale ?? 1.0,
      offsetX: initialJump.autoFit?.offsetX ?? 0,
      offsetY: initialJump.autoFit?.offsetY ?? 0,
      neckFill: initialJump.autoFit?.neckFill ?? 1.0,
      bgMode: 'white_df11',
      bgBlur: 0,
    }));
    onConsumeJump?.();
  }, [initialJump, clubs, templates, commitSnap, onConsumeJump]);

  const hasComposition = Boolean(snap.headAssetId || (snap.wearMode === 'template' && snap.templateId));

  const composePayload = useMemo(
    () => ({
      modular: true,
      headAssetId: snap.headAssetId === 'legacy-jump' ? '' : snap.headAssetId,
      wearMode: snap.wearMode,
      templateId: snap.templateId,
      clubId: snap.clubId,
      scale: snap.scale,
      offsetX: snap.offsetX,
      offsetY: snap.offsetY,
      neckFill: snap.neckFill,
      harmonize: snap.harmonize,
      bgMode: snap.bgMode,
      bgBlur: snap.bgBlur,
      customKitDirty: snap.customKitDirty,
      customPrimary: snap.customPrimary,
      customSecondary: snap.customSecondary,
      customPattern: snap.customPattern,
    }),
    [snap],
  );

  // Live modular preview when layers/fit/background change
  useEffect(() => {
    if (cropStage) return undefined;
    if (!snap.headAssetId && !(snap.wearMode === 'template' && snap.templateId)) {
      setPreviewUrl('');
      return undefined;
    }
    if (snap.headAssetId === 'legacy-jump') return undefined;
    const seq = ++reqSeqRef.current;
    const t = window.setTimeout(async () => {
      try {
        const res = await callBridge<{ previewDataUrl: string }>('render_modular_preview', composePayload);
        if (seq === reqSeqRef.current && res?.previewDataUrl) setPreviewUrl(res.previewDataUrl);
      } catch {
        /* transient drag */
      }
    }, 65);
    return () => window.clearTimeout(t);
  }, [cropStage, snap.headAssetId, snap.wearMode, snap.templateId, composePayload]);

  const openStagedCrop = useCallback((staged: StagedFaceResponse) => {
    setCropStage(staged);
    setCropVp(staged.suggestedViewport);
    setCanExtractBg(!staged.isPreCutout);
    setErrorMsg('');
    setSavedMsg('');
  }, []);

  const handleFileBlob = useCallback(
    async (file: File) => {
      setErrorMsg(''); setSavedMsg(''); setBusy(true);
      try {
        const dataUrl = await new Promise<string>((res, rej) => {
          const r = new FileReader();
          r.onload = () => res(String(r.result));
          r.onerror = () => rej(new Error('No se pudo leer la imagen.'));
          r.readAsDataURL(file);
        });
        const staged = await callBridge<StagedFaceResponse>('load_raw_face_source', dataUrl, file.name);
        if (staged?.rawDataUrl) openStagedCrop(staged);
      } catch (e) {
        setErrorMsg(e instanceof Error ? e.message : 'Formato o tamaño inválido (máx. 20 MB / 25 MP).');
      } finally {
        setBusy(false);
      }
    },
    [openStagedCrop],
  );

  const handlePickPortrait = useCallback(async () => {
    if (window.pywebview?.api?.pick_raw_face_source) {
      setErrorMsg(''); setSavedMsg(''); setBusy(true);
      try {
        const staged = await callBridge<StagedFaceResponse | null>('pick_raw_face_source');
        if (staged?.rawDataUrl) openStagedCrop(staged);
      } catch (e) {
        setErrorMsg(e instanceof Error ? e.message : 'No se pudo abrir la imagen.');
      } finally {
        setBusy(false);
      }
      return;
    }
    if (window.pywebview?.api?.pick_and_upload_studio_image) {
      setErrorMsg(''); setSavedMsg(''); setBusy(true);
      try {
        const out = await callBridge<{ previewDataUrl: string; isPreCutout?: boolean } | null>('pick_and_upload_studio_image', true, snap.harmonize, false, {});
        if (out?.previewDataUrl) {
          setPreviewUrl(out.previewDataUrl);
          setCanExtractBg(!out.isPreCutout);
          commitSnap((s) => ({ ...s, headAssetId: 'legacy-jump', faceLabel: 'Retrato' }));
        }
      } catch (e) {
        setErrorMsg(e instanceof Error ? e.message : 'Formato inválido.');
      } finally {
        setBusy(false);
      }
      return;
    }
    fileInputRef.current?.click();
  }, [openStagedCrop, snap.harmonize, commitSnap]);

  const handleConfirmCropAndExtract = useCallback(async () => {
    if (!cropStage) return;
    setBusy(true); setErrorMsg('');
    try {
      const targetTpl = snap.wearMode === 'template' ? snap.templateId : '';
      const res = await callBridge<ExtractedFaceResponse>('extract_face_from_crop', {
        zoom: cropVp.zoom,
        panX: cropVp.panX,
        panY: cropVp.panY,
        removeBg: removeBgCrop,
        templateId: targetTpl,
        wearMode: snap.wearMode,
        bgMode: snap.bgMode,
        bgBlur: snap.bgBlur,
        harmonize: snap.harmonize,
      });
      reqSeqRef.current += 1;
      setCropStage(null);
      if (res.previewDataUrl) setPreviewUrl(res.previewDataUrl);
      commitSnap((s) => ({
        ...s,
        headAssetId: res.headAssetId,
        faceLabel: res.suggestedName || 'Cara extraída',
        scale: res.autoFit?.scale ?? 1.0,
        offsetX: res.autoFit?.offsetX ?? 0.0,
        offsetY: res.autoFit?.offsetY ?? 0.0,
        neckFill: res.autoFit?.neckFill ?? 1.0,
      }));
    } catch (e) {
      setErrorMsg(e instanceof Error ? e.message : 'No se pudo extraer la cabeza y cuello.');
    } finally {
      setBusy(false);
    }
  }, [cropStage, cropVp, removeBgCrop, snap.wearMode, snap.templateId, snap.bgMode, snap.bgBlur, snap.harmonize, commitSnap]);

  const handlePickSavedFace = useCallback(
    async (faceId: string) => {
      setBusy(true); setErrorMsg(''); setToolTab('composer'); setCropStage(null);
      try {
        const targetTpl = snap.wearMode === 'template' ? snap.templateId : '';
        const res = await callBridge<{
          headAssetId: string;
          name: string;
          isPreCutout?: boolean;
          autoFit: { scale: number; offsetX: number; offsetY: number; neckFill: number };
          previewDataUrl: string;
        }>('load_saved_face', faceId, targetTpl, composePayload);
        reqSeqRef.current += 1;
        setCanExtractBg(!res.isPreCutout);
        if (res.previewDataUrl) setPreviewUrl(res.previewDataUrl);
        commitSnap((s) => ({
          ...s,
          headAssetId: res.headAssetId,
          faceLabel: res.name,
          scale: res.autoFit?.scale ?? 1.0,
          offsetX: res.autoFit?.offsetX ?? 0.0,
          offsetY: res.autoFit?.offsetY ?? 0.0,
          neckFill: res.autoFit?.neckFill ?? 1.0,
        }));
      } catch (e) {
        setErrorMsg(e instanceof Error ? e.message : 'No se pudo cargar la cara guardada.');
      } finally {
        setBusy(false);
      }
    },
    [snap.wearMode, snap.templateId, composePayload, commitSnap],
  );

  const handleSelectTemplate = useCallback(
    async (templateId: string) => {
      setToolTab('composer');
      setErrorMsg('');
      if (snap.headAssetId && snap.headAssetId !== 'legacy-jump') {
        try {
          const fit = await callBridge<{ scale: number; offsetX: number; offsetY: number; neckFill: number }>(
            'auto_fit_head_to_template',
            snap.headAssetId,
            templateId,
          );
          commitSnap((s) => ({
            ...s,
            wearMode: 'template',
            templateId,
            scale: fit?.scale ?? s.scale,
            offsetX: fit?.offsetX ?? s.offsetX,
            offsetY: fit?.offsetY ?? s.offsetY,
            neckFill: fit?.neckFill ?? s.neckFill,
          }));
          return;
        } catch {
          /* fall through */
        }
      }
      commitSnap((s) => ({ ...s, wearMode: 'template', templateId }));
    },
    [snap.headAssetId, commitSnap],
  );

  const handleSaveTemplateMeta = async () => {
    if (!snap.templateId) return;
    setBusy(true); setErrorMsg('');
    try {
      const res = await callBridge<{ templates: ShirtTemplateInfo[] }>(
        'update_shirt_template_meta',
        snap.templateId,
        tplNameDraft,
        tplClubDraft,
      );
      if (Array.isArray(res?.templates)) setTemplates(res.templates);
      setSavedMsg(`Plantilla actualizada: ${tplNameDraft || snap.templateId}`);
    } catch (e) {
      setErrorMsg(e instanceof Error ? e.message : 'No se pudo actualizar la plantilla.');
    } finally {
      setBusy(false);
    }
  };

  // Keyboard shortcuts: Ctrl+Z (Undo), Ctrl+Y / Ctrl+Shift+Z (Redo), Delete/Suprimir (Clear), Enter (Apply Crop)
  useEffect(() => {
    if (toolTab !== 'composer') return undefined;
    const onKeyDown = (ev: KeyboardEvent) => {
      const tag = (ev.target as HTMLElement | null)?.tagName?.toLowerCase();
      if (tag === 'input' || tag === 'textarea' || tag === 'select') return;
      if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === 'z') {
        ev.preventDefault();
        if (ev.shiftKey) handleRedo();
        else handleUndo();
      } else if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === 'y') {
        ev.preventDefault();
        handleRedo();
      } else if (ev.key === 'Delete') {
        ev.preventDefault();
        handleClearCanvas();
      } else if (ev.key === 'Enter' && cropStage && !busy) {
        ev.preventDefault();
        void handleConfirmCropAndExtract();
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [toolTab, cropStage, busy, handleUndo, handleRedo, handleClearCanvas, handleConfirmCropAndExtract]);

  useEffect(() => {
    if (toolTab !== 'composer') return undefined;
    const onPaste = (ev: ClipboardEvent) => {
      const f = Array.from(ev.clipboardData?.items ?? [])
        .find((i) => i.type.startsWith('image/'))
        ?.getAsFile();
      if (f) void handleFileBlob(f);
    };
    window.addEventListener('paste', onPaste);
    return () => window.removeEventListener('paste', onPaste);
  }, [toolTab, handleFileBlob]);

  const handlePickCustomBg = useCallback(async () => {
    if (!window.pywebview?.api?.pick_and_upload_custom_background) {
      bgInputRef.current?.click();
      return;
    }
    setErrorMsg(''); setBusy(true);
    try {
      const out = await callBridge<{ bgDataUrl: string; previewDataUrl: string } | null>(
        'pick_and_upload_custom_background',
        composePayload,
      );
      if (!out) return;
      reqSeqRef.current += 1;
      commitSnap((s) => ({ ...s, bgMode: 'custom' }));
      if (out.previewDataUrl) setPreviewUrl(out.previewDataUrl);
    } catch (e) {
      setErrorMsg(e instanceof Error ? e.message : 'Fondo inválido (máx. 20 MB / 25 MP).');
    } finally {
      setBusy(false);
    }
  }, [composePayload, commitSnap]);

  const handleExtractBg = async () => {
    setErrorMsg(''); setBusy(true);
    try {
      const res = await callBridge<{ cleanBgDataUrl: string; previewDataUrl: string }>('extract_studio_background', {
        ...composePayload,
        bgMode: 'custom',
      });
      reqSeqRef.current += 1;
      setHasExtractedBg(true);
      commitSnap((s) => ({ ...s, bgMode: 'custom' }));
      if (res?.previewDataUrl) setPreviewUrl(res.previewDataUrl);
    } catch (e) {
      setErrorMsg(e instanceof Error ? e.message : 'Sube primero una foto con fondo para extraerlo.');
    } finally {
      setBusy(false);
    }
  };

  const handleCustomBgUpload = async (file: File) => {
    setErrorMsg(''); setBusy(true);
    try {
      const dataUrl = await new Promise<string>((res, rej) => {
        const r = new FileReader();
        r.onload = () => res(String(r.result));
        r.onerror = () => rej(new Error('No se pudo leer el fondo.'));
        r.readAsDataURL(file);
      });
      const out = await callBridge<{ bgDataUrl: string; previewDataUrl: string }>(
        'upload_custom_background',
        dataUrl,
        composePayload,
      );
      reqSeqRef.current += 1;
      commitSnap((s) => ({ ...s, bgMode: 'custom' }));
      if (out?.previewDataUrl) setPreviewUrl(out.previewDataUrl);
    } catch (e) {
      setErrorMsg(e instanceof Error ? e.message : 'Fondo inválido.');
    } finally {
      setBusy(false);
    }
  };

  const uidInvalid = uid.trim().length > 0 && !UID_RE.test(uid.trim());

  const handleExport = async () => {
    const cleanUid = uid.trim();
    if (!UID_RE.test(cleanUid)) {
      setErrorMsg('Introduce un ID válido (dígitos o r-<dígitos>, máx. 12 cifras).');
      return;
    }
    setBusy(true); setErrorMsg('');
    try {
      const method = snap.headAssetId === 'legacy-jump' ? 'export_studio_card' : 'export_modular_card';
      const res = await callBridge<{ savedPath: string }>(method, {
        uid: cleanUid,
        fmt,
        updateConfigXml: updateXml,
        ...composePayload,
      });
      setSavedMsg(`Guardado: ${res.savedPath ?? `${cleanUid}.${fmt}`}`);
    } catch (e) {
      setErrorMsg(e instanceof Error ? e.message : 'Error al exportar la ficha DF11.');
    } finally {
      setBusy(false);
    }
  };

  const cropFitBase = cropStage ? Math.min(260 / Math.max(cropStage.width, 1), 310 / Math.max(cropStage.height, 1)) : 1;
  const cropEffScale = cropFitBase * cropVp.zoom;
  const cropDispW = cropStage ? cropStage.width * cropEffScale : 260;
  const cropDispH = cropStage ? cropStage.height * cropEffScale : 310;
  const cropLeft = (260 - cropDispW) * 0.5 + cropVp.panX;
  const cropTop = (310 - cropDispH) * 0.5 + cropVp.panY;
  const crownRisk = cropStage !== null && cropTop + cropStage.crownSrcY * cropEffScale < 19;

  const stageBgClass =
    stageSkin === 'fm_dark'
      ? 'bg-[#0b111e] text-slate-200'
      : stageSkin === 'fm_light'
      ? 'bg-[#e6ebf2] text-slate-800'
      : 'bg-[repeating-conic-gradient(#cbd5e1_0%_25%,#f8fafc_0%_50%)] dark:bg-[repeating-conic-gradient(#1e293b_0%_25%,#0f172a_0%_50%)] bg-[length:16px_16px]';
  const segBtn = (active: boolean) =>
    `px-2.5 py-1.5 text-xs font-medium rounded-md transition ${
      active
        ? 'bg-emerald-600 text-white'
        : 'bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-slate-700'
    }`;
  const toolBtn = (active: boolean) =>
    `px-3.5 py-2 text-xs font-medium rounded-lg inline-flex items-center gap-2 transition ${
      active
        ? 'bg-emerald-600 text-white shadow-xs'
        : 'text-slate-700 dark:text-slate-300 hover:bg-slate-200/70 dark:hover:bg-slate-800'
    }`;

  return (
    <div className="space-y-5">
      {/* Top 3-Tool Switcher */}
      <div className="rounded-xl border border-slate-200/80 dark:border-slate-800 bg-white dark:bg-slate-900 p-2 flex flex-wrap items-center justify-between gap-2 shadow-xs">
        <div className="flex flex-wrap items-center gap-1.5" role="tablist" aria-label="Herramientas del Estudio DF11">
          <button type="button" role="tab" aria-selected={toolTab === 'composer'} onClick={() => setToolTab('composer')} className={toolBtn(toolTab === 'composer')}>
            <Layers className="w-4 h-4" /> Montaje Paso a Paso
          </button>
          <button type="button" role="tab" aria-selected={toolTab === 'face_tool'} onClick={() => setToolTab('face_tool')} className={toolBtn(toolTab === 'face_tool')}>
            <Scissors className="w-4 h-4" /> Extraer Cara
          </button>
          <button type="button" role="tab" aria-selected={toolTab === 'shirt_tool'} onClick={() => setToolTab('shirt_tool')} className={toolBtn(toolTab === 'shirt_tool')}>
            <Shirt className="w-4 h-4" /> Extraer Camiseta ({templates.length})
          </button>
        </div>
        <span className="px-2.5 text-[11px] text-slate-500 dark:text-slate-400 hidden sm:inline">
          Flujo modular no destructivo · 260 × 310 px
        </span>
      </div>

      {toolTab === 'face_tool' ? (
        <FaceExtractorTool
          faces={faces}
          activeTemplateId={snap.wearMode === 'template' ? snap.templateId : ''}
          onFacesUpdated={setFaces}
          onUseExtractedFace={(payload) => {
            setToolTab('composer');
            setCropStage(null);
            setCanExtractBg(!payload.isPreCutout);
            if (payload.previewDataUrl) setPreviewUrl(payload.previewDataUrl);
            commitSnap((s) => ({
              ...s,
              headAssetId: payload.headAssetId,
              faceLabel: payload.name,
              scale: payload.autoFit.scale,
              offsetX: payload.autoFit.offsetX,
              offsetY: payload.autoFit.offsetY,
              neckFill: payload.autoFit.neckFill,
            }));
          }}
          onPickSavedFace={(fid) => void handlePickSavedFace(fid)}
        />
      ) : toolTab === 'shirt_tool' ? (
        <ShirtExtractorTool
          clubs={clubs}
          templates={templates}
          onTemplatesUpdated={setTemplates}
          onSelectTemplateForComposer={(tid) => void handleSelectTemplate(tid)}
        />
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
          {/* Official 260x310 DF11 Canvas with Empty-Center Click, Wheel Pre-Crop, Undo/Redo, and Suprimir */}
          <section className="lg:col-span-5 rounded-xl shadow-xs border border-slate-200/80 dark:border-slate-800 bg-white dark:bg-slate-900 p-5 flex flex-col items-center gap-4">
            <div className="w-full flex items-center justify-between gap-2 text-xs text-slate-600 dark:text-slate-400">
              <div>
                <span className="font-medium text-slate-900 dark:text-white">Lienzo Oficial DF11</span>
                <span className="ml-2 tabular-nums font-mono text-[11px]">260 × 310 px</span>
              </div>
              <div className="flex items-center gap-1">
                <button
                  type="button"
                  aria-label="Deshacer"
                  title="Deshacer (Ctrl+Z)"
                  disabled={history.past.length === 0}
                  onClick={handleUndo}
                  className="p-1.5 rounded-md bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 disabled:opacity-35 hover:bg-slate-200 dark:hover:bg-slate-700 transition"
                >
                  <Undo2 className="w-3.5 h-3.5" />
                </button>
                <button
                  type="button"
                  aria-label="Rehacer"
                  title="Rehacer (Ctrl+Y)"
                  disabled={history.future.length === 0}
                  onClick={handleRedo}
                  className="p-1.5 rounded-md bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 disabled:opacity-35 hover:bg-slate-200 dark:hover:bg-slate-700 transition"
                >
                  <Redo2 className="w-3.5 h-3.5" />
                </button>
                <button
                  type="button"
                  aria-label="Limpiar imagen editada"
                  title="Limpiar cara (Supr)"
                  disabled={!cropStage && !snap.headAssetId && !previewUrl}
                  onClick={handleClearCanvas}
                  className="p-1.5 rounded-md bg-slate-100 dark:bg-slate-800 text-rose-600 dark:text-rose-400 disabled:opacity-35 hover:bg-rose-50 dark:hover:bg-rose-950/40 transition"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </div>
            </div>

            <div
              onDragOver={(e) => e.preventDefault()}
              onDrop={(e) => {
                e.preventDefault();
                const f = e.dataTransfer.files?.[0];
                if (f) void handleFileBlob(f);
              }}
              className={`w-full rounded-lg p-6 flex flex-col items-center justify-center transition ${stageBgClass} border border-slate-200/60 dark:border-slate-800`}
            >
              <div
                data-testid="df11-official-canvas"
                onWheel={(e) => {
                  if (cropStage) {
                    e.preventDefault();
                    const delta = e.deltaY < 0 ? 0.08 : -0.08;
                    setCropVp((v) => ({ ...v, zoom: Number(Math.min(3.2, Math.max(0.35, v.zoom + delta)).toFixed(3)) }));
                    return;
                  }
                  if (snap.headAssetId) {
                    e.preventDefault();
                    const delta = e.deltaY < 0 ? 0.04 : -0.04;
                    commitSnap((s) => ({ ...s, scale: Number(Math.min(2.2, Math.max(0.15, s.scale + delta)).toFixed(3)) }));
                  }
                }}
                onPointerDown={(e) => {
                  if ((e.target as HTMLElement | null)?.closest('button')) return;
                  if (cropStage) {
                    dragRef.current = { sx: e.clientX, sy: e.clientY, ox: cropVp.panX, oy: cropVp.panY };
                    e.currentTarget.setPointerCapture?.(e.pointerId);
                    return;
                  }
                  if (!snap.headAssetId) return;
                  dragRef.current = { sx: e.clientX, sy: e.clientY, ox: snap.offsetX, oy: snap.offsetY, baseSnap: snap };
                  e.currentTarget.setPointerCapture?.(e.pointerId);
                }}
                onPointerMove={(e) => {
                  if (!dragRef.current) return;
                  const dx = Math.round(e.clientX - dragRef.current.sx);
                  const dy = Math.round(e.clientY - dragRef.current.sy);
                  if (cropStage) {
                    setCropVp((v) => ({ ...v, panX: dragRef.current!.ox + dx, panY: dragRef.current!.oy + dy }));
                  } else {
                    replaceLiveSnap((s) => ({ ...s, offsetX: dragRef.current!.ox + dx, offsetY: dragRef.current!.oy + dy }));
                  }
                }}
                onPointerUp={() => {
                  if (dragRef.current?.baseSnap) {
                    const prevBase = dragRef.current.baseSnap;
                    setHistory((h) =>
                      prevBase.offsetX === h.present.offsetX && prevBase.offsetY === h.present.offsetY
                        ? h
                        : { past: [...h.past.slice(-34), prevBase], present: h.present, future: [] },
                    );
                  }
                  dragRef.current = null;
                }}
                onPointerCancel={() => {
                  dragRef.current = null;
                }}
                className={`relative w-[260px] h-[310px] overflow-hidden select-none ${
                  cropStage || snap.headAssetId ? 'cursor-grab active:cursor-grabbing' : 'cursor-pointer'
                } flex items-center justify-center`}
              >
                {cropStage ? (
                  <img
                    src={cropStage.rawDataUrl}
                    alt="Zona de corte previa"
                    style={{ width: `${cropDispW}px`, height: `${cropDispH}px`, left: `${cropLeft}px`, top: `${cropTop}px` }}
                    className="absolute max-w-none pointer-events-none"
                  />
                ) : snap.headAssetId && previewUrl ? (
                  <img src={previewUrl} alt="Previsualización DF11 260x310" className="w-[260px] h-[310px] pointer-events-none" />
                ) : (
                  <>
                    {previewUrl && (
                      <img
                        src={previewUrl}
                        alt="Plantilla base DF11"
                        className="absolute inset-0 w-[260px] h-[310px] opacity-65 pointer-events-none"
                      />
                    )}
                    <button
                      type="button"
                      onClick={() => void handlePickPortrait()}
                      className="relative z-10 w-[222px] h-[276px] rounded-xl border-2 border-dashed border-slate-400/70 dark:border-slate-600 flex flex-col items-center justify-center gap-2 px-4 text-center text-xs text-slate-700 dark:text-slate-200 bg-white/75 dark:bg-slate-900/75 cursor-pointer hover:border-emerald-500/80 transition"
                    >
                      <Upload className="w-6 h-6 text-emerald-600 dark:text-emerald-400" />
                      <span className="font-medium">Arrastra foto, haz clic o pulsa Ctrl+V</span>
                      <span className="text-[11px] text-slate-500 dark:text-slate-400">
                        Abre tu última carpeta · Rueda = Zona de corte
                      </span>
                    </button>
                  </>
                )}

                {(showGuides || cropStage) && (
                  <svg className="absolute inset-0 w-[260px] h-[310px] pointer-events-none" viewBox="0 0 260 310">
                    <line
                      x1="19"
                      y1="21"
                      x2="241"
                      y2="21"
                      stroke={crownRisk ? '#f59e0b' : '#10b981'}
                      strokeDasharray="3 3"
                      strokeWidth="1.2"
                    />
                    <line x1="19" y1="113" x2="241" y2="113" stroke="#38bdf8" strokeDasharray="4 2" strokeWidth="1" />
                    <line x1="19" y1="292" x2="241" y2="292" stroke="#f59e0b" strokeDasharray="3 3" strokeWidth="1" />
                    <line x1="130" y1="17" x2="130" y2="292" stroke="#94a3b8" strokeOpacity="0.4" strokeDasharray="2 4" strokeWidth="1" />
                  </svg>
                )}

                {busy && (
                  <div className="absolute inset-0 z-20 bg-slate-950/45 rounded-lg flex items-center justify-center gap-2 text-xs font-medium text-white">
                    <Loader2 className="w-4 h-4 animate-spin" /> Procesando capas…
                  </div>
                )}
              </div>
            </div>

            {cropStage && (
              <div className="w-full rounded-lg p-3 bg-emerald-50/70 dark:bg-emerald-950/30 border border-emerald-500/30 space-y-2 text-xs">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-medium text-emerald-900 dark:text-emerald-200">
                    Zona de corte ({Math.round(cropVp.zoom * 100)}%) {crownRisk ? '· ¡Tope cabeza!' : '· Rueda = Zoom'}
                  </span>
                  {crownRisk && (
                    <button
                      type="button"
                      onClick={() => setCropVp(cropStage.suggestedViewport)}
                      className="text-[11px] underline font-medium text-amber-700 dark:text-amber-300"
                    >
                      Auto-proteger
                    </button>
                  )}
                  <label className="inline-flex items-center gap-1.5 text-[11px] text-slate-700 dark:text-slate-300">
                    <input
                      type="checkbox"
                      checked={removeBgCrop}
                      onChange={(e) => setRemoveBgCrop(e.target.checked)}
                      className="accent-emerald-600"
                    />
                    Quitar fondo
                  </label>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => void handleConfirmCropAndExtract()}
                    className="flex-1 px-3 py-1.5 rounded-md bg-emerald-600 hover:bg-emerald-500 text-white font-medium inline-flex items-center justify-center gap-1.5"
                  >
                    <Crop className="w-3.5 h-3.5" /> Aplicar zona de corte
                  </button>
                  <button
                    type="button"
                    onClick={() => setCropStage(null)}
                    className="px-2.5 py-1.5 rounded-md bg-slate-200 dark:bg-slate-800 text-slate-700 dark:text-slate-300"
                  >
                    Cancelar
                  </button>
                </div>
              </div>
            )}

            <div className="w-full flex flex-wrap items-center justify-between gap-2 text-xs">
              <div className="flex items-center gap-1">
                <button type="button" onClick={() => setStageSkin('fm_dark')} className={segBtn(stageSkin === 'fm_dark')}>Skin Oscura</button>
                <button type="button" onClick={() => setStageSkin('fm_light')} className={segBtn(stageSkin === 'fm_light')}>Skin Clara</button>
                <button type="button" onClick={() => setStageSkin('checker')} className={segBtn(stageSkin === 'checker')}>Alfa 0</button>
              </div>
              <div className="flex items-center gap-2">
                <button type="button" onClick={() => setShowGuides((g) => !g)} className={segBtn(showGuides)} title="Guías ópticas">
                  <Crosshair className="w-3.5 h-3.5" />
                </button>
                <span className="tabular-nums text-slate-500 dark:text-slate-400">
                  X:{snap.offsetX} · Y:{snap.offsetY}
                </span>
              </div>
            </div>
          </section>

          {/* Right Panel: Chronological 4-Step Layer Builder */}
          <section className="lg:col-span-7 rounded-xl shadow-xs border border-slate-200/80 dark:border-slate-800 bg-white dark:bg-slate-900 divide-y divide-slate-200/80 dark:divide-slate-800">
            {/* PASO 1: CARA Y CUELLO */}
            <div className="p-4 space-y-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <h2 className="text-xs font-semibold uppercase tracking-wider text-emerald-700 dark:text-emerald-400">
                    Paso 1 · Capa Cara y Cuello
                  </h2>
                  <p className="text-xs text-slate-600 dark:text-slate-400 mt-0.5">
                    {snap.faceLabel ? `Activa: ${snap.faceLabel}` : 'Elige una cara extraída o sube una imagen para recortar su zona.'}
                  </p>
                </div>
                <div className="flex items-center gap-1.5">
                  <input
                    ref={fileInputRef}
                    type="file"
                    accept="image/*"
                    className="hidden"
                    onChange={(e) => {
                      const f = e.target.files?.[0];
                      e.target.value = '';
                      if (f) void handleFileBlob(f);
                    }}
                  />
                  <button
                    type="button"
                    onClick={() => void handlePickPortrait()}
                    className="px-3 py-1.5 text-xs font-medium rounded-md bg-emerald-600 hover:bg-emerald-500 text-white inline-flex items-center gap-1.5"
                  >
                    <ImagePlus className="w-3.5 h-3.5" /> Subir retrato
                  </button>
                  <button
                    type="button"
                    disabled={!snap.headAssetId || snap.wearMode !== 'template' || !snap.templateId}
                    onClick={() => snap.templateId && void handleSelectTemplate(snap.templateId)}
                    className="px-2.5 py-1.5 text-xs rounded-md bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 disabled:opacity-40 inline-flex items-center gap-1"
                    title="Auto-encajar cabeza y cuello a la camiseta plantilla"
                  >
                    <RotateCcw className="w-3.5 h-3.5" /> Auto-encajar
                  </button>
                </div>
              </div>

              {faces.length > 0 && (
                <div className="flex items-center gap-2 overflow-x-auto pb-1">
                  {faces.map((f) => (
                    <button
                      key={f.faceId}
                      type="button"
                      onClick={() => void handlePickSavedFace(f.faceId)}
                      title={`Cargar ${f.name}`}
                      className="shrink-0 px-2 py-1 rounded-md border border-slate-200 dark:border-slate-800 hover:border-emerald-500 bg-slate-50 dark:bg-slate-950/60 inline-flex items-center gap-1.5 text-[11px] text-slate-700 dark:text-slate-300 transition"
                    >
                      <img src={f.thumbDataUrl} alt={f.name} className="w-6 h-6 object-contain rounded bg-slate-900" />
                      <span className="max-w-[92px] truncate">{f.name}</span>
                    </button>
                  ))}
                </div>
              )}

              <div className="grid grid-cols-1 sm:grid-cols-12 gap-3 items-center text-xs">
                <label className="sm:col-span-3 inline-flex items-center gap-2 text-slate-700 dark:text-slate-300">
                  <input
                    type="checkbox"
                    checked={snap.harmonize}
                    onChange={(e) => commitSnap((s) => ({ ...s, harmonize: e.target.checked }))}
                    className="accent-emerald-600"
                  />
                  Luz DF11
                </label>
                <label className="sm:col-span-4 flex items-center gap-2 text-slate-700 dark:text-slate-300 tabular-nums">
                  <span>Zoom</span>
                  <input
                    type="range"
                    min="0.15"
                    max="2.2"
                    step="0.02"
                    value={snap.scale}
                    onChange={(e) => commitSnap((s) => ({ ...s, scale: Number(e.target.value) }))}
                    className="w-full accent-emerald-600"
                  />
                  <span>{Math.round(snap.scale * 100)}%</span>
                </label>
                <label className="sm:col-span-5 flex items-center gap-2 text-slate-700 dark:text-slate-300 tabular-nums">
                  <span className="shrink-0">Cuello</span>
                  <input
                    type="range"
                    min="0"
                    max="1.4"
                    step="0.05"
                    value={snap.neckFill}
                    onChange={(e) => commitSnap((s) => ({ ...s, neckFill: Number(e.target.value) }))}
                    className="w-full accent-emerald-600"
                  />
                  <span>{Math.round(snap.neckFill * 100)}%</span>
                </label>
              </div>
            </div>

            {/* PASO 2: CAMISETA PLANTILLA */}
            <div className="p-4 space-y-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h2 className="text-xs font-semibold uppercase tracking-wider text-emerald-700 dark:text-emerald-400">
                  Paso 2 · Capa Camiseta Plantilla
                </h2>
                <div className="flex flex-wrap items-center gap-1">
                  <button type="button" onClick={() => commitSnap((s) => ({ ...s, wearMode: 'template' }))} className={segBtn(snap.wearMode === 'template')}>
                    Plantilla
                  </button>
                  <button type="button" onClick={() => commitSnap((s) => ({ ...s, wearMode: 'none' }))} className={segBtn(snap.wearMode === 'none')}>
                    Original / Sin
                  </button>
                  <button type="button" onClick={() => commitSnap((s) => ({ ...s, wearMode: 'club' }))} className={segBtn(snap.wearMode === 'club')}>
                    Club
                  </button>
                  <button type="button" onClick={() => commitSnap((s) => ({ ...s, wearMode: 'staff_polo' }))} className={segBtn(snap.wearMode === 'staff_polo')}>
                    Polo Staff
                  </button>
                  <button type="button" onClick={() => commitSnap((s) => ({ ...s, wearMode: 'staff_suit' }))} className={segBtn(snap.wearMode === 'staff_suit')}>
                    Traje Staff
                  </button>
                </div>
              </div>

              {snap.wearMode === 'template' && (
                <div className="space-y-2.5">
                  <div className="grid grid-cols-3 sm:grid-cols-5 gap-2 max-h-40 overflow-y-auto pr-1">
                    {templates.map((t) => {
                      const active = t.templateId === snap.templateId;
                      return (
                        <button
                          key={t.templateId}
                          type="button"
                          onClick={() => void handleSelectTemplate(t.templateId)}
                          className={`p-1.5 rounded-lg border text-center flex flex-col items-center gap-1 transition ${
                            active
                              ? 'border-emerald-500 bg-emerald-50/60 dark:bg-emerald-950/30'
                              : 'border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950/50 hover:border-slate-400'
                          }`}
                        >
                          <img src={t.thumbDataUrl} alt={t.displayName} className="w-12 h-12 object-contain rounded bg-[#0f172a]" />
                          <span className="text-[11px] font-medium truncate w-full text-slate-800 dark:text-slate-200">
                            {t.displayName}
                          </span>
                        </button>
                      );
                    })}
                    <button
                      type="button"
                      onClick={() => setToolTab('shirt_tool')}
                      className="p-1.5 rounded-lg border border-dashed border-emerald-500/60 hover:border-emerald-500 text-emerald-700 dark:text-emerald-400 flex flex-col items-center justify-center gap-1 text-[11px] font-medium"
                    >
                      <Shirt className="w-5 h-5" />
                      <span>+ Extraer camiseta</span>
                    </button>
                  </div>

                  {snap.templateId && (
                    <div className="grid grid-cols-1 sm:grid-cols-12 gap-2 items-center text-xs pt-1">
                      <input
                        aria-label="Nombre de la camiseta activa"
                        value={tplNameDraft}
                        onChange={(e) => setTplNameDraft(e.target.value)}
                        placeholder="Nombre club / plantilla"
                        className="sm:col-span-5 px-2.5 py-1.5 rounded-md border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-950 text-slate-900 dark:text-slate-100"
                      />
                      <select
                        aria-label="Vincular plantilla a club"
                        value={tplClubDraft}
                        onChange={(e) => setTplClubDraft(e.target.value)}
                        className="sm:col-span-4 px-2 py-1.5 rounded-md border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-950 text-slate-900 dark:text-slate-100 truncate"
                      >
                        <option value="">Sin club fijo</option>
                        {Object.entries(clubs).map(([cid, info]) => (
                          <option key={cid} value={cid}>
                            {info.name} (#{cid})
                          </option>
                        ))}
                      </select>
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => void handleSaveTemplateMeta()}
                        className="sm:col-span-3 px-2.5 py-1.5 rounded-md bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 dark:hover:bg-slate-700 text-slate-800 dark:text-slate-200 font-medium"
                      >
                        Guardar nombre
                      </button>
                    </div>
                  )}
                </div>
              )}

              {(snap.wearMode === 'club' || snap.wearMode === 'staff_polo' || snap.wearMode === 'staff_suit') && (
                <div className="grid grid-cols-1 sm:grid-cols-12 gap-2 items-center pt-1">
                  <select
                    aria-label="Selector de club"
                    value={snap.clubId}
                    onChange={(e) => {
                      const cid = e.target.value;
                      const c = clubs[cid];
                      commitSnap((s) => ({
                        ...s,
                        clubId: cid,
                        customKitDirty: false,
                        customPrimary: c?.primary ?? '#F7F8FA',
                        customSecondary: c?.secondary ?? '#F8FAFC',
                        customPattern: c?.pattern ?? 'solid',
                      }));
                    }}
                    className="sm:col-span-6 px-2.5 py-1.5 text-xs rounded-md border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-950 text-slate-900 dark:text-slate-100 truncate"
                  >
                    {Object.entries(clubs).map(([cid, info]) => (
                      <option key={cid} value={cid}>
                        {info.name} (#{cid})
                      </option>
                    ))}
                  </select>
                  <select
                    aria-label="Patrón textil"
                    value={snap.customPattern}
                    onChange={(e) => commitSnap((s) => ({ ...s, customPattern: e.target.value, customKitDirty: true }))}
                    className="sm:col-span-3 px-2 py-1.5 text-xs rounded-md border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-950 text-slate-900 dark:text-slate-100"
                  >
                    <option value="solid">Liso</option>
                    <option value="stripes">Rayas</option>
                    <option value="halves">Mitades</option>
                    <option value="hoops">Franjas</option>
                    <option value="sash">Banda</option>
                  </select>
                  <div className="sm:col-span-3 flex items-center justify-end gap-1.5">
                    <input
                      type="color"
                      title="Color primario textil"
                      value={snap.customPrimary}
                      onChange={(e) => commitSnap((s) => ({ ...s, customPrimary: e.target.value, customKitDirty: true }))}
                      className="w-7 h-7 rounded cursor-pointer border border-slate-300 dark:border-slate-700 bg-transparent"
                    />
                    <input
                      type="color"
                      title="Color secundario textil"
                      value={snap.customSecondary}
                      onChange={(e) => commitSnap((s) => ({ ...s, customSecondary: e.target.value, customKitDirty: true }))}
                      className="w-7 h-7 rounded cursor-pointer border border-slate-300 dark:border-slate-700 bg-transparent"
                    />
                  </div>
                </div>
              )}
            </div>

            {/* PASO 3: FONDO */}
            <div className="p-4 space-y-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h2 className="text-xs font-semibold uppercase tracking-wider text-emerald-700 dark:text-emerald-400">
                  Paso 3 · Capa Fondo (Por defecto DF11)
                </h2>
                <div className="flex items-center gap-2">
                  <input
                    ref={bgInputRef}
                    type="file"
                    accept="image/*"
                    className="hidden"
                    onChange={(e) => {
                      const f = e.target.files?.[0];
                      e.target.value = '';
                      if (f) void handleCustomBgUpload(f);
                    }}
                  />
                  <button
                    type="button"
                    onClick={() => void handlePickCustomBg()}
                    className="px-2.5 py-1 text-xs rounded-md bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300"
                  >
                    Subir fondo
                  </button>
                  <button
                    type="button"
                    disabled={!snap.headAssetId || !canExtractBg || busy}
                    onClick={() => void handleExtractBg()}
                    title={!canExtractBg ? 'Disponible cuando subes una foto con fondo original' : 'Extraer fondo limpio de la foto'}
                    className="px-2.5 py-1 text-xs rounded-md bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 disabled:opacity-45 inline-flex items-center gap-1"
                  >
                    <Sparkles className="w-3 h-3" /> Extraer de foto
                  </button>
                </div>
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 items-center text-xs">
                <select
                  aria-label="Modo de fondo"
                  value={snap.bgMode}
                  onChange={(e) => commitSnap((s) => ({ ...s, bgMode: e.target.value as BgMode }))}
                  className="px-2.5 py-1.5 rounded-md border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-950 text-slate-900 dark:text-slate-100"
                >
                  <option value="white_df11">Blanco Estudio DF11 (Oficial)</option>
                  <option value="transparent">Sin fondo (Transparente)</option>
                  <option value="pearl_studio">Gris Perla Estudio</option>
                  <option value="stadium_bokeh">Estadio Nocturno</option>
                  <option value="tunnel_club">Túnel de Vestuarios</option>
                  <option value="office_staff">Despacho Staff / Prensa</option>
                  <option value="custom">{hasExtractedBg ? 'Fondo Limpio Extraído / Propio' : 'Fondo Personalizado'}</option>
                </select>
                <label className="flex items-center gap-2 text-slate-700 dark:text-slate-300 tabular-nums">
                  <span>Bokeh</span>
                  <input
                    type="range"
                    min="0"
                    max="18"
                    step="0.5"
                    disabled={snap.bgMode === 'transparent'}
                    value={snap.bgBlur}
                    onChange={(e) => commitSnap((s) => ({ ...s, bgBlur: Number(e.target.value) }))}
                    className="w-full accent-emerald-600 disabled:opacity-40"
                  />
                  <span>{snap.bgBlur}px</span>
                </label>
              </div>
            </div>

            {/* PASO 4: MARCO MAESTRO Y EXPORTACIÓN */}
            <div className="p-4 space-y-3 bg-slate-50/70 dark:bg-slate-950/40 rounded-b-xl">
              <div className="flex items-center justify-between text-xs">
                <span className="font-semibold uppercase tracking-wider text-emerald-700 dark:text-emerald-400">
                  Paso 4 · Marco Maestro DF11 y Exportación
                </span>
                <span className="text-[11px] text-slate-500 dark:text-slate-400">Anillo exterior Alpha = 0 garantizado</span>
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-12 gap-2.5 items-center">
                <div className="sm:col-span-5">
                  <input
                    aria-label="ID Football Manager"
                    value={uid}
                    onChange={(e) => setUid(e.target.value)}
                    placeholder="ID FM / Partida (ej: 29184012 o r-2002049102)"
                    className="w-full px-3 py-1.5 text-xs rounded-md border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-950 text-slate-900 dark:text-slate-100 tabular-nums font-mono"
                  />
                </div>
                <div className="sm:col-span-3 flex items-center gap-1">
                  <button type="button" onClick={() => setFmt('png')} className={segBtn(fmt === 'png')}>PNG Oficial</button>
                  <button type="button" onClick={() => setFmt('jpg')} className={segBtn(fmt === 'jpg')}>JPG</button>
                </div>
                <div className="sm:col-span-4 flex justify-end">
                  <button
                    type="button"
                    disabled={busy || !hasComposition}
                    onClick={() => void handleExport()}
                    className="w-full px-3 py-1.5 text-xs font-medium rounded-md bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white inline-flex items-center justify-center gap-1.5"
                  >
                    <Download className="w-3.5 h-3.5" /> Exportar DF11
                  </button>
                </div>
              </div>
              <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-slate-600 dark:text-slate-400">
                <label className="inline-flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={updateXml}
                    disabled={fmt !== 'png'}
                    onChange={(e) => setUpdateXml(e.target.checked)}
                    className="accent-emerald-600"
                  />
                  Actualizar config.xml atómico
                </label>
                <button
                  type="button"
                  onClick={async () => {
                    try {
                      const p = await callBridge<{ path: string; storageHealth?: StorageHealth } | null>('choose_directory', 'export');
                      if (p?.path) onExportDirChange(p.path, p.storageHealth);
                    } catch (e) {
                      setErrorMsg(e instanceof Error ? e.message : 'Carpeta no válida.');
                    }
                  }}
                  title={exportDir}
                  className="max-w-[260px] truncate inline-flex items-center gap-1 text-slate-700 dark:text-slate-300 hover:underline"
                >
                  <FolderOpen className="w-3.5 h-3.5 shrink-0" /> {exportDir}
                </button>
              </div>
              {uidInvalid && <p className="text-xs text-amber-600 dark:text-amber-400">Usa dígitos o r-&lt;dígitos&gt; (máx. 12 cifras).</p>}
              {errorMsg && <p className="text-xs text-rose-600 dark:text-rose-400">{errorMsg}</p>}
              {savedMsg && (
                <p className="text-xs text-emerald-700 dark:text-emerald-400 inline-flex items-center gap-1">
                  <Check className="w-3.5 h-3.5" /> {savedMsg}
                </p>
              )}
            </div>
          </section>
        </div>
      )}
    </div>
  );
}
