import { useCallback, useEffect, useState } from 'react';
import { AlertTriangle, ArrowUpRight, Check, ClipboardPaste, Copy, FolderOpen, Play, Radio, RefreshCw, ShieldAlert, Square, Tag } from 'lucide-react';
import { ClubSeed, StorageHealth, callBridge } from '../lib/ipc';
import { StudioJumpPayload } from './StudioView';

interface RegenRow { uid: string; clubId: string; }
interface SyncSummary { total_found: number; processed: number; skipped: number; cancelled: boolean; aborted_by_shrink_guard: boolean; }

interface Props {
  clubs: Record<string, ClubSeed>;
  vaultDir: string;
  exportDir: string;
  storageHealth: StorageHealth | null;
  onVaultChange: (dir: string) => void;
  onExportChange: (dir: string, sh?: StorageHealth) => void;
  onJumpToStudio: (payload: StudioJumpPayload) => void;
}

export default function RegensSyncView({ clubs, vaultDir, exportDir, storageHealth, onVaultChange, onExportChange, onJumpToStudio }: Props) {
  const [totalFound, setTotalFound] = useState(0);
  const [sample, setSample] = useState<RegenRow[]>([]);
  const [selectedUids, setSelectedUids] = useState<Record<string, boolean>>({});
  const [myClubId, setMyClubId] = useState('1736');
  const [applyKits, setApplyKits] = useState(true);
  const [harmonize, setHarmonize] = useState(true);
  const [liveWatch, setLiveWatch] = useState(false);
  const [running, setRunning] = useState(false);
  const [importText, setImportText] = useState('');
  const [showImporter, setShowImporter] = useState(false);
  const [copiedArg, setCopiedArg] = useState(false);
  const [lastSync, setLastSync] = useState<SyncSummary | null>(null);
  const [statusMsg, setStatusMsg] = useState('');

  const refreshVault = useCallback(async () => {
    const res = await callBridge<{ totalFound?: number; sample?: RegenRow[] }>('scan_vault_summary');
    setTotalFound(res?.totalFound ?? 0);
    setSample(res?.sample ?? []);
  }, []);

  useEffect(() => { refreshVault(); }, [refreshVault, vaultDir]);

  const handleSync = async (allowShrink = false) => {
    setRunning(true); setStatusMsg('');
    try {
      const res = await callBridge<SyncSummary>('start_regens_sync', { applyClubKits: applyKits, harmonize, bgMode: 'white_df11', allowShrink });
      setLastSync(res);
      await refreshVault();
    } catch (e) {
      setStatusMsg(e instanceof Error ? e.message : 'Error durante la sincronización por lotes.');
    } finally {
      setRunning(false);
    }
  };

  const handleTagClub = async () => {
    const targets = Object.keys(selectedUids).filter((k) => selectedUids[k]);
    const list = targets.length > 0 ? targets : sample.map((s) => s.uid);
    if (list.length === 0) return;
    const res = await callBridge<{ updated: number }>('tag_my_club', list, myClubId);
    setStatusMsg(`Asignados ${res.updated ?? list.length} regens a ${clubs[myClubId]?.name ?? myClubId}.`);
    setSelectedUids({});
    await refreshVault();
  };

  const handleImport = async () => {
    if (!importText.trim()) return;
    const res = await callBridge<{ mapped: number }>('import_squad_text', importText);
    setStatusMsg(`Importadas ${res.mapped ?? 0} asignaciones UID → Club.`);
    setImportText('');
    setShowImporter(false);
    await refreshVault();
  };

  const handleJump = async (row: RegenRow) => {
    const res = await callBridge<{ uid: string; previewDataUrl: string }>('load_regen_into_studio', row.uid);
    if (res?.previewDataUrl) onJumpToStudio({ uid: row.uid, previewDataUrl: res.previewDataUrl, clubId: row.clubId || undefined });
  };

  return (
    <div className="space-y-5">
      {/* OneDrive & Disk Sentinel */}
      {storageHealth?.warning && (
        <section className="rounded-xl border border-amber-300/80 dark:border-amber-800/80 bg-amber-50 dark:bg-amber-950/30 p-4 space-y-2 text-xs text-amber-950 dark:text-amber-200">
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

      {/* Main Sync Console */}
      <section className="rounded-xl shadow-xs border border-slate-200/80 dark:border-slate-800 bg-white dark:bg-slate-900 divide-y divide-slate-200/80 dark:divide-slate-800">
        <div className="p-4 grid grid-cols-1 md:grid-cols-2 gap-4 text-xs">
          <div className="space-y-1">
            <span className="font-semibold text-slate-900 dark:text-slate-100">1. Bóveda NG_Regens (Solo lectura · Cero .bak)</span>
            <button
              type="button"
              onClick={async () => { const p = await callBridge<{ path: string } | null>('choose_directory', 'vault'); if (p?.path) onVaultChange(p.path); }}
              title={vaultDir}
              className="w-full px-3 py-2 rounded-md border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-900 text-slate-700 dark:text-slate-300 flex items-center justify-between gap-2"
            >
              <span className="truncate font-mono">{vaultDir}</span>
              <FolderOpen className="w-3.5 h-3.5 shrink-0 text-emerald-600 dark:text-emerald-400" />
            </button>
          </div>

          <div className="space-y-1">
            <span className="font-semibold text-slate-900 dark:text-slate-100">2. Salida FM27 (000_DF11_Regens_Override)</span>
            <button
              type="button"
              onClick={async () => { const p = await callBridge<{ path: string; storageHealth: StorageHealth } | null>('choose_directory', 'export'); if (p?.path) onExportChange(p.path, p.storageHealth); }}
              title={exportDir}
              className="w-full px-3 py-2 rounded-md border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-900 text-slate-700 dark:text-slate-300 flex items-center justify-between gap-2"
            >
              <span className="truncate font-mono">{exportDir}</span>
              <FolderOpen className="w-3.5 h-3.5 shrink-0 text-emerald-600 dark:text-emerald-400" />
            </button>
          </div>
        </div>

        {/* 2 Toggles + Live Sync + Action */}
        <div className="p-4 flex flex-wrap items-center justify-between gap-4 text-xs">
          <div className="flex flex-wrap items-center gap-4 text-slate-700 dark:text-slate-300">
            <label className="inline-flex items-center gap-2"><input type="checkbox" checked={applyKits} onChange={(e) => setApplyKits(e.target.checked)} className="accent-emerald-600" /> Equipación real de club (P_clothes = 0)</label>
            <label className="inline-flex items-center gap-2"><input type="checkbox" checked={harmonize} onChange={(e) => setHarmonize(e.target.checked)} className="accent-emerald-600" /> Armonizar luz DF11 (OKLab)</label>
            <button
              type="button"
              onClick={async () => { const next = !liveWatch; await callBridge('toggle_live_watch', next); setLiveWatch(next); }}
              className={`px-2.5 py-1 rounded-full inline-flex items-center gap-1.5 font-medium transition ${liveWatch ? 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-400' : 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400'}`}
            >
              <Radio className="w-3.5 h-3.5" /> Live Disk Sync (650ms)
            </button>
          </div>

          <div className="flex items-center gap-2">
            <button type="button" onClick={refreshVault} className="px-2.5 py-1.5 rounded-md bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 inline-flex items-center gap-1"><RefreshCw className="w-3.5 h-3.5" /> Re-escanear</button>
            {running ? (
              <button type="button" onClick={() => callBridge('cancel_regens_sync')} className="px-3.5 py-1.5 rounded-md bg-rose-600 text-white font-medium inline-flex items-center gap-1.5"><Square className="w-3.5 h-3.5" /> Cancelar</button>
            ) : (
              <button type="button" onClick={() => handleSync(false)} className="px-4 py-1.5 rounded-md bg-emerald-600 hover:bg-emerald-500 text-white font-medium inline-flex items-center gap-1.5 tabular-nums"><Play className="w-3.5 h-3.5" /> Convertir {totalFound} regens a DF11</button>
            )}
          </div>
        </div>

        {/* "Mi Club" Tagger & CSV/HTML Importer */}
        <div className="p-4 space-y-3 text-xs">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-medium text-slate-800 dark:text-slate-200 inline-flex items-center gap-1"><Tag className="w-3.5 h-3.5 text-emerald-600 dark:text-emerald-400" /> Etiquetar Mi Club:</span>
              <select aria-label="Club para etiquetado masivo" value={myClubId} onChange={(e) => setMyClubId(e.target.value)} className="px-2.5 py-1 rounded-md border border-slate-300 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 text-slate-900 dark:text-slate-100">
                {Object.entries(clubs).map(([cid, info]) => <option key={cid} value={cid}>{info.name} (#{cid})</option>)}
              </select>
              <button type="button" onClick={handleTagClub} className="px-2.5 py-1 rounded-md bg-slate-900 dark:bg-slate-100 text-white dark:text-slate-900 font-medium">Aplicar a selección / vista</button>
            </div>
            <button type="button" onClick={() => setShowImporter((s) => !s)} className="px-2.5 py-1 rounded-md bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 inline-flex items-center gap-1"><ClipboardPaste className="w-3.5 h-3.5" /> Importar CSV / HTML (F9)</button>
          </div>

          {showImporter && (
            <div className="flex gap-2 items-start pt-1">
              <textarea value={importText} onChange={(e) => setImportText(e.target.value)} rows={3} placeholder="Pega líneas CSV o tabla HTML: r-2002049102, Real Madrid" className="flex-1 p-2 rounded-md border border-slate-300 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 text-slate-900 dark:text-slate-100 font-mono text-xs" />
              <button type="button" onClick={handleImport} className="px-3 py-2 rounded-md bg-emerald-600 text-white font-medium">Mapear</button>
            </div>
          )}

          {lastSync?.aborted_by_shrink_guard && (
            <div className="p-3 rounded-lg bg-rose-50 dark:bg-rose-950/40 border border-rose-300 dark:border-rose-800 text-rose-800 dark:text-rose-200 flex items-center justify-between gap-2">
              <span className="inline-flex items-center gap-1.5"><ShieldAlert className="w-4 h-4" /> Shrink Guard (50%) bloqueó un borrado accidental por truncado de config.xml.</span>
              <button type="button" onClick={() => handleSync(true)} className="px-2.5 py-1 rounded bg-rose-600 text-white font-medium">Forzar actualización</button>
            </div>
          )}

          {lastSync && !lastSync.aborted_by_shrink_guard && (
            <p className="text-emerald-700 dark:text-emerald-400 tabular-nums">Sincronizados: {lastSync.processed} nuevos · {lastSync.skipped} ya al día en caché SQLite.</p>
          )}
          {statusMsg && <p className="text-slate-600 dark:text-slate-300">{statusMsg}</p>}
        </div>

        {/* Discovered Regens List & 1-Click Jump to Studio */}
        <div className="p-4">
          {sample.length === 0 ? (
            <p className="text-xs text-slate-500 dark:text-slate-400 py-6 text-center">Bóveda sin regens detectados aún. Genera caras en NG_Regens apuntando a {vaultDir} y pulsa Re-escanear.</p>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2.5">
              {sample.map((row) => (
                <div key={row.uid} className="px-3 py-2 rounded-lg bg-slate-50 dark:bg-slate-900/70 border border-slate-200/70 dark:border-slate-800 flex items-center justify-between gap-2 text-xs">
                  <label className="inline-flex items-center gap-2 min-w-0">
                    <input type="checkbox" checked={Boolean(selectedUids[row.uid])} onChange={(e) => setSelectedUids((p) => ({ ...p, [row.uid]: e.target.checked }))} className="accent-emerald-600" />
                    <span className="font-mono font-medium text-slate-900 dark:text-slate-100 tabular-nums truncate">{row.uid}</span>
                    {row.clubId && <span className="px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 truncate">{clubs[row.clubId]?.name ?? `#${row.clubId}`}</span>}
                  </label>
                  <button type="button" onClick={() => handleJump(row)} className="shrink-0 px-2 py-1 rounded bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 text-slate-700 dark:text-slate-200 inline-flex items-center gap-1 hover:border-emerald-500">
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
