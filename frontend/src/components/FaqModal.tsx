import { useEffect, useMemo, useState } from 'react';
import { ChevronDown, ChevronRight, HelpCircle, Search, X } from 'lucide-react';
import faqMarkdown from '../../../docs/FAQ.md?raw';

export interface FAQItem { id: string; question: string; bullets: string[]; }
export interface FAQSection { id: string; title: string; items: FAQItem[]; }

const cleanMd = (s: string) => s.replace(/\*+|`+/g, '').trim();

function parseFaqMarkdown(raw: string): FAQSection[] {
  const sections: FAQSection[] = [];
  let curSec: FAQSection | null = null;
  let curItem: FAQItem | null = null;
  let idx = 0;
  for (const rawLine of raw.split(/\r?\n/)) {
    const line = rawLine.trim();
    const secMatch = /^##\s+(\d+)\.\s+(.+)$/.exec(line);
    if (secMatch) {
      curSec = { id: `sec-${secMatch[1]}`, title: cleanMd(secMatch[2]), items: [] };
      sections.push(curSec);
      curItem = null;
    } else if (curSec && line.startsWith('### ')) {
      curItem = { id: `faq-${idx++}`, question: cleanMd(line.slice(4)), bullets: [] };
      curSec.items.push(curItem);
    } else if (curItem && line.startsWith('* ')) {
      curItem.bullets.push(cleanMd(line.slice(2)));
    }
  }
  return sections;
}

const SECTIONS = parseFaqMarkdown(faqMarkdown);

export default function FaqModal({ onClose }: { onClose: () => void }) {
  const [query, setQuery] = useState('');
  const [activeSec, setActiveSec] = useState<string>('all');
  const [openIds, setOpenIds] = useState<Record<string, boolean>>({ 'faq-0': true, 'faq-4': true });

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const qNorm = query.trim().toLowerCase();
  const filtered = useMemo(() => {
    return SECTIONS.filter((s) => activeSec === 'all' || s.id === activeSec)
      .map((s) => ({
        ...s,
        items: s.items.filter((it) => !qNorm || it.question.toLowerCase().includes(qNorm) || it.bullets.some((b) => b.toLowerCase().includes(qNorm))),
      }))
      .filter((s) => s.items.length > 0);
  }, [activeSec, qNorm]);

  const allItemIds = SECTIONS.flatMap((s) => s.items.map((i) => i.id));
  const setAllOpen = (val: boolean) => setOpenIds(Object.fromEntries(allItemIds.map((id) => [id, val])));

  return (
    <div onClick={(e) => { if (e.target === e.currentTarget) onClose(); }} className="fixed inset-0 z-50 bg-slate-950/60 flex items-center justify-center p-4" role="dialog" aria-modal="true">
      <div className="w-full max-w-5xl max-h-[86vh] rounded-xl shadow-xl border border-slate-200/80 dark:border-slate-800 bg-white dark:bg-slate-900 text-slate-900 dark:text-white flex flex-col overflow-hidden">
        <div className="px-5 py-3.5 border-b border-slate-200 dark:border-slate-800 flex items-center justify-between gap-2">
          <div className="flex items-center gap-2 font-semibold text-sm">
            <HelpCircle className="w-4 h-4 text-emerald-600 dark:text-emerald-400" /> Centro de Ayuda &amp; FAQ
          </div>
          <div className="flex items-center gap-2 text-xs">
            <button type="button" onClick={() => setAllOpen(true)} className="px-2.5 py-1 rounded bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300">Expandir todo</button>
            <button type="button" onClick={() => setAllOpen(false)} className="px-2.5 py-1 rounded bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300">Colapsar todo</button>
            <button type="button" aria-label="Cerrar ayuda" onClick={onClose} className="p-1.5 rounded bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300"><X className="w-4 h-4" /></button>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto grid grid-cols-1 md:grid-cols-12">
          <aside className="md:col-span-4 p-4 border-b md:border-b-0 md:border-r border-slate-200 dark:border-slate-800 space-y-3 bg-slate-50/70 dark:bg-slate-900/40">
            <div className="relative">
              <Search className="w-3.5 h-3.5 absolute left-3 top-2.5 text-slate-400" />
              <input aria-label="Buscar en preguntas frecuentes" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Buscar dudas, atajos o funciones..." className="w-full pl-8 pr-3 py-2 text-xs rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-100" />
            </div>
            <div className="flex flex-wrap md:flex-col gap-1.5 text-xs">
              <button type="button" onClick={() => setActiveSec('all')} className={`min-h-[44px] px-3 py-2 rounded-lg text-left font-medium ${activeSec === 'all' ? 'bg-emerald-600 text-white' : 'bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-300'}`}>Todas las secciones ({allItemIds.length})</button>
              {SECTIONS.map((s) => (
                <button key={s.id} type="button" onClick={() => setActiveSec(s.id)} className={`min-h-[44px] px-3 py-2 rounded-lg text-left font-medium ${activeSec === s.id ? 'bg-emerald-600 text-white' : 'bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-300'}`}>
                  {s.title} ({s.items.length})
                </button>
              ))}
            </div>
          </aside>

          <div className="md:col-span-8 p-5 space-y-5 max-w-3xl">
            {filtered.length === 0 ? (
              <div className="py-10 text-center space-y-2 text-xs text-slate-600 dark:text-slate-400">
                <p>Sin coincidencias para <strong className="text-slate-900 dark:text-white">“{query}”</strong>.</p>
                <button type="button" onClick={() => { setQuery(''); setActiveSec('all'); }} className="px-3 py-1.5 rounded-lg bg-slate-100 dark:bg-slate-800 text-slate-800 dark:text-slate-200 font-medium">Limpiar búsqueda</button>
              </div>
            ) : filtered.map((sec) => (
              <div key={sec.id} className="space-y-2">
                <h3 className="text-xs font-semibold uppercase tracking-wider text-emerald-700 dark:text-emerald-400">{sec.title}</h3>
                <div className="divide-y divide-slate-200 dark:divide-slate-800 border border-slate-200 dark:border-slate-800 rounded-lg">
                  {sec.items.map((it) => {
                    const isOpen = Boolean(qNorm) || Boolean(openIds[it.id]);
                    return (
                      <div key={it.id} className="p-3.5 text-xs">
                        <button type="button" aria-expanded={isOpen} onClick={() => setOpenIds((p) => ({ ...p, [it.id]: !isOpen }))} className="w-full min-h-[44px] flex items-center justify-between gap-2 text-left font-semibold text-slate-900 dark:text-white">
                          <span>{it.question}</span>
                          <span className="inline-flex items-center gap-1.5 shrink-0">
                            {isOpen ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
                          </span>
                        </button>
                        {isOpen && (
                          <ul className="mt-2 space-y-1.5 pl-4 list-disc text-slate-600 dark:text-slate-300 leading-relaxed">
                            {it.bullets.map((b, i) => <li key={i}>{b}</li>)}
                          </ul>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
