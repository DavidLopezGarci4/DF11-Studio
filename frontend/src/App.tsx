import { Suspense, lazy, useCallback, useEffect, useRef, useState } from 'react';
import { HelpCircle, Info, Moon, Sun } from 'lucide-react';
import AboutModal from './components/AboutModal';
import FaqModal from './components/FaqModal';
import RegensSyncView from './components/RegensSyncView';
import StudioView, { StudioJumpPayload } from './components/StudioView';
import { BootstrapState, ClubSeed, StorageHealth, callBridge } from './lib/ipc';

const AppArchitectureGraph = lazy(() => import('./components/AppArchitectureGraph'));

export default function App() {
  const hadStoredTheme = useRef(localStorage.getItem('df11_theme') !== null);
  const [dark, setDark] = useState(() => localStorage.getItem('df11_theme') !== 'light');
  const [tab, setTab] = useState<'studio' | 'sync'>('studio');
  const [modal, setModal] = useState<'faq' | 'about' | 'graph' | null>(null);
  const [boot, setBoot] = useState<BootstrapState | null>(null);
  const [clubs, setClubs] = useState<Record<string, ClubSeed>>({});
  const [vaultDir, setVaultDir] = useState('D:\\DF11Studio\\NG_Regens_Vault');
  const [exportDir, setExportDir] = useState('D:\\DF11Studio\\Exports\\000_DF11_Regens_Override');
  const [facepackDir, setFacepackDir] = useState('');
  const [storageHealth, setStorageHealth] = useState<StorageHealth | null>(null);
  const [liveWatching, setLiveWatching] = useState(false);
  const [studioJump, setStudioJump] = useState<StudioJumpPayload | null>(null);

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
        if (typeof b.facepackDir === 'string') setFacepackDir(b.facepackDir);
        if (b.storageHealth) setStorageHealth(b.storageHealth);
        if (typeof b.liveWatching === 'boolean') setLiveWatching(b.liveWatching);
        if (!hadStoredTheme.current && (b.theme === 'light' || b.theme === 'dark')) {
          setDark(b.theme === 'dark');
        }
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    loadBootstrap();
    window.addEventListener('pywebviewready', loadBootstrap);
    return () => window.removeEventListener('pywebviewready', loadBootstrap);
  }, [loadBootstrap]);

  const navBtn = (active: boolean) => `px-3 py-1 text-xs font-medium rounded-md transition ${active ? 'bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-100 shadow-xs' : 'text-slate-600 dark:text-slate-400'}`;

  return (
    <div className="min-h-screen flex flex-col bg-slate-50 text-slate-900 dark:bg-[#090d16] dark:text-white">
      <header className="sticky top-0 z-30 h-14 px-5 border-b border-slate-200/80 dark:border-slate-800 bg-white/90 dark:bg-[#090d16]/90 backdrop-blur-md flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <img src="./icon-128.png" alt="Logo DF11 Face Studio" className="w-7 h-7 rounded-md" />
          <span className="font-semibold tracking-tight text-sm text-slate-900 dark:text-white">DF11 Face Studio</span>
          <span className="text-xs px-2 py-0.5 rounded-full border bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-500/10 dark:text-emerald-400 dark:border-emerald-500/20 tabular-nums">v{boot?.version ?? '1.3.0'}</span>
        </div>
        <nav className="flex items-center gap-1 p-1 rounded-lg bg-slate-100 dark:bg-slate-950 border border-slate-200/80 dark:border-slate-800">
          <button type="button" onClick={() => setTab('studio')} className={navBtn(tab === 'studio')}>Estudio</button>
          <button type="button" onClick={() => setTab('sync')} className={navBtn(tab === 'sync')}>Sincronizador NG_Regens</button>
        </nav>
        <div className="flex items-center gap-1.5">
          <button type="button" aria-label="Centro de ayuda y FAQ" title="Ayuda y FAQ" onClick={() => setModal('faq')} className="p-2 rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300">
            <HelpCircle className="w-4 h-4" />
          </button>
          <button type="button" aria-label="Acerca de DF11 Face Studio" title="Acerca de" onClick={() => setModal('about')} className="p-2 rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300">
            <Info className="w-4 h-4" />
          </button>
          <button type="button" aria-label="Cambiar tema" title="Cambiar modo claro/oscuro" onClick={() => setDark((d) => { const next = !d; void callBridge('set_ui_theme', next ? 'dark' : 'light'); return next; })} className="p-2 rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300">
            {dark ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
          </button>
        </div>
      </header>
      <main className="flex-1 p-5 max-w-6xl w-full mx-auto">
        {tab === 'studio' ? (
          <StudioView
            clubs={clubs}
            onClubsUpdated={setClubs}
            exportDir={exportDir}
            facepackDir={facepackDir}
            onExportDirChange={(dir, sh) => { setExportDir(dir); if (sh) setStorageHealth(sh); }}
            onFacepackDirChange={setFacepackDir}
            initialJump={studioJump}
            onConsumeJump={() => setStudioJump(null)}
          />
        ) : (
          <RegensSyncView
            clubs={clubs}
            vaultDir={vaultDir}
            exportDir={exportDir}
            storageHealth={storageHealth}
            liveWatch={liveWatching}
            onLiveWatchChange={setLiveWatching}
            onVaultChange={setVaultDir}
            onExportChange={(dir, sh) => { setExportDir(dir); if (sh) setStorageHealth(sh); }}
            onJumpToStudio={(payload) => { setStudioJump(payload); setTab('studio'); }}
          />
        )}
      </main>
      {modal === 'faq' && <FaqModal onClose={() => setModal(null)} />}
      {modal === 'about' && <AboutModal onClose={() => setModal(null)} onOpenGraph={() => setModal('graph')} />}
      <Suspense fallback={null}>
        {modal === 'graph' && <AppArchitectureGraph onClose={() => setModal(null)} />}
      </Suspense>
    </div>
  );
}
