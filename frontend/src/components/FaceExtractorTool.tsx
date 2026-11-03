import { useCallback, useRef, useState } from 'react';
import { ArrowRight, Check, Crop, ImagePlus, Loader2, RotateCcw, Save, Upload } from 'lucide-react';
import { CropViewportDTO, ExtractedFaceResponse, SavedFaceInfo, StagedFaceResponse, callBridge } from '../lib/ipc';

interface Props {
  faces: SavedFaceInfo[];
  activeTemplateId: string;
  onFacesUpdated: (faces: SavedFaceInfo[]) => void;
  onUseExtractedFace: (payload: {
    headAssetId: string;
    name: string;
    isPreCutout: boolean;
    autoFit: { scale: number; offsetX: number; offsetY: number; neckFill: number };
    previewDataUrl: string;
  }) => void;
  onPickSavedFace: (faceId: string) => void;
}

export default function FaceExtractorTool({
  faces,
  activeTemplateId,
  onFacesUpdated,
  onUseExtractedFace,
  onPickSavedFace,
}: Props) {
  const [staged, setStaged] = useState<StagedFaceResponse | null>(null);
  const [viewport, setViewport] = useState<CropViewportDTO>({ zoom: 1, panX: 0, panY: 0 });
  const [removeBg, setRemoveBg] = useState(true);
  const [extracted, setExtracted] = useState<ExtractedFaceResponse | null>(null);
  const [viewMode, setViewMode] = useState<'crop' | 'result'>('crop');
  const [stageSkin, setStageSkin] = useState<'checker' | 'fm_dark' | 'fm_light'>('checker');
  const [saveName, setSaveName] = useState('');
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState('');
  const [err, setErr] = useState('');

  const fileRef = useRef<HTMLInputElement>(null);
  const dragRef = useRef<{ sx: number; sy: number; ox: number; oy: number } | null>(null);

  const applyStaged = (res: StagedFaceResponse) => {
    setStaged(res);
    setViewport(res.suggestedViewport);
    setExtracted(null);
    setViewMode('crop');
    setSaveName(res.fileName ? res.fileName.replace(/\.[^.]+$/, '') : 'Cara_Extraida');
    setMsg('');
    setErr('');
  };

  const handlePickNative = useCallback(async () => {
    if (!window.pywebview?.api?.pick_raw_face_source) {
      fileRef.current?.click();
      return;
    }
    setBusy(true); setErr('');
    try {
      const res = await callBridge<StagedFaceResponse | null>('pick_raw_face_source');
      if (res?.rawDataUrl) applyStaged(res);
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'No se pudo cargar la imagen.');
    } finally {
      setBusy(false);
    }
  }, []);

  const handleFileBlob = useCallback(async (file: File) => {
    setBusy(true); setErr('');
    try {
      const dataUrl = await new Promise<string>((resolve, reject) => {
        const r = new FileReader();
        r.onload = () => resolve(String(r.result));
        r.onerror = () => reject(new Error('No se pudo leer el archivo.'));
        r.readAsDataURL(file);
      });
      const res = await callBridge<StagedFaceResponse>('load_raw_face_source', dataUrl, file.name);
      if (res?.rawDataUrl) applyStaged(res);
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Formato inválido.');
    } finally {
      setBusy(false);
    }
  }, []);

  const handleExtract = async () => {
    if (!staged) return;
    setBusy(true); setErr(''); setMsg('');
    try {
      const res = await callBridge<ExtractedFaceResponse>('extract_face_from_crop', {
        zoom: viewport.zoom,
        panX: viewport.panX,
        panY: viewport.panY,
        removeBg,
        templateId: activeTemplateId,
      });
      setExtracted(res);
      setViewMode('result');
      if (res.suggestedName && !saveName) setSaveName(res.suggestedName);
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Error al extraer cabeza y cuello.');
    } finally {
      setBusy(false);
    }
  };

  const handleSaveFace = async () => {
    if (!extracted) return;
    setBusy(true); setErr('');
    try {
      const res = await callBridge<{ faceId: string; name: string; faces: SavedFaceInfo[] }>(
        'save_extracted_face',
        extracted.headAssetId,
        saveName || 'Cara_Extraida',
      );
      if (Array.isArray(res?.faces)) onFacesUpdated(res.faces);
      setMsg(`Cara guardada en biblioteca: ${res.name}.png`);
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'No se pudo guardar la cara.');
    } finally {
      setBusy(false);
    }
  };

  const fitBase = staged ? Math.min(260 / Math.max(staged.width, 1), 310 / Math.max(staged.height, 1)) : 1;
  const effScale = fitBase * viewport.zoom;
  const dispW = staged ? staged.width * effScale : 260;
  const dispH = staged ? staged.height * effScale : 310;
  const imgLeft = (260 - dispW) * 0.5 + viewport.panX;
  const imgTop = (310 - dispH) * 0.5 + viewport.panY;
  const crownCanvasY = staged ? imgTop + staged.crownSrcY * effScale : 24;
  const crownRisk = staged !== null && viewMode === 'crop' && crownCanvasY < 19;

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

  return (
    <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
      <section className="lg:col-span-5 rounded-xl shadow-xs border border-slate-200/80 dark:border-slate-800 bg-white dark:bg-slate-900 p-5 flex flex-col items-center gap-4">
        <div className="w-full flex items-center justify-between text-xs text-slate-600 dark:text-slate-400">
          <span className="font-medium text-slate-900 dark:text-white">
            {viewMode === 'crop' ? 'Zona de Corte · Cabeza y Cuello' : 'Cabeza y Cuello Extraídos'}
          </span>
          <span className="tabular-nums font-mono">Rueda = Zoom</span>
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
            onWheel={(e) => {
              if (!staged || viewMode !== 'crop') return;
              e.preventDefault();
              const delta = e.deltaY < 0 ? 0.08 : -0.08;
              setViewport((v) => ({ ...v, zoom: Number(Math.min(3.2, Math.max(0.35, v.zoom + delta)).toFixed(3)) }));
            }}
            onPointerDown={(e) => {
              if (!staged || viewMode !== 'crop' || (e.target as HTMLElement | null)?.closest('button')) return;
              dragRef.current = { sx: e.clientX, sy: e.clientY, ox: viewport.panX, oy: viewport.panY };
              e.currentTarget.setPointerCapture?.(e.pointerId);
            }}
            onPointerMove={(e) => {
              if (!dragRef.current) return;
              const dx = e.clientX - dragRef.current.sx;
              const dy = e.clientY - dragRef.current.sy;
              setViewport((v) => ({ ...v, panX: Math.round(dragRef.current!.ox + dx), panY: Math.round(dragRef.current!.oy + dy) }));
            }}
            onPointerUp={() => { dragRef.current = null; }}
            onPointerCancel={() => { dragRef.current = null; }}
            className="relative w-[260px] h-[310px] overflow-hidden rounded-lg border border-emerald-500/40 select-none flex items-center justify-center cursor-grab active:cursor-grabbing"
          >
            {!staged ? (
              <button
                type="button"
                onClick={() => void handlePickNative()}
                className="w-[222px] h-[276px] rounded-xl border-2 border-dashed border-slate-400/70 dark:border-slate-600 flex flex-col items-center justify-center gap-2 px-4 text-center text-xs text-slate-600 dark:text-slate-300 bg-white/75 dark:bg-slate-900/75 cursor-pointer hover:border-emerald-500 transition"
              >
                <Upload className="w-6 h-6 text-emerald-600 dark:text-emerald-400" />
                <span className="font-medium">Haz clic para elegir imagen de cara</span>
                <span className="text-[11px] text-slate-500 dark:text-slate-400">Usa la rueda del ratón para encuadrar sin cortar cabezas</span>
              </button>
            ) : viewMode === 'crop' ? (
              <img
                src={staged.rawDataUrl}
                alt="Encuadre previo de cara"
                style={{ width: `${dispW}px`, height: `${dispH}px`, left: `${imgLeft}px`, top: `${imgTop}px` }}
                className="absolute max-w-none pointer-events-none"
              />
            ) : (
              extracted && (
                <img
                  src={extracted.headPreviewDataUrl}
                  alt="Cabeza y cuello limpios"
                  className="max-w-[240px] max-h-[290px] object-contain pointer-events-none"
                />
              )
            )}

            {staged && viewMode === 'crop' && (
              <svg className="absolute inset-0 w-[260px] h-[310px] pointer-events-none" viewBox="0 0 260 310">
                <line x1="19" y1="21" x2="241" y2="21" stroke={crownRisk ? '#f59e0b' : '#10b981'} strokeDasharray="3 3" strokeWidth="1.4" />
                <line x1="19" y1="113" x2="241" y2="113" stroke="#38bdf8" strokeDasharray="4 2" strokeWidth="1" />
                <rect x="19" y="17" width="222" height="275" rx="8" fill="none" stroke="#94a3b8" strokeOpacity="0.45" strokeDasharray="4 3" />
              </svg>
            )}

            {busy && (
              <div className="absolute inset-0 bg-slate-950/50 flex items-center justify-center gap-2 text-xs font-medium text-white">
                <Loader2 className="w-4 h-4 animate-spin" /> Extrayendo cabeza y cuello…
              </div>
            )}
          </div>
        </div>

        {crownRisk && (
          <div className="w-full px-3 py-1.5 rounded-md bg-amber-50 dark:bg-amber-950/40 border border-amber-300/70 dark:border-amber-700/60 text-[11px] text-amber-800 dark:text-amber-300 flex items-center justify-between gap-2">
            <span>Atención: el pelo supera el margen superior seguro.</span>
            <button
              type="button"
              onClick={() => staged && setViewport(staged.suggestedViewport)}
              className="underline font-medium shrink-0"
            >
              Auto-proteger
            </button>
          </div>
        )}

        <div className="w-full flex flex-wrap items-center justify-between gap-2 text-xs">
          <div className="flex items-center gap-1">
            <button type="button" onClick={() => setStageSkin('checker')} className={segBtn(stageSkin === 'checker')}>Alfa 0</button>
            <button type="button" onClick={() => setStageSkin('fm_dark')} className={segBtn(stageSkin === 'fm_dark')}>Skin Oscura</button>
            <button type="button" onClick={() => setStageSkin('fm_light')} className={segBtn(stageSkin === 'fm_light')}>Skin Clara</button>
          </div>
          {staged && (
            <span className="tabular-nums text-slate-500 dark:text-slate-400">
              Zoom {Math.round(viewport.zoom * 100)}% · X:{viewport.panX} Y:{viewport.panY}
            </span>
          )}
        </div>
      </section>

      <section className="lg:col-span-7 rounded-xl shadow-xs border border-slate-200/80 dark:border-slate-800 bg-white dark:bg-slate-900 divide-y divide-slate-200/80 dark:divide-slate-800">
        <div className="p-4 space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <h2 className="text-xs font-semibold uppercase tracking-wider text-emerald-700 dark:text-emerald-400">
                Herramienta · Extractor de Cabeza y Cuello
              </h2>
              <p className="text-xs text-slate-600 dark:text-slate-400 mt-0.5">
                Selecciona con la rueda del ratón la zona exacta antes de extraer; elimina fondos y cuellos de ropa antiguos.
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
              <button
                type="button"
                onClick={() => void handlePickNative()}
                className="px-3 py-1.5 text-xs font-medium rounded-md bg-slate-100 dark:bg-slate-800 text-slate-800 dark:text-slate-200 inline-flex items-center gap-1.5"
              >
                <ImagePlus className="w-3.5 h-3.5" /> Elegir imagen
              </button>
              {staged && (
                <button
                  type="button"
                  onClick={() => { setViewport(staged.suggestedViewport); setViewMode('crop'); }}
                  className="px-2.5 py-1.5 text-xs rounded-md bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 inline-flex items-center gap-1"
                >
                  <RotateCcw className="w-3.5 h-3.5" /> Encuadre seguro
                </button>
              )}
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-12 gap-3 items-center text-xs">
            <label className="sm:col-span-5 inline-flex items-center gap-2 text-slate-700 dark:text-slate-300">
              <input
                type="checkbox"
                checked={removeBg}
                onChange={(e) => setRemoveBg(e.target.checked)}
                className="accent-emerald-600"
              />
              Quitar fondo y ropa (BiRefNet + BiSeNet)
            </label>
            <label className="sm:col-span-7 flex items-center gap-2 text-slate-700 dark:text-slate-300 tabular-nums">
              <span>Zona</span>
              <input
                type="range"
                min="0.35"
                max="3.2"
                step="0.02"
                disabled={!staged}
                value={viewport.zoom}
                onChange={(e) => { setViewMode('crop'); setViewport((v) => ({ ...v, zoom: Number(e.target.value) })); }}
                className="w-full accent-emerald-600 disabled:opacity-40"
              />
              <span>{Math.round(viewport.zoom * 100)}%</span>
            </label>
          </div>

          <div className="flex flex-wrap items-center gap-2 pt-1">
            {extracted && viewMode === 'result' && (
              <button
                type="button"
                onClick={() => setViewMode('crop')}
                className="px-3 py-1.5 text-xs font-medium rounded-md bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 inline-flex items-center gap-1.5"
              >
                <Crop className="w-3.5 h-3.5" /> Reajustar zona de corte
              </button>
            )}
            <button
              type="button"
              disabled={!staged || busy}
              onClick={() => void handleExtract()}
              className="px-3.5 py-1.5 text-xs font-medium rounded-md bg-emerald-600 hover:bg-emerald-500 disabled:opacity-45 text-white inline-flex items-center gap-1.5"
            >
              <Crop className="w-3.5 h-3.5" /> Aplicar zona de corte y extraer
            </button>
          </div>
        </div>

        {extracted && (
          <div className="p-4 space-y-3 bg-emerald-50/40 dark:bg-emerald-950/15">
            <div className="grid grid-cols-1 sm:grid-cols-12 gap-2.5 items-center">
              <input
                aria-label="Nombre para guardar cara"
                value={saveName}
                onChange={(e) => setSaveName(e.target.value)}
                placeholder="Nombre de la cara (ej: Regen_Delantero)"
                className="sm:col-span-5 px-3 py-1.5 text-xs rounded-md border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-950 text-slate-900 dark:text-slate-100"
              />
              <button
                type="button"
                disabled={busy}
                onClick={() => void handleSaveFace()}
                className="sm:col-span-3 px-3 py-1.5 text-xs font-medium rounded-md bg-slate-800 hover:bg-slate-700 dark:bg-slate-700 dark:hover:bg-slate-600 text-white inline-flex items-center justify-center gap-1.5"
              >
                <Save className="w-3.5 h-3.5" /> Guardar cara
              </button>
              <button
                type="button"
                onClick={() =>
                  onUseExtractedFace({
                    headAssetId: extracted.headAssetId,
                    name: saveName || extracted.suggestedName,
                    isPreCutout: Boolean(staged?.isPreCutout),
                    autoFit: extracted.autoFit,
                    previewDataUrl: extracted.previewDataUrl,
                  })
                }
                className="sm:col-span-4 px-3 py-1.5 text-xs font-medium rounded-md bg-emerald-600 hover:bg-emerald-500 text-white inline-flex items-center justify-center gap-1.5"
              >
                Usar en Montaje <ArrowRight className="w-3.5 h-3.5" />
              </button>
            </div>
          </div>
        )}

        <div className="p-4 space-y-2.5">
          <div className="flex items-center justify-between text-xs">
            <span className="font-semibold text-slate-800 dark:text-slate-200">
              Biblioteca de Caras ({faces.length})
            </span>
            <span className="text-slate-500 dark:text-slate-400">caras_extraidas · caras_prueba</span>
          </div>
          {faces.length === 0 ? (
            <p className="text-xs text-slate-500 dark:text-slate-400">
              Aún no hay caras guardadas. Extrae una cara arriba o añade recortes en D:\DF11Studio\caras_prueba.
            </p>
          ) : (
            <div className="grid grid-cols-3 sm:grid-cols-5 gap-2 max-h-56 overflow-y-auto pr-1">
              {faces.map((f) => (
                <button
                  key={f.faceId}
                  type="button"
                  onClick={() => onPickSavedFace(f.faceId)}
                  className="p-1.5 rounded-lg border border-slate-200 dark:border-slate-800 hover:border-emerald-500 bg-slate-50 dark:bg-slate-950/60 flex flex-col items-center gap-1 text-center transition"
                >
                  <img src={f.thumbDataUrl} alt={f.name} className="w-12 h-12 object-contain rounded bg-slate-900/80" />
                  <span className="text-[11px] font-medium truncate w-full text-slate-700 dark:text-slate-300">{f.name}</span>
                </button>
              ))}
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
