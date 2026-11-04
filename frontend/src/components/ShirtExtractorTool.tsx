import { MutableRefObject, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ArrowRight,
  Check,
  Crop,
  FolderSearch,
  HelpCircle,
  ImagePlus,
  Loader2,
  Pencil,
  Redo2,
  RotateCcw,
  Save,
  Scissors,
  Search,
  Shirt,
  Star,
  Trash2,
  Undo2,
  Upload,
  X,
} from 'lucide-react';
import {
  CaptureTarget,
  ClubSeed,
  ShirtTemplateInfo,
  StagedShirtResponse,
  TemplateCategory,
  callBridge,
  isTextEntryTarget,
  resolveDroppedImageTransfer,
} from '../lib/ipc';

interface Props {
  clubs: Record<string, ClubSeed>;
  templates: ShirtTemplateInfo[];
  initialCategory?: TemplateCategory;
  persistedRef?: MutableRefObject<ShirtHistoryState | null>;
  incomingStage?: { seq: number; data: StagedShirtResponse } | null;
  onCaptureScreen?: (target: CaptureTarget) => void;
  onTemplatesUpdated: (templates: ShirtTemplateInfo[]) => void;
  onClubsUpdated?: (clubs: Record<string, ClubSeed>) => void;
  onSelectTemplateForComposer: (templateId: string) => void;
}

export interface ShirtSnapshot {
  staged: StagedShirtResponse | null;
  zoom: number;
  panX: number;
  panY: number;
  symmetrize: boolean;
  shoulderBoost: number;
  detailCrispness: number;
  viewMode: 'frame' | 'result';
  cleanUrl: string;
  collarMetrics: { w: number; v: number } | null;
  extractedKey: string;
  displayName: string;
  category: TemplateCategory;
  clubId: string;
  clubName: string;
  season: string;
  isActiveForClub: boolean;
  replacePreviousForClub: boolean;
}

export interface ShirtHistoryState {
  past: ShirtSnapshot[];
  present: ShirtSnapshot;
  future: ShirtSnapshot[];
}

type SliderField = 'zoom' | 'shoulderBoost' | 'detailCrispness';
type CatalogFilter = 'all' | 'player' | 'staff' | 'active' | 'history' | 'unassigned';

interface EditDraft {
  templateId: string;
  displayName: string;
  category: TemplateCategory;
  clubId: string;
  clubName: string;
  season: string;
  isActiveForClub: boolean;
}

const MAX_SHIRT_HISTORY = 40;
const MAX_FILE_BYTES = 20 * 1024 * 1024;
const NON_TEXT_INPUT_TYPES = new Set(['range', 'checkbox', 'radio', 'button', 'color', 'file']);

const EMPTY_SNAPSHOT: ShirtSnapshot = {
  staged: null,
  zoom: 1,
  panX: 0,
  panY: 0,
  symmetrize: true,
  shoulderBoost: 0,
  detailCrispness: 0.35,
  viewMode: 'frame',
  cleanUrl: '',
  collarMetrics: null,
  extractedKey: '',
  displayName: '',
  category: 'player',
  clubId: '',
  clubName: '',
  season: '',
  isActiveForClub: true,
  replacePreviousForClub: false,
};

function sanitizeDigitsId(raw: string): string {
  return raw.replace(/[^0-9]/g, '').slice(0, 12);
}

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

export function pushStagedShirtToHistory(
  prevHistory: ShirtHistoryState | null,
  res: StagedShirtResponse,
  fallbackCategory: TemplateCategory,
): ShirtHistoryState {
  const base = prevHistory ?? {
    past: [],
    present: { ...EMPTY_SNAPSHOT, category: fallbackCategory },
    future: [],
  };
  const width = Number(res.width) || 260;
  const height = Number(res.height) || 310;
  const vp = res.suggestedViewport ?? { zoom: 1, panX: 0, panY: 0 };
  const normalized: StagedShirtResponse = { ...res, width, height, suggestedViewport: vp };
  const cur = base.present;
  const next: ShirtSnapshot = {
    staged: normalized,
    zoom: vp.zoom,
    panX: vp.panX,
    panY: vp.panY,
    symmetrize: true,
    shoulderBoost: 0,
    detailCrispness: cur.detailCrispness,
    viewMode: 'frame',
    cleanUrl: '',
    collarMetrics: null,
    extractedKey: '',
    displayName: res.suggestedName || (cur.category === 'staff' ? 'Prenda_Staff' : 'Camiseta_Club'),
    category: cur.category,
    clubId: cur.clubId,
    clubName: cur.clubName,
    season: cur.season,
    isActiveForClub: cur.isActiveForClub,
    replacePreviousForClub: false,
  };
  const shouldPushPast = cur.staged !== null || base.past.length > 0;
  return {
    past: shouldPushPast ? [...base.past.slice(-(MAX_SHIRT_HISTORY - 1)), cur] : [],
    present: next,
    future: [],
  };
}

function isSameSnap(a: ShirtSnapshot, b: ShirtSnapshot): boolean {
  return (
    a.staged === b.staged &&
    a.zoom === b.zoom &&
    a.panX === b.panX &&
    a.panY === b.panY &&
    a.symmetrize === b.symmetrize &&
    a.shoulderBoost === b.shoulderBoost &&
    a.detailCrispness === b.detailCrispness &&
    a.viewMode === b.viewMode &&
    a.cleanUrl === b.cleanUrl &&
    a.extractedKey === b.extractedKey &&
    a.displayName === b.displayName &&
    a.category === b.category &&
    a.clubId === b.clubId &&
    a.clubName === b.clubName &&
    a.season === b.season &&
    a.isActiveForClub === b.isActiveForClub &&
    a.replacePreviousForClub === b.replacePreviousForClub
  );
}

function buildParamKey(
  staged: StagedShirtResponse | null,
  zoom: number,
  panX: number,
  panY: number,
  symmetrize: boolean,
  shoulderBoost: number,
  detailCrispness: number,
): string {
  if (!staged) return '';
  const srcKey = staged.shirtSourceId || staged.suggestedName || 'raw';
  return `${srcKey}|${zoom.toFixed(3)}|${panX}|${panY}|${symmetrize ? 1 : 0}|${shoulderBoost.toFixed(2)}|${detailCrispness.toFixed(2)}`;
}

export default function ShirtExtractorTool({
  clubs,
  templates,
  initialCategory = 'player',
  persistedRef,
  incomingStage,
  onCaptureScreen,
  onTemplatesUpdated,
  onClubsUpdated,
  onSelectTemplateForComposer,
}: Props) {
  const [history, setHistory] = useState<ShirtHistoryState>(
    () =>
      persistedRef?.current ?? {
        past: [],
        present: { ...EMPTY_SNAPSHOT, category: initialCategory },
        future: [],
      },
  );
  const snap = history.present;
  const consumedSeqRef = useRef<number>(incomingStage?.seq ?? 0);

  useEffect(() => {
    if (persistedRef) {
      persistedRef.current = history;
    }
  }, [persistedRef, history]);

  useEffect(() => {
    setHistory((h) => {
      if (h.present.staged || h.present.category === initialCategory) return h;
      return { ...h, present: { ...h.present, category: initialCategory } };
    });
  }, [initialCategory]);

  const [stageSkin, setStageSkin] = useState<'checker' | 'fm_dark' | 'fm_light'>('checker');
  const [busy, setBusy] = useState(false);
  const [busyLabel, setBusyLabel] = useState('Extrayendo solo la camiseta…');
  const [msg, setMsg] = useState('');
  const [err, setErr] = useState('');

  // Club picker & FM ID helper state
  const [clubFilterQuery, setClubFilterQuery] = useState('');
  const [showIdGuide, setShowIdGuide] = useState(false);

  // Template catalog search, filter, inline edit & delete confirmation state
  const [catalogSearch, setCatalogSearch] = useState('');
  const [catalogFilter, setCatalogFilter] = useState<CatalogFilter>('all');
  const [editDraft, setEditDraft] = useState<EditDraft | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);

  const historyRef = useRef(history);
  historyRef.current = history;

  const fileRef = useRef<HTMLInputElement>(null);
  const canvasRef = useRef<HTMLDivElement>(null);
  const dragRef = useRef<{ sx: number; sy: number; ox: number; oy: number; startSnap: ShirtSnapshot } | null>(null);
  const sliderStartRef = useRef<{ field: SliderField; snap: ShirtSnapshot } | null>(null);
  const wheelBurstTsRef = useRef(0);
  const extractSeqRef = useRef(0);

  const sortedClubs = useMemo(
    () => Object.entries(clubs).sort((a, b) => a[1].name.localeCompare(b[1].name, 'es')),
    [clubs],
  );

  const filteredClubOptions = useMemo(() => {
    const q = clubFilterQuery.trim().toLowerCase().replace(/^#/, '');
    if (!q) return sortedClubs;
    return sortedClubs.filter(([cid, info]) => cid.includes(q) || info.name.toLowerCase().includes(q));
  }, [sortedClubs, clubFilterQuery]);

  const existingClubTemplates = useMemo(
    () =>
      snap.clubId
        ? templates.filter((t) => t.clubId === snap.clubId && (t.category ?? 'player') === snap.category)
        : [],
    [templates, snap.clubId, snap.category],
  );

  const catalogCounts = useMemo(() => {
    let active = 0;
    let historyCount = 0;
    let unassigned = 0;
    let player = 0;
    let staff = 0;
    for (const t of templates) {
      if ((t.category ?? 'player') === 'staff') staff += 1;
      else player += 1;
      if (!t.clubId) unassigned += 1;
      else if (t.isActiveForClub !== false) active += 1;
      else historyCount += 1;
    }
    return { all: templates.length, player, staff, active, history: historyCount, unassigned };
  }, [templates]);

  const effectiveCatalogFilter: CatalogFilter =
    (catalogFilter === 'history' && catalogCounts.history === 0) ||
    (catalogFilter === 'staff' && catalogCounts.staff === 0)
      ? 'all'
      : catalogFilter;

  useEffect(() => {
    if (
      (catalogFilter === 'history' && catalogCounts.history === 0) ||
      (catalogFilter === 'staff' && catalogCounts.staff === 0)
    ) {
      setCatalogFilter('all');
    }
  }, [catalogFilter, catalogCounts.history, catalogCounts.staff]);

  const filteredTemplates = useMemo(() => {
    const q = catalogSearch.trim().toLowerCase().replace(/^#/, '');
    return templates.filter((t) => {
      const cat = t.category ?? 'player';
      if (effectiveCatalogFilter === 'player' && cat !== 'player') return false;
      if (effectiveCatalogFilter === 'staff' && cat !== 'staff') return false;
      if (effectiveCatalogFilter === 'active' && (!t.clubId || t.isActiveForClub === false)) return false;
      if (effectiveCatalogFilter === 'history' && (!t.clubId || t.isActiveForClub !== false)) return false;
      if (effectiveCatalogFilter === 'unassigned' && Boolean(t.clubId)) return false;
      if (!q) return true;
      const resolvedClubName = (t.clubName || clubs[t.clubId]?.name || '').toLowerCase();
      return (
        t.displayName.toLowerCase().includes(q) ||
        t.templateId.toLowerCase().includes(q) ||
        t.clubId.toLowerCase().includes(q) ||
        resolvedClubName.includes(q) ||
        (t.season || '').toLowerCase().includes(q) ||
        (cat === 'staff' && 'staff'.includes(q))
      );
    });
  }, [templates, effectiveCatalogFilter, catalogSearch, clubs]);

  const commitChange = useCallback((updater: (cur: ShirtSnapshot) => ShirtSnapshot) => {
    setHistory((h) => {
      const next = updater(h.present);
      if (isSameSnap(next, h.present)) return h;
      return {
        past: [...h.past.slice(-(MAX_SHIRT_HISTORY - 1)), h.present],
        present: next,
        future: [],
      };
    });
  }, []);

  const replacePresent = useCallback((updater: (cur: ShirtSnapshot) => ShirtSnapshot) => {
    setHistory((h) => {
      const next = updater(h.present);
      if (isSameSnap(next, h.present)) return h;
      return { ...h, present: next };
    });
  }, []);

  const cancelTransientInteractions = useCallback(() => {
    extractSeqRef.current += 1;
    dragRef.current = null;
    sliderStartRef.current = null;
    wheelBurstTsRef.current = 0;
  }, []);

  const handleUndo = useCallback(() => {
    if (busy) return;
    cancelTransientInteractions();
    setHistory((h) => {
      if (h.past.length === 0) return h;
      const previous = h.past[h.past.length - 1];
      return {
        past: h.past.slice(0, -1),
        present: previous,
        future: [h.present, ...h.future.slice(0, MAX_SHIRT_HISTORY - 1)],
      };
    });
  }, [busy, cancelTransientInteractions]);

  const handleRedo = useCallback(() => {
    if (busy) return;
    cancelTransientInteractions();
    setHistory((h) => {
      if (h.future.length === 0) return h;
      const [next, ...rest] = h.future;
      return {
        past: [...h.past.slice(-(MAX_SHIRT_HISTORY - 1)), h.present],
        present: next,
        future: rest,
      };
    });
  }, [busy, cancelTransientInteractions]);

  const handleClearCanvas = useCallback(() => {
    if (busy || !historyRef.current.present.staged) return;
    cancelTransientInteractions();
    commitChange((cur) => ({ ...EMPTY_SNAPSHOT, category: cur.category }));
    setMsg('');
    setErr('');
  }, [busy, cancelTransientInteractions, commitChange]);

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (document.querySelector('[role="dialog"]')) return;
      if (isTextEntryTarget(e.target)) return;
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z' && !e.shiftKey) {
        e.preventDefault();
        handleUndo();
      } else if (
        ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'y') ||
        ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key.toLowerCase() === 'z')
      ) {
        e.preventDefault();
        handleRedo();
      } else if (e.key === 'Delete' && historyRef.current.present.staged) {
        e.preventDefault();
        handleClearCanvas();
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [handleUndo, handleRedo, handleClearCanvas]);

  useEffect(() => {
    const el = canvasRef.current;
    if (!el) return undefined;
    const onNativeWheel = (e: WheelEvent) => {
      const cur = historyRef.current.present;
      if (!cur.staged || busy) return;
      e.preventDefault();
      const now = Date.now();
      const shouldPush = now - wheelBurstTsRef.current > 260;
      wheelBurstTsRef.current = now;
      const delta = e.deltaY < 0 ? 0.06 : -0.06;
      setHistory((h) => {
        if (!h.present.staged) return h;
        const nextZoom = Number(Math.min(4.0, Math.max(0.2, h.present.zoom + delta)).toFixed(3));
        const next: ShirtSnapshot = { ...h.present, zoom: nextZoom, viewMode: 'frame' };
        if (isSameSnap(next, h.present)) return h;
        return shouldPush
          ? {
              past: [...h.past.slice(-(MAX_SHIRT_HISTORY - 1)), h.present],
              present: next,
              future: [],
            }
          : { ...h, present: next };
      });
    };
    el.addEventListener('wheel', onNativeWheel, { passive: false });
    return () => el.removeEventListener('wheel', onNativeWheel);
  }, [busy]);

  const applyStage = useCallback(
    (res: StagedShirtResponse) => {
      cancelTransientInteractions();
      const width = Number(res.width) || 260;
      const height = Number(res.height) || 310;
      const vp = res.suggestedViewport ?? { zoom: 1, panX: 0, panY: 0 };
      const normalized: StagedShirtResponse = {
        ...res,
        width,
        height,
        suggestedViewport: vp,
      };
      commitChange((cur) => ({
        staged: normalized,
        zoom: vp.zoom,
        panX: vp.panX,
        panY: vp.panY,
        symmetrize: true,
        shoulderBoost: 0,
        detailCrispness: cur.detailCrispness,
        viewMode: 'frame',
        cleanUrl: '',
        collarMetrics: null,
        extractedKey: '',
        displayName: res.suggestedName || (cur.category === 'staff' ? 'Prenda_Staff' : 'Camiseta_Club'),
        category: cur.category,
        clubId: cur.clubId,
        clubName: cur.clubName,
        season: cur.season,
        isActiveForClub: cur.isActiveForClub,
        replacePreviousForClub: false,
      }));
      setMsg('');
      setErr('');
    },
    [cancelTransientInteractions, commitChange],
  );

  const handlePickNative = useCallback(async () => {
    if (busy) return;
    if (!window.pywebview?.api?.pick_raw_shirt_source) {
      fileRef.current?.click();
      return;
    }
    setBusyLabel('Cargando imagen…');
    setBusy(true);
    setErr('');
    try {
      const res = await callBridge<StagedShirtResponse | null>('pick_raw_shirt_source');
      if (res?.rawDataUrl) applyStage(res);
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'No se pudo cargar la camiseta.');
    } finally {
      setBusy(false);
    }
  }, [busy, applyStage]);

  const handleFileBlob = useCallback(
    async (file: File) => {
      if (busy) return;
      if (file.size > MAX_FILE_BYTES) {
        setErr('El archivo supera el límite máximo permitido de 20 MB.');
        return;
      }
      setBusyLabel('Cargando imagen…');
      setBusy(true);
      setErr('');
      try {
        const dataUrl = await new Promise<string>((resolve, reject) => {
          const r = new FileReader();
          r.onload = () => resolve(String(r.result));
          r.onerror = () => reject(new Error('No se pudo leer el archivo.'));
          r.readAsDataURL(file);
        });
        const res = await callBridge<StagedShirtResponse>('load_raw_shirt_source', dataUrl, file.name);
        if (res?.rawDataUrl) applyStage(res);
      } catch (e) {
        setErr(e instanceof Error ? e.message : 'Formato inválido.');
      } finally {
        setBusy(false);
      }
    },
    [busy, applyStage],
  );

  useEffect(() => {
    if (incomingStage && incomingStage.seq > consumedSeqRef.current) {
      consumedSeqRef.current = incomingStage.seq;
      applyStage(incomingStage.data);
    }
  }, [incomingStage, applyStage]);

  useEffect(() => {
    const onPaste = (ev: ClipboardEvent) => {
      if (busy || document.querySelector('[role="dialog"]') || isTextEntryTarget(ev.target)) return;
      const f = Array.from(ev.clipboardData?.items ?? [])
        .find((i) => i.type.startsWith('image/'))
        ?.getAsFile();
      if (f) void handleFileBlob(f);
    };
    window.addEventListener('paste', onPaste);
    return () => window.removeEventListener('paste', onPaste);
  }, [busy, handleFileBlob]);

  const handleExtractShirt = async () => {
    const cur = historyRef.current.present;
    if (!cur.staged || busy) return;
    const seq = ++extractSeqRef.current;
    setBusyLabel('Extrayendo en 2× SSAA…');
    setBusy(true);
    setErr('');
    setMsg('');
    try {
      const res = await callBridge<{ cleanShirtDataUrl: string; collarWidth: number; apexY: number }>(
        'preview_shirt_extraction',
        {
          shirtSourceId: cur.staged.shirtSourceId,
          symmetrizeShoulders: cur.symmetrize,
          shoulderBoost: cur.shoulderBoost,
          detailCrispness: cur.detailCrispness,
          zoom: cur.zoom,
          panX: cur.panX,
          panY: cur.panY,
        },
      );
      if (seq === extractSeqRef.current && res?.cleanShirtDataUrl) {
        const key = buildParamKey(
          cur.staged,
          cur.zoom,
          cur.panX,
          cur.panY,
          cur.symmetrize,
          cur.shoulderBoost,
          cur.detailCrispness,
        );
        setHistory((h) => {
          const base = h.present;
          const next: ShirtSnapshot = {
            ...base,
            viewMode: 'result',
            cleanUrl: res.cleanShirtDataUrl,
            collarMetrics: { w: res.collarWidth, v: res.apexY },
            extractedKey: key,
          };
          if (isSameSnap(next, base)) return h;
          return {
            past: [...h.past.slice(-(MAX_SHIRT_HISTORY - 1)), base],
            present: next,
            future: [],
          };
        });
      }
    } catch (e) {
      if (seq === extractSeqRef.current) {
        setErr(e instanceof Error ? e.message : 'Error al extraer la camiseta.');
      }
    } finally {
      if (seq === extractSeqRef.current) setBusy(false);
    }
  };

  const currentKey = buildParamKey(
    snap.staged,
    snap.zoom,
    snap.panX,
    snap.panY,
    snap.symmetrize,
    snap.shoulderBoost,
    snap.detailCrispness,
  );
  const isExtractedUpToDate = Boolean(snap.cleanUrl) && snap.extractedKey === currentKey;

  const handleSaveTemplate = async (sendToComposer: boolean) => {
    if (!snap.staged || !isExtractedUpToDate || busy) return;
    setBusyLabel('Guardando plantilla…');
    setBusy(true);
    setErr('');
    setMsg('');
    try {
      const res = await callBridge<{
        savedTemplateId: string;
        templates: ShirtTemplateInfo[];
        clubs?: Record<string, ClubSeed>;
      }>('save_shirt_template', {
        shirtSourceId: snap.staged.shirtSourceId,
        displayName: snap.displayName.trim() || (snap.category === 'staff' ? 'Prenda Staff' : 'Camiseta Club'),
        category: snap.category,
        clubId: snap.clubId.trim(),
        clubName: snap.clubName.trim(),
        season: snap.season.trim(),
        isActiveForClub: snap.isActiveForClub,
        replacePreviousForClub: snap.replacePreviousForClub,
        templateId: '',
        symmetrizeShoulders: snap.symmetrize,
        shoulderBoost: snap.shoulderBoost,
        detailCrispness: snap.detailCrispness,
        zoom: snap.zoom,
        panX: snap.panX,
        panY: snap.panY,
      });
      if (res?.clubs) onClubsUpdated?.(res.clubs);
      if (Array.isArray(res?.templates)) onTemplatesUpdated(res.templates);
      setMsg(`Plantilla guardada en tshirt_templates: ${res.savedTemplateId}.png`);
      if (sendToComposer && res?.savedTemplateId) {
        onSelectTemplateForComposer(res.savedTemplateId);
      }
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Error al guardar la plantilla.');
    } finally {
      setBusy(false);
    }
  };

  const handleImportFmGraphicsIds = async () => {
    if (busy) return;
    setBusyLabel('Indexando #IDs de Graphics FM…');
    setBusy(true);
    setErr('');
    setMsg('');
    try {
      const res = await callBridge<{
        path: string;
        importedCount: number;
        clubs: Record<string, ClubSeed>;
      } | null>('import_clubs_from_fm_graphics');
      if (!res) return;
      if (res.clubs) onClubsUpdated?.(res.clubs);
      setMsg(`Catálogo actualizado: ${res.importedCount} entradas #ID detectadas en ${res.path}`);
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'No se pudo escanear la carpeta de Graphics.');
    } finally {
      setBusy(false);
    }
  };

  const handleRegisterCustomClub = async () => {
    const cid = sanitizeDigitsId(snap.clubId);
    if (!cid || busy) return;
    setBusy(true);
    setErr('');
    setMsg('');
    try {
      const res = await callBridge<{ clubs: Record<string, ClubSeed>; templates?: ShirtTemplateInfo[] }>(
        'upsert_custom_club',
        cid,
        snap.clubName.trim() || `Club #${cid}`,
      );
      if (res?.clubs) onClubsUpdated?.(res.clubs);
      if (Array.isArray(res?.templates)) onTemplatesUpdated(res.templates);
      setMsg(`Club registrado: ${snap.clubName.trim() || `Club #${cid}`} (#${cid})`);
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'No se pudo registrar el club.');
    } finally {
      setBusy(false);
    }
  };

  const openEditTemplate = (t: ShirtTemplateInfo) => {
    setConfirmDeleteId(null);
    setEditDraft({
      templateId: t.templateId,
      displayName: t.displayName,
      category: t.category === 'staff' ? 'staff' : 'player',
      clubId: t.clubId || '',
      clubName: t.clubName || (t.clubId ? clubs[t.clubId]?.name ?? '' : ''),
      season: t.season || '',
      isActiveForClub: t.clubId ? t.isActiveForClub !== false : true,
    });
  };

  const handleSaveTemplateEdit = async () => {
    if (!editDraft || busy) return;
    setBusy(true);
    setErr('');
    setMsg('');
    try {
      const res = await callBridge<{ templates: ShirtTemplateInfo[]; clubs?: Record<string, ClubSeed> }>(
        'update_shirt_template_meta',
        {
          templateId: editDraft.templateId,
          displayName: editDraft.displayName,
          category: editDraft.category,
          clubId: editDraft.clubId,
          clubName: editDraft.clubName,
          season: editDraft.season,
          isActiveForClub: editDraft.isActiveForClub,
        },
      );
      if (res?.clubs) onClubsUpdated?.(res.clubs);
      if (Array.isArray(res?.templates)) onTemplatesUpdated(res.templates);
      setMsg(`Plantilla actualizada: ${editDraft.displayName || editDraft.templateId}`);
      setEditDraft(null);
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'No se pudo actualizar la plantilla.');
    } finally {
      setBusy(false);
    }
  };

  const handlePromoteActiveTemplate = async (t: ShirtTemplateInfo) => {
    if (busy || !t.clubId) return;
    setBusy(true);
    setErr('');
    setMsg('');
    try {
      const res = await callBridge<{ activeTemplateId: string; templates: ShirtTemplateInfo[] }>(
        'set_active_club_shirt_template',
        t.templateId,
      );
      if (Array.isArray(res?.templates)) onTemplatesUpdated(res.templates);
      setMsg(`Marcada como camiseta titular activa del club #${t.clubId}: ${t.displayName}`);
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'No se pudo activar la plantilla.');
    } finally {
      setBusy(false);
    }
  };

  const handleConfirmDeleteTemplate = async (templateId: string) => {
    if (busy) return;
    setBusy(true);
    setErr('');
    setMsg('');
    try {
      const res = await callBridge<{ deletedTemplateId: string; templates: ShirtTemplateInfo[] }>(
        'delete_shirt_template',
        templateId,
      );
      if (Array.isArray(res?.templates)) onTemplatesUpdated(res.templates);
      if (editDraft?.templateId === templateId) setEditDraft(null);
      setConfirmDeleteId(null);
      setMsg(`Plantilla eliminada de tshirt_templates: ${res?.deletedTemplateId ?? templateId}`);
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'No se pudo eliminar la plantilla.');
    } finally {
      setBusy(false);
    }
  };

  const finishDrag = () => {
    const d = dragRef.current;
    if (!d) return;
    dragRef.current = null;
    const startSnap = d.startSnap;
    setHistory((h) => {
      if (isSameSnap(h.present, startSnap)) return h;
      return {
        past: [...h.past.slice(-(MAX_SHIRT_HISTORY - 1)), startSnap],
        present: h.present,
        future: [],
      };
    });
  };

  const flushSliderHistory = (field: SliderField) => {
    const start = sliderStartRef.current;
    if (!start || start.field !== field) return;
    sliderStartRef.current = null;
    const startSnap = start.snap;
    setHistory((h) => {
      if (isSameSnap(h.present, startSnap)) return h;
      return {
        past: [...h.past.slice(-(MAX_SHIRT_HISTORY - 1)), startSnap],
        present: h.present,
        future: [],
      };
    });
  };

  const fitBase = snap.staged
    ? Math.min(260 / Math.max(snap.staged.width, 1), 310 / Math.max(snap.staged.height, 1))
    : 1;
  const effScale = fitBase * snap.zoom;
  const dispW = snap.staged ? snap.staged.width * effScale : 260;
  const dispH = snap.staged ? snap.staged.height * effScale : 310;
  const imgLeft = (260 - dispW) * 0.5 + snap.panX;
  const imgTop = (310 - dispH) * 0.5 + snap.panY;

  const stageBgClass =
    stageSkin === 'fm_dark'
      ? 'bg-[#0b111e] text-slate-200'
      : stageSkin === 'fm_light'
      ? 'bg-[#e6ebf2] text-slate-800'
      : 'bg-[repeating-conic-gradient(#334155_0%_25%,#0f172a_0%_50%)] bg-[length:16px_16px] text-slate-200';
  const dropzoneCardClass =
    stageSkin === 'fm_light'
      ? 'border-slate-400/90 text-slate-800 bg-white/85 hover:border-emerald-600'
      : 'border-slate-500 text-slate-200 bg-slate-900/80 hover:border-emerald-500';
  const segBtn = (active: boolean) =>
    `px-2.5 py-1.5 text-xs font-medium rounded-md transition ${
      active
        ? 'bg-emerald-600 text-white'
        : 'bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-slate-700'
    }`;

  return (
    <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
      <section className="lg:col-span-5 rounded-xl shadow-xs border border-slate-200/80 dark:border-slate-800 bg-white dark:bg-slate-900 p-5 flex flex-col items-center gap-4">
        <div className="w-full flex items-center justify-between gap-2 text-xs text-slate-600 dark:text-slate-400">
          <span className="font-medium text-slate-900 dark:text-white">
            {snap.viewMode === 'result' && snap.cleanUrl
              ? isExtractedUpToDate
                ? 'Camiseta Extraída · 2× SSAA'
                : 'Ajuste pendiente · Re-extrae la prenda'
              : 'Encuadre Previo · Posición y Tamaño'}
          </span>
          <div className="flex items-center gap-1">
            <button
              type="button"
              title="Deshacer (Ctrl+Z)"
              aria-label="Deshacer"
              disabled={history.past.length === 0 || busy}
              onClick={handleUndo}
              className="p-1.5 rounded-md border border-slate-200 dark:border-slate-700 bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 disabled:opacity-40 hover:bg-slate-200 dark:hover:bg-slate-700 transition"
            >
              <Undo2 className="w-3.5 h-3.5" />
            </button>
            <button
              type="button"
              title="Rehacer (Ctrl+Y / Ctrl+Shift+Z)"
              aria-label="Rehacer"
              disabled={history.future.length === 0 || busy}
              onClick={handleRedo}
              className="p-1.5 rounded-md border border-slate-200 dark:border-slate-700 bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 disabled:opacity-40 hover:bg-slate-200 dark:hover:bg-slate-700 transition"
            >
              <Redo2 className="w-3.5 h-3.5" />
            </button>
            <button
              type="button"
              title="Limpiar lienzo (Supr)"
              aria-label="Limpiar lienzo de camiseta"
              disabled={!snap.staged || busy}
              onClick={handleClearCanvas}
              className="p-1.5 rounded-md border border-slate-200 dark:border-slate-700 bg-slate-100 dark:bg-slate-800 text-rose-600 dark:text-rose-400 disabled:opacity-40 hover:bg-rose-50 dark:hover:bg-rose-950/40 transition"
            >
              <Trash2 className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>

        <div
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            e.preventDefault();
            if (busy) return;
            const { file, blockedRemoteUrl } = resolveDroppedImageTransfer(e.dataTransfer);
            if (file) void handleFileBlob(file);
            else if (blockedRemoteUrl) setErr('Las webs protegen el arrastre directo: usa el botón «Capturar» o Ctrl+V.');
          }}
          className={`w-full rounded-lg p-6 flex flex-col items-center justify-center transition ${stageBgClass} border border-slate-200/60 dark:border-slate-800`}
        >
          <div
            ref={canvasRef}
            data-testid="shirt-extractor-canvas"
            onPointerDown={(e) => {
              if (!snap.staged || busy || (e.target as HTMLElement | null)?.closest('button')) return;
              if (e.pointerType === 'mouse' && e.button !== 0) return;
              const cx = Number.isFinite(e.clientX) ? e.clientX : 0;
              const cy = Number.isFinite(e.clientY) ? e.clientY : 0;
              wheelBurstTsRef.current = 0;
              dragRef.current = {
                sx: cx,
                sy: cy,
                ox: snap.panX,
                oy: snap.panY,
                startSnap: snap,
              };
              e.currentTarget.setPointerCapture?.(e.pointerId);
            }}
            onPointerMove={(e) => {
              const d = dragRef.current;
              if (!d) return;
              const cx = Number.isFinite(e.clientX) ? e.clientX : d.sx;
              const cy = Number.isFinite(e.clientY) ? e.clientY : d.sy;
              const nextX = Math.round(d.ox + (cx - d.sx));
              const nextY = Math.round(d.oy + (cy - d.sy));
              setHistory((h) => {
                if (nextX === h.present.panX && nextY === h.present.panY) return h;
                return {
                  ...h,
                  present: { ...h.present, panX: nextX, panY: nextY, viewMode: 'frame' },
                };
              });
            }}
            onPointerUp={finishDrag}
            onPointerCancel={finishDrag}
            onLostPointerCapture={finishDrag}
            className="box-content relative w-[260px] h-[310px] overflow-hidden rounded-lg border border-emerald-500/40 select-none flex items-center justify-center cursor-grab active:cursor-grabbing"
          >
            {!snap.staged ? (
              <button
                type="button"
                onClick={() => void handlePickNative()}
                className={`w-[222px] h-[276px] rounded-xl border-2 border-dashed flex flex-col items-center justify-center gap-2 px-4 text-center text-xs cursor-pointer transition ${dropzoneCardClass}`}
              >
                <Upload className="w-6 h-6 text-emerald-500" />
                <span className="font-medium">Sube imagen para encuadrar su camiseta</span>
                <span className={stageSkin === 'fm_light' ? 'text-[11px] text-slate-600' : 'text-[11px] text-slate-400'}>
                  Primero amplía, reduce y mueve la imagen en el lienzo; luego extrae en alta nitidez 2× SSAA
                </span>
              </button>
            ) : snap.viewMode === 'frame' || !snap.cleanUrl ? (
              <img
                src={snap.staged.rawDataUrl}
                alt="Encuadre previo de camiseta"
                style={{ width: `${dispW}px`, height: `${dispH}px`, left: `${imgLeft}px`, top: `${imgTop}px` }}
                className="absolute max-w-none pointer-events-none"
              />
            ) : (
              <img
                src={snap.cleanUrl}
                alt="Plantilla de camiseta limpia"
                className="w-[260px] h-[310px] object-contain pointer-events-none"
              />
            )}

            {snap.staged && snap.viewMode === 'result' && snap.cleanUrl && !isExtractedUpToDate && (
              <div className="absolute top-2 inset-x-3 px-2 py-1 rounded bg-amber-950/90 border border-amber-500/60 text-[10px] font-medium text-amber-200 text-center pointer-events-none">
                Ajuste pendiente · Pulsa «Extraer solo la camiseta»
              </div>
            )}

            {snap.staged && (snap.viewMode === 'frame' || !snap.cleanUrl) && (
              <svg className="absolute inset-0 w-[260px] h-[310px] pointer-events-none" viewBox="0 0 260 310">
                <line x1="130" y1="17" x2="130" y2="292" stroke="#0ea5e9" strokeOpacity="0.65" strokeDasharray="2 3" strokeWidth="1" />
                <line x1="19" y1="198" x2="241" y2="198" stroke="#10b981" strokeOpacity="0.8" strokeDasharray="4 3" strokeWidth="1.2" />
                <rect x="19" y="17" width="222" height="275" rx="8" fill="none" stroke="#38bdf8" strokeOpacity="0.7" strokeDasharray="4 3" />
              </svg>
            )}

            {busy && (
              <div className="absolute inset-0 bg-slate-950/60 flex items-center justify-center gap-2 text-xs font-medium text-white">
                <Loader2 className="w-4 h-4 animate-spin" /> {busyLabel}
              </div>
            )}
          </div>
        </div>

        <div className="w-full flex flex-wrap items-center justify-between gap-2 text-xs">
          <div className="flex items-center gap-1">
            <button type="button" onClick={() => setStageSkin('checker')} className={segBtn(stageSkin === 'checker')}>Damero Oscuro</button>
            <button type="button" onClick={() => setStageSkin('fm_dark')} className={segBtn(stageSkin === 'fm_dark')}>Skin Oscura</button>
            <button type="button" onClick={() => setStageSkin('fm_light')} className={segBtn(stageSkin === 'fm_light')}>Skin Clara</button>
          </div>
          {snap.staged ? (
            <span className="tabular-nums font-mono text-slate-500 dark:text-slate-400">
              {snap.viewMode === 'result' && snap.collarMetrics && isExtractedUpToDate
                ? `Cuello ${snap.collarMetrics.w}px · V=${snap.collarMetrics.v}`
                : `Zoom ${Math.round(snap.zoom * 100)}% · X:${snap.panX} Y:${snap.panY}`}
            </span>
          ) : (
            <span className="tabular-nums font-mono text-slate-500 dark:text-slate-400">260 × 310 px</span>
          )}
        </div>
      </section>

      <section className="lg:col-span-7 rounded-xl shadow-xs border border-slate-200/80 dark:border-slate-800 bg-white dark:bg-slate-900 divide-y divide-slate-200/80 dark:divide-slate-800">
        {/* 1. Encuadre y Calidad 2x SSAA */}
        <div className="p-4 space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-xs font-semibold uppercase tracking-wider text-emerald-700 dark:text-emerald-400">
                  Herramienta · Extractor de Plantillas de Camiseta
                </h2>
                <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-700 dark:text-emerald-300 border border-emerald-500/20 font-medium">
                  2× SSAA + Cuello OKLab
                </span>
              </div>
              <p className="text-xs text-slate-600 dark:text-slate-400 mt-0.5">
                1º Ajusta tamaño y posición sobre el lienzo · 2º Pulsa para extraer con nitidez de escudos y ribetes.
              </p>
            </div>
            <div className="flex items-center gap-2">
              <input
                ref={fileRef}
                type="file"
                accept="image/*"
                className="hidden"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  e.target.value = '';
                  if (f) void handleFileBlob(f);
                }}
              />
              {onCaptureScreen && (
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => onCaptureScreen('raw_shirt')}
                  title="Recortar zona de camiseta directamente desde la pantalla"
                  className="px-2.5 py-1.5 text-xs font-medium rounded-md border border-emerald-500/40 bg-emerald-500/10 hover:bg-emerald-500/20 disabled:opacity-40 text-emerald-800 dark:text-emerald-300 inline-flex items-center gap-1.5 transition"
                >
                  <Scissors className="w-3.5 h-3.5" /> Capturar camiseta
                </button>
              )}
              <button
                type="button"
                disabled={busy}
                onClick={() => void handlePickNative()}
                className="px-3 py-1.5 text-xs font-medium rounded-md bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 dark:hover:bg-slate-700 disabled:opacity-40 text-slate-800 dark:text-slate-200 inline-flex items-center gap-1.5 transition"
              >
                <ImagePlus className="w-3.5 h-3.5" /> Subir camiseta
              </button>
              {snap.staged && (
                <button
                  type="button"
                  disabled={busy}
                  onClick={() =>
                    commitChange((s) => ({
                      ...s,
                      zoom: 1,
                      panX: 0,
                      panY: 0,
                      viewMode: 'frame',
                    }))
                  }
                  className="px-2.5 py-1.5 text-xs rounded-md bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 dark:hover:bg-slate-700 disabled:opacity-40 text-slate-700 dark:text-slate-300 inline-flex items-center gap-1 transition"
                >
                  <RotateCcw className="w-3.5 h-3.5" /> 1:1
                </button>
              )}
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-12 gap-3 items-center text-xs">
            <label className="sm:col-span-6 flex items-center gap-2 text-slate-700 dark:text-slate-300 tabular-nums">
              <span className="shrink-0 font-medium">Tamaño (Zoom)</span>
              <input
                aria-label="Tamaño de camiseta en el lienzo"
                type="range"
                min="0.2"
                max="4.0"
                step="0.02"
                disabled={!snap.staged || busy}
                value={snap.zoom}
                onPointerDown={(e) => {
                  sliderStartRef.current = { field: 'zoom', snap: historyRef.current.present };
                  e.currentTarget.setPointerCapture?.(e.pointerId);
                }}
                onChange={(e) => {
                  const val = Number(e.target.value);
                  if (sliderStartRef.current?.field !== 'zoom') {
                    commitChange((s) => ({ ...s, zoom: val, viewMode: 'frame' }));
                  } else {
                    replacePresent((s) => ({ ...s, zoom: val, viewMode: 'frame' }));
                  }
                }}
                onPointerUp={() => flushSliderHistory('zoom')}
                onPointerCancel={() => flushSliderHistory('zoom')}
                onLostPointerCapture={() => flushSliderHistory('zoom')}
                onBlur={() => flushSliderHistory('zoom')}
                className="w-full accent-emerald-600 disabled:opacity-40"
              />
              <span className="w-10 text-right">{Math.round(snap.zoom * 100)}%</span>
            </label>

            <label className="sm:col-span-6 flex items-center gap-2 text-slate-700 dark:text-slate-300 tabular-nums">
              <span className="shrink-0 font-medium" title="Micro-contraste perceptual OKLab en escudos, marcas y costuras">
                Nitidez textil
              </span>
              <input
                aria-label="Nitidez textil de la camiseta"
                type="range"
                min="0"
                max="1"
                step="0.05"
                disabled={!snap.staged || busy}
                value={snap.detailCrispness}
                onPointerDown={(e) => {
                  sliderStartRef.current = { field: 'detailCrispness', snap: historyRef.current.present };
                  e.currentTarget.setPointerCapture?.(e.pointerId);
                }}
                onChange={(e) => {
                  const val = Number(e.target.value);
                  if (sliderStartRef.current?.field !== 'detailCrispness') {
                    commitChange((s) => ({ ...s, detailCrispness: val }));
                  } else {
                    replacePresent((s) => ({ ...s, detailCrispness: val }));
                  }
                }}
                onPointerUp={() => flushSliderHistory('detailCrispness')}
                onPointerCancel={() => flushSliderHistory('detailCrispness')}
                onLostPointerCapture={() => flushSliderHistory('detailCrispness')}
                onBlur={() => flushSliderHistory('detailCrispness')}
                className="w-full accent-emerald-600 disabled:opacity-40"
              />
              <span className="w-9 text-right">{Math.round(snap.detailCrispness * 100)}%</span>
            </label>

            <label className="sm:col-span-5 inline-flex items-center gap-2 text-slate-700 dark:text-slate-300">
              <input
                type="checkbox"
                checked={snap.symmetrize}
                disabled={!snap.staged || busy}
                onChange={(e) => commitChange((s) => ({ ...s, symmetrize: e.target.checked }))}
                className="accent-emerald-600"
              />
              Simetrizar hombros (ideal blancas)
            </label>
            <label className="sm:col-span-7 flex items-center gap-2 text-slate-700 dark:text-slate-300 tabular-nums">
              <span className="shrink-0">Refuerzo hombro</span>
              <input
                type="range"
                min="0"
                max="1"
                step="0.05"
                disabled={!snap.staged || busy}
                value={snap.shoulderBoost}
                onPointerDown={(e) => {
                  sliderStartRef.current = { field: 'shoulderBoost', snap: historyRef.current.present };
                  e.currentTarget.setPointerCapture?.(e.pointerId);
                }}
                onChange={(e) => {
                  const val = Number(e.target.value);
                  if (sliderStartRef.current?.field !== 'shoulderBoost') {
                    commitChange((s) => ({ ...s, shoulderBoost: val }));
                  } else {
                    replacePresent((s) => ({ ...s, shoulderBoost: val }));
                  }
                }}
                onPointerUp={() => flushSliderHistory('shoulderBoost')}
                onPointerCancel={() => flushSliderHistory('shoulderBoost')}
                onLostPointerCapture={() => flushSliderHistory('shoulderBoost')}
                onBlur={() => flushSliderHistory('shoulderBoost')}
                className="w-full accent-emerald-600 disabled:opacity-40"
              />
              <span className="w-9 text-right">{Math.round(snap.shoulderBoost * 100)}%</span>
            </label>
          </div>

          <div className="flex flex-wrap items-center justify-between gap-2 pt-1">
            <div className="flex flex-wrap items-center gap-2">
              {snap.staged && snap.cleanUrl && (
                <button
                  type="button"
                  disabled={busy}
                  onClick={() =>
                    commitChange((s) => ({
                      ...s,
                      viewMode: s.viewMode === 'frame' ? 'result' : 'frame',
                    }))
                  }
                  className="px-3 py-1.5 text-xs font-medium rounded-md bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 dark:hover:bg-slate-700 disabled:opacity-40 text-slate-700 dark:text-slate-300 inline-flex items-center gap-1.5 transition"
                >
                  <Crop className="w-3.5 h-3.5" />
                  {snap.viewMode === 'frame' ? 'Ver camiseta extraída' : 'Reencuadrar sobre el lienzo'}
                </button>
              )}
              <button
                type="button"
                disabled={!snap.staged || busy}
                onClick={() => void handleExtractShirt()}
                className="px-3.5 py-1.5 text-xs font-medium rounded-md bg-emerald-600 hover:bg-emerald-500 disabled:opacity-45 text-white inline-flex items-center gap-1.5 transition"
              >
                <Scissors className="w-3.5 h-3.5" /> Extraer solo la camiseta
              </button>
            </div>
            {snap.staged && !isExtractedUpToDate && (
              <span className="text-[11px] text-amber-700 dark:text-amber-300">
                Encuadra y pulsa «Extraer solo la camiseta» para aplicar.
              </span>
            )}
          </div>
        </div>

        {/* 2. Asignación de Categoría (Plantilla / Staff), Club (#ID), Temporada y Guardado */}
        <div className="p-4 space-y-3 bg-slate-50/60 dark:bg-slate-950/35">
          <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
            <span className="font-semibold text-slate-800 dark:text-slate-200">
              Identificación, Tipo (Plantilla / Staff), #ID de Club FM y Temporada
            </span>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => setShowIdGuide((v) => !v)}
                className="text-[11px] font-medium text-emerald-700 dark:text-emerald-400 hover:underline inline-flex items-center gap-1"
              >
                <HelpCircle className="w-3.5 h-3.5" /> ¿Cómo saber el #ID del club?
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={() => void handleImportFmGraphicsIds()}
                title="Escanear carpeta graphics/logos o graphics/kits de Football Manager para importar sus #ID"
                className="px-2 py-1 text-[11px] rounded border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 text-slate-700 dark:text-slate-300 hover:border-emerald-500 inline-flex items-center gap-1 transition"
              >
                <FolderSearch className="w-3 h-3 text-emerald-500" /> Importar #IDs FM
              </button>
            </div>
          </div>

          <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
            <span className="text-slate-600 dark:text-slate-400 font-medium">
              Destino en Paso 2 (Montaje):
            </span>
            <div className="flex items-center gap-1" role="group" aria-label="Tipo de prenda para Paso 2">
              <button
                type="button"
                onClick={() => replacePresent((s) => ({ ...s, category: 'player', replacePreviousForClub: false }))}
                className={segBtn(snap.category === 'player')}
              >
                Plantilla
              </button>
              <button
                type="button"
                onClick={() => replacePresent((s) => ({ ...s, category: 'staff', replacePreviousForClub: false }))}
                className={segBtn(snap.category === 'staff')}
              >
                Staff
              </button>
            </div>
          </div>

          {showIdGuide && (
            <div className="rounded-lg border border-emerald-500/30 bg-emerald-50/70 dark:bg-emerald-950/25 p-3 text-xs text-slate-700 dark:text-slate-300 space-y-1.5">
              <p className="font-medium text-emerald-900 dark:text-emerald-300">
                3 formas rápidas de conocer el #ID único de cualquier equipo en Football Manager:
              </p>
              <ul className="list-disc pl-4 space-y-1 text-[11px]">
                <li>
                  <strong>Dentro del juego:</strong> abre <code>Preferencias → Interfaz</code> y activa{' '}
                  <em>«Mostrar ID de pantalla en la barra de título para ayudar con la apariencia»</em>. Al entrar a un club verás su número exacto (ej. <code>1744</code> Rayo Vallecano, <code>1736</code> Real Madrid, <code>1708</code> FC Barcelona).
                </li>
                <li>
                  <strong>Desde tus packs de Logos / Kits 2D:</strong> pulsa <strong>Importar #IDs FM</strong> arriba y elige tu carpeta <code>graphics</code>; la app leerá los <code>config.xml</code> automáticamente.
                </li>
                <li>
                  <strong>Cualquier club del mundo o creado en Editor:</strong> escribe el número en <code>#ID Club</code> y su nombre al lado; quedará guardado en tu base local para futuras temporadas.
                </li>
              </ul>
            </div>
          )}

          <div className="grid grid-cols-1 sm:grid-cols-12 gap-2.5 items-center text-xs">
            <input
              aria-label="Nombre de plantilla de camiseta"
              value={snap.displayName}
              onChange={(e) => replacePresent((s) => ({ ...s, displayName: e.target.value }))}
              placeholder="Nombre plantilla (ej: Rayo Titular)"
              className="sm:col-span-5 px-3 py-1.5 rounded-md border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-950 text-slate-900 dark:text-slate-100"
            />
            <input
              aria-label="Temporada de la camiseta"
              value={snap.season}
              onChange={(e) => replacePresent((s) => ({ ...s, season: e.target.value }))}
              placeholder="Temporada (ej: 2026/27)"
              className="sm:col-span-3 px-2.5 py-1.5 rounded-md border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-950 text-slate-900 dark:text-slate-100 tabular-nums"
            />
            <div className="sm:col-span-4 relative">
              <Search className="w-3.5 h-3.5 text-slate-400 absolute left-2.5 top-1/2 -translate-y-1/2 pointer-events-none" />
              <input
                aria-label="Filtrar selector de clubes"
                value={clubFilterQuery}
                onChange={(e) => setClubFilterQuery(e.target.value)}
                placeholder={`Filtrar ${sortedClubs.length} clubes o #ID…`}
                className="w-full pl-8 pr-2.5 py-1.5 rounded-md border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-950 text-slate-900 dark:text-slate-100"
              />
            </div>

            <select
              aria-label="Club asociado a plantilla"
              value={snap.clubId}
              onChange={(e) => {
                const cid = e.target.value;
                const knownName = cid ? clubs[cid]?.name ?? '' : '';
                replacePresent((s) => ({
                  ...s,
                  clubId: cid,
                  clubName: knownName,
                  replacePreviousForClub: false,
                }));
              }}
              className="sm:col-span-5 px-2.5 py-1.5 rounded-md border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-950 text-slate-900 dark:text-slate-100"
            >
              <option value="">Sin club fijo (uso libre)</option>
              {snap.clubId && !clubs[snap.clubId] && (
                <option value={snap.clubId}>
                  {snap.clubName.trim() || `Club #${snap.clubId}`} (#{snap.clubId})
                </option>
              )}
              {filteredClubOptions.map(([cid, info]) => (
                <option key={cid} value={cid}>
                  {info.name} (#{cid})
                </option>
              ))}
            </select>

            <input
              aria-label="ID numérico del club"
              inputMode="numeric"
              value={snap.clubId}
              onChange={(e) => {
                const cid = sanitizeDigitsId(e.target.value);
                replacePresent((s) => ({
                  ...s,
                  clubId: cid,
                  clubName: resolveNextClubName(s.clubId, s.clubName, cid, clubs, templates),
                  replacePreviousForClub: false,
                }));
              }}
              placeholder="#ID Club (ej: 1744)"
              className="sm:col-span-3 px-2.5 py-1.5 rounded-md border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-950 text-slate-900 dark:text-slate-100 tabular-nums font-mono"
            />

            <div className="sm:col-span-4 flex items-center gap-1.5">
              <input
                aria-label="Nombre del club"
                value={snap.clubName}
                disabled={!snap.clubId}
                onChange={(e) => replacePresent((s) => ({ ...s, clubName: e.target.value }))}
                placeholder={snap.clubId ? 'Nombre del club' : 'Indica #ID primero'}
                className="w-full px-2.5 py-1.5 rounded-md border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-950 text-slate-900 dark:text-slate-100 disabled:opacity-50"
              />
              {snap.clubId && (!clubs[snap.clubId] || (snap.clubName.trim() && snap.clubName.trim() !== clubs[snap.clubId]?.name)) && (
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => void handleRegisterCustomClub()}
                  title="Guardar este #ID y nombre en el catálogo de clubes"
                  className="shrink-0 px-2 py-1.5 rounded-md bg-emerald-600 hover:bg-emerald-500 text-white font-medium text-[11px]"
                >
                  + Club
                </button>
              )}
            </div>
          </div>

          {snap.clubId && (
            <div className="flex flex-wrap items-center justify-between gap-2 text-xs pt-0.5">
              <label className="inline-flex items-center gap-1.5 text-slate-700 dark:text-slate-300">
                <input
                  type="checkbox"
                  checked={snap.isActiveForClub || snap.replacePreviousForClub}
                  disabled={snap.replacePreviousForClub}
                  onChange={(e) => replacePresent((s) => ({ ...s, isActiveForClub: e.target.checked }))}
                  className="accent-emerald-600"
                />
                <span>Marcar como ★ Camiseta Titular Activa de #{snap.clubId}</span>
              </label>
              {existingClubTemplates.length > 0 && (
                <label className="inline-flex items-center gap-1.5 text-amber-800 dark:text-amber-300 text-[11px]">
                  <input
                    type="checkbox"
                    checked={snap.replacePreviousForClub}
                    onChange={(e) =>
                      replacePresent((s) => ({
                        ...s,
                        replacePreviousForClub: e.target.checked,
                        isActiveForClub: e.target.checked ? true : s.isActiveForClub,
                      }))
                    }
                    className="accent-amber-600"
                  />
                  <span>
                    Reemplazar {existingClubTemplates.length} anterior(es) de #{snap.clubId} (sin conservar histórico)
                  </span>
                </label>
              )}
            </div>
          )}

          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              disabled={!isExtractedUpToDate || busy}
              onClick={() => void handleSaveTemplate(false)}
              className="px-3 py-1.5 text-xs font-medium rounded-md bg-slate-800 hover:bg-slate-700 dark:bg-slate-700 dark:hover:bg-slate-600 disabled:opacity-45 text-white inline-flex items-center gap-1.5 transition"
            >
              <Save className="w-3.5 h-3.5" /> Guardar en tshirt_templates
            </button>
            <button
              type="button"
              disabled={!isExtractedUpToDate || busy}
              onClick={() => void handleSaveTemplate(true)}
              className="px-3.5 py-1.5 text-xs font-medium rounded-md bg-emerald-600 hover:bg-emerald-500 disabled:opacity-45 text-white inline-flex items-center gap-1.5 transition"
            >
              Guardar y usar en Montaje <ArrowRight className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>

        {/* 3. Catálogo tshirt_templates con Buscador, Temporadas, Edición y Borrado */}
        <div className="p-4 space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
            <span className="font-semibold text-slate-800 dark:text-slate-200 inline-flex items-center gap-1.5">
              <Shirt className="w-3.5 h-3.5 text-emerald-500" /> Plantillas en tshirt_templates ({filteredTemplates.length}/{templates.length})
            </span>
            <div className="flex flex-wrap items-center gap-1">
              <button
                type="button"
                onClick={() => setCatalogFilter('all')}
                className={segBtn(effectiveCatalogFilter === 'all')}
              >
                Todas ({catalogCounts.all})
              </button>
              {catalogCounts.staff > 0 && (
                <>
                  <button
                    type="button"
                    onClick={() => setCatalogFilter('player')}
                    className={segBtn(effectiveCatalogFilter === 'player')}
                  >
                    Plantilla ({catalogCounts.player})
                  </button>
                  <button
                    type="button"
                    onClick={() => setCatalogFilter('staff')}
                    className={segBtn(effectiveCatalogFilter === 'staff')}
                  >
                    Staff ({catalogCounts.staff})
                  </button>
                </>
              )}
              <button
                type="button"
                onClick={() => setCatalogFilter('active')}
                className={segBtn(effectiveCatalogFilter === 'active')}
              >
                ★ Activas ({catalogCounts.active})
              </button>
              {catalogCounts.history > 0 && (
                <button
                  type="button"
                  onClick={() => setCatalogFilter('history')}
                  className={segBtn(effectiveCatalogFilter === 'history')}
                >
                  Histórico ({catalogCounts.history})
                </button>
              )}
              <button
                type="button"
                onClick={() => setCatalogFilter('unassigned')}
                className={segBtn(effectiveCatalogFilter === 'unassigned')}
              >
                Sin club ({catalogCounts.unassigned})
              </button>
            </div>
          </div>

          <div className="relative text-xs">
            <Search className="w-3.5 h-3.5 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none" />
            <input
              aria-label="Buscar plantillas de camiseta"
              value={catalogSearch}
              onChange={(e) => setCatalogSearch(e.target.value)}
              placeholder="Buscar camiseta por nombre, club, #ID (ej. 1744) o temporada (ej. 2026/27)…"
              className="w-full pl-8 pr-8 py-1.5 rounded-md border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-950 text-slate-900 dark:text-slate-100"
            />
            {catalogSearch && (
              <button
                type="button"
                aria-label="Limpiar búsqueda de plantillas"
                onClick={() => setCatalogSearch('')}
                className="absolute right-2 top-1/2 -translate-y-1/2 p-0.5 text-slate-400 hover:text-slate-600 dark:hover:text-slate-200"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            )}
          </div>

          {editDraft && (
            <div className="rounded-lg border border-emerald-500/40 bg-slate-50 dark:bg-slate-950/80 p-3 space-y-2.5 text-xs">
              <div className="flex items-center justify-between">
                <span className="font-semibold text-emerald-800 dark:text-emerald-300">
                  Editar plantilla: {editDraft.templateId}.png
                </span>
                <button
                  type="button"
                  onClick={() => setEditDraft(null)}
                  className="text-slate-500 hover:text-slate-800 dark:hover:text-slate-200"
                >
                  Cerrar
                </button>
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-12 gap-2 items-center">
                <input
                  aria-label="Editar nombre de plantilla"
                  value={editDraft.displayName}
                  onChange={(e) => setEditDraft((d) => (d ? { ...d, displayName: e.target.value } : d))}
                  placeholder="Nombre plantilla"
                  className="sm:col-span-4 px-2.5 py-1.5 rounded-md border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-100"
                />
                <input
                  aria-label="Editar ID de club de plantilla"
                  inputMode="numeric"
                  value={editDraft.clubId}
                  onChange={(e) => {
                    const cid = sanitizeDigitsId(e.target.value);
                    setEditDraft((d) =>
                      d
                        ? {
                            ...d,
                            clubId: cid,
                            clubName: resolveNextClubName(d.clubId, d.clubName, cid, clubs, templates),
                          }
                        : d,
                    );
                  }}
                  placeholder="#ID Club"
                  className="sm:col-span-2 px-2 py-1.5 rounded-md border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-100 tabular-nums font-mono"
                />
                <input
                  aria-label="Editar nombre de club de plantilla"
                  value={editDraft.clubName}
                  disabled={!editDraft.clubId}
                  onChange={(e) => setEditDraft((d) => (d ? { ...d, clubName: e.target.value } : d))}
                  placeholder="Nombre del club"
                  className="sm:col-span-3 px-2.5 py-1.5 rounded-md border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-100 disabled:opacity-50"
                />
                <input
                  aria-label="Editar temporada de plantilla"
                  value={editDraft.season}
                  onChange={(e) => setEditDraft((d) => (d ? { ...d, season: e.target.value } : d))}
                  placeholder="Temporada"
                  className="sm:col-span-3 px-2.5 py-1.5 rounded-md border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-100 tabular-nums"
                />
              </div>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex flex-wrap items-center gap-2">
                  <div className="inline-flex items-center gap-1" role="group" aria-label="Editar tipo de plantilla">
                    <button
                      type="button"
                      onClick={() => setEditDraft((d) => (d ? { ...d, category: 'player' } : d))}
                      className={segBtn(editDraft.category === 'player')}
                    >
                      Plantilla
                    </button>
                    <button
                      type="button"
                      onClick={() => setEditDraft((d) => (d ? { ...d, category: 'staff' } : d))}
                      className={segBtn(editDraft.category === 'staff')}
                    >
                      Staff
                    </button>
                  </div>
                  <label className="inline-flex items-center gap-1.5 text-slate-700 dark:text-slate-300">
                    <input
                      type="checkbox"
                      disabled={!editDraft.clubId}
                      checked={Boolean(editDraft.clubId) && editDraft.isActiveForClub}
                      onChange={(e) => setEditDraft((d) => (d ? { ...d, isActiveForClub: e.target.checked } : d))}
                      className="accent-emerald-600"
                    />
                    <span>★ Prenda titular activa de este club</span>
                  </label>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => setEditDraft(null)}
                    className="px-2.5 py-1 rounded-md bg-slate-200 dark:bg-slate-800 text-slate-700 dark:text-slate-300"
                  >
                    Cancelar
                  </button>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => void handleSaveTemplateEdit()}
                    className="px-3 py-1 rounded-md bg-emerald-600 hover:bg-emerald-500 text-white font-medium"
                  >
                    Guardar cambios
                  </button>
                </div>
              </div>
            </div>
          )}

          {filteredTemplates.length === 0 ? (
            <p className="text-xs text-slate-500 dark:text-slate-400 py-4 text-center">
              {templates.length === 0
                ? 'Aún no hay plantillas en tshirt_templates. Sube y extrae una camiseta arriba.'
                : 'Ninguna plantilla coincide con la búsqueda o filtro actual.'}
            </p>
          ) : (
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-2.5 max-h-72 overflow-y-auto pr-1">
              {filteredTemplates.map((t) => {
                const resolvedClubLabel = t.clubId ? t.clubName || clubs[t.clubId]?.name || `Club #${t.clubId}` : '';
                const isActiveClubKit = Boolean(t.clubId) && t.isActiveForClub !== false;
                const isStaffKit = (t.category ?? 'player') === 'staff';
                const isConfirmingDelete = confirmDeleteId === t.templateId;
                return (
                  <div
                    key={t.templateId}
                    className="p-2 rounded-lg border border-slate-200 dark:border-slate-800 hover:border-emerald-500/70 bg-slate-50 dark:bg-slate-950/60 flex flex-col justify-between gap-1.5 transition"
                  >
                    <button
                      type="button"
                      onClick={() => onSelectTemplateForComposer(t.templateId)}
                      className="w-full flex flex-col items-center gap-1 text-center cursor-pointer"
                    >
                      <div className="relative">
                        <img
                          src={t.thumbDataUrl}
                          alt={t.displayName}
                          className="w-16 h-16 object-contain rounded bg-[repeating-conic-gradient(#334155_0%_25%,#0f172a_0%_50%)] bg-[length:10px_10px]"
                        />
                        {isStaffKit && (
                          <span className="absolute -top-1 -left-1 text-[9px] px-1 py-0.2 rounded font-semibold bg-amber-600 text-white">
                            Staff
                          </span>
                        )}
                        {t.clubId && (
                          <span
                            className={`absolute -top-1 -right-1 text-[9px] px-1 py-0.2 rounded font-semibold ${
                              isActiveClubKit
                                ? 'bg-emerald-600 text-white'
                                : 'bg-slate-700 text-slate-200'
                            }`}
                          >
                            {isActiveClubKit ? '★' : 'Hist.'}
                          </span>
                        )}
                      </div>
                      <span className="text-xs font-medium truncate w-full text-slate-800 dark:text-slate-200">
                        {t.displayName}
                      </span>
                      {t.clubId ? (
                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 truncate max-w-full tabular-nums">
                          #{t.clubId} · {resolvedClubLabel}
                        </span>
                      ) : (
                        <span className="text-[10px] text-slate-400">Sin club asignado</span>
                      )}
                      {t.season && (
                        <span className="text-[10px] text-slate-500 dark:text-slate-400 tabular-nums">
                          Temp. {t.season}
                        </span>
                      )}
                    </button>

                    {isConfirmingDelete ? (
                      <div className="flex items-center justify-between gap-1 pt-1 border-t border-slate-200 dark:border-slate-800 text-[10px]">
                        <button
                          type="button"
                          disabled={busy}
                          onClick={() => void handleConfirmDeleteTemplate(t.templateId)}
                          className="flex-1 px-1.5 py-1 rounded bg-rose-600 hover:bg-rose-500 text-white font-medium"
                        >
                          Borrar
                        </button>
                        <button
                          type="button"
                          onClick={() => setConfirmDeleteId(null)}
                          className="flex-1 px-1.5 py-1 rounded bg-slate-200 dark:bg-slate-800 text-slate-700 dark:text-slate-300"
                        >
                          No
                        </button>
                      </div>
                    ) : (
                      <div className="flex items-center justify-between gap-1 pt-1 border-t border-slate-200/70 dark:border-slate-800/80">
                        {t.clubId && !isActiveClubKit ? (
                          <button
                            type="button"
                            disabled={busy}
                            onClick={() => void handlePromoteActiveTemplate(t)}
                            title="Convertir en la camiseta titular activa de este #ID de club"
                            className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-amber-500/15 text-amber-800 dark:text-amber-300 hover:bg-amber-500/25 inline-flex items-center gap-0.5"
                          >
                            <Star className="w-2.5 h-2.5" /> Activar
                          </button>
                        ) : (
                          <span className="text-[10px] text-slate-400 truncate">
                            {isActiveClubKit ? 'Titular activa' : 'Libre'}
                          </span>
                        )}
                        <div className="flex items-center gap-1">
                          <button
                            type="button"
                            aria-label={`Editar plantilla ${t.displayName}`}
                            title="Asignar #ID de club, temporada o renombrar"
                            onClick={() => openEditTemplate(t)}
                            className="p-1 rounded hover:bg-slate-200 dark:hover:bg-slate-800 text-slate-600 dark:text-slate-300"
                          >
                            <Pencil className="w-3 h-3" />
                          </button>
                          <button
                            type="button"
                            aria-label={`Eliminar plantilla ${t.displayName}`}
                            title="Eliminar plantilla de tshirt_templates"
                            onClick={() => setConfirmDeleteId(t.templateId)}
                            className="p-1 rounded hover:bg-rose-100 dark:hover:bg-rose-950/50 text-rose-600 dark:text-rose-400"
                          >
                            <Trash2 className="w-3 h-3" />
                          </button>
                        </div>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}

          {err && <p className="text-xs text-rose-600 dark:text-rose-400">{err}</p>}
          {msg && (
            <p className="text-xs text-emerald-700 dark:text-emerald-400 inline-flex items-center gap-1">
              <Check className="w-3.5 h-3.5" /> {msg}
            </p>
          )}
        </div>
      </section>
    </div>
  );
}
