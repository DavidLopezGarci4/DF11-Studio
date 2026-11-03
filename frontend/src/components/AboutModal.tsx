import { useEffect } from 'react';
import { ChevronDown, Cpu, ShieldCheck, Sparkles, X } from 'lucide-react';
import userChangelog from '../config/changelog.user.json';

interface Props {
  onClose: () => void;
  onOpenGraph: () => void;
}

function renderHumanHighlight(line: string) {
  const parts = line.split('**');
  if (parts.length >= 3) {
    return (
      <span>
        {parts[0]}<strong className="font-semibold text-slate-900 dark:text-slate-100">{parts[1]}</strong>{parts.slice(2).join('**')}
      </span>
    );
  }
  return <span>{line}</span>;
}

export default function AboutModal({ onClose, onOpenGraph }: Props) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const latest = userChangelog.versions[0];
  const older = userChangelog.versions.slice(1);

  return (
    <div onClick={(e) => { if (e.target === e.currentTarget) onClose(); }} className="fixed inset-0 z-50 bg-slate-950/60 flex items-center justify-center p-4" role="dialog" aria-modal="true">
      <div className="w-full max-w-xl max-h-[88vh] rounded-xl shadow-xl border border-slate-200/80 dark:border-slate-800 bg-white dark:bg-slate-900 text-slate-900 dark:text-white divide-y divide-slate-200/80 dark:divide-slate-800 overflow-y-auto">
        <div className="p-5 flex items-start justify-between gap-4">
          <div className="flex items-center gap-3.5">
            <img src="./icon-128.png" alt="Logo DF11 Face Studio" className="w-12 h-12 rounded-xl border border-slate-200/80 dark:border-slate-800" />
            <div>
              <h2 className="font-semibold text-base text-slate-900 dark:text-white">{userChangelog.appName}</h2>
              <p className="text-xs text-slate-600 dark:text-slate-400 mt-0.5">{userChangelog.appDescription}</p>
              <div className="flex flex-wrap items-center gap-1.5 mt-2 text-[11px] tabular-nums">
                <span className="px-2 py-0.5 rounded-full border bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-500/10 dark:text-emerald-400 dark:border-emerald-500/20 font-medium">v{userChangelog.currentVersion}</span>
                <span className="px-2 py-0.5 rounded-full bg-slate-100 dark:bg-slate-950 text-slate-700 dark:text-slate-300">Build {userChangelog.buildNumber}</span>
                <span className="px-2 py-0.5 rounded-full bg-slate-100 dark:bg-slate-950 text-slate-700 dark:text-slate-300">Windows PC</span>
                <span className="px-2 py-0.5 rounded-full border bg-blue-50 text-blue-700 border-blue-200 dark:bg-blue-500/10 dark:text-blue-400 dark:border-blue-500/20 inline-flex items-center gap-1"><ShieldCheck className="w-3 h-3" /> 100% Local · 0 €</span>
              </div>
            </div>
          </div>
          <button type="button" aria-label="Cerrar acerca de" onClick={onClose} className="p-1.5 rounded bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300"><X className="w-4 h-4" /></button>
        </div>

        <div className="p-5 space-y-3 bg-emerald-500/[0.04] dark:bg-emerald-500/[0.06]">
          <div className="flex items-center justify-between text-xs">
            <span className="font-semibold text-emerald-700 dark:text-emerald-400 inline-flex items-center gap-1.5"><Sparkles className="w-3.5 h-3.5" /> Novedades de la versión v{latest.version}</span>
            <span className="text-slate-500 dark:text-slate-400 tabular-nums">{latest.date}</span>
          </div>
          <p className="text-xs font-medium text-slate-800 dark:text-slate-200">{latest.title}</p>
          <ul className="space-y-2 text-xs text-slate-600 dark:text-slate-300 leading-relaxed">
            {latest.highlights.map((h, idx) => <li key={idx}>{renderHumanHighlight(h)}</li>)}
          </ul>
        </div>

        {older.length > 0 && (
          <details className="group p-4 text-xs">
            <summary className="cursor-pointer list-none flex items-center justify-between font-medium text-slate-700 dark:text-slate-300">
              <span>Historial de versiones anteriores ({older.length})</span>
              <ChevronDown className="w-4 h-4 transition group-open:rotate-180" />
            </summary>
            <div className="mt-3 space-y-3 pt-2 border-t border-slate-200/70 dark:border-slate-800">
              {older.map((ver) => (
                <div key={ver.version} className="space-y-1.5">
                  <div className="flex items-center justify-between font-medium text-slate-800 dark:text-slate-200">
                    <span>v{ver.version} — {ver.title}</span>
                    <span className="text-slate-500 tabular-nums">{ver.date}</span>
                  </div>
                  <ul className="space-y-1 text-slate-600 dark:text-slate-400">
                    {ver.highlights.map((h, i) => <li key={i}>{renderHumanHighlight(h)}</li>)}
                  </ul>
                </div>
              ))}
            </div>
          </details>
        )}

        <div className="p-4 flex flex-wrap items-center justify-between gap-3 text-xs">
          <p className="text-slate-500 dark:text-slate-400 max-w-xs">{userChangelog.privacyPolicy}</p>
          <button
            type="button"
            onClick={onOpenGraph}
            className="px-3 py-2 rounded-lg bg-slate-900 dark:bg-slate-100 text-white dark:text-slate-900 font-medium inline-flex items-center gap-1.5"
          >
            <Cpu className="w-3.5 h-3.5" /> Inspeccionar Salud de la Arquitectura
          </button>
        </div>
      </div>
    </div>
  );
}
