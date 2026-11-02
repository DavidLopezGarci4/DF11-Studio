import { useEffect } from 'react';
import { Cpu, ShieldCheck, Sparkles, X } from 'lucide-react';
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

  return (
    <div className="fixed inset-0 z-50 bg-slate-950/60 flex items-center justify-center p-4" role="dialog" aria-modal="true">
      <div className="w-full max-w-xl rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-[#111827] text-slate-900 dark:text-slate-100 divide-y divide-slate-200 dark:divide-slate-800 overflow-hidden">
        <div className="p-5 flex items-start justify-between gap-4">
          <div className="flex items-center gap-3.5">
            <img src="./icon-128.png" alt="Logo DF11 Face Studio" className="w-12 h-12 rounded-xl border border-slate-200 dark:border-slate-700" />
            <div>
              <h2 className="font-semibold text-base">{userChangelog.appName}</h2>
              <p className="text-xs text-slate-600 dark:text-slate-400 mt-0.5">{userChangelog.appDescription}</p>
              <div className="flex flex-wrap items-center gap-1.5 mt-2 text-[11px] tabular-nums">
                <span className="px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 font-medium">v{userChangelog.currentVersion}</span>
                <span className="px-2 py-0.5 rounded-full bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300">Build {userChangelog.buildNumber}</span>
                <span className="px-2 py-0.5 rounded-full bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300">Windows PC</span>
                <span className="px-2 py-0.5 rounded-full bg-sky-500/10 text-sky-700 dark:text-sky-400 inline-flex items-center gap-1"><ShieldCheck className="w-3 h-3" /> 100% Local · 0 €</span>
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
