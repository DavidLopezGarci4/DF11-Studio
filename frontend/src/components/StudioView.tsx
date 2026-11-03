import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Check,
  ChevronDown,
  ChevronUp,
  Crop,
  Crosshair,
  Download,
  FolderOpen,
  ImagePlus,
  Layers,
  Loader2,
  Redo2,
  RefreshCw,
  RotateCcw,
  Save,
  Scissors,
  Search,
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
  FacepackRemixResponse,
  SavedFaceInfo,
  ShirtTemplateInfo,
  StagedFaceResponse,
  StorageHealth,
  TemplateCategory,
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
  onClubsUpdated?: (clubs: Record<string, ClubSeed>) => void;
  exportDir: string;
  facepackDir?: string;
  onExportDirChange: (dir: string, sh?: StorageHealth) => void;
  onFacepackDirChange?: (dir: string) => void;
  initialJump: StudioJumpPayload | null;
  onConsumeJump?: () => void;
}

const UID_RE = /^(?:r-)?[0-9]{1,12}$/;

function resolveNextClubName(
  prevCid: string,
  prevName: string,
  nextCid: string,
  clubs: Record<string, ClubSeed>,
  templates: ShirtTemplateInfo[],
): string {
  if (!nextCid) return '';
  const knownNext = clubs[nextCid]?.name;
  if (knownNext !== undefined) return knownNext;
  const tplNext = templates.find((t) => t.clubId === nextCid && t.clubName)?.clubName;
  if (tplNext) return tplNext;
  const prevCatalogName =
    (prevCid ? clubs[prevCid]?.name : undefined) ??
    (prevCid ? templates.find((t) => t.clubId === prevCid && t.clubName)?.clubName : undefined);
  if (prevCatalogName !== undefined && prevName === prevCatalogName) return '';
  if (prevCid && !(nextCid.startsWith(prevCid) || prevCid.startsWith(nextCid))) return '';
  return prevName;
}

type ToolTab = 'composer' | 'face_tool' | 'shirt_tool';
type WearMode = 'template';
type BgMode = 'transparent' | 'white_df11' | 'pearl_studio' | 'stadium_bokeh' | 'tunnel_club' | 'office_staff' | 'custom';
type ExportTarget = 'creations' | 'facepack';

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
};

interface PercentStepperProps {
  sessionPrefix: string;
  label: string;
  sliderAriaLabel: string;
  inputAriaLabel: string;
  upAriaLabel: string;
  downAriaLabel: string;
  titleHint?: string;
  value: number;
  minPct: number;
  maxPct: number;
  onChangeValue: (nextRatio: number, sessionKey?: string) => void;
  onEndSession: (sessionKey?: string) => void;
}

function PercentStepperControl({
  sessionPrefix,
  label,
  sliderAriaLabel,
  inputAriaLabel,
  upAriaLabel,
  downAriaLabel,
  titleHint,
  value,
  minPct,
  maxPct,
  onChangeValue,
  onEndSession,
}: PercentStepperProps) {
  const pct = Math.round(value * 100);
  const [draft, setDraft] = useState(() => String(pct));
  const focusedRef = useRef(false);
  const sliderDragRef = useRef(false);
  const inputSessionKey = `${sessionPrefix}:input`;
  const sliderSessionKey = `${sessionPrefix}:slider`;

  useEffect(() => {
    if (!focusedRef.current) {
      setDraft(String(pct));
    }
  }, [pct]);

  const applyClampedPct = (rawPct: number, sessionKey?: string) => {
    const clamped = Math.min(maxPct, Math.max(minPct, Math.round(rawPct)));
    setDraft(String(clamped));
    onChangeValue(Number((clamped / 100).toFixed(2)), sessionKey);
  };

  return (
    <div title={titleHint} className="flex items-center gap-2 text-slate-700 dark:text-slate-300 tabular-nums">
      <span className="shrink-0 font-medium">{label}</span>
      <input
        aria-label={sliderAriaLabel}
        type="range"
        min={minPct}
        max={maxPct}
        step={1}
        value={pct}
        onPointerDown={() => {
          sliderDragRef.current = true;
          onEndSession();
        }}
        onPointerUp={() => {
          sliderDragRef.current = false;
          onEndSession(sliderSessionKey);
        }}
        onPointerCancel={() => {
          sliderDragRef.current = false;
          onEndSession(sliderSessionKey);
        }}
        onBlur={() => {
          sliderDragRef.current = false;
          onEndSession(sliderSessionKey);
        }}
        onChange={(e) => applyClampedPct(Number(e.target.value), sliderDragRef.current ? sliderSessionKey : undefined)}
        className="w-full min-w-[68px] accent-emerald-600"
      />
      <div className="shrink-0 inline-flex items-center">
        <div className="relative flex items-center">
          <input
            aria-label={inputAriaLabel}
            type="text"
            inputMode="numeric"
            value={draft}
            onFocus={() => {
              focusedRef.current = true;
              onEndSession();
            }}
            onChange={(e) => {
              const cleaned = e.target.value.replace(/[^0-9]/g, '').slice(0, 3);
              setDraft(cleaned);
              if (cleaned !== '') {
                const parsed = Number(cleaned);
                if (parsed >= minPct && parsed <= maxPct) {
                  onChangeValue(Number((parsed / 100).toFixed(2)), inputSessionKey);
                }
              }
            }}
            onBlur={() => {
              focusedRef.current = false;
              if (draft === '') {
                setDraft(String(pct));
                onEndSession(inputSessionKey);
                return;
              }
              applyClampedPct(Number(draft), inputSessionKey);
              onEndSession(inputSessionKey);
            }}
            onKeyDown={(e) => {
              if ((e.ctrlKey || e.metaKey) && (e.key.toLowerCase() === 'z' || e.key.toLowerCase() === 'y')) {
                e.currentTarget.blur();
                return;
              }
              if (e.key === 'Enter') {
                e.preventDefault();
                e.currentTarget.blur();
              } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                applyClampedPct((draft !== '' ? Number(draft) : pct) + 1, inputSessionKey);
              } else if (e.key === 'ArrowDown') {
                e.preventDefault();
                applyClampedPct((draft !== '' ? Number(draft) : pct) - 1, inputSessionKey);
              }
            }}
            className="w-14 pl-1.5 pr-4 py-1 text-right text-xs font-mono rounded-l-md border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-950 text-slate-900 dark:text-slate-100"
          />
          <span className="pointer-events-none absolute right-1 text-[10px] text-slate-400">%</span>
        </div>
        <div className="flex flex-col border border-l-0 border-slate-300 dark:border-slate-700 rounded-r-md overflow-hidden bg-slate-100 dark:bg-slate-800">
          <button
            type="button"
            aria-label={upAriaLabel}
            title={upAriaLabel}
            disabled={pct >= maxPct}
            onClick={() => applyClampedPct(pct + 1)}
            className="px-1 py-0.5 hover:bg-emerald-600 hover:text-white disabled:opacity-35 transition flex items-center justify-center"
          >
            <ChevronUp className="w-3 h-3" />
          </button>
          <button
            type="button"
            aria-label={downAriaLabel}
            title={downAriaLabel}
            disabled={pct <= minPct}
            onClick={() => applyClampedPct(pct - 1)}
            className="px-1 py-0.5 border-t border-slate-300 dark:border-slate-700 hover:bg-emerald-600 hover:text-white disabled:opacity-35 transition flex items-center justify-center"
          >
            <ChevronDown className="w-3 h-3" />
          </button>
        </div>
      </div>
    </div>
  );
}

export default function StudioView({
  clubs,
  onClubsUpdated,
  exportDir,
  facepackDir,
  onExportDirChange,
  onFacepackDirChange,
  initialJump,
  onConsumeJump,
}: Props) {
  const [toolTab, setToolTab] = useState<ToolTab>('composer');
  const [activeStep, setActiveStep] = useState<1 | 2 | 3 | 4>(1);
  const [step2Category, setStep2Category] = useState<TemplateCategory>('player');
  const [extractorInitCategory, setExtractorInitCategory] = useState<TemplateCategory>('player');

  const [templates, setTemplates] = useState<ShirtTemplateInfo[]>([]);
  const templatesRef = useRef<ShirtTemplateInfo[]>([]);
  const allowInitialAutoSelectRef = useRef(!initialJump);
  const [faces, setFaces] = useState<SavedFaceInfo[]>([]);

  const [history, setHistory] = useState<{
    past: LayerSnapshot[];
    present: LayerSnapshot;
    future: LayerSnapshot[];
    sessionKey: string | null;
  }>({
    past: [],
    present: INITIAL_SNAP,
    future: [],
    sessionKey: null,
  });
  const snap = history.present;

  // Inline pre-extraction wheel-crop state on the main 260x310 canvas
  const [cropStage, setCropStage] = useState<StagedFaceResponse | null>(null);
  const [cropVp, setCropVp] = useState<CropViewportDTO>({ zoom: 1, panX: 0, panY: 0 });
  const [removeBgCrop, setRemoveBgCrop] = useState(true);

  // Facepack Card Remix state (assembled FM facepack card)
  const [loadedFacepackCard, setLoadedFacepackCard] = useState<{
    label: string;
    detectedUid: string;
    mode: 'swap_shirt' | 'swap_face';
    headAssetId?: string;
    adhocShirtId?: string;
  } | null>(null);
  const [adhocShirtsById, setAdhocShirtsById] = useState<
    Record<string, { id: string; label: string; thumbDataUrl: string }>
  >({});
  const [latestAdhocShirtId, setLatestAdhocShirtId] = useState('');
  const adhocShirt = snap.templateId.startsWith('adhoc:')
    ? (adhocShirtsById[snap.templateId] ?? (latestAdhocShirtId ? adhocShirtsById[latestAdhocShirtId] : null) ?? null)
    : latestAdhocShirtId
    ? (adhocShirtsById[latestAdhocShirtId] ?? null)
    : null;

  const [previewUrl, setPreviewUrl] = useState('');
  const [busy, setBusy] = useState(false);
  const [errorMsg, setErrorMsg] = useState('');
  const [savedMsg, setSavedMsg] = useState('');
  const [showGuides, setShowGuides] = useState(true);
  const [stageSkin, setStageSkin] = useState<'fm_dark' | 'fm_light' | 'checker'>('fm_dark');
  const [hasExtractedBg, setHasExtractedBg] = useState(false);
  const [canExtractBg, setCanExtractBg] = useState(false);

  // Inline template rename/category/club/season/delete state in Paso 2
  const [tplNameDraft, setTplNameDraft] = useState('');
  const [tplCategoryDraft, setTplCategoryDraft] = useState<TemplateCategory>('player');
  const [tplClubDraft, setTplClubDraft] = useState('');
  const [tplClubNameDraft, setTplClubNameDraft] = useState('');
  const [tplSeasonDraft, setTplSeasonDraft] = useState('');
  const [tplActiveDraft, setTplActiveDraft] = useState(true);
  const [step2Search, setStep2Search] = useState('');
  const [confirmDeleteTpl, setConfirmDeleteTpl] = useState(false);

  // Paso 4 export options
  const [uid, setUid] = useState('');
  const [exportTarget, setExportTarget] = useState<ExportTarget>('creations');
  const [localFacepackDir, setLocalFacepackDir] = useState(facepackDir ?? '');
  const [fmt, setFmt] = useState<'png' | 'jpg'>('png');
  const [updateXml, setUpdateXml] = useState(true);

  useEffect(() => {
    if (facepackDir) setLocalFacepackDir(facepackDir);
  }, [facepackDir]);

  const effectiveFacepackDir = facepackDir || localFacepackDir;

  const dragRef = useRef<{ sx: number; sy: number; ox: number; oy: number; baseSnap?: LayerSnapshot } | null>(null);
  const bokehDragRef = useRef(false);
  const arrowBurstTsRef = useRef(0);
  const reqSeqRef = useRef(0);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const bgInputRef = useRef<HTMLInputElement>(null);
  const facepackInputRef = useRef<HTMLInputElement>(null);
  const pendingRemixModeRef = useRef<'swap_shirt' | 'swap_face'>('swap_shirt');

  const endEditSession = useCallback((sessionKey?: string) => {
    setHistory((h) => {
      if (!h.sessionKey) return h;
      if (sessionKey && h.sessionKey !== sessionKey) return h;
      return { ...h, sessionKey: null };
    });
  }, []);

  const commitSnap = useCallback((updater: (prev: LayerSnapshot) => LayerSnapshot) => {
    allowInitialAutoSelectRef.current = false;
    setHistory((h) => {
      const next = updater(h.present);
      if (JSON.stringify(next) === JSON.stringify(h.present)) {
        return h.sessionKey ? { ...h, sessionKey: null } : h;
      }
      const past = [...h.past.slice(-34), h.present];
      return { past, present: next, future: [], sessionKey: null };
    });
  }, []);

  const commitSessionSnap = useCallback(
    (sessionKey: string | undefined, updater: (prev: LayerSnapshot) => LayerSnapshot) => {
      if (!sessionKey) {
        commitSnap(updater);
        return;
      }
      allowInitialAutoSelectRef.current = false;
      setHistory((h) => {
        const next = updater(h.present);
        if (JSON.stringify(next) === JSON.stringify(h.present)) return h;
        if (h.sessionKey === sessionKey) {
          if (h.past.length > 0 && JSON.stringify(next) === JSON.stringify(h.past[h.past.length - 1])) {
            return { past: h.past.slice(0, -1), present: next, future: [], sessionKey: null };
          }
          return { ...h, present: next };
        }
        return { past: [...h.past.slice(-34), h.present], present: next, future: [], sessionKey };
      });
    },
    [commitSnap],
  );

  const replaceLiveSnap = useCallback((updater: (prev: LayerSnapshot) => LayerSnapshot) => {
    setHistory((h) => ({ ...h, present: updater(h.present) }));
  }, []);

  const handleUndo = useCallback(() => {
    arrowBurstTsRef.current = 0;
    setCropStage(null);
    setHistory((h) => {
      if (h.past.length === 0) return h;
      const prev = h.past[h.past.length - 1];
      return { past: h.past.slice(0, -1), present: prev, future: [h.present, ...h.future], sessionKey: null };
    });
  }, []);

  const handleRedo = useCallback(() => {
    arrowBurstTsRef.current = 0;
    setCropStage(null);
    setHistory((h) => {
      if (h.future.length === 0) return h;
      const [next, ...rest] = h.future;
      return { past: [...h.past, h.present], present: next, future: rest, sessionKey: null };
    });
  }, []);

  const handleClearCanvas = useCallback(() => {
    if (cropStage) {
      setCropStage(null);
      return;
    }
    if (!snap.headAssetId) return;
    if (!snap.templateId) {
      setPreviewUrl('');
    }
    setCanExtractBg(false);
    commitSnap((s) => ({
      ...s,
      headAssetId: '',
      faceLabel: '',
      scale: 1.0,
      offsetX: 0,
      offsetY: 0,
    }));
  }, [cropStage, snap.headAssetId, snap.templateId, commitSnap]);

  const handleTemplatesUpdated = useCallback((nextTemplates: ShirtTemplateInfo[]) => {
    const prevTemplates = templatesRef.current;
    templatesRef.current = nextTemplates;
    setTemplates(nextTemplates);
    setConfirmDeleteTpl(false);
    const shouldSeedInitialPlayer = allowInitialAutoSelectRef.current;
    if (nextTemplates.length > 0) {
      allowInitialAutoSelectRef.current = false;
    }
    setHistory((h) => {
      const validIds = new Set(nextTemplates.map((t) => t.templateId));
      const firstPlayer = nextTemplates.find((t) => (t.category ?? 'player') === 'player');
      const firstStaff = nextTemplates.find((t) => t.category === 'staff');
      let changed = false;
      const fixDeletedSnap = (sn: LayerSnapshot): LayerSnapshot => {
        if (!sn.templateId || sn.templateId.startsWith('adhoc:') || validIds.has(sn.templateId)) {
          return sn;
        }
        const prevCat = prevTemplates.find((t) => t.templateId === sn.templateId)?.category ?? 'player';
        const replacementTid = prevCat === 'staff' ? (firstStaff?.templateId ?? '') : (firstPlayer?.templateId ?? '');
        if (sn.templateId === replacementTid) return sn;
        changed = true;
        return { ...sn, templateId: replacementTid };
      };
      let nextPresent = fixDeletedSnap(h.present);
      if (
        shouldSeedInitialPlayer &&
        !nextPresent.templateId &&
        !nextPresent.headAssetId &&
        h.past.length === 0 &&
        firstPlayer
      ) {
        changed = true;
        nextPresent = { ...nextPresent, templateId: firstPlayer.templateId };
      }
      const nextPast = h.past.map(fixDeletedSnap);
      const nextFuture = h.future.map(fixDeletedSnap);
      return changed ? { ...h, past: nextPast, present: nextPresent, future: nextFuture } : h;
    });
  }, []);

  const loadInitialCatalogs = useCallback(() => {
    void callBridge<ShirtTemplateInfo[]>('list_shirt_templates')
      .then((tpls) => {
        if (Array.isArray(tpls)) handleTemplatesUpdated(tpls);
      })
      .catch(() => {});
    void callBridge<SavedFaceInfo[]>('list_saved_faces')
      .then((fcs) => {
        if (Array.isArray(fcs)) setFaces(fcs);
      })
      .catch(() => {});
  }, [handleTemplatesUpdated]);

  // Load templates & saved faces on mount and on pywebviewready
  useEffect(() => {
    loadInitialCatalogs();
    window.addEventListener('pywebviewready', loadInitialCatalogs);
    return () => window.removeEventListener('pywebviewready', loadInitialCatalogs);
  }, [loadInitialCatalogs]);

  // Sync inline template name/category/club/season drafts when selected template changes
  useEffect(() => {
    if (snap.templateId.startsWith('adhoc:')) return;
    const active = templates.find((t) => t.templateId === snap.templateId);
    setTplNameDraft(active?.displayName ?? '');
    setTplCategoryDraft(active?.category === 'staff' ? 'staff' : 'player');
    setTplClubDraft(active?.clubId ?? '');
    setTplClubNameDraft(active?.clubName || (active?.clubId ? clubs[active.clubId]?.name ?? '' : ''));
    setTplSeasonDraft(active?.season ?? '');
    setTplActiveDraft(active?.clubId ? active.isActiveForClub !== false : true);
    setConfirmDeleteTpl(false);
  }, [templates, snap.templateId, clubs]);

  // Handle jump from NG_Regens Sync tab
  useEffect(() => {
    if (!initialJump) return;
    allowInitialAutoSelectRef.current = false;
    setLoadedFacepackCard(null);
    setLatestAdhocShirtId('');
    setToolTab('composer');
    setActiveStep(1);
    setCropStage(null);
    setUid(initialJump.uid);
    setPreviewUrl(initialJump.previewDataUrl);
    setCanExtractBg(!initialJump.isPreCutout);
    const jumpClubId = (initialJump.clubId ?? '').replace(/[^0-9]/g, '').slice(0, 12);
    const matchedTpl = initialJump.matchedTemplateId
      ? templatesRef.current.find((t) => t.templateId === initialJump.matchedTemplateId) ?? {
          templateId: initialJump.matchedTemplateId,
          category: 'player' as TemplateCategory,
        }
      : jumpClubId
      ? templates.find(
          (t) => t.clubId === jumpClubId && (t.category ?? 'player') === 'player' && t.isActiveForClub !== false,
        ) || templates.find((t) => t.clubId === jumpClubId && (t.category ?? 'player') === 'player')
      : undefined;
    setStep2Category(matchedTpl?.category === 'staff' ? 'staff' : 'player');
    commitSnap((s) => ({
      ...s,
      headAssetId: initialJump.headAssetId ?? 'legacy-jump',
      faceLabel: initialJump.uid,
      wearMode: 'template',
      templateId: matchedTpl ? matchedTpl.templateId : '',
      clubId: jumpClubId || s.clubId,
      scale: initialJump.autoFit?.scale ?? 1.0,
      offsetX: initialJump.autoFit?.offsetX ?? 0,
      offsetY: initialJump.autoFit?.offsetY ?? 0,
      neckFill: initialJump.autoFit?.neckFill ?? 1.0,
      bgMode: 'white_df11',
      bgBlur: 0,
    }));
    onConsumeJump?.();
  }, [initialJump, clubs, templates, commitSnap, onConsumeJump]);

  const hasComposition = Boolean(snap.headAssetId || snap.templateId);

  const composePayload = useMemo(
    () => ({
      modular: true,
      headAssetId: snap.headAssetId === 'legacy-jump' ? '' : snap.headAssetId,
      wearMode: 'template' as const,
      templateId: snap.templateId,
      clubId: snap.clubId || '1736',
      scale: snap.scale,
      offsetX: snap.offsetX,
      offsetY: snap.offsetY,
      neckFill: snap.neckFill,
      harmonize: snap.harmonize,
      bgMode: snap.bgMode,
      bgBlur: snap.bgBlur,
    }),
    [snap],
  );

  // Live modular preview when layers/fit/background change
  useEffect(() => {
    if (cropStage) return undefined;
    if (!snap.headAssetId && !snap.templateId) {
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
  }, [cropStage, snap.headAssetId, snap.templateId, composePayload]);

  const openStagedCrop = useCallback((staged: StagedFaceResponse) => {
    setActiveStep(1);
    setCropStage(staged);
    setCropVp(staged.suggestedViewport);
    setCanExtractBg(!staged.isPreCutout);
    setErrorMsg('');
    setSavedMsg('');
  }, []);

  const handleFileBlob = useCallback(
    async (file: File) => {
      if (busy) return;
      if (file.size > 20 * 1024 * 1024) {
        setErrorMsg('El archivo supera el límite máximo permitido de 20 MB.');
        return;
      }
      setErrorMsg('');
      setSavedMsg('');
      setBusy(true);
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
    [busy, openStagedCrop],
  );

  const handlePickPortrait = useCallback(async () => {
    setActiveStep(1);
    if (window.pywebview?.api?.pick_raw_face_source) {
      setErrorMsg('');
      setSavedMsg('');
      setBusy(true);
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
      setErrorMsg('');
      setSavedMsg('');
      setBusy(true);
      try {
        const out = await callBridge<{ previewDataUrl: string; isPreCutout?: boolean } | null>(
          'pick_and_upload_studio_image',
          true,
          snap.harmonize,
          false,
          {},
        );
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
    setBusy(true);
    setErrorMsg('');
    try {
      const res = await callBridge<ExtractedFaceResponse>('extract_face_from_crop', {
        zoom: cropVp.zoom,
        panX: cropVp.panX,
        panY: cropVp.panY,
        removeBg: removeBgCrop,
        templateId: snap.templateId,
        wearMode: 'template',
        bgMode: snap.bgMode,
        bgBlur: snap.bgBlur,
        harmonize: snap.harmonize,
      });
      reqSeqRef.current += 1;
      setActiveStep(1);
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
  }, [cropStage, cropVp, removeBgCrop, snap.templateId, snap.bgMode, snap.bgBlur, snap.harmonize, commitSnap]);

  const handlePickSavedFace = useCallback(
    async (faceId: string) => {
      setBusy(true);
      setErrorMsg('');
      setToolTab('composer');
      setActiveStep(1);
      setCropStage(null);
      try {
        const res = await callBridge<{
          headAssetId: string;
          name: string;
          isPreCutout?: boolean;
          autoFit: { scale: number; offsetX: number; offsetY: number; neckFill: number };
          previewDataUrl: string;
        }>('load_saved_face', faceId, snap.templateId, composePayload);
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
    [snap.templateId, composePayload, commitSnap],
  );

  const applyFacepackRemixResult = useCallback(
    (res: FacepackRemixResponse, isSameCardSwitch: boolean) => {
      reqSeqRef.current += 1;
      setCropStage(null);
      setErrorMsg('');
      if (res.detectedUid) {
        setUid(res.detectedUid);
      }
      if (res.facepackDir) {
        setLocalFacepackDir(res.facepackDir);
        onFacepackDirChange?.(res.facepackDir);
        setExportTarget('facepack');
        setFmt('png');
      }
      setLoadedFacepackCard((prev) => ({
        label: res.cardLabel || res.detectedUid || 'Ficha FM',
        detectedUid: res.detectedUid ?? '',
        mode: res.remixMode,
        headAssetId: isSameCardSwitch ? (res.headAssetId || prev?.headAssetId) : res.headAssetId,
        adhocShirtId: isSameCardSwitch ? (res.adhocShirtId || prev?.adhocShirtId) : res.adhocShirtId,
      }));

      if (res.remixMode === 'swap_face' && res.adhocShirtId) {
        const entry = {
          id: res.adhocShirtId,
          label: res.adhocShirtLabel || `Camiseta ficha ${res.cardLabel}`,
          thumbDataUrl: res.adhocShirtThumbDataUrl || '',
        };
        setAdhocShirtsById((prev) => ({ ...prev, [entry.id]: entry }));
        setLatestAdhocShirtId(entry.id);
        if (res.previewDataUrl) setPreviewUrl(res.previewDataUrl);
        commitSnap((s) => ({
          ...s,
          wearMode: 'template',
          templateId: res.adhocShirtId!,
          scale: res.autoFit?.scale ?? s.scale,
          offsetX: res.autoFit?.offsetX ?? s.offsetX,
          offsetY: res.autoFit?.offsetY ?? s.offsetY,
          neckFill: res.autoFit?.neckFill ?? s.neckFill,
        }));
        setSavedMsg(`Camiseta aislada de ${res.cardLabel}. Elige ahora cualquier cara en el Paso 1.`);
        return;
      }

      if (!isSameCardSwitch) {
        setLatestAdhocShirtId('');
      }
      setActiveStep(1);
      setCanExtractBg(!res.isPreCutout);
      if (res.previewDataUrl) setPreviewUrl(res.previewDataUrl);
      const fallbackPrevTid = snap.templateId.startsWith('adhoc:') ? '' : snap.templateId;
      const nextTid = res.templateId !== undefined ? res.templateId : fallbackPrevTid;
      const foundTpl = templatesRef.current.find((t) => t.templateId === nextTid);
      if (foundTpl) {
        setStep2Category((foundTpl.category ?? 'player') === 'staff' ? 'staff' : 'player');
      }
      commitSnap((s) => ({
        ...s,
        wearMode: 'template',
        headAssetId: res.headAssetId || s.headAssetId,
        faceLabel: `Ficha FM ${res.cardLabel}`,
        templateId: nextTid,
        scale: res.autoFit?.scale ?? 1.0,
        offsetX: res.autoFit?.offsetX ?? 0.0,
        offsetY: res.autoFit?.offsetY ?? 0.0,
        neckFill: res.autoFit?.neckFill ?? 1.0,
      }));
      setSavedMsg(`Cabeza y cuello extraídos de ${res.cardLabel}. Elige su nueva equipación en el Paso 2.`);
    },
    [onFacepackDirChange, snap.templateId, commitSnap],
  );

  const handlePickFacepackCard = useCallback(
    async (mode: 'swap_shirt' | 'swap_face') => {
      if (busy) return;
      if (!window.pywebview?.api?.pick_facepack_card) {
        pendingRemixModeRef.current = mode;
        facepackInputRef.current?.click();
        return;
      }
      setBusy(true);
      setErrorMsg('');
      setSavedMsg('');
      try {
        const reqTemplateId = snap.templateId.startsWith('adhoc:') ? '' : snap.templateId;
        const res = await callBridge<FacepackRemixResponse | null>(
          'pick_facepack_card',
          mode,
          reqTemplateId,
          composePayload,
        );
        if (res) applyFacepackRemixResult(res, false);
      } catch (e) {
        setErrorMsg(e instanceof Error ? e.message : 'No se pudo cargar la ficha del Pack de Faces.');
      } finally {
        setBusy(false);
      }
    },
    [busy, snap.templateId, composePayload, applyFacepackRemixResult],
  );

  const handleFacepackFileBlob = useCallback(
    async (file: File, mode: 'swap_shirt' | 'swap_face') => {
      if (busy) return;
      if (file.size > 20 * 1024 * 1024) {
        setErrorMsg('El archivo supera el límite máximo permitido de 20 MB.');
        return;
      }
      setBusy(true);
      setErrorMsg('');
      setSavedMsg('');
      try {
        const dataUrl = await new Promise<string>((res, rej) => {
          const r = new FileReader();
          r.onload = () => res(String(r.result));
          r.onerror = () => rej(new Error('No se pudo leer la ficha.'));
          r.readAsDataURL(file);
        });
        const reqTemplateId = snap.templateId.startsWith('adhoc:') ? '' : snap.templateId;
        const out = await callBridge<FacepackRemixResponse>(
          'load_facepack_card',
          dataUrl,
          file.name,
          mode,
          reqTemplateId,
          composePayload,
        );
        if (out) applyFacepackRemixResult(out, false);
      } catch (e) {
        setErrorMsg(e instanceof Error ? e.message : 'No se pudo desmontar la ficha de Football Manager.');
      } finally {
        setBusy(false);
      }
    },
    [busy, snap.templateId, composePayload, applyFacepackRemixResult],
  );

  const isUsingCardFace = Boolean(
    loadedFacepackCard?.headAssetId &&
      snap.headAssetId === loadedFacepackCard.headAssetId &&
      !snap.templateId.startsWith('adhoc:'),
  );
  const isUsingCardShirt = Boolean(
    loadedFacepackCard?.adhocShirtId && snap.templateId === loadedFacepackCard.adhocShirtId,
  );

  const handleSwitchFacepackMode = useCallback(
    async (mode: 'swap_shirt' | 'swap_face') => {
      if (busy || !loadedFacepackCard) return;
      if (mode === 'swap_shirt' && isUsingCardFace) return;
      if (mode === 'swap_face' && isUsingCardShirt) return;
      setBusy(true);
      setErrorMsg('');
      try {
        const targetTpl = snap.templateId.startsWith('adhoc:')
          ? (templatesRef.current.find((t) => (t.category ?? 'player') === step2Category)?.templateId ?? '')
          : snap.templateId;
        const res = await callBridge<FacepackRemixResponse>(
          'switch_facepack_remix_mode',
          mode,
          targetTpl,
          composePayload,
        );
        if (res) applyFacepackRemixResult(res, true);
      } catch (e) {
        setErrorMsg(e instanceof Error ? e.message : 'No se pudo cambiar el modo de edición de la ficha.');
      } finally {
        setBusy(false);
      }
    },
    [
      busy,
      loadedFacepackCard,
      isUsingCardFace,
      isUsingCardShirt,
      snap.templateId,
      step2Category,
      composePayload,
      applyFacepackRemixResult,
    ],
  );

  const handleSaveAdhocShirt = async () => {
    if (!adhocShirt || busy) return;
    setBusy(true);
    setErrorMsg('');
    try {
      const res = await callBridge<{
        savedTemplateId: string;
        templates: ShirtTemplateInfo[];
        clubs?: Record<string, ClubSeed>;
      }>('save_adhoc_shirt_template', {
        adhocShirtId: adhocShirt.id,
        displayName: adhocShirt.label,
        category: step2Category,
      });
      if (res?.clubs) onClubsUpdated?.(res.clubs);
      if (Array.isArray(res?.templates)) handleTemplatesUpdated(res.templates);
      if (res?.savedTemplateId) {
        setLatestAdhocShirtId('');
        commitSnap((s) => ({ ...s, templateId: res.savedTemplateId }));
        setSavedMsg(`Camiseta guardada en plantillas (${step2Category === 'staff' ? 'Staff' : 'Plantilla'}): ${res.savedTemplateId}.png`);
      }
    } catch (e) {
      setErrorMsg(e instanceof Error ? e.message : 'No se pudo guardar la camiseta en tshirt_templates.');
    } finally {
      setBusy(false);
    }
  };

  const handleSelectTemplate = useCallback(
    async (templateId: string) => {
      setToolTab('composer');
      setErrorMsg('');
      const meta = templatesRef.current.find((t) => t.templateId === templateId);
      if (meta) {
        setStep2Category((meta.category ?? 'player') === 'staff' ? 'staff' : 'player');
      }
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

  const sortedClubs = useMemo(
    () => Object.entries(clubs).sort((a, b) => a[1].name.localeCompare(b[1].name, 'es')),
    [clubs],
  );

  const filteredStep2Templates = useMemo(() => {
    const q = step2Search.trim().toLowerCase().replace(/^#/, '');
    return templates.filter((t) => {
      const cat = t.category ?? 'player';
      if (cat !== step2Category) return false;
      if (!q) return true;
      const cName = (t.clubName || (t.clubId ? clubs[t.clubId]?.name ?? '' : '')).toLowerCase();
      return (
        t.displayName.toLowerCase().includes(q) ||
        t.templateId.toLowerCase().includes(q) ||
        t.clubId.toLowerCase().includes(q) ||
        cName.includes(q) ||
        (t.season || '').toLowerCase().includes(q)
      );
    });
  }, [templates, step2Category, step2Search, clubs]);

  const handleSaveTemplateMeta = async () => {
    if (!snap.templateId || snap.templateId.startsWith('adhoc:')) return;
    setBusy(true);
    setErrorMsg('');
    try {
      const res = await callBridge<{ templates: ShirtTemplateInfo[]; clubs?: Record<string, ClubSeed> }>(
        'update_shirt_template_meta',
        {
          templateId: snap.templateId,
          displayName: tplNameDraft,
          category: tplCategoryDraft,
          clubId: tplClubDraft,
          clubName: tplClubNameDraft,
          season: tplSeasonDraft,
          isActiveForClub: tplActiveDraft,
        },
      );
      if (res?.clubs) onClubsUpdated?.(res.clubs);
      if (Array.isArray(res?.templates)) handleTemplatesUpdated(res.templates);
      setStep2Category(tplCategoryDraft);
      setSavedMsg(`Plantilla actualizada: ${tplNameDraft || snap.templateId}`);
    } catch (e) {
      setErrorMsg(e instanceof Error ? e.message : 'No se pudo actualizar la plantilla.');
    } finally {
      setBusy(false);
    }
  };

  const handleDeleteCurrentTemplate = async () => {
    if (!snap.templateId || snap.templateId.startsWith('adhoc:') || busy) return;
    const targetTid = snap.templateId;
    setBusy(true);
    setErrorMsg('');
    try {
      const res = await callBridge<{ deletedTemplateId: string; templates: ShirtTemplateInfo[] }>(
        'delete_shirt_template',
        targetTid,
      );
      if (Array.isArray(res?.templates)) handleTemplatesUpdated(res.templates);
      setConfirmDeleteTpl(false);
      setSavedMsg(`Plantilla eliminada: ${res?.deletedTemplateId ?? targetTid}`);
    } catch (e) {
      setErrorMsg(e instanceof Error ? e.message : 'No se pudo eliminar la plantilla.');
    } finally {
      setBusy(false);
    }
  };

  // Keyboard shortcuts: Paso 1 directional arrows, Ctrl+Z (Undo), Ctrl+Y / Ctrl+Shift+Z (Redo), Delete/Suprimir, Enter (Apply Crop)
  useEffect(() => {
    if (toolTab !== 'composer') return undefined;
    const nonTextTypes = new Set(['range', 'checkbox', 'radio', 'button', 'color', 'file']);
    const onKeyDown = (ev: KeyboardEvent) => {
      if (busy || document.querySelector('[role="dialog"]')) return;
      const el = ev.target as HTMLElement | null;
      if (el?.isContentEditable) return;
      const tag = el?.tagName?.toLowerCase();
      if (tag === 'textarea' || tag === 'select') return;

      const inputType = tag === 'input' ? ((el as HTMLInputElement).type || 'text').toLowerCase() : '';
      const blocksDirectionalArrows =
        tag === 'input' && !['checkbox', 'radio', 'button', 'color', 'file'].includes(inputType);

      // Directional arrow keys move head/crop when Paso 1 is active and focus is NOT on a text/numeric/range input
      if (
        activeStep === 1 &&
        !blocksDirectionalArrows &&
        (ev.key === 'ArrowLeft' || ev.key === 'ArrowRight' || ev.key === 'ArrowUp' || ev.key === 'ArrowDown')
      ) {
        const step = ev.shiftKey ? 5 : 1;
        const dx = ev.key === 'ArrowLeft' ? -step : ev.key === 'ArrowRight' ? step : 0;
        const dy = ev.key === 'ArrowUp' ? -step : ev.key === 'ArrowDown' ? step : 0;
        if (cropStage) {
          ev.preventDefault();
          setCropVp((v) => ({ ...v, panX: v.panX + dx, panY: v.panY + dy }));
          return;
        }
        if (snap.headAssetId) {
          ev.preventDefault();
          const now = Date.now();
          const shouldPush = now - arrowBurstTsRef.current > 450;
          arrowBurstTsRef.current = now;
          setHistory((h) => {
            const next: LayerSnapshot = {
              ...h.present,
              offsetX: h.present.offsetX + dx,
              offsetY: h.present.offsetY + dy,
            };
            return shouldPush
              ? { past: [...h.past.slice(-34), h.present], present: next, future: [], sessionKey: null }
              : { ...h, present: next, sessionKey: null };
          });
          return;
        }
      }

      if (tag === 'input' && !nonTextTypes.has(((el as HTMLInputElement).type || 'text').toLowerCase())) return;
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
      } else if (ev.key === 'Enter' && cropStage) {
        ev.preventDefault();
        void handleConfirmCropAndExtract();
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [
    toolTab,
    activeStep,
    cropStage,
    snap.headAssetId,
    busy,
    handleUndo,
    handleRedo,
    handleClearCanvas,
    handleConfirmCropAndExtract,
  ]);

  useEffect(() => {
    if (toolTab !== 'composer') return undefined;
    const onPaste = (ev: ClipboardEvent) => {
      if (busy || document.querySelector('[role="dialog"]')) return;
      const f = Array.from(ev.clipboardData?.items ?? [])
        .find((i) => i.type.startsWith('image/'))
        ?.getAsFile();
      if (f) void handleFileBlob(f);
    };
    window.addEventListener('paste', onPaste);
    return () => window.removeEventListener('paste', onPaste);
  }, [toolTab, busy, handleFileBlob]);

  const handlePickCustomBg = useCallback(async () => {
    if (!window.pywebview?.api?.pick_and_upload_custom_background) {
      bgInputRef.current?.click();
      return;
    }
    setErrorMsg('');
    setBusy(true);
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
    setErrorMsg('');
    setBusy(true);
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
    setErrorMsg('');
    setBusy(true);
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

  const handleChooseFacepackFolder = async (): Promise<string> => {
    try {
      const p = await callBridge<{ path: string; storageHealth?: StorageHealth } | null>('choose_directory', 'facepack');
      if (p?.path) {
        setLocalFacepackDir(p.path);
        onFacepackDirChange?.(p.path);
        return p.path;
      }
    } catch (e) {
      setErrorMsg(e instanceof Error ? e.message : 'Carpeta de Pack de Faces no válida.');
    }
    return '';
  };

  const uidInvalid = uid.trim().length > 0 && !UID_RE.test(uid.trim());

  const handleExport = async () => {
    const cleanUid = uid.trim();
    if (!UID_RE.test(cleanUid)) {
      setErrorMsg('Introduce el ID asignado al futbolista (dígitos o r-<dígitos>, máx. 12 cifras).');
      return;
    }
    let activeFpDir = effectiveFacepackDir;
    if (exportTarget === 'facepack' && !activeFpDir) {
      activeFpDir = await handleChooseFacepackFolder();
      if (!activeFpDir) {
        setErrorMsg('Indica primero la carpeta del Pack de Faces de Football Manager.');
        return;
      }
    }
    setBusy(true);
    setErrorMsg('');
    try {
      const effectiveFmt = exportTarget === 'facepack' ? 'png' : fmt;
      const method = snap.headAssetId === 'legacy-jump' ? 'export_studio_card' : 'export_modular_card';
      const res = await callBridge<{ savedPath: string }>(method, {
        uid: cleanUid,
        fmt: effectiveFmt,
        exportTarget,
        outDir: exportTarget === 'facepack' ? activeFpDir : undefined,
        updateConfigXml: updateXml,
        ...composePayload,
      });
      setSavedMsg(`Guardado: ${res.savedPath ?? `${cleanUid}.${effectiveFmt}`}`);
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
          <button
            type="button"
            role="tab"
            aria-selected={toolTab === 'composer'}
            onClick={() => setToolTab('composer')}
            className={toolBtn(toolTab === 'composer')}
          >
            <Layers className="w-4 h-4" /> Montaje Paso a Paso
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={toolTab === 'face_tool'}
            onClick={() => setToolTab('face_tool')}
            className={toolBtn(toolTab === 'face_tool')}
          >
            <Scissors className="w-4 h-4" /> Extraer Cara
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={toolTab === 'shirt_tool'}
            onClick={() => {
              setExtractorInitCategory(step2Category);
              setToolTab('shirt_tool');
            }}
            className={toolBtn(toolTab === 'shirt_tool')}
          >
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
          activeTemplateId={snap.templateId}
          onFacesUpdated={setFaces}
          onUseExtractedFace={(payload) => {
            setToolTab('composer');
            setActiveStep(1);
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
          initialCategory={extractorInitCategory}
          onTemplatesUpdated={handleTemplatesUpdated}
          onClubsUpdated={onClubsUpdated}
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
                  disabled={!cropStage && !snap.headAssetId}
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
                  setActiveStep(1);
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
                  setActiveStep(1);
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
                        : { past: [...h.past.slice(-34), prevBase], present: h.present, future: [], sessionKey: null },
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
                        className="absolute inset-0 w-[260px] h-[310px] opacity-75 pointer-events-none"
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
                    Zona de corte ({Math.round(cropVp.zoom * 100)}%) {crownRisk ? '· ¡Tope cabeza!' : '· Rueda / ←↑↓→'}
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
                <button type="button" onClick={() => setStageSkin('fm_dark')} className={segBtn(stageSkin === 'fm_dark')}>
                  Skin Oscura
                </button>
                <button type="button" onClick={() => setStageSkin('fm_light')} className={segBtn(stageSkin === 'fm_light')}>
                  Skin Clara
                </button>
                <button type="button" onClick={() => setStageSkin('checker')} className={segBtn(stageSkin === 'checker')}>
                  Alfa 0
                </button>
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
            <div
              onClick={() => setActiveStep(1)}
              className={`p-4 space-y-3 rounded-t-xl transition ${
                activeStep === 1 ? 'bg-emerald-50/35 dark:bg-emerald-950/15' : ''
              }`}
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <div className="flex items-center gap-2">
                    <h2 className="text-xs font-semibold uppercase tracking-wider text-emerald-700 dark:text-emerald-400 cursor-pointer">
                      Paso 1 · Capa Cara y Cuello
                    </h2>
                    <span
                      className={`text-[10px] px-1.5 py-0.5 rounded font-medium border ${
                        activeStep === 1
                          ? 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 border-emerald-500/30'
                          : 'bg-slate-100 dark:bg-slate-800 text-slate-500 border-slate-200 dark:border-slate-700'
                      }`}
                    >
                      {activeStep === 1 ? 'Activo · Ratón o ←↑↓→' : 'Clic para mover con ←↑↓→'}
                    </span>
                  </div>
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
                  <input
                    ref={facepackInputRef}
                    type="file"
                    accept="image/*"
                    className="hidden"
                    onChange={(e) => {
                      const f = e.target.files?.[0];
                      e.target.value = '';
                      if (f) void handleFacepackFileBlob(f, pendingRemixModeRef.current);
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
                    disabled={!snap.headAssetId || !snap.templateId}
                    onClick={() => snap.templateId && void handleSelectTemplate(snap.templateId)}
                    className="px-2.5 py-1.5 text-xs rounded-md bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 disabled:opacity-40 inline-flex items-center gap-1"
                    title="Auto-encajar cabeza y cuello a la camiseta activa"
                  >
                    <RotateCcw className="w-3.5 h-3.5" /> Auto-encajar
                  </button>
                </div>
              </div>

              {/* Facepack Card Remix Bar */}
              <div className="rounded-lg border border-slate-200/80 dark:border-slate-800 bg-slate-50/80 dark:bg-slate-950/60 p-2.5 space-y-2 text-xs">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="font-medium text-slate-700 dark:text-slate-300 inline-flex items-center gap-1.5">
                    <RefreshCw className="w-3.5 h-3.5 text-emerald-500" /> Ficha ya montada del Pack de Faces FM:
                  </span>
                  <div className="flex flex-wrap items-center gap-1.5">
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => void handlePickFacepackCard('swap_shirt')}
                      className="px-2.5 py-1 rounded-md border border-emerald-500/40 bg-emerald-500/10 hover:bg-emerald-500/20 text-emerald-800 dark:text-emerald-300 font-medium transition"
                    >
                      Cambiar camiseta a ficha FM
                    </button>
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => void handlePickFacepackCard('swap_face')}
                      className="px-2.5 py-1 rounded-md border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 hover:border-emerald-500 text-slate-700 dark:text-slate-300 font-medium transition"
                    >
                      Cambiar cara (conservar su camiseta)
                    </button>
                  </div>
                </div>
                {loadedFacepackCard && (
                  <div className="flex flex-wrap items-center justify-between gap-2 pt-1.5 border-t border-slate-200/70 dark:border-slate-800 text-[11px]">
                    <span className="text-slate-600 dark:text-slate-400 font-mono truncate">
                      Ficha cargada: {loadedFacepackCard.label}
                    </span>
                    <div className="flex items-center gap-1">
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => void handleSwitchFacepackMode('swap_shirt')}
                        className={segBtn(isUsingCardFace)}
                      >
                        Usar su cara
                      </button>
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => void handleSwitchFacepackMode('swap_face')}
                        className={segBtn(isUsingCardShirt)}
                      >
                        Usar su camiseta
                      </button>
                    </div>
                  </div>
                )}
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
                <label className="sm:col-span-2 inline-flex items-center gap-2 text-slate-700 dark:text-slate-300">
                  <input
                    type="checkbox"
                    checked={snap.harmonize}
                    onChange={(e) => commitSnap((s) => ({ ...s, harmonize: e.target.checked }))}
                    className="accent-emerald-600"
                  />
                  Luz DF11
                </label>
                <div className="sm:col-span-5">
                  <PercentStepperControl
                    sessionPrefix="zoom"
                    label="Zoom"
                    sliderAriaLabel="Barra de Zoom de cabeza"
                    inputAriaLabel="Valor exacto de Zoom (%)"
                    upAriaLabel="Subir Zoom"
                    downAriaLabel="Bajar Zoom"
                    value={snap.scale}
                    minPct={15}
                    maxPct={220}
                    onChangeValue={(nextScale, skey) => commitSessionSnap(skey, (s) => ({ ...s, scale: nextScale }))}
                    onEndSession={endEditSession}
                  />
                </div>
                <div className="sm:col-span-5">
                  <PercentStepperControl
                    sessionPrefix="neck"
                    label="Cuello"
                    sliderAriaLabel="Barra de engrosamiento de cuello"
                    inputAriaLabel="Valor exacto de Cuello (%)"
                    upAriaLabel="Subir Cuello"
                    downAriaLabel="Bajar Cuello"
                    titleHint={
                      !snap.templateId ? 'Se aplica al engarzar la cabeza con la camiseta o traje del Paso 2' : undefined
                    }
                    value={snap.neckFill}
                    minPct={0}
                    maxPct={150}
                    onChangeValue={(nextNeck, skey) => commitSessionSnap(skey, (s) => ({ ...s, neckFill: nextNeck }))}
                    onEndSession={endEditSession}
                  />
                </div>
              </div>
            </div>

            {/* PASO 2: CAMISETA PLANTILLA / STAFF */}
            <div onClick={() => setActiveStep(2)} className="p-4 space-y-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h2 className="text-xs font-semibold uppercase tracking-wider text-emerald-700 dark:text-emerald-400">
                  Paso 2 · Capa Camiseta Plantilla
                </h2>
                <div className="flex flex-wrap items-center gap-1" role="group" aria-label="Categoría de equipación en Paso 2">
                  <button
                    type="button"
                    onClick={() => setStep2Category('player')}
                    className={segBtn(step2Category === 'player')}
                  >
                    Plantilla
                  </button>
                  <button
                    type="button"
                    onClick={() => setStep2Category('staff')}
                    className={segBtn(step2Category === 'staff')}
                  >
                    Staff
                  </button>
                </div>
              </div>

              <div className="space-y-2.5">
                {adhocShirt && (
                  <div
                    className={`p-2.5 rounded-lg border flex flex-wrap items-center justify-between gap-2 text-xs ${
                      snap.templateId === adhocShirt.id
                        ? 'border-emerald-500 bg-emerald-50/60 dark:bg-emerald-950/30'
                        : 'border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950/50'
                    }`}
                  >
                    <button
                      type="button"
                      onClick={() => void handleSelectTemplate(adhocShirt.id)}
                      className="inline-flex items-center gap-2 text-left cursor-pointer"
                    >
                      {adhocShirt.thumbDataUrl && (
                        <img src={adhocShirt.thumbDataUrl} alt={adhocShirt.label} className="w-10 h-10 object-contain rounded bg-[#0f172a]" />
                      )}
                      <div>
                        <div className="font-medium text-slate-900 dark:text-slate-100">{adhocShirt.label}</div>
                        <div className="text-[11px] text-emerald-700 dark:text-emerald-400">
                          Camiseta original aislada de la ficha del Pack de Faces
                        </div>
                      </div>
                    </button>
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => void handleSaveAdhocShirt()}
                      className="px-2.5 py-1 rounded-md bg-slate-800 hover:bg-slate-700 dark:bg-slate-700 dark:hover:bg-slate-600 text-white font-medium inline-flex items-center gap-1"
                    >
                      <Save className="w-3 h-3" /> Guardar en plantillas
                    </button>
                  </div>
                )}

                {templates.length > 0 && (
                  <div className="relative text-xs">
                    <Search className="w-3.5 h-3.5 text-slate-400 absolute left-2.5 top-1/2 -translate-y-1/2 pointer-events-none" />
                    <input
                      aria-label="Buscar camiseta plantilla en montaje"
                      value={step2Search}
                      onChange={(e) => setStep2Search(e.target.value)}
                      placeholder={`Buscar en ${step2Category === 'staff' ? 'Staff' : 'Plantilla'} por nombre, club, #ID o temporada…`}
                      className="w-full pl-8 pr-3 py-1.5 rounded-md border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-950 text-slate-900 dark:text-slate-100"
                    />
                  </div>
                )}

                <div className="grid grid-cols-3 sm:grid-cols-5 gap-2 max-h-44 overflow-y-auto pr-1">
                  {filteredStep2Templates.map((t) => {
                    const active = t.templateId === snap.templateId;
                    const isTitular = Boolean(t.clubId) && t.isActiveForClub !== false;
                    return (
                      <button
                        key={t.templateId}
                        type="button"
                        onClick={() => void handleSelectTemplate(t.templateId)}
                        className={`p-1.5 rounded-lg border text-center flex flex-col items-center gap-0.5 transition ${
                          active
                            ? 'border-emerald-500 bg-emerald-50/60 dark:bg-emerald-950/30'
                            : 'border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950/50 hover:border-slate-400'
                        }`}
                      >
                        <div className="relative">
                          <img src={t.thumbDataUrl} alt={t.displayName} className="w-12 h-12 object-contain rounded bg-[#0f172a]" />
                          {t.clubId && (
                            <span
                              className={`absolute -top-1 -right-1 text-[8px] px-1 rounded font-semibold ${
                                isTitular ? 'bg-emerald-600 text-white' : 'bg-slate-700 text-slate-200'
                              }`}
                            >
                              {isTitular ? '★' : 'H'}
                            </span>
                          )}
                        </div>
                        <span className="text-[11px] font-medium truncate w-full text-slate-800 dark:text-slate-200">
                          {t.displayName}
                        </span>
                        {t.clubId && (
                          <span className="text-[9px] text-emerald-700 dark:text-emerald-400 truncate max-w-full tabular-nums">
                            #{t.clubId}
                            {t.season ? ` · ${t.season}` : ''}
                          </span>
                        )}
                      </button>
                    );
                  })}
                  <button
                    type="button"
                    onClick={() => {
                      setExtractorInitCategory(step2Category);
                      setToolTab('shirt_tool');
                    }}
                    className="p-1.5 rounded-lg border border-dashed border-emerald-500/60 hover:border-emerald-500 text-emerald-700 dark:text-emerald-400 flex flex-col items-center justify-center gap-1 text-[11px] font-medium"
                  >
                    <Shirt className="w-5 h-5" />
                    <span>{step2Category === 'staff' ? '+ Extraer staff' : '+ Extraer camiseta'}</span>
                  </button>
                </div>

                {snap.templateId && !snap.templateId.startsWith('adhoc:') && (
                  <div className="space-y-2 pt-1 text-xs">
                    <div className="grid grid-cols-1 sm:grid-cols-12 gap-2 items-center">
                      <input
                        aria-label="Nombre de la camiseta activa"
                        value={tplNameDraft}
                        onChange={(e) => setTplNameDraft(e.target.value)}
                        placeholder="Nombre plantilla"
                        className="sm:col-span-4 px-2.5 py-1.5 rounded-md border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-950 text-slate-900 dark:text-slate-100"
                      />
                      <select
                        aria-label="Vincular plantilla a club"
                        value={tplClubDraft}
                        onChange={(e) => {
                          const cid = e.target.value;
                          setTplClubDraft(cid);
                          setTplClubNameDraft(cid ? clubs[cid]?.name ?? '' : '');
                        }}
                        className="sm:col-span-4 px-2 py-1.5 rounded-md border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-950 text-slate-900 dark:text-slate-100 truncate"
                      >
                        <option value="">Sin club fijo</option>
                        {tplClubDraft && !clubs[tplClubDraft] && (
                          <option value={tplClubDraft}>
                            {tplClubNameDraft.trim() || `Club #${tplClubDraft}`} (#{tplClubDraft})
                          </option>
                        )}
                        {sortedClubs.map(([cid, info]) => (
                          <option key={cid} value={cid}>
                            {info.name} (#{cid})
                          </option>
                        ))}
                      </select>
                      <input
                        aria-label="ID numérico del club en montaje"
                        inputMode="numeric"
                        value={tplClubDraft}
                        onChange={(e) => {
                          const cid = e.target.value.replace(/[^0-9]/g, '').slice(0, 12);
                          setTplClubNameDraft((prevName) =>
                            resolveNextClubName(tplClubDraft, prevName, cid, clubs, templates),
                          );
                          setTplClubDraft(cid);
                        }}
                        placeholder="#ID Club"
                        className="sm:col-span-2 px-2 py-1.5 rounded-md border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-950 text-slate-900 dark:text-slate-100 tabular-nums font-mono"
                      />
                      <input
                        aria-label="Temporada de plantilla en montaje"
                        value={tplSeasonDraft}
                        onChange={(e) => setTplSeasonDraft(e.target.value)}
                        placeholder="Temporada"
                        className="sm:col-span-2 px-2 py-1.5 rounded-md border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-950 text-slate-900 dark:text-slate-100 tabular-nums"
                      />
                    </div>

                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="flex flex-wrap items-center gap-2">
                        <select
                          aria-label="Categoría de prenda activa"
                          value={tplCategoryDraft}
                          onChange={(e) => setTplCategoryDraft(e.target.value === 'staff' ? 'staff' : 'player')}
                          className="px-2 py-1 rounded border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-950 text-slate-900 dark:text-slate-100"
                        >
                          <option value="player">Tipo: Plantilla</option>
                          <option value="staff">Tipo: Staff</option>
                        </select>
                        {tplClubDraft && (
                          <input
                            aria-label="Nombre de club nuevo en montaje"
                            value={tplClubNameDraft}
                            onChange={(e) => setTplClubNameDraft(e.target.value)}
                            placeholder="Nombre del club"
                            className="w-40 px-2 py-1 rounded border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-950 text-slate-900 dark:text-slate-100"
                          />
                        )}
                        {tplClubDraft && (
                          <label className="inline-flex items-center gap-1.5 text-slate-700 dark:text-slate-300">
                            <input
                              type="checkbox"
                              checked={tplActiveDraft}
                              onChange={(e) => setTplActiveDraft(e.target.checked)}
                              className="accent-emerald-600"
                            />
                            <span>★ Titular activa</span>
                          </label>
                        )}
                      </div>
                      <div className="flex items-center gap-1.5">
                        <button
                          type="button"
                          disabled={busy}
                          onClick={() => void handleSaveTemplateMeta()}
                          className="px-2.5 py-1 rounded-md bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 dark:hover:bg-slate-700 text-slate-800 dark:text-slate-200 font-medium"
                        >
                          Guardar datos
                        </button>
                        {confirmDeleteTpl ? (
                          <>
                            <button
                              type="button"
                              disabled={busy}
                              onClick={() => void handleDeleteCurrentTemplate()}
                              className="px-2 py-1 rounded-md bg-rose-600 hover:bg-rose-500 text-white font-medium"
                            >
                              Confirmar borrado
                            </button>
                            <button
                              type="button"
                              onClick={() => setConfirmDeleteTpl(false)}
                              className="px-2 py-1 rounded-md bg-slate-200 dark:bg-slate-800 text-slate-700 dark:text-slate-300"
                            >
                              Cancelar
                            </button>
                          </>
                        ) : (
                          <button
                            type="button"
                            aria-label="Eliminar plantilla seleccionada"
                            title="Eliminar esta plantilla de tshirt_templates"
                            disabled={busy}
                            onClick={() => setConfirmDeleteTpl(true)}
                            className="p-1.5 rounded-md bg-slate-100 dark:bg-slate-800 hover:bg-rose-100 dark:hover:bg-rose-950/40 text-rose-600 dark:text-rose-400"
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
                        )}
                      </div>
                    </div>
                  </div>
                )}
              </div>
            </div>

            {/* PASO 3: FONDO (Sin alterar comportamiento confirmado por el usuario) */}
            <div onClick={() => setActiveStep(3)} className="p-4 space-y-3">
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
                    onPointerDown={() => {
                      bokehDragRef.current = true;
                      endEditSession();
                    }}
                    onPointerUp={() => {
                      bokehDragRef.current = false;
                      endEditSession('bokeh:slider');
                    }}
                    onPointerCancel={() => {
                      bokehDragRef.current = false;
                      endEditSession('bokeh:slider');
                    }}
                    onBlur={() => {
                      bokehDragRef.current = false;
                      endEditSession('bokeh:slider');
                    }}
                    onChange={(e) =>
                      commitSessionSnap(bokehDragRef.current ? 'bokeh:slider' : undefined, (s) => ({
                        ...s,
                        bgBlur: Number(e.target.value),
                      }))
                    }
                    className="w-full accent-emerald-600 disabled:opacity-40"
                  />
                  <span>{snap.bgBlur}px</span>
                </label>
              </div>
            </div>

            {/* PASO 4: MARCO MAESTRO Y EXPORTACIÓN DUAL */}
            <div onClick={() => setActiveStep(4)} className="p-4 space-y-3 bg-slate-50/70 dark:bg-slate-950/40 rounded-b-xl">
              <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
                <span className="font-semibold uppercase tracking-wider text-emerald-700 dark:text-emerald-400">
                  Paso 4 · Marco Maestro DF11 y Exportación
                </span>
                <span className="text-[11px] text-slate-500 dark:text-slate-400">Anillo exterior Alpha = 0 garantizado</span>
              </div>

              {/* Dual Destination Selector */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-xs" role="group" aria-label="Destino de guardado DF11">
                <button
                  type="button"
                  onClick={() => setExportTarget('creations')}
                  className={`p-2 rounded-lg border text-left transition ${
                    exportTarget === 'creations'
                      ? 'border-emerald-500 bg-emerald-50/70 dark:bg-emerald-950/35 text-slate-900 dark:text-white'
                      : 'border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 text-slate-600 dark:text-slate-400 hover:border-slate-400'
                  }`}
                >
                  <div className="font-semibold">1. Nuestras creaciones</div>
                  <div className="text-[11px] text-slate-500 dark:text-slate-400 truncate">
                    Guarda en tu carpeta de creaciones DF11
                  </div>
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setExportTarget('facepack');
                    setFmt('png');
                  }}
                  className={`p-2 rounded-lg border text-left transition ${
                    exportTarget === 'facepack'
                      ? 'border-emerald-500 bg-emerald-50/70 dark:bg-emerald-950/35 text-slate-900 dark:text-white'
                      : 'border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 text-slate-600 dark:text-slate-400 hover:border-slate-400'
                  }`}
                >
                  <div className="font-semibold">2. Pack de Faces FM</div>
                  <div className="text-[11px] text-slate-500 dark:text-slate-400 truncate">
                    Renombra con el #ID original del futbolista (.png)
                  </div>
                </button>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-12 gap-2.5 items-center">
                <div className="sm:col-span-5">
                  <input
                    aria-label="ID Football Manager"
                    value={uid}
                    onChange={(e) => setUid(e.target.value)}
                    placeholder="ID original futbolista (ej: 29184012 o r-2002049102)"
                    className="w-full px-3 py-1.5 text-xs rounded-md border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-950 text-slate-900 dark:text-slate-100 tabular-nums font-mono"
                  />
                </div>
                <div className="sm:col-span-3 flex items-center gap-1">
                  <button type="button" onClick={() => setFmt('png')} className={segBtn(exportTarget === 'facepack' || fmt === 'png')}>
                    PNG Oficial
                  </button>
                  {exportTarget === 'creations' && (
                    <button type="button" onClick={() => setFmt('jpg')} className={segBtn(fmt === 'jpg')}>
                      JPG
                    </button>
                  )}
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
                    disabled={exportTarget !== 'facepack' && fmt !== 'png'}
                    onChange={(e) => setUpdateXml(e.target.checked)}
                    className="accent-emerald-600"
                  />
                  Actualizar config.xml atómico
                </label>
                {exportTarget === 'creations' ? (
                  <button
                    type="button"
                    aria-label="Elegir carpeta de nuestras creaciones"
                    onClick={async () => {
                      try {
                        const p = await callBridge<{ path: string; storageHealth?: StorageHealth } | null>('choose_directory', 'export');
                        if (p?.path) onExportDirChange(p.path, p.storageHealth);
                      } catch (e) {
                        setErrorMsg(e instanceof Error ? e.message : 'Carpeta no válida.');
                      }
                    }}
                    title={exportDir}
                    className="max-w-[280px] truncate inline-flex items-center gap-1 text-slate-700 dark:text-slate-300 hover:underline"
                  >
                    <FolderOpen className="w-3.5 h-3.5 shrink-0 text-emerald-500" /> {exportDir}
                  </button>
                ) : (
                  <button
                    type="button"
                    aria-label="Elegir carpeta Pack Faces FM"
                    onClick={() => void handleChooseFacepackFolder()}
                    title={effectiveFacepackDir || 'Seleccionar carpeta del Pack de Faces de Football Manager'}
                    className="max-w-[280px] truncate inline-flex items-center gap-1 text-emerald-700 dark:text-emerald-400 font-medium hover:underline"
                  >
                    <FolderOpen className="w-3.5 h-3.5 shrink-0" />
                    {effectiveFacepackDir || 'Elegir carpeta Pack Faces FM…'}
                  </button>
                )}
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
