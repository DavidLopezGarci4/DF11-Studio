import { Component, ReactNode, Suspense, lazy, useCallback, useEffect, useRef, useState } from 'react';
import { ChevronDown, FolderSync, HelpCircle, Info, Layers, Moon, RefreshCw, Scissors, Shirt, Sun } from 'lucide-react';
import AboutModal from './components/AboutModal';
import FaqModal from './components/FaqModal';
import RegensSyncView from './components/RegensSyncView';
import StudioView, { StudioJumpPayload, ToolTab } from './components/StudioView';
import { BootstrapState, CaptureTarget, ClubSeed, ExportVariant, StorageHealth, callBridge } from './lib/ipc';

const AppArchitectureGraph = lazy(() => import('./components/AppArchitectureGraph'));

class GraphErrorBoundary extends Component<
  { onClose: () => void; children: ReactNode },
  { hasError: boolean }
> {
  state = { hasError: false };
  static getDerivedStateFromError() {
    return { hasError: true };
  }
  render() {
    if (!this.state.hasError) return this.props.children;
    return (
      <div
        onClick={(e) => {
          if (e.target === e.currentTarget) this.props.onClose();
        }}
        className="fixed inset-0 z-50 bg-slate-950/70 flex items-center justify-center p-4"
        role="dialog"
        aria-modal="true"
      >
        <div className="w-full max-w-md rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-5 space-y-3 text-xs text-slate-800 dark:text-slate-200 shadow-xl">
          <h2 className="text-sm font-semibold text-slate-900 dark:text-white">
            Actualización detectada en el módulo de Arquitectura
          </h2>
          <p className="text-slate-600 dark:text-slate-400 leading-relaxed">
            La aplicación se ha actualizado en disco mientras esta ventana estaba abierta. Recarga la vista para cargar el nuevo visor de salud y topología de nodos.
          </p>
          <div className="flex items-center justify-end gap-2 pt-1">
            <button
              type="button"
              onClick={this.props.onClose}
              className="px-3 py-1.5 rounded-lg bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300"
            >
              Cerrar
            </button>
            <button
              type="button"
              onClick={() => window.location.reload()}
              className="px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white font-medium inline-flex items-center gap-1.5"
            >
              <RefreshCw className="w-3.5 h-3.5" /> Recargar ahora
            </button>
          </div>
        </div>
      </div>
    );
  }
}

export default function App() {
  const hadStoredTheme = useRef(localStorage.getItem('df11_theme') !== null);
  const [dark, setDark] = useState(() => localStorage.getItem('df11_theme') !== 'light');
  const [tab, setTab] = useState<'studio' | 'sync'>('studio');
  const [studioToolTab, setStudioToolTab] = useState<ToolTab>('composer');
  const [templatesCount, setTemplatesCount] = useState(0);
  const [modal, setModal] = useState<'faq' | 'about' | 'graph' | null>(null);
  const [boot, setBoot] = useState<BootstrapState | null>(null);
  const [clubs, setClubs] = useState<Record<string, ClubSeed>>({});
  const [vaultDir, setVaultDir] = useState('D:\\DF11Studio\\NG_Regens_Vault');
  const [exportDir, setExportDir] = useState('D:\\DF11Studio\\Exports\\000_DF11_Regens_Override');
  const [exportPureDir, setExportPureDir] = useState('D:\\DF11Studio\\Exports\\000_DF11_Pure_Override');
  const [facepackDir, setFacepackDir] = useState('');
  const [facepackPureDir, setFacepackPureDir] = useState('');
  const [exportVariant, setExportVariant] = useState<ExportVariant>('classic');
  const [fmGraphicsCollision, setFmGraphicsCollision] = useState(false);
  const [fmFacepackCollision, setFmFacepackCollision] = useState(false);
  const [storageHealth, setStorageHealth] = useState<StorageHealth | null>(null);
  const [liveWatching, setLiveWatching] = useState(false);
  const [studioJump, setStudioJump] = useState<StudioJumpPayload | null>(null);
  const [captureHotkey, setCaptureHotkey] = useState(false);
  const [capMenuOpen, setCapMenuOpen] = useState(false);
  const capMenuRef = useRef<HTMLDivElement>(null);
  const capSeqRef = useRef(0);
  const [externalCaptureReq, setExternalCaptureReq] = useState<{
    seq: number;
    target?: CaptureTarget;
    explicit?: boolean;
    directBgReplace?: boolean;
  } | null>(null);

  useEffect(() => {
    document.documentElement.classList.toggle('dark', dark);
    localStorage.setItem('df11_theme', dark ? 'dark' : 'light');
  }, [dark]);

  const loadBootstrap = useCallback(() => {
    void callBridge<BootstrapState>('get_bootstrap_state')
      .then((b) => {
        if (!b) return;
        setBoot(b);
        if (b.clubs) setClubs(b.clubs);
        if (b.vaultDir) setVaultDir(b.vaultDir);
        if (b.exportDir) setExportDir(b.exportDir);
        if (b.exportPureDir) setExportPureDir(b.exportPureDir);
        if (typeof b.facepackDir === 'string') setFacepackDir(b.facepackDir);
        if (typeof b.facepackPureDir === 'string') setFacepackPureDir(b.facepackPureDir);
        if (b.exportVariant === 'classic' || b.exportVariant === 'pure' || b.exportVariant === 'dual') {
          setExportVariant(b.exportVariant);
        }
        if (typeof b.fmGraphicsCollision === 'boolean') setFmGraphicsCollision(b.fmGraphicsCollision);
        if (typeof b.fmFacepackCollision === 'boolean') setFmFacepackCollision(b.fmFacepackCollision);
        if (b.storageHealth) setStorageHealth(b.storageHealth);
        if (typeof b.liveWatching === 'boolean') setLiveWatching(b.liveWatching);
        if (typeof b.captureHotkey === 'boolean') setCaptureHotkey(b.captureHotkey);
        if (!hadStoredTheme.current && (b.theme === 'light' || b.theme === 'dark')) {
          setDark(b.theme === 'dark');
        }
      })
      .catch(() => {});
  }, []);

  const handleExportVariantChange = useCallback((next: ExportVariant) => {
    setExportVariant(next);
    void callBridge('set_export_variant', next).catch(() => {});
  }, []);

  useEffect(() => {
    loadBootstrap();
    window.addEventListener('pywebviewready', loadBootstrap);
    return () => window.removeEventListener('pywebviewready', loadBootstrap);
  }, [loadBootstrap]);

  const triggerGlobalCapture = useCallback((target?: CaptureTarget, explicit = false, directBgReplace?: boolean) => {
    setCapMenuOpen(false);
    setTab('studio');
    const nextSeq = ++capSeqRef.current;
    setExternalCaptureReq({ seq: nextSeq, target, explicit, directBgReplace });
  }, []);

  useEffect(() => {
    if (tab !== 'sync') return undefined;
    const onHotkey = () => {
      if (document.querySelector('[role="dialog"]')) return;
      triggerGlobalCapture();
    };
    window.addEventListener('df11:hotkey-capture', onHotkey);
    return () => window.removeEventListener('df11:hotkey-capture', onHotkey);
  }, [tab, triggerGlobalCapture]);

  useEffect(() => {
    if (!capMenuOpen) return undefined;
    const onDocPointer = (ev: MouseEvent) => {
      if (capMenuRef.current && !capMenuRef.current.contains(ev.target as Node)) setCapMenuOpen(false);
    };
    const onDocKey = (ev: KeyboardEvent) => {
      if (ev.key === 'Escape') setCapMenuOpen(false);
    };
    document.addEventListener('mousedown', onDocPointer);
    document.addEventListener('keydown', onDocKey);
    return () => {
      document.removeEventListener('mousedown', onDocPointer);
      document.removeEventListener('keydown', onDocKey);
    };
  }, [capMenuOpen]);

  const handleToggleGlobalHotkey = async () => {
    const res = await callBridge<{ enabled?: boolean; hotkeyEnabled?: boolean }>('toggle_capture_hotkey', !captureHotkey).catch(() => null);
    if (res) setCaptureHotkey(Boolean(res.hotkeyEnabled ?? res.enabled));
  };

  const navBtn = (active: boolean) =>
    `px-2.5 py-1 text-xs font-medium rounded-md inline-flex items-center gap-1.5 whitespace-nowrap shrink-0 transition ${
      active
        ? 'bg-emerald-600 text-white shadow-xs'
        : 'text-slate-600 dark:text-slate-400 hover:bg-slate-200/70 dark:hover:bg-slate-800 hover:text-slate-900 dark:hover:text-slate-100'
    }`;

  return (
    <div className="min-h-screen lg:h-screen lg:overflow-hidden flex flex-col bg-slate-50 text-slate-900 dark:bg-[#090d16] dark:text-white">
      <header className="sticky top-0 z-30 h-12 shrink-0 border-b border-slate-200/80 dark:border-slate-800 bg-white/90 dark:bg-[#090d16]/90 backdrop-blur-md">
        <div className="h-full max-w-[1600px] w-full mx-auto px-4 flex items-center justify-between gap-3">
          <div className="flex items-center gap-2 shrink-0">
            <img src="./icon-128.png" alt="Logo DF11 Face Studio" className="w-6 h-6 rounded-md" />
            <span className="font-semibold tracking-tight text-sm text-slate-900 dark:text-white hidden sm:inline">
              DF11 Face Studio
            </span>
            <span className="text-[11px] px-2 py-0.5 rounded-full border bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-500/10 dark:text-emerald-400 dark:border-emerald-500/20 tabular-nums">
              v{boot?.version ?? '1.6.0'}
            </span>
          </div>

          <nav
            aria-label="Navegación principal DF11"
            className="min-w-0 flex items-center gap-1 p-1 rounded-lg bg-slate-100 dark:bg-slate-950 border border-slate-200/80 dark:border-slate-800 overflow-x-auto"
          >
            <button
              type="button"
              onClick={() => {
                setTab('studio');
                setStudioToolTab('composer');
              }}
              className={navBtn(tab === 'studio' && studioToolTab === 'composer')}
            >
              <Layers className="w-3.5 h-3.5" /> Montaje Paso a Paso
            </button>
            <button
              type="button"
              onClick={() => {
                setTab('studio');
                setStudioToolTab('face_tool');
              }}
              className={navBtn(tab === 'studio' && studioToolTab === 'face_tool')}
            >
              <Scissors className="w-3.5 h-3.5" /> Extraer Cara
            </button>
            <button
              type="button"
              onClick={() => {
                setTab('studio');
                setStudioToolTab('shirt_tool');
              }}
              className={navBtn(tab === 'studio' && studioToolTab === 'shirt_tool')}
            >
              <Shirt className="w-3.5 h-3.5" />
              <span>Extraer Camiseta</span>
              <span className="tabular-nums">({templatesCount})</span>
            </button>
            <span className="h-4 w-px bg-slate-300/80 dark:bg-slate-800 mx-0.5" aria-hidden="true" />
            <button type="button" onClick={() => setTab('sync')} className={navBtn(tab === 'sync')}>
              <FolderSync className="w-3.5 h-3.5" /> Sincronizador NG_Regens
            </button>
          </nav>

          <div className="flex items-center gap-1.5 shrink-0">
            <div ref={capMenuRef} className="relative inline-flex items-center mr-1">
              <button
                type="button"
                aria-label="Capturar pantalla"
                onClick={() => triggerGlobalCapture()}
                title="Recorte nativo de pantalla en 2 pasos (Seleccionar -> Reencuadrar -> Intro / Esc; oculta la app automáticamente; Shift bloquea 260×310)"
                className="px-2.5 py-1.5 text-xs font-medium rounded-l-lg bg-emerald-600 hover:bg-emerald-500 text-white inline-flex items-center gap-1.5 transition"
              >
                <Scissors className="w-3.5 h-3.5" /> Capturar
              </button>
              <button
                type="button"
                aria-label="Opciones de captura de pantalla"
                aria-haspopup="menu"
                aria-expanded={capMenuOpen}
                onClick={() => setCapMenuOpen((o) => !o)}
                title="Elegir destino de captura o abrir menú"
                className="px-1.5 py-1.5 text-xs font-medium rounded-r-lg border-l border-emerald-700/60 bg-emerald-600 hover:bg-emerald-500 text-white inline-flex items-center transition"
              >
                <ChevronDown className="w-3.5 h-3.5" />
              </button>
              {capMenuOpen && (
                <div
                  role="menu"
                  aria-label="Destinos independientes de captura"
                  className="absolute right-0 top-full mt-1.5 z-50 w-72 rounded-lg border border-slate-200/80 dark:border-slate-800 bg-white dark:bg-slate-900 shadow-lg py-1 text-xs text-slate-800 dark:text-slate-200"
                >
                  <button
                    type="button"
                    role="menuitem"
                    onClick={() => triggerGlobalCapture('direct_photo', true, false)}
                    className="w-full px-3 py-1.5 text-left hover:bg-slate-100 dark:hover:bg-slate-800 flex items-center justify-between"
                  >
                    <span>Foto Directa + Marco DF11</span>
                    <span className="text-[10px] text-slate-400 dark:text-slate-500">Fondo original</span>
                  </button>
                  <button
                    type="button"
                    role="menuitem"
                    onClick={() => triggerGlobalCapture('direct_photo', true, true)}
                    className="w-full px-3 py-1.5 text-left hover:bg-emerald-50 dark:hover:bg-slate-800 flex items-center justify-between text-emerald-700 dark:text-emerald-400"
                  >
                    <span>Foto Directa · Capa Blanca DF11</span>
                    <span className="text-[10px] text-emerald-600 dark:text-emerald-400">Capa blanca</span>
                  </button>
                  <button
                    type="button"
                    role="menuitem"
                    onClick={() => triggerGlobalCapture('raw_face', true)}
                    className="w-full px-3 py-1.5 text-left hover:bg-slate-100 dark:hover:bg-slate-800 flex items-center justify-between"
                  >
                    <span>Recortar Cara</span>
                    <span className="text-[10px] text-slate-400 dark:text-slate-500">Extractor</span>
                  </button>
                  <button
                    type="button"
                    role="menuitem"
                    onClick={() => triggerGlobalCapture('raw_shirt', true)}
                    className="w-full px-3 py-1.5 text-left hover:bg-slate-100 dark:hover:bg-slate-800 flex items-center justify-between"
                  >
                    <span>Extraer Camiseta</span>
                    <span className="text-[10px] text-slate-400 dark:text-slate-500">2× SSAA</span>
                  </button>
                  <div className="my-1 border-t border-slate-100 dark:border-white/5" />
                  <button
                    type="button"
                    role="menuitem"
                    onClick={() => triggerGlobalCapture('save_png', true)}
                    className="w-full px-3 py-1.5 text-left hover:bg-slate-100 dark:hover:bg-slate-800 flex items-center justify-between"
                  >
                    <span>Guardar PNG como…</span>
                    <span className="text-[10px] text-slate-400 dark:text-slate-500">.png</span>
                  </button>
                  <div className="my-1 border-t border-slate-100 dark:border-white/5" />
                  <button
                    type="button"
                    role="menuitem"
                    onClick={() => void handleToggleGlobalHotkey()}
                    className="w-full px-3 py-1.5 text-left hover:bg-slate-100 dark:hover:bg-slate-800 flex items-center justify-between text-[11px]"
                  >
                    <span>Atajo global Ctrl+Shift+X</span>
                    <span className={captureHotkey ? 'text-emerald-700 dark:text-emerald-400 font-semibold' : 'text-slate-400 dark:text-slate-500'}>
                      {captureHotkey ? 'Activo' : 'Off'}
                    </span>
                  </button>
                </div>
              )}
            </div>

            <button type="button" aria-label="Centro de ayuda y FAQ" title="Ayuda y FAQ" onClick={() => setModal('faq')} className="p-1.5 rounded-lg border border-slate-200/80 dark:border-slate-800 bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300">
              <HelpCircle className="w-4 h-4" />
            </button>
            <button type="button" aria-label="Acerca de DF11 Face Studio" title="Acerca de" onClick={() => setModal('about')} className="p-1.5 rounded-lg border border-slate-200/80 dark:border-slate-800 bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300">
              <Info className="w-4 h-4" />
            </button>
            <button type="button" aria-label="Cambiar tema" title="Cambiar modo claro/oscuro" onClick={() => setDark((d) => { const next = !d; void callBridge('set_ui_theme', next ? 'dark' : 'light'); return next; })} className="p-1.5 rounded-lg border border-slate-200/80 dark:border-slate-800 bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300">
              {dark ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
            </button>
          </div>
        </div>
      </header>
      <main className="flex-1 w-full max-w-[1600px] mx-auto px-4 py-2.5 lg:h-[calc(100vh-3rem)] lg:overflow-hidden flex flex-col min-h-0">
        {tab === 'studio' ? (
          <StudioView
            clubs={clubs}
            onClubsUpdated={setClubs}
            exportDir={exportDir}
            exportPureDir={exportPureDir}
            facepackDir={facepackDir}
            facepackPureDir={facepackPureDir}
            exportVariant={exportVariant}
            fmGraphicsCollision={fmGraphicsCollision}
            fmFacepackCollision={fmFacepackCollision}
            onExportDirChange={(dir, sh, fmCol) => {
              setExportDir(dir);
              if (sh) setStorageHealth(sh);
              if (typeof fmCol === 'boolean') setFmGraphicsCollision(fmCol);
            }}
            onExportPureDirChange={(dir, sh, fmCol) => {
              setExportPureDir(dir);
              if (sh) setStorageHealth(sh);
              if (typeof fmCol === 'boolean') setFmGraphicsCollision(fmCol);
            }}
            onFacepackDirChange={(dir, fmFpCol) => {
              setFacepackDir(dir);
              if (typeof fmFpCol === 'boolean') setFmFacepackCollision(fmFpCol);
            }}
            onFacepackPureDirChange={(dir, fmFpCol) => {
              setFacepackPureDir(dir);
              if (typeof fmFpCol === 'boolean') setFmFacepackCollision(fmFpCol);
            }}
            onExportVariantChange={handleExportVariantChange}
            initialJump={studioJump}
            onConsumeJump={() => setStudioJump(null)}
            toolTab={studioToolTab}
            onToolTabChange={setStudioToolTab}
            onTemplatesCountChange={setTemplatesCount}
            hideInternalToolbar
            initialHotkeyEnabled={captureHotkey}
            externalCaptureReq={externalCaptureReq}
          />
        ) : (
          <RegensSyncView
            clubs={clubs}
            vaultDir={vaultDir}
            exportDir={exportDir}
            exportPureDir={exportPureDir}
            exportVariant={exportVariant}
            fmGraphicsCollision={fmGraphicsCollision}
            storageHealth={storageHealth}
            liveWatch={liveWatching}
            onLiveWatchChange={setLiveWatching}
            onVaultChange={setVaultDir}
            onExportChange={(dir, sh, fmCol) => {
              setExportDir(dir);
              if (sh) setStorageHealth(sh);
              if (typeof fmCol === 'boolean') setFmGraphicsCollision(fmCol);
            }}
            onExportPureChange={(dir, sh, fmCol) => {
              setExportPureDir(dir);
              if (sh) setStorageHealth(sh);
              if (typeof fmCol === 'boolean') setFmGraphicsCollision(fmCol);
            }}
            onExportVariantChange={handleExportVariantChange}
            onJumpToStudio={(payload) => { setStudioJump(payload); setStudioToolTab('composer'); setTab('studio'); }}
          />
        )}
      </main>
      {modal === 'faq' && <FaqModal onClose={() => setModal(null)} />}
      {modal === 'about' && <AboutModal onClose={() => setModal(null)} onOpenGraph={() => setModal('graph')} />}
      {modal === 'graph' && (
        <GraphErrorBoundary onClose={() => setModal(null)}>
          <Suspense
            fallback={
              <div className="fixed inset-0 z-50 bg-slate-950/70 flex items-center justify-center p-4 text-xs text-white">
                Cargando Topología TecnoRed y Salud del Sistema…
              </div>
            }
          >
            <AppArchitectureGraph onClose={() => setModal(null)} />
          </Suspense>
        </GraphErrorBoundary>
      )}
    </div>
  );
}
