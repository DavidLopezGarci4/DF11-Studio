import { useCallback, useEffect, useRef, useState } from 'react';
import { ArrowRight, Check, ImagePlus, Loader2, RotateCcw, Save, Shirt, Upload } from 'lucide-react';
import { ClubSeed, ShirtTemplateInfo, callBridge } from '../lib/ipc';

interface Props {
  clubs: Record<string, ClubSeed>;
  templates: ShirtTemplateInfo[];
  onTemplatesUpdated: (templates: ShirtTemplateInfo[]) => void;
  onSelectTemplateForComposer: (templateId: string) => void;
}

interface ShirtStagePayload {
  rawDataUrl: string;
  cleanShirtDataUrl: string;
  collarWidth: number;
  apexY: number;
  suggestedName: string;
}

export default function ShirtExtractorTool({
  clubs,
  templates,
  onTemplatesUpdated,
  onSelectTemplateForComposer,
}: Props) {
  const [staged, setStaged] = useState<ShirtStagePayload | null>(null);
  const [cleanUrl, setCleanUrl] = useState('');
  const [collarMetrics, setCollarMetrics] = useState<{ w: number; v: number } | null>(null);
  const [symmetrize, setSymmetrize] = useState(true);
  const [shoulderBoost, setShoulderBoost] = useState(0);
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [showRaw, setShowRaw] = useState(false);
  const [stageSkin, setStageSkin] = useState<'checker' | 'fm_dark' | 'fm_light'>('checker');

  const [displayName, setDisplayName] = useState('');
  const [clubId, setClubId] = useState('');
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState('');
  const [err, setErr] = useState('');

  const fileRef = useRef<HTMLInputElement>(null);
  const dragRef = useRef<{ sx: number; sy: number; ox: number; oy: number } | null>(null);
  const seqRef = useRef(0);
  const skipNextPreviewRef = useRef(false);

  const applyStage = (res: ShirtStagePayload) => {
    skipNextPreviewRef.current = true;
    setStaged(res);
    setCleanUrl(res.cleanShirtDataUrl);
    setCollarMetrics({ w: res.collarWidth, v: res.apexY });
    setSymmetrize(true);
    setShoulderBoost(0);
    setZoom(1);
    setPan({ x: 0, y: 0 });
    setShowRaw(false);
    setDisplayName(res.suggestedName || 'Camiseta_Club');
    setMsg('');
    setErr('');
  };

  const handlePickNative = useCallback(async () => {
    if (!window.pywebview?.api?.pick_raw_shirt_source) {
      fileRef.current?.click();
      return;
    }
    setBusy(true); setErr('');
    try {
      const res = await callBridge<ShirtStagePayload | null>('pick_raw_shirt_source');
      if (res?.cleanShirtDataUrl) applyStage(res);
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'No se pudo cargar la camiseta.');
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
      const res = await callBridge<ShirtStagePayload>('load_raw_shirt_source', dataUrl, file.name);
      if (res?.cleanShirtDataUrl) applyStage(res);
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Formato inválido.');
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    if (!staged) return undefined;
    if (skipNextPreviewRef.current) {
      skipNextPreviewRef.current = false;
      return undefined;
    }
    const seq = ++seqRef.current;
    const t = window.setTimeout(async () => {
      try {
        const res = await callBridge<{ cleanShirtDataUrl: string; collarWidth: number; apexY: number }>(
          'preview_shirt_extraction',
          { symmetrizeShoulders: symmetrize, shoulderBoost, zoom, panX: pan.x, panY: pan.y },
        );
        if (seq === seqRef.current && res?.cleanShirtDataUrl) {
          setCleanUrl(res.cleanShirtDataUrl);
          setCollarMetrics({ w: res.collarWidth, v: res.apexY });
        }
      } catch {
        /* ignore transient drag */
      }
    }, 110);
    return () => window.clearTimeout(t);
  }, [staged, symmetrize, shoulderBoost, zoom, pan.x, pan.y]);

  const handleSaveTemplate = async (sendToComposer: boolean) => {
    if (!cleanUrl) return;
    setBusy(true); setErr(''); setMsg('');
    try {
      const res = await callBridge<{ savedTemplateId: string; templates: ShirtTemplateInfo[] }>('save_shirt_template', {
        displayName: displayName.trim() || 'Camiseta Club',
        clubId,
        templateId: displayName.trim(),
        symmetrizeShoulders: symmetrize,
        shoulderBoost,
        zoom,
        panX: pan.x,
        panY: pan.y,
      });
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

  const stageBgClass =
    stageSkin === 'fm_dark'
      ? 'bg-[#0b111e] text-slate-200'
      : stageSkin === 'fm_light'
      ? 'bg-[#e6ebf2] text-slate-800'
      : 'bg-[repeating-conic-gradient(#334155_0%_25%,#0f172a_0%_50%)] bg-[length:16px_16px] text-slate-200';
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
          <span className="font-medium text-slate-900 dark:text-white">Extractor · Solo Camiseta</span>
          <span className="tabular-nums font-mono">
            {collarMetrics ? `Cuello ${collarMetrics.w}px · V=${collarMetrics.v}` : '260 × 310 px'}
          </span>
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
              if (!staged) return;
              e.preventDefault();
              const delta = e.deltaY < 0 ? 0.06 : -0.06;
              setZoom((z) => Number(Math.min(2.6, Math.max(0.5, z + delta)).toFixed(3)));
            }}
            onPointerDown={(e) => {
              if (!staged || (e.target as HTMLElement | null)?.closest('button')) return;
              dragRef.current = { sx: e.clientX, sy: e.clientY, ox: pan.x, oy: pan.y };
              e.currentTarget.setPointerCapture?.(e.pointerId);
            }}
            onPointerMove={(e) => {
              if (!dragRef.current) return;
              setPan({
                x: Math.round(dragRef.current.ox + (e.clientX - dragRef.current.sx)),
                y: Math.round(dragRef.current.oy + (e.clientY - dragRef.current.sy)),
              });
            }}
            onPointerUp={() => { dragRef.current = null; }}
            onPointerCancel={() => { dragRef.current = null; }}
            className="relative w-[260px] h-[310px] overflow-hidden rounded-lg border border-emerald-500/40 select-none flex items-center justify-center cursor-grab active:cursor-grabbing"
          >
            {!staged ? (
              <button
                type="button"
                onClick={() => void handlePickNative()}
                className="w-[222px] h-[276px] rounded-xl border-2 border-dashed border-slate-500 flex flex-col items-center justify-center gap-2 px-4 text-center text-xs text-slate-200 bg-slate-900/80 cursor-pointer hover:border-emerald-500 transition"
              >
                <Upload className="w-6 h-6 text-emerald-400" />
                <span className="font-medium">Sube imagen para extraer su camiseta</span>
                <span className="text-[11px] text-slate-400">Elimina cabeza, cuello y fondo conservando hombros blancos y oscuros</span>
              </button>
            ) : (
              <img
                src={showRaw ? staged.rawDataUrl : cleanUrl}
                alt="Plantilla de camiseta limpia"
                className="w-[260px] h-[310px] object-contain pointer-events-none"
              />
            )}

            {busy && (
              <div className="absolute inset-0 bg-slate-950/55 flex items-center justify-center gap-2 text-xs font-medium text-white">
                <Loader2 className="w-4 h-4 animate-spin" /> Limpiando camiseta…
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
          {staged && (
            <button type="button" onClick={() => setShowRaw((v) => !v)} className={segBtn(showRaw)}>
              {showRaw ? 'Ver limpia' : 'Ver original'}
            </button>
          )}
        </div>
      </section>

      <section className="lg:col-span-7 rounded-xl shadow-xs border border-slate-200/80 dark:border-slate-800 bg-white dark:bg-slate-900 divide-y divide-slate-200/80 dark:divide-slate-800">
        <div className="p-4 space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <h2 className="text-xs font-semibold uppercase tracking-wider text-emerald-700 dark:text-emerald-400">
                Herramienta · Extractor de Plantillas de Camiseta
              </h2>
              <p className="text-xs text-slate-600 dark:text-slate-400 mt-0.5">
                Extrae solo la prenda (incluidas equipaciones blancas sobre fondo claro) y guárdala en tshirt_templates.
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
                className="px-3 py-1.5 text-xs font-medium rounded-md bg-emerald-600 hover:bg-emerald-500 text-white inline-flex items-center gap-1.5"
              >
                <ImagePlus className="w-3.5 h-3.5" /> Subir camiseta
              </button>
              {staged && (
                <button
                  type="button"
                  onClick={() => { setZoom(1); setPan({ x: 0, y: 0 }); setShoulderBoost(0); setSymmetrize(true); }}
                  className="px-2.5 py-1.5 text-xs rounded-md bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 inline-flex items-center gap-1"
                >
                  <RotateCcw className="w-3.5 h-3.5" /> 1:1
                </button>
              )}
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-12 gap-3 items-center text-xs">
            <label className="sm:col-span-5 inline-flex items-center gap-2 text-slate-700 dark:text-slate-300">
              <input
                type="checkbox"
                checked={symmetrize}
                disabled={!staged}
                onChange={(e) => setSymmetrize(e.target.checked)}
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
                disabled={!staged}
                value={shoulderBoost}
                onChange={(e) => setShoulderBoost(Number(e.target.value))}
                className="w-full accent-emerald-600 disabled:opacity-40"
              />
              <span>{Math.round(shoulderBoost * 100)}%</span>
            </label>
          </div>
        </div>

        <div className="p-4 space-y-3 bg-slate-50/60 dark:bg-slate-950/35">
          <div className="grid grid-cols-1 sm:grid-cols-12 gap-2.5 items-center text-xs">
            <input
              aria-label="Nombre de plantilla de camiseta"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              placeholder="Nombre (ej: Real Madrid Blanca)"
              className="sm:col-span-6 px-3 py-1.5 rounded-md border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-950 text-slate-900 dark:text-slate-100"
            />
            <select
              aria-label="Club asociado a plantilla"
              value={clubId}
              onChange={(e) => setClubId(e.target.value)}
              className="sm:col-span-6 px-2.5 py-1.5 rounded-md border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-950 text-slate-900 dark:text-slate-100"
            >
              <option value="">Sin club fijo (uso libre)</option>
              {Object.entries(clubs).map(([cid, info]) => (
                <option key={cid} value={cid}>
                  {info.name} (#{cid})
                </option>
              ))}
            </select>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              disabled={!cleanUrl || busy}
              onClick={() => void handleSaveTemplate(false)}
              className="px-3 py-1.5 text-xs font-medium rounded-md bg-slate-800 hover:bg-slate-700 dark:bg-slate-700 dark:hover:bg-slate-600 disabled:opacity-45 text-white inline-flex items-center gap-1.5"
            >
              <Save className="w-3.5 h-3.5" /> Guardar en tshirt_templates
            </button>
            <button
              type="button"
              disabled={!cleanUrl || busy}
              onClick={() => void handleSaveTemplate(true)}
              className="px-3.5 py-1.5 text-xs font-medium rounded-md bg-emerald-600 hover:bg-emerald-500 disabled:opacity-45 text-white inline-flex items-center gap-1.5"
            >
              Guardar y usar en Montaje <ArrowRight className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>

        <div className="p-4 space-y-2.5">
          <div className="flex items-center justify-between text-xs">
            <span className="font-semibold text-slate-800 dark:text-slate-200 inline-flex items-center gap-1.5">
              <Shirt className="w-3.5 h-3.5 text-emerald-500" /> Plantillas en tshirt_templates ({templates.length})
            </span>
            <span className="text-slate-500 dark:text-slate-400">Haz clic para enviar al Montaje</span>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5 max-h-60 overflow-y-auto pr-1">
            {templates.map((t) => (
              <button
                key={t.templateId}
                type="button"
                onClick={() => onSelectTemplateForComposer(t.templateId)}
                className="p-2 rounded-lg border border-slate-200 dark:border-slate-800 hover:border-emerald-500 bg-slate-50 dark:bg-slate-950/60 flex flex-col items-center gap-1 text-center transition"
              >
                <img src={t.thumbDataUrl} alt={t.displayName} className="w-16 h-16 object-contain rounded bg-[#0f172a]" />
                <span className="text-xs font-medium truncate w-full text-slate-800 dark:text-slate-200">{t.displayName}</span>
                {t.clubId && clubs[t.clubId] && (
                  <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 truncate max-w-full">
                    {clubs[t.clubId].name}
                  </span>
                )}
              </button>
            ))}
          </div>
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
