import { useEffect, useState } from 'react';
import { Moon, Sun } from 'lucide-react';
import StudioView, { StudioJumpPayload } from './components/StudioView';
import { BootstrapState, callBridge } from './lib/ipc';

export default function App() {
  const [dark, setDark] = useState(() => localStorage.getItem('df11_theme') !== 'light');
  const [tab, setTab] = useState<'studio' | 'sync'>('studio');
  const [boot, setBoot] = useState<BootstrapState | null>(null);
  const [exportDir, setExportDir] = useState('D:\\DF11Studio\\Exports\\000_DF11_Regens_Override');
  const [studioJump, setStudioJump] = useState<StudioJumpPayload | null>(null);

  useEffect(() => {
    document.documentElement.classList.toggle('dark', dark);
    localStorage.setItem('df11_theme', dark ? 'dark' : 'light');
  }, [dark]);

  useEffect(() => {
    callBridge<BootstrapState>('get_bootstrap_state').then((b) => {
      setBoot(b);
      if (b?.exportDir) setExportDir(b.exportDir);
    });
  }, []);

  const navBtn = (active: boolean) => `px-3 py-1 text-xs font-medium rounded-md transition ${active ? 'bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-100 shadow-xs' : 'text-slate-600 dark:text-slate-400'}`;

  return (
    <div className="min-h-screen flex flex-col bg-slate-50 text-slate-900 dark:bg-[#090d16] dark:text-slate-100">
      <header className="h-14 px-5 border-b border-slate-200/80 dark:border-slate-800/80 bg-white dark:bg-[#111827] flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="font-semibold tracking-tight text-sm">DF11 Face Studio</span>
          <span className="text-xs px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 tabular-nums">v{boot?.version ?? '1.0.0'}</span>
        </div>
        <nav className="flex items-center gap-1 p-1 rounded-lg bg-slate-100 dark:bg-slate-800/80">
          <button type="button" onClick={() => setTab('studio')} className={navBtn(tab === 'studio')}>Estudio</button>
          <button type="button" onClick={() => setTab('sync')} className={navBtn(tab === 'sync')}>Sincronizador NG_Regens</button>
        </nav>
        <button type="button" aria-label="Cambiar tema" onClick={() => setDark((d) => !d)} className="p-2 rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300">
          {dark ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
        </button>
      </header>
      <main className="flex-1 p-5 max-w-6xl w-full mx-auto">
        {tab === 'studio' ? (
          <StudioView clubs={boot?.clubs ?? {}} exportDir={exportDir} onExportDirChange={setExportDir} initialJump={studioJump} />
        ) : (
          <p className="text-sm text-slate-600 dark:text-slate-400" data-jump={Boolean(setStudioJump)}>Sincronizador NG_Regens listo.</p>
        )}
      </main>
    </div>
  );
}
