import { useCallback, useEffect, useState } from 'react';
import { AlertTriangle, ArrowUpRight, Check, ClipboardPaste, Copy, FolderOpen, Play, Radio, RefreshCw, ShieldAlert, Square, Tag } from 'lucide-react';
import { ClubSeed, ExportVariant, StorageHealth, callBridge } from '../lib/ipc';
import { StudioJumpPayload } from './StudioView';

interface RegenRow { uid: string; clubId: string; }
interface SyncSummary { total_found: number; processed: number; skipped: number; failed?: number; cancelled: boolean; aborted_by_shrink_guard: boolean; }

interface Props {
  clubs: Record<string, ClubSeed>;
  vaultDir: string;
  exportDir: string;
  exportPureDir?: string;
  exportVariant?: ExportVariant;
  fmGraphicsCollision?: boolean;
  storageHealth: StorageHealth | null;
  liveWatch?: boolean;
  onLiveWatchChange?: (watching: boolean) => void;
  onVaultChange: (dir: string) => void;
  onExportChange: (dir: string, sh?: StorageHealth, fmGraphicsCollision?: boolean) => void;
  onExportPureChange?: (dir: string, sh?: StorageHealth, fmGraphicsCollision?: boolean) => void;
  onExportVariantChange?: (variant: ExportVariant) => void;
  onJumpToStudio: (payload: StudioJumpPayload) => void;
}

export default function RegensSyncView({
  clubs,
  vaultDir,
  exportDir,
  exportPureDir,
  exportVariant,
  fmGraphicsCollision,
  storageHealth,
  liveWatch: externalLiveWatch,
  onLiveWatchChange,
  onVaultChange,
  onExportChange,
  onExportPureChange,
  onExportVariantChange,
  onJumpToStudio,
}: Props) {
  const [totalFound, setTotalFound] = useState(0);
  const [sample, setSample] = useState<RegenRow[]>([]);
  const [selectedUids, setSelectedUids] = useState<Record<string, boolean>>({});
  const [myClubId, setMyClubId] = useState('1736');
  const [applyKits, setApplyKits] = useState(true);
  const [harmonize, setHarmonize] = useState(true);
  const [localLiveWatch, setLocalLiveWatch] = useState(false);
  const [localPureDir, setLocalPureDir] = useState(exportPureDir ?? 'D:\\DF11Studio\\Exports\\000_DF11_Pure_Override');
  const [localVariant, setLocalVariant] = useState<ExportVariant>(exportVariant ?? 'classic');
  const [localFmCollision, setLocalFmCollision] = useState(fmGraphicsCollision ?? false);
  const [running, setRunning] = useState(false);
  const [importText, setImportText] = useState('');
  const [showImporter, setShowImporter] = useState(false);
  const [copiedArg, setCopiedArg] = useState(false);
  const [lastSync, setLastSync] = useState<SyncSummary | null>(null);
  const [statusMsg, setStatusMsg] = useState('');

  useEffect(() => {
    if (exportPureDir) setLocalPureDir(exportPureDir);
  }, [exportPureDir]);

  useEffect(() => {
    if (exportVariant) setLocalVariant(exportVariant);
  }, [exportVariant]);

  useEffect(() => {
    if (typeof fmGraphicsCollision === 'boolean') setLocalFmCollision(fmGraphicsCollision);
  }, [fmGraphicsCollision]);

  const activeVariant: ExportVariant = exportVariant ?? localVariant;
  const effectivePureDir = exportPureDir || localPureDir;
  const effectiveFmCollision = fmGraphicsCollision ?? localFmCollision;

  const liveWatch = externalLiveWatch ?? localLiveWatch;
  const setLiveWatch = (val: boolean) => { setLocalLiveWatch(val); onLiveWatchChange?.(val); };

  const refreshVault = useCallback(async () => {
    try {
      const res = await callBridge<{ totalFound?: number; sample?: RegenRow[] }>('scan_vault_summary');
      setTotalFound(res?.totalFound ?? 0);
      setSample(res?.sample ?? []);
    } catch (e) {
      setStatusMsg(e instanceof Error ? e.message : 'No se pudo escanear la bóveda NG_Regens.');
    }
  }, []);

  useEffect(() => {
    setSelectedUids({});
    void refreshVault();
  }, [refreshVault, vaultDir]);

  const handleSync = async (allowShrink = false) => {
    setRunning(true); setStatusMsg('');
    try {
      const res = await callBridge<SyncSummary>('start_regens_sync', {
        applyClubKits: applyKits,
        harmonize,
        bgMode: 'white_df11',
        allowShrink,
        variant: activeVariant,
      });
      setLastSync(res);
      await refreshVault();
    } catch (e) {
      setStatusMsg(e instanceof Error ? e.message : 'Error durante la sincronización por lotes.');
    } finally {
      setRunning(false);
    }
  };

  const handleToggleLiveWatch = async (
    next: boolean,
    nextKits = applyKits,
    nextHarm = harmonize,
    nextVar: ExportVariant = activeVariant,
  ) => {
    try {
      const res = await callBridge<{ watching?: boolean }>('toggle_live_watch', next, {
        applyClubKits: nextKits,
        harmonize: nextHarm,
        bgMode: 'white_df11',
        variant: nextVar,
      });
      setLiveWatch(Boolean(res?.watching ?? next));
    } catch (e) {
      setStatusMsg(e instanceof Error ? e.message : 'No se pudo cambiar el estado de Live Disk Sync.');
    }
  };

  const handleSelectVariant = (next: ExportVariant) => {
    if (next === activeVariant) return;
    setLocalVariant(next);
    if (onExportVariantChange) {
      onExportVariantChange(next);
    } else {
      void callBridge('set_export_variant', next).catch(() => {});
    }
    if (liveWatch) {
      void handleToggleLiveWatch(true, applyKits, harmonize, next);
    }
  };

  const handleTagClub = async () => {
    const targets = Object.keys(selectedUids).filter((k) => selectedUids[k]);
    const list = targets.length > 0 ? targets : sample.map((s) => s.uid);
    if (list.length === 0) return;
    try {
      const res = await callBridge<{ updated: number }>('tag_my_club', list, myClubId);
      setStatusMsg(`Asignados ${res.updated ?? list.length} regens a ${clubs[myClubId]?.name ?? myClubId}.`);
      setSelectedUids({});
      await refreshVault();
    } catch (e) {
      setStatusMsg(e instanceof Error ? e.message : 'Error al etiquetar regens.');
    }
  };

  const handleImport = async () => {
    if (!importText.trim()) return;
    try {
      const res = await callBridge<{ mapped: number }>('import_squad_text', importText);
      setStatusMsg(`Importadas ${res.mapped ?? 0} asignaciones UID → Club.`);
      setImportText('');
      setShowImporter(false);
      await refreshVault();
    } catch (e) {
      setStatusMsg(e instanceof Error ? e.message : 'Error al importar asignaciones.');
    }
  };

  const handleJump = async (row: RegenRow) => {
    try {
      const params = row.clubId ? { kitMode: 'club', clubId: row.clubId } : { kitMode: 'original' };
      const res = await callBridge<StudioJumpPayload>('load_regen_into_studio', row.uid, params);
      if (res?.previewDataUrl) {
        onJumpToStudio({
          uid: row.uid,
          previewDataUrl: res.previewDataUrl,
          clubId: res.clubId || row.clubId || undefined,
          headAssetId: res.headAssetId,
          matchedTemplateId: res.matchedTemplateId,
          isPreCutout: res.isPreCutout,
          autoFit: res.autoFit,
        });
      }
    } catch (e) {
      setStatusMsg(e instanceof Error ? e.message : 'No se pudo abrir el regen en el Estudio.');
    }
  };

  return (
    <div className="flex flex-col gap-3 lg:h-full lg:min-h-0">
      {storageHealth?.warning && (
        <section className="shrink-0 rounded-xl border border-amber-300/80 dark:border-amber-800/80 bg-amber-50 dark:bg-amber-950/30 p-3 space-y-1.5 text-xs text-amber-950 dark:text-amber-200">
          <div className="flex items-center justify-between gap-2 font-semibold">
            <span className="inline-flex items-center gap-1.5"><AlertTriangle className="w-4 h-4 text-amber-600 dark:text-amber-400" /> Centinela OneDrive &amp; Disco C: ({storageHealth.free_gb} GB libres)</span>
            <span className="tabular-nums">Protección activa</span>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span><strong>Steam / Epic FM27:</strong> añade en Parámetros de lanzamiento</span>
            <code className="px-2 py-0.5 rounded bg-amber-100 dark:bg-amber-900/60 font-mono">{storageHealth.steam_launch_arg}</code>
            <button
              type="button"
              onClick={() => { navigator.clipboard?.writeText(storageHealth.steam_launch_arg); setCopiedArg(true); setTimeout(() => setCopiedArg(false), 1800); }}
              className="px-2 py-0.5 rounded bg-amber-200/80 dark:bg-amber-800/70 inline-flex items-center gap-1 font-medium"
            >
              {copiedArg ? <Check className="w-3 h-3" /> : <Copy className="w-3 h-3" />} Copiar
            </button>
          </div>
          <p className="text-[11px] text-amber-900/90 dark:text-amber-300/90">{storageHealth.gamepass_guide}</p>
        </section>
      )}

      <section className="flex-1 min-h-0 rounded-xl shadow-xs border border-slate-200/80 dark:border-slate-800 bg-white dark:bg-slate-900 divide-y divide-slate-200/80 dark:divide-slate-800 flex flex-col overflow-hidden">
        <div className={`shrink-0 p-3 grid grid-cols-1 ${activeVariant === 'dual' ? 'md:grid-cols-3' : 'md:grid-cols-2'} gap-3 text-xs`}>
          <div className="space-y-1">
            <span className="font-semibold text-slate-900 dark:text-slate-100">1. Bóveda NG_Regens (Solo lectura · Cero .bak)</span>
            <button
              type="button"
              onClick={async () => { try { const p = await callBridge<{ path: string } | null>('choose_directory', 'vault'); if (p?.path) onVaultChange(p.path); } catch (e) { setStatusMsg(e instanceof Error ? e.message : 'Ruta inválida.'); } }}
              title={vaultDir}
              className="w-full px-3 py-2 rounded-md border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950 text-slate-700 dark:text-slate-300 flex items-center justify-between gap-2"
            >
              <span className="truncate font-mono">{vaultDir}</span>
              <FolderOpen className="w-3.5 h-3.5 shrink-0 text-emerald-600 dark:text-emerald-400" />
            </button>
          </div>

          {activeVariant !== 'pure' && (
            <div className="space-y-1">
              <span className="font-semibold text-slate-900 dark:text-slate-100">
                {activeVariant === 'dual' ? '2A. Salida FM Classic (260×310)' : '2. Salida FM27 (000_DF11_Regens_Override)'}
              </span>
              <button
                type="button"
                aria-label="Elegir carpeta de salida Classic NG_Regens"
                onClick={async () => {
                  try {
                    const p = await callBridge<{ path: string; storageHealth: StorageHealth; fmGraphicsCollision?: boolean } | null>('choose_directory', 'export');
                    if (p?.path) {
                      if (typeof p.fmGraphicsCollision === 'boolean') setLocalFmCollision(p.fmGraphicsCollision);
                      onExportChange(p.path, p.storageHealth, p.fmGraphicsCollision);
                    }
                  } catch (e) {
                    setStatusMsg(e instanceof Error ? e.message : 'Carpeta de salida inválida.');
                  }
                }}
                title={exportDir}
                className="w-full px-3 py-2 rounded-md border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950 text-slate-700 dark:text-slate-300 flex items-center justify-between gap-2"
              >
                <span className="truncate font-mono">{exportDir}</span>
                <FolderOpen className="w-3.5 h-3.5 shrink-0 text-emerald-600 dark:text-emerald-400" />
              </button>
            </div>
          )}

          {activeVariant !== 'classic' && (
            <div className="space-y-1">
              <span className="font-semibold text-slate-900 dark:text-slate-100">
                {activeVariant === 'dual' ? '2B. Salida FM Pure (220×276)' : '2. Salida FM Pure (220×276 · 000_DF11_Pure_Override)'}
              </span>
              <button
                type="button"
                aria-label="Elegir carpeta de salida Pure NG_Regens"
                onClick={async () => {
                  try {
                    const p = await callBridge<{ path: string; storageHealth: StorageHealth; fmGraphicsCollision?: boolean } | null>('choose_directory', 'export_pure');
                    if (p?.path) {
                      setLocalPureDir(p.path);
                      if (typeof p.fmGraphicsCollision === 'boolean') setLocalFmCollision(p.fmGraphicsCollision);
                      onExportPureChange?.(p.path, p.storageHealth, p.fmGraphicsCollision);
                    }
                  } catch (e) {
                    setStatusMsg(e instanceof Error ? e.message : 'Carpeta de salida DF11 Pure inválida.');
                  }
                }}
                title={effectivePureDir}
                className="w-full px-3 py-2 rounded-md border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950 text-slate-700 dark:text-slate-300 flex items-center justify-between gap-2"
              >
                <span className="truncate font-mono">{effectivePureDir}</span>
                <FolderOpen className="w-3.5 h-3.5 shrink-0 text-emerald-600 dark:text-emerald-400" />
              </button>
            </div>
          )}
        </div>

        <div className="shrink-0 p-3 flex flex-wrap items-center justify-between gap-3 text-xs">
          <div className="flex flex-wrap items-center gap-3 text-slate-700 dark:text-slate-300">
            <div className="inline-flex items-center gap-1 rounded-lg bg-slate-100 dark:bg-slate-950 p-0.5 border border-slate-200/80 dark:border-slate-800" role="group" aria-label="Formato de sincronización DF11">
              {([
                ['classic', 'Classic 260×310'],
                ['pure', 'Pure 220×276'],
                ['dual', 'Dual (Ambas)'],
              ] as const).map(([vKey, vLabel]) => (
                <button
                  key={vKey}
                  type="button"
                  onClick={() => handleSelectVariant(vKey)}
                  className={`px-2 py-1 rounded-md text-[11px] font-medium transition ${
                    activeVariant === vKey
                      ? 'bg-emerald-600 text-white shadow-xs'
                      : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-100'
                  }`}
                >
                  {vLabel}
                </button>
              ))}
            </div>
            <label
              title="Desmárcalo para sincronizar Classic, Pure o Dual con algoritmo óptico 100% 0% IA (8 hilos CPU, sin cargar modelos ONNX)"
              className="inline-flex items-center gap-2"
            >
              <input type="checkbox" checked={applyKits} onChange={(e) => { const v = e.target.checked; setApplyKits(v); if (liveWatch) void handleToggleLiveWatch(true, v, harmonize); }} className="accent-emerald-600" /> Equipación real de club (desmarcado = 0% IA)
            </label>
            <label className="inline-flex items-center gap-2"><input type="checkbox" checked={harmonize} onChange={(e) => { const v = e.target.checked; setHarmonize(v); if (liveWatch) void handleToggleLiveWatch(true, applyKits, v); }} className="accent-emerald-600" /> Armonizar luz DF11 (OKLab)</label>
            <button
              type="button"
              onClick={() => void handleToggleLiveWatch(!liveWatch)}
              className={`px-2.5 py-1 rounded-full inline-flex items-center gap-1.5 font-medium transition ${liveWatch ? 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-400' : 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400'}`}
            >
              <Radio className="w-3.5 h-3.5" /> Live Disk Sync (650ms)
            </button>
          </div>

          <div className="flex items-center gap-2">
            <button type="button" onClick={() => void refreshVault()} className="px-2.5 py-1.5 rounded-md bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 inline-flex items-center gap-1"><RefreshCw className="w-3.5 h-3.5" /> Re-escanear</button>
            {running ? (
              <button type="button" onClick={() => void callBridge('cancel_regens_sync')} className="px-3.5 py-1.5 rounded-md bg-rose-600 text-white font-medium inline-flex items-center gap-1.5"><Square className="w-3.5 h-3.5" /> Cancelar</button>
            ) : (
              <button type="button" onClick={() => void handleSync(false)} className="px-4 py-1.5 rounded-md bg-emerald-600 hover:bg-emerald-500 text-white font-medium inline-flex items-center gap-1.5 tabular-nums">
                <Play className="w-3.5 h-3.5" />{' '}
                {activeVariant === 'dual'
                  ? `Convertir ${totalFound} regens (Dual)`
                  : activeVariant === 'pure'
                  ? `Convertir ${totalFound} regens a Pure`
                  : `Convertir ${totalFound} regens a DF11`}
              </button>
            )}
          </div>
        </div>

        {activeVariant === 'dual' && effectiveFmCollision && (
          <div className="shrink-0 px-3 py-2 bg-amber-50/80 dark:bg-amber-950/30 text-[11px] text-amber-900 dark:text-amber-200 flex items-center gap-1.5">
            <AlertTriangle className="w-3.5 h-3.5 shrink-0 text-amber-600 dark:text-amber-400" />
            <span>
              Ambas salidas cuelgan de <code className="font-mono">graphics/</code> de Football Manager: el juego aplicará prioridad alfabética sobre el mismo <code className="font-mono">config.xml</code>. Guarda una variante fuera de <code className="font-mono">graphics/</code> si deseas alternarlas manualmente.
            </span>
          </div>
        )}

        <div className="shrink-0 p-3 space-y-2 text-xs">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-medium text-slate-800 dark:text-slate-200 inline-flex items-center gap-1"><Tag className="w-3.5 h-3.5 text-emerald-600 dark:text-emerald-400" /> Etiquetar Mi Club:</span>
              <select aria-label="Club para etiquetado masivo" value={myClubId} onChange={(e) => setMyClubId(e.target.value)} className="px-2.5 py-1 rounded-md border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-950 text-slate-900 dark:text-slate-100">
                {myClubId && !clubs[myClubId] && <option value={myClubId}>Club #{myClubId}</option>}
                {Object.entries(clubs).sort((a, b) => a[1].name.localeCompare(b[1].name, 'es')).map(([cid, info]) => <option key={cid} value={cid}>{info.name} (#{cid})</option>)}
              </select>
              <input
                aria-label="ID numérico de club para regens"
                inputMode="numeric"
                value={myClubId}
                onChange={(e) => setMyClubId(e.target.value.replace(/[^0-9]/g, '').slice(0, 12))}
                placeholder="#ID Club"
                className="w-24 px-2 py-1 rounded-md border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-950 text-slate-900 dark:text-slate-100 tabular-nums font-mono"
              />
              <button type="button" onClick={() => void handleTagClub()} className="px-2.5 py-1 rounded-md bg-slate-900 dark:bg-slate-100 text-white dark:text-slate-900 font-medium">Aplicar a selección / vista</button>
            </div>
            <button type="button" onClick={() => setShowImporter((s) => !s)} className="px-2.5 py-1 rounded-md bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 inline-flex items-center gap-1"><ClipboardPaste className="w-3.5 h-3.5" /> Importar CSV / HTML (F9)</button>
          </div>

          {showImporter && (
            <div className="flex gap-2 items-start pt-1">
              <textarea value={importText} onChange={(e) => setImportText(e.target.value)} rows={3} placeholder="Pega líneas CSV o tabla HTML: r-2002049102, Real Madrid" className="flex-1 p-2 rounded-md border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-950 text-slate-900 dark:text-slate-100 font-mono text-xs" />
              <button type="button" onClick={() => void handleImport()} className="px-3 py-2 rounded-md bg-emerald-600 text-white font-medium">Mapear</button>
            </div>
          )}

          {lastSync?.aborted_by_shrink_guard && (
            <div className="p-3 rounded-lg bg-rose-50 dark:bg-rose-950/40 border border-rose-300 dark:border-rose-800 text-rose-800 dark:text-rose-200 flex items-center justify-between gap-2">
              <span className="inline-flex items-center gap-1.5"><ShieldAlert className="w-4 h-4" /> Shrink Guard (50%) bloqueó un borrado accidental por truncado de config.xml.</span>
              <button type="button" onClick={() => void handleSync(true)} className="px-2.5 py-1 rounded bg-rose-600 text-white font-medium">Forzar actualización</button>
            </div>
          )}

          {lastSync && !lastSync.aborted_by_shrink_guard && (
            <p className="text-emerald-700 dark:text-emerald-400 tabular-nums">
              Sincronizados: {lastSync.processed} nuevos · {lastSync.skipped} al día{lastSync.failed ? ` · ${lastSync.failed} omitidos por archivo dañado` : ''}.
            </p>
          )}
          {statusMsg && <p className="text-slate-600 dark:text-slate-300">{statusMsg}</p>}
        </div>

        <div className="flex-1 min-h-0 p-3 overflow-y-auto">
          {sample.length === 0 ? (
            <p className="text-xs text-slate-500 dark:text-slate-400 py-6 text-center">Bóveda sin regens detectados aún. Genera caras en NG_Regens apuntando a {vaultDir} y pulsa Re-escanear.</p>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-2">
              {sample.map((row) => (
                <div key={row.uid} className="px-3 py-2 rounded-lg bg-slate-50 dark:bg-slate-950 border border-slate-200/70 dark:border-slate-800 flex items-center justify-between gap-2 text-xs">
                  <label className="inline-flex items-center gap-2 min-w-0">
                    <input type="checkbox" checked={Boolean(selectedUids[row.uid])} onChange={(e) => setSelectedUids((p) => ({ ...p, [row.uid]: e.target.checked }))} className="accent-emerald-600" />
                    <span className="font-mono font-medium text-slate-900 dark:text-slate-100 tabular-nums truncate">{row.uid}</span>
                    {row.clubId && <span className="px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 truncate">{clubs[row.clubId]?.name ?? `#${row.clubId}`}</span>}
                  </label>
                  <button type="button" onClick={() => void handleJump(row)} className="shrink-0 px-2 py-1 rounded bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 text-slate-700 dark:text-slate-200 inline-flex items-center gap-1 hover:border-emerald-500">
                    Editar en Estudio <ArrowUpRight className="w-3 h-3" />
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      </section>
    </div>
  );
}
