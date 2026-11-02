import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Check, Crosshair, Download, FolderOpen, ImagePlus, Loader2, RotateCcw, Sparkles, Upload } from 'lucide-react';
import { ClubSeed, StorageHealth, callBridge } from '../lib/ipc';

export interface StudioJumpPayload { uid: string; previewDataUrl: string; clubId?: string; }
interface Props {
  clubs: Record<string, ClubSeed>;
  exportDir: string;
  onExportDirChange: (dir: string, sh?: StorageHealth) => void;
  initialJump: StudioJumpPayload | null;
  onConsumeJump?: () => void;
}

const UID_RE = /^(?:r-)?[0-9]{1,12}$/;
type KitMode = 'original' | 'club' | 'staff_polo' | 'staff_suit';
type BgMode = 'transparent' | 'white_df11' | 'pearl_studio' | 'stadium_bokeh' | 'tunnel_club' | 'office_staff' | 'custom';

export default function StudioView({ clubs, exportDir, onExportDirChange, initialJump, onConsumeJump }: Props) {
  const [previewUrl, setPreviewUrl] = useState('');
  const [hasPortrait, setHasPortrait] = useState(false);
  const [busy, setBusy] = useState(false);
  const [errorMsg, setErrorMsg] = useState('');
  const [savedMsg, setSavedMsg] = useState('');
  const [showGuides, setShowGuides] = useState(true);
  const [stageSkin, setStageSkin] = useState<'fm_dark' | 'fm_light' | 'checker'>('fm_dark');

  const [removeBg, setRemoveBg] = useState(true);
  const [harmonize, setHarmonize] = useState(true);
  const [scale, setScale] = useState(1.0);
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  const [kitMode, setKitMode] = useState<KitMode>('original');
  const [clubId, setClubId] = useState('1736');
  const [customKitDirty, setCustomKitDirty] = useState(false);
  const [customPrimary, setCustomPrimary] = useState('#F7F8FA');
  const [customSecondary, setCustomSecondary] = useState('#1E293B');
  const [customPattern, setCustomPattern] = useState('solid');

  const [bgMode, setBgMode] = useState<BgMode>('white_df11');
  const [bgBlur, setBgBlur] = useState(0);
  const [hasExtractedBg, setHasExtractedBg] = useState(false);
  const [uid, setUid] = useState('');
  const [fmt, setFmt] = useState<'png' | 'jpg'>('png');
  const [updateXml, setUpdateXml] = useState(true);

  const dragRef = useRef<{ startX: number; startY: number; origX: number; origY: number } | null>(null);
  const reqSeqRef = useRef(0);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const bgInputRef = useRef<HTMLInputElement>(null);

  const syncClubDefaults = useCallback((cid: string) => {
    const c = clubs[cid];
    setCustomKitDirty(false);
    setCustomPrimary(c?.primary ?? '#F7F8FA');
    setCustomSecondary(c?.secondary ?? '#F8FAFC');
    setCustomPattern(c?.pattern ?? 'solid');
  }, [clubs]);

  const composeParams = useMemo(() => ({
    removeBg, harmonize, kitMode, clubId, bgMode, bgBlur, scale,
    offsetX: offset.x, offsetY: offset.y,
    customKitDirty, customPrimary, customSecondary, customPattern,
  }), [removeBg, harmonize, kitMode, clubId, bgMode, bgBlur, scale, offset.x, offset.y, customKitDirty, customPrimary, customSecondary, customPattern]);

  useEffect(() => {
    if (!initialJump) return;
    setUid(initialJump.uid);
    setPreviewUrl(initialJump.previewDataUrl);
    setHasPortrait(true);
    setRemoveBg(false);
    setHarmonize(true);
    if (initialJump.clubId && clubs[initialJump.clubId]) {
      setClubId(initialJump.clubId);
      syncClubDefaults(initialJump.clubId);
      setKitMode('club');
    }
    onConsumeJump?.();
  }, [initialJump, clubs, onConsumeJump, syncClubDefaults]);

  const handleFileBlob = useCallback(async (file: File, extractOriginalBg = false) => {
    setErrorMsg(''); setSavedMsg(''); setBusy(true);
    try {
      const dataUrl = await new Promise<string>((res, rej) => {
        const r = new FileReader();
        r.onload = () => res(String(r.result));
        r.onerror = () => rej(new Error('No se pudo leer la imagen.'));
        r.readAsDataURL(file);
      });
      const resetParams = { ...composeParams, scale: 1.0, offsetX: 0, offsetY: 0 };
      const out = await callBridge<{ previewDataUrl: string; cleanBgDataUrl: string }>('upload_studio_image', dataUrl, removeBg, harmonize, extractOriginalBg, resetParams);
      reqSeqRef.current += 1;
      if (out.previewDataUrl) { setPreviewUrl(out.previewDataUrl); setHasPortrait(true); }
      if (extractOriginalBg && out.cleanBgDataUrl) { setHasExtractedBg(true); setBgMode('custom'); }
      setOffset({ x: 0, y: 0 }); setScale(1.0);
    } catch (e) {
      setErrorMsg(e instanceof Error ? e.message : 'Formato o tamaño inválido (máx. 20 MB / 25 MP).');
    } finally {
      setBusy(false);
    }
  }, [composeParams, removeBg, harmonize]);

  useEffect(() => {
    const onPaste = (ev: ClipboardEvent) => {
      const f = Array.from(ev.clipboardData?.items ?? []).find((i) => i.type.startsWith('image/'))?.getAsFile();
      if (f) void handleFileBlob(f);
    };
    window.addEventListener('paste', onPaste);
    return () => window.removeEventListener('paste', onPaste);
  }, [handleFileBlob]);

  useEffect(() => {
    if (!hasPortrait) return undefined;
    const seq = ++reqSeqRef.current;
    const t = window.setTimeout(async () => {
      try {
        const res = await callBridge<{ previewDataUrl: string }>('render_studio_preview', composeParams);
        if (seq === reqSeqRef.current && res?.previewDataUrl) setPreviewUrl(res.previewDataUrl);
      } catch { /* transient drag */ }
    }, 80);
    return () => window.clearTimeout(t);
  }, [hasPortrait, composeParams]);

  const handleExtractBg = async () => {
    setErrorMsg(''); setBusy(true);
    try {
      const res = await callBridge<{ cleanBgDataUrl: string; previewDataUrl: string }>('extract_studio_background', composeParams);
      reqSeqRef.current += 1;
      setHasExtractedBg(true); setBgMode('custom');
      if (res?.previewDataUrl) setPreviewUrl(res.previewDataUrl);
    } catch (e) {
      setErrorMsg(e instanceof Error ? e.message : 'Sube primero un retrato para extraer su fondo.');
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
      const out = await callBridge<{ bgDataUrl: string; previewDataUrl: string }>('upload_custom_background', dataUrl, composeParams);
      reqSeqRef.current += 1;
      setBgMode('custom');
      if (out?.previewDataUrl) setPreviewUrl(out.previewDataUrl);
    } catch (e) {
      setErrorMsg(e instanceof Error ? e.message : 'Fondo inválido (máx. 20 MB / 25 MP).');
    } finally {
      setBusy(false);
    }
  };

  const uidInvalid = uid.trim().length > 0 && !UID_RE.test(uid.trim());

  const handleExport = async () => {
    const cleanUid = uid.trim();
    if (!UID_RE.test(cleanUid)) { setErrorMsg('Introduce un ID válido (dígitos o r-<dígitos>, máx. 12 cifras).'); return; }
    setBusy(true); setErrorMsg('');
    try {
      const res = await callBridge<{ savedPath: string }>('export_studio_card', {
        uid: cleanUid, fmt, updateConfigXml: updateXml, ...composeParams,
      });
      setSavedMsg(`Guardado: ${res.savedPath ?? `${cleanUid}.${fmt}`}`);
    } catch (e) {
      setErrorMsg(e instanceof Error ? e.message : 'Error al exportar la ficha DF11.');
    } finally {
      setBusy(false);
    }
  };

  const stageBgClass = stageSkin === 'fm_dark' ? 'bg-[#0b111e] text-slate-200' : stageSkin === 'fm_light' ? 'bg-[#e6ebf2] text-slate-800' : 'bg-[repeating-conic-gradient(#cbd5e1_0%_25%,#f8fafc_0%_50%)] dark:bg-[repeating-conic-gradient(#1e293b_0%_25%,#0f172a_0%_50%)] bg-[length:16px_16px]';
  const segBtn = (active: boolean) => `px-2.5 py-1.5 text-xs font-medium rounded-md transition ${active ? 'bg-emerald-600 text-white' : 'bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-slate-700'}`;

  return (
    <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
      <section className="lg:col-span-5 rounded-xl shadow-xs border border-slate-200/80 dark:border-slate-800 bg-white dark:bg-slate-900 p-5 flex flex-col items-center gap-4">
        <div className="w-full flex items-center justify-between text-xs text-slate-600 dark:text-slate-400">
          <span className="font-medium text-slate-900 dark:text-white">Lienzo Oficial DF11</span>
          <span className="tabular-nums font-mono">260 × 310 px</span>
        </div>

        <div onDragOver={(e) => e.preventDefault()} onDrop={(e) => { e.preventDefault(); const f = e.dataTransfer.files?.[0]; if (f) void handleFileBlob(f); }} className={`w-full rounded-lg p-6 flex flex-col items-center justify-center transition ${stageBgClass} border border-slate-200/60 dark:border-slate-800`}>
          <div
            onPointerDown={(e) => { dragRef.current = { startX: e.clientX, startY: e.clientY, origX: offset.x, origY: offset.y }; e.currentTarget.setPointerCapture(e.pointerId); }}
            onPointerMove={(e) => { if (dragRef.current) setOffset({ x: Math.round(dragRef.current.origX + (e.clientX - dragRef.current.startX)), y: Math.round(dragRef.current.origY + (e.clientY - dragRef.current.startY)) }); }}
            onPointerUp={() => { dragRef.current = null; }}
            className="relative w-[260px] h-[310px] select-none cursor-grab active:cursor-grabbing flex items-center justify-center"
          >
            {previewUrl ? (
              <img src={previewUrl} alt="Previsualización DF11 260x310" className="w-[260px] h-[310px] pointer-events-none" />
            ) : (
              <button type="button" onClick={() => fileInputRef.current?.click()} className="w-[222px] h-[276px] rounded-xl border-2 border-dashed border-slate-400/70 dark:border-slate-600 flex flex-col items-center justify-center gap-2 px-4 text-center text-xs text-slate-600 dark:text-slate-300 bg-white/70 dark:bg-slate-900/70">
                <Upload className="w-6 h-6 text-emerald-600 dark:text-emerald-400" />
                <span className="font-medium">Arrastra foto, haz clic o pulsa Ctrl+V</span>
                <span className="text-[11px] text-slate-500 dark:text-slate-400">PNG · JPG · WEBP · AVIF (≤ 20 MB)</span>
              </button>
            )}
            {showGuides && (
              <svg className="absolute inset-0 w-[260px] h-[310px] pointer-events-none" viewBox="0 0 260 310">
                <line x1="19" y1="24" x2="241" y2="24" stroke="#10b981" strokeDasharray="3 3" strokeWidth="1" />
                <line x1="19" y1="112" x2="241" y2="112" stroke="#38bdf8" strokeDasharray="4 2" strokeWidth="1" />
                <line x1="19" y1="292" x2="241" y2="292" stroke="#f59e0b" strokeDasharray="3 3" strokeWidth="1" />
                <line x1="130" y1="17" x2="130" y2="292" stroke="#94a3b8" strokeOpacity="0.4" strokeDasharray="2 4" strokeWidth="1" />
              </svg>
            )}
            {busy && (
              <div className="absolute inset-0 bg-slate-950/45 rounded-lg flex items-center justify-center gap-2 text-xs font-medium text-white">
                <Loader2 className="w-4 h-4 animate-spin" /> Procesando DirectML…
              </div>
            )}
          </div>
        </div>

        <div className="w-full flex flex-wrap items-center justify-between gap-2 text-xs">
          <div className="flex items-center gap-1">
            <button type="button" onClick={() => setStageSkin('fm_dark')} className={segBtn(stageSkin === 'fm_dark')}>Skin Oscura</button>
            <button type="button" onClick={() => setStageSkin('fm_light')} className={segBtn(stageSkin === 'fm_light')}>Skin Clara</button>
            <button type="button" onClick={() => setStageSkin('checker')} className={segBtn(stageSkin === 'checker')}>Alfa 0</button>
          </div>
          <span className="tabular-nums text-slate-500 dark:text-slate-400">X:{offset.x} · Y:{offset.y}</span>
        </div>
      </section>

      <section className="lg:col-span-7 rounded-xl shadow-xs border border-slate-200/80 dark:border-slate-800 bg-white dark:bg-slate-900 divide-y divide-slate-200/80 dark:divide-slate-800">
        <div className="p-4 flex items-center justify-between gap-4">
          <div>
            <h2 className="text-xs font-semibold uppercase tracking-wider text-emerald-700 dark:text-emerald-400">Capa 3 · Marco Maestro DF11</h2>
            <p className="text-xs text-slate-600 dark:text-slate-400 mt-0.5">Bisel interior simétrico y anillo transparente Alpha = 0 bloqueado sin pérdidas.</p>
          </div>
          <button type="button" onClick={() => setShowGuides((g) => !g)} className={segBtn(showGuides)}>
            <span className="inline-flex items-center gap-1.5"><Crosshair className="w-3.5 h-3.5" /> Guías Ópticas</span>
          </button>
        </div>

        <div className="p-4 space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-xs font-semibold uppercase tracking-wider text-emerald-700 dark:text-emerald-400">Capa 2 · Persona (Futbolista / Staff)</h2>
            <div className="flex items-center gap-2">
              <input ref={fileInputRef} type="file" accept="image/*" className="hidden" onChange={(e) => { const f = e.target.files?.[0]; if (f) void handleFileBlob(f); }} />
              <button type="button" onClick={() => fileInputRef.current?.click()} className="px-3 py-1.5 text-xs font-medium rounded-md bg-emerald-600 hover:bg-emerald-500 text-white inline-flex items-center gap-1.5"><ImagePlus className="w-3.5 h-3.5" /> Subir retrato</button>
              <button type="button" onClick={() => { setScale(1.0); setOffset({ x: 0, y: 0 }); }} className="px-2.5 py-1.5 text-xs rounded-md bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 inline-flex items-center gap-1"><RotateCcw className="w-3.5 h-3.5" /> 1:1</button>
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 items-center text-xs">
            <label className="inline-flex items-center gap-2 text-slate-700 dark:text-slate-300"><input type="checkbox" checked={removeBg} onChange={(e) => setRemoveBg(e.target.checked)} className="accent-emerald-600" /> Quitar fondo (BiRefNet)</label>
            <label className="inline-flex items-center gap-2 text-slate-700 dark:text-slate-300"><input type="checkbox" checked={harmonize} onChange={(e) => setHarmonize(e.target.checked)} className="accent-emerald-600" /> Luz Estudio DF11</label>
            <label className="flex items-center gap-2 text-slate-700 dark:text-slate-300 tabular-nums">
              <span>Zoom</span>
              <input type="range" min="0.55" max="1.75" step="0.02" value={scale} onChange={(e) => setScale(Number(e.target.value))} className="w-full accent-emerald-600" />
              <span>{Math.round(scale * 100)}%</span>
            </label>
          </div>

          <div className="pt-2 border-t border-slate-100 dark:border-slate-800/70 space-y-2.5">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="text-xs font-medium text-slate-700 dark:text-slate-300">Equipación (P_clothes = 0):</span>
              <div className="flex flex-wrap items-center gap-1">
                <button type="button" onClick={() => setKitMode('original')} className={segBtn(kitMode === 'original')}>Original</button>
                <button type="button" onClick={() => setKitMode('club')} className={segBtn(kitMode === 'club')}>Club</button>
                <button type="button" onClick={() => setKitMode('staff_polo')} className={segBtn(kitMode === 'staff_polo')}>Polo Staff</button>
                <button type="button" onClick={() => setKitMode('staff_suit')} className={segBtn(kitMode === 'staff_suit')}>Traje Staff</button>
              </div>
            </div>
            {kitMode !== 'original' && (
              <div className="grid grid-cols-1 sm:grid-cols-12 gap-2 items-center pt-1">
                <select aria-label="Selector de club" value={clubId} onChange={(e) => { setClubId(e.target.value); syncClubDefaults(e.target.value); }} className="sm:col-span-6 px-2.5 py-1.5 text-xs rounded-md border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-950 text-slate-900 dark:text-slate-100 truncate">
                  {Object.entries(clubs).map(([cid, info]) => <option key={cid} value={cid}>{info.name} (#{cid})</option>)}
                </select>
                <select aria-label="Patrón textil" value={customPattern} onChange={(e) => { setCustomPattern(e.target.value); setCustomKitDirty(true); }} className="sm:col-span-3 px-2 py-1.5 text-xs rounded-md border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-950 text-slate-900 dark:text-slate-100">
                  <option value="solid">Liso</option><option value="stripes">Rayas</option><option value="halves">Mitades</option><option value="hoops">Franjas</option><option value="sash">Banda</option>
                </select>
                <div className="sm:col-span-3 flex items-center justify-end gap-1.5">
                  <input type="color" title="Color primario textil" value={customPrimary} onChange={(e) => { setCustomPrimary(e.target.value); setCustomKitDirty(true); }} className="w-7 h-7 rounded cursor-pointer border border-slate-300 dark:border-slate-700 bg-transparent" />
                  <input type="color" title="Color secundario textil" value={customSecondary} onChange={(e) => { setCustomSecondary(e.target.value); setCustomKitDirty(true); }} className="w-7 h-7 rounded cursor-pointer border border-slate-300 dark:border-slate-700 bg-transparent" />
                </div>
              </div>
            )}
          </div>
        </div>

        <div className="p-4 space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-xs font-semibold uppercase tracking-wider text-emerald-700 dark:text-emerald-400">Capa 1 · Fondo de Escena (Opcional)</h2>
            <div className="flex items-center gap-2">
              <input ref={bgInputRef} type="file" accept="image/*" className="hidden" onChange={(e) => { const f = e.target.files?.[0]; if (f) void handleCustomBgUpload(f); }} />
              <button type="button" onClick={() => bgInputRef.current?.click()} className="px-2.5 py-1 text-xs rounded-md bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300">Subir fondo</button>
              <button type="button" disabled={!hasPortrait || busy} onClick={() => void handleExtractBg()} className="px-2.5 py-1 text-xs rounded-md bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 disabled:opacity-45 inline-flex items-center gap-1"><Sparkles className="w-3 h-3" /> Extraer de foto</button>
            </div>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 items-center text-xs">
            <select aria-label="Modo de fondo" value={bgMode} onChange={(e) => setBgMode(e.target.value as BgMode)} className="px-2.5 py-1.5 rounded-md border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-950 text-slate-900 dark:text-slate-100">
              <option value="transparent">Sin fondo (Transparente)</option>
              <option value="white_df11">Blanco Estudio DF11 (Oficial)</option>
              <option value="pearl_studio">Gris Perla Estudio</option>
              <option value="stadium_bokeh">Estadio Nocturno</option>
              <option value="tunnel_club">Túnel de Vestuarios</option>
              <option value="office_staff">Despacho Staff / Prensa</option>
              <option value="custom">{hasExtractedBg ? 'Fondo Limpio Extraído / Propio' : 'Fondo Personalizado'}</option>
            </select>
            <label className="flex items-center gap-2 text-slate-700 dark:text-slate-300 tabular-nums">
              <span>Bokeh</span>
              <input type="range" min="0" max="18" step="0.5" disabled={bgMode === 'transparent'} value={bgBlur} onChange={(e) => setBgBlur(Number(e.target.value))} className="w-full accent-emerald-600 disabled:opacity-40" />
              <span>{bgBlur}px</span>
            </label>
          </div>
        </div>

        <div className="p-4 space-y-3 bg-slate-50/70 dark:bg-slate-950/40 rounded-b-xl">
          <div className="grid grid-cols-1 sm:grid-cols-12 gap-2.5 items-center">
            <div className="sm:col-span-5">
              <input aria-label="ID Football Manager" value={uid} onChange={(e) => setUid(e.target.value)} placeholder="ID FM (ej: 29184012 o r-2002049102)" className="w-full px-3 py-1.5 text-xs rounded-md border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-950 text-slate-900 dark:text-slate-100 tabular-nums font-mono" />
            </div>
            <div className="sm:col-span-3 flex items-center gap-1">
              <button type="button" onClick={() => setFmt('png')} className={segBtn(fmt === 'png')}>PNG Oficial</button>
              <button type="button" onClick={() => setFmt('jpg')} className={segBtn(fmt === 'jpg')}>JPG</button>
            </div>
            <div className="sm:col-span-4 flex justify-end">
              <button type="button" disabled={busy || !hasPortrait} onClick={handleExport} className="w-full px-3 py-1.5 text-xs font-medium rounded-md bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white inline-flex items-center justify-center gap-1.5"><Download className="w-3.5 h-3.5" /> Exportar DF11</button>
            </div>
          </div>
          <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-slate-600 dark:text-slate-400">
            <label className="inline-flex items-center gap-2"><input type="checkbox" checked={updateXml} disabled={fmt !== 'png'} onChange={(e) => setUpdateXml(e.target.checked)} className="accent-emerald-600" /> Actualizar config.xml atómico</label>
            <button type="button" onClick={async () => { try { const p = await callBridge<{ path: string; storageHealth?: StorageHealth } | null>('choose_directory', 'export'); if (p?.path) onExportDirChange(p.path, p.storageHealth); } catch (e) { setErrorMsg(e instanceof Error ? e.message : 'Carpeta no válida.'); } }} title={exportDir} className="max-w-[260px] truncate inline-flex items-center gap-1 text-slate-700 dark:text-slate-300 hover:underline"><FolderOpen className="w-3.5 h-3.5 shrink-0" /> {exportDir}</button>
          </div>
          {uidInvalid && <p className="text-xs text-amber-600 dark:text-amber-400">Usa dígitos o r-&lt;dígitos&gt; (máx. 12 cifras).</p>}
          {errorMsg && <p className="text-xs text-rose-600 dark:text-rose-400">{errorMsg}</p>}
          {savedMsg && <p className="text-xs text-emerald-700 dark:text-emerald-400 inline-flex items-center gap-1"><Check className="w-3.5 h-3.5" /> {savedMsg}</p>}
        </div>
      </section>
    </div>
  );
}
